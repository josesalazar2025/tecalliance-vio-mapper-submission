"""Self-contained contracts for the reviewer-facing mapping workflow."""
import hashlib
import json
from pathlib import Path

import pandas as pd

from vio_mapper.cli import main
from vio_mapper.chassis_decoder import decode_chassis_model
from vio_mapper.config import (ALL_CANDIDATES_CONTRADICTED, ALL_CONTRADICTED, AMBIGUOUS, CONFLICT,
                               MATCHED, NEAR_POWER_ONLY, NO_CANDIDATE_IN_REFERENCE, NOT_SEPARATED,
                               PROJECT_ROOT, RULES_DIR, Policy, available_registries)
from vio_mapper.pipeline import map_vehicles, map_vehicles_streaming
from vio_mapper.reporting import review_queue
from vio_mapper.review_ranking import order_review_candidates
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

XTRAIL_HYBRID_SOURCE = {
    **SOURCE_ROW,
    'ID': 2,
    'MAKE': 'NISSAN',
    'MODEL': 'X-TRAIL',
    'SUBMODEL': 'HYBRID',
    'CC_RATING': 1997,
    'MOTIVE_POWER': 'PETROL HYBRID',
    'POWER_RATING': 138,
    'ENGINE_NUMBER': 'MR20-RM31-727508C',
    'BODY_TYPE': 'STATION WAGON',
    'CHASSIS7': 'HNT32-1',
}

XTRAIL_HYBRID_REFERENCES = (
    {**REFERENCE_ROW, 'KType': 124054, 'Brand': 'NISSAN',
     'Sales_designation': 'X-TRAIL', 'Construction_from': 201611,
     'Construction_to': None, 'Capacity_cubic': 1997,
     'Fuel_type': 'Petrol/Electric', 'Maximum_output_KW': 138,
     'Engine_code': 'MR20DD; RM31', 'Kind_of_structure': 'SUV',
     'Drive_system': 'Front-Wheel Drive', 'Type_design': 'HT32',
     'Type_designation': 'Hybrid', 'Model_design': 'T32RR;T32R;T32_'},
    {**REFERENCE_ROW, 'KType': 124055, 'Brand': 'NISSAN',
     'Sales_designation': 'X-TRAIL', 'Construction_from': 201611,
     'Construction_to': 202207, 'Capacity_cubic': 1997,
     'Fuel_type': 'Petrol/Electric', 'Maximum_output_KW': 138,
     'Engine_code': 'MR20DD; RM31', 'Kind_of_structure': 'SUV',
     'Drive_system': 'All-wheel Drive', 'Type_design': 'HNT32',
     'Type_designation': 'Hybrid', 'Model_design': 'T32RR;T32R;T32_'},
)

MERCEDES_SOURCE = {
    **SOURCE_ROW,
    'ID': 3,
    'MAKE': 'MERCEDES-BENZ',
    'MODEL': 'C-CLASS',
    'SUBMODEL': 'C 200 2.0P/9AT',
    'CC_RATING': 1991,
    'MOTIVE_POWER': 'PETROL',
    'POWER_RATING': 150,
    'ENGINE_NUMBER': '264920123456',
    'BODY_TYPE': 'SALOON',
    'VIN11': 'WDD2050802R',
    'MVMA_MODEL_CODE': '20508022-NZ5',
}

# Synthetic candidate rows used only to prove that the decoder compares an MVMA
# hint with whatever Type_design the supplied reference carries. These IDs are
# deliberately unrelated to the real extract: no model-code -> kType mapping is
# allowed in application code or rule data.
MERCEDES_REFERENCES = tuple(
    {**REFERENCE_ROW, 'KType': ktype, 'Brand': 'MERCEDES-BENZ',
     'Sales_designation': 'C-CLASS', 'Construction_from': 201806,
     'Construction_to': 202304, 'Capacity_cubic': 1991,
     'Fuel_type': 'Petrol', 'Maximum_output_KW': 150,
     'Engine_code': 'M 264.920', 'Kind_of_structure': body,
     'Drive_system': 'Rear-Wheel Drive', 'Type_design': type_code,
     'Type_designation': 'C 200', 'Model_design': model_design}
    for ktype, type_code, model_design, body in (
        (900001, '205.080', 'W205', 'Saloon'),
        (900002, '205.280', 'S205', 'Estate'),
        (900003, '205.380', 'C205', 'Coupe'),
        (900004, '205.480', 'A205', 'Convertible'),
    )
)


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


