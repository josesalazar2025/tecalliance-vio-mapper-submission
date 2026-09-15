# Algorithm

## 1. Normalize the inputs

The source adapter maps registry column names to semantic roles such as make, model,
year, displacement, power and fuel. Text, numeric values, structural identifiers and
known vocabulary terms are normalized consistently before comparison.

## 2. Generate candidates

Normalized make and model form the initial candidate pool. A candidate is excluded when
the registry year is earlier than its `Construction_from` year. `Construction_to` is not
a gate because the NZ field may be first-registration year and can therefore be later
than production. Other production-interval relationships remain review context.

## 3. Build three-valued evidence

Each comparable field produces one of three verdicts:

- `agree`: the source supports the candidate;
- `disagree`: the source contradicts the candidate;
- `unknown`: one side lacks enough information.

Unknown evidence supplies neither support nor contradiction. Compared specifications
include capacity, fuel, power, drive, body, engine and variant information. Reviewed
VIN layouts and structural identifiers contribute evidence with recorded provenance.

Manufacturer model-code interpretation is data-driven. Each profile declares an exact
make, model, identifier kind, input pattern, reference column, known code vocabulary,
decision role and sources. The Nissan X-Trail profile extracts `HNT32` from
`CHASSIS7=HNT32-1` and may veto a candidate because its chassis format and model codes
are officially documented. The Mercedes C-Class profile compares the leading value in
`MVMA_MODEL_CODE` with type numbers published in official Mercedes manuals, but NZTA
does not document the composite field's internal format. It is therefore proposal-only:
it cannot veto, satisfy evidence or populate `mapped kType`, and a hint contradicted by
a core specification is not elevated over the other rejected candidates. For `WDD`
C-Class 205 VINs, Mercedes separately documents the next six characters as the
`Grundbaumuster`; the four enumerated values are therefore compared authoritatively
with `Type_design`. Other Mercedes WMIs and unlisted codes remain unknown. Agreeing VIN
and MVMA decodes corroborate; differing decodes stop as an identifier conflict. Adding
another manufacturer or WMI requires a sourced data profile, not a broader regex.

Where a reviewed SUBMODEL profile contains marketing capacity, the matcher parses it
as a decimal and compares it with RDM `Capacity_litre`. Decimal point and comma are
equivalent spellings (`1.5` = `1,5`). If every make/model/year-gated candidate has a
comparable value and the agreement narrows the pool, the agreeing kTypes form a
review-only shortlist. This cannot override exact `CC_RATING`, repair a contradiction,
or assign a kType.

## 4. Reject contradictions

A known contradiction vetoes a candidate. Source self-conflicts, inconsistent duplicate
IDs, conflicting identifiers and VIN/source contradictions are surfaced explicitly
rather than resolved silently.

## 5. Require a unique compatible candidate

Version criteria are capacity, fuel and power; variant criteria are body, engine and
drive. A documented manufacturer model code decoded from a scoped identifier is checked first within the
make/model/year candidate set. A disagreement vetoes that candidate. An agreement can
make the sole compatible candidate sufficient even when an unrelated specification is
missing. If the chassis code is absent, malformed, unsupported or outside the scoped
manufacturer/model profile, every candidate receives `unknown` and the ordinary cascade
continues without a penalty.

Without a documented manufacturer-model-code agreement, acceptance requires sufficient comparable
evidence, at least one variant agreement, and the applicable identifier and
unearned-elimination safeguards. A candidate with more recorded agreements cannot
defeat a compatible sibling whose corresponding values are missing. Exact power
agreement is the default. A one-kilowatt near-power rule is used only to prioritize
review and never makes an assignment.

## 6. Report or defer

Accepted rows receive a kType and enter the partial VIO count once per distinct vehicle
ID. Every other row receives a status, review reason, relevant fields and candidate
evidence. Proposals and triage leads remain unassigned until a reviewer confirms them.

After an unresolved outcome is final, RapidFuzz compares the normalized registry
`SUBMODEL` text with each candidate's `Type_designation`, `Model_design` and
`Type_design`. The recorded similarity is the mean of character ratio and token-sorted
ratio; token-set containment is deliberately not used. Deterministic review tiers come
first. Within a tier, a sole power conflict inside the existing review band leads other
contradictions. Ordinary specification/configuration conflicts precede documented
identity/generation contradictions; within the same class, positive identity agreement
precedes independent conflict count and exact criterion agreements. Text similarity
breaks remaining ties. Similarity never changes an evidence verdict,
compatibility, score, proposal, status or `mapped kType`. Matched rows do not calculate
it, and missing source or reference text yields no score.

The implementation is separated into input adapters (`sources.py`), normalization,
evidence construction, criterion selection, decision safeguards, pipeline orchestration
and reporting. Runtime vocabularies and policy tables live under `vio_mapper/rules/`.
