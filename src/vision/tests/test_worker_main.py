from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from mavi_vision.runtime.supervisor import RuntimeState
from mavi_vision.worker.client import WorkerApiError
from mavi_vision.worker import main as worker_main


class _LoopSupervisor:
    def __init__(
        self,
        state: RuntimeState,
        *,
        restart_required: bool = False,
        events: list[str] | None = None,
    ) -> None:
        self.state = state
        self.restart_required = restart_required
        self.events = events if events is not None else []
        self.pending_recovery = False

    async def recover_if_required(self) -> None:
        if self.pending_recovery:
            self.events.append("recover-pending")
            self.pending_recovery = False
            self.state = RuntimeState.READY
            return
        self.events.append("recover")

    async def close(self) -> None:
        self.events.append("supervisor-close")
        self.state = RuntimeState.STOPPING


class _LoopRunner:
    def __init__(self, callback, events: list[str]) -> None:
        self._callback = callback
        self.events = events
        self.calls = 0

    async def run_once(self) -> bool:
        self.calls += 1
        self.events.append(f"run:{self.calls}")
        return await self._callback(self.calls)


def test_supervised_loop_reconciles_in_finally_after_success() -> None:
    async def scenario() -> None:
        events: list[str] = []
        supervisor = _LoopSupervisor(RuntimeState.READY, events=events)

        async def run_once(call: int) -> bool:
            assert call == 1
            supervisor.state = RuntimeState.STOPPING
            return True

        runner = _LoopRunner(run_once, events)

        exit_code = await worker_main._run_supervised_loop(
            supervisor,
            runner,
            poll_interval_seconds=2.0,
            sleep=lambda _: asyncio.sleep(0),
        )

        assert exit_code == 0
        assert events == ["recover", "run:1", "recover"]

    asyncio.run(scenario())


def test_supervised_loop_reconciles_in_finally_after_worker_api_error() -> None:
    async def scenario() -> None:
        events: list[str] = []
        supervisor = _LoopSupervisor(RuntimeState.READY, events=events)

        async def run_once(call: int) -> bool:
            assert call == 1
            supervisor.state = RuntimeState.STOPPING
            raise WorkerApiError("transport failed")

        runner = _LoopRunner(run_once, events)

        exit_code = await worker_main._run_supervised_loop(
            supervisor,
            runner,
            poll_interval_seconds=2.0,
            sleep=lambda _: asyncio.sleep(0),
        )

        assert exit_code == 0
        assert events == ["recover", "run:1", "recover"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "initial_state",
    [
        RuntimeState.STARTING,
        RuntimeState.RECOVERING,
        RuntimeState.UNAVAILABLE,
    ],
)
def test_non_ready_runtime_never_leases_and_yields_for_diagnostics(
    initial_state: RuntimeState,
) -> None:
    async def scenario() -> None:
        events: list[str] = []
        supervisor = _LoopSupervisor(initial_state, events=events)

        async def should_not_run(call: int) -> bool:
            raise AssertionError(f"lease path reached in {initial_state}: {call}")

        runner = _LoopRunner(should_not_run, events)
        sleep_calls: list[float] = []

        async def sleep(delay: float) -> None:
            sleep_calls.append(delay)
            supervisor.state = RuntimeState.STOPPING

        exit_code = await worker_main._run_supervised_loop(
            supervisor,
            runner,
            poll_interval_seconds=2.0,
            sleep=sleep,
        )

        assert exit_code == 0
        assert runner.calls == 0
        assert sleep_calls == [2.0]

    asyncio.run(scenario())


def test_restart_required_unavailable_exits_with_service_restart_code_70() -> None:
    async def scenario() -> None:
        events: list[str] = []
        supervisor = _LoopSupervisor(
            RuntimeState.UNAVAILABLE,
            restart_required=True,
            events=events,
        )

        async def should_not_run(call: int) -> bool:
            raise AssertionError(f"unexpected lease call {call}")

        runner = _LoopRunner(should_not_run, events)
        sleep_calls: list[float] = []

        exit_code = await worker_main._run_supervised_loop(
            supervisor,
            runner,
            poll_interval_seconds=2.0,
            sleep=lambda delay: _record_sleep(delay, sleep_calls),
        )

        assert exit_code == 70
        assert runner.calls == 0
        assert sleep_calls == []

    asyncio.run(scenario())


async def _record_sleep(delay: float, calls: list[float]) -> None:
    calls.append(delay)


