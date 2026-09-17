from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


TOOL_PATH = Path(__file__).parents[3] / "tools" / "vision" / "build_model_pack.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("build_model_pack", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("build_model_pack_module_unloadable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fixture(tmp_path: Path):
    checkpoint = tmp_path / "rtmdet.pth"
    config = tmp_path / "rtmdet_resolved.py"
    checkpoint.write_bytes(b"checkpoint-bytes")
    config.write_bytes(b"model = dict(type='RTMDet')\n")

    import hashlib

    manifest = {
        "schemaVersion": "1.0",
        "modelId": "rtmdet-m-coco-phase1",
        "checkpoint": {
            "relativePath": "rtmdet-m-coco-phase1-v1/rtmdet.pth",
            "sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        },
        "resolvedConfig": {
            "relativePath": "rtmdet-m-coco-phase1-v1/rtmdet_resolved.py",
            "sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
        },
    }
    manifest_path = tmp_path / "model-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, checkpoint, config


def test_model_pack_id_is_independent_of_assembly_commit(tmp_path: Path) -> None:
    tool = _load_tool()
    manifest_path, checkpoint, config = _fixture(tmp_path)

    first = tool.build_model_pack(
        source_manifest=manifest_path,
        checkpoint=checkpoint,
        resolved_config=config,
        assembled_from_commit="1" * 40,
        output=tmp_path / "pack-a",
    )
    second = tool.build_model_pack(
        source_manifest=manifest_path,
        checkpoint=checkpoint,
        resolved_config=config,
        assembled_from_commit="2" * 40,
        output=tmp_path / "pack-b",
    )

    assert first["modelPackId"] == second["modelPackId"]
    assert first["modelPackId"].startswith("mavi-model-v1-")
    assert first["assembledFromCommit"] != second["assembledFromCommit"]
    assert first["checkpointSha256"] == second["checkpointSha256"]
    assert first["resolvedConfigSha256"] == second["resolvedConfigSha256"]


def test_model_pack_manifest_enumerates_only_verified_model_assets(tmp_path: Path) -> None:
    tool = _load_tool()
    manifest_path, checkpoint, config = _fixture(tmp_path)
    output = tmp_path / "pack"

    manifest = tool.build_model_pack(
        source_manifest=manifest_path,
        checkpoint=checkpoint,
        resolved_config=config,
        assembled_from_commit="3" * 40,
        output=output,
    )

    persisted = json.loads((output / "model-pack-manifest.json").read_text())
    assert persisted == manifest
    assert [item["purpose"] for item in manifest["artifacts"]] == [
        "model-checkpoint",
        "resolved-model-config",
    ]
    for item in manifest["artifacts"]:
        path = output / Path(item["relativePath"])
        assert path.is_file()
        assert path.stat().st_size == item["sizeBytes"]


def test_model_pack_rejects_asset_hash_mismatch(tmp_path: Path) -> None:
    tool = _load_tool()
    manifest_path, checkpoint, config = _fixture(tmp_path)
    checkpoint.write_bytes(b"tampered")

    with pytest.raises(tool.ModelPackError, match="model_pack_checkpoint_hash_mismatch"):
        tool.build_model_pack(
            source_manifest=manifest_path,
            checkpoint=checkpoint,
            resolved_config=config,
            assembled_from_commit="4" * 40,
            output=tmp_path / "pack",
        )
