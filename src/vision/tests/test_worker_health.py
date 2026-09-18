import pytest

from mavi_vision.worker.health import WorkerHealthUnavailable, get_worker_health


def test_worker_health_reports_ready_with_versioned_contract() -> None:
    health = get_worker_health(
        "gpu-sdd-01",
        runtime_ready=True,
    ).model_dump(by_alias=True, mode="json")

    assert health["workerId"] == "gpu-sdd-01"
    assert health["status"] == "ready"
    assert health["schemaVersion"] == "2.0"
    assert health["timestampUtc"].endswith("Z")


def test_worker_health_refuses_to_serialize_non_ready_runtime() -> None:
    with pytest.raises(WorkerHealthUnavailable, match="runtime_not_ready"):
        get_worker_health("gpu-sdd-01", runtime_ready=False)
