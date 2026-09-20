from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import zipfile

import pytest

from mavi_vision.runtime.offline_lock import (
    LockedDistribution,
    OfflineRuntimeLock,
    serialize_offline_runtime_lock,
)
from mavi_vision.runtime.requirements_projection import (
    RuntimeRequirementsProjection,
    serialize_runtime_requirements_projection,
)

TOOL_PATH = Path(__file__).parents[3] / "tools" / "vision" / "build_runtime_pack.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("build_runtime_pack", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("build_runtime_pack_module_unloadable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_wheel(root: Path, *, name: str, version: str) -> Path:
    normalized = name.replace("-", "_")
    filename = f"{normalized}-{version}-py3-none-any.whl"
    path = root / filename
    root.mkdir(parents=True, exist_ok=True)
    dist_info = f"{normalized}-{version}.dist-info"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"{dist_info}/METADATA",
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n",
        )
        archive.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\nGenerator: mavi-tests\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n",
        )
        archive.writestr(f"{dist_info}/RECORD", f"{dist_info}/RECORD,,\n")
    return path


def _fixture(tmp_path: Path):
    tool = _load_tool()
    wheelhouse = tmp_path / "wheelhouse"
    wheel = _write_wheel(wheelhouse, name="httpx", version="0.28.1")
    lock = OfflineRuntimeLock(
        schema_version="mavi-offline-lock-v1",
        platform_variant="windows-x86_64-cpu",
        python_version="3.12.10",
        distributions=(
            LockedDistribution(
                name="httpx",
                version="0.28.1",
                sha256=tool.sha256_file(wheel),
            ),
        ),
    )
    lock_path = tmp_path / "windows-x86_64-cpu.lock"
    lock_path.write_bytes(serialize_offline_runtime_lock(lock))
    requirements = RuntimeRequirementsProjection(
        schema_version="mavi-vision-runtime-requirements-v1",
        platform_variant="windows-x86_64-cpu",
        python_version="3.12.10",
        requirements=("httpx<0.29,>=0.28",),
    )
    requirements_path = tmp_path / "windows-x86_64-cpu.requirements.txt"
    requirements_path.write_bytes(serialize_runtime_requirements_projection(requirements))
    installer = tmp_path / "python-3.12.10-amd64.exe"
    installer.write_bytes(b"signed-installer-fixture")
    return tool, wheelhouse, lock_path, requirements_path, installer


def test_runtime_pack_contains_only_third_party_runtime_material(tmp_path: Path) -> None:
    tool, wheelhouse, lock_path, requirements_path, installer = _fixture(tmp_path)
    output = tmp_path / "runtime-pack"

    manifest = tool.build_runtime_pack(
        wheelhouse=wheelhouse,
        lock_path=lock_path,
        requirements_path=requirements_path,
        platform_variant="windows-x86_64-cpu",
        python_version="3.12.10",
        native_abi="win_amd64",
        python_installer=installer,
        assembled_from_commit="a" * 40,
        output=output,
    )

    assert manifest["schemaVersion"] == "mavi-vision-runtime-pack-v2"
    assert manifest["runtimePackId"].startswith("mavi-runtime-v2-")
    assert manifest["assembledFromCommit"] == "a" * 40
    assert (output / "wheels" / "httpx-0.28.1-py3-none-any.whl").is_file()
    assert not any("mavi_vision" in path.name for path in output.rglob("*"))
    declared = {item["relativePath"] for item in manifest["artifacts"]}
    assert "runtime/windows-x86_64-cpu.lock" in declared
    assert "runtime/windows-x86_64-cpu.requirements.txt" in declared
    assert "prerequisites/python/python-3.12.10-amd64.exe" in declared


