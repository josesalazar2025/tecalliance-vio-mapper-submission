"""The two human-readable outputs: the performance report and the workbook.

The report is written for a reviewer who has to decide whether to trust the
mapping, so it reports acceptance coverage and names every place coverage was
lost. It never reports accuracy, because nothing here measures accuracy.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pandas as pd

from .config import (attainable_score, ALL_CANDIDATES_CONTRADICTED, ALL_STATUSES, AMBIGUOUS, BELOW_THRESHOLD,
                     CRITERION_SET,
                     CONFLICT,
                     MATCHED, NO_CANDIDATE_IN_REFERENCE, PROPOSED,
                     SOLE_CANDIDATE_INCOMPLETE, column, policy_decisions,
                     registry_report_notes)
from .normalization import normalized_text

WORKBOOK_SHEETS = ('Results', 'Candidate_Evidence', 'Review_Queue', 'Review_Detail', 'Duplicates',
                   'VIO', 'Summary', 'Decision_Policy', 'Metadata')

# Internal score diagnostics remain available to the frozen comparison and
# research tools while the primary workbook presents only the default policy.
RESULT_DIAGNOSTIC_COLUMNS = (
    'top_candidate_kTypes', 'top_match_score', 'runner_up_score', 'score_margin',
    'score_threshold_met', 'score_margin_met', 'accept_score_threshold',
    'minimum_score_margin',
)
EVIDENCE_DIAGNOSTIC_COLUMNS = (
    'temporal_points', 'evidence_floor', 'sufficient', 'match_score',
    'score_powertrain', 'score_configuration', 'score_identity', 'score_temporal',
    'score_components_before_caps', 'score_rank', 'score_band',
)

# The decision sheet's columns, in reading order: who the vehicle is, how many
# ride on the answer, what the algorithm found, what it is pointing at, and the
# values the reviewer has to rule on.
REVIEW_QUEUE_COLUMNS = ('vehicles', 'make', 'model', 'submodel', 'status', 'why',
                        'candidates', 'decide_on', 'identifier_evidence', 'question', 'IDs',
                        'source_rows')


def _normalized_ids(frame: pd.DataFrame) -> pd.Series:
    """The identity policy used by duplicate detection, counts and grouping."""
    return frame[column('id')].map(normalized_text)


def _distinct_vehicles(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.loc[~_normalized_ids(frame).duplicated()].copy()


def performance_report(results: pd.DataFrame, metadata: dict) -> str:
    """Assemble the markdown report from the finished results frame."""
    unique = _distinct_vehicles(results)
    accepted = int(results['count_in_vio'].sum())
    lines = ['# Mapping performance', '',
             f"Run: {metadata['run_utc']}; algorithm {metadata['algorithm_version']}.", '',
             f'Processed **{len(results)} worksheet rows**, representing **{len(unique)} distinct vehicle IDs**. '
             f'Accepted **{accepted} distinct vehicles ({accepted / len(unique):.1%})** under the documented rules.', '',
             'This is acceptance coverage, not measured accuracy. No calibrated confidence score is produced.', '']
    lines += _proposal_section(unique)
    lines += _triage_lead_section(unique)
    lines += _uncontradicted_shortfall_section(unique)
    lines += _status_section(results, unique, accepted)
    lines += _late_registration_section(unique)
    lines += _lost_coverage_section(unique)
    lines += _source_group_section(unique)
    lines += _decision_policy_section(metadata)
    lines += _evaluation_limits_section(results, unique)
    return '\n'.join(lines)


def _proposal_section(unique: pd.DataFrame) -> list[str]:
    """Rows where advisory evidence names a candidate for human review."""
    proposals = unique[unique['Match_Status'] == PROPOSED]
    if not len(proposals):
        return []
    lines = [f'**{len(proposals)} distinct vehicles are proposals awaiting human confirmation.** '
             'Advisory identifier or manufacturer-model-code evidence names one likely kType, but a '
             'specification contradicts it. They are not assigned, not counted in VIO, and remain in the '
             'review queue; the conflicting field needs reconciling before any can be accepted.', '',
             '| Model | Submodel | Proposed kType | Conflicting field | Identifier basis | Distinct IDs |',
             '|---|---|---|---|---|---:|']
    for key, group in proposals.groupby([column('model'), column('submodel'), 'proposed_kType',
                                         'proposal_conflicting_fields', 'proposal_basis'], sort=True):
        lines.append('| ' + ' | '.join(map(str, key)) + f' | {len(group)} |')
    return lines + ['']


def _triage_lead_section(unique: pd.DataFrame) -> list[str]:
    """Unresolved rows where one candidate is a single field from compatible."""
    leads = unique[unique['triage_lead_kType'].notna() | unique['triage_lead_alternatives'].ne('')]
    if not len(leads):
        return []
    named = int(leads['triage_lead_kType'].notna().sum())
    lines = [f'**{len(leads)} distinct unresolved vehicles carry a triage lead**, {named} of them naming a '
             'single candidate. Every candidate is still contradicted and none of these rows is assigned or '
             'counted in VIO. A lead only says which candidate a reviewer should look at first, because '
             'exactly one specification stands between it and compatibility; where several candidates are '
             'equally close, the shortlist is given and none is named. A lead is not evidence.', '',
             '| Model | Submodel | Lead kType | Blocking field | Why | Other one-field candidates | Distinct IDs |',
             '|---|---|---|---|---|---|---:|']
    for key, group in leads.groupby([column('model'), column('submodel'), 'triage_lead_kType', 'triage_lead_blocking_field',
                                     'triage_lead_basis', 'triage_lead_alternatives'],
                                    dropna=False, sort=True):
        model, submodel, ktype, blocking, basis, alternatives = key
        named_ktype = '— (shortlist only)' if pd.isna(ktype) else str(int(ktype))
        lines.append(f'| {model} | {submodel} | {named_ktype} | {blocking} | {basis} | '
                     f"{alternatives or '—'} | {len(group)} |")
    return lines + ['']


def _uncontradicted_shortfall_section(unique: pd.DataFrame) -> list[str]:
    """Rows where nothing contradicts the candidate; there is simply too little of it.

    The third structural review class, alongside proposals and triage leads, and
    the one that asks least of a reviewer: no field disagrees with these
    candidates, so there is nothing to reconcile with the data owner. They are
    short of the evidence requirement, which is a statement about how much the two
    catalogues happen to say in common about the row -- not a conflict.

    Deliberately free of any registry- or model-specific reading: the class is
    defined by two columns the decision produces for every row, whatever
    catalogue pair or country it ran against.
    """
    # Keyed on the sub-status, not the status: a row refused because an
    # identifier carried it alone is also uncontradicted and also 'Insufficient
    # information', but it did not fall short of the evidence bar -- it can reach
    # it. Only rows the bar itself stopped belong in this class, and each
    # selector names that bar in its own terms: a threshold it did not reach, or
    # an Annex I criterion that went unanswered.
    rows = unique[unique['Review_Category'].isin({BELOW_THRESHOLD, CRITERION_SET})
                  & unique['compatible_candidate_count'].ge(1)]
    if rows.empty:
        return []
    sole = int(rows['compatible_candidate_count'].eq(1).sum())
    lines = [f'**{len(rows)} distinct unresolved vehicles carry an uncontradicted candidate**, {sole} of '
             'them a single one. No field disagrees with these candidates: they fall short of the evidence '
             'acceptance requires rather than conflicting with anything, so there is nothing to reconcile '
             'before a reviewer can judge them. None is assigned or counted in VIO. Where more than one '
             'candidate survives uncontradicted the shortlist is given and none is named, because the '
             'evidence that would separate them is the evidence the row lacks.', '']
    # The primary report describes the retained criterion requirement directly.
    dominance = unique['selection_rule'].eq('dominance').all()
    grouping = [column('model'), column('submodel'), 'remaining_kTypes',
                'Review_Fields' if dominance else 'top_match_score',
                'compatible_candidate_count']
    lines += [f"| Model | Submodel | Uncontradicted kType | {'Criteria unanswered' if dominance else 'Score'}"
              f" | {'Required' if dominance else 'Threshold'} | Distinct IDs |",
              '|---|---|---|---|---|---:|']
    for key, group in rows.groupby(grouping, dropna=False, sort=True):
        model, submodel, candidates, shortfall, count = key
        named = str(candidates) if count == 1 else f'{candidates} (shortlist of {int(count)})'
        bar = ('every comparable version criterion, plus one variant' if dominance
               else f"{group['accept_score_threshold'].iloc[0]:g}")
        shortfall = shortfall if dominance else f'{shortfall:g}'
        lines.append(f'| {model} | {submodel} | {named} | {shortfall or "—"} | {bar} | {len(group)} |')
    return lines + ['']


def _status_section(results: pd.DataFrame, unique: pd.DataFrame, accepted: int) -> list[str]:
    tolerance_dependent = int((results['count_in_vio'] & results['selected_power_tolerance_used']).sum())
    lines = [f'VIO is a partial count of accepted vehicles: **{len(unique) - accepted} distinct vehicles remain unresolved**. '
             'They remain in the review queue and source-population denominator; they are not absent vehicles.', '',
             (f'**{tolerance_dependent} accepted vehicles depend on the configured power tolerance**. '
              'The source/reference difference is exported in kW and as a percentage, and the tolerance '
              'earns no exact-power points.' if tolerance_dependent else
              '**Power agreement is exact**: no acceptance depends on a power tolerance. The allowance is '
              'not needed by any accepted assignment in this run. This does not establish which tolerance, '
              'if any, would be appropriate for other records.'), '',
             '| Status | Worksheet rows | Distinct IDs |', '|---|---:|---:|']
    for status in ALL_STATUSES:
        subset = results[results['Match_Status'] == status]
        lines.append(f"| {status} | {len(subset)} | {_normalized_ids(subset).nunique()} |")
    # Read without this, a zero on that row says the reference covered every vehicle,
    # which it does not: the status counts one way of missing and not the other.
    lines += ['',
              f'`{NO_CANDIDATE_IN_REFERENCE}` counts only vehicles whose normalized make and model '
              'match no reference row at all. A vehicle whose make and model are present but whose '
              f'version is not -- no candidate at its capacity or power -- stops as `{ALL_CANDIDATES_CONTRADICTED}`, '
              'which the same status also gives to a vehicle the reference does carry and disagrees with. '
              'The two are told apart by the quoted values in *Where coverage is lost*, not by the status.']
    return lines


def _late_registration_section(unique: pd.DataFrame) -> list[str]:
    """Accepted rows whose year is later than the kType's production end."""
    late = unique[unique['count_in_vio'] & unique['selected_registration_after_end_years'].notna()]
    if not len(late):
        return []
    lines = ['', '## Accepted with a vehicle year after production end', '',
             f"**{len(late)} accepted vehicles** carry a {column('year')} later than the end of their kType production "
             'interval. NZTA defines the field as year of manufacture or model year, falling back to year of first '
             'registration when manufacture is unknown, so this is legitimate for unsold stock registered late and is '
             'not treated as a contradiction. It is listed because these rows pass every specification check by '
             'construction, which makes an incorrect one hard to see. Confirm the pre/post-facelift split before relying on them.', '',
             '| Model | Submodel | kType | Production ends | Years later | Import status | Distinct IDs |',
             '|---|---|---:|---:|---:|---|---:|']
    for key, group in late.groupby([column('model'), column('submodel'), 'mapped kType',
                                    'selected_registration_after_end_years'], dropna=False, sort=True):
        model, submodel, ktype, lag = key
        ends = group['selected_construction_to'].iloc[0]
        statuses = sorted({normalized_text(value)
                           for value in group.get(column('import_status'), pd.Series(dtype=object)).dropna()})
        lines.append(f'| {model} | {submodel} | {int(ktype)} | {ends or "—"} | {lag:g} | '
                     f'{"; ".join(statuses) or "—"} | {len(group)} |')
    return lines + ['']


