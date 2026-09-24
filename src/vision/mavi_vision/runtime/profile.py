from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import isclose, isfinite
from numbers import Real
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from mavi_vision.common.analytical import ObjectClass
from mavi_vision.evidence.policy import (
    PRODUCTION_ENCODER_POLICY,
    EncoderPolicy,
    EvidencePolicy,
    decimal_micro_units,
)
from mavi_vision.runtime.manifest import (
    ModelManifest,
    ReleaseMetadataError,
    read_release_json,
)


_PHASE1_SOURCE_CLASSES = ("person", "car", "motorcycle", "bus", "truck")
_PHASE1_CLASS_MAPPING = {
    "person": ObjectClass.PERSON,
    "car": ObjectClass.VEHICLE,
    "motorcycle": ObjectClass.VEHICLE,
    "bus": ObjectClass.VEHICLE,
    "truck": ObjectClass.VEHICLE,
}
_TRACKERS_REFERENCE_HZ = 30.0
_INTEGER_TOLERANCE = 1e-9


def _is_finite_real(value: object) -> bool:
    return (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and isfinite(float(value))
    )


def _lost_track_buffer_units(seconds: float) -> int:
    if not _is_finite_real(seconds) or not 0.0 < float(seconds) <= 60.0:
        raise ValueError("bytetrack_lost_buffer_seconds_invalid")
    scaled = float(seconds) * _TRACKERS_REFERENCE_HZ
    nearest = round(scaled)
    if not isclose(
        scaled,
        nearest,
        rel_tol=0.0,
        abs_tol=_INTEGER_TOLERANCE,
    ):
        raise ValueError("bytetrack_lost_buffer_not_integral_at_30hz")
    return nearest


@dataclass(frozen=True, slots=True)
class ByteTrackProfile:
    reference_frame_rate: float
    track_activation_threshold: float
    high_confidence_threshold: float
    minimum_iou_threshold: float
    minimum_consecutive_frames: int
    lost_track_buffer_seconds: float

    def __post_init__(self) -> None:
        if (
            not _is_finite_real(self.reference_frame_rate)
            or float(self.reference_frame_rate) <= 0.0
        ):
            raise ValueError("bytetrack_reference_frame_rate_invalid")
        for name, value in (
            ("track_activation_threshold", self.track_activation_threshold),
            ("high_confidence_threshold", self.high_confidence_threshold),
            ("minimum_iou_threshold", self.minimum_iou_threshold),
        ):
            if (
                not _is_finite_real(value)
                or not 0.0 <= float(value) <= 1.0
            ):
                raise ValueError(f"bytetrack_{name}_invalid")
        if not self.high_confidence_threshold < self.track_activation_threshold:
            raise ValueError("bytetrack_confidence_threshold_order_invalid")
        if (
            not isinstance(self.minimum_consecutive_frames, int)
            or isinstance(self.minimum_consecutive_frames, bool)
            or not 1 <= self.minimum_consecutive_frames <= 100
        ):
            raise ValueError("bytetrack_minimum_consecutive_frames_invalid")
        _lost_track_buffer_units(self.lost_track_buffer_seconds)

    @property
    def lost_track_buffer(self) -> int:
        return _lost_track_buffer_units(self.lost_track_buffer_seconds)


@dataclass(frozen=True, slots=True)
class PipelineProfile:
    schema_version: str
    profile_id: str
    profile_version: str
    model_id: str
    detector_inference_floor: float
    allowed_source_classes: tuple[str, ...]
    class_mapping: Mapping[str, ObjectClass]
    tracker: ByteTrackProfile
    frame_policy: Literal["every-frame"]
    evidence: EvidencePolicy


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _ByteTrackProfileSchema(_StrictModel):
    reference_frame_rate: float = Field(
        alias="referenceFrameRate",
        gt=0.0,
        allow_inf_nan=False,
    )
    track_activation_threshold: float = Field(
        alias="trackActivationThreshold",
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
    )
    high_confidence_threshold: float = Field(
        alias="highConfidenceThreshold",
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
    )
    minimum_iou_threshold: float = Field(
        alias="minimumIouThreshold",
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
    )
    minimum_consecutive_frames: int = Field(
        alias="minimumConsecutiveFrames",
        ge=1,
        le=100,
    )
    lost_track_buffer_seconds: float = Field(
        alias="lostTrackBufferSeconds",
        gt=0.0,
        le=60.0,
        allow_inf_nan=False,
    )

    @model_validator(mode="after")
    def validate_tracker_policy(self) -> "_ByteTrackProfileSchema":
        if not self.high_confidence_threshold < self.track_activation_threshold:
            raise ValueError("bytetrack_confidence_threshold_order_invalid")

        _lost_track_buffer_units(self.lost_track_buffer_seconds)
        return self


