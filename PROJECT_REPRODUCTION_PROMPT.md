# Project reproduction prompt

You are a senior data engineer building an auditable prototype for TecAlliance. Reproduce and continue developing a system that maps New Zealand government vehicle-registration records to TecDoc **kTypes**.

## Goal

Given:

- `data/nz_gov_data_subset.xlsx` — source vehicle records;
- `data/RDM_CARPARK_NZ_20250801_subset.xlsx` — candidate kType reference data;

produce a deterministic mapping for every source row. Assign a kType only when the available evidence identifies one sufficiently supported, uniquely compatible candidate. Leave uncertain, contradictory, or unsupported rows unresolved and explain exactly why. Multiple vehicles may map to one kType, and some vehicles may have no valid match.

## Product principles

- Optimize for correctness, traceability, and reviewer trust—not maximum match coverage.
- Treat missing data as unknown, never as agreement.
- Reject candidates contradicted by known evidence; never guess through ambiguity.
- Keep acceptance rules separate from review-only hints and fuzzy ranking.
- Use sourced, narrowly scoped manufacturer/VIN/chassis rules. Do not invent taxonomy correspondences.
- Make every decision reproducible: no runtime LLM calls, external APIs, or hidden state.
- Report coverage separately from accuracy. Sparse supplied labels are checks, not adequate ground truth.

## High-level design

Build a Python 3.12 package using pandas, openpyxl, and RapidFuzz, managed with `uv`.

1. Load and strictly validate Excel or delimited source data and the TecDoc reference. Preserve worksheet, row, duplicate, and source-ID provenance.
2. Normalize text, numbers, dates, makes, models, fuels, body styles, drives, engines, and structural identifiers using versioned JSON vocabularies.
3. Generate candidates primarily by normalized make/model and plausible construction year.
4. Compare candidates with three-valued evidence: `agree`, `disagree`, or `unknown`, covering capacity, fuel, power, drive, body, engine, variant, chronology, and any supported identifiers.
5. Veto known contradictions. Accept only a uniquely defensible candidate with enough version and variant evidence. The primary policy should use criterion-set dominance rather than arbitrary weighted totals; retain weighted scoring only as a diagnostic comparison.
6. Detect and surface source self-conflicts, conflicting duplicate IDs, VIN/source conflicts, unsupported identifiers, tied candidates, incomplete evidence, and cases where all candidates are contradicted.
7. Rank unresolved candidates for human review. Fuzzy text similarity and near-power checks may prioritize review but must never change compatibility or assign a kType.
8. Count VIO only for accepted, distinct vehicle IDs; retain duplicate source rows for audit.

Keep input adapters, normalization, evidence extraction, decision policy, reporting, and UI concerns modular. Store configurable policy, registry/catalogue vocabularies, and manufacturer-specific rules as reviewable data files with provenance and integrity checks.

## Required outputs

Provide:

- a CLI (`uv run vio-mapper`) with explicit source, reference, output, and report paths;
- an audit workbook containing a summary, row-level results, unresolved review queues, candidate evidence, accepted VIO counts, rule/policy context, and reproducibility metadata including versions and input/rule hashes;
- a Markdown performance/result report;
- streaming candidate-evidence export for datasets too large for an Excel worksheet;
- a benchmark CLI reporting phase timings, throughput, per-row latency, memory, and outcome distribution;
- a local FastAPI review application that uploads a registry file, runs the fixed default policy, presents summary/review/audit/rules views, shows row-level candidate evidence, and downloads the workbook;
- self-contained pytest coverage for decision behavior, normalization, rule integrity, duplicate handling, provenance, workbook/API contracts, and failure cases;
- concise reviewer documentation covering the approach, algorithm, outputs, UI, limitations, measured performance, and next steps;
- a short executive presentation for a non-technical, AI-skeptical VP, focused on results, risks, unresolved policy decisions, and a staged validation recommendation.

## Baseline behavior to reproduce

For the supplied extract, the reference implementation accounts for 111 distinct vehicle IDs and accepts 60 (54.1% coverage), while preserving one duplicate worksheet row for audit. Unresolved records remain grouped by actionable causes such as a policy ruling, source-data conflict, or absence from the supplied reference. Treat these figures as a regression target only when using the same input files and rule version—not as proof of general accuracy.

The system must remain usable without proprietary workbooks in the repository: tests use synthetic fixtures, rule files ship with the package, generated artifacts and input data stay out of version control, and the application makes no network calls during mapping.

## Acceptance criteria

- Repeated runs with identical inputs and rules produce identical decisions.
- Every source row has a status and human-readable reason; every accepted row has an explicit acceptance route.
- Unknown evidence cannot increase support, contradictions cannot be silently overridden, and review-only signals cannot assign a kType.
- Accepted VIO counts deduplicate vehicle IDs without losing row-level provenance.
- Rule changes are visible, sourced, versioned, and covered by integrity tests.
- CLI, UI, workbook, report, benchmark, documentation, and tests describe the same default policy.
- `uv run pytest` passes from a clean checkout without the proprietary input files.

When extending the project, preserve these invariants first. Add a new registry, catalogue, manufacturer decoder, or policy only through explicit configuration, documented provenance, regression fixtures, and an auditable change in behavior.
