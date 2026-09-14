"""Comparing one source row with one reference candidate.

Every comparison is three-valued -- agree, disagree or unknown -- and unknown is
the default. Support can only come from evidence that is actually present, and a
single disagreement on an independent specification vetoes the candidate no
matter how much else agrees.
"""
from __future__ import annotations

import re

import pandas as pd

from . import submodel as submodel_rules_module
from .config import (authority_assigned_prefix, authority_assigned_vin_prefixes,
                     known_reference_structures,
                     DISPLACEMENTLESS_FUELS, column, identifiers, identifiers_of_kind,
                     source_field,
                     identifiers_where, vin_column, vin_value,
                     VETO_FIELDS, vocabularies)
from .normalization import (code_tokens, compact_code, compare_values, displacement_cc,
                            catalogue_fuel_category, mercedes_variant, model_year,
                            normalized_text, numeric_value, reference_drive_category,
                            registry_fuel_category, submodel_drive_category)
from .vin_evidence import candidate_vin_evidence, vin_context

# Mercedes writes M/OM prefixes on engine families that the source omits.
MERCEDES_ENGINE_PREFIX = re.compile(r'^(OM|M)')
# Scoped, dataset-derived Hyundai format: a four-character G/D-series code at the
# start of the engine number, terminated by a separator or the end of the field.
# Declared once because both the comparison below and the decision key derive
# the engine serial away through it; if the two disagreed, two rows could share
# a decision key while the algorithm treated them differently.
HYUNDAI_ENGINE_CODE = re.compile(r'^([GD][34][A-Z]{2})(?:[A-Z0-9]|[- /]|$)')
COMPLETE_HYUNDAI_CODE = re.compile(r'[GD][34][A-Z]{2}')
# Mercedes VIN positions 4-9 and the MVMA six-digit prefix. Deliberately not an
# unrestricted search of arbitrary VIN substrings.
MERCEDES_VIN = re.compile(r'(?:WDD|W1K)[0-9]{6}[A-Z0-9]{2}')
MERCEDES_MVMA_PREFIX = re.compile(r'^(\d{6})')
MINIMUM_CODE_LENGTH = 4


def reference_codes(value) -> list[str]:
    """Split a semicolon-delimited reference code field into its entries."""
    return normalized_text(value).split(';')


def scoped_engine_code(row) -> str | None:
    """The complete engine code the source engine number states, if any.

    Hyundai source numbers contain four-character G/D-series prefixes matching
    the reference's complete codes. The prefix is parsed independently of which
    candidates are present, so deleting G4NH from the reference cannot turn a
    G4NH-versus-G4NS contradiction into 'unknown'. Every other make and every
    unrecognized format stays None: no alias or engine specification is inferred.
    """
    if normalized_text(source_field(row, 'make')) != 'HYUNDAI':
        return None
    match = HYUNDAI_ENGINE_CODE.match(normalized_text(source_field(row, 'engine_number')))
    return match.group(1) if match else None


def engine_number_carries(row, tokens) -> set[str]:
    """Which of ``tokens`` the engine number states, as a prefix or a token.

    Both paths matter: MR20-RM31-727508C carries RM31 only as a delimited token,
    and that is worth ten points. Positive evidence only -- an unrecognized
    format is unknown, never a mismatch.
    """
    compacted = compact_code(source_field(row, 'engine_number'))
    delimited = set(code_tokens(source_field(row, 'engine_number')))
    return {token for token in tokens if compacted.startswith(token) or token in delimited}


def matching_engine_codes(row, candidate, make: str) -> list[str]:
    """Reference engine codes that this row's engine number states, in order."""
    comparable = {}
    for code in reference_codes(candidate.get('Engine_code')):
        token = compact_code(code)
        if make == 'MERCEDES-BENZ':
            token = MERCEDES_ENGINE_PREFIX.sub('', token)
        if len(token) >= MINIMUM_CODE_LENGTH:
            comparable[code] = token
    carried = engine_number_carries(row, set(comparable.values()))
    # Reference order, not set order, so the exported text is reproducible.
    return [code.strip() for code, token in comparable.items() if token in carried]


