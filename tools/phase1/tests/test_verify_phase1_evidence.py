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


def offline(os_name="linux"):
    variants = []
    for device in ("cpu", "cuda"):
        variants.append({
            "variant": f"{os_name}-x86_64-{device}",
            "bundleManifestSha256": "a" * 64,
            "releaseLockSha256": ("b" if device == "cpu" else "c") * 64,
            "expectedHostCompatibility": {"os": os_name, "abi": "qualified"},
            "observedHostCompatibility": {"os": os_name, "abi": "qualified"},
            "installCommand": "pip install --no-index --only-binary=:all: --require-hashes --find-links wheelhouse -r lock.txt",
            "installExitCode": 0,
            "pipCheckPassed": True,
            "runtimeStarted": True,
            "realInferencePassed": True,
            "workerFlowPassed": True,
            "actualDevice": "cpu" if device == "cpu" else "cuda:0",
            "outboundNetworkUnavailable": True,
            "firstRunDownloadObserved": False,
            "result": "passed",
        })
    return {
        "schemaVersion": "mavi-offline-install-evidence-v1",
        "sourceCommit": "d" * 40,
        "os": os_name,
        "bundleMode": "qualification-candidate",
        "isolationMethod": "physically isolated qualification VLAN",
        "variants": variants,
        "result": "passed",
    }


def test_offline_requires_cpu_and_cuda():
    value = offline()
    value["variants"] = value["variants"][:1]
    with pytest.raises(mod.EvidenceError, match="offline_variant_coverage_incomplete"):
        mod.verify_offline_install(value)


def test_offline_rejects_host_contract_mismatch():
    value = offline()
    value["variants"][1]["observedHostCompatibility"]["abi"] = "different"
    with pytest.raises(mod.EvidenceError, match="offline_host_compatibility_mismatch"):
        mod.verify_offline_install(value)


def test_offline_rejects_weak_pip_command():
    value = offline()
    value["variants"][0]["installCommand"] = "pip install -r lock.txt"
    with pytest.raises(mod.EvidenceError, match="offline_install_command_not_strict"):
        mod.verify_offline_install(value)


def test_offline_rejects_cuda_cpu_fallback():
    value = offline()
    value["variants"][1]["actualDevice"] = "cpu"
    with pytest.raises(mod.EvidenceError, match="offline_cuda_device_mismatch"):
        mod.verify_offline_install(value)


def test_offline_complete_package_passes():
    mod.verify_offline_install(offline())
