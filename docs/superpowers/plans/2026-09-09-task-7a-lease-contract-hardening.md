# MAVI Task 7A — Lease & Worker Contract Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden Task-7 processing orchestration before Python worker execution by introducing secure lease capabilities, attempt-local progress, post-lock time semantics, a single v2.0 worker control-plane contract, and automatic .NET/JSON/Python contract parity checks.

**Architecture:** PostgreSQL remains the concurrency authority and `ProcessingOrchestrator` remains the transaction boundary. Infrastructure generates and verifies 256-bit lease capabilities while `VisionJob` persists only the SHA-256 token hash and enforces lease state transitions. `Mavi.Contracts` becomes the public HTTP contract boundary; JSON Schema and Python Pydantic v2 models implement the same v2.0 protocol.

**Tech Stack:** .NET 10 / ASP.NET Core, EF Core 10.0.11, Npgsql EF Core 10.0.3, PostgreSQL 18, `TimeProvider`, BCL cryptography (`RandomNumberGenerator`, `SHA256`, `CryptographicOperations.FixedTimeEquals`), System.Text.Json strict unmapped-member handling, Python 3.13 baseline retained for Task 7A, Pydantic v2, pytest, JSON Schema.

**Spec:** `docs/superpowers/specs/2026-09-09-task-7a-lease-contract-hardening-design.md`

## Global Constraints

- Implement on the currently selected `feature/visual-intelligence-memory` code line; Codex Cloud may expose its local worktree as `work`.
- Do not start Task 8 or implement worker polling, HTTP execution, media resolution, video decoding, detector/tracker logic, or successful analytical-result submission.
- `Mavi.Domain` must remain free of Infrastructure/API/Python dependencies.
- `Mavi.Contracts` must remain free of MAVI project dependencies.
- Python must not write PostgreSQL.
- Raw video frames must not cross ordinary HTTP APIs.
- Worker media input uses logical storage keys only; no physical path or file URI may cross the contract.
- All cross-system absolute timestamps are UTC; Task-7A current-time decisions use injected `.NET TimeProvider`.
- A lease is expired when `LeaseExpiresAtUtc <= nowUtc`.
- A fresh lease/reclaim resets attempt-local progress and heartbeat state.
- Raw lease tokens are capability data: they must never be persisted, logged, returned by processing-status APIs, rendered in UI state, or placed in diagnostics.
- PostgreSQL stores only a 32-byte SHA-256 lease-token hash.
- Worker control-plane protocol v1 is retired. Task 7A supports only `schemaVersion = "2.0"` on worker control-plane payloads.
- Existing worker endpoint URLs remain unchanged.
- `WorkerId` is a trimmed opaque string, maximum 128 characters, compared using ordinal case-sensitive semantics.
- `Localization:DefaultDisplayTimeZoneId` must be canonical configuration; leading/trailing whitespace is rejected at startup.
- Camera API input may normalize whitespace before validating/persisting the IANA timezone ID.
- Use strict TDD: RED → GREEN → REFACTOR for each behavior change.
- DB-mutating integration tests use `mavi_test` and `[Collection(DatabaseIntegrationGroup.Name)]`.
- `TreatWarningsAsErrors` remains enabled.
- Run `python tools/verify_repo.py` and language-specific builds/tests before completion.

---

## File Structure Map

Primary changes:

```text
src/platform/Mavi.Domain/Processing/
  VisionJob.cs

src/platform/Mavi.Application/
  Abstractions/Security/ILeaseCapabilityService.cs          # new
  Modules/Intelligence/IProcessingOrchestrator.cs
  Modules/Cameras/CameraService.cs

src/platform/Mavi.Infrastructure/
  Security/LeaseCapabilityService.cs                        # new
  Persistence/Configurations/VisionJobConfiguration.cs
  Persistence/Repositories/ProcessingOrchestrator.cs
  Persistence/Migrations/*HardenVisionJobLeases*.cs         # EF-generated migration + designer
  Persistence/Migrations/MaviDbContextModelSnapshot.cs      # EF-generated update
  Time/SystemTimeZoneService.cs
  DependencyInjection.cs

src/platform/Mavi.Contracts/
  Api/Processing/ProcessingContracts.cs
  Worker/ControlPlaneContracts.cs                           # new
  Worker/WorkerContractRules.cs                             # new
  Worker/WorkerContracts.cs                                 # remove retired control-plane DTOs; keep result DTOs only

src/platform/Mavi.Api/Endpoints/
  VisionJobEndpoints.cs

contracts/
  schemas/vision-job-lease-request-v2.schema.json           # new
  schemas/vision-job-lease-v2.schema.json                   # new
  schemas/vision-job-heartbeat-v2.schema.json               # new
  schemas/vision-job-heartbeat-response-v2.schema.json      # new
  schemas/vision-job-fail-v2.schema.json                    # new
  schemas/worker-health-v2.schema.json                      # new
  examples/* matching the six schemas above                # new
  schemas/vision-job.schema.json                            # delete retired v1 job schema
  examples/vision-job.example.json                          # delete retired v1 job example
  schemas/worker-health.schema.json                         # delete retired v1 health schema
  examples/worker-health.example.json                       # delete retired v1 health example
  README.md

tools/
  verify_repo.py

src/vision/
  pyproject.toml
  mavi_vision/common/control_plane.py                       # new Pydantic v2 control-plane models
  mavi_vision/common/contracts.py                           # retain result-side scaffold; remove retired VisionJob/WorkerHealth
  mavi_vision/worker/health.py
  tests/test_control_plane_contracts.py                     # new
  tests/test_worker_health.py
  tests/test_contracts.py                                   # remove/replace retired v1 job tests

tests/Mavi.Domain.Tests/
  ProcessingOrchestrationStateTests.cs

tests/Mavi.IntegrationTests/
  ProcessingOrchestrationApiTests.cs
  WorkerContractV2Tests.cs                                  # new
  LeaseCapabilityServiceTests.cs                            # new
  MigrationTests.cs
  ConfigurationValidationTests.cs
```