def _lost_coverage_section(unique: pd.DataFrame) -> list[str]:
    """Every unaccepted vehicle, attributed to a cause and a field."""
    unresolved = unique[unique['Match_Status'] != MATCHED]
    if not len(unresolved):
        return []
    lines = ['', '## Where coverage is lost', '',
             'Every unaccepted vehicle carries a review sub-status and, where one applies, the specification '
             'field the row stopped on. These classify why the row stopped; they do not claim which source is wrong. '
             'A field marked *every candidate* has to be reconciled before the row can be matched at all; one marked '
             'with a count blocks only that many candidates, so it is the most frequent obstacle rather than a '
             'universal one. The last column quotes both catalogues verbatim, because the field name alone does not '
             'distinguish a vehicle the reference does not carry from one it records a few units away.', '',
             '| Review sub-status | Field | Covers | Source vs reference | Status | Distinct IDs |',
             '|---|---|---|---|---|---:|']
    for key, group in unresolved.groupby(['Review_Category', 'Review_Fields', 'Review_Fields_scope',
                                          'blocking_values', 'Match_Status'], sort=True):
        category, review_fields, scope, values, status = key
        lines.append(f"| {category} | {review_fields or '—'} | {scope or '—'} | {values or '—'} | "
                     f'{status} | {len(group)} |')
    return lines


