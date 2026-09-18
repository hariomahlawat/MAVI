# MAVI Task 7A — Lease & Worker Contract Hardening Design

**Status:** Approved design baseline for implementation planning  
**Date:** 09 Sep 2026  
**Product:** MAVI — Mission-Aware Visual Intelligence  
**Phase:** Phase 1 — Searchable Visual Intelligence Memory  
**Checkpoint:** Task 7A — Lease & Worker Contract Hardening  

## 1. Purpose

Task 7 established the .NET/PostgreSQL processing-orchestration nucleus: queueing, leasing, heartbeats, reclaim, failure propagation, attempt exhaustion, active-run concurrency protection, and worker-facing HTTP endpoints.

Post-merge review identified several issues that should be resolved before any Python worker begins consuming that boundary. Task 7A hardens the lease protocol, removes contract drift, strengthens stale-worker protection, and establishes one authoritative v2 worker control-plane contract.

The objective is to build the worker boundary once, correctly, before detector/tracker implementation begins.

## 2. Scope

### 2.1 In scope

Task 7A shall implement:

1. Cryptographically strong per-lease capability tokens.
2. Hash-only lease-token persistence.
3. Lease-generation rotation on every lease and reclaim.
4. Attempt-local progress and heartbeat state.
5. Post-row-lock authoritative time sampling for lease mutations.
6. Worker control-plane contract version 2.0.
7. `Mavi.Contracts` as the public .NET worker HTTP boundary.
8. Strict JSON contract validation.
9. Pydantic v2 control-plane models for Python contract parity.
10. A consistent opaque-string `WorkerId` model.
11. Full logical `sourceStorageKey` validation across .NET/schema/Python.
12. Retry-safe failure semantics.
13. Strict localization timezone configuration normalization rules.
14. An expired-lease lookup index.
15. Cross-language golden contract tests and distributed-state regression tests.

### 2.2 Explicitly out of scope

Task 7A shall not implement:

- Python job polling;
- Python HTTP worker execution;
- local media resolution in Python;
- video decoding;
- detector or tracker execution;
- RTMDet;
- ByteTrack;
- successful analytical-result submission;
- Track/Observation persistence from workers;
- live RTSP ingestion;
- Phase-2 capabilities.

The Python runtime-version baseline change remains deferred to Task 8.

## 3. Design Principles

### 3.1 Lease ownership is a capability protocol

`WorkerId` identifies the logical worker. `AttemptCount` records retry sequence. Neither is sufficient to prove ownership of the current lease generation.

Every successful lease or reclaim therefore receives a fresh cryptographically random `LeaseToken`. A worker may mutate a leased job only when all of the following are true:

- the `JobId` matches;
- the `WorkerId` matches the current lease owner;
- the supplied `LeaseToken` matches the current lease capability;
- the lease has not expired.

A previous token must immediately become invalid when a new lease generation is issued, including when the same logical `WorkerId` reacquires the job after restart.

### 3.2 Raw lease tokens are not durable data

The platform generates 32 cryptographically random bytes using platform cryptography primitives and returns the Base64Url-encoded raw token only to the worker receiving the lease.

PostgreSQL stores only:

`LeaseTokenHash = SHA-256(raw lease token)`

The raw token must never be persisted, logged, returned by processing-status endpoints, shown in the UI, included in diagnostics, or exposed through telemetry.

Token comparison must use constant-time comparison.

### 3.3 Progress is attempt-local

Phase 1 has no resumable inference checkpoint. A reclaimed job therefore starts processing from the beginning.

Every successful new lease generation shall:

- increment `AttemptCount`;
- rotate `LeaseToken`;
- set the new `LeaseOwner`;
- reset `ProgressPercent` to `0`;
- reset `LastHeartbeatUtc` to `null`;
- set a fresh `LeaseExpiresAtUtc`.

Progress monotonicity applies only within one lease generation. Equal progress is allowed; regression within the same lease is rejected.

### 3.4 PostgreSQL remains the concurrency authority

No Redis lock, distributed-lock service, or message broker is introduced for Task 7A.

Lease acquisition continues to use PostgreSQL row locking with `FOR UPDATE SKIP LOCKED`. Heartbeat and failure operations use row locking before ownership/expiry validation.

The authoritative current time for a lock-protected lease decision must be sampled from injected `.NET TimeProvider` only after the relevant row lock has been acquired.

This prevents a request that began before lease expiry but waited on a row lock until after expiry from acting on an obsolete lease.

## 4. Lease State Model

### 4.1 Persisted lease state

`VisionJob` shall carry, at minimum:

- `LeaseOwner` — nullable opaque string, maximum 128 characters;
- `LeaseTokenHash` — nullable 32-byte SHA-256 digest;
- `LeaseExpiresAtUtc` — nullable UTC instant;
- `AttemptCount` — retry sequence;
- `ProgressPercent` — attempt-local progress;
- `LastHeartbeatUtc` — attempt-local heartbeat instant.

