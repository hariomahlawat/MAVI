from __future__ import annotations

import asyncio
import importlib
import importlib.util
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from mavi_vision.runtime.activity import InferenceActivity
from mavi_vision.runtime.watchdog import RuntimeWatchdogSnapshot
from mavi_vision.runtime.errors import GpuOutOfMemoryError, GpuRuntimeError, TrackerError
from mavi_vision.runtime.execution_lane import VisionExecutionLane
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


class _BlockingWarmupRuntime(_Runtime):
    def __init__(
        self,
        name: str,
        *,
        activity: InferenceActivity,
        started: threading.Event,
        release: threading.Event,
    ) -> None:
        super().__init__(name)
        self._activity = activity
        self._started = started
        self._release = release

    def warmup(self) -> None:
        self.warmup_calls += 1
        self._activity.mark_started()
        self._started.set()
        try:
            if not self._release.wait(timeout=0.5):
                raise TimeoutError("blocking warmup was not released")
        finally:
            self._activity.mark_completed()


class _LifecycleFatalSentinel(RuntimeError):
    pass


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
        device_resolution_reason: str | None = None,
        production_mode: bool = False,
        deployment_profile: str | None = None,
        cuda_available: bool = False,
        require_gpu_identity: bool = False,
        activity: InferenceActivity | None = None,
        monotonic_clock=None,
        lane=None,
        inference_watchdog_seconds: float = 30.0,
        watchdog_grace_seconds: float = 10.0,
        watchdog_poll_seconds: float = 1.0,
        fatal_terminator=None,
    ) -> None:
        module = _module()
        self.module = module
        self.events: list[str] = []
        self.lane = lane or _Lane()
        self.activity = activity or InferenceActivity()
        self.selection = SimpleNamespace(
            manifest=SimpleNamespace(
                backend="mmdetection",
                model_id="model-a",
                class_vocabulary=VOCABULARY,
            ),
            profile=SimpleNamespace(profile_id="profile-a"),
            runtime_platform_variants={
                variant: SimpleNamespace(
                    status=(
                        "qualified-hardware"
                        if variant.endswith("-cuda")
                        else "qualified-hosted-cpu"
                    )
                )
                for variant in (
                    "windows-x86_64-cpu",
                    "windows-x86_64-cuda",
                    "linux-x86_64-cpu",
                    "linux-x86_64-cuda",
                )
            },
            runtime_release_locks={
                variant: SimpleNamespace(
                    status="qualified-offline-lock"
                )
                for variant in (
                    "windows-x86_64-cpu",
                    "windows-x86_64-cuda",
                    "linux-x86_64-cpu",
                    "linux-x86_64-cuda",
                )
            },
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

        effective_profile = (
            deployment_profile
            if deployment_profile is not None
            else ("P3" if production_mode else None)
        )

        def load_deployment_profile(profile_id, path):
            del path
            contracts = {
                "P1": SimpleNamespace(
                    profile_id="P1",
                    runtime_variant="windows-x86_64-cuda",
                    requires_cuda=True,
                    qualification_gates=frozenset({
                        "windows-x86_64-cuda",
                        "windows-offline-install",
                        "cctv-quality-baseline",
                    }),
                ),
                "P2": SimpleNamespace(
                    profile_id="P2",
                    runtime_variant="linux-x86_64-cuda",
                    requires_cuda=True,
                    qualification_gates=frozenset({
                        "linux-x86_64-cuda",
                        "linux-offline-install",
                        "cctv-quality-baseline",
                        "linux-nvidia-recovery-performance",
                    }),
                ),
                "P3": SimpleNamespace(
                    profile_id="P3",
                    runtime_variant="windows-x86_64-cpu",
                    requires_cuda=False,
                    qualification_gates=frozenset({
                        "windows-x86_64-cpu",
                        "windows-offline-install",
                        "cctv-quality-baseline",
                    }),
                ),
            }
            return contracts[profile_id], "f" * 64

        self.supervisor = module.RuntimeSupervisor(
            lane=self.lane,
            activity=self.activity,
            model_root=SimpleNamespace(),
            manifest_path=SimpleNamespace(),
            profile_path=SimpleNamespace(),
            runtime_profile_path=SimpleNamespace(),
            qualification_path=SimpleNamespace(),
            deployment_profile_policy_path=Path("profiles.json"),
            deployment_profile=effective_profile,
            device_policy=device_policy,
            device_resolution_reason=device_resolution_reason,
            device_index=2,
            production_mode=production_mode,
            inference_watchdog_seconds=inference_watchdog_seconds,
            watchdog_grace_seconds=watchdog_grace_seconds,
            watchdog_poll_seconds=watchdog_poll_seconds,
            build_id="build-a",
            commit_sha="a" * 40,
            release_verifier=verify,
            runtime_factory=make_runtime,
            provenance_builder=make_provenance,
            gpu_identity_provider=lambda device: None,
            cuda_availability_provider=lambda index: cuda_available,
            deployment_profile_loader=load_deployment_profile,
            **(
                {"monotonic_clock": monotonic_clock}
                if monotonic_clock is not None
                else {}
            ),
            **(
                {"fatal_terminator": fatal_terminator}
                if fatal_terminator is not None
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
        assert production.verify_calls[0]["required_profile"] == "P3"
        assert (
            production.verify_calls[0]["required_runtime_variant"]
            == "windows-x86_64-cpu"
        )
        assert (
            production.verify_calls[0][
                "required_deployment_profile_policy_sha256"
            ]
            == "f" * 64
        )
        assert production_auto.events == []
        assert production_auto.supervisor.state is production_auto.module.RuntimeState.UNAVAILABLE
        assert (
            production_auto.supervisor.unavailable_reason
            == "production_device_policy_profile_mismatch"
        )

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


def test_startup_warmup_hang_is_bounded_by_process_watchdog() -> None:
    async def scenario() -> None:
        started = threading.Event()
        release = threading.Event()
        activity = InferenceActivity()
        runtime = _BlockingWarmupRuntime(
            "startup-hang",
            activity=activity,
            started=started,
            release=release,
        )
        lane = VisionExecutionLane()
        fatal_codes: list[int] = []

        def terminator(code: int) -> None:
            fatal_codes.append(code)
            raise _LifecycleFatalSentinel("startup-watchdog")

        harness = _Harness(
            runtimes=[runtime],
            activity=activity,
            lane=lane,
            inference_watchdog_seconds=0.01,
            watchdog_grace_seconds=0.01,
            watchdog_poll_seconds=0.001,
            fatal_terminator=terminator,
        )

        try:
            with pytest.raises(_LifecycleFatalSentinel, match="startup-watchdog"):
                await harness.supervisor.start()
        finally:
            release.set()
            await lane.close()

        assert started.is_set() is True
        assert fatal_codes == [70]
        assert harness.supervisor.fatal_termination_active is True
        assert runtime.close_calls == 0
        with pytest.raises(harness.module.RuntimeNotReadyError):
            _ = harness.supervisor.runtime

    asyncio.run(scenario())


def test_recovery_warmup_hang_is_bounded_by_process_watchdog() -> None:
    async def scenario() -> None:
        started = threading.Event()
        release = threading.Event()
        activity = InferenceActivity()
        runtime_a = _Runtime("a")
        runtime_b = _BlockingWarmupRuntime(
            "recovery-hang",
            activity=activity,
            started=started,
            release=release,
        )
        lane = VisionExecutionLane()
        fatal_codes: list[int] = []

        def terminator(code: int) -> None:
            fatal_codes.append(code)
            raise _LifecycleFatalSentinel("recovery-watchdog")

        harness = _Harness(
            runtimes=[runtime_a, runtime_b],
            activity=activity,
            lane=lane,
            inference_watchdog_seconds=0.01,
            watchdog_grace_seconds=0.01,
            watchdog_poll_seconds=0.001,
            fatal_terminator=terminator,
        )
        await harness.supervisor.start()
        harness.supervisor.report_processing_failure(GpuOutOfMemoryError("oom"))

        try:
            with pytest.raises(_LifecycleFatalSentinel, match="recovery-watchdog"):
                await harness.supervisor.recover_if_required()
        finally:
            release.set()
            await lane.close()

        assert started.is_set() is True
        assert fatal_codes == [70]
        assert harness.supervisor.fatal_termination_active is True
        assert runtime_a.close_calls == 1
        assert runtime_b.close_calls == 0
        with pytest.raises(harness.module.RuntimeNotReadyError):
            _ = harness.supervisor.runtime

    asyncio.run(scenario())



def test_watchdog_snapshot_is_one_coherent_runtime_observation() -> None:
    observation = [129.5]
    activity = InferenceActivity(monotonic_clock=lambda: 100.0)
    activity.mark_started()
    harness = _Harness(
        activity=activity,
        monotonic_clock=lambda: observation[0],
        inference_watchdog_seconds=30.0,
    )

    before = harness.supervisor.watchdog_snapshot()

    assert before.observed_monotonic == 129.5
    assert before.active is True
    assert before.started_monotonic == 100.0
    assert before.elapsed_seconds == pytest.approx(29.5)
    assert before.completed_count == 0
    assert before.threshold_seconds == 30.0
    assert before.expired is False
    assert before.device is None

    observation[0] = 130.0
    expired = harness.supervisor.watchdog_snapshot()

    assert expired.elapsed_seconds == pytest.approx(30.0)
    assert expired.expired is True
    assert harness.supervisor.watchdog_expired() is True


def test_watchdog_snapshot_has_no_elapsed_duration_while_inactive() -> None:
    harness = _Harness(
        activity=InferenceActivity(monotonic_clock=lambda: 100.0),
        monotonic_clock=lambda: 1_000.0,
        inference_watchdog_seconds=30.0,
    )

    snapshot = harness.supervisor.watchdog_snapshot()

    assert snapshot.active is False
    assert snapshot.started_monotonic is None
    assert snapshot.elapsed_seconds is None
    assert snapshot.expired is False



def test_runtime_watchdog_snapshot_rejects_incoherent_inactive_state() -> None:
    with pytest.raises(ValueError, match="runtime_watchdog_inactive_expired_invalid"):
        RuntimeWatchdogSnapshot(
            observed_monotonic=10.0,
            active=False,
            started_monotonic=None,
            elapsed_seconds=None,
            completed_count=0,
            threshold_seconds=5.0,
            expired=True,
            device=None,
            model_id=None,
            runtime_variant=None,
            pipeline_profile_id=None,
            model_manifest_sha256=None,
            checkpoint_sha256=None,
            resolved_config_sha256=None,
            pipeline_profile_sha256=None,
            runtime_profile_sha256=None,
        )


def test_runtime_watchdog_snapshot_rejects_expiry_flag_mismatch() -> None:
    with pytest.raises(ValueError, match="runtime_watchdog_expiry_state_invalid"):
        RuntimeWatchdogSnapshot(
            observed_monotonic=20.0,
            active=True,
            started_monotonic=10.0,
            elapsed_seconds=10.0,
            completed_count=0,
            threshold_seconds=5.0,
            expired=False,
            device="cpu",
            model_id=None,
            runtime_variant=None,
            pipeline_profile_id=None,
            model_manifest_sha256=None,
            checkpoint_sha256=None,
            resolved_config_sha256=None,
            pipeline_profile_sha256=None,
            runtime_profile_sha256=None,
        )


def test_development_auto_prefers_qualified_available_windows_gpu(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        module = _module()
        monkeypatch.setattr(module.platform, "system", lambda: "Windows")
        monkeypatch.setattr(module.platform, "machine", lambda: "AMD64")

        runtime = _Runtime("cuda", device="cuda:2")
        harness = _Harness(
            runtimes=[runtime],
            device_policy="auto",
            cuda_available=True,
        )

        await harness.supervisor.start()

        assert harness.supervisor.state is module.RuntimeState.READY
        assert harness.factory_calls[0][1] == "cuda:2"

    asyncio.run(scenario())


def test_development_auto_falls_back_to_cpu_when_cuda_unavailable(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        module = _module()
        monkeypatch.setattr(module.platform, "system", lambda: "Windows")
        monkeypatch.setattr(module.platform, "machine", lambda: "AMD64")

        harness = _Harness(
            device_policy="auto",
            cuda_available=False,
        )
        await harness.supervisor.start()

        assert harness.supervisor.state is module.RuntimeState.READY
        assert harness.factory_calls[0][1] == "cpu"

    asyncio.run(scenario())


def test_development_auto_falls_back_when_cuda_runtime_is_not_qualified(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        module = _module()
        monkeypatch.setattr(module.platform, "system", lambda: "Windows")
        monkeypatch.setattr(module.platform, "machine", lambda: "AMD64")

        harness = _Harness(
            device_policy="auto",
            cuda_available=True,
        )
        harness.selection.runtime_platform_variants[
            "windows-x86_64-cuda"
        ].status = "pending-hardware-qualification"

        await harness.supervisor.start()

        assert harness.supervisor.state is module.RuntimeState.READY
        assert harness.factory_calls[0][1] == "cpu"

    asyncio.run(scenario())


def test_p1_production_binds_windows_cuda_profile_before_runtime(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        module = _module()
        monkeypatch.setattr(module.platform, "system", lambda: "Windows")
        monkeypatch.setattr(module.platform, "machine", lambda: "AMD64")

        runtime = _Runtime("cuda", device="cuda:2")
        harness = _Harness(
            runtimes=[runtime],
            production_mode=True,
            deployment_profile="P1",
            device_policy="cuda",
        )
        await harness.supervisor.start()

        assert harness.supervisor.state is module.RuntimeState.READY
        call = harness.verify_calls[0]
        assert call["required_profile"] == "P1"
        assert call["required_runtime_variant"] == "windows-x86_64-cuda"
        assert (
            call["required_deployment_profile_policy_sha256"]
            == "f" * 64
        )
        assert harness.factory_calls[0][1] == "cuda:2"

    asyncio.run(scenario())


def test_split_linux_profile_cannot_run_on_windows_cuda_host(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        module = _module()
        monkeypatch.setattr(module.platform, "system", lambda: "Windows")
        monkeypatch.setattr(module.platform, "machine", lambda: "AMD64")

        harness = _Harness(
            runtimes=[_Runtime("cuda", device="cuda:2")],
            production_mode=True,
            deployment_profile="P2",
            device_policy="cuda",
        )
        await harness.supervisor.start()

        assert harness.supervisor.state is module.RuntimeState.UNAVAILABLE
        assert (
            harness.supervisor.unavailable_reason
            == "production_deployment_profile_runtime_variant_mismatch"
        )
        assert harness.factory_calls == []

    asyncio.run(scenario())


def test_development_auto_records_cuda_selection_reason(monkeypatch) -> None:
    """An Auto selection must be explainable from provenance alone."""

    async def scenario() -> None:
        module = _module()
        monkeypatch.setattr(module.platform, "system", lambda: "Windows")
        monkeypatch.setattr(module.platform, "machine", lambda: "AMD64")

        runtime = _Runtime("cuda", device="cuda:2")
        harness = _Harness(
            runtimes=[runtime],
            device_policy="auto",
            cuda_available=True,
        )

        await harness.supervisor.start()

        assert harness.provenance_calls[0][
            "device_resolution_reason"
        ] == "cuda_selected"

    asyncio.run(scenario())


def test_development_auto_records_cpu_fallback_reason(monkeypatch) -> None:
    async def scenario() -> None:
        module = _module()
        monkeypatch.setattr(module.platform, "system", lambda: "Windows")
        monkeypatch.setattr(module.platform, "machine", lambda: "AMD64")

        harness = _Harness(
            device_policy="auto",
            cuda_available=False,
        )

        await harness.supervisor.start()

        assert harness.provenance_calls[0][
            "device_resolution_reason"
        ] == "cuda_device_unavailable"

    asyncio.run(scenario())


def test_development_auto_records_undeclared_cuda_runtime_reason(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        module = _module()
        monkeypatch.setattr(module.platform, "system", lambda: "Windows")
        monkeypatch.setattr(module.platform, "machine", lambda: "AMD64")

        harness = _Harness(
            device_policy="auto",
            cuda_available=True,
        )
        harness.selection.runtime_platform_variants[
            "windows-x86_64-cuda"
        ].status = "pending-hardware-qualification"

        await harness.supervisor.start()

        assert harness.provenance_calls[0][
            "device_resolution_reason"
        ] == "cuda_pack_not_declared"

    asyncio.run(scenario())


def test_development_auto_records_probe_failure_reason(monkeypatch) -> None:
    async def scenario() -> None:
        module = _module()
        monkeypatch.setattr(module.platform, "system", lambda: "Windows")
        monkeypatch.setattr(module.platform, "machine", lambda: "AMD64")

        def _explode(_index: int) -> bool:
            raise RuntimeError("probe exploded")

        harness = _Harness(
            device_policy="auto",
            cuda_available=False,
        )
        harness.supervisor._cuda_availability_provider = _explode

        await harness.supervisor.start()

        assert harness.provenance_calls[0][
            "device_resolution_reason"
        ] == "cuda_driver_probe_failed"

    asyncio.run(scenario())


def test_explicit_policy_preserves_launcher_resolution_reason(
    monkeypatch,
) -> None:
    """A reason resolved before Python started must survive unchanged."""

    async def scenario() -> None:
        module = _module()
        monkeypatch.setattr(module.platform, "system", lambda: "Windows")
        monkeypatch.setattr(module.platform, "machine", lambda: "AMD64")

        harness = _Harness(
            device_policy="cpu",
            device_resolution_reason="cuda_pack_absent",
        )

        await harness.supervisor.start()

        assert harness.provenance_calls[0][
            "device_resolution_reason"
        ] == "cuda_pack_absent"

    asyncio.run(scenario())