---

### Task 1: Add Secure Lease-Capability Infrastructure and Attempt-Local Domain State

**Files:**
- Create: `src/platform/Mavi.Application/Abstractions/Security/ILeaseCapabilityService.cs`
- Create: `src/platform/Mavi.Infrastructure/Security/LeaseCapabilityService.cs`
- Modify: `src/platform/Mavi.Infrastructure/DependencyInjection.cs`
- Modify: `src/platform/Mavi.Domain/Processing/VisionJob.cs`
- Modify: `tests/Mavi.Domain.Tests/ProcessingOrchestrationStateTests.cs`
- Create: `tests/Mavi.IntegrationTests/LeaseCapabilityServiceTests.cs`

**Interfaces:**

```csharp
namespace Mavi.Application.Abstractions.Security;

public sealed record LeaseCapability(string Token, byte[] Hash);

public interface ILeaseCapabilityService
{
    LeaseCapability Create();
    bool Matches(string token, byte[] expectedHash);
}
```

`LeaseCapabilityService.Create()` must generate exactly 32 random bytes, encode them as canonical unpadded Base64Url, hash the raw random bytes using SHA-256, and return the textual token plus the 32-byte hash. `Matches()` must reject malformed tokens and compare the derived SHA-256 hash using `CryptographicOperations.FixedTimeEquals`.

`VisionJob` changes:

```csharp
public byte[]? LeaseTokenHash { get; private set; }

public void Lease(
    string workerId,
    byte[] leaseTokenHash,
    DateTimeOffset nowUtc,
    TimeSpan duration,
    int maximumAttempts);

public void Heartbeat(
    string workerId,
    bool leaseTokenMatches,
    double progressPercent,
    DateTimeOffset nowUtc,
    TimeSpan extension);

public void Fail(
    string workerId,
    bool leaseTokenMatches,
    string code,
    string? details,
    DateTimeOffset nowUtc);
```

A successful `Lease()` must clone/store the 32-byte hash, increment `AttemptCount`, set owner/expiry, reset `ProgressPercent = 0`, and reset `LastHeartbeatUtc = null`. The domain must reject a hash that is not exactly 32 bytes. `Heartbeat` and `Fail` must require `leaseTokenMatches == true` in addition to current owner/status/unexpired rules.

- [ ] **Step 1: Write RED domain tests for token-aware lease generation and progress reset**

Add tests equivalent to:

```csharp
[Fact]
public void ReclaimResetsAttemptLocalProgressAndStoresNewTokenHash()
{
    var job = VisionJob.Create(Guid.CreateVersion7(), "pipeline", Now);
    var firstHash = Enumerable.Repeat((byte)0x11, 32).ToArray();
    var secondHash = Enumerable.Repeat((byte)0x22, 32).ToArray();

    job.Lease("worker-a", firstHash, Now, TimeSpan.FromSeconds(10), 3);
    job.Heartbeat("worker-a", true, 70, Now.AddSeconds(1), TimeSpan.FromSeconds(9));
    job.Lease("worker-b", secondHash, Now.AddSeconds(10), TimeSpan.FromSeconds(10), 3);

    Assert.Equal(2, job.AttemptCount);
    Assert.Equal(0, job.ProgressPercent);
    Assert.Null(job.LastHeartbeatUtc);
    Assert.Equal(secondHash, job.LeaseTokenHash);
}
```

Add tests proving wrong-token boolean is rejected for heartbeat/fail and monotonicity restarts from zero after reclaim.

- [ ] **Step 2: Run RED test**

```bash
dotnet test tests/Mavi.Domain.Tests/Mavi.Domain.Tests.csproj --filter ProcessingOrchestrationStateTests
```

Expected: compile/test failure because the new signatures/property do not exist.

- [ ] **Step 3: Implement the minimal VisionJob changes**

Preserve the existing `<=` expiry rule. Do not put token-generation or cryptographic comparison code in Domain.

- [ ] **Step 4: Write RED capability-service tests**

Tests must assert:

