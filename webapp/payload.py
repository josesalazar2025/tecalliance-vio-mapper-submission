"""Turn one finished run into the JSON the browser renders.

Nothing here decides anything. Every figure is read back off the results and
evidence frames that :mod:`vio_mapper.reporting` writes into the workbook, so
the four tabs on screen and the downloaded file are the same run by
construction. Where a figure is a count of distinct vehicles rather than of
worksheet rows it says so, because the two differ whenever the source repeats
an ID.
"""
from __future__ import annotations

import json
import math

import pandas as pd

from vio_mapper.config import (ALL_STATUSES, COMPARED_FIELDS, MATCHED, column, identifiers,
                               VETO_FIELDS, Policy, score_rules, submodel_rules, vocabularies)
from vio_mapper.normalization import normalized_text

# Bumped whenever a field the frontend reads is renamed, removed or changes
# meaning. The page checks it on load: a server left running across such a change
# serves the old field names to a newly loaded script, and every figure that moved
# quietly renders as an em dash. A mismatch must say so instead.
PAYLOAD_VERSION = 8

# Columns the results table shows before a reviewer opens a row. The drawer
# fetches the whole row on demand: sending all 90 columns for every row would
# make the first paint of a large run wait on data almost none of it displays.
# A function, not a constant: the register's column names come from the selected
# registry, which is chosen per run.
def table_columns() -> tuple:
    source = tuple(name for name in (column(role) for role
                                     in ('id', 'make', 'model', 'submodel', 'year', 'body',
                                         'displacement', 'power', 'fuel')) if name)
    return ('source_key', *source, 'mapped kType', 'Match_Status',
            'Match_Reason', 'Review_Category', 'Review_Fields',
            'selected_criterion_vector', 'count_in_vio', 'provided_kType', 'provided_label_agreement',
            'triage_lead_kType', 'proposed_kType', 'remaining_kTypes')
# What a reviewer needs to see about a rejected candidate to judge it without
# opening the workbook: what it claims, what agrees, and what it contradicts.
CANDIDATE_COLUMNS = ('KType', 'review_rank', 'review_priority', 'review_priority_basis',
                     'review_conflict_severity', 'review_independent_conflict_count',
                     'review_near_power_only', 'review_identity_conflicts',
                     'review_configuration_conflicts', 'review_identity_agreements',
                     'compatible', 'selected',
                     'text_similarity_score', 'text_similarity_rank',
                     'text_similarity_method', 'text_similarity_source',
                     'text_similarity_reference',
                     'disagreements', 'power_difference_kw', 'power_difference_pct',
                     'power_within_triage_band', 'year_relationship', 'criterion_vector',
                     'reference_Type_designation', 'reference_Model_design', 'reference_Type_design',
                     'reference_Capacity_litre', 'reference_Capacity_cubic',
                     'reference_Fuel_type', 'reference_Maximum_output_KW',
                     'reference_Drive_system', 'reference_Kind_of_structure', 'reference_Engine_code',
                     'reference_Construction_from', 'reference_Construction_to',
                     'submodel_capacity_litre',
                     *(f'{field}' for field in COMPARED_FIELDS))
# Candidates shown inline in the review brief. The full set stays one click away
# in the row drawer; a brief that printed every compared candidate would be the
# evidence sheet again, which is the thing it exists to summarise.
BRIEF_CANDIDATE_LIMIT = 6
# Identical vehicles are folded into one brief entry; this many of their IDs are
# named on the card, and the rest are reachable through the results table.
BRIEF_ID_LIMIT = 12
PRIMARY_POLICY_FIELDS = (
    'power_tolerance_pct', 'power_triage_kw', 'use_identifiers', 'year_mode',
    'use_vin_helper', 'evidence', 'reuse_identical_rows', 'selection',
)


def primary_policy(policy: Policy) -> dict:
    """The maintained policy fields the review workflow needs to explain."""
    return {name: getattr(policy, name) for name in PRIMARY_POLICY_FIELDS}