def explicit_engine_comparison(row, candidate) -> dict:
    """Compare complete engine codes, where both sides state one.

    Both sides must be complete for a disagreement to mean anything, so the
    reference codes are only used when every one of them is a full code.
    """
    source_code = scoped_engine_code(row)
    codes = {code.strip() for code in reference_codes(candidate.get('Engine_code')) if code.strip()}
    complete = bool(codes) and all(COMPLETE_HYUNDAI_CODE.fullmatch(code) for code in codes)
    comparison = ('unknown' if source_code is None or not complete else
                  'agree' if source_code in codes else 'disagree')
    return {'source_engine_code': source_code,
            'explicit_engine_comparison': comparison,
            'engine_comparison_basis': ('Hyundai four-character prefix; dataset-derived format'
                                        if source_code else 'No scoped complete-code extraction')}


def identifier_context(row) -> dict:
    """Explain existing import fields, without inferring a factory code from 7AT.

    Previous registration in Japan corroborates import context. It neither proves
    why a particular VIN was assigned nor identifies a variant by itself.
    """
    context_values = vocabularies()['import_context']
    vin = compact_code(vin_value(row))
    prefix = authority_assigned_prefix(vin)
    corroborating = context_values.get('corroborating_previous_country')
    adjective = context_values.get('corroborating_previous_country_adjective', '')
    previous = normalized_text(source_field(row, 'previous_country'))
    matched_country = bool(corroborating) and previous == normalized_text(corroborating)
    used = normalized_text(source_field(row, 'import_status')) == normalized_text(
        context_values.get('used_import_status', ''))
    used = used and bool(context_values.get('used_import_status'))
    country_column = column('previous_country') or 'previous country'
    if prefix:
        note = f'{prefix} assigned VIN: not decoded as manufacturer variant or production year.'
        note += (f' {country_column}={corroborating} corroborates {adjective} import context.'
                 if matched_country else
                 f' {adjective} prior registration is not established by {country_column}.'
                 if corroborating else '')
    else:
        note = 'Only the documented manufacturer-specific code patterns are interpreted.'
    authority = authority_assigned_vin_prefixes().get(prefix, '') if prefix else ''
    origin = (f'{authority}-assigned ({prefix})'.lstrip('-') if prefix
              else 'missing' if not vin else 'manufacturer/other')
    manufacturer_code = next(iter(identifiers_of_kind('manufacturer_model_code')), None)
    return {'vin_origin': origin,
            'previously_registered_in_japan': matched_country,
            'used_japan_import': matched_country and used,
            'missing_mvma_consistent_with_import': used and manufacturer_code is not None
                                                   and not normalized_text(row.get(manufacturer_code)),
            'vin_context_note': note}


def structural_codes(row) -> dict[str, set[str]]:
    """Comparable structural codes the source row states, per identifier field."""
    codes: dict[str, set[str]] = {name: set() for name in identifiers()}
    vin_field = vin_column()
    manufacturer_code = next(iter(identifiers_of_kind('manufacturer_model_code')), None)
    if normalized_text(source_field(row, 'make')) == 'MERCEDES-BENZ':
        vin = compact_code(vin_value(row))
        if vin and not authority_assigned_prefix(vin) and MERCEDES_VIN.fullmatch(vin):
            codes[vin_field].add(vin[3:9])
        if manufacturer_code:
            match = MERCEDES_MVMA_PREFIX.match(normalized_text(row.get(manufacturer_code)))
            if match:
                codes[manufacturer_code].add(match.group(1))
    # Delimited chassis/model codes can be compared without decoding a VIN.
    for name in identifiers_of_kind('delimited_code'):
        for token in code_tokens(row.get(name)):
            if (len(token) >= MINIMUM_CODE_LENGTH
                    and re.search('[A-Z]', token) and re.search('[0-9]', token)):
                codes[name].add(token)
    return codes


