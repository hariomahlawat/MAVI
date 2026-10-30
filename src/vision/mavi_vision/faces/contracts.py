"""The worker side of the face control plane ``mavi-face-control-v1`` (PoC S6; ADR-022).

Mirrors ``contracts/schemas/face-{lease,complete,query-lease,query-complete}-v1.schema.json``. The lease capability
is never a member of any model here: it travels only in the ``X-Mavi-Lease-Capability`` header.
"""

from __future__ import annotations

from typing import Final, Literal
from uuid import UUID

from pydantic import Field, StrictInt, StrictStr

from mavi_vision.common.control_plane import CanonicalUtcDateTime, ControlPlaneModel, Sha256, WorkerId

CONTROL_VERSION: Final = "mavi-face-control-v1"
IDENTITY_SCHEMA_VERSION: Final = "mavi-face-identity-v1"
PIPELINE_SCHEMA_VERSION: Final = "mavi-face-pipeline-v1"
ROLE_ID: Final = "faces"
# One Model Pack per face pipeline serves the ``embedding`` capability (ADR-022 §2): no new capability id.
CAPABILITY_ID: Final = "embedding"
RUNTIME_PROFILE_ID: Final = "embeddings-onnx-v1"
WORKER_VERSION: Final = "1.0.0"
ALIGNMENT_ID: Final = "arcface-112-similarity-v1"
PREPROCESSING_IDS: Final = ("adaface-ir50-v1", "sface-v1")
DETECTOR_ARTIFACT_ROLE: Final = "onnx-face-detector"
EMBEDDER_ARTIFACT_ROLE: Final = "onnx-face-embedder"

ANALYSIS_ROUTE_PREFIX: Final = "/api/faces/analyses"
QUERY_ROUTE_PREFIX: Final = "/api/faces/queries"
CAPABILITY_HEADER: Final = "X-Mavi-Lease-Capability"
ATTEMPT_HEADER: Final = "X-Mavi-Attempt"
WORKER_HEADER: Final = "X-Mavi-Worker-Id"

# --- Shape bounds -------------------------------------------------------------------------------------
MAXIMUM_ANALYSIS_TRACKS: Final = 10_000
MAXIMUM_TRACK_OBSERVATIONS: Final = 16
MAXIMUM_FACES_PER_CROP: Final = 8
MAXIMUM_FACES_PER_TRACK: Final = MAXIMUM_TRACK_OBSERVATIONS * MAXIMUM_FACES_PER_CROP
MAXIMUM_FACES_PER_QUERY: Final = 16
MAXIMUM_EVIDENCE_BYTES: Final = 16 * 1024 * 1024
MAXIMUM_QUERY_IMAGE_BYTES: Final = 2 * 1024 * 1024
# A query image is decoded only up to this many pixels (a decompression-bomb guard independent of Pillow's global).
MAXIMUM_QUERY_IMAGE_PIXELS: Final = 4096 * 4096
MAXIMUM_LEASE_RESPONSE_BYTES: Final = 64 * 1024 * 1024
MAXIMUM_COMPLETION_REQUEST_BYTES: Final = 64 * 1024 * 1024
MAXIMUM_QUERY_LEASE_BYTES: Final = 64 * 1024
MAXIMUM_FAILURE_MESSAGE_LENGTH: Final = 2000
THUMBNAIL_JPEG_QUALITY: Final = 90

# --- Vocabulary ---------------------------------------------------------------------------------------
TRACK_OBSERVED: Final = "observed"
TRACK_UNKNOWN: Final = "unknown"
REASON_NO_EVIDENCE: Final = "no_evidence"
REASON_EVIDENCE_UNAVAILABLE: Final = "evidence_unavailable"
REASON_NO_FACE_DETECTED: Final = "no_face_detected"
REASON_FACE_TOO_SMALL: Final = "face_too_small"

FAILURE_RUNTIME: Final = "face_runtime_failed"
FAILURE_EVIDENCE_TRANSPORT: Final = "face_evidence_transport_failed"
FAILURE_MODEL_UNAVAILABLE: Final = "face_model_unavailable"
FAILURE_CANCELLED: Final = "face_cancelled"
FAILURE_OUTPUT_INVALID: Final = "face_output_invalid"
FAILURE_QUERY_RUNTIME: Final = "face_query_runtime_failed"
FAILURE_QUERY_IMAGE_INVALID: Final = "face_query_image_invalid"
FAILURE_CODE_RETRYABLE: Final = {
    FAILURE_RUNTIME: True,
    FAILURE_EVIDENCE_TRANSPORT: True,
    FAILURE_MODEL_UNAVAILABLE: True,
    FAILURE_CANCELLED: True,
    FAILURE_OUTPUT_INVALID: False,
}
QUERY_FAILURE_CODE_RETRYABLE: Final = {FAILURE_QUERY_RUNTIME: True, FAILURE_QUERY_IMAGE_INVALID: False}

