from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "build_application_artifact_manifest.py"
SPEC = importlib.util.spec_from_file_location("app_manifest", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def test_manifest_round_trip_detects_byte_drift(tmp_path: Path):
    root = tmp_path / "app"
    root.mkdir()
    (root / "Mavi.Api.dll").write_bytes(b"abc")
    manifest = mod.build_manifest(root, source_commit="a" * 40, build="build-1")
    mod.verify_manifest(root, manifest)
    (root / "Mavi.Api.dll").write_bytes(b"changed")
    with pytest.raises(mod.ApplicationArtifactError, match="application_manifest_integrity_failed"):
        mod.verify_manifest(root, manifest)


def test_manifest_rejects_untracked_extra_file(tmp_path: Path):
    root = tmp_path / "app"
    root.mkdir()
    (root / "a.txt").write_text("a", encoding="utf-8")
    manifest = mod.build_manifest(root, source_commit="a" * 40, build="build-1")
    (root / "b.txt").write_text("b", encoding="utf-8")
    with pytest.raises(mod.ApplicationArtifactError, match="application_manifest_file_set_mismatch"):
        mod.verify_manifest(root, manifest)
