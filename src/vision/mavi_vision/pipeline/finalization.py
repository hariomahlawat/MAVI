from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

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
    """Prepare deterministic track payloads without performing external side effects."""

    if representative is None or representative_crop is None or observation_count <= 0:
        raise ValueError("track_observation_missing")

    points = tuple(trajectory)
    if not points or len(points) != observation_count:
        raise ValueError("track_observation_missing")

    mean_confidence = confidence_sum / observation_count
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
