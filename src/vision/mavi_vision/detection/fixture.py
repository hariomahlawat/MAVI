from __future__ import annotations

from collections.abc import Mapping, Sequence

from mavi_vision.detection.interfaces import DetectionCandidate
from mavi_vision.video.reader import DecodedFrame


class FixtureDetector:
    def __init__(
        self,
        detections_by_frame: Mapping[int, Sequence[DetectionCandidate]],
    ) -> None:
        self._detections = {
            frame_number: tuple(detections)
            for frame_number, detections in detections_by_frame.items()
        }

    def detect(self, frame: DecodedFrame) -> tuple[DetectionCandidate, ...]:
        return self._detections.get(frame.source_frame_number, ())
