# Mapping NZ vehicle registrations to kTypes — approach and recommendation

Jose Salazar · algorithm 1.1.0 · supplied extract, run 18 September 2026

## What I was asked

Map each row of the New Zealand government vehicle extract to a TecAlliance kType,
and judge whether automation (AI-supported or otherwise) is worth applying to this
step at all.

## What I assumed, and what I refused to assume

The business framing was left open deliberately, so these are stated rather than
buried. Each one is a place where a correction from TecAlliance changes the answer.

- **How much of the mapping is already automated — unknown, and not guessed.** I was
  told the motivation is reducing manual mapping effort. That establishes manual effort
  exists; it does not tell me whether a person touches every vehicle today or only the
  exceptions. Nothing in the recommendation depends on knowing: the pilot measures
  review effort against whatever the process actually is. But if much of it is already
  automated, the savings available here are smaller than the coverage figures suggest,
  and that is worth establishing before a pilot rather than during one.
- **The cost of a reviewed vehicle — unknown, and deliberately not invented.** I can
  describe the shape of the work; I cannot price it. Multiplying my own estimate by
  111 would have produced a confident number resting on nothing.
- **The reference is an extract, not the catalogue.** 365 rows. Where I report that no
  kType exists for a vehicle — the fourteen Ford Rangers — that is a statement about
  the supplied extract, not a claim that TecAlliance's full catalogue lacks them.
- **The two supplied labels are not a test set.** Two records carry a `mapped kType`,
  both the same kType. They are consistency checks, not a basis for measuring accuracy,
  and no figure in this document is presented as precision.
- **VIO counts distinct vehicle IDs, not worksheet rows.** One exact duplicate is
  retained in the output for audit and counted once.

## Approach

I treated mapping as evidence comparison rather than prediction. The mapper narrows
the catalogue to the same normalized make and model, compares every remaining
candidate against the registry attributes, rejects known contradictions, and assigns
a kType **only when the evidence leaves exactly one compatible candidate**.

Three commitments shape every outcome:

- **Missing information stays unknown.** It never becomes agreement, so a candidate
  with more recorded values cannot beat a compatible sibling whose fields are blank.
- **Unresolved is a result, not a failure.** Every row that stops names the field it
  stopped on and quotes both catalogues' values, so a reviewer starts from evidence.
- **Only sourced correspondences are rules.** Where no publisher states a mapping
  between the two taxonomies, I removed it rather than assert my own judgement as
  vocabulary. That cost coverage, deliberately.

I chose deterministic rules over a statistical model because both inputs are
structured and only two supplied records carry labels, far too few to train or
calibrate anything. Every decision is reproducible and inspectable row by row.

## Result

Of 111 distinct vehicles, **60 receive a kType (54.1%)** and 51 stop with a named
reason. Accepted: 20 Kona → 129021, 18 C-Class 2.0P → 137963, 13 Tucson → 115220,
9 X-Trail Hybrid → 124055.

**54.1% is acceptance coverage, not accuracy.** Two labelled records cannot
establish precision, and I am not presenting coverage as quality.

## Thirty more vehicles are blocked by two decisions, not by code

- **A one-kilowatt gap.** Registry 125 kW against catalogue 126 kW on 20 X-Trails,
  everything else agreeing. Allowing the gap leaves exactly one compatible candidate
  per row, but I will not let a tolerance manufacture evidence. Whether a 1 kW
  difference between two publishers *is* agreement is a data-owner ruling. **+20.**

  Worth stating precisely, because it is the whole argument: a different candidate
  (kType 124043) matches the registry's 125 kW *exactly*, along with capacity, fuel
  and drive. It is vetoed only because the VIN says T32 and that kType is the
  previous T31 generation. The choice here is between a right-generation near miss
  and a wrong-generation exact match, not between a tight threshold and a loose one.
- **A body-vocabulary correspondence.** The two Colorado kTypes are identical on
  capacity, power, fuel, drive, engine code and dates; only the body descriptor
  differs, and NZ "UTILITY" maps to no published TecDoc structure. **+10.**

Ruled either way, these take the run to **90 of 111 (81.1%)** and apply to every
future batch.

The remaining 21 are not one residual bucket, and calling them that would hide the
most useful finding in the run:

- **Seven Mercedes C 200 rows are a registry recording error, not a mapping failure.**
  Power, fuel, variant and engine all agree with one kType; only the recorded 1491 cc
  contradicts the 1991 cc every other field on the row points to. Correcting it
  resolves one row outright. The other six also need a Mercedes VIN layout for the
  newer `W1K` manufacturer code, which Mercedes does not publish and TecAlliance may
  already hold. **+1 now, +7 with the layout.**
- **Fourteen Ford Rangers have no answer in the supplied reference.** Registered at
  1996 cc and 157 kW; the extract holds 2184–3198 cc across its 13 Rangers. No expert
  could map these from this data either, and a process that returns a kType for them
  is guessing. This is a catalogue-coverage finding about the reference, not a
  limitation of the mapper.

So the file accounts for itself completely: 60 + 30 + 7 + 14 = 111, and **97 is every
vehicle for which a kType exists at all.**

## Scale

For reference, I tested the pipeline on the published 181,790-vehicle 2020 New Zealand
register and mapped it in **36 seconds**, reaching a complete result set in 59 seconds
when the row-level sheets are written as CSV. Written as a single workbook the same run
takes eight minutes, almost all of it XLSX serialization — the one measured bottleneck,
reported with a costed remedy in `docs/performance.md` rather than fixed, because at the
111-row scale of this deliverable the workbook takes five seconds and is the right format.
Time scales sub-linearly in source rows; memory does not. Volume is not the constraint
here; correctness is.

## Recommendation

**Do not implement AI for this step.** The prototype uses no model and makes no network
calls, and nothing about the decision in front of you depends on changing that.

1. **Name the owner of the two rulings above.** This needs no budget, and 30 vehicles follow.
2. **Approve a bounded pilot beside the current process**, on one representative
   batch with independent expert adjudication and no change to published outputs.
   It answers the only open question: are the matches correct, and does total review
   effort actually fall?
3. **Decide expansion separately**, against quality, effort and cost criteria agreed
   *before* the results are seen.

Machine learning becomes worth discussing only after the pilot, because adjudicated
corrections are the raw material it needs and none exist today. The staged case,
what to build, in what order, AWS infrastructure options, and where a language model does and does not
belong, is in `docs/next-steps.md`.

---

Detail: [approach](docs/approach.md) · [algorithm](docs/algorithm.md) ·
[limitations](docs/limitations.md) · [workbook](docs/output.md) ·
[performance](docs/performance.md) · [next steps](docs/next-steps.md)
