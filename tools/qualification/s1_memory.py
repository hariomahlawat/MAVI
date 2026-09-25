"""S1.4 B2 live-memory qualification harness (plan §6.2).

Runs a declared synthetic workload through the **real** ``VideoProcessor``:
- the real tracker adapter (native ByteTrack for authoritative evidence;
  ``FixtureTracker`` only for structural/parity runs);
- the real scorer, selector, JPEG encoder, trajectory spool, staging,
  finalisation and admission.

It measures the four §6.2 terms:
1. **Per-live-Track accounting.** The maximum encoded bytes held by any live
   Track's role holders, and the maximum trajectory points buffered in memory.
   Both are read from the live accumulators on every frame.
2. **Per-retired-Track retained cost.** The ``tracemalloc`` slope of traced
   bytes against retired count (tracemalloc mode).
3. **Process-level slope.** USS on Linux, commit charge on Windows, against
   retired count (process mode, tracemalloc off).
4. **Completion peak.** The traced peak while the real worker client builds
   and serialises the completion body for the run's own result. Recorded only.

**Frame source (declared, §6.2).** Synthetic, lossless, high-entropy. A
deterministic pool of seeded noise frames is cycled through the
``VideoProcessor(frame_reader=...)`` qualification seam. The source file is
still opened and SHA-verified; only decoding is replaced. A lossy codec would
smear the high-entropy crops that make the 16 KiB per-retired-Track ceiling
discriminate, and a multi-gigabyte video is not needed.

**Scene.** ``live_tracks`` slots on a grid. Each slot shows one subject for
``track_frames`` frames, grows its box by ``growth`` so supplemental roles are
exercised, then leaves the slot empty for ``gap_frames`` frames. The gap is
longer than the ByteTrack lost-track buffer, so the subject retires before the
next one appears. Slot phases are staggered so retirements are spread evenly.

The harness is measurement tooling. It asserts no PASS; the evidence checker
(``s1_evidence.py``) applies the plan's limits to its output. Heavy runs are
opt-in via the CLI: normal CI runs only the small presets in
``tests/test_s1_memory.py``.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import hashlib
import json
import os
import platform as platform_module
import subprocess
import sys
import tempfile
import time
import tracemalloc
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from uuid import UUID

import numpy as np

REPO = Path(__file__).resolve().parents[2]
VISION = REPO / "src" / "vision"
if str(VISION) not in sys.path:
    sys.path.insert(0, str(VISION))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import process_memory  # noqa: E402
from mavi_vision.common.analytical import NormalizedBoundingBox, ObjectClass, VisionProcessingResult  # noqa: E402
from mavi_vision.common.lease import LeaseGuard, LeaseLostError  # noqa: E402
from mavi_vision.detection.interfaces import DetectionCandidate  # noqa: E402
from mavi_vision.pipeline.process_video import VideoProcessingError, VideoProcessor  # noqa: E402
from mavi_vision.runtime.profile import load_pipeline_profile  # noqa: E402
from mavi_vision.storage.artifact_store import StagingArtifactStore, attempt_directory_name  # noqa: E402
from mavi_vision.tracking.interfaces import TrackerUpdate  # noqa: E402
from mavi_vision.video.reader import DecodedFrame  # noqa: E402
from mavi_vision.video.trajectory_spool import DEFAULT_CHUNK_POINTS, RECORD_BYTES as SPOOL_RECORD_BYTES  # noqa: E402

OUTPUT_SCHEMA = "s1-b2-memory-output-v1"
FRAME_SOURCE = "synthetic-noise-pool-v1"
PROFILE_PATH = VISION / "config" / "pipelines" / "phase1-detection-tracking-v1.json"
JOB_ID = UUID("01920000-0000-7000-8000-00000000b2b2")
QUALIFIED_CPU_VARIANTS = ("linux-x86_64-cpu", "windows-x86_64-cpu")
PER_LIVE_HELD_BOUND_BYTES = 64 * 1024 + 3 * 160 * 1024  # ADR-013 §4: 544 KiB


@dataclass(frozen=True)
class Workload:
    name: str
    tracker: str  # "bytetrack" (authoritative) or "fixture" (structural only)
    mode: str  # "trace" (tracemalloc, bounds 1, 2 and 4) or "process" (bound 3)
    live_tracks: int
    retirements: int
    track_frames: int
    gap_frames: int
    box_px: int
    frame_width: int
    frame_height: int
    fps: float = 30.0
    growth: float = 0.35
    pool_frames: int = 8
    sample_every: int = 50
    warmup_fraction: float = 0.10
    seed: int = 20260924
    measure_completion: bool = True

    def validate(self) -> None:
        if self.tracker not in ("bytetrack", "fixture"):
            raise ValueError("workload_tracker_invalid")
        if self.mode not in ("trace", "process"):
            raise ValueError("workload_mode_invalid")
        if min(self.live_tracks, self.retirements, self.track_frames, self.box_px, self.sample_every) < 1:
            raise ValueError("workload_nonpositive")
        cell = self.cell_px
        if (self.frame_width // cell) * (self.frame_height // cell) < self.live_tracks:
            raise ValueError("workload_slots_do_not_fit")

    @property
    def cell_px(self) -> int:
        return int(self.box_px * (1.0 + self.growth)) + 16

    @property
    def cycle_frames(self) -> int:
        return self.track_frames + self.gap_frames

    @property
    def frame_budget(self) -> int:
        """Twice the declared frame count: a tracker that stops retiring fails."""
        return 2 * (self.retirements * self.cycle_frames // self.live_tracks + 2 * self.cycle_frames)


# Authoritative presets (§6.2). Each runs in its own process, and ``derive``
# combines their outputs. The frame counts are declared, not discovered:
#   frames ≈ retirements × (track_frames + gap_frames) / live_tracks.
# Wall-time estimates below are from a Linux development host at about 1 ms per
# live observation. They are the declared budget; the harness records the
# actual ``processingSeconds``.
_BYTETRACK_GAP = 45  # frames; > the 1,033 ms ByteTrack retirement horizon at 30 fps
_BASE_FRAMES = 450  # 15 s Tracks
_LONG_FRAMES = 10 * _BASE_FRAMES  # 10× longer (§6.2), and > one spool chunk
assert _LONG_FRAMES > DEFAULT_CHUNK_POINTS
PRESETS: dict[str, Workload] = {
    # Bound 2 baseline: 1,000 retirements at L=16, high-entropy crops.
    # ≈ 31,000 frames, ≈ 8 min.
    "b2-retained-baseline": Workload("b2-retained-baseline", "bytetrack", "trace", 16, 1_000, _BASE_FRAMES, _BYTETRACK_GAP, 144, 1280, 720, sample_every=25),
    # Bound 2, duration variation: 10× longer Tracks, spilling spool chunks.
    # ≈ 284,000 frames, ≈ 75 min.
    "b2-retained-long": Workload("b2-retained-long", "bytetrack", "trace", 16, 1_000, _LONG_FRAMES, _BYTETRACK_GAP, 144, 1280, 720, sample_every=25, measure_completion=False),
    # Bound 2, crop variation: larger supplemental crops; the Representative
    # stays within its 64 KiB cap. ≈ 41,000 frames, ≈ 8 min.
    "b2-retained-large-crops": Workload("b2-retained-large-crops", "bytetrack", "trace", 12, 1_000, _BASE_FRAMES, _BYTETRACK_GAP, 224, 1920, 1080, sample_every=25, measure_completion=False),
    # Bound 3, retired history: 5,000 retirements at L=32, tracemalloc off.
    # ≈ 21,000 frames, ≈ 12 min.
    "b2-process-memory": Workload("b2-process-memory", "bytetrack", "process", 32, 5_000, 90, _BYTETRACK_GAP, 128, 1920, 1080, sample_every=100, measure_completion=False),
    # Bound 4: the completion peak of a 10,000-Track result. Retirements stop 64
    # short, so retired plus still-live stays within the 10,000-Track bound.
    # ≈ 11,800 frames, ≈ 6 min.
    "b2-completion-peak": Workload("b2-completion-peak", "bytetrack", "trace", 64, 10_000 - 64, 30, _BYTETRACK_GAP, 96, 1920, 1080, sample_every=500),
}
# Bound 3, stepped live levels: at least five plateaus, fitted against live count.
LIVE_LEVELS = (4, 8, 16, 32, 64)
for _level in LIVE_LEVELS:
    PRESETS[f"b2-live-{_level}"] = Workload(
        f"b2-live-{_level}", "bytetrack", "process", _level, 400, 150, _BYTETRACK_GAP, 96, 1920, 1080,
        sample_every=50, measure_completion=False,
    )


# --------------------------------------------------------------------------- scene
class Scene:
    """Deterministic subjects per slot; the detector and fixture script source."""

    def __init__(self, workload: Workload) -> None:
        workload.validate()
        self.workload = workload
        cell = workload.cell_px
        columns = workload.frame_width // cell
        self._origins = [((index % columns) * cell + 8, (index // columns) * cell + 8) for index in range(workload.live_tracks)]
        self._phases = [slot * workload.cycle_frames // workload.live_tracks for slot in range(workload.live_tracks)]

    def active(self, frame_number: int) -> list[tuple[int, int, int]]:
        """(slot, subject, age) of every subject visible in the frame, slot order."""
        result = []
        for slot, phase in enumerate(self._phases):
            local = frame_number - phase
            if local < 0:
                continue
            subject, age = divmod(local, self.workload.cycle_frames)
            if age < self.workload.track_frames:
                result.append((slot, subject, age))
        return result

    def box(self, slot: int, age: int) -> NormalizedBoundingBox:
        workload = self.workload
        span = max(1, workload.track_frames - 1)
        edge = workload.box_px * (1.0 + workload.growth * age / span)
        drift = (age % 5) - 2
        x0, y0 = self._origins[slot]
        return NormalizedBoundingBox(
            (x0 + 4 + drift) / workload.frame_width,
            (y0 + 4) / workload.frame_height,
            edge / workload.frame_width,
            edge / workload.frame_height,
        )

    def detections(self, frame_number: int) -> tuple[DetectionCandidate, ...]:
        return tuple(
            DetectionCandidate(ObjectClass.PERSON, 0.9, self.box(slot, age), frame_ordinal=ordinal)
            for ordinal, (slot, _, age) in enumerate(self.active(frame_number))
        )

    @staticmethod
    def track_id(slot: int, subject: int) -> str:
        return f"person-{slot:03d}-{subject:06d}"


class SceneDetector:
    def __init__(self, scene: Scene) -> None:
        self._scene = scene

    def detect(self, frame: DecodedFrame):
        return self._scene.detections(frame.source_frame_number)


class ScriptedSceneTracker:
    """The structural path: ``FixtureTracker`` driven by the scene's own script.

    ``FixtureTracker`` needs its association map up front, so this builds it
    for a bounded horizon. It is used only for small structural runs, never as
    authoritative memory evidence (§6.2).
    """

    def __init__(self, scene: Scene, horizon_frames: int) -> None:
        from mavi_vision.tracking.fixture import FixtureTracker

        association: dict[tuple[int, int], str] = {}
        retirements: dict[int, list[str]] = {}
        workload = scene.workload
        for frame_number in range(horizon_frames):
            for ordinal, (slot, subject, age) in enumerate(scene.active(frame_number)):
                track_id = scene.track_id(slot, subject)
                association[(frame_number, ordinal)] = track_id
                if age == workload.track_frames - 1:
                    retire_at = frame_number + max(1, workload.gap_frames // 2)
                    if retire_at < horizon_frames:
                        retirements.setdefault(retire_at, []).append(track_id)
        self._inner = FixtureTracker(association, retirements)

    def update(self, frame, detections) -> TrackerUpdate:
        return self._inner.update(frame, detections)


class CountingTracker:
    """Delegates to the real tracker and counts what it reports retired."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.retired = 0

    def update(self, frame, detections) -> TrackerUpdate:
        update = self._inner.update(frame, detections)
        if isinstance(update, TrackerUpdate):
            self.retired += len(update.retired_track_ids)
        return update