def test_pending_oom_recovery_occurs_before_any_next_lease_after_api_failure() -> None:
    async def scenario() -> None:
        events: list[str] = []
        supervisor = _LoopSupervisor(RuntimeState.READY, events=events)

        async def run_once(call: int) -> bool:
            if call == 1:
                supervisor.pending_recovery = True
                raise WorkerApiError("terminal fail transport failed")
            supervisor.state = RuntimeState.STOPPING
            return True

        runner = _LoopRunner(run_once, events)
        sleep_calls: list[float] = []

        async def sleep(delay: float) -> None:
            sleep_calls.append(delay)

        exit_code = await worker_main._run_supervised_loop(
            supervisor,
            runner,
            poll_interval_seconds=2.0,
            sleep=sleep,
        )

        assert exit_code == 0
        assert runner.calls == 2
        assert events.index("recover-pending") < events.index("run:2")
        assert sleep_calls == [2.0]

    asyncio.run(scenario())


class _CompositionLane:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1
        self.events.append("lane-close")


class _CompositionClient:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1
        self.events.append("client-close")


class _CompositionSupervisor:
    def __init__(self, lane: _CompositionLane, events: list[str]) -> None:
        self._lane = lane
        self.events = events
        self.state = RuntimeState.STARTING
        self.restart_required = False
        self.runtime = object()
        self.profile = object()
        self.close_calls = 0

    async def start(self) -> None:
        self.events.append("supervisor-start")
        self.state = RuntimeState.READY

    async def recover_if_required(self) -> None:
        self.events.append("recover")

    def report_processing_failure(self, error) -> None:
        del error

    def watchdog_expired(self) -> bool:
        return False

    def report_watchdog_expiry(self) -> None:
        return None

    async def close(self) -> None:
        self.close_calls += 1
        self.events.append("supervisor-close")
        self.state = RuntimeState.STOPPING
        await self._lane.close()


def _settings(tmp_path: Path):
    return SimpleNamespace(
        worker_id="dev-worker-01",
        api_base_url="https://mavi-api.local",
        media_root=tmp_path,
        poll_interval_seconds=2.0,
        heartbeat_interval_seconds=30.0,
        request_timeout_seconds=30.0,
        ca_bundle=None,
        model_root=tmp_path / "models",
        model_manifest_path=tmp_path / "manifest.json",
        pipeline_profile_path=tmp_path / "profile.json",
        runtime_profile_path=tmp_path / "runtime.json",
        qualification_record_path=tmp_path / "qualification.json",
        build_id="build-a",
        commit_sha="a" * 40,
        device_policy="cpu",
        device_index=0,
        production_mode=False,
        inference_watchdog_seconds=120.0,
        watchdog_grace_seconds=15.0,
    )


