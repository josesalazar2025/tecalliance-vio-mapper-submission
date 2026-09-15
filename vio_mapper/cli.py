"""Command-line entry point: read the two catalogues, map, and write the outputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import openpyxl
import pandas as pd

from .config import (ALGORITHM_VERSION, DEFAULT_REFERENCE_PATH, DEFAULT_REGISTRY,
                     DEFAULT_SOURCE_PATH, EVIDENCE_RETENTION, EXCEL_MAX_ROWS, PROJECT_ROOT,
                     REGISTRIES_DIR, STREAM_ROW_THRESHOLD, Policy,
                     available_registries,
                     registry_file, score_rules, use_registry, vin_rules_path)
from .pipeline import map_vehicles, map_vehicles_streaming
from .reporting import build_sheets, performance_report, write_workbook
from .sources import load_source
from .normalization import normalized_text

DEFAULT_OUTPUT = Path.cwd() / 'mapped_nz_gov_reviewed.xlsx'
DEFAULT_REPORT = Path.cwd() / 'mapping_performance.md'
# Files whose content defines a run, and which must never be overwritten by it.
PROVENANCE_FILES = ('config.py', 'normalization.py', 'sources.py', 'submodel.py',
                    'vin_decoder.py', 'vin_evidence.py', 'chassis_decoder.py',
                    'evidence.py', 'scoring.py',
                    'dominance.py', 'decision.py', 'pipeline.py', 'reporting.py', 'cli.py')


def build_parser() -> argparse.ArgumentParser:
    defaults = Policy()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE_PATH)
    parser.add_argument('--reference', type=Path, default=DEFAULT_REFERENCE_PATH)
    parser.add_argument('--registry', choices=available_registries(), default=DEFAULT_REGISTRY,
                        help='Which register --source comes from, selecting its vocabulary under '
                             'the packaged registry rules (default: %(default)s). The reference '
                             'catalogue is selected by --reference and is unaffected.')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--report', type=Path, default=DEFAULT_REPORT)
    parser.add_argument('--evidence', choices=EVIDENCE_RETENTION, default=defaults.evidence,
                        help="Candidate-evidence retention: all compared candidates, only those of rows needing review "
                             "('unresolved', plus the accepted candidate of matched rows), or only accepted candidates. "
                             'Audit trail only: retention never changes a decision or status.')
    parser.add_argument('--stream-evidence', action=argparse.BooleanOptionalAction, default=None,
                        help='Stream candidate evidence to a sibling CSV instead of holding it in memory. '
                             f'Default: automatic above {STREAM_ROW_THRESHOLD} source rows.')
    return parser


def policy_from_arguments(args) -> Policy:
    """The primary command always runs the documented default decision policy."""
    return Policy(evidence=args.evidence)


def _rule_inputs() -> tuple[Path, ...]:
    """Every rule file the active registry's run reads, in hash order.

    Named per run rather than as a constant because the registry is selected per
    run: the files that define the run are the selected registry's, not the
    default's. A registry with no VIN layouts contributes no VIN file.
    """
    from .config import (RULES_DIR, CATALOGUES_DIR, DEFAULT_CATALOGUE,
                         MANUFACTURER_RULES_DIR, active_registry)

    paths = [RULES_DIR / 'categories.json', RULES_DIR / 'scoring.json',
             RULES_DIR / 'policy_decisions.json',
             CATALOGUES_DIR / f'{DEFAULT_CATALOGUE}.json',
             REGISTRIES_DIR / f'{active_registry()}.json']
    profiles = REGISTRIES_DIR / f'{active_registry()}_submodel_profiles.json'
    vin = vin_rules_path()
    manufacturer_rules = tuple(sorted(MANUFACTURER_RULES_DIR.glob('*.json')))
    return tuple(path for path in (*paths, profiles, vin, *manufacturer_rules)
                 if path is not None and path.exists())


def _check_paths(parser: argparse.ArgumentParser, args) -> None:
    """Refuse to write over an input file or over the run's own other output."""
    package = Path(__file__).resolve().parent
    inputs = {path.resolve() for path in
              (args.source, args.reference, *_rule_inputs(), PROJECT_ROOT / 'main.py',
               *(package / name for name in PROVENANCE_FILES))}
    if (args.output.resolve() in inputs or args.report.resolve() in inputs
            or args.output.resolve() == args.report.resolve()):
        parser.error('Output/report paths must differ from each other and from input/code files')


def run_metadata(results: pd.DataFrame, policy: Policy, source: Path, reference: Path) -> dict:
    """Everything needed to reproduce and audit this run."""
    from .config import active_registry

    package = Path(__file__).resolve().parent
    hashed = (source, reference, *_rule_inputs(), *(package / name for name in PROVENANCE_FILES))
    return {
        'algorithm_version': ALGORITHM_VERSION,
        'registry': active_registry(),
        'run_utc': datetime.now(timezone.utc).isoformat(),
        'python': platform.python_version(), 'pandas': pd.__version__,
        'openpyxl': openpyxl.__version__,
        'policy': json.dumps(policy.__dict__, sort_keys=True),
        'vio_scope': 'Accepted distinct IDs only; not the complete source population',
        'source_distinct_ids': int(results.ID.map(normalized_text).nunique()),
        'accepted_distinct_ids': int(results.count_in_vio.sum()),
        'unresolved_distinct_ids': int(results.ID.map(normalized_text).nunique()
                                       - results.count_in_vio.sum()),
        'power_tolerance_dependent_distinct_ids':
            int((results.count_in_vio & results.selected_power_tolerance_used).sum()),
        **{f'sha256_{path.name}': hashlib.sha256(path.read_bytes()).hexdigest() for path in hashed},
    }


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    use_registry(args.registry)
    _check_paths(parser, args)
    source = load_source(args.source)
    reference = pd.read_excel(args.reference, dtype=object)
    policy = policy_from_arguments(args)
    stream = len(source) > STREAM_ROW_THRESHOLD if args.stream_evidence is None else args.stream_evidence
    evidence_path = args.output.with_name(args.output.stem + '_candidate_evidence.csv')
    if stream:
        results, evidence, evidence_rows = map_vehicles_streaming(
            source, reference, policy, evidence_path, include_score_diagnostics=False)
    else:
        results, evidence = map_vehicles(
            source, reference, policy, include_score_diagnostics=False)
        evidence_rows = len(evidence)
        if evidence_rows >= EXCEL_MAX_ROWS:
            raise ValueError(f'{evidence_rows} candidate-evidence rows exceed the {EXCEL_MAX_ROWS} '
                             'worksheet limit; rerun with --stream-evidence, or narrow --evidence retention')
    metadata = run_metadata(results, policy, args.source, args.reference)
    sheets = build_sheets(results, evidence, policy, metadata)
    write_workbook(sheets, args.output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(performance_report(results, metadata))
    print(sheets['Summary'].to_string(index=False))
    print(f"Distinct vehicles in accepted VIO: {int(results['count_in_vio'].sum())}")
    print(f'Workbook: {args.output}\nReport: {args.report}')


if __name__ == '__main__':
    main()
