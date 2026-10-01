"""Disk-partitioned execution for registries too large to hold in pandas."""
from __future__ import annotations

import json
import resource
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Policy
from .optimized import ExecutionOptions, map_vehicles_optimized
from .semantic import sha256_file, sha256_files


def _write_json_atomic(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def _peak_rss_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == 'darwin' else peak * 1024)


def partition_source(dataset: Path, output: Path, *, buckets: int = 512) -> dict:
    """Put equal make/model/year keys in one bounded, resumable bucket.

    The decision key includes the raw make, model and year, so equal decisions
    necessarily share this normalized partition key. Every bucket later receives
    the complete reference; no candidate group is divided within a decision.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    if buckets < 1:
        raise ValueError('buckets must be at least 1')
    source_path = dataset / 'source.parquet'
    directory = output / 'source-buckets'
    marker = directory / 'partition-manifest.json'
    signature = {'source_sha256': sha256_file(source_path), 'buckets': buckets,
                 'partition_columns': ['_make', '_model', '_year']}
    if marker.exists():
        existing = json.loads(marker.read_text())
        if all(existing.get(key) == value for key, value in signature.items()):
            return existing
        raise ValueError('Existing source buckets have different inputs or bucket count')
    directory.mkdir(parents=True, exist_ok=True)
    # A missing marker means an earlier conversion was interrupted. Its files
    # are generated scratch output, and every bucket is rewritten from source.
    for path in directory.glob('bucket-*.parquet'):
        path.unlink()
    reader = pq.ParquetFile(source_path)
    # Limit open writers even for hundreds of final buckets. A first pass into
    # at most 64 shards and a second pass per shard also bounds file handles.
    shard_count = min(64, buckets)
    shards = directory / '_shards'
    shards.mkdir(exist_ok=True)
    for path in shards.glob('shard-*.parquet'):
        path.unlink()
    writers: dict[int, pq.ParquetWriter] = {}
    counts = np.zeros(buckets, dtype=np.int64)
    try:
        for batch in reader.iter_batches(batch_size=50_000):
            table = pa.Table.from_batches([batch])
            keys = table.select(['_make', '_model', '_year']).to_pandas()
            labels = (pd.util.hash_pandas_object(keys, index=False).to_numpy(dtype=np.uint64)
                      % np.uint64(shard_count)).astype(np.int32)
            for shard in np.unique(labels):
                indices = np.flatnonzero(labels == shard)
                path = shards / f'shard-{int(shard):04d}.parquet'
                if int(shard) not in writers:
                    writers[int(shard)] = pq.ParquetWriter(
                        path, table.schema, compression='zstd', use_dictionary=True)
                writers[int(shard)].write_table(table.take(pa.array(indices)))
    finally:
        for writer in writers.values():
            writer.close()
    for shard_path in sorted(shards.glob('shard-*.parquet')):
        final_writers: dict[int, pq.ParquetWriter] = {}
        try:
            for batch in pq.ParquetFile(shard_path).iter_batches(batch_size=50_000):
                table = pa.Table.from_batches([batch])
                keys = table.select(['_make', '_model', '_year']).to_pandas()
                labels = (pd.util.hash_pandas_object(keys, index=False).to_numpy(dtype=np.uint64)
                          % np.uint64(buckets)).astype(np.int32)
                for bucket in np.unique(labels):
                    indices = np.flatnonzero(labels == bucket)
                    path = directory / f'bucket-{int(bucket):04d}.parquet'
                    if int(bucket) not in final_writers:
                        final_writers[int(bucket)] = pq.ParquetWriter(
                            path, table.schema, compression='zstd', use_dictionary=True)
                    final_writers[int(bucket)].write_table(table.take(pa.array(indices)))
                    counts[int(bucket)] += len(indices)
        finally:
            for writer in final_writers.values():
                writer.close()
        shard_path.unlink()
    manifest = {**signature, 'rows': int(counts.sum()),
                'bucket_rows': {str(i): int(value) for i, value in enumerate(counts) if value}}
    _write_json_atomic(marker, manifest)
    return manifest


def _map_bucket(bucket: int, dataset: str, output: str, policy: Policy,
                source_sha256: str, reference_sha256: str,
                code_sha256: str, rule_sha256: str) -> dict:
    dataset_path, output_path = Path(dataset), Path(output)
    source_path = output_path / 'source-buckets' / f'bucket-{bucket:04d}.parquet'
    directory = output_path / 'mapped-buckets' / f'bucket-{bucket:04d}'
    directory.mkdir(parents=True, exist_ok=True)
    done = directory / 'done.json'
    results_path, evidence_path = directory / 'results.parquet', directory / 'candidate_evidence.parquet'
    signature = {'source_sha256': source_sha256,
                 'reference_sha256': reference_sha256,
                 'bucket_sha256': sha256_file(source_path),
                 'code_sha256': code_sha256, 'rule_sha256': rule_sha256,
                 'policy': vars(policy)}
    if (done.exists() and results_path.exists() and evidence_path.is_dir()):
        previous = json.loads(done.read_text())
        if all(previous.get(key) == value for key, value in signature.items()):
            return {**previous, 'checkpoint_hit': True}
    source = pd.read_parquet(source_path, engine='pyarrow')
    reference = pd.read_parquet(dataset_path / 'reference.parquet', engine='pyarrow')
    started = time.perf_counter()
    results, evidence, metrics = map_vehicles_optimized(
        source, reference, policy,
        options=ExecutionOptions(workers=1, checkpoint_dir=directory / 'inner',
                                 expand_evidence=False, include_decision_id=True,
                                 disk_evidence=True, collect_diagnostics=False,
                                 trust_precomputed_normalization=True,
                                 trust_prepared_reference=True),
        include_score_diagnostics=False)
    results.insert(0, 'bucket_id', bucket)
    results.sort_values('source_ordinal').to_parquet(
        results_path.with_suffix('.parquet.tmp'), index=False,
        engine='pyarrow', compression='zstd')
    evidence_temporary = evidence_path.with_name(evidence_path.name + '.tmp')
    if evidence_temporary.exists():
        shutil.rmtree(evidence_temporary)
    evidence_temporary.mkdir()
    for fragment in sorted(Path(evidence).glob('part-*.parquet')):
        frame = pd.read_parquet(fragment)
        frame.insert(0, 'bucket_id', bucket)
        frame.to_parquet(evidence_temporary / fragment.name, index=False,
                         engine='pyarrow', compression='zstd')
    results_path.with_suffix('.parquet.tmp').replace(results_path)
    if evidence_path.exists():
        if evidence_path.is_dir():
            shutil.rmtree(evidence_path)
        else:
            evidence_path.unlink()
    evidence_temporary.replace(evidence_path)
    accepted = results.loc[results['count_in_vio'], 'mapped kType'].value_counts()
    summary = {**signature, 'bucket': bucket, 'rows': len(results),
               'distinct_decisions': metrics.distinct_decisions,
               'gated_rows': metrics.gated_rows,
               'candidate_rows': metrics.candidate_rows,
               'logical_candidate_comparisons': metrics.logical_candidate_comparisons,
               'status_counts': {str(key): int(value)
                                 for key, value in results.Match_Status.value_counts().items()},
               'accepted_ktype_counts': {str(int(key)): int(value)
                                         for key, value in accepted.items()},
               'elapsed_seconds': time.perf_counter() - started,
               'peak_rss_bytes': _peak_rss_bytes(), 'checkpoint_hit': False}
    _write_json_atomic(done, summary)
    return summary


def run_bounded_dataset(dataset: Path | str, output: Path | str, *,
                        buckets: int = 512, workers: int = 1,
                        policy: Policy = Policy(), max_buckets: int | None = None,
                        bucket_ids: list[int] | None = None) -> dict:
    """Run closed decision buckets with disk checkpoints and bounded memory.

    ``max_buckets`` permits a development slice; a partial run never receives
    a completion marker. Full output remains partitioned to avoid a final
    all-rows pandas join.
    """
    dataset, output = Path(dataset), Path(output)
    if workers < 1:
        raise ValueError('workers must be at least 1')
    if bucket_ids is not None and max_buckets is not None:
        raise ValueError('Choose either bucket IDs or max buckets')
    if max_buckets is not None and max_buckets < 1:
        raise ValueError('max_buckets must be at least 1')
    policy.validate()
    dataset_manifest = json.loads((dataset / 'manifest.json').read_text())
    from .columnar import EXECUTION_SCHEMA_VERSION
    if dataset_manifest.get('schema_version') != EXECUTION_SCHEMA_VERSION:
        raise ValueError('Unsupported execution-dataset schema version')
    started = time.perf_counter()
    partition = partition_source(dataset, output, buckets=buckets)
    reference_sha256 = sha256_file(dataset / 'reference.parquet')
    from .cli import PROVENANCE_FILES, _rule_inputs
    package = Path(__file__).resolve().parent
    code_sha256 = sha256_files(package / name for name in (
        *PROVENANCE_FILES, 'optimized.py', 'bounded.py', 'columnar.py',
        'semantic.py', 'throughput.py'))
    rule_sha256 = sha256_files(_rule_inputs())
    active = sorted(int(key) for key in partition['bucket_rows'])
    if bucket_ids is not None:
        selected = sorted(set(bucket_ids))
        unknown = set(selected) - set(active)
        if unknown:
            raise ValueError(f'Unknown bucket IDs: {sorted(unknown)}')
    else:
        selected = active if max_buckets is None else active[:max_buckets]
    summaries = []
    arguments = [(bucket, str(dataset), str(output), policy,
                  partition['source_sha256'], reference_sha256,
                  code_sha256, rule_sha256)
                 for bucket in sorted(
                     selected, key=lambda value: partition['bucket_rows'][str(value)],
                     reverse=True)]
    if workers == 1:
        summaries = [_map_bucket(*arguments) for arguments in arguments]
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_map_bucket, *arguments) for arguments in arguments]
            for future in as_completed(futures):
                summaries.append(future.result())
    counts: dict[str, int] = {}
    accepted: dict[str, int] = {}
    for summary in summaries:
        for key, value in summary['status_counts'].items():
            counts[key] = counts.get(key, 0) + value
        for key, value in summary['accepted_ktype_counts'].items():
            accepted[key] = accepted.get(key, 0) + value
    complete = len(selected) == len(active)
    result = {'complete': complete, 'dataset': str(dataset),
              'source_sha256': dataset_manifest['source']['sha256'],
              'reference_sha256': dataset_manifest.get(
                  'reference_input', dataset_manifest['reference'])['sha256'],
              'code_sha256': code_sha256, 'rule_sha256': rule_sha256,
              'rows': sum(item['rows'] for item in summaries),
              'expected_rows': partition['rows'],
              'buckets_completed': len(summaries), 'buckets_total': len(active),
              'distinct_decisions': sum(item['distinct_decisions'] for item in summaries),
              'gated_rows': sum(item['gated_rows'] for item in summaries),
              'candidate_rows': sum(item['candidate_rows'] for item in summaries),
              'logical_candidate_comparisons': sum(
                  item['logical_candidate_comparisons'] for item in summaries),
              'status_counts': counts, 'accepted_ktype_counts': accepted,
              'elapsed_seconds': time.perf_counter() - started,
              'worker_count': workers, 'bucket_count': buckets,
              'checkpoint_hits': sum(bool(item.get('checkpoint_hit')) for item in summaries),
              # A conservative bound: the parent peak plus the largest possible
              # combination of worker peaks, even if they did not overlap.
              'peak_aggregate_rss_upper_bound_bytes': _peak_rss_bytes() + sum(
                  sorted((item['peak_rss_bytes'] for item in summaries),
                         reverse=True)[:workers])}
    if complete and result['rows'] != partition['rows']:
        raise AssertionError('Bounded executor did not produce one result per source row')
    _write_json_atomic(output / 'bounded-manifest.json', result)
    return result


def audit_bounded_results(dataset: Path | str, output: Path | str) -> dict:
    """Independently check saved fragments for row coverage and evidence links."""
    dataset, output = Path(dataset), Path(output)
    expected = json.loads((dataset / 'manifest.json').read_text())['source']['rows']
    seen = np.zeros(expected, dtype=bool)
    counts: dict[str, int] = {}
    accepted: dict[str, int] = {}
    logical_comparisons = 0
    evidence_rows = 0
    bucket_count = 0
    for directory in sorted((output / 'mapped-buckets').glob('bucket-*')):
        done_path = directory / 'done.json'
        if not done_path.exists():
            continue
        done = json.loads(done_path.read_text())
        result_path = directory / 'results.parquet'
        evidence_path = directory / 'candidate_evidence.parquet'
        if not result_path.exists() or not evidence_path.exists():
            raise AssertionError(f'Incomplete bucket {directory.name}')
        frame = pd.read_parquet(result_path, columns=[
            'source_ordinal', 'bucket_id', 'decision_id', 'Match_Status',
            'mapped kType', 'count_in_vio', 'base_candidate_count'])
        ordinals = frame['source_ordinal'].to_numpy(dtype=np.int64)
        if (len(frame) != done['rows'] or len(np.unique(ordinals)) != len(ordinals)
                or np.any(ordinals < 0) or np.any(ordinals >= expected)
                or seen[ordinals].any()):
            raise AssertionError(f'Row coverage failed in {directory.name}')
        seen[ordinals] = True
        if not frame['bucket_id'].eq(done['bucket']).all():
            raise AssertionError(f'Bucket ID mismatch in {directory.name}')
        evidence = pd.read_parquet(evidence_path, columns=['bucket_id', 'decision_id'])
        if (not evidence['bucket_id'].eq(done['bucket']).all()
                or not set(evidence['decision_id']).issubset(set(frame['decision_id']))):
            raise AssertionError(f'Evidence link failed in {directory.name}')
        evidence_rows += len(evidence)
        logical_comparisons += int(frame['base_candidate_count'].fillna(0).sum())
        bucket_count += 1
        for key, value in frame['Match_Status'].value_counts().items():
            counts[str(key)] = counts.get(str(key), 0) + int(value)
        for key, value in frame.loc[frame['count_in_vio'], 'mapped kType'].value_counts().items():
            key = str(int(key))
            accepted[key] = accepted.get(key, 0) + int(value)
    complete = bool(seen.all())
    manifest_path = output / 'bounded-manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest.get('complete') and not complete:
            raise AssertionError('Manifest claims completion but source rows are missing')
        if manifest.get('complete') and (manifest['status_counts'] != counts
                                         or manifest['accepted_ktype_counts'] != accepted
                                         or manifest['logical_candidate_comparisons'] != logical_comparisons):
            raise AssertionError('Saved fragments differ from the completion manifest')
    report = {'complete': complete, 'rows': int(seen.sum()),
              'expected_rows': expected, 'buckets': bucket_count,
              'evidence_rows': evidence_rows,
              'logical_candidate_comparisons': logical_comparisons,
              'status_counts': counts, 'accepted_ktype_counts': accepted}
    _write_json_atomic(output / 'audit.json', report)
    return report


def compare_bounded_runs(left: Path | str, right: Path | str) -> dict:
    """Compare every saved result and compact evidence value across two runs."""
    left, right = Path(left), Path(right)
    first = json.loads((left / 'bounded-manifest.json').read_text())
    second = json.loads((right / 'bounded-manifest.json').read_text())
    if not first['complete'] or not second['complete']:
        raise ValueError('Both bounded runs must be complete')
    checked = ('source_sha256', 'reference_sha256', 'rows', 'status_counts',
               'accepted_ktype_counts', 'logical_candidate_comparisons')
    differences = [name for name in checked if first[name] != second[name]]
    left_buckets = {path.parent.name for path in (left / 'mapped-buckets').glob('bucket-*/done.json')}
    right_buckets = {path.parent.name for path in (right / 'mapped-buckets').glob('bucket-*/done.json')}
    if left_buckets != right_buckets:
        differences.append('bucket set')
    compared = 0
    for name in sorted(left_buckets & right_buckets):
        a, b = left / 'mapped-buckets' / name, right / 'mapped-buckets' / name
        for filename in ('results.parquet', 'candidate_evidence.parquet'):
            left_path, right_path = a / filename, b / filename
            left_parts = sorted(left_path.glob('part-*.parquet')) if left_path.is_dir() else [left_path]
            right_parts = sorted(right_path.glob('part-*.parquet')) if right_path.is_dir() else [right_path]
            if (len(left_parts) != len(right_parts)
                    or [path.name for path in left_parts] != [path.name for path in right_parts]):
                differences.append(f'{name}/{filename}: fragment set')
                continue
            for left_part, right_part in zip(left_parts, right_parts):
                try:
                    pd.testing.assert_frame_equal(
                        pd.read_parquet(left_part), pd.read_parquet(right_part),
                        check_dtype=False, check_categorical=False, check_exact=True)
                except AssertionError:
                    differences.append(f'{name}/{filename}/{left_part.name}')
        compared += 1
    return {'identical': not differences, 'buckets_compared': compared,
            'differences': differences}
