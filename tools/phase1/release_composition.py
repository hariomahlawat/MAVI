"""Component Binding v2 composition for the Phase-1 acceptance tools (S2a.3).

One place where the Phase-1 tools compose the vision role, so every read-only
check goes through the worker's own composition root
(``mavi_vision.runtime.resolver``) rather than a second reader (plan §5), and
every worker environment a tool builds carries exactly the v2 composition
variables (plan P-9) and none of the retired ones.

Identities are only ever read from the resolver: nothing here derives, copies
or invents a ``modelPackId`` or ``runtimePackId``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[2]
VISION_ROOT = ROOT / "src" / "vision"
VISION_TOOLS = ROOT / "tools" / "vision"
for _candidate in (VISION_ROOT, VISION_TOOLS):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

import build_offline_bundle  # noqa: E402
from mavi_vision.common.settings import RETIRED_COMPOSITION_ENVIRONMENT  # noqa: E402
from mavi_vision.runtime.binding import load_component_binding  # noqa: E402
from mavi_vision.runtime.deployment_profiles import DeploymentProfile  # noqa: E402
from mavi_vision.runtime.manifest import ReleaseMetadataError  # noqa: E402
from mavi_vision.runtime.resolver import (  # noqa: E402
    ResolvedRole,
    RoleComposition,
    RoleCompositionInputs,
    resolve_completion_contract,
)

ROLE_ID = build_offline_bundle.ROLE_ID
CANONICAL_COMPONENT_BINDING = build_offline_bundle.CANONICAL_COMPONENT_BINDING
CANONICAL_PIPELINE_PROFILE = build_offline_bundle.CANONICAL_PIPELINE_PROFILE
# The completion schema the worker emits after the cut-over (P-16): 3.3 since Stage 3 (ADR-016).
EMITTED_COMPLETION_VERSIONS = ("3.3",)

# Never inherited into a worker a tool launches: the retired v1 composition
# variables (the worker refuses to start on any of them), the Development-only
# completion override (a qualification run is never non-qualifying by
# accident) and an installed Runtime Pack manifest (a bundle-built environment
# is not an installed Runtime Pack, P-8; a stray inherited path would make the
# worker claim a pack the tool never checked).
SCRUBBED_WORKER_ENVIRONMENT = (
    *RETIRED_COMPOSITION_ENVIRONMENT,
    "MAVI_COMPLETION_SCHEMA_OVERRIDE",
    "MAVI_RUNTIME_PACK_MANIFEST_PATH",
)


def without_scrubbed_composition(environ: Mapping[str, str]) -> dict[str, str]:
    """A copy of ``environ`` without any scrubbed variable (case-insensitive, as the worker reads)."""
    scrubbed = {name.upper() for name in SCRUBBED_WORKER_ENVIRONMENT}
    return {name: value for name, value in environ.items() if name.upper() not in scrubbed}


def bundle_worker_composition(bundle_dir: Path) -> dict[str, str]:
    """The v2 composition variables for a worker run from an offline bundle's ``release/`` overlay."""
    return {
        "MAVI_COMPONENT_BINDING_PATH": str((bundle_dir / build_offline_bundle.BUNDLED_BINDING).resolve()),
        "MAVI_ROLE_ID": ROLE_ID,
        "MAVI_OVERLAY_ROOT": str((bundle_dir / build_offline_bundle.RELEASE_ROOT).resolve()),
        "MAVI_MODEL_ROOT": str((bundle_dir / build_offline_bundle.BUNDLED_MODEL_ROOT).resolve()),
        "MAVI_PIPELINE_PROFILE_PATH": str(
            (bundle_dir / build_offline_bundle.BUNDLED_PIPELINE_PROFILE).resolve()
        ),
    }


def bundle_deployment_policy(bundle_dir: Path) -> Path:
    return bundle_dir / build_offline_bundle.BUNDLED_DEPLOYMENT_POLICY


def bundle_e2e_arguments(bundle_dir: Path) -> list[str]:
    """``phase1_e2e_check.py`` composition arguments for a bundle's ``release/`` overlay."""
    return [
        "--component-binding", str(bundle_dir / build_offline_bundle.BUNDLED_BINDING),
        "--overlay-root", str(bundle_dir / build_offline_bundle.RELEASE_ROOT),
        "--model-root", str(bundle_dir / build_offline_bundle.BUNDLED_MODEL_ROOT),
        "--pipeline-profile", str(bundle_dir / build_offline_bundle.BUNDLED_PIPELINE_PROFILE),
        "--bundle-dir", str(bundle_dir),
    ]


