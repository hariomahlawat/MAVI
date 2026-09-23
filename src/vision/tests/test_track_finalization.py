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
        confidence_sum=1.7,
        max_confidence=0.9,
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
        confidence_sum=1.7,
        max_confidence=0.9,
        observation_count=2,
        representative=_representative(),
        representative_crop=crop,
        trajectory=trajectory,
    )

    assert isinstance(first, PreparedTrack)
    assert first == second
    assert first.detection_count == 2
    assert first.mean_confidence == pytest.approx(0.85)
    assert first.max_confidence == pytest.approx(0.9)
    assert first.confidence == first.mean_confidence
    assert first.thumbnail_payload.startswith(b"\xff\xd8")
    assert first.thumbnail_payload.endswith(b"\xff\xd9")
    assert deserialize_trajectory(first.trajectory_payload) == trajectory



def _accumulated(confidence: float, count: int) -> float:
    """The confidence sum exactly as ``VideoProcessor`` builds it: a running ``+=``.

    ``sum()`` is not a substitute. Since Python 3.12 it uses compensated summation,
    so ``sum([0.9] * 250)`` is exactly 225.0 and never shows the rounding the
    worker's accumulator produces.
    """
    total = 0.0
    for _ in range(count):
        total += confidence
    return total


def _prepare_constant_track(confidence: float, count: int, confidence_sum: float):
    return prepare_track(
        track_id="person-0001",
        object_class=ObjectClass.PERSON,
        start_offset_ms=0,
        end_offset_ms=(count - 1) * 40,
        confidence_sum=confidence_sum,
        max_confidence=confidence,
        observation_count=count,
        representative=_representative(),
        representative_crop=np.full((12, 10, 3), 120, dtype=np.uint8),
        trajectory=tuple(TrajectoryPoint(index * 40, 0.3, 0.4) for index in range(count)),
    )


def test_prepare_track_tolerates_floating_point_accumulation_noise() -> None:
    # The scripted-corpus case that failed in the worker: 250 observations at 0.9.
    confidence_sum = _accumulated(0.9, 250)
    assert confidence_sum / 250 > 0.9  # the rounding under test really occurs

    prepared = _prepare_constant_track(0.9, 250, confidence_sum)

    assert prepared.mean_confidence == 0.9
    assert prepared.max_confidence == 0.9


def test_prepare_track_tolerance_scales_with_track_length() -> None:
    # A long constant-confidence track rounds further above the maximum than any
    # fixed tolerance near 1e-12 allows; the bound grows with the count.
    count = 72_801  # roughly 48 minutes of one Track at 25 fps
    confidence_sum = _accumulated(0.9, count)
    assert confidence_sum / count - 0.9 > 1e-12

    prepared = _prepare_constant_track(0.9, count, confidence_sum)

    assert prepared.mean_confidence == 0.9


def test_prepare_track_rejects_an_excess_just_beyond_rounding() -> None:
    count = 250
    bound = count * 0.9 * 2.220446049250313e-16
    with pytest.raises(ValueError, match="track_confidence_invalid"):
        _prepare_constant_track(0.9, count, (0.9 + 4 * bound) * count)


@pytest.mark.parametrize(
    ("confidence_sum", "max_confidence"),
    [
        (float("nan"), 0.9),
        (0.9, float("nan")),
        (float("inf"), 0.9),
        (0.9, float("inf")),
        (-0.1, 0.9),
        (0.9, -0.1),
        (1.2, 1.2),
        (1.0000001, 1.0000001),
    ],
)
def test_prepare_track_rejects_non_finite_and_out_of_range_confidence(
    confidence_sum: float, max_confidence: float
) -> None:
    with pytest.raises(ValueError, match="track_confidence_invalid"):
        _prepare_constant_track(max_confidence, 1, confidence_sum)


def test_prepare_track_rejects_materially_inconsistent_confidence_aggregate() -> None:
    crop = np.full((12, 10, 3), 120, dtype=np.uint8)
    trajectory = (
        TrajectoryPoint(0, 0.3, 0.4),
        TrajectoryPoint(40, 0.4, 0.4),
    )

    with pytest.raises(ValueError, match="track_confidence_invalid"):
        prepare_track(
            track_id="person-0001",
            object_class=ObjectClass.PERSON,
            start_offset_ms=0,
            end_offset_ms=40,
            confidence_sum=1.81,
            max_confidence=0.9,
            observation_count=2,
            representative=_representative(),
            representative_crop=crop,
            trajectory=trajectory,
        )


def test_prepare_track_rejects_missing_observations() -> None:
    with pytest.raises(ValueError, match="track_observation_missing"):
        prepare_track(
            track_id="person-0001",
            object_class=ObjectClass.PERSON,
            start_offset_ms=0,
            end_offset_ms=0,
            confidence_sum=0.0,
            max_confidence=0.0,
            observation_count=0,
            representative=_representative(),
            representative_crop=np.ones((2, 2, 3), dtype=np.uint8),
            trajectory=(),
        )


def _prepare_with_trajectory(
    trajectory: tuple[TrajectoryPoint, ...],
    *,
    start_offset_ms: int = 0,
    end_offset_ms: int = 1000,
) -> PreparedTrack:
    return prepare_track(
        track_id="person-0001",
        object_class=ObjectClass.PERSON,
        start_offset_ms=start_offset_ms,
        end_offset_ms=end_offset_ms,
        confidence_sum=0.9 * len(trajectory),
        max_confidence=0.9,
        observation_count=len(trajectory),
        representative=_representative(),
        representative_crop=np.ones((4, 4, 3), dtype=np.uint8),
        trajectory=trajectory,
    )


def test_prepare_track_owns_trajectory_monotonicity() -> None:
    # The finalised ProcessedTrack no longer carries points, so this is the last
    # place a non-monotonic trajectory can be caught before it is staged.
    with pytest.raises(ValueError, match="trajectory_offsets_not_monotonic"):
        _prepare_with_trajectory(
            (TrajectoryPoint(500, 0.4, 0.3), TrajectoryPoint(500, 0.2, 0.3))
        )
    with pytest.raises(ValueError, match="trajectory_offsets_not_monotonic"):
        _prepare_with_trajectory(
            (TrajectoryPoint(1000, 0.4, 0.3), TrajectoryPoint(500, 0.2, 0.3))
        )


def test_prepare_track_rejects_trajectory_outside_track_bounds() -> None:
    with pytest.raises(ValueError, match="trajectory_offsets_outside_track"):
        _prepare_with_trajectory(
            (TrajectoryPoint(0, 0.4, 0.3), TrajectoryPoint(40, 0.2, 0.3)),
            start_offset_ms=10,
            end_offset_ms=40,
        )
    with pytest.raises(ValueError, match="trajectory_offsets_outside_track"):
        _prepare_with_trajectory(
            (TrajectoryPoint(0, 0.4, 0.3), TrajectoryPoint(40, 0.2, 0.3)),
            start_offset_ms=0,
            end_offset_ms=39,
        )


def test_prepare_track_rejects_point_count_differing_from_detections() -> None:
    with pytest.raises(ValueError, match="track_observation_missing"):
        prepare_track(
            track_id="person-0001",
            object_class=ObjectClass.PERSON,
            start_offset_ms=0,
            end_offset_ms=1000,
            confidence_sum=2.7,
            max_confidence=0.9,
            observation_count=3,
            representative=_representative(),
            representative_crop=np.ones((4, 4, 3), dtype=np.uint8),
            trajectory=(TrajectoryPoint(0, 0.2, 0.3), TrajectoryPoint(1000, 0.4, 0.3)),
        )
