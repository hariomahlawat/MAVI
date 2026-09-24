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
    platform_contract_confirmed: bool,
) -> WorkerHealth:
    if not runtime_ready:
        raise WorkerHealthUnavailable("runtime_not_ready")
    if not platform_contract_confirmed:
        # The platform has not (yet) listed completion 3.0; no job is leased.
        raise WorkerHealthUnavailable("vision_platform_contract_unsupported")

    return WorkerHealth.model_validate(
        {
            "schemaVersion": "2.0",
            "workerId": worker_id,
            "status": "ready",
            "timestampUtc": datetime.now(timezone.utc),
        }
    )
