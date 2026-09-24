"""Evidence selector parameter measurement over the C1 scripted corpus — NOT a runtime component.

Produces the figures the S1.2 plan §5 asks for, per confirmed Track: the
sharpness / area / edge-margin distributions, the share of frames that pass each
floor and all floors, the roles filled, and the encodes per Track. It runs the
real ``VideoProcessor`` with the shipped profile's evidence policy, the real
``QualityV1Scorer`` and the real ``JpegLadderEncoder``; only detection and
tracking are scripted (the box ffmpeg drew on each frame), exactly as
``fixture_worker_harness.py`` does for the same videos.

It does not measure real footage. Real Development clips need the qualified
detector and are recorded separately.

Development prerequisite: ffmpeg (as for ``scripted_corpus.py generate``).
Usage, from the repository root::

    PYTHONPATH=src/vision python tools/vision/dev/measure_evidence_parameters.py <work-dir>

Prints one JSON document to stdout.
"""
from __future__ import annotations

import hashlib
import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scripted_corpus  # noqa: E402

from mavi_vision.common.analytical import NormalizedBoundingBox, ObjectClass  # noqa: E402
from mavi_vision.common.lease import LeaseGuard  # noqa: E402
from mavi_vision.detection.interfaces import DetectionCandidate  # noqa: E402
from mavi_vision.evidence.encoder import JpegLadderEncoder  # noqa: E402
from mavi_vision.evidence.quality import QualityV1Scorer  # noqa: E402
from mavi_vision.evidence.roles import ROLE_ORDER  # noqa: E402
from mavi_vision.pipeline.process_video import VideoProcessor  # noqa: E402
from mavi_vision.runtime.profile import load_pipeline_profile  # noqa: E402
from mavi_vision.storage.artifact_store import StagingArtifactStore  # noqa: E402
from mavi_vision.tracking.interfaces import TrackCandidate, TrackerUpdate  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
PROFILE = ROOT / "src/vision/config/pipelines/phase1-detection-tracking-v1.json"
JOB_ID = UUID("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761")
TRACK_ID = "person-000001"


class ScriptedScene:
    """Detector + tracker: the one box the scenario drew, as one confirmed Track."""

    def __init__(self, boxes: dict[int, tuple[float, float, float, float]]) -> None:
        self._boxes = boxes

    def detect(self, frame):
        box = self._boxes.get(frame.source_frame_number)
        if box is None:
            return ()
        return (DetectionCandidate(ObjectClass.PERSON, 0.9, NormalizedBoundingBox(*box)),)

    def update(self, frame, detections) -> TrackerUpdate:
        return TrackerUpdate(
            candidates=tuple(
                TrackCandidate(TRACK_ID, d.object_class, d.confidence, d.bounding_box) for d in detections
            ),
            retired_track_ids=(),
        )


class RecordingScorer:
    def __init__(self, inner: QualityV1Scorer) -> None:
        self._inner = inner
        self.scores = []

    def score(self, context, candidate):
        quality = self._inner.score(context, candidate)
        self.scores.append((candidate.confidence, quality))
        return quality


class CountingEncoder:
    def __init__(self, inner: JpegLadderEncoder) -> None:
        self._inner = inner
        self.calls = 0

    def encode(self, crop, cap_bytes):
        self.calls += 1
        return self._inner.encode(crop, cap_bytes)


def _distribution(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "min": round(ordered[0], 6),
        "p10": round(ordered[len(ordered) // 10], 6),
        "median": round(statistics.median(ordered), 6),
        "p90": round(ordered[(len(ordered) * 9) // 10], 6),
        "max": round(ordered[-1], 6),
    }


def measure(work_dir: Path) -> dict:
    spec = scripted_corpus.load_spec()
    profile = load_pipeline_profile(PROFILE)
    policy = profile.evidence
    videos = scripted_corpus.generate(spec, work_dir / "videos", [s["id"] for s in spec["scenarios"]])
    report = {"profileSha256": hashlib.sha256(PROFILE.read_bytes()).hexdigest(), "scenarios": []}
    for scene, video in zip(spec["scenarios"], videos, strict=True):
        payload = video.read_bytes()
        driver = ScriptedScene(scripted_corpus.detection_boxes(spec, scene))
        scorer = RecordingScorer(QualityV1Scorer(policy.occlusion_penalty_weight))
        encoder = CountingEncoder(JpegLadderEncoder(policy.encoder))
        staging_root = work_dir / "staging" / scene["id"]
        staging_root.mkdir(parents=True, exist_ok=True)
        processor = VideoProcessor(
            driver,
            driver,
            StagingArtifactStore(staging_root, JOB_ID, 1),
            evidence_policy=policy,
            evidence_scorer=scorer,
            evidence_encoder=encoder,
        )
        result = processor.process(
            job_id=JOB_ID,
            attempt_count=1,
            source_path=video,
            expected_source_size_bytes=len(payload),
            expected_source_sha256=hashlib.sha256(payload).hexdigest(),
            lease_guard=LeaseGuard(datetime.now(timezone.utc) + timedelta(hours=1)),
        )
        (track,) = result.tracks
        floors = {
            "confidence": sum(c >= policy.confidence_floor for c, _ in scorer.scores),
            "sharpness": sum(q.sharpness >= policy.sharpness_floor for _, q in scorer.scores),
            "edgeMargin": sum(q.edge_margin >= policy.edge_margin_floor for _, q in scorer.scores),
            "occlusion": sum(q.occlusion_iou < policy.occlusion_iou_ceiling for _, q in scorer.scores),
        }
        qualified = sum(
            c >= policy.confidence_floor
            and q.sharpness >= policy.sharpness_floor
            and q.edge_margin >= policy.edge_margin_floor
            and q.occlusion_iou < policy.occlusion_iou_ceiling
            for c, q in scorer.scores
        )
        frames = len(scorer.scores)
        report["scenarios"].append(
            {
                "id": scene["id"],
                "candidateFrames": frames,
                "sharpness": _distribution([q.sharpness for _, q in scorer.scores]),
                "area": _distribution([q.area for _, q in scorer.scores]),
                "edgeMargin": _distribution([q.edge_margin for _, q in scorer.scores]),
                "shareQualifiedPerFloor": {k: round(v / frames, 4) for k, v in floors.items()},
                "shareQualifiedAllFloors": round(qualified / frames, 4),
                "encodesPerTrack": encoder.calls,
                "roles": [
                    {
                        "role": o.role.value,
                        "rank": o.rank,
                        "sourceFrameNumber": o.source_frame_number,
                        "selectionScore": o.selection_score,
                        "cropBytes": o.crop.size_bytes,
                    }
                    for o in track.observations
                ],
                "accounting": {
                    role.value: result.evidence_accounting.for_role(role).candidates for role in ROLE_ORDER
                },
            }
        )
    return report


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    print(json.dumps(measure(Path(argv[1])), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
