from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "validate_supported_update.py"
SPEC = importlib.util.spec_from_file_location("supported_update", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def build_prior(tmp_path: Path):
    root = tmp_path / "prior"
    root.mkdir()
    (root / "Mavi.Api.dll").write_bytes(b"prior")
    manifest = mod.app_manifest.build_manifest(
        root, source_commit="a" * 40, build="prior-build"
    )
    manifest_path = root / "mavi-application-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return root, manifest_path


def _use_test_policy(monkeypatch, policy: Path):
    monkeypatch.setattr(
        mod,
        "canonical_supported_updates",
        lambda observed: (policy, mod.sha256_file(policy)),
    )


def test_rejects_unfrozen_prior_manifest_identity(tmp_path: Path, monkeypatch):
    root, manifest_path = build_prior(tmp_path)
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({
        "schemaVersion": "mavi-phase1-supported-updates-v1",
        "priorReleases": [{
            "sourceCommit": "a" * 40,
            "applicationManifestSha256": None,
            "migrationPolicy": "none",
        }],
    }), encoding="utf-8")
    _use_test_policy(monkeypatch, policy)
    with pytest.raises(mod.SupportedUpdateError, match="update_prior_release_identity_not_frozen"):
        mod.validate(policy, manifest_path, root)


def test_rejects_mislabeled_or_modified_prior_artifact(tmp_path: Path, monkeypatch):
    root, manifest_path = build_prior(tmp_path)
    manifest_sha = mod.sha256_file(manifest_path)
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({
        "schemaVersion": "mavi-phase1-supported-updates-v1",
        "priorReleases": [{
            "sourceCommit": "a" * 40,
            "applicationManifestSha256": manifest_sha,
            "migrationPolicy": "none",
        }],
    }), encoding="utf-8")
    _use_test_policy(monkeypatch, policy)
    (root / "Mavi.Api.dll").write_bytes(b"modified")
    with pytest.raises(mod.SupportedUpdateError, match="update_prior_release_integrity_failed"):
        mod.validate(policy, manifest_path, root)


def test_rejects_noncanonical_supported_update_policy(tmp_path: Path):
    root, manifest_path = build_prior(tmp_path)
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({
        "schemaVersion": "mavi-phase1-supported-updates-v1",
        "priorReleases": [],
    }), encoding="utf-8")
    with pytest.raises(mod.PolicyIdentityError, match="supported_updates_policy_not_canonical"):
        mod.validate(policy, manifest_path, root)
