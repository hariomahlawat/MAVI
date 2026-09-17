from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
TOOL = ROOT / "tools/vision/sync_offline_vision_components.py"
spec = importlib.util.spec_from_file_location("_offline_vision_components", TOOL)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

VisionComponentStoreError = module.VisionComponentStoreError
sync_vision_components = module.sync_vision_components
verify_vision_component_store = module.verify_vision_component_store


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_pack(root: Path, *, kind: str, provenance: str, payload: bytes) -> dict[str, object]:
    root.mkdir(parents=True)
    payload_path = root / "payload.bin"
    payload_path.write_bytes(payload)
    artifact = {
        "relativePath": "payload.bin",
        "sizeBytes": len(payload),
        "sha256": _sha(payload),
    }
    if kind == "runtime":
        manifest = {
            "schemaVersion": "mavi-vision-runtime-pack-v2",
            "runtimePackId": "mavi-runtime-v2-" + "a" * 64,
            "platformVariant": "windows-x86_64-cpu",
            "pythonVersion": "3.12.10",
            "nativeAbi": "win-fixture",
            "thirdPartyLockSha256": "b" * 64,
            "runtimeRequirementsSha256": "c" * 64,
            "assembledFromCommit": provenance,
            "artifacts": [artifact],
        }
        name = "runtime-pack-manifest.json"
    else:
        manifest = {
            "schemaVersion": "mavi-vision-model-pack-v1",
            "modelPackId": "mavi-model-v1-" + "d" * 64,
            "modelId": "rtmdet-m-coco-phase1",
            "checkpointSha256": "e" * 64,
            "resolvedConfigSha256": "f" * 64,
            "assembledFromCommit": provenance,
            "artifacts": [artifact],
        }
        name = "model-pack-manifest.json"
    (root / name).write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def _requirements(path: Path, runtime: dict[str, object], model: dict[str, object]) -> None:
    value = {
        "schemaVersion": "mavi-vision-component-requirements-v1",
        "runtimeProfileId": "mmdetection-phase1-v1",
        "runtimePacks": {
            "windows-x86_64-cpu": {
                "runtimePackId": runtime["runtimePackId"],
                "thirdPartyLockSha256": runtime["thirdPartyLockSha256"],
                "runtimeRequirementsSha256": runtime["runtimeRequirementsSha256"],
                "nativeAbi": runtime["nativeAbi"],
            }
        },
        "modelPack": {
            "modelPackId": model["modelPackId"],
            "modelId": model["modelId"],
            "checkpointSha256": model["checkpointSha256"],
            "resolvedConfigSha256": model["resolvedConfigSha256"],
        },
    }
    path.write_text(json.dumps(value), encoding="utf-8")


def test_reuses_heavy_components_when_only_provenance_changes(tmp_path: Path) -> None:
    first_runtime = _write_pack(
        tmp_path / "runtime-a", kind="runtime", provenance="1" * 40, payload=b"runtime"
    )
    first_model = _write_pack(
        tmp_path / "model-a", kind="model", provenance="1" * 40, payload=b"model"
    )
    requirements = tmp_path / "components.json"
    _requirements(requirements, first_runtime, first_model)
    kit = tmp_path / "kit"

    first = sync_vision_components(
        kit_root=kit,
        runtime_pack_root=tmp_path / "runtime-a",
        model_pack_root=tmp_path / "model-a",
        component_requirements_path=requirements,
        application_revision="1" * 40,
    )
    assert first["runtimeReused"] is False
    assert first["modelReused"] is False

    runtime_root = kit / "vision/runtime" / str(first_runtime["runtimePackId"])
    model_root = kit / "vision/models" / str(first_model["modelPackId"])
    runtime_manifest_before = json.loads(
        (runtime_root / "runtime-pack-manifest.json").read_text(encoding="utf-8")
    )
    model_manifest_before = json.loads(
        (model_root / "model-pack-manifest.json").read_text(encoding="utf-8")
    )
    assert runtime_manifest_before["assembledFromCommit"] == "1" * 40
    assert model_manifest_before["assembledFromCommit"] == "1" * 40

    _write_pack(
        tmp_path / "runtime-b", kind="runtime", provenance="2" * 40, payload=b"runtime"
    )
    _write_pack(
        tmp_path / "model-b", kind="model", provenance="2" * 40, payload=b"model"
    )
    second = sync_vision_components(
        kit_root=kit,
        runtime_pack_root=tmp_path / "runtime-b",
        model_pack_root=tmp_path / "model-b",
        component_requirements_path=requirements,
        application_revision="2" * 40,
    )
    assert second["runtimeReused"] is True
    assert second["modelReused"] is True
    # Reuse means the stored heavy component is not replaced by the later
    # provenance manifest; only the small application inventory advances.
    assert json.loads(
        (runtime_root / "runtime-pack-manifest.json").read_text(encoding="utf-8")
    )["assembledFromCommit"] == "1" * 40
    assert json.loads(
        (model_root / "model-pack-manifest.json").read_text(encoding="utf-8")
    )["assembledFromCommit"] == "1" * 40
    assert (runtime_root / "payload.bin").read_bytes() == b"runtime"
    assert (model_root / "payload.bin").read_bytes() == b"model"
    inventory = verify_vision_component_store(kit)
    assert inventory["applicationOverlay"]["revision"] == "2" * 40


