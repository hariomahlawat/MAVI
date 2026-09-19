"""C6 must produce checkable evidence, not a report that it went well.

The phase asks the Development laptop to prove eight things about real runs.
Every negative case here is the assembler refusing a bundle that claims one of
them without having done it -- most importantly the silent GPU-to-CPU fallback
that C6 requirement 8 forbids, which is precisely the failure that looks like
success in a log.

Every record is synthesised in-test; nothing depends on repository state or on
a GPU being present.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


TOOL_PATH = (
    Path(__file__).resolve().parents[3]
    / "tools"
    / "vision"
    / "build_development_e2e_evidence.py"
)

_SOURCE_HEAD_SHA = "426195d4e1b0a9f2c3d4e5f60718293a4b5c6d7e"
_CAPTURED_AT = "2026-09-18T06:22:41Z"
_OPERATOR = "mavi-dev-workstation-01"
_MEDIA_SHA = "9f" * 32
_GPU_DIGEST = "cb70319f" + "0" * 56


def _load():
    spec = importlib.util.spec_from_file_location(
        "build_development_e2e_evidence", TOOL_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load()


def _hardware_evidence(**overrides) -> dict:
    """A faithful C4 record, including a self-digest that actually recomputes."""
    value = {
        "schemaVersion": "mavi-windows-cuda-development-evidence-v2",
        "developmentEvidence": {
            "hostObservationSha256": "ab" * 32,
            "evidenceBundleSha256": "",
            "sourceHeadSha": _SOURCE_HEAD_SHA,
            "capturedAtUtc": "2026-09-18T04:11:52Z",
            "operatorReference": _OPERATOR,
        },
        "variantPatch": {
            "status": "qualified-development-hardware",
            "resolvedConfigSha256": "3d" * 32,
        },
        "corroboration": {
            "gpuUuidSha256": _GPU_DIGEST,
            "deviceIndex": 0,
            "targetArchitecture": "sm_75",
            "torchCudaRuntimeVersion": "12.4",
        },
    }
    value.update(overrides)
    value["developmentEvidence"]["evidenceBundleSha256"] = hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    return value


def _run(case_id: str, **overrides) -> dict:
    expectation = MODULE.REQUIRED_CASES[case_id]
    on_cuda = expectation["cuda"]
    value: dict = {
        "schemaVersion": "mavi-windows-cuda-development-e2e-run-v1",
        "configuredDevicePolicy": expectation["configuredDevicePolicy"],
        "deviceResolutionReason": expectation["deviceResolutionReason"],
        "actualDevice": "cuda:0" if on_cuda else "cpu",
        "status": "Processed",
        "progressPercent": 100,
        "mediaSha256": _MEDIA_SHA,
        "framesProcessed": 3600,
        "detectionCount": 8421,
        "trackCount": 57,
        "elapsedSeconds": 96.4 if on_cuda else 612.7,
        "hostRamPeakBytes": 4 * 1024**3,
        "provenance": {
            "actualDevice": "cuda:0" if on_cuda else "cpu",
            "deviceResolutionReason": expectation["deviceResolutionReason"],
            "verificationStatus": "unverified",
        },
    }
    if on_cuda:
        value["gpuUuidSha256"] = _GPU_DIGEST
        value["cuda"] = {
            "maxMemoryAllocatedBytes": 1824 * 1024 * 1024,
            "maxMemoryReservedBytes": 2048 * 1024 * 1024,
            "archList": ["sm_75"],
            "runtimeVersion": "12.4",
            "mmcvNmsExecutedOnCuda": True,
        }
        value["nvidiaSmi"] = {
            "before": {"freeMiB": 11000, "usedMiB": 264},
            "during": {"freeMiB": 8800, "usedMiB": 2464},
            "after": {"freeMiB": 10950, "usedMiB": 314},
        }
    if case_id == "cuda-oom-recovery":
        value["recoveredFromCudaOutOfMemory"] = True
    if case_id == "restart-recovery":
        value["restartCount"] = 1
    value.update(overrides)
    return value


def _write(root: Path, name: str, value: object) -> Path:
    path = root / name
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def _build(
    tmp_path: Path,
    *,
    hardware: dict | None = None,
    runs: dict[str, dict] | None = None,
    drop: str | None = None,
    source_head_sha: str = _SOURCE_HEAD_SHA,
    captured_at_utc: str = _CAPTURED_AT,
    operator_reference: str = _OPERATOR,
) -> dict:
    records = {case: _run(case) for case in MODULE.REQUIRED_CASES}
    if runs:
        records.update(runs)
    if drop is not None:
        records.pop(drop, None)
    return MODULE.build_e2e_evidence(
        development_evidence=_write(
            tmp_path,
            "hardware.json",
            _hardware_evidence() if hardware is None else hardware,
        ),
        runs={
            case: _write(tmp_path, f"run-{case}.json", record)
            for case, record in records.items()
        },
        source_head_sha=source_head_sha,
        captured_at_utc=captured_at_utc,
        operator_reference=operator_reference,
    )


def _code(excinfo) -> str:
    return excinfo.value.code


def test_a_complete_run_matrix_is_accepted(tmp_path):
    evidence = _build(tmp_path)

    assert evidence["schemaVersion"] == "mavi-windows-cuda-development-e2e-v1"
    assert {run["caseId"] for run in evidence["runs"]} == set(
        MODULE.REQUIRED_CASES
    )
    assert evidence["developmentE2e"]["sourceHeadSha"] == _SOURCE_HEAD_SHA
    assert "No Production threshold" in evidence["characterisationOnly"]
    assert "asserts nothing about Production" in evidence["note"].replace(
        "\n", " "
    )


def test_timing_is_recorded_as_characterisation_not_a_threshold(tmp_path):
    evidence = _build(tmp_path)
    by_case = {run["caseId"]: run for run in evidence["runs"]}

    assert by_case["explicit-cuda"]["framesPerSecond"] > 0
    assert by_case["explicit-cpu"]["framesPerSecond"] > 0
    # Both are reported; neither is compared against a bound by this tool.
    assert "Production threshold" in evidence["characterisationOnly"]


@pytest.mark.parametrize("case", sorted(MODULE.REQUIRED_CASES))
def test_every_required_case_must_be_present(tmp_path, case):
    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, drop=case)

    assert _code(excinfo) == "e2e_required_case_missing:" + case


def test_an_unrecognised_case_is_refused(tmp_path):
    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        MODULE.build_e2e_evidence(
            development_evidence=_write(
                tmp_path, "hardware.json", _hardware_evidence()
            ),
            runs={
                **{
                    case: _write(tmp_path, f"run-{case}.json", _run(case))
                    for case in MODULE.REQUIRED_CASES
                },
                "looks-good-to-me": _write(
                    tmp_path, "extra.json", _run("explicit-cuda")
                ),
            },
            source_head_sha=_SOURCE_HEAD_SHA,
            captured_at_utc=_CAPTURED_AT,
            operator_reference=_OPERATOR,
        )

    assert _code(excinfo) == "e2e_unknown_case:looks-good-to-me"


def test_a_cuda_case_that_actually_ran_on_cpu_is_refused(tmp_path):
    """C6 requirement 8: the fallback that looks like success in a log.

    Note this one is caught here, not by the shared wire contract: that
    function proves `explicit_cuda` implies the *policy* was cuda, and leaves
    "explicit CUDA never becomes CPU" to the runtime layers that enforce it
    (`supervisor`, `provenance`, the launcher). A C6 case claiming CUDA while
    reporting `cpu` has to be refused wherever it is noticed.
    """
    run = _run("explicit-cuda")
    run["actualDevice"] = "cpu"
    run["provenance"]["actualDevice"] = "cpu"

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"explicit-cuda": run})

    assert _code(excinfo) == "e2e_run_cuda_fallback:explicit-cuda"


def test_auto_claiming_cuda_while_running_on_cpu_is_refused(tmp_path):
    run = _run("auto-cuda")
    run["actualDevice"] = "cpu"
    run["provenance"]["actualDevice"] = "cpu"

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"auto-cuda": run})

    assert _code(excinfo).startswith("e2e_run_device_relationship_invalid")


def test_auto_that_fell_back_to_cpu_does_not_satisfy_the_cuda_case(tmp_path):
    """A legitimate fallback is still not evidence that Auto chose CUDA."""
    run = _run("auto-cuda")
    run["actualDevice"] = "cpu"
    run["deviceResolutionReason"] = "cuda_device_unavailable"
    run["provenance"]["actualDevice"] = "cpu"
    run["provenance"]["deviceResolutionReason"] = "cuda_device_unavailable"
    del run["cuda"]
    del run["nvidiaSmi"]

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"auto-cuda": run})

    assert _code(excinfo) == "e2e_run_resolution_reason_mismatch:auto-cuda"


def test_a_reason_outside_the_closed_vocabulary_is_refused(tmp_path):
    run = _run("explicit-cuda", deviceResolutionReason="cuda_looked_fine")

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"explicit-cuda": run})

    assert "device_resolution_reason_unknown" in _code(excinfo)


def test_a_cuda_run_without_on_device_native_ops_is_refused(tmp_path):
    run = _run("explicit-cuda")
    run["cuda"]["mmcvNmsExecutedOnCuda"] = False

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"explicit-cuda": run})

    assert _code(excinfo) == "e2e_run_native_ops_not_executed:explicit-cuda"


def test_a_cuda_run_the_allocator_never_saw_is_refused(tmp_path):
    run = _run("explicit-cuda")
    run["cuda"]["maxMemoryAllocatedBytes"] = 0

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"explicit-cuda": run})

    assert _code(excinfo) == "e2e_run_no_device_allocation:explicit-cuda"


def test_a_cuda_run_with_no_device_memory_in_use_is_refused(tmp_path):
    """Work on the device shows up in nvidia-smi while it is running."""
    run = _run("explicit-cuda")
    run["nvidiaSmi"]["during"] = {"freeMiB": 11000, "usedMiB": 264}

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"explicit-cuda": run})

    assert _code(excinfo) == "e2e_run_no_device_utilisation:explicit-cuda"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    (
        ("status", "Failed", "e2e_run_not_processed:explicit-cuda"),
        ("progressPercent", 99, "e2e_run_incomplete:explicit-cuda"),
        ("detectionCount", 0, "e2e_run_no_detections:explicit-cuda"),
        ("framesProcessed", 0, "e2e_run_no_frames:explicit-cuda"),
        ("elapsedSeconds", 0, "e2e_run_timing_missing:explicit-cuda"),
        ("mediaSha256", "not-a-digest", "e2e_run_media_identity_missing:explicit-cuda"),
        ("hostRamPeakBytes", 0, "e2e_run_host_ram_missing:explicit-cuda"),
    ),
)
def test_an_incomplete_run_is_refused(tmp_path, field, value, code):
    run = _run("explicit-cuda", **{field: value})

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"explicit-cuda": run})

    assert _code(excinfo) == code


def test_provenance_disagreeing_with_the_run_is_refused(tmp_path):
    run = _run("explicit-cuda")
    run["provenance"]["actualDevice"] = "cuda:1"

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"explicit-cuda": run})

    assert _code(excinfo) == "e2e_run_provenance_device_mismatch:explicit-cuda"


def test_provenance_claiming_verified_on_development_is_refused(tmp_path):
    """Development never inherits the release's verified label."""
    run = _run("explicit-cuda")
    run["provenance"]["verificationStatus"] = "verified"

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"explicit-cuda": run})

    assert _code(excinfo) == (
        "e2e_run_provenance_status_unexpected:explicit-cuda"
    )


