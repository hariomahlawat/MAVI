from datetime import datetime, timezone

from mavi_vision.common.control_plane import WorkerHealth


class WorkerHealthUnavailable(RuntimeError):
    """Local readiness failure; worker-health-v2 has no non-ready wire status."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def get_worker_health(
    worker_id: str,
    *,
    runtime_ready: bool,
) -> WorkerHealth:
    if not runtime_ready:
        raise WorkerHealthUnavailable("runtime_not_ready")

    return WorkerHealth.model_validate(
        {
            "schemaVersion": "2.0",
            "workerId": worker_id,
            "status": "ready",
            "timestampUtc": datetime.now(timezone.utc),
        }
    )
