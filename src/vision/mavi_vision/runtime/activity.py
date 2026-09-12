from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class InferenceActivitySnapshot:
    """Point-in-time view of process-scoped inference activity."""

    active: bool
    started_monotonic: float | None
    completed_count: int


class InferenceActivity:
    """Thread-safe monotonic activity marker consumed by the watchdog supervisor."""

    def __init__(
        self,
        *,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._monotonic_clock = monotonic_clock
        self._lock = threading.Lock()
        self._active = False
        self._started_monotonic: float | None = None
        self._completed_count = 0

    def mark_started(self) -> None:
        started = self._monotonic_clock()
        if not isfinite(started):
            raise ValueError("inference_activity_clock_invalid")

        with self._lock:
            if self._active:
                raise RuntimeError("inference_activity_already_active")
            self._active = True
            self._started_monotonic = started

    def mark_completed(self) -> None:
        with self._lock:
            if not self._active:
                raise RuntimeError("inference_activity_not_active")
            self._active = False
            self._started_monotonic = None
            self._completed_count += 1

    def snapshot(self) -> InferenceActivitySnapshot:
        with self._lock:
            return InferenceActivitySnapshot(
                active=self._active,
                started_monotonic=self._started_monotonic,
                completed_count=self._completed_count,
            )

    def is_hung(
        self,
        *,
        now_monotonic: float,
        threshold_seconds: float,
    ) -> bool:
        if not isfinite(now_monotonic):
            raise ValueError("inference_watchdog_now_invalid")
        if not isfinite(threshold_seconds) or threshold_seconds <= 0:
            raise ValueError("inference_watchdog_threshold_invalid")

        with self._lock:
            if not self._active:
                return False

            started = self._started_monotonic
            if started is None:
                # This state should be impossible because all writes are guarded
                # by the same lock. Fail closed if internal state is corrupted.
                raise RuntimeError("inference_activity_state_invalid")

            elapsed = now_monotonic - started
            if elapsed < 0:
                raise ValueError("inference_watchdog_clock_regressed")
            return elapsed >= threshold_seconds
