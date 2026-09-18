"""Turning one row's candidate evidence into one auditable outcome.

The cascade is ordered by how fundamental a problem is. A row that contradicts
itself is stopped before any candidate is considered; identifiers that disagree
with each other are stopped before either is believed; only once the row and its
identifiers are coherent does score ranking decide anything. Every branch that
does not accept names a review sub-status and, where one applies, the field the
row stopped on.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field as dataclass_field

import pandas as pd

from .chassis_decoder import chassis_audit_columns, decode_chassis_model
from .config import (ACCEPTED_ON_DOMINANCE, ACCEPTED_ON_SCORE, ACCEPTED_ON_UNIQUENESS,
                     ALL_CANDIDATES_CONTRADICTED, ALL_CONTRADICTED, AMBIGUOUS, BELOW_THRESHOLD,
                     COMPARED_FIELDS, CONFLICT, CRITERION_SET, DISPLACEMENTLESS_FUELS,
                     DUPLICATE_CONFLICT, EVIDENCE_FLOOR, NOT_SEPARATED,
                     EXPORTED_REFERENCE_COLUMNS, FIELD_VALUE_SOURCES, IDENTIFIER_DISAGREEMENT,
                     IDENTIFIER_UNSUPPORTED, IDENTIFIER_VS_SPECIFICATION,
                     IDENTIFIER_WITHOUT_SPECIFICATION, UNEARNED_ELIMINATION, VERSION_CRITERIA,
                     INSUFFICIENT, MATCHED, MINIMUM_ANCHOR_FIELDS, NARROW_MARGIN,
                     NEAR_POWER_ONLY, NO_CANDIDATE,
                     NO_CANDIDATE_IN_REFERENCE, PROPOSED, SOLE_CANDIDATE_INCOMPLETE,
                     column, identifiers, identifiers_where,
                     source_field,
                     vin_value,
                     SEPARABLE_ONLY_BY_SCOPED_RULE,
                     SELF_CONTRADICTION, TIED_CANDIDATES, VIN_CONTRADICTION, core_conflict,
                     score_rules)
from .dominance import criterion_columns, criterion_vector, sufficient
from .evidence import active_structural_codes, candidate_evidence, identifier_context
from .normalization import (compact_code, model_year, normalized_text, numeric_value,
                            submodel_drive_category)
from .review_ranking import add_review_similarity, order_review_candidates
from .scoring import SCORE_COLUMNS, rank_candidates, score_candidate
from .submodel import audit_columns as submodel_audit_columns, source_context as submodel_context
from .vin_evidence import audit_columns as vin_audit_columns, drive_comparison, vin_context


def vin_drive_conflict() -> str:
    """The conflict a VIN drive disagreeing with the submodel text is recorded as."""
    return f"VIN drive contradicts {column('submodel')} drive"


def vin_engine_conflict() -> str:
    return f"VIN engine contradicts {column('engine_number')} code"


def vin_conflict_fields() -> dict:
    """Which specification each recorded VIN conflict belongs to.

    Built per run rather than declared once, because two of the three messages
    name a register column and the register is selected per run.
    """
    return {'VIN profile contradicts supplied make/model': 'make/model',
            vin_drive_conflict(): 'drive',
            vin_engine_conflict(): 'engine'}


@dataclass
class Outcome:
    """What happened to one row, and why.

    The four leading fields are positional because every branch supplies them in
    the same order. Everything after them is keyword-only: these are the optional
    details that get added to over time, and a new one appended here must never
    silently capture an argument meant for the field that used to follow it.
    """

    status: str = INSUFFICIENT
    selected: int | None = None
    reason: str = 'Candidate evidence is insufficient for acceptance.'
    category: str = EVIDENCE_FLOOR
    fields: str = dataclass_field(default='', kw_only=True)
    # How much of the candidate set `fields` covers: 'every candidate', an
    # 'N of M candidates' count, or blank where the field came from elsewhere.
    fields_scope: str = dataclass_field(default='', kw_only=True)
    proposal: dict | None = dataclass_field(default=None, kw_only=True)
    # A weaker, non-identifier reading than `proposal`: see triage_lead.
    lead: dict | None = dataclass_field(default=None, kw_only=True)
    # Which acceptance route allowed this row through, blank where none did.
    route: str = dataclass_field(default='', kw_only=True)
    # The candidates an ambiguous row could not be separated between, where the
    # branch knows them. The score route's are its score leaders; the dominance
    # route's are the candidates no rival out-agrees, which are not the same set,
    # so the branch says which rather than letting the reader assume.
    tied: list | None = dataclass_field(default=None, kw_only=True)


@dataclass(kw_only=True)
class AnchorState:
    """What the row's structural identifiers point at, and whether they agree."""

    codes: dict = dataclass_field(default_factory=dict)
    per_field: dict = dataclass_field(default_factory=dict)
    anchored: set = dataclass_field(default_factory=set)
    populated: list = dataclass_field(default_factory=list)
    unsupported: list = dataclass_field(default_factory=list)
    conflicting: bool = False

    @property
    def has_identifiers(self) -> bool:
        return bool(self.populated)


EVERY_CANDIDATE = 'every candidate'


def blocking_conflicts(details) -> tuple[list[str], str]:
    """The fields that stopped the row, and how much of the candidate set they cover.

    A field contradicted on *every* candidate is the strongest thing review can
    be told: the row cannot be rescued by picking a different candidate, so that
    field has to be reconciled. That is reported whenever such a field exists.

    Often none does, because the candidates fail on a mix -- one on capacity, the
    next on power. Reporting nothing there leaves a reviewer with a cause but no
    field to act on, so the most frequently contradicted field is reported
    instead, with its coverage, and the caller records that it is not universal.
    The distinction matters: fixing a universal conflict could unblock the row,
    while fixing a partial one only unblocks some of the candidates.
    """
    conflict_sets = [{core_conflict(f) for f in entry['disagreements'].split('; ') if f}
                     for entry in details]
    if not conflict_sets:
        return [], ''
    universal = set.intersection(*conflict_sets)
    if universal:
        return sorted(universal), EVERY_CANDIDATE
    counts = Counter(field for conflicts in conflict_sets for field in conflicts)
    if not counts:
        return [], ''
    most = max(counts.values())
    return (sorted(field for field, n in counts.items() if n == most),
            f'{most} of {len(conflict_sets)} candidates')


def near_power_candidates(details) -> list:
    """Contradicted candidates whose only disagreement is a power difference
    inside the review band.

    Says nothing about whether such a candidate is the right one. It records
    that the row stopped on a number the two publishers may simply have rounded
    differently rather than on a specification they disagree about, so the
    question can be put to the data owner as a question rather than filed as a
    rejection. The band is ``power_triage_kw``, which is engineering's to set
    precisely because it cannot accept anything: acceptance stays with
    ``power_tolerance_pct``, and this function is never consulted for it.
    """
    found = []
    for entry in details:
        if entry['compatible']:
            continue
        conflicts = {core_conflict(name)
                     for name in entry['disagreements'].split('; ') if name}
        if conflicts == {'power'} and entry.get('power_within_triage_band'):
            found.append(entry['KType'])
    return sorted(found)


