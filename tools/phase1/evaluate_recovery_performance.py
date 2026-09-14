#!/usr/bin/env python3
"""Evaluate Task-17 Linux NVIDIA recovery/performance evidence against reviewed thresholds."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


class PerformanceEvidenceError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PerformanceEvidenceError("performance_json_invalid")
    return value


def evaluate(profile: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    thresholds = profile.get("performanceThresholds")
    if not isinstance(thresholds, dict):
        raise PerformanceEvidenceError("performance_thresholds_not_approved")
    required = {"minimumProcessingFps", "maximumP95LatencyMs", "maximumSoakGrowthBytes"}
    if set(thresholds) != required:
        raise PerformanceEvidenceError("performance_thresholds_invalid")

    for key in required:
        value = thresholds[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise PerformanceEvidenceError("performance_thresholds_invalid")

    required_true = (
        "noTrackStateLeakAcrossVideos",
        "boundedCudaOomRecovery",
        "noSemanticFallback",
        "watchdogContainmentPassed",
        "replacementRuntimeUsedAfterRecovery",
        "noCudaToCpuFallback",
    )
    for key in required_true:
        if observation.get(key) is not True:
            raise PerformanceEvidenceError("performance_recovery_contract_failed:" + key)

    samples = observation.get("memorySamplesBytes")
    if (
        not isinstance(samples, list)
        or len(samples) < 3
        or any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in samples)
    ):
        raise PerformanceEvidenceError("performance_memory_samples_invalid")

    processing_fps = observation.get("processingFps")
    p95_latency_ms = observation.get("p95EndToEndLatencyMs")
    if (
        isinstance(processing_fps, bool)
        or not isinstance(processing_fps, (int, float))
        or processing_fps <= 0
        or isinstance(p95_latency_ms, bool)
        or not isinstance(p95_latency_ms, (int, float))
        or p95_latency_ms < 0
    ):
        raise PerformanceEvidenceError("performance_metrics_invalid")

    growth = max(samples) - min(samples)
    failures: list[str] = []
    if processing_fps < thresholds["minimumProcessingFps"]:
        failures.append("processing_fps")
    if p95_latency_ms > thresholds["maximumP95LatencyMs"]:
        failures.append("p95_latency")
    if growth > thresholds["maximumSoakGrowthBytes"]:
        failures.append("memory_growth")

    return {
        "schemaVersion": "mavi-linux-nvidia-recovery-performance-evidence-v1",
        "sourceCommit": observation.get("sourceCommit"),
        "targetVerifiedManifestSha256": observation.get("targetVerifiedManifestSha256"),
        "acceptanceProfileSha256": observation.get("acceptanceProfileSha256"),
        "runtimeVariant": observation.get("runtimeVariant"),
        "actualDevice": observation.get("actualDevice"),
        "noTrackStateLeakAcrossVideos": True,
        "boundedCudaOomRecovery": True,
        "noSemanticFallback": True,
        "watchdogContainmentPassed": True,
        "replacementRuntimeUsedAfterRecovery": True,
        "noCudaToCpuFallback": True,
        "memorySamplesBytes": samples,
        "memoryGrowthBytes": growth,
        "processingFps": processing_fps,
        "p95EndToEndLatencyMs": p95_latency_ms,
        "thresholds": thresholds,
        "result": {"passed": not failures, "failureCodes": failures},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acceptance-profile", type=Path, required=True)
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.output.exists():
            raise PerformanceEvidenceError("performance_output_exists")
        profile = load(args.acceptance_profile)
        observation = load(args.observation)
        if observation.get("sourceCommit") != args.source_commit:
            raise PerformanceEvidenceError("performance_source_commit_mismatch")
        if observation.get("acceptanceProfileSha256") != sha256_file(args.acceptance_profile):
            raise PerformanceEvidenceError("performance_profile_hash_mismatch")
        target = observation.get("targetVerifiedManifestSha256")
        if (
            not isinstance(target, str)
            or len(target) != 64
            or any(ch not in "0123456789abcdef" for ch in target)
        ):
            raise PerformanceEvidenceError("performance_target_manifest_invalid")
        if observation.get("runtimeVariant") != "linux-x86_64-cuda":
            raise PerformanceEvidenceError("performance_runtime_variant_invalid")
        actual_device = observation.get("actualDevice")
        if not isinstance(actual_device, str) or not actual_device.startswith("cuda:"):
            raise PerformanceEvidenceError("performance_cuda_device_required")
        result = evaluate(profile, observation)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    except (OSError, json.JSONDecodeError, PerformanceEvidenceError) as exc:
        print(json.dumps({"ok": False, "code": str(exc)}, sort_keys=True))
        return 2

    print(json.dumps({"ok": result["result"]["passed"], "sha256": sha256_file(args.output)}, sort_keys=True))
    return 0 if result["result"]["passed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