class ObservedVideoProcessor(VideoProcessor):
    """The production processor, observed from outside.

    It overrides nothing that affects behavior. ``_accumulate`` is wrapped only
    to keep a reference to the attempt's live-Track map, so the frame source can
    account for held evidence between frames. ``test_s1_memory`` pins the
    signature this relies on, so a refactor fails loudly instead of silently
    measuring nothing.
    """

    live_view: dict | None = None

    def _accumulate(self, live, context, candidate):  # type: ignore[override]
        self.live_view = live
        return super()._accumulate(live, context, candidate)


# --------------------------------------------------------------------------- measurement
@dataclass
class _Running:
    held_max: int = 0
    buffered_points_max: int = 0
    live_max: int = 0
    staging_peak: int = 0
    samples: list[dict[str, Any]] = field(default_factory=list)


def held_evidence_bytes(accumulator) -> int:
    return sum(holder.image.size_bytes for holder in accumulator.evidence.holders())


def buffered_trajectory_points(accumulator) -> int:
    spool = accumulator.trajectory
    return spool.point_count - spool.spilled_points


def attempt_directory(media_root: Path, job_id: UUID, attempt_count: int) -> Path:
    """Where ``StagingArtifactStore`` stages one attempt (``staging/<job>/attempt-NNNN``)."""
    return media_root / "staging" / str(job_id) / attempt_directory_name(attempt_count)


