from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator
import pytest


TOOL_PATH = (
    Path(__file__).parents[3]
    / "tools"
    / "vision"
    / "probe_windows_cuda_host.py"
)
SCHEMA_PATH = (
    Path(__file__).parents[3]
    / "tools"
    / "vision"
    / "windows-cuda-host-observation.schema.json"
)


def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "probe_windows_cuda_host",
        TOOL_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _runner(args):
    module = _load_tool()
    if any(str(item).startswith("--query-gpu=") for item in args):
        return module.CommandResult(
            stdout=(
                "0,NVIDIA GeForce RTX 4070 Laptop GPU,GPU-abc,"
                "00000000:01:00.0,580.82,8188,7000,1188,8.9,"
                "WDDM,N/A,Enabled,Enabled\n"
            ),
            stderr="",
            returncode=0,
        )
    return module.CommandResult(
        stdout=(
            "NVIDIA-SMI 580.82    Driver Version: 580.82    "
            "CUDA Version: 12.9\n"
        ),
        stderr="",
        returncode=0,
    )


def _observation():
    module = _load_tool()
    return module.collect_observation(
        runner=_runner,
        platform_system=lambda: "Windows",
        platform_release=lambda: "11",
        platform_version=lambda: "10.0.26100",
        platform_machine=lambda: "AMD64",
    )


def test_windows_cuda_host_observation_is_fact_only() -> None:
    value = _observation()

    assert value["schemaVersion"] == (
        "mavi-windows-cuda-host-observation-v2"
    )
    assert value["host"] == {
        "system": "Windows",
        "release": "11",
        "version": "10.0.26100",
        "machine": "AMD64",
    }
    assert value["nvidia"]["driverVersion"] == "580.82"
    assert value["nvidia"]["driverSupportedCudaVersion"] == "12.9"
    assert value["nvidia"]["gpuCount"] == 1

    gpu = value["nvidia"]["gpus"][0]
    assert gpu["index"] == 0
    assert gpu["name"] == "NVIDIA GeForce RTX 4070 Laptop GPU"
    assert gpu["uuid"] == "GPU-abc"
    assert len(gpu["uuidSha256"]) == 64
    assert gpu["pciBusId"] == "00000000:01:00.0"
    assert gpu["driverVersion"] == "580.82"
    assert gpu["memoryMiB"] == {
        "total": 8188,
        "free": 7000,
        "used": 1188,
    }
    assert gpu["computeCapability"] == "8.9"
    assert gpu["driverModel"] == {
        "current": "WDDM",
        "pending": None,
    }
    assert gpu["display"] == {
        "active": "Enabled",
        "mode": "Enabled",
    }
    assert value["qualification"] == {
        "status": "observation-only",
        "windowsCudaRuntimePackQualified": False,
    }


def test_observation_conforms_to_checked_in_schema() -> None:
    value = _observation()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(value)


def test_schema_rejects_missing_compute_capability() -> None:
    value = _observation()
    del value["nvidia"]["gpus"][0]["computeCapability"]
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(value))
    assert errors


def test_sanitized_observation_redacts_raw_uuid() -> None:
    module = _load_tool()
    value = _observation()
    sanitized = module.sanitize_observation(value)
    gpu = sanitized["nvidia"]["gpus"][0]
    assert "uuid" not in gpu
    assert gpu["uuidSha256"] == value["nvidia"]["gpus"][0]["uuidSha256"]
    assert "uuid" in value["nvidia"]["gpus"][0]


def test_probe_rejects_non_windows_host() -> None:
    module = _load_tool()
    with pytest.raises(
        module.CudaHostProbeError,
        match="cuda_host_windows_required",
    ):
        module.collect_observation(
            runner=_runner,
            platform_system=lambda: "Linux",
            platform_machine=lambda: "x86_64",
        )


def test_probe_rejects_failed_nvidia_smi() -> None:
    module = _load_tool()

    def failed(_args):
        return module.CommandResult(
            stdout="",
            stderr="not found",
            returncode=1,
        )

    with pytest.raises(
        module.CudaHostProbeError,
        match="nvidia_smi_query_failed",
    ):
        module.collect_observation(
            runner=failed,
            platform_system=lambda: "Windows",
            platform_machine=lambda: "AMD64",
        )


@pytest.mark.parametrize(
    "text",
    [
        "",
        "bad,row\n",
        (
            "x,GPU,GPU-1,0000:01:00.0,580.82,8192,7000,1192,"
            "7.5,WDDM,N/A,Enabled,Enabled\n"
        ),
        (
            "0,GPU,GPU-1,0000:01:00.0,580.82,zero,7000,1192,"
            "7.5,WDDM,N/A,Enabled,Enabled\n"
        ),
        (
            "0,GPU,GPU-1,0000:01:00.0,580.82,8192,7000,1192,"
            "bad,WDDM,N/A,Enabled,Enabled\n"
        ),
    ],
)
def test_gpu_row_parser_fails_closed(text: str) -> None:
    module = _load_tool()
    with pytest.raises(module.CudaHostProbeError):
        module._parse_gpu_rows(text)


def test_supported_cuda_version_may_be_unknown() -> None:
    module = _load_tool()
    assert (
        module._parse_supported_cuda_version(
            "NVIDIA-SMI 580.82 Driver Version: 580.82"
        )
        is None
    )


def test_observation_writer_never_overwrites(tmp_path: Path) -> None:
    module = _load_tool()
    output = tmp_path / "observation.json"
    value = {
        "schemaVersion": (
            "mavi-windows-cuda-host-observation-v2"
        )
    }
    module.write_observation(value, output)
    assert json.loads(output.read_text(encoding="utf-8")) == value

    with pytest.raises(
        module.CudaHostProbeError,
        match="cuda_host_output_exists",
    ):
        module.write_observation(value, output)
