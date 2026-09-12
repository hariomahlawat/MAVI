from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from mavi_vision.common.analytical import VisionProcessingResult
from mavi_vision.common.lease import LeaseGuard
from mavi_vision.detection.rtmdet import RTMDetDetector
from mavi_vision.pipeline.process_video import VideoProcessor
from mavi_vision.runtime.errors import ProcessingDependencyError
from mavi_vision.runtime.interfaces import DetectorRuntime
from mavi_vision.runtime.profile import PipelineProfile
from mavi_vision.storage.artifact_store import StagingArtifactStore
from mavi_vision.tracking.bytetrack import ByteTrackTracker


RuntimeProvider = Callable[[], DetectorRuntime]
StagingFactory = Callable[[UUID, int], StagingArtifactStore]
ProcessingFailureSink = Callable[[ProcessingDependencyError], None]


class ProductionVisionProcessor:
    """Compose one production attempt around the current shared detector runtime.

    The facade is deliberately not a runtime owner. runtime_provider is resolved
    exactly once after initial lease validation for each call, which gives the
    attempt an immutable runtime snapshot while allowing a later attempt to see
    a supervisor-reconstructed replacement runtime.

    Every attempt receives fresh detector-adapter, tracker, staging-store and
    VideoProcessor state. The failure sink is a local runtime-health notification
    seam only: its implementation must be synchronous, thread-safe, non-blocking
    and non-throwing, and must perform no network/control-plane mutation from the
    vision execution lane.
    """

    def __init__(
        self,
        runtime_provider: RuntimeProvider,
        profile: PipelineProfile,
        staging_factory: StagingFactory,
        runtime_failure_sink: ProcessingFailureSink,
    ) -> None:
        self._runtime_provider = runtime_provider
        self._profile = profile
        self._staging_factory = staging_factory
        self._runtime_failure_sink = runtime_failure_sink

    def process(
        self,
        *,
        job_id: UUID,
        attempt_count: int,
        source_path: Path,
        expected_source_size_bytes: int,
        expected_source_sha256: str,
        lease_guard: LeaseGuard,
    ) -> VisionProcessingResult:
        # Attempt-local construction itself must not start after authority is
        # already known to be lost. VideoProcessor continues to own all later
        # mutation-boundary lease checks.
        lease_guard.check_owned()

        try:
            runtime = self._runtime_provider()
            detector = RTMDetDetector(runtime, self._profile)
            tracker = ByteTrackTracker(self._profile.tracker)
            artifact_store = self._staging_factory(job_id, attempt_count)
            processor = VideoProcessor(detector, tracker, artifact_store)

            return processor.process(
                job_id=job_id,
                attempt_count=attempt_count,
                source_path=source_path,
                expected_source_size_bytes=expected_source_size_bytes,
                expected_source_sha256=expected_source_sha256,
                lease_guard=lease_guard,
            )
        except ProcessingDependencyError as exc:
            # Runtime health is independent of lease authority. Preserve the local
            # signal even when WorkerRunner later suppresses a stale terminal job
            # mutation after ownership loss.
            self._runtime_failure_sink(exc)
            raise
