# S1.4 B3 — Asynchronous Vision Completion Finalization

**Date:** 2026-09-25  
**Status:** Architecture frozen for implementation after independent review  
**Base:** `main@daba6505976e4eb6ba2c17e5110833d1c920095f`  
**Trigger:** S1.4 PR B authoritative Linux B3 evidence at `bb331c6825569b32ed280cfde21d6527071a7fb0`

## 1. Problem

S1.4 B3 exposed a product-architecture bottleneck rather than a qualification-tooling problem.

Today `ProcessingResultStore.CompleteAsync`:

1. starts a PostgreSQL transaction;
2. locks the `vision_jobs` row `FOR UPDATE`;
3. validates the completion body and lease;
4. seals every Evidence Set crop and trajectory into the platform-owned evidence root;
5. creates the Track / Observation / Artifact graph;
6. performs EF persistence;
7. allocates the visibility sequence;
8. marks the VisionJob, ProcessingRun and VideoAsset complete;
9. commits;
10. only then returns to the worker.

The worker HTTP client has a 30 s default request timeout. S1.4 requires 2× headroom: worst-case synchronous completion ≤ 15 s.

The authoritative Linux B3 run at the 10,000-Track / 50,000-object envelope measured:

- p50 ≈ 104 s;
- max ≈ 190.8 s;
- 50,000 durable evidence publications;
- roughly 100,000 relational rows.

A throwaway fsync-reduction prototype still measured roughly 63–80 s. EF persistence alone consumed roughly 12–15 s. The current synchronous design therefore cannot credibly satisfy the 15 s request bound through local tuning.

The repair must remove the product coupling, not weaken qualification.

## 2. Decision

Split **completion submission** from **platform finalization**.

### 2.1 Worker responsibility

The worker:

- produces the bounded deterministic Evidence Set and completion body;
- stages referenced artefacts under its attempt-scoped staging path;
- submits completion protocol **3.1**;
- receives a truthful durable hand-off acknowledgement;
- does not delete current-attempt staging after a `Finalizing` acknowledgement;
- does not poll finalization.

### 2.2 Platform submission responsibility

The synchronous completion endpoint performs only bounded control-plane work:

- validate caller, lease, attempt and body;
- compute the existing completion digest;
- persist the canonical capability-free semantic finalization payload atomically in PostgreSQL;
- transition the VisionJob from `Leased` to `Finalizing`;
- return within the existing bounded request envelope.

It does **not**:

- seal accepted evidence;
- create the Track / Observation / Artifact graph;
- allocate the completion visibility sequence;
- report the run Completed.

### 2.3 Platform finalizer responsibility

A platform-owned background finalizer:

- claims a `Finalizing` VisionJob using PostgreSQL fencing;
- revalidates the retained completion payload;
- seals worker-staged artefacts outside the final publication transaction;
- persists the relational graph;
- allocates the visibility sequence;
- atomically publishes the run as Completed;
- recovers after host/process loss.

## 3. State model

Add:

`VisionJobStatus.Finalizing`

The lifecycle becomes:

`Queued → Leased → Finalizing → Completed | Failed`

Existing `Leased → Failed` and attempt exhaustion remain.

### 3.1 Ownership

- `Queued → Leased`: ProcessingOrchestrator.
- `Leased → Finalizing`: worker completion submission transaction.
- claim/reclaim while `Finalizing`: platform finalizer lifecycle.
- `Finalizing → Completed`: finalizer publication transaction.
- `Finalizing → Failed`: finalizer deterministic failure or exhausted transient retries.

The finalizer claim is **sub-state**, not another public status.

### 3.2 ProcessingRun and VideoAsset

`ProcessingRunStatus` remains `Running` until final publication.

`VideoAsset` remains in its processing state until final publication.

This avoids rippling a new ProcessingRun status through search, analytics and content queries that already rely on `Completed` as the fact-bearing boundary.

The public status projection must nevertheless expose a distinct phase such as:

`phase = processing | finalizing | completed | failed`

Operators must never see a finished worker represented as still performing inference.

## 4. Durable hand-off: PostgreSQL payload row

The finalization hand-off must be a **single-resource atomic transaction**.

Do not introduce a filesystem finalization-manifest root.

Persist a canonical semantic finalization payload in PostgreSQL as bounded binary content. The retained payload must exclude the authenticated HTTP envelope: never persist the raw `leaseToken`, and do not persist `workerId` inside the payload. Exact replay authentication remains on the `VisionJob` through `LeaseOwner`, `LeaseTokenHash` and `AttemptCount`.

### 4.1 Shape

Introduce a dedicated table/entity conceptually equivalent to:

`VisionFinalizationPayload`

Key:

- `JobId`
- `AttemptCount`

Fields:

- canonical semantic finalization payload bytes (`bytea`), containing only schema/job/attempt/result/provenance/evidence facts required for deterministic re-validation;
- byte length;
- SHA-256 of the retained semantic payload bytes;
- completion digest;
- created/accepted timestamp.

The exact schema names are implementation details.

### 4.2 Bounds

The row is bounded by the existing completion request/body limits.

The current worst-shape evidence is within the existing contract envelope; no new larger completion-body allowance is introduced for this repair.

### 4.3 Persistence discipline

Use bounded raw SQL / binary parameter handling for the large payload path where appropriate. Do not require EF to track or materialize the payload as a large object graph during ordinary status queries. The payload serializer is platform-owned and must omit authentication capabilities (`workerId`, raw `leaseToken`). A discriminating test must prove a recognizable lease token cannot occur in retained bytes.

PostgreSQL/TOAST, WAL, backup/restore and transactional atomicity become the durability mechanism.

### 4.4 Cleanup

The payload row remains until the VisionJob is terminal.

After `Completed` or terminal `Failed`, payload cleanup may occur in its own short transaction.

If cleanup is delayed, the payload is bounded retained garbage, not a correctness failure.

## 5. Completion protocol 3.1

Do not reinterpret the existing 3.0 exchange.

Version the completion **exchange** to 3.1.

### 5.1 Request

The 3.1 request carries the same semantic completion content as 3.0 unless implementation requires a narrowly scoped additive field.

**3.1 is a wire/exchange version, not a new Evidence Set digest version.** The validator maps both completion 3.0 and 3.1 bodies to the existing canonical `CompletionSchema.V3` semantic shape and therefore to the existing domain tag `mavi:vision-completion-digest:v3`. No selector/evidence meaning changed, so inventing digest v4 would be incorrect. Tests must prove byte-equivalent 3.0/3.1 semantic payloads produce the same v3 completion digest after normalization.

The version itself provides the compatibility fence.

The existing platform capability endpoint advertises supported completion versions.

