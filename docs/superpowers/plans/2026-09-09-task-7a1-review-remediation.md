# Task 7A.1 Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all verified Task 7A review defects and acceptance gaps before Task 8 consumes the worker control plane.

**Architecture:** Preserve the approved Task 7A lease-capability architecture: PostgreSQL remains the concurrency authority, raw lease capabilities remain worker-only, and `Mavi.Contracts` remains the public worker boundary. This checkpoint is corrective rather than a redesign: make token parsing total/non-throwing, enforce exact v2 request presence and schema parity, close terminal-state capability leaks, prove post-lock timing and upgrade migration behavior, and remove obsolete v1/media-URI residue.

**Tech Stack:** .NET 10 / ASP.NET Core, EF Core 10.0.11, Npgsql/PostgreSQL, System.Text.Json, BCL cryptography, JSON Schema 2020-12, Python/Pydantic v2/pytest, React/Vite verification only.

**Spec:** `docs/superpowers/specs/2026-09-09-task-7a-lease-contract-hardening-design.md`

## Global Constraints

- Do not start Task 8.
- Do not rewrite accepted migrations; add no new migration unless a new persisted field is actually required.
- Raw lease capability data must never be persisted, logged, exposed by processing status, or copied into failure diagnostics.
- Exact expiry remains `LeaseExpiresAtUtc <= nowUtc`.
- Lease-sensitive authoritative time must be sampled after the PostgreSQL row lock is held.
- Worker control-plane schema version remains exactly `2.0`; v1 stays retired.
- `Mavi.Contracts` remains the public .NET HTTP contract boundary.
- Worker control-plane input is machine-to-machine canonical data: reject surrounding whitespace in `workerId` rather than silently normalizing it.
- `sourceStorageKey` remains logical/relative only.
- Python remains contract-only in this checkpoint; do not implement polling, HTTP worker execution, media resolution, decoding, detection, tracking, or result submission.
- Preserve the current Python runtime declaration until Task 8.
- Use TDD for every behavioral change.

---

## File Structure Map

Primary files expected to change:

```text
src/platform/Mavi.Contracts/Worker/
  ControlPlaneContracts.cs
  WorkerContractRules.cs

src/platform/Mavi.Infrastructure/Security/
  LeaseCapabilityService.cs

src/platform/Mavi.Domain/Processing/
  VisionJob.cs

src/platform/Mavi.Application/Modules/Intelligence/
  IProcessingOrchestrator.cs

src/platform/Mavi.Infrastructure/Persistence/Repositories/
  ProcessingOrchestrator.cs

src/platform/Mavi.Api/Endpoints/
  VisionJobEndpoints.cs

contracts/schemas/
  vision-job-lease-request-v2.schema.json
  vision-job-lease-v2.schema.json
  vision-job-heartbeat-v2.schema.json
  vision-job-heartbeat-response-v2.schema.json
  vision-job-fail-v2.schema.json
  worker-health-v2.schema.json

contracts/examples/
  existing v2 golden examples

contracts/test-vectors/
  control-plane-v2-invalid.json

src/vision/mavi_vision/common/
  control_plane.py

src/vision/mavi_vision/video/
  media_reference.py (delete if unused; otherwise replace media_uri with source_storage_key)

src/vision/tests/
  test_contracts.py
  test_worker_health.py

tests/Mavi.Domain.Tests/
  ProcessingOrchestrationStateTests.cs

tests/Mavi.IntegrationTests/
  LeaseCapabilityServiceTests.cs
  ProcessingOrchestrationApiTests.cs
  MigrationTests.cs
  WorkerContractTests.cs (create if a focused file is cleaner)

tools/
  verify_repo.py
```

---

### Task 1: Make Lease-Token Validation Canonical and Non-Throwing

**Files:**
- Modify: `src/platform/Mavi.Contracts/Worker/WorkerContractRules.cs`
- Modify: `src/platform/Mavi.Infrastructure/Security/LeaseCapabilityService.cs`
- Modify: `tests/Mavi.IntegrationTests/LeaseCapabilityServiceTests.cs`
- Test: worker endpoint tests in `tests/Mavi.IntegrationTests/ProcessingOrchestrationApiTests.cs` or focused contract tests

**Interfaces:**
- Produces one canonical Base64Url validation rule for exactly 32 bytes / 43 unpadded characters.
- `LeaseCapabilityService.Matches(...)` must be total: malformed input returns `false`, never a decoding exception.

