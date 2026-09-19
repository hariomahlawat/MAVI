"""The composer writes only records the assemblers will accept, from artefacts.

Every field in a composed record traces to something the host produced: the
worker's telemetry line, the API's saved responses, the media file, the
operator's nvidia-smi readings. These tests are about the two properties that
matter: an inconsistent set of inputs is refused with the assembler's own
code, and the record that does come out is one the assembler accepts as-is.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from uuid import UUID

import pytest


TOOLS = Path(__file__).resolve().parents[3] / "tools" / "vision"
TOOL = TOOLS / "compose_windows_cuda_evidence.py"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load("compose_windows_cuda_evidence")
E2E = _load("build_development_e2e_evidence")
MATRIX = _load("build_failure_matrix_evidence")
DIGEST = _load("host_gpu_digest")

_JOB = str(UUID(int=11))
_RUN = str(UUID(int=12))
_RAW_UUID = "GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_MEDIA_SHA = "9f" * 32


def _telemetry(**overrides) -> dict:
    value = {
        "schemaVersion": "mavi-attempt-telemetry-v1",
        "recordedAtUtc": "2026-09-19T15:00:00Z",
        "jobId": _JOB,
        "attemptCount": 1,
        "framesProcessed": 3600,
        "trackCount": 57,
        "detectionCount": 8421,
        "processingDurationMs": 96400,
        "configuredDevicePolicy": "cuda",
        "actualDevice": "cuda:0",
        "deviceResolutionReason": "explicit_cuda",
        "verificationStatus": "unverified",
        "runtimeVariant": "windows-x86_64-cuda",
        "gpuUuidSha256": DIGEST.gpu_uuid_digest(_RAW_UUID),
        "driverVersion": "576.83",
        "hostRamPeakBytes": 4 * 1024**3,
        "cuda": {
            "device": "cuda:0",
            "maxMemoryAllocatedBytes": 1824 * 1024 * 1024,
            "maxMemoryReservedBytes": 2048 * 1024 * 1024,
            "archList": ["sm_75"],
            "runtimeVersion": "12.4",
            "mmcvNmsExecutedOnCuda": True,
            "probeError": None,
        },
    }
    value.update(overrides)
    return value


def _cpu_telemetry() -> dict:
    return _telemetry(
        configuredDevicePolicy="cpu",
        actualDevice="cpu",
        deviceResolutionReason="explicit_cpu",
        runtimeVariant="windows-x86_64-cpu",
        gpuUuidSha256=None,
        driverVersion=None,
        cuda=None,
    )


def _status(**overrides) -> dict:
    """GET /api/videos/{id}/processing as ASP.NET serialises it: camelCase."""
    latest = {
        "processingRunId": _RUN,
        "status": "Completed",
        "pipeline": "phase1-detection-tracking",
        "pipelineVersion": "phase1-v1",
        "workerId": "c6-explicit-cuda-01",
        "progressPercent": 100.0,
        "attemptCount": 1,
        "failureCode": None,
    }
    latest.update(overrides.pop("latest", {}))
    value = {"videoStatus": "Processed", "latestRun": latest}
    value.update(overrides)
    return value


def _attestation(**overrides) -> dict:
    value = {
        "processingRunId": _RUN,
        "verificationStatus": "unverified",
        "configuredDevicePolicy": "cuda",
        "deviceResolutionReason": "explicit_cuda",
        "actualDevice": "cuda:0",
        "gpu": {"name": "NVIDIA GeForce GTX 1650 Ti", "uuid": _RAW_UUID},
        "framesProcessed": 3600,
        "tracksCreated": 57,
        "processingDurationMs": 96400,
    }
    value.update(overrides)
    return value


_SMI = {
    "before": {"usedMiB": 312, "freeMiB": 3784},
    "during": {"usedMiB": 2400, "freeMiB": 1696},
    "after": {"usedMiB": 330, "freeMiB": 3766},
}


def _compose(case_id: str = "explicit-cuda", **overrides) -> dict:
    kwargs = {
        "case_id": case_id,
        "telemetry": _telemetry(),
        "processing_status": _status(),
        "media_sha256": _MEDIA_SHA,
        "configured_device_policy": "cuda",
        "nvidia_smi": _SMI,
        "attestation": _attestation(),
    }
    kwargs.update(overrides)
    return MODULE.compose_e2e_run(**kwargs)


def _code(excinfo) -> str:
    return excinfo.value.code


# C6 run records
def test_an_explicit_cuda_run_is_composed_from_the_artefacts():
    record = _compose()

    assert record["schemaVersion"] == "mavi-windows-cuda-development-e2e-run-v1"
    assert record["configuredDevicePolicy"] == "cuda"
    assert record["actualDevice"] == "cuda:0"
    assert record["status"] == "Processed"
    assert record["progressPercent"] == 100
    assert record["mediaSha256"] == _MEDIA_SHA
    assert record["framesProcessed"] == 3600
    assert record["detectionCount"] == 8421
    assert record["trackCount"] == 57
    assert record["elapsedSeconds"] == pytest.approx(96.4)
    assert record["hostRamPeakBytes"] == 4 * 1024**3
    assert record["provenance"] == {
        "actualDevice": "cuda:0",
        "deviceResolutionReason": "explicit_cuda",
        "verificationStatus": "unverified",
    }
    assert record["cuda"] == {
        "maxMemoryAllocatedBytes": 1824 * 1024 * 1024,
        "maxMemoryReservedBytes": 2048 * 1024 * 1024,
        "archList": ["sm_75"],
        "runtimeVersion": "12.4",
        "mmcvNmsExecutedOnCuda": True,
    }
    assert record["nvidiaSmi"] == _SMI
    assert record["gpuUuidSha256"] == DIGEST.gpu_uuid_digest(_RAW_UUID)
    assert _RAW_UUID not in json.dumps(record)


def test_the_composed_record_is_what_the_assembler_accepts():
    """Round trip: the record must pass the assembler's own per-case check."""
    record = _compose()

    checked = E2E._check_run(
        "explicit-cuda", record, E2E.REQUIRED_CASES["explicit-cuda"], None
    )

    assert checked["caseId"] == "explicit-cuda"
    assert checked["cuda"]["mmcvNmsExecutedOnCuda"] is True


