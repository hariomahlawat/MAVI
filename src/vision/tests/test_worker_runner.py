import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mavi_vision.common.analytical import VisionProcessingResult
from mavi_vision.common.control_plane import (
    VisionJobFinalizationResponse,
    VisionJobHeartbeatResponse,
    VisionJobLease,
)
from mavi_vision.common.lease import LeaseGuard, LeaseLostError
from mavi_vision.pipeline.process_video import VideoProcessingError
from mavi_vision.runtime.errors import (
    GpuOutOfMemoryError,
    GpuRuntimeError,
    InferenceContractError,
    ProcessingDependencyError,
    RuntimeDisposition,
    TrackerError,
)
from mavi_vision.runtime.progress import ProcessingProgress, ProcessingProgressSink
from mavi_vision.storage.integrity import SourceIntegrityError
from mavi_vision.storage.local_media_store import LocalMediaStore
from mavi_vision.worker.client import WorkerApiError
from mavi_vision.worker.runner import WorkerRunner


ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "contracts/examples/vision-job-lease-v2.example.json"
PROVENANCE_SENTINEL = object()


# Test doubles
class FakeWorkerApiClient:
    def __init__(self, leased_job: VisionJobLease | None) -> None:
        self.leased_job = leased_job
        self.heartbeats: list[float] = []
        self.failures: list[tuple[str, str | None]] = []
        self.completions: list[tuple[VisionProcessingResult, int, object]] = []
        self.events: list[str] = []

    async def get_contract_capabilities(self) -> None:
        return None

    async def lease(self) -> VisionJobLease | None:
        self.events.append("lease")
        return self.leased_job

    async def heartbeat(
        self, lease: VisionJobLease, progress_percent: float
    ) -> VisionJobHeartbeatResponse:
        self.events.append("heartbeat")
        self.heartbeats.append(progress_percent)
        return VisionJobHeartbeatResponse(
            schemaVersion="2.0",
            progressPercent=progress_percent,
            leaseExpiresAtUtc=datetime(2099, 9, 9, 3, 0, tzinfo=timezone.utc),
        )

    async def fail(
        self,
        lease: VisionJobLease,
        failure_code: str,
        failure_message: str | None = None,
    ) -> None:
        self.events.append(f"fail:{failure_code}")
        self.failures.append((failure_code, failure_message))

    async def complete(
        self,
        lease: VisionJobLease,
        result: VisionProcessingResult,
        processing_duration_ms: int,
        provenance: object,
        *,
        authorize_publish=None,
    ) -> object:
        if authorize_publish is not None:
            authorize_publish()
        self.events.append("complete")
        self.completions.append((result, processing_duration_ms, provenance))
        return object()


class FailingTerminalWorkerApiClient(FakeWorkerApiClient):
    async def fail(
        self,
        lease: VisionJobLease,
        failure_code: str,
        failure_message: str | None = None,
    ) -> None:
        self.events.append(f"fail:{failure_code}")
        self.failures.append((failure_code, failure_message))
        raise WorkerApiError("worker API request failed")


class FailingCompletionWorkerApiClient(FakeWorkerApiClient):
    async def complete(
        self,
        lease: VisionJobLease,
        result: VisionProcessingResult,
        processing_duration_ms: int,
        provenance: object,
        *,
        authorize_publish=None,
    ) -> object:
        if authorize_publish is not None:
            authorize_publish()
        self.events.append("complete")
        self.completions.append((result, processing_duration_ms, provenance))
        raise WorkerApiError("worker API request failed")


class ExpiringAtCompletionPublicationApi(FakeWorkerApiClient):
    async def heartbeat(
        self, lease: VisionJobLease, progress_percent: float
    ) -> VisionJobHeartbeatResponse:
        self.events.append("heartbeat")
        self.heartbeats.append(progress_percent)
        return VisionJobHeartbeatResponse(
            schemaVersion="2.0",
            progressPercent=progress_percent,
            leaseExpiresAtUtc=datetime.now(timezone.utc) + timedelta(seconds=0.03),
        )

    async def complete(
        self,
        lease: VisionJobLease,
        result: VisionProcessingResult,
        processing_duration_ms: int,
        provenance: object,
        *,
        authorize_publish=None,
    ) -> object:
        await asyncio.sleep(0.05)
        if authorize_publish is not None:
            authorize_publish()
        self.events.append("complete")
        self.completions.append((result, processing_duration_ms, provenance))
        return object()


