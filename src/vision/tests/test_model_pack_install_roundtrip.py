"""Installability across the language boundary (S2a plan §5.4, §13.1 item 5b).

A Model Pack built by the Python builder (``tools/vision/build_model_pack.py``)
is installed by the PowerShell installer (``Install-MaviVisionModelPack.ps1``)
into a temporary shared store, and the worker's Python resolver then resolves
the vision role from that store. This proves that the three agree on the pack
format, on the store layout (``<store>/<packDirectory>/``, P-10) and on the
licence notice, with no hand-written fixture in between.

PowerShell is present on the hosted Linux and Windows runners; where it is
not, the test is skipped (never passed).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.resolver_overlay import Overlay

REPOSITORY = Path(__file__).resolve().parents[3]
INSTALLER = REPOSITORY / "tools/setup/Install-MaviVisionModelPack.ps1"
BUILDER = REPOSITORY / "tools/vision/build_model_pack.py"
PWSH = shutil.which("pwsh") or shutil.which("powershell")

pytestmark = pytest.mark.skipif(PWSH is None, reason="PowerShell is not installed on this host")


def _builder():
    spec = importlib.util.spec_from_file_location("build_model_pack_roundtrip", BUILDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _install(pack: Path, store: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-File", str(INSTALLER), "-PackRoot", str(pack), "-StoreRoot", str(store), "-NoMachineEnvironment"],
        capture_output=True,
        text=True,
        timeout=300,
    )


def _build(overlay: Overlay, tmp_path: Path, name: str) -> tuple[Path, dict]:
    artifacts = {}
    for item in overlay.manifest["artifacts"]:
        source = tmp_path / f"{name}-inputs" / Path(item["relativePath"]).name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(overlay.artifacts[item["artifactRole"]])
        artifacts[item["artifactRole"]] = source
    output = tmp_path / name
    manifest = _builder().build_model_pack(
        source_manifest=overlay.manifest_path,
        artifacts=artifacts,
        assembled_from_commit="1" * 40,
        output=output,
    )
    return output, manifest


def test_a_built_pack_installs_and_the_worker_resolves_it(tmp_path: Path) -> None:
    overlay = Overlay.create(tmp_path / "repo")
    pack, built = _build(overlay, tmp_path, "pack")
    store = tmp_path / "store"
    store.mkdir()

    result = _install(pack, store)
    assert result.returncode == 0, result.stderr + result.stdout

    pack_directory = store / "rtmdet-m-coco-phase1-v1"
    state = json.loads((pack_directory / "model-install.json").read_text(encoding="utf-8-sig"))
    assert state["schemaVersion"] == "mavi-vision-model-install-v2"
    assert state["modelPackId"] == built["modelPackId"] == overlay.derived_model_pack_id()
    assert state["modelPackManifestSha256"] == hashlib.sha256(
        (pack_directory / "model-pack-manifest.json").read_bytes()
    ).hexdigest()
    # The licence notice is installed with its identity-bearing digest (P-15).
    notice = pack_directory / "LICENSE"
    assert notice.read_bytes() == overlay.artifacts["licence-notice"]
    assert state["artifactSha256"]["licence-notice"] == hashlib.sha256(notice.read_bytes()).hexdigest()

    # The worker's resolver reads the installed store as its model root.
    overlay.model_root = store
    resolved = overlay.resolve()
    capability = resolved.capabilities["detector"]
    assert capability.model_pack_id == built["modelPackId"]
    assert capability.artifact_paths["licence-notice"] == notice.resolve()


def test_installing_a_second_pack_leaves_the_first_byte_identical(tmp_path: Path) -> None:
    first = Overlay.create(tmp_path / "first")
    pack_a, _ = _build(first, tmp_path, "pack-a")
    second = Overlay.create(tmp_path / "second")
    for item in second.manifest["artifacts"]:
        item["relativePath"] = item["relativePath"].replace("rtmdet-m-coco-phase1-v1/", "rtmdet-m-coco-other-v1/")
    second.manifest["modelId"] = "rtmdet-m-coco-other"
    second.artifacts["checkpoint"] = b"another checkpoint\n"
    second.write()
    pack_b, _ = _build(second, tmp_path, "pack-b")
    store = tmp_path / "store"
    store.mkdir()
    assert _install(pack_a, store).returncode == 0

    def fingerprint(root: Path) -> dict[str, str]:
        return {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    before = fingerprint(store / "rtmdet-m-coco-phase1-v1")
    result = _install(pack_b, store)
    assert result.returncode == 0, result.stderr + result.stdout
    assert fingerprint(store / "rtmdet-m-coco-phase1-v1") == before
    assert (store / "rtmdet-m-coco-other-v1" / "model-install.json").is_file()


def test_a_v1_install_state_is_refused_and_left_as_it_was(tmp_path: Path) -> None:
    overlay = Overlay.create(tmp_path / "repo")
    pack, _ = _build(overlay, tmp_path, "pack")
    store = tmp_path / "store"
    legacy = store / "rtmdet-m-coco-phase1-v1"
    legacy.mkdir(parents=True)
    (legacy / "model-install.json").write_text(json.dumps({"schemaVersion": "mavi-vision-model-install-v1"}), encoding="utf-8")

    result = _install(pack, store)
    assert result.returncode != 0
    assert "model_install_state_v1_rejected" in result.stderr + result.stdout
    assert sorted(path.name for path in legacy.iterdir()) == ["model-install.json"]
