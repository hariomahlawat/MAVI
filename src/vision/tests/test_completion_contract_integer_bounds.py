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
