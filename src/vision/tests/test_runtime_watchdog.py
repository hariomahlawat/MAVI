from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone
from math import inf, nan
from pathlib import Path

import pytest

from mavi_vision.common.analytical import VisionProcessingResult
from mavi_vision.common.control_plane import VisionJobHeartbeatResponse, VisionJobLease
from mavi_vision.common.lease import LeaseGuard
from mavi_vision.runtime.activity import InferenceActivity
from mavi_vision.runtime.execution_lane import VisionExecutionLane
from mavi_vision.runtime.watchdog import RuntimeWatchdogSnapshot
from mavi_vision.storage.local_media_store import LocalMediaStore
from mavi_vision.worker.client import WorkerApiError
from mavi_vision.worker.runner import WorkerRunner
from mavi_vision.worker.watchdog_incident import WATCHDOG_OBSERVATION_FAILURE_CODE


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


def test_inference_activity_treats_pre_start_sample_as_not_hung() -> None:
    activity = InferenceActivity(monotonic_clock=ManualMonotonicClock(100.0))
    activity.mark_started()

    assert (
        activity.is_hung(now_monotonic=99.999, threshold_seconds=5.0)
        is False
    )


@pytest.mark.parametrize("started_at", [inf, -inf, nan])
def test_inference_activity_rejects_invalid_start_clock(started_at: float) -> None:
    activity = InferenceActivity(monotonic_clock=ManualMonotonicClock(started_at))

    with pytest.raises(ValueError, match="inference_activity_clock_invalid"):
        activity.mark_started()


ROOT = Path(__file__).resolve().parents[3]
WATCHDOG_LEASE_EXAMPLE = ROOT / "contracts/examples/vision-job-lease-v2.example.json"
PROVENANCE_SENTINEL = object()


def _watchdog_lease() -> VisionJobLease:
    return VisionJobLease.model_validate_json(WATCHDOG_LEASE_EXAMPLE.read_text())


def _heartbeat_response(seconds: float = 60.0) -> VisionJobHeartbeatResponse:
    return VisionJobHeartbeatResponse(
        schemaVersion="2.0",
        progressPercent=5.0,
        leaseExpiresAtUtc=datetime.now(timezone.utc) + timedelta(seconds=seconds),
    )


class _WatchdogApi:
    def __init__(
        self,
        lease: VisionJobLease,
        *,
        release_on_heartbeat: threading.Event | None = None,
    ) -> None:
        self.lease_value = lease
        self.release_on_heartbeat = release_on_heartbeat
        self.heartbeats: list[float] = []
        self.failures: list[str] = []
        self.completions: list[tuple[VisionProcessingResult, object]] = []

    async def lease(self) -> VisionJobLease | None:
        return self.lease_value

    async def heartbeat(
        self,
        lease: VisionJobLease,
        progress_percent: float,
    ) -> VisionJobHeartbeatResponse:
        del lease
        self.heartbeats.append(progress_percent)
        if len(self.heartbeats) >= 2 and self.release_on_heartbeat is not None:
            self.release_on_heartbeat.set()
        return _heartbeat_response()

    async def fail(
        self,
        lease: VisionJobLease,
        failure_code: str,
        failure_message: str | None = None,
    ) -> None:
        del lease, failure_message
        self.failures.append(failure_code)

    async def complete(
        self,
        lease: VisionJobLease,
        result: VisionProcessingResult,
        processing_duration_ms: int,
        provenance: object,
        *,
        authorize_publish=None,
    ) -> object:
        del lease, processing_duration_ms
        if authorize_publish is not None:
            authorize_publish()
        self.completions.append((result, provenance))
        return object()


class _BlockingProcessor:
    def __init__(
        self,
        started: threading.Event,
        release: threading.Event,
        *,
        check_guard_after_release: bool = False,
    ) -> None:
        self.started = started
        self.release = release
        self.check_guard_after_release = check_guard_after_release

    def process(
        self,
        *,
        job_id,
        attempt_count: int,
        source_path: Path,
        expected_source_size_bytes: int,
        expected_source_sha256: str,
        lease_guard: LeaseGuard,
        progress_sink=None,
    ) -> VisionProcessingResult:
        del attempt_count, source_path, expected_source_size_bytes, expected_source_sha256
        self.started.set()
        if not self.release.wait(timeout=2.0):
            raise TimeoutError("watchdog test release signal not received")
        if self.check_guard_after_release:
            lease_guard.check_owned()
        return VisionProcessingResult(job_id=job_id, frames_processed=1, tracks=())


class _FatalTerminatorSentinel(RuntimeError):
    pass


