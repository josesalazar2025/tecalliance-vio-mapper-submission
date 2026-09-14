"""Reading and validating the two catalogues.

Both loaders are strict on purpose. A malformed construction date or a
duplicated kType is a defect in the inputs, and continuing past it would turn a
data problem into a wrong assignment further down the pipeline.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import column, required_source_columns
from .normalization import construction_yyyymm, normalized_text

DELIMITED_SUFFIXES = ('.csv', '.txt', '.tsv')
REQUIRED_REFERENCE_COLUMNS = ('KType', 'Brand', 'Sales_designation',
                              'Construction_from', 'Construction_to')
# Bookkeeping added by this module; never part of a row's identity.
PROVENANCE_COLUMNS = frozenset({'source_key', 'source_sheet', 'source_excel_row'})


def require_columns(frame: pd.DataFrame, columns, name: str) -> None:
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f'{name}: missing required columns {sorted(missing)}')


def read_delimited(path: Path) -> pd.DataFrame:
    """Read a CSV without pandas' NA vocabulary corrupting legitimate values.

    By default pandas converts NA, N/A, NULL, None and NaN to missing. A source
    code, colour or model text of 'NA' would silently become missing data, which
    is exactly the kind of failure this pipeline must not have. Only genuinely
    empty cells are missing; everything else is kept verbatim as text and parsed
    by the same numeric/year helpers the Excel path uses.
    """
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[],
                        skipinitialspace=False)
    return frame.replace('', pd.NA)


def load_source(path: Path) -> pd.DataFrame:
    """Load the government file, whichever of the two supported shapes it is."""
    if path.suffix.lower() in DELIMITED_SUFFIXES:
        frame = read_delimited(path).assign(
            source_sheet=path.name,
            source_excel_row=lambda data: range(2, len(data) + 2),
            source_key=lambda data: [f'{path.name}!{row}' for row in data['source_excel_row']])
        return prepare_source(frame)
    return prepare_source(_concatenate_sheets(path))


def _concatenate_sheets(path: Path) -> pd.DataFrame:
    """Stack every non-empty worksheet, keeping each row's origin traceable."""
    sheets = pd.read_excel(path, sheet_name=None, dtype=object)
    frames = []
    for sheet, data in sheets.items():
        if data.empty:
            continue
        require_columns(data, required_source_columns(), f'{path.name}/{sheet}')
        data = data.copy()
        blank = [column for column in data
                 if str(column).startswith('Unnamed:') and data[column].isna().all()]
        data = data.drop(columns=blank)
        data['source_sheet'] = sheet
        data['source_excel_row'] = range(2, len(data) + 2)
        data['source_key'] = [f'{sheet}!{row}' for row in data['source_excel_row']]
        frames.append(data)
    if not frames:
        raise ValueError('Government workbook contains no vehicle rows')
    return pd.concat(frames, ignore_index=True)


def prepare_source(data: pd.DataFrame) -> pd.DataFrame:
    """Validate the government rows and resolve repeated vehicle IDs."""
    data = data.copy().reset_index(drop=True)
    require_columns(data, required_source_columns(), 'Government data')
    if data.empty:
        raise ValueError('Government data contains no vehicle rows')
    if 'source_key' not in data:
        data['source_key'] = [f'input!{index + 2}' for index in range(len(data))]
    if data['source_key'].duplicated().any():
        raise ValueError('Source row keys must be unique')
    if data[column('id')].map(normalized_text).eq('').any():
        raise ValueError('Government IDs must not be missing')
    if 'mapped kType' in data:
        data = data.rename(columns={'mapped kType': 'provided_kType'})
    if 'provided_kType' not in data:
        data['provided_kType'] = pd.NA
    return _mark_duplicate_ids(data)


def _mark_duplicate_ids(data: pd.DataFrame) -> pd.DataFrame:
    """Separate harmless repeated rows from genuinely contradictory ones.

    An identical copy of a row is one vehicle recorded twice: it is kept for the
    audit trail but counted once. Two rows sharing an ID with *different* values
    are a source defect, and neither may be assigned, since nothing in the file
    says which one describes the vehicle.
    """
    identity_columns = [column for column in data if column not in PROVENANCE_COLUMNS]
    data['duplicate_of'] = ''
    data['duplicate_id_conflict'] = False
    data['canonical_record'] = True
    for _, group in data.groupby(data[column('id')].map(normalized_text), sort=False):
        if len(group) < 2:
            continue
        # Exact source equality after null normalization, not VIN equality.
        if len(group[identity_columns].fillna('').drop_duplicates()) > 1:
            data.loc[group.index, 'duplicate_id_conflict'] = True
            data.loc[group.index, 'canonical_record'] = False
        else:
            copies = group.index[1:]
            data.loc[copies, 'canonical_record'] = False
            data.loc[copies, 'duplicate_of'] = data.at[group.index[0], 'source_key']
    return data


def prepare_reference(data: pd.DataFrame) -> pd.DataFrame:
    """Validate the RDM reference and derive its gating and interval columns."""
    data = data.copy().reset_index(drop=True)
    require_columns(data, REQUIRED_REFERENCE_COLUMNS, 'Reference')
    identifiers = pd.to_numeric(data['KType'], errors='coerce')
    if (identifiers.isna().any() or (identifiers <= 0).any()
            or (identifiers % 1 != 0).any() or identifiers.duplicated().any()):
        raise ValueError('Reference KType must be a unique positive integer')
    data['KType'] = identifiers.astype('int64')
    data['_make'] = data['Brand'].map(normalized_text)
    data['_model'] = data['Sales_designation'].map(normalized_text)
    if data[['_make', '_model']].eq('').any().any():
        raise ValueError('Reference make and model must not be missing')
    starts, ends = _production_intervals(data)
    data['_from'] = starts
    data['_to'] = pd.array(ends, dtype='Int64')
    return data.sort_values('KType').reset_index(drop=True)


def _production_intervals(data: pd.DataFrame) -> tuple[list[int], list[int | None]]:
    """Production start/end as plain years, naming the kType that fails."""
    starts: list[int] = []
    ends: list[int | None] = []
    for kind_type, raw_from, raw_to in zip(data['KType'], data['Construction_from'],
                                           data['Construction_to']):
        try:
            start = construction_yyyymm(raw_from)
            end = construction_yyyymm(raw_to, allow_open=True)
            if end is not None and start > end:
                raise ValueError('Construction start is after end')
        except ValueError as exc:
            raise ValueError(f'KType {kind_type}: {exc}') from exc
        starts.append(start // 100)
        ends.append(end // 100 if end else None)
    return starts, ends
