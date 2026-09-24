"""Replaceable, model-neutral evidence quality scoring (ADR-013 §4)."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Protocol

from mavi_vision.common.analytical import NormalizedBoundingBox
from mavi_vision.detection.interfaces import DetectionCandidate
from mavi_vision.evidence.errors import EvidenceError
from mavi_vision.evidence.policy import SCORER_VERSION, EvidencePolicy, quantize_score
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


def occlusion_iou(
    context: FrameContext,
    candidate: TrackCandidate,
    *,
    competitor_confidence_floor: float,
) -> float:
    """quality-v2 occlusion proxy: maximum IoU of the candidate with any *credible*
    competing detection in the frame, of either class.

    A competing detection is credible when its confidence is at or above
    ``competitor_confidence_floor`` (the profile's ``confidenceFloor``). Detections
    below it do not count. They are the detector's low-confidence residue down to
    ``detectorInferenceFloor``: part-boxes, and same-object duplicates that survive
    per-source-class NMS (a car also boxed as a truck). Counting them made the
    quality-v1 proxy reject 93 % of real-clip candidates as occluded (parameter
    note F1).

    The candidate's own source detection is identified model-neutrally and
    *before* the credibility filter, because the tracker may confirm a candidate
    from a sub-floor detection (ByteTrack's second association stage). Every
    ``Tracker`` in this repository reports a candidate with its source
    detection's class and exact bounding box, and exactly one such detection is
    excluded. A tracker that reports a box matching no detection makes the proxy
    meaningless, so it fails closed rather than scoring every frame occluded or
    unoccluded.
    """
    floor = float(competitor_confidence_floor)
    if not isfinite(floor) or not 0.0 <= floor <= 1.0:
        raise EvidenceError("evidence_competitor_confidence_floor_invalid")
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
        if detection.confidence >= floor:
            best = max(best, box_iou(candidate.bounding_box, detection.bounding_box))
    if not excluded:
        raise EvidenceError("evidence_candidate_detection_unmatched")
    return best


class QualityV2Scorer:
    """Quality formula v1 (sharpness, area, edge margin) plus the quality-v2
    occlusion proxy (credible competing detections only).

    ``quality_score`` is formula v1 and describes the frame; ``selection_score``
    is ``quality − occlusionPenaltyWeight · occlusionIou`` and orders
    candidates. They are equal while the penalty weight is 0. The frame-quality
    formula is unchanged from quality-v1; only the occlusion proxy's input set
    differs.
    """

    version = SCORER_VERSION

    def __init__(self, occlusion_penalty_weight: float, competitor_confidence_floor: float) -> None:
        self._penalty = float(occlusion_penalty_weight)
        self._competitor_floor = float(competitor_confidence_floor)

    def score(self, context: FrameContext, candidate: TrackCandidate) -> CandidateQuality:
        components = quality_components(context.frame, candidate.bounding_box)
        occlusion = occlusion_iou(
            context, candidate, competitor_confidence_floor=self._competitor_floor
        )
        return CandidateQuality(
            sharpness=components.sharpness,
            edge_margin=components.edge_margin,
            area=components.area,
            occlusion_iou=occlusion,
            quality_micro=quantize_score(components.quality),
            selection_micro=quantize_score(components.quality - self._penalty * occlusion),
        )


def scorer_for_policy(policy: EvidencePolicy) -> QualityV2Scorer:
    """The profile's scorer, configured from the profile alone.

    The only production construction path: the competitor floor is the policy's
    ``confidenceFloor``, so the proxy and the qualification floor cannot drift.
    """
    return QualityV2Scorer(policy.occlusion_penalty_weight, policy.confidence_floor)
