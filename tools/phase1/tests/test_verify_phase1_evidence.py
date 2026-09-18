from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "verify_phase1_evidence.py"
SPEC = importlib.util.spec_from_file_location("phase1_evidence_verifier", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def offline(
    os_name="linux",
    *,
    device="cuda",
    profile="P2",
):
    variant = f"{os_name}-x86_64-{device}"
    item = {
        "variant": variant,
        "bundleManifestSha256": "a" * 64,
        "releaseLockSha256": "c" * 64,
        "expectedHostCompatibility": {
            "os": os_name,
            "abi": "qualified",
        },
        "observedHostCompatibility": {
            "os": os_name,
            "abi": "qualified",
        },
        "installCommand":
            "pip install --no-index --only-binary=:all: "
            "--require-hashes --find-links wheelhouse -r lock.txt",
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
        "actualDevice": "cpu" if device == "cpu" else "cuda:0",
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
    return {
        "schemaVersion": "mavi-offline-install-evidence-v2",
        "sourceCommit": "d" * 40,
        "targetVerifiedManifestSha256": "e" * 64,
        "acceptanceProfileSha256": "f" * 64,
        "maviBuild": "build-a",
        "deploymentProfile": profile,
        "deploymentProfilePolicySha256": "7" * 64,
        "os": os_name,
        "bundleMode": "qualification-candidate",
        "isolationMethod":
            "physically isolated qualification VLAN",
        "variantEvidenceSha256": {
            variant: "9" * 64,
        },
        "variants": [item],
        "result": "passed",
    }


def test_offline_requires_exact_selected_variant():
    value = offline()
    with pytest.raises(
        mod.EvidenceError,
        match="offline_variant_coverage_incomplete",
    ):
        mod.verify_offline_install(
            value,
            expected_runtime_variant="windows-x86_64-cuda",
        )


def test_offline_rejects_host_contract_mismatch():
    value = offline()
    value["variants"][0]["observedHostCompatibility"]["abi"] = (
        "different"
    )
    with pytest.raises(
        mod.EvidenceError,
        match="offline_host_compatibility_mismatch",
    ):
        mod.verify_offline_install(value)


def test_offline_rejects_weak_pip_command():
    value = offline()
    value["variants"][0]["installCommand"] = "pip install -r lock.txt"
    with pytest.raises(
        mod.EvidenceError,
        match="offline_install_command_not_strict",
    ):
        mod.verify_offline_install(value)


def test_offline_rejects_cuda_cpu_fallback():
    value = offline()
    value["variants"][0]["actualDevice"] = "cpu"
    with pytest.raises(
        mod.EvidenceError,
        match="offline_cuda_device_mismatch",
    ):
        mod.verify_offline_install(value)


def test_offline_complete_profile_package_passes():
    mod.verify_offline_install(
        offline(),
        expected_deployment_profile="P2",
        expected_runtime_variant="linux-x86_64-cuda",
        expected_deployment_profile_policy_sha256="7" * 64,
    )


def test_windows_offline_schema_allows_frozen_null_distribution_fields(
    tmp_path,
):
    value = offline(
        "windows",
        device="cuda",
        profile="P1",
    )
    item = value["variants"][0]
    item["expectedHostCompatibility"] = {
        "osFamily": "windows",
        "architecture": "x86_64",
        "distribution": None,
        "distributionVersion": None,
        "nativeAbi": "win_amd64",
        "portability": "qualified-platform",
    }
    item["observedHostCompatibility"] = dict(
        item["expectedHostCompatibility"]
    )
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "offline-install-evidence.schema.json"
    )
    mod._validate_schema(value, schema_path)
    mod.verify_offline_install(
        value,
        expected_deployment_profile="P1",
        expected_runtime_variant="windows-x86_64-cuda",
    )


def test_offline_rejects_incomplete_variant_evidence_hash_binding():
    value = offline()
    value["variantEvidenceSha256"] = {
        "linux-x86_64-cuda": "9" * 64,
        "windows-x86_64-cpu": "b" * 64,
    }
    with pytest.raises(
        mod.EvidenceError,
        match="offline_variant_evidence_hash_coverage_incomplete",
    ):
        mod.verify_offline_install(value)



def test_acceptance_rejects_wrong_frozen_profile_hash():
    value = {
        "sourceCommit": "a" * 40,
        "acceptanceProfileSha256": "b" * 64,
    }
    with pytest.raises(mod.EvidenceError, match="acceptance_profile_hash_mismatch"):
        mod.verify_acceptance(
            value,
            expected_source_commit="a" * 40,
            expected_acceptance_profile_sha256="c" * 64,
        )


def test_offline_rejects_incomplete_variant_evidence_hash_binding():
    value = offline()
    value["variantEvidenceSha256"] = {
        "linux-x86_64-cpu": "9" * 64,
        "linux-x86_64-cuda": "a" * 64,
        "windows-x86_64-cpu": "b" * 64,
    }
    with pytest.raises(
        mod.EvidenceError,
        match="offline_variant_evidence_hash_coverage_incomplete",
    ):
        mod.verify_offline_install(value)


def test_acceptance_rejects_attested_commit_different_from_source_commit():
    value = {
        "sourceCommit": "a" * 40,
        "acceptanceProfileSha256": "b" * 64,
        "attestation": {
            "processingRunId": "run-1",
            "maviCommit": "c" * 40,
        },
        "processing": {"processingRunId": "run-1"},
    }
    with pytest.raises(mod.EvidenceError, match="acceptance_attested_commit_mismatch"):
        mod.verify_acceptance(value)
