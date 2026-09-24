"""S1.2c real-clip evidence-selector measurement — Development qualification tooling, NOT a runtime component.

Runs real video through the production composition, exactly as
``ProductionVisionProcessor`` builds it: the qualified runtime → ``RTMDetDetector`` →
``ByteTrackTracker`` → ``VideoProcessor(evidence_policy=profile.evidence)``. The
runtime comes from the real ``RuntimeSupervisor`` configured from the worker's own
``WorkerSettings`` (the same environment variables the worker reads), and
measurement refuses to start unless the supervisor reports READY. Nothing is
scripted, and detections are never derived from ground truth.

Instrumentation observes; it never decides:

* the scorer and encoder are the production ``QualityV1Scorer`` and
  ``JpegLadderEncoder``, wrapped only to record what they compute;
* ``EvidenceSelector.observe`` / ``resolve`` are wrapped to read the holders the
  selector already has (tier after each frame, holders before resolve), then
  delegate unchanged. ``test_measure_evidence_real_clips.py`` proves the resolved
  Evidence Sets are identical with and without the instrumentation.

Per-candidate rows hold scalars only (no pixels) and are written to a local
gzip CSV. The summary JSON carries the distributions and per-Track results for
the parameter note. Neither the clips nor the outputs belong in Git.

Usage, from ``src/vision`` with the qualified Development runtime installed and the
worker settings in the environment::

    python ../../tools/vision/dev/measure_evidence_real_clips.py <out-dir> \\
        MOT17-02-FRCNN=<path> MOT17-13-FRCNN=<path>
"""
from __future__ import annotations

import asyncio
import contextlib
import csv
import gzip
import hashlib
import json
import statistics
import sys
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import av

from mavi_vision.common.lease import LeaseGuard
from mavi_vision.detection.rtmdet import RTMDetDetector
from mavi_vision.evidence import selector as selector_module
from mavi_vision.evidence.encoder import JpegLadderEncoder
from mavi_vision.evidence.quality import QualityV1Scorer
from mavi_vision.evidence.roles import ROLE_ORDER, EvidenceRole
from mavi_vision.pipeline.process_video import VideoProcessor
from mavi_vision.storage.artifact_store import StagingArtifactStore
from mavi_vision.tracking.bytetrack import ByteTrackTracker

JOB_ID = UUID("018fa7b6-2b31-7f42-9f33-9fd9f6fdd7a1")
PERCENTILES = (("min", 0.0), ("p10", 0.10), ("p25", 0.25), ("p50", 0.50), ("p75", 0.75), ("p90", 0.90), ("max", 1.0))
CANDIDATE_FIELDS = (
    "clip", "track_id", "object_class", "frame", "offset_ms", "confidence", "area", "sharpness",
    "edge_margin", "occlusion_iou", "quality_micro", "selection_micro", "pass_confidence",
    "pass_sharpness", "pass_edge", "pass_occlusion", "qualified",
)


def percentiles(values: list[float]) -> dict[str, float] | None:
    """Nearest-rank on the sorted values (min and max are exact)."""
    if not values:
        return None
    ordered = sorted(values)
    last = len(ordered) - 1
    return {name: round(ordered[round(q * last)], 6) for name, q in PERCENTILES}


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def media_metadata(path: Path) -> dict:
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        return {
            "container": container.format.name,
            "codec": stream.codec_context.name,
            "width": stream.codec_context.width,
            "height": stream.codec_context.height,
            "fps": float(stream.average_rate) if stream.average_rate else None,
            "frames": stream.frames or None,
            "durationSeconds": float(container.duration / av.time_base) if container.duration else None,
        }


