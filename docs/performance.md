# Measured performance

Everything below is produced by `vio-mapper-bench`, which runs the ordinary
decision path and times the phases around it. It adds no policy and changes no
outcome. Reproduce any figure with the commands in
[Running the benchmark](#running-the-benchmark).

## Test dataset

The supplied extract is 111 vehicles, which cannot exercise scale. The scale
figures below use the published New Zealand motor vehicle register for 2020:

- <https://wksprdgisopendata.blob.core.windows.net/motorvehicleregister/VehicleYear-2020.csv>
- 181,790 vehicles, 39 columns.
- One column was added locally: `ID`, a unique row identifier, because the
  mapper keys every result, duplicate check and VIO count on a distinct vehicle
  ID and the published file carries none. Nothing else was altered. The local
  file is therefore named `VehicleYear-2020-ID.csv`.

The file is not kept in the repository: it is 48 MB, it is reconstructable, and
versioning a derived copy of a public dataset is not useful. Rebuild it with:

```sh
curl -O https://wksprdgisopendata.blob.core.windows.net/motorvehicleregister/VehicleYear-2020.csv
uv run python -c "
import pandas as pd
d = pd.read_csv('VehicleYear-2020.csv', low_memory=False)
d.insert(0, 'ID', range(1, len(d) + 1))
d.to_csv('VehicleYear-2020-ID.csv', index=False)
"
```

This is a *throughput and stability* test, not a coverage test. It is measured
against the supplied 365-row TecAlliance reference extract, so 91.6% of rows
match no make and model in the catalogue at all and exit before any comparison.
The 1.4% acceptance rate from this run is an artifact of catalogue coverage and
must never be quoted as a mapping result. Mapping quality is reported only on
the supplied pair, in [approach.md](approach.md).

## Scaling in source rows

Three runs at each size; the median is reported and the spread is the gap
between the fastest and slowest run of the three.

| Source rows | Map time (median) | Spread | µs/row | Comparisons | Marginal memory |
|---:|---:|---:|---:|---:|---:|
| 10,000 | 2.90 s | 3.4% | 290.0 | 15,468 | 73 MB |
| 25,000 | 6.44 s | 0.3% | 257.6 | 41,396 | 189 MB |
| 50,000 | 11.57 s | 1.1% | 231.4 | 81,281 | 371 MB |
| 100,000 | 21.11 s | 2.5% | 211.1 | 157,252 | 763 MB |
| 181,790 | 36.01 s | 4.6% | 198.1 | 285,552 | 1,273 MB |

Cost grows more slowly than volume: 18.2× the rows costs 12.4× the mapping
time, a scaling ratio of about 0.7. Per-row cost falls from 290 to 198 µs.
Run-to-run spread reaches 4.6%, so the ratio is reported to one decimal place
and no finer.

The slices are `head(N)` prefixes, which is only meaningful if the published
file is unordered. It is: across the first 10,000, 50,000 and all 181,790 rows
the share of Toyotas holds at 16.6%, 16.2% and 16.0%, mean first-registration
month at 6.76, 6.75 and 6.76, and the count of distinct territorial authorities
at 66, 67 and 67. Candidate density likewise held between 8.4% and 8.7%.

Two throughput figures are reported because rows whose make and model match
nothing exit before any comparison. Against a catalogue extract those rows
inflate rows-per-second; comparisons-per-second is the figure that survives a
change of catalogue size.

### Why it is sub-linear

`_RowMatcher` caches a decision by decision key and replays it for an identical
row. A real registry contains many repeated vehicle configurations, so the reuse
rate rises with fleet size:

| Source rows | Distinct decision keys | Reuse |
|---:|---:|---:|
| 10,000 | 4,743 | 52.6% |
| 25,000 | 9,383 | 62.5% |
| 50,000 | 15,491 | 69.0% |
| 100,000 | 25,466 | 74.5% |
| 181,790 | 38,977 | 78.6% |

Fitting cost as *unique decisions + per-row overhead* by least squares across
all five measured points gives **351 µs per unique decision and 123 µs per row**
for key construction and evidence serialization. Residuals are under 1.3% at
every point:

| Source rows | Measured | Fitted | Residual |
|---:|---:|---:|---:|
| 10,000 | 2.90 s | 2.89 s | −0.3% |
| 25,000 | 6.44 s | 6.36 s | −1.3% |
| 50,000 | 11.57 s | 11.57 s | −0.0% |
| 100,000 | 21.11 s | 21.20 s | +0.4% |
| 181,790 | 36.01 s | 35.97 s | −0.1% |

Two parameters fitted to five points is a thin fit, and the residuals are within
the run-to-run spread, so it should be read as a decomposition of where the time
goes rather than a predictive model.

### What this does not establish

This is scaling in *source rows against a fixed reference*. It says nothing
about scaling in catalogue size. A full TecAlliance catalogue would enlarge the
candidate group behind each make and model, raising the per-decision cost and
worsening the tail already visible in the 245-candidate Mercedes rows. The
sub-linearity above comes from registry duplication, not from candidate
comparison being cheap.

## Where the time goes

Full 181,790-row run, by phase. This is a single run of each configuration; the
dominant mapping phase varies by at most 4.6% across repeats, as above.

| Phase | CSV output | With XLSX |
|---|---:|---:|
| Load and normalize source | 1.61 s | 1.54 s |
| Load reference workbook | 0.03 s | 0.03 s |
| Map and stream evidence | 36.15 s | 35.86 s |
| Run metadata (hashing) | 0.21 s | 0.21 s |
| Build sheets | 7.48 s | 7.48 s |
| Write result sheets as CSV | 10.05 s | 9.45 s |
| Write result workbook (XLSX) | — | 429.96 s |
| Write performance report | 3.74 s | 3.50 s |
| **Total** | **59.27 s** | **488.03 s** |

Peak RSS is about 1.8 GB on the CSV path and 4.3 GB when the workbook is
written, but peak RSS carries a 508 MB fixed baseline of interpreter, pandas and
reference that is present before a single row is mapped. Net of that baseline,
**memory attributable to the run grows essentially linearly**: 73 MB at 10,000
rows to 1,273 MB at 181,790, a 17.4× increase for 18.2× the rows (ratio 0.96).
Only *time* is sub-linear; memory is not, and capacity planning should use the
marginal figure.

Per-row latency is p50 65 µs, p90 336 µs, p99 1.05 ms, p99.9 9.0 ms, max 82 ms.
The tail tracks candidate-group size but not exclusively — one of the slowest
rows had no candidates at all, so interpreter garbage collection is part of it.
Individual rows should not be over-read.

### The known bottleneck

XLSX serialization is 88% of wall clock and 45× the cost of writing the same
sheets as CSV. The cause is container choice rather than algorithm: at this
volume `Results` carries 181,790 rows and `Review_Detail` 179,197, so the
workbook holds about 360,000 wide rows that are written cell by cell.

The fix is to route row-level sheets to CSV above a row threshold, exactly as
`Candidate_Evidence` already is, and keep the workbook for the sheets a person
reads. That would return a full run to roughly one minute and remove the 4.3 GB
peak.

This is **not implemented**, deliberately. At the 111-row scale of the submitted
deliverable the workbook takes about five seconds and is the correct format, and
the change would affect the workbook guide, the tests and the review UI download
path for no benefit to the submitted result. It is recorded here as a measured
finding with a costed remedy.

## What was optimized, and what was not

Present, each traceable to a measurement from the run above:

- a decision cache keyed on the fields that determine an outcome, reaching 78.6%
  reuse at full scale;
- candidate groups held in a dictionary, so a row is one lookup rather than a
  scan of the reference;
- candidate evidence streamed to CSV above `STREAM_ROW_THRESHOLD` rows, so the
  audit trail never accumulates in memory;
- vectorized duplicate-ID processing;
- review payloads built from prepared indexes rather than repeated scans;
- workbook serialization deferred until the first download in the review UI.

Deliberately absent: parallelism, multiprocessing, native extensions and any
rewrite of the comparison loop. The task brief ranks correctness above
efficiency, and none of the work above changes a single mapping outcome.

## Running the benchmark

```sh
uv run vio-mapper-bench --source VehicleYear-2020-ID.csv --format csv    # skip the workbook
uv run vio-mapper-bench --source VehicleYear-2020-ID.csv --format both   # compare containers
uv run vio-mapper-bench --source VehicleYear-2020-ID.csv --limit 25000   # one scaling point
```

The report is printed and written to `<out-dir>/benchmark_metrics.txt`.
`--trace-malloc` adds a peak Python-heap figure and slows the run. `--limit`
takes a scaling point; the load phase still reads the whole file, so end-to-end
rates from a limited run are not comparable with a full one.

Figures on this page were produced on macOS 26.5 (arm64), Python 3.12.13,
pandas 3.0.5, algorithm 1.1.0. Absolute times are machine-specific; the scaling
ratios are the transferable result.
