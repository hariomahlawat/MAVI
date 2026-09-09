# Task 8 — Dummy Python Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first operational Python worker loop against the real MAVI Task-7/7A worker-control-plane API: lease work, resolve leased media safely, heartbeat it, and terminate the dummy attempt through the existing controlled-failure path without AI inference or PostgreSQL access.

**Architecture:** ASP.NET Core remains the processing authority. Python is a stateless worker that consumes the frozen v2 Pydantic control-plane models, uses `httpx.AsyncClient` for HTTP, resolves logical storage keys below a configured media root, and keeps lifecycle orchestration separate from transport and storage. Task 8 does not fabricate a completion endpoint because the current API exposes lease, heartbeat and fail only; successful result submission/completion remains for the later result-ingest task.

**Tech Stack:** Python 3.13, Pydantic 2.11+, pydantic-settings 2.x, httpx 0.28.x, pytest 8.4+, existing ASP.NET Core worker API v2.

**Spec:** `docs/superpowers/specs/2026-09-08-visual-intelligence-memory-design.md`; baseline plan `docs/superpowers/plans/2026-09-08-visual-intelligence-memory.md`; canonical boundary `docs/superpowers/plans/2026-09-09-task-7a3-contract-canonicalization-quality-gate.md`.

## Global Constraints

- Base implementation on `feature/visual-intelligence-memory` after merge commit `2cb6098a525b9f485527cc5ddde3fece0df17d63` and green post-merge MAVI Quality Gate #26.
- Retain Python `>=3.13`; do not restore the superseded 3.12-only draft baseline.
- Worker schema remains exactly `2.0` and canonical camelCase. Incoming HTTP JSON must be parsed with each Pydantic model's `model_validate_json` method; outgoing HTTP JSON must use alias serialization.
- Reuse `WorkerId`, `LeaseToken`, `StorageKey`, `FailureCode`, canonical timestamp types, and request/response models from `mavi_vision.common.control_plane`. Do not duplicate or weaken them in `contracts.py`.
- Canonical timestamps remain uppercase `T`, uppercase `Z`, mandatory seconds, and at most six fractional digits.
- Python never writes operational PostgreSQL records and never receives database credentials.
- HTTP carries logical storage keys only. Local resolution must prevent absolute paths, traversal, backslashes, drive syntax, empty segments and symlink escape from `MAVI_MEDIA_ROOT`.
- Do not disable TLS verification. Permit an optional local CA bundle for internal/air-gapped PKI.
- Lease tokens must never appear in logs, exception strings or generic failure messages.
- Do not add AI inference, PyAV, RTMDet, ByteTrack, MessagePack result payloads, concurrency, PostgreSQL clients or an invented completion endpoint in Task 8.
- Use TDD for every behavioral change and end each implementation task with focused tests and a focused commit.

## File Structure

```text
src/vision/
  pyproject.toml
  mavi_vision/common/settings.py
  mavi_vision/storage/__init__.py
  mavi_vision/storage/local_media_store.py
  mavi_vision/worker/client.py
  mavi_vision/worker/runner.py
  mavi_vision/worker/main.py
  tests/test_worker_settings.py
  tests/test_storage.py
  tests/test_worker_client.py
  tests/test_worker_runner.py
```

`mavi_vision.common.control_plane` is the frozen worker-wire boundary. `mavi_vision.common.contracts` remains reserved for analytical result-domain types.

---

### Task 1: Runtime Dependencies and Typed Settings

**Files:**
- Modify: `src/vision/pyproject.toml`
- Create: `src/vision/mavi_vision/common/settings.py`
- Create: `src/vision/tests/test_worker_settings.py`

**Interfaces:**
- Consumes: `WorkerId` from `mavi_vision.common.control_plane`.
- Produces: `WorkerSettings` with `api_base_url`, `worker_id`, `media_root`, `poll_interval_seconds`, `request_timeout_seconds`, `ca_bundle`.

- [ ] **Step 1: Write failing settings tests**

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from mavi_vision.common.settings import WorkerSettings


