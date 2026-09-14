# Validation and limitations

The repository contains behavioral tests for normalization, evidence semantics,
candidate selection, duplicate handling, source conflicts, identifier safeguards, VIN
rules, reporting and rule-table integrity. Run them with `uv run pytest`.

The implementation and workbook establish reproducibility and traceability. They do
not establish production accuracy:

- Only two distinct supplied records carry labels.
- Acceptance coverage is not precision and is not labor saved.
- Synthetic edge cases demonstrate intended behavior, not real-world prevalence.
- Attribute agreement does not independently prove vehicle identity.
- Missing reference attributes can leave siblings indistinguishable.
- The secondary catalogue used during development shares TecDoc ancestry and is not
  independent ground truth.
- Transmission cannot be checked because the supplied reference lacks that field.
- Policy choices are provisional engineering judgments, not a TecAlliance-published
  matching specification.

Before production use, freeze the policy and have a mapping expert adjudicate a fresh,
representative batch. Record disagreements as unresolved, measure accepted-assignment
precision and review effort, and define ownership for data corrections and rule changes.
