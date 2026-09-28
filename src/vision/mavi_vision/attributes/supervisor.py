"""Startup and readiness of the ``attributes`` role (S2b plan §14; ADR-014 §1–§11).

Composition is the vision role's: settings -> Component Binding v2 -> the ``attributes`` role
-> its provenance contract -> ``RoleComposition.resolve`` for the observed variant, with the
same Runtime Pack, Model Pack, qualification and environment-policy checks. The supervisor is
READY only when all of that and the inferencer the profile names succeed; otherwise it is
UNAVAILABLE with a stable reason, and an UNAVAILABLE worker never leases, so it can never
consume an attempt it cannot serve.
"""

from __future__ import annotations

import logging
import platform
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from mavi_vision.attributes.inference import AttributeInferencer, inferencer_for
from mavi_vision.attributes.pipeline import AttributeIdentity, AttributePipelineProfile
from mavi_vision.attributes.settings import AttributeWorkerSettings
from mavi_vision.runtime.binding import load_component_binding
from mavi_vision.runtime.deployment_profiles import select_profile
from mavi_vision.runtime.resolver import (
    ATTRIBUTE_CONTROL_VERSION,
    INSTALLED_PACK,
    AttributeSelection,
    RoleComposition,
    RoleCompositionInputs,
    resolve_completion_contract,
)

_LOGGER = logging.getLogger(__name__)


class AttributeRuntimeState(StrEnum):
    STARTING = "starting"
    READY = "ready"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class AttributeRuntime:
    selection: AttributeSelection
    inferencer: AttributeInferencer
    provenance: Mapping[str, object]

    @property
    def identity(self) -> AttributeIdentity:
        return self.selection.identity

    @property
    def profile(self) -> AttributePipelineProfile:
        return self.selection.profile


def attribute_composition(settings: AttributeWorkerSettings) -> RoleComposition:
    binding = load_component_binding(settings.component_binding_path)
    completion = resolve_completion_contract(
        binding.role(settings.role_id),
        override=None,
        production_mode=settings.production_mode,
        emittable_versions=(ATTRIBUTE_CONTROL_VERSION,),
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


def build_provenance(selection: AttributeSelection, settings: AttributeWorkerSettings, device: str) -> dict[str, object]:
    """``visual-attribute-complete-v1`` provenance: the producing components, truthfully.

    A capability is ``verified`` only when its Model Pack manifest is verified and it runs from
    an installed Runtime Pack (ADR-014 §8); an unpacked environment is never verified.
    """
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


class AttributeSupervisor:
    def __init__(self, settings: AttributeWorkerSettings, composition: RoleComposition) -> None:
        self._settings = settings
        self._composition = composition
        self._state = AttributeRuntimeState.STARTING
        self._reason: str | None = None
        self._runtime: AttributeRuntime | None = None

    @property
    def state(self) -> AttributeRuntimeState:
        return self._state

    @property
    def unavailable_reason(self) -> str | None:
        return self._reason

    @property
    def runtime(self) -> AttributeRuntime:
        if self._runtime is None:
            raise RuntimeError("attribute_runtime_not_ready")
        return self._runtime

    def start(self) -> None:
        settings = self._settings
        try:
            profile_requirement = None
            policy_sha256 = None
            if settings.production_mode:
                if settings.deployment_profile is None:
                    raise ValueError("production_deployment_profile_required")
                profile_requirement, policy_sha256 = select_profile(
                    settings.deployment_profile, settings.deployment_profile_policy_path
                )
            # The S2b inferencer runs on CPU only; a CUDA device is refused rather than
            # silently substituted, and Auto resolves to the CPU it can serve.
            if settings.device_policy == "cuda":
                raise ValueError("attribute_device_unsupported:cuda")
            device = "cpu"
            variant = f"{'windows' if platform.system() == 'Windows' else 'linux'}-x86_64-cpu"
            resolved = self._composition.resolve(
                runtime_variant=variant,
                python_version=platform.python_version(),
                profile_requirement=profile_requirement,
                deployment_profile_policy_sha256=policy_sha256,
            )
            selection = resolved.attribute_selection()
            inferencer = inferencer_for(selection.profile.parameters, development_only=selection.profile.development_only)
            provenance = build_provenance(selection, settings, device)
        except ValueError as exc:
            # ReleaseMetadataError is a ValueError whose message is the stable code.
            self._reason = str(exc).split("\n", 1)[0][:128] or "attribute_startup_failed"
            self._state = AttributeRuntimeState.UNAVAILABLE
            _LOGGER.error("MAVI attributes runtime UNAVAILABLE: %s", self._reason)
            return
        self._runtime = AttributeRuntime(selection, inferencer, provenance)
        self._state = AttributeRuntimeState.READY
        _LOGGER.info(
            "MAVI attributes runtime READY: identity %s (%s)",
            selection.identity.fingerprint,
            ", ".join(f"{item.capability_id}={item.model_pack_id}" for item in selection.identity.capabilities),
        )


__all__ = [
    "AttributeRuntime",
    "AttributeRuntimeState",
    "AttributeSupervisor",
    "attribute_composition",
    "build_provenance",
]
