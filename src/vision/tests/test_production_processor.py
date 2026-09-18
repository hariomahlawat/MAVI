from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from uuid import UUID

import av
import numpy as np
import pytest

import mavi_vision.pipeline.production_processor as production_module
from mavi_vision.common.analytical import (
    NormalizedBoundingBox,
    ObjectClass,
    VisionProcessingResult,
)
from mavi_vision.common.lease import LeaseGuard, LeaseLostError
from mavi_vision.detection.interfaces import DetectionCandidate
from mavi_vision.pipeline.process_video import VideoProcessingError
from mavi_vision.runtime.errors import (
    GpuOutOfMemoryError,
    GpuRuntimeError,
    InferenceContractError,
    TrackerError,
)
from mavi_vision.runtime.profile import ByteTrackProfile, PipelineProfile
from mavi_vision.storage.artifact_store import StagingArtifactError, StagingArtifactStore
from mavi_vision.storage.integrity import SourceIntegrityError
from mavi_vision.tracking.interfaces import TrackCandidate


JOB_ID = UUID("018fa7b6-2b31-7f42-9f33-9fd9f6fdd771")
BASE = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)


def _profile() -> PipelineProfile:
    return PipelineProfile(
        schema_version="1.0",
        profile_id="phase1-detection-tracking",
        profile_version="1.1.0-candidate",
        model_id="rtmdet-m-coco",
        detector_inference_floor=0.3,
        allowed_source_classes=("person", "car", "motorcycle", "bus", "truck"),
        class_mapping=MappingProxyType(
            {
                "person": ObjectClass.PERSON,
                "car": ObjectClass.VEHICLE,
                "motorcycle": ObjectClass.VEHICLE,
                "bus": ObjectClass.VEHICLE,
                "truck": ObjectClass.VEHICLE,
            }
        ),
        tracker=ByteTrackProfile(
            reference_frame_rate=30.0,
            track_activation_threshold=0.7,
            high_confidence_threshold=0.6,
            minimum_iou_threshold=0.1,
            minimum_consecutive_frames=2,
            lost_track_buffer_seconds=1.0,
        ),
        frame_policy="every-frame",
    )


def _guard() -> LeaseGuard:
    return LeaseGuard(BASE + timedelta(minutes=5), now_utc=lambda: BASE)


