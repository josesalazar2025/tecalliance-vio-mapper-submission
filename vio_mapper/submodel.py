"""Dataset-scoped SUBMODEL parsing and consistency checks, with no score bonuses.

The NZ registration SUBMODEL is free text written by a clerk, so it is parsed
only for make/model pairs with a reviewed profile in ``registries/nz_submodel_profiles.json``.
Everything it yields is a veto or an audit note: rounded marketing litres never
replace exact CC_RATING, CVT reported steps are not assumed to be fixed gears,
and a door count is not a seat count.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from functools import lru_cache

from .config import column, source_field, submodel_rules, vocabularies
from .normalization import (displacement_cc, strict_text, submodel_drive_category,
                            MERCEDES_VARIANT_PATTERN, submodel_drive_pattern)

# Registry free text normally uses a decimal point while TecDoc's display field
# uses a decimal comma.  Accept either spelling, but store and compare a Decimal;
# punctuation is presentation, not vehicle evidence.
CAPACITY_PATTERN = re.compile(r'(?<![A-Z0-9.,])(\d{1,2}[.,]\d)(?:([PD])\b|(?=$|[ /]))')
TRANSMISSION_PATTERN = re.compile(r'\b(?:(\d{1,2}))?(CVT|AT|MT)\b')
DOOR_PATTERN = re.compile(r'\b(\d{1,2})DR\b')
WORD_PATTERN = re.compile(r'\b[A-Z]+\b')
GEAR_COUNT_PATTERN = re.compile(r'\b(\d{1,2})[- ]GEAR\b')
RESIDUAL_TOKEN_PATTERN = re.compile(r'[A-Z0-9]+(?:\.[0-9]+)?')
TRANSMISSION_KINDS = {'CVT': 'cvt', 'AT': 'automatic', 'MT': 'manual'}
FUEL_LETTERS = {'P': 'petrol', 'D': 'diesel'}
NOT_COMPARABLE = {
    'submodel_transmission': 'not comparable: no reference transmission field',
    'submodel_doors': 'not comparable: no reference door field',
    'submodel_trim': 'not comparable: no reference marketing-trim field',
}


@lru_cache(maxsize=1)
def _cab_pattern() -> re.Pattern:
    """Longest-first alternation so 'DOUBLE CAB' wins over a bare 'DC'."""
    tokens = sorted(vocabularies()['cab_tokens'], key=len, reverse=True)
    return re.compile(r'\b(?:' + '|'.join(tokens).replace(' ', r'\s+') + r')\b')


def core_field(key: str) -> str:
    """The specification a SUBMODEL fact belongs to, for review reporting."""
    return submodel_rules()['core_fields'].get(key, key)


class _FactCollector:
    """Accumulates parsed facts and records which characters they consumed.

    Tracking coverage is what lets the parser report honestly on the text it did
    *not* understand, instead of silently ignoring it.
    """

    def __init__(self) -> None:
        self.facts: dict[str, dict] = {}
        self.covered: set[int] = set()

    def add(self, key: str, value, match: re.Match) -> None:
        self.covered.update(range(match.start(), match.end()))
        fact = self.facts.setdefault(key, {'values': [], 'tokens': []})
        if value not in fact['values']:
            fact['values'].append(value)
        fact['tokens'].append(match.group())


def parse_submodel(value, make, model) -> dict:
    """Extract the facts a reviewed profile can read out of one SUBMODEL string."""
    normalized = strict_text(value)
    profile = submodel_rules()['profiles'].get((strict_text(make), strict_text(model)))
    result = {'profile': profile[0] if profile else None, 'normalized': normalized,
              'facts': {}, 'internal_conflicts': [], 'conflict_fields': [], 'unparsed_tokens': [],
              'basis': 'Dataset-scoped format rules; no external trim lookup'}
    if not profile:
        # No reviewed profile: report the text rather than interpret it.
        result['unparsed_tokens'] = normalized.split()
        return result
    profile_id, marketing_trims = profile
    collector = _FactCollector()
    _collect_facts(collector, normalized, profile_id, marketing_trims)
    result['facts'] = collector.facts
    _record_internal_conflicts(result, normalized)
    residual = ''.join(' ' if i in collector.covered else c for i, c in enumerate(normalized))
    result['unparsed_tokens'] = RESIDUAL_TOKEN_PATTERN.findall(residual)
    return result


def _collect_facts(collector: _FactCollector, normalized: str,
                   profile_id: str, marketing_trims: set[str]) -> None:
    """Read every reviewed format out of the SUBMODEL text, in one pass per rule.

    The order matches the order the formats are documented in: generic tokens
    first, then the two profile-specific spellings that also carry fuel or body
    meaning, then transmission, doors and the profile's own designations.
    """
    drives = vocabularies()['submodel_drive']
    for match in submodel_drive_pattern().finditer(normalized):
        # Source-only tokens are matched so the text is fully accounted for, but
        # they name no category and so contribute no fact to compare.
        if match.group() in drives:
            collector.add('drive_category', drives[match.group()], match)
    for match in CAPACITY_PATTERN.finditer(normalized):
        litres = Decimal(match[1].replace(',', '.'))
        if litres <= 0:
            continue
        collector.add('capacity_litres', format(litres, 'f'), match)
        if match[2]:
            collector.add('fuel_family', FUEL_LETTERS[match[2]], match)
    for match in re.finditer(r'\bHYBRID\b', normalized):
        collector.add('hybrid', True, match)
    cab_tokens = vocabularies()['cab_tokens']
    for match in _cab_pattern().finditer(normalized):
        collector.add('cab_configuration', cab_tokens[' '.join(match.group().split())], match)
    # CRDi is Hyundai's diesel badge and SW is how the X-Trail rows spell estate.
    # Both were only reviewed for their own profile.
    if profile_id == 'hyundai_tucson':
        for match in re.finditer(r'\bCRDI\b', normalized):
            collector.add('fuel_family', 'diesel', match)
    if profile_id == 'nissan_xtrail':
        for match in re.finditer(r'\bSW\b', normalized):
            collector.add('body_family', 'station_wagon', match)
    for match in TRANSMISSION_PATTERN.finditer(normalized):
        kind = TRANSMISSION_KINDS[match[2]]
        collector.add('transmission_kind', kind, match)
        if match[1]:
            # A CVT's reported steps are simulated ratios, not fixed gears, so
            # they are recorded under a different key and never gear-compared.
            collector.add('reported_cvt_steps' if kind == 'cvt' else 'gear_count', int(match[1]), match)
    for match in DOOR_PATTERN.finditer(normalized):
        collector.add('door_count', int(match[1]), match)
    if profile_id == 'mercedes_cclass':
        for match in MERCEDES_VARIANT_PATTERN.finditer(normalized):
            collector.add('variant', 'C ' + match[1], match)
    for match in WORD_PATTERN.finditer(normalized):
        if match.group() in marketing_trims:
            collector.add('marketing_trim', match.group(), match)


def _record_internal_conflicts(result: dict, normalized: str) -> None:
    """Flag a SUBMODEL string that contradicts itself."""
    def conflict(message: str, key: str) -> None:
        result['internal_conflicts'].append(message)
        if core_field(key) not in result['conflict_fields']:
            result['conflict_fields'].append(core_field(key))

    for key, fact in result['facts'].items():
        values = fact['values']
        if key == 'drive_category':
            if submodel_drive_category(normalized) == 'conflict':
                conflict('mutually exclusive drive categories', key)
        elif key == 'transmission_kind':
            # Automatic is broad enough to include CVT. AT+CVT is not a conflict.
            if 'manual' in values and any(v in values for v in ('automatic', 'cvt')):
                conflict('mutually exclusive transmission kinds', key)
        elif key != 'marketing_trim' and len(values) > 1:
            conflict('multiple conflicting ' + key + ' values', key)


def single_value(parsed: dict, key: str):
    """The one value for a fact, or None when absent or self-contradictory."""
    values = parsed['facts'].get(key, {}).get('values', [])
    return values[0] if len(values) == 1 else None


def capacity_check(parsed: dict, cubic_centimetres) -> str:
    """Compare rounded marketing litres with an exact displacement.

    A one-decimal marketing displacement is shown as consistent when the exact
    displacement falls in its ordinary rounding interval. A value outside that
    interval is only an apparent mismatch for review: no supplied official
    source establishes that every marketing label follows this rounding rule,
    so it cannot veto a candidate or declare the source self-contradictory.

    Displacement is read through the same helper the candidate comparison uses,
    so the two agree on what counts as a displacement at all. That matters for
    battery electric vehicles, recorded as 0 or 1 cc: reading 1 as a real
    measurement here would let a litres token in the SUBMODEL contradict it,
    turning an honest abstention into a source conflict.
    """
    litres = single_value(parsed, 'capacity_litres')
    value = displacement_cc(cubic_centimetres)
    if litres is None or value is None:
        return 'unknown'
    midpoint = Decimal(litres) * 1000
    return ('consistent (rounded litres)'
            if midpoint - 50 <= Decimal(str(value)) < midpoint + 50
            else 'apparent mismatch (review only)')


def capacity_litre_check(parsed: dict, catalogue_litres) -> str:
    """Compare SUBMODEL marketing litres with TecDoc ``Capacity_litre``.

    Both inputs are display values, so ``1.5`` and ``1,5`` state the same fact.
    This comparison is review evidence only: it can narrow a shortlist after
    the make/model/year gates, but cannot repair an exact CC_RATING conflict or
    make a candidate eligible for automatic assignment.
    """
    source_litres = single_value(parsed, 'capacity_litres')
    if source_litres is None or catalogue_litres is None:
        return 'unknown'
    raw = strict_text(catalogue_litres).replace(',', '.')
    try:
        reference_litres = Decimal(raw)
    except InvalidOperation:
        return 'unknown'
    if not reference_litres.is_finite():
        return 'unknown'
    return 'agree' if Decimal(source_litres) == reference_litres else 'disagree'


def fuel_checks(parsed: dict, value, table: str) -> dict:
    """Compare the SUBMODEL fuel family and hybrid token with a fuel label.

    ``table`` names which side's labels to read -- the register's or the
    reference catalogue's. They are separate vocabularies in separate files, so
    the caller says which publisher wrote the value it is passing.
    """
    known = vocabularies()[table].get(strict_text(value))
    family = single_value(parsed, 'fuel_family')
    hybrid = single_value(parsed, 'hybrid')
    return {
        'fuel_family': ('unknown' if known is None or family is None
                        else 'consistent' if family == known[0] else 'disagree'),
        'hybrid': ('unknown' if known is None or hybrid is None
                   else 'consistent' if known[1] else 'disagree'),
    }


def source_context(row) -> dict:
    """Parse the row's SUBMODEL and check it against the row's own structured fields.

    These checks describe the source record, not any candidate, so a failure
    here withdraws the whole row rather than eliminating one kType.
    """
    parsed = parse_submodel(source_field(row, 'submodel'), source_field(row, 'make'), source_field(row, 'model'))
    checks = {'capacity': capacity_check(parsed, source_field(row, 'displacement')),
              **fuel_checks(parsed, source_field(row, 'fuel'), 'registry_submodel_fuel')}
    bodies = vocabularies()['registry_bodies']
    families = vocabularies()['submodel_body_families']
    body_type = strict_text(source_field(row, 'body'))
    checks['body'] = 'unknown'
    # The register value this submodel body family names, where the registry
    # records one. Without it the free text cannot contradict the body field,
    # which is an abstention rather than a disagreement.
    stated = families.get(single_value(parsed, 'body_family'))
    if stated is not None and body_type in bodies:
        checks['body'] = 'consistent' if body_type == strict_text(stated) else 'disagree'
    checks.update(_transmission_checks(parsed, source_field(row, 'transmission')))
    conflicts = list(parsed['internal_conflicts'])
    fields = list(parsed['conflict_fields'])
    for key, verdict in checks.items():
        if verdict != 'disagree':
            continue
        conflicts.append(f"{column('submodel')} {key} contradicts structured source field")
        if core_field(key) not in fields:
            fields.append(core_field(key))
    return {'parsed': parsed, 'source_checks': checks,
            'source_conflicts': conflicts, 'source_conflict_fields': fields}


def _transmission_checks(parsed: dict, transmission_type) -> dict:
    """Compare SUBMODEL transmission wording with TRANSMISSION_TYPE.

    NZTA notes TRANSMISSION_TYPE "is infrequently recorded" (62% populated in
    the 2020 cohort). That warns about presence, not correctness, and this check
    can only withdraw an acceptance, never create one, so an unreliable field
    costs coverage rather than accuracy. The veto therefore stays; the caveat is
    recorded so the cost is attributed to the right field in review.
    """
    transmission = strict_text(transmission_type)
    source_kinds = set()
    if re.search(r'\bMANUAL\b', transmission):
        source_kinds.add('manual')
    if re.search(r'\bAUTO(?:MATIC)?\b', transmission):
        source_kinds.add('automatic')
    if 'CONTINUOUSLY VARIABLE' in transmission or re.search(r'\bCVT\b', transmission):
        source_kinds.add('cvt')
    submodel_kinds = parsed['facts'].get('transmission_kind', {}).get('values', [])
    checks = {'transmission': 'unknown', 'gear_count': 'unknown'}
    if submodel_kinds and source_kinds:
        source_manual = 'manual' in source_kinds
        source_auto = bool(source_kinds & {'automatic', 'cvt'})
        conflict = (source_manual and source_auto
                    or ('manual' in submodel_kinds and source_auto)
                    or (any(k in submodel_kinds for k in ('automatic', 'cvt')) and source_manual))
        checks['transmission'] = 'disagree' if conflict else 'consistent'
    reported = GEAR_COUNT_PATTERN.search(transmission)
    gears = single_value(parsed, 'gear_count')
    if reported and gears is not None and 'cvt' not in source_kinds:
        checks['gear_count'] = 'consistent' if gears == int(reported[1]) else 'disagree'
    return checks


def candidate_checks(context: dict, candidate) -> dict:
    """Compare the parsed SUBMODEL with one reference candidate."""
    parsed = context['parsed']
    checks = {'capacity': capacity_check(parsed, candidate.get('Capacity_cubic')),
              'capacity_litre': capacity_litre_check(parsed, candidate.get('Capacity_litre')),
              **fuel_checks(parsed, candidate.get('Fuel_type'), 'catalogue_submodel_fuel'),
              'body': 'unknown', 'cab': 'unknown'}
    # Body wording in a submodel is compared only where both publishers print the
    # same name for the structure -- see registry_bodies and catalogue_structures,
    # which record a pairing on name identity alone. The station-wagon family check this used to
    # run rested on pairing STATION WAGON with Estate, SUV and Closed Off-Road
    # Vehicle, which no publisher states, so it is not made.
    #
    # 'cab' likewise stays unknown. Excluding PICKUP for a single cab needed a
    # Holden model-lineup specification that is not one of this project's sources,
    # and the RDM carries no cab column to replace it with. Because it is unknown
    # on every row, decision.scoped_structural_preference cannot fire: that is why
    # the Colorado rows stop as 'candidates not separated' and need the KT 086
    # ruling rather than a reading of this field.
    return {**{'submodel_' + key: value for key, value in checks.items()}, **NOT_COMPARABLE}


def audit_columns(context: dict) -> dict:
    """Everything the parser saw, serialized for the audit trail."""
    return {'submodel_parsed': json.dumps(context['parsed'], sort_keys=True),
            'submodel_source_checks': json.dumps(context['source_checks'], sort_keys=True),
            'submodel_source_conflicts': '; '.join(context['source_conflicts']),
            'submodel_source_conflict_fields': '; '.join(context['source_conflict_fields'])}
