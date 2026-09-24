from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from re import fullmatch
from uuid import UUID

from mavi_vision.evidence.policy import SCORE_SCALE
from mavi_vision.evidence.roles import ROLE_ORDER, EvidenceRole, role_cap_bytes


_SHA256_PATTERN = r"[0-9a-f]{64}"
_TRACK_ID_PATTERN = r"[a-z0-9][a-z0-9._-]{0,63}"
# The completion contract carries at most this many Tracks (schema maxItems,
# WorkerContractRules.MaximumCompletionTracks). The pipeline refuses the next
# Track rather than stage evidence for a result that could never be sent.
MAXIMUM_TRACKS_PER_RESULT = 10_000
_STORAGE_SEGMENT_PATTERN = r"[^/\\]+"


class ObjectClass(StrEnum):
    PERSON = "person"
    VEHICLE = "vehicle"


def _require_unit_interval(value: float, name: str) -> None:
    if not isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name}_out_of_range")


def _validate_storage_key(value: str) -> None:
    if not value or len(value) > 512 or value.startswith(("/", "\\")) or "\\" in value:
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
class ObservationDescriptor:
    """One staged Track Evidence Set observation: scalars plus the crop descriptor.

    Scores are held as exact integer millionths (the only form the selector
    compares); ``quality_score`` and ``selection_score`` are their float views.
    """

    role: EvidenceRole
    rank: int
    offset_ms: int
    source_frame_number: int
    confidence: float
    bounding_box: NormalizedBoundingBox
    quality_micro: int
    selection_micro: int
    crop: ArtifactDescriptor

    def __post_init__(self) -> None:
        if not isinstance(self.role, EvidenceRole):
            raise ValueError("observation_role_invalid")
        if not 0 <= self.rank < len(ROLE_ORDER):
            raise ValueError("observation_rank_invalid")
        if (self.role is EvidenceRole.REPRESENTATIVE) != (self.rank == 0):
            raise ValueError("observation_rank_invalid")
        if self.offset_ms < 0 or self.source_frame_number < 0:
            raise ValueError("observation_offset_invalid")
        _require_unit_interval(self.confidence, "observation_confidence")
        for micro in (self.quality_micro, self.selection_micro):
            if isinstance(micro, bool) or not isinstance(micro, int) or not 0 <= micro <= SCORE_SCALE:
                raise ValueError("observation_score_invalid")
        if self.crop.media_type != "image/jpeg":
            raise ValueError("observation_crop_media_type_invalid")
        if not 0 < self.crop.size_bytes <= role_cap_bytes(self.role):
            raise ValueError("observation_crop_size_invalid")

    @property
    def quality_score(self) -> float:
        return self.quality_micro / SCORE_SCALE

    @property
    def selection_score(self) -> float:
        return self.selection_micro / SCORE_SCALE


@dataclass(frozen=True, slots=True)
class ProcessedTrack:
    """A finalised Track: scalar summary plus staged-artifact descriptors only.

    It deliberately carries no trajectory points and no image bytes. A Track is
    finalised when its lifecycle ends, possibly long before end-of-stream, and the
    result keeps one of these per Track until completion; holding points or
    encoded evidence here would make completion memory grow with the run. The
    points live on only as ``trajectory_artifact`` and each evidence image only
    as its observation's ``crop`` descriptor.
    """

    track_id: str
    object_class: ObjectClass
    start_offset_ms: int
    end_offset_ms: int
    detection_count: int
    mean_confidence: float
    max_confidence: float
    observations: tuple[ObservationDescriptor, ...]
    trajectory_artifact: ArtifactDescriptor

    def __post_init__(self) -> None:
        if fullmatch(_TRACK_ID_PATTERN, self.track_id) is None:
            raise ValueError("track_id_invalid")
        if self.start_offset_ms < 0 or self.end_offset_ms < self.start_offset_ms:
            raise ValueError("track_offsets_invalid")
        if self.detection_count <= 0:
            raise ValueError("track_detection_count_invalid")
        _require_unit_interval(self.mean_confidence, "track_mean_confidence")
        _require_unit_interval(self.max_confidence, "track_max_confidence")
        if self.mean_confidence > self.max_confidence:
            raise ValueError("track_confidence_order_invalid")
        _validate_observations(self)

    @property
    def representative(self) -> ObservationDescriptor:
        return self.observations[0]

    @property
    def confidence(self) -> float:
        """Backward-compatible read alias for the historical mean-confidence field."""
        return self.mean_confidence


