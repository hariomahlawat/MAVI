from __future__ import annotations

import ast
from pathlib import Path
from types import MappingProxyType

import pytest

from mavi_vision.common.analytical import ObjectClass
from mavi_vision.runtime.interfaces import RuntimeMetadata
from mavi_vision.runtime.manifest import ArtifactRef, ModelManifest
from mavi_vision.runtime.profile import ByteTrackProfile, PipelineProfile
from mavi_vision.common.control_plane import DEVICE_RESOLUTION_REASONS
from mavi_vision.runtime.provenance import (
    GpuIdentity,
    PlatformIdentity,
    _validate_device_relationship,
    build_runtime_provenance,
)
from mavi_vision.runtime.qualification import (
    QualificationRecord,
    RuntimePlatformVariantIdentity,
    RuntimePythonIdentity,
    RuntimeReleaseLockIdentity,
    VerifiedReleaseSelection,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64

VOCABULARY = ("person", "car", "motorcycle", "bus", "truck")
VERSIONS = {
    "torch": "2.6.0",
    "torchvision": "0.21.0",
    "mmdet": "3.3.0",
    "mmcv": "2.1.0",
    "mmengine": "0.10.7",
    "trackers": "2.6.0",
    "supervision": "0.30.2",
    "scipy": "1.18.1",
    "numpy": "2.5.3",
    "opencv": "5.0.0",
    "opencvPython": "5.0.0.93",
    "av": "16.1.0",
    "pillow": "11.3.0",
}
LIVE_VERSIONS = {
    **VERSIONS,
    "torch": "2.6.0+cpu",
    "torchvision": "0.21.0+cpu",
}
CPU_BINARY_VERSIONS = MappingProxyType(
    {
        "torch": "2.6.0+cpu",
        "torchvision": "0.21.0+cpu",
    }
)
CUDA_BINARY_VERSIONS = MappingProxyType(
    {
        "torch": "2.6.0+cu124",
        "torchvision": "0.21.0+cu124",
    }
)


def _platform() -> PlatformIdentity:
    return PlatformIdentity(
        system="Linux",
        release="6.8.0",
        version="#1 SMP",
        machine="x86_64",
        processor="x86_64",
        python_version="3.12.14",
        python_implementation="CPython",
        python_build=("main", "Aug 13 2026 02:47:42"),
        python_compiler="GCC 13.3.0",
    )


def _profile() -> PipelineProfile:
    return PipelineProfile(
        schema_version="1.0",
        profile_id="phase1-detection-tracking-v1",
        profile_version="1.1.0-candidate",
        model_id="rtmdet-m-coco-phase1",
        detector_inference_floor=0.05,
        allowed_source_classes=VOCABULARY,
        class_mapping=MappingProxyType(
            {
                "person": ObjectClass.PERSON,
                "car": ObjectClass.VEHICLE,
                "motorcycle": ObjectClass.VEHICLE,
                "bus": ObjectClass.VEHICLE,
                "truck": ObjectClass.VEHICLE,
            }
        ),
        tracker=ByteTrackProfile(
            reference_frame_rate=30.0,
            track_activation_threshold=0.7,
            high_confidence_threshold=0.6,
            minimum_iou_threshold=0.1,
            minimum_consecutive_frames=2,
            lost_track_buffer_seconds=1.0,
        ),
        frame_policy="every-frame",
    )


def _selection(
    *,
    verified: bool = False,
    runtime_qualified: bool | None = None,
    lock_qualified: bool | None = None,
) -> VerifiedReleaseSelection:
    manifest = ModelManifest(
        schema_version="1.0",
        model_id="rtmdet-m-coco-phase1",
        model_version="1.0.0",
        purpose="phase1-person-vehicle-detection",
        backend="mmdetection",
        architecture="rtmdet-m",
        class_vocabulary=VOCABULARY,
        checkpoint=ArtifactRef("release/checkpoint.pth", SHA_B),
        resolved_config=ArtifactRef("release/config.py", SHA_C),
        runtime_profile_id="mmdetection-phase1-v1",
        verification_status="verified" if verified else "unverified",
        qualification_id="qualification-a" if verified else None,
    )
    qualification = (
        QualificationRecord(
            schema_version="1.0",
            qualification_id="qualification-a",
            model_id=manifest.model_id,
            model_manifest_sha256=SHA_A,
            checkpoint_sha256=SHA_B,
            resolved_config_sha256=SHA_C,
            pipeline_profile_id="phase1-detection-tracking-v1",
            pipeline_profile_sha256=SHA_D,
            runtime_profile_id=manifest.runtime_profile_id,
            runtime_profile_sha256=SHA_E,
            required_gates=MappingProxyType({}),
            evidence=MappingProxyType({}),
            overall_result="passed",
        )
        if verified
        else None
    )

    qualified = verified if runtime_qualified is None else runtime_qualified
    locks_qualified = qualified if lock_qualified is None else lock_qualified
    linux_python = RuntimePythonIdentity(
        version="3.12.14",
        implementation="CPython",
        build=("main", "Aug 13 2026 02:47:42"),
        compiler="GCC 13.3.0",
    )
    windows_python = RuntimePythonIdentity(
        version="3.12.10",
        implementation="CPython",
        build=("tags/v3.12.10:0cc8128", "Apr  8 2025 12:21:36"),
        compiler="MSC v.1943 64 bit (AMD64)",
    )
    variants = {
        "linux-x86_64-cpu": RuntimePlatformVariantIdentity(
            status="qualified-hosted-cpu",
            resolved_config_sha256=SHA_C,
            python_identity=linux_python,
            binary_versions=CPU_BINARY_VERSIONS,
        ),
        "windows-x86_64-cpu": RuntimePlatformVariantIdentity(
            status="qualified-hosted-cpu",
            resolved_config_sha256=SHA_C,
            python_identity=windows_python,
            binary_versions=CPU_BINARY_VERSIONS,
        ),
        "linux-x86_64-cuda": RuntimePlatformVariantIdentity(
            status=(
                "qualified-hardware"
                if qualified
                else "pending-hardware-qualification"
            ),
            resolved_config_sha256=SHA_C if qualified else None,
            python_identity=linux_python if qualified else None,
            binary_versions=CUDA_BINARY_VERSIONS if qualified else None,
        ),
        "windows-x86_64-cuda": RuntimePlatformVariantIdentity(
            status=(
                "qualified-hardware"
                if qualified
                else "pending-hardware-qualification"
            ),
            resolved_config_sha256=SHA_C if qualified else None,
            python_identity=windows_python if qualified else None,
            binary_versions=CUDA_BINARY_VERSIONS if qualified else None,
        ),
    }
    lock_hashes = {
        "linux-x86_64-cpu": SHA_A,
        "windows-x86_64-cpu": SHA_B,
        "linux-x86_64-cuda": SHA_C,
        "windows-x86_64-cuda": SHA_D,
    }
    locks = {
        variant: RuntimeReleaseLockIdentity(
            status=(
                "qualified-offline-lock"
                if locks_qualified
                else (
                    "pending-wheelhouse-freeze"
                    if variant.endswith("-cpu")
                    else "pending-hardware-qualification"
                )
            ),
            artifact=f"locks/{variant}.lock" if locks_qualified else None,
            sha256=lock_hashes[variant] if locks_qualified else None,
        )
        for variant in lock_hashes
    }

    return VerifiedReleaseSelection(
        manifest=manifest,
        profile=_profile(),
        qualification=qualification,
        manifest_sha256=SHA_A,
        profile_sha256=SHA_D,
        qualification_sha256=SHA_F if verified else None,
        runtime_profile_id=manifest.runtime_profile_id,
        runtime_profile_sha256=SHA_E,
        checkpoint_path=Path("models/release/checkpoint.pth"),
        resolved_config_path=Path("models/release/config.py"),
        verification_status=manifest.verification_status,
        runtime_qualification_status="qualified" if qualified else "partial",
        runtime_semantic_graph=MappingProxyType(dict(VERSIONS)),
        runtime_platform_variants=MappingProxyType(variants),
        runtime_release_locks=MappingProxyType(locks),
    )


def _metadata(*, device: str = "cpu", versions: dict[str, str] | None = None) -> RuntimeMetadata:
    return RuntimeMetadata(
        backend="mmdetection",
        model_id="rtmdet-m-coco-phase1",
        device=device,
        versions=LIVE_VERSIONS if versions is None else versions,
        ordered_class_vocabulary=VOCABULARY,
    )


def test_development_provenance_is_complete_immutable_and_explicitly_unknown() -> None:
    provenance = build_runtime_provenance(
        selection=_selection(),
        runtime_metadata=_metadata(),
        configured_device_policy="auto",
        device_resolution_reason="cuda_pack_not_declared",
        configured_device_index=0,
        production_mode=False,
        platform_identity=_platform(),
        ffmpeg_version="7.1",
    )

    assert provenance.verification_status == "unverified"
    assert provenance.mavi_build == "unknown-development"
    assert provenance.mavi_commit == "unknown-development"
    assert provenance.dependency_versions["python"] == "3.12.14"
    assert provenance.dependency_versions["torch"] == "2.6.0+cpu"
    assert provenance.ffmpeg_version == "7.1"
    assert provenance.actual_device == "cpu"
    assert provenance.input_colour_space == "RGB"
    assert provenance.frame_policy == "every-frame"
    assert provenance.tracker_parameters.reference_frame_rate == 30.0
    assert provenance.tracker_parameters.track_activation_threshold == 0.7
    assert provenance.tracker_parameters.high_confidence_threshold == 0.6
    assert provenance.tracker_parameters.minimum_iou_threshold == 0.1
    assert provenance.tracker_parameters.minimum_consecutive_frames == 2
    assert provenance.tracker_parameters.lost_track_buffer_seconds == 1.0
    with pytest.raises(TypeError):
        provenance.dependency_versions["torch"] = "tampered"  # type: ignore[index]


def test_verified_production_provenance_requires_release_and_build_identity() -> None:
    provenance = build_runtime_provenance(
        selection=_selection(verified=True),
        runtime_metadata=_metadata(),
        configured_device_policy="cpu",
        configured_device_index=0,
        production_mode=True,
        mavi_build="mavi-0.1.0",
        mavi_commit="1234567890abcdef1234567890abcdef12345678",
        platform_identity=_platform(),
    )

    assert provenance.verification_status == "verified"
    assert provenance.qualification_id == "qualification-a"
    assert provenance.qualification_sha256 == SHA_F
    assert provenance.runtime_variant == "linux-x86_64-cpu"
    assert provenance.platform_lock_sha256 == SHA_A
    assert provenance.mavi_build == "mavi-0.1.0"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {
                "selection": _selection(),
                "runtime_metadata": _metadata(),
                "configured_device_policy": "cpu",
                "configured_device_index": 0,
                "production_mode": True,
                "mavi_build": "build",
                "mavi_commit": "commit",
                "platform_identity": _platform(),
            },
            "production_release_not_verified",
        ),
        (
            {
                "selection": _selection(verified=True),
                "runtime_metadata": _metadata(),
                "configured_device_policy": "cpu",
                "configured_device_index": 0,
                "production_mode": True,
                "platform_identity": _platform(),
            },
            "production_mavi_identity_required",
        ),
        (
            {
                "selection": _selection(verified=True, lock_qualified=False),
                "runtime_metadata": _metadata(),
                "configured_device_policy": "cpu",
                "configured_device_index": 0,
                "production_mode": True,
                "mavi_build": "build",
                "mavi_commit": "1234567890abcdef1234567890abcdef12345678",
                "platform_identity": _platform(),
            },
            "production_platform_lock_required",
        ),
        (
            {
                "selection": _selection(
                    verified=True,
                    runtime_qualified=False,
                    lock_qualified=True,
                ),
                "runtime_metadata": _metadata(),
                "configured_device_policy": "cpu",
                "configured_device_index": 0,
                "production_mode": True,
                "mavi_build": "build",
                "mavi_commit": "1234567890abcdef1234567890abcdef12345678",
                "platform_identity": _platform(),
            },
            "production_runtime_not_qualified",
        ),
    ],
)
def test_production_provenance_fails_closed(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        build_runtime_provenance(**kwargs)  # type: ignore[arg-type]


def test_provenance_requires_complete_runtime_dependency_versions() -> None:
    versions = dict(VERSIONS)
    versions.pop("mmdet")

    with pytest.raises(ValueError, match="runtime_dependency_versions_missing:mmdet"):
        build_runtime_provenance(
            selection=_selection(),
            runtime_metadata=_metadata(versions=versions),
            configured_device_policy="cpu",
            configured_device_index=0,
            production_mode=False,
            platform_identity=_platform(),
        )


@pytest.mark.parametrize(
    ("backend", "model_id", "vocabulary", "message"),
    [
        ("other", "rtmdet-m-coco-phase1", VOCABULARY, "runtime_backend_manifest_mismatch"),
        ("mmdetection", "other-model", VOCABULARY, "runtime_model_manifest_mismatch"),
        (
            "mmdetection",
            "rtmdet-m-coco-phase1",
            ("person", "car"),
            "runtime_vocabulary_manifest_mismatch",
        ),
    ],
)
def test_provenance_rejects_runtime_manifest_identity_drift(
    backend: str,
    model_id: str,
    vocabulary: tuple[str, ...],
    message: str,
) -> None:
    metadata = RuntimeMetadata(
        backend=backend,
        model_id=model_id,
        device="cpu",
        versions=VERSIONS,
        ordered_class_vocabulary=vocabulary,
    )

    with pytest.raises(ValueError, match=message):
        build_runtime_provenance(
            selection=_selection(),
            runtime_metadata=metadata,
            configured_device_policy="cpu",
            configured_device_index=0,
            production_mode=False,
            platform_identity=_platform(),
        )


def test_cuda_provenance_requires_matching_gpu_identity() -> None:
    gpu = GpuIdentity(
        name="NVIDIA RTX",
        index=1,
        vram_bytes=12 * 1024**3,
        driver_version="580.1",
        cuda_runtime_version="12.4",
        uuid="GPU-test-uuid",
        pci_bus_id="00000000:01:00.0",
        compute_capability="8.9",
    )

    provenance = build_runtime_provenance(
        selection=_selection(),
        runtime_metadata=_metadata(device="cuda:1"),
        configured_device_policy="cuda",
        configured_device_index=1,
        production_mode=False,
        gpu=gpu,
        platform_identity=_platform(),
    )

    assert provenance.actual_device == "cuda:1"
    assert provenance.gpu == gpu


def test_cuda_provenance_rejects_missing_gpu_identity() -> None:
    with pytest.raises(ValueError, match="cuda_gpu_identity_required"):
        build_runtime_provenance(
            selection=_selection(),
            runtime_metadata=_metadata(device="cuda:0"),
            configured_device_policy="cuda",
            configured_device_index=0,
            production_mode=False,
            platform_identity=_platform(),
        )


def test_runtime_contract_modules_do_not_import_heavy_ml_frameworks() -> None:
    runtime_root = Path(__file__).resolve().parents[1] / "mavi_vision" / "runtime"
    forbidden = {"torch", "mmdet", "mmcv", "supervision", "trackers"}

    for filename in ("interfaces.py", "errors.py", "provenance.py"):
        tree = ast.parse((runtime_root / filename).read_text(encoding="utf-8"))
        imported_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])

        assert imported_roots.isdisjoint(forbidden), (
            filename,
            sorted(imported_roots & forbidden),
        )




