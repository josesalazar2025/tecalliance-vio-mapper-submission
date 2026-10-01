 # Full-registry throughput optimization plan

## Objective

Apply the four changes proposed in Appendix A13 without changing the mapping
policy or any vehicle outcome. The performance baseline is the completed
all-years run against the broader eBay-derived reference:

| Baseline measure | Observed |
|---|---:|
| Registry rows | 5,905,376 |
| Prepared reference candidates | 17,756 |
| Rows with a candidate | 3,356,466 (56.84%) |
| Rows with no candidate | 2,523,767 (42.74%) |
| Logical candidate comparisons | 102,587,804 |
| Distinct decision configurations | 1.83 million |
| Rows reusing a decision | 69% |
| Wall time | 3,096.1 seconds (51.6 minutes) |
| Throughput | 1,907 rows/second |

The 365-row supplied-reference run remains a regression case, but it is not the
capacity baseline: its 95.16% no-candidate rate makes it substantially cheaper
than a realistic-sized reference.

## Non-negotiable acceptance contract

Each phase runs behind a feature flag and is compared with algorithm 1.1.0 on
the same immutable source and reference hashes. A phase is merged only when:

1. sorted row-level `ID`, mapped kType, status, review category and reason are
   identical to the baseline;
2. accepted VIO counts by kType are identical;
3. candidate evidence for every evaluated distinct decision is identical after
   deterministic sorting;
4. duplicate, insufficient-information and source-conflict counts are identical;
5. median throughput improves, or the phase demonstrably enables a later phase;
6. the final full run reaches at least 5,000 rows/second, completes in under
   20 minutes and stays below 4 GB peak RSS on the nominated machine.

At 5,000 rows/second, 5,905,376 rows take 1,181 seconds, or 19.7 minutes. The
target therefore requires about 2.6 times the measured baseline throughput.
Performance is reported as the median of three warm runs with machine, worker
count, input hashes and phase timings recorded. Correctness is checked before
performance.

## Phase 0 — freeze the baseline

Before optimizing, add a benchmark manifest and deterministic comparison tool.
The manifest records input hashes, algorithm and rule versions, row and status
counts, accepted kType counts, logical comparison count, phase timings and peak
RSS. The comparison tool hashes sorted semantic outputs rather than file bytes,
so container metadata and row ordering cannot hide or manufacture a difference.

Run the gate at four levels:

- synthetic edge cases for fast development;
- the supplied 111-vehicle pair for the existing golden result;
- the 181,790-row 2020 registry slice for repeatable performance iteration;
- the 5.905-million-row registry with the broader reference for final acceptance.

## 1. Columnar intake

### Finding addressed

The public registry arrives as a wide CSV inside a ZIP and is currently parsed
in 100,000-row chunks. Most source values repeat, while the decision engine reads
only its declared decision fields. Repeated parsing and Python object strings add
per-row cost before candidate evaluation begins.

### Implementation

1. Introduce an ingestion command that reads the official ZIP once and assigns a
   stable source ordinal and synthetic `ID` using the existing convention.
2. Project the declared decision columns, provenance locator and raw values needed
   for audit. Do not discard or rewrite the original source archive.
3. Normalize make, model and typed numeric fields once, using the existing
   normalization functions, and write an execution dataset as Parquet.
4. Use dictionary encoding for repeated text and explicit schemas for nullable
   numeric, Boolean and string fields. Reject schema drift rather than allowing
   inference to change a field type.
5. Prepare the reference into the same execution format, retaining its source
   locator and raw comparison values.

### Validation and measurement

- Round-trip every projected raw value against the source for the 111-row and
  2020 fixtures.
- Assert that normalization outputs match the current runtime normalization.
- Measure ingestion separately from mapping and report warm reuse separately from
  the first conversion. Parquet preparation is a reusable build artifact, not a
  hidden addition to mapper speed.
- Record projected bytes, Parquet bytes, load time and peak RSS.

### Deliverable

An immutable, versioned execution dataset plus schema and provenance manifest.
The existing CSV/XLSX path remains available for small ad hoc runs.

## 2. Bulk candidate gate

