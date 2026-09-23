"""VideoProcessor Track lifecycle: retirement, end-of-stream and exactly-once.

These tests hold the consumer side of the ADR-013 §5 lifecycle contract. The
scripted tracker below speaks only the model-neutral ``TrackerUpdate`` contract,
so every assertion holds for any tracker implementation, not only ByteTrack.
"""

from __future__ import annotations

import gc
from collections import Counter
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
from mavi_vision.runtime.errors import TrackerError
from mavi_vision.runtime.progress import ProcessingProgress
from mavi_vision.storage.artifact_publisher import ArtifactPublisher
from mavi_vision.storage.artifact_store import StagingArtifactStore
from mavi_vision.tracking.fixture import FixtureTracker
from mavi_vision.tracking.interfaces import TrackCandidate, TrackerUpdate
from mavi_vision.video.reader import DecodedFrame
from mavi_vision.video.trajectory import deserialize_trajectory


JOB_ID = UUID("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761")
OTHER_JOB_ID = UUID("018fa7b6-2b31-7f42-9f33-9fd9f6fdd762")
BASE = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
FRAME_INTERVAL_MS = 100


def _write_mp4(path: Path, frame_count: int) -> tuple[int, str]:
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=10)
        stream.width = 32
        stream.height = 24
        stream.pix_fmt = "yuv420p"
        for index in range(frame_count):
            image = np.zeros((24, 32, 3), dtype=np.uint8)
            image[:, :, :] = 32 + index * 4
            for packet in stream.encode(av.VideoFrame.from_ndarray(image, format="rgb24")):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    payload = path.read_bytes()
    return len(payload), sha256(payload).hexdigest()


def _person(x: float = 0.2) -> DetectionCandidate:
    return DetectionCandidate(
        ObjectClass.PERSON,
        0.9,
        NormalizedBoundingBox(x, 0.2, 0.3, 0.5),
    )


def _vehicle() -> DetectionCandidate:
    return DetectionCandidate(
        ObjectClass.VEHICLE,
        0.8,
        NormalizedBoundingBox(0.5, 0.5, 0.3, 0.3),
    )


class ScriptedTracker:
    """A contract-level tracker: per frame, ids for each detection plus retirements.

    It deliberately does not enforce the cross-update contract, so tests can
    prove that the consumer does.
    """

    def __init__(
        self,
        ids: dict[int, tuple[str, ...]],
        retirements: dict[int, tuple[str, ...]] | None = None,
    ) -> None:
        self._ids = ids
        self._retirements = retirements or {}

    def update(self, frame: DecodedFrame, detections) -> TrackerUpdate:
        track_ids = self._ids.get(frame.source_frame_number, ())
        candidates = tuple(
            TrackCandidate(
                track_id=track_id,
                object_class=detection.object_class,
                confidence=detection.confidence,
                bounding_box=detection.bounding_box,
            )
            for track_id, detection in zip(track_ids, detections, strict=True)
        )
        return TrackerUpdate(
            candidates=candidates,
            retired_track_ids=self._retirements.get(frame.source_frame_number, ()),
        )


class SpyDetector:
    """Fixture detections plus an optional per-frame observation hook."""

    def __init__(self, detections, on_frame=None) -> None:
        self._inner = FixtureDetector(detections)
        self._on_frame = on_frame

    def detect(self, frame: DecodedFrame):
        if self._on_frame is not None:
            self._on_frame(frame.source_frame_number)
        return self._inner.detect(frame)


def _guard() -> LeaseGuard:
    return LeaseGuard(datetime.now(timezone.utc) + timedelta(minutes=5))


def _run(
    tmp_path: Path,
    detector,
    tracker,
    frame_count: int,
    *,
    attempt: int = 1,
    job_id: UUID = JOB_ID,
    lease_guard: LeaseGuard | None = None,
    progress_sink=None,
):
    source = tmp_path / f"source-{job_id}-{attempt}.mp4"
    size, digest = _write_mp4(source, frame_count)
    processor = VideoProcessor(
        detector,
        tracker,
        StagingArtifactStore(tmp_path, job_id, attempt),
    )
    return processor.process(
        job_id=job_id,
        attempt_count=attempt,
        source_path=source,
        expected_source_size_bytes=size,
        expected_source_sha256=digest,
        lease_guard=lease_guard or _guard(),
        progress_sink=progress_sink,
    )


def _attempt_dir(root: Path, attempt: int = 1, job_id: UUID = JOB_ID) -> Path:
    return root / "staging" / str(job_id) / f"attempt-{attempt:04d}"


def _thumbnail(root: Path, track_id: str, attempt: int = 1) -> Path:
    return _attempt_dir(root, attempt) / "thumbnails" / f"{track_id}.jpg"


