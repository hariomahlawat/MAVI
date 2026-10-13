"""Offline packaging of the instrument environment's model payloads (manifest, fetch and staging)."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest

from tools.benchmarks.plates import instrument_env


def test_manifest_matches_every_instrument_specification():
    instruments = instrument_env.load_manifest()
    ids = {i["instrumentId"] for i in instruments}
    assert ids == {"fast-plate-ocr-cct-s-v2-global", "rapidocr-ppocrv4", "open-image-models-yolo-v9-s-608-plates"}


def _fixture(tmp_path: Path, files: dict[str, bytes], kinds: dict[str, str]) -> tuple[Path, Path]:
    specs = tmp_path / "specs"
    specs.mkdir()
    spec = {"instrumentId": "inst", "modelFiles": [{"path": n, "sha256": hashlib.sha256(b).hexdigest()}
                                                  for n, b in files.items()]}
    (specs / "inst.json").write_text(json.dumps(spec))
    manifest = {"schemaVersion": "benchmark-plate-instrument-payloads-v1", "instruments": [{
        "instrumentId": "inst",
        "files": [{"path": n, "sha256": hashlib.sha256(b).hexdigest(),
                   "source": ({"kind": "url", "url": f"https://example.invalid/{n}"} if kinds[n] == "url"
                              else {"kind": "wheel", "member": f"pkg/models/{n}"})} for n, b in files.items()]}]}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path, specs


@pytest.fixture
def patched(tmp_path, monkeypatch):
    files = {"a.onnx": b"model-a", "b.onnx": b"model-b"}
    path, specs = _fixture(tmp_path, files, {"a.onnx": "url", "b.onnx": "wheel"})
    real = instrument_env.load_manifest
    monkeypatch.setattr(instrument_env, "load_manifest", lambda: real(path, specs))
    return files


def test_fetch_then_stage_offline(tmp_path, patched):
    cache, site, root = tmp_path / "cache", tmp_path / "site", tmp_path / "models"
    instrument_env.fetch_payloads(cache, opener=lambda url: io.BytesIO(patched[url.rsplit("/", 1)[1]]))
    (site / "pkg" / "models").mkdir(parents=True)
    (site / "pkg" / "models" / "b.onnx").write_bytes(patched["b.onnx"])
    staged = instrument_env.stage_models(cache, site, root)
    assert sorted(p.name for p in staged) == ["a.onnx", "b.onnx"]
    assert (root / "inst" / "a.onnx").read_bytes() == b"model-a"


def test_fetch_refuses_and_discards_a_hash_mismatch(tmp_path, patched):
    cache = tmp_path / "cache"
    with pytest.raises(instrument_env.PayloadError, match="payload_hash_mismatch"):
        instrument_env.fetch_payloads(cache, opener=lambda url: io.BytesIO(b"tampered"))
    assert not list((cache / "inst").glob("*"))


def test_stage_refuses_missing_or_altered_payloads(tmp_path, patched):
    cache, site = tmp_path / "cache", tmp_path / "site"
    with pytest.raises(instrument_env.PayloadError, match="payload_missing"):
        instrument_env.stage_models(cache, site, tmp_path / "models")
    (cache / "inst").mkdir(parents=True)
    (cache / "inst" / "a.onnx").write_bytes(b"altered")
    with pytest.raises(instrument_env.PayloadError, match="payload_hash_mismatch"):
        instrument_env.stage_models(cache, site, tmp_path / "models")


def test_manifest_refuses_a_specification_mismatch(tmp_path):
    path, specs = _fixture(tmp_path, {"a.onnx": b"x"}, {"a.onnx": "url"})
    (specs / "inst.json").write_text(json.dumps({"modelFiles": [{"path": "a.onnx", "sha256": "0" * 64}]}))
    with pytest.raises(instrument_env.PayloadError, match="spec_mismatch"):
        instrument_env.load_manifest(path, specs)