def _materialize_watchdog_source(tmp_path: Path, lease: VisionJobLease) -> None:
    path = tmp_path.joinpath(*lease.source_storage_key.split("/"))
    path.parent.mkdir(parents=True)
    path.write_bytes(b"video")


def test_watchdog_polling_does_not_postpone_absolute_heartbeat_schedule(
    tmp_path: Path,
) -> None:
    lease = _watchdog_lease()
    _materialize_watchdog_source(tmp_path, lease)
    started = threading.Event()
    release = threading.Event()
    client = _WatchdogApi(lease, release_on_heartbeat=release)
    processor = _BlockingProcessor(started, release)
    clock = [0.0]
    poll_count = 0

    def watchdog_expired() -> bool:
        nonlocal poll_count
        poll_count += 1
        clock[0] += 0.25
        return False

    result = asyncio.run(
        WorkerRunner(
            client,
            LocalMediaStore(tmp_path),
            2.0,
            processor,
            heartbeat_interval_seconds=0.5,
            process_executor=None,
            watchdog_expired=watchdog_expired,
            watchdog_poll_seconds=0.001,
            monotonic_clock=lambda: clock[0],
            runtime_provenance_provider=lambda: PROVENANCE_SENTINEL,
        ).run_once()
    )

    assert result is True
    assert started.is_set() is True
    assert poll_count >= 2
    assert len(client.heartbeats) >= 2
    assert client.failures == []
    assert len(client.completions) == 1
    assert client.completions[0][1] is PROVENANCE_SENTINEL


def test_watchdog_expiry_with_unwind_in_grace_surfaces_only_lease_loss(
    tmp_path: Path,
) -> None:
    lease = _watchdog_lease()
    _materialize_watchdog_source(tmp_path, lease)
    started = threading.Event()
    release = threading.Event()
    client = _WatchdogApi(lease)
    processor = _BlockingProcessor(
        started,
        release,
        check_guard_after_release=True,
    )
    expiry_reports: list[str] = []
    fatal_codes: list[int] = []

    def expiry_sink() -> None:
        expiry_reports.append("expired")
        release.set()

    def terminator(code: int) -> None:
        fatal_codes.append(code)
        raise _FatalTerminatorSentinel("terminator must not run")

    with pytest.raises(WorkerApiError, match="lease ownership lost"):
        asyncio.run(
            WorkerRunner(
                client,
                LocalMediaStore(tmp_path),
                2.0,
                processor,
                process_executor=None,
                watchdog_expired=lambda: started.is_set(),
                watchdog_expiry_sink=expiry_sink,
                watchdog_grace_seconds=0.1,
                watchdog_poll_seconds=0.001,
                fatal_terminator=terminator,
            ).run_once()
        )

    assert expiry_reports == ["expired"]
    assert fatal_codes == []
    assert client.heartbeats == [1.0]
    assert client.failures == []


