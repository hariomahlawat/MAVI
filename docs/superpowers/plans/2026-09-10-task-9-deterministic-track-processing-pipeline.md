# Task 9 — Deterministic Track Processing Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, model-independent Python vision-processing pipeline that reads a leased MP4 by logical storage key, verifies source integrity, decodes frames using media timestamps, produces deterministic fixture detections/tracks, selects representative evidence, writes staged thumbnail/trajectory artifacts, and returns an internal track-oriented processing result without yet adding a completion API or database writes.

**Architecture:** ASP.NET Core remains the operational authority and PostgreSQL remains exclusively owned by the .NET platform. Python consumes the frozen Task-7/7A v2 lease contract and Task-8 worker/storage boundary, performs only local media processing, and returns an internal analytical result that will be translated into the external completion contract in Task 11. Task 9 must be deterministic and model-independent so Task 10 can replace only detector/tracker adapters with RTMDet/ByteTrack.

**Tech Stack:** Python 3.13+, PyAV, NumPy, Pillow, MessagePack, existing Pydantic/httpx worker stack, pytest. No PyTorch, CUDA, MMDetection, ByteTrack, PostgreSQL client, pgvector client, or external network dependency in this task.

**Spec:** `docs/superpowers/specs/2026-09-08-visual-intelligence-memory-design.md`

## Global Constraints

- Base all implementation work on `feature/visual-intelligence-memory` after merge commit `f18a76683fef5970324cb01d8858125099a3cc9a`.
- Create a dedicated implementation branch for Task 9. PR base/target must be `feature/visual-intelligence-memory`; never target an intermediate planning/execution branch.
- Python remains `>=3.13` as established by Task 8.
- Preserve the frozen Task-7/7A v2 lease/heartbeat/fail wire contract; do not modify canonical casing, token grammar, timestamp grammar, or storage-key grammar in this task.
- Python must not connect to PostgreSQL or any operational database.
- Do not add `/complete` or any result-ingestion HTTP endpoint in Task 9.
- Do not extend the legacy `VisionResult` v1 observation-centric wire DTO for the new pipeline. Task 9 uses a new internal track-oriented analytical model.
- Logical storage keys use `/` and are OS-independent. Absolute filesystem paths must never cross HTTP or analytical contracts.
- Source media must be verified against the lease's `sourceSizeBytes` and lowercase hex `sourceSha256` before decoding.
- Video-relative time is integer `offset_ms`; do not derive or persist wall-clock observation timestamps in the Python pipeline.
- PTS/time-base is authoritative when present; rational frame-rate fallback is allowed only when a decoded frame has no usable PTS.
- Track is the primary analytical unit. Do not emit one durable relational-style observation object per processed frame.
- Staged artifacts must remain beneath `staging/<job-id>/...` and be addressed by logical storage key plus SHA-256/size/media type.
- Deterministic fixtures only: no learned model, network download, GPU dependency, random track IDs, nondeterministic timestamps, or external services.
- Tests are written before production changes for every behavioural change.
- Full hosted MAVI Quality Gate must be green before merge.

---

## File Structure Map

Create or modify only the following primary units for Task 9:

```text
src/vision/pyproject.toml

src/vision/mavi_vision/common/
  analytical.py                 # internal track-oriented result/value types

src/vision/mavi_vision/storage/
  local_media_store.py          # retain source resolution; add no arbitrary writes
  artifact_store.py             # root-confined staging artifact writer
  integrity.py                  # source size/SHA-256 verification

src/vision/mavi_vision/video/
  reader.py                     # PyAV PTS-aware decoded-frame iterator
  trajectory.py                 # deterministic trajectory model + MessagePack serializer

src/vision/mavi_vision/detection/
  interfaces.py                 # typed frame/object-class boundary
  fixture.py                    # deterministic fixture detector

src/vision/mavi_vision/tracking/
  interfaces.py                 # typed frame/object-class boundary
  fixture.py                    # deterministic fixture tracker

src/vision/mavi_vision/quality/
  __init__.py
  scoring.py                    # deterministic representative-frame score

src/vision/mavi_vision/pipeline/
  __init__.py
  process_video.py              # orchestration only

src/vision/tests/
  test_source_integrity.py
  test_artifact_store.py
  test_video_reader.py
  test_trajectory.py
  test_fixture_detection_tracking.py
  test_quality_scoring.py
  test_process_video.py
```

