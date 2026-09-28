"""Entry point of the ``attributes`` role: ``python -m mavi_vision.attributes.main``.

The Component Binding names this module as the role's entry point, and the resolver refuses
any other (``IMPLEMENTED_ROLE_ENTRY_POINTS``). The process leases only while READY.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from mavi_vision.attributes.client import AttributeApiClient, AttributeApiError
from mavi_vision.attributes.runner import AttributeRunner
from mavi_vision.attributes.settings import AttributeWorkerSettings
from mavi_vision.attributes.supervisor import AttributeRuntimeState, AttributeSupervisor, attribute_composition
from mavi_vision.common.settings import reject_v1_composition_environment

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

COMPOSITION_REFUSED_EXIT = 2
RUNTIME_UNAVAILABLE_EXIT = 3


async def run_worker(
    settings: AttributeWorkerSettings,
    *,
    client_factory: Callable[..., Any] = AttributeApiClient,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    max_iterations: int | None = None,
) -> int:
    try:
        composition = attribute_composition(settings)
    except ValueError as exc:
        logger.error("Attributes role composition refused: %s", exc)
        return COMPOSITION_REFUSED_EXIT
    supervisor = AttributeSupervisor(settings, composition)
    supervisor.start()
    if supervisor.state is not AttributeRuntimeState.READY:
        # Never lease without a runtime: an attempt would be consumed for nothing. The
        # platform's readiness reports the absence of a READY worker meanwhile.
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
    runner = AttributeRunner(
        client,
        worker_id=settings.worker_id,
        profile=runtime.profile,
        inferencer=runtime.inferencer,
        provenance=runtime.provenance,
        heartbeat_interval_seconds=settings.heartbeat_interval_seconds,
        request_timeout_seconds=settings.request_timeout_seconds,
    )
    logger.info("Starting MAVI attributes worker %s", settings.worker_id)
    iterations = 0
    try:
        while max_iterations is None or iterations < max_iterations:
            iterations += 1
            try:
                outcome = await runner.run_once()
            except AttributeApiError as exc:
                logger.warning("Attribute lease poll failed (%s, %s)", exc.status_code, exc.code)
                outcome = None
            if outcome is None:
                await sleep(settings.poll_interval_seconds)
        return 0
    finally:
        await client.aclose()


def main() -> None:
    try:
        reject_v1_composition_environment()
        settings = AttributeWorkerSettings()  # type: ignore[call-arg]
    except ValueError as exc:
        logger.error("Attributes worker configuration refused: %s", exc)
        raise SystemExit(COMPOSITION_REFUSED_EXIT) from None
    try:
        exit_code = asyncio.run(run_worker(settings))
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("MAVI attributes worker stopped")
        return
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
