"""Development hardware qualification must be earned by a run, not by a build.

ADR-009 lets `qualified-development-hardware` exist only because a real GPU on
controlled Development hardware executed the native operators. Every negative
case here is the evidence writer refusing to issue that record from artefacts
that do not prove it: a build that compiled but never ran, a run on a card the
host observation does not describe, kernels the wheel does not contain.

All artefacts are synthesised in-test; nothing depends on repository state or
on a GPU being present.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


TOOL_PATH = (
    Path(__file__).resolve().parents[3]
    / "tools"
    / "vision"
    / "build_development_hardware_evidence.py"
)

_SOURCE_HEAD_SHA = "426195d4e1b0a9f2c3d4e5f60718293a4b5c6d7e"
_CAPTURED_AT = "2026-09-18T04:11:52Z"
_OPERATOR = "mavi-dev-workstation-01"
_UUID_DIGEST = "cb70319f" + "0" * 56


def _load():
    spec = importlib.util.spec_from_file_location(
        "build_development_hardware_evidence", TOOL_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("development_evidence_module_unloadable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load()


def _host(**overrides) -> dict:
    gpu = {
        "index": 0,
        "name": "NVIDIA GeForce RTX 2080 Ti",
        "uuidSha256": _UUID_DIGEST,
        "pciBusId": "00000000:01:00.0",
        "driverVersion": "560.94",
        "memoryMiB": {"total": 11264, "free": 11000, "used": 264},
        "computeCapability": "7.5",
    }
    value = {
        "schemaVersion": "mavi-windows-cuda-host-observation-v2",
        "host": {"system": "Windows", "machine": "AMD64"},
        "nvidia": {
            "driverVersion": "560.94",
            "gpuCount": 1,
            "gpus": [gpu],
        },
    }
    value.update(overrides)
    return value


def _toolchain(**overrides) -> dict:
    value = {
        "schemaVersion": "mavi-windows-cuda-toolchain-observation-v1",
        "status": "passed",
        "cudaToolkitVersion": "12.4",
        "vcToolsVersion": "14.44.35207",
        "windowsSdkVersion": "10.0.26100.0",
    }
    value.update(overrides)
    return value


def _runtime(**overrides) -> dict:
    value = {
        "schemaVersion": "mavi-windows-cuda-runtime-verification-v1",
        "deviceIndex": 0,
        "deviceName": "NVIDIA GeForce RTX 2080 Ti",
        "computeCapability": "7.5",
        "torchVersion": "2.6.0+cu124",
        "torchCudaRuntimeVersion": "12.4",
        "torchCudaArchList": ["sm_75"],
        "mmcvNmsExecutedOnCuda": True,
        "torchMatmulExecutedOnCuda": True,
        "result": "passed",
    }
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
    host: dict | None = None,
    toolchain: dict | None = None,
    runtime: dict | None = None,
    source_head_sha: str = _SOURCE_HEAD_SHA,
    captured_at_utc: str = _CAPTURED_AT,
    operator_reference: str = _OPERATOR,
    device_index: int = 0,
) -> dict:
    return MODULE.build_evidence(
        host_observation=_write(
            tmp_path, "host.json", _host() if host is None else host
        ),
        toolchain_observation=_write(
            tmp_path, "toolchain.json", _toolchain() if toolchain is None else toolchain
        ),
        runtime_verification=_write(
            tmp_path, "runtime.json", _runtime() if runtime is None else runtime
        ),
        source_head_sha=source_head_sha,
        captured_at_utc=captured_at_utc,
        operator_reference=operator_reference,
        device_index=device_index,
    )


def _code(excinfo) -> str:
    return excinfo.value.code


def test_complete_evidence_is_accepted_and_scoped_to_development(tmp_path):
    evidence = _build(tmp_path)

    assert evidence["schemaVersion"] == (
        "mavi-windows-cuda-development-evidence-v1"
    )
    assert evidence["developmentEvidence"]["sourceHeadSha"] == _SOURCE_HEAD_SHA
    assert evidence["developmentEvidence"]["capturedAtUtc"] == _CAPTURED_AT
    assert evidence["developmentEvidence"]["operatorReference"] == _OPERATOR
    assert evidence["corroboration"]["gpuUuidSha256"] == _UUID_DIGEST
    assert evidence["corroboration"]["targetArchitecture"] == "sm_75"
    assert evidence["corroboration"]["hostGpuCount"] == 1
    assert evidence["corroboration"]["msvcToolset"] == "14.44.35207"
    # The record must never read as a Production qualification.
    assert "may not be promoted to, Production qualification" in evidence["note"]


def test_raw_gpu_uuid_is_never_carried_into_the_bundle(tmp_path):
    host = _host()
    host["nvidia"]["gpus"][0]["uuid"] = "GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    serialised = json.dumps(_build(tmp_path, host=host))

    assert "GPU-aaaaaaaa" not in serialised


def test_build_without_on_device_native_ops_is_refused(tmp_path):
    with pytest.raises(MODULE.DevelopmentEvidenceError) as excinfo:
        _build(tmp_path, runtime=_runtime(mmcvNmsExecutedOnCuda=False))

    assert _code(excinfo) == "development_evidence_native_ops_not_executed"


def test_missing_native_op_flag_is_not_read_as_success(tmp_path):
    runtime = _runtime()
    del runtime["mmcvNmsExecutedOnCuda"]

    with pytest.raises(MODULE.DevelopmentEvidenceError) as excinfo:
        _build(tmp_path, runtime=runtime)

    assert _code(excinfo) == "development_evidence_native_ops_not_executed"


def test_truthy_but_non_boolean_execution_flag_is_refused(tmp_path):
    with pytest.raises(MODULE.DevelopmentEvidenceError) as excinfo:
        _build(tmp_path, runtime=_runtime(torchMatmulExecutedOnCuda="yes"))

    assert _code(excinfo) == "development_evidence_torch_not_executed"


def test_failed_runtime_verification_is_refused(tmp_path):
    with pytest.raises(MODULE.DevelopmentEvidenceError) as excinfo:
        _build(tmp_path, runtime=_runtime(result="failed"))

    assert _code(excinfo) == "development_evidence_runtime_not_passed"


def test_failed_toolchain_observation_is_refused(tmp_path):
    with pytest.raises(MODULE.DevelopmentEvidenceError) as excinfo:
        _build(tmp_path, toolchain=_toolchain(status="failed"))

    assert _code(excinfo) == "development_evidence_toolchain_not_passed"


def test_gpu_named_differently_by_host_and_run_is_refused(tmp_path):
    with pytest.raises(MODULE.DevelopmentEvidenceError) as excinfo:
        _build(tmp_path, runtime=_runtime(deviceName="NVIDIA RTX A4000"))

    assert _code(excinfo) == "development_evidence_gpu_mismatch"


def test_compute_capability_disagreement_is_refused(tmp_path):
    with pytest.raises(MODULE.DevelopmentEvidenceError) as excinfo:
        _build(
            tmp_path,
            runtime=_runtime(computeCapability="8.6", torchCudaArchList=["sm_86"]),
        )

    assert _code(excinfo) == "development_evidence_gpu_mismatch"


def test_second_gpu_is_matched_by_identity_not_by_ordinal(tmp_path):
    """The run's CUDA ordinal may not be used to index nvidia-smi order."""
    host = _host()
    other = dict(host["nvidia"]["gpus"][0])
    other.update(
        index=0,
        name="NVIDIA RTX A4000",
        computeCapability="8.6",
        uuidSha256="a" * 64,
        pciBusId="00000000:41:00.0",
    )
    target = dict(host["nvidia"]["gpus"][0])
    target["index"] = 1
    # nvidia-smi lists the other card first; the run was on the 2080 Ti.
    host["nvidia"]["gpus"] = [other, target]
    host["nvidia"]["gpuCount"] = 2

    evidence = _build(tmp_path, host=host)

    assert evidence["corroboration"]["gpuUuidSha256"] == _UUID_DIGEST
    assert evidence["corroboration"]["hostGpuCount"] == 2


