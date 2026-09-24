"""The real-clip measurement harness observes the production composition without changing it.

Runs in the qualified runtime job (ByteTrack needs the exact ``trackers``
package), with a fake detector runtime in place of RTMDet weights: the harness's
own composition (RTMDetDetector → ByteTrackTracker → VideoProcessor) is what is
under test, not the model.
"""

from __future__ import annotations

import importlib.util
import os
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import av
import numpy as np
import pytest

if os.environ.get("MAVI_RUN_QUALIFIED_PRODUCTION_PROCESSOR_TESTS") != "1":
    pytest.skip(
        "real-clip harness composition runs only in the qualified runtime job",
        allow_module_level=True,
    )

from mavi_vision.common.lease import LeaseGuard  # noqa: E402
from mavi_vision.pipeline.production_processor import ProductionVisionProcessor  # noqa: E402
from mavi_vision.runtime.interfaces import PixelBoxXYXY, RawDetection, RuntimeMetadata  # noqa: E402
from mavi_vision.runtime.profile import load_pipeline_profile  # noqa: E402
from mavi_vision.storage.artifact_store import StagingArtifactStore  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
PROFILE = ROOT / "src/vision/config/pipelines/phase1-detection-tracking-v1.json"
FRAMES = 90


def _harness():
    spec = importlib.util.spec_from_file_location(
        "measure_evidence_real_clips", ROOT / "tools/vision/dev/measure_evidence_real_clips.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _MovingRuntime:
    """Two people crossing a textured scene; the frame index is read from the
    image so detections are a pure function of the decoded frame."""

    def __init__(self, model_id: str, vocabulary: tuple[str, ...]) -> None:
        self.metadata = RuntimeMetadata(
            backend="harness-fixture", model_id=model_id, device="cpu",
            versions={"fixture": "1"}, ordered_class_vocabulary=vocabulary,
        )

    def warmup(self) -> None:
        pass

    def infer(self, image_rgb: np.ndarray):
        height, width, _ = image_rgb.shape
        index = int(round(image_rgb[:4, :4, 0].mean() / 2))
        boxes = []
        left = 0.02 + 0.008 * index
        boxes.append((left, 0.20, left + 0.18 + 0.001 * index, 0.80, 0.9))
        if index >= 20:
            right = 0.90 - 0.006 * (index - 20)
            boxes.append((right - 0.15, 0.30, right, 0.75, 0.85))
        return tuple(
            RawDetection(
                source_class="person",
                confidence=score,
                bounding_box=PixelBoxXYXY(x1=x1 * width, y1=y1 * height, x2=x2 * width, y2=y2 * height),
            )
            for x1, y1, x2, y2, score in boxes
        )

    def close(self) -> None:
        pass


def _write_video(path: Path) -> None:
    rng = np.random.default_rng(7)
    texture = rng.integers(0, 256, (144, 256, 3), dtype=np.uint8)
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=25)
        stream.width, stream.height, stream.pix_fmt = 256, 144, "yuv420p"
        stream.options = {"qscale": "1"}
        for index in range(FRAMES):
            image = texture.copy()
            image[:8, :8, :] = min(255, 2 * index)
            for packet in stream.encode(av.VideoFrame.from_ndarray(image, format="rgb24")):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def _evidence(result, root: Path):
    return [
        (t.track_id, o.role.value, o.rank, o.source_frame_number, o.selection_micro,
         sha256(root.joinpath(*o.crop.storage_key.split("/")).read_bytes()).hexdigest())
        for t in result.tracks
        for o in t.observations
    ]


def test_harness_measures_without_changing_the_evidence_set(tmp_path: Path) -> None:
    harness = _harness()
    profile = load_pipeline_profile(PROFILE)
    runtime = _MovingRuntime(profile.model_id, tuple(profile.allowed_source_classes))
    video = tmp_path / "clip.mp4"
    _write_video(video)

    # Uninstrumented: the production processor itself.
    plain_root = tmp_path / "plain"
    plain_root.mkdir()
    job = UUID("018fa7b6-2b31-7f42-9f33-9fd9f6fdd7b2")
    plain = ProductionVisionProcessor(
        runtime_provider=lambda: runtime,
        profile=profile,
        staging_factory=lambda job_id, attempt: StagingArtifactStore(plain_root, job_id, attempt),
        runtime_failure_sink=lambda exc: None,
    ).process(
        job_id=job,
        attempt_count=1,
        source_path=video,
        expected_source_size_bytes=video.stat().st_size,
        expected_source_sha256=sha256(video.read_bytes()).hexdigest(),
        lease_guard=LeaseGuard(datetime.now(timezone.utc) + timedelta(hours=1)),
    )

    captured = {}
    original = harness.VideoProcessor.process

    def spy(self, **kwargs):
        captured["result"] = original(self, **kwargs)
        return captured["result"]

    harness.VideoProcessor.process = spy
    try:
        summary, rows = harness.measure_clip(runtime, profile, "fixture", video, tmp_path / "measured")
    finally:
        harness.VideoProcessor.process = original
    measured = captured["result"]
    measured_root = tmp_path / "measured" / "staging" / "fixture"

    # Same Tracks, roles, ranks, frames, scores and crop bytes; the instrumentation
    # decided nothing.
    assert len(plain.tracks) >= 2
    assert _evidence(measured, measured_root) == _evidence(plain, plain_root)
    assert any(len(t.observations) > 1 for t in plain.tracks), "fixture must fill supplemental roles"

    # Every candidate of every confirmed Track was scored exactly once.
    detections = {t.track_id: t.detection_count for t in plain.tracks}
    assert {t["trackId"]: t["candidateFrames"] for t in summary["tracks"]} == detections
    assert len(rows) == sum(detections.values())
    for track in summary["tracks"]:
        assert track["resolved"][0] == "representative"
        assert set(track["admitted"]) <= set(track["resolved"]) <= set(track["heldBeforeResolve"])
        assert track["representativeQualified"] == (track["qualifiedFrames"] > 0)
        assert track["supplementalUnqualified"] == 0
        assert set(track["cropPixels"]) == set(track["resolved"])
    assert summary["sha256"] == sha256(video.read_bytes()).hexdigest()
    assert summary["media"]["width"] == 256 and summary["framesProcessed"] == FRAMES


