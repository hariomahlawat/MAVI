"""The worker side of the attribute control plane (S2b plan §9; ADR-013 amendment 2026-09-28).

Mirrors ``Mavi.Contracts.Worker.Attributes``. The lease capability is never a member of any
model here: it travels only in the ``X-Mavi-Lease-Capability`` header, and the client holds it
beside the lease rather than inside it, so no serialisation of a model can carry it.
"""

from __future__ import annotations

from typing import Final, Literal
from uuid import UUID

from pydantic import Field

from mavi_vision.common.control_plane import (
    CanonicalUtcDateTime,
    ControlPlaneModel,
    Sha256,
    WorkerId,
)

CONTROL_VERSION: Final = "mavi-visual-attribute-control-v1"
PROVENANCE_CONTRACT: Final = "visual-attribute-complete-v1"
PREDICTIONS_SCHEMA_VERSION: Final = "mavi-attribute-predictions-v1"
PREDICTIONS_MEDIA_TYPE: Final = "application/json"

ROUTE_PREFIX: Final = "/api/attributes/analyses"
CAPABILITY_HEADER: Final = "X-Mavi-Lease-Capability"
ATTEMPT_HEADER: Final = "X-Mavi-Attempt"
WORKER_HEADER: Final = "X-Mavi-Worker-Id"
CONTENT_SHA256_HEADER: Final = "X-Mavi-Content-Sha256"

MAXIMUM_ANALYSIS_TRACKS: Final = 10_000
MAXIMUM_TRACK_OBSERVATIONS: Final = 4
# The lease response is the largest body the worker reads; beyond this it is refused
# unread (S2b plan §15; implementation record §4: ~8.4 MB at 10,000 Tracks x 4 crops).
MAXIMUM_LEASE_RESPONSE_BYTES: Final = 16 * 1024 * 1024
MAXIMUM_PREDICTION_ARTIFACT_BYTES: Final = 64 * 1024 * 1024
MAXIMUM_COMPLETION_REQUEST_BYTES: Final = 32 * 1024 * 1024
MAXIMUM_FAILURE_MESSAGE_LENGTH: Final = 4000

OUTCOME_ANALYSED: Final = "analysed"
OUTCOME_UNAVAILABLE: Final = "unavailable"
OUTCOME_OBSERVED: Final = "observed"
OUTCOME_UNKNOWN: Final = "unknown"

# Track-level Unavailable reasons: only platform-authoritative evidence conditions.
UNAVAILABLE_REASONS: Final = frozenset(
    {"evidence_missing", "evidence_integrity_failed", "evidence_decode_failed", "no_accepted_evidence"}
)

# Worker failure codes and whether each is retryable (VisualAttributeContractRules).
FAILURE_CODE_RETRYABLE: Final = {
    "visual_attribute_evidence_transport_failed": True,
    "visual_attribute_upload_transport_failed": True,
    "visual_attribute_capability_unavailable": True,
    "visual_attribute_inference_failed": True,
    "visual_attribute_output_invalid": False,
    "visual_attribute_contract_violation": False,
}


class CapabilityIdentityContract(ControlPlaneModel):
    capability_id: str
    model_pack_id: str


class IdentityContract(ControlPlaneModel):
    fingerprint: Sha256
    attribute_schema_id: str
    attribute_schema_version: str
    attribute_schema_sha256: Sha256
    pipeline_id: str
    pipeline_version: str
    aggregation_policy_id: str
    aggregation_policy_version: str
    aggregation_policy_sha256: Sha256
    capabilities: tuple[CapabilityIdentityContract, ...]
    parameters_sha256: Sha256


class LeaseObservation(ControlPlaneModel):
    observation_id: UUID
    role: str
    evidence_rank: int = Field(ge=0, le=3)
    size_bytes: int = Field(ge=1, le=MAXIMUM_PREDICTION_ARTIFACT_BYTES)
    sha256: Sha256


class LeaseTrack(ControlPlaneModel):
    track_id: UUID
    object_class: Literal["person", "vehicle"]
    observations: tuple[LeaseObservation, ...] = Field(max_length=MAXIMUM_TRACK_OBSERVATIONS)


class AttributeLease(ControlPlaneModel):
    schema_version: Literal["mavi-visual-attribute-control-v1"]
    analysis_id: UUID
    processing_run_id: UUID
    worker_id: WorkerId
    attempt_count: int = Field(ge=1, le=2_147_483_647)
    lease_expires_at_utc: CanonicalUtcDateTime
    deadline_at_utc: CanonicalUtcDateTime
    identity: IdentityContract
    tracks: tuple[LeaseTrack, ...] = Field(max_length=MAXIMUM_ANALYSIS_TRACKS)


class HeartbeatResponse(ControlPlaneModel):
    schema_version: Literal["mavi-visual-attribute-control-v1"]
    lease_expires_at_utc: CanonicalUtcDateTime


class FailResponse(ControlPlaneModel):
    schema_version: Literal["mavi-visual-attribute-control-v1"]
    outcome: Literal["requeued", "failed"]


class UploadResponse(ControlPlaneModel):
    schema_version: Literal["mavi-visual-attribute-control-v1"]
    status: Literal["stored", "already_stored"]
    size_bytes: int
    sha256: Sha256


class CompleteResponse(ControlPlaneModel):
    schema_version: Literal["mavi-visual-attribute-control-v1"]
    analysis_id: UUID
    processing_run_id: UUID
    status: Literal["completed", "superseded"]
    completed_at_utc: CanonicalUtcDateTime
    tracks_analysed: int = Field(ge=0)
    tracks_unavailable: int = Field(ge=0)


__all__ = [
    "ATTEMPT_HEADER",
    "AttributeLease",
    "CAPABILITY_HEADER",
    "CONTENT_SHA256_HEADER",
    "CONTROL_VERSION",
    "CapabilityIdentityContract",
    "CompleteResponse",
    "FAILURE_CODE_RETRYABLE",
    "FailResponse",
    "HeartbeatResponse",
    "IdentityContract",
    "LeaseObservation",
    "LeaseTrack",
    "MAXIMUM_ANALYSIS_TRACKS",
    "MAXIMUM_COMPLETION_REQUEST_BYTES",
    "MAXIMUM_FAILURE_MESSAGE_LENGTH",
    "MAXIMUM_LEASE_RESPONSE_BYTES",
    "MAXIMUM_PREDICTION_ARTIFACT_BYTES",
    "MAXIMUM_TRACK_OBSERVATIONS",
    "OUTCOME_ANALYSED",
    "OUTCOME_OBSERVED",
    "OUTCOME_UNAVAILABLE",
    "OUTCOME_UNKNOWN",
    "PREDICTIONS_MEDIA_TYPE",
    "PREDICTIONS_SCHEMA_VERSION",
    "PROVENANCE_CONTRACT",
    "ROUTE_PREFIX",
    "UNAVAILABLE_REASONS",
    "UploadResponse",
    "WORKER_HEADER",
]