def test_two_indistinguishable_gpus_are_refused_rather_than_guessed(tmp_path):
    host = _host()
    twin = dict(host["nvidia"]["gpus"][0])
    twin.update(index=1, uuidSha256="b" * 64, pciBusId="00000000:41:00.0")
    host["nvidia"]["gpus"] = [host["nvidia"]["gpus"][0], twin]
    host["nvidia"]["gpuCount"] = 2

    with pytest.raises(MODULE.DevelopmentEvidenceError) as excinfo:
        _build(tmp_path, host=host)

    assert _code(excinfo) == "development_evidence_gpu_ambiguous"


def test_device_index_disagreement_is_refused(tmp_path):
    with pytest.raises(MODULE.DevelopmentEvidenceError) as excinfo:
        _build(tmp_path, runtime=_runtime(deviceIndex=1))

    assert _code(excinfo) == "development_evidence_device_index_mismatch"


def test_architecture_absent_from_the_torch_build_is_refused(tmp_path):
    """A run that fell back to PTX JIT does not qualify the built artefact."""
    with pytest.raises(MODULE.DevelopmentEvidenceError) as excinfo:
        _build(tmp_path, runtime=_runtime(torchCudaArchList=["sm_86", "sm_89"]))

    assert _code(excinfo) == (
        "development_evidence_architecture_not_in_torch_build"
    )


def test_missing_gpu_identity_digest_is_refused(tmp_path):
    host = _host()
    del host["nvidia"]["gpus"][0]["uuidSha256"]

    with pytest.raises(MODULE.DevelopmentEvidenceError) as excinfo:
        _build(tmp_path, host=host)

    assert _code(excinfo) == "development_evidence_gpu_identity_missing"


def test_malformed_gpu_identity_digest_is_refused(tmp_path):
    host = _host()
    host["nvidia"]["gpus"][0]["uuidSha256"] = "not-a-digest"

    with pytest.raises(MODULE.DevelopmentEvidenceError) as excinfo:
        _build(tmp_path, host=host)

    assert _code(excinfo) == "development_evidence_gpu_identity_missing"


