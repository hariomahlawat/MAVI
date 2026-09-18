from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

from mavi_vision.runtime.offline_lock import (
    LockedDistribution,
    OfflineLockError,
    OfflineRuntimeLock,
    validate_accelerator_distribution_versions,
    validate_offline_runtime_lock_for_runtime,
)


ROOT = Path(__file__).parents[3]
BUILD_TOOL = ROOT / "tools" / "vision" / "build_runtime_pack.py"


def _lock(
    variant: str,
    *,
    torch_version: str,
    torchvision_version: str,
) -> OfflineRuntimeLock:
    return OfflineRuntimeLock(
        schema_version="mavi-offline-lock-v1",
        platform_variant=variant,
        python_version="3.12.10",
        distributions=(
            LockedDistribution(
                name="torch",
                version=torch_version,
                sha256="a" * 64,
            ),
            LockedDistribution(
                name="torchvision",
                version=torchvision_version,
                sha256="b" * 64,
            ),
        ),
    )


def _load_build_tool():
    spec = importlib.util.spec_from_file_location(
        "build_runtime_pack_cuda_contract",
        BUILD_TOOL,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_cuda_lock_requires_cuda_binary_build_tags() -> None:
    lock = _lock(
        "windows-x86_64-cuda",
        torch_version="2.6.0+cu124",
        torchvision_version="0.21.0+cu124",
    )
    validate_accelerator_distribution_versions(
        lock,
        expected_variant="windows-x86_64-cuda",
    )


@pytest.mark.parametrize(
    ("torch_version", "torchvision_version"),
    [
        ("2.6.0+cpu", "0.21.0+cpu"),
        ("2.6.0", "0.21.0"),
        ("2.6.0+cu124", "0.21.0+cpu"),
    ],
)
def test_cuda_lock_rejects_non_cuda_binary_builds(
    torch_version: str,
    torchvision_version: str,
) -> None:
    lock = _lock(
        "windows-x86_64-cuda",
        torch_version=torch_version,
        torchvision_version=torchvision_version,
    )
    with pytest.raises(
        OfflineLockError,
        match="offline_lock_cuda_binary_build_required",
    ):
        validate_accelerator_distribution_versions(
            lock,
            expected_variant="windows-x86_64-cuda",
        )


def test_cpu_lock_rejects_cuda_binary_builds() -> None:
    lock = _lock(
        "windows-x86_64-cpu",
        torch_version="2.6.0+cu124",
        torchvision_version="0.21.0+cu124",
    )
    with pytest.raises(
        OfflineLockError,
        match="offline_lock_cpu_binary_build_required",
    ):
        validate_accelerator_distribution_versions(
            lock,
            expected_variant="windows-x86_64-cpu",
        )


def test_semantic_graph_accepts_cuda_local_version_before_binary_freeze() -> None:
    lock = _lock(
        "windows-x86_64-cuda",
        torch_version="2.6.0+cu124",
        torchvision_version="0.21.0+cu124",
    )
    validate_offline_runtime_lock_for_runtime(
        lock,
        expected_variant="windows-x86_64-cuda",
        expected_python_version="3.12.10",
        semantic_graph={
            "torch": "2.6.0",
            "torchvision": "0.21.0",
        },
        binary_versions=None,
        root_requirements=(
            "torch==2.6.0",
            "torchvision==0.21.0",
        ),
    )


def test_exact_binary_versions_still_reject_wrong_cuda_build() -> None:
    lock = _lock(
        "windows-x86_64-cuda",
        torch_version="2.6.0+cu124",
        torchvision_version="0.21.0+cu124",
    )
    with pytest.raises(
        OfflineLockError,
        match="offline_lock_binary_version_mismatch",
    ):
        validate_offline_runtime_lock_for_runtime(
            lock,
            expected_variant="windows-x86_64-cuda",
            expected_python_version="3.12.10",
            semantic_graph={
                "torch": "2.6.0",
                "torchvision": "0.21.0",
            },
            binary_versions={
                "torch": "2.6.0+cu126",
                "torchvision": "0.21.0+cu126",
            },
            root_requirements=(
                "torch==2.6.0",
                "torchvision==0.21.0",
            ),
        )


def test_cuda_runtime_pack_native_abi_requires_cuda_and_sm_identity() -> None:
    module = _load_build_tool()
    module._validate_native_abi_for_variant(
        "win_amd64-msvc-14.39-sdk-10.0.26100.0-cuda12.4-sm75",
        "windows-x86_64-cuda",
    )

    with pytest.raises(
        module.RuntimePackError,
        match="runtime_pack_cuda_native_abi_incomplete",
    ):
        module._validate_native_abi_for_variant(
            "win_amd64-msvc-14.39-sdk-10.0.26100.0",
            "windows-x86_64-cuda",
        )


def test_cpu_runtime_pack_rejects_cuda_native_abi() -> None:
    module = _load_build_tool()
    with pytest.raises(
        module.RuntimePackError,
        match="runtime_pack_cpu_native_abi_contains_cuda",
    ):
        module._validate_native_abi_for_variant(
            "win_amd64-msvc-14.44-sdk-10.0.26100.0-cuda12.4-sm75",
            "windows-x86_64-cpu",
        )


def test_cuda_lock_without_binary_versions_still_requires_cuda_wheels() -> None:
    """A CUDA-labelled lock must prove CUDA wheels with or without a binary map."""
    lock = OfflineRuntimeLock(
        schema_version="mavi-offline-lock-v1",
        platform_variant="windows-x86_64-cuda",
        python_version="3.12.10",
        distributions=(
            LockedDistribution("torch", "2.6.0+cpu", "a" * 64),
            LockedDistribution("torchvision", "0.21.0+cpu", "b" * 64),
        ),
    )

    with pytest.raises(
        OfflineLockError,
        match="offline_lock_cuda_binary_build_required",
    ):
        validate_offline_runtime_lock_for_runtime(
            lock,
            expected_variant="windows-x86_64-cuda",
            expected_python_version="3.12.10",
            semantic_graph={},
            binary_versions=None,
        )