Do not modify `worker/client.py`, the Task-7/7A control-plane models, .NET persistence, result-ingestion contracts, React, or database migrations in this task unless a genuine blocker is discovered and separately reviewed.

---

### Task 9.1: Add Deterministic Media Dependencies and Internal Analytical Types

**Files:**
- Modify: `src/vision/pyproject.toml`
- Create: `src/vision/mavi_vision/common/analytical.py`
- Test: `src/vision/tests/test_analytical_models.py`

**Interfaces:**
- Produces `ObjectClass`, `NormalizedBoundingBox`, `TrajectoryPoint`, `RepresentativeObservation`, `ArtifactDescriptor`, `ProcessedTrack`, and `VisionProcessingResult`.
- These are Python-internal Task-9 types. They are not HTTP DTOs and must not be serialized through the frozen worker API.

- [ ] **Step 1: Add failing analytical-model tests**

Test exact invariants:

```python
from uuid import UUID
import pytest

from mavi_vision.common.analytical import (
    ArtifactDescriptor,
    NormalizedBoundingBox,
    ObjectClass,
    ProcessedTrack,
    RepresentativeObservation,
    TrajectoryPoint,
    VisionProcessingResult,
)


def test_normalized_bbox_rejects_out_of_range_values() -> None:
    with pytest.raises(ValueError):
        NormalizedBoundingBox(x=-0.01, y=0.0, width=0.2, height=0.2)


def test_processing_result_is_track_oriented() -> None:
    track = ProcessedTrack(
        track_id="fixture-0001",
        object_class=ObjectClass.PERSON,
        start_offset_ms=0,
        end_offset_ms=1000,
        confidence=0.9,
        representative=RepresentativeObservation(
            offset_ms=500,
            source_frame_number=12,
            confidence=0.9,
            bounding_box=NormalizedBoundingBox(0.1, 0.1, 0.2, 0.4),
            quality_score=0.8,
        ),
        trajectory=(TrajectoryPoint(0, 0.2, 0.3), TrajectoryPoint(1000, 0.4, 0.3)),
        thumbnail=ArtifactDescriptor("staging/job/thumbnails/fixture-0001.jpg", "image/jpeg", 10, "a" * 64),
        trajectory_artifact=ArtifactDescriptor("staging/job/trajectories/fixture-0001.msgpack", "application/msgpack", 20, "b" * 64),
    )
    result = VisionProcessingResult(job_id=UUID(int=1), frames_processed=25, tracks=(track,))
    assert result.tracks == (track,)
```

- [ ] **Step 2: Run and verify RED**

```bash
cd src/vision
python -m pytest tests/test_analytical_models.py -q
```

Expected: import failure because `analytical.py` does not exist.

- [ ] **Step 3: Add dependencies and minimal types**

Add bounded dependencies to `pyproject.toml`:

```toml
"av>=15,<17",
"numpy>=2.2,<3",
"Pillow>=11,<12",
"msgpack>=1.1,<2",
```

Implement:

```python
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

class ObjectClass(StrEnum):
    PERSON = "person"
    VEHICLE = "vehicle"

@dataclass(frozen=True, slots=True)
class NormalizedBoundingBox:
    x: float
    y: float
    width: float
    height: float

@dataclass(frozen=True, slots=True)
class TrajectoryPoint:
    offset_ms: int
    center_x: float
    center_y: float

@dataclass(frozen=True, slots=True)
class RepresentativeObservation:
    offset_ms: int
    source_frame_number: int
    confidence: float
    bounding_box: NormalizedBoundingBox
    quality_score: float

@dataclass(frozen=True, slots=True)
class ArtifactDescriptor:
    storage_key: str
    media_type: str
    size_bytes: int
    sha256: str

@dataclass(frozen=True, slots=True)
class ProcessedTrack:
    track_id: str
    object_class: ObjectClass
    start_offset_ms: int
    end_offset_ms: int
    confidence: float
    representative: RepresentativeObservation
    trajectory: tuple[TrajectoryPoint, ...]
    thumbnail: ArtifactDescriptor
    trajectory_artifact: ArtifactDescriptor

@dataclass(frozen=True, slots=True)
class VisionProcessingResult:
    job_id: UUID
    frames_processed: int
    tracks: tuple[ProcessedTrack, ...]
```

