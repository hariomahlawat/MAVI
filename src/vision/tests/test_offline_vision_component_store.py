"""The offline Vision component store, described by the component binding v2 (plan §7)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
TOOL = ROOT / "tools/vision/sync_offline_vision_components.py"
BINDING = ROOT / "src/vision/config/components/phase1-bindings-v2.json"
spec = importlib.util.spec_from_file_location("_offline_vision_components", TOOL)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

VisionComponentStoreError = module.VisionComponentStoreError
sync_vision_components = module.sync_vision_components
verify_vision_component_store = module.verify_vision_component_store

MODEL_PACK_ID = "mavi-model-v2-" + "d" * 64


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _binding_entry(variant: str) -> dict[str, str]:
    binding = json.loads(BINDING.read_text(encoding="utf-8"))
    return binding["runtimePacks"][0]["variants"][variant]


def _write_runtime(root: Path, *, provenance: str, payload: bytes, variant: str = "windows-x86_64-cpu", **changes) -> dict:
    """A Runtime Pack claiming exactly the committed binding's entry (never an invented id)."""
    root.mkdir(parents=True)
    (root / "payload.bin").write_bytes(payload)
    entry = _binding_entry(variant)
    manifest = {
        "schemaVersion": "mavi-vision-runtime-pack-v2",
        "runtimePackId": entry["runtimePackId"],
        "platformVariant": variant,
        "pythonVersion": "3.12.10",
        "nativeAbi": entry["nativeAbi"],
        "thirdPartyLockSha256": entry["thirdPartyLockSha256"],
        "runtimeRequirementsSha256": entry["runtimeRequirementsSha256"],
        "assembledFromCommit": provenance,
        "artifacts": [{"relativePath": "payload.bin", "sizeBytes": len(payload), "sha256": _sha(payload)}],
    }
    manifest.update(changes)
    (root / "runtime-pack-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def _write_model(root: Path, *, provenance: str, payload: bytes, model_pack_id: str = MODEL_PACK_ID, schema: str = "mavi-vision-model-pack-v2") -> dict:
    root.mkdir(parents=True)
    pack = root / "rtmdet-m-coco-phase1-v1"
    pack.mkdir()
    (pack / "checkpoint.pth").write_bytes(payload)
    (pack / "LICENSE").write_bytes(b"Apache License 2.0\n")
    manifest = {
        "schemaVersion": schema,
        "modelPackId": model_pack_id,
        "modelId": "rtmdet-m-coco-phase1",
        "modelVersion": "1.0.0",
        "capabilityIds": ["detector"],
        "assembledFromCommit": provenance,
        "artifacts": [
            {"relativePath": "rtmdet-m-coco-phase1-v1/LICENSE", "sizeBytes": 19, "sha256": _sha(b"Apache License 2.0\n"), "artifactRole": "licence-notice"},
            {"relativePath": "rtmdet-m-coco-phase1-v1/checkpoint.pth", "sizeBytes": len(payload), "sha256": _sha(payload), "artifactRole": "checkpoint"},
        ],
    }
    (root / "model-pack-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def _binding(tmp_path: Path, *, model_pack_id: str = MODEL_PACK_ID) -> Path:
    document = json.loads(BINDING.read_text(encoding="utf-8"))
    document["capabilityBindings"][0]["modelPackId"] = model_pack_id
    path = tmp_path / "phase1-bindings-v2.json"
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def _sync(tmp_path: Path, *, runtimes, models, binding=None, revision="1" * 40, kit=None):
    return sync_vision_components(
        kit_root=kit or tmp_path / "kit",
        runtime_pack_roots=[tmp_path / name for name in runtimes],
        model_pack_roots=[tmp_path / name for name in models],
        component_binding_path=binding or _binding(tmp_path),
        application_revision=revision,
    )


def test_reuses_heavy_components_when_only_provenance_changes(tmp_path: Path) -> None:
    runtime = _write_runtime(tmp_path / "runtime-a", provenance="1" * 40, payload=b"runtime")
    _write_model(tmp_path / "model-a", provenance="1" * 40, payload=b"model")
    binding = _binding(tmp_path)
    kit = tmp_path / "kit"

    first = _sync(tmp_path, runtimes=["runtime-a"], models=["model-a"], binding=binding, kit=kit)
    assert first["reused"] == {runtime["runtimePackId"]: False, MODEL_PACK_ID: False}

    runtime_root = kit / "vision/runtime" / runtime["runtimePackId"]
    model_root = kit / "vision/models" / MODEL_PACK_ID
    _write_runtime(tmp_path / "runtime-b", provenance="2" * 40, payload=b"runtime")
    _write_model(tmp_path / "model-b", provenance="2" * 40, payload=b"model")
    second = _sync(tmp_path, runtimes=["runtime-b"], models=["model-b"], binding=binding, kit=kit, revision="2" * 40)
    assert second["reused"] == {runtime["runtimePackId"]: True, MODEL_PACK_ID: True}
    # Reuse keeps the stored heavy component; only the small inventory advances.
    assert json.loads((runtime_root / "runtime-pack-manifest.json").read_text())["assembledFromCommit"] == "1" * 40
    assert json.loads((model_root / "model-pack-manifest.json").read_text())["assembledFromCommit"] == "1" * 40

    inventory = verify_vision_component_store(kit)
    assert inventory["schemaVersion"] == "mavi-offline-vision-component-inventory-v2"
    assert inventory["applicationOverlay"] == {
        "revision": "2" * 40,
        "componentBinding": "phase1-bindings-v2.json",
        "componentBindingSha256": _sha(binding.read_bytes()),
    }
    assert [item["modelPackId"] for item in inventory["modelPacks"]] == [MODEL_PACK_ID]
    assert inventory["modelPacks"][0]["materialIdentity"]["artifacts"][0]["artifactRole"] == "licence-notice"


def test_several_runtime_variants_share_one_model_pack(tmp_path: Path) -> None:
    _write_runtime(tmp_path / "win", provenance="1" * 40, payload=b"win")
    _write_runtime(tmp_path / "linux", provenance="1" * 40, payload=b"linux", variant="linux-x86_64-cpu", pythonVersion="3.12.14")
    _write_model(tmp_path / "model", provenance="1" * 40, payload=b"model")

    result = _sync(tmp_path, runtimes=["win", "linux"], models=["model"])
    assert sorted(item["platformVariant"] for item in result["runtimePacks"]) == ["linux-x86_64-cpu", "windows-x86_64-cpu"]
    verify_vision_component_store(tmp_path / "kit")


def test_rejects_same_component_id_with_different_payload(tmp_path: Path) -> None:
    _write_runtime(tmp_path / "runtime-a", provenance="1" * 40, payload=b"runtime-a")
    _write_model(tmp_path / "model", provenance="1" * 40, payload=b"model")
    binding = _binding(tmp_path)
    _sync(tmp_path, runtimes=["runtime-a"], models=["model"], binding=binding)
    _write_runtime(tmp_path / "runtime-b", provenance="2" * 40, payload=b"runtime-b")
    with pytest.raises(VisionComponentStoreError, match="component_id_collision"):
        _sync(tmp_path, runtimes=["runtime-b"], models=["model"], binding=binding, revision="2" * 40)


def test_a_kit_without_a_bound_model_pack_is_incomplete(tmp_path: Path) -> None:
    _write_runtime(tmp_path / "runtime", provenance="1" * 40, payload=b"runtime")
    with pytest.raises(VisionComponentStoreError, match=f"kit_incomplete:{MODEL_PACK_ID}"):
        _sync(tmp_path, runtimes=["runtime"], models=[])
    assert not (tmp_path / "kit").exists()


def test_a_pack_the_binding_does_not_reach_is_refused(tmp_path: Path) -> None:
    _write_runtime(tmp_path / "runtime", provenance="1" * 40, payload=b"runtime")
    _write_model(tmp_path / "model", provenance="1" * 40, payload=b"model")
    _write_model(tmp_path / "other", provenance="1" * 40, payload=b"other", model_pack_id="mavi-model-v2-" + "9" * 64)
    with pytest.raises(VisionComponentStoreError, match="kit_unbound_component:mavi-model-v2-9"):
        _sync(tmp_path, runtimes=["runtime"], models=["model", "other"])


def test_a_runtime_pack_that_is_not_the_binding_entry_is_refused(tmp_path: Path) -> None:
    _write_runtime(tmp_path / "runtime", provenance="1" * 40, payload=b"runtime", nativeAbi="win-other")
    _write_model(tmp_path / "model", provenance="1" * 40, payload=b"model")
    with pytest.raises(VisionComponentStoreError, match="runtime_requirement_mismatch:nativeAbi"):
        _sync(tmp_path, runtimes=["runtime"], models=["model"])


def test_a_class_a_variant_is_never_synchronized(tmp_path: Path) -> None:
    _write_runtime(tmp_path / "runtime", provenance="1" * 40, payload=b"runtime")
    manifest = json.loads((tmp_path / "runtime/runtime-pack-manifest.json").read_text())
    manifest["platformVariant"] = "linux-x86_64-cuda"
    (tmp_path / "runtime/runtime-pack-manifest.json").write_text(json.dumps(manifest))
    _write_model(tmp_path / "model", provenance="1" * 40, payload=b"model")
    with pytest.raises(VisionComponentStoreError, match="kit_variant_not_bound:linux-x86_64-cuda"):
        _sync(tmp_path, runtimes=["runtime"], models=["model"])


def test_a_v1_model_pack_is_refused(tmp_path: Path) -> None:
    _write_runtime(tmp_path / "runtime", provenance="1" * 40, payload=b"runtime")
    _write_model(tmp_path / "model", provenance="1" * 40, payload=b"model", schema="mavi-vision-model-pack-v1")
    with pytest.raises(VisionComponentStoreError, match="model_manifest_invalid"):
        _sync(tmp_path, runtimes=["runtime"], models=["model"])


def test_a_v1_binding_is_refused(tmp_path: Path) -> None:
    _write_runtime(tmp_path / "runtime", provenance="1" * 40, payload=b"runtime")
    _write_model(tmp_path / "model", provenance="1" * 40, payload=b"model")
    v1 = Path(__file__).parent / "fixtures/component-binding-v1/mmdetection-phase1-v1.json"
    with pytest.raises(VisionComponentStoreError, match="component_binding_invalid:component_binding_schema_unsupported"):
        _sync(tmp_path, runtimes=["runtime"], models=["model"], binding=v1)


def test_a_v1_inventory_is_refused(tmp_path: Path) -> None:
    _write_runtime(tmp_path / "runtime", provenance="1" * 40, payload=b"runtime")
    _write_model(tmp_path / "model", provenance="1" * 40, payload=b"model")
    _sync(tmp_path, runtimes=["runtime"], models=["model"])
    inventory_path = tmp_path / "kit/vision/component-inventory.json"
    inventory = json.loads(inventory_path.read_text())
    inventory["schemaVersion"] = "mavi-offline-vision-component-inventory-v1"
    inventory_path.write_text(json.dumps(inventory))
    with pytest.raises(VisionComponentStoreError, match="component_inventory_schema_invalid"):
        verify_vision_component_store(tmp_path / "kit")


def test_a_tampered_stored_artefact_is_refused(tmp_path: Path) -> None:
    _write_runtime(tmp_path / "runtime", provenance="1" * 40, payload=b"runtime")
    _write_model(tmp_path / "model", provenance="1" * 40, payload=b"model")
    _sync(tmp_path, runtimes=["runtime"], models=["model"])
    (tmp_path / "kit/vision/models" / MODEL_PACK_ID / "rtmdet-m-coco-phase1-v1/LICENSE").write_bytes(b"changed")
    with pytest.raises(VisionComponentStoreError, match="component_artifact_mismatch"):
        verify_vision_component_store(tmp_path / "kit")


def test_rejects_symlink_inside_component(tmp_path: Path) -> None:
    _write_runtime(tmp_path / "runtime", provenance="1" * 40, payload=b"runtime")
    _write_model(tmp_path / "model", provenance="1" * 40, payload=b"model")
    link = tmp_path / "runtime" / "unexpected-link"
    try:
        link.symlink_to(tmp_path / "runtime" / "payload.bin")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this test host")
    with pytest.raises(VisionComponentStoreError, match="component_symlink_forbidden"):
        _sync(tmp_path, runtimes=["runtime"], models=["model"])
