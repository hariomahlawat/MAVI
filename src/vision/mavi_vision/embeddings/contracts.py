"""The worker side of the embedding control plane ``mavi-embedding-control-v1`` (PoC S4; ADR-021 §3–§4).

Mirrors ``contracts/schemas/embedding-{lease,complete,text-query-lease,text-query-complete}-v1.schema.json`` and
the C# records in ``Mavi.Contracts/Worker/Embeddings``. The lease capability is never a member of any model here:
it travels only in the ``X-Mavi-Lease-Capability`` header.
"""

from __future__ import annotations

from typing import Final, Literal
from uuid import UUID

from pydantic import Field, StrictInt, StrictStr

from mavi_vision.common.control_plane import CanonicalUtcDateTime, ControlPlaneModel, Sha256, WorkerId

CONTROL_VERSION: Final = "mavi-embedding-control-v1"
IDENTITY_SCHEMA_VERSION: Final = "mavi-embedding-identity-v1"
PIPELINE_SCHEMA_VERSION: Final = "mavi-embedding-pipeline-v1"
ROLE_ID: Final = "embeddings"
CAPABILITY_ID: Final = "embedding"
RUNTIME_PROFILE_ID: Final = "embeddings-onnx-v1"
WORKER_VERSION: Final = "1.0.0"
PREPROCESSING_ID: Final = "siglip2-fixed-224-v1"
AGGREGATION_ID: Final = "mean-l2-v1"

ANALYSIS_ROUTE_PREFIX: Final = "/api/embeddings/analyses"
TEXT_QUERY_ROUTE_PREFIX: Final = "/api/embeddings/text-queries"
CAPABILITY_HEADER: Final = "X-Mavi-Lease-Capability"
ATTEMPT_HEADER: Final = "X-Mavi-Attempt"
WORKER_HEADER: Final = "X-Mavi-Worker-Id"

# --- Shape bounds -------------------------------------------------------------------------------------
MAXIMUM_ANALYSIS_TRACKS: Final = 10_000
MAXIMUM_TRACK_OBSERVATIONS: Final = 16
MAXIMUM_EVIDENCE_BYTES: Final = 16 * 1024 * 1024
# 10,000 Tracks x 16 observations of about 200 bytes each is about 32 MB of lease; the bound leaves headroom.
MAXIMUM_LEASE_RESPONSE_BYTES: Final = 64 * 1024 * 1024
# 10,000 embedded Tracks x (4,096 base64 characters + 16 ids) is about 47 MB of completion.
MAXIMUM_COMPLETION_REQUEST_BYTES: Final = 64 * 1024 * 1024
MAXIMUM_TEXT_QUERY_LEASE_BYTES: Final = 64 * 1024
MAXIMUM_FAILURE_MESSAGE_LENGTH: Final = 4000
MAXIMUM_TEXT_CHARACTERS: Final = 200
VECTOR_NORM_TOLERANCE: Final = 1e-3

# --- Vocabulary ---------------------------------------------------------------------------------------
TRACK_EMBEDDED: Final = "embedded"
TRACK_UNAVAILABLE: Final = "unavailable"
REASON_NO_EVIDENCE: Final = "no_evidence"
REASON_EVIDENCE_TOO_SMALL: Final = "evidence_too_small"
REASON_EVIDENCE_UNAVAILABLE: Final = "evidence_unavailable"

FAILURE_RUNTIME: Final = "embedding_runtime_failed"
FAILURE_EVIDENCE_TRANSPORT: Final = "embedding_evidence_transport_failed"
FAILURE_MODEL_UNAVAILABLE: Final = "embedding_model_unavailable"
FAILURE_CANCELLED: Final = "embedding_cancelled"
FAILURE_OUTPUT_INVALID: Final = "embedding_output_invalid"
FAILURE_TEXT_RUNTIME: Final = "embedding_text_runtime_failed"
FAILURE_TEXT_INVALID: Final = "embedding_text_invalid"
FAILURE_CODE_RETRYABLE: Final = {
    FAILURE_RUNTIME: True,
    FAILURE_EVIDENCE_TRANSPORT: True,
    FAILURE_MODEL_UNAVAILABLE: True,
    FAILURE_CANCELLED: True,
    FAILURE_OUTPUT_INVALID: False,
}
TEXT_FAILURE_CODE_RETRYABLE: Final = {FAILURE_TEXT_RUNTIME: True, FAILURE_TEXT_INVALID: False}

# Problem codes that mean this attempt no longer owns its lease: stop, never /fail, never retry.
LEASE_LOST_CODES: Final = frozenset(
    {
        "embedding_lease_invalid",
        "embedding_not_running",
        "embedding_attempt_stale",
        "embedding_deadline_exceeded",
        "embedding_analysis_not_found",
        "embedding_text_query_not_found",
    }
)
EVIDENCE_MISSING_CODE: Final = "embedding_evidence_missing"
EVIDENCE_INTEGRITY_FAILED_CODE: Final = "embedding_evidence_integrity_failed"


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
    schema_version: Literal["mavi-embedding-identity-v1"]
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
    object_class: Literal["Person", "Vehicle"]
    observations: tuple[LeaseObservation, ...] = Field(max_length=MAXIMUM_TRACK_OBSERVATIONS)


class EmbeddingLease(ControlPlaneModel):
    schema_version: Literal["mavi-embedding-control-v1"]
    analysis_id: UUID
    processing_run_id: UUID
    worker_id: WorkerId
    attempt_count: StrictInt = Field(ge=1, le=2_147_483_647)
    lease_expires_at_utc: CanonicalUtcDateTime
    deadline_at_utc: CanonicalUtcDateTime
    identity: IdentityContract
    tracks: tuple[LeaseTrack, ...] = Field(max_length=MAXIMUM_ANALYSIS_TRACKS)


class HeartbeatResponse(ControlPlaneModel):
    schema_version: Literal["mavi-embedding-control-v1"]
    lease_expires_at_utc: CanonicalUtcDateTime


class FailResponse(ControlPlaneModel):
    schema_version: Literal["mavi-embedding-control-v1"]
    outcome: Literal["requeued", "failed"]


class CompleteResponse(ControlPlaneModel):
    schema_version: Literal["mavi-embedding-control-v1"]
    analysis_id: UUID
    processing_run_id: UUID
    status: Literal["completed", "superseded"]
    completed_at_utc: CanonicalUtcDateTime
    tracks_embedded: StrictInt = Field(ge=0)
    tracks_unavailable: StrictInt = Field(ge=0)


class TextQueryLease(ControlPlaneModel):
    schema_version: Literal["mavi-embedding-control-v1"]
    query_id: UUID
    worker_id: WorkerId
    attempt_count: StrictInt = Field(ge=1, le=2_147_483_647)
    lease_expires_at_utc: CanonicalUtcDateTime
    identity_fingerprint: Sha256
    text: StrictStr = Field(min_length=1, max_length=MAXIMUM_TEXT_CHARACTERS)


class TextQueryCompleteResponse(ControlPlaneModel):
    schema_version: Literal["mavi-embedding-control-v1"]
    status: Literal["completed"]

