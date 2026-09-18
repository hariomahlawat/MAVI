#!/usr/bin/env python3
"""Capture a deterministic Windows/NVIDIA host observation for CUDA engineering.

This probe records host/GPU facts only. It does not qualify a CUDA Runtime Pack and
does not infer that a particular PyTorch CUDA build is supported. Qualification is a
separate step performed against an exact Runtime Pack on the observed hardware.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


SCHEMA_VERSION = "mavi-windows-cuda-host-observation-v1"
_CUDA_VERSION_RE = re.compile(r"CUDA Version:\s*([0-9]+(?:\.[0-9]+)?)")


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
    completed = subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return CommandResult(
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
    )


def _nonempty(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise CudaHostProbeError("cuda_host_probe_value_missing")
    return normalized


def _parse_gpu_rows(text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = [item.strip() for item in line.split(",")]
        if len(fields) != 5:
            raise CudaHostProbeError("nvidia_smi_gpu_row_invalid")
        index_text, name, uuid, driver, memory_text = fields
        try:
            index = int(index_text)
            memory_mib = int(memory_text)
        except ValueError as exc:
            raise CudaHostProbeError(
                "nvidia_smi_gpu_numeric_value_invalid"
            ) from exc
        if index < 0 or memory_mib <= 0:
            raise CudaHostProbeError(
                "nvidia_smi_gpu_numeric_value_invalid"
            )
        rows.append(
            {
                "index": index,
                "name": _nonempty(name),
                "uuid": _nonempty(uuid),
                "driverVersion": _nonempty(driver),
                "memoryMiB": memory_mib,
            }
        )
    if not rows:
        raise CudaHostProbeError("nvidia_smi_no_gpu")
    if len({item["index"] for item in rows}) != len(rows):
        raise CudaHostProbeError("nvidia_smi_gpu_index_duplicate")
    return sorted(rows, key=lambda item: int(item["index"]))


def _parse_supported_cuda_version(text: str) -> str | None:
    match = _CUDA_VERSION_RE.search(text)
    return match.group(1) if match else None


def collect_observation(
    *,
    runner: Runner = _run_command,
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
            "--query-gpu=index,name,uuid,driver_version,memory.total",
            "--format=csv,noheader,nounits",
        )
    )
    if query.returncode != 0:
        raise CudaHostProbeError("nvidia_smi_query_failed")
    gpus = _parse_gpu_rows(query.stdout)

    summary = runner(("nvidia-smi",))
    if summary.returncode != 0:
        raise CudaHostProbeError("nvidia_smi_summary_failed")
    supported_cuda = _parse_supported_cuda_version(summary.stdout)

    driver_versions = sorted(
        {str(item["driverVersion"]) for item in gpus}
    )
    if len(driver_versions) != 1:
        raise CudaHostProbeError(
            "nvidia_smi_driver_version_inconsistent"
        )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "host": {
            "system": system,
            "release": platform_release(),
            "version": platform_version(),
            "machine": machine,
        },
        "nvidia": {
            "driverVersion": driver_versions[0],
            "driverSupportedCudaVersion": supported_cuda,
            "gpuCount": len(gpus),
            "gpus": gpus,
        },
        "qualification": {
            "status": "observation-only",
            "windowsCudaRuntimePackQualified": False,
        },
    }


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
            "Without --output the observation is printed to stdout."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        value = collect_observation()
        if args.output is not None:
            write_observation(value, args.output)
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
            {"ok": True, "observation": value},
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