def test_a_launcher_auto_run_keeps_the_operator_policy_with_the_worker_reason():
    """The launcher resolves Auto before Python starts and hands over `cuda`.

    The record states what the operator configured and the reason the worker
    recorded; only an Auto reason may accompany a launcher `auto`.
    """
    record = _compose(
        "auto-cuda",
        telemetry=_telemetry(deviceResolutionReason="cuda_selected"),
        attestation=_attestation(deviceResolutionReason="cuda_selected"),
        configured_device_policy="auto",
    )

    assert record["configuredDevicePolicy"] == "auto"
    assert record["deviceResolutionReason"] == "cuda_selected"
    E2E._check_run("auto-cuda", record, E2E.REQUIRED_CASES["auto-cuda"], None)


def test_a_launcher_auto_with_an_explicit_reason_is_inconsistent():
    with pytest.raises(MODULE.ComposeError) as excinfo:
        _compose("auto-cuda", configured_device_policy="auto")

    assert _code(excinfo) == "compose_configured_policy_inconsistent"


def test_an_explicit_policy_the_worker_did_not_see_is_inconsistent():
    with pytest.raises(MODULE.ComposeError) as excinfo:
        _compose(
            "explicit-cuda",
            telemetry=_cpu_telemetry(),
            attestation=None,
            nvidia_smi=None,
        )

    assert _code(excinfo) == "compose_configured_policy_inconsistent"


def test_an_explicit_cpu_run_carries_no_device_fields():
    record = _compose(
        "explicit-cpu",
        telemetry=_cpu_telemetry(),
        configured_device_policy="cpu",
        nvidia_smi=None,
        attestation=None,
    )

    assert record["actualDevice"] == "cpu"
    assert "cuda" not in record
    assert "nvidiaSmi" not in record
    assert "gpuUuidSha256" not in record
    E2E._check_run("explicit-cpu", record, E2E.REQUIRED_CASES["explicit-cpu"], None)


def test_incomplete_device_telemetry_is_refused_with_its_probe_error():
    telemetry = _telemetry()
    telemetry["cuda"]["maxMemoryAllocatedBytes"] = None
    telemetry["cuda"]["probeError"] = "counter_read_failed:RuntimeError"

    with pytest.raises(MODULE.ComposeError) as excinfo:
        _compose(telemetry=telemetry)

    assert _code(excinfo) == "compose_cuda_telemetry_incomplete"
    assert "counter_read_failed" in excinfo.value.detail


