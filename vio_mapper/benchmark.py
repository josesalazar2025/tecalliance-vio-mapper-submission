"""Measure where a full-scale run spends its time, memory and output bytes.

Run it from a terminal; it prints a report and writes the same text to a file:

    uv run vio-mapper-bench --source VehicleYear-2020-ID.csv --format both

The mapping decisions are the ordinary ones. This module adds no policy and
changes no outcome: it calls :func:`vio_mapper.pipeline.map_vehicles` through
its documented ``evidence_sink`` extension point, which is also how
:func:`map_vehicles_streaming` writes its audit trail, and times the phases
around it.

Two throughput numbers are reported on purpose. Rows whose make and model match
nothing in the reference cost almost nothing, so on a large registry measured
against a small catalogue extract the headline rows-per-second is dominated by
rows that were never real work. Candidate comparisons per second is the figure
that survives a change of catalogue size.
"""
from __future__ import annotations

import argparse
import csv
import platform
import resource
import statistics
import sys
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .config import (ALGORITHM_VERSION, DEFAULT_REFERENCE_PATH, DEFAULT_SOURCE_PATH,
                     EVIDENCE_RETENTION, STREAM_ROW_THRESHOLD, Policy,
                     available_registries, use_registry)
from .normalization import normalized_text
from .pipeline import map_vehicles
from .reporting import build_sheets, performance_report
from .cli import run_metadata

OUTPUT_FORMATS = ('xlsx', 'csv', 'both', 'none')
SLOWEST_ROWS_SHOWN = 5


