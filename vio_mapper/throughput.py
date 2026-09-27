"""Commands for preparing, running, and comparing throughput-optimized jobs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .columnar import load_execution_dataset, prepare_execution_dataset
from .config import EVIDENCE_RETENTION, Policy
from .optimized import ExecutionOptions, map_vehicles_optimized
from .semantic import (build_manifest, compare_manifests, sha256_file, sha256_files,
                       write_manifest)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare', help='build a reusable Parquet execution dataset')
    prepare.add_argument('--source', type=Path, required=True)
    prepare.add_argument('--reference', type=Path, required=True)
    prepare.add_argument('--output-dir', type=Path, required=True)
    prepare.add_argument('--ebay-reference', action='store_true',
                         help='adapt the recorded eBay capacity-test workbook before preparation')

    run = commands.add_parser('run', help='map a prepared execution dataset')
    run.add_argument('--dataset', type=Path, required=True)
    run.add_argument('--output-dir', type=Path, required=True)
    run.add_argument('--workers', type=int, default=1)
    run.add_argument('--evidence', choices=EVIDENCE_RETENTION, default='all')
    run.add_argument('--expand-evidence', action=argparse.BooleanOptionalAction, default=False,
                     help='Expand compact decision evidence to every source row (default: no)')
    run.add_argument('--bulk-gate', action=argparse.BooleanOptionalAction, default=True)
    run.add_argument('--group-decisions', action=argparse.BooleanOptionalAction, default=True)
    run.add_argument('--partitioned', action=argparse.BooleanOptionalAction, default=True)

    bounded = commands.add_parser('run-bounded',
                                  help='map a full registry in resumable disk buckets')
    bounded.add_argument('--dataset', type=Path, required=True)
    bounded.add_argument('--output-dir', type=Path, required=True)
    bounded.add_argument('--buckets', type=int, default=512)
    bounded.add_argument('--workers', type=int, default=1)
    bounded.add_argument('--max-buckets', type=int,
                         help='run only this many buckets for a validation slice')
    bounded.add_argument('--bucket-id', type=int, action='append', dest='bucket_ids',
                         help='run a specific bucket; may be repeated')
    bounded.add_argument('--evidence', choices=EVIDENCE_RETENTION, default='all')

    audit = commands.add_parser('audit-bounded',
                                help='verify every saved source row and evidence link')
    audit.add_argument('--dataset', type=Path, required=True)
    audit.add_argument('--output-dir', type=Path, required=True)

    bounded_compare = commands.add_parser('compare-bounded',
                                          help='compare all result and evidence fragments')
    bounded_compare.add_argument('left', type=Path)
    bounded_compare.add_argument('right', type=Path)

    manifest = commands.add_parser('manifest', help='hash existing baseline outputs')
    manifest.add_argument('--results', type=Path, required=True)
    manifest.add_argument('--evidence-file', type=Path, required=True)
    manifest.add_argument('--source', type=Path, required=True)
    manifest.add_argument('--reference', type=Path, required=True)
    manifest.add_argument('--output', type=Path, required=True)

    compare = commands.add_parser('compare', help='compare two semantic manifests')
    compare.add_argument('baseline', type=Path)
    compare.add_argument('candidate', type=Path)
    return parser


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == 'prepare':
        reference = args.reference
        if args.ebay_reference:
            from .ebay_reference import build_ebay_reference
            reference_frame, diagnostics = build_ebay_reference(reference)
            reference = args.output_dir.parent / (args.output_dir.name + '-ebay-reference.parquet')
            reference_frame.to_parquet(reference, index=False, engine='pyarrow', compression='zstd')
        manifest = prepare_execution_dataset(args.source, reference, args.output_dir)
        if args.ebay_reference:
            manifest['reference_adapter'] = diagnostics
            manifest['reference_input'] = {
                'path': str(args.reference), 'sha256': sha256_file(args.reference)}
            (args.output_dir / 'manifest.json').write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + '\n')
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return
    if args.command == 'compare':
        differences = compare_manifests(json.loads(args.baseline.read_text()),
                                        json.loads(args.candidate.read_text()))
        if differences:
            raise SystemExit('Semantic manifests differ:\n' + '\n'.join(differences))
        print('Semantic manifests are identical.')
        return
    if args.command == 'manifest':
        def read_frame(path: Path) -> pd.DataFrame:
            return (pd.read_parquet(path) if path.suffix.lower() == '.parquet'
                    else pd.read_csv(path, keep_default_na=False).replace('', pd.NA))
        manifest_value = build_manifest(
            read_frame(args.results), read_frame(args.evidence_file),
            source_path=args.source, reference_path=args.reference)
        write_manifest(manifest_value, args.output)
        print(json.dumps(manifest_value, indent=2, sort_keys=True))
        return

    if args.command == 'run-bounded':
        from .bounded import run_bounded_dataset
        result = run_bounded_dataset(
            args.dataset, args.output_dir, buckets=args.buckets,
            workers=args.workers, policy=Policy(evidence=args.evidence),
            max_buckets=args.max_buckets, bucket_ids=args.bucket_ids)
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    if args.command == 'audit-bounded':
        from .bounded import audit_bounded_results
        print(json.dumps(audit_bounded_results(args.dataset, args.output_dir),
                         indent=2, sort_keys=True))
        return
    if args.command == 'compare-bounded':
        from .bounded import compare_bounded_runs
        result = compare_bounded_runs(args.left, args.right)
        print(json.dumps(result, indent=2, sort_keys=True))
        if not result['identical']:
            raise SystemExit(1)
        return

    source, reference, dataset_manifest = load_execution_dataset(args.dataset)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = args.output_dir / 'partitions'
    policy = Policy(evidence=args.evidence)
    results, evidence, metrics = map_vehicles_optimized(
        source, reference, policy,
        options=ExecutionOptions(workers=args.workers, checkpoint_dir=checkpoint,
                                 expand_evidence=args.expand_evidence,
                                 bulk_gate=args.bulk_gate,
                                 group_decisions=args.group_decisions,
                                 partitioned=args.partitioned),
        include_score_diagnostics=False)
    results.to_parquet(args.output_dir / 'results.parquet', index=False,
                       engine='pyarrow', compression='zstd')
    evidence.to_parquet(args.output_dir / 'candidate_evidence.parquet', index=False,
                        engine='pyarrow', compression='zstd')
    from .cli import PROVENANCE_FILES, _rule_inputs
    package = Path(__file__).resolve().parent
    manifest = build_manifest(
        results, evidence, source_path=args.dataset / 'source.parquet',
        reference_path=args.dataset / 'reference.parquet',
        timings=metrics.timings_seconds, metrics={
            key: value for key, value in vars(metrics).items() if key != 'timings_seconds'
        }, workers=args.workers,
        rule_hash=sha256_files(_rule_inputs()),
        code_hash=sha256_files(package / name for name in PROVENANCE_FILES))
    # Preserve hashes of the immutable external inputs rather than presenting
    # hashes of their execution encoding as if they were the originals.
    manifest['source_sha256'] = dataset_manifest['source']['sha256']
    manifest['reference_sha256'] = dataset_manifest.get(
        'reference_input', dataset_manifest['reference'])['sha256']
    write_manifest(manifest, args.output_dir / 'benchmark-manifest.json')
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
