# Task 7A.3 Contract Canonicalization & Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze the Task 7/7A worker control-plane boundary by making wire representations canonical across .NET, JSON Schema, and Python, and by adding a reproducible GitHub CI quality gate before Task 8 begins.

**Architecture:** Preserve the approved Task 7A lease-capability, PostgreSQL concurrency, and worker-control-plane v2 architecture. Task 7A.3 is deliberately narrow: accept only canonical camelCase worker JSON in Python, require canonical UTC `Z` timestamps on all worker wire contracts, define one safe WorkerId alphabet across all layers, document global strict API numeric JSON policy, and add CI that runs the existing .NET/PostgreSQL, contract, Python 3.13, and frontend verification on every relevant pull request.

**Tech Stack:** .NET 10 / ASP.NET Core / EF Core / PostgreSQL 18 + pgvector / System.Text.Json, JSON Schema 2020-12, Python 3.13 + Pydantic v2 + pytest + jsonschema, Node 22 + React/Vite/Vitest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-09-task-7a-lease-contract-hardening-design.md`

## Global Constraints

- Do not start Task 8.
- Do not redesign the secure lease-capability architecture.
- Do not rewrite any accepted EF Core migration.
- Raw lease capability remains worker-only and hash-only at rest.
- PostgreSQL remains the concurrency authority.
- Exact expiry remains `LeaseExpiresAtUtc <= nowUtc`.
- `Mavi.Contracts` remains the public worker HTTP boundary.
- Worker control-plane version remains exactly `2.0`; v1 remains retired.
- Machine-to-machine worker JSON is canonical protocol data, not user-entered input.
- Python remains contract-only in Task 7A.3; no polling, HTTP worker client, media resolution, decoding, inference, tracking, or result submission.
- Preserve `requires-python = ">=3.13"`.
- Global API numeric JSON strictness introduced in Task 7A.2 is retained unless tests prove an incompatible existing endpoint.
- Use TDD for behavioral changes.
- The implementation PR must remain open until GitHub CI is green and the GitHub Codex review has completed with zero unresolved P1/P2 findings.

---

## File Structure Map

Primary files expected to change:

```text
src/vision/mavi_vision/common/
  control_plane.py

src/vision/mavi_vision/worker/
  health.py

src/vision/tests/
  test_control_plane_contracts.py

src/platform/Mavi.Contracts/Worker/
  WorkerContractRules.cs
  UtcDateTimeOffsetJsonConverter.cs

src/platform/Mavi.Domain/Processing/
  VisionJob.cs
  ProcessingRun.cs

src/platform/Mavi.Api/
  Program.cs

contracts/schemas/
  vision-job-lease-request-v2.schema.json
  vision-job-lease-v2.schema.json
  vision-job-heartbeat-v2.schema.json
  vision-job-fail-v2.schema.json
  worker-health-v2.schema.json

contracts/test-vectors/
  control-plane-v2-invalid.json

tests/Mavi.Domain.Tests/
  ProcessingOrchestrationStateTests.cs

tests/Mavi.IntegrationTests/
  WorkerContractV2Tests.cs

.github/workflows/
  quality-gate.yml

docs/superpowers/plans/
  2026-09-09-task-7a3-contract-canonicalization-quality-gate.md
```

Do not add a migration for these contract-only changes.

---

### Task 1: Make Python Worker JSON Alias-Only

**Files:**
- Modify: `src/vision/mavi_vision/common/control_plane.py`
- Modify: `src/vision/mavi_vision/worker/health.py`
- Modify: `src/vision/tests/test_control_plane_contracts.py`
- Modify: `contracts/test-vectors/control-plane-v2-invalid.json`

**Interfaces:**
- Public wire property names remain the existing camelCase JSON names.
- Python internal attribute names may remain snake_case.
- Raw JSON validation must accept aliases only; Python field names are not alternative wire spellings.

- [ ] **Step 1: Add RED tests proving snake_case wire properties are rejected**

Add raw-JSON tests equivalent to:

```python
with pytest.raises(ValidationError):
    VisionJobLeaseRequest.model_validate_json(
        '{"schema_version":"2.0","worker_id":"gpu-sdd-01"}'
    )

