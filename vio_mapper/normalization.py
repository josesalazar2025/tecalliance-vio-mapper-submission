"""Field-level parsing shared by both catalogues.

Every function here answers one question about one value and returns ``None``
when it cannot answer it. That is deliberate: an unknown withholds acceptance,
whereas a guessed value could grant it, and this pipeline treats a wrong kType
as worse than an unresolved row.
"""
from __future__ import annotations

import re
from functools import lru_cache

import pandas as pd

from .config import vocabularies

MERCEDES_VARIANT_PATTERN = re.compile(r'\bC\s*(\d{3})\b')
NON_ALPHANUMERIC = re.compile(r'[^A-Z0-9]+')


@lru_cache(maxsize=1)
def submodel_drive_pattern() -> re.Pattern:
    """Match exactly the drive tokens the vocabulary records, and nothing else.

    Built from ``submodel_drive`` rather than written out here, so that the
    grounding recorded in that section is the only thing this reads. A token
    removed there for want of a source stops being matched, instead of
    surviving in a regex nobody thought to update.
    """
    vocabulary = vocabularies()
    tokens = sorted({*vocabulary['submodel_drive'], *vocabulary['submodel_drive_source_only']},
                    key=len, reverse=True)
    if not tokens:
        # A registry that records no drive wording must match nothing. An empty
        # alternation would match the empty string at every position instead.
        return re.compile(r'(?!)')
    return re.compile(r'\b(?:' + '|'.join(re.escape(token) for token in tokens) + r')\b')


def normalized_text(value) -> str:
    """Upper-cased, whitespace-collapsed text; missing values become ''."""
    if pd.isna(value):
        return ''
    return ' '.join(str(value).strip().upper().split())


def strict_text(value) -> str:
    """Like :func:`normalized_text`, but a non-string is treated as absent.

    The SUBMODEL rules parse free text written by a registration clerk. A
    numeric cell in a text column is a data-quality problem, not a submodel, so
    it is read as 'nothing was written' instead of being stringified into tokens
    that the format rules were never reviewed against.
    """
    return ' '.join(value.upper().split()) if isinstance(value, str) else ''


def compact_code(value) -> str:
    """Text reduced to A-Z0-9, for comparing codes written with punctuation."""
    return NON_ALPHANUMERIC.sub('', normalized_text(value))


def code_tokens(value) -> list[str]:
    """Split a code field on its punctuation, keeping the parts comparable."""
    return NON_ALPHANUMERIC.split(normalized_text(value))


def numeric_value(value):
    """A finite, strictly positive number, or None. Zero is never a measurement."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if pd.notna(parsed) and 0 < parsed < float('inf') else None


def displacement_cc(value):
    """Engine displacement, or None when the field cannot be one.

    NZTA defines CC_RATING as the total swept volume of all cylinders. Battery
    electric vehicles have no cylinders and are recorded as 0 or 1: in the 2020
    cohort 2,087 carry 0 and 1,057 carry 1. Zero was already rejected, but 1 was
    compared as a real displacement and contradicted every candidate, turning a
    vehicle we cannot describe into one we claim to have refuted. One cubic
    centimetre is not an engine, so it is unknown.
    """
    displacement = numeric_value(value)
    return displacement if displacement is not None and displacement > 1 else None


def model_year(value):
    """A four-digit year in a plausible range, or None."""
    parsed = numeric_value(value)
    return int(parsed) if parsed is not None and parsed.is_integer() and 1886 <= parsed <= 2100 else None


def construction_yyyymm(value, *, allow_open: bool = False):
    """Parse an RDM construction date, raising on anything malformed.

    A production interval decides whether a candidate is chronologically
    possible, so a value that cannot be parsed must stop the run rather than
    silently become an open-ended interval. Only a construction *end* may be
    absent, meaning production had not ceased.
    """
    if pd.isna(value) or normalized_text(value) == '':
        if allow_open:
            return None
        raise ValueError('Missing construction start')
    parsed = numeric_value(value)
    if parsed is None or not parsed.is_integer():
        raise ValueError(f'Expected numeric YYYYMM, got {value!r}')
    year_part, month_part = divmod(int(parsed), 100)
    if model_year(year_part) is None or not 1 <= month_part <= 12:
        raise ValueError(f'Invalid YYYYMM: {value!r}')
    return int(parsed)


def registry_fuel_category(value):
    """A register fuel label as an internal fuel category; unlisted stays unknown.

    One function per catalogue, reading one vocabulary each. A single shared
    table would have to list both publishers' labels, which is exactly the
    coupling the two files were separated to remove: the register's labels are
    replaced when the country changes, the extract's are not.
    """
    return vocabularies()['registry_fuel'].get(normalized_text(value))


def catalogue_fuel_category(value):
    """A reference-catalogue fuel label as an internal fuel category."""
    return vocabularies()['catalogue_fuel'].get(normalized_text(value))


def reference_drive_category(value):
    """The RDM Drive_system label as an internal drive category."""
    return vocabularies()['reference_drive_system'].get(normalized_text(value))


def submodel_drive_category(value):
    """The drive category written in a SUBMODEL string.

    Returns 'conflict' when the text names mutually exclusive systems, which is
    a statement about the source row rather than about any candidate.
    """
    vocabulary = vocabularies()
    drives = vocabulary['submodel_drive']
    tokens = {match.group() for match in submodel_drive_pattern().finditer(strict_text(value))}
    found = {drives[token] for token in tokens if token in drives}
    # A two-wheel-drive token carries no category of its own -- KT 082 states no
    # value it could be compared against -- but writing one alongside an
    # all-wheel drive still contradicts the text itself.
    if tokens & set(vocabulary['submodel_drive_source_only']):
        if vocabulary['submodel_drive_contradicts'] in found:
            return 'conflict'
    if len(found) > 1:
        return 'conflict'
    return next((category for category in ('awd', 'fwd', 'rwd') if category in found), None)


def mercedes_variant(value):
    """The 'C 200' style variant number written in a Mercedes designation."""
    match = MERCEDES_VARIANT_PATTERN.search(normalized_text(value))
    return f'C {match.group(1)}' if match else None


def compare_values(left, right) -> str:
    """Three-valued comparison: an unknown on either side is never a mismatch."""
    return 'unknown' if left is None or right is None else 'agree' if left == right else 'disagree'