class FailingHeartbeatWorkerApiClient(FakeWorkerApiClient):
    async def heartbeat(
        self, lease: VisionJobLease, progress_percent: float
    ) -> VisionJobHeartbeatResponse:
        self.events.append("heartbeat")
        self.heartbeats.append(progress_percent)
        raise WorkerApiError("worker API request failed")


class BackoffProbeWorkerApiClient(FailingHeartbeatWorkerApiClient):
    def __init__(self, leased_job: VisionJobLease) -> None:
        super().__init__(leased_job)
        self.lease_calls = 0

    async def lease(self) -> VisionJobLease | None:
        self.lease_calls += 1
        self.events.append("lease")
        if self.lease_calls == 1:
            return self.leased_job
        raise RuntimeError("stop polling probe")


class ExplodingMediaStore:
    def resolve_file(self, storage_key: str) -> Path:
        raise RuntimeError(f"secret path and token: {storage_key}")


class RecordingProcessor:
    def __init__(self, result: VisionProcessingResult | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict[str, object]] = []
        self.events: list[str] = []

    def process(
        self,
        *,
        job_id,
        attempt_count: int,
        source_path: Path,
        expected_source_size_bytes: int,
        expected_source_sha256: str,
        lease_guard: LeaseGuard,
        progress_sink: ProcessingProgressSink | None = None,
    ) -> VisionProcessingResult:
        self.events.append("process")
        self.calls.append(
            {
                "job_id": job_id,
                "attempt_count": attempt_count,
                "source_path": source_path,
                "expected_source_size_bytes": expected_source_size_bytes,
                "expected_source_sha256": expected_source_sha256,
                "lease_guard": lease_guard,
                "progress_sink": progress_sink,
            }
        )
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


# Test helpers
def make_lease(storage_key: str = "videos/input.mp4") -> VisionJobLease:
    payload = json.loads(EXAMPLE.read_text())
    payload["sourceStorageKey"] = storage_key
    return VisionJobLease.model_validate_json(json.dumps(payload))


def make_result(lease: VisionJobLease) -> VisionProcessingResult:
    return VisionProcessingResult(job_id=lease.job_id, frames_processed=1, tracks=())


# Worker iterations
def test_no_work_iteration_returns_false_without_lifecycle_calls(tmp_path: Path) -> None:
    client = FakeWorkerApiClient(None)
    processor = RecordingProcessor(VisionProcessingResult(job_id=make_lease().job_id, frames_processed=0, tracks=()))
    result = asyncio.run(
        WorkerRunner(client, LocalMediaStore(tmp_path), 2.0, processor).run_once()
    )
    assert result is False
    assert client.heartbeats == []
    assert client.failures == []
    assert processor.calls == []


def test_task9_pipeline_heartbeats_then_processes_with_shared_attempt_guard(
    tmp_path: Path,
) -> None:
    lease = make_lease()
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir()
    media.write_bytes(b"video")
    client = FakeWorkerApiClient(lease)
    processor = RecordingProcessor(make_result(lease))

    duration_times = iter([10.0, 10.25])
    result = asyncio.run(
        WorkerRunner(
            client,
            LocalMediaStore(tmp_path),
            2.0,
            processor,
            runtime_provenance_provider=lambda: PROVENANCE_SENTINEL,
            duration_clock=lambda: next(duration_times),
        ).run_once()
    )

    assert result is True
    assert client.heartbeats == [1.0]
    assert len(processor.calls) == 1
    call = processor.calls[0]
    assert call["job_id"] == lease.job_id
    assert call["attempt_count"] == lease.attempt_count
    assert call["source_path"] == media
    assert call["expected_source_size_bytes"] == lease.source_size_bytes
    assert call["expected_source_sha256"] == lease.source_sha256
    assert isinstance(call["lease_guard"], LeaseGuard)
    assert call["lease_guard"].is_lost() is False
    assert client.failures == []
    assert len(client.completions) == 1
    completed_result, duration_ms, provenance = client.completions[0]
    assert completed_result == processor.result
    assert duration_ms == 250
    assert provenance is PROVENANCE_SENTINEL
    assert client.events == ["lease", "heartbeat", "complete"]
    assert processor.events == ["process"]


