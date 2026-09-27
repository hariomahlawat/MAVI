"""Capability-scoped qualification record v2 and capability gate sets.

ADR-014 §4a, §6, §7; S2a plan §4.4, P-12, P-17.

A record binds evidence to one capability, one derived Model Pack identity, one
Runtime Pack family and a per-variant Runtime Pack identity. Gates are named by
policy gate sets and evaluated per variant. The record is evidence and status
only; nothing reads a Runtime Pack identity *from* it.

Cross-file rules (the binding's variants, the runtime profile's variant classes,
live file hashes) are checked where all artefacts are visible (S2a.3: resolver
and ``verify_repo``). This module enforces everything a record can prove about
itself, including that a variant without a Runtime Pack can never pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping

from pydantic import Field, ValidationError, field_validator

from mavi_vision.runtime.capabilities import require_known_capability
from mavi_vision.runtime.component_identity import RUNTIME_PACK_ID_RE
from mavi_vision.runtime.manifest import (
    ReleaseMetadataError,
    validate_sha256_hex,
)
from mavi_vision.runtime.model_pack_identity import MODEL_PACK_ID_RE
from mavi_vision.runtime.qualification import (
    _ProfileQualificationSchema,
    _QualificationEvidenceSchema,
)
from mavi_vision.runtime.schema_common import (
    StrictModel,
    read_release_json_v2,
    release_error,
    require_kebab_id,
    require_optional_text,
    require_text,
)
from mavi_vision.runtime.variants import RUNTIME_VARIANTS

__all__ = [
    "CAPABILITY_GATE_SETS_SCHEMA",
    "QUALIFICATION_RECORD_V2_SCHEMA",
    "GateSet",
    "QualificationRecordV2",
    "applicable_gate_set_ids",
    "load_capability_gate_sets",
    "load_qualification_record_v2",
    "parse_capability_gate_sets",
    "parse_qualification_record_v2",
]

CAPABILITY_GATE_SETS_SCHEMA = "mavi-capability-gate-sets-v1"
QUALIFICATION_RECORD_V2_SCHEMA = "2.0"

GateStatus = Literal["pending", "passed"]


# --------------------------------------------------------------------------- gate sets


@dataclass(frozen=True, slots=True)
class GateSet:
    """A named, versioned list of gates and the capabilities it applies to.

    ``scope == "common"`` applies to every capability; ``scope == "capability"``
    applies only to ``capability_ids`` (ADR-014 §6: detector-era gates are never
    imposed on another capability).
    """

    scope: Literal["common", "capability"]
    capability_ids: tuple[str, ...]
    gates: tuple[str, ...]


class _GateSetSchema(StrictModel):
    scope: Literal["common", "capability"]
    capability_ids: tuple[str, ...] = Field(default=(), alias="capabilityIds")
    gates: tuple[str, ...]

    @field_validator("capability_ids")
    @classmethod
    def validate_capability_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("gate_set_capabilities_invalid")
        for capability_id in value:
            require_known_capability(capability_id)
        return value


class _GateSetsSchema(StrictModel):
    schema_version: Literal["mavi-capability-gate-sets-v1"] = Field(alias="schemaVersion")
    gate_sets: dict[str, _GateSetSchema] = Field(alias="gateSets")

    @field_validator("gate_sets")
    @classmethod
    def validate_gate_sets(cls, value: dict[str, _GateSetSchema]) -> dict[str, _GateSetSchema]:
        if not value:
            raise ValueError("gate_sets_empty")
        seen: set[str] = set()
        for gate_set_id, gate_set in value.items():
            require_kebab_id(gate_set_id, code="gate_set_id_invalid")
            if (gate_set.scope == "common") == bool(gate_set.capability_ids):
                raise ValueError(f"gate_set_scope_invalid:{gate_set_id}")
            if not gate_set.gates:
                raise ValueError(f"gate_set_empty:{gate_set_id}")
            for gate in gate_set.gates:
                require_kebab_id(gate, code="gate_name_invalid")
                if gate in seen:
                    raise ValueError(f"gate_name_duplicate:{gate}")
                seen.add(gate)
        return value


def parse_capability_gate_sets(raw: object) -> Mapping[str, GateSet]:
    try:
        parsed = _GateSetsSchema.model_validate(raw)
    except ValidationError as exc:
        raise release_error(exc, default_code="gate_sets_invalid") from exc
    return MappingProxyType(
        {
            gate_set_id: GateSet(scope=item.scope, capability_ids=item.capability_ids, gates=item.gates)
            for gate_set_id, item in parsed.gate_sets.items()
        }
    )


def load_capability_gate_sets(path: Path) -> Mapping[str, GateSet]:
    raw, _payload = read_release_json_v2(path, code="gate_sets_invalid")
    return parse_capability_gate_sets(raw)


def applicable_gate_set_ids(gate_sets: Mapping[str, GateSet], capability_id: str) -> tuple[str, ...]:
    """Every common set plus every capability set that names this capability, sorted."""
    applicable = sorted(
        gate_set_id
        for gate_set_id, gate_set in gate_sets.items()
        if gate_set.scope == "common" or capability_id in gate_set.capability_ids
    )
    if not any(gate_sets[gate_set_id].scope == "capability" for gate_set_id in applicable):
        raise ReleaseMetadataError(f"qualification_capability_gate_set_missing:{capability_id}")
    return tuple(applicable)


# --------------------------------------------------------------------------- record v2


def _require_runtime_pack_id(value: str) -> str:
    if RUNTIME_PACK_ID_RE.fullmatch(value) is None:
        raise ValueError("qualification_runtime_pack_id_invalid")
    return value


class _VariantSchema(StrictModel):
    status: GateStatus
    runtime_pack_id: str | None = Field(alias="runtimePackId")
    gates: dict[str, GateStatus]

    @field_validator("runtime_pack_id")
    @classmethod
    def validate_runtime_pack_id(cls, value: str | None) -> str | None:
        return None if value is None else _require_runtime_pack_id(value)


class _OutputContractSchema(StrictModel):
    schema_id: str = Field(alias="schemaId")

    @field_validator("schema_id")
    @classmethod
    def validate_schema_id(cls, value: str) -> str:
        return require_kebab_id(value, code="qualification_output_contract_invalid")


class _PoliciesSchema(StrictModel):
    # Both keys are always present when `policies` is given; "no policy" has exactly
    # two encodings: the `policies` key omitted, or both fields null.
    pipeline_profile_id: str | None = Field(alias="pipelineProfileId")
    pipeline_profile_sha256: str | None = Field(alias="pipelineProfileSha256")


class _ProtocolSchema(StrictModel):
    corpus_id: str | None = Field(alias="corpusId")
    protocol_version: str | None = Field(alias="protocolVersion")

    @field_validator("corpus_id", "protocol_version")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        return require_optional_text(value, code="qualification_protocol_invalid")


class _SupersedesSchema(StrictModel):
    qualification_id: str = Field(alias="qualificationId")
    reason: str

    @field_validator("qualification_id", "reason")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return require_text(value, code="qualification_supersedes_invalid")


class _QualificationRecordV2Schema(StrictModel):
    schema_version: Literal["2.0"] = Field(alias="schemaVersion")
    qualification_id: str = Field(alias="qualificationId")
    capability_id: str = Field(alias="capabilityId")
    model_pack_id: str = Field(alias="modelPackId")
    model_id: str = Field(alias="modelId")
    model_manifest_sha256: str = Field(alias="modelManifestSha256")
    artifact_sha256: dict[str, str] = Field(alias="artifactSha256")
    runtime_pack_family_id: str = Field(alias="runtimePackFamilyId")
    runtime_profile_sha256: str = Field(alias="runtimeProfileSha256")
    output_contract: _OutputContractSchema = Field(alias="outputContract")
    # Pipeline/aggregation policy is bound "where relevant" (ADR-014 §6); whether a
    # detector record must carry it is decided in S2a.3 (plan §17).
    policies: _PoliciesSchema | None = None

    @field_validator("policies", mode="before")
    @classmethod
    def reject_explicit_null_policies(cls, value: object) -> object:
        if value is None:
            raise ValueError("qualification_policies_invalid")
        return value
    protocol: _ProtocolSchema
    gate_set_ids: tuple[str, ...] = Field(alias="gateSetIds")
    variants: dict[str, _VariantSchema]
    qualified_profiles: tuple[str, ...] = Field(default=(), alias="qualifiedProfiles")
    profile_qualifications: dict[str, _ProfileQualificationSchema] = Field(
        default_factory=dict, alias="profileQualifications"
    )
    evidence: dict[str, dict[str, _QualificationEvidenceSchema]] = Field(default_factory=dict)
    overall_result: GateStatus = Field(alias="overallResult")
    supersedes: _SupersedesSchema | None = None

    @field_validator("qualification_id", "model_id")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return require_text(value, code="qualification_text_invalid")

    @field_validator("capability_id")
    @classmethod
    def validate_capability(cls, value: str) -> str:
        return require_known_capability(value)

    @field_validator("model_pack_id")
    @classmethod
    def validate_model_pack_id(cls, value: str) -> str:
        if MODEL_PACK_ID_RE.fullmatch(value) is None:
            raise ValueError("qualification_model_pack_id_invalid")
        return value

    @field_validator("model_manifest_sha256", "runtime_profile_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        validate_sha256_hex(value)
        return value

    @field_validator("artifact_sha256")
    @classmethod
    def validate_artifact_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("qualification_artifacts_empty")
        for role, digest in value.items():
            require_kebab_id(role, code="qualification_artifact_role_invalid")
            validate_sha256_hex(digest)
        return value

    @field_validator("runtime_pack_family_id")
    @classmethod
    def validate_family(cls, value: str) -> str:
        return require_kebab_id(value, code="qualification_runtime_family_invalid")

    @field_validator("gate_set_ids")
    @classmethod
    def validate_gate_set_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(set(value)) != len(value):
            raise ValueError("qualification_gate_sets_invalid")
        return value

    @field_validator("qualified_profiles")
    @classmethod
    def validate_qualified_profiles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("qualification_profile_duplicate")
        for item in value:
            require_text(item, code="qualification_profile_invalid")
        return value


@dataclass(frozen=True, slots=True)
class QualificationVariantV2:
    status: GateStatus
    runtime_pack_id: str | None
    gates: Mapping[str, GateStatus]


@dataclass(frozen=True, slots=True)
class QualificationRecordV2:
    qualification_id: str
    capability_id: str
    model_pack_id: str
    model_id: str
    model_manifest_sha256: str
    artifact_sha256: Mapping[str, str]
    runtime_pack_family_id: str
    runtime_profile_sha256: str
    output_schema_id: str
    pipeline_profile_id: str | None
    pipeline_profile_sha256: str | None
    gate_set_ids: tuple[str, ...]
    variants: Mapping[str, QualificationVariantV2]
    qualified_profiles: tuple[str, ...]
    profile_runtime_variants: Mapping[str, str]
    profile_policy_sha256: Mapping[str, str]
    profile_evidence_gates: Mapping[str, frozenset[str]]
    overall_result: GateStatus
    supersedes_qualification_id: str | None


def _fail(code: str) -> None:
    raise ReleaseMetadataError(code)


def _check_record_semantics(
    parsed: _QualificationRecordV2Schema,
    gate_sets: Mapping[str, GateSet],
) -> None:
    for variant in sorted(RUNTIME_VARIANTS - set(parsed.variants)):
        _fail(f"qualification_variant_missing:{variant}")
    for variant in sorted(set(parsed.variants) - RUNTIME_VARIANTS):
        _fail(f"qualification_variant_unknown:{variant}")

    for gate_set_id in parsed.gate_set_ids:
        if gate_set_id not in gate_sets:
            _fail(f"qualification_gate_set_unknown:{gate_set_id}")
    # Exactly the sets that apply to this capability: none may be omitted, and a set
    # that belongs to another capability may not be imposed (ADR-014 §6).
    if parsed.gate_set_ids != applicable_gate_set_ids(gate_sets, parsed.capability_id):
        _fail(f"qualification_gate_sets_mismatch:{parsed.capability_id}")
    expected_gates: set[str] = set()
    for gate_set_id in parsed.gate_set_ids:
        expected_gates.update(gate_sets[gate_set_id].gates)

    policies = parsed.policies
    if policies is not None:
        if (policies.pipeline_profile_id is None) != (policies.pipeline_profile_sha256 is None):
            _fail("qualification_policies_incomplete")
        if policies.pipeline_profile_id is not None:
            try:
                require_text(policies.pipeline_profile_id, code="qualification_policies_invalid")
                validate_sha256_hex(policies.pipeline_profile_sha256 or "")
            except ValueError:
                _fail("qualification_policies_invalid")

    for variant_name in sorted(parsed.variants):
        variant = parsed.variants[variant_name]
        if set(variant.gates) != expected_gates:
            _fail(f"qualification_variant_gates_mismatch:{variant_name}")
        all_passed = all(status == "passed" for status in variant.gates.values())
        if variant.status != ("passed" if all_passed else "pending"):
            _fail(f"qualification_variant_status_mismatch:{variant_name}")
        # A variant without a Runtime Pack (class A, ADR-014 §4a) can never pass.
        if variant.runtime_pack_id is None and (
            variant.status != "pending" or any(status != "pending" for status in variant.gates.values())
        ):
            _fail(f"qualification_pending_variant_claims_pass:{variant_name}")

    for variant_name, gate_evidence in parsed.evidence.items():
        if variant_name not in parsed.variants:
            _fail(f"qualification_evidence_variant_unknown:{variant_name}")
        gates = parsed.variants[variant_name].gates
        for gate in gate_evidence:
            if gate not in gates:
                _fail(f"qualification_evidence_gate_unknown:{variant_name}:{gate}")
            if gates[gate] != "passed":
                _fail(f"qualification_evidence_for_pending_gate:{variant_name}:{gate}")
    for variant_name, variant in parsed.variants.items():
        for gate, status in variant.gates.items():
            if status == "passed" and gate not in parsed.evidence.get(variant_name, {}):
                _fail(f"qualification_passed_gate_missing_evidence:{variant_name}:{gate}")

    if set(parsed.qualified_profiles) != set(parsed.profile_qualifications):
        _fail("qualification_profile_index_mismatch")
    for profile_id in sorted(parsed.profile_qualifications):
        profile = parsed.profile_qualifications[profile_id]
        require_text(profile_id, code="qualification_profile_invalid")
        record_variant = parsed.variants[profile.runtime_variant]
        if record_variant.runtime_pack_id is None:
            _fail(f"qualification_pending_variant_claims_pass:{profile.runtime_variant}")
        for gate in profile.evidence:
            if gate not in record_variant.gates:
                _fail(f"qualification_profile_evidence_gate_unknown:{profile_id}:{gate}")

    qualified_variants_passed = bool(parsed.qualified_profiles) and all(
        parsed.variants[parsed.profile_qualifications[profile_id].runtime_variant].status == "passed"
        for profile_id in parsed.qualified_profiles
    )
    if parsed.overall_result != ("passed" if qualified_variants_passed else "pending"):
        _fail("qualification_overall_result_mismatch")


def parse_qualification_record_v2(
    raw: object,
    *,
    gate_sets: Mapping[str, GateSet],
) -> QualificationRecordV2:
    if isinstance(raw, dict) and raw.get("schemaVersion") != QUALIFICATION_RECORD_V2_SCHEMA:
        raise ReleaseMetadataError("qualification_record_schema_unsupported")
    try:
        parsed = _QualificationRecordV2Schema.model_validate(raw)
    except ValidationError as exc:
        raise release_error(exc, default_code="qualification_record_invalid") from exc
    _check_record_semantics(parsed, gate_sets)
    return QualificationRecordV2(
        qualification_id=parsed.qualification_id,
        capability_id=parsed.capability_id,
        model_pack_id=parsed.model_pack_id,
        model_id=parsed.model_id,
        model_manifest_sha256=parsed.model_manifest_sha256,
        artifact_sha256=MappingProxyType(dict(parsed.artifact_sha256)),
        runtime_pack_family_id=parsed.runtime_pack_family_id,
        runtime_profile_sha256=parsed.runtime_profile_sha256,
        output_schema_id=parsed.output_contract.schema_id,
        pipeline_profile_id=None if parsed.policies is None else parsed.policies.pipeline_profile_id,
        pipeline_profile_sha256=None if parsed.policies is None else parsed.policies.pipeline_profile_sha256,
        gate_set_ids=parsed.gate_set_ids,
        variants=MappingProxyType(
            {
                name: QualificationVariantV2(
                    status=item.status,
                    runtime_pack_id=item.runtime_pack_id,
                    gates=MappingProxyType(dict(item.gates)),
                )
                for name, item in parsed.variants.items()
            }
        ),
        qualified_profiles=parsed.qualified_profiles,
        profile_runtime_variants=MappingProxyType(
            {name: item.runtime_variant for name, item in parsed.profile_qualifications.items()}
        ),
        profile_policy_sha256=MappingProxyType(
            {name: item.deployment_profile_policy_sha256 for name, item in parsed.profile_qualifications.items()}
        ),
        profile_evidence_gates=MappingProxyType(
            {name: frozenset(item.evidence) for name, item in parsed.profile_qualifications.items()}
        ),
        overall_result=parsed.overall_result,
        supersedes_qualification_id=(
            None if parsed.supersedes is None else parsed.supersedes.qualification_id
        ),
    )


def load_qualification_record_v2(
    path: Path,
    *,
    gate_sets: Mapping[str, GateSet],
) -> QualificationRecordV2:
    raw, _payload = read_release_json_v2(path, code="qualification_record_invalid")
    return parse_qualification_record_v2(raw, gate_sets=gate_sets)
