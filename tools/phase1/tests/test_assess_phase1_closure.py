from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "assess_phase1_closure.py"
SPEC = importlib.util.spec_from_file_location("phase1_closure", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def test_quality_requires_formal_qualification_metrics():
    value = {
        "sourceCommit": "a" * 40,
        "mode": "formal",
        "metrics": {
            "mode": "baseline",
            "qualification": {"passed": None},
        },
    }
    with pytest.raises(mod.ClosureError, match="quality_qualification_not_passed"):
        metrics = value["metrics"]
        if metrics.get("mode") != "qualification" or metrics.get("qualification", {}).get("passed") is not True:
            raise mod.ClosureError("quality_qualification_not_passed")


def test_application_update_requires_supported_prior():
    value = {
        "sourceCommit": "a" * 40,
        "mode": "offline-update",
        "internetUnavailable": True,
        "priorRelease": None,
        "observedHealth": {"commit": "a" * 40},
        "result": {"passed": True, "failureCodes": []},
    }
    assert mod._passed_result(value) is True
    prior = value.get("priorRelease")
    with pytest.raises(mod.ClosureError, match="offline_update_supported_prior_missing"):
        if not isinstance(prior, dict) or prior.get("supported") is not True:
            raise mod.ClosureError("offline_update_supported_prior_missing")


def test_result_helper_rejects_failure_codes():
    assert mod._passed_result({"result": {"passed": True, "failureCodes": ["x"]}}) is False
    assert mod._passed_result({"result": {"passed": True, "failureCodes": []}}) is True


def _backup_restore_schema(tmp_path: Path) -> Path:
    schema = {
        "type": "object",
        "required": [
            "sourceCommit",
            "acceptanceProfileSha256",
            "sourceDatabaseIdentity",
            "restoreDatabaseIdentity",
            "cleanRestoreTarget",
            "liveStorageTopology",
            "result",
        ],
        "properties": {},
    }
    path = tmp_path / "backup.schema.json"
    path.write_text(__import__("json").dumps(schema), encoding="utf-8")
    return path


def _backup_restore_value(tmp_path: Path, build: str = "build-a") -> Path:
    value = {
        "sourceCommit": "a" * 40,
        "acceptanceProfileSha256": "b" * 64,
        "sourceDatabaseIdentity": "source|127.0.0.1|5432",
        "restoreDatabaseIdentity": "restore|127.0.0.1|5433",
        "cleanRestoreTarget": True,
        "liveStorageTopology": {"maviBuild": build},
        "result": {"passed": True, "failureCodes": []},
    }
    path = tmp_path / "backup.json"
    path.write_text(__import__("json").dumps(value), encoding="utf-8")
    return path


def test_backup_restore_validator_accepts_expected_build_argument(tmp_path: Path):
    result = mod.validate_backup_restore(
        _backup_restore_value(tmp_path),
        source_commit="a" * 40,
        mavi_build="build-a",
        acceptance_profile_sha256="b" * 64,
        schema_path=_backup_restore_schema(tmp_path),
    )
    assert result["liveStorageTopology"]["maviBuild"] == "build-a"


def test_backup_restore_validator_rejects_wrong_build(tmp_path: Path):
    with pytest.raises(mod.ClosureError, match="backup_restore_mavi_build_mismatch"):
        mod.validate_backup_restore(
            _backup_restore_value(tmp_path, build="build-b"),
            source_commit="a" * 40,
            mavi_build="build-a",
            acceptance_profile_sha256="b" * 64,
            schema_path=_backup_restore_schema(tmp_path),
        )
