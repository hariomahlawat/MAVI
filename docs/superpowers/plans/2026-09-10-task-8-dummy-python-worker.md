# Task 8 — Dummy Python Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first operational Python worker loop that talks to the real MAVI Task-7/7A worker-control-plane API, safely resolves leased media from local storage, heartbeats active work, and reports controlled failures without performing AI processing or writing PostgreSQL.

**Architecture:** Keep ASP.NET Core as the processing authority and Python as a stateless worker. The worker uses the frozen v2 Pydantic models in `mavi_vision.common.control_plane` as its only wire boundary, an async `httpx` client for lease/heartbeat/fail calls, a root-confined local media store for logical storage keys, and a small runner that is dependency-injected for testing. Task 8 deliberately does **not** invent a completion endpoint: the current API exposes lease, heartbeat and fail only; successful analytical result submission/completion remains for the later result-ingest task.

**Tech Stack:** Python 3.13, Pydantic 2.11+, pydantic-settings 2.x, httpx 0.28.x, pytest 8.4+, existing ASP.NET Core worker API v2.

**Spec:** `docs/superpowers/specs/2026-09-08-visual-intelligence-memory-design.md`; baseline phase plan `docs/superpowers/plans/2026-09-08-visual-intelligence-memory.md`; canonical worker boundary frozen by `docs/superpowers/plans/2026-09-09-task-7a3-contract-canonicalization-quality-gate.md`.

## Global Constraints

- Implement from `feature/visual-intelligence-memory` after merge commit `2cb6098a525b9f485527cc5ddde3fece0df17d63` and the green post-merge MAVI Quality Gate #26.
- Retain the repository Python baseline at `>=3.13`; do **not** revert the current Python 3.13 quality gate to the older draft plan's 3.12-only constraint.
- Worker wire schema remains exactly `2.0` and canonical camelCase. Incoming worker JSON must be parsed with `model_validate_json(...)`; outgoing payloads must serialize by alias.
- Do not duplicate or weaken `WorkerId`, lease-token, storage-key, timestamp or failure-code validation already frozen in `mavi_vision.common.control_plane`.
- Canonical worker timestamps remain uppercase `Z`, uppercase `T`, mandatory seconds, and at most six fractional digits.
- Python never writes operational PostgreSQL records and never receives database credentials.
- The API passes logical storage keys only. The worker maps them under `MAVI_MEDIA_ROOT`; absolute paths, traversal, backslashes, drive syntax, empty segments and symlink escapes must not escape that root.
- Do not disable TLS verification as a convenience. Support an optional local CA bundle for air-gapped/internal PKI; otherwise use the platform trust store.
- Do not log or surface lease tokens in exception text. Failure messages sent to the API must be bounded and non-secret.
- No AI inference, PyAV, RTMDet, ByteTrack, MessagePack result payloads or PostgreSQL access in this task.
- Tests precede production changes. Every implementation task ends with focused tests and a focused commit.

---

## File Structure Map

```text
src/vision/
  pyproject.toml                         # add HTTP/settings runtime dependencies; retain Python 3.13
  mavi_vision/common/control_plane.py   # consume frozen v2 models; change only if a test proves a contract defect
  mavi_vision/common/settings.py        # typed MAVI_* worker configuration
  mavi_vision/storage/__init__.py       # package marker
  mavi_vision/storage/local_media_store.py # safe logical-key -> local-file resolution
  mavi_vision/worker/client.py          # async Task-7 API client
  mavi_vision/worker/runner.py          # lease/heartbeat/failure orchestration
  mavi_vision/worker/main.py            # process entry point / polling loop
  tests/test_worker_settings.py
  tests/test_storage.py
  tests/test_worker_client.py
  tests/test_worker_runner.py
```

`mavi_vision.common.contracts` remains the analytical-result contract area and must not become a second copy of worker-control-plane DTOs.

---

### Task 1: Add Runtime Dependencies and Typed Worker Settings

**Files:**
- Modify: `src/vision/pyproject.toml`
- Create: `src/vision/mavi_vision/common/settings.py`
- Create: `src/vision/tests/test_worker_settings.py`

**Interfaces:**
- Consumes: public `WorkerId` validator from `mavi_vision.common.control_plane`.
- Produces: `WorkerSettings` with `api_base_url`, `worker_id`, `media_root`, `poll_interval_seconds`, `request_timeout_seconds`, and optional `ca_bundle`.

- [ ] **Step 1: Write failing settings tests**

Create `src/vision/tests/test_worker_settings.py` with tests equivalent to:

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from mavi_vision.common.settings import WorkerSettings


