"""Entry point of the ``plates`` role: ``python -m mavi_vision.plates.main``.

The Component Binding names this module as the role's entry point, and the resolver refuses any other
(``IMPLEMENTED_ROLE_ENTRY_POINTS``). The process leases only while READY.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from mavi_vision.common.settings import reject_v1_composition_environment
from mavi_vision.plates.client import PlateApiClient, PlateApiError
from mavi_vision.plates.runner import PlateRunner
from mavi_vision.plates.settings import PlateWorkerSettings
from mavi_vision.plates.supervisor import PlateRuntimeState, PlateSupervisor, plate_composition

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

COMPOSITION_REFUSED_EXIT = 2
RUNTIME_UNAVAILABLE_EXIT = 3


async def run_worker(
    settings: PlateWorkerSettings,
    *,
    client_factory: Callable[..., Any] = PlateApiClient,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    max_iterations: int | None = None,
) -> int:
    try:
        composition = plate_composition(settings)
    except ValueError as exc:
        logger.error("Plates role composition refused: %s", exc)
        return COMPOSITION_REFUSED_EXIT
    supervisor = PlateSupervisor(settings, composition)
    supervisor.start()
    if supervisor.state is not PlateRuntimeState.READY:
        # Never lease without a runtime: an attempt would be consumed for nothing.
        return RUNTIME_UNAVAILABLE_EXIT
    runtime = supervisor.runtime
    client = client_factory(
        api_base_url=settings.api_base_url,
        worker_id=settings.worker_id,
        identity_fingerprint=runtime.identity.fingerprint,
        request_timeout_seconds=settings.request_timeout_seconds,
        evidence_read_attempts=settings.evidence_read_attempts,
        evidence_retry_backoff_seconds=settings.evidence_retry_backoff_seconds,
        verify=str(settings.ca_bundle) if settings.ca_bundle is not None else True,
    )
    runner = PlateRunner(
        client,
        worker_id=settings.worker_id,
        parameters=runtime.profile.parameters,
        detector=runtime.detector,
        recogniser=runtime.recogniser,
        provenance=runtime.provenance,
        heartbeat_interval_seconds=settings.heartbeat_interval_seconds,
        request_timeout_seconds=settings.request_timeout_seconds,
    )
    logger.info("Starting MAVI plates worker %s", settings.worker_id)
    iterations = 0
    try:
        while max_iterations is None or iterations < max_iterations:
            iterations += 1
            try:
                outcome = await runner.run_once()
            except PlateApiError as exc:
                logger.warning("Plate lease poll failed (%s, %s)", exc.status_code, exc.code)
                outcome = None
            if outcome is None:
                await sleep(settings.poll_interval_seconds)
        return 0
    finally:
        runner.close()
        await client.aclose()


def main() -> None:
    try:
        reject_v1_composition_environment()
        settings = PlateWorkerSettings()  # type: ignore[call-arg]
    except ValueError as exc:
        logger.error("Plates worker configuration refused: %s", exc)
        raise SystemExit(COMPOSITION_REFUSED_EXIT) from None
    try:
        exit_code = asyncio.run(run_worker(settings))
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("MAVI plates worker stopped")
        return
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
