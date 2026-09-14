from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "qualify_offline_variant.py"
SPEC = importlib.util.spec_from_file_location("offline_variant", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def test_observed_windows_contract_is_not_linux(monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    monkeypatch.setattr(mod.platform, "machine", lambda: "AMD64")
    observed = mod.observed_host({"portability": "qualified-platform"})
    assert observed == {
        "osFamily": "windows",
        "architecture": "x86_64",
        "distribution": None,
        "distributionVersion": None,
        "nativeAbi": "win_amd64",
        "portability": "qualified-platform",
    }


def test_venv_python_path_matches_host(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    assert mod._venv_python(tmp_path) == tmp_path / "Scripts" / "python.exe"
    monkeypatch.setattr(mod.platform, "system", lambda: "Linux")
    assert mod._venv_python(tmp_path) == tmp_path / "bin" / "python"


def _worker(platform_value):
    return {
        "mode": "formal",
        "targetVerifiedManifestSha256": "a" * 64,
        "attestation": {
            "verificationStatus": "unverified",
            "runtimeVariant": "linux-x86_64-cpu",
            "candidateBundleManifestSha256": "b" * 64,
            "candidateSelectedLockSha256": "c" * 64,
            "productionBundleManifestSha256": None,
            "platformLockSha256": None,
            "maviBuild": "build-a",
            "platform": platform_value,
            "actualDevice": "cpu",
        },
        "evidenceReads": {"passed": 1},
    }


def test_worker_flow_binding_rejects_other_bundle():
    platform_value = {"system": "Linux"}
    value = _worker(platform_value)
    value["attestation"]["candidateBundleManifestSha256"] = "d" * 64
    with pytest.raises(mod.VariantQualificationError, match="variant_worker_flow_evidence_invalid"):
        mod.assert_worker_flow_binding(
            value,
            variant="linux-x86_64-cpu",
            bundle_mode="qualification-candidate",
            target_verified_manifest_sha256="a" * 64,
            bundle_manifest_sha256="b" * 64,
            release_lock_sha256="c" * 64,
            runtime_platform=platform_value,
            device="cpu",
            expected_mavi_build="build-a",
        )


def test_worker_flow_binding_rejects_other_host():
    expected_platform = {"system": "Linux", "release": "qualified"}
    value = _worker({"system": "Linux", "release": "different"})
    with pytest.raises(mod.VariantQualificationError, match="variant_worker_flow_evidence_invalid"):
        mod.assert_worker_flow_binding(
            value,
            variant="linux-x86_64-cpu",
            target_verified_manifest_sha256="a" * 64,
            bundle_manifest_sha256="b" * 64,
            release_lock_sha256="c" * 64,
            runtime_platform=expected_platform,
            device="cpu",
            expected_mavi_build="build-a",
        )


def test_worker_flow_binding_rejects_reused_candidate_evidence_for_production():
    platform_value = {"system": "Linux"}
    value = _worker(platform_value)
    with pytest.raises(mod.VariantQualificationError, match="variant_worker_flow_evidence_invalid"):
        mod.assert_worker_flow_binding(
            value,
            variant="linux-x86_64-cpu",
            bundle_mode="production",
            target_verified_manifest_sha256="a" * 64,
            bundle_manifest_sha256="b" * 64,
            release_lock_sha256="c" * 64,
            runtime_platform=platform_value,
            device="cpu",
            expected_mavi_build="build-a",
        )
