# Stage 2 S2b — Attribute Lifecycle with Fixture Inferencer

**Status:** Implementation plan — cold-reviewed before implementation  
**Date:** 2026-09-28  
**Starting baseline:** `main@406172657599350ecbb27819865ecc9482c6c97d`  
**Governing:** ADR-013, ADR-014, ADR-006, ADR-009, Stage-2 Visual Attributes plan, Stage-2 acceptance register  
**Exit gate:** Stage-2 acceptance D1–D8 PASS using deterministic fixture inference; no real attribute model.

## 1. Objective

Implement the complete Visual Attribute asynchronous lifecycle and transport boundary without introducing a learned attribute model.

S2b proves that MAVI can queue, lease, heartbeat, execute, read authorised accepted evidence, upload bounded prediction evidence, complete/fail with fencing, recover/retry and preserve raw-processing validity in a separate attribute-worker failure domain.

The deterministic fixture inferencer is a test instrument. It must exercise the same worker/platform contracts that S2c real Model Packs will use; no fixture-only shortcut may bypass evidence reads, upload/sealing, fencing or completion validation.

## 2. Non-goals

S2b does **not**:

- introduce person/vehicle learned Model Packs;
- qualify attribute accuracy or operational vocabulary;
- implement Stage-2 attribute search/cursor v4 (S3);
- implement final operator attribute UI (S4);
- promote RTMDet, CUDA or Production qualification;
- alter Component Binding v2 identity rules;
- give Python direct filesystem access to accepted evidence or platform staging;
- turn `VisualAttributeAnalysis` into a generic IntelligenceJob table;
- perform automatic historical backfill;
- supersede an earlier completed analysis after a failed replacement;
- reuse `EmbeddingExtractor` as a generic attribute inferencer abstraction. Remove it if truly unused, or explicitly retain/document it as Stage-5-only groundwork.

## 3. Repository reconciliation before coding

The implementer must begin from current `main`, record the exact SHA, and reconcile this plan against the actual code. Read at minimum:

- ADR-013 §§8–14 and ADR-014;
- `docs/superpowers/plans/2026-09-23-visual-attributes.md`;
- `docs/reviews/2026-09-23-visual-attributes-acceptance.md`;
- VisionJob lease/heartbeat/complete/fail implementation and tests;
- SceneAnalysis claim/retry/supersession implementation and tests;
- accepted-evidence reader/sealing implementation from S1;
- Observation/Track/ProcessingRun persistence and completion contracts;
- current worker HTTP client/transport code;
- current role/component binding and launcher code from S2a;
- `EmbeddingExtractor` declaration/usages.

If current `main` has advanced beyond the baseline, inspect intervening commits before implementation. If a governing ADR and this plan conflict, stop and reconcile documentation rather than silently choosing a third design.

## 4. Architectural boundary

### 4.1 Domain aggregate

Create capability-specific `VisualAttributeAnalysis` with one unit per:

`(ProcessingRun, immutable analysis identity)`.

Identity is exactly the ADR-013 tuple:

- ProcessingRunId;
- attribute schema version/SHA;
- attribute pipeline version;
- aggregation-policy version/SHA;
- ordered capability/model-pack identities;
- parameters SHA-256.

Runtime-pack identity/variant, actual device, platform build and commit are provenance, not analysis identity.

Lifecycle states:

- Queued;
- Running;
- Completed;
- Failed;
- Superseded.

A binding/identity change does not rewrite history. Existing completed analyses remain readable; a newer successful identity may supersede the previous default. Failed replacement work never supersedes a completed predecessor.

### 4.2 Independent process/failure domain

Add/activate an `attributes` worker role as a separate process with independent:

- READY/health state;
- device policy;
- lease/heartbeat;
- provenance;
- crash/OOM/failure containment.

A fixture-worker crash or failed analysis must never invalidate a completed detector/tracker ProcessingRun.

S2b must not assume the worker shares a filesystem or process with the platform. The contract must remain valid for a future remote GPU node.

