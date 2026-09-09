# Task 7A.2 Final Contract Parity Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the last known worker-control-plane parity and type-safety gaps so the Task 7/7A lease boundary can be frozen before Task 8 begins.

**Architecture:** Preserve the approved Task 7A lease-capability design. This checkpoint is deliberately narrow: make Python wire validation strict, align remaining JSON Schema constraints with the canonical v2 model, enforce canonical worker identity below the HTTP boundary, replace nullable heartbeat-success plumbing with a type-safe result, strengthen the historical migration test to prove an actual post-upgrade reclaim, and perform one final review gate before merge.

**Tech Stack:** .NET 10 / ASP.NET Core / EF Core / PostgreSQL / System.Text.Json, JSON Schema 2020-12, Python 3.13 package metadata with Pydantic v2, pytest, repository verifier, React/Vite verification only.

**Spec:** `docs/superpowers/specs/2026-09-09-task-7a-lease-contract-hardening-design.md`

## Global Constraints

- Do not start Task 8.
- Do not redesign the lease-capability architecture.
- Do not rewrite accepted migrations.
- Raw lease capability remains worker-only and hash-only at rest.
- PostgreSQL remains the lease concurrency authority.
- Exact expiry remains `LeaseExpiresAtUtc <= nowUtc`.
- `Mavi.Contracts` remains the public worker HTTP boundary.
- Worker control-plane version remains exactly `2.0`; v1 remains retired.
- Worker control-plane input is canonical machine data; do not silently normalize it.
- Python remains contract-only; no polling, HTTP worker client, media resolution, decoding, inference, tracking, or result submission.
- Preserve the current Python `requires-python = ">=3.13"` declaration until Task 8.
- Use TDD for every behavioral change.
- Do not merge the implementation PR until the GitHub Codex review has completed and every P1/P2 finding has been addressed.

---

## File Structure Map

Primary files expected to change:

```text
src/vision/mavi_vision/common/
  control_plane.py

src/vision/tests/
  test_control_plane_contracts.py

contracts/schemas/
  vision-job-lease-v2.schema.json
  vision-job-heartbeat-v2.schema.json
  vision-job-heartbeat-response-v2.schema.json
  vision-job-fail-v2.schema.json
  worker-health-v2.schema.json

contracts/test-vectors/
  control-plane-v2-invalid.json

src/platform/Mavi.Domain/Processing/
  VisionJob.cs
  ProcessingRun.cs

src/platform/Mavi.Application/Modules/Intelligence/
  IProcessingOrchestrator.cs

src/platform/Mavi.Infrastructure/Persistence/Repositories/
  ProcessingOrchestrator.cs

src/platform/Mavi.Api/Endpoints/
  VisionJobEndpoints.cs

tests/Mavi.Domain.Tests/
  ProcessingOrchestrationStateTests.cs

tests/Mavi.IntegrationTests/
  WorkerContractV2Tests.cs
  ProcessingOrchestrationApiTests.cs
  MigrationTests.cs

tools/
  verify_repo.py
```

No migration file should change unless a test proves a previously accepted migration is wrong.

---

### Task 1: Make Python Wire Validation Strict Instead of Coercive

**Files:**
- Modify: `src/vision/mavi_vision/common/control_plane.py`
- Modify: `src/vision/tests/test_control_plane_contracts.py`
- Modify: `contracts/test-vectors/control-plane-v2-invalid.json`

**Interfaces:**
- Python models continue exposing the same v2 field names and aliases.
- Raw HTTP JSON must be validated with strict JSON semantics: JSON numeric strings are not numbers, epoch integers are not date-time strings, and normal JSON date-time/UUID strings remain valid.

- [ ] **Step 1: Add RED Python tests for the Codex numeric-coercion finding**

Add invalid cases equivalent to:

```json
{"progressPercent":"50"}
{"attemptCount":"1"}
{"width":"1920"}
{"durationMs":"1000"}
```

For each case, start from the appropriate canonical payload and validate the raw serialized JSON.

Expected: `ValidationError`.

