# Throughput validation after interrupted full run

Checked on 2026-09-23 after the prior full run ended during macOS restart.

## Recovered inputs

The official full NZ archive and eBay workbook were restored and verified against
the recorded SHA-256 hashes:

| Input | SHA-256 |
|---|---|
| `Fleet-data-all-vehicle-years.zip` | `fca6cc7d3c706d04779e4d73bc429040c8be666516eaa163ce9f079dafc27d3b` |
| `eBay-AU_Master_Vehicle_List_202607.xlsx` | `fbf76d65bc34e19adc265b8368a8a5450e7d50f7eae375a20eb89a9332215cad` |

The archive, adapted eBay reference and prepared Parquet execution dataset are
stored under ignored `data/full_registry_capacity/` so a restart does not remove
them. Preparation produced 5,905,376 source rows and 17,756 reference candidates.

## Checks completed

- Full test suite: passed.
- First 5,000 registry rows, baseline versus optimized single-process path:
  identical row-level ID, mapped kType, status, review category, reason and VIO
  flag; identical sorted candidate evidence. Baseline decision run: 16.70 s;
  optimized: 14.16 s. This single slice is not a median performance benchmark.
- Streaming gate check across all 5,905,376 rows: 3,356,466 candidate-bearing
  rows, exactly matching the recorded eBay baseline. The remaining 2,548,910
  rows include no-candidate and insufficient-information outcomes, which this
  gate-only check does not adjudicate.

## Implementation and correctness

The bounded executor partitions the prepared source by normalized make, model
and year into 512 resumable disk buckets. Equal decision keys remain in one
bucket; every bucket sees the complete prepared reference. It groups identical
decisions, bypasses candidate lookup for rows proved to have no candidate,
streams compact evidence to Parquet fragments, and links that evidence by
`(bucket_id, decision_id)`. Its checkpoint signature includes source, reference,
policy, code and rule hashes. The ordinary `run` path remains for smaller data.

An audit caught an initial ZIP intake defect: `source_ordinal` restarted at zero
after every 250,000-row chunk. That attempt was discarded. The corrected
execution schema assigns archive-wide ordinals and rejects the flawed schema.
The corrected full source is `data/full_registry_capacity/execution-v3`.

The independent bounded audit found each of the 5,905,376 source ordinals
exactly once, valid evidence links across 512 buckets and 19,416,921 compact
evidence rows. The full aggregate matches the recorded algorithm 1.1.0 eBay
baseline: 3,356,466 candidate-bearing rows, 102,587,804 logical comparisons,
429,287 accepted rows and every status count. It found 1,827,371 distinct
decision configurations. The original baseline's per-row output was lost in
the restart, so `scripts/validate_full_baseline.py` recomputed algorithm 1.1.0
on the same immutable prepared source and reference, one bounded bucket at a
time. Its completed report verifies identical ID, mapped kType, status, review
category, reason and VIO flag on **all 5,905,376 rows**, and identical
candidate evidence on **all 19,416,921 evaluated distinct-decision rows**.
The per-bucket comparisons are checkpointed under
`data/full_registry_capacity/baseline-comparison/`.

To repeat or resume that independent check from the repository root:

```sh
.venv/bin/python scripts/validate_full_baseline.py --workers 2
```

Full value comparisons between the earlier bounded implementation and the
final version, and among all three final runs, found no differences in results
or compact evidence across all 512 buckets. The comparison records are under
`final-benchmark-{1,2,3}/compare-output.json` where applicable.

## Fresh warm benchmark

Machine: arm64 Mac, macOS 26.5.2. Four workers. The prepared execution dataset
and 512 source buckets were reused. Each mapping run started with an empty
output directory and had zero mapping checkpoint hits. This measures mapping,
including bucket reads, decisions, evidence writes and the completion manifest;
archive ingestion and source partition creation are separate reusable steps.
Peak RSS is a conservative upper bound: parent process peak plus the four
largest worker peaks, even if those peaks did not coincide.

| Final run | Seconds | Rows/s | Conservative peak RSS |
|---|---:|---:|---:|
| 1 | 1,106.0 | 5,339 | 3.40 GB |
| 2 | 1,159.1 | 5,095 | 3.32 GB |
| 3 | 1,153.9 | 5,118 | 3.27 GB |
| **Median** | **1,153.9** | **5,118** | **3.32 GB** |

The median meets the plan's 5,000 rows/s, under-20-minute and under-4-GB
requirements. All three runs have the same input, code and rule hashes. The
reported baseline was 3,096.1 seconds and 1,907 rows/s, so the median mapping
time is 2.68 times faster. The final-run manifests and audits are stored under
ignored `data/full_registry_capacity/final-benchmark-{1,2,3}/`.

The baseline comparison is a fresh algorithm 1.1.0 recomputation from the
verified inputs; the original run's row files are still unavailable. It proves
semantic equality to the baseline algorithm on every saved source row and
distinct decision, while the recovered original report supplies the independent
aggregate cross-check.