- [ ] **Step 1: Add RED tests for malformed trailing Base64Url bits**

Use the concrete regression token:

```csharp
var malformed = new string('A', 42) + "B";
```

Assert both:

```csharp
Assert.False(WorkerContractRules.IsCanonicalLeaseToken(malformed));
Assert.False(service.Matches(malformed, new byte[32]));
```

Also POST the malformed token to heartbeat/fail and assert a controlled `400` rather than HTTP 500.

- [ ] **Step 2: Run the focused tests and verify the current failure/exception behavior**

```powershell
dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj --filter "LeaseCapabilityServiceTests|ProcessingOrchestrationApiTests"
```

- [ ] **Step 3: Implement canonical decode + round-trip validation**

The validator must:

1. require exactly 43 Base64Url characters;
2. catch/contain any `FormatException` from the BCL decoder;
3. decode to exactly 32 bytes;
4. re-encode the decoded bytes with unpadded Base64Url;
5. compare the re-encoded form to the supplied token with ordinal equality.

The JSON-schema lease-token pattern should later be tightened to make the final character canonical for a 32-byte value:

```regex
^[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]$
```

- [ ] **Step 4: Run focused tests GREEN**

- [ ] **Step 5: Commit**

```powershell
git add src/platform/Mavi.Contracts/Worker/WorkerContractRules.cs src/platform/Mavi.Infrastructure/Security/LeaseCapabilityService.cs tests/Mavi.IntegrationTests
git commit -m "fix: make lease token validation canonical and total"
```

---

### Task 2: Enforce Required Worker Request Members and Exact v2 Contract Parity

**Files:**
- Modify: `src/platform/Mavi.Contracts/Worker/ControlPlaneContracts.cs`
- Modify: `src/platform/Mavi.Contracts/Worker/WorkerContractRules.cs`
- Modify: `src/platform/Mavi.Api/Endpoints/VisionJobEndpoints.cs`
- Modify: `contracts/schemas/*-v2.schema.json`
- Create: `contracts/test-vectors/control-plane-v2-invalid.json`
- Modify: `src/vision/mavi_vision/common/control_plane.py`
- Modify: `src/vision/tests/test_contracts.py`
- Modify: `tools/verify_repo.py`
- Test: create/extend focused `.NET` worker contract tests

**Interfaces:**
- Missing `progressPercent` must be distinguishable from explicit `0`.
- `failureMessage` is optional and nullable consistently in .NET, JSON Schema, and Python.
- Machine `workerId` values are canonical and must not contain leading/trailing whitespace.

- [ ] **Step 1: Add RED API test for omitted heartbeat progress**

Send raw JSON:

```json
{
  "schemaVersion": "2.0",
  "workerId": "gpu-sdd-01",
  "leaseToken": "<valid-token>"
}
```

Expected:

```text
400 vision_job_heartbeat_invalid
```

The request must not extend the lease.

- [ ] **Step 2: Make heartbeat presence explicit**

Use an inbound shape that can detect omission, e.g. nullable request storage with explicit validation:

```csharp
public sealed record VisionJobHeartbeatRequest(
    string? SchemaVersion,
    string? WorkerId,
    string? LeaseToken,
    double? ProgressPercent);
```

Then reject `null`/missing before orchestration. Do not substitute zero.

- [ ] **Step 3: Add RED parity tests for failureMessage**

Validate all three legal forms:

```json
{"failureMessage":"diagnostic"}
{"failureMessage":null}
// member omitted
```

The latter two must be accepted by the JSON Schema and Python/.NET request model when all other fields are valid.

- [ ] **Step 4: Correct `vision-job-fail-v2.schema.json`**

Remove `failureMessage` from `required` and permit string-or-null when present:

```json
"failureMessage": {
  "type": ["string", "null"],
  "maxLength": 4000
}
```

- [ ] **Step 5: Canonicalize `workerId` consistently**

Change the worker control plane so these are rejected everywhere:

```text
" gpu-sdd-01"
"gpu-sdd-01 "
" gpu-sdd-01 "
```

Do not silently trim machine-to-machine worker IDs. Keep camera/user-input normalization unchanged.

- [ ] **Step 6: Standardize failure-code syntax**

Use one rule in .NET/schema/Python, compatible with existing MAVI codes:

```regex
^[a-z][a-z0-9_]{0,63}$
```

Examples accepted:

```text
vision_dummy_not_implemented
ffmpeg_decode_failed
```

Whitespace-only, mixed-space, URI-like, or arbitrary capability-shaped codes are rejected.

- [ ] **Step 7: Tighten Python model validation**

Add strict/no-coercion behavior where compatible with JSON input, retain `extra="forbid"`, and canonicalize lease-token validation by decode + re-encode equality. Ensure worker-health `status` and JSON Schema both use the same allowed vocabulary (`ready` for the current scaffold).

- [ ] **Step 8: Add shared invalid contract vectors**

Create `contracts/test-vectors/control-plane-v2-invalid.json` containing at least:

- malformed trailing-bit lease token;
- padded worker ID;
- unknown property;
- wrong/missing schema version;
- missing heartbeat progress;
- invalid failure code;
- invalid storage key;
- non-UTC timestamp where applicable.

Use the vectors from `verify_repo.py` and Python tests; cover the equivalent cases in .NET contract/API tests.

- [ ] **Step 9: Run .NET, Python and repository-contract tests GREEN**

- [ ] **Step 10: Commit**

```powershell
git add src/platform/Mavi.Contracts src/platform/Mavi.Api contracts src/vision tools/verify_repo.py tests/Mavi.IntegrationTests
git commit -m "fix: align worker control plane v2 validation"
```

---

### Task 3: Close Terminal-State Capability and Diagnostic Leakage Paths

**Files:**
- Modify: `src/platform/Mavi.Domain/Processing/VisionJob.cs`
- Modify: `src/platform/Mavi.Application/Modules/Intelligence/IProcessingOrchestrator.cs`
- Modify: `src/platform/Mavi.Infrastructure/Persistence/Repositories/ProcessingOrchestrator.cs`
- Modify: `src/platform/Mavi.Api/Endpoints/VisionJobEndpoints.cs`
- Modify: `tests/Mavi.Domain.Tests/ProcessingOrchestrationStateTests.cs`
- Modify: `tests/Mavi.IntegrationTests/ProcessingOrchestrationApiTests.cs`

**Interfaces:**
- `Complete` must require the current lease capability match, just like heartbeat/fail.
- Automatic attempt exhaustion must not be replayable as a worker-idempotent failure.
- The raw presented lease token must be rejected if copied into worker failure diagnostics.

- [ ] **Step 1: Add RED domain test for completion without a matching token**

Change the intended signature to:

```csharp
Complete(string workerId, bool leaseTokenMatches, DateTimeOffset nowUtc)
```

Prove `leaseTokenMatches == false` is rejected even for the correct worker.

- [ ] **Step 2: Add RED test for automatic exhaustion replay**

After `Exhaust(...)`, prove the previous worker/token cannot submit an apparently idempotent `vision_job_attempts_exhausted` failure.

- [ ] **Step 3: Make automatic exhaustion revoke worker capability state**

On `Exhaust(...)`, clear capability-bearing active lease fields:

```text
LeaseOwner = null
LeaseTokenHash = null
LeaseExpiresAtUtc = null
LastHeartbeatUtc = null
```

Keep AttemptCount and relevant diagnostic progress/history.

Worker-originated `Fail(...)` continues retaining owner/hash solely for identical retry acknowledgement.

- [ ] **Step 4: Add RED diagnostic-leak integration test**

Lease a job, capture the raw token, then attempt failure payloads where:

```text
failureCode == leaseToken
failureMessage == leaseToken
failureMessage contains leaseToken inside surrounding text
```

Expected: controlled invalid-failure response and zero copies of the raw token in `VisionJob.FailureCode`, `VisionJob.FailureDetails`, `ProcessingRun.ErrorCode`, `ProcessingRun.ErrorDetails`, and `GET /api/videos/{id}/processing`.

- [ ] **Step 5: Add defense-in-depth before persistence**

Reject a failure operation if the presented raw lease capability occurs in `failureCode` or `failureMessage`. Enforce this in the orchestration path as well as the HTTP boundary so a future caller cannot accidentally persist the capability by bypassing endpoint validation.

- [ ] **Step 6: Run focused domain/integration tests GREEN**

- [ ] **Step 7: Commit**

```powershell
git add src/platform/Mavi.Domain src/platform/Mavi.Application src/platform/Mavi.Infrastructure src/platform/Mavi.Api tests/Mavi.Domain.Tests tests/Mavi.IntegrationTests
git commit -m "fix: close terminal lease capability leaks"
```