with pytest.raises(ValidationError):
    VisionJobHeartbeat.model_validate_json(json.dumps({
        "schemaVersion": "2.0",
        "worker_id": "gpu-sdd-01",
        "leaseToken": "A" * 43,
        "progressPercent": 50,
    }))
```

Also prove the canonical camelCase forms still pass.

- [ ] **Step 2: Change Pydantic configuration to alias-only wire validation**

Replace `populate_by_name=True` with explicit Pydantic-v2 alias behavior equivalent to:

```python
class ControlPlaneModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_by_alias=True,
        validate_by_name=False,
        serialize_by_alias=True,
        alias_generator=snake_to_camel,
    )
```

If the installed Pydantic version requires a different exact option name, use the supported v2.11+ equivalent and prove behavior with the tests above. Do not restore permissive name population.

- [ ] **Step 3: Keep programmatic worker-health construction explicit**

Because `health.py` currently creates `WorkerHealth` using Python field names, update it to construct through canonical aliases or an explicit factory. One acceptable implementation is:

```python
def get_worker_health(worker_id: str) -> WorkerHealth:
    return WorkerHealth.model_validate({
        "schemaVersion": "2.0",
        "workerId": worker_id,
        "status": "ready",
        "timestampUtc": datetime.now(timezone.utc),
    })
```

If strict model validation makes the datetime construction path unsuitable, introduce a small `WorkerHealth.create(...)` classmethod that accepts native typed values but does not change raw JSON alias policy.

- [ ] **Step 4: Add shared invalid vectors for snake_case wire aliases**

At minimum add:

```text
lease request with schema_version
lease request with worker_id
heartbeat with worker_id
fail with failure_code
```

Tag each as `direction: worker-request` and point each at its existing v2 schema.

- [ ] **Step 5: Run Python and schema gates**

```bash
cd src/vision
python -m pytest -q
cd ../..
python tools/verify_repo.py
```

Expected: all tests and contract verification pass.

- [ ] **Step 6: Commit**

```bash
git add src/vision/mavi_vision/common/control_plane.py src/vision/mavi_vision/worker/health.py src/vision/tests/test_control_plane_contracts.py contracts/test-vectors/control-plane-v2-invalid.json
git commit -m "fix: require canonical worker JSON aliases"
```

---

### Task 2: Require Canonical `Z` UTC Timestamps on the Worker Wire

**Files:**
- Modify: `src/vision/mavi_vision/common/control_plane.py`
- Modify: `src/platform/Mavi.Contracts/Worker/UtcDateTimeOffsetJsonConverter.cs`
- Modify: `src/vision/tests/test_control_plane_contracts.py`
- Modify: `tests/Mavi.IntegrationTests/WorkerContractV2Tests.cs`
- Modify: `contracts/test-vectors/control-plane-v2-invalid.json`

**Interfaces:**
- Canonical worker timestamp syntax is ISO-8601 UTC ending in uppercase `Z`.
- `+00:00`, `+0000`, lowercase `z`, local/naive timestamps, and non-zero offsets are not accepted on the worker wire.
- Serialization from .NET and Python continues producing canonical UTC strings.

- [ ] **Step 1: Add RED Python tests for lexical UTC canonicalization**

For each timestamp-bearing contract, prove canonical `Z` succeeds and equivalent zero-offset syntax is rejected:

```python
valid = "2026-09-09T03:00:00Z"
invalid = "2026-09-09T03:00:00+00:00"
```

At minimum cover:

```text
VisionJobLease.leaseExpiresAtUtc
VisionJobLease.recordingStartUtc
VisionJobLease.recordingEndUtc
VisionJobHeartbeatResponse.leaseExpiresAtUtc
WorkerHealth.timestampUtc
```

Use `model_validate_json(...)` for these tests.

- [ ] **Step 2: Add a Python before-validator for timestamp syntax**

Use a `field_validator(..., mode="before")` or a reusable annotated type so raw wire timestamp values must first be strings ending exactly in `Z` before Pydantic converts them to `datetime`.

One acceptable pattern is:

```python
@field_validator(
    "lease_expires_at_utc",
    "recording_start_utc",
    "recording_end_utc",
    mode="before",
    check_fields=False,
)
@classmethod
def require_canonical_utc_wire(cls, value: object) -> object:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("worker contract timestamp must use canonical UTC Z syntax")
    return value
