from uuid import UUID

from mavi_vision.common.contracts import WorkerHealth


def get_worker_health(worker_id: UUID) -> WorkerHealth:
    return WorkerHealth.ready(worker_id)
