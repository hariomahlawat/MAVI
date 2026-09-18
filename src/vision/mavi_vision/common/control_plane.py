import base64
import json
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
    model_validator,
)


_WORKER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", re.ASCII)
_FAILURE_CODE_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}", re.ASCII)
_TRACK_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$", re.ASCII)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_CANONICAL_UTC_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z",
    re.ASCII,
)


def _snake_to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(part.title() for part in parts[1:])


_COMPLETION_ARTIFACT_MAX_BYTES = 64 * 1024 * 1024
_COMPLETION_EVIDENCE_MAX_BYTES = 512 * 1024 * 1024
_COMPLETION_DEPENDENCY_VERSION_MAX_COUNT = 128
_TRACKER_POSITIVE_MIN = 1e-9
_TRACKER_POSITIVE_MAX = 1e9
_COMPLETION_INTEGER_WIRE_NAMES = frozenset(
    {
        "attemptCount",
        "framesProcessed",
        "processingDurationMs",
        "sizeBytes",
        "offsetMs",
        "sourceFrameNumber",
        "startOffsetMs",
        "endOffsetMs",
        "detectionCount",
        "configuredDeviceIndex",
        "index",
        "vramBytes",
        "minimumConsecutiveFrames",
    }
)
_CONTRACT_EDGE_WHITESPACE = frozenset(
    chr(code)
    for code in (
        *range(0x0009, 0x000E),
        0x0020,
        0x0085,
        0x00A0,
        0x1680,
        *range(0x2000, 0x200B),
        0x2028,
        0x2029,
        0x202F,
        0x205F,
        0x3000,
        0xFEFF,
    )
)


class _CompletionJsonNumber(str):
    pass


def _completion_json_float(value: str) -> _CompletionJsonNumber:
    return _CompletionJsonNumber(value)


def _parse_completion_exponent(
    value: str | None,
    *,
    fraction_length: int,
    mantissa_digit_count: int,
) -> int:
    if value is None:
        return 0

    negative = value.startswith("-")
    digits = value.lstrip("+-").lstrip("0") or "0"

    if negative:
        # A negative exponent increases the fractional scale. Once its
        # magnitude exceeds the complete non-zero mantissa width, the value
        # cannot be mathematically integral.
        limit = mantissa_digit_count
        if len(digits) > len(str(limit)) or (
            len(digits) == len(str(limit)) and digits > str(limit)
        ):
            raise ValueError("completion integer must be mathematically integral")
        return -int(digits)

    # A positive exponent may cancel fractional digits and append zeroes.
    # If it exceeds the fractional scale by more than the Int64 decimal
    # envelope, a non-zero value cannot fit any completion wire integer.
    limit = fraction_length + 19
    if len(digits) > len(str(limit)) or (
        len(digits) == len(str(limit)) and digits > str(limit)
    ):
        raise ValueError("completion integer is outside the wire-type range")
    return int(digits)


def _completion_integer_token(value: str) -> int:
    match = re.fullmatch(
        r"(?P<sign>-?)(?P<whole>0|[1-9]\d*)(?:\.(?P<fraction>\d+))?(?:[eE](?P<exponent>[+-]?\d+))?",
        value,
        re.ASCII,
    )
    if match is None:
        raise ValueError("completion integer must be a JSON number")

    whole = match.group("whole")
    fraction = match.group("fraction") or ""
    digits = whole + fraction
    if all(character == "0" for character in digits):
        return 0

    exponent = _parse_completion_exponent(
        match.group("exponent"),
        fraction_length=len(fraction),
        mantissa_digit_count=len(digits),
    )
    scale = len(fraction) - exponent

    if scale > 0:
        if scale > len(digits) or any(character != "0" for character in digits[-scale:]):
            raise ValueError("completion integer must be mathematically integral")
        integral_digits = digits[:-scale]
    else:
        zeros_to_append = -scale
        if zeros_to_append > 19:
            raise ValueError("completion integer is outside the wire-type range")
        integral_digits = digits + ("0" * zeros_to_append)

    integral_digits = integral_digits.lstrip("0") or "0"
    if len(integral_digits) > 19:
        raise ValueError("completion integer is outside the wire-type range")

    result = int(integral_digits)
    return -result if match.group("sign") == "-" else result


