"""Component binding v2 (ADR-014 §1, §5, §9; S2a plan §4.1, P-1, P-2, P-4-P-6, P-11, P-16).

The binding is the application/release overlay's selection: which Runtime Pack
family variants the release can deploy, which roles run from which family and
serve which capabilities, and which Model Pack and qualification record each
capability is bound to. File-local rules are enforced here; rules that need other
artefacts (runtime-profile variant classes, manifests, records) are enforced by
the resolver and ``verify_repo`` (S2a.3).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping

from pydantic import Field, StrictBool, ValidationError, field_validator, model_validator

from mavi_vision.runtime.capabilities import require_known_capability
from mavi_vision.runtime.component_identity import RUNTIME_PACK_ID_RE
from mavi_vision.runtime.manifest import (
    ReleaseMetadataError,
    validate_sha256_hex,
)
from mavi_vision.runtime.model_pack_identity import MODEL_PACK_ID_RE
from mavi_vision.runtime.schema_common import (
    StrictModel,
    read_release_json_v2,
    release_error,
    require_kebab_id,
    require_text,
)
from mavi_vision.runtime.variants import RUNTIME_VARIANTS

__all__ = [
    "COMPONENT_BINDING_V2_SCHEMA",
    "KNOWN_PROVENANCE_CONTRACTS",
    "KNOWN_READINESS_CONTRACTS",
    "CapabilityBindingV2",
    "ComponentBindingV2",
    "RoleV2",
    "RuntimePackVariantV2",
    "load_component_binding",
    "parse_component_binding",
]

COMPONENT_BINDING_V2_SCHEMA = "mavi-vision-component-binding-v2"

# Closed contract vocabularies a role may declare. A role declares exactly one
# provenance contract; startup enforcement against the worker's effective
# completion schema is the resolver's job (P-16, S2a.3).
KNOWN_READINESS_CONTRACTS = frozenset({"worker-health-v2"})
KNOWN_PROVENANCE_CONTRACTS = frozenset({"vision-job-complete-v3.2"})

_ENTRY_POINT_RE = re.compile(r"^[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+$")


class _RuntimePackVariantSchema(StrictModel):
    runtime_pack_id: str = Field(alias="runtimePackId")
    third_party_lock_sha256: str = Field(alias="thirdPartyLockSha256")
    runtime_requirements_sha256: str = Field(alias="runtimeRequirementsSha256")
    native_abi: str = Field(alias="nativeAbi")

    @field_validator("runtime_pack_id")
    @classmethod
    def validate_runtime_pack_id(cls, value: str) -> str:
        if RUNTIME_PACK_ID_RE.fullmatch(value) is None:
            raise ValueError("component_binding_invalid:runtimePackId")
        return value

    @field_validator("third_party_lock_sha256", "runtime_requirements_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        try:
            validate_sha256_hex(value)
        except ValueError as exc:
            raise ValueError("component_binding_invalid:sha256") from exc
        return value

    @field_validator("native_abi")
    @classmethod
    def validate_native_abi(cls, value: str) -> str:
        return require_text(value, code="component_binding_invalid:nativeAbi")


class _RuntimePackFamilySchema(StrictModel):
    runtime_pack_family_id: str = Field(alias="runtimePackFamilyId")
    variants: dict[str, _RuntimePackVariantSchema]

    @field_validator("runtime_pack_family_id")
    @classmethod
    def validate_family_id(cls, value: str) -> str:
        return require_kebab_id(value, code="component_binding_invalid:runtimePackFamilyId")

    @field_validator("variants")
    @classmethod
    def validate_variant_keys(
        cls, value: dict[str, _RuntimePackVariantSchema]
    ) -> dict[str, _RuntimePackVariantSchema]:
        if not value:
            raise ValueError("component_binding_invalid:variants")
        for variant in sorted(value):
            if variant not in RUNTIME_VARIANTS:
                raise ValueError(f"binding_variant_unknown:{variant}")
        return value


class _RoleSchema(StrictModel):
    role_id: str = Field(alias="roleId")
    runtime_pack_family_id: str = Field(alias="runtimePackFamilyId")
    capability_ids: tuple[str, ...] = Field(alias="capabilityIds")
    entry_point: str = Field(alias="entryPoint")
    readiness_contract: str = Field(alias="readinessContract")
    provenance_contract: str = Field(alias="provenanceContract")

    @field_validator("role_id")
    @classmethod
    def validate_role_id(cls, value: str) -> str:
        return require_kebab_id(value, code="component_binding_invalid:roleId")

    @field_validator("capability_ids")
    @classmethod
    def validate_capability_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("component_binding_invalid:capabilityIds")
        if len(set(value)) != len(value):
            raise ValueError("role_capability_duplicate")
        for capability_id in value:
            require_known_capability(capability_id)
        return value

    @field_validator("entry_point")
    @classmethod
    def validate_entry_point(cls, value: str) -> str:
        if _ENTRY_POINT_RE.fullmatch(value) is None:
            raise ValueError("component_binding_invalid:entryPoint")
        return value

    @field_validator("readiness_contract")
    @classmethod
    def validate_readiness_contract(cls, value: str) -> str:
        if value not in KNOWN_READINESS_CONTRACTS:
            raise ValueError(f"role_readiness_contract_unknown:{value}")
        return value

    @field_validator("provenance_contract")
    @classmethod
    def validate_provenance_contract(cls, value: str) -> str:
        if value not in KNOWN_PROVENANCE_CONTRACTS:
            raise ValueError(f"role_provenance_contract_unknown:{value}")
        return value


class _CapabilityBindingSchema(StrictModel):
    capability_id: str = Field(alias="capabilityId")
    role_id: str = Field(alias="roleId")
    model_pack_id: str = Field(alias="modelPackId")
    qualification_id: str = Field(alias="qualificationId")
    enabled: StrictBool

    @field_validator("capability_id")
    @classmethod
    def validate_capability_id(cls, value: str) -> str:
        return require_known_capability(value)

    @field_validator("model_pack_id")
    @classmethod
    def validate_model_pack_id(cls, value: str) -> str:
        if MODEL_PACK_ID_RE.fullmatch(value) is None:
            raise ValueError("component_binding_invalid:modelPackId")
        return value

    @field_validator("qualification_id")
    @classmethod
    def validate_qualification_id(cls, value: str) -> str:
        return require_text(value, code="component_binding_invalid:qualificationId")


class _ComponentBindingSchema(StrictModel):
    schema_version: Literal["mavi-vision-component-binding-v2"] = Field(alias="schemaVersion")
    binding_id: str = Field(alias="bindingId")
    runtime_packs: tuple[_RuntimePackFamilySchema, ...] = Field(alias="runtimePacks")
    roles: tuple[_RoleSchema, ...]
    capability_bindings: tuple[_CapabilityBindingSchema, ...] = Field(alias="capabilityBindings")

    @field_validator("binding_id")
    @classmethod
    def validate_binding_id(cls, value: str) -> str:
        return require_kebab_id(value, code="component_binding_invalid:bindingId")

    @model_validator(mode="after")
    def validate_relationships(self) -> "_ComponentBindingSchema":
        families = [family.runtime_pack_family_id for family in self.runtime_packs]
        if not families:
            raise ValueError("component_binding_invalid:runtimePacks")
        if len(set(families)) != len(families):
            raise ValueError("runtime_family_duplicate")

        role_ids = [role.role_id for role in self.roles]
        if not role_ids:
            raise ValueError("component_binding_invalid:roles")
        if len(set(role_ids)) != len(role_ids):
            raise ValueError("role_duplicate")
        roles = {role.role_id: role for role in self.roles}
        for role in self.roles:
            if role.runtime_pack_family_id not in families:
                raise ValueError(f"runtime_family_unknown:{role.runtime_pack_family_id}")

        capability_ids = [binding.capability_id for binding in self.capability_bindings]
        if len(set(capability_ids)) != len(capability_ids):
            raise ValueError("capability_binding_duplicate")
        if capability_ids != sorted(capability_ids):
            raise ValueError("capability_bindings_unordered")

        bound: dict[str, str] = {}
        for binding in self.capability_bindings:
            role = roles.get(binding.role_id)
            if role is None:
                raise ValueError(f"role_unknown:{binding.role_id}")
            if binding.capability_id not in role.capability_ids:
                raise ValueError(f"capability_not_served_by_role:{binding.role_id}:{binding.capability_id}")
            bound[binding.capability_id] = binding.role_id

        # Required-ness is per role (P-6): every capability a role serves has exactly
        # one binding. A capability served by two roles would need two bindings with
        # the same capabilityId, which the uniqueness rule above already refuses.
        for role in self.roles:
            for capability_id in role.capability_ids:
                if bound.get(capability_id) != role.role_id:
                    raise ValueError(f"capability_binding_missing:{role.role_id}:{capability_id}")
        return self


@dataclass(frozen=True, slots=True)
class RuntimePackVariantV2:
    runtime_pack_id: str
    third_party_lock_sha256: str
    runtime_requirements_sha256: str
    native_abi: str


@dataclass(frozen=True, slots=True)
class RoleV2:
    role_id: str
    runtime_pack_family_id: str
    capability_ids: tuple[str, ...]
    entry_point: str
    readiness_contract: str
    provenance_contract: str


@dataclass(frozen=True, slots=True)
class CapabilityBindingV2:
    capability_id: str
    role_id: str
    model_pack_id: str
    qualification_id: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class ComponentBindingV2:
    binding_id: str
    runtime_pack_families: Mapping[str, Mapping[str, RuntimePackVariantV2]]
    roles: Mapping[str, RoleV2]
    capability_bindings: tuple[CapabilityBindingV2, ...]
    component_binding_sha256: str

    def family_variants(self, runtime_pack_family_id: str) -> Mapping[str, RuntimePackVariantV2]:
        variants = self.runtime_pack_families.get(runtime_pack_family_id)
        if variants is None:
            raise ReleaseMetadataError(f"runtime_family_unknown:{runtime_pack_family_id}")
        return variants

    def role(self, role_id: str) -> RoleV2:
        role = self.roles.get(role_id)
        if role is None:
            raise ReleaseMetadataError(f"role_unknown:{role_id}")
        return role

    def bindings_for_role(self, role_id: str) -> tuple[CapabilityBindingV2, ...]:
        self.role(role_id)
        return tuple(binding for binding in self.capability_bindings if binding.role_id == role_id)


def parse_component_binding(raw: object, *, component_binding_sha256: str) -> ComponentBindingV2:
    try:
        validate_sha256_hex(component_binding_sha256)
    except ValueError as exc:
        raise ReleaseMetadataError("component_binding_sha256_invalid") from exc
    if isinstance(raw, dict) and raw.get("schemaVersion") != COMPONENT_BINDING_V2_SCHEMA:
        raise ReleaseMetadataError("component_binding_schema_unsupported")
    try:
        parsed = _ComponentBindingSchema.model_validate(raw)
    except ValidationError as exc:
        raise release_error(exc, default_code="component_binding_invalid") from exc
    return ComponentBindingV2(
        binding_id=parsed.binding_id,
        runtime_pack_families=MappingProxyType(
            {
                family.runtime_pack_family_id: MappingProxyType(
                    {
                        name: RuntimePackVariantV2(
                            runtime_pack_id=item.runtime_pack_id,
                            third_party_lock_sha256=item.third_party_lock_sha256,
                            runtime_requirements_sha256=item.runtime_requirements_sha256,
                            native_abi=item.native_abi,
                        )
                        for name, item in family.variants.items()
                    }
                )
                for family in parsed.runtime_packs
            }
        ),
        roles=MappingProxyType(
            {
                role.role_id: RoleV2(
                    role_id=role.role_id,
                    runtime_pack_family_id=role.runtime_pack_family_id,
                    capability_ids=role.capability_ids,
                    entry_point=role.entry_point,
                    readiness_contract=role.readiness_contract,
                    provenance_contract=role.provenance_contract,
                )
                for role in parsed.roles
            }
        ),
        capability_bindings=tuple(
            CapabilityBindingV2(
                capability_id=binding.capability_id,
                role_id=binding.role_id,
                model_pack_id=binding.model_pack_id,
                qualification_id=binding.qualification_id,
                enabled=binding.enabled,
            )
            for binding in parsed.capability_bindings
        ),
        component_binding_sha256=component_binding_sha256,
    )


def load_component_binding(path: Path) -> ComponentBindingV2:
    """Load a binding file; its identity is the SHA-256 of the exact file bytes (P-11)."""
    # One read: the bytes hashed are exactly the bytes parsed; duplicate keys fail.
    raw, payload = read_release_json_v2(path, code="component_binding_invalid")
    return parse_component_binding(raw, component_binding_sha256=hashlib.sha256(payload).hexdigest())