def test_rejects_same_component_id_with_different_payload(tmp_path: Path) -> None:
    runtime = _write_pack(
        tmp_path / "runtime-a", kind="runtime", provenance="1" * 40, payload=b"runtime-a"
    )
    model = _write_pack(
        tmp_path / "model", kind="model", provenance="1" * 40, payload=b"model"
    )
    requirements = tmp_path / "components.json"
    _requirements(requirements, runtime, model)
    kit = tmp_path / "kit"
    sync_vision_components(
        kit_root=kit,
        runtime_pack_root=tmp_path / "runtime-a",
        model_pack_root=tmp_path / "model",
        component_requirements_path=requirements,
        application_revision="1" * 40,
    )
    _write_pack(
        tmp_path / "runtime-b", kind="runtime", provenance="2" * 40, payload=b"runtime-b"
    )
    with pytest.raises(VisionComponentStoreError, match="component_id_collision"):
        sync_vision_components(
            kit_root=kit,
            runtime_pack_root=tmp_path / "runtime-b",
            model_pack_root=tmp_path / "model",
            component_requirements_path=requirements,
            application_revision="2" * 40,
        )


def test_rejects_pack_not_required_by_application_overlay(tmp_path: Path) -> None:
    runtime = _write_pack(
        tmp_path / "runtime", kind="runtime", provenance="1" * 40, payload=b"runtime"
    )
    model = _write_pack(
        tmp_path / "model", kind="model", provenance="1" * 40, payload=b"model"
    )
    requirements = tmp_path / "components.json"
    _requirements(requirements, runtime, model)
    value = json.loads(requirements.read_text())
    value["runtimePacks"]["windows-x86_64-cpu"]["runtimePackId"] = (
        "mavi-runtime-v2-" + "9" * 64
    )
    requirements.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(
        VisionComponentStoreError,
        match="runtime_requirement_mismatch:runtimePackId",
    ):
        sync_vision_components(
            kit_root=tmp_path / "kit",
            runtime_pack_root=tmp_path / "runtime",
            model_pack_root=tmp_path / "model",
            component_requirements_path=requirements,
            application_revision="1" * 40,
        )


def test_rejects_symlink_inside_component(tmp_path: Path) -> None:
    runtime = _write_pack(
        tmp_path / "runtime", kind="runtime", provenance="1" * 40, payload=b"runtime"
    )
    model = _write_pack(
        tmp_path / "model", kind="model", provenance="1" * 40, payload=b"model"
    )
    requirements = tmp_path / "components.json"
    _requirements(requirements, runtime, model)
    link = tmp_path / "runtime" / "unexpected-link"
    try:
        link.symlink_to(tmp_path / "runtime" / "payload.bin")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this test host")
    with pytest.raises(VisionComponentStoreError, match="component_symlink_forbidden"):
        sync_vision_components(
            kit_root=tmp_path / "kit",
            runtime_pack_root=tmp_path / "runtime",
            model_pack_root=tmp_path / "model",
            component_requirements_path=requirements,
            application_revision="1" * 40,
        )


def test_rejects_malformed_runtime_pack_map(tmp_path: Path) -> None:
    runtime = _write_pack(
        tmp_path / "runtime", kind="runtime", provenance="1" * 40, payload=b"runtime"
    )
    model = _write_pack(
        tmp_path / "model", kind="model", provenance="1" * 40, payload=b"model"
    )
    requirements = tmp_path / "components.json"
    _requirements(requirements, runtime, model)
    value = json.loads(requirements.read_text())
    value["runtimePacks"] = []
    requirements.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(VisionComponentStoreError, match="component_requirements_incomplete"):
        sync_vision_components(
            kit_root=tmp_path / "kit",
            runtime_pack_root=tmp_path / "runtime",
            model_pack_root=tmp_path / "model",
            component_requirements_path=requirements,
            application_revision="1" * 40,
        )
