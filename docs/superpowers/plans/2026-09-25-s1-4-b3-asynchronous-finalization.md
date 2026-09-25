# S1.4 B3 — Asynchronous Vision Completion Finalization

**Date:** 2026-09-25  
**Status:** Proposed implementation plan for owner review  
**Base:** `main@daba6505976e4eb6ba2c17e5110833d1c920095f`  
**Trigger:** S1.4 PR B authoritative Linux B3 evidence at `bb331c6825569b32ed280cfde21d6527071a7fb0`

## 1. Problem

S1.4 B3 has exposed a product-architecture bottleneck rather than a qualification-tooling problem.

At the current completion boundary, `ProcessingResultStore.CompleteAsync`:

1. starts a PostgreSQL transaction;
2. locks the `vision_jobs` row `FOR UPDATE`;
3. validates the completion body and lease;
4. seals every Evidence Set crop and trajectory into the platform-owned evidence root;
5. creates the Track / Observation / Artifact graph;
6. performs EF persistence;
7. allocates the visibility sequence;
8. marks the VisionJob, ProcessingRun and VideoAsset complete;
9. commits the transaction;
10. only then returns to the worker.

The worker HTTP client has a 30 s default request timeout. S1.4 therefore requires at least 2× headroom: worst-case completion ≤ 15 s.

The authoritative Linux B3 run at the 10,000-Track / 50,000-object envelope measured:

- p50 ≈ 104 s;
- max ≈ 190.8 s;
- 50,000 durable evidence publications;
- roughly 100,000 relational rows in the completion graph.

A throwaway experiment reducing redundant directory/fsync work still measured roughly 63–80 s. EF persistence alone consumed approximately 12–15 s. Therefore the existing synchronous design cannot credibly reach the 15 s request bound through local tuning.

This is not a reason to increase the worker timeout or weaken B3. The worker request is carrying work that does not belong on the synchronous request path.

## 2. Decision

Split **completion submission** from **platform finalization**.

The worker remains responsible for producing and staging the bounded, deterministic completion 3.0 result.

The platform completion endpoint becomes responsible only for:

- validating the caller, lease, attempt and body;
- computing/verifying the completion digest using the existing validator;
- durably recording one finalization intent plus a durable copy of the completion manifest;
- fencing the VisionJob so the attempt cannot be leased or completed again;
- returning an acknowledgement to the worker within the existing bounded request envelope.

A platform-owned background finalizer then performs:

- re-validation of the durable manifest and completion digest;
- sealing worker-staged artefacts into the accepted-evidence root;
- relational persistence;
- visibility-sequence allocation;
- atomic publication of the completed run;
- retry/recovery after host/process loss.

The expensive work therefore no longer runs under the worker's HTTP request or under a long-lived `vision_jobs FOR UPDATE` lock.

### Required state

Add an explicit `VisionJobStatus.Finalizing`.

`ProcessingRunStatus` remains `Running` until finalization commits. The run becomes `Completed` only when accepted evidence and the relational graph are authoritative.

The user-facing processing projection should distinguish **Finalizing** from active inference. Do not report the run as Completed early.

## 3. Why this is the smallest sound change

Rejected shortcuts:

### Increase the worker timeout

Rejected. It turns a measured product bottleneck into a configuration workaround and leaves a very long database/file-system critical path.

### Continue fsync micro-optimisation until B3 passes

Rejected. Measurement shows that removing most redundant sync calls is insufficient. It also risks weakening ADR-006 durability for little benefit.

### Seal outside the transaction but keep the HTTP request synchronous

Rejected. The worker still waits tens of seconds/minutes, and process-loss recovery becomes ambiguous without durable finalization state.

### Bulk/parallel rewrite first

Rejected for the first repair slice. Bulk COPY and parallel sealing may improve throughput later, but they are not required to remove the correctness/timeout coupling. Implement the lifecycle split first, measure it, and optimize the finalizer only if operational latency still warrants it.

## 4. Durable finalization intent

Do **not** persist the entire worst-case completion body as a large PostgreSQL JSON column.

Introduce a platform-owned finalization-manifest root, physically separate from worker-writable staging. It is not accepted evidence and is never exposed to operators.

Canonical key:

`finalization/{jobId}/attempt-NNNN/completion.json`

Submission writes one bounded manifest file containing the completion request required for deterministic re-validation. The file is written create-once, with:

- schema version;
- job id;
- attempt count;
- byte length;
- SHA-256;
- completion digest.

The VisionJob persists only the manifest identity/facts required to recover it, for example:

- `FinalizationManifestKey`;
- `FinalizationManifestSha256`;
- `FinalizationManifestSizeBytes`;
- `CompletionDigest`;
- `FinalizationQueuedAtUtc`.

The exact names are an implementation detail; the persisted semantics are not.

The manifest publication follows the same dual-resource failure discipline already established by B4:

- manifest created, DB commit fails with confirmed rollback → compensate the new manifest;
- commit outcome ambiguous → retain the manifest; it is unreferenced and not operator-readable;
- process loss after manifest publication but before DB commit → unreferenced manifest may be janitored later;
- DB commit succeeds → the Finalizing row is the authority.

Do not reuse the accepted-evidence root for the manifest.

## 5. Submission transaction

The synchronous completion request should hold `FOR UPDATE` only for bounded control-plane work.

Under the short transaction:

1. lock VisionJob;
2. verify schema / job id / worker id / lease token / attempt;
3. reject expired or superseded lease;
4. validate the body using the existing `VisionResultValidator`;
5. compute the existing completion digest;
6. handle exact replay:
   - Completed + same digest → existing successful completion response;
   - Finalizing + same digest and same attempt → idempotent accepted/finalizing response;
   - different digest → completion conflict;
7. durably publish the finalization manifest;
8. transition Leased → Finalizing;
9. persist manifest facts + completion digest;
10. commit;
11. return acknowledgement.

No accepted evidence is sealed here.

No Track / Observation / Artifact graph is created here.

No visibility sequence is allocated here.

The transition to Finalizing consumes the worker lease authority. Once committed, that VisionJob cannot be reclaimed by another worker attempt.

## 6. Worker contract

Do not pretend Finalizing means Completed.

Introduce an additive completion-response evolution rather than overloading `CompletedAtUtc`.

Preferred shape:

- the platform continues to accept completion request schema 3.0;
- response contract gains an explicit state, e.g. `finalizing | completed`, under a versioned/additive response shape;
- a newly accepted submission returns Finalizing;
- an exact replay after finalization returns Completed with final counts/time;
- an exact replay while finalization is still pending returns Finalizing.

The Python worker treats a durable Finalizing acknowledgement as successful hand-off. It must **not** delete the current attempt's staging after that acknowledgement; platform finalization/janitor owns cleanup.

The worker may terminate normally after hand-off. It does not poll finalization.

If changing the existing response shape cannot be done safely/additively, introduce a completion response schema 3.1 while keeping the request body at 3.0. Do not silently reinterpret the existing `CompletedAtUtc`.

## 7. Finalizer lifecycle and fencing

Use the established platform `BackgroundService` precedent from Scene Analytics, but keep the capability semantics VisionJob-specific.

A `VisionFinalizationHostedService` in the API host runs a bounded reconciliation/execution loop.

Finalizer ownership must be crash-safe and multi-host safe. Keep the additional state minimal:

- finalization attempt/count;
- claim owner/token hash or equivalent opaque claim;
- claim expiry;
- last error / terminal failure if retries are exhausted.

Claiming uses PostgreSQL `FOR UPDATE SKIP LOCKED` or the repository's established equivalent.

The finalizer's claim is distinct from the worker lease. The worker lease is finished once Finalizing is committed.

A stale finalizer may continue file IO after its claim expires, so publication remains create-once and the final database commit must re-check finalizer ownership before publishing state.

## 8. Finalization algorithm

For one claimed Finalizing VisionJob:

1. read and SHA-verify the platform-owned manifest;
2. deserialize and re-run `VisionResultValidator`;
3. verify the recomputed completion digest equals the VisionJob's stored digest;
4. seal every referenced staged artefact through `IAcceptedEvidenceStore`;
5. retain the accepted-key mapping;
6. build the same Track / Observation / Artifact graph as today;
7. start the short publication transaction;
8. lock/re-check the VisionJob and finalizer claim;
9. confirm status is still Finalizing and digest/attempt match;
10. persist the graph;
11. allocate the completion visibility sequence;
12. mark VisionJob Completed, ProcessingRun Completed and VideoAsset Processed;
13. commit;
14. remove the finalization manifest and eligible staging as best-effort cleanup after authority is committed.

