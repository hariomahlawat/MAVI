#!/usr/bin/env python3
"""Evaluate profile-specific recovery/performance evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PHASE1_ROOT = Path(__file__).resolve().parent
if str(PHASE1_ROOT) not in sys.path:
    sys.path.insert(0, str(PHASE1_ROOT))

import deployment_profiles  # noqa: E402
from policy_identity import (  # noqa: E402
    PolicyIdentityError,
    canonical_acceptance_profile,
)


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


def evaluate(
    profile: dict[str, Any],
    observation: dict[str, Any],
    deployment_profile: deployment_profiles.DeploymentProfile,
    deployment_profile_policy_sha256: str,
) -> dict[str, Any]:
    thresholds = profile.get("performanceThresholds")
    if not isinstance(thresholds, dict):
        raise PerformanceEvidenceError(
            "performance_thresholds_not_approved"
        )
    required_thresholds = {
        "minimumProcessingFps",
        "maximumP95LatencyMs",
        "maximumSoakGrowthBytes",
    }
    if set(thresholds) != required_thresholds:
        raise PerformanceEvidenceError(
            "performance_thresholds_invalid"
        )
    for key in required_thresholds:
        value = thresholds[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or value < 0
        ):
            raise PerformanceEvidenceError(
                "performance_thresholds_invalid"
            )

    common_true = (
        "noTrackStateLeakAcrossVideos",
        "noSemanticFallback",
        "watchdogContainmentPassed",
        "replacementRuntimeUsedAfterRecovery",
    )
    for key in common_true:
        if observation.get(key) is not True:
            raise PerformanceEvidenceError(
                "performance_recovery_contract_failed:" + key
            )

    if deployment_profile.requires_cuda:
        for key in (
            "boundedCudaOomRecovery",
            "noCudaToCpuFallback",
        ):
            if observation.get(key) is not True:
                raise PerformanceEvidenceError(
                    "performance_recovery_contract_failed:" + key
                )

    samples = observation.get("memorySamplesBytes")
    if (
        not isinstance(samples, list)
        or len(samples) < 3
        or any(
            isinstance(x, bool)
            or not isinstance(x, int)
            or x < 0
            for x in samples
        )
    ):
        raise PerformanceEvidenceError(
            "performance_memory_samples_invalid"
        )

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
        raise PerformanceEvidenceError(
            "performance_metrics_invalid"
        )

    growth = max(samples) - min(samples)
    failures: list[str] = []
    if processing_fps < thresholds["minimumProcessingFps"]:
        failures.append("processing_fps")
    if p95_latency_ms > thresholds["maximumP95LatencyMs"]:
        failures.append("p95_latency")
    if growth > thresholds["maximumSoakGrowthBytes"]:
        failures.append("memory_growth")

    return {
        "schemaVersion":
            "mavi-profile-recovery-performance-evidence-v2",
        "sourceCommit": observation.get("sourceCommit"),
        "targetVerifiedManifestSha256": observation.get(
            "targetVerifiedManifestSha256"
        ),
        "acceptanceProfileSha256": observation.get(
            "acceptanceProfileSha256"
        ),
        "maviBuild": observation.get("maviBuild"),
        "deploymentProfile": deployment_profile.profile_id,
        "deploymentProfilePolicySha256":
            deployment_profile_policy_sha256,
        "runtimeVariant": deployment_profile.runtime_variant,
        "actualDevice": observation.get("actualDevice"),
        "noTrackStateLeakAcrossVideos": True,
        "noSemanticFallback": True,
        "watchdogContainmentPassed": True,
        "replacementRuntimeUsedAfterRecovery": True,
        "boundedCudaOomRecovery": (
            True if deployment_profile.requires_cuda else None
        ),
        "noCudaToCpuFallback": (
            True if deployment_profile.requires_cuda else None
        ),
        "memorySamplesBytes": samples,
        "memoryGrowthBytes": growth,
        "processingFps": processing_fps,
        "p95EndToEndLatencyMs": p95_latency_ms,
        "thresholds": thresholds,
        "result": {
            "passed": not failures,
            "failureCodes": failures,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--acceptance-profile",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--deployment-profile-policy",
        type=Path,
        default=deployment_profiles.CANONICAL_DEPLOYMENT_PROFILES,
    )
    parser.add_argument(
        "--deployment-profile",
        choices=("P1", "P2", "P3"),
        required=True,
    )
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.output.exists():
            raise PerformanceEvidenceError(
                "performance_output_exists"
            )
        canonical_profile, acceptance_profile_sha = (
            canonical_acceptance_profile(
                args.acceptance_profile
            )
        )
        profile = load(canonical_profile)
        selected_profile, deployment_policy_sha = (
            deployment_profiles.select_profile(
                args.deployment_profile,
                args.deployment_profile_policy,
            )
        )
        observation = load(args.observation)
        if observation.get("sourceCommit") != args.source_commit:
            raise PerformanceEvidenceError(
                "performance_source_commit_mismatch"
            )
        if (
            observation.get("acceptanceProfileSha256")
            != acceptance_profile_sha
        ):
            raise PerformanceEvidenceError(
                "performance_profile_hash_mismatch"
            )
        build = observation.get("maviBuild")
        if not isinstance(build, str) or not build:
            raise PerformanceEvidenceError(
                "performance_mavi_build_invalid"
            )
        target = observation.get(
            "targetVerifiedManifestSha256"
        )
        if (
            not isinstance(target, str)
            or len(target) != 64
            or any(
                ch not in "0123456789abcdef"
                for ch in target
            )
        ):
            raise PerformanceEvidenceError(
                "performance_target_manifest_invalid"
            )
        if (
            observation.get("runtimeVariant")
            != selected_profile.runtime_variant
        ):
            raise PerformanceEvidenceError(
                "performance_runtime_variant_invalid"
            )
        actual_device = observation.get("actualDevice")
        if not isinstance(actual_device, str):
            raise PerformanceEvidenceError(
                "performance_device_invalid"
            )
        if selected_profile.requires_cuda:
            if not actual_device.startswith("cuda:"):
                raise PerformanceEvidenceError(
                    "performance_cuda_device_required"
                )
        elif actual_device != "cpu":
            raise PerformanceEvidenceError(
                "performance_cpu_device_required"
            )

        result = evaluate(
            profile,
            observation,
            selected_profile,
            deployment_policy_sha,
        )
        args.output.write_text(
            json.dumps(result, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (
        OSError,
        json.JSONDecodeError,
        PerformanceEvidenceError,
        PolicyIdentityError,
        deployment_profiles.DeploymentProfileError,
    ) as exc:
        code = getattr(exc, "code", str(exc))
        print(
            json.dumps(
                {"ok": False, "code": code},
                sort_keys=True,
            )
        )
        return 2

    print(
        json.dumps(
            {
                "ok": result["result"]["passed"],
                "sha256": sha256_file(args.output),
            },
            sort_keys=True,
        )
    )
    return 0 if result["result"]["passed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
