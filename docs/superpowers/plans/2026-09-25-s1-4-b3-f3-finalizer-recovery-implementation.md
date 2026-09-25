# S1.4 B3 F3 — Asynchronous Finalizer and Recovery: Implementation Plan

**Status:** Plan only. No production code is implemented by this document. It is the input to the F3 implementation pull request(s).

**Governing plan:** `docs/superpowers/plans/2026-09-25-s1-4-b3-asynchronous-finalization.md` (the "B3 plan"). Where this document and the B3 plan disagree, the B3 plan governs and this document must be corrected.

**Amendment 1 (2026-09-25, commit after `71ea11c`):** resolves the cold-review findings P1 (absolute finalization deadline not enforced against claim extension), P2 (rollback needs a PostgreSQL-derived Finalizing count in health) and P2 (malformed claim metadata must fail closed). Sections amended: 3, 5.2–5.4, 6.1, 6.2, 6.6, 6.8, 6.9, 7.1, 7.2, 7.5, 8.6, 8.7, 11, 13.3, 14, 15.1, 15.3, 16 (slices 1, 4, 6, 7, 10), 17, 19, 20.

**Amendment 2 (2026-09-25, commit after `d48fd38`):** resolves the remaining cold-review P1: `ClaimFinalization` itself was deadline-blind. The domain transition now takes `maximumFinalizationDuration` and re-proves `now < FinalizationDeadline` on the locked row, so no caller can create a claim at or after the deadline. Sections amended: 3 (I13), 4.1, 5.4, 7.1, 8.6, 15.1, 15.3, 16 (slice 1), 19, 20, 20.2.

**Governing ADRs:** ADR-006 §1–§7 (platform-owned accepted evidence; asynchronous finalization ownership), ADR-008 (API host on the operational plane), ADR-011 decision 1 (background services live in the API host).

---

## 1. Purpose

