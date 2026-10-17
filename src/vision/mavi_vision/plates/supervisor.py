"""Startup and readiness of the ``plates`` role (Stage 4 plan §2.1, §2.4; ADR-014 §1–§11).

Composition is every role's: settings -> Component Binding v2 -> the ``plates`` role -> its provenance
contract -> ``RoleComposition.resolve`` for the observed variant, with the same Runtime Pack, Model Pack,
qualification and environment-policy checks. The supervisor is READY only when all of that and the
detector and recogniser the profile names succeed; otherwise it is UNAVAILABLE with a stable reason, and
an UNAVAILABLE worker never leases, so it can never consume an attempt it cannot serve.
"""

from __future__ import annotations

import logging
import platform
from importlib import metadata
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from mavi_vision.plates.adapters import (
    DETECTOR_CAPABILITY,
    OCR_CAPABILITY,
    AdapterRequest,
    AdapterUnavailable,
    components_for,
)
from mavi_vision.plates.inference import PlateDetector, PlateRecogniser
from mavi_vision.plates.profile import PlateIdentity, PlatePipelineProfile
from mavi_vision.plates.settings import PlateWorkerSettings
from mavi_vision.runtime.binding import load_component_binding
from mavi_vision.runtime.deployment_profiles import select_profile
from mavi_vision.runtime.manifest import ReleaseMetadataError
from mavi_vision.runtime.resolver import (
    INSTALLED_PACK,
    PLATE_CONTROL_VERSION,
    PlateSelection,
    RoleComposition,
    RoleCompositionInputs,
    resolve_completion_contract,
)

_LOGGER = logging.getLogger(__name__)


class PlateRuntimeState(StrEnum):
    STARTING = "starting"
    READY = "ready"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class PlateRuntime:
    selection: PlateSelection
    detector: PlateDetector
    recogniser: PlateRecogniser
    provenance: Mapping[str, object]

    @property
    def identity(self) -> PlateIdentity:
        return self.selection.identity

    @property
    def profile(self) -> PlatePipelineProfile:
        return self.selection.profile


def plate_composition(settings: PlateWorkerSettings) -> RoleComposition:
    binding = load_component_binding(settings.component_binding_path)
    completion = resolve_completion_contract(
        binding.role(settings.role_id),
        override=None,
        production_mode=settings.production_mode,
        emittable_versions=(PLATE_CONTROL_VERSION,),
    )
    return RoleComposition(
        RoleCompositionInputs(
            component_binding_path=settings.component_binding_path,
            role_id=settings.role_id,
            overlay_root=settings.overlay_root,
            model_root=settings.model_root,
            pipeline_profile_path=settings.pipeline_profile_path,
            runtime_pack_manifest_path=settings.runtime_pack_manifest_path,
            production_mode=settings.production_mode,
        ),
        completion=completion,
        binding=binding,
    )


def build_provenance(selection: PlateSelection, settings: PlateWorkerSettings, device: str) -> dict[str, object]:
    """``plate-complete-v1`` provenance: the producing components, truthfully (ADR-014 §8)."""
    role = selection.resolved_role
    runtime_pack = role.runtime_pack
    installed = runtime_pack.runtime_pack_source == INSTALLED_PACK
    capabilities = [
        {
            "capabilityId": capability_id,
            "modelPackId": item.model_pack_id,
            "modelManifestSha256": item.manifest_sha256,
            "qualificationId": item.qualification.qualification_id,
            "qualificationSha256": item.qualification_sha256,
            "verificationStatus": "verified" if installed and item.manifest.verification_status == "verified" else "unverified",
        }
        for capability_id, item in sorted(role.capabilities.items())
    ]
    return {
        "provenanceContract": role.role.provenance_contract,
        "roleId": role.role.role_id,
        "capabilities": capabilities,
        "runtimePackFamilyId": runtime_pack.runtime_pack_family_id,
        "runtimeProfileSha256": role.family.runtime_profile_sha256,
        "runtimeVariant": runtime_pack.runtime_variant,
        "runtimePackId": runtime_pack.runtime_pack_id,
        "runtimePackSource": runtime_pack.runtime_pack_source,
        "componentBindingSha256": role.component_binding_sha256,
        "pipelineProfileSha256": role.pipeline_profile_sha256,
        "configuredDevicePolicy": settings.device_policy,
        "actualDevice": device,
        "maviBuild": settings.build_id,
        "maviCommit": settings.commit_sha,
    }


