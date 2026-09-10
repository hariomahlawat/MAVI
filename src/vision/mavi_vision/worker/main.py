import asyncio
import logging

from mavi_vision.common.settings import WorkerSettings
from mavi_vision.storage.local_media_store import LocalMediaStore
from mavi_vision.worker.client import WorkerApiClient
from mavi_vision.worker.runner import WorkerRunner


# Process logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# Worker composition
async def _run_worker(settings: WorkerSettings) -> None:
    client = WorkerApiClient(settings)
    runner = WorkerRunner(
        client,
        LocalMediaStore(settings.media_root),
        settings.poll_interval_seconds,
    )
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
