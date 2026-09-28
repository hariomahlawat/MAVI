# Stage 2 S2c.0 — Baseline Activation Record

**Status:** Baseline activation record for S2c.0. This change activates the decisions already accepted by the merge of PR #115; it introduces no feature code, model, weight, corpus, dependency, runtime or qualification claim.  
**Date:** 2026-09-28  
**Starting main:** `677afb6b73edf436e23f8d275bb95a7d5b3badac` (merge of PR #115)  
**Scope:** S2c.0 only — S2b closure reconciliation, governing-document activation and accountable-owner assignment.  
**Next slice after this record merges:** S2c.1 Task + corpus + labels.

## 1. Why this slice exists

PR #115 merged the independently reviewed S2c implementation plan and its supporting Model Selection Record methodology. Several governing documents deliberately retained the word **Proposed** until a baseline slice formally activated them, and the Stage-2 acceptance register deliberately retained S2b's pre-merge "exact-head CI pending" qualifiers until post-merge evidence was entered.

S2c.0 performs only that authority and evidence reconciliation. It does **not** start model evaluation, corpus collection, annotation, contract v2 implementation, Model Pack creation, Runtime Pack changes or Production promotion.

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

The following planning decisions are therefore activated as governing S2c decisions:

1. ADR-013 learned-model amendment items 8–10:
   - capability adapter boundary;
   - explicit admissibility/abstention plus artefact/pipeline/identity v2;
   - vision Runtime Pack lock is never widened for an attribute model.
2. ADR-014 Development overlay binding note.
3. ADR-014 Model Selection Records note.
4. Qualification-plan protocol revisions R1 and R2.
5. Model Selection Record method v1.

Nothing in this activation selects a model or marks any F/G acceptance row PASS.

## 4. Accountable owners for the next slices

S2c.0 names accountable roles without pretending that specialist determinations have already been performed.

| Area | Accountable owner | Execution / independent role | Required before |
|---|---|---|---|
| Licence and data review (U1/U10) | **MAVI owner** | a designated human licence/legal reviewer records evaluation/use/derivative/redistribution/end-use determinations from primary sources | candidate evaluation in S2c.2; use/packaging in S2c.6 |
| Corpus, footage access and partition custody (U2) | **MAVI owner** | corpus operators/annotators may be delegated; at least two annotators with one independent for the required labelled subset | S2c.1 evidence production |
| 500-camera workload envelope (U9) | **MAVI owner** | engineering measurements/projection are produced by the S2c harness and independently reviewed | protocol freeze in S2c.2 |

The accountable owner may designate named human executors later, but responsibility does not become unowned while those assignments are being made.

## 5. Baseline invariants carried into S2c.1

- MAVI remains domain-neutral and non-commercial; "enterprise-grade" means engineering quality, not commercial use.
- Licence qualification is performed against the declared MAVI deployment profile and exact exercised rights; "free of cost" never implies redistribution permission.
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
| ADR-013 items 8–10 activated | satisfied by this reconciliation |
| ADR-014 overlay/MSR notes activated | satisfied by this reconciliation |
| Qualification revisions R1/R2 activated | satisfied by this reconciliation |
| MSR method v1 activated | satisfied by this reconciliation |
| Licence-review accountable owner named | MAVI owner |
| Corpus accountable owner named | MAVI owner |
| 500-camera workload-envelope owner named | MAVI owner |
| Model selected | **no** |
| Corpus/frozen-test data read | **no** |
| Dependency/model/runtime change | **no** |
| Acceptance F/G status promoted | **no** |

S2c.1 may begin only after this baseline record is merged and its exact-head documentation CI is green.
