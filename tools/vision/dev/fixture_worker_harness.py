"""Development evidence harness — NOT a MAVI runtime component.

Drives the real MAVI worker control plane (lease, heartbeat, complete) through
the repository's WorkerApiClient/WorkerRunner with the deterministic
FixtureDetector and FixtureTracker instead of RTMDet/ByteTrack. It exists so
the API, PostgreSQL and operator UI workflow (import → processing → search →
review) can be exercised on a host that has no qualified vision runtime
bundle. Detections follow the synthetic video described in
docs/reviews/2026-09-20-pr50-correctness-review.md; nothing it produces is
model evidence or qualification evidence, and its provenance is labelled
`fixture-detector` / `unverified`.

Usage (repository virtualenv, API already running):

    MAVI_API_BASE_URL=http://localhost:62153 MAVI_WORKER_ID=fixture-worker-01 \
    MAVI_MEDIA_ROOT=<MediaStorage:RootPath> python tools/vision/dev/fixture_worker_harness.py

Exit code 0 when one job was leased and completed, 3 when no job was queued.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src" / "vision"))

from mavi_vision.common.analytical import NormalizedBoundingBox, ObjectClass, VisionProcessingResult
from mavi_vision.common.lease import LeaseGuard
from mavi_vision.common.settings import WorkerSettings
from mavi_vision.detection.fixture import FixtureDetector
from mavi_vision.detection.interfaces import DetectionCandidate
from mavi_vision.pipeline.process_video import VideoProcessor
from mavi_vision.runtime.progress import ProcessingProgressSink
from mavi_vision.runtime.provenance import RuntimeProvenance, TrackerParameters, capture_platform_identity
from mavi_vision.storage.artifact_store import StagingArtifactStore
from mavi_vision.storage.local_media_store import LocalMediaStore
from mavi_vision.tracking.fixture import FixtureTracker
from mavi_vision.worker.client import WorkerApiClient
from mavi_vision.worker.runner import WorkerRunner

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

FPS = 25
WIDTH, HEIGHT = 640, 360


def build_fixture():
    """Detections that follow the white box drawn by ffmpeg (x = 80 + 30t px)."""
    detections: dict[int, tuple[DetectionCandidate, ...]] = {}
    associations: dict[tuple[int, int], str] = {}
    for frame in range(50, 251):
        t = frame / FPS
        x = (80 + 30 * t) / WIDTH
        person = DetectionCandidate(ObjectClass.PERSON, 0.90 - 0.001 * ((frame % 7)), NormalizedBoundingBox(min(x, 0.85), 120 / HEIGHT, 60 / WIDTH, 140 / HEIGHT))
        items = [person]
        associations[(frame, 0)] = "person-000001"
        if 100 <= frame <= 200:
            vehicle = DetectionCandidate(ObjectClass.VEHICLE, 0.82, NormalizedBoundingBox(0.62, 0.55, 0.28, 0.30))
            items.append(vehicle)
            associations[(frame, 1)] = "vehicle-000001"
        detections[frame] = tuple(items)
    return detections, associations


class FixtureVisionProcessor:
    def __init__(self, media_root: Path) -> None:
        self._media_root = media_root

    def process(self, *, job_id: UUID, attempt_count: int, source_path: Path, expected_source_size_bytes: int,
                expected_source_sha256: str, lease_guard: LeaseGuard,
                progress_sink: ProcessingProgressSink | None = None) -> VisionProcessingResult:
        detections, associations = build_fixture()
        processor = VideoProcessor(FixtureDetector(detections), FixtureTracker(associations),
                                   StagingArtifactStore(self._media_root, job_id, attempt_count))
        return processor.process(job_id=job_id, attempt_count=attempt_count, source_path=source_path,
                                 expected_source_size_bytes=expected_source_size_bytes,
                                 expected_source_sha256=expected_source_sha256, lease_guard=lease_guard,
                                 progress_sink=progress_sink)


def provenance() -> RuntimeProvenance:
    return RuntimeProvenance(
        model_id="fixture-detector", model_version="0",
        model_manifest_sha256="0" * 64, checkpoint_sha256="0" * 64, resolved_config_sha256="0" * 64,
        pipeline_profile_id="fixture-detection-tracking", pipeline_profile_version="0", pipeline_profile_sha256="0" * 64,
        qualification_id=None, qualification_sha256=None, verification_status="unverified",
        runtime_profile_id="fixture-local-evidence", runtime_profile_sha256="0" * 64,
        runtime_variant="linux-x86_64-cpu", platform_lock_sha256=None, detector_backend="fixture",
        dependency_versions={"python": sys.version.split()[0], "trackers": "fixture-0", "av": "16.1.0", "numpy": "fixture"}, ffmpeg_version=None,
        platform=capture_platform_identity(), configured_device_policy="cpu", configured_device_index=0,
        actual_device="cpu", gpu=None, mavi_build="local-evidence", mavi_commit=os.environ.get("MAVI_COMMIT_SHA", "0" * 40),
        frame_policy="every-frame",
        tracker_parameters=TrackerParameters(25.0, 0.5, 0.5, 0.1, 1, 1.0),
        device_resolution_reason="explicit_cpu",
    )


async def main() -> int:
    settings = WorkerSettings(api_base_url=os.environ["MAVI_API_BASE_URL"], worker_id=os.environ["MAVI_WORKER_ID"],
                              media_root=Path(os.environ["MAVI_MEDIA_ROOT"]), heartbeat_interval_seconds=5.0)
    client = WorkerApiClient(settings)
    runner = WorkerRunner(client, LocalMediaStore(settings.media_root), 1.0, FixtureVisionProcessor(settings.media_root),
                          heartbeat_interval_seconds=5.0, runtime_provenance_provider=provenance)
    worked = await runner.run_once()
    logging.info("run_once -> %s", worked)
    return 0 if worked else 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