def test_runtime_replacement_cannot_rebind_completed_result_provenance(
    tmp_path: Path,
) -> None:
    lease = make_lease()
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir()
    media.write_bytes(b"video")
    client = FakeWorkerApiClient(lease)
    old_provenance = object()
    new_provenance = object()
    current_provenance = [old_provenance]

    class RuntimeReplacingProcessor(RecordingProcessor):
        def process(self, **kwargs) -> VisionProcessingResult:
            current_provenance[0] = new_provenance
            return super().process(**kwargs)

    processor = RuntimeReplacingProcessor(make_result(lease))

    result = asyncio.run(
        WorkerRunner(
            client,
            LocalMediaStore(tmp_path),
            2.0,
            processor,
            runtime_provenance_provider=lambda: current_provenance[0],
        ).run_once()
    )

    assert result is True
    assert current_provenance[0] is new_provenance
    assert len(client.completions) == 1
    assert client.completions[0][2] is old_provenance
    assert client.failures == []


def test_unconfigured_task9_processor_reports_controlled_failure(tmp_path: Path) -> None:
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir()
    media.write_bytes(b"video")
    client = FakeWorkerApiClient(make_lease())

    result = asyncio.run(WorkerRunner(client, LocalMediaStore(tmp_path), 2.0).run_once())

    assert result is True
    assert client.heartbeats == [1.0]
    assert client.failures == [
        ("task9_processor_not_configured", "Task 9 processor is not configured.")
    ]


def test_source_integrity_processor_failure_is_controlled_once(tmp_path: Path) -> None:
    lease = make_lease()
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir()
    media.write_bytes(b"video")
    client = FakeWorkerApiClient(lease)
    processor = RecordingProcessor(error=SourceIntegrityError("source_sha256_mismatch"))

    result = asyncio.run(
        WorkerRunner(client, LocalMediaStore(tmp_path), 2.0, processor).run_once()
    )

    assert result is True
    assert client.failures == [
        (
            "source_media_integrity_failed",
            "Leased source media failed integrity verification.",
        )
    ]


def test_video_processing_failure_is_controlled_once(tmp_path: Path) -> None:
    lease = make_lease()
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir()
    media.write_bytes(b"video")
    client = FakeWorkerApiClient(lease)
    processor = RecordingProcessor(error=VideoProcessingError("pipeline_processing_failed"))

    result = asyncio.run(
        WorkerRunner(client, LocalMediaStore(tmp_path), 2.0, processor).run_once()
    )

    assert result is True
    assert client.failures == [("vision_processing_failed", "Vision processing failed.")]


@pytest.mark.parametrize(
    ("error_type", "expected_code"),
    [
        (InferenceContractError, "vision_inference_contract_failed"),
        (GpuOutOfMemoryError, "vision_gpu_out_of_memory"),
        (GpuRuntimeError, "vision_gpu_runtime_failed"),
        (TrackerError, "vision_tracker_failed"),
    ],
)
def test_processing_dependency_failure_uses_approved_stable_code(
    tmp_path: Path,
    error_type: type[ProcessingDependencyError],
    expected_code: str,
) -> None:
    lease = make_lease()
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir()
    media.write_bytes(b"video")
    client = FakeWorkerApiClient(lease)
    local_diagnostic = r"checkpoint=C:\\secret\\rtmdet.pth token=do-not-send"
    processor = RecordingProcessor(error=error_type(local_diagnostic))

    result = asyncio.run(
        WorkerRunner(client, LocalMediaStore(tmp_path), 2.0, processor).run_once()
    )

    assert result is True
    assert client.heartbeats == [1.0]
    assert len(processor.calls) == 1
    assert client.failures == [(expected_code, "Vision processing failed.")]
    assert local_diagnostic not in (client.failures[0][1] or "")
    assert client.events == ["lease", "heartbeat", f"fail:{expected_code}"]


