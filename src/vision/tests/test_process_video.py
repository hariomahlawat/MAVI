from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import av
import numpy as np
import pytest

import mavi_vision.pipeline.process_video as process_video_module
from mavi_vision.common.analytical import NormalizedBoundingBox, ObjectClass
from mavi_vision.common.lease import LeaseGuard, LeaseLostError
from mavi_vision.detection.fixture import FixtureDetector
from mavi_vision.detection.interfaces import DetectionCandidate
from mavi_vision.pipeline.process_video import VideoProcessingError, VideoProcessor
from mavi_vision.runtime.errors import GpuOutOfMemoryError, TrackerError
from mavi_vision.storage.artifact_store import StagingArtifactStore
from mavi_vision.storage.integrity import SourceIntegrityError
from mavi_vision.tracking.fixture import FixtureTracker


JOB_ID = UUID("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761")
OTHER_JOB_ID = UUID("018fa7b6-2b31-7f42-9f33-9fd9f6fdd762")
ATTEMPT = 1
BASE = datetime(2026, 9, 10, 14, 30, tzinfo=timezone.utc)


def _write_tiny_mp4(path: Path, frame_count: int = 3) -> None:
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=10)
        stream.width = 32
        stream.height = 24
        stream.pix_fmt = "yuv420p"
        for index in range(frame_count):
            image = np.zeros((24, 32, 3), dtype=np.uint8)
            image[:, :, :] = 32 + index * 8
            frame = av.VideoFrame.from_ndarray(image, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def _source_facts(path: Path) -> tuple[int, str]:
    payload = path.read_bytes()
    return len(payload), sha256(payload).hexdigest()


def _person(confidence: float = 0.9) -> DetectionCandidate:
    return DetectionCandidate(
        ObjectClass.PERSON,
        confidence,
        NormalizedBoundingBox(0.20, 0.20, 0.40, 0.50),
    )


def _owned_guard() -> LeaseGuard:
    return LeaseGuard(datetime.now(timezone.utc) + timedelta(minutes=5))


def _processor(
    tmp_path: Path,
    detections: dict[int, tuple[DetectionCandidate, ...]],
    *,
    attempt: int = ATTEMPT,
) -> VideoProcessor:
    associations = {
        (frame_number, index): "person-0001"
        for frame_number, items in detections.items()
        for index, _ in enumerate(items)
    }
    return VideoProcessor(
        FixtureDetector(detections),
        FixtureTracker(associations),
        StagingArtifactStore(tmp_path, JOB_ID, attempt),
    )


def _run(
    processor: VideoProcessor,
    source: Path,
    size: int,
    digest: str,
    *,
    attempt: int = ATTEMPT,
    lease_guard: LeaseGuard | None = None,
):
    return processor.process(
        job_id=JOB_ID,
        attempt_count=attempt,
        source_path=source,
        expected_source_size_bytes=size,
        expected_source_sha256=digest,
        lease_guard=lease_guard or _owned_guard(),
    )


def _artifact_path(root: Path, storage_key: str) -> Path:
    return root.joinpath(*storage_key.split("/"))


def _attempt_path(root: Path, job_id: UUID = JOB_ID, attempt: int = ATTEMPT) -> Path:
    return root / "staging" / str(job_id) / f"attempt-{attempt:04d}"


def test_process_builds_one_deterministic_track_and_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source)
    size, digest = _source_facts(source)
    detections = {0: (_person(),), 1: (_person(),), 2: (_person(),)}

    result = _run(_processor(tmp_path, detections), source, size, digest)

    assert result.frames_processed == 3
    assert len(result.tracks) == 1
    track = result.tracks[0]
    assert track.track_id == "person-0001"
    assert track.object_class is ObjectClass.PERSON
    assert track.start_offset_ms <= track.representative.offset_ms <= track.end_offset_ms
    assert track.representative.offset_ms == track.start_offset_ms
    offsets = [point.offset_ms for point in track.trajectory]
    assert offsets == sorted(offsets)
    assert all(current > previous for previous, current in zip(offsets, offsets[1:]))

    thumbnail_path = _artifact_path(tmp_path, track.thumbnail.storage_key)
    trajectory_path = _artifact_path(tmp_path, track.trajectory_artifact.storage_key)
    assert thumbnail_path.exists()
    assert trajectory_path.exists()
    assert "/attempt-0001/thumbnails/" in track.thumbnail.storage_key
    assert "/attempt-0001/trajectories/" in track.trajectory_artifact.storage_key
    assert track.thumbnail.size_bytes == thumbnail_path.stat().st_size
    assert track.thumbnail.sha256 == sha256(thumbnail_path.read_bytes()).hexdigest()
    assert track.trajectory_artifact.size_bytes == trajectory_path.stat().st_size
    assert track.trajectory_artifact.sha256 == sha256(trajectory_path.read_bytes()).hexdigest()


def test_process_zero_detections_returns_no_tracks_or_track_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source)
    size, digest = _source_facts(source)

    result = _run(_processor(tmp_path, {}), source, size, digest)

    assert result.frames_processed == 3
    assert result.tracks == ()
    assert not _attempt_path(tmp_path).exists()