def test_mmdetection_module_has_no_top_level_heavy_ml_imports() -> None:
    runtime_root = Path(__file__).resolve().parents[1] / "mavi_vision" / "runtime"
    tree = ast.parse((runtime_root / "mmdetection.py").read_text(encoding="utf-8"))
    forbidden = {"torch", "torchvision", "mmdet", "mmcv", "mmengine", "supervision", "trackers"}
    imported_roots: set[str] = set()

    for node in tree.body:
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert imported_roots.isdisjoint(forbidden), sorted(
        imported_roots & forbidden
    )


def test_production_provenance_requires_full_git_commit_identity() -> None:
    with pytest.raises(ValueError, match="mavi_commit_invalid"):
        build_runtime_provenance(
            selection=_selection(verified=True),
            runtime_metadata=_metadata(),
            configured_device_policy="cpu",
            configured_device_index=0,
            production_mode=True,
            mavi_build="mavi-0.1.0",
            mavi_commit="short-sha",
            platform_identity=_platform(),
        )


def test_production_provenance_preserves_qualified_binary_build_identity() -> None:
    provenance = build_runtime_provenance(
        selection=_selection(verified=True),
        runtime_metadata=_metadata(),
        configured_device_policy="cpu",
        configured_device_index=0,
        production_mode=True,
        mavi_build="build",
        mavi_commit="1234567890abcdef1234567890abcdef12345678",
        platform_identity=_platform(),
    )

    assert provenance.dependency_versions["torch"] == "2.6.0+cpu"
    assert provenance.dependency_versions["torchvision"] == "0.21.0+cpu"
    assert provenance.verification_status == "verified"