```

Prefer a reusable type/validator if it avoids duplication across models. Retain the existing post-parse UTC semantic check as defense in depth.

- [ ] **Step 3: Make the .NET worker timestamp converter require lexical `Z`**

Current `UtcDateTimeOffsetJsonConverter.Read` accepts any zero-offset representation. Change it so it first requires a JSON string whose textual form ends exactly in uppercase `Z`, then parses it as a `DateTimeOffset`, then verifies zero offset.

Use a pattern equivalent to:

```csharp
if (reader.TokenType != JsonTokenType.String)
    throw new JsonException("Worker contract timestamps must be JSON strings.");

var raw = reader.GetString();
if (string.IsNullOrEmpty(raw) || !raw.EndsWith('Z'))
    throw new JsonException("Worker contract timestamps must use canonical UTC Z syntax.");

if (!DateTimeOffset.TryParse(raw, CultureInfo.InvariantCulture,
        DateTimeStyles.RoundtripKind, out var value) || value.Offset != TimeSpan.Zero)
    throw new JsonException("Worker contract timestamps must be UTC.");

return value;
```

Keep writer output as canonical `...Z`.

- [ ] **Step 4: Add .NET contract tests**

Add tests that deserialize the public DTO with:

```text
2026-09-09T03:00:00Z        -> accepted
2026-09-09T03:00:00+00:00   -> JsonException
2026-09-09T08:30:00+05:30   -> JsonException
```

Also prove serialization ends in `Z`.

- [ ] **Step 5: Add shared invalid vectors**

Add platform-response vectors for zero-offset-but-noncanonical timestamps, including:

```text
heartbeat response leaseExpiresAtUtc = ...+00:00
lease response leaseExpiresAtUtc = ...+00:00
worker health timestampUtc = ...+00:00
```

The schemas already require `Z$`; these vectors must fail schema and Python validation.

- [ ] **Step 6: Run focused tests**

```bash
cd src/vision && python -m pytest -q && cd ../..
dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj --filter WorkerContractV2Tests
python tools/verify_repo.py
```

- [ ] **Step 7: Commit**

```bash
git add src/vision/mavi_vision/common/control_plane.py src/platform/Mavi.Contracts/Worker/UtcDateTimeOffsetJsonConverter.cs src/vision/tests/test_control_plane_contracts.py tests/Mavi.IntegrationTests/WorkerContractV2Tests.cs contracts/test-vectors/control-plane-v2-invalid.json
git commit -m "fix: require canonical UTC worker timestamps"
```

---

### Task 3: Define One Safe WorkerId Alphabet Across All Layers

**Files:**
- Modify: `src/platform/Mavi.Contracts/Worker/WorkerContractRules.cs`
- Modify: `src/platform/Mavi.Domain/Processing/VisionJob.cs`
- Modify: `src/platform/Mavi.Domain/Processing/ProcessingRun.cs`
- Modify: `src/vision/mavi_vision/common/control_plane.py`
- Modify: all worker v2 schemas containing `workerId`
- Modify: `tests/Mavi.Domain.Tests/ProcessingOrchestrationStateTests.cs`
- Modify: `tests/Mavi.IntegrationTests/WorkerContractV2Tests.cs`
- Modify: `src/vision/tests/test_control_plane_contracts.py`
- Modify: `contracts/test-vectors/control-plane-v2-invalid.json`

**Interfaces:**
- Canonical WorkerId syntax becomes exactly:

```regex
^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$
```

- This is an opaque identifier, not a hostname, UUID, or URI.
- WorkerId remains ordinal case-sensitive.

- [ ] **Step 1: Add RED cross-layer WorkerId vectors**

Valid examples:

```text
gpu-sdd-01
gpu.sdd.01
gpu_sdd_01
A1
```

Invalid examples:

```text
-gpu
_gpu
.gpu
gpu worker
gpu/worker
gpu:worker
gpu\worker
gpu\nworker
gpu\tworker
non-ASCII identifier
129-character identifier
```

Use exact real newline/tab characters in tests where possible, not only escaped display text.

- [ ] **Step 2: Centralize .NET contract validation**

Change `WorkerContractRules.TryNormalizeWorkerId` into a clearly named canonical validator if practical, for example:

```csharp
public static bool IsCanonicalWorkerId(string? value) =>
    value is not null && WorkerIdPattern().IsMatch(value);

