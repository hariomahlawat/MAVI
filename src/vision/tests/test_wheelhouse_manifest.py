"""A C2 wheelhouse must be able to say what each artefact is and where it came from.

C2 mixes three acquisition sources -- the PyTorch CUDA index, ordinary PyPI and
a locally compiled MMCV -- so every negative case here is about the manifest
refusing to describe a wheelhouse it cannot fully account for.

Every wheel is synthesised in-test; nothing depends on repository state.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest


TOOL_PATH = (
    Path(__file__).resolve().parents[3]
    / "tools"
    / "vision"
    / "build_wheelhouse_manifest.py"
)

_CU124_INDEX = "https://download.pytorch.org/whl/cu124"
_PYPI = "https://pypi.org/simple"
_MMCV_REPO = "https://github.com/open-mmlab/mmcv.git"
_MMCV_COMMIT = "57c4e25e06e2d4f8a9357c84bcd24089a284dc88"
_TOOLCHAIN = "win_amd64-msvc-14.44.35207-sdk-10.0.26100.0-cuda12.4-sm75"


def _load():
    spec = importlib.util.spec_from_file_location("build_wheelhouse_manifest", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("wheelhouse_manifest_module_unloadable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_wheel(
    root: Path,
    *,
    name: str,
    version: str,
    tag: str = "cp312-cp312-win_amd64",
    requires_dist: tuple[str, ...] = (),
) -> Path:
    normalized = name.replace("-", "_")
    path = root / f"{normalized}-{version}-{tag}.whl"
    root.mkdir(parents=True, exist_ok=True)
    dist_info = f"{normalized}-{version}.dist-info"
    requires = "".join(f"Requires-Dist: {item}\n" for item in requires_dist)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"{dist_info}/METADATA",
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n{requires}\n",
        )
        archive.writestr(
            f"{dist_info}/WHEEL",
            f"Wheel-Version: 1.0\nGenerator: mavi-tests\n"
            f"Root-Is-Purelib: false\nTag: {tag}\n\n",
        )
        archive.writestr(f"{dist_info}/RECORD", f"{dist_info}/RECORD,,\n")
    return path


def _cuda_wheelhouse(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    house = tmp_path / "wheelhouse"
    torch = _write_wheel(house, name="torch", version="2.6.0+cu124")
    vision = _write_wheel(house, name="torchvision", version="0.21.0+cu124")
    mmcv = _write_wheel(house, name="mmcv", version="2.1.0")
    origins = {
        torch.name: {"kind": "index", "indexUrl": _CU124_INDEX},
        vision.name: {"kind": "index", "indexUrl": _CU124_INDEX},
        mmcv.name: {
            "kind": "local-build",
            "sourceRepository": _MMCV_REPO,
            "sourceCommit": _MMCV_COMMIT,
            "buildToolchain": _TOOLCHAIN,
        },
    }
    return house, origins


def _build(module, house: Path, origins: dict[str, object], variant="windows-x86_64-cuda"):
    return module.build_manifest(
        wheelhouse=house,
        platform_variant=variant,
        python_version="3.12.10",
        origins=origins,
    )


def test_manifest_records_identity_and_origin_for_every_wheel(tmp_path: Path) -> None:
    module = _load()
    house, origins = _cuda_wheelhouse(tmp_path)

    manifest = _build(module, house, origins)

    assert manifest["schemaVersion"] == "mavi-wheelhouse-manifest-v1"
    assert manifest["wheelCount"] == 3
    by_package = {item["package"]: item for item in manifest["wheels"]}

    torch = by_package["torch"]
    assert torch["version"] == "2.6.0+cu124"
    assert torch["origin"] == {"kind": "index", "indexUrl": _CU124_INDEX}
    assert len(torch["sha256"]) == 64
    assert torch["sizeBytes"] > 0
    assert torch["wheelTags"] == ["cp312-cp312-win_amd64"]
    assert torch["filename"].endswith("-cp312-cp312-win_amd64.whl")

    mmcv = by_package["mmcv"]
    assert mmcv["origin"]["kind"] == "local-build"
    assert mmcv["origin"]["sourceCommit"] == _MMCV_COMMIT
    assert mmcv["origin"]["buildToolchain"] == _TOOLCHAIN


def test_manifest_inventory_is_deterministic(tmp_path: Path) -> None:
    """Two runs over the same wheelhouse must serialise identically."""
    module = _load()
    house, origins = _cuda_wheelhouse(tmp_path)

    first = json.dumps(_build(module, house, origins), sort_keys=True)
    second = json.dumps(_build(module, house, origins), sort_keys=True)

    assert first == second
    packages = [item["package"] for item in _build(module, house, origins)["wheels"]]
    assert packages == sorted(packages)


def test_a_wheel_with_no_declared_origin_is_refused(tmp_path: Path) -> None:
    module = _load()
    house, origins = _cuda_wheelhouse(tmp_path)
    origins.pop(next(k for k in origins if k.startswith("mmcv")))

    with pytest.raises(module.WheelhouseManifestError, match="wheelhouse_origin_missing"):
        _build(module, house, origins)


def test_an_origin_naming_an_absent_wheel_is_refused(tmp_path: Path) -> None:
    """The declaration and the wheelhouse must describe the same thing."""
    module = _load()
    house, origins = _cuda_wheelhouse(tmp_path)
    origins["ghost-1.0.0-cp312-cp312-win_amd64.whl"] = {
        "kind": "index",
        "indexUrl": _PYPI,
    }

    with pytest.raises(
        module.WheelhouseManifestError, match="wheelhouse_origin_unmatched"
    ):
        _build(module, house, origins)


def test_a_stray_non_wheel_file_is_refused(tmp_path: Path) -> None:
    module = _load()
    house, origins = _cuda_wheelhouse(tmp_path)
    (house / "notes.txt").write_text("stray\n", encoding="utf-8")

    with pytest.raises(
        module.WheelhouseManifestError, match="wheelhouse_unexpected_file"
    ):
        _build(module, house, origins)


def test_an_empty_wheelhouse_is_refused(tmp_path: Path) -> None:
    module = _load()
    house = tmp_path / "wheelhouse"
    house.mkdir()

    with pytest.raises(module.WheelhouseManifestError, match="wheelhouse_empty"):
        _build(module, house, {})


def test_cpu_torch_is_refused_in_a_cuda_wheelhouse(tmp_path: Path) -> None:
    """The defect C2 most needs to prevent: CPU Torch labelled CUDA."""
    module = _load()
    house = tmp_path / "wheelhouse"
    torch = _write_wheel(house, name="torch", version="2.6.0+cpu")
    origins = {torch.name: {"kind": "index", "indexUrl": _CU124_INDEX}}

    with pytest.raises(
        module.WheelhouseManifestError, match="wheelhouse_cuda_binary_build_required"
    ):
        _build(module, house, origins)


def test_plain_torch_without_a_local_version_is_refused_for_cuda(
    tmp_path: Path,
) -> None:
    """A bare 2.6.0 from PyPI is not a proven CUDA build."""
    module = _load()
    house = tmp_path / "wheelhouse"
    torch = _write_wheel(house, name="torch", version="2.6.0")
    origins = {torch.name: {"kind": "index", "indexUrl": _PYPI}}

    with pytest.raises(
        module.WheelhouseManifestError, match="wheelhouse_cuda_binary_build_required"
    ):
        _build(module, house, origins)


def test_cuda_torch_is_refused_in_a_cpu_wheelhouse(tmp_path: Path) -> None:
    module = _load()
    house = tmp_path / "wheelhouse"
    torch = _write_wheel(house, name="torch", version="2.6.0+cu124", tag="cp312-cp312-win_amd64")
    origins = {torch.name: {"kind": "index", "indexUrl": _CU124_INDEX}}

    with pytest.raises(
        module.WheelhouseManifestError, match="wheelhouse_cpu_binary_build_required"
    ):
        _build(module, house, origins, variant="windows-x86_64-cpu")


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        ({"kind": "index"}, "wheelhouse_origin_index_url_invalid"),
        (
            {"kind": "index", "indexUrl": "http://insecure.invalid/simple"},
            "wheelhouse_origin_index_url_invalid",
        ),
        ({"kind": "mystery"}, "wheelhouse_origin_kind_invalid"),
        ({}, "wheelhouse_origin_kind_invalid"),
        (
            {"kind": "local-build", "sourceRepository": _MMCV_REPO,
             "sourceCommit": "abc", "buildToolchain": _TOOLCHAIN},
            "wheelhouse_origin_source_commit_invalid",
        ),
        (
            {"kind": "local-build", "sourceRepository": _MMCV_REPO,
             "sourceCommit": _MMCV_COMMIT, "buildToolchain": ""},
            "wheelhouse_origin_build_toolchain_invalid",
        ),
        (
            {"kind": "local-build", "sourceRepository": "git@github.com:x/y.git",
             "sourceCommit": _MMCV_COMMIT, "buildToolchain": _TOOLCHAIN},
            "wheelhouse_origin_source_repository_invalid",
        ),
    ],
)
def test_malformed_origins_are_refused(
    tmp_path: Path,
    origin: dict,
    expected: str,
) -> None:
    module = _load()
    house = tmp_path / "wheelhouse"
    wheel = _write_wheel(house, name="mmcv", version="2.1.0")

    with pytest.raises(module.WheelhouseManifestError, match=expected):
        _build(module, house, {wheel.name: origin})


def test_a_locally_built_wheel_must_name_its_source_commit(tmp_path: Path) -> None:
    """MMCV is compiled, not downloaded; its provenance is the commit."""
    module = _load()
    house = tmp_path / "wheelhouse"
    wheel = _write_wheel(house, name="mmcv", version="2.1.0")

    manifest = _build(
        module,
        house,
        {
            wheel.name: {
                "kind": "local-build",
                "sourceRepository": _MMCV_REPO,
                "sourceCommit": _MMCV_COMMIT,
                "buildToolchain": _TOOLCHAIN,
            }
        },
    )

    origin = manifest["wheels"][0]["origin"]
    assert origin["sourceCommit"] == _MMCV_COMMIT
    assert origin["sourceRepository"] == _MMCV_REPO


def test_a_wheel_for_the_wrong_platform_is_refused(tmp_path: Path) -> None:
    module = _load()
    house = tmp_path / "wheelhouse"
    wheel = _write_wheel(
        house, name="mmcv", version="2.1.0", tag="cp312-cp312-manylinux_2_39_x86_64"
    )

    with pytest.raises(module.WheelhouseManifestError, match="wheelhouse_wheel_invalid"):
        _build(module, house, {wheel.name: {"kind": "index", "indexUrl": _PYPI}})


def test_manifest_never_claims_qualification(tmp_path: Path) -> None:
    module = _load()
    house, origins = _cuda_wheelhouse(tmp_path)

    note = _build(module, house, origins)["note"].casefold()

    assert "not a runtime, hardware or production qualification" in note


def test_output_file_is_never_overwritten(tmp_path: Path, monkeypatch) -> None:
    module = _load()
    house, origins = _cuda_wheelhouse(tmp_path)
    origins_path = tmp_path / "origins.json"
    origins_path.write_text(json.dumps(origins), encoding="utf-8")
    output = tmp_path / "manifest.json"
    output.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_wheelhouse_manifest.py",
            "--wheelhouse", str(house),
            "--platform-variant", "windows-x86_64-cuda",
            "--python-version", "3.12.10",
            "--origins", str(origins_path),
            "--output", str(output),
        ],
    )

    assert module.main() == 2
    assert output.read_text(encoding="utf-8") == "{}\n"
