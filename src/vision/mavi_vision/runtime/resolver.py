"""Component Binding v2 role resolver: the worker's one composition root.

ADR-014 §1-§11; S2a plan §5.1, P-2, P-6, P-8, P-9, P-13, P-16, P-17.

A role starts only from the component binding. The resolver loads the binding,
the role's Runtime Pack family profile, every bound Model Pack manifest (found by
scanning and indexing the derived ``modelPackId``, never by a configured path),
every bound qualification record (indexed by ``qualificationId``) and, when one is
installed, the Runtime Pack manifest. Each check fails closed with a stable code
and nothing is inferred to make startup succeed: a Runtime Pack identity is taken
from an installed pack whose identity re-derives, never from the binding or the
qualification record.

Order of checks (plan §5.1): role -> provenance contract (P-16) -> family profile ->
locks -> P-17 variant classes -> observed variant declared -> lock/requirements
bytes -> installed Runtime Pack -> per capability: enabled, implemented, manifest,
runtime compatibility, artefact bytes, qualification record, relationships and
policies -> environment policy.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Collection, Literal, Mapping

from mavi_vision.runtime.binding import (
    CapabilityBindingV2,
    ComponentBindingV2,
    RoleV2,
    RuntimePackVariantV2,
    load_component_binding,
)
from mavi_vision.runtime.capabilities import require_implemented_capability
from mavi_vision.runtime.component_identity import (
    ComponentIdentityError,
    RuntimePackIdentityInputs,
    runtime_pack_id,
)
from mavi_vision.runtime.component_relationships import (
    check_binding_variants,
    check_record_variants,
)
from mavi_vision.runtime.deployment_profiles import DeploymentProfile
from mavi_vision.runtime.manifest import (
    ArtifactRef,
    ReleaseMetadataError,
    resolve_release_artifact,
    sha256_release_file,
)
from mavi_vision.runtime.model_manifest_v2 import ModelManifestV2, load_model_manifest_v2
from mavi_vision.runtime.profile import (
    PipelineProfile,
    load_pipeline_profile,
    validate_profile_against_manifest,
)
from mavi_vision.runtime.qualification import (
    RuntimePlatformVariantIdentity,
    RuntimeReleaseLockIdentity,
    runtime_platform_variant_identities,
    runtime_release_lock_identities,
    runtime_semantic_graph_identity,
    verify_runtime_release_locks,
)
from mavi_vision.runtime.qualification_v2 import (
    QualificationRecordV2,
    load_capability_gate_sets,
    load_qualification_record_v2,
)
from mavi_vision.runtime.runtime_profile_v2 import (
    RuntimeProfileV2,
    classify_runtime_variants,
    load_runtime_profile_v2,
)
from mavi_vision.runtime.variants import RUNTIME_VARIANTS, VariantClass

_LOGGER = logging.getLogger(__name__)

DETECTOR_CAPABILITY = "detector"
INSTALLED_PACK: Literal["installed-pack"] = "installed-pack"
UNPACKED_ENVIRONMENT: Literal["unpacked-environment"] = "unpacked-environment"
RuntimePackSource = Literal["installed-pack", "unpacked-environment"]

RUNTIME_PACK_MANIFEST_SCHEMA = "mavi-vision-runtime-pack-v2"
GATE_SETS_RELATIVE = Path("config/acceptance/capability-gate-sets-v1.json")
MANIFESTS_RELATIVE = Path("models/manifests")
QUALIFICATIONS_RELATIVE = Path("models/qualifications")
RUNTIME_PROFILES_RELATIVE = Path("src/vision/runtime")

# A role's declared provenance contract and the completion schema it emits (P-16).
PROVENANCE_CONTRACT_VERSIONS: Mapping[str, str] = MappingProxyType({"vision-job-complete-v3.2": "3.2"})
# The explicit, Development-only, non-qualifying override (P-16; ADR-014 amendment).
COMPLETION_OVERRIDE_VERSIONS = frozenset({"3.0", "3.1"})

_QUALIFIED_VARIANT_STATUS = {"cpu": "qualified-hosted-cpu", "cuda": "qualified-hardware"}


def _fail(code: str) -> ReleaseMetadataError:
    return ReleaseMetadataError(code)


# --------------------------------------------------------------------------- results


@dataclass(frozen=True, slots=True)
class CompletionContract:
    """The completion schema a role emits and whether the P-16 override chose it."""

    version: str
    override: str | None

    def __post_init__(self) -> None:
        # Structural, not advisory: a 3.0/3.1 contract exists only as the P-16
        # override, so no worker path can emit a pre-cut-over version by default.
        if self.override is None:
            if self.version not in PROVENANCE_CONTRACT_VERSIONS.values():
                raise ValueError("completion_contract_version_not_a_role_contract")
        elif self.override not in COMPLETION_OVERRIDE_VERSIONS or self.version != self.override:
            raise ValueError("completion_override_invalid")

    @property
    def override_active(self) -> bool:
        return self.override is not None


@dataclass(frozen=True, slots=True)
class RoleFamily:
    """What device resolution needs before the observed variant is known."""

    role: RoleV2
    runtime_profile: RuntimeProfileV2
    runtime_profile_path: Path
    runtime_profile_sha256: str
    variant_classes: Mapping[str, VariantClass]
    runtime_semantic_graph: Mapping[str, str]
    runtime_platform_variants: Mapping[str, RuntimePlatformVariantIdentity]
    runtime_release_locks: Mapping[str, RuntimeReleaseLockIdentity]


@dataclass(frozen=True, slots=True)
class ResolvedRuntimePack:
    runtime_pack_family_id: str
    runtime_variant: str
    binding_entry: RuntimePackVariantV2
    lock_path: Path
    runtime_pack_source: RuntimePackSource
    # Present exactly when a Runtime Pack is installed and its identity re-derived.
    runtime_pack_id: str | None


@dataclass(frozen=True, slots=True)
class ResolvedCapability:
    capability_id: str
    binding: CapabilityBindingV2
    manifest: ModelManifestV2
    manifest_path: Path
    manifest_sha256: str
    model_pack_id: str
    artifact_paths: Mapping[str, Path]
    qualification: QualificationRecordV2
    qualification_path: Path
    qualification_sha256: str


@dataclass(frozen=True, slots=True)
class DetectorModelView:
    """The detector capability's model identity, read through its v2 section."""

    backend: str
    architecture: str
    model_id: str
    model_version: str
    class_vocabulary: tuple[str, ...]
    checkpoint: ArtifactRef
    resolved_config: ArtifactRef