def test_the_oom_case_must_actually_have_recovered_from_one(tmp_path):
    run = _run("cuda-oom-recovery")
    del run["recoveredFromCudaOutOfMemory"]

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"cuda-oom-recovery": run})

    assert _code(excinfo) == "e2e_run_oom_not_exercised"


def test_the_restart_case_must_actually_have_restarted(tmp_path):
    run = _run("restart-recovery", restartCount=0)

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"restart-recovery": run})

    assert _code(excinfo) == "e2e_run_restart_not_exercised"


def test_runs_from_another_source_revision_are_refused(tmp_path):
    hardware = _hardware_evidence()
    hardware["developmentEvidence"]["sourceHeadSha"] = "f" * 40

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, hardware=hardware)

    assert _code(excinfo) == "e2e_source_revision_mismatch"


def test_a_hardware_bundle_of_the_wrong_schema_is_refused(tmp_path):
    hardware = _hardware_evidence(
        schemaVersion="mavi-windows-cuda-development-evidence-v1"
    )

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, hardware=hardware)

    assert _code(excinfo) == "e2e_development_evidence_schema_invalid"


def test_the_bundle_digest_can_be_recomputed_from_the_file_alone(tmp_path):
    evidence = _build(tmp_path)

    recomputed = json.loads(json.dumps(evidence))
    recomputed["developmentE2e"]["evidenceBundleSha256"] = ""
    digest = hashlib.sha256(
        json.dumps(
            recomputed, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()

    assert digest == evidence["developmentE2e"]["evidenceBundleSha256"]


def test_the_bundle_digest_covers_every_run(tmp_path):
    second = tmp_path / "again"
    second.mkdir()

    baseline = _build(tmp_path)
    altered = _build(
        second, runs={"explicit-cuda": _run("explicit-cuda", detectionCount=8422)}
    )

    assert (
        baseline["developmentE2e"]["evidenceBundleSha256"]
        != altered["developmentE2e"]["evidenceBundleSha256"]
    )


# --- Guards an earlier adversarial review proved were unpinned. Each of these
# --- corresponds to a weakening mutation that previously survived the suite.


def test_a_run_on_a_card_c4_never_qualified_is_refused(tmp_path):
    """Otherwise the bundle's only claim about the GPU is the ordinal string."""
    run = _run("explicit-cuda", gpuUuidSha256="ab" * 32)

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"explicit-cuda": run})

    assert _code(excinfo) == "e2e_run_gpu_identity_mismatch:explicit-cuda"


