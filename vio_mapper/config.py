"""Paths, tunable policy and the rule tables shipped with the package.

Lookup tables live in JSON rather than in code so that a domain reviewer can
read and amend them without touching Python, and so that a rule change shows up
as a data diff. Every table is loaded once per process and cached: the matcher
consults them per candidate, and re-reading a file in that loop would dominate
the runtime.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ALGORITHM_VERSION = '1.1.0'

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
# Anchored to the repository rather than to the process working directory: the
# CLI defaults name the two supplied workbooks, and a default that silently means
# a different file depending on where the command was typed is not a default. An
# explicit --source/--reference still overrides it.
DATA_DIR = PROJECT_ROOT / 'data'
RULES_DIR = PACKAGE_ROOT / 'rules'
REGISTRIES_DIR = RULES_DIR / 'registries'
CATALOGUES_DIR = RULES_DIR / 'catalogues'
MANUFACTURER_RULES_DIR = RULES_DIR / 'manufacturers'

SOURCE_NAME = 'nz_gov_data_subset.xlsx'
REFERENCE_NAME = 'RDM_CARPARK_NZ_20250801_subset.xlsx'
DEFAULT_SOURCE_PATH = DATA_DIR / SOURCE_NAME
DEFAULT_REFERENCE_PATH = DATA_DIR / REFERENCE_NAME
# Which register the source data comes from, and which catalogue the reference
# is. Both name a file under the packaged registries or catalogues directories; the
# registry is a property of the source data, so its default belongs here beside
# DEFAULT_SOURCE_PATH rather than in the vocabulary loader.
DEFAULT_REGISTRY = 'nz'
DEFAULT_CATALOGUE = 'tecdoc'

# --- Row outcomes ---------------------------------------------------------
# A row is either accepted, or it is named in the review queue with a cause.
#
# A status is a claim about what the algorithm found, and a reviewer acts on it
# without reading the sub-status. It must therefore never say more, or less,
# than the sub-status beneath it. Two former statuses did:
#
#   'No compatible reference found' covered both an empty candidate pool and a
#   pool every member of which was contradicted. The second is not a missing
#   reference -- the reference was found and rejected on a named field -- and a
#   reviewer who trusts the wording will never open the group.
#
#   'Insufficient information' covered both thin evidence that could not
#   separate candidates and a lone candidate that nothing contradicted. The
#   second is the opposite situation: everything comparable agreed and no rival
#   survived at all.
#
# Both are split below. STATUS_CATEGORIES declares which sub-statuses each
# status may carry, and is enforced as a contract rather than a convention.
MATCHED = 'Matched'
AMBIGUOUS = 'Ambiguous'
CONFLICT = 'Conflicting source data'
NO_CANDIDATE_IN_REFERENCE = 'No candidate in reference'
ALL_CANDIDATES_CONTRADICTED = 'All candidates contradicted'
# Named for the situation rather than for the mechanism that stopped the row: a
# threshold is one selector's reason and the default selector has none, so the
# wording said 'below threshold' on rows no threshold was applied to. What is
# true under both is that one candidate survived, nothing contradicts it, and the
# evidence the two catalogues share does not reach what acceptance requires.
SOLE_CANDIDATE_INCOMPLETE = 'Single uncontradicted candidate, evidence incomplete'
INSUFFICIENT = 'Insufficient information'
PROPOSED = 'Proposed: likely candidate for review'
ALL_STATUSES = (MATCHED, PROPOSED, AMBIGUOUS, CONFLICT, NO_CANDIDATE_IN_REFERENCE,
                ALL_CANDIDATES_CONTRADICTED, SOLE_CANDIDATE_INCOMPLETE, INSUFFICIENT)

# Every unaccepted row carries a review sub-status so the review queue can be
# triaged and, more importantly, so lost coverage is attributable to a cause and
# a field instead of one undifferentiated 'conflicting' bucket. These are
# classifications of why a row stopped, never claims about which source is wrong.
SELF_CONTRADICTION = 'source contradicts itself'
VIN_CONTRADICTION = 'VIN contradicts source fields'
DUPLICATE_CONFLICT = 'duplicate ID values differ'
IDENTIFIER_DISAGREEMENT = 'identifiers disagree with each other'
IDENTIFIER_VS_SPECIFICATION = 'identifiers contradicted by specifications'
MODEL_CODE_HINT_VS_SPECIFICATION = 'model-code hint contradicted by specifications'
IDENTIFIER_UNSUPPORTED = 'identifier absent from candidate reference'
NO_CANDIDATE = 'no candidate passes make/model gates'
ALL_CONTRADICTED = 'every candidate contradicts specifications'
# A narrower reading of the same stop. Separated from ALL_CONTRADICTED because the
# two route to different desks: a specification disagreement is a data question,
# while a difference inside the engineering review band is a question about how the
# two publishers rounded one number. It classifies the stop and nothing else -- the
# headline status, the assignment and the VIO count are identical either way, and
# whether such a difference may ever be accepted stays with power_tolerance_pct,
# which is the data owner's to set.
NEAR_POWER_ONLY = 'closest candidate differs only on power, within the review band'
TIED_CANDIDATES = 'candidates tied'
SEPARABLE_ONLY_BY_SCOPED_RULE = 'separable only by a model-specific reading'
NARROW_MARGIN = 'margin below minimum'
BELOW_THRESHOLD = 'score below threshold'
EVIDENCE_FLOOR = 'evidence floor not met'
# The dominance selector's counterparts to the two above. Named separately
# rather than folded into them because they say something different: no score
# fell short and no candidates tied on a total -- the criteria the two
# catalogues could compare did not agree, or did not separate one candidate
# from another.
CRITERION_SET = 'minimum criterion set not met'
NOT_SEPARATED = 'candidates not separated by criterion set'
MISSING_GATE_FIELDS = 'make/model or gating year unavailable'
IDENTIFIER_WITHOUT_SPECIFICATION = 'identifier match unsupported by any specification'
# The last candidate standing, where the ones that fell were removed by a comparison
# this one escaped because no recorded vocabulary names its own value.
UNEARNED_ELIMINATION = 'sole survivor of comparisons it was not held to'

# How a row that was accepted got there. Recorded per row so an acceptance states
# its own reason rather than leaving a reader to infer it from a score.
ACCEPTED_ON_SCORE = 'support score'
ACCEPTED_ON_UNIQUENESS = 'sole candidate, complete version evidence'
# The weightless route. Recorded distinctly from the two above because it rests
# on a different fact: not how much evidence there is, nor that nothing else
# survived, but that no rival agrees with a wider set of Annex I criteria.
ACCEPTED_ON_DOMINANCE = 'criterion dominance'

# Which sub-statuses each headline status is allowed to carry. A status outside
# this table, or a pairing outside it, is a defect: the headline would be making
# a claim the sub-status does not support. Enforced by tests over every row of a
# real run, so the two can never drift apart again.
STATUS_CATEGORIES = {
    MATCHED: frozenset({''}),
    PROPOSED: frozenset({IDENTIFIER_VS_SPECIFICATION,
                         MODEL_CODE_HINT_VS_SPECIFICATION}),
    AMBIGUOUS: frozenset({TIED_CANDIDATES, SEPARABLE_ONLY_BY_SCOPED_RULE, NARROW_MARGIN,
                          NOT_SEPARATED}),
    CONFLICT: frozenset({SELF_CONTRADICTION, VIN_CONTRADICTION, DUPLICATE_CONFLICT,
                         IDENTIFIER_DISAGREEMENT, IDENTIFIER_VS_SPECIFICATION}),
    NO_CANDIDATE_IN_REFERENCE: frozenset({NO_CANDIDATE}),
    ALL_CANDIDATES_CONTRADICTED: frozenset({ALL_CONTRADICTED, NEAR_POWER_ONLY}),
    # One entry per selector, and no more: the score route stops such a row on
    # its threshold, the dominance route on a version criterion that went
    # unanswered. Both are the same situation and neither is the other's reason.
    SOLE_CANDIDATE_INCOMPLETE: frozenset({BELOW_THRESHOLD, CRITERION_SET}),
    INSUFFICIENT: frozenset({EVIDENCE_FLOOR, BELOW_THRESHOLD, IDENTIFIER_UNSUPPORTED,
                             IDENTIFIER_WITHOUT_SPECIFICATION, MISSING_GATE_FIELDS,
                             UNEARNED_ELIMINATION, CRITERION_SET}),
}

# --- Field vocabularies ---------------------------------------------------
# The specifications a candidate is compared on, in report order.
COMPARED_FIELDS = ('capacity', 'fuel', 'power', 'drive', 'body', 'variant', 'engine')
# Fuel categories whose vehicles have no cylinder displacement to compare. NZTA
# defines CC_RATING as total swept volume, and a battery electric vehicle has no
# cylinders: it is recorded as 0 or 1 cc, and the reference leaves Capacity_cubic
# empty for its electric kTypes. Exact capacity agreement is therefore not merely
# missing for these vehicles, it is unsatisfiable on both sides, so the evidence
# floor substitutes a different requirement rather than abstaining forever.
DISPLACEMENTLESS_FUELS = frozenset({'electric'})
# Available version attributes from the cited Annex I taxonomy. Agreement on
# these incomplete records does not establish complete vehicle identity.
# The chosen ranking and sufficiency are provisional engineering policies.
VERSION_CRITERIA = ('capacity', 'fuel', 'power')
# Annex I 1.2.1(a), (b) and (d): the type of bodywork, the power plant's
# construction features and the powered axles. The coarser of the two tiers, and
# the companion to VERSION_CRITERIA above -- pinned to the same criterion_tier
# table by tests/test_config.py, so neither list can drift from the claim about
# the Regulation that justifies it.
VARIANT_CRITERIA = ('body', 'engine', 'drive')
# Every evidence key whose 'disagree' verdict contradicts a candidate. The VIN
# and SUBMODEL entries duplicate observations already covered above; see the
# core-conflict table, which collapses them back onto one specification.
# submodel_cab is deliberately absent. Cab wording is a model-specific reading of
# free text: Holden sold no single-cab pickup, but that is a fact about one model's
# lineup, not a rule that generalises to every light commercial in TecDoc. Where two
# candidates differ only by body, vetoing one is equivalent to selecting the other, so
# a scoped reading would silently decide the row. It names the likely candidate and
# sends the row to review instead; see decision.scoped_structural_preference -- which is
# itself inert on every registry shipped here, because the cab vocabulary it reads carries
# no body restriction and submodel_cab never resolves. Both facts are recorded there.
VETO_FIELDS = (*COMPARED_FIELDS, 'vin_generation', 'vin_drive', 'vin_engine',
               'chassis_model_comparison', 'chronology',
               'submodel_capacity', 'submodel_fuel_family', 'submodel_hybrid',
               'submodel_body')
# Which roles a decision reads. The register column each one is recorded in is
# declared per registry, so this list says what the matcher consults and the
# registry file says where to find it. Deduplicating identical rows is only sound
# while this is complete, so it is declared once here and the decision code is
# checked against it by test_decision_columns_are_declared.
# The row identifier and source_key identify a row; they never change its outcome.
DECISION_ROLES = ('make', 'model', 'submodel', 'body', 'displacement', 'power', 'fuel',
                  'year', 'transmission', 'previous_country', 'import_status', 'engine_number')
# Roles without which a source file cannot be read at all: a row that names no
# vehicle and carries no identifier cannot be matched or reported on.
REQUIRED_ROLES = ('id', 'make', 'model', 'year')
# Two independent identifier fields must agree before a row may be proposed.
MINIMUM_ANCHOR_FIELDS = 2

# Reference columns copied onto each evidence row so a reviewer can see what the
# candidate actually claimed, without opening the reference workbook.
EXPORTED_REFERENCE_COLUMNS = ('Type_design', 'Type_designation', 'Model_design', 'Capacity_litre',
                              'Capacity_cubic',
                              'Fuel_type', 'Maximum_output_KW', 'Drive_system', 'Kind_of_structure',
                              'Engine_code', 'Construction_from', 'Construction_to')

# What each compared specification is called on either side, so a row that stops
# on a field can state the two values that disagree instead of only naming the
# field. Purely descriptive: quoting a source cell beside a reference cell
# asserts no correspondence between the two vocabularies and decides nothing. It
# hands the reviewer the pair their domain judgement is being deferred to.
#
# `source_role` is None where the register has no single column for the field --
# drive and variant are read out of free text, and the parsed reading is quoted
# instead. A field absent here is simply not described.
FIELD_VALUE_SOURCES = {
    'capacity': {'source_role': 'displacement', 'reference': 'Capacity_cubic', 'unit': 'cc'},
    'power': {'source_role': 'power', 'reference': 'Maximum_output_KW', 'unit': 'kW'},
    'fuel': {'source_role': 'fuel', 'reference': 'Fuel_type', 'unit': ''},
    'body': {'source_role': 'body', 'reference': 'Kind_of_structure', 'unit': ''},
    'drive': {'source_role': None, 'reference': 'Drive_system', 'unit': ''},
    'engine': {'source_role': 'engine_number', 'reference': 'Engine_code', 'unit': ''},
    'variant': {'source_role': None, 'reference': 'Type_designation', 'unit': ''},
    'chronology': {'source_role': 'year', 'reference': 'Construction_from', 'unit': ''},
}

EXCEL_MAX_ROWS = 1_048_576  # Hard worksheet limit; row-level exports outgrow it.
STREAM_ROW_THRESHOLD = 20_000  # Above this, candidate evidence is streamed to disk.
EVIDENCE_RETENTION = ('all', 'unresolved', 'selected')
# How a winner is chosen among the candidates that survived every veto. Both
# selectors run the same comparisons, the same vetoes and the same conflict
# safeguards; they differ only in what separates two survivors and in what makes
# the survivor sufficient. Shipped side by side deliberately, so replacing one
# with the other is a measurement rather than a rewrite -- the discipline
# --no-row-reuse applies to row reuse.
SELECTION_RULES = ('score', 'dominance')


@dataclass(frozen=True, kw_only=True)
class Policy:
    """Every tunable the matcher has.

    Frozen so a run cannot drift mid-file, and keyword-only so that adding or
    reordering a setting can never silently change the meaning of an existing
    call. With ten interchangeable numbers and flags, a positional argument here
    would be unreadable as well as fragile.
    """

    # Power must agree exactly by default. A tolerance is available as an explicit
    # opt-in, expressed as a percentage of the reference figure, but no value for
    # it can be derived from the supplied official definitions. Any non-zero
    # default could be fitted to one model's records rather than to a general
    # property of the data. Where a registry does carry a known
    # systematic offset for a model, that belongs in a correction table reviewed
    # with the data owner, not in a global allowance.
    power_tolerance_pct: float = 0.0
    # Triage only, and deliberately separate from the tolerance above: this band
    # never makes a candidate compatible, earns no points and cannot accept a
    # row. It only marks a rejected candidate as close enough that the gap is
    # explicable by rounding, so the review queue can name the likely kType.
    #
    # Absolute kW rather than a percentage, because integer rounding error does
    # not scale with magnitude: it is +/-0.5 kW at 40 kW and at 300 kW alike. A
    # percentage band is therefore simultaneously too tight on small engines and
    # too loose on large ones. One kW is the whole of the rounding explanation --
    # two sources rounding the same underlying figure to integer kW can differ by
    # at most 1 -- so a wider band is no longer a rounding allowance but an
    # assumption that the catalogues disagree about the value itself.
    #
    # The cost of widening is measurable: two sibling kTypes become jointly
    # eligible when their catalogue gap is at most twice the band. In the NZ
    # reference exactly one pair of otherwise identical kTypes sits within 2 kW
    # (Ford Capri 15158/15159, 41 and 39 kW), so 1 kW puts one pair in reach and
    # 2 kW puts three there, for no additional coverage in the observed data.
    power_triage_kw: float = 1.0
    use_identifiers: bool = True
    # Diagnostic score settings are retained for sensitivity analysis. They do
    # not govern the default dominance selector and are not exposed by the CLI.
    accept_score: float = 35.0
    min_margin: float = 12.0
    use_scoring: bool = True
    year_mode: str = 'gate'
    year_weight: float = 5.0
    use_vin_helper: bool = True
    # Candidate evidence is an audit artefact, not an input to any decision.
    # 'all' keeps every compared candidate; 'unresolved' keeps them only for
    # rows that need review, plus the selected candidate of accepted rows;
    # 'selected' keeps only the accepted candidate. Retention never changes a
    # decision, a score or a status -- only what is written out.
    evidence: str = 'all'
    # Decide each distinct decision key once and replay the outcome for every
    # row that shares it. Pure caching: see pipeline.decision_key for the
    # completeness obligation that makes it sound.
    reuse_identical_rows: bool = True
    # 'dominance' compares the sets of Annex I criteria each candidate agrees
    # with, and reads none of the four field weights, four group caps, threshold
    # or margin -- none of which is grounded in anything, as scoring.json says of
    # itself. It is the default because a weighted total asserts magnitudes and a
    # commensurability between them that no cited source establishes, and because
    # the two selectors agree on what they accept far more often than the weights
    # would suggest.
    #
    # On the supplied catalogue pair the two selectors return the same outcome on
    # 106 of 112 rows (94.6%). Every difference is dominance accepting where score
    # refuses -- the six X-Trail hybrids -- and **no row is ever reassigned from
    # one kType to another by the choice of selector**, which is the property that
    # matters: the selectors differ in how much evidence they demand, not in which
    # vehicle they think they are looking at. Reproduce with
    # Policy(selection='score') against the default.
    #
    # The percentage is quoted for this pair only. An earlier revision of this
    # comment cited three figures for three catalogue pairs without naming them,
    # which is not reproducible from anything in this repository; it has been
    # replaced by the one measurement a reviewer can rerun from the supplied data.
    #
    # 'score' retains the weighted total, for the reason --rules-only retains the
    # policy that predated scoring: so the contribution of a mechanism can be
    # measured rather than assumed. It decides nothing by default.
    selection: str = 'dominance'

    def validate(self) -> None:
        """Reject an unusable policy before a single row is read."""
        import math

        if not math.isfinite(self.power_tolerance_pct) or not 0 <= self.power_tolerance_pct <= 100:
            raise ValueError('Power tolerance percentage must be finite and between 0 and 100')
        if not math.isfinite(self.power_triage_kw) or self.power_triage_kw < 0:
            raise ValueError('Power triage band must be finite and non-negative')
        # Bounded by the real maximum, not a nominal 100: the caps define the
        # scale, and a threshold above their sum would accept nothing at all.
        attainable = attainable_score()
        for name in ('accept_score', 'min_margin'):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 <= value <= attainable:
                raise ValueError(f'{name} must be finite and between 0 and {attainable:g}')
        if self.year_mode not in ('soft', 'gate'):
            raise ValueError('year_mode must be soft or gate')
        if self.selection not in SELECTION_RULES:
            raise ValueError(f'selection must be one of {SELECTION_RULES}')
        if self.evidence not in EVIDENCE_RETENTION:
            raise ValueError(f'evidence retention must be one of {EVIDENCE_RETENTION}')
        temporal_cap = score_rules()['group_caps']['temporal']
        if not math.isfinite(self.year_weight) or not 0 <= self.year_weight <= temporal_cap:
            raise ValueError(f'year_weight must be finite and between 0 and {temporal_cap:g}')


@lru_cache(maxsize=None)
def _rule_file(name: str, subdirectory: str = '') -> dict:
    """Load and cache one packaged JSON rule file."""
    path = RULES_DIR / subdirectory / name if subdirectory else RULES_DIR / name
    rules = json.loads(path.read_text())
    if rules.get('schema_version') != 1:
        raise ValueError(f'Unsupported schema version in {name}')
    return rules


# Companion files a registry may carry beside its vocabulary. Both are optional:
# a registry with no VIN layouts decodes no VIN, and one with no SUBMODEL
# profiles parses no trim. Neither absence is an error, because neither is
# something every register has.
REGISTRY_COMPANIONS = ('_vin_rules', '_submodel_profiles')
_ACTIVE_REGISTRY = DEFAULT_REGISTRY


def available_registries() -> tuple[str, ...]:
    """Every registry with a vocabulary file, by name."""
    return tuple(path.stem for path in sorted(REGISTRIES_DIR.glob('*.json'))
                 if not path.stem.endswith(REGISTRY_COMPANIONS))


def active_registry() -> str:
    """Which register the source data is being read as."""
    return _ACTIVE_REGISTRY


def use_registry(name: str) -> None:
    """Select the register for this process, and drop what the last one cached.

    Process-level rather than threaded through every call because the registry
    is a property of the run: one input file comes from one register, and the
    rule tables are loaded once and shared for the whole of it. Selecting the
    same registry twice is a no-op, so the caches survive.
    """
    global _ACTIVE_REGISTRY

    if name == _ACTIVE_REGISTRY:
        return
    if name not in available_registries():
        raise ValueError(f'Unknown registry {name!r}; available: '
                         f'{", ".join(available_registries())}')
    _ACTIVE_REGISTRY = name
    for cached in (registry_file, vocabularies, registry_vocabulary, submodel_rules,
                   known_reference_structures, structures_by_registry_body,
                   registry_columns, registry_identifiers, authority_assigned_vin_prefixes):
        cached.cache_clear()
    from .normalization import submodel_drive_pattern
    from .vin_decoder import _validated_rules
    submodel_drive_pattern.cache_clear()
    _validated_rules.cache_clear()


def vin_rules_path(name: str | None = None) -> Path | None:
    """A registry's VIN layout file, or None where it has none."""
    path = REGISTRIES_DIR / f'{name or active_registry()}_vin_rules.json'
    return path if path.exists() else None