def identifier_proposal(details, anchors: AnchorState):
    """Triage only: name the candidate the identifiers point at, never accept it.

    Two or more distinct identifier fields must agree on exactly one kType,
    and that kType must be contradicted on exactly one independent specification.
    The result is a human-confirmation queue entry; `mapped kType` stays empty
    and the vehicle never enters VIO. Identifiers still do not override
    specifications, they only explain why the row deserves a quick decision.
    """
    fields = [name for name in identifiers_where('authoritative') if anchors.per_field[name]]
    if len(anchors.anchored) != 1 or len(fields) < MINIMUM_ANCHOR_FIELDS:
        return None
    target = next(iter(anchors.anchored))
    candidate = next((entry for entry in details if entry['KType'] == target), None)
    if candidate is None or candidate['compatible'] or not candidate['disagreements']:
        return None
    conflicts = {core_conflict(f) for f in candidate['disagreements'].split('; ')}
    if len(conflicts) != 1 or conflicts & score_rules()['unproposable_conflicts']:
        return None
    tokens = sorted({token for field in fields
                     for token in candidate[f'{field}_tokens'].split('; ') if token})
    return {'kType': candidate['KType'], 'conflicts': sorted(conflicts),
            'basis': ' + '.join(fields) + ' agree on ' + '; '.join(tokens)}


def model_code_hint_proposal(details):
    """One officially named model-code correspondence, for review only.

    A proposal-only decoder is deliberately weaker than a candidate veto: its
    agreement cannot make a candidate compatible, and its disagreement cannot
    remove one. It merely names the one reference row carrying the same reviewed
    manufacturer type value.
    """
    agreeing = [entry for entry in details
                if entry.get('chassis_model_hint_comparison') == 'agree']
    if len(agreeing) != 1:
        return None
    candidate = agreeing[0]
    conflicts = sorted({core_conflict(field) for field in
                        candidate['disagreements'].split('; ') if field})
    return {'kType': candidate['KType'], 'conflicts': conflicts,
            'basis': (f"{candidate['chassis_model_source_field']} manufacturer model-code hint "
                      f"{candidate['chassis_model_code']} agrees with reference Type_design "
                      f"{candidate['chassis_model_reference_codes']}")}


def triage_lead(details, policy):
    """Triage only: name the one candidate a single field away from compatible.

    When every candidate is contradicted the row stops with a cause and a field,
    which says what is wrong but not what the vehicle probably is. A reviewer
    then re-derives that by hand from thirty-odd candidate rows. This names the
    candidate worth looking at first, and nothing else: no kType is assigned, the
    vehicle is not counted in VIO, the veto stands and no score changes.

    Two readings qualify, in order of how much the data supports them. A
    candidate blocked *only* by power, by a margin the rounding band explains, is
    the stronger one: the catalogues may not actually disagree at all. Failing
    that, a candidate that is the sole one blocked by exactly one specification
    is still the obvious place to start.

    Both require uniqueness. Where several candidates are each one field from
    compatible, naming one would be choosing the answer rather than triaging, so
    no kType is named -- but the shortlist is still exported, because narrowing
    thirty candidates to three is most of the work and costs no judgement.
    Chronology is excluded for the reason identifier proposals exclude it: a
    production interval that cannot contain the vehicle suggests the wrong
    candidate altogether, not a near miss.

    The readings are tried strongest first, and that ordering is the whole point
    of this function. Compatibility evidence -- which fields actually agreed and
    disagreed -- comes before the marketing capacity written in the registration
    text, because the first is the comparison the algorithm performed and the
    second is a string a person typed. Trying the weaker reading first does not
    merely mis-rank the queue: it returns early and suppresses the stronger one
    entirely, so a row that could have named one kType names six instead.
    """
    leads = []
    for entry in details:
        if entry['compatible'] or not entry['disagreements']:
            continue
        conflicts = {core_conflict(field) for field in entry['disagreements'].split('; ') if field}
        if len(conflicts) != 1 or conflicts & score_rules()['unproposable_conflicts']:
            continue
        leads.append((entry, next(iter(conflicts))))
    rounding = [pair for pair in leads if pair[1] == 'power' and pair[0]['power_within_triage_band']]
    if len(rounding) == 1:
        entry, conflict = rounding[0]
        basis = (f"blocked only by power: {entry['power_difference_kw']:+g} kW against reference "
                 f"{entry['reference_Maximum_output_KW']} kW, inside the {policy.power_triage_kw:g} kW "
                 'band that independent integer rounding of one figure can produce')
    elif len(leads) == 1:
        entry, conflict = leads[0]
        basis = f'blocked only by {conflict}; every other compared specification agrees'
    elif len(leads) > 1:
        fields = '; '.join(sorted({conflict for _, conflict in leads}))
        return {'kType': None, 'field': fields, 'alternatives': sorted(e['KType'] for e, _ in leads),
                'basis': f'{len(leads)} candidates are each blocked by exactly one specification '
                         f'({fields}); none is named, because choosing between them is the reviewer '
                         'decision, not a triage step'}
    else:
        return _litre_shortlist(details)
    return {'kType': entry['KType'], 'field': conflict, 'basis': basis,
            'alternatives': sorted(other['KType'] for other, _ in leads
                                   if other['KType'] != entry['KType'])}


def _litre_shortlist(details):
    """The weakest reading: marketing capacity in the registration text.

    Deliberately a shortlist criterion and not a compatibility criterion, and
    deliberately the last thing `triage_lead` tries. It is used only when every
    gated candidate states a comparable value and the agreement genuinely narrows
    the pool; unknown values must never be silently eliminated.
    """
    litre_matches = [entry for entry in details
                     if entry.get('submodel_capacity_litre') == 'agree']
    litre_comparable = [entry for entry in details
                        if entry.get('submodel_capacity_litre') in {'agree', 'disagree'}]
    if not (litre_matches and len(litre_comparable) == len(details)
            and len(litre_matches) < len(details)):
        return None
    alternatives = sorted(entry['KType'] for entry in litre_matches)
    return {
        'kType': None,
        'field': 'submodel capacity',
        'alternatives': alternatives,
        'basis': (f"{column('submodel')} capacity agrees numerically with reference "
                  f"Capacity_litre for {len(alternatives)} of {len(details)} candidates; "
                  'decimal point and comma spellings are equivalent; shortlist only'),
    }