@dataclass(frozen=True, slots=True)
class DetectorSelection:
    """Everything the detector runtime and provenance need, from one resolution."""

    resolved_role: "ResolvedRole"
    capability: ResolvedCapability
    detector: DetectorModelView
    profile: PipelineProfile
    profile_sha256: str
    checkpoint_path: Path
    resolved_config_path: Path
    # The manifest's own status; the effective label is decided by provenance.
    verification_status: Literal["verified", "unverified"]
    runtime_qualification_status: Literal["partial", "qualified"]
    runtime_semantic_graph: Mapping[str, str]
    runtime_platform_variants: Mapping[str, RuntimePlatformVariantIdentity]
    runtime_release_locks: Mapping[str, RuntimeReleaseLockIdentity]


@dataclass(frozen=True, slots=True)
class ResolvedRole:
    role: RoleV2
    binding: ComponentBindingV2
    binding_path: Path
    family: RoleFamily
    runtime_pack: ResolvedRuntimePack
    capabilities: Mapping[str, ResolvedCapability]
    pipeline_profile: PipelineProfile
    pipeline_profile_sha256: str
    completion: CompletionContract
    production_mode: bool

    @property
    def component_binding_sha256(self) -> str:
        return self.binding.component_binding_sha256

    @property
    def runtime_variant(self) -> str:
        return self.runtime_pack.runtime_variant

    def detector_selection(self) -> DetectorSelection:
        capability = self.capabilities.get(DETECTOR_CAPABILITY)
        if capability is None:
            raise _fail(f"capability_binding_missing:{self.role.role_id}:{DETECTOR_CAPABILITY}")
        section = capability.manifest.detector_section()
        family = self.family
        return DetectorSelection(
            resolved_role=self,
            capability=capability,
            detector=DetectorModelView(
                backend=section.backend,
                architecture=section.architecture,
                model_id=capability.manifest.model_id,
                model_version=capability.manifest.model_version,
                class_vocabulary=section.class_vocabulary,
                checkpoint=ArtifactRef(
                    relative_path=section.checkpoint.relative_path,
                    sha256=section.checkpoint.sha256,
                ),
                resolved_config=ArtifactRef(
                    relative_path=section.resolved_config.relative_path,
                    sha256=section.resolved_config.sha256,
                ),
            ),
            profile=self.pipeline_profile,
            profile_sha256=self.pipeline_profile_sha256,
            checkpoint_path=capability.artifact_paths[section.checkpoint.artifact_role],
            resolved_config_path=capability.artifact_paths[section.resolved_config.artifact_role],
            verification_status=capability.manifest.verification_status,
            runtime_qualification_status=family.runtime_profile.qualification_status,
            runtime_semantic_graph=family.runtime_semantic_graph,
            runtime_platform_variants=family.runtime_platform_variants,
            runtime_release_locks=family.runtime_release_locks,
        )


