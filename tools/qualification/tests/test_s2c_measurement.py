"""E2 must use the real runner, including its aggregation/publication path."""
import asyncio
from pathlib import Path

import pytest


def test_e2_runs_existing_runner_through_inference_seam():
    from tests.test_attribute_role import FakeApi, _person_lease
    from mavi_vision.attributes.inference import FixtureAttributeInferencer
    from mavi_vision.attributes.pipeline import load_attribute_pipeline
    from model_selection.operational_measurement import measure_attempts
    api = FakeApi(_person_lease())
    profile = load_attribute_pipeline(Path(__file__).resolve().parents[3]/"tests/fixtures/visual-attributes/fixture-pipeline-v1.json")
    result = asyncio.run(measure_attempts(api, pair={"personUnitId": "P", "vehicleUnitId": "V"},
        identity_sha256="a"*64, worker_id="test", profile=profile, inferencer=FixtureAttributeInferencer("seed"),
        provenance={"fixture": True}, heartbeat_interval_seconds=0.01, request_timeout_seconds=1,
        maximum_attempts=1, api_mode="synthetic-test"))
    assert result["attempts"] == [{"status": "completed", "failureCode": None}]
    operations = [e["operation"] for e in result["calls"]]
    assert operations[0] == "lease"
    assert "read_evidence" in operations and operations[-2:] == ["upload", "complete"]
    assert api.uploaded and api.completions
    assert all(type(e["durationUs"]) is int and e["durationUs"] >= 0 for e in result["calls"])
    assert all("capability" not in e for e in result["calls"])


def test_e2_cannot_label_synthetic_api_as_real_platform():
    from model_selection.operational_measurement import measure_attempts
    with pytest.raises(ValueError, match="real_platform_client_required"):
        asyncio.run(measure_attempts(object(), pair={"personUnitId": "P", "vehicleUnitId": "V"},
            identity_sha256="a"*64, worker_id="test", profile=None, inferencer=None, provenance={},
            heartbeat_interval_seconds=0.01, request_timeout_seconds=1, maximum_attempts=1, api_mode="real-platform"))
