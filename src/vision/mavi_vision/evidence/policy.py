"""Immutable numeric policy of the Track Evidence Set, built from the profile.

One ``EvidencePolicy`` governs one ProcessingRun. Every value here is part of
the pipeline profile, so any change is a new profile SHA and therefore a new
provenance identity (ADR-013 §3, §6; ADR-009 requalification rule). Versions
name the algorithm; the numeric parameters are the tunable part.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import isfinite

from mavi_vision.evidence.roles import (
    REPRESENTATIVE_CAP_BYTES,
    RUN_EVIDENCE_CROP_QUOTA_BYTES,
    SUPPLEMENTAL_CAP_BYTES,
)


SELECTOR_VERSION = "evidence-selector-v1"
SCORER_VERSION = "quality-v1"
ENCODER_VERSION = "evidence-jpeg-ladder-v1"

# Scores are compared and emitted in integer millionths (plan §4.1, §8): the
# comparisons are exact, and identical on every runtime variant for the same
# float64 inputs.
SCORE_SCALE = 1_000_000

MAX_WINDOW_MS = 3_600_000


def quantize_score(value: float) -> int:
    """``floor(clamp01(value) · 10⁶)`` as an exact integer (plan §4.1)."""
    if not isfinite(value):
        raise ValueError("evidence_score_invalid")
    clamped = min(1.0, max(0.0, float(value)))
    return int(Fraction(clamped) * SCORE_SCALE)


def score_from_micro(micro: int) -> float:
    return micro / SCORE_SCALE


def decimal_micro_units(value: float, name: str) -> int:
    """A profile score parameter as exact millionths; finer values are refused."""
    scaled = Fraction(str(value)) * SCORE_SCALE
    if scaled.denominator != 1:
        raise ValueError(f"evidence_{name}_precision_invalid")
    return int(scaled)


@dataclass(frozen=True, slots=True)
class EncoderPolicy:
    """The ADR-013 §5 encoding contract. The values are fixed product bounds."""

    encoder_version: str
    max_long_edge_px: int
    initial_quality: int
    representative_cap_bytes: int
    supplemental_cap_bytes: int
    floor_long_edge_px: int
    floor_quality: int
    ladder_scale: Fraction
    ladder_qualities: tuple[int, ...]
    floor_qualities: tuple[int, ...]


PRODUCTION_ENCODER_POLICY = EncoderPolicy(
    encoder_version=ENCODER_VERSION,
    max_long_edge_px=1024,
    initial_quality=85,
    representative_cap_bytes=REPRESENTATIVE_CAP_BYTES,
    supplemental_cap_bytes=SUPPLEMENTAL_CAP_BYTES,
    floor_long_edge_px=128,
    floor_quality=50,
    ladder_scale=Fraction(4, 5),
    ladder_qualities=(85, 75),
    floor_qualities=(65, 55, 50),
)


@dataclass(frozen=True, slots=True)
class EvidencePolicy:
    """Selector, scorer and admission parameters for one ProcessingRun.

    Score thresholds are held both as the profile's float (for the floors,
    compared against unquantised signals) and, where the selector compares
    quantised scores, as exact integer millionths.
    """

    selector_version: str
    scorer_version: str
    confidence_floor: float
    sharpness_floor: float
    edge_margin_floor: float
    occlusion_iou_ceiling: float
    occlusion_penalty_weight: float
    replace_epsilon_micro: int
    near_view_growth: Fraction
    early_window_ms: int
    late_refresh_interval_ms: int
    min_separation_ms: int
    duplicate_window_ms: int
    duplicate_iou_threshold: float
    encoder: EncoderPolicy
    run_evidence_crop_quota_bytes: int

    def __post_init__(self) -> None:
        if self.selector_version != SELECTOR_VERSION:
            raise ValueError("evidence_selector_version_unsupported")
        if self.scorer_version != SCORER_VERSION:
            raise ValueError("evidence_scorer_version_unsupported")
        if self.encoder != PRODUCTION_ENCODER_POLICY:
            raise ValueError("evidence_encoder_policy_not_adr_bound")
        for name, value in (
            ("confidence_floor", self.confidence_floor),
            ("sharpness_floor", self.sharpness_floor),
            ("edge_margin_floor", self.edge_margin_floor),
            ("occlusion_iou_ceiling", self.occlusion_iou_ceiling),
            ("occlusion_penalty_weight", self.occlusion_penalty_weight),
            ("duplicate_iou_threshold", self.duplicate_iou_threshold),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, float)
                or not isfinite(value)
                or not 0.0 <= value <= 1.0
            ):
                raise ValueError(f"evidence_{name}_invalid")
        if not 0 < self.replace_epsilon_micro <= SCORE_SCALE // 2:
            raise ValueError("evidence_replace_epsilon_invalid")
        if not 0 < self.near_view_growth <= 4:
            raise ValueError("evidence_near_view_growth_invalid")
        for name, value in (
            ("early_window_ms", self.early_window_ms),
            ("late_refresh_interval_ms", self.late_refresh_interval_ms),
            ("min_separation_ms", self.min_separation_ms),
            ("duplicate_window_ms", self.duplicate_window_ms),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 < value <= MAX_WINDOW_MS
            ):
                raise ValueError(f"evidence_{name}_invalid")
        if self.run_evidence_crop_quota_bytes != RUN_EVIDENCE_CROP_QUOTA_BYTES:
            raise ValueError("evidence_run_quota_not_adr_bound")