def active_structural_codes(row, policy) -> dict[str, set[str]]:
    """Structural codes, or none at all when identifiers are switched off."""
    return structural_codes(row) if policy.use_identifiers else {name: set() for name in identifiers()}


def temporal_evidence(row, candidate, policy) -> dict:
    """Later than production is allowed; earlier than production needs review.

    NZTA defines VEHICLE_YEAR as "year of manufacture or model year - if unknown,
    year of first registration", and no field says which of the three a given row
    carries. The asymmetric treatment follows from that ambiguity:

    A year before production start is impossible under all three readings, so it
    blocks automatic acceptance. A year after production end is a contradiction
    under the first two readings but legitimate under the third, since unsold
    stock can be first registered years after it was built; it therefore stays
    eligible and the lag is exported for review rather than vetoed. Candidates
    remain in the audit trail either way. Unknown years are neutral, and no
    registration-delay cutoff is invented.
    """
    registered = model_year(source_field(row, 'year'))
    start = int(candidate['_from'])
    end = None if pd.isna(candidate['_to']) else int(candidate['_to'])
    lag = None
    if registered is None:
        relation = 'unknown registration year'
    elif registered < start:
        relation = 'registration before production start: review chronology'
    elif end is not None and registered > end:
        relation = 'registration after production end: production date unknown'
        lag = registered - end
    else:
        relation = 'registration year overlaps production interval'
    overlaps = registered is not None and registered >= start and (end is None or registered <= end)
    return {'year_relationship': relation,
            'registration_after_end_years': lag,
            'chronology': ('disagree' if registered is not None and registered < start
                           else 'unknown' if registered is None else 'not contradicted'),
            'year_interval_overlap': overlaps,
            'temporal_points': policy.year_weight if overlaps else 0}


def candidate_evidence(row, candidate, policy, decoded_vin=None, parsed_submodel=None) -> dict:
    """Every comparison between one source row and one candidate kType."""
    if parsed_submodel is None:
        parsed_submodel = submodel_rules_module.source_context(row)
    if decoded_vin is None:
        decoded_vin = vin_context(vin_value(row), normalized_text(source_field(row, 'make')),
                                  normalized_text(source_field(row, 'model')),
                                  enabled=policy.use_identifiers and policy.use_vin_helper)
    make = normalized_text(source_field(row, 'make'))
    source_drive = submodel_drive_category(source_field(row, 'submodel'))
    evidence = {'capacity': compare_values(displacement_cc(source_field(row, 'displacement')),
                                           displacement_cc(candidate.get('Capacity_cubic'))),
                **temporal_evidence(row, candidate, policy)}
    source_fuel = registry_fuel_category(source_field(row, 'fuel'))
    evidence['fuel'] = compare_values(source_fuel,
                                      catalogue_fuel_category(candidate.get('Fuel_type')))
    evidence.update(_power_evidence(row, candidate, policy))
    evidence['drive'] = _drive_evidence(source_drive, candidate)
    evidence['body'] = _body_evidence(row, candidate)
    evidence['variant'] = (compare_values(mercedes_variant(source_field(row, 'submodel')),
                                          mercedes_variant(candidate.get('Type_designation')))
                           if make == 'MERCEDES-BENZ' else 'not comparable')
    matched_engines = matching_engine_codes(row, candidate, make)
    evidence['engine'] = 'agree' if matched_engines else 'unknown'
    evidence['engine_tokens'] = '; '.join(matched_engines)
    evidence.update(explicit_engine_comparison(row, candidate))
    if evidence['explicit_engine_comparison'] != 'unknown':
        evidence['engine'] = evidence['explicit_engine_comparison']
    evidence.update(candidate_vin_evidence(decoded_vin, candidate))
    # A decoded specification fills or confirms the SAME score component, never
    # an additional identity bonus. Both sources must remain compatible.
    for field in ('drive', 'engine'):
        if evidence[f'vin_{field}'] == 'agree' and evidence[field] == 'unknown':
            evidence[field] = 'agree'
    evidence.update(_identifier_evidence(row, candidate, policy))
    evidence['family_context_only'] = _family_context(row, candidate)
    evidence.update(submodel_rules_module.candidate_checks(parsed_submodel, candidate))
    # SUBMODEL consistency adds no points and never fills missing exact capacity
    # or fuel. Its contradictions are vetoes; drive/variant use existing scores.
    evidence['disagreements'] = '; '.join(field for field in VETO_FIELDS
                                          if evidence[field] == 'disagree')
    evidence['compatible'] = (not evidence['disagreements']
                              and source_drive != 'conflict'
                              and not decoded_vin['source_conflicts']
                              and not parsed_submodel['source_conflicts'])
    evidence['evidence_floor'] = _evidence_floor_route(evidence, source_fuel)
    evidence['sufficient'] = bool(evidence['evidence_floor'])
    evidence['transmission'] = 'not comparable: no reference transmission field'
    return evidence