---

### Task 4: Prove Post-Lock Time Semantics and Bound Lease Transactions

**Files:**
- Modify: `src/platform/Mavi.Infrastructure/Persistence/Repositories/ProcessingOrchestrator.cs`
- Modify: `tests/Mavi.IntegrationTests/ProcessingOrchestrationApiTests.cs`
- Modify test infrastructure only if needed for deterministic lock coordination

**Interfaces:**
- Heartbeat/fail must use `TimeProvider.GetUtcNow()` only after their job row lock is acquired.
- Exhausted candidates must not accumulate row locks across an unbounded lease-selection loop.

- [ ] **Step 1: Add deterministic RED heartbeat lock-wait regression test**

Use two separate DB connections/contexts:

1. lease target job;
2. connection A begins a transaction and locks the `vision_jobs` row `FOR UPDATE`;
3. operation B begins heartbeat and blocks on that row;
4. while B is blocked, advance `MutableTimeProvider` to exact/beyond expiry;
5. release/commit A;
6. assert B returns `vision_job_lease_invalid` and does not extend expiry.

Do not use `Thread.Sleep` or `Task.Delay` as correctness synchronization; coordinate using explicit DB lock state/task signals.

- [ ] **Step 2: Add the equivalent fail lock-wait regression**

After the same timing sequence, failure must be rejected and job/run/video must remain non-terminal from that stale request.

- [ ] **Step 3: Refactor lease selection to release locks after an exhausted candidate**

Prefer one transaction per candidate iteration:

```text
loop
  BEGIN
  select candidate FOR UPDATE SKIP LOCKED
  if none: COMMIT; return 204
  sample authoritative now
  if exhausted:
      terminalize
      save
      COMMIT
      continue with a fresh transaction
  else:
      issue lease
      save
      COMMIT
      return lease
```

This preserves correctness while preventing one worker request from retaining locks on multiple exhausted rows until a later candidate is found.

- [ ] **Step 4: Run concurrency tests GREEN**

Include the existing two-worker race and exact-attempt assertions.

- [ ] **Step 5: Commit**

```powershell
git add src/platform/Mavi.Infrastructure/Persistence/Repositories/ProcessingOrchestrator.cs tests/Mavi.IntegrationTests
git commit -m "test: prove post-lock lease timing semantics"
```

---

### Task 5: Add a Real Pre-v2 → Task-7A Migration Upgrade Test

**Files:**
- Modify: `tests/Mavi.IntegrationTests/MigrationTests.cs`
- Do not modify the existing `HardenVisionJobLeases` migration unless the test proves its current SQL is wrong

**Interfaces:**
- A pre-v2 active leased row with no capability hash must become reclaimable after Task 7A migration.
- Migration must preserve AttemptCount.

- [ ] **Step 1: Add RED upgrade-path test**

Programmatically migrate a clean DB only through:

```text
20260909053831_AddProcessingOrchestration
```

Insert a valid camera/artifact/video/run/job chain using SQL compatible with that historical schema. Seed a `Leased` job with:

```text
lease_owner = 'legacy-worker'
lease_expires_at_utc = future instant
attempt_count = known value
```

There is intentionally no `lease_token_hash` column at this stage.

- [ ] **Step 2: Apply migrations to latest**

Assert:

- `lease_token_hash` exists as `bytea`;
- `ck_vision_jobs_lease_token_hash` enforces exactly 32 bytes when non-null;
- `ix_vision_jobs_expired_lease` is partial with predicate `status = 'Leased'`;
- the legacy leased row is now immediately reclaimable;
- `AttemptCount` is unchanged solely by migration;
- the row has no invented raw or hashed capability.

- [ ] **Step 3: Run migration tests GREEN**

- [ ] **Step 4: Commit**

```powershell
git add tests/Mavi.IntegrationTests/MigrationTests.cs
git commit -m "test: verify Task 7A lease migration upgrade path"
```

---

### Task 6: Restore Clean Layer Boundaries and Remove Retired Media-URI Residue

**Files:**
- Modify: `src/platform/Mavi.Application/Modules/Intelligence/IProcessingOrchestrator.cs`
- Modify: `src/platform/Mavi.Infrastructure/Persistence/Repositories/ProcessingOrchestrator.cs`
- Modify: `src/platform/Mavi.Api/Endpoints/VisionJobEndpoints.cs`
- Delete or modify: `src/vision/mavi_vision/video/media_reference.py`
- Modify affected tests