```csharp
var capability = service.Create();
Assert.Equal(43, capability.Token.Length);
Assert.Equal(32, capability.Hash.Length);
Assert.True(service.Matches(capability.Token, capability.Hash));
Assert.False(service.Matches(capability.Token, Enumerable.Repeat((byte)0x44, 32).ToArray()));
Assert.False(service.Matches("not-a-valid-token", capability.Hash));
Assert.DoesNotContain('=', capability.Token);
```

Also generate at least two capabilities and assert both token and hash differ.

- [ ] **Step 5: Implement `LeaseCapabilityService` with BCL cryptography only**

Use .NET 10 BCL Base64Url support when available. Do not add a crypto package and do not implement a custom random-number generator, hash, or comparison function.

Register:

```csharp
services.AddSingleton<ILeaseCapabilityService, LeaseCapabilityService>();
```

- [ ] **Step 6: Run focused tests**

```bash
dotnet test tests/Mavi.Domain.Tests/Mavi.Domain.Tests.csproj --filter ProcessingOrchestrationStateTests
dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj --filter LeaseCapabilityServiceTests
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/platform/Mavi.Domain/Processing/VisionJob.cs \
        src/platform/Mavi.Application/Abstractions/Security \
        src/platform/Mavi.Infrastructure/Security \
        src/platform/Mavi.Infrastructure/DependencyInjection.cs \
        tests/Mavi.Domain.Tests/ProcessingOrchestrationStateTests.cs \
        tests/Mavi.IntegrationTests/LeaseCapabilityServiceTests.cs
git commit -m "feat: add secure lease capability primitives"
```

---

### Task 2: Persist Only the Lease-Token Hash and Add Expired-Lease Indexing

**Files:**
- Modify: `src/platform/Mavi.Infrastructure/Persistence/Configurations/VisionJobConfiguration.cs`
- Create via EF: migration named `HardenVisionJobLeases`
- Modify via EF: `src/platform/Mavi.Infrastructure/Persistence/Migrations/MaviDbContextModelSnapshot.cs`
- Modify: `tests/Mavi.IntegrationTests/MigrationTests.cs`

**Persistence requirements:**

```csharp
builder.Property(x => x.LeaseTokenHash)
    .HasColumnName("lease_token_hash")
    .HasColumnType("bytea");
```

Add DB constraint:

```sql
lease_token_hash IS NULL OR octet_length(lease_token_hash) = 32
```

Add partial reclaim index equivalent to:

```sql
CREATE INDEX ix_vision_jobs_expired_lease
ON vision_jobs (lease_expires_at_utc)
WHERE status = 'Leased';
```

Because v1 is retired, any Task-7 `Leased` row upgraded without a token hash must be made immediately reclaimable. The migration shall expire such pre-v2 leases without changing `AttemptCount`:

```sql
UPDATE vision_jobs
SET lease_expires_at_utc = CURRENT_TIMESTAMP
WHERE status = 'Leased'
  AND lease_token_hash IS NULL
  AND (lease_expires_at_utc IS NULL OR lease_expires_at_utc > CURRENT_TIMESTAMP);
```

- [ ] **Step 1: Add RED migration-model tests**

Add assertions that a fully migrated `mavi_test` database contains:

- column `vision_jobs.lease_token_hash` with PostgreSQL type `bytea`;
- check constraint enforcing 32-byte hash when non-null;
- index `ix_vision_jobs_expired_lease` with a leased-only predicate.

Also add an upgrade-path test that migrates to `AddProcessingOrchestration`, inserts one leased v1-style job with no hash and future expiry, applies `HardenVisionJobLeases`, and verifies it is immediately expired/reclaimable.

- [ ] **Step 2: Run the migration tests and verify RED**

```bash
dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj --filter MigrationTests
```

- [ ] **Step 3: Modify EF configuration and generate migration**

Use the repository's EF migration command pattern. Generate a new migration named exactly `HardenVisionJobLeases`; do not rewrite `20260909053831_AddProcessingOrchestration` or earlier accepted migrations.

- [ ] **Step 4: Inspect generated SQL/model snapshot**

Confirm the migration contains the new column, constraint, pre-v2 lease expiry SQL, and partial index. Confirm `Down()` removes the new index/constraint/column only.

- [ ] **Step 5: Run migration tests and full Integration tests**

```bash
dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj
```

- [ ] **Step 6: Commit**

```bash
git add src/platform/Mavi.Infrastructure/Persistence/Configurations/VisionJobConfiguration.cs \
        src/platform/Mavi.Infrastructure/Persistence/Migrations \
        tests/Mavi.IntegrationTests/MigrationTests.cs
git commit -m "feat: persist hashed lease capabilities"
```

---

### Task 3: Harden Orchestrator Ownership, Reclaim, Post-Lock Time, and Failure Idempotency

**Files:**
- Modify: `src/platform/Mavi.Application/Modules/Intelligence/IProcessingOrchestrator.cs`
- Modify: `src/platform/Mavi.Infrastructure/Persistence/Repositories/ProcessingOrchestrator.cs`
- Modify: `tests/Mavi.IntegrationTests/ProcessingOrchestrationApiTests.cs`

**Interfaces:**

Replace the internal lease view with:

