# Next steps if the pilot is approved

Everything here is **proposed and unimplemented**. It is sequenced so each stage
produces the evidence the next one needs, and each has a criterion that would stop
it. Nothing in the pilot decision itself depends on any of it.

## The constraint that does not move

The system's value is that every assignment can be explained by the evidence that
produced it, and every refusal names the field it stopped on. No addition may take
that away. Concretely:

- **A model never assigns a kType.** Prediction can rank, explain, extract or
  propose. Acceptance stays with the documented rules.
- **Learned output enters the rule tables as a rule, not as a score.** The tables
  already carry `provenance` (`official`, `correspondence`, `dataset_derived`,
  `mixed`), `evidence_status` and `completeness`. A rule induced from adjudications
  enters at a new, *lower* tier — `adjudicated` — and therefore can never override a
  documented correspondence or veto.
- **An induced rule is not a discovered fact.** It carries the adjudication batch,
  the support count and the confidence, so a reviewer can see it was learned from
  *n* human decisions rather than published by NZTA or TecDoc.

## Stage 0 — the pilot itself (no ML)

Expert adjudication of a representative batch, covering both accepted and unresolved
groups. This is not preparation for machine learning; it is the measurement that
decides whether to continue at all. It also produces the **adjudication corpus** —
the first labelled data this problem has ever had.

**Size it in decisions, not rows.** Identical evidence reuses one cached decision, so
rows sharing it carry no additional information; see *Effective sample size* in
[limitations.md](limitations.md). Roughly 150 adjudicated decisions supports a 98%
precision floor and covers the rules behind about 97% of the vehicles in the
adjudicable population.

**The reference must be independent of this matcher.** A reviewer who settles a row by
comparing the same registry attributes against the same catalogue attributes is running
the algorithm by hand: agreement then measures reproducibility, not correctness. Record
which tier settled each row —

1. **Authoritative in-house vehicle identification**, where TecAlliance holds it. This
   derives a kType by manufacturer VIN semantics rather than attribute comparison, so it
   is genuinely independent. The registry supplies the full type-bearing VIN content
   (WMI, descriptor section, year and plant) for 79% of rows.
2. **Manufacturer build or homologation records**, for rows tier 1 cannot resolve.
3. **Expert attribute judgement**, last and labelled as such. It shares the algorithm's
   inputs, so precision computed over these rows demonstrates reproducibility only.

Reporting the tiers merged would reintroduce exactly the circularity the project avoids
elsewhere.

**Three outcomes, not two:** correct, incorrect and *undeterminable*. Where no catalogue
row exists at the recorded specification, an expert cannot determine the answer either;
recording that as correct or incorrect biases the estimate. Undeterminable rows belong
outside the precision denominator and are reported separately as a catalogue-coverage
finding.

**Gate:** precision on adjudicated accepted rows meets the floor agreed in advance,
and total review effort falls. **Stop if:** either fails and no specific, bounded
fix is identified.

## Stage 1 — learn from the corrections (classical ML, no language model)

Two things become possible once a few thousand adjudications exist. Both are cheap
and both preserve inspectability.

**1a. Rule induction from adjudications.** Mine the adjudicated decisions for
patterns a rule can express — *"where NZ `BODY_TYPE` is UTILITY and the SUBMODEL cab
code is X, reviewers selected `Kind_of_structure` = Pickup"* — and surface each as a
**proposed rule** carrying its support count, confidence, counter-examples and a
draft provenance note, for the data owner to approve into the rule tables. The
figures are whatever the adjudications turn out to say; none exist yet.
Depth-limited decision trees or a rule learner (RIPPER/CN2) are the right tools —
the output must be a readable condition, not a weight vector.

This is the mechanism that converts reviewer effort into permanent coverage. It is
also what makes the two rulings in the brief the *first* of a class rather than a
one-off.

*Risk to manage:* induced rules inherit reviewer bias and overfit the adjudicated
sample. Each needs held-out validation on a batch it was not mined from, and the
lower provenance tier above keeps it from silently outranking published evidence.

