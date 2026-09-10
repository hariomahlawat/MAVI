# Task 9 — Lease Ownership and Attempt Isolation Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Task 9's callback-by-convention lease safety with a structural ownership model that remains safe across event-loop stalls, lease expiry, retry overlap, artifact finalization, and concurrent processing failures.

**Architecture:** Introduce a thread-safe `LeaseGuard` shared by the asyncio runner and processing thread, make the server-returned lease deadline directly visible to processing code, isolate filesystem artifacts by lease attempt, separate pure track preparation from side-effect publication, and make artifact publication pass through one ownership-aware gateway. A stale attempt may continue consuming bounded CPU until cooperative cancellation is observed, but it must never be able to overwrite or delete a newer attempt's artifacts.

**Tech Stack:** Python 3.13+, asyncio/threading, PyAV, Pillow, MessagePack, existing POSIX dirfd/no-follow staging primitives, pytest, hosted MAVI Quality Gate.

**Spec:** `docs/superpowers/specs/2026-09-08-visual-intelligence-memory-design.md`

## Global Constraints

- Work only on `feature/task-9-deterministic-track-pipeline`; PR target remains `feature/visual-intelligence-memory`.
- Preserve the frozen Task-7/7A v2 worker HTTP contract; no wire-schema changes.
- Do not add Task 10 RTMDet/ByteTrack/model runtime or Task 11 completion/result-ingestion behavior.
- Python must not connect directly to PostgreSQL.
- Server-returned `leaseExpiresAtUtc` remains authoritative.
- Processing must stop or fail closed once lease ownership is cancelled or its authoritative deadline expires.
- Staged artifacts remain beneath `staging/<job-id>/...`, but each lease attempt gets a unique child namespace.
- A stale attempt must never clean, replace, or publish into another attempt's namespace.
- Existing POSIX dirfd/no-follow confinement and atomic-replace protections must be preserved.
- Track preparation must be deterministic and side-effect free; filesystem publication is a separate responsibility.
- Every behavioral change follows RED -> GREEN TDD. Hosted RED must prove the regression before production code is changed.
- Full hosted MAVI Quality Gate must be green on the exact final head before review clearance.

---

## File Structure Map

```text
src/vision/mavi_vision/common/
  lease.py                       # thread-safe authoritative lease ownership guard

src/vision/mavi_vision/storage/
  artifact_store.py              # attempt-scoped, hardened low-level persistence
  artifact_publisher.py          # sole guarded track-artifact publication gateway

src/vision/mavi_vision/pipeline/
  finalization.py                # pure deterministic track preparation
  process_video.py               # orchestration only

src/vision/mavi_vision/worker/
  runner.py                      # owns guard lifecycle and authoritative renewals

src/vision/tests/
  test_lease_guard.py
  test_artifact_store.py
  test_artifact_publisher.py
  test_process_video.py
  test_worker_lease_heartbeat.py
  test_worker_runner.py
```

## Ownership model

`LeaseGuard` is the single in-process authority used by both threads.

```text
.NET lease/heartbeat response
          |
          v
     WorkerRunner
          |
          | update_deadline(new leaseExpiresAtUtc)
          v
      LeaseGuard  <--------------------+
          |                             |
          | check_owned()/is_lost()     | processing thread
          v                             |
 VideoProcessor -> TrackFinalizer -> ArtifactPublisher
                                      |
                                      v
                            StagingArtifactStore
                     staging/<job>/attempt-XXXX/...
```

The runner still schedules heartbeats before the current deadline. The additional guard means the processing thread can independently observe expiry even if the asyncio event loop is blocked or suspended.

---

### Task 1: Add the authoritative thread-safe LeaseGuard

**Files:**
- Create: `src/vision/mavi_vision/common/lease.py`
- Create: `src/vision/tests/test_lease_guard.py`

**Interfaces:**