Important: sealing occurs **outside** the final publication transaction.

Because accepted keys are deterministic and create-once, a retry after process loss reuses already sealed identical objects rather than duplicating them.

The final transaction still owns the relational visibility boundary: no Track, Observation or Artifact row is visible before the authoritative completion commit.

## 9. Failure semantics

The architecture must preserve or improve B4 semantics.

### Failure before Finalizing commit

The worker receives failure and may retry under the existing lease rules. A newly created manifest is compensated when rollback is confirmed.

### Process loss after Finalizing commit, before sealing

The background reconciler reclaims Finalizing and starts/restarts finalization from the durable manifest.

### Process loss during sealing

Already-created accepted objects remain unreferenced. Retry reuses/adopts the deterministic accepted keys after integrity verification.

### Sealing integrity failure

Finalization fails closed. No relational graph is published.

This is not a worker retry: the worker has already handed off the result. The VisionJob transitions Finalizing → Failed with a finalization-specific safe error code and the ProcessingRun/VideoAsset failure path is applied consistently.

### Process loss after all sealing, before publication transaction

Retry sees/adopts the sealed objects and publishes once.

### Database commit ambiguity

Keep the current conservative rule: never delete evidence when rollback cannot be confirmed. Exact retry reconciles against the authoritative row/digest.

### Exact duplicate completion POST

- Finalizing + same worker attempt/digest → idempotent Finalizing response.
- Completed + same digest → idempotent Completed response.
- Any different digest → conflict.

## 10. Staging and janitor ownership

The current janitor assumes Completed/Failed are terminal and a Leased attempt may be fenced by a later attempt.

It must learn Finalizing:

- the current Finalizing attempt's staging is **not deletable**;
- older attempts remain deletable under existing fencing rules;
- after Completed/Failed, normal grace-based cleanup applies;
- unknown or inconsistent Finalizing metadata fails closed: preserve and log.

The worker's successful-completion fast-path cleanup must change so a Finalizing acknowledgement never deletes the current attempt.

## 11. Performance contract after the architecture change

Do not simply delete B3's timing gate.

Replace the obsolete synchronous sealing criterion with two independently measured product-quality criteria.

### B3-A — submission latency

Worst-case 10,000-Track / 50,000-object completion submission, using the real validator and durable manifest publication:

- n ≥ 30;
- warm-up excluded;
- ≥ 3 repeats;
- min / p50 / p95 / max;
- real supported Development filesystems;
- both CPU OS variants;
- **max ≤ 15 s**, preserving 2× headroom against the 30 s worker timeout.

This is the direct successor to the current B3 bound.

### B3-B — asynchronous finalization

Measure separately:

- sealing time;
- relational-persistence time;
- final publication transaction time;
- end-to-end Finalizing → Completed;
- claim/recovery after injected process loss;
- lock-hold time for the publication transaction;
- throughput at 10,000 Tracks / 50,000 objects.

Do not invent a finalization latency threshold merely to obtain PASS.

For the first implementation, retain the measured finalization time as an explicit operational baseline and require:

- no worker/request timeout dependency;
- no worker lease dependency;
- bounded finalizer claim with successful recovery;
- no long-lived `vision_jobs FOR UPDATE` across sealing;
- exact eventual completion under the full envelope;
- no partial relational visibility;
- deterministic replay/adoption.

After the first real measurements on the repaired architecture, set an operator-facing finalization SLO only if the evidence justifies it. Do not choose one in advance without a product basis.

## 12. Implementation slices

Keep this repair isolated from S2 work.

### F1 — architecture/contracts/domain

- amend ADR-006 for asynchronous finalization ownership;
- amend S1.4 B3 criterion as §11 above;
- add Finalizing state and domain transitions;
- define the additive completion acknowledgement;
- define finalization-manifest options/root and bounds;
- migrations/configuration;
- domain and contract tests.

No background execution yet.

### F2 — durable submission

