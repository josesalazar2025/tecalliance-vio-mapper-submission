# Approach and result

The prototype treats mapping as an evidence-comparison problem. It first narrows the
TecAlliance reference to the same normalized make and model, compares every remaining
candidate against the available registry attributes, rejects known contradictions,
and assigns only a uniquely supported candidate. Missing information is unknown; it
never becomes agreement. Ambiguity is an outcome rather than a reason to guess.

Structured deterministic rules were chosen because both inputs are structured and the
provided labels are far too sparse to train or calibrate a statistical model. The
decision and its evidence can therefore be reproduced and inspected row by row.

On the supplied extract, the output contains 112 worksheet rows representing 111
distinct vehicle IDs. It accepts 42 distinct vehicles (37.8%) and leaves 69 unresolved.
Nine Nissan X-Trail hybrids are assigned to kType 124055 through the officially sourced
`HNT32` manufacturer-code rule; the alternative `HT32` candidate is vetoed. Missing or
unsupported chassis codes remain neutral. For Mercedes-Benz C-Class, the leading value
of `MVMA_MODEL_CODE` produces a review-only proposal: 18 C 200 saloon rows propose kType
137963 while remaining ambiguous. Seven internally inconsistent 1.5-litre rows instead
produce a Capacity_litre review shortlist; their conflicting 205.380 model-code hint does
not name an incompatible proposal. No Mercedes row is assigned by this rule, and no
Mercedes VIN character is decoded.
The two distinct labeled examples agree with the assigned kType, but two examples do
not establish general accuracy.

The recommended next step is an expert-reviewed pilot on a fresh batch. Accepted and
unresolved groups should be adjudicated by a mapping expert before any result affects
published VIO. Measure precision against that adjudication, correction rate, unresolved
rate and reviewer time; expand only if quality and net effort justify it.
