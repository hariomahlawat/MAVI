import asyncio
import logging
import os
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, NoReturn, Protocol
from uuid import UUID

from mavi_vision.common.analytical import VisionProcessingResult
from mavi_vision.common.control_plane import VisionJobHeartbeatResponse, VisionJobLease
from mavi_vision.common.lease import LeaseGuard, LeaseLostError
from mavi_vision.pipeline.process_video import VideoProcessingError
from mavi_vision.runtime.errors import ProcessingDependencyError
from mavi_vision.runtime.execution_lane import ProcessExecutor
from mavi_vision.storage.integrity import SourceIntegrityError
from mavi_vision.storage.local_media_store import MediaStoreError
from mavi_vision.worker.client import WorkerApiError


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


class _WatchdogExpiredDuringHeartbeat(RuntimeError):
    pass


# Worker collaborators
class WorkerApi(Protocol):
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
        watchdog_expired: Callable[[], bool] | None = None,
        watchdog_expiry_sink: Callable[[], None] | None = None,
        watchdog_grace_seconds: float = 10.0,
        watchdog_poll_seconds: float = 1.0,
        fatal_terminator: Callable[[int], NoReturn] = os._exit,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if heartbeat_interval_seconds <= 0:
            raise ValueError("heartbeat_interval_seconds must be positive")
        if heartbeat_request_timeout_seconds <= 0:
            raise ValueError("heartbeat_request_timeout_seconds must be positive")
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
        self._watchdog_expired = watchdog_expired
        self._watchdog_expiry_sink = watchdog_expiry_sink
        self._watchdog_grace_seconds = watchdog_grace_seconds
        self._watchdog_poll_seconds = watchdog_poll_seconds
        self._fatal_terminator = fatal_terminator
        self._monotonic_clock = monotonic_clock
        self._fatal_termination_active = False

    @property
    def fatal_termination_active(self) -> bool:
        """True once watchdog containment requires process-level termination."""
        return self._fatal_termination_active

    async def run_once(self) -> bool:
        lease = await self._api_client.lease()
        if lease is None:
            return False

        try:
            source_path = self._media_store.resolve_file(lease.source_storage_key)
            heartbeat = await self._api_client.heartbeat(lease, 5.0)
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
            await self._process_with_lease_heartbeats(
                lease,
                source_path,
                heartbeat,
            )
        except LeaseLostError as exc:
            # Ownership loss is not a processing failure. A stale attempt must not
            # emit any terminal lifecycle request after its guard rejects work.
            raise WorkerApiError("lease ownership lost") from exc
        except SourceIntegrityError:
            await self._best_effort_fail(
                lease,
                "source_media_integrity_failed",
                "Leased source media failed integrity verification.",
            )
            return True
        except ProcessingDependencyError as exc:
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

        await self._api_client.fail(
            lease,
            "task9_result_submission_not_implemented",
            "Task 9 result submission is not implemented.",
        )
        return True

    async def _process_with_lease_heartbeats(
        self,
        lease: VisionJobLease,
        source_path: Path,
        heartbeat: VisionJobHeartbeatResponse,
    ) -> VisionProcessingResult:
        if self._processor is None:
            raise RuntimeError("processor_missing")

        current_deadline = heartbeat.lease_expires_at_utc
        lease_guard = LeaseGuard(current_deadline)
        process_task: asyncio.Task[VisionProcessingResult] | None = None

        try:
            lease_guard.check_owned()
            process_task = asyncio.create_task(
                self._process_executor.run(
                    self._processor.process,
                    job_id=lease.job_id,
                    attempt_count=lease.attempt_count,
                    source_path=source_path,
                    expected_source_size_bytes=lease.source_size_bytes,
                    expected_source_sha256=lease.source_sha256,
                    lease_guard=lease_guard,
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
                if self._watchdog_expired is not None:
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
                    return result

                if self._watchdog_is_expired():
                    await self._handle_watchdog_expiry(
                        process_task,
                        lease_guard,
                    )

                now_monotonic = self._monotonic_clock()
                if now_monotonic >= next_heartbeat_due:
                    try:
                        current_heartbeat = (
                            await self._heartbeat_before_deadline_while_processing(
                                lease,
                                current_deadline,
                                process_task,
                            )
                        )
                    except _WatchdogExpiredDuringHeartbeat:
                        await self._handle_watchdog_expiry(
                            process_task,
                            lease_guard,
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
                )
            raise
        finally:
            if process_task is not None and not process_task.done():
                lease_guard.mark_lost()

    async def _handle_watchdog_expiry(
        self,
        process_task: asyncio.Task[VisionProcessingResult],
        lease_guard: LeaseGuard,
    ) -> None:
        lease_guard.mark_lost()
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
    ) -> None:
        """Keep watchdog containment active while ordinary cleanup unwinds."""
        if self._watchdog_expired is None:
            try:
                await process_task
            except BaseException:
                pass
            return

        while not process_task.done():
            if self._watchdog_is_expired():
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

    def _watchdog_is_expired(self) -> bool:
        callback = self._watchdog_expired
        if callback is None:
            return False
        try:
            return bool(callback())
        except Exception:
            _LOGGER.exception("Watchdog callback failed; containing as expired")
            return True

    def _report_watchdog_expiry(self) -> None:
        sink = self._watchdog_expiry_sink
        if sink is None:
            return
        try:
            sink()
        except Exception:
            _LOGGER.exception("Watchdog expiry sink failed")

    async def _heartbeat_before_deadline_while_processing(
        self,
        lease: VisionJobLease,
        lease_deadline_utc: datetime,
        process_task: asyncio.Task[VisionProcessingResult],
    ) -> VisionJobHeartbeatResponse | None:
        if self._watchdog_expired is None:
            return await self._heartbeat_before_deadline(
                lease,
                lease_deadline_utc,
            )

        remaining = (
            lease_deadline_utc - datetime.now(timezone.utc)
        ).total_seconds()
        if remaining <= 0:
            raise WorkerApiError("heartbeat deadline exceeded")

        heartbeat_task = asyncio.create_task(
            self._api_client.heartbeat(lease, 5.0),
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

                if process_task in done:
                    if heartbeat_task in done:
                        try:
                            heartbeat_task.result()
                        except BaseException:
                            pass
                    return None

                if heartbeat_task in done:
                    heartbeat = heartbeat_task.result()
                    if datetime.now(timezone.utc) >= lease_deadline_utc:
                        raise WorkerApiError("heartbeat deadline exceeded")
                    return heartbeat

                if self._watchdog_is_expired():
                    raise _WatchdogExpiredDuringHeartbeat(
                        "vision_inference_watchdog_expired"
                    )
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
    ) -> VisionJobHeartbeatResponse:
        remaining = (lease_deadline_utc - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            raise WorkerApiError("heartbeat deadline exceeded")

        try:
            heartbeat = await asyncio.wait_for(
                self._api_client.heartbeat(lease, 5.0),
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