The existing failure fields remain authoritative for terminal failure information.

### 4.2 New lease / reclaim

Within one transaction:

1. Lock/select a candidate job using PostgreSQL concurrency rules.
2. Sample `nowUtc` after the lock is held.
3. Reconfirm the candidate is still leaseable or determine that it is exhausted.
4. Generate a new 256-bit random lease token.
5. Hash the raw token with SHA-256 for persistence.
6. Increment `AttemptCount`.
7. Set `LeaseOwner`.
8. Persist `LeaseTokenHash`.
9. Reset `ProgressPercent` to `0`.
10. Reset `LastHeartbeatUtc` to `null`.
11. Set `LeaseExpiresAtUtc = nowUtc + LeaseDuration`.
12. Update `ProcessingRun` assignment while preserving its original `StartedAtUtc` on reclaim.
13. Transition `VideoAsset` to `Processing` only when required by its current state.
14. Commit.
15. Return the raw token only in the successful lease response.

The raw token must never be written to the database.

### 4.3 Heartbeat

Heartbeat ownership validation occurs after `SELECT ... FOR UPDATE` and after sampling `nowUtc`.

A heartbeat succeeds only when:

- `VisionJob.Status == Leased`;
- `WorkerId` matches by ordinal case-sensitive comparison;
- the SHA-256 hash of the supplied token matches `LeaseTokenHash` using constant-time comparison;
- `LeaseExpiresAtUtc > nowUtc`;
- `0 <= ProgressPercent <= 100`;
- progress is not lower than the current attempt progress.

On success:

- `ProgressPercent` is updated;
- `LastHeartbeatUtc = nowUtc`;
- `LeaseExpiresAtUtc = nowUtc + HeartbeatExtension`.

The worker does not select heartbeat-extension duration.

### 4.4 Failure

Failure uses the same locked ownership validation as heartbeat.

A valid first failure atomically transitions:

- `VisionJob -> Failed`;
- `ProcessingRun -> Failed`;
- `VideoAsset -> Failed`.

The final lease-token hash is retained for retry-safe terminal acknowledgement but remains non-display capability state.

An identical failure request repeated with the same final `WorkerId`, valid terminal token, `FailureCode`, and `FailureMessage` shall return a success-equivalent result. This handles a lost HTTP response after a successful database commit.

A retry with a different token, different worker, or different failure payload shall not be treated as the same idempotent operation.

Attempt-exhaustion failures do not create a new token and are not worker-idempotency cases.

### 4.5 Attempt exhaustion

If an expired job has already reached `MaximumAttempts`, the lease sweep shall not issue another capability.

Within the same transaction:

- `VisionJob -> Failed`;
- `ProcessingRun -> Failed`;
- `VideoAsset -> Failed`;
- `FailureCode = vision_job_attempts_exhausted`.

No attempt `MaximumAttempts + 1` is allowed.

## 5. Worker Identity

`WorkerId` is a stable, human-readable opaque string across all worker control-plane contracts.

Rules:

- required;
- trimmed at controlled user/worker-input boundaries;
- maximum 128 characters;
- compared with ordinal case-sensitive semantics;
- not interpreted as a UUID;
- not used as a security credential.

Examples include `gpu-sdd-01`, `gpu-sdd-02`, and `development-worker-01`.

`WorkerId` answers **who** owns a lease. `LeaseToken` answers **which exact lease generation** that worker owns. `AttemptCount` answers **which retry number** is executing.

## 6. Worker Control-Plane Contract v2.0

### 6.1 Version policy

The bootstrap `mediaUri` worker contract is retired. No dual v1/v2 compatibility layer shall be implemented.

The authoritative control-plane protocol version is:

`schemaVersion = "2.0"`

Existing endpoint URLs remain unchanged because MAVI is not operating two protocol generations concurrently. Contract versioning is carried in the wire payload, not the route.

Unsupported versions return a stable `worker_contract_version_unsupported` error.

### 6.2 Public .NET boundary

`Mavi.Contracts` is the authoritative public .NET boundary for worker HTTP traffic.

The API must explicitly map internal Application models such as `VisionLeaseView` into `Mavi.Contracts` DTOs. Application DTOs shall not be serialized directly across the worker boundary.

The principal v2 DTOs are conceptually:

- `VisionJobLeaseContract`;
- `VisionJobHeartbeatRequest`;
- `VisionJobFailRequest`;
- `WorkerHealthContract`.

Successful vision-result submission is not part of Task 7A and will be versioned separately when that boundary is designed.

### 6.3 Lease response

The v2 lease response includes:

