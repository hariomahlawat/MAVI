from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from mavi_vision.common.analytical import NormalizedBoundingBox, ObjectClass
from mavi_vision.detection.interfaces import DetectionCandidate
from mavi_vision.runtime.errors import TrackerError
from mavi_vision.video.reader import DecodedFrame


def _require_track_id(value: object) -> None:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ValueError("track_id_invalid")


@dataclass(frozen=True, slots=True)
class TrackCandidate:
    track_id: str
    object_class: ObjectClass
    confidence: float
    bounding_box: NormalizedBoundingBox

    def __post_init__(self) -> None:
        _require_track_id(self.track_id)
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("track_confidence_out_of_range")


@dataclass(frozen=True, slots=True)
class TrackerUpdate:
    """One accepted frame's model-neutral tracker output.

    ``candidates`` are the evidence-bearing observations of live MAVI Tracks in
    this frame. ``retired_track_ids`` are the MAVI Track ids whose lifecycle ended
    at this frame: the tracker guarantees that none of them can ever be emitted
    again within the same attempt, so the consumer may finalise each one exactly
    once, immediately.

    Lifecycle contract every ``Tracker`` implementation must honour within one
    attempt (ADR-013 §5):

    - a Track id is *live* from its first candidate until it is retired;
    - an id absent from one frame's candidates is merely unmatched, not retired;
    - an id is retired at most once, and only when the implementation can prove
      its backend can no longer re-associate that identity;
    - a retired id never appears again, as a candidate or as a retirement;
    - an id is never both a candidate and retired in the same update;
    - Tracks still live when the stream ends are not retired by the tracker; the
      consumer finalises them at end-of-stream.

    The value object enforces the per-update invariants; the cross-update ones
    are the implementation's responsibility and are re-checked by the consumer.
    """

    candidates: tuple[TrackCandidate, ...]
    retired_track_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.candidates, tuple) or not isinstance(
            self.retired_track_ids, tuple
        ):
            raise TrackerError("tracker_update_invalid")
        candidate_ids: set[str] = set()
        for candidate in self.candidates:
            if not isinstance(candidate, TrackCandidate):
                raise TrackerError("tracker_update_invalid")
            if candidate.track_id in candidate_ids:
                raise TrackerError("tracker_update_candidate_duplicate")
            candidate_ids.add(candidate.track_id)
        for track_id in self.retired_track_ids:
            try:
                _require_track_id(track_id)
            except ValueError:
                raise TrackerError("tracker_update_invalid") from None
        if len(set(self.retired_track_ids)) != len(self.retired_track_ids):
            raise TrackerError("tracker_update_retirement_duplicate")
        if list(self.retired_track_ids) != sorted(self.retired_track_ids):
            raise TrackerError("tracker_update_retirement_unordered")
        if candidate_ids.intersection(self.retired_track_ids):
            raise TrackerError("tracker_update_retired_candidate")


class Tracker(Protocol):
    def update(
        self,
        frame: DecodedFrame,
        detections: Sequence[DetectionCandidate],
    ) -> TrackerUpdate: ...