# Keyed by status value, and complete: every member of ALL_STATUSES has an entry,
# checked by tests/test_webapp.py so every outcome shown by the API is explained.
STATUS_GLOSSARY = {
    'Matched': 'Accepted under the active decision policy and safeguards. Read the row reason '
               'and acceptance route for its basis. Counted in VIO once per canonical vehicle ID.',
    'Proposed: identifier anchor, one specification conflict':
        'Two or more distinct manufacturer identifier fields agree on one kType that exactly one '
        'specification contradicts. Not assigned and not counted in VIO: the conflicting field has '
        'to be reconciled with the data owner first.',
    'Ambiguous': 'Multiple candidates survive without a unique acceptable selection under the '
                 'active policy. The remaining kTypes and differentiating fields support review; '
                 'additional authoritative evidence may still be needed.',
    'Conflicting source data': 'The source contradicts itself, or the VIN contradicts the source '
                               'fields, before any reference candidate is consulted.',
    'No candidate in reference': 'The make/model gates produced no candidate at all: nothing in the '
                                 'reference was compared.',
    'All candidates contradicted': 'Every candidate the make/model gates produced is contradicted '
                                   'on at least one specification. The reference was consulted and '
                                   'rejected on a named field.',
    'Single uncontradicted candidate, evidence incomplete':
        'One candidate survived and no field disagrees with it, but the evidence the two catalogues '
        'share falls short of what acceptance requires. Additional evidence is needed; absence of '
        'a contradiction is not validation.',
    'Insufficient information': 'The row lacks the fields the gates, or the criteria acceptance '
                                'requires, are asking for.',
}


