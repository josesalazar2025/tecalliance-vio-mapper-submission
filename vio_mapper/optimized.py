"""Outcome-preserving high-throughput execution for algorithm 1.1.0.

The baseline mapper remains available in :mod:`vio_mapper.pipeline`.  This
module changes scheduling and representation only: one global preparation,
one decision per exact decision key, and closed make/model worker partitions.
"""
from __future__ import annotations

import hashlib
import json
import resource
import shutil
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from .config import Policy, column
from .decision import decide
from .normalization import model_year, normalized_text
from .pipeline import (_RowMatcher, _finalize, decision_key, retain_evidence)
from .sources import prepare_reference, prepare_source

EVIDENCE_FLUSH_ROWS = 10_000


@dataclass
class ExecutionMetrics:
    source_rows: int = 0
    early_conflicts: int = 0
    insufficient_rows: int = 0
    gated_rows: int = 0
    candidate_rows: int = 0
    distinct_decisions: int = 0
    cache_reused_rows: int = 0
    logical_candidate_comparisons: int = 0
    worker_count: int = 1
    retries: int = 0
    checkpoint_hits: int = 0
    failed_partitions: int = 0
    peak_aggregate_rss_bytes: int = 0
    partition_costs: list[int] = field(default_factory=list)
    gate_counts: list[dict] = field(default_factory=list)
    multiplicity_percentiles: dict[str, int] = field(default_factory=dict)
    candidate_count_percentiles: dict[str, int] = field(default_factory=dict)
    timings_seconds: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionOptions:
    workers: int = 1
    checkpoint_dir: Path | None = None
    expand_evidence: bool = True
    bulk_gate: bool = True
    group_decisions: bool = True
    partitioned: bool = True
    include_decision_id: bool = False
    disk_evidence: bool = False
    collect_diagnostics: bool = True
    trust_precomputed_normalization: bool = False
    trust_prepared_reference: bool = False

    def validate(self) -> None:
        if self.workers < 1:
            raise ValueError('workers must be at least 1')
        if self.disk_evidence and self.expand_evidence:
            raise ValueError('disk evidence requires compact evidence output')
        if self.disk_evidence and self.workers != 1:
            raise ValueError('disk evidence currently requires one inner worker')
        if self.disk_evidence and self.checkpoint_dir is None:
            raise ValueError('disk evidence requires a checkpoint directory')


class _Timer:
    def __init__(self, metrics: ExecutionMetrics, name: str):
        self.metrics, self.name = metrics, name

    def __enter__(self):
        self.start = time.perf_counter()

    def __exit__(self, *args):
        self.metrics.timings_seconds[self.name] = time.perf_counter() - self.start


def _peak_rss_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == 'darwin' else peak * 1024)


def _gate(source: pd.DataFrame, reference: pd.DataFrame, policy: Policy,
          make: pd.Series, model: pd.Series, year: pd.Series) -> pd.Series:
    """Vectorized equivalent of ``_RowMatcher._candidates`` membership."""
    keys = pd.MultiIndex.from_arrays([make, model])
    if policy.year_mode != 'gate':
        groups = pd.MultiIndex.from_frame(reference[['_make', '_model']].drop_duplicates())
        return pd.Series(keys.isin(groups), index=source.index)
    earliest = reference.groupby(['_make', '_model'], sort=False)['_from'].min()
    starts = earliest.reindex(keys).set_axis(source.index)
    return starts.notna() & year.notna() & starts.le(year)


def _global_decisions(source: pd.DataFrame, matcher: _RowMatcher, *, reuse: bool = True):
    ids: list[int] = []
    representatives: list[int] = []
    key_to_id: dict = {}
    canonical_keys: list[object] = []
    for index, row in source.iterrows():
        key = decision_key(row, matcher.engine_tokens)
        decision_id = key_to_id.get(key) if reuse else None
        if decision_id is None:
            decision_id = len(representatives)
            key_to_id[key] = decision_id
            representatives.append(index)
            canonical_keys.append(key)
        # Equality on the canonical key, not a hash, is the collision check.
        elif canonical_keys[decision_id] != key:
            raise AssertionError('decision-key collision')
        ids.append(decision_id)
    links = pd.DataFrame({'source_ordinal': range(len(source)), 'decision_id': ids})
    multiplicity = links.groupby('decision_id', sort=False).size().rename('multiplicity')
    decisions = source.loc[representatives].copy().reset_index(drop=True)
    decisions.insert(0, 'decision_id', range(len(decisions)))
    decisions['multiplicity'] = multiplicity.to_numpy()
    return decisions, links