## 5. Shared asynchronous primitives — extract before third copy

Before implementing the third asynchronous plane, inspect VisionJob and SceneAnalysis for semantically identical infrastructure. Extract/reuse only where semantics genuinely match:

1. lease capability/token generation, constant-time validation and non-echo rules;
2. canonical SHA-256 representation/validation;
3. `FOR UPDATE SKIP LOCKED` claim helper/pattern;
4. idempotent completion-digest verification.

Do not genericise the domain aggregates. VisionJob, SceneAnalysis and VisualAttributeAnalysis retain their own state machines and typed payloads.

Regression tests must prove the extraction does not change existing VisionJob or SceneAnalysis behaviour.

## 6. Persistence and migration

Introduce the S2b persistence required for lifecycle execution, but do not prematurely implement S3 search semantics.

### 6.1 VisualAttributeAnalysis

Persist at least:

- analysis id;
- ProcessingRun id;
- immutable identity fields/fingerprint;
- status;
- attempt count;
- worker id;
- lease expiry;
- lease/fencing material in the established secure form;
- heartbeat timestamps;
- maximum-duration/deadline state;
- completion digest;
- prediction artefact linkage/SHA/size;
- provenance;
- coverage/output counts;
- visibility sequence/supersession linkage needed by the lifecycle contract.

Constraints/indexes must enforce one unit per run + immutable identity and support bounded SKIP LOCKED claims.

### 6.2 Track outcome / final attribute rows

S2b must implement enough typed completion persistence to prove D8 and ADR-013 outcome semantics with the fixture:

- `VisualAttributeTrackOutcome` — `(AnalysisId, TrackId)`, `Analysed | Unavailable`, optional reason;
- final `VisualAttribute` rows — one per applicable `(AnalysisId, TrackId, AttributeType)`, `Observed | Unknown`, nullable value/confidence, supporting Observation required for Observed.

Foreign keys to supporting evidence use Restrict semantics. Per-row model name/version is not authoritative; producer provenance lives on the analysis header.

Do not add S3 query/index optimisation beyond integrity/claim indexes unless measurement demonstrates it is required for S2b execution.

## 7. Queue/reconciliation semantics

A reconciler queues an analysis only for a completed/visible ProcessingRun when an enabled attribute capability identity is resolvable.

Rules:

- no enabled attribute capability → readiness is NotConfigured; do not manufacture a job;
- capability enabled but no applicable Tracks → NotApplicable; do not consume worker attempts;
- otherwise create/reuse exactly one queued unit for `(run, identity)`;
- queue-time identity is frozen from enabled bindings/configuration;
- binding change does not automatically backfill historical runs;
- explicit bounded re-analysis remains a later/API operation unless needed to prove lifecycle tests.

Concurrent reconcilers must not create duplicate units.

## 8. Lease/heartbeat/reclaim/failure semantics

Follow the **VisionJob lease shape**, not SceneAnalysis's in-process execution shape.

Required behaviour:

- claim uses SKIP LOCKED semantics;
- claim increments/sets attempt state and issues a fresh lease capability;
- heartbeat extends an unexpired matching lease;
- completion, failure, evidence reads and prediction upload require Running + matching attempt + active lease;
- expired/mismatched/stale attempts receive conflict semantics and cannot publish;
- reclaim issues a new attempt and new token;
- stale token cannot read evidence, upload predictions, fail or complete;
- maximum analysis duration fails the unit as a whole rather than publishing partial results;
- duplicate identical completion is idempotent according to the established digest rule;
- duplicate completion with a different digest is rejected;
- startup capability/model unavailable leaves units Queued and does not consume attempts.

Lease duration must exceed heartbeat interval by an explicit configured margin and tests must pin that invariant.

## 9. Python-facing HTTP contract

Implement typed endpoints/transport for:

- lease/claim;
- heartbeat;
- evidence read;
- prediction artefact upload;
- complete;
- fail.

Use the reusable envelope defined by ADR-013:

`schemaVersion, jobId, workerId, leaseToken, attemptCount, provenance, payload`.

Capability payloads remain typed.

Lease capability is carried in a header, never URL/query. No response, exception or structured log may echo the token.

Malformed payloads fail closed without advancing lifecycle state.

## 10. Lease-scoped accepted-evidence read

Python must never browse or mount the accepted-evidence root.

The lease identifies permitted Observation descriptors for Tracks in that ProcessingRun, including expected size and SHA-256.

The read endpoint must:

1. validate active lease/attempt;
2. verify requested Observation belongs to a Track in the leased ProcessingRun and is an authorised accepted EvidenceCrop;
3. stream only through `IAcceptedEvidenceReader`;
4. bound the response to recorded `SizeBytes`;
5. expose no listing/search primitive;
6. log unit id, attempt, Observation id, bytes and outcome without lease secrets;
7. terminate/deny reads after cancellation/expiry/reclaim.

The worker independently verifies received size and SHA before decode. Integrity mismatch or inaccessible evidence becomes Track-level `Unavailable` with a deterministic reason; bytes must never be passed to inference after integrity failure.

A foreign Observation, stale lease or mismatched attempt returns conflict/denial with no partial body.

## 11. Prediction artefact upload and sealing

Use one bounded `AttributePredictions` artefact per completed analysis.

### 11.1 Encoding decision

Use **MessagePack only if it is already on the qualified dependency graph on implementation baseline**; otherwise use an existing already-qualified serialization mechanism. S2b must not add a new serialization dependency merely for this artefact.

The document is versioned and self-describing and contains:

- schema id/version;
- analysis identity/fingerprint;
- per-observation fixture outputs/scores;
- aggregation inputs;
- aggregation decisions;
- retained internal outputs allowed by the schema.

Hard cap: existing 64 MiB per-artefact limit. The implementation must reject declared or streamed overflow without unbounded buffering.

### 11.2 Reverse transport

Worker uploads through the active lease; it never writes platform staging directly.

Platform:

- streams into attempt-scoped staging;
- validates declared size/SHA while streaming;
- binds upload to analysis + attempt;
- permits at most the defined artefact contract;
- seals under ADR-006 only as part of successful fenced completion;
- rejects completion when declared descriptor does not match uploaded bytes;
- removes/abandons stale-attempt staging according to existing artefact cleanup patterns.

No prediction artefact becomes accepted/fact-bearing before successful completion.

## 12. Deterministic fixture inferencer

Implement a deterministic fixture inferencer behind the same worker abstraction that S2c will replace with real capability-bound inference.

Requirements:

- deterministic output from fixture/evidence identity, not wall-clock/random state;
- no network;
- no learned checkpoint;
- exercises real evidence download + size/SHA verification;
- produces both Observed and Unknown outcomes;
- supports deterministic Unavailable scenarios via evidence failure fixtures;
- produces a real bounded `AttributePredictions` upload;
- aggregation is deterministic and versioned;
- fixture identity is explicitly Development/test-only and cannot be mistaken for a qualified Model Pack.

Do not add fixture-specific platform endpoints or bypass component/lifecycle contracts.

## 13. Completion transaction and publication

Completion is the atomic publication boundary for an analysis attempt.

Inside the fenced completion transaction:

1. revalidate Running state, attempt and unexpired lease;
2. validate typed payload bounds and referential integrity;
3. validate completion digest/idempotence;
4. validate uploaded prediction artefact descriptor against staged bytes;
5. validate every Track belongs to the ProcessingRun and every supporting Observation belongs to that Track/run;
6. enforce exactly one Track outcome for every applicable Track represented by the fixture contract;
7. enforce exactly one final row per applicable `(Track, AttributeType)` for Analysed Tracks;
8. enforce Observed ⇒ schema-coded non-null value + confidence [0,1] + supporting Observation;
9. enforce Unknown ⇒ null value and no fabricated negative meaning;
10. seal prediction artefact;
11. persist final relational rows/header counts/provenance;
12. mark Completed and advance visibility sequence;
13. supersede a prior default only after the new completion succeeds.

