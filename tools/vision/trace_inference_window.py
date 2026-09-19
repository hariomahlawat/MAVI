#!/usr/bin/env python3
"""Per-frame inference trace for isolating a watchdog exit-70 on the CUDA host.

C6.1's explicit-CUDA run died with fatal supervisor exit 70 at ~70% of
`2min.mp4`, frame 3451, ~115 s into the source. Exit 70 has exactly one
meaning: a single `InferenceActivity.mark_started()` was still open 135 s
later. That interval encloses precisely two calls in `MMDetectionRuntime.infer`
-- `bindings.inference_detector(...)` and `_convert_prediction(...)` -- and
nothing else in the worker can produce that exit code. The tracker, the
staging store and the heartbeat all run outside the activity.

The two calls are not equivalent stall sites. CUDA launches are asynchronous,
so wall-clock around `inference_detector` measures enqueue; the device-to-host
`.cpu()` inside `_convert_prediction` is where the stream is actually waited
on. A GPU-side stall therefore looks like a fast detector call followed by a
conversion that never returns. A diagnostic that calls the detector and does
not read the result back cannot see it -- which is why the 29-frame sampled
check that preceded this tool proved nothing about the failure.

So this tool runs the **real** path -- `MMDetectionRuntime.infer()`, built the
way the supervisor builds it, checkpoint loaded under the runtime's own
restricted `checkpoint_scope()` -- and times three things separately per frame:
the detector call, an explicit `torch.cuda.synchronize()`, and the conversion.
It records CUDA allocated/reserved/peak and the frame geometry, and it writes
every event to disk with flush-and-fsync **before** the next stage begins, so
if the process is killed mid-frame the last line names the frame and the stage
it died in.

A sentinel thread watches the same activity object the production watchdog
would. If an inference stays open past `--hang-report-seconds` it dumps every
thread's Python stack to a sibling file -- the one artefact that says *where*
a stuck lane is stuck -- and after `--hang-exit-seconds` terminates the
process with exit 3, distinct from the worker's 70 so nobody confuses the two.
The production 120 s / 15 s values are not read, not changed, not mirrored.

Two modes. `window` (default) decodes from the start but infers only frames
whose offset lies in [start, end]; use it to test the exact failing region
first. `sequential` infers every frame from the start until `--until-seconds`
through one runtime instance, so cumulative degradation over thousands of
sequential calls can be observed if the window alone is clean.

This is a Development diagnostic. It qualifies nothing, marks nothing
complete, and its output is external evidence, never committed.
"""

from __future__ import annotations

import argparse
import dataclasses
import faulthandler
import hashlib
import json
import os
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

for _candidate in (
    Path(__file__).resolve().parent,
    Path(__file__).resolve().parents[2] / "src" / "vision",
):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

SCHEMA_VERSION = "mavi-inference-window-trace-v1"

#: Exit code when the sentinel gives up on a hung inference. Deliberately not
#: 70: that code belongs to the worker's watchdog, and a diagnostic that
#: reproduced it would muddy the very incident record it exists to explain.
HANG_EXIT_CODE = 3

_MODES = ("window", "sequential")


class TraceError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


# ---------------------------------------------------------------------------
# Event log: every line on disk before the next stage runs
# ---------------------------------------------------------------------------