def _normalize_completion_json_numbers(value, field_name: str | None = None):
    if isinstance(value, _CompletionJsonNumber):
        if field_name in _COMPLETION_INTEGER_WIRE_NAMES:
            try:
                return _completion_integer_token(value)
            except ValueError:
                # Preserve invalidity through JSON re-serialization. Strict integer
                # validation rejects the string rather than accepting a rounded float.
                return str(value)
        return float(value)
    if isinstance(value, list):
        return [_normalize_completion_json_numbers(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _normalize_completion_json_numbers(item, key)
            for key, item in value.items()
        }
    return value


def _completion_integral(value: object, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("completion integer must be a JSON number")
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError("completion integer must be mathematically integral")
        value = int(value)
    if value < minimum or value > maximum:
        raise ValueError("completion integer is outside the wire-type range")
    return value


def _completion_int32(value: object) -> int:
    return _completion_integral(value, minimum=-(2**31), maximum=2**31 - 1)


def _completion_int64(value: object) -> int:
    return _completion_integral(value, minimum=-(2**63), maximum=2**63 - 1)


def _canonical_utc_wire(value: object, info: ValidationInfo) -> object:
    if info.mode == "json":
        if not isinstance(value, str) or _CANONICAL_UTC_PATTERN.fullmatch(value) is None:
            raise ValueError(
                "worker contract timestamp must use canonical RFC3339 UTC Z syntax with at most 6 fractional digits"
            )
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


def _track_id(value: str) -> str:
    if _TRACK_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("trackId must use the canonical safe identifier syntax")
    return value


def _bounded_trimmed_text(value: str, *, maximum_length: int, label: str) -> str:
    if (
        len(value) > maximum_length
        or not value
        or "\x00" in value
        or value[0] in _CONTRACT_EDGE_WHITESPACE
        or value[-1] in _CONTRACT_EDGE_WHITESPACE
    ):
        raise ValueError(
            f"{label} must be non-empty, trimmed, and at most {maximum_length} characters"
        )
    return value


def _provenance_identity(value: str) -> str:
    return _bounded_trimmed_text(
        value,
        maximum_length=128,
        label="provenance identity",
    )


def _provenance_detail(value: str) -> str:
    return _bounded_trimmed_text(
        value,
        maximum_length=256,
        label="provenance detail",
    )


def _sha256(value: str) -> str:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError("SHA-256 must use canonical lowercase hexadecimal syntax")
    return value


def _lease_token(value: str) -> str:
    if len(value) != 43 or any(
        c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
        for c in value
    ):
        raise ValueError("leaseToken must be canonical unpadded Base64Url")
    try:
        decoded = base64.b64decode(value + "=", altchars=b"-_", validate=True)
        if (
            len(decoded) != 32
            or base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value
        ):
            raise ValueError("invalid canonical token encoding")
    except Exception as exc:
        raise ValueError("leaseToken must encode 32 bytes") from exc
    return value


def _storage_key(value: str) -> str:
    segments = value.split("/")
    if (
        not 1 <= len(value) <= 512
        or value.startswith("/")
        or value.endswith("/")
        or "\\" in value
        or ":" in value
        or any(segment in ("", ".", "..") for segment in segments)
    ):
        raise ValueError("storage key must be a logical relative storage key")
    return value


WorkerId = Annotated[StrictStr, AfterValidator(_worker_id)]
FailureCode = Annotated[StrictStr, AfterValidator(_failure_code)]
LeaseToken = Annotated[StrictStr, AfterValidator(_lease_token)]
StorageKey = Annotated[StrictStr, AfterValidator(_storage_key)]
TrackId = Annotated[StrictStr, AfterValidator(_track_id)]
Sha256 = Annotated[StrictStr, AfterValidator(_sha256)]
CanonicalUtcDateTime = Annotated[datetime, BeforeValidator(_canonical_utc_wire)]
CompletionInt32 = Annotated[int, BeforeValidator(_completion_int32)]
CompletionInt64 = Annotated[int, BeforeValidator(_completion_int64)]
ProvenanceIdentity = Annotated[StrictStr, AfterValidator(_provenance_identity)]
ProvenanceDetail = Annotated[StrictStr, AfterValidator(_provenance_detail)]


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
        if isinstance(value, datetime) and (
            value.tzinfo is None
            or value.utcoffset() != timezone.utc.utcoffset(value)
        ):
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
    attempt_count: int = Field(ge=1, le=2_147_483_647)
    lease_expires_at_utc: CanonicalUtcDateTime
    pipeline: str = Field(min_length=1, max_length=64)
    pipeline_version: str = Field(min_length=1, max_length=64)
    source_storage_key: StorageKey
    source_sha256: str = Field(pattern=r"^[A-Fa-f0-9]{64}$")
    source_size_bytes: int = Field(ge=0, le=9_223_372_036_854_775_807)
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


class VisionCompletionArtifact(ControlPlaneModel):
    storage_key: StorageKey
    media_type: Literal["image/jpeg", "application/msgpack"]
    size_bytes: CompletionInt64 = Field(ge=0, le=_COMPLETION_ARTIFACT_MAX_BYTES)
    sha256: Sha256


class VisionCompletionBoundingBox(ControlPlaneModel):
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)
    width: float = Field(ge=1.401298464324817e-45, le=1, allow_inf_nan=False)
    height: float = Field(ge=1.401298464324817e-45, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_bounds(self) -> "VisionCompletionBoundingBox":
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("boundingBox must be fully normalized inside [0,1]")
        return self


class VisionCompletionRepresentative(ControlPlaneModel):
    offset_ms: CompletionInt64 = Field(ge=0, le=9_223_372_036_854_775_807)
    source_frame_number: CompletionInt64 = Field(ge=0, le=9_223_372_036_854_775_807)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    quality_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    bounding_box: VisionCompletionBoundingBox
    thumbnail: VisionCompletionArtifact


class VisionCompletionTrack(ControlPlaneModel):
    track_id: TrackId
    object_class: Literal["person", "vehicle"]
    start_offset_ms: CompletionInt64 = Field(ge=0, le=9_223_372_036_854_775_807)
    end_offset_ms: CompletionInt64 = Field(ge=0, le=9_223_372_036_854_775_807)
    detection_count: CompletionInt32 = Field(gt=0, le=2_147_483_647)
    mean_confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    max_confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    representative: VisionCompletionRepresentative
    trajectory_artifact: VisionCompletionArtifact

    @model_validator(mode="after")
    def validate_track_semantics(self) -> "VisionCompletionTrack":
        if self.end_offset_ms < self.start_offset_ms:
            raise ValueError("track offsets are invalid")
        if self.mean_confidence > self.max_confidence:
            raise ValueError("meanConfidence cannot exceed maxConfidence")
        if self.representative.confidence > self.max_confidence:
            raise ValueError("representative confidence cannot exceed maxConfidence")
        if not self.start_offset_ms <= self.representative.offset_ms <= self.end_offset_ms:
            raise ValueError("representative observation must lie inside the track")
        return self


class VisionPlatformIdentity(ControlPlaneModel):
    system: ProvenanceDetail
    release: ProvenanceDetail
    version: ProvenanceDetail
    machine: ProvenanceDetail
    processor: ProvenanceDetail
    python_version: ProvenanceDetail
    python_implementation: ProvenanceDetail
    python_build: tuple[ProvenanceDetail, ProvenanceDetail]
    python_compiler: ProvenanceDetail


class VisionGpuIdentity(ControlPlaneModel):
    name: ProvenanceDetail
    index: CompletionInt32 = Field(ge=0, le=2_147_483_647)
    vram_bytes: CompletionInt64 = Field(gt=0, le=9_223_372_036_854_775_807)
    driver_version: ProvenanceDetail
    cuda_runtime_version: ProvenanceDetail


class VisionTrackerParameters(ControlPlaneModel):
    reference_frame_rate: float = Field(
        ge=_TRACKER_POSITIVE_MIN,
        le=_TRACKER_POSITIVE_MAX,
        allow_inf_nan=False,
    )
    track_activation_threshold: float = Field(ge=0, le=1, allow_inf_nan=False)
    high_confidence_threshold: float = Field(ge=0, le=1, allow_inf_nan=False)
    minimum_iou_threshold: float = Field(ge=0, le=1, allow_inf_nan=False)
    minimum_consecutive_frames: CompletionInt32 = Field(ge=1, le=2_147_483_647)
    lost_track_buffer_seconds: float = Field(
        ge=_TRACKER_POSITIVE_MIN,
        le=_TRACKER_POSITIVE_MAX,
        allow_inf_nan=False,
    )


class VisionRuntimeProvenance(ControlPlaneModel):
    model_id: ProvenanceIdentity
    model_version: ProvenanceIdentity
    model_manifest_sha256: Sha256
    checkpoint_sha256: Sha256
    resolved_config_sha256: Sha256
    pipeline_profile_id: ProvenanceIdentity
    pipeline_profile_version: ProvenanceIdentity
    pipeline_profile_sha256: Sha256
    qualification_id: ProvenanceIdentity | None = None
    qualification_sha256: Sha256 | None = None
    verification_status: Literal["verified", "unverified"]
    runtime_profile_id: ProvenanceIdentity
    runtime_profile_sha256: Sha256
    runtime_variant: ProvenanceIdentity
    platform_lock_sha256: Sha256 | None = None
    detector_backend: ProvenanceIdentity
    dependency_versions: dict[ProvenanceIdentity, ProvenanceIdentity] = Field(
        min_length=1,
        max_length=_COMPLETION_DEPENDENCY_VERSION_MAX_COUNT,
    )
    ffmpeg_version: ProvenanceDetail | None = None
    platform: VisionPlatformIdentity
    configured_device_policy: Literal["cpu", "cuda", "auto"]
    configured_device_index: CompletionInt32 = Field(ge=0, le=2_147_483_647)
    actual_device: ProvenanceIdentity
    gpu: VisionGpuIdentity | None = None
    mavi_build: ProvenanceIdentity
    mavi_commit: ProvenanceIdentity
    frame_policy: Literal["every-frame"]
    tracker_parameters: VisionTrackerParameters
    input_colour_space: Literal["RGB"]


    @model_validator(mode="after")
    def validate_verified_binding(self) -> "VisionRuntimeProvenance":
        if self.verification_status == "verified" and (
            self.qualification_id is None
            or self.qualification_sha256 is None
            or self.platform_lock_sha256 is None
        ):
            raise ValueError("verified provenance requires qualification and platform lock identities")
        return self


class VisionJobComplete(ControlPlaneModel):
    @classmethod
    def model_validate_json(cls, json_data, **kwargs):
        if isinstance(json_data, (bytes, bytearray)):
            try:
                text = bytes(json_data).decode("utf-8")
            except UnicodeDecodeError:
                return super().model_validate_json(json_data, **kwargs)
        else:
            text = json_data

        try:
            payload = json.loads(text, parse_float=_completion_json_float)
            payload = _normalize_completion_json_numbers(payload)
            normalized = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            return super().model_validate_json(json_data, **kwargs)

        return super().model_validate_json(normalized, **kwargs)

    schema_version: Literal["2.0"]
    job_id: UUID
    worker_id: WorkerId
    lease_token: LeaseToken
    attempt_count: CompletionInt32 = Field(ge=1, le=2_147_483_647)
    frames_processed: CompletionInt64 = Field(ge=0, le=9_223_372_036_854_775_807)
    processing_duration_ms: CompletionInt64 = Field(ge=0, le=9_223_372_036_854_775_807)
    provenance: VisionRuntimeProvenance
    tracks: tuple[VisionCompletionTrack, ...] = Field(max_length=10_000)

    @model_validator(mode="after")
    def validate_result_semantics(self) -> "VisionJobComplete":
        if self.frames_processed == 0 and self.tracks:
            raise ValueError("tracks require at least one processed frame")
        track_ids = [track.track_id for track in self.tracks]
        if len(track_ids) != len(set(track_ids)):
            raise ValueError("trackId values must be unique")
        evidence_bytes = sum(
            track.representative.thumbnail.size_bytes + track.trajectory_artifact.size_bytes
            for track in self.tracks
        )
        if evidence_bytes > _COMPLETION_EVIDENCE_MAX_BYTES:
            raise ValueError("completion evidence size limit exceeded")
        for track in self.tracks:
            if track.detection_count > self.frames_processed:
                raise ValueError("track detectionCount cannot exceed framesProcessed")
            if track.representative.source_frame_number >= self.frames_processed:
                raise ValueError(
                    "representative sourceFrameNumber must be below framesProcessed"
                )
        return self


class VisionJobCompleteResponse(ControlPlaneModel):
    schema_version: Literal["2.0"]
    job_id: UUID
    processing_run_id: UUID
    tracks_accepted: int = Field(ge=0)
    completed_at_utc: CanonicalUtcDateTime


class WorkerHealth(ControlPlaneModel):
    schema_version: Literal["2.0"]
    worker_id: WorkerId
    status: Literal["ready"]
    timestamp_utc: CanonicalUtcDateTime
