from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "evaluate_recovery_performance.py"
SPEC = importlib.util.spec_from_file_location("phase1_perf", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def observation():
    return {
        "sourceCommit": "a" * 40,
        "targetVerifiedManifestSha256": "c" * 64,
        "acceptanceProfileSha256": "b" * 64,
        "maviBuild": "build-a",
        "runtimeVariant": "linux-x86_64-cuda",
        "actualDevice": "cuda:0",
        "noTrackStateLeakAcrossVideos": True,
        "boundedCudaOomRecovery": True,
        "noSemanticFallback": True,
        "watchdogContainmentPassed": True,
        "replacementRuntimeUsedAfterRecovery": True,
        "noCudaToCpuFallback": True,
        "memorySamplesBytes": [100, 110, 105],
        "processingFps": 12.0,
        "p95EndToEndLatencyMs": 900.0,
    }


def test_requires_approved_profile_thresholds():
    with pytest.raises(mod.PerformanceEvidenceError, match="performance_thresholds_not_approved"):
        mod.evaluate({"performanceThresholds": None}, observation())


def test_evaluates_all_thresholds():
    profile = {"performanceThresholds": {
        "minimumProcessingFps": 10.0,
        "maximumP95LatencyMs": 1000.0,
        "maximumSoakGrowthBytes": 20,
    }}
    result = mod.evaluate(profile, observation())
    assert result["result"]["passed"] is True


def test_recovery_contract_is_mandatory():
    profile = {"performanceThresholds": {
        "minimumProcessingFps": 10.0,
        "maximumP95LatencyMs": 1000.0,
        "maximumSoakGrowthBytes": 20,
    }}
    value = observation()
    value["noCudaToCpuFallback"] = False
    with pytest.raises(mod.PerformanceEvidenceError, match="performance_recovery_contract_failed"):
        mod.evaluate(profile, value)
