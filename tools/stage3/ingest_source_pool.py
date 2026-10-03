#!/usr/bin/env python3
"""Development-host execution (Stage 3, S3.2 plan T9): ``vehicle-subclass-t9-execution-v1``.

Drives MAVI through its product API only (standard-library HTTP; never the database, never a
bypass) for every member of the frozen source pool:
``GET/POST /api/cameras`` → ``POST /api/videos/import`` (the member's T8 ``video.mp4``) →
``POST /api/videos/{id}/process`` → ``GET /api/videos/{id}/processing`` until terminal → the
T1 export tool. It then checks the exit conditions and writes the execution record.

Before any API call it verifies the source-pool and ingestion-map git bindings (or their
committed ``.sha256`` digest files), the map against the pool and release, every T8
derivation against its pool member, and the measured profile. It needs a fresh, dedicated
catalogue: the read-only ``GET /api/cameras`` and ``GET /api/videos`` must show nothing T9's
journal does not explain (``t9_catalogue_not_fresh``). Runs are never reused: every run is
queued by T9 and journalled before polling; a duplicate import is never adopted
(``t9_asset_preexisting``); a latest run that is not the journalled one is
``t9_run_substituted``. Cameras are created once and, on resume, looked up by code
(``t9_camera_mismatch``).

The API URL, journal, export root, export command and local input paths are runtime-only
and never written into the record. The record holds no native-media pack identity: no
product surface exposes the host's pack, and T9 does not fabricate one.

Usage::

    ingest_source_pool.py --repository <git root>
        --source-pool <file> (--source-pool-commit <sha> | --source-pool-digest <file> --source-pool-digest-commit <sha>)
        --ingestion-map <file> (--ingestion-map-commit <sha> | --ingestion-map-digest <file> --ingestion-map-digest-commit <sha>)
        --release <record> --derivation <dir>... --pipeline-profile <file>
        --api <url> --journal <file> --export-root <dir> --export-exe <exe> [--export-arg <arg>...]
        --out <file>
    ingest_source_pool.py --verify-sample <sample> --execution <record>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "phase1"))
import artefacts as a  # noqa: E402
import derive_mp4  # noqa: E402
import evaluate_vehicle_subclass as evaluator  # noqa: E402
import ingestion_map  # noqa: E402
import release_bridge as rb  # noqa: E402

SCHEMA = "vehicle-subclass-t9-execution-v1"
POOL_SCHEMA = "vehicle-subclass-source-pool-v1"
DERIVATION_SCHEMA = "vehicle-subclass-derivation-v1"
SAMPLE_SCHEMA = "vehicle-subclass-sample-v1"
JOURNAL_SCHEMA = "s3-2-t9-journal-v1"
POOL_PATHS = ("docs/qualification/stage3/s3-2-source-pool.json", "docs/qualification/stage3/s3-2-source-pool.sha256")
MAP_PATHS = ("docs/qualification/stage3/s3-2-ingestion-map.json", "docs/qualification/stage3/s3-2-ingestion-map.sha256")
PRODUCER_KEYS = (*evaluator._PRODUCER_TEXT, *evaluator._PRODUCER_SHA256, *evaluator._PRODUCER_OPTIONAL_SHA256)
# Producer members the S3.1 check does not compare; T9 requires them equal across runs as well.
PRODUCER_EXTRA = ("maviBuild", "modelPackId", "runtimePackId", "runtimePackSource", "platform")
TERMINAL_FAILURES = ("Failed", "Cancelled")
HTTP_TIMEOUT_SECONDS = 600


# ---------------------------------------------------------------- committed inputs


def bound_artefact(repository: Path, path: Path, schema: str, code: str, paths: tuple[str, str], commit: str | None,
                   digest: Path | None, digest_commit: str | None) -> tuple[dict[str, Any], str, dict[str, str]]:
    """A committed artefact, or one whose committed digest file names its SHA-256."""
    document, _, sha = a.read_artefact(path, schema, code)
    if digest is None:
        a.require(commit is not None and digest_commit is None, f"{code}:binding")
        binding = a.git_binding(repository, path, commit, paths[0], f"{code}:not_committed")
    else:
        a.require(commit is None and digest_commit is not None, f"{code}:binding")
        binding = a.git_binding(repository, digest, digest_commit, paths[1], f"{code}:not_committed")
        a.require(a.read_bytes(digest, code) == f"{sha}\n".encode("ascii"), f"{code}:digest_mismatch")
    return document, sha, {"gitCommit": binding["gitCommit"], "gitPath": binding["gitPath"]}


def file_sha256(path: Path, code: str) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    try:
        with open(path, "rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
                size += len(block)
    except OSError as exc:
        raise a.S32Error(f"{code}:unreadable") from exc
    return digest.hexdigest(), size


def load_derivations(directories: list[Path], pool: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Exactly one verified T8 derivation per pool member, bound to that member."""
    members = {member["member"]: member for member in pool["members"]}
    derivations: dict[str, dict[str, Any]] = {}
    for directory in directories:
        manifest, _, manifest_sha = a.read_artefact(Path(directory) / derive_mp4.MANIFEST, DERIVATION_SCHEMA,
                                                    "t9_derivation_invalid")
        video = Path(directory) / derive_mp4.VIDEO
        video_sha, size = file_sha256(video, "t9_derivation_invalid:video")
        try:
            derive_mp4.check_consistency(manifest, video_sha)
        except a.S32Error as exc:
            raise a.S32Error(f"t9_derivation_invalid:{exc}") from exc
        a.require(size <= manifest["importLimitBytes"], "t9_derivation_invalid:size")
        release = manifest["release"]
        a.require(release["releaseRecordSha256"] == pool["releaseRecordSha256"]
                  and release["releaseId"] == pool["releaseId"], "t9_derivation_release")
        name = release["member"]
        a.require(name in members, "t9_derivation_not_in_pool")
        a.require(name not in derivations, "t9_derivation_duplicate")
        a.require(manifest["sourceSha256"] == members[name]["sha256"], "t9_derivation_source")
        derivations[name] = {"manifest": manifest, "manifestSha256": manifest_sha, "video": video,
                             "videoSha256": video_sha}
    a.require(set(derivations) == set(members), "t9_derivation_missing")
    return derivations