def directory_usage(root: Path) -> tuple[int, int]:
    """(bytes, files) under ``root``; staging is attempt-scoped regular files."""
    total = files = 0
    for path in root.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
                files += 1
        except OSError:
            continue
    return total, files


def fit_line(points: list[tuple[float, float]]) -> dict[str, float]:
    """Ordinary least squares y = slope·x + intercept, with r²."""
    n = len(points)
    if n < 3:
        raise ValueError("fit_needs_three_points")
    xs = np.array([p[0] for p in points], dtype=np.float64)
    ys = np.array([p[1] for p in points], dtype=np.float64)
    x_mean, y_mean = xs.mean(), ys.mean()
    sxx = float(((xs - x_mean) ** 2).sum())
    if sxx == 0.0:
        raise ValueError("fit_degenerate_x")
    slope = float(((xs - x_mean) * (ys - y_mean)).sum() / sxx)
    intercept = float(y_mean - slope * x_mean)
    residual = float(((ys - (slope * xs + intercept)) ** 2).sum())
    total = float(((ys - y_mean) ** 2).sum())
    # Standard error of the slope: the resolution a relative comparison needs.
    stderr = float(np.sqrt(residual / (n - 2) / sxx))
    return {"slope": slope, "intercept": intercept, "r2": 1.0 - residual / total if total else 1.0, "points": n, "stderr": stderr}


def _frame_pool(workload: Workload) -> list[np.ndarray]:
    rng = np.random.default_rng(workload.seed)
    return [
        rng.integers(0, 256, (workload.frame_height, workload.frame_width, 3), dtype=np.uint8)
        for _ in range(workload.pool_frames)
    ]


def _make_tracker(workload: Workload, scene: Scene):
    if workload.tracker == "bytetrack":
        from mavi_vision.tracking.bytetrack import ByteTrackTracker

        return ByteTrackTracker(load_pipeline_profile(PROFILE_PATH).tracker)
    horizon = workload.retirements * workload.cycle_frames // workload.live_tracks + 2 * workload.cycle_frames
    return ScriptedSceneTracker(scene, horizon)


