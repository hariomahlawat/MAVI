import re
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictStr,
    ValidationInfo,
    field_validator,
)


_WORKER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", re.ASCII)
_FAILURE_CODE_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}", re.ASCII)


def _snake_to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(part.title() for part in parts[1:])


def _canonical_utc_wire(value: object, info: ValidationInfo) -> object:
    if info.mode == "json":
        if not isinstance(value, str) or not value.endswith("Z"):
            raise ValueError("worker contract timestamp must use canonical UTC Z syntax")
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("worker contract timestamp must be a valid ISO-8601 datetime") from exc
    return value


def _worker_id(value: str) -> str:
    if _WORKER_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("workerId must use the canonical safe identifier syntax")
    return value


def _failure_code(value: str) -> str:
    if _FAILURE_CODE_PATTERN.fullmatch(value) is None:
        raise ValueError("failureCode must use the canonical machine-code syntax")
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
FailureCode = Annotated[StrictStr, AfterValidator(_failure_code)]
LeaseToken = Annotated[StrictStr, AfterValidator(_lease_token)]
StorageKey = Annotated[StrictStr, AfterValidator(_storage_key)]
CanonicalUtcDateTime = Annotated[datetime, BeforeValidator(_canonical_utc_wire)]


class ControlPlaneModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_by_alias=True,
        validate_by_name=False,
        serialize_by_alias=True,
        alias_generator=_snake_to_camel,
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
    lease_expires_at_utc: CanonicalUtcDateTime
    pipeline: str = Field(min_length=1, max_length=64)
    pipeline_version: str = Field(min_length=1, max_length=64)
    source_storage_key: StorageKey
    source_sha256: str = Field(pattern=r"^[A-Fa-f0-9]{64}$")
    source_size_bytes: int = Field(ge=0)
    recording_start_utc: CanonicalUtcDateTime
    recording_end_utc: CanonicalUtcDateTime
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
    lease_expires_at_utc: CanonicalUtcDateTime


class VisionJobFail(ControlPlaneModel):
    schema_version: Literal["2.0"]
    worker_id: WorkerId
    lease_token: LeaseToken
    failure_code: FailureCode
    failure_message: str | None = Field(default=None, max_length=4000)


class WorkerHealth(ControlPlaneModel):
    schema_version: Literal["2.0"]
    worker_id: WorkerId
    status: Literal["ready"]
    timestamp_utc: CanonicalUtcDateTime
