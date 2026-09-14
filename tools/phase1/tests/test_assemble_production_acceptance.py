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
            final_e2e_sha256="9" * 64,
        )
