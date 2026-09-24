import asyncio
import logging
import os
import threading
import time
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager, ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Final, NoReturn, Protocol
from uuid import UUID

from mavi_vision.common.analytical import VisionProcessingResult
from mavi_vision.common.control_plane import VisionJobHeartbeatResponse, VisionJobLease
from mavi_vision.common.lease import LeaseGuard, LeaseLostError
from mavi_vision.pipeline.process_video import VideoProcessingError
from mavi_vision.runtime.errors import ProcessingDependencyError
from mavi_vision.runtime.execution_lane import ProcessExecutor
from mavi_vision.runtime.host_power import keep_host_awake
from mavi_vision.runtime.progress import (
    RUNNING_MAX_PERCENT,
    ProcessingProgress,
    ProcessingProgressReader,
    ProcessingProgressSink,
)
from mavi_vision.runtime.provenance import RuntimeProvenance
from mavi_vision.runtime.watchdog import (
    RuntimeWatchdogSnapshot,
    RuntimeWatchdogSnapshotProvider,
)
from mavi_vision.storage.integrity import SourceIntegrityError
from mavi_vision.storage.local_media_store import MediaStoreError
from mavi_vision.worker.attempt_telemetry import AttemptCompletion
from mavi_vision.worker.client import (
    CompletionPayloadInvalid,
    PlatformContractUnsupported,
    WorkerApiError,
)
from mavi_vision.worker.watchdog_incident import (
    WATCHDOG_FAILURE_CODE,
    WATCHDOG_OBSERVATION_FAILURE_CODE,
    WatchdogIncidentRecorder,
    WatchdogIncidentSnapshot,
)


_LOGGER = logging.getLogger(__name__)

_APPROVED_PROCESSING_DEPENDENCY_CODES: Final[frozenset[str]] = frozenset(
    {
        "vision_inference_contract_failed",
        "vision_gpu_out_of_memory",
        "vision_gpu_runtime_failed",
        "vision_tracker_failed",
    }
)
_GENERIC_PROCESSING_FAILURE_CODE: Final = "vision_processing_failed"
_PROCESSING_FAILURE_MESSAGE: Final = "Vision processing failed."
_FATAL_SERVICE_RESTART_CODE: Final = 70


@dataclass(frozen=True, slots=True)
class _WatchdogTrigger:
    failure_code: str
    runtime_snapshot: RuntimeWatchdogSnapshot | None


class _WatchdogExpiredDuringHeartbeat(RuntimeError):
    def __init__(self, trigger: _WatchdogTrigger) -> None:
        super().__init__(trigger.failure_code)
        self.trigger = trigger


# Worker collaborators
class WorkerApi(Protocol):
    async def get_contract_capabilities(self) -> object: ...

    async def lease(self) -> VisionJobLease | None: ...

    async def heartbeat(
        self, lease: VisionJobLease, progress_percent: float
    ) -> VisionJobHeartbeatResponse: ...

    async def fail(
        self,
        lease: VisionJobLease,
        failure_code: str,
        failure_message: str | None = None,
    ) -> None: ...

    async def complete(
        self,
        lease: VisionJobLease,
        result: VisionProcessingResult,
        processing_duration_ms: int,
        provenance: RuntimeProvenance,
        *,
        authorize_publish: Callable[[], None] | None = None,
    ) -> object: ...


class MediaStore(Protocol):
    def resolve_file(self, storage_key: str) -> Path: ...


class VisionProcessor(Protocol):
    def process(
        self,
        *,
        job_id: UUID,
        attempt_count: int,
        source_path: Path,
        expected_source_size_bytes: int,
        expected_source_sha256: str,
        lease_guard: LeaseGuard,
        progress_sink: ProcessingProgressSink | None = None,
    ) -> VisionProcessingResult: ...


class _AsyncioThreadProcessExecutor:
    """Backward-compatible default executor for unsupervised/dev callers."""

    async def run(self, func, /, *args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)


