from __future__ import annotations

from itertools import permutations
from types import MappingProxyType
from typing import Sequence

import numpy as np

from mavi_vision.common.analytical import ObjectClass
from mavi_vision.detection.rtmdet import RTMDetDetector
from mavi_vision.runtime.interfaces import (
    PixelBoxXYXY,
    RawDetection,
    RuntimeMetadata,
)
from mavi_vision.runtime.profile import ByteTrackProfile, PipelineProfile
from mavi_vision.video.reader import DecodedFrame


VOCABULARY = (
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "bus",
    "truck",
    "dog",
)


class FakeRuntime:
    def __init__(self, detections: Sequence[RawDetection]) -> None:
        self._detections = tuple(detections)
        self.calls = 0
        self.images: list[np.ndarray] = []
        self._metadata = RuntimeMetadata(
            backend="fake-rtmdet",
            model_id="rtmdet-m-coco-phase1",
            device="cpu",
            versions={"fake-runtime": "1.0"},
            ordered_class_vocabulary=VOCABULARY,
        )

    @property
    def metadata(self) -> RuntimeMetadata:
        return self._metadata

    def warmup(self) -> None:
        return None

    def infer(self, image_rgb: np.ndarray) -> Sequence[RawDetection]:
        self.calls += 1
        self.images.append(image_rgb)
        return self._detections

    def close(self) -> None:
        return None


def _profile() -> PipelineProfile:
    return PipelineProfile(
        schema_version="1.0",
        profile_id="phase1-detection-tracking-v1",
        profile_version="1.0.0-candidate",
        model_id="rtmdet-m-coco-phase1",
        detector_inference_floor=0.05,
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
            track_activation_threshold=0.25,
            high_confidence_threshold=0.6,
            minimum_matching_threshold=0.8,
            minimum_consecutive_frames=1,
            lost_track_buffer_seconds=1.0,
        ),
        frame_policy="every-frame",
    )


def _frame(*, width: int = 200, height: int = 100) -> DecodedFrame:
    return DecodedFrame(
        source_frame_number=7,
        offset_ms=280,
        image=np.zeros((height, width, 3), dtype=np.uint8),
    )


def _raw(
    source_class: str,
    confidence: float,
    xyxy: tuple[float, float, float, float],
) -> RawDetection:
    return RawDetection(
        source_class=source_class,
        confidence=confidence,
        bounding_box=PixelBoxXYXY(*xyxy),
    )


def _serialize(detections: Sequence[object]) -> tuple[tuple[object, ...], ...]:
    serialized: list[tuple[object, ...]] = []
    for detection in detections:
        serialized.append(
            (
                detection.object_class.value,
                detection.confidence,
                detection.bounding_box.x,
                detection.bounding_box.y,
                detection.bounding_box.width,
                detection.bounding_box.height,
                detection.frame_ordinal,
            )
        )
    return tuple(serialized)


def test_phase1_mapping_is_profile_driven_and_ignores_other_valid_vocabulary() -> None:
    runtime = FakeRuntime(
        (
            _raw("person", 0.91, (10.0, 10.0, 30.0, 40.0)),
            _raw("car", 0.81, (40.0, 10.0, 70.0, 40.0)),
            _raw("motorcycle", 0.71, (80.0, 10.0, 100.0, 40.0)),
            _raw("bus", 0.61, (110.0, 10.0, 140.0, 40.0)),
            _raw("truck", 0.51, (150.0, 10.0, 180.0, 40.0)),
            _raw("dog", 0.99, (20.0, 50.0, 60.0, 90.0)),
        )
    )
    frame = _frame()

    output = RTMDetDetector(runtime, _profile()).detect(frame)

    assert runtime.calls == 1
    assert runtime.images == [frame.image]
    assert [candidate.object_class for candidate in output] == [
        ObjectClass.PERSON,
        ObjectClass.VEHICLE,
        ObjectClass.VEHICLE,
        ObjectClass.VEHICLE,
        ObjectClass.VEHICLE,
    ]
    assert [candidate.frame_ordinal for candidate in output] == [0, 1, 2, 3, 4]


def test_detector_calls_runtime_exactly_once_with_original_rgb_frame() -> None:
    runtime = FakeRuntime((_raw("person", 0.8, (10.0, 10.0, 20.0, 20.0)),))
    frame = _frame()
    detector = RTMDetDetector(runtime, _profile())

    detector.detect(frame)

    assert runtime.calls == 1
    assert len(runtime.images) == 1
    assert runtime.images[0] is frame.image


def test_canonical_order_is_independent_of_backend_permutation() -> None:
    raw = (
        _raw("truck", 0.74, (100.0, 20.0, 150.0, 70.0)),
        _raw("person", 0.60, (15.0, 15.0, 25.0, 35.0)),
        _raw("car", 0.92, (40.0, 30.0, 90.0, 80.0)),
        _raw("person", 0.95, (5.0, 10.0, 20.0, 30.0)),
    )
    frame = _frame()
    profile = _profile()

    outputs = {
        _serialize(RTMDetDetector(FakeRuntime(order), profile).detect(frame))
        for order in permutations(raw)
    }

    assert len(outputs) == 1
    (serialized,) = tuple(outputs)
    assert [row[-1] for row in serialized] == [0, 1, 2, 3]
    assert [row[0] for row in serialized] == [
        ObjectClass.PERSON.value,
        ObjectClass.PERSON.value,
        ObjectClass.VEHICLE.value,
        ObjectClass.VEHICLE.value,
    ]
    assert [row[1] for row in serialized] == [0.95, 0.60, 0.92, 0.74]


def test_adapter_does_not_add_nms_or_generic_detection_cap() -> None:
    raw = tuple(
        _raw(
            "car",
            0.5 + index / 1000.0,
            (20.0, 20.0, 80.0, 80.0),
        )
        for index in range(40)
    )

    output = RTMDetDetector(FakeRuntime(raw), _profile()).detect(_frame())

    assert len(output) == 40
    assert [candidate.frame_ordinal for candidate in output] == list(range(40))
