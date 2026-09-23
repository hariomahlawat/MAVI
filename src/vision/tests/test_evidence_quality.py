"""Evidence quality scorer: formula v1, quantisation and the occlusion proxy."""

from __future__ import annotations

import numpy as np
import pytest

from mavi_vision.common.analytical import NormalizedBoundingBox, ObjectClass
from mavi_vision.detection.interfaces import DetectionCandidate
from mavi_vision.evidence.errors import EvidenceError
from mavi_vision.evidence.policy import SCORE_SCALE, quantize_score
from mavi_vision.evidence.quality import FrameContext, QualityV1Scorer, box_iou, occlusion_iou
from mavi_vision.quality.scoring import representative_quality
from mavi_vision.tracking.interfaces import TrackCandidate
from mavi_vision.video.reader import DecodedFrame


def _frame() -> DecodedFrame:
    image = np.random.default_rng(1).integers(0, 256, (120, 160, 3), dtype=np.uint8)
    return DecodedFrame(source_frame_number=3, offset_ms=100, image=image)


def _det(box: NormalizedBoundingBox, cls: ObjectClass = ObjectClass.PERSON, ordinal: int = 0) -> DetectionCandidate:
    return DetectionCandidate(cls, 0.9, box, frame_ordinal=ordinal)


def _cand(box: NormalizedBoundingBox, cls: ObjectClass = ObjectClass.PERSON) -> TrackCandidate:
    return TrackCandidate("person-a", cls, 0.9, box)


BOX = NormalizedBoundingBox(0.2, 0.2, 0.3, 0.4)


def test_quality_score_is_formula_v1_quantised_to_millionths() -> None:
    frame = _frame()
    score = QualityV1Scorer(0.0).score(FrameContext(frame, (_det(BOX),)), _cand(BOX))

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


def test_occlusion_uses_every_other_detection_of_both_classes() -> None:
    """S4: an unconfirmed vehicle overlapping the person raises its occlusion proxy."""
    overlapping = NormalizedBoundingBox(0.3, 0.2, 0.3, 0.4)
    context = FrameContext(
        _frame(),
        (_det(BOX), _det(overlapping, ObjectClass.VEHICLE, ordinal=1)),
    )

    assert occlusion_iou(context, _cand(BOX)) == pytest.approx(box_iou(BOX, overlapping))
    assert occlusion_iou(context, _cand(BOX)) > 0.3


def test_an_identical_second_detection_counts_as_full_occlusion() -> None:
    context = FrameContext(_frame(), (_det(BOX), _det(BOX, ordinal=1)))

    assert occlusion_iou(context, _cand(BOX)) == 1.0


def test_penalty_weight_lowers_only_the_selection_score() -> None:
    overlapping = NormalizedBoundingBox(0.3, 0.2, 0.3, 0.4)
    context = FrameContext(_frame(), (_det(BOX), _det(overlapping, ordinal=1)))

    plain = QualityV1Scorer(0.0).score(context, _cand(BOX))
    penalised = QualityV1Scorer(0.5).score(context, _cand(BOX))

    assert penalised.quality_micro == plain.quality_micro
    assert penalised.selection_micro < plain.selection_micro


def test_candidate_without_its_source_detection_fails_closed() -> None:
    other = NormalizedBoundingBox(0.6, 0.6, 0.2, 0.2)
    with pytest.raises(EvidenceError, match="evidence_candidate_detection_unmatched"):
        occlusion_iou(FrameContext(_frame(), (_det(other),)), _cand(BOX))
    # Same box but a different class is not the candidate's own detection.
    with pytest.raises(EvidenceError, match="evidence_candidate_detection_unmatched"):
        occlusion_iou(FrameContext(_frame(), (_det(BOX, ObjectClass.VEHICLE),)), _cand(BOX))


def test_iou_is_symmetric_and_zero_for_disjoint_boxes() -> None:
    left = NormalizedBoundingBox(0.0, 0.0, 0.2, 0.2)
    right = NormalizedBoundingBox(0.1, 0.1, 0.2, 0.2)
    far = NormalizedBoundingBox(0.7, 0.7, 0.2, 0.2)

    assert box_iou(left, right) == box_iou(right, left) == pytest.approx(0.01 / 0.07)
    assert box_iou(left, far) == 0.0
    assert box_iou(left, left) == 1.0
