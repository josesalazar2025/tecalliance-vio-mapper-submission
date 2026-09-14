"""Conservative bridge from sourced VIN fields to reference attributes.

Only reviewed semantic adapters are actionable. No kTypes, row IDs, dataset
observations, inferred values or VIN model-year production-date gates are used.
A documented value is necessary but not sufficient: units, terminology and scope
must also match the reference, so every other decoded field stays audit-only.
"""
from __future__ import annotations

import json
import re

from .config import vin_column, vin_rules_path
from .normalization import reference_drive_category
from .vin_decoder import decode_vin11, rules_for_decoding

GENERATION_TOKENS = {'nissan_t32': {'T31', 'T32', 'T33'}}
DEFAULT_GENERATION_TOKENS = {'OS', 'SX2'}
# Nissan code shapes this helper is willing to call a mismatch. Anything else is
# unrecognized rather than contradicted.
NISSAN_ENGINE_CODE = re.compile(r'(?:[A-Z]{2}\d{2}[A-Z]{2}|R9M)')
GENERATION_TOKEN_SPLIT = re.compile(r'[^A-Z0-9_]+')


def _nissan_t32_adapters(decoded, context: dict) -> dict:
    """Documented Nissan T32 series, engine and drive segments."""
    profile = next(p for p in rules_for_decoding()['profiles'] if p['id'] == decoded.profile)
    context['recognized_engine_codes'] = sorted({
        value for segment in profile['segments']
        if segment['key'] == 'engine' and segment['evidence_status'] == 'documented'
        for value in segment['values'].values()})
    return {'series': ('generation', lambda segment: segment['raw']),
            'engine': ('engine', lambda segment: segment['meaning']),
            'drive': ('drive', lambda segment: {'2WD': '2wd', '4WD': 'awd'}.get(segment['meaning']))}


def vin_context(value, make: str, model: str, *, enabled: bool = True) -> dict:
    """Decode one VIN11 and keep only the facts with a reviewed reference meaning."""
    context = {'profile': None, 'status': 'disabled', 'facts': {}, 'sources': {},
               'source_conflicts': [], 'recognized_engine_codes': [],
               'note': 'VIN helper disabled.'}
    if not enabled:
        return context
    # A registry may carry no VIN layouts. That is an absence of evidence, not a
    # failure: the helper contributes nothing and every VIN comparison stays
    # unknown, exactly as --no-vin-helper leaves it.
    if vin_rules_path() is None:
        return {**context, 'note': 'VIN helper unavailable: this registry records no VIN layouts.'}
    if not isinstance(value, str) or not value.strip():
        return {**context, 'status': 'missing',
                'note': f'{vin_column()} missing; no helper evidence.'}
    try:
        decoded = decode_vin11(value)
    except (TypeError, ValueError) as exc:
        return {**context, 'status': 'invalid', 'note': f'{vin_column()} not used: {exc}'}
    context.update(profile=decoded.profile, status=decoded.status,
                   note='Only documented fields with reviewed reference comparisons are used.')
    documented = {segment['key']: segment for segment in decoded.segments
                  if segment['status'] == 'documented'}
    expected_vehicle = None
    if decoded.profile == 'nissan_t32':
        expected_vehicle = ('NISSAN', 'X-TRAIL')
        adapters = _nissan_t32_adapters(decoded, context)
    elif (decoded.profile == 'hyundai_kona_os'
          and documented.get('model_year', {}).get('meaning') == '2020'):
        # The retrieved manual is for 2020 OS. Do not extend its applicability
        # to every Hyundai beginning KMHK or treat Nu 2.0 MPI as engine G4NH.
        expected_vehicle = ('HYUNDAI', 'KONA')
        adapters = {'series': ('generation',
                               lambda segment: 'OS' if segment['meaning'] == 'Kona OS' else None)}
    else:
        adapters = {}
        context['note'] = 'No reviewed actionable adapter; decoded fields remain audit-only.'
    if expected_vehicle and (make, model) != expected_vehicle:
        context['source_conflicts'].append('VIN profile contradicts supplied make/model')
    for key, (attribute, convert) in adapters.items():
        segment = documented.get(key)
        if segment is None:
            continue
        decoded_value = convert(segment)
        if decoded_value is None:
            continue
        context['facts'][attribute] = {
            'value': decoded_value, 'field': key, 'raw': segment['raw'],
            'start': segment['start'], 'end': segment['end'], 'status': 'documented',
            'source_ids': segment['source_ids']}
        for source_id in segment['source_ids']:
            context['sources'][source_id] = decoded.sources[source_id]
    return context


def drive_comparison(left, right) -> str:
    """Compare two drive categories, treating 2WD as compatible with FWD/RWD."""
    if left is None or right is None:
        return 'unknown'
    if left == right or (left == '2wd' and right in {'fwd', 'rwd'}) or (right == '2wd' and left in {'fwd', 'rwd'}):
        return 'agree'
    return 'disagree'


def reference_generations(value, profile) -> set[str]:
    """Compare exact tokens, not arbitrary substrings or Type_design variants.

    An explicit T31/T32/T33 or OS/SX2 is comparable. Wildcards or unfamiliar
    designations remain unknown and therefore cannot be eliminated by this rule.
    """
    tokens = set(GENERATION_TOKEN_SPLIT.split(str(value).upper()))
    return tokens & GENERATION_TOKENS.get(profile, DEFAULT_GENERATION_TOKENS)


def candidate_vin_evidence(context: dict, candidate) -> dict:
    """Compare the decoded VIN facts with one reference candidate."""
    facts = context['facts']
    evidence = {f'vin_{key}': 'unknown' for key in ('generation', 'drive', 'engine')}
    if 'generation' in facts:
        generations = reference_generations(candidate.get('Model_design'), context['profile'])
        if generations:
            evidence['vin_generation'] = 'agree' if facts['generation']['value'] in generations else 'disagree'
    if 'drive' in facts:
        evidence['vin_drive'] = drive_comparison(facts['drive']['value'],
                                                 reference_drive_category(candidate.get('Drive_system')))
    if 'engine' in facts:
        # Compare whole reference engine codes; an absent code remains unknown.
        # Limit negative comparisons to recognizable complete Nissan codes.
        codes = {code.strip().upper() for code in str(candidate.get('Engine_code')).split(';')}
        recognizable = {code for code in codes if NISSAN_ENGINE_CODE.fullmatch(code)}
        if facts['engine']['value'] in codes:
            evidence['vin_engine'] = 'agree'
        elif codes and codes == recognizable:
            evidence['vin_engine'] = 'disagree'
    return evidence


def audit_columns(context: dict) -> dict:
    """Everything the helper decoded and every source it relied on."""
    return {'vin_helper_profile': context['profile'], 'vin_helper_status': context['status'],
            'vin_helper_facts': json.dumps(context['facts'], sort_keys=True),
            'vin_helper_sources': json.dumps(context['sources'], sort_keys=True),
            'vin_helper_source_conflicts': '; '.join(context['source_conflicts']),
            'vin_helper_note': context['note']}