def test_production_provenance_rejects_wrong_binary_build_with_same_semantic_version() -> None:
    versions = dict(LIVE_VERSIONS)
    versions["torch"] = "2.6.0+cu124"

    with pytest.raises(
        ValueError,
        match="runtime_binary_version_mismatch:torch",
    ):
        build_runtime_provenance(
            selection=_selection(verified=True),
            runtime_metadata=_metadata(versions=versions),
            configured_device_policy="cpu",
            configured_device_index=0,
            production_mode=True,
            mavi_build="build",
            mavi_commit="1234567890abcdef1234567890abcdef12345678",
            platform_identity=_platform(),
        )


def test_production_provenance_rejects_runtime_dependency_drift() -> None:
    versions = dict(VERSIONS)
    versions["torch"] = "2.7.0"

    with pytest.raises(
        ValueError,
        match="runtime_dependency_version_mismatch:torch",
    ):
        build_runtime_provenance(
            selection=_selection(verified=True),
            runtime_metadata=_metadata(versions=versions),
            configured_device_policy="cpu",
            configured_device_index=0,
            production_mode=True,
            mavi_build="build",
            mavi_commit="1234567890abcdef1234567890abcdef12345678",
            platform_identity=_platform(),
        )


def test_production_provenance_rejects_python_identity_drift() -> None:
    drifted_platform = PlatformIdentity(
        system="Linux",
        release="6.8.0",
        version="#1 SMP",
        machine="x86_64",
        processor="x86_64",
        python_version="3.12.13",
        python_implementation="CPython",
        python_build=("main", "different-build"),
        python_compiler="GCC 13.3.0",
    )

    with pytest.raises(ValueError, match="runtime_python_identity_mismatch"):
        build_runtime_provenance(
            selection=_selection(verified=True),
            runtime_metadata=_metadata(),
            configured_device_policy="cpu",
            configured_device_index=0,
            production_mode=True,
            mavi_build="build",
            mavi_commit="1234567890abcdef1234567890abcdef12345678",
            platform_identity=drifted_platform,
        )

