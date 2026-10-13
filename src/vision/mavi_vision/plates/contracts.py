"""The worker side of the plate control plane ``mavi-plate-control-v1`` (Stage 4 plan §5.3).

Mirrors ``Mavi.Contracts.Worker.Plates.PlateContractRules`` and the JSON Schemas
``contracts/schemas/plate-{lease,complete,predictions}-v1.schema.json``. The lease capability is never
a member of any model here: it travels only in the ``X-Mavi-Lease-Capability`` header.
"""

from __future__ import annotations

from typing import Final, Literal
from uuid import UUID

from pydantic import Field

from mavi_vision.common.control_plane import CanonicalUtcDateTime, ControlPlaneModel, Sha256, WorkerId

CONTROL_VERSION: Final = "mavi-plate-control-v1"
PROVENANCE_CONTRACT: Final = "plate-complete-v1"
PREDICTIONS_SCHEMA_VERSION: Final = "mavi-plate-predictions-v1"
PREDICTIONS_MEDIA_TYPE: Final = "application/json"
IDENTITY_SCHEMA_VERSION: Final = "mavi-plate-identity-v1"
NORMALISATION_ID: Final = "mavi-plate-normalisation-v1"
# SHA-256 of contracts/test-vectors/plate-normalisation-v1.json, frozen 2026-10-13 (pinned by test, as in .NET).
NORMALISATION_SHA256: Final = "6e505158a735a1c4c5d96ad33d08e4ddb0b98d456f0dd532a6af25de120bf935"

ROUTE_PREFIX: Final = "/api/plates/analyses"
CAPABILITY_HEADER: Final = "X-Mavi-Lease-Capability"
ATTEMPT_HEADER: Final = "X-Mavi-Attempt"
WORKER_HEADER: Final = "X-Mavi-Worker-Id"
CONTENT_SHA256_HEADER: Final = "X-Mavi-Content-Sha256"

CAPABILITY_OCR: Final = "ocr"
CAPABILITY_PLATE_DETECTOR: Final = "plate-detector"
CAPABILITIES: Final = (CAPABILITY_OCR, CAPABILITY_PLATE_DETECTOR)

ROLES: Final = ("representative", "near-view", "early-diverse", "late-diverse")

# --- Shape bounds ---------------------------------------------------------------------------------
MAXIMUM_ANALYSIS_TRACKS: Final = 10_000
MAXIMUM_TRACK_OBSERVATIONS: Final = 4
# The bounded v1 processing profile (owner decision 2026-10-13): at most two detector proposals per crop,
# one accepted plate per crop, three candidate readings for it. Output beyond a configured bound is a
# contract violation (the attempt fails with plate_output_invalid); it is never truncated.
MAXIMUM_DETECTIONS_PER_CROP: Final = 2
MAXIMUM_PLATES_PER_CROP: Final = 1
MAXIMUM_READINGS_PER_PLATE: Final = 3
MAXIMUM_TRACK_PLATE_OBSERVATIONS: Final = MAXIMUM_TRACK_OBSERVATIONS * MAXIMUM_PLATES_PER_CROP
MAXIMUM_RAW_TEXT_LENGTH: Final = 32  # UTF-16 code units
MAXIMUM_RAW_LINE_COUNT: Final = 2
MAXIMUM_NORMALISATION_EXPANSION: Final = 4
MAXIMUM_NORMALISED_TEXT_LENGTH: Final = MAXIMUM_RAW_TEXT_LENGTH * MAXIMUM_NORMALISATION_EXPANSION
MAXIMUM_CROP_DIMENSION: Final = 4096
MAXIMUM_LEASE_RESPONSE_BYTES: Final = 16 * 1024 * 1024
MAXIMUM_PREDICTION_ARTIFACT_BYTES: Final = 64 * 1024 * 1024
MAXIMUM_COMPLETION_REQUEST_BYTES: Final = 64 * 1024 * 1024
MAXIMUM_FAILURE_MESSAGE_LENGTH: Final = 4000

# --- Byte envelopes (upper bounds on one element's compact canonical JSON; see the .NET rules) -----
RAW_TEXT_WORST_CASE_BYTES: Final = MAXIMUM_RAW_TEXT_LENGTH * 6
ARTIFACT_HEADER_BYTES: Final = 4096
ARTIFACT_TRACK_ENVELOPE_BYTES: Final = 160
ARTIFACT_CROP_ENVELOPE_BYTES: Final = 256
ARTIFACT_DETECTION_ENVELOPE_BYTES: Final = 96
ARTIFACT_PLATE_ENVELOPE_BYTES: Final = 64
ARTIFACT_READING_ENVELOPE_BYTES: Final = 96
ARTIFACT_TEXT_ENVELOPE_BYTES: Final = 160
COMPLETION_HEADER_BYTES: Final = 16 * 1024
COMPLETION_TRACK_ENVELOPE_BYTES: Final = 160
COMPLETION_OBSERVATION_ENVELOPE_BYTES: Final = 288
COMPLETION_READING_ENVELOPE_BYTES: Final = 96
COMPLETION_TEXT_ENVELOPE_BYTES: Final = 192

