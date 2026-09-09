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
    WorkerHealth,
)

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "contracts/examples/vision-job-lease-v2.example.json"
INVALID_VECTORS = ROOT / "contracts/test-vectors/control-plane-v2-invalid.json"


def test_canonical_lease_golden_example_round_trips_semantically() -> None:
    payload = json.loads(EXAMPLE.read_text())
    model = VisionJobLease.model_validate_json(EXAMPLE.read_text())
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
        VisionJobLease.model_validate_json(json.dumps(payload))


def test_shared_invalid_vectors_are_rejected() -> None:
    models = {
        "vision-job-lease-request-v2": VisionJobLeaseRequest,
        "vision-job-lease-v2": VisionJobLease,
        "vision-job-heartbeat-v2": VisionJobHeartbeat,
        "vision-job-heartbeat-response-v2": VisionJobHeartbeatResponse,
        "vision-job-fail-v2": VisionJobFail,
        "worker-health-v2": WorkerHealth,
    }
    for vector in json.loads(INVALID_VECTORS.read_text()):
        with pytest.raises(ValidationError):
            models[vector["schema"]].model_validate_json(json.dumps(vector["payload"]))


@pytest.mark.parametrize("change", [
    {"attemptCount": "1"},
    {"width": "1920"},
    {"durationMs": "1000"},
    {"leaseExpiresAtUtc": 1788912000},
])
def test_lease_rejects_coercible_wire_values(change: dict[str, object]) -> None:
    payload = json.loads(EXAMPLE.read_text())
    payload.update(change)
    with pytest.raises(ValidationError):
        VisionJobLease.model_validate_json(json.dumps(payload))


def test_heartbeat_rejects_numeric_string_progress() -> None:
    payload = {
        "schemaVersion": "2.0",
        "workerId": "gpu-sdd-01",
        "leaseToken": "A" * 43,
        "progressPercent": "50",
    }
    with pytest.raises(ValidationError):
        VisionJobHeartbeat.model_validate_json(json.dumps(payload))


def test_heartbeat_accepts_json_numeric_progress() -> None:
    payload = {
        "schemaVersion": "2.0",
        "workerId": "gpu-sdd-01",
        "leaseToken": "A" * 43,
        "progressPercent": 50,
    }
    model = VisionJobHeartbeat.model_validate_json(json.dumps(payload))
    assert model.progress_percent == 50


@pytest.mark.parametrize(
    ("model", "canonical_payload", "snake_case_payload"),
    [
        (
            VisionJobLeaseRequest,
            {"schemaVersion": "2.0", "workerId": "gpu-sdd-01"},
            {"schema_version": "2.0", "worker_id": "gpu-sdd-01"},
        ),
        (
            VisionJobHeartbeat,
            {
                "schemaVersion": "2.0",
                "workerId": "gpu-sdd-01",
                "leaseToken": "A" * 43,
                "progressPercent": 50,
            },
            {
                "schemaVersion": "2.0",
                "worker_id": "gpu-sdd-01",
                "leaseToken": "A" * 43,
                "progress_percent": 50,
            },
        ),
        (
            VisionJobFail,
            {
                "schemaVersion": "2.0",
                "workerId": "gpu-sdd-01",
                "leaseToken": "A" * 43,
                "failureCode": "ffmpeg_decode_failed",
            },
            {
                "schemaVersion": "2.0",
                "workerId": "gpu-sdd-01",
                "leaseToken": "A" * 43,
                "failure_code": "ffmpeg_decode_failed",
            },
        ),
    ],
)
def test_wire_json_accepts_only_canonical_aliases(
    model: type, canonical_payload: dict[str, object], snake_case_payload: dict[str, object]
) -> None:
    model.model_validate_json(json.dumps(canonical_payload))

    with pytest.raises(ValidationError):
        model.model_validate_json(json.dumps(snake_case_payload))


@pytest.mark.parametrize(
    ("model", "payload", "timestamp_names"),
    [
        (
            VisionJobLease,
            json.loads(EXAMPLE.read_text()),
            ("leaseExpiresAtUtc", "recordingStartUtc", "recordingEndUtc"),
        ),
        (
            VisionJobHeartbeatResponse,
            {
                "schemaVersion": "2.0",
                "progressPercent": 50,
                "leaseExpiresAtUtc": "2026-09-09T03:00:00Z",
            },
            ("leaseExpiresAtUtc",),
        ),
        (
            WorkerHealth,
            {
                "schemaVersion": "2.0",
                "workerId": "gpu-sdd-01",
                "status": "ready",
                "timestampUtc": "2026-09-09T03:00:00Z",
            },
            ("timestampUtc",),
        ),
    ],
)
def test_timestamp_wire_json_requires_canonical_utc_z(
    model: type, payload: dict[str, object], timestamp_names: tuple[str, ...]
) -> None:
    canonical = dict(payload)
    for timestamp_name in timestamp_names:
        canonical[timestamp_name] = "2026-09-09T03:00:00Z"
    model.model_validate_json(json.dumps(canonical))

    invalid_timestamps = (
        "2026-09-09T03:00:00+00:00",
        "2026-09-09 03:00:00Z",
        "2026-09-09T03:00:00",
        "2026-09-09T03:00:00z",
    )
    for timestamp_name in timestamp_names:
        for invalid_timestamp in invalid_timestamps:
            noncanonical = dict(canonical)
            noncanonical[timestamp_name] = invalid_timestamp
            with pytest.raises(ValidationError):
                model.model_validate_json(json.dumps(noncanonical))


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
    assert VisionJobFail.model_validate_json(json.dumps(payload)).failure_message == failure_message