F1 (PR #89) gave the platform the `Finalizing` state, the fenced finalizer claim on `VisionJob`, and the `vision_finalization_payloads` row. F2 (PR #91) made completion 3.1 a single-transaction durable hand-off behind the `VisionFinalization:Enabled` gate, which is `false` by default so that no job can enter `Finalizing` on a platform that has nothing to finalize it.

F3 is the missing consumer: the hosted finalizer that claims Finalizing jobs, revalidates the retained payload, seals staged evidence into the accepted root, publishes the relational graph under the visibility barrier, and either completes or terminally fails the job — recoverably, across process loss, with exactly one live owner at any instant, and without ever deleting accepted evidence.

This document specifies F3 precisely enough that the implementation PR can be reviewed slice-by-slice against it, and precisely enough that the cold review in §20 could be repeated by someone who did not write it.

## 2. Starting repository state

- Repository: `hariomahlawat/MAVI`.
- Exact `main` SHA this plan was written against: **`26b44f573560de918ddfc6863bda7ccc18717806`** (merge of PR #91, "F2: gate asynchronous finalization off until F3 activates it").
- The F3 implementation branch must start from this SHA or a later `main` that has not changed the surfaces in §4. Any intervening change to those surfaces requires re-running the §4 survey before implementation begins.

All file paths below are relative to the repository root and were verified at that SHA.

## 3. Architectural invariants (must hold at every commit of F3)

These restate the B3 plan §18 cold-review invariants and ADR-006 §7 in the form the implementation is checked against.

| # | Invariant | Enforced by |
|---|---|---|
| I1 | PostgreSQL is the sole authority for hand-off and for finalizer ownership. No filesystem manifest, no lock file, no in-memory registry. | Every transition is a domain method on a `FOR UPDATE`-locked `VisionJob` row. |
| I2 | Exactly one live finalizer claim per job. A claim is live iff `FinalizationClaimTokenHash` is set and `FinalizationClaimExpiresAtUtc > now`. | `ClaimFinalization` only when `CanClaimFinalization`; token rotates on every claim; `FOR UPDATE SKIP LOCKED` selection. |
| I3 | A claimant that is expired, rotated away, or otherwise not the live owner cannot publish, cannot terminally fail, cannot extend, and cannot note errors that change outcome. | `FinalizationOwnedBy` inside `CompleteFinalization`, `FailFinalization`, `ExtendFinalizationClaim`; re-checked under the row lock in the same transaction as every write. |
| I4 | Nothing relational is authoritative before the publication commit. `ProcessingRun` stays `Running`, `VideoAsset` stays `Processing`, and no `Track`/`Observation`/`Artifact` row for the run exists outside the uncommitted publication transaction. | Single publication transaction; readers gate on `ProcessingRun.Status == Completed && CompletedAtUtc != null` and the visibility sequence. |
| I5 | Sealing precedes publication and happens outside any database transaction. | Sealing batches run with no open transaction; publication re-verifies the accepted-key mapping before writing rows. |
| I6 | Accepted evidence created by the asynchronous path is never deleted by the asynchronous path. No compensation deletion, no orphan collector. | `IAcceptedEvidenceStore.DeleteAcceptedAsync` is not referenced by any F3 component; guarded by an architecture test. |
| I7 | Persisted finalization bytes and finalizer logs contain no bearer capability, no raw claim token, no lease token, no filesystem path, and no exception payload. | Codec (F2) + log message contracts (§14) + tests. |
| I8 | The finalizer is a `BackgroundService` in the API host with bounded concurrency (default 1); no separate executable, no distributed lock outside PostgreSQL, no workflow engine. | `Program.cs` registration; `VisionFinalizationOptions.MaxConcurrentFinalizations`. |
| I9 | Deterministic failures are terminal and immediate; transient failures retry within the claim/attempt/duration bounds; exhaustion is a platform reconciliation transition that cannot publish. | Failure taxonomy §9; `ExhaustFinalization` (new domain transition). |
| I10 | The current Finalizing attempt's staging is never reclaimed by the janitor; superseded attempts remain reclaimable; malformed state fails closed. | `StagingJanitor.Evaluate` Finalizing case (new). |
| I11 | Status is truthful: `phase = finalizing` while Finalizing, run `Running`, video `Processing`, counts unpublished; `completed` only after the publication commit. | F1 `ProcessingPhaseRule`; F3 changes nothing here and adds tests that prove it under the running finalizer. |
| I12 | No AI/worker output becomes authoritative without platform validation: the payload is re-validated by `VisionResultValidator` and its digest recomputed before any sealing. | Payload integrity step §6.4. |
| I13 | The absolute finalization deadline `FinalizationAcceptedAtUtc + MaximumFinalizationDuration` is authoritative: no claim is created and no claim is extended at or after it. A claim live at the deadline expires naturally and is then exhausted. Total wall clock is bounded by `MaximumFinalizationDuration + one claim lifetime`. | `VisionJob.FinalizationDeadline`, `CanClaimFinalization`, **`ClaimFinalization`** and `ExtendFinalizationClaim` (domain, each taking the maximum duration and re-proving the deadline on the locked row); the claim and reconciliation SQL predicates are pre-filters derived from the same policy value. |
| I14 | Claim ownership metadata has exactly three canonical states (Unclaimed, Claimed-live, Claimed-expired). Anything else is malformed and fails closed: never claimed, never exhausted, never repaired, always logged. | `VisionJob.FinalizationClaimStateAt(now)`; SQL predicates select only canonical states; reconciliation reports malformed rows. |

## 4. Current-state code survey (at `26b44f5`)

### 4.1 Domain — `src/platform/Mavi.Domain/Processing/VisionJob.cs`

Present at `26b44f5` (F3 reuses these; amendment 1 changes the signatures of `CanClaimFinalization` and `ExtendFinalizationClaim` in slice 1 to carry the maximum duration, §5.4):

- `CanClaimFinalization(nowUtc, maximumFinalizationAttempts)`: Finalizing ∧ attempts remain ∧ (no claim ∨ claim expired).
- `ClaimFinalization(byte[] claimTokenHash, nowUtc, TimeSpan claimDuration, int max)`: increments `FinalizationAttemptCount`, stores the SHA-256 hash, sets `FinalizationClaimExpiresAtUtc = now + duration` and `FinalizationClaimExtendedAtUtc = now`. **Deadline-blind** at `26b44f5`: it calls the two-argument `CanClaimFinalization` and has no maximum-duration argument (amendment 2 replaces the signature; §5.4).
- `FinalizationOwnedBy(ReadOnlySpan<byte> claimToken, nowUtc)`: Finalizing ∧ 32-byte hash present ∧ unexpired ∧ fixed-time SHA-256 equality.
- `ExtendFinalizationClaim(token, nowUtc, extension)`: requires `FinalizationOwnedBy`; sets expiry `= now + extension`. **Has no deadline check** (amendment 1 adds one).
- `CanClaimFinalization(nowUtc, max)`: **has no duration bound** and treats `FinalizationClaimExpiresAtUtc == null` as claimable without checking the hash (amendment 1 replaces it with the paired canonical-state check).
- `NoteFinalizationError(code)`: Finalizing ∧ bounded finalization code; sets `FinalizationLastErrorCode`. **Not claim-fenced** (see §8.5 for how F3 uses it safely).
- `CompleteFinalization(token, nowUtc)`: requires `FinalizationOwnedBy` and `nowUtc ≥ FinalizationAcceptedAtUtc`; → Completed; clears hash/expiry.
- `FailFinalization(token, code, details, nowUtc)`: requires `FinalizationOwnedBy`; bounded code (`vision_finalization_` prefix, ≤64, `[a-z0-9_]`) and details ≤4000; → Failed; sets `FailureCode`, `FailureDetails`, `FinalizationLastErrorCode`, `CompletedAtUtc`; clears hash/expiry.
- `Exhaust(nowUtc)`: **Queued/Leased only**; throws from Finalizing (tested by `FinalizingRefusesHeartbeatWorkerFailureReLeaseAndExhaustion`).
- `IsFinalizationFailureCode(code)`.

**Missing (F3 must add):** the separately fenced platform reconciliation transition for exhaustion (B3 plan §10.8). Named here `ExhaustFinalization(DateTimeOffset nowUtc, int maximumFinalizationAttempts, TimeSpan maximumFinalizationDuration)`; see §5.3 and §8.4.

### 4.2 Domain — `VisionFinalizationPayload.cs`

`Create(jobId, attemptCount, byte[] payload, completionDigest, acceptedAtUtc, maximumPayloadBytes)`; properties `JobId`, `AttemptCount`, `Payload`, `PayloadLength`, `PayloadSha256` (lowercase hex), `CompletionDigest`, `AcceptedAtUtc`; `Matches(ReadOnlySpan<byte>)` recomputes length and SHA-256. No navigation to `VisionJob`. F3 uses it unchanged.

### 4.3 Persistence

- `VisionFinalizationPayloadConfiguration.cs`: table `vision_finalization_payloads`, PK `(job_id, attempt_count)`, check constraints on attempt/length/sha256/digest, FK to `vision_jobs` with cascade.
- `VisionJobConfiguration.cs`: finalization columns; `ck_vision_jobs_finalizing_facts`; partial index `ix_vision_jobs_finalizing_claim` on `status = 'Finalizing'` (the finalizer's selection index).
- Migration `20260925020849_AddVisionFinalization` (Down refuses with Finalizing rows or unfinished payloads).
- **No schema change is expected in F3.** If the exhaustion transition or observability needs a column, that is a P1 deviation to be raised, not silently added.

### 4.4 Application — `Modules/Intelligence`

- `VisionFinalizationPayloadCodec`: `Encode(VisionJobCompleteRequest)` (3.1 only, omits `workerId`/`leaseToken`), `Decode(ReadOnlySpan<byte>)` → `VisionJobCompleteRequest` with null envelope (`finalization_payload_invalid`, `finalization_payload_version_invalid`).
- `VisionResultValidator.Validate(routeJobId, request, videoDurationMs)` → `ValidatedVisionResult` (schema, attempt, frames, duration, provenance, detector/tracker identity, tracks with `ValidatedObservation`s and `ValidatedArtifactDescriptor`s, `CompletionDigest`). Digest domain for `CompletionSchema.V3` is `mavi:vision-completion-digest:v3`.
- `VisionFinalizationOptions`: `SectionName = "VisionFinalization"`, `bool Enabled` (default false). Registered in `Infrastructure/DependencyInjection.cs` with `.ValidateOnStart()` and **no validators**.
- `IVisionFinalizationSubmissionStore` / `VisionFinalizationSubmissionStore` (F2): the hand-off transaction. F3 does not change it, except that its replay branch already answers `completed` once the finalizer publishes (it reads `job.CompletedAtUtc` and `run.Status == Completed`), which F3 tests end-to-end.
- `IProcessingOrchestrator` / `ProcessingPhaseRule.FromJobStatus` (F1): `Finalizing → ProcessingPhases.Finalizing`. `ProcessingOrchestrator.GetStatusAsync` projects phase from the job. F3 changes nothing.

### 4.5 Infrastructure — synchronous store (extraction source)

`Persistence/Repositories/ProcessingResultStore.cs` (416 lines) is the only place sealing and graph construction exist today. Relevant structure:

- Lines 145–200: admitted-crop quota defence; per-track sealing loop (crops in rank order, then trajectory) via `SealAsync(descriptor, acceptedKey, newlySealedKeys, acceptedStorageKeys, ct)`; `AcceptedEvidenceKey(jobId, attempt, category, trackId, sha, ext)` = `evidence/{jobId:D}/attempt-{attempt:0000}/{crops|thumbnails|trajectories}/{stem}-{sha}.{jpg|msgpack}`; v3 crop stem is `{trackId}-{roleToken}`.
- Lines 201–270: graph construction (`Artifact.Create` trajectory, `Track.Create`, `AttachTrajectoryArtifact`, per observation `Artifact.Create` crop + `Observation.Create` + `AttachEvidenceArtifact`, `SaveChangesAsync`, then `AttachRepresentativeObservation`).
- Lines 275–310: `AcquireCompletionExclusiveAsync`, `AllocateSequenceAsync`, `job.Complete`, `run.MarkCompleted(frames, tracks, durationMs, detector/tracker names+versions, provenanceJson, now)`, `run.AssignCompletionVisibilitySequence`, `video.MarkProcessed`, `SaveChangesAsync`, commit.
- Lines 330–376: **compensation deletion** of newly sealed keys (`CompensateNewlySealedEvidenceAsync`, events 1301/1302). This is correct for the synchronous path and **prohibited** for the asynchronous path (ADR-006 §7).
- `MapSealFailure`: `Missing → vision_result_artifact_missing`, everything else `vision_result_artifact_integrity_failed`. The asynchronous path needs finer classes (§9).

Note: the whole synchronous sealing loop runs **inside** the `FOR UPDATE` transaction on the job. F3 must not copy that shape.

### 4.6 Infrastructure — storage

- `Storage/AcceptedEvidenceStore.cs`: `SealAsync(source, accepted, expectedSize, expectedSha, ct)` streams staging → temp file → durable publish; `File.Exists(destination)` before copying and `DestinationAlreadyExists` after publishing both route to `VerifyExistingAcceptedAsync`, which returns `Sealed(CreatedNew=false)` for an identical object and `DestinationConflict` otherwise. `Missing` when the staging source is absent; `IntegrityMismatch` on size/SHA mismatch or `UnsafeMediaPathException` (staging key escapes the media root). Temp files are always deleted. `DeleteAcceptedAsync` exists for the synchronous path only.
- `Storage/LocalMediaStore.cs`: `OpenReadAsync` resolves through `ResolveLocalPath`, which refuses link escape (`UnsafeMediaPathException`). Staging-root confinement for F3 comes from this resolver plus `AcceptedEvidenceStore`'s evidence-root confinement; F3 adds no new path logic.
- `Storage/StagingJanitor.cs`: `Evaluate(job, row, options, now)` switches on `row.Status`: Completed/Failed/Cancelled after grace; Leased → attempts `< AttemptCount`; Queued/0 → preserved; **`default` (which today includes `Finalizing`) → `LogInvariantViolation` (event 1406, Error) and nothing deleted.** So Finalizing staging is already safe, but is misreported as an invariant violation on every cycle. F3 must add an explicit Finalizing case (§12).
- `Api/Storage/StagingJanitorHostedService.cs`: the scheduling pattern (`PeriodicTimer(timeProvider)`, scope per cycle, public `RunCycleAsync` seam, `Enabled` gate with warning log).

### 4.7 Infrastructure — visibility barrier and readers

- `Persistence/ProcessingVisibilityBarrier.cs`: `AcquireCompletionExclusiveAsync(db, ct)` (advisory xact lock `1296127561,1412505908`), `AllocateSequenceAsync(db, ct)` (`nextval('processing_visibility_sequence')`), both `RequireTransaction`. Shared lock for first-page searches.
- `TrackSearchRepository.cs:71`, `TrackSearchRepository.Analytics.cs:177,501`, `ContentCatalog.cs:75,84`: readers require `run.Status == Completed && run.CompletedAtUtc != null` (and for search, the visibility sequence within snapshot). Nothing reads by `VisionJob.Status`.

### 4.8 Claim/reclaim precedent — Scene Analytics

`Persistence/Repositories/SceneAnalysisLifecycle.cs` and `Api/SceneAnalytics/SceneAnalyticsHostedService.cs`:

- Claim transaction: `BeginFreshAsync` (ChangeTracker cleared), `FromSqlInterpolated` with `FOR UPDATE SKIP LOCKED LIMIT 1` whose predicate includes the attempt bound and the reclaim cutoff; 32 random bytes, only the hash persisted; commit **before** compute.
- Exhaustion: separate transaction, `FOR UPDATE SKIP LOCKED` over abandoned rows (a row being completed right now is locked and skipped; "completion wins").
- Commit facts: fresh transaction, row lock, early `OwnedBy` exit, bulk writes **before** the barrier, barrier, sequence, domain `Complete(attempt, token, …)` re-verifies ownership, commit. `DbUpdateException`/`PostgresException` mapped to a retryable failure code rather than thrown.
- Host: `Enabled` gate, `PeriodicTimer(timeProvider)`, one scope per unit, `MaxConcurrentUnits` loop, public `RunCycleAsync` seam, cycle exceptions logged and swallowed.

F3 follows this shape exactly, with one addition: **claim extension between sealing batches** (Scene Analytics units are short enough not to need it).

### 4.9 Options registration and host

- `Infrastructure/DependencyInjection.cs`: `services.AddOptions<T>().Bind(configuration.GetSection(T.SectionName)).Validate(...).ValidateOnStart()`; `IAcceptedEvidenceStore` singleton; stores scoped.
- `Api/Program.cs`: `AddHostedService<SceneAnalyticsHostedService>()`, `AddHostedService<StagingJanitorHostedService>()`; `/api/health` → `GetPlatformHealth.Execute(version, build, commit, new PlatformHealthDetails(stagingJanitor.Current))`.
- `Api/appsettings.json`: `"VisionFinalization": { "Enabled": false }`.

### 4.10 Worker (Python) — no F3 changes

- `common/settings.py`: `completion_schema_version: Literal["3.0","3.1"] = "3.0"`.
- `worker/client.py`: probe requires the configured version in the platform's advertised set; fails closed otherwise.
- `worker/runner.py:447–465`: on `VisionJobFinalizationResponse` the worker logs and **retains** staging; `_release_accepted_staging` runs only after a synchronous `VisionJobCompleteResponse`.

### 4.11 Tests and harnesses

- `tests/Mavi.IntegrationTests/ApiTestFactory.cs`: `Clock`, `ConfigureDbContext` (interceptors), `OverrideServices`, `EnableSceneAnalyticsHost`, `EnableStagingJanitorHost`, `EnableAsynchronousFinalization`, `MediaRootOverride`/`EvidenceRootOverride`.
- `VisionFinalizationSubmissionApiTests.cs` (12 tests; `BuildRequestAsync` for 3.1; `VisibilitySequenceAllocationsAsync`; `CapturingLoggerProvider`), `VisionResultCompletionCommitFailureTests.cs` (`CommitBoundaryFaults` `DbTransactionInterceptor`), `VisionFinalizationActivationGateTests.cs` (6), `VisionResultCompletionV3ApiTests.cs` (sync 3.0), `StagingJanitorTests.cs` (world with `Logs.Count(eventId)`), `SceneAnalyticsHostTests.cs`/`SceneAnalyticsOwnershipTests.cs` (host/ownership precedents).
- `tests/Mavi.Domain.Tests/VisionFinalizationDomainTests.cs` (26 tests) and `ArchitectureBoundaryTests.cs`.
- `tools/qualification/s1_evidence.py` B4 cites `VisionFinalizationSubmissionApiTests`; B3 still encodes the synchronous criterion (replaced in F4). `Qualification/S1SealingScaleTests.cs` posts 3.0 (F4 replaces).

### 4.12 Survey conclusions that shape the design

1. The domain lacks `ExhaustFinalization`; everything else the finalizer needs at the aggregate level exists.
2. Sealing and graph construction must be **extracted** from `ProcessingResultStore` into shared, transaction-free components so that the synchronous 2.0/3.0 path and the finalizer run one implementation (§6.7, §22 of the request → §16 here).
3. The janitor needs a Finalizing branch, not a rewrite.
4. `VisionFinalizationOptions` needs the finalizer's tuning surface plus validation that prevents unsafe combinations (§13).
5. No schema change and no ADR amendment are required (ADR-006 §7 already states every rule F3 implements; see §19.3).

## 5. Target state machine

### 5.1 Job lifecycle (unchanged from B3 plan §3)

```
Queued → Leased → Finalizing → Completed
                       └──────→ Failed
```

`ProcessingRun`: `Queued → Running → Completed | Failed`. `VideoAsset.ProcessingStatus`: `Queued → Processing → Processed | Failed`. Run and video move only in the publication transaction (→ Completed/Processed) or in a terminal failure transaction (→ Failed/Failed).

### 5.2 Finalizer claim sub-state (within Finalizing)

Ownership metadata is the triple (`FinalizationClaimTokenHash`, `FinalizationClaimExpiresAtUtc`, `FinalizationClaimExtendedAtUtc`). The aggregate writes all three together in every transition (`BeginFinalization` clears all three; `ClaimFinalization` sets all three; `ExtendFinalizationClaim` and `ReleaseFinalizationClaim` update expiry and extended-at while keeping the hash), so only three canonical states are reachable through the domain:

| Canonical state | Persisted facts | Who may act |
|---|---|---|
| **Unclaimed** | hash `null` ∧ expiry `null` ∧ extended-at `null` (fresh from hand-off) | Any finalizer host: `ClaimFinalization` if attempts remain and `now < deadline` (§5.4). |
| **Claimed, live** | hash (32 bytes) ∧ expiry ∧ extended-at all present ∧ `expiry > now` | Only the holder of the token whose hash matches: extend (only while `now < deadline`), complete, fail, note. Others: nothing. |
| **Claimed, expired** | all three present ∧ `expiry ≤ now` | Any finalizer host: reclaim (rotates token, increments attempt) if attempts remain and `now < deadline`. Old holder: nothing. |
| **Malformed** (non-canonical) | any other combination: hash without expiry, expiry without hash, either without extended-at, extended-at alone, or a hash that is not 32 bytes | **Nobody.** Not claimable, not exhaustible, not modified. Reported as an invariant violation (§7.5, event 1512) and counted in health (§6.9) for operator investigation. |
| **Exhausted** (derived) | canonical Unclaimed or Claimed-expired ∧ (`FinalizationAttemptCount ≥ MaximumFinalizationAttempts` ∨ `now ≥ deadline`) | Platform reconciliation only: `ExhaustFinalization` → Failed with `vision_finalization_exhausted`. |

The domain exposes this classification once, as `VisionJob.FinalizationClaimStateAt(DateTimeOffset nowUtc)` returning `FinalizationClaimState { Unclaimed, Live, Expired, Malformed }`; `CanClaimFinalization`, `FinalizationOwnedBy`, `ExhaustFinalization` and the lifecycle all consult it rather than re-deriving null checks. `FinalizationOwnedBy` returns `false` for Malformed (it already requires a 32-byte hash and a non-null future expiry, so today's implementation is fail-closed for ownership; F3 makes the classification explicit and shared).

The database (`ck_vision_jobs_finalization_claim_token_hash`) already refuses a hash that is not 32 bytes but does **not** pair the three columns. Malformed state is therefore reachable only by direct database manipulation. §8.7 records the decision that code-level fail-closed handling is sufficient for F3 and that no pairing constraint is added.

### 5.3 New domain transition: `ExhaustFinalization`

```csharp
/// Finalizing → Failed by platform reconciliation, never by a claimant.
public void ExhaustFinalization(DateTimeOffset nowUtc, int maximumFinalizationAttempts, TimeSpan maximumFinalizationDuration)
```

Preconditions (all proven from the aggregate's own state, all required, any failure throws `DomainValidationException("vision_job_transition_invalid")`):

1. `Status == Finalizing`.
2. `FinalizationAcceptedAtUtc` is not null (a Finalizing row always has it; `ck_vision_jobs_finalizing_facts`).
3. **Canonical no-live-claim state**: `FinalizationClaimStateAt(now)` is `Unclaimed` or `Expired`. `Live` throws (a live claimant is never overridden); `Malformed` throws (fail closed; the row is left for the operator). This is a paired-state check, not a loose `hash == null || expiry == null || expiry <= now` disjunction.
4. **Exhaustion condition**: `FinalizationAttemptCount >= maximumFinalizationAttempts` **or** `now >= FinalizationDeadline(maximumFinalizationDuration)` (§5.4).
5. `maximumFinalizationAttempts >= 1`, `maximumFinalizationDuration > TimeSpan.Zero`.

Effects: `Status = Failed`; `FailureCode = "vision_finalization_exhausted"`; `FailureDetails = null` (the last transient code is already in `FinalizationLastErrorCode`; details are deliberately not synthesised); `CompletedAtUtc = now`; `FinalizationClaimTokenHash = null`; `FinalizationClaimExpiresAtUtc = null`. Hand-off facts (`LeaseOwner`, `LeaseTokenHash`, `AttemptCount`, `CompletionDigest`, `FinalizationAcceptedAtUtc`, `FinalizationAttemptCount`, `FinalizationLastErrorCode`) are retained for audit and replay conflict detection.

It takes **no token**. There is nothing a stale claimant can present to it, and it cannot publish. It is callable only from the reconciliation transaction in §7.5.

### 5.4 `MaximumFinalizationDurationSeconds` semantics

- **Absolute deadline.** `FinalizationDeadline(TimeSpan maximumFinalizationDuration) = FinalizationAcceptedAtUtc + maximumFinalizationDuration`, computed by the aggregate from the hand-off commit's authority time. It is the only timestamp that exists before any claim and survives every reclaim, so it is the only one that bounds total wall-clock recovery. It is authoritative for every rule below.
- **Authoritative state:** the persisted row under `FOR UPDATE`, evaluated against `TimeProvider.GetUtcNow()` of the platform host. Never a claimant's remembered start time.
- **New claims.** The transition is `ClaimFinalization(byte[] claimTokenHash, DateTimeOffset nowUtc, TimeSpan claimDuration, int maximumFinalizationAttempts, TimeSpan maximumFinalizationDuration)`, replacing the four-argument F1 signature. Its first check is `CanClaimFinalization(nowUtc, maximumFinalizationAttempts, maximumFinalizationDuration)` (a new signature; the F1 two-argument overload is retired in slice 1), which requires the canonical Unclaimed or Expired state, attempts remaining and `now < FinalizationDeadline(maximumFinalizationDuration)`. The transition therefore refuses, with no state change, when `nowUtc >= FinalizationAcceptedAtUtc + maximumFinalizationDuration`, whatever path reached it. The claim `SELECT` predicate (§7.1) carries the same bound expressed as `finalization_accepted_at_utc > {now − maximumDuration}`, which is the same inequality rearranged, with `now` and `maximumDuration` taken from the same policy and clock the domain check receives, so an exhausted job is never selected-then-skipped and SQL cannot drift from the domain.
- **Extension** (`ExtendFinalizationClaim(token, now, extension, maximumDuration)`, signature amended in slice 1): requires ownership **and** `now < FinalizationDeadline`. At or after the deadline the aggregate refuses, so a claimant cannot renew ownership indefinitely by `seal → extend → seal → extend`. The claim's existing expiry is not shortened.
- **A live claim is never revoked underneath filesystem work or publication.** The deadline stops new claims and extensions only. The claim that is live when the deadline passes expires naturally at its already-granted expiry; `CompleteFinalization` and `FailFinalization` remain permitted for that claimant while its claim is live (they are fenced by ownership, not by the deadline), so a finalization that is in its final seconds can still publish legitimately.
- **When retry stops:** at the first reconciliation pass that observes a canonical no-live-claim state and either bound exceeded. After the deadline no host can create a claim (`CanClaimFinalization` and the SQL predicate both refuse), so once the last live claim expires the job is exhausted on the next cycle.
- **Bounded tail.** The last extension that can be granted is one requested at `now < deadline`, which sets `expiry = now + ClaimExtension < deadline + ClaimExtension`; a first claim taken at `now < deadline` sets `expiry < deadline + ClaimDuration`. Therefore no claim is live after `deadline + max(ClaimDuration, ClaimExtension)`, and the job is Failed (exhausted) no later than `deadline + max(ClaimDuration, ClaimExtension) + PollInterval`. This is the bound F4 measures against (§17).
- **Production value:** not decided here. The mechanism ships with a generous development default (§6.1) and F4 freezes the production value from measurement (B3 plan §16 F4, §21 item 11), including the tail above.

## 6. Component design

All new platform components live in existing projects; no new project, executable or package.

### 6.1 `VisionFinalizationOptions` (Application) — extended

```
Enabled                               bool      default false   (F2; activation gate)
MaxConcurrentFinalizations            int       default 1       range [1, 8]
PollIntervalSeconds                   int       default 5       range [1, 300]
ClaimSeconds                          int       default 300     range [30, 86400]
ClaimExtensionSeconds                 int       default 300     range [30, 86400]
MaximumFinalizationAttempts           int       default 3       range [1, 20]
MaximumFinalizationDurationSeconds    int       default 21600   range [ClaimSeconds, 604800]  (6 h dev default; F4 freezes)
SealingBatchSize                      int       default 200     range [1, 5000]   (objects per batch between ownership revalidations)
PayloadCleanupGraceSeconds            int       default 0       range [0, 86400]
```

Validation (`.Validate(...)` chain, `ValidateOnStart`):

- every range above;
- `ClaimExtensionSeconds >= 30` and `ClaimExtensionSeconds <= ClaimSeconds` (an extension renews for at most one claim duration; with the deadline rule of §5.4 the tail is then exactly `MaximumFinalizationDuration + ClaimSeconds`);
- `MaximumFinalizationDurationSeconds >= ClaimSeconds` (otherwise no claim could ever be legal); the option's XML remarks and `appsettings.json` comment state the effective bound `MaximumFinalizationDurationSeconds + ClaimSeconds`;
- `Enabled == false` → the rest is still validated (a misconfigured but disabled section fails fast at start, the same way `StagingJanitorOptions.IsValid` does).

A single `ToPolicy()` (`VisionFinalizationPolicy` record: `ClaimDuration`, `ClaimExtension`, `MaximumAttempts`, `MaximumDuration`, `SealingBatchSize`) is passed into the lifecycle so tests can construct policies without configuration. `MaximumDuration` is the single source for the deadline in SQL and in the domain (§5.4).

### 6.2 `IVisionFinalizationLifecycle` (Application abstraction) / `VisionFinalizationLifecycle` (Infrastructure)

The transactional half. Every method opens its own short transaction on a cleared `MaviDbContext` (Scene Analytics `BeginFreshAsync` pattern), takes its row lock explicitly, and commits before returning. **No method computes, hashes a payload, reads staging or seals inside its transaction**, with one exception: §7.4 publication, which persists the already-built graph.

```csharp
Task<VisionFinalizationClaim?>        ClaimNextAsync(VisionFinalizationPolicy policy, CancellationToken ct);          // §7.1
Task<VisionFinalizationClaimStatus>   ExtendClaimAsync(VisionFinalizationClaim claim, VisionFinalizationPolicy p, CancellationToken ct); // §7.2 → Live | DeadlineReached | Lost
Task<VisionFinalizationPayloadSnapshot?> LoadPayloadAsync(VisionFinalizationClaim claim, CancellationToken ct);       // §7.3 (read-only, AsNoTracking, no lock)
Task<VisionFinalizationTransition>    PublishAsync(VisionFinalizationClaim claim, FinalizationGraphPlan plan, CancellationToken ct);      // §7.4 → Published | Stale | Retry(code) | Fail(code)
Task<VisionFinalizationTransition>    FailAsync(VisionFinalizationClaim claim, string code, string? details, CancellationToken ct);       // §7.6 (claim-fenced)
Task<VisionFinalizationTransition>    NoteTransientAsync(VisionFinalizationClaim claim, string code, bool releaseClaim, CancellationToken ct); // §7.7
Task<VisionFinalizationReconciliation> ExhaustAbandonedAsync(VisionFinalizationPolicy policy, CancellationToken ct);  // §7.5 → (Exhausted, MalformedJobIds)
Task<VisionFinalizationCounts>        CountAsync(CancellationToken ct);                                               // §6.9 (read-only: Finalizing rows, live claims, malformed rows, oldest accepted-at)
Task<int>                             CleanUpPayloadsAsync(int batchSize, TimeSpan grace, CancellationToken ct);      // §7.8
```

`VisionFinalizationClaim` = `(Guid JobId, Guid ProcessingRunId, Guid VideoAssetId, int AttemptCount /*worker attempt*/, int FinalizationAttemptCount, ReadOnlyMemory<byte> ClaimToken, DateTimeOffset ClaimExpiresAtUtc, DateTimeOffset FinalizationDeadlineUtc, string CompletionDigest, DateTimeOffset AcceptedAtUtc)`. `FinalizationDeadlineUtc` is informational for logging and for the executor's decision in §6.6; the authority is always the aggregate's own computation under lock. The raw token exists in this record and nowhere else; it is never logged, never serialised, and the record is not `ToString`-able with the token (override `ToString` to omit it, as `SceneAnalysisClaim` should).

### 6.3 `VisionFinalizationExecutor` (Infrastructure)

The non-transactional half: given a claim, runs §6.4 → §6.5 → §6.6 → publication, deciding failure class per §9. Owns no DbContext; calls the lifecycle for every database interaction. Structured as a sequence of steps each returning `Outcome = Continue | Fail(code, details) | Retry(code) | Lost`.

### 6.4 Payload integrity step (executor)

Given `LoadPayloadAsync` result (`Payload` bytes, `PayloadLength`, `PayloadSha256`, `CompletionDigest`, `AttemptCount`, plus `VideoAsset.DurationMs` and `RecordingStartUtc`, `ProcessingRun.Id`), in this order, each with a deterministic code (§9.1):

1. Row missing → `vision_finalization_payload_missing`.
2. `PayloadLength != Payload.Length` or `PayloadLength > WorkerContractRules.MaximumCompletionRequestBodyBytes` → `vision_finalization_payload_integrity_failed`.
3. Recomputed SHA-256 ≠ `PayloadSha256` (via `VisionFinalizationPayload.Matches`) → `vision_finalization_payload_integrity_failed`.
4. `VisionFinalizationPayloadCodec.Decode` throws → `vision_finalization_payload_invalid`.
5. Decoded `jobId != claim.JobId` or `attemptCount != claim.AttemptCount` → `vision_finalization_payload_invalid`.
6. `VisionResultValidator.Validate(jobId, decoded, video.DurationMs)` throws → `vision_finalization_payload_invalid` (details = the validator reason code only).
7. `result.CompletionDigest != payload.CompletionDigest` or `!= claim.CompletionDigest` (job's stored digest, captured at claim time under lock) → `vision_finalization_payload_integrity_failed`.
8. `result.Schema != CompletionSchema.V3` → `vision_finalization_payload_invalid`.

All eight are deterministic: the same bytes will fail the same way on every claimant, so they terminate via `FailAsync` immediately. Memory: the payload is read once into a `byte[]` bounded by `MaximumCompletionRequestBodyBytes`; the decoded request and `ValidatedVisionResult` are the same objects the submission transaction held in F2 (F2 timing tests established the 10,000-Track cost).

### 6.5 Sealing plan and staging validation (shared component, extracted)

`EvidenceSealingPlan` (Application, pure): from `ValidatedVisionResult`, `jobId`, `attemptCount` produce the ordered list of `SealingUnit(SourceStorageKey, AcceptedStorageKey, ExpectedSizeBytes, ExpectedSha256, Category)`, using the exact `AcceptedEvidenceKey` rule from `ProcessingResultStore` (moved, not copied). Crops in rank order then trajectory per track, tracks in validated order. Also computes the admitted-crop-bytes quota defence (moved from `ProcessingResultStore`).

Staging validation is done **by `AcceptedEvidenceStore.SealAsync`** during sealing, not as a separate pre-pass (a pre-pass would double the IO at 10,000 Tracks and still race the janitor). The expected logical key is the validator's `StorageKey`, whose shape the validator already constrains to `staging/{jobId}/attempt-{attempt:0000}/…` for the routed job and attempt (this is asserted by a new test in §15.2 so that an F3 reviewer does not have to trust it). Result classification (§9):

| `AcceptedEvidenceSealStatus` | Class | Code |
|---|---|---|
| `Sealed` (CreatedNew true/false) | success (adopted when false) | — |
| `Missing` | deterministic **unless** the job is not terminal and a re-check under the claim finds the staging directory gone entirely → still deterministic | `vision_finalization_staging_missing` |
| `IntegrityMismatch` | deterministic | `vision_finalization_staging_integrity_failed` |
| `DestinationConflict` | deterministic | `vision_finalization_evidence_conflict` |
| `IOException`/`UnauthorizedAccessException` thrown (not one of the above) | transient | `vision_finalization_io_transient` (noted, not terminal) |
| `OperationCanceledException` | claim continues if the token is not the host stop token; else Lost | — |

Orphan accounting (B3 plan §10.9): the executor counts `createdNew` objects and bytes and `adopted` objects and bytes; on any failure after the first seal it logs both (§14).

### 6.6 Bounded batches and claim extension

```
for each batch of SealingBatchSize units:
    seal each unit (no transaction open)
    status = lifecycle.ExtendClaimAsync(claim)     // §7.2, its own short transaction
    if status == Lost → stop: outcome Lost (no failure written, nothing published)
    if status == DeadlineReached → stop sealing (§ below)
```

- **Deadline reached during sealing** (`DeadlineReached`): the claim is still live until its current expiry but can never be renewed. The executor starts **no further batch** and attempts **no further extension**. If every sealing unit is already sealed it proceeds to `PublishAsync`, which is fenced by the live claim and by `CompleteFinalization` (a claim that expires before commit yields `Stale`, nothing written). If sealing is incomplete it stops with outcome `DeadlineReached` (log 1513), writes nothing, and lets the claim expire; reconciliation then exhausts the job (§7.5). Continuing to seal past the deadline would be harmless create-once IO but would spend host IO on a job that can no longer be claimed again, so it is not done.

- Extension is **after** each batch, so the claim is revalidated at most `SealingBatchSize` objects apart. With the defaults (200 objects, ≈ 20 ms per seal in the S1.4 B3 measurement) that is roughly every 4 s against a 300 s claim; a 10,000-Track set (≈ 40,000 objects) extends ≈ 200 times.
- If the claim **expires during** a batch (host paused, slow disk), the seals of that batch are harmless create-once IO (I3, B3 plan §18.7). The next `ExtendClaimAsync` returns Lost and the executor stops without writing anything.
- Extension is never attempted when the executor already knows `now ≥ claim.FinalizationDeadlineUtc` (it would be refused); the aggregate is still the authority when it is attempted.
- Extension failure due to a transient database error: retried once after `PollIntervalSeconds`; if it still fails, treat as Lost (the claim may legitimately be reclaimed by another host; this host must assume it is stale).
- Before the first batch the executor also extends once, so a claim that spent its initial duration waiting in the `MaxConcurrentFinalizations` queue is refreshed or found lost before IO begins.

### 6.7 Graph construction (shared component, extracted)

`FinalizationGraphBuilder` (Application, pure): from `ValidatedVisionResult`, the `SourceStorageKey → AcceptedStorageKey` map, run id, video id, `RecordingStartUtc`, and `createdAtUtc` produce `FinalizationGraphPlan` = ordered `(Artifact trajectory, Track track, List<(Artifact crop, Observation observation)>, Observation representative)`. This is the body of `ProcessingResultStore` lines 201–270 moved into a pure builder; the store and the finalizer both call it. `AttachRepresentativeObservation` needs the persisted observation id, so the builder returns the pairing and the publisher applies it after the first `SaveChangesAsync`, exactly as today.

Memory: the plan holds ≈ 1 Track + up to 5 Observations + up to 6 Artifacts per track as tracked entities. For the 10,000-Track worst shape that is ≈ 120,000 entity instances plus the change tracker's per-entity overhead. The F2 timing harness (`MAVI_F2_TIMING_TRACKS`) measured the validated result; F3 adds the graph plan and EF tracking to the same harness (§15.4) and F4 records the RSS. No intermediate is written to disk or to a temp table in F3 (B3 plan §20 excludes bulk COPY unless measured).

Nothing about the plan is visible outside the publication transaction: it is built in memory after sealing and before `PublishAsync` opens its transaction.

### 6.8 `VisionFinalizationHostedService` (API)

`BackgroundService` in `src/platform/Mavi.Api/Finalization/`, registered in `Program.cs` after the janitor, following `SceneAnalyticsHostedService`:

- `Enabled == false` → log 1500 (Information); the service then runs a **read-only** loop that refreshes the health counts (§6.9) once at start and every `PollIntervalSeconds`, and nothing else: no claim, no reconciliation, no cleanup. This keeps `FinalizingJobs` truthful in both gate states so that a stranded row after a premature disable is visible, without turning a disabled finalizer into a hidden one (it never writes).
- Startup: one immediate cycle (recovery of Finalizing rows left by a previous process), then `PeriodicTimer(PollIntervalSeconds, timeProvider)`.
- One cycle (`public RunCycleAsync(ct)` seam):
  1. Reconciliation: `ExhaustAbandonedAsync` (own scope). Exhausted count logged when `> 0`; each malformed job id logged once per host lifetime (1512).
  1a. Health refresh: `CountAsync` (same scope, read-only), published to the monitor (§6.9).
  2. Payload cleanup: `CleanUpPayloadsAsync` (own scope; bounded batch).
  3. Execution: up to `MaxConcurrentFinalizations` **concurrent** `Task`s, each: own `AsyncScope` → `ClaimNextAsync` → if null stop spawning → `VisionFinalizationExecutor.ExecuteAsync(claim)`; `Task.WhenAll`. A `SemaphoreSlim(MaxConcurrentFinalizations)` bounds the in-flight count across cycles so a long finalization in cycle N does not let cycle N+1 exceed the bound.
- Cancellation: the host stop token is passed to every step. The executor treats `OperationCanceledException` with the stop token as **Lost-equivalent**: it stops without writing a failure; the claim expires and another host (or this host after restart) reclaims. Shutdown therefore never terminally fails a job.
- Shutdown ordering: `StopAsync` waits for in-flight executions up to the host's shutdown timeout; a publication transaction already past `CommitAsync` is not interruptible; one before it is rolled back by connection close.
- Crash/restart: nothing is held in memory that matters. The startup cycle reclaims expired claims and exhausts abandoned jobs.
- Scope-per-work-unit: no `MaviDbContext` lives longer than one lifecycle method. The executor takes an `IServiceScopeFactory` and creates a scope per lifecycle call; the `IAcceptedEvidenceStore`/`IMediaStore` singletons are resolved once.
- Cycle exceptions are logged (1514) and the loop continues; `OperationCanceledException` with the stop token ends the loop.

### 6.9 Health (`/api/health`)

Add `VisionFinalizationHealth` to `PlatformHealthDetails` via an `IVisionFinalizationMonitor` singleton updated by the host (the `IStagingJanitorMonitor`/`StagingJanitorHealth` pattern in `Application/Abstractions/Storage/IStagingJanitor.cs`). Read-only; no new endpoint. Serialised with the existing camelCase policy, so the runbook refers to `visionFinalization.finalizingJobs`.

```
VisionFinalizationHealth(
    bool            Enabled,
    int             FinalizingJobs,                  // COUNT(*) FROM vision_jobs WHERE status = 'Finalizing' — PostgreSQL state, all hosts
    int             LiveClaims,                      // of those, canonical Claimed-live at count time
    int             MalformedClaims,                 // of those, non-canonical ownership metadata (§5.2)
    DateTimeOffset? OldestFinalizingAcceptedAtUtc,
    DateTimeOffset? CountsRefreshedAtUtc,            // null until the first successful CountAsync
    int             InFlight,                        // this host's executions in progress
    DateTimeOffset? LastCycleUtc,
    int             LastCycleClaimed,
    int             LastCycleExhausted)
```

- **Source of `FinalizingJobs`:** one `SELECT count(*) … WHERE status = 'Finalizing'` (plus the live/malformed/oldest aggregates in the same statement) by `IVisionFinalizationLifecycle.CountAsync`, `AsNoTracking`, no lock, no transaction. It is the database's answer, never derived from in-flight work, so it is correct across every API host.
- **Refresh:** every cycle while enabled (step 1a in §6.8), and every `PollIntervalSeconds` in the read-only loop while disabled. A failed count leaves the previous snapshot and its `CountsRefreshedAtUtc` untouched, so a stale value is recognisable.
- **Before the first refresh** (`CountsRefreshedAtUtc == null`) the counts are reported as `0` with the null timestamp; the runbook requires a non-null timestamp within the last two poll intervals before trusting `FinalizingJobs == 0`.

## 7. Transaction boundaries

Every transaction below: `db.ChangeTracker.Clear()` then `BeginTransactionAsync` (default `ReadCommitted`; the row lock is what serialises, not the isolation level), explicit `FOR UPDATE`, commit or rollback before return. Timings for logs are measured around each transaction.

### 7.1 Claim (`ClaimNextAsync`)

```sql
SELECT * FROM vision_jobs
WHERE status = 'Finalizing'
  AND finalization_attempt_count < {policy.MaximumAttempts}
  AND finalization_accepted_at_utc > {nowUtc - policy.MaximumDuration}          -- now < deadline (§5.4)
  AND (   (finalization_claim_token_hash IS NULL                                -- canonical Unclaimed
           AND finalization_claim_expires_at_utc IS NULL
           AND finalization_claim_extended_at_utc IS NULL)
       OR (finalization_claim_token_hash IS NOT NULL                            -- canonical Claimed, expired
           AND finalization_claim_expires_at_utc IS NOT NULL
           AND finalization_claim_extended_at_utc IS NOT NULL
           AND finalization_claim_expires_at_utc <= {nowUtc}))
ORDER BY finalization_accepted_at_utc, id
FOR UPDATE SKIP LOCKED LIMIT 1
```

Uses `ix_vision_jobs_finalizing_claim`. Malformed rows (§5.2) match neither disjunct and are never selected. The predicate is a pre-filter only: the domain (`ClaimFinalization` → `CanClaimFinalization(now, MaximumAttempts, MaximumDuration)` → `FinalizationClaimStateAt(now)`) re-proves every condition on the locked row with the same `nowUtc` and policy, and a `DomainValidationException` here rolls back and logs 1512 (the SQL and domain disagreeing is itself an invariant violation, and a test in §15.3 drives the boundary instant `now == deadline` through both). Then in the same transaction: load `ProcessingRun` and `VideoAsset` (plain reads; they are not locked because nothing else mutates them while the job is Finalizing — the orchestrator's lease query selects only Queued/Leased rows and its fail path requires Leased), generate 32 random bytes, `job.ClaimFinalization(SHA256.HashData(token), nowUtc, policy.ClaimDuration, policy.MaximumAttempts, policy.MaximumDuration)` with the **same** `nowUtc` and `policy` the SQL predicate was built from (the domain re-proves the canonical state, the attempt bound and `nowUtc < FinalizationDeadline(policy.MaximumDuration)` on the locked row), `SaveChangesAsync`, **commit**. Return the claim record. The row lock is held only for the claim write.

If `run.Status != Running || video.ProcessingStatus != Processing` the job is in a state the hand-off never produces. The claim is still taken (it consumes an attempt) and the executor fails it deterministically with `vision_finalization_context_invalid` (§9.1). Refusing to claim would make `LIMIT 1 … SKIP LOCKED` return the same row every cycle; claiming keeps the selection predicate simple and the outcome auditable (event 1512).

### 7.2 Extension (`ExtendClaimAsync`)

Row lock, `job.ExtendFinalizationClaim(token, now, ClaimExtension, MaximumDuration)`; on `DomainValidationException` → rollback, then classify for the caller without writing: if `job.FinalizationOwnedBy(token, now)` is true (ownership intact, so the refusal was the deadline) → `DeadlineReached`; otherwise → `Lost`. `SaveChangesAsync`, commit, `Live` with the new expiry. Held for one `UPDATE`. The aggregate is the only place the deadline rule for extension lives; the lifecycle merely names the reason.

### 7.3 Payload load (`LoadPayloadAsync`)

**No lock, no transaction** (`AsNoTracking`, single `SELECT` of the `(job_id, attempt_count)` row plus `video.DurationMs`/`RecordingStartUtc`). The payload row is immutable after hand-off (only ever deleted, §7.8, and only after the job is terminal), so an unlocked read is exact. Reading a bytea of up to the request maximum must not sit under a row lock.

### 7.4 Publication (`PublishAsync`) — exact ordering

1. Fresh context, `BeginTransactionAsync`.
2. `SELECT * FROM vision_jobs WHERE id = {jobId} FOR UPDATE` (re-read; never the claim-time instance).
3. Prove `Status == Finalizing`; else rollback → `Stale`.
4. Prove `job.FinalizationOwnedBy(token, now)`; else rollback → `Stale`. (Early exit; the domain re-proves in step 13.)
5. Prove identity: `job.AttemptCount == claim.AttemptCount`, `job.CompletionDigest == claim.CompletionDigest == plan.CompletionDigest`, `job.FinalizationAttemptCount == claim.FinalizationAttemptCount`; else rollback → `Stale` (a rotated claim on the same job would already fail step 4; this guards a plan built for the wrong attempt).
6. Load `ProcessingRun` and `VideoAsset`; prove `Running`/`Processing`; else rollback → `Fail(vision_finalization_context_invalid)`.
7. Prove no graph exists for the run: `!db.Tracks.Any(t => t.ProcessingRunId == run.Id)`; else rollback → `Fail(vision_finalization_context_invalid)` (a previous publication for this run is impossible while the run is Running; presence means an invariant violation and is not repaired by deletion).
8. Add all `Artifact`/`Track`/`Observation` entities from the plan; `SaveChangesAsync` (the bulk write, **before** the barrier; Scene Analytics does the same for the same reason).
9. `AttachRepresentativeObservation` per track; (deferred to the save in step 14).
10. `ProcessingVisibilityBarrier.AcquireCompletionExclusiveAsync(db)`.
11. `visibilitySequence = AllocateSequenceAsync(db)`.
12. `completionNow = timeProvider.GetUtcNow()`.
13. `job.CompleteFinalization(token, completionNow)` — the fence proper; `DomainValidationException` → rollback → `Stale`.
14. `run.MarkCompleted(frames, tracks.Count, durationMs, detector/tracker identities, provenanceJson, completionNow)`; `run.AssignCompletionVisibilitySequence(visibilitySequence)`; `video.MarkProcessed()`; `SaveChangesAsync`.
15. `CommitAsync`. On exception: attempt rollback, then return `Ambiguous` (§10.2); never retry the same transaction object.

Validation against existing code: steps 8–15 are `ProcessingResultStore` lines 265–316 with `job.Complete(worker capability…)` replaced by `job.CompleteFinalization(claimToken, now)` and the sealing loop removed. `run.MarkCompleted` requires `Running` (line 89) and `AssignCompletionVisibilitySequence` requires `Completed` with a null sequence (line 105): the order in step 14 is therefore forced. `video.MarkProcessed` requires `Processing`. Readers cannot see partial state because every row written in steps 8–14 is in one uncommitted transaction, the exclusive advisory lock is held from step 10 through commit, and readers gate on `run.Status == Completed && CompletedAtUtc != null` plus the sequence, all of which flip in the same commit.

Row-lock discipline: the job row is locked for the whole of §7.4, which is the bulk insert plus the barrier. This is the same as the synchronous path minus sealing, and is the floor the B3 plan accepts (B3-B measures it). Nothing else contends for that row while it is Finalizing (§7.1 note), so the lock costs no one but the finalizer itself.

### 7.5 Exhaustion reconciliation (`ExhaustAbandonedAsync`)

```sql
SELECT * FROM vision_jobs
WHERE status = 'Finalizing'
  AND (   (finalization_claim_token_hash IS NULL                                -- canonical Unclaimed
           AND finalization_claim_expires_at_utc IS NULL
           AND finalization_claim_extended_at_utc IS NULL)
       OR (finalization_claim_token_hash IS NOT NULL                            -- canonical Claimed, expired
           AND finalization_claim_expires_at_utc IS NOT NULL
           AND finalization_claim_extended_at_utc IS NOT NULL
           AND finalization_claim_expires_at_utc <= {nowUtc}))
  AND (finalization_attempt_count >= {policy.MaximumAttempts}
       OR finalization_accepted_at_utc <= {nowUtc - policy.MaximumDuration})    -- now >= deadline (§5.4)
ORDER BY finalization_accepted_at_utc, id
FOR UPDATE SKIP LOCKED LIMIT {batch}
```

The same canonical-state disjunction as §7.1 (shared as one SQL fragment constant in the lifecycle so the two cannot drift), with the exhaustion condition instead of the claimability condition. A live claim is excluded; a malformed row is excluded.

In the same method, before the locking query, a **read-only** query lists Finalizing rows whose ownership metadata is non-canonical (the complement of the disjunction above, restricted to `status = 'Finalizing'`), returned as `MalformedJobIds` for the host to log once per job per host lifetime (1512) and for health (`MalformedClaims`). Nothing is written to them.

For each row: `job.ExhaustFinalization(now, MaximumAttempts, MaximumDuration)` (the domain re-proves every predicate from the locked row, including the canonical no-live-claim state; `Malformed` throws, rolls back and is logged), `run.MarkFailed("vision_finalization_exhausted", null, now)`, `video.MarkProcessingFailed()`. `SaveChangesAsync`, commit. A job whose live claimant is publishing right now is row-locked and **skipped**; a job whose claim is live is excluded by the predicate and re-proven by the domain. Payload rows are not deleted here (§7.8).

`run.MarkFailed` requires the run not Completed/Cancelled and `video.MarkProcessingFailed` requires Queued/Processing: both hold for a Finalizing job by the hand-off preconditions. If either throws, the transaction rolls back, event 1512 is logged and the row is left for an operator — nothing is inferred.

### 7.6 Deterministic failure (`FailAsync`)

Row lock; `job.FailFinalization(token, code, details, now)` (fenced); `run.MarkFailed(code, details, now)`; `video.MarkProcessingFailed()`; save; commit. `DomainValidationException` from `FailFinalization` → rollback → `Stale` (a stale claimant cannot fail the job, I3). Orphan accounting is logged by the executor **after** this commit (or after `Stale`), not inside it.

### 7.7 Transient note (`NoteTransientAsync`)

Row lock; **prove `FinalizationOwnedBy(token, now)` first** (because `NoteFinalizationError` is not fenced in F1; §8.5); if not owned → rollback → `Stale` (write nothing). If owned: `job.NoteFinalizationError(code)`; if `releaseClaim`, `job.ReleaseFinalizationClaim(token, now)` — a new fenced domain transition (slice 1) that sets `FinalizationClaimExpiresAtUtc = now` and keeps the hash, so the next cycle may reclaim without waiting out the remaining claim duration (`ExtendFinalizationClaim` cannot shorten a claim). Save, commit.

Backoff: the reclaim predicate in §7.1 selects on `expires_at <= now`; the released claim is immediately reclaimable **by the next cycle**, which is `PollIntervalSeconds` away. F3 does not add exponential backoff: the attempt bound and duration bound are the limits, and a transient database outage makes every cycle fail cheaply at the claim step anyway. (Recorded as an accepted simplification; F4 measurement can revisit.)

### 7.8 Payload cleanup (`CleanUpPayloadsAsync`)

Separate from publication authority. Predicate:

```sql
DELETE FROM vision_finalization_payloads p
USING vision_jobs j
WHERE j.id = p.job_id
  AND j.status IN ('Completed','Failed','Cancelled')
  AND j.completed_at_utc <= {nowUtc - grace}
  AND p.ctid IN (SELECT ctid FROM vision_finalization_payloads ... LIMIT {batch})
```

(Implemented as an EF `ExecuteDeleteAsync` over a bounded `Take`, or two statements; the exact form is a slice detail.) Idempotent, retryable, runs in its own transaction, never touches `vision_jobs`. A Finalizing job's payload is never eligible. Ownership: the hosted service, every cycle, `batch = 100`. Grace default 0: once the job is terminal, the payload has no reader (replay uses the job row's digest, not the payload). The FK cascade also removes payloads if a job row is ever deleted.

## 8. Ownership and fencing rules

### 8.1 Token

32 bytes from `RandomNumberGenerator`; only `SHA256(token)` is persisted; comparison is `CryptographicOperations.FixedTimeEquals` inside the aggregate. The raw token lives in the `VisionFinalizationClaim` record for the executor's lifetime and is never logged, serialised or placed in an exception.

### 8.2 One live owner

Proof sketch: a claim is written only under `FOR UPDATE` on the job row by `ClaimFinalization`, whose precondition is "no unexpired claim". Two hosts cannot both pass that precondition for the same row because the second waits on (or skips) the first's row lock and re-reads after commit. Extension never creates a claim; it only moves the expiry of the existing one and only for the presenter of the matching token. Hence at any instant at most one token hash is unexpired for a row, and only its presenter passes `FinalizationOwnedBy`.

### 8.3 Stale claimant

Every write that changes the outcome (`ExtendFinalizationClaim`, `CompleteFinalization`, `FailFinalization`) requires `FinalizationOwnedBy` inside the aggregate, and the aggregate instance is always freshly `FOR UPDATE`-read in the same transaction. A stale claimant therefore gets `Invalid()` and its transaction rolls back. Its filesystem side-effects are create-once objects with content-addressed keys (`{trackId}-{sha}`) that a later claimant adopts identically (I3, §18.7 of the B3 plan).

### 8.4 Exhaustion cannot bypass a live claim

`ExhaustFinalization` requires "no live claim" from the locked row, and the reconciliation `SELECT` excludes live claims and `SKIP LOCKED`s rows being written. A live claimant about to publish holds the row lock through commit, so reconciliation cannot interleave between its ownership check and its commit.

### 8.5 `NoteFinalizationError` is not fenced in F1

F3 never calls it without first proving ownership in the same transaction (§7.7). It is not made claim-fenced in the domain because a legitimate use exists for the platform (reconciliation may want to record `vision_finalization_exhausted` before failing), but the F3 executor only ever calls it via `NoteTransientAsync`. A domain test in §15.1 pins `NoteTransientAsync`'s ownership check via the lifecycle, and a mutant that removes the check must be caught.

### 8.6 The deadline is enforced at the authority boundary

The deadline rule lives in the aggregate: `CanClaimFinalization(now, maxAttempts, maxDuration)`, `ClaimFinalization(hash, now, claimDuration, maxAttempts, maxDuration)` (which begins with that predicate) and `ExtendFinalizationClaim(token, now, extension, maxDuration)` all call `FinalizationDeadline(maxDuration)` and refuse at `now >= deadline`. Every domain method that can create or prolong ownership therefore carries the maximum duration in its own signature; there is no deadline-blind transition left for a direct caller to reach, and SQL, lifecycle, executor and caller discipline are never the only line of defence. The executor never computes it for a decision that writes; the lifecycle passes the policy's `MaximumDuration` and the platform clock, and the SQL pre-filters use the same two values rearranged (`accepted_at > now − maxDuration`). There is therefore one definition of "before the deadline" (`now < accepted_at + maxDuration`) and two expressions of it (the strict `<` in the four domain checks, the rearranged `accepted_at > now − maxDuration` in the two SQL predicates) that are tested to agree at the boundary instant `now == deadline`, where all of them refuse. Proof of the bounded tail is in §5.4.

### 8.7 Malformed ownership metadata fails closed; no schema change

Decision: F3 adds **no** pairing check constraint over the three claim columns. Justification:

- every writer of the three columns is the `VisionJob` aggregate, which sets or clears them together (§5.2), so malformed state is reachable only by direct database manipulation, which is outside the threat model the fence addresses (the same assumption ADR-006 §7 makes for the payload digest);
- the fail-closed rule is what protects correctness, and it is enforced in code at every consumer: `FinalizationClaimStateAt` in the domain, the canonical-state disjunction in both SQL predicates, and `FinalizationOwnedBy` (which already refuses a missing expiry or a wrong-length hash);
- a constraint would not change recoverability: malformed rows are preserved for the operator either way, and a constraint would only convert a (hypothetical) corrupting write into a failed write;
- a migration would re-open the F1 schema, require the `Down` guard to be revisited and cost a migration test cycle for a defence-in-depth gain, which the plan records as a candidate hardening migration after F4 rather than a silent addition.

If, during implementation, any code path other than the aggregate is found to write these columns, that is a stop-and-report condition and the pairing constraint becomes required.

### 8.8 Where row locks are required and where they must not be held

Required: claim (§7.1), extension (§7.2), publication (§7.4), exhaustion (§7.5), deterministic failure (§7.6), transient note (§7.7). Must not be held: payload load (§7.3), payload hashing/decoding/validation (§6.4), sealing (§6.5), graph building (§6.7), payload cleanup (§7.8, which locks payload rows only), orphan/metric logging.

## 9. Failure taxonomy

### 9.1 Deterministic (terminal via `FailFinalization`; closed vocabulary)

| Code | Cause |
|---|---|
| `vision_finalization_payload_missing` | no payload row for `(job, attempt)` |
| `vision_finalization_payload_integrity_failed` | length/SHA-256 mismatch, or recomputed digest ≠ stored digest(s) |
| `vision_finalization_payload_invalid` | codec decode failure, wrong job/attempt inside payload, validator rejection, non-V3 schema |
| `vision_finalization_staging_missing` | a required staging object is absent |
| `vision_finalization_staging_integrity_failed` | staging size/SHA mismatch, or staging key escapes the media root |
| `vision_finalization_evidence_conflict` | accepted destination exists with different content |
| `vision_finalization_context_invalid` | run not Running / video not Processing / graph rows already exist for the run |
| `vision_finalization_exhausted` | platform reconciliation only (§7.5); never via `FailFinalization` |

Details: at most the failing validator reason code, the sealing category (`crops`/`trajectories`) and the zero-based unit index — never a path, key, token, or exception text. The vocabulary is a `static readonly` set in `VisionFinalizationFailureCodes` (Application) and contract-tested to be exactly this list and to pass `VisionJob.IsFinalizationFailureCode`.

`ProcessingRun.ErrorCode` receives the same code, so status/UI shows a finalization failure distinctly from a detector/tracker failure (B3 plan §17 Status/UI).

### 9.2 Transient (retry via claim release/expiry)

| Code | Cause |
|---|---|
| `vision_finalization_io_transient` | `IOException`/`UnauthorizedAccessException` from sealing not classified above |
| `vision_finalization_db_transient` | `DbUpdateException`/`PostgresException`/`NpgsqlException`/`TimeoutException` from any lifecycle method |
| `vision_finalization_publication_ambiguous` | commit exception in §7.4 step 15 (§10.2) |

Recorded in `FinalizationLastErrorCode` by `NoteTransientAsync` (with `releaseClaim = true`), never in `FailureCode`. Retried by the next claim while attempts and duration remain; exhausted by §7.5.

### 9.3 Lost (no write)

Claim not owned at any revalidation point, or host shutdown cancellation. The executor logs 1512 and returns; the row is untouched.

## 10. Recovery semantics

### 10.1 Restart

A restarting host's first cycle: exhausts abandoned jobs, cleans terminal payloads, reclaims expired claims. Jobs whose claim is still unexpired (the previous process died < `ClaimSeconds`/`ClaimExtensionSeconds` ago) wait out the expiry; nothing is force-reclaimed, because a sibling host could legitimately hold that claim.

### 10.2 Publication ambiguity

- **Exception before `CommitAsync`:** rollback; nothing published; `NoteTransientAsync(db_transient, release)`; retry.
- **`CommitAsync` throws but the commit succeeded:** the executor cannot know. It records `vision_finalization_publication_ambiguous` via `NoteTransientAsync` — which, on a committed job, finds `Status == Completed`, fails `FinalizationOwnedBy`, and writes nothing (`Stale`). On an uncommitted job it records the code and releases the claim. Either way PostgreSQL's state is the answer and the next cycle either finds nothing to do (Completed) or reclaims (Finalizing). No compensation, no delete, no second sequence allocation for a committed run (`AssignCompletionVisibilitySequence` would refuse and the reclaim path never reaches it because the job is not Finalizing).
- **Process death after commit, before logging/cleanup:** the job is Completed; the payload row is cleaned by §7.8 on a later cycle; the orphan/metric log line for that run is lost (accepted).
- **Process death before payload cleanup:** identical; cleanup is idempotent.
- **Process death after `CompleteFinalization` but the transaction never committed:** connection close rolls it back; reclaim after expiry re-seals (adopting identical objects) and republishes.

### 10.3 Retry adopts, never re-creates

Because keys are content-addressed per job/attempt, a retry's `SealAsync` returns `Sealed(CreatedNew=false)` for every object the previous claimant finished, so a retry after mid-seal death costs only the hash verification of existing objects plus the remaining copies.

### 10.4 Orphans

Objects sealed by a claimant that then fails deterministically, or by a stale claimant of a job another claimant finished with the same content, are identical-content objects under the final referenced keys (adopted, not orphaned). True orphans arise only when a job terminally fails after sealing began: those keys are never referenced and remain under `evidence/{jobId}/attempt-NNNN/`. F3 logs their count and bytes (§14) and does nothing else (ADR-006 §5, §7; B3 plan §20).

## 11. Crash and fault matrix

Legend: DB = `vision_jobs` row (and run/video); Ev = accepted-evidence root; Next = what the next cycle/host does; Vis = what readers/status see; End = eventual outcome. "Reclaim" always means after claim expiry unless the claim was released.

| # | Fault point | DB | Ev | Next | Vis | End |
|---|---|---|---|---|---|---|
| 1 | Worker dies after 3.1 accepted, before it logs | Finalizing, unclaimed | none | Claim, finalize | `finalizing`, run Running | Completed (§15) |
| 2 | Host dies after claim commit, before payload load | Finalizing, claim live until expiry | none | Reclaim after expiry (attempt 2) | `finalizing` | Completed or exhausted |
| 3 | Host dies during payload validation | same as 2 | none | same as 2 | same | same |
| 4 | Payload row missing (operator deleted) | Finalizing | none | Claim → `payload_missing` → Failed | `finalizing` → `failed` | Failed (deterministic) |
| 5 | Payload bytes tampered (SHA mismatch) | Finalizing | none | Claim → `payload_integrity_failed` → Failed | → `failed` | Failed |
| 6 | Host dies before first seal | Finalizing, claim live | none | Reclaim; seal from start | `finalizing` | Completed |
| 7 | Host dies mid-seal (batch k) | Finalizing, claim extended to last batch | batches < k created; batch k partial | Reclaim; adopt existing, create rest | `finalizing` | Completed |
| 8 | Claim expires mid-batch (host paused) and another host reclaims | Finalizing, rotated claim | old host's later seals adopted by new claimant or identical | Old host: `ExtendClaimAsync` → Lost; new host finalizes | `finalizing` | Completed; no double publication |
| 9 | Staging directory deleted (janitor bug / operator) | Finalizing | partial | `staging_missing` → Failed | → `failed` | Failed; sealed objects orphaned, logged |
| 10 | Staging object modified | Finalizing | partial | `staging_integrity_failed` → Failed | → `failed` | Failed |
| 11 | Accepted destination exists with other content | Finalizing | conflict object untouched | `evidence_conflict` → Failed | → `failed` | Failed; conflicting object never deleted |
| 12 | Host dies after all seals, before publication tx | Finalizing, claim live | complete | Reclaim; all adopted; publish | `finalizing` | Completed |
| 13 | DB dies during publication bulk insert (step 8) | rolled back | complete | `db_transient` noted, claim released; reclaim, adopt, publish | `finalizing` | Completed |
| 14 | Commit throws, commit actually succeeded | Completed, run Completed, video Processed | complete | Note → Stale (writes nothing); cleanup later | `completed` | Completed |
| 15 | Commit throws, commit did not happen | Finalizing, claim released, `publication_ambiguous` | complete | Reclaim, adopt, publish | `finalizing` | Completed |
| 16 | Host dies after commit, before payload cleanup | Completed | complete | Cleanup on a later cycle | `completed` | Completed |
| 17 | Final permitted claimant dies (attempt = max) | Finalizing, claim expires, attempts exhausted | partial/complete | Reconciliation → `exhausted`; run/video Failed | `finalizing` → `failed` | Failed (exhausted); orphans logged |
| 18 | Duration bound exceeded while unclaimed | Finalizing | any | Reconciliation → `exhausted` | → `failed` | Failed |
| 19 | Two hosts, same job, same instant | one claims, other skips | — | second host takes another job or none | — | one owner (§8.2) |
| 20 | Reconciliation races a live publisher | publisher holds row lock; reconciliation skips | — | next pass finds Completed | `completed` | Completed |
| 21 | Stale claimant attempts `FailAsync` | fenced → Stale; nothing written | — | live claimant proceeds | — | live claimant's outcome |
| 22 | Host shutdown mid-seal | claim live; nothing written | partial | reclaim after expiry (or immediately after restart if expired) | `finalizing` | Completed |
| 23 | Deadline passes while a claim is live and sealing is incomplete | Finalizing, claim live until its granted expiry; extension refused (`DeadlineReached`) | partial | executor stops (1513); claim expires naturally; reconciliation → `exhausted` | `finalizing` → `failed` | Failed no later than deadline + ClaimSeconds + PollInterval |
| 24 | Deadline passes while a claim is live and sealing is complete | as 23 | complete | executor publishes under its live claim; if the claim expires before commit → Stale, then as 23 | `finalizing` → `completed` or `failed` | Completed within the tail, else exhausted |
| 25 | Deadline passes while unclaimed or expired | Finalizing | any | no host can claim (§7.1 predicate + domain); reconciliation → `exhausted` | → `failed` | Failed |
| 26 | Malformed claim metadata (hash without expiry, or expiry without hash) | Finalizing, non-canonical | any | not claimed, not exhausted, not modified; 1512 once per host; `MalformedClaims` in health | `finalizing` (indefinitely, visibly) | Operator investigation |

## 12. Staging and janitor rules

`StagingJanitor.Evaluate` gains an explicit `case VisionJobStatus.Finalizing:` before `default`:

- The current attempt `attempt-{row.AttemptCount:0000}` is **never** eligible.
- Attempts `< row.AttemptCount` are eligible exactly as in the Leased case (they are fenced by the lease authority that superseded them).
- Attempts `> row.AttemptCount` are unexpected: logged once (1401 unrecognised) and preserved.
- `RemoveJobDirectory: false`.
- If `row.AttemptCount == 0` on a Finalizing row (unreachable), `LogInvariantViolation` (1406) and nothing is deleted (fail closed, as today).
- Terminal grace for Completed/Failed is unchanged; once the finalizer publishes or fails, the current attempt becomes reclaimable after `GraceMinutes` as it always was.

The janitor's `LoadRowsAsync` already selects `Status`, `AttemptCount`, `CompletedAtUtc`; no query change. Direct janitor change is therefore required but small (one `case`). The 1406 misreport for Finalizing rows disappears as a side effect.

Ordering hazard: the janitor and the finalizer read the row at different instants. The only dangerous interleaving would be the janitor reading `Leased` (attempt N-1 eligible), the job moving to `Finalizing` at attempt N, and the janitor deleting attempt N. That cannot happen: a Leased row at attempt N makes only attempts `< N` eligible, and a hand-off never lowers `AttemptCount`. Test §15.3 pins this.

## 13. Activation and deployment

### 13.1 Sequence (B3 plan §15)

1. Deploy the F3 binary with `VisionFinalization:Enabled = false`. The hosted service logs 1500 and idles. Probe still `["2.0","3.0"]`; nothing enters Finalizing.
2. Verify health: `/api/health` shows `visionFinalization.enabled = false`, no errors at start (options validated even while disabled).
3. Set `VisionFinalization:Enabled = true` on the platform and restart. Probe now `["2.0","3.1"]`; 3.0 refused; the finalizer polls.
4. Set `MAVI_COMPLETION_SCHEMA_VERSION=3.1` on every worker and restart them. Until this step, 3.0 workers fail closed at the probe and lease nothing (F2 split-brain rule) — this is the intended brief outage, not a fallback.
5. 3.0 is retired.

### 13.2 Unsafe combinations and their prevention

| Combination | Effect | Prevention |
|---|---|---|
| Platform `Enabled=true`, worker 3.0 | worker probe fails closed; no leases | existing F2 behaviour |
| Platform `Enabled=false`, worker 3.1 | worker probe fails closed | existing F2 behaviour |
| `Enabled=true` but hosted service not registered | jobs stranded Finalizing | `Program.cs` registers unconditionally; an integration test asserts the service is resolvable when `Enabled=true` (§15.2) |
| `MaximumFinalizationDurationSeconds < ClaimSeconds` | nothing claimable | options validation |
| Two API hosts with different `Enabled` | one advertises 3.1 and finalizes; the other refuses 3.1 and idles. Jobs handed to host A are finalized by A; workers probing B fail closed. | Not preventable by code; runbook rule: the gate is one value per deployment. Health exposes `enabled` per host for verification. |
| Rollback to a pre-F1 binary with Finalizing rows | migration Down refuses (F1) | existing |

### 13.3 Rollback

Setting `Enabled=false` stops **new** hand-offs (the probe reverts to 3.0) and also stops claiming, extension, reconciliation and cleanup, so Finalizing rows must be drained first. Decision: the finalizer writes iff `Enabled` (running it whenever Finalizing rows exist would be a hidden behaviour, rejected); while disabled it only refreshes the health counts (§6.8).

Runbook procedure, using the health contract of §6.9:

1. Set every worker to `MAVI_COMPLETION_SCHEMA_VERSION=3.0` and restart them. They fail closed at the probe (the platform still advertises 3.1), so no new hand-off can occur.
2. Poll `GET /api/health` until `visionFinalization.finalizingJobs == 0` **and** `visionFinalization.countsRefreshedAtUtc` is within the last two `PollIntervalSeconds`, on **every** API host. `finalizingJobs` is the PostgreSQL row count, so one host's answer covers the deployment, but each host's `enabled` is checked to confirm the gate is uniform.
3. If `visionFinalization.malformedClaims > 0`, stop and investigate: those rows will never drain on their own (§5.2).
4. Set `VisionFinalization:Enabled=false` on every API host and restart. The probe reverts to `["2.0","3.0"]`.

A pre-F1 binary is never deployed while Finalizing rows exist (migration `Down` refuses, B3 plan §15.3).

## 14. Observability

Event ids 1500–1519 (`LoggerMessage` in the hosted service and lifecycle; ≤6 type args each):

| Id | Level | Event |
|---|---|---|
| 1500 | Info | finalizer disabled |
| 1501 | Info | finalizer started (poll, claim, extension, max attempts, max duration, concurrency) |
| 1502 | Info | claimed (job, worker attempt, finalization attempt, expires) |
| 1503 | Debug | claim extended (job, batch index, new expiry) |
| 1504 | Info | published (job, run, tracks, objects created, objects adopted, bytes, seal ms, publish tx ms, total ms, hand-off→publish latency s) |
| 1505 | Warning | deterministic failure (job, code, details-safe) |
| 1506 | Warning | transient failure noted (job, code, finalization attempt) |
| 1507 | Warning | claim lost (job, at step) |
| 1508 | Error | exhausted by reconciliation (job, attempts, age s, last error code) |
| 1509 | Warning | orphan accounting after failure (job, created count, created bytes, adopted count) |
| 1510 | Info | payload rows cleaned (count) |
| 1511 | Error | cycle failed (exception) |
| 1512 | Error | invariant (context invalid / graph exists / run transition refused / SQL–domain disagreement / **malformed claim metadata**, once per job per host lifetime) |
| 1513 | Warning | finalization deadline reached with a live claim (job, finalization attempt, sealed/total units, claim expiry); no further extension |

Never logged: token, token hash, lease token, storage paths, exception messages from the filesystem (log the exception type only, as `runner.py:811` does on the worker side).

Metrics (via the `IVisionFinalizationMonitor` snapshot in health, and the 1504 line for offline analysis; no new metrics library): `finalizingJobs`, `liveClaims`, `malformedClaims`, oldest Finalizing accepted-at, counts timestamp, in-flight, claimed/exhausted per cycle, last publish duration, last seal duration. F4 records baseline API p95 latency, host RSS and throughput with the finalizer active (B3 plan §13); F3 only ensures the numbers are emitted.

## 15. Test matrix

Every critical test lists the **mutant** it must kill (a compile-safe single change that the test must fail on). Mutants are applied manually during review of the slice, not automated.

### 15.1 Domain (`tests/Mavi.Domain.Tests/VisionFinalizationDomainTests.cs`, extended)

| Test | Mutant killed |
|---|---|
| `ExhaustFinalizationRequiresNoLiveClaim` | remove the live-claim check → test expects throw with an unexpired claim |
| `ExhaustFinalizationRequiresAttemptOrDurationExhaustion` | change `>=` to `>` on attempts; change duration comparison |
| `ExhaustFinalizationTakesNoTokenAndCannotPublish` | (structural: signature has no token; status is Failed not Completed) |
| `ExhaustFinalizationRetainsHandOffFacts` | clear `CompletionDigest` |
| `ExhaustFinalizationOnlyFromFinalizing` | allow from Leased |
| `CanClaimFinalizationHonoursTheDurationBound` (`NoNewClaimAfterMaximumFinalizationDuration`: at `now == deadline` and after, not claimable; at `deadline − 1 tick`, claimable) | drop the duration term; change `<` to `<=` |
| `ClaimFinalizationItselfRefusesAtOrAfterMaximumFinalizationDuration` (valid Finalizing job, no claim; `now == deadline` → `ClaimFinalization(hash, now, duration, max, maxDuration)` throws; `now > deadline` → throws; in both cases `FinalizationAttemptCount`, token hash, expiry and extended-at are unchanged, i.e. still 0/null/null/null; the test calls the transition, not `CanClaimFinalization`) | make `ClaimFinalization` call the deadline-blind predicate, or ignore `maximumFinalizationDuration` (both compile-safe) |
| `ClaimFinalizationSucceedsImmediatelyBeforeMaximumFinalizationDuration` (`now == deadline − 1 tick` → claim taken; attempt 1, hash/expiry/extended-at set) | — (positive control) |
| `ClaimCanBeExtendedBeforeMaximumFinalizationDuration` | — (positive control) |
| `ClaimCannotBeExtendedAfterMaximumFinalizationDuration` (live claim, `now == deadline` → throws; `now > deadline` → throws; expiry unchanged) | remove the deadline check in `ExtendFinalizationClaim` |
| `DurationExceededLiveClaimIsNotKilledImmediately` (`FinalizationOwnedBy` true after the deadline while `expiry > now`; `CompleteFinalization` still succeeds) | make `FinalizationOwnedBy` consult the deadline |
| `DurationExceededLiveClaimExpiresThenExhaustionApplies` (after the deadline: `ExhaustFinalization` throws while live; succeeds once `now ≥ expiry`) | drop the live-claim check |
| `ClaimStateClassificationIsCanonical` (theory over all 8 null-combinations × hash length: exactly three canonical states; all others `Malformed`) | treat hash-without-expiry as `Unclaimed` (the OR mutant) |
| `MalformedClaimIsNotClaimableNotExhaustibleNotOwned` (hash without expiry; expiry without hash; missing extended-at) | change the paired check back to `||` semantics |
| `CanonicalExpiredClaimIsReclaimable` | — (positive control) |
| `ReleaseFinalizationClaimIsFencedAndMakesTheJobReclaimable` | remove `FinalizationOwnedBy` check; set expiry to `now + 1s` instead of `now` |
| `ExhaustedCodeIsInTheClosedVocabulary` | rename the code |

### 15.2 Application / contract (`tests/Mavi.Application.Tests`)

| Test | Mutant killed |
|---|---|
| `FailureCodeVocabularyIsExactlyTheDocumentedSet` | add/remove a code |
| `EvidenceSealingPlanReproducesTheSynchronousKeys` (golden keys for a 3-track fixture; crops rank-ordered then trajectory) | swap order; change key template |
| `EvidenceSealingPlanEnforcesTheAdmittedCropQuota` | remove the quota |
| `GraphBuilderIsPureAndDeterministic` (same input → same plan; representative pairing correct) | pick `Observations[1]` as representative |
| `ValidatorBindsStagingKeysToTheRoutedJobAndAttempt` (a key for another job/attempt is rejected) | remove the prefix check in the validator |
| `OptionsValidationRejectsEveryUnsafeCombination` (theory over §6.1 rules) | drop any one rule |

### 15.3 Integration (`tests/Mavi.IntegrationTests`, `mavi_test`, `EnableAsynchronousFinalization = true`, finalizer host **off**; tests drive `RunCycleAsync`/lifecycle directly)

New files: `VisionFinalizationLifecycleTests.cs`, `VisionFinalizationExecutorTests.cs`, `VisionFinalizationHostTests.cs`, `VisionFinalizationRecoveryTests.cs`, `VisionFinalizationJanitorTests.cs`, `VisionFinalizationStatusTests.cs`.

| Test | Proves | Mutant killed |
|---|---|---|
| `HandOffThenOneCyclePublishesTheGraph` | end-to-end: 3.1 POST → cycle → Completed, run Completed with sequence, video Processed, tracks/observations/artifacts with accepted keys, staging retained, payload row cleaned on a later cycle | — (happy path) |
| `NothingIsVisibleBeforeThePublicationCommit` (fault: `CommitBoundaryFaults` throw at commit) | no tracks, run Running, video Processing, sequence not consumed by a committed run | remove barrier ordering |
| `VisibilityBarrierIsAcquiredAfterGraphPersistence` (SQL capture: advisory lock statement after the bulk INSERTs) | ordering §7.4 | move step 10 before step 8 |
| `ClaimIsExclusiveUnderConcurrency` (two lifecycles claim concurrently 20×; exactly one wins each) | I2 | drop `SKIP LOCKED`/`FOR UPDATE` |
| `ExpiredClaimIsReclaimedWithARotatedToken` (`MutableTimeProvider`) | rotation | keep old hash |
| `NoNewClaimAfterMaximumFinalizationDuration` (lifecycle: advance past the deadline; `ClaimNextAsync` returns null; SQL capture shows the row not selected) | §7.1 / I13 | drop the accepted-at term from the SQL |
| `ClaimSqlAndDomainAgreeAtTheDeadlineInstant` (row accepted at T; clock = T + MaximumDuration exactly: SQL does not select; loading the row `FOR UPDATE` in a test transaction and calling `ClaimFinalization(…, policy.MaximumDuration)` on it throws and leaves it unchanged; at T + MaximumDuration − 1 tick both select and claim succeed) | §8.6 | change either inequality; drop `maximumFinalizationDuration` from the lifecycle call |
| `ClaimCannotBeExtendedAfterMaximumFinalizationDuration` (lifecycle: `ExtendClaimAsync` → `DeadlineReached`; expiry unchanged; ownership still true) | §7.2 | remove the deadline from `ExtendFinalizationClaim` |
| `DurationExceededLiveClaimIsNotKilledImmediately` (reconciliation returns 0 while the claim is live past the deadline) | §5.4 item 4 | let reconciliation ignore live claims |
| `DurationExceededLiveClaimExpiresThenReconciliationExhausts` (advance to expiry; reconciliation → `exhausted`, run/video Failed; no new claim was possible in between) | §5.4 | — |
| `ExecutorStopsSealingWhenTheDeadlineIsReached` (batch size 2, 6 units, deadline passes after batch 1: 1513 logged, ≤ 4 units sealed, nothing published, job still Finalizing) | §6.6 | keep sealing |
| `ExecutorPublishesAfterTheDeadlineIfSealingWasComplete` (deadline passes after the last batch: publication succeeds under the live claim) | §6.6 | refuse publication after the deadline |
| `MalformedClaimIsNeverClaimedOrExhausted` (raw `UPDATE` sets hash without expiry, and separately expiry without hash, and separately clears extended-at: `ClaimNextAsync` null, reconciliation 0, row bytes unchanged, 1512 logged once across two cycles, `malformedClaims == 1` in health) | §5.2 / I14 | OR-semantics in either predicate |
| `CanonicalExpiredClaimIsReclaimable` (positive control for the previous row) | §5.2 | — |
| `StaleClaimantCannotPublish` (claim A; advance clock; claim B; A calls `PublishAsync` → Stale, nothing written; B publishes) | I3 | remove step 4/13 fence |
| `StaleClaimantCannotFail` | I3 | remove fence in `FailFinalization` use |
| `StaleClaimantCannotNoteTransient` | §8.5 | remove ownership check in `NoteTransientAsync` |
| `StaleClaimantCannotExtend` | | remove fence |
| `LiveClaimIsExtendedBetweenBatches` (SealingBatchSize=2, 5 objects → 3 extensions; expiry advances) | §6.6 | extend only at start |
| `ClaimLostMidSealStopsWithoutWriting` (rotate the claim between batches via a second lifecycle) | §6.6 | ignore Lost |
| `RetryAdoptsIdenticalAcceptedObjects` (pre-seal half the objects; run; `CreatedNew=false` count matches; no delete) | §10.3 | — |
| `ConflictingAcceptedObjectFailsClosed` (pre-place different content) | §9.1 `evidence_conflict`; object untouched | map conflict to adopt |
| `NoPathDeletesAcceptedEvidence` (architecture: no F3 type references `DeleteAcceptedAsync`; plus behavioural: after every failure test the evidence root file set is a superset of before) | I6 | call delete on failure |
| `PayloadMissingFailsDeterministically` / `PayloadTamperedFailsDeterministically` (raw `UPDATE` of bytea) / `PayloadInvalidFailsDeterministically` (raw bytes) / `DigestMismatchFailsDeterministically` (raw `UPDATE` of `completion_digest`) | §6.4 codes; run/video Failed with the same code; staging retained | skip a check |
| `StagingMissingFailsDeterministically` / `StagingTamperedFailsDeterministically` / `StagingEscapeFailsDeterministically` (symlinked staging key) | §9.1 | collapse classes |
| `TransientIoIsNotedAndReclaimed` (`IAcceptedEvidenceStore` decorator throws `IOException` once) | §9.2; `FinalizationLastErrorCode` set; attempt 2 succeeds | treat as deterministic |
| `TransientDbIsNotedAndReclaimed` (interceptor fault on the bulk insert) | §9.2 | — |
| `AmbiguousCommitThatSucceededIsNotRepublished` (`CommitBoundaryFaults` throw-after-commit) | §10.2; one sequence; Completed; note writes nothing | second publish |
| `AmbiguousCommitThatFailedIsRetried` | §10.2 | — |
| `FinalPermittedClaimantCrashIsExhaustedByReconciliation` (max attempts 1; claim; advance clock past expiry; reconciliation → Failed `exhausted`; run/video Failed) | §7.5 | remove reconciliation |
| `DurationBoundIsExhaustedByReconciliation` | §5.4 | — |
| `ReconciliationSkipsALiveClaim` and `ReconciliationSkipsARowLockedByAPublisher` (open a publication tx in a second context, run reconciliation, assert 0) | §8.4 | drop `SKIP LOCKED`/live-claim predicate |
| `ReconciliationCannotPublish` (structural + behavioural: exhausted job has no tracks) | §5.3 | — |
| `HostRecoversFinalizingRowsOnStartup` (seed Finalizing rows with expired claims; start host with `Enabled`; one cycle finalizes) | §10.1 | — |
| `HostBoundsConcurrency` (3 jobs, `MaxConcurrentFinalizations=1`, seals block on a gate; assert one in flight) | §6.8 | drop semaphore |
| `HostShutdownDoesNotFailTheJob` (cancel during sealing; row still Finalizing; no failure code) | §6.8 | write failure on cancel |
| `HostIdlesWhenDisabled` (`Enabled=false`; seeded Finalizing row untouched; 1500 logged) | §13 | — |
| `HostedServiceIsRegisteredWhenEnabled` | §13.2 | drop registration |
| `HealthExposesTheFinalizingRowCount` (`finalizingJobs` equals a raw `COUNT(*)`; `countsRefreshedAtUtc` set after one cycle) | §6.9 | derive from in-flight |
| `FinalizingJobsCountIncreasesAfterHandOff` (3.1 POST ×2 → cycle count step → 2) | §6.9 | — |
| `FinalizingJobsCountReturnsToZeroAfterPublishFailAndExhaust` (three jobs: one publishes, one fails deterministically, one is exhausted → 0) | §6.9 | — |
| `FinalizingJobsTransitionsToZeroAfterDrain` (host enabled, two Finalizing rows, no new hand-offs; cycles until `finalizingJobs == 0`; then `Enabled=false` factory shows 0 with a refreshed timestamp) | §13.3 | stop counting when disabled |
| `DisabledHostRefreshesCountsButWritesNothing` (`Enabled=false`, seeded Finalizing row: count 1, row untouched, no claim, 1500 logged) | §6.8 | — |
| `WorkerDeathAfterHandOffDoesNotMatter` (3.1 POST; never touch the worker again; cycle → Completed; replay 3.1 → `completed`) | §15 request item | — |
| `ReplayAfterPublicationReportsCompleted` (F2 replay branch end-to-end) | §4.4 | — |
| `JanitorPreservesTheCurrentFinalizingAttempt` / `JanitorReclaimsSupersededAttemptsOfAFinalizingJob` / `JanitorPreservesMalformedFinalizingState` / `JanitorNoLongerReports1406ForFinalizing` / `JanitorTerminalGraceUnchangedAfterFinalization` | §12 | delete current attempt |
| `StatusShowsFinalizingUntilPublication` (phase `finalizing`, run Running, video Processing, counters 0/unpublished; after cycle `completed` with counts) | I11 | — |
| `FinalizationFailureIsNotLabelledAsInferenceFailure` (run `ErrorCode` = `vision_finalization_*`) | §9.1 | — |
| `LogsContainNoTokenPathOrExceptionText` (`CapturingLoggerProvider` scan over every F3 test's logs for the raw token base64, the media root path, `Exception:`) | I7 | log the path |
| `SynchronousPathStillUsesTheSharedComponents` (existing `VisionResultCompletionApiTests` and `VisionResultCompletionV3ApiTests` pass unchanged after extraction; a golden-key test proves the same accepted keys) | §16 slice 2 | — |

### 15.4 Timing / memory (opt-in, `MAVI_F3_TIMING_TRACKS`)

Extend `VisionFinalizationSubmissionTimingTests` with a finalizer run at N tracks recording payload load/validate ms, seal ms, graph build ms, publish tx ms, RSS before/after. Not asserted against a bound in F3 (F4 freezes bounds).

### 15.5 Worker (Python) — no new behaviour; regression only

Existing `test_lease_ownership_matrix.py` / runner tests already cover: 3.1 required, Finalizing acknowledgement ends the attempt, staging retained, replay accepted, no fallback. F3 adds nothing to the worker.

### 15.6 Qualification guards

`s1_evidence.py` is **not** changed in F3 (F4 replaces the B3 criterion). The plan-qualification test (`PlanQualificationTests`) is untouched.

## 16. Implementation sequence (slices)

Each slice is one reviewable commit (or a small PR if the owner prefers) on `feature/stage2-s1-2c-evidence-set-v3-worker` or a dedicated `feature/s1-4-b3-f3-finalizer` branch from `26b44f5`. Validation command for every slice: `dotnet build MAVI.sln --configuration Release` (warnings are errors) and the listed test filters with `MAVI_TEST_DB_CONNECTION` set; `python tools/verify_repo.py` at the end of the last slice.

### Slice 1 — Domain: exhaustion, release, duration bound

- **Files:** `src/platform/Mavi.Domain/Processing/VisionJob.cs`; `tests/Mavi.Domain.Tests/VisionFinalizationDomainTests.cs`.
- **Tests first:** §15.1 (8 tests).
- **Work:** `FinalizationDeadline(maxDuration)`, `FinalizationClaimStateAt(now)` + `FinalizationClaimState`, `ExhaustFinalization` (canonical no-live-claim), `ReleaseFinalizationClaim`, `CanClaimFinalization(now, max, maxDuration)` replacing the two-argument overload, `ClaimFinalization(hash, now, claimDuration, max, maxDuration)` replacing the four-argument signature, `ExtendFinalizationClaim(token, now, extension, maxDuration)` replacing the three-argument signature (all three retirements are compile-time breaking on purpose: no caller may bypass the deadline; the only production caller of the old `ClaimFinalization` is none at `26b44f5`, and the F1 domain tests are updated); `vision_finalization_exhausted` constant.
- **Invariants proven:** I3 (release fenced), I9 (exhaustion cannot publish, needs no token), I13 (deadline refuses claim and extension), I14 (canonical states; malformed fails closed).
- **Validate:** `dotnet test tests/Mavi.Domain.Tests`.
- **Stays disabled:** everything; no host code yet.

### Slice 2 — Extract shared sealing plan and graph builder (behaviour-preserving)

- **Files:** new `Application/Modules/Intelligence/EvidenceSealingPlan.cs`, `FinalizationGraphBuilder.cs`; `Infrastructure/.../ProcessingResultStore.cs` (calls the shared components; keeps its transaction shape and its compensation deletion); `tests/Mavi.Application.Tests/EvidenceSealingPlanTests.cs`, `FinalizationGraphBuilderTests.cs`.
- **Tests first:** §15.2 golden-key and builder tests, written against the **current** synchronous behaviour before the move.
- **Work:** move `AcceptedEvidenceKey`, the quota defence and the graph loop; `ProcessingResultStore` becomes a thin caller. No behaviour change: `VisionResultCompletionApiTests`, `VisionResultCompletionV3ApiTests`, `VisionResultCompletionCommitFailureTests` must pass unchanged.
- **Invariants proven:** one sealing/graph implementation (§22 of the request); 2.0/3.0 unchanged.
- **Validate:** `dotnet test tests/Mavi.Application.Tests`; `dotnet test tests/Mavi.IntegrationTests --filter "FullyQualifiedName~VisionResultCompletion"`.
- **Stays disabled:** finalizer.

### Slice 3 — Options, policy, failure vocabulary

- **Files:** `Application/Modules/Intelligence/VisionFinalizationOptions.cs`, new `VisionFinalizationPolicy.cs`, `VisionFinalizationFailureCodes.cs`; `Infrastructure/DependencyInjection.cs` (validation chain); `Api/appsettings.json` (full section, `Enabled: false`); `tests/Mavi.Application.Tests/VisionFinalizationOptionsTests.cs`; `tests/Mavi.IntegrationTests/ConfigurationValidationTests.cs` (start-up failure cases).
- **Tests first:** §15.2 options and vocabulary tests.
- **Invariants proven:** §13.2 code-preventable combinations.
- **Validate:** Application tests; `ConfigurationValidationTests`.
- **Stays disabled:** finalizer (`Enabled=false`; no host registered yet).

### Slice 4 — Lifecycle: claim, extend, load, note, fail, exhaust, cleanup

- **Files:** new `Application/Modules/Intelligence/IVisionFinalizationLifecycle.cs` (+ claim/transition records); new `Infrastructure/Persistence/Repositories/VisionFinalizationLifecycle.cs`; `DependencyInjection.cs` (scoped registration); `tests/Mavi.IntegrationTests/VisionFinalizationLifecycleTests.cs`.
- **Tests first:** claim exclusivity, rotation, stale extend/fail/note, deadline (no new claim; SQL–domain boundary agreement; `DeadlineReached`), reconciliation (skip live, skip locked, cannot publish, duration-exceeded live claim not killed then exhausted after expiry), malformed rows (never selected, reported, unchanged), `CountAsync`, cleanup idempotence, no-lock payload load (SQL capture shows no `FOR UPDATE`).
- **Invariants proven:** I1, I2, I3, I9, I13, I14, §8.8 lock discipline.
- **Validate:** `--filter "FullyQualifiedName~VisionFinalizationLifecycle"`.
- **Stays disabled:** publication (`PublishAsync` lands in slice 5), host.

### Slice 5 — Publication transaction

- **Files:** `VisionFinalizationLifecycle.cs` (`PublishAsync`); `tests/Mavi.IntegrationTests/VisionFinalizationPublicationTests.cs`.
- **Tests first:** ordering via SQL capture, nothing-visible-before-commit, stale cannot publish, ambiguous commit both ways, context invalid, graph-exists guard, one sequence per run.
- **Invariants proven:** I4, I5 (publication reads accepted keys it did not create), §7.4 ordering.
- **Validate:** `--filter "FullyQualifiedName~VisionFinalizationPublication"`.
- **Stays disabled:** host.

### Slice 6 — Executor: payload integrity, sealing batches, extension, failure classes, orphan accounting

- **Files:** new `Infrastructure/Finalization/VisionFinalizationExecutor.cs` (+ `SealingOutcome` classification); `tests/Mavi.IntegrationTests/VisionFinalizationExecutorTests.cs`; architecture test in `tests/Mavi.Domain.Tests/ArchitectureBoundaryTests.cs` or a new `tests/Mavi.IntegrationTests/VisionFinalizationBoundaryTests.cs` asserting no F3 type references `DeleteAcceptedAsync`.
- **Tests first:** §15.3 payload/staging/conflict/transient/adopt/lost-mid-seal/extension cadence/deadline-reached (stop sealing; publish only if complete)/no-delete/log hygiene.
- **Invariants proven:** I6, I7, I12, I13 (executor side), §6.6.
- **Validate:** `--filter "FullyQualifiedName~VisionFinalizationExecutor"`.
- **Stays disabled:** host.

### Slice 7 — Hosted service, health, registration

- **Files:** new `Api/Finalization/VisionFinalizationHostedService.cs`, `IVisionFinalizationMonitor`/state; `Api/Program.cs`; `Application/Health/GetPlatformHealth.cs` (+ `PlatformHealthDetails`); `tests/Mavi.IntegrationTests/ApiTestFactory.cs` (`EnableVisionFinalizationHost` switch, off by default); `VisionFinalizationHostTests.cs`, `HealthApiTests.cs`.
- **Tests first:** startup recovery, concurrency bound, shutdown does not fail, disabled refreshes counts but writes nothing, registered when enabled, health shape including `finalizingJobs`/`liveClaims`/`malformedClaims`/`countsRefreshedAtUtc`, count transitions (hand-off up; publish/fail/exhaust to zero; drain to zero).
- **Invariants proven:** I8, §6.8, §6.9.
- **Validate:** `--filter "FullyQualifiedName~VisionFinalizationHost|FullyQualifiedName~HealthApi"`.
- **Stays disabled:** production `Enabled` remains `false` in `appsettings.json`.

### Slice 8 — Janitor Finalizing rule

- **Files:** `Infrastructure/Storage/StagingJanitor.cs`; `tests/Mavi.IntegrationTests/StagingJanitorTests.cs` (or new `VisionFinalizationJanitorTests.cs`).
- **Tests first:** §15.3 janitor rows.
- **Invariants proven:** I10.
- **Validate:** `--filter "FullyQualifiedName~StagingJanitor"`.

### Slice 9 — End-to-end recovery, status, replay, worker-independence, timing harness

- **Files:** `VisionFinalizationRecoveryTests.cs`, `VisionFinalizationStatusTests.cs`, `VisionFinalizationSubmissionTimingTests.cs` (extension).
- **Tests first:** the remaining §15.3 rows and §15.4.
- **Invariants proven:** I11, §10, §11 rows 1, 7, 8, 12–17.
- **Validate:** full `dotnet test tests/Mavi.IntegrationTests` (serial; shared `mavi_test`).

### Slice 10 — Docs and records

- **Files:** B3 plan §16 "F3 implementation record"; ADR-006 §7 status line (F3 landed; no rule change); `docs/runbooks/vision-runtime-model-component-lifecycle.md` (activation sequence §13.1, rollback drain procedure §13.3 naming `visionFinalization.finalizingJobs`, `countsRefreshedAtUtc` and `malformedClaims`, the effective duration bound `MaximumFinalizationDurationSeconds + ClaimSeconds`, health fields, event ids 1500–1513, and the malformed-claim operator procedure: investigate, never repair automatically); `contracts/README.md` if any finalization failure code is surfaced to the worker (none expected); `config/dependencies/offline-dependency-policy-v1.json` **unchanged** (no new dependency — assert in the PR description).
- **Validate:** `python tools/verify_repo.py`; `pytest tools/phase1/tests` (known environmental failures noted in the PR).

Slices 1–3 are independent and may be reviewed in any order; 4 depends on 1 and 3; 5 on 4 and 2; 6 on 5; 7 on 6; 8 is independent; 9 on 7 and 8; 10 last.

## 17. F4 qualification hand-off

Not part of F3. After F3 merges and the configuration values in §6.1 are reviewed:

1. Choose the new exact `main` SHA.
2. Replace the B3 synchronous harness (`S1SealingScaleTests` posting 3.0; checker `completion_headroom_insufficient`/sealing-wall metrics) with B3-A (3.1 hand-off request bound, 15 s, real payload insert and transition) and B3-B (hand-off → publication wall clock through the real host, lifecycle and DB).
3. Run B3-A on Linux and Windows.
4. Measure asynchronous finalization at the 10,000-Track envelope: seal duration, publish transaction duration, extension count, host RSS, API p95 latency under concurrent finalization, throughput, orphan bytes after the fault matrix.
5. Freeze `MaximumFinalizationDurationSeconds` (and `ClaimSeconds`/`ClaimExtensionSeconds`/`SealingBatchSize`) from product requirements plus measurement. The B3-B bound F4 asserts is the **enforced** bound of §5.4: a job is Completed or Failed no later than `FinalizationAcceptedAtUtc + MaximumFinalizationDuration + ClaimSeconds + PollInterval`, and the crash-matrix mutants for rows 23–25 must show the deadline refusing extension and claim, not merely the executor choosing to stop.
6. Re-run authoritative B3-B after the freeze.
7. Run the crash matrix (§11) as discriminated mutants in the checker's B3 proving set.
8. Re-run every S1 unit the F1–F3 diff invalidates (B1/B2/B4/B5/B6, disconnected) per the invalidation map; do not carry forward prior PASS results.
9. Write the closure record.

## 18. Non-goals (F3)

No S2 attributes, OCR/ANPR, ReID; no selector/scorer changes; no bulk COPY or parallel sealing unless F4 measurement demands it; no separate finalizer executable; no generic workflow/job engine; no distributed lock outside PostgreSQL; no filesystem manifest; no orphan collector; no accepted-evidence format change; no model accuracy work; no CUDA work; no schema migration; no worker (Python) behaviour change; no change to the qualification checker.

## 19. Completion criteria

F3 is complete when all of the following hold on the implementation branch:

1. Every slice in §16 is merged with its tests, and every mutant in §15 was applied and killed during review (recorded in the PR).
2. `dotnet build MAVI.sln --configuration Release` is warning-free; `python tools/verify_repo.py` passes; the full .NET test suites pass serially against `mavi_test`.
3. `VisionFinalization:Enabled` is still `false` in `appsettings.json`; with it `true` in a test factory, a 3.1 hand-off is published by one host cycle and the §11 matrix rows are covered by tests.
4. No F3 code references `IAcceptedEvidenceStore.DeleteAcceptedAsync` (architecture test).
4a. The deadline mutants (`ClaimFinalizationItselfRefusesAtOrAfterMaximumFinalizationDuration`, `ClaimCannotBeExtendedAfterMaximumFinalizationDuration`, `NoNewClaimAfterMaximumFinalizationDuration`) and the malformed-state OR-mutant were applied and killed.
4c. No domain method that creates or prolongs a finalizer claim lacks a `maximumFinalizationDuration` parameter (reviewer grep over `VisionJob.cs` for `ClaimFinalization(`, `CanClaimFinalization(`, `ExtendFinalizationClaim(`).
4b. `/api/health` exposes `visionFinalization.finalizingJobs` from PostgreSQL and the runbook rollback procedure names it.
5. No schema change and no new dependency (`offline-dependency-policy-v1.json` untouched).
6. The runbook documents activation (§13.1), the drain-before-disable rollback rule (§13.3) and the health fields.
7. §19.3 below is confirmed by the reviewer.

### 19.1 ADR amendment

**None required.** ADR-006 §7 already records every rule this plan implements (PostgreSQL authority, capability-free payload, sealing before publication, no compensation deletion, separate fenced claim, staging retention, janitor rule). Slice 10 updates only the status line ("F3 landed") and adds no decision. If the implementation discovers a need for a schema change or a rule not in §7, that is a new ADR amendment and a stop-and-report condition.

### 19.2 Configuration values that F3 ships but does not freeze

`ClaimSeconds`, `ClaimExtensionSeconds`, `MaximumFinalizationAttempts`, `MaximumFinalizationDurationSeconds`, `SealingBatchSize`, `PollIntervalSeconds`. Their development defaults are chosen to be safe (generous) and are explicitly labelled "F4 freezes" in `appsettings.json` comments and the runbook.

### 19.3 Reviewer confirmation list

The reviewer of the last F3 slice confirms in the PR: no production code path deletes accepted evidence; no token reaches a log or row; every outcome-changing write is fenced by `FinalizationOwnedBy` under `FOR UPDATE`; exhaustion is a separate, tokenless, failure-only transition that requires a canonical no-live-claim state; no code path can claim or extend at or after the finalization deadline, and `ClaimFinalization` itself carries and enforces the maximum duration; malformed claim metadata is never claimed, exhausted or modified; the janitor never selects the current Finalizing attempt; the synchronous 2.0/3.0 path is behaviourally unchanged.

## 20. Self-review (cold, as a non-author)

Attack surfaces from the request, with the finding, severity, and the amendment already folded into the sections above.

| Attack | Finding | Severity | Resolution |
|---|---|---|---|
| Stale claimant publication | `PublishAsync` early-exits on ownership and the domain re-proves in `CompleteFinalization` under the same row lock; the plan built by a stale claimant cannot be committed. Gap found: a plan built for worker attempt N by a claimant that read the job before a *new* hand-off at attempt N+1 (impossible today because Finalizing blocks re-lease, but cheap to guard). | P3 | §7.4 step 5 identity proof added (attempt, digest, finalization attempt). |
| Stale claimant terminal failure | `FailFinalization` fenced (F1 repair). Gap found: `NoteFinalizationError` is **not** fenced, so a stale claimant could overwrite `FinalizationLastErrorCode` of the live attempt. | **P2** | §7.7/§8.5: lifecycle proves ownership under lock before calling it; test + mutant. |
| Final permitted claimant crash | Without a tokenless exhaustion transition the job would stay Finalizing forever (F1 `Exhaust` throws from Finalizing). | **P1** (known from B3 plan §10.8) | §5.3 `ExhaustFinalization`, §7.5 reconciliation with `SKIP LOCKED`, tests + mutants. |
| Ambiguous DB commit | Retrying a commit or compensating would double-publish or delete. | P2 | §10.2: never retry the transaction object; note-as-transient is itself fenced so it writes nothing on a Completed job; test both branches with `CommitBoundaryFaults`. |
| Accepted-evidence deletion races | The extracted sealing component must not carry the synchronous compensation into the finalizer. | P2 | Compensation stays in `ProcessingResultStore` only; architecture test forbids `DeleteAcceptedAsync` references in F3 types; behavioural superset test. |
| Orphan handling | No collector; must at least be observable. | P3 | §14 event 1509 counts/bytes; F4 measures orphan bytes across the fault matrix. |
| Payload tampering | SHA and digest recomputed; but a tampered `completion_digest` column on the job with a matching tampered payload would pass. | P3 (requires DB write access, out of the threat model) | Digest is also compared to the claim-time snapshot and to the validator's recomputation; documented as a DB-integrity assumption. |
| Staging disappearance | Janitor already fails closed for Finalizing via `default`, but logs 1406 every cycle, which would train operators to ignore that Error. | P2 | §12 explicit Finalizing case; test that 1406 is no longer emitted for Finalizing. |
| Visibility ordering | Same as synchronous path; bulk insert before the barrier. | — | §7.4; SQL-capture test. |
| Partial relational publication | Single transaction; readers gate on run status + sequence. | — | Fault test at commit. |
| Claim extension race | Extension after each batch could extend a claim that a reclaimer rotated between batches. | — | `ExtendFinalizationClaim` is fenced on the token; rotated hash ⇒ Lost. Test. |
| Configuration split-brain | Two API hosts with different `Enabled`. | P2 (operational) | Not code-preventable; §13.2 runbook rule + health exposes `enabled`; validation prevents every single-host unsafe combination. |
| Two-host concurrency | `SKIP LOCKED` + fenced transitions. | — | §8.2 proof; concurrency test. |
| Worker death after hand-off | Nothing depends on the worker after the 3.1 commit. | — | §11 row 1; dedicated test. |
| Janitor deleting Finalizing staging | See "staging disappearance"; plus the Leased→Finalizing ordering hazard. | P3 | §12 hazard analysis; test. |
| Rollback / version skew | Disabling the gate while Finalizing rows exist strands them because the service runs iff `Enabled`. | **P2** | §13.3 drain rule (workers to 3.0 first, wait for zero Finalizing in health, then disable); health exposes `finalizingJobs`; runbook slice. Rejected alternative: auto-run when rows exist (hidden behaviour). |
| Duration bound cutting a live claim | An earlier draft let reconciliation exhaust on duration regardless of a live claim, creating a stale-publisher race at the boundary. | **P1** (design) | §5.4/§5.3: the duration bound stops *new* claims only; exhaustion requires no live claim; tail documented for F4. |
| Duration bound not enforced against extension (cold review, amendment 1) | The first version let a live claimant extend forever past the duration, so reconciliation could never act and no maximum was enforced. | **P1** | §5.4/§8.6: `ExtendFinalizationClaim` takes the maximum duration and refuses at the absolute deadline; `CanClaimFinalization` and both SQL predicates share the same inequality; the live claim expires naturally; tail is `MaximumDuration + ClaimSeconds`. Tests and mutants in §15.1/§15.3. |
| `ClaimFinalization` deadline-blind (cold review, amendment 2) | Amendment 1 made the predicate, extension and SQL deadline-aware but left the claim transition on its F1 signature, so a direct caller could create a claim after the deadline (I13 violated at the authority boundary). | **P1** | §5.4/§7.1/§8.6: `ClaimFinalization` gains `maximumFinalizationDuration` and starts with the three-argument `CanClaimFinalization`; the lifecycle passes `policy.MaximumDuration`; domain test with two mutants in §15.1; lifecycle boundary test extended in §15.3. |
| Rollback needs a count health does not expose (cold review, amendment 1) | §13.3 referenced a `finalizingJobs` field §6.9 did not define. | **P2** | §6.9 defines `FinalizingJobs` (PostgreSQL `COUNT(*)`), `LiveClaims`, `MalformedClaims`, `CountsRefreshedAtUtc`; refreshed every cycle and, read-only, while disabled; runbook procedure in §13.3; tests in §15.3. |
| Malformed claim metadata read as unclaimed (cold review, amendment 1) | `hash == null \|\| expiry == null \|\| expiry <= now` treated hash-without-expiry as unclaimed and therefore claimable/exhaustible. | **P2** | §5.2 canonical states via `FinalizationClaimStateAt`; paired-state SQL disjunction shared by §7.1/§7.5; malformed rows never selected, reported once (1512) and counted in health; §8.7 justifies no schema change. Tests and the OR-mutant in §15.1/§15.3. |
| Extension outside the publication transaction holding a lock | Extension is its own transaction; nothing holds the row lock during IO. | — | §8.8. |
| Payload load under lock | A 100 MB bytea read under `FOR UPDATE` would block reconciliation and extension for the read's duration. | P3 | §7.3 unlocked, `AsNoTracking`. |

### 20.1 Cold self-review after amendment 1

1. **Can any claimant extend forever beyond the maximum duration?** No. `ExtendFinalizationClaim` refuses when `now ≥ FinalizationAcceptedAtUtc + MaximumDuration`, inside the aggregate, under the row lock, with the platform clock. The last grant is before the deadline and adds at most `ClaimExtension ≤ ClaimSeconds`.
2. **Can exhaustion act while a valid live claim exists?** No. The reconciliation SQL excludes canonical live claims, `SKIP LOCKED` skips a row its owner is writing, and `ExhaustFinalization` throws on `Live` from the locked row.
3. **Can malformed ownership metadata be interpreted as unclaimed?** No. Unclaimed requires all three columns null; both SQL predicates and `FinalizationClaimStateAt` use paired checks; malformed rows are excluded from selection and throw in the domain.
4. **Can an expired but canonical claim be safely reclaimed?** Yes, while attempts remain and before the deadline: `ClaimFinalization` rotates the token so the old holder fails every fence.
5. **Can rollback be verified using the defined health contract?** Yes. `finalizingJobs` is the PostgreSQL row count with a refresh timestamp, available while enabled and (read-only) while disabled; §13.3 is written against those exact fields.
6. **Can two API hosts still safely contend for one Finalizing job?** Yes. `FOR UPDATE SKIP LOCKED` on claim and reconciliation, token rotation, and fenced writes are unchanged; the deadline and canonical-state predicates only narrow what either host may select.
7. **Does the plan still preserve the no-delete rule?** Yes. Nothing in the amendment touches sealing or evidence; the architecture test and I6 stand.
8. **Does any correction require a migration or ADR amendment?** No migration: the deadline and canonical states use existing columns; §8.7 records why no pairing constraint is added. No ADR amendment: ADR-006 §7 already requires a bounded, fenced claim and says nothing that the amendment contradicts.

Residual: the effective bound is `MaximumFinalizationDuration + ClaimSeconds`, not `MaximumFinalizationDuration` alone. This is inherent to "never revoke a live claim underneath filesystem work" and is stated in the option remarks, the runbook and the F4 bound (§17), so the frozen production value can absorb it.

### 20.2 Cold self-review after amendment 2

1. **Can SQL reject a claim but the domain transition still accept the same state?** No. Both use `now < FinalizationAcceptedAtUtc + MaximumDuration` with the same `nowUtc` and `policy.MaximumDuration`; the SQL form is the same inequality rearranged. The converse (SQL selects, domain refuses) is an invariant violation logged as 1512 and tested at the boundary instant.
2. **Can any direct caller create a claim at or after the deadline?** No. `ClaimFinalization` requires `maximumFinalizationDuration` and refuses through `CanClaimFinalization(now, max, maxDuration)` before touching state; the F1 signatures without the duration are removed.
3. **Do SQL, `CanClaimFinalization`, `ClaimFinalization` and `ExtendFinalizationClaim` all use the same strict `< deadline` rule?** Yes: the three domain methods call the one `FinalizationDeadline(maxDuration)` helper and compare with `<`; the two SQL predicates use `accepted_at > now − maxDuration`, which is equivalent.
4. **At `now == deadline`, are both claim and extension refused?** Yes, by every layer.
5. **Can a claim already live at the deadline still publish before its claim expiry?** Yes. `CompleteFinalization` and `FailFinalization` are fenced by `FinalizationOwnedBy` only, which does not consult the deadline (§5.4, unchanged).
6. **Does any remaining signature permit bypassing the maximum duration?** No. `ReleaseFinalizationClaim` only shortens; `CompleteFinalization`/`FailFinalization`/`ExhaustFinalization` end Finalizing; `NoteFinalizationError` changes no ownership field.

**Unresolved P1/P2:** none. The operational split-brain (two hosts with different gates) is mitigated, not eliminated, and is recorded as a runbook rule rather than a code control; it is P2 operational and accepted by the B3 plan §15.

---

*End of plan. No implementation files were created or modified by this document.*