# --------------------------------------------------------------------------- contract (P-16)


def resolve_completion_contract(
    role: RoleV2,
    *,
    override: str | None,
    production_mode: bool,
    emittable_versions: Collection[str],
) -> CompletionContract:
    """The completion schema the role emits: its contract's, unless the explicit override.

    The override is Development-only and non-qualifying (P-16): it is refused in
    Production, and provenance forces ``unverified`` whenever it is active.
    """
    contract_version = PROVENANCE_CONTRACT_VERSIONS.get(role.provenance_contract)
    if contract_version is None:
        raise _fail(f"role_provenance_contract_unknown:{role.provenance_contract}")
    if override is not None:
        if production_mode:
            raise _fail("completion_override_forbidden_in_production")
        if override not in COMPLETION_OVERRIDE_VERSIONS:
            raise _fail("completion_override_invalid")
        version = override
    else:
        version = contract_version
    if version not in emittable_versions:
        raise _fail("role_provenance_contract_mismatch")
    return CompletionContract(version=version, override=override)


# --------------------------------------------------------------------------- family


def _tracked_lock_variants(runtime_dir: Path) -> tuple[str, ...]:
    return tuple(variant for variant in sorted(RUNTIME_VARIANTS) if (runtime_dir / f"{variant}.lock").is_file())


def load_role_family(*, binding: ComponentBindingV2, role_id: str, overlay_root: Path) -> RoleFamily:
    """Role -> family profile -> locks -> P-17 classes, cross-checked with the binding."""
    role = binding.role(role_id)
    family_id = role.runtime_pack_family_id
    binding_variants = binding.family_variants(family_id)
    runtime_profile_path = overlay_root / RUNTIME_PROFILES_RELATIVE / family_id / "runtime.json"
    if not runtime_profile_path.is_file():
        raise _fail(f"runtime_family_unknown:{family_id}")
    profile = load_runtime_profile_v2(runtime_profile_path)
    # A Runtime Pack family is identified by its runtime profile id (P-2).
    if profile.runtime_profile_id != family_id:
        raise _fail(f"runtime_family_profile_mismatch:{family_id}")
    verify_runtime_release_locks(runtime_profile_path, profile)
    classes = classify_runtime_variants(
        profile,
        tracked_lock_variants=_tracked_lock_variants(runtime_profile_path.parent),
    )
    check_binding_variants(binding_variants=binding_variants, variant_classes=classes)
    _check_binding_runtime_pack_ids(
        profile=profile,
        runtime_dir=runtime_profile_path.parent,
        binding_variants=binding_variants,
    )
    return RoleFamily(
        role=role,
        runtime_profile=profile,
        runtime_profile_path=runtime_profile_path,
        runtime_profile_sha256=sha256_release_file(runtime_profile_path),
        variant_classes=classes,
        runtime_semantic_graph=runtime_semantic_graph_identity(profile),
        runtime_platform_variants=runtime_platform_variant_identities(profile),
        runtime_release_locks=runtime_release_lock_identities(profile),
    )


