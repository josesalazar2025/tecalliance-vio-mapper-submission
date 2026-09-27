"""Compare every bounded result and decision evidence with algorithm 1.1.0.

Run from the repository root with ``.venv/bin/python scripts/validate_full_baseline.py``.
The validation works one source bucket at a time and checkpoints each comparison.
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from vio_mapper.pipeline import map_vehicles
from vio_mapper.semantic import sha256_file


RESULT_COLUMNS = ('ID', 'mapped kType', 'Match_Status', 'Review_Category',
                  'Match_Reason', 'count_in_vio')


def check_bucket(bucket: int, dataset: str, output: str, checkpoint: str,
                 signature: dict) -> dict:
    dataset, output, checkpoint = Path(dataset), Path(output), Path(checkpoint)
    done = checkpoint / f'bucket-{bucket:04d}.json'
    if done.exists():
        previous = json.loads(done.read_text())
        # Earlier checkpoints used the same value comparison but accumulated
        # duplicate-row evidence first. Both implementations have identical
        # acceptance criteria, so completed checks remain valid.
        inputs = ('source_sha256', 'reference_sha256', 'output_code_sha256')
        if previous.get('complete') and all(
                previous.get(key) == signature[key] for key in inputs):
            return previous
    source = pd.read_parquet(output / 'source-buckets' / f'bucket-{bucket:04d}.parquet')
    reference = pd.read_parquet(dataset / 'reference.parquet')
    directory = output / 'mapped-buckets' / f'bucket-{bucket:04d}'
    actual = pd.read_parquet(directory / 'results.parquet')
    representatives = actual.drop_duplicates('decision_id')[['source_key', 'decision_id']]
    representative_keys = set(representatives['source_key'])
    kept_evidence: list[dict] = []

    def retain_representative(rows: list[dict]) -> None:
        if rows and rows[0]['source_key'] in representative_keys:
            kept_evidence.extend(rows)

    baseline, _ = map_vehicles(
        source, reference, evidence_sink=retain_representative,
        include_score_diagnostics=False)
    actual = actual.sort_values('source_ordinal').reset_index(drop=True)
    baseline = baseline.sort_values('source_ordinal').reset_index(drop=True)
    pd.testing.assert_frame_equal(actual[list(RESULT_COLUMNS)],
                                  baseline[list(RESULT_COLUMNS)], check_dtype=False)

    fragments = sorted((directory / 'candidate_evidence.parquet').glob('part-*.parquet'))
    compact = pd.concat((pd.read_parquet(path) for path in fragments), ignore_index=True)
    compact = compact.drop(columns=['bucket_id', 'source_key', 'ID'], errors='ignore')
    if kept_evidence:
        expected = pd.DataFrame(kept_evidence).merge(
            representatives, on='source_key', how='inner', validate='many_to_one')
        expected = expected.drop(columns=['source_key', 'ID'])
    else:
        expected = compact.iloc[:0].copy()
    if set(expected.columns) != set(compact.columns):
        raise AssertionError(f'Bucket {bucket}: evidence columns differ')
    columns = sorted(expected.columns)
    order = [name for name in ('decision_id', 'review_rank', 'KType') if name in columns]
    expected = expected.sort_values(order).reset_index(drop=True)[columns]
    compact = compact.sort_values(order).reset_index(drop=True)[columns]
    # Parquet and the in-memory baseline use different null sentinels for some
    # all-empty text fields. Treat all missing scalar values as the same value.
    expected = expected.astype(object).where(expected.notna(), None)
    compact = compact.astype(object).where(compact.notna(), None)
    pd.testing.assert_frame_equal(compact, expected, check_dtype=False,
                                  check_categorical=False, check_exact=True)
    result = {**signature, 'bucket': bucket, 'rows': len(actual),
              'decision_evidence_rows': len(compact), 'complete': True}
    temporary = done.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(result, sort_keys=True) + '\n')
    temporary.replace(done)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path,
                        default=Path('data/full_registry_capacity/execution-v3'))
    parser.add_argument('--output-dir', type=Path,
                        default=Path('data/full_registry_capacity/final-benchmark-1'))
    parser.add_argument('--checkpoint-dir', type=Path,
                        default=Path('data/full_registry_capacity/baseline-comparison'))
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--bucket-id', type=int, action='append')
    args = parser.parse_args()
    if args.workers < 1:
        raise ValueError('workers must be positive')
    args.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    bucket_rows = json.loads((args.output_dir / 'source-buckets' /
                              'partition-manifest.json').read_text())['bucket_rows']
    buckets = (sorted(set(args.bucket_id)) if args.bucket_id is not None
               else sorted(map(int, bucket_rows), key=lambda key: bucket_rows[str(key)],
                           reverse=True))
    if set(buckets) - set(map(int, bucket_rows)):
        raise ValueError('Unknown bucket ID')
    signature = {
        'source_sha256': sha256_file(args.dataset / 'source.parquet'),
        'reference_sha256': sha256_file(args.dataset / 'reference.parquet'),
        'output_code_sha256': json.loads((args.output_dir /
                                          'bounded-manifest.json').read_text())['code_sha256'],
        'validator_sha256': sha256_file(Path(__file__)),
    }
    jobs = [(bucket, str(args.dataset), str(args.output_dir),
             str(args.checkpoint_dir), signature) for bucket in buckets]
    if args.workers == 1:
        results = [check_bucket(*job) for job in jobs]
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            results = [future.result() for future in as_completed(
                [pool.submit(check_bucket, *job) for job in jobs])]
    report = {key: value for key, value in signature.items()
              if key != 'validator_sha256'}
    report.update({'validator_sha256s': sorted({
        item['validator_sha256'] for item in results}),
              'complete': len(results) == len(bucket_rows),
              'buckets_checked': len(results), 'rows_checked': sum(x['rows'] for x in results),
              'decision_evidence_rows_checked': sum(
                  x['decision_evidence_rows'] for x in results)})
    (args.checkpoint_dir / 'report.json').write_text(
        json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
