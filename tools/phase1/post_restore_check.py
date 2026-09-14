#!/usr/bin/env python3
"""Revalidate a restored Phase-1 acceptance case through public MAVI APIs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from urllib.parse import urlencode

E2E_PATH = Path(__file__).with_name("phase1_e2e_check.py")
SPEC = importlib.util.spec_from_file_location("mavi_phase1_e2e_restore", E2E_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("task17_e2e_import_failed")
e2e = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = e2e
SPEC.loader.exec_module(e2e)


class RestoreCheckError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--acceptance-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        evidence = json.loads(args.acceptance_evidence.read_text(encoding="utf-8"))
        if evidence.get("schemaVersion") != "mavi-phase1-acceptance-evidence-v1":
            raise RestoreCheckError("restore_acceptance_evidence_invalid")
        if evidence.get("result", {}).get("passed") is not True:
            raise RestoreCheckError("restore_acceptance_evidence_not_passed")

        client = e2e.ApiClient(args.base_url)
        health = client.json("GET", "/api/health")
        if (
            not isinstance(health, dict)
            or health.get("status") != "ok"
            or health.get("commit") != evidence["sourceCommit"]
        ):
            raise RestoreCheckError("restore_application_identity_mismatch")

        camera_expected = evidence["camera"]
        camera = client.json("GET", f"/api/cameras/{camera_expected['id']}")
        if not isinstance(camera, dict) or any(
            camera.get(key) != camera_expected[key]
            for key in ("id", "code", "timeZoneId", "isActive")
        ):
            raise RestoreCheckError("restore_camera_identity_mismatch")

        video_expected = evidence["video"]
        video = client.json("GET", f"/api/videos/{video_expected['id']}")
        if not isinstance(video, dict) or any(
            video.get(key) != video_expected[key]
            for key in (
                "id", "cameraId", "recordingStartUtc", "recordingTimeZoneId",
                "recordingUtcOffsetMinutes", "durationMs"
            )
        ):
            raise RestoreCheckError("restore_video_identity_mismatch")

        run_id = evidence["processing"]["processingRunId"]
        attestation = client.json("GET", f"/api/processing/runs/{run_id}/attestation")
        if (
            not isinstance(attestation, dict)
            or attestation.get("processingRunId") != run_id
            or attestation.get("videoAssetId") != video_expected["id"]
            or attestation.get("maviCommit") != evidence["attestation"]["maviCommit"]
        ):
            raise RestoreCheckError("restore_run_attestation_mismatch")

        status, source_headers, source_bytes = client.request(
            "GET", f"/api/videos/{video_expected['id']}/content"
        )
        if status != 200:
            raise RestoreCheckError("restore_source_read_failed")
        source_sha = e2e.sha256_bytes(source_bytes)
        source_etag = e2e._etag_sha256(source_headers)
        expected_source_sha = evidence["sourceMedia"]["localSha256"]
        if source_sha != expected_source_sha or source_etag != expected_source_sha:
            raise RestoreCheckError("restore_source_integrity_mismatch")

        page = client.json(
            "GET",
            "/api/tracks/?" + urlencode({
                "videoAssetId": video_expected["id"],
                "processingRunId": run_id,
                "limit": "100",
            }),
        )
        if not isinstance(page, dict):
            raise RestoreCheckError("restore_track_search_invalid")
        items = list(page.get("items") or [])
        cursor = page.get("nextCursor")
        while cursor is not None:
            page = client.json(
                "GET",
                "/api/tracks/?" + urlencode({
                    "videoAssetId": video_expected["id"],
                    "processingRunId": run_id,
                    "limit": "100",
                    "cursor": cursor,
                }),
            )
            if not isinstance(page, dict):
                raise RestoreCheckError("restore_track_search_invalid")
            items.extend(page.get("items") or [])
            cursor = page.get("nextCursor")

        expected_track_ids = set(evidence["tracks"]["trackIds"])
        restored_track_ids = {item.get("id") for item in items}
        if restored_track_ids != expected_track_ids:
            raise RestoreCheckError("restore_track_identity_mismatch")

        for track_id in sorted(expected_track_ids):
            detail = client.json("GET", f"/api/tracks/{track_id}")
            if (
                not isinstance(detail, dict)
                or detail.get("processingRunId") != run_id
                or detail.get("videoAssetId") != video_expected["id"]
            ):
                raise RestoreCheckError("restore_track_detail_mismatch")

        artifact_id = evidence["evidenceReads"]["representativeArtifactId"]
        if artifact_id is not None:
            status, artifact_headers, artifact_bytes = client.request(
                "GET", f"/api/artifacts/{artifact_id}/content"
            )
            if status != 200:
                raise RestoreCheckError("restore_evidence_read_failed")
            artifact_sha = e2e.sha256_bytes(artifact_bytes)
            artifact_etag = e2e._etag_sha256(artifact_headers)
            if (
                artifact_sha != evidence["evidenceReads"]["streamedSha256"]
                or artifact_etag != evidence["evidenceReads"]["etagSha256"]
            ):
                raise RestoreCheckError("restore_evidence_integrity_mismatch")

        result = {
            "schemaVersion": "mavi-post-restore-check-v1",
            "sourceCommit": evidence["sourceCommit"],
            "acceptanceEvidenceSha256": sha256_file(args.acceptance_evidence),
            "cameraId": camera_expected["id"],
            "videoAssetId": video_expected["id"],
            "processingRunId": run_id,
            "trackIds": sorted(expected_track_ids),
            "representativeArtifactId": artifact_id,
            "sourceSha256": source_sha,
            "result": {"passed": True, "failureCodes": []},
        }
    except (OSError, json.JSONDecodeError, e2e.AcceptanceError, RestoreCheckError) as exc:
        print(json.dumps({"ok": False, "code": str(exc)}, sort_keys=True))
        return 2

    if args.output.exists():
        print(json.dumps({"ok": False, "code": "restore_check_output_exists"}, sort_keys=True))
        return 2
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"ok": True, "sha256": sha256_file(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
