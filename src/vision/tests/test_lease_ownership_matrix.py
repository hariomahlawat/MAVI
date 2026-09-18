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
from mavi_vision.pipeline.process_video import VideoProcessor
from mavi_vision.storage.artifact_store import StagingArtifactStore
from mavi_vision.tracking.fixture import FixtureTracker
from mavi_vision.tracking.interfaces import TrackCandidate


JOB_ID = UUID("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761")
BASE = datetime(2026, 9, 10, 14, 30, tzinfo=timezone.utc)


def _write_tiny_mp4(path: Path) -> None:
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=10)
        stream.width = 32
        stream.height = 24
        stream.pix_fmt = "yuv420p"
        image = np.zeros((24, 32, 3), dtype=np.uint8)
        frame = av.VideoFrame.from_ndarray(image, format="rgb24")
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def _source_facts(path: Path) -> tuple[int, str]:
    payload = path.read_bytes()
    return len(payload), sha256(payload).hexdigest()


def _person() -> DetectionCandidate:
    return DetectionCandidate(
        ObjectClass.PERSON,
        0.9,
        NormalizedBoundingBox(0.20, 0.20, 0.40, 0.50),
    )


def _run(processor: VideoProcessor, source: Path, guard: LeaseGuard) -> None:
    size, digest = _source_facts(source)
    processor.process(
        job_id=JOB_ID,
        attempt_count=1,
        source_path=source,
        expected_source_size_bytes=size,
        expected_source_sha256=digest,
        lease_guard=guard,
    )


def test_deadline_expiry_during_decode_stops_before_detector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source)
    now = BASE
    guard = LeaseGuard(BASE + timedelta(seconds=1), now_utc=lambda: now)
    detector_called = False
    real_iter_frames = process_video_module.iter_frames

    class RecordingDetector:
        def detect(self, frame):
            nonlocal detector_called
            detector_called = True
            return ()

    def expire_during_decode(stream):
        nonlocal now
        for frame in real_iter_frames(stream):
            now = BASE + timedelta(seconds=2)
            yield frame

    monkeypatch.setattr(process_video_module, "iter_frames", expire_during_decode)
    processor = VideoProcessor(
        RecordingDetector(),
        FixtureTracker({}),
        StagingArtifactStore(tmp_path, JOB_ID, 1),
    )

    with pytest.raises(LeaseLostError, match="lease_lost"):
        _run(processor, source, guard)

    assert detector_called is False


def test_deadline_expiry_during_detector_stops_before_tracker(tmp_path: Path) -> None:
    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source)
    now = BASE
    guard = LeaseGuard(BASE + timedelta(seconds=1), now_utc=lambda: now)
    tracker_called = False

    class ExpiringDetector:
        def detect(self, frame):
            nonlocal now
            now = BASE + timedelta(seconds=2)
            return (_person(),)

    class RecordingTracker:
        def update(self, frame, detections):
            nonlocal tracker_called
            tracker_called = True
            return ()

    processor = VideoProcessor(
        ExpiringDetector(),
        RecordingTracker(),
        StagingArtifactStore(tmp_path, JOB_ID, 1),
    )

    with pytest.raises(LeaseLostError, match="lease_lost"):
        _run(processor, source, guard)

    assert tracker_called is False


def test_deadline_expiry_during_tracker_stops_before_finalization(tmp_path: Path) -> None:
    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source)
    now = BASE
    guard = LeaseGuard(BASE + timedelta(seconds=1), now_utc=lambda: now)

    class ExpiringTracker:
        def update(self, frame, detections):
            nonlocal now
            now = BASE + timedelta(seconds=2)
            return (
                TrackCandidate(
                    track_id="person-0001",
                    object_class=ObjectClass.PERSON,
                    confidence=0.9,
                    bounding_box=detections[0].bounding_box,
                ),
            )

    processor = VideoProcessor(
        FixtureDetector({0: (_person(),)}),
        ExpiringTracker(),
        StagingArtifactStore(tmp_path, JOB_ID, 1),
    )

    with pytest.raises(LeaseLostError, match="lease_lost"):
        _run(processor, source, guard)

    assert not (tmp_path / "staging" / str(JOB_ID) / "attempt-0001").exists()


def test_stale_attempt_cannot_alter_replacement_attempt_same_logical_artifact(
    tmp_path: Path,
) -> None:
    stale_store = StagingArtifactStore(tmp_path, JOB_ID, 1)
    replacement_store = StagingArtifactStore(tmp_path, JOB_ID, 2)
    stale_guard = LeaseGuard(BASE + timedelta(seconds=1), now_utc=lambda: BASE + timedelta(seconds=2))
    replacement_guard = LeaseGuard(BASE + timedelta(minutes=1), now_utc=lambda: BASE)
    relative_name = "thumbnails/person-0001.jpg"

    replacement = replacement_store.write_bytes(
        relative_name,
        b"replacement-attempt",
        "image/jpeg",
        authorize_publish=replacement_guard.check_owned,
    )
    replacement_path = tmp_path.joinpath(*replacement.storage_key.split("/"))

    with pytest.raises(LeaseLostError, match="lease_lost"):
        stale_store.write_bytes(
            relative_name,
            b"stale-attempt",
            "image/jpeg",
            authorize_publish=stale_guard.check_owned,
        )

    stale_path = tmp_path / "staging" / str(JOB_ID) / "attempt-0001" / relative_name
    assert not stale_path.exists()
    assert replacement_path.read_bytes() == b"replacement-attempt"
