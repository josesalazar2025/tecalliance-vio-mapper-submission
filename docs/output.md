# Output workbook

The workbook preserves the source population and separates assignments from review
work. Its sheets are:

| Sheet | Purpose |
|---|---|
| `Results` | Every input row, mapped kType when accepted, status, reason and provenance |
| `Candidate_Evidence` | Candidate-by-candidate agreements, unknowns and contradictions |
| `Review_Queue` | Grouped unresolved questions for efficient adjudication |
| `Review_Detail` | Underlying unresolved vehicle rows |
| `Duplicates` | Repeated records and canonical-row handling |
| `VIO` | Counts of accepted distinct vehicle IDs by kType |
| `Summary` | Source, accepted and unresolved totals |
| `Decision_Policy` | The active decision settings relevant to the published result |
| `Metadata` | Algorithm/environment versions and hashes of run-defining inputs |

`mapped kType` is populated only for accepted rows. `proposed_kType` and
`triage_lead_kType` are review aids, not assignments. Unresolved vehicles remain in the
source denominator and never enter the `VIO` sheet.

For unresolved rows, `Candidate_Evidence` records `review_rank` and the
`text_similarity_*` audit fields. Candidate order first respects deterministic standing,
promotes sole near-power conflicts, then places ordinary specification/configuration
conflicts before documented identity/generation contradictions. Positive identity
agreement breaks otherwise equal conflict classes before independent conflict counts
and exact criterion agreements; text similarity is a later tie-breaker. The
`review_*conflict*` and `review_identity_agreements` fields expose that ordering.
The score is neither matching evidence nor a probability and cannot populate any kType
result field. Its normalized source and reference strings and method name are exported
beside the score.

The output workbook is supplied separately because its row-level evidence contains
information derived from the proprietary input files.