Validate non-negative offsets/frame numbers/sizes, confidence and quality in `[0,1]`, normalized boxes fully within `[0,1]`, monotonic trajectory offsets, 64-character lowercase hex SHA-256, and relative slash-separated artifact storage keys.

- [ ] **Step 4: Run tests GREEN**

```bash
python -m pytest tests/test_analytical_models.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/vision/pyproject.toml src/vision/mavi_vision/common/analytical.py src/vision/tests/test_analytical_models.py
git commit -m "feat: add task9 analytical track model"
```

---

### Task 9.2: Verify Leased Source Media Before Processing

**Files:**
- Create: `src/vision/mavi_vision/storage/integrity.py`
- Test: `src/vision/tests/test_source_integrity.py`

**Interfaces:**
- Consumes a resolved `Path` plus expected size/SHA-256 from `VisionJobLease`.
- Produces `VerifiedSource(path: Path, size_bytes: int, sha256: str)`.

- [ ] **Step 1: Write failing tests**

Cover exact success, size mismatch, SHA mismatch, and missing file:

```python
from hashlib import sha256
import pytest

from mavi_vision.storage.integrity import SourceIntegrityError, verify_source


def test_verify_source_accepts_matching_file(tmp_path):
    source = tmp_path / "input.mp4"
    source.write_bytes(b"video")
    digest = sha256(b"video").hexdigest()
    verified = verify_source(source, expected_size_bytes=5, expected_sha256=digest)
    assert verified.path == source


def test_verify_source_rejects_sha_mismatch(tmp_path):
    source = tmp_path / "input.mp4"
    source.write_bytes(b"video")
    with pytest.raises(SourceIntegrityError, match="source_sha256_mismatch"):
        verify_source(source, expected_size_bytes=5, expected_sha256="0" * 64)
```

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/test_source_integrity.py -q
```

- [ ] **Step 3: Implement streaming verification**

Implement `verify_source(path, expected_size_bytes, expected_sha256)` using `Path.stat()` for size and `hashlib.sha256()` over fixed-size chunks. Never read the entire MP4 into memory. Raise stable `SourceIntegrityError.code` values:

```text
source_missing
source_size_mismatch
source_sha256_mismatch
source_read_failed
```

- [ ] **Step 4: Run GREEN and commit**

```bash
python -m pytest tests/test_source_integrity.py -q
git add src/vision/mavi_vision/storage/integrity.py src/vision/tests/test_source_integrity.py
git commit -m "feat: verify leased source media integrity"
```

---

### Task 9.3: Add Root-Confined Staging Artifact Store

**Files:**
- Create: `src/vision/mavi_vision/storage/artifact_store.py`
- Test: `src/vision/tests/test_artifact_store.py`

**Interfaces:**
- `StagingArtifactStore(media_root: Path, job_id: UUID)`
- `write_bytes(relative_name: str, content: bytes, media_type: str) -> ArtifactDescriptor`
- `thumbnail_key(track_id: str) -> str`
- `trajectory_key(track_id: str) -> str`
- `cleanup() -> None`

- [ ] **Step 1: Write failing confinement/digest tests**

Prove generated keys are exactly beneath `staging/<job-id>/`, SHA/size are correct, parent traversal is rejected, absolute paths are rejected, and symlink escapes cannot be written through.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/test_artifact_store.py -q
```

- [ ] **Step 3: Implement store**

Use logical keys only. Convert the final key to a filesystem path only inside the store, call `resolve(strict=False)` on the destination parent, require containment below the resolved media root, create only the job staging directories, write to a sibling temporary file, `flush()`/`os.fsync()`, then `os.replace()` into final position. Return `ArtifactDescriptor` with SHA-256 and byte length.

Canonical keys:

```text
staging/<job-uuid>/thumbnails/<safe-track-id>.jpg
staging/<job-uuid>/trajectories/<safe-track-id>.msgpack
```

