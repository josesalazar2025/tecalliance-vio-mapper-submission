"""Presentation-only text similarity for unresolved candidate review.

Similarity is calculated only after the mapping outcome is final. It never changes
candidate compatibility, evidence verdicts, scores, proposals or assignments.
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from .config import core_conflict, score_rules, source_field
from .normalization import normalized_text


SIMILARITY_METHOD = 'mean(ratio, token_sort_ratio); RapidFuzz'
REFERENCE_TEXT_FIELDS = ('reference_Type_designation',
                         'reference_Model_design',
                         'reference_Type_design')
NON_TEXT = re.compile(r'[^A-Z0-9]+')


def similarity_text(value) -> str:
    """Normalize punctuation without concatenating distinct vehicle tokens."""
    return ' '.join(NON_TEXT.sub(' ', normalized_text(value)).split())


def reference_text(candidate) -> str:
    """Build one stable candidate label, omitting duplicate and missing parts."""
    parts = []
    for field in REFERENCE_TEXT_FIELDS:
        value = similarity_text(candidate.get(field))
        if value and value not in parts:
            parts.append(value)
    return ' '.join(parts)


def add_review_similarity(row, details: list[dict], *, unresolved: bool) -> None:
    """Attach auditable similarity diagnostics and order unresolved candidates.

    Deterministic evidence remains the primary review ordering. Text similarity
    breaks ties only after decision priority, conflict class, identity agreement,
    conflict count and exact criterion agreements. The final kType key makes
    ordering reproducible.
    """
    source = similarity_text(source_field(row, 'submodel')) if unresolved else ''
    for candidate in details:
        target = reference_text(candidate) if source else ''
        score = None
        if source and target:
            score = round((fuzz.ratio(source, target)
                           + fuzz.token_sort_ratio(source, target)) / 2, 1)
        candidate.update({
            'text_similarity_score': score,
            'text_similarity_method': SIMILARITY_METHOD if score is not None else '',
            'text_similarity_source': source,
            'text_similarity_reference': target,
        })

    scores = sorted({candidate['text_similarity_score'] for candidate in details
                     if candidate['text_similarity_score'] is not None}, reverse=True)
    for candidate in details:
        score = candidate['text_similarity_score']
        candidate['text_similarity_rank'] = scores.index(score) + 1 if score is not None else None


def order_review_candidates(details: list[dict], *, selected: int | None,
                            proposed: int | None, lead: int | None,
                            shortlist: set[int], remaining: set[int],
                            unresolved: bool) -> None:
    """Order evidence for reviewers without feeding the order back into a decision."""
    def standing(candidate) -> tuple[int, str, str]:
        ktype = candidate['KType']
        if candidate.get('selected') or ktype == selected:
            return 0, 'selected', 'Accepted candidate produced by the decision policy.'
        if ktype == proposed:
            return 1, 'most likely', 'Advisory proposal named by identifier or scoped model evidence.'
        if ktype == lead:
            return 1, 'most likely', 'Closest candidate explicitly named for human review.'
        if ktype in shortlist:
            return 2, 'shortlist', 'Candidate included in the explicit review shortlist.'
        if candidate.get('compatible') or ktype in remaining:
            return 3, 'compatible', 'No retained specification comparison contradicts this candidate.'
        return 4, 'other', 'Review-only ordering; no candidate status or decision was changed.'

    for candidate in details:
        tier, priority, basis = standing(candidate)
        candidate['_review_tier'] = tier
        candidate['review_priority'] = priority
        candidate['review_priority_basis'] = basis

    def count_fields(value) -> int:
        return len([field for field in str(value or '').split(';') if field.strip()])

    def order_key(candidate):
        rules = score_rules()
        conflict_classes = rules['review_conflict_classes']
        severity = rules['review_conflict_severity']
        raw_conflicts = {field.strip() for field in
                         str(candidate.get('disagreements') or '').split(';') if field.strip()}
        independent_conflicts = {core_conflict(field) for field in raw_conflicts}
        identity_conflicts = {field for field in raw_conflicts
                              if conflict_classes.get(field) == 'identity'}
        configuration_conflicts = {field for field in raw_conflicts
                                   if conflict_classes.get(field) == 'configuration'}
        identity_agreements = {field for field, conflict_class in conflict_classes.items()
                               if conflict_class == 'identity'
                               and candidate.get(field) == 'agree'}
        near_power_only = (independent_conflicts == {'power'}
                           and bool(candidate.get('power_within_triage_band')))
        conflict_severity = (severity['none'] if not independent_conflicts else
                             severity['near_power_only']
                             if unresolved and near_power_only else
                             severity['identity']
                             if unresolved and identity_conflicts else
                             severity['specification_or_configuration'])
        agreements = sum(count_fields(candidate.get(field))
                         for field in ('version_criteria_agreed', 'variant_criteria_agreed'))
        similarity = candidate.get('text_similarity_score')
        power_gap = candidate.get('power_difference_kw')
        try:
            power_gap = abs(float(power_gap))
        except (TypeError, ValueError):
            power_gap = float('inf')
        candidate['review_conflict_severity'] = conflict_severity
        candidate['review_independent_conflict_count'] = len(independent_conflicts)
        candidate['review_near_power_only'] = near_power_only
        candidate['review_identity_conflicts'] = '; '.join(sorted(identity_conflicts))
        candidate['review_configuration_conflicts'] = '; '.join(sorted(configuration_conflicts))
        candidate['review_identity_agreements'] = '; '.join(sorted(identity_agreements))
        if unresolved:
            return (candidate['_review_tier'], conflict_severity, -len(identity_agreements),
                    len(independent_conflicts), -agreements,
                    -(similarity if similarity is not None else -1), power_gap, candidate['KType'])
        # Preserve the established ordering of alternatives on matched rows.
        return (candidate['_review_tier'], len(raw_conflicts), -agreements, -1,
                power_gap, candidate['KType'])

    details.sort(key=order_key)
    for rank, candidate in enumerate(details, 1):
        candidate['review_rank'] = rank
        del candidate['_review_tier']