def test_integrity_mismatch_cleans_only_current_attempt_staging(tmp_path: Path) -> None:
    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source)
    size, _ = _source_facts(source)
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)
    store.write_bytes("stale.bin", b"stale", "application/octet-stream")
    replacement = StagingArtifactStore(tmp_path, JOB_ID, 2)
    replacement_descriptor = replacement.write_bytes(
        "keep.bin", b"replacement", "application/octet-stream"
    )
    replacement_path = _artifact_path(tmp_path, replacement_descriptor.storage_key)
    processor = VideoProcessor(FixtureDetector({}), FixtureTracker({}), store)

    with pytest.raises(SourceIntegrityError, match="source_sha256_mismatch"):
        _run(processor, source, size, "0" * 64)

    assert not _attempt_path(tmp_path).exists()
    assert replacement_path.read_bytes() == b"replacement"


def test_pre_lost_processor_preserves_existing_attempt_staging(tmp_path: Path) -> None:
    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source)
    size, digest = _source_facts(source)
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)
    descriptor = store.write_bytes("keep.bin", b"keep", "application/octet-stream")
    keep_path = _artifact_path(tmp_path, descriptor.storage_key)
    processor = VideoProcessor(FixtureDetector({}), FixtureTracker({}), store)
    guard = _owned_guard()
    guard.mark_lost()

    with pytest.raises(LeaseLostError, match="lease_lost"):
        _run(processor, source, size, digest, lease_guard=guard)

    assert keep_path.read_bytes() == b"keep"


def test_processing_failure_after_lease_loss_preserves_replacement_attempt(tmp_path: Path) -> None:
    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source, frame_count=1)
    size, digest = _source_facts(source)
    stale_store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)
    replacement_store = StagingArtifactStore(tmp_path, JOB_ID, 2)
    guard = _owned_guard()
    replacement_path: Path | None = None

    class FailingDetector:
        def detect(self, frame):
            nonlocal replacement_path
            descriptor = replacement_store.write_bytes(
                "reclaimed/keep.bin",
                b"new-attempt",
                "application/octet-stream",
            )
            replacement_path = _artifact_path(tmp_path, descriptor.storage_key)
            guard.mark_lost()
            raise RuntimeError("processing failure after lease loss")

    processor = VideoProcessor(FailingDetector(), FixtureTracker({}), stale_store)

    with pytest.raises(LeaseLostError, match="lease_lost"):
        _run(processor, source, size, digest, lease_guard=guard)

    assert replacement_path is not None
    assert replacement_path.read_bytes() == b"new-attempt"


def test_deadline_expiry_during_source_snapshot_maps_to_lease_loss(tmp_path: Path) -> None:
    source = tmp_path / "large-source.mp4"
    source.write_bytes(b"x" * (2 * 1024 * 1024))
    size, digest = _source_facts(source)
    processor = _processor(tmp_path, {})
    clock_checks = 0

    def now_utc() -> datetime:
        nonlocal clock_checks
        clock_checks += 1
        if clock_checks < 5:
            return BASE
        return BASE + timedelta(seconds=2)

    guard = LeaseGuard(BASE + timedelta(seconds=1), now_utc=now_utc)

    with pytest.raises(LeaseLostError, match="lease_lost"):
        _run(processor, source, size, digest, lease_guard=guard)

    assert clock_checks >= 5


def test_deadline_expiry_after_pure_finalization_prevents_stale_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source, frame_count=1)
    size, digest = _source_facts(source)
    detections = {0: (_person(),)}
    processor = _processor(tmp_path, detections)
    replacement_store = StagingArtifactStore(tmp_path, JOB_ID, 2)
    replacement_descriptor = replacement_store.write_bytes(
        "thumbnails/person-0001.jpg",
        b"replacement-attempt",
        "image/jpeg",
    )
    replacement_path = _artifact_path(tmp_path, replacement_descriptor.storage_key)
    now = BASE
    guard = LeaseGuard(BASE + timedelta(seconds=1), now_utc=lambda: now)
    real_prepare = process_video_module.prepare_track

    def prepare_then_expire(**kwargs):
        nonlocal now
        prepared = real_prepare(**kwargs)
        now = BASE + timedelta(seconds=2)
        return prepared

    monkeypatch.setattr(process_video_module, "prepare_track", prepare_then_expire)

    with pytest.raises(LeaseLostError, match="lease_lost"):
        _run(processor, source, size, digest, lease_guard=guard)

    assert not (_attempt_path(tmp_path) / "thumbnails" / "person-0001.jpg").exists()
    assert replacement_path.read_bytes() == b"replacement-attempt"


def test_corrupt_video_maps_to_stable_error_and_cleans_attempt(tmp_path: Path) -> None:
    source = tmp_path / "corrupt.mp4"
    source.write_bytes(b"not-an-mp4")
    size, digest = _source_facts(source)
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)
    store.write_bytes("stale.bin", b"stale", "application/octet-stream")
    processor = VideoProcessor(FixtureDetector({}), FixtureTracker({}), store)

    with pytest.raises(VideoProcessingError) as exc_info:
        _run(processor, source, size, digest)

    assert exc_info.value.code == "video_decode_failed"
    assert not _attempt_path(tmp_path).exists()


