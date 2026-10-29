"""Entry point of the ``embeddings`` role: ``python -m mavi_vision.embeddings.main`` (PoC S4; ADR-021).

Two concurrent loops share one READY runtime: the analysis loop (lease, embed, complete) and the appearance
text-query loop, so a long analysis never starves a text query. The process leases only while READY, and refuses
production mode before anything else.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from mavi_vision.embeddings.client import EmbeddingApiClient, EmbeddingApiError
from mavi_vision.embeddings.runner import EmbeddingRunner, TextQueryRunner
from mavi_vision.embeddings.settings import EmbeddingWorkerSettings
from mavi_vision.embeddings.supervisor import EmbeddingRuntimeState, EmbeddingSupervisor

logger = logging.getLogger(__name__)

CONFIGURATION_REFUSED_EXIT = 2
RUNTIME_UNAVAILABLE_EXIT = 3


async def _loop(name: str, run_once: Callable[[], Awaitable[Any]], idle_seconds: float,
                sleep: Callable[[float], Awaitable[None]], max_iterations: int | None) -> None:
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        iterations += 1
        try:
            outcome = await run_once()
        except EmbeddingApiError as exc:
            logger.warning("Embedding %s poll failed (%s, %s)", name, exc.status_code, exc.code)
            outcome = None
        if outcome is None:
            await sleep(idle_seconds)


async def run_worker(
    settings: EmbeddingWorkerSettings,
    *,
    supervisor_factory: Callable[[EmbeddingWorkerSettings], EmbeddingSupervisor] = EmbeddingSupervisor,
    client_factory: Callable[..., Any] = EmbeddingApiClient,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    max_iterations: int | None = None,
) -> int:
    supervisor = supervisor_factory(settings)
    # Model loading is slow (about 1.5 GB of ONNX); it runs off the event loop.
    await asyncio.to_thread(supervisor.start)
    if supervisor.state is not EmbeddingRuntimeState.READY:
        # Never lease without a runtime: an attempt would be consumed for nothing.
        return RUNTIME_UNAVAILABLE_EXIT
    runtime = supervisor.runtime
    client = client_factory(
        api_base_url=settings.api_base_url,
        worker_id=settings.worker_id,
        identity=runtime.identity,
        request_timeout_seconds=settings.request_timeout_seconds,
        evidence_read_attempts=settings.evidence_read_attempts,
        evidence_retry_backoff_seconds=settings.evidence_retry_backoff_seconds,
        verify=str(settings.ca_bundle) if settings.ca_bundle is not None else True,
    )
    analysis = EmbeddingRunner(
        client,
        worker_id=settings.worker_id,
        model=runtime.model,
        dimension=runtime.identity.dimension,
        minimum_crop_side=runtime.profile.minimum_crop_side,
        provenance=runtime.provenance,
        heartbeat_interval_seconds=settings.heartbeat_interval_seconds,
        request_timeout_seconds=settings.request_timeout_seconds,
    )
    text = TextQueryRunner(
        client,
        worker_id=settings.worker_id,
        model=runtime.model,
        dimension=runtime.identity.dimension,
        maximum_characters=runtime.profile.text_maximum_characters,
    )
    logger.info("Starting MAVI embeddings worker %s (identity %s)", settings.worker_id, runtime.identity.fingerprint)
    try:
        await asyncio.gather(
            _loop("analysis", analysis.run_once, settings.poll_interval_seconds, sleep, max_iterations),
            _loop("text query", text.run_once, settings.text_query_poll_interval_seconds, sleep, max_iterations),
        )
        return 0
    finally:
        analysis.close()
        text.close()
        await client.aclose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        settings = EmbeddingWorkerSettings()  # type: ignore[call-arg]
    except ValueError as exc:
        # pydantic's message names the failing setting and code, never a secret: settings carry none.
        logger.error("Embeddings worker configuration refused: %s", exc)
        raise SystemExit(CONFIGURATION_REFUSED_EXIT) from None
    try:
        exit_code = asyncio.run(run_worker(settings))
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("MAVI embeddings worker stopped")
        return
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
