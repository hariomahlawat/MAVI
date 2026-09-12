from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from mavi_vision.common.analytical import VisionProcessingResult
from mavi_vision.common.lease import LeaseGuard
from mavi_vision.runtime.errors import ProcessingDependencyError
from mavi_vision.runtime.interfaces import DetectorRuntime
from mavi_vision.runtime.profile import PipelineProfile
from mavi_vision.storage.artifact_store import StagingArtifactStore


RuntimeProvider = Callable[[], DetectorRuntime]
StagingFactory = Callable[[UUID, int], StagingArtifactStore]
ProcessingFailureSink = Callable[[ProcessingDependencyError], None]


class ProductionVisionProcessor:
    """Task-9 production composition facade.

    The implementation is intentionally absent in this TDD checkpoint. The
    contract tests added with this stub define the required attempt/runtime
    ownership semantics before production composition is implemented.
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
        raise NotImplementedError("task9_production_processor_not_implemented")
