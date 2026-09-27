"""``build_model_pack.py`` v2: every declared artefact, derived id, measured sizes."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from tests.component_binding_v2_fixtures import LICENCE_BYTES, V1_MANIFEST, V2_MANIFEST

TOOL_PATH = Path(__file__).parents[3] / "tools" / "vision" / "build_model_pack.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("build_model_pack", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("build_model_pack_module_unloadable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fixture(tmp_path: Path, *, licence: bytes = LICENCE_BYTES):
    """The committed RTMDet manifest with small synthetic model bytes."""
    payloads = {
        "checkpoint": b"checkpoint-bytes",
        "licence-notice": licence,
        "resolved-config": b"model = dict(type='RTMDet')\n",
    }
    manifest = json.loads(V2_MANIFEST.read_text(encoding="utf-8"))
    artifacts: dict[str, Path] = {}
    for item in manifest["artifacts"]:
        role = item["artifactRole"]
        item["sha256"] = _sha(payloads[role])
        path = tmp_path / "inputs" / Path(item["relativePath"]).name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payloads[role])
        artifacts[role] = path
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path, artifacts, payloads


def _build(tool, tmp_path: Path, manifest_path: Path, artifacts: dict[str, Path], name: str = "pack", commit: str = "1" * 40):
    return tool.build_model_pack(
        source_manifest=manifest_path,
        artifacts=artifacts,
        assembled_from_commit=commit,
        output=tmp_path / name,
    )


def test_the_pack_is_v2_and_its_id_is_the_manifest_derived_id(tmp_path: Path) -> None:
    from mavi_vision.runtime.model_manifest_v2 import load_model_manifest_v2

    tool = _load_tool()
    manifest_path, artifacts, _ = _fixture(tmp_path)
    manifest = _build(tool, tmp_path, manifest_path, artifacts)

    assert manifest["schemaVersion"] == "mavi-vision-model-pack-v2"
    assert manifest["modelPackId"] == load_model_manifest_v2(manifest_path).model_pack_id
    assert manifest["modelPackId"].startswith("mavi-model-v2-")
    assert manifest["modelId"] == "rtmdet-m-coco-phase1"
    assert manifest["modelVersion"] == "1.0.0"
    assert manifest["capabilityIds"] == ["detector"]
    assert set(manifest) == {
        "schemaVersion",
        "modelPackId",
        "modelId",
        "modelVersion",
        "capabilityIds",
        "assembledFromCommit",
        "artifacts",
    }


def test_the_committed_manifest_builds_the_binding_model_pack_id() -> None:
    """With the real bytes' digests the builder's id is the id the binding pins."""
    from mavi_vision.runtime.model_manifest_v2 import load_model_manifest_v2
    from tests.component_binding_v2_fixtures import V2_BINDING

    binding = json.loads(V2_BINDING.read_text(encoding="utf-8"))
    assert load_model_manifest_v2(V2_MANIFEST).model_pack_id == binding["capabilityBindings"][0]["modelPackId"]


def test_every_declared_artefact_ships_with_a_measured_size(tmp_path: Path) -> None:
    tool = _load_tool()
    manifest_path, artifacts, payloads = _fixture(tmp_path)
    output = tmp_path / "pack"
    manifest = _build(tool, tmp_path, manifest_path, artifacts)

    persisted = (output / "model-pack-manifest.json").read_bytes()
    assert json.loads(persisted) == manifest
    assert persisted == tool.serialize_model_pack_manifest(manifest)
    roles = {item["artifactRole"]: item for item in manifest["artifacts"]}
    assert set(roles) == {"checkpoint", "licence-notice", "resolved-config"}
    for role, item in roles.items():
        path = output / Path(item["relativePath"])
        assert path.read_bytes() == payloads[role]
        assert item["sizeBytes"] == len(payloads[role]) == path.stat().st_size
        assert item["sha256"] == _sha(payloads[role])
    # The licence notice is in the built pack (P-15), in the one pack directory (P-10).
    assert (output / "rtmdet-m-coco-phase1-v1" / "LICENSE").read_bytes() == LICENCE_BYTES
    assert {Path(item["relativePath"]).parts[0] for item in manifest["artifacts"]} == {"rtmdet-m-coco-phase1-v1"}
    assert sorted(path.name for path in output.iterdir()) == ["model-pack-manifest.json", "rtmdet-m-coco-phase1-v1"]


def test_the_model_pack_id_is_independent_of_the_assembly_commit(tmp_path: Path) -> None:
    tool = _load_tool()
    manifest_path, artifacts, _ = _fixture(tmp_path)
    first = _build(tool, tmp_path, manifest_path, artifacts, "a", "1" * 40)
    second = _build(tool, tmp_path, manifest_path, artifacts, "b", "2" * 40)

    assert first["modelPackId"] == second["modelPackId"]
    assert first["assembledFromCommit"] != second["assembledFromCommit"]


def test_the_licence_notice_changes_the_model_pack_id(tmp_path: Path) -> None:
    tool = _load_tool()
    first_manifest, first_artifacts, _ = _fixture(tmp_path / "a")
    second_manifest, second_artifacts, _ = _fixture(tmp_path / "b", licence=LICENCE_BYTES + b"\n")
    first = _build(tool, tmp_path, first_manifest, first_artifacts, "pack-a")
    second = _build(tool, tmp_path, second_manifest, second_artifacts, "pack-b")

    assert first["modelPackId"] != second["modelPackId"]


@pytest.mark.parametrize("role", ["checkpoint", "licence-notice", "resolved-config"])
def test_an_artefact_hash_mismatch_is_refused_and_leaves_nothing(tmp_path: Path, role: str) -> None:
    tool = _load_tool()
    manifest_path, artifacts, _ = _fixture(tmp_path)
    artifacts[role].write_bytes(b"tampered")

    with pytest.raises(tool.ModelPackError, match=f"model_pack_artifact_hash_mismatch:{role}"):
        _build(tool, tmp_path, manifest_path, artifacts)
    assert not (tmp_path / "pack").exists()
    assert [path.name for path in tmp_path.iterdir() if path.name.startswith(".pack.")] == []


def test_a_missing_licence_notice_input_is_refused(tmp_path: Path) -> None:
    tool = _load_tool()
    manifest_path, artifacts, _ = _fixture(tmp_path)
    del artifacts["licence-notice"]

    with pytest.raises(tool.ModelPackError, match="model_pack_artifact_missing:licence-notice"):
        _build(tool, tmp_path, manifest_path, artifacts)


def test_an_undeclared_artefact_is_refused(tmp_path: Path) -> None:
    tool = _load_tool()
    manifest_path, artifacts, _ = _fixture(tmp_path)
    extra = tmp_path / "extra.bin"
    extra.write_bytes(b"x")
    artifacts["calibration"] = extra

    with pytest.raises(tool.ModelPackError, match="model_pack_artifact_undeclared:calibration"):
        _build(tool, tmp_path, manifest_path, artifacts)


def test_a_v1_source_manifest_is_refused(tmp_path: Path) -> None:
    tool = _load_tool()
    _, artifacts, _ = _fixture(tmp_path)

    with pytest.raises(tool.ModelPackError, match="model_pack_source_manifest_invalid:model_manifest_schema_unsupported"):
        _build(tool, tmp_path, V1_MANIFEST, artifacts)


def test_an_authored_size_in_the_source_is_refused(tmp_path: Path) -> None:
    tool = _load_tool()
    manifest_path, artifacts, _ = _fixture(tmp_path)
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    edited = copy.deepcopy(document)
    edited["artifacts"][0]["sizeBytes"] = 1
    manifest_path.write_text(json.dumps(edited), encoding="utf-8")

    with pytest.raises(tool.ModelPackError, match="model_pack_source_manifest_invalid"):
        _build(tool, tmp_path, manifest_path, artifacts)


def test_a_non_empty_destination_is_refused(tmp_path: Path) -> None:
    tool = _load_tool()
    manifest_path, artifacts, _ = _fixture(tmp_path)
    (tmp_path / "pack").mkdir()
    (tmp_path / "pack" / "other").write_bytes(b"x")

    with pytest.raises(tool.ModelPackError, match="model_pack_destination_not_empty"):
        _build(tool, tmp_path, manifest_path, artifacts)