def _source_group_section(unique: pd.DataFrame) -> list[str]:
    lines = ['', '## Outcomes by source group', '',
             '| Model | Submodel | Status | kType / alternatives | Distinct IDs |', '|---|---|---|---|---:|']
    for key, group in unique.groupby([column('model'), column('submodel'), 'Match_Status', 'remaining_kTypes'],
                                     dropna=False, sort=True):
        model, submodel, status, alternatives = key
        if status == MATCHED:
            alternatives = '; '.join(map(str, sorted(group['mapped kType'].dropna().astype(int).unique())))
        lines.append(f"| {model} | {submodel} | {status} | {alternatives or '—'} | {len(group)} |")
    return lines


def selection_description(policy) -> str:
    """Describe the active acceptance policy, not the diagnostic score columns."""
    if not policy.use_scoring:
        return ('Rules-only: requires a unique compatible candidate after identifier narrowing, '
                'sufficient evidence and the source/identifier conflict checks. Scores are diagnostic.')
    if policy.selection == 'dominance':
        return ('Criterion policy: acceptance requires exactly one compatible candidate. A documented '
                'manufacturer model code decoded from a scoped identifier and agreeing with the reference takes priority over '
                'missing criterion evidence; a documented disagreement remains a veto and an absent '
                'or unsupported code is neutral. Without that code, every comparable version criterion '
                'and at least one variant criterion must agree. Additional '
                'positive evidence cannot eliminate a compatible sibling, catalogue size does not '
                'change sufficiency, and missing capacity still requires a structural identifier. '
                'Conflict and unearned-elimination checks also apply. '
                'These are provisional engineering rules, not fitted or calibrated estimates.')
    return ('Weighted score: uses a support threshold and margin, or the sole-candidate complete-version '
            'route that bypasses the threshold. Both routes require the evidence floor and conflict '
            'safeguards. Ties require review. These are provisional settings, not fitted or calibrated estimates.')


