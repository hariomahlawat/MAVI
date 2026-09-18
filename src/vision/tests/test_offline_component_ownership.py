from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
TOOL = ROOT / "tools/vision/verify_offline_component_ownership.py"
spec = importlib.util.spec_from_file_location("_offline_component_ownership", TOOL)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

ComponentOwnershipError = module.ComponentOwnershipError
verify_component_ownership = module.verify_component_ownership


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_kit(tmp_path: Path, *, runtime_payload: bytes, model_payload: bytes) -> Path:
    kit = tmp_path / "kit"
    runtime_id = "mavi-runtime-v2-" + "a" * 64
    model_id = "mavi-model-v1-" + "b" * 64
    runtime_root = kit / "vision" / "runtime" / runtime_id
    model_root = kit / "vision" / "models" / model_id
    runtime_root.mkdir(parents=True)
    model_root.mkdir(parents=True)
    runtime_manifest = {
        "schemaVersion": "mavi-vision-runtime-pack-v2",
        "runtimePackId": runtime_id,
        "artifacts": [{"relativePath": "runtime.bin", "sha256": _sha(runtime_payload)}],
    }
    model_manifest = {
        "schemaVersion": "mavi-vision-model-pack-v1",
        "modelPackId": model_id,
        "artifacts": [{"relativePath": "model.bin", "sha256": _sha(model_payload)}],
    }
    (runtime_root / "runtime-pack-manifest.json").write_text(json.dumps(runtime_manifest), encoding="utf-8")
    (model_root / "model-pack-manifest.json").write_text(json.dumps(model_manifest), encoding="utf-8")
    inventory = {
        "schemaVersion": "mavi-offline-vision-component-inventory-v1",
        "runtimePack": {"runtimePackId": runtime_id, "relativePath": f"vision/runtime/{runtime_id}"},
        "modelPack": {"modelPackId": model_id, "relativePath": f"vision/models/{model_id}"},
        "applicationOverlay": {
            "revision": "1" * 40,
            "componentRequirements": "mmdetection-phase1-v1.json",
            "componentRequirementsSha256": "c" * 64,
        },
    }
    (kit / "vision" / "component-inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
    return kit


def test_accepts_disjoint_runtime_model_and_overlay_ownership(tmp_path: Path) -> None:
    kit = _write_kit(tmp_path, runtime_payload=b"runtime", model_payload=b"model")
    result = verify_component_ownership(kit)
    assert result["crossComponentDuplicates"] == 0
    assert result["runtimeArtifactCount"] == 1
    assert result["modelArtifactCount"] == 1


def test_rejects_same_heavy_artifact_in_runtime_and_model_packs(tmp_path: Path) -> None:
    kit = _write_kit(tmp_path, runtime_payload=b"same-heavy-bytes", model_payload=b"same-heavy-bytes")
    with pytest.raises(ComponentOwnershipError, match="cross_component_artifact_duplicate"):
        verify_component_ownership(kit)


def test_rejects_application_overlay_claiming_component_payload_location(tmp_path: Path) -> None:
    kit = _write_kit(tmp_path, runtime_payload=b"runtime", model_payload=b"model")
    inventory_path = kit / "vision" / "component-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory["applicationOverlay"]["relativePath"] = "vision/application/overlay"
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    with pytest.raises(ComponentOwnershipError, match="application_overlay_inventory_boundary_invalid"):
        verify_component_ownership(kit)
