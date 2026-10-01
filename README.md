# NZ government vehicle-to-kType mapper

A deterministic Python prototype that maps New Zealand vehicle-register rows to
TecAlliance kTypes. It assigns a kType only when the available evidence separates one
compatible candidate; ambiguous or contradictory rows remain unresolved for review.

Algorithm version: **1.1.0**.

## Reviewer guide

Start with **[the one-page brief](BRIEF.md)** — the approach, the result and the
recommendation, for a reader who wants neither code nor caveats first.

1. Read [the approach and measured result](docs/approach.md).
2. Read [how the algorithm works](docs/algorithm.md).
3. Inspect [the workbook guide](docs/output.md) beside the separately supplied output.
4. Review [limitations and validation](docs/limitations.md).
5. See [measured performance](docs/performance.md) for the scale test and profile.
6. See [next steps](docs/next-steps.md) for the staged ML/AI case, if the pilot passes.

## Run

Python 3.12 or later and [uv](https://docs.astral.sh/uv/) are required. Place the two
authorized input files in `data/` using their supplied names:

- `data/nz_gov_data_subset.xlsx`
- `data/RDM_CARPARK_NZ_20250801_subset.xlsx`

Then run:

```sh
uv sync
uv run vio-mapper
```

The command writes:

- `mapped_nz_gov_reviewed.xlsx`
- `mapping_performance.md`

Explicit paths are also supported:

```sh
uv run vio-mapper \
  --source /path/to/source.xlsx \
  --reference /path/to/reference.xlsx \
  --output /path/to/mapped.xlsx \
  --report /path/to/report.md
```

Run the repository tests with:

```sh
uv run pytest
```

## Continuous integration

`.github/workflows/tests.yml` runs the suite on every push and pull request, on
Ubuntu with Python 3.12 and dependencies resolved strictly from `uv.lock`.

It verifies behaviour and contracts, including rule-table integrity: editing a
transcription under `docs/rule-sources/` without updating the `sha256` recorded
beside it in `vio_mapper/rules/` fails the build. That is what keeps *"only
sourced correspondences are rules"* enforceable rather than merely asserted.

It does **not** verify mapping correctness or coverage. The two authorized input
workbooks are proprietary and are not in this repository, so no mapping runs in
CI; the suite is self-contained and passes with `data/` absent, which is the
state of a fresh clone. There is no deployment job, because there is nothing to
deploy — the prototype makes no network calls and publishes no artifact.

## Benchmark

`vio-mapper-bench` times a run phase by phase and reports throughput, per-row
latency, peak memory and the outcome distribution. It runs the ordinary decision
path and changes no outcome.

```sh
uv run vio-mapper-bench --source VehicleYear-2020-ID.csv --format both
```

The prototype maps the published 181,790-vehicle 2020 New Zealand register in 36
seconds and scales sub-linearly in source rows; a complete result set takes 59 seconds
with row-level sheets written as CSV, or about eight minutes as a single workbook. See
[docs/performance.md](docs/performance.md) for the figures, the dataset link and
the known workbook-serialization bottleneck.

### Full-registry execution

The opt-in throughput path keeps algorithm 1.1.0 but changes how work is stored
and scheduled. Prepare the immutable, reusable execution dataset once, then run
one, two, or four closed make/model partitions:

```sh
uv run vio-mapper-throughput prepare \
  --source /path/to/official-register.zip \
  --reference /path/to/reference.xlsx \
  --output-dir execution-data

uv run vio-mapper-throughput run \
  --dataset execution-data \
  --output-dir mapped-run \
  --workers 4
```

For the full 5.9-million-row registry, use the bounded executor. It partitions
the prepared source by make, model and year on disk, then checkpoints each
bucket independently. Rerunning the same command reuses completed buckets:

```sh
uv run vio-mapper-throughput run-bounded \
  --dataset execution-data \
  --output-dir mapped-run-bounded \
  --buckets 512 --workers 2
```

Results and compact candidate evidence are under
`mapped-run-bounded/mapped-buckets/bucket-*/`. The pair of `bucket_id` and
`decision_id` connects a result row to its evidence. The `bounded-manifest.json`
contains completion state and aggregate counts; `complete: true` means every
source row has one result. Use `--max-buckets N` or repeated `--bucket-id N` for
a validation slice. The ordinary `run` command materializes the whole source
and is intended for smaller datasets.

After a full run, verify saved row coverage, status totals and evidence links:

```sh
uv run vio-mapper-throughput audit-bounded \
  --dataset execution-data --output-dir mapped-run-bounded
```

To compare two completed bounded runs, including every saved result and compact
candidate-evidence value:

```sh
uv run vio-mapper-throughput compare-bounded mapped-run-bounded mapped-run-repeat
```

The run writes deterministic Parquet results and evidence, resumable partition
fragments, and `benchmark-manifest.json`. Each phase has an independent switch:
`--no-bulk-gate`, `--no-group-decisions`, and `--no-partitioned`. The ordinary
`vio-mapper` command remains the baseline unless `--execution optimized` is set.
Evidence stays compact at one copy per decision by default; add
`--expand-evidence` for row-level regression comparisons or review exports.

Create a manifest for baseline CSV/Parquet outputs and enforce semantic equality
without depending on row order or container metadata:

```sh
uv run vio-mapper-throughput manifest \
  --results baseline-results.csv --evidence-file baseline-evidence.csv \
  --source /path/to/source.zip --reference /path/to/reference.xlsx \
  --output baseline-manifest.json
uv run vio-mapper-throughput compare \
  baseline-manifest.json mapped-run/benchmark-manifest.json
```

## Local review UI

Install the web dependencies and start the local interface:

```sh
uv sync --extra web
uv run vio-mapper-ui
```

Open `http://127.0.0.1:8000`. The UI uses the same default decision policy and
workbook builder as the CLI. It uploads a registry file for a temporary in-memory
review session; the reference workbook remains local in `data/`. See
[the UI guide](docs/ui.md) for scope and operating limits.

## Repository contents

```text
vio_mapper/         mapping, evidence, decision and reporting code
vio_mapper/benchmark.py  phase timing, throughput and memory profile
vio_mapper/rules/   versioned JSON vocabularies and policy tables
webapp/             local review API and packaged browser interface
docs/               reviewer documentation and rule-source transcriptions
tests/              self-contained behavioral and contract tests
main.py             direct Python entry point
```

The supplied workbooks and generated workbooks are intentionally excluded from Git.
The rule tables required at runtime are included in both the repository and built
Python package.

## Scope

This is a review-assistance prototype, not a production identity service. It makes no
network calls and uses no LLM at runtime. The supplied labels are too limited to
estimate general accuracy, so acceptance coverage must not be presented as precision.