@lru_cache(maxsize=None)
def registry_file(name: str = '') -> dict:
    """One register's vocabulary file, whole, as it is on disk."""
    return _rule_file(f'{name or active_registry()}.json', 'registries')


@lru_cache(maxsize=None)
def catalogue_file(name: str = DEFAULT_CATALOGUE) -> dict:
    """One reference catalogue's vocabulary file, whole, as it is on disk."""
    return _rule_file(f'{name}.json', 'catalogues')


@lru_cache(maxsize=None)
def registry_columns() -> dict:
    """Role -> the column this register records it in.

    The matcher reads roles, never column names. A role names what a field means
    to a decision -- the displacement, the fuel, the year -- and the registry
    file says which of its columns carries it, so a register that spells a field
    differently, or does not publish it at all, needs no code change.
    """
    return registry_file().get('columns', {'values': {}})['values']


def column(role: str) -> str | None:
    """The column name for one role, or None where this register has no such field."""
    return registry_columns().get(role)


def source_field(row, role: str):
    """One row's value for a role, or None where this register has no such field.

    None is the same answer a missing cell gives, and every comparison treats it
    as unknown: no points, no veto. A register that omits a field therefore loses
    the evidence that field carried, and nothing else.
    """
    name = registry_columns().get(role)
    return row.get(name) if name is not None else None


