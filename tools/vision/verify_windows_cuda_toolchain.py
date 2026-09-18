#!/usr/bin/env python3
"""Verify the Windows CUDA native build toolchain before C2 begins."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence


class ToolchainVerificationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _run(args: Sequence[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(args),
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except FileNotFoundError as exc:
        raise ToolchainVerificationError(
            "cuda_toolchain_command_not_found"
        ) from exc


def _load_contract(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolchainVerificationError(
            "cuda_build_contract_invalid"
        ) from exc
    if value.get("schemaVersion") != (
        "mavi-windows-cuda-development-build-v1"
    ):
        raise ToolchainVerificationError(
            "cuda_build_contract_schema_invalid"
        )
    return value


def _first_version(text: str, pattern: str, code: str) -> str:
    match = re.search(pattern, text, re.IGNORECASE)
    if match is None:
        raise ToolchainVerificationError(code)
    return match.group(1)


def verify_toolchain(
    contract_path: Path,
) -> dict[str, object]:
    if platform.system() != "Windows":
        raise ToolchainVerificationError(
            "cuda_toolchain_windows_required"
        )
    if platform.machine().casefold() not in {"amd64", "x86_64"}:
        raise ToolchainVerificationError(
            "cuda_toolchain_x86_64_required"
        )

    contract = _load_contract(contract_path)
    build_env = contract["mmcv"]["buildEnvironment"]
    required_env = {
        "MMCV_WITH_OPS": "1",
        "FORCE_CUDA": "1",
        "TORCH_CUDA_ARCH_LIST": "7.5+PTX",
    }
    for name, expected in required_env.items():
        observed = os.environ.get(name)
        if observed != expected:
            raise ToolchainVerificationError(
                "cuda_build_environment_mismatch:" + name
            )

    nvcc = _run(("nvcc", "--version"))
    if nvcc.returncode != 0:
        raise ToolchainVerificationError(
            "cuda_toolchain_nvcc_unavailable"
        )
    nvcc_text = (nvcc.stdout + "\n" + nvcc.stderr).strip()
    cuda_release = _first_version(
        nvcc_text,
        r"release\s+(\d+\.\d+)",
        "cuda_toolchain_nvcc_version_unreadable",
    )
    expected_cuda = str(contract["toolchain"]["cudaToolkitVersion"])
    if cuda_release != expected_cuda:
        raise ToolchainVerificationError(
            "cuda_toolchain_version_mismatch"
        )

    cl = _run(("cl",))
    cl_text = (cl.stdout + "\n" + cl.stderr).strip()
    if not cl_text:
        raise ToolchainVerificationError(
            "cuda_toolchain_msvc_unavailable"
        )
    msvc_compiler = _first_version(
        cl_text,
        r"Compiler Version\s+([0-9.]+)",
        "cuda_toolchain_msvc_version_unreadable",
    )

    vc_tools = (os.environ.get("VCToolsVersion") or "").strip().rstrip("\\")
    sdk = (os.environ.get("WindowsSDKVersion") or "").strip().rstrip("\\")
    if not vc_tools:
        raise ToolchainVerificationError(
            "cuda_toolchain_vctools_identity_missing"
        )
    if not sdk:
        raise ToolchainVerificationError(
            "cuda_toolchain_windows_sdk_identity_missing"
        )

    with tempfile.TemporaryDirectory(prefix="mavi-cuda-toolchain-") as temp:
        root = Path(temp)
        source = root / "probe.cu"
        obj = root / "probe.obj"
        source.write_text(
            "extern \"C\" __global__ void mavi_probe() {}\n",
            encoding="utf-8",
            newline="\n",
        )
        compile_result = _run(
            (
                "nvcc",
                "-c",
                str(source),
                "-o",
                str(obj),
                "-arch=sm_75",
            ),
            cwd=root,
        )
        if compile_result.returncode != 0 or not obj.is_file():
            detail = (
                compile_result.stdout + "\n" + compile_result.stderr
            ).strip()
            raise ToolchainVerificationError(
                "cuda_toolchain_compile_failed:"
                + detail[-1200:]
            )

    return {
        "schemaVersion": "mavi-windows-cuda-toolchain-observation-v1",
        "status": "passed",
        "cudaToolkitVersion": cuda_release,
        "msvcCompilerVersion": msvc_compiler,
        "vcToolsVersion": vc_tools,
        "windowsSdkVersion": sdk,
        "targetArchitecture": "sm75",
        "buildEnvironment": required_env,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path(
            "config/vision/windows-cuda-development-build-v1.json"
        ),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        result = verify_toolchain(args.contract)
    except ToolchainVerificationError as exc:
        print(
            json.dumps(
                {"ok": False, "code": exc.code},
                sort_keys=True,
            )
        )
        return 2

    payload = json.dumps(
        {"ok": True, "toolchain": result},
        sort_keys=True,
        separators=(",", ":"),
    )
    print(payload)
    if args.output is not None:
        if args.output.exists():
            print(
                json.dumps(
                    {
                        "ok": False,
                        "code": "cuda_toolchain_output_exists",
                    },
                    sort_keys=True,
                )
            )
            return 2
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