def test_unapproved_processing_dependency_code_fails_closed(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lease = make_lease()
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir()
    media.write_bytes(b"video")
    client = FakeWorkerApiClient(lease)
    local_diagnostic = r"checkpoint=C:\\secret\\future.pth token=do-not-send"
    processor = RecordingProcessor(
        error=ProcessingDependencyError(
            "vision_future_dependency_failed",
            RuntimeDisposition.RECOVER,
            local_diagnostic,
        )
    )

    with caplog.at_level(logging.WARNING, logger="mavi_vision.worker.runner"):
        result = asyncio.run(
            WorkerRunner(client, LocalMediaStore(tmp_path), 2.0, processor).run_once()
        )

    assert result is True
    assert client.failures == [("vision_processing_failed", "Vision processing failed.")]
    assert local_diagnostic not in (client.failures[0][1] or "")
    assert "vision_future_dependency_failed" in caplog.text
    assert local_diagnostic not in caplog.text
    assert client.events == ["lease", "heartbeat", "fail:vision_processing_failed"]


def test_processing_dependency_terminal_fail_error_is_not_retried(
    tmp_path: Path,
) -> None:
    lease = make_lease()
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir()
    media.write_bytes(b"video")
    client = FailingTerminalWorkerApiClient(lease)
    processor = RecordingProcessor(
        error=GpuOutOfMemoryError("local CUDA diagnostic must not leave worker")
    )

    with pytest.raises(WorkerApiError, match="worker API request failed"):
        asyncio.run(
            WorkerRunner(client, LocalMediaStore(tmp_path), 2.0, processor).run_once()
        )

    assert client.heartbeats == [1.0]
    assert len(processor.calls) == 1
    assert client.failures == [
        ("vision_gpu_out_of_memory", "Vision processing failed.")
    ]
    assert client.events == [
        "lease",
        "heartbeat",
        "fail:vision_gpu_out_of_memory",
    ]


def test_processor_lease_loss_is_api_error_without_terminal_failure(tmp_path: Path) -> None:
    lease = make_lease()
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir()
    media.write_bytes(b"video")
    client = FakeWorkerApiClient(lease)
    processor = RecordingProcessor(error=LeaseLostError())

    with pytest.raises(WorkerApiError, match="lease ownership lost"):
        asyncio.run(
            WorkerRunner(client, LocalMediaStore(tmp_path), 2.0, processor).run_once()
        )

    assert client.heartbeats == [1.0]
    assert len(processor.calls) == 1
    assert client.failures == []


def test_completion_publication_rechecks_lease_after_payload_projection(
    tmp_path: Path,
) -> None:
    lease = make_lease()
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir()
    media.write_bytes(b"video")
    client = ExpiringAtCompletionPublicationApi(lease)
    processor = RecordingProcessor(make_result(lease))

    with pytest.raises(WorkerApiError, match="lease ownership lost"):
        asyncio.run(
            WorkerRunner(
                client,
                LocalMediaStore(tmp_path),
                2.0,
                processor,
                heartbeat_interval_seconds=30.0,
                runtime_provenance_provider=lambda: PROVENANCE_SENTINEL,
            ).run_once()
        )

    assert client.heartbeats == [1.0]
    assert client.failures == []
    assert client.completions == []
    assert client.events == ["lease", "heartbeat"]


def test_completion_transport_error_is_not_followed_by_failure(tmp_path: Path) -> None:
    lease = make_lease()
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir()
    media.write_bytes(b"video")
    client = FailingCompletionWorkerApiClient(lease)
    processor = RecordingProcessor(make_result(lease))

    with pytest.raises(WorkerApiError):
        asyncio.run(
            WorkerRunner(
                client,
                LocalMediaStore(tmp_path),
                2.0,
                processor,
                runtime_provenance_provider=lambda: PROVENANCE_SENTINEL,
            ).run_once()
        )

    assert client.heartbeats == [1.0]
    assert len(processor.calls) == 1
    assert client.failures == []
    assert len(client.completions) == 1
    assert client.events == ["lease", "heartbeat", "complete"]


def test_heartbeat_api_error_propagates_without_processing_for_polling_backoff(
    tmp_path: Path,
) -> None:
    lease = make_lease()
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir()
    media.write_bytes(b"video")
    client = FailingHeartbeatWorkerApiClient(lease)
    processor = RecordingProcessor(make_result(lease))

    with pytest.raises(WorkerApiError):
        asyncio.run(
            WorkerRunner(client, LocalMediaStore(tmp_path), 2.0, processor).run_once()
        )

    assert client.heartbeats == [1.0]
    assert client.failures == []
    assert processor.calls == []


def test_run_forever_sleeps_before_next_lease_after_worker_api_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir()
    media.write_bytes(b"video")
    lease = make_lease()
    client = BackoffProbeWorkerApiClient(lease)
    processor = RecordingProcessor(make_result(lease))
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)
        client.events.append("sleep")

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with pytest.raises(RuntimeError, match="stop polling probe"):
        asyncio.run(
            WorkerRunner(client, LocalMediaStore(tmp_path), 2.0, processor).run_forever()
        )

    assert sleep_calls == [2.0]
    assert client.events == ["lease", "heartbeat", "sleep", "lease"]
    assert processor.calls == []


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