def _write_tiny_mp4(path: Path, frame_count: int = 2) -> None:
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=10)
        stream.width = 32
        stream.height = 24
        stream.pix_fmt = "yuv420p"
        for index in range(frame_count):
            image = np.full((24, 32, 3), 40 + index, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(image, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def _source_facts(path: Path) -> tuple[int, str]:
    from hashlib import sha256

    payload = path.read_bytes()
    return len(payload), sha256(payload).hexdigest()


def test_process_constructs_fresh_attempt_graph_in_exact_order_and_delegates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[tuple[object, ...]] = []
    runtime = object()
    detector_instances: list[object] = []
    tracker_instances: list[object] = []
    stores: list[object] = []
    processors: list[object] = []

    def runtime_provider():
        events.append(("runtime_provider",))
        return runtime

    class FakeDetector:
        def __init__(self, received_runtime, received_profile):
            events.append(("detector", received_runtime, received_profile))
            detector_instances.append(self)

    class FakeTracker:
        def __init__(self, tracker_profile):
            events.append(("tracker", tracker_profile))
            tracker_instances.append(self)

    def staging_factory(job_id, attempt_count):
        store = object()
        events.append(("staging", job_id, attempt_count, store))
        stores.append(store)
        return store

    class FakeVideoProcessor:
        def __init__(self, detector, tracker, store):
            events.append(("processor", detector, tracker, store))
            processors.append(self)

        def process(self, **kwargs):
            events.append(("process", kwargs))
            return VisionProcessingResult(
                job_id=kwargs["job_id"],
                frames_processed=kwargs["attempt_count"],
                tracks=(),
            )

    monkeypatch.setattr(production_module, "RTMDetDetector", FakeDetector, raising=False)
    monkeypatch.setattr(production_module, "ByteTrackTracker", FakeTracker, raising=False)
    monkeypatch.setattr(production_module, "VideoProcessor", FakeVideoProcessor, raising=False)

    processor = production_module.ProductionVisionProcessor(
        runtime_provider,
        _profile(),
        staging_factory,
        lambda error: pytest.fail(f"unexpected sink call: {error!r}"),
    )
    guard = _guard()
    source = tmp_path / "source.mp4"

    first = processor.process(
        job_id=JOB_ID,
        attempt_count=1,
        source_path=source,
        expected_source_size_bytes=11,
        expected_source_sha256="a" * 64,
        lease_guard=guard,
    )
    second = processor.process(
        job_id=JOB_ID,
        attempt_count=2,
        source_path=source,
        expected_source_size_bytes=22,
        expected_source_sha256="b" * 64,
        lease_guard=guard,
    )

    assert first.frames_processed == 1
    assert second.frames_processed == 2
    assert sum(event[0] == "runtime_provider" for event in events) == 2
    assert len(detector_instances) == len(set(map(id, detector_instances))) == 2
    assert len(tracker_instances) == len(set(map(id, tracker_instances))) == 2
    assert len(stores) == len(set(map(id, stores))) == 2
    assert len(processors) == len(set(map(id, processors))) == 2

    labels = [event[0] for event in events]
    assert labels == [
        "runtime_provider",
        "detector",
        "tracker",
        "staging",
        "processor",
        "process",
        "runtime_provider",
        "detector",
        "tracker",
        "staging",
        "processor",
        "process",
    ]
    process_events = [event[1] for event in events if event[0] == "process"]
    assert process_events[0]["source_path"] is source
    assert process_events[0]["expected_source_size_bytes"] == 11
    assert process_events[0]["expected_source_sha256"] == "a" * 64
    assert process_events[0]["lease_guard"] is guard
    assert process_events[1]["expected_source_size_bytes"] == 22
    assert process_events[1]["expected_source_sha256"] == "b" * 64


def test_pre_lost_lease_does_not_resolve_runtime_or_construct_attempt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def runtime_provider():
        calls.append("runtime")
        return object()

    def forbidden(*args, **kwargs):
        calls.append("constructor")
        pytest.fail("attempt-local constructor must not run after lease loss")

    monkeypatch.setattr(production_module, "RTMDetDetector", forbidden, raising=False)
    monkeypatch.setattr(production_module, "ByteTrackTracker", forbidden, raising=False)
    monkeypatch.setattr(production_module, "VideoProcessor", forbidden, raising=False)

    processor = production_module.ProductionVisionProcessor(
        runtime_provider,
        _profile(),
        lambda job_id, attempt: forbidden(),
        lambda error: calls.append("sink"),
    )
    guard = _guard()
    guard.mark_lost()

    with pytest.raises(LeaseLostError):
        processor.process(
            job_id=JOB_ID,
            attempt_count=1,
            source_path=tmp_path / "source.mp4",
            expected_source_size_bytes=1,
            expected_source_sha256="a" * 64,
            lease_guard=guard,
        )

    assert calls == []


def test_next_attempt_uses_replacement_runtime_from_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_a = object()
    runtime_b = object()
    current = [runtime_a]
    detector_runtimes: list[object] = []

    class FakeDetector:
        def __init__(self, runtime, profile):
            detector_runtimes.append(runtime)

    class FakeTracker:
        def __init__(self, profile):
            pass

    class FakeVideoProcessor:
        def __init__(self, detector, tracker, store):
            pass

        def process(self, **kwargs):
            return VisionProcessingResult(kwargs["job_id"], 0, ())

    monkeypatch.setattr(production_module, "RTMDetDetector", FakeDetector, raising=False)
    monkeypatch.setattr(production_module, "ByteTrackTracker", FakeTracker, raising=False)
    monkeypatch.setattr(production_module, "VideoProcessor", FakeVideoProcessor, raising=False)

    processor = production_module.ProductionVisionProcessor(
        lambda: current[0],
        _profile(),
        lambda job_id, attempt: object(),
        lambda error: pytest.fail(f"unexpected sink call: {error!r}"),
    )

    for attempt in (1, 2):
        if attempt == 2:
            current[0] = runtime_b
        processor.process(
            job_id=JOB_ID,
            attempt_count=attempt,
            source_path=tmp_path / "source.mp4",
            expected_source_size_bytes=0,
            expected_source_sha256="0" * 64,
            lease_guard=_guard(),
        )

    assert detector_runtimes == [runtime_a, runtime_b]


@pytest.mark.parametrize(
    "stage,error",
    [
        ("detector", InferenceContractError("detector construction")),
        ("tracker", TrackerError("tracker construction")),
    ],
)
def test_typed_construction_failure_notifies_once_and_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stage: str,
    error: Exception,
) -> None:
    calls: list[str] = []
    sink: list[Exception] = []

    class FakeDetector:
        def __init__(self, runtime, profile):
            calls.append("detector")
            if stage == "detector":
                raise error

    class FakeTracker:
        def __init__(self, profile):
            calls.append("tracker")
            if stage == "tracker":
                raise error

    def staging_factory(job_id, attempt):
        calls.append("staging")
        return object()

    class FakeVideoProcessor:
        def __init__(self, *args):
            calls.append("processor")

    monkeypatch.setattr(production_module, "RTMDetDetector", FakeDetector, raising=False)
    monkeypatch.setattr(production_module, "ByteTrackTracker", FakeTracker, raising=False)
    monkeypatch.setattr(production_module, "VideoProcessor", FakeVideoProcessor, raising=False)

    processor = production_module.ProductionVisionProcessor(
        lambda: object(),
        _profile(),
        staging_factory,
        sink.append,
    )

    with pytest.raises(type(error)) as exc_info:
        processor.process(
            job_id=JOB_ID,
            attempt_count=1,
            source_path=tmp_path / "source.mp4",
            expected_source_size_bytes=0,
            expected_source_sha256="0" * 64,
            lease_guard=_guard(),
        )

    assert exc_info.value is error
    assert sink == [error]
    if stage == "detector":
        assert calls == ["detector"]
    else:
        assert calls == ["detector", "tracker"]


@pytest.mark.parametrize(
    "error",
    [
        GpuOutOfMemoryError("oom"),
        GpuRuntimeError("gpu runtime"),
        InferenceContractError("contract"),
        TrackerError("tracker"),
    ],
)
def test_typed_processing_failure_notifies_exact_object_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    error: Exception,
) -> None:
    sink: list[Exception] = []

    class FakeDetector:
        def __init__(self, runtime, profile):
            pass

    class FakeTracker:
        def __init__(self, profile):
            pass

    class FakeVideoProcessor:
        def __init__(self, detector, tracker, store):
            pass

        def process(self, **kwargs):
            raise error

    monkeypatch.setattr(production_module, "RTMDetDetector", FakeDetector, raising=False)
    monkeypatch.setattr(production_module, "ByteTrackTracker", FakeTracker, raising=False)
    monkeypatch.setattr(production_module, "VideoProcessor", FakeVideoProcessor, raising=False)

    processor = production_module.ProductionVisionProcessor(
        lambda: object(),
        _profile(),
        lambda job_id, attempt: object(),
        sink.append,
    )

    with pytest.raises(type(error)) as exc_info:
        processor.process(
            job_id=JOB_ID,
            attempt_count=1,
            source_path=tmp_path / "source.mp4",
            expected_source_size_bytes=0,
            expected_source_sha256="0" * 64,
            lease_guard=_guard(),
        )

    assert exc_info.value is error
    assert sink == [error]