def _decision_policy_section(metadata: dict) -> list[str]:
    """Describe the one policy used by the primary workflow."""
    from .config import Policy
    policy = Policy(**json.loads(metadata['policy']))
    lines = ['', '## Decision policy', '', selection_description(policy), '']
    if policy.use_scoring and policy.selection == 'score':
        lines += [f'Acceptance threshold: **{policy.accept_score:g}/{attainable_score():g}**; '
                  f'minimum margin: **{policy.min_margin:g} points**.', '']
    lines += [f'Year mode: `{policy.year_mode}`. Gate mode excludes candidates whose '
              '`Construction_from` year is later than the registry year. It does not gate on '
              '`Construction_to`, because the registry year may be first-registration year. '
              'Soft mode retains every make/model candidate for sensitivity analysis.', '',
              f'Sourced VIN helper: {"enabled" if policy.use_vin_helper and policy.use_identifiers else "disabled"}. '
              'Reviewed VIN facts can corroborate specifications or contradict candidates. '
              'Reviewed VIN evidence may support or block an assignment; see docs/algorithm.md.', '',
              'Unresolved candidate review order first promotes sole near-power conflicts, '
              'prefers positive identity/generation agreement within a conflict class, and '
              'places identity contradictions after configuration/specification conflicts; '
              'RapidFuzz text similarity is a later tie-breaker. It never '
              'changes compatibility, status, proposals or assignments.', '']
    return lines


