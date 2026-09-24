"""Evidence Set through the real VideoProcessor: staging, admission, failure, memory.

P1–P7 and M1–M5 of the S1.2 plan. Videos are textured (seeded noise) so that
real candidates pass the sharpness floor; the fixture tracker speaks only the
model-neutral ``TrackerUpdate`` contract.
"""

from __future__ import annotations

import gc
import tracemalloc
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
from mavi_vision.detection.interfaces import DetectionCandidate
from mavi_vision.evidence.encoder import EncodedImage, JpegLadderEncoder
from mavi_vision.evidence.errors import EvidenceError
from mavi_vision.evidence.quality import FrameContext, scorer_for_policy
from mavi_vision.evidence.roles import ROLE_ORDER, EvidenceRole
from mavi_vision.evidence.selector import EvidenceSelector
from mavi_vision.pipeline.process_video import VideoProcessingError, VideoProcessor
from mavi_vision.storage.artifact_store import StagingArtifactError, StagingArtifactStore
from mavi_vision.tracking.interfaces import TrackCandidate, TrackerUpdate
from mavi_vision.video.reader import DecodedFrame
from tests.profile_fixtures import PRODUCTION_EVIDENCE_POLICY as POLICY

JOB_ID = UUID("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761")
FPS = 10
REP, NEAR, EARLY, LATE = ROLE_ORDER


def _write_textured_mp4(path: Path, frame_count: int, *, width: int = 64, height: int = 48) -> tuple[int, str]:
    rng = np.random.default_rng(11)
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=FPS)
        stream.width = width
        stream.height = height
        stream.pix_fmt = "yuv420p"
        for _ in range(frame_count):
            image = rng.integers(0, 256, (height, width, 3), dtype=np.uint8)
            for packet in stream.encode(av.VideoFrame.from_ndarray(image, format="rgb24")):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    payload = path.read_bytes()
    return len(payload), sha256(payload).hexdigest()


def _guard() -> LeaseGuard:
    return LeaseGuard(datetime.now(timezone.utc) + timedelta(minutes=5))


def _box(frame_number: int, grow: float = 0.0, grow_after: int = 0) -> NormalizedBoundingBox:
    # A person drifting right; from ``grow_after`` on it approaches the camera.
    x = 0.05 + (frame_number % 40) * 0.01
    size = min(0.45, 0.2 + grow * max(0, frame_number - grow_after))
    return NormalizedBoundingBox(x, 0.1, size, size)


class Walker:
    """Detector + tracker pair: ``track_frames`` maps track id -> frames it is seen in."""

    def __init__(self, track_frames: dict[str, range], *, grow: float = 0.0, grow_after: int = 0, retire: dict[int, tuple[str, ...]] | None = None, on_frame=None) -> None:
        self.track_frames = track_frames
        self.grow = grow
        self.grow_after = grow_after
        self.retire = retire or {}
        self.on_frame = on_frame

    def detect(self, frame: DecodedFrame):
        if self.on_frame is not None:
            self.on_frame(frame)
        return tuple(
            DetectionCandidate(
                ObjectClass.PERSON,
                0.9,
                _box(frame.source_frame_number + 7 * index, self.grow, self.grow_after),
                frame_ordinal=index,
            )
            for index, (track_id, frames) in enumerate(self.track_frames.items())
            if frame.source_frame_number in frames
        )

    def update(self, frame: DecodedFrame, detections) -> TrackerUpdate:
        live = [t for t, frames in self.track_frames.items() if frame.source_frame_number in frames]
        return TrackerUpdate(
            candidates=tuple(
                TrackCandidate(track_id, d.object_class, d.confidence, d.bounding_box)
                for track_id, d in zip(live, detections, strict=True)
            ),
            retired_track_ids=self.retire.get(frame.source_frame_number, ()),
        )