**1b. Learned review ordering.** Replace the RapidFuzz tie-breaker with a ranker
(gradient-boosted trees) trained on which candidate the reviewer actually chose.
Safe by construction — ordering cannot change a status or an assignment — and
measurable directly as time-to-decision per exception.

**Gate:** induced rules survive held-out validation; ranking measurably cuts
reviewer time. **Stop if:** accepted rules do not raise coverage without lowering
adjudicated precision.

## Stage 2 — reviewer assistance (this is where a language model belongs)

For an exception a reviewer has opened, generate a short explanation of the conflict
from the candidate evidence already computed: which fields agree, which contradict,
what each publisher recorded, and what additional information would settle it.

Bounded by construction: it reads the evidence rows for one vehicle, emits
structured output validated against those rows, and has no authority over any
status. It is measured on **reviewer effort and explanation correctness**, never on
mapping accuracy, and it ships behind the same quality gate as everything else.

**Stop if:** checked explanations do not reduce total effort. An assistant that is
merely pleasant to read is a cost.

## Stage 3 — a learned candidate scorer (only if 1 and 2 pay)

A calibrated scorer over candidate pairs, with explicit abstention, shadow-deployed
against the rules for a full release cycle before it influences anything. It needs
configuration-level splits before pair construction, realistic competing negatives,
and held-out *assignment* metrics rather than pair metrics. This is the most
expensive and least certain stage, and it is deliberately last.

## Where a small model fits, and where a large one does

The discriminator is volume and audience, not capability:

> **Per-row and high-volume → deterministic rules or a small classical model.
> Per-exception and read by a human → a language model.**

At 181,790 vehicles a per-row LLM call is indefensible on cost and latency alone.
Across the ~2,600 unresolved exceptions in that same run it is bounded and cheap.

| Workflow step | Volume | Recommendation |
|---|---|---|
| Field normalization, SUBMODEL parsing | per row | Deterministic grammar and sourced profiles. **No model** — these are coded strings, not natural language, and a table is auditable and free |
| Make/model synonym discovery | offline batch | Embeddings *propose*; a human approves a synonym table. Retrieval misses are silent recall loss |
| Review ordering of candidates | per exception | Learned ranker (Stage 1b) |
| Rule induction from adjudications | offline batch | Rule learner (Stage 1a) |
| Explaining an exception to a reviewer | per exception | **LLM** (Stage 2), structured output, validated against the evidence |
| Drafting a proposed rule's provenance note | per proposed rule | **LLM**, human-approved before it enters a rule file |
| Assigning a kType | — | **Never a model** |

**On a fine-tuned SLM specifically: probably not for this data.** The source text is
coded — `ST 2.5P/6CVT/SW/5DR`, `LS RC SC 2.8D/4WD` — and a grammar with a sourced
vocabulary parses it more accurately, more cheaply and more inspectably than any
learned model. An SLM earns its place if TecAlliance extends this to registries
whose fields are genuinely free text, such as dealer-entered descriptions. That is a
different problem, and the decision should be made on that data, not this.

## AWS shape

Mapped onto the platform already in use, extending the deployment sketch in the
presentation appendix:

| Need | Service |
|---|---|
| Frozen, hashed input and evidence snapshots | **S3** |
| Run orchestration: validate → execute → reconcile → publish | **Step Functions** |
| Mapping workers (the existing container, unchanged) | **AWS Batch**, images in **ECR** |
| Adjudication store, queried for rule mining | **S3** + **Glue/Athena** |
| Reviewer interface | **Lambda** + **API Gateway** fronting the existing FastAPI app |
| Training the ranker and rule-induction jobs; versioning and shadow deployment | **SageMaker** training jobs, **Model Registry**, batch transform |
| Exception explanation and rule-note drafting | **Bedrock**, with **Guardrails** on output shape |
| Run, cost and model monitoring | **CloudWatch** |

Bedrock stays off the critical path by design: model throttling must never prevent
mapping from publishing or a reviewer from working unassisted.

## What would make me stop

If Stage 0 shows precision below the agreed floor with no bounded fix, none of the
stages above should be funded — a learned system trained on an unreliable process
inherits the unreliability and hides it behind a score. Coverage is not the goal.
An accurate VIO count with a manageable review queue is.