def _check_binding_runtime_pack_ids(
    *,
    profile: RuntimeProfileV2,
    runtime_dir: Path,
    binding_variants: Mapping[str, RuntimePackVariantV2],
) -> None:
    """Every pinned Runtime Pack id is the one its tracked lock derives (P-17 class B).

    Checked for every declared variant, not only the observed one, so a binding
    that pins an id no lock produces never loads, installed pack or not.
    """
    for variant in sorted(binding_variants):
        entry = binding_variants[variant]
        try:
            lock_sha256 = sha256_release_file(runtime_dir / f"{variant}.lock")
            requirements_sha256 = sha256_release_file(runtime_dir / f"{variant}.requirements.txt")
        except ReleaseMetadataError as exc:
            raise _fail(f"runtime_lock_binding_mismatch:{variant}") from exc
        if lock_sha256 != entry.third_party_lock_sha256:
            raise _fail(f"runtime_lock_binding_mismatch:{variant}")
        if requirements_sha256 != entry.runtime_requirements_sha256:
            raise _fail(f"runtime_requirements_binding_mismatch:{variant}")
        python_identity = profile.platform_variants[variant].python_identity
        if python_identity is None:
            raise _fail(f"runtime_pack_binding_id_mismatch:{variant}")
        try:
            derived = runtime_pack_id(
                RuntimePackIdentityInputs(
                    platform_variant=variant,
                    python_version=python_identity.version,
                    third_party_lock_sha256=lock_sha256,
                    runtime_requirements_sha256=requirements_sha256,
                    native_abi=entry.native_abi,
                )
            )
        except ComponentIdentityError as exc:
            raise _fail(f"runtime_pack_binding_id_mismatch:{variant}") from exc
        if derived != entry.runtime_pack_id:
            raise _fail(f"runtime_pack_binding_id_mismatch:{variant}")


# --------------------------------------------------------------------------- Runtime Pack


def _resolve_runtime_pack(
    *,
    family: RoleFamily,
    binding: ComponentBindingV2,
    runtime_variant: str,
    runtime_pack_manifest_path: Path | None,
    python_version: str,
) -> ResolvedRuntimePack:
    family_id = family.role.runtime_pack_family_id
    # The resolver never consults the qualification record to find a Runtime Pack:
    # an undeclared variant (class A today: linux-x86_64-cuda) never starts.
    entry = binding.family_variants(family_id).get(runtime_variant)
    if entry is None:
        raise _fail(f"runtime_variant_not_declared:{runtime_variant}")
    runtime_dir = family.runtime_profile_path.parent
    lock_path = runtime_dir / f"{runtime_variant}.lock"
    requirements_path = runtime_dir / f"{runtime_variant}.requirements.txt"
    # The lock *file* is compared, so a pending-lock variant such as
    # windows-x86_64-cuda still cross-checks (P-13).
    try:
        lock_sha256 = sha256_release_file(lock_path)
        requirements_sha256 = sha256_release_file(requirements_path)
    except ReleaseMetadataError as exc:
        raise _fail(f"runtime_lock_binding_mismatch:{runtime_variant}") from exc
    if lock_sha256 != entry.third_party_lock_sha256:
        raise _fail(f"runtime_lock_binding_mismatch:{runtime_variant}")
    if requirements_sha256 != entry.runtime_requirements_sha256:
        raise _fail(f"runtime_requirements_binding_mismatch:{runtime_variant}")

    if runtime_pack_manifest_path is None:
        # Truthful: a virtual environment installed from the lock is not a pack (P-8).
        return ResolvedRuntimePack(
            runtime_pack_family_id=family_id,
            runtime_variant=runtime_variant,
            binding_entry=entry,
            lock_path=lock_path,
            runtime_pack_source=UNPACKED_ENVIRONMENT,
            runtime_pack_id=None,
        )
    manifest = _read_runtime_pack_manifest(runtime_pack_manifest_path)
    try:
        derived = runtime_pack_id(
            RuntimePackIdentityInputs(
                platform_variant=manifest["platformVariant"],
                python_version=manifest["pythonVersion"],
                third_party_lock_sha256=manifest["thirdPartyLockSha256"],
                runtime_requirements_sha256=manifest["runtimeRequirementsSha256"],
                native_abi=manifest["nativeAbi"],
            )
        )
    except ComponentIdentityError as exc:
        raise _fail("runtime_pack_manifest_invalid") from exc
    if manifest["runtimePackId"] != derived:
        raise _fail("runtime_pack_manifest_mismatch:id")
    if manifest["platformVariant"] != runtime_variant:
        raise _fail("runtime_pack_variant_mismatch")
    if derived != entry.runtime_pack_id:
        raise _fail("runtime_pack_manifest_mismatch:binding")
    if manifest["thirdPartyLockSha256"] != entry.third_party_lock_sha256:
        raise _fail("runtime_pack_manifest_mismatch:lock")
    if manifest["runtimeRequirementsSha256"] != entry.runtime_requirements_sha256:
        raise _fail("runtime_pack_manifest_mismatch:requirements")
    if manifest["nativeAbi"] != entry.native_abi:
        raise _fail("runtime_pack_manifest_mismatch:nativeAbi")
    if manifest["pythonVersion"] != python_version:
        raise _fail("runtime_pack_manifest_mismatch:python")
    return ResolvedRuntimePack(
        runtime_pack_family_id=family_id,
        runtime_variant=runtime_variant,
        binding_entry=entry,
        lock_path=lock_path,
        runtime_pack_source=INSTALLED_PACK,
        runtime_pack_id=derived,
    )


