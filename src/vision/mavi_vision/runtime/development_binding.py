"""Development replacement bindings (ADR-014 note 2026-10-06).

A Development replacement binding is a complete alternative component binding
that a Development or Testing host may select instead of the release binding.
It is not an overlay: it does not add roles, it replaces the Model Pack and
qualification record of one declared capability, and it is otherwise identical
to the release binding it was derived from.

Every such binding is declared in the tracked producer registry
(``src/vision/config/development-producers-v1.json``), which pins the release
binding by path and SHA-256 (so a changed release binding makes every
declaration stale) and names, per producer, the binding, the Development-only
pipeline profile it runs with and the capabilities it replaces. Only
``vision``/``detector`` may be replaced. ``tools/verify_repo.py`` applies these
rules to the tracked files; the launcher selects a producer by id from the same
registry; the resolver refuses a Development-only profile in Production, and
the replacement's qualification record pins that profile, so a Development
producer can never start in Production.

A **Development role binding** (ADR-014 amendment 2026-10-17, Issue #225) is the other kind the registry declares:
a complete binding for a role the release binding does not have (today only ``plates``), with its own Runtime Pack
family, Model Packs and qualification records, run with a declared Development-only plate pipeline profile. It never
changes or shadows a release role or family, its manifests stay unverified and its records pending and pinned to
that profile, so it can never start in Production either (the resolver refuses a Development-only plate profile).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, ValidationError, field_validator

from mavi_vision.runtime.binding import ComponentBindingV2
from mavi_vision.runtime.manifest import ReleaseMetadataError
from mavi_vision.runtime.schema_common import (
    StrictModel,
    read_release_json_v2,
    release_error,
    require_kebab_id,
)

DEVELOPMENT_PRODUCERS_SCHEMA = "mavi-vision-development-producers-v1"
DEVELOPMENT_PRODUCERS_PATH = "src/vision/config/development-producers-v1.json"
DEVELOPMENT_BINDING_DIRECTORY = "src/vision/config/components"
DEVELOPMENT_BINDING_PREFIX = "development-"
PIPELINE_PROFILE_DIRECTORY = "src/vision/config/pipelines"
# The only capability a Development replacement binding may rebind.
REPLACEABLE_CAPABILITIES = frozenset({("vision", "detector")})
# The only roles a Development role binding may add, and where their pipeline profiles live.
DEVELOPMENT_ROLES = frozenset({"plates"})
PLATE_PROFILE_DIRECTORY = "src/vision/config/plates"


def _fail(code: str) -> ReleaseMetadataError:
    return ReleaseMetadataError(code)


def _repository_path(value: str, *, directory: str, prefix: str = "") -> str:
    path = PurePosixPath(value)
    if (
        "\\" in value
        or path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != value
        or path.parent.as_posix() != directory
        or path.suffix != ".json"
        or not path.name.startswith(prefix)
    ):
        raise ValueError("development_producers_path_invalid")
    return value


class _ReleaseBindingSchema(StrictModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _repository_path(value, directory=DEVELOPMENT_BINDING_DIRECTORY)


class _ReplacementSchema(StrictModel):
    role_id: str = Field(alias="roleId")
    capability_id: str = Field(alias="capabilityId")


class _ProducerSchema(StrictModel):
    producer_id: str = Field(alias="producerId")
    binding_path: str = Field(alias="bindingPath")
    pipeline_profile_path: str = Field(alias="pipelineProfilePath")
    replaces: tuple[_ReplacementSchema, ...]

    @field_validator("producer_id")
    @classmethod
    def validate_producer_id(cls, value: str) -> str:
        return require_kebab_id(value, code="development_producers_invalid:producerId")

    @field_validator("binding_path")
    @classmethod
    def validate_binding_path(cls, value: str) -> str:
        return _repository_path(value, directory=DEVELOPMENT_BINDING_DIRECTORY, prefix=DEVELOPMENT_BINDING_PREFIX)

    @field_validator("pipeline_profile_path")
    @classmethod
    def validate_profile_path(cls, value: str) -> str:
        return _repository_path(value, directory=PIPELINE_PROFILE_DIRECTORY)


class _RoleBindingSchema(StrictModel):
    role_binding_id: str = Field(alias="roleBindingId")
    binding_path: str = Field(alias="bindingPath")
    pipeline_profile_path: str = Field(alias="pipelineProfilePath")
    role_ids: tuple[str, ...] = Field(alias="roleIds")

    @field_validator("role_binding_id")
    @classmethod
    def validate_role_binding_id(cls, value: str) -> str:
        return require_kebab_id(value, code="development_producers_invalid:roleBindingId")

    @field_validator("binding_path")
    @classmethod
    def validate_binding_path(cls, value: str) -> str:
        return _repository_path(value, directory=DEVELOPMENT_BINDING_DIRECTORY, prefix=DEVELOPMENT_BINDING_PREFIX)

    @field_validator("pipeline_profile_path")
    @classmethod
    def validate_profile_path(cls, value: str) -> str:
        return _repository_path(value, directory=PLATE_PROFILE_DIRECTORY, prefix=DEVELOPMENT_BINDING_PREFIX)


class _ProducersSchema(StrictModel):
    schema_version: Literal["mavi-vision-development-producers-v1"] = Field(alias="schemaVersion")
    release_binding: _ReleaseBindingSchema = Field(alias="releaseBinding")
    producers: tuple[_ProducerSchema, ...]
    # Additive (ADR-014 amendment 2026-10-17): absent in a registry that declares none.
    development_role_bindings: tuple[_RoleBindingSchema, ...] = Field(default=(), alias="developmentRoleBindings")


@dataclass(frozen=True, slots=True)
class DevelopmentProducer:
    producer_id: str
    binding_path: str
    pipeline_profile_path: str
    replaces: frozenset[tuple[str, str]]


@dataclass(frozen=True, slots=True)
class DevelopmentRoleBinding:
    role_binding_id: str
    binding_path: str
    pipeline_profile_path: str
    role_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class DevelopmentProducers:
    release_binding_path: str
    release_binding_sha256: str
    producers: tuple[DevelopmentProducer, ...]
    role_bindings: tuple[DevelopmentRoleBinding, ...] = ()

    def producer(self, producer_id: str) -> DevelopmentProducer:
        for item in self.producers:
            if item.producer_id == producer_id:
                return item
        raise _fail(f"development_producer_unknown:{producer_id}")


def parse_development_producers(raw: object) -> DevelopmentProducers:
    if isinstance(raw, dict) and raw.get("schemaVersion") != DEVELOPMENT_PRODUCERS_SCHEMA:
        raise _fail("development_producers_schema_unsupported")
    try:
        parsed = _ProducersSchema.model_validate(raw)
    except ValidationError as exc:
        raise release_error(exc, default_code="development_producers_invalid") from exc
    producers: list[DevelopmentProducer] = []
    for item in parsed.producers:
        replaces = frozenset((entry.role_id, entry.capability_id) for entry in item.replaces)
        if not replaces or len(replaces) != len(item.replaces):
            raise _fail(f"development_producers_invalid:replaces:{item.producer_id}")
        unauthorised = sorted(replaces - REPLACEABLE_CAPABILITIES)
        if unauthorised:
            role_id, capability_id = unauthorised[0]
            raise _fail(f"development_binding_capability_unauthorised:{role_id}:{capability_id}")
        producers.append(
            DevelopmentProducer(
                producer_id=item.producer_id,
                binding_path=item.binding_path,
                pipeline_profile_path=item.pipeline_profile_path,
                replaces=replaces,
            )
        )
    if not producers:
        raise _fail("development_producers_invalid:producers")
    role_bindings: list[DevelopmentRoleBinding] = []
    for item in parsed.development_role_bindings:
        roles = frozenset(item.role_ids)
        if not roles or len(roles) != len(item.role_ids):
            raise _fail(f"development_producers_invalid:roleIds:{item.role_binding_id}")
        unauthorised = sorted(roles - DEVELOPMENT_ROLES)
        if unauthorised:
            raise _fail(f"development_role_binding_role_unauthorised:{unauthorised[0]}")
        role_bindings.append(DevelopmentRoleBinding(item.role_binding_id, item.binding_path, item.pipeline_profile_path, roles))
    for attribute in ("producer_id", "binding_path"):
        values = [getattr(item, attribute) for item in producers]
        if len(set(values)) != len(values):
            raise _fail(f"development_producers_duplicate:{attribute}")
    ids = [item.role_binding_id for item in role_bindings]
    paths = [item.binding_path for item in producers] + [item.binding_path for item in role_bindings]
    if len(set(ids)) != len(ids) or len(set(paths)) != len(paths):
        raise _fail("development_producers_duplicate:binding_path")
    if parsed.release_binding.path.startswith(f"{DEVELOPMENT_BINDING_DIRECTORY}/{DEVELOPMENT_BINDING_PREFIX}"):
        raise _fail("development_producers_release_binding_invalid")
    return DevelopmentProducers(
        release_binding_path=parsed.release_binding.path,
        release_binding_sha256=parsed.release_binding.sha256,
        producers=tuple(producers),
        role_bindings=tuple(role_bindings),
    )


def load_development_producers(path: Path) -> DevelopmentProducers:
    raw, _payload = read_release_json_v2(path, code="development_producers_invalid")
    return parse_development_producers(raw)


def check_release_binding_pin(producers: DevelopmentProducers, *, release_binding_path: str, release_binding_sha256: str) -> None:
    """The registry names exactly the tracked release binding, at its current bytes."""
    if producers.release_binding_path != release_binding_path:
        raise _fail("development_producers_release_binding_mismatch")
    if producers.release_binding_sha256 != release_binding_sha256:
        raise _fail("development_producers_release_binding_stale")


def check_replacement_binding(
    *,
    release: ComponentBindingV2,
    candidate: ComponentBindingV2,
    replaces: frozenset[tuple[str, str]],
) -> None:
    """``candidate`` equals ``release`` except for the declared capability replacements.

    A replaced capability keeps its role and enabled state and must name its own
    qualification record (the release record pins the release pipeline profile);
    it may keep the release Model Pack when only the pipeline policy differs.
    """
    if not candidate.binding_id.startswith(DEVELOPMENT_BINDING_PREFIX):
        raise _fail("development_binding_id_invalid")
    if candidate.binding_id == release.binding_id:
        raise _fail("development_binding_id_invalid")
    if dict(candidate.runtime_pack_families) != dict(release.runtime_pack_families) or any(
        dict(candidate.runtime_pack_families[family]) != dict(variants)
        for family, variants in release.runtime_pack_families.items()
    ):
        raise _fail("development_binding_runtime_packs_changed")
    if dict(candidate.roles) != dict(release.roles):
        raise _fail("development_binding_roles_changed")
    released = {(item.role_id, item.capability_id): item for item in release.capability_bindings}
    offered = {(item.role_id, item.capability_id): item for item in candidate.capability_bindings}
    if set(released) != set(offered):
        changed = sorted(set(released) ^ set(offered))[0]
        raise _fail(f"development_binding_capability_unauthorised:{changed[0]}:{changed[1]}")
    for key, original in released.items():
        replacement = offered[key]
        if key not in replaces:
            if replacement != original:
                raise _fail(f"development_binding_capability_unauthorised:{key[0]}:{key[1]}")
            continue
        if not replacement.enabled or replacement.enabled != original.enabled:
            raise _fail(f"development_binding_capability_disabled:{key[0]}:{key[1]}")
        if replacement.qualification_id == original.qualification_id:
            raise _fail(f"development_binding_reuses_release_qualification:{key[0]}:{key[1]}")


def check_role_binding(*, release: ComponentBindingV2, candidate: ComponentBindingV2, role_ids: frozenset[str]) -> None:
    """``candidate`` adds exactly ``role_ids``, none of which (nor any of whose families) the release binding has."""
    if not candidate.binding_id.startswith(DEVELOPMENT_BINDING_PREFIX) or candidate.binding_id == release.binding_id:
        raise _fail("development_binding_id_invalid")
    if set(candidate.roles) != set(role_ids):
        raise _fail("development_role_binding_roles_mismatch")
    if set(candidate.roles) & set(release.roles):
        raise _fail("development_role_binding_shadows_release_role")
    if set(candidate.runtime_pack_families) & set(release.runtime_pack_families):
        raise _fail("development_role_binding_shares_release_family")
    if any(not item.enabled for item in candidate.capability_bindings):
        raise _fail("development_role_binding_capability_disabled")


__all__ = [
    "DEVELOPMENT_BINDING_DIRECTORY",
    "DEVELOPMENT_BINDING_PREFIX",
    "DEVELOPMENT_PRODUCERS_PATH",
    "DEVELOPMENT_PRODUCERS_SCHEMA",
    "DEVELOPMENT_ROLES",
    "DevelopmentProducer",
    "DevelopmentProducers",
    "DevelopmentRoleBinding",
    "PLATE_PROFILE_DIRECTORY",
    "REPLACEABLE_CAPABILITIES",
    "check_release_binding_pin",
    "check_replacement_binding",
    "check_role_binding",
    "load_development_producers",
    "parse_development_producers",
]