def test_a_cuda_run_without_a_gpu_identity_is_refused(tmp_path):
    run = _run("explicit-cuda")
    del run["gpuUuidSha256"]

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"explicit-cuda": run})

    assert _code(excinfo) == "e2e_run_gpu_identity_missing:explicit-cuda"


def test_a_run_on_another_ordinal_than_c4_attested_is_refused(tmp_path):
    run = _run("explicit-cuda", actualDevice="cuda:1")
    run["provenance"]["actualDevice"] = "cuda:1"

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"explicit-cuda": run})

    assert _code(excinfo) == "e2e_run_device_index_mismatch:explicit-cuda"


def test_a_run_whose_architecture_c4_did_not_build_is_refused(tmp_path):
    """A PTX-JIT fallback is not the artefact C4 qualified."""
    run = _run("explicit-cuda")
    run["cuda"]["archList"] = ["sm_37"]

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"explicit-cuda": run})

    assert _code(excinfo) == "e2e_run_architecture_not_in_build:explicit-cuda"


def test_a_run_under_another_cuda_runtime_than_c4_is_refused(tmp_path):
    run = _run("explicit-cuda")
    run["cuda"]["runtimeVersion"] = "11.8"

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"explicit-cuda": run})

    assert _code(excinfo) == (
        "e2e_run_cuda_runtime_version_mismatch:explicit-cuda"
    )


