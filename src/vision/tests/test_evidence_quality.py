"""Evidence quality scorer quality-v2: formula v1, quantisation and the credible-competitor occlusion proxy."""

from __future__ import annotations

import numpy as np
import pytest

from mavi_vision.common.analytical import NormalizedBoundingBox, ObjectClass
from mavi_vision.detection.interfaces import DetectionCandidate
from mavi_vision.evidence.errors import EvidenceError
from mavi_vision.evidence.policy import SCORE_SCALE, SCORER_VERSION, quantize_score
from mavi_vision.evidence.quality import (
    FrameContext,
    QualityV2Scorer,
    box_iou,
    occlusion_iou,
    scorer_for_policy,
)
from mavi_vision.quality.scoring import representative_quality
from mavi_vision.tracking.interfaces import TrackCandidate
from mavi_vision.video.reader import DecodedFrame
from tests.profile_fixtures import PRODUCTION_EVIDENCE_POLICY as POLICY

FLOOR = POLICY.confidence_floor  # the shipped profile's confidenceFloor (0.5)


def _frame() -> DecodedFrame:
    image = np.random.default_rng(1).integers(0, 256, (120, 160, 3), dtype=np.uint8)
    return DecodedFrame(source_frame_number=3, offset_ms=100, image=image)


def _det(
    box: NormalizedBoundingBox,
    cls: ObjectClass = ObjectClass.PERSON,
    ordinal: int = 0,
    confidence: float = 0.9,
) -> DetectionCandidate:
    return DetectionCandidate(cls, confidence, box, frame_ordinal=ordinal)


def _occlusion(context: FrameContext, candidate: TrackCandidate) -> float:
    return occlusion_iou(context, candidate, competitor_confidence_floor=FLOOR)


def _cand(box: NormalizedBoundingBox, cls: ObjectClass = ObjectClass.PERSON) -> TrackCandidate:
    return TrackCandidate("person-a", cls, 0.9, box)


BOX = NormalizedBoundingBox(0.2, 0.2, 0.3, 0.4)


def test_quality_score_is_formula_v1_quantised_to_millionths() -> None:
    frame = _frame()
    score = scorer_for_policy(POLICY).score(FrameContext(frame, (_det(BOX),)), _cand(BOX))

    assert score.quality_micro == quantize_score(representative_quality(frame, BOX))
    assert score.selection_micro == score.quality_micro
    assert score.area == pytest.approx(0.12)
    assert score.edge_margin == pytest.approx(0.2)
    assert score.occlusion_iou == 0.0


def test_quantise_floors_and_clamps_exactly() -> None:
    assert quantize_score(0.1234569) == 123456
    assert quantize_score(1.5) == SCORE_SCALE
    assert quantize_score(-0.2) == 0
    with pytest.raises(ValueError):
        quantize_score(float("nan"))


def test_occlusion_uses_every_other_credible_detection_of_both_classes() -> None:
    """S4: an unconfirmed, credible vehicle overlapping the person raises its occlusion proxy."""
    overlapping = NormalizedBoundingBox(0.3, 0.2, 0.3, 0.4)
    context = FrameContext(
        _frame(),
        (_det(BOX), _det(overlapping, ObjectClass.VEHICLE, ordinal=1)),
    )

    assert _occlusion(context, _cand(BOX)) == pytest.approx(box_iou(BOX, overlapping))
    assert _occlusion(context, _cand(BOX)) > 0.3


def test_an_identical_second_detection_counts_as_full_occlusion() -> None:
    context = FrameContext(_frame(), (_det(BOX), _det(BOX, ordinal=1)))

    assert _occlusion(context, _cand(BOX)) == 1.0


def test_penalty_weight_lowers_only_the_selection_score() -> None:
    overlapping = NormalizedBoundingBox(0.3, 0.2, 0.3, 0.4)
    context = FrameContext(_frame(), (_det(BOX), _det(overlapping, ordinal=1)))

    plain = QualityV2Scorer(0.0, FLOOR).score(context, _cand(BOX))
    penalised = QualityV2Scorer(0.5, FLOOR).score(context, _cand(BOX))

    assert penalised.quality_micro == plain.quality_micro
    assert penalised.selection_micro < plain.selection_micro


def test_candidate_without_its_source_detection_fails_closed() -> None:
    other = NormalizedBoundingBox(0.6, 0.6, 0.2, 0.2)
    with pytest.raises(EvidenceError, match="evidence_candidate_detection_unmatched"):
        _occlusion(FrameContext(_frame(), (_det(other),)), _cand(BOX))
    # Same box but a different class is not the candidate's own detection.
    with pytest.raises(EvidenceError, match="evidence_candidate_detection_unmatched"):
        _occlusion(FrameContext(_frame(), (_det(BOX, ObjectClass.VEHICLE),)), _cand(BOX))


def test_iou_is_symmetric_and_zero_for_disjoint_boxes() -> None:
    left = NormalizedBoundingBox(0.0, 0.0, 0.2, 0.2)
    right = NormalizedBoundingBox(0.1, 0.1, 0.2, 0.2)
    far = NormalizedBoundingBox(0.7, 0.7, 0.2, 0.2)

    assert box_iou(left, right) == box_iou(right, left) == pytest.approx(0.01 / 0.07)
    assert box_iou(left, far) == 0.0
    assert box_iou(left, left) == 1.0


