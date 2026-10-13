"""Stage 4 X1 experiment runner: evidence selection with a bottom-border edge-margin exemption for Vehicles.

Development experiment tooling (owner decision O3, 2026-10-13); **not** a runtime component and **not** a pipeline
profile change. The frozen release profile, the frozen E-A/E-B results, the protocol and the thresholds are untouched.

Design: one causal difference. The production composition (``RTMDetDetector`` → ``ByteTrackTracker`` →
``VideoProcessor`` with the release profile's evidence policy, scorer and encoder) runs on each derived H3 video.

* ``live`` — the qualified runtime started through the worker's own composition (READY or stop), recording every
  per-frame detection (S1.4 §5.3 recorder) and keeping the release-profile result as the live baseline.
* ``replay --arm baseline`` — the recorded detections through the real tracker and selector, production scorer.
  It must reproduce ``live`` exactly (determinism check).
* ``replay --arm candidate`` — the same, with the production scorer wrapped by ``BottomEdgeExemptScorer``.

``BottomEdgeExemptScorer`` changes one scalar: for a **Vehicle** candidate, the ``edge_margin`` it reports to the
selector is the smallest distance to the left, top and right borders, so a box touching only the **bottom** border
can still meet ``edgeMarginFloor``. The quality and selection scores, the confidence, sharpness and occlusion floors,
the encoder, the byte caps, run-level admission and Person candidates are unchanged. Nothing reads plate pixels.

    python tools/benchmarks/plates/x1_run.py live <manifest> <derived-dir> <out-dir>
    python tools/benchmarks/plates/x1_run.py replay <baseline|candidate> <manifest> <derived-dir> <detections-dir> <out-dir>
"""
from __future__ import annotations

import asyncio
import dataclasses
import gzip
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "tools" / "vision" / "dev"), str(ROOT / "src" / "vision")]

from mavi_vision.common.analytical import ObjectClass  # noqa: E402
from mavi_vision.common.lease import LeaseGuard  # noqa: E402
from mavi_vision.detection.rtmdet import RTMDetDetector  # noqa: E402
from mavi_vision.evidence.encoder import JpegLadderEncoder  # noqa: E402
from mavi_vision.evidence.quality import scorer_for_policy  # noqa: E402
from mavi_vision.pipeline.process_video import VideoProcessor  # noqa: E402
from mavi_vision.storage.artifact_store import StagingArtifactStore  # noqa: E402
from mavi_vision.tracking.bytetrack import ByteTrackTracker  # noqa: E402
from measure_evidence_real_clips import (  # noqa: E402
    RecordingDetector, RecordingScorer, ReplayDetector, read_detections, write_detections)

RULE = {"id": "x1-bottom-edge-exempt-vehicle-v1",
        "description": "Vehicle edge margin for qualification = min(left, top, right); bottom border exempt"}


class BottomEdgeExemptScorer:
    def __init__(self, inner) -> None:
        self._inner = inner
        self.changed = 0

    def score(self, context, candidate):
        quality = self._inner.score(context, candidate)
        if candidate.object_class is ObjectClass.VEHICLE:
            box = candidate.bounding_box
            margin = min(box.x, box.y, 1.0 - (box.x + box.width))
            if margin != quality.edge_margin:
                self.changed += 1
                quality = dataclasses.replace(quality, edge_margin=margin)
        return quality


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _job_id(arm: str, sequence: str) -> UUID:
    return UUID(hashlib.sha256(f"stage4-x1/{arm}/{sequence}".encode()).hexdigest()[:32])


def run_sequence(profile, arm: str, sequence: str, video: Path, out: Path, detector, scorer) -> dict:
    job = _job_id(arm, sequence)
    staging = out / "staging" / sequence
    staging.mkdir(parents=True, exist_ok=False)
    processor = VideoProcessor(detector, ByteTrackTracker(profile.tracker), StagingArtifactStore(staging, job, 1),
                               evidence_policy=profile.evidence, evidence_scorer=scorer,
                               evidence_encoder=JpegLadderEncoder(profile.evidence.encoder))
    data = video.read_bytes()
    result = processor.process(job_id=job, attempt_count=1, source_path=video, expected_source_size_bytes=len(data),
                               expected_source_sha256=hashlib.sha256(data).hexdigest(),
                               lease_guard=LeaseGuard(datetime.now(timezone.utc) + timedelta(days=1)))

    def artefact(descriptor) -> dict:
        return {"storageKey": descriptor.storage_key, "sha256": descriptor.sha256, "sizeBytes": descriptor.size_bytes}

    tracks = [{"trackId": t.track_id, "objectClass": t.object_class.value, "startOffsetMs": t.start_offset_ms,
               "endOffsetMs": t.end_offset_ms, "trajectory": artefact(t.trajectory_artifact),
               "observations": [{"role": o.role.value, "rank": o.rank, "offsetMs": o.offset_ms,
                                 "sourceFrameNumber": o.source_frame_number, "confidence": o.confidence,
                                 "boundingBox": dataclasses.asdict(o.bounding_box), "qualityMicro": o.quality_micro,
                                 "selectionMicro": o.selection_micro, "crop": artefact(o.crop)}
                                for o in t.observations]} for t in result.tracks]
    return {"sequenceId": sequence, "processingRunId": str(job), "videoSha256": hashlib.sha256(data).hexdigest(),
            "framesProcessed": result.frames_processed, "tracks": tracks}


