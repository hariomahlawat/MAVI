from __future__ import annotations

from math import inf, nan

import pytest

from mavi_vision.runtime.activity import InferenceActivity


class ManualMonotonicClock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_inference_activity_is_not_hung_while_inactive() -> None:
    clock = ManualMonotonicClock(100.0)
    activity = InferenceActivity(monotonic_clock=clock)

    snapshot = activity.snapshot()

    assert snapshot.active is False
    assert snapshot.started_monotonic is None
    assert snapshot.completed_count == 0
    assert activity.is_hung(now_monotonic=10_000.0, threshold_seconds=30.0) is False


def test_inference_activity_watchdog_threshold_is_inclusive() -> None:
    clock = ManualMonotonicClock(100.0)
    activity = InferenceActivity(monotonic_clock=clock)
    activity.mark_started()

    assert activity.is_hung(now_monotonic=129.999, threshold_seconds=30.0) is False
    assert activity.is_hung(now_monotonic=130.0, threshold_seconds=30.0) is True
    assert activity.is_hung(now_monotonic=131.0, threshold_seconds=30.0) is True


def test_completed_activity_clears_active_state_and_increments_counter() -> None:
    clock = ManualMonotonicClock(42.5)
    activity = InferenceActivity(monotonic_clock=clock)

    activity.mark_started()
    active_snapshot = activity.snapshot()
    assert active_snapshot.active is True
    assert active_snapshot.started_monotonic == 42.5
    assert active_snapshot.completed_count == 0

    activity.mark_completed()
    completed_snapshot = activity.snapshot()

    assert completed_snapshot.active is False
    assert completed_snapshot.started_monotonic is None
    assert completed_snapshot.completed_count == 1
    assert activity.is_hung(now_monotonic=1_000.0, threshold_seconds=10.0) is False


def test_inference_activity_counts_multiple_completed_calls() -> None:
    clock = ManualMonotonicClock(10.0)
    activity = InferenceActivity(monotonic_clock=clock)

    activity.mark_started()
    activity.mark_completed()
    clock.value = 20.0
    activity.mark_started()
    activity.mark_completed()

    assert activity.snapshot().completed_count == 2


def test_inference_activity_rejects_overlapping_start() -> None:
    activity = InferenceActivity(monotonic_clock=ManualMonotonicClock(1.0))
    activity.mark_started()

    with pytest.raises(RuntimeError, match="inference_activity_already_active"):
        activity.mark_started()


def test_inference_activity_rejects_completion_without_active_call() -> None:
    activity = InferenceActivity(monotonic_clock=ManualMonotonicClock(1.0))

    with pytest.raises(RuntimeError, match="inference_activity_not_active"):
        activity.mark_completed()


@pytest.mark.parametrize("threshold", [0.0, -1.0, inf, nan])
def test_inference_activity_rejects_invalid_watchdog_threshold(
    threshold: float,
) -> None:
    activity = InferenceActivity(monotonic_clock=ManualMonotonicClock(1.0))

    with pytest.raises(ValueError, match="inference_watchdog_threshold_invalid"):
        activity.is_hung(now_monotonic=2.0, threshold_seconds=threshold)


@pytest.mark.parametrize("now_monotonic", [inf, -inf, nan])
def test_inference_activity_rejects_non_finite_observation_time(
    now_monotonic: float,
) -> None:
    activity = InferenceActivity(monotonic_clock=ManualMonotonicClock(1.0))
    activity.mark_started()

    with pytest.raises(ValueError, match="inference_watchdog_now_invalid"):
        activity.is_hung(now_monotonic=now_monotonic, threshold_seconds=5.0)


def test_inference_activity_rejects_monotonic_regression() -> None:
    activity = InferenceActivity(monotonic_clock=ManualMonotonicClock(100.0))
    activity.mark_started()

    with pytest.raises(ValueError, match="inference_watchdog_clock_regressed"):
        activity.is_hung(now_monotonic=99.999, threshold_seconds=5.0)


@pytest.mark.parametrize("started_at", [inf, -inf, nan])
def test_inference_activity_rejects_invalid_start_clock(started_at: float) -> None:
    activity = InferenceActivity(monotonic_clock=ManualMonotonicClock(started_at))

    with pytest.raises(ValueError, match="inference_activity_clock_invalid"):
        activity.mark_started()
