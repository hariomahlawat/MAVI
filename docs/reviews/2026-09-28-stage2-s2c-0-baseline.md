# Stage 2 S2c.0 — Baseline Reconciliation Record

**Status:** Merged through PR #116 at `main@647d8f605d7c29bb6984408cb4d7e87eb5dcc163`, which is the S2c.0 implementation baseline (the text below records the pre-merge reconciliation as written). Baseline reconciliation proposed on the S2c.0 branch. PR #115 is the architecture/planning acceptance event. This record becomes the implementation baseline only when this change passes exact-head CI and merges; it introduces no feature code, model, weight, corpus, dependency, runtime or qualification claim.  
**Date:** 2026-09-28  
**Starting main:** `677afb6b73edf436e23f8d275bb95a7d5b3badac` (merge of PR #115)  
**Scope:** S2c.0 only — S2b closure reconciliation, recording of already-accepted governing decisions, accountable-role assignment and establishment of the implementation baseline on merge.  
**Next slice after this record merges:** S2c.1 Task + corpus + labels.

## 1. Why this slice exists

PR #115 merged the independently reviewed S2c implementation plan and its supporting Model Selection Record methodology. By the wording of those proposed notes/revisions, that merge is the acceptance event. Several governing documents still retained the word **Proposed** and therefore need reconciliation to the already-effective decision. Separately, the Stage-2 acceptance register deliberately retained S2b's pre-merge "exact-head CI pending" qualifiers until post-merge evidence was entered.

S2c.0 performs only that authority/status and evidence reconciliation and establishes the clean implementation baseline when this change merges after exact-head CI. It does **not** start model evaluation, corpus collection, annotation, contract v2 implementation, Model Pack creation, Runtime Pack changes or Production promotion.

## 2. S2b closure evidence (DR1 / DR8a)

S2b merged in PR #114:

- final PR head: `37376fb28e4be181642eace65d09dec7884c550f`;
- merge/main baseline: `f7b03a24aba8b8bd303ed3a93b26622395e94c5f`;
- retained implementation evidence: `docs/qualification/stage2-s2b/implementation-record.md`.

### Exact-head PR evidence

The final PR head completed the required exact-head workflows before merge:

- MAVI Quality Gate run `36403353060` — success;
- deterministic / Windows script validation run `36403353027` — success;
- CPU Ubuntu / Windows runtime qualification run `36403353097` — success.

### Post-merge main evidence

On merged `main@f7b03a24aba8b8bd303ed3a93b26622395e94c5f`:

- MAVI Quality Gate #2150, run `36406745354` — success;
- Task 17 Acceptance Validation #1284, run `36406745355` — success;
- Task 10 Runtime Qualification #807, run `36406745357` — success.

Therefore the S2b closure qualifier "exact-head CI pending" is retired from D1–D8 and E1–E4. Their already-recorded PASS status is not newly created by S2c.0; this record supplies the closure evidence that the acceptance register required.

The deliberate D2 implementation choice remains as recorded in the S2b implementation record: only semantics-identical primitives were extracted; claim SQL and digest logic were not genericised. No generic claim helper or digest verifier is introduced by S2c.0.

## 3. S2c planning acceptance evidence

PR #115:

- final reviewed head: `33a701d0045b6fa8961a10f69189313d60e6111c`;
- merge commit: `677afb6b73edf436e23f8d275bb95a7d5b3badac`;
- MAVI Quality Gate #2159 — success;
- Task 17 Acceptance Validation #1293 — success;
- unresolved review threads at merge: 0;
- final independent review state: no open P1/P2.

The following decisions were accepted by PR #115 and are recorded here as governing S2c decisions; S2c.0 does not approve them a second time:

1. ADR-013 learned-model amendment items 8–10:
   - capability adapter boundary;
   - explicit admissibility/abstention plus artefact/pipeline/identity v2;
   - vision Runtime Pack lock is never widened for an attribute model.
2. ADR-014 Development overlay binding note.
3. ADR-014 Model Selection Records note.
4. Qualification-plan protocol revisions R1 and R2.
5. Model Selection Record method v1.

Nothing in this reconciliation selects a model or marks any F/G acceptance row PASS.

## 4. Accountable owners for the next slices

S2c.0 names accountable roles without pretending that specialist determinations have already been performed. Named human assignees may change over time; the gate-bearing roles below must be assigned before the listed work begins.

| Area | Accountable owner | Execution / independent role | Required before |
|---|---|---|---|
| Licence and data review (U1/U10) | **MAVI Product/Repository Owner** | **Licence Review Owner** — a named human must be designated before S2c.2 candidate evaluation and records evaluation/use/derivative/redistribution/end-use determinations from primary sources | candidate evaluation in S2c.2; use/packaging in S2c.6 |
| Corpus, footage access and partition custody (U2) | **MAVI Product/Repository Owner** | **Corpus Custodian** — a named human must be designated before footage acquisition/partition execution; corpus operators/annotators may be delegated, with at least two annotators and one independent for the required labelled subset | S2c.1 evidence production |
| 500-camera workload envelope (U9) | **MAVI Product/Repository Owner** | **Scale/Performance Evidence Owner** — a named human must be designated before S2c.2 protocol freeze; engineering measurements/projection are produced by the S2c harness and independently reviewed | protocol freeze in S2c.2 |

The accountable owner may designate named human executors later, but responsibility does not become unowned while those assignments are being made.

## 5. Baseline invariants carried into S2c.1

- MAVI remains domain-neutral and non-commercial; "enterprise-grade" means engineering quality, not commercial use.
- Licence qualification is performed against the declared MAVI deployment profile and exact exercised rights; "free of cost" never implies redistribution permission.
- MAVI itself is intended as an open-source solution, but a model's code/weights remain separately licensed artefacts. Non-commercial permission does not imply a right to redistribute model weights with an open-source MAVI release; when redistribution is not granted, only a separately permitted local-acquisition route may be used.
- Scalability up to **500 cameras** remains a standing selection and engineering constraint. Projection evidence is not presented as a physical 500-camera qualification unless executed.
- The S2b lifecycle, fencing, evidence-read boundary, completion protocol, supersession and Unknown/Unavailable semantics remain unchanged.
- The release binding stays unchanged during S2c; learned capabilities use the accepted Development overlay and `developmentOnly` Production fence.
- The frozen qualification test is never used for model selection.
- No model is selected until its MSR selection event executes the accepted protocol.
- Production and CUDA qualification are outside S2c's claims.

## 6. S2c.0 exit check

| Check | Result |
|---|---|
| S2b exact-head evidence retained | satisfied |
| S2b post-merge evidence retained | satisfied |
| ADR-013 items 8–10 accepted | accepted by PR #115; reconciled here |
| ADR-014 overlay/MSR notes accepted | accepted by PR #115; reconciled here |
| Qualification revisions R1/R2 accepted | accepted by PR #115; reconciled here |
| MSR method v1 accepted | accepted by PR #115; reconciled here |
| Licence-review accountable role defined | MAVI Product/Repository Owner accountable; Licence Review Owner must be named before S2c.2 |
| Corpus accountable role defined | MAVI Product/Repository Owner accountable; Corpus Custodian must be named before acquisition/partition execution |
| 500-camera workload-envelope role defined | MAVI Product/Repository Owner accountable; Scale/Performance Evidence Owner must be named before S2c.2 |
| Model selected | **no** |
| Corpus/frozen-test data read | **no** |
| Dependency/model/runtime change | **no** |
| Acceptance F/G status promoted | **no** |

S2c.1 may begin only after this S2c.0 change passes exact-head documentation CI and merges. The merge of this record—not its presence on the branch—establishes the S2c.0 implementation baseline.
