"""The exit-70 diagnostic must be trustworthy before it is trusted on the host.

Everything GPU-bound sits behind a seam, so what is pinned here is the logic
that decides what the evidence *means*: which frames are selected, that every
event is on disk before the next stage runs, that the sentinel reports and then
terminates in that order and only on a genuinely open activity, that the timing
shim leaves `infer()` itself untouched, and that the tool cannot reach the
checkpoint except through the runtime's own restricted scope.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from mavi_vision.runtime.activity import InferenceActivity


TOOLS = Path(__file__).resolve().parents[3] / "tools" / "vision"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load("trace_inference_window")


def _frame(number: int, offset_ms: int, shape=(8, 12, 3)):
    return SimpleNamespace(
        source_frame_number=number,
        offset_ms=offset_ms,
        image=np.zeros(shape, dtype=np.uint8),
    )


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------------------
# Frame selection
# ---------------------------------------------------------------------------


def test_window_mode_selects_only_the_inclusive_window_and_stops_after_it() -> None:
    plan = MODULE.FramePlan(mode="window", start_ms=108_000, end_ms=122_000)
    frames = [_frame(i, off) for i, off in enumerate((0, 107_999, 108_000, 115_000, 122_000, 122_001, 200_000))]

    result = list(MODULE.select_frames(frames, plan))

    assert [(f.offset_ms, sel) for f, sel in result] == [
        (0, False),
        (107_999, False),
        (108_000, True),
        (115_000, True),
        (122_000, True),
    ]


def test_sequential_mode_selects_every_frame_from_the_start_until_the_bound() -> None:
    plan = MODULE.FramePlan(mode="sequential", start_ms=0, end_ms=122_000)
    frames = [_frame(i, off) for i, off in enumerate((0, 40, 80, 122_000, 122_040))]

    result = list(MODULE.select_frames(frames, plan))

    assert all(sel for _, sel in result)
    assert [f.offset_ms for f, _ in result] == [0, 40, 80, 122_000]


def test_sequential_mode_does_not_stop_short_of_the_bound() -> None:
    """Cumulative degradation needs the thousands of calls *before* 122 s."""
    plan = MODULE.FramePlan(mode="sequential", start_ms=0, end_ms=122_000)
    frames = [_frame(i, i * 33) for i in range(4_000)]

    selected = [f for f, sel in MODULE.select_frames(frames, plan) if sel]

    assert len(selected) == 3_697
    assert selected[-1].offset_ms <= 122_000


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"mode": "window", "start_ms": 122_000, "end_ms": 108_000}, "trace_window_inverted"),
        ({"mode": "window", "start_ms": -1, "end_ms": 10}, "trace_window_negative"),
        ({"mode": "sampled", "start_ms": 0, "end_ms": 10}, "trace_mode_invalid"),
    ],
)
def test_an_invalid_plan_is_refused(kwargs, code) -> None:
    with pytest.raises(MODULE.TraceError) as excinfo:
        MODULE.FramePlan(**kwargs)
    assert excinfo.value.code == code


# ---------------------------------------------------------------------------
# Event log durability
# ---------------------------------------------------------------------------


def test_each_event_is_on_disk_before_emit_returns(tmp_path: Path) -> None:
    """The last line before a kill is the evidence; it must never sit in a buffer."""
    log = MODULE.EventLog(tmp_path / "trace.jsonl")
    try:
        log.emit("enter", frame=3451, offsetMs=115_000, stage="enter")
        # Read while the handle is still open and unclosed.
        lines = _read(tmp_path / "trace.jsonl")
        assert len(lines) == 1
        assert lines[0]["event"] == "enter"
        assert lines[0]["frame"] == 3451
        log.emit("complete", frame=3451)
        assert len(_read(tmp_path / "trace.jsonl")) == 2
    finally:
        log.close()


def test_every_emit_fsyncs_the_log_descriptor(tmp_path: Path, monkeypatch) -> None:
    """Durability across a crash is the property; fsync is its only observable proxy.

    `flush()` already makes bytes visible to another reader on this OS, so the
    read-back test above cannot tell flush from fsync -- a mutation that drops
    the fsync survives it. What a test *can* pin is the contract: one fsync of
    the log's own descriptor per emitted event, after the write.
    """
    synced: list[int] = []
    real_fsync = MODULE.os.fsync

    def spy(fd: int) -> None:
        synced.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(MODULE.os, "fsync", spy)
    log = MODULE.EventLog(tmp_path / "trace.jsonl")
    try:
        fd = log._handle.fileno()
        log.emit("enter", frame=1)
        log.emit("complete", frame=1)
        log.emit("summary")
    finally:
        log.close()

    assert synced == [fd, fd, fd]
    assert log.count == 3


def test_the_log_refuses_to_overwrite_an_existing_trace(tmp_path: Path) -> None:
    target = tmp_path / "trace.jsonl"
    target.write_text("{}\n")
    with pytest.raises(MODULE.TraceError) as excinfo:
        MODULE.EventLog(target)
    assert excinfo.value.code == "trace_output_exists"
    assert target.read_text() == "{}\n"


def test_events_refuse_non_finite_numbers(tmp_path: Path) -> None:
    log = MODULE.EventLog(tmp_path / "trace.jsonl")
    try:
        with pytest.raises(ValueError):
            log.emit("complete", totalSeconds=float("nan"))
    finally:
        log.close()


# ---------------------------------------------------------------------------
# Hang sentinel
# ---------------------------------------------------------------------------


class _Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def _sentinel(tmp_path: Path, activity, clock, *, report=60.0, exit_=150.0):
    log = MODULE.EventLog(tmp_path / "trace.jsonl")
    dumps: list[str] = []
    exits: list[int] = []

    def dump(handle) -> None:
        handle.write("FAKE TRACEBACK\n")
        dumps.append("dumped")

    def terminator(code: int):
        exits.append(code)

    sentinel = MODULE.HangSentinel(
        activity,
        log,
        report_seconds=report,
        exit_seconds=exit_,
        traceback_path=tmp_path / "trace.jsonl.tracebacks.txt",
        current=lambda: {"frame": 3451, "offsetMs": 115_000, "stage": "convert_prediction"},
        monotonic=clock,
        dump=dump,
        terminator=terminator,
    )
    return sentinel, log, dumps, exits


def test_the_sentinel_stays_quiet_while_inference_is_healthy(tmp_path: Path) -> None:
    clock = _Clock()
    activity = InferenceActivity(monotonic_clock=clock)
    sentinel, log, dumps, exits = _sentinel(tmp_path, activity, clock)
    try:
        assert sentinel.check_once() is False          # inactive
        activity.mark_started()
        clock.now += 59.9
        assert sentinel.check_once() is False          # open but under threshold
        activity.mark_completed()
        assert sentinel.check_once() is False
    finally:
        log.close()
    assert dumps == [] and exits == []
    assert [e["event"] for e in _read(tmp_path / "trace.jsonl")] == []


def test_the_sentinel_reports_once_then_terminates_with_its_own_code(tmp_path: Path) -> None:
    """Report first, dump stacks, terminate later -- and the code is 3, never 70."""
    clock = _Clock()
    activity = InferenceActivity(monotonic_clock=clock)
    sentinel, log, dumps, exits = _sentinel(tmp_path, activity, clock)
    try:
        activity.mark_started()
        clock.now += 60.0
        assert sentinel.check_once() is False
        clock.now += 10.0
        assert sentinel.check_once() is False          # no duplicate report
        clock.now += 80.0                               # 150 s open
        assert sentinel.check_once() is True
    finally:
        log.close()

    events = _read(tmp_path / "trace.jsonl")
    assert [e["event"] for e in events] == ["hang", "hang_terminate"]
    assert events[0]["frame"] == 3451
    assert events[0]["stage"] == "convert_prediction"
    assert events[0]["elapsedSeconds"] == 60.0
    assert events[1]["exitCode"] == MODULE.HANG_EXIT_CODE == 3
    assert exits == [3]
    assert len(dumps) == 2
    tracebacks = (tmp_path / "trace.jsonl.tracebacks.txt").read_text()
    assert tracebacks.count("FAKE TRACEBACK") == 2


def test_a_new_inference_after_a_report_is_reported_again(tmp_path: Path) -> None:
    clock = _Clock()
    activity = InferenceActivity(monotonic_clock=clock)
    sentinel, log, dumps, exits = _sentinel(tmp_path, activity, clock, report=10.0, exit_=1000.0)
    try:
        activity.mark_started(); clock.now += 10; sentinel.check_once(); activity.mark_completed()
        activity.mark_started(); clock.now += 10; sentinel.check_once(); activity.mark_completed()
    finally:
        log.close()
    assert [e["event"] for e in _read(tmp_path / "trace.jsonl")] == ["hang", "hang"]
    assert exits == []


def test_hang_thresholds_must_be_ordered(tmp_path: Path) -> None:
    log = MODULE.EventLog(tmp_path / "t.jsonl")
    try:
        with pytest.raises(MODULE.TraceError) as excinfo:
            MODULE.HangSentinel(
                InferenceActivity(), log, report_seconds=150, exit_seconds=60,
                traceback_path=tmp_path / "x", current=dict,
            )
        assert excinfo.value.code == "trace_hang_thresholds_invalid"
    finally:
        log.close()


# ---------------------------------------------------------------------------
# Timing shim and the real infer() path
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _Bindings:
    inference_detector: object
    cuda_empty_cache: object = None


class _FakeRuntime:
    """Enough of MMDetectionRuntime for infer() to be exercised end to end.

    The important property mirrored here is that `infer()` *itself* calls
    `self._bindings.inference_detector` and then converts -- so a shim that
    swaps the binding changes what is timed, not what runs.
    """

    def __init__(self, activity, *, detections=2, fail_at_frame=None, convert_error=False):
        self._activity = activity
        self.calls = 0
        self.convert_calls = 0
        self._detections = detections
        self._fail_at = fail_at_frame
        self._convert_error = convert_error
        self.metadata = SimpleNamespace(device="cuda:0", model_id="rtmdet", versions={})
        self._bindings = _Bindings(inference_detector=self._detect)

    def _detect(self, model, image):
        self.calls += 1
        if self._fail_at is not None and self.calls == self._fail_at:
            raise RuntimeError("CUDA error: device-side assert triggered")
        return ("prediction", image.shape)

    def _convert(self, prediction):
        self.convert_calls += 1
        if self._convert_error:
            raise ValueError("mmdetection_prediction_invalid")
        return tuple(range(self._detections))

    def infer(self, image):
        self._activity.mark_started()
        try:
            prediction = self._bindings.inference_detector(None, image)
            return self._convert(prediction)
        finally:
            self._activity.mark_completed()


def test_the_shim_times_the_detector_call_and_leaves_infer_intact() -> None:
    activity = InferenceActivity()
    runtime = _FakeRuntime(activity)
    timer = MODULE.StageTimer()
    clock = _Clock()
    synced: list[str] = []

    def synchronize() -> None:
        clock.now += 0.25
        synced.append("sync")

    original_detect = runtime._bindings.inference_detector

    def slow_detect(model, image):
        clock.now += 0.12
        return original_detect(model, image)

    runtime._bindings = dataclasses.replace(runtime._bindings, inference_detector=slow_detect)
    MODULE.instrument_runtime(runtime, timer, synchronize=synchronize, monotonic=clock)

    result = runtime.infer(np.zeros((8, 12, 3), dtype=np.uint8))

    assert result == (0, 1)
    assert runtime.calls == 1 and runtime.convert_calls == 1
    assert synced == ["sync"]
    assert timer.detect_seconds == pytest.approx(0.12)
    assert timer.sync_seconds == pytest.approx(0.25)
    assert timer.stage == "convert_prediction"
    assert activity.snapshot().completed_count == 1
    assert activity.snapshot().active is False


def test_the_shim_without_explicit_sync_records_no_sync_time() -> None:
    runtime = _FakeRuntime(InferenceActivity())
    timer = MODULE.StageTimer()
    MODULE.instrument_runtime(runtime, timer, synchronize=None)
    runtime.infer(np.zeros((8, 12, 3), dtype=np.uint8))
    assert timer.detect_seconds is not None
    assert timer.sync_seconds is None


# ---------------------------------------------------------------------------
# run_trace end to end over a fake runtime
# ---------------------------------------------------------------------------


def _trace(tmp_path: Path, runtime, frames, plan, **kwargs):
    activity = runtime._activity
    log = MODULE.EventLog(tmp_path / "trace.jsonl")
    timer = MODULE.StageTimer()
    MODULE.instrument_runtime(runtime, timer, synchronize=None)
    state: dict = {}
    try:
        summary = MODULE.run_trace(
            frames=frames, plan=plan, runtime=runtime, activity=activity, log=log,
            timer=timer, cuda_stats=lambda: {"cudaAllocatedBytes": 97}, current_state=state, **kwargs,
        )
    finally:
        log.close()
    return summary, _read(tmp_path / "trace.jsonl"), state


def test_run_trace_logs_enter_then_complete_per_selected_frame(tmp_path: Path) -> None:
    runtime = _FakeRuntime(InferenceActivity(), detections=3)
    frames = [_frame(i, off) for i, off in enumerate((0, 108_000, 115_000, 122_000, 130_000))]
    plan = MODULE.FramePlan(mode="window", start_ms=108_000, end_ms=122_000)

    summary, events, state = _trace(tmp_path, runtime, frames, plan)

    assert [e["event"] for e in events] == ["enter", "complete"] * 3 + ["summary"]
    assert [e["frame"] for e in events if e["event"] == "enter"] == [1, 2, 3]
    complete = [e for e in events if e["event"] == "complete"]
    assert all(e["detections"] == 3 for e in complete)
    assert [e["completedCountAfter"] for e in complete] == [1, 2, 3]
    assert all(e["cudaAllocatedBytes"] == 97 for e in complete)
    assert all(e["stageAtExit"] == "convert_prediction" for e in complete)
    assert summary["inferredFrames"] == 3
    assert summary["skippedFrames"] == 1
    assert summary["decodedFrames"] == 4          # stopped before 130 s
    assert summary["detectionsTotal"] == 9
    assert state["stage"] == "finished"


def test_the_enter_event_precedes_the_call_so_a_kill_leaves_the_frame_named(tmp_path: Path) -> None:
    """If infer() never returns, the last durable line must already say which frame."""
    activity = InferenceActivity()
    runtime = _FakeRuntime(activity)
    log = MODULE.EventLog(tmp_path / "trace.jsonl")
    timer = MODULE.StageTimer()
    seen_at_call: list[list[dict]] = []

    def observing_detect(model, image):
        seen_at_call.append(_read(tmp_path / "trace.jsonl"))
        return ("prediction",)

    runtime._bindings = dataclasses.replace(runtime._bindings, inference_detector=observing_detect)
    MODULE.instrument_runtime(runtime, timer, synchronize=None)
    try:
        MODULE.run_trace(
            frames=[_frame(3451, 115_000)],
            plan=MODULE.FramePlan(mode="window", start_ms=0, end_ms=200_000),
            runtime=runtime, activity=activity, log=log, timer=timer, cuda_stats=dict,
        )
    finally:
        log.close()

    on_disk_during_call = seen_at_call[0]
    assert on_disk_during_call[-1]["event"] == "enter"
    assert on_disk_during_call[-1]["frame"] == 3451
    assert on_disk_during_call[-1]["offsetMs"] == 115_000


def test_a_backend_error_is_recorded_with_its_stage_and_stops_the_trace(tmp_path: Path) -> None:
    runtime = _FakeRuntime(InferenceActivity(), fail_at_frame=2)
    frames = [_frame(i, 1_000 * i) for i in range(5)]
    plan = MODULE.FramePlan(mode="sequential", start_ms=0, end_ms=10_000)

    summary, events, state = _trace(tmp_path, runtime, frames, plan)

    kinds = [e["event"] for e in events]
    assert kinds == ["enter", "complete", "enter", "error", "summary"]
    error = events[3]
    assert error["error"]["type"] == "RuntimeError"
    assert "device-side assert" in error["error"]["code"]
    assert error["stageAtExit"] == "inference_detector"
    assert summary["inferredFrames"] == 1
    assert state["stage"] == "finished"
    # The activity was released by infer()'s finally even on failure.
    assert runtime._activity.snapshot().active is False


def test_a_conversion_error_is_attributed_to_the_conversion_stage(tmp_path: Path) -> None:
    runtime = _FakeRuntime(InferenceActivity(), convert_error=True)
    summary, events, _ = _trace(
        tmp_path, runtime, [_frame(0, 0)],
        MODULE.FramePlan(mode="sequential", start_ms=0, end_ms=1_000),
    )
    error = next(e for e in events if e["event"] == "error")
    assert error["stageAtExit"] == "convert_prediction"
    assert error["error"]["type"] == "ValueError"


def test_max_frames_bounds_the_run(tmp_path: Path) -> None:
    runtime = _FakeRuntime(InferenceActivity())
    frames = [_frame(i, 100 * i) for i in range(50)]
    summary, events, _ = _trace(
        tmp_path, runtime, frames,
        MODULE.FramePlan(mode="sequential", start_ms=0, end_ms=100_000), max_frames=7,
    )
    assert summary["inferredFrames"] == 7
    assert runtime.calls == 7


def test_the_slowest_frame_is_summarised(tmp_path: Path) -> None:
    activity = InferenceActivity()
    runtime = _FakeRuntime(activity)
    clock = _Clock()
    durations = iter([0.1, 0.9, 0.2])
    original = runtime._bindings.inference_detector

    def variable(model, image):
        clock.now += next(durations)
        return original(model, image)

    runtime._bindings = dataclasses.replace(runtime._bindings, inference_detector=variable)
    log = MODULE.EventLog(tmp_path / "trace.jsonl")
    timer = MODULE.StageTimer()
    MODULE.instrument_runtime(runtime, timer, synchronize=None, monotonic=clock)
    try:
        summary = MODULE.run_trace(
            frames=[_frame(i, i * 40) for i in range(3)],
            plan=MODULE.FramePlan(mode="sequential", start_ms=0, end_ms=1_000),
            runtime=runtime, activity=activity, log=log, timer=timer, cuda_stats=dict, monotonic=clock,
        )
    finally:
        log.close()
    assert summary["slowest"]["frame"] == 1
    assert summary["slowest"]["totalSeconds"] == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# CLI contract
# ---------------------------------------------------------------------------


def test_cli_refuses_a_missing_source(tmp_path: Path, capsys) -> None:
    code = MODULE.main(["--source", str(tmp_path / "nope.mp4"), "--output", str(tmp_path / "t.jsonl")])
    assert code == 2
    assert json.loads(capsys.readouterr().out)["code"] == "trace_source_missing"
    assert not (tmp_path / "t.jsonl").exists()


def test_cli_refuses_a_source_that_does_not_match_the_expected_hash(tmp_path: Path, capsys) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"not really video")
    code = MODULE.main([
        "--source", str(source), "--output", str(tmp_path / "t.jsonl"),
        "--expected-sha256", "0" * 64,
    ])
    assert code == 2
    assert json.loads(capsys.readouterr().out)["code"] == "trace_source_sha256_mismatch"


def test_cli_refuses_an_existing_output_before_touching_the_gpu(tmp_path: Path, capsys) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"x")
    out = tmp_path / "t.jsonl"
    out.write_text("keep\n")
    code = MODULE.main(["--source", str(source), "--output", str(out)])
    assert code == 2
    assert json.loads(capsys.readouterr().out)["code"] == "trace_output_exists"
    assert out.read_text() == "keep\n"


def test_cli_refuses_an_inverted_window(tmp_path: Path, capsys) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"x")
    code = MODULE.main([
        "--source", str(source), "--output", str(tmp_path / "t.jsonl"),
        "--window-start-seconds", "122", "--window-end-seconds", "108",
    ])
    assert code == 2
    assert json.loads(capsys.readouterr().out)["code"] == "trace_window_inverted"


def test_cli_defaults_name_the_failing_window_and_the_supervisor_defaults() -> None:
    args = MODULE.build_parser().parse_args(["--source", "s", "--output", "o"])
    assert args.mode == "window"
    assert (args.window_start_seconds, args.window_end_seconds) == (108.0, 122.0)
    assert args.until_seconds == 122.0
    assert args.device == "cuda:0"
    assert args.no_warmup is False and args.no_explicit_sync is False
    # Same artefact paths the worker resolves by default.
    from mavi_vision.common.settings import WorkerSettings

    fields = WorkerSettings.model_fields
    assert args.model_manifest == fields["model_manifest_path"].default
    assert args.pipeline_profile == fields["pipeline_profile_path"].default
    assert args.runtime_profile == fields["runtime_profile_path"].default
    assert args.qualification_record == fields["qualification_record_path"].default


# ---------------------------------------------------------------------------
# Security and fidelity of the runtime construction
# ---------------------------------------------------------------------------


def test_the_tool_never_loads_a_checkpoint_itself() -> None:
    """The only path to the weights is MMDetectionRuntime and its restricted scope."""
    source = (TOOLS / "trace_inference_window.py").read_text(encoding="utf-8")
    # Call-site syntax, so the docstring may *say* "never calls torch.load"
    # without tripping the guard that enforces it.
    assert "torch.load(" not in source
    assert "weights_only=" not in source
    assert "safe_globals(" not in source          # not re-declared here either
    assert "MMDetectionRuntime(selection, device=device, activity=activity)" in source


def test_the_selection_is_verified_the_way_the_supervisor_verifies_it() -> None:
    """Development host: allow_unverified=True, as `production_mode=False` yields."""
    source = (TOOLS / "trace_inference_window.py").read_text(encoding="utf-8")
    assert "verify_release_selection(" in source
    assert "allow_unverified=True" in source
    assert "required_runtime_variant" not in source   # that is the Production path


def test_the_hang_exit_code_is_not_the_worker_exit_code() -> None:
    assert MODULE.HANG_EXIT_CODE != 70