def _clean(value):
    """One cell, as something ``json.dumps`` will accept."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if value is pd.NA:
        return None
    if isinstance(value, (bool,)):
        return bool(value)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):  # arrays and other non-scalars are never NA here
        pass
    if hasattr(value, 'item'):  # numpy scalars
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def records(frame: pd.DataFrame, columns=None) -> list[dict]:
    """A frame as JSON-safe records, restricted to the columns that exist."""
    if columns is not None:
        frame = frame[[column for column in columns if column in frame.columns]]
    return [{column: _clean(value) for column, value in row.items()}
            for row in frame.to_dict('records')]


def _kType(value) -> int | None:
    """A result-cell kType, without treating blank/NA values as candidates."""
    cleaned = _clean(value)
    if cleaned in (None, ''):
        return None
    try:
        return int(float(cleaned))
    except (TypeError, ValueError):
        return None


def _kType_list(value) -> set[int]:
    """Semicolon-separated result kTypes as a set, tolerating empty cells."""
    cleaned = _clean(value)
    if cleaned in (None, ''):
        return set()
    parsed = set()
    for token in str(cleaned).split(';'):
        candidate = _kType(token.strip())
        if candidate is not None:
            parsed.add(candidate)
    return parsed


def order_candidates_for_review(row, candidates: pd.DataFrame) -> pd.DataFrame:
    """Put the decision's likeliest candidates first in every UI candidate list.

    This is presentation order, not a new matching decision or a probability.
    Explicit decision outputs lead: the accepted candidate, an advisory proposal
    or lead, and an explicit shortlist. Remaining compatible candidates follow.
    Within the same tier, fewer contradictions and more agreed Annex I criteria
    rank ahead; kType is only the deterministic final tie-breaker.
    """
    if candidates.empty:
        return candidates.copy()
    ranked = candidates.copy()
    recorded_rank = pd.to_numeric(
        ranked.get('review_rank', pd.Series(index=ranked.index, dtype=float)), errors='coerce')
    if recorded_rank.notna().all() and {'review_priority', 'review_priority_basis'} <= set(ranked):
        return ranked.assign(review_rank=recorded_rank.astype(int)).sort_values(
            ['review_rank', 'KType'], kind='stable')
    selected = _kType(row.get('mapped kType'))
    proposed = _kType(row.get('proposed_kType'))
    lead = _kType(row.get('triage_lead_kType'))
    shortlist = _kType_list(row.get('triage_lead_alternatives'))
    remaining = _kType_list(row.get('remaining_kTypes'))

    def standing(candidate) -> tuple[int, str, str]:
        ktype = _kType(candidate.get('KType'))
        is_selected = _clean(candidate.get('selected')) is True
        is_compatible = _clean(candidate.get('compatible')) is True
        if is_selected or ktype == selected:
            return 0, 'selected', 'Accepted candidate produced by the decision policy.'
        if ktype == proposed:
            return 1, 'most likely', 'Advisory proposal named by identifier or scoped model evidence.'
        if ktype == lead:
            return 1, 'most likely', 'Closest candidate explicitly named for human review.'
        if ktype in shortlist:
            return 2, 'shortlist', 'Candidate included in the explicit review shortlist.'
        if is_compatible or ktype in remaining:
            return 3, 'compatible', 'No retained specification comparison contradicts this candidate.'
        return 4, 'other', 'Ordered by fewer contradictions, then more criterion agreements.'

    standings = [standing(candidate) for candidate in ranked.to_dict('records')]
    ranked['_review_tier'] = [item[0] for item in standings]
    ranked['review_priority'] = [item[1] for item in standings]
    ranked['review_priority_basis'] = [item[2] for item in standings]
    ranked['_contradiction_count'] = ranked.get(
        'disagreements', pd.Series('', index=ranked.index)).fillna('').map(
            lambda value: len([field for field in str(value).split(';') if field.strip()]))
    agreed_columns = [name for name in ('version_criteria_agreed', 'variant_criteria_agreed')
                      if name in ranked.columns]
    ranked['_agreement_count'] = sum(
        ranked[name].fillna('').map(
            lambda value: len([field for field in str(value).split(';') if field.strip()]))
        for name in agreed_columns
    ) if agreed_columns else 0
    ranked['_power_gap'] = pd.to_numeric(
        ranked.get('power_difference_kw', pd.Series(index=ranked.index, dtype=float)),
        errors='coerce').abs().fillna(float('inf'))
    ranked['_text_similarity'] = pd.to_numeric(
        ranked.get('text_similarity_score', pd.Series(index=ranked.index, dtype=float)),
        errors='coerce').fillna(-1)
    ranked = ranked.sort_values(
        ['_review_tier', '_contradiction_count', '_agreement_count',
         '_text_similarity', '_power_gap', 'KType'],
        ascending=[True, True, False, False, True, True], kind='stable')
    ranked['review_rank'] = range(1, len(ranked) + 1)
    return ranked.drop(columns=['_review_tier', '_contradiction_count',
                                '_agreement_count', '_text_similarity', '_power_gap'])


def _counts(series: pd.Series, name: str) -> list[dict]:
    """A value-count as sorted records, missing values folded into one bucket."""
    counted = series.fillna('—').replace('', '—').value_counts()
    return [{name: str(key), 'count': int(value)} for key, value in counted.items()]


def _normalized_ids(frame: pd.DataFrame) -> pd.Series:
    return frame[column('id')].map(normalized_text)


def _distinct_vehicles(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.loc[~_normalized_ids(frame).duplicated()].copy()


def summary(results: pd.DataFrame, evidence: pd.DataFrame, metadata: dict,
            source_name: str, elapsed: float) -> dict:
    """The headline figures: what came in, what was accepted, and on what basis."""
    unique = _distinct_vehicles(results)
    accepted = int(results['count_in_vio'].sum())
    distinct = len(unique)
    labeled = unique[unique['provided_kType'].notna()]
    agreement = labeled['provided_label_agreement']
    status_rows = []
    for status in ALL_STATUSES:
        subset = results[results['Match_Status'] == status]
        if len(subset):
            status_rows.append({'status': status, 'worksheet_rows': len(subset),
                                'distinct_ids': int(_normalized_ids(subset).nunique()),
                                'glossary': STATUS_GLOSSARY.get(status, '')})
    vio = (results.loc[results['count_in_vio']].groupby('mapped kType').size()
           .rename('distinct_vehicle_count').reset_index())
    vio = vio.sort_values('distinct_vehicle_count', ascending=False)
    return {
        'source_name': source_name,
        'worksheet_rows': len(results),
        'distinct_ids': distinct,
        'accepted': accepted,
        'accepted_pct': round(100 * accepted / distinct, 1) if distinct else 0.0,
        'unresolved': distinct - accepted,
        'review_rows': int((results['Match_Status'] != MATCHED).sum()),
        'distinct_ktypes': int(len(vio)),
        'status_counts': status_rows,
        'vio': [{'kType': int(row['mapped kType']), 'distinct_vehicle_count': int(row['distinct_vehicle_count'])}
                for _, row in vio.iterrows()],
        'duplicates': int(results['duplicate_of'].ne('').sum()),
        'duplicate_conflicts': int(results['duplicate_id_conflict'].sum()),
        'power_tolerance_dependent': int(metadata['power_tolerance_dependent_distinct_ids']),
        # One evidence row is one source row weighed against one candidate kType.
        # It is a count of comparisons, never of distinct kTypes: the same kType
        # is reconsidered for every row whose make and model reach it.
        'candidate_comparisons': int(len(evidence)),
        'label_agreement': {
            'labeled': int(len(labeled)),
            'agree': int(agreement.eq('agree').sum()),
            'disagree': int(agreement.eq('disagree').sum()),
            'unassigned': int(agreement.eq('unassigned').sum()),
            'conflicting_ids': int(_normalized_ids(
                results[results['provided_label_conflict']]).nunique()),
        },
        'run_utc': metadata['run_utc'],
        'algorithm_version': metadata['algorithm_version'],
        'elapsed_seconds': round(elapsed, 2),
        # Acceptance coverage is not measured accuracy, and the screen must not
        # let a percentage imply otherwise.
        'coverage_caveat': 'Acceptance coverage under the documented rules, not measured accuracy. '
                           'No calibrated confidence score is produced.',
    }


def _brief_candidates(evidence: pd.DataFrame, source_key: str, result_row) -> list[dict]:
    """The first few candidates for one row, in the same order as its drawer."""
    if evidence.empty or 'source_key' not in evidence.columns:
        return []
    rows = evidence[evidence['source_key'] == source_key]
    if rows.empty:
        return []
    rows = order_candidates_for_review(result_row, rows).head(BRIEF_CANDIDATE_LIMIT)
    return records(rows, CANDIDATE_COLUMNS)


def _brief_kind(row) -> str:
    """Which kind of likely candidate, if any, this row carries.

    The status decides, not the presence of a kType. ``proposed_kType`` is also
    populated for a row that a model-specific reading merely *prefers* -- see
    ``decision.scoped_structural_preference`` -- and that is a weaker claim than
    an identifier anchor: it names a candidate without any identifier agreeing
    on it. Folding the two together would advertise a scoped reading of one
    model's cab wording as if two manufacturer codes had confirmed it.
    """
    status = str(row.get('Match_Status') or '')
    proposed = _clean(row.get('proposed_kType'))
    if proposed is not None:
        return 'proposal' if status.startswith('Proposed') else 'scoped'
    if _clean(row.get('triage_lead_kType')) is not None:
        return 'lead'
    return 'shortlist' if _clean(row.get('triage_lead_alternatives')) else 'none'


def review_brief(results: pd.DataFrame, evidence: pd.DataFrame) -> list[dict]:
    """One entry per distinct unresolved case: what stopped it, and what is likeliest.

    Vehicles whose whole brief is identical -- same model, same status, same
    blocking field, same shortlist -- are one entry carrying the count and the
    IDs. A register repeats a fleet purchase dozens of times, and seventeen
    copies of one Holden Colorado card is not seventeen findings for a reviewer
    to work through; it is one, seventeen times over.

    A proposal names a kType distinct identifier fields agree on. A scoped
    preference names one a model-specific reading favours. A triage lead names
    only the candidate to open first, because exactly one specification stands
    between it and compatibility. None of the three is evidence of a match, and
    none is counted in VIO.
    """
    all_unresolved = results[results['Match_Status'] != MATCHED]
    unresolved = _distinct_vehicles(all_unresolved)
    grouped: dict[tuple, dict] = {}
    for _, row in unresolved.iterrows():
        kind = _brief_kind(row)
        entry = {
            'source_key': _clean(row['source_key']), 'ID': _clean(row[column('id')]),
            # Payload keys are the UI's contract and stay put; what moves is
            # which register column each is read from.
            'MAKE': _clean(row[column('make')]), 'MODEL': _clean(row[column('model')]),
            'SUBMODEL': _clean(row[column('submodel')]),
            'VEHICLE_YEAR': _clean(row[column('year')]),
            'status': _clean(row['Match_Status']),
            'review_category': _clean(row['Review_Category']),
            'review_fields': _clean(row['Review_Fields']),
            'review_fields_scope': _clean(row['Review_Fields_scope']),
            'kind': kind,
            'likely_kType': (int(_clean(row.get('proposed_kType')))
                             if kind in ('proposal', 'scoped')
                             else int(_clean(row.get('triage_lead_kType'))) if kind == 'lead'
                             else None),
            'proposal_basis': _clean(row.get('proposal_basis')),
            'proposal_conflicting_fields': _clean(row.get('proposal_conflicting_fields')),
            'lead_blocking_field': _clean(row.get('triage_lead_blocking_field')),
            'lead_basis': _clean(row.get('triage_lead_basis')),
            'lead_alternatives': _clean(row.get('triage_lead_alternatives')),
            'remaining_kTypes': _clean(row.get('remaining_kTypes')),
            'identifier_kTypes': _clean(row.get('identifier_kTypes')),
            'match_reason': _clean(row.get('Match_Reason')),
            'criterion_vector': _clean(row.get('selected_criterion_vector')),
            'base_candidate_count': _clean(row.get('base_candidate_count')),
            'compatible_candidate_count': _clean(row.get('compatible_candidate_count')),
            'evidence_notes': _clean(row.get('evidence_notes')),
            'source_keys': all_unresolved.loc[
                _normalized_ids(all_unresolved).eq(normalized_text(row[column('id')])),
                'source_key'].astype(str).tolist(),
        }
        # Everything that would make two cards read differently is in the key,
        # so folding them can never hide a distinction a reviewer would act on.
        key = tuple(str(entry[field]) for field in
                    ('MAKE', 'MODEL', 'SUBMODEL', 'VEHICLE_YEAR', 'status', 'kind', 'likely_kType',
                     'review_category', 'review_fields', 'review_fields_scope', 'proposal_basis',
                     'proposal_conflicting_fields', 'lead_blocking_field', 'lead_basis',
                     'lead_alternatives', 'remaining_kTypes', 'match_reason'))
        existing = grouped.get(key)
        if existing is None:
            entry['vehicle_count'] = 1
            entry['ids'] = [entry[column('id')]]
            entry['candidates'] = _brief_candidates(evidence, entry['source_key'], row)
            grouped[key] = entry
        else:
            existing['vehicle_count'] += 1
            if len(existing['ids']) < BRIEF_ID_LIMIT:
                existing['ids'].append(entry[column('id')])

    order = {'proposal': 0, 'scoped': 1, 'lead': 2, 'shortlist': 3, 'none': 4}
    entries = sorted(grouped.values(),
                     key=lambda entry: (order[entry['kind']], -entry['vehicle_count'],
                                        str(entry['MODEL'])))
    return entries


def _semicolon_counts(series: pd.Series) -> list[dict]:
    """Frequency of each item in a semicolon-joined free-text column."""
    tally: dict[str, int] = {}
    for value in series.dropna():
        for item in str(value).split(';'):
            item = item.strip()
            if item:
                tally[item] = tally.get(item, 0) + 1
    return [{'item': item, 'distinct_ids': count}
            for item, count in sorted(tally.items(), key=lambda pair: -pair[1])]


def audit(results: pd.DataFrame, evidence: pd.DataFrame, metadata: dict, report: str) -> dict:
    """Traceability: where coverage was lost, what was assumed, and what was compared.

    Every unaccepted vehicle is attributed to a sub-status and, where one
    applies, to the specification field it stopped on. A field marked *every
    candidate* has to be reconciled before the row can match at all; one marked
    with a count blocks only that many candidates.
    """
    unique = _distinct_vehicles(results)
    unresolved = unique[unique['Match_Status'] != MATCHED]
    lost = []
    if len(unresolved):
        grouped = unresolved.groupby(['Review_Category', 'Review_Fields', 'Review_Fields_scope',
                                      'Match_Status'], sort=True)
        for (category, fields, scope, status), group in grouped:
            lost.append({'review_category': category, 'review_fields': fields or '—',
                         'scope': scope or '—', 'status': status, 'distinct_ids': len(group)})
        lost.sort(key=lambda row: -row['distinct_ids'])

    late = unique[unique['count_in_vio'] & unique['selected_registration_after_end_years'].notna()]
    late_rows = records(late[[column('id'), column('make'), column('model'), column('submodel'),
                              'mapped kType', column('year'),
                              'selected_construction_to', 'selected_registration_after_end_years',
                              column('import_status')]])

    disagreement_tally: dict[str, int] = {}
    if 'disagreements' in evidence.columns:
        for value in evidence['disagreements'].dropna():
            for item in str(value).split(';'):
                item = item.strip()
                if item:
                    disagreement_tally[item] = disagreement_tally.get(item, 0) + 1

    return {
        'lost_coverage': lost,
        'assumptions': _semicolon_counts(unique['assumptions_used']),
        'assumption_rows': int(unique['assumption_count'].gt(0).sum()),
        'late_registration': late_rows,
        'vin_helper_status': _counts(unique['vin_helper_status'], 'value'),
        'vin_origin': _counts(unique['vin_origin'], 'value'),
        'submodel_conflicts': _semicolon_counts(unique['submodel_source_conflict_fields']),
        'candidate_totals': {
            'comparisons': int(len(evidence)),
            'rows_with_evidence': int(evidence['source_key'].nunique()) if len(evidence) else 0,
            'compatible': int(evidence['compatible'].sum()) if 'compatible' in evidence.columns else 0,
            'criterion_sufficient': int(evidence['criterion_sufficient'].sum())
                                    if 'criterion_sufficient' in evidence.columns else 0,
            'selected': int(evidence['selected'].sum()) if 'selected' in evidence.columns else 0,
            'mean_candidates_per_row': round(len(evidence) / max(evidence['source_key'].nunique(), 1), 1)
                                       if len(evidence) else 0,
        },
        'criterion_shortfalls': _counts(evidence['criterion_shortfall'], 'basis')
                                if 'criterion_shortfall' in evidence.columns else [],
        'disagreements': [{'field': field, 'candidates': count}
                          for field, count in sorted(disagreement_tally.items(), key=lambda pair: -pair[1])],
        'duplicates': records(results[results['duplicate_of'].ne('') | results['duplicate_id_conflict']]
                              [[column('id'), 'source_key', 'duplicate_of',
                                'duplicate_id_conflict', 'canonical_record', 'Match_Status']]),
        'label_agreement_rows': records(
            unique[unique['provided_kType'].notna()]
            [[column('id'), column('make'), column('model'), 'provided_kType', 'mapped kType',
              'provided_label_agreement']]),
        'metadata': [{'property': key, 'value': str(value)} for key, value in metadata.items()],
        'report_markdown': report,
    }


def rules(policy: Policy) -> dict:
    """The rule sets that govern the run, as data rather than prose.

    These are loaded from ``data/rules`` exactly as the matcher loads them, so a
    reviewer amending a JSON table sees the change here without a code change.
    """
    from vio_mapper.reporting import selection_description

    shared = score_rules()
    submodels = submodel_rules()
    vocabulary = vocabularies()
    return {
        'policy': primary_policy(policy),
        'selection_description': selection_description(policy),
        'core_conflicts': [{'evidence_key': key, 'counts_as': value}
                           for key, value in shared['core_conflicts'].items()],
        'review_conflict_classes': [{'evidence_key': key, 'review_class': value}
                                    for key, value in shared['review_conflict_classes'].items()],
        'review_conflict_severity': shared['review_conflict_severity'],
        'unproposable_conflicts': sorted(shared['unproposable_conflicts']),
        'statuses': [{'status': status, 'meaning': STATUS_GLOSSARY.get(status, '')}
                     for status in ALL_STATUSES],
        'compared_fields': list(COMPARED_FIELDS),
        'veto_fields': list(VETO_FIELDS),
        'identifiers': list(identifiers()),
        'vocabularies': {
            'registry_fuel': vocabulary['registry_fuel'],
            'catalogue_fuel': vocabulary['catalogue_fuel'],
            'reference_drive_system': vocabulary['reference_drive_system'],
            'submodel_drive': vocabulary['submodel_drive'],
            'registry_submodel_fuel': {key: list(value) for key, value
                                       in vocabulary['registry_submodel_fuel'].items()},
            'catalogue_submodel_fuel': {key: list(value) for key, value
                                        in vocabulary['catalogue_submodel_fuel'].items()},
            'registry_bodies': vocabulary['registry_bodies'],
            'catalogue_structures': vocabulary['catalogue_structures'],
            'cab_tokens': vocabulary['cab_tokens'],
        },
        'submodel_profiles': [{'make': make, 'model': model, 'id': identifier,
                               'marketing_trims': sorted(trims)}
                              for (make, model), (identifier, trims) in submodels['profiles'].items()],
        'submodel_core_fields': submodels['core_fields'],
        'vin_rules': _vin_rules(),
    }


def _vin_rules() -> dict:
    """The VIN profiles and their sources, trimmed to what the tab displays."""
    from vio_mapper.config import vin_rules_path

    path = vin_rules_path()
    if path is None:
        return {'sources': {}, 'profiles': []}
    raw = json.loads(path.read_text())
    profiles = []
    for profile in raw.get('profiles', []):
        profiles.append({
            'id': profile.get('id'), 'pattern': profile.get('pattern'),
            'source': profile.get('source'), 'note': profile.get('note'),
            'segments': [{'start': segment.get('start'), 'end': segment.get('end'),
                          'key': segment.get('key'),
                          'value_count': len(segment.get('values') or {})}
                         for segment in profile.get('segments', [])],
        })
    return {'sources': raw.get('sources', {}), 'profiles': profiles}
