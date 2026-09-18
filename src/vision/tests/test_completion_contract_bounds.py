import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from mavi_vision.common.control_plane import VisionJobComplete


ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "contracts/examples/vision-job-complete-v2.example.json"
SCHEMA = ROOT / "contracts/schemas/vision-job-complete-v2.schema.json"


@pytest.mark.parametrize(
    ("mutation", "value"),
    [
        ("modelId", "m" * 129),
        ("modelVersion", "v" * 129),
        ("trackers", "t" * 129),
    ],
)
def test_completion_contracts_share_server_provenance_identity_bounds(
    mutation: str,
    value: str,
) -> None:
    payload = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    if mutation == "trackers":
        payload["provenance"]["dependencyVersions"]["trackers"] = value
    else:
        payload["provenance"][mutation] = value

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            instance=payload,
            schema=schema,
            format_checker=jsonschema.FormatChecker(),
        )

    with pytest.raises(ValidationError):
        VisionJobComplete.model_validate_json(json.dumps(payload))


def test_json_array_normalization_does_not_relax_strict_python_mode() -> None:
    """Tuple-backed fields accept a JSON array only in JSON mode."""
    from mavi_vision.common.control_plane import VisionPlatformIdentity

    platform = json.loads(EXAMPLE.read_text(encoding="utf-8"))["provenance"][
        "platform"
    ]

    with pytest.raises(ValidationError):
        VisionPlatformIdentity.model_validate(
            {**platform, "pythonBuild": ["main", "Sep 1 2026"]}
        )

    value = VisionPlatformIdentity.model_validate(
        {**platform, "pythonBuild": ("main", "Sep 1 2026")}
    )
    assert value.python_build == ("main", "Sep 1 2026")


def test_json_array_normalization_preserves_tuple_arity() -> None:
    payload = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    payload["provenance"]["platform"]["pythonBuild"] = ["a", "b", "c"]

    with pytest.raises(ValidationError):
        VisionJobComplete.model_validate_json(json.dumps(payload))