def test_a_cuda_run_without_nvidia_smi_readings_is_refused():
    with pytest.raises(MODULE.ComposeError) as excinfo:
        _compose(nvidia_smi=None)

    assert _code(excinfo) == "compose_nvidia_smi_missing"


def test_a_cuda_run_whose_telemetry_lacks_the_device_block_is_refused():
    with pytest.raises(MODULE.ComposeError) as excinfo:
        _compose(telemetry=_telemetry(cuda=None))

    assert _code(excinfo) == "compose_cuda_telemetry_missing"


@pytest.mark.parametrize(
    "field, value",
    [
        ("framesProcessed", 3599),
        ("tracksCreated", 56),
        ("actualDevice", "cpu"),
        ("processingDurationMs", 1),
        ("verificationStatus", "verified"),
    ],
)
def test_an_attestation_that_disagrees_with_the_worker_is_refused(field, value):
    with pytest.raises(MODULE.ComposeError) as excinfo:
        _compose(attestation=_attestation(**{field: value}))

    assert _code(excinfo) == "compose_attestation_disagrees"


def test_an_attestation_naming_another_card_is_refused():
    other = _attestation(gpu={"uuid": "GPU-ffffffff-0000-0000-0000-000000000000"})

    with pytest.raises(MODULE.ComposeError) as excinfo:
        _compose(attestation=other)

    assert _code(excinfo) == "compose_attestation_disagrees"
    assert excinfo.value.detail == "gpuUuidSha256"


def test_a_processing_status_from_another_attempt_is_refused():
    with pytest.raises(MODULE.ComposeError) as excinfo:
        _compose(processing_status=_status(latest={"attemptCount": 2}))

    assert _code(excinfo) == "compose_processing_status_disagrees"


def test_a_run_that_did_not_reach_processed_is_refused_by_the_assembler_rule():
    with pytest.raises(MODULE.ComposeError) as excinfo:
        _compose(processing_status=_status(videoStatus="Failed"))

    assert _code(excinfo) == "e2e_run_not_processed:explicit-cuda"


def test_pascal_case_api_fields_are_read_too():
    status = {
        "VideoStatus": "Processed",
        "LatestRun": {
            "ProcessingRunId": _RUN,
            "Status": "Completed",
            "ProgressPercent": 100,
            "AttemptCount": 1,
            "FailureCode": None,
        },
    }

    record = _compose(processing_status=status)

    assert record["status"] == "Processed"


def test_restart_recovery_derives_the_restart_count_from_the_attempt():
    """A restart re-leases the same job; attempt two is the proof of one restart."""
    record = _compose(
        "restart-recovery",
        telemetry=_telemetry(attemptCount=2),
        processing_status=_status(latest={"attemptCount": 2}),
    )

    assert record["restartCount"] == 1
    E2E._check_run(
        "restart-recovery", record, E2E.REQUIRED_CASES["restart-recovery"], None
    )


def test_restart_recovery_on_a_first_attempt_is_not_a_restart():
    with pytest.raises(MODULE.ComposeError) as excinfo:
        _compose("restart-recovery")

    assert _code(excinfo) == "compose_restart_not_exercised"


def test_oom_recovery_is_proven_by_the_failed_runs_own_status():
    failed = _status(
        videoStatus="Failed",
        latest={
            "processingRunId": str(UUID(int=99)),
            "status": "Failed",
            "progressPercent": 41.5,
            "failureCode": "vision_gpu_out_of_memory",
        },
    )

    record = _compose("cuda-oom-recovery", failed_processing_status=failed)

    assert record["recoveredFromCudaOutOfMemory"] is True
    E2E._check_run(
        "cuda-oom-recovery", record, E2E.REQUIRED_CASES["cuda-oom-recovery"], None
    )


def test_oom_recovery_without_the_failed_run_is_refused():
    with pytest.raises(MODULE.ComposeError) as excinfo:
        _compose("cuda-oom-recovery")

    assert _code(excinfo) == "compose_oom_evidence_missing"