A 3.1 worker must not silently fall back to 3.0.

### 5.2 Response

The 3.1 response explicitly includes state:

- `finalizing`
- `completed`

and fields such as:

- schema version;
- job id;
- processing run id;
- state;
- accepted-at UTC;
- completed-at UTC only when actually Completed;
- `tracksSubmitted`: the validated Track count of the accepted body, in both states. It is deterministic from the body the platform durably holds; the finalizer publishes exactly that count or fails closed, so it never changes between `finalizing` and `completed`. (F1 named it `tracksSubmitted`, not `tracksAccepted`: in a `finalizing` acknowledgement nothing is published yet, and the 3.0 response's `tracksAccepted` meant a published count.)

Do not populate `CompletedAtUtc` for a hand-off acknowledgement.

### 5.3 Replay

- `Leased` + valid new 3.1 submission → `Finalizing`.
- `Finalizing` + same authenticated worker capability + same attempt + same digest → idempotent `finalizing`.
- `Completed` + same authenticated worker capability + same attempt + same digest → idempotent `completed`.
- Finalizing/Completed replay with a token that does not match the capability stored from the accepted hand-off → conflict.
- same attempt with a different digest → conflict.
- different attempt → conflict/fenced according to the existing attempt rules.

### 5.4 Worker staging

A `finalizing` response means the platform durably owns the hand-off but still needs current-attempt staging.

The worker must therefore not run the existing successful-completion staging release path for a Finalizing acknowledgement.

The worker may terminate normally after hand-off.

## 6. Submission transaction

The synchronous completion path holds `FOR UPDATE` only for bounded submission work.

Under one PostgreSQL transaction:

1. lock VisionJob;
2. verify schema / job id / worker id / lease token / attempt;
3. reject expired or superseded lease;
4. validate the body using the existing `VisionResultValidator`;
5. compute the existing completion digest;
6. handle replay/conflict rules;
7. insert the bounded canonical semantic finalization payload row, excluding `workerId` and the raw `leaseToken`;
8. transition `Leased → Finalizing`;
9. persist completion digest and finalization acceptance time;
10. end the worker lease **semantically** by entering Finalizing, but preserve `LeaseOwner`, `LeaseTokenHash` and `AttemptCount` until terminal state so an exact duplicate completion after an ambiguous HTTP outcome can still authenticate against the capability that originally handed off the job;
11. the stored lease expiry is no longer authority for heartbeat/fail/re-lease once status is Finalizing; those operations reject by status;
12. commit;
13. return the 3.1 acknowledgement.

No accepted evidence is sealed.

No Track / Observation / Artifact graph is created.

No visibility sequence is allocated.

Because the payload row and state transition are in the same database transaction:

- the accepted worker capability facts needed for exact replay remain on the VisionJob through Finalizing/Completed; Finalizing status, not lease expiry, prevents further worker lifecycle authority;
- there is no state where authoritative `Finalizing` references a missing filesystem manifest;
- there is no manifest-without-row compensation race;
- ambiguous commit resolves atomically to either pre-handoff or handed-off state.

## 7. Finalizer claims and fencing

Use the established PostgreSQL claim/reclaim pattern already proven by Scene Analytics, but keep the semantics VisionJob-specific.

A `VisionFinalizationHostedService` in the API host runs a bounded reconciliation/execution loop.

### 7.1 Claim fields

Persist minimal finalizer claim state on the VisionJob or a tightly bound finalization record:

- finalization attempt count;
- claim token hash;
- claim expiry;
- last heartbeat/extension time where useful;
- last safe error;
- terminal failure facts.

### 7.2 Claiming

Claim using `FOR UPDATE SKIP LOCKED` or the repository's established equivalent.

Reclaim is allowed only when:

- status is `Finalizing`;
- no live claim exists, or the claim expired;
- finalization attempts remain.

A reclaim rotates the claim token/hash.

### 7.3 Claim extension

Sealing may exceed one fixed claim duration.

The active finalizer must extend its claim between bounded sealing batches using a short conditional update that proves:

- job id;
- status `Finalizing`;
- current claim token/hash.

A stale finalizer may continue file IO after losing ownership, but cannot extend or publish.

### 7.4 Maximum duration

Introduce a product-level `MaximumFinalizationDurationSeconds`.

The mechanism is part of F1–F3.

Do **not** choose the final production value merely to make qualification pass.

After repaired-architecture measurement, freeze the value using:

- operational requirements;
- observed worst-case performance;
- recovery margin.

Authoritative B3 requalification occurs only after that value is frozen.

Exceeding the enforced maximum fails closed through the finalization failure path.

## 8. Accepted-evidence publication rule

The asynchronous finalizer must **never compensate by deleting accepted evidence** that it created.

Once concurrent/stale claimants can adopt deterministic create-once accepted keys, creator-based compensation is unsafe.

Failure sequence to prohibit:

1. finalizer A creates accepted key K;
2. A loses ownership;
3. finalizer B adopts K by verified size/SHA;
4. A later fails elsewhere;
5. A deletes K because it originally created it;
6. B publishes a relational reference to a missing object.

Therefore:

- accepted publication remains deterministic, create-once and hash/size verified;
- retries adopt existing identical objects;
- conflicting existing bytes fail closed;
- failed/restarted finalization may leave unreferenced accepted objects;
- unreferenced objects are an orphan/retention cost, never served without relational references;
- orphan cleanup remains a separate retention concern and must not be added to F1–F3.

The existing synchronous path may keep its current behavior until replaced, but the new asynchronous path has no accepted-evidence compensation deletion.

## 9. Finalization algorithm

For one valid claimed `Finalizing` job:

1. read the canonical semantic payload bytes from PostgreSQL;
2. verify payload length/SHA and deserialize;
3. re-run `VisionResultValidator`;
4. verify the recomputed completion digest equals the stored digest;
5. seal every referenced staged artefact through `IAcceptedEvidenceStore`;
6. adopt already-existing identical accepted keys as normal retry behavior;
7. periodically extend the finalizer claim between bounded batches;
8. build the same Track / Observation / Artifact graph as today in memory;
9. start the publication transaction;
10. lock/re-read VisionJob;
11. verify status `Finalizing`, claim token, attempt and digest;
12. insert/persist the relational graph and representative fix-up;
13. **then** acquire the exclusive ProcessingVisibilityBarrier;
14. allocate the visibility sequence;
15. call the claim-fenced `VisionJob.CompleteFinalization(claimToken, nowUtc)` transition;
16. mark ProcessingRun Completed and assign visibility sequence;
17. mark VideoAsset Processed;
18. commit;
19. perform terminal cleanup best-effort after authority is committed.

### 9.1 Transaction ordering invariant

Do not acquire the exclusive visibility barrier before the large graph persistence work.

The ordering is intentionally:

`job lock → graph persistence → visibility barrier → sequence/state publication → commit`

This preserves current snapshot/search behavior and minimizes exclusive visibility-lock hold time.

### 9.2 Partial visibility

No Track, Observation or Artifact row from the finalization becomes authoritative before the publication transaction commits.

Existing read/search/analytics paths continue to require Completed/fact-bearing run state.

## 10. Failure semantics

### 10.1 Before submission commit

Nothing authoritative changed.

The worker may retry under existing lease/attempt rules.

### 10.2 Ambiguous submission commit

Because payload + `Finalizing` transition are one PostgreSQL transaction, retry observes one of:

- still Leased → submit normally;
- Finalizing + same digest/attempt → idempotent hand-off.

No cross-resource repair is required.

### 10.3 Process loss after Finalizing commit

Another finalizer claims/reclaims and continues from the PostgreSQL payload.

### 10.4 Process loss mid-seal

Already sealed accepted objects remain unreferenced.

The next finalizer adopts them after integrity verification.

No deletion occurs.

### 10.5 Process loss after sealing, before publication

Same recovery: revalidate, adopt, then publish once.

### 10.6 Publication transaction ambiguity

PostgreSQL atomicity leaves either:

- Finalizing with no published relational graph; or
- Completed with the committed graph.

A stale caller must re-read authoritative state before further action.

### 10.7 Deterministic finalization failure

Add a domain transition:

`VisionJob.FailFinalization(claimToken, code, details, nowUtc)`

valid only from `Finalizing` and only for the current live finalizer claim. The transition itself verifies claim ownership so an expired or rotated-away claimant cannot terminally fail the job.

Deterministic failures fail immediately, including:

- payload missing/corrupt;
- completion payload digest mismatch;
- staged artifact missing;
- staged artifact integrity mismatch;
- accepted-key content conflict.

Use distinct safe codes such as:

- `vision_finalization_payload_missing`
- `vision_finalization_payload_integrity_failed`
- `vision_finalization_artifact_missing`
- `vision_finalization_artifact_integrity_failed`

The exact list should remain bounded and contract-tested.

### 10.8 Transient finalization failure

Transient IO/database/host errors are retried within:

- claim/reclaim rules;
- maximum finalization attempts;
- maximum finalization duration.

Normal claimant-owned terminal failure remains claim-fenced through `VisionJob.FailFinalization(claimToken, code, details, nowUtc)`.

F3 must also provide a **separately fenced platform reconciliation transition** for the case where no live claim remains and another claim is no longer permitted because the maximum attempt count or maximum finalization duration has been exhausted. That transition is failure-only: it must run under the authoritative VisionJob row lock, re-read `Finalizing` state, prove that no live claim exists, prove the configured exhaustion condition from persisted state/current time, and then move the job to the distinct finalization-exhausted terminal failure. It must not accept a stale claimant token, publish results, or serve as a general bypass around claim ownership.

This prevents the final permitted claimant crashing and leaving the job permanently `Finalizing` while preserving the rule that a stale claimant cannot terminally mutate a job owned by another live claimant.

When exhausted, fail with a distinct finalization-exhausted code.

The corresponding ProcessingRun and VideoAsset use their existing failed-processing transitions consistently.

A later operator/user reprocess creates a new ProcessingRun and VisionJob through the existing path.

### 10.9 Orphan accounting

On a finalization failure after sealing began, record/log:

- number of accepted objects created/adopted where known;
- bytes sealed where known.

This provides a measurable retention signal without adding an orphan collector to this repair.

## 11. Staging and janitor ownership

`StagingJanitor` must explicitly understand `Finalizing`.

Rules:

- current `Finalizing` attempt staging is **not deletable**;
- attempts below the current authoritative attempt remain reclaimable under existing fencing;
- no later attempt can supersede a Finalizing VisionJob;
- Completed/Failed retain existing grace-based cleanup;
- malformed/inconsistent Finalizing metadata → preserve and log fail-closed;
- old binaries must not encounter Finalizing during supported deployment rollback.

The worker's successful-completion fast path must not delete current-attempt staging after a 3.1 Finalizing acknowledgement.

## 12. Operator/status semantics

The status API must expose that the system is finalizing.

Keep ProcessingRun `Running`, but project the VisionJob phase.

Web/operator UI should render a clear Finalizing state distinct from inference/processing.

No arbitrary progress percentage should be fabricated for finalization.

If a finalization error occurs, surface a safe finalization-specific failure category rather than implying detector/tracker inference failed.

## 13. API-host placement and concurrency

For this repair, keep finalization in the platform API host.

Reasons:

- the host already owns platform/background responsibilities;
- Scene Analytics and staging janitor establish the precedent;
- current Windows/IIS deployment already depends on the host being continuously available;
- introducing another executable is unnecessary for correctness.

Initial concurrency:

`MaxConcurrentFinalizations = 1`

Qualification/measurement must record:

- API request latency during worst-case finalization;
- process RSS;
- finalization duration;
- claim-extension behavior.

If measured operator/API contention is unacceptable, a separate platform finalizer process is a later evolution using the same database protocol.

Do not introduce it pre-emptively.

## 14. B3 qualification after the repair

Do not weaken B3.

Split it into synchronous hand-off quality and asynchronous finalization quality.

### 14.1 B3-A — submission latency

Worst-case 10,000-Track / 50,000-object completion 3.1 submission using:

- real validator;
- real PostgreSQL payload insert;
- real `Leased → Finalizing` transition.

Required:

- n ≥ 30;
- warm-up excluded;
- ≥ 3 repeats;
- min / p50 / p95 / max;
- both qualified CPU OS variants;
- **max ≤ 15 s**.

This preserves 2× headroom against the 30 s worker request timeout.

### 14.2 B3-B — finalization duration

A product-enforced `MaximumFinalizationDurationSeconds` must exist before authoritative qualification.

Its value is frozen only after repaired-architecture measurement and review.

Authoritative B3-B then requires:

- worst-case Finalizing → Completed within **½ of the enforced maximum** on each qualified OS variant;
- no worker process dependency;
- no worker lease dependency;
- successful claim extension;
- recovery after process loss;
- no partial relational visibility;
- deterministic retry/adoption;
- bounded finalizer attempts;
- full 10,000-Track / 50,000-object completion.

This is a product safety limit, not an operator-facing SLO.

### 14.3 Publication transaction / visibility barrier

Record:

- graph persistence time;
- final publication transaction time;
- exclusive visibility-lock hold time.

The visibility-lock hold must not regress above the corresponding post-graph publication phase measured on the pre-repair baseline without explicit review.

Do not set a synthetic numeric lock limit without measurement.

### 14.4 Recovery qualification

Inject loss at:

- after hand-off commit;
- before first seal;
- mid-seal;
- after seal before publication;
- during/around publication commit;
- after Completed before cleanup.

Each must converge to exactly one authoritative terminal state under the configured claim/reconcile bounds.

### 14.5 Worker independence

Kill/stop the worker immediately after the Finalizing acknowledgement.

Platform finalization must still complete.

### 14.6 Staging retention

Staging must remain available throughout Finalizing and be reclaimed only under terminal-state authority.

Record retention against:

`MaximumFinalizationDuration + terminal janitor grace`

### 14.7 Operational baseline

Record, but do not initially gate on arbitrary new thresholds:

- API p95 latency while one worst-case finalization runs;
- API-host RSS;
- finalizer throughput;
- accepted-evidence orphan bytes under injected failures.

A later operational SLO may be frozen from product needs plus measurements.

## 15. Compatibility and deployment

Adding `Finalizing` to a string-persisted enum introduces binary compatibility risk.

### 15.1 Migration

Migration may add:

- payload table;
- nullable finalizer claim fields;
- finalization timestamps/error fields.

Adding an enum string does not need a PostgreSQL enum migration because the status is string-converted, but old binaries cannot safely interpret the new value.

### 15.2 Deployment order

Supported deployment:

1. apply migration;
2. deploy platform binaries that understand Finalizing everywhere;
3. advertise completion 3.1;
4. deploy 3.1 worker;
5. only then allow new Finalizing jobs.

**Decision:** the platform stops advertising and accepting completion 3.0 in the same release that introduces 3.1 (F2). A 3.0 worker then refuses at the existing capability probe (`PlatformContractUnsupported`), which is the established no-fallback behaviour; it does not reach the synchronous v3 path. This removes the measured-failing synchronous v3 sealing path from the platform rather than keeping two live v3 completion paths, and it makes the qualified completion path unambiguous. Development installs deploy platform and worker together, so no supported topology needs a 3.0 transition window. Completion 2.0 handling is unchanged. Reversing this decision is an owner call and would keep `ProcessingResultStore.CompleteAsync`'s v3 branch in service, with its own B3 exposure.

No worker silently switches protocols.

### 15.3 Rollback

Do not roll platform binaries back to a version that cannot parse Finalizing while any Finalizing row exists.

Operational rollback requires:

- drain/finish all Finalizing jobs; or
- restore to a state before 3.1 was enabled.

Document this explicitly.

### 15.4 In-flight jobs

A job leased by a 3.0 worker that is still processing when the platform stops accepting 3.0 (§15.2) cannot complete: its `POST …/complete` is refused with `worker_contract_version_unsupported`, the worker fails the attempt closed (`vision_worker_contract_unsupported`, the existing `PlatformContractUnsupported` path in `runner.py`), and the job is re-leased by a 3.1 worker under the existing attempt rules. The Development upgrade stops the worker before the platform, so this case does not arise on the supported path; it is stated so that no implementation adds a 3.0 fallback to avoid it.

Do not reinterpret an existing 3.0 completion as 3.1 hand-off.

### 15.5 Digest compatibility

Completion 3.1 is intentionally normalized to the existing semantic `CompletionSchema.V3` and digest-v3 domain because the Track Evidence Set content has not changed.

Required compatibility tests:

- equivalent 3.0 and 3.1 bodies normalize to the same validated v3 semantic result and completion digest;
- 3.1 remains distinguishable at the HTTP contract/capability layer;
- a 3.0 worker can never receive a Finalizing acknowledgement;
- a 3.1 worker can never fall back to the synchronous 3.0 protocol.

## 16. Implementation slices

Keep this repair isolated from S2.

### F1 — architecture/contracts/domain

- amend ADR-006:
  - asynchronous finalization ownership;
  - accepted-evidence no-deletion rule in the async path;
  - orphan semantics;
- amend S1.4 B3 qualification criteria;
- add `Finalizing` domain transition;
- add `FailFinalization`;
- add finalizer claim fields/policy;
- define completion exchange 3.1;
- add payload table/migration;
- status projection/UI contract for Finalizing;
- domain/contract/migration tests.

No background execution yet.

**F1 implementation record (2026-09-25, branch `feature/s1-4-b3-f1-finalization-contracts-domain` from `main@c829510`).**

- Domain: `VisionJobStatus.Finalizing`; `VisionJob.BeginFinalization(workerId, leaseTokenMatches, attemptCount, authorityNowUtc, completionDigest)` (canonical digest, live lease at authority time, attempt match; keeps `LeaseOwner`/`LeaseTokenHash`/`AttemptCount`/`LeaseExpiresAtUtc`; sets `FinalizationAcceptedAtUtc`); `CanAuthenticateCompletionReplay` (§5.3, lease expiry not consulted); finalizer claim `CanClaimFinalization`/`ClaimFinalization` (32-byte token SHA-256 hash, rotates per claim, bounded attempts)/`FinalizationOwnedBy` (fixed-time compare)/`ExtendFinalizationClaim`/`NoteFinalizationError`; `CompleteFinalization(claimToken, nowUtc)` (verifies the live claim itself at `nowUtc`, so an expired or rotated-away claimant cannot publish; the lease plays no part); `FailFinalization(claimToken, code, details, nowUtc)` from Finalizing only, codes `vision_finalization_[a-z0-9_]+` ≤ 64 chars. Both terminal transitions are claim-fenced inside the aggregate: each verifies `FinalizationOwnedBy(claimToken, nowUtc)` before mutating, so a stale finalizer (expired or rotated-away claim) can neither publish nor terminate the recovery attempt that superseded it; no unfenced reconciler terminal path exists in F1. Heartbeat, worker fail, re-lease and exhaustion are refused for Finalizing by status. The synchronous `Complete` path is untouched.
- Payload: `VisionFinalizationPayload` (JobId, AttemptCount, canonical semantic `Payload` bytes, `PayloadLength`, `PayloadSha256`, `CompletionDigest`, `AcceptedAtUtc`), bounded by `WorkerContractRules.MaximumCompletionRequestBodyBytes`; no navigation to or from `VisionJob`, so status and lease queries never load it. `VisionFinalizationPayloadCodec` serializes only schema/job/attempt/result/provenance/evidence facts and deliberately excludes `workerId` and raw `leaseToken`; its test proves a recognizable bearer token cannot appear in retained bytes while decoded payload re-validates to the identical completion digest.
- Persistence: migration `20260925020849_AddVisionFinalization` adds six nullable/defaulted `vision_jobs` columns, `vision_finalization_payloads` (PK `(job_id, attempt_count)`, FK cascade, checks on attempt, `payload_length = octet_length(payload)` ≤ 50331648, SHA-256 and digest format), partial index `ix_vision_jobs_finalizing_claim` (`status = 'Finalizing'`), checks `ck_vision_jobs_finalization_attempts`, `ck_vision_jobs_finalization_claim_token_hash`, `ck_vision_jobs_finalizing_facts` (a Finalizing row has digest, accepted time, lease owner, lease token hash and attempt ≥ 1). `Down` refuses while any job is Finalizing or a payload of an unfinished job exists (§15.3).
- Contracts: `WorkerContractRules.CompletionSchemaVersionV31 = "3.1"`, `AsynchronousCompletionSchemaVersions = ["2.0", "3.1"]`, `IsKnownCompletionSchemaVersion`, `IsAsynchronousCompletionSchemaVersion`, finalization states; `VisionJobFinalizationResponse` (§5.2, `completedAtUtc` omitted unless `completed`); schemas/examples `vision-job-complete-v3.1` (the 3.0 schema with only title and version const changed, enforced by `verify_repo.py`) and `vision-job-finalization-response-v3.1`. The validator maps 3.1 to `CompletionSchema.V3`; the golden 3.0 example with `schemaVersion` swapped to 3.1 produces the pinned v3 digest.
- Staged acceptance: the completion endpoint still accepts only 2.0 and 3.0 and the probe still advertises `["2.0","3.0"]` (`CompletionSchemaVersions` unchanged). F2 switches the endpoint and probe to `AsynchronousCompletionSchemaVersions`, which retires 3.0 and leaves 2.0 unchanged.
- Status: `ProcessingRunStatusResponse.phase` (`queued|processing|finalizing|completed|failed`, `ProcessingPhaseRule.FromJobStatus`) beside the unchanged run `status`; no `ProcessingRunStatus.Finalizing`; `progressPercent` stays the job's value (100 after hand-off) and counters stay zero until publication.
- Not in F1: the submission transaction, worker 3.1 runtime behavior, the finalizer, janitor Finalizing rules, UI rendering, B3 measurement. F2 does **not** persist the raw HTTP body; after authentication/validation it persists the canonical capability-free semantic payload produced by `VisionFinalizationPayloadCodec`.

### F2 — atomic submission

- implement canonical semantic PostgreSQL payload persistence with the worker authentication envelope stripped before persistence;
- `Leased → Finalizing` atomic transaction;
- exact replay/conflict rules;
- 3.1 response;
- worker 3.1 support;
- worker current-staging retention after hand-off;
- submission timing tests;
- version-skew tests.

At F2 completion, no Finalizing result may be reported Completed.

**F2 implementation record (2026-09-25, branch `feature/s1-4-b3-f2-atomic-submission` from `main@7538542`).**

- **Activation gate (F2 deployment note, cold-review repair).** F2 merges with asynchronous finalization **disabled by default**: `VisionFinalization:Enabled = false` (`VisionFinalizationOptions`, `appsettings.json`) on the platform and `MAVI_COMPLETION_SCHEMA_VERSION = 3.0` (`WorkerSettings.completion_schema_version`) on the worker. While disabled the platform advertises and accepts exactly the pre-F2 set `["2.0","3.0"]` (both synchronous, `ProcessingResultStore`), refuses 3.1 with `worker_contract_version_unsupported` before the hand-off store is reached, and the store itself refuses (`vision_finalization_disabled`) if reached, so **no job can enter Finalizing on a platform without a finalizer**; the default worker emits 3.0 and requires `"3.0"` from the probe, so an F2-only deployment keeps completing normally. The F3 release, once the hosted finalizer and recovery path exist, flips both together: `VisionFinalization:Enabled = true` and `MAVI_COMPLETION_SCHEMA_VERSION = 3.1`. That activation is where 3.0 retires: the platform then advertises and accepts `["2.0","3.1"]`, 3.1 routes to the atomic hand-off, and the 3.1 worker leases and hands off. Symmetry is enforced, not assumed: advertisement and acceptance derive from one option (`WorkerContractRules.CompletionSchemaVersions(enabled)` / `IsAcceptedCompletionSchemaVersion(version, enabled)`), and the worker requires exactly its configured version at every probe, so either split-brain (3.1 worker on an unactivated platform, or default worker on an activated one) fails closed before any lease; no fallback exists in either direction. No supported state advertises or accepts 3.1 without a working finalizer. Deployment order at F3: migrate (done in F1) → deploy platform binaries → set `VisionFinalization:Enabled=true` → deploy/configure the 3.1 worker → Finalizing jobs begin.
- Protocol switch (§15.2), effective only when the gate is on: `WorkerContractRules.AsynchronousCompletionSchemaVersions` = `["2.0","3.1"]`; `IsAcceptedCompletionSchemaVersion(v, true)` accepts 2.0 and 3.1; `GET /api/vision/contract` advertises `["2.0","3.1"]`; a 3.0 `POST …/complete` is refused with `worker_contract_version_unsupported` and never reinterpreted (§15.4); `ProcessingResultStore` then serves 2.0 only, its v3 sealing/graph code retained for the F3 finalizer to lift.
- Submission (§6): `VisionFinalizationSubmissionStore.SubmitAsync` — one transaction, `SELECT … FOR UPDATE` on the job; envelope check (route job id, worker id, lease token equal to the body's); capability via `ILeaseCapabilityService.Matches` (hash, fixed-time); Leased → lease owner/token/expiry at authority time, attempt match, run Running and video Processing; `VisionResultValidator.Validate`; `VisionFinalizationPayloadCodec.Encode` (no `workerId`, no `leaseToken`); `VisionFinalizationPayload.Create` (length, SHA-256 of the retained bytes, digest, accepted time = authority time) and `VisionJob.BeginFinalization` in the same unit of work; `SaveChanges`; commit. A commit exception triggers an explicit rollback attempt and propagates; the retry reads PostgreSQL's answer (§10.1–§10.2). Response `VisionJobFinalizationResponse.Finalizing(jobId, runId, acceptedAtUtc, tracksSubmitted = validated Track count)`.
- Replay/conflict (§5.3): on Finalizing or Completed the job must `CanAuthenticateCompletionReplay(workerId, tokenMatches, attempt)` (lease expiry not consulted); the replay body is re-validated and its recomputed digest compared with the stored `CompletionDigest`; equal → `finalizing` with the stored `FinalizationAcceptedAtUtc` (nothing written: no second payload row, no claim reset), or `completed` with the stored `CompletedAtUtc` once the run is Completed; wrong worker/token/attempt or different digest → `vision_job_completion_conflict` (409). Not Leased → `vision_job_not_leased`; expired/foreign lease → `vision_job_lease_invalid`; wrong attempt → `vision_job_attempt_mismatch`; invalid body → `vision_result_invalid` (400) with the lease intact.
- Not done in the 3.1 request (§6, §8): no `IAcceptedEvidenceStore` call, no Track/Observation/Artifact row, no visibility sequence, no `run.MarkCompleted`, no `video.MarkProcessed`; run stays Running, video Processing, counters zero, status `phase = finalizing`. `FailFinalization` is never called from the request path.
- Payload persistence (§4): EF `DbSet<VisionFinalizationPayload>.Add` + `SaveChanges` sends the bytea as one Npgsql parameter; the retained document is the codec's canonical JSON (smaller than the request body). Transient copies: the bound request graph, the encoded array, and the entity's defensive copy made by `VisionFinalizationPayload.Create`; no bulk COPY, no second serialization. Diagnostic timing (validation, encoding, persistence, total) is logged (event 1310) and returned in `VisionFinalizationSubmissionResult.Timings`; `VisionFinalizationSubmissionTimingTests` measures 500 Tracks by default and the full 10,000-Track envelope with `MAVI_F2_TIMING_TRACKS=10000` (development host, not a verdict: 10,000 Tracks, 29.1 MB body → validation ≈ 0.8 s, encoding ≈ 0.6 s, persistence ≈ 0.8 s, total ≈ 2.3 s). B3-A/B3-B remain F4.
- Worker (§5.4, §11): `WorkerSettings.completion_schema_version` (`3.0` default, `3.1` at activation) selects both the emitted body version and the version the probe requires (a platform not listing it is `PlatformContractUnsupported`, never a fallback); the body model accepts `3.0|3.1` for the shared corpora. `complete()` returns `VisionJobCompleteResponse` for 3.0 and `VisionJobFinalizationResponse` for 3.1 (`finalizing` = hand-off, `completed` = idempotent replay); the acknowledgement must match the version sent (a 3.0 worker refuses a hand-off acknowledgement and vice versa; a foreign job id or a malformed state/`completedAtUtc` pairing is refused). After a 3.1 hand-off the runner logs the state, does not poll, and keeps the current attempt's `staging/{jobId}/attempt-NNNN` (the finalizer's input); after a synchronous 3.0 completion the pre-F2 fast-path cleaner still releases the attempt (the platform sealed in the request). Superseded-attempt cleanup in the pipeline and the platform janitor are unchanged.
- Tests: `VisionFinalizationActivationGateTests` (default: probe `["2.0","3.0"]`, 3.1 refused before a trapped hand-off store, the store refuses directly, an F2-only deployment cannot strand a job in Finalizing — the 3.0 completion publishes and no Finalizing row or payload exists; activated: probe `["2.0","3.1"]`, 3.0 refused, 3.1 hands off; symmetry: for both states the probe advertises exactly the versions the endpoint accepts), the restored synchronous `VisionResultCompletionV3ApiTests` (default state), `VisionFinalizationSubmissionApiTests` with the gate on (hand-off atomicity and non-publication with a sealing trap, capability-free bytea proof by raw Npgsql read, invalid body, expired/foreign lease, Finalizing and Completed replay, wrong capability/digest conflicts, identical and conflicting concurrent submissions, retired 3.0, unchanged 2.0 with the visibility sequence allocated, request-body bound), `VisionResultCompletionCommitFailureTests` re-targeted to the 3.1 commit boundary (fail before commit, commit-succeeded-reported-failed, unconfirmed rollback), `VisionFinalizationSubmissionTimingTests`, updated `WorkerContractV3Tests`/`CompletionExchange31Tests`/`VisionFinalizationPersistenceTests`/`TrackEvidenceSetReadApiTests` (the relational read shape is seeded; the real v3 publication path is F3). Worker: `test_worker_completion_v3.py` (3.1 golden/schema, probe skew, acknowledgement states, malformed acknowledgements, no fallback), `test_worker_client.py`, `test_worker_runner.py` (staging survives `finalizing`/`completed`, no cleaner exists, lease loss keeps staging). Retired: the synchronous v3 API tests (sealing, compensation, adoption) whose semantics move to the F3 finalizer.
- Evidence checker: `tools/qualification/s1_evidence.py` B4 cites `VisionFinalizationSubmissionApiTests` in place of the deleted `VisionResultCompletionV3ApiTests` so the requirement names a suite that exists; the B4 set itself is re-derived in F4 (§14) with the finalizer's publication and recovery suites. No verdict changes.
- Not implemented (F3/F4): hosted finalizer, claim loop, sealing from the retained payload, graph publication, `Finalizing → Completed` at runtime, janitor Finalizing rules, B3 measurement; `S1SealingScaleTests` (opt-in) still posts 3.0 and is replaced by F4's B3-A/B3-B harness.

### F3 — finalizer and recovery

- hosted service;
- claim/reclaim/token rotation;
- claim extension;
- maximum attempts/duration;
- payload revalidation;
- seal outside publication transaction;
- no accepted-evidence compensation deletion;
- final graph publication;
- visibility-barrier ordering;
- Finalizing failure semantics;
- janitor Finalizing rules;
- status/UI phase;
- process-loss/replay tests.

**F3 implementation record (2026-09-25, branch `feature/s1-4-b3-f3-finalizer-recovery` from `main@26b44f5`, implementing the frozen plan `docs/superpowers/plans/2026-09-25-s1-4-b3-f3-finalizer-recovery-implementation.md` at `44e1f7b`).**

- **Domain (slice 1).** `VisionJob.FinalizationDeadline(maxDuration)` = `FinalizationAcceptedAtUtc + maxDuration`; `IsBeforeFinalizationDeadline` is the strict `now < deadline` rule shared by `CanClaimFinalization(now, maxAttempts, maxDuration)`, `ClaimFinalization(hash, now, claimDuration, maxAttempts, maxDuration)` (the transition itself re-proves the deadline before touching state) and `ExtendFinalizationClaim(token, now, extension, maxDuration)`; the deadline-blind F1 signatures are gone. `FinalizationClaimStateAt(now)` classifies the triple (hash, expiry, extended-at) as Unclaimed / Live / Expired / Malformed; malformed rows are never claimed, owned, extended or exhausted. `ReleaseFinalizationClaim(token, now)` lets a live claimant hand back early (fenced; the row becomes a canonical expired claim). `ExhaustFinalization(now, maxAttempts, maxDuration)` is the tokenless, failure-only reconciliation transition (`vision_finalization_exhausted`): Finalizing, canonical unclaimed/expired, attempts or deadline exhausted. Terminal transitions clear the whole triple. No schema change.
- **Shared components (slice 2).** `EvidenceSealingPlan` (key rule `evidence/{job}/attempt-NNNN/{crops|thumbnails|trajectories}/{stem}-{sha}.{ext}`, crops-then-trajectory order, admitted-crop quota defence), `FinalizationGraphBuilder` (pure Track/Observation/Artifact graph) and `FinalizationGraphPersistence` (the one relational write routine) are extracted from `ProcessingResultStore`, which keeps its transaction shape and compensation deletion for 2.0 (and 3.0 while the gate is off) and is behaviourally unchanged.
- **Options (slice 3).** `VisionFinalizationOptions`: `Enabled` (false), `MaxConcurrentFinalizations` (1), `PollIntervalSeconds` (5), `ClaimSeconds` (300), `ClaimExtensionSeconds` (300, must not exceed `ClaimSeconds`), `MaximumFinalizationAttempts` (3), `MaximumFinalizationDurationSeconds` (21600, must be ≥ `ClaimSeconds`; F4 freezes the production value), `SealingBatchSize` (200), `PayloadCleanupGraceSeconds` (0); validated at start even while disabled; `EffectiveMaximumFinalizationBound = MaximumFinalizationDurationSeconds + ClaimSeconds`. `VisionFinalizationPolicy` is the single source of the deadline for SQL and domain. `VisionFinalizationFailureCodes` is the closed vocabulary (§10.7 codes `vision_finalization_payload_missing|payload_integrity_failed|payload_invalid|staging_missing|staging_integrity_failed|evidence_conflict|context_invalid`, reconciliation `vision_finalization_exhausted`, transient `vision_finalization_io_transient|db_transient|publication_ambiguous`).
- **Lifecycle (slices 4–5).** `VisionFinalizationLifecycle`: claim (`FOR UPDATE SKIP LOCKED`, canonical-state, attempt and deadline pre-filter, re-proven by the aggregate under the lock, 32 random bytes with only the hash persisted); extension naming `Live | DeadlineReached | Lost`; unlocked input load; publication (lock and re-read → Finalizing, live ownership, attempt/digest/claim-ordinal identity → run Running and video Processing, no prior graph → graph write → completion barrier → sequence → `CompleteFinalization` → `MarkCompleted` → `AssignCompletionVisibilitySequence` → `MarkProcessed` → save → commit; a failing commit call is `Ambiguous`, never retried or compensated); claim-fenced `FailAsync` (job, run and video); ownership-proven `NoteTransientAsync` with optional release; tokenless one-row-per-transaction `ExhaustAbandonedAsync` that skips live and locked rows and reports malformed and invariant rows without touching them; terminal-only idempotent `CleanUpPayloadsAsync`; `CountAsync` for health.
- **Executor (slice 6).** `VisionFinalizationExecutor`: the eight payload checks of the F3 plan §6.4; one extension before IO; sealing in `SealingBatchSize` batches with an extension after each; `Lost` stops; `DeadlineReached` stops sealing and publishes only if sealing was already complete; deterministic seal statuses end the job with the unit's category and index as the only details; `IOException`/`UnauthorizedAccessException` are transient (noted, claim released); DB exceptions likewise; an ambiguous commit is noted through the fenced note (which writes nothing on a job that committed); orphan counts are logged (1509) after a failure that began sealing. It never references `IAcceptedEvidenceStore.DeleteAcceptedAsync` (source-scan test plus a deleting trap in every test world). Logs carry ids, counts, codes and exception type names; never a token, path or exception message.
- **Host and health (slice 7).** `VisionFinalizationHostedService` in the API host: immediate cycle then `PeriodicTimer(PollInterval)`; a cycle reconciles (batch 50), refreshes the counts, cleans payloads (batch 100), then claims and executes up to `MaxConcurrentFinalizations` with a scope per lifecycle call and a `SemaphoreSlim` that holds the bound across cycles; cancellation writes nothing (the claim expires and is reclaimed). With `Enabled = false` it only refreshes the counts. `/api/health` `details.visionFinalization`: `enabled, finalizingJobs, liveClaims, malformedClaims, oldestFinalizingAcceptedAtUtc, countsRefreshedAtUtc, inFlight, lastCycleUtc, lastCycleClaimed, lastCycleExhausted, lastCyclePayloadsCleaned`. Events 1500–1514 (below).
- **Janitor (slice 8).** Explicit `Finalizing` case: the current attempt is never reclaimed while Finalizing, attempts below it are reclaimed as for Leased, a later attempt is preserved and reported once (1401); Finalizing rows no longer raise 1406 every cycle.
- **Tests (slice 9).** Domain (`VisionFinalizationDomainTests`: deadline at claim and extension including the boundary instant, canonical/malformed matrix, release, exhaustion with and without live ownership), Application (`EvidenceSealingPlanTests`, `VisionFinalizationOptionsTests`, validator key binding), Integration (`VisionFinalizationLifecycleTests`, `VisionFinalizationPublicationTests`, `VisionFinalizationExecutorTests`, `VisionFinalizationHostTests`, `VisionFinalizationRecoveryTests`, `StagingJanitorTests` Finalizing rows, `VisionFinalizationTimingTests` diagnostic with `MAVI_F3_TIMING_TRACKS`). The crash matrix of the F3 plan §11 is covered: worker death after hand-off, host death before claim / after claim / before first seal / mid-seal / after all seals / after commit before cleanup, claim expiry mid-seal with a live reclaimant, stale claimant IO without publication, DB fault during graph persistence, ambiguous commit both ways, final permitted claimant death, deadline during a live claim, malformed metadata, two hosts, reconciliation racing a publisher, the janitor racing Finalizing, the deadline boundary instant. Mutants were applied per slice and killed (recorded in the F3 pull request), including the lifecycle passing the claim duration in place of the maximum finalization duration to the domain claim (`ClaimNextUsesMaximumFinalizationDurationNotClaimDuration`) and the executor losing its sealing accounting on a database transient after sealing began (`DatabaseTransientAfterSealingBeganKeepsTheSealingAccounting`; the accounting is carried in an execution state the outer transient handler reads, and event 1506 reports it).
- **Activation stays off.** `VisionFinalization:Enabled = false` in `appsettings.json` and `MAVI_COMPLETION_SCHEMA_VERSION = 3.0` on the worker remain the production defaults; the activation and rollback procedure is in `docs/runbooks/vision-runtime-model-component-lifecycle.md`. Development diagnostic at 200 Tracks (1,000 objects) on the development host: seal ≈ 1.6 s, publication transaction ≈ 0.8 s, executor wall ≈ 2.4 s; not a verdict. B3-A/B3-B, the frozen production timing values and every qualification verdict remain F4.

### F4 — B3 requalification

The S1.4 evidence checker's B3 requirement set (`tools/qualification/s1_evidence.py`: the sealing wall-time metrics, `completion_headroom_insufficient`, the sealing-output binding) and `S1SealingScaleTests` encode the pre-repair synchronous criterion. They are evidence tooling under S1.4 §2.1 and are replaced in F4 by B3-A/B3-B measurement and binding, with discrimination tests as Harness A required. Until then the checker correctly reports the old criterion as FAIL.

After F1–F3 merge and configuration freeze:

- choose the new exact `main` SHA;
- run B3-A Linux and Windows;
- measure repaired B3-B and freeze finalization maximum;
- re-run authoritative B3-B after the value is frozen if required;
- run fault matrix;
- rerun every S1 unit invalidated by the final behavior-bearing diff;
- only then resume B1/B2/B5/disconnected closure.

Do not perform expensive S1 qualification on an intermediate SHA that F1–F3 will invalidate.

## 17. Required tests

### Domain

- valid `Leased → Finalizing`;
- invalid/expired/stale lease cannot hand off;
- Finalizing cannot be worker-leased, heartbeated or worker-failed;
- Finalizing → Completed;
- Finalizing → Failed;
- finalizer claim rotation/expiry;
- maximum attempts/duration;
- exact digest replay;
- Finalizing/Completed replay authenticates with the retained original worker capability even after the original lease expiry, while heartbeat/fail/re-lease remain prohibited by status.

### Submission

- payload row + Finalizing transition are atomic;\n- retained payload contains no raw lease token or worker id;
- request rollback leaves neither;
- ambiguous commit is resolved by replay;
- same-digest duplicate is idempotent;
- different digest conflicts;
- no accepted evidence is sealed synchronously;
- no graph/visibility publication occurs synchronously;
- 3.1 response never claims Completed when only handed off;
- old/new protocol skew fails safely;
- after F2 a 3.0 completion is refused at the capability probe and at `POST …/complete` (`worker_contract_version_unsupported`), and 2.0 is unchanged;
- 3.0 and 3.1 semantic v3 bodies share the pinned digest-v3 behavior after normalization (the raw `schemaVersion` string is not a digest input; only the `CompletionSchema`-selected domain tag is).

### Finalizer

- payload SHA/length verification;
- process loss before first seal;
- process loss mid-seal;
- loss after all seals before publication;
- expired claim reclaim;
- stale claim cannot extend;
- stale claim cannot publish;
- current claim extends between batches;
- retry adopts existing identical accepted objects;
- conflicting accepted object fails closed;
- **no retry/failure path deletes accepted objects**;
- deterministic finalization failure;
- transient retry/exhaustion;
- no partial relational visibility;
- final publication idempotent;
- visibility barrier is acquired after graph persistence.

### Janitor

- Finalizing current attempt preserved;
- earlier fenced attempts reclaimed;
- Completed/Failed grace unchanged;
- malformed Finalizing state preserved/logged;
- payload row terminal cleanup is idempotent.

### Worker

- advertises/requires 3.1 for async hand-off;
- Finalizing acknowledgement ends worker attempt successfully;
- current staging is retained;
- Completed replay is accepted;
- no protocol fallback;
- timeout before acknowledgement fails safely.

### Status/UI

- Finalizing shown distinctly from inference;
- counts remain final-only where authoritative;
- finalization failure is not labelled detector/tracker failure.

### Qualification guards

- B3-A measures real payload insert and transition;
- B3-B full envelope uses real store/DB;
- claim-loss/process-loss mutants are discriminated;
- checker cannot PASS B3 from B3-A alone.

## 18. Cold-review invariants

Implementation must preserve all of these:

1. Python/model components never write operational PostgreSQL directly.
2. Worker staging remains worker-writable but not authoritative.
3. Accepted evidence remains platform-owned and hash/size verified.
4. No accepted evidence from the async path is deleted merely because the creating finalizer failed.
5. No relational intelligence is authoritative before the final publication commit.
6. Finalizing is truthful and operator-visible.
7. A stale finalizer may perform harmless create-once IO but cannot publish.
8. Worker protocol skew cannot delete staging needed by a finalizer.
9. Completion replay remains deterministic and conflict-safe.
10. PostgreSQL is the authority for both durable hand-off and finalizer fencing; persisted finalization bytes contain no bearer capability.
11. No distributed lock or generic workflow system is added.
12. Qualification remains tied to field correctness, not paperwork.

## 19. Qualification/invalidation consequence

PR #86 moved `main` to:

`daba6505976e4eb6ba2c17e5110833d1c920095f`

This is not the final S1.4 measured SHA.

PR #87 remains an interim historical evidence record for the old measured SHA.

F1–F3 change behavior-bearing platform, worker and qualification surfaces. After the complete architecture repair merges:

- select the new exact `main` SHA;
- apply the S1.4 invalidation map;
- re-run every invalidated unit;
- do not carry forward prior PASS results merely to save time.

## 20. Explicit non-goals

Do not add in F1–F3:

- bulk COPY solely to chase the old request timeout;
- parallel sealing solely to chase the old request timeout;
- a separate finalizer executable;
- a generic AI/job/workflow framework;
- a second public status hierarchy;
- distributed locks outside PostgreSQL;
- a filesystem finalization manifest/root;
- a new orphan-evidence collector;
- a new accepted-evidence storage format;
- S2 attribute functionality;
- Evidence Set selector/scorer changes.

Bulk insert, parallel sealing or a separate process may be considered later only if repaired-architecture measurements show an independent operational need.

## 21. Acceptance for implementation freeze

The architecture is ready for implementation when the plan and ADRs agree that:

1. hand-off is one PostgreSQL transaction;
2. completion protocol 3.1 fences mixed-version behavior, and 3.0 is retired with it;
3. `Finalizing` is explicit and truthful;
4. accepted-evidence compensation deletion is prohibited in the async path;
5. finalizer claims rotate and extend;
6. stale finalizers cannot publish;
7. deterministic and transient finalization failures are distinct;
8. publication ordering keeps the visibility barrier late;
9. current-attempt staging survives Finalizing;
10. B3-A retains the 15 s synchronous bound;
11. B3-B has an enforced maximum-duration mechanism whose final value is frozen from product requirements plus measurement before authoritative requalification;
12. implementation remains limited to F1–F3 before requalification.

The objective is not to make the qualification checker green. It is to make the real completion path reliable, recoverable and truthful at MAVI's declared 10,000-Track envelope.
