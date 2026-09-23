from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import sys

import numpy as np
from PIL import Image

from mavi_vision.common.analytical import (
    ObjectClass,
    RepresentativeObservation,
    TrajectoryPoint,
)
from mavi_vision.video.trajectory import serialize_trajectory


@dataclass(frozen=True, slots=True)
class PreparedTrack:
    """Filesystem-independent, deterministic representation of a finalized track."""

    track_id: str
    object_class: ObjectClass
    start_offset_ms: int
    end_offset_ms: int
    detection_count: int
    mean_confidence: float
    max_confidence: float
    representative: RepresentativeObservation
    trajectory: tuple[TrajectoryPoint, ...]
    thumbnail_payload: bytes
    trajectory_payload: bytes

    @property
    def confidence(self) -> float:
        """Backward-compatible read alias for historical tests/callers."""
        return self.mean_confidence


def prepare_track(
    *,
    track_id: str,
    object_class: ObjectClass,
    start_offset_ms: int,
    end_offset_ms: int,
    confidence_sum: float,
    max_confidence: float,
    observation_count: int,
    representative: RepresentativeObservation | None,
    representative_crop: np.ndarray | None,
    trajectory: tuple[TrajectoryPoint, ...],
) -> PreparedTrack:
    """Prepare deterministic track payloads without performing external side effects.

    This is the last point at which the Track's trajectory points exist in memory,
    so every trajectory invariant is enforced here; the resulting ``ProcessedTrack``
    keeps only the staged descriptor.
    """

    if representative is None or representative_crop is None or observation_count <= 0:
        raise ValueError("track_observation_missing")

    points = tuple(trajectory)
    if not points or len(points) != observation_count:
        raise ValueError("track_observation_missing")
    offsets = [point.offset_ms for point in points]
    if any(current <= previous for previous, current in zip(offsets, offsets[1:])):
        raise ValueError("trajectory_offsets_not_monotonic")
    if offsets[0] < start_offset_ms or offsets[-1] > end_offset_ms:
        raise ValueError("trajectory_offsets_outside_track")

    mean_confidence = confidence_sum / observation_count
    # Every observation is bounded by the observed maximum, so the true mean
    # cannot exceed it. The running `+=` sum can still round a mean above it: 250
    # additions of 0.9 give 0.9000000000000038. Recursive summation of n terms errs
    # by at most about (n - 1) * u * sum (u = 2**-53), so the mean errs by at most
    # about n * u * max. The tolerance below is twice that bound: it scales with
    # the track's length, so long constant-confidence tracks still finalize, and it
    # is far narrower than any real inconsistency. Only an excess inside it is
    # rounding and is normalized to the maximum. Anything larger, and any NaN,
    # infinity or out-of-range value, still fails the check that follows.
    excess = mean_confidence - max_confidence
    if 0.0 < excess <= observation_count * max_confidence * sys.float_info.epsilon:
        mean_confidence = max_confidence
    if not 0.0 <= mean_confidence <= max_confidence <= 1.0:
        raise ValueError("track_confidence_invalid")

    trajectory_payload = serialize_trajectory(points)
    thumbnail_payload = _encode_jpeg(representative_crop)

    return PreparedTrack(
        track_id=track_id,
        object_class=object_class,
        start_offset_ms=start_offset_ms,
        end_offset_ms=end_offset_ms,
        detection_count=observation_count,
        mean_confidence=mean_confidence,
        max_confidence=max_confidence,
        representative=representative,
        trajectory=points,
        thumbnail_payload=thumbnail_payload,
        trajectory_payload=trajectory_payload,
    )


def _encode_jpeg(crop: np.ndarray) -> bytes:
    if crop.ndim != 3 or crop.shape[2] != 3 or crop.size == 0:
        raise ValueError("representative_crop_invalid")

    image_data = np.ascontiguousarray(crop, dtype=np.uint8)
    buffer = BytesIO()
    Image.fromarray(image_data).save(
        buffer,
        format="JPEG",
        quality=90,
        optimize=False,
        progressive=False,
        subsampling=2,
    )
    return buffer.getvalue()