def test_runtime_pack_identity_ignores_assembly_commit(tmp_path: Path) -> None:
    tool, wheelhouse, lock_path, requirements_path, installer = _fixture(tmp_path)
    first = tool.build_runtime_pack(
        wheelhouse=wheelhouse,
        lock_path=lock_path,
        requirements_path=requirements_path,
        platform_variant="windows-x86_64-cpu",
        python_version="3.12.10",
        native_abi="win_amd64",
        python_installer=installer,
        assembled_from_commit="a" * 40,
        output=tmp_path / "first",
    )
    second = tool.build_runtime_pack(
        wheelhouse=wheelhouse,
        lock_path=lock_path,
        requirements_path=requirements_path,
        platform_variant="windows-x86_64-cpu",
        python_version="3.12.10",
        native_abi="win_amd64",
        python_installer=installer,
        assembled_from_commit="b" * 40,
        output=tmp_path / "second",
    )

    assert first["runtimePackId"] == second["runtimePackId"]


def test_runtime_pack_rejects_first_party_wheel(tmp_path: Path) -> None:
    tool, wheelhouse, lock_path, requirements_path, installer = _fixture(tmp_path)
    _write_wheel(wheelhouse, name="mavi-vision", version="0.1.0")

    with pytest.raises(tool.RuntimePackError, match="runtime_pack_first_party_wheel_forbidden"):
        tool.build_runtime_pack(
            wheelhouse=wheelhouse,
            lock_path=lock_path,
            requirements_path=requirements_path,
            platform_variant="windows-x86_64-cpu",
            python_version="3.12.10",
            native_abi="win_amd64",
            python_installer=installer,
            assembled_from_commit="a" * 40,
            output=tmp_path / "runtime-pack",
        )


def test_runtime_pack_rejects_undeclared_wheel(tmp_path: Path) -> None:
    tool, wheelhouse, lock_path, requirements_path, installer = _fixture(tmp_path)
    _write_wheel(wheelhouse, name="orphan", version="1.0")

    with pytest.raises(tool.RuntimePackError, match="runtime_pack_wheelhouse_lock_mismatch"):
        tool.build_runtime_pack(
            wheelhouse=wheelhouse,
            lock_path=lock_path,
            requirements_path=requirements_path,
            platform_variant="windows-x86_64-cpu",
            python_version="3.12.10",
            native_abi="win_amd64",
            python_installer=installer,
            assembled_from_commit="a" * 40,
            output=tmp_path / "runtime-pack",
        )


def test_runtime_pack_manifest_file_is_deterministic_json(tmp_path: Path) -> None:
    tool, wheelhouse, lock_path, requirements_path, installer = _fixture(tmp_path)
    output = tmp_path / "runtime-pack"
    manifest = tool.build_runtime_pack(
        wheelhouse=wheelhouse,
        lock_path=lock_path,
        requirements_path=requirements_path,
        platform_variant="windows-x86_64-cpu",
        python_version="3.12.10",
        native_abi="win_amd64",
        python_installer=installer,
        assembled_from_commit="a" * 40,
        output=output,
    )
    payload = (output / "runtime-pack-manifest.json").read_bytes()

    assert payload.endswith(b"\n")
    assert b"\r" not in payload
    assert json.loads(payload) == manifest


# --- the build contract must describe the inputs actually packed -----------
#
# The native ABI is derived from the contract, so a `-cuda` pack's identity
# spells the contract's CUDA family. Until this check nothing tied the contract
# to the lock being packed, so a lock refrozen on another Torch build would have
# produced a pack whose identity named the qualified toolchain.

REPOSITORY_ROOT = Path(__file__).parents[3]
CUDA_CONTRACT = (
    REPOSITORY_ROOT / "config" / "vision" / "windows-cuda-development-build-v1.json"
)
CUDA_LOCK = (
    REPOSITORY_ROOT
    / "src"
    / "vision"
    / "runtime"
    / "mmdetection-phase1-v1"
    / "windows-x86_64-cuda.lock"
)


def _cuda_lock(*, torch: str = "2.6.0+cu124", torchvision: str = "0.21.0+cu124"):
    return OfflineRuntimeLock(
        schema_version="mavi-offline-lock-v1",
        platform_variant="windows-x86_64-cuda",
        python_version="3.12.10",
        distributions=(
            LockedDistribution(name="torch", version=torch, sha256="a" * 64),
            LockedDistribution(
                name="torchvision", version=torchvision, sha256="b" * 64
            ),
        ),
    )