# ---------------------------------------------------------------- HTTP


class Multipart:
    """A streamed ``multipart/form-data`` body: the file is read in blocks, never held in memory."""

    def __init__(self, fields: dict[str, str], file_field: str, file_name: str, file_path: Path) -> None:
        self.boundary = f"mavi-s32-{uuid.uuid4().hex}"
        head = b"".join(
            f'--{self.boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")
            for name, value in fields.items())
        head += (f'--{self.boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{file_name}"\r\n'
                 f"Content-Type: video/mp4\r\n\r\n").encode("utf-8")
        self.head, self.tail, self.path = head, f"\r\n--{self.boundary}--\r\n".encode("ascii"), Path(file_path)
        self.length = len(head) + self.path.stat().st_size + len(self.tail)

    @property
    def content_type(self) -> str:
        return f"multipart/form-data; boundary={self.boundary}"

    def __iter__(self) -> Iterator[bytes]:
        yield self.head
        with open(self.path, "rb") as stream:
            yield from iter(lambda: stream.read(1 << 20), b"")
        yield self.tail


LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")


class Api:
    """The local MAVI API only: a loopback URL, and never a system or environment proxy, so neither
    the calls nor the corpus uploads can leave the host."""

    def __init__(self, base: str) -> None:
        parsed = urllib.parse.urlsplit(base)
        a.require(parsed.scheme in ("http", "https") and parsed.hostname in LOOPBACK_HOSTS
                  and not parsed.username and not parsed.query, "t9_api_not_local")
        self.base = base.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(self, method: str, path: str, *, json_body: Any = None, multipart: Multipart | None = None) -> tuple[int, Any]:
        headers = {"Accept": "application/json"}
        data: Any = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif multipart is not None:
            data = multipart
            headers["Content-Type"] = multipart.content_type
            headers["Content-Length"] = str(multipart.length)
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with self.opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
        except (urllib.error.URLError, OSError) as exc:
            raise a.S32Error("t9_api_unreachable") from exc
        try:
            body = json.loads(raw.decode("utf-8")) if raw else None
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise a.S32Error(f"t9_api_invalid_response:{method}") from exc
        return status, body


