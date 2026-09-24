"""VideoProcessor Track lifecycle: retirement, end-of-stream and exactly-once.

These tests hold the consumer side of the ADR-013 §5 lifecycle contract. The
scripted tracker below speaks only the model-neutral ``TrackerUpdate`` contract,
so every assertion holds for any tracker implementation, not only ByteTrack.
"""

from __future__ import annotations

import gc
import os
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
from tests.profile_fixtures import PRODUCTION_EVIDENCE_POLICY


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
    trajectory_chunk_points: int | None = None,
):
    source = tmp_path / f"source-{job_id}-{attempt}.mp4"
    size, digest = _write_mp4(source, frame_count)
    options = (
        {}
        if trajectory_chunk_points is None
        else {"trajectory_chunk_points": trajectory_chunk_points}
    )
    processor = VideoProcessor(
        detector,
        tracker,
        StagingArtifactStore(tmp_path, job_id, attempt),
        **options,
        evidence_policy=PRODUCTION_EVIDENCE_POLICY,
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
    """The Track's staged Representative crop (the summary image)."""
    return _attempt_dir(root, attempt) / "evidence" / f"{track_id}-representative.jpg"


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

    def counting_publish(self, prepared, trajectory_chunks):
        counts[prepared.track_id] += 1
        return real_publish(self, prepared, trajectory_chunks)

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

    def recording_publish(self, prepared, trajectory_chunks):
        stages_at_publish.append(progress.reader.snapshot().stage)
        return real_publish(self, prepared, trajectory_chunks)

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
    assert "/attempt-0002/" in result.tracks[0].representative.crop.storage_key
    assert _thumbnail(tmp_path, "person-a", attempt=2).exists()
    assert tmp_path.joinpath(*other_job.storage_key.split("/")).read_bytes() == b"other-job"


# --- Trajectory spool (S1.2b) ------------------------------------------------


class _EveryFrame:
    """One person on every frame, drifting right, with an optional frame hook."""

    def __init__(self, on_frame=None) -> None:
        self._on_frame = on_frame

    def detect(self, frame: DecodedFrame):
        if self._on_frame is not None:
            self._on_frame(frame.source_frame_number)
        return (_person(0.1 + (frame.source_frame_number % 50) / 100.0),)


def _persistent(retire_at: int | None = None) -> ScriptedTracker:
    class Persistent(ScriptedTracker):
        def __init__(self) -> None:
            super().__init__({})

        def update(self, frame, detections):
            number = frame.source_frame_number
            if retire_at is not None and number >= retire_at:
                retired = ("person-a",) if number == retire_at else ()
                return TrackerUpdate(candidates=(), retired_track_ids=retired)
            return TrackerUpdate(
                candidates=tuple(
                    TrackCandidate("person-a", d.object_class, d.confidence, d.bounding_box)
                    for d in detections
                ),
                retired_track_ids=(),
            )

    return Persistent()


def _spool_path(root: Path, attempt: int = 1) -> Path:
    return _attempt_dir(root, attempt) / "spool" / "person-a.traj"


def _live_spools() -> list:
    gc.collect()
    return [
        item.trajectory
        for item in gc.get_objects()
        if isinstance(item, process_video_module._TrackAccumulator)
    ]


def test_spooled_trajectory_bytes_do_not_depend_on_chunk_size(tmp_path: Path) -> None:
    payloads = []
    for chunk_points in (1, 4, 4096):
        root = tmp_path / f"chunk-{chunk_points}"
        root.mkdir()
        result = _run(
            root, _EveryFrame(), _persistent(), frame_count=40,
            trajectory_chunk_points=chunk_points,
        )
        (track,) = result.tracks
        payload = _trajectory(root, "person-a").read_bytes()
        assert track.trajectory_artifact.size_bytes == len(payload)
        assert track.trajectory_artifact.sha256 == sha256(payload).hexdigest()
        assert len(deserialize_trajectory(payload)) == 40 == track.detection_count
        # Removed once published: only the published artefact remains.
        assert not _spool_path(root).exists()
        payloads.append(payload)

    assert payloads[0] == payloads[1] == payloads[2]


def test_live_track_state_stays_bounded_while_the_track_grows(tmp_path: Path) -> None:
    observed: list[tuple[int, int, int]] = []

    def observe(frame_number: int) -> None:
        if frame_number and frame_number % 5 == 0:
            (spool,) = _live_spools()
            points = sum(1 for item in gc.get_objects() if type(item).__name__ == "TrajectoryPoint")
            observed.append((spool.buffered_points, spool.spilled_points, points))

    result = _run(
        tmp_path, _EveryFrame(observe), _persistent(), frame_count=50,
        trajectory_chunk_points=4,
    )

    assert result.tracks[0].detection_count == 50
    # Never more than one chunk in memory, no point objects at all, and the
    # rest of the Track on disk.
    assert all(buffered < 4 and points == 0 for buffered, _, points in observed)
    assert [spilled for _, spilled, _ in observed] == [
        (n // 4) * 4 for n in range(5, 50, 5)
    ]
    assert not hasattr(result.tracks[0], "trajectory")


def test_spool_is_removed_at_retirement_mid_stream(tmp_path: Path) -> None:
    observed: dict[int, bool] = {}

    def observe(frame_number: int) -> None:
        observed[frame_number] = _spool_path(tmp_path).exists()

    _run(
        tmp_path, _EveryFrame(observe), _persistent(retire_at=12), frame_count=20,
        trajectory_chunk_points=4,
    )

    # Frames 0-11 carry the Track; the tracker retires it on frame 12.
    assert observed[11] is True  # spilled while live
    assert observed[13] is False  # removed right after the retirement publication
    assert _trajectory(tmp_path, "person-a").exists()


def test_lease_lost_mid_spool_publishes_nothing_and_next_attempt_removes_the_spool(
    tmp_path: Path,
) -> None:
    guard = _guard()

    def lose_at(frame_number: int) -> None:
        if frame_number == 10:
            guard.mark_lost()

    with pytest.raises(LeaseLostError):
        _run(
            tmp_path, _EveryFrame(lose_at), _persistent(), frame_count=20,
            lease_guard=guard, trajectory_chunk_points=3,
        )

    # The stale attempt deletes nothing and publishes no trajectory.
    assert _spool_path(tmp_path).stat().st_size == 9 * 24
    assert not _trajectory(tmp_path, "person-a").exists()

    result = _run(
        tmp_path, _EveryFrame(), _persistent(), frame_count=5, attempt=2,
        trajectory_chunk_points=3,
    )

    assert not _attempt_dir(tmp_path, 1).exists()
    assert result.tracks[0].detection_count == 5
    assert not _spool_path(tmp_path, attempt=2).exists()


def test_failed_attempt_cleanup_removes_live_spools(tmp_path: Path) -> None:
    def fail_at(frame_number: int) -> None:
        if frame_number == 15:
            raise RuntimeError("detector failed mid-track")

    with pytest.raises(VideoProcessingError, match="pipeline_processing_failed"):
        _run(
            tmp_path, _EveryFrame(fail_at), _persistent(), frame_count=20,
            trajectory_chunk_points=4,
        )

    assert not _attempt_dir(tmp_path).exists()


def test_corrupt_spool_fails_the_attempt_and_is_never_published(tmp_path: Path) -> None:
    def tamper(frame_number: int) -> None:
        if frame_number == 9:
            path = _spool_path(tmp_path)
            raw = bytearray(path.read_bytes())
            raw[3] ^= 0xFF  # a spilled offset, same length
            path.write_bytes(bytes(raw))

    with pytest.raises(VideoProcessingError, match="pipeline_processing_failed"):
        _run(
            tmp_path, _EveryFrame(tamper), _persistent(), frame_count=12,
            trajectory_chunk_points=4,
        )

    assert not _attempt_dir(tmp_path).exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor limit fixture")
def test_many_live_tracks_need_no_descriptor_each(tmp_path: Path) -> None:
    import resource

    live_tracks = 300
    source = tmp_path / "source.mp4"
    size, digest = _write_mp4(source, 3)

    class Crowd:
        def detect(self, frame):
            return tuple(
                DetectionCandidate(
                    ObjectClass.PERSON, 0.9,
                    NormalizedBoundingBox((i % 20) / 25.0, (i // 20) / 20.0, 0.02, 0.02),
                )
                for i in range(live_tracks)
            )

    class CrowdTracker:
        def update(self, frame, detections):
            return TrackerUpdate(
                candidates=tuple(
                    TrackCandidate(f"person-{i:04d}", d.object_class, d.confidence, d.bounding_box)
                    for i, d in enumerate(detections)
                ),
                retired_track_ids=(),
            )

    processor = VideoProcessor(
        Crowd(), CrowdTracker(), StagingArtifactStore(tmp_path, JOB_ID, 1),
        trajectory_chunk_points=1,
        evidence_policy=PRODUCTION_EVIDENCE_POLICY,
    )
    limits = resource.getrlimit(resource.RLIMIT_NOFILE)
    open_now = len(os.listdir("/proc/self/fd")) if os.path.isdir("/proc/self/fd") else 64
    resource.setrlimit(resource.RLIMIT_NOFILE, (open_now + 64, limits[1]))
    try:
        result = processor.process(
            job_id=JOB_ID,
            attempt_count=1,
            source_path=source,
            expected_source_size_bytes=size,
            expected_source_sha256=digest,
            lease_guard=_guard(),
        )
    finally:
        resource.setrlimit(resource.RLIMIT_NOFILE, limits)

    assert len(result.tracks) == live_tracks
    assert all(track.detection_count == 3 for track in result.tracks)
