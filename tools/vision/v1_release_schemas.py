#!/usr/bin/env python3
"""Frozen v1 release-metadata schemas: the migration generator's reader only.

Stage 2 S2a.3 deleted every v1 reader from the worker runtime (ADR-014 migration
strategy: "after the cut-over, v1 artefacts and v1 install state are rejected, not
reinterpreted, and no period with two binding systems remains"). The one-shot
generator ``migrate_component_binding_v1.py`` must still read the v1 inputs it
migrated, so its tests can prove the published v2 artefacts are exactly its output.
These definitions were moved here verbatim from
``mavi_vision.runtime.{manifest,qualification,component_identity}`` for that
purpose and nothing else. ``test_v1_release_schemas_are_tooling_only`` proves no
module under ``mavi_vision`` imports this file.
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping

ROOT = Path(__file__).resolve().parents[2]
VISION_ROOT = ROOT / "src" / "vision"
if str(VISION_ROOT) not in sys.path:
    sys.path.insert(0, str(VISION_ROOT))

from pydantic import Field, ValidationError, field_validator, model_validator  # noqa: E402

from mavi_vision.runtime.component_identity import (  # noqa: E402
    canonical_identity_digest,
    validate_identity_text,
)
from mavi_vision.runtime.manifest import (  # noqa: E402
    ArtifactRef,
    ReleaseMetadataError,
    read_release_json,
    validate_logical_relative_path,
    validate_sha256_hex,
)
from mavi_vision.runtime.qualification import (  # noqa: E402
    _RUNTIME_VARIANTS,
    _ProfileQualificationSchema,
    _QualificationEvidenceSchema,
    _RuntimeBinaryVersionsSchema,
    _RuntimeDevelopmentHardwareEvidenceSchema,
    _RuntimePythonIdentitySchema,
    _RuntimeReleaseLockSchema,
    _RuntimeSemanticGraphSchema,
    _StrictModel,
    check_platform_variant_evidence,
    check_runtime_graph_relationships,
    check_runtime_platform_variant_statuses,
    check_runtime_profile_id,
    check_runtime_python_minor,
    check_runtime_qualification_status,
    check_runtime_release_lock_keys,
)

# --------------------------------------------------------------------- model manifest v1

@dataclass(frozen=True, slots=True)
class ModelManifest:
    schema_version: str
    model_id: str
    model_version: str
    purpose: str
    backend: str
    architecture: str
    class_vocabulary: tuple[str, ...]
    checkpoint: ArtifactRef
    resolved_config: ArtifactRef
    runtime_profile_id: str
    verification_status: Literal["verified", "unverified"]
    qualification_id: str | None


class _ArtifactRefSchema(_StrictModel):
    relative_path: str = Field(alias="relativePath")
    sha256: str

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        validate_logical_relative_path(value)
        return value

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        validate_sha256_hex(value)
        return value


class _ModelManifestSchema(_StrictModel):
    schema_version: Literal["1.0"] = Field(alias="schemaVersion")
    model_id: str = Field(alias="modelId")
    model_version: str = Field(alias="modelVersion")
    purpose: str
    backend: str
    architecture: str
    class_vocabulary: tuple[str, ...] = Field(alias="classVocabulary")
    checkpoint: _ArtifactRefSchema
    resolved_config: _ArtifactRefSchema = Field(alias="resolvedConfig")
    runtime_profile_id: str = Field(alias="runtimeProfileId")
    verification_status: Literal["verified", "unverified"] = Field(alias="verificationStatus")
    qualification_id: str | None = Field(alias="qualificationId")

    @field_validator(
        "model_id",
        "model_version",
        "purpose",
        "backend",
        "architecture",
        "runtime_profile_id",
    )
    @classmethod
    def validate_nonempty_text(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("release_metadata_text_invalid")
        return value

    @field_validator("class_vocabulary")
    @classmethod
    def validate_vocabulary(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("model_vocabulary_empty")
        if any(not item or item != item.strip() for item in value):
            raise ValueError("model_vocabulary_entry_invalid")
        if len(set(value)) != len(value):
            raise ValueError("model_vocabulary_duplicate")
        return value

    @model_validator(mode="after")
    def validate_verification_relationship(self) -> "_ModelManifestSchema":
        if self.verification_status == "verified" and not self.qualification_id:
            raise ValueError("verified_manifest_requires_qualification")
        if self.qualification_id is not None and (
            not self.qualification_id or self.qualification_id != self.qualification_id.strip()
        ):
            raise ValueError("qualification_id_invalid")
        return self


def load_model_manifest(path: Path) -> ModelManifest:
    raw = read_release_json(path, code="model_manifest_invalid")
    try:
        parsed = _ModelManifestSchema.model_validate(raw)
    except ValidationError as exc:
        raise ReleaseMetadataError("model_manifest_invalid") from exc

    return ModelManifest(
        schema_version=parsed.schema_version,
        model_id=parsed.model_id,
        model_version=parsed.model_version,
        purpose=parsed.purpose,
        backend=parsed.backend,
        architecture=parsed.architecture,
        class_vocabulary=parsed.class_vocabulary,
        checkpoint=ArtifactRef(
            relative_path=parsed.checkpoint.relative_path,
            sha256=parsed.checkpoint.sha256,
        ),
        resolved_config=ArtifactRef(
            relative_path=parsed.resolved_config.relative_path,
            sha256=parsed.resolved_config.sha256,
        ),
        runtime_profile_id=parsed.runtime_profile_id,
        verification_status=parsed.verification_status,
        qualification_id=parsed.qualification_id,
    )


# --------------------------------------------------------------------- Model Pack id v1

_MODEL_SCHEMA_V1 = "mavi-vision-model-pack-v1"


@dataclass(frozen=True, slots=True)
class ModelPackIdentityInputs:
    model_id: str
    checkpoint_sha256: str
    resolved_config_sha256: str


def model_pack_id(inputs: ModelPackIdentityInputs) -> str:
    """The retired v1 derivation, kept only to re-check the v1 binding being migrated."""
    validate_identity_text(inputs.model_id)
    for digest in (inputs.checkpoint_sha256, inputs.resolved_config_sha256):
        validate_sha256_hex(digest)
    return "mavi-model-v1-" + canonical_identity_digest({"schemaVersion": _MODEL_SCHEMA_V1, **asdict(inputs)})


# --------------------------------------------------------------------- runtime profile / record v1

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
class ProfileQualification:
    deployment_profile_policy_sha256: str
    runtime_variant: str
    evidence: Mapping[str, QualificationEvidence]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence",
            MappingProxyType(dict(self.evidence)),
        )


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
    qualified_profiles: tuple[str, ...] = ()
    profile_qualifications: Mapping[str, ProfileQualification] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "profile_qualifications",
            MappingProxyType(dict(self.profile_qualifications)),
        )

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

class _RuntimePlatformVariantSchema(_StrictModel):
    status: Literal[
        "qualified-hosted-cpu",
        "qualified-hardware",
        "qualified-development-hardware",
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
    binary_versions: _RuntimeBinaryVersionsSchema | None = Field(
        default=None,
        alias="binaryVersions",
    )
    development_evidence: (
        _RuntimeDevelopmentHardwareEvidenceSchema | None
    ) = Field(default=None, alias="developmentEvidence")

    @model_validator(mode="after")
    def validate_evidence_shape(self) -> "_RuntimePlatformVariantSchema":
        check_platform_variant_evidence(
            status=self.status,
            workflow_run_id=self.workflow_run_id,
            job_id=self.job_id,
            evidence_head_sha=self.evidence_head_sha,
            runtime_identity=(
                self.resolved_config_sha256,
                self.python_identity,
                self.binary_versions,
            ),
            development_evidence=self.development_evidence,
        )
        if self.resolved_config_sha256 is not None:
            validate_sha256_hex(self.resolved_config_sha256)
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
        return check_runtime_profile_id(value)

    @field_validator("python_minor")
    @classmethod
    def validate_python_minor(cls, value: str) -> str:
        return check_runtime_python_minor(value)

    @field_validator("platform_variants")
    @classmethod
    def validate_platform_variant_keys(
        cls,
        value: dict[str, _RuntimePlatformVariantSchema],
    ) -> dict[str, _RuntimePlatformVariantSchema]:
        check_runtime_platform_variant_statuses(value)
        return value

    @field_validator("release_locks")
    @classmethod
    def validate_release_lock_keys(
        cls,
        value: dict[str, _RuntimeReleaseLockSchema],
    ) -> dict[str, _RuntimeReleaseLockSchema]:
        check_runtime_release_lock_keys(value)
        return value

    @model_validator(mode="after")
    def validate_runtime_relationships(self) -> "_RuntimeProfileSchema":
        for variant in self.platform_variants.values():
            if (
                variant.resolved_config_sha256 is not None
                and variant.resolved_config_sha256 != self.resolved_config.sha256
            ):
                raise ValueError("runtime_variant_config_hash_mismatch")
        check_runtime_graph_relationships(
            python_minor=self.python_minor,
            semantic_graph=self.semantic_graph,
            platform_variants=self.platform_variants,
        )
        check_runtime_qualification_status(
            qualification_status=self.qualification_status,
            platform_variants=self.platform_variants,
            release_locks=self.release_locks,
        )
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
    qualified_profiles: tuple[str, ...] = Field(default=(), alias="qualifiedProfiles")
    profile_qualifications: dict[str, _ProfileQualificationSchema] = Field(
        default_factory=dict,
        alias="profileQualifications",
    )

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

    @field_validator("qualified_profiles")
    @classmethod
    def validate_qualified_profiles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("qualification_profile_duplicate")
        if any(not item or item != item.strip() for item in value):
            raise ValueError("qualification_profile_invalid")
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

        if set(self.qualified_profiles) != set(self.profile_qualifications):
            raise ValueError("qualification_profile_index_mismatch")
        for profile_id, profile_qualification in self.profile_qualifications.items():
            if not profile_id or profile_id != profile_id.strip():
                raise ValueError("qualification_profile_invalid")
            if any(
                gate_name not in self.required_gates
                for gate_name in profile_qualification.evidence
            ):
                raise ValueError("qualification_profile_evidence_gate_unknown")
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
    profile_qualifications = {
        profile_id: ProfileQualification(
            deployment_profile_policy_sha256=(
                profile_item.deployment_profile_policy_sha256
            ),
            runtime_variant=profile_item.runtime_variant,
            evidence=MappingProxyType(
                {
                    gate_name: QualificationEvidence(
                        kind=item.kind,
                        reference=item.reference,
                        sha256=item.sha256,
                    )
                    for gate_name, item in profile_item.evidence.items()
                }
            ),
        )
        for profile_id, profile_item in parsed.profile_qualifications.items()
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
        qualified_profiles=tuple(parsed.qualified_profiles),
        profile_qualifications=MappingProxyType(profile_qualifications),
    )
