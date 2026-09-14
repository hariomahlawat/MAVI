#!/usr/bin/env python3
"""Execute the mandatory Task-17 production failure/reprocess scenario."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
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
        "MAVI_BUILD_ID": args.mavi_build,
        "MAVI_COMMIT_SHA": args.source_commit,
        "MAVI_DEVICE_POLICY": "cuda",
        "MAVI_DEVICE_INDEX": str(args.device_index),
        "MAVI_PRODUCTION_MODE": "true",
        "MAVI_POLL_INTERVAL_SECONDS": "0.25",
    }


def validate_production_inputs(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], str]:
    variant = load_json(
        args.linux_cuda_variant_evidence,
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
    return bundle, bundle_sha


def execute(args: argparse.Namespace) -> dict[str, Any]:
    bundle, bundle_sha = validate_production_inputs(args)
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
        or attestation.get("runtimeVariant") != "linux-x86_64-cuda"
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

    return {
        "schemaVersion": "mavi-production-failure-reprocess-evidence-v1",
        "sourceCommit": args.source_commit,
        "maviBuild": args.mavi_build,
        "targetVerifiedManifestSha256": args.target_verified_manifest_sha256,
        "productionBundleManifestSha256": bundle_sha,
        "productionReleaseLockSha256": bundle["lockSha256"],
        "linuxCudaVariantEvidenceSha256": sha256_file(
            args.linux_cuda_variant_evidence
        ),
        "workerPythonSha256": sha256_file(args.worker_python),
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
        "result": {"passed": True, "failureCodes": []},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--camera-code", required=True)
    parser.add_argument("--camera-name", required=True)
    parser.add_argument("--camera-timezone", required=True)
    parser.add_argument("--recording-local", required=True)
    parser.add_argument("--video", type=Path, required=True)
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