def _peak_rss_bytes() -> int:
    """Process high-water mark. ``ru_maxrss`` is bytes on macOS, kibibytes on Linux."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == 'darwin' else peak * 1024


def _megabytes(value: float) -> str:
    return f'{value / 1_048_576:,.1f} MB'


def _seconds(value: float) -> str:
    return f'{value:,.2f} s'


class Timings:
    """Ordered phase durations, so the report cannot silently lose a phase."""

    def __init__(self) -> None:
        self.phases: dict[str, float] = {}

    def record(self, name: str):
        timings = self

        class _Phase:
            def __enter__(self):
                self.started = time.perf_counter()
                return self

            def __exit__(self, *exception):
                timings.phases[name] = time.perf_counter() - self.started
                return False

        return _Phase()

    @property
    def total(self) -> float:
        return sum(self.phases.values())


def _percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile; no interpolation, so every value reported was observed."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * len(ordered)) - 1))
    return ordered[index]


def _map_with_row_timings(source, reference, policy, evidence_path: Path):
    """Map every row, streaming candidate evidence to CSV and timing each row.

    Mirrors :func:`vio_mapper.pipeline.map_vehicles_streaming`, with a timestamp
    taken as each row's evidence reaches the sink. The measured per-row interval
    therefore covers matching plus that row's evidence serialization, which is
    the work the pipeline actually performs per row.
    """
    latencies: list[float] = []
    written = 0
    with evidence_path.open('w', newline='', encoding='utf-8') as handle:
        writer = None
        previous = time.perf_counter()

        def sink(rows):
            nonlocal writer, written, previous
            for row in rows:
                if writer is None:
                    writer = csv.DictWriter(handle, fieldnames=list(row))
                    writer.writeheader()
                writer.writerow({key: ('' if pd.isna(value) is True else value)
                                 for key, value in row.items()})
                written += 1
            now = time.perf_counter()
            latencies.append(now - previous)
            previous = now

        results, _ = map_vehicles(source, reference, policy, evidence_sink=sink,
                                  include_score_diagnostics=False)
    return results, latencies, written


def _write_sheets_as_csv(sheets: dict, directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, frame in sheets.items():
        path = directory / f'{name}.csv'
        frame.to_csv(path, index=False)
        written.append(path)
    return written


def _workload_metrics(results: pd.DataFrame) -> dict:
    """How much comparison work the run actually contained."""
    candidates = pd.to_numeric(results.get('base_candidate_count'), errors='coerce').fillna(0)
    with_candidates = candidates[candidates > 0]
    return {
        'rows': int(len(results)),
        'distinct_ids': int(results['ID'].map(normalized_text).nunique()),
        'rows_with_candidates': int(len(with_candidates)),
        'total_comparisons': int(candidates.sum()),
        'max_group': int(candidates.max()) if len(candidates) else 0,
        'mean_group': float(with_candidates.mean()) if len(with_candidates) else 0.0,
        'median_group': float(with_candidates.median()) if len(with_candidates) else 0.0,
    }


def _report(args, timings: Timings, results: pd.DataFrame, latencies: list[float],
            evidence_rows: int, outputs: dict, peak_rss: int, baseline_rss: int,
            traced_peak: int | None, source_rows: int, reference_rows: int,
            map_seconds: float) -> str:
    work = _workload_metrics(results)
    lines: list[str] = []
    add = lines.append

    add('=' * 78)
    add('VIO MAPPER — SCALE BENCHMARK')
    add('=' * 78)
    add(f'Run (UTC)         {datetime.now(timezone.utc).isoformat(timespec="seconds")}')
    add(f'Algorithm         {ALGORITHM_VERSION}')
    add(f'Python / pandas   {platform.python_version()} / {pd.__version__}')
    add(f'Platform          {platform.platform()}')
    add(f'Source            {args.source.name}  ({source_rows:,} rows)')
    add(f'Reference         {args.reference.name}  ({reference_rows:,} rows)')
    add(f'Evidence          retention={args.evidence}  streamed to CSV')
    add(f'Output format     {args.format}')
    if args.limit:
        add(f'Limit             first {args.limit:,} source rows')
        add('                  (the load phase still reads the whole file, so its share')
        add('                   and the end-to-end rate are not comparable to a full run)')

    add('')
    add('-' * 78)
    add('PHASE TIMINGS')
    add('-' * 78)
    total = timings.total
    for name, seconds in timings.phases.items():
        share = (seconds / total * 100) if total else 0
        bar = '█' * int(round(share / 2.5))
        add(f'{name:<34}{_seconds(seconds):>12}{share:>7.1f}%  {bar}')
    add(f'{"TOTAL":<34}{_seconds(total):>12}{100.0:>7.1f}%')

    add('')
    add('-' * 78)
    add('THROUGHPUT')
    add('-' * 78)
    add(f'{"Source rows":<34}{work["rows"]:>12,}')
    add(f'{"Distinct vehicle IDs":<34}{work["distinct_ids"]:>12,}')
    add(f'{"Rows mapped per second":<34}{work["rows"] / map_seconds:>12,.0f}   (mapping phase)')
    add(f'{"Rows per second, end to end":<34}{work["rows"] / total:>12,.0f}   (all phases)')
    add(f'{"Microseconds per row":<34}{map_seconds / work["rows"] * 1e6:>12,.1f}')
    add('')
    add(f'{"Rows with >=1 candidate":<34}{work["rows_with_candidates"]:>12,}'
        f'   ({work["rows_with_candidates"] / work["rows"] * 100:.1f}% of rows)')
    add(f'{"Candidate comparisons":<34}{work["total_comparisons"]:>12,}')
    if map_seconds:
        add(f'{"Comparisons per second":<34}{work["total_comparisons"] / map_seconds:>12,.0f}')
    add(f'{"Candidates per row that had any":<34}'
        f'{work["mean_group"]:>12,.1f}   mean; median {work["median_group"]:,.0f}; '
        f'max {work["max_group"]:,}')
    add('')
    add('Note: rows whose make and model match nothing in the reference exit before any')
    add('      comparison. Against a catalogue extract they inflate rows-per-second, so')
    add('      comparisons-per-second is the figure to carry across catalogue sizes.')

    if latencies:
        add('')
        add('-' * 78)
        add('PER-ROW LATENCY  (match + evidence write)')
        add('-' * 78)
        for label, value in (('p50', _percentile(latencies, .50)),
                             ('p90', _percentile(latencies, .90)),
                             ('p99', _percentile(latencies, .99)),
                             ('p99.9', _percentile(latencies, .999)),
                             ('max', max(latencies))):
            add(f'{label:<34}{value * 1e6:>12,.1f} us')
        add(f'{"mean":<34}{statistics.fmean(latencies) * 1e6:>12,.1f} us')
        add('')
        slowest = sorted(range(len(latencies)), key=lambda i: latencies[i], reverse=True)
        add(f'Slowest {SLOWEST_ROWS_SHOWN} rows:')
        for index in slowest[:SLOWEST_ROWS_SHOWN]:
            row = results.iloc[index]
            candidates = row.get('base_candidate_count', 0)
            add(f'  {latencies[index] * 1e3:>8,.1f} ms  '
                f'{str(row.get("MAKE", "")):<16}{str(row.get("MODEL", "")):<16}'
                f'candidates={candidates}  {row.get("Match_Status", "")}')

    add('')
    add('-' * 78)
    add('MEMORY')
    add('-' * 78)
    add(f'{"Peak process RSS":<34}{_megabytes(peak_rss):>12}')
    add(f'{"Baseline after inputs loaded":<34}{_megabytes(baseline_rss):>12}'
        '   (interpreter, pandas, reference)')
    add(f'{"Marginal, attributable to the run":<34}{_megabytes(peak_rss - baseline_rss):>12}')
    add('Peak RSS carries a large fixed baseline, so it understates how memory grows')
    add('with volume. The marginal figure is the one to scale.')
    if traced_peak is not None:
        add(f'{"Peak traced Python heap":<34}{_megabytes(traced_peak):>12}'
            '   (tracemalloc; slows the run)')
    add(f'{"Reference held in memory":<34}{reference_rows:>12,} rows')
    add('Candidate evidence is streamed to disk and never accumulated.')

    add('')
    add('-' * 78)
    add('OUTCOME DISTRIBUTION')
    add('-' * 78)
    counts = results['Match_Status'].value_counts()
    ids = (results.assign(_id=results['ID'].map(normalized_text))
           .groupby('Match_Status')['_id'].nunique())
    add(f'{"Status":<52}{"Rows":>10}{"Distinct":>10}')
    for status, count in counts.items():
        add(f'{str(status):<52}{count:>10,}{ids.get(status, 0):>10,}')
    accepted = int(results['count_in_vio'].sum())
    add('')
    add(f'{"Accepted distinct vehicles (VIO)":<52}{accepted:>20,}')
    add(f'{"Unresolved distinct vehicles":<52}'
        f'{work["distinct_ids"] - accepted:>20,}')
    add(f'{"Acceptance coverage":<52}'
        f'{accepted / work["distinct_ids"] * 100:>19.1f}%')
    add('')
    add('Coverage here is not accuracy, and against a catalogue extract it is not')
    add('comparable to a run with full reference coverage. This benchmark measures')
    add('throughput and stability, not mapping quality.')

    add('')
    add('-' * 78)
    add('OUTPUT SIZE')
    add('-' * 78)
    add(f'{"Candidate evidence rows":<34}{evidence_rows:>12,}')
    for label, path in outputs.items():
        if path is None:
            continue
        if isinstance(path, list):
            size = sum(item.stat().st_size for item in path)
            add(f'{label:<34}{_megabytes(size):>12}   ({len(path)} files)')
        elif path.exists():
            add(f'{label:<34}{_megabytes(path.stat().st_size):>12}   {path.name}')
    add('')
    add('=' * 78)
    return '\n'.join(lines)


def build_parser() -> argparse.ArgumentParser:
    defaults = Policy()
    parser = argparse.ArgumentParser(
        description='Time, profile and summarize a full-scale mapping run.')
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE_PATH,
                        help='Registry file to map: .csv/.txt or .xlsx (default: %(default)s)')
    parser.add_argument('--reference', type=Path, default=DEFAULT_REFERENCE_PATH,
                        help='TecAlliance reference workbook (default: %(default)s)')
    parser.add_argument('--registry', choices=available_registries(), default='nz',
                        help='Which register --source comes from (default: %(default)s)')
    parser.add_argument('--format', choices=OUTPUT_FORMATS, default='both',
                        help='Which result outputs to write and time (default: %(default)s). '
                             "'csv' skips workbook serialization entirely.")
    parser.add_argument('--out-dir', type=Path, default=Path.cwd() / 'benchmark_output',
                        help='Directory for generated outputs (default: %(default)s)')
    parser.add_argument('--metrics', type=Path, default=None,
                        help='Metrics text file (default: <out-dir>/benchmark_metrics.txt)')
    parser.add_argument('--evidence', choices=EVIDENCE_RETENTION, default=defaults.evidence,
                        help='Candidate-evidence retention (default: %(default)s)')
    parser.add_argument('--limit', type=int, default=None,
                        help='Map only the first N source rows, for a scaling curve')
    parser.add_argument('--trace-malloc', action='store_true',
                        help='Also report peak traced Python heap. Slows the run substantially.')
    parser.add_argument('--keep-outputs', action=argparse.BooleanOptionalAction, default=True,
                        help='Keep generated files (default: keep, so sizes can be inspected)')
    return parser


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    use_registry(args.registry)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = args.metrics or (args.out_dir / 'benchmark_metrics.txt')
    policy = Policy(evidence=args.evidence)
    timings = Timings()

    if args.trace_malloc:
        tracemalloc.start()

    # Imported here so the load phase below times only the file read.
    from .sources import load_source

    print(f'Mapping {args.source.name} against {args.reference.name} ...', flush=True)

    with timings.record('load + normalize source'):
        source = load_source(args.source)
    if args.limit:
        source = source.head(args.limit).copy()
    source_rows = len(source)

    with timings.record('load reference workbook'):
        reference = pd.read_excel(args.reference, dtype=object)
    reference_rows = len(reference)

    # High-water mark before mapping: everything below this is interpreter,
    # pandas and the reference, not work attributable to the run's volume.
    baseline_rss = _peak_rss_bytes()

    evidence_path = args.out_dir / 'candidate_evidence.csv'
    with timings.record('map + stream evidence'):
        results, latencies, evidence_rows = _map_with_row_timings(
            source, reference, policy, evidence_path)
    map_seconds = timings.phases['map + stream evidence']

    with timings.record('run metadata (hashing)'):
        metadata = run_metadata(results, policy, args.source, args.reference)

    evidence_pointer = pd.DataFrame([{
        'note': 'Candidate evidence exceeds practical worksheet size and was written to CSV.',
        'file': evidence_path.name, 'rows': evidence_rows, 'retention': policy.evidence,
    }])
    with timings.record('build sheets'):
        sheets = build_sheets(results, evidence_pointer, policy, metadata)

    outputs: dict = {'Candidate evidence CSV': evidence_path,
                     'Result sheets as CSV': None, 'Result workbook (XLSX)': None,
                     'Performance report': None}

    if args.format in ('csv', 'both'):
        with timings.record('write result sheets as CSV'):
            outputs['Result sheets as CSV'] = _write_sheets_as_csv(
                sheets, args.out_dir / 'sheets_csv')

    if args.format in ('xlsx', 'both'):
        from .reporting import write_workbook
        workbook = args.out_dir / 'mapped.xlsx'
        with timings.record('write result workbook (XLSX)'):
            write_workbook(sheets, workbook)
        outputs['Result workbook (XLSX)'] = workbook

    report_path = args.out_dir / 'mapping_performance.md'
    with timings.record('write performance report'):
        report_path.write_text(performance_report(results, metadata))
    outputs['Performance report'] = report_path

    traced_peak = None
    if args.trace_malloc:
        traced_peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()

    text = _report(args, timings, results, latencies, evidence_rows, outputs,
                   _peak_rss_bytes(), baseline_rss, traced_peak, source_rows,
                   reference_rows, map_seconds)
    print()
    print(text)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(text + '\n')
    print(f'Metrics written to {metrics_path}')

    if not args.keep_outputs:
        for path in (evidence_path, report_path, outputs['Result workbook (XLSX)']):
            if isinstance(path, Path):
                path.unlink(missing_ok=True)
        for path in (outputs['Result sheets as CSV'] or []):
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
