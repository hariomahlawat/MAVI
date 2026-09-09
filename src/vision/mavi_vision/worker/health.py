from datetime import datetime, timezone

from mavi_vision.common.control_plane import WorkerHealth


def get_worker_health(worker_id: str) -> WorkerHealth:
    return WorkerHealth(schema_version="2.0", worker_id=worker_id, status="ready", timestamp_utc=datetime.now(timezone.utc))
