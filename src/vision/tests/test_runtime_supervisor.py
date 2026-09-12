from __future__ import annotations

import asyncio
import importlib
import importlib.util
import threading
from types import SimpleNamespace

import pytest

from mavi_vision.runtime.activity import InferenceActivity
from mavi_vision.runtime.errors import GpuOutOfMemoryError, GpuRuntimeError, TrackerError
from mavi_vision.runtime.interfaces import RuntimeMetadata


VOCABULARY = ("person", "car", "motorcycle", "bus", "truck")


def _module():
    spec = importlib.util.find_spec("mavi_vision.runtime.supervisor")
    assert spec is not None, "Task 11 runtime supervisor has not been implemented"
    return importlib.import_module("mavi_vision.runtime.supervisor")


class _Runtime:
    def __init__(
        self,
        name: str,
        *,
        device: str = "cpu",
        vocabulary: tuple[str, ...] = VOCABULARY,
        warmup_error: BaseException | None = None,
    ) -> None:
        self.name = name
        self.metadata = RuntimeMetadata(
            backend="mmdetection",
            model_id="model-a",
            device=device,
            versions={"fixture": "1"},
            ordered_class_vocabulary=vocabulary,
        )
        self.warmup_error = warmup_error
        self.warmup_calls = 0
        self.close_calls = 0

    def warmup(self) -> None:
        self.warmup_calls += 1
        if self.warmup_error is not None:
            raise self.warmup_error

    def infer(self, image_rgb):
        del image_rgb
        return ()

    def close(self) -> None:
        self.close_calls += 1


class _Lane:
    def __init__(self) -> None:
        self.close_calls = 0

    async def run(self, func, /, *args, **kwargs):
        return func(*args, **kwargs)

    async def close(self) -> None:
        self.close_calls += 1


class _Harness:
    def __init__(
        self,
        *,
        runtimes: list[_Runtime] | None = None,
        verifier_error: BaseException | None = None,
        provenance_error: BaseException | None = None,
        device_policy: str = "cpu",
        production_mode: bool = False,
        require_gpu_identity: bool = False,
        activity: InferenceActivity | None = None,
        monotonic_clock=None,
    ) -> None:
        module = _module()
        self.module = module
        self.events: list[str] = []
        self.lane = _Lane()
        self.activity = activity or InferenceActivity()
        self.selection = SimpleNamespace(
            manifest=SimpleNamespace(
                backend="mmdetection",
                model_id="model-a",
                class_vocabulary=VOCABULARY,
            ),
            profile=SimpleNamespace(profile_id="profile-a"),
        )
        self.runtimes = list(runtimes or [_Runtime("a")])
        self.verify_calls: list[dict[str, object]] = []
        self.factory_calls: list[tuple[object, str, object]] = []
        self.provenance_calls: list[dict[str, object]] = []
        self.provenances: list[object] = []

        def verify(**kwargs):
            self.events.append("verify")
            self.verify_calls.append(kwargs)
            if verifier_error is not None:
                raise verifier_error
            return self.selection

        def make_runtime(selection, *, device, activity):
            self.events.append("construct:" + device)
            self.factory_calls.append((selection, device, activity))
            if not self.runtimes:
                raise AssertionError("unexpected reconstruction")
            return self.runtimes.pop(0)

        def make_provenance(**kwargs):
            self.events.append("provenance")
            self.provenance_calls.append(kwargs)
            if require_gpu_identity and kwargs.get("gpu") is None:
                raise ValueError("cuda_gpu_identity_required")
            if provenance_error is not None:
                raise provenance_error
            value = object()
            self.provenances.append(value)
            return value

        self.supervisor = module.RuntimeSupervisor(
            lane=self.lane,
            activity=self.activity,
            model_root=SimpleNamespace(),
            manifest_path=SimpleNamespace(),
            profile_path=SimpleNamespace(),
            runtime_profile_path=SimpleNamespace(),
            qualification_path=SimpleNamespace(),
            device_policy=device_policy,
            device_index=2,
            production_mode=production_mode,
            inference_watchdog_seconds=30.0,
            build_id="build-a",
            commit_sha="a" * 40,
            release_verifier=verify,
            runtime_factory=make_runtime,
            provenance_builder=make_provenance,
            gpu_identity_provider=lambda device: None,
            **(
                {"monotonic_clock": monotonic_clock}
                if monotonic_clock is not None
                else {}
            ),
        )