Use `model_validate_json(...)`, not `json.loads(...)` followed by `model_validate(...)`, for wire-protocol tests.

- [ ] **Step 2: Add RED strict date-time test**

For a heartbeat response or lease payload, replace a date-time string with an integer epoch:

```json
{"leaseExpiresAtUtc":1788912000}
```

Expected: `ValidationError`.

- [ ] **Step 3: Confirm canonical JSON still passes**

The canonical lease example must continue to parse from raw JSON:

```python
model = VisionJobLease.model_validate_json(EXAMPLE.read_text())
assert model.model_dump(by_alias=True, mode="json") == json.loads(EXAMPLE.read_text())
```

- [ ] **Step 4: Enable strict Pydantic wire semantics**

Update the base model to use:

```python
class ControlPlaneModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        strict=True,
        alias_generator=lambda n: n.split("_")[0] + "".join(x.title() for x in n.split("_")[1:]),
    )
```

Keep programmatic construction valid for native Python values such as `datetime` and `UUID`.

Remove unused `StrictInt` / `StrictFloat` imports unless they remain genuinely necessary after strict-model validation is enabled.

- [ ] **Step 5: Convert shared-vector Python tests to raw JSON validation**

Use:

```python
model.model_validate_json(json.dumps(vector["payload"]))
```

This verifies actual wire semantics rather than Python-object coercion semantics.

- [ ] **Step 6: Run Python tests GREEN**

```bash
cd src/vision
python -m pytest -q
```

- [ ] **Step 7: Commit**

```bash
git add src/vision/mavi_vision/common/control_plane.py src/vision/tests/test_control_plane_contracts.py contracts/test-vectors/control-plane-v2-invalid.json
git commit -m "fix: enforce strict Python worker wire types"
```

---

### Task 2: Align Remaining JSON Schema Constraints with the Canonical v2 Model

**Files:**
- Modify: `contracts/schemas/vision-job-lease-v2.schema.json`
- Modify: `contracts/schemas/vision-job-heartbeat-v2.schema.json`
- Modify: `contracts/schemas/vision-job-heartbeat-response-v2.schema.json`
- Modify: `contracts/test-vectors/control-plane-v2-invalid.json`
- Modify: `tools/verify_repo.py` only if needed to expose vector counts/results more clearly
- Modify: `src/vision/tests/test_control_plane_contracts.py`

**Interfaces:**
- JSON Schema and Python must reject the same numeric/string bound violations for fields already constrained by the existing Python model.

- [ ] **Step 1: Add RED shared invalid vectors for numeric type and bound drift**

Add vectors for at least:

```text
heartbeat progressPercent = "50"
lease attemptCount = "1"
lease attemptCount = 0
lease sourceSizeBytes = -1
lease durationMs = -1
lease width = 0
lease height = 0
lease frameRateNumerator = 0
lease frameRateDenominator = 0
heartbeat-response leaseExpiresAtUtc = integer epoch
```

- [ ] **Step 2: Add RED vectors for existing string-bound drift**

Add over-length values for:

```text
pipeline > 64
pipelineVersion > 64
recordingTimeZoneId > 64
```

- [ ] **Step 3: Tighten the lease schema to match existing Python semantics**

Apply:

```json
"attemptCount": { "type": "integer", "minimum": 1 }
"sourceSizeBytes": { "type": "integer", "minimum": 0 }
"durationMs": { "type": "integer", "minimum": 0 }
"width": { "type": "integer", "minimum": 1 }
"height": { "type": "integer", "minimum": 1 }
"frameRateNumerator": { "type": "integer", "minimum": 1 }
"frameRateDenominator": { "type": "integer", "minimum": 1 }
```

Retain existing `maxLength: 64` constraints for `pipeline`, `pipelineVersion`, and `recordingTimeZoneId`.

- [ ] **Step 4: Apply the same string bounds in Pydantic**

Use explicit fields such as:

```python
pipeline: StrictStr = Field(min_length=1, max_length=64)
pipeline_version: StrictStr = Field(min_length=1, max_length=64)
recording_time_zone_id: StrictStr = Field(min_length=1, max_length=64)
```