def test_a_c4_record_that_is_not_development_qualified_is_refused(tmp_path):
    hardware = _hardware_evidence()
    hardware["variantPatch"]["status"] = "pending-hardware-qualification"
    hardware["developmentEvidence"]["evidenceBundleSha256"] = ""
    hardware["developmentEvidence"]["evidenceBundleSha256"] = hashlib.sha256(
        json.dumps(
            hardware, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, hardware=hardware)

    assert _code(excinfo) == "e2e_development_evidence_not_qualified"


def test_a_c4_record_whose_own_digest_does_not_recompute_is_refused(tmp_path):
    """C7 declares a case for tampered evidence; the consumer must detect it."""
    hardware = _hardware_evidence()
    hardware["developmentEvidence"]["evidenceBundleSha256"] = "00" * 32

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, hardware=hardware)

    assert _code(excinfo) == "e2e_development_evidence_digest_mismatch"


@pytest.mark.parametrize("value", (float("nan"), float("inf"), float("-inf")))
def test_a_non_finite_elapsed_time_is_refused(tmp_path, value):
    """`nan <= 0` is False, and the artefact would not be valid JSON."""
    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"explicit-cuda": _run("explicit-cuda", elapsedSeconds=value)})

    assert _code(excinfo) == "e2e_run_timing_missing:explicit-cuda"


