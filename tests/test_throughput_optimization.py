"""Equivalence contracts for the opt-in throughput executor."""
from __future__ import annotations

import zipfile

import pandas as pd
import pytest

from vio_mapper.columnar import load_execution_dataset, prepare_execution_dataset
from vio_mapper.bounded import (audit_bounded_results, compare_bounded_runs,
                                run_bounded_dataset)
from vio_mapper.config import CONFLICT, Policy
from vio_mapper.optimized import ExecutionOptions, map_vehicles_optimized
from vio_mapper.pipeline import _RowMatcher, map_vehicles
from vio_mapper.semantic import build_manifest, compare_manifests, semantic_hash
from vio_mapper.sources import prepare_source


SOURCE = {
    'ID': 1, 'MAKE': 'HYUNDAI', 'MODEL': 'KONA', 'SUBMODEL': '',
    'VEHICLE_YEAR': 2020, 'CC_RATING': 1999, 'MOTIVE_POWER': 'PETROL',
    'POWER_RATING': 110, 'ENGINE_NUMBER': 'G4NA123', 'BODY_TYPE': 'HATCHBACK',
}
REFERENCE = {
    'KType': 1, 'Brand': 'HYUNDAI', 'Sales_designation': 'KONA',
    'Construction_from': 201801, 'Construction_to': 202212,
    'Capacity_cubic': 1999, 'Fuel_type': 'Petrol', 'Maximum_output_KW': 110,
    'Engine_code': 'G4NA', 'Kind_of_structure': 'Hatchback',
    'Drive_system': 'Front-Wheel Drive', 'Type_designation': 'OS',
    'Model_design': 'OS',
}


def _frames():
    source = prepare_source(pd.DataFrame([
        SOURCE,
        {**SOURCE, 'ID': 2},                       # same decision across a chunk boundary
        {**SOURCE, 'ID': 3, 'MODEL': 'UNKNOWN'},  # vectorized anti-join
        {**SOURCE, 'ID': 4, 'MAKE': 'OTHER'},
    ]))
    return source, pd.DataFrame([REFERENCE])


@pytest.mark.parametrize('workers', [1, 2])
def test_optimized_results_and_evidence_equal_baseline(tmp_path, workers):
    source, reference = _frames()
    baseline, baseline_evidence = map_vehicles(source, reference,
                                               include_score_diagnostics=False)
    result, evidence, metrics = map_vehicles_optimized(
        source, reference, options=ExecutionOptions(
            workers=workers, checkpoint_dir=tmp_path / f'p{workers}'),
        include_score_diagnostics=False)
    result_columns = ['ID', 'mapped kType', 'Match_Status', 'Review_Category',
                      'Match_Reason', 'count_in_vio']
    pd.testing.assert_frame_equal(result[result_columns], baseline[result_columns],
                                  check_dtype=False)
    evidence_columns = sorted(set(evidence) - {'source_key', 'ID'})
    assert semantic_hash(evidence, evidence_columns) == semantic_hash(
        baseline_evidence, evidence_columns)
    assert metrics.source_rows == 4
    assert metrics.distinct_decisions == 3
    assert metrics.gated_rows == 2


def test_duplicate_conflict_is_global_before_partitioning(tmp_path):
    source = pd.DataFrame([SOURCE, {**SOURCE, 'MAKE': 'OTHER'}])
    # Same ID, different make/model: these rows are deliberately routed to
    # different closed groups after the global duplicate pass.
    result, _, _ = map_vehicles_optimized(
        source, pd.DataFrame([REFERENCE]),
        options=ExecutionOptions(workers=2, checkpoint_dir=tmp_path))
    assert set(result.Match_Status) == {CONFLICT}
    assert not result.count_in_vio.any()


def test_global_reference_validation_precedes_partitioning(tmp_path):
    source, reference = _frames()
    duplicated = pd.concat([reference, pd.DataFrame([
        {**REFERENCE, 'Brand': 'OTHER', 'Sales_designation': 'OTHER'}])], ignore_index=True)
    with pytest.raises(ValueError, match='unique positive integer'):
        map_vehicles_optimized(source, duplicated,
                               options=ExecutionOptions(workers=2, checkpoint_dir=tmp_path))


def test_completed_partitions_are_reused(tmp_path):
    source, reference = _frames()
    options = ExecutionOptions(workers=1, checkpoint_dir=tmp_path)
    first, _, first_metrics = map_vehicles_optimized(source, reference, options=options)
    second, _, second_metrics = map_vehicles_optimized(source, reference, options=options)
    pd.testing.assert_frame_equal(first, second)
    assert first_metrics.retries == 0
    assert second_metrics.checkpoint_hits == 1


