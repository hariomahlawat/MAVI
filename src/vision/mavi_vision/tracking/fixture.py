from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from mavi_vision.detection.interfaces import DetectionCandidate
from mavi_vision.tracking.interfaces import TrackCandidate, TrackerUpdate
from mavi_vision.video.reader import DecodedFrame


class FixtureTrackerError(RuntimeError):
    pass


class FixtureTracker:
    """Deterministic scripted tracker with the production lifecycle contract.

    ``association_map`` assigns each ``(source_frame_number, detection_index)`` to a
    Track id. ``retirements`` optionally retires Track ids at a source frame, the
    scripted analogue of a backend's lost-track expiry. Without retirements every
    Track stays live until end-of-stream, which the consumer then drains.

    The script is held to the same guarantees as a real adapter: an id is retired
    only while live, never in the frame it is emitted, at most once, and never
    emitted again afterwards. A script that breaks them fails the update rather
    than producing a lifecycle a production tracker could not.
    """

    def __init__(
        self,
        association_map: Mapping[tuple[int, int], str],
        retirements: Mapping[int, Iterable[str]] | None = None,
    ) -> None:
        self._association_map = dict(association_map)
        self._retirements = {
            frame_number: tuple(track_ids)
            for frame_number, track_ids in (retirements or {}).items()
        }
        self._live: set[str] = set()
        self._retired: set[str] = set()

    def update(
        self,
        frame: DecodedFrame,
        detections: Sequence[DetectionCandidate],
    ) -> TrackerUpdate:
        track_ids: list[str] = []
        tracks: list[TrackCandidate] = []
        for index, detection in enumerate(detections):
            key = (frame.source_frame_number, index)
            track_id = self._association_map.get(key)
            if track_id is None:
                raise FixtureTrackerError("fixture_track_mapping_missing")
            if track_id in track_ids:
                raise FixtureTrackerError("fixture_track_mapping_duplicate")
            if track_id in self._retired:
                raise FixtureTrackerError("fixture_track_reappeared_after_retirement")
            track_ids.append(track_id)
            tracks.append(
                TrackCandidate(
                    track_id=track_id,
                    object_class=detection.object_class,
                    confidence=detection.confidence,
                    bounding_box=detection.bounding_box,
                )
            )

        retired = self._retirements.get(frame.source_frame_number, ())
        if len(set(retired)) != len(retired):
            raise FixtureTrackerError("fixture_retirement_duplicate")
        for track_id in retired:
            if track_id in track_ids:
                raise FixtureTrackerError("fixture_retirement_while_emitted")
            if track_id in self._retired:
                raise FixtureTrackerError("fixture_retirement_duplicate")
            if track_id not in self._live:
                raise FixtureTrackerError("fixture_retirement_unknown_track")

        self._live.update(track_ids)
        self._live.difference_update(retired)
        self._retired.update(retired)
        return TrackerUpdate(
            candidates=tuple(tracks),
            retired_track_ids=tuple(sorted(retired)),
        )