```python
class LeaseLostError(RuntimeError): ...

class LeaseGuard:
    def __init__(self, lease_expires_at_utc: datetime, now_utc: Callable[[], datetime] | None = None) -> None: ...
    def update_deadline(self, lease_expires_at_utc: datetime) -> None: ...
    def mark_lost(self) -> None: ...
    def is_lost(self) -> bool: ...
    def check_owned(self) -> None: ...
```

Required behavior:
- reject naive/non-UTC deadlines;
- `is_lost()` is true after `mark_lost()` or when `now >= deadline`;
- `check_owned()` raises `LeaseLostError("lease_lost")` when lost;
- `update_deadline()` replaces the current authoritative deadline, including a shorter but still valid server deadline;
- all mutable state is protected by `threading.Lock`.

TDD scenarios: explicit cancellation, deadline expiry without runner intervention, deadline renewal, and shortened authoritative deadline.

---

### Task 2: Make staging lease-attempt isolated

**Files:**
- Modify: `src/vision/mavi_vision/storage/artifact_store.py`
- Modify: `src/vision/tests/test_artifact_store.py`
- Modify: direct store construction in pipeline tests.

**Interface:**

```python
StagingArtifactStore(media_root: Path, job_id: UUID, attempt_count: int)
```

Canonical namespace:

```text
staging/<job-id>/attempt-0001/thumbnails/<track-id>.jpg
staging/<job-id>/attempt-0001/trajectories/<track-id>.msgpack
```

Required behavior:
- `attempt_count >= 1`;
- `job_id` and `attempt_count` exposed read-only;
- all low-level path walking includes `attempt-XXXX` beneath the job root;
- `cleanup()` deletes only the current attempt subtree;
- cleaning attempt N never modifies attempt N-1/N+1 or another job;
- symlink/root-confinement/dirfd/atomic replacement protections remain unchanged.

TDD scenario proving the architecture: attempt 1 and attempt 2 write the same logical relative artifact; both files coexist, then attempt-1 cleanup leaves attempt-2 bytes untouched.

---

### Task 3: Split pure finalization from artifact publication

**Files:**
- Create: `src/vision/mavi_vision/pipeline/finalization.py`
- Create: `src/vision/tests/test_track_finalization.py`
- Modify later: `process_video.py`.

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class PreparedTrack:
    track_id: str
    object_class: ObjectClass
    start_offset_ms: int
    end_offset_ms: int
    confidence: float
    representative: RepresentativeObservation
    trajectory: tuple[TrajectoryPoint, ...]
    thumbnail_payload: bytes
    trajectory_payload: bytes


def prepare_track(...inputs...) -> PreparedTrack: ...
```

Required behavior:
- validate required representative/observation count;
- serialize trajectory deterministically;
- encode JPEG deterministically with existing parameters;
- no filesystem/store dependency and no side effects.

---

### Task 4: Add the sole ownership-aware ArtifactPublisher

**Files:**
- Create: `src/vision/mavi_vision/storage/artifact_publisher.py`
- Create: `src/vision/tests/test_artifact_publisher.py`
- Modify: `artifact_store.py` to accept an optional publication authorization callback immediately before `os.replace`.

**Interfaces:**

```python
class ArtifactPublisher:
    def __init__(self, store: StagingArtifactStore, lease_guard: LeaseGuard) -> None: ...
    def publish_track(self, prepared: PreparedTrack) -> ProcessedTrack: ...
