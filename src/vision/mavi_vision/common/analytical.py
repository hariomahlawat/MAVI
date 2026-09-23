from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from re import fullmatch
from uuid import UUID


_SHA256_PATTERN = r"[0-9a-f]{64}"
_TRACK_ID_PATTERN = r"[a-z0-9][a-z0-9._-]{0,63}"
_STORAGE_SEGMENT_PATTERN = r"[^/\\]+"


class ObjectClass(StrEnum):
    PERSON = "person"
    VEHICLE = "vehicle"


def _require_unit_interval(value: float, name: str) -> None:
    if not isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name}_out_of_range")


def _validate_storage_key(value: str) -> None:
    if not value or len(value) > 512 or value.startswith(("/", "\\")) or "\\" in value:
        raise ValueError("artifact_storage_key_invalid")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("artifact_storage_key_invalid")
    if any(not fullmatch(_STORAGE_SEGMENT_PATTERN, part) for part in parts):
        raise ValueError("artifact_storage_key_invalid")
    if ":" in parts[0]:
        raise ValueError("artifact_storage_key_invalid")


@dataclass(frozen=True, slots=True)
class NormalizedBoundingBox:
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        for name, value in (
            ("bbox_x", self.x),
            ("bbox_y", self.y),
            ("bbox_width", self.width),
            ("bbox_height", self.height),
        ):
            _require_unit_interval(value, name)
        if self.width <= 0.0 or self.height <= 0.0:
            raise ValueError("bbox_size_invalid")
        if self.x + self.width > 1.0 or self.y + self.height > 1.0:
            raise ValueError("bbox_out_of_bounds")


@dataclass(frozen=True, slots=True)
class TrajectoryPoint:
    offset_ms: int
    center_x: float
    center_y: float

    def __post_init__(self) -> None:
        if self.offset_ms < 0:
            raise ValueError("trajectory_offset_invalid")
        _require_unit_interval(self.center_x, "trajectory_center_x")
        _require_unit_interval(self.center_y, "trajectory_center_y")


@dataclass(frozen=True, slots=True)
class RepresentativeObservation:
    offset_ms: int
    source_frame_number: int
    confidence: float
    bounding_box: NormalizedBoundingBox
    quality_score: float

    def __post_init__(self) -> None:
        if self.offset_ms < 0:
            raise ValueError("representative_offset_invalid")
        if self.source_frame_number < 0:
            raise ValueError("source_frame_number_invalid")
        _require_unit_interval(self.confidence, "representative_confidence")
        _require_unit_interval(self.quality_score, "representative_quality")


@dataclass(frozen=True, slots=True)
class ArtifactDescriptor:
    storage_key: str
    media_type: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        _validate_storage_key(self.storage_key)
        if not self.media_type or not self.media_type.strip():
            raise ValueError("artifact_media_type_invalid")
        if self.size_bytes < 0:
            raise ValueError("artifact_size_invalid")
        if fullmatch(_SHA256_PATTERN, self.sha256) is None:
            raise ValueError("artifact_sha256_invalid")


@dataclass(frozen=True, slots=True)
class ProcessedTrack:
    """A finalised Track: scalar summary plus staged-artifact descriptors only.

    It deliberately carries no trajectory points or image payloads. A Track is
    finalised when its lifecycle ends, possibly long before end-of-stream, and the
    result keeps one of these per Track until completion; holding the full point
    list here would make completion memory grow with every detection of every
    Track. The points are validated in ``prepare_track`` and live on only as the
    staged ``trajectory_artifact``.
    """

    track_id: str
    object_class: ObjectClass
    start_offset_ms: int
    end_offset_ms: int
    detection_count: int
    mean_confidence: float
    max_confidence: float
    representative: RepresentativeObservation
    thumbnail: ArtifactDescriptor
    trajectory_artifact: ArtifactDescriptor

    def __post_init__(self) -> None:
        if fullmatch(_TRACK_ID_PATTERN, self.track_id) is None:
            raise ValueError("track_id_invalid")
        if self.start_offset_ms < 0 or self.end_offset_ms < self.start_offset_ms:
            raise ValueError("track_offsets_invalid")
        if self.detection_count <= 0:
            raise ValueError("track_detection_count_invalid")
        _require_unit_interval(self.mean_confidence, "track_mean_confidence")
        _require_unit_interval(self.max_confidence, "track_max_confidence")
        if self.mean_confidence > self.max_confidence:
            raise ValueError("track_confidence_order_invalid")
        if self.representative.confidence > self.max_confidence:
            raise ValueError("representative_confidence_exceeds_track_max")
        if not self.start_offset_ms <= self.representative.offset_ms <= self.end_offset_ms:
            raise ValueError("representative_outside_track")

    @property
    def confidence(self) -> float:
        """Backward-compatible read alias for the historical mean-confidence field."""
        return self.mean_confidence


@dataclass(frozen=True, slots=True)
class VisionProcessingResult:
    job_id: UUID
    frames_processed: int
    tracks: tuple[ProcessedTrack, ...]

    def __post_init__(self) -> None:
        if self.job_id.int == 0:
            raise ValueError("job_id_invalid")
        if self.frames_processed < 0:
            raise ValueError("frames_processed_invalid")
        if self.frames_processed == 0 and self.tracks:
            raise ValueError("tracks_require_processed_frames")
        track_ids = tuple(track.track_id for track in self.tracks)
        if len(track_ids) != len(set(track_ids)):
            raise ValueError("track_id_duplicate")
