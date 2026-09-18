"""Running the matcher over a whole file.

Two concerns live here that the per-row code does not have to know about:
reusing the decision of an identical row, and keeping the audit trail out of
memory when the file is large. Neither may change a single outcome.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from .config import (INSUFFICIENT, MATCHED, MISSING_GATE_FIELDS, CONFLICT, Policy,
                     column, decision_columns, source_field, vin_rules_path)
from .decision import decide
from .evidence import MINIMUM_CODE_LENGTH, MERCEDES_ENGINE_PREFIX, engine_number_carries, scoped_engine_code
from .normalization import compact_code, model_year, normalized_text, numeric_value
from .sources import prepare_reference, prepare_source
from .vin_decoder import rules_for_decoding


def group_engine_tokens(reference: pd.DataFrame) -> dict:
    """Comparable engine-code tokens per make/model group, plus VIN-rule codes.

    Deliberately over-inclusive: the Mercedes M/OM-stripped form and every
    documented VIN engine code are added to all groups. A superset of tokens can
    only split decision keys further apart, never merge two rows that the
    algorithm would treat differently.
    """
    documented = set()
    for profile in rules_for_decoding()['profiles']:
        for segment in profile['segments']:
            if segment['key'] == 'engine' and segment['evidence_status'] == 'documented':
                documented.update(compact_code(value) for value in segment['values'].values())
    tokens = {}
    for key, group in reference.groupby(['_make', '_model'], sort=False):
        found = set(documented)
        for codes in group['Engine_code'].fillna(''):
            for code in str(codes).split(';'):
                token = compact_code(code)
                if len(token) >= MINIMUM_CODE_LENGTH:
                    found.add(token)
                    found.add(MERCEDES_ENGINE_PREFIX.sub('', token))
        # Stripping a prefix can leave a token too short to ever match, so the
        # length floor is applied again after the whole group is collected.
        tokens[key] = sorted(token for token in found if len(token) >= MINIMUM_CODE_LENGTH)
    return tokens


def decision_key(row, engine_tokens: dict):
    """Everything the decision depends on, with the engine serial derived away.

    The engine number is a per-vehicle serial, so keying on it directly would defeat
    reuse entirely. Nothing in the algorithm reads the serial: it only reads
    which reference engine codes the number carries and whether it states a
    scoped complete engine code, and both are derived here through the very same
    helpers the evidence code uses. That shared derivation is what makes reuse
    sound -- two rows may share a key only if every input to the decision is
    equal, and a column read but not declared in DECISION_ROLES would break it.

    Raw values are used verbatim rather than normalized: a coarser key could
    merge rows the algorithm separates, while a finer one only costs reuse.
    """
    group = (normalized_text(source_field(row, 'make')), normalized_text(source_field(row, 'model')))
    carried = frozenset(engine_number_carries(row, engine_tokens.get(group, ())))
    return (tuple(str(row.get(name)) for name in decision_columns()
                  if name != column('engine_number')),
            scoped_engine_code(row) or '', carried,
            bool(row.get('duplicate_id_conflict', False)))


class _RowMatcher:
    """Decides one row at a time, reusing the outcome of an identical row.

    The cache stores the decision and its candidate evidence. Replay stamps each
    evidence row with the row it belongs to; nothing else about an outcome
    depends on which row produced it.
    """

    def __init__(self, reference: pd.DataFrame, policy: Policy,
                 include_score_diagnostics: bool = True):
        self.policy = policy
        self.include_score_diagnostics = include_score_diagnostics
        self.reference = reference
        self.empty = reference.iloc[:0]
        # One dictionary lookup per row instead of a scan of the reference.
        self.groups = {key: group for key, group in reference.groupby(['_make', '_model'], sort=False)}
        self.engine_tokens = group_engine_tokens(reference) if policy.reuse_identical_rows else {}
        self.cache: dict = {}

    def __call__(self, row) -> tuple[dict, list[dict]]:
        if not self.policy.reuse_identical_rows:
            return self._decide(row)
        key = decision_key(row, self.engine_tokens)
        if key not in self.cache:
            self.cache[key] = self._decide(row)
        result, details = self.cache[key]
        return result, [{**entry, 'source_key': row['source_key'], 'ID': row[column('id')]}
                        for entry in details]

    def _decide(self, row) -> tuple[dict, list[dict]]:
        make, model = normalized_text(source_field(row, 'make')), normalized_text(source_field(row, 'model'))
        vehicle_year = model_year(source_field(row, 'year'))
        gated = self.policy.year_mode == 'gate'
        if not make or not model or (gated and vehicle_year is None):
            # Nothing can be compared, but a self-contradicting row still
            # reports its contradiction rather than a missing-field notice.
            result, details = decide(
                row, self.empty, self.policy,
                include_score_diagnostics=self.include_score_diagnostics)
            if result['Match_Status'] != CONFLICT:
                result = {**result, 'Match_Status': INSUFFICIENT,
                          'Review_Category': MISSING_GATE_FIELDS,
                          'Match_Reason': 'Missing make/model, or missing year with the '
                                          'diagnostic legacy gate enabled.'}
            return result, details
        return decide(
            row, self._candidates(make, model, vehicle_year, gated), self.policy,
            include_score_diagnostics=self.include_score_diagnostics)

    def _candidates(self, make: str, model: str, vehicle_year, gated: bool) -> pd.DataFrame:
        """The candidate pool, with the configured production-start gate.

        Gate mode excludes a candidate when the registry year predates its
        Construction_from year. Construction_to is deliberately not a gate:
        the registry field may be first-registration year, so a vehicle can be
        registered after production ended.
        """
        group = self.groups.get((make, model), self.empty)
        if not gated:
            return group
        return group[group['_from'] <= vehicle_year]


def retain_evidence(details, status, policy):
    """Audit-trail retention. Never consulted by decide(), scoring or ranking."""
    if policy.evidence == 'all':
        return details
    if policy.evidence == 'selected' or status == MATCHED:
        return [entry for entry in details if entry['selected']]
    return details


def map_vehicles(source, reference, policy=Policy(), evidence_sink=None, *,
                 include_score_diagnostics: bool = True):
    """Map every source row, returning the results and the candidate evidence.

    ``evidence_sink`` receives each row's retained evidence as it is produced;
    when given, no evidence is accumulated and the returned evidence frame is
    empty.
    """
    policy.validate()
    # Fail explicitly on invalid configuration, before any rows. A registry that
    # records no VIN layouts is not invalid configuration: it has nothing to
    # validate, and vin_context then contributes no evidence.
    if policy.use_identifiers and policy.use_vin_helper and vin_rules_path() is not None:
        rules_for_decoding()
    reference = prepare_reference(reference)
    source = source.copy().reset_index(drop=True)
    if 'canonical_record' not in source:
        source = prepare_source(source)
    matcher = _RowMatcher(reference, policy, include_score_diagnostics)
    records, evidence = [], []
    for _, row in source.iterrows():
        result, details = matcher(row)
        records.append({**row.to_dict(), **result})
        kept = retain_evidence(details, result['Match_Status'], policy)
        # With a sink, evidence rows leave memory as they are produced: a large
        # run would otherwise accumulate tens of millions of dictionaries.
        if evidence_sink is not None:
            evidence_sink(kept)
        else:
            evidence.extend(kept)
    return _finalize(pd.DataFrame(records)), pd.DataFrame(evidence)


def _finalize(results: pd.DataFrame) -> pd.DataFrame:
    """Apply the nullable integer types and the row-level summary columns."""
    results['mapped kType'] = pd.array(results['mapped kType'], dtype='Int64')
    results['proposed_kType'] = pd.array(results['proposed_kType'], dtype='Int64')
    results['count_in_vio'] = results['Match_Status'].eq(MATCHED) & results['canonical_record']
    results['provided_label_agreement'] = [
        'not provided' if pd.isna(label) else 'unassigned' if pd.isna(predicted)
        else 'agree' if numeric_value(label) == numeric_value(predicted) else 'disagree'
        for label, predicted in zip(results['provided_kType'], results['mapped kType'])]
    return results


def _is_missing(value) -> bool:
    """Whether one evidence value should be written as an empty CSV cell.

    ``pd.isna`` returns an array for an array argument, so the identity test this
    replaced (``pd.isna(value) is True``) was really two rules at once: blank a
    missing scalar, and never blank a container. That happened to be right for
    every value the evidence currently carries, all of which are scalars, but it
    said so by accident. Scalars are checked explicitly here so that an
    array-valued field added later raises rather than silently writing the repr
    of an array into the audit trail.
    """
    if isinstance(value, (str, bytes)) or value is None:
        return value is None
    result = pd.isna(value)
    if isinstance(result, bool):
        return result
    raise TypeError(f'candidate evidence must hold scalars; got {type(value).__name__}')


def map_vehicles_streaming(source, reference, policy, evidence_path: Path, *,
                           include_score_diagnostics: bool = True):
    """Map with the candidate evidence written straight to CSV, never accumulated.

    Returns the results frame, a one-row pointer frame for the workbook, and the
    number of evidence rows written. The decisions are identical to map_vehicles;
    only where the audit trail is kept differs.
    """
    written = 0
    with evidence_path.open('w', newline='', encoding='utf-8') as handle:
        writer = None

        def sink(rows):
            nonlocal writer, written
            for row in rows:
                if writer is None:
                    writer = csv.DictWriter(handle, fieldnames=list(row))
                    writer.writeheader()
                writer.writerow({key: ('' if _is_missing(value) else value)
                                 for key, value in row.items()})
                written += 1

        results, _ = map_vehicles(
            source, reference, policy, evidence_sink=sink,
            include_score_diagnostics=include_score_diagnostics)
    pointer = pd.DataFrame([{
        'note': 'Candidate evidence exceeds practical worksheet size and was written to CSV.',
        'file': evidence_path.name, 'rows': written, 'retention': policy.evidence,
    }])
    return results, pointer, written
