#!/usr/bin/env python3
"""Execute the mandatory production failure/reprocess scenario for one deployment profile."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

PHASE1_ROOT = Path(__file__).resolve().parent
E2E_PATH = PHASE1_ROOT / "phase1_e2e_check.py"
SPEC = importlib.util.spec_from_file_location("mavi_phase1_failure_e2e", E2E_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("failure_reprocess_e2e_import_failed")
e2e = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = e2e
SPEC.loader.exec_module(e2e)

import qualify_offline_variant as offline_variant  # noqa: E402
import deployment_profiles  # noqa: E402
from production_acceptance_context import (  # noqa: E402
    AcceptanceContextError,
    load_context as load_acceptance_context,
)
from environment_fingerprint import (  # noqa: E402
    EnvironmentFingerprintError,
    fingerprint as environment_fingerprint,
)


class FailureReprocessError(ValueError):
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
        raise FailureReprocessError(code) from exc
    if not isinstance(value, dict):
        raise FailureReprocessError(code)
    return value


def read_source(
    client: Any,
    video_id: str,
) -> tuple[str, str]:
    status, headers, payload = client.request(
        "GET",
        f"/api/videos/{video_id}/content",
    )
    if status != 200:
        raise FailureReprocessError("failure_reprocess_source_read_failed")
    return e2e.sha256_bytes(payload), e2e._etag_sha256(headers)


def worker_environment(
    args: argparse.Namespace,
    bundle_dir: Path,
) -> dict[str, str]:
    release_models = bundle_dir / "release" / "models"
    runtime_root = (
        bundle_dir
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
        "MAVI_WORKER_ID": "task17-production-reprocess-worker",
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
                bundle_dir
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
        "MAVI_DEPLOYMENT_PROFILE": args.selected_profile.profile_id,
        "MAVI_DEPLOYMENT_PROFILE_POLICY_PATH": str(
            (
                bundle_dir
                / "release"
                / "config"
                / "acceptance"
                / "phase1-deployment-profiles-v1.json"
            ).resolve()
        ),
        "MAVI_BUILD_ID": args.mavi_build,
        "MAVI_COMMIT_SHA": args.source_commit,
        "MAVI_DEVICE_POLICY": (
            "cuda" if args.selected_profile.requires_cuda else "cpu"
        ),
        "MAVI_DEVICE_INDEX": str(args.device_index),
        "MAVI_PRODUCTION_MODE": "true",
        "MAVI_POLL_INTERVAL_SECONDS": "0.25",
    }


def validate_production_inputs(
    args: argparse.Namespace,
) -> tuple[
    dict[str, Any],
    str,
    dict[str, Any],
    deployment_profiles.DeploymentProfile,
    str,
]:
    selected_profile, deployment_policy_sha = deployment_profiles.select_profile(
        args.deployment_profile,
        args.deployment_profile_policy,
    )
    variant = load_json(
        args.variant_evidence,
        "failure_reprocess_variant_evidence_invalid",
    )
    bundle, bundle_sha = e2e._validate_bundle(
        args.bundle_dir,
        args.source_commit,
    )
    if bundle.get("releaseStatus") != "production":
        raise FailureReprocessError(
            "failure_reprocess_production_bundle_required"
        )
    environment_identity = environment_fingerprint(args.worker_python)
    if (
        variant.get("schemaVersion")
        != "mavi-offline-variant-evidence-v1"
        or variant.get("variant") != selected_profile.runtime_variant
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
        raise FailureReprocessError(
            "failure_reprocess_variant_binding_failed"
        )

    model_manifest_path = (
        args.bundle_dir
        / "release"
        / "models"
        / "manifests"
        / "rtmdet-m-coco-phase1-v1.json"
    )
    if sha256_file(model_manifest_path) != args.target_verified_manifest_sha256:
        raise FailureReprocessError(
            "failure_reprocess_model_manifest_mismatch"
        )
    return (
        bundle,
        bundle_sha,
        environment_identity,
        selected_profile,
        deployment_policy_sha,
    )


def execute(args: argparse.Namespace) -> dict[str, Any]:
    context, context_sha = load_acceptance_context(
        args.acceptance_context,
        schema_path=PHASE1_ROOT / "production-acceptance-context.schema.json",
        expected_source_commit=args.source_commit,
        expected_mavi_build=args.mavi_build,
    )
    scenario_started = datetime.now(timezone.utc)
    (
        bundle,
        bundle_sha,
        environment_identity,
        selected_profile,
        deployment_policy_sha,
    ) = validate_production_inputs(args)
    args.selected_profile = selected_profile
    network_isolation = offline_variant.assert_outbound_internet_unavailable()
    client = e2e.ApiClient(args.base_url)

    health = client.json("GET", "/api/health")
    if (
        not isinstance(health, dict)
        or health.get("status") != "ok"
        or health.get("build") != args.mavi_build
        or health.get("commit") != args.source_commit
    ):
        raise FailureReprocessError(
            "failure_reprocess_application_identity_mismatch"
        )
    try:
        operational_api = e2e._validate_operational_topology(
            client,
            source_commit=args.source_commit,
            expected_mavi_build=args.mavi_build,
            expected_host_identity_sha256=args.expected_operational_host_identity_sha256,
        )
    except e2e.AcceptanceError as exc:
        raise FailureReprocessError(
            "failure_reprocess_operational_host_mismatch"
        ) from exc

    camera = e2e.resolve_camera(
        client,
        code=args.camera_code,
        name=args.camera_name,
        time_zone_id=args.camera_timezone,
    )
    video = e2e.import_or_resolve_video(
        client,
        camera=camera,
        recording_local=args.recording_local,
        video_path=args.video,
    )
    local_sha = sha256_file(args.video)

    first_queue = client.json(
        "POST",
        f"/api/videos/{video['id']}/process",
        expected=(202,),
    )
    if not isinstance(first_queue, dict):
        raise FailureReprocessError(
            "failure_reprocess_first_queue_invalid"
        )
    first_run_id = first_queue.get("processingRunId")
    if not isinstance(first_run_id, str):
        raise FailureReprocessError(
            "failure_reprocess_first_queue_invalid"
        )

    lease = client.json(
        "POST",
        "/api/vision/jobs/lease",
        value={
            "schemaVersion": "2.0",
            "workerId": "task17-controlled-fault-injector",
        },
    )
    if (
        not isinstance(lease, dict)
        or lease.get("processingRunId") != first_run_id
        or not isinstance(lease.get("jobId"), str)
        or not isinstance(lease.get("leaseToken"), str)
    ):
        raise FailureReprocessError(
            "failure_reprocess_fault_lease_not_authoritative"
        )

    client.json(
        "POST",
        f"/api/vision/jobs/{lease['jobId']}/fail",
        value={
            "schemaVersion": "2.0",
            "workerId": lease["workerId"],
            "leaseToken": lease["leaseToken"],
            "failureCode": "task17_controlled_failure",
            "failureMessage": "controlled Task-17 production acceptance failure",
        },
    )

    status = client.json(
        "GET",
        f"/api/videos/{video['id']}/processing",
    )
    latest = status.get("latestRun") if isinstance(status, dict) else None
    if (
        not isinstance(latest, dict)
        or latest.get("processingRunId") != first_run_id
        or latest.get("status") != "Failed"
    ):
        raise FailureReprocessError(
            "failure_reprocess_first_run_not_failed"
        )

    failure_sha, failure_etag = read_source(client, video["id"])
    if len({local_sha, failure_sha, failure_etag}) != 1:
        raise FailureReprocessError(
            "failure_reprocess_source_changed_after_failure"
        )

    second_queue = client.json(
        "POST",
        f"/api/videos/{video['id']}/process",
        expected=(202,),
    )
    second_run_id = (
        second_queue.get("processingRunId")
        if isinstance(second_queue, dict)
        else None
    )
    if (
        not isinstance(second_run_id, str)
        or second_run_id == first_run_id
    ):
        raise FailureReprocessError(
            "failure_reprocess_second_queue_invalid"
        )

    worker_log = args.output.with_suffix(
        args.output.suffix + ".worker.log"
    )
    if worker_log.exists():
        raise FailureReprocessError(
            "failure_reprocess_worker_log_exists"
        )
    worker_env = worker_environment(args, args.bundle_dir)
    worker_command = [
        str(args.worker_python),
        "-m",
        "mavi_vision.worker.main",
    ]

    with worker_log.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as log_stream:
        worker = subprocess.Popen(
            worker_command,
            env=worker_env,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            time.sleep(args.worker_startup_seconds)
            if worker.poll() is not None:
                raise FailureReprocessError(
                    "failure_reprocess_worker_startup_failed"
                )
            e2e._poll_completed_run(
                client,
                video["id"],
                second_run_id,
                args.processing_timeout_seconds,
            )
        finally:
            if worker.poll() is None:
                worker.terminate()
                try:
                    worker.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=10)

    attestation = client.json(
        "GET",
        f"/api/processing/runs/{second_run_id}/attestation",
    )
    if not isinstance(attestation, dict):
        raise FailureReprocessError(
            "failure_reprocess_attestation_invalid"
        )
    if (
        attestation.get("verificationStatus") != "verified"
        or attestation.get("runtimeVariant") != selected_profile.runtime_variant
        or attestation.get("maviBuild") != args.mavi_build
        or attestation.get("maviCommit") != args.source_commit
        or attestation.get("modelManifestSha256")
        != args.target_verified_manifest_sha256
        or attestation.get("platformLockSha256")
        != bundle.get("lockSha256")
        or not isinstance(attestation.get("actualDevice"), str)
        or not attestation["actualDevice"].startswith("cuda:")
    ):
        raise FailureReprocessError(
            "failure_reprocess_attestation_mismatch"
        )

    actual_device = attestation.get("actualDevice")
    if not isinstance(actual_device, str):
        raise FailureReprocessError("failure_reprocess_device_missing")
    if selected_profile.requires_cuda:
        if not actual_device.startswith("cuda:"):
            raise FailureReprocessError("failure_reprocess_cuda_required")
    elif actual_device.startswith("cuda:"):
        raise FailureReprocessError("failure_reprocess_cpu_profile_used_cuda")

    tracks = e2e._all_tracks(
        client,
        video["id"],
        second_run_id,
    )
    if not tracks:
        raise FailureReprocessError(
            "failure_reprocess_no_tracks_after_reprocess"
        )

    reprocess_sha, reprocess_etag = read_source(client, video["id"])
    if len(
        {
            local_sha,
            failure_sha,
            failure_etag,
            reprocess_sha,
            reprocess_etag,
        }
    ) != 1:
        raise FailureReprocessError(
            "failure_reprocess_source_changed_after_reprocess"
        )

    scenario_completed = datetime.now(timezone.utc)
    return {
        "schemaVersion": "mavi-production-failure-reprocess-evidence-v2",
        "acceptanceExecutionId": context["acceptanceExecutionId"],
        "acceptanceContextSha256": context_sha,
        "scenarioStartedAtUtc": scenario_started.isoformat().replace("+00:00", "Z"),
        "scenarioCompletedAtUtc": scenario_completed.isoformat().replace("+00:00", "Z"),
        "sourceCommit": args.source_commit,
        "maviBuild": args.mavi_build,
        "operationalHostIdentitySha256": operational_api["hostIdentitySha256"],
        "targetVerifiedManifestSha256": args.target_verified_manifest_sha256,
        "deploymentProfile": selected_profile.profile_id,
        "deploymentProfilePolicySha256": deployment_policy_sha,
        "runtimeVariant": selected_profile.runtime_variant,
        "productionBundleManifestSha256": bundle_sha,
        "productionReleaseLockSha256": bundle["lockSha256"],
        "variantEvidenceSha256": sha256_file(args.variant_evidence),
        "workerPythonSha256": sha256_file(args.worker_python),
        "workerEnvironmentSha256": environment_identity["workerEnvironmentSha256"],
        "workerVenvRootSha256": environment_identity["workerVenvRootSha256"],
        "workerResolvedPythonSha256": environment_identity["workerResolvedPythonSha256"],
        "videoAssetId": video["id"],
        "firstProcessingRunId": first_run_id,
        "firstVisionJobId": lease["jobId"],
        "failureCode": "task17_controlled_failure",
        "reprocessProcessingRunId": second_run_id,
        "reprocessAttestation": {
            "verificationStatus": attestation["verificationStatus"],
            "runtimeVariant": attestation["runtimeVariant"],
            "actualDevice": attestation["actualDevice"],
            "maviBuild": attestation["maviBuild"],
            "maviCommit": attestation["maviCommit"],
            "modelManifestSha256": attestation["modelManifestSha256"],
            "platformLockSha256": attestation["platformLockSha256"],
        },
        "sourceMedia": {
            "localSha256": local_sha,
            "afterFailureSha256": failure_sha,
            "afterFailureEtagSha256": failure_etag,
            "afterReprocessSha256": reprocess_sha,
            "afterReprocessEtagSha256": reprocess_etag,
        },
        "trackCount": len(tracks),
        "workerLogSha256": sha256_file(worker_log),
        "networkIsolation": network_isolation,
        "result": {"passed": True, "failureCodes": []},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acceptance-context", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--camera-code", required=True)
    parser.add_argument("--camera-name", required=True)
    parser.add_argument("--camera-timezone", required=True)
    parser.add_argument("--recording-local", required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--mavi-build", required=True)
    parser.add_argument("--expected-operational-host-identity-sha256", required=True)
    parser.add_argument(
        "--target-verified-manifest-sha256",
        required=True,
    )
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--worker-python", type=Path, required=True)
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
    parser.add_argument(
        "--variant-evidence",
        type=Path,
        required=True,
    )
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
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.output.exists():
            raise FailureReprocessError(
                "failure_reprocess_output_exists"
            )
        if not args.video.is_file() or not args.worker_python.is_file():
            raise FailureReprocessError(
                "failure_reprocess_input_missing"
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
        FailureReprocessError,
        EnvironmentFingerprintError,
        AcceptanceContextError,
        e2e.AcceptanceError,
        deployment_profiles.DeploymentProfileError,
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
