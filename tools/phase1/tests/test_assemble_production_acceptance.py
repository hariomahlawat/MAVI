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


def test_candidate_variant_cannot_satisfy_production_acceptance(tmp_path: Path):
    path = tmp_path / "variant.json"
    path.write_text(json.dumps(variant_payload("qualification-candidate")), encoding="utf-8")
    with pytest.raises(
        mod.ProductionAcceptanceError,
        match="production_variant_binding_failed",
    ):
        mod.validate_variant(
            path,
            variant="linux-x86_64-cpu",
            source_commit="a" * 40,
            target_manifest_sha256="b" * 64,
            acceptance_profile_sha256="c" * 64,
            mavi_build="build-a",
        )


def test_production_variant_set_requires_all_four():
    with pytest.raises(
        mod.ProductionAcceptanceError,
        match="production_variant_set_incomplete",
    ):
        mod.parse_variant_arguments([
            "linux-x86_64-cpu=a.json",
            "linux-x86_64-cuda=b.json",
        ])


def test_backup_must_reference_exact_final_e2e(tmp_path: Path):
    value = {
        "schemaVersion": "mavi-backup-restore-evidence-v1",
        "sourceCommit": "a" * 40,
        "acceptanceEvidenceSha256": "1" * 64,
        "acceptanceProfileSha256": "c" * 64,
        "executionEvidenceSha256": "2" * 64,
        "sourceDatabaseIdentity": "source|127.0.0.1|5432",
        "restoreDatabaseIdentity": "restore|127.0.0.1|5433",
        "database": {"included": True, "manifestSha256": "3" * 64},
        "managedSource": {"included": True, "manifestSha256": "4" * 64},
        "acceptedEvidence": {"included": True, "manifestSha256": "5" * 64},
        "backupManifestSha256": "6" * 64,
        "cleanRestoreTarget": True,
        "postRestoreCheckSha256": "7" * 64,
        "result": {"passed": True, "failureCodes": []},
    }
    path = tmp_path / "backup.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(
        mod.ProductionAcceptanceError,
        match="production_backup_restore_binding_failed",
    ):
        mod.validate_backup(
            path,
            source_commit="a" * 40,
            acceptance_profile_sha256="c" * 64,
            formal_e2e_sha256="9" * 64,
        )


def test_log_inspection_rejects_worker_log_from_other_execution(
    tmp_path: Path,
    monkeypatch,
):
    roles = (
        "api", "iis", "postgres",
        "formal-worker", "empty-worker", "failure-worker",
    )
    paths = {}
    entries = []
    for role in roles:
        path = tmp_path / f"{role}.log"
        payload = f"{role} clean local log\n".encode()
        path.write_bytes(payload)
        paths[role] = path
        entries.append({
            "role": role,
            "path": path.name,
            "sizeBytes": len(payload),
            "sha256": mod.hashlib.sha256(payload).hexdigest(),
        })

    value = {
        "sourceCommit": "a" * 40,
        "maviBuild": "build-a",
        "formalE2eSha256": "1" * 64,
        "emptySceneDiagnosticSha256": "2" * 64,
        "failureReprocessSha256": "3" * 64,
        "allowedHosts": ["localhost", "127.0.0.1", "::1"],
        "logs": entries,
        "result": {
            "passed": True,
            "externalUrlHits": [],
            "telemetryOrLicenceHits": [],
            "failureCodes": [],
        },
    }
    path = tmp_path / "logs.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(mod, "validate_schema", lambda *_: None)

    with pytest.raises(
        mod.ProductionAcceptanceError,
        match="production_log_inspection_binding_failed",
    ):
        mod.validate_log_inspection(
            path,
            log_paths=paths,
            source_commit="a" * 40,
            mavi_build="build-a",
            formal_e2e_sha256="1" * 64,
            empty_e2e_sha256="2" * 64,
            failure_sha256="3" * 64,
            formal_worker_log_sha256="9" * 64,
            empty_worker_log_sha256=next(
                item["sha256"]
                for item in entries
                if item["role"] == "empty-worker"
            ),
            failure_worker_log_sha256=next(
                item["sha256"]
                for item in entries
                if item["role"] == "failure-worker"
            ),
        )


def test_final_scenario_cannot_reuse_variant_smoke_e2e(
    tmp_path: Path,
    monkeypatch,
):
    e2e = {
        "mode": "formal",
        "sourceCommit": "a" * 40,
        "targetVerifiedManifestSha256": "b" * 64,
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
    e2e_path = tmp_path / "e2e.json"
    e2e_path.write_text(json.dumps(e2e), encoding="utf-8")
    e2e_sha = mod.sha256_file(e2e_path)

    scenario = {
        "mode": "formal",
        "sourceCommit": "a" * 40,
        "maviBuild": "build-a",
        "targetVerifiedManifestSha256": "b" * 64,
        "linuxCudaVariantEvidenceSha256": "f" * 64,
        "productionBundleManifestSha256": "d" * 64,
        "productionReleaseLockSha256": "e" * 64,
        "workerPythonSha256": "2" * 64,
        "e2eEvidenceSha256": e2e_sha,
        "workerLogSha256": "3" * 64,
        "result": {"passed": True, "failureCodes": []},
    }
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
    variant_path = tmp_path / "variant.json"
    variant_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(mod, "validate_schema", lambda *_: None)
    monkeypatch.setattr(
        mod.evidence_verifier,
        "verify_acceptance",
        lambda *_, **__: None,
    )
    variant = {
        "workerPythonSha256": "2" * 64,
        "workerFlowEvidenceSha256": e2e_sha,
    }
    scenario["linuxCudaVariantEvidenceSha256"] = mod.sha256_file(variant_path)
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")

    with pytest.raises(
        mod.ProductionAcceptanceError,
        match="production_scenario_reused_variant_smoke:formal",
    ):
        mod.validate_scenario(
            scenario_path,
            e2e_path,
            mode="formal",
            source_commit="a" * 40,
            target_manifest_sha256="b" * 64,
            acceptance_profile_sha256="c" * 64,
            expected_corpus_sha256="9" * 64,
            mavi_build="build-a",
            linux_cuda_variant_path=variant_path,
            linux_cuda_variant=variant,
            linux_cuda_bundle_sha256="d" * 64,
            linux_cuda_lock_sha256="e" * 64,
        )


def test_failure_reprocess_rejects_source_drift(
    tmp_path: Path,
    monkeypatch,
):
    variant_path = tmp_path / "variant.json"
    variant_path.write_text("{}", encoding="utf-8")
    value = {
        "sourceCommit": "a" * 40,
        "maviBuild": "build-a",
        "targetVerifiedManifestSha256": "b" * 64,
        "productionBundleManifestSha256": "d" * 64,
        "productionReleaseLockSha256": "e" * 64,
        "linuxCudaVariantEvidenceSha256": mod.sha256_file(variant_path),
        "workerPythonSha256": "2" * 64,
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

    with pytest.raises(
        mod.ProductionAcceptanceError,
        match="production_failure_reprocess_binding_failed",
    ):
        mod.validate_failure_reprocess(
            path,
            source_commit="a" * 40,
            mavi_build="build-a",
            target_manifest_sha256="b" * 64,
            linux_cuda_variant_path=variant_path,
            linux_cuda_variant={"workerPythonSha256": "2" * 64},
            linux_cuda_bundle_sha256="d" * 64,
            linux_cuda_lock_sha256="e" * 64,
        )