# --- Vocabulary -------------------------------------------------------------------------------------
TRACK_ANALYSED: Final = "analysed"
TRACK_UNAVAILABLE: Final = "unavailable"
PLATE_READ: Final = "read"
PLATE_UNREADABLE: Final = "unreadable"
CROP_SCORED: Final = "scored"
CROP_ABSTAINED: Final = "abstained"
CROP_EXCLUDED: Final = "excluded"
CROP_UNAVAILABLE: Final = "unavailable"
CROP_ABSTENTION_REASONS: Final = frozenset({"decode_failed", "detector_error", "ocr_error", "ocr_output_invalid"})
CROP_UNAVAILABLE_REASONS: Final = frozenset({"evidence_missing", "evidence_integrity_failed"})
# Most severe first; a Track with no scored crop reports the first one its crops caused.
TRACK_UNAVAILABLE_REASONS_BY_SEVERITY: Final = (
    "evidence_integrity_failed",
    "evidence_missing",
    "evidence_decode_failed",
    "plate_inference_failed",
    "no_accepted_evidence",
)
FAILURE_CODE_RETRYABLE: Final = {
    "plate_evidence_transport_failed": True,
    "plate_upload_transport_failed": True,
    "plate_capability_unavailable": True,
    "plate_inference_failed": True,
    "plate_output_invalid": False,
    "plate_contract_violation": False,
    # The platform found a crop this worker reported unavailable intact at rest; the next attempt re-reads it.
    "plate_evidence_claim_contradicted": True,
}
EVIDENCE_CLAIM_CONTRADICTED: Final = "plate_evidence_claim_contradicted"


def is_profile_shape_in_range(max_detections: int, max_plates: int, max_readings: int) -> bool:
    return (
        1 <= max_detections <= MAXIMUM_DETECTIONS_PER_CROP
        and 1 <= max_plates <= MAXIMUM_PLATES_PER_CROP
        and max_plates <= max_detections
        and 1 <= max_readings <= MAXIMUM_READINGS_PER_PLATE
    )


def _require_shape(max_detections: int, max_plates: int, max_readings: int) -> None:
    if not is_profile_shape_in_range(max_detections, max_plates, max_readings):
        raise ValueError("plate_profile_shape_out_of_range")


def worst_case_prediction_artifact_bytes(max_detections: int, max_plates: int, max_readings: int) -> int:
    """The largest ``PlatePredictions`` an honest worker can produce at 10,000 Tracks x 4 crops."""
    _require_shape(max_detections, max_plates, max_readings)
    reading = ARTIFACT_READING_ENVELOPE_BYTES + RAW_TEXT_WORST_CASE_BYTES
    plate = ARTIFACT_PLATE_ENVELOPE_BYTES + max_readings * reading
    crop = ARTIFACT_CROP_ENVELOPE_BYTES + max_detections * ARTIFACT_DETECTION_ENVELOPE_BYTES + max_plates * plate
    texts = MAXIMUM_TRACK_OBSERVATIONS * max_plates * ARTIFACT_TEXT_ENVELOPE_BYTES
    track = ARTIFACT_TRACK_ENVELOPE_BYTES + MAXIMUM_TRACK_OBSERVATIONS * crop + texts
    return ARTIFACT_HEADER_BYTES + MAXIMUM_ANALYSIS_TRACKS * track


def worst_case_completion_body_bytes(max_detections: int, max_plates: int, max_readings: int) -> int:
    """The largest completion body an honest worker can send at 10,000 Tracks x 4 crops."""
    _require_shape(max_detections, max_plates, max_readings)
    reading = COMPLETION_READING_ENVELOPE_BYTES + RAW_TEXT_WORST_CASE_BYTES
    observation = COMPLETION_OBSERVATION_ENVELOPE_BYTES + max_readings * reading
    plates = MAXIMUM_TRACK_OBSERVATIONS * max_plates
    track = COMPLETION_TRACK_ENVELOPE_BYTES + plates * observation + plates * COMPLETION_TEXT_ENVELOPE_BYTES
    return COMPLETION_HEADER_BYTES + MAXIMUM_ANALYSIS_TRACKS * track


