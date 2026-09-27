"""Worker composition from settings: the component binding is the only source.

Every entry point that starts the detector runtime (the worker, the real-clip
measurement tool, the fixture harness) composes through this one function, so they
cannot drift: settings -> binding -> role -> completion contract (P-16) -> the
``RoleComposition`` the supervisor resolves for the observed variant.
"""

from __future__ import annotations

from mavi_vision.common.settings import WorkerSettings, reject_v1_composition_environment
from mavi_vision.runtime.resolver import (
    RoleComposition,
    RoleCompositionInputs,
    resolve_completion_contract,
)
from mavi_vision.runtime.binding import load_component_binding
from mavi_vision.worker.client import SUPPORTED_COMPLETION_SCHEMA_VERSIONS


def role_composition_from_settings(settings: WorkerSettings) -> RoleComposition:
    """Load the binding once and fix the role's completion contract before any lease."""
    reject_v1_composition_environment()
    binding = load_component_binding(settings.component_binding_path)
    completion = resolve_completion_contract(
        binding.role(settings.role_id),
        override=settings.completion_schema_override,
        production_mode=settings.production_mode,
        emittable_versions=SUPPORTED_COMPLETION_SCHEMA_VERSIONS,
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


__all__ = ["role_composition_from_settings"]