[GeneratedRegex("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", RegexOptions.CultureInvariant)]
private static partial Regex WorkerIdPattern();
```

If retaining `TryNormalizeWorkerId` avoids broad churn, it must not normalize anything; it may return the exact original only when the same regex passes.

- [ ] **Step 3: Keep Domain independent but semantically identical**

Do not add Domain -> Contracts. Implement the same invariant in a Domain-local helper or a small Domain value-rule helper reused by `VisionJob` and `ProcessingRun`.

The Domain must store the exact already-canonical string; no trimming or normalization.

- [ ] **Step 4: Update Python WorkerId validation**

Use a full-match regex equivalent to the exact syntax above. Retain `StrictStr` semantics.

- [ ] **Step 5: Update every worker schema containing `workerId`**

Replace the current whitespace-based pattern in:

```text
vision-job-lease-request-v2.schema.json
vision-job-lease-v2.schema.json
vision-job-heartbeat-v2.schema.json
vision-job-fail-v2.schema.json
worker-health-v2.schema.json
```

with:

```json
"pattern": "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
```

The `minLength`/`maxLength` fields may remain for readability, even though the regex already bounds length.

- [ ] **Step 6: Extend shared invalid vectors**

Add worker-request vectors for at least internal whitespace, slash, colon, newline/control character, invalid leading punctuation, and non-ASCII worker ID.

Where a corresponding platform-response contract carries WorkerId, add at least one platform-response invalid WorkerId vector too.

- [ ] **Step 7: Run all WorkerId gates**

```bash
dotnet test tests/Mavi.Domain.Tests/Mavi.Domain.Tests.csproj --filter ProcessingOrchestrationStateTests
dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj --filter WorkerContractV2Tests
cd src/vision && python -m pytest -q && cd ../..
python tools/verify_repo.py
```

- [ ] **Step 8: Commit**

```bash
git add src/platform/Mavi.Contracts/Worker/WorkerContractRules.cs src/platform/Mavi.Domain/Processing src/vision/mavi_vision/common/control_plane.py contracts/schemas contracts/test-vectors/control-plane-v2-invalid.json tests/Mavi.Domain.Tests tests/Mavi.IntegrationTests/WorkerContractV2Tests.cs src/vision/tests/test_control_plane_contracts.py
git commit -m "fix: canonicalize worker identity syntax"
```

---

### Task 4: Clarify the Global Strict API JSON Policy

**Files:**
- Modify: `src/platform/Mavi.Api/Program.cs`
- Test: existing integration suite; add a targeted test only if an existing non-worker API depends on numeric-string coercion.

**Interfaces:**
- `JsonNumberHandling.Strict` remains a platform-wide Minimal API JSON policy.
- Numeric JSON properties are numbers, never quoted numeric strings.

- [ ] **Step 1: Change the misleading comment**

Replace:

```csharp
// Worker boundary serialization
```

with:

```csharp
// Canonical API JSON policy: numeric properties must be JSON numbers, not numeric strings.
```

- [ ] **Step 2: Run the full .NET suite to prove no current API compatibility regression**

```bash
dotnet test MAVI.sln
```

If any unrelated endpoint legitimately requires quoted-number compatibility, do not weaken the global policy automatically. Stop and report that concrete compatibility conflict for design review.

- [ ] **Step 3: Commit**

```bash
git add src/platform/Mavi.Api/Program.cs
git commit -m "docs: clarify canonical API JSON number policy"
```

---

### Task 5: Add a Reproducible GitHub Quality Gate

**Files:**
- Create: `.github/workflows/quality-gate.yml`
- Modify: `tools/verify_repo.py` only if CI reveals a genuine path/environment assumption
- Do not modify application runtime architecture to satisfy CI.

**Interfaces:**
- One required workflow named `MAVI Quality Gate` runs on pull requests targeting `feature/visual-intelligence-memory` and on pushes to that branch.
- CI uses the declared Python 3.13 baseline, .NET 10, Node 22, PostgreSQL 18 with pgvector, and FFmpeg.
- Integration tests receive only a dedicated `mavi_test` connection string.

- [ ] **Step 1: Create the workflow skeleton**

Create `.github/workflows/quality-gate.yml` with:

```yaml
name: MAVI Quality Gate

