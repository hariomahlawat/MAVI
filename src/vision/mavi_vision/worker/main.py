from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from mavi_vision.common.settings import WorkerSettings
from mavi_vision.pipeline.production_processor import ProductionVisionProcessor
from mavi_vision.runtime.activity import InferenceActivity
from mavi_vision.runtime.execution_lane import ProcessExecutor, VisionExecutionLane
from mavi_vision.runtime.supervisor import RuntimeState, RuntimeSupervisor
from mavi_vision.storage.artifact_store import StagingArtifactStore
from mavi_vision.storage.local_media_store import LocalMediaStore
from mavi_vision.worker.client import WorkerApiClient, WorkerApiError
from mavi_vision.worker.runner import VisionProcessor, WorkerRunner


# Process logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SERVICE_RESTART_EXIT_CODE = 70


def build_runner(
    settings: WorkerSettings,
    client: WorkerApiClient,
    processor: VisionProcessor | None = None,
    *,
    process_executor: ProcessExecutor | None = None,
    watchdog_expired: Callable[[], bool] | None = None,
    watchdog_expiry_sink: Callable[[], None] | None = None,
    watchdog_grace_seconds: float | None = None,
) -> WorkerRunner:
    """Compose the control-plane runner without granting it runtime ownership."""
    return WorkerRunner(
        client,
        LocalMediaStore(settings.media_root),
        settings.poll_interval_seconds,
        processor,
        heartbeat_interval_seconds=settings.heartbeat_interval_seconds,
        heartbeat_request_timeout_seconds=settings.request_timeout_seconds,
        process_executor=process_executor,
        watchdog_expired=watchdog_expired,
        watchdog_expiry_sink=watchdog_expiry_sink,
        watchdog_grace_seconds=(
            settings.watchdog_grace_seconds
            if watchdog_grace_seconds is None
            else watchdog_grace_seconds
        ),
    )


async def _run_supervised_loop(
    supervisor: Any,
    runner: Any,
    *,
    poll_interval_seconds: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> int:
    """Lease only while READY and reconcile local runtime incidents around attempts."""
    while True:
        # This is the mandatory before-lease reconciliation point. A failure sink
        # may have reported an incident even if the previous terminal API call failed.
        await supervisor.recover_if_required()
        state = supervisor.state

        if state is RuntimeState.STOPPING:
            return 0
        if state is RuntimeState.UNAVAILABLE and supervisor.restart_required:
            return SERVICE_RESTART_EXIT_CODE

        if state is RuntimeState.RECOVERING:
            # Recovery is event-loop owned. Give an already-entered recovery state
            # one explicit reconciliation opportunity before yielding diagnostics.
            await supervisor.recover_if_required()
            state = supervisor.state
            if state is RuntimeState.STOPPING:
                return 0
            if state is RuntimeState.UNAVAILABLE and supervisor.restart_required:
                return SERVICE_RESTART_EXIT_CODE

        if state is not RuntimeState.READY:
            # STARTING, non-restart UNAVAILABLE, and a still-RECOVERING state must
            # never reach lease(). Yield rather than spinning while diagnostics
            # remain available to the service manager/operator.
            await sleep(poll_interval_seconds)
            continue

        had_work = False
        try:
            had_work = await runner.run_once()
        except WorkerApiError:
            # Preserve historical polling/backoff behavior for transport and lease
            # errors. Local runtime reconciliation still runs in finally below.
            had_work = False
        finally:
            # Critical containment boundary: reconcile even when terminal /fail,
            # heartbeat, or lease transport failed after a local OOM/fatal report.
            await supervisor.recover_if_required()

        state = supervisor.state
        if state is RuntimeState.STOPPING:
            return 0
        if state is RuntimeState.UNAVAILABLE and supervisor.restart_required:
            return SERVICE_RESTART_EXIT_CODE

        if not had_work:
            await sleep(poll_interval_seconds)


# Worker composition
async def _run_worker(
    settings: WorkerSettings,
    *,
    client_factory: Callable[[WorkerSettings], Any] = WorkerApiClient,
    lane_factory: Callable[[], Any] = VisionExecutionLane,
    activity_factory: Callable[[], Any] = InferenceActivity,
    supervisor_factory: Callable[..., Any] = RuntimeSupervisor,
    processor_factory: Callable[..., Any] = ProductionVisionProcessor,
    runner_builder: Callable[..., Any] = build_runner,
    supervised_loop: Callable[..., Awaitable[int]] = _run_supervised_loop,
) -> int:
    """Compose one process-scoped runtime and run the readiness-gated worker."""
    client = client_factory(settings)
    lane: Any | None = None
    supervisor: Any | None = None
    runner: Any | None = None

    try:
        lane = lane_factory()
        activity = activity_factory()
        supervisor = supervisor_factory(
            lane=lane,
            activity=activity,
            model_root=settings.model_root,
            manifest_path=settings.model_manifest_path,
            profile_path=settings.pipeline_profile_path,
            runtime_profile_path=settings.runtime_profile_path,
            qualification_path=settings.qualification_record_path,
            device_policy=settings.device_policy,
            device_index=settings.device_index,
            production_mode=settings.production_mode,
            inference_watchdog_seconds=settings.inference_watchdog_seconds,
            build_id=settings.build_id,
            commit_sha=settings.commit_sha,
        )

        logger.info("Starting MAVI vision worker %s", settings.worker_id)
        await supervisor.start()

        processor: VisionProcessor | None = None
        if supervisor.state is RuntimeState.READY:
            processor = processor_factory(
                runtime_provider=lambda: supervisor.runtime,
                profile=supervisor.profile,
                staging_factory=lambda job_id, attempt_count: StagingArtifactStore(
                    settings.media_root,
                    job_id,
                    attempt_count,
                ),
                runtime_failure_sink=supervisor.report_processing_failure,
            )

        runner = runner_builder(
            settings,
            client,
            processor,
            process_executor=lane,
            watchdog_expired=supervisor.watchdog_expired,
            watchdog_expiry_sink=supervisor.report_watchdog_expiry,
            watchdog_grace_seconds=settings.watchdog_grace_seconds,
        )

        return await supervised_loop(
            supervisor,
            runner,
            poll_interval_seconds=settings.poll_interval_seconds,
        )
    finally:
        # RuntimeSupervisor is the designated owner once constructed. Fatal
        # watchdog containment is the one exception: the lane is known to contain
        # native work that failed to unwind inside grace, so waiting teardown would
        # recreate the deadlock the process-level terminator is meant to escape.
        fatal_watchdog = bool(
            runner is not None
            and getattr(runner, "fatal_termination_active", False)
        )
        try:
            if fatal_watchdog:
                logger.critical(
                    "Skipping poisoned vision-lane teardown after fatal watchdog"
                )
            elif supervisor is not None:
                await supervisor.close()
            elif lane is not None:
                await lane.close()
        finally:
            # HTTP resources are independent of the poisoned native lane and can
            # still be closed without violating bounded fatal containment.
            await client.aclose()


# Module entry point
def main() -> None:
    settings = WorkerSettings()
    try:
        exit_code = asyncio.run(_run_worker(settings))
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("MAVI vision worker stopped")
        return

    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