def _problem_code(body: Any) -> str:
    return str(body.get("code")) if isinstance(body, dict) and body.get("code") else "unknown"


# ---------------------------------------------------------------- journal


class Journal:
    """The runtime-only resume journal: what this T9 instance created and queued."""

    def __init__(self, path: Path, pool_sha: str, map_sha: str) -> None:
        self.path = Path(path)
        if self.path.exists():
            self.data = a.parse_json(a.read_bytes(self.path, "t9_journal_invalid"), "t9_journal_invalid")
            a.require(isinstance(self.data, dict) and self.data.get("schemaVersion") == JOURNAL_SCHEMA
                      and isinstance(self.data.get("cameras"), dict) and isinstance(self.data.get("members"), dict),
                      "t9_journal_invalid")
            a.require(self.data.get("sourcePoolSha256") == pool_sha and self.data.get("ingestionMapSha256") == map_sha,
                      "t9_journal_mismatch")
        else:
            self.data = {"schemaVersion": JOURNAL_SCHEMA, "sourcePoolSha256": pool_sha, "ingestionMapSha256": map_sha,
                         "cameras": {}, "members": {}}

    @property
    def cameras(self) -> dict[str, str]:
        return self.data["cameras"]

    def member(self, name: str) -> dict[str, Any]:
        return self.data["members"].setdefault(name, {})

    def assets(self) -> set[str]:
        return {m["videoAssetId"] for m in self.data["members"].values() if m.get("videoAssetId")}

    def save(self) -> None:
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}")
        temporary.write_bytes(json.dumps(self.data, sort_keys=True, indent=1).encode("utf-8"))
        os.replace(temporary, self.path)


# ---------------------------------------------------------------- execution


def check_fresh(api: Api, journal: Journal) -> dict[str, dict[str, Any]]:
    """The catalogue holds nothing this T9 instance did not create; returns its videos by id."""
    status, cameras = api.call("GET", "/api/cameras")
    a.require(status == 200 and isinstance(cameras, list), "t9_api_invalid_response:cameras")
    status, videos = api.call("GET", "/api/videos")
    a.require(status == 200 and isinstance(videos, list), "t9_api_invalid_response:videos")
    known_cameras = set(journal.cameras.values())
    a.require(all(isinstance(c, dict) and c.get("id") in known_cameras for c in cameras), "t9_catalogue_not_fresh:cameras")
    known_assets = journal.assets()
    a.require(all(isinstance(v, dict) and v.get("id") in known_assets for v in videos), "t9_catalogue_not_fresh:videos")
    return {video["id"]: video for video in videos}


def ensure_cameras(api: Api, journal: Journal, cameras: dict[str, dict[str, Any]]) -> dict[str, str]:
    status, existing = api.call("GET", "/api/cameras")
    a.require(status == 200 and isinstance(existing, list), "t9_api_invalid_response:cameras")
    by_id = {camera.get("id"): camera for camera in existing if isinstance(camera, dict)}
    ids: dict[str, str] = {}
    for code, camera in sorted(cameras.items()):
        if code in journal.cameras:
            found = by_id.get(journal.cameras[code])
            a.require(found is not None and found.get("code") == code and found.get("name") == camera["name"]
                      and found.get("timeZoneId") == camera["timeZoneId"], "t9_camera_mismatch")
        else:
            status, created = api.call("POST", "/api/cameras", json_body={
                "code": code, "name": camera["name"], "timeZoneId": camera["timeZoneId"]})
            a.require(status == 201 and isinstance(created, dict), f"t9_camera_mismatch:{status}:{_problem_code(created)}")
            a.require(created.get("code") == code and created.get("name") == camera["name"]
                      and created.get("timeZoneId") == camera["timeZoneId"], "t9_camera_mismatch")
            journal.cameras[code] = created["id"]
            journal.save()
        ids[code] = journal.cameras[code]
    return ids


