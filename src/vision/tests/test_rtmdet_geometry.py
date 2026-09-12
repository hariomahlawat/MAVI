from __future__ import annotations

from dataclasses import dataclass
from math import inf, nan
from types import MappingProxyType
import numpy as np
import pytest

from mavi_vision.common.analytical import ObjectClass
from mavi_vision.detection.rtmdet import RTMDetDetector
from mavi_vision.runtime.errors import InferenceContractError
from mavi_vision.runtime.interfaces import (
    PixelBoxXYXY,
    RawDetection,
    RuntimeMetadata,
)
from mavi_vision.runtime.profile import ByteTrackProfile, PipelineProfile
from mavi_vision.video.reader import DecodedFrame


VOCABULARY = ("person", "car", "motorcycle", "bus", "truck", "dog")


class FakeRuntime:
    def __init__(self, detections: tuple[object, ...]) -> None:
        self._detections = detections
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

    def infer(self, image_rgb: np.ndarray) -> tuple[object, ...]:
        del image_rgb
        return self._detections

    def close(self) -> None:
        return None


@dataclass
class UnsafeBox:
    x1: object
    y1: object
    x2: object
    y2: object


@dataclass
class UnsafeDetection:
    source_class: object
    confidence: object
    bounding_box: object


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


def _frame(*, width: int, height: int) -> DecodedFrame:
    return DecodedFrame(
        source_frame_number=0,
        offset_ms=0,
        image=np.zeros((height, width, 3), dtype=np.uint8),
    )


def _raw(
    xyxy: tuple[float, float, float, float],
    *,
    source_class: str = "person",
    confidence: float = 0.8,
) -> RawDetection:
    return RawDetection(
        source_class=source_class,
        confidence=confidence,
        bounding_box=PixelBoxXYXY(*xyxy),
    )


@pytest.mark.parametrize(
    ("xyxy", "expected"),
    [
        ((-10.0, 20.0, 40.0, 80.0), (0.0, 0.2, 0.2, 0.6)),
        ((160.0, 20.0, 220.0, 80.0), (0.8, 0.2, 0.2, 0.6)),
        ((20.0, -10.0, 80.0, 40.0), (0.1, 0.0, 0.3, 0.4)),
        ((20.0, 60.0, 80.0, 120.0), (0.1, 0.6, 0.3, 0.4)),
        ((-50.0, -50.0, 250.0, 150.0), (0.0, 0.0, 1.0, 1.0)),
    ],
)
def test_finite_overflow_clips_to_frame_bounds(
    xyxy: tuple[float, float, float, float],
    expected: tuple[float, float, float, float],
) -> None:
    output = RTMDetDetector(FakeRuntime((_raw(xyxy),)), _profile()).detect(
        _frame(width=200, height=100)
    )

    assert len(output) == 1
    bbox = output[0].bounding_box
    assert (bbox.x, bbox.y, bbox.width, bbox.height) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("width", "height", "xyxy", "expected"),
    [
        (101, 55, (0.5, 1.25, 100.25, 54.75), (0.5 / 101, 1.25 / 55, 99.75 / 101, 53.5 / 55)),
        (55, 101, (1.25, 0.5, 54.75, 100.25), (1.25 / 55, 0.5 / 101, 53.5 / 55, 99.75 / 101)),
        (200, 100, (10.125, 20.25, 10.625, 20.75), (10.125 / 200, 20.25 / 100, 0.5 / 200, 0.5 / 100)),
    ],
)
def test_fractional_boxes_normalize_without_quantization(
    width: int,
    height: int,
    xyxy: tuple[float, float, float, float],
    expected: tuple[float, float, float, float],
) -> None:
    output = RTMDetDetector(FakeRuntime((_raw(xyxy),)), _profile()).detect(
        _frame(width=width, height=height)
    )

    bbox = output[0].bounding_box
    assert (bbox.x, bbox.y, bbox.width, bbox.height) == pytest.approx(expected)


@pytest.mark.parametrize(
    "xyxy",
    [
        (-10.0, 10.0, -1.0, 20.0),
        (201.0, 10.0, 220.0, 20.0),
        (10.0, -20.0, 20.0, -1.0),
        (10.0, 101.0, 20.0, 120.0),
        (20.0, 20.0, 20.0, 40.0),
        (20.0, 20.0, 40.0, 20.0),
    ],
)
def test_zero_area_after_clipping_is_discarded(
    xyxy: tuple[float, float, float, float],
) -> None:
    output = RTMDetDetector(FakeRuntime((_raw(xyxy),)), _profile()).detect(
        _frame(width=200, height=100)
    )

    assert output == ()


