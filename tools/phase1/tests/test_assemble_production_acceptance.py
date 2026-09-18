from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "assemble_production_acceptance.py"
SPEC = importlib.util.spec_from_file_location("production_acceptance", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)

EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
CONTEXT_SHA = "c" * 64
WINDOWS_HOST = "6" * 64


def variant_payload(mode: str = "production") -> dict:
    return {
        "schemaVersion": "mavi-offline-variant-evidence-v1",
        "sourceCommit": "a" * 40,
        "targetVerifiedManifestSha256": "b" * 64,
        "acceptanceProfileSha256": "c" * 64,
        "maviBuild": "build-a",
        "variant": "linux-x86_64-cpu",
        "bundleMode": mode,
        "bundleManifestSha256": "d" * 64,
        "releaseLockSha256": "e" * 64,
        "expectedHostCompatibility": {"os": "linux"},
        "observedHostCompatibility": {"os": "linux"},
        "installCommand": "pip install --no-index --only-binary=:all: --require-hashes --find-links wheels -r lock",
        "installExitCode": 0,
        "pipCheckPassed": True,
        "runtimeStarted": True,
        "realInferencePassed": True,
        "workerFlowPassed": True,
        "workerFlowEvidenceSha256": "1" * 64,
        "workerPythonSha256": "2" * 64,
        "workerEnvironmentSha256": "5" * 64,
        "workerVenvRootSha256": "6" * 64,
        "workerResolvedPythonSha256": "7" * 64,
        "hostIdentitySha256": "8" * 64,
        "workerCommandSha256": "3" * 64,
        "workerLogSha256": "4" * 64,
        "actualDevice": "cpu",
        "outboundNetworkUnavailable": True,
        "networkIsolation": {
            "proxyEnvironmentAbsent": True,
            "probes": [
                {"host": f"h{i}", "port": 443, "reachable": False}
                for i in range(5)
            ],
            "passed": True,
        },
        "firstRunDownloadObserved": False,
        "result": "passed",
    }


def scenario_payload(e2e_sha: str) -> dict:
    return {
        "schemaVersion": "mavi-production-scenario-evidence-v2",
        "acceptanceExecutionId": EXECUTION_ID,
        "acceptanceContextSha256": CONTEXT_SHA,
        "scenarioStartedAtUtc": "2026-09-14T18:10:00Z",
        "scenarioCompletedAtUtc": "2026-09-14T18:11:00Z",
        "mode": "formal",
        "sourceCommit": "a" * 40,
        "maviBuild": "build-a",
        "operationalHostIdentitySha256": WINDOWS_HOST,
        "targetVerifiedManifestSha256": "b" * 64,
        "deploymentProfile": "P2",
        "deploymentProfilePolicySha256": "f" * 64,
        "runtimeVariant": "linux-x86_64-cuda",
        "variantEvidenceSha256": "f" * 64,
        "productionBundleManifestSha256": "d" * 64,
        "productionReleaseLockSha256": "e" * 64,
        "workerPythonSha256": "2" * 64,
        "workerEnvironmentSha256": "5" * 64,
        "workerVenvRootSha256": "6" * 64,
        "workerResolvedPythonSha256": "7" * 64,
        "e2eEvidenceSha256": e2e_sha,
        "workerLogSha256": "3" * 64,
        "networkIsolation": {
            "proxyEnvironmentAbsent": True,
            "probes": [
                {"host": f"h{i}", "port": 443, "reachable": False}
                for i in range(5)
            ],
            "passed": True,
        },
        "result": {"passed": True, "failureCodes": []},
    }


def e2e_payload() -> dict:
    return {
        "mode": "formal",
        "sourceCommit": "a" * 40,
        "targetVerifiedManifestSha256": "b" * 64,
        "operationalApi": {"hostIdentitySha256": WINDOWS_HOST},
        "releaseExpected": {"modelManifestSha256": "b" * 64},
        "attestation": {
            "verificationStatus": "verified",
            "runtimeVariant": "linux-x86_64-cuda",
            "maviBuild": "build-a",
            "maviCommit": "a" * 40,
            "productionBundleManifestSha256": "d" * 64,
            "platformLockSha256": "e" * 64,
            "candidateBundleManifestSha256": None,
            "candidateSelectedLockSha256": None,
            "actualDevice": "cuda:0",
        },
        "result": {"passed": True, "failureCodes": []},
    }


def test_candidate_variant_cannot_satisfy_production_acceptance(tmp_path: Path):
    path = tmp_path / "variant.json"
    path.write_text(json.dumps(variant_payload("qualification-candidate")), encoding="utf-8")
    with pytest.raises(mod.ProductionAcceptanceError, match="production_variant_binding_failed"):
        mod.validate_variant(
            path,
            variant="linux-x86_64-cpu",
            source_commit="a" * 40,
            target_manifest_sha256="b" * 64,
            acceptance_profile_sha256="c" * 64,
            mavi_build="build-a",
        )


def test_production_variant_set_is_profile_scoped():
    assert mod.parse_variant_arguments(
        ["linux-x86_64-cuda=b.json"],
        frozenset({"linux-x86_64-cuda"}),
    ) == {"linux-x86_64-cuda": Path("b.json")}
    with pytest.raises(
        mod.ProductionAcceptanceError,
        match="production_variant_set_incomplete",
    ):
        mod.parse_variant_arguments(
            ["linux-x86_64-cpu=a.json"],
            frozenset({"linux-x86_64-cuda"}),
        )