### Finding addressed

The broader-reference run found no make/model/year candidate for 2,523,767 rows
(42.74%). Those rows do not need the per-candidate evidence path. With the small
reference the same fast path applies to 5,619,546 rows (95.16%), demonstrating
that its value varies with catalogue coverage.

### Implementation

1. Build a columnar reference index of normalized make, model and
   `Construction_from` year.
2. Classify source conflicts and missing gate fields first. This preserves the
   456 source-conflict and 25,143 insufficient-information outcomes instead of
   incorrectly labelling them as no-candidate rows.
3. Apply the production year rule in a vectorized semi-join: make and model must
   exist and `Construction_from` may not be later than the registry year.
   `Construction_to` remains non-gating, exactly as in algorithm 1.1.0.
4. Materialize the anti-join as the existing `No candidate in reference` outcome,
   with the same review category and reason. Route only the semi-join population
   to candidate evaluation.
5. Preserve counts by make/model/year so a changed reference immediately exposes
   unexpected gate movement.

### Validation and measurement

- Compare gate membership row-for-row with the current `_RowMatcher` candidate
  lookup on all four validation levels.
- Test missing years, normalized aliases, future construction starts and source
  self-conflicts explicitly.
- Report gate time, rows fast-pathed, rows forwarded and false differences.

### Deliverable

A governed fast path that avoids Python candidate handling for 2.52 million rows
in the capacity baseline while preserving every existing outcome.

## 3. Decide each distinct configuration once

### Finding addressed

Only about 1.83 million distinct decision configurations occur in 5.91 million
registry rows. Approximately 69% of rows repeat a decision. The current cache
already reuses identical rows within a matcher lifetime, but chunked full-registry
execution still constructs per-row keys, serializes per-row evidence and can lose
reuse across chunk boundaries.

### Implementation

1. Generate the exact current `decision_key` semantics from the columnar fields,
   including derived engine-token evidence and source-conflict state. Do not
   coarsen the key in this phase.
2. Assign a compact `decision_id` and group the candidate-bearing population by
   that ID. Retain the canonical key alongside any hash so collisions are checked,
   not assumed impossible.
3. Store multiplicity, source ordinals and vehicle IDs separately from the
   canonical decision row.
4. Run the existing decision engine once per `decision_id` and store one compact
   result and one evidence set per decision.
5. Join outcomes back to source ordinals only when row-level output is required.
   Calculate VIO directly from decision multiplicity, while keeping duplicate-ID
   rules unchanged.
6. Expand detailed evidence on demand for review rather than copying identical
   candidate evidence for every repeated vehicle.

### Validation and measurement

- Prove cached and uncached equivalence with the existing tests, then add a test
  where identical decisions cross ingestion chunk boundaries.
- Compare every expanded row with the baseline, not only aggregate counts.
- Report source rows, distinct decisions, multiplicity distribution, decision
  time, expansion time and evidence bytes.
- Treat 1.83 million as a measured work population, not as a promised 69% runtime
  saving: gating, grouping and current cache savings overlap.

### Deliverable

A global decision table and a source-to-decision multiplicity table. This becomes
the single-process production path and the input to parallel execution.

## 4. Partition, execute and join

### Finding addressed

After bulk gating and global grouping, remaining work is independent by normalized
make/model. Arbitrary row partitions would split repeated decisions and duplicate
reference data, weakening the cache and creating nondeterministic audit output.

### Global invariants around the workers

Partitioning uses a global-local-global pipeline; workers do not decide source
identity or catalogue uniqueness.

1. **Global source pass:** group the complete registry by normalized vehicle
   `ID`, using a disk-backed columnar group-by if it does not fit in memory. Mark
   exact copies, choose the stable first source row as canonical, and mark every
   occurrence of an ID whose non-provenance values conflict. Attach
   `duplicate_of`, `duplicate_id_conflict`, `provided_label_conflict` and
   `canonical_record` before any row is routed to a worker. This is the same
   contract implemented by `sources._mark_duplicate_ids` today, but it operates
   across the full input rather than independently inside ingestion chunks.
