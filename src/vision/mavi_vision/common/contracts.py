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



def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Cross-system timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