def _write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _backup_proof_fixture(tmp_path: Path, *, formal_e2e_sha: str = "1" * 64):
    db_manifest = _write_json(tmp_path / "db-manifest.json", {
        "schemaVersion": "mavi-backup-database-manifest-v1",
        "files": [{"relativePath": "postgres.dump", "sizeBytes": 1, "sha256": "d" * 64}],
    })
    media_manifest = _write_json(tmp_path / "media-manifest.json", {
        "schemaVersion": "mavi-backup-store-manifest-v1",
        "files": [{"relativePath": "video.mp4", "sizeBytes": 1, "sha256": "e" * 64}],
    })
    evidence_manifest = _write_json(tmp_path / "evidence-manifest.json", {
        "schemaVersion": "mavi-backup-store-manifest-v1",
        "files": [{"relativePath": "thumb.jpg", "sizeBytes": 1, "sha256": "f" * 64}],
    })
    tooling = {
        "databaseBackup": {
            "tool": "pg_dump", "version": "17.6", "arguments": ["--format=custom"],
            "exitCode": 0, "passed": True,
        },
        "databaseRestore": {
            "tool": "pg_restore", "version": "17.6", "arguments": ["--clean"],
            "exitCode": 0, "passed": True,
        },
        "managedSourceCopy": {
            "tool": "python-shutil.copytree", "version": "3.12", "arguments": ["src", "dst"],
            "exitCode": 0, "passed": True,
        },
        "acceptedEvidenceCopy": {
            "tool": "python-shutil.copytree", "version": "3.12", "arguments": ["src", "dst"],
            "exitCode": 0, "passed": True,
        },
    }
    live = {
        "schemaVersion": "mavi-storage-topology-attestation-v1",
        "maviBuild": "build-a",
        "maviCommit": "a" * 40,
        "operationalHostIdentitySha256": WINDOWS_HOST,
        "databaseIdentitySha256": "1" * 64,
        "managedMediaRootIdentitySha256": "8" * 64,
        "acceptedEvidenceRootIdentitySha256": "9" * 64,
    }
    restore = {
        **live,
        "databaseIdentitySha256": "2" * 64,
        "managedMediaRootIdentitySha256": "a" * 64,
        "acceptedEvidenceRootIdentitySha256": "b" * 64,
    }
    backup_set = _write_json(tmp_path / "backup-set.json", {
        "schemaVersion": "mavi-backup-set-v1",
        "sourceCommit": "a" * 40,
        "acceptanceEvidenceSha256": formal_e2e_sha,
        "acceptanceProfileSha256": "c" * 64,
        "sourceDatabaseIdentitySha256": live["databaseIdentitySha256"],
        "restoreDatabaseIdentitySha256": restore["databaseIdentitySha256"],
        "liveStorageTopology": live,
        "databaseManifestSha256": mod.sha256_file(db_manifest),
        "managedSourceManifestSha256": mod.sha256_file(media_manifest),
        "acceptedEvidenceManifestSha256": mod.sha256_file(evidence_manifest),
        "pgDumpVersion": "17.6",
        "pgRestoreVersion": "17.6",
        "tooling": tooling,
    })
    execution = _write_json(tmp_path / "execution.json", {
        "schemaVersion": "mavi-backup-restore-execution-v1",
        "sourceCommit": "a" * 40,
        "acceptanceEvidenceSha256": formal_e2e_sha,
        "acceptanceProfileSha256": "c" * 64,
        "sourceDatabaseIdentitySha256": live["databaseIdentitySha256"],
        "restoreDatabaseIdentitySha256": restore["databaseIdentitySha256"],
        "liveStorageTopology": live,
        "restoreStorageTopology": restore,
        "tooling": tooling,
        "database": {"included": True, "manifestSha256": mod.sha256_file(db_manifest)},
        "managedSource": {"included": True, "manifestSha256": mod.sha256_file(media_manifest)},
        "acceptedEvidence": {"included": True, "manifestSha256": mod.sha256_file(evidence_manifest)},
        "backupManifestSha256": mod.sha256_file(backup_set),
        "cleanRestoreTarget": True,
        "result": "restore-complete",
    })
    post = _write_json(tmp_path / "post.json", {
        "schemaVersion": "mavi-post-restore-check-v1",
        "sourceCommit": "a" * 40,
        "acceptanceEvidenceSha256": formal_e2e_sha,
        "executionEvidenceSha256": mod.sha256_file(execution),
        "backupManifestSha256": mod.sha256_file(backup_set),
        "databaseManifestSha256": mod.sha256_file(db_manifest),
        "managedSourceManifestSha256": mod.sha256_file(media_manifest),
        "acceptedEvidenceManifestSha256": mod.sha256_file(evidence_manifest),
        "restoreStorageTopology": restore,
        "stateCheck": {
            "operationalHostIdentitySha256": WINDOWS_HOST,
            "authoritativeStateSha256": "7" * 64,
        },
        "result": {"passed": True, "failureCodes": []},
    })
    summary = _write_json(tmp_path / "backup.json", {
        "schemaVersion": "mavi-backup-restore-evidence-v1",
        "sourceCommit": "a" * 40,
        "acceptanceEvidenceSha256": formal_e2e_sha,
        "acceptanceProfileSha256": "c" * 64,
        "executionEvidenceSha256": mod.sha256_file(execution),
        "sourceDatabaseIdentitySha256": live["databaseIdentitySha256"],
        "restoreDatabaseIdentitySha256": restore["databaseIdentitySha256"],
        "liveStorageTopology": live,
        "restoreStorageTopology": restore,
        "database": {"included": True, "manifestSha256": mod.sha256_file(db_manifest)},
        "managedSource": {"included": True, "manifestSha256": mod.sha256_file(media_manifest)},
        "acceptedEvidence": {"included": True, "manifestSha256": mod.sha256_file(evidence_manifest)},
        "backupManifestSha256": mod.sha256_file(backup_set),
        "cleanRestoreTarget": True,
        "postRestoreCheckSha256": mod.sha256_file(post),
        "result": {"passed": True, "failureCodes": []},
    })
    kwargs = {
        "execution_evidence": execution,
        "post_restore_check": post,
        "backup_set_manifest": backup_set,
        "database_manifest": db_manifest,
        "managed_source_manifest": media_manifest,
        "accepted_evidence_manifest": evidence_manifest,
    }
    return summary, kwargs