def _evaluation_limits_section(results: pd.DataFrame, unique: pd.DataFrame) -> list[str]:
    labeled = unique[unique['provided_kType'].notna()]
    agreement = labeled['provided_label_agreement']
    return ['', '## Evaluation limits', '',
            f'- Supplied labels: {len(labeled)} distinct vehicle IDs; '
            f"{int(agreement.eq('agree').sum())} agree, {int(agreement.eq('disagree').sum())} disagree, "
            f"{int(agreement.eq('unassigned').sum())} unassigned. "
            f'The labels cover {labeled["provided_kType"].nunique()} kType(s) and do not measure general accuracy.',
            f"- Conflicting provided labels within a normalized vehicle ID: "
            f"{_normalized_ids(results[results['provided_label_conflict']]).nunique()}.",
            f"- Exact duplicate copies retained but excluded from VIO: {int(results['duplicate_of'].ne('').sum())}.",
            '- Dataset-derived structural parsing and the power near-match policy are review context, not ground truth. '
            'Body agreement is limited to official names shared by both publishers; unreviewed pairs remain unknown. '
            'VIN facts carry source provenance, while their reference comparisons still need independent validation.',
            '- RapidFuzz similarity orders unresolved candidates for review only. It is uncalibrated, '
            'is not a probability and contributes no matching evidence.',
            # Whatever this register says about itself; another register's file
            # states its own, and one that states none prints none.
            *(f'- {note}' for note in registry_report_notes()),
            '- Transmission is not validated because the reference lacks transmission data.',
            '- Complete Hyundai engine prefixes are compared as a scoped dataset-derived format rule. They can corroborate '
            'a sole compatible candidate but cannot eliminate a still-compatible sibling; other formats remain unknown.',
            '- Assessment is limited to the supplied data and the reviewed VIN helper. Unresolved cases remain unresolved; '
            'no additional ground-truth examples are assumed.', '',
            "See the workbook's Candidate_Evidence sheet for rejected alternatives and the Results sheet for row-level reasons. "
            'Unaccepted rows never enter the VIO sheet.', '']


def _candidate_summary(row) -> tuple[str, str]:
    """What the row points at, and how strongly. Never an assignment.

    The three pointers already computed per row differ in standing, and
    flattening them into one column would let the weakest inherit the strongest's
    credibility. The standing is stated alongside the kType instead.
    """
    if pd.notna(row['proposed_kType']):
        return str(int(row['proposed_kType'])), 'identifiers agree; one specification conflicts'
    if pd.notna(row['triage_lead_kType']):
        others = f" (also close: {row['triage_lead_alternatives']})" if row['triage_lead_alternatives'] else ''
        return f"{int(row['triage_lead_kType'])}{others}", 'closest candidate, for triage only'
    if row['triage_lead_alternatives']:
        return row['triage_lead_alternatives'], 'shortlist; none is closer than the others'
    if row['remaining_kTypes']:
        count = int(row['compatible_candidate_count'])
        return row['remaining_kTypes'], ('sole uncontradicted candidate' if count == 1
                                         else f'{count} uncontradicted candidates')
    # Candidates were compared and every one was contradicted: saying 'none' here
    # would repeat the status, so say the thing the status does not -- that none
    # of them came within a single field of fitting.
    return '—', 'no candidate within one specification'


def _identifier_codes(row) -> str:
    """The row's parsed structural codes, as text, or blank where it carries none."""
    codes = json.loads(row['parsed_identifiers'] or '{}')
    return '; '.join(f"{field}: {', '.join(values)}" for field, values in sorted(codes.items()))


def _review_question(row, candidates: str) -> str:
    """The one thing this decision is asking a human to rule on."""
    status, fields = row['Match_Status'], row['Review_Fields']
    if status == PROPOSED:
        return (f'Advisory evidence proposes kType {candidates}. Is the {fields} difference a catalogue '
                'discrepancy, or is this a different vehicle?')
    if status == AMBIGUOUS:
        return f'Which of kTypes {candidates} is correct? See decide_on for how they differ.'
    if status == ALL_CANDIDATES_CONTRADICTED:
        if candidates != '—':
            return (f'Is kType {candidates} correct despite the {fields} difference, or does this '
                    'vehicle belong to a kType the reference does not carry?')
        return f'Every candidate disagrees on {fields}. Which catalogue is right?'
    if status == SOLE_CANDIDATE_INCOMPLETE:
        return (f'kType {candidates} is the only uncontradicted candidate, but evidence is incomplete. '
                f"{row['Match_Reason']} What additional evidence can resolve this?")
    if status == NO_CANDIDATE_IN_REFERENCE:
        return 'The reference carries no candidate for this make/model. Is the catalogue missing it?'
    if status == CONFLICT:
        return f'The source row contradicts itself on {fields}. Which value is correct?'
    return f'Not enough shared evidence to judge ({row["Review_Category"]}). Can the gap be filled?'