Restrict `track_id` to `[A-Za-z0-9._-]{1,64}` at this boundary.

- [ ] **Step 4: Run GREEN and commit**

```bash
python -m pytest tests/test_artifact_store.py -q
git add src/vision/mavi_vision/storage/artifact_store.py src/vision/tests/test_artifact_store.py
git commit -m "feat: add confined task9 staging artifact store"
```

---

### Task 9.4: Implement PTS-Aware MP4 Frame Reader

**Files:**
- Create: `src/vision/mavi_vision/video/reader.py`
- Test: `src/vision/tests/test_video_reader.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class DecodedFrame:
    source_frame_number: int
    offset_ms: int
    image: NDArray[np.uint8]   # H x W x 3 RGB

class VideoReadError(RuntimeError): ...

def iter_frames(path: Path) -> Iterator[DecodedFrame]: ...
```

- [ ] **Step 1: Write fixture-video helper and failing reader test**

Generate a tiny MP4 inside the pytest temp directory using PyAV. Do not commit binary media. Decode it and assert source frame numbers are zero-based/increasing, RGB shape is stable, offsets are non-negative and monotonic.

- [ ] **Step 2: Add a unit test for time calculation**

Expose a private pure helper `_frame_offset_ms(pts, time_base, frame_number, frame_rate_num, frame_rate_den)` and test:
- PTS present: `pts * time_base * 1000`, rounded to nearest integer using deterministic decimal/rational arithmetic;
- PTS absent: `frame_number * 1000 * denominator / numerator`;
- neither usable PTS nor valid frame rate: raise `VideoReadError("frame_timestamp_unavailable")`.

- [ ] **Step 3: Run RED**

```bash
python -m pytest tests/test_video_reader.py -q
```

- [ ] **Step 4: Implement PyAV reader**

Open the local verified path with `av.open()`, require exactly one usable video stream for Phase 1, decode in presentation order, convert each frame to `rgb24`, and return contiguous `np.uint8` arrays. Do not derive UTC timestamps.

- [ ] **Step 5: Run GREEN and commit**

```bash
python -m pytest tests/test_video_reader.py -q
git add src/vision/mavi_vision/video/reader.py src/vision/tests/test_video_reader.py
git commit -m "feat: add pts aware video reader"
```

---

### Task 9.5: Add Deterministic Fixture Detector and Tracker

**Files:**
- Modify: `src/vision/mavi_vision/detection/interfaces.py`
- Modify: `src/vision/mavi_vision/tracking/interfaces.py`
- Create: `src/vision/mavi_vision/detection/fixture.py`
- Create: `src/vision/mavi_vision/tracking/fixture.py`
- Test: `src/vision/tests/test_fixture_detection_tracking.py`

**Interfaces:**

Refine the existing interface types without changing their architectural role:

```python
@dataclass(frozen=True, slots=True)
class DetectionCandidate:
    object_class: ObjectClass
    confidence: float
    bounding_box: NormalizedBoundingBox

class Detector(Protocol):
    def detect(self, frame: DecodedFrame) -> Sequence[DetectionCandidate]: ...

@dataclass(frozen=True, slots=True)
class TrackCandidate:
    track_id: str
    object_class: ObjectClass
    confidence: float
    bounding_box: NormalizedBoundingBox

class Tracker(Protocol):
    def update(self, frame: DecodedFrame, detections: Sequence[DetectionCandidate]) -> Sequence[TrackCandidate]: ...
```

- [ ] **Step 1: Write RED tests for deterministic fixtures**

Construct synthetic `DecodedFrame` instances and verify the fixture detector yields the same person/vehicle detections for the same frame number every run. Verify the fixture tracker assigns stable IDs such as `person-0001` and keeps the same ID across sequential frames according to deterministic fixture rules.

- [ ] **Step 2: Implement `FixtureDetector`**

Use frame-number-indexed fixture definitions supplied at construction:

```python
FixtureDetector({
    0: (DetectionCandidate(ObjectClass.PERSON, 0.90, ...),),
    1: (DetectionCandidate(ObjectClass.PERSON, 0.92, ...),),
})
```

No pixel inference and no randomness.

- [ ] **Step 3: Implement `FixtureTracker`**