@lru_cache(maxsize=None)
def registry_identifiers() -> dict:
    """Identifier column -> what kind of code it is and what authority it carries.

    Declaration order is comparison and export order.
    """
    return registry_file().get('identifiers', {'values': {}})['values']


def identifiers() -> tuple:
    """Every identifier column, in the order they are compared and exported."""
    return tuple(registry_identifiers())


def identifiers_where(attribute: str) -> tuple:
    """The identifier columns whose declaration sets ``attribute``."""
    return tuple(name for name, entry in registry_identifiers().items() if entry.get(attribute))


def identifiers_of_kind(kind: str) -> tuple:
    """The identifier columns declared to be one kind of code."""
    return tuple(name for name, entry in registry_identifiers().items()
                 if entry.get('kind') == kind)


def decision_columns() -> tuple:
    """Every source column any decision branch reads, in a stable order."""
    roles = tuple(name for name in (column(role) for role in DECISION_ROLES) if name is not None)
    return roles + identifiers()


def required_source_columns() -> tuple:
    """The columns a source file must carry to be read at all."""
    return tuple(name for name in (column(role) for role in REQUIRED_ROLES) if name is not None)


def registry_report_notes() -> tuple:
    """Assumptions the report must state because they are this register's."""
    return tuple(registry_file().get('report_notes', {'values': []})['values'])


