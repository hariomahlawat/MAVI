"""Source model manifest v2 (ADR-014 §3; S2a plan §4.2, P-3, P-10, P-14, P-15).

The source manifest is the authored, capability-neutral description of one
learned component. It carries artefact roles, logical paths and SHA-256 only:
no ``modelPackId`` (derived, see ``model_pack_identity``) and no byte sizes
(measured into the built Model Pack manifest, never authored here).
Capability-specific detail lives in a registered ``capabilitySpecific`` section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Literal, Mapping

from pydantic import Field, StrictInt, ValidationError, field_validator, model_validator

from mavi_vision.runtime.capabilities import require_known_capability
from mavi_vision.runtime.manifest import (
    ReleaseMetadataError,
    find_release_network_hazard,
    validate_logical_relative_path,
    validate_sha256_hex,
)
from mavi_vision.runtime.model_pack_identity import (
    ModelPackArtifactIdentity,
    ModelPackIdentityInputsV2,
    model_pack_id_v2,
)
from mavi_vision.runtime.schema_common import (
    StrictModel,
    read_release_json_v2,
    release_error,
    require_kebab_id,
    require_text,
)

MODEL_MANIFEST_V2_SCHEMA = "2.0"
LICENCE_NOTICE_ROLE = "licence-notice"
_MODEL_VERSION_RE = re.compile(r"^[0-9A-Za-z](?:[0-9A-Za-z.+-]*[0-9A-Za-z])?$")


class _ArtifactSchema(StrictModel):
    artifact_role: str = Field(alias="artifactRole")
    relative_path: str = Field(alias="relativePath")
    sha256: str

    @field_validator("artifact_role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        return require_kebab_id(value, code="model_artifact_role_invalid")

    @field_validator("relative_path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        try:
            validate_logical_relative_path(value)
        except ValueError as exc:
            raise ValueError("model_artifact_path_invalid") from exc
        if len(PurePosixPath(value).parts) < 2:
            raise ValueError("model_artifact_path_invalid")
        return value

    @field_validator("sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        try:
            validate_sha256_hex(value)
        except ValueError as exc:
            raise ValueError("model_artifact_sha256_invalid") from exc
        return value


class _InputContractSchema(StrictModel):
    kind: str
    colour_space: Literal["RGB"] | None = Field(default=None, alias="colourSpace")

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        return require_kebab_id(value, code="model_input_contract_invalid")


class _OutputContractSchema(StrictModel):
    schema_id: str = Field(alias="schemaId")

    @field_validator("schema_id")
    @classmethod
    def validate_schema_id(cls, value: str) -> str:
        return require_kebab_id(value, code="model_output_contract_invalid")


class _RuntimeCompatibilitySchema(StrictModel):
    runtime_pack_family_ids: tuple[str, ...] = Field(alias="runtimePackFamilyIds")

    @field_validator("runtime_pack_family_ids")
    @classmethod
    def validate_families(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(set(value)) != len(value):
            raise ValueError("model_runtime_compatibility_invalid")
        for family in value:
            require_kebab_id(family, code="model_runtime_compatibility_invalid")
        return value


class _LicenceSchema(StrictModel):
    spdx_id: str = Field(alias="spdxId")
    notice_artifact_role: str = Field(alias="noticeArtifactRole")
    review_status: Literal["pending-review", "approved"] = Field(alias="reviewStatus")

    @field_validator("spdx_id")
    @classmethod
    def validate_spdx(cls, value: str) -> str:
        return require_text(value, code="model_licence_invalid")


class _ProvenanceSchema(StrictModel):
    publisher: str
    source_repository: str = Field(alias="sourceRepository")
    source_revision: str = Field(alias="sourceRevision")

    @field_validator("publisher", "source_repository", "source_revision")
    @classmethod
    def validate_text(cls, value: str) -> str:
        require_text(value, code="model_provenance_invalid")
        # Release metadata never carries a network locator (plan §17 E-1); the same
        # rule verify_repo applies to every file under models/manifests.
        if find_release_network_hazard(value) is not None:
            raise ValueError("model_provenance_network_locator")
        return value


class _DetectorSectionSchema(StrictModel):
    backend: str
    architecture: str
    class_vocabulary: tuple[str, ...] = Field(alias="classVocabulary")
    checkpoint_artifact_role: str = Field(alias="checkpointArtifactRole")
    resolved_config_artifact_role: str = Field(alias="resolvedConfigArtifactRole")

    @field_validator("backend", "architecture")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return require_text(value, code="detector_section_invalid")

    @field_validator("class_vocabulary")
    @classmethod
    def validate_vocabulary(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("model_vocabulary_empty")
        for item in value:
            require_text(item, code="model_vocabulary_entry_invalid")
        if len(set(value)) != len(value):
            raise ValueError("model_vocabulary_duplicate")
        return value


class _EmbeddingSectionSchema(StrictModel):
    dimension: StrictInt

    @field_validator("dimension")
    @classmethod
    def validate_dimension(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("embedding_section_invalid")
        return value


# Capability-specific sections are a closed registry: a capability whose section
# shape is not registered here cannot carry a section (fail closed).
_CAPABILITY_SECTIONS: Mapping[str, type[StrictModel]] = MappingProxyType(
    {
        "detector": _DetectorSectionSchema,
        "embedding": _EmbeddingSectionSchema,
    }
)
# Capabilities whose runtime cannot operate without their section.
_SECTION_REQUIRED = frozenset({"detector"})


class _ModelManifestV2Schema(StrictModel):
    schema_version: Literal["2.0"] = Field(alias="schemaVersion")
    model_id: str = Field(alias="modelId")
    model_version: str = Field(alias="modelVersion")
    capability_ids: tuple[str, ...] = Field(alias="capabilityIds")
    artifacts: tuple[_ArtifactSchema, ...]
    input_contract: _InputContractSchema = Field(alias="inputContract")
    output_contract: _OutputContractSchema = Field(alias="outputContract")
    runtime_compatibility: _RuntimeCompatibilitySchema = Field(alias="runtimeCompatibility")
    licence: _LicenceSchema
    provenance: _ProvenanceSchema
    verification_status: Literal["verified", "unverified"] = Field(alias="verificationStatus")
    qualification_id: str | None = Field(alias="qualificationId")
    capability_specific: dict[str, dict[str, Any]] = Field(alias="capabilitySpecific")

    @field_validator("model_id")
    @classmethod
    def validate_model_id(cls, value: str) -> str:
        return require_kebab_id(value, code="model_id_invalid")

    @field_validator("model_version")
    @classmethod
    def validate_model_version(cls, value: str) -> str:
        if _MODEL_VERSION_RE.fullmatch(value) is None:
            raise ValueError("model_version_invalid")
        return value

    @field_validator("capability_ids")
    @classmethod
    def validate_capabilities(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("model_capabilities_empty")
        for capability_id in value:
            require_known_capability(capability_id)
        if list(value) != sorted(set(value)):
            raise ValueError("model_capabilities_unordered_or_duplicate")
        return value

    @model_validator(mode="after")
    def validate_relationships(self) -> "_ModelManifestV2Schema":
        roles = [artifact.artifact_role for artifact in self.artifacts]
        if not roles:
            raise ValueError("model_artifacts_empty")
        if len(set(roles)) != len(roles):
            raise ValueError("model_artifact_role_duplicate")
        paths = [artifact.relative_path for artifact in self.artifacts]
        if len(set(paths)) != len(paths):
            raise ValueError("model_artifact_path_duplicate")
        pack_directories = {PurePosixPath(path).parts[0] for path in paths}
        if len(pack_directories) != 1:
            raise ValueError("model_pack_directory_not_unique")

        # Every Model Pack ships exactly its licence notice under the one reserved
        # role, so the notice is always part of modelPackId (P-15).
        if self.licence.notice_artifact_role != LICENCE_NOTICE_ROLE:
            raise ValueError("model_licence_notice_role_invalid")
        if LICENCE_NOTICE_ROLE not in roles:
            raise ValueError("model_licence_notice_missing")

        for capability_id, section in self.capability_specific.items():
            if capability_id not in self.capability_ids:
                raise ValueError(f"capability_section_unbound:{capability_id}")
            schema = _CAPABILITY_SECTIONS.get(capability_id)
            if schema is None:
                raise ValueError(f"capability_section_unsupported:{capability_id}")
            try:
                parsed = schema.model_validate(section)
            except ValidationError as exc:
                raise ValueError(
                    release_error(exc, default_code=f"capability_section_invalid:{capability_id}").code
                ) from exc
            if isinstance(parsed, _DetectorSectionSchema):
                detector_roles = (parsed.checkpoint_artifact_role, parsed.resolved_config_artifact_role)
                for role in detector_roles:
                    if role not in roles:
                        raise ValueError("detector_section_artifact_missing")
                if len(set(detector_roles)) != 2 or LICENCE_NOTICE_ROLE in detector_roles:
                    raise ValueError("detector_section_artifact_roles_invalid")
        for capability_id in _SECTION_REQUIRED:
            if capability_id in self.capability_ids and capability_id not in self.capability_specific:
                raise ValueError(f"capability_section_missing:{capability_id}")

        if self.verification_status == "verified":
            if self.qualification_id is None:
                raise ValueError("verified_manifest_requires_qualification")
            if self.licence.review_status != "approved":
                raise ValueError("verified_manifest_requires_licence_approval")
        if self.qualification_id is not None:
            require_text(self.qualification_id, code="qualification_id_invalid")
        return self


@dataclass(frozen=True, slots=True)
class ModelArtifactV2:
    artifact_role: str
    relative_path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class DetectorModelSection:
    backend: str
    architecture: str
    class_vocabulary: tuple[str, ...]
    checkpoint: ModelArtifactV2
    resolved_config: ModelArtifactV2


@dataclass(frozen=True, slots=True)
class ModelManifestV2:
    schema_version: str
    model_id: str
    model_version: str
    capability_ids: tuple[str, ...]
    artifacts: tuple[ModelArtifactV2, ...]
    pack_directory: str
    input_contract_kind: str
    input_colour_space: str | None
    output_schema_id: str
    runtime_pack_family_ids: tuple[str, ...]
    licence_spdx_id: str
    licence_notice: ModelArtifactV2
    licence_review_status: Literal["pending-review", "approved"]
    verification_status: Literal["verified", "unverified"]
    qualification_id: str | None
    model_pack_id: str
    capability_specific: Mapping[str, Mapping[str, Any]]

    def artifact(self, role: str) -> ModelArtifactV2:
        for artifact in self.artifacts:
            if artifact.artifact_role == role:
                return artifact
        raise ReleaseMetadataError(f"model_artifact_missing:{role}")

    def detector_section(self) -> DetectorModelSection:
        section = self.capability_specific.get("detector")
        if section is None:
            raise ReleaseMetadataError("capability_section_missing:detector")
        parsed = _DetectorSectionSchema.model_validate(_thaw(section))
        return DetectorModelSection(
            backend=parsed.backend,
            architecture=parsed.architecture,
            class_vocabulary=parsed.class_vocabulary,
            checkpoint=self.artifact(parsed.checkpoint_artifact_role),
            resolved_config=self.artifact(parsed.resolved_config_artifact_role),
        )


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def parse_model_manifest_v2(raw: object) -> ModelManifestV2:
    if isinstance(raw, dict) and raw.get("schemaVersion") != MODEL_MANIFEST_V2_SCHEMA:
        raise ReleaseMetadataError("model_manifest_schema_unsupported")
    try:
        parsed = _ModelManifestV2Schema.model_validate(raw)
    except ValidationError as exc:
        raise release_error(exc, default_code="model_manifest_invalid") from exc

    artifacts = tuple(
        ModelArtifactV2(
            artifact_role=item.artifact_role,
            relative_path=item.relative_path,
            sha256=item.sha256,
        )
        for item in parsed.artifacts
    )
    by_role = {artifact.artifact_role: artifact for artifact in artifacts}
    model_pack_id = model_pack_id_v2(
        ModelPackIdentityInputsV2(
            model_id=parsed.model_id,
            model_version=parsed.model_version,
            capability_ids=parsed.capability_ids,
            artifacts=tuple(
                ModelPackArtifactIdentity(artifact_role=item.artifact_role, sha256=item.sha256)
                for item in artifacts
            ),
        )
    )
    return ModelManifestV2(
        schema_version=parsed.schema_version,
        model_id=parsed.model_id,
        model_version=parsed.model_version,
        capability_ids=parsed.capability_ids,
        artifacts=artifacts,
        pack_directory=PurePosixPath(artifacts[0].relative_path).parts[0],
        input_contract_kind=parsed.input_contract.kind,
        input_colour_space=parsed.input_contract.colour_space,
        output_schema_id=parsed.output_contract.schema_id,
        runtime_pack_family_ids=parsed.runtime_compatibility.runtime_pack_family_ids,
        licence_spdx_id=parsed.licence.spdx_id,
        licence_notice=by_role[parsed.licence.notice_artifact_role],
        licence_review_status=parsed.licence.review_status,
        verification_status=parsed.verification_status,
        qualification_id=parsed.qualification_id,
        model_pack_id=model_pack_id,
        capability_specific=_freeze(parsed.capability_specific),
    )


def load_model_manifest_v2(path: Path) -> ModelManifestV2:
    raw, _payload = read_release_json_v2(path, code="model_manifest_invalid")
    return parse_model_manifest_v2(raw)


__all__ = [
    "DetectorModelSection",
    "LICENCE_NOTICE_ROLE",
    "MODEL_MANIFEST_V2_SCHEMA",
    "ModelArtifactV2",
    "ModelManifestV2",
    "load_model_manifest_v2",
    "parse_model_manifest_v2",
]