```csharp
public sealed record VisionLeaseView(
    Guid JobId,
    Guid ProcessingRunId,
    Guid VideoAssetId,
    Guid CameraId,
    string WorkerId,
    string LeaseToken,
    string Pipeline,
    string PipelineVersion,
    string SourceStorageKey,
    string SourceSha256,
    long SourceSizeBytes,
    DateTimeOffset RecordingStartUtc,
    DateTimeOffset RecordingEndUtc,
    long DurationMs,
    int Width,
    int Height,
    int FrameRateNumerator,
    int FrameRateDenominator,
    int AttemptCount,
    DateTimeOffset LeaseExpiresAtUtc,
    string RecordingTimeZoneId,
    int RecordingUtcOffsetMinutes);
```

Do not carry `SchemaVersion` in this Application view; schema version belongs to the public contract mapping.

Add:

```csharp
public sealed record HeartbeatResult(
    bool IsSuccess,
    string? ErrorCode,
    double? ProgressPercent,
    DateTimeOffset? LeaseExpiresAtUtc)
{
    public static HeartbeatResult Success(double progress, DateTimeOffset expiresAtUtc) =>
        new(true, null, progress, expiresAtUtc);

    public static HeartbeatResult Failure(string code) =>
        new(false, code, null, null);
}
```

Update interface methods:

```csharp
Task<VisionLeaseView?> LeaseAsync(string workerId, CancellationToken cancellationToken);
Task<HeartbeatResult> HeartbeatAsync(Guid jobId, string workerId, string leaseToken, double progressPercent, CancellationToken cancellationToken);
Task<OrchestrationResult> FailAsync(Guid jobId, string workerId, string leaseToken, string failureCode, string? failureMessage, CancellationToken cancellationToken);
```

**Transactional semantics:**

For lease acquisition, a pre-lock `selectionCutoffUtc` may be used only to find index-eligible candidates. After `FOR UPDATE SKIP LOCKED` returns a job, call `timeProvider.GetUtcNow()` again and use that post-lock value for `CanLease`, exhaustion, token issuance, run assignment, video transition, and expiry calculation.

For heartbeat/fail:

```text
BEGIN
SELECT job ... FOR UPDATE
nowUtc = TimeProvider.GetUtcNow()
verify status + WorkerId + capability hash + expiry
mutate
COMMIT
```

Do not capture authoritative `nowUtc` before acquiring the job row lock.

Failure idempotency rule for an already-Failed job:

```text
same LeaseOwner
+ matching retained LeaseTokenHash
+ identical FailureCode
+ identical FailureDetails
=> success-equivalent replay with no mutation
```

Any differing token/worker/failure payload is rejected.

- [ ] **Step 1: Write RED integration tests for reclaim token rotation and progress reset**

Extend the existing queue/lease/reclaim flow to capture `leaseToken` from Worker A, heartbeat to 70%, expire, reclaim with Worker B, then assert:

```csharp
Assert.NotEqual(tokenA, tokenB);
Assert.Equal(2, job.AttemptCount);
Assert.Equal(0, job.ProgressPercent);
Assert.Null(job.LastHeartbeatUtc);
Assert.Equal("worker-b", job.LeaseOwner);
Assert.Equal(32, job.LeaseTokenHash!.Length);
```

- [ ] **Step 2: Add RED stale-capability tests**

Cover:

- Worker A + token A rejected after Worker B reclaim;
- same `WorkerId` reacquires after expiry, but old token is rejected;
- valid current WorkerId + token succeeds;
- malformed token is rejected without exception leakage.

- [ ] **Step 3: Add RED idempotent failure tests**

Flow:

1. lease current job;
2. fail with code/message;
3. resend identical fail request with the same capability → success;
4. resend with same token but different message → conflict/rejected;
5. confirm `CompletedAtUtc` and terminal state were not changed by the successful replay.

- [ ] **Step 4: Implement orchestrator capability generation/verification**

Inject `ILeaseCapabilityService`. Generate the capability only after a lease candidate is locked and confirmed leaseable. Store only `capability.Hash`; return only `capability.Token` in `VisionLeaseView`.

- [ ] **Step 5: Move authoritative TimeProvider sampling after row locks**

For lease candidate selection, use separate names such as `selectionCutoffUtc` and `nowUtc` so code review cannot confuse preselection time with authoritative locked-decision time.

- [ ] **Step 6: Add a lock-wait expiry regression test**

Use two independent DbContexts/connections in `mavi_test`. Hold `SELECT ... FOR UPDATE` on the target job in transaction A, begin the heartbeat/fail operation through transaction B, advance the existing mutable test clock past `LeaseExpiresAtUtc`, release A, and assert B rejects the old lease. Coordinate using deterministic task/transaction synchronization; do not use `Thread.Sleep` or delay-based timing assertions.

- [ ] **Step 7: Strengthen existing two-worker race test**

After the race assert:

```csharp
var job = await db.VisionJobs.SingleAsync();
Assert.Equal(1, job.AttemptCount);
Assert.NotNull(job.LeaseOwner);
Assert.NotNull(job.LeaseTokenHash);
Assert.Equal(32, job.LeaseTokenHash!.Length);
```