def vin_column() -> str | None:
    """The identifier column carrying a VIN, if this register records one."""
    return next(iter(identifiers_of_kind('vin')), None)


def vin_value(row):
    """One row's VIN, or None where this register records none."""
    name = vin_column()
    return row.get(name) if name is not None else None


@lru_cache(maxsize=None)
def authority_assigned_vin_prefixes() -> dict:
    """VIN prefixes the registration authority assigns itself, and its name.

    A VIN under one of these was issued by the register, not by a manufacturer,
    so its characters carry no variant and no production year and it must not be
    read as a structural code. Declared by the registry's VIN layouts; a register
    whose authority assigns no VINs declares none, and the suppression then
    simply does not apply.
    """
    path = vin_rules_path()
    if path is None:
        return {}
    profiles = json.loads(path.read_text())['profiles']
    return {profile['authority_assigned_prefix']: profile.get('authority_label', '')
            for profile in profiles if profile.get('authority_assigned_prefix')}


def authority_assigned_prefix(value) -> str | None:
    """Which authority prefix a VIN carries, or None for a manufacturer VIN."""
    text = str(value or '')
    return next((prefix for prefix in authority_assigned_vin_prefixes()
                 if text.startswith(prefix)), None)


@lru_cache(maxsize=None)
def categories() -> dict:
    """The neutral internal categories, per axis, with which side produces each.

    The interlingua: the only vocabulary a registry file and a catalogue file may
    both name. Each axis maps a category name to the sides declared to produce
    it, so a deliberately one-sided category -- ``lpg`` on the registry side,
    ``petrol_lpg`` on the catalogue side -- is a declaration a test can check
    rather than a silent gap between two files.
    """
    raw = _rule_file('categories.json')
    return {axis: {name: tuple(entry['produced_by'])
                   for name, entry in body['values'].items()}
            for axis, body in raw['axes'].items()}