def test_unresolved_candidates_use_text_similarity_for_review_order_only():
    vehicle = source(SUBMODEL='KONA PREMIUM SPORT')
    candidates = reference(
        {**REFERENCE_ROW, 'Type_designation': 'BASE'},
        {**REFERENCE_ROW, 'KType': 2, 'Type_designation': 'PREMIUM SPORT'},
    )

    results, evidence = map_vehicles(vehicle, candidates)

    assert results.loc[0, 'Match_Status'] == AMBIGUOUS
    assert pd.isna(results.loc[0, 'mapped kType'])
    assert evidence['KType'].tolist() == [2, 1]
    assert evidence['review_rank'].tolist() == [1, 2]
    scores = evidence.set_index('KType')['text_similarity_score']
    assert scores[2] > scores[1]
    assert set(evidence['text_similarity_method']) == {
        'mean(ratio, token_sort_ratio); RapidFuzz'}


def test_matched_rows_do_not_calculate_review_similarity():
    results, evidence = map_vehicles(source(SUBMODEL='PREMIUM SPORT'), reference())

    assert results.loc[0, 'Match_Status'] == MATCHED
    assert evidence['text_similarity_score'].isna().all()
    assert set(evidence['text_similarity_method']) == {''}


def test_near_power_candidate_outranks_exact_power_with_vin_generation_conflict():
    details = [
        {'KType': 124043, 'selected': False, 'compatible': False,
         'disagreements': 'vin_generation',
         'version_criteria_agreed': 'capacity; fuel; power',
         'variant_criteria_agreed': 'drive; engine',
         'power_difference_kw': 0, 'power_within_triage_band': False,
         'vin_generation': 'disagree',
         'text_similarity_score': 9.1},
        {'KType': 107384, 'selected': False, 'compatible': False,
         'disagreements': 'power; vin_drive',
         'version_criteria_agreed': 'capacity; fuel',
         'variant_criteria_agreed': 'engine',
         'power_difference_kw': -1, 'power_within_triage_band': True,
         'vin_generation': 'agree', 'vin_drive': 'disagree',
         'text_similarity_score': 31.6},
        {'KType': 17194, 'selected': False, 'compatible': False,
         'disagreements': 'power',
         'version_criteria_agreed': 'capacity; fuel',
         'variant_criteria_agreed': 'drive; engine',
         'power_difference_kw': -4, 'power_within_triage_band': False,
         'vin_generation': 'unknown',
         'text_similarity_score': 18.0},
        {'KType': 107383, 'selected': False, 'compatible': False,
         'disagreements': 'power',
         'version_criteria_agreed': 'capacity; fuel',
         'variant_criteria_agreed': 'drive; engine',
         'power_difference_kw': -1, 'power_within_triage_band': True,
         'vin_generation': 'agree',
         'text_similarity_score': 32.4},
    ]

    order_review_candidates(details, selected=None, proposed=None, lead=None,
                            shortlist={17194, 124043, 107383, 107384}, remaining=set(),
                            unresolved=True)

    assert [candidate['KType'] for candidate in details] == [107383, 107384, 17194, 124043]
    assert details[0]['review_near_power_only'] is True
    assert details[1]['review_configuration_conflicts'] == 'vin_drive'
    assert details[1]['review_identity_agreements'] == 'vin_generation'
    assert details[3]['review_identity_conflicts'] == 'vin_generation'


def test_known_contradictions_block_every_candidate():
    contradicted = reference(
        {**REFERENCE_ROW, 'Maximum_output_KW': 120},
        {**REFERENCE_ROW, 'KType': 2, 'Maximum_output_KW': 130},
    )
    results, evidence = map_vehicles(source(), contradicted)
    assert results.loc[0, 'Match_Status'] == ALL_CANDIDATES_CONTRADICTED
    assert pd.isna(results.loc[0, 'mapped kType'])
    assert not evidence['compatible'].any()


def test_absent_make_model_has_no_reference_candidate():
    results, evidence = map_vehicles(source(MODEL='NOT IN REFERENCE'), reference())
    assert results.loc[0, 'Match_Status'] == NO_CANDIDATE_IN_REFERENCE
    assert evidence.empty


def test_unknown_information_never_becomes_agreement():
    incomplete = source(POWER_RATING=None)
    results, evidence = map_vehicles(incomplete, reference())
    assert pd.isna(results.loc[0, 'mapped kType'])
    assert set(evidence['power']) == {'unknown'}


