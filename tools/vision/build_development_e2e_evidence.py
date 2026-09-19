#!/usr/bin/env python3
"""Assemble the C6 Development end-to-end evidence bundle.

C6 asks the Development laptop to prove eight things about real processing runs.
Left to prose, "we ran it and it worked" is what arrives; this tool turns that
phase's output into a checked artefact instead, by requiring a run record for
every case the plan names and refusing a bundle where any of them is missing,
contradicts itself, or quietly did something other than what it claims.

Two rules carry most of the weight:

- **No silent GPU-to-CPU fallback.** Every run's configured policy, resolved
  device and reason code are checked against the one authoritative vocabulary
  in `mavi_vision.common.control_plane` -- the same function the wire contract
  uses -- rather than a restatement of it here that could drift.
- **A CUDA run must have touched the GPU.** On-device MMCV native ops and a
  non-zero peak device allocation are both required, because a run that reports
  `cuda:0` while the allocator never saw a byte did not execute there.

Timing is carried for engineering characterisation only. The plan is explicit
that no Production threshold may be frozen from a CPU-versus-CUDA comparison on
Development hardware, so the bundle says so in the record itself.

It is offline and reads only the files it is given.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
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
    CUDA_DEVICE_PATTERN,
    is_cuda_device,
    validate_device_resolution_wire_relationship,
)

SCHEMA_VERSION = "mavi-windows-cuda-development-e2e-v1"
RUN_SCHEMA_VERSION = "mavi-windows-cuda-development-e2e-run-v1"

_DEVELOPMENT_EVIDENCE_SCHEMA = "mavi-windows-cuda-development-evidence-v2"

_SOURCE_HEAD_SHA = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_CANONICAL_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", re.ASCII)
_OPERATOR_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@/-]{0,127}$", re.ASCII)
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)

# One case per thing C6 asks to be proven. A bundle missing any of these has
# not finished the phase, whatever its other runs show.
REQUIRED_CASES: dict[str, dict[str, object]] = {
    "explicit-cuda": {
        "proves": "explicit CUDA selects cuda:0 and never falls back",
        "configuredDevicePolicy": "cuda",
        "deviceResolutionReason": "explicit_cuda",
        "cuda": True,
    },
    "auto-cuda": {
        "proves": "Auto selects CUDA when the qualified pack and device exist",
        "configuredDevicePolicy": "auto",
        "deviceResolutionReason": "cuda_selected",
        "cuda": True,
    },
    "explicit-cpu": {
        "proves": "the CPU path still completes independently",
        "configuredDevicePolicy": "cpu",
        "deviceResolutionReason": "explicit_cpu",
        "cuda": False,
    },
    "restart-recovery": {
        "proves": "retry and restart behaviour remains correct",
        "configuredDevicePolicy": "cuda",
        "deviceResolutionReason": "explicit_cuda",
        "cuda": True,
    },
    "cuda-oom-recovery": {
        "proves": "one deliberate, bounded CUDA OOM is recovered from",
        "configuredDevicePolicy": "cuda",
        "deviceResolutionReason": "explicit_cuda",
        "cuda": True,
    },
}

_CHARACTERISATION_NOTE = (
    "Timing is engineering characterisation on Development hardware only. No "
    "Production threshold may be derived from this CPU-versus-CUDA comparison."
)


class DevelopmentE2eError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    # allow_nan=False: a bundle carrying NaN or Infinity is not valid JSON, and
    # a strict reader would reject the whole artefact after it was committed.
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _text(value: object, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DevelopmentE2eError(code)
    return value


def _positive_int(value: object, code: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise DevelopmentE2eError(code)
    return value


def _non_negative_int(value: object, code: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise DevelopmentE2eError(code)
    return value


def _load(path: Path, schema: str, code: str) -> tuple[dict, str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DevelopmentE2eError(code + "_unreadable") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DevelopmentE2eError(code + "_invalid") from exc
    if not isinstance(value, dict) or value.get("schemaVersion") != schema:
        raise DevelopmentE2eError(code + "_schema_invalid")
    return value, _sha256_bytes(raw)


def _memory_reading(value: object, code: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise DevelopmentE2eError(code)
    return {
        key: _non_negative_int(value.get(key), code)
        for key in ("freeMiB", "usedMiB")
    }


def _check_run(
    case_id: str,
    run: dict,
    expectation: dict[str, object],
    corroboration: dict | None = None,
) -> dict:
    """Check one run against the case it claims to prove."""
    policy = _text(
        run.get("configuredDevicePolicy"), "e2e_run_device_policy_missing"
    )
    device = _text(run.get("actualDevice"), "e2e_run_actual_device_missing")
    reason = run.get("deviceResolutionReason")

    # The one authoritative vocabulary and relationship, not a copy of it.
    try:
        validate_device_resolution_wire_relationship(
            configured_device_policy=policy,
            actual_device=device,
            device_resolution_reason=reason,
        )
    except ValueError as exc:
        raise DevelopmentE2eError("e2e_run_device_relationship_invalid:" + str(exc))

    if policy != expectation["configuredDevicePolicy"]:
        raise DevelopmentE2eError("e2e_run_device_policy_mismatch:" + case_id)
    if reason != expectation["deviceResolutionReason"]:
        raise DevelopmentE2eError("e2e_run_resolution_reason_mismatch:" + case_id)

    on_cuda = bool(expectation["cuda"])
    if on_cuda and not is_cuda_device(device):
        # The case exists to prove CUDA ran; a CPU device here is the silent
        # fallback C6 requirement 8 forbids, however the run was labelled.
        raise DevelopmentE2eError("e2e_run_cuda_fallback:" + case_id)
    if not on_cuda and device != "cpu":
        raise DevelopmentE2eError("e2e_run_unexpected_cuda:" + case_id)

    if run.get("status") != "Processed":
        raise DevelopmentE2eError("e2e_run_not_processed:" + case_id)
    if run.get("progressPercent") != 100:
        raise DevelopmentE2eError("e2e_run_incomplete:" + case_id)
    _positive_int(run.get("detectionCount"), "e2e_run_no_detections:" + case_id)
    _positive_int(run.get("trackCount"), "e2e_run_no_tracks:" + case_id)
    _positive_int(run.get("framesProcessed"), "e2e_run_no_frames:" + case_id)

    media_sha = run.get("mediaSha256")
    if not isinstance(media_sha, str) or _SHA256.fullmatch(media_sha) is None:
        raise DevelopmentE2eError("e2e_run_media_identity_missing:" + case_id)

    elapsed = run.get("elapsedSeconds")
    if not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool):
        raise DevelopmentE2eError("e2e_run_timing_missing:" + case_id)
    # NaN <= 0 is False, so a bare `NaN` in the record would pass a naive guard
    # and then be written into the artefact as invalid JSON.
    if not math.isfinite(elapsed) or elapsed <= 0:
        raise DevelopmentE2eError("e2e_run_timing_missing:" + case_id)

    provenance = run.get("provenance")
    if not isinstance(provenance, dict):
        raise DevelopmentE2eError("e2e_run_provenance_missing:" + case_id)
    if provenance.get("actualDevice") != device:
        raise DevelopmentE2eError("e2e_run_provenance_device_mismatch:" + case_id)
    if provenance.get("deviceResolutionReason") != reason:
        raise DevelopmentE2eError("e2e_run_provenance_reason_mismatch:" + case_id)
    # Development provenance is never `verified`: the profile carries a
    # Development-qualified variant, so the record describes the run without
    # inheriting the release's verified label. Claiming otherwise here would
    # mean the record did not come from this runtime.
    if provenance.get("verificationStatus") != "unverified":
        raise DevelopmentE2eError(
            "e2e_run_provenance_status_unexpected:" + case_id
        )

    host_ram_peak = _positive_int(
        run.get("hostRamPeakBytes"), "e2e_run_host_ram_missing:" + case_id
    )

    checked: dict[str, object] = {
        "caseId": case_id,
        "proves": expectation["proves"],
        "configuredDevicePolicy": policy,
        "deviceResolutionReason": reason,
        "actualDevice": device,
        "mediaSha256": media_sha,
        "framesProcessed": run["framesProcessed"],
        "detectionCount": run["detectionCount"],
        "trackCount": run["trackCount"],
        "elapsedSeconds": elapsed,
        "framesPerSecond": round(run["framesProcessed"] / elapsed, 3),
        "hostRamPeakBytes": host_ram_peak,
        "provenanceVerificationStatus": "unverified",
    }

    if not on_cuda:
        return checked

    cuda = run.get("cuda")
    if not isinstance(cuda, dict):
        raise DevelopmentE2eError("e2e_run_cuda_telemetry_missing:" + case_id)
    if cuda.get("mmcvNmsExecutedOnCuda") is not True:
        # Same rule as C4: reporting cuda:0 is not evidence the native ops ran.
        raise DevelopmentE2eError("e2e_run_native_ops_not_executed:" + case_id)
    allocated = _positive_int(
        cuda.get("maxMemoryAllocatedBytes"),
        "e2e_run_no_device_allocation:" + case_id,
    )
    reserved = _non_negative_int(
        cuda.get("maxMemoryReservedBytes"),
        "e2e_run_device_allocation_invalid:" + case_id,
    )
    if reserved < allocated:
        raise DevelopmentE2eError(
            "e2e_run_device_allocation_invalid:" + case_id
        )
    arch_list = cuda.get("archList")
    if not isinstance(arch_list, list) or not all(
        isinstance(item, str) and item for item in arch_list
    ):
        raise DevelopmentE2eError("e2e_run_arch_list_missing:" + case_id)

    smi = run.get("nvidiaSmi")
    if not isinstance(smi, dict):
        raise DevelopmentE2eError("e2e_run_nvidia_smi_missing:" + case_id)
    readings = {
        phase: _memory_reading(
            smi.get(phase), "e2e_run_nvidia_smi_invalid:" + case_id
        )
        for phase in ("before", "during", "after")
    }
    if readings["during"]["usedMiB"] <= readings["before"]["usedMiB"]:
        # Work on the device shows up as device memory in use while it runs.
        raise DevelopmentE2eError("e2e_run_no_device_utilisation:" + case_id)

    if corroboration is not None:
        # The run must be on the card C4 qualified, at the ordinal C4 attested,
        # with kernels for that card. Without this the bundle's only statement
        # about which GPU ran the work is the literal ordinal string.
        observed_gpu = run.get("gpuUuidSha256")
        if not isinstance(observed_gpu, str) or _SHA256.fullmatch(
            observed_gpu
        ) is None:
            raise DevelopmentE2eError("e2e_run_gpu_identity_missing:" + case_id)
        if observed_gpu != corroboration.get("gpuUuidSha256"):
            raise DevelopmentE2eError("e2e_run_gpu_identity_mismatch:" + case_id)
        match = CUDA_DEVICE_PATTERN.fullmatch(device)
        if match is None or int(match.group(1)) != corroboration.get("deviceIndex"):
            raise DevelopmentE2eError("e2e_run_device_index_mismatch:" + case_id)
        target = corroboration.get("targetArchitecture")
        if target not in arch_list:
            # A run that fell back to PTX JIT is not the artefact C4 qualified.
            raise DevelopmentE2eError(
                "e2e_run_architecture_not_in_build:" + case_id
            )
        if cuda.get("runtimeVersion") != corroboration.get(
            "torchCudaRuntimeVersion"
        ):
            raise DevelopmentE2eError(
                "e2e_run_cuda_runtime_version_mismatch:" + case_id
            )
        checked["gpuUuidSha256"] = observed_gpu

    checked.update(
        {
            "cuda": {
                "maxMemoryAllocatedBytes": allocated,
                "maxMemoryReservedBytes": reserved,
                "archList": list(arch_list),
                "runtimeVersion": _text(
                    cuda.get("runtimeVersion"),
                    "e2e_run_cuda_runtime_version_missing:" + case_id,
                ),
                "mmcvNmsExecutedOnCuda": True,
            },
            "nvidiaSmi": readings,
        }
    )
    if case_id == "cuda-oom-recovery":
        if run.get("recoveredFromCudaOutOfMemory") is not True:
            raise DevelopmentE2eError("e2e_run_oom_not_exercised")
        checked["recoveredFromCudaOutOfMemory"] = True
    if case_id == "restart-recovery":
        _positive_int(run.get("restartCount"), "e2e_run_restart_not_exercised")
        checked["restartCount"] = run["restartCount"]
    return checked


def build_e2e_evidence(
    *,
    development_evidence: Path,
    runs: dict[str, Path],
    source_head_sha: str,
    captured_at_utc: str,
    operator_reference: str,
) -> dict[str, object]:
    if _SOURCE_HEAD_SHA.fullmatch(source_head_sha) is None:
        raise DevelopmentE2eError("e2e_source_head_sha_invalid")
    if _CANONICAL_UTC.fullmatch(captured_at_utc) is None:
        raise DevelopmentE2eError("e2e_captured_at_invalid")
    if _OPERATOR_REFERENCE.fullmatch(operator_reference) is None:
        raise DevelopmentE2eError("e2e_operator_invalid")

    hardware, hardware_sha = _load(
        development_evidence,
        _DEVELOPMENT_EVIDENCE_SCHEMA,
        "e2e_development_evidence",
    )
    block = hardware.get("developmentEvidence")
    corroboration = hardware.get("corroboration")
    variant_patch = hardware.get("variantPatch")
    if (
        not isinstance(block, dict)
        or not isinstance(corroboration, dict)
        or not isinstance(variant_patch, dict)
    ):
        raise DevelopmentE2eError("e2e_development_evidence_schema_invalid")
    # C6 runs describe the same source revision the hardware was qualified at;
    # otherwise the bundle joins a run to a qualification of something else.
    if block.get("sourceHeadSha") != source_head_sha:
        raise DevelopmentE2eError("e2e_source_revision_mismatch")
    # A C4 record that did not itself reach the Development state cannot be the
    # base of a Development E2E bundle.
    if variant_patch.get("status") != "qualified-development-hardware":
        raise DevelopmentE2eError("e2e_development_evidence_not_qualified")
    # C4's digest is recomputable by design, and C7 declares a case for tampered
    # qualification evidence -- so the one tool that consumes C4 must check it.
    claimed = block.get("evidenceBundleSha256")
    restated = json.loads(json.dumps(hardware))
    restated["developmentEvidence"]["evidenceBundleSha256"] = ""
    if not isinstance(claimed, str) or claimed != _sha256_bytes(
        _canonical(restated)
    ):
        raise DevelopmentE2eError("e2e_development_evidence_digest_mismatch")
    if not isinstance(corroboration.get("gpuUuidSha256"), str):
        raise DevelopmentE2eError("e2e_development_evidence_schema_invalid")

    missing = sorted(set(REQUIRED_CASES) - set(runs))
    if missing:
        raise DevelopmentE2eError("e2e_required_case_missing:" + ",".join(missing))
    unexpected = sorted(set(runs) - set(REQUIRED_CASES))
    if unexpected:
        raise DevelopmentE2eError("e2e_unknown_case:" + ",".join(unexpected))

    checked_runs = []
    run_digests = {}
    for case_id in sorted(REQUIRED_CASES):
        run, run_sha = _load(
            runs[case_id], RUN_SCHEMA_VERSION, "e2e_run"
        )
        checked_runs.append(
            _check_run(
                case_id,
                run,
                REQUIRED_CASES[case_id],
                corroboration if REQUIRED_CASES[case_id]["cuda"] else None,
            )
        )
        run_digests[case_id] = run_sha

    media = {run["mediaSha256"] for run in checked_runs}
    if len(media) != 1:
        # A CPU-versus-CUDA characterisation between two different videos
        # characterises nothing.
        raise DevelopmentE2eError("e2e_runs_describe_different_media")
    frames = {run["framesProcessed"] for run in checked_runs}
    if len(frames) != 1:
        raise DevelopmentE2eError("e2e_runs_processed_different_frame_counts")

    evidence: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "developmentE2e": {
            "developmentEvidenceSha256": hardware_sha,
            "gpuUuidSha256": corroboration.get("gpuUuidSha256"),
            "mediaSha256": sorted(media)[0],
            "evidenceBundleSha256": "",
            "sourceHeadSha": source_head_sha,
            "capturedAtUtc": captured_at_utc,
            "operatorReference": operator_reference,
        },
        "runs": checked_runs,
        "runSha256": run_digests,
        "characterisationOnly": _CHARACTERISATION_NOTE,
        "note": (
            "C6 Development end-to-end evidence. This supports the "
            "qualified-development-hardware runtime state only and asserts "
            "nothing about Production capability or performance."
        ),
    }
    evidence["developmentE2e"]["evidenceBundleSha256"] = _sha256_bytes(  # type: ignore[index]
        _canonical(evidence)
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--development-evidence", type=Path, required=True)
    parser.add_argument(
        "--run",
        action="append",
        default=[],
        metavar="CASE_ID=PATH",
        help="one run record per C6 case; repeat for each",
    )
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--captured-at-utc", required=True)
    parser.add_argument("--operator-reference", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    runs: dict[str, Path] = {}
    for item in args.run:
        case_id, separator, path = item.partition("=")
        if not separator or not case_id or not path:
            print(
                json.dumps({"ok": False, "code": "e2e_run_argument_invalid"}),
                flush=True,
            )
            return 2
        if case_id in runs:
            print(json.dumps({"ok": False, "code": "e2e_run_argument_duplicate"}))
            return 2
        runs[case_id] = Path(path)

    try:
        evidence = build_e2e_evidence(
            development_evidence=args.development_evidence,
            runs=runs,
            source_head_sha=args.source_head_sha,
            captured_at_utc=args.captured_at_utc,
            operator_reference=args.operator_reference,
        )
    except DevelopmentE2eError as exc:
        print(json.dumps({"ok": False, "code": exc.code}, sort_keys=True))
        return 2

    if args.output is not None:
        if args.output.exists():
            print(
                json.dumps(
                    {"ok": False, "code": "e2e_output_exists"}, sort_keys=True
                )
            )
            return 2
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False)
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(json.dumps({"ok": True, "evidence": evidence}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
