"""Completion 3.3 (ADR-016): the worker's models refuse the shared negative corpus."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mavi_vision.common.control_plane import VisionJobCompleteV32, VisionJobCompleteV33

ROOT = Path(__file__).resolve().parents[3]
BASES = {
    "installed": ROOT / "contracts/examples/vision-job-complete-v3.3.example.json",
    "unpacked": ROOT / "contracts/examples/vision-job-complete-v3.3-unpacked-environment.example.json",
}
CORPUS = json.loads((ROOT / "contracts/test-vectors/control-plane-v3.3-invalid.json").read_text(encoding="utf-8"))["cases"]
MODELS = {"3.2": VisionJobCompleteV32, "3.3": VisionJobCompleteV33}


def _payload(case: dict) -> dict:
    """The same patching rule as tools/verify_repo.py and the .NET corpus test."""
    payload = json.loads(BASES[case["base"]].read_text(encoding="utf-8"))
    if "schemaVersion" in case:
        payload["schemaVersion"] = case["schemaVersion"]
    for field in case.get("remove", []):
        del payload[field]
    payload.update(case.get("set", {}))
    for edit in case.get("tracks", []):
        track = payload["tracks"][edit["index"]]
        for field in edit.get("remove", []):
            del track[field]
        track.update(edit.get("set", {}))
    return payload


@pytest.mark.parametrize("case", CORPUS, ids=[case["name"] for case in CORPUS])
def test_every_shared_invalid_case_is_refused_by_the_worker_model(case: dict) -> None:
    payload = _payload(case)
    with pytest.raises(ValidationError):
        MODELS[payload["schemaVersion"]].model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("name", sorted(BASES))
def test_the_examples_are_accepted_and_round_trip(name: str) -> None:
    raw = BASES[name].read_text(encoding="utf-8")
    model = VisionJobCompleteV33.model_validate_json(raw)
    assert json.loads(model.model_dump_json(by_alias=True)) == json.loads(raw)


def test_an_explicit_null_subclass_is_refused() -> None:
    payload = json.loads(BASES["installed"].read_text(encoding="utf-8"))
    payload["tracks"][1]["objectSubclass"] = None
    with pytest.raises(ValidationError, match="never null"):
        VisionJobCompleteV33.model_validate_json(json.dumps(payload))