class RecordingScorer:
    """The production scorer, recording each candidate's scalars (no pixels)."""

    def __init__(self, inner: QualityV1Scorer, policy, clip: str, sink) -> None:
        self._inner, self._policy, self._clip, self._sink = inner, policy, clip, sink

    def score(self, context, candidate):
        quality = self._inner.score(context, candidate)
        p = self._policy
        passes = (
            candidate.confidence >= p.confidence_floor,
            quality.sharpness >= p.sharpness_floor,
            quality.edge_margin >= p.edge_margin_floor,
            quality.occlusion_iou < p.occlusion_iou_ceiling,
        )
        self._sink.append(
            {
                "clip": self._clip,
                "track_id": candidate.track_id,
                "object_class": candidate.object_class.value,
                "frame": context.frame.source_frame_number,
                "offset_ms": context.frame.offset_ms,
                "confidence": candidate.confidence,
                "area": quality.area,
                "sharpness": quality.sharpness,
                "edge_margin": quality.edge_margin,
                "occlusion_iou": quality.occlusion_iou,
                "quality_micro": quality.quality_micro,
                "selection_micro": quality.selection_micro,
                "pass_confidence": passes[0],
                "pass_sharpness": passes[1],
                "pass_edge": passes[2],
                "pass_occlusion": passes[3],
                "qualified": all(passes),
            }
        )
        return quality


class CountingEncoder:
    """The production encoder; counts calls and cap failures by cap."""

    def __init__(self, inner: JpegLadderEncoder) -> None:
        self._inner = inner
        self.calls = 0
        self.refused: dict[int, int] = {}

    def encode(self, crop, cap_bytes):
        self.calls += 1
        image = self._inner.encode(crop, cap_bytes)
        if image is None:
            self.refused[cap_bytes] = self.refused.get(cap_bytes, 0) + 1
        return image


@contextlib.contextmanager
def observe_selectors(tracks: dict[str, dict]):
    """Read-only taps on EvidenceSelector: tier after each frame and holders at resolve.

    Records are keyed by Track id. ``live`` maps a selector's ``id()`` to its Track
    and is refreshed on every observe, which always precedes that selector's
    resolve, so an id reused after a finished selector is collected is corrected
    before it is read. No selector (and no holder bytes) is ever retained.
    """
    cls = selector_module.EvidenceSelector
    original_observe, original_resolve = cls.observe, cls.resolve
    live: dict[int, str] = {}

    def observe(self, context, candidate):
        original_observe(self, context, candidate)
        live[id(self)] = candidate.track_id
        record = tracks.setdefault(candidate.track_id, {"trackId": candidate.track_id, "tiers": []})
        holder = self.holder(EvidenceRole.REPRESENTATIVE)
        tier = None if holder is None else ("qualified" if holder.qualified else "fallback")
        if not record["tiers"] or record["tiers"][-1] != tier:
            record["tiers"].append(tier)

    def resolve(self):
        resolved = original_resolve(self)
        record = tracks[live.pop(id(self))]
        record["heldBeforeResolve"] = [h.role.value for h in self.holders()]
        record["resolved"] = [r.role.value for r in resolved]
        record["representativeQualified"] = bool(resolved) and resolved[0].evidence.qualified
        record["encodeAttempts"] = self.stats.encode_attempts
        record["unadmissibleByRole"] = {k.value: v for k, v in self.stats.unadmissible_by_role.items() if v}
        return resolved

    cls.observe, cls.resolve = observe, resolve
    try:
        yield
    finally:
        cls.observe, cls.resolve = original_observe, original_resolve