def _cuda_contract() -> dict:
    return json.loads(CUDA_CONTRACT.read_text(encoding="utf-8"))


def test_contract_cross_check_accepts_the_committed_cuda_inputs() -> None:
    """The committed contract and the frozen CUDA lock must agree today."""
    from mavi_vision.runtime.offline_lock import load_offline_runtime_lock

    tool = _load_tool()
    contract = _cuda_contract()

    tool.validate_contract_binds_inputs(
        contract,
        platform_variant=contract["platformVariant"],
        python_version=contract["pythonVersion"],
        lock=load_offline_runtime_lock(CUDA_LOCK),
    )


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda c, k: k.update(platform_variant="windows-x86_64-cpu"),
            "runtime_pack_contract_platform_variant_mismatch",
        ),
        (
            lambda c, k: k.update(python_version="3.12.14"),
            "runtime_pack_contract_python_version_mismatch",
        ),
        (
            lambda c, k: k.update(lock=_cuda_lock(torch="2.6.0+cu121")),
            "runtime_pack_contract_binary_version_mismatch:torch",
        ),
        (
            lambda c, k: k.update(lock=_cuda_lock(torchvision="0.21.0+cpu")),
            "runtime_pack_contract_binary_version_mismatch:torchvision",
        ),
        (
            lambda c, k: k.update(
                lock=OfflineRuntimeLock(
                    schema_version="mavi-offline-lock-v1",
                    platform_variant="windows-x86_64-cuda",
                    python_version="3.12.10",
                    distributions=(
                        LockedDistribution(
                            name="torch", version="2.6.0+cu124", sha256="a" * 64
                        ),
                    ),
                )
            ),
            "runtime_pack_contract_binary_version_mismatch:torchvision",
        ),
        (
            lambda c, k: c.pop("torchBinaryVersion"),
            "runtime_pack_contract_binary_version_missing:torch",
        ),
        (
            lambda c, k: c.update(torchvisionBinaryVersion=""),
            "runtime_pack_contract_binary_version_missing:torchvision",
        ),
    ],
)
def test_contract_cross_check_refuses_inputs_the_contract_does_not_describe(
    mutate, expected: str
) -> None:
    tool = _load_tool()
    contract = _cuda_contract()
    kwargs = {
        "platform_variant": "windows-x86_64-cuda",
        "python_version": "3.12.10",
        "lock": _cuda_lock(),
    }
    mutate(contract, kwargs)

    with pytest.raises(tool.RuntimePackError) as excinfo:
        tool.validate_contract_binds_inputs(contract, **kwargs)

    assert excinfo.value.code == expected


def test_contract_cross_check_refuses_a_contract_that_is_not_an_object() -> None:
    tool = _load_tool()

    with pytest.raises(tool.RuntimePackError) as excinfo:
        tool.validate_contract_binds_inputs(
            ["not", "an", "object"],
            platform_variant="windows-x86_64-cuda",
            python_version="3.12.10",
            lock=_cuda_lock(),
        )

    assert excinfo.value.code == "runtime_pack_contract_invalid"


def test_build_refuses_a_contract_that_describes_other_inputs(
    tmp_path: Path,
) -> None:
    """The cross-check runs inside the build, before anything is published."""
    tool, wheelhouse, lock_path, requirements_path, installer = _fixture(tmp_path)
    output = tmp_path / "pack"

    with pytest.raises(tool.RuntimePackError) as excinfo:
        tool.build_runtime_pack(
            wheelhouse=wheelhouse,
            lock_path=lock_path,
            requirements_path=requirements_path,
            platform_variant="windows-x86_64-cpu",
            python_version="3.12.10",
            native_abi="win_amd64-msvc-14.44-sdk-10.0.26100.0",
            python_installer=installer,
            assembled_from_commit="1" * 40,
            output=output,
            contract=_cuda_contract(),
        )

    assert excinfo.value.code == "runtime_pack_contract_platform_variant_mismatch"
    assert not output.exists()