def _power_evidence(row, candidate, policy) -> dict:
    """Exact kW agreement, with a near-miss recorded but never rewarded.

    The tolerance band is a percentage of the *reference* figure, because the
    reference carries the manufacturer's type-approval value and UN ECE R85
    frames its allowance as a deviation from that approval figure. A difference
    inside the band is neutral: it neither contradicts the candidate nor counts
    as exact agreement, and every dependent acceptance is flagged per row.

    ``power_within_triage_band`` is a separate and much weaker observation, and
    it is reporting only. It says the gap is small enough to be explained by the
    two catalogues rounding the same underlying figure to integer kW, nothing
    more. It never touches the verdict, so a candidate it marks stays
    contradicted, unscored and unacceptable; decision.triage_lead reads it only
    to tell a reviewer which rejected candidate to look at first.
    """
    power = numeric_value(source_field(row, 'power'))
    reference_power = numeric_value(candidate.get('Maximum_output_KW'))
    if power is None or reference_power is None:
        return {'power_difference_kw': None, 'power_difference_pct': None,
                'power_within_triage_band': False,
                'power': compare_values(power, reference_power)}
    difference = power - reference_power
    percentage = abs(difference) / reference_power * 100
    verdict = compare_values(power, reference_power)
    if difference != 0 and percentage <= policy.power_tolerance_pct:
        verdict = 'near (not exact evidence)'
    return {'power_difference_kw': difference,
            'power_difference_pct': round(percentage, 2),
            'power_within_triage_band': 0 < abs(difference) <= policy.power_triage_kw,
            'power': verdict}


def _drive_evidence(drive, candidate) -> str:
    """Compare drive categories, both sides named by the reference catalogue.

    There is no two-wheel-drive branch. A submodel reading '2WD' used to agree
    with Front- and Rear-Wheel Drive and contradict All-wheel Drive, but TecDoc
    KT 082 defines no two-wheel-drive value, so neither half of that could be
    grounded in any source this project cites. '2WD' is now simply a token the
    vocabulary does not record, and an unrecorded token yields no category.
    """
    if drive == 'conflict':
        return 'source conflict'
    return compare_values(drive, reference_drive_category(candidate.get('Drive_system')))