For Task 9, accept a deterministic association map keyed by `(source_frame_number, detection_index)` to stable `track_id`; reject missing/duplicate mapping entries rather than guessing associations. Task 10 will replace this adapter with ByteTrack.

- [ ] **Step 4: Run GREEN and commit**

```bash
python -m pytest tests/test_fixture_detection_tracking.py -q
git add src/vision/mavi_vision/detection src/vision/mavi_vision/tracking src/vision/tests/test_fixture_detection_tracking.py
git commit -m "feat: add deterministic detection tracking fixtures"
```

---

### Task 9.6: Add Trajectory Serialization and Representative Quality Scoring

**Files:**
- Create: `src/vision/mavi_vision/video/trajectory.py`
- Create: `src/vision/mavi_vision/quality/__init__.py`
- Create: `src/vision/mavi_vision/quality/scoring.py`
- Test: `src/vision/tests/test_trajectory.py`
- Test: `src/vision/tests/test_quality_scoring.py`

**Interfaces:**

```python
def serialize_trajectory(points: Sequence[TrajectoryPoint]) -> bytes: ...
def deserialize_trajectory(payload: bytes) -> tuple[TrajectoryPoint, ...]: ...

def representative_quality(frame: DecodedFrame, bbox: NormalizedBoundingBox) -> float: ...
```

- [ ] **Step 1: Write RED trajectory tests**

Require deterministic bytes for identical point sequences, round-trip equality, monotonic-offset validation, normalized centers, and rejection of malformed payloads. Use a fixed MessagePack object shape:

```python
{"v": 1, "points": [[offset_ms, center_x, center_y], ...]}
```

Pack with deterministic key/order choices controlled by the implementation; never serialize arbitrary Python objects.

- [ ] **Step 2: Implement serializer and run GREEN**

Use `msgpack.packb(..., use_bin_type=True)` and strict manual validation on unpack.

- [ ] **Step 3: Write RED quality tests**

Quality must be deterministic and depend only on the decoded RGB frame and bbox. Define the score exactly as:

```text
0.45 * normalized_sharpness
+ 0.35 * bbox_area_score
+ 0.20 * edge_margin_score
```

Clamp to `[0,1]`. `normalized_sharpness` is mean absolute grayscale finite-difference energy divided by `64.0` and clamped to `[0,1]`; `bbox_area_score = min(1, bbox_area / 0.20)`; `edge_margin_score = min(1, min(left, top, right, bottom) / 0.10)`.

- [ ] **Step 4: Implement scoring without OpenCV**

Use NumPy only. Crop/convert deterministically; return `0.0` for an empty crop.

- [ ] **Step 5: Run GREEN and commit**

```bash
python -m pytest tests/test_trajectory.py tests/test_quality_scoring.py -q
git add src/vision/mavi_vision/video/trajectory.py src/vision/mavi_vision/quality src/vision/tests/test_trajectory.py src/vision/tests/test_quality_scoring.py
git commit -m "feat: add deterministic trajectory and quality processing"
```

---

### Task 9.7: Build Model-Independent `VideoProcessor`

**Files:**
- Create: `src/vision/mavi_vision/pipeline/__init__.py`
- Create: `src/vision/mavi_vision/pipeline/process_video.py`
- Test: `src/vision/tests/test_process_video.py`

**Interfaces:**

```python
class VideoProcessor:
    def __init__(self, detector: Detector, tracker: Tracker, artifact_store: StagingArtifactStore): ...

    def process(
        self,
        *,
        job_id: UUID,
        source_path: Path,
        expected_source_size_bytes: int,
        expected_source_sha256: str,
    ) -> VisionProcessingResult: ...
```

- [ ] **Step 1: Write failing end-to-end deterministic fixture test**

Generate a tiny MP4 in `tmp_path`, compute its real SHA/size, provide fixture detections/associations for one moving person, run `VideoProcessor.process()`, and assert:

```text
frames_processed > 0
tracks == 1
track_id == "person-0001"
start_offset_ms <= representative.offset_ms <= end_offset_ms
trajectory offsets strictly monotonic
representative selected by max quality score, then lowest offset_ms on tie
thumbnail descriptor exists under staging/<job-id>/thumbnails/
trajectory descriptor exists under staging/<job-id>/trajectories/
artifact SHA-256 and size match files
```

