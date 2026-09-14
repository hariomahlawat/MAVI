#!/usr/bin/env python3
"""Verify retained authoritative Phase-1 state through public MAVI APIs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from urllib.parse import urlencode

E2E_PATH = Path(__file__).with_name("phase1_e2e_check.py")
SPEC = importlib.util.spec_from_file_location("mavi_phase1_e2e_state", E2E_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("task17_e2e_import_failed")
e2e = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = e2e
SPEC.loader.exec_module(e2e)


class StateCheckError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_state(
    *,
    base_url: str,
    acceptance_evidence: Path,
    expected_application_commit: str,
) -> dict:
    evidence = json.loads(acceptance_evidence.read_text(encoding="utf-8"))
    if evidence.get("schemaVersion") != "mavi-phase1-acceptance-evidence-v1":
        raise StateCheckError("state_acceptance_evidence_invalid")
    if evidence.get("result", {}).get("passed") is not True:
        raise StateCheckError("state_acceptance_evidence_not_passed")

    client = e2e.ApiClient(base_url)
    health = client.json("GET", "/api/health")
    if (
        not isinstance(health, dict)
        or health.get("status") != "ok"
        or health.get("commit") != expected_application_commit
    ):
        raise StateCheckError("state_application_identity_mismatch")

    camera_expected = evidence["camera"]
    camera = client.json("GET", f"/api/cameras/{camera_expected['id']}")
    if not isinstance(camera, dict) or any(
        camera.get(key) != camera_expected[key]
        for key in ("id", "code", "timeZoneId", "isActive")
    ):
        raise StateCheckError("state_camera_identity_mismatch")

    video_expected = evidence["video"]
    video = client.json("GET", f"/api/videos/{video_expected['id']}")
    if not isinstance(video, dict) or any(
        video.get(key) != video_expected[key]
        for key in (
            "id", "cameraId", "recordingStartUtc", "recordingTimeZoneId",
            "recordingUtcOffsetMinutes", "durationMs"
        )
    ):
        raise StateCheckError("state_video_identity_mismatch")

    run_id = evidence["processing"]["processingRunId"]
    attestation = client.json("GET", f"/api/processing/runs/{run_id}/attestation")
    if (
        not isinstance(attestation, dict)
        or attestation.get("processingRunId") != run_id
        or attestation.get("videoAssetId") != video_expected["id"]
        or attestation.get("maviCommit") != evidence["attestation"]["maviCommit"]
    ):
        raise StateCheckError("state_run_attestation_mismatch")

    status, source_headers, source_bytes = client.request(
        "GET", f"/api/videos/{video_expected['id']}/content"
    )
    if status != 200:
        raise StateCheckError("state_source_read_failed")
    source_sha = e2e.sha256_bytes(source_bytes)
    source_etag = e2e._etag_sha256(source_headers)
    expected_source_sha = evidence["sourceMedia"]["localSha256"]
    if source_sha != expected_source_sha or source_etag != expected_source_sha:
        raise StateCheckError("state_source_integrity_mismatch")

    items = []
    cursor = None
    while True:
        query = {
            "videoAssetId": video_expected["id"],
            "processingRunId": run_id,
            "limit": "100",
        }
        if cursor is not None:
            query["cursor"] = cursor
        page = client.json("GET", "/api/tracks/?" + urlencode(query))
        if not isinstance(page, dict) or not isinstance(page.get("items"), list):
            raise StateCheckError("state_track_search_invalid")
        items.extend(page["items"])
        cursor = page.get("nextCursor")
        if cursor is None:
            break
        if not isinstance(cursor, str) or not cursor:
            raise StateCheckError("state_track_cursor_invalid")

    expected_track_ids = set(evidence["tracks"]["trackIds"])
    restored_track_ids = {item.get("id") for item in items}
    if restored_track_ids != expected_track_ids:
        raise StateCheckError("state_track_identity_mismatch")

    for track_id in sorted(expected_track_ids):
        detail = client.json("GET", f"/api/tracks/{track_id}")
        if (
            not isinstance(detail, dict)
            or detail.get("processingRunId") != run_id
            or detail.get("videoAssetId") != video_expected["id"]
        ):
            raise StateCheckError("state_track_detail_mismatch")

    artifact_id = evidence["evidenceReads"]["representativeArtifactId"]
    artifact_sha = None
    artifact_etag = None
    if artifact_id is not None:
        status, artifact_headers, artifact_bytes = client.request(
            "GET", f"/api/artifacts/{artifact_id}/content"
        )
        if status != 200:
            raise StateCheckError("state_evidence_read_failed")
        artifact_sha = e2e.sha256_bytes(artifact_bytes)
        artifact_etag = e2e._etag_sha256(artifact_headers)
        if (
            artifact_sha != evidence["evidenceReads"]["streamedSha256"]
            or artifact_etag != evidence["evidenceReads"]["etagSha256"]
        ):
            raise StateCheckError("state_evidence_integrity_mismatch")

    return {
        "schemaVersion": "mavi-authoritative-state-check-v1",
        "acceptanceEvidenceSha256": sha256_file(acceptance_evidence),
        "acceptanceSourceCommit": evidence["sourceCommit"],
        "expectedApplicationCommit": expected_application_commit,
        "observedApplicationCommit": health["commit"],
        "cameraId": camera_expected["id"],
        "videoAssetId": video_expected["id"],
        "processingRunId": run_id,
        "trackIds": sorted(expected_track_ids),
        "representativeArtifactId": artifact_id,
        "sourceSha256": source_sha,
        "sourceEtagSha256": source_etag,
        "artifactSha256": artifact_sha,
        "artifactEtagSha256": artifact_etag,
        "result": {"passed": True, "failureCodes": []},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--acceptance-evidence", type=Path, required=True)
    parser.add_argument("--expected-application-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.output.exists():
            raise StateCheckError("state_check_output_exists")
        value = check_state(
            base_url=args.base_url,
            acceptance_evidence=args.acceptance_evidence,
            expected_application_commit=args.expected_application_commit,
        )
        args.output.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (OSError, json.JSONDecodeError, e2e.AcceptanceError, StateCheckError) as exc:
        print(json.dumps({"ok": False, "code": str(exc)}, sort_keys=True))
        return 2

    print(json.dumps({"ok": True, "sha256": sha256_file(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