def test_detector_failure_maps_to_pipeline_error_and_cleans_attempt(tmp_path: Path) -> None:
    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source)
    size, digest = _source_facts(source)
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)

    class FailingDetector:
        def detect(self, frame):
            raise RuntimeError("fixture failure")

    processor = VideoProcessor(FailingDetector(), FixtureTracker({}), store)

    with pytest.raises(VideoProcessingError) as exc_info:
        _run(processor, source, size, digest)

    assert exc_info.value.code == "pipeline_processing_failed"
    assert not _attempt_path(tmp_path).exists()



def test_gpu_oom_error_propagates_unchanged_and_cleans_owned_attempt(
    tmp_path: Path,
) -> None:
    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source, frame_count=1)
    size, digest = _source_facts(source)
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)
    store.write_bytes("stale.bin", b"stale", "application/octet-stream")
    error = GpuOutOfMemoryError("fixture oom")

    class FailingDetector:
        def detect(self, frame):
            raise error

    processor = VideoProcessor(FailingDetector(), FixtureTracker({}), store)

    with pytest.raises(GpuOutOfMemoryError) as exc_info:
        _run(processor, source, size, digest)

    assert exc_info.value is error
    assert not _attempt_path(tmp_path).exists()


def test_tracker_error_propagates_unchanged_and_cleans_owned_attempt(
    tmp_path: Path,
) -> None:
    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source, frame_count=1)
    size, digest = _source_facts(source)
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)
    store.write_bytes("stale.bin", b"stale", "application/octet-stream")
    error = TrackerError("fixture tracker failure")

    class FailingTracker:
        def update(self, frame, detections):
            raise error

    processor = VideoProcessor(
        FixtureDetector({0: (_person(),)}),
        FailingTracker(),
        store,
    )

    with pytest.raises(TrackerError) as exc_info:
        _run(processor, source, size, digest)

    assert exc_info.value is error
    assert not _attempt_path(tmp_path).exists()


def test_typed_dependency_failure_survives_lease_loss_without_stale_cleanup(
    tmp_path: Path,
) -> None:
    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source, frame_count=1)
    size, digest = _source_facts(source)
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)
    descriptor = store.write_bytes("keep.bin", b"keep", "application/octet-stream")
    keep_path = _artifact_path(tmp_path, descriptor.storage_key)
    guard = _owned_guard()
    error = GpuOutOfMemoryError("fixture oom after lease loss")

    class FailingDetector:
        def detect(self, frame):
            guard.mark_lost()
            raise error

    processor = VideoProcessor(FailingDetector(), FixtureTracker({}), store)

    with pytest.raises(GpuOutOfMemoryError) as exc_info:
        _run(processor, source, size, digest, lease_guard=guard)

    assert exc_info.value is error
    assert keep_path.read_bytes() == b"keep"

def test_process_rejects_store_scoped_to_different_job_without_cleanup(tmp_path: Path) -> None:
    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source)
    size, digest = _source_facts(source)
    other_store = StagingArtifactStore(tmp_path, OTHER_JOB_ID, ATTEMPT)
    descriptor = other_store.write_bytes("keep.bin", b"keep", "application/octet-stream")
    keep_path = _artifact_path(tmp_path, descriptor.storage_key)
    processor = VideoProcessor(FixtureDetector({}), FixtureTracker({}), other_store)

    with pytest.raises(VideoProcessingError) as exc_info:
        _run(processor, source, size, digest)

    assert exc_info.value.code == "pipeline_configuration_invalid"
    assert keep_path.read_bytes() == b"keep"


def test_process_rejects_store_scoped_to_different_attempt_without_cleanup(tmp_path: Path) -> None:
    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source)
    size, digest = _source_facts(source)
    other_store = StagingArtifactStore(tmp_path, JOB_ID, 2)
    descriptor = other_store.write_bytes("keep.bin", b"keep", "application/octet-stream")
    keep_path = _artifact_path(tmp_path, descriptor.storage_key)
    processor = VideoProcessor(FixtureDetector({}), FixtureTracker({}), other_store)

    with pytest.raises(VideoProcessingError) as exc_info:
        _run(processor, source, size, digest, attempt=ATTEMPT)

    assert exc_info.value.code == "pipeline_configuration_invalid"
    assert keep_path.read_bytes() == b"keep"


def test_unsafe_tracker_id_is_rejected_before_artifact_creation(tmp_path: Path) -> None:
    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source, frame_count=1)
    size, digest = _source_facts(source)
    detections = {0: (_person(),)}
    processor = VideoProcessor(
        FixtureDetector(detections),
        FixtureTracker({(0, 0): "person/nested"}),
        StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT),
    )

    with pytest.raises(VideoProcessingError) as exc_info:
        _run(processor, source, size, digest)

    assert exc_info.value.code == "pipeline_processing_failed"
    assert not _attempt_path(tmp_path).exists()