def scoped_structural_preference(details, candidate_ids):
    """Name the candidate a model-specific reading favours, without accepting it.

    Some candidates are separated by nothing a catalogue can check. The two
    Colorado kTypes are identical on capacity, power, drive, engine code, type
    designation and production interval, and differ only in body: one is a
    cab-chassis, the other a pickup. The registration SUBMODEL says which cab the
    vehicle has, and for that model the manufacturer sold no single-cab pickup.

    That reasoning is sound for one model and does not generalise: other makes
    sell single-cab pickups, and the same wording means different things across
    manufacturers. Encoding it as a veto would be indistinguishable from choosing
    the answer, because with candidates identical in every other respect
    eliminating one *is* selecting the other. So the reading names the likely
    candidate for a reviewer and the row stays unassigned.

    **Inert on the supplied catalogue pair, and on every registry shipped here.**
    This function can only fire where `submodel_cab` resolves to 'consistent' or
    'disagree'. It resolves to 'unknown' on all 7,645 candidate-evidence rows of
    the supplied run, because the cab restriction it depends on was removed from
    `rules/registries/nz.json`: that restriction rested on a Holden model-lineup
    specification which is not an NZTA, TecAlliance or RDM source and could not be
    produced for review. The removal is recorded in the `cab_configurations`
    description in that file.

    The consequence matters for reading the Colorado result and is stated here so
    that nobody infers otherwise from this code: the ten Colorado rows stop as
    `candidates not separated by criterion set`, not as `separable only by a
    model-specific reading`, and separating them needs the KT 086 ruling named in
    the review queue, not this function. The function is retained rather than
    deleted because a registry that does publish a cab vocabulary would want
    exactly this behaviour -- name the candidate, assign nothing -- and because
    `SEPARABLE_ONLY_BY_SCOPED_RULE` is a declared status with a contract entry in
    `config.STATUS_CATEGORIES` and a rendering path in the review UI. It is
    unreachable today, not speculative.
    """
    considered = [entry for entry in details if entry['KType'] in candidate_ids]
    favoured = [entry for entry in considered if entry['submodel_cab'] == 'consistent']
    excluded = [entry for entry in considered if entry['submodel_cab'] == 'disagree']
    if len(favoured) != 1 or not excluded or len(favoured) + len(excluded) != len(considered):
        return None
    return {'kType': favoured[0]['KType'],
            'conflicts': [],
            'basis': f"{column('submodel')} cab wording favours " + favoured[0]['reference_Kind_of_structure']
                     + ' over ' + '; '.join(sorted({e['reference_Kind_of_structure'] for e in excluded}))
                     + '; a model-specific reading, not a general rule'}


def cross_field_vin_conflicts(row, decoded_vin) -> None:
    """Record where the decoded VIN contradicts another field of the same row.

    These comparisons need both the VIN facts and the structured columns, so
    they live here rather than inside the VIN helper, which never sees the row.
    """
    facts = decoded_vin['facts']
    if 'drive' in facts and drive_comparison(
            facts['drive']['value'], submodel_drive_category(source_field(row, 'submodel'))) == 'disagree':
        decoded_vin['source_conflicts'].append(vin_drive_conflict())
    # Only recognize complete engine codes in the source engine-number prefix.
    # MR20 by itself, for example, does not establish MR20DD versus MR20DE.
    if decoded_vin['profile'] == 'nissan_t32' and 'engine' in facts:
        engine_number = compact_code(source_field(row, 'engine_number'))
        recognized = {code for code in decoded_vin['recognized_engine_codes']
                      if engine_number.startswith(code)}
        if recognized and facts['engine']['value'] not in recognized:
            decoded_vin['source_conflicts'].append(vin_engine_conflict())


def anchor_state(row, details, policy) -> AnchorState:
    """Resolve which kTypes the row's specific identifiers support."""
    per_field = {field: {entry['KType'] for entry in details if entry[f'{field}_tokens']}
                 for field in identifiers_where('authoritative')}
    populated = [ktypes for ktypes in per_field.values() if ktypes]
    anchored = set.intersection(*populated) if populated else set()
    codes = active_structural_codes(row, policy)
    conflicting = (
        policy.use_identifiers and decode_chassis_model(row)['status'] == 'conflicting'
        or (len(populated) > 1 and not anchored)
    )
    # Recognized VIN/MVMA codes must agree even if one is absent from reference.
    manufacturer_codes = [values for name, values in codes.items()
                          if values and name in identifiers_where('manufacturer_assigned')]
    if len(manufacturer_codes) > 1 and not set.intersection(*manufacturer_codes):
        conflicting = True
    unsupported = [name for name in identifiers_where('expected_in_reference')
                   if codes[name] and not per_field[name]]
    return AnchorState(codes=codes, per_field=per_field, anchored=anchored,
                       populated=populated, unsupported=unsupported, conflicting=conflicting)


def _source_conflict_outcome(row, decoded_vin, parsed_submodel, anchors) -> Outcome | None:
    """Problems with the row itself, or between its own identifiers."""
    if row.get('duplicate_id_conflict', False):
        return Outcome(CONFLICT, None,
                       'Same vehicle ID occurs with different source values; reconcile duplicate records.',
                       DUPLICATE_CONFLICT)
    if submodel_drive_category(source_field(row, 'submodel')) == 'conflict':
        return Outcome(CONFLICT, None,
                       'Source submodel contains mutually exclusive drive descriptions.',
                       SELF_CONTRADICTION, fields='drive')
    if parsed_submodel['source_conflicts']:
        return Outcome(CONFLICT, None,
                       '; '.join(parsed_submodel['source_conflicts']) + '; manual review required.',
                       SELF_CONTRADICTION,
                       fields='; '.join(parsed_submodel['source_conflict_fields']))
    if decoded_vin['source_conflicts']:
        named = (vin_conflict_fields().get(conflict, '') for conflict in decoded_vin['source_conflicts'])
        return Outcome(CONFLICT, None,
                       '; '.join(decoded_vin['source_conflicts']) + '; manual review required.',
                       VIN_CONTRADICTION,
                       fields='; '.join(dict.fromkeys(name for name in named if name)))
    if anchors.conflicting:
        return Outcome(CONFLICT, None,
                       'Specific structural identifiers disagree; no automatic precedence is applied.',
                       IDENTIFIER_DISAGREEMENT)
    return None


def _identifier_versus_specification_outcome(details, compatible, anchors) -> Outcome | None:
    """Identifiers point somewhere the specifications refuse to go."""
    if not anchors.has_identifiers or compatible & anchors.anchored:
        return None
    proposal = identifier_proposal(details, anchors)
    if proposal is None:
        anchored_details = [entry for entry in details if entry['KType'] in anchors.anchored]
        fields, scope = blocking_conflicts(anchored_details)
        return Outcome(CONFLICT, None,
                       'Specific identifiers point to candidates contradicted by source specifications.',
                       IDENTIFIER_VS_SPECIFICATION, fields='; '.join(fields), fields_scope=scope)
    conflicts = ', '.join(proposal['conflicts'])
    return Outcome(PROPOSED, None,
                   f"Specific identifiers ({proposal['basis']}) uniquely indicate kType {proposal['kType']}, "
                   f'which agrees on every compared specification except {conflicts}. '
                   'Proposed for human confirmation only: no kType is assigned and the vehicle is not counted in VIO. '
                   'Reconcile the conflicting field with the data owner before accepting.',
                   IDENTIFIER_VS_SPECIFICATION, fields='; '.join(proposal['conflicts']),
                   proposal=proposal)


