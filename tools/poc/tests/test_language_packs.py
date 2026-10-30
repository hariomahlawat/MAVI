"""PoC S10 (ADR-026, C9.1): the language payload record, staging and the launcher's verification."""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "language"))
import language_packs  # noqa: E402


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_the_committed_record_agrees_with_both_manifests():
    document = language_packs.load()
    packs = {model["packDirectory"] for model in document["models"]}
    assert packs == {"language-qwen2.5-1.5b-instruct-q8-0-dev-v1", "language-qwen2.5-7b-instruct-q4-k-m-dev-v1"}
    assert document["runtime"]["licence"]["spdxId"] == "MIT"
    for model in document["models"]:
        manifest = language_packs.load_manifest(model["manifest"])
        assert manifest["licence"]["spdxId"] == "Apache-2.0"
        assert language_packs.pack_identity(manifest).startswith("mavi-language-v1-")
    cuda = next(variant for variant in document["runtime"]["variants"] if variant["directory"] == "cuda")
    assert "sm_89" in cuda["cuda"]["sass"] and "sm_75" in cuda["cuda"]["ptx"]
    assert {"cudart64_12.dll", "cublas64_12.dll", "cublasLt64_12.dll", "llama-server.exe"} <= set(cuda["files"])


def test_pack_identity_is_material_only():
    manifest = language_packs.load_manifest("models/language/language-qwen2.5-1.5b-instruct-q8-0-dev-v1.json")
    changed = json.loads(json.dumps(manifest))
    changed["provenance"]["publisher"] = "someone else"
    assert language_packs.pack_identity(changed) == language_packs.pack_identity(manifest)
    changed["artifacts"][0]["sha256"] = "0" * 64
    assert language_packs.pack_identity(changed) != language_packs.pack_identity(manifest)


def test_a_research_licensed_size_is_refused(tmp_path):
    manifest = json.loads((ROOT / "models/language/language-qwen2.5-7b-instruct-q4-k-m-dev-v1.json").read_text(encoding="utf-8"))
    manifest["modelId"] = "qwen2-5-3b-instruct"
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "m.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(language_packs.PackError, match="research_licensed"):
        language_packs.load_manifest("models/m.json", tmp_path)


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    """A one-variant runtime and a one-file pack, with the record pointing at them."""
    store = tmp_path / "store"
    (store / "runtime").mkdir(parents=True)
    (store / "models" / "pack-v1").mkdir(parents=True)
    server, library = b"server-bytes", b"library-bytes"
    archive = store / "runtime" / "runtime.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("llama-server.exe", server)
        bundle.writestr("ggml.dll", library)
    licence = b"MIT License\n\nPermission is hereby granted, free of charge"
    (store / "runtime" / "LICENSE").write_bytes(licence)
    weights = b"gguf-bytes"
    (store / "models" / "pack-v1" / "model.gguf").write_bytes(weights)
    document = {
        "schemaVersion": language_packs.SCHEMA,
        "runtime": {
            "runtimeId": "llamacpp-test",
            "licence": {"spdxId": "MIT", "file": "LICENSE", "sha256": _sha(licence), "url": "unused"},
            "variants": [{
                "variant": "windows-x86_64-cpu",
                "directory": "cpu",
                "archives": [{"file": "runtime.zip", "sha256": _sha(archive.read_bytes()), "url": "unused"}],
                "files": {"llama-server.exe": _sha(server), "ggml.dll": _sha(library)},
            }],
        },
        "models": [{"manifest": "m.json", "packDirectory": "pack-v1", "files": [{"file": "model.gguf", "sha256": _sha(weights), "url": "unused"}]}],
    }
    manifest = {
        "modelId": "test-model", "modelVersion": "1", "capabilityIds": ["query-translation"], "packDirectory": "pack-v1",
        "artifacts": [{"artifactRole": "gguf-weights", "relativePath": "pack-v1/model.gguf", "sha256": _sha(weights)}],
        "quantisation": {"type": "Q8_0"},
    }
    monkeypatch.setattr(language_packs, "load", lambda root=None: document)
    monkeypatch.setattr(language_packs, "load_manifest", lambda relative, root=None: manifest)
    return store, document


def test_stage_then_verify_returns_the_bound_identity(synthetic, tmp_path):
    store, _ = synthetic
    runtime_root, model_root = tmp_path / "runtime", tmp_path / "models"
    staged = language_packs.stage(store, runtime_root, model_root)
    assert "runtime/cpu" in staged
    identity = language_packs.verify(runtime_root, "cpu", model_root, "pack-v1")
    assert identity["modelId"] == "test-model" and identity["modelPath"].endswith("model.gguf")
    # A second stage verifies and keeps what is present.
    assert "runtime/cpu (present)" in language_packs.stage(store, runtime_root, model_root)


def test_verify_refuses_a_changed_or_added_runtime_file(synthetic, tmp_path):
    store, _ = synthetic
    runtime_root, model_root = tmp_path / "runtime", tmp_path / "models"
    language_packs.stage(store, runtime_root, model_root)
    (runtime_root / "cpu" / "ggml.dll").write_bytes(b"tampered")
    with pytest.raises(language_packs.PackError, match="hash:ggml.dll"):
        language_packs.verify(runtime_root, "cpu", model_root, "pack-v1")
    language_packs.stage(store, runtime_root, model_root)
    (runtime_root / "cpu" / "extra.dll").write_bytes(b"x")
    with pytest.raises(language_packs.PackError, match="unrecorded:extra.dll"):
        language_packs.verify(runtime_root, "cpu", model_root, "pack-v1")


def test_stage_refuses_an_archive_member_the_record_does_not_list(synthetic, tmp_path):
    store, document = synthetic
    archive = store / "runtime" / "runtime.zip"
    with zipfile.ZipFile(archive, "a") as bundle:
        bundle.writestr("smuggled.dll", b"x")
    document["runtime"]["variants"][0]["archives"][0]["sha256"] = _sha(archive.read_bytes())
    with pytest.raises(language_packs.PackError, match="unrecorded_member:smuggled.dll"):
        language_packs.stage(store, tmp_path / "runtime", tmp_path / "models")


def test_stage_refuses_a_payload_whose_hash_differs(synthetic, tmp_path):
    store, _ = synthetic
    (store / "models" / "pack-v1" / "model.gguf").write_bytes(b"other weights")
    with pytest.raises(language_packs.PackError, match="missing_or_mismatched"):
        language_packs.stage(store, tmp_path / "runtime", tmp_path / "models")