# Problem codes that mean this attempt no longer owns its lease: stop, never /fail, never retry.
LEASE_LOST_CODES: Final = frozenset(
    {
        "face_lease_invalid",
        "face_not_running",
        "face_attempt_stale",
        "face_deadline_exceeded",
        "face_analysis_not_found",
        "face_query_not_found",
    }
)
EVIDENCE_MISSING_CODE: Final = "face_evidence_missing"
EVIDENCE_INTEGRITY_FAILED_CODE: Final = "face_evidence_integrity_failed"
COMPLETION_INVALID_CODE: Final = "face_completion_invalid"
QUERY_IMAGE_MISSING_CODE: Final = "face_query_image_missing"


class ModelIdentityContract(ControlPlaneModel):
    id: StrictStr = Field(min_length=1, max_length=128)
    version: StrictStr = Field(min_length=1, max_length=64)
    manifest_sha256: Sha256
    dimension: StrictInt = Field(ge=1, le=4096)


class PipelineIdentityContract(ControlPlaneModel):
    id: StrictStr = Field(min_length=1, max_length=64)
    version: StrictStr = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    sha256: Sha256


class IdentityContract(ControlPlaneModel):
    fingerprint: Sha256
    schema_version: Literal["mavi-face-identity-v1"]
    model: ModelIdentityContract
    pipeline: PipelineIdentityContract


class LeaseObservation(ControlPlaneModel):
    observation_id: UUID
    role: StrictStr = Field(max_length=64, pattern=r"^[a-z](?:-?[a-z0-9])*$")
    evidence_rank: StrictInt = Field(ge=0)
    size_bytes: StrictInt = Field(ge=1, le=MAXIMUM_EVIDENCE_BYTES)
    sha256: Sha256


class LeaseTrack(ControlPlaneModel):
    track_id: UUID
    object_class: Literal["Person"]
    observations: tuple[LeaseObservation, ...] = Field(max_length=MAXIMUM_TRACK_OBSERVATIONS)


class FaceLease(ControlPlaneModel):
    schema_version: Literal["mavi-face-control-v1"]
    analysis_id: UUID
    processing_run_id: UUID
    worker_id: WorkerId
    attempt_count: StrictInt = Field(ge=1, le=2_147_483_647)
    lease_expires_at_utc: CanonicalUtcDateTime
    deadline_at_utc: CanonicalUtcDateTime
    identity: IdentityContract
    tracks: tuple[LeaseTrack, ...] = Field(max_length=MAXIMUM_ANALYSIS_TRACKS)


class HeartbeatResponse(ControlPlaneModel):
    schema_version: Literal["mavi-face-control-v1"]
    lease_expires_at_utc: CanonicalUtcDateTime


class FailResponse(ControlPlaneModel):
    schema_version: Literal["mavi-face-control-v1"]
    outcome: Literal["requeued", "failed"]


class CompleteResponse(ControlPlaneModel):
    schema_version: Literal["mavi-face-control-v1"]
    analysis_id: UUID
    processing_run_id: UUID
    status: Literal["completed", "superseded"]
    completed_at_utc: CanonicalUtcDateTime
    tracks_observed: StrictInt = Field(ge=0)
    tracks_unknown: StrictInt = Field(ge=0)


class QueryImage(ControlPlaneModel):
    mime_type: Literal["image/jpeg", "image/png"]
    size_bytes: StrictInt = Field(ge=1, le=MAXIMUM_QUERY_IMAGE_BYTES)
    sha256: Sha256


class FaceQueryLease(ControlPlaneModel):
    schema_version: Literal["mavi-face-control-v1"]
    query_id: UUID
    worker_id: WorkerId
    attempt_count: StrictInt = Field(ge=1, le=2_147_483_647)
    lease_expires_at_utc: CanonicalUtcDateTime
    identity: IdentityContract
    image: QueryImage


class QueryCompleteResponse(ControlPlaneModel):
    schema_version: Literal["mavi-face-control-v1"]
    status: Literal["completed"]