def _trajectory(root: Path, track_id: str, attempt: int = 1) -> Path:
    return _attempt_dir(root, attempt) / "trajectories" / f"{track_id}.msgpack"


def _live_accumulators() -> int:
    gc.collect()
    return sum(
        1
        for item in gc.get_objects()
        if isinstance(item, process_video_module._TrackAccumulator)
    )


@pytest.fixture
def publish_counts(monkeypatch: pytest.MonkeyPatch) -> Counter:
    counts: Counter = Counter()
    real_publish = ArtifactPublisher.publish_track

    def counting_publish(self, prepared):
        counts[prepared.track_id] += 1
        return real_publish(self, prepared)

    monkeypatch.setattr(ArtifactPublisher, "publish_track", counting_publish)
    return counts


# --- Retirement-time finalisation ---------------------------------------------


def test_retired_track_is_staged_whole_before_the_stream_ends(tmp_path: Path) -> None:
    observed: dict[int, dict[str, object]] = {}

    def observe(frame_number: int) -> None:
        a_trajectory = _trajectory(tmp_path, "person-a")
        observed[frame_number] = {
            "a_thumbnail": _thumbnail(tmp_path, "person-a").exists(),
            "a_points": (
                len(deserialize_trajectory(a_trajectory.read_bytes()))
                if a_trajectory.exists()
                else None
            ),
            "b_staged": _trajectory(tmp_path, "person-b").exists(),
        }

    detections = {
        0: (_person(0.1), _person(0.5)),
        1: (_person(0.1), _person(0.5)),
        2: (_person(0.5),),
        3: (_person(0.5),),
        4: (_person(0.5),),
    }
    tracker = FixtureTracker(
        {
            (0, 0): "person-a",
            (0, 1): "person-b",
            (1, 0): "person-a",
            (1, 1): "person-b",
            (2, 0): "person-b",
            (3, 0): "person-b",
            (4, 0): "person-b",
        },
        retirements={3: ("person-a",)},
    )

    result = _run(tmp_path, SpyDetector(detections, observe), tracker, frame_count=5)

    # Not staged while live, even while unmatched (frame 2 and 3's detector runs
    # before that frame's retirement).
    assert observed[3] == {"a_thumbnail": False, "a_points": None, "b_staged": False}
    # Staged whole, with its complete trajectory, the frame after retirement,
    # while the other Track is still live and unstaged.
    assert observed[4] == {"a_thumbnail": True, "a_points": 2, "b_staged": False}
    assert [track.track_id for track in result.tracks] == ["person-a", "person-b"]
    track_a, track_b = result.tracks
    assert (track_a.detection_count, track_a.start_offset_ms, track_a.end_offset_ms) == (
        2,
        0,
        FRAME_INTERVAL_MS,
    )
    assert track_b.detection_count == 5
    assert _trajectory(tmp_path, "person-b").exists()


def test_retirement_releases_live_track_state(tmp_path: Path) -> None:
    samples: dict[int, int] = {}
    detections = {
        frame: (_person(0.1), _person(0.5)) for frame in range(3)
    } | {frame: (_person(0.5),) for frame in range(3, 6)}
    associations = {
        (frame, index): track_id
        for frame in range(3)
        for index, track_id in enumerate(("person-a", "person-b"))
    } | {(frame, 0): "person-b" for frame in range(3, 6)}

    def sample(frame_number: int) -> None:
        samples[frame_number] = _live_accumulators()

    baseline = _live_accumulators()
    _run(
        tmp_path,
        SpyDetector(detections, sample),
        FixtureTracker(associations, retirements={3: ("person-a",)}),
        frame_count=6,
    )

    assert samples[1] - baseline == 2
    # After person-a retires at frame 3, only person-b's live state remains.
    assert samples[4] - baseline == 1
    assert samples[5] - baseline == 1
    assert _live_accumulators() == baseline


def test_temporarily_lost_track_is_reacquired_not_split(
    tmp_path: Path, publish_counts: Counter
) -> None:
    detections = {0: (_person(),), 3: (_person(),), 4: (_person(),)}
    tracker = FixtureTracker(
        {(0, 0): "person-a", (3, 0): "person-a", (4, 0): "person-a"}
    )

    result = _run(tmp_path, FixtureDetector(detections), tracker, frame_count=6)

    assert len(result.tracks) == 1
    track = result.tracks[0]
    assert track.detection_count == 3
    assert (track.start_offset_ms, track.end_offset_ms) == (0, 4 * FRAME_INTERVAL_MS)
    points = deserialize_trajectory(_trajectory(tmp_path, "person-a").read_bytes())
    assert [point.offset_ms for point in points] == [0, 300, 400]
    assert publish_counts == Counter({"person-a": 1})