def test_initial_state_has_no_published_runtime() -> None:
    module = _module()
    harness = _Harness()

    assert harness.supervisor.state is module.RuntimeState.STARTING
    assert harness.supervisor.provenance is None
    assert harness.supervisor.restart_required is False
    with pytest.raises(module.RuntimeNotReadyError, match="runtime_not_ready"):
        _ = harness.supervisor.runtime


def test_startup_verifies_before_construction_and_publishes_transactionally() -> None:
    async def scenario() -> None:
        harness = _Harness()
        runtime = harness.runtimes[0]

        original_warmup = runtime.warmup

        def warmup() -> None:
            harness.events.append("warmup")
            original_warmup()

        runtime.warmup = warmup
        await harness.supervisor.start()

        assert harness.events == ["verify", "construct:cpu", "warmup", "provenance"]
        assert harness.supervisor.state is harness.module.RuntimeState.READY
        assert harness.supervisor.runtime is runtime
        assert harness.supervisor.provenance is harness.provenances[0]
        assert harness.verify_calls[0]["allow_unverified"] is True
        assert harness.factory_calls == [(harness.selection, "cpu", harness.activity)]

    asyncio.run(scenario())


def test_verification_failure_never_constructs_or_publishes_runtime() -> None:
    async def scenario() -> None:
        harness = _Harness(verifier_error=ValueError("release-invalid"))

        await harness.supervisor.start()

        assert harness.events == ["verify"]
        assert harness.factory_calls == []
        assert harness.supervisor.state is harness.module.RuntimeState.UNAVAILABLE
        assert harness.supervisor.unavailable_reason == "release-invalid"
        with pytest.raises(harness.module.RuntimeNotReadyError):
            _ = harness.supervisor.runtime

    asyncio.run(scenario())


def test_candidate_failure_after_construction_is_closed_and_never_published() -> None:
    async def scenario() -> None:
        runtime = _Runtime("bad", warmup_error=RuntimeError("warmup-failed"))
        harness = _Harness(runtimes=[runtime])

        await harness.supervisor.start()

        assert runtime.close_calls == 1
        assert harness.supervisor.state is harness.module.RuntimeState.UNAVAILABLE
        assert harness.supervisor.provenance is None
        with pytest.raises(harness.module.RuntimeNotReadyError):
            _ = harness.supervisor.runtime

    asyncio.run(scenario())


def test_runtime_vocabulary_mismatch_fails_closed() -> None:
    async def scenario() -> None:
        runtime = _Runtime("bad-vocabulary", vocabulary=("person",))
        harness = _Harness(runtimes=[runtime])

        await harness.supervisor.start()

        assert runtime.close_calls == 1
        assert harness.supervisor.state is harness.module.RuntimeState.UNAVAILABLE
        assert harness.provenance_calls == []

    asyncio.run(scenario())


def test_release_policy_is_explicit_and_production_auto_is_defensively_rejected() -> None:
    async def scenario() -> None:
        development = _Harness(production_mode=False)
        production = _Harness(production_mode=True)
        production_auto = _Harness(production_mode=True, device_policy="auto")

        await development.supervisor.start()
        await production.supervisor.start()
        await production_auto.supervisor.start()

        assert development.verify_calls[0]["allow_unverified"] is True
        assert production.verify_calls[0]["allow_unverified"] is False
        assert production_auto.events == ["verify"]
        assert production_auto.supervisor.state is production_auto.module.RuntimeState.UNAVAILABLE

    asyncio.run(scenario())