def _candidate_availability_outcome(details, compatible, anchors, policy) -> Outcome | None:
    """No candidate survived, or a recognized code is absent from the reference."""
    if not details:
        gate_note = (' and the diagnostic legacy year gate.' if policy.year_mode == 'gate' else '.')
        return Outcome(NO_CANDIDATE_IN_REFERENCE, None,
                       'No reference candidate passes normalized make/model gates' + gate_note,
                       NO_CANDIDATE)
    if not compatible:
        fields, scope = blocking_conflicts(details)
        named = '; '.join(fields)
        coverage = f' on {scope}' if scope else ''
        reason = ('All candidate variants have specification or chronology conflicts; manual review required.'
                  + (f' Blocked{coverage} by: {named}.' if named else ''))
        near_power = near_power_candidates(details)
        if near_power:
            reason += (' The closest candidate differs only on power, by less than the review band'
                       f" ({'; '.join(map(str, near_power))}): whether the two catalogues record that"
                       ' number the same way is a question for the data owner. No kType is assigned'
                       ' and the vehicle is not counted in VIO.')
        lead = triage_lead(details, policy)
        if lead is not None and lead['kType'] is None:
            reason += (f" Shortlist for review: kTypes {'; '.join(map(str, lead['alternatives']))}"
                       f" -- {lead['basis']}.")
        elif lead is not None:
            others = (' Other candidates are also one field from compatible: '
                      + '; '.join(map(str, lead['alternatives'])) + '.' if lead['alternatives'] else '')
            reason += (f" Closest candidate for review is kType {lead['kType']}, {lead['basis']}."
                       ' Named for triage only: no kType is assigned and the vehicle is not counted in VIO.'
                       + others)
        return Outcome(ALL_CANDIDATES_CONTRADICTED, None, reason,
                       NEAR_POWER_ONLY if near_power else ALL_CONTRADICTED,
                       fields=named, fields_scope=scope, lead=lead)
    if anchors.unsupported:
        return Outcome(INSUFFICIENT, None,
                       'Interpretable structural codes are not represented in the candidate reference: '
                       + ', '.join(anchors.unsupported) + '.',
                       IDENTIFIER_UNSUPPORTED, fields='; '.join(anchors.unsupported))
    return None


def _compatible_model_code_hint_outcome(details, compatible) -> Outcome | None:
    """Surface a unique model-code hint without letting it select a candidate."""
    if len(compatible) < 2:
        return None
    proposal = model_code_hint_proposal(details)
    if proposal is None or proposal['kType'] not in compatible:
        return None
    return Outcome(
        AMBIGUOUS, None,
        f"{len(compatible)} compatible candidates remain. {proposal['basis']}. This is the most "
        'likely candidate for review, but the composite registry-code format and cross-catalogue '
        'uniqueness are not established strongly enough for automatic assignment.',
        NOT_SEPARATED, proposal=proposal, tied=sorted(compatible))


def complete_version_evidence(entry, source_fuel) -> bool:
    """Agreement at both levels Regulation (EU) 2018/858 Annex I defines.

    Every version-defining criterion the two catalogues share must agree --
    engine capacity 1.3.1(b), the nature of the fuel (d) and the maximum engine
    power output (c) -- and so must at least one variant criterion, from
    bodywork 1.2.1(a), the power plant's construction features (b) or the
    powered axles (d).

    The variant requirement is not decoration. Capacity and fuel are gates the
    evidence floor already demands of every candidate, so "every version
    criterion agrees" would otherwise reduce to "power agrees" -- one scored
    field. Requiring a variant criterion too means the catalogues describe the
    same vehicle at both levels the approval regime distinguishes, which is a
    statement about the vehicle rather than about one number.

    A displacement-less vehicle has no cylinder capacity on either side, so
    capacity is skipped rather than failed -- the same exception the evidence
    floor makes, for the same reason.
    """
    for field in VERSION_CRITERIA:
        if field == 'capacity' and source_fuel in DISPLACEMENTLESS_FUELS:
            continue
        if entry[field] != 'agree':
            return False
    # Read from the tier table rather than subtracted from the weights. Under
    # subtraction, any field that started being scored would silently enrol
    # itself as an Annex I variant criterion and widen this route; the tier is a
    # claim about the Regulation, so it comes from the table that cites it.
    tiers = score_rules()['criterion_tier']
    variant_tier = [field for field, tier in tiers.items() if tier == 'variant']
    return any(entry[field] == 'agree' for field in variant_tier)


# Verdicts that mean a comparison said nothing about a candidate, as opposed to
# saying it agrees. Kept as data rather than an `== 'agree'` test because the
# non-specification comparisons speak in their own words -- chronology reports
# 'not contradicted', the SUBMODEL checks report 'consistent' -- and each of
# those is the field speaking for the candidate, not silence.
SILENT_VERDICTS = frozenset({'unknown', 'not comparable'})


def unearned_eliminations(details, winner) -> list[tuple]:
    """Rivals removed only by comparisons this candidate was never held to.

    Being the last candidate standing is evidence -- it is the whole basis of the
    uniqueness acceptance route, and it is what leaves the score route with no
    runner-up to beat. But it is evidence only when the candidates were compared
    on the same terms. Where a rival was vetoed on a field and the winner is
    merely *silent* on that same field, nothing was out-argued: the rival lost
    because a vocabulary happens to name its value and not the winner's.

    The observed case is bodywork. `_body_evidence` returns unknown for a
    structure no recorded vocabulary contains -- correctly, since inventing a
    contradiction there would be a false veto. The consequence it did not
    anticipate is the mirror image: where two siblings differ only in structure
    and just one of them is named, the named one is contradicted and the unnamed
    one inherits the row. The vocabulary gap stops being a loss of evidence and
    becomes a thumb on the scale, and `tecdoc_structure` is declared partial, so
    this is a standing property of the catalogue pair rather than a rarity.

    Reported per rival, because the fields that removed one rival are not the
    fields that removed another, and a reviewer needs the specific pair.
    """
    unearned = []
    for entry in details:
        if entry['compatible'] or entry['KType'] == winner['KType']:
            continue
        fields = [field.strip() for field in str(entry['disagreements']).split(';') if field.strip()]
        # A candidate held back by a row-level source conflict rather than by any
        # field of its own says nothing about the winner either way.
        if not fields:
            continue
        if all(winner.get(field) in SILENT_VERDICTS for field in fields):
            unearned.append((entry['KType'], fields))
    return unearned


