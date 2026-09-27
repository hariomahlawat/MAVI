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



# Completion 3.2 (Stage 2 S2a plan P-7, section 4.5). The platform accepts it from
# S2a.2; the worker emits it from S2a.3.
_V32_EXAMPLES = (
    "vision-job-complete-v3.2.example.json",
    "vision-job-complete-v3.2-unpacked-environment.example.json",
)
_V32_FIELDS = ("capabilityId", "modelPackId", "runtimePackId", "runtimePackSource", "componentBindingSha256")


def _schema_validator(stem: str) -> jsonschema.Draft202012Validator:
    schema = json.loads((SCHEMAS / f"{stem}.schema.json").read_text())
    return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())


def _v32_example(name: str = _V32_EXAMPLES[0]) -> dict:
    return json.loads((EXAMPLES / name).read_text())


def _is_valid(stem: str, payload: dict) -> bool:
    return not list(_schema_validator(stem).iter_errors(payload))


@pytest.mark.parametrize("name", _V32_EXAMPLES)
def test_completion_v32_examples_are_schema_valid_and_pinned(name: str) -> None:
    raw = (EXAMPLES / name).read_bytes()
    vectors = json.loads((TEST_VECTORS / "vision-job-complete-v3.2-digest.json").read_text())["vectors"]
    pinned = {vector["example"]: vector for vector in vectors}[f"contracts/examples/{name}"]

    assert _is_valid("vision-job-complete-v3.2", json.loads(raw))
    assert hashlib.sha256(raw).hexdigest() == pinned["exampleSha256"]
    assert pinned["videoDurationMs"] == 3_600_000


def test_a_3_1_body_carrying_3_2_fields_is_rejected_by_the_3_1_schema() -> None:
    body = _v32_example()
    body["schemaVersion"] = "3.1"
    assert not _is_valid("vision-job-complete-v3.1", body)
    for field in _V32_FIELDS:
        only_one = json.loads((EXAMPLES / "vision-job-complete-v3.1.example.json").read_text())
        only_one["provenance"][field] = body["provenance"][field]
        assert not _is_valid("vision-job-complete-v3.1", only_one), field


def test_a_3_2_body_without_3_2_fields_is_rejected_by_the_3_2_schema() -> None:
    body = json.loads((EXAMPLES / "vision-job-complete-v3.1.example.json").read_text())
    body["schemaVersion"] = "3.2"
    assert not _is_valid("vision-job-complete-v3.2", body)
    for field in ("capabilityId", "modelPackId", "runtimePackSource", "componentBindingSha256"):
        missing = _v32_example()
        del missing["provenance"][field]
        assert not _is_valid("vision-job-complete-v3.2", missing), field


def test_the_runtime_pack_id_is_optional_only_for_an_unpacked_environment() -> None:
    unpacked = _v32_example(_V32_EXAMPLES[1])
    assert unpacked["provenance"]["runtimePackId"] is None
    del unpacked["provenance"]["runtimePackId"]
    assert _is_valid("vision-job-complete-v3.2", unpacked)

    installed = _v32_example()
    del installed["provenance"]["runtimePackId"]
    assert not _is_valid("vision-job-complete-v3.2", installed)


def test_every_shared_3_2_invalid_case_is_rejected_by_its_schema() -> None:
    corpus = json.loads((TEST_VECTORS / "control-plane-v3.2-invalid.json").read_text())
    stems = {"3.0": "vision-job-complete-v3", "3.1": "vision-job-complete-v3.1", "3.2": "vision-job-complete-v3.2"}
    bases = {"installed": _V32_EXAMPLES[0], "unpacked": _V32_EXAMPLES[1]}
    assert len(corpus["cases"]) >= 20
    for case in corpus["cases"]:
        payload = _v32_example(bases[case["base"]])
        payload["schemaVersion"] = case.get("schemaVersion", "3.2")
        for field in case.get("remove", []):
            del payload["provenance"][field]
        payload["provenance"].update(case.get("set", {}))
        assert case["code"].startswith("provenance_"), case["name"]
        assert not _is_valid(stems[payload["schemaVersion"]], payload), case["name"]


def test_the_published_capability_enum_is_the_worker_registry() -> None:
    from mavi_vision.runtime.capabilities import KNOWN_CAPABILITIES

    schema = json.loads((SCHEMAS / "vision-job-complete-v3.2.schema.json").read_text())
    published = schema["$defs"]["capabilityId"]["enum"]
    assert published == sorted(published)
    assert frozenset(published) == KNOWN_CAPABILITIES
    for capability in published:
        body = _v32_example()
        body["provenance"]["capabilityId"] = capability
        assert _is_valid("vision-job-complete-v3.2", body), capability


def test_the_published_pack_id_grammars_are_the_worker_grammars() -> None:
    from mavi_vision.runtime.component_identity import RUNTIME_PACK_ID_RE
    from mavi_vision.runtime.model_pack_identity import MODEL_PACK_ID_RE

    defs = json.loads((SCHEMAS / "vision-job-complete-v3.2.schema.json").read_text())["$defs"]
    assert defs["modelPackId"]["pattern"] == MODEL_PACK_ID_RE.pattern
    assert defs["runtimePackId"]["pattern"] == RUNTIME_PACK_ID_RE.pattern
    example = _v32_example()["provenance"]
    assert MODEL_PACK_ID_RE.fullmatch(example["modelPackId"])
    assert RUNTIME_PACK_ID_RE.fullmatch(example["runtimePackId"])
    assert len(example["modelPackId"]) == defs["modelPackId"]["minLength"] == defs["modelPackId"]["maxLength"]
    assert len(example["runtimePackId"]) == defs["runtimePackId"]["minLength"] == defs["runtimePackId"]["maxLength"]


def test_the_3_2_finalization_response_example_is_schema_valid_and_read_by_the_worker() -> None:
    from mavi_vision.common.control_plane import VisionJobFinalizationResponse

    raw = (EXAMPLES / "vision-job-finalization-response-v3.2.example.json").read_text()
    assert _is_valid("vision-job-finalization-response-v3.2", json.loads(raw))
    assert not _is_valid("vision-job-finalization-response-v3.1", json.loads(raw))
    assert VisionJobFinalizationResponse.model_validate_json(raw).schema_version == "3.2"
