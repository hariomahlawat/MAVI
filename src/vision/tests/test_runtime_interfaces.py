from __future__ import annotations

from math import inf, nan

import numpy as np
import pytest

from mavi_vision.runtime.interfaces import (
    DetectorRuntime,
    PixelBoxXYXY,
    RawDetection,
    RuntimeMetadata,
)


@pytest.mark.parametrize(
    "box",
    [
        (nan, 0.0, 1.0, 1.0),
        (0.0, inf, 1.0, 1.0),
        (0.0, 0.0, -inf, 1.0),
        (0.0, 0.0, 1.0, nan),
    ],
)
def test_pixel_box_rejects_non_finite_values(
    box: tuple[float, float, float, float],
) -> None:
    with pytest.raises(ValueError, match="raw_detection_bbox_non_finite"):
        PixelBoxXYXY(*box)


def test_pixel_box_allows_out_of_frame_and_inverted_raw_coordinates() -> None:
    outside = PixelBoxXYXY(-10.5, -2.0, 1925.0, 1088.0)
    inverted = PixelBoxXYXY(20.0, 30.0, 10.0, 5.0)

    assert outside.x1 == -10.5
    assert inverted.x2 == 10.0


@pytest.mark.parametrize("confidence", [-0.01, 1.01, nan, inf, -inf])
def test_raw_detection_rejects_invalid_confidence(confidence: float) -> None:
    with pytest.raises(ValueError, match="raw_detection_confidence_invalid"):
        RawDetection(
            source_class="person",
            confidence=confidence,
            bounding_box=PixelBoxXYXY(0.0, 0.0, 1.0, 1.0),
        )


@pytest.mark.parametrize("source_class", ["", " ", " person", "person "])
def test_raw_detection_requires_canonical_nonempty_source_class(
    source_class: str,
) -> None:
    with pytest.raises(ValueError, match="raw_detection_source_class_invalid"):
        RawDetection(
            source_class=source_class,
            confidence=0.5,
            bounding_box=PixelBoxXYXY(0.0, 0.0, 1.0, 1.0),
        )


def test_raw_detection_accepts_unit_interval_boundaries() -> None:
    box = PixelBoxXYXY(-1.0, 2.0, 3.0, 4.0)

    assert RawDetection("person", 0.0, box).confidence == 0.0
    assert RawDetection("person", 1.0, box).confidence == 1.0


def test_runtime_metadata_freezes_versions_and_vocabulary() -> None:
    versions = {"torch": "2.6.0", "mmdet": "3.3.0"}
    metadata = RuntimeMetadata(
        backend="mmdetection",
        model_id="rtmdet-m-coco-phase1",
        device="cpu",
        versions=versions,
        ordered_class_vocabulary=("person", "car"),
    )
    versions["torch"] = "tampered"

    assert metadata.versions["torch"] == "2.6.0"
    with pytest.raises(TypeError):
        metadata.versions["torch"] = "2.7.0"  # type: ignore[index]


@pytest.mark.parametrize(
    ("versions", "vocabulary", "message"),
    [
        ({}, ("person",), "runtime_versions_required"),
        ({"": "1"}, ("person",), "runtime_version_name_invalid"),
        ({"torch": ""}, ("person",), "runtime_version_value_invalid"),
        ({"torch": "2.6.0"}, (), "runtime_vocabulary_required"),
        (
            {"torch": "2.6.0"},
            ("person", "person"),
            "runtime_vocabulary_duplicate",
        ),
    ],
)
def test_runtime_metadata_rejects_invalid_identity(
    versions: dict[str, str],
    vocabulary: tuple[str, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        RuntimeMetadata(
            backend="mmdetection",
            model_id="model-a",
            device="cpu",
            versions=versions,
            ordered_class_vocabulary=vocabulary,
        )


def test_detector_runtime_protocol_is_structural() -> None:
    class FakeRuntime:
        @property
        def metadata(self) -> RuntimeMetadata:
            return RuntimeMetadata(
                backend="fake",
                model_id="model-a",
                device="cpu",
                versions={"fake": "1.0"},
                ordered_class_vocabulary=("person",),
            )

        def warmup(self) -> None:
            return None

        def infer(self, image_rgb: np.ndarray) -> tuple[RawDetection, ...]:
            assert image_rgb.dtype == np.uint8
            return ()

        def close(self) -> None:
            return None

    assert isinstance(FakeRuntime(), DetectorRuntime)
