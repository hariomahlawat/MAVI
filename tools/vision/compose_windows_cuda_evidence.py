#!/usr/bin/env python3
"""Compose one C6 run record or one C7 case record from what the host produced.

Both record shapes were designed to be "authored by the operator from what the
worker reported". Between five run records of twenty fields each and thirty-
seven case records, that is the largest operator-error surface in the whole
session, and every mistake surfaces only at assembly time as a refusal naming
the field. This tool moves the mechanical part off the operator: it reads the
worker's own per-attempt telemetry line, the API's processing status and
attestation, and the media file, and writes a record that already satisfies the
published schema and the assembler's per-record policy -- or refuses, here, with
the same code the assembler would have used.

It composes; it does not observe. Everything in the record traces to an
artefact the host produced: the telemetry line the worker wrote at completion,
the API responses saved to disk, the nvidia-smi readings the operator took, the
media the operator hashes. The only fields typed in are the ones that are
genuinely the operator's statement -- the launcher policy they chose, the
nvidia-smi figures, a C7 diagnostic -- and those are cross-checked against the
observed facts wherever a fact exists to check them against.

Two things it will not do. It will not write a record for a case it cannot
satisfy: a missing or inconsistent input is a refusal, never a default. And it
will not overwrite: an evidence record on disk is the record.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
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

from host_gpu_digest import gpu_uuid_digest  # noqa: E402
from mavi_vision.common.control_plane import (  # noqa: E402
    AUTO_DEVICE_RESOLUTION_REASONS,
    EXPLICIT_CPU_DEVICE_RESOLUTION_REASON,
    EXPLICIT_CUDA_DEVICE_RESOLUTION_REASON,
)

_TOOLS = Path(__file__).resolve().parent
_TELEMETRY_SCHEMA = "mavi-attempt-telemetry-v1"
_RUN_SCHEMA_VERSION = "mavi-windows-cuda-development-e2e-run-v1"
_CASE_SCHEMA_VERSION = "mavi-windows-cuda-failure-case-v1"
_OOM_FAILURE_CODE = "vision_gpu_out_of_memory"
_SMI_READING = re.compile(r"^\s*(\d+)\s*,\s*(\d+)\s*$")
# A driver or NVML message pasted as a C7 diagnostic naturally contains the
# card's raw UUID. The assembler redacts on the way in; the case file itself
# must not carry it either, so it is redacted at composition too.
_RAW_GPU_UUID = re.compile(r"GPU-[0-9A-Fa-f][0-9A-Fa-f-]{7,}")


class ComposeError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(code)


def _load_tool(name: str):
    """Import a sibling assembler so its per-record policy is reused, not copied."""
    spec = importlib.util.spec_from_file_location(name, _TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


def _read_json(path: Path, code: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise ComposeError(code + "_unreadable", str(path.name)) from exc
    except json.JSONDecodeError as exc:
        raise ComposeError(code + "_invalid", str(path.name)) from exc
    if not isinstance(value, dict):
        raise ComposeError(code + "_invalid", str(path.name))
    return value


def _field(value: dict, *names: str):
    """Read one field under any of its spellings; the API emits camelCase."""
    for name in names:
        if name in value:
            return value[name]
    lowered = {key.lower(): key for key in value}
    for name in names:
        key = lowered.get(name.lower())
        if key is not None:
            return value[key]
    return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ComposeError("compose_media_unreadable", path.name) from exc
    return digest.hexdigest()


def _smi_reading(value: str, phase: str) -> dict[str, int]:
    """One `nvidia-smi --query-gpu=memory.used,memory.free ... nounits` line."""
    match = _SMI_READING.fullmatch(value or "")
    if match is None:
        raise ComposeError("compose_nvidia_smi_reading_invalid", phase)
    return {"usedMiB": int(match.group(1)), "freeMiB": int(match.group(2))}


def _write(path: Path, value: dict) -> None:
    if path.exists():
        raise ComposeError("compose_output_exists", path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


# C6 run record
def select_telemetry(path: Path, job_id: str | None) -> dict:
    """The worker's completion line for the job, or the last one written."""
    try:
        lines = [
            line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
    except OSError as exc:
        raise ComposeError("compose_telemetry_unreadable", path.name) from exc
    records = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ComposeError("compose_telemetry_invalid") from exc
        if isinstance(value, dict) and value.get("schemaVersion") == _TELEMETRY_SCHEMA:
            records.append(value)
    if job_id is not None:
        records = [r for r in records if r.get("jobId") == job_id]
    if not records:
        raise ComposeError("compose_telemetry_missing", job_id or "")
    return records[-1]


def _processing_facts(status: dict) -> dict:
    latest = _field(status, "latestRun")
    if not isinstance(latest, dict):
        raise ComposeError("compose_processing_status_invalid", "latestRun")
    return {
        "videoStatus": _field(status, "videoStatus"),
        "runStatus": _field(latest, "status"),
        "progressPercent": _field(latest, "progressPercent"),
        "attemptCount": _field(latest, "attemptCount"),
        "failureCode": _field(latest, "failureCode"),
        "processingRunId": _field(latest, "processingRunId"),
    }


def _check_policy(
    operator_policy: str, telemetry: dict
) -> None:
    """The launcher policy the operator chose must agree with what the worker saw.

    The launcher resolves Auto before Python starts and hands the worker the
    resolved policy, so a launcher `auto` legitimately reaches provenance as
    `cuda` or `cpu` -- but only ever with an Auto reason. An explicit policy
    must arrive unchanged with its explicit reason.
    """
    worker_policy = telemetry.get("configuredDevicePolicy")
    reason = telemetry.get("deviceResolutionReason")
    if operator_policy == "auto":
        if reason not in AUTO_DEVICE_RESOLUTION_REASONS:
            raise ComposeError(
                "compose_configured_policy_inconsistent",
                f"launcher auto but worker reason {reason!r}",
            )
        return
    if worker_policy != operator_policy:
        raise ComposeError(
            "compose_configured_policy_inconsistent",
            f"launcher {operator_policy} but worker {worker_policy!r}",
        )
    expected = (
        EXPLICIT_CUDA_DEVICE_RESOLUTION_REASON
        if operator_policy == "cuda"
        else EXPLICIT_CPU_DEVICE_RESOLUTION_REASON
    )
    if reason != expected:
        raise ComposeError(
            "compose_configured_policy_inconsistent",
            f"launcher {operator_policy} but worker reason {reason!r}",
        )


def _check_attestation(attestation: dict, telemetry: dict) -> None:
    """The API's own record of the run must agree with the worker's line."""
    pairs = (
        ("actualDevice", telemetry.get("actualDevice"), _field(attestation, "actualDevice")),
        (
            "deviceResolutionReason",
            telemetry.get("deviceResolutionReason"),
            _field(attestation, "deviceResolutionReason"),
        ),
        ("framesProcessed", telemetry.get("framesProcessed"), _field(attestation, "framesProcessed")),
        ("trackCount", telemetry.get("trackCount"), _field(attestation, "tracksCreated")),
        (
            "processingDurationMs",
            telemetry.get("processingDurationMs"),
            _field(attestation, "processingDurationMs"),
        ),
        (
            "verificationStatus",
            telemetry.get("verificationStatus"),
            _field(attestation, "verificationStatus"),
        ),
    )
    for name, ours, theirs in pairs:
        if ours != theirs:
            raise ComposeError("compose_attestation_disagrees", name)
    gpu = _field(attestation, "gpu")
    if isinstance(gpu, dict):
        raw = _field(gpu, "uuid")
        if isinstance(raw, str) and raw:
            if gpu_uuid_digest(raw) != telemetry.get("gpuUuidSha256"):
                raise ComposeError("compose_attestation_disagrees", "gpuUuidSha256")
    elif telemetry.get("gpuUuidSha256") is not None:
        raise ComposeError("compose_attestation_disagrees", "gpu")


def compose_e2e_run(
    *,
    case_id: str,
    telemetry: dict,
    processing_status: dict,
    media_sha256: str,
    configured_device_policy: str,
    nvidia_smi: dict[str, dict[str, int]] | None,
    attestation: dict | None = None,
    failed_processing_status: dict | None = None,
    host_ram_peak_bytes: int | None = None,
) -> dict:
    e2e = _load_tool("build_development_e2e_evidence")
    if case_id not in e2e.REQUIRED_CASES:
        raise ComposeError("compose_case_unknown", case_id)

    _check_policy(configured_device_policy, telemetry)
    if attestation is not None:
        _check_attestation(attestation, telemetry)

    facts = _processing_facts(processing_status)
    if facts["attemptCount"] != telemetry.get("attemptCount"):
        raise ComposeError("compose_processing_status_disagrees", "attemptCount")
    progress = facts["progressPercent"]
    if not isinstance(progress, (int, float)) or isinstance(progress, bool):
        raise ComposeError("compose_processing_status_invalid", "progressPercent")

    ram = telemetry.get("hostRamPeakBytes")
    if host_ram_peak_bytes is not None:
        ram = host_ram_peak_bytes
    if not isinstance(ram, int) or isinstance(ram, bool) or ram <= 0:
        raise ComposeError("compose_host_ram_peak_missing")

    record: dict = {
        "schemaVersion": _RUN_SCHEMA_VERSION,
        "configuredDevicePolicy": configured_device_policy,
        "deviceResolutionReason": telemetry.get("deviceResolutionReason"),
        "actualDevice": telemetry.get("actualDevice"),
        "status": facts["videoStatus"],
        "progressPercent": int(round(progress)),
        "mediaSha256": media_sha256,
        "framesProcessed": telemetry.get("framesProcessed"),
        "detectionCount": telemetry.get("detectionCount"),
        "trackCount": telemetry.get("trackCount"),
        "elapsedSeconds": telemetry.get("processingDurationMs", 0) / 1000.0,
        "hostRamPeakBytes": ram,
        "provenance": {
            "actualDevice": telemetry.get("actualDevice"),
            "deviceResolutionReason": telemetry.get("deviceResolutionReason"),
            "verificationStatus": telemetry.get("verificationStatus"),
        },
    }

    device = str(telemetry.get("actualDevice") or "")
    if device.startswith("cuda:"):
        cuda = telemetry.get("cuda")
        if not isinstance(cuda, dict):
            raise ComposeError("compose_cuda_telemetry_missing")
        block = {
            key: cuda.get(key)
            for key in (
                "maxMemoryAllocatedBytes",
                "maxMemoryReservedBytes",
                "archList",
                "runtimeVersion",
                "mmcvNmsExecutedOnCuda",
            )
        }
        if any(value is None for value in block.values()):
            raise ComposeError(
                "compose_cuda_telemetry_incomplete",
                str(cuda.get("probeError") or "field missing"),
            )
        if nvidia_smi is None:
            raise ComposeError("compose_nvidia_smi_missing")
        digest = telemetry.get("gpuUuidSha256")
        if not isinstance(digest, str):
            raise ComposeError("compose_gpu_identity_missing")
        record["cuda"] = block
        record["nvidiaSmi"] = nvidia_smi
        record["gpuUuidSha256"] = digest

    if case_id == "restart-recovery":
        # A restart re-leases the same job; the attempt count is the proof.
        attempts = telemetry.get("attemptCount")
        if not isinstance(attempts, int) or attempts < 2:
            raise ComposeError("compose_restart_not_exercised")
        record["restartCount"] = attempts - 1

    if case_id == "cuda-oom-recovery":
        # A failed attempt is terminal on the platform, so the OOM lives in an
        # earlier processing run of the same media. Its status record, not a
        # flag, is what says the OOM happened.
        if failed_processing_status is None:
            raise ComposeError("compose_oom_evidence_missing")
        failed = _processing_facts(failed_processing_status)
        if failed["failureCode"] != _OOM_FAILURE_CODE:
            raise ComposeError(
                "compose_oom_not_exercised", str(failed["failureCode"])
            )
        if failed["processingRunId"] == facts["processingRunId"]:
            raise ComposeError("compose_oom_evidence_missing", "same run")
        record["recoveredFromCudaOutOfMemory"] = True

    schema = json.loads(
        (_TOOLS / "windows-cuda-development-e2e-run.schema.json").read_text(
            encoding="utf-8"
        )
    )
    try:
        Draft202012Validator(schema).validate(record)
    except Exception as exc:
        raise ComposeError("compose_run_schema_invalid", _schema_path(exc)) from exc
    # The assembler's own per-record policy, so a refusal happens here.
    try:
        e2e._check_run(case_id, record, e2e.REQUIRED_CASES[case_id], None)
    except e2e.DevelopmentE2eError as exc:
        raise ComposeError(exc.code) from exc
    return record


def _schema_path(exc: Exception) -> str:
    path = getattr(exc, "absolute_path", None)
    return "/".join(str(item) for item in path) if path else ""


# C7 case record
def compose_failure_case(
    *,
    case_id: str,
    operator_diagnostic: str,
    failure_code: str | None = None,
    actual_device: str | None = None,
    device_resolution_reason: str | None = None,
    refused_resolution_reason: str | None = None,
    fallback_logged: bool = False,
    fallback_persisted_in_provenance: bool = False,
    recovered: bool = False,
    attempt_count: int | None = None,
    gpu_uuid: str | None = None,
    driver_version: str | None = None,
) -> dict:
    matrix = _load_tool("build_failure_matrix_evidence")
    declared = matrix.FAILURE_CASES.get(case_id)
    if declared is None:
        raise ComposeError("compose_case_unknown", case_id)

    record: dict = {
        "schemaVersion": _CASE_SCHEMA_VERSION,
        "configuredDevicePolicy": declared["configuredDevicePolicy"],
        "outcome": declared["outcome"],
        "operatorDiagnostic": _RAW_GPU_UUID.sub("GPU-<redacted>", operator_diagnostic),
    }
    if declared["outcome"] == "fail-closed":
        record["processingCompleted"] = False
        record["actualDevice"] = None
        record["deviceResolutionReason"] = None
    else:
        record["actualDevice"] = actual_device
        record["deviceResolutionReason"] = device_resolution_reason
    if failure_code is not None:
        record["failureCode"] = failure_code
    if refused_resolution_reason is not None:
        record["refusedResolutionReason"] = refused_resolution_reason
    if declared["outcome"] == "auto-fallback-cpu":
        record["fallbackLogged"] = fallback_logged
        record["fallbackPersistedInProvenance"] = fallback_persisted_in_provenance
    if declared["outcome"] == "recovered":
        record["recovered"] = recovered
        if attempt_count is not None:
            record["attemptCount"] = attempt_count
    if gpu_uuid is not None:
        # Digested here; the raw UUID is the card's identity and never travels.
        record["gpuUuidSha256"] = gpu_uuid_digest(gpu_uuid)
    if driver_version is not None:
        record["driverVersion"] = driver_version

    schema = json.loads(
        (_TOOLS / "windows-cuda-failure-case.schema.json").read_text(encoding="utf-8")
    )
    try:
        Draft202012Validator(schema).validate(record)
    except Exception as exc:
        raise ComposeError("compose_case_schema_invalid", _schema_path(exc)) from exc
    try:
        matrix._check_case(case_id, record, declared)
    except matrix.FailureMatrixError as exc:
        raise ComposeError(exc.code) from exc
    return record


# Command line
def _add_e2e(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("e2e-run", help="compose one C6 run record")
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--telemetry", type=Path, required=True,
                        help="the worker's diagnostics/attempt-telemetry.jsonl")
    parser.add_argument("--job-id", help="select this job's line; default: the last line")
    parser.add_argument("--processing-status", type=Path, required=True,
                        help="GET /api/videos/{id}/processing saved to a file")
    parser.add_argument("--attestation", type=Path,
                        help="GET /api/processing/runs/{id}/attestation saved to a file")
    parser.add_argument("--media", type=Path, required=True)
    parser.add_argument("--configured-device-policy", choices=("cpu", "cuda", "auto"),
                        required=True, help="the -DevicePolicy given to the launcher")
    parser.add_argument("--nvidia-smi-before", metavar="USED,FREE")
    parser.add_argument("--nvidia-smi-during", metavar="USED,FREE")
    parser.add_argument("--nvidia-smi-after", metavar="USED,FREE")
    parser.add_argument("--failed-processing-status", type=Path,
                        help="cuda-oom-recovery: the earlier run's processing status")
    parser.add_argument("--host-ram-peak-bytes", type=int)
    parser.add_argument("--output", type=Path, required=True)


def _add_case(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("failure-case", help="compose one C7 case record")
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--failure-code")
    parser.add_argument("--diagnostic", help="the observed refusal, verbatim")
    parser.add_argument("--diagnostic-file", type=Path)
    parser.add_argument("--actual-device")
    parser.add_argument("--device-resolution-reason")
    parser.add_argument("--refused-resolution-reason")
    parser.add_argument("--fallback-logged", action="store_true")
    parser.add_argument("--fallback-persisted-in-provenance", action="store_true")
    parser.add_argument("--recovered", action="store_true")
    parser.add_argument("--attempt-count", type=int)
    parser.add_argument("--gpu-uuid", help="raw UUID from nvidia-smi; digested, never stored")
    parser.add_argument("--driver-version")
    parser.add_argument("--output", type=Path, required=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    _add_e2e(sub)
    _add_case(sub)
    args = parser.parse_args()

    try:
        if args.command == "e2e-run":
            telemetry = select_telemetry(args.telemetry, args.job_id)
            readings = (args.nvidia_smi_before, args.nvidia_smi_during, args.nvidia_smi_after)
            nvidia_smi = None
            if any(readings):
                nvidia_smi = {
                    phase: _smi_reading(value, phase)
                    for phase, value in zip(("before", "during", "after"), readings)
                }
            record = compose_e2e_run(
                case_id=args.case_id,
                telemetry=telemetry,
                processing_status=_read_json(
                    args.processing_status, "compose_processing_status"
                ),
                media_sha256=_sha256_file(args.media),
                configured_device_policy=args.configured_device_policy,
                nvidia_smi=nvidia_smi,
                attestation=(
                    None
                    if args.attestation is None
                    else _read_json(args.attestation, "compose_attestation")
                ),
                failed_processing_status=(
                    None
                    if args.failed_processing_status is None
                    else _read_json(
                        args.failed_processing_status, "compose_processing_status"
                    )
                ),
                host_ram_peak_bytes=args.host_ram_peak_bytes,
            )
        else:
            if args.diagnostic_file is not None:
                try:
                    diagnostic = args.diagnostic_file.read_text(encoding="utf-8-sig")
                except OSError as exc:
                    raise ComposeError("compose_diagnostic_unreadable") from exc
            else:
                diagnostic = args.diagnostic or ""
            record = compose_failure_case(
                case_id=args.case_id,
                operator_diagnostic=diagnostic.strip()[-2000:],
                failure_code=args.failure_code,
                actual_device=args.actual_device,
                device_resolution_reason=args.device_resolution_reason,
                refused_resolution_reason=args.refused_resolution_reason,
                fallback_logged=args.fallback_logged,
                fallback_persisted_in_provenance=args.fallback_persisted_in_provenance,
                recovered=args.recovered,
                attempt_count=args.attempt_count,
                gpu_uuid=args.gpu_uuid,
                driver_version=args.driver_version,
            )
        _write(args.output, record)
    except ComposeError as exc:
        print(
            json.dumps(
                {"ok": False, "code": exc.code, "detail": exc.detail}, sort_keys=True
            )
        )
        return 2

    print(
        json.dumps(
            {"ok": True, "output": str(args.output), "caseId": args.case_id},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
