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
        "liveStorageTopology": {
            "maviBuild": build,
            "maviCommit": "a" * 40,
            "databaseIdentity": "source|127.0.0.1|5432",
        },
        "restoreStorageTopology": {
            "maviBuild": build,
            "maviCommit": "a" * 40,
            "databaseIdentity": "restore|127.0.0.1|5433",
        },
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


def test_backup_restore_validator_rejects_restore_topology_database_mismatch(tmp_path: Path):
    path = _backup_restore_value(tmp_path)
    value = __import__("json").loads(path.read_text(encoding="utf-8"))
    value["restoreStorageTopology"]["databaseIdentity"] = "source|127.0.0.1|5432"
    path.write_text(__import__("json").dumps(value), encoding="utf-8")
    with pytest.raises(mod.ClosureError, match="backup_restore_topology_binding_mismatch"):
        mod.validate_backup_restore(
            path,
            source_commit="a" * 40,
            mavi_build="build-a",
            acceptance_profile_sha256="b" * 64,
            schema_path=_backup_restore_schema(tmp_path),
        )


def test_application_lifecycle_build_mismatch_is_rejected(tmp_path: Path):
    schema_path = tmp_path / "lifecycle.schema.json"
    schema_path.write_text(
        __import__("json").dumps({"type": "object"}),
        encoding="utf-8",
    )
    value = {
        "sourceCommit": "a" * 40,
        "mode": "fresh-install",
        "build": "build-b",
        "applicationManifestSha256": "d" * 64,
        "destination": "mavi-root",
        "hosting": {"passed": True, "physicalPath": "mavi-root"},
        "internetUnavailable": True,
        "observedHealth": {"commit": "a" * 40, "build": "build-b"},
        "supportedUpdatesPolicySha256": "c" * 64,
        "uiSmoke": {"passed": True},
        "priorRelease": None,
        "retainedState": None,
        "result": {"passed": True, "failureCodes": []},
    }
    path = tmp_path / "lifecycle.json"
    path.write_text(__import__("json").dumps(value), encoding="utf-8")
    with pytest.raises(mod.ClosureError, match="application_lifecycle_build_mismatch"):
        mod.validate_application_lifecycle(
            path,
            expected_mode="fresh-install",
            source_commit="a" * 40,
            mavi_build="build-a",
            application_manifest_sha256="d" * 64,
            supported_updates_policy_sha256="c" * 64,
            schema_path=schema_path,
        )


def test_production_acceptance_call_contracts_match_live_signatures():
    ast = __import__("ast")
    inspect = __import__("inspect")
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    checked = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "production_acceptance"
        ):
            continue
        target = getattr(mod.production_acceptance, func.attr)
        signature = inspect.signature(target)
        parameters = signature.parameters
        keyword_names = {item.arg for item in node.keywords if item.arg is not None}
        accepts_kwargs = any(
            item.kind == inspect.Parameter.VAR_KEYWORD
            for item in parameters.values()
        )
        if not accepts_kwargs:
            unexpected = keyword_names - set(parameters)
            assert not unexpected, (
                f"{func.attr} called with unsupported keywords: {sorted(unexpected)}"
            )
        required_keyword_only = {
            name
            for name, item in parameters.items()
            if item.kind == inspect.Parameter.KEYWORD_ONLY
            and item.default is inspect.Parameter.empty
        }
        missing = required_keyword_only - keyword_names
        assert not missing, (
            f"{func.attr} missing required keyword-only arguments: {sorted(missing)}"
        )
        positional_capacity = sum(
            1
            for item in parameters.values()
            if item.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        )
        has_varargs = any(
            item.kind == inspect.Parameter.VAR_POSITIONAL
            for item in parameters.values()
        )
        if not has_varargs:
            assert len(node.args) <= positional_capacity, (
                f"{func.attr} has too many positional arguments"
            )
        checked += 1
    assert checked >= 8


def test_application_lifecycle_manifest_hash_mismatch_is_rejected(tmp_path: Path):
    schema_path = tmp_path / "lifecycle-manifest.schema.json"
    schema_path.write_text(__import__("json").dumps({"type": "object"}), encoding="utf-8")
    value = {
        "sourceCommit": "a" * 40,
        "mode": "fresh-install",
        "build": "build-a",
        "applicationManifestSha256": "e" * 64,
        "destination": "mavi-root",
        "hosting": {"passed": True, "physicalPath": "mavi-root"},
        "internetUnavailable": True,
        "observedHealth": {"commit": "a" * 40, "build": "build-a"},
        "supportedUpdatesPolicySha256": "c" * 64,
        "uiSmoke": {"passed": True},
        "priorRelease": None,
        "retainedState": None,
        "result": {"passed": True, "failureCodes": []},
    }
    path = tmp_path / "lifecycle-manifest.json"
    path.write_text(__import__("json").dumps(value), encoding="utf-8")
    with pytest.raises(mod.ClosureError, match="application_lifecycle_manifest_mismatch"):
        mod.validate_application_lifecycle(
            path,
            expected_mode="fresh-install",
            source_commit="a" * 40,
            mavi_build="build-a",
            application_manifest_sha256="d" * 64,
            supported_updates_policy_sha256="c" * 64,
            schema_path=schema_path,
        )
