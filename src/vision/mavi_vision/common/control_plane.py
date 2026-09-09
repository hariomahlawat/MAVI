from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictStr, field_validator


def _worker_id(value: str) -> str:
    if value != value.strip() or not 1 <= len(value) <= 128:
        raise ValueError("workerId must be canonical and contain 1..128 characters")
    return value


def _lease_token(value: str) -> str:
    import base64
    if len(value) != 43 or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for c in value):
        raise ValueError("leaseToken must be canonical unpadded Base64Url")
    try:
        decoded = base64.b64decode(value + "=", altchars=b"-_", validate=True)
        if len(decoded) != 32 or base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
            raise ValueError("invalid canonical token encoding")
    except Exception as exc:
        raise ValueError("leaseToken must encode 32 bytes") from exc
    return value


def _storage_key(value: str) -> str:
    segments = value.split("/")
    if not 1 <= len(value) <= 512 or value.startswith("/") or value.endswith("/") or \
            "\\" in value or ":" in value or any(segment in ("", ".", "..") for segment in segments):
        raise ValueError("sourceStorageKey must be a logical relative storage key")
    return value


WorkerId = Annotated[StrictStr, AfterValidator(_worker_id)]
LeaseToken = Annotated[StrictStr, AfterValidator(_lease_token)]
StorageKey = Annotated[StrictStr, AfterValidator(_storage_key)]


class ControlPlaneModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        strict=True,
        alias_generator=lambda n: n.split("_")[0] + "".join(x.title() for x in n.split("_")[1:]),
    )

    @field_validator("*", mode="after")
    @classmethod
    def require_utc_datetimes(cls, value: object) -> object:
        if isinstance(value, datetime) and (value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value)):
            raise ValueError("cross-system datetime must be timezone-aware UTC")
        return value


class VisionJobLeaseRequest(ControlPlaneModel):
    schema_version: Literal["2.0"]
    worker_id: WorkerId


class VisionJobLease(ControlPlaneModel):
    schema_version: Literal["2.0"]
    job_id: UUID
    processing_run_id: UUID
    video_asset_id: UUID
    camera_id: UUID
    worker_id: WorkerId
    lease_token: LeaseToken
    attempt_count: int = Field(ge=1)
    lease_expires_at_utc: datetime
    pipeline: str = Field(min_length=1, max_length=64)
    pipeline_version: str = Field(min_length=1, max_length=64)
    source_storage_key: StorageKey
    source_sha256: str = Field(pattern=r"^[A-Fa-f0-9]{64}$")
    source_size_bytes: int = Field(ge=0)
    recording_start_utc: datetime
    recording_end_utc: datetime
    duration_ms: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    frame_rate_numerator: int = Field(gt=0)
    frame_rate_denominator: int = Field(gt=0)
    recording_time_zone_id: str = Field(min_length=1, max_length=64)
    recording_utc_offset_minutes: int


class VisionJobHeartbeat(ControlPlaneModel):
    schema_version: Literal["2.0"]
    worker_id: WorkerId
    lease_token: LeaseToken
    progress_percent: float = Field(ge=0, le=100, allow_inf_nan=False)


class VisionJobHeartbeatResponse(ControlPlaneModel):
    schema_version: Literal["2.0"]
    progress_percent: float = Field(ge=0, le=100, allow_inf_nan=False)
    lease_expires_at_utc: datetime


class VisionJobFail(ControlPlaneModel):
    schema_version: Literal["2.0"]
    worker_id: WorkerId
    lease_token: LeaseToken
    failure_code: StrictStr = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    failure_message: str | None = Field(default=None, max_length=4000)


class WorkerHealth(ControlPlaneModel):
    schema_version: Literal["2.0"]
    worker_id: WorkerId
    status: Literal["ready"]
    timestamp_utc: datetime