2. **Global reference pass:** run `prepare_reference` over the complete reference
   before slicing it. This rejects a duplicated kType even when its two rows
   would otherwise land in different partitions, derives production intervals
   once, and applies make/model normalization and approved aliases consistently.
3. **Closed candidate partitions:** route source decisions and reference rows by
   the same normalized make/model key. A worker receives every candidate for its
   assigned keys, not an arbitrary subset. The year gate then filters that
   complete local candidate group exactly as the single-process matcher does.
4. **Global result pass:** join worker results to the source ordinal and assert
   exactly one outcome per input row and one canonical row per normalized ID.
   Recompute `count_in_vio` as `Matched AND canonical_record`, build duplicate
   review tasks across the joined result, and reduce VIO only after this check.

A conflicting ID may contain two different make/models and therefore be routed
to two workers. Both rows already carry `duplicate_id_conflict=True`, so both
workers return the same conflict status and neither can enter VIO. An isolated
worker-side duplicate check would miss this case and is explicitly prohibited.

### Implementation

1. Partition the global decision table by normalized make/model, keeping each
   group and its reference slice together.
2. Measure group cost using decision count and candidate count, then pack whole
   groups into balanced worker batches. Never split a make/model merely to equalize
   row counts.
3. Start with process-based workers because candidate evaluation is Python-heavy.
   Benchmark one, two and four workers before selecting the production default.
4. Give each worker only its reference slice and decision columns. Write partition
   results and evidence as deterministic Parquet fragments rather than returning
   large Python objects to a parent process.
5. Merge by stable source ordinal, join multiplicities back for row output and
   reduce decision multiplicities for VIO.
6. Make each partition idempotent and checkpointed. A failed worker reruns its
   partition without restarting the fleet and without partially publishing output.

### Validation and measurement

- Require identical hashes at one, two and four workers.
- Place an exact duplicate and a conflicting duplicate on opposite ingestion
  chunks; require the same canonical/conflict outcome as an unchunked run.
- Place a duplicated kType under two different reference make/model keys and
  require global reference preparation to reject it before workers start.
- Assert that the union of each worker's reference slices equals the globally
  prepared reference and that no normalized make/model key occurs in two workers.
- Record worker utilization, partition skew, serialization time, merge time and
  peak aggregate RSS.
- Reject a worker count that breaches the 4 GB memory target even if it is faster.
- Test a worker failure and rerun to prove deterministic recovery.

### Deliverable

A deterministic parallel executor with a single-process fallback and resumable
partition outputs.

## Rollout order and decision gates

| Gate | Change under test | Proceed when |
|---|---|---|
| 0 | Baseline harness | Golden outputs and resource measurements reproduce |
| 1 | Columnar intake | Schema and normalized values are identical; load cost is visible |
| 2 | Bulk gate | Gate membership and all early statuses are identical |
| 3 | Global decide-once | Full row expansion and evidence are identical across chunks |
| 4 | Partitioned execution | Results are identical across worker counts and recovery tests |
| Final | Combined full run | ≥5,000 rows/s, <20 minutes, <4 GB, all semantic hashes equal |

If a phase changes an outcome, disable it and retain the last equivalent path.
Do not compensate for a performance regression by loosening matching rules,
dropping audit evidence or suppressing unresolved rows.

## Production observability

Every run should publish:

- input, reference, rule and code hashes;
- rows read, early conflicts, insufficient rows, gated rows and candidate rows;
- distinct decisions, cache reuse and multiplicity percentiles;
- logical candidate comparisons and candidate-count percentiles;
- time and peak RSS for ingest, gate, group, decide, join and write;
- output hashes and status/kType totals;
- worker count, retries and failed partitions.

These measures separate a faster engine from a thinner catalogue or a changed
fleet. Coverage and throughput remain different metrics.

## What this plan does not change

- It does not validate the eBay-derived reference as ground truth.
- It does not change the dominance policy, tolerances, VIN profiles or rulings.
- It does not convert unresolved rows into assignments.
- It does not require XLSX output at full-registry scale.
- It does not claim that the four gains are additive; the combined run decides.
