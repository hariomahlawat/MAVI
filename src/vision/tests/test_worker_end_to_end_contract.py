from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from mavi_vision.common.analytical import VisionProcessingResult
from mavi_vision.common.control_plane import VisionJobHeartbeatResponse, VisionJobLease
from mavi_vision.common.lease import LeaseGuard
from mavi_vision.storage.local_media_store import LocalMediaStore
from mavi_vision.worker.runner import WorkerRunner

ROOT = Path(__file__).resolve().parents[3]
LEASE_EXAMPLE = ROOT / "contracts/examples/vision-job-lease-v2.example.json"
PROVENANCE = object()


class RecordingApi:
    def __init__(self, lease: VisionJobLease) -> None:
        self.lease_value = lease
        self.events: list[str] = []
        self.completion_authorized = False
        self.completed_result: VisionProcessingResult | None = None
        self.provenance: object | None = None

    async def lease(self) -> VisionJobLease | None:
        self.events.append("lease")
        value, self.lease_value = self.lease_value, None
        return value

    async def heartbeat(self, lease: VisionJobLease, progress_percent: float) -> VisionJobHeartbeatResponse:
        self.events.append("heartbeat")
        return VisionJobHeartbeatResponse.model_validate_json(
            '{"schemaVersion":"2.0","progressPercent":5.0,'
            '"leaseExpiresAtUtc":"2099-09-09T03:00:00Z"}'
        )

    async def fail(self, lease: VisionJobLease, failure_code: str, failure_message: str | None = None) -> None:
        self.events.append("fail:" + failure_code)

    async def complete(
        self,
        lease: VisionJobLease,
        result: VisionProcessingResult,
        processing_duration_ms: int,
        provenance: object,
        *,
        authorize_publish=None,
    ) -> object:
        self.events.append("authorize")
        if authorize_publish is not None:
            authorize_publish()
        self.completion_authorized = True
        self.events.append("complete")
        self.completed_result = result
        self.provenance = provenance
        assert processing_duration_ms >= 0
        return object()


class IntegrityCheckingProcessor:
    def __init__(self, expected_bytes: bytes, result: VisionProcessingResult) -> None:
        self.expected_bytes = expected_bytes
        self.result = result
        self.guard_seen: LeaseGuard | None = None

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
        lease_guard.check_owned()
        payload = source_path.read_bytes()
        assert len(payload) == expected_source_size_bytes
        assert hashlib.sha256(payload).hexdigest() == expected_source_sha256
        assert attempt_count >= 1
        assert job_id == self.result.job_id
        return self.result


def make_lease(source_bytes: bytes) -> VisionJobLease:
    value = json.loads(LEASE_EXAMPLE.read_text(encoding="utf-8"))
    value["sourceStorageKey"] = "source/qualification.mp4"
    value["sourceSizeBytes"] = len(source_bytes)
    value["sourceSha256"] = hashlib.sha256(source_bytes).hexdigest()
    return VisionJobLease.model_validate(value)


def test_worker_contract_executes_lease_source_heartbeat_processing_authorized_completion(tmp_path: Path) -> None:
    source_bytes = b"task17-worker-contract-media"
    lease = make_lease(source_bytes)
    source = tmp_path / "source" / "qualification.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(source_bytes)

    result = VisionProcessingResult(
        job_id=lease.job_id,
        frames_processed=1,
        tracks=(),
    )
    api = RecordingApi(lease)
    processor = IntegrityCheckingProcessor(source_bytes, result)
    duration = iter([100.0, 100.125])

    worked = asyncio.run(
        WorkerRunner(
            api,
            LocalMediaStore(tmp_path),
            poll_interval_seconds=1.0,
            processor=processor,
            runtime_provenance_provider=lambda: PROVENANCE,
            duration_clock=lambda: next(duration),
        ).run_once()
    )

    assert worked is True
    assert api.events == ["lease", "heartbeat", "authorize", "complete"]
    assert api.completion_authorized is True
    assert api.completed_result == result
    assert api.provenance is PROVENANCE
    assert processor.guard_seen is not None
    assert processor.guard_seen.is_lost() is False


def test_worker_without_runtime_provenance_fails_instead_of_completing(tmp_path: Path) -> None:
    source_bytes = b"task17-worker-contract-no-provenance"
    lease = make_lease(source_bytes)
    source = tmp_path / "source" / "qualification.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(source_bytes)

    result = VisionProcessingResult(job_id=lease.job_id, frames_processed=1, tracks=())
    api = RecordingApi(lease)
    processor = IntegrityCheckingProcessor(source_bytes, result)

    worked = asyncio.run(
        WorkerRunner(
            api,
            LocalMediaStore(tmp_path),
            poll_interval_seconds=1.0,
            processor=processor,
            runtime_provenance_provider=lambda: None,
        ).run_once()
    )

    assert worked is True
    assert "complete" not in api.events
    assert api.events[-1] == "fail:vision_runtime_provenance_unavailable"