def test_verified_release_retains_verified_label_in_development_only_when_binding_matches() -> None:
    provenance = build_runtime_provenance(
        selection=_selection(verified=True),
        runtime_metadata=_metadata(),
        configured_device_policy="auto",
        device_resolution_reason="cuda_pack_not_declared",
        configured_device_index=0,
        production_mode=False,
        platform_identity=_platform(),
    )

    assert provenance.verification_status == "verified"
    assert provenance.runtime_variant == "linux-x86_64-cpu"
    assert provenance.platform_lock_sha256 == SHA_A


def test_verified_release_downgrades_dependency_drift_in_development() -> None:
    versions = dict(VERSIONS)
    versions["torch"] = "2.7.0"

    provenance = build_runtime_provenance(
        selection=_selection(verified=True),
        runtime_metadata=_metadata(versions=versions),
        configured_device_policy="auto",
        device_resolution_reason="cuda_pack_not_declared",
        configured_device_index=0,
        production_mode=False,
        platform_identity=_platform(),
    )

    assert provenance.verification_status == "unverified"
    assert provenance.platform_lock_sha256 is None
    assert provenance.qualification_id == "qualification-a"
    assert provenance.qualification_sha256 == SHA_F


def test_verified_release_downgrades_python_drift_in_development() -> None:
    drifted_platform = PlatformIdentity(
        system="Linux",
        release="6.8.0",
        version="#1 SMP",
        machine="x86_64",
        processor="x86_64",
        python_version="3.12.13",
        python_implementation="CPython",
        python_build=("main", "different-build"),
        python_compiler="GCC 13.3.0",
    )

    provenance = build_runtime_provenance(
        selection=_selection(verified=True),
        runtime_metadata=_metadata(),
        configured_device_policy="auto",
        device_resolution_reason="cuda_pack_not_declared",
        configured_device_index=0,
        production_mode=False,
        platform_identity=drifted_platform,
    )

    assert provenance.verification_status == "unverified"
    assert provenance.platform_lock_sha256 is None