Any validation failure publishes nothing from that attempt.

## 14. Failure isolation and retry

Tests must prove:

- fixture worker crash leaves ProcessingRun valid;
- failure increments/records only the attribute analysis attempt semantics;
- retry/reclaim can subsequently complete;
- stale attempt cannot publish after reclaim;
- failed replacement leaves prior completed analysis fact-bearing;
- cancellation/expiry prevents subsequent evidence read/upload/complete;
- malformed prediction artefact or completion fails without partial rows;
- one Track's inaccessible evidence yields that Track's Unavailable outcome without corrupting other Tracks, unless the unit-level contract itself is invalid.

## 15. Bounds and resource safety

Contract-test at the existing 10,000-Track bound.

Pin explicit limits for:

- Tracks per analysis;
- Observations/evidence descriptors per Track according to Evidence Set contract;
- completion request size;
- prediction artefact ≤64 MiB;
- evidence response exactly bounded by recorded size;
- no unbounded in-memory accumulation of evidence bytes or prediction upload;
- heartbeat/max-duration relationship.

The fixture does not need to make a 10,000-Track test slow; generated descriptors/payloads may be synthetic, but the production validators and bounds must be exercised.

## 16. Security tests

At minimum prove:

- lease token absent from URLs and logs;
- foreign Observation denied;
- Observation from another ProcessingRun denied;
- stale/reclaimed token denied for read/upload/complete/fail;
- expired lease denied;
- hash/size mismatch never reaches inference;
- path traversal/storage-key manipulation cannot escape accepted-evidence abstraction;
- upload over cap is rejected while streaming;
- completion cannot reference another attempt's upload;
- Python worker has no direct accepted-evidence-root/staging dependency.

## 17. Test-first implementation sequence

### S2b.1 — Shared primitives

Write regression tests first; extract lease/SHA/claim/digest primitives without changing existing planes.

### S2b.2 — Domain + persistence + queueing

Add aggregate/entities/migration/reconciler and concurrency/idempotence tests.

### S2b.3 — Lease/heartbeat/fail plane

Implement typed HTTP lifecycle without evidence/predictions first; prove fencing/reclaim/startup-unavailable semantics.

### S2b.4 — Evidence read

Add lease-authorised streaming read and worker-side integrity verification; prove foreign/stale/hash failure cases.

### S2b.5 — Prediction upload/sealing

Add bounded reverse streaming, attempt-scoped staging and completion descriptor validation.

### S2b.6 — Fixture worker + completion

Run deterministic fixture end-to-end through real contracts; publish Track outcomes/final rows/prediction artefact.

### S2b.7 — Resilience/bounds/reconciliation

Run 10k contract bounds, retry/reclaim/cancellation/malformed-output tests, docs reconciliation and cold review.

Each sub-slice must leave the repository green; avoid one monolithic implementation commit.

## 18. Expected repository areas

Exact files must be discovered from current `main`; do not invent parallel layers. Expected areas include:

- platform Domain/Application/Infrastructure persistence for analysis aggregate and shared primitives;
- platform API endpoints for lifecycle/evidence/upload;
- platform tests for lifecycle, persistence, security and accepted-evidence integration;
- `src/vision` worker role/client/fixture inferencer and tests;
- migration under the existing persistence migration directory;
- configuration for bounded lease/heartbeat/max-duration values using existing configuration patterns;
- Stage-2 documentation/acceptance evidence.

Changes to component binding, model manifests, runtime locks, qualification status or real model files are presumptively out of scope and require an explicit architectural explanation.

## 19. Discriminating tests / mutation targets

The final test suite must kill, at minimum, mutations that:

1. accept a stale lease after reclaim;
2. omit attempt-number validation;
3. permit evidence from a foreign ProcessingRun;
4. skip worker-side SHA verification;
5. allow inference after evidence integrity failure;
6. remove prediction upload size cap;
7. permit completion without a matching uploaded artefact;
8. publish relational rows before fenced completion succeeds;
9. supersede prior analysis on failed replacement;
10. consume an attempt when capability/model is unavailable at startup;
11. treat Unknown as Absent/false;
12. permit Observed without supporting Observation;
13. include runtime variant/commit in immutable analysis identity;
14. allow duplicate `(run, identity)` queue units;
15. echo lease token in an error/log;
16. let fixture code bypass the production evidence/upload path.

Record mutation evidence or an equivalent deliberate regression demonstration for each critical guard.

## 20. Local verification

Before opening/declaring the implementation PR ready, run all repository-prescribed checks plus:

- focused S2b platform tests;
- existing VisionJob/SceneAnalysis regression suites affected by shared extraction;
- accepted-evidence tests;
- complete relevant .NET test projects;
- `src/vision` pytest suite;
- repository verification / `verify_repo`;
- frontend/build checks if shared API contracts affect generated/client code;
- migration/model snapshot validation;
- offline/component checks if and only if files under those boundaries change.

Run a cold diff review against the starting baseline after tests are green.

## 21. Exact-head CI and review gate

The implementation PR must remain unmerged until:

- exact-head MAVI Quality Gate is green;
- every path-triggered Stage-2/vision acceptance workflow is green;
- Task 17 is green where triggered/required by changed paths;
- any manually required workflow identified by repository policy is run on the exact head;
- PR is mergeable;
- no unresolved review thread remains;
- no unresolved P1/P2 attributable to S2b remains;
- identity/qualification diff review confirms no accidental S2c/Production/CUDA promotion.

Do not claim a workflow ran if path filters legitimately excluded it; document the filter determination instead.

## 22. D1–D8 exit mapping

S2b is complete only when retained evidence supports:

- **D1** VisualAttributeAnalysis lifecycle independent of ProcessingRun success;
- **D2** shared fencing/hash/claim primitives extracted where semantics match, with no third divergent copy;
- **D3** Python lease/heartbeat/complete/fail + typed transport contract-tested;
- **D4** lease-scoped evidence read and prediction upload authorised/integrity checked with no Python evidence-root access;
- **D5** independent attributes worker process/role with independent READY/device/provenance/failure domain;
- **D6** capability/model unavailable at startup leaves work Queued without consuming attempts;
- **D7** stale attempts, reclaim, retry, cancellation, malformed output and failure isolation pass;
- **D8** prediction-level output sealed as bounded AttributePredictions while final relational rows remain Track-level only.

Update the authoritative Stage-2 acceptance register only from executed evidence. Planned tests are not PASS evidence.

## 23. Cold-review amendments incorporated before implementation

The independent pre-implementation cold review specifically hardened these points:

1. **Fixture parity:** fixture inference may not bypass the production evidence-read/upload path.
2. **Publication atomicity:** prediction artefact and final rows become fact-bearing only through fenced completion.
3. **Startup unavailable:** D6 is a claim/worker-availability condition, not a failed attempt.
4. **Identity discipline:** runtime variant/device/commit remain provenance and cannot create analysis identities.
5. **No generic-job overreach:** shared transport/fencing primitives do not justify a generic intelligence domain table.
6. **Streaming bounds:** evidence and prediction bytes are bounded/streamed; no hidden whole-run byte accumulation.
7. **Replacement safety:** supersession occurs only after successful completion.
8. **S2b/S2c boundary:** no learned checkpoint, model qualification or operational vocabulary enters this slice.
9. **Evidence security:** stale/foreign access is denied before bytes are emitted and tokens are never echoed.
10. **Existing-plane regression:** shared-primitives extraction must be proven behaviour-preserving for VisionJob/SceneAnalysis.

No unresolved architecture P1/P2 remains in this plan. Implementation discoveries that contradict a governing ADR must stop the slice and return to documentation rather than being improvised in code.