def _sequences(manifest_path: Path) -> list[str]:
    return sorted(row["sequenceId"] for row in json.loads(manifest_path.read_bytes())["sequences"])


def _write(out: Path, arm: str, rows: list[dict], extra: dict) -> None:
    for row in rows:
        (out / "results").mkdir(parents=True, exist_ok=True)
        (out / "results" / f"{row['sequenceId']}.json").write_text(json.dumps(row, sort_keys=True), encoding="utf-8")
    index = {"arm": arm, **extra,
             "results": {row["sequenceId"]: _sha(out / "results" / f"{row['sequenceId']}.json") for row in rows}}
    (out / "index.json").write_text(json.dumps(index, indent=1, sort_keys=True, default=str), encoding="utf-8")


async def live(manifest: Path, derived: Path, out: Path) -> None:
    from mavi_vision.common.settings import WorkerSettings
    from mavi_vision.runtime.activity import InferenceActivity
    from mavi_vision.runtime.execution_lane import VisionExecutionLane
    from mavi_vision.runtime.gpu_identity import capture_gpu_identity
    from mavi_vision.runtime.supervisor import RuntimeState, RuntimeSupervisor
    from mavi_vision.worker.composition import role_composition_from_settings

    out.mkdir(parents=True, exist_ok=False)
    settings = WorkerSettings()
    lane = VisionExecutionLane()
    supervisor = RuntimeSupervisor(
        lane=lane, activity=InferenceActivity(), composition=role_composition_from_settings(settings),
        deployment_profile_policy_path=settings.deployment_profile_policy_path,
        deployment_profile=settings.deployment_profile, device_policy=settings.device_policy,
        device_index=settings.device_index, production_mode=settings.production_mode,
        inference_watchdog_seconds=settings.inference_watchdog_seconds,
        device_resolution_reason=settings.device_resolution_reason,
        watchdog_grace_seconds=settings.watchdog_grace_seconds, build_id=settings.build_id,
        commit_sha=settings.commit_sha, gpu_identity_provider=capture_gpu_identity)
    rows = []
    try:
        await supervisor.start()
        if supervisor.state is not RuntimeState.READY:
            raise SystemExit(f"qualified runtime not READY: {supervisor.unavailable_reason}")
        profile = supervisor.profile
        for n, sequence in enumerate(_sequences(manifest), start=1):
            recorded: list = []
            detector = RecordingDetector(RTMDetDetector(supervisor.runtime, profile), recorded)
            row = await lane.run(run_sequence, profile, "live", sequence, derived / "sequences" / sequence / "video.mp4",
                                 out, detector, scorer_for_policy(profile.evidence))
            write_detections(out / "detections" / f"{sequence}.detections.jsonl", recorded)
            rows.append(row)
            print(f"live {n} {sequence} tracks={len(row['tracks'])}", flush=True)
        provenance = json.loads(json.dumps(supervisor.provenance, default=lambda o: getattr(o, "__dict__", str(o))))
    finally:
        await supervisor.close()
    detections = {s: _sha(out / "detections" / f"{s}.detections.jsonl") for s in _sequences(manifest)}
    _write(out, "live", rows, {"provenance": provenance, "detections": detections,
                               "manifestSha256": _sha(manifest), "rule": None})


def replay(arm: str, manifest: Path, derived: Path, detections_dir: Path, out: Path) -> None:
    from mavi_vision.common.settings import WorkerSettings
    from mavi_vision.runtime.profile import load_pipeline_profile

    if arm not in ("baseline", "candidate"):
        raise SystemExit("arm must be baseline or candidate")
    out.mkdir(parents=True, exist_ok=False)
    profile_path = Path(WorkerSettings().pipeline_profile_path)
    profile = load_pipeline_profile(profile_path)
    rows, changed = [], 0
    for n, sequence in enumerate(_sequences(manifest), start=1):
        inner = scorer_for_policy(profile.evidence)
        if arm == "candidate":
            inner = BottomEdgeExemptScorer(inner)
        # Per-candidate qualification scalars (no pixels): which floor each Vehicle candidate met, per frame.
        candidate_rows: list[dict] = []
        scorer = RecordingScorer(inner, profile.evidence, sequence, candidate_rows)
        detector = ReplayDetector(read_detections(detections_dir / f"{sequence}.detections.jsonl"))
        rows.append(run_sequence(profile, arm, sequence, derived / "sequences" / sequence / "video.mp4", out, detector,
                                 scorer))
        changed += getattr(inner, "changed", 0)
        (out / "candidates").mkdir(parents=True, exist_ok=True)
        with gzip.open(out / "candidates" / f"{sequence}.jsonl.gz", "wt", encoding="utf-8") as handle:
            for row in candidate_rows:
                if row["object_class"] == "vehicle":
                    handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        print(f"{arm} {n} {sequence} tracks={len(rows[-1]['tracks'])}", flush=True)
    _write(out, arm, rows, {"pipelineProfileSha256": _sha(profile_path), "manifestSha256": _sha(manifest),
                            "rule": RULE if arm == "candidate" else None,
                            "vehicleCandidatesWithChangedEdgeMargin": changed,
                            "detections": {s: _sha(detections_dir / f"{s}.detections.jsonl") for s in _sequences(manifest)}})


if __name__ == "__main__":
    if sys.argv[1] == "live":
        asyncio.run(live(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])))
    else:
        replay(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[5]), Path(sys.argv[6]))
