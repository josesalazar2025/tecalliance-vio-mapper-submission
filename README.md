# NZ government vehicle-to-kType mapper

A deterministic Python prototype that maps New Zealand vehicle-register rows to
TecAlliance kTypes. It assigns a kType only when the available evidence separates one
compatible candidate; ambiguous or contradictory rows remain unresolved for review.

Algorithm version: **1.1.0**.

## Reviewer guide

1. Read [the approach and measured result](docs/approach.md).
2. Read [how the algorithm works](docs/algorithm.md).
3. Inspect [the workbook guide](docs/output.md) beside the separately supplied output.
4. Review [limitations and validation](docs/limitations.md).

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
