"""Stage 3 Track-identity gate scenario (ADR-016).

One deterministic run through the real RTMDet class mapping, the real evidence
selector and encoder, the real staging and the real Track accumulator, fed by a
fake runtime that emits native COCO detections. Association uses the fixture
tracker, because the native ByteTrack backend exists only in the qualified runtime
job; the ByteTrack adapter's pass-through of the native class has its own test.

- a Person;
- vehicle A, labelled ``car`` for 14 frames and ``truck`` for 6 (resolves to car);
- vehicle B, always ``bus`` (resolves to bus);
- vehicle C, alternating ``car`` and ``truck`` at equal confidence (an exact tie,
  so it abstains).

Decoding is replaced by synthetic frames so the result does not depend on a
codec build. The scenario uses only interfaces that also exist before Stage 3,
so the golden summary in ``fixtures/vehicle-subclass-track-identity-gate-v1.json``
was produced by running this module against ``main@68b5b48b`` (before Stage 3),
and the gate test runs it against the current code.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Sequence
from uuid import UUID

import numpy as np
import PIL
from PIL import features

import mavi_vision
from mavi_vision.common.lease import LeaseGuard
from mavi_vision.detection.rtmdet import RTMDetDetector
from mavi_vision.evidence.roles import ROLE_ORDER
from mavi_vision.pipeline.process_video import VideoProcessor
from mavi_vision.runtime.interfaces import PixelBoxXYXY, RawDetection, RuntimeMetadata
from mavi_vision.runtime.profile import load_pipeline_profile
from mavi_vision.storage.artifact_store import StagingArtifactStore
from mavi_vision.tracking.fixture import FixtureTracker
from mavi_vision.video.reader import DecodedFrame

JOB_ID = UUID("018fa7b6-2b31-7f42-9f33-9fd9f6fdd7a3")
FRAMES = 20
WIDTH, HEIGHT = 160, 120
VOCABULARY = ("person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck")
PROFILE = Path(mavi_vision.__file__).resolve().parents[1] / "config/pipelines/phase1-detection-tracking-v1.json"
# The detector orders each frame's detections by class, then descending confidence,
# then box: Person, bus (0.9), vehicle A (0.85 or 0.8, upper box), vehicle C (0.8).
TRACK_BY_INDEX = ("person-000001", "vehicle-000001", "vehicle-000002", "vehicle-000003")


def _detections(frame: int) -> tuple[RawDetection, ...]:
    def raw(source_class: str, confidence: float, box: tuple[float, float, float, float]) -> RawDetection:
        x1, y1, x2, y2 = box
        drift = float(frame // 4)
        return RawDetection(source_class=source_class, confidence=confidence,
                            bounding_box=PixelBoxXYXY(x1 + drift, y1, x2 + drift, y2))

    return (
        raw("person", 0.9, (10.0, 20.0, 35.0, 100.0)),
        raw("car" if frame < 14 else "truck", 0.85 if frame < 14 else 0.8, (50.0, 10.0, 90.0, 40.0)),
        raw("bus", 0.9, (100.0, 10.0, 150.0, 45.0)),
        raw("car" if frame % 2 == 0 else "truck", 0.8, (50.0, 70.0, 100.0, 110.0)),
    )


class _ScriptedRuntime:
    def __init__(self) -> None:
        self._frame = 0
        self._metadata = RuntimeMetadata(
            backend="fake-rtmdet", model_id="rtmdet-m-coco-phase1", device="cpu",
            versions={"fake-runtime": "1.0"}, ordered_class_vocabulary=VOCABULARY,
        )

    @property
    def metadata(self) -> RuntimeMetadata:
        return self._metadata

    def warmup(self) -> None:
        return None

    def infer(self, image_rgb: np.ndarray) -> Sequence[RawDetection]:
        detections = _detections(self._frame)
        self._frame += 1
        return detections

    def close(self) -> None:
        return None


def _frames() -> list[DecodedFrame]:
    rng = np.random.default_rng(316)
    return [
        DecodedFrame(source_frame_number=index, offset_ms=index * 100,
                     image=rng.integers(0, 256, (HEIGHT, WIDTH, 3), dtype=np.uint8))
        for index in range(FRAMES)
    ]


def run(root: Path, *, vehicle_subclass: bool):
    """Process the scenario into ``root``; ``vehicle_subclass`` enables the Stage-3 vote."""
    root.mkdir(parents=True, exist_ok=True)
    profile = load_pipeline_profile(PROFILE)
    extra = {"vehicle_subclass_policy": profile.vehicle_subclass} if vehicle_subclass else {}
    frames = _frames()
    processor = VideoProcessor(
        RTMDetDetector(_ScriptedRuntime(), profile),
        FixtureTracker({(frame, index): track for frame in range(FRAMES) for index, track in enumerate(TRACK_BY_INDEX)}),
        StagingArtifactStore(root, JOB_ID, 1),
        evidence_policy=profile.evidence,
        frame_reader=lambda stream: iter(frames),
        **extra,
    )
    source = root / "placeholder.bin"
    source.write_bytes(b"stage-3 identity gate")
    return processor.process(
        job_id=JOB_ID, attempt_count=1, source_path=source,
        expected_source_size_bytes=source.stat().st_size,
        expected_source_sha256=sha256(source.read_bytes()).hexdigest(),
        lease_guard=LeaseGuard(datetime.now(timezone.utc) + timedelta(minutes=5)),
    )


def encoding_identity() -> list[str | None]:
    """What the crop bytes depend on (the rule of ``test_evidence_encoder``)."""
    return [sys.platform, PIL.__version__, features.version("libjpeg_turbo")]


def summarize(result, root: Path) -> dict:
    """Everything a Track is made of, except the Stage-3 subclass."""
    def file_sha(storage_key: str) -> str:
        return sha256(root.joinpath(*storage_key.split("/")).read_bytes()).hexdigest()

    tracks = []
    for track in result.tracks:
        tracks.append({
            "trackId": track.track_id,
            "objectClass": track.object_class.value,
            "startOffsetMs": track.start_offset_ms,
            "endOffsetMs": track.end_offset_ms,
            "detectionCount": track.detection_count,
            "meanConfidence": track.mean_confidence,
            "maxConfidence": track.max_confidence,
            "trajectory": {
                "storageKey": track.trajectory_artifact.storage_key,
                "sizeBytes": track.trajectory_artifact.size_bytes,
                "sha256": track.trajectory_artifact.sha256,
                "fileSha256": file_sha(track.trajectory_artifact.storage_key),
            },
            "observations": [
                {
                    "role": observation.role.value,
                    "rank": observation.rank,
                    "offsetMs": observation.offset_ms,
                    "sourceFrameNumber": observation.source_frame_number,
                    "confidence": observation.confidence,
                    "boundingBox": [observation.bounding_box.x, observation.bounding_box.y,
                                    observation.bounding_box.width, observation.bounding_box.height],
                    "qualityMicro": observation.quality_micro,
                    "selectionMicro": observation.selection_micro,
                    "crop": {
                        "storageKey": observation.crop.storage_key,
                        "sizeBytes": observation.crop.size_bytes,
                        "sha256": observation.crop.sha256,
                        "fileSha256": file_sha(observation.crop.storage_key),
                    },
                }
                for observation in track.observations
            ],
        })
    accounting = {}
    for role in ROLE_ORDER:
        counts = result.evidence_accounting.for_role(role)
        accounting[role.value] = [counts.candidates, counts.admitted, counts.omitted, counts.candidate_bytes, counts.admitted_bytes]
    return {"framesProcessed": result.frames_processed, "tracks": tracks, "evidenceAccounting": accounting}