def _validate_observations(track: ProcessedTrack) -> None:
    """Canonical Evidence Set shape: exactly one Representative at rank 0, then
    supplemental roles in role order, contiguous ranks, one source frame each."""
    observations = track.observations
    if not isinstance(observations, tuple) or not 1 <= len(observations) <= len(ROLE_ORDER):
        raise ValueError("track_observations_invalid")
    previous_role_index = -1
    frames: set[int] = set()
    for rank, observation in enumerate(observations):
        if not isinstance(observation, ObservationDescriptor) or observation.rank != rank:
            raise ValueError("track_observation_rank_invalid")
        role_index = ROLE_ORDER.index(observation.role)
        if role_index <= previous_role_index:
            raise ValueError("track_observation_order_invalid")
        previous_role_index = role_index
        if observation.source_frame_number in frames:
            raise ValueError("track_observation_frame_duplicate")
        frames.add(observation.source_frame_number)
        if observation.confidence > track.max_confidence:
            raise ValueError("observation_confidence_exceeds_track_max")
        if not track.start_offset_ms <= observation.offset_ms <= track.end_offset_ms:
            raise ValueError("observation_outside_track")
    if observations[0].role is not EvidenceRole.REPRESENTATIVE:
        raise ValueError("track_representative_missing")


@dataclass(frozen=True, slots=True)
class RoleAccounting:
    candidates: int
    admitted: int
    omitted: int
    candidate_bytes: int
    admitted_bytes: int

    def __post_init__(self) -> None:
        values = (self.candidates, self.admitted, self.omitted, self.candidate_bytes, self.admitted_bytes)
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in values):
            raise ValueError("evidence_accounting_invalid")
        if (
            self.admitted > self.candidates
            or self.omitted != self.candidates - self.admitted
            or self.admitted_bytes > self.candidate_bytes
        ):
            raise ValueError("evidence_accounting_invalid")


_EMPTY_ROLE_ACCOUNTING = RoleAccounting(0, 0, 0, 0, 0)


@dataclass(frozen=True, slots=True)
class EvidenceAccounting:
    """Per-role candidate/admitted/omitted counts and bytes for one run (ADR-013 §6)."""

    representative: RoleAccounting = _EMPTY_ROLE_ACCOUNTING
    near_view: RoleAccounting = _EMPTY_ROLE_ACCOUNTING
    early_diverse: RoleAccounting = _EMPTY_ROLE_ACCOUNTING
    late_diverse: RoleAccounting = _EMPTY_ROLE_ACCOUNTING

    def for_role(self, role: EvidenceRole) -> RoleAccounting:
        return {
            EvidenceRole.REPRESENTATIVE: self.representative,
            EvidenceRole.NEAR_VIEW: self.near_view,
            EvidenceRole.EARLY_DIVERSE: self.early_diverse,
            EvidenceRole.LATE_DIVERSE: self.late_diverse,
        }[role]

    @staticmethod
    def of(by_role: dict[EvidenceRole, RoleAccounting]) -> "EvidenceAccounting":
        return EvidenceAccounting(
            representative=by_role[EvidenceRole.REPRESENTATIVE],
            near_view=by_role[EvidenceRole.NEAR_VIEW],
            early_diverse=by_role[EvidenceRole.EARLY_DIVERSE],
            late_diverse=by_role[EvidenceRole.LATE_DIVERSE],
        )


@dataclass(frozen=True, slots=True)
class VisionProcessingResult:
    job_id: UUID
    frames_processed: int
    tracks: tuple[ProcessedTrack, ...]
    evidence_accounting: EvidenceAccounting = EvidenceAccounting()

    def __post_init__(self) -> None:
        if self.job_id.int == 0:
            raise ValueError("job_id_invalid")
        if self.frames_processed < 0:
            raise ValueError("frames_processed_invalid")
        if self.frames_processed == 0 and self.tracks:
            raise ValueError("tracks_require_processed_frames")
        if len(self.tracks) > MAXIMUM_TRACKS_PER_RESULT:
            raise ValueError("track_limit_exceeded")
        track_ids = tuple(track.track_id for track in self.tracks)
        if len(track_ids) != len(set(track_ids)):
            raise ValueError("track_id_duplicate")
        # The accounting must describe exactly the observations present:
        # admitted counts and bytes per role, and one Representative candidate
        # per Track, none omitted (ADR-013 §6).
        for role in ROLE_ORDER:
            present = [
                observation
                for track in self.tracks
                for observation in track.observations
                if observation.role is role
            ]
            accounting = self.evidence_accounting.for_role(role)
            if accounting.admitted != len(present) or accounting.admitted_bytes != sum(
                observation.crop.size_bytes for observation in present
            ):
                raise ValueError("evidence_accounting_mismatch")
        representative = self.evidence_accounting.representative
        if representative.candidates != len(self.tracks) or representative.omitted != 0:
            raise ValueError("evidence_accounting_mismatch")