def review_queue(results: pd.DataFrame) -> pd.DataFrame:
    """One row per decision a human has to make, not one row per vehicle.

    The audit trail belongs in Review_Detail; this sheet is the thing a reviewer
    actually works from, so it carries only what a decision needs and is ordered
    by how many vehicles ride on it. Grouping is by the columns that define the
    decision, so two vehicles asking the same question appear once.
    """
    unresolved = results[results['Match_Status'].ne(MATCHED)]
    if unresolved.empty:
        return pd.DataFrame(columns=list(REVIEW_QUEUE_COLUMNS))
    keys = [column('make'), column('model'), column('submodel'), 'Match_Status',
            'Review_Category', 'Review_Fields', 'Review_Fields_scope', 'proposed_kType',
            'triage_lead_kType', 'triage_lead_alternatives', 'remaining_kTypes',
            'compatible_candidate_count', 'differentiating_fields', 'blocking_values']
    rows = []
    conflicts = unresolved[unresolved['duplicate_id_conflict']]
    for _, group in conflicts.groupby(_normalized_ids(conflicts), sort=False):
        first = group.iloc[0]
        ids = list(dict.fromkeys(group[column('id')].astype(str)))
        source_rows = list(dict.fromkeys(group['source_key'].astype(str)))
        rows.append({
            'vehicles': 1,
            'make': first[column('make')], 'model': first[column('model')],
            'submodel': first[column('submodel')],
            'status': first['Match_Status'],
            'why': first['Review_Category'],
            'candidates': '—',
            'decide_on': 'Reconcile the differing source values in the linked rows.',
            'identifier_evidence': _identifier_codes(first),
            'question': 'Which linked source row contains the correct vehicle facts?',
            'IDs': '; '.join(ids),
            'source_rows': '; '.join(source_rows),
        })
    ordinary = unresolved[unresolved['canonical_record'] & ~unresolved['duplicate_id_conflict']]
    for _, group in ordinary.fillna({'Review_Fields': '', 'differentiating_fields': '',
                                     'blocking_values': ''}).groupby(keys, dropna=False, sort=False):
        first = group.iloc[0]
        candidates, standing = _candidate_summary(first)
        scope = f" ({first['Review_Fields_scope']})" if first['Review_Fields_scope'] else ''
        ids = sorted(group[column('id')].astype(str))
        source_rows = sorted(group['source_key'].astype(str))
        rows.append({
            'vehicles': len(ids),
            'make': first[column('make')], 'model': first[column('model')],
            'submodel': first[column('submodel')],
            'status': first['Match_Status'],
            'why': first['Review_Category'] + (f" — {first['Review_Fields']}{scope}"
                                               if first['Review_Fields'] else ''),
            'candidates': standing if candidates == '—' else f'{candidates} — {standing}',
            'decide_on': first['differentiating_fields'] or first['blocking_values'] or '',
            'identifier_evidence': first['proposal_basis'] or _identifier_codes(first),
            'question': _review_question(first, candidates),
            'IDs': '; '.join(ids if len(ids) <= 12 else ids[:12] + [f'... +{len(ids) - 12} more']),
            'source_rows': '; '.join(source_rows if len(source_rows) <= 12 else
                                    source_rows[:12] + [f'... +{len(source_rows) - 12} more']),
        })
    queue = pd.DataFrame(rows, columns=list(REVIEW_QUEUE_COLUMNS))
    return queue.sort_values('vehicles', ascending=False, kind='stable').reset_index(drop=True)


