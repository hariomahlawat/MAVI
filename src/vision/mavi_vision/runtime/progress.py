from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from typing import Literal, Protocol


ProcessingStage = Literal["validating", "processing", "finalizing"]

VALIDATION_START_PERCENT = 1.0
PROCESSING_START_PERCENT = 5.0
PROCESSING_END_PERCENT = 89.0
FINALIZATION_START_PERCENT = 90.0
FINALIZATION_READY_PERCENT = 95.0
RUNNING_MAX_PERCENT = FINALIZATION_READY_PERCENT


@dataclass(frozen=True, slots=True)
class ProcessingProgressSnapshot:
    """Immutable attempt-local processing progress observed by the event loop."""

    stage: ProcessingStage
    frames_processed: int
    source_offset_ms: int | None
    source_duration_ms: int
    progress_percent: float
    last_progress_monotonic: float


class ProcessingProgressReader(Protocol):
    def snapshot(self) -> ProcessingProgressSnapshot: ...


class ProcessingProgressSink(Protocol):
    def mark_processing_started(self) -> None: ...

    def mark_frame_completed(self, *, source_offset_ms: int) -> None: ...

    def mark_finalization_started(self) -> None: ...

    def mark_finalization_ready(self) -> None: ...


class _Reader:
    def __init__(self, owner: "ProcessingProgress") -> None:
        self._owner = owner

    def snapshot(self) -> ProcessingProgressSnapshot:
        return self._owner.snapshot()


class _Sink:
    def __init__(self, owner: "ProcessingProgress") -> None:
        self._owner = owner

    def mark_processing_started(self) -> None:
        self._owner.mark_processing_started()

    def mark_frame_completed(self, *, source_offset_ms: int) -> None:
        self._owner.mark_frame_completed(source_offset_ms=source_offset_ms)

    def mark_finalization_started(self) -> None:
        self._owner.mark_finalization_started()

    def mark_finalization_ready(self) -> None:
        self._owner.mark_finalization_ready()


class ProcessingProgress:
    """Thread-safe progress state for exactly one leased processing attempt.

    WorkerRunner owns this object. The event-loop side receives only the reader;
    the synchronous vision lane receives only the sink. Progress is observational:
    it never performs I/O and never attempts to cancel native processing.
    """

    def __init__(
        self,
        *,
        source_duration_ms: int,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if source_duration_ms < 0:
            raise ValueError("processing_progress_duration_invalid")

        observed = monotonic_clock()
        if not isfinite(observed):
            raise ValueError("processing_progress_clock_invalid")

        self._source_duration_ms = source_duration_ms
        self._monotonic_clock = monotonic_clock
        self._lock = threading.Lock()
        self._stage: ProcessingStage = "validating"
        self._frames_processed = 0
        self._source_offset_ms: int | None = None
        self._progress_percent = VALIDATION_START_PERCENT
        self._last_progress_monotonic = observed
        self._reader = _Reader(self)
        self._sink = _Sink(self)

    @property
    def reader(self) -> ProcessingProgressReader:
        return self._reader

    @property
    def sink(self) -> ProcessingProgressSink:
        return self._sink

    def snapshot(self) -> ProcessingProgressSnapshot:
        with self._lock:
            return ProcessingProgressSnapshot(
                stage=self._stage,
                frames_processed=self._frames_processed,
                source_offset_ms=self._source_offset_ms,
                source_duration_ms=self._source_duration_ms,
                progress_percent=self._progress_percent,
                last_progress_monotonic=self._last_progress_monotonic,
            )

    def mark_processing_started(self) -> None:
        with self._lock:
            self._advance(
                stage="processing",
                progress_percent=PROCESSING_START_PERCENT,
            )

    def mark_frame_completed(self, *, source_offset_ms: int) -> None:
        if source_offset_ms < 0:
            raise ValueError("processing_progress_offset_invalid")

        with self._lock:
            if self._stage != "processing":
                raise RuntimeError("processing_progress_frame_outside_processing")

            previous_offset = self._source_offset_ms
            if previous_offset is not None and source_offset_ms < previous_offset:
                raise ValueError("processing_progress_offset_regression")

            progress = PROCESSING_START_PERCENT
            if self._source_duration_ms > 0:
                media_fraction = min(
                    1.0,
                    max(0.0, source_offset_ms / self._source_duration_ms),
                )
                progress = PROCESSING_START_PERCENT + (
                    PROCESSING_END_PERCENT - PROCESSING_START_PERCENT
                ) * media_fraction

            self._frames_processed += 1
            self._source_offset_ms = source_offset_ms
            self._advance(
                stage="processing",
                progress_percent=max(self._progress_percent, progress),
            )

    def mark_finalization_started(self) -> None:
        with self._lock:
            if self._stage == "validating":
                raise RuntimeError("processing_progress_finalization_before_processing")
            self._advance(
                stage="finalizing",
                progress_percent=FINALIZATION_START_PERCENT,
            )

    def mark_finalization_ready(self) -> None:
        with self._lock:
            if self._stage != "finalizing":
                raise RuntimeError("processing_progress_finalization_not_started")
            self._advance(
                stage="finalizing",
                progress_percent=FINALIZATION_READY_PERCENT,
            )

    def _advance(
        self,
        *,
        stage: ProcessingStage,
        progress_percent: float,
    ) -> None:
        if (
            not isfinite(progress_percent)
            or progress_percent < self._progress_percent
            or progress_percent > RUNNING_MAX_PERCENT
        ):
            raise ValueError("processing_progress_value_invalid")

        observed = self._monotonic_clock()
        if not isfinite(observed):
            raise ValueError("processing_progress_clock_invalid")

        self._stage = stage
        self._progress_percent = progress_percent
        self._last_progress_monotonic = observed
