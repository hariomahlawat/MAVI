from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from mavi_vision.common.contracts import BoundingBox
from mavi_vision.detection.interfaces import DetectionCandidate


@dataclass(frozen=True, slots=True)
class TrackCandidate:
    track_id: str
    entity_type: str
    confidence: float
    bounding_box: BoundingBox


class Tracker(Protocol):
    def update(self, frame: object, detections: Sequence[DetectionCandidate]) -> Sequence[TrackCandidate]: ...
