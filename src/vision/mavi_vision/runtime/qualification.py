from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from mavi_vision.runtime.manifest import (
    ArtifactRef,
    ModelManifest,
    ReleaseMetadataError,
    load_model_manifest,
    read_release_json,
    resolve_release_artifact,
    sha256_release_file,
    validate_sha256_hex,
)
from mavi_vision.runtime.profile import (
    PipelineProfile,
    load_pipeline_profile,
    validate_profile_against_manifest,
)


MANDATORY_QUALIFICATION_GATES = frozenset(
    {
        "windows-x86_64-cpu",
        "windows-x86_64-cuda",
        "linux-x86_64-cpu",
        "linux-x86_64-cuda",
        "windows-offline-install",
        "linux-offline-install",
        "cctv-quality-baseline",
        "linux-nvidia-recovery-performance",
    }
)


@dataclass(frozen=True, slots=True)
class QualificationEvidence:
    kind: str
    reference: str
    sha256: str


@dataclass(frozen=True, slots=True)
class QualificationRecord:
    schema_version: str
    qualification_id: str
    model_id: str
    model_manifest_sha256: str
    checkpoint_sha256: str
    resolved_config_sha256: str
    pipeline_profile_id: str
    pipeline_profile_sha256: str
    runtime_profile_id: str
    runtime_profile_sha256: str
    required_gates: Mapping[str, Literal["passed", "pending"]]
    evidence: Mapping[str, QualificationEvidence]
    overall_result: Literal["passed", "pending"]


@dataclass(frozen=True, slots=True)
class VerifiedReleaseSelection:
    manifest: ModelManifest
    profile: PipelineProfile
    qualification: QualificationRecord | None
    manifest_sha256: str
    profile_sha256: str
    qualification_sha256: str | None
    runtime_profile_id: str
    runtime_profile_sha256: str
    checkpoint_path: Path
    resolved_config_path: Path
    verification_status: Literal["verified", "unverified"]


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


