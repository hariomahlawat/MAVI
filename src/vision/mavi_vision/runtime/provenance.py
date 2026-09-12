from __future__ import annotations

import platform
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping

from mavi_vision.runtime.interfaces import RuntimeMetadata
from mavi_vision.runtime.manifest import validate_sha256_hex
from mavi_vision.runtime.qualification import VerifiedReleaseSelection


_REQUIRED_RUNTIME_VERSION_KEYS = frozenset(
    {
        "torch",
        "torchvision",
        "mmdet",
        "mmcv",
        "mmengine",
        "trackers",
        "supervision",
        "scipy",
        "numpy",
        "opencv",
        "av",
        "pillow",
    }
)
_CUDA_DEVICE_PATTERN = re.compile(r"cuda:(\d+)", re.ASCII)


def _require_text(value: str, *, code: str) -> str:
    if not value or value != value.strip():
        raise ValueError(code)
    return value


def _validated_sha256(value: str | None, *, code: str) -> str | None:
    if value is None:
        return None
    try:
        validate_sha256_hex(value)
    except ValueError as exc:
        raise ValueError(code) from exc
    return value


@dataclass(frozen=True, slots=True)
class PlatformIdentity:
    system: str
    release: str
    version: str
    machine: str
    processor: str
    python_version: str
    python_implementation: str
    python_build: tuple[str, str]
    python_compiler: str

    def __post_init__(self) -> None:
        for name, value in (
            ("platform_system_invalid", self.system),
            ("platform_release_invalid", self.release),
            ("platform_version_invalid", self.version),
            ("platform_machine_invalid", self.machine),
            ("python_version_invalid", self.python_version),
            ("python_implementation_invalid", self.python_implementation),
            ("python_compiler_invalid", self.python_compiler),
        ):
            _require_text(value, code=name)
        if len(self.python_build) != 2 or any(
            not item or item != item.strip() for item in self.python_build
        ):
            raise ValueError("python_build_invalid")


@dataclass(frozen=True, slots=True)
class GpuIdentity:
    name: str
    index: int
    vram_bytes: int
    driver_version: str
    cuda_runtime_version: str

    def __post_init__(self) -> None:
        _require_text(self.name, code="gpu_name_invalid")
        _require_text(self.driver_version, code="gpu_driver_version_invalid")
        _require_text(
            self.cuda_runtime_version,
            code="cuda_runtime_version_invalid",
        )
        if self.index < 0:
            raise ValueError("gpu_index_invalid")
        if self.vram_bytes <= 0:
            raise ValueError("gpu_vram_invalid")


@dataclass(frozen=True, slots=True)
class TrackerParameters:
    track_activation_threshold: float
    high_confidence_threshold: float
    minimum_matching_threshold: float
    minimum_consecutive_frames: int
    lost_track_buffer_seconds: float


@dataclass(frozen=True, slots=True)
class RuntimeProvenance:
    model_id: str
    model_version: str
    model_manifest_sha256: str
    checkpoint_sha256: str
    resolved_config_sha256: str
    pipeline_profile_id: str
    pipeline_profile_version: str
    pipeline_profile_sha256: str
    qualification_id: str | None
    qualification_sha256: str | None
    verification_status: Literal["verified", "unverified"]
    runtime_profile_id: str
    runtime_profile_sha256: str
    platform_lock_sha256: str | None
    detector_backend: str
    dependency_versions: Mapping[str, str]
    ffmpeg_version: str | None
    platform: PlatformIdentity
    configured_device_policy: Literal["cpu", "cuda", "auto"]
    configured_device_index: int
    actual_device: str
    gpu: GpuIdentity | None
    mavi_build: str
    mavi_commit: str
    frame_policy: Literal["every-frame"]
    tracker_parameters: TrackerParameters
    input_colour_space: Literal["RGB"] = "RGB"

    def __post_init__(self) -> None:
        versions = dict(self.dependency_versions)
        object.__setattr__(
            self,
            "dependency_versions",
            MappingProxyType(versions),
        )


def capture_platform_identity() -> PlatformIdentity:
    """Capture standard-library-only host/interpreter identity."""
    build = platform.python_build()
    return PlatformIdentity(
        system=platform.system(),
        release=platform.release(),
        version=platform.version(),
        machine=platform.machine(),
        processor=platform.processor() or "unknown",
        python_version=platform.python_version(),
        python_implementation=platform.python_implementation(),
        python_build=(build[0], build[1]),
        python_compiler=platform.python_compiler(),
    )


def _resolve_mavi_identity(
    *,
    production_mode: bool,
    mavi_build: str | None,
    mavi_commit: str | None,
) -> tuple[str, str]:
    if production_mode:
        if (
            mavi_build is None
            or mavi_commit is None
            or mavi_build == "unknown-development"
            or mavi_commit == "unknown-development"
        ):
            raise ValueError("production_mavi_identity_required")
        return (
            _require_text(mavi_build, code="mavi_build_invalid"),
            _require_text(mavi_commit, code="mavi_commit_invalid"),
        )

    resolved_build = mavi_build or "unknown-development"
    resolved_commit = mavi_commit or "unknown-development"
    return (
        _require_text(resolved_build, code="mavi_build_invalid"),
        _require_text(resolved_commit, code="mavi_commit_invalid"),
    )


