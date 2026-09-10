from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from uuid import UUID

import av
import numpy as np
import pytest

from mavi_vision.common.analytical import NormalizedBoundingBox, ObjectClass
from mavi_vision.detection.fixture import FixtureDetector
from mavi_vision.detection.interfaces import DetectionCandidate
from mavi_vision.pipeline.process_video import VideoProcessingError, VideoProcessor
from mavi_vision.storage.artifact_store import StagingArtifactStore
from mavi_vision.storage.integrity import SourceIntegrityError
from mavi_vision.tracking.fixture import FixtureTracker


JOB_ID = UUID("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761")
OTHER_JOB_ID = UUID("018fa7b6-2b31-7f42-9f33-9fd9f6fdd762")


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


def _processor(tmp_path: Path, detections: dict[int, tuple[DetectionCandidate, ...]]) -> VideoProcessor:
    associations = {
        (frame_number, index): "person-0001"
        for frame_number, items in detections.items()
        for index, _ in enumerate(items)
    }
    return VideoProcessor(
        FixtureDetector(detections),
        FixtureTracker(associations),
        StagingArtifactStore(tmp_path, JOB_ID),
    )


def _artifact_path(root: Path, storage_key: str) -> Path:
    return root.joinpath(*storage_key.split("/"))


def test_process_builds_one_deterministic_track_and_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source)
    size, digest = _source_facts(source)
    detections = {0: (_person(),), 1: (_person(),), 2: (_person(),)}
    processor = _processor(tmp_path, detections)

    result = processor.process(
        job_id=JOB_ID,
        source_path=source,
        expected_source_size_bytes=size,
        expected_source_sha256=digest,
    )

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
    assert "/thumbnails/" in track.thumbnail.storage_key
    assert "/trajectories/" in track.trajectory_artifact.storage_key
    assert track.thumbnail.size_bytes == thumbnail_path.stat().st_size
    assert track.thumbnail.sha256 == sha256(thumbnail_path.read_bytes()).hexdigest()
    assert track.trajectory_artifact.size_bytes == trajectory_path.stat().st_size
    assert track.trajectory_artifact.sha256 == sha256(trajectory_path.read_bytes()).hexdigest()


def test_process_zero_detections_returns_no_tracks_or_track_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source)
    size, digest = _source_facts(source)

    result = _processor(tmp_path, {}).process(
        job_id=JOB_ID,
        source_path=source,
        expected_source_size_bytes=size,
        expected_source_sha256=digest,
    )

    assert result.frames_processed == 3
    assert result.tracks == ()
    assert not (tmp_path / "staging" / str(JOB_ID)).exists()


def test_integrity_mismatch_cleans_job_staging(tmp_path: Path) -> None:
    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source)
    size, _ = _source_facts(source)
    store = StagingArtifactStore(tmp_path, JOB_ID)
    store.write_bytes("stale.bin", b"stale", "application/octet-stream")
    processor = VideoProcessor(FixtureDetector({}), FixtureTracker({}), store)

    with pytest.raises(SourceIntegrityError, match="source_sha256_mismatch"):
        processor.process(
            job_id=JOB_ID,
            source_path=source,
            expected_source_size_bytes=size,
            expected_source_sha256="0" * 64,
        )

    assert not (tmp_path / "staging" / str(JOB_ID)).exists()


def test_pre_cancelled_processor_preserves_existing_job_staging(tmp_path: Path) -> None:
    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source)
    size, digest = _source_facts(source)
    store = StagingArtifactStore(tmp_path, JOB_ID)
    descriptor = store.write_bytes("keep.bin", b"keep", "application/octet-stream")
    keep_path = _artifact_path(tmp_path, descriptor.storage_key)
    processor = VideoProcessor(FixtureDetector({}), FixtureTracker({}), store)

    with pytest.raises(VideoProcessingError) as exc_info:
        processor.process(
            job_id=JOB_ID,
            source_path=source,
            expected_source_size_bytes=size,
            expected_source_sha256=digest,
            cancel_requested=lambda: True,
        )

    assert exc_info.value.code == "lease_lost"
    assert keep_path.read_bytes() == b"keep"