@pytest.mark.parametrize(
    "xyxy",
    [
        (20.0, 10.0, 19.999, 20.0),
        (10.0, 20.0, 20.0, 19.999),
        (20.0, 20.0, 10.0, 10.0),
    ],
)
def test_inverted_xyxy_is_contract_failure(
    xyxy: tuple[float, float, float, float],
) -> None:
    with pytest.raises(InferenceContractError, match="raw_detection_bbox_inverted"):
        RTMDetDetector(FakeRuntime((_raw(xyxy),)), _profile()).detect(
            _frame(width=200, height=100)
        )


@pytest.mark.parametrize(
    "xyxy",
    [
        (nan, 0.0, 1.0, 1.0),
        (0.0, inf, 1.0, 1.0),
        (0.0, 0.0, -inf, 1.0),
        (0.0, 0.0, 1.0, nan),
    ],
)
def test_nonfinite_runtime_geometry_is_contract_failure(
    xyxy: tuple[float, float, float, float],
) -> None:
    malformed = UnsafeDetection(
        source_class="person",
        confidence=0.8,
        bounding_box=UnsafeBox(*xyxy),
    )

    with pytest.raises(InferenceContractError, match="raw_detection_bbox_non_finite"):
        RTMDetDetector(FakeRuntime((malformed,)), _profile()).detect(
            _frame(width=200, height=100)
        )


@pytest.mark.parametrize("confidence", [nan, inf, -inf, -0.01, 1.01])
def test_impossible_confidence_is_contract_failure(confidence: float) -> None:
    malformed = UnsafeDetection(
        source_class="person",
        confidence=confidence,
        bounding_box=UnsafeBox(1.0, 1.0, 2.0, 2.0),
    )

    with pytest.raises(InferenceContractError, match="raw_detection_confidence_invalid"):
        RTMDetDetector(FakeRuntime((malformed,)), _profile()).detect(
            _frame(width=200, height=100)
        )


def test_source_class_outside_runtime_vocabulary_is_contract_failure() -> None:
    malformed = UnsafeDetection(
        source_class="aircraft",
        confidence=0.8,
        bounding_box=UnsafeBox(1.0, 1.0, 2.0, 2.0),
    )

    with pytest.raises(InferenceContractError, match="raw_detection_vocabulary_violation"):
        RTMDetDetector(FakeRuntime((malformed,)), _profile()).detect(
            _frame(width=200, height=100)
        )


@pytest.mark.parametrize(
    "malformed",
    [
        None,
        UnsafeDetection("person", 0.8, None),
        UnsafeDetection("person", "high", UnsafeBox(1.0, 1.0, 2.0, 2.0)),
        UnsafeDetection(7, 0.8, UnsafeBox(1.0, 1.0, 2.0, 2.0)),
        UnsafeDetection("person", 0.8, UnsafeBox("left", 1.0, 2.0, 2.0)),
    ],
)
def test_malformed_runtime_output_is_contract_failure(malformed: object) -> None:
    with pytest.raises(InferenceContractError):
        RTMDetDetector(FakeRuntime((malformed,)), _profile()).detect(
            _frame(width=200, height=100)
        )


def test_tiny_positive_box_is_preserved() -> None:
    output = RTMDetDetector(
        FakeRuntime((_raw((10.0, 10.0, 10.000001, 10.000001)),)),
        _profile(),
    ).detect(_frame(width=200, height=100))

    assert len(output) == 1
    assert output[0].bounding_box.width > 0.0
    assert output[0].bounding_box.height > 0.0


@pytest.mark.parametrize(
    ("width", "height"),
    [
        (1, 1),
        (1919, 1079),
        (1079, 1919),
    ],
)
def test_valid_full_frame_box_normalizes_for_odd_and_portrait_dimensions(
    width: int,
    height: int,
) -> None:
    output = RTMDetDetector(
        FakeRuntime((_raw((0.0, 0.0, float(width), float(height))),)),
        _profile(),
    ).detect(_frame(width=width, height=height))

    bbox = output[0].bounding_box
    assert (bbox.x, bbox.y, bbox.width, bbox.height) == (0.0, 0.0, 1.0, 1.0)


def test_constructor_rejects_runtime_model_profile_mismatch() -> None:
    runtime = FakeRuntime(())
    runtime._metadata = RuntimeMetadata(
        backend="fake-rtmdet",
        model_id="different-model",
        device="cpu",
        versions={"fake-runtime": "1.0"},
        ordered_class_vocabulary=VOCABULARY,
    )

    with pytest.raises(InferenceContractError, match="runtime_model_profile_mismatch"):
        RTMDetDetector(runtime, _profile())


def test_constructor_rejects_profile_class_missing_from_runtime_vocabulary() -> None:
    runtime = FakeRuntime(())
    runtime._metadata = RuntimeMetadata(
        backend="fake-rtmdet",
        model_id="rtmdet-m-coco-phase1",
        device="cpu",
        versions={"fake-runtime": "1.0"},
        ordered_class_vocabulary=("person", "car"),
    )

    with pytest.raises(InferenceContractError, match="profile_runtime_vocabulary_mismatch"):
        RTMDetDetector(runtime, _profile())
