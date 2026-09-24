from __future__ import annotations

import pytest

from mavi_vision.common.analytical import (
    NormalizedBoundingBox,
    ObjectClass,
    TrajectoryPoint,
)
from mavi_vision.evidence.errors import EvidenceError
from mavi_vision.evidence.roles import EvidenceRole
from mavi_vision.pipeline.finalization import PreparedTrack, prepare_track
from mavi_vision.video.trajectory_spool import TrajectorySummary
from tests.evidence_fixtures import representative_only, resolved


def _summary(points: tuple[TrajectoryPoint, ...]) -> TrajectorySummary:
    if not points:
        return TrajectorySummary(0, 0, 0)
    return TrajectorySummary(len(points), points[0].offset_ms, points[-1].offset_ms)


def test_prepare_track_is_deterministic_and_side_effect_free() -> None:
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
        evidence=representative_only(),
        trajectory=_summary(trajectory),
    )
    second = prepare_track(
        track_id="person-0001",
        object_class=ObjectClass.PERSON,
        start_offset_ms=0,
        end_offset_ms=40,
        confidence_sum=1.7,
        max_confidence=0.9,
        observation_count=2,
        evidence=representative_only(),
        trajectory=_summary(trajectory),
    )

    assert isinstance(first, PreparedTrack)
    assert first == second
    assert first.detection_count == 2
    assert first.mean_confidence == pytest.approx(0.85)
    assert first.max_confidence == pytest.approx(0.9)
    assert first.confidence == first.mean_confidence
    # prepare_track encodes nothing: the resolved Evidence Set passes through.
    assert first.evidence == representative_only()
    # Only the summary travels; the points are streamed from the spool.
    assert first.trajectory == TrajectorySummary(2, 0, 40)
    assert not hasattr(first, "trajectory_payload")



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
        evidence=representative_only(),
        trajectory=_summary(tuple(TrajectoryPoint(index * 40, 0.3, 0.4) for index in range(count))),
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
            evidence=representative_only(),
            trajectory=_summary(trajectory),
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
            evidence=representative_only(),
            trajectory=_summary(()),
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
        evidence=representative_only(),
        trajectory=_summary(trajectory),
    )


def test_prepare_track_owns_trajectory_monotonicity() -> None:
    # The spool enforces strict monotonicity point by point; the summary check
    # here is the independent backstop that the endpoints agree with it.
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
            evidence=representative_only(),
            trajectory=_summary((TrajectoryPoint(0, 0.2, 0.3), TrajectoryPoint(1000, 0.4, 0.3))),
        )


def _prepare_with_evidence(evidence) -> PreparedTrack:
    return prepare_track(
        track_id="person-0001",
        object_class=ObjectClass.PERSON,
        start_offset_ms=0,
        end_offset_ms=1000,
        confidence_sum=1.8,
        max_confidence=0.9,
        observation_count=2,
        evidence=evidence,
        trajectory=TrajectorySummary(2, 0, 1000),
    )


def test_prepare_track_requires_a_representative() -> None:
    with pytest.raises(EvidenceError, match="evidence_representative_missing"):
        _prepare_with_evidence(())


@pytest.mark.parametrize(
    "evidence",
    [
        # Supplemental first.
        resolved((EvidenceRole.NEAR_VIEW, 1, 100)),
        # Roles out of canonical order.
        resolved((EvidenceRole.REPRESENTATIVE, 0, 0), (EvidenceRole.LATE_DIVERSE, 2, 900), (EvidenceRole.NEAR_VIEW, 1, 100)),
        # Two roles on one source frame.
        resolved((EvidenceRole.REPRESENTATIVE, 0, 0), (EvidenceRole.NEAR_VIEW, 0, 0)),
        # An observation outside the Track.
        resolved((EvidenceRole.REPRESENTATIVE, 0, 0), (EvidenceRole.LATE_DIVERSE, 9, 1001)),
        # Confidence above the Track maximum.
        resolved((EvidenceRole.REPRESENTATIVE, 0, 0), confidence=0.95),
    ],
)
def test_prepare_track_refuses_a_non_canonical_evidence_set(evidence) -> None:
    with pytest.raises(EvidenceError, match="evidence_set_invalid"):
        _prepare_with_evidence(evidence)


def test_prepare_track_accepts_the_full_canonical_set() -> None:
    evidence = resolved(
        (EvidenceRole.REPRESENTATIVE, 0, 0),
        (EvidenceRole.NEAR_VIEW, 1, 100),
        (EvidenceRole.EARLY_DIVERSE, 2, 400),
        (EvidenceRole.LATE_DIVERSE, 3, 900),
    )

    assert _prepare_with_evidence(evidence).evidence == evidence
