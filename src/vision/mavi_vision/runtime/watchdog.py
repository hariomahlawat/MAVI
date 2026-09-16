from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RuntimeWatchdogSnapshot:
    """One coherent runtime-side observation used for expiry and diagnostics."""

    observed_monotonic: float
    active: bool
    started_monotonic: float | None
    elapsed_seconds: float | None
    completed_count: int
    threshold_seconds: float
    expired: bool
    device: str | None
    model_id: str | None
    runtime_variant: str | None
    pipeline_profile_id: str | None
    model_manifest_sha256: str | None
    checkpoint_sha256: str | None
    resolved_config_sha256: str | None
    pipeline_profile_sha256: str | None
    runtime_profile_sha256: str | None

    def __post_init__(self) -> None:
        if not isfinite(self.observed_monotonic):
            raise ValueError("runtime_watchdog_observation_invalid")
        if not isfinite(self.threshold_seconds) or self.threshold_seconds <= 0:
            raise ValueError("runtime_watchdog_threshold_invalid")
        if self.completed_count < 0:
            raise ValueError("runtime_watchdog_completed_count_invalid")
        if self.active:
            if self.started_monotonic is None or not isfinite(self.started_monotonic):
                raise ValueError("runtime_watchdog_started_invalid")
            if self.elapsed_seconds is None or not isfinite(self.elapsed_seconds):
                raise ValueError("runtime_watchdog_elapsed_invalid")
            if self.elapsed_seconds < 0:
                raise ValueError("runtime_watchdog_elapsed_invalid")
        elif self.elapsed_seconds is not None:
            raise ValueError("runtime_watchdog_inactive_elapsed_invalid")


class RuntimeWatchdogSnapshotProvider(Protocol):
    def __call__(self) -> RuntimeWatchdogSnapshot: ...