def test_settings_load_canonical_worker_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MAVI_API_BASE_URL", "https://mavi-api.local:62152")
    monkeypatch.setenv("MAVI_WORKER_ID", "dev-worker-01")
    monkeypatch.setenv("MAVI_MEDIA_ROOT", str(tmp_path))

    settings = WorkerSettings()

    assert settings.api_base_url == "https://mavi-api.local:62152"
    assert settings.worker_id == "dev-worker-01"
    assert settings.media_root == tmp_path


def test_settings_reject_unsafe_worker_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MAVI_API_BASE_URL", "https://mavi-api.local:62152")
    monkeypatch.setenv("MAVI_WORKER_ID", "bad/worker")
    monkeypatch.setenv("MAVI_MEDIA_ROOT", str(tmp_path))

    with pytest.raises(ValidationError):
        WorkerSettings()
```

- [ ] **Step 2: Run the settings tests and verify RED**

Run:

```powershell
cd src/vision
python -m pytest -q tests/test_worker_settings.py
```

Expected: import failure because `mavi_vision.common.settings` does not exist.

- [ ] **Step 3: Update Python dependencies without downgrading Python**

Change only the runtime dependency block needed by Task 8:

```toml
[project]
requires-python = ">=3.13"
dependencies = [
  "httpx>=0.28,<0.29",
  "pydantic>=2.11,<3",
  "pydantic-settings>=2.10,<3"
]
```

Do not add PyAV, ML frameworks or MessagePack in Task 8.

- [ ] **Step 4: Implement `WorkerSettings`**

Use `pydantic_settings.BaseSettings` and `SettingsConfigDict(env_prefix="MAVI_", extra="ignore")`. Required behavior:

```python
class WorkerSettings(BaseSettings):
    api_base_url: str
    worker_id: WorkerId
    media_root: Path
    poll_interval_seconds: float = Field(default=2.0, ge=0.25, le=60.0)
    request_timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)
    ca_bundle: Path | None = None
```

Normalize `api_base_url` by removing one trailing slash after validation. Require `http://` or `https://`; do not introduce an `insecure_skip_verify` setting.

- [ ] **Step 5: Run focused tests**

```powershell
cd src/vision
python -m pytest -q tests/test_worker_settings.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/vision/pyproject.toml src/vision/mavi_vision/common/settings.py src/vision/tests/test_worker_settings.py
git commit -m "feat: add vision worker settings"
```

---

### Task 2: Add Root-Confined Local Media Storage

**Files:**
- Create: `src/vision/mavi_vision/storage/__init__.py`
- Create: `src/vision/mavi_vision/storage/local_media_store.py`
- Create: `src/vision/tests/test_storage.py`

**Interfaces:**
- Consumes: canonical logical storage-key grammar from `StorageKey` in `mavi_vision.common.control_plane`.
- Produces: `LocalMediaStore(root: Path)` and `resolve_file(storage_key: str) -> Path`.

- [ ] **Step 1: Write failing containment tests**

Cover all of these cases in `test_storage.py`:

```python
def test_resolve_file_maps_logical_key_under_root(tmp_path: Path) -> None: ...
def test_resolve_file_rejects_parent_traversal(tmp_path: Path) -> None: ...
def test_resolve_file_rejects_absolute_or_backslash_key(tmp_path: Path) -> None: ...
def test_resolve_file_rejects_missing_file(tmp_path: Path) -> None: ...
def test_resolve_file_rejects_directory(tmp_path: Path) -> None: ...
```

The positive test creates `tmp_path / "videos" / "camera-01" / "clip.mp4"` and resolves `videos/camera-01/clip.mp4`. The traversal tests use `../outside.mp4`, `/outside.mp4`, and `videos\\clip.mp4`.

Where symlink creation is supported, add a test that a symlink inside the media root pointing to a file outside the root is rejected after real-path resolution.

- [ ] **Step 2: Run storage tests and verify RED**

```powershell
cd src/vision
python -m pytest -q tests/test_storage.py
```

Expected: import failure because `LocalMediaStore` does not exist.

- [ ] **Step 3: Implement exact logical-key validation and containment**

Use `TypeAdapter(StorageKey).validate_python(storage_key, strict=True)` before filesystem mapping. Resolve the configured root and candidate with `Path.resolve()`, then require `candidate.is_relative_to(root)`, `candidate.exists()`, and `candidate.is_file()`.

Use specific worker-local exceptions such as:

```python
class MediaStoreError(RuntimeError):
    pass
```

Exception messages may include the logical storage key but must not disclose unrelated filesystem contents.

- [ ] **Step 4: Run storage tests**

```powershell
cd src/vision
python -m pytest -q tests/test_storage.py
```

Expected: PASS on supported platforms; symlink test may be explicitly skipped only when the OS denies symlink creation.

- [ ] **Step 5: Commit**

```powershell
git add src/vision/mavi_vision/storage src/vision/tests/test_storage.py
git commit -m "feat: add safe worker media storage"
```

