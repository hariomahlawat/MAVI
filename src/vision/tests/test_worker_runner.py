import asyncio
import json
from pathlib import Path

import pytest

from mavi_vision.common.control_plane import VisionJobHeartbeatResponse, VisionJobLease
from mavi_vision.storage.local_media_store import LocalMediaStore
from mavi_vision.worker.client import WorkerApiError
from mavi_vision.worker.runner import WorkerRunner


ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "contracts/examples/vision-job-lease-v2.example.json"


# Test doubles
class FakeWorkerApiClient:
    def __init__(self, leased_job: VisionJobLease | None) -> None:
        self.leased_job = leased_job
        self.heartbeats: list[float] = []
        self.failures: list[tuple[str, str | None]] = []

    async def lease(self) -> VisionJobLease | None:
        return self.leased_job

    async def heartbeat(
        self, lease: VisionJobLease, progress_percent: float
    ) -> VisionJobHeartbeatResponse:
        self.heartbeats.append(progress_percent)
        return VisionJobHeartbeatResponse.model_validate_json(
            '{"schemaVersion":"2.0","progressPercent":5.0,'
            '"leaseExpiresAtUtc":"2026-09-09T03:00:00Z"}'
        )

    async def fail(
        self,
        lease: VisionJobLease,
        failure_code: str,
        failure_message: str | None = None,
    ) -> None:
        self.failures.append((failure_code, failure_message))


class FailingTerminalWorkerApiClient(FakeWorkerApiClient):
    async def fail(
        self,
        lease: VisionJobLease,
        failure_code: str,
        failure_message: str | None = None,
    ) -> None:
        self.failures.append((failure_code, failure_message))
        raise WorkerApiError("worker API request failed")


class FailingHeartbeatWorkerApiClient(FakeWorkerApiClient):
    async def heartbeat(
        self, lease: VisionJobLease, progress_percent: float
    ) -> VisionJobHeartbeatResponse:
        self.heartbeats.append(progress_percent)
        raise WorkerApiError("worker API request failed")


class BackoffProbeWorkerApiClient(FailingHeartbeatWorkerApiClient):
    def __init__(self, leased_job: VisionJobLease) -> None:
        super().__init__(leased_job)
        self.lease_calls = 0
        self.events: list[str] = []

    async def lease(self) -> VisionJobLease | None:
        self.lease_calls += 1
        self.events.append("lease")
        if self.lease_calls == 1:
            return self.leased_job
        raise RuntimeError("stop polling probe")

    async def heartbeat(
        self, lease: VisionJobLease, progress_percent: float
    ) -> VisionJobHeartbeatResponse:
        self.events.append("heartbeat")
        return await super().heartbeat(lease, progress_percent)


class ExplodingMediaStore:
    def resolve_file(self, storage_key: str) -> Path:
        raise RuntimeError(f"secret path and token: {storage_key}")


# Test helpers
def make_lease(storage_key: str = "videos/input.mp4") -> VisionJobLease:
    payload = json.loads(EXAMPLE.read_text())
    payload["sourceStorageKey"] = storage_key
    return VisionJobLease.model_validate_json(json.dumps(payload))


# Worker iterations
def test_no_work_iteration_returns_false_without_lifecycle_calls(tmp_path: Path) -> None:
    client = FakeWorkerApiClient(None)
    result = asyncio.run(WorkerRunner(client, LocalMediaStore(tmp_path), 2.0).run_once())
    assert result is False
    assert client.heartbeats == []
    assert client.failures == []


def test_valid_dummy_lifecycle_heartbeats_then_fails(tmp_path: Path) -> None:
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir()
    media.write_bytes(b"video")
    client = FakeWorkerApiClient(make_lease())

    result = asyncio.run(WorkerRunner(client, LocalMediaStore(tmp_path), 2.0).run_once())

    assert result is True
    assert client.heartbeats == [5.0]
    assert client.failures == [
        ("dummy_processing_not_implemented", "Dummy processing is not implemented.")
    ]


def test_terminal_fail_error_is_not_followed_by_second_fail(tmp_path: Path) -> None:
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir()
    media.write_bytes(b"video")
    client = FailingTerminalWorkerApiClient(make_lease())

    with pytest.raises(WorkerApiError):
        asyncio.run(WorkerRunner(client, LocalMediaStore(tmp_path), 2.0).run_once())

    assert client.heartbeats == [5.0]
    assert client.failures == [
        ("dummy_processing_not_implemented", "Dummy processing is not implemented.")
    ]


def test_heartbeat_api_error_propagates_for_polling_backoff(tmp_path: Path) -> None:
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir()
    media.write_bytes(b"video")
    client = FailingHeartbeatWorkerApiClient(make_lease())

    with pytest.raises(WorkerApiError):
        asyncio.run(WorkerRunner(client, LocalMediaStore(tmp_path), 2.0).run_once())

    assert client.heartbeats == [5.0]
    assert client.failures == []


def test_run_forever_sleeps_before_next_lease_after_worker_api_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir()
    media.write_bytes(b"video")
    client = BackoffProbeWorkerApiClient(make_lease())
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)
        client.events.append("sleep")

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with pytest.raises(RuntimeError, match="stop polling probe"):
        asyncio.run(WorkerRunner(client, LocalMediaStore(tmp_path), 2.0).run_forever())

    assert sleep_calls == [2.0]
    assert client.events == ["lease", "heartbeat", "sleep", "lease"]


def test_missing_source_media_uses_controlled_failure(tmp_path: Path) -> None:
    client = FakeWorkerApiClient(make_lease())
    result = asyncio.run(WorkerRunner(client, LocalMediaStore(tmp_path), 2.0).run_once())
    assert result is True
    assert client.heartbeats == []
    assert client.failures == [
        ("source_media_unavailable", "Leased source media is unavailable.")
    ]


def test_unexpected_error_uses_generic_controlled_failure(tmp_path: Path) -> None:
    leased_job = make_lease()
    client = FakeWorkerApiClient(leased_job)
    result = asyncio.run(WorkerRunner(client, ExplodingMediaStore(), 2.0).run_once())
    assert result is True
    assert client.heartbeats == []
    assert client.failures == [
        ("worker_unhandled_error", "The worker encountered an unexpected error.")
    ]
    assert leased_job.lease_token not in client.failures[0][1]
    assert leased_job.source_storage_key not in client.failures[0][1]