def _partition_batches(decisions: pd.DataFrame, reference: pd.DataFrame, workers: int):
    makes = decisions[column('make')].map(normalized_text)
    models = decisions[column('model')].map(normalized_text)
    refs = reference.groupby(['_make', '_model'], sort=False).size().to_dict()
    groups: dict[tuple[str, str], list[int]] = {}
    for index, key in enumerate(zip(makes, models)):
        groups.setdefault(key, []).append(index)
    weighted = sorted(((len(indices) * max(1, refs.get(key, 0)), key, indices)
                       for key, indices in groups.items()), reverse=True)
    bins = [{'cost': 0, 'indices': [], 'keys': []} for _ in range(min(workers, len(weighted)))]
    for cost, key, indices in weighted:
        target = min(bins, key=lambda item: item['cost'])
        target['cost'] += cost
        target['indices'].extend(indices)
        target['keys'].append(key)
    return bins


def _frame_fingerprint(decisions: pd.DataFrame, reference: pd.DataFrame,
                       policy: Policy, partition_id: int,
                       include_score_diagnostics: bool,
                       disk_evidence: bool = False) -> str:
    payload = {'partition': partition_id, 'policy': asdict(policy),
               'include_score_diagnostics': include_score_diagnostics,
               'disk_evidence': disk_evidence,
               'decisions': decisions.to_json(orient='split', default_handler=str),
               'reference': reference.to_json(orient='split', default_handler=str)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _write_fragment(frame: pd.DataFrame, path: Path) -> None:
    try:
        temporary = path.with_name(path.name + '.tmp')
        frame.to_parquet(temporary, index=False, engine='pyarrow', compression='zstd')
        temporary.replace(path)
    except ImportError as exc:
        raise RuntimeError('Parallel/checkpoint execution requires pyarrow') from exc


def _run_partition(partition_id: int, decisions: pd.DataFrame, reference: pd.DataFrame,
                   policy: Policy, include_score_diagnostics: bool, directory: str,
                   disk_evidence: bool = False):
    directory_path = Path(directory)
    result_path = directory_path / f'partition-{partition_id:05d}-results.parquet'
    evidence_path = directory_path / f'partition-{partition_id:05d}-evidence.parquet'
    done_path = directory_path / f'partition-{partition_id:05d}.json'
    fingerprint = _frame_fingerprint(decisions, reference, policy, partition_id,
                                     include_score_diagnostics, disk_evidence)
    if done_path.exists():
        state = json.loads(done_path.read_text())
        if (state.get('fingerprint') == fingerprint and result_path.exists()
                and evidence_path.exists()):
            return (str(result_path), str(evidence_path), True,
                    int(state.get('peak_rss_bytes', 0)))

    matcher = _RowMatcher(reference, policy, include_score_diagnostics)
    results, evidence = [], []
    fragment_number = 0
    evidence_temporary = evidence_path.with_name(evidence_path.name + '.tmp')
    if disk_evidence:
        if evidence_temporary.exists():
            shutil.rmtree(evidence_temporary)
        evidence_temporary.mkdir()

    def flush_evidence() -> None:
        nonlocal evidence, fragment_number
        if not evidence:
            return
        frame = pd.DataFrame(evidence)
        sort_fields = [name for name in ('decision_id', 'review_rank', 'KType')
                       if name in frame]
        frame.sort_values(sort_fields).to_parquet(
            evidence_temporary / f'part-{fragment_number:05d}.parquet',
            index=False, engine='pyarrow', compression='zstd')
        fragment_number += 1
        evidence = []

    for _, row in decisions.sort_values('decision_id').iterrows():
        if row.get('_bulk_no_candidate', False):
            # The global gate proved this make/model/year has no reference
            # candidates. Keep decide() for identifier and source-conflict
            # audit columns, but bypass the candidate-group lookup entirely.
            result, details = decide(
                row, matcher.empty, policy,
                include_score_diagnostics=include_score_diagnostics)
        else:
            result, details = matcher._decide(row)
        results.append({'decision_id': int(row['decision_id']), **result})
        for entry in retain_evidence(details, result['Match_Status'], policy):
            evidence.append({'decision_id': int(row['decision_id']), **entry})
        if disk_evidence and len(evidence) >= EVIDENCE_FLUSH_ROWS:
            flush_evidence()
    result_frame = pd.DataFrame(results)
    _write_fragment(result_frame.sort_values('decision_id'), result_path)
    if disk_evidence:
        flush_evidence()
        if not fragment_number:
            pd.DataFrame({'decision_id': pd.Series(dtype='int64')}).to_parquet(
                evidence_temporary / 'part-00000.parquet', index=False,
                engine='pyarrow', compression='zstd')
        if evidence_path.exists():
            if evidence_path.is_dir():
                shutil.rmtree(evidence_path)
            else:
                evidence_path.unlink()
        evidence_temporary.replace(evidence_path)
    else:
        evidence_frame = pd.DataFrame(evidence)
        if evidence_frame.empty:
            evidence_frame = pd.DataFrame({'decision_id': pd.Series(dtype='int64')})
        _write_fragment(evidence_frame.sort_values(
            [name for name in ('decision_id', 'review_rank', 'KType') if name in evidence_frame]),
            evidence_path)
    done_temporary = done_path.with_name(done_path.name + '.tmp')
    peak_rss = _peak_rss_bytes()
    done_temporary.write_text(json.dumps({'fingerprint': fingerprint, 'complete': True,
                                          'peak_rss_bytes': peak_rss}) + '\n')
    done_temporary.replace(done_path)
    return str(result_path), str(evidence_path), False, peak_rss


def _execute(decisions: pd.DataFrame, reference: pd.DataFrame, policy: Policy,
             options: ExecutionOptions, include_score_diagnostics: bool,
             metrics: ExecutionMetrics):
    batches = _partition_batches(decisions, reference, options.workers)
    metrics.partition_costs = [item['cost'] for item in batches]
    # An explicit directory is a resumable audit artefact. Without one the same
    # fragment protocol is used as scratch IPC and cleaned after the join.
    temporary = tempfile.TemporaryDirectory(prefix='vio-mapper-') if options.checkpoint_dir is None else None
    directory = options.checkpoint_dir or Path(temporary.name)
    directory.mkdir(parents=True, exist_ok=True)
    tasks = []
    for partition_id, batch in enumerate(batches):
        local_decisions = decisions.iloc[batch['indices']].copy()
        key_set = set(batch['keys'])
        local_reference = reference[[key in key_set
                                     for key in zip(reference['_make'], reference['_model'])]].copy()
        tasks.append((partition_id, local_decisions, local_reference, policy,
                      include_score_diagnostics, str(directory), options.disk_evidence))
    completed = []
    if options.workers == 1:
        completed = [_run_partition(*task) for task in tasks]
    else:
        with ProcessPoolExecutor(max_workers=options.workers) as executor:
            futures = {executor.submit(_run_partition, *task): task[0] for task in tasks}
            for future in as_completed(futures):
                completed.append(future.result())
    completed.sort()
    results = pd.concat([pd.read_parquet(item[0]) for item in completed], ignore_index=True)
    if options.disk_evidence:
        evidence = Path(completed[0][1])
    else:
        evidence = pd.concat([pd.read_parquet(item[1]) for item in completed], ignore_index=True)
        if 'KType' in evidence:
            evidence['KType'] = pd.array(evidence['KType'], dtype='Int64')
    metrics.checkpoint_hits = sum(int(item[2]) for item in completed)
    metrics.peak_aggregate_rss_bytes = (_peak_rss_bytes() if options.workers == 1
                                        else _peak_rss_bytes() + sum(item[3] for item in completed))
    if temporary is not None:
        temporary.cleanup()
    return results, evidence


def _nearest_percentiles(values: pd.Series) -> dict[str, int]:
    if values.empty:
        return {'p50': 0, 'p90': 0, 'p99': 0, 'max': 0}
    return {name: int(values.quantile(fraction, interpolation='nearest'))
            for name, fraction in (('p50', .5), ('p90', .9), ('p99', .99), ('max', 1.0))}


def _expand_evidence(compact: pd.DataFrame, links: pd.DataFrame,
                     source: pd.DataFrame) -> pd.DataFrame:
    if compact.empty or set(compact.columns) == {'decision_id'}:
        return pd.DataFrame()
    expanded = links.merge(compact.drop(columns=['source_key', 'ID'], errors='ignore'),
                           on='decision_id', how='inner', validate='many_to_many')
    provenance = source.reset_index(drop=True)[['source_key', column('id')]].copy()
    provenance.columns = ['source_key', 'ID']
    expanded = expanded.join(provenance, on='source_ordinal')
    return expanded.drop(columns=['source_ordinal', 'decision_id'])


def map_vehicles_optimized(source, reference, policy=Policy(), *,
                           options=ExecutionOptions(), include_score_diagnostics=True):
    """Map globally grouped decisions and return results, evidence, and metrics."""
    policy.validate()
    options.validate()
    effective_workers = options.workers if options.partitioned else 1
    metrics = ExecutionMetrics(source_rows=len(source), worker_count=effective_workers)
    with _Timer(metrics, 'prepare'):
        if options.trust_prepared_reference:
            required = {'_make', '_model', '_from', '_to', 'KType'}
            if not required.issubset(reference.columns):
                raise ValueError('Prepared reference is missing gate columns')
            reference = reference.copy().reset_index(drop=True)
        else:
            reference = prepare_reference(reference)
        source = source.copy().reset_index(drop=True)
        if 'canonical_record' not in source:
            source = prepare_source(source)
        matcher = _RowMatcher(reference, policy, include_score_diagnostics)
    with _Timer(metrics, 'gate'):
        if options.trust_precomputed_normalization:
            required = {'_make', '_model', '_year'}
            if not required.issubset(source.columns):
                raise ValueError('Prepared source is missing normalized gate columns')
            make, model, year = source['_make'], source['_model'], source['_year']
        else:
            make = source[column('make')].map(normalized_text)
            model = source[column('model')].map(normalized_text)
            year = source[column('year')].map(model_year)
        forwarded = (_gate(source, reference, policy, make, model, year)
                     if options.bulk_gate else pd.Series(True, index=source.index))
        metrics.early_conflicts = int(source['duplicate_id_conflict'].sum())
        metrics.insufficient_rows = int((make.eq('') | model.eq('') |
                                         ((policy.year_mode == 'gate') & year.isna())).sum())
        metrics.candidate_rows = int(forwarded.sum())
        metrics.gated_rows = int((~forwarded & make.ne('') & model.ne('') &
                                  ~source['duplicate_id_conflict']).sum())
        if options.collect_diagnostics:
            gate_frame = pd.DataFrame({'make': make, 'model': model, 'year': year,
                                       'forwarded': forwarded})
            metrics.gate_counts = [
                {'make': key[0], 'model': key[1],
                 'year': None if pd.isna(key[2]) else int(key[2]),
                 'forwarded': bool(key[3]), 'rows': int(count)}
                for key, count in gate_frame.value_counts(dropna=False, sort=False).items()
            ]
    with _Timer(metrics, 'group'):
        decisions, links = _global_decisions(source, matcher,
                                             reuse=options.group_decisions)
        if options.bulk_gate:
            eligible = make.ne('') & model.ne('')
            if policy.year_mode == 'gate':
                eligible &= year.notna()
            representatives = links.drop_duplicates('decision_id')['source_ordinal']
            decisions['_bulk_no_candidate'] = (
                (~forwarded & eligible).iloc[representatives.to_numpy()]
                .to_numpy(dtype=bool))
        metrics.distinct_decisions = len(decisions)
        metrics.cache_reused_rows = len(source) - len(decisions)
        if options.collect_diagnostics:
            metrics.multiplicity_percentiles = _nearest_percentiles(decisions['multiplicity'])
    with _Timer(metrics, 'decide'):
        effective_options = ExecutionOptions(
            workers=effective_workers, checkpoint_dir=options.checkpoint_dir,
            expand_evidence=options.expand_evidence, bulk_gate=options.bulk_gate,
            group_decisions=options.group_decisions, partitioned=options.partitioned,
            include_decision_id=options.include_decision_id,
            disk_evidence=options.disk_evidence,
            collect_diagnostics=options.collect_diagnostics,
            trust_precomputed_normalization=options.trust_precomputed_normalization,
            trust_prepared_reference=options.trust_prepared_reference)
        decision_results, compact_evidence = _execute(
            decisions, reference, policy, effective_options,
            include_score_diagnostics, metrics)
    with _Timer(metrics, 'join'):
        expanded = links.merge(decision_results, on='decision_id', how='left',
                               validate='many_to_one').sort_values('source_ordinal')
        if len(expanded) != len(source) or expanded['decision_id'].isna().any():
            raise AssertionError('Global result pass did not produce exactly one outcome per row')
        result_columns = [name for name in decision_results if name != 'decision_id']
        results = pd.concat([source.reset_index(drop=True),
                             expanded[result_columns].reset_index(drop=True)], axis=1)
        if options.include_decision_id:
            results['decision_id'] = expanded['decision_id'].to_numpy()
        results = _finalize(results)
        evidence = (_expand_evidence(compact_evidence, links, source)
                    if options.expand_evidence else compact_evidence)
        metrics.logical_candidate_comparisons = int(pd.to_numeric(
            results.get('base_candidate_count', 0), errors='coerce').fillna(0).sum())
        if options.collect_diagnostics:
            metrics.candidate_count_percentiles = _nearest_percentiles(pd.to_numeric(
                decision_results.get('base_candidate_count', pd.Series(dtype='int64')),
                errors='coerce').fillna(0))
    return results, evidence, metrics