def test_stuck_watchdog_invokes_fatal_terminator_once_without_stale_fail(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        lease = _watchdog_lease()
        _materialize_watchdog_source(tmp_path, lease)
        started = threading.Event()
        release = threading.Event()
        client = _WatchdogApi(lease)
        processor = _BlockingProcessor(started, release)
        lane = VisionExecutionLane()
        expiry_reports: list[str] = []
        fatal_codes: list[int] = []

        def terminator(code: int) -> None:
            fatal_codes.append(code)
            raise _FatalTerminatorSentinel("fatal-watchdog")

        runner = WorkerRunner(
            client,
            LocalMediaStore(tmp_path),
            2.0,
            processor,
            process_executor=lane,
            watchdog_expired=lambda: started.is_set(),
            watchdog_expiry_sink=lambda: expiry_reports.append("expired"),
            watchdog_grace_seconds=0.01,
            watchdog_poll_seconds=0.001,
            fatal_terminator=terminator,
        )

        try:
            with pytest.raises(_FatalTerminatorSentinel, match="fatal-watchdog"):
                await runner.run_once()
        finally:
            release.set()
            await lane.close()

        assert expiry_reports == ["expired"]
        assert fatal_codes == [70]
        assert runner.fatal_termination_active is True
        assert client.heartbeats == [1.0]
        assert client.failures == []

    asyncio.run(scenario())


@pytest.mark.parametrize("poll_seconds", [0.0, -0.1, 1.001])
def test_worker_rejects_invalid_watchdog_poll_interval(
    tmp_path: Path,
    poll_seconds: float,
) -> None:
    lease = _watchdog_lease()
    with pytest.raises(ValueError, match="watchdog_poll_seconds"):
        WorkerRunner(
            _WatchdogApi(lease),
            LocalMediaStore(tmp_path),
            2.0,
            watchdog_expired=lambda: False,
            watchdog_poll_seconds=poll_seconds,
        )


class _SlowHeartbeatApi(_WatchdogApi):
    def __init__(self, lease: VisionJobLease) -> None:
        super().__init__(lease)
        self.renewal_started = asyncio.Event()
        self.renewal_cancelled = False

    async def heartbeat(
        self,
        lease: VisionJobLease,
        progress_percent: float,
    ) -> VisionJobHeartbeatResponse:
        del lease
        self.heartbeats.append(progress_percent)
        if len(self.heartbeats) == 1:
            return _heartbeat_response()

        self.renewal_started.set()
        try:
            await asyncio.sleep(10.0)
        except asyncio.CancelledError:
            self.renewal_cancelled = True
            raise
        return _heartbeat_response()


def test_watchdog_keeps_polling_while_heartbeat_request_is_in_flight(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        lease = _watchdog_lease()
        _materialize_watchdog_source(tmp_path, lease)
        started = threading.Event()
        release = threading.Event()
        client = _SlowHeartbeatApi(lease)
        processor = _BlockingProcessor(
            started,
            release,
            check_guard_after_release=True,
        )
        expiry_reports: list[str] = []
        watchdog_polls = 0

        def watchdog_expired() -> bool:
            nonlocal watchdog_polls
            watchdog_polls += 1
            return client.renewal_started.is_set()

        def expiry_sink() -> None:
            expiry_reports.append("expired")
            release.set()

        runner = WorkerRunner(
            client,
            LocalMediaStore(tmp_path),
            2.0,
            processor,
            heartbeat_interval_seconds=0.01,
            process_executor=None,
            watchdog_expired=watchdog_expired,
            watchdog_expiry_sink=expiry_sink,
            watchdog_grace_seconds=0.1,
            watchdog_poll_seconds=0.001,
        )

        with pytest.raises(WorkerApiError, match="lease ownership lost"):
            await runner.run_once()

        assert client.renewal_started.is_set() is True
        assert client.renewal_cancelled is True
        assert watchdog_polls >= 2
        assert expiry_reports == ["expired"]
        assert client.heartbeats == [1.0, 1.0]
        assert client.failures == []

    asyncio.run(scenario())



def test_watchdog_incident_captures_one_coherent_runtime_and_attempt_snapshot(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        lease = _watchdog_lease()
        _materialize_watchdog_source(tmp_path, lease)
        started = threading.Event()
        release = threading.Event()
        client = _WatchdogApi(lease)
        processor = _BlockingProcessor(started, release)
        lane = VisionExecutionLane()
        records = []
        fatal_codes: list[int] = []

        class Recorder:
            def record(self, incident) -> None:
                records.append(incident)

        def runtime_snapshot() -> RuntimeWatchdogSnapshot:
            active = started.is_set()
            return RuntimeWatchdogSnapshot(
                observed_monotonic=221.0 if active else 100.0,
                active=active,
                started_monotonic=100.0 if active else None,
                elapsed_seconds=121.0 if active else None,
                completed_count=7,
                threshold_seconds=120.0,
                expired=active,
                device="cpu",
                model_id="rtmdet-m-coco",
                runtime_variant="windows-x86_64-cpu",
                pipeline_profile_id="phase1-detection-tracking-v1",
                model_manifest_sha256="a" * 64,
                checkpoint_sha256="b" * 64,
                resolved_config_sha256="c" * 64,
                pipeline_profile_sha256="d" * 64,
                runtime_profile_sha256="e" * 64,
            )

        def terminator(code: int) -> None:
            fatal_codes.append(code)
            raise _FatalTerminatorSentinel("fatal-watchdog")

        runner = WorkerRunner(
            client,
            LocalMediaStore(tmp_path),
            2.0,
            processor,
            process_executor=lane,
            watchdog_snapshot_provider=runtime_snapshot,
            watchdog_expiry_sink=lambda: None,
            watchdog_incident_recorder=Recorder(),
            watchdog_grace_seconds=0.01,
            watchdog_poll_seconds=0.001,
            fatal_terminator=terminator,
        )

        try:
            with pytest.raises(_FatalTerminatorSentinel, match="fatal-watchdog"):
                await runner.run_once()
        finally:
            release.set()
            await lane.close()

        assert fatal_codes == [70]
        assert len(records) == 1
        incident = records[0]
        assert incident.worker_id == str(lease.worker_id)
        assert incident.job_id == lease.job_id
        assert incident.attempt_count == lease.attempt_count
        assert incident.progress.progress_percent == 1.0
        assert incident.progress.frames_processed == 0
        assert incident.runtime.expired is True
        assert incident.runtime.elapsed_seconds == 121.0
        assert client.failures == []

    asyncio.run(scenario())



def test_watchdog_snapshot_provider_failure_is_durable_and_secret_safe(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario() -> None:
        lease = _watchdog_lease()
        _materialize_watchdog_source(tmp_path, lease)
        started = threading.Event()
        release = threading.Event()
        client = _WatchdogApi(lease)
        processor = _BlockingProcessor(started, release)
        lane = VisionExecutionLane()
        records = []
        fatal_codes: list[int] = []

        class Recorder:
            def record(self, incident) -> None:
                records.append(incident)

        def failing_snapshot() -> RuntimeWatchdogSnapshot:
            raise RuntimeError(r"C:\secret\runtime token=do-not-send")

        def terminator(code: int) -> None:
            fatal_codes.append(code)
            raise _FatalTerminatorSentinel("fatal-watchdog")

        runner = WorkerRunner(
            client,
            LocalMediaStore(tmp_path),
            2.0,
            processor,
            process_executor=lane,
            watchdog_snapshot_provider=failing_snapshot,
            watchdog_incident_recorder=Recorder(),
            watchdog_grace_seconds=0.01,
            watchdog_poll_seconds=0.001,
            fatal_terminator=terminator,
        )

        try:
            with pytest.raises(_FatalTerminatorSentinel, match="fatal-watchdog"):
                await runner.run_once()
        finally:
            release.set()
            await lane.close()

        assert fatal_codes == [70]
        assert len(records) == 1
        incident = records[0]
        assert incident.failure_code == WATCHDOG_OBSERVATION_FAILURE_CODE
        assert incident.runtime is None
        assert incident.progress.progress_percent == 1.0
        assert client.failures == []

    awaitable = scenario()
    asyncio.run(awaitable)

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert "Watchdog snapshot provider failed" in rendered
    assert "do-not-send" not in rendered
    assert r"C:\secret\runtime" not in rendered



def test_blocked_watchdog_incident_recorder_cannot_block_fatal_containment(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario() -> None:
        lease = _watchdog_lease()
        _materialize_watchdog_source(tmp_path, lease)
        started = threading.Event()
        release = threading.Event()
        recorder_release = threading.Event()
        client = _WatchdogApi(lease)
        processor = _BlockingProcessor(started, release)
        lane = VisionExecutionLane()
        fatal_codes: list[int] = []

        class BlockingRecorder:
            def record(self, incident) -> None:
                del incident
                recorder_release.wait(timeout=2.0)

        def runtime_snapshot() -> RuntimeWatchdogSnapshot:
            active = started.is_set()
            return RuntimeWatchdogSnapshot(
                observed_monotonic=221.0 if active else 100.0,
                active=active,
                started_monotonic=100.0 if active else None,
                elapsed_seconds=121.0 if active else None,
                completed_count=0,
                threshold_seconds=120.0,
                expired=active,
                device="cpu",
                model_id=None,
                runtime_variant=None,
                pipeline_profile_id=None,
                model_manifest_sha256=None,
                checkpoint_sha256=None,
                resolved_config_sha256=None,
                pipeline_profile_sha256=None,
                runtime_profile_sha256=None,
            )

        def terminator(code: int) -> None:
            fatal_codes.append(code)
            raise _FatalTerminatorSentinel("fatal-watchdog")

        runner = WorkerRunner(
            client,
            LocalMediaStore(tmp_path),
            2.0,
            processor,
            process_executor=lane,
            watchdog_snapshot_provider=runtime_snapshot,
            watchdog_incident_recorder=BlockingRecorder(),
            watchdog_incident_write_timeout_seconds=0.01,
            watchdog_grace_seconds=0.01,
            watchdog_poll_seconds=0.001,
            fatal_terminator=terminator,
        )

        try:
            with pytest.raises(_FatalTerminatorSentinel, match="fatal-watchdog"):
                await runner.run_once()
        finally:
            recorder_release.set()
            release.set()
            await lane.close()

        assert fatal_codes == [70]
        assert client.failures == []

    asyncio.run(scenario())

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert "Watchdog incident persistence timed out" in rendered


def test_worker_rejects_non_positive_watchdog_incident_write_timeout(
    tmp_path: Path,
) -> None:
    lease = _watchdog_lease()

    with pytest.raises(
        ValueError,
        match="watchdog_incident_write_timeout_seconds",
    ):
        WorkerRunner(
            _WatchdogApi(lease),
            LocalMediaStore(tmp_path),
            2.0,
            watchdog_incident_write_timeout_seconds=0.0,
        )
