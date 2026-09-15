"""Reading and validating the two catalogues.

Both loaders are strict on purpose. A malformed construction date or a
duplicated kType is a defect in the inputs, and continuing past it would turn a
data problem into a wrong assignment further down the pipeline.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import column, required_source_columns
from .normalization import construction_yyyymm, normalized_text, numeric_value

DELIMITED_SUFFIXES = ('.csv', '.txt', '.tsv')
REQUIRED_REFERENCE_COLUMNS = ('KType', 'Brand', 'Sales_designation',
                              'Construction_from', 'Construction_to', 'Engine_code')
# Bookkeeping added by this module; never part of a row's identity.
PROVENANCE_COLUMNS = frozenset({'source_key', 'source_sheet', 'source_excel_row',
                                'provided_kType', 'provided_label_agreement',
                                'provided_label_conflict',
                                'duplicate_of', 'duplicate_id_conflict', 'canonical_record'})


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
    separator = '\t' if path.suffix.lower() == '.tsv' else ','
    frame = pd.read_csv(path, sep=separator, dtype=str, keep_default_na=False, na_values=[],
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
    sheets = pd.read_excel(path, sheet_name=None, dtype=object,
                           keep_default_na=False, na_values=[])
    frames = []
    for sheet, data in sheets.items():
        if data.empty:
            continue
        require_columns(data, required_source_columns(), f'{path.name}/{sheet}')
        data = data.copy().replace('', pd.NA)
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
    identity_columns = [name for name in data if name not in PROVENANCE_COLUMNS]
    normalized_id = data[column('id')].map(normalized_text)
    # The ID already defines the group. Compare its normalized value, so harmless
    # whitespace/case differences do not manufacture a source conflict.
    comparable = data[identity_columns].copy()
    comparable[column('id')] = normalized_id
    # Grouped transforms do the same comparisons for all IDs in column-sized
    # operations. The former Python loop built and indexed a tiny DataFrame once
    # per distinct ID, which dominates ingestion when a register has hundreds of
    # thousands of mostly unique vehicles.
    variation = (comparable.fillna('')
                 .groupby(normalized_id, sort=False)
                 .transform('nunique', dropna=False)
                 .gt(1).any(axis=1))
    labels = data['provided_kType'].map(numeric_value)
    provided_label_conflict = (labels.groupby(normalized_id, sort=False)
                               .transform('nunique').gt(1))

    copies = normalized_id.duplicated(keep='first')
    first_source_key = data['source_key'].groupby(normalized_id, sort=False).transform('first')
    # Preserve the published provenance-column order while assigning the
    # vectorized results.
    data['duplicate_of'] = first_source_key.where(copies, '')
    data['duplicate_id_conflict'] = variation
    data['provided_label_conflict'] = provided_label_conflict
    data['canonical_record'] = ~copies
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