on:
  pull_request:
    branches:
      - feature/visual-intelligence-memory
  push:
    branches:
      - feature/visual-intelligence-memory

permissions:
  contents: read

concurrency:
  group: mavi-quality-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  quality:
    runs-on: ubuntu-latest
    timeout-minutes: 30

    services:
      postgres:
        image: pgvector/pgvector:pg18
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: mavi_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd="pg_isready -U postgres -d mavi_test"
          --health-interval=10s
          --health-timeout=5s
          --health-retries=10

    env:
      MAVI_TEST_DB_CONNECTION: Host=localhost;Port=5432;Database=mavi_test;Username=postgres;Password=postgres

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-dotnet@v4
        with:
          dotnet-version: '10.0.x'

      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
          cache: pip
          cache-dependency-path: src/vision/pyproject.toml

      - uses: actions/setup-node@v4
        with:
          node-version: '22'
          cache: npm
          cache-dependency-path: src/web/mavi-web/package-lock.json

      - name: Install FFmpeg
        run: sudo apt-get update && sudo apt-get install -y ffmpeg

      - name: Install Python verification dependencies
        run: |
          python -m pip install --upgrade pip
          python -m pip install -e './src/vision[dev]' jsonschema

      - name: Verify toolchain
        run: |
          dotnet --info
          python --version
          node --version
          npm --version
          ffmpeg -version | head -n 1
          psql --version
          pg_isready -h localhost -p 5432 -U postgres -d mavi_test

      - name: Build .NET
        run: dotnet build MAVI.sln --configuration Release

      - name: Test .NET
        run: dotnet test MAVI.sln --configuration Release --no-build

      - name: Verify repository
        run: python tools/verify_repo.py

      - name: Test Python contracts
        working-directory: src/vision
        run: python -m pytest -q

      - name: Install frontend dependencies
        working-directory: src/web/mavi-web
        run: npm ci

      - name: Test frontend
        working-directory: src/web/mavi-web
        run: npm test

      - name: Typecheck frontend
        working-directory: src/web/mavi-web
        run: npm run typecheck

      - name: Build frontend
        working-directory: src/web/mavi-web
        run: npm run build
```

If the exact `pgvector/pgvector:pg18` image tag is unavailable in GitHub Actions, use the closest PostgreSQL-18 pgvector image that actually runs and document the tested tag. Do not fall back to vanilla PostgreSQL because migrations require the `vector` extension.

- [ ] **Step 2: Ensure the workflow is self-contained**

The workflow must not require repository secrets. The PostgreSQL password above is ephemeral CI-only state. No application production credential may be introduced.

- [ ] **Step 3: Ensure `verify_repo.py` works in a normal checkout**

`verify_repo.py` uses `git ls-files`; GitHub Actions checkout provides the needed repository metadata. Do not change this unless CI proves otherwise.

- [ ] **Step 4: Validate workflow syntax before commit**

If a YAML linter is available locally, run it. Otherwise inspect indentation carefully and rely on the first PR workflow execution as the authoritative GitHub parser.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/quality-gate.yml
git commit -m "ci: add MAVI quality gate"
```

---

### Task 6: Final Cross-Language Canonicalization Gate