```

`StagingArtifactStore.write_bytes` gains:

```python
*, authorize_publish: Callable[[], None] | None = None
```

Required behavior:
- publisher calls `lease_guard.check_owned()` before each artifact write;
- store calls `authorize_publish()` after temp-file fsync and immediately before atomic `os.replace`;
- cancellation/expiry during serialization or temp-file I/O prevents final publication;
- partial stale output, if any artifact was published before later lease loss, remains only inside that stale attempt namespace and cannot affect a newer attempt;
- `LeaseLostError` is never translated to a generic staging failure.

TDD scenarios:
- loss before first publish -> neither artifact exists;
- loss between thumbnail and trajectory -> thumbnail may remain in stale attempt only, trajectory absent;
- loss inside low-level write immediately before atomic replace -> destination is not published.

---

### Task 5: Rewire VideoProcessor around guard + attempt + pure preparation

**Files:**
- Modify: `src/vision/mavi_vision/pipeline/process_video.py`
- Modify: `src/vision/tests/test_process_video.py`

**Required process interface:**

```python
def process(
    *,
    job_id: UUID,
    attempt_count: int,
    source_path: Path,
    expected_source_size_bytes: int,
    expected_source_sha256: str,
    lease_guard: LeaseGuard,
) -> VisionProcessingResult
```

Required behavior:
- validate store job and attempt before any mutation;
- guard ownership before startup cleanup;
- source snapshot cancellation uses `lease_guard.is_lost`;
- guard checkpoints remain around frame/decode/detector/tracker boundaries;
- `_finalize_track` side effects are removed; processor prepares then publishes through `ArtifactPublisher`;
- `LeaseLostError` propagates unchanged to the runner; it is not mapped to ordinary `VideoProcessingError`;
- ordinary owned processing failures retain attempt-local best-effort cleanup;
- once guard reports lost, failure cleanup is skipped.

Critical TDD regression: event-loop-independent lease expiry during track preparation/publication must preserve another attempt's same-named artifact.

---

### Task 6: Rewire WorkerRunner to own the LeaseGuard lifecycle

**Files:**
- Modify: `src/vision/mavi_vision/worker/runner.py`
- Modify: `src/vision/tests/test_worker_lease_heartbeat.py`
- Modify: `src/vision/tests/test_worker_runner.py`

Required behavior:
- create `LeaseGuard` from the initial heartbeat's `lease_expires_at_utc` before launching processing;
- pass `attempt_count` and that exact guard instance to the processor;
- on every successful heartbeat, call `guard.update_deadline(response.lease_expires_at_utc)` before continuing;
- on heartbeat/API failure, call `guard.mark_lost()` before awaiting processor shutdown;
- if processor raises `LeaseLostError`, surface it through the existing `WorkerApiError` ownership-loss/backoff path and never call `/fail`;
- processor result is accepted only after `guard.check_owned()`;
- Task-9 deferred submission behavior remains unchanged for a valid result.

Critical TDD scenario: block the asyncio event loop past the current deadline while the processing thread remains active; the processing thread's `LeaseGuard` must reject publication independently, and no terminal stale call may occur.

---

### Task 7: Comprehensive invariant regression matrix and exact-head gate

**Files:**
- Modify tests only as needed; no production behavior after the matrix is complete unless a new test proves a defect.

Required matrix:
- cancellation before processing starts;
- cancellation/expiry during source snapshot;
- cancellation around detector/tracker;
- expiry during pure finalization;
- cancellation before thumbnail publish;
- cancellation at low-level atomic publication boundary;
- cancellation between two artifact publications;
- concurrent ordinary processing exception + lease loss;
- event-loop stall beyond deadline;
- attempt 1 cleanup after attempt 2 exists;
- same-named artifact writes from two attempts remain isolated;
- ordinary owned error still cleans only its own attempt;
- all existing source-integrity, timestamp, artifact confinement and deterministic-output regressions remain green.

Verification sequence:
1. focused Python tests;
2. full Python suite;
3. full hosted MAVI Quality Gate on exact head;
4. confirm all previous blocking threads remain resolved;
5. reply to the current P1 with exact RED/GREEN evidence and resolve only after green;
6. request one fresh Codex review of the exact final head, explicitly asking for remaining P1/P2 findings across the full Task-9 ownership/staging boundary;
7. do not merge until that exact-head review is clean.

## Non-goals

- No `/complete` endpoint.
- No result ingestion/persistence.
- No Task 10 model/runtime integration.
- No database schema changes.
- No frontend changes.
- No weakening of POSIX secure staging.

## Review criterion

The remediation is successful when missing one cooperative cancellation checkpoint can at worst waste bounded work; it must no longer be capable of corrupting, replacing, or deleting another lease attempt's artifacts.