class _EncoderProfileSchema(_StrictModel):
    """ADR-013 §5 bounds. Recorded in the profile for identity; not tunable."""

    encoder_version: str = Field(alias="encoderVersion")
    max_long_edge_px: int = Field(alias="maxLongEdgePx")
    initial_quality: int = Field(alias="initialQuality")
    representative_cap_bytes: int = Field(alias="representativeCapBytes")
    supplemental_cap_bytes: int = Field(alias="supplementalCapBytes")
    floor_long_edge_px: int = Field(alias="floorLongEdgePx")
    floor_quality: int = Field(alias="floorQuality")
    ladder_scale: float = Field(alias="ladderScale", allow_inf_nan=False)
    ladder_qualities: tuple[int, ...] = Field(alias="ladderQualities")
    floor_qualities: tuple[int, ...] = Field(alias="floorQualities")

    def to_policy(self) -> EncoderPolicy:
        policy = EncoderPolicy(
            encoder_version=self.encoder_version,
            max_long_edge_px=self.max_long_edge_px,
            initial_quality=self.initial_quality,
            representative_cap_bytes=self.representative_cap_bytes,
            supplemental_cap_bytes=self.supplemental_cap_bytes,
            floor_long_edge_px=self.floor_long_edge_px,
            floor_quality=self.floor_quality,
            ladder_scale=Fraction(str(self.ladder_scale)),
            ladder_qualities=self.ladder_qualities,
            floor_qualities=self.floor_qualities,
        )
        if policy != PRODUCTION_ENCODER_POLICY:
            raise ValueError("evidence_encoder_policy_not_adr_bound")
        return policy


class _EvidenceProfileSchema(_StrictModel):
    selector_version: str = Field(alias="selectorVersion")
    scorer_version: str = Field(alias="scorerVersion")
    confidence_floor: float = Field(alias="confidenceFloor", ge=0.0, le=1.0, allow_inf_nan=False)
    sharpness_floor: float = Field(alias="sharpnessFloor", ge=0.0, le=1.0, allow_inf_nan=False)
    edge_margin_floor: float = Field(alias="edgeMarginFloor", ge=0.0, le=1.0, allow_inf_nan=False)
    occlusion_iou_ceiling: float = Field(alias="occlusionIouCeiling", ge=0.0, le=1.0, allow_inf_nan=False)
    occlusion_penalty_weight: float = Field(
        alias="occlusionPenaltyWeight", ge=0.0, le=1.0, allow_inf_nan=False
    )
    replace_epsilon: float = Field(alias="replaceEpsilon", gt=0.0, le=0.5, allow_inf_nan=False)
    near_view_growth: float = Field(alias="nearViewGrowth", gt=0.0, le=4.0, allow_inf_nan=False)
    early_window_ms: int = Field(alias="earlyWindowMs", gt=0, le=3_600_000)
    late_refresh_interval_ms: int = Field(alias="lateRefreshIntervalMs", gt=0, le=3_600_000)
    min_separation_ms: int = Field(alias="minSeparationMs", gt=0, le=3_600_000)
    duplicate_window_ms: int = Field(alias="duplicateWindowMs", gt=0, le=3_600_000)
    duplicate_iou_threshold: float = Field(
        alias="duplicateIouThreshold", ge=0.0, le=1.0, allow_inf_nan=False
    )
    encoder: _EncoderProfileSchema
    run_evidence_crop_quota_bytes: int = Field(alias="runEvidenceCropQuotaBytes")

    def to_policy(self) -> EvidencePolicy:
        return EvidencePolicy(
            selector_version=self.selector_version,
            scorer_version=self.scorer_version,
            confidence_floor=float(self.confidence_floor),
            sharpness_floor=float(self.sharpness_floor),
            edge_margin_floor=float(self.edge_margin_floor),
            occlusion_iou_ceiling=float(self.occlusion_iou_ceiling),
            occlusion_penalty_weight=float(self.occlusion_penalty_weight),
            replace_epsilon_micro=decimal_micro_units(self.replace_epsilon, "replace_epsilon"),
            near_view_growth=Fraction(str(self.near_view_growth)),
            early_window_ms=self.early_window_ms,
            late_refresh_interval_ms=self.late_refresh_interval_ms,
            min_separation_ms=self.min_separation_ms,
            duplicate_window_ms=self.duplicate_window_ms,
            duplicate_iou_threshold=float(self.duplicate_iou_threshold),
            encoder=self.encoder.to_policy(),
            run_evidence_crop_quota_bytes=self.run_evidence_crop_quota_bytes,
        )