def only_identity_supports(entry) -> bool:
    """A structural code matched and not one specification agrees with it.

    An identifier match says two catalogue rows carry the same manufacturer type
    number. It does not verify that the vehicle in front of you has that type's
    specifications -- a contradiction would be vetoed, but silence is not
    agreement. Identity is worth 30 of the 75 points on a single binary fact, so
    without this check an identifier plus a production-interval overlap reaches
    the threshold with no specification agreeing at all. It corroborates
    specifications; it does not stand in for them.
    """
    return (entry['score_identity'] > 0
            and not any(entry[field] == 'agree' for field in score_rules()['field_weights']))


def _scored_outcome(details, ranking, leaders, anchors, policy, has_vin_facts,
                    source_fuel) -> Outcome:
    """Accept the score leader only once every safeguard has also passed."""
    if len(leaders) > 1:
        preference = scoped_structural_preference(details, leaders)
        if preference is None:
            return Outcome(AMBIGUOUS, None,
                           'Highest-scoring compatible candidates are tied; no arbitrary selection.',
                           TIED_CANDIDATES)
        return Outcome(AMBIGUOUS, None,
                       f"Candidates are tied on every catalogue specification. {preference['basis']}, "
                       f"indicating kType {preference['kType']}. Named for human confirmation only: "
                       'no kType is assigned and the vehicle is not counted in VIO, because a reading '
                       'scoped to one model must not decide a row on its own.',
                       SEPARABLE_ONLY_BY_SCOPED_RULE, fields='body', proposal=preference)
    winner = next(entry for entry in details if entry['KType'] == leaders[0])
    if not winner['sufficient']:
        return Outcome(INSUFFICIENT, None,
                       'Top candidate lacks the required exact capacity/fuel and additional specific evidence.',
                       EVIDENCE_FLOOR)
    if only_identity_supports(winner):
        return Outcome(INSUFFICIENT, None,
                       f"kType {winner['KType']} is supported only by a structural identifier: no "
                       'compared specification agrees with it. An identifier corroborates '
                       'specifications rather than replacing them, so this row goes to review.',
                       IDENTIFIER_WITHOUT_SPECIFICATION)
    # The second acceptance route, and the only one that reads the candidate set
    # rather than a total. A score measures how much evidence there is; it cannot
    # express that nothing else survived, which is a different and stronger fact.
    # Where one candidate stands alone and every version criterion the two
    # catalogues share agrees exactly, the evidence has discriminated as far as
    # these catalogues allow, whatever the total comes to.
    # Sufficiency depends on the vehicle/candidate evidence rather than on how
    # many unrelated siblings happen to be present in this catalogue extract.
    sole_candidate = sum(1 for entry in details if entry['compatible']) == 1
    chassis_route = winner['chassis_model_comparison'] == 'agree'
    unique_route = sole_candidate and (complete_version_evidence(winner, source_fuel)
                                       or chassis_route)
    if not ranking['score_threshold_met'] and not unique_route:
        # A lone survivor and a crowded field are different situations, and the
        # status has to say which. Where this candidate is the only one the
        # reference offers that nothing contradicts, the row is not short of
        # information about *which* candidate -- there is no rival to choose
        # against. It is short of the evidence the threshold asks for, which is a
        # statement about how much the two catalogues happen to say in common.
        sole = sum(1 for entry in details if entry['compatible']) == 1
        agreed = ', '.join(field for field in COMPARED_FIELDS if winner[field] == 'agree')
        if sole:
            return Outcome(SOLE_CANDIDATE_INCOMPLETE, None,
                           f"kType {winner['KType']} is the only candidate in the reference that nothing "
                           f'contradicts, agreeing on {agreed}, but its support score '
                           f"{ranking['top_match_score']} is below the acceptance threshold "
                           f'{policy.accept_score:g}. No kType is assigned and the vehicle is not counted '
                           'in VIO. Nothing needs reconciling before a reviewer can judge it: the fields '
                           'that would raise the score are absent, not in conflict.',
                           BELOW_THRESHOLD)
        return Outcome(INSUFFICIENT, None,
                       f"Top score {ranking['top_match_score']} is below acceptance threshold "
                       f'{policy.accept_score:g}.',
                       BELOW_THRESHOLD)
    if not ranking['score_margin_met'] and not unique_route:
        return Outcome(AMBIGUOUS, None,
                       f"Top score margin {ranking['score_margin']} is below required margin "
                       f'{policy.min_margin:g}.',
                       NARROW_MARGIN)
    if anchors.has_identifiers and winner['KType'] not in anchors.anchored:
        return Outcome(CONFLICT, None,
                       'Score leader is not consistent with the specific structural identifiers.',
                       IDENTIFIER_VS_SPECIFICATION)
    unearned = unearned_eliminations(details, winner)
    if unearned:
        return _unearned_outcome(details, winner, unearned)
    if ranking['score_threshold_met']:
        margin_text = ('no compatible runner-up' if ranking['score_margin'] is None else
                       f"margin {ranking['score_margin']} >= {policy.min_margin:g}")
        route = ACCEPTED_ON_SCORE
        reason = (f"Support score {winner['match_score']} >= {policy.accept_score:g}; {margin_text}. "
                  'Required evidence and contradiction checks passed; score is not a probability.')
    elif chassis_route:
        route = ACCEPTED_ON_UNIQUENESS
        reason = (f"kType {winner['KType']} is the only compatible candidate after the documented "
                  f"manufacturer model code {winner['chassis_model_code']} decoded from "
                  f"{winner['chassis_model_source_field']} agreed with "
                  f"reference Type_design {winner['chassis_model_reference_codes']}. "
                  'The manufacturer-code comparison takes priority over missing specification '
                  'evidence; every known contradiction still vetoes a candidate.')
    else:
        route = ACCEPTED_ON_UNIQUENESS
        reason = (f"kType {winner['KType']} is the only candidate in the reference that nothing "
                  'contradicts, and every version-defining criterion the two catalogues share '
                  'agrees exactly: capacity, fuel and power. Accepted on that basis rather than on '
                  f"the support score, which is {winner['match_score']} against a threshold of "
                  f'{policy.accept_score:g}. Regulation (EU) 2018/858 Annex I 1.3.1 makes those '
                  'three the criteria that individuate a version; the two it also names, laden '
                  'mass and seating positions, are absent from the reference extract, so no '
                  'further version evidence exists to require.')
    if has_vin_facts:
        reason += ' Documented VIN evidence applied; see vin_helper_facts and Candidate_Evidence.'
    return Outcome(MATCHED, winner['KType'], reason, '', route=route)