def test_verified_release_downgrades_pending_lock_in_development() -> None:
    provenance = build_runtime_provenance(
        selection=_selection(verified=True, lock_qualified=False),
        runtime_metadata=_metadata(),
        configured_device_policy="auto",
        device_resolution_reason="cuda_pack_not_declared",
        configured_device_index=0,
        production_mode=False,
        platform_identity=_platform(),
    )

    assert provenance.verification_status == "unverified"
    assert provenance.platform_lock_sha256 is None



_REASON_GPU = GpuIdentity(
    name="NVIDIA GeForce GTX 1650 Ti",
    index=0,
    vram_bytes=4 * 1024 * 1024 * 1024,
    driver_version="576.83",
    cuda_runtime_version="12.4",
    uuid="GPU-3f2b1c4d-0000-0000-0000-000000000001",
    pci_bus_id="00000000:01:00.0",
    compute_capability="7.5",
)


def _device_relationship(**overrides) -> None:
    arguments = {
        "configured_device_policy": "cpu",
        "configured_device_index": 0,
        "actual_device": "cpu",
        "device_resolution_reason": "explicit_cpu",
        "gpu": None,
        "production_mode": False,
    }
    arguments.update(overrides)
    _validate_device_relationship(**arguments)


def test_device_resolution_reason_vocabulary_is_closed() -> None:
    """The reason vocabulary is a contract, not an open string field."""
    assert DEVICE_RESOLUTION_REASONS == frozenset(
        {
            "explicit_cpu",
            "explicit_cuda",
            "cuda_selected",
            "cuda_pack_absent",
            "cuda_pack_integrity_failed",
            "cuda_pack_variant_mismatch",
            "cuda_pack_not_declared",
            "cuda_pack_id_mismatch",
            "cuda_driver_probe_unavailable",
            "cuda_device_unavailable",
            "cuda_driver_probe_failed",
        }
    )