Also test zero detections => zero tracks and no track artifacts.

- [ ] **Step 2: Write failure tests before implementation**

Cover:
- source integrity mismatch => no staged artifacts remain;
- corrupt/non-decodable MP4 => stable `VideoProcessingError("video_decode_failed")` and cleanup;
- fixture detector/tracker error => stable `VideoProcessingError("pipeline_processing_failed")` and cleanup;
- multiple observations at the same quality => earliest offset selected deterministically.

- [ ] **Step 3: Implement orchestration only**

Pipeline order must be exactly:

```text
verify source
→ decode frame
→ detector.detect(frame)
→ tracker.update(frame, detections)
→ accumulate per-track offsets/confidence/bbox centers
→ score representative candidates
→ crop representative RGB bbox and encode JPEG with fixed Pillow parameters
→ serialize trajectory MessagePack
→ write staged artifacts through StagingArtifactStore
→ construct VisionProcessingResult
```

Use fixed JPEG settings: RGB, quality `90`, optimize `False`, progressive `False`, subsampling `2`. Track confidence is arithmetic mean of tracked observation confidences. Representative tie-break order is highest quality, then highest confidence, then lowest `offset_ms`, then lowest `source_frame_number`.

- [ ] **Step 4: Run GREEN**

```bash
python -m pytest tests/test_process_video.py -q
```

- [ ] **Step 5: Run entire Python suite**

```bash
python -m pytest -q
```

Expected: all Task-7/7A/8 tests plus new Task-9 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/vision/mavi_vision/pipeline src/vision/tests/test_process_video.py
git commit -m "feat: add deterministic task9 video processor"
```

---

### Task 9.8: Integrate the Pipeline Behind the Worker Without Adding Completion

**Files:**
- Modify: `src/vision/mavi_vision/worker/runner.py`
- Modify: `src/vision/mavi_vision/worker/main.py`
- Test: `src/vision/tests/test_worker_runner.py`

**Interfaces:**
- `WorkerRunner` gains an injected processing callable/protocol but retains lease, heartbeat, fail and backoff semantics from Task 8.
- Successful deterministic processing in Task 9 must **not** be represented as completion because the Task-11 completion endpoint does not exist yet.

- [ ] **Step 1: Write RED worker integration tests**

Add a processor stub and prove:
- lease source is resolved and verified/processed once;
- heartbeat still occurs before heavy processing;
- processor failure maps to one stable fail request;
- API transport failures still propagate to `run_forever()` backoff;
- successful Task-9 processing produces an internal result but deliberately reports `task9_result_submission_not_implemented` exactly once, preserving the no-fake-completion rule.

- [ ] **Step 2: Introduce processor protocol**

```python
class VisionProcessor(Protocol):
    def process(
        self,
        *,
        job_id: UUID,
        source_path: Path,
        expected_source_size_bytes: int,
        expected_source_sha256: str,
    ) -> VisionProcessingResult: ...