Under strict model configuration, an ordinary `str = Field(...)` is also acceptable if the tests prove numeric/non-string coercion is rejected.

Do not invent new offset or timezone semantics in this task.

- [ ] **Step 5: Run verifier and Python parity tests GREEN**

```bash
python tools/verify_repo.py
cd src/vision && python -m pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add contracts/schemas contracts/test-vectors/control-plane-v2-invalid.json src/vision/mavi_vision/common/control_plane.py src/vision/tests/test_control_plane_contracts.py tools/verify_repo.py
git commit -m "fix: align worker schema bounds with Python contracts"
```

---

### Task 3: Enforce Canonical Worker Identity Below the HTTP Boundary

**Files:**
- Modify: `src/platform/Mavi.Domain/Processing/VisionJob.cs`
- Modify: `src/platform/Mavi.Domain/Processing/ProcessingRun.cs`
- Modify: `tests/Mavi.Domain.Tests/ProcessingOrchestrationStateTests.cs`
- Modify: `tests/Mavi.IntegrationTests/ProcessingOrchestrationApiTests.cs` only if service-level coverage is cleaner there

**Interfaces:**
- Internal domain methods must accept only already-canonical worker IDs.
- Domain code must never trim and persist one worker ID while returning/using a different external representation.

- [ ] **Step 1: Add RED domain tests for padded worker IDs**

Prove each rejects an ID such as `" worker-a "`:

```text
VisionJob.Lease
VisionJob.Heartbeat / Complete / Fail via owner matching
ProcessingRun.AssignLease
ProcessingRun.MarkRunning if still used
```

The canonical ID `worker-a` continues to pass.

- [ ] **Step 2: Replace trim-and-store behavior with validate-and-store-exact behavior**

For lease/run assignment use an invariant equivalent to:

```csharp
if (string.IsNullOrWhiteSpace(workerId) ||
    workerId.Length > 128 ||
    !string.Equals(workerId, workerId.Trim(), StringComparison.Ordinal))
    throw Invalid(...);

LeaseOwner = workerId;
WorkerId = workerId;
```

Do not add a Domain -> Contracts dependency.

- [ ] **Step 3: Verify the API behavior remains unchanged**

Canonical IDs are accepted. Padded IDs remain HTTP 400 before orchestration.

- [ ] **Step 4: Run domain + orchestration tests GREEN**

```bash
dotnet test tests/Mavi.Domain.Tests/Mavi.Domain.Tests.csproj --filter ProcessingOrchestrationStateTests
dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj --filter ProcessingOrchestrationApiTests
```

- [ ] **Step 5: Commit**

```bash
git add src/platform/Mavi.Domain/Processing tests/Mavi.Domain.Tests tests/Mavi.IntegrationTests
git commit -m "fix: enforce canonical worker identity in domain state"
```

---

### Task 4: Replace Nullable Heartbeat Success Plumbing with a Type-Safe Result

**Files:**
- Modify: `src/platform/Mavi.Application/Modules/Intelligence/IProcessingOrchestrator.cs`
- Modify: `src/platform/Mavi.Infrastructure/Persistence/Repositories/ProcessingOrchestrator.cs`
- Modify: `src/platform/Mavi.Api/Endpoints/VisionJobEndpoints.cs`
- Modify: `tests/Mavi.IntegrationTests/ProcessingOrchestrationApiTests.cs`

**Interfaces:**
- `FailAsync` may continue returning the existing simple `OrchestrationResult`.
- `HeartbeatAsync` returns a dedicated result whose success shape always contains progress and expiry.

- [ ] **Step 1: Introduce a discriminated heartbeat result**

Use a type equivalent to:

```csharp
public abstract record HeartbeatResult
{
    private HeartbeatResult() { }

    public sealed record Success(double ProgressPercent, DateTimeOffset LeaseExpiresAtUtc) : HeartbeatResult;
    public sealed record Failure(string ErrorCode) : HeartbeatResult;
}
```

