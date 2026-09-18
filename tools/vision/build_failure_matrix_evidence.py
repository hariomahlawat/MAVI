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

SCHEMA_VERSION = "mavi-windows-cuda-failure-matrix-v1"
CASE_SCHEMA_VERSION = "mavi-windows-cuda-failure-case-v1"

SCOPES = ("linux-observable", "hardware")

_SOURCE_HEAD_SHA = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_CANONICAL_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", re.ASCII)
_OPERATOR_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@/-]{0,127}$", re.ASCII)
_FAILURE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$", re.ASCII)


class FailureMatrixError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _auto_fallback_case(reason: str, invariant: str, *, hardware: bool) -> dict:
    """One permitted Development Auto fallback, named by its stable reason."""
    return {
        "invariant": invariant,
        "stage": "device-resolution",
        "configuredDevicePolicy": "auto",
        "outcome": "auto-fallback-cpu",
        "deviceResolutionReason": reason,
        "fallbackPermitted": True,
        "retryPermitted": False,
        "requiresHardware": hardware,
    }


def _fail_closed_case(
    invariant: str,
    *,
    stage: str,
    policy: str = "cuda",
    retry: bool = False,
    hardware: bool = False,
) -> dict:
    return {
        "invariant": invariant,
        "stage": stage,
        "configuredDevicePolicy": policy,
        "outcome": "fail-closed",
        "deviceResolutionReason": None,
        "fallbackPermitted": False,
        "retryPermitted": retry,
        "requiresHardware": hardware,
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

FAILURE_CASES: dict[str, dict] = {
    f"auto-{reason.removeprefix('cuda_').replace('_', '-')}": _auto_fallback_case(
        reason,
        invariant,
        hardware=reason in {"cuda_device_unavailable", "cuda_driver_probe_failed"},
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
        ),
        "explicit-cuda-pack-integrity-failed": _fail_closed_case(
            "explicit CUDA refuses a pack that fails integrity",
            stage="device-resolution",
        ),
        "explicit-cuda-pack-identity-mismatch": _fail_closed_case(
            "explicit CUDA refuses a pack that is not the declared identity",
            stage="device-resolution",
        ),
        "explicit-cuda-device-unavailable": _fail_closed_case(
            "explicit CUDA refuses when no CUDA device is present",
            stage="startup",
            hardware=True,
        ),
        "explicit-cuda-invalid-device-index": _fail_closed_case(
            "explicit CUDA refuses a device index the host does not have",
            stage="startup",
            hardware=True,
        ),
        "explicit-cuda-driver-insufficient": _fail_closed_case(
            "explicit CUDA refuses a driver older than the packed CUDA family",
            stage="startup",
            hardware=True,
        ),
        "explicit-cuda-wrong-architecture": _fail_closed_case(
            "explicit CUDA refuses a device the pack has no kernels for",
            stage="startup",
            hardware=True,
        ),
        "explicit-cuda-wrong-physical-gpu": _fail_closed_case(
            "the attested physical GPU must be the one that ran the work",
            stage="startup",
            hardware=True,
        ),
        "explicit-cuda-native-extension-import-failed": _fail_closed_case(
            "a native extension that cannot import fails closed, never to CPU",
            stage="startup",
        ),
        "explicit-cuda-mmcv-ops-failed": _fail_closed_case(
            "mmcv.ops failing on device fails closed, never to CPU",
            stage="startup",
            hardware=True,
        ),
        "explicit-cuda-torch-cuda-mismatch": _fail_closed_case(
            "a Torch CUDA runtime other than the qualified one fails closed",
            stage="startup",
        ),
        "explicit-cuda-torchvision-binary-mismatch": _fail_closed_case(
            "a torchvision build other than the qualified one fails closed",
            stage="startup",
        ),
        "explicit-cuda-python-abi-mismatch": _fail_closed_case(
            "a Python ABI other than the qualified one fails closed",
            stage="startup",
        ),
        # The forbidden transition itself. This case exists so the matrix
        # records that the system refuses it, not that it was observed working.
        "explicit-cuda-resolved-to-cpu-refused": _fail_closed_case(
            "explicit CUDA may never silently resolve to CPU",
            stage="device-resolution",
        ),
        "auto-unknown-reason-refused": _fail_closed_case(
            "a device-resolution reason outside the closed vocabulary is refused",
            stage="device-resolution",
            policy="auto",
        ),
        # Evidence and identity integrity.
        "stale-qualification-evidence": _fail_closed_case(
            "qualification evidence for another source revision is refused",
            stage="release-selection",
        ),
        "tampered-qualification-evidence": _fail_closed_case(
            "qualification evidence whose digest does not match is refused",
            stage="release-selection",
        ),
        "qualification-bundle-mismatch": _fail_closed_case(
            "an evidence bundle that does not bind its own artefacts is refused",
            stage="release-selection",
        ),
        "corrupted-lock": _fail_closed_case(
            "an offline lock that does not parse or hash is refused",
            stage="release-selection",
        ),
        "corrupted-manifest": _fail_closed_case(
            "a Runtime Pack manifest that does not parse or hash is refused",
            stage="release-selection",
        ),
        "missing-model-identity": _fail_closed_case(
            "a missing model, config or checkpoint identity is refused",
            stage="release-selection",
        ),
        "runtime-profile-mismatch": _fail_closed_case(
            "a runtime profile other than the bound one is refused",
            stage="release-selection",
        ),
        "development-evidence-presented-to-production": _fail_closed_case(
            "Development evidence can never satisfy Production qualification",
            stage="release-selection",
            policy="cuda",
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


def _load(path: Path, schema: str, code: str) -> tuple[dict, str]:
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
    return value, _sha256_bytes(raw)


def _check_case(case_id: str, observation: dict, declared: dict) -> dict:
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

    failure_code = _text(
        observation.get("failureCode"),
        "failure_case_failure_code_missing:" + case_id,
    )
    if _FAILURE_CODE.fullmatch(failure_code) is None:
        raise FailureMatrixError("failure_case_failure_code_invalid:" + case_id)

    diagnostic = _text(
        observation.get("operatorDiagnostic"),
        "failure_case_operator_diagnostic_missing:" + case_id,
    )
    if len(diagnostic) > 2000:
        raise FailureMatrixError(
            "failure_case_operator_diagnostic_invalid:" + case_id
        )

    reason = observation.get("deviceResolutionReason")
    device = observation.get("actualDevice")

    if declared["outcome"] == "fail-closed":
        # Nothing ran, so nothing may be reported as having run. A device here
        # is the failure the case exists to detect.
        if device is not None:
            raise FailureMatrixError("failure_case_not_fail_closed:" + case_id)
        if observation.get("processingCompleted") is True:
            raise FailureMatrixError("failure_case_not_fail_closed:" + case_id)
        if reason is not None:
            raise FailureMatrixError(
                "failure_case_unexpected_resolution_reason:" + case_id
            )
    else:
        expected_reason = declared["deviceResolutionReason"]
        if reason != expected_reason:
            raise FailureMatrixError(
                "failure_case_resolution_reason_mismatch:" + case_id
            )
        if reason not in DEVICE_RESOLUTION_REASONS:
            raise FailureMatrixError(
                "failure_case_resolution_reason_unknown:" + case_id
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

    if not declared["retryPermitted"] and observation.get("recovered") is True:
        raise FailureMatrixError("failure_case_retry_not_permitted:" + case_id)

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
    }


def expected_cases(scope: str) -> set[str]:
    """Which cases a bundle of this scope must carry."""
    if scope not in SCOPES:
        raise FailureMatrixError("failure_matrix_scope_invalid")
    if scope == "hardware":
        return set(FAILURE_CASES)
    return {
        case_id
        for case_id, declared in FAILURE_CASES.items()
        if not declared["requiresHardware"]
    }


def build_failure_matrix(
    *,
    scope: str,
    cases: dict[str, Path],
    source_head_sha: str,
    captured_at_utc: str,
    operator_reference: str,
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
    if scope == "linux-observable":
        # A bundle assembled without a GPU may not carry a case that needs one;
        # otherwise its scope label would understate what it claims.
        hardware_only = sorted(set(cases) - required)
        if hardware_only:
            raise FailureMatrixError(
                "failure_matrix_hardware_case_out_of_scope:" + ",".join(hardware_only)
            )

    checked = []
    digests = {}
    for case_id in sorted(cases):
        observation, digest = _load(
            cases[case_id], CASE_SCHEMA_VERSION, "failure_case"
        )
        checked.append(_check_case(case_id, observation, FAILURE_CASES[case_id]))
        digests[case_id] = digest

    evidence: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "failureMatrix": {
            "scope": scope,
            "evidenceBundleSha256": "",
            "sourceHeadSha": source_head_sha,
            "capturedAtUtc": captured_at_utc,
            "operatorReference": operator_reference,
            "caseCount": len(checked),
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
        "--case",
        action="append",
        default=[],
        metavar="CASE_ID=PATH",
        help="one observation per failure case; repeat for each",
    )
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--captured-at-utc", required=True)
    parser.add_argument("--operator-reference", required=True)
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
        cases[case_id] = Path(path)

    try:
        evidence = build_failure_matrix(
            scope=args.scope,
            cases=cases,
            source_head_sha=args.source_head_sha,
            captured_at_utc=args.captured_at_utc,
            operator_reference=args.operator_reference,
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
