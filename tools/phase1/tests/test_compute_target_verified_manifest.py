from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "compute_target_verified_manifest.py"
SPEC = importlib.util.spec_from_file_location("target_manifest", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def test_target_changes_only_verification_linkage():
    candidate = {
        "schemaVersion": "1.0",
        "modelId": "model",
        "verificationStatus": "unverified",
        "qualificationId": None,
        "other": {"stable": True},
    }
    payload = mod.build_target_manifest(candidate, "qual-1")
    import json
    target = json.loads(payload)
    assert target["verificationStatus"] == "verified"
    assert target["qualificationId"] == "qual-1"
    assert target["other"] == candidate["other"]


def test_target_rejects_already_linked_candidate():
    with pytest.raises(mod.TargetManifestError):
        mod.build_target_manifest(
            {"verificationStatus": "unverified", "qualificationId": "existing"},
            "qual-1",
        )