_RUNTIME_PACK_MANIFEST_TEXT_FIELDS = (
    "runtimePackId",
    "platformVariant",
    "pythonVersion",
    "nativeAbi",
    "thirdPartyLockSha256",
    "runtimeRequirementsSha256",
)


def _read_runtime_pack_manifest(path: Path) -> dict[str, str]:
    try:
        raw = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _fail("runtime_pack_manifest_invalid") from exc
    if not isinstance(raw, dict) or raw.get("schemaVersion") != RUNTIME_PACK_MANIFEST_SCHEMA:
        raise _fail("runtime_pack_manifest_invalid")
    fields: dict[str, str] = {}
    for name in _RUNTIME_PACK_MANIFEST_TEXT_FIELDS:
        value = raw.get(name)
        if not isinstance(value, str) or not value:
            raise _fail("runtime_pack_manifest_invalid")
        fields[name] = value
    return fields


# --------------------------------------------------------------------------- indexes (P-9)


def index_model_manifests(manifests_root: Path) -> Mapping[str, tuple[ModelManifestV2, Path]]:
    """Every source manifest by derived ``modelPackId``; two deriving one id fail closed."""
    index: dict[str, tuple[ModelManifestV2, Path]] = {}
    for path in sorted(manifests_root.glob("*.json")):
        manifest = load_model_manifest_v2(path)
        if manifest.model_pack_id in index:
            raise _fail(f"model_manifest_ambiguous:{manifest.model_pack_id}")
        index[manifest.model_pack_id] = (manifest, path)
    return MappingProxyType(index)


def index_qualification_records(
    qualifications_root: Path,
    *,
    gate_sets_path: Path,
) -> Mapping[str, tuple[QualificationRecordV2, Path]]:
    gate_sets = load_capability_gate_sets(gate_sets_path)
    index: dict[str, tuple[QualificationRecordV2, Path]] = {}
    for path in sorted(qualifications_root.glob("*.json")):
        record = load_qualification_record_v2(path, gate_sets=gate_sets)
        if record.qualification_id in index:
            raise _fail(f"qualification_record_ambiguous:{record.qualification_id}")
        index[record.qualification_id] = (record, path)
    return MappingProxyType(index)


# --------------------------------------------------------------------------- capability


