# Approach and result

The prototype treats mapping as an evidence-comparison problem. It first narrows the
TecAlliance reference to the same normalized make and model, compares every remaining
candidate against the available registry attributes, rejects known contradictions,
and assigns only a uniquely supported candidate. Missing information is unknown; it
never becomes agreement. Ambiguity is an outcome rather than a reason to guess.

Structured deterministic rules were chosen because both inputs are structured and the
provided labels are far too sparse to train or calibrate a statistical model. The
decision and its evidence can therefore be reproduced and inspected row by row.

The current supplied-extract run contains 112 worksheet rows representing 111 distinct
vehicle IDs. It accepts 60 distinct vehicles (54.1%) and leaves 51 unresolved. There
are 61 matched worksheet rows because one exact duplicate is retained in `Results` for
audit but counted only once in VIO. The accepted population comprises 20 Hyundai Kona
vehicles mapped to kType 129021, 13 Hyundai Tucson vehicles mapped to 115220, 18
Mercedes-Benz C-Class vehicles mapped to 137963, and nine Nissan X-Trail hybrids mapped
to 124055.

The X-Trail hybrid assignment uses the sourced `HNT32` manufacturer-code rule to veto
the `HT32` alternative. The Mercedes assignment can authoritatively compare the
documented six-character `Grundbaumuster` in supported `WDD` C-Class 205 VINs with
`Type_design`; other Mercedes WMIs remain neutral, and the composite `MVMA_MODEL_CODE`
remains proposal-only. The two distinct labeled examples agree with the assigned kType,
but two examples do not establish general accuracy. The 54.1% figure is acceptance
coverage, not measured precision.

Separately from mapping quality, the pipeline has been profiled on the published
181,790-vehicle 2020 New Zealand register: 36 seconds to map, scaling sub-linearly
in source rows because repeated vehicle configurations reuse a cached decision. See
[performance.md](performance.md), which also records the one measured bottleneck,
workbook serialization, and why it is reported rather than fixed.

The recommended next step is an expert-reviewed pilot on a fresh batch. Accepted and
unresolved groups should be adjudicated by a mapping expert before any result affects
published VIO. Measure precision against that adjudication, correction rate, unresolved
rate and reviewer time; expand only if quality and net effort justify it.
