import asyncio
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mavi_vision.common.analytical import VisionProcessingResult
from mavi_vision.common.control_plane import VisionJobHeartbeatResponse, VisionJobLease
from mavi_vision.common.lease import LeaseGuard, LeaseLostError
from mavi_vision.storage.local_media_store import LocalMediaStore
from mavi_vision.worker.client import WorkerApiError
from mavi_vision.worker.runner import WorkerRunner


ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "contracts/examples/vision-job-lease-v2.example.json"


def make_lease() -> VisionJobLease:
    return VisionJobLease.model_validate_json(EXAMPLE.read_text())


def heartbeat_response(expires_in_seconds: float) -> VisionJobHeartbeatResponse:
    return VisionJobHeartbeatResponse(
        schemaVersion="2.0",
        progressPercent=5.0,
        leaseExpiresAtUtc=datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds),
    )


class HeartbeatCountingApi:
    def __init__(self, lease: VisionJobLease) -> None:
        self.lease_value = lease
        self.heartbeats: list[float] = []
        self.heartbeat_times: list[float] = []
        self.failures: list[str] = []

    async def lease(self) -> VisionJobLease | None:
        return self.lease_value

    async def heartbeat(
        self, lease: VisionJobLease, progress_percent: float
    ) -> VisionJobHeartbeatResponse:
        self.heartbeats.append(progress_percent)
        self.heartbeat_times.append(time.monotonic())
        return heartbeat_response(60.0)

    async def fail(
        self,
        lease: VisionJobLease,
        failure_code: str,
        failure_message: str | None = None,
    ) -> None:
        self.failures.append(failure_code)


class ShortDeadlineApi(HeartbeatCountingApi):
    async def heartbeat(
        self, lease: VisionJobLease, progress_percent: float
    ) -> VisionJobHeartbeatResponse:
        self.heartbeats.append(progress_percent)
        self.heartbeat_times.append(time.monotonic())
        return heartbeat_response(0.30)


class CompletionDeadlineApi(HeartbeatCountingApi):
    async def heartbeat(
        self, lease: VisionJobLease, progress_percent: float
    ) -> VisionJobHeartbeatResponse:
        self.heartbeats.append(progress_percent)
        self.heartbeat_times.append(time.monotonic())
        return heartbeat_response(0.05)


class RenewalPastDeadlineApi(HeartbeatCountingApi):
    async def heartbeat(
        self, lease: VisionJobLease, progress_percent: float
    ) -> VisionJobHeartbeatResponse:
        self.heartbeats.append(progress_percent)
        self.heartbeat_times.append(time.monotonic())
        if len(self.heartbeats) == 1:
            return heartbeat_response(0.12)
        await asyncio.sleep(0.20)
        return heartbeat_response(60.0)


class LeaseLostApi(HeartbeatCountingApi):
    async def heartbeat(
        self, lease: VisionJobLease, progress_percent: float
    ) -> VisionJobHeartbeatResponse:
        self.heartbeats.append(progress_percent)
        self.heartbeat_times.append(time.monotonic())
        if len(self.heartbeats) >= 2:
            raise WorkerApiError("lease ownership lost")
        return heartbeat_response(60.0)


class SlowProcessor:
    def __init__(self, lease: VisionJobLease, delay_seconds: float = 0.05) -> None:
        self.lease = lease
        self.delay_seconds = delay_seconds
        self.guard_seen: LeaseGuard | None = None
        self.attempt_count_seen: int | None = None

    def process(
        self,
        *,
        job_id,
        attempt_count: int,
        source_path: Path,
        expected_source_size_bytes: int,
        expected_source_sha256: str,
        lease_guard: LeaseGuard,
    ) -> VisionProcessingResult:
        self.guard_seen = lease_guard
        self.attempt_count_seen = attempt_count
        lease_guard.check_owned()
        time.sleep(self.delay_seconds)
        lease_guard.check_owned()
        return VisionProcessingResult(job_id=job_id, frames_processed=1, tracks=())


class EventLoopStallProcessor:
    def __init__(self, delay_seconds: float = 0.08) -> None:
        self.delay_seconds = delay_seconds
        self.started = threading.Event()
        self.guard_rejected_publication = False

    def process(
        self,
        *,
        job_id,
        attempt_count: int,
        source_path: Path,
        expected_source_size_bytes: int,
        expected_source_sha256: str,
        lease_guard: LeaseGuard,
    ) -> VisionProcessingResult:
        self.started.set()
        time.sleep(self.delay_seconds)
        try:
            # Model the ownership check immediately before artifact publication.
            # This executes in the processing thread while the asyncio loop is stalled.
            lease_guard.check_owned()
        except LeaseLostError:
            self.guard_rejected_publication = True
            raise
        return VisionProcessingResult(job_id=job_id, frames_processed=1, tracks=())