def _resolve_capability(
    *,
    binding: CapabilityBindingV2,
    family: RoleFamily,
    manifests: Mapping[str, tuple[ModelManifestV2, Path]],
    records: Mapping[str, tuple[QualificationRecordV2, Path]],
    model_root: Path,
    pipeline_profile: PipelineProfile,
    pipeline_profile_sha256: str,
) -> ResolvedCapability:
    capability_id = binding.capability_id
    if not binding.enabled:
        raise _fail("capability_binding_disabled")
    try:
        require_implemented_capability(capability_id)
    except ValueError as exc:
        raise _fail(str(exc)) from exc

    found = manifests.get(binding.model_pack_id)
    if found is None:
        raise _fail(f"model_manifest_missing:{binding.model_pack_id}")
    manifest, manifest_path = found
    if capability_id not in manifest.capability_ids:
        raise _fail(f"model_capability_mismatch:{capability_id}")
    if family.role.runtime_pack_family_id not in manifest.runtime_pack_family_ids:
        raise _fail("model_runtime_incompatible")

    artifact_paths: dict[str, Path] = {}
    for artifact in manifest.artifacts:
        reference = ArtifactRef(relative_path=artifact.relative_path, sha256=artifact.sha256)
        try:
            path = resolve_release_artifact(model_root, reference)
            digest = sha256_release_file(path)
        except ReleaseMetadataError as exc:
            raise _fail(f"model_artifact_missing:{artifact.artifact_role}") from exc
        if digest != artifact.sha256:
            raise _fail(f"model_artifact_hash_mismatch:{artifact.artifact_role}")
        artifact_paths[artifact.artifact_role] = path

    found_record = records.get(binding.qualification_id)
    if found_record is None:
        raise _fail(f"qualification_record_missing:{binding.qualification_id}")
    record, record_path = found_record
    manifest_sha256 = sha256_release_file(manifest_path)
    expected = {
        "capability_id": capability_id,
        "model_pack_id": binding.model_pack_id,
        "model_id": manifest.model_id,
        "model_manifest_sha256": manifest_sha256,
        "artifact_sha256": {artifact.artifact_role: artifact.sha256 for artifact in manifest.artifacts},
        "runtime_pack_family_id": family.role.runtime_pack_family_id,
        "runtime_profile_sha256": family.runtime_profile_sha256,
        "output_schema_id": manifest.output_schema_id,
    }
    actual = {
        "capability_id": record.capability_id,
        "model_pack_id": record.model_pack_id,
        "model_id": record.model_id,
        "model_manifest_sha256": record.model_manifest_sha256,
        "artifact_sha256": dict(record.artifact_sha256),
        "runtime_pack_family_id": record.runtime_pack_family_id,
        "runtime_profile_sha256": record.runtime_profile_sha256,
        "output_schema_id": record.output_schema_id,
    }
    if actual["model_pack_id"] != expected["model_pack_id"]:
        raise _fail("model_pack_id_mismatch")
    if actual != expected:
        raise _fail("qualification_identity_mismatch")
    # An unverified manifest never claims a record; a verified one names exactly its own.
    if manifest.verification_status == "unverified":
        if manifest.qualification_id is not None:
            raise _fail("unverified_manifest_claims_qualification")
    elif manifest.qualification_id != record.qualification_id:
        raise _fail("qualification_identity_mismatch")

    # Pipeline policy is reconciled against the live profile, never copied (plan §17).
    if capability_id == DETECTOR_CAPABILITY:
        if record.pipeline_profile_id is None or record.pipeline_profile_sha256 is None:
            raise _fail(f"qualification_policies_required:{capability_id}")
        section = manifest.detector_section()
        validate_profile_against_manifest(
            pipeline_profile,
            model_id=manifest.model_id,
            class_vocabulary=section.class_vocabulary,
        )
    if record.pipeline_profile_id is not None and (
        record.pipeline_profile_id != pipeline_profile.profile_id
        or record.pipeline_profile_sha256 != pipeline_profile_sha256
    ):
        raise _fail("qualification_policy_mismatch")

    return ResolvedCapability(
        capability_id=capability_id,
        binding=binding,
        manifest=manifest,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        model_pack_id=binding.model_pack_id,
        artifact_paths=MappingProxyType(artifact_paths),
        qualification=record,
        qualification_path=record_path,
        qualification_sha256=sha256_release_file(record_path),
    )


# --------------------------------------------------------------------------- environment policy


