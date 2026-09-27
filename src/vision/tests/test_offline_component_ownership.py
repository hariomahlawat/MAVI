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


RUNTIME_ID = "mavi-runtime-v2-" + "a" * 64
MODEL_A = "mavi-model-v2-" + "b" * 64
MODEL_B = "mavi-model-v2-" + "c" * 64


def _write_model(kit: Path, model_id: str, payload: bytes) -> dict:
    root = kit / "vision" / "models" / model_id
    root.mkdir(parents=True)
    manifest = {
        "schemaVersion": "mavi-vision-model-pack-v2",
        "modelPackId": model_id,
        "artifacts": [{"relativePath": "pack/model.bin", "sha256": _sha(payload), "artifactRole": "checkpoint"}],
    }
    (root / "model-pack-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return {"modelPackId": model_id, "relativePath": f"vision/models/{model_id}"}


def _write_kit(tmp_path: Path, *, runtime_payload: bytes, model_payloads: dict[str, bytes]) -> Path:
    kit = tmp_path / "kit"
    runtime_root = kit / "vision" / "runtime" / RUNTIME_ID
    runtime_root.mkdir(parents=True)
    runtime_manifest = {
        "schemaVersion": "mavi-vision-runtime-pack-v2",
        "runtimePackId": RUNTIME_ID,
        "artifacts": [{"relativePath": "runtime.bin", "sha256": _sha(runtime_payload)}],
    }
    (runtime_root / "runtime-pack-manifest.json").write_text(json.dumps(runtime_manifest), encoding="utf-8")
    models = [_write_model(kit, model_id, payload) for model_id, payload in model_payloads.items()]
    inventory = {
        "schemaVersion": "mavi-offline-vision-component-inventory-v2",
        "runtimePacks": [{"runtimePackId": RUNTIME_ID, "relativePath": f"vision/runtime/{RUNTIME_ID}"}],
        "modelPacks": models,
        "applicationOverlay": {
            "revision": "1" * 40,
            "componentBinding": "phase1-bindings-v2.json",
            "componentBindingSha256": "c" * 64,
        },
    }
    (kit / "vision" / "component-inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
    return kit


def test_accepts_disjoint_runtime_model_and_overlay_ownership(tmp_path: Path) -> None:
    kit = _write_kit(tmp_path, runtime_payload=b"runtime", model_payloads={MODEL_A: b"model-a", MODEL_B: b"model-b"})
    result = verify_component_ownership(kit)
    assert result["crossComponentDuplicates"] == 0
    assert result["runtimeArtifactCount"] == 1
    assert result["modelArtifactCount"] == 2
    assert result["modelPackIds"] == [MODEL_A, MODEL_B]


def test_rejects_same_heavy_artifact_in_runtime_and_model_packs(tmp_path: Path) -> None:
    kit = _write_kit(tmp_path, runtime_payload=b"same-heavy-bytes", model_payloads={MODEL_A: b"same-heavy-bytes"})
    with pytest.raises(ComponentOwnershipError, match="cross_component_artifact_duplicate"):
        verify_component_ownership(kit)


def test_rejects_same_heavy_artifact_in_two_model_packs(tmp_path: Path) -> None:
    kit = _write_kit(tmp_path, runtime_payload=b"runtime", model_payloads={MODEL_A: b"shared", MODEL_B: b"shared"})
    with pytest.raises(ComponentOwnershipError, match=f"cross_component_artifact_duplicate:.*model:{MODEL_A}.*model:{MODEL_B}"):
        verify_component_ownership(kit)


def test_rejects_a_v1_inventory_or_model_pack(tmp_path: Path) -> None:
    kit = _write_kit(tmp_path, runtime_payload=b"runtime", model_payloads={MODEL_A: b"model"})
    manifest_path = kit / "vision" / "models" / MODEL_A / "model-pack-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schemaVersion"] = "mavi-vision-model-pack-v1"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ComponentOwnershipError, match="model_component_identity_invalid"):
        verify_component_ownership(kit)

    inventory_path = kit / "vision" / "component-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory["schemaVersion"] = "mavi-offline-vision-component-inventory-v1"
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    with pytest.raises(ComponentOwnershipError, match="component_inventory_schema_invalid"):
        verify_component_ownership(kit)


def test_rejects_a_pack_stored_under_another_id(tmp_path: Path) -> None:
    kit = _write_kit(tmp_path, runtime_payload=b"runtime", model_payloads={MODEL_A: b"model"})
    inventory_path = kit / "vision" / "component-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory["modelPacks"][0]["modelPackId"] = MODEL_B
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    with pytest.raises(ComponentOwnershipError, match="model_component_location_invalid"):
        verify_component_ownership(kit)


def test_rejects_application_overlay_claiming_component_payload_location(tmp_path: Path) -> None:
    kit = _write_kit(tmp_path, runtime_payload=b"runtime", model_payloads={MODEL_A: b"model"})
    inventory_path = kit / "vision" / "component-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory["applicationOverlay"]["relativePath"] = "vision/application/overlay"
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    with pytest.raises(ComponentOwnershipError, match="application_overlay_inventory_boundary_invalid"):
        verify_component_ownership(kit)
