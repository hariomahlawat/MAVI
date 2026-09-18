from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from threading import Lock


class LeaseLostError(RuntimeError):
    """Raised when the worker no longer owns the current lease attempt."""

    def __init__(self) -> None:
        super().__init__("lease_lost")


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError("lease_deadline_must_be_utc")
    return value


class LeaseGuard:
    """Thread-safe local projection of the server-authoritative lease lifetime.

    The guard is shared by the asyncio control-plane loop and the synchronous
    processing thread. Explicit loss is irreversible. A successful heartbeat may
    replace the current deadline with any valid UTC value because the server is
    authoritative, including a shorter deadline than the worker previously held.
    """

    def __init__(
        self,
        lease_expires_at_utc: datetime,
        now_utc: Callable[[], datetime] | None = None,
    ) -> None:
        self._lock = Lock()
        self._deadline_utc = _require_utc(lease_expires_at_utc)
        self._explicitly_lost = False
        self._now_utc = now_utc or (lambda: datetime.now(timezone.utc))

    def update_deadline(self, lease_expires_at_utc: datetime) -> None:
        deadline = _require_utc(lease_expires_at_utc)
        with self._lock:
            if not self._explicitly_lost:
                self._deadline_utc = deadline

    def mark_lost(self) -> None:
        with self._lock:
            self._explicitly_lost = True

    def is_lost(self) -> bool:
        now = _require_utc(self._now_utc())
        with self._lock:
            return self._explicitly_lost or now >= self._deadline_utc

    def check_owned(self) -> None:
        if self.is_lost():
            raise LeaseLostError()
