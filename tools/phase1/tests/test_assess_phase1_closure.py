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


def test_production_acceptance_guard_requires_prior_acceptance_evidence():
    source = __import__("inspect").getsource(mod.assess)
    assert "args.prior_acceptance_evidence" in source
    assert "production_acceptance_ready" in source



# --------------------------------------------------------------------------- v2 composition (S2a.3)

from phase1_v2_support import (  # noqa: E402
    ACCEPTANCE_PROFILE,
    COMMITTED_BINDING,
    COMMITTED_MANIFEST,
    COMMITTED_RECORD,
    committed_release_hashes,
    overlay_type,
    sha256_file,
)

FENCE_PENDING = "qualification-evidence-binding:v2_promotion_not_supported_by_this_slice"
PROFILE_VARIANTS = {"P1": "windows-x86_64-cuda", "P2": "linux-x86_64-cuda", "P3": "windows-x86_64-cpu"}


def _closure_args(tmp_path: Path, profile: str, *extra: str):
    return mod.build_parser().parse_args([
        "--source-commit", "a" * 40,
        "--deployment-profile", profile,
        "--model-root", str(tmp_path / "empty-model-store"),
        "--acceptance-profile", str(ACCEPTANCE_PROFILE),
        "--output", str(tmp_path / "closure.json"),
        *extra,
    ])


def _overlay_args(tmp_path: Path, overlay, profile: str, *extra: str):
    return _closure_args(
        tmp_path,
        profile,
        "--component-binding", str(overlay.binding_path),
        "--overlay-root", str(overlay.root),
        "--model-root", str(overlay.model_root),
        "--pipeline-profile", str(overlay.pipeline_path),
        *extra,
    )


@pytest.mark.parametrize("profile", sorted(PROFILE_VARIANTS))
def test_the_committed_release_is_not_closed_for_any_profile(tmp_path: Path, profile: str):
    before = committed_release_hashes()

    value = mod.assess(_closure_args(tmp_path, profile))

    variant = PROFILE_VARIANTS[profile]
    assert value["state"] == "implementation-complete-evidence-pending"
    assert value["runtimeVariant"] == variant
    pending = set(value["pending"])
    assert {
        "release:promotion",
        FENCE_PENDING,
        "qualification-profile:" + profile,
        "qualification-variant:" + variant,
    } <= pending
    # P-12: the v1 requiredGates names are gone; every v2 gate of the variant is pending.
    assert "qualification:" + variant + ":offline-install" in pending
    assert "qualification:" + variant + ":cctv-quality-baseline" in pending
    assert not any(item.startswith("qualification:windows-offline-install") for item in pending)
    metadata = value["releaseMetadata"]
    assert metadata["manifestSha256"] == sha256_file(COMMITTED_MANIFEST)
    assert metadata["qualificationSha256"] == sha256_file(COMMITTED_RECORD)
    assert metadata["componentBindingSha256"] == sha256_file(COMMITTED_BINDING)
    assert committed_release_hashes() == before


def test_the_cli_reports_not_closed_and_require_complete_fails(tmp_path: Path, monkeypatch):
    output = tmp_path / "closure.json"
    monkeypatch.setattr(sys, "argv", [
        "assess_phase1_closure.py",
        "--source-commit", "a" * 40,
        "--deployment-profile", "P3",
        "--model-root", str(tmp_path / "empty-model-store"),
        "--acceptance-profile", str(ACCEPTANCE_PROFILE),
        "--output", str(output),
        "--require-complete",
    ])
    assert mod.main() == 3
    assert __import__("json").loads(output.read_text(encoding="utf-8"))["state"] != "release-verified"


@pytest.mark.parametrize("retired", ["--manifest", "--qualification", "--runtime-profile"])
def test_the_retired_path_arguments_are_refused(tmp_path: Path, retired: str):
    with pytest.raises(SystemExit):
        _closure_args(tmp_path, "P3", retired, str(COMMITTED_MANIFEST))


