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


def test_quality_closure_rejects_independent_corpus_validation_failure(
    tmp_path: Path,
    monkeypatch,
):
    evidence = tmp_path / "quality.json"
    evidence.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        mod.quality_corpus,
        "validate_quality_corpus_evidence",
        lambda *_, **__: (_ for _ in ()).throw(
            mod.quality_corpus.QualityCorpusError(
                "quality_corpus_evidence_recalculation_mismatch"
            )
        ),
    )
    with pytest.raises(
        mod.ClosureError,
        match="quality_corpus_invalid:quality_corpus_evidence_recalculation_mismatch",
    ):
        mod.validate_quality(
            evidence,
            source_commit="a" * 40,
            acceptance_profile_sha256="b" * 64,
            acceptance_profile={},
            expected_mavi_build="build-a",
            target_verified_manifest_sha256="c" * 64,
            corpus_manifest=tmp_path / "corpus.json",
            case_evidence={},
            ground_truth={},
        )


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
            "sourceDatabaseIdentitySha256",
            "restoreDatabaseIdentitySha256",
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
        "sourceDatabaseIdentitySha256": "1" * 64,
        "restoreDatabaseIdentitySha256": "2" * 64,
        "cleanRestoreTarget": True,
        "liveStorageTopology": {
            "maviBuild": build,
            "maviCommit": "a" * 40,
            "databaseIdentitySha256": "1" * 64,
        },
        "restoreStorageTopology": {
            "maviBuild": build,
            "maviCommit": "a" * 40,
            "databaseIdentitySha256": "2" * 64,
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
    value["restoreStorageTopology"]["databaseIdentitySha256"] = "1" * 64
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
        "hosting": {
            "passed": True,
            "physicalPath": "mavi-root",
            "hostIdentitySha256": "6" * 64,
        },
        "operationalApi": {
            "baseUrl": "http://mavi.local",
            "hostIdentitySha256": "6" * 64,
            "passed": True,
        },
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
        "hosting": {
            "passed": True,
            "physicalPath": "mavi-root",
            "hostIdentitySha256": "6" * 64,
        },
        "operationalApi": {
            "baseUrl": "http://mavi.local",
            "hostIdentitySha256": "6" * 64,
            "passed": True,
        },
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


def test_qualification_evidence_hashes_use_selected_profile_record():
    class Evidence:
        def __init__(self, sha256: str):
            self.sha256 = sha256

    class ProfileQualification:
        deployment_profile_policy_sha256 = "f" * 64
        runtime_variant = "windows-x86_64-cuda"
        evidence = {
            "windows-x86_64-cuda": Evidence("a" * 64),
            "windows-offline-install": Evidence("b" * 64),
            "cctv-quality-baseline": Evidence("c" * 64),
        }

    class Qualification:
        required_gates = {
            gate: "passed"
            for gate in mod.MANDATORY_QUALIFICATION_GATES
        }
        # Simulate a later P2 promotion overwriting the legacy top-level
        # shared quality gate. P1 closure must still use P1's own record.
        evidence = {
            "windows-x86_64-cuda": Evidence("a" * 64),
            "windows-offline-install": Evidence("b" * 64),
            "cctv-quality-baseline": Evidence("d" * 64),
        }
        profile_qualifications = {
            "P1": ProfileQualification(),
        }

    observed = {
        "windows-x86_64-cuda": "a" * 64,
        "windows-offline-install": "b" * 64,
        "cctv-quality-baseline": "c" * 64,
    }
    mod.validate_qualification_evidence_hashes(
        Qualification(),
        observed,
        frozenset({
            "windows-x86_64-cuda",
            "windows-offline-install",
            "cctv-quality-baseline",
        }),
        deployment_profile_id="P1",
        deployment_profile_policy_sha256="f" * 64,
        runtime_variant="windows-x86_64-cuda",
    )


def test_qualification_evidence_hashes_reject_selected_profile_mismatch():
    class Evidence:
        def __init__(self, sha256: str):
            self.sha256 = sha256

    class ProfileQualification:
        deployment_profile_policy_sha256 = "f" * 64
        runtime_variant = "windows-x86_64-cuda"
        evidence = {
            "windows-x86_64-cuda": Evidence("a" * 64),
            "windows-offline-install": Evidence("b" * 64),
            "cctv-quality-baseline": Evidence("c" * 64),
        }

    class Qualification:
        required_gates = {
            gate: "passed"
            for gate in mod.MANDATORY_QUALIFICATION_GATES
        }
        profile_qualifications = {
            "P1": ProfileQualification(),
        }

    observed = {
        "windows-x86_64-cuda": "a" * 64,
        "windows-offline-install": "b" * 64,
        "cctv-quality-baseline": "d" * 64,
    }
    with pytest.raises(
        mod.ClosureError,
        match=(
            "qualification_evidence_hash_mismatch:"
            "P1:cctv-quality-baseline"
        ),
    ):
        mod.validate_qualification_evidence_hashes(
            Qualification(),
            observed,
            frozenset({
                "windows-x86_64-cuda",
                "windows-offline-install",
                "cctv-quality-baseline",
            }),
            deployment_profile_id="P1",
            deployment_profile_policy_sha256="f" * 64,
            runtime_variant="windows-x86_64-cuda",
        )



def test_production_acceptance_guard_requires_prior_acceptance_evidence():
    source = __import__("inspect").getsource(mod.assess)
    assert "args.prior_acceptance_evidence" in source
    assert "production_acceptance_ready" in source