def test_run_worker_composes_ready_processor_runner_and_single_owner_shutdown(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        events: list[str] = []
        settings = _settings(tmp_path)
        client = _CompositionClient(events)
        lane = _CompositionLane(events)
        activity = object()
        supervisor_holder: list[_CompositionSupervisor] = []
        processor_kwargs: dict[str, object] = {}
        runner_kwargs: dict[str, object] = {}

        def supervisor_factory(**kwargs):
            assert kwargs["lane"] is lane
            assert kwargs["activity"] is activity
            assert kwargs["model_root"] == settings.model_root
            assert kwargs["manifest_path"] == settings.model_manifest_path
            assert kwargs["profile_path"] == settings.pipeline_profile_path
            assert kwargs["runtime_profile_path"] == settings.runtime_profile_path
            assert kwargs["qualification_path"] == settings.qualification_record_path
            assert kwargs["device_policy"] == settings.device_policy
            assert kwargs["device_index"] == settings.device_index
            assert kwargs["production_mode"] is settings.production_mode
            assert kwargs["build_id"] == settings.build_id
            assert kwargs["commit_sha"] == settings.commit_sha
            supervisor = _CompositionSupervisor(lane, events)
            supervisor_holder.append(supervisor)
            return supervisor

        def processor_factory(**kwargs):
            processor_kwargs.update(kwargs)
            events.append("processor-build")
            return object()

        def runner_builder(settings_arg, client_arg, processor, **kwargs):
            assert settings_arg is settings
            assert client_arg is client
            assert processor is not None
            runner_kwargs.update(kwargs)
            events.append("runner-build")
            return object()

        async def supervised_loop(supervisor, runner, **kwargs):
            assert supervisor is supervisor_holder[0]
            assert runner is not None
            assert kwargs["poll_interval_seconds"] == settings.poll_interval_seconds
            events.append("loop")
            return 0

        exit_code = await worker_main._run_worker(
            settings,
            client_factory=lambda _: client,
            lane_factory=lambda: lane,
            activity_factory=lambda: activity,
            supervisor_factory=supervisor_factory,
            processor_factory=processor_factory,
            runner_builder=runner_builder,
            supervised_loop=supervised_loop,
        )

        supervisor = supervisor_holder[0]
        assert exit_code == 0
        assert events[:4] == [
            "supervisor-start",
            "processor-build",
            "runner-build",
            "loop",
        ]
        assert processor_kwargs["profile"] is supervisor.profile
        assert processor_kwargs["runtime_provider"]() is supervisor.runtime
        assert (
            processor_kwargs["runtime_failure_sink"]
            == supervisor.report_processing_failure
        )
        staging_factory = processor_kwargs["staging_factory"]
        store = staging_factory(UUID(int=1), 1)
        assert store.job_id == UUID(int=1)
        assert store.attempt_count == 1

        assert runner_kwargs["process_executor"] is lane
        assert runner_kwargs["watchdog_expired"] == supervisor.watchdog_expired
        assert (
            runner_kwargs["watchdog_expiry_sink"]
            == supervisor.report_watchdog_expiry
        )
        assert runner_kwargs["watchdog_grace_seconds"] == settings.watchdog_grace_seconds

        assert events[-3:] == ["supervisor-close", "lane-close", "client-close"]
        assert supervisor.close_calls == 1
        assert lane.close_calls == 1
        assert client.close_calls == 1

    asyncio.run(scenario())


def test_run_worker_does_not_build_processor_when_startup_is_unavailable(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        events: list[str] = []
        settings = _settings(tmp_path)
        client = _CompositionClient(events)
        lane = _CompositionLane(events)
        activity = object()

        class UnavailableSupervisor(_CompositionSupervisor):
            async def start(self) -> None:
                self.events.append("supervisor-start")
                self.state = RuntimeState.UNAVAILABLE

        supervisor = UnavailableSupervisor(lane, events)
        runner_processor: list[object | None] = []

        def runner_builder(settings_arg, client_arg, processor, **kwargs):
            del settings_arg, client_arg, kwargs
            runner_processor.append(processor)
            return object()

        async def supervised_loop(supervisor_arg, runner, **kwargs):
            del runner, kwargs
            assert supervisor_arg.state is RuntimeState.UNAVAILABLE
            return 0

        exit_code = await worker_main._run_worker(
            settings,
            client_factory=lambda _: client,
            lane_factory=lambda: lane,
            activity_factory=lambda: activity,
            supervisor_factory=lambda **_: supervisor,
            processor_factory=lambda **_: (_ for _ in ()).throw(
                AssertionError("processor must not build while runtime is unavailable")
            ),
            runner_builder=runner_builder,
            supervised_loop=supervised_loop,
        )

        assert exit_code == 0
        assert runner_processor == [None]
        assert events[-3:] == ["supervisor-close", "lane-close", "client-close"]

    asyncio.run(scenario())


class _FatalCompositionSentinel(RuntimeError):
    pass


def test_run_worker_bypasses_poisoned_lane_teardown_after_fatal_watchdog(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        events: list[str] = []
        settings = _settings(tmp_path)
        client = _CompositionClient(events)
        lane = _CompositionLane(events)
        activity = object()
        supervisor = _CompositionSupervisor(lane, events)

        class FatalRunner:
            fatal_termination_active = False

        runner = FatalRunner()

        def runner_builder(settings_arg, client_arg, processor, **kwargs):
            del settings_arg, client_arg, processor, kwargs
            return runner

        async def supervised_loop(supervisor_arg, runner_arg, **kwargs):
            del supervisor_arg, kwargs
            assert runner_arg is runner
            runner.fatal_termination_active = True
            raise _FatalCompositionSentinel("fatal-watchdog")

        with pytest.raises(_FatalCompositionSentinel, match="fatal-watchdog"):
            await worker_main._run_worker(
                settings,
                client_factory=lambda _: client,
                lane_factory=lambda: lane,
                activity_factory=lambda: activity,
                supervisor_factory=lambda **_: supervisor,
                processor_factory=lambda **_: object(),
                runner_builder=runner_builder,
                supervised_loop=supervised_loop,
            )

        assert supervisor.close_calls == 0
        assert lane.close_calls == 0
        assert client.close_calls == 1
        assert events[-1] == "client-close"

    asyncio.run(scenario())