def measure_clip(runtime, profile, clip: str, video: Path, work_dir: Path) -> tuple[dict, list[dict]]:
    """One clip through the production composition, instrumented read-only."""
    policy = profile.evidence
    rows: list[dict] = []
    selectors: dict[str, dict] = {}
    encoder = CountingEncoder(JpegLadderEncoder(policy.encoder))
    staging = work_dir / "staging" / clip
    staging.mkdir(parents=True, exist_ok=True)
    processor = VideoProcessor(
        RTMDetDetector(runtime, profile),
        ByteTrackTracker(profile.tracker),
        StagingArtifactStore(staging, JOB_ID, 1),
        evidence_policy=policy,
        evidence_scorer=RecordingScorer(QualityV1Scorer(policy.occlusion_penalty_weight), policy, clip, rows),
        evidence_encoder=encoder,
    )
    digest, size = sha256_file(video)
    started = time.perf_counter()
    with observe_selectors(selectors):
        result = processor.process(
            job_id=JOB_ID,
            attempt_count=1,
            source_path=video,
            expected_source_size_bytes=size,
            expected_source_sha256=digest,
            lease_guard=LeaseGuard(datetime.now(timezone.utc) + timedelta(days=1)),
        )
    elapsed = time.perf_counter() - started
    by_id = selectors
    tracks = []
    for track in result.tracks:
        record = by_id[track.track_id]
        track_rows = [row for row in rows if row["track_id"] == track.track_id]
        tiers = record["tiers"]
        tracks.append(
            {
                "trackId": track.track_id,
                "objectClass": track.object_class.value,
                "candidateFrames": len(track_rows),
                "qualifiedFrames": sum(row["qualified"] for row in track_rows),
                "representativeQualified": record["representativeQualified"],
                "fallbackToQualified": "fallback" in tiers and tiers[-1] == "qualified",
                "representativeSelectionMicro": track.observations[0].selection_micro,
                "heldBeforeResolve": record["heldBeforeResolve"],
                "resolved": record["resolved"],
                "admitted": [o.role.value for o in track.observations],
                "encodeAttempts": record["encodeAttempts"],
                "unadmissibleByRole": record["unadmissibleByRole"],
                "cropBytes": {o.role.value: o.crop.size_bytes for o in track.observations},
            }
        )
    frames = result.frames_processed
    summary = {
        "clip": clip,
        "sha256": digest,
        "sizeBytes": size,
        "media": media_metadata(video),
        "framesProcessed": frames,
        "processingSeconds": round(elapsed, 2),
        "tracks": tracks,
        "encoderCalls": encoder.calls,
        "encoderRefusedByCap": encoder.refused,
        "accounting": {
            role.value: asdict(result.evidence_accounting.for_role(role)) for role in ROLE_ORDER
        },
        "peakRssKiB": _peak_rss_kib(),
    }
    return summary, rows


def aggregate(label: str, summaries: list[dict], rows: list[dict]) -> dict:
    tracks = [t for s in summaries for t in s["tracks"]]
    n = len(rows)

    def share(key: str) -> float | None:
        return round(sum(r[key] for r in rows) / n, 4) if n else None

    def role_share(role: str) -> float | None:
        return round(sum(role in t["resolved"] for t in tracks) / len(tracks), 4) if tracks else None

    held_nv = [t for t in tracks if EvidenceRole.NEAR_VIEW.value in t["heldBeforeResolve"]]
    dropped_nv = [t for t in held_nv if EvidenceRole.NEAR_VIEW.value not in t["resolved"]]
    encodes = [t["encodeAttempts"] for t in tracks]
    by_class: dict[str, dict] = {}
    for track in tracks:
        entry = by_class.setdefault(track["objectClass"], {"tracks": 0, "fallback": 0})
        entry["tracks"] += 1
        entry["fallback"] += not track["representativeQualified"]
    return {
        "label": label,
        "candidateFrames": n,
        "tracks": len(tracks),
        "distributions": {
            key: percentiles([r[key] for r in rows])
            for key in ("sharpness", "area", "edge_margin", "confidence", "occlusion_iou")
        },
        "passRates": {
            "confidence": share("pass_confidence"),
            "sharpness": share("pass_sharpness"),
            "edgeMargin": share("pass_edge"),
            "occlusion": share("pass_occlusion"),
            "allFloors": share("qualified"),
        },
        "tracksWithQualifiedFrame": sum(t["qualifiedFrames"] > 0 for t in tracks),
        "fallbackRepresentatives": sum(not t["representativeQualified"] for t in tracks),
        "fallbackToQualifiedTransitions": sum(t["fallbackToQualified"] for t in tracks),
        "fallbackByClass": by_class,
        "roleCoverage": {
            "near-view": role_share("near-view"),
            "early-diverse": role_share("early-diverse"),
            "late-diverse": role_share("late-diverse"),
            "allFour": round(sum(len(t["resolved"]) == 4 for t in tracks) / len(tracks), 4) if tracks else None,
        },
        "nearViewResolveDrops": {"held": len(held_nv), "dropped": len(dropped_nv)},
        "encodeAttemptsPerTrack": {
            "mean": round(statistics.fmean(encodes), 3) if encodes else None,
            "median": statistics.median(encodes) if encodes else None,
            "max": max(encodes) if encodes else None,
        },
        "unadmissibleTotal": sum(sum(t["unadmissibleByRole"].values()) for t in tracks),
        "cropBytes": {
            role.value: percentiles([t["cropBytes"][role.value] for t in tracks if role.value in t["cropBytes"]])
            for role in ROLE_ORDER
        },
    }