def _run(tmp_path: Path, walker: Walker, frame_count: int, *, attempt: int = 1, guard: LeaseGuard | None = None, **options):
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / f"source-{attempt}.mp4"
    size, digest = _write_textured_mp4(source, frame_count)
    processor = VideoProcessor(
        walker, walker, StagingArtifactStore(tmp_path, JOB_ID, attempt), evidence_policy=POLICY, **options
    )
    return processor.process(
        job_id=JOB_ID,
        attempt_count=attempt,
        source_path=source,
        expected_source_size_bytes=size,
        expected_source_sha256=digest,
        lease_guard=guard or _guard(),
    )


def _attempt(root: Path, attempt: int = 1) -> Path:
    return root / "staging" / str(JOB_ID) / f"attempt-{attempt:04d}"


def _evidence_files(root: Path, attempt: int = 1) -> list[str]:
    directory = _attempt(root, attempt) / "evidence"
    return sorted(p.name for p in directory.iterdir()) if directory.exists() else []


# P ---------------------------------------------------------------------------------


def test_one_long_track_carries_all_four_roles_in_canonical_order(tmp_path: Path) -> None:
    result = _run(tmp_path, Walker({"person-a": range(0, 120)}, grow=0.01, grow_after=40), 120)

    (track,) = result.tracks
    assert [(o.rank, o.role) for o in track.observations] == [(0, REP), (1, NEAR), (2, EARLY), (3, LATE)]
    frames = [o.source_frame_number for o in track.observations]
    assert len(set(frames)) == 4
    early = track.observations[2]
    assert early.offset_ms - track.start_offset_ms <= POLICY.early_window_ms
    for observation in track.observations:
        path = tmp_path.joinpath(*observation.crop.storage_key.split("/"))
        assert path.read_bytes()[:2] == b"\xff\xd8"
        assert observation.crop.size_bytes == path.stat().st_size
        assert observation.crop.sha256 == sha256(path.read_bytes()).hexdigest()
    assert _evidence_files(tmp_path) == sorted(f"person-a-{role.value}.jpg" for role in ROLE_ORDER)
    assert not (_attempt(tmp_path) / "thumbnails").exists()
    for role in ROLE_ORDER:
        assert result.evidence_accounting.for_role(role).admitted == 1


def test_short_featureless_track_still_gets_a_fallback_representative(tmp_path: Path) -> None:
    # Every frame is at the frame edge (edge margin 0): no qualified candidate
    # ever, yet the accepted Track must have its Representative.
    class EdgeWalker(Walker):
        def detect(self, frame):
            return (DetectionCandidate(ObjectClass.PERSON, 0.9, NormalizedBoundingBox(0.0, 0.3, 0.3, 0.3)),)

    result = _run(tmp_path, EdgeWalker({"person-a": range(0, 30)}), 30)

    (track,) = result.tracks
    assert [o.role for o in track.observations] == [REP]
    assert _evidence_files(tmp_path) == ["person-a-representative.jpg"]