def test_windows_launcher_emits_only_contracted_resolution_reasons() -> None:
    """PowerShell and Python must not silently diverge on reason codes."""
    launcher = (
        Path(__file__).resolve().parents[3]
        / "tools/setup/Start-MaviVisionWorker.ps1"
    )
    text = launcher.read_text(encoding="utf-8")
    emitted = {
        line.split('Reason = "', 1)[1].split('"', 1)[0]
        for line in text.splitlines()
        if 'Reason = "' in line
    }

    # An interpolated literal such as "explicit_$DevicePolicy" cannot be
    # verified against the vocabulary, so it fails this assertion too.
    assert emitted >= {"explicit_cpu", "explicit_cuda", "cuda_selected"}
    assert emitted <= DEVICE_RESOLUTION_REASONS


@pytest.mark.parametrize(
    "reason",
    ["cuda_pack_stale", "fell_back_to_cpu", "explicit_auto", "unknown"],
)
def test_unknown_device_resolution_reason_is_rejected(reason: str) -> None:
    """An unrecognised code cannot be correlated with the executed device."""
    with pytest.raises(ValueError, match="device_resolution_reason_unknown"):
        _device_relationship(device_resolution_reason=reason)


@pytest.mark.parametrize(
    "reason",
    ["cuda_pack_stale", "fell_back_to_cpu"],
)
def test_unknown_reason_cannot_smuggle_auto_result_into_production(
    reason: str,
) -> None:
    """Production must not carry an Auto result under an unknown code."""
    with pytest.raises(ValueError, match="device_resolution_reason_unknown"):
        _device_relationship(
            device_resolution_reason=reason,
            production_mode=True,
        )