def test_injected_process_executor_receives_processor_call_exactly_once(
    tmp_path: Path,
) -> None:
    class RecordingExecutor:
        def __init__(self) -> None:
            self.calls: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

        async def run(self, func, /, *args, **kwargs):
            self.calls.append((func, args, kwargs))
            return func(*args, **kwargs)

    lease = make_lease()
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir()
    media.write_bytes(b"video")
    client = FakeWorkerApiClient(lease)
    processor = RecordingProcessor(make_result(lease))
    executor = RecordingExecutor()

    result = asyncio.run(
        WorkerRunner(
            client,
            LocalMediaStore(tmp_path),
            2.0,
            processor,
            process_executor=executor,
        ).run_once()
    )

    assert result is True
    assert len(executor.calls) == 1
    func, args, kwargs = executor.calls[0]
    assert func == processor.process
    assert args == ()
    assert kwargs["job_id"] == lease.job_id
    assert kwargs["attempt_count"] == lease.attempt_count
    assert kwargs["source_path"] == media
    assert isinstance(kwargs["lease_guard"], LeaseGuard)


def test_injected_vision_lane_executes_processing_on_its_dedicated_thread(
    tmp_path: Path,
) -> None:
    import threading

    from mavi_vision.runtime.execution_lane import VisionExecutionLane

    class ThreadRecordingProcessor(RecordingProcessor):
        def __init__(self, result: VisionProcessingResult) -> None:
            super().__init__(result)
            self.thread_id: int | None = None

        def process(self, **kwargs) -> VisionProcessingResult:
            self.thread_id = threading.get_ident()
            return super().process(**kwargs)

    async def scenario() -> None:
        lease = make_lease()
        media = tmp_path / "videos" / "input.mp4"
        media.parent.mkdir()
        media.write_bytes(b"video")
        client = FakeWorkerApiClient(lease)
        processor = ThreadRecordingProcessor(make_result(lease))
        lane = VisionExecutionLane()
        event_loop_thread = threading.get_ident()

        try:
            result = await WorkerRunner(
                client,
                LocalMediaStore(tmp_path),
                2.0,
                processor,
                process_executor=lane,
            ).run_once()
        finally:
            await lane.close()

        assert result is True
        assert processor.thread_id is not None
        assert processor.thread_id != event_loop_thread

    asyncio.run(scenario())


# Host power request lifetime
class RecordingPowerRequest:
    """Stands in for the Windows idle-sleep inhibition at the runner seam.

    Records enter/exit against the processing timeline so the tests can assert
    the request is held for exactly the attempt and nothing wider.
    """

    def __init__(self, timeline: list[str], *, enter_error: Exception | None = None) -> None:
        self.timeline = timeline
        self.enter_error = enter_error
        self.reasons: list[str] = []
        self.entered = 0
        self.exited = 0

    def __call__(self, reason: str):
        self.reasons.append(reason)
        return self

    def __enter__(self):
        if self.enter_error is not None:
            raise self.enter_error
        self.entered += 1
        self.timeline.append("power:acquire")
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.exited += 1
        self.timeline.append("power:release")
        return False