Update:

```csharp
Task<HeartbeatResult> HeartbeatAsync(...)
```

- [ ] **Step 2: Add RED/compile-time endpoint test expectations**

Existing successful heartbeat tests must continue asserting HTTP 200 and v2 response contents; invalid heartbeat paths must continue returning the same stable error codes.

- [ ] **Step 3: Return explicit success/failure variants from orchestration**

Successful heartbeat returns:

```csharp
new HeartbeatResult.Success(job.ProgressPercent, job.LeaseExpiresAtUtc!.Value)
```

Failures return:

```csharp
new HeartbeatResult.Failure("vision_job_lease_invalid")
```

Do not use nullable success payload fields.

- [ ] **Step 4: Pattern-match in the endpoint**

Use the shared version constant:

```csharp
return result switch
{
    HeartbeatResult.Success success => Results.Ok(
        new VisionJobHeartbeatResponse(
            WorkerContractRules.SchemaVersion,
            success.ProgressPercent,
            success.LeaseExpiresAtUtc)),
    HeartbeatResult.Failure failure => Result(failure.ErrorCode),
    _ => throw new UnreachableException(),
};
```

Add the required namespace for `UnreachableException` or use an equivalent exhaustive helper.

This also removes the remaining literal `"2.0"` from heartbeat response construction.

- [ ] **Step 5: Run Application/Integration tests GREEN**

```bash
dotnet test tests/Mavi.Application.Tests/Mavi.Application.Tests.csproj
dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj --filter ProcessingOrchestrationApiTests
```

- [ ] **Step 6: Commit**

```bash
git add src/platform/Mavi.Application/Modules/Intelligence/IProcessingOrchestrator.cs src/platform/Mavi.Infrastructure/Persistence/Repositories/ProcessingOrchestrator.cs src/platform/Mavi.Api/Endpoints/VisionJobEndpoints.cs tests/Mavi.IntegrationTests
git commit -m "refactor: make heartbeat orchestration result type safe"
```

---

### Task 5: Strengthen the Historical Migration Test to Prove Actual Reclaim

**Files:**
- Modify: `tests/Mavi.IntegrationTests/MigrationTests.cs`
- Do not modify: `src/platform/Mavi.Infrastructure/Persistence/Migrations/20260909080708_HardenVisionJobLeases.cs` unless this stronger test proves it wrong

**Interfaces:**
- The historical row must represent a realistic active Task-7 chain before upgrade.
- After migration, the test must execute a real v2 lease reclaim and verify a fresh capability is issued.

- [ ] **Step 1: Make the seeded historical chain internally realistic**

For the upgrade-specific seeded row ensure:

```text
VideoAsset.ProcessingStatus = Processing
ProcessingRun.Status = Running
VisionJob.Status = Leased
ProcessingRun.WorkerId = legacy-worker
VisionJob.LeaseOwner = legacy-worker
AttemptCount = 2
ProgressPercent = 40
future lease expiry
```

Preserve the existing historical-schema constraints.

- [ ] **Step 2: Keep the existing post-migration structural assertions**

Continue proving:

```text
AttemptCount == 2
LeaseTokenHash is null immediately after migration
lease expiry <= CURRENT_TIMESTAMP
bytea column
32-byte check constraint
partial leased-expiry index
```

- [ ] **Step 3: Execute a real post-upgrade reclaim**

After applying `HardenVisionJobLeases`, instantiate/use the current `ProcessingOrchestrator` against the migrated database with the current lease-capability service and configured processing options.

Call:

```csharp
var lease = await orchestrator.LeaseAsync("upgrade-worker", CancellationToken.None);
```

Assert:

```text
lease != null
lease.WorkerId == upgrade-worker
lease.AttemptCount == 3
lease.LeaseToken is canonical
VisionJob.LeaseTokenHash is 32 bytes
VisionJob.LeaseOwner == upgrade-worker
VisionJob.ProgressPercent == 0
VisionJob.LastHeartbeatUtc == null
ProcessingRun.StartedAtUtc preserved
VideoAsset remains Processing
```

