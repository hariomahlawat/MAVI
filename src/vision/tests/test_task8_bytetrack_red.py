from __future__ import annotations

import json
from pathlib import Path

from mavi_vision.runtime.profile import load_pipeline_profile


def test_task8_corrected_trackers_26_profile_contract_is_loadable(tmp_path: Path) -> None:
    payload = {
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
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    profile = load_pipeline_profile(path)

    assert profile.profile_version == "1.1.0-candidate"
    assert profile.tracker.reference_frame_rate == 30.0
    assert profile.tracker.minimum_iou_threshold == 0.1
    assert profile.tracker.lost_track_buffer == 30