def test_runs_of_different_media_do_not_characterise_anything(tmp_path):
    run = _run("explicit-cpu", mediaSha256="ab" * 32)

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"explicit-cpu": run})

    assert _code(excinfo) == "e2e_runs_describe_different_media"


def test_runs_over_different_frame_counts_are_refused(tmp_path):
    run = _run("explicit-cpu", framesProcessed=1800)

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"explicit-cpu": run})

    assert _code(excinfo) == "e2e_runs_processed_different_frame_counts"


def test_a_run_that_persisted_no_tracks_is_refused(tmp_path):
    """Requirement 4 is that tracking output is persisted, not merely counted."""
    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"explicit-cuda": _run("explicit-cuda", trackCount=0)})

    assert _code(excinfo) == "e2e_run_no_tracks:explicit-cuda"


@pytest.mark.parametrize(
    ("block", "code"),
    (
        ("cuda", "e2e_run_cuda_telemetry_missing:explicit-cuda"),
        ("nvidiaSmi", "e2e_run_nvidia_smi_missing:explicit-cuda"),
        ("provenance", "e2e_run_provenance_missing:explicit-cuda"),
    ),
)
def test_a_cuda_run_missing_a_required_block_is_refused(tmp_path, block, code):
    run = _run("explicit-cuda")
    del run[block]

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"explicit-cuda": run})

    assert _code(excinfo) == code


def test_reserved_memory_below_allocated_memory_is_refused(tmp_path):
    run = _run("explicit-cuda")
    run["cuda"]["maxMemoryReservedBytes"] = 1024

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"explicit-cuda": run})

    assert _code(excinfo) == (
        "e2e_run_device_allocation_invalid:explicit-cuda"
    )


@pytest.mark.parametrize("value", (None, [], ["", "sm_75"], "sm_75"))
def test_a_malformed_architecture_list_is_refused(tmp_path, value):
    run = _run("explicit-cuda")
    if value is None:
        del run["cuda"]["archList"]
    else:
        run["cuda"]["archList"] = value

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"explicit-cuda": run})

    assert _code(excinfo).startswith("e2e_run_")


def test_a_cuda_run_without_a_runtime_version_is_refused(tmp_path):
    run = _run("explicit-cuda")
    del run["cuda"]["runtimeVersion"]

    with pytest.raises(MODULE.DevelopmentE2eError) as excinfo:
        _build(tmp_path, runs={"explicit-cuda": run})

    assert _code(excinfo).startswith("e2e_run_cuda_runtime_version")


def test_the_bundle_names_the_card_and_the_media_it_describes(tmp_path):
    evidence = _build(tmp_path)

    assert evidence["developmentE2e"]["gpuUuidSha256"] == _GPU_DIGEST
    assert evidence["developmentE2e"]["mediaSha256"] == _MEDIA_SHA