def same_recording(asset: Any, camera_id: str, entry: dict[str, Any], zone: str) -> bool:
    """MAVI's asset carries this camera, the camera's zone and the map's start converted as the importer does."""
    if not isinstance(asset, dict) or asset.get("cameraId") != camera_id or asset.get("recordingTimeZoneId") != zone:
        return False
    try:
        started = datetime.fromisoformat(str(asset.get("recordingStartUtc")).replace("Z", "+00:00"))
    except ValueError:
        return False
    return started.tzinfo is not None and started == ingestion_map.recording_start_utc(entry["recordingStartLocal"], zone)


def ensure_asset(api: Api, journal: Journal, name: str, entry: dict[str, Any], camera: tuple[str, str],
                 derivation: dict[str, Any], videos: dict[str, dict[str, Any]]) -> str:
    camera_id, zone = camera
    record = journal.member(name)
    if record.get("videoAssetId"):
        # Bound by this instance earlier; it must still be the same asset, content, camera and recording start.
        a.require(record.get("derivedSha256") == derivation["videoSha256"], "t9_asset_preexisting:journal")
        a.require(same_recording(videos.get(record["videoAssetId"]), camera_id, entry, zone),
                  "t9_asset_preexisting:journal")
        return record["videoAssetId"]
    body = Multipart({"cameraId": camera_id, "recordingStartLocal": entry["recordingStartLocal"]}, "file",
                     derive_mp4.VIDEO, derivation["video"])
    status, created = api.call("POST", "/api/videos/import", multipart=body)
    if status == 409 and _problem_code(created) == "video_duplicate":
        # This instance never created it (it is not journalled): pre-existing state is never adopted.
        raise a.S32Error("t9_asset_preexisting")
    a.require(status == 201 and isinstance(created, dict) and created.get("id"),
              f"t9_import_refused:{status}:{_problem_code(created)}")
    a.require(same_recording(created, camera_id, entry, zone), "t9_import_refused:recording")
    record.update({"videoAssetId": created["id"], "derivedSha256": derivation["videoSha256"]})
    journal.save()
    return created["id"]


def ensure_run(api: Api, journal: Journal, name: str, asset: str, poll_seconds: float, timeout_seconds: float) -> str:
    record = journal.member(name)
    if not record.get("processingRunId"):
        status, queued = api.call("POST", f"/api/videos/{asset}/process")
        # 409: a run this instance did not queue is already active for the asset.
        a.require(status != 409, "t9_run_substituted:active")
        a.require(status == 202 and isinstance(queued, dict) and queued.get("processingRunId"),
                  f"t9_process_refused:{status}:{_problem_code(queued)}")
        record["processingRunId"] = queued["processingRunId"]
        journal.save()  # journalled before polling
    run = record["processingRunId"]
    deadline = time.monotonic() + timeout_seconds
    while True:
        status, state = api.call("GET", f"/api/videos/{asset}/processing")
        a.require(status == 200 and isinstance(state, dict), "t9_api_invalid_response:processing")
        latest = state.get("latestRun")
        a.require(isinstance(latest, dict) and latest.get("processingRunId") == run, "t9_run_substituted")
        if latest.get("status") == "Completed":
            return run
        a.require(latest.get("status") not in TERMINAL_FAILURES, f"t9_run_failed:{latest.get('status')}")
        a.require(time.monotonic() < deadline, "t9_run_timeout")
        time.sleep(poll_seconds)