def test_percentiles_and_pass_rates_are_exact() -> None:
    harness = _harness()
    assert harness.percentiles([5, 1, 3, 2, 4]) == {
        "min": 1, "p10": 1, "p25": 2, "p50": 3, "p75": 4, "p90": 5, "max": 5,
    }
    assert harness.percentiles([]) is None
    rows = [
        {"pass_confidence": True, "pass_sharpness": s, "pass_edge": True, "pass_occlusion": True,
         "qualified": s, "sharpness": 0.1, "area": 0.1, "edge_margin": 0.1, "confidence": 0.9, "occlusion_iou": 0.0}
        for s in (True, False, False, True)
    ]
    track = {"trackId": "person-000001", "objectClass": "person", "qualifiedFrames": 2,
             "representativeQualified": True, "fallbackToQualified": True,
             "heldBeforeResolve": ["representative", "near-view"], "resolved": ["representative"],
             "encodeAttempts": 3, "unadmissibleByRole": {}, "cropBytes": {"representative": 1000},
             "candidateFrames": 4, "durationMs": 120, "supplementalUnqualified": 0,
             "nearViewDropCause": "near-duplicate-of-representative",
             "cropPixels": {"representative": [40, 90, 0]}}
    # Rows 0-3 under quality-v2: rows 0 and 3 pass occlusion; quality-v1 (all
    # detections) would have blocked rows 0, 1 and 2.
    for row, (passes_v2, passes_v1) in zip(rows, ((True, False), (False, False), (False, False), (True, True))):
        row.update(object_class="person", pass_occlusion=passes_v2, occlusion_iou=0.1 if passes_v2 else 0.5,
                   pass_occlusion_all=passes_v1, occlusion_iou_all=0.1 if passes_v1 else 0.9,
                   occluder_same_class=True, occluder_confidence=0.2)
    for row in rows:
        row["qualified"] = row["pass_sharpness"] and row["pass_occlusion"]
    combined = harness.aggregate("t", [{"tracks": [track]}], rows)
    assert combined["passRates"]["sharpness"] == 0.5
    assert combined["passRates"]["allFloors"] == 0.5
    assert combined["passRatesByClass"]["person"]["allFloors"] == 0.5
    assert combined["nearViewResolveDrops"] == {
        "held": 1, "dropped": 1,
        "causes": {"near-duplicate-of-representative": 1, "other": 0},
    }
    assert combined["reEncodesPerTrack"]["max"] == 1
    assert combined["cropLongEdgePx"]["representative"]["max"] == 90
    assert combined["fallbackDespiteQualifiedFrame"] == 0
    assert combined["fallbackToQualifiedTransitions"] == 1
    assert combined["fallbackRepresentatives"] == 0
    assert combined["emptyEvidenceTracks"] == 0
    assert combined["candidateFramesPerTrack"]["max"] == 4 and combined["trackDurationMs"]["max"] == 120
    assert combined["roleCoverageAmongTracksWithQualifiedFrame"]["near-view"] == 0.0
    diagnostics = combined["occlusionDiagnostics"]
    assert diagnostics["blockedCandidates"] == 2
    assert diagnostics["rescuedFromQualityV1"] == 1  # row 0
    # sharpness passes on rows 0 and 3 only (the other floors always pass)
    assert diagnostics["otherThreeFloorsPassed"] == 0.5
    assert diagnostics["qualityV1OcclusionPass"] == 0.25
    assert diagnostics["qualityV1AllFloors"] == 0.25
    assert diagnostics["occlusionIouAllDetections"]["max"] == 0.9


def test_occluder_diagnostics_report_the_superseded_proxy_without_replacing_it() -> None:
    from types import SimpleNamespace

    from mavi_vision.common.analytical import NormalizedBoundingBox, ObjectClass
    from mavi_vision.detection.interfaces import DetectionCandidate
    from mavi_vision.evidence.quality import occlusion_iou

    harness = _harness()
    own = NormalizedBoundingBox(x=0.1, y=0.1, width=0.2, height=0.4)
    near_duplicate = NormalizedBoundingBox(x=0.11, y=0.1, width=0.2, height=0.4)
    neighbour = NormalizedBoundingBox(x=0.2, y=0.1, width=0.2, height=0.4)
    detections = (
        DetectionCandidate(ObjectClass.PERSON, 0.9, own),
        DetectionCandidate(ObjectClass.PERSON, 0.08, near_duplicate),  # low-confidence duplicate
        DetectionCandidate(ObjectClass.VEHICLE, 0.8, neighbour),
    )
    context = SimpleNamespace(detections=detections)
    candidate = SimpleNamespace(object_class=ObjectClass.PERSON, bounding_box=own)
    confidence, same_class, all_detections = harness.occluder_diagnostics(context, candidate)
    # The superseded all-detections maximum comes from the low-confidence duplicate ...
    assert (confidence, same_class) == (0.08, True)
    assert all_detections > 0.9
    # ... while the production quality-v2 proxy counts only the credible neighbour.
    production = occlusion_iou(context, candidate, competitor_confidence_floor=0.5)
    assert abs(production - 1 / 3) < 1e-9
