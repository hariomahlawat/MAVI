"""The detector-native vehicle subclass vote and its profile block (ADR-016)."""

from __future__ import annotations

from itertools import permutations
from types import MappingProxyType

import pytest

from mavi_vision.common.analytical import ObjectClass
from mavi_vision.common.subclass import (
    PHASE1_VEHICLE_SUBCLASS_MAPPING,
    VEHICLE_SUBCLASS_VALUES_V1,
    VEHICLE_SUBCLASS_VOCABULARY_V1,
    SubclassVotes,
    VehicleSubclassPolicy,
    detector_native_source,
    resolve_vehicle_subclass,
)


def _policy(min_share: float = 0.6, min_matched: int = 3) -> VehicleSubclassPolicy:
    return VehicleSubclassPolicy(
        vocabulary_id=VEHICLE_SUBCLASS_VOCABULARY_V1,
        mapping=PHASE1_VEHICLE_SUBCLASS_MAPPING,
        min_share_micro=round(min_share * 1_000_000),
        min_matched_detections=min_matched,
    )


def _resolve(votes: list[tuple[str | None, float]], **policy) -> str | None:
    tally = SubclassVotes()
    for source_class, confidence in votes:
        tally.add(source_class, confidence)
    return resolve_vehicle_subclass(tally, _policy(**policy))


def test_the_vocabulary_is_the_four_phase1_vehicle_classes() -> None:
    assert VEHICLE_SUBCLASS_VALUES_V1 == ("car", "truck", "bus", "motorcycle")
    assert set(PHASE1_VEHICLE_SUBCLASS_MAPPING) == set(VEHICLE_SUBCLASS_VALUES_V1)
    assert "bicycle" not in PHASE1_VEHICLE_SUBCLASS_MAPPING


@pytest.mark.parametrize("value", VEHICLE_SUBCLASS_VALUES_V1)
def test_a_single_class_resolves_to_itself(value: str) -> None:
    assert _resolve([(value, 0.9)] * 3) == value


def test_a_mixed_track_resolves_to_its_confidence_weighted_majority() -> None:
    assert _resolve([("car", 0.85)] * 7 + [("truck", 0.8)] * 3) == "car"
    # A few confident minority detections can outweigh many weak ones.
    assert _resolve([("car", 0.3)] * 3 + [("truck", 0.95)] * 2, min_share=0.6) == "truck"


def test_an_exact_tie_abstains() -> None:
    assert _resolve([("car", 0.8), ("truck", 0.8)] * 3) is None


def test_the_share_threshold_is_inclusive_and_exact() -> None:
    # car 3 x 0.6 = 1.8, truck 2 x 0.6 = 1.2: share exactly 0.6.
    assert _resolve([("car", 0.6)] * 3 + [("truck", 0.6)] * 2, min_share=0.6) == "car"
    assert _resolve([("car", 0.6)] * 3 + [("truck", 0.6)] * 2, min_share=0.600001) is None


def test_the_matched_detection_threshold_is_inclusive() -> None:
    assert _resolve([("bus", 0.9)] * 3, min_matched=3) == "bus"
    assert _resolve([("bus", 0.9)] * 2, min_matched=3) is None


def test_the_result_does_not_depend_on_detection_order() -> None:
    votes = [("car", 0.71), ("truck", 0.83), ("car", 0.66), ("bus", 0.92), ("car", 0.59)]
    results = {_resolve(list(order)) for order in permutations(votes)}
    assert len(results) == 1


def test_a_detection_without_a_native_class_casts_no_vote() -> None:
    tally = SubclassVotes()
    tally.add(None, 0.9)
    assert tally.detections == 0 and tally.totals == {}
    assert _resolve([(None, 0.9)] * 5) is None
    assert _resolve([(None, 0.9)] * 5 + [("car", 0.9)] * 3) == "car"


def test_an_unmapped_native_class_fails_closed() -> None:
    with pytest.raises(ValueError, match="vehicle_subclass_source_class_unmapped"):
        _resolve([("bicycle", 0.9)] * 3)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"vocabulary_id": "mavi-vehicle-subclass-v2"}, "vehicle_subclass_vocabulary_unsupported"),
        ({"mapping": MappingProxyType({"car": "car"})}, "vehicle_subclass_mapping_invalid"),
        ({"mapping": MappingProxyType({**PHASE1_VEHICLE_SUBCLASS_MAPPING, "bicycle": "bicycle"})}, "vehicle_subclass_mapping_invalid"),
        ({"min_share_micro": 500_000}, "vehicle_subclass_min_share_invalid"),
        ({"min_share_micro": 1_000_001}, "vehicle_subclass_min_share_invalid"),
        ({"min_matched_detections": 0}, "vehicle_subclass_min_matched_detections_invalid"),
        ({"min_matched_detections": True}, "vehicle_subclass_min_matched_detections_invalid"),
    ],
)
def test_an_invalid_policy_is_refused(change: dict, code: str) -> None:
    fields = {
        "vocabulary_id": VEHICLE_SUBCLASS_VOCABULARY_V1,
        "mapping": PHASE1_VEHICLE_SUBCLASS_MAPPING,
        "min_share_micro": 600_000,
        "min_matched_detections": 3,
    }
    fields.update(change)
    with pytest.raises(ValueError, match=code):
        VehicleSubclassPolicy(**fields)


def test_the_source_names_the_pipeline_profile() -> None:
    assert detector_native_source("a" * 64) == "detector-native:" + "a" * 64
    for bad in ("A" * 64, "a" * 63, "g" * 64):
        with pytest.raises(ValueError, match="pipeline_profile_sha256_invalid"):
            detector_native_source(bad)


def test_a_processed_track_carries_a_subclass_only_as_a_vehicle() -> None:
    with pytest.raises(ValueError, match="track_object_subclass_invalid"):
        _processed_track(ObjectClass.PERSON, "car")
    with pytest.raises(ValueError, match="track_object_subclass_invalid"):
        _processed_track(ObjectClass.VEHICLE, "bicycle")
    assert _processed_track(ObjectClass.VEHICLE, "truck").object_subclass == "truck"
    assert _processed_track(ObjectClass.VEHICLE, None).object_subclass is None


def _processed_track(object_class: ObjectClass, subclass: str | None):
    from mavi_vision.common.analytical import (
        ArtifactDescriptor,
        NormalizedBoundingBox,
        ObservationDescriptor,
        ProcessedTrack,
    )
    from mavi_vision.evidence.roles import EvidenceRole

    track_id = f"{object_class.value}-000001"
    return ProcessedTrack(
        track_id=track_id,
        object_class=object_class,
        start_offset_ms=0,
        end_offset_ms=100,
        detection_count=3,
        mean_confidence=0.8,
        max_confidence=0.9,
        observations=(
            ObservationDescriptor(
                role=EvidenceRole.REPRESENTATIVE, rank=0, offset_ms=0, source_frame_number=0, confidence=0.9,
                bounding_box=NormalizedBoundingBox(0.1, 0.1, 0.2, 0.2), quality_micro=500_000, selection_micro=500_000,
                crop=ArtifactDescriptor(f"staging/x/attempt-0001/evidence/{track_id}-representative.jpg", "image/jpeg", 10, "a" * 64),
            ),
        ),
        trajectory_artifact=ArtifactDescriptor(f"staging/x/attempt-0001/trajectories/{track_id}.msgpack", "application/msgpack", 10, "b" * 64),
        object_subclass=subclass,
    )