def test_auto_policy_requires_a_resolution_reason() -> None:
    with pytest.raises(
        ValueError,
        match="auto_device_resolution_reason_required",
    ):
        _device_relationship(
            configured_device_policy="auto",
            device_resolution_reason=None,
        )


def test_explicit_policies_may_omit_a_resolution_reason() -> None:
    _device_relationship(device_resolution_reason=None)
    _device_relationship(
        configured_device_policy="cuda",
        actual_device="cuda:0",
        gpu=_REASON_GPU,
        device_resolution_reason=None,
    )


@pytest.mark.parametrize(
    "reason",
    sorted(
        {
            "cuda_pack_absent",
            "cuda_pack_integrity_failed",
            "cuda_pack_variant_mismatch",
            "cuda_pack_not_declared",
            "cuda_pack_id_mismatch",
            "cuda_driver_probe_unavailable",
            "cuda_device_unavailable",
            "cuda_driver_probe_failed",
        }
    ),
)
def test_auto_cpu_fallback_reasons_are_forbidden_in_production(
    reason: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="production_auto_resolution_reason_forbidden",
    ):
        _device_relationship(
            device_resolution_reason=reason,
            production_mode=True,
        )


@pytest.mark.parametrize(
    "reason",
    sorted(
        {
            "cuda_pack_absent",
            "cuda_pack_integrity_failed",
            "cuda_pack_variant_mismatch",
            "cuda_pack_not_declared",
            "cuda_pack_id_mismatch",
            "cuda_driver_probe_unavailable",
            "cuda_device_unavailable",
            "cuda_driver_probe_failed",
        }
    ),
)
def test_auto_cpu_fallback_reasons_require_cpu_execution(reason: str) -> None:
    with pytest.raises(
        ValueError,
        match="device_resolution_reason_device_mismatch",
    ):
        _device_relationship(
            configured_device_policy="cuda",
            actual_device="cuda:0",
            gpu=_REASON_GPU,
            device_resolution_reason=reason,
        )


def test_cuda_selection_reason_requires_cuda_execution() -> None:
    with pytest.raises(
        ValueError,
        match="device_resolution_reason_device_mismatch",
    ):
        _device_relationship(device_resolution_reason="cuda_selected")


def test_cuda_selection_reason_is_forbidden_in_production() -> None:
    with pytest.raises(
        ValueError,
        match="production_auto_resolution_reason_forbidden",
    ):
        _device_relationship(
            configured_device_policy="cuda",
            actual_device="cuda:0",
            gpu=_REASON_GPU,
            device_resolution_reason="cuda_selected",
            production_mode=True,
        )


@pytest.mark.parametrize(
    ("reason", "policy"),
    [("explicit_cpu", "cuda"), ("explicit_cuda", "cpu")],
)
def test_explicit_reasons_must_match_the_configured_policy(
    reason: str,
    policy: str,
) -> None:
    arguments = {"configured_device_policy": policy}
    if policy == "cuda":
        arguments["actual_device"] = "cuda:0"
        arguments["gpu"] = _REASON_GPU
    with pytest.raises(
        ValueError,
        match="device_resolution_reason_policy_mismatch",
    ):
        _device_relationship(device_resolution_reason=reason, **arguments)


def test_auto_cpu_fallback_reason_is_accepted_after_launcher_resolution() -> None:
    """The launcher resolves auto to cpu and hands Python the reason."""
    _device_relationship(device_resolution_reason="cuda_pack_absent")


def test_explicit_cuda_request_cannot_report_cpu_execution() -> None:
    with pytest.raises(ValueError, match="actual_device_policy_mismatch"):
        _device_relationship(
            configured_device_policy="cuda",
            device_resolution_reason="explicit_cuda",
        )


def test_resolution_reason_is_carried_into_runtime_provenance() -> None:
    provenance = build_runtime_provenance(
        selection=_selection(),
        runtime_metadata=_metadata(),
        configured_device_policy="cpu",
        device_resolution_reason="cuda_pack_integrity_failed",
        configured_device_index=0,
        production_mode=False,
        platform_identity=_platform(),
    )

    assert (
        provenance.device_resolution_reason
        == "cuda_pack_integrity_failed"
    )
