from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from mavi_vision.common.analytical import NormalizedBoundingBox, ObjectClass
from mavi_vision.detection.interfaces import DetectionCandidate
from mavi_vision.video.reader import DecodedFrame


@dataclass(frozen=True, slots=True)
class TrackCandidate:
    track_id: str
    object_class: ObjectClass
    confidence: float
    bounding_box: NormalizedBoundingBox

    def __post_init__(self) -> None:
        if not self.track_id or len(self.track_id) > 64:
            raise ValueError("track_id_invalid")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("track_confidence_out_of_range")


class Tracker(Protocol):
    def update(
        self,
        frame: DecodedFrame,
        detections: Sequence[DetectionCandidate],
    ) -> Sequence[TrackCandidate]: ...