def test_oom_recovery_from_a_run_that_failed_otherwise_is_refused():
    failed = _status(
        videoStatus="Failed",
        latest={
            "processingRunId": str(UUID(int=99)),
            "status": "Failed",
            "failureCode": "vision_processing_failed",
        },
    )

    with pytest.raises(MODULE.ComposeError) as excinfo:
        _compose("cuda-oom-recovery", failed_processing_status=failed)

    assert _code(excinfo) == "compose_oom_not_exercised"


def test_oom_recovery_cannot_cite_the_recovered_run_as_the_failed_one():
    failed = _status(latest={"failureCode": "vision_gpu_out_of_memory"})

    with pytest.raises(MODULE.ComposeError) as excinfo:
        _compose("cuda-oom-recovery", failed_processing_status=failed)

    assert _code(excinfo) == "compose_oom_evidence_missing"


def test_a_missing_host_ram_peak_is_refused_unless_supplied():
    telemetry = _telemetry(hostRamPeakBytes=None)

    with pytest.raises(MODULE.ComposeError) as excinfo:
        _compose(telemetry=telemetry)
    assert _code(excinfo) == "compose_host_ram_peak_missing"

    record = _compose(telemetry=telemetry, host_ram_peak_bytes=123456789)
    assert record["hostRamPeakBytes"] == 123456789


def test_an_unknown_case_is_refused():
    with pytest.raises(MODULE.ComposeError) as excinfo:
        _compose("looks-good-to-me")

    assert _code(excinfo) == "compose_case_unknown"


# Telemetry selection
def test_the_last_line_is_selected_by_default_and_a_job_by_id(tmp_path):
    path = tmp_path / "attempt-telemetry.jsonl"
    first = _telemetry(jobId=str(UUID(int=1)), attemptCount=1)
    second = _telemetry(jobId=str(UUID(int=2)), attemptCount=1)
    path.write_text(
        json.dumps(first) + "\n" + json.dumps(second) + "\n", encoding="utf-8"
    )

    assert MODULE.select_telemetry(path, None)["jobId"] == str(UUID(int=2))
    assert MODULE.select_telemetry(path, str(UUID(int=1)))["jobId"] == str(UUID(int=1))


def test_a_job_with_several_attempts_yields_its_latest_line(tmp_path):
    path = tmp_path / "attempt-telemetry.jsonl"
    path.write_text(
        json.dumps(_telemetry(attemptCount=1))
        + "\n"
        + json.dumps(_telemetry(attemptCount=2))
        + "\n",
        encoding="utf-8",
    )

    assert MODULE.select_telemetry(path, _JOB)["attemptCount"] == 2


def test_a_missing_job_is_refused(tmp_path):
    path = tmp_path / "attempt-telemetry.jsonl"
    path.write_text(json.dumps(_telemetry()) + "\n", encoding="utf-8")

    with pytest.raises(MODULE.ComposeError) as excinfo:
        MODULE.select_telemetry(path, str(UUID(int=42)))

    assert _code(excinfo) == "compose_telemetry_missing"


def test_lines_of_another_schema_are_ignored(tmp_path):
    path = tmp_path / "attempt-telemetry.jsonl"
    path.write_text(
        json.dumps({"schemaVersion": "something-else", "jobId": _JOB})
        + "\n"
        + json.dumps(_telemetry())
        + "\n",
        encoding="utf-8",
    )

    assert MODULE.select_telemetry(path, None)["schemaVersion"] == (
        "mavi-attempt-telemetry-v1"
    )


# nvidia-smi readings
@pytest.mark.parametrize("text", ["312, 3784", "312,3784", " 312 , 3784 "])
def test_an_nvidia_smi_line_is_parsed_as_used_then_free(text):
    assert MODULE._smi_reading(text, "before") == {"usedMiB": 312, "freeMiB": 3784}


@pytest.mark.parametrize("text", ["312 MiB, 3784 MiB", "3784", "", "a,b"])
def test_a_malformed_nvidia_smi_line_is_refused(text):
    with pytest.raises(MODULE.ComposeError) as excinfo:
        MODULE._smi_reading(text, "during")

    assert _code(excinfo) == "compose_nvidia_smi_reading_invalid"


