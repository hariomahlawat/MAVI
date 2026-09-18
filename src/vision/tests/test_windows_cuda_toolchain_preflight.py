"""The R1 preflight must classify its own failures and bind its evidence.

R1 decides whether a different MSVC toolset is required. That decision is only
sound if a genuine CUDA host-compiler rejection is distinguishable from an
unrelated environment problem, and if the resulting observation names the
revision and target it was collected against.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tools" / "vision" / "verify_windows_cuda_toolchain.py"
CONTRACT = ROOT / "config" / "vision" / "windows-cuda-development-build-v1.json"


def _load():
    spec = importlib.util.spec_from_file_location(
        "verify_windows_cuda_toolchain",
        TOOL,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("toolchain_verifier_unloadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_HOST_COMPILER_REJECTION = (
    r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.4\include"
    r"\crt/host_config.h(153): fatal error C1189: #error:  -- unsupported "
    "Microsoft Visual Studio version! Only the versions between 2017 and "
    "2022 (inclusive) are supported!"
)


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        (_HOST_COMPILER_REJECTION, "cuda_toolchain_host_compiler_unsupported"),
        (
            "nvcc fatal   : Cannot find compiler 'cl.exe' in PATH",
            "cuda_toolchain_host_compiler_not_found",
        ),
        (
            "nvcc fatal   : Unsupported gpu architecture 'compute_75'",
            "cuda_toolchain_architecture_unsupported",
        ),
        (
            "probe.cu(1): fatal error C1083: Cannot open include file: "
            "'crtdefs.h': No such file or directory",
            "cuda_toolchain_headers_unavailable",
        ),
        (
            "probe.cu(1): error: expected a declaration",
            "cuda_toolchain_compile_failed",
        ),
        ("", "cuda_toolchain_compile_failed"),
    ],
)
def test_compile_failures_are_classified(detail: str, expected: str) -> None:
    assert _load().classify_compile_failure(detail) == expected


def test_host_compiler_rejection_is_not_confused_with_other_failures() -> None:
    """Only a real host-compiler rejection may justify changing toolset."""
    module = _load()
    unrelated = (
        "nvcc fatal   : Cannot find compiler 'cl.exe' in PATH",
        "probe.cu(1): fatal error C1083: Cannot open include file: 'x.h'",
        "probe.cu(1): error: expected a declaration",
    )

    for detail in unrelated:
        assert (
            module.classify_compile_failure(detail)
            != "cuda_toolchain_host_compiler_unsupported"
        )


def test_probe_architecture_is_derived_from_the_contract() -> None:
    module = _load()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    assert module._nvcc_architecture_flag(contract) == "-arch=sm_75"


def test_probe_architecture_rejects_an_inconsistent_contract() -> None:
    """A contract whose capability and architecture disagree cannot be probed."""
    module = _load()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    contract["targetGpu"] = {**contract["targetGpu"], "architecture": "sm86"}

    with pytest.raises(
        module.ToolchainVerificationError,
        match="cuda_build_contract_target_inconsistent",
    ):
        module._nvcc_architecture_flag(contract)


@pytest.mark.parametrize(
    "target",
    [
        {},
        {"computeCapability": "seven.five", "architecture": "sm75"},
        {"architecture": "sm75"},
    ],
)
def test_probe_architecture_rejects_an_invalid_target(target: dict) -> None:
    module = _load()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    contract["targetGpu"] = target

    with pytest.raises(
        module.ToolchainVerificationError,
        match="cuda_build_contract_target_invalid",
    ):
        module._nvcc_architecture_flag(contract)


def test_source_head_sha_accepts_an_explicit_revision() -> None:
    module = _load()

    assert module._resolve_source_head_sha("A" * 40) == "a" * 40
    assert module._resolve_source_head_sha("b" * 64) == "b" * 64


@pytest.mark.parametrize("value", ["", "not-a-sha", "abc123", "z" * 40])
def test_source_head_sha_fails_closed_on_an_unusable_revision(
    value: str,
) -> None:
    """An observation that cannot name its revision is not evidence."""
    module = _load()

    with pytest.raises(
        module.ToolchainVerificationError,
        match="cuda_toolchain_source_identity_unavailable",
    ):
        module._resolve_source_head_sha(value)


def test_preflight_refuses_to_run_off_windows() -> None:
    """R1 evidence may only be produced on the real build host."""
    module = _load()

    with pytest.raises(
        module.ToolchainVerificationError,
        match="cuda_toolchain_windows_required",
    ):
        module.verify_toolchain(CONTRACT)


def test_preflight_never_forces_an_unsupported_compiler() -> None:
    """A forced compile is not a qualified toolchain, at any severity."""
    assert "allow-unsupported-compiler" not in TOOL.read_text(encoding="utf-8")


def test_preflight_compiles_a_real_cuda_kernel() -> None:
    """nvcc -V alone is not evidence; the probe must compile device code."""
    text = TOOL.read_text(encoding="utf-8")

    assert "__global__" in text
    assert '"-c",' in text


def test_contract_remains_fail_closed_until_r1_completes() -> None:
    """This test must be updated deliberately when R1 freezes a toolchain."""
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    toolchain = contract["toolchain"]

    if toolchain["verificationStatus"] == "pending-r1-preflight":
        assert toolchain["msvcToolset"] is None
        assert toolchain["windowsSdkVersion"] is None
    else:
        assert toolchain["verificationStatus"] == "verified"
        assert isinstance(toolchain["msvcToolset"], str)
        assert isinstance(toolchain["windowsSdkVersion"], str)


def test_required_build_environment_comes_from_the_contract() -> None:
    """A hardcoded copy could prove a build environment the contract does not."""
    module = _load()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    assert module._required_build_environment(contract) == {
        "MMCV_WITH_OPS": "1",
        "FORCE_CUDA": "1",
        "TORCH_CUDA_ARCH_LIST": "7.5+PTX",
    }


def test_required_build_environment_tracks_a_changed_contract() -> None:
    module = _load()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    contract["mmcv"]["buildEnvironment"]["TORCH_CUDA_ARCH_LIST"] = "8.6+PTX"

    assert (
        module._required_build_environment(contract)["TORCH_CUDA_ARCH_LIST"]
        == "8.6+PTX"
    )


def test_required_build_environment_ignores_tuning_knobs() -> None:
    """MAX_JOBS does not decide whether CUDA ops are produced."""
    module = _load()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    assert "MAX_JOBS" not in module._required_build_environment(contract)


@pytest.mark.parametrize(
    "build_environment",
    [
        {},
        {"MMCV_WITH_OPS": "1", "FORCE_CUDA": "1"},
        {"MMCV_WITH_OPS": "1", "FORCE_CUDA": "1", "TORCH_CUDA_ARCH_LIST": ""},
        {"MMCV_WITH_OPS": "1", "FORCE_CUDA": "1", "TORCH_CUDA_ARCH_LIST": 7.5},
    ],
)
def test_required_build_environment_fails_closed(
    build_environment: dict,
) -> None:
    module = _load()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    contract["mmcv"] = {**contract["mmcv"], "buildEnvironment": build_environment}

    with pytest.raises(
        module.ToolchainVerificationError,
        match="cuda_build_contract_build_environment_invalid",
    ):
        module._required_build_environment(contract)