@lru_cache(maxsize=None)
def vocabularies() -> dict:
    """Value vocabularies, flattened to plain lookup dicts at load time.

    Assembled from the registry file and the catalogue file, and deliberately
    kept in one flat shape: the modules where a mistake is expensive --
    ``evidence``, ``submodel``, ``decision``, ``normalization`` -- read this and
    need not know which file a table came from.
    """
    from .normalization import normalized_text

    registry = registry_file()
    catalogue = catalogue_file()
    # Registry sections are optional, one by one. A register that records no
    # free-text drive wording, no body pairing or no cab wording simply supplies
    # no such vocabulary, and every comparison that reads it stays unknown --
    # which earns no points and vetoes nothing. Requiring them all would make the
    # seam usable only by a register as fully transcribed as the first one.
    drive = registry.get('submodel_drive', {'values': {},
                                            'source_only_tokens': {'tokens': [],
                                                                   'contradicts_category': None}})
    return {
        # Two independent maps into the same neutral fuel categories, one per
        # catalogue. Neither names the other's labels: they meet in
        # categories.json and nowhere else.
        'registry_fuel': registry['registry_fuel']['values'],
        'catalogue_fuel': catalogue['catalogue_fuel']['values'],
        'reference_drive_system': catalogue['reference_drive_system']['values'],
        'submodel_drive': drive['values'],
        # Recognised in the text, deliberately mapped to no category: see
        # submodel_drive.source_only_tokens. They flag a self-contradictory
        # SUBMODEL and are never compared with a candidate.
        'submodel_drive_source_only': drive['source_only_tokens']['tokens'],
        'submodel_drive_contradicts': drive['source_only_tokens']['contradicts_category'],
        # JSON has no tuples; the pair is (fuel family, is hybrid). Split by side
        # for the same reason as the fuel categories above.
        'registry_submodel_fuel': {label: tuple(pair) for label, pair
                                   in registry.get('registry_submodel_fuel',
                                                   {'values': {}})['values'].items()},
        'catalogue_submodel_fuel': {label: tuple(pair) for label, pair
                                    in catalogue['catalogue_submodel_fuel']['values'].items()},
        # Two independent maps into the neutral body categories. Normalised at
        # load time on both sides: these are compared against
        # normalized_text(BODY_TYPE) and normalized_text(Kind_of_structure), so a
        # differently-cased entry would not merely fail to match -- it would read
        # as a contradiction and veto a candidate the vocabulary was written to
        # permit.
        'registry_bodies': {normalized_text(term): category for term, category
                            in registry.get('registry_bodies', {'values': {}})['values'].items()},
        'catalogue_structures': {normalized_text(value): category for value, category
                                 in catalogue['catalogue_structures']['values'].items()},
        # Register values read for the audit note only: how a vehicle entered the
        # fleet, and which published body a SUBMODEL body family corresponds to.
        # Both are registry-internal -- no catalogue value is named by either.
        'import_context': registry.get('import_context', {'values': {}})['values'],
        'submodel_body_families': registry.get('submodel_body_families',
                                               {'values': {}})['values'],
        # Parsed for the audit trail only. cab_configurations records no body
        # restriction: the exclusion it used to carry could not be grounded in an
        # NZTA, TecAlliance or RDM source.
        'cab_tokens': registry.get('cab_configurations', {'tokens': {}})['tokens'],
    }