- [ ] **Step 8: Run orchestration tests**

```bash
dotnet test tests/Mavi.Domain.Tests/Mavi.Domain.Tests.csproj --filter ProcessingOrchestrationStateTests
dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj --filter ProcessingOrchestrationApiTests
```

- [ ] **Step 9: Commit**

```bash
git add src/platform/Mavi.Application/Modules/Intelligence/IProcessingOrchestrator.cs \
        src/platform/Mavi.Infrastructure/Persistence/Repositories/ProcessingOrchestrator.cs \
        tests/Mavi.Domain.Tests/ProcessingOrchestrationStateTests.cs \
        tests/Mavi.IntegrationTests/ProcessingOrchestrationApiTests.cs
git commit -m "fix: harden lease ownership and retry semantics"
```

---

### Task 4: Establish Mavi.Contracts as the Strict Worker Control-Plane v2 Boundary

**Files:**
- Create: `src/platform/Mavi.Contracts/Worker/ControlPlaneContracts.cs`
- Create: `src/platform/Mavi.Contracts/Worker/WorkerContractRules.cs`
- Modify: `src/platform/Mavi.Contracts/Api/Processing/ProcessingContracts.cs`
- Modify: `src/platform/Mavi.Contracts/Worker/WorkerContracts.cs`
- Modify: `src/platform/Mavi.Api/Endpoints/VisionJobEndpoints.cs`
- Create: `tests/Mavi.IntegrationTests/WorkerContractV2Tests.cs`

**Public contract version constant:**

```csharp
public static class WorkerControlPlaneVersions
{
    public const string V2 = "2.0";
}
```

**Request DTOs:**

```csharp
[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record LeaseVisionJobRequest(string? SchemaVersion, string? WorkerId);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record VisionJobHeartbeatRequest(
    string? SchemaVersion,
    string? WorkerId,
    string? LeaseToken,
    double ProgressPercent);

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed record FailVisionJobRequest(
    string? SchemaVersion,
    string? WorkerId,
    string? LeaseToken,
    string? FailureCode,
    string? FailureMessage);
```

Move these worker request DTOs out of `Mavi.Contracts.Api.Processing`; keep only `QueueProcessingResponse` there.

**Lease response DTO:**

```csharp
public sealed record VisionJobLeaseContract(
    string SchemaVersion,
    Guid JobId,
    Guid ProcessingRunId,
    Guid VideoAssetId,
    Guid CameraId,
    string WorkerId,
    string LeaseToken,
    int AttemptCount,
    DateTimeOffset LeaseExpiresAtUtc,
    string Pipeline,
    string PipelineVersion,
    string SourceStorageKey,
    string SourceSha256,
    long SourceSizeBytes,
    DateTimeOffset RecordingStartUtc,
    DateTimeOffset RecordingEndUtc,
    long DurationMs,
    int Width,
    int Height,
    int FrameRateNumerator,
    int FrameRateDenominator,
    string RecordingTimeZoneId,
    int RecordingUtcOffsetMinutes);
```

**Heartbeat response DTO:**

```csharp
public sealed record VisionJobHeartbeatResponse(
    string SchemaVersion,
    double ProgressPercent,
    DateTimeOffset LeaseExpiresAtUtc);
```

**Health DTO:**

```csharp
public sealed record WorkerHealthContract(
    string SchemaVersion,
    string WorkerId,
    string Status,
    DateTimeOffset TimestampUtc);
```

Remove the old `Guid WorkerId` v1 health DTO and old `VisionJobContract` from `WorkerContracts.cs`; leave result-side contracts untouched for the later result-ingestion design.

**Rules:**

`WorkerContractRules` shall provide deterministic pure validation for:

```csharp
public static bool TryNormalizeWorkerId(string? value, out string normalized);
public static bool IsSupportedControlPlaneVersion(string? value);
public static bool IsLeaseTokenShapeValid(string? value); // canonical 43-char Base64Url alphabet, no '='
public static bool IsLogicalStorageKeyValid(string? value); // full 1..512 segment invariant
```

`IsLogicalStorageKeyValid` rejects leading/trailing slash, empty segments, `.`/`..`, colon, backslash, and physical URI/drive syntax.

- [ ] **Step 1: Write RED contract tests**

Test supported/unsupported versions, WorkerId normalization, 43-character lease token shape, logical storage-key valid/invalid vectors, and System.Text.Json rejection of unknown request properties.

- [ ] **Step 2: Implement v2 DTOs/rules and retire v1 control-plane DTOs**

No compatibility adapter is created for `mediaUri` v1.

- [ ] **Step 3: Update `VisionJobEndpoints` to map internal models explicitly**

Lease endpoint:

```text
validate schemaVersion == 2.0
normalize WorkerId
orchestrator.LeaseAsync(...)
map VisionLeaseView -> VisionJobLeaseContract
204 when no work
```

Heartbeat endpoint:

```text
validate v2 + WorkerId + lease-token syntax + finite progress 0..100
call token-aware HeartbeatAsync
map success -> VisionJobHeartbeatResponse
```

