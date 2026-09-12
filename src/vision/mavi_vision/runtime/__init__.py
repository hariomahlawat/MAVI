"""Framework-neutral runtime contracts for MAVI vision processing."""

from mavi_vision.runtime.activity import InferenceActivity, InferenceActivitySnapshot
from mavi_vision.runtime.errors import (
    GpuOutOfMemoryError,
    GpuRuntimeError,
    InferenceContractError,
    ProcessingDependencyError,
    RuntimeDisposition,
    TrackerError,
)
from mavi_vision.runtime.execution_lane import ProcessExecutor, VisionExecutionLane
from mavi_vision.runtime.interfaces import (
    DetectorRuntime,
    PixelBoxXYXY,
    RawDetection,
    RuntimeMetadata,
)
from mavi_vision.runtime.provenance import (
    GpuIdentity,
    PlatformIdentity,
    RuntimeProvenance,
    TrackerParameters,
    build_runtime_provenance,
    capture_platform_identity,
)

__all__ = [
    "DetectorRuntime",
    "GpuIdentity",
    "GpuOutOfMemoryError",
    "GpuRuntimeError",
    "InferenceContractError",
    "InferenceActivity",
    "InferenceActivitySnapshot",
    "PixelBoxXYXY",
    "PlatformIdentity",
    "ProcessingDependencyError",
    "ProcessExecutor",
    "RawDetection",
    "RuntimeDisposition",
    "RuntimeMetadata",
    "RuntimeProvenance",
    "TrackerError",
    "TrackerParameters",
    "VisionExecutionLane",
    "build_runtime_provenance",
    "capture_platform_identity",
]