def _body_evidence(row, candidate) -> str:
    """One registration-body taxonomy, shared with the SUBMODEL checks.

    Absence from the permitted set means two different things, and only one of
    them is a contradiction. Where the structure is one this project has a
    vocabulary for, its absence is a genuine disagreement: the taxonomy says
    that registration body does not cover that structure. Where the structure is
    a term no recorded vocabulary contains, nothing about it is known, and
    reporting a contradiction would state as evidence something never
    established -- a false veto, which does not merely lose a row but can
    redirect it onto a different candidate.

    Both sides map their own publisher's value into a body category, and the
    verdict compares the two categories. Neither vocabulary names the other's
    values, so each is checkable against its own publisher.

    The vocabulary judged against is itself incomplete -- see tecdoc_structure,
    marked partial -- so the unknown branch is expected to be taken often. That
    is the honest outcome: unknown earns no points and vetoes nothing, leaving
    the decision to evidence the project can actually justify.
    """
    vocabulary = vocabularies()
    category = vocabulary['registry_bodies'].get(normalized_text(source_field(row, 'body')))
    body = normalized_text(candidate.get('Kind_of_structure'))
    if category is None or not body:
        return 'unknown'
    structure = vocabulary['catalogue_structures'].get(body)
    if structure is not None:
        return 'agree' if structure == category else 'disagree'
    return 'disagree' if body in known_reference_structures() else 'unknown'


def _identifier_evidence(row, candidate, policy) -> dict:
    """Compare each identifier field with the candidate's specific type codes."""
    source_codes = active_structural_codes(row, policy)
    type_codes = {compact_code(token) for token in reference_codes(candidate.get('Type_design'))
                  if '_' not in token and len(compact_code(token)) >= MINIMUM_CODE_LENGTH}
    evidence = {}
    for name in identifiers():
        shared = source_codes[name] & type_codes
        evidence[f'{name}_tokens'] = '; '.join(sorted(shared))
        evidence[f'{name}_comparison'] = ('unknown' if not source_codes[name] or not type_codes
                                          else 'agree' if shared else 'disagree')
    return evidence


def _family_context(row, candidate) -> str:
    """Model-family fragments are audit context only: never a vote or tie-breaker."""
    hits = []
    for design in reference_codes(candidate.get('Model_design')):
        design = design.strip()
        if not design or '_' in design:
            continue
        for name in identifiers_where('manufacturer_assigned'):
            if (name in identifiers_of_kind('vin')
                    and authority_assigned_prefix(compact_code(row.get(name)))):
                continue
            if design in normalized_text(row.get(name)):
                hits.append(f'{name}:{design}')
    return '; '.join(hits)


def _evidence_floor_route(evidence, source_fuel) -> str:
    """Which acceptance route this candidate meets, or '' for none.

    Exact fuel agreement is required by every route; it is the one comparison
    that is always available and always meaningful. What must accompany it
    depends on whether the vehicle has a displacement at all.

    Vehicles with an engine take the displacement route: exact capacity, plus
    either another specific specification or a specific Type_design identifier
    -- never family text.

    Vehicles with no displacement (see DISPLACEMENTLESS_FUELS) cannot satisfy
    that, and would otherwise abstain forever however well evidenced they are.
    Their substitute route is deliberately stricter than the displacement route
    rather than looser: exact fuel, exact power AND a specific Type_design
    identifier are all three required, where the displacement route needs only
    one of the last two. A near-power match never qualifies, because it is not
    exact evidence.

    Exact power is a weaker anchor than displacement, since several variants can
    share an output -- which is exactly why the identifier is mandatory here and
    optional there. This route is not widened to make more vehicles match: if a
    reference carries no identifier for its electric kTypes, those vehicles stay
    unresolved, which is the correct outcome when nothing distinguishes them.
    """
    if evidence['fuel'] != 'agree':
        return ''
    specific_code = any(evidence[f'{name}_tokens'] for name in identifiers_where('authoritative'))
    if source_fuel in DISPLACEMENTLESS_FUELS:
        # A contradicted capacity vetoes the candidate elsewhere; it must never
        # be waved through by the route that exists because capacity is absent.
        if evidence['capacity'] == 'disagree':
            return ''
        if evidence['power'] == 'agree' and specific_code:
            return 'fuel + exact power + specific identifier (no displacement)'
        return ''
    if evidence['capacity'] != 'agree':
        return ''
    extra_specification = any(evidence[field] == 'agree'
                              for field in ('power', 'drive', 'variant', 'engine'))
    if extra_specification or specific_code:
        return 'exact capacity + fuel + specific evidence'
    return ''