# Worker lifecycle orchestration
class WorkerRunner:
    def __init__(
        self,
        api_client: WorkerApi,
        media_store: MediaStore,
        poll_interval_seconds: float,
        processor: VisionProcessor | None = None,
        heartbeat_interval_seconds: float = 30.0,
        heartbeat_request_timeout_seconds: float = 30.0,
        process_executor: ProcessExecutor | None = None,
        watchdog_snapshot_provider: RuntimeWatchdogSnapshotProvider | None = None,
        watchdog_expired: Callable[[], bool] | None = None,
        watchdog_expiry_sink: Callable[[], None] | None = None,
        watchdog_incident_recorder: WatchdogIncidentRecorder | None = None,
        watchdog_incident_write_timeout_seconds: float = 1.0,
        watchdog_grace_seconds: float = 10.0,
        watchdog_poll_seconds: float = 1.0,
        fatal_terminator: Callable[[int], NoReturn] = os._exit,
        monotonic_clock: Callable[[], float] = time.monotonic,
        runtime_provenance_provider: Callable[[], RuntimeProvenance | None] | None = None,
        duration_clock: Callable[[], float] = time.perf_counter,
        host_power_request: Callable[[str], AbstractContextManager[object]] = (
            keep_host_awake
        ),
        attempt_completed_sink: (
            Callable[[AttemptCompletion], Awaitable[None]] | None
        ) = None,
        staging_cleaner: Callable[[UUID, int], None] | None = None,
    ) -> None:
        if heartbeat_interval_seconds <= 0:
            raise ValueError("heartbeat_interval_seconds must be positive")
        if heartbeat_request_timeout_seconds <= 0:
            raise ValueError("heartbeat_request_timeout_seconds must be positive")
        if watchdog_incident_write_timeout_seconds <= 0:
            raise ValueError(
                "watchdog_incident_write_timeout_seconds must be positive"
            )
        if watchdog_grace_seconds <= 0:
            raise ValueError("watchdog_grace_seconds must be positive")
        if watchdog_poll_seconds <= 0 or watchdog_poll_seconds > 1.0:
            raise ValueError("watchdog_poll_seconds must be in (0, 1]")
        self._api_client = api_client
        self._media_store = media_store
        self._poll_interval_seconds = poll_interval_seconds
        self._processor = processor
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._heartbeat_request_timeout_seconds = heartbeat_request_timeout_seconds
        self._process_executor = process_executor or _AsyncioThreadProcessExecutor()
        self._watchdog_snapshot_provider = watchdog_snapshot_provider
        self._watchdog_expired = watchdog_expired
        self._watchdog_expiry_sink = watchdog_expiry_sink
        self._watchdog_incident_recorder = watchdog_incident_recorder
        self._watchdog_incident_write_timeout_seconds = (
            watchdog_incident_write_timeout_seconds
        )
        self._watchdog_grace_seconds = watchdog_grace_seconds
        self._watchdog_poll_seconds = watchdog_poll_seconds
        self._fatal_terminator = fatal_terminator
        self._monotonic_clock = monotonic_clock
        self._runtime_provenance_provider = runtime_provenance_provider
        self._duration_clock = duration_clock
        self._host_power_request = host_power_request
        self._attempt_completed_sink = attempt_completed_sink
        self._staging_cleaner = staging_cleaner
        self._fatal_termination_active = False
        self._platform_contract_confirmed = False
        self._platform_contract_reported = False

    @property
    def fatal_termination_active(self) -> bool:
        """True once watchdog containment requires process-level termination."""
        return self._fatal_termination_active

    @property
    def platform_contract_confirmed(self) -> bool:
        """True while the platform is known to accept completion 3.0."""
        return self._platform_contract_confirmed

    async def run_once(self) -> bool:
        try:
            return await self._run_once()
        except WorkerApiError:
            # Any control-plane failure (transport, lease loss, a rejected
            # contract) may mean a different platform answers next time; the
            # capability is probed again before the next lease.
            self._platform_contract_confirmed = False
            raise

    async def _confirm_platform_contract(self) -> bool:
        """Plan §23: never lease before the platform lists completion 3.0.

        Probed before **every** lease (one small GET per poll), so a platform
        swapped for an older one between leases is noticed before a job is
        leased against it, not after the video has been processed. An
        incompatible or malformed answer keeps the worker not-ready (no lease,
        no v2 fallback); a transport failure propagates as the ordinary polling
        back-off.
        """
        try:
            await self._api_client.get_contract_capabilities()
        except PlatformContractUnsupported:
            self._platform_contract_confirmed = False
            if not self._platform_contract_reported:
                _LOGGER.error(
                    "Vision worker not ready: vision_platform_contract_unsupported "
                    "(the platform does not accept completion 3.0); no job is leased"
                )
                self._platform_contract_reported = True
            return False
        self._platform_contract_confirmed = True
        self._platform_contract_reported = False
        return True

    async def _run_once(self) -> bool:
        if not await self._confirm_platform_contract():
            return False
        lease = await self._api_client.lease()
        if lease is None:
            return False

        progress = ProcessingProgress(
            source_duration_ms=lease.duration_ms,
            monotonic_clock=self._monotonic_clock,
        )
        progress_reader = progress.reader
        progress_sink = progress.sink

        try:
            source_path = self._media_store.resolve_file(lease.source_storage_key)
            heartbeat = await self._api_client.heartbeat(
                lease,
                self._running_progress_percent(progress_reader),
            )
            self._log_progress(lease, progress_reader)
        except MediaStoreError:
            await self._best_effort_fail(
                lease,
                "source_media_unavailable",
                "Leased source media is unavailable.",
            )
            return True
        except WorkerApiError:
            raise
        except Exception:
            await self._best_effort_fail(
                lease,
                "worker_unhandled_error",
                "The worker encountered an unexpected error.",
            )
            return True

        if self._processor is None:
            await self._api_client.fail(
                lease,
                "task9_processor_not_configured",
                "Task 9 processor is not configured.",
            )
            return True

        try:
            provenance_snapshot = (
                self._runtime_provenance_provider()
                if self._runtime_provenance_provider is not None
                else None
            )
            processing_started = self._duration_clock()
            result, completion_guard = await self._process_with_lease_heartbeats(
                lease,
                source_path,
                heartbeat,
                progress_reader,
                progress_sink,
            )
        except LeaseLostError as exc:
            # Ownership loss is not a processing failure. A stale attempt must not
            # emit any terminal lifecycle request after its guard rejects work.
            raise WorkerApiError("lease ownership lost") from exc
        except SourceIntegrityError:
            _LOGGER.exception(
                "Vision job %s attempt %s failed source-integrity verification",
                lease.job_id,
                lease.attempt_count,
            )
            await self._best_effort_fail(
                lease,
                "source_media_integrity_failed",
                "Leased source media failed integrity verification.",
            )
            return True
        except ProcessingDependencyError as exc:
            # ProcessingDependencyError detail is local diagnostic data and may
            # contain paths, tokens, model locations, or other sensitive runtime
            # context. Keep the wire/log contract to the reviewed failure code only.
            # Do not use logger.exception here: traceback rendering includes the
            # exception message and would re-expose the diagnostic.
            _LOGGER.error(
                "Vision job %s attempt %s failed in processing dependency: code=%s",
                lease.job_id,
                lease.attempt_count,
                exc.failure_code,
            )
            # The runtime-health sink has already observed this model-neutral error.
            # This layer owns only the leased-job terminal mapping. Never trust a
            # future/custom typed code as a wire contract without explicit review.
            failure_code = exc.failure_code
            if failure_code not in _APPROVED_PROCESSING_DEPENDENCY_CODES:
                _LOGGER.warning(
                    "Unallowlisted processing dependency failure code: %s",
                    failure_code,
                )
                failure_code = _GENERIC_PROCESSING_FAILURE_CODE
            await self._best_effort_fail(
                lease,
                failure_code,
                _PROCESSING_FAILURE_MESSAGE,
            )
            return True
        except VideoProcessingError as exc:
            _LOGGER.exception(
                "Vision job %s attempt %s failed in video pipeline: internal_code=%s",
                lease.job_id,
                lease.attempt_count,
                exc.code,
            )
            # Preserve compatibility with processors that still surface the stable
            # Task-9 lease_lost processing code while the structural LeaseGuard path
            # uses LeaseLostError directly.
            if exc.code == "lease_lost":
                raise WorkerApiError("lease ownership lost") from exc
            await self._best_effort_fail(
                lease,
                "vision_processing_failed",
                "Vision processing failed.",
            )
            return True
        except WorkerApiError:
            raise
        except Exception:
            _LOGGER.exception(
                "Vision job %s attempt %s failed with an unhandled worker error",
                lease.job_id,
                lease.attempt_count,
            )
            # Test terminators may raise a sentinel instead of terminating the
            # process. Never turn that sentinel into a stale leased-job /fail.
            if self._fatal_termination_active:
                raise
            await self._best_effort_fail(
                lease,
                "worker_unhandled_error",
                "The worker encountered an unexpected error.",
            )
            return True

        try:
            completion_guard.check_owned()
            if provenance_snapshot is None:
                await self._best_effort_fail(
                    lease,
                    "vision_runtime_provenance_unavailable",
                    "Vision runtime provenance is unavailable.",
                )
                return True

            elapsed_seconds = max(0.0, self._duration_clock() - processing_started)
            processing_duration_ms = int(round(elapsed_seconds * 1000.0))
            await self._api_client.complete(
                lease,
                result,
                processing_duration_ms,
                provenance_snapshot,
                authorize_publish=completion_guard.check_owned,
            )
        except PlatformContractUnsupported:
            # The platform rejected completion 3.0 after confirming it (for
            # example a downgrade). Terminal for this attempt: no retry of the
            # completion and no v2 fallback. The staging stays for the next
            # attempt's cleanup or the platform janitor.
            self._platform_contract_confirmed = False
            _LOGGER.error(
                "Vision job %s attempt %s: platform rejected completion 3.0",
                lease.job_id,
                lease.attempt_count,
            )
            await self._best_effort_fail(
                lease,
                "vision_worker_contract_unsupported",
                "The platform does not accept this worker's completion contract.",
            )
            return True
        except CompletionPayloadInvalid:
            # Nothing was sent: the worker's own result does not form a valid
            # 3.0 body (for example more Tracks than the contract carries).
            # Retrying would rebuild the same body, so the attempt fails.
            _LOGGER.error(
                "Vision job %s attempt %s produced an invalid completion body",
                lease.job_id,
                lease.attempt_count,
            )
            await self._best_effort_fail(
                lease,
                "vision_result_invalid",
                "The vision result could not be expressed as a valid completion.",
            )
            return True
        except LeaseLostError as exc:
            raise WorkerApiError("lease ownership lost") from exc

        await self._release_accepted_staging(lease)

        # The attempt is authoritative from here. Telemetry describes it and
        # cannot change it, so a failing sink is logged and nothing more.
        if self._attempt_completed_sink is not None:
            try:
                await self._attempt_completed_sink(
                    AttemptCompletion(
                        job_id=lease.job_id,
                        attempt_count=lease.attempt_count,
                        result=result,
                        processing_duration_ms=processing_duration_ms,
                        provenance=provenance_snapshot,
                    )
                )
            except Exception:
                _LOGGER.warning(
                    "Attempt telemetry sink failed for job %s attempt %s",
                    lease.job_id,
                    lease.attempt_count,
                )
        return True

    async def _release_accepted_staging(self, lease: VisionJobLease) -> None:
        """Remove this attempt's staging once the platform has accepted it.

        The platform seals every accepted artefact into its own evidence root
        before it acknowledges completion, so nothing references this staging
        any more. This is only the fast path: the platform's staging janitor
        (ADR-006 section 6) reclaims it anyway if the worker dies first, so a
        failure here is logged and never changes the accepted attempt.
        """
        if self._staging_cleaner is None:
            return
        try:
            await asyncio.to_thread(
                self._staging_cleaner,
                lease.job_id,
                lease.attempt_count,
            )
        except Exception:
            _LOGGER.warning(
                "Staging cleanup after accepted completion failed for job %s "
                "attempt %s; the platform staging janitor will reclaim it",
                lease.job_id,
                lease.attempt_count,
            )

    async def _process_with_lease_heartbeats(
        self,
        lease: VisionJobLease,
        source_path: Path,
        heartbeat: VisionJobHeartbeatResponse,
        progress_reader: ProcessingProgressReader,
        progress_sink: ProcessingProgressSink,
    ) -> tuple[VisionProcessingResult, LeaseGuard]:
        if self._processor is None:
            raise RuntimeError("processor_missing")

        current_deadline = heartbeat.lease_expires_at_utc
        lease_guard = LeaseGuard(current_deadline)
        process_task: asyncio.Task[VisionProcessingResult] | None = None
        # Scoped to exactly this attempt's native work, so an idle worker never
        # keeps a workstation awake. Best-effort and Windows-only: see
        # mavi_vision.runtime.host_power for what it does not promise.
        power_scope = ExitStack()

        try:
            lease_guard.check_owned()
            power_scope.enter_context(
                self._host_power_request(
                    "MAVI vision processing active "
                    f"(job {lease.job_id} attempt {lease.attempt_count})"
                )
            )
            process_task = asyncio.create_task(
                self._process_executor.run(
                    self._processor.process,
                    job_id=lease.job_id,
                    attempt_count=lease.attempt_count,
                    source_path=source_path,
                    expected_source_size_bytes=lease.source_size_bytes,
                    expected_source_sha256=lease.source_sha256,
                    lease_guard=lease_guard,
                    progress_sink=progress_sink,
                )
            )

            # Polling the watchdog must not reset heartbeat timing. Keep an
            # absolute monotonic scheduling deadline independent of poll cadence.
            next_heartbeat_due = (
                self._monotonic_clock()
                + self._heartbeat_wait_seconds(heartbeat)
            )

            while True:
                now_monotonic = self._monotonic_clock()
                heartbeat_wait = max(0.0, next_heartbeat_due - now_monotonic)
                wait_seconds = heartbeat_wait
                if self._watchdog_enabled():
                    wait_seconds = min(wait_seconds, self._watchdog_poll_seconds)

                done, _ = await asyncio.wait(
                    {process_task},
                    timeout=wait_seconds,
                )
                if process_task in done:
                    # Lease loss outranks both a processing result and processing
                    # error if the event loop resumes after authority expired.
                    lease_guard.check_owned()
                    try:
                        result = process_task.result()
                    except LeaseLostError:
                        raise
                    except BaseException:
                        lease_guard.check_owned()
                        raise
                    lease_guard.check_owned()
                    return result, lease_guard

                watchdog_trigger = self._watchdog_trigger()
                if watchdog_trigger is not None:
                    await self._handle_watchdog_expiry(
                        process_task,
                        lease_guard,
                        lease,
                        progress_reader,
                        watchdog_trigger,
                    )

                now_monotonic = self._monotonic_clock()
                if now_monotonic >= next_heartbeat_due:
                    try:
                        current_heartbeat = (
                            await self._heartbeat_before_deadline_while_processing(
                                lease,
                                current_deadline,
                                process_task,
                                progress_reader,
                            )
                        )
                    except _WatchdogExpiredDuringHeartbeat as exc:
                        await self._handle_watchdog_expiry(
                            process_task,
                            lease_guard,
                            lease,
                            progress_reader,
                            exc.trigger,
                        )
                        raise AssertionError(
                            "watchdog containment unexpectedly returned"
                        )

                    if current_heartbeat is None:
                        # Processing completed while renewal was in flight. The
                        # request has been cancelled; loop back so lease precedence
                        # is applied to the processing result/error immediately.
                        continue

                    current_deadline = current_heartbeat.lease_expires_at_utc
                    lease_guard.update_deadline(current_deadline)
                    self._log_progress(lease, progress_reader)
                    next_heartbeat_due = (
                        self._monotonic_clock()
                        + self._heartbeat_wait_seconds(current_heartbeat)
                    )
        except BaseException:
            lease_guard.mark_lost()
            if (
                process_task is not None
                and not process_task.done()
                and not self._fatal_termination_active
            ):
                await self._await_unwound_after_loss(
                    process_task,
                    lease_guard,
                    lease,
                    progress_reader,
                )
            raise
        finally:
            # Released first because it cannot raise and must not be able to
            # displace the ownership containment that follows. The watchdog's
            # os._exit path runs no finally at all; Windows reclaims a dead
            # process's power requests, which is what covers it.
            power_scope.close()
            if process_task is not None and not process_task.done():
                lease_guard.mark_lost()

    async def _handle_watchdog_expiry(
        self,
        process_task: asyncio.Task[VisionProcessingResult],
        lease_guard: LeaseGuard,
        lease: VisionJobLease,
        progress_reader: ProcessingProgressReader,
        watchdog_trigger: _WatchdogTrigger,
    ) -> None:
        lease_guard.mark_lost()
        self._record_watchdog_incident(
            lease,
            progress_reader,
            watchdog_trigger,
        )
        self._report_watchdog_expiry()
        still_stuck = await self._watchdog_grace_wait(
            process_task,
            lease_guard,
        )
        if still_stuck:
            # Set persistent fatal state before invoking a terminator. Production
            # os._exit does not return; injected tests may raise a sentinel.
            self._fatal_termination_active = True
            self._fatal_terminator(_FATAL_SERVICE_RESTART_CODE)
            raise RuntimeError("watchdog_fatal_terminator_returned")

    async def _await_unwound_after_loss(
        self,
        process_task: asyncio.Task[VisionProcessingResult],
        lease_guard: LeaseGuard,
        lease: VisionJobLease,
        progress_reader: ProcessingProgressReader,
    ) -> None:
        """Keep watchdog containment active while ordinary cleanup unwinds."""
        if not self._watchdog_enabled():
            try:
                await process_task
            except BaseException:
                pass
            return

        while not process_task.done():
            watchdog_trigger = self._watchdog_trigger()
            if watchdog_trigger is not None:
                self._record_watchdog_incident(
                    lease,
                    progress_reader,
                    watchdog_trigger,
                )
                self._report_watchdog_expiry()
                still_stuck = await self._watchdog_grace_wait(
                    process_task,
                    lease_guard,
                )
                if still_stuck:
                    self._fatal_termination_active = True
                    self._fatal_terminator(_FATAL_SERVICE_RESTART_CODE)
                    raise RuntimeError("watchdog_fatal_terminator_returned")
            await asyncio.wait(
                {process_task},
                timeout=self._watchdog_poll_seconds,
            )

        try:
            process_task.result()
        except BaseException:
            pass

    async def _watchdog_grace_wait(
        self,
        process_task: asyncio.Task[VisionProcessingResult],
        lease_guard: LeaseGuard,
    ) -> bool:
        lease_guard.mark_lost()
        done, _ = await asyncio.wait(
            {process_task},
            timeout=self._watchdog_grace_seconds,
        )
        if process_task in done:
            try:
                process_task.result()
            except BaseException:
                pass
            # Once the watchdog has expired the attempt result is no longer
            # authoritative, even if native work happens to unwind in grace.
            raise LeaseLostError()

        return True

    def _watchdog_enabled(self) -> bool:
        return (
            self._watchdog_snapshot_provider is not None
            or self._watchdog_expired is not None
        )

    def _watchdog_trigger(self) -> _WatchdogTrigger | None:
        provider = self._watchdog_snapshot_provider
        if provider is not None:
            try:
                snapshot = provider()
            except Exception:
                # Runtime/provider exceptions may contain paths or other private
                # diagnostics. Preserve fail-closed containment without rendering
                # the exception or traceback into operator logs.
                _LOGGER.error(
                    "Watchdog snapshot provider failed; containing as unhealthy"
                )
                return _WatchdogTrigger(
                    WATCHDOG_OBSERVATION_FAILURE_CODE,
                    None,
                )
            if snapshot.expired:
                return _WatchdogTrigger(WATCHDOG_FAILURE_CODE, snapshot)
            return None

        callback = self._watchdog_expired
        if callback is None:
            return None
        try:
            if bool(callback()):
                return _WatchdogTrigger(WATCHDOG_FAILURE_CODE, None)
            return None
        except Exception:
            _LOGGER.error(
                "Watchdog callback failed; containing as unhealthy"
            )
            return _WatchdogTrigger(
                WATCHDOG_OBSERVATION_FAILURE_CODE,
                None,
            )

    def _record_watchdog_incident(
        self,
        lease: VisionJobLease,
        progress_reader: ProcessingProgressReader,
        watchdog_trigger: _WatchdogTrigger,
    ) -> None:
        recorder = self._watchdog_incident_recorder
        if recorder is None:
            return

        incident = WatchdogIncidentSnapshot(
            worker_id=str(lease.worker_id),
            job_id=lease.job_id,
            attempt_count=lease.attempt_count,
            failure_code=watchdog_trigger.failure_code,
            progress=progress_reader.snapshot(),
            runtime=watchdog_trigger.runtime_snapshot,
        )
        completed = threading.Event()
        failed = threading.Event()

        def persist() -> None:
            try:
                recorder.record(incident)
            except BaseException:
                # Never retain or render the exception payload: filesystem errors
                # can contain private local paths and other diagnostics.
                failed.set()
            finally:
                completed.set()

        # Fatal containment must never wait indefinitely on a degraded filesystem.
        # A daemon thread permits bounded waiting while still allowing os._exit(70)
        # (or normal service restart after grace) to terminate the process cleanly.
        writer = threading.Thread(
            target=persist,
            name="mavi-watchdog-incident-writer",
            daemon=True,
        )
        writer.start()
        if not completed.wait(self._watchdog_incident_write_timeout_seconds):
            _LOGGER.error("Watchdog incident persistence timed out")
            return
        if failed.is_set():
            _LOGGER.error("Watchdog incident persistence failed")

    def _report_watchdog_expiry(self) -> None:
        sink = self._watchdog_expiry_sink
        if sink is None:
            return
        try:
            sink()
        except Exception:
            _LOGGER.error("Watchdog expiry sink failed")

    async def _heartbeat_before_deadline_while_processing(
        self,
        lease: VisionJobLease,
        lease_deadline_utc: datetime,
        process_task: asyncio.Task[VisionProcessingResult],
        progress_reader: ProcessingProgressReader,
    ) -> VisionJobHeartbeatResponse | None:
        if not self._watchdog_enabled():
            return await self._heartbeat_before_deadline(
                lease,
                lease_deadline_utc,
                progress_reader,
            )

        remaining = (
            lease_deadline_utc - datetime.now(timezone.utc)
        ).total_seconds()
        if remaining <= 0:
            raise WorkerApiError("heartbeat deadline exceeded")
        if process_task.done():
            return None
        watchdog_trigger = self._watchdog_trigger()
        if watchdog_trigger is not None:
            raise _WatchdogExpiredDuringHeartbeat(watchdog_trigger)

        heartbeat_task = asyncio.create_task(
            self._api_client.heartbeat(
                lease,
                self._running_progress_percent(progress_reader),
            ),
            name="mavi-worker-heartbeat",
        )
        try:
            while True:
                remaining = (
                    lease_deadline_utc - datetime.now(timezone.utc)
                ).total_seconds()
                if remaining <= 0:
                    raise WorkerApiError("heartbeat deadline exceeded")

                done, _ = await asyncio.wait(
                    {heartbeat_task, process_task},
                    timeout=min(self._watchdog_poll_seconds, remaining),
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if heartbeat_task in done:
                    # A completed renewal is server-authoritative even when
                    # processing completes in the same event-loop turn. Surface
                    # lease loss/errors or accept its returned deadline before
                    # the processing result can be interpreted.
                    heartbeat = heartbeat_task.result()
                    if datetime.now(timezone.utc) >= lease_deadline_utc:
                        raise WorkerApiError("heartbeat deadline exceeded")
                    return heartbeat

                if process_task in done:
                    return None

                watchdog_trigger = self._watchdog_trigger()
                if watchdog_trigger is not None:
                    raise _WatchdogExpiredDuringHeartbeat(watchdog_trigger)
        finally:
            if not heartbeat_task.done():
                # Heartbeat/network work is asyncio-owned and safe to cancel.
                # Do not await a cancellation-resistant transport on the fatal path.
                heartbeat_task.cancel()
                heartbeat_task.add_done_callback(_consume_background_task_result)

    async def _heartbeat_before_deadline(
        self,
        lease: VisionJobLease,
        lease_deadline_utc: datetime,
        progress_reader: ProcessingProgressReader,
    ) -> VisionJobHeartbeatResponse:
        remaining = (lease_deadline_utc - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            raise WorkerApiError("heartbeat deadline exceeded")

        try:
            heartbeat = await asyncio.wait_for(
                self._api_client.heartbeat(
                    lease,
                    self._running_progress_percent(progress_reader),
                ),
                timeout=remaining,
            )
        except asyncio.TimeoutError as exc:
            raise WorkerApiError("heartbeat deadline exceeded") from exc

        # `wait_for` is driven by the event loop's monotonic timer. Re-check the
        # authoritative UTC deadline so a response completing on the boundary, or
        # after a wall-clock correction, is never accepted as a valid renewal.
        if datetime.now(timezone.utc) >= lease_deadline_utc:
            raise WorkerApiError("heartbeat deadline exceeded")
        return heartbeat

    def _log_progress(
        self,
        lease: VisionJobLease,
        progress_reader: ProcessingProgressReader,
    ) -> None:
        snapshot = progress_reader.snapshot()
        now_monotonic = self._monotonic_clock()
        started_monotonic = snapshot.started_monotonic
        elapsed_seconds = (
            None
            if started_monotonic is None or not isfinite(now_monotonic)
            else max(0.0, now_monotonic - started_monotonic)
        )

        processing_fps: float | None = None
        eta_seconds: float | None = None
        if elapsed_seconds is not None and elapsed_seconds > 0:
            processing_fps = snapshot.frames_processed / elapsed_seconds
            source_offset_ms = snapshot.source_offset_ms
            if (
                source_offset_ms is not None
                and source_offset_ms > 0
                and snapshot.source_duration_ms > source_offset_ms
            ):
                source_rate = (source_offset_ms / 1000.0) / elapsed_seconds
                if source_rate > 0:
                    eta_seconds = (
                        (snapshot.source_duration_ms - source_offset_ms) / 1000.0
                    ) / source_rate

        _LOGGER.info(
            "Vision job %s attempt %s progress stage=%s percent=%.2f "
            "frames=%s source_offset_ms=%s elapsed_s=%s fps=%s eta_s=%s",
            lease.job_id,
            lease.attempt_count,
            snapshot.stage,
            snapshot.progress_percent,
            snapshot.frames_processed,
            snapshot.source_offset_ms,
            (
                None
                if elapsed_seconds is None
                else round(elapsed_seconds, 3)
            ),
            (
                None
                if processing_fps is None
                else round(processing_fps, 3)
            ),
            None if eta_seconds is None else round(eta_seconds, 1),
        )

    @staticmethod
    def _running_progress_percent(
        progress_reader: ProcessingProgressReader,
    ) -> float:
        progress_percent = progress_reader.snapshot().progress_percent
        if (
            not isfinite(progress_percent)
            or progress_percent < 0.0
            or progress_percent > RUNNING_MAX_PERCENT
        ):
            raise WorkerApiError("worker progress invalid")
        return progress_percent

    def _heartbeat_wait_seconds(
        self,
        heartbeat: VisionJobHeartbeatResponse,
    ) -> float:
        now = datetime.now(timezone.utc)
        remaining = (heartbeat.lease_expires_at_utc - now).total_seconds()
        if remaining <= 0:
            raise WorkerApiError("worker API returned expired lease deadline")

        # Start the request early enough that its configured timeout cannot consume the
        # entire remaining lease. For a lease shorter than two request timeouts, reserve
        # half of the remaining lifetime instead of waiting until expiry.
        safety_margin = min(
            self._heartbeat_request_timeout_seconds,
            remaining / 2.0,
        )
        deadline_wait = remaining - safety_margin
        return min(self._heartbeat_interval_seconds, deadline_wait)

    async def run_forever(self) -> None:
        while True:
            try:
                had_work = await self.run_once()
            except WorkerApiError:
                had_work = False
            if not had_work:
                await asyncio.sleep(self._poll_interval_seconds)

    async def _best_effort_fail(
        self,
        lease: VisionJobLease,
        failure_code: str,
        failure_message: str,
    ) -> None:
        try:
            await self._api_client.fail(lease, failure_code, failure_message)
        except WorkerApiError:
            raise
        except Exception:
            return


def _consume_background_task_result(task: asyncio.Task[object]) -> None:
    if task.cancelled():
        return
    try:
        task.exception()
    except asyncio.CancelledError:
        return
