from datetime import datetime, timedelta, timezone

import pytest

from mavi_vision.common.lease import LeaseGuard, LeaseLostError


BASE = datetime(2026, 9, 10, 14, 30, tzinfo=timezone.utc)


def test_guard_detects_deadline_expiry_without_runner_cancellation() -> None:
    now = BASE
    guard = LeaseGuard(BASE + timedelta(seconds=5), now_utc=lambda: now)

    guard.check_owned()
    now = BASE + timedelta(seconds=5)

    assert guard.is_lost() is True
    with pytest.raises(LeaseLostError, match="lease_lost"):
        guard.check_owned()


def test_guard_mark_lost_is_immediate_and_irreversible() -> None:
    guard = LeaseGuard(BASE + timedelta(minutes=1), now_utc=lambda: BASE)

    guard.mark_lost()

    assert guard.is_lost() is True
    with pytest.raises(LeaseLostError, match="lease_lost"):
        guard.check_owned()


def test_guard_accepts_authoritative_renewal_and_shortened_deadline() -> None:
    now = BASE
    guard = LeaseGuard(BASE + timedelta(seconds=30), now_utc=lambda: now)

    guard.update_deadline(BASE + timedelta(seconds=60))
    now = BASE + timedelta(seconds=40)
    guard.check_owned()

    guard.update_deadline(BASE + timedelta(seconds=45))
    now = BASE + timedelta(seconds=45)

    with pytest.raises(LeaseLostError, match="lease_lost"):
        guard.check_owned()


def test_guard_rejects_naive_or_non_utc_deadlines() -> None:
    with pytest.raises(ValueError, match="lease_deadline_must_be_utc"):
        LeaseGuard(datetime(2026, 9, 10, 14, 30))

    non_utc = datetime(2026, 9, 10, 20, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    with pytest.raises(ValueError, match="lease_deadline_must_be_utc"):
        LeaseGuard(non_utc)