def test_more_complete_candidate_does_not_defeat_compatible_sibling():
    candidates = reference(
        REFERENCE_ROW,
        {**REFERENCE_ROW, 'KType': 2, 'Maximum_output_KW': None},
    )
    results, evidence = map_vehicles(source(), candidates)
    assert results.loc[0, 'Match_Status'] == AMBIGUOUS
    assert pd.isna(results.loc[0, 'mapped kType'])
    assert evidence['compatible'].all()


def test_sufficiency_is_invariant_to_irrelevant_catalogue_rows():
    vehicle = source(SUBMODEL='AWD', ENGINE_NUMBER='')
    supported = {**REFERENCE_ROW, 'Drive_system': 'All-wheel Drive'}
    only = reference(supported)
    with_irrelevant = reference(
        supported,
        {**supported, 'KType': 2, 'Maximum_output_KW': 130, 'Engine_code': 'G4NB'},
    )
    one_result, _ = map_vehicles(vehicle, only)
    many_result, _ = map_vehicles(vehicle, with_irrelevant)
    assert one_result.loc[0, 'Match_Status'] == MATCHED
    assert many_result.loc[0, 'Match_Status'] == MATCHED
    assert one_result.loc[0, 'mapped kType'] == many_result.loc[0, 'mapped kType'] == 1


def test_unreviewed_body_pair_is_unknown_not_negative_evidence():
    vehicle = source(BODY_TYPE='SALOON')
    candidates = reference({**REFERENCE_ROW, 'Kind_of_structure': 'SUV'})
    _, evidence = map_vehicles(vehicle, candidates)
    assert evidence.loc[0, 'body'] == 'unknown'


def test_provisional_rounding_and_chronology_readings_do_not_veto():
    vehicle = source(SUBMODEL='3.0 AWD', VEHICLE_YEAR=2020)
    later_candidate = {**REFERENCE_ROW, 'Construction_from': 202201,
                       'Construction_to': 202412, 'Drive_system': 'All-wheel Drive'}
    _, evidence = map_vehicles(vehicle, reference(later_candidate), Policy(year_mode='soft'))
    assert evidence.loc[0, 'submodel_capacity'] == 'apparent mismatch (review only)'
    assert evidence.loc[0, 'chronology'] == 'unknown'
    assert bool(evidence.loc[0, 'compatible'])


def test_default_year_gate_excludes_only_candidates_starting_later():
    vehicle = source(VEHICLE_YEAR=2020)
    older = {**REFERENCE_ROW, 'KType': 1, 'Construction_from': 201001,
             'Construction_to': 201512}
    later = {**REFERENCE_ROW, 'KType': 2, 'Construction_from': 202101,
             'Construction_to': 202412}
    results, evidence = map_vehicles(vehicle, reference(older, later))
    assert results.loc[0, 'mapped kType'] == 1
    assert set(evidence['KType']) == {1}


def test_documented_chassis_prefix_is_prioritized_as_candidate_veto():
    # Power is deliberately absent: the documented manufacturer model code is
    # the discriminator and must not be demoted by an unrelated missing field.
    vehicle = prepare_source(pd.DataFrame([{**XTRAIL_HYBRID_SOURCE, 'POWER_RATING': None}]))
    results, evidence = map_vehicles(vehicle, reference(*XTRAIL_HYBRID_REFERENCES))
    compared = evidence.set_index('KType')['chassis_model_comparison']
    assert compared.to_dict() == {124054: 'disagree', 124055: 'agree'}
    assert results.loc[0, 'mapped kType'] == 124055
    assert results.loc[0, 'chassis_decoder_model_code'] == 'HNT32'
    assert results.loc[0, 'acceptance_route'] == 'criterion dominance'
    assert 'manufacturer model code HNT32 decoded from CHASSIS7' in results.loc[0, 'Match_Reason']


def test_missing_or_unrecognized_chassis_prefix_is_neutral():
    candidates = reference(*XTRAIL_HYBRID_REFERENCES)
    for value in (None, 'UNKNOWN'):
        vehicle = prepare_source(pd.DataFrame([{**XTRAIL_HYBRID_SOURCE, 'CHASSIS7': value}]))
        results, evidence = map_vehicles(vehicle, candidates)
        assert results.loc[0, 'Match_Status'] == AMBIGUOUS
        assert set(evidence['chassis_model_comparison']) == {'unknown'}


