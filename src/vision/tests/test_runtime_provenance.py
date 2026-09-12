from __future__ import annotations

import ast
from pathlib import Path
from types import MappingProxyType

import pytest

from mavi_vision.common.analytical import ObjectClass
from mavi_vision.runtime.interfaces import RuntimeMetadata
from mavi_vision.runtime.manifest import ArtifactRef, ModelManifest
from mavi_vision.runtime.profile import ByteTrackProfile, PipelineProfile
from mavi_vision.runtime.provenance import (
    GpuIdentity,
    PlatformIdentity,
    build_runtime_provenance,
)
from mavi_vision.runtime.qualification import (
    QualificationRecord,
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
    "torch": "2.6.0+cpu",
    "torchvision": "0.21.0+cpu",
    "mmdet": "3.3.0",
    "mmcv": "2.1.0",
    "mmengine": "0.10.7",
    "trackers": "2.6.0",
    "supervision": "0.30.2",
    "scipy": "1.18.1",
    "numpy": "2.5.3",
    "opencv": "5.0.0",
    "av": "16.1.0",
    "pillow": "11.3.0",
}


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
        profile_version="1.0.0-candidate",
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
            track_activation_threshold=0.25,
            high_confidence_threshold=0.6,
            minimum_matching_threshold=0.8,
            minimum_consecutive_frames=1,
            lost_track_buffer_seconds=1.0,
        ),
        frame_policy="every-frame",
    )


def _selection(*, verified: bool = False) -> VerifiedReleaseSelection:
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
    )


def _metadata(*, device: str = "cpu", versions: dict[str, str] | None = None) -> RuntimeMetadata:
    return RuntimeMetadata(
        backend="mmdetection",
        model_id="rtmdet-m-coco-phase1",
        device=device,
        versions=VERSIONS if versions is None else versions,
        ordered_class_vocabulary=VOCABULARY,
    )


def test_development_provenance_is_complete_immutable_and_explicitly_unknown() -> None:
    provenance = build_runtime_provenance(
        selection=_selection(),
        runtime_metadata=_metadata(),
        configured_device_policy="auto",
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
        platform_lock_sha256=SHA_A,
        platform_identity=_platform(),
    )

    assert provenance.verification_status == "verified"
    assert provenance.qualification_id == "qualification-a"
    assert provenance.qualification_sha256 == SHA_F
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
                "platform_lock_sha256": SHA_A,
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
                "platform_lock_sha256": SHA_A,
                "platform_identity": _platform(),
            },
            "production_mavi_identity_required",
        ),
        (
            {
                "selection": _selection(verified=True),
                "runtime_metadata": _metadata(),
                "configured_device_policy": "cpu",
                "configured_device_index": 0,
                "production_mode": True,
                "mavi_build": "build",
                "mavi_commit": "commit",
                "platform_identity": _platform(),
            },
            "production_platform_lock_required",
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