def resolve_vision_role(
    *,
    component_binding_path: Path,
    overlay_root: Path,
    model_root: Path,
    pipeline_profile_path: Path,
    runtime_variant: str,
    production_mode: bool = False,
    runtime_pack_manifest_path: Path | None = None,
    profile_requirement: DeploymentProfile | None = None,
    deployment_profile_policy_sha256: str | None = None,
) -> ResolvedRole:
    """Resolve the vision role exactly as the worker would, or raise ``ReleaseMetadataError``.

    ``production_mode=False`` is the v2 mapping of the retired
    ``allow_unverified=True``: an unverified capability resolves and is labelled
    ``unverified``. ``production_mode=True`` applies the resolver's own
    environment policy (verified manifest, installed Runtime Pack, the deployment
    profile's variant passed with every gate passed; P-12). The Python version
    compared against an installed Runtime Pack is the family profile's declared
    identity for the variant, never a guessed one.
    """
    binding = load_component_binding(component_binding_path)
    completion = resolve_completion_contract(
        binding.role(ROLE_ID),
        override=None,
        production_mode=production_mode,
        emittable_versions=EMITTED_COMPLETION_VERSIONS,
    )
    composition = RoleComposition(
        RoleCompositionInputs(
            component_binding_path=component_binding_path,
            role_id=ROLE_ID,
            overlay_root=overlay_root,
            model_root=model_root,
            pipeline_profile_path=pipeline_profile_path,
            runtime_pack_manifest_path=runtime_pack_manifest_path,
            production_mode=production_mode,
        ),
        completion=completion,
        binding=binding,
    )
    family = composition.family()
    if runtime_variant not in binding.family_variants(family.role.runtime_pack_family_id):
        raise ReleaseMetadataError(f"runtime_variant_not_declared:{runtime_variant}")
    platform = family.runtime_platform_variants.get(runtime_variant)
    if platform is None or platform.python_identity is None:
        raise ReleaseMetadataError(f"runtime_platform_identity_missing:{runtime_variant}")
    return composition.resolve(
        runtime_variant=runtime_variant,
        python_version=platform.python_identity.version,
        profile_requirement=profile_requirement,
        deployment_profile_policy_sha256=deployment_profile_policy_sha256,
        # A tool assesses an installed pack on disk, not its own interpreter: it
        # names the pack's own environment (<installRoot>/venv) explicitly.
        interpreter_prefix=(
            None if runtime_pack_manifest_path is None else runtime_pack_manifest_path.parent / "venv"
        ),
    )


def resolve_staged_bundle(bundle_dir: Path, manifest: Mapping[str, object]) -> ResolvedRole:
    """Resolve the vision role from a bundle's ``release/`` overlay, as the bundle verifier does."""
    platform_variant = manifest.get("platformVariant")
    release_status = manifest.get("releaseStatus")
    policy_sha = manifest.get("deploymentProfilePolicySha256")
    profile_id = manifest.get("deploymentProfile")
    if not isinstance(platform_variant, str) or not isinstance(release_status, str) or not isinstance(policy_sha, str):
        raise build_offline_bundle.OfflineBundleError("bundle_manifest_invalid")
    if profile_id is not None and not isinstance(profile_id, str):
        raise build_offline_bundle.OfflineBundleError("bundle_deployment_profile_variant_mismatch")
    return build_offline_bundle._resolve_staged_bundle(
        bundle_dir,
        release_status=release_status,
        platform_variant=platform_variant,
        deployment_profile_id=profile_id,
        expected_policy_sha256=policy_sha,
    )


__all__ = [
    "CANONICAL_COMPONENT_BINDING",
    "CANONICAL_PIPELINE_PROFILE",
    "EMITTED_COMPLETION_VERSIONS",
    "ROLE_ID",
    "SCRUBBED_WORKER_ENVIRONMENT",
    "bundle_deployment_policy",
    "bundle_e2e_arguments",
    "bundle_worker_composition",
    "resolve_staged_bundle",
    "resolve_vision_role",
    "without_scrubbed_composition",
]