def test_mercedes_mvma_type_names_likely_candidate_without_assigning():
    vehicle = prepare_source(pd.DataFrame([
        {**MERCEDES_SOURCE, 'VIN11': 'W1K2050802R'},
    ]))
    results, evidence = map_vehicles(vehicle, reference(*MERCEDES_REFERENCES))
    compared = evidence.set_index('KType')['chassis_model_hint_comparison']
    assert compared.to_dict() == {900001: 'agree', 900002: 'disagree',
                                  900003: 'disagree', 900004: 'disagree'}
    assert results.loc[0, 'Match_Status'] == AMBIGUOUS
    assert pd.isna(results.loc[0, 'mapped kType'])
    assert results.loc[0, 'proposed_kType'] == 900001
    assert results.loc[0, 'chassis_decoder_source_field'] == 'MVMA_MODEL_CODE'
    assert results.loc[0, 'chassis_decoder_model_code'] == '205080'
    assert results.loc[0, 'chassis_decoder_decision_role'] == 'proposal_only'
    assert set(evidence['MVMA_MODEL_CODE_comparison']) == {'unknown'}
    assert set(evidence['MVMA_MODEL_CODE_tokens']) == {''}
    assert results.loc[0, 'parsed_identifiers'] == '{}'
    assert 'most likely candidate for review' in results.loc[0, 'Match_Reason']


def test_mercedes_wdd_fin_type_assigns_matching_type_design():
    vehicle = prepare_source(pd.DataFrame([MERCEDES_SOURCE]))
    results, evidence = map_vehicles(vehicle, reference(*MERCEDES_REFERENCES))
    compared = evidence.set_index('KType')['chassis_model_comparison']
    assert compared.to_dict() == {900001: 'agree', 900002: 'disagree',
                                  900003: 'disagree', 900004: 'disagree'}
    assert results.loc[0, 'Match_Status'] == MATCHED
    assert results.loc[0, 'mapped kType'] == 900001
    assert pd.isna(results.loc[0, 'proposed_kType'])
    assert results.loc[0, 'chassis_decoder_source_field'] == 'VIN11'
    assert results.loc[0, 'chassis_decoder_model_code'] == '205080'
    assert results.loc[0, 'chassis_decoder_decision_role'] == 'candidate_veto'
    assert evidence.set_index('KType').loc[900001, 'VIN11_tokens'] == '205080'


def test_conflicting_mercedes_wdd_fin_and_mvma_code_stops_assignment():
    vehicle = prepare_source(pd.DataFrame([
        {**MERCEDES_SOURCE, 'MVMA_MODEL_CODE': '20538022-NZ5'},
    ]))
    results, evidence = map_vehicles(vehicle, reference(*MERCEDES_REFERENCES))
    assert results.loc[0, 'Match_Status'] == CONFLICT
    assert pd.isna(results.loc[0, 'mapped kType'])
    assert results.loc[0, 'chassis_decoder_status'] == 'conflicting'
    assert set(evidence['chassis_model_comparison']) == {'unknown'}
    assert 'identifiers disagree' in results.loc[0, 'Match_Reason'].lower()


def test_mercedes_vin_without_mvma_remains_undecoded_and_neutral():
    vehicle = prepare_source(pd.DataFrame([
        {**MERCEDES_SOURCE, 'VIN11': 'W1K2050802R', 'MVMA_MODEL_CODE': None},
    ]))
    results, evidence = map_vehicles(vehicle, reference(*MERCEDES_REFERENCES))
    assert results.loc[0, 'Match_Status'] == AMBIGUOUS
    assert pd.isna(results.loc[0, 'mapped kType'])
    assert set(evidence['chassis_model_comparison']) == {'unknown'}
    assert set(evidence['chassis_model_hint_comparison']) == {'unknown'}
    assert results.loc[0, 'vin_helper_profile'] is None


def test_mercedes_mvma_hint_never_excuses_capacity_conflict():
    vehicle = prepare_source(pd.DataFrame([
        {**MERCEDES_SOURCE, 'VIN11': 'W1K2053802F',
         'MVMA_MODEL_CODE': '20538022-NZ5', 'CC_RATING': 1491},
    ]))
    results, evidence = map_vehicles(vehicle, reference(*MERCEDES_REFERENCES))
    target = evidence.set_index('KType').loc[900003]
    assert target['chassis_model_comparison'] == 'unknown'
    assert target['chassis_model_hint_comparison'] == 'agree'
    assert target['capacity'] == 'disagree'
    assert pd.isna(results.loc[0, 'mapped kType'])
    assert pd.isna(results.loc[0, 'proposed_kType'])