- extract today's large completion path into:
  - bounded submission service;
  - reusable finalization executor;
- implement durable manifest publication;
- Leased → Finalizing transaction;
- exact replay semantics;
- worker handling of Finalizing acknowledgement;
- stop worker cleanup of the current submitted attempt;
- submission timing tests.

At the end of F2, no result may be falsely reported Completed.

### F3 — finalizer + recovery

- hosted service;
- claim/reclaim/fencing;
- revalidation;
- seal outside publication transaction;
- existing graph persistence;
- short publication transaction;
- failure transitions;
- janitor Finalizing rules;
- process-loss/replay tests.

### F4 — B3 requalification

On the final merged SHA:

- run B3-A on Linux and Windows;
- run full finalization measurements;
- run commit/process-loss fault matrix;
- rerun all S1 units invalidated by the behavior-bearing changes;
- only then resume B1/B2/B5/disconnected closure work.

Do not optimize database insertion or parallelize sealing in F1–F3 unless measurement after decoupling demonstrates an operational problem independent of the old HTTP timeout.

## 13. Required tests

At minimum:

### Domain

- Leased → Finalizing only under valid current lease/attempt;
- Finalizing cannot be leased/heartbeated/worker-failed;
- Finalizing → Completed;
- Finalizing → Failed;
- exact digest replay rules.

### Submission API

- worst-shape request does not seal accepted evidence synchronously;
- manifest is hash/size bound;
- accepted response does not claim Completed;
- duplicate same digest is idempotent;
- different digest conflicts;
- rollback compensation;
- ambiguous DB commit retains unreferenced manifest;
- request cancellation before commit leaves no authoritative Finalizing state.

### Finalizer

- process loss before first seal;
- process loss mid-seal;
- process loss after sealing before DB publication;
- expired finalizer claim and reclaim;
- stale finalizer cannot publish;
- integrity mismatch fails closed;
- exact retry adopts already sealed objects;
- no partial Tracks/Observations/Artifacts before publication;
- final visibility sequence allocated only at final commit;
- final publication is idempotent.

### Janitor

- Finalizing current attempt preserved;
- older fenced attempts reclaimed;
- Completed/Failed grace behavior unchanged;
- malformed/inconsistent state preserved and logged.

### Worker

- Finalizing acknowledgement ends the attempt successfully;
- current staging is retained after hand-off;
- no fallback to older completion protocol;
- transport timeout still fails safely before acknowledgement.

## 14. Qualification/invalidation consequence

PR #86 has already moved `main` to:

`daba6505976e4eb6ba2c17e5110833d1c920095f`

That commit is not the final S1.4 measured SHA.

The B3 architecture implementation changes behavior-bearing platform, worker and qualification surfaces. Therefore the existing interim evidence in PR #87 remains historical evidence only.

After the final B3 implementation merges, choose that new `main` commit as the measured SHA and re-run every S1 unit required by the S1.4 invalidation map. Do not try to carry forward B4 PASS or the Linux B1 probe merely to save time if the checker says they are invalidated.

## 15. Non-goals

This repair does not:

- change Evidence Set selection/scoring;
- change model/runtime qualification;
- implement S2 attributes;
- add a generic AI-job framework;
- redesign accepted-evidence storage format;
- introduce a new database bulk-ingest package;
- weaken ADR-006 integrity;
- make staged worker files operator-readable;
- declare any existing S1 evidence PASS on the new SHA.

## 16. Acceptance for the architecture repair

The repair is ready for S1.4 requalification when:

1. a worst-case submission no longer seals/persists the 50,000-object graph synchronously;
2. submission satisfies the existing 15 s max bound on both qualified CPU OS variants;
3. Finalizing state is visible and truthful;
4. finalization survives process loss at every boundary above;
5. accepted evidence remains create-once, integrity-verified and platform-owned;
6. relational intelligence becomes visible atomically only at final commit;
7. no long-lived row lock spans sealing;
8. worker staging cannot be deleted while authoritative finalization still needs it;
9. exact replay remains deterministic and conflict-safe;
10. full Task 10 / Quality Gate / S1 fault tests are green.

The architectural objective is not to make the qualification checker green. It is to make the real completion path reliable at the product's declared 10,000-Track envelope.