**Interfaces:**
- Application lease view must not carry worker wire `schemaVersion`.
- Heartbeat success should use a non-nullable success-specific result type rather than nullable fields on a generic result.
- Active Python source must not contain the retired `media_uri` worker abstraction.

- [ ] **Step 1: Remove `SchemaVersion` from internal `VisionLeaseView`**

The API mapping should supply:

```csharp
WorkerContractRules.SchemaVersion
```

directly when constructing `VisionJobLeaseContract`.

- [ ] **Step 2: Introduce a typed heartbeat result**

Use a result equivalent to:

```csharp
public sealed record HeartbeatResult(
    bool IsSuccess,
    string? ErrorCode,
    double ProgressPercent,
    DateTimeOffset LeaseExpiresAtUtc);
```

or another discriminated shape that does not require `!.Value` on a successful path. Keep fail/command results separate.

- [ ] **Step 3: Remove retired Python `media_uri` residue**

Search for references to:

```text
MediaReference
media_uri
mediaUri
```

If `media_reference.py` is unused, delete it. If a legitimate pre-Task-8 consumer exists, change it to a logical `source_storage_key` model and test it. Do not create a Python media resolver or worker client yet.

- [ ] **Step 4: Run static scans**

Worker-control-plane active source must contain no retired `mediaUri`/`media_uri` abstraction except historical documentation where explicitly marked retired.

- [ ] **Step 5: Commit**

```powershell
git add src/platform/Mavi.Application src/platform/Mavi.Infrastructure src/platform/Mavi.Api src/vision tests
git commit -m "refactor: clean Task 7A worker boundaries"
```

---

### Task 7: Final Task 7A.1 Verification Gate

**Files:**
- Modify documentation only if implementation changed an approved invariant
- Modify `tools/verify_repo.py` only to strengthen—not weaken—checks

- [ ] **Step 1: Run complete .NET verification**

```powershell
dotnet build MAVI.sln
dotnet test MAVI.sln
```

Record per-project and total test counts.

- [ ] **Step 2: Run repository verification**

```powershell
python tools/verify_repo.py
```

- [ ] **Step 3: Run Python control-plane suite**

```bash
cd src/vision
python -m pytest -q
```

- [ ] **Step 4: Run frontend regression gate**

From `src/web/mavi-web` run the existing applicable scripts:

```bash
npm test
npm run typecheck
npm run build
```

- [ ] **Step 5: Run migration verification against a clean PostgreSQL test DB**

Apply all migrations from zero and run the new historical upgrade-path test.

- [ ] **Step 6: Run static security/architecture scans**

Search for and explain every intentional occurrence of:

```text
mediaUri
media_uri
schemaVersion "1.0" in worker-control-plane artifacts
lease_token
LeaseToken
DateTime.UtcNow
DateTimeOffset.UtcNow
DateTime.Now
DateTimeOffset.Now
Thread.Sleep
Task.Delay
```

Confirm no raw capability is persisted/logged/status-exposed.

- [ ] **Step 7: Run diff hygiene**

```bash
git diff --check
```

- [ ] **Step 8: Commit final documentation/verifier updates**

```powershell
git add docs tools contracts tests src
git commit -m "docs: close Task 7A review remediation"
```

---

## Acceptance Gate Before Task 8

Task 8 may start only when all of the following are demonstrated:

1. malformed canonical-looking Base64Url never throws and returns controlled validation failure;
2. heartbeat without `progressPercent` cannot extend a lease;
3. optional `failureMessage` has identical semantics in .NET, JSON Schema, and Python;
4. worker IDs and failure codes have one canonical cross-language validation rule;
5. old/same-worker stale capabilities remain rejected;
6. `Complete` cannot bypass capability validation;
7. attempt exhaustion revokes worker capability and cannot masquerade as idempotent worker failure;
8. presented raw token cannot be copied into persistent failure diagnostics;
9. heartbeat/fail lock-wait tests prove post-lock authoritative time behavior;
10. the pre-v2 migration upgrade path is exercised with a real historical leased row;
11. `VisionLeaseView` no longer owns the wire schema version;
12. heartbeat success is type-safe;
13. retired Python `media_uri` worker residue is removed;
14. all .NET, Python, frontend, migration, contract, verifier, concurrency, and diff-hygiene gates pass;
15. Task 8 has not started.