class _RuntimeCheckpointSchema(_StrictModel):
    publisher: str
    artifact: str
    sha256: str

    @field_validator("publisher")
    @classmethod
    def validate_publisher(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("runtime_checkpoint_publisher_invalid")
        return value

    @field_validator("artifact")
    @classmethod
    def validate_artifact(cls, value: str) -> str:
        from mavi_vision.runtime.manifest import validate_logical_relative_path

        validate_logical_relative_path(value)
        return value

    @field_validator("sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        validate_sha256_hex(value)
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


class _RuntimePlatformVariantSchema(_StrictModel):
    status: Literal[
        "qualified-hosted-cpu",
        "qualified-hardware",
        "pending-hardware-qualification",
    ]
    workflow_run_id: str | None = Field(default=None, alias="workflowRunId")
    job_id: str | None = Field(default=None, alias="jobId")
    evidence_head_sha: str | None = Field(default=None, alias="evidenceHeadSha")
    resolved_config_sha256: str | None = Field(
        default=None,
        alias="resolvedConfigSha256",
    )
    python_identity: _RuntimePythonIdentitySchema | None = Field(
        default=None,
        alias="pythonIdentity",
    )

    @model_validator(mode="after")
    def validate_evidence_shape(self) -> "_RuntimePlatformVariantSchema":
        evidence = (
            self.workflow_run_id,
            self.job_id,
            self.evidence_head_sha,
            self.resolved_config_sha256,
            self.python_identity,
        )
        if self.status.startswith("qualified-"):
            if any(value is None for value in evidence):
                raise ValueError("runtime_platform_evidence_required")
            assert self.workflow_run_id is not None
            assert self.job_id is not None
            assert self.evidence_head_sha is not None
            assert self.resolved_config_sha256 is not None
            if not self.workflow_run_id.isdigit() or not self.job_id.isdigit():
                raise ValueError("runtime_platform_evidence_id_invalid")
            if (
                len(self.evidence_head_sha) not in {40, 64}
                or self.evidence_head_sha.lower() != self.evidence_head_sha
                or any(ch not in "0123456789abcdef" for ch in self.evidence_head_sha)
            ):
                raise ValueError("runtime_platform_head_sha_invalid")
            validate_sha256_hex(self.resolved_config_sha256)
        elif any(value is not None for value in evidence):
            raise ValueError("runtime_pending_platform_has_evidence")
        return self


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


class _RuntimeResolvedConfigSchema(_StrictModel):
    artifact: str
    sha256: str
    format: Literal["python"]
    encoding: Literal["utf-8"]
    line_endings: Literal["lf"] = Field(alias="lineEndings")
    self_contained: Literal[True] = Field(alias="selfContained")

    @field_validator("artifact")
    @classmethod
    def validate_artifact(cls, value: str) -> str:
        from mavi_vision.runtime.manifest import validate_logical_relative_path

        validate_logical_relative_path(value)
        return value

    @field_validator("sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        validate_sha256_hex(value)
        return value


_RUNTIME_VARIANTS = frozenset(
    {
        "linux-x86_64-cpu",
        "windows-x86_64-cpu",
        "linux-x86_64-cuda",
        "windows-x86_64-cuda",
    }
)


class _RuntimeProfileSchema(_StrictModel):
    schema_version: Literal["1.0"] = Field(alias="schemaVersion")
    runtime_profile_id: str = Field(alias="runtimeProfileId")
    qualification_status: Literal["partial", "qualified"] = Field(
        alias="qualificationStatus"
    )
    python_minor: str = Field(alias="pythonMinor")
    semantic_graph: _RuntimeSemanticGraphSchema = Field(alias="semanticGraph")
    checkpoint: _RuntimeCheckpointSchema
    platform_variants: dict[str, _RuntimePlatformVariantSchema] = Field(
        alias="platformVariants"
    )
    release_locks: dict[str, _RuntimeReleaseLockSchema] = Field(alias="releaseLocks")
    resolved_config: _RuntimeResolvedConfigSchema = Field(alias="resolvedConfig")

    @field_validator("runtime_profile_id")
    @classmethod
    def validate_runtime_profile_id(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("runtime_profile_id_invalid")
        return value

    @field_validator("python_minor")
    @classmethod
    def validate_python_minor(cls, value: str) -> str:
        if value not in {"3.11", "3.12"}:
            raise ValueError("runtime_python_minor_invalid")
        return value

    @field_validator("platform_variants")
    @classmethod
    def validate_platform_variant_keys(
        cls,
        value: dict[str, _RuntimePlatformVariantSchema],
    ) -> dict[str, _RuntimePlatformVariantSchema]:
        if set(value) != _RUNTIME_VARIANTS:
            raise ValueError("runtime_platform_variants_incomplete")

        for variant_name, variant in value.items():
            if variant_name.endswith("-cuda"):
                if variant.status not in {
                    "pending-hardware-qualification",
                    "qualified-hardware",
                }:
                    raise ValueError("runtime_cuda_variant_status_invalid")
            elif variant_name.endswith("-cpu"):
                if variant.status not in {
                    "pending-hardware-qualification",
                    "qualified-hosted-cpu",
                }:
                    raise ValueError("runtime_cpu_variant_status_invalid")
            else:
                raise ValueError("runtime_platform_variant_unknown")

        return value

    @field_validator("release_locks")
    @classmethod
    def validate_release_lock_keys(
        cls,
        value: dict[str, _RuntimeReleaseLockSchema],
    ) -> dict[str, _RuntimeReleaseLockSchema]:
        if set(value) != _RUNTIME_VARIANTS:
            raise ValueError("runtime_release_locks_incomplete")
        return value

    @model_validator(mode="after")
    def validate_runtime_relationships(self) -> "_RuntimeProfileSchema":
        for variant in self.platform_variants.values():
            if (
                variant.resolved_config_sha256 is not None
                and variant.resolved_config_sha256 != self.resolved_config.sha256
            ):
                raise ValueError("runtime_variant_config_hash_mismatch")
            if variant.python_identity is not None:
                if not variant.python_identity.version.startswith(self.python_minor + "."):
                    raise ValueError("runtime_python_minor_identity_mismatch")

        has_pending = any(
            variant.status == "pending-hardware-qualification"
            for variant in self.platform_variants.values()
        ) or any(
            lock.status != "qualified-offline-lock"
            for lock in self.release_locks.values()
        )
        if self.qualification_status == "qualified" and has_pending:
            raise ValueError("runtime_qualified_with_pending_gate")
        return self


def load_runtime_profile(path: Path) -> _RuntimeProfileSchema:
    raw = read_release_json(path, code="runtime_profile_invalid")
    try:
        return _RuntimeProfileSchema.model_validate(raw)
    except ValidationError as exc:
        raise ReleaseMetadataError("runtime_profile_invalid") from exc


class _QualificationRecordSchema(_StrictModel):
    schema_version: Literal["1.0"] = Field(alias="schemaVersion")
    qualification_id: str = Field(alias="qualificationId")
    model_id: str = Field(alias="modelId")
    model_manifest_sha256: str = Field(alias="modelManifestSha256")
    checkpoint_sha256: str = Field(alias="checkpointSha256")
    resolved_config_sha256: str = Field(alias="resolvedConfigSha256")
    pipeline_profile_id: str = Field(alias="pipelineProfileId")
    pipeline_profile_sha256: str = Field(alias="pipelineProfileSha256")
    runtime_profile_id: str = Field(alias="runtimeProfileId")
    runtime_profile_sha256: str = Field(alias="runtimeProfileSha256")
    required_gates: dict[str, Literal["passed", "pending"]] = Field(alias="requiredGates")
    evidence: dict[str, _QualificationEvidenceSchema] = Field(default_factory=dict)
    overall_result: Literal["passed", "pending"] = Field(alias="overallResult")

    @field_validator(
        "qualification_id",
        "model_id",
        "pipeline_profile_id",
        "runtime_profile_id",
    )
    @classmethod
    def validate_nonempty_text(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("qualification_text_invalid")
        return value

    @field_validator(
        "model_manifest_sha256",
        "checkpoint_sha256",
        "resolved_config_sha256",
        "pipeline_profile_sha256",
        "runtime_profile_sha256",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        validate_sha256_hex(value)
        return value

    @field_validator("required_gates")
    @classmethod
    def validate_required_gates(
        cls,
        value: dict[str, Literal["passed", "pending"]],
    ) -> dict[str, Literal["passed", "pending"]]:
        if not MANDATORY_QUALIFICATION_GATES.issubset(value):
            raise ValueError("qualification_mandatory_gate_missing")
        if any(not key or key != key.strip() for key in value):
            raise ValueError("qualification_gate_name_invalid")
        return value

    @model_validator(mode="after")
    def validate_result_and_evidence(self) -> "_QualificationRecordSchema":
        for gate_name in self.evidence:
            if gate_name not in self.required_gates:
                raise ValueError("qualification_evidence_gate_unknown")
            if self.required_gates[gate_name] != "passed":
                raise ValueError("qualification_evidence_for_pending_gate")

        passed_gates = {
            gate_name
            for gate_name, status in self.required_gates.items()
            if status == "passed"
        }
        if not passed_gates.issubset(self.evidence):
            raise ValueError("qualification_passed_gate_missing_evidence")

        all_passed = all(status == "passed" for status in self.required_gates.values())
        expected_result = "passed" if all_passed else "pending"
        if self.overall_result != expected_result:
            raise ValueError("qualification_overall_result_mismatch")
        return self


def load_qualification_record(path: Path) -> QualificationRecord:
    raw = read_release_json(path, code="qualification_record_invalid")
    try:
        parsed = _QualificationRecordSchema.model_validate(raw)
    except ValidationError as exc:
        raise ReleaseMetadataError("qualification_record_invalid") from exc

    evidence = {
        gate_name: QualificationEvidence(
            kind=item.kind,
            reference=item.reference,
            sha256=item.sha256,
        )
        for gate_name, item in parsed.evidence.items()
    }
    return QualificationRecord(
        schema_version=parsed.schema_version,
        qualification_id=parsed.qualification_id,
        model_id=parsed.model_id,
        model_manifest_sha256=parsed.model_manifest_sha256,
        checkpoint_sha256=parsed.checkpoint_sha256,
        resolved_config_sha256=parsed.resolved_config_sha256,
        pipeline_profile_id=parsed.pipeline_profile_id,
        pipeline_profile_sha256=parsed.pipeline_profile_sha256,
        runtime_profile_id=parsed.runtime_profile_id,
        runtime_profile_sha256=parsed.runtime_profile_sha256,
        required_gates=MappingProxyType(dict(parsed.required_gates)),
        evidence=MappingProxyType(evidence),
        overall_result=parsed.overall_result,
    )


def load_runtime_identity(path: Path) -> tuple[str, str, str]:
    profile = load_runtime_profile(path)
    return (
        profile.runtime_profile_id,
        profile.checkpoint.sha256,
        profile.resolved_config.sha256,
    )


def verify_runtime_release_locks(
    runtime_profile_path: Path,
    profile: _RuntimeProfileSchema,
) -> Mapping[str, Path]:
    """Verify every qualified runtime lock against exact local bytes."""
    verified: dict[str, Path] = {}
    root = runtime_profile_path.parent

    for variant, lock in profile.release_locks.items():
        if lock.status != "qualified-offline-lock":
            continue
        if lock.artifact is None or lock.sha256 is None:
            raise ReleaseMetadataError("runtime_release_lock_evidence_required")

        artifact = ArtifactRef(relative_path=lock.artifact, sha256=lock.sha256)
        lock_path = resolve_release_artifact(root, artifact)
        if sha256_release_file(lock_path) != lock.sha256:
            raise ReleaseMetadataError("runtime_release_lock_hash_mismatch")
        verified[variant] = lock_path

    return MappingProxyType(verified)


def verify_qualification_relationships(
    *,
    qualification: QualificationRecord,
    manifest: ModelManifest,
    manifest_sha256: str,
    profile: PipelineProfile,
    profile_sha256: str,
    runtime_profile_id: str,
    runtime_profile_sha256: str,
    require_passed: bool,
) -> None:
    expected = {
        "qualification_id": manifest.qualification_id,
        "model_id": manifest.model_id,
        "model_manifest_sha256": manifest_sha256,
        "checkpoint_sha256": manifest.checkpoint.sha256,
        "resolved_config_sha256": manifest.resolved_config.sha256,
        "pipeline_profile_id": profile.profile_id,
        "pipeline_profile_sha256": profile_sha256,
        "runtime_profile_id": runtime_profile_id,
        "runtime_profile_sha256": runtime_profile_sha256,
    }
    actual = {
        "qualification_id": qualification.qualification_id,
        "model_id": qualification.model_id,
        "model_manifest_sha256": qualification.model_manifest_sha256,
        "checkpoint_sha256": qualification.checkpoint_sha256,
        "resolved_config_sha256": qualification.resolved_config_sha256,
        "pipeline_profile_id": qualification.pipeline_profile_id,
        "pipeline_profile_sha256": qualification.pipeline_profile_sha256,
        "runtime_profile_id": qualification.runtime_profile_id,
        "runtime_profile_sha256": qualification.runtime_profile_sha256,
    }

    if manifest.verification_status == "unverified":
        expected["qualification_id"] = qualification.qualification_id

    if actual != expected:
        raise ReleaseMetadataError("qualification_identity_mismatch")

    if require_passed:
        if qualification.overall_result != "passed":
            raise ReleaseMetadataError("qualification_not_passed")
        if any(
            qualification.required_gates.get(gate_name) != "passed"
            for gate_name in MANDATORY_QUALIFICATION_GATES
        ):
            raise ReleaseMetadataError("qualification_gate_not_passed")


def verify_release_selection(
    *,
    model_root: Path,
    manifest_path: Path,
    profile_path: Path,
    runtime_profile_path: Path,
    qualification_path: Path | None = None,
    allow_unverified: bool = False,
) -> VerifiedReleaseSelection:
    """Verify one immutable local release selection before runtime construction."""
    manifest = load_model_manifest(manifest_path)
    profile = load_pipeline_profile(profile_path)
    validate_profile_against_manifest(profile, manifest)

    if manifest.verification_status != "verified" and not allow_unverified:
        raise ReleaseMetadataError("unverified_release_forbidden")

    manifest_sha256 = sha256_release_file(manifest_path)
    profile_sha256 = sha256_release_file(profile_path)
    runtime_profile_sha256 = sha256_release_file(runtime_profile_path)
    runtime_profile = load_runtime_profile(runtime_profile_path)
    verify_runtime_release_locks(runtime_profile_path, runtime_profile)
    runtime_profile_id = runtime_profile.runtime_profile_id
    runtime_checkpoint_sha256 = runtime_profile.checkpoint.sha256
    runtime_config_sha256 = runtime_profile.resolved_config.sha256

    if manifest.verification_status == "verified" and (
        runtime_profile.qualification_status != "qualified"
    ):
        raise ReleaseMetadataError("runtime_profile_not_qualified")

    if runtime_profile_id != manifest.runtime_profile_id:
        raise ReleaseMetadataError("runtime_profile_id_mismatch")
    if runtime_checkpoint_sha256 != manifest.checkpoint.sha256:
        raise ReleaseMetadataError("runtime_checkpoint_hash_mismatch")
    if runtime_config_sha256 != manifest.resolved_config.sha256:
        raise ReleaseMetadataError("runtime_config_hash_mismatch")

    checkpoint_path = resolve_release_artifact(model_root, manifest.checkpoint)
    resolved_config_path = resolve_release_artifact(model_root, manifest.resolved_config)

    if sha256_release_file(checkpoint_path) != manifest.checkpoint.sha256:
        raise ReleaseMetadataError("checkpoint_hash_mismatch")
    if sha256_release_file(resolved_config_path) != manifest.resolved_config.sha256:
        raise ReleaseMetadataError("resolved_config_hash_mismatch")

    qualification: QualificationRecord | None = None
    qualification_sha256: str | None = None

    if manifest.verification_status == "verified":
        if qualification_path is None:
            raise ReleaseMetadataError("qualification_record_required")
        qualification = load_qualification_record(qualification_path)
        qualification_sha256 = sha256_release_file(qualification_path)
        verify_qualification_relationships(
            qualification=qualification,
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            profile=profile,
            profile_sha256=profile_sha256,
            runtime_profile_id=runtime_profile_id,
            runtime_profile_sha256=runtime_profile_sha256,
            require_passed=True,
        )
    elif qualification_path is not None:
        qualification = load_qualification_record(qualification_path)
        qualification_sha256 = sha256_release_file(qualification_path)
        verify_qualification_relationships(
            qualification=qualification,
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            profile=profile,
            profile_sha256=profile_sha256,
            runtime_profile_id=runtime_profile_id,
            runtime_profile_sha256=runtime_profile_sha256,
            require_passed=False,
        )

    return VerifiedReleaseSelection(
        manifest=manifest,
        profile=profile,
        qualification=qualification,
        manifest_sha256=manifest_sha256,
        profile_sha256=profile_sha256,
        qualification_sha256=qualification_sha256,
        runtime_profile_id=runtime_profile_id,
        runtime_profile_sha256=runtime_profile_sha256,
        checkpoint_path=checkpoint_path,
        resolved_config_path=resolved_config_path,
        verification_status=manifest.verification_status,
    )