def run_workload(
    workload: Workload,
    work_root: Path,
    *,
    processor_class: type[VideoProcessor] = ObservedVideoProcessor,
    on_frame: Callable[[int], None] | None = None,
    job_id: UUID = JOB_ID,
    attempt_count: int = 1,
    lease_guard: LeaseGuard | None = None,
) -> dict[str, Any]:
    """Run one workload in this process and return its measurement record.

    ``processor_class`` and ``on_frame`` exist for the discrimination tests;
    ``job_id``, ``attempt_count`` and ``lease_guard`` for the staging-lifecycle
    phases, which share one media root across jobs and attempts.
    """
    workload.validate()
    work_root.mkdir(parents=True, exist_ok=True)
    scene = Scene(workload)
    profile = load_pipeline_profile(PROFILE_PATH)
    tracker = CountingTracker(_make_tracker(workload, scene))
    detector = SceneDetector(scene)
    store = StagingArtifactStore(work_root, job_id, attempt_count)
    running = _Running()
    pool = _frame_pool(workload)
    tracing = workload.mode == "trace"
    # Only this attempt's staging counts toward its peak and its derived bound.
    staging_root = attempt_directory(work_root, job_id, attempt_count)

    def sample(frame_number: int) -> None:
        gc.collect()
        entry: dict[str, Any] = {"frame": frame_number, "retired": tracker.retired, "live": len(processor.live_view or {})}
        if tracing:
            entry["tracedBytes"] = tracemalloc.get_traced_memory()[0]
        else:
            entry["process"] = process_memory.sample().as_dict()
        staged, files = directory_usage(staging_root)
        running.staging_peak = max(running.staging_peak, staged)
        entry["stagingBytes"] = staged
        entry["stagedFiles"] = files
        running.samples.append(entry)

    def frames(_stream) -> Iterator[DecodedFrame]:
        next_sample = workload.sample_every
        frame_number = 0
        sample(0)  # the baseline, before any frame is processed
        while tracker.retired < workload.retirements:
            if frame_number >= workload.frame_budget:
                raise RuntimeError("workload_frame_budget_exceeded")
            live = processor.live_view
            if live:
                running.live_max = max(running.live_max, len(live))
                for accumulator in live.values():
                    running.held_max = max(running.held_max, held_evidence_bytes(accumulator))
                    running.buffered_points_max = max(running.buffered_points_max, buffered_trajectory_points(accumulator))
            if tracker.retired >= next_sample:
                sample(frame_number)
                next_sample = (tracker.retired // workload.sample_every + 1) * workload.sample_every
            if on_frame is not None:
                on_frame(frame_number)
            yield DecodedFrame(
                source_frame_number=frame_number,
                offset_ms=round(frame_number * 1000 / workload.fps),
                image=pool[frame_number % len(pool)],
            )
            frame_number += 1
        sample(frame_number)

    # The declared frame source goes through the processor's qualification seam;
    # ``frames`` reads ``processor`` lazily, once processing has started.
    processor = processor_class(detector, tracker, store, evidence_policy=profile.evidence, frame_reader=frames)
    source = work_root / "sources" / f"{job_id}-{attempt_count}.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(f"{FRAME_SOURCE}\n{json.dumps(asdict(workload), sort_keys=True)}\n", encoding="utf-8")
    payload = source.read_bytes()

    if tracing:
        tracemalloc.start()
    started = time.perf_counter()
    try:
        result = processor.process(
            job_id=job_id,
            attempt_count=attempt_count,
            source_path=source,
            expected_source_size_bytes=len(payload),
            expected_source_sha256=hashlib.sha256(payload).hexdigest(),
            lease_guard=lease_guard or LeaseGuard(datetime.now(timezone.utc) + timedelta(days=7)),
        )
        processing_seconds = time.perf_counter() - started
        completion = measure_completion_peak(result) if (tracing and workload.measure_completion) else None
    finally:
        if tracing:
            tracemalloc.stop()

    warmup = workload.retirements * workload.warmup_fraction
    series_key = "tracedBytes" if tracing else None
    points = [
        (float(sample_entry["retired"]), float(sample_entry[series_key] if series_key else sample_entry["process"]["primary_bytes"]))
        for sample_entry in running.samples
        if sample_entry["retired"] >= warmup
    ]
    fit = fit_line(points)
    roles: dict[str, dict[str, int]] = {}
    for track in result.tracks:
        for observation in track.observations:
            entry = roles.setdefault(observation.role.value, {"count": 0, "minBytes": observation.crop.size_bytes, "maxBytes": 0, "totalBytes": 0})
            entry["count"] += 1
            entry["minBytes"] = min(entry["minBytes"], observation.crop.size_bytes)
            entry["maxBytes"] = max(entry["maxBytes"], observation.crop.size_bytes)
            entry["totalBytes"] += observation.crop.size_bytes
    # §6.3 / ADR-013 §4: staging never exceeds each Track's encoded-evidence
    # bound plus its trajectory bytes (the finalised msgpack, and the 24-byte
    # spool records that exist until it is written). Derived from this run.
    staged_after, _ = directory_usage(staging_root)
    running.staging_peak = max(running.staging_peak, staged_after)
    bound_terms = {
        "tracks": len(result.tracks),
        "perTrackEvidenceBoundBytes": PER_LIVE_HELD_BOUND_BYTES,
        "trajectoryArtifactBytes": sum(track.trajectory_artifact.size_bytes for track in result.tracks),
        "spoolRecordBytes": sum(track.detection_count for track in result.tracks) * SPOOL_RECORD_BYTES,
    }
    staging_bound = (
        bound_terms["tracks"] * bound_terms["perTrackEvidenceBoundBytes"]
        + bound_terms["trajectoryArtifactBytes"]
        + bound_terms["spoolRecordBytes"]
    )
    process_summary = None
    if not tracing:
        post_warmup = [entry["process"] for entry in running.samples if entry["retired"] >= warmup]
        process_summary = {
            "metric": running.samples[-1]["process"]["primary_metric"],
            "baselineBytes": running.samples[0]["process"]["primary_bytes"],
            "afterWarmupBytes": post_warmup[0]["primary_bytes"],
            "plateauMeanBytes": sum(item["primary_bytes"] for item in post_warmup) / len(post_warmup),
            "peakRssBytes": running.samples[-1]["process"]["peak_bytes"],
        }

    return {
        "schema": OUTPUT_SCHEMA,
        "frameSource": FRAME_SOURCE,
        "workload": asdict(workload),
        "results": {
            "framesProcessed": result.frames_processed,
            "retirements": tracker.retired,
            "tracks": len(result.tracks),
            "admittedCropsByRole": dict(sorted(roles.items())),
            "liveMax": running.live_max,
            "perLiveHeldEvidenceBytesMax": running.held_max,
            "perLiveHeldEvidenceBoundBytes": PER_LIVE_HELD_BOUND_BYTES,
            "perLiveBufferedTrajectoryPointsMax": running.buffered_points_max,
            "trajectoryChunkPoints": DEFAULT_CHUNK_POINTS,
            "retiredSlope": {
                "series": "tracemalloc-traced-bytes" if tracing else f"process-{running.samples[-1]['process']['primary_metric']}",
                "bytesPerRetiredTrack": fit["slope"],
                "stderr": fit["stderr"],
                "r2": fit["r2"],
                "points": fit["points"],
                "warmupRetirementsExcluded": warmup,
            },
            "stagingPeakBytes": running.staging_peak,
            "stagingDerivedBoundBytes": staging_bound,
            "stagingDerivedBoundTerms": bound_terms,
            "completion": completion,
            "process": process_summary,
            "processingSeconds": processing_seconds,
        },
        "samples": running.samples,
    }


def measure_completion_peak(result: VisionProcessingResult) -> dict[str, int]:
    """Traced peak while the real worker client builds and serialises the body.

    Goes through ``WorkerApiClient.complete`` with an in-memory transport, so the
    measured allocation is the production path (model build, JSON dump and
    body encode). The lease and provenance come from the repository's v3 golden.
    """
    import httpx

    from mavi_vision.common.control_plane import VisionJobLease
    from mavi_vision.common.settings import WorkerSettings
    from mavi_vision.worker.client import WorkerApiClient

    golden = json.loads((REPO / "contracts/examples/vision-job-complete-v3.example.json").read_text(encoding="utf-8"))
    lease_payload = json.loads((REPO / "contracts/examples/vision-job-lease-v2.example.json").read_text(encoding="utf-8"))
    lease_payload.update(jobId=str(result.job_id), workerId=golden["workerId"], leaseToken=golden["leaseToken"], attemptCount=1)
    lease = VisionJobLease.model_validate_json(json.dumps(lease_payload))
    provenance = _provenance_from(golden["provenance"])

    sent: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(len(request.content))
        # The platform's completion 3.1 hand-off acknowledgement (S1.4 B3 F2): the
        # worker's peak is measured up to the acknowledged submission, not publication.
        return httpx.Response(
            200,
            json={
                "schemaVersion": "3.1",
                "jobId": str(result.job_id),
                "processingRunId": "01920000-0000-7000-8000-000000000001",
                "state": "finalizing",
                "acceptedAtUtc": "2026-09-24T00:00:00Z",
                "tracksSubmitted": len(result.tracks),
            },
        )

    async def invoke() -> None:
        with tempfile.TemporaryDirectory() as media_root:
            settings = WorkerSettings(api_base_url="https://mavi-api.local", worker_id=golden["workerId"], media_root=Path(media_root))
            client = WorkerApiClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
            try:
                response = await client.complete(lease, result, 1, provenance)
            finally:
                await client.aclose()
        if response.state != "finalizing" or response.tracks_submitted != len(result.tracks):
            raise RuntimeError("completion_peak_response_mismatch")

    gc.collect()
    tracemalloc.reset_peak()
    before = tracemalloc.get_traced_memory()[0]
    asyncio.run(invoke())
    peak = tracemalloc.get_traced_memory()[1] - before
    if len(sent) != 1:
        raise RuntimeError("completion_peak_body_not_sent")
    return {"tracedPeakBytes": peak, "bodyBytes": sent[0]}


def _provenance_from(wire: dict):
    from mavi_vision.runtime.provenance import PlatformIdentity, RuntimeProvenance, TrackerParameters

    platform_wire = wire["platform"]
    tracker = wire["trackerParameters"]
    return RuntimeProvenance(
        model_id=wire["modelId"], model_version=wire["modelVersion"],
        model_manifest_sha256=wire["modelManifestSha256"], checkpoint_sha256=wire["checkpointSha256"],
        resolved_config_sha256=wire["resolvedConfigSha256"], pipeline_profile_id=wire["pipelineProfileId"],
        pipeline_profile_version=wire["pipelineProfileVersion"], pipeline_profile_sha256=wire["pipelineProfileSha256"],
        qualification_id=wire["qualificationId"], qualification_sha256=wire["qualificationSha256"],
        verification_status=wire["verificationStatus"], runtime_profile_id=wire["runtimeProfileId"],
        runtime_profile_sha256=wire["runtimeProfileSha256"], runtime_variant=wire["runtimeVariant"],
        platform_lock_sha256=wire["platformLockSha256"], detector_backend=wire["detectorBackend"],
        dependency_versions=dict(wire["dependencyVersions"]), ffmpeg_version=wire["ffmpegVersion"],
        platform=PlatformIdentity(
            system=platform_wire["system"], release=platform_wire["release"], version=platform_wire["version"],
            machine=platform_wire["machine"], processor=platform_wire["processor"],
            python_version=platform_wire["pythonVersion"], python_implementation=platform_wire["pythonImplementation"],
            python_build=tuple(platform_wire["pythonBuild"]), python_compiler=platform_wire["pythonCompiler"],
        ),
        configured_device_policy=wire["configuredDevicePolicy"], configured_device_index=wire["configuredDeviceIndex"],
        device_resolution_reason=wire["deviceResolutionReason"], actual_device=wire["actualDevice"], gpu=None,
        mavi_build=wire["maviBuild"], mavi_commit=wire["maviCommit"], frame_policy=wire["framePolicy"],
        tracker_parameters=TrackerParameters(
            reference_frame_rate=tracker["referenceFrameRate"], track_activation_threshold=tracker["trackActivationThreshold"],
            high_confidence_threshold=tracker["highConfidenceThreshold"], minimum_iou_threshold=tracker["minimumIouThreshold"],
            minimum_consecutive_frames=tracker["minimumConsecutiveFrames"], lost_track_buffer_seconds=tracker["lostTrackBufferSeconds"],
        ),
    )


# --------------------------------------------------------------------------- identity
def source_identity() -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()

    try:
        sha = git("rev-parse", "HEAD")
        clean = git("status", "--porcelain") == ""
    except (OSError, subprocess.CalledProcessError):
        sha, clean = None, False
    profile_bytes = PROFILE_PATH.read_bytes()
    profile = json.loads(profile_bytes)
    return {
        "sourceSha": sha,
        "cleanTree": clean,
        "profileId": profile["profileId"],
        "profileVersion": profile["profileVersion"],
        "profileSha256": hashlib.sha256(profile_bytes).hexdigest(),
        "selectorVersion": profile["evidence"]["selectorVersion"],
        "scorerVersion": profile["evidence"]["scorerVersion"],
        "encoderVersion": profile["evidence"]["encoder"]["encoderVersion"],
    }


def runtime_identity() -> dict[str, Any]:
    import PIL
    from PIL import features

    versions: dict[str, str | None] = {"python": platform_module.python_version(), "numpy": np.__version__, "pillow": PIL.__version__, "libjpegTurbo": features.version("libjpeg_turbo")}
    try:
        import importlib.metadata

        versions["trackers"] = importlib.metadata.version("trackers")
    except Exception:
        versions["trackers"] = None
    return {
        "platform": sys.platform,
        "os": f"{platform_module.system()} {platform_module.release()}",
        "osBuild": platform_module.version(),
        "machine": platform_module.machine(),
        "runtimeVariant": os.environ.get("MAVI_RUNTIME_VARIANT"),
        "versions": versions,
    }


def host_identity(work_root: Path) -> dict[str, Any]:
    """Host identity (§3) read from the host itself, never typed in.

    Every field the evidence schema binds is measured on both qualified
    platforms; a field that cannot be read is ``None`` and the checker then
    refuses to bind it. Storage class (SSD/HDD) cannot be detected reliably
    and stays a declared field of the record.
    """
    if sys.platform.startswith("linux"):
        return _linux_host(work_root)
    if sys.platform == "win32":  # pragma: no cover - exercised on the Windows variant
        return _windows_host(work_root)
    return {"cpuModel": None, "physicalCores": None, "logicalCores": os.cpu_count(), "ramBytes": None,
            "os": platform_module.system(), "osBuild": platform_module.version(), "stagingFilesystem": None}


def _linux_host(work_root: Path) -> dict[str, Any]:
    cpu_model = physical = ram = filesystem = os_name = None
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text(encoding="ascii", errors="replace")
        models = [line.split(":", 1)[1].strip() for line in cpuinfo.splitlines() if line.startswith("model name")]
        cpu_model = models[0] if models else None
        cores = {(block.get("physical id"), block.get("core id")) for block in _cpuinfo_blocks(cpuinfo)}
        physical = len(cores) or None
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemTotal:"):
                ram = int(line.split()[1]) * 1024
        filesystem = _linux_filesystem(work_root)
        for line in Path("/etc/os-release").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("PRETTY_NAME="):
                os_name = line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return {
        "cpuModel": cpu_model,
        "physicalCores": physical,
        "logicalCores": os.cpu_count(),
        "ramBytes": ram,
        "os": os_name,
        "osBuild": platform_module.release(),
        "stagingFilesystem": filesystem,
    }


def _windows_host(work_root: Path) -> dict[str, Any]:  # pragma: no cover - Windows variant
    import ctypes
    import struct
    import winreg
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    cpu_model = None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            cpu_model = str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
    except OSError:
        pass

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(MemoryStatusEx)
    ram = int(status.ullTotalPhys) if kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) else None

    # Physical cores: one RelationProcessorCore (0) record per core.
    physical = None
    length = wintypes.DWORD(0)
    kernel32.GetLogicalProcessorInformationEx(0, None, ctypes.byref(length))
    if length.value:
        buffer = (ctypes.c_byte * length.value)()
        if kernel32.GetLogicalProcessorInformationEx(0, buffer, ctypes.byref(length)):
            raw, offset, count = bytes(buffer), 0, 0
            while offset + 8 <= length.value:
                relationship, size = struct.unpack_from("<II", raw, offset)
                if size == 0:
                    break
                count += relationship == 0
                offset += size
            physical = count or None

    filesystem = None
    drive = os.path.splitdrive(str(work_root.resolve()))[0]
    if drive:
        name = ctypes.create_unicode_buffer(64)
        if kernel32.GetVolumeInformationW(drive + "\\", None, 0, None, None, None, name, len(name)):
            filesystem = name.value

    return {
        "cpuModel": cpu_model,
        "physicalCores": physical,
        "logicalCores": os.cpu_count(),
        "ramBytes": ram,
        "os": f"Windows {platform_module.release()}",
        "osBuild": platform_module.version(),
        "stagingFilesystem": filesystem,
    }


