"""The closed vocabulary of Windows launcher fail-closed failures.

`Start-MaviVisionWorker.ps1` refuses to start the worker whenever the installed
Runtime Pack, Model Pack or application overlay is not the qualified one. Those
refusals are the operator-facing surface of every explicit-`CUDA` failure --
explicit CUDA never falls back, so a refusal is the whole outcome -- and until
now each one was a sentence of English with nothing stable to key on.

That made them unclassifiable. C7 records each failure case with a stable code;
an operator runbook wants to index by one; support wants to compare two hosts.
Prose cannot do any of it, and prose is also what changes when someone rewords
a message.

So the launcher now emits `mavi_launch_failed:<code>: <message>` and this module
is the authoritative set of codes it may use. The message stays, because a code
alone does not tell an operator which file to look at.

This is a mirror-checked contract, like the device-resolution reasons: a test
scrapes the launcher and requires the two to agree exactly, so a code cannot be
added on one side alone.

These are launcher-stage codes. They are not worker failure codes and never
reach the control plane; the worker is not running when they are raised.
"""

from __future__ import annotations

LAUNCH_FAILURE_PREFIX = "mavi_launch_failed"

#: Refusals raised before the worker process starts. Closed, and mirrored by
#: ``tools/setup/Start-MaviVisionWorker.ps1``.
LAUNCH_FAILURE_CODES = frozenset(
    {
        # Repository identity.
        "launch_git_unavailable",
        "launch_repository_head_unknown",
        # Runtime Pack installation and identity.
        "launch_runtime_pack_not_installed",
        "launch_runtime_state_schema_unsupported",
        "launch_runtime_manifest_fingerprint_mismatch",
        "launch_runtime_interpreter_missing",
        "launch_runtime_python_identity_unverifiable",
        "launch_runtime_python_identity_malformed",
        "launch_runtime_python_identity_state_mismatch",
        "launch_runtime_python_identity_manifest_mismatch",
        # Model Pack installation and identity.
        "launch_model_pack_not_installed",
        "launch_model_state_schema_unsupported",
        "launch_model_manifest_fingerprint_mismatch",
        # Application overlay and its bindings to qualification metadata.
        "launch_overlay_file_missing",
        "launch_component_schema_unsupported",
        "launch_component_runtime_profile_mismatch",
        "launch_component_pack_requirement_missing",
        "launch_model_manifest_qualification_mismatch",
        "launch_pipeline_qualification_mismatch",
        "launch_runtime_profile_qualification_mismatch",
        "launch_runtime_lock_binding_stale",
        "launch_runtime_requirements_binding_stale",
        "launch_runtime_native_abi_binding_stale",
        "launch_model_pack_binding_stale",
        # The resolved policy and the installed pack must be the same thing.
        # These two are where explicit CUDA fails closed rather than running on
        # a pack that is not the CUDA one.
        "launch_cuda_policy_requires_cuda_pack",
        "launch_cpu_policy_requires_cpu_pack",
        # Development source overlay.
        "launch_vision_source_tree_missing",
        "launch_vision_source_overlay_unverifiable",
        "launch_vision_source_overlay_foreign",
    }
)


__all__ = ["LAUNCH_FAILURE_CODES", "LAUNCH_FAILURE_PREFIX"]
