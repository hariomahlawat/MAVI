import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from mavi_vision.common.control_plane import VisionJobComplete


ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "contracts/examples/vision-job-complete-v2.example.json"
SCHEMA = ROOT / "contracts/schemas/vision-job-complete-v2.schema.json"


def _payload(model_id: str) -> dict:
    payload = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    payload["provenance"]["modelId"] = model_id
    return payload


def test_completion_contract_identity_limit_counts_unicode_code_points() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    exactly_128 = _payload("😀" * 128)
    too_many = _payload("😀" * 129)

    jsonschema.validate(
        instance=exactly_128,
        schema=schema,
        format_checker=jsonschema.FormatChecker(),
    )
    VisionJobComplete.model_validate_json(json.dumps(exactly_128))

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            instance=too_many,
            schema=schema,
            format_checker=jsonschema.FormatChecker(),
        )
    with pytest.raises(ValidationError):
        VisionJobComplete.model_validate_json(json.dumps(too_many))