def test_phase_switches_preserve_outcomes(tmp_path):
    source, reference = _frames()
    baseline, _ = map_vehicles(source, reference)
    result, _, metrics = map_vehicles_optimized(
        source, reference, options=ExecutionOptions(
            workers=2, checkpoint_dir=tmp_path, bulk_gate=False,
            group_decisions=False, partitioned=False))
    columns = ['mapped kType', 'Match_Status', 'Review_Category', 'Match_Reason']
    pd.testing.assert_frame_equal(result[columns], baseline[columns], check_dtype=False)
    assert metrics.distinct_decisions == len(source)
    assert metrics.worker_count == 1
    assert metrics.gated_rows == 0


def test_bulk_gate_bypasses_candidate_lookup_for_no_candidate_rows(tmp_path, monkeypatch):
    source, reference = _frames()
    original = _RowMatcher._candidates
    looked_up = []

    def counted(self, make, model, vehicle_year, gated):
        looked_up.append((make, model))
        return original(self, make, model, vehicle_year, gated)

    monkeypatch.setattr(_RowMatcher, '_candidates', counted)
    result, _, metrics = map_vehicles_optimized(
        source, reference,
        options=ExecutionOptions(workers=1, checkpoint_dir=tmp_path))
    assert len(result) == 4
    assert metrics.gated_rows == 2
    assert looked_up == [('HYUNDAI', 'KONA')]


def test_disk_evidence_fragments_expand_to_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr('vio_mapper.optimized.EVIDENCE_FLUSH_ROWS', 1)
    source = prepare_source(pd.DataFrame([
        SOURCE, {**SOURCE, 'ID': 2, 'CC_RATING': 2000}]))
    reference = pd.DataFrame([REFERENCE])
    baseline, baseline_evidence = map_vehicles(
        source, reference, include_score_diagnostics=False)
    result, evidence_path, _ = map_vehicles_optimized(
        source, reference,
        options=ExecutionOptions(workers=1, checkpoint_dir=tmp_path,
                                 expand_evidence=False, include_decision_id=True,
                                 disk_evidence=True),
        include_score_diagnostics=False)
    assert evidence_path.is_dir()
    assert len(list(evidence_path.glob('part-*.parquet'))) > 1
    compact = pd.read_parquet(evidence_path)
    expanded = result[['decision_id', 'ID', 'source_key']].merge(
        compact.drop(columns=['ID', 'source_key']), on='decision_id')
    columns = sorted(set(expanded) - {'decision_id', 'ID', 'source_key'})
    assert semantic_hash(expanded, columns) == semantic_hash(baseline_evidence, columns)
    assert result.Match_Status.tolist() == baseline.Match_Status.tolist()


def test_disk_evidence_replaces_legacy_checkpoint_file(tmp_path):
    source, reference = _frames()
    _, legacy, _ = map_vehicles_optimized(
        source, reference,
        options=ExecutionOptions(checkpoint_dir=tmp_path, expand_evidence=False))
    assert isinstance(legacy, pd.DataFrame)
    result, evidence_path, metrics = map_vehicles_optimized(
        source, reference,
        options=ExecutionOptions(checkpoint_dir=tmp_path, expand_evidence=False,
                                 disk_evidence=True))
    assert len(result) == len(source)
    assert evidence_path.is_dir()
    assert metrics.checkpoint_hits == 0


def test_columnar_round_trip_and_schema_manifest(tmp_path):
    source_path, reference_path = tmp_path / 'source.csv', tmp_path / 'reference.csv'
    pd.DataFrame([SOURCE, {**SOURCE, 'ID': 2, 'ENGINE_NUMBER': 12345}]).to_csv(
        source_path, index=False)
    pd.DataFrame([REFERENCE]).to_csv(reference_path, index=False)
    output = tmp_path / 'execution'
    manifest = prepare_execution_dataset(source_path, reference_path, output)
    source, reference, loaded = load_execution_dataset(output)
    assert manifest == loaded
    assert source['source_ordinal'].tolist() == [0, 1]
    assert source['ENGINE_NUMBER'].tolist() == ['G4NA123', '12345']
    assert reference.KType.tolist() == [1]
    assert manifest['source']['parquet_bytes'] > 0


def test_zip_intake_assigns_documented_synthetic_ids(tmp_path, monkeypatch):
    monkeypatch.setattr('vio_mapper.columnar.ZIP_CHUNK_SIZE', 2)
    archive = tmp_path / 'registry.zip'
    raw = pd.DataFrame([{key: value for key, value in SOURCE.items() if key != 'ID'}] * 5)
    csv_path = tmp_path / 'registry.csv'
    raw.to_csv(csv_path, index=False)
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.write(csv_path, arcname='registry.csv')
    reference_path = tmp_path / 'reference.csv'
    pd.DataFrame([REFERENCE]).to_csv(reference_path, index=False)
    output = tmp_path / 'execution'
    prepare_execution_dataset(archive, reference_path, output)
    source, _, _ = load_execution_dataset(output)
    assert source.ID.astype(int).tolist() == [1, 2, 3, 4, 5]
    assert source.source_ordinal.tolist() == [0, 1, 2, 3, 4]