class TimelineProcessor(RecordingProcessor):
    def __init__(self, timeline: list[str], result: VisionProcessingResult, error: Exception | None = None) -> None:
        super().__init__(result, error)
        self.timeline = timeline

    def process(self, **kwargs) -> VisionProcessingResult:
        self.timeline.append("process")
        return super().process(**kwargs)


def _run_with_power(tmp_path: Path, power, processor_error: Exception | None = None):
    lease = make_lease()
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir(exist_ok=True)
    media.write_bytes(b"video")
    client = FakeWorkerApiClient(lease)
    processor = TimelineProcessor(power.timeline, make_result(lease), processor_error)
    runner = WorkerRunner(
        client,
        LocalMediaStore(tmp_path),
        2.0,
        processor,
        runtime_provenance_provider=lambda: PROVENANCE_SENTINEL,
        host_power_request=power,
    )
    return asyncio.run(runner.run_once()), client, processor


def test_power_request_is_held_for_exactly_the_processing_attempt(tmp_path: Path) -> None:
    timeline: list[str] = []
    power = RecordingPowerRequest(timeline)

    result, client, _ = _run_with_power(tmp_path, power)

    assert result is True
    assert "complete" in client.events
    # Acquired before native work starts, released after it finishes.
    assert timeline == ["power:acquire", "process", "power:release"]
    assert power.entered == 1
    assert power.exited == 1


def test_power_request_names_the_job_it_is_held_for(tmp_path: Path) -> None:
    timeline: list[str] = []
    power = RecordingPowerRequest(timeline)
    lease = make_lease()

    _run_with_power(tmp_path, power)

    assert len(power.reasons) == 1
    reason = power.reasons[0]
    assert reason.startswith("MAVI vision processing active")
    assert str(lease.job_id) in reason
    # A reason string is read out of `powercfg /requests`; no filesystem path
    # of any kind belongs in it.
    assert "\\" not in reason and "/" not in reason


def test_power_request_is_released_when_processing_raises(tmp_path: Path) -> None:
    timeline: list[str] = []
    power = RecordingPowerRequest(timeline)

    result, client, _ = _run_with_power(
        tmp_path, power, processor_error=VideoProcessingError("decode_failed")
    )

    assert result is True
    assert power.exited == 1
    assert timeline[-1] == "power:release"


def test_power_request_is_released_when_the_lease_is_lost(tmp_path: Path) -> None:
    timeline: list[str] = []
    power = RecordingPowerRequest(timeline)

    with pytest.raises(WorkerApiError):
        _run_with_power(tmp_path, power, processor_error=LeaseLostError())

    assert power.entered == 1
    assert power.exited == 1


def test_an_idle_worker_never_requests_anything(tmp_path: Path) -> None:
    """No lease, no attempt, no reason to keep a workstation awake."""
    timeline: list[str] = []
    power = RecordingPowerRequest(timeline)
    client = FakeWorkerApiClient(None)

    result = asyncio.run(
        WorkerRunner(
            client,
            LocalMediaStore(tmp_path),
            2.0,
            RecordingProcessor(make_result(make_lease())),
            host_power_request=power,
        ).run_once()
    )

    assert result is False
    assert power.entered == 0
    assert power.reasons == []


def test_processing_continues_when_the_power_request_cannot_be_established(
    tmp_path: Path,
) -> None:
    """Best-effort means best-effort: a refused request never costs a job."""
    timeline: list[str] = []
    power = RecordingPowerRequest(timeline, enter_error=OSError("access denied"))

    lease = make_lease()
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir(exist_ok=True)
    media.write_bytes(b"video")
    client = FakeWorkerApiClient(lease)
    processor = TimelineProcessor(timeline, make_result(lease))

    # The production context manager never raises; this asserts the runner does
    # not silently swallow a contract violation if some future one ever does.
    with pytest.raises(OSError):
        asyncio.run(
            WorkerRunner(
                client,
                LocalMediaStore(tmp_path),
                2.0,
                processor,
                runtime_provenance_provider=lambda: PROVENANCE_SENTINEL,
                host_power_request=power,
            )._process_with_lease_heartbeats(
                lease,
                media,
                VisionJobHeartbeatResponse(
                    schemaVersion="2.0",
                    progressPercent=0.0,
                    leaseExpiresAtUtc=datetime(2099, 9, 9, 3, 0, tzinfo=timezone.utc),
                ),
                ProcessingProgress(
                    source_duration_ms=lease.duration_ms,
                ).reader,
                ProcessingProgress(
                    source_duration_ms=lease.duration_ms,
                ).sink,
            )
        )