def policy_decisions_frame(policy) -> pd.DataFrame:
    """Who chose each setting this run used, and on what basis.

    This records which values are ours to have chosen -- the distinction a reader
    needs before treating any of them as a finding rather than a decision awaiting
    an owner. The primary workbook filters this broader internal register through
    :func:`decision_policy_frame`.
    """
    rows = []
    for name, entry in policy_decisions().items():
        value = getattr(policy, name, entry['default'])
        rows.append({'setting': name,
                     # Text, not the native value: the column mixes floats, bools
                     # and strings, and a mixed column round-trips through Excel
                     # as whichever type dominates -- 1.0 came back as True.
                     'value_this_run': f'{value:g}' if isinstance(value, float) else str(value),
                     'decided_by': entry['decided_by'],
                     'basis': entry['basis'],
                     'affects_acceptance': entry['affects_acceptance'],
                     'active_for_acceptance_this_run': entry['affects_acceptance'] and not (
                         name in ('accept_score', 'min_margin', 'field_weights', 'year_weight')
                         and (not policy.use_scoring or policy.selection != 'score')),
                     'overridden': value != entry['default'],
                     'cli_flag': entry['cli_flag'] or '',
                     'rationale': entry['rationale']})
    frame = pd.DataFrame(rows)
    # The owner's decisions first: they are what a reader is being asked to act on.
    return frame.sort_values(['decided_by', 'affects_acceptance', 'setting'],
                             ascending=[True, False, True]).reset_index(drop=True)


def decision_policy_frame(policy) -> pd.DataFrame:
    """Only settings that describe the maintained default and its audit output."""
    retained = {
        'power_tolerance_pct', 'power_triage_kw', 'use_identifiers', 'year_mode',
        'use_vin_helper', 'evidence', 'reuse_identical_rows', 'selection',
    }
    frame = policy_decisions_frame(policy)
    frame = frame[frame['setting'].isin(retained)].copy()
    return frame.drop(columns=['overridden', 'cli_flag',
                               'active_for_acceptance_this_run']).reset_index(drop=True)


def build_sheets(results: pd.DataFrame, evidence: pd.DataFrame, policy, metadata: dict) -> dict:
    """Every sheet the workbook carries, ordered by :data:`WORKBOOK_SHEETS`."""
    vio = (results.loc[results['count_in_vio']].groupby('mapped kType').size()
           .rename('distinct_vehicle_count').reset_index())
    counts = (results.groupby('Match_Status')
              .agg(worksheet_rows=(column('id'), 'size'),
                    distinct_IDs=(column('id'),
                                  lambda values: values.map(normalized_text).nunique()))
              .reset_index())
    published_results = results.drop(columns=list(RESULT_DIAGNOSTIC_COLUMNS), errors='ignore')
    published_evidence = evidence.drop(columns=list(EVIDENCE_DIAGNOSTIC_COLUMNS), errors='ignore')
    frames = {'Results': published_results, 'Candidate_Evidence': published_evidence,
              'Review_Queue': review_queue(results),
              'Review_Detail': published_results[published_results['Match_Status'] != MATCHED],
              'Duplicates': published_results[
                  published_results['duplicate_of'].ne('')
                  | published_results['duplicate_id_conflict']],
              'VIO': vio, 'Summary': counts,
              'Decision_Policy': decision_policy_frame(policy),
              'Metadata': pd.DataFrame(metadata.items(), columns=['property', 'value'])}
    # One declared order, so a new sheet cannot silently appear in the middle.
    return {name: frames[name] for name in WORKBOOK_SHEETS}


def write_workbook(sheets: dict, output: Path) -> None:
    """Write every sheet atomically, so a failed run cannot leave a half workbook."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix='.xlsx', dir=output.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with pd.ExcelWriter(temporary, engine='openpyxl') as writer:
            for name, frame in sheets.items():
                frame.to_excel(writer, sheet_name=name, index=False)
                _format_sheet(writer.sheets[name], frame)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def _format_sheet(sheet, frame: pd.DataFrame) -> None:
    """Freeze the header, enable filtering, and neutralize accidental formulas."""
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions
    # Source strings are data, never formulas. Scanning every cell is
    # O(rows x columns) in Python, so only pay it when a value could actually
    # have been typed as a formula.
    text_columns = frame.select_dtypes(include=['object', 'string'])
    if not any(text_columns[column].astype('string').str.startswith('=').fillna(False).any()
               for column in text_columns.columns):
        return
    for cells in sheet.iter_rows():
        for cell in cells:
            if cell.data_type == 'f':
                cell.data_type = 's'