# C7 case records
def test_a_fail_closed_case_states_that_nothing_ran():
    record = MODULE.compose_failure_case(
        case_id="explicit-cuda-pack-absent",
        failure_code="launch_runtime_pack_not_installed",
        operator_diagnostic="mavi_launch_failed:launch_runtime_pack_not_installed: ...",
    )

    assert record["configuredDevicePolicy"] == "cuda"
    assert record["outcome"] == "fail-closed"
    assert record["processingCompleted"] is False
    assert record["actualDevice"] is None
    assert record["deviceResolutionReason"] is None
    MATRIX._check_case(
        "explicit-cuda-pack-absent", record, MATRIX.FAILURE_CASES["explicit-cuda-pack-absent"]
    )


def test_a_fail_closed_case_with_another_cases_code_is_refused():
    with pytest.raises(MODULE.ComposeError) as excinfo:
        MODULE.compose_failure_case(
            case_id="explicit-cuda-pack-absent",
            failure_code="launch_cuda_policy_requires_cuda_pack",
            operator_diagnostic="wrong code",
        )

    assert _code(excinfo) == "failure_case_failure_code_unexpected:explicit-cuda-pack-absent"


def test_a_permitted_fallback_case_is_composed_from_its_flags():
    record = MODULE.compose_failure_case(
        case_id="auto-pack-absent",
        actual_device="cpu",
        device_resolution_reason="cuda_pack_absent",
        fallback_logged=True,
        fallback_persisted_in_provenance=True,
        operator_diagnostic="Development Auto selected CPU: cuda_pack_absent",
    )

    assert record["outcome"] == "auto-fallback-cpu"
    assert "failureCode" not in record
    MATRIX._check_case("auto-pack-absent", record, MATRIX.FAILURE_CASES["auto-pack-absent"])


def test_an_unlogged_fallback_is_refused():
    with pytest.raises(MODULE.ComposeError) as excinfo:
        MODULE.compose_failure_case(
            case_id="auto-pack-absent",
            actual_device="cpu",
            device_resolution_reason="cuda_pack_absent",
            fallback_persisted_in_provenance=True,
            operator_diagnostic="no log line",
        )

    assert _code(excinfo) in {
        "compose_case_schema_invalid",
        "failure_case_fallback_not_logged:auto-pack-absent",
    }


def test_a_recovered_case_digests_the_card_and_keeps_no_raw_uuid():
    record = MODULE.compose_failure_case(
        case_id="worker-restart-recovered",
        failure_code="vision_inference_watchdog_expired",
        actual_device="cuda:0",
        device_resolution_reason="explicit_cuda",
        recovered=True,
        attempt_count=2,
        gpu_uuid=_RAW_UUID,
        driver_version="576.83",
        operator_diagnostic=f"worker exited 70 on {_RAW_UUID}; restarted; attempt 2 Processed",
    )

    assert record["gpuUuidSha256"] == DIGEST.gpu_uuid_digest(_RAW_UUID)
    assert _RAW_UUID not in json.dumps(record)
    assert "GPU-<redacted>" in record["operatorDiagnostic"]
    MATRIX._check_case(
        "worker-restart-recovered",
        record,
        MATRIX.FAILURE_CASES["worker-restart-recovered"],
        gpu_uuid_sha256=DIGEST.gpu_uuid_digest(_RAW_UUID),
    )


def test_a_recovery_that_never_retried_is_refused():
    with pytest.raises(MODULE.ComposeError) as excinfo:
        MODULE.compose_failure_case(
            case_id="cuda-out-of-memory-recovered",
            failure_code="vision_gpu_out_of_memory",
            actual_device="cuda:0",
            device_resolution_reason="explicit_cuda",
            recovered=True,
            attempt_count=1,
            gpu_uuid=_RAW_UUID,
            driver_version="576.83",
            operator_diagnostic="one attempt",
        )

    assert _code(excinfo) in {
        "compose_case_schema_invalid",
        "failure_case_recovery_not_exercised:cuda-out-of-memory-recovered",
    }


def test_the_unknown_reason_case_records_what_was_refused():
    record = MODULE.compose_failure_case(
        case_id="auto-unknown-reason-refused",
        failure_code="device_resolution_reason_unknown",
        refused_resolution_reason="cuda_because_i_said_so",
        operator_diagnostic="MAVI_DEVICE_RESOLUTION_REASON is invalid",
    )

    assert record["refusedResolutionReason"] == "cuda_because_i_said_so"
    MATRIX._check_case(
        "auto-unknown-reason-refused",
        record,
        MATRIX.FAILURE_CASES["auto-unknown-reason-refused"],
    )