class EventLog:
    """Append-only JSONL with flush-and-fsync per event.

    The point of this tool is the *last* line it wrote before dying, so an
    event is not considered emitted until it is durable. `os.fsync` per event
    costs ~ms on an SSD and is the difference between a diagnostic and a wish.
    """

    def __init__(self, path: Path, *, monotonic: Callable[[], float] = time.monotonic) -> None:
        if path.exists():
            raise TraceError("trace_output_exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._handle = path.open("a", encoding="utf-8", newline="\n")
        self._lock = threading.Lock()
        self._monotonic = monotonic
        self._count = 0

    @property
    def path(self) -> Path:
        return self._path

    @property
    def count(self) -> int:
        return self._count

    def emit(self, event: str, **fields: Any) -> None:
        record = {
            "event": event,
            "monotonic": self._monotonic(),
            "wallUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **fields,
        }
        line = json.dumps(record, sort_keys=True, allow_nan=False) + "\n"
        with self._lock:
            self._handle.write(line)
            self._handle.flush()
            os.fsync(self._handle.fileno())
            self._count += 1

    def close(self) -> None:
        with self._lock:
            self._handle.close()


# ---------------------------------------------------------------------------
# Frame selection: which decoded frames get inferred
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FramePlan:
    mode: str
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        if self.mode not in _MODES:
            raise TraceError("trace_mode_invalid")
        if self.start_ms < 0 or self.end_ms < 0:
            raise TraceError("trace_window_negative")
        if self.end_ms < self.start_ms:
            raise TraceError("trace_window_inverted")

    def selects(self, offset_ms: int) -> bool:
        if self.mode == "window":
            return self.start_ms <= offset_ms <= self.end_ms
        return offset_ms <= self.end_ms

    def exhausted(self, offset_ms: int) -> bool:
        """True once no later frame can be selected, so decoding can stop."""
        return offset_ms > self.end_ms


def select_frames(frames: Iterable[Any], plan: FramePlan) -> Iterator[tuple[Any, bool]]:
    """Yield (frame, selected) in decode order; stop once the plan is exhausted.

    Decoding is always from the start because `iter_frames` is the production
    decoder and it does not seek -- and a seek would change decoder state
    relative to what the worker saw. Frames before a window are decoded and
    passed over, exactly as the worker would have decoded them.
    """
    for frame in frames:
        if plan.exhausted(frame.offset_ms):
            return
        yield frame, plan.selects(frame.offset_ms)


# ---------------------------------------------------------------------------
# Hang sentinel
# ---------------------------------------------------------------------------


class HangSentinel:
    """Watch the activity; on a stuck inference, dump stacks, then terminate.

    Mirrors what the production watchdog *observes* -- the same
    `InferenceActivity.is_hung` predicate -- without touching what it *does*.
    Its thresholds are its own arguments, not the worker's settings.
    """

    def __init__(
        self,
        activity: Any,
        log: EventLog,
        *,
        report_seconds: float,
        exit_seconds: float,
        traceback_path: Path,
        current: Callable[[], dict[str, Any]],
        monotonic: Callable[[], float] = time.monotonic,
        dump: Callable[[Any], None] | None = None,
        terminator: Callable[[int], NoReturn] = os._exit,
        poll_seconds: float = 0.5,
    ) -> None:
        if report_seconds <= 0 or exit_seconds <= report_seconds:
            raise TraceError("trace_hang_thresholds_invalid")
        self._activity = activity
        self._log = log
        self._report = report_seconds
        self._exit = exit_seconds
        self._traceback_path = traceback_path
        self._current = current
        self._monotonic = monotonic
        self._dump = dump if dump is not None else self._default_dump
        self._terminator = terminator
        self._poll = poll_seconds
        self._stop = threading.Event()
        self._reported_for: float | None = None
        self._thread = threading.Thread(
            target=self._run, name="mavi-trace-hang-sentinel", daemon=True
        )

    @staticmethod
    def _default_dump(handle: Any) -> None:
        faulthandler.dump_traceback(file=handle, all_threads=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def check_once(self) -> bool:
        """One poll. Returns True if the terminator was invoked (tests only)."""
        snapshot = self._activity.snapshot()
        if not snapshot.active or snapshot.started_monotonic is None:
            self._reported_for = None
            return False
        now = self._monotonic()
        elapsed = now - snapshot.started_monotonic
        if elapsed < self._report:
            return False
        if self._reported_for != snapshot.started_monotonic:
            self._reported_for = snapshot.started_monotonic
            self._log.emit(
                "hang",
                elapsedSeconds=round(elapsed, 3),
                completedCount=snapshot.completed_count,
                **self._current(),
            )
            self._write_tracebacks(elapsed)
        if elapsed >= self._exit:
            self._log.emit(
                "hang_terminate",
                elapsedSeconds=round(elapsed, 3),
                exitCode=HANG_EXIT_CODE,
                **self._current(),
            )
            self._write_tracebacks(elapsed)
            self._terminator(HANG_EXIT_CODE)
            return True
        return False

    def _write_tracebacks(self, elapsed: float) -> None:
        try:
            with self._traceback_path.open("a", encoding="utf-8") as handle:
                handle.write(f"\n=== hang after {elapsed:.1f}s ===\n")
                handle.flush()
                self._dump(handle)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            # The trace log is the primary evidence; a traceback write failing
            # must not stop the sentinel from terminating.
            pass

    def _run(self) -> None:
        while not self._stop.wait(self._poll):
            try:
                if self.check_once():
                    return
            except Exception:
                # A sentinel that dies silently is worse than none.
                self._log.emit("sentinel_error")


# ---------------------------------------------------------------------------
# Timing shim around the runtime's detector binding
# ---------------------------------------------------------------------------


@dataclass
class StageTimer:
    """Records the detector-call and explicit-sync durations of one infer()."""

    detect_seconds: float | None = None
    sync_seconds: float | None = None
    stage: str = "idle"

    def reset(self) -> None:
        self.detect_seconds = None
        self.sync_seconds = None
        self.stage = "idle"


def instrument_runtime(
    runtime: Any,
    timer: StageTimer,
    *,
    synchronize: Callable[[], None] | None,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Replace the runtime's `inference_detector` binding with a timed wrapper.

    `infer()` itself is not modified: the activity marking, the conversion, the
    error classification all run as shipped. The binding is a frozen dataclass,
    so it is swapped wholesale via `dataclasses.replace`, which also means any
    other field stays exactly as the runtime loaded it.
    """
    bindings = runtime._bindings
    original = bindings.inference_detector

    def timed(model: Any, image: Any) -> Any:
        timer.stage = "inference_detector"
        started = monotonic()
        prediction = original(model, image)
        timer.detect_seconds = monotonic() - started
        if synchronize is not None:
            timer.stage = "cuda_synchronize"
            started = monotonic()
            synchronize()
            timer.sync_seconds = monotonic() - started
        timer.stage = "convert_prediction"
        return prediction

    runtime._bindings = dataclasses.replace(bindings, inference_detector=timed)


# ---------------------------------------------------------------------------
# Runtime construction: the supervisor's Development path, exactly
# ---------------------------------------------------------------------------


def build_runtime(
    *,
    model_root: Path,
    manifest_path: Path,
    profile_path: Path,
    runtime_profile_path: Path,
    qualification_path: Path | None,
    device: str,
    activity: Any,
) -> Any:
    """Construct MMDetectionRuntime the way `_default_runtime_factory` does.

    The selection is verified with `allow_unverified=True`, which is what the
    supervisor passes when `production_mode` is false -- i.e. on the
    Development host this runs on. The checkpoint is loaded inside the
    runtime's own `bindings.checkpoint_scope()`; this tool never calls
    `torch.load` and has no path that could widen the reviewed globals.
    """
    from mavi_vision.runtime.mmdetection import MMDetectionRuntime
    from mavi_vision.runtime.qualification import verify_release_selection

    selection = verify_release_selection(
        model_root=model_root,
        manifest_path=manifest_path,
        profile_path=profile_path,
        runtime_profile_path=runtime_profile_path,
        qualification_path=qualification_path,
        allow_unverified=True,
    )
    return MMDetectionRuntime(selection, device=device, activity=activity)


def _cuda_stats(device: str) -> Callable[[], dict[str, int]]:
    if not device.startswith("cuda:"):
        return lambda: {}
    import torch

    index = int(device.split(":", 1)[1])

    def stats() -> dict[str, int]:
        return {
            "cudaAllocatedBytes": int(torch.cuda.memory_allocated(index)),
            "cudaReservedBytes": int(torch.cuda.memory_reserved(index)),
            "cudaMaxAllocatedBytes": int(torch.cuda.max_memory_allocated(index)),
            "cudaMaxReservedBytes": int(torch.cuda.max_memory_reserved(index)),
        }

    return stats


def _cuda_synchronize(device: str) -> Callable[[], None] | None:
    if not device.startswith("cuda:"):
        return None
    import torch

    index = int(device.split(":", 1)[1])
    return lambda: torch.cuda.synchronize(index)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# The trace
# ---------------------------------------------------------------------------


def run_trace(
    *,
    frames: Iterable[Any],
    plan: FramePlan,
    runtime: Any,
    activity: Any,
    log: EventLog,
    timer: StageTimer,
    cuda_stats: Callable[[], dict[str, int]],
    monotonic: Callable[[], float] = time.monotonic,
    max_frames: int | None = None,
    current_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Infer selected frames through `runtime.infer()`, logging each stage.

    `current_state` is shared with the sentinel so a hang report can name the
    frame and stage that was in flight. It is written *before* infer() is
    entered, which is the whole flush-before discipline in one line.
    """
    state = current_state if current_state is not None else {}
    inferred = 0
    decoded = 0
    skipped = 0
    detections_total = 0
    slowest: dict[str, Any] | None = None

    for frame, selected in select_frames(frames, plan):
        decoded += 1
        if not selected:
            skipped += 1
            continue
        if max_frames is not None and inferred >= max_frames:
            break

        shape = list(frame.image.shape)
        state.update(
            frame=frame.source_frame_number,
            offsetMs=frame.offset_ms,
            stage="enter",
        )
        timer.reset()
        entered = monotonic()
        log.emit(
            "enter",
            frame=frame.source_frame_number,
            offsetMs=frame.offset_ms,
            shape=shape,
            completedCountBefore=activity.snapshot().completed_count,
            **cuda_stats(),
        )

        error: dict[str, str] | None = None
        detections = None
        try:
            detections = runtime.infer(frame.image)
        except Exception as exc:  # noqa: BLE001 -- the classification is the evidence
            error = {"type": type(exc).__name__, "code": str(exc)[:200]}
        total = monotonic() - entered

        detect_seconds = timer.detect_seconds
        sync_seconds = timer.sync_seconds
        accounted = (detect_seconds or 0.0) + (sync_seconds or 0.0)
        convert_seconds = max(0.0, total - accounted) if detect_seconds is not None else None
        count = len(detections) if detections is not None else None
        if count is not None:
            detections_total += count

        record: dict[str, Any] = {
            "frame": frame.source_frame_number,
            "offsetMs": frame.offset_ms,
            "shape": shape,
            "detectSeconds": _r(detect_seconds),
            "syncSeconds": _r(sync_seconds),
            "convertSeconds": _r(convert_seconds),
            "totalSeconds": _r(total),
            "detections": count,
            "completedCountAfter": activity.snapshot().completed_count,
            "stageAtExit": timer.stage,
            **cuda_stats(),
        }
        if error is not None:
            record["error"] = error
            state["stage"] = "error"
            log.emit("error", **record)
            break

        state["stage"] = "complete"
        log.emit("complete", **record)
        inferred += 1
        if slowest is None or total > slowest["totalSeconds"]:
            slowest = {k: record[k] for k in ("frame", "offsetMs", "totalSeconds", "detectSeconds", "syncSeconds", "convertSeconds")}

    state["stage"] = "finished"
    summary = {
        "decodedFrames": decoded,
        "skippedFrames": skipped,
        "inferredFrames": inferred,
        "detectionsTotal": detections_total,
        "slowest": slowest,
        "completedCount": activity.snapshot().completed_count,
        **cuda_stats(),
    }
    log.emit("summary", **summary)
    return summary


def _r(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--source", type=Path, required=True, help="the exact media file the failed job processed")
    parser.add_argument("--expected-sha256", help="refuse to run if the source does not hash to this")
    parser.add_argument("--output", type=Path, required=True, help="JSONL trace; must not already exist")
    parser.add_argument("--mode", choices=_MODES, default="window")
    parser.add_argument("--window-start-seconds", type=float, default=108.0)
    parser.add_argument("--window-end-seconds", type=float, default=122.0)
    parser.add_argument("--until-seconds", type=float, default=122.0, help="sequential mode: infer every frame up to this offset")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--model-root", type=Path, default=Path("models"))
    parser.add_argument("--model-manifest", type=Path, default=Path("models/manifests/rtmdet-m-coco-phase1-v1.json"))
    parser.add_argument("--pipeline-profile", type=Path, default=Path("src/vision/config/pipelines/phase1-detection-tracking-v1.json"))
    parser.add_argument("--runtime-profile", type=Path, default=Path("src/vision/runtime/mmdetection-phase1-v1/runtime.json"))
    parser.add_argument("--qualification-record", type=Path, default=Path("models/qualifications/rtmdet-m-coco-phase1-v1.json"))
    parser.add_argument("--no-warmup", action="store_true", help="skip runtime.warmup(); the supervisor always warms up, so leave this off unless testing the cold call")
    parser.add_argument("--no-explicit-sync", action="store_true", help="do not torch.cuda.synchronize() between the detector call and conversion; reproduces production timing but hides where a GPU stall surfaces")
    parser.add_argument("--hang-report-seconds", type=float, default=60.0)
    parser.add_argument("--hang-exit-seconds", type=float, default=150.0)
    parser.add_argument("--max-frames", type=int)
    return parser


def _plan_from_args(args: argparse.Namespace) -> FramePlan:
    if args.mode == "window":
        return FramePlan(
            mode="window",
            start_ms=int(round(args.window_start_seconds * 1000)),
            end_ms=int(round(args.window_end_seconds * 1000)),
        )
    return FramePlan(mode="sequential", start_ms=0, end_ms=int(round(args.until_seconds * 1000)))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        plan = _plan_from_args(args)
        if not args.source.is_file():
            raise TraceError("trace_source_missing")
        source_sha = _sha256(args.source)
        if args.expected_sha256 and source_sha != args.expected_sha256.lower():
            raise TraceError("trace_source_sha256_mismatch")
        log = EventLog(args.output)
    except TraceError as exc:
        print(json.dumps({"ok": False, "code": exc.code}, sort_keys=True))
        return 2

    traceback_path = args.output.with_suffix(args.output.suffix + ".tracebacks.txt")
    state: dict[str, Any] = {"frame": None, "offsetMs": None, "stage": "startup"}

    try:
        log.emit(
            "start",
            schemaVersion=SCHEMA_VERSION,
            mode=plan.mode,
            windowStartMs=plan.start_ms,
            windowEndMs=plan.end_ms,
            device=args.device,
            sourceName=args.source.name,
            sourceSha256=source_sha,
            explicitSync=not args.no_explicit_sync,
            warmup=not args.no_warmup,
            hangReportSeconds=args.hang_report_seconds,
            hangExitSeconds=args.hang_exit_seconds,
            pid=os.getpid(),
        )

        from mavi_vision.runtime.activity import InferenceActivity
        from mavi_vision.video.reader import iter_frames

        activity = InferenceActivity()
        sentinel = HangSentinel(
            activity,
            log,
            report_seconds=args.hang_report_seconds,
            exit_seconds=args.hang_exit_seconds,
            traceback_path=traceback_path,
            current=lambda: dict(state),
        )
        sentinel.start()

        state["stage"] = "build_runtime"
        log.emit("build_runtime_enter", **dict(state))
        runtime = build_runtime(
            model_root=args.model_root,
            manifest_path=args.model_manifest,
            profile_path=args.pipeline_profile,
            runtime_profile_path=args.runtime_profile,
            qualification_path=args.qualification_record,
            device=args.device,
            activity=activity,
        )
        log.emit(
            "build_runtime_done",
            device=runtime.metadata.device,
            modelId=runtime.metadata.model_id,
            versions=dict(runtime.metadata.versions),
        )

        timer = StageTimer()
        instrument_runtime(
            runtime,
            timer,
            synchronize=None if args.no_explicit_sync else _cuda_synchronize(args.device),
        )
        cuda_stats = _cuda_stats(args.device)

        if not args.no_warmup:
            state["stage"] = "warmup"
            log.emit("warmup_enter", **cuda_stats())
            started = time.monotonic()
            runtime.warmup()
            log.emit("warmup_done", totalSeconds=_r(time.monotonic() - started), **cuda_stats())

        summary = run_trace(
            frames=iter_frames(args.source),
            plan=plan,
            runtime=runtime,
            activity=activity,
            log=log,
            timer=timer,
            cuda_stats=cuda_stats,
            max_frames=args.max_frames,
            current_state=state,
        )
        sentinel.stop()
        print(json.dumps({"ok": True, "trace": str(args.output), "summary": summary}, sort_keys=True, default=str))
        return 0
    except Exception as exc:  # noqa: BLE001 -- record, then fail loudly
        log.emit("fatal", errorType=type(exc).__name__, error=str(exc)[:400], **dict(state))
        print(json.dumps({"ok": False, "code": "trace_failed", "errorType": type(exc).__name__, "trace": str(args.output)}, sort_keys=True))
        return 1
    finally:
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
