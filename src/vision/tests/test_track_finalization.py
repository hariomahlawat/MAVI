from __future__ import annotations

import numpy as np
import pytest

from mavi_vision.common.analytical import (
    NormalizedBoundingBox,
    ObjectClass,
    RepresentativeObservation,
    TrajectoryPoint,
)
from mavi_vision.pipeline.finalization import PreparedTrack, prepare_track
from mavi_vision.video.trajectory import deserialize_trajectory


def _representative() -> RepresentativeObservation:
    return RepresentativeObservation(
        offset_ms=40,
        source_frame_number=1,
        confidence=0.9,
        bounding_box=NormalizedBoundingBox(0.1, 0.1, 0.4, 0.5),
        quality_score=0.8,
    )


def test_prepare_track_is_deterministic_and_side_effect_free() -> None:
    crop = np.full((12, 10, 3), 120, dtype=np.uint8)
    trajectory = (
        TrajectoryPoint(0, 0.3, 0.4),
        TrajectoryPoint(40, 0.4, 0.4),
    )

    first = prepare_track(
        track_id="person-0001",
        object_class=ObjectClass.PERSON,
        start_offset_ms=0,
        end_offset_ms=40,
        confidence_sum=1.8,
        observation_count=2,
        representative=_representative(),
        representative_crop=crop,
        trajectory=trajectory,
    )
    second = prepare_track(
        track_id="person-0001",
        object_class=ObjectClass.PERSON,
        start_offset_ms=0,
        end_offset_ms=40,
        confidence_sum=1.8,
        observation_count=2,
        representative=_representative(),
        representative_crop=crop,
        trajectory=trajectory,
    )

    assert isinstance(first, PreparedTrack)
    assert first == second
    assert first.confidence == pytest.approx(0.9)
    assert first.thumbnail_payload.startswith(b"\xff\xd8")
    assert first.thumbnail_payload.endswith(b"\xff\xd9")
    assert deserialize_trajectory(first.trajectory_payload) == trajectory


def test_prepare_track_rejects_missing_observations() -> None:
    with pytest.raises(ValueError, match="track_observation_missing"):
        prepare_track(
            track_id="person-0001",
            object_class=ObjectClass.PERSON,
            start_offset_ms=0,
            end_offset_ms=0,
            confidence_sum=0.0,
            observation_count=0,
            representative=_representative(),
            representative_crop=np.ones((2, 2, 3), dtype=np.uint8),
            trajectory=(),
        )
