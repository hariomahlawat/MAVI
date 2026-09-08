from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from mavi_vision.common.contracts import BoundingBox


@dataclass(frozen=True, slots=True)
class DetectionCandidate:
    entity_type: str
    confidence: float
    bounding_box: BoundingBox


class Detector(Protocol):
    def detect(self, frame: object) -> Sequence[DetectionCandidate]: ...