def test_backup_must_reference_exact_final_e2e(tmp_path: Path):
    path, proofs = _backup_proof_fixture(tmp_path, formal_e2e_sha="1" * 64)
    with pytest.raises(mod.ProductionAcceptanceError, match="production_backup_restore_binding_failed"):
        mod.validate_backup(
            path,
            source_commit="a" * 40,
            mavi_build="build-a",
            acceptance_profile_sha256="c" * 64,
            formal_e2e_sha256="9" * 64,
            **proofs,
        )


def test_backup_rejects_tampered_underlying_execution(tmp_path: Path):
    path, proofs = _backup_proof_fixture(tmp_path)
    execution = json.loads(proofs["execution_evidence"].read_text(encoding="utf-8"))
    execution["restoreDatabaseIdentitySha256"] = "6" * 64
    proofs["execution_evidence"].write_text(json.dumps(execution), encoding="utf-8")
    with pytest.raises(mod.ProductionAcceptanceError, match="production_backup_restore_binding_failed"):
        mod.validate_backup(
            path,
            source_commit="a" * 40,
            mavi_build="build-a",
            acceptance_profile_sha256="c" * 64,
            formal_e2e_sha256="1" * 64,
            **proofs,
        )


def test_topology_binding_rejects_other_linux_host():
    prereq = {
        "topologyIdentities": {
            "windows-operational-plane": "1" * 64,
            "database": "5" * 64,
            "linux-vision-worker": "2" * 64,
        }
    }
    fresh = {
        "hosting": {"hostIdentitySha256": "1" * 64},
        "operationalApi": {"hostIdentitySha256": "1" * 64},
    }
    update = {
        "hosting": {"hostIdentitySha256": "1" * 64},
        "operationalApi": {"hostIdentitySha256": "1" * 64},
    }
    backup = {
        "sourceDatabaseIdentitySha256": "5" * 64,
        "liveStorageTopology": {
            "databaseIdentitySha256": "5" * 64,
            "operationalHostIdentitySha256": "1" * 64,
        },
        "restoreStorageTopology": {
            "operationalHostIdentitySha256": "1" * 64,
        },
    }
    linux = {"hostIdentitySha256": "9" * 64}
    with pytest.raises(
        mod.ProductionAcceptanceError,
        match="production_vision_topology_mismatch",
    ):
        mod.validate_topology_binding(
            prereq,
            fresh,
            update,
            backup,
            linux,
            mod.deployment_profiles.select_profile("P2")[0],
        )


def test_final_scenario_rejects_other_venv(tmp_path: Path, monkeypatch):
    e2e_path = tmp_path / "e2e.json"
    e2e_path.write_text(json.dumps(e2e_payload()), encoding="utf-8")
    scenario = scenario_payload(mod.sha256_file(e2e_path))
    variant_path = tmp_path / "variant.json"
    variant_path.write_text("{}", encoding="utf-8")
    scenario["variantEvidenceSha256"] = mod.sha256_file(variant_path)
    scenario["workerEnvironmentSha256"] = "9" * 64
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")

    monkeypatch.setattr(mod, "validate_schema", lambda *_: None)
    monkeypatch.setattr(mod.evidence_verifier, "verify_acceptance", lambda *_, **__: None)
    monkeypatch.setattr(mod.evidence_verifier, "verify_acceptance", lambda *_, **__: None)
    variant = {
        "workerPythonSha256": "2" * 64,
        "workerEnvironmentSha256": "5" * 64,
        "workerVenvRootSha256": "6" * 64,
        "workerResolvedPythonSha256": "7" * 64,
        "workerFlowEvidenceSha256": "0" * 64,
    }
    with pytest.raises(mod.ProductionAcceptanceError, match="production_scenario_binding_failed:formal"):
        mod.validate_scenario(
            scenario_path,
            e2e_path,
            mode="formal",
            source_commit="a" * 40,
            target_manifest_sha256="b" * 64,
            acceptance_profile_sha256="c" * 64,
            expected_corpus_sha256="9" * 64,
            mavi_build="build-a",
            deployment_profile=mod.deployment_profiles.select_profile("P2")[0],
            deployment_profile_policy_sha256="f" * 64,
            variant_path=variant_path,
            variant=variant,
            bundle_sha256="d" * 64,
            lock_sha256="e" * 64,
            acceptance_execution_id=EXECUTION_ID,
            acceptance_context_sha256=CONTEXT_SHA,
            expected_operational_host_identity_sha256=WINDOWS_HOST,
        )


