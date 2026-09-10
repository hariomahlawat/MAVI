import asyncio
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
    ) -> VisionProcessingResult: ...


# Worker lifecycle orchestration
class WorkerRunner:
    def __init__(
        self,
        api_client: WorkerApi,
        media_store: MediaStore,
        poll_interval_seconds: float,
        processor: VisionProcessor | None = None,
    ) -> None:
        self._api_client = api_client
        self._media_store = media_store
        self._poll_interval_seconds = poll_interval_seconds
        self._processor = processor

    async def run_once(self) -> bool:
        lease = await self._api_client.lease()
        if lease is None:
            return False

        try:
            source_path = self._media_store.resolve_file(lease.source_storage_key)
            await self._api_client.heartbeat(lease, 5.0)
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
            self._processor.process(
                job_id=lease.job_id,
                source_path=source_path,
                expected_source_size_bytes=lease.source_size_bytes,
                expected_source_sha256=lease.source_sha256,
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