def test_semantic_manifest_ignores_row_order_and_id_storage_type(tmp_path):
    source, reference = _frames()
    results, evidence = map_vehicles(source, reference)
    source_path, reference_path = tmp_path / 's', tmp_path / 'r'
    source_path.write_text('source')
    reference_path.write_text('reference')
    first = build_manifest(results, evidence, source_path=source_path,
                           reference_path=reference_path)
    reordered = results.iloc[::-1].copy()
    reordered['ID'] = reordered.ID.astype(str)
    second = build_manifest(reordered, evidence.iloc[::-1], source_path=source_path,
                            reference_path=reference_path)
    assert compare_manifests(first, second) == []


@pytest.mark.parametrize('workers', [1, 2])
def test_bounded_run_keeps_decisions_together_and_resumes(tmp_path, workers):
    source, reference = _frames()
    source_path, reference_path = tmp_path / 'source.csv', tmp_path / 'reference.csv'
    source.drop(columns=['source_key', 'source_sheet', 'source_excel_row',
                         'provided_kType', 'provided_label_conflict', 'duplicate_of',
                         'duplicate_id_conflict', 'canonical_record'], errors='ignore').to_csv(
                             source_path, index=False)
    reference.to_csv(reference_path, index=False)
    dataset, output = tmp_path / 'dataset', tmp_path / 'bounded'
    prepare_execution_dataset(source_path, reference_path, dataset)
    first = run_bounded_dataset(dataset, output, buckets=3, workers=workers)
    second = run_bounded_dataset(dataset, output, buckets=3, workers=workers)
    assert first['complete'] and second['complete']
    assert first['rows'] == len(source) == second['rows']
    assert first['status_counts'] == second['status_counts']
    audit = audit_bounded_results(dataset, output)
    assert audit['complete'] and audit['rows'] == len(source)
    assert audit['status_counts'] == second['status_counts']
    frames = [pd.read_parquet(path) for path in (output / 'mapped-buckets').glob(
        'bucket-*/results.parquet')]
    actual = pd.concat(frames).sort_values('source_ordinal').reset_index(drop=True)
    prepared_source, prepared_reference, _ = load_execution_dataset(dataset)
    baseline, baseline_evidence = map_vehicles(
        prepared_source, prepared_reference, include_score_diagnostics=False)
    columns = ['ID', 'mapped kType', 'Match_Status', 'Review_Category',
               'Match_Reason', 'count_in_vio']
    actual['ID'] = actual['ID'].astype(str)
    baseline['ID'] = baseline['ID'].astype(str)
    pd.testing.assert_frame_equal(actual[columns], baseline[columns], check_dtype=False)
    assert actual.loc[actual.ID.isin(['1', '2']),
                      ['bucket_id', 'decision_id']].nunique().eq(1).all()
    evidence_frames = [pd.read_parquet(path) for path in (output / 'mapped-buckets').glob(
        'bucket-*/candidate_evidence.parquet')]
    compact = pd.concat(evidence_frames, ignore_index=True)
    links = actual[['bucket_id', 'decision_id', 'ID', 'source_key']]
    expanded = links.merge(compact.drop(columns=['ID', 'source_key']),
                           on=['bucket_id', 'decision_id'], how='inner')
    evidence_columns = sorted(set(expanded) - {'bucket_id', 'decision_id', 'source_key', 'ID'})
    assert semantic_hash(expanded, evidence_columns) == semantic_hash(
        baseline_evidence, evidence_columns)
    other_output = tmp_path / 'bounded-repeat'
    run_bounded_dataset(dataset, other_output, buckets=3, workers=workers)
    assert compare_bounded_runs(output, other_output)['identical']
    result_path = next((other_output / 'mapped-buckets').glob('bucket-*/results.parquet'))
    altered = pd.read_parquet(result_path)
    altered.loc[0, 'Match_Status'] = 'altered for comparison test'
    altered.to_parquet(result_path, index=False)
    assert not compare_bounded_runs(output, other_output)['identical']


def test_bounded_run_keeps_global_duplicate_conflict(tmp_path):
    raw = pd.DataFrame([SOURCE, {**SOURCE, 'MAKE': 'OTHER'}])
    source_path, reference_path = tmp_path / 'source.csv', tmp_path / 'reference.csv'
    raw.to_csv(source_path, index=False)
    pd.DataFrame([REFERENCE]).to_csv(reference_path, index=False)
    dataset, output = tmp_path / 'dataset', tmp_path / 'bounded'
    prepare_execution_dataset(source_path, reference_path, dataset)
    manifest = run_bounded_dataset(dataset, output, buckets=5, workers=2)
    actual = pd.concat(pd.read_parquet(path) for path in
                       (output / 'mapped-buckets').glob('bucket-*/results.parquet'))
    assert manifest['rows'] == 2
    assert set(actual.Match_Status) == {CONFLICT}
    assert not actual.count_in_vio.any()
