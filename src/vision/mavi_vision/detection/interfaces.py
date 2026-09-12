from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from mavi_vision.common.analytical import NormalizedBoundingBox, ObjectClass
from mavi_vision.video.reader import DecodedFrame


@dataclass(frozen=True, slots=True)
class DetectionCandidate:
    object_class: ObjectClass
    confidence: float
    bounding_box: NormalizedBoundingBox
    frame_ordinal: int = 0

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("detection_confidence_out_of_range")
        if isinstance(self.frame_ordinal, bool) or self.frame_ordinal < 0:
            raise ValueError("detection_frame_ordinal_invalid")


class Detector(Protocol):
    def detect(self, frame: DecodedFrame) -> Sequence[DetectionCandidate]: ...
