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
distinct vehicle IDs. It accepts 51 distinct vehicles (45.9%) and leaves 60 unresolved.
The two distinct labeled examples agree with the assigned kType, but two examples do
not establish general accuracy.

The recommended next step is an expert-reviewed pilot on a fresh batch. Accepted and
unresolved groups should be adjudicated by a mapping expert before any result affects
published VIO. Measure precision against that adjudication, correction rate, unresolved
rate and reviewer time; expand only if quality and net effort justify it.