def _cpuinfo_blocks(text: str) -> list[dict[str, str]]:
    blocks = []
    for chunk in text.strip().split("\n\n"):
        block = {}
        for line in chunk.splitlines():
            key, _, value = line.partition(":")
            block[key.strip()] = value.strip()
        blocks.append(block)
    return blocks


def _linux_filesystem(path: Path) -> str | None:
    target = str(path.resolve())
    best = ("", None)
    for line in Path("/proc/mounts").read_text(encoding="ascii", errors="replace").splitlines():
        parts = line.split()
        if len(parts) >= 3 and target.startswith(parts[1]) and len(parts[1]) > len(best[0]):
            best = (parts[1], parts[2])
    return best[1]


# §6.2 bound 2: the slope must not change beyond ±10 %, a plain relative change.
VARIATION_LIMIT = 0.10


LIFECYCLE_SCHEMA = "s1-b2-staging-lifecycle-v1"
SIBLING_JOB_ID = UUID("01920000-0000-7000-8000-00000000b2b3")
LIFECYCLE_WORKLOAD = Workload(
    "b2-staging-lifecycle", "bytetrack", "trace", 4, 24, 60, _BYTETRACK_GAP, 96, 640, 360,
    sample_every=6, measure_completion=False,
)


def _tree_digest(root: Path) -> str | None:
    if not root.exists():
        return None
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def staging_lifecycle(workload: Workload, media_root: Path) -> dict[str, Any]:
    """§6.3: staging through a failed attempt, a lost lease, a sibling job and a
    superseding attempt, on one shared media root.

    Each phase runs the real processor and its real staging backend. The
    platform janitor's ownership after completion is the .NET
    ``StagingJanitorTests`` suite, which B2 cites.
    """
    failing_frame = workload.cycle_frames  # after the first Tracks have staged
    phases: dict[str, Any] = {}

    def fail_attempt(frame: int) -> None:
        if frame == failing_frame:
            raise RuntimeError("injected_attempt_failure")

    try:
        run_workload(workload, media_root, job_id=JOB_ID, attempt_count=1, on_frame=fail_attempt)
        failed_as_expected = False
    except VideoProcessingError:
        failed_as_expected = True
    phases["failedAttempt"] = {
        "failed": failed_as_expected,
        "residualBytes": directory_usage(attempt_directory(media_root, JOB_ID, 1))[0],
    }

    guard = LeaseGuard(datetime.now(timezone.utc) + timedelta(days=7))

    def lose_lease(frame: int) -> None:
        if frame == failing_frame:
            guard.mark_lost()

    try:
        run_workload(workload, media_root, job_id=JOB_ID, attempt_count=2, on_frame=lose_lease, lease_guard=guard)
        lost_as_expected = False
    except LeaseLostError:
        lost_as_expected = True
    phases["leaseLostAttempt"] = {
        "leaseLost": lost_as_expected,
        # A lost lease leaves staging for the next attempt to supersede.
        "retainedBytes": directory_usage(attempt_directory(media_root, JOB_ID, 2))[0],
    }

    sibling = run_workload(workload, media_root, job_id=SIBLING_JOB_ID, attempt_count=1)["results"]
    sibling_digest = _tree_digest(attempt_directory(media_root, SIBLING_JOB_ID, 1))
    phases["siblingJob"] = {
        "tracks": sibling["tracks"],
        "stagingPeakBytes": sibling["stagingPeakBytes"],
        "stagingDerivedBoundBytes": sibling["stagingDerivedBoundBytes"],
        "retainedAfterSuccessBytes": directory_usage(attempt_directory(media_root, SIBLING_JOB_ID, 1))[0],
    }

    superseding = run_workload(workload, media_root, job_id=JOB_ID, attempt_count=3)["results"]
    phases["supersedingAttempt"] = {
        "tracks": superseding["tracks"],
        "stagingPeakBytes": superseding["stagingPeakBytes"],
        "stagingDerivedBoundBytes": superseding["stagingDerivedBoundBytes"],
        "supersededAttemptRemaining": attempt_directory(media_root, JOB_ID, 2).exists(),
        "siblingJobUnchanged": _tree_digest(attempt_directory(media_root, SIBLING_JOB_ID, 1)) == sibling_digest,
        "retainedAfterSuccessBytes": directory_usage(attempt_directory(media_root, JOB_ID, 3))[0],
    }
    checks = {
        "failedAttemptCleaned": failed_as_expected and phases["failedAttempt"]["residualBytes"] == 0,
        "leaseLostStagingRetained": lost_as_expected and phases["leaseLostAttempt"]["retainedBytes"] > 0,
        "supersededAttemptRemoved": not phases["supersedingAttempt"]["supersededAttemptRemaining"],
        "siblingJobUntouched": phases["supersedingAttempt"]["siblingJobUnchanged"],
        "successfulStagingRetainedForPlatform": phases["siblingJob"]["retainedAfterSuccessBytes"] > 0
        and phases["supersedingAttempt"]["retainedAfterSuccessBytes"] > 0,
        "peaksWithinDerivedBound": all(
            phase["stagingPeakBytes"] <= phase["stagingDerivedBoundBytes"]
            for phase in (phases["siblingJob"], phases["supersedingAttempt"])
        ),
    }
    return {"schema": LIFECYCLE_SCHEMA, "workload": asdict(workload), "phases": phases, "checks": checks}