def test_a_fully_qualified_overlay_is_promoted_but_still_not_closed(tmp_path: Path):
    """The mapped Production check discriminates, and the fence still blocks closure."""
    overlay = overlay_type().create(tmp_path)
    overlay.qualify_for_production(profile_id="P3")

    unpacked = mod.assess(_overlay_args(tmp_path, overlay, "P3"))
    assert "release:promotion" in unpacked["pending"]  # no installed Runtime Pack

    installed = mod.assess(
        _overlay_args(tmp_path, overlay, "P3", "--runtime-pack-manifest", str(overlay.pack_manifest_path))
    )
    pending = set(installed["pending"])
    assert "release:promotion" not in pending
    assert not any(
        item.startswith(("qualification:", "qualification-variant:", "qualification-profile"))
        for item in pending
    )
    assert FENCE_PENDING in pending
    assert installed["state"] != "release-verified"


def test_the_production_check_refuses_an_unverified_overlay_even_with_a_pack(tmp_path: Path):
    overlay = overlay_type().create(tmp_path)
    overlay.qualify_for_production(profile_id="P3")
    overlay.manifest["verificationStatus"] = "unverified"
    overlay.manifest["qualificationId"] = None
    overlay.write()
    value = mod.assess(
        _overlay_args(tmp_path, overlay, "P3", "--runtime-pack-manifest", str(overlay.pack_manifest_path))
    )
    assert "release:promotion" in value["pending"]


def _record(overlay):
    from mavi_vision.runtime.qualification_v2 import load_capability_gate_sets, load_qualification_record_v2

    return load_qualification_record_v2(
        overlay.record_path,
        gate_sets=load_capability_gate_sets(overlay.root / "config/acceptance/capability-gate-sets-v1.json"),
    )


def test_qualification_pending_requires_the_profile_policy_and_variant(tmp_path: Path):
    overlay = overlay_type().create(tmp_path)
    _profile, policy_sha = overlay.qualify_for_production(profile_id="P3")
    record = _record(overlay)

    assert mod.qualification_pending(
        record,
        profile_id="P3",
        runtime_variant="windows-x86_64-cpu",
        deployment_profile_policy_sha256=policy_sha,
    ) == []
    with pytest.raises(mod.ClosureError, match="qualification_profile_policy_mismatch:P3"):
        mod.qualification_pending(
            record,
            profile_id="P3",
            runtime_variant="windows-x86_64-cpu",
            deployment_profile_policy_sha256="0" * 64,
        )
    with pytest.raises(mod.ClosureError, match="qualification_profile_runtime_variant_mismatch:P3"):
        mod.qualification_pending(
            record,
            profile_id="P3",
            runtime_variant="linux-x86_64-cpu",
            deployment_profile_policy_sha256=policy_sha,
        )
    # Another profile on a pending variant is reported per gate, never as passed.
    other = mod.qualification_pending(
        record,
        profile_id="P1",
        runtime_variant="windows-x86_64-cuda",
        deployment_profile_policy_sha256=policy_sha,
    )
    assert "qualification-profile:P1" in other
    assert "qualification-variant:windows-x86_64-cuda" in other


def test_profile_evidence_must_cover_every_variant_gate(tmp_path: Path):
    overlay = overlay_type().create(tmp_path)
    _profile, policy_sha = overlay.qualify_for_production(profile_id="P3")
    del overlay.record["profileQualifications"]["P3"]["evidence"]["licence"]
    overlay.write()
    assert mod.qualification_pending(
        _record(overlay),
        profile_id="P3",
        runtime_variant="windows-x86_64-cpu",
        deployment_profile_policy_sha256=policy_sha,
    ) == ["qualification-profile-evidence:P3:licence"]


def test_the_closure_tool_has_no_v1_reader():
    source = MODULE_PATH.read_text(encoding="utf-8")
    for retired in ("load_qualification_record(", "load_runtime_profile(", "verify_release_selection(", "required_gates"):
        assert retired not in source
