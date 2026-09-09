import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mavi_vision.common.control_plane import VisionJobHeartbeatResponse, VisionJobLease, WorkerHealth

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "contracts" / "schemas"
EXAMPLES = ROOT / "contracts" / "examples"
CANONICAL_UTC_PATTERN = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]+)?Z(?![\s\S])"
)


@pytest.mark.parametrize(
    ("schema_name", "timestamp_fields"),
    [
        ("vision-job-lease-v2", ("leaseExpiresAtUtc", "recordingStartUtc", "recordingEndUtc")),
        ("vision-job-heartbeat-response-v2", ("leaseExpiresAtUtc",)),
        ("worker-health-v2", ("timestampUtc",)),
    ],
)
def test_worker_timestamp_schemas_use_exact_canonical_utc_grammar(
    schema_name: str, timestamp_fields: tuple[str, ...]
) -> None:
    schema = json.loads((SCHEMAS / f"{schema_name}.schema.json").read_text())
    for field in timestamp_fields:
        assert schema["properties"][field]["pattern"] == CANONICAL_UTC_PATTERN


@pytest.mark.parametrize(
    ("model", "payload", "timestamp_field"),
    [
        (
            VisionJobLease,
            json.loads((EXAMPLES / "vision-job-lease-v2.example.json").read_text()),
            "leaseExpiresAtUtc",
        ),
        (
            VisionJobHeartbeatResponse,
            {
                "schemaVersion": "2.0",
                "progressPercent": 50,
                "leaseExpiresAtUtc": "2026-09-09T03:00:00Z",
            },
            "leaseExpiresAtUtc",
        ),
        (
            WorkerHealth,
            {
                "schemaVersion": "2.0",
                "workerId": "gpu-sdd-01",
                "status": "ready",
                "timestampUtc": "2026-09-09T03:00:00Z",
            },
            "timestampUtc",
        ),
    ],
)
def test_python_wire_models_reject_lowercase_t_timestamp(
    model: type, payload: dict[str, object], timestamp_field: str
) -> None:
    invalid = dict(payload)
    invalid[timestamp_field] = "2026-09-09t03:00:00Z"

    with pytest.raises(ValidationError):
        model.model_validate_json(json.dumps(invalid))
