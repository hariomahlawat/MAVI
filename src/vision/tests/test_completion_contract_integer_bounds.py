import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from mavi_vision.common.control_plane import VisionJobComplete


ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "contracts/examples/vision-job-complete-v2.example.json"
SCHEMA = ROOT / "contracts/schemas/vision-job-complete-v2.schema.json"
INT32_OVERFLOW = 2**31
INT64_OVERFLOW = 2**63


def _payload() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _set_overflow(payload: dict, field: str, value: int) -> None:
    track = payload["tracks"][0]
    representative = track["representative"]
    provenance = payload["provenance"]

    if field == "attemptCount":
        payload[field] = value
    elif field in {"framesProcessed", "processingDurationMs"}:
        payload[field] = value
    elif field in {"startOffsetMs", "endOffsetMs", "detectionCount"}:
        track[field] = value
    elif field in {"offsetMs", "sourceFrameNumber"}:
        representative[field] = value
    elif field == "thumbnailSizeBytes":
        representative["thumbnail"]["sizeBytes"] = value
    elif field == "trajectorySizeBytes":
        track["trajectoryArtifact"]["sizeBytes"] = value
    elif field == "configuredDeviceIndex":
        provenance[field] = value
    elif field == "minimumConsecutiveFrames":
        provenance["trackerParameters"][field] = value
    elif field in {"gpuIndex", "gpuVramBytes"}:
        provenance["gpu"] = {
            "name": "qualified-gpu",
            "index": value if field == "gpuIndex" else 0,
            "vramBytes": value if field == "gpuVramBytes" else 1,
            "driverVersion": "1",
            "cudaRuntimeVersion": "1",
            "uuid": "GPU-test",
            "pciBusId": "00000000:01:00.0",
            "computeCapability": "7.5",
        }
    else:
        raise AssertionError(f"unknown field: {field}")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("attemptCount", INT32_OVERFLOW),
        ("framesProcessed", INT64_OVERFLOW),
        ("processingDurationMs", INT64_OVERFLOW),
        ("startOffsetMs", INT64_OVERFLOW),
        ("endOffsetMs", INT64_OVERFLOW),
        ("detectionCount", INT32_OVERFLOW),
        ("offsetMs", INT64_OVERFLOW),
        ("sourceFrameNumber", INT64_OVERFLOW),
        ("thumbnailSizeBytes", INT64_OVERFLOW),
        ("trajectorySizeBytes", INT64_OVERFLOW),
        ("configuredDeviceIndex", INT32_OVERFLOW),
        ("minimumConsecutiveFrames", INT32_OVERFLOW),
        ("gpuIndex", INT32_OVERFLOW),
        ("gpuVramBytes", INT64_OVERFLOW),
    ],
)
def test_completion_integer_bounds_match_csharp_wire_types(
    field: str,
    value: int,
) -> None:
    payload = _payload()
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    _set_overflow(payload, field, value)

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            instance=payload,
            schema=schema,
            format_checker=jsonschema.FormatChecker(),
        )

    with pytest.raises(ValidationError):
        VisionJobComplete.model_validate_json(json.dumps(payload))


def test_completion_accepts_mathematically_integral_json_numbers() -> None:
    payload = _payload()
    payload["attemptCount"] = 1.0
    payload["framesProcessed"] = 3.0
    payload["processingDurationMs"] = 1250.0
    track = payload["tracks"][0]
    track["detectionCount"] = 3.0
    track["startOffsetMs"] = 0.0
    track["endOffsetMs"] = 80.0
    track["representative"]["offsetMs"] = 40.0
    track["representative"]["sourceFrameNumber"] = 1.0

    model = VisionJobComplete.model_validate_json(json.dumps(payload))

    assert model.attempt_count == 1
    assert model.tracks[0].detection_count == 3


def test_completion_rejects_fractional_integer_fields() -> None:
    payload = _payload()
    payload["attemptCount"] = 1.5

    with pytest.raises(ValidationError):
        VisionJobComplete.model_validate_json(json.dumps(payload))


def test_completion_rejects_dimensions_that_cannot_survive_float_persistence() -> None:
    payload = _payload()
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["tracks"][0]["representative"]["boundingBox"]["width"] = 1e-300

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            instance=payload,
            schema=schema,
            format_checker=jsonschema.FormatChecker(),
        )

    with pytest.raises(ValidationError):
        VisionJobComplete.model_validate_json(json.dumps(payload))


def test_completion_schema_caps_track_collection() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema["properties"]["tracks"]["maxItems"] == 10_000


def test_completion_accepts_exact_int64_maximum_decimal_encoding() -> None:
    raw = EXAMPLE.read_text(encoding="utf-8")
    raw = raw.replace(
        '"framesProcessed": 3',
        '"framesProcessed": 9223372036854775807.0',
        1,
    )

    model = VisionJobComplete.model_validate_json(raw)

    assert model.frames_processed == 9_223_372_036_854_775_807
