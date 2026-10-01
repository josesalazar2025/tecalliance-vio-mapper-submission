"""Deterministic semantic manifests for performance and equivalence gates."""
from __future__ import annotations

import hashlib
import json
import platform
import resource
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from .config import ALGORITHM_VERSION, MATCHED

SEMANTIC_RESULT_COLUMNS = ('ID', 'mapped kType', 'Match_Status',
                           'Review_Category', 'Match_Reason')


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def sha256_files(paths: Iterable[Path | str]) -> str:
    """Hash an ordered set of named files without ambiguous concatenation."""
    digest = hashlib.sha256()
    for raw_path in sorted((Path(path) for path in paths), key=lambda path: str(path)):
        digest.update(str(raw_path).encode())
        digest.update(b'\0')
        digest.update(sha256_file(raw_path).encode())
        digest.update(b'\n')
    return digest.hexdigest()


def _scalar(value):
    if value is None or pd.isna(value):
        return None
    if hasattr(value, 'item'):
        value = value.item()
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return value


def semantic_hash(frame: pd.DataFrame, columns: Iterable[str], *,
                  sort_by: Iterable[str] | None = None) -> str:
    """Hash values and multiplicity, independent of input order and file metadata."""
    columns = tuple(columns)
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f'Cannot hash missing semantic columns {sorted(missing)}')
    keys = tuple(sort_by or columns)
    ordered = frame.sort_values(list(keys), kind='stable', na_position='first')
    digest = hashlib.sha256()
    for values in ordered.loc[:, columns].itertuples(index=False, name=None):
        line = json.dumps([_scalar(value) for value in values], ensure_ascii=False,
                          sort_keys=True, separators=(',', ':'), default=str)
        digest.update(line.encode('utf-8'))
        digest.update(b'\n')
    return digest.hexdigest()


def _peak_rss_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == 'darwin' else peak * 1024)


def build_manifest(results: pd.DataFrame, evidence: pd.DataFrame, *,
                   source_path: Path | str, reference_path: Path | str,
                   rule_hash: str = '', code_hash: str = '', timings: dict | None = None,
                   metrics: dict | None = None, workers: int = 1) -> dict:
    """Build the Phase-0 correctness and resource manifest."""
    result_columns = [name for name in SEMANTIC_RESULT_COLUMNS if name in results]
    evidence_columns = sorted(name for name in evidence if name not in {'source_key', 'ID'})
    statuses = results['Match_Status'].value_counts(dropna=False).sort_index()
    accepted = (results.loc[results['Match_Status'].eq(MATCHED) & results['canonical_record']]
                ['mapped kType'].value_counts().sort_index())
    logical = int(pd.to_numeric(results.get('base_candidate_count', 0),
                                errors='coerce').fillna(0).sum())
    semantic_results = results.loc[:, result_columns].copy()
    if 'ID' in semantic_results:
        semantic_results['ID'] = semantic_results['ID'].map(
            lambda value: None if value is None or pd.isna(value) else str(value))
    return {
        'schema_version': 1,
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'algorithm_version': ALGORITHM_VERSION,
        'python': platform.python_version(),
        'pandas': pd.__version__,
        'source_sha256': sha256_file(source_path),
        'reference_sha256': sha256_file(reference_path),
        'rule_hash': rule_hash,
        'code_hash': code_hash,
        'rows': int(len(results)),
        'status_counts': {str(key): int(value) for key, value in statuses.items()},
        'accepted_ktype_counts': {str(int(key)): int(value)
                                  for key, value in accepted.items()},
        'logical_candidate_comparisons': logical,
        'result_semantic_sha256': semantic_hash(semantic_results, result_columns),
        'evidence_semantic_sha256': semantic_hash(evidence, evidence_columns)
                                    if evidence_columns else hashlib.sha256(b'').hexdigest(),
        'timings_seconds': timings or {},
        'metrics': metrics or {},
        'workers': workers,
        'peak_rss_bytes': _peak_rss_bytes(),
    }


def write_manifest(manifest: dict, path: Path | str) -> None:
    Path(path).write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')


def compare_manifests(baseline: dict, candidate: dict) -> list[str]:
    """Return exact acceptance-contract differences; an empty list means equal."""
    checked = ('source_sha256', 'reference_sha256', 'rows', 'status_counts',
               'accepted_ktype_counts', 'logical_candidate_comparisons',
               'result_semantic_sha256', 'evidence_semantic_sha256')
    return [f'{name}: {baseline.get(name)!r} != {candidate.get(name)!r}'
            for name in checked if baseline.get(name) != candidate.get(name)]