def test_processing_failure_after_lease_loss_preserves_reclaimed_staging(tmp_path: Path) -> None:
    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source, frame_count=1)
    size, digest = _source_facts(source)
    store = StagingArtifactStore(tmp_path, JOB_ID)
    cancelled = False
    reclaimed_path: Path | None = None

    class FailingDetector:
        def detect(self, frame):
            nonlocal cancelled, reclaimed_path
            descriptor = store.write_bytes(
                "reclaimed/keep.bin",
                b"new-attempt",
                "application/octet-stream",
            )
            reclaimed_path = _artifact_path(tmp_path, descriptor.storage_key)
            cancelled = True
            raise RuntimeError("processing failure after lease loss")

    processor = VideoProcessor(FailingDetector(), FixtureTracker({}), store)

    with pytest.raises(VideoProcessingError) as exc_info:
        processor.process(
            job_id=JOB_ID,
            source_path=source,
            expected_source_size_bytes=size,
            expected_source_sha256=digest,
            cancel_requested=lambda: cancelled,
        )

    assert reclaimed_path is not None
    assert reclaimed_path.read_bytes() == b"new-attempt"
    assert exc_info.value.code == "lease_lost"


def test_lease_cancellation_during_source_snapshot_maps_to_lease_lost(tmp_path: Path) -> None:
    source = tmp_path / "large-source.mp4"
    source.write_bytes(b"x" * (2 * 1024 * 1024))
    size, digest = _source_facts(source)
    processor = _processor(tmp_path, {})
    checks = 0

    def cancel_requested() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 2

    with pytest.raises(VideoProcessingError) as exc_info:
        processor.process(
            job_id=JOB_ID,
            source_path=source,
            expected_source_size_bytes=size,
            expected_source_sha256=digest,
            cancel_requested=cancel_requested,
        )

    assert exc_info.value.code == "lease_lost"
    assert checks >= 2


def test_corrupt_video_maps_to_stable_error_and_cleans(tmp_path: Path) -> None:
    source = tmp_path / "corrupt.mp4"
    source.write_bytes(b"not-an-mp4")
    size, digest = _source_facts(source)
    store = StagingArtifactStore(tmp_path, JOB_ID)
    store.write_bytes("stale.bin", b"stale", "application/octet-stream")
    processor = VideoProcessor(FixtureDetector({}), FixtureTracker({}), store)

    with pytest.raises(VideoProcessingError) as exc_info:
        processor.process(
            job_id=JOB_ID,
            source_path=source,
            expected_source_size_bytes=size,
            expected_source_sha256=digest,
        )

    assert exc_info.value.code == "video_decode_failed"
    assert not (tmp_path / "staging" / str(JOB_ID)).exists()


def test_detector_failure_maps_to_pipeline_error_and_cleans(tmp_path: Path) -> None:
    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source)
    size, digest = _source_facts(source)
    store = StagingArtifactStore(tmp_path, JOB_ID)

    class FailingDetector:
        def detect(self, frame):
            raise RuntimeError("fixture failure")

    processor = VideoProcessor(FailingDetector(), FixtureTracker({}), store)

    with pytest.raises(VideoProcessingError) as exc_info:
        processor.process(
            job_id=JOB_ID,
            source_path=source,
            expected_source_size_bytes=size,
            expected_source_sha256=digest,
        )

    assert exc_info.value.code == "pipeline_processing_failed"
    assert not (tmp_path / "staging" / str(JOB_ID)).exists()


def test_process_rejects_artifact_store_scoped_to_different_job_without_cleanup(tmp_path: Path) -> None:
    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source)
    size, digest = _source_facts(source)
    other_store = StagingArtifactStore(tmp_path, OTHER_JOB_ID)
    descriptor = other_store.write_bytes("keep.bin", b"keep", "application/octet-stream")
    keep_path = _artifact_path(tmp_path, descriptor.storage_key)
    processor = VideoProcessor(FixtureDetector({}), FixtureTracker({}), other_store)

    with pytest.raises(VideoProcessingError) as exc_info:
        processor.process(
            job_id=JOB_ID,
            source_path=source,
            expected_source_size_bytes=size,
            expected_source_sha256=digest,
        )

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
        StagingArtifactStore(tmp_path, JOB_ID),
    )

    with pytest.raises(VideoProcessingError) as exc_info:
        processor.process(
            job_id=JOB_ID,
            source_path=source,
            expected_source_size_bytes=size,
            expected_source_sha256=digest,
        )

    assert exc_info.value.code == "pipeline_processing_failed"
    assert not (tmp_path / "staging" / str(JOB_ID)).exists()
