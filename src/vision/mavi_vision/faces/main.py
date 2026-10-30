"""Entry point of the ``faces`` role: ``python -m mavi_vision.faces.main`` (PoC S6; ADR-022).

Two concurrent loops share one READY runtime: the analysis loop (lease, detect, embed, complete) and the transient
query-image loop, so a long analysis never starves an operator's query. The process leases only while READY, and
refuses production mode before anything else.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from mavi_vision.faces.client import FaceApiClient, FaceApiError
from mavi_vision.faces.runner import FaceRunner, QueryRunner
from mavi_vision.faces.settings import FaceWorkerSettings
from mavi_vision.faces.supervisor import FaceRuntimeState, FaceSupervisor

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
        except FaceApiError as exc:
            logger.warning("Face %s poll failed (%s, %s)", name, exc.status_code, exc.code)
            outcome = None
        if outcome is None:
            await sleep(idle_seconds)


async def run_worker(
    settings: FaceWorkerSettings,
    *,
    supervisor_factory: Callable[[FaceWorkerSettings], FaceSupervisor] = FaceSupervisor,
    client_factory: Callable[..., Any] = FaceApiClient,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    max_iterations: int | None = None,
) -> int:
    supervisor = supervisor_factory(settings)
    await asyncio.to_thread(supervisor.start)
    if supervisor.state is not FaceRuntimeState.READY:
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
    analysis = FaceRunner(
        client,
        worker_id=settings.worker_id,
        model=runtime.model,
        dimension=runtime.identity.dimension,
        minimum_face_side=runtime.profile.minimum_face_side,
        provenance=runtime.provenance,
        heartbeat_interval_seconds=settings.heartbeat_interval_seconds,
        request_timeout_seconds=settings.request_timeout_seconds,
    )
    query = QueryRunner(
        client,
        worker_id=settings.worker_id,
        model=runtime.model,
        dimension=runtime.identity.dimension,
        minimum_face_side=runtime.profile.minimum_face_side,
        maximum_image_bytes=runtime.profile.query_image_maximum_bytes,
    )
    logger.info("Starting MAVI faces worker %s (identity %s)", settings.worker_id, runtime.identity.fingerprint)
    try:
        await asyncio.gather(
            _loop("analysis", analysis.run_once, settings.poll_interval_seconds, sleep, max_iterations),
            _loop("query", query.run_once, settings.query_poll_interval_seconds, sleep, max_iterations),
        )
        return 0
    finally:
        analysis.close()
        query.close()
        await client.aclose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        settings = FaceWorkerSettings()  # type: ignore[call-arg]
    except ValueError as exc:
        logger.error("Faces worker configuration refused: %s", exc)
        raise SystemExit(CONFIGURATION_REFUSED_EXIT) from None
    try:
        exit_code = asyncio.run(run_worker(settings))
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("MAVI faces worker stopped")
        return
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