def _check_environment_policy(
    *,
    capability: ResolvedCapability,
    family: RoleFamily,
    runtime_pack: ResolvedRuntimePack,
    production_mode: bool,
    completion: CompletionContract,
    profile_requirement: DeploymentProfile | None,
    deployment_profile_policy_sha256: str | None,
) -> None:
    """Which qualification status is allowed here (ADR-014 §9, §10; ADR-009).

    Development may run an unverified capability; the provenance label is then
    ``unverified``. Production requires a verified manifest from an installed Runtime
    Pack whose record has passed for the deployment profile's variant. v2 records
    evaluate gates per variant (P-12), so the deployment profile's v1 gate names map
    to "every gate of the variant passed" (``variants[v].status == passed``); no
    weaker, gate-by-gate reading exists.
    """
    if not production_mode:
        return
    if completion.override_active:
        raise _fail("completion_override_forbidden_in_production")
    manifest = capability.manifest
    if manifest.verification_status != "verified":
        raise _fail("unverified_release_forbidden")
    if runtime_pack.runtime_pack_source != INSTALLED_PACK or runtime_pack.runtime_pack_id is None:
        raise _fail("runtime_pack_required")
    variant = runtime_pack.runtime_variant
    accelerator = "cuda" if variant.endswith("-cuda") else "cpu"
    platform_variant = family.runtime_platform_variants.get(variant)
    if platform_variant is None or platform_variant.status != _QUALIFIED_VARIANT_STATUS[accelerator]:
        raise _fail("runtime_profile_variant_not_qualified")
    lock = family.runtime_release_locks.get(variant)
    if lock is None or lock.status != "qualified-offline-lock":
        raise _fail("runtime_profile_lock_not_qualified")
    record = capability.qualification
    if record.overall_result != "passed" or record.variants[variant].status != "passed":
        raise _fail("qualification_variant_not_passed")
    if profile_requirement is None or deployment_profile_policy_sha256 is None:
        raise _fail("qualification_profile_requirement_incomplete")
    if profile_requirement.runtime_variant != variant:
        raise _fail("production_deployment_profile_runtime_variant_mismatch")
    if profile_requirement.profile_id not in record.qualified_profiles:
        raise _fail("qualification_profile_not_qualified")
    if record.profile_runtime_variants.get(profile_requirement.profile_id) != variant:
        raise _fail("qualification_profile_runtime_variant_mismatch")
    if record.profile_policy_sha256.get(profile_requirement.profile_id) != deployment_profile_policy_sha256:
        raise _fail("qualification_profile_policy_mismatch")
    gates = set(record.variants[variant].gates)
    if not gates.issubset(record.profile_evidence_gates.get(profile_requirement.profile_id, frozenset())):
        raise _fail("qualification_profile_evidence_missing")


# --------------------------------------------------------------------------- entry points


@dataclass(frozen=True, slots=True)
class RoleCompositionInputs:
    """Everything the worker settings contribute to composition."""

    component_binding_path: Path
    role_id: str
    overlay_root: Path
    model_root: Path
    pipeline_profile_path: Path
    runtime_pack_manifest_path: Path | None
    production_mode: bool


class RoleComposition:
    """The binding, loaded once, and the role resolved against an observed variant."""

    def __init__(
        self,
        inputs: RoleCompositionInputs,
        *,
        completion: CompletionContract,
        binding: ComponentBindingV2 | None = None,
    ) -> None:
        self._inputs = inputs
        self._completion = completion
        # The bytes hashed into componentBindingSha256 are the bytes resolved (P-11).
        self._binding = binding if binding is not None else load_component_binding(inputs.component_binding_path)
        self._family: RoleFamily | None = None

    @property
    def binding(self) -> ComponentBindingV2:
        return self._binding

    @property
    def completion(self) -> CompletionContract:
        return self._completion

    def family(self) -> RoleFamily:
        if self._family is None:
            self._family = load_role_family(
                binding=self._binding,
                role_id=self._inputs.role_id,
                overlay_root=self._inputs.overlay_root,
            )
        return self._family

    def resolve(
        self,
        *,
        runtime_variant: str,
        python_version: str,
        profile_requirement: DeploymentProfile | None = None,
        deployment_profile_policy_sha256: str | None = None,
    ) -> ResolvedRole:
        return resolve_role(
            binding=self._binding,
            binding_path=self._inputs.component_binding_path,
            family=self.family(),
            runtime_variant=runtime_variant,
            python_version=python_version,
            overlay_root=self._inputs.overlay_root,
            model_root=self._inputs.model_root,
            pipeline_profile_path=self._inputs.pipeline_profile_path,
            runtime_pack_manifest_path=self._inputs.runtime_pack_manifest_path,
            production_mode=self._inputs.production_mode,
            completion=self._completion,
            profile_requirement=profile_requirement,
            deployment_profile_policy_sha256=deployment_profile_policy_sha256,
        )