---

### Task 3: Implement the Canonical Async Worker API Client

**Files:**
- Create: `src/vision/mavi_vision/worker/client.py`
- Create: `src/vision/tests/test_worker_client.py`
- Read/consume unchanged: `src/vision/mavi_vision/common/control_plane.py`

**Interfaces:**
- Consumes: `VisionJobLeaseRequest`, `VisionJobLease`, `VisionJobHeartbeat`, `VisionJobHeartbeatResponse`, `VisionJobFail`.
- Produces: `WorkerApiClient.lease()`, `heartbeat(...)`, `fail(...)`, and `WorkerApiError`.

- [ ] **Step 1: Write failing lease test with `httpx.MockTransport`**

The test must assert the request is exactly:

```json
{"schemaVersion":"2.0","workerId":"dev-worker-01"}
```

and that HTTP 204 returns `None` while HTTP 200 is parsed through `VisionJobLease.model_validate_json(...)`.

Use a canonical lease fixture with a 43-character Base64Url token, UUIDs, logical `sourceStorageKey`, uppercase-`Z` timestamps and all v2 fields.

- [ ] **Step 2: Add failing heartbeat and fail tests**

Assert routes and canonical payloads:

```text
POST /api/vision/jobs/{jobId}/heartbeat
POST /api/vision/jobs/{jobId}/fail
```

Heartbeat payload:

```json
{"schemaVersion":"2.0","workerId":"dev-worker-01","leaseToken":"<token>","progressPercent":10.0}
```

Failure payload uses a canonical machine code such as `dummy_processing_not_implemented`; the test must confirm the lease token is present only in the request body and never in raised `WorkerApiError` text.

- [ ] **Step 3: Add a failing malformed-response test**

Return a lease response using `worker_id` or a noncanonical timestamp such as `2026-09-10T00:00:00+00:00`. Assert `lease()` rejects it rather than silently accepting aliases or offset timestamps.

- [ ] **Step 4: Run focused tests and verify RED**

```powershell
cd src/vision
python -m pytest -q tests/test_worker_client.py
```

Expected: failure because `WorkerApiClient` does not exist.

- [ ] **Step 5: Implement `WorkerApiClient`**

Implementation rules:

```python
class WorkerApiClient:
    async def lease(self) -> VisionJobLease | None: ...
    async def heartbeat(self, lease: VisionJobLease, progress_percent: float) -> VisionJobHeartbeatResponse: ...
    async def fail(self, lease: VisionJobLease, failure_code: str, failure_message: str | None = None) -> None: ...
```

Serialize requests with the frozen Pydantic models and `model_dump_json(by_alias=True)`, send them as UTF-8 `application/json`, and parse typed responses with `model_validate_json`. Treat 204 lease as no work. For non-success HTTP responses, parse only a safe RFC-7807 `code` when present and raise `WorkerApiError(status_code, code)` without embedding request bodies, lease tokens, or server response dumps.

Create the underlying `httpx.AsyncClient` with the configured timeout. If `MAVI_CA_BUNDLE` is present, pass that CA path as the verification trust source; otherwise retain normal TLS verification. Permit dependency injection of an `AsyncClient` so `MockTransport` tests need no real server.

- [ ] **Step 6: Run focused tests**

```powershell
cd src/vision
python -m pytest -q tests/test_worker_client.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src/vision/mavi_vision/worker/client.py src/vision/tests/test_worker_client.py
git commit -m "feat: add canonical worker api client"
```

---

### Task 4: Implement the Dummy Worker Runner and Polling Entry Point

**Files:**
- Create: `src/vision/mavi_vision/worker/runner.py`
- Create: `src/vision/mavi_vision/worker/main.py`
- Create: `src/vision/tests/test_worker_runner.py`

**Interfaces:**
- Consumes: `WorkerApiClient`, `LocalMediaStore`, `VisionJobLease`.
- Produces: `WorkerRunner.run_once() -> bool`, `WorkerRunner.run_forever() -> None`, and an executable `python -m mavi_vision.worker.main` entry point.

- [ ] **Step 1: Write a failing no-work test**

Inject a fake client whose `lease()` returns `None`. Assert `run_once()` returns `False` and never calls heartbeat or fail.

- [ ] **Step 2: Write a failing leased-job lifecycle test**

Inject a valid lease and real temporary media file. Assert the runner:

```text
1. leases the job
2. resolves sourceStorageKey under MAVI_MEDIA_ROOT
3. sends a heartbeat after local source validation
4. reports a controlled failure with failureCode=dummy_processing_not_implemented
5. returns True to indicate that one lease was handled
```

Do not claim successful completion: Task 7/7A currently exposes no worker completion/result endpoint.

