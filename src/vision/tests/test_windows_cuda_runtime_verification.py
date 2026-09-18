"""The record that proves CUDA ops ran, and the record left when they did not.

This tool is the only artefact in the C4 set that can attest a GPU executed
anything, which makes its shape worth pinning and its failure path worth having
at all: C7 is a phase whose entire output is failures, so a refusal that left no
artefact behind would lose exactly the evidence that phase exists to collect.

The verification run itself needs a GPU, so what is exercised here is everything
around it -- record composition, the failure record, and the command-line
contract -- none of which needs one.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from mavi_vision.runtime import qualification


TOOLS = Path(__file__).resolve().parents[3] / "tools" / "vision"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load("verify_windows_cuda_runtime")
DIGEST = _load("host_gpu_digest")

_RAW_UUID = "GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_CONFIG_SHA = "377d9f57abf6a73a6c308f765b70fc571715448c62998819d609d2eebc7c5ee3"


def _record(**overrides):
    values = {
        "host_observation_sha256": "d" * 64,
        "device_index": 0,
        "device_name": "NVIDIA GeForce RTX 2080 Ti",
        "compute_capability": "7.5",
        "gpu_uuid": _RAW_UUID,
        "driver_version": "560.94",
        "torch_version": "2.6.0+cu124",
        "torchvision_version": "0.21.0+cu124",
        "torch_cuda_runtime_version": "12.4",
        "torch_cuda_arch_list": ["sm_75"],
        "total_memory_bytes": 11264 * 1024 * 1024,
        "peak_memory_allocated_bytes": 1024,
        "peak_memory_reserved_bytes": 2048,
        "resolved_config_sha256": _CONFIG_SHA,
    }
    values.update(overrides)
    return MODULE.compose_record(**values)


def test_record_carries_the_salted_identity_of_the_card_that_ran(tmp_path):
    record = _record()

    assert record["gpuUuidSha256"] == DIGEST.gpu_uuid_digest(_RAW_UUID)
    # The digest is what correlates this run with the host observation; the raw
    # UUID identifies a specific workstation card and never travels.
    assert _RAW_UUID not in json.dumps(record)


def test_record_states_the_identities_a_development_qualification_needs():
    """ADR-009 requires these alongside the evidence, so the run must state them."""
    record = _record()

    python_identity = qualification._RuntimePythonIdentitySchema.model_validate(
        record["pythonIdentity"]
    )
    binaries = qualification._RuntimeBinaryVersionsSchema.model_validate(
        record["binaryVersions"]
    )

    assert python_identity.implementation == "CPython"
    assert binaries.torch == "2.6.0+cu124"
    assert binaries.torchvision == "0.21.0+cu124"
    assert record["resolvedConfigSha256"] == _CONFIG_SHA


def test_record_declares_on_device_execution_only_as_a_literal_result():
    record = _record()

    assert record["mmcvNmsExecutedOnCuda"] is True
    assert record["torchMatmulExecutedOnCuda"] is True
    assert record["result"] == "passed"
    assert record["schemaVersion"] == "mavi-windows-cuda-runtime-verification-v2"


def test_failure_record_never_claims_on_device_execution():
    record = MODULE.failure_record(
        code="cuda_unavailable",
        detail="torch.cuda.is_available() returned False",
        device_index=0,
        resolved_config="rtmdet_m_resolved.py",
    )

    assert record["result"] == "failed"
    assert record["mmcvNmsExecutedOnCuda"] is False
    assert record["torchMatmulExecutedOnCuda"] is False
    assert record["failureCode"] == "cuda_unavailable"


def test_a_failed_run_leaves_its_evidence_behind(tmp_path, monkeypatch, capsys):
    """The most interesting runs must not be the ones with no artefact."""
    output = tmp_path / "runtime-verification.json"

    def _fail(device_index, resolved_config, host_observation):
        raise MODULE.CudaRuntimeVerificationError(
            "mmcv_cuda_op_executed_off_device", "nms returned a CPU tensor"
        )

    monkeypatch.setattr(MODULE, "verify", _fail)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_windows_cuda_runtime.py",
            "--resolved-config",
            str(tmp_path / "config.py"),
            "--host-observation",
            str(tmp_path / "host.json"),
            "--output",
            str(output),
        ],
    )

    assert MODULE.main() == 2

    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["failureCode"] == "mmcv_cuda_op_executed_off_device"
    assert written["failureDetail"] == "nms returned a CPU tensor"
    assert json.loads(capsys.readouterr().out)["outputWritten"] is True


def test_an_unexpected_failure_is_still_recorded(tmp_path, monkeypatch, capsys):
    output = tmp_path / "runtime-verification.json"

    def _fail(device_index, resolved_config, host_observation):
        raise RuntimeError("CUDA driver version is insufficient")

    monkeypatch.setattr(MODULE, "verify", _fail)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_windows_cuda_runtime.py",
            "--resolved-config",
            str(tmp_path / "config.py"),
            "--host-observation",
            str(tmp_path / "host.json"),
            "--output",
            str(output),
        ],
    )

    assert MODULE.main() == 2

    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["failureCode"] == "cuda_runtime_verification_failed"
    assert "CUDA driver version is insufficient" in written["failureDetail"]


def test_an_existing_output_is_never_overwritten(tmp_path, monkeypatch, capsys):
    output = tmp_path / "runtime-verification.json"
    output.write_text("{}\n", encoding="utf-8")

    def _fail(device_index, resolved_config, host_observation):
        raise MODULE.CudaRuntimeVerificationError("cuda_unavailable")

    monkeypatch.setattr(MODULE, "verify", _fail)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_windows_cuda_runtime.py",
            "--resolved-config",
            str(tmp_path / "config.py"),
            "--host-observation",
            str(tmp_path / "host.json"),
            "--output",
            str(output),
        ],
    )

    assert MODULE.main() == 2

    assert output.read_text(encoding="utf-8") == "{}\n"
    assert json.loads(capsys.readouterr().out)["outputWritten"] is False


def test_verification_refuses_without_a_stable_device_order(tmp_path, monkeypatch):
    monkeypatch.delenv("CUDA_DEVICE_ORDER", raising=False)

    with pytest.raises(MODULE.CudaRuntimeVerificationError) as excinfo:
        MODULE.verify(0, tmp_path / "config.py", tmp_path / "host.json")

    assert excinfo.value.code == "cuda_device_order_not_pci_bus_id"


def test_verification_refuses_without_the_resolved_config(tmp_path, monkeypatch):
    monkeypatch.setenv("CUDA_DEVICE_ORDER", "PCI_BUS_ID")

    with pytest.raises(MODULE.CudaRuntimeVerificationError) as excinfo:
        MODULE.verify(0, tmp_path / "absent.py", tmp_path / "host.json")

    assert excinfo.value.code == "cuda_runtime_resolved_config_missing"


def test_verification_refuses_without_the_host_observation(tmp_path, monkeypatch):
    monkeypatch.setenv("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
    config = tmp_path / "config.py"
    config.write_text("model = dict()\n", encoding="utf-8")

    with pytest.raises(MODULE.CudaRuntimeVerificationError) as excinfo:
        MODULE.verify(0, config, tmp_path / "absent.json")

    assert excinfo.value.code == "cuda_runtime_host_observation_missing"


def test_a_failure_record_never_leaks_a_raw_gpu_uuid():
    """A failure artefact is a file the operator is meant to hand over."""
    record = MODULE.failure_record(
        code="cuda_runtime_verification_failed",
        detail=(
            "RuntimeError: device GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee "
            "is in an unrecoverable state"
        ),
        device_index=0,
        resolved_config="rtmdet_m_resolved.py",
    )

    assert "GPU-aaaaaaaa" not in json.dumps(record)
    assert "GPU-<redacted>" in record["failureDetail"]
    assert "unrecoverable state" in record["failureDetail"]


def test_a_successful_run_never_overwrites_an_existing_output(
    tmp_path, monkeypatch, capsys
):
    output = tmp_path / "runtime-verification.json"
    output.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        MODULE, "verify", lambda index, config, host: _record()
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_windows_cuda_runtime.py",
            "--resolved-config",
            str(tmp_path / "config.py"),
            "--host-observation",
            str(tmp_path / "host.json"),
            "--output",
            str(output),
        ],
    )

    assert MODULE.main() == 2

    assert output.read_text(encoding="utf-8") == "{}\n"
    assert json.loads(capsys.readouterr().out)["code"] == (
        "cuda_runtime_verification_output_exists"
    )


def test_the_record_names_the_observation_it_was_produced_against():
    assert _record()["hostObservationSha256"] == "d" * 64