def test_final_scenario_cannot_reuse_variant_smoke_e2e(tmp_path: Path, monkeypatch):
    e2e_path = tmp_path / "e2e.json"
    e2e_path.write_text(json.dumps(e2e_payload()), encoding="utf-8")
    e2e_sha = mod.sha256_file(e2e_path)
    scenario = scenario_payload(e2e_sha)
    variant_path = tmp_path / "variant.json"
    variant_path.write_text("{}", encoding="utf-8")
    scenario["linuxCudaVariantEvidenceSha256"] = mod.sha256_file(variant_path)
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")

    monkeypatch.setattr(mod, "validate_schema", lambda *_: None)
    monkeypatch.setattr(mod.evidence_verifier, "verify_acceptance", lambda *_, **__: None)
    monkeypatch.setattr(mod.evidence_verifier, "verify_acceptance", lambda *_, **__: None)
    variant = {
        "workerPythonSha256": "2" * 64,
        "workerEnvironmentSha256": "5" * 64,
        "workerVenvRootSha256": "6" * 64,
        "workerResolvedPythonSha256": "7" * 64,
        "workerFlowEvidenceSha256": e2e_sha,
    }
    with pytest.raises(mod.ProductionAcceptanceError, match="production_scenario_reused_variant_smoke:formal"):
        mod.validate_scenario(
            scenario_path,
            e2e_path,
            mode="formal",
            source_commit="a" * 40,
            target_manifest_sha256="b" * 64,
            acceptance_profile_sha256="c" * 64,
            expected_corpus_sha256="9" * 64,
            mavi_build="build-a",
            deployment_profile=mod.deployment_profiles.select_profile("P2")[0],
            deployment_profile_policy_sha256="f" * 64,
            variant_path=variant_path,
            variant=variant,
            bundle_sha256="d" * 64,
            lock_sha256="e" * 64,
            acceptance_execution_id=EXECUTION_ID,
            acceptance_context_sha256=CONTEXT_SHA,
            expected_operational_host_identity_sha256=WINDOWS_HOST,
        )


def test_failure_reprocess_rejects_source_drift(tmp_path: Path, monkeypatch):
    variant_path = tmp_path / "variant.json"
    variant_path.write_text("{}", encoding="utf-8")
    value = {
        "schemaVersion": "mavi-production-failure-reprocess-evidence-v2",
        "acceptanceExecutionId": EXECUTION_ID,
        "acceptanceContextSha256": CONTEXT_SHA,
        "scenarioStartedAtUtc": "2026-09-14T18:12:00Z",
        "scenarioCompletedAtUtc": "2026-09-14T18:13:00Z",
        "sourceCommit": "a" * 40,
        "maviBuild": "build-a",
        "operationalHostIdentitySha256": WINDOWS_HOST,
        "targetVerifiedManifestSha256": "b" * 64,
        "deploymentProfile": "P2",
        "deploymentProfilePolicySha256": "f" * 64,
        "runtimeVariant": "linux-x86_64-cuda",
        "productionBundleManifestSha256": "d" * 64,
        "productionReleaseLockSha256": "e" * 64,
        "variantEvidenceSha256": mod.sha256_file(variant_path),
        "workerPythonSha256": "2" * 64,
        "workerEnvironmentSha256": "5" * 64,
        "workerVenvRootSha256": "6" * 64,
        "workerResolvedPythonSha256": "7" * 64,
        "firstProcessingRunId": "11111111-1111-1111-1111-111111111111",
        "reprocessProcessingRunId": "22222222-2222-2222-2222-222222222222",
        "sourceMedia": {
            "localSha256": "1" * 64,
            "afterFailureSha256": "1" * 64,
            "afterFailureEtagSha256": "1" * 64,
            "afterReprocessSha256": "9" * 64,
            "afterReprocessEtagSha256": "1" * 64,
        },
        "trackCount": 1,
        "workerLogSha256": "4" * 64,
        "networkIsolation": {
            "proxyEnvironmentAbsent": True,
            "probes": [{"host": f"h{i}", "port": 443, "reachable": False} for i in range(5)],
            "passed": True,
        },
        "reprocessAttestation": {
            "verificationStatus": "verified",
            "runtimeVariant": "linux-x86_64-cuda",
            "maviBuild": "build-a",
            "maviCommit": "a" * 40,
            "modelManifestSha256": "b" * 64,
            "platformLockSha256": "e" * 64,
            "actualDevice": "cuda:0",
        },
        "result": {"passed": True, "failureCodes": []},
    }
    path = tmp_path / "failure.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(mod, "validate_schema", lambda *_: None)
    monkeypatch.setattr(mod.evidence_verifier, "verify_acceptance", lambda *_, **__: None)
    variant = {
        "workerPythonSha256": "2" * 64,
        "workerEnvironmentSha256": "5" * 64,
        "workerVenvRootSha256": "6" * 64,
        "workerResolvedPythonSha256": "7" * 64,
    }
    with pytest.raises(mod.ProductionAcceptanceError, match="production_failure_reprocess_binding_failed"):
        mod.validate_failure_reprocess(
            path,
            source_commit="a" * 40,
            mavi_build="build-a",
            target_manifest_sha256="b" * 64,
            deployment_profile=mod.deployment_profiles.select_profile("P2")[0],
            deployment_profile_policy_sha256="f" * 64,
            variant_path=variant_path,
            variant=variant,
            bundle_sha256="d" * 64,
            lock_sha256="e" * 64,
            acceptance_execution_id=EXECUTION_ID,
            acceptance_context_sha256=CONTEXT_SHA,
            expected_operational_host_identity_sha256=WINDOWS_HOST,
        )