Fail endpoint validates v2 + WorkerId + token syntax + bounded code/message and forwards token-aware request. Identical failure replay returns the same success-equivalent HTTP result as the first accepted failure.

Use stable error `worker_contract_version_unsupported` for missing/non-`2.0` versions and `worker_id_invalid` for invalid worker identity.

- [ ] **Step 4: Prove `GET /api/videos/{id}/processing` never exposes lease capability**

Add an integration assertion that response JSON contains neither `leaseToken` nor any token/hash representation.

- [ ] **Step 5: Run tests**

```bash
dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj --filter WorkerContractV2Tests
dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj --filter ProcessingOrchestrationApiTests
```

- [ ] **Step 6: Commit**

```bash
git add src/platform/Mavi.Contracts \
        src/platform/Mavi.Api/Endpoints/VisionJobEndpoints.cs \
        tests/Mavi.IntegrationTests/WorkerContractV2Tests.cs \
        tests/Mavi.IntegrationTests/ProcessingOrchestrationApiTests.cs
git commit -m "feat: publish worker control plane v2"
```

---

### Task 5: Replace Retired v1 JSON Contracts with Explicit v2 Schemas and Golden Examples

**Files:**
- Delete: `contracts/schemas/vision-job.schema.json`
- Delete: `contracts/examples/vision-job.example.json`
- Delete: `contracts/schemas/worker-health.schema.json`
- Delete: `contracts/examples/worker-health.example.json`
- Create six v2 schemas and six matching examples listed in the File Structure Map
- Modify: `contracts/README.md`
- Modify: `tools/verify_repo.py`

**Schema requirements:**

All v2 schemas use:

```json
{
  "type": "object",
  "additionalProperties": false
}
```

and require `schemaVersion` with:

```json
{ "const": "2.0" }
```

Lease token schema:

```json
{
  "type": "string",
  "minLength": 43,
  "maxLength": 43,
  "pattern": "^[A-Za-z0-9_-]{43}$"
}
```

WorkerId: non-empty, maximum 128. Storage-key schema must encode the full relative-segment invariant rather than only banning backslash/colon. Timestamps use JSON Schema `date-time`; canonical examples use `Z` UTC.

`contracts/README.md` must state:

- UUIDs identify jobs/runs/videos/cameras, not workers;
- `WorkerId` is an opaque string;
- worker control plane current generation is v2.0;
- v1 `mediaUri` control-plane contract is retired;
- `vision-result` is separate and will be finalized/versioned with successful result acceptance.

Update `verify_repo.py` so its required paths and schema/example pairs reference all active v2 control-plane artifacts plus the existing vision-result pair. Remove retired v1 job/health paths.

- [ ] **Step 1: Create invalid golden examples locally and verify current verifier cannot support the new contract set**

Use this as RED evidence before modifying verifier/schema paths.

- [ ] **Step 2: Create canonical v2 schemas/examples and update verifier**

Use one stable canonical lease example with fixed UUIDs, worker `gpu-sdd-01`, a valid 43-char token, valid source key, and UTC `Z` timestamps. The same file will be consumed by .NET and Python parity tests.

- [ ] **Step 3: Run repository verifier**

```bash
python tools/verify_repo.py
```

Expected: PASS with every active schema/example pair validated.

- [ ] **Step 4: Commit**

```bash
git add contracts tools/verify_repo.py
git commit -m "refactor: retire v1 worker contracts"
```

---

### Task 6: Add Python Pydantic v2 Control-Plane Models Without Starting the Worker

**Files:**
- Modify: `src/vision/pyproject.toml`
- Create: `src/vision/mavi_vision/common/control_plane.py`
- Modify: `src/vision/mavi_vision/common/contracts.py`
- Modify: `src/vision/mavi_vision/worker/health.py`
- Create: `src/vision/tests/test_control_plane_contracts.py`
- Modify: `src/vision/tests/test_worker_health.py`
- Modify/delete retired v1 job assertions in: `src/vision/tests/test_contracts.py`

**Dependency rule:**

Keep:

```toml
requires-python = ">=3.13"
```

for Task 7A. Add only Pydantic v2 as a runtime dependency, bounded below at a tested v2 release and below v3, for example:

```toml
dependencies = ["pydantic>=2.11,<3"]
```

Do not add `httpx`, PyAV, PyTorch, MMDetection, ByteTrack, or worker polling dependencies in Task 7A.

**Model base:**

```python
class ControlPlaneModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
```

Implement Pydantic models matching the six v2 contracts. Use explicit aliases such as `Field(alias="schemaVersion")`. Use `Literal["2.0"]` for version fields, UUID types for IDs, timezone-aware datetime validation for UTC instants, strict WorkerId validation, canonical lease-token validation, and the same logical storage-key rules as .NET/schema.

`mavi_vision.common.contracts` retains only result-side scaffold types needed later; remove the old v1 `VisionJob` and UUID-based `WorkerHealth` definitions.

`worker.health.get_worker_health` becomes:

```python
def get_worker_health(worker_id: str) -> WorkerHealth:
    return WorkerHealth(
        schema_version="2.0",
        worker_id=worker_id,
        status="ready",
        timestamp_utc=datetime.now(timezone.utc),
    )
```

This is a contract helper only; do not add a health server or worker runtime loop.

- [ ] **Step 1: Write RED Python tests loading repository golden examples**

`test_control_plane_contracts.py` must load the canonical JSON examples from `contracts/examples` and validate them through Pydantic. Test `model_dump(by_alias=True, mode="json")` for semantic round-trip.

Add invalid vectors for v1, unknown fields, padded/blank WorkerId, bad token, `../` storage key, absolute storage key, and naive/timezone-less datetime input.

- [ ] **Step 2: Run RED Python tests**

```bash
cd src/vision
python -m pytest -q
```

- [ ] **Step 3: Add Pydantic dependency and implement models**

Do not change Python runtime version in this task.

- [ ] **Step 4: Run all Python tests**

```bash
cd src/vision
python -m pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add src/vision
git commit -m "feat: add pydantic worker control contracts"
```

---

### Task 7: Enforce .NET ↔ JSON Schema ↔ Python Golden Contract Parity

**Files:**
- Create/complete: `tests/Mavi.IntegrationTests/WorkerContractV2Tests.cs`
- Modify: `src/vision/tests/test_control_plane_contracts.py`
- Modify: `tools/verify_repo.py` only if parity checks reveal a verifier gap

**Parity test:**

The canonical `vision-job-lease-v2.example.json` is the shared artifact.

.NET test must:

1. read the repository example;
2. deserialize it into `VisionJobLeaseContract` with strict System.Text.Json options;
3. serialize the contract back with web/camelCase naming;
4. compare semantic JSON properties/values, not whitespace/order;
5. assert `SchemaVersion == "2.0"`, `WorkerId` is the expected opaque string, and `LeaseToken` is present only on the lease contract.

Python test must parse the same file and produce semantically identical `model_dump(by_alias=True, mode="json")` output.

`verify_repo.py` validates the same file against JSON Schema.

- [ ] **Step 1: Run the three parity layers independently**

```bash
dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj --filter WorkerContractV2Tests
python tools/verify_repo.py
cd src/vision && python -m pytest -q
```

- [ ] **Step 2: Fix any naming/type/version drift discovered by parity tests**

Do not solve drift with compatibility aliases for retired v1 names.

- [ ] **Step 3: Add a static scan asserting old `mediaUri` worker-job contract is gone**

The only remaining `mediaUri` text, if any, must be historical documentation explicitly marked retired; it must not appear in active C# DTOs, JSON schemas/examples, or Python control-plane models.

- [ ] **Step 4: Commit**

```bash
git add tests/Mavi.IntegrationTests/WorkerContractV2Tests.cs src/vision/tests tools/verify_repo.py
git commit -m "test: enforce worker contract parity"
```

---

### Task 8: Canonicalize Timezone Configuration While Preserving Camera Input Normalization

**Files:**
- Modify: `src/platform/Mavi.Infrastructure/Time/SystemTimeZoneService.cs`
- Modify: `src/platform/Mavi.Application/Modules/Cameras/CameraService.cs`
- Modify: `tests/Mavi.IntegrationTests/ConfigurationValidationTests.cs`
- Modify: `tests/Mavi.Application.Tests/CameraServiceTests.cs`

**Required behavior:**

`SystemTimeZoneService.IsValidIanaTimeZoneId` rejects values whose original text differs from `Trim()`:

```text
Asia/Kolkata      valid
UTC               valid
" Asia/Kolkata " invalid
"UTC "            invalid
```

Camera input intentionally normalizes before service validation:

```csharp
var normalizedTimeZoneId = command.TimeZoneId.Trim();
if (normalizedTimeZoneId.Length > 64) ...
if (!timeZones.IsValidIanaTimeZoneId(normalizedTimeZoneId)) ...
var camera = Camera.Create(command.Code, command.Name, normalizedTimeZoneId, timeProvider.GetUtcNow());
```

This preserves ergonomic user input while deployment configuration remains fail-fast/canonical.

- [ ] **Step 1: Add RED configuration cases**

Add `" Asia/Kolkata "`, `"UTC "`, and `" UTC"` as invalid `Localization:DefaultDisplayTimeZoneId` cases. Add/retain valid `UTC` and `Asia/Kolkata` tests.

- [ ] **Step 2: Add RED CameraService normalization test**

Create camera with `" Asia/Kolkata "` and assert persisted `TimeZoneId == "Asia/Kolkata"`.

- [ ] **Step 3: Implement strict service validation and explicit CameraService normalization**

- [ ] **Step 4: Run tests**

```bash
dotnet test tests/Mavi.Application.Tests/Mavi.Application.Tests.csproj --filter CameraServiceTests
dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj --filter ConfigurationValidationTests
```

- [ ] **Step 5: Commit**