def test_cross_thread_incident_handoff_is_nonblocking_and_severity_is_monotonic() -> None:
    async def scenario() -> None:
        runtime_a = _Runtime("a")
        runtime_b = _Runtime("b")
        harness = _Harness(runtimes=[runtime_a, runtime_b])
        await harness.supervisor.start()
        errors: list[BaseException] = []

        def report() -> None:
            try:
                harness.supervisor.report_processing_failure(TrackerError("continue"))
                harness.supervisor.report_processing_failure(GpuOutOfMemoryError("recover"))
                harness.supervisor.report_processing_failure(TrackerError("cannot-downgrade"))
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=report)
        thread.start()
        thread.join(timeout=1.0)

        assert thread.is_alive() is False
        assert errors == []
        assert runtime_a.close_calls == 0
        assert len(harness.factory_calls) == 1

        await harness.supervisor.recover_if_required()

        assert runtime_a.close_calls == 1
        assert len(harness.factory_calls) == 2
        assert harness.supervisor.runtime is runtime_b
        assert harness.supervisor.state is harness.module.RuntimeState.READY

    asyncio.run(scenario())


def test_recover_incident_gets_one_same_release_same_device_reconstruction() -> None:
    async def scenario() -> None:
        runtime_a = _Runtime("a")
        runtime_b = _Runtime("b")
        harness = _Harness(runtimes=[runtime_a, runtime_b])
        await harness.supervisor.start()
        selected_release, selected_device, _ = harness.factory_calls[0]

        harness.supervisor.report_processing_failure(GpuOutOfMemoryError("oom"))
        await harness.supervisor.recover_if_required()
        await harness.supervisor.recover_if_required()

        assert len(harness.factory_calls) == 2
        recovered_release, recovered_device, _ = harness.factory_calls[1]
        assert recovered_release is selected_release
        assert recovered_device == selected_device
        assert runtime_a.close_calls == 1
        assert runtime_b.warmup_calls == 1

    asyncio.run(scenario())


def test_failed_recovery_is_not_automatically_retried() -> None:
    async def scenario() -> None:
        runtime_a = _Runtime("a")
        runtime_b = _Runtime("b", warmup_error=RuntimeError("recovery-failed"))
        harness = _Harness(runtimes=[runtime_a, runtime_b])
        await harness.supervisor.start()

        harness.supervisor.report_processing_failure(GpuOutOfMemoryError("oom"))
        await harness.supervisor.recover_if_required()
        await harness.supervisor.recover_if_required()

        assert harness.supervisor.state is harness.module.RuntimeState.UNAVAILABLE
        assert len(harness.factory_calls) == 2
        assert runtime_a.close_calls == 1
        assert runtime_b.close_calls == 1

    asyncio.run(scenario())


def test_poisoned_runtime_requires_restart_without_cleanup_or_reconstruction() -> None:
    async def scenario() -> None:
        runtime = _Runtime("poisoned")
        harness = _Harness(runtimes=[runtime])
        await harness.supervisor.start()

        harness.supervisor.report_processing_failure(GpuRuntimeError("cuda-poisoned"))
        await harness.supervisor.recover_if_required()

        assert harness.supervisor.state is harness.module.RuntimeState.UNAVAILABLE
        assert harness.supervisor.restart_required is True
        assert runtime.close_calls == 0
        assert len(harness.factory_calls) == 1
        with pytest.raises(harness.module.RuntimeNotReadyError):
            _ = harness.supervisor.runtime

    asyncio.run(scenario())


