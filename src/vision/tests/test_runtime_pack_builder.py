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
