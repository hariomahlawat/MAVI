from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class BoundingBox:
    x: float
    y: float
    width: float
    height: float

    def to_dict(self) -> dict[str, float]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True, slots=True)
class VisionObservation:
    track_id: str
    entity_type: str
    timestamp_utc: datetime
    confidence: float
    bounding_box: BoundingBox

    def to_dict(self) -> dict[str, Any]:
        return {
            "trackId": self.track_id,
            "entityType": self.entity_type,
            "timestampUtc": _iso_utc(self.timestamp_utc),
            "confidence": self.confidence,
            "boundingBox": self.bounding_box.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class VisionJob:
    job_id: UUID
    video_asset_id: UUID
    camera_id: str
    media_uri: str
    start_utc: datetime | None = None
    end_utc: datetime | None = None
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schemaVersion": self.schema_version,
            "jobId": str(self.job_id),
            "videoAssetId": str(self.video_asset_id),
            "cameraId": self.camera_id,
            "mediaUri": self.media_uri,
        }
        if self.start_utc is not None:
            payload["startUtc"] = _iso_utc(self.start_utc)
        if self.end_utc is not None:
            payload["endUtc"] = _iso_utc(self.end_utc)
        return payload


@dataclass(frozen=True, slots=True)
class VisionResult:
    job_id: UUID
    status: str
    observations: tuple[VisionObservation, ...] = ()
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "jobId": str(self.job_id),
            "status": self.status,
            "observations": [observation.to_dict() for observation in self.observations],
        }


@dataclass(frozen=True, slots=True)
class WorkerHealth:
    worker_id: UUID
    status: str
    timestamp_utc: datetime
    schema_version: str = "1.0"

    @classmethod
    def ready(cls, worker_id: UUID) -> "WorkerHealth":
        return cls(worker_id=worker_id, status="ready", timestamp_utc=datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "workerId": str(self.worker_id),
            "status": self.status,
            "timestampUtc": _iso_utc(self.timestamp_utc),
        }


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Cross-system timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