```

Retain the existing Task-8 post-lease `WorkerApiError` propagation/backoff behavior.

- [ ] **Step 3: Compose fixture processor only for test/dev execution**

Do not make a hard-coded production fixture the default service configuration. `main.py` may expose a `build_worker(...)` composition helper used by tests, while the executable remains unable to claim real production completion until Task 10/11 wiring is available.

- [ ] **Step 4: Run worker and Python suite**

```bash
python -m pytest tests/test_worker_runner.py tests/test_process_video.py -q
python -m pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add src/vision/mavi_vision/worker src/vision/tests/test_worker_runner.py
git commit -m "feat: connect deterministic pipeline to worker lifecycle"
```

---

### Task 9.9: Acceptance, Repository Verification, and PR Gate

**Files:**
- Modify only if required by deterministic test/verification findings.

- [ ] **Step 1: Run Python verification from the declared environment**

```bash
cd src/vision
python -m pytest -q
```

- [ ] **Step 2: Run repository verification**

```bash
cd ../..
python tools/verify_repo.py
```

- [ ] **Step 3: Run .NET regression suite**

With `MAVI_TEST_DB_CONNECTION` pointing only to `mavi_test`:

```bash
dotnet build MAVI.sln --configuration Release
dotnet test MAVI.sln --configuration Release --no-build
```

- [ ] **Step 4: Run frontend regression suite**

```bash
cd src/web/mavi-web
npm ci
npm test
npm run typecheck
npm run build
```

- [ ] **Step 5: Re-run Python suite after all repository checks**

```bash
cd ../../../src/vision
python -m pytest -q
```

- [ ] **Step 6: Open PR with exact integration target**

PR rules:

```text
HEAD = dedicated Task-9 implementation branch
BASE = feature/visual-intelligence-memory
Do not merge automatically.
Do not target a planning/execution branch.
```

PR description must state explicitly:
- no PostgreSQL access from Python;
- no `/complete` endpoint;
- no RTMDet/ByteTrack/PyTorch/CUDA;
- source SHA/size preflight is enforced;
- PTS-aware offsets are media-relative milliseconds;
- outputs are track-oriented internal results plus staged artifacts;
- all fixture outputs are deterministic.

- [ ] **Step 7: Require hosted gate and current-head review**

Wait for the MAVI Quality Gate on the current PR head. Then request a Codex review limited to blocking P1/P2 issues, explicitly checking source-integrity enforcement, path confinement, timestamp semantics, deterministic serialization/scoring, cleanup, Task-8 backoff preservation, and absence of scope creep into Task 10/11.

- [ ] **Step 8: Merge only after both conditions are true**

```text
1. Current-head MAVI Quality Gate = success
2. No unresolved blocking P1/P2 findings or merge blockers
```

Use the repository-accepted merge method, verify the merge commit SHA, then delete/close the implementation branch if permitted.

---

## Acceptance Criteria

Task 9 is complete only when all of the following are demonstrated by tests and hosted CI:

1. A leased source MP4 is not decoded unless its size and SHA-256 match the lease.
2. Frame offsets come from PTS/time-base when available and otherwise from rational frame-rate fallback.
3. All analytical time values are video-relative integer milliseconds, never fabricated UTC timestamps.
4. Fixture detector/tracker behavior is deterministic across repeated runs.
5. One deterministic moving-person fixture produces one stable track with monotonic trajectory points.
6. Each produced track has exactly one representative observation, one JPEG thumbnail descriptor, and one MessagePack trajectory descriptor.
7. Staged artifacts are root-confined beneath `staging/<job-id>/...`; traversal, absolute paths and symlink escapes are rejected.
8. Artifact descriptors carry logical storage key, media type, exact byte size and lowercase SHA-256.
9. Corrupt media, integrity mismatch and pipeline failure leave no accepted analytical result and no unintended staged residue.
10. Task-8 worker API transport backoff remains intact.
11. No Python PostgreSQL client, real detector/tracker model, completion endpoint, React change or database migration is introduced.
12. Full MAVI Quality Gate passes on the current PR head and no blocking P1/P2 review finding remains.

## Deliberately Deferred to Later Tasks

- **Task 10:** RTMDet and ByteTrack production adapters, GPU/model manifests, real inference thresholds and device selection.
- **Task 11:** external result-completion contract, .NET validation, atomic persistence of Tracks/Artifacts/ProcessingRun/VisionJob completion.
- **Task 12+:** searchable track APIs, evidence streaming and operator UI.

## Self-Review of This Plan

- **Spec coverage:** preserves recorded-MP4-only Phase 1, track-primary memory, logical storage keys, Python/.NET separation, UTC-vs-offset rules and deterministic testing.
- **Post-Task-8 corrections incorporated:** Python 3.13, frozen v2 worker control plane, post-lease backoff semantics, current local-development quality-gate discipline.
- **Architectural debt avoided:** legacy `VisionResult` v1 is not expanded into Task 9; result submission remains deferred to Task 11.
- **Type consistency:** `ObjectClass`, `NormalizedBoundingBox`, `DecodedFrame`, `TrajectoryPoint`, `ArtifactDescriptor`, `ProcessedTrack` and `VisionProcessingResult` are introduced before any dependent task.
- **Scope control:** no learned model, GPU stack, database access, completion endpoint or UI work appears in Task 9.