def test_host_observation_without_gpus_is_refused(tmp_path):
    host = _host()
    host["nvidia"]["gpus"] = []

    with pytest.raises(MODULE.DevelopmentEvidenceError) as excinfo:
        _build(tmp_path, host=host)

    assert _code(excinfo) == "development_evidence_host_gpu_missing"


@pytest.mark.parametrize(
    ("artefact", "schema", "code"),
    (
        ("host", "mavi-windows-cuda-host-observation-v1", "host_observation"),
        ("toolchain", "mavi-windows-cuda-toolchain-observation-v2", "toolchain"),
        ("runtime", "mavi-windows-cuda-runtime-verification-v2", "runtime"),
    ),
)
def test_wrong_artefact_schema_version_is_refused(
    tmp_path, artefact, schema, code
):
    builders = {"host": _host, "toolchain": _toolchain, "runtime": _runtime}
    value = builders[artefact](schemaVersion=schema)

    with pytest.raises(MODULE.DevelopmentEvidenceError) as excinfo:
        _build(tmp_path, **{artefact: value})

    assert _code(excinfo) == f"development_evidence_{code}_schema_invalid"


def test_unreadable_artefact_is_refused(tmp_path):
    with pytest.raises(MODULE.DevelopmentEvidenceError) as excinfo:
        MODULE.build_evidence(
            host_observation=tmp_path / "absent.json",
            toolchain_observation=_write(tmp_path, "toolchain.json", _toolchain()),
            runtime_verification=_write(tmp_path, "runtime.json", _runtime()),
            source_head_sha=_SOURCE_HEAD_SHA,
            captured_at_utc=_CAPTURED_AT,
            operator_reference=_OPERATOR,
        )

    assert _code(excinfo) == "development_evidence_host_observation_unreadable"


def test_malformed_artefact_json_is_refused(tmp_path):
    path = tmp_path / "runtime.json"
    path.write_text("{ not json", encoding="utf-8")

    with pytest.raises(MODULE.DevelopmentEvidenceError) as excinfo:
        MODULE.build_evidence(
            host_observation=_write(tmp_path, "host.json", _host()),
            toolchain_observation=_write(tmp_path, "toolchain.json", _toolchain()),
            runtime_verification=path,
            source_head_sha=_SOURCE_HEAD_SHA,
            captured_at_utc=_CAPTURED_AT,
            operator_reference=_OPERATOR,
        )

    assert _code(excinfo) == "development_evidence_runtime_invalid"


@pytest.mark.parametrize(
    "value",
    ("426195D4E1B0A9F2C3D4E5F60718293A4B5C6D7E", "426195d", "", "426195d4" * 6),
)
def test_malformed_source_head_sha_is_refused(tmp_path, value):
    with pytest.raises(MODULE.DevelopmentEvidenceError) as excinfo:
        _build(tmp_path, source_head_sha=value)

    assert _code(excinfo) == "development_evidence_source_head_sha_invalid"


@pytest.mark.parametrize(
    "value",
    (
        "2026-09-18T04:11:52+05:30",
        "2026-09-18 04:11:52Z",
        "2026-09-18T04:11:52.123Z",
        "",
    ),
)
def test_non_canonical_capture_timestamp_is_refused(tmp_path, value):
    with pytest.raises(MODULE.DevelopmentEvidenceError) as excinfo:
        _build(tmp_path, captured_at_utc=value)

    assert _code(excinfo) == "development_evidence_captured_at_invalid"


@pytest.mark.parametrize("value", ("", " leading", "operator\nreference", "x" * 129))
def test_malformed_operator_reference_is_refused(tmp_path, value):
    with pytest.raises(MODULE.DevelopmentEvidenceError) as excinfo:
        _build(tmp_path, operator_reference=value)

    assert _code(excinfo) == "development_evidence_operator_invalid"


def test_evidence_bundle_digest_is_deterministic(tmp_path):
    second_root = tmp_path / "again"
    second_root.mkdir()

    first = _build(tmp_path)
    second = _build(second_root)

    assert (
        first["developmentEvidence"]["evidenceBundleSha256"]
        == second["developmentEvidence"]["evidenceBundleSha256"]
    )


def test_evidence_bundle_digest_changes_with_any_artefact(tmp_path):
    """The record may not be detachable from the evidence it summarises."""
    second_root = tmp_path / "again"
    second_root.mkdir()

    baseline = _build(tmp_path)
    altered = _build(
        second_root, toolchain=_toolchain(windowsSdkVersion="10.0.22621.0")
    )

    assert (
        baseline["developmentEvidence"]["evidenceBundleSha256"]
        != altered["developmentEvidence"]["evidenceBundleSha256"]
    )
    assert (
        baseline["corroboration"]["toolchainObservationSha256"]
        != altered["corroboration"]["toolchainObservationSha256"]
    )
    assert (
        baseline["developmentEvidence"]["hostObservationSha256"]
        == altered["developmentEvidence"]["hostObservationSha256"]
    )
