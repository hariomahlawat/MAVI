#!/usr/bin/env python3
"""Capture deterministic Windows/NVIDIA facts for CUDA engineering.

The observation is factual only. It never qualifies a Runtime Pack or a
Production profile. Raw GPU UUID is written only to a local output file;
stdout is sanitized by default.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from host_gpu_digest import gpu_uuid_digest  # noqa: E402


SCHEMA_VERSION = "mavi-windows-cuda-host-observation-v2"
_CUDA_VERSION_RE = re.compile(r"CUDA Version:\s*([0-9]+(?:\.[0-9]+)?)")
_NVIDIA_QUERY_FIELDS = (
    "index",
    "name",
    "uuid",
    "pci.bus_id",
    "driver_version",
    "memory.total",
    "memory.free",
    "memory.used",
    "compute_cap",
    "driver_model.current",
    "driver_model.pending",
    "display_active",
    "display_mode",
)


class CudaHostProbeError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class CommandResult:
    stdout: str
    stderr: str
    returncode: int


Runner = Callable[[Sequence[str]], CommandResult]


def _run_command(args: Sequence[str]) -> CommandResult:
    try:
        completed = subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except FileNotFoundError as exc:
        command = str(args[0]) if args else ""
        code = (
            "nvidia_smi_not_found"
            if command.casefold() == "nvidia-smi"
            else "cuda_toolchain_command_not_found"
        )
        raise CudaHostProbeError(code) from exc
    return CommandResult(
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
    )


def _nonempty(value: str, *, code: str = "cuda_host_probe_value_missing") -> str:
    normalized = value.strip()
    if not normalized:
        raise CudaHostProbeError(code)
    return normalized


def _optional_text(value: str) -> str | None:
    normalized = value.strip()
    if not normalized or normalized.casefold() in {"n/a", "[n/a]", "not supported"}:
        return None
    return normalized


def _parse_int(value: str, *, code: str) -> int:
    try:
        parsed = int(value.strip())
    except ValueError as exc:
        raise CudaHostProbeError(code) from exc
    if parsed < 0:
        raise CudaHostProbeError(code)
    return parsed


def _parse_compute_capability(value: str) -> str:
    normalized = _nonempty(value, code="nvidia_smi_compute_cap_invalid")
    if not re.fullmatch(r"\d+\.\d+", normalized):
        raise CudaHostProbeError("nvidia_smi_compute_cap_invalid")
    return normalized


def _uuid_digest(uuid: str) -> str:
    return gpu_uuid_digest(uuid)


def _parse_gpu_rows(text: str) -> list[dict[str, object]]:
    reader = csv.reader(io.StringIO(text), skipinitialspace=True)
    rows: list[dict[str, object]] = []
    for fields in reader:
        if not fields or all(not field.strip() for field in fields):
            continue
        if len(fields) != len(_NVIDIA_QUERY_FIELDS):
            raise CudaHostProbeError("nvidia_smi_gpu_row_invalid")

        (
            index_text,
            name,
            uuid,
            pci_bus_id,
            driver,
            memory_total_text,
            memory_free_text,
            memory_used_text,
            compute_cap,
            driver_model_current,
            driver_model_pending,
            display_active,
            display_mode,
        ) = (item.strip() for item in fields)

        index = _parse_int(
            index_text,
            code="nvidia_smi_gpu_numeric_value_invalid",
        )
        memory_total = _parse_int(
            memory_total_text,
            code="nvidia_smi_gpu_numeric_value_invalid",
        )
        memory_free = _parse_int(
            memory_free_text,
            code="nvidia_smi_gpu_numeric_value_invalid",
        )
        memory_used = _parse_int(
            memory_used_text,
            code="nvidia_smi_gpu_numeric_value_invalid",
        )
        if memory_total <= 0 or memory_free + memory_used > memory_total + 32:
            raise CudaHostProbeError("nvidia_smi_gpu_memory_invalid")

        raw_uuid = _nonempty(uuid, code="nvidia_smi_gpu_uuid_invalid")
        rows.append(
            {
                "index": index,
                "name": _nonempty(name),
                "uuid": raw_uuid,
                "uuidSha256": _uuid_digest(raw_uuid),
                "pciBusId": _nonempty(
                    pci_bus_id,
                    code="nvidia_smi_pci_bus_id_invalid",
                ),
                "driverVersion": _nonempty(driver),
                "memoryMiB": {
                    "total": memory_total,
                    "free": memory_free,
                    "used": memory_used,
                },
                "computeCapability": _parse_compute_capability(
                    compute_cap
                ),
                "driverModel": {
                    "current": _optional_text(driver_model_current),
                    "pending": _optional_text(driver_model_pending),
                },
                "display": {
                    "active": _optional_text(display_active),
                    "mode": _optional_text(display_mode),
                },
            }
        )

    if not rows:
        raise CudaHostProbeError("nvidia_smi_no_gpu")
    if len({item["index"] for item in rows}) != len(rows):
        raise CudaHostProbeError("nvidia_smi_gpu_index_duplicate")
    if len({item["uuid"] for item in rows}) != len(rows):
        raise CudaHostProbeError("nvidia_smi_gpu_uuid_duplicate")
    return sorted(rows, key=lambda item: int(item["index"]))


def _parse_supported_cuda_version(text: str) -> str | None:
    match = _CUDA_VERSION_RE.search(text)
    return match.group(1) if match else None


def _capture_toolchain(runner: Runner) -> dict[str, object]:
    nvcc_path = shutil.which("nvcc")
    cl_path = shutil.which("cl")
    ninja_path = shutil.which("ninja")

    result: dict[str, object] = {
        "captureStatus": "observed",
        "cudaHome": os.environ.get("CUDA_PATH") or os.environ.get("CUDA_HOME"),
        "vcToolsVersion": os.environ.get("VCToolsVersion"),
        "windowsSdkVersion": os.environ.get("WindowsSDKVersion"),
        "nvcc": None,
        "msvc": None,
        "ninja": None,
    }

    if nvcc_path is not None:
        nvcc = runner(("nvcc", "--version"))
        if nvcc.returncode != 0:
            raise CudaHostProbeError("cuda_toolchain_nvcc_probe_failed")
        result["nvcc"] = {
            "path": nvcc_path,
            "versionOutput": nvcc.stdout.strip(),
        }

    if cl_path is not None:
        cl = runner(("cl",))
        # cl writes its banner to stderr and returns 2 without inputs.
        banner = (cl.stdout + "\n" + cl.stderr).strip()
        if not banner:
            raise CudaHostProbeError("cuda_toolchain_msvc_probe_failed")
        result["msvc"] = {
            "path": cl_path,
            "versionOutput": banner,
        }

    if ninja_path is not None:
        ninja = runner(("ninja", "--version"))
        if ninja.returncode != 0:
            raise CudaHostProbeError("cuda_toolchain_ninja_probe_failed")
        result["ninja"] = {
            "path": ninja_path,
            "version": ninja.stdout.strip(),
        }

    return result


def collect_observation(
    *,
    runner: Runner = _run_command,
    include_toolchain: bool = False,
    platform_system: Callable[[], str] = platform.system,
    platform_release: Callable[[], str] = platform.release,
    platform_version: Callable[[], str] = platform.version,
    platform_machine: Callable[[], str] = platform.machine,
) -> dict[str, object]:
    system = platform_system()
    machine = platform_machine()
    if system != "Windows":
        raise CudaHostProbeError("cuda_host_windows_required")
    if machine.casefold() not in {"amd64", "x86_64"}:
        raise CudaHostProbeError("cuda_host_x86_64_required")

    query = runner(
        (
            "nvidia-smi",
            "--query-gpu=" + ",".join(_NVIDIA_QUERY_FIELDS),
            "--format=csv,noheader,nounits",
        )
    )
    if query.returncode != 0:
        raise CudaHostProbeError("nvidia_smi_query_failed")
    gpus = _parse_gpu_rows(query.stdout)

    summary = runner(("nvidia-smi",))
    if summary.returncode != 0:
        raise CudaHostProbeError("nvidia_smi_summary_failed")

    driver_versions = sorted(
        {str(item["driverVersion"]) for item in gpus}
    )
    if len(driver_versions) != 1:
        raise CudaHostProbeError(
            "nvidia_smi_driver_version_inconsistent"
        )

    value: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "host": {
            "system": system,
            "release": platform_release(),
            "version": platform_version(),
            "machine": machine,
        },
        "nvidia": {
            "driverVersion": driver_versions[0],
            "driverSupportedCudaVersion": (
                _parse_supported_cuda_version(summary.stdout)
            ),
            "gpuCount": len(gpus),
            "gpus": gpus,
        },
        "qualification": {
            "status": "observation-only",
            "windowsCudaRuntimePackQualified": False,
        },
    }
    if include_toolchain:
        value["toolchain"] = _capture_toolchain(runner)
    return value


def sanitize_observation(
    value: dict[str, object],
) -> dict[str, object]:
    # JSON round-trip provides a simple deep copy of this JSON-only structure.
    sanitized = json.loads(json.dumps(value))
    nvidia = sanitized.get("nvidia")
    if isinstance(nvidia, dict):
        gpus = nvidia.get("gpus")
        if isinstance(gpus, list):
            for gpu in gpus:
                if isinstance(gpu, dict):
                    gpu.pop("uuid", None)
    return sanitized


def write_observation(
    value: dict[str, object],
    output: Path,
) -> None:
    if output.exists():
        raise CudaHostProbeError("cuda_host_output_exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Optional JSON output path. Existing files are never overwritten. "
            "The file contains the raw UUID unless --sanitized is supplied."
        ),
    )
    parser.add_argument(
        "--sanitized",
        action="store_true",
        help="Redact raw GPU UUID from the output file as well as stdout.",
    )
    parser.add_argument(
        "--include-toolchain",
        action="store_true",
        help=(
            "Also observe build-host-only CUDA/MSVC/SDK/ninja facts. "
            "This does not make them runtime prerequisites."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        value = collect_observation(
            include_toolchain=args.include_toolchain
        )
        display_value = sanitize_observation(value)
        if args.output is not None:
            write_observation(
                display_value if args.sanitized else value,
                args.output,
            )
    except (
        CudaHostProbeError,
        OSError,
        subprocess.SubprocessError,
    ) as exc:
        code = getattr(exc, "code", "cuda_host_probe_failed")
        print(
            json.dumps(
                {"ok": False, "code": str(code)},
                sort_keys=True,
            )
        )
        return 2

    print(
        json.dumps(
            {"ok": True, "observation": display_value},
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