def seed_required(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MAVI_API_BASE_URL", "https://mavi-api.local:62152/")
    monkeypatch.setenv("MAVI_WORKER_ID", "dev-worker-01")
    monkeypatch.setenv("MAVI_MEDIA_ROOT", str(tmp_path))


def test_settings_load_and_normalize(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seed_required(monkeypatch, tmp_path)
    settings = WorkerSettings()
    assert settings.api_base_url == "https://mavi-api.local:62152"
    assert settings.worker_id == "dev-worker-01"
    assert settings.media_root == tmp_path
    assert settings.poll_interval_seconds == 2.0


def test_settings_reject_unsafe_worker_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seed_required(monkeypatch, tmp_path)
    monkeypatch.setenv("MAVI_WORKER_ID", "bad/worker")
    with pytest.raises(ValidationError):
        WorkerSettings()
```

- [ ] **Step 2: Verify RED**

```powershell
cd src/vision
python -m pytest -q tests/test_worker_settings.py
```

Expected: import failure because `settings.py` does not exist.

- [ ] **Step 3: Add only Task-8 dependencies**

```toml
[project]
requires-python = ">=3.13"
dependencies = [
  "httpx>=0.28,<0.29",
  "pydantic>=2.11,<3",
  "pydantic-settings>=2.10,<3"
]
```

- [ ] **Step 4: Implement `WorkerSettings`**

```python
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from mavi_vision.common.control_plane import WorkerId


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MAVI_", extra="ignore")

    api_base_url: str
    worker_id: WorkerId
    media_root: Path
    poll_interval_seconds: float = Field(default=2.0, ge=0.25, le=60.0)
    request_timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)
    ca_bundle: Path | None = None

    @field_validator("api_base_url")
    @classmethod
    def validate_api_base_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        parts = urlsplit(normalized)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("MAVI_API_BASE_URL must be an absolute HTTP(S) URL")
        return normalized
```

- [ ] **Step 5: Verify GREEN and commit**

```powershell
cd src/vision
python -m pytest -q tests/test_worker_settings.py
cd ../..
git add src/vision/pyproject.toml src/vision/mavi_vision/common/settings.py src/vision/tests/test_worker_settings.py
git commit -m "feat: add vision worker settings"
```

---

### Task 2: Root-Confined Local Media Store

**Files:**
- Create: `src/vision/mavi_vision/storage/__init__.py`
- Create: `src/vision/mavi_vision/storage/local_media_store.py`
- Create: `src/vision/tests/test_storage.py`

**Interfaces:**
- Consumes: `StorageKey` from `mavi_vision.common.control_plane`.
- Produces: `MediaStoreError`; `LocalMediaStore.resolve_file(storage_key: str) -> Path`.

- [ ] **Step 1: Write failing storage tests**

```python
from pathlib import Path

import pytest

from mavi_vision.storage.local_media_store import LocalMediaStore, MediaStoreError


def test_resolve_file_maps_logical_key_under_root(tmp_path: Path) -> None:
    target = tmp_path / "videos" / "camera-01" / "clip.mp4"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"video")
    store = LocalMediaStore(tmp_path)
    assert store.resolve_file("videos/camera-01/clip.mp4") == target.resolve()


@pytest.mark.parametrize("key", ["../outside.mp4", "/outside.mp4", "videos\\clip.mp4", "C:/outside.mp4"])
def test_resolve_file_rejects_unsafe_keys(tmp_path: Path, key: str) -> None:
    store = LocalMediaStore(tmp_path)
    with pytest.raises((ValueError, MediaStoreError)):
        store.resolve_file(key)


def test_resolve_file_rejects_missing_or_directory(tmp_path: Path) -> None:
    directory = tmp_path / "videos"
    directory.mkdir()
    store = LocalMediaStore(tmp_path)
    with pytest.raises(MediaStoreError):
        store.resolve_file("videos")
    with pytest.raises(MediaStoreError):
        store.resolve_file("videos/missing.mp4")
```

Add a symlink-escape test on platforms where symlink creation is permitted: a symlink beneath the media root resolving to a file outside the root must raise `MediaStoreError`.

- [ ] **Step 2: Verify RED**

```powershell
cd src/vision
python -m pytest -q tests/test_storage.py
```

- [ ] **Step 3: Implement storage validation and containment**

```python
from pathlib import Path

from pydantic import TypeAdapter

from mavi_vision.common.control_plane import StorageKey


_storage_key_adapter = TypeAdapter(StorageKey)


