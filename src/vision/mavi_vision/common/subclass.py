"""Detector-native vehicle subclass (Stage 3, ADR-016).

A Vehicle Track's subclass is the detector's own native class, resolved once per
Track from every detection the tracker matched to it. Tracking is unchanged: the
broad Vehicle association pool still mixes car, truck, bus and motorcycle
detections, so one Track can carry several native classes. The vote below turns
those into one value, or abstains.

The vote is exact: each matched detection contributes its confidence in integer
micro-units, so the result never depends on summation order. A value is resolved
only when one class has the unique highest total, that total is at least
``min_share`` of all votes, and at least ``min_matched_detections`` detections
voted. Otherwise the Track is undetermined (``None``). Person Tracks never vote.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

VEHICLE_SUBCLASS_VOCABULARY_V1 = "mavi-vehicle-subclass-v1"
VEHICLE_SUBCLASS_VALUES_V1 = ("car", "truck", "bus", "motorcycle")
# Phase-1 detector classes that are Vehicle, mapped to their v1 vocabulary value.
# Bicycle is not a Phase-1 source class (the pipeline drops it), so it never votes.
PHASE1_VEHICLE_SUBCLASS_MAPPING = MappingProxyType(
    {"car": "car", "truck": "truck", "bus": "bus", "motorcycle": "motorcycle"}
)
DETECTOR_NATIVE_SOURCE_PREFIX = "detector-native:"
_MICRO = 1_000_000


def detector_native_source(pipeline_profile_sha256: str) -> str:
    """The source identity of a detector-native subclass: the profile that resolved it."""
    if len(pipeline_profile_sha256) != 64 or any(c not in "0123456789abcdef" for c in pipeline_profile_sha256):
        raise ValueError("pipeline_profile_sha256_invalid")
    return DETECTOR_NATIVE_SOURCE_PREFIX + pipeline_profile_sha256


def _micro(value: float) -> int:
    return int(round(float(value) * _MICRO))


@dataclass(frozen=True, slots=True)
class VehicleSubclassPolicy:
    """The pipeline profile's ``vehicleSubclass`` block."""

    vocabulary_id: str
    mapping: Mapping[str, str]
    min_share_micro: int
    min_matched_detections: int

    def __post_init__(self) -> None:
        if self.vocabulary_id != VEHICLE_SUBCLASS_VOCABULARY_V1:
            raise ValueError("vehicle_subclass_vocabulary_unsupported")
        if dict(self.mapping) != dict(PHASE1_VEHICLE_SUBCLASS_MAPPING):
            raise ValueError("vehicle_subclass_mapping_invalid")
        # A share at or below one half could resolve two classes at once if ties
        # were allowed; the unique-maximum rule already forbids that, but a share
        # below one half would also admit a winner most detections disagree with.
        if not isinstance(self.min_share_micro, int) or not _MICRO // 2 < self.min_share_micro <= _MICRO:
            raise ValueError("vehicle_subclass_min_share_invalid")
        if (
            not isinstance(self.min_matched_detections, int)
            or isinstance(self.min_matched_detections, bool)
            or not 1 <= self.min_matched_detections <= 10_000
        ):
            raise ValueError("vehicle_subclass_min_matched_detections_invalid")


@dataclass(slots=True)
class SubclassVotes:
    """Votes of one live Vehicle Track: integer micro-confidence per native class."""

    totals: dict[str, int] = field(default_factory=dict)
    detections: int = 0

    def add(self, source_class: str | None, confidence: float) -> None:
        # A detection without a native class (a fixture detector) carries no vote.
        if source_class is None:
            return
        self.totals[source_class] = self.totals.get(source_class, 0) + _micro(confidence)
        self.detections += 1


def resolve_vehicle_subclass(votes: SubclassVotes, policy: VehicleSubclassPolicy) -> str | None:
    """The Track's subclass, or ``None`` when the vote abstains."""
    if votes.detections < policy.min_matched_detections:
        return None
    mapped: dict[str, int] = {}
    for source_class, total in votes.totals.items():
        value = policy.mapping.get(source_class)
        if value is None:
            raise ValueError("vehicle_subclass_source_class_unmapped")
        mapped[value] = mapped.get(value, 0) + total
    grand_total = sum(mapped.values())
    if grand_total <= 0:
        return None
    best = max(mapped.values())
    winners = [value for value, total in mapped.items() if total == best]
    if len(winners) != 1:
        return None
    # share >= min_share, exactly: best / total >= min_share_micro / 1e6.
    if best * _MICRO < policy.min_share_micro * grand_total:
        return None
    return winners[0]
