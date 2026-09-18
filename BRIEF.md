# Mapping NZ vehicle registrations to kTypes

Jose Salazar · algorithm 1.1.0 · supplied extract, run 18 September 2026

**Asked:** map each row of the New Zealand vehicle extract to a TecAlliance kType, and
judge whether automation is worth applying to this step at all.

The assumptions this rests on, including the ones the supplied material does not settle,
are recorded in [limitations.md](docs/limitations.md).

## Approach

Evidence comparison, not prediction. The mapper narrows the catalogue to the same
normalized make and model, compares every remaining candidate against the registry
attributes, rejects known contradictions, and assigns a kType **only when exactly one
compatible candidate remains**.

Missing information stays unknown and never becomes agreement, so a candidate with more
recorded values cannot beat a compatible sibling whose fields are blank. Every unresolved
row names the field it stopped on and quotes both catalogues' values. Where no publisher
states a correspondence between the two taxonomies, I removed it rather than assert my
own judgement as vocabulary — that cost coverage, deliberately.

Deterministic rules rather than a model: both inputs are structured, and the two supplied
labels are far too few to train or calibrate anything.

## Result

**60 of 111 vehicles receive a kType (54.1%).** The other 51 stop with a named reason.
**54.1% is coverage, not accuracy** — two labels cannot establish precision, and the
365-row reference is an extract rather than the catalogue.

Every vehicle in the file is accounted for:

| | |
|---:|---|
| **60** | assigned; the evidence separates exactly one candidate |
| **30** | waiting on two data-owner rulings |
| **7** | a registry recording error: 1491 cc against the 1991 cc every other field supports |
| **14** | no kType exists in the supplied extract at 1996 cc and 157 kW |

**The two rulings.** A one-kilowatt gap — registry 125 kW against catalogue 126 kW on 20
X-Trails, everything else agreeing — where whether that counts as agreement is a question
for the two publishers, not a tolerance for me to set (**+20**). And what TecDoc means by
"Platform/Chassis", the only field separating the two Colorado kTypes (**+10**). Ruled
either way, both apply to every future batch and take the run to 90 of 111. Ninety-seven
is every vehicle for which a kType exists at all.

Scale is not the constraint: the published 181,790-vehicle 2020 NZ register maps in 36
seconds. Correctness is.

## Recommendation

**Do not implement AI for this step.** The prototype uses no model and makes no network
calls, and nothing about the decision in front of you depends on changing that.

1. **Name the owner of the two rulings.** No budget required; 30 vehicles follow.
2. **Approve a capped pilot beside the current process**, with independent expert
   adjudication and no change to published outputs. It answers the only open question:
   are the matches correct, and does total review effort actually fall?
3. **Decide expansion separately**, against criteria agreed *before* results are seen.

Machine learning becomes worth discussing only after the pilot: adjudicated corrections
are the raw material it needs, and none exist today.

---

Detail: [approach](docs/approach.md) · [algorithm](docs/algorithm.md) ·
[limitations](docs/limitations.md) · [workbook](docs/output.md) ·
[performance](docs/performance.md) · [next steps](docs/next-steps.md)