**Files:**
- Modify: `contracts/test-vectors/control-plane-v2-invalid.json`
- Modify: `src/vision/tests/test_control_plane_contracts.py`
- Modify: `tests/Mavi.IntegrationTests/WorkerContractV2Tests.cs`
- Modify: `tools/verify_repo.py` only if needed for clearer vector reporting

**Interfaces:**
- Every shared invalid vector must be rejected by JSON Schema.
- Python must reject every vector through raw JSON parsing.
- Every `worker-request` vector must be rejected by the real .NET HTTP endpoint with 4xx, never 5xx.

- [ ] **Step 1: Confirm the vector catalogue now covers the three final canonicalization classes**

The catalogue must include at least:

```text
snake_case property aliases
noncanonical +00:00 timestamp syntax
unsafe WorkerId characters/control whitespace
```

Retain all Task 7A.1/7A.2 invalid vectors.

- [ ] **Step 2: Run schema verification**

```bash
python tools/verify_repo.py
```

Expected: every canonical example passes and every invalid vector fails its named schema.

- [ ] **Step 3: Run Python raw-wire vector gate**

```bash
cd src/vision
python -m pytest -q
```

Expected: every vector fails `model_validate_json(...)` for its corresponding model.

- [ ] **Step 4: Run real HTTP worker-request vector gate**

```bash
dotnet test tests/Mavi.IntegrationTests/Mavi.IntegrationTests.csproj --filter WorkerContractV2Tests
```

Expected: every `direction == worker-request` vector produces a controlled 4xx and never 5xx.

- [ ] **Step 5: Commit any final vector/test-only adjustments**

```bash
git add contracts/test-vectors/control-plane-v2-invalid.json src/vision/tests/test_control_plane_contracts.py tests/Mavi.IntegrationTests/WorkerContractV2Tests.cs tools/verify_repo.py
git commit -m "test: freeze canonical worker contract vectors"
```

---

### Task 7: Full Verification, PR Review Gate, and Freeze Decision

**Files:**
- No production code expected unless verification finds a real defect.
- Update documentation only to record the final closure if required.

**Interfaces:**
- This task produces the formal go/no-go evidence for Task 8.

- [ ] **Step 1: Run the full local verification suite**

```bash
source /etc/profile.d/mavi-codex.sh || true
pg_ctlcluster 18 main start >/dev/null 2>&1 || true
for i in $(seq 1 30); do pg_isready -h localhost -p 5432 >/dev/null 2>&1 && break; sleep 1; done
pg_isready -h localhost -p 5432

dotnet build MAVI.sln
dotnet test MAVI.sln
python tools/verify_repo.py
cd src/vision && python -m pytest -q && cd ../..
cd src/web/mavi-web && npm ci && npm test && npm run typecheck && npm run build && cd ../../..
git diff --check
```

Record actual test counts; do not assume 176 .NET / 19 Python / 9 frontend.

- [ ] **Step 2: Static-scan canonicalization and Task-8 scope**

Search for:

```text
populate_by_name
validate_by_name
schema_version
worker_id
+00:00
workerId.Trim
mediaUri
media_uri
schemaVersion "1.0"
LeaseToken
lease_token
Thread.Sleep
Task.Delay
DateTime.UtcNow
DateTimeOffset.UtcNow
Python HTTP client/polling code
PyAV
RTMDet
ByteTrack
```

Explain every intentional occurrence. Do not treat internal Python snake_case attributes as a defect; the defect is acceptance of snake_case **wire JSON**.

- [ ] **Step 3: Open the implementation PR and do not merge it**

The PR body must explicitly state:

```text
Task 7A.3 final worker-boundary freeze gate.
Do not merge until:
1. MAVI Quality Gate is green.
2. GitHub Codex review has completed.
3. Every P1/P2 review finding is resolved.
```

- [ ] **Step 4: Observe the GitHub Actions run**

The new `MAVI Quality Gate` must execute on the PR head. If it fails:

```text
inspect exact failing job/step
→ reproduce locally when possible
→ fix root cause
→ rerun focused verification
→ rerun full local suite
→ push new commit
→ wait for green CI
```

Do not bypass, disable, or weaken a check simply to obtain green status.

- [ ] **Step 5: Wait for GitHub Codex review**