def _dominance_outcome(details, anchors, has_vin_facts) -> Outcome:
    """Accept the candidate no rival out-agrees, on the criteria themselves.

    The weightless counterpart to `_scored_outcome`, reached only once the row
    and its identifiers are coherent and at least one candidate has survived
    every veto. It reads no weight, no cap, no threshold and no margin: a winner
    must be the only compatible candidate and its criterion set must clear
    `dominance.sufficient`.

    The safeguards that are not weighting artefacts are kept in the same order
    the score route applies them, because each constrains something other than
    how much evidence there is: identifiers must still not point elsewhere, and
    a rival must not have fallen only on a comparison the winner escaped.
    """
    pool = [entry for entry in details if entry['compatible']]
    # A strict agreement-set superset is not identity evidence when its sibling
    # merely has a missing value. More complete catalogue rows cannot defeat
    # still-compatible rivals. No cross-catalogue identifier correspondence in
    # this prototype is backed by an official source that establishes uniqueness,
    # so identifiers corroborate a sole compatible candidate but never remove a
    # still-compatible sibling.
    winners = [entry['KType'] for entry in pool]
    if len(winners) > 1:
        preference = scoped_structural_preference(details, winners)
        if preference is None:
            return Outcome(AMBIGUOUS, None,
                           f'{len(winners)} compatible candidates remain: kTypes '
                           + '; '.join(map(str, winners))
                           + '. Differences caused only by missing or additional positive '
                           'evidence do not establish identity. No official source supplied with '
                           'this project establishes that a cross-catalogue identifier match is '
                           'unique, so it cannot remove a still-compatible sibling.',
                           NOT_SEPARATED, tied=winners)
        return Outcome(AMBIGUOUS, None,
                       f"Candidates are tied on every catalogue specification. {preference['basis']}, "
                       f"indicating kType {preference['kType']}. Named for human confirmation only: "
                       'no kType is assigned and the vehicle is not counted in VIO, because a reading '
                       'scoped to one model must not decide a row on its own.',
                       SEPARABLE_ONLY_BY_SCOPED_RULE, fields='body', proposal=preference,
                       tied=winners)
    winner = next(entry for entry in details if entry['KType'] == winners[0])
    enough = winner['criterion_sufficient']
    shortfall = winner['criterion_shortfall']
    open_fields = tuple(name for name in winner['criterion_open_fields'].split('; ') if name)
    if not enough:
        # A lone survivor and a crowded field are different situations and the
        # status has to say which -- the same distinction the score route draws,
        # for the same reason. Where this is the only candidate nothing
        # contradicts, the row is not short of information about *which*
        # candidate; there is no rival to choose against. It is short of the
        # evidence acceptance requires, and the fields that would supply it are
        # absent rather than in conflict, so nothing needs reconciling before a
        # reviewer can judge it.
        return Outcome(SOLE_CANDIDATE_INCOMPLETE if len(pool) == 1 else INSUFFICIENT, None,
                       f"kType {winner['KType']} is the candidate no rival out-agrees "
                       f"({criterion_vector(winner)}), but that is not enough to assign it: "
                       f'{shortfall}. Every version-defining criterion the two catalogues can '
                       'compare must agree, and at least one variant criterion with it.',
                       CRITERION_SET,
                       # Only the criteria that were asked and went unanswered:
                       # naming capacity on a vehicle that has none to compare
                       # sends a reviewer after a field nothing can fix.
                       fields='; '.join(open_fields))
    if anchors.has_identifiers and winner['KType'] not in anchors.anchored:
        return Outcome(CONFLICT, None,
                       'The dominant candidate is not consistent with the specific structural identifiers.',
                       IDENTIFIER_VS_SPECIFICATION)
    unearned = unearned_eliminations(details, winner)
    if unearned:
        return _unearned_outcome(details, winner, unearned)
    if winner['chassis_model_comparison'] == 'agree':
        reason = (f"kType {winner['KType']} is the only compatible candidate after the documented "
                  f"manufacturer model code {winner['chassis_model_code']} decoded from "
                  f"{winner['chassis_model_source_field']} agreed with "
                  f"reference Type_design {winner['chassis_model_reference_codes']}, out of "
                  f'{len(details)} candidates compared and {len(pool)} uncontradicted. The code '
                  'comparison takes priority over missing criterion evidence; all explicit '
                  'contradiction checks still apply.')
    else:
        reason = (f"kType {winner['KType']} is the only compatible candidate supported after "
                  f'explicit contradiction checks: {criterion_vector(winner)} '
                  f"({winner['version_criteria_agreed'] or 'none'}; "
                  f"{winner['variant_criteria_agreed'] or 'none'}), out of {len(details)} candidates "
                  f'compared and {len(pool)} uncontradicted. Nothing is summed and no threshold is '
                  'applied. Agreement sets and sufficiency guards are provisional engineering rules '
                  'informed by Annex I attribute groups; they do not establish verified identity.')
    if has_vin_facts:
        reason += ' Documented VIN evidence applied; see vin_helper_facts and Candidate_Evidence.'
    return Outcome(MATCHED, winner['KType'], reason, '', route=ACCEPTED_ON_DOMINANCE)


def _unearned_outcome(details, winner, unearned) -> Outcome:
    """The row a survivor won only on comparisons it was never entered in.

    Shared by both selectors verbatim. The guard constrains what "nothing else
    survived" is allowed to mean, which is orthogonal to how a winner is chosen:
    a total and a criterion set both lean on the elimination of rivals, and both
    are entitled to lean on it only where the rival lost a contest this candidate
    also entered.
    """
    blocking = sorted({field for _, fields in unearned for field in fields})
    rival, fields = unearned[0]
    return Outcome(INSUFFICIENT, None,
                   f"kType {winner['KType']} is the last candidate standing, but kType {rival} "
                   f"fell only on {', '.join(fields)} -- a comparison this candidate was never "
                   'held to, because its own value there is one no recorded vocabulary names, '
                   'so the comparison returned unknown rather than agreement. Surviving a '
                   'contest the rival was entered in and this candidate was not is no evidence '
                   'of being right, so no kType is assigned and the vehicle is not counted in '
                   'VIO. The reference owner can close it by naming the missing value.',
                   UNEARNED_ELIMINATION, fields='; '.join(blocking),
                   fields_scope=f'{len(unearned)} of {sum(1 for e in details if not e["compatible"])}'
                                ' contradicted candidates')


def _rules_only_outcome(details, compatible: set, anchors) -> tuple[Outcome, set]:
    """The pre-scoring policy: accept only a unique compatible candidate.

    Retained as an explicit sensitivity setting, so the contribution of scoring
    can be measured rather than assumed. Unlike the scored path this narrows the
    surviving candidate set, so the narrowed set is returned with the outcome.
    """
    remaining = compatible & anchors.anchored if anchors.has_identifiers else set(compatible)
    if len(remaining) > 1:
        return Outcome(AMBIGUOUS, None,
                       'Multiple compatible candidates remain; reference order is not a tie-breaker.',
                       TIED_CANDIDATES), remaining
    if len(remaining) != 1:
        return Outcome(), remaining
    winner = next(entry for entry in details if entry['KType'] in remaining)
    if not winner['sufficient']:
        return Outcome(), remaining
    agreements = ', '.join(field for field in COMPARED_FIELDS if winner[field] == 'agree')
    reason = f'Unique compatible candidate with exact evidence: {agreements}.'
    if anchors.has_identifiers:
        reason += ' Specific structural evidence is consistent (dataset-derived rules).'
    return Outcome(MATCHED, winner['KType'], reason, ''), remaining


