# Algorithm

## 1. Normalize the inputs

The source adapter maps registry column names to semantic roles such as make, model,
year, displacement, power and fuel. Text, numeric values, structural identifiers and
known vocabulary terms are normalized consistently before comparison.

## 2. Generate candidates

Normalized make and model form the initial candidate pool. A vehicle year before a
candidate's production start blocks that candidate. A later registry year remains
eligible because the NZ field may mean manufacture year, model year or first
registration year.

## 3. Build three-valued evidence

Each comparable field produces one of three verdicts:

- `agree`: the source supports the candidate;
- `disagree`: the source contradicts the candidate;
- `unknown`: one side lacks enough information.

Unknown evidence supplies neither support nor contradiction. Compared specifications
include capacity, fuel, power, drive, body, engine and variant information. Reviewed
VIN layouts and structural identifiers contribute evidence with recorded provenance.

## 4. Reject contradictions

A known contradiction vetoes a candidate. Source self-conflicts, inconsistent duplicate
IDs, conflicting identifiers and VIN/source contradictions are surfaced explicitly
rather than resolved silently.

## 5. Select by criterion dominance

The default selector compares the sets of criteria each surviving candidate agrees
with. Version criteria are capacity, fuel and power; variant criteria are body, engine
and drive. Acceptance requires a unique dominant candidate, sufficient comparable
evidence, at least one variant agreement, and the applicable identifier and
unearned-elimination safeguards.

Identifier values corroborate specifications and detect conflicts; they do not replace
missing specification evidence. Exact power agreement is the default. A one-kilowatt
near-power rule is used only to prioritize review and never makes an assignment.

## 6. Report or defer

Accepted rows receive a kType and enter the partial VIO count once per distinct vehicle
ID. Every other row receives a status, review reason, relevant fields and candidate
evidence. Proposals and triage leads remain unassigned until a reviewer confirms them.

The implementation is separated into input adapters (`sources.py`), normalization,
evidence construction, dominance selection, decision safeguards, pipeline orchestration
and reporting. Runtime vocabularies and policy tables live under `vio_mapper/rules/`.