def _variation(baseline: dict[str, float], variant: dict[str, float]) -> dict[str, Any]:
    """|variant - baseline| / baseline, or an explicit ``undefined`` reason.

    A relative change is undefined when the baseline slope is not positive, or
    when its own standard error is at least the 10 % it is judged against: the
    measurement then cannot resolve a ±10 % change. That fails closed (the
    checker reports ``variation_undefined``); it is not a noise tolerance.
    """
    slope, stderr = baseline["bytesPerRetiredTrack"], baseline.get("stderr")
    if slope <= 0:
        return {"value": None, "unit": "ratio", "undefined": f"baseline slope {slope} B/track is not positive"}
    if stderr is None or stderr >= VARIATION_LIMIT * slope:
        return {"value": None, "unit": "ratio", "undefined": f"baseline slope {slope} ± {stderr} B/track cannot resolve a {VARIATION_LIMIT:.0%} change"}
    return {"value": abs(variant["bytesPerRetiredTrack"] - slope) / slope, "unit": "ratio"}


def _require(output: dict[str, Any], preset: str) -> dict[str, Any]:
    if output.get("schema") != OUTPUT_SCHEMA:
        raise ValueError(f"derive_output_schema_invalid:{preset}")
    if output["workload"]["name"] != preset:
        raise ValueError(f"derive_output_preset_mismatch:{preset}")
    if output["workload"]["tracker"] != "bytetrack":
        raise ValueError(f"derive_output_not_bytetrack:{preset}")
    if output["results"]["retirements"] < PRESETS[preset].retirements:
        raise ValueError(f"derive_output_short:{preset}")
    identity = output.get("identity") or {}
    if identity.get("cleanTree") is not True or not identity.get("sourceSha"):
        raise ValueError(f"derive_output_not_clean_source:{preset}")
    if not output.get("runtime") or not output.get("host"):
        raise ValueError(f"derive_output_identity_incomplete:{preset}")
    if output["runtime"].get("runtimeVariant") not in QUALIFIED_CPU_VARIANTS:
        raise ValueError(f"derive_output_not_qualified_variant:{preset}")
    # The workload is the declared preset, parameter for parameter.
    if output["workload"] != asdict(PRESETS[preset]):
        raise ValueError(f"derive_output_workload_not_declared:{preset}")
    return output