- `schemaVersion`;
- `jobId`;
- `processingRunId`;
- `videoAssetId`;
- `cameraId`;
- `workerId`;
- raw `leaseToken`;
- `attemptCount`;
- `leaseExpiresAtUtc`;
- `pipeline`;
- `pipelineVersion`;
- `sourceStorageKey`;
- `sourceSha256`;
- `sourceSizeBytes`;
- `recordingStartUtc`;
- `recordingEndUtc`;
- `durationMs`;
- `width`;
- `height`;
- `frameRateNumerator`;
- `frameRateDenominator`;
- `recordingTimeZoneId`;
- `recordingUtcOffsetMinutes`.

`WorkerId` is echoed so the receiver can verify that the lease was issued to the identity it requested.

### 6.4 Heartbeat request

The v2 heartbeat request contains:

- `schemaVersion = "2.0"`;
- `workerId`;
- `leaseToken`;
- `progressPercent`.

A successful heartbeat response may return safe state such as current progress and the new lease expiry, but must never return the lease token again.

### 6.5 Failure request

The v2 failure request contains:

- `schemaVersion = "2.0"`;
- `workerId`;
- `leaseToken`;
- `failureCode`;
- optional bounded `failureMessage`.

The lease token must never be echoed in the response.

### 6.6 Worker health

Worker health uses the same opaque-string `WorkerId` and `schemaVersion = "2.0"`.

Task 7A updates the contract definition but does not add a new health endpoint unless one already exists and requires compatibility changes.

## 7. Strict Contract Validation

### 7.1 Unknown fields

All worker control-plane v2 contracts reject unknown JSON members.

.NET request deserialization/validation must be configured or implemented so the worker boundary does not silently accept contract drift.

Python Pydantic models shall use strict configuration equivalent to:

`ConfigDict(extra="forbid", frozen=True)`.

### 7.2 Lease-token format

The raw lease token is a Base64Url representation of exactly 32 random bytes. Implementations shall validate canonical Base64Url form and expected decoded length.

No padding-dependent or alternative textual representations shall be accepted silently.

### 7.3 Logical storage-key invariant

`sourceStorageKey` is a logical MAVI storage key, never a physical path or URI.

The v2 contract shall enforce the existing media-store invariant consistently across .NET, JSON Schema, and Python:

- 1 to 512 characters;
- relative path only;
- forward-slash separators;
- no leading slash;
- no trailing slash;
- no empty segment;
- no `.` segment;
- no `..` segment;
- no backslash;
- no colon;
- no drive path;
- no `file://` or other physical-URI syntax.

Examples accepted:

`source/<camera-id>/2026/09/09/<video-id>.mp4`

Examples rejected:

- `/source/video.mp4`;
- `source//video.mp4`;
- `source/../video.mp4`;
- `source/./video.mp4`;
- `D:\MAVI-Data\video.mp4`;
- `file:///mnt/video.mp4`.

## 8. Python Contract Package

Task 7A introduces Pydantic v2 only for worker control-plane contract models.

The Python package shall model the same v2 payloads as `Mavi.Contracts` and the JSON Schemas, with typed validation for:

- UUID identifiers;
- timezone-aware UTC instants;
- literal schema version `2.0`;
- bounded opaque `WorkerId`;
- canonical lease token;
- logical storage keys;
- bounded progress/failure fields.

Task 7A does not implement worker polling, HTTP execution, inference, or media access.

The existing Python runtime-version baseline is not changed by Task 7A. The planned Python 3.12 worker runtime baseline is established in Task 8.

## 9. Contract Artifacts and Parity

The repository shall maintain one authoritative v2 control-plane generation across:

1. `Mavi.Contracts` DTOs;
2. JSON Schemas;
3. canonical JSON examples;
4. Python Pydantic models.

The old v1 `mediaUri` worker-job contract is retired and shall not remain as an active supposedly compatible protocol.

Prefer explicit v2 artifact names, for example:

- `vision-job-lease-v2.schema.json`;
- `vision-job-heartbeat-v2.schema.json`;
- `vision-job-fail-v2.schema.json`;
- `worker-health-v2.schema.json`;

with corresponding examples.

Golden contract tests shall prove that the same canonical payload:

- serializes from the public .NET contract;
- validates against the corresponding JSON Schema;
- parses in Python Pydantic;
- round-trips without semantic drift.

Invalid vectors shall be shared across layers where practical.

## 10. API Semantics

Existing routes remain:

- `POST /api/vision/jobs/lease`;
- `POST /api/vision/jobs/{id}/heartbeat`;
- `POST /api/vision/jobs/{id}/fail`.

No `/api/v2` route hierarchy is added because v1 is retired rather than supported concurrently.

Stable worker-boundary errors include, at minimum:

- `worker_contract_version_unsupported`;
- `worker_id_invalid`;
- `vision_job_not_found`;
- `vision_job_not_leased`;
- `vision_job_lease_invalid`;
- `vision_job_progress_regression`;
- `vision_job_attempts_exhausted`.