This turns “eligible for reclaim” into “actually reclaimed successfully by the current v2 implementation.”

- [ ] **Step 4: Run migration tests GREEN**

```bash
dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj --filter HardenedLeaseMigration
```

- [ ] **Step 5: Commit**

```bash
git add tests/Mavi.IntegrationTests/MigrationTests.cs
git commit -m "test: prove legacy lease reclaims after v2 migration"
```

---

### Task 6: Make Shared Invalid Vectors a True Cross-Language Gate

**Files:**
- Modify: `contracts/test-vectors/control-plane-v2-invalid.json`
- Modify: `src/vision/tests/test_control_plane_contracts.py`
- Modify: `tests/Mavi.IntegrationTests/WorkerContractV2Tests.cs`
- Modify: `tools/verify_repo.py`

**Interfaces:**
- JSON Schema remains the canonical syntax validator for all contract artifacts.
- Python consumes all shared vectors using raw JSON validation.
- .NET consumes the subset representing inbound worker requests and proves the public HTTP boundary rejects them.

- [ ] **Step 1: Tag each vector by direction**

Extend vector records with a field such as:

```json
"direction": "worker-request"
```

or:

```json
"direction": "platform-response"
```

Keep `schema`, `name`, and `payload`.

- [ ] **Step 2: Update the repository verifier**

Continue validating that every vector is rejected by its named JSON Schema regardless of direction.

- [ ] **Step 3: Update Python tests**

Python must reject every vector through raw JSON validation because it both emits worker requests and consumes platform responses.

- [ ] **Step 4: Add .NET request-vector integration coverage**

For each vector with `direction == "worker-request"`, route it to the corresponding endpoint:

```text
vision-job-lease-request-v2  -> POST /api/vision/jobs/lease
vision-job-heartbeat-v2      -> POST /api/vision/jobs/{jobId}/heartbeat
vision-job-fail-v2           -> POST /api/vision/jobs/{jobId}/fail
```

Use a valid leased job where a job ID/token is required, replacing only the intentionally invalid field represented by the vector.

Assert controlled 4xx rejection, never 5xx.

Do not force .NET to deserialize invalid platform-response DTOs merely for symmetry; those responses are produced by the platform and are guarded by domain/application invariants plus canonical serialization tests.

- [ ] **Step 5: Run all parity gates GREEN**

```bash
python tools/verify_repo.py
cd src/vision && python -m pytest -q
cd ../..
dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj --filter "WorkerContractV2Tests|ProcessingOrchestrationApiTests"
```

- [ ] **Step 6: Commit**

```bash
git add contracts/test-vectors src/vision/tests tests/Mavi.IntegrationTests/WorkerContractV2Tests.cs tests/Mavi.IntegrationTests/ProcessingOrchestrationApiTests.cs tools/verify_repo.py
git commit -m "test: enforce shared worker contract rejection vectors"
```

---

### Task 7: Final Task 7A Boundary Verification and Review Gate

**Files:**
- Modify documentation only if required to record the closure checkpoint
- Do not add Task-8 implementation

**Interfaces:**
- This task produces the final go/no-go evidence for Task 8.

- [ ] **Step 1: Run the full environment baseline**

```bash
source /etc/profile.d/mavi-codex.sh || true
pg_ctlcluster 18 main start >/dev/null 2>&1 || true
for i in $(seq 1 30); do pg_isready -h localhost -p 5432 >/dev/null 2>&1 && break; sleep 1; done
pg_isready -h localhost -p 5432

dotnet --info
psql --version
python --version
ffmpeg -version
ffprobe -version
```

- [ ] **Step 2: Run full repository verification**

```bash
dotnet build MAVI.sln
dotnet test MAVI.sln
python tools/verify_repo.py
cd src/vision && python -m pytest -q && cd ../..
cd src/web/mavi-web && npm test && npm run typecheck && npm run build && cd ../../..
git diff --check
```

