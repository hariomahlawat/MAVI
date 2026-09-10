import asyncio
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from uuid import UUID

from mavi_vision.common.analytical import VisionProcessingResult
from mavi_vision.common.control_plane import VisionJobHeartbeatResponse, VisionJobLease
from mavi_vision.pipeline.process_video import VideoProcessingError
from mavi_vision.storage.integrity import SourceIntegrityError
from mavi_vision.storage.local_media_store import MediaStoreError
from mavi_vision.worker.client import WorkerApiError


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
        source_path: Path,
        expected_source_size_bytes: int,
        expected_source_sha256: str,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> VisionProcessingResult: ...


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
    ) -> None:
        if heartbeat_interval_seconds <= 0:
            raise ValueError("heartbeat_interval_seconds must be positive")
        if heartbeat_request_timeout_seconds <= 0:
            raise ValueError("heartbeat_request_timeout_seconds must be positive")
        self._api_client = api_client
        self._media_store = media_store
        self._poll_interval_seconds = poll_interval_seconds
        self._processor = processor
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._heartbeat_request_timeout_seconds = heartbeat_request_timeout_seconds

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
        except SourceIntegrityError:
            await self._best_effort_fail(
                lease,
                "source_media_integrity_failed",
                "Leased source media failed integrity verification.",
            )
            return True
        except VideoProcessingError:
            await self._best_effort_fail(
                lease,
                "vision_processing_failed",
                "Vision processing failed.",
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

        # Prove that the first renewal deadline is still usable before expensive work
        # is launched. Every subsequent response is validated immediately as well.
        current_deadline = heartbeat.lease_expires_at_utc
        wait_seconds = self._heartbeat_wait_seconds(heartbeat)
        cancel_event = threading.Event()
        process_task = asyncio.create_task(
            asyncio.to_thread(
                self._processor.process,
                job_id=lease.job_id,
                source_path=source_path,
                expected_source_size_bytes=lease.source_size_bytes,
                expected_source_sha256=lease.source_sha256,
                cancel_requested=cancel_event.is_set,
            )
        )

        try:
            while True:
                done, _ = await asyncio.wait(
                    {process_task},
                    timeout=wait_seconds,
                )
                if process_task in done:
                    if datetime.now(timezone.utc) >= current_deadline:
                        raise WorkerApiError("lease deadline exceeded")
                    return process_task.result()

                current_heartbeat = await self._heartbeat_before_deadline(
                    lease,
                    current_deadline,
                )
                current_deadline = current_heartbeat.lease_expires_at_utc
                wait_seconds = self._heartbeat_wait_seconds(current_heartbeat)
        except BaseException:
            cancel_event.set()
            if not process_task.done():
                try:
                    await process_task
                except BaseException:
                    pass
            raise
        finally:
            if not process_task.done():
                cancel_event.set()

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