No-work lease behavior remains `204 No Content`.

## 11. Configuration Hardening

`Localization:DefaultDisplayTimeZoneId` is deployment configuration and must already be canonical.

Accepted examples:

- `Asia/Kolkata`;
- `UTC`.

Rejected examples:

- ` Asia/Kolkata `;
- `UTC `;
- ` UTC`.

Configuration validation shall fail startup rather than silently trim the value. User-entered camera input may continue to normalize whitespace before durable persistence.

## 12. Database Changes

Task 7A adds a new migration; it does not rewrite the accepted Task-7 orchestration migration.

The migration shall add the durable lease-token hash field using a representation appropriate for a 32-byte SHA-256 digest, preferably PostgreSQL `bytea` with length/invariant enforcement in application/persistence configuration.

The migration shall also add an index supporting expired-lease selection. The preferred PostgreSQL shape is a partial index on `lease_expires_at_utc` for leased jobs, subject to the actual persisted enum representation:

`WHERE status = 'Leased'`

Existing active-run uniqueness remains unchanged.

## 13. Security Requirements

Task 7A shall use only platform cryptography primitives such as:

- `RandomNumberGenerator`;
- `SHA256`;
- `CryptographicOperations.FixedTimeEquals`.

No custom cryptographic algorithm and no additional crypto package is required.

The raw lease token must be absent from:

- PostgreSQL;
- `GET /api/videos/{id}/processing`;
- ordinary structured logs;
- exception messages;
- failure diagnostics;
- UI state;
- telemetry.

The token is returned only in the successful lease response and subsequently supplied by the owning worker on lease-protected mutations.

## 14. Required Verification

### 14.1 Lease generation

Tests shall prove:

- every lease generates a token;
- the database stores only its hash;
- reclaim generates a different token;
- reclaim increments `AttemptCount`;
- reclaim resets progress to zero;
- reclaim clears `LastHeartbeatUtc`.

### 14.2 Ownership and stale-worker protection

Tests shall prove:

- correct worker and token succeed;
- wrong worker fails;
- wrong token fails;
- previous token fails after reclaim;
- the same `WorkerId` with the previous token fails after reclaim;
- an expired token fails;
- the token is absent from processing-status output.

### 14.3 Timing

Tests shall prove that lease-sensitive time is sampled after the row lock is acquired, including scenarios where a heartbeat or failure request begins before expiry but obtains the row lock only after expiry.

### 14.4 Progress

Tests shall prove:

- equal progress is allowed;
- increasing progress is allowed;
- regression within an attempt is rejected;
- a reclaimed attempt may restart from zero.

### 14.5 Failure idempotency

Tests shall prove:

- the first valid failure commits all terminal transitions atomically;
- an identical retry with the same terminal lease capability succeeds equivalently;
- a different failure payload is rejected as a different operation;
- a stale capability after reclaim is rejected.

### 14.6 Contract v2 parity

Tests shall prove:

- .NET emits `schemaVersion = 2.0`;
- JSON Schemas accept canonical payloads;
- Python Pydantic accepts the same payloads;
- v1 payloads are rejected;
- unknown fields are rejected;
- WorkerId rules are consistent;
- lease-token rules are consistent;
- logical storage-key rules are consistent;
- timezone-less cross-system instants are rejected.

### 14.7 Configuration

Tests shall prove:

- `Asia/Kolkata` is accepted;
- `UTC` is accepted;
- padded timezone configuration is rejected.

### 14.8 Concurrency and indexes

Tests shall prove:

- two workers racing one queued job produce exactly one lease winner;
- the winning job has `AttemptCount == 1`;
- exactly one owner/token hash is persisted;
- expired-lease reclaim remains race-safe;
- the new index exists after migration.

## 15. Completion Criteria

Task 7A is complete only when:

1. the secure lease-capability model is implemented and tested;
2. progress/heartbeat state is attempt-local;
3. authoritative time is sampled after row locking;
4. the worker control plane is consistently v2.0;
5. `Mavi.Contracts` is the public .NET boundary;
6. .NET/schema/Python contract parity is automatically tested;
7. stale messages cannot mutate a reclaimed lease, even with the same WorkerId;
8. no raw lease token is persisted or exposed outside the lease-protected worker exchange;
9. localization configuration is canonical and fail-fast;
10. the expired-lease query is appropriately indexed;
11. all .NET, frontend, Python contract, migration, concurrency, and repository verification checks pass;
12. Task 8 worker execution has not started.

## 16. Next Step

After Task 7A passes architecture review, Task 8 may establish the executable Python worker baseline and implement lease polling, heartbeat behavior, logical-media resolution, and deliberate controlled failure without yet introducing detector/tracker result acceptance.