class CancellationWaitingProcessor:
    def __init__(self) -> None:
        self.cancellation_observed = False

    def process(
        self,
        *,
        job_id,
        attempt_count: int,
        source_path: Path,
        expected_source_size_bytes: int,
        expected_source_sha256: str,
        lease_guard: LeaseGuard,
    ) -> VisionProcessingResult:
        deadline = time.monotonic() + 1.0
        while not lease_guard.is_lost():
            if time.monotonic() >= deadline:
                raise AssertionError("lease cancellation was not propagated")
            time.sleep(0.002)
        self.cancellation_observed = True
        raise LeaseLostError()


def _materialize_source(tmp_path: Path, lease: VisionJobLease) -> None:
    media = tmp_path.joinpath(*lease.source_storage_key.split("/"))
    media.parent.mkdir(parents=True)
    media.write_bytes(b"video")


def test_long_processing_renews_lease_periodically(tmp_path: Path) -> None:
    lease = make_lease()
    _materialize_source(tmp_path, lease)
    client = HeartbeatCountingApi(lease)
    processor = SlowProcessor(lease)

    result = asyncio.run(
        WorkerRunner(
            client,
            LocalMediaStore(tmp_path),
            2.0,
            processor,
            heartbeat_interval_seconds=0.01,
        ).run_once()
    )

    assert result is True
    assert isinstance(processor.guard_seen, LeaseGuard)
    assert processor.attempt_count_seen == lease.attempt_count
    assert len(client.heartbeats) >= 2
    assert client.heartbeats[0] == 5.0
    assert client.failures == ["task9_result_submission_not_implemented"]


def test_server_deadline_overrides_longer_configured_heartbeat_interval(
    tmp_path: Path,
) -> None:
    lease = make_lease()
    _materialize_source(tmp_path, lease)
    client = ShortDeadlineApi(lease)
    processor = SlowProcessor(lease, delay_seconds=0.50)

    result = asyncio.run(
        WorkerRunner(
            client,
            LocalMediaStore(tmp_path),
            2.0,
            processor,
            heartbeat_interval_seconds=30.0,
            heartbeat_request_timeout_seconds=30.0,
        ).run_once()
    )

    assert result is True
    assert len(client.heartbeat_times) >= 2
    assert client.heartbeat_times[1] - client.heartbeat_times[0] < 0.30
    assert client.failures == ["task9_result_submission_not_implemented"]


def test_event_loop_stall_cannot_bypass_processing_thread_lease_guard(
    tmp_path: Path,
) -> None:
    lease = make_lease()
    _materialize_source(tmp_path, lease)
    client = CompletionDeadlineApi(lease)
    processor = EventLoopStallProcessor()
    runner = WorkerRunner(
        client,
        LocalMediaStore(tmp_path),
        2.0,
        processor,
        heartbeat_interval_seconds=30.0,
        heartbeat_request_timeout_seconds=30.0,
    )

    async def run_with_stalled_event_loop() -> None:
        run_task = asyncio.create_task(runner.run_once())
        assert await asyncio.to_thread(processor.started.wait, 1.0)
        # Simulate a suspended/blocked event loop while the processing thread crosses
        # the authoritative deadline and reaches its publication boundary.
        time.sleep(0.10)
        await run_task

    with pytest.raises(WorkerApiError, match="lease ownership lost"):
        asyncio.run(run_with_stalled_event_loop())

    assert processor.guard_rejected_publication is True
    assert client.failures == []


def test_heartbeat_response_must_arrive_before_current_lease_deadline(
    tmp_path: Path,
) -> None:
    lease = make_lease()
    _materialize_source(tmp_path, lease)
    client = RenewalPastDeadlineApi(lease)
    processor = CancellationWaitingProcessor()

    with pytest.raises(WorkerApiError, match="heartbeat deadline exceeded"):
        asyncio.run(
            WorkerRunner(
                client,
                LocalMediaStore(tmp_path),
                2.0,
                processor,
                heartbeat_interval_seconds=30.0,
                heartbeat_request_timeout_seconds=30.0,
            ).run_once()
        )

    assert processor.cancellation_observed is True
    assert client.failures == []


def test_lease_loss_cancels_processing_and_does_not_submit_terminal_failure(
    tmp_path: Path,
) -> None:
    lease = make_lease()
    _materialize_source(tmp_path, lease)
    client = LeaseLostApi(lease)
    processor = CancellationWaitingProcessor()

    with pytest.raises(WorkerApiError, match="lease ownership lost"):
        asyncio.run(
            WorkerRunner(
                client,
                LocalMediaStore(tmp_path),
                2.0,
                processor,
                heartbeat_interval_seconds=0.01,
            ).run_once()
        )

    assert processor.cancellation_observed is True
    assert client.heartbeats == [5.0, 5.0]
    assert client.failures == []