def assumptions_used(winner) -> list[str]:
    """Which documented assumptions contributed to this acceptance, in report order.

    Every entry names an assumption from the README rather than a measurement, so
    a reviewer can see what an acceptance rests on without re-deriving it. Read
    this as *contributed*, not as *was individually necessary*: a row can list an
    assumption it would still be accepted without, because another route to the
    evidence floor also passes. Necessity requires a separate ablation run that
    disables each mechanism and compares the outcomes.

    This is reporting only. Nothing here feeds back into whether a row was
    accepted, and the column is absent on every row that was not.
    """
    dependencies = []
    if winner['power'] == 'near (not exact evidence)':
        dependencies.append('power tolerance')
    if winner['vin_generation'] != 'unknown' or winner['vin_drive'] != 'unknown' or winner['vin_engine'] != 'unknown':
        dependencies.append('sourced VIN evidence')
    if winner['chassis_model_comparison'] == 'agree':
        dependencies.append('manufacturer chassis model code')
    if any(winner[f'{name}_tokens'] for name in identifiers_where('authoritative')):
        dependencies.append('structural identifier')
    if winner['explicit_engine_comparison'] == 'agree':
        dependencies.append('scoped engine-code format')
    return dependencies


def _display_value(value, unit: str = '') -> str:
    """One cell as a reviewer should read it: no NaN, no trailing .0 on integers."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return 'missing'
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return f'{text} {unit}'.strip() if text else 'missing'


def differentiating_fields(details, ktypes) -> str:
    """The reference columns on which the named candidates differ, with values.

    Describes; never decides. When candidates tie, the row stops with a list of
    kTypes and no statement of what separates them, so a reviewer re-derives it
    by hand from the reference workbook -- for COLORADO, that two otherwise
    identical candidates are a Platform/Chassis and a Pickup. That derivation is
    mechanical and asserts nothing, so the algorithm can do it.

    What it must not do is pair either value with the source row's own body
    field. `UTILITY` -> `Pickup` is a correspondence no publisher states, and
    asserting it here would silently decide the row. The reference values are
    quoted as they stand; the judgement stays with the reviewer.
    """
    named = [entry for entry in details if entry['KType'] in set(ktypes)]
    if len(named) < 2:
        return ''
    parts = []
    for reference_column in EXPORTED_REFERENCE_COLUMNS:
        key = f'reference_{reference_column}'
        values = [_display_value(entry[key]) for entry in named]
        if len(set(values)) < 2:
            continue
        pairs = ', '.join(f"{entry['KType']}={value}" for entry, value in zip(named, values))
        parts.append(f'{reference_column}: {pairs}')
    return '; '.join(parts)


def _values_focus(details, lead) -> int | None:
    """Which candidate's values :func:`blocking_values` should quote.

    The triage lead where there is one. Otherwise a lone near-power candidate,
    because the spread that would be printed instead hides exactly the fact the
    row turns on: quoting ``reference 84-206 kW across 27 candidates`` for a row
    whose closest candidate reads 126 kW against the register's 125 kW tells a
    reviewer nothing. With several such candidates the spread is kept -- naming
    one of them would suggest a preference between them that nothing here has
    earned.
    """
    if lead is not None and lead['kType'] is not None:
        return lead['kType']
    near_power = near_power_candidates(details)
    return near_power[0] if len(near_power) == 1 else None


def blocking_values(row, details, fields: str, focus: int | None = None) -> str:
    """The source and reference values behind each field that stopped the row.

    Naming `power` tells a reviewer where to look; stating `source 125 kW,
    reference 126 kW` tells them what to rule on, and is the difference between
    a status they can act on and one they have to investigate. Both numbers are
    quoted from the two catalogues exactly as recorded.

    Where the row already names a candidate for triage, that candidate's values
    are the ones quoted -- it is the one the reviewer will look at first, and
    enumerating the other thirty helps nobody. With no named candidate the field
    is summarised across the contradicted candidates as a range, which says
    whether the row sits just outside the catalogue's spread or nowhere near it.
    """
    contradicted = [entry for entry in details if not entry['compatible']]
    parts = []
    for field in (name for name in fields.split('; ') if name):
        spec = FIELD_VALUE_SOURCES.get(field)
        if spec is None:
            continue
        unit, key = spec['unit'], f"reference_{spec['reference']}"
        source = (_display_value(source_field(row, spec['source_role']), unit)
                  if spec['source_role'] else 'parsed from free text')
        named = next((entry for entry in contradicted if entry['KType'] == focus), None)
        if named is not None:
            reference = f"{_display_value(named[key], unit)} (kType {named['KType']})"
        else:
            blocked_on = [entry for entry in contradicted
                          if field in {core_conflict(name)
                                       for name in entry['disagreements'].split('; ') if name}]
            reference = _value_spread([entry[key] for entry in (blocked_on or contradicted)], unit)
        parts.append(f'{field}: source {source}, reference {reference}')
    return '; '.join(parts)


def _value_spread(values, unit: str) -> str:
    """A field's reference values as a range where numeric, else as a short list."""
    numeric = [numeric_value(value) for value in values]
    usable = [number for number in numeric if number is not None]
    if usable and len(usable) == len(numeric):
        low, high = min(usable), max(usable)
        span = (_display_value(low, unit) if low == high
                else f'{_display_value(low)}-{_display_value(high, unit)}')
        return f'{span} across {len(numeric)} candidates'
    distinct = sorted({_display_value(value, unit) for value in values})
    shown = '; '.join(distinct[:4]) + (f' (+{len(distinct) - 4} more)' if len(distinct) > 4 else '')
    return f'{shown} across {len(values)} candidates'


def _evidence_notes(row) -> str:
    """Source fields that were unusable, so a reviewer can see what was missing."""
    issues = []
    if model_year(source_field(row, 'year')) is None:
        issues.append(f"{column('year')} missing/invalid: no temporal points")
    for role in ('displacement', 'power'):
        if column(role) and numeric_value(source_field(row, role)) is None:
            issues.append(f'{column(role)} missing/zero/invalid')
    for name in ((column('fuel'),) if column('fuel') else ()) + identifiers():
        if not normalized_text(row.get(name)):
            issues.append(f'{name} unavailable')
    return '; '.join(issues)


