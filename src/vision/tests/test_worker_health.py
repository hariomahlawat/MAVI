from uuid import UUID

from mavi_vision.worker.health import get_worker_health


def test_worker_health_reports_ready_with_versioned_contract() -> None:
    worker_id = UUID("33333333-3333-3333-3333-333333333333")

    health = get_worker_health(worker_id).to_dict()

    assert health["workerId"] == str(worker_id)
    assert health["status"] == "ready"
    assert health["schemaVersion"] == "1.0"
    assert health["timestampUtc"].endswith("Z")
