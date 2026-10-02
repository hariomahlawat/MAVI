"""In-memory v2 resolution results for unit tests (S2a.3).

The resolver itself is tested end to end against real files in ``test_resolver.py``.
The provenance, supervisor, runtime and client tests only need a resolved role of a
chosen shape, so this module builds the frozen v2 result dataclasses directly with
synthetic hashes. Nothing here reads a v1 shape.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from mavi_vision.common.analytical import ObjectClass
from mavi_vision.runtime.binding import (
    CapabilityBindingV2,
    ComponentBindingV2,
    RoleV2,
    RuntimePackVariantV2,
)
from mavi_vision.runtime.model_manifest_v2 import ModelArtifactV2, ModelManifestV2
from mavi_vision.runtime.profile import ByteTrackProfile, PipelineProfile
from mavi_vision.runtime.qualification import (
    RuntimePlatformVariantIdentity,
    RuntimePythonIdentity,
    RuntimeReleaseLockIdentity,
)
from mavi_vision.runtime.qualification_v2 import QualificationRecordV2, QualificationVariantV2
from mavi_vision.runtime.resolver import (
    CompletionContract,
    DetectorSelection,
    ResolvedCapability,
    ResolvedRole,
    ResolvedRuntimePack,
    RoleFamily,
)
from mavi_vision.runtime.runtime_profile_v2 import parse_runtime_profile_v2
from mavi_vision.runtime.variants import VariantClass
from tests.profile_fixtures import PRODUCTION_EVIDENCE_POLICY

REPOSITORY = Path(__file__).resolve().parents[3]
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64
SHA_9 = "9" * 64
BINDING_SHA = "1" * 64
LICENCE_SHA = "2" * 64
MODEL_PACK_ID = "mavi-model-v2-" + "3" * 64
RUNTIME_PACK_IDS = {
    "linux-x86_64-cpu": "mavi-runtime-v2-" + "4" * 64,
    "windows-x86_64-cpu": "mavi-runtime-v2-" + "5" * 64,
    "windows-x86_64-cuda": "mavi-runtime-v2-" + "6" * 64,
}
FAMILY_ID = "mmdetection-phase1-v1"
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
CPU_BINARY_VERSIONS = MappingProxyType({"torch": "2.6.0+cpu", "torchvision": "0.21.0+cpu"})
CUDA_BINARY_VERSIONS = MappingProxyType({"torch": "2.6.0+cu124", "torchvision": "0.21.0+cu124"})
LINUX_PYTHON = RuntimePythonIdentity(
    version="3.12.14",
    implementation="CPython",
    build=("main", "Aug 13 2026 02:47:42"),
    compiler="GCC 13.3.0",
)
WINDOWS_PYTHON = RuntimePythonIdentity(
    version="3.12.10",
    implementation="CPython",
    build=("tags/v3.12.10:0cc8128", "Apr  8 2025 12:21:36"),
    compiler="MSC v.1943 64 bit (AMD64)",
)


def pipeline_profile() -> PipelineProfile:
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
        evidence=PRODUCTION_EVIDENCE_POLICY,
    )


def _manifest(*, verified: bool, checkpoint_path: str, config_path: str) -> ModelManifestV2:
    checkpoint = ModelArtifactV2("checkpoint", checkpoint_path, SHA_B)
    config = ModelArtifactV2("resolved-config", config_path, SHA_C)
    licence = ModelArtifactV2("licence-notice", checkpoint_path.split("/", 1)[0] + "/LICENSE", LICENCE_SHA)
    return ModelManifestV2(
        schema_version="2.0",
        model_id="rtmdet-m-coco-phase1",
        model_version="1.0.0",
        capability_ids=("detector",),
        artifacts=(checkpoint, licence, config),
        pack_directory=checkpoint_path.split("/", 1)[0],
        input_contract_kind="video-frame-rgb",
        input_colour_space="RGB",
        output_schema_id="detector-output-v1",
        runtime_pack_family_ids=(FAMILY_ID,),
        licence_spdx_id="Apache-2.0",
        licence_notice=licence,
        licence_review_status="approved" if verified else "pending-review",
        verification_status="verified" if verified else "unverified",
        qualification_id="rtmdet-m-coco-phase1-v2" if verified else None,
        model_pack_id=MODEL_PACK_ID,
        capability_specific=MappingProxyType(
            {
                "detector": MappingProxyType(
                    {
                        "backend": "mmdetection",
                        "architecture": "rtmdet-m",
                        "classVocabulary": VOCABULARY,
                        "checkpointArtifactRole": "checkpoint",
                        "resolvedConfigArtifactRole": "resolved-config",
                    }
                )
            }
        ),
    )


def _record(*, passed_variants: frozenset[str]) -> QualificationRecordV2:
    variants = {}
    for variant in ("linux-x86_64-cpu", "linux-x86_64-cuda", "windows-x86_64-cpu", "windows-x86_64-cuda"):
        status: Literal["pending", "passed"] = "passed" if variant in passed_variants else "pending"
        variants[variant] = QualificationVariantV2(
            status=status,
            runtime_pack_id=RUNTIME_PACK_IDS.get(variant),
            gates=MappingProxyType({"offline-install": status}),
        )
    return QualificationRecordV2(
        qualification_id="rtmdet-m-coco-phase1-v2",
        capability_id="detector",
        model_pack_id=MODEL_PACK_ID,
        model_id="rtmdet-m-coco-phase1",
        model_manifest_sha256=SHA_A,
        artifact_sha256=MappingProxyType({"checkpoint": SHA_B, "licence-notice": LICENCE_SHA, "resolved-config": SHA_C}),
        runtime_pack_family_id=FAMILY_ID,
        runtime_profile_sha256=SHA_E,
        output_schema_id="detector-output-v1",
        pipeline_profile_id="phase1-detection-tracking-v1",
        pipeline_profile_sha256=SHA_D,
        gate_set_ids=("common-v1", "detector-v1"),
        variants=MappingProxyType(variants),
        qualified_profiles=(),
        profile_runtime_variants=MappingProxyType({}),
        profile_policy_sha256=MappingProxyType({}),
        profile_evidence_gates=MappingProxyType({}),
        overall_result="passed" if passed_variants else "pending",
        supersedes_qualification_id="rtmdet-m-coco-phase1-v1",
    )


def _identities(*, runtime_qualified: bool, locks_qualified: bool):
    variants = {
        "linux-x86_64-cpu": RuntimePlatformVariantIdentity(
            status="qualified-hosted-cpu", python_identity=LINUX_PYTHON, binary_versions=CPU_BINARY_VERSIONS
        ),
        "windows-x86_64-cpu": RuntimePlatformVariantIdentity(
            status="qualified-hosted-cpu", python_identity=WINDOWS_PYTHON, binary_versions=CPU_BINARY_VERSIONS
        ),
        "linux-x86_64-cuda": RuntimePlatformVariantIdentity(
            status="qualified-hardware" if runtime_qualified else "pending-hardware-qualification",
            python_identity=LINUX_PYTHON if runtime_qualified else None,
            binary_versions=CUDA_BINARY_VERSIONS if runtime_qualified else None,
        ),
        "windows-x86_64-cuda": RuntimePlatformVariantIdentity(
            status="qualified-hardware" if runtime_qualified else "pending-hardware-qualification",
            python_identity=WINDOWS_PYTHON if runtime_qualified else None,
            binary_versions=CUDA_BINARY_VERSIONS if runtime_qualified else None,
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
                else ("pending-wheelhouse-freeze" if variant.endswith("-cpu") else "pending-hardware-qualification")
            ),
            artifact=f"locks/{variant}.lock" if locks_qualified else None,
            sha256=digest if locks_qualified else None,
        )
        for variant, digest in lock_hashes.items()
    }
    return MappingProxyType(variants), MappingProxyType(locks)


def make_selection(
    *,
    verified: bool = False,
    runtime_qualified: bool | None = None,
    lock_qualified: bool | None = None,
    runtime_variant: str = "linux-x86_64-cpu",
    runtime_pack_source: Literal["installed-pack", "unpacked-environment"] | None = None,
    passed_variants: frozenset[str] | None = None,
    override: str | None = None,
    profile: PipelineProfile | None = None,
    checkpoint_path: Path = Path("models/release/checkpoint.pth"),
    resolved_config_path: Path = Path("models/release/config.py"),
    logical_checkpoint: str = "release/checkpoint.pth",
    logical_config: str = "release/config.py",
    component_binding_sha256: str = BINDING_SHA,
) -> DetectorSelection:
    """A resolved detector role of the requested shape.

    Defaults mirror today's truth: an unverified manifest in an unpacked environment.
    ``verified=True`` also installs the Runtime Pack and passes the observed variant,
    unless told otherwise, so each test states only the one thing it changes.
    """
    qualified = verified if runtime_qualified is None else runtime_qualified
    locks_qualified = qualified if lock_qualified is None else lock_qualified
    if runtime_pack_source is None:
        runtime_pack_source = "installed-pack" if verified else "unpacked-environment"
    if passed_variants is None:
        passed_variants = frozenset({runtime_variant}) if verified else frozenset()
    variants, locks = _identities(runtime_qualified=qualified, locks_qualified=locks_qualified)
    runtime_profile = parse_runtime_profile_v2(
        json.loads((REPOSITORY / "src/vision/runtime/mmdetection-phase1-v1/runtime.json").read_text(encoding="utf-8"))
    )
    runtime_profile = runtime_profile.model_copy(update={"qualification_status": "qualified" if qualified else "partial"})
    role = RoleV2(
        role_id="vision",
        runtime_pack_family_id=FAMILY_ID,
        capability_ids=("detector",),
        entry_point="mavi_vision.worker.main",
        readiness_contract="worker-health-v2",
        provenance_contract="vision-job-complete-v3.3",
    )
    entries = {
        variant: RuntimePackVariantV2(
            runtime_pack_id=pack_id,
            third_party_lock_sha256=SHA_A,
            runtime_requirements_sha256=SHA_B,
            native_abi="fixture-abi",
        )
        for variant, pack_id in RUNTIME_PACK_IDS.items()
    }
    capability_binding = CapabilityBindingV2(
        capability_id="detector",
        role_id="vision",
        model_pack_id=MODEL_PACK_ID,
        qualification_id="rtmdet-m-coco-phase1-v2",
        enabled=True,
    )
    binding = ComponentBindingV2(
        binding_id="phase1-v2",
        runtime_pack_families=MappingProxyType({FAMILY_ID: MappingProxyType(entries)}),
        roles=MappingProxyType({"vision": role}),
        capability_bindings=(capability_binding,),
        component_binding_sha256=component_binding_sha256,
    )
    family = RoleFamily(
        role=role,
        runtime_profile=runtime_profile,
        runtime_profile_path=Path("src/vision/runtime/mmdetection-phase1-v1/runtime.json"),
        runtime_profile_sha256=SHA_E,
        variant_classes=MappingProxyType(
            {
                "linux-x86_64-cpu": VariantClass.DEPLOYABLE,
                "windows-x86_64-cpu": VariantClass.DEPLOYABLE,
                "windows-x86_64-cuda": VariantClass.DEPLOYABLE,
                "linux-x86_64-cuda": VariantClass.KNOWN_NOT_RELEASABLE,
            }
        ),
        runtime_semantic_graph=MappingProxyType(dict(VERSIONS)),
        runtime_platform_variants=variants,
        runtime_release_locks=locks,
    )
    entry = entries.get(runtime_variant, RuntimePackVariantV2("mavi-runtime-v2-" + "7" * 64, SHA_A, SHA_B, "fixture-abi"))
    runtime_pack = ResolvedRuntimePack(
        runtime_pack_family_id=FAMILY_ID,
        runtime_variant=runtime_variant,
        binding_entry=entry,
        lock_path=Path(f"src/vision/runtime/mmdetection-phase1-v1/{runtime_variant}.lock"),
        runtime_pack_source=runtime_pack_source,
        runtime_pack_id=entry.runtime_pack_id if runtime_pack_source == "installed-pack" else None,
    )
    manifest = _manifest(verified=verified, checkpoint_path=logical_checkpoint, config_path=logical_config)
    capability = ResolvedCapability(
        capability_id="detector",
        binding=capability_binding,
        manifest=manifest,
        manifest_path=Path("models/manifests/rtmdet-m-coco-phase1-v2.json"),
        manifest_sha256=SHA_A,
        model_pack_id=MODEL_PACK_ID,
        artifact_paths=MappingProxyType(
            {"checkpoint": checkpoint_path, "resolved-config": resolved_config_path, "licence-notice": Path("LICENSE")}
        ),
        qualification=_record(passed_variants=passed_variants),
        qualification_path=Path("models/qualifications/rtmdet-m-coco-phase1-v2.json"),
        qualification_sha256=SHA_F,
    )
    resolved = ResolvedRole(
        role=role,
        binding=binding,
        binding_path=Path("src/vision/config/components/phase1-bindings-v2.json"),
        family=family,
        runtime_pack=runtime_pack,
        capabilities=MappingProxyType({"detector": capability}),
        pipeline_profile=profile or pipeline_profile(),
        pipeline_profile_sha256=SHA_D,
        completion=CompletionContract(version=override or "3.3", override=override),
        production_mode=False,
    )
    return resolved.detector_selection()


def with_family(selection: DetectorSelection, **changes) -> DetectorSelection:
    """Rebuild a selection with changed runtime-family identity views."""
    resolved = selection.resolved_role
    family = replace(resolved.family, **changes)
    return replace(resolved, family=family).detector_selection()


__all__ = [
    "BINDING_SHA",
    "CPU_BINARY_VERSIONS",
    "CUDA_BINARY_VERSIONS",
    "MODEL_PACK_ID",
    "RUNTIME_PACK_IDS",
    "SHA_A",
    "SHA_B",
    "SHA_C",
    "SHA_D",
    "SHA_E",
    "SHA_F",
    "VERSIONS",
    "VOCABULARY",
    "make_selection",
    "pipeline_profile",
    "with_family",
]
