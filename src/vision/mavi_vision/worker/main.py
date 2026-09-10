import asyncio
import logging

from mavi_vision.common.settings import WorkerSettings
from mavi_vision.storage.local_media_store import LocalMediaStore
from mavi_vision.worker.client import WorkerApiClient
from mavi_vision.worker.runner import VisionProcessor, WorkerRunner


# Process logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def build_runner(
    settings: WorkerSettings,
    client: WorkerApiClient,
    processor: VisionProcessor | None = None,
) -> WorkerRunner:
    """Compose a worker without hard-coding a fixture or production model pipeline."""
    return WorkerRunner(
        client,
        LocalMediaStore(settings.media_root),
        settings.poll_interval_seconds,
        processor,
        heartbeat_interval_seconds=settings.heartbeat_interval_seconds,
    )


# Worker composition
async def _run_worker(settings: WorkerSettings) -> None:
    client = WorkerApiClient(settings)
    runner = build_runner(settings, client)
    logger.info("Starting MAVI vision worker %s", settings.worker_id)
    try:
        await runner.run_forever()
    finally:
        await client.aclose()


# Module entry point
def main() -> None:
    settings = WorkerSettings()
    try:
        asyncio.run(_run_worker(settings))
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("MAVI vision worker stopped")


if __name__ == "__main__":
    main()
