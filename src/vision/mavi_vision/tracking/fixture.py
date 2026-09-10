from __future__ import annotations

from collections.abc import Mapping, Sequence

from mavi_vision.detection.interfaces import DetectionCandidate
from mavi_vision.tracking.interfaces import TrackCandidate
from mavi_vision.video.reader import DecodedFrame


class FixtureTrackerError(RuntimeError):
    pass


class FixtureTracker:
    def __init__(self, association_map: Mapping[tuple[int, int], str]) -> None:
        self._association_map = dict(association_map)

    def update(
        self,
        frame: DecodedFrame,
        detections: Sequence[DetectionCandidate],
    ) -> tuple[TrackCandidate, ...]:
        track_ids: list[str] = []
        tracks: list[TrackCandidate] = []
        for index, detection in enumerate(detections):
            key = (frame.source_frame_number, index)
            track_id = self._association_map.get(key)
            if track_id is None:
                raise FixtureTrackerError("fixture_track_mapping_missing")
            if track_id in track_ids:
                raise FixtureTrackerError("fixture_track_mapping_duplicate")
            track_ids.append(track_id)
            tracks.append(
                TrackCandidate(
                    track_id=track_id,
                    object_class=detection.object_class,
                    confidence=detection.confidence,
                    bounding_box=detection.bounding_box,
                )
            )
        return tuple(tracks)