def test_an_unknown_failure_case_is_refused():
    with pytest.raises(MODULE.ComposeError) as excinfo:
        MODULE.compose_failure_case(
            case_id="made-up", failure_code="x", operator_diagnostic="y"
        )

    assert _code(excinfo) == "compose_case_unknown"


# Command line
def _run_cli(*args: str) -> tuple[int, dict]:
    completed = subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, json.loads(completed.stdout.strip().splitlines()[-1])


def test_the_cli_composes_a_run_and_refuses_to_overwrite_it(tmp_path):
    telemetry = tmp_path / "attempt-telemetry.jsonl"
    telemetry.write_text(json.dumps(_telemetry()) + "\n", encoding="utf-8")
    status = tmp_path / "status.json"
    status.write_text(json.dumps(_status()), encoding="utf-8")
    media = tmp_path / "2min.mp4"
    media.write_bytes(b"not really a video")
    output = tmp_path / "run-explicit-cuda.json"

    code, result = _run_cli(
        "e2e-run",
        "--case-id", "explicit-cuda",
        "--telemetry", str(telemetry),
        "--processing-status", str(status),
        "--media", str(media),
        "--configured-device-policy", "cuda",
        "--nvidia-smi-before", "312, 3784",
        "--nvidia-smi-during", "2400, 1696",
        "--nvidia-smi-after", "330, 3766",
        "--output", str(output),
    )

    assert code == 0, result
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["mediaSha256"] == MODULE._sha256_file(media)
    assert written["nvidiaSmi"]["during"] == {"usedMiB": 2400, "freeMiB": 1696}

    code, result = _run_cli(
        "e2e-run",
        "--case-id", "explicit-cuda",
        "--telemetry", str(telemetry),
        "--processing-status", str(status),
        "--media", str(media),
        "--configured-device-policy", "cuda",
        "--nvidia-smi-before", "312, 3784",
        "--nvidia-smi-during", "2400, 1696",
        "--nvidia-smi-after", "330, 3766",
        "--output", str(output),
    )

    assert code == 2
    assert result["code"] == "compose_output_exists"


def test_the_cli_composes_a_case_from_a_diagnostic_file(tmp_path):
    diagnostic = tmp_path / "refusal.txt"
    diagnostic.write_text(
        "mavi_launch_failed:launch_runtime_pack_not_installed: MAVI Vision Runtime "
        "Pack for requested device policy 'cuda' is not installed at 'C:\\...'.\n",
        encoding="utf-8",
    )
    output = tmp_path / "case-explicit-cuda-pack-absent.json"

    code, result = _run_cli(
        "failure-case",
        "--case-id", "explicit-cuda-pack-absent",
        "--failure-code", "launch_runtime_pack_not_installed",
        "--diagnostic-file", str(diagnostic),
        "--output", str(output),
    )

    assert code == 0, result
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["processingCompleted"] is False
    assert written["operatorDiagnostic"].startswith("mavi_launch_failed")


def test_the_cli_refuses_with_the_assemblers_code(tmp_path):
    code, result = _run_cli(
        "failure-case",
        "--case-id", "explicit-cuda-pack-absent",
        "--failure-code", "launch_cuda_policy_requires_cuda_pack",
        "--diagnostic", "wrong",
        "--output", str(tmp_path / "case.json"),
    )

    assert code == 2
    assert result["code"].startswith("failure_case_failure_code_unexpected")
    assert not (tmp_path / "case.json").exists()


def test_a_telemetry_line_whose_policy_contradicts_its_own_reason_is_refused():
    """A tampered or inconsistent line: explicit reason, some other policy.

    Provenance validation forbids this pairing inside the worker, so a line
    carrying it did not come from an honest completion; the composer must not
    launder it into a record just because the reason happens to match.
    """
    with pytest.raises(MODULE.ComposeError) as excinfo:
        _compose(telemetry=_telemetry(configuredDevicePolicy="auto"))

    assert _code(excinfo) == "compose_configured_policy_inconsistent"
    assert "worker 'auto'" in excinfo.value.detail