# -- quality-v2: only credible competing detections count (parameter note F1) --

NEAR_DUPLICATE = NormalizedBoundingBox(0.21, 0.2, 0.3, 0.4)
OVERLAPPING = NormalizedBoundingBox(0.3, 0.2, 0.3, 0.4)


def test_scorer_version_is_quality_v2_and_the_policy_scorer_uses_confidence_floor() -> None:
    scorer = scorer_for_policy(POLICY)
    assert SCORER_VERSION == "quality-v2" and scorer.version == "quality-v2"
    just_below = FrameContext(_frame(), (_det(BOX), _det(BOX, ordinal=1, confidence=0.49)))
    at_floor = FrameContext(_frame(), (_det(BOX), _det(BOX, ordinal=1, confidence=FLOOR)))
    assert scorer.score(just_below, _cand(BOX)).occlusion_iou == 0.0
    assert scorer.score(at_floor, _cand(BOX)).occlusion_iou == 1.0


def test_low_confidence_duplicate_is_ignored() -> None:
    """The F1 case: a sub-floor near-duplicate of the subject is detector residue."""
    context = FrameContext(
        _frame(),
        (_det(BOX), _det(NEAR_DUPLICATE, ordinal=1, confidence=0.12), _det(BOX, ordinal=2, confidence=0.05)),
    )
    assert box_iou(BOX, NEAR_DUPLICATE) > 0.9
    assert _occlusion(context, _cand(BOX)) == 0.0


def test_detection_exactly_at_the_floor_is_counted_and_just_below_is_not() -> None:
    at_floor = FrameContext(_frame(), (_det(BOX), _det(OVERLAPPING, ordinal=1, confidence=FLOOR)))
    below = FrameContext(
        _frame(), (_det(BOX), _det(OVERLAPPING, ordinal=1, confidence=float(np.nextafter(FLOOR, 0.0))))
    )
    assert _occlusion(at_floor, _cand(BOX)) == pytest.approx(box_iou(BOX, OVERLAPPING))
    assert _occlusion(below, _cand(BOX)) == 0.0


def test_high_confidence_same_class_overlap_is_counted() -> None:
    context = FrameContext(_frame(), (_det(BOX), _det(OVERLAPPING, ordinal=1, confidence=0.8)))
    assert _occlusion(context, _cand(BOX)) == pytest.approx(box_iou(BOX, OVERLAPPING))
    assert _occlusion(context, _cand(BOX)) >= POLICY.occlusion_iou_ceiling


def test_high_confidence_cross_class_overlap_is_counted() -> None:
    context = FrameContext(
        _frame(), (_det(BOX), _det(OVERLAPPING, ObjectClass.VEHICLE, ordinal=1, confidence=0.8))
    )
    assert _occlusion(context, _cand(BOX)) == pytest.approx(box_iou(BOX, OVERLAPPING))
    # ... and in the other direction, for a vehicle candidate occluded by a person.
    vehicle = FrameContext(
        _frame(), (_det(BOX, ObjectClass.VEHICLE), _det(OVERLAPPING, ObjectClass.PERSON, ordinal=1, confidence=0.8))
    )
    assert _occlusion(vehicle, _cand(BOX, ObjectClass.VEHICLE)) == pytest.approx(box_iou(BOX, OVERLAPPING))


def test_the_strongest_credible_competitor_wins_over_a_stronger_sub_floor_overlap() -> None:
    """A sub-floor near-duplicate never raises the proxy; the credible neighbour sets it."""
    context = FrameContext(
        _frame(),
        (
            _det(BOX),
            _det(NEAR_DUPLICATE, ordinal=1, confidence=0.3),
            _det(OVERLAPPING, ObjectClass.VEHICLE, ordinal=2, confidence=0.7),
        ),
    )
    assert _occlusion(context, _cand(BOX)) == pytest.approx(box_iou(BOX, OVERLAPPING))


def test_a_sub_floor_source_detection_is_still_excluded_as_the_candidate_itself() -> None:
    """ByteTrack can confirm a candidate from a low-confidence box: the own-detection
    exclusion runs before the credibility filter, so it is excluded exactly once and
    an identical credible second detection still counts."""
    own_low = FrameContext(_frame(), (_det(BOX, confidence=0.2),))
    assert _occlusion(own_low, _cand(BOX)) == 0.0
    own_low_with_credible_twin = FrameContext(
        _frame(), (_det(BOX, confidence=0.2), _det(BOX, ordinal=1, confidence=0.9))
    )
    assert _occlusion(own_low_with_credible_twin, _cand(BOX)) == 1.0


def test_the_competitor_floor_is_mandatory_and_bounded() -> None:
    context = FrameContext(_frame(), (_det(BOX),))
    with pytest.raises(TypeError):
        occlusion_iou(context, _cand(BOX))  # type: ignore[call-arg]
    for bad in (-0.1, 1.5, float("nan")):
        with pytest.raises(EvidenceError, match="evidence_competitor_confidence_floor_invalid"):
            occlusion_iou(context, _cand(BOX), competitor_confidence_floor=bad)