@lru_cache(maxsize=None)
def registry_vocabulary(name: str = '') -> dict:
    """One register's official field vocabularies, with their cited sources.

    Source of truth for what a register field may contain, cited to the
    publisher's documents named in the file's ``sources`` block. No decision
    reads this: it asserts no correspondence with any reference catalogue, and
    exists so that a reviewer can check a value against the publisher's own
    definition and so that an extract can be validated against the published
    vocabulary.
    """
    raw = registry_file(name)
    # Each published table is optional: a register whose published vocabulary
    # this project has not transcribed records none, and the validator then has
    # nothing to check rather than a table it can wrongly call violated.
    def values(section):
        return raw.get(section, {'values': {}})['values']

    return {
        'sources': raw['sources'],
        'vehicle_types': values('registry_vehicle_types'),
        'body_types': values('registry_body_types'),
        'vehicle_classes': values('registry_vehicle_classes'),
        'motive_power': values('registry_motive_power'),
        # Which body types each vehicle type may carry, per VIRM Table 2-2-8.
        'body_types_by_vehicle_type': {name: set(entry['body_types'])
                                       for name, entry in values('registry_vehicle_types').items()},
    }


@lru_cache(maxsize=None)
def known_reference_structures() -> frozenset:
    """Reference body structures this project has a vocabulary for.

    Purely catalogue-side: the structures the reference catalogue's own key table
    states. A structure outside this set is not one this project can reason
    about, so its absence from a body category says nothing rather than
    contradicting it.

    It used to union those values with whatever the registry-body correspondence
    named, which made a catalogue-side question partly answerable by the register
    -- the coupling this split removes. Nothing is lost: both names that
    correspondence recorded are KT 086 values, because it only ever paired on
    name identity.
    """
    from .normalization import normalized_text

    recorded = {normalized_text(value) for value in catalogue_file()['tecdoc_structure']['values']}
    return frozenset(value for value in recorded if value)