def _validate_device_relationship(
    *,
    configured_device_policy: Literal["cpu", "cuda", "auto"],
    configured_device_index: int,
    actual_device: str,
    gpu: GpuIdentity | None,
    production_mode: bool,
) -> None:
    if configured_device_policy not in {"cpu", "cuda", "auto"}:
        raise ValueError("configured_device_policy_invalid")
    if configured_device_index < 0:
        raise ValueError("configured_device_index_invalid")
    if production_mode and configured_device_policy == "auto":
        raise ValueError("production_auto_device_forbidden")

    cuda_match = _CUDA_DEVICE_PATTERN.fullmatch(actual_device)
    if actual_device != "cpu" and cuda_match is None:
        raise ValueError("actual_device_invalid")

    if configured_device_policy == "cpu" and actual_device != "cpu":
        raise ValueError("actual_device_policy_mismatch")
    if configured_device_policy == "cuda" and cuda_match is None:
        raise ValueError("actual_device_policy_mismatch")

    if cuda_match is not None:
        actual_index = int(cuda_match.group(1))
        if actual_index != configured_device_index:
            raise ValueError("actual_device_index_mismatch")
        if gpu is None:
            raise ValueError("cuda_gpu_identity_required")
        if gpu.index != actual_index:
            raise ValueError("gpu_identity_index_mismatch")
    elif gpu is not None:
        raise ValueError("cpu_device_gpu_identity_invalid")


def build_runtime_provenance(
    *,
    selection: VerifiedReleaseSelection,
    runtime_metadata: RuntimeMetadata,
    configured_device_policy: Literal["cpu", "cuda", "auto"],
    configured_device_index: int,
    production_mode: bool,
    mavi_build: str | None = None,
    mavi_commit: str | None = None,
    platform_lock_sha256: str | None = None,
    ffmpeg_version: str | None = None,
    gpu: GpuIdentity | None = None,
    platform_identity: PlatformIdentity | None = None,
) -> RuntimeProvenance:
    """Build one immutable attempt-level provenance snapshot."""
    manifest = selection.manifest
    profile = selection.profile

    if runtime_metadata.backend != manifest.backend:
        raise ValueError("runtime_backend_manifest_mismatch")
    if runtime_metadata.model_id != manifest.model_id:
        raise ValueError("runtime_model_manifest_mismatch")
    if runtime_metadata.ordered_class_vocabulary != manifest.class_vocabulary:
        raise ValueError("runtime_vocabulary_manifest_mismatch")

    if production_mode and selection.verification_status != "verified":
        raise ValueError("production_release_not_verified")

    missing_versions = sorted(
        _REQUIRED_RUNTIME_VERSION_KEYS - set(runtime_metadata.versions)
    )
    if missing_versions:
        raise ValueError(
            "runtime_dependency_versions_missing:" + ",".join(missing_versions)
        )

    versions = {
        "python": (platform_identity or capture_platform_identity()).python_version,
        **dict(runtime_metadata.versions),
    }
    for name, value in versions.items():
        _require_text(name, code="runtime_version_name_invalid")
        _require_text(value, code="runtime_version_value_invalid")

    _validate_device_relationship(
        configured_device_policy=configured_device_policy,
        configured_device_index=configured_device_index,
        actual_device=runtime_metadata.device,
        gpu=gpu,
        production_mode=production_mode,
    )

    lock_sha = _validated_sha256(
        platform_lock_sha256,
        code="platform_lock_sha256_invalid",
    )
    if production_mode and lock_sha is None:
        raise ValueError("production_platform_lock_required")

    if ffmpeg_version is not None:
        _require_text(ffmpeg_version, code="ffmpeg_version_invalid")

    build_identity, commit_identity = _resolve_mavi_identity(
        production_mode=production_mode,
        mavi_build=mavi_build,
        mavi_commit=mavi_commit,
    )

    qualification_id = (
        selection.qualification.qualification_id
        if selection.qualification is not None
        else None
    )

    tracker = profile.tracker
    return RuntimeProvenance(
        model_id=manifest.model_id,
        model_version=manifest.model_version,
        model_manifest_sha256=selection.manifest_sha256,
        checkpoint_sha256=manifest.checkpoint.sha256,
        resolved_config_sha256=manifest.resolved_config.sha256,
        pipeline_profile_id=profile.profile_id,
        pipeline_profile_version=profile.profile_version,
        pipeline_profile_sha256=selection.profile_sha256,
        qualification_id=qualification_id,
        qualification_sha256=selection.qualification_sha256,
        verification_status=selection.verification_status,
        runtime_profile_id=selection.runtime_profile_id,
        runtime_profile_sha256=selection.runtime_profile_sha256,
        platform_lock_sha256=lock_sha,
        detector_backend=runtime_metadata.backend,
        dependency_versions=versions,
        ffmpeg_version=ffmpeg_version,
        platform=platform_identity or capture_platform_identity(),
        configured_device_policy=configured_device_policy,
        configured_device_index=configured_device_index,
        actual_device=runtime_metadata.device,
        gpu=gpu,
        mavi_build=build_identity,
        mavi_commit=commit_identity,
        frame_policy=profile.frame_policy,
        tracker_parameters=TrackerParameters(
            track_activation_threshold=tracker.track_activation_threshold,
            high_confidence_threshold=tracker.high_confidence_threshold,
            minimum_matching_threshold=tracker.minimum_matching_threshold,
            minimum_consecutive_frames=tracker.minimum_consecutive_frames,
            lost_track_buffer_seconds=tracker.lost_track_buffer_seconds,
        ),
    )
