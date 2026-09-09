from datetime import datetime, timezone

from mavi_vision.common.control_plane import WorkerHealth


def get_worker_health(worker_id: str) -> WorkerHealth:
    return WorkerHealth.model_validate(
        {
            "schemaVersion": "2.0",
            "workerId": worker_id,
            "status": "ready",
            "timestampUtc": datetime.now(timezone.utc),
        }
    )