def test_two_separate_oom_incidents_each_receive_one_recovery() -> None:
    async def scenario() -> None:
        runtime_a = _Runtime("a")
        runtime_b = _Runtime("b")
        runtime_c = _Runtime("c")
        harness = _Harness(runtimes=[runtime_a, runtime_b, runtime_c])
        await harness.supervisor.start()

        harness.supervisor.report_processing_failure(GpuOutOfMemoryError("oom-1"))
        await harness.supervisor.recover_if_required()
        harness.supervisor.report_processing_failure(GpuOutOfMemoryError("oom-2"))
        await harness.supervisor.recover_if_required()

        assert len(harness.factory_calls) == 3
        assert runtime_a.close_calls == 1
        assert runtime_b.close_calls == 1
        assert harness.supervisor.runtime is runtime_c

    asyncio.run(scenario())


def test_watchdog_expiry_uses_activity_and_records_restart_required_incident() -> None:
    async def scenario() -> None:
        clock_value = [100.0]
        activity = InferenceActivity(monotonic_clock=lambda: clock_value[0])
        runtime = _Runtime("a")
        harness = _Harness(
            runtimes=[runtime],
            activity=activity,
            monotonic_clock=lambda: clock_value[0],
        )
        await harness.supervisor.start()

        assert harness.supervisor.watchdog_expired() is False
        activity.mark_started()
        clock_value[0] = 130.0
        assert harness.supervisor.watchdog_expired() is True
        activity.mark_completed()

        harness.supervisor.report_watchdog_expiry()
        await harness.supervisor.recover_if_required()

        assert harness.supervisor.state is harness.module.RuntimeState.UNAVAILABLE
        assert harness.supervisor.restart_required is True
        assert runtime.close_calls == 0

    asyncio.run(scenario())


def test_cuda_startup_fails_closed_when_gpu_identity_is_unavailable() -> None:
    async def scenario() -> None:
        runtime = _Runtime("cuda", device="cuda:2")
        harness = _Harness(
            runtimes=[runtime],
            device_policy="cuda",
            require_gpu_identity=True,
        )

        await harness.supervisor.start()

        assert harness.supervisor.state is harness.module.RuntimeState.UNAVAILABLE
        assert harness.supervisor.unavailable_reason == "cuda_gpu_identity_required"
        assert runtime.close_calls == 1

    asyncio.run(scenario())


def test_close_is_idempotent_and_supervisor_owns_lane_shutdown_once() -> None:
    async def scenario() -> None:
        runtime = _Runtime("a")
        harness = _Harness(runtimes=[runtime])
        await harness.supervisor.start()

        await harness.supervisor.close()
        await harness.supervisor.close()
        harness.supervisor.report_processing_failure(GpuOutOfMemoryError("late"))
        await harness.supervisor.recover_if_required()

        assert harness.supervisor.state is harness.module.RuntimeState.STOPPING
        assert runtime.close_calls == 1
        assert harness.lane.close_calls == 1

    asyncio.run(scenario())


def test_continue_incident_keeps_ready_runtime_without_reconstruction() -> None:
    async def scenario() -> None:
        runtime = _Runtime("a")
        harness = _Harness(runtimes=[runtime])
        await harness.supervisor.start()

        harness.supervisor.report_processing_failure(TrackerError("tracker"))
        await harness.supervisor.recover_if_required()

        assert harness.supervisor.state is harness.module.RuntimeState.READY
        assert harness.supervisor.runtime is runtime
        assert runtime.close_calls == 0
        assert len(harness.factory_calls) == 1

    asyncio.run(scenario())


def test_reports_after_stopping_are_ignored_and_nonthrowing() -> None:
    async def scenario() -> None:
        runtime = _Runtime("a")
        harness = _Harness(runtimes=[runtime])
        await harness.supervisor.start()
        await harness.supervisor.close()

        harness.supervisor.report_processing_failure(GpuOutOfMemoryError("late"))
        harness.supervisor.report_watchdog_expiry()
        await harness.supervisor.recover_if_required()

        assert harness.supervisor.state is harness.module.RuntimeState.STOPPING
        assert len(harness.factory_calls) == 1

    asyncio.run(scenario())
