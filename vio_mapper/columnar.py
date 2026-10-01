"""Build and load immutable, explicitly-described Parquet execution datasets."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd

from .config import ALGORITHM_VERSION, column, decision_columns
from .normalization import model_year, normalized_text, numeric_value
from .semantic import sha256_file
from .sources import load_source, prepare_reference, read_delimited

EXECUTION_SCHEMA_VERSION = 2
ZIP_CHUNK_SIZE = 250_000


def _require_parquet() -> None:
    try:
        import pyarrow  # noqa: F401
    except ImportError as exc:
        raise RuntimeError('Columnar execution requires the pyarrow dependency') from exc


def _read_source(path: Path) -> pd.DataFrame:
    if path.suffix.lower() != '.zip':
        return load_source(path)
    with zipfile.ZipFile(path) as archive:
        members = sorted(name for name in archive.namelist()
                         if Path(name).suffix.lower() in ('.csv', '.txt', '.tsv'))
        if len(members) != 1:
            raise ValueError('Source ZIP must contain exactly one CSV, TXT or TSV member')
        member = members[0]
        with archive.open(member) as handle:
            separator = '\t' if Path(member).suffix.lower() == '.tsv' else ','
            frame = pd.read_csv(handle, sep=separator, dtype=str, keep_default_na=False,
                                na_values=[], skipinitialspace=False).replace('', pd.NA)
        identifier = column('id')
        if identifier not in frame:
            # The published full register has no vehicle key.  This is the
            # established benchmark convention documented in performance.md.
            frame.insert(0, identifier, range(1, len(frame) + 1))
        frame['source_sheet'] = member
        frame['source_excel_row'] = range(2, len(frame) + 2)
        frame['source_key'] = [f'{member}!{row}' for row in frame.source_excel_row]
        from .sources import prepare_source
        return prepare_source(frame)


def _project_source(source: pd.DataFrame) -> pd.DataFrame:
    # Decision fields plus the raw identifier and provenance are the complete
    # inputs needed to reproduce a decision and trace it to the archive.
    names = list(dict.fromkeys((column('id'), *decision_columns(), 'source_key',
                                'source_sheet', 'source_excel_row', 'provided_kType',
                                'provided_label_conflict', 'duplicate_of',
                                'duplicate_id_conflict', 'canonical_record')))
    projected = source.reindex(columns=names).copy()
    projected.insert(0, 'source_ordinal', pd.array(range(len(projected)), dtype='int64'))
    projected['_make'] = source[column('make')].map(normalized_text)
    projected['_model'] = source[column('model')].map(normalized_text)
    projected['_year'] = pd.array(source[column('year')].map(model_year), dtype='Int64')
    for role in ('displacement', 'power'):
        name = column(role)
        if name in projected:
            projected[f'_numeric_{role}'] = projected[name].map(numeric_value).astype('Float64')
    return projected


def _parquet_schema_manifest(path: Path) -> dict[str, str]:
    import pyarrow.parquet as parquet
    schema = parquet.read_schema(path)
    return {field.name: str(field.type) for field in schema}


def _check_source_ordinals(path: Path, expected_rows: int) -> None:
    import numpy as np
    import pyarrow.parquet as parquet

    next_ordinal = 0
    for batch in parquet.ParquetFile(path).iter_batches(
            columns=['source_ordinal'], batch_size=250_000):
        values = batch.column(0).to_numpy(zero_copy_only=False)
        if not np.array_equal(values, np.arange(
                next_ordinal, next_ordinal + len(values), dtype=np.int64)):
            raise ValueError('Execution source ordinals are not archive-wide and contiguous')
        next_ordinal += len(values)
    if next_ordinal != expected_rows:
        raise ValueError('Execution source row count changed during preparation')


def _parquet_safe(frame: pd.DataFrame) -> pd.DataFrame:
    """Give every formerly-object column one explicit nullable scalar type.

    Excel commonly mixes numeric and textual engine numbers in one column.
    Arrow correctly refuses to guess a type for that; these are identifiers,
    not quantities, so their lossless execution representation is text.
    """
    frame = frame.copy()
    for name in frame.select_dtypes(include=['object', 'string']):
        frame[name] = frame[name].map(
            lambda value: pd.NA if value is None or pd.isna(value) else str(value)
        ).astype('string')
    return frame


def _projected_zip_source(path: Path, output: Path) -> tuple[int, int]:
    """Project the official ID-less register to Parquet without materializing it."""
    import pyarrow as arrow
    import pyarrow.parquet as parquet

    with zipfile.ZipFile(path) as archive:
        members = sorted(name for name in archive.namelist()
                         if Path(name).suffix.lower() in ('.csv', '.txt', '.tsv'))
        if len(members) != 1:
            raise ValueError('Source ZIP must contain exactly one CSV, TXT or TSV member')
        member = members[0]
        separator = '\t' if Path(member).suffix.lower() == '.tsv' else ','
        with archive.open(member) as handle:
            header = pd.read_csv(handle, sep=separator, nrows=0).columns
        identifier = column('id')
        # Existing IDs require a true global duplicate pass. The official
        # capacity input is ID-less; retain the general loader for other ZIPs.
        if identifier in header:
            frame = _parquet_safe(_project_source(_read_source(path)))
            frame.to_parquet(output, index=False, engine='pyarrow', compression='zstd',
                             use_dictionary=True)
            return len(frame), int(frame.memory_usage(deep=True).sum())

        wanted = list(dict.fromkeys((*decision_columns(),)))
        missing = set(name for name in wanted if name is not None) - set(header)
        # Optional decision/identifier columns may legitimately be absent; the
        # required role check remains strict.
        from .config import required_source_columns
        required_without_id = set(required_source_columns()) - {identifier}
        required_missing = required_without_id - set(header)
        if required_missing:
            raise ValueError(f'{member}: missing required columns {sorted(required_missing)}')
        usecols = [name for name in wanted if name in header]
        writer = None
        rows = projected_bytes = 0
        try:
            with archive.open(member) as handle:
                chunks = pd.read_csv(
                    handle, sep=separator, usecols=usecols, chunksize=ZIP_CHUNK_SIZE,
                    dtype=str, keep_default_na=False, na_values=[], low_memory=False)
                for chunk in chunks:
                    chunk = chunk.replace('', pd.NA).reset_index(drop=True)
                    count = len(chunk)
                    chunk.insert(0, identifier, range(rows + 1, rows + count + 1))
                    chunk['source_sheet'] = member
                    chunk['source_excel_row'] = range(rows + 2, rows + count + 2)
                    chunk['source_key'] = [f'{member}!{row}' for row in chunk.source_excel_row]
                    chunk['provided_kType'] = pd.NA
                    chunk['provided_label_conflict'] = False
                    chunk['duplicate_of'] = ''
                    chunk['duplicate_id_conflict'] = False
                    chunk['canonical_record'] = True
                    projected = _parquet_safe(_project_source(chunk))
                    # _project_source starts at zero for each frame. ZIP intake
                    # is chunked, so persist the archive-wide ordinal instead.
                    projected['source_ordinal'] = pd.array(
                        range(rows, rows + count), dtype='int64')
                    projected_bytes += int(projected.memory_usage(deep=True).sum())
                    table = arrow.Table.from_pandas(projected, preserve_index=False)
                    if writer is None:
                        writer = parquet.ParquetWriter(
                            output, table.schema, compression='zstd', use_dictionary=True)
                    writer.write_table(table)
                    rows += count
        finally:
            if writer is not None:
                writer.close()
        if not rows:
            raise ValueError('Government data contains no vehicle rows')
        return rows, projected_bytes


def prepare_execution_dataset(source_path: Path | str, reference_path: Path | str,
                              output_dir: Path | str) -> dict:
    """Convert source and reference once, with provenance and drift detection."""
    _require_parquet()
    source_path, reference_path, output_dir = (Path(source_path), Path(reference_path),
                                               Path(output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / 'manifest.json'
    source_hash, reference_hash = sha256_file(source_path), sha256_file(reference_path)
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text())
        same_inputs = (existing.get('schema_version') == EXECUTION_SCHEMA_VERSION
                       and existing.get('algorithm_version') == ALGORITHM_VERSION
                       and existing.get('source', {}).get('sha256') == source_hash
                       and existing.get('reference', {}).get('sha256') == reference_hash)
        if (same_inputs and (output_dir / 'source.parquet').exists()
                and (output_dir / 'reference.parquet').exists()):
            return existing
        raise ValueError('Execution dataset is immutable; choose a new output directory')
    if reference_path.suffix.lower() == '.parquet':
        raw_reference = pd.read_parquet(reference_path)
    elif reference_path.suffix.lower() in ('.csv', '.txt', '.tsv'):
        raw_reference = read_delimited(reference_path)
    else:
        raw_reference = pd.read_excel(reference_path, dtype=object)
    reference = _parquet_safe(prepare_reference(raw_reference))
    source_file, reference_file = output_dir / 'source.parquet', output_dir / 'reference.parquet'
    if source_path.suffix.lower() == '.zip':
        source_rows, projected_source_bytes = _projected_zip_source(source_path, source_file)
    else:
        source = _parquet_safe(_project_source(_read_source(source_path)))
        source.to_parquet(source_file, index=False, engine='pyarrow', compression='zstd',
                          use_dictionary=True)
        source_rows = len(source)
        projected_source_bytes = int(source.memory_usage(deep=True).sum())
    reference.to_parquet(reference_file, index=False, engine='pyarrow', compression='zstd',
                         use_dictionary=True)
    _check_source_ordinals(source_file, source_rows)
    manifest = {
        'schema_version': EXECUTION_SCHEMA_VERSION,
        'algorithm_version': ALGORITHM_VERSION,
        'source': {'path': str(source_path), 'sha256': source_hash,
                   'rows': source_rows, 'schema': _parquet_schema_manifest(source_file),
                   'projected_bytes': projected_source_bytes,
                   'parquet_bytes': source_file.stat().st_size},
        'reference': {'path': str(reference_path), 'sha256': reference_hash,
                      'rows': len(reference), 'schema': _parquet_schema_manifest(reference_file),
                      'projected_bytes': int(reference.memory_usage(deep=True).sum()),
                      'parquet_bytes': reference_file.stat().st_size},
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    return manifest


def load_execution_dataset(directory: Path | str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    _require_parquet()
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_text())
    if manifest.get('schema_version') != EXECUTION_SCHEMA_VERSION:
        raise ValueError('Unsupported execution-dataset schema version')
    source_path, reference_path = directory / 'source.parquet', directory / 'reference.parquet'
    for label, path in (('source', source_path), ('reference', reference_path)):
        actual = _parquet_schema_manifest(path)
        expected = manifest[label]['schema']
        if actual != expected:
            raise ValueError(f'{label} execution schema drift: {actual!r} != {expected!r}')
    source = pd.read_parquet(source_path, engine='pyarrow', dtype_backend='pyarrow')
    # The reference is small and prepare_reference deliberately uses pandas'
    # numeric modulo validation, which Arrow extension arrays do not implement.
    reference = pd.read_parquet(reference_path, engine='pyarrow')
    return source, reference, manifest
