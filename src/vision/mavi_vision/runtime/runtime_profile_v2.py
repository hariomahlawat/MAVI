"""Runtime profile v2 (ADR-014 §4, §4a; S2a plan §4.3, P-2, P-17).

The runtime profile describes one Runtime Pack family (its id is the
``runtimeProfileId``): the executable dependency graph, the per-variant
runtime-graph qualification state and the release locks. It carries no model
identity: the v1 top-level ``checkpoint``/``resolvedConfig`` and the per-variant
``resolvedConfigSha256`` are gone and are rejected as unknown fields.
"""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping

from pydantic import Field, ValidationError, field_validator, model_validator

from mavi_vision.runtime.manifest import ReleaseMetadataError
from mavi_vision.runtime.qualification import (
    _RuntimeBinaryVersionsSchema,
    _RuntimeDevelopmentHardwareEvidenceSchema,
    _RuntimePythonIdentitySchema,
    _RuntimeReleaseLockSchema,
    _RuntimeSemanticGraphSchema,
    check_platform_variant_evidence,
    check_runtime_graph_relationships,
    check_runtime_platform_variant_statuses,
    check_runtime_profile_id,
    check_runtime_python_minor,
    check_runtime_qualification_status,
    check_runtime_release_lock_keys,
)
from mavi_vision.runtime.schema_common import StrictModel, read_release_json_v2, release_error, require_kebab_id
from mavi_vision.runtime.variants import (
    VariantClass,
    check_variant_status_pair,
    classify_variant,
)

RUNTIME_PROFILE_V2_SCHEMA = "2.0"


class _RuntimePlatformVariantSchemaV2(StrictModel):
    status: Literal[
        "qualified-hosted-cpu",
        "qualified-hardware",
        "qualified-development-hardware",
        "pending-hardware-qualification",
    ]
    workflow_run_id: str | None = Field(default=None, alias="workflowRunId")
    job_id: str | None = Field(default=None, alias="jobId")
    evidence_head_sha: str | None = Field(default=None, alias="evidenceHeadSha")
    python_identity: _RuntimePythonIdentitySchema | None = Field(default=None, alias="pythonIdentity")
    binary_versions: _RuntimeBinaryVersionsSchema | None = Field(default=None, alias="binaryVersions")
    development_evidence: _RuntimeDevelopmentHardwareEvidenceSchema | None = Field(
        default=None, alias="developmentEvidence"
    )

    @model_validator(mode="after")
    def validate_evidence_shape(self) -> "_RuntimePlatformVariantSchemaV2":
        check_platform_variant_evidence(
            status=self.status,
            workflow_run_id=self.workflow_run_id,
            job_id=self.job_id,
            evidence_head_sha=self.evidence_head_sha,
            runtime_identity=(self.python_identity, self.binary_versions),
            development_evidence=self.development_evidence,
        )
        return self


class RuntimeProfileV2(StrictModel):
    schema_version: Literal["2.0"] = Field(alias="schemaVersion")
    runtime_profile_id: str = Field(alias="runtimeProfileId")
    qualification_status: Literal["partial", "qualified"] = Field(alias="qualificationStatus")
    python_minor: str = Field(alias="pythonMinor")
    semantic_graph: _RuntimeSemanticGraphSchema = Field(alias="semanticGraph")
    platform_variants: dict[str, _RuntimePlatformVariantSchemaV2] = Field(alias="platformVariants")
    release_locks: dict[str, _RuntimeReleaseLockSchema] = Field(alias="releaseLocks")

    @field_validator("runtime_profile_id")
    @classmethod
    def validate_runtime_profile_id(cls, value: str) -> str:
        # The profile id is the Runtime Pack family id (P-2), so it obeys the family-id rule.
        return require_kebab_id(check_runtime_profile_id(value), code="runtime_profile_id_invalid")

    @field_validator("python_minor")
    @classmethod
    def validate_python_minor(cls, value: str) -> str:
        return check_runtime_python_minor(value)

    @field_validator("platform_variants")
    @classmethod
    def validate_platform_variant_keys(
        cls, value: dict[str, _RuntimePlatformVariantSchemaV2]
    ) -> dict[str, _RuntimePlatformVariantSchemaV2]:
        check_runtime_platform_variant_statuses(value)
        return value

    @field_validator("release_locks")
    @classmethod
    def validate_release_lock_keys(
        cls, value: dict[str, _RuntimeReleaseLockSchema]
    ) -> dict[str, _RuntimeReleaseLockSchema]:
        check_runtime_release_lock_keys(value)
        return value

    @model_validator(mode="after")
    def validate_runtime_relationships(self) -> "RuntimeProfileV2":
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
        for variant, platform_variant in sorted(self.platform_variants.items()):
            check_variant_status_pair(
                variant=variant,
                variant_status=platform_variant.status,
                lock_status=self.release_locks[variant].status,
            )
        return self

    @property
    def runtime_pack_family_id(self) -> str:
        """A Runtime Pack family is identified by its runtime profile id (P-2)."""
        return self.runtime_profile_id


def parse_runtime_profile_v2(raw: object) -> RuntimeProfileV2:
    if isinstance(raw, dict) and raw.get("schemaVersion") != RUNTIME_PROFILE_V2_SCHEMA:
        raise ReleaseMetadataError("runtime_profile_schema_unsupported")
    try:
        return RuntimeProfileV2.model_validate(raw)
    except ValidationError as exc:
        raise release_error(exc, default_code="runtime_profile_invalid") from exc


def load_runtime_profile_v2(path: Path) -> RuntimeProfileV2:
    raw, _payload = read_release_json_v2(path, code="runtime_profile_invalid")
    return parse_runtime_profile_v2(raw)


def classify_runtime_variants(
    profile: RuntimeProfileV2,
    *,
    tracked_lock_variants: Collection[str],
) -> Mapping[str, VariantClass]:
    """Classify every variant of the family (P-17).

    ``tracked_lock_variants`` names the variants for which a ``<variant>.lock``
    file is tracked beside the profile; the caller that can see the file system
    supplies it. Any variant that is neither class A nor class B fails closed.
    """
    tracked = frozenset(tracked_lock_variants)
    unknown = tracked - set(profile.platform_variants)
    if unknown:
        raise ReleaseMetadataError(f"runtime_variant_unknown:{sorted(unknown)[0]}")
    classes: dict[str, VariantClass] = {}
    for variant in sorted(profile.platform_variants):
        try:
            classes[variant] = classify_variant(
                variant=variant,
                variant_status=profile.platform_variants[variant].status,
                lock_status=profile.release_locks[variant].status,
                lock_file_tracked=variant in tracked,
            )
        except ValueError as exc:
            raise ReleaseMetadataError(str(exc)) from exc
    return MappingProxyType(classes)


__all__ = [
    "RUNTIME_PROFILE_V2_SCHEMA",
    "RuntimeProfileV2",
    "classify_runtime_variants",
    "load_runtime_profile_v2",
    "parse_runtime_profile_v2",
]
