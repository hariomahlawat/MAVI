import asyncio
import json
import time
from pathlib import Path

from mavi_vision.common.analytical import VisionProcessingResult
from mavi_vision.common.control_plane import VisionJobHeartbeatResponse, VisionJobLease
from mavi_vision.storage.local_media_store import LocalMediaStore
from mavi_vision.worker.runner import WorkerRunner


ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "contracts/examples/vision-job-lease-v2.example.json"


def make_lease() -> VisionJobLease:
    return VisionJobLease.model_validate_json(EXAMPLE.read_text())


class HeartbeatCountingApi:
    def __init__(self, lease: VisionJobLease) -> None:
        self.lease_value = lease
        self.heartbeats: list[float] = []
        self.failures: list[str] = []

    async def lease(self) -> VisionJobLease | None:
        return self.lease_value

    async def heartbeat(
        self, lease: VisionJobLease, progress_percent: float
    ) -> VisionJobHeartbeatResponse:
        self.heartbeats.append(progress_percent)
        return VisionJobHeartbeatResponse.model_validate_json(
            '{"schemaVersion":"2.0","progressPercent":5.0,'
            '"leaseExpiresAtUtc":"2026-09-10T12:00:00Z"}'
        )

    async def fail(
        self,
        lease: VisionJobLease,
        failure_code: str,
        failure_message: str | None = None,
    ) -> None:
        self.failures.append(failure_code)


class SlowProcessor:
    def __init__(self, lease: VisionJobLease) -> None:
        self.lease = lease
        self.cancel_probe_seen = False

    def process(
        self,
        *,
        job_id,
        source_path: Path,
        expected_source_size_bytes: int,
        expected_source_sha256: str,
        cancel_requested=None,
    ) -> VisionProcessingResult:
        self.cancel_probe_seen = callable(cancel_requested)
        time.sleep(0.05)
        return VisionProcessingResult(job_id=job_id, frames_processed=1, tracks=())


def test_long_processing_renews_lease_periodically(tmp_path: Path) -> None:
    lease = make_lease()
    media = tmp_path.joinpath(*lease.source_storage_key.split("/"))
    media.parent.mkdir(parents=True)
    media.write_bytes(b"video")
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
    assert processor.cancel_probe_seen is True
    assert len(client.heartbeats) >= 2
    assert client.heartbeats[0] == 5.0
    assert client.failures == ["task9_result_submission_not_implemented"]
