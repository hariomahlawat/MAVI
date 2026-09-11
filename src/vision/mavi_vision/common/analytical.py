from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from re import fullmatch
from uuid import UUID


_SHA256_PATTERN = r"[0-9a-f]{64}"
_STORAGE_SEGMENT_PATTERN = r"[^/\\]+"


class ObjectClass(StrEnum):
    PERSON = "person"
    VEHICLE = "vehicle"


def _require_unit_interval(value: float, name: str) -> None:
    if not isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name}_out_of_range")


def _validate_storage_key(value: str) -> None:
    if not value or value.startswith(("/", "\\")) or "\\" in value:
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
    track_id: str
    object_class: ObjectClass
    start_offset_ms: int
    end_offset_ms: int
    confidence: float
    representative: RepresentativeObservation
    trajectory: tuple[TrajectoryPoint, ...]
    thumbnail: ArtifactDescriptor
    trajectory_artifact: ArtifactDescriptor

    def __post_init__(self) -> None:
        if not self.track_id or len(self.track_id) > 64:
            raise ValueError("track_id_invalid")
        if self.start_offset_ms < 0 or self.end_offset_ms < self.start_offset_ms:
            raise ValueError("track_offsets_invalid")
        _require_unit_interval(self.confidence, "track_confidence")
        if not self.trajectory:
            raise ValueError("trajectory_required")
        offsets = [point.offset_ms for point in self.trajectory]
        if any(current <= previous for previous, current in zip(offsets, offsets[1:])):
            raise ValueError("trajectory_offsets_not_monotonic")
        if offsets[0] < self.start_offset_ms or offsets[-1] > self.end_offset_ms:
            raise ValueError("trajectory_offsets_outside_track")
        if not self.start_offset_ms <= self.representative.offset_ms <= self.end_offset_ms:
            raise ValueError("representative_outside_track")


@dataclass(frozen=True, slots=True)
class VisionProcessingResult:
    job_id: UUID
    frames_processed: int
    tracks: tuple[ProcessedTrack, ...]

    def __post_init__(self) -> None:
        if self.frames_processed < 0:
            raise ValueError("frames_processed_invalid")
