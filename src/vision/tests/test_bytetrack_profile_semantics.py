from __future__ import annotations

import json
from pathlib import Path

import pytest

from mavi_vision.runtime.manifest import ReleaseMetadataError
from mavi_vision.runtime.profile import ByteTrackProfile, load_pipeline_profile


def _payload() -> dict:
    return {
        "schemaVersion": "1.0",
        "profileId": "phase1-detection-tracking-v1",
        "profileVersion": "1.1.0-candidate",
        "modelId": "rtmdet-m-coco-phase1",
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
    }


def _load(tmp_path: Path, payload: dict):
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return load_pipeline_profile(path)


def test_corrected_trackers_26_profile_maps_exact_native_policy(tmp_path: Path) -> None:
    profile = _load(tmp_path, _payload())

    assert profile.profile_version == "1.1.0-candidate"
    assert profile.tracker.reference_frame_rate == 30.0
    assert profile.tracker.track_activation_threshold == 0.7
    assert profile.tracker.high_confidence_threshold == 0.6
    assert profile.tracker.minimum_iou_threshold == 0.1
    assert profile.tracker.minimum_consecutive_frames == 2
    assert profile.tracker.lost_track_buffer_seconds == 1.0
    assert profile.tracker.lost_track_buffer == 30


def test_legacy_minimum_matching_threshold_fails_closed(tmp_path: Path) -> None:
    payload = _payload()
    del payload["tracker"]["minimumIouThreshold"]
    payload["tracker"]["minimumMatchingThreshold"] = 0.8

    with pytest.raises(ReleaseMetadataError, match="pipeline_profile_invalid"):
        _load(tmp_path, payload)


@pytest.mark.parametrize(
    ("floor", "high", "activation"),
    [
        (0.60, 0.60, 0.70),
        (0.61, 0.60, 0.70),
        (0.05, 0.70, 0.70),
        (0.05, 0.80, 0.70),
    ],
)
def test_confidence_thresholds_require_strict_floor_high_activation_order(
    tmp_path: Path,
    floor: float,
    high: float,
    activation: float,
) -> None:
    payload = _payload()
    payload["detectorInferenceFloor"] = floor
    payload["tracker"]["highConfidenceThreshold"] = high
    payload["tracker"]["trackActivationThreshold"] = activation

    with pytest.raises(ReleaseMetadataError, match="pipeline_profile_invalid"):
        _load(tmp_path, payload)


@pytest.mark.parametrize("seconds", [0.01, 0.333333333, 1.01])
def test_lost_track_budget_must_be_integral_in_trackers_30hz_units(
    tmp_path: Path,
    seconds: float,
) -> None:
    payload = _payload()
    payload["tracker"]["lostTrackBufferSeconds"] = seconds

    with pytest.raises(ReleaseMetadataError, match="pipeline_profile_invalid"):
        _load(tmp_path, payload)


@pytest.mark.parametrize("rate", [0.0, -1.0, float("inf")])
def test_reference_frame_rate_must_be_finite_and_positive(
    tmp_path: Path,
    rate: float,
) -> None:
    payload = _payload()
    payload["tracker"]["referenceFrameRate"] = rate

    with pytest.raises(ReleaseMetadataError, match="pipeline_profile_invalid"):
        _load(tmp_path, payload)


@pytest.mark.parametrize("threshold", [-0.01, 1.01, float("nan")])
def test_minimum_iou_must_be_finite_unit_interval(
    tmp_path: Path,
    threshold: float,
) -> None:
    payload = _payload()
    payload["tracker"]["minimumIouThreshold"] = threshold

    with pytest.raises(ReleaseMetadataError, match="pipeline_profile_invalid"):
        _load(tmp_path, payload)


def test_direct_profile_construction_rejects_ambiguous_lost_buffer() -> None:
    with pytest.raises(
        ValueError,
        match="bytetrack_lost_buffer_not_integral_at_30hz",
    ):
        ByteTrackProfile(
            reference_frame_rate=30.0,
            track_activation_threshold=0.7,
            high_confidence_threshold=0.6,
            minimum_iou_threshold=0.1,
            minimum_consecutive_frames=2,
            lost_track_buffer_seconds=1.01,
        )


def test_direct_profile_construction_enforces_tracker_threshold_order() -> None:
    with pytest.raises(
        ValueError,
        match="bytetrack_confidence_threshold_order_invalid",
    ):
        ByteTrackProfile(
            reference_frame_rate=30.0,
            track_activation_threshold=0.6,
            high_confidence_threshold=0.6,
            minimum_iou_threshold=0.1,
            minimum_consecutive_frames=2,
            lost_track_buffer_seconds=1.0,
        )