def test_submodel_litres_create_review_shortlist_after_candidate_gates():
    vehicle = prepare_source(pd.DataFrame([
        {**MERCEDES_SOURCE, 'SUBMODEL': 'C 200 1.5P/9AT', 'CC_RATING': 1491,
         'VIN11': 'W1K2050802R', 'MVMA_MODEL_CODE': '20538022-NZ5'},
    ]))
    candidates = reference(
        {**MERCEDES_REFERENCES[0], 'KType': 11, 'Capacity_litre': '1,5',
         'Capacity_cubic': 1497, 'Maximum_output_KW': 135,
         'Fuel_type': 'Petrol/Electric', 'Engine_code': 'M 264.915',
         'Type_design': '205.077'},
        {**MERCEDES_REFERENCES[1], 'KType': 12, 'Capacity_litre': '1.5',
         'Capacity_cubic': 1497, 'Maximum_output_KW': 135,
         'Fuel_type': 'Petrol/Electric', 'Engine_code': 'M 264.915',
         'Type_design': '205.277'},
        {**MERCEDES_REFERENCES[2], 'KType': 20, 'Capacity_litre': '2,0',
         'Type_design': '205.380'},
    )

    results, evidence = map_vehicles(vehicle, candidates)

    compared = evidence.set_index('KType')['submodel_capacity_litre'].to_dict()
    assert compared == {11: 'agree', 12: 'agree', 20: 'disagree'}
    assert results.loc[0, 'Match_Status'] == ALL_CANDIDATES_CONTRADICTED
    assert pd.isna(results.loc[0, 'proposed_kType'])
    assert results.loc[0, 'triage_lead_alternatives'] == '11; 12'
    assert 'decimal point and comma spellings are equivalent' in results.loc[0, 'triage_lead_basis']


def test_chassis_decoder_is_scoped_to_manufacturer_and_model():
    wrong_model = {**XTRAIL_HYBRID_SOURCE, 'MODEL': 'OTHER'}
    decoded = decode_chassis_model(wrong_model)
    assert decoded['status'] == 'unavailable'
    assert decoded['model_code'] is None


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


def test_conflicting_duplicate_has_one_review_task_linking_every_row():
    conflicting = prepare_source(pd.DataFrame([
        SOURCE_ROW,
        {**SOURCE_ROW, 'POWER_RATING': 120},
    ]))
    results, _ = map_vehicles(conflicting, reference())
    queue = review_queue(results)
    assert len(queue) == 1
    assert queue.loc[0, 'vehicles'] == 1
    assert queue.loc[0, 'source_rows'] == 'input!2; input!3'
    assert int(results['count_in_vio'].sum()) + int(queue['vehicles'].sum()) == 1


def test_provided_labels_do_not_change_duplicate_identity_or_decisions():
    rows = pd.DataFrame([
        {**SOURCE_ROW, 'mapped kType': 1},
        SOURCE_ROW,
    ])
    prepared = prepare_source(rows)
    assert not prepared['duplicate_id_conflict'].any()
    results, _ = map_vehicles(prepared, reference())
    assert results['mapped kType'].eq(1).all()


def test_conflicting_labels_are_reported_separately_from_vehicle_facts():
    rows = pd.DataFrame([
        {**SOURCE_ROW, 'mapped kType': 1},
        {**SOURCE_ROW, 'mapped kType': 2},
    ])
    prepared = prepare_source(rows)
    assert not prepared['duplicate_id_conflict'].any()
    assert prepared['provided_label_conflict'].all()
    results, _ = map_vehicles(prepared, reference())
    assert results['mapped kType'].eq(1).all()


def test_normalized_ids_share_one_identity_without_false_conflict():
    prepared = prepare_source(pd.DataFrame([
        {**SOURCE_ROW, 'ID': 'abc'},
        {**SOURCE_ROW, 'ID': ' ABC '},
    ]))
    assert not prepared['duplicate_id_conflict'].any()
    assert prepared['canonical_record'].sum() == 1
    results, _ = map_vehicles(prepared, reference())
    assert results['mapped kType'].notna().all()
    assert results['count_in_vio'].sum() == 1


