"""Self-contained contracts for the reviewer-facing mapping workflow."""
import hashlib
import json
from pathlib import Path

import pandas as pd

from vio_mapper.cli import main
from vio_mapper.config import (ALL_CANDIDATES_CONTRADICTED, AMBIGUOUS, MATCHED,
                               NOT_SEPARATED, PROJECT_ROOT, RULES_DIR, available_registries)
from vio_mapper.pipeline import map_vehicles
from vio_mapper.sources import load_source, prepare_reference, prepare_source


SOURCE_ROW = {
    'ID': 1,
    'MAKE': 'HYUNDAI',
    'MODEL': 'KONA',
    'SUBMODEL': '',
    'VEHICLE_YEAR': 2020,
    'CC_RATING': 1999,
    'MOTIVE_POWER': 'PETROL',
    'POWER_RATING': 110,
    'ENGINE_NUMBER': 'G4NA123456',
    'BODY_TYPE': 'HATCHBACK',
}

REFERENCE_ROW = {
    'KType': 1,
    'Brand': 'HYUNDAI',
    'Sales_designation': 'KONA',
    'Construction_from': 201801,
    'Construction_to': 202212,
    'Capacity_cubic': 1999,
    'Fuel_type': 'Petrol',
    'Maximum_output_KW': 110,
    'Engine_code': 'G4NA',
    'Kind_of_structure': 'Hatchback',
    'Drive_system': 'Front-Wheel Drive',
    'Type_designation': 'OS',
    'Model_design': 'OS',
}


def source(**changes):
    return prepare_source(pd.DataFrame([{**SOURCE_ROW, **changes}]))


def reference(*rows):
    values = rows or (
        REFERENCE_ROW,
        {**REFERENCE_ROW, 'KType': 2, 'Maximum_output_KW': 120, 'Engine_code': 'G4NB'},
    )
    return pd.DataFrame(values)


def test_rules_ship_with_the_package():
    assert available_registries() == ('nz',)


def test_public_rule_sources_match_their_recorded_hashes():
    for rule_path in RULES_DIR.rglob('*.json'):
        rule = json.loads(rule_path.read_text())
        for source_name, source in rule.get('sources', {}).items():
            local_copy = source.get('local_copy', '')
            if not local_copy.startswith('docs/'):
                continue
            path = PROJECT_ROOT / local_copy
            assert path.exists(), f'{source_name}: missing {path}'
            assert hashlib.sha256(path.read_bytes()).hexdigest() == source['sha256']


def test_unique_supported_candidate_is_assigned():
    results, evidence = map_vehicles(source(), reference())
    assert results.loc[0, 'Match_Status'] == MATCHED
    assert results.loc[0, 'mapped kType'] == 1
    assert bool(results.loc[0, 'count_in_vio'])
    assert evidence.set_index('KType').loc[1, 'selected'] == True  # noqa: E712


def test_indistinguishable_candidates_are_left_for_review():
    results, _ = map_vehicles(source(), reference(
        REFERENCE_ROW, {**REFERENCE_ROW, 'KType': 2}))
    assert results.loc[0, 'Match_Status'] == AMBIGUOUS
    assert results.loc[0, 'Review_Category'] == NOT_SEPARATED
    assert pd.isna(results.loc[0, 'mapped kType'])


def test_known_contradictions_block_every_candidate():
    contradicted = reference(
        {**REFERENCE_ROW, 'Maximum_output_KW': 120},
        {**REFERENCE_ROW, 'KType': 2, 'Maximum_output_KW': 130},
    )
    results, evidence = map_vehicles(source(), contradicted)
    assert results.loc[0, 'Match_Status'] == ALL_CANDIDATES_CONTRADICTED
    assert pd.isna(results.loc[0, 'mapped kType'])
    assert not evidence['compatible'].any()


def test_unknown_information_never_becomes_agreement():
    incomplete = source(POWER_RATING=None)
    results, evidence = map_vehicles(incomplete, reference())
    assert pd.isna(results.loc[0, 'mapped kType'])
    assert set(evidence['power']) == {'unknown'}


def test_duplicate_vehicle_is_counted_once():
    duplicated = prepare_source(pd.DataFrame([SOURCE_ROW, SOURCE_ROW]))
    results, _ = map_vehicles(duplicated, reference())
    assert results['mapped kType'].notna().all()
    assert int(results['count_in_vio'].sum()) == 1
    assert int(results['duplicate_of'].ne('').sum()) == 1


def test_conflicting_duplicate_is_never_assigned():
    conflicting = prepare_source(pd.DataFrame([
        SOURCE_ROW,
        {**SOURCE_ROW, 'POWER_RATING': 120},
    ]))
    results, _ = map_vehicles(conflicting, reference())
    assert results['mapped kType'].isna().all()
    assert results['duplicate_id_conflict'].all()


def test_reference_validation_rejects_duplicate_ktype():
    duplicated = reference(REFERENCE_ROW, REFERENCE_ROW)
    try:
        prepare_reference(duplicated)
    except ValueError as error:
        assert 'unique positive integer' in str(error)
    else:
        raise AssertionError('duplicate kType was accepted')


def test_cli_writes_auditable_workbook_and_report(tmp_path: Path):
    source_path = tmp_path / 'source.xlsx'
    reference_path = tmp_path / 'reference.xlsx'
    output_path = tmp_path / 'mapped.xlsx'
    report_path = tmp_path / 'report.md'
    pd.DataFrame([SOURCE_ROW]).to_excel(source_path, index=False)
    reference().to_excel(reference_path, index=False)

    main([
        '--source', str(source_path),
        '--reference', str(reference_path),
        '--output', str(output_path),
        '--report', str(report_path),
    ])

    assert output_path.exists() and report_path.exists()
    workbook = pd.ExcelFile(output_path)
    assert {'Results', 'Candidate_Evidence', 'Review_Queue', 'VIO', 'Metadata'} <= set(
        workbook.sheet_names)
    metadata = pd.read_excel(output_path, sheet_name='Metadata').set_index('property')['value']
    assert metadata['algorithm_version'] == '1.0.0'
    assert 'acceptance coverage' in report_path.read_text()


def test_csv_loader_preserves_literal_na_and_row_origin(tmp_path: Path):
    path = tmp_path / 'source.csv'
    pd.DataFrame([{**SOURCE_ROW, 'ENGINE_NUMBER': 'NA'}]).to_csv(path, index=False)
    loaded = load_source(path)
    assert loaded.loc[0, 'ENGINE_NUMBER'] == 'NA'
    assert loaded.loc[0, 'source_key'] == 'source.csv!2'