def _peak_rss_kib() -> int | None:
    """Peak resident memory where the platform reports it; None otherwise."""
    try:
        import resource  # POSIX only

        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except ImportError:
        try:
            import psutil  # present in the Development runtime on Windows

            info = psutil.Process().memory_info()
            return int(getattr(info, "peak_wset", info.rss) // 1024)
        except ImportError:
            return None


def _jsonable(value):
    if is_dataclass(value):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return value


async def _measure(out: Path, clips: list[list[str]]) -> dict:
    """The worker's own composition: WorkerSettings → RuntimeSupervisor (READY or stop);
    every clip runs on the vision execution lane, as the worker runs attempts."""
    from mavi_vision.common.settings import WorkerSettings
    from mavi_vision.runtime.activity import InferenceActivity
    from mavi_vision.runtime.execution_lane import VisionExecutionLane
    from mavi_vision.runtime.gpu_identity import capture_gpu_identity
    from mavi_vision.runtime.supervisor import RuntimeState, RuntimeSupervisor

    settings = WorkerSettings()
    lane = VisionExecutionLane()
    supervisor = RuntimeSupervisor(
        lane=lane,
        activity=InferenceActivity(),
        model_root=settings.model_root,
        manifest_path=settings.model_manifest_path,
        profile_path=settings.pipeline_profile_path,
        runtime_profile_path=settings.runtime_profile_path,
        qualification_path=settings.qualification_record_path,
        deployment_profile_policy_path=settings.deployment_profile_policy_path,
        deployment_profile=settings.deployment_profile,
        device_policy=settings.device_policy,
        device_index=settings.device_index,
        production_mode=settings.production_mode,
        inference_watchdog_seconds=settings.inference_watchdog_seconds,
        device_resolution_reason=settings.device_resolution_reason,
        watchdog_grace_seconds=settings.watchdog_grace_seconds,
        build_id=settings.build_id,
        commit_sha=settings.commit_sha,
        gpu_identity_provider=capture_gpu_identity,
    )
    try:
        await supervisor.start()
        if supervisor.state is not RuntimeState.READY:
            raise SystemExit(f"qualified runtime not READY: {supervisor.unavailable_reason}")
        summaries, all_rows = [], []
        for clip, path in clips:
            summary, rows = await lane.run(
                measure_clip, supervisor.runtime, supervisor.profile, clip, Path(path), out
            )
            summaries.append(summary)
            all_rows.extend(rows)
        return {
            "provenance": _jsonable(supervisor.provenance),
            "clips": summaries,
            "perClip": [
                aggregate(s["clip"], [s], [r for r in all_rows if r["clip"] == s["clip"]]) for s in summaries
            ],
            "combined": aggregate("combined", summaries, all_rows),
            "rows": all_rows,
        }
    finally:
        await supervisor.close()


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(_measure(out, [arg.split("=", 1) for arg in argv[2:]]))
    rows = report.pop("rows")
    with gzip.open(out / "candidates.csv.gz", "wt", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("perClip", "combined")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
