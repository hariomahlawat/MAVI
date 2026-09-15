from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "verify_authoritative_state.py"
SPEC = importlib.util.spec_from_file_location("verify_authoritative_state_tests", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class HealthOnlyClient:
    def __init__(self, _base_url: str):
        pass

    def json(self, method: str, path: str):
        assert method == "GET"
        assert path == "/api/health"
        return {
            "status": "ok",
            "commit": "a" * 40,
            "build": "wrong-build",
        }


def test_authoritative_state_rejects_same_commit_wrong_build(tmp_path: Path, monkeypatch):
    evidence = tmp_path / "acceptance.json"
    evidence.write_text(
        json.dumps({
            "schemaVersion": "mavi-phase1-acceptance-evidence-v1",
            "sourceCommit": "a" * 40,
            "attestation": {"maviCommit": "a" * 40, "maviBuild": "prior-build"},
            "result": {"passed": True, "failureCodes": []},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod.e2e, "ApiClient", HealthOnlyClient)
    monkeypatch.setattr(mod.evidence_verifier, "_validate_schema", lambda *_: None)
    monkeypatch.setattr(mod.evidence_verifier, "verify_acceptance", lambda *_, **__: None)
    with pytest.raises(mod.StateCheckError, match="state_application_identity_mismatch"):
        mod.check_state(
            base_url="http://mavi.local",
            acceptance_evidence=evidence,
            expected_application_commit="a" * 40,
            expected_application_build="prior-build",
        )


def test_authoritative_state_rejects_malformed_evidence_before_api_access(
    tmp_path: Path,
    monkeypatch,
):
    evidence = tmp_path / "malformed.json"
    evidence.write_text(json.dumps({
        "schemaVersion": "mavi-phase1-acceptance-evidence-v1",
        "sourceCommit": "a" * 40,
        "result": {"passed": True, "failureCodes": []},
    }), encoding="utf-8")

    class UnexpectedClient:
        def __init__(self, _base_url: str):
            raise AssertionError("API must not be called for malformed evidence")

    monkeypatch.setattr(mod.e2e, "ApiClient", UnexpectedClient)
    with pytest.raises(mod.StateCheckError, match="state_acceptance_evidence_invalid"):
        mod.check_state(
            base_url="http://mavi.local",
            acceptance_evidence=evidence,
            expected_application_commit="a" * 40,
            expected_application_build="prior-build",
        )