def _log_window_fixture(tmp_path: Path):
    context_path = tmp_path / "context.json"
    context_path.write_text("{}", encoding="utf-8")
    checkpoint_path = tmp_path / "checkpoint.json"
    paths = {}
    checkpoint_logs = []
    entries = []
    worker_hashes = {}
    for role in ("api", "iis", "postgres", "formal-worker", "empty-worker", "failure-worker"):
        path = tmp_path / f"{role}.log"
        if role in {"api", "iis", "postgres"}:
            prefix = f"{role} before\n".encode()
            segment = f"{role} acceptance\n".encode()
            path.write_bytes(prefix + segment)
            checkpoint_logs.append({
                "role": role,
                "path": str(path.resolve()),
                "startOffset": len(prefix),
                "prefixSha256": mod.hashlib.sha256(prefix).hexdigest(),
            })
            start = len(prefix)
        else:
            segment = f"{role} acceptance\n".encode()
            path.write_bytes(segment)
            start = 0
            worker_hashes[role] = mod.hashlib.sha256(segment).hexdigest()
        raw = path.read_bytes()
        paths[role] = path
        entries.append({
            "role": role,
            "path": str(path.resolve()),
            "startOffset": start,
            "endOffset": len(raw),
            "segmentSizeBytes": len(segment),
            "segmentSha256": mod.hashlib.sha256(segment).hexdigest(),
        })
    checkpoint = {
        "acceptanceExecutionId": EXECUTION_ID,
        "acceptanceContextSha256": CONTEXT_SHA,
        "capturedAtUtc": "2026-09-14T18:05:00Z",
        "logs": checkpoint_logs,
    }
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")
    return context_path, checkpoint_path, paths, entries, worker_hashes


def test_log_inspection_rejects_checkpoint_after_scenario(tmp_path: Path, monkeypatch):
    context_path, checkpoint_path, paths, entries, worker_hashes = _log_window_fixture(tmp_path)
    checkpoint = json.loads(checkpoint_path.read_text())
    checkpoint["capturedAtUtc"] = "2026-09-14T18:20:00Z"
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")

    value = {
        "acceptanceExecutionId": EXECUTION_ID,
        "acceptanceContextSha256": CONTEXT_SHA,
        "serverLogCheckpointSha256": mod.sha256_file(checkpoint_path),
        "acceptanceStartedAtUtc": "2026-09-14T18:00:00Z",
        "inspectionCompletedAtUtc": "2026-09-14T18:30:00Z",
        "sourceCommit": "a" * 40,
        "maviBuild": "build-a",
        "formalScenarioSha256": "1" * 64,
        "formalE2eSha256": "2" * 64,
        "emptySceneScenarioSha256": "3" * 64,
        "emptySceneDiagnosticSha256": "4" * 64,
        "failureReprocessSha256": "5" * 64,
        "allowedHosts": ["localhost", "127.0.0.1", "::1"],
        "logs": entries,
        "result": {"passed": True, "externalUrlHits": [], "telemetryOrLicenceHits": [], "failureCodes": []},
    }
    inspection = tmp_path / "inspection.json"
    inspection.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(mod, "validate_schema", lambda *_: None)
    monkeypatch.setattr(mod.evidence_verifier, "verify_acceptance", lambda *_, **__: None)
    monkeypatch.setattr(
        mod,
        "load_acceptance_context",
        lambda *_, **__: ({
            "acceptanceExecutionId": EXECUTION_ID,
            "startedAtUtc": "2026-09-14T18:00:00Z",
        }, CONTEXT_SHA),
    )
    formal = {
        "scenarioStartedAtUtc": "2026-09-14T18:10:00Z",
        "scenarioCompletedAtUtc": "2026-09-14T18:11:00Z",
    }
    empty = {
        "scenarioStartedAtUtc": "2026-09-14T18:12:00Z",
        "scenarioCompletedAtUtc": "2026-09-14T18:13:00Z",
    }
    failure = {
        "scenarioStartedAtUtc": "2026-09-14T18:14:00Z",
        "scenarioCompletedAtUtc": "2026-09-14T18:15:00Z",
    }
    with pytest.raises(mod.ProductionAcceptanceError, match="production_acceptance_time_order_invalid"):
        mod.validate_log_inspection(
            inspection,
            context_path=context_path,
            checkpoint_path=checkpoint_path,
            log_paths=paths,
            source_commit="a" * 40,
            mavi_build="build-a",
            formal_scenario_sha256="1" * 64,
            formal_e2e_sha256="2" * 64,
            empty_scenario_sha256="3" * 64,
            empty_e2e_sha256="4" * 64,
            failure_sha256="5" * 64,
            formal_worker_log_sha256=worker_hashes["formal-worker"],
            empty_worker_log_sha256=worker_hashes["empty-worker"],
            failure_worker_log_sha256=worker_hashes["failure-worker"],
            formal_scenario=formal,
            empty_scenario=empty,
            failure_evidence=failure,
        )


