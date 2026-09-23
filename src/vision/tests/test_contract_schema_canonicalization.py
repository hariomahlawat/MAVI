import hashlib
import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from mavi_vision.common.control_plane import VisionJobHeartbeatResponse, VisionJobLease, WorkerHealth

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "contracts" / "schemas"
EXAMPLES = ROOT / "contracts" / "examples"
CANONICAL_UTC_PATTERN = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]{1,6})?Z(?![\s\S])"
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
def test_python_wire_models_reject_noncanonical_timestamp_precision_and_case(
    model: type, payload: dict[str, object], timestamp_field: str
) -> None:
    for timestamp in (
        "2026-09-09t03:00:00Z",
        "2026-09-09T03:00:00.1234567Z",
        "2026-09-09T03:00:00.11111111111111111Z",
    ):
        invalid = dict(payload)
        invalid[timestamp_field] = timestamp
        with pytest.raises(ValidationError):
            model.model_validate_json(json.dumps(invalid))


def test_python_wire_models_accept_microsecond_precision() -> None:
    payload = {
        "schemaVersion": "2.0",
        "workerId": "gpu-sdd-01",
        "status": "ready",
        "timestampUtc": "2026-09-09T03:00:00.123456Z",
    }
    model = WorkerHealth.model_validate_json(json.dumps(payload))
    assert model.timestamp_utc.microsecond == 123456


# Completion 3.0 (S1.2a). The platform accepts it; the worker emits it from S1.2c.
TEST_VECTORS = ROOT / "contracts" / "test-vectors"
_V3_PLACEHOLDER = "__mavi_conformance_token__"


def _v3_schema() -> dict[str, object]:
    return json.loads((SCHEMAS / "vision-job-complete-v3.schema.json").read_text())


def _v3_validator() -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(_v3_schema(), format_checker=jsonschema.FormatChecker())


def test_completion_v3_golden_example_is_schema_valid_and_pinned() -> None:
    example = (EXAMPLES / "vision-job-complete-v3.example.json").read_bytes()
    pinned = json.loads((TEST_VECTORS / "vision-job-complete-v3-digest.json").read_text())

    assert not list(_v3_validator().iter_errors(json.loads(example)))
    assert hashlib.sha256(example).hexdigest() == pinned["exampleSha256"]


def test_completion_v3_shares_every_non_evidence_definition_with_v2() -> None:
    v2 = json.loads((SCHEMAS / "vision-job-complete-v2.schema.json").read_text())
    v3 = _v3_schema()

    for name, definition in v2["$defs"].items():
        if name in {"representative", "track"}:
            continue
        assert v3["$defs"][name] == definition, name
    assert "representative" not in v3["$defs"]["track"]["properties"]
    assert v3["properties"]["schemaVersion"] == {"const": "3.0"}


def test_completion_v3_invalid_vectors_are_rejected_at_their_declared_boundary() -> None:
    validator = _v3_validator()
    for vector in json.loads((TEST_VECTORS / "control-plane-v3-invalid.json").read_text()):
        schema_valid = not list(validator.iter_errors(vector["payload"]))
        if vector["rejectedBy"] == "schema":
            assert not schema_valid, vector["name"]
        else:
            # Cross-field rules the schema cannot express; the platform validator rejects them.
            assert schema_valid, vector["name"]


def test_completion_v3_integer_conformance_corpus_matches_schema() -> None:
    example = json.loads((EXAMPLES / "vision-job-complete-v3.example.json").read_text())
    validator = _v3_validator()
    for vector in json.loads((TEST_VECTORS / "vision-job-complete-v3-conformance.json").read_text())["integerCases"]:
        payload = json.loads(json.dumps(example))
        parent: object = payload
        parts = vector["path"].strip("/").split("/")
        for part in parts[:-1]:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        if isinstance(parent, list):
            parent[int(parts[-1])] = _V3_PLACEHOLDER
        else:
            parent[parts[-1]] = _V3_PLACEHOLDER
        raw = json.dumps(payload).replace(f'"{_V3_PLACEHOLDER}"', vector["token"])

        assert (not list(validator.iter_errors(json.loads(raw)))) is vector["accepted"], vector["name"]