class _PipelineProfileSchema(_StrictModel):
    schema_version: Literal["1.1"] = Field(alias="schemaVersion")
    profile_id: str = Field(alias="profileId")
    profile_version: str = Field(alias="profileVersion")
    model_id: str = Field(alias="modelId")
    detector_inference_floor: float = Field(
        alias="detectorInferenceFloor",
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
    )
    allowed_source_classes: tuple[str, ...] = Field(alias="allowedSourceClasses")
    class_mapping: dict[str, ObjectClass] = Field(alias="classMapping")
    tracker: _ByteTrackProfileSchema
    frame_policy: Literal["every-frame"] = Field(alias="framePolicy")
    evidence: _EvidenceProfileSchema

    @field_validator("profile_id", "profile_version", "model_id")
    @classmethod
    def validate_nonempty_text(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("pipeline_profile_text_invalid")
        return value

    @field_validator("allowed_source_classes")
    @classmethod
    def validate_allowed_classes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != _PHASE1_SOURCE_CLASSES:
            raise ValueError("phase1_allowed_source_classes_invalid")
        return value

    @model_validator(mode="after")
    def validate_phase1_mapping(self) -> "_PipelineProfileSchema":
        if self.class_mapping != _PHASE1_CLASS_MAPPING:
            raise ValueError("phase1_class_mapping_invalid")
        if not self.detector_inference_floor < self.tracker.high_confidence_threshold:
            raise ValueError("detector_floor_not_below_high_confidence")
        # A confirmed Track always has candidates at or above the activation
        # threshold, so the confidence floor alone can never be the reason its
        # Representative is a fallback rather than qualified (plan §4.2, ADR-013
        # §4 two-tier amendment).
        if self.evidence.confidence_floor > self.tracker.track_activation_threshold:
            raise ValueError("evidence_confidence_floor_above_activation")
        # Validate the evidence policy eagerly so a bad profile fails at load.
        self.evidence.to_policy()
        return self


def load_pipeline_profile(path: Path) -> PipelineProfile:
    raw = read_release_json(path, code="pipeline_profile_invalid")
    try:
        parsed = _PipelineProfileSchema.model_validate(raw)
    except ValidationError as exc:
        raise ReleaseMetadataError("pipeline_profile_invalid") from exc

    try:
        evidence = parsed.evidence.to_policy()
    except ValueError as exc:
        raise ReleaseMetadataError("pipeline_profile_invalid") from exc

    tracker = ByteTrackProfile(
        reference_frame_rate=parsed.tracker.reference_frame_rate,
        track_activation_threshold=parsed.tracker.track_activation_threshold,
        high_confidence_threshold=parsed.tracker.high_confidence_threshold,
        minimum_iou_threshold=parsed.tracker.minimum_iou_threshold,
        minimum_consecutive_frames=parsed.tracker.minimum_consecutive_frames,
        lost_track_buffer_seconds=parsed.tracker.lost_track_buffer_seconds,
    )
    return PipelineProfile(
        schema_version=parsed.schema_version,
        profile_id=parsed.profile_id,
        profile_version=parsed.profile_version,
        model_id=parsed.model_id,
        detector_inference_floor=parsed.detector_inference_floor,
        allowed_source_classes=parsed.allowed_source_classes,
        class_mapping=MappingProxyType(dict(parsed.class_mapping)),
        tracker=tracker,
        frame_policy=parsed.frame_policy,
        evidence=evidence,
    )


def validate_profile_against_manifest(
    profile: PipelineProfile,
    manifest: ModelManifest,
) -> None:
    if profile.model_id != manifest.model_id:
        raise ReleaseMetadataError("profile_model_id_mismatch")

    vocabulary = set(manifest.class_vocabulary)
    if any(source_class not in vocabulary for source_class in profile.allowed_source_classes):
        raise ReleaseMetadataError("profile_class_not_in_manifest_vocabulary")
    if any(source_class not in vocabulary for source_class in profile.class_mapping):
        raise ReleaseMetadataError("profile_mapping_not_in_manifest_vocabulary")
