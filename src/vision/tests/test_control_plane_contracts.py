import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mavi_vision.common.control_plane import VisionJobLease

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "contracts/examples/vision-job-lease-v2.example.json"


def test_canonical_lease_golden_example_round_trips_semantically() -> None:
    payload = json.loads(EXAMPLE.read_text())
    model = VisionJobLease.model_validate(payload)
    assert model.model_dump(by_alias=True, mode="json") == payload


@pytest.mark.parametrize("change", [
    {"schemaVersion": "1.0"},
    {"workerId": " padded "},
    {"leaseToken": "bad"},
    {"sourceStorageKey": "source/../video.mp4"},
    {"sourceStorageKey": "/source/video.mp4"},
    {"recordingStartUtc": "2026-09-09T01:30:00"},
    {"unexpected": True},
])
def test_invalid_control_plane_vectors_are_rejected(change: dict[str, object]) -> None:
    payload = json.loads(EXAMPLE.read_text())
    payload.update(change)
    with pytest.raises(ValidationError):
        VisionJobLease.model_validate(payload)