```bash
git add src/platform/Mavi.Infrastructure/Time/SystemTimeZoneService.cs \
        src/platform/Mavi.Application/Modules/Cameras/CameraService.cs \
        tests/Mavi.Application.Tests/CameraServiceTests.cs \
        tests/Mavi.IntegrationTests/ConfigurationValidationTests.cs
git commit -m "fix: require canonical display timezone configuration"
```

---

### Task 9: Update Phase Plan, Run Security Scans, and Complete Task-7A Verification

**Files:**
- Modify: `docs/superpowers/plans/2026-09-08-visual-intelligence-memory.md`
- Modify: `contracts/README.md` only if final verification exposes documentation drift
- No production feature additions.

Update the Phase-1 implementation plan so Task 7A is an explicit checkpoint between Task 7 and Task 8 and records:

- secure 256-bit lease capability/hash-only persistence;
- attempt-local progress;
- post-row-lock time sampling;
- failure replay semantics;
- control-plane v2.0 retirement of v1;
- `Mavi.Contracts` public boundary;
- Pydantic v2 parity;
- opaque-string WorkerId;
- full logical storage-key contract;
- canonical timezone configuration;
- expired-lease index.

- [ ] **Step 1: Full .NET build/test**

```bash
dotnet build MAVI.sln
dotnet test MAVI.sln
```

- [ ] **Step 2: Frontend regression verification**

From `src/web/mavi-web`, run the scripts that exist in `package.json`, including:

```bash
npm test
npm run typecheck
npm run build
```

Task 7A should not require frontend feature changes; these commands prove no regression.

- [ ] **Step 3: Python verification**

```bash
cd src/vision
python -m pytest -q
```

- [ ] **Step 4: Repository verifier and DB confirmation**

```bash
python tools/verify_repo.py
pg_isready -h localhost -p 5432
PGPASSWORD="$MAVI_LOCAL_POSTGRES_PASSWORD" psql -h localhost -U postgres -d mavi_test -c "SELECT current_database();"
git diff --check
```

Expected DB: `mavi_test`.

- [ ] **Step 5: Security/static scans**

Scan active source/contracts for:

```text
mediaUri
schemaVersion = "1.0" in worker control-plane artifacts
LeaseToken / leaseToken being logged
lease token persisted as raw text
physical source paths in worker contracts
DateTime.UtcNow / DateTimeOffset.UtcNow / DateTime.Now / DateTimeOffset.Now in Task-7A orchestration code
Thread.Sleep / timing sleeps in lease tests
```

Any remaining occurrence must be either unrelated result-contract scaffold, test input intentionally proving rejection, or documentation clearly marked historical/retired.

- [ ] **Step 6: Verify raw capability absence from DB/status API**

The DB must expose only `lease_token_hash bytea`; no raw-token column exists. `GET /api/videos/{id}/processing` must not serialize token or hash.

- [ ] **Step 7: Final focused commit**

```bash
git add docs/superpowers/plans/2026-09-08-visual-intelligence-memory.md contracts/README.md
git commit -m "docs: record Task 7A hardening checkpoint"
```

- [ ] **Step 8: Stop before Task 8**

Do not add Python polling, HTTP worker client execution, logical-media resolution, decoding, inference, detector/tracker packages, or successful result submission.

---

## Final Acceptance Scenario

The implementation is accepted only when this deterministic scenario passes:

1. Queue one imported video.
2. Lease as `gpu-sdd-01` using a v2 lease request.
3. Response contains `schemaVersion = "2.0"`, opaque `workerId`, and a canonical raw lease token.
4. PostgreSQL contains a 32-byte `lease_token_hash` and no raw token.
5. Heartbeat to 70% with the current token succeeds.
6. Advance the injected clock to exact expiry.
7. Reclaim using the same logical `WorkerId` or another worker.
8. Reclaim returns a different raw token, increments `AttemptCount`, preserves `ProcessingRun.StartedAtUtc`, resets progress to 0, and clears `LastHeartbeatUtc`.
9. Heartbeat/fail using the previous token is rejected even if `WorkerId` is identical.
10. Current token heartbeat succeeds.
11. Current token fail atomically fails VisionJob/ProcessingRun/VideoAsset.
12. Repeating the identical failure with the same final capability is success-equivalent and does not mutate terminal timestamps/state.
13. Changing the repeated failure payload is rejected.
14. `GET /api/videos/{id}/processing` exposes no raw token or hash.
15. Two concurrent workers racing one queued job still produce exactly one winner with `AttemptCount == 1` and one 32-byte hash.
16. .NET contract, JSON Schema, canonical example, and Python Pydantic all agree on the same v2 payload.
17. A v1 worker control-plane payload and any unknown JSON member are rejected.
18. Padded localization configuration fails startup; padded camera input normalizes to canonical IANA before persistence.
19. All build/test/verifier checks are green.
20. Task 8 has not started.

## Recommended Commit Sequence

```text
feat: add secure lease capability primitives
feat: persist hashed lease capabilities
fix: harden lease ownership and retry semantics
feat: publish worker control plane v2
refactor: retire v1 worker contracts
feat: add pydantic worker control contracts
test: enforce worker contract parity
fix: require canonical display timezone configuration
docs: record Task 7A hardening checkpoint
```
