import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mavi_vision.common.control_plane import (
    VisionJobFail,
    VisionJobHeartbeat,
    VisionJobHeartbeatResponse,
    VisionJobLease,
    VisionJobLeaseRequest,
)

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "contracts/examples/vision-job-lease-v2.example.json"
INVALID_VECTORS = ROOT / "contracts/test-vectors/control-plane-v2-invalid.json"


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


def test_shared_invalid_vectors_are_rejected() -> None:
    models = {
        "vision-job-lease-request-v2": VisionJobLeaseRequest,
        "vision-job-lease-v2": VisionJobLease,
        "vision-job-heartbeat-v2": VisionJobHeartbeat,
        "vision-job-heartbeat-response-v2": VisionJobHeartbeatResponse,
        "vision-job-fail-v2": VisionJobFail,
    }
    for vector in json.loads(INVALID_VECTORS.read_text()):
        with pytest.raises(ValidationError):
            models[vector["schema"]].model_validate(vector["payload"])


@pytest.mark.parametrize("include_member,failure_message", [(False, None), (True, None), (True, "diagnostic")])
def test_failure_message_is_optional_and_nullable(include_member: bool, failure_message: str | None) -> None:
    payload = {
        "schemaVersion": "2.0",
        "workerId": "gpu-sdd-01",
        "leaseToken": "A" * 43,
        "failureCode": "ffmpeg_decode_failed",
    }
    if include_member:
        payload["failureMessage"] = failure_message
    assert VisionJobFail.model_validate(payload).failure_message == failure_message