def test_backup_rejects_restore_topology_database_mismatch(tmp_path: Path):
    path, proofs = _backup_proof_fixture(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["restoreStorageTopology"]["databaseIdentitySha256"] = "1" * 64
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(mod.ProductionAcceptanceError, match="production_backup_restore_binding_failed"):
        mod.validate_backup(
            path,
            source_commit="a" * 40,
            mavi_build="build-a",
            acceptance_profile_sha256="c" * 64,
            formal_e2e_sha256="1" * 64,
            **proofs,
        )


def _state_check_payload(
    *,
    acceptance_sha: str = "1" * 64,
    acceptance_commit: str = "a" * 40,
    expected_commit: str = "a" * 40,
    expected_build: str = "prior-build",
    camera_id: str = "camera-1",
) -> dict:
    return {
        "schemaVersion": "mavi-authoritative-state-check-v1",
        "acceptanceEvidenceSha256": acceptance_sha,
        "acceptanceSourceCommit": acceptance_commit,
        "expectedApplicationCommit": expected_commit,
        "observedApplicationCommit": expected_commit,
        "expectedApplicationBuild": expected_build,
        "observedApplicationBuild": expected_build,
        "operationalHostIdentitySha256": WINDOWS_HOST,
        "authoritativeStateSha256": "7" * 64,
        "cameraId": camera_id,
        "videoAssetId": "video-1",
        "processingRunId": "run-1",
        "trackIds": ["track-1"],
        "representativeArtifactId": "artifact-1",
        "sourceSha256": "2" * 64,
        "sourceEtagSha256": "2" * 64,
        "artifactSha256": "3" * 64,
        "artifactEtagSha256": "3" * 64,
        "result": {"passed": True, "failureCodes": []},
    }


def _prior_manifest(tmp_path: Path) -> Path:
    path = tmp_path / "prior-manifest.json"
    path.write_text(json.dumps({
        "schemaVersion": "mavi-application-artifact-v1",
        "sourceCommit": "a" * 40,
        "build": "prior-build",
        "files": [],
    }), encoding="utf-8")
    return path


def _prior_acceptance(tmp_path: Path) -> Path:
    path = tmp_path / "prior-acceptance.json"
    path.write_text(json.dumps({
        "schemaVersion": "mavi-phase1-acceptance-evidence-v1",
        "sourceCommit": "a" * 40,
        "operationalApi": {"hostIdentitySha256": WINDOWS_HOST},
        "attestation": {
            "maviCommit": "a" * 40,
            "maviBuild": "prior-build",
        },
        "result": {"passed": True, "failureCodes": []},
    }), encoding="utf-8")
    return path


def _offline_update_value(
    pre_sha: str,
    post_sha: str,
    prior_manifest_sha: str,
    prior_acceptance_sha: str,
    *,
    migration_policy: str = "none",
) -> dict:
    return {
        "schemaVersion": "mavi-application-lifecycle-evidence-v1",
        "mode": "offline-update",
        "sourceCommit": "b" * 40,
        "build": "target-build",
        "applicationManifestSha256": "4" * 64,
        "supportedUpdatesPolicySha256": "5" * 64,
        "destination": "mavi-root",
        "deployment": {
            "mechanism": "robocopy-mirror",
            "tool": "robocopy.exe",
            "toolVersion": "10.0.0",
            "arguments": ["source", "target", "/MIR", "/COPY:DAT"],
            "exitCode": 1,
            "passed": True,
        },
        "hosting": {
            "siteName": "MAVI",
            "applicationPool": "MAVI",
            "physicalPath": "mavi-root",
            "hostIdentitySha256": WINDOWS_HOST,
            "passed": True,
        },
        "operationalApi": {
            "baseUrl": "http://mavi.local",
            "hostIdentitySha256": WINDOWS_HOST,
            "passed": True,
        },
        "internetUnavailable": True,
        "networkIsolation": {
            "proxyEnvironmentAbsent": True,
            "probes": [{}, {}, {}, {}, {}],
            "passed": True,
        },
        "priorRelease": {
            "sourceCommit": "a" * 40,
            "build": "prior-build",
            "applicationManifestSha256": prior_manifest_sha,
            "supported": True,
        },
        "migrationPolicy": migration_policy,
        "migration": None,
        "retainedState": {
            "acceptanceEvidenceSha256": prior_acceptance_sha,
            "preUpdateCheckSha256": pre_sha,
            "postUpdateCheckSha256": post_sha,
        },
        "uiSmoke": {
            "rootStatusCode": 200,
            "rootBytes": 1,
            "assetCount": 1,
            "passed": True,
        },
        "observedHealth": {
            "status": "ok",
            "build": "target-build",
            "commit": "b" * 40,
        },
        "result": {"passed": True, "failureCodes": []},
    }


def test_supported_prior_rejects_forged_manifest_hash(monkeypatch):
    policy = {
        "priorReleases": [{
            "sourceCommit": "a" * 40,
            "applicationManifestSha256": "8" * 64,
            "migrationPolicy": "none",
        }]
    }
    monkeypatch.setattr(mod, "load_json", lambda *_: policy)
    with pytest.raises(
        mod.ProductionAcceptanceError,
        match="production_offline_update_prior_policy_mismatch",
    ):
        mod._validate_supported_prior(
            {
                "sourceCommit": "a" * 40,
                "applicationManifestSha256": "7" * 64,
            },
            "none",
        )


def test_offline_update_rejects_missing_required_migration(tmp_path: Path, monkeypatch):
    prior = _prior_manifest(tmp_path)
    prior_acceptance = _prior_acceptance(tmp_path)
    acceptance_sha = mod.sha256_file(prior_acceptance)
    pre = tmp_path / "pre.json"
    post = tmp_path / "post.json"
    pre.write_text(json.dumps(_state_check_payload(acceptance_sha=acceptance_sha)), encoding="utf-8")
    post.write_text(json.dumps(_state_check_payload(
        acceptance_sha=acceptance_sha,
        expected_commit="b" * 40,
        expected_build="target-build",
    )), encoding="utf-8")
    lifecycle = tmp_path / "update.json"
    lifecycle.write_text(json.dumps(_offline_update_value(
        mod.sha256_file(pre),
        mod.sha256_file(post),
        mod.sha256_file(prior),
        acceptance_sha,
        migration_policy="required",
    )), encoding="utf-8")
    monkeypatch.setattr(mod, "validate_schema", lambda *_: None)
    monkeypatch.setattr(mod.evidence_verifier, "verify_acceptance", lambda *_, **__: None)
    monkeypatch.setattr(
        mod,
        "_validate_supported_prior",
        lambda *_: {"migrationScriptSha256": "a" * 64},
    )
    with pytest.raises(
        mod.ProductionAcceptanceError,
        match="production_offline_update_migration_invalid",
    ):
        mod.validate_lifecycle(
            lifecycle,
            mode="offline-update",
            source_commit="b" * 40,
            mavi_build="target-build",
            application_manifest_sha256="4" * 64,
            supported_updates_policy_sha256="5" * 64,
            prior_application_manifest=prior,
            prior_acceptance_evidence=prior_acceptance,
            pre_update_state_check=pre,
            post_update_state_check=post,
        )


def test_offline_update_rejects_cross_spliced_retained_state(tmp_path: Path, monkeypatch):
    prior = _prior_manifest(tmp_path)
    prior_acceptance = _prior_acceptance(tmp_path)
    acceptance_sha = mod.sha256_file(prior_acceptance)
    pre = tmp_path / "pre.json"
    post = tmp_path / "post.json"
    pre.write_text(json.dumps(_state_check_payload(acceptance_sha=acceptance_sha)), encoding="utf-8")
    post.write_text(json.dumps(_state_check_payload(
        acceptance_sha=acceptance_sha,
        expected_commit="b" * 40,
        expected_build="target-build",
        camera_id="other-camera",
    )), encoding="utf-8")
    lifecycle = tmp_path / "update.json"
    lifecycle.write_text(json.dumps(_offline_update_value(
        mod.sha256_file(pre),
        mod.sha256_file(post),
        mod.sha256_file(prior),
        acceptance_sha,
    )), encoding="utf-8")
    monkeypatch.setattr(mod, "validate_schema", lambda *_: None)
    monkeypatch.setattr(mod.evidence_verifier, "verify_acceptance", lambda *_, **__: None)
    monkeypatch.setattr(mod, "_validate_supported_prior", lambda *_: {})
    with pytest.raises(
        mod.ProductionAcceptanceError,
        match="production_offline_update_retained_state_mismatch",
    ):
        mod.validate_lifecycle(
            lifecycle,
            mode="offline-update",
            source_commit="b" * 40,
            mavi_build="target-build",
            application_manifest_sha256="4" * 64,
            supported_updates_policy_sha256="5" * 64,
            prior_application_manifest=prior,
            prior_acceptance_evidence=prior_acceptance,
            pre_update_state_check=pre,
            post_update_state_check=post,
        )


def test_offline_update_rejects_wrong_prior_running_build(tmp_path: Path, monkeypatch):
    prior = _prior_manifest(tmp_path)
    prior_acceptance = _prior_acceptance(tmp_path)
    acceptance_sha = mod.sha256_file(prior_acceptance)
    pre = tmp_path / "pre.json"
    post = tmp_path / "post.json"
    pre.write_text(json.dumps(_state_check_payload(
        acceptance_sha=acceptance_sha,
        expected_build="wrong-prior-build",
    )), encoding="utf-8")
    post.write_text(json.dumps(_state_check_payload(
        acceptance_sha=acceptance_sha,
        expected_commit="b" * 40,
        expected_build="target-build",
    )), encoding="utf-8")
    lifecycle = tmp_path / "update.json"
    lifecycle.write_text(json.dumps(_offline_update_value(
        mod.sha256_file(pre),
        mod.sha256_file(post),
        mod.sha256_file(prior),
        acceptance_sha,
    )), encoding="utf-8")
    monkeypatch.setattr(mod, "validate_schema", lambda *_: None)
    monkeypatch.setattr(mod.evidence_verifier, "verify_acceptance", lambda *_, **__: None)
    monkeypatch.setattr(mod, "_validate_supported_prior", lambda *_: {})
    with pytest.raises(
        mod.ProductionAcceptanceError,
        match="production_pre_update_state_binding_failed",
    ):
        mod.validate_lifecycle(
            lifecycle,
            mode="offline-update",
            source_commit="b" * 40,
            mavi_build="target-build",
            application_manifest_sha256="4" * 64,
            supported_updates_policy_sha256="5" * 64,
            prior_application_manifest=prior,
            prior_acceptance_evidence=prior_acceptance,
            pre_update_state_check=pre,
            post_update_state_check=post,
        )


def test_offline_update_rejects_missing_state_proofs(tmp_path: Path, monkeypatch):
    prior = _prior_manifest(tmp_path)
    prior_acceptance = _prior_acceptance(tmp_path)
    acceptance_sha = mod.sha256_file(prior_acceptance)
    lifecycle = tmp_path / "update.json"
    lifecycle.write_text(json.dumps(_offline_update_value(
        "8" * 64,
        "9" * 64,
        mod.sha256_file(prior),
        acceptance_sha,
    )), encoding="utf-8")
    monkeypatch.setattr(mod, "validate_schema", lambda *_: None)
    monkeypatch.setattr(mod.evidence_verifier, "verify_acceptance", lambda *_, **__: None)
    with pytest.raises(mod.ProductionAcceptanceError, match="production_offline_update_invalid"):
        mod.validate_lifecycle(
            lifecycle,
            mode="offline-update",
            source_commit="b" * 40,
            mavi_build="target-build",
            application_manifest_sha256="4" * 64,
            supported_updates_policy_sha256="5" * 64,
            prior_application_manifest=prior,
            prior_acceptance_evidence=prior_acceptance,
        )


def test_offline_update_rejects_prior_acceptance_hash_splice(tmp_path: Path, monkeypatch):
    prior = _prior_manifest(tmp_path)
    prior_acceptance = _prior_acceptance(tmp_path)
    acceptance_sha = mod.sha256_file(prior_acceptance)
    pre = tmp_path / "pre.json"
    post = tmp_path / "post.json"
    pre.write_text(json.dumps(_state_check_payload(acceptance_sha=acceptance_sha)), encoding="utf-8")
    post.write_text(json.dumps(_state_check_payload(
        acceptance_sha=acceptance_sha,
        expected_commit="b" * 40,
        expected_build="target-build",
    )), encoding="utf-8")
    lifecycle = tmp_path / "update.json"
    lifecycle.write_text(json.dumps(_offline_update_value(
        mod.sha256_file(pre),
        mod.sha256_file(post),
        mod.sha256_file(prior),
        "9" * 64,
    )), encoding="utf-8")
    monkeypatch.setattr(mod, "validate_schema", lambda *_: None)
    monkeypatch.setattr(mod.evidence_verifier, "verify_acceptance", lambda *_, **__: None)
    monkeypatch.setattr(mod, "_validate_supported_prior", lambda *_: {})
    with pytest.raises(
        mod.ProductionAcceptanceError,
        match="production_prior_acceptance_evidence_mismatch",
    ):
        mod.validate_lifecycle(
            lifecycle,
            mode="offline-update",
            source_commit="b" * 40,
            mavi_build="target-build",
            application_manifest_sha256="4" * 64,
            supported_updates_policy_sha256="5" * 64,
            prior_application_manifest=prior,
            prior_acceptance_evidence=prior_acceptance,
            pre_update_state_check=pre,
            post_update_state_check=post,
        )


def test_offline_update_rejects_prior_acceptance_from_different_build(
    tmp_path: Path,
    monkeypatch,
):
    prior = _prior_manifest(tmp_path)
    prior_acceptance = _prior_acceptance(tmp_path)
    value = json.loads(prior_acceptance.read_text(encoding="utf-8"))
    value["attestation"]["maviBuild"] = "other-build"
    prior_acceptance.write_text(json.dumps(value), encoding="utf-8")
    acceptance_sha = mod.sha256_file(prior_acceptance)
    pre = tmp_path / "pre-build.json"
    post = tmp_path / "post-build.json"
    pre.write_text(json.dumps(_state_check_payload(
        acceptance_sha=acceptance_sha,
    )), encoding="utf-8")
    post.write_text(json.dumps(_state_check_payload(
        acceptance_sha=acceptance_sha,
        expected_commit="b" * 40,
        expected_build="target-build",
    )), encoding="utf-8")
    lifecycle = tmp_path / "update-build.json"
    lifecycle.write_text(json.dumps(_offline_update_value(
        mod.sha256_file(pre),
        mod.sha256_file(post),
        mod.sha256_file(prior),
        acceptance_sha,
    )), encoding="utf-8")
    monkeypatch.setattr(mod, "validate_schema", lambda *_: None)
    monkeypatch.setattr(mod.evidence_verifier, "verify_acceptance", lambda *_, **__: None)
    monkeypatch.setattr(mod, "_validate_supported_prior", lambda *_: {})
    with pytest.raises(
        mod.ProductionAcceptanceError,
        match="production_prior_acceptance_release_identity_mismatch",
    ):
        mod.validate_lifecycle(
            lifecycle,
            mode="offline-update",
            source_commit="b" * 40,
            mavi_build="target-build",
            application_manifest_sha256="4" * 64,
            supported_updates_policy_sha256="5" * 64,
            prior_application_manifest=prior,
            prior_acceptance_evidence=prior_acceptance,
            pre_update_state_check=pre,
            post_update_state_check=post,
        )


def test_lifecycle_rejects_missing_deployment_audit(tmp_path: Path, monkeypatch):
    prior = _prior_manifest(tmp_path)
    prior_acceptance = _prior_acceptance(tmp_path)
    acceptance_sha = mod.sha256_file(prior_acceptance)
    pre = tmp_path / "pre-deployment.json"
    post = tmp_path / "post-deployment.json"
    pre.write_text(json.dumps(_state_check_payload(
        acceptance_sha=acceptance_sha,
    )), encoding="utf-8")
    post.write_text(json.dumps(_state_check_payload(
        acceptance_sha=acceptance_sha,
        expected_commit="b" * 40,
        expected_build="target-build",
    )), encoding="utf-8")
    value = _offline_update_value(
        mod.sha256_file(pre),
        mod.sha256_file(post),
        mod.sha256_file(prior),
        acceptance_sha,
    )
    value.pop("deployment")
    lifecycle = tmp_path / "update-no-deployment.json"
    lifecycle.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(mod, "validate_schema", lambda *_: None)
    with pytest.raises(
        mod.ProductionAcceptanceError,
        match="production_lifecycle_deployment_audit_failed",
    ):
        mod.validate_lifecycle(
            lifecycle,
            mode="offline-update",
            source_commit="b" * 40,
            mavi_build="target-build",
            application_manifest_sha256="4" * 64,
            supported_updates_policy_sha256="5" * 64,
            prior_application_manifest=prior,
            prior_acceptance_evidence=prior_acceptance,
            pre_update_state_check=pre,
            post_update_state_check=post,
        )