def test_typed_failure_is_reported_locally_even_if_lease_is_lost_during_unwind(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sink: list[Exception] = []
    guard = _guard()
    error = GpuOutOfMemoryError("oom while lease expires")

    class FakeDetector:
        def __init__(self, runtime, profile):
            pass

    class FakeTracker:
        def __init__(self, profile):
            pass

    class FakeVideoProcessor:
        def __init__(self, detector, tracker, store):
            pass

        def process(self, **kwargs):
            guard.mark_lost()
            raise error

    monkeypatch.setattr(production_module, "RTMDetDetector", FakeDetector, raising=False)
    monkeypatch.setattr(production_module, "ByteTrackTracker", FakeTracker, raising=False)
    monkeypatch.setattr(production_module, "VideoProcessor", FakeVideoProcessor, raising=False)

    processor = production_module.ProductionVisionProcessor(
        lambda: object(),
        _profile(),
        lambda job_id, attempt: object(),
        sink.append,
    )

    with pytest.raises(GpuOutOfMemoryError) as exc_info:
        processor.process(
            job_id=JOB_ID,
            attempt_count=1,
            source_path=tmp_path / "source.mp4",
            expected_source_size_bytes=0,
            expected_source_sha256="0" * 64,
            lease_guard=guard,
        )

    assert exc_info.value is error
    assert sink == [error]
    assert guard.is_lost()


@pytest.mark.parametrize(
    "error",
    [
        LeaseLostError(),
        SourceIntegrityError("source_media_integrity_failed"),
        VideoProcessingError("video_decode_failed"),
        RuntimeError("programming failure"),
    ],
)
def test_non_dependency_processing_failure_does_not_notify_sink(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    error: Exception,
) -> None:
    sink: list[Exception] = []

    class FakeDetector:
        def __init__(self, runtime, profile):
            pass

    class FakeTracker:
        def __init__(self, profile):
            pass

    class FakeVideoProcessor:
        def __init__(self, detector, tracker, store):
            pass

        def process(self, **kwargs):
            raise error

    monkeypatch.setattr(production_module, "RTMDetDetector", FakeDetector, raising=False)
    monkeypatch.setattr(production_module, "ByteTrackTracker", FakeTracker, raising=False)
    monkeypatch.setattr(production_module, "VideoProcessor", FakeVideoProcessor, raising=False)

    processor = production_module.ProductionVisionProcessor(
        lambda: object(),
        _profile(),
        lambda job_id, attempt: object(),
        sink.append,
    )

    with pytest.raises(type(error)) as exc_info:
        processor.process(
            job_id=JOB_ID,
            attempt_count=1,
            source_path=tmp_path / "source.mp4",
            expected_source_size_bytes=0,
            expected_source_sha256="0" * 64,
            lease_guard=_guard(),
        )

    assert exc_info.value is error
    assert sink == []


def test_staging_factory_failure_is_not_misclassified_as_runtime_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sink: list[Exception] = []
    error = StagingArtifactError("secure_staging_unavailable")

    class FakeDetector:
        def __init__(self, runtime, profile):
            pass

    class FakeTracker:
        def __init__(self, profile):
            pass

    monkeypatch.setattr(production_module, "RTMDetDetector", FakeDetector, raising=False)
    monkeypatch.setattr(production_module, "ByteTrackTracker", FakeTracker, raising=False)

    processor = production_module.ProductionVisionProcessor(
        lambda: object(),
        _profile(),
        lambda job_id, attempt: (_ for _ in ()).throw(error),
        sink.append,
    )

    with pytest.raises(StagingArtifactError) as exc_info:
        processor.process(
            job_id=JOB_ID,
            attempt_count=1,
            source_path=tmp_path / "source.mp4",
            expected_source_size_bytes=0,
            expected_source_sha256="0" * 64,
            lease_guard=_guard(),
        )

    assert exc_info.value is error
    assert sink == []


def test_real_video_processor_keeps_attempt_artifacts_and_tracker_state_isolated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source)
    size, digest = _source_facts(source)
    runtime = object()
    tracker_instances: list[object] = []

    class FakeDetector:
        def __init__(self, received_runtime, profile):
            assert received_runtime is runtime

        def detect(self, frame):
            return (
                DetectionCandidate(
                    object_class=ObjectClass.PERSON,
                    confidence=0.95,
                    bounding_box=NormalizedBoundingBox(0.2, 0.2, 0.4, 0.5),
                    frame_ordinal=0,
                ),
            )

    class FakeTracker:
        def __init__(self, profile):
            tracker_instances.append(self)

        def update(self, frame, detections):
            detection = tuple(detections)[0]
            return (
                TrackCandidate(
                    track_id="person-000001",
                    object_class=detection.object_class,
                    confidence=detection.confidence,
                    bounding_box=detection.bounding_box,
                ),
            )

    monkeypatch.setattr(production_module, "RTMDetDetector", FakeDetector, raising=False)
    monkeypatch.setattr(production_module, "ByteTrackTracker", FakeTracker, raising=False)

    processor = production_module.ProductionVisionProcessor(
        lambda: runtime,
        _profile(),
        lambda job_id, attempt: StagingArtifactStore(tmp_path, job_id, attempt),
        lambda error: pytest.fail(f"unexpected sink call: {error!r}"),
    )

    first = processor.process(
        job_id=JOB_ID,
        attempt_count=1,
        source_path=source,
        expected_source_size_bytes=size,
        expected_source_sha256=digest,
        lease_guard=_guard(),
    )
    second = processor.process(
        job_id=JOB_ID,
        attempt_count=2,
        source_path=source,
        expected_source_size_bytes=size,
        expected_source_sha256=digest,
        lease_guard=_guard(),
    )

    assert len(tracker_instances) == 2
    assert tracker_instances[0] is not tracker_instances[1]
    assert first.tracks[0].track_id == second.tracks[0].track_id == "person-000001"
    assert "/attempt-0001/" in first.tracks[0].thumbnail.storage_key
    assert "/attempt-0002/" in second.tracks[0].thumbnail.storage_key


def test_import_does_not_eagerly_load_optional_ml_packages() -> None:
    script = """
import sys
import mavi_vision.pipeline.production_processor
forbidden = ("torch", "mmdet", "mmcv", "trackers", "supervision")
loaded = [name for name in forbidden if name in sys.modules]
if loaded:
    raise SystemExit("eager-heavy-import:" + ",".join(loaded))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