def resolve_role(
    *,
    binding: ComponentBindingV2,
    binding_path: Path,
    family: RoleFamily,
    runtime_variant: str,
    python_version: str,
    overlay_root: Path,
    model_root: Path,
    pipeline_profile_path: Path,
    runtime_pack_manifest_path: Path | None,
    production_mode: bool,
    completion: CompletionContract,
    profile_requirement: DeploymentProfile | None = None,
    deployment_profile_policy_sha256: str | None = None,
) -> ResolvedRole:
    """Resolve one role for the observed variant, or fail closed with a stable code.

    ``resolve_role`` never chooses a device: the caller resolves the device policy
    first and passes the variant it observed (plan §5.1).
    """
    role = family.role
    runtime_pack = _resolve_runtime_pack(
        family=family,
        binding=binding,
        runtime_variant=runtime_variant,
        runtime_pack_manifest_path=runtime_pack_manifest_path,
        python_version=python_version,
    )

    pipeline_profile = load_pipeline_profile(pipeline_profile_path)
    pipeline_profile_sha256 = sha256_release_file(pipeline_profile_path)
    manifests = index_model_manifests(overlay_root / MANIFESTS_RELATIVE)
    records = index_qualification_records(
        overlay_root / QUALIFICATIONS_RELATIVE,
        gate_sets_path=overlay_root / GATE_SETS_RELATIVE,
    )

    capabilities: dict[str, ResolvedCapability] = {}
    bindings = {item.capability_id: item for item in binding.bindings_for_role(role.role_id)}
    # Every capability the role declares is required for READY (P-6).
    for capability_id in role.capability_ids:
        capability_binding = bindings.get(capability_id)
        if capability_binding is None:
            raise _fail(f"capability_binding_missing:{role.role_id}:{capability_id}")
        capability = _resolve_capability(
            binding=capability_binding,
            family=family,
            manifests=manifests,
            records=records,
            model_root=model_root,
            pipeline_profile=pipeline_profile,
            pipeline_profile_sha256=pipeline_profile_sha256,
        )
        check_record_variants(
            record=capability.qualification,
            binding_variants=binding.family_variants(role.runtime_pack_family_id),
            variant_classes=family.variant_classes,
        )
        _check_environment_policy(
            capability=capability,
            family=family,
            runtime_pack=runtime_pack,
            production_mode=production_mode,
            completion=completion,
            profile_requirement=profile_requirement,
            deployment_profile_policy_sha256=deployment_profile_policy_sha256,
        )
        capabilities[capability_id] = capability

    if completion.override_active:
        _LOGGER.warning(
            "completion_schema_override_active: role %s emits completion %s instead of its "
            "provenance contract %s; every completion is non-qualifying (unverified)",
            role.role_id,
            completion.version,
            role.provenance_contract,
        )
    return ResolvedRole(
        role=role,
        binding=binding,
        binding_path=binding_path,
        family=family,
        runtime_pack=runtime_pack,
        capabilities=MappingProxyType(capabilities),
        pipeline_profile=pipeline_profile,
        pipeline_profile_sha256=pipeline_profile_sha256,
        completion=completion,
        production_mode=production_mode,
    )


__all__ = [
    "COMPLETION_OVERRIDE_VERSIONS",
    "DETECTOR_CAPABILITY",
    "INSTALLED_PACK",
    "PROVENANCE_CONTRACT_VERSIONS",
    "UNPACKED_ENVIRONMENT",
    "CompletionContract",
    "DetectorModelView",
    "DetectorSelection",
    "ResolvedCapability",
    "ResolvedRole",
    "ResolvedRuntimePack",
    "RoleComposition",
    "RoleCompositionInputs",
    "RoleFamily",
    "RuntimePackSource",
    "index_model_manifests",
    "index_qualification_records",
    "load_role_family",
    "resolve_completion_contract",
    "resolve_role",
]
