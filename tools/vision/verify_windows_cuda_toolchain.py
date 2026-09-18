#!/usr/bin/env python3
"""Verify the Windows CUDA native build toolchain before C2 begins."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


class ToolchainVerificationError(ValueError):
    def __init__(
        self,
        code: str,
        *,
        evidence: dict[str, object] | None = None,
    ) -> None:
        self.code = code
        # A failed R1 run is evidence too: the rejection of one toolset is what
        # justifies testing another, so it must be recorded in full rather than
        # summarised into an exception message.
        self.evidence = evidence
        super().__init__(code)


def _run(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    missing_code: str = "cuda_toolchain_command_not_found",
) -> subprocess.CompletedProcess[str]:
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
        raise ToolchainVerificationError(missing_code) from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolchainVerificationError(
            "cuda_toolchain_command_timed_out"
        ) from exc


# R1 must distinguish a genuine CUDA host-compiler rejection from an unrelated
# environment problem, because only the former justifies selecting a different
# MSVC toolset. An unclassified failure would invite exactly the wrong remedy.
_COMPILE_FAILURE_SIGNATURES: tuple[tuple[str, str], ...] = (
    (
        "unsupported microsoft visual studio version",
        "cuda_toolchain_host_compiler_unsupported",
    ),
    (
        "cannot find compiler 'cl.exe' in path",
        "cuda_toolchain_host_compiler_not_found",
    ),
    (
        "unsupported gpu architecture",
        "cuda_toolchain_architecture_unsupported",
    ),
    (
        "cannot open include file",
        "cuda_toolchain_headers_unavailable",
    ),
)


def classify_compile_failure(detail: str) -> str:
    """Name the reason an nvcc compile failed, for the R1 decision procedure."""
    text = detail.casefold()
    for marker, code in _COMPILE_FAILURE_SIGNATURES:
        if marker in text:
            return code
    return "cuda_toolchain_compile_failed"


def _nvcc_architecture_flag(contract: dict[str, object]) -> str:
    """Derive the probe architecture from the contract's frozen target.

    Hardcoding the architecture would let the probe prove a target other than
    the one being frozen.
    """
    target = contract.get("targetGpu")
    if not isinstance(target, dict):
        raise ToolchainVerificationError(
            "cuda_build_contract_target_invalid"
        )
    capability = str(target.get("computeCapability", ""))
    if re.fullmatch(r"\d+\.\d+", capability) is None:
        raise ToolchainVerificationError(
            "cuda_build_contract_target_invalid"
        )
    major, minor = capability.split(".")
    architecture = f"sm{major}{minor}"
    if str(target.get("architecture", "")) != architecture:
        raise ToolchainVerificationError(
            "cuda_build_contract_target_inconsistent"
        )
    return f"-arch=sm_{major}{minor}"


# The correctness-bearing build variables. MAX_JOBS and any other tuning knob in
# the contract's build environment do not decide whether CUDA ops are produced,
# so the preflight does not demand them.
_REQUIRED_BUILD_ENVIRONMENT_NAMES = (
    "MMCV_WITH_OPS",
    "FORCE_CUDA",
    "TORCH_CUDA_ARCH_LIST",
)


def _required_build_environment(contract: dict[str, object]) -> dict[str, str]:
    """Take the expected build environment from the contract, not a copy of it.

    A hardcoded copy would let the preflight prove a build environment other
    than the one the contract freezes.
    """
    mmcv = contract.get("mmcv")
    build_env = mmcv.get("buildEnvironment") if isinstance(mmcv, dict) else None
    if not isinstance(build_env, dict):
        raise ToolchainVerificationError(
            "cuda_build_contract_build_environment_invalid"
        )
    required: dict[str, str] = {}
    for name in _REQUIRED_BUILD_ENVIRONMENT_NAMES:
        value = build_env.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ToolchainVerificationError(
                "cuda_build_contract_build_environment_invalid"
            )
        required[name] = value
    return required


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


def _captured_at_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_source_head_sha(explicit: str | None) -> str:
    if explicit is not None:
        candidate = explicit.strip().casefold()
    else:
        result = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            capture_output=True,
            text=True,
            check=False,
        )
        candidate = result.stdout.strip().casefold() if result.returncode == 0 else ""
    if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", candidate) is None:
        raise ToolchainVerificationError(
            "cuda_toolchain_source_identity_unavailable"
        )
    return candidate


def verify_toolchain(
    contract_path: Path,
    *,
    source_head_sha: str | None = None,
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
    resolved_head_sha = _resolve_source_head_sha(source_head_sha)
    architecture_flag = _nvcc_architecture_flag(contract)
    required_env = _required_build_environment(contract)
    for name, expected in required_env.items():
        observed = os.environ.get(name)
        if observed != expected:
            raise ToolchainVerificationError(
                "cuda_build_environment_mismatch:" + name
            )

    nvcc = _run(
        ("nvcc", "--version"),
        missing_code="cuda_toolchain_nvcc_not_found",
    )
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

    cl = _run(
        ("cl",),
        missing_code="cuda_toolchain_host_compiler_not_found",
    )
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
        source_text = "extern \"C\" __global__ void mavi_probe() {}\n"
        source.write_text(
            source_text,
            encoding="utf-8",
            newline="\n",
        )
        command = (
            "nvcc",
            "-c",
            str(source),
            "-o",
            str(obj),
            architecture_flag,
        )
        compile_result = _run(
            command,
            cwd=root,
            missing_code="cuda_toolchain_nvcc_not_found",
        )
        compile_evidence: dict[str, object] = {
            "command": list(command),
            "exitCode": compile_result.returncode,
            "stdout": compile_result.stdout,
            "stderr": compile_result.stderr,
            "source": source_text,
            "sourceSha256": hashlib.sha256(
                source_text.encode("utf-8")
            ).hexdigest(),
            "objectProduced": obj.is_file(),
        }
        if compile_result.returncode != 0 or not obj.is_file():
            detail = (
                compile_result.stdout + "\n" + compile_result.stderr
            ).strip()
            code = classify_compile_failure(detail)
            raise ToolchainVerificationError(
                code + ":" + detail[-1200:],
                evidence={
                    "schemaVersion": (
                        "mavi-windows-cuda-toolchain-observation-v1"
                    ),
                    "status": "failed",
                    "failureCode": code,
                    "capturedAtUtc": _captured_at_utc(),
                    "sourceHeadSha": resolved_head_sha,
                    "cudaToolkitVersion": cuda_release,
                    "msvcCompilerVersion": msvc_compiler,
                    "vcToolsVersion": vc_tools,
                    "windowsSdkVersion": sdk,
                    "nvccArchitectureFlag": architecture_flag,
                    "buildEnvironment": required_env,
                    "compile": compile_evidence,
                },
            )
        compile_evidence["objectBytes"] = obj.stat().st_size
        compile_evidence["objectSha256"] = hashlib.sha256(
            obj.read_bytes()
        ).hexdigest()

    return {
        "schemaVersion": "mavi-windows-cuda-toolchain-observation-v1",
        "status": "passed",
        "capturedAtUtc": _captured_at_utc(),
        "sourceHeadSha": resolved_head_sha,
        "cudaToolkitVersion": cuda_release,
        "msvcCompilerVersion": msvc_compiler,
        "vcToolsVersion": vc_tools,
        "windowsSdkVersion": sdk,
        "targetArchitecture": str(contract["targetGpu"]["architecture"]),
        "nvccArchitectureFlag": architecture_flag,
        "buildEnvironment": required_env,
        "compile": compile_evidence,
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
    parser.add_argument(
        "--source-head-sha",
        help=(
            "Source revision the evidence is collected against. "
            "Defaults to the current git HEAD."
        ),
    )
    args = parser.parse_args()

    def _write(value: dict[str, object]) -> bool:
        if args.output is None:
            return True
        if args.output.exists():
            print(
                json.dumps(
                    {"ok": False, "code": "cuda_toolchain_output_exists"},
                    sort_keys=True,
                )
            )
            return False
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return True

    try:
        result = verify_toolchain(
            args.contract,
            source_head_sha=args.source_head_sha,
        )
    except ToolchainVerificationError as exc:
        # Persist the rejection as evidence: it is the record that justifies
        # testing a different toolset.
        if exc.evidence is not None:
            _write(exc.evidence)
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
    if not _write(result):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
