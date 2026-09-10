from __future__ import annotations

import numpy as np
import pytest

from mavi_vision.common.analytical import NormalizedBoundingBox, ObjectClass
from mavi_vision.detection.fixture import FixtureDetector
from mavi_vision.detection.interfaces import DetectionCandidate
from mavi_vision.tracking.fixture import FixtureTracker, FixtureTrackerError
from mavi_vision.video.reader import DecodedFrame


def _frame(number: int) -> DecodedFrame:
    return DecodedFrame(number, number * 40, np.zeros((10, 10, 3), dtype=np.uint8))


def _person(confidence: float = 0.9) -> DetectionCandidate:
    return DetectionCandidate(
        ObjectClass.PERSON,
        confidence,
        NormalizedBoundingBox(0.1, 0.1, 0.2, 0.4),
    )


def test_fixture_detector_is_frame_number_indexed_and_deterministic() -> None:
    detections = {0: (_person(0.9),), 1: (_person(0.92),)}
    detector = FixtureDetector(detections)

    assert detector.detect(_frame(0)) == detections[0]
    assert detector.detect(_frame(0)) == detections[0]
    assert detector.detect(_frame(99)) == ()


def test_fixture_tracker_assigns_stable_ids_from_explicit_map() -> None:
    tracker = FixtureTracker({(0, 0): "person-0001", (1, 0): "person-0001"})

    first = tracker.update(_frame(0), (_person(0.9),))
    second = tracker.update(_frame(1), (_person(0.92),))

    assert first[0].track_id == "person-0001"
    assert second[0].track_id == "person-0001"
    assert second[0].object_class is ObjectClass.PERSON


def test_fixture_tracker_rejects_missing_association() -> None:
    tracker = FixtureTracker({})

    with pytest.raises(FixtureTrackerError, match="fixture_track_mapping_missing"):
        tracker.update(_frame(0), (_person(),))


def test_fixture_tracker_rejects_duplicate_track_mapping_within_frame() -> None:
    tracker = FixtureTracker({(0, 0): "person-0001", (0, 1): "person-0001"})

    with pytest.raises(FixtureTrackerError, match="fixture_track_mapping_duplicate"):
        tracker.update(_frame(0), (_person(), _person()))