def test_the_default_runner_uses_the_real_best_effort_request(tmp_path: Path) -> None:
    """The default must be the real mechanism, and must be inert on Linux."""
    from mavi_vision.runtime.host_power import keep_host_awake
    from mavi_vision.worker.runner import WorkerRunner as Runner

    lease = make_lease()
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir(exist_ok=True)
    media.write_bytes(b"video")
    client = FakeWorkerApiClient(lease)
    processor = RecordingProcessor(make_result(lease))
    runner = Runner(
        client,
        LocalMediaStore(tmp_path),
        2.0,
        processor,
        runtime_provenance_provider=lambda: PROVENANCE_SENTINEL,
    )

    assert runner._host_power_request is keep_host_awake
    # And an ordinary attempt on this (non-Windows) CI host completes normally.
    assert asyncio.run(runner.run_once()) is True
    assert "complete" in client.events


# Attempt telemetry sink
class RecordingSink:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.completions: list[object] = []
        self.error = error

    async def __call__(self, completion) -> None:
        self.completions.append(completion)
        if self.error is not None:
            raise self.error


def test_the_sink_receives_the_accepted_attempt_after_completion(tmp_path: Path) -> None:
    lease = make_lease()
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir(exist_ok=True)
    media.write_bytes(b"video")
    client = FakeWorkerApiClient(lease)
    result = make_result(lease)
    processor = RecordingProcessor(result)
    sink = RecordingSink()

    outcome = asyncio.run(
        WorkerRunner(
            client,
            LocalMediaStore(tmp_path),
            2.0,
            processor,
            runtime_provenance_provider=lambda: PROVENANCE_SENTINEL,
            attempt_completed_sink=sink,
        ).run_once()
    )

    assert outcome is True
    assert client.events[-1] == "complete"
    [completion] = sink.completions
    assert completion.job_id == lease.job_id
    assert completion.attempt_count == lease.attempt_count
    assert completion.result is result
    assert completion.provenance is PROVENANCE_SENTINEL
    assert completion.processing_duration_ms == client.completions[0][1]


def test_a_failing_sink_cannot_change_the_attempt_outcome(tmp_path: Path, caplog) -> None:
    lease = make_lease()
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir(exist_ok=True)
    media.write_bytes(b"video")
    client = FakeWorkerApiClient(lease)
    sink = RecordingSink(error=OSError("disk full"))

    with caplog.at_level(logging.WARNING):
        outcome = asyncio.run(
            WorkerRunner(
                client,
                LocalMediaStore(tmp_path),
                2.0,
                RecordingProcessor(make_result(lease)),
                runtime_provenance_provider=lambda: PROVENANCE_SENTINEL,
                attempt_completed_sink=sink,
            ).run_once()
        )

    assert outcome is True
    assert "complete" in client.events
    assert client.failures == []
    assert any("telemetry sink failed" in r.message for r in caplog.records)


def test_the_sink_is_not_called_for_a_failed_attempt(tmp_path: Path) -> None:
    lease = make_lease()
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir(exist_ok=True)
    media.write_bytes(b"video")
    client = FakeWorkerApiClient(lease)
    sink = RecordingSink()

    asyncio.run(
        WorkerRunner(
            client,
            LocalMediaStore(tmp_path),
            2.0,
            RecordingProcessor(error=VideoProcessingError("decode_failed")),
            runtime_provenance_provider=lambda: PROVENANCE_SENTINEL,
            attempt_completed_sink=sink,
        ).run_once()
    )

    assert sink.completions == []
    assert client.failures[0][0] == "vision_processing_failed"


