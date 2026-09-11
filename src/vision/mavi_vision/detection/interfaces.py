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

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("detection_confidence_out_of_range")


class Detector(Protocol):
    def detect(self, frame: DecodedFrame) -> Sequence[DetectionCandidate]: ...
