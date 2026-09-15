"""Agreement-set selection with provisional engineering rules.

Annex I informs the attribute groups; it does not specify the ranking or acceptance
policy implemented here. Weights are avoided, but precedence, sufficiency and
identifier guards still require domain validation."""
from __future__ import annotations

from .config import VARIANT_CRITERIA, VERSION_CRITERIA, identifiers_where

# Verdicts that mean the two catalogues could not be put side by side at all,
# as opposed to being compared and saying nothing. Only the former removes a
# criterion from the denominator: a field this catalogue pair does not both
# carry was never a question, while a field one side simply left empty is a
# question that went unanswered, and answering it is what would let the row
# through.
NOT_COMPARABLE = 'not comparable'


def agreed(entry, criteria) -> frozenset:
    """The criteria this candidate actually agrees with."""
    return frozenset(field for field in criteria if entry[field] == 'agree')


def comparable_version(entry) -> frozenset:
    """The version criteria this catalogue pair can compare for this candidate.

    Capacity drops out when it is unknown as well as when it is structurally
    incomparable, because the two are the same situation seen from either side:
    an electric vehicle has no cylinder displacement to compare and a row whose
    displacement is missing has none recorded. Neither can ever agree, so
    requiring agreement would abstain forever rather than decide. What keeps
    that from being a loosening is `sufficient`, which then demands an
    identifier -- with capacity gone, version evidence reduces to fuel plus
    power, and several variants share an output.
    """
    return frozenset(field for field in VERSION_CRITERIA
                     if entry[field] != NOT_COMPARABLE
                     and not (field == 'capacity' and entry[field] == 'unknown'))


def capacity_comparable(entry) -> bool:
    """Whether cylinder capacity was a question these two catalogues could ask."""
    return entry['capacity'] not in (NOT_COMPARABLE, 'unknown')


def has_identifier(entry) -> bool:
    """Whether a recorded structural identifier points at this candidate.

It can release a sufficiency guard, but is not a weighted tie-breaker here."""
    return any(entry[f'{field}_tokens'] for field in identifiers_where('authoritative'))


def criterion_sets(entry) -> tuple[frozenset, frozenset]:
    """One candidate as the pair of criterion sets selection compares."""
    return agreed(entry, VERSION_CRITERIA), agreed(entry, VARIANT_CRITERIA)


def sufficient(entry) -> tuple[bool, str, tuple]:
    """Require a documented identity code or the complete criterion route.

An officially decoded manufacturer model code takes priority because it is
compared directly with the candidate's manufacturer model code. It can make
a compatible candidate sufficient even when a registry specification is absent;
it can never excuse a contradiction because only compatible candidates qualify.

Without that code, every comparable version criterion and at least one variant
criterion must agree. Missing capacity additionally needs an identifier. The
requirement depends only on the source/candidate evidence: adding or removing
unrelated catalogue rows must not change whether this candidate is sufficiently
described.
Return the verdict, explanation and fields needing more evidence."""
    if entry.get('compatible') and entry.get('chassis_model_comparison') == 'agree':
        return True, '', ()
    version, variant = criterion_sets(entry)
    missing = comparable_version(entry) - version
    if missing:
        return False, 'no agreement on ' + ', '.join(sorted(missing)), tuple(sorted(missing))
    if not variant:
        # The variant criteria the catalogues could have compared and did not
        # agree on. A criterion neither side carries is not a field anyone can
        # settle, so it is not named.
        open_fields = tuple(field for field in VARIANT_CRITERIA
                            if entry[field] != NOT_COMPARABLE)
        return False, 'no variant criterion agrees', open_fields
    if not capacity_comparable(entry) and not has_identifier(entry):
        return (False, 'capacity is not comparable and no structural identifier corroborates',
                ('capacity',))
    return True, '', ()


def criterion_vector(entry) -> str:
    """Display agreement counts and comparable version fields, not confidence."""
    version, variant = criterion_sets(entry)
    return (f'{len(version)}/{len(comparable_version(entry))} version'
            f' + {len(variant)}/{len(VARIANT_CRITERIA)} variant')


def criterion_columns(entry) -> dict:
    """The per-candidate audit trail, recorded whichever selector is running.

    Descriptive only: these columns state which Annex I criteria agreed and
    which could be compared at all. They are computed for every candidate under
    both selection rules, so a run under the score route can be read in the
    redesign's terms without being decided by them.
    """
    version, variant = criterion_sets(entry)
    return {'version_criteria_agreed': '; '.join(sorted(version)),
            'variant_criteria_agreed': '; '.join(sorted(variant)),
            'version_criteria_comparable': '; '.join(sorted(comparable_version(entry))),
            'criterion_vector': criterion_vector(entry)}
