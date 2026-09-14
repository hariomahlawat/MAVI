#!/usr/bin/env python3
"""Task-17 public-API Phase-1 acceptance harness.

This tool deliberately treats MAVI APIs and immutable release artifacts as the
acceptance boundary. It does not query PostgreSQL or inspect MAVI storage roots.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[2]
VISION_ROOT = ROOT / "src" / "vision"
VISION_TOOLS = ROOT / "tools" / "vision"
for candidate in (VISION_ROOT, VISION_TOOLS):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from mavi_vision.runtime.manifest import ReleaseMetadataError, sha256_release_file  # noqa: E402
from mavi_vision.runtime.qualification import verify_release_selection  # noqa: E402
import build_offline_bundle  # noqa: E402

EVALUATOR_PATH = Path(__file__).with_name("evaluate_ground_truth.py")
EVAL_SPEC = importlib.util.spec_from_file_location("mavi_phase1_evaluator", EVALUATOR_PATH)
if EVAL_SPEC is None or EVAL_SPEC.loader is None:
    raise RuntimeError("task17_evaluator_import_failed")
evaluator = importlib.util.module_from_spec(EVAL_SPEC)
sys.modules[EVAL_SPEC.name] = evaluator
EVAL_SPEC.loader.exec_module(evaluator)


class AcceptanceError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcceptanceError("qualification_json_invalid") from exc
    if not isinstance(value, dict):
        raise AcceptanceError("qualification_json_root_invalid")
    return value


def _etag_sha256(headers: Any) -> str:
    raw = headers.get("ETag")
    if raw is None or raw.startswith("W/"):
        raise AcceptanceError("qualification_etag_missing_or_weak")
    value = raw.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise AcceptanceError("qualification_etag_invalid")
    return value


class ApiClient:
    def __init__(self, base_url: str, timeout_seconds: float = 30.0):
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any, bytes]:
        target = urljoin(self.base_url, path.lstrip("/"))
        request = Request(target, data=body, method=method, headers=headers or {})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return response.status, response.headers, response.read()
        except HTTPError as exc:
            return exc.code, exc.headers, exc.read()
        except (URLError, TimeoutError, OSError) as exc:
            raise AcceptanceError("qualification_api_unreachable") from exc

    def json(
        self,
        method: str,
        path: str,
        *,
        value: Any | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> dict[str, Any] | list[Any]:
        body = None
        headers: dict[str, str] = {}
        if value is not None:
            body = json.dumps(value, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        status, _, payload = self.request(method, path, body=body, headers=headers)
        try:
            decoded = json.loads(payload) if payload else None
        except json.JSONDecodeError as exc:
            raise AcceptanceError("qualification_api_json_invalid") from exc
        if status not in expected:
            code = decoded.get("code") if isinstance(decoded, dict) else None
            raise AcceptanceError(code or f"qualification_http_{status}")
        if not isinstance(decoded, (dict, list)):
            raise AcceptanceError("qualification_api_json_invalid")
        return decoded


def _recording_identity(local_text: str, time_zone_id: str) -> tuple[str, int]:
    try:
        zone = ZoneInfo(time_zone_id)
    except ZoneInfoNotFoundError as exc:
        raise AcceptanceError("qualification_camera_timezone_invalid") from exc
    try:
        naive = datetime.fromisoformat(local_text)
    except ValueError as exc:
        raise AcceptanceError("qualification_recording_local_invalid") from exc
    if naive.tzinfo is not None:
        raise AcceptanceError("qualification_recording_local_must_be_naive")
    first = naive.replace(tzinfo=zone, fold=0)
    second = naive.replace(tzinfo=zone, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise AcceptanceError("qualification_recording_time_ambiguous")
    roundtrip = first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
    if roundtrip != naive:
        raise AcceptanceError("qualification_recording_time_nonexistent")
    utc_value = first.astimezone(timezone.utc)
    offset_minutes = int(first.utcoffset().total_seconds() // 60)  # type: ignore[union-attr]
    return utc_value.isoformat().replace("+00:00", "Z"), offset_minutes


def _multipart_import(
    client: ApiClient,
    *,
    camera_id: str,
    recording_local: str,
    video_path: Path,
) -> tuple[int, dict[str, Any]]:
    boundary = "----mavi-task17-boundary-7d302e63"
    video = video_path.read_bytes()
    boundary_bytes = boundary.encode("ascii")
    if boundary_bytes in video:
        raise AcceptanceError("qualification_multipart_boundary_collision")

    parts: list[bytes] = []
    for name, value in (
        ("cameraId", camera_id),
        ("recordingStartLocal", recording_local),
    ):
        parts.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            str(value).encode(),
            b"\r\n",
        ])
    parts.extend([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{video_path.name}"\r\n'.encode(),
        b"Content-Type: video/mp4\r\n\r\n",
        video,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    status, _, payload = client.request(
        "POST",
        "/api/videos/import",
        body=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise AcceptanceError("qualification_import_response_invalid") from exc
    if not isinstance(value, dict):
        raise AcceptanceError("qualification_import_response_invalid")
    return status, value


def resolve_camera(
    client: ApiClient,
    *,
    code: str,
    name: str,
    time_zone_id: str,
) -> dict[str, Any]:
    status, _, payload = client.request(
        "POST",
        "/api/cameras/",
        body=json.dumps(
            {"code": code, "name": name, "timeZoneId": time_zone_id},
            separators=(",", ":"),
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    if status == 201:
        value = json.loads(payload)
    elif status == 409:
        problem = json.loads(payload)
        if problem.get("code") != "camera_code_duplicate":
            raise AcceptanceError(problem.get("code") or "qualification_camera_create_failed")
        cameras = client.json("GET", "/api/cameras/")
        if not isinstance(cameras, list):
            raise AcceptanceError("qualification_camera_list_invalid")
        matches = [item for item in cameras if item.get("code") == code]
        if len(matches) != 1:
            raise AcceptanceError("qualification_camera_duplicate_unresolved")
        value = matches[0]
    else:
        try:
            problem = json.loads(payload)
        except json.JSONDecodeError:
            problem = {}
        raise AcceptanceError(problem.get("code") or f"qualification_camera_http_{status}")

    if (
        value.get("code") != code
        or value.get("name") != name
        or value.get("timeZoneId") != time_zone_id
        or value.get("isActive") is not True
    ):
        raise AcceptanceError("qualification_camera_provenance_mismatch")
    return value


def import_or_resolve_video(
    client: ApiClient,
    *,
    camera: dict[str, Any],
    recording_local: str,
    video_path: Path,
) -> dict[str, Any]:
    expected_utc, expected_offset = _recording_identity(recording_local, camera["timeZoneId"])
    status, value = _multipart_import(
        client,
        camera_id=camera["id"],
        recording_local=recording_local,
        video_path=video_path,
    )
    if status == 201:
        video = value
    elif status == 409 and value.get("code") == "video_duplicate":
        video_id = value.get("videoAssetId")
        if not isinstance(video_id, str):
            raise AcceptanceError("qualification_video_duplicate_unresolved")
        video = client.json("GET", f"/api/videos/{video_id}")
        if not isinstance(video, dict):
            raise AcceptanceError("qualification_video_response_invalid")
    else:
        raise AcceptanceError(value.get("code") or f"qualification_video_http_{status}")

    if (
        video.get("cameraId") != camera["id"]
        or video.get("recordingStartUtc") != expected_utc
        or video.get("recordingTimeZoneId") != camera["timeZoneId"]
        or video.get("recordingUtcOffsetMinutes") != expected_offset
    ):
        raise AcceptanceError("qualification_video_provenance_mismatch")
    return video


def _poll_completed_run(
    client: ApiClient,
    video_id: str,
    processing_run_id: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = client.json("GET", f"/api/videos/{video_id}/processing")
        if not isinstance(status, dict):
            raise AcceptanceError("qualification_processing_status_invalid")
        latest = status.get("latestRun")
        if latest is not None:
            if latest.get("processingRunId") != processing_run_id:
                raise AcceptanceError("qualification_processing_run_superseded")
            state = latest.get("status")
            if state == "Completed":
                return latest
            if state in {"Failed", "Cancelled"}:
                raise AcceptanceError("qualification_processing_failed")
        time.sleep(1.0)
    raise AcceptanceError("qualification_processing_timeout")


def _all_tracks(
    client: ApiClient,
    video_id: str,
    processing_run_id: str | None,
) -> list[dict[str, Any]]:
    query = {"videoAssetId": video_id, "limit": "100"}
    if processing_run_id is not None:
        query["processingRunId"] = processing_run_id
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        current = dict(query)
        if cursor is not None:
            current["cursor"] = cursor
        page = client.json("GET", "/api/tracks/?" + urlencode(current))
        if not isinstance(page, dict) or not isinstance(page.get("items"), list):
            raise AcceptanceError("qualification_track_search_invalid")
        items.extend(page["items"])
        next_cursor = page.get("nextCursor")
        if next_cursor is None:
            break
        if not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor:
            raise AcceptanceError("qualification_cursor_invalid")
        cursor = next_cursor
    return items


def _validate_bundle(bundle_dir: Path, source_commit: str) -> tuple[dict[str, Any], str]:
    manifest_path = bundle_dir / "bundle-manifest.json"
    manifest = read_json(manifest_path)
    if manifest.get("sourceCommit") != source_commit:
        raise AcceptanceError("qualification_bundle_source_mismatch")
    status = manifest.get("releaseStatus")
    if status not in {"qualification-candidate", "production"}:
        raise AcceptanceError("qualification_bundle_status_invalid")
    try:
        build_offline_bundle._verify_bundled_release_selection(bundle_dir, status)
    except Exception as exc:
        raise AcceptanceError("qualification_bundle_release_selection_invalid") from exc

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise AcceptanceError("qualification_bundle_manifest_invalid")
    for item in artifacts:
        if not isinstance(item, dict):
            raise AcceptanceError("qualification_bundle_manifest_invalid")
        relative = item.get("relativePath")
        expected = item.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise AcceptanceError("qualification_bundle_manifest_invalid")
        target = bundle_dir / Path(relative)
        if not target.is_file() or sha256_file(target) != expected:
            raise AcceptanceError("qualification_bundle_artifact_hash_mismatch")
    return manifest, sha256_file(manifest_path)


def _expected_release(args: argparse.Namespace) -> tuple[Any, dict[str, Any]]:
    try:
        selection = verify_release_selection(
            model_root=args.model_root,
            manifest_path=args.model_manifest,
            profile_path=args.pipeline_profile,
            runtime_profile_path=args.runtime_profile,
            qualification_path=args.qualification_record,
            allow_unverified=True,
        )
    except ReleaseMetadataError as exc:
        raise AcceptanceError(exc.code) from exc
    expected = {
        "modelId": selection.manifest.model_id,
        "modelManifestSha256": selection.manifest_sha256,
        "checkpointSha256": selection.manifest.checkpoint.sha256,
        "resolvedConfigSha256": selection.manifest.resolved_config.sha256,
        "pipelineProfileId": selection.profile.profile_id,
        "pipelineProfileSha256": selection.profile_sha256,
        "runtimeProfileId": selection.runtime_profile_id,
        "runtimeProfileSha256": selection.runtime_profile_sha256,
        "qualificationSha256": selection.qualification_sha256,
    }
    return selection, expected


def _compare_attestation(
    attestation: dict[str, Any],
    selection: Any,
    expected: dict[str, Any],
    bundle: dict[str, Any],
    bundle_manifest_sha: str,
    source_commit: str,
) -> dict[str, Any]:
    checks = {
        "modelId": expected["modelId"],
        "modelManifestSha256": expected["modelManifestSha256"],
        "checkpointSha256": expected["checkpointSha256"],
        "resolvedConfigSha256": expected["resolvedConfigSha256"],
        "pipelineProfileId": expected["pipelineProfileId"],
        "pipelineProfileSha256": expected["pipelineProfileSha256"],
        "runtimeProfileId": expected["runtimeProfileId"],
        "runtimeProfileSha256": expected["runtimeProfileSha256"],
        "qualificationSha256": expected["qualificationSha256"],
        "verificationStatus": selection.verification_status,
        "runtimeVariant": bundle.get("platformVariant"),
        "maviCommit": source_commit,
    }
    for key, expected_value in checks.items():
        if attestation.get(key) != expected_value:
            raise AcceptanceError("qualification_attestation_mismatch:" + key)

    variant = bundle.get("platformVariant")
    actual_device = attestation.get("actualDevice")
    if not isinstance(variant, str):
        raise AcceptanceError("qualification_bundle_variant_invalid")
    if variant.endswith("-cpu") and actual_device != "cpu":
        raise AcceptanceError("qualification_attestation_device_mismatch")
    if variant.endswith("-cuda") and not (
        isinstance(actual_device, str) and actual_device.startswith("cuda:")
    ):
        raise AcceptanceError("qualification_attestation_device_mismatch")

    lock_sha = bundle.get("lockSha256")
    if not isinstance(lock_sha, str):
        raise AcceptanceError("qualification_bundle_lock_invalid")
    if selection.verification_status == "unverified":
        if bundle.get("releaseStatus") != "qualification-candidate":
            raise AcceptanceError("qualification_candidate_bundle_required")
        if attestation.get("platformLockSha256") is not None:
            raise AcceptanceError("qualification_candidate_persisted_lock_unexpected")
        return {
            "processingRunId": attestation["processingRunId"],
            "comparisonPassed": True,
            "verificationStatus": "unverified",
            "runtimeVariant": variant,
            "actualDevice": actual_device,
            "maviBuild": attestation["maviBuild"],
            "maviCommit": attestation["maviCommit"],
            "platformLockSha256": None,
            "candidateBundleManifestSha256": bundle_manifest_sha,
            "candidateSelectedLockSha256": lock_sha,
        }

    if bundle.get("releaseStatus") != "production":
        raise AcceptanceError("qualification_production_bundle_required")
    if attestation.get("platformLockSha256") != lock_sha:
        raise AcceptanceError("qualification_production_lock_mismatch")
    return {
        "processingRunId": attestation["processingRunId"],
        "comparisonPassed": True,
        "verificationStatus": "verified",
        "runtimeVariant": variant,
        "actualDevice": actual_device,
        "maviBuild": attestation["maviBuild"],
        "maviCommit": attestation["maviCommit"],
        "platformLockSha256": lock_sha,
        "candidateBundleManifestSha256": None,
        "candidateSelectedLockSha256": None,
    }


def _corpus_binding(
    corpus_path: Path,
    ground_truth_path: Path,
    local_media_sha: str,
    imported_duration_ms: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    corpus = read_json(corpus_path)
    gt = read_json(ground_truth_path)
    corpus_sha = sha256_file(corpus_path)
    gt_sha = sha256_file(ground_truth_path)
    if corpus.get("schemaVersion") != "mavi-phase1-corpus-v1":
        raise AcceptanceError("qualification_corpus_schema_invalid")
    cases = corpus.get("cases")
    if not isinstance(cases, list):
        raise AcceptanceError("qualification_corpus_schema_invalid")
    matches = [
        case for case in cases
        if isinstance(case, dict)
        and case.get("mediaSha256") == local_media_sha
        and case.get("groundTruthManifestSha256") == gt_sha
    ]
    if len(matches) != 1:
        raise AcceptanceError("qualification_corpus_mapping_mismatch")
    if gt.get("videoSha256") != local_media_sha:
        raise AcceptanceError("qualification_ground_truth_video_mismatch")
    if gt.get("durationMs") != imported_duration_ms:
        raise AcceptanceError("qualification_ground_truth_duration_mismatch")
    return gt, {
        "corpusManifestSha256": corpus_sha,
        "groundTruthManifestSha256": gt_sha,
        "videoSha256": local_media_sha,
        "durationMs": imported_duration_ms,
        "bindingPassed": True,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.mode == "formal" and (args.corpus_manifest is None or args.ground_truth is None):
        raise AcceptanceError("qualification_formal_ground_truth_required")
    if args.mode == "empty-scene-diagnostic" and (args.corpus_manifest is not None or args.ground_truth is not None):
        raise AcceptanceError("qualification_diagnostic_ground_truth_arguments_forbidden")

    selection, expected_release = _expected_release(args)
    bundle, bundle_manifest_sha = _validate_bundle(args.bundle_dir, args.source_commit)
    client = ApiClient(args.base_url)

    health = client.json("GET", "/api/health")
    config = client.json("GET", "/api/system/config")
    if not isinstance(health, dict) or not isinstance(config, dict):
        raise AcceptanceError("qualification_health_invalid")

    camera = resolve_camera(
        client,
        code=args.camera_code,
        name=args.camera_name,
        time_zone_id=args.camera_timezone,
    )

    with tempfile.TemporaryDirectory(prefix="mavi-task17-") as directory:
        working = Path(directory) / "qualification.mp4"
        shutil.copyfile(args.video, working)
        local_media_sha = sha256_file(working)
        video = import_or_resolve_video(
            client,
            camera=camera,
            recording_local=args.recording_local,
            video_path=working,
        )
        working.unlink()

    queue = client.json(
        "POST",
        f"/api/videos/{video['id']}/process",
        expected=(202,),
    )
    if not isinstance(queue, dict) or not isinstance(queue.get("processingRunId"), str):
        raise AcceptanceError("qualification_queue_response_invalid")
    run_id = queue["processingRunId"]
    _poll_completed_run(client, video["id"], run_id, args.processing_timeout_seconds)

    attestation = client.json(
        "GET",
        f"/api/processing/runs/{run_id}/attestation",
    )
    if not isinstance(attestation, dict) or attestation.get("processingRunId") != run_id:
        raise AcceptanceError("qualification_attestation_invalid")
    attestation_evidence = _compare_attestation(
        attestation, selection, expected_release, bundle, bundle_manifest_sha, args.source_commit
    )

    exact_tracks = _all_tracks(client, video["id"], run_id)
    default_tracks = _all_tracks(client, video["id"], None)
    if any(item.get("processingRunId") != run_id for item in exact_tracks):
        raise AcceptanceError("qualification_track_run_mismatch")
    if any(item.get("videoAssetId") != video["id"] for item in exact_tracks):
        raise AcceptanceError("qualification_track_video_mismatch")
    if any(item.get("processingRunId") != run_id for item in default_tracks):
        raise AcceptanceError("qualification_default_search_run_mismatch")

    details: list[dict[str, Any]] = []
    normalized_tracks: list[dict[str, Any]] = []
    orphan_count = 0
    for item in exact_tracks:
        detail = client.json("GET", f"/api/tracks/{item['id']}")
        if not isinstance(detail, dict):
            raise AcceptanceError("qualification_track_detail_invalid")
        if detail.get("processingRunId") != run_id or detail.get("videoAssetId") != video["id"]:
            orphan_count += 1
            continue
        details.append(detail)
        representative = detail.get("representative")
        if representative is None:
            if args.mode == "formal":
                raise AcceptanceError("qualification_track_representative_missing")
            continue
        normalized_tracks.append({
            "id": detail["id"],
            "processingRunId": detail["processingRunId"],
            "videoAssetId": detail["videoAssetId"],
            "objectClass": detail["objectClass"],
            "startOffsetMs": detail["startOffsetMs"],
            "endOffsetMs": detail["endOffsetMs"],
            "representative": {
                "videoOffsetMs": representative["videoOffsetMs"],
                "boundingBox": representative["boundingBox"],
            },
        })
    if orphan_count:
        raise AcceptanceError("qualification_orphan_track_detected")

    status, source_headers, source_bytes = client.request("GET", f"/api/videos/{video['id']}/content")
    if status != 200:
        raise AcceptanceError("qualification_source_read_failed")
    streamed_sha = sha256_bytes(source_bytes)
    source_etag = _etag_sha256(source_headers)
    if len({local_media_sha, streamed_sha, source_etag}) != 1:
        raise AcceptanceError("qualification_source_integrity_failed")

    range_status, _, range_payload = client.request(
        "GET",
        f"/api/videos/{video['id']}/content",
        headers={"Range": "bytes=0-0"},
    )
    range_passed = range_status == 206 and len(range_payload) == 1
    if not range_passed:
        raise AcceptanceError("qualification_source_range_failed")

    evidence_attempted = 0
    evidence_passed = 0
    representative_id = None
    representative_sha = None
    representative_etag = None
    for detail in details:
        representative = detail.get("representative")
        if not isinstance(representative, dict):
            continue
        content_url = representative.get("thumbnailContentUrl")
        artifact_id = representative.get("thumbnailArtifactId")
        if not isinstance(content_url, str) or not isinstance(artifact_id, str):
            continue
        evidence_attempted += 1
        artifact_status, artifact_headers, artifact_bytes = client.request("GET", content_url)
        if artifact_status != 200:
            raise AcceptanceError("qualification_representative_read_failed")
        artifact_sha = sha256_bytes(artifact_bytes)
        artifact_etag = _etag_sha256(artifact_headers)
        if artifact_sha != artifact_etag:
            raise AcceptanceError("qualification_representative_integrity_failed")
        evidence_passed += 1
        if representative_id is None:
            representative_id = artifact_id
            representative_sha = artifact_sha
            representative_etag = artifact_etag

    gt_evidence = None
    metrics = None
    if args.mode == "formal":
        gt, gt_evidence = _corpus_binding(
            args.corpus_manifest,
            args.ground_truth,
            local_media_sha,
            video["durationMs"],
        )
        if not gt.get("events"):
            raise AcceptanceError("qualification_formal_no_expected_events")
        if not normalized_tracks or not details or evidence_passed == 0:
            raise AcceptanceError("qualification_formal_no_reviewable_tracks")
        acceptance_profile = read_json(args.acceptance_profile)
        metrics = evaluator.evaluate(gt, normalized_tracks, acceptance_profile)

    counts = {"Person": 0, "Vehicle": 0}
    for item in exact_tracks:
        object_class = item.get("objectClass")
        if object_class in counts:
            counts[object_class] += 1

    return {
        "schemaVersion": "mavi-phase1-acceptance-evidence-v1",
        "mode": args.mode,
        "sourceCommit": args.source_commit,
        "environmentLabel": args.environment_label,
        "releaseExpected": expected_release,
        "attestation": attestation_evidence,
        "camera": {
            "id": camera["id"],
            "code": camera["code"],
            "timeZoneId": camera["timeZoneId"],
            "isActive": camera["isActive"],
        },
        "video": {
            "id": video["id"],
            "cameraId": video["cameraId"],
            "recordingStartUtc": video["recordingStartUtc"],
            "recordingTimeZoneId": video["recordingTimeZoneId"],
            "recordingUtcOffsetMinutes": video["recordingUtcOffsetMinutes"],
            "durationMs": video["durationMs"],
        },
        "sourceMedia": {
            "localSha256": local_media_sha,
            "streamedSha256": streamed_sha,
            "etagSha256": source_etag,
            "matched": True,
        },
        "groundTruth": gt_evidence,
        "processing": {
            "processingRunId": run_id,
            "terminalState": "Completed",
            "processingDurationMs": attestation["processingDurationMs"],
        },
        "tracks": {
            "total": len(exact_tracks),
            "person": counts["Person"],
            "vehicle": counts["Vehicle"],
            "detailsResolved": len(details),
            "orphanCount": orphan_count,
        },
        "evidenceReads": {
            "attempted": evidence_attempted,
            "passed": evidence_passed,
            "representativeArtifactId": representative_id,
            "streamedSha256": representative_sha,
            "etagSha256": representative_etag,
        },
        "sourceRange": {
            "passed": range_passed,
            "statusCode": range_status,
        },
        "metrics": metrics,
        "result": {
            "passed": True,
            "failureCodes": [],
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("formal", "empty-scene-diagnostic"), required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--camera-code", required=True)
    parser.add_argument("--camera-name", required=True)
    parser.add_argument("--camera-timezone", required=True)
    parser.add_argument("--recording-local", required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--processing-timeout-seconds", type=float, default=900)
    parser.add_argument("--environment-label", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--model-manifest", type=Path, required=True)
    parser.add_argument("--pipeline-profile", type=Path, required=True)
    parser.add_argument("--runtime-profile", type=Path, required=True)
    parser.add_argument("--qualification-record", type=Path, required=True)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--acceptance-profile", type=Path, required=True)
    parser.add_argument("--corpus-manifest", type=Path)
    parser.add_argument("--ground-truth", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if not args.video.is_file():
            raise AcceptanceError("qualification_video_missing")
        if args.processing_timeout_seconds <= 0:
            raise AcceptanceError("qualification_timeout_invalid")
        evidence = run(args)
    except (AcceptanceError, evaluator.EvaluationError) as exc:
        code = getattr(exc, "code", str(exc))
        failure = {
            "schemaVersion": "mavi-phase1-acceptance-failure-v1",
            "sourceCommit": args.source_commit,
            "environmentLabel": args.environment_label,
            "code": code,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"ok": False, "code": code}, sort_keys=True))
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "evidenceSha256": sha256_file(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