def adapter_request(selection: PlateSelection, capability_id: str) -> AdapterRequest:
    """The adapter one capability's **own** Model Pack names (``capabilitySpecific.<capabilityId>.adapterId``).

    Its artefact paths are the ones the resolver already hash-verified, by the adapter's slot names. The profile's
    ``fixtureSeed`` never selects an adapter (Issue #225); it only parameterises the fixture the packs name.
    """
    capability = selection.resolved_role.capabilities.get(capability_id)
    if capability is None:
        raise AdapterUnavailable(f"capability_binding_missing:{capability_id}")
    try:
        section = capability.manifest.plate_adapter_section(capability_id)
    except ReleaseMetadataError as exc:
        raise AdapterUnavailable(str(exc)) from exc
    artifacts = {slot: capability.artifact_paths[artifact.artifact_role] for slot, artifact in section.artifacts.items()}
    return AdapterRequest(capability_id=capability_id, adapter_id=section.adapter_id, artifacts=artifacts)


def check_development_environment(selection: PlateSelection, *, python_version: str | None = None,
                                  installed: Mapping[str, str] | None = None) -> None:
    """A Development-only runtime graph (``plates-onnx-v1``) runs only in the environment its lock describes.

    There is no installed Runtime Pack for it (``runtimePackSource`` is ``unpacked-environment``), so the running
    interpreter's version and every semantic-graph distribution are compared with the family profile instead:
    a mismatch is refused, never run under the family's identity.
    """
    role = selection.resolved_role
    profile = role.family.runtime_profile
    graph = profile.graph
    if not graph.development_only:
        return
    identity = role.family.runtime_platform_variants[role.runtime_variant].python_identity
    if identity is None or (python_version or platform.python_version()) != identity.version:
        raise ValueError("plate_runtime_python_mismatch")
    members = profile.semantic_graph.model_dump(by_alias=True)
    for member, distribution in graph.distributions.items():
        if distribution is None:
            continue
        try:
            version = installed[distribution] if installed is not None else metadata.version(distribution)
        except (KeyError, metadata.PackageNotFoundError):
            raise ValueError(f"plate_runtime_environment_mismatch:{distribution}") from None
        if version != members[member]:
            raise ValueError(f"plate_runtime_environment_mismatch:{distribution}")


class PlateSupervisor:
    def __init__(self, settings: PlateWorkerSettings, composition: RoleComposition) -> None:
        self._settings = settings
        self._composition = composition
        self._state = PlateRuntimeState.STARTING
        self._reason: str | None = None
        self._runtime: PlateRuntime | None = None

    @property
    def state(self) -> PlateRuntimeState:
        return self._state

    @property
    def unavailable_reason(self) -> str | None:
        return self._reason

    @property
    def runtime(self) -> PlateRuntime:
        if self._runtime is None:
            raise RuntimeError("plate_runtime_not_ready")
        return self._runtime

    def start(self) -> None:
        settings = self._settings
        try:
            profile_requirement = None
            policy_sha256 = None
            if settings.production_mode:
                if settings.deployment_profile is None:
                    raise ValueError("production_deployment_profile_required")
                profile_requirement, policy_sha256 = select_profile(settings.deployment_profile, settings.deployment_profile_policy_path)
            # The fixture and the Development ONNX adapters run on CPU only; a CUDA device is refused, never
            # silently substituted (ADR-008).
            if settings.device_policy == "cuda":
                raise ValueError("plate_device_unsupported:cuda")
            device = "cpu"
            variant = f"{'windows' if platform.system() == 'Windows' else 'linux'}-x86_64-cpu"
            resolved = self._composition.resolve(
                runtime_variant=variant,
                python_version=platform.python_version(),
                profile_requirement=profile_requirement,
                deployment_profile_policy_sha256=policy_sha256,
            )
            selection = resolved.plate_selection()
            check_development_environment(selection)
            detector, recogniser = components_for(
                adapter_request(selection, DETECTOR_CAPABILITY),
                adapter_request(selection, OCR_CAPABILITY),
                parameters=selection.profile.parameters,
                development_only=selection.profile.development_only,
                production_mode=settings.production_mode,
            )
            provenance = build_provenance(selection, settings, device)
        except ValueError as exc:
            # ReleaseMetadataError and AdapterUnavailable are ValueErrors whose message is the stable code.
            self._reason = str(exc).split("\n", 1)[0][:128] or "plate_startup_failed"
            self._state = PlateRuntimeState.UNAVAILABLE
            _LOGGER.error("MAVI plates runtime UNAVAILABLE: %s", self._reason)
            return
        self._runtime = PlateRuntime(selection, detector, recogniser, provenance)
        self._state = PlateRuntimeState.READY
        _LOGGER.info("MAVI plates runtime READY: identity %s (%s)", selection.identity.fingerprint,
                     ", ".join(f"{item.capability_id}={item.model_pack_id}" for item in selection.identity.capabilities))


__all__ = ["PlateRuntime", "PlateRuntimeState", "PlateSupervisor", "adapter_request", "build_provenance", "check_development_environment", "plate_composition"]