@lru_cache(maxsize=None)
def structures_by_registry_body() -> dict:
    """Registry body -> the catalogue structures sharing its body category.

    Derived, never declared: each side maps into the category independently and
    this composes the two. Nothing on disk states the pairing, which is what
    keeps the registry file free of catalogue values and the catalogue file free
    of registry values. Provided for the audit tools that want the join as a
    table; no decision reads it.
    """
    vocabulary = vocabularies()
    return {body: frozenset(structure for structure, structure_category
                            in vocabulary['catalogue_structures'].items()
                            if structure_category == category)
            for body, category in vocabulary['registry_bodies'].items()}


@lru_cache(maxsize=None)
def submodel_rules() -> dict:
    """SUBMODEL profiles keyed by (make, model), plus the core-field vocabulary."""
    path = REGISTRIES_DIR / f'{active_registry()}_submodel_profiles.json'
    profiles = _rule_file(path.name, 'registries')['profiles'] if path.exists() else []
    return {
        'profiles': {(p['make'], p['model']): (p['id'], set(p['marketing_trims']))
                     for p in profiles},
        # The review vocabulary is country-neutral -- it names the specification
        # an internal fact belongs to -- so it lives in scoring.json beside
        # core_conflicts, which does the same job for evidence keys.
        'core_fields': score_rules()['submodel_core_fields'],
    }


