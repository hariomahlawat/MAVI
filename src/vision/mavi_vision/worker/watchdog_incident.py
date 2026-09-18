from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from uuid import UUID

from mavi_vision.runtime.progress import ProcessingProgressSnapshot
from mavi_vision.runtime.watchdog import RuntimeWatchdogSnapshot


WATCHDOG_FAILURE_CODE = "vision_inference_watchdog_expired"
WATCHDOG_OBSERVATION_FAILURE_CODE = "vision_watchdog_observation_failed"
_ALLOWED_FAILURE_CODES = frozenset(
    {
        WATCHDOG_FAILURE_CODE,
        WATCHDOG_OBSERVATION_FAILURE_CODE,
    }
)
_MAX_INCIDENT_RECORD_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class WatchdogIncidentSnapshot:
    """Secret-safe immutable evidence captured when one attempt watchdog expires."""

    worker_id: str
    job_id: UUID
    attempt_count: int
    failure_code: str
    progress: ProcessingProgressSnapshot
    runtime: RuntimeWatchdogSnapshot | None

    def __post_init__(self) -> None:
        if not self.worker_id or len(self.worker_id) > 128:
            raise ValueError("watchdog_incident_worker_id_invalid")
        if self.attempt_count < 1:
            raise ValueError("watchdog_incident_attempt_invalid")
        if self.failure_code not in _ALLOWED_FAILURE_CODES:
            raise ValueError("watchdog_incident_failure_code_invalid")


class WatchdogIncidentRecorder(Protocol):
    def record(self, incident: WatchdogIncidentSnapshot) -> None: ...


class JsonlWatchdogIncidentRecorder:
    """Durably append bounded watchdog incidents before process-level termination."""

    def __init__(
        self,
        path: Path,
        *,
        max_bytes: int = 1 * 1024 * 1024,
        backup_count: int = 3,
    ) -> None:
        if max_bytes < _MAX_INCIDENT_RECORD_BYTES:
            raise ValueError("watchdog_incident_max_bytes_invalid")
        if backup_count < 1 or backup_count > 16:
            raise ValueError("watchdog_incident_backup_count_invalid")
        self._path = path
        self._max_bytes = max_bytes
        self._backup_count = backup_count

    def record(self, incident: WatchdogIncidentSnapshot) -> None:
        payload = {
            "recordedAtUtc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "workerId": incident.worker_id,
            "jobId": str(incident.job_id),
            "attemptCount": incident.attempt_count,
            "failureCode": incident.failure_code,
            "progress": asdict(incident.progress),
            "runtimeSnapshotAvailable": incident.runtime is not None,
            "runtime": (
                None
                if incident.runtime is None
                else asdict(incident.runtime)
            ),
        }
        encoded = (
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            + "\n"
        ).encode("utf-8")
        if len(encoded) > _MAX_INCIDENT_RECORD_BYTES:
            raise ValueError("watchdog_incident_record_too_large")

        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists() and self._path.is_symlink():
            raise OSError("watchdog_incident_path_symlink_forbidden")

        current_size = self._path.stat().st_size if self._path.exists() else 0
        if current_size + len(encoded) > self._max_bytes:
            self._rotate()

        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        descriptor = os.open(self._path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "ab", closefd=False) as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(descriptor)

    def _rotate(self) -> None:
        oldest = self._backup_path(self._backup_count)
        if oldest.exists():
            oldest.unlink()

        for index in range(self._backup_count - 1, 0, -1):
            source = self._backup_path(index)
            if source.exists():
                os.replace(source, self._backup_path(index + 1))

        if self._path.exists():
            os.replace(self._path, self._backup_path(1))

    def _backup_path(self, index: int) -> Path:
        return self._path.with_name(f"{self._path.name}.{index}")