def test_evidence_is_staged_once_at_retirement_never_before(tmp_path: Path) -> None:
    """P1"""
    seen: dict[int, list[str]] = {}

    def observe(frame: DecodedFrame) -> None:
        seen[frame.source_frame_number] = _evidence_files(tmp_path)

    walker = Walker({"person-a": range(0, 40), "person-b": range(0, 70)}, retire={45: ("person-a",)}, on_frame=observe)
    writes: list[str] = []
    real_write = StagingArtifactStore.write_bytes

    def counting_write(self, relative_name, *args, **kwargs):
        writes.append(relative_name)
        return real_write(self, relative_name, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(StagingArtifactStore, "write_bytes", counting_write)
        result = _run(tmp_path, walker, 70)

    assert seen[45] == []  # retirement happens in frame 45's update ...
    assert seen[46] and all(name.startswith("person-a-") for name in seen[46])  # ... staged right after
    assert all(name.startswith("person-a-") for name in seen[69])  # person-b only at EOS
    # Each crop written exactly once.
    assert len(writes) == len(set(writes)) == sum(len(t.observations) for t in result.tracks)


def test_eos_finalises_live_tracks_and_retired_tracks_are_not_redone(tmp_path: Path) -> None:
    """P2"""
    result = _run(tmp_path, Walker({"person-a": range(0, 30), "person-b": range(5, 60)}, retire={35: ("person-a",)}), 60)

    assert [t.track_id for t in result.tracks] == ["person-a", "person-b"]
    assert result.evidence_accounting.representative.candidates == 2


def test_lease_lost_during_evidence_staging_publishes_nothing_further(tmp_path: Path) -> None:
    """P3: expire after the first crop write; later roles are never staged."""
    guard = _guard()
    real_write = StagingArtifactStore.write_bytes
    writes = 0

    def write_then_lose(self, relative_name, *args, **kwargs):
        nonlocal writes
        descriptor = real_write(self, relative_name, *args, **kwargs)
        writes += 1
        guard.mark_lost()
        return descriptor

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(StagingArtifactStore, "write_bytes", write_then_lose)
        with pytest.raises(LeaseLostError):
            _run(tmp_path, Walker({"person-a": range(0, 120)}, grow=0.01, grow_after=40), 120, guard=guard)

    assert writes == 1
    assert _evidence_files(tmp_path) == ["person-a-representative.jpg"]


def test_omitted_supplementals_are_removed_from_staging_and_absent_from_result(tmp_path: Path) -> None:
    """P4: a quota with room for the Representatives only."""
    first = _run(tmp_path / "full", Walker({"person-a": range(0, 120)}, grow=0.01, grow_after=40), 120)
    representative_bytes = first.tracks[0].observations[0].crop.size_bytes

    result = _run(
        tmp_path / "tight",
        Walker({"person-a": range(0, 120)}, grow=0.01, grow_after=40),
        120,
        evidence_quota_bytes=representative_bytes,
    )

    (track,) = result.tracks
    assert [o.role for o in track.observations] == [REP]
    assert _evidence_files(tmp_path / "tight") == ["person-a-representative.jpg"]
    accounting = result.evidence_accounting
    assert (accounting.near_view.candidates, accounting.near_view.omitted) == (1, 1)
    assert accounting.late_diverse.admitted == 0 and accounting.late_diverse.omitted == 1


def test_attempt_n_cleans_n_minus_one_including_its_evidence(tmp_path: Path) -> None:
    """P5"""
    guard = _guard()
    walker = Walker({"person-a": range(0, 20)}, retire={25: ("person-a",)}, on_frame=lambda f: f.source_frame_number == 30 and guard.mark_lost())
    with pytest.raises(LeaseLostError):
        _run(tmp_path, walker, 40, guard=guard)
    assert _evidence_files(tmp_path, 1)  # a lease-lost attempt deletes nothing

    _run(tmp_path, Walker({"person-a": range(0, 20)}), 20, attempt=2)

    assert not _attempt(tmp_path, 1).exists()
    staged = _evidence_files(tmp_path, 2)
    assert "person-a-representative.jpg" in staged
    assert all(name.startswith("person-a-") for name in staged)


def test_no_admissible_representative_fails_the_attempt_and_cleans_staging(tmp_path: Path) -> None:
    """P7: an encoder that never admits anything."""

    class NeverAdmits:
        version = "stub"

        def encode(self, crop, cap_bytes):
            return None

    with pytest.raises(VideoProcessingError, match="pipeline_processing_failed") as raised:
        _run(tmp_path, Walker({"person-a": range(0, 10)}), 10, evidence_encoder=NeverAdmits())

    assert isinstance(raised.value.__cause__, EvidenceError)
    assert raised.value.__cause__.code == "evidence_representative_missing"
    assert not _attempt(tmp_path).exists()


def test_track_beyond_the_contract_limit_fails_before_staging_it(tmp_path: Path, monkeypatch) -> None:
    """More Tracks than a completion can carry: fail closed at the first extra
    Track, so staging never grows for a result that could not be sent."""
    monkeypatch.setattr(process_video_module, "MAXIMUM_TRACKS_PER_RESULT", 2)
    staged: list[str] = []
    real_write = StagingArtifactStore.write_bytes

    def recording_write(self, name, *args, **kwargs):
        staged.append(name)
        return real_write(self, name, *args, **kwargs)

    monkeypatch.setattr(StagingArtifactStore, "write_bytes", recording_write)
    walker = Walker(
        {"person-a": range(0, 5), "person-b": range(0, 5), "person-c": range(3, 8)},
        retire={4: ("person-a", "person-b")},
    )

    with pytest.raises(VideoProcessingError, match="pipeline_processing_failed") as raised:
        _run(tmp_path, walker, 10)

    assert str(raised.value.__cause__) == "track_limit_exceeded"
    assert not any("person-c" in name for name in staged)
    assert not _attempt(tmp_path).exists()


def test_encoder_failure_fails_the_attempt_and_cleans_staging(tmp_path: Path) -> None:
    class Broken:
        version = "stub"

        def encode(self, crop, cap_bytes):
            raise OSError("codec exploded")

    with pytest.raises(VideoProcessingError, match="pipeline_processing_failed"):
        _run(tmp_path, Walker({"person-a": range(0, 10)}, retire={12: ("person-a",)}), 20, evidence_encoder=Broken())

    assert not _attempt(tmp_path).exists()


def test_staging_write_failure_fails_the_attempt_and_cleans_staging(tmp_path: Path) -> None:
    def refuse(self, relative_name, *args, **kwargs):
        raise StagingArtifactError("staging_write_failed")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(StagingArtifactStore, "write_bytes", refuse)
        with pytest.raises(VideoProcessingError, match="pipeline_processing_failed"):
            _run(tmp_path, Walker({"person-a": range(0, 10)}), 10)

    assert not _attempt(tmp_path).exists()


def test_result_observations_are_canonical_and_descriptor_only(tmp_path: Path) -> None:
    """P6 + M5: canonical order, and nothing reachable from the result holds image bytes."""
    result = _run(tmp_path, Walker({"person-b": range(0, 90), "person-a": range(10, 100)}, grow=0.002), 100)

    assert [t.track_id for t in result.tracks] == ["person-a", "person-b"]
    for track in result.tracks:
        assert [o.rank for o in track.observations] == list(range(len(track.observations)))
        assert track.observations[0].role is REP
    big = [item for item in _reachable(result) if isinstance(item, (bytes, bytearray)) and len(item) > 1024]
    assert big == []


def test_determinism_same_input_same_evidence(tmp_path: Path) -> None:
    first = _run(tmp_path / "a", Walker({"person-a": range(0, 120)}, grow=0.01, grow_after=40), 120)
    second = _run(tmp_path / "b", Walker({"person-a": range(0, 120)}, grow=0.01, grow_after=40), 120)

    def facts(result):
        return [
            (o.role, o.rank, o.source_frame_number, o.quality_micro, o.selection_micro, o.crop.sha256, o.crop.size_bytes)
            for t in result.tracks
            for o in t.observations
        ]

    assert facts(first) == facts(second)
    assert first.evidence_accounting == second.evidence_accounting


# M ---------------------------------------------------------------------------------


def _live_accumulators():
    gc.collect()
    return [item for item in gc.get_objects() if isinstance(item, process_video_module._TrackAccumulator)]


def test_live_track_state_holds_no_ndarray_and_at_most_four_images(tmp_path: Path) -> None:
    """M1 + M3, checked after every frame of a long Track."""
    violations: list[str] = []

    def inspect(frame: DecodedFrame) -> None:
        if frame.source_frame_number % 10:
            return
        for accumulator in _live_accumulators():
            reachable = _reachable(accumulator)
            if any(isinstance(item, np.ndarray) for item in reachable):
                violations.append(f"ndarray at frame {frame.source_frame_number}")
            images = [item for item in reachable if isinstance(item, EncodedImage)]
            if len(images) > 4 or sum(i.size_bytes for i in images) > 65536 + 3 * 163840:
                violations.append(f"images at frame {frame.source_frame_number}")

    _run(tmp_path, Walker({"person-a": range(0, 150), "person-b": range(20, 150)}, grow=0.002, on_frame=inspect), 150)

    assert violations == []


class FixedSizeEncoder:
    """Returns a fresh 100 KiB payload per admission (M2): memory growth would show."""

    version = "stub"

    def encode(self, crop, cap_bytes):
        return EncodedImage(bytes(min(cap_bytes, 100 * 1024)), crop.shape[1], crop.shape[0], 85, 0)


def _selector_run(frames: int) -> int:
    selector = EvidenceSelector(policy=POLICY, scorer=scorer_for_policy(POLICY), encoder=FixedSizeEncoder(), track_start_ms=0)
    image = np.random.default_rng(3).integers(0, 256, (48, 64, 3), dtype=np.uint8)
    gc.collect()
    tracemalloc.start()
    try:
        baseline = tracemalloc.get_traced_memory()[0]
        for number in range(frames):
            box = _box(number, 0.003)
            frame = DecodedFrame(number, number * 100, image)
            candidate = TrackCandidate("person-a", ObjectClass.PERSON, 0.9, box)
            selector.observe(FrameContext(frame, (DetectionCandidate(ObjectClass.PERSON, 0.9, box),)), candidate)
        gc.collect()
        retained = tracemalloc.get_traced_memory()[0] - baseline
    finally:
        tracemalloc.stop()
    assert len(selector.holders()) <= 4
    return retained


def test_evidence_memory_is_flat_with_track_duration() -> None:
    """M2: 60, 600 and 6,000 frames of one Track retain the same evidence bytes."""
    retained = {frames: _selector_run(frames) for frames in (60, 600, 6000)}

    assert max(retained.values()) <= 4 * 100 * 1024 + 64 * 1024, retained
    assert retained[6000] - retained[600] <= 64 * 1024, retained


def test_many_live_selectors_retain_only_their_holders() -> None:
    """M4-style: 1,000 live Tracks retain ≤ 4 images each, never a history."""
    image = np.random.default_rng(4).integers(0, 256, (48, 64, 3), dtype=np.uint8)
    selectors = [
        EvidenceSelector(policy=POLICY, scorer=scorer_for_policy(POLICY), encoder=JpegLadderEncoder(POLICY.encoder), track_start_ms=0)
        for _ in range(1000)
    ]
    for number in range(12):
        frame = DecodedFrame(number, number * 700, image)
        for index, selector in enumerate(selectors):
            box = _box(number + index, 0.0)
            selector.observe(
                FrameContext(frame, (DetectionCandidate(ObjectClass.PERSON, 0.9, box),)),
                TrackCandidate(f"person-{index}", ObjectClass.PERSON, 0.9, box),
            )

    for selector in selectors:
        reachable = _reachable(selector)
        assert not any(isinstance(item, np.ndarray) for item in reachable)
        assert len([item for item in reachable if isinstance(item, EncodedImage)]) <= 4


def _reachable(root: object) -> list[object]:
    import dataclasses

    seen: dict[int, object] = {}
    stack = [root]
    while stack:
        item = stack.pop()
        if id(item) in seen or isinstance(item, (type, int, float, str)) or item is None:
            continue
        seen[id(item)] = item
        if isinstance(item, (bytes, bytearray)):
            continue
        if dataclasses.is_dataclass(item) and not isinstance(item, type):
            stack.extend(getattr(item, f.name) for f in dataclasses.fields(item))
        for name in getattr(type(item), "__slots__", ()):
            if hasattr(item, name):
                stack.append(getattr(item, name))
        if isinstance(item, (tuple, list, set, frozenset)):
            stack.extend(item)
        elif isinstance(item, dict):
            stack.extend(item.keys())
            stack.extend(item.values())
    return list(seen.values())


# S1.4 Harness A: the declared frame-source seam -------------------------------


def test_frame_reader_defaults_to_the_real_decoder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # No reader means the module's ``iter_frames``, looked up when processing
    # starts, so production composition (and tests that patch it) is unchanged.
    import inspect

    assert inspect.signature(VideoProcessor.__init__).parameters["frame_reader"].default is None
    calls: list[object] = []

    def recording(stream):
        calls.append(stream)
        return iter(())

    monkeypatch.setattr(process_video_module, "iter_frames", recording)
    walker = Walker({})
    source = tmp_path / "source.bin"
    source.write_bytes(b"declared")
    result = VideoProcessor(walker, walker, StagingArtifactStore(tmp_path, JOB_ID, 1), evidence_policy=POLICY).process(
        job_id=JOB_ID, attempt_count=1, source_path=source,
        expected_source_size_bytes=source.stat().st_size,
        expected_source_sha256=sha256(source.read_bytes()).hexdigest(),
        lease_guard=_guard(),
    )
    assert len(calls) == 1 and result.frames_processed == 0


def test_a_substituted_frame_reader_feeds_the_real_pipeline(tmp_path: Path) -> None:
    # The source file is still opened and SHA-verified; only decoding is
    # replaced. Here the substitute ignores the stream and yields synthetic
    # frames, and the Track they carry is finalised through the real selector,
    # encoder and staging.
    rng = np.random.default_rng(5)
    frames = [
        DecodedFrame(source_frame_number=index, offset_ms=index * 100, image=rng.integers(0, 256, (48, 64, 3), dtype=np.uint8))
        for index in range(12)
    ]
    streams: list[object] = []

    def reader(stream):
        streams.append(stream)
        return iter(frames)

    walker = Walker({"synthetic-a": range(0, 12)})
    source = tmp_path / "placeholder.bin"
    source.write_bytes(b"not a video")
    processor = VideoProcessor(
        walker, walker, StagingArtifactStore(tmp_path, JOB_ID, 1), evidence_policy=POLICY, frame_reader=reader,
    )
    result = processor.process(
        job_id=JOB_ID, attempt_count=1, source_path=source,
        expected_source_size_bytes=source.stat().st_size,
        expected_source_sha256=sha256(source.read_bytes()).hexdigest(),
        lease_guard=_guard(),
    )

    assert len(streams) == 1 and hasattr(streams[0], "read")
    assert result.frames_processed == 12
    assert [track.track_id for track in result.tracks] == ["synthetic-a"]
    assert result.tracks[0].observations[0].crop.size_bytes > 0


def test_a_substituted_frame_reader_does_not_bypass_source_integrity(tmp_path: Path) -> None:
    called: list[bool] = []

    def reader(stream):
        called.append(True)
        return iter(())

    source = tmp_path / "placeholder.bin"
    source.write_bytes(b"not a video")
    walker = Walker({})
    processor = VideoProcessor(
        walker, walker, StagingArtifactStore(tmp_path, JOB_ID, 1), evidence_policy=POLICY, frame_reader=reader,
    )
    from mavi_vision.storage.integrity import SourceIntegrityError

    with pytest.raises(SourceIntegrityError, match="source_sha256_mismatch"):
        processor.process(
            job_id=JOB_ID, attempt_count=1, source_path=source,
            expected_source_size_bytes=source.stat().st_size,
            expected_source_sha256="0" * 64,
            lease_guard=_guard(),
        )
    assert called == []