def ensure_export(run: str, profile: Path, export_root: Path, command: list[str]) -> Path:
    directory = Path(export_root) / run
    if not directory.exists():
        result = subprocess.run([*command, "--run", run, "--pipeline-profile", str(profile), "--out", str(directory)],
                                capture_output=True, check=False)
        a.require(result.returncode == 0, f"t9_export_failed:{result.returncode}")
    path = directory / a.EXPORT_FILE_NAME
    a.require(path.is_file(), "t9_export_failed:missing")
    return path


def producer(exports: dict[str, a.Export], measured_profile_sha: str) -> dict[str, Any]:
    attestations = [export.attestation for export in exports.values()]
    try:
        checked = evaluator._producer(attestations, measured_profile_sha)
    except evaluator.SubclassEvaluationError as exc:
        raise a.S32Error(f"t9_producer:{exc}") from exc
    extras = {tuple(json.dumps(item.get(key), sort_keys=True) for key in PRODUCER_EXTRA) for item in attestations}
    a.require(len(extras) == 1, "t9_producer:producers_differ")
    return {**{key: checked[key] for key in PRODUCER_KEYS}, **{key: attestations[0].get(key) for key in PRODUCER_EXTRA}}


def execute(args: argparse.Namespace) -> bytes:
    a.require(not args.out.exists(), "output_exists")
    repository = args.repository
    pool, pool_sha, pool_binding = bound_artefact(
        repository, args.source_pool, POOL_SCHEMA, "t9_source_pool", POOL_PATHS, args.source_pool_commit,
        args.source_pool_digest, args.source_pool_digest_commit)
    a.require(pool["kind"] == "pilot", "t9_source_pool:kind")
    release, release_sha = rb.read_release(args.release, "t9_release_invalid")
    a.require(release_sha == pool["releaseRecordSha256"] and release["releaseId"] == pool["releaseId"],
              "t9_release_mismatch")
    document, map_sha, map_binding = bound_artefact(
        repository, args.ingestion_map, ingestion_map.SCHEMA, ingestion_map.CODE, MAP_PATHS, args.ingestion_map_commit,
        args.ingestion_map_digest, args.ingestion_map_digest_commit)
    cameras = ingestion_map.check(document, pool=pool, pool_sha256=pool_sha, release=release, release_sha256=release_sha,
                                  repository=repository)
    entries = {entry["member"]: entry for entry in document["members"]}
    derivations = load_derivations(args.derivation, pool)
    profile_sha = a.sha256_hex(a.read_bytes(args.pipeline_profile, "pipeline_profile_unreadable"))
    a.require(args.export_root.is_dir(), "t9_export_root_missing")

    # Every input is verified; only now does T9 touch the API.
    api = Api(args.api)
    journal = Journal(args.journal, pool_sha, map_sha)
    videos = check_fresh(api, journal)
    camera_ids = ensure_cameras(api, journal, cameras)
    command = [args.export_exe, *args.export_arg]
    runs: dict[str, tuple[str, str, Path]] = {}
    for name in sorted(entries):
        entry = entries[name]
        camera = (camera_ids[entry["cameraCode"]], cameras[entry["cameraCode"]]["timeZoneId"])
        asset = ensure_asset(api, journal, name, entry, camera, derivations[name], videos)
        run = ensure_run(api, journal, name, asset, args.poll_seconds, args.poll_timeout_seconds)
        runs[name] = (asset, run, ensure_export(run, args.pipeline_profile, args.export_root, command))

    exports = a.load_exports([path for _, _, path in runs.values()])
    by_run = {export.run_id: (sha, export) for sha, export in exports.items()}
    members = []
    for name in sorted(entries):
        asset, run, _ = runs[name]
        a.require(run in by_run, "t9_run_substituted:export")
        export_sha, export = by_run[run]
        a.require(export.document["processingRun"]["status"] == "Completed", "t9_run_failed:export")
        a.require(export.video["videoAssetId"] == asset, "t9_export_mismatch:video")
        a.require(export.video["sourceSha256"] == derivations[name]["manifest"]["outputSha256"],
                  "t9_export_mismatch:source")
        a.require(export.video["cameraCode"] == entries[name]["cameraCode"], "t9_export_mismatch:camera")
        members.append({
            "member": name, "derivationManifestSha256": derivations[name]["manifestSha256"],
            "derivedSha256": derivations[name]["manifest"]["outputSha256"], "cameraCode": entries[name]["cameraCode"],
            "recordingStartLocal": entries[name]["recordingStartLocal"], "recordingTime": entries[name]["recordingTime"],
            "videoAssetId": asset, "processingRunId": run, "attestationSha256": a.document_sha256(export.attestation),
            "exportSha256": export_sha})
    record = {
        "schemaVersion": SCHEMA,
        "sourcePoolSha256": pool_sha, "sourcePoolBinding": pool_binding,
        "ingestionMapSha256": map_sha, "ingestionMapBinding": map_binding,
        "releaseRecordSha256": release_sha, "measuredProfileSha256": profile_sha,
        "producer": producer(exports, profile_sha),
        "cameras": [{**cameras[code], "cameraId": camera_ids[code]} for code in sorted(cameras)],
        "members": members,
    }
    a.validate(record, SCHEMA, "t9_execution_invalid")
    data = a.canonical_json(record)
    a.write_once(args.out, data)
    return data