- [ ] **Step 3: Write a failing local-media-error test**

When the leased source file is missing or escapes the media root, assert the runner calls `fail()` using `source_media_unavailable` and a bounded generic message that does not disclose the lease token.

- [ ] **Step 4: Write a failing unexpected-exception test**

Force an internal processing exception after a lease. Assert the runner attempts a single `fail()` with `worker_unhandled_error`. The failure message must be generic; do not send raw traceback text, environment variables, absolute paths or lease tokens to the API.

- [ ] **Step 5: Run runner tests and verify RED**

```powershell
cd src/vision
python -m pytest -q tests/test_worker_runner.py
```

Expected: failure because `WorkerRunner` does not exist.

- [ ] **Step 6: Implement `WorkerRunner`**

Use a small dependency-injected class. `run_once()` should own only lifecycle orchestration; it must not contain HTTP serialization or path-validation logic. After a valid lease/source resolution, send a low progress heartbeat (for example `5.0`) and then intentionally report `dummy_processing_not_implemented`. This establishes the real control-plane path without leaving a leased job hanging until timeout.

`run_forever()` loops until cancellation, sleeping `poll_interval_seconds` only when no lease is available or after a recoverable transport error. Do not create parallel lease workers in Task 8.

- [ ] **Step 7: Implement `main.py`**

`main.py` must:

```text
load WorkerSettings
construct LocalMediaStore
construct WorkerApiClient
construct WorkerRunner
run asyncio.run(runner.run_forever())
close AsyncClient on shutdown
return cleanly on Ctrl+C / cancellation
```

Use standard `logging` with worker ID and job ID where useful, but never log lease tokens.

- [ ] **Step 8: Run runner tests**

```powershell
cd src/vision
python -m pytest -q tests/test_worker_runner.py
```

Expected: PASS.

- [ ] **Step 9: Commit**

```powershell
git add src/vision/mavi_vision/worker/runner.py src/vision/mavi_vision/worker/main.py src/vision/tests/test_worker_runner.py
git commit -m "feat: add dummy vision worker loop"
```

---

### Task 5: Cross-Contract Regression and Repository Verification

**Files:**
- Modify only if required by a failing test: `src/vision/tests/test_control_plane_contracts.py`
- Modify only if required by a failing test: `src/vision/tests/test_contract_schema_canonicalization.py`
- Do not weaken `.github/workflows/quality-gate.yml`.

**Interfaces:**
- Consumes: all Task 8 components and frozen Task-7/7A contracts.
- Produces: merge-ready Task 8 branch with no contract regression.

- [ ] **Step 1: Run the complete Python suite**

```powershell
cd src/vision
python -m pytest -q
```

Expected: all existing canonical contract tests and all new Task 8 tests pass.

- [ ] **Step 2: Run repository verification**

From repository root:

```powershell
python tools/verify_repo.py
```

Expected: repository verification PASSED.

- [ ] **Step 3: Run .NET build and tests to guard the frozen server boundary**

```powershell
dotnet build MAVI.sln --configuration Release
dotnet test MAVI.sln --configuration Release --no-build
```

Expected: all projects build and all .NET tests pass.

- [ ] **Step 4: Re-run Python tests after the .NET verification**

```powershell
cd src/vision
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 5: Review the Task 8 diff for forbidden scope**

The diff must contain no PostgreSQL client, no database credentials, no ML dependencies, no direct filesystem path in HTTP JSON, no snake_case wire aliases, no timestamp grammar relaxation, no invented `/complete` endpoint, and no TLS-verification bypass.

- [ ] **Step 6: Final commit if verification required any test-only adjustment**

```powershell
git add src/vision
git commit -m "test: verify dummy worker control plane"
```

Skip this commit only when the working tree is already clean.

---

## Definition of Done

Task 8 is complete only when all of the following are true:

- Python 3.13 remains the worker/CI baseline.
- Worker settings load entirely from local `MAVI_*` configuration with no cloud dependency.
- A logical media storage key cannot escape `MAVI_MEDIA_ROOT`, including through path traversal or resolvable symlink escape.
- `WorkerApiClient` uses the frozen schema `2.0` canonical camelCase models for every request and response.
- Lease 204, canonical lease 200, heartbeat, fail, malformed response and safe-error behavior are covered by tests.
- The dummy runner can lease a real job contract, validate local media, heartbeat it, and deliberately close the lease through the existing fail path without AI.
- No successful-completion endpoint is fabricated before result-ingest architecture provides one.
- No lease token is exposed in log/error text.
- `python -m pytest -q`, `python tools/verify_repo.py`, `dotnet build`, and `dotnet test` pass.
- The resulting PR targets `feature/visual-intelligence-memory` and receives the MAVI Quality Gate plus final Codex review before merge.