For each P1 or P2 finding:

```text
reproduce
→ establish root cause
→ fix with TDD
→ focused tests
→ full suite
→ push
→ wait for review/checks again
```

No unresolved P1/P2 may remain.

- [ ] **Step 6: Report READY TO MERGE, but do not merge unless explicitly instructed**

Only when:

```text
local full suite = green
MAVI Quality Gate = green
GitHub Codex review = complete
unresolved P1/P2 = 0
```

may the final report state:

```text
TASK 7A.3 COMPLETE
TASK 7/7A WORKER CONTROL PLANE READY TO FREEZE
TASK 8 NOT STARTED
READY TO MERGE
```

If any gate is still pending, state the exact pending gate and do not claim readiness.

---

## Final Acceptance Matrix

Task 7A.3 is complete only when all of the following are proven:

```text
PYTHON ALIAS CANONICALIZATION
✓ camelCase worker JSON accepted
✓ snake_case schema_version rejected
✓ snake_case worker_id rejected
✓ snake_case failure_code rejected
✓ internal Python attributes may remain snake_case
✓ canonical serialization emits aliases

UTC WIRE CANONICALIZATION
✓ ...Z accepted
✓ ...+00:00 rejected
✓ non-zero offset rejected
✓ lowercase/noncanonical suffix rejected if tested
✓ .NET writer emits Z
✓ Python wire validation requires Z
✓ JSON Schema already requires Z

WORKER IDENTITY
✓ exact syntax ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$
✓ same rule in .NET Contracts
✓ same rule in Domain
✓ same rule in JSON Schemas
✓ same rule in Python
✓ internal whitespace/control characters rejected
✓ slash/colon/backslash rejected
✓ leading punctuation rejected
✓ non-ASCII rejected
✓ ordinal case-sensitive semantics retained

GLOBAL API JSON POLICY
✓ JsonNumberHandling.Strict retained
✓ comment/documentation identifies it as platform-wide API policy
✓ full .NET suite proves no current API regression

QUALITY GATE
✓ .github/workflows/quality-gate.yml exists
✓ runs on PRs to feature/visual-intelligence-memory
✓ .NET 10 build/test
✓ PostgreSQL 18 + pgvector integration/migrations
✓ Python 3.13 install/test
✓ repository verifier
✓ Node 22 frontend test/typecheck/build
✓ no production secret required
✓ PR workflow run is green

SECURITY/LEASE REGRESSION
✓ stale token rejection still green
✓ hash-only capability persistence still green
✓ no raw token in processing status/diagnostics
✓ attempt exhaustion still revokes capability
✓ Complete still requires capability match
✓ post-lock time tests still green
✓ migration reclaim test still green

PROCESS
✓ PR left open until CI completion
✓ Codex review completed before merge
✓ zero unresolved P1/P2
✓ Task 8 not started
```

## Expected Commit Structure

Prefer focused commits equivalent to:

```text
fix: require canonical worker JSON aliases
fix: require canonical UTC worker timestamps
fix: canonicalize worker identity syntax
docs: clarify canonical API JSON number policy
ci: add MAVI quality gate
test: freeze canonical worker contract vectors
```

A different split is acceptable if TDD yields a cleaner review boundary, but avoid one monolithic commit.

## Final Report Required From Executor

Return:

1. Baseline environment and test counts.
2. Python alias-only wire behavior.
3. UTC lexical canonicalization results.
4. WorkerId canonical alphabet and cross-layer parity.
5. Global JSON number policy confirmation.
6. Shared invalid-vector count and results.
7. GitHub Actions workflow definition and actual run result.
8. Full .NET/Python/frontend/verifier results.
9. Security/lease regression status.
10. Commits with SHA + message.
11. GitHub Codex review status and findings.
12. Unresolved P1/P2 count.
13. Deviations/risks.
14. Explicit scope confirmation:

```text
TASK 7A.3 COMPLETE
TASK 8 NOT STARTED
```

Only add:

```text
READY TO MERGE
```

when the GitHub quality gate is green and the GitHub Codex review is complete with zero unresolved P1/P2 findings.