def verify_sample(sample_path: Path, execution_path: Path) -> None:
    """The pilot sample is drawn from exactly the T9 exports and derivations (plan T9, T10 step 2)."""
    sample, _, _ = a.read_artefact(sample_path, SAMPLE_SCHEMA, "sample_invalid")
    record, _, _ = a.read_artefact(execution_path, SCHEMA, "t9_execution_invalid")
    a.require(set(sample["exportSha256s"]) == {m["exportSha256"] for m in record["members"]}
              and len(sample["exportSha256s"]) == len(record["members"]), "t9_sample_mismatch:exports")
    a.require(set(sample["derivationSha256s"]) == {m["derivationManifestSha256"] for m in record["members"]}
              and len(sample["derivationSha256s"]) == len(record["members"]), "t9_sample_mismatch:derivations")
    a.require(sample["releaseRecordSha256"] == record["releaseRecordSha256"], "t9_sample_mismatch:release")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--verify-sample", type=Path)
    p.add_argument("--execution", type=Path)
    p.add_argument("--repository", type=Path, default=a.ROOT)
    p.add_argument("--source-pool", type=Path)
    p.add_argument("--source-pool-commit")
    p.add_argument("--source-pool-digest", type=Path)
    p.add_argument("--source-pool-digest-commit")
    p.add_argument("--ingestion-map", type=Path)
    p.add_argument("--ingestion-map-commit")
    p.add_argument("--ingestion-map-digest", type=Path)
    p.add_argument("--ingestion-map-digest-commit")
    p.add_argument("--release", type=Path)
    p.add_argument("--derivation", type=Path, action="append", default=[])
    p.add_argument("--pipeline-profile", type=Path)
    p.add_argument("--api")
    p.add_argument("--journal", type=Path)
    p.add_argument("--export-root", type=Path)
    p.add_argument("--export-exe")
    p.add_argument("--export-arg", action="append", default=[])
    p.add_argument("--poll-seconds", type=float, default=15.0)
    p.add_argument("--poll-timeout-seconds", type=float, default=24 * 3600.0)
    p.add_argument("--out", type=Path)
    return p


REQUIRED = ("source_pool", "ingestion_map", "release", "pipeline_profile", "api", "journal", "export_root",
            "export_exe", "out")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.verify_sample is not None:
            a.require(args.execution is not None, "arguments_invalid:--execution")
            verify_sample(args.verify_sample, args.execution)
            print("sample verified")
            return 0
        missing = [name for name in REQUIRED if getattr(args, name) is None]
        a.require(not missing, "arguments_invalid:" + ",".join(missing))
        data = execute(args)
    except a.S32Error as exc:
        print(f"refused {exc}", file=sys.stderr)
        return 2
    print(a.sha256_hex(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
