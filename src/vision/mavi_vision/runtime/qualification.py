"""Runtime-profile schema pieces and runtime identity shared by every loader.

Stage 2 S2a.3 removed the v1 runtime profile, qualification record and release
selection (ADR-014; S2a plan §4.3, §5.1). What stays here is shared by runtime
profile v2 (``runtime_profile_v2``), qualification record v2
(``qualification_v2``) and the resolver: the field schemas, the evidence-shape and
graph rules, the runtime identity views and the release-lock verification. No v1
artefact can be read through this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mavi_vision.runtime.offline_lock import (
    OfflineLockError,
    load_offline_runtime_lock,
    validate_offline_runtime_lock_for_runtime,
)

from mavi_vision.runtime.manifest import (
    ArtifactRef,
    ReleaseMetadataError,
    resolve_release_artifact,
    sha256_release_file,
    validate_sha256_hex,
)
from mavi_vision.runtime.variants import RUNTIME_VARIANTS

if TYPE_CHECKING:
    from mavi_vision.runtime.runtime_profile_v2 import RuntimeProfileV2


@dataclass(frozen=True, slots=True)
class RuntimePythonIdentity:
    version: str
    implementation: str
    build: tuple[str, str]
    compiler: str


@dataclass(frozen=True, slots=True)
class RuntimeDevelopmentHardwareEvidenceIdentity:
    host_observation_sha256: str
    evidence_bundle_sha256: str
    source_head_sha: str
    captured_at_utc: str
    operator_reference: str


@dataclass(frozen=True, slots=True)
class RuntimePlatformVariantIdentity:
    status: Literal[
        "qualified-hosted-cpu",
        "qualified-hardware",
        "qualified-development-hardware",
        "pending-hardware-qualification",
    ]
    python_identity: RuntimePythonIdentity | None
    binary_versions: Mapping[str, str] | None = None
    development_evidence: (
        RuntimeDevelopmentHardwareEvidenceIdentity | None
    ) = None

    def __post_init__(self) -> None:
        if self.binary_versions is not None:
            object.__setattr__(
                self,
                "binary_versions",
                MappingProxyType(dict(self.binary_versions)),
            )


@dataclass(frozen=True, slots=True)
class RuntimeReleaseLockIdentity:
    status: Literal[
        "pending-wheelhouse-freeze",
        "pending-hardware-qualification",
        "qualified-offline-lock",
    ]
    artifact: str | None
    sha256: str | None


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _QualificationEvidenceSchema(_StrictModel):
    kind: str
    reference: str
    sha256: str

    @field_validator("kind", "reference")
    @classmethod
    def validate_nonempty_text(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("qualification_evidence_text_invalid")
        return value

    @field_validator("sha256")
    @classmethod
    def validate_evidence_sha256(cls, value: str) -> str:
        validate_sha256_hex(value)
        return value


class _ProfileQualificationSchema(_StrictModel):
    deployment_profile_policy_sha256: str = Field(
        alias="deploymentProfilePolicySha256"
    )
    runtime_variant: Literal[
        "windows-x86_64-cpu",
        "windows-x86_64-cuda",
        "linux-x86_64-cpu",
        "linux-x86_64-cuda",
    ] = Field(alias="runtimeVariant")
    evidence: dict[str, _QualificationEvidenceSchema]

    @field_validator("deployment_profile_policy_sha256")
    @classmethod
    def validate_policy_sha256(cls, value: str) -> str:
        validate_sha256_hex(value)
        return value

    @field_validator("evidence")
    @classmethod
    def validate_profile_evidence(
        cls,
        value: dict[str, _QualificationEvidenceSchema],
    ) -> dict[str, _QualificationEvidenceSchema]:
        if not value:
            raise ValueError("qualification_profile_evidence_empty")
        if any(not key or key != key.strip() for key in value):
            raise ValueError("qualification_profile_gate_name_invalid")
        return value


class _RuntimeSemanticGraphSchema(_StrictModel):
    torch: str
    torchvision: str
    mmcv: str
    mmengine: str
    mmdet: str
    trackers: str
    supervision: str
    scipy: str
    numpy: str
    opencv: str
    av: str
    opencv_python: str = Field(alias="opencvPython")
    pillow: str

    @field_validator(
        "torch",
        "torchvision",
        "mmcv",
        "mmengine",
        "mmdet",
        "trackers",
        "supervision",
        "scipy",
        "numpy",
        "opencv",
        "av",
        "opencv_python",
        "pillow",
    )
    @classmethod
    def validate_version(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("runtime_semantic_version_invalid")
        return value


class _RuntimePythonIdentitySchema(_StrictModel):
    version: str
    implementation: Literal["CPython"]
    build: tuple[str, str]
    compiler: str

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        parts = value.split(".")
        if len(parts) != 3 or any(not part.isdigit() for part in parts):
            raise ValueError("runtime_python_version_invalid")
        return value

    @field_validator("build")
    @classmethod
    def validate_build(cls, value: tuple[str, str]) -> tuple[str, str]:
        if len(value) != 2 or any(not part or part != part.strip() for part in value):
            raise ValueError("runtime_python_build_invalid")
        return value

    @field_validator("compiler")
    @classmethod
    def validate_compiler(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("runtime_python_compiler_invalid")
        return value


class _RuntimeBinaryVersionsSchema(_StrictModel):
    torch: str
    torchvision: str

    @field_validator("torch", "torchvision")
    @classmethod
    def validate_binary_version(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("runtime_binary_version_invalid")
        if "+" not in value:
            raise ValueError("runtime_binary_build_tag_required")
        return value


class _RuntimeDevelopmentHardwareEvidenceSchema(_StrictModel):
    host_observation_sha256: str = Field(
        alias="hostObservationSha256"
    )
    evidence_bundle_sha256: str = Field(
        alias="evidenceBundleSha256"
    )
    source_head_sha: str = Field(alias="sourceHeadSha")
    captured_at_utc: str = Field(alias="capturedAtUtc")
    operator_reference: str = Field(alias="operatorReference")

    @field_validator(
        "host_observation_sha256",
        "evidence_bundle_sha256",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        validate_sha256_hex(value)
        return value

    @field_validator("source_head_sha")
    @classmethod
    def validate_source_head_sha(cls, value: str) -> str:
        if (
            len(value) not in {40, 64}
            or value.lower() != value
            or any(ch not in "0123456789abcdef" for ch in value)
        ):
            raise ValueError(
                "runtime_development_evidence_head_sha_invalid"
            )
        return value

    @field_validator(
        "captured_at_utc",
        "operator_reference",
    )
    @classmethod
    def validate_nonempty_text(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError(
                "runtime_development_evidence_text_invalid"
            )
        return value


def check_platform_variant_evidence(
    *,
    status: str,
    workflow_run_id: str | None,
    job_id: str | None,
    evidence_head_sha: str | None,
    runtime_identity: tuple[object | None, ...],
    development_evidence: object | None,
) -> None:
    """The one evidence-shape rule for a runtime-profile platform variant.

    ``runtime_identity`` holds the fields a qualified variant must carry: the
    Python identity and binary versions. Model identity no longer lives in the
    runtime profile (ADR-014 §4a); the v1 profile's per-variant resolved-config
    SHA is gone.
    """
    ci_evidence = (workflow_run_id, job_id, evidence_head_sha)

    if status in {"qualified-hosted-cpu", "qualified-hardware"}:
        if (
            any(value is None for value in ci_evidence)
            or any(value is None for value in runtime_identity)
            or development_evidence is not None
        ):
            raise ValueError("runtime_platform_evidence_required")
        assert workflow_run_id is not None
        assert job_id is not None
        assert evidence_head_sha is not None
        if not workflow_run_id.isdigit() or not job_id.isdigit():
            raise ValueError("runtime_platform_evidence_id_invalid")
        if (
            len(evidence_head_sha) not in {40, 64}
            or evidence_head_sha.lower() != evidence_head_sha
            or any(ch not in "0123456789abcdef" for ch in evidence_head_sha)
        ):
            raise ValueError("runtime_platform_head_sha_invalid")
    elif status == "qualified-development-hardware":
        if (
            any(value is not None for value in ci_evidence)
            or any(value is None for value in runtime_identity)
            or development_evidence is None
        ):
            raise ValueError("runtime_development_platform_evidence_required")
    else:
        all_evidence = (*ci_evidence, *runtime_identity, development_evidence)
        if any(value is not None for value in all_evidence):
            raise ValueError("runtime_pending_platform_has_evidence")


class _RuntimeReleaseLockSchema(_StrictModel):
    status: Literal[
        "pending-wheelhouse-freeze",
        "pending-hardware-qualification",
        "qualified-offline-lock",
    ]
    artifact: str | None = None
    sha256: str | None = None

    @model_validator(mode="after")
    def validate_lock_shape(self) -> "_RuntimeReleaseLockSchema":
        if self.status == "qualified-offline-lock":
            if self.artifact is None or self.sha256 is None:
                raise ValueError("runtime_release_lock_evidence_required")
            from mavi_vision.runtime.manifest import validate_logical_relative_path

            validate_logical_relative_path(self.artifact)
            validate_sha256_hex(self.sha256)
        elif self.artifact is not None or self.sha256 is not None:
            raise ValueError("runtime_pending_lock_has_evidence")
        return self


_RUNTIME_VARIANTS = RUNTIME_VARIANTS


def check_runtime_profile_id(value: str) -> str:
    if not value or value != value.strip():
        raise ValueError("runtime_profile_id_invalid")
    return value


def check_runtime_python_minor(value: str) -> str:
    if value not in {"3.11", "3.12"}:
        raise ValueError("runtime_python_minor_invalid")
    return value


def check_runtime_platform_variant_statuses(value: Mapping[str, object]) -> None:
    """Platform-variant keys equal the closed universe; statuses fit CPU/CUDA."""
    if set(value) != _RUNTIME_VARIANTS:
        raise ValueError("runtime_platform_variants_incomplete")

    for variant_name, variant in value.items():
        status = getattr(variant, "status")
        if variant_name.endswith("-cuda"):
            if status not in {
                "pending-hardware-qualification",
                "qualified-development-hardware",
                "qualified-hardware",
            }:
                raise ValueError("runtime_cuda_variant_status_invalid")
        elif variant_name.endswith("-cpu"):
            if status not in {
                "pending-hardware-qualification",
                "qualified-hosted-cpu",
            }:
                raise ValueError("runtime_cpu_variant_status_invalid")
        else:
            raise ValueError("runtime_platform_variant_unknown")


def check_runtime_release_lock_keys(value: Mapping[str, object]) -> None:
    if set(value) != _RUNTIME_VARIANTS:
        raise ValueError("runtime_release_locks_incomplete")


def check_runtime_graph_relationships(
    *,
    python_minor: str,
    semantic_graph: "_RuntimeSemanticGraphSchema",
    platform_variants: Mapping[str, object],
) -> None:
    """Python-minor and torch/torchvision binary-vs-semantic agreement per variant."""
    for variant in platform_variants.values():
        python_identity = getattr(variant, "python_identity")
        binary_versions = getattr(variant, "binary_versions")
        if python_identity is not None:
            if not python_identity.version.startswith(python_minor + "."):
                raise ValueError("runtime_python_minor_identity_mismatch")
        if binary_versions is not None:
            if binary_versions.torch.split("+", 1)[0] != semantic_graph.torch:
                raise ValueError("runtime_torch_binary_semantic_mismatch")
            if (
                binary_versions.torchvision.split("+", 1)[0]
                != semantic_graph.torchvision
            ):
                raise ValueError("runtime_torchvision_binary_semantic_mismatch")


def check_runtime_qualification_status(
    *,
    qualification_status: str,
    platform_variants: Mapping[str, object],
    release_locks: Mapping[str, object],
) -> None:
    has_pending = any(
        getattr(variant, "status") in {
            "pending-hardware-qualification",
            "qualified-development-hardware",
        }
        for variant in platform_variants.values()
    ) or any(
        getattr(lock, "status") != "qualified-offline-lock"
        for lock in release_locks.values()
    )
    if qualification_status == "qualified" and has_pending:
        raise ValueError("runtime_qualified_with_pending_gate")


def runtime_semantic_graph_identity(
    profile: "RuntimeProfileV2",
) -> Mapping[str, str]:
    graph = profile.semantic_graph
    return MappingProxyType(
        {
            "torch": graph.torch,
            "torchvision": graph.torchvision,
            "mmcv": graph.mmcv,
            "mmengine": graph.mmengine,
            "mmdet": graph.mmdet,
            "trackers": graph.trackers,
            "supervision": graph.supervision,
            "scipy": graph.scipy,
            "numpy": graph.numpy,
            "opencv": graph.opencv,
            "av": graph.av,
            "opencvPython": graph.opencv_python,
            "pillow": graph.pillow,
        }
    )


def runtime_platform_variant_identities(
    profile: "RuntimeProfileV2",
) -> Mapping[str, RuntimePlatformVariantIdentity]:
    identities: dict[str, RuntimePlatformVariantIdentity] = {}
    for variant_name, variant in profile.platform_variants.items():
        python_identity = (
            RuntimePythonIdentity(
                version=variant.python_identity.version,
                implementation=variant.python_identity.implementation,
                build=variant.python_identity.build,
                compiler=variant.python_identity.compiler,
            )
            if variant.python_identity is not None
            else None
        )
        binary_versions = (
            MappingProxyType(
                {
                    "torch": variant.binary_versions.torch,
                    "torchvision": variant.binary_versions.torchvision,
                }
            )
            if variant.binary_versions is not None
            else None
        )
        development_evidence = (
            RuntimeDevelopmentHardwareEvidenceIdentity(
                host_observation_sha256=(
                    variant.development_evidence.host_observation_sha256
                ),
                evidence_bundle_sha256=(
                    variant.development_evidence.evidence_bundle_sha256
                ),
                source_head_sha=(
                    variant.development_evidence.source_head_sha
                ),
                captured_at_utc=(
                    variant.development_evidence.captured_at_utc
                ),
                operator_reference=(
                    variant.development_evidence.operator_reference
                ),
            )
            if variant.development_evidence is not None
            else None
        )
        identities[variant_name] = RuntimePlatformVariantIdentity(
            status=variant.status,
            python_identity=python_identity,
            binary_versions=binary_versions,
            development_evidence=development_evidence,
        )
    return MappingProxyType(identities)


def runtime_release_lock_identities(
    profile: "RuntimeProfileV2",
) -> Mapping[str, RuntimeReleaseLockIdentity]:
    return MappingProxyType(
        {
            variant_name: RuntimeReleaseLockIdentity(
                status=lock.status,
                artifact=lock.artifact,
                sha256=lock.sha256,
            )
            for variant_name, lock in profile.release_locks.items()
        }
    )


def verify_runtime_release_locks(
    runtime_profile_path: Path,
    profile: "RuntimeProfileV2",
) -> Mapping[str, Path]:
    """Verify every qualified runtime lock against exact local bytes and identity."""
    verified: dict[str, Path] = {}
    root = runtime_profile_path.parent
    semantic_graph = {
        "torch": profile.semantic_graph.torch,
        "torchvision": profile.semantic_graph.torchvision,
        "mmcv": profile.semantic_graph.mmcv,
        "mmengine": profile.semantic_graph.mmengine,
        "mmdet": profile.semantic_graph.mmdet,
        "trackers": profile.semantic_graph.trackers,
        "supervision": profile.semantic_graph.supervision,
        "scipy": profile.semantic_graph.scipy,
        "numpy": profile.semantic_graph.numpy,
        "opencv-python": profile.semantic_graph.opencv_python,
        "av": profile.semantic_graph.av,
        "pillow": profile.semantic_graph.pillow,
    }

    for variant, lock in profile.release_locks.items():
        if lock.status != "qualified-offline-lock":
            continue
        if lock.artifact is None or lock.sha256 is None:
            raise ReleaseMetadataError("runtime_release_lock_evidence_required")

        artifact = ArtifactRef(relative_path=lock.artifact, sha256=lock.sha256)
        lock_path = resolve_release_artifact(root, artifact)
        if sha256_release_file(lock_path) != lock.sha256:
            raise ReleaseMetadataError("runtime_release_lock_hash_mismatch")

        platform = profile.platform_variants[variant]
        if platform.python_identity is None:
            raise ReleaseMetadataError("runtime_release_lock_python_identity_required")
        binary_versions = (
            {
                "torch": platform.binary_versions.torch,
                "torchvision": platform.binary_versions.torchvision,
            }
            if platform.binary_versions is not None
            else None
        )
        try:
            parsed = load_offline_runtime_lock(lock_path)
            validate_offline_runtime_lock_for_runtime(
                parsed,
                expected_variant=variant,
                expected_python_version=platform.python_identity.version,
                semantic_graph=semantic_graph,
                binary_versions=binary_versions,
                platform_status=platform.status,
            )
        except OfflineLockError as exc:
            raise ReleaseMetadataError(exc.code) from exc

        verified[variant] = lock_path

    return MappingProxyType(verified)
