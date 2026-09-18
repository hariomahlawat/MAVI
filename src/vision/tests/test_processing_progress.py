from __future__ import annotations

from math import inf, nan

import pytest

from mavi_vision.runtime.progress import (
    FINALIZATION_READY_PERCENT,
    FINALIZATION_START_PERCENT,
    PROCESSING_END_PERCENT,
    PROCESSING_START_PERCENT,
    VALIDATION_START_PERCENT,
    ProcessingProgress,
)


class MonotonicClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        current = self.value
        self.value += 1.0
        return current


def test_progress_starts_in_validation_at_one_percent() -> None:
    clock = MonotonicClock()
    progress = ProcessingProgress(source_duration_ms=1_000, monotonic_clock=clock)

    snapshot = progress.reader.snapshot()

    assert snapshot.stage == "validating"
    assert snapshot.frames_processed == 0
    assert snapshot.source_offset_ms is None
    assert snapshot.source_duration_ms == 1_000
    assert snapshot.progress_percent == VALIDATION_START_PERCENT
    assert snapshot.started_monotonic == 100.0
    assert snapshot.last_progress_monotonic == 100.0


def test_processing_floor_is_five_percent_until_media_advances() -> None:
    progress = ProcessingProgress(source_duration_ms=1_000)
    progress.sink.mark_processing_started()

    started = progress.reader.snapshot()
    progress.sink.mark_frame_completed(source_offset_ms=0)
    first = progress.reader.snapshot()

    assert started.stage == "processing"
    assert started.progress_percent == PROCESSING_START_PERCENT
    assert first.frames_processed == 1
    assert first.source_offset_ms == 0
    assert first.progress_percent == PROCESSING_START_PERCENT


def test_media_time_drives_monotonic_processing_progress() -> None:
    progress = ProcessingProgress(source_duration_ms=1_000)
    progress.sink.mark_processing_started()

    progress.sink.mark_frame_completed(source_offset_ms=250)
    first = progress.reader.snapshot()
    progress.sink.mark_frame_completed(source_offset_ms=500)
    second = progress.reader.snapshot()
    progress.sink.mark_frame_completed(source_offset_ms=2_000)
    clamped = progress.reader.snapshot()

    assert first.progress_percent == pytest.approx(26.0)
    assert second.progress_percent == pytest.approx(47.0)
    assert clamped.progress_percent == PROCESSING_END_PERCENT
    assert clamped.frames_processed == 3


def test_zero_duration_never_invents_fps_progress() -> None:
    progress = ProcessingProgress(source_duration_ms=0)
    progress.sink.mark_processing_started()
    progress.sink.mark_frame_completed(source_offset_ms=123)

    snapshot = progress.reader.snapshot()

    assert snapshot.frames_processed == 1
    assert snapshot.source_offset_ms == 123
    assert snapshot.progress_percent == PROCESSING_START_PERCENT


def test_offset_regression_is_rejected_without_mutating_snapshot() -> None:
    progress = ProcessingProgress(source_duration_ms=1_000)
    progress.sink.mark_processing_started()
    progress.sink.mark_frame_completed(source_offset_ms=500)
    before = progress.reader.snapshot()

    with pytest.raises(ValueError, match="processing_progress_offset_regression"):
        progress.sink.mark_frame_completed(source_offset_ms=499)

    assert progress.reader.snapshot() == before


def test_finalization_is_bounded_below_terminal_completion() -> None:
    progress = ProcessingProgress(source_duration_ms=1_000)
    progress.sink.mark_processing_started()
    progress.sink.mark_frame_completed(source_offset_ms=999)
    progress.sink.mark_finalization_started()

    finalizing = progress.reader.snapshot()
    progress.sink.mark_finalization_ready()
    ready = progress.reader.snapshot()

    assert finalizing.stage == "finalizing"
    assert finalizing.progress_percent == FINALIZATION_START_PERCENT
    assert ready.progress_percent == FINALIZATION_READY_PERCENT
    assert ready.progress_percent < 100.0


@pytest.mark.parametrize("value", [nan, inf, -inf])
def test_non_finite_clock_is_rejected(value: float) -> None:
    with pytest.raises(ValueError, match="processing_progress_clock_invalid"):
        ProcessingProgress(source_duration_ms=1_000, monotonic_clock=lambda: value)


def test_negative_duration_is_rejected() -> None:
    with pytest.raises(ValueError, match="processing_progress_duration_invalid"):
        ProcessingProgress(source_duration_ms=-1)


def test_reader_and_sink_are_narrow_views() -> None:
    progress = ProcessingProgress(source_duration_ms=1_000)

    assert hasattr(progress.reader, "snapshot")
    assert not hasattr(progress.reader, "mark_frame_completed")
    assert hasattr(progress.sink, "mark_frame_completed")
    assert not hasattr(progress.sink, "snapshot")



def test_frame_progress_remains_atomic_when_clock_fails() -> None:
    readings = iter((100.0, 101.0, float("nan")))

    progress = ProcessingProgress(
        source_duration_ms=1_000,
        monotonic_clock=lambda: next(readings),
    )
    progress.sink.mark_processing_started()
    before = progress.reader.snapshot()

    with pytest.raises(ValueError, match="processing_progress_clock_invalid"):
        progress.sink.mark_frame_completed(source_offset_ms=500)

    after = progress.reader.snapshot()
    assert after == before
    assert after.frames_processed == 0
    assert after.source_offset_ms is None
    assert after.progress_percent == PROCESSING_START_PERCENT