def is_admissible_profile_shape(max_detections: int, max_plates: int, max_readings: int) -> bool:
    return (
        is_profile_shape_in_range(max_detections, max_plates, max_readings)
        and worst_case_prediction_artifact_bytes(max_detections, max_plates, max_readings) <= MAXIMUM_PREDICTION_ARTIFACT_BYTES
        and worst_case_completion_body_bytes(max_detections, max_plates, max_readings) <= MAXIMUM_COMPLETION_REQUEST_BYTES
    )


def utf16_length(text: str) -> int:
    """UTF-16 code units, the unit .NET counts; a lone surrogate (which Python allows) counts as one."""
    return sum(2 if ord(character) > 0xFFFF else 1 for character in text)


def reading_rank_key(confidence: float, raw_text: str) -> tuple[float, bytes]:
    """The rank order of one plate's readings (vector ``contracts/test-vectors/plate-reading-order-v1.json``).

    Confidence descending, then raw text in ascending UTF-16 code-unit order -- the platform's
    ``string.CompareOrdinal``. Python's ``str`` order is code-point order, which differs for characters
    outside the Basic Multilingual Plane; UTF-16BE bytes compare exactly like UTF-16 code units.
    """
    return (-confidence, raw_text.encode("utf-16-be", "surrogatepass"))


def is_raw_text(value: object) -> bool:
    """The wire rule for raw OCR text (ADR-013 item 13), identical to ``PlateContractRules.IsRawText``."""
    if not isinstance(value, str) or not 1 <= utf16_length(value) <= MAXIMUM_RAW_TEXT_LENGTH:
        return False
    for character in value:
        code = ord(character)
        if 0xD800 <= code <= 0xDFFF:  # a lone surrogate: Python strings can hold one
            return False
        if character != "\n" and (code < 0x20 or code == 0x7F):
            return False
    if value.startswith("\n") or value.endswith("\n"):
        return False
    return value.count("\n") < MAXIMUM_RAW_LINE_COUNT


def raw_line_count(value: str) -> int:
    return 1 + value.count("\n")


class CapabilityIdentityContract(ControlPlaneModel):
    capability_id: str
    model_pack_id: str


class NormalisationIdentityContract(ControlPlaneModel):
    id: Literal["mavi-plate-normalisation-v1"]
    sha256: Sha256


class SummaryPolicyIdentityContract(ControlPlaneModel):
    id: str
    version: str
    sha256: Sha256


class IdentityContract(ControlPlaneModel):
    fingerprint: Sha256
    pipeline_id: str
    pipeline_version: str
    predictions_schema_version: Literal["mavi-plate-predictions-v1"]
    normalisation: NormalisationIdentityContract
    summary_policy: SummaryPolicyIdentityContract
    capabilities: tuple[CapabilityIdentityContract, ...] = Field(min_length=2, max_length=2)
    parameters_sha256: Sha256


class LeaseObservation(ControlPlaneModel):
    observation_id: UUID
    role: Literal["representative", "near-view", "early-diverse", "late-diverse"]
    evidence_rank: int = Field(ge=0, le=3)
    size_bytes: int = Field(ge=1, le=MAXIMUM_PREDICTION_ARTIFACT_BYTES)
    sha256: Sha256


class LeaseTrack(ControlPlaneModel):
    track_id: UUID
    object_class: Literal["vehicle"]
    observations: tuple[LeaseObservation, ...] = Field(max_length=MAXIMUM_TRACK_OBSERVATIONS)


class PlateLease(ControlPlaneModel):
    schema_version: Literal["mavi-plate-control-v1"]
    analysis_id: UUID
    processing_run_id: UUID
    worker_id: WorkerId
    attempt_count: int = Field(ge=1, le=2_147_483_647)
    lease_expires_at_utc: CanonicalUtcDateTime
    deadline_at_utc: CanonicalUtcDateTime
    identity: IdentityContract
    tracks: tuple[LeaseTrack, ...] = Field(max_length=MAXIMUM_ANALYSIS_TRACKS)


class HeartbeatResponse(ControlPlaneModel):
    schema_version: Literal["mavi-plate-control-v1"]
    lease_expires_at_utc: CanonicalUtcDateTime


class FailResponse(ControlPlaneModel):
    schema_version: Literal["mavi-plate-control-v1"]
    outcome: Literal["requeued", "failed"]


class UploadResponse(ControlPlaneModel):
    schema_version: Literal["mavi-plate-control-v1"]
    status: Literal["stored", "already_stored"]
    size_bytes: int
    sha256: Sha256


class CompleteResponse(ControlPlaneModel):
    schema_version: Literal["mavi-plate-control-v1"]
    analysis_id: UUID
    processing_run_id: UUID
    status: Literal["completed", "superseded"]
    completed_at_utc: CanonicalUtcDateTime
    tracks_analysed: int = Field(ge=0)
    tracks_unavailable: int = Field(ge=0)
