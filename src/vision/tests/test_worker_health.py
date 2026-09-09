from mavi_vision.worker.health import get_worker_health


def test_worker_health_reports_ready_with_versioned_contract() -> None:
    health = get_worker_health("gpu-sdd-01").model_dump(by_alias=True, mode="json")
    assert health["workerId"] == "gpu-sdd-01"
    assert health["status"] == "ready"
    assert health["schemaVersion"] == "2.0"
    assert health["timestampUtc"].endswith("Z")