def test_tracks_retired_at_different_times_are_each_finalised_once(
    tmp_path: Path, publish_counts: Counter
) -> None:
    detections = {
        0: (_person(0.1), _person(0.5), _vehicle()),
        1: (_person(0.5), _vehicle()),
        2: (_vehicle(),),
    }
    tracker = FixtureTracker(
        {
            (0, 0): "person-c",
            (0, 1): "person-a",
            (0, 2): "vehicle-b",
            (1, 0): "person-a",
            (1, 1): "vehicle-b",
            (2, 0): "vehicle-b",
        },
        # Retirement order differs from canonical order; one Track stays live
        # until end-of-stream.
        retirements={2: ("person-c",), 4: ("person-a",)},
    )

    result = _run(tmp_path, FixtureDetector(detections), tracker, frame_count=6)

    assert [track.track_id for track in result.tracks] == [
        "person-a",
        "person-c",
        "vehicle-b",
    ]
    assert [track.detection_count for track in result.tracks] == [2, 1, 3]
    assert publish_counts == Counter({"person-a": 1, "person-c": 1, "vehicle-b": 1})


def test_one_sample_track_retired_mid_stream(tmp_path: Path) -> None:
    tracker = FixtureTracker({(1, 0): "person-a"}, retirements={2: ("person-a",)})

    result = _run(
        tmp_path, FixtureDetector({1: (_person(),)}), tracker, frame_count=4
    )

    (track,) = result.tracks
    assert track.detection_count == 1
    assert track.start_offset_ms == track.end_offset_ms == FRAME_INTERVAL_MS
    assert track.representative.offset_ms == FRAME_INTERVAL_MS
    points = deserialize_trajectory(_trajectory(tmp_path, "person-a").read_bytes())
    assert [point.offset_ms for point in points] == [FRAME_INTERVAL_MS]


def test_track_retired_in_the_final_frame_is_not_drained_again(
    tmp_path: Path, publish_counts: Counter
) -> None:
    tracker = FixtureTracker({(0, 0): "person-a"}, retirements={2: ("person-a",)})

    result = _run(
        tmp_path, FixtureDetector({0: (_person(),)}), tracker, frame_count=3
    )

    assert [track.track_id for track in result.tracks] == ["person-a"]
    assert publish_counts == Counter({"person-a": 1})


# --- End-of-stream ------------------------------------------------------------


def test_end_of_stream_drains_every_live_track_once(
    tmp_path: Path, publish_counts: Counter
) -> None:
    progress = ProcessingProgress(source_duration_ms=300)
    stages_at_publish: list[str] = []
    real_publish = ArtifactPublisher.publish_track

    def recording_publish(self, prepared):
        stages_at_publish.append(progress.reader.snapshot().stage)
        return real_publish(self, prepared)

    detections = {0: (_person(0.1), _person(0.5)), 1: (_person(0.1),)}
    tracker = FixtureTracker(
        {(0, 0): "person-b", (0, 1): "person-a", (1, 0): "person-b"}
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ArtifactPublisher, "publish_track", recording_publish)
        result = _run(
            tmp_path,
            FixtureDetector(detections),
            tracker,
            frame_count=3,
            progress_sink=progress.sink,
        )

    assert [track.track_id for track in result.tracks] == ["person-a", "person-b"]
    # End-of-stream Tracks are finalised after the finalisation boundary.
    assert stages_at_publish == ["finalizing", "finalizing"]
    assert progress.reader.snapshot().frames_processed == 3


def test_mid_stream_retirement_does_not_enter_the_finalisation_stage(
    tmp_path: Path,
) -> None:
    progress = ProcessingProgress(source_duration_ms=400)
    stages: dict[int, str] = {}

    def observe(frame_number: int) -> None:
        stages[frame_number] = progress.reader.snapshot().stage

    tracker = FixtureTracker({(0, 0): "person-a"}, retirements={1: ("person-a",)})
    _run(
        tmp_path,
        SpyDetector({0: (_person(),)}, observe),
        tracker,
        frame_count=4,
        progress_sink=progress.sink,
    )

    assert _thumbnail(tmp_path, "person-a").exists()
    assert "finalizing" not in stages.values()
    assert progress.reader.snapshot().stage == "finalizing"


def test_empty_stream_finalises_nothing(
    tmp_path: Path, publish_counts: Counter
) -> None:
    result = _run(tmp_path, FixtureDetector({}), FixtureTracker({}), frame_count=3)

    assert result.frames_processed == 3
    assert result.tracks == ()
    assert publish_counts == Counter()
    assert not _attempt_dir(tmp_path).exists()


# --- Consumer-side enforcement of the cross-update contract -------------------