def decide(row, candidates, policy, *, include_score_diagnostics: bool = True) -> tuple[dict, list[dict]]:
    """Compare a row with every candidate and resolve it to one outcome."""
    parsed_submodel = submodel_context(row)
    decoded_vin = vin_context(vin_value(row), normalized_text(source_field(row, 'make')),
                              normalized_text(source_field(row, 'model')),
                              enabled=policy.use_identifiers and policy.use_vin_helper)
    cross_field_vin_conflicts(row, decoded_vin)
    details = _compare_all_candidates(row, candidates, policy, decoded_vin, parsed_submodel,
                                      include_score_diagnostics)
    compatible = {entry['KType'] for entry in details if entry['compatible']}
    anchors = anchor_state(row, details, policy)
    remaining = compatible.copy()
    ranking = None
    leaders = []

    outcome = (_source_conflict_outcome(row, decoded_vin, parsed_submodel, anchors)
               or _identifier_versus_specification_outcome(details, compatible, anchors)
               or _candidate_availability_outcome(details, compatible, anchors, policy)
               or _compatible_model_code_hint_outcome(details, compatible))
    candidate_ids = sorted(compatible)
    if outcome is None:
        if not policy.use_scoring:
            # The rule-only policy predates both selectors and is unaffected by
            # the choice between them: it accepts a unique compatible candidate
            # and consults neither a total nor a criterion set.
            outcome, remaining = _rules_only_outcome(details, compatible, anchors)
            candidate_ids = sorted(remaining)
        elif policy.selection == 'dominance':
            outcome = _dominance_outcome(details, anchors, bool(decoded_vin['facts']))
        else:
            ranking, leaders = _score_diagnostics(details, policy)
            outcome = _scored_outcome(details, ranking, leaders, anchors, policy,
                                      bool(decoded_vin['facts']),
                                      normalized_text(source_field(row, 'fuel')))
    # The default dominance decision above is complete before diagnostics are
    # calculated. Callers may request scores for reference comparisons, but they
    # cannot select a default winner or shape its reason.
    if ranking is None and include_score_diagnostics:
        ranking, leaders = _score_diagnostics(details, policy)
    for entry in details:
        entry['remaining_candidate'] = entry['KType'] in remaining
        entry['selected'] = entry['KType'] == outcome.selected

    proposal = outcome.proposal
    lead = outcome.lead
    add_review_similarity(row, details, unresolved=outcome.status != MATCHED)
    order_review_candidates(
        details,
        selected=outcome.selected,
        proposed=proposal['kType'] if proposal else None,
        lead=lead['kType'] if lead else None,
        shortlist=set(lead['alternatives']) if lead else set(),
        remaining=set(candidate_ids),
        unresolved=outcome.status != MATCHED,
    )
    result = {'mapped kType': outcome.selected, 'Match_Status': outcome.status,
              'Match_Reason': outcome.reason, 'Review_Category': outcome.category,
              'acceptance_route': outcome.route,
              'Review_Fields': outcome.fields,
              'Review_Fields_scope': outcome.fields_scope,
              # Descriptive only. Neither column feeds any acceptance decision:
              # they state what the reference rows say, so a reviewer is handed
              # the values their judgement is being deferred to instead of a
              # field name and a workbook to go and open.
              'differentiating_fields': differentiating_fields(
                  details, outcome.tied if outcome.tied is not None else leaders)
                                        if outcome.status == AMBIGUOUS else '',
              'blocking_values': blocking_values(row, details, outcome.fields,
                                                 _values_focus(details, lead))
                                 if outcome.status == ALL_CANDIDATES_CONTRADICTED else '',
              'proposed_kType': proposal['kType'] if proposal else None,
              'proposal_basis': proposal['basis'] if proposal else '',
              'proposal_conflicting_fields': '; '.join(proposal['conflicts']) if proposal else '',
              # Deliberately separate from the proposal columns above. A proposal
              # rests on agreeing structural identifiers; a lead rests only on a
              # candidate being one field short. Merging them would let the
              # weaker claim inherit the stronger one's standing.
              'triage_lead_kType': lead['kType'] if lead else None,
              'triage_lead_blocking_field': lead['field'] if lead else '',
              'triage_lead_basis': lead['basis'] if lead else '',
              'triage_lead_alternatives': '; '.join(map(str, lead['alternatives'])) if lead else '',
              # Which selector produced the outcome above. Recorded per row
              # rather than only in the run metadata, because a workbook outlives
              # the command that made it and an acceptance has to be able to say
              # what it was decided by.
              'selection_rule': policy.selection,
              **(ranking or {}), **identifier_context(row), **chassis_audit_columns(row),
              **vin_audit_columns(decoded_vin),
              **submodel_audit_columns(parsed_submodel),
              'base_candidate_count': len(details),
              'compatible_candidate_count': len(compatible),
              'remaining_kTypes': '; '.join(map(str, candidate_ids)),
              'identifier_kTypes': '; '.join(map(str, sorted(
                  set.union(*anchors.populated) if anchors.populated else set()))),
              'parsed_identifiers': json.dumps(
                  {field: sorted(codes) for field, codes in anchors.codes.items() if codes},
                  sort_keys=True),
              **_selected_candidate_columns(details),
              'evidence_notes': _evidence_notes(row)}
    return result, details


def _compare_all_candidates(row, candidates, policy, decoded_vin, parsed_submodel,
                            include_score_diagnostics: bool) -> list[dict]:
    """Decision evidence and reference context for every candidate."""
    details = []
    for _, candidate in candidates.iterrows():
        evidence = candidate_evidence(row, candidate, policy, decoded_vin, parsed_submodel)
        details.append({'source_key': row['source_key'], 'ID': row[column('id')],
                        'KType': int(candidate['KType']), **evidence,
                        # Optional diagnostic columns are populated only when requested.
                        **(dict.fromkeys(SCORE_COLUMNS) if include_score_diagnostics else {}),
                        # Descriptive under either selector: which Annex I
                        # criteria agreed, and which could be compared at all.
                        **criterion_columns(evidence),
                        **{f'reference_{column}': candidate.get(column, pd.NA)
                           for column in EXPORTED_REFERENCE_COLUMNS}})
    for entry in details:
        enough, shortfall, open_fields = sufficient(entry)
        entry.update({'criterion_sufficient': enough,
                      'criterion_shortfall': shortfall,
                      'criterion_open_fields': '; '.join(open_fields)})
    return details


def _score_diagnostics(details, policy):
    """Populate optional support diagnostics and summarize their ranking."""
    for entry in details:
        entry.update(score_candidate(entry))
    return rank_candidates(details, policy)


def _selected_candidate_columns(details) -> dict:
    """Lift the accepted candidate's caveats onto the row, for review triage."""
    selected = next((entry for entry in details if entry['selected']), None)
    assumptions = assumptions_used(selected) if selected else []
    # Record what the accepted candidate agreed with and what was comparable.
    criteria = {name: (selected[name] if selected else '')
                for name in ('version_criteria_agreed', 'variant_criteria_agreed',
                             'version_criteria_comparable', 'criterion_vector')}
    return {**{f'selected_{name}': value for name, value in criteria.items()},
            'assumptions_used': '; '.join(assumptions),
            'assumption_count': len(assumptions),
            'selected_year_relationship': selected['year_relationship'] if selected else '',
            'selected_power_tolerance_used': bool(selected) and selected['power'] == 'near (not exact evidence)',
            'selected_power_difference_kw': selected['power_difference_kw'] if selected else None,
            'selected_registration_after_end_years': selected['registration_after_end_years'] if selected else None,
            'selected_construction_to': selected['reference_Construction_to'] if selected else None}