class MediaStoreError(RuntimeError):
    pass


class LocalMediaStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def resolve_file(self, storage_key: str) -> Path:
        canonical_key = _storage_key_adapter.validate_python(storage_key, strict=True)
        candidate = (self._root / Path(*canonical_key.split("/"))).resolve()
        if not candidate.is_relative_to(self._root):
            raise MediaStoreError("logical storage key escapes configured media root")
        if not candidate.exists() or not candidate.is_file():
            raise MediaStoreError("leased source media is unavailable")
        return candidate
```

- [ ] **Step 4: Verify GREEN and commit**

```powershell
cd src/vision
python -m pytest -q tests/test_storage.py
cd ../..
git add src/vision/mavi_vision/storage src/vision/tests/test_storage.py
git commit -m "feat: add safe worker media storage"
```

---

### Task 3: Canonical Async Worker API Client

**Files:**
- Create: `src/vision/mavi_vision/worker/client.py`
- Create: `src/vision/tests/test_worker_client.py`
- Consume unchanged: `src/vision/mavi_vision/common/control_plane.py`

**Interfaces:**
- Consumes: `VisionJobLeaseRequest`, `VisionJobLease`, `VisionJobHeartbeat`, `VisionJobHeartbeatResponse`, `VisionJobFail`.
- Produces: `WorkerApiClient.lease`, `WorkerApiClient.heartbeat`, `WorkerApiClient.fail`, `WorkerApiError`.

- [ ] **Step 1: Write failing client tests using `httpx.MockTransport`**

Tests must prove all of the following:

```text
POST /api/vision/jobs/lease serializes exactly schemaVersion + workerId
HTTP 204 lease returns None
HTTP 200 lease uses VisionJobLease.model_validate_json
heartbeat route is /api/vision/jobs/{jobId}/heartbeat
heartbeat JSON is canonical camelCase and includes the exact lease token
fail route is /api/vision/jobs/{jobId}/fail
fail JSON is canonical camelCase
snake_case lease responses are rejected
+00:00 or other noncanonical timestamp responses are rejected
WorkerApiError text never contains the lease token or raw request/response bodies
```

Use the existing canonical v2 examples/tests as the lease fixture source rather than inventing a second contract shape.

- [ ] **Step 2: Verify RED**

```powershell
cd src/vision
python -m pytest -q tests/test_worker_client.py
```

- [ ] **Step 3: Implement the client**

Required signatures:

```text
WorkerApiClient(settings: WorkerSettings, http_client: httpx.AsyncClient | None = None)
async lease() -> VisionJobLease | None
async heartbeat(lease: VisionJobLease, progress_percent: float) -> VisionJobHeartbeatResponse
async fail(lease: VisionJobLease, failure_code: str, failure_message: str | None = None) -> None
async aclose() -> None
```

Implementation requirements:

```text
build requests with the frozen Pydantic request models
serialize via model_dump_json(by_alias=True)
send UTF-8 application/json
parse typed responses with model_validate_json
return None only for lease HTTP 204
raise a sanitized WorkerApiError for non-success status
read only a safe RFC-7807 code field from error responses
never include request bodies, response dumps or lease tokens in exception text
use configured request timeout
use MAVI_CA_BUNDLE as the trust source when supplied; otherwise retain normal TLS verification
allow AsyncClient injection so tests use MockTransport without a real server
```

- [ ] **Step 4: Verify GREEN and commit**

```powershell
cd src/vision
python -m pytest -q tests/test_worker_client.py
cd ../..
git add src/vision/mavi_vision/worker/client.py src/vision/tests/test_worker_client.py
git commit -m "feat: add canonical worker api client"
```

---

### Task 4: Dummy Worker Runner and Entry Point

**Files:**
- Create: `src/vision/mavi_vision/worker/runner.py`
- Create: `src/vision/mavi_vision/worker/main.py`
- Create: `src/vision/tests/test_worker_runner.py`

**Interfaces:**
- Consumes: `WorkerApiClient`, `LocalMediaStore`, `VisionJobLease`.
- Produces: `WorkerRunner.run_once() -> bool`, `WorkerRunner.run_forever() -> None`, `python -m mavi_vision.worker.main`.

- [ ] **Step 1: Write failing runner tests**

Cover four exact behaviors:

```text
no lease -> run_once returns False and sends no heartbeat/fail
valid lease + valid local media -> heartbeat 5.0, fail with dummy_processing_not_implemented, return True
missing/unsafe local media after lease -> fail once with source_media_unavailable and a generic bounded message
unexpected internal error after lease -> fail once with worker_unhandled_error and no traceback/path/token in the failure message
```

Use fakes for the API client and a temporary filesystem for `LocalMediaStore`; do not start a real HTTP server.

- [ ] **Step 2: Verify RED**

```powershell
cd src/vision
python -m pytest -q tests/test_worker_runner.py
```

- [ ] **Step 3: Implement `WorkerRunner`**

`run_once` owns lifecycle orchestration only:

```text
lease
if none: return False
resolve sourceStorageKey under media root
heartbeat 5.0
fail deliberately with dummy_processing_not_implemented and a fixed non-secret message
return True
```

On `MediaStoreError`, fail with `source_media_unavailable`. On any other exception after a lease, make one best-effort fail call with `worker_unhandled_error`. Do not send raw exception text. Do not add a success completion call.

`run_forever` performs one lease at a time. Sleep `poll_interval_seconds` when no work is available or after a recoverable transport error. Respect cancellation and do not spawn parallel workers in Task 8.

- [ ] **Step 4: Implement `main.py`**

The entry point must load `WorkerSettings`, construct `LocalMediaStore`, `WorkerApiClient` and `WorkerRunner`, call `asyncio.run`, close the client in `finally`, and exit cleanly on cancellation/keyboard interruption. Logging may include worker ID and job ID but never lease tokens.

- [ ] **Step 5: Verify GREEN and commit**

```powershell
cd src/vision
python -m pytest -q tests/test_worker_runner.py
cd ../..
git add src/vision/mavi_vision/worker/runner.py src/vision/mavi_vision/worker/main.py src/vision/tests/test_worker_runner.py
git commit -m "feat: add dummy vision worker loop"
```

---

### Task 5: Full Verification and PR Gate

**Files:**
- Modify existing contract tests only if a newly exposed defect requires a stricter regression; do not relax them.
- Do not weaken `.github/workflows/quality-gate.yml`.

- [ ] **Step 1: Run the complete Python suite**

```powershell
cd src/vision
python -m pytest -q
```

Expected: all prior Task-7/7A canonicalization tests plus new Task-8 tests pass.

- [ ] **Step 2: Run repository verification**

```powershell
cd ../..
python tools/verify_repo.py
```

Expected: repository verification PASSED.

- [ ] **Step 3: Guard the frozen server boundary**

```powershell
dotnet build MAVI.sln --configuration Release
dotnet test MAVI.sln --configuration Release --no-build
```

Expected: all .NET projects build and all .NET tests pass.

- [ ] **Step 4: Re-run Python tests after full verification**

```powershell
cd src/vision
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 5: Scope audit before PR**

The diff must contain no PostgreSQL client or credentials, ML/runtime inference dependencies, direct filesystem path in HTTP JSON, snake_case wire aliases, timestamp relaxation, completion endpoint, TLS-verification bypass, lease-token logging, or unrelated refactoring.

- [ ] **Step 6: Push the execution branch and open a PR**

Target `feature/visual-intelligence-memory`. Require the MAVI Quality Gate and final Codex review before merge.

## Definition of Done

- Python 3.13 remains the worker and CI baseline.
- Worker settings are local `MAVI_*` configuration only.
- Logical storage keys cannot escape `MAVI_MEDIA_ROOT` through traversal, absolute syntax or resolvable symlink escape.
- Worker HTTP uses only frozen schema `2.0` canonical camelCase models.
- Lease 204, canonical lease 200, heartbeat, fail, malformed response and safe-error behavior are tested.
- The dummy worker leases, validates local media, heartbeats, and deliberately closes the job through the existing fail path without AI.
- No successful-completion endpoint is invented before result ingestion exists.
- Lease tokens are absent from log/error text.
- Python tests, repository verification, .NET build and .NET tests pass.
- The Task 8 PR targets `feature/visual-intelligence-memory`, passes the MAVI Quality Gate, and receives a final Codex review before merge.
