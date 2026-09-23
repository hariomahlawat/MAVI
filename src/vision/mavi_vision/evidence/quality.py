"""Replaceable, model-neutral evidence quality scoring (ADR-013 §4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mavi_vision.common.analytical import NormalizedBoundingBox
from mavi_vision.detection.interfaces import DetectionCandidate
from mavi_vision.evidence.errors import EvidenceError
from mavi_vision.evidence.policy import SCORER_VERSION, quantize_score
from mavi_vision.quality.scoring import quality_components
from mavi_vision.tracking.interfaces import TrackCandidate
from mavi_vision.video.reader import DecodedFrame


@dataclass(frozen=True, slots=True)
class FrameContext:
    """One accepted frame and every detection the tracker was given for it.

    The detections include both classes and those the tracker did not confirm:
    the occlusion proxy must see every concurrent box (plan §4.1).
    """

    frame: DecodedFrame
    detections: tuple[DetectionCandidate, ...]


@dataclass(frozen=True, slots=True)
class CandidateQuality:
    """Scalar signals of one Track candidate in one frame; no pixels.

    ``quality_micro`` and ``selection_micro`` are quantised scores in integer
    millionths, the only form the selector compares and the wire carries.
    """

    sharpness: float
    edge_margin: float
    area: float
    occlusion_iou: float
    quality_micro: int
    selection_micro: int


class QualityScorer(Protocol):
    version: str

    def score(self, context: FrameContext, candidate: TrackCandidate) -> CandidateQuality: ...


def box_iou(left: NormalizedBoundingBox, right: NormalizedBoundingBox) -> float:
    ix = max(0.0, min(left.x + left.width, right.x + right.width) - max(left.x, right.x))
    iy = max(0.0, min(left.y + left.height, right.y + right.height) - max(left.y, right.y))
    intersection = ix * iy
    if intersection <= 0.0:
        return 0.0
    union = left.width * left.height + right.width * right.height - intersection
    # Rounding can put identical boxes a few ulps above 1; IoU is in [0, 1].
    return min(1.0, intersection / union) if union > 0.0 else 0.0


def occlusion_iou(context: FrameContext, candidate: TrackCandidate) -> float:
    """Maximum IoU of the candidate with any *other* detection in the frame.

    The candidate's own source detection is identified model-neutrally: every
    ``Tracker`` in this repository reports a candidate with its source
    detection's class and exact bounding box, and exactly one such detection is
    excluded. A tracker that reports a box matching no detection makes the proxy
    meaningless, so it fails closed rather than scoring every frame occluded or
    unoccluded.
    """
    excluded = False
    best = 0.0
    for detection in context.detections:
        if (
            not excluded
            and detection.object_class is candidate.object_class
            and detection.bounding_box == candidate.bounding_box
        ):
            excluded = True
            continue
        best = max(best, box_iou(candidate.bounding_box, detection.bounding_box))
    if not excluded:
        raise EvidenceError("evidence_candidate_detection_unmatched")
    return best


class QualityV1Scorer:
    """Quality formula v1 (sharpness, area, edge margin) plus the occlusion proxy.

    ``quality_score`` is formula v1 and describes the frame; ``selection_score``
    is ``quality − occlusionPenaltyWeight · occlusionIou`` and orders
    candidates. They are equal while the penalty weight is 0.
    """

    version = SCORER_VERSION

    def __init__(self, occlusion_penalty_weight: float) -> None:
        self._penalty = float(occlusion_penalty_weight)

    def score(self, context: FrameContext, candidate: TrackCandidate) -> CandidateQuality:
        components = quality_components(context.frame, candidate.bounding_box)
        occlusion = occlusion_iou(context, candidate)
        return CandidateQuality(
            sharpness=components.sharpness,
            edge_margin=components.edge_margin,
            area=components.area,
            occlusion_iou=occlusion,
            quality_micro=quantize_score(components.quality),
            selection_micro=quantize_score(components.quality - self._penalty * occlusion),
        )