@lru_cache(maxsize=None)
def policy_decisions() -> dict:
    """Who decides each setting that can change an acceptance, and on what basis.

    Declaration only: it holds no value the matcher reads, and changing an entry
    changes no outcome. Its purpose is that a setting resting on a claim about
    the two catalogues cannot sit in the code as an invisible default -- which is
    what the acceptance threshold did while the same principle was being applied
    to the power tolerance. tests/test_policy_register.py fails when a Policy
    field is undeclared or when a declared default drifts from the real one.
    """
    return _rule_file('policy_decisions.json')['settings']


def owner_decisions() -> tuple:
    """The declared settings that are the data owner's to choose, in file order."""
    return tuple(name for name, entry in policy_decisions().items()
                 if entry['decided_by'] == 'data_owner')


@lru_cache(maxsize=None)
def score_rules() -> dict:
    """Score weights, group caps and the conflict-collapsing vocabulary."""
    raw = _rule_file('scoring.json')
    return {
        'field_weights': raw['field_weights'],
        # Compared and vetoed, never scored: the evidence floor already requires
        # them of every candidate that could be accepted. See scoring.json.
        'gate_fields': tuple(raw['gate_fields']['values']),
        'group_caps': raw['group_caps'],
        'group_members': raw['group_members'],
        # Which Annex I level each compared criterion belongs to. Read rather
        # than re-derived: a version criterion is the finer discriminator, and
        # both the tier split and the constraint that no variant-tier field may
        # outweigh a version-tier one come from this table alone.
        'criterion_tier': {field: entry['tier']
                           for field, entry in raw['criterion_tier']['values'].items()},
        'core_conflicts': raw['core_conflicts']['values'],
        'review_conflict_classes': raw['review_conflict_classes']['values'],
        'review_conflict_severity': raw['review_conflict_classes']['severity'],
        'unproposable_conflicts': set(raw['unproposable_conflicts']['values']),
        'submodel_core_fields': raw['submodel_core_fields']['values'],
    }


def attainable_score() -> float:
    """The highest diagnostic support score: the configured group caps' sum."""
    return float(sum(score_rules()['group_caps'].values()))


def core_conflict(field: str) -> str:
    """The independent specification a disagreement really belongs to."""
    return score_rules()['core_conflicts'].get(field, field)
