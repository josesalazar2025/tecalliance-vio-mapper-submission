"""Manufacturer-scoped decoding of registry model-code identifiers.

The engine is generic; the knowledge is data. A profile may read a chassis prefix,
VIN or manufacturer model-code field. Each profile names its make/model, input
pattern, reference column, known model-code vocabulary and manufacturer sources.
A missing profile or unfamiliar value returns unknown and cannot affect a match.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from .config import MANUFACTURER_RULES_DIR, identifiers_of_kind, source_field
from .normalization import compact_code, normalized_text

RULES_PATH = MANUFACTURER_RULES_DIR / 'chassis_model_codes.json'


@lru_cache(maxsize=1)
def chassis_rules() -> dict:
    rules = json.loads(RULES_PATH.read_text())
    if rules.get('schema_version') != 1:
        raise ValueError('Unsupported chassis-model decoder schema')
    profile_ids = set()
    for profile in rules.get('profiles', []):
        if profile['id'] in profile_ids:
            raise ValueError(f"Duplicate chassis decoder profile {profile['id']}")
        profile_ids.add(profile['id'])
        pattern = re.compile(profile['pattern'])
        if 'model_code' not in pattern.groupindex:
            raise ValueError(f"Chassis profile {profile['id']} must capture model_code")
        if not profile.get('known_model_codes'):
            raise ValueError(f"Chassis profile {profile['id']} has no known model codes")
        if profile.get('decision_role', 'candidate_veto') not in {'candidate_veto', 'proposal_only'}:
            raise ValueError(f"Chassis profile {profile['id']} has invalid decision role")
        for source_id in profile['source_ids']:
            if source_id not in rules['sources']:
                raise ValueError(f"Chassis profile {profile['id']} has unknown source {source_id}")
    return rules


def decode_chassis_model(row) -> dict:
    """Decode one manufacturer model code, or return a neutral audit result."""
    make = normalized_text(source_field(row, 'make'))
    model = normalized_text(source_field(row, 'model'))
    profiles = [profile for profile in chassis_rules()['profiles']
                if profile['make'] == make and profile['model'] == model]
    matches = []
    for profile in profiles:
        for field in identifiers_of_kind(profile['source_identifier_kind']):
            raw = normalized_text(row.get(field))
            match = re.fullmatch(profile['pattern'], raw)
            code = match.group('model_code') if match else None
            # A syntactically valid but unlisted code is still unsupported.
            # It must not be turned into negative evidence by the decoder.
            if code in profile['known_model_codes']:
                matches.append((field, raw, profile, code))
    if not matches:
        return {'status': 'unavailable', 'model_code': None,
                'source_field': '', 'raw': '', 'profile': None, 'sources': {},
                'reference_column': '', 'known_model_codes': frozenset()}
    codes = {code for _, _, _, code in matches}
    if len(codes) != 1:
        return {'status': 'conflicting', 'model_code': None,
                'source_field': '; '.join(field for field, _, _, _ in matches),
                'raw': '; '.join(f'{field}={raw}' for field, raw, _, _ in matches),
                'profile': None,
                'sources': {source_id: chassis_rules()['sources'][source_id]
                            for _, _, profile, _ in matches
                            for source_id in profile['source_ids']},
                'reference_column': '', 'known_model_codes': frozenset()}
    # Independent identifiers that decode to the same value corroborate rather
    # than make the result ambiguous. Prefer an actionable profile over a
    # proposal-only one, while retaining the provenance of every agreeing read.
    field, raw, profile, code = min(
        matches, key=lambda item: item[2].get('decision_role', 'candidate_veto') == 'proposal_only')
    sources = {source_id: chassis_rules()['sources'][source_id]
               for _, _, matched_profile, _ in matches
               for source_id in matched_profile['source_ids']}
    return {'status': 'documented', 'model_code': code, 'source_field': field,
            'raw': raw, 'profile': profile['id'], 'sources': sources,
            'reference_column': profile['reference_column'],
            'decision_role': profile.get('decision_role', 'candidate_veto'),
            'known_model_codes': frozenset(profile['known_model_codes'])}


def candidate_chassis_evidence(row, candidate) -> dict:
    """Compare a decoded code only with officially enumerated reference codes."""
    decoded = decode_chassis_model(row)
    comparison = 'unknown'
    reference_codes = set()
    if decoded['model_code']:
        raw_reference = normalized_text(candidate.get(decoded['reference_column']))
        reference_codes = {compact_code(part) for part in raw_reference.split(';')
                           if compact_code(part)}
        comparable = reference_codes & decoded['known_model_codes']
        if comparable:
            comparison = 'agree' if decoded['model_code'] in comparable else 'disagree'
    role = decoded.get('decision_role', 'candidate_veto')
    return {'chassis_model_code': decoded['model_code'],
            'chassis_model_comparison': comparison if role == 'candidate_veto' else 'unknown',
            'chassis_model_hint_comparison': comparison if role == 'proposal_only' else 'unknown',
            'chassis_model_decision_role': role if decoded['model_code'] else '',
            'chassis_model_reference_codes': '; '.join(sorted(reference_codes)),
            'chassis_model_profile': decoded['profile'] or '',
            'chassis_model_source_field': decoded['source_field'],
            'chassis_model_sources': '; '.join(sorted(decoded['sources']))}


def chassis_audit_columns(row) -> dict:
    decoded = decode_chassis_model(row)
    return {'chassis_decoder_status': decoded['status'],
            'chassis_decoder_profile': decoded['profile'] or '',
            'chassis_decoder_source_field': decoded['source_field'],
            'chassis_decoder_raw': decoded['raw'],
            'chassis_decoder_model_code': decoded['model_code'],
            'chassis_decoder_decision_role': decoded.get('decision_role', ''),
            'chassis_decoder_sources': json.dumps(decoded['sources'], sort_keys=True)}
