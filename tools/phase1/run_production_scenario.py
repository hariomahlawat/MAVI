#!/usr/bin/env python3
"""Run an independent final production E2E scenario on the exact Linux-CUDA worker."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PHASE1_ROOT = Path(__file__).resolve().parent
E2E_PATH = PHASE1_ROOT / "phase1_e2e_check.py"
SPEC = importlib.util.spec_from_file_location("mavi_production_scenario_e2e", E2E_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("production_scenario_e2e_import_failed")
e2e = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = e2e
SPEC.loader.exec_module(e2e)

import qualify_offline_variant as offline_variant  # noqa: E402
from environment_fingerprint import (  # noqa: E402
    EnvironmentFingerprintError,
    fingerprint as environment_fingerprint,
)


class ProductionScenarioError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionScenarioError(code) from exc
    if not isinstance(value, dict):
        raise ProductionScenarioError(code)
    return value


def validate_inputs(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    variant = load_json(
        args.linux_cuda_variant_evidence,
        "production_scenario_variant_invalid",
    )
    bundle, bundle_sha = e2e._validate_bundle(
        args.bundle_dir,
        args.source_commit,
    )
    if bundle.get("releaseStatus") != "production":
        raise ProductionScenarioError(
            "production_scenario_production_bundle_required"
        )
    environment_identity = environment_fingerprint(args.worker_python)
    if (
        variant.get("schemaVersion")
        != "mavi-offline-variant-evidence-v1"
        or variant.get("variant") != "linux-x86_64-cuda"
        or variant.get("bundleMode") != "production"
        or variant.get("sourceCommit") != args.source_commit
        or variant.get("maviBuild") != args.mavi_build
        or variant.get("targetVerifiedManifestSha256")
        != args.target_verified_manifest_sha256
        or variant.get("bundleManifestSha256") != bundle_sha
        or variant.get("releaseLockSha256") != bundle.get("lockSha256")
        or variant.get("workerPythonSha256")
        != sha256_file(args.worker_python)
        or variant.get("workerEnvironmentSha256")
        != environment_identity["workerEnvironmentSha256"]
        or variant.get("workerVenvRootSha256")
        != environment_identity["workerVenvRootSha256"]
        or variant.get("workerResolvedPythonSha256")
        != environment_identity["workerResolvedPythonSha256"]
        or variant.get("result") != "passed"
    ):
        raise ProductionScenarioError(
            "production_scenario_variant_binding_failed"
        )
    if args.mode == "formal":
        if args.corpus_manifest is None or args.ground_truth is None:
            raise ProductionScenarioError(
                "production_scenario_ground_truth_required"
            )
    elif args.corpus_manifest is not None or args.ground_truth is not None:
        raise ProductionScenarioError(
            "production_scenario_ground_truth_forbidden"
        )
    return bundle, bundle_sha, variant, environment_identity


def worker_environment(
    args: argparse.Namespace,
) -> dict[str, str]:
    release_models = args.bundle_dir / "release" / "models"
    runtime_root = (
        args.bundle_dir
        / "release"
        / "runtime"
        / "mmdetection-phase1-v1"
    )
    return {
        **os.environ,
        "PIP_NO_INDEX": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "MAVI_API_BASE_URL": args.base_url,
        "MAVI_WORKER_ID": f"task17-final-{args.mode}",
        "MAVI_MEDIA_ROOT": str(args.media_root.resolve()),
        "MAVI_MODEL_ROOT": str(release_models.resolve()),
        "MAVI_MODEL_MANIFEST_PATH": str(
            (
                release_models
                / "manifests"
                / "rtmdet-m-coco-phase1-v1.json"
            ).resolve()
        ),
        "MAVI_PIPELINE_PROFILE_PATH": str(
            (
                args.bundle_dir
                / "release"
                / "config"
                / "pipelines"
                / "phase1-detection-tracking-v1.json"
            ).resolve()
        ),
        "MAVI_RUNTIME_PROFILE_PATH": str(
            (runtime_root / "runtime.json").resolve()
        ),
        "MAVI_QUALIFICATION_RECORD_PATH": str(
            (
                release_models
                / "qualifications"
                / "rtmdet-m-coco-phase1-v1.json"
            ).resolve()
        ),
        "MAVI_BUILD_ID": args.mavi_build,
        "MAVI_COMMIT_SHA": args.source_commit,
        "MAVI_DEVICE_POLICY": "cuda",
        "MAVI_DEVICE_INDEX": str(args.device_index),
        "MAVI_PRODUCTION_MODE": "true",
        "MAVI_POLL_INTERVAL_SECONDS": "0.25",
    }


def execute(args: argparse.Namespace) -> dict[str, Any]:
    bundle, bundle_sha, variant, environment_identity = validate_inputs(args)
    network_isolation = offline_variant.assert_outbound_internet_unavailable()

    health = e2e.ApiClient(args.base_url).json("GET", "/api/health")
    if (
        not isinstance(health, dict)
        or health.get("status") != "ok"
        or health.get("build") != args.mavi_build
        or health.get("commit") != args.source_commit
    ):
        raise ProductionScenarioError(
            "production_scenario_application_identity_mismatch"
        )

    worker_log = args.output.with_suffix(
        args.output.suffix + ".worker.log"
    )
    if worker_log.exists() or args.e2e_output.exists():
        raise ProductionScenarioError(
            "production_scenario_output_exists"
        )

    command = [
        str(args.worker_python),
        str(E2E_PATH),
        "--mode",
        args.mode,
        "--base-url",
        args.base_url,
        "--camera-code",
        args.camera_code,
        "--camera-name",
        args.camera_name,
        "--camera-timezone",
        args.camera_timezone,
        "--recording-local",
        args.recording_local,
        "--video",
        str(args.video),
        "--processing-timeout-seconds",
        str(args.processing_timeout_seconds),
        "--environment-label",
        args.environment_label,
        "--source-commit",
        args.source_commit,
        "--expected-mavi-build",
        args.mavi_build,
        "--target-verified-manifest-sha256",
        args.target_verified_manifest_sha256,
        "--model-root",
        str(args.bundle_dir / "release" / "models"),
        "--model-manifest",
        str(
            args.bundle_dir
            / "release"
            / "models"
            / "manifests"
            / "rtmdet-m-coco-phase1-v1.json"
        ),
        "--pipeline-profile",
        str(
            args.bundle_dir
            / "release"
            / "config"
            / "pipelines"
            / "phase1-detection-tracking-v1.json"
        ),
        "--runtime-profile",
        str(
            args.bundle_dir
            / "release"
            / "runtime"
            / "mmdetection-phase1-v1"
            / "runtime.json"
        ),
        "--qualification-record",
        str(
            args.bundle_dir
            / "release"
            / "models"
            / "qualifications"
            / "rtmdet-m-coco-phase1-v1.json"
        ),
        "--bundle-dir",
        str(args.bundle_dir),
        "--acceptance-profile",
        str(args.acceptance_profile),
        "--output",
        str(args.e2e_output),
    ]
    if args.mode == "formal":
        command.extend([
            "--corpus-manifest",
            str(args.corpus_manifest),
            "--ground-truth",
            str(args.ground_truth),
        ])

    with worker_log.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as stream:
        worker = subprocess.Popen(
            [
                str(args.worker_python),
                "-m",
                "mavi_vision.worker.main",
            ],
            env=worker_environment(args),
            stdout=stream,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            time.sleep(args.worker_startup_seconds)
            if worker.poll() is not None:
                raise ProductionScenarioError(
                    "production_scenario_worker_startup_failed"
                )
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "PIP_NO_INDEX": "1",
                    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                    "HF_HUB_OFFLINE": "1",
                    "TRANSFORMERS_OFFLINE": "1",
                },
            )
            if completed.returncode != 0:
                raise ProductionScenarioError(
                    "production_scenario_e2e_failed"
                )
        finally:
            if worker.poll() is None:
                worker.terminate()
                try:
                    worker.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=10)

    evidence = load_json(
        args.e2e_output,
        "production_scenario_e2e_invalid",
    )
    attestation = evidence.get("attestation", {})
    if (
        evidence.get("mode") != args.mode
        or evidence.get("sourceCommit") != args.source_commit
        or evidence.get("targetVerifiedManifestSha256")
        != args.target_verified_manifest_sha256
        or attestation.get("verificationStatus") != "verified"
        or attestation.get("runtimeVariant") != "linux-x86_64-cuda"
        or attestation.get("maviBuild") != args.mavi_build
        or attestation.get("maviCommit") != args.source_commit
        or attestation.get("productionBundleManifestSha256")
        != bundle_sha
        or attestation.get("platformLockSha256")
        != bundle.get("lockSha256")
        or evidence.get("result", {}).get("passed") is not True
    ):
        raise ProductionScenarioError(
            "production_scenario_e2e_binding_failed"
        )

    if args.mode == "empty-scene-diagnostic":
        if (
            evidence.get("tracks", {}).get("total") != 0
            or evidence.get("tracks", {}).get("detailsResolved") != 0
            or evidence.get("evidenceReads", {}).get("passed") != 0
        ):
            raise ProductionScenarioError(
                "production_scenario_empty_scene_false_positive"
            )

    return {
        "schemaVersion": "mavi-production-scenario-evidence-v1",
        "mode": args.mode,
        "sourceCommit": args.source_commit,
        "maviBuild": args.mavi_build,
        "targetVerifiedManifestSha256": args.target_verified_manifest_sha256,
        "linuxCudaVariantEvidenceSha256": sha256_file(
            args.linux_cuda_variant_evidence
        ),
        "productionBundleManifestSha256": bundle_sha,
        "productionReleaseLockSha256": bundle["lockSha256"],
        "workerPythonSha256": sha256_file(args.worker_python),
        "workerEnvironmentSha256": environment_identity["workerEnvironmentSha256"],
        "workerVenvRootSha256": environment_identity["workerVenvRootSha256"],
        "workerResolvedPythonSha256": environment_identity["workerResolvedPythonSha256"],
        "e2eEvidenceSha256": sha256_file(args.e2e_output),
        "workerLogSha256": sha256_file(worker_log),
        "networkIsolation": network_isolation,
        "result": {"passed": True, "failureCodes": []},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("formal", "empty-scene-diagnostic"),
        required=True,
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--camera-code", required=True)
    parser.add_argument("--camera-name", required=True)
    parser.add_argument("--camera-timezone", required=True)
    parser.add_argument("--recording-local", required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--environment-label", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--mavi-build", required=True)
    parser.add_argument(
        "--target-verified-manifest-sha256",
        required=True,
    )
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--worker-python", type=Path, required=True)
    parser.add_argument(
        "--linux-cuda-variant-evidence",
        type=Path,
        required=True,
    )
    parser.add_argument("--acceptance-profile", type=Path, required=True)
    parser.add_argument("--corpus-manifest", type=Path)
    parser.add_argument("--ground-truth", type=Path)
    parser.add_argument("--device-index", type=int, default=0)
    parser.add_argument(
        "--processing-timeout-seconds",
        type=float,
        default=900.0,
    )
    parser.add_argument(
        "--worker-startup-seconds",
        type=float,
        default=3.0,
    )
    parser.add_argument("--e2e-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        if (
            args.output.exists()
            or not args.video.is_file()
            or not args.worker_python.is_file()
        ):
            raise ProductionScenarioError(
                "production_scenario_input_invalid"
            )
        value = execute(args)
        args.output.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (
        OSError,
        KeyError,
        TypeError,
        ProductionScenarioError,
        EnvironmentFingerprintError,
        e2e.AcceptanceError,
    ) as exc:
        code = getattr(exc, "code", str(exc))
        print(json.dumps({"ok": False, "code": code}, sort_keys=True))
        return 2

    print(
        json.dumps(
            {"ok": True, "sha256": sha256_file(args.output)},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
