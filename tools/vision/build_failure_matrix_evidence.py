#!/usr/bin/env python3
"""Assemble the C7 failure-matrix evidence bundle.

C7's entire output is failures, which makes it the phase most easily reduced to
prose: every case "behaved as expected" and nothing is checkable afterwards.
This tool declares the matrix as data -- one entry per failure the phase must
exercise, each stating the invariant it defends, the stable reason or failure
code expected, whether retry is permitted, and whether fallback is permitted --
and then refuses an observation that does not match its own case.

The distinction the matrix exists to protect is between a *permitted* fallback
and a *silent* one. Development `Auto` may resolve to CPU, but only for one of
the eight reasons the closed vocabulary allows, and the reason must be recorded.
Explicit `CUDA` may never resolve to CPU at all: those cases are fail-closed,
and an observation reporting a device for one of them is the defect, not the
evidence.

The vocabulary is imported from `mavi_vision.common.control_plane`, never
restated here. A failure matrix that carried its own copy of the reason codes
would eventually certify against codes the runtime no longer emits.

Scope is explicit and never implied. A bundle assembled without a GPU is
`linux-observable` and says so; it is evidence that the fail-closed paths behave,
not evidence that any hardware ran. Only a `hardware` bundle may carry the cases
that need a real device, and neither kind is hardware qualification.

It is offline and reads only the files it is given.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

for _candidate in (
    Path(__file__).resolve().parent,
    Path(__file__).resolve().parents[2] / "src" / "vision",
):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from mavi_vision.common.control_plane import (  # noqa: E402
    AUTO_CPU_DEVICE_RESOLUTION_REASONS,
    DEVICE_RESOLUTION_REASONS,
    is_cuda_device,
)
from mavi_vision.runtime.launch_failures import (  # noqa: E402
    LAUNCH_FAILURE_CODES,
)

# Codes raised as inline literals by the worker-side refusal paths. They are not
# importable as a set -- they exist only at their raise sites -- so the honest
# option is to restate the ones this matrix cites and pin them with a test that
# scrapes those sites. A restatement nothing checks would drift.
_OFFLINE_LOCK_CODES = frozenset(
    {
        "offline_lock_unreadable",
        "offline_lock_utf8_invalid",
        "offline_lock_bom_forbidden",
        "offline_lock_cr_forbidden",
        "offline_lock_header_invalid",
        "offline_lock_schema_invalid",
        "offline_lock_hash_invalid",
        "offline_lock_not_sorted",
        "offline_lock_requirement_invalid",
    }
)
_RELEASE_METADATA_CODES = frozenset(
    {
        "qualification_identity_mismatch",
        "qualification_record_invalid",
        "qualification_record_required",
        "runtime_checkpoint_hash_mismatch",
        "runtime_config_hash_mismatch",
        "checkpoint_hash_mismatch",
        "resolved_config_hash_mismatch",
        "runtime_release_lock_hash_mismatch",
        "runtime_profile_id_mismatch",
        "runtime_profile_invalid",
        "runtime_profile_not_qualified",
        "runtime_profile_variant_not_qualified",
        "release_artifact_missing",
    }
)
_GPU_IDENTITY_CODES = frozenset(
    {
        "gpu_identity_uuid_mismatch",
        "gpu_identity_memory_mismatch",
        "gpu_identity_compute_capability_mismatch",
        "gpu_identity_device_order_unstable",
        "gpu_identity_visible_devices_ambiguous",
        "gpu_identity_index_unavailable",
        # The driver inventory probe itself. Explicit CUDA reaches the worker's
        # own identity probe (the launcher probes only for Auto), so these are
        # the codes an explicit-CUDA driver-probe refusal actually surfaces.
        "nvidia_smi_not_found",
        "nvidia_smi_timed_out",
        "gpu_identity_nvidia_smi_failed",
    }
)
_RUNTIME_VERIFICATION_CODES = frozenset(
    {
        "cuda_unavailable",
        "cuda_device_index_invalid",
        "torch_cuda_architecture_missing",
        "mmcv_cuda_op_executed_off_device",
        "torch_cuda_matmul_executed_off_device",
        "cuda_runtime_verification_failed",
    }
)
_WORKER_CODES = frozenset(
    {
        "vision_runtime_incompatible",
        "vision_gpu_out_of_memory",
        "vision_gpu_runtime_failed",
        "vision_inference_watchdog_expired",
    }
)
_PROVENANCE_CODES = frozenset(
    {
        "actual_device_policy_mismatch",
        "device_resolution_reason_unknown",
        "device_resolution_reason_invalid",
        "auto_device_resolution_reason_required",
        "runtime_platform_variant_not_qualified",
        "production_runtime_not_qualified",
        "production_release_not_verified",
        "unverified_release_forbidden",
    }
)

#: Every code any declared case may legitimately cite.
CITABLE_FAILURE_CODES = frozenset(
    LAUNCH_FAILURE_CODES
    | _OFFLINE_LOCK_CODES
    | _RELEASE_METADATA_CODES
    | _GPU_IDENTITY_CODES
    | _RUNTIME_VERIFICATION_CODES
    | _WORKER_CODES
    | _PROVENANCE_CODES
)

SCHEMA_VERSION = "mavi-windows-cuda-failure-matrix-v1"
CASE_SCHEMA_VERSION = "mavi-windows-cuda-failure-case-v1"

SCOPES = ("linux-observable", "windows-host", "hardware")

_SOURCE_HEAD_SHA = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_CANONICAL_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", re.ASCII)
_OPERATOR_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@/-]{0,127}$", re.ASCII)
_FAILURE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$", re.ASCII)
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
# C7 is entirely a phase of failure artefacts, and the natural NVML or driver
# message for a wrong-GPU refusal *is* the card's UUID. The operator is asked to
# paste that message in here, so it is redacted on the way through, exactly as
# the runtime verifier already redacts its own failure detail.
_RAW_GPU_UUID = re.compile(r"GPU-[0-9A-Fa-f][0-9A-Fa-f-]{7,}")


_RECORD_SCHEMA_PATH = Path(__file__).resolve().parent / "windows-cuda-failure-case.schema.json"

# Where the C4 record lives once Gate C4 has passed. A hardware-scope bundle is
# bound to that committed record rather than to a head equality, for the same
# reason C6 is: the C4 patch is committed after capture, so the head carrying
# it can never be the head the evidence names.
_CUDA_VARIANT = "windows-x86_64-cuda"
_DEFAULT_RUNTIME_PROFILE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "vision"
    / "runtime"
    / "mmdetection-phase1-v1"
    / "runtime.json"
)
_EVIDENCE_BLOCK_FIELDS = (
    "hostObservationSha256",
    "evidenceBundleSha256",
    "sourceHeadSha",
    "capturedAtUtc",
    "operatorReference",
)


def _record_schema() -> dict:
    return json.loads(_RECORD_SCHEMA_PATH.read_text(encoding="utf-8"))


class FailureMatrixError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _auto_fallback_case(
    reason: str, invariant: str, *, hardware: bool, windows: bool = True
) -> dict:
    """One permitted Development Auto fallback, named by its stable reason.

    All of these are resolved by the Windows launcher's `Test-CudaRuntimeUsable`
    except the one the worker's own Auto branch produces, so nearly all of them
    need a Windows host even when they need no GPU.
    """
    return {
        "invariant": invariant,
        "stage": "device-resolution",
        "configuredDevicePolicy": "auto",
        "outcome": "auto-fallback-cpu",
        "deviceResolutionReason": reason,
        "fallbackPermitted": True,
        "retryPermitted": False,
        "requiresHardware": hardware,
        "requiresWindowsHost": windows,
        "expectedFailureCodes": None,
    }


def _fail_closed_case(
    invariant: str,
    *,
    stage: str,
    policy: str = "cuda",
    retry: bool = False,
    hardware: bool = False,
    windows: bool = False,
    codes: frozenset[str] | None = None,
) -> dict:
    """One fail-closed refusal.

    `codes` names the stable failure codes that may legitimately report this
    case, where such codes exist. Several refusals still live in PowerShell
    modules that carry no coded vocabulary; those cases declare none rather
    than pretend to a code the system cannot emit.
    """
    if codes is not None and not codes <= CITABLE_FAILURE_CODES:
        raise FailureMatrixError("failure_matrix_declared_code_unknown")
    return {
        "invariant": invariant,
        "stage": stage,
        "configuredDevicePolicy": policy,
        "outcome": "fail-closed",
        "deviceResolutionReason": None,
        "fallbackPermitted": False,
        "retryPermitted": retry,
        "requiresHardware": hardware,
        "requiresWindowsHost": windows,
        "expectedFailureCodes": None if codes is None else sorted(codes),
    }


# The permitted Development Auto fallbacks are exactly the closed vocabulary's
# Auto-CPU reasons: one case each, so a reason the runtime can emit but the
# matrix never exercises cannot exist.
_AUTO_FALLBACK_INVARIANTS = {
    "cuda_pack_absent": "no CUDA Runtime Pack is installed",
    "cuda_pack_not_declared": "the component declares no CUDA Runtime Pack",
    "cuda_pack_integrity_failed": "the installed pack fails its integrity preflight",
    "cuda_pack_variant_mismatch": "the installed pack is for another variant",
    "cuda_pack_id_mismatch": "the installed pack is not the declared identity",
    "cuda_driver_probe_unavailable": "the NVIDIA driver cannot be probed",
    "cuda_device_unavailable": "the configured device is not present",
    "cuda_driver_probe_failed": "the driver probe itself failed",
}

# Three reasons come from the worker's own Auto branch (supervisor.py), so they
# are observable without a Windows launcher; all three are already exercised on
# Linux with no GPU by test_runtime_supervisor.py. The other five come from
# `Test-CudaRuntimeUsable` and need the host.
_WORKER_RESOLVED_FALLBACKS = frozenset(
    {
        "cuda_pack_not_declared",
        "cuda_device_unavailable",
        "cuda_driver_probe_failed",
    }
)

FAILURE_CASES: dict[str, dict] = {
    f"auto-{reason.removeprefix('cuda_').replace('_', '-')}": _auto_fallback_case(
        reason,
        invariant,
        hardware=False,
        windows=reason not in _WORKER_RESOLVED_FALLBACKS,
    )
    for reason, invariant in _AUTO_FALLBACK_INVARIANTS.items()
}

FAILURE_CASES.update(
    {
        # Explicit CUDA is fail-closed in every one of these. None may resolve
        # to a device, and none may fall back.
        "explicit-cuda-pack-absent": _fail_closed_case(
            "explicit CUDA refuses to start without its Runtime Pack",
            stage="device-resolution",
            windows=True,
            codes=frozenset({"launch_runtime_pack_not_installed"}),
        ),
        "explicit-cuda-pack-integrity-failed": _fail_closed_case(
            "explicit CUDA refuses a pack that fails integrity",
            stage="device-resolution",
            windows=True,
            codes=frozenset({"launch_runtime_manifest_fingerprint_mismatch"}),
        ),
        "explicit-cuda-pack-identity-mismatch": _fail_closed_case(
            "explicit CUDA refuses a pack that is not the declared identity",
            stage="device-resolution",
            windows=True,
            codes=frozenset(
                {
                    "launch_component_pack_requirement_missing",
                    "launch_runtime_native_abi_binding_stale",
                    "launch_cuda_policy_requires_cuda_pack",
                }
            ),
        ),
        "explicit-cuda-device-unavailable": _fail_closed_case(
            "explicit CUDA refuses when no CUDA device is present",
            stage="startup",
            hardware=True,
            codes=frozenset({"cuda_unavailable", "vision_gpu_runtime_failed"}),
        ),
        "explicit-cuda-invalid-device-index": _fail_closed_case(
            "explicit CUDA refuses a device index the host does not have",
            stage="startup",
            hardware=True,
            codes=frozenset(
                {"cuda_device_index_invalid", "gpu_identity_index_unavailable"}
            ),
        ),
        "explicit-cuda-driver-insufficient": _fail_closed_case(
            "explicit CUDA refuses a driver older than the packed CUDA family",
            stage="startup",
            hardware=True,
            codes=frozenset(
                {"cuda_unavailable", "vision_gpu_runtime_failed"}
            ),
        ),
        "explicit-cuda-wrong-architecture": _fail_closed_case(
            "explicit CUDA refuses a device the pack has no kernels for",
            stage="startup",
            hardware=True,
            codes=frozenset(
                {
                    "torch_cuda_architecture_missing",
                    "gpu_identity_compute_capability_mismatch",
                }
            ),
        ),
        "explicit-cuda-wrong-physical-gpu": _fail_closed_case(
            "the attested physical GPU must be the one that ran the work",
            stage="startup",
            hardware=True,
            codes=frozenset(
                {
                    "gpu_identity_uuid_mismatch",
                    "gpu_identity_memory_mismatch",
                    "gpu_identity_device_order_unstable",
                    "gpu_identity_visible_devices_ambiguous",
                }
            ),
        ),
        "explicit-cuda-native-extension-import-failed": _fail_closed_case(
            "a native extension that cannot import fails closed, never to CPU",
            stage="startup",
            windows=True,
            codes=frozenset({"vision_runtime_incompatible"}),
        ),
        "explicit-cuda-mmcv-ops-failed": _fail_closed_case(
            "mmcv.ops failing on device fails closed, never to CPU",
            stage="startup",
            hardware=True,
            codes=frozenset(
                {"mmcv_cuda_op_executed_off_device", "vision_runtime_incompatible"}
            ),
        ),
        "explicit-cuda-torch-cuda-mismatch": _fail_closed_case(
            "a Torch CUDA runtime other than the qualified one fails closed",
            stage="startup",
            windows=True,
            codes=frozenset({"vision_runtime_incompatible"}),
        ),
        "explicit-cuda-torchvision-binary-mismatch": _fail_closed_case(
            "a torchvision build other than the qualified one fails closed",
            stage="startup",
            windows=True,
            codes=frozenset({"vision_runtime_incompatible"}),
        ),
        "explicit-cuda-python-abi-mismatch": _fail_closed_case(
            "a Python ABI other than the qualified one fails closed",
            stage="startup",
            windows=True,
            codes=frozenset(
                {
                    "launch_runtime_python_identity_state_mismatch",
                    "launch_runtime_python_identity_manifest_mismatch",
                }
            ),
        ),
        # The forbidden transition itself. This case exists so the matrix
        # records that the system refuses it, not that it was observed working.
        "explicit-cuda-resolved-to-cpu-refused": _fail_closed_case(
            "explicit CUDA may never silently resolve to CPU",
            stage="device-resolution",
            windows=True,
            codes=frozenset({"launch_cuda_policy_requires_cuda_pack"}),
        ),
        "auto-unknown-reason-refused": _fail_closed_case(
            "a device-resolution reason outside the closed vocabulary is refused",
            stage="device-resolution",
            policy="auto",
            codes=frozenset(
                {
                    "device_resolution_reason_unknown",
                    "device_resolution_reason_invalid",
                    "auto_device_resolution_reason_required",
                }
            ),
        ),
        # The four remaining Auto-CPU conditions, mirrored under explicit CUDA.
        # Auto is permitted to answer CPU for each of these; explicit CUDA is
        # not, and these are the highest-risk places for a silent fallback
        # precisely because a legitimate CPU answer exists next door.
        "explicit-cuda-pack-not-declared": _fail_closed_case(
            "explicit CUDA refuses when no CUDA pack is declared",
            stage="device-resolution",
            windows=True,
            codes=frozenset({"launch_component_pack_requirement_missing"}),
        ),
        "explicit-cuda-pack-variant-mismatch": _fail_closed_case(
            "explicit CUDA refuses a pack built for another variant",
            stage="device-resolution",
            windows=True,
            codes=frozenset({"launch_cuda_policy_requires_cuda_pack"}),
        ),
        "explicit-cuda-driver-probe-unavailable": _fail_closed_case(
            "explicit CUDA refuses when the driver cannot be probed",
            stage="startup",
            hardware=True,
            windows=True,
            codes=frozenset(
                {
                    "cuda_unavailable",
                    "vision_gpu_runtime_failed",
                    "nvidia_smi_not_found",
                    "nvidia_smi_timed_out",
                }
            ),
        ),
        "explicit-cuda-driver-probe-failed": _fail_closed_case(
            "explicit CUDA refuses when the driver probe itself fails",
            stage="startup",
            hardware=True,
            windows=True,
            codes=frozenset(
                {
                    "cuda_unavailable",
                    "vision_gpu_runtime_failed",
                    "gpu_identity_nvidia_smi_failed",
                    "nvidia_smi_timed_out",
                }
            ),
        ),
        # Evidence and identity integrity.
        "stale-qualification-evidence": _fail_closed_case(
            "qualification evidence for another source revision is refused",
            stage="release-selection",
            windows=True,
            codes=frozenset(
                {
                    "launch_model_manifest_qualification_mismatch",
                    "launch_pipeline_qualification_mismatch",
                    "launch_runtime_profile_qualification_mismatch",
                }
            ),
        ),
        "tampered-qualification-evidence": _fail_closed_case(
            "qualification evidence whose digest does not match is refused",
            stage="release-selection",
            windows=True,
            codes=frozenset(
                {
                    "launch_model_manifest_qualification_mismatch",
                    "launch_pipeline_qualification_mismatch",
                    "launch_runtime_profile_qualification_mismatch",
                }
            ),
        ),
        "qualification-bundle-mismatch": _fail_closed_case(
            "an evidence bundle that does not bind its own artefacts is refused",
            stage="release-selection",
            codes=frozenset(
                {
                    "qualification_record_invalid",
                    "qualification_record_required",
                    "qualification_identity_mismatch",
                    "runtime_profile_id_mismatch",
                }
            ),
        ),
        "corrupted-lock": _fail_closed_case(
            "an offline lock that does not parse or hash is refused",
            stage="release-selection",
            codes=frozenset(
                _OFFLINE_LOCK_CODES | {"launch_runtime_lock_binding_stale"}
            ),
        ),
        "corrupted-manifest": _fail_closed_case(
            "a Runtime Pack manifest that does not parse or hash is refused",
            stage="release-selection",
            windows=True,
            codes=frozenset(
                {
                    "launch_runtime_manifest_fingerprint_mismatch",
                    "launch_model_manifest_fingerprint_mismatch",
                }
            ),
        ),
        "missing-model-identity": _fail_closed_case(
            "a missing model, config or checkpoint identity is refused",
            stage="release-selection",
            windows=True,
            codes=frozenset(
                {
                    "launch_model_pack_binding_stale",
                    "launch_overlay_file_missing",
                }
            ),
        ),
        "runtime-profile-mismatch": _fail_closed_case(
            "a runtime profile other than the bound one is refused",
            stage="release-selection",
            windows=True,
            codes=frozenset({"launch_component_runtime_profile_mismatch"}),
        ),
        "development-evidence-presented-to-production": _fail_closed_case(
            "Development evidence can never satisfy Production qualification",
            stage="release-selection",
            policy="cuda",
            codes=frozenset(
                {
                    "runtime_platform_variant_not_qualified",
                    "production_runtime_not_qualified",
                    "production_release_not_verified",
                    "unverified_release_forbidden",
                }
            ),
        ),
        # Recovery, where retry is the correct behaviour rather than refusal.
        "cuda-out-of-memory-recovered": {
            "invariant": "a bounded CUDA OOM is recoverable, not fatal",
            "stage": "processing",
            "configuredDevicePolicy": "cuda",
            "outcome": "recovered",
            "deviceResolutionReason": "explicit_cuda",
            "fallbackPermitted": False,
            "retryPermitted": True,
            "requiresHardware": True,
            "requiresWindowsHost": True,
            "expectedFailureCodes": ["vision_gpu_out_of_memory"],
        },
        "worker-restart-recovered": {
            "invariant": "a worker restart resumes without losing the lease contract",
            "stage": "processing",
            "configuredDevicePolicy": "cuda",
            "outcome": "recovered",
            "deviceResolutionReason": "explicit_cuda",
            "fallbackPermitted": False,
            "retryPermitted": True,
            "requiresHardware": True,
            "requiresWindowsHost": True,
            "expectedFailureCodes": [
                "vision_gpu_runtime_failed",
                "vision_inference_watchdog_expired",
            ],
        },
    }
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _text(value: object, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FailureMatrixError(code)
    return value


def _load(
    path: Path,
    schema: str,
    code: str,
    json_schema: dict | None = None,
) -> tuple[dict, str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FailureMatrixError(code + "_unreadable") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FailureMatrixError(code + "_invalid") from exc
    if not isinstance(value, dict) or value.get("schemaVersion") != schema:
        raise FailureMatrixError(code + "_schema_invalid")
    if json_schema is not None:
        # The published schema owns the record's shape, and names the offending
        # path when it is wrong. The assembler owns the policy the shape cannot
        # express, and keeps its own actionable codes for that.
        try:
            Draft202012Validator(json_schema).validate(value)
        except Exception as exc:
            raise FailureMatrixError(code + "_schema_invalid") from exc
    return value, _sha256_bytes(raw)


def _check_case(
    case_id: str,
    observation: dict,
    declared: dict,
    *,
    gpu_uuid_sha256: str | None = None,
) -> dict:
    """Check one observed failure against the case it claims to exercise."""
    policy = _text(
        observation.get("configuredDevicePolicy"),
        "failure_case_device_policy_missing:" + case_id,
    )
    if policy != declared["configuredDevicePolicy"]:
        raise FailureMatrixError("failure_case_device_policy_mismatch:" + case_id)

    outcome = observation.get("outcome")
    if outcome != declared["outcome"]:
        raise FailureMatrixError("failure_case_outcome_mismatch:" + case_id)

    # A permitted Auto fallback is not a failure: the run succeeded on CPU, and
    # the resolution reason is the whole record. Only a refusal or a recovery
    # has a failure code, and then it must be one this case can legitimately
    # produce -- otherwise the case was reported by some other path.
    failure_code = observation.get("failureCode")
    if declared["outcome"] == "auto-fallback-cpu":
        if failure_code is not None:
            raise FailureMatrixError(
                "failure_case_fallback_has_failure_code:" + case_id
            )
    else:
        failure_code = _text(
            failure_code, "failure_case_failure_code_missing:" + case_id
        )
        if _FAILURE_CODE.fullmatch(failure_code) is None:
            raise FailureMatrixError(
                "failure_case_failure_code_invalid:" + case_id
            )
        expected_codes = declared["expectedFailureCodes"]
        if expected_codes is not None and failure_code not in expected_codes:
            raise FailureMatrixError(
                "failure_case_failure_code_unexpected:" + case_id
            )

    diagnostic = _text(
        observation.get("operatorDiagnostic"),
        "failure_case_operator_diagnostic_missing:" + case_id,
    )
    if len(diagnostic) > 2000:
        raise FailureMatrixError(
            "failure_case_operator_diagnostic_invalid:" + case_id
        )
    diagnostic = _RAW_GPU_UUID.sub("GPU-<redacted>", diagnostic)

    reason = observation.get("deviceResolutionReason")
    device = observation.get("actualDevice")

    refused_reason = observation.get("refusedResolutionReason")
    if case_id == "auto-unknown-reason-refused":
        # The case exists to prove an out-of-vocabulary reason is rejected, so
        # the observation has to be able to say which one. It is deliberately a
        # separate field: `deviceResolutionReason` is forbidden here because
        # nothing was resolved.
        if not isinstance(refused_reason, str) or not refused_reason.strip():
            raise FailureMatrixError(
                "failure_case_refused_reason_missing:" + case_id
            )
        if refused_reason in DEVICE_RESOLUTION_REASONS:
            # A reason inside the vocabulary is not the thing being refused.
            raise FailureMatrixError(
                "failure_case_refused_reason_is_contracted:" + case_id
            )
    elif refused_reason is not None:
        raise FailureMatrixError(
            "failure_case_refused_reason_out_of_place:" + case_id
        )

    if declared["outcome"] == "fail-closed":
        # Nothing ran, so nothing may be reported as having run. A device here
        # is the failure the case exists to detect.
        if device is not None:
            raise FailureMatrixError("failure_case_not_fail_closed:" + case_id)
        if observation.get("processingCompleted") is not False:
            # Stating it is the point: silence is not evidence that nothing ran.
            raise FailureMatrixError("failure_case_not_fail_closed:" + case_id)
        if reason is not None:
            raise FailureMatrixError(
                "failure_case_unexpected_resolution_reason:" + case_id
            )
    else:
        if reason not in DEVICE_RESOLUTION_REASONS:
            raise FailureMatrixError(
                "failure_case_resolution_reason_unknown:" + case_id
            )
        if reason != declared["deviceResolutionReason"]:
            raise FailureMatrixError(
                "failure_case_resolution_reason_mismatch:" + case_id
            )
        device = _text(device, "failure_case_actual_device_missing:" + case_id)

    if declared["outcome"] == "auto-fallback-cpu":
        # A permitted fallback, and only for a reason the closed vocabulary
        # allows. This is the one place CPU is an acceptable answer to CUDA.
        if reason not in AUTO_CPU_DEVICE_RESOLUTION_REASONS:
            raise FailureMatrixError(
                "failure_case_fallback_reason_not_permitted:" + case_id
            )
        if device != "cpu":
            raise FailureMatrixError("failure_case_fallback_device_invalid:" + case_id)
        if observation.get("fallbackLogged") is not True:
            # An unlogged fallback is a silent one, whatever its reason.
            raise FailureMatrixError("failure_case_fallback_not_logged:" + case_id)
        if observation.get("fallbackPersistedInProvenance") is not True:
            raise FailureMatrixError(
                "failure_case_fallback_not_persisted:" + case_id
            )

    if declared["outcome"] == "recovered":
        if not is_cuda_device(device):
            raise FailureMatrixError("failure_case_recovery_device_invalid:" + case_id)
        if observation.get("recovered") is not True:
            raise FailureMatrixError("failure_case_not_recovered:" + case_id)
        attempts = observation.get("attemptCount")
        if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 2:
            # A recovery that never retried did not exercise recovery.
            raise FailureMatrixError("failure_case_recovery_not_exercised:" + case_id)

    if not declared["retryPermitted"] and observation.get("recovered") not in (
        None,
        False,
    ):
        raise FailureMatrixError("failure_case_retry_not_permitted:" + case_id)

    if declared["requiresHardware"]:
        # A case that needs a GPU must carry something only a GPU host could
        # have produced. Without this, a full `hardware` bundle assembles on a
        # machine with no device and is indistinguishable from one that ran --
        # which is exactly the tooling-is-not-execution line this phase exists
        # to hold. The identity is the salted digest, never the raw UUID.
        observed_gpu = observation.get("gpuUuidSha256")
        if not isinstance(observed_gpu, str) or _SHA256.fullmatch(
            observed_gpu
        ) is None:
            raise FailureMatrixError(
                "failure_case_gpu_identity_missing:" + case_id
            )
        if gpu_uuid_sha256 is not None and observed_gpu != gpu_uuid_sha256:
            raise FailureMatrixError(
                "failure_case_gpu_identity_mismatch:" + case_id
            )
        if not isinstance(observation.get("driverVersion"), str) or not str(
            observation.get("driverVersion")
        ).strip():
            raise FailureMatrixError(
                "failure_case_driver_version_missing:" + case_id
            )

    return {
        "caseId": case_id,
        "invariant": declared["invariant"],
        "stage": declared["stage"],
        "configuredDevicePolicy": policy,
        "outcome": outcome,
        "failureCode": failure_code,
        "deviceResolutionReason": reason,
        "actualDevice": device,
        "operatorDiagnostic": diagnostic,
        "retryPermitted": declared["retryPermitted"],
        "fallbackPermitted": declared["fallbackPermitted"],
        "requiresHardware": declared["requiresHardware"],
        "requiresWindowsHost": declared["requiresWindowsHost"],
        "refusedResolutionReason": refused_reason,
        "gpuUuidSha256": observation.get("gpuUuidSha256")
        if declared["requiresHardware"]
        else None,
    }


def expected_cases(scope: str) -> set[str]:
    """Which cases a bundle of this scope must carry.

    Two axes, not one. A case can need the Windows launcher without needing a
    GPU -- most of the permitted Auto fallbacks are resolved by
    `Test-CudaRuntimeUsable` before Python starts, and PowerShell does not run
    in hosted CI at all. Treating "no GPU required" as "observable here" would
    have put those cases in a bundle no hosted machine can honestly produce.
    """
    if scope not in SCOPES:
        raise FailureMatrixError("failure_matrix_scope_invalid")
    if scope == "hardware":
        return set(FAILURE_CASES)
    if scope == "windows-host":
        return {
            case_id
            for case_id, declared in FAILURE_CASES.items()
            if not declared["requiresHardware"]
        }
    return {
        case_id
        for case_id, declared in FAILURE_CASES.items()
        if not declared["requiresHardware"] and not declared["requiresWindowsHost"]
    }


def _committed_qualification(
    runtime_profile: Path,
    block: dict,
) -> tuple[str, str]:
    """Require the C4 block to be the record the committed profile carries."""
    try:
        raw = runtime_profile.read_bytes()
        profile = json.loads(raw)
    except OSError as exc:
        raise FailureMatrixError("failure_matrix_runtime_profile_unreadable") from exc
    except json.JSONDecodeError as exc:
        raise FailureMatrixError("failure_matrix_runtime_profile_invalid") from exc
    variants = profile.get("platformVariants") if isinstance(profile, dict) else None
    variant = variants.get(_CUDA_VARIANT) if isinstance(variants, dict) else None
    if not isinstance(variant, dict):
        raise FailureMatrixError("failure_matrix_runtime_profile_invalid")
    if variant.get("status") != "qualified-development-hardware":
        raise FailureMatrixError("failure_matrix_runtime_variant_not_qualified")
    committed = variant.get("developmentEvidence")
    if not isinstance(committed, dict):
        raise FailureMatrixError("failure_matrix_qualification_not_committed")
    for field in _EVIDENCE_BLOCK_FIELDS:
        if block.get(field) != committed.get(field):
            raise FailureMatrixError("failure_matrix_qualification_not_committed")
    head = block.get("sourceHeadSha")
    if not isinstance(head, str) or _SOURCE_HEAD_SHA.fullmatch(head) is None:
        raise FailureMatrixError(
            "failure_matrix_development_evidence_schema_invalid"
        )
    return _sha256_bytes(raw), head


def build_failure_matrix(
    *,
    scope: str,
    cases: dict[str, Path],
    source_head_sha: str,
    captured_at_utc: str,
    operator_reference: str,
    development_evidence: Path | None = None,
    runtime_profile: Path = _DEFAULT_RUNTIME_PROFILE,
) -> dict[str, object]:
    if scope not in SCOPES:
        raise FailureMatrixError("failure_matrix_scope_invalid")
    if _SOURCE_HEAD_SHA.fullmatch(source_head_sha) is None:
        raise FailureMatrixError("failure_matrix_source_head_sha_invalid")
    if _CANONICAL_UTC.fullmatch(captured_at_utc) is None:
        raise FailureMatrixError("failure_matrix_captured_at_invalid")
    if _OPERATOR_REFERENCE.fullmatch(operator_reference) is None:
        raise FailureMatrixError("failure_matrix_operator_invalid")

    required = expected_cases(scope)
    missing = sorted(required - set(cases))
    if missing:
        raise FailureMatrixError("failure_matrix_case_missing:" + ",".join(missing))
    unknown = sorted(set(cases) - set(FAILURE_CASES))
    if unknown:
        raise FailureMatrixError("failure_matrix_unknown_case:" + ",".join(unknown))
    if scope != "hardware":
        # A bundle may not carry a case its scope says it cannot have observed;
        # otherwise the scope label understates what the bundle claims.
        out_of_scope = sorted(set(cases) - required)
        if out_of_scope:
            raise FailureMatrixError(
                "failure_matrix_hardware_case_out_of_scope:" + ",".join(out_of_scope)
            )

    # A hardware bundle names the card its cases were observed on, and binds to
    # the C4 record that qualified it. Otherwise the bundle asserts nothing
    # about which machine produced it.
    gpu_uuid_sha256: str | None = None
    development_sha: str | None = None
    runtime_profile_sha: str | None = None
    qualification_head: str | None = None
    if scope == "hardware":
        if development_evidence is None:
            raise FailureMatrixError("failure_matrix_development_evidence_required")
        hardware, development_sha = _load(
            development_evidence,
            "mavi-windows-cuda-development-evidence-v2",
            "failure_matrix_development_evidence",
        )
        corroboration = hardware.get("corroboration")
        variant_patch = hardware.get("variantPatch")
        if not isinstance(corroboration, dict) or not isinstance(
            variant_patch, dict
        ):
            raise FailureMatrixError(
                "failure_matrix_development_evidence_schema_invalid"
            )
        # The same two checks C6 applies to the same artefact. C7 declares
        # `tampered-qualification-evidence` as a case it exercises, so a C7
        # bundle that trusts an unverified C4 digest claims to have tested the
        # very thing it skipped.
        if variant_patch.get("status") != "qualified-development-hardware":
            raise FailureMatrixError(
                "failure_matrix_development_evidence_not_qualified"
            )
        block_for_digest = hardware.get("developmentEvidence")
        if not isinstance(block_for_digest, dict):
            raise FailureMatrixError(
                "failure_matrix_development_evidence_schema_invalid"
            )
        claimed = block_for_digest.get("evidenceBundleSha256")
        restated = json.loads(json.dumps(hardware))
        restated["developmentEvidence"]["evidenceBundleSha256"] = ""
        if not isinstance(claimed, str) or claimed != _sha256_bytes(
            _canonical(restated)
        ):
            raise FailureMatrixError(
                "failure_matrix_development_evidence_digest_mismatch"
            )
        gpu_uuid_sha256 = corroboration.get("gpuUuidSha256")
        if not isinstance(gpu_uuid_sha256, str) or _SHA256.fullmatch(
            gpu_uuid_sha256
        ) is None:
            raise FailureMatrixError(
                "failure_matrix_development_evidence_schema_invalid"
            )
        # Bound to the qualification the tree under test actually carries, as
        # C6 is; see _committed_qualification for why head equality cannot.
        runtime_profile_sha, qualification_head = _committed_qualification(
            runtime_profile, block_for_digest
        )
    elif development_evidence is not None:
        # A non-hardware bundle that cited hardware evidence would imply the
        # very thing its scope denies.
        raise FailureMatrixError("failure_matrix_development_evidence_out_of_scope")

    checked = []
    digests = {}
    for case_id in sorted(cases):
        observation, digest = _load(
            cases[case_id], CASE_SCHEMA_VERSION, "failure_case", _record_schema()
        )
        checked.append(
            _check_case(
                case_id,
                observation,
                FAILURE_CASES[case_id],
                gpu_uuid_sha256=gpu_uuid_sha256,
            )
        )
        digests[case_id] = digest

    evidence: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "failureMatrix": {
            "scope": scope,
            "evidenceBundleSha256": "",
            "sourceHeadSha": source_head_sha,
            "qualificationSourceHeadSha": qualification_head,
            "runtimeProfileSha256": runtime_profile_sha,
            "capturedAtUtc": captured_at_utc,
            "operatorReference": operator_reference,
            "caseCount": len(checked),
            "developmentEvidenceSha256": development_sha,
            "gpuUuidSha256": gpu_uuid_sha256,
        },
        "cases": checked,
        "caseSha256": digests,
        "note": (
            "C7 failure-matrix evidence. It records that the fail-closed and "
            "permitted-fallback paths behave as declared. It is not hardware "
            "qualification, and a linux-observable bundle asserts nothing about "
            "any GPU."
        ),
    }
    evidence["failureMatrix"]["evidenceBundleSha256"] = _sha256_bytes(  # type: ignore[index]
        _canonical(evidence)
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", choices=SCOPES, required=True)
    parser.add_argument(
        "--development-evidence",
        type=Path,
        help="the C4 hardware evidence bundle; required for --scope hardware",
    )
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        metavar="CASE_ID=PATH",
        help="one observation per failure case; repeat for each",
    )
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--captured-at-utc", required=True)
    parser.add_argument("--operator-reference", required=True)
    parser.add_argument(
        "--runtime-profile",
        type=Path,
        default=_DEFAULT_RUNTIME_PROFILE,
        help="the committed runtime profile carrying the C4 record (hardware scope)",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--print-matrix",
        action="store_true",
        help="print the declared matrix and exit, for operator preparation",
    )
    args = parser.parse_args()

    if args.print_matrix:
        print(
            json.dumps(
                {"schemaVersion": SCHEMA_VERSION, "cases": FAILURE_CASES},
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    cases: dict[str, Path] = {}
    for item in args.case:
        case_id, separator, path = item.partition("=")
        if not separator or not case_id or not path:
            print(json.dumps({"ok": False, "code": "failure_case_argument_invalid"}))
            return 2
        if case_id in cases:
            print(json.dumps({"ok": False, "code": "failure_case_argument_duplicate"}))
            return 2
        cases[case_id] = Path(path)

    try:
        evidence = build_failure_matrix(
            scope=args.scope,
            cases=cases,
            source_head_sha=args.source_head_sha,
            captured_at_utc=args.captured_at_utc,
            operator_reference=args.operator_reference,
            development_evidence=args.development_evidence,
            runtime_profile=args.runtime_profile,
        )
    except FailureMatrixError as exc:
        print(json.dumps({"ok": False, "code": exc.code}, sort_keys=True))
        return 2

    if args.output is not None:
        if args.output.exists():
            print(
                json.dumps(
                    {"ok": False, "code": "failure_matrix_output_exists"},
                    sort_keys=True,
                )
            )
            return 2
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(json.dumps({"ok": True, "evidence": evidence}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
