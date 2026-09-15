"""Execute one default-policy mapping run for the web UI and keep its artefacts.

The run is the library's run: :func:`vio_mapper.pipeline.map_vehicles` with the
documented default :class:`~vio_mapper.config.Policy`, and the workbook written
by :func:`vio_mapper.reporting.write_workbook`. This module adds only the
plumbing a browser needs -- a temporary home for the upload, an id to fetch the
results back by, and a bound on how many runs are held at once.
"""
from __future__ import annotations

import shutil
import tempfile
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

import pandas as pd

from vio_mapper.cli import run_metadata
from vio_mapper.config import DEFAULT_REFERENCE_PATH, EXCEL_MAX_ROWS, Policy
from vio_mapper.pipeline import map_vehicles
from vio_mapper.reporting import build_sheets, performance_report, write_workbook
from vio_mapper.sources import load_source

from . import payload

SUPPORTED_SUFFIXES = ('.xlsx', '.xlsm', '.csv', '.txt', '.tsv')
# A demonstration holds its runs in memory so the presenter can flick back to an
# earlier one. Without a bound, an afternoon of runs would keep every frame
# alive; the oldest is discarded and its temporary directory removed with it.
MAX_RETAINED_RUNS = 8
# A live demo runs on a subset. Beyond this the honest answer is the CLI, which
# streams candidate evidence to disk instead of holding it in a browser payload.
MAX_SOURCE_ROWS = 20_000


class RunError(Exception):
    """An input the user can fix: a bad file, an unusable policy, a run too large."""


@dataclass
class Run:
    """One finished mapping run; its workbook is materialized on first download."""

    id: str
    source_name: str
    directory: Path
    results: pd.DataFrame
    evidence: pd.DataFrame
    workbook: Path
    report: str
    policy: Policy
    metadata: dict
    data: dict = field(default_factory=dict)
    workbook_lock: Lock = field(default_factory=Lock, repr=False)

    def dispose(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)


def ensure_workbook(run: Run) -> Path:
    """Build a run's workbook on first download, once even under concurrent requests."""
    with run.workbook_lock:
        if not run.workbook.exists():
            write_workbook(build_sheets(run.results, run.evidence, run.policy, run.metadata),
                           run.workbook)
    return run.workbook


class RunStore:
    """The retained runs, newest last, with the oldest evicted on overflow."""

    def __init__(self, limit: int = MAX_RETAINED_RUNS) -> None:
        self._runs: OrderedDict[str, Run] = OrderedDict()
        self._limit = limit
        self._lock = Lock()

    def add(self, run: Run) -> None:
        with self._lock:
            self._runs[run.id] = run
            while len(self._runs) > self._limit:
                _, evicted = self._runs.popitem(last=False)
                evicted.dispose()

    def get(self, run_id: str) -> Run | None:
        with self._lock:
            return self._runs.get(run_id)


def execute(upload_name: str, upload_bytes: bytes, policy: Policy, store: RunStore) -> Run:
    """Map one uploaded registry file against the authorized local reference."""
    suffix = Path(upload_name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise RunError(f'Unsupported file type {suffix or "(none)"}. '
                       f'Upload one of: {", ".join(SUPPORTED_SUFFIXES)}.')
    if not upload_bytes:
        raise RunError('The uploaded file is empty.')
    if not DEFAULT_REFERENCE_PATH.exists():
        raise RunError(f'Reference catalogue is missing at {DEFAULT_REFERENCE_PATH}.')

    directory = Path(tempfile.mkdtemp(prefix='vio-run-'))
    # Keep the uploaded name: run_metadata hashes inputs by file name, and an
    # audit trail that says 'tmp8f3a.xlsx' is not an audit trail.
    source_path = directory / Path(upload_name).name
    source_path.write_bytes(upload_bytes)

    started = time.perf_counter()
    try:
        source = load_source(source_path)
        if len(source) > MAX_SOURCE_ROWS:
            raise RunError(f'{len(source)} source rows exceed the {MAX_SOURCE_ROWS}-row limit of the '
                           'demonstration UI. Run the CLI, which streams candidate evidence to disk.')
        reference = pd.read_excel(DEFAULT_REFERENCE_PATH, dtype=object)
        results, evidence = map_vehicles(
            source, reference, policy, include_score_diagnostics=False)
        if len(evidence) >= EXCEL_MAX_ROWS:
            raise RunError(f'{len(evidence)} candidate-evidence rows exceed the worksheet limit; '
                           'narrow the evidence retention setting or use the CLI.')
        metadata = run_metadata(results, policy, source_path, DEFAULT_REFERENCE_PATH)
        report = performance_report(results, metadata)
        workbook = directory / f'mapped_{source_path.stem}.xlsx'
    except RunError:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    except ValueError as error:
        # The loaders are strict by design: a malformed date or a duplicated
        # kType is an input defect, and its message is the useful thing to show.
        shutil.rmtree(directory, ignore_errors=True)
        raise RunError(str(error)) from None
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    elapsed = time.perf_counter() - started

    run = Run(id=uuid.uuid4().hex[:12], source_name=Path(upload_name).name, directory=directory,
              results=results, evidence=evidence, workbook=workbook, report=report,
              policy=policy, metadata=metadata)
    run.data = {
        'run_id': run.id,
        'payload_version': payload.PAYLOAD_VERSION,
        'summary': payload.summary(results, evidence, metadata, run.source_name, elapsed),
        'results': payload.records(results, payload.table_columns()),
        'review': payload.review_brief(results, evidence),
        'audit': payload.audit(results, evidence, metadata, report),
        'rules': payload.rules(policy),
        'download_name': workbook.name,
    }
    store.add(run)
    return run


def row_detail(run: Run, source_key: str) -> dict:
    """Everything the run knows about one source row, for the detail drawer."""
    rows = run.results[run.results['source_key'] == source_key]
    if rows.empty:
        raise RunError(f'No row with source key {source_key} in this run.')
    candidates = run.evidence
    if len(candidates) and 'source_key' in candidates.columns:
        candidates = candidates[candidates['source_key'] == source_key]
        candidates = payload.order_candidates_for_review(rows.iloc[0], candidates)
    else:
        candidates = candidates.iloc[0:0]
    return {'row': payload.records(rows)[0],
            'candidates': payload.records(candidates, payload.CANDIDATE_COLUMNS)}