def test_candidate_order_and_cache_do_not_change_decisions():
    vehicles = prepare_source(pd.DataFrame([
        SOURCE_ROW,
        {**SOURCE_ROW, 'ID': 2, 'POWER_RATING': 130},
    ]))
    candidates = reference()
    cached, _ = map_vehicles(vehicles, candidates, Policy(reuse_identical_rows=True))
    uncached, _ = map_vehicles(vehicles.iloc[::-1], candidates.iloc[::-1],
                               Policy(reuse_identical_rows=False))
    columns = ['source_key', 'mapped kType', 'Match_Status', 'Review_Category']
    left = cached[columns].sort_values('source_key').reset_index(drop=True)
    right = uncached[columns].sort_values('source_key').reset_index(drop=True)
    pd.testing.assert_frame_equal(left, right)


def test_streaming_and_in_memory_paths_make_identical_decisions(tmp_path: Path):
    vehicles = prepare_source(pd.DataFrame([
        SOURCE_ROW,
        {**SOURCE_ROW, 'ID': 2, 'POWER_RATING': 130},
    ]))
    candidates = reference()
    expected, evidence = map_vehicles(vehicles, candidates)
    actual, _, written = map_vehicles_streaming(
        vehicles, candidates, Policy(), tmp_path / 'evidence.csv')
    columns = ['source_key', 'mapped kType', 'Match_Status', 'Review_Category']
    pd.testing.assert_frame_equal(expected[columns], actual[columns])
    assert written == len(evidence)


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
    assert metadata['algorithm_version'] == '1.1.0'
    assert str(metadata['rapidfuzz']).startswith('3.')
    assert 'acceptance coverage' in report_path.read_text()


def test_csv_loader_preserves_literal_na_and_row_origin(tmp_path: Path):
    path = tmp_path / 'source.csv'
    pd.DataFrame([{**SOURCE_ROW, 'ENGINE_NUMBER': 'NA'}]).to_csv(path, index=False)
    loaded = load_source(path)
    assert loaded.loc[0, 'ENGINE_NUMBER'] == 'NA'
    assert loaded.loc[0, 'source_key'] == 'source.csv!2'


def test_tsv_loader_uses_tab_delimiter(tmp_path: Path):
    path = tmp_path / 'source.tsv'
    pd.DataFrame([SOURCE_ROW]).to_csv(path, sep='\t', index=False)
    loaded = load_source(path)
    assert loaded.loc[0, 'MODEL'] == 'KONA'


def test_excel_loader_preserves_literal_na(tmp_path: Path):
    path = tmp_path / 'source.xlsx'
    pd.DataFrame([{**SOURCE_ROW, 'ENGINE_NUMBER': 'NA'}]).to_excel(path, index=False)
    loaded = load_source(path)
    assert loaded.loc[0, 'ENGINE_NUMBER'] == 'NA'


def test_reference_requires_engine_code_before_matching():
    incomplete = reference().drop(columns='Engine_code')
    try:
        prepare_reference(incomplete)
    except ValueError as error:
        assert 'Engine_code' in str(error)
    else:
        raise AssertionError('reference without Engine_code was accepted')


def test_near_power_stop_is_classified_apart_from_a_specification_disagreement():
    """The register and the catalogue rounding one number differently is not the
    same stop as the two disagreeing about a specification, and the sub-status
    has to say which. Neither may be accepted."""
    near = reference({**REFERENCE_ROW, 'Maximum_output_KW': 111})
    results, _ = map_vehicles(source(), near)
    row = results.loc[0]
    assert row['Match_Status'] == ALL_CANDIDATES_CONTRADICTED
    assert row['Review_Category'] == NEAR_POWER_ONLY
    # The stop is quoted against the candidate it turns on, not as a spread that
    # would hide a one-kW gap among every rejected candidate's values.
    assert row['blocking_values'] == 'power: source 110 kW, reference 111 kW (kType 1)'

    far = reference({**REFERENCE_ROW, 'Maximum_output_KW': 130})
    assert map_vehicles(source(), far)[0].loc[0, 'Review_Category'] == ALL_CONTRADICTED


def test_the_near_power_classification_accepts_nothing():
    """The guard on the whole change: a sub-status may describe a stop, never
    lift it. power_tolerance_pct is the data owner's and is untouched here."""
    near = reference({**REFERENCE_ROW, 'Maximum_output_KW': 111})
    results, evidence = map_vehicles(source(), near)
    row = results.loc[0]
    assert pd.isna(row['mapped kType'])
    assert not row['count_in_vio']
    assert not evidence['compatible'].any()
    assert Policy().power_tolerance_pct == 0.0