Record actual counts. Do not assume the previous 163 .NET / 12 Python counts.

- [ ] **Step 3: Static-scan the final boundary**

Search for:

```text
StrictInt
StrictFloat
model_validate(
model_validate_json(
mediaUri
media_uri
schemaVersion "1.0"
"2.0"
workerId.Trim
LeaseToken
lease_token
Thread.Sleep
Task.Delay
DateTime.UtcNow
DateTimeOffset.UtcNow
DateTime.Now
DateTimeOffset.Now
```

Explain every intentional occurrence.

Specifically confirm:

```text
no numeric-string coercion in Python wire models
no epoch-number datetime acceptance in Python wire models
no padded WorkerId acceptance below HTTP boundary
no heartbeat success nullable dereference
no active worker-control-plane v1
no raw lease-token persistence
```

- [ ] **Step 4: Open the implementation PR but DO NOT MERGE IMMEDIATELY**

Wait for the GitHub Codex review to finish.

If Codex reports any P1 or P2 finding:

```text
reproduce
→ fix with TDD
→ rerun focused tests
→ rerun full verification
→ request/retrigger review if required
```

Merge only after there are no unresolved P1/P2 findings.

- [ ] **Step 5: Commit closure documentation if modified**

Recommended commit only if a doc update is required:

```bash
git add docs
git commit -m "docs: close Task 7A worker boundary hardening"
```

---

## Final Acceptance Matrix

Task 7A.2 is complete only when all of the following are proven:

```text
PYTHON STRICTNESS
✓ progressPercent "50" rejected
✓ attemptCount "1" rejected
✓ width "1920" rejected
✓ epoch integer datetime rejected
✓ canonical JSON UUID/date-time strings still accepted
✓ canonical golden lease round-trips from raw JSON

SCHEMA PARITY
✓ attemptCount minimum 1
✓ size/duration lower bounds aligned
✓ dimensions/frame rates positive
✓ pipeline max length aligned
✓ pipelineVersion max length aligned
✓ recordingTimeZoneId max length aligned
✓ all shared invalid vectors rejected by JSON Schema

WORKER IDENTITY
✓ padded worker ID rejected at HTTP boundary
✓ padded worker ID rejected by Domain lease/run assignment
✓ canonical worker ID stored without normalization drift

HEARTBEAT TYPE SAFETY
✓ dedicated heartbeat success type carries progress + expiry
✓ failures carry only stable error code
✓ no `!.Value` heartbeat success dereference
✓ response uses WorkerContractRules.SchemaVersion

MIGRATION
✓ realistic legacy running/leased chain upgrades
✓ AttemptCount preserved at 2 on migration
✓ no fake capability invented by migration
✓ actual current LeaseAsync reclaims the migrated lease
✓ reclaim issues new capability
✓ AttemptCount becomes 3
✓ progress resets to zero
✓ ProcessingRun.StartedAtUtc remains preserved

CROSS-LANGUAGE GATE
✓ shared invalid vectors rejected by schema
✓ shared invalid vectors rejected by Python raw-JSON validation
✓ inbound request vectors rejected by .NET HTTP boundary
✓ no invalid vector causes HTTP 500

FINAL VERIFICATION
✓ dotnet build
✓ complete .NET test suite
✓ Python tests
✓ repository verifier
✓ frontend tests
✓ frontend typecheck
✓ frontend production build
✓ git diff --check
✓ Codex PR review completed
✓ no unresolved P1/P2 review finding
✓ Task 8 not started
```

## Explicit Non-Goals

Do not implement in Task 7A.2:

- Python lease polling;
- HTTP worker client;
- heartbeat scheduler;
- Python local-media resolver;
- PyAV / video decoding;
- RTMDet;
- ByteTrack;
- PyTorch inference;
- worker success/result endpoint;
- VisionResult ingestion;
- Track/Observation persistence from worker output;
- RTSP;
- ReID;
- ANPR;
- LLM/VLM;
- Phase 2;
- broad CI/CD redesign.

The Python runtime baseline transition and executable worker environment belong to Task 8.
