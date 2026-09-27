from __future__ import annotations

import copy

import json
from pathlib import Path

import pytest

from mavi_vision.common.analytical import ObjectClass
from mavi_vision.runtime.manifest import ReleaseMetadataError
from mavi_vision.runtime.profile import load_pipeline_profile, validate_profile_against_manifest
from tests.profile_fixtures import PRODUCTION_EVIDENCE_SECTION


def _profile_payload() -> dict:
    return {
        "schemaVersion": "1.1",
        "profileId": "phase1-detection-tracking-v1",
        "profileVersion": "1.1.0-candidate",
        "modelId": "model-a",
        "detectorInferenceFloor": 0.05,
        "allowedSourceClasses": ["person", "car", "motorcycle", "bus", "truck"],
        "classMapping": {
            "person": "person",
            "car": "vehicle",
            "motorcycle": "vehicle",
            "bus": "vehicle",
            "truck": "vehicle",
        },
        "tracker": {
            "referenceFrameRate": 30.0,
            "trackActivationThreshold": 0.7,
            "highConfidenceThreshold": 0.6,
            "minimumIouThreshold": 0.1,
            "minimumConsecutiveFrames": 2,
            "lostTrackBufferSeconds": 1.0,
        },
        "framePolicy": "every-frame",
        "evidence": copy.deepcopy(PRODUCTION_EVIDENCE_SECTION),
    }


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")


_VOCABULARY = ("person", "car", "motorcycle", "bus", "truck")


def test_pipeline_profile_loads_immutable_phase1_policy(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    _write_json(path, _profile_payload())

    profile = load_pipeline_profile(path)

    assert profile.frame_policy == "every-frame"
    assert profile.class_mapping["person"] is ObjectClass.PERSON
    assert profile.class_mapping["truck"] is ObjectClass.VEHICLE
    with pytest.raises(TypeError):
        profile.class_mapping["car"] = ObjectClass.PERSON  # type: ignore[index]


def test_pipeline_profile_rejects_generic_detection_cap(tmp_path: Path) -> None:
    payload = _profile_payload()
    payload["maxDetections"] = 100
    path = tmp_path / "profile.json"
    _write_json(path, payload)

    with pytest.raises(ReleaseMetadataError, match="pipeline_profile_invalid"):
        load_pipeline_profile(path)


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_pipeline_profile_rejects_detector_threshold_outside_unit_interval(
    tmp_path: Path,
    value: float,
) -> None:
    payload = _profile_payload()
    payload["detectorInferenceFloor"] = value
    path = tmp_path / "profile.json"
    _write_json(path, payload)

    with pytest.raises(ReleaseMetadataError, match="pipeline_profile_invalid"):
        load_pipeline_profile(path)


def test_pipeline_profile_rejects_floor_above_tracker_activation(tmp_path: Path) -> None:
    payload = _profile_payload()
    payload["detectorInferenceFloor"] = 0.5
    payload["tracker"]["trackActivationThreshold"] = 0.25
    path = tmp_path / "profile.json"
    _write_json(path, payload)

    with pytest.raises(ReleaseMetadataError, match="pipeline_profile_invalid"):
        load_pipeline_profile(path)


def test_pipeline_profile_rejects_non_phase1_class_mapping(tmp_path: Path) -> None:
    payload = _profile_payload()
    payload["classMapping"]["truck"] = "person"
    path = tmp_path / "profile.json"
    _write_json(path, payload)

    with pytest.raises(ReleaseMetadataError, match="pipeline_profile_invalid"):
        load_pipeline_profile(path)


def test_profile_mapped_classes_must_exist_in_manifest_vocabulary(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    _write_json(path, _profile_payload())
    profile = load_pipeline_profile(path)

    with pytest.raises(
        ReleaseMetadataError,
        match="profile_class_not_in_manifest_vocabulary",
    ):
        validate_profile_against_manifest(
            profile,
            model_id="model-a",
            class_vocabulary=("person", "car", "motorcycle", "bus"),
        )


def test_profile_model_id_must_match_manifest(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    _write_json(path, _profile_payload())
    profile = load_pipeline_profile(path)
    with pytest.raises(ReleaseMetadataError, match="profile_model_id_mismatch"):
        validate_profile_against_manifest(profile, model_id="different-model", class_vocabulary=_VOCABULARY)


def test_a_matching_detector_section_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    _write_json(path, _profile_payload())
    validate_profile_against_manifest(
        load_pipeline_profile(path), model_id="model-a", class_vocabulary=_VOCABULARY
    )