@pytest.mark.parametrize(
    ("ids", "retirements", "code"),
    [
        # A retired id emitted again would otherwise be finalised twice.
        (
            {0: ("person-a",), 2: ("person-a",)},
            {1: ("person-a",)},
            "tracker_track_reappeared_after_retirement",
        ),
        # Retired twice.
        (
            {0: ("person-a",)},
            {1: ("person-a",), 2: ("person-a",)},
            "tracker_retired_unknown_track",
        ),
        # Retired without ever having been live.
        ({}, {1: ("person-z",)}, "tracker_retired_unknown_track"),
    ],
)
def test_cross_update_contract_violation_fails_the_attempt_and_cleans_staging(
    tmp_path: Path, ids, retirements, code
) -> None:
    detections = {frame: (_person(),) for frame in ids}

    with pytest.raises(TrackerError, match=code):
        _run(
            tmp_path,
            FixtureDetector(detections),
            ScriptedTracker(ids, retirements),
            frame_count=4,
        )

    # Tracks already finalised by the failed attempt do not survive it.
    assert not _attempt_dir(tmp_path).exists()


def test_non_update_tracker_output_fails_as_tracker_error(tmp_path: Path) -> None:
    class LegacyTracker:
        def update(self, frame, detections):
            return ()

    with pytest.raises(TrackerError, match="tracker_update_invalid"):
        _run(tmp_path, FixtureDetector({}), LegacyTracker(), frame_count=1)


def test_failure_after_mid_stream_finalisation_removes_staged_tracks(
    tmp_path: Path,
) -> None:
    class FailingLater:
        def __init__(self) -> None:
            self._inner = FixtureDetector({0: (_person(),)})

        def detect(self, frame):
            if frame.source_frame_number == 3:
                assert _thumbnail(tmp_path, "person-a").exists()
                raise RuntimeError("detector failed after retirement")
            return self._inner.detect(frame)

    tracker = FixtureTracker({(0, 0): "person-a"}, retirements={1: ("person-a",)})

    with pytest.raises(VideoProcessingError, match="pipeline_processing_failed"):
        _run(tmp_path, FailingLater(), tracker, frame_count=5)

    assert not _attempt_dir(tmp_path).exists()


# --- Lease authority ----------------------------------------------------------


def test_lease_lost_during_retirement_staging_publishes_nothing_further(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = BASE
    guard = LeaseGuard(BASE + timedelta(seconds=1), now_utc=lambda: now)
    real_prepare = process_video_module.prepare_track
    progress = ProcessingProgress(source_duration_ms=400)

    def prepare_then_expire(**kwargs):
        nonlocal now
        prepared = real_prepare(**kwargs)
        now = BASE + timedelta(seconds=2)
        return prepared

    monkeypatch.setattr(process_video_module, "prepare_track", prepare_then_expire)
    tracker = FixtureTracker({(0, 0): "person-a"}, retirements={1: ("person-a",)})

    with pytest.raises(LeaseLostError, match="lease_lost"):
        _run(
            tmp_path,
            FixtureDetector({0: (_person(),)}),
            tracker,
            frame_count=4,
            lease_guard=guard,
            progress_sink=progress.sink,
        )

    # Nothing is staged after the lease is lost, and the retiring frame is not
    # counted as progress.
    assert not _thumbnail(tmp_path, "person-a").exists()
    assert progress.reader.snapshot().frames_processed == 1


def test_next_attempt_removes_staging_left_by_a_lease_lost_attempt(
    tmp_path: Path,
) -> None:
    guard = _guard()

    class LoseLeaseAfterRetirement:
        def __init__(self) -> None:
            self._inner = FixtureDetector({0: (_person(),)})

        def detect(self, frame):
            if frame.source_frame_number == 2:
                guard.mark_lost()
            return self._inner.detect(frame)

    with pytest.raises(LeaseLostError):
        _run(
            tmp_path,
            LoseLeaseAfterRetirement(),
            FixtureTracker({(0, 0): "person-a"}, retirements={1: ("person-a",)}),
            frame_count=4,
            lease_guard=guard,
        )
    # A lease-lost attempt may not delete anything; its staging survives it.
    assert _thumbnail(tmp_path, "person-a", attempt=1).exists()
    other_job = StagingArtifactStore(tmp_path, OTHER_JOB_ID, 1).write_bytes(
        "keep.bin", b"other-job", "application/octet-stream"
    )

    # The same Track id is scoped to the attempt: the retry reuses it without
    # colliding with, or inheriting, the superseded attempt's evidence.
    result = _run(
        tmp_path,
        FixtureDetector({0: (_person(),)}),
        FixtureTracker({(0, 0): "person-a"}),
        frame_count=2,
        attempt=2,
    )

    assert not _attempt_dir(tmp_path, attempt=1).exists()
    assert "/attempt-0002/" in result.tracks[0].thumbnail.storage_key
    assert _thumbnail(tmp_path, "person-a", attempt=2).exists()
    assert tmp_path.joinpath(*other_job.storage_key.split("/")).read_bytes() == b"other-job"
