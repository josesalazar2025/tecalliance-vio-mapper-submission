# Validation and limitations

## Assumptions the result rests on

The business framing was left open deliberately, so these are recorded rather than
left implicit. Each is a place where a correction from TecAlliance changes the answer,
and none of them is settled by the material supplied with the task.

- **How much of the mapping is already automated — unknown, and not guessed.** The
  stated motivation is reducing manual mapping effort. That establishes manual effort
  exists; it does not say whether a person touches every vehicle today or only the
  exceptions. Nothing in the recommendation depends on knowing, because the pilot
  measures review effort against whatever the process actually is. But if much of it is
  already automated, the effort available to save is smaller than the coverage figure
  suggests, and that is worth establishing before a pilot rather than during one.
- **The cost of a reviewed vehicle — unknown, and deliberately not invented.** The shape
  of the work is described here; it is not priced. Multiplying an outside estimate by
  111 would have produced a confident number resting on nothing.
- **The reference is an extract, not the catalogue.** 365 rows. Where this submission
  reports that no kType exists for a vehicle — the fourteen Ford Rangers — that is a
  statement about the supplied extract, not a claim that TecAlliance's full catalogue
  lacks them.
- **The two supplied labels are not a test set.** Two records carry a `mapped kType`,
  both the same kType. They are consistency checks, not a basis for measuring accuracy,
  and no figure in this submission is presented as precision.
- **VIO counts distinct vehicle IDs, not worksheet rows.** One exact duplicate is
  retained in the output for audit and counted once.
- **A registry value is not corrected, only reported.** Where the two publishers
  disagree, the row stops and quotes both. Deciding which one is wrong belongs to the
  data owner, and doing it here would hide the disagreement behind an assignment.

The repository contains behavioral tests for normalization, evidence semantics,
candidate selection, duplicate handling, source conflicts, identifier safeguards, VIN
rules, reporting and rule-table integrity: 96 tests and 69 subtests. Run them with
`uv run pytest`.

The pipeline has also been run against the published 181,790-vehicle 2020 New
Zealand register; see [performance.md](performance.md). That run establishes
throughput, memory behaviour and stability on real-world volume and variety. It
establishes nothing about mapping accuracy, and its acceptance rate is an
artifact of the 365-row reference extract rather than a coverage result.

The implementation and workbook establish reproducibility and traceability. They do
not establish production accuracy:

- Only two distinct supplied records carry labels.
- Volume testing is not quality testing; no adjudicated labels exist at any scale.
- The accepted set is 9 decisions, not 60 observations. See below.
- Acceptance coverage is not precision and is not labor saved.
- Synthetic edge cases demonstrate intended behavior, not real-world prevalence.
- Attribute agreement does not independently prove vehicle identity.
- Missing reference attributes can leave siblings indistinguishable.
- Cross-checks during development used a larger TecDoc-derived vehicle list obtained
  through an eBay seller account. It shares the reference's TecDoc ancestry, so it is
  not independent ground truth, and it is login-gated, so it has no reproducible
  locator. It is named here for transparency only: no claim in this submission, and
  no rule in `vio_mapper/rules/`, rests on it.
- Transmission cannot be checked because the supplied reference lacks that field.
- Policy choices are provisional engineering judgments, not a TecAlliance-published
  matching specification.

## Effective sample size, and how to size a pilot

The matcher caches a decision by decision key and replays it for any identical row,
so correctness is perfectly correlated within a key: if a rule is wrong, it is wrong
for every row sharing it. Rows are therefore not independent observations, and
evaluation has to be counted in **distinct decisions**.

On the supplied extract the 60 accepted vehicles come from **9 distinct decisions**,
and all 112 worksheet rows from 18. Adjudicating every accepted row and finding no
error would support a one-sided 95% precision floor of about **0.72** — not the 0.95
that treating 60 rows as 60 observations would imply.

| Distinct decisions adjudicated, no errors | Precision floor supported |
|---:|---:|
| 9 | 0.72 |
| 30 | 0.91 |
| 50 | 0.94 |
| 100 | 0.97 |
| 150 | 0.98 |
| 300 | 0.99 |

Three consequences for a pilot:

- **Sample by decision, not by row.** Decision multiplicity is heavily skewed — in
  the 181,790-vehicle run the 15,270 adjudicable rows contain 483 distinct decisions,
  the commonest covering 835 vehicles while 237 appear once. Reaching 150 distinct
  decisions costs about 1,405 randomly drawn rows, or 150 adjudications sampled by
  decision: roughly a tenth of the expert time for the same statistical power.
- **Stratify by evidence mechanism, not by model.** The Mercedes acceptance rests on
  a VIN `Grundbaumuster` decode and the X-Trail hybrid on a chassis-code veto. Each
  rule is a separate hypothesis with its own failure mode, and a pooled precision
  figure hides which one is broken.
- **Do not spend budget on duplicate review.** Aliasing — two vehicles with identical
  registry evidence that are genuinely different kTypes — is the one failure mode that
  reviewing a second row in the same group could catch. It is not a live risk in this
  population: `decision_key` includes `VIN11`, `MVMA_MODEL_CODE` and `CHASSIS7`
  verbatim, so every row in a group carries a byte-identical manufacturer VIN
  descriptor, and all 246 multi-vehicle decisions in the 181,790-row run are
  VIN-anchored. The only two attribute-only decisions are singletons, where aliasing is
  impossible by definition. Spend the whole budget on breadth across distinct decisions.
  A registry with weaker VIN coverage would need this revisited, and the pilot's
  undeterminable count is what would signal it.

Adjudication also needs three outcomes rather than two: correct, incorrect and
*undeterminable*. Where no catalogue row exists at the recorded specification — the
Ford Ranger group is the example — an expert cannot determine the right kType either,
and recording that as correct or incorrect biases the estimate. Those rows belong
outside the precision denominator, reported separately as a catalogue-coverage
finding. The reference used to settle each row should be recorded too, since a
reviewer comparing the same registry attributes against the same catalogue attributes
is reproducing this matcher rather than testing it.

**The reachable floor is a property of the batch.** `VEHICLE_YEAR` is part of the
decision key, so vintages partition the decision space and share no decisions at all.
The 2020 model-year slice contains 483 distinct decisions among its 15,270 adjudicable
rows; the 2026 slice contains 317; their union is 800 and their intersection is empty.
A batch spanning several model years therefore offers proportionally more, and a
single-vintage batch caps what it can demonstrate — 483 decisions support a floor of
about 0.99 and no more. Count the distinct decisions in the actual pilot batch before
agreeing a precision floor: a floor above what the batch can reach cannot be met by
evidence, only asserted.

Decision keys may also be finer than true decision equivalence, so 9 and 483 are upper
bounds and the effective sample can only be smaller. Because the raw year is keyed,
two otherwise identical vehicles from consecutive model years count as separate
decisions even where they resolve identically; keying on the year-gate outcome rather
than the raw year would raise reuse across a multi-vintage fleet, and is a possible
future optimisation rather than a change made here.

Before production use, freeze the policy and have a mapping expert adjudicate a fresh,
representative batch. Record disagreements as unresolved, measure accepted-assignment
precision and review effort, and define ownership for data corrections and rule changes.