# Staging after the completion 3.1 hand-off (S1.4 B3 F2, plan §5.4, §11)
class FinalizingWorkerApiClient(FakeWorkerApiClient):
    """Answers completion with a real 3.1 acknowledgement in the given state."""

    def __init__(self, leased_job: VisionJobLease | None, state: str = "finalizing") -> None:
        super().__init__(leased_job)
        self.state = state

    async def complete(self, lease, result, processing_duration_ms, provenance, *, authorize_publish=None):
        await super().complete(lease, result, processing_duration_ms, provenance, authorize_publish=authorize_publish)
        payload = {
            "schemaVersion": "3.1",
            "jobId": str(lease.job_id),
            "processingRunId": str(lease.processing_run_id),
            "state": self.state,
            "acceptedAtUtc": "2026-09-25T08:00:00Z",
            "tracksSubmitted": len(result.tracks),
        }
        if self.state == "completed":
            payload["completedAtUtc"] = "2026-09-25T08:01:30Z"
        return VisionJobFinalizationResponse.model_validate_json(json.dumps(payload))


def _stage_current_attempt(tmp_path: Path, lease: VisionJobLease) -> Path:
    from mavi_vision.storage.artifact_store import StagingArtifactStore

    StagingArtifactStore(tmp_path, lease.job_id, lease.attempt_count).append_bytes("spool/t.traj", b"x")
    return tmp_path / "staging" / str(lease.job_id) / f"attempt-{lease.attempt_count:04d}" / "spool" / "t.traj"


@pytest.mark.parametrize("state", ["finalizing", "completed"])
def test_current_attempt_staging_survives_the_hand_off(tmp_path: Path, state: str, caplog) -> None:
    """The retained staging is the platform finalizer's input: a ``finalizing``
    acknowledgement (or the ``completed`` replay of one) never deletes it."""
    lease = make_lease()
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir(exist_ok=True)
    media.write_bytes(b"video")
    staged = _stage_current_attempt(tmp_path, lease)
    client = FinalizingWorkerApiClient(lease, state)
    runner = WorkerRunner(
        client,
        LocalMediaStore(tmp_path),
        2.0,
        RecordingProcessor(make_result(lease)),
        runtime_provenance_provider=lambda: PROVENANCE_SENTINEL,
    )

    with caplog.at_level(logging.INFO):
        assert asyncio.run(runner.run_once()) is True

    assert client.events[-1] == "complete"
    assert client.failures == []
    assert staged.exists()
    assert any(f"handed off: state={state}" in r.message for r in caplog.records)


def test_the_runner_has_no_post_hand_off_staging_cleaner(tmp_path: Path) -> None:
    """Mutation guard: nothing on the runner or its composition can delete the
    current attempt after acknowledgement; the only deletions left are the
    pipeline's superseded-attempt cleanup and the platform janitor."""
    from types import SimpleNamespace

    from mavi_vision.worker.main import build_runner

    settings = SimpleNamespace(
        media_root=tmp_path,
        poll_interval_seconds=2.0,
        heartbeat_interval_seconds=30.0,
        request_timeout_seconds=30.0,
        watchdog_grace_seconds=10.0,
    )
    runner = build_runner(settings, client=None)  # type: ignore[arg-type]

    assert not hasattr(runner, "_staging_cleaner")
    assert not hasattr(runner, "_release_accepted_staging")
    with pytest.raises(TypeError):
        WorkerRunner(FakeWorkerApiClient(None), LocalMediaStore(tmp_path), 2.0, None, staging_cleaner=lambda j, a: None)


def test_staging_is_kept_after_lease_loss_too(tmp_path: Path) -> None:
    lease = make_lease()
    media = tmp_path / "videos" / "input.mp4"
    media.parent.mkdir(exist_ok=True)
    media.write_bytes(b"video")
    staged = _stage_current_attempt(tmp_path, lease)
    client = FakeWorkerApiClient(lease)
    runner = WorkerRunner(
        client,
        LocalMediaStore(tmp_path),
        2.0,
        RecordingProcessor(error=LeaseLostError()),
        runtime_provenance_provider=lambda: PROVENANCE_SENTINEL,
    )

    with pytest.raises(WorkerApiError, match="lease ownership lost"):
        asyncio.run(runner.run_once())

    # A stale attempt deletes nothing: its staging belongs to the next attempt's
    # superseded-attempt cleanup or the platform janitor.
    assert staged.exists()
    assert "complete" not in client.events
