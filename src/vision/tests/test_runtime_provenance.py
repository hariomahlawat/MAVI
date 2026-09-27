from __future__ import annotations

import ast
from pathlib import Path
from dataclasses import replace
from types import MappingProxyType

import pytest

from mavi_vision.runtime.interfaces import RuntimeMetadata
from mavi_vision.common.control_plane import (
    AUTO_CPU_DEVICE_RESOLUTION_REASONS,
    DEVICE_RESOLUTION_REASONS,
)
from mavi_vision.runtime.provenance import (
    GpuIdentity,
    PlatformIdentity,
    _validate_device_relationship,
    build_runtime_provenance,
)
from mavi_vision.runtime.resolver import DetectorSelection
from tests.detector_selection_fixtures import (
    BINDING_SHA,
    CPU_BINARY_VERSIONS,
    CUDA_BINARY_VERSIONS,
    MODEL_PACK_ID,
    RUNTIME_PACK_IDS,
    SHA_A,
    SHA_B,
    SHA_C,
    SHA_D,
    SHA_E,
    SHA_F,
    VERSIONS,
    VOCABULARY,
    make_selection,
    pipeline_profile,
)

LIVE_VERSIONS = {
    **VERSIONS,
    "torch": "2.6.0+cpu",
    "torchvision": "0.21.0+cpu",
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


def _windows_platform() -> PlatformIdentity:
    return PlatformIdentity(
        system="Windows",
        release="11",
        version="10.0.26100",
        machine="AMD64",
        processor="Intel64 Family 6",
        python_version="3.12.10",
        python_implementation="CPython",
        python_build=("tags/v3.12.10:0cc8128", "Apr  8 2025 12:21:36"),
        python_compiler="MSC v.1943 64 bit (AMD64)",
    )


def _profile():
    return pipeline_profile()


def _selection(**kwargs) -> DetectorSelection:
    return make_selection(**kwargs)


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
    assert provenance.qualification_id == "rtmdet-m-coco-phase1-v2"
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

    # Linux CUDA is class A and never resolves; a CUDA execution is Windows CUDA.
    provenance = build_runtime_provenance(
        selection=_selection(runtime_variant="windows-x86_64-cuda"),
        runtime_metadata=_metadata(device="cuda:1"),
        configured_device_policy="cuda",
        configured_device_index=1,
        production_mode=False,
        gpu=gpu,
        platform_identity=_windows_platform(),
    )

    assert provenance.actual_device == "cuda:1"
    assert provenance.gpu == gpu


def test_cuda_provenance_rejects_missing_gpu_identity() -> None:
    with pytest.raises(ValueError, match="cuda_gpu_identity_required"):
        build_runtime_provenance(
            selection=_selection(runtime_variant="windows-x86_64-cuda"),
            runtime_metadata=_metadata(device="cuda:0"),
            configured_device_policy="cuda",
            configured_device_index=0,
            production_mode=False,
            platform_identity=_windows_platform(),
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
    assert provenance.qualification_id == "rtmdet-m-coco-phase1-v2"
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
    """PowerShell and Python must not silently diverge on reason codes.

    The Auto decision moved into `Mavi.VisionRuntime.Common.psm1` so it could be
    called and therefore tested; the explicit policies are still decided in the
    launcher. Both files are read, because the contract is about what the
    Windows side can emit, not about which file happens to hold it.
    """
    setup = Path(__file__).resolve().parents[3] / "tools/setup"
    text = "\n".join(
        (setup / name).read_text(encoding="utf-8")
        for name in (
            "Start-MaviVisionWorker.ps1",
            "Mavi.VisionRuntime.Common.psm1",
        )
    )
    # `Reason = "` is a suffix of `deviceResolutionReason = "`, so one scrape
    # captures both the Auto result object and the explicit assignments.
    emitted = {
        line.split('Reason = "', 1)[1].split('"', 1)[0]
        for line in text.splitlines()
        if 'Reason = "' in line
    }

    # An interpolated literal such as "explicit_$DevicePolicy" cannot be
    # verified against the vocabulary, so it fails this assertion too.
    assert emitted >= {"explicit_cpu", "explicit_cuda", "cuda_selected"}
    assert emitted <= DEVICE_RESOLUTION_REASONS


def test_every_auto_cpu_reason_is_reachable_from_the_windows_auto_decision() -> None:
    """A reason the vocabulary contracts but nothing emits cannot be observed."""
    module = (
        Path(__file__).resolve().parents[3]
        / "tools/setup/Mavi.VisionRuntime.Common.psm1"
    ).read_text(encoding="utf-8")
    emitted = {
        line.split('Reason = "', 1)[1].split('"', 1)[0]
        for line in module.splitlines()
        if 'Reason = "' in line
    }

    assert AUTO_CPU_DEVICE_RESOLUTION_REASONS <= emitted
    assert "cuda_selected" in emitted


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


def test_development_cuda_execution_is_recorded_but_never_labelled_verified(
    monkeypatch,
) -> None:
    """Where the supervisor's widened Auto check deliberately stops.

    `RuntimeSupervisor` now lets Development `Auto` select a GPU whose variant
    is `qualified-development-hardware` (ADR-009's Development state). Provenance
    is not widened to match: its `-cuda` bar stays `qualified-hardware`, and a
    profile carrying any Development-qualified variant is `partial` anyway, so
    the record is `unverified`. That is the intended asymmetry -- Development may
    run on the GPU, and the run is fully described, but it never inherits the
    release's verified label. The C6 evidence is the description, not the label.
    """
    selection = _selection(verified=True, runtime_variant="windows-x86_64-cuda")
    variants = dict(selection.runtime_platform_variants)
    variants["windows-x86_64-cuda"] = replace(
        variants["windows-x86_64-cuda"],
        status="qualified-development-hardware",
    )
    selection = replace(
        selection,
        runtime_platform_variants=MappingProxyType(variants),
        runtime_qualification_status="partial",
    )

    provenance = build_runtime_provenance(
        selection=selection,
        runtime_metadata=_metadata(device="cuda:0"),
        configured_device_policy="auto",
        device_resolution_reason="cuda_selected",
        configured_device_index=0,
        production_mode=False,
        platform_identity=_windows_platform(),
        gpu=GpuIdentity(
            name="NVIDIA GeForce RTX 2080 Ti",
            index=0,
            vram_bytes=11 * 1024**3,
            driver_version="560.94",
            cuda_runtime_version="12.4",
            uuid="GPU-3f2b1c4d-0000-0000-0000-000000000001",
            pci_bus_id="00000000:01:00.0",
            compute_capability="7.5",
        ),
    )

    assert provenance.verification_status == "unverified"
    assert provenance.platform_lock_sha256 is None
    # The execution itself is still fully described.
    assert provenance.actual_device == "cuda:0"
    assert provenance.device_resolution_reason == "cuda_selected"
    assert provenance.gpu is not None
    assert provenance.gpu.compute_capability == "7.5"


# --------------------------------------------------------------------------- S2a.3


def _build(selection, *, production_mode=False, **kwargs):
    arguments = {
        "selection": selection,
        "runtime_metadata": _metadata(),
        "configured_device_policy": "cpu",
        "configured_device_index": 0,
        "production_mode": production_mode,
        "platform_identity": _platform(),
    }
    if production_mode:
        arguments.update(mavi_build="build", mavi_commit="1234567890abcdef1234567890abcdef12345678")
    arguments.update(kwargs)
    return build_runtime_provenance(**arguments)


def test_pack_ids_from_resolver() -> None:
    selection = _selection(verified=True)
    provenance = _build(selection)

    assert provenance.capability_id == "detector"
    assert provenance.model_pack_id == MODEL_PACK_ID
    assert provenance.runtime_pack_id == RUNTIME_PACK_IDS["linux-x86_64-cpu"]
    assert provenance.runtime_pack_source == "installed-pack"
    assert provenance.component_binding_sha256 == BINDING_SHA
    # Every identity is the resolution's; none is recomputed here.
    assert provenance.model_manifest_sha256 == selection.capability.manifest_sha256
    assert provenance.qualification_sha256 == selection.capability.qualification_sha256
    assert provenance.runtime_profile_sha256 == selection.resolved_role.family.runtime_profile_sha256


def test_the_binding_sha_is_the_resolved_binding_file_identity() -> None:
    other = "8" * 64
    assert _build(_selection(component_binding_sha256=other)).component_binding_sha256 == other


def test_no_installed_pack_yields_null_and_unpacked_source() -> None:
    provenance = _build(_selection())

    assert provenance.runtime_pack_source == "unpacked-environment"
    assert provenance.runtime_pack_id is None
    assert provenance.verification_status == "unverified"


def test_verified_requires_pack() -> None:
    unpacked = _selection(verified=True, runtime_pack_source="unpacked-environment")
    # Development downgrades a verified manifest outside an installed pack...
    provenance = _build(unpacked)
    assert provenance.verification_status == "unverified"
    assert provenance.runtime_pack_id is None
    assert provenance.platform_lock_sha256 is None
    # ...and Production refuses it.
    with pytest.raises(ValueError, match="runtime_pack_required"):
        _build(unpacked, production_mode=True)


def test_verified_requires_the_observed_variant_to_have_passed() -> None:
    selection = _selection(verified=True, passed_variants=frozenset({"windows-x86_64-cpu"}))
    assert _build(selection).verification_status == "unverified"
    with pytest.raises(ValueError, match="qualification_variant_not_passed"):
        _build(selection, production_mode=True)


def test_verified_with_installed_pack_and_passed_variant_is_verified() -> None:
    provenance = _build(_selection(verified=True))
    assert provenance.verification_status == "verified"
    assert provenance.platform_lock_sha256 == SHA_A


@pytest.mark.parametrize("override", ["3.1", "3.0"])
def test_override_forces_unverified(override: str) -> None:
    provenance = _build(_selection(verified=True, override=override))
    assert provenance.verification_status == "unverified"
    assert provenance.platform_lock_sha256 is None
    with pytest.raises(ValueError, match="completion_override_forbidden_in_production"):
        _build(_selection(verified=True, override=override), production_mode=True)


def test_the_live_runtime_must_be_on_the_resolved_variant() -> None:
    # Resolved for windows-x86_64-cpu, running on a Linux host: never relabelled.
    with pytest.raises(ValueError, match="runtime_variant_resolution_mismatch"):
        _build(_selection(runtime_variant="windows-x86_64-cpu"))


def _provenance_fields(**changes):
    base = _build(_selection())
    return replace(base, **changes)


def test_an_unpacked_environment_cannot_carry_a_runtime_pack_id() -> None:
    with pytest.raises(ValueError, match="runtime_pack_id_fabricated"):
        _provenance_fields(runtime_pack_id=RUNTIME_PACK_IDS["linux-x86_64-cpu"])


def test_an_installed_pack_must_name_its_runtime_pack() -> None:
    with pytest.raises(ValueError, match="runtime_pack_id_invalid"):
        _provenance_fields(runtime_pack_source="installed-pack", runtime_pack_id=None)


def test_an_unpacked_environment_is_never_verified() -> None:
    base = _build(_selection(verified=True))
    with pytest.raises(ValueError, match="unpacked_environment_cannot_be_verified"):
        replace(base, runtime_pack_source="unpacked-environment", runtime_pack_id=None)


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"capability_id": "face-recognition"}, "capability_id_invalid"),
        ({"model_pack_id": "mavi-model-v1-" + "3" * 64}, "model_pack_id_invalid"),
        ({"component_binding_sha256": "0" * 63}, "component_binding_sha256_invalid"),
        ({"runtime_pack_source": "installed"}, "runtime_pack_source_invalid"),
    ],
)
def test_component_identity_fields_are_validated(changes, code) -> None:
    with pytest.raises(ValueError, match=code):
        _provenance_fields(**changes)


def test_provenance_has_no_default_component_identity() -> None:
    from dataclasses import MISSING, fields

    from mavi_vision.runtime.provenance import RuntimeProvenance

    defaults = {field.name: field.default for field in fields(RuntimeProvenance)}
    for name in ("capability_id", "model_pack_id", "runtime_pack_id", "runtime_pack_source", "component_binding_sha256"):
        assert defaults[name] is MISSING, name