def derive(outputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The §6.2 B2 measurements, from one output per authoritative preset.

    Metric names are those ``s1_evidence.UNIT_REQUIREMENTS`` binds. Every output
    must come from the native ByteTrack adapter, from a clean tree at a known
    source SHA, and from one identical source, runtime and host identity.
    """
    missing = sorted(set(PRESETS) - outputs.keys())
    if missing:
        raise ValueError(f"derive_outputs_missing:{missing}")
    for preset, output in outputs.items():
        _require(output, preset)
    # One source, one runtime and one host: B2 is a claim about that triple.
    for key in ("identity", "runtime", "host"):
        if len({json.dumps(output.get(key), sort_keys=True) for output in outputs.values()}) != 1:
            raise ValueError(f"derive_outputs_mixed_{key}")

    def fit_of(preset: str) -> dict[str, float]:
        return outputs[preset]["results"]["retiredSlope"]

    def slope(preset: str) -> float:
        return outputs[preset]["results"]["retiredSlope"]["bytesPerRetiredTrack"]

    live_points = [
        (float(level), float(outputs[f"b2-live-{level}"]["results"]["process"]["plateauMeanBytes"]))
        for level in LIVE_LEVELS
    ]
    live_fit = fit_line(live_points)
    live_presets = [f"b2-live-{level}" for level in LIVE_LEVELS]
    accounted_evidence = max(outputs[p]["results"]["perLiveHeldEvidenceBytesMax"] for p in live_presets)
    accounted_points = max(outputs[p]["results"]["perLiveBufferedTrajectoryPointsMax"] for p in live_presets)
    staging_ratio = max(
        output["results"]["stagingPeakBytes"] / output["results"]["stagingDerivedBoundBytes"]
        for output in outputs.values()
    )
    trace_presets = ("b2-retained-baseline", "b2-retained-long", "b2-retained-large-crops", "b2-completion-peak")
    return {
        "schema": "s1-b2-memory-derived-v1",
        "identity": outputs["b2-retained-baseline"]["identity"],
        "runtime": outputs["b2-retained-baseline"]["runtime"],
        "host": outputs["b2-retained-baseline"]["host"],
        "measurements": {
            "b2.per-live-buffered-trajectory-points-max": {"value": max(outputs[p]["results"]["perLiveBufferedTrajectoryPointsMax"] for p in trace_presets), "unit": "count"},
            "b2.per-live-held-evidence-bytes-max": {"value": max(outputs[p]["results"]["perLiveHeldEvidenceBytesMax"] for p in trace_presets), "unit": "bytes"},
            "b2.per-retired-traced-bytes-slope": {"value": max(slope(p) for p in trace_presets[:3]), "unit": "bytes/track"},
            "b2.retired-slope-duration-variation": _variation(fit_of("b2-retained-baseline"), fit_of("b2-retained-long")),
            "b2.retired-slope-crop-variation": _variation(fit_of("b2-retained-baseline"), fit_of("b2-retained-large-crops")),
            "b2.process-memory-retired-slope": {"value": slope("b2-process-memory"), "unit": "bytes/track"},
            "b2.completion-peak-bytes": {"value": outputs["b2-completion-peak"]["results"]["completion"]["tracedPeakBytes"], "unit": "bytes"},
            "b2.staging-peak-bytes": {"value": max(output["results"]["stagingPeakBytes"] for output in outputs.values()), "unit": "bytes"},
            "b2.staging-peak-to-derived-bound-ratio": {"value": staging_ratio, "unit": "ratio"},
            # §6.2 bound 3: the empirical per-live-Track process cost. Recorded as
            # the regression baseline and reconciled with bound 1 below; bound 1
            # is the encoded-holder bound, not a process-memory ceiling.
            "b2.process-memory-per-live-track-slope": {"value": live_fit["slope"], "unit": "bytes/track"},
        },
        "liveLevelFit": {
            **{key: value for key, value in live_fit.items() if key != "points"},
            "n": live_fit["points"],
            # The five stepped live-level plateaus the checker refits.
            "points": [[level, mean] for level, mean in live_points],
        },
        "boundOneReconciliation": {
            "perLiveProcessSlopeBytes": live_fit["slope"],
            "accountedEncodedEvidenceBytesMax": accounted_evidence,
            "encodedEvidenceBoundBytes": PER_LIVE_HELD_BOUND_BYTES,
            "accountedTrajectoryPointsMax": accounted_points,
            "trajectoryChunkPoints": DEFAULT_CHUNK_POINTS,
            # What bound 1 does not account for: Python objects, tracker and
            # native-library state, the spool's in-memory chunk. Recorded, not bounded.
            "unaccountedPerLiveBytes": live_fit["slope"] - accounted_evidence,
        },
        "recorded": {
            "completionBodyBytes": outputs["b2-completion-peak"]["results"]["completion"]["bodyBytes"],
        },
    }


def _run_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    workload = PRESETS[args.preset]
    with tempfile.TemporaryDirectory(dir=args.work_root) as scratch:
        work_root = Path(scratch)
        record = {
            "identity": source_identity(),
            "runtime": runtime_identity(),
            "host": host_identity(work_root),
            "command": " ".join([Path(sys.executable).name, *sys.argv]),
            "startedAtUtc": datetime.now(timezone.utc).isoformat(),
            **run_workload(workload, work_root),
        }
    _write(args.output, record)
    results = record["results"]
    print(
        f"s1-b2-memory {workload.name}: slope {results['retiredSlope']['bytesPerRetiredTrack']:.1f} B/track, "
        f"held max {results['perLiveHeldEvidenceBytesMax']} B, {results['processingSeconds']:.0f} s, output {args.output}"
    )
    if not record["identity"]["cleanTree"]:
        print("warning: the source tree is not clean; this output cannot be authoritative evidence", file=sys.stderr)
    return 0


def _write(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S1.4 B2 live-memory qualification harness (opt-in heavy runs)")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run one authoritative preset in this process")
    run.add_argument("--preset", required=True, choices=sorted(PRESETS))
    run.add_argument("--output", required=True, type=Path)
    run.add_argument("--work-root", type=Path, default=None, help="staging root on the filesystem being qualified")
    lifecycle = commands.add_parser("staging-lifecycle", help="§6.3 staging through failure, lease loss, a sibling job and supersession")
    lifecycle.add_argument("--output", required=True, type=Path)
    lifecycle.add_argument("--work-root", type=Path, default=None, help="staging root on the filesystem being qualified")
    combine = commands.add_parser("derive", help="derive the B2 measurements from one output per preset")
    combine.add_argument("outputs", nargs="+", type=Path)
    combine.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "run":
        return _run_command(args, parser)
    if args.command == "staging-lifecycle":
        with tempfile.TemporaryDirectory(dir=args.work_root) as scratch:
            record = {
                "identity": source_identity(),
                "runtime": runtime_identity(),
                "host": host_identity(Path(scratch)),
                "command": " ".join([Path(sys.executable).name, *sys.argv]),
                "startedAtUtc": datetime.now(timezone.utc).isoformat(),
                **staging_lifecycle(LIFECYCLE_WORKLOAD, Path(scratch)),
            }
        _write(args.output, record)
        print(f"s1-b2-staging-lifecycle: {record['checks']}, output {args.output}")
        return 0 if all(record["checks"].values()) else 1
    loaded = [json.loads(path.read_text(encoding="utf-8")) for path in args.outputs]
    by_preset = {output["workload"]["name"]: output for output in loaded}
    if len(by_preset) != len(loaded):
        parser.error("one output per preset")
    _write(args.output, derive(by_preset))
    print(f"s1-b2-memory derived: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
