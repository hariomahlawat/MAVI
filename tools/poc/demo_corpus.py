"""PoC S2 demo corpus: deterministic trims, SHA-256 manifests and a public-API import (Development only).

    python tools/poc/demo_corpus.py validate
    python tools/poc/demo_corpus.py trim   --root E:/MAVI-Controlled/PoC/Corpus --ffmpeg <ffmpeg.exe>
    python tools/poc/demo_corpus.py verify --root E:/MAVI-Controlled/PoC/Corpus
    python tools/poc/demo_corpus.py import --root E:/MAVI-Controlled/PoC/Corpus --api http://localhost:62153

The corpus definition (``tools/poc/demo-corpus/demo-corpus-v1.json``) is the single source of truth: which
acquired Commons original each clip comes from (bound by SHA-256), the trim window, the expected derivative
SHA-256, the demo camera and the Stage-1 scene geometry. Media bytes never enter Git: originals live in the
source-acquisition store under ``<root>/source-store`` and derivatives under ``<root>/derivatives``.

``import`` reproduces the demo state from a clean install through the public HTTP API only, in the order
camera -> import -> scene -> process, and is idempotent: an existing camera, asset or identical active scene
is reused when it matches the definition and refused when it does not. Nothing here creates a label,
annotation, count or ground truth (register B5), and nothing reads model output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

SCHEMA = "mavi-poc-demo-corpus-v1"
DEFAULT_DEFINITION = Path(__file__).resolve().parent / "demo-corpus" / "demo-corpus-v1.json"
KIT_LICENCES = ("cc0", "cc-by-2.0", "cc-by-2.5", "cc-by-3.0", "cc-by-4.0")
SCENE_CLASSES = ("junction", "gate", "car-park", "pedestrian", "lobby")
ZONE_KINDS = ("General", "Restricted", "Entrance", "Exit")
MIN_CLIPS, MAX_CLIPS = 8, 12
MIN_TRIM_S, MAX_TRIM_S = 60, 180
CLIP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
CAMERA_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,31}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
TERMINAL_FAILURES = ("Failed", "Cancelled")

# Pinned derivation, mirroring tools/benchmarks/prepare.py: libx264 single-threaded with bit-exact flags,
# so the same FFmpeg binary and original always give the same bytes. Audio, subtitles, data streams,
# container metadata and chapters are dropped (no speech enters the kit).
FFMPEG_ARGS = ["-nostdin", "-hide_banner", "-loglevel", "error", "-ss", "{start}", "-i", "{input}", "-t", "{duration}",
               "-map", "0:v:0", "-vf", "{filter}", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
               "-pix_fmt", "yuv420p", "-threads", "1", "-an", "-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1",
               "-fflags", "+bitexact", "-flags:v", "+bitexact", "-movflags", "+faststart", "-f", "mp4", "{output}"]
FFMPEG_TIMEOUT_S = 3600


class CorpusError(Exception):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise CorpusError(code)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------- definition and scene rules

def _point(value: Any, code: str) -> tuple[float, float]:
    require(isinstance(value, list) and len(value) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value), code)
    x, y = float(value[0]), float(value[1])
    require(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 and math.isfinite(x) and math.isfinite(y), code)
    return x, y


def _cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _segments_cross(p1, p2, q1, q2) -> bool:
    d1, d2, d3, d4 = _cross(q1, q2, p1), _cross(q1, q2, p2), _cross(p1, p2, q1), _cross(p1, p2, q2)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and 0 not in (d1, d2, d3, d4)


def polygon_problems(vertices: list[tuple[float, float]]) -> list[str]:
    """The server's zone rules (SceneRules): 3..64 vertices, positive area, no self-intersection."""
    problems = []
    if not 3 <= len(vertices) <= 64:
        problems.append("vertex_count")
        return problems
    area = 0.5 * abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(vertices, vertices[1:] + vertices[:1])))
    if area < 1e-6:
        problems.append("area")
    edges = list(zip(vertices, vertices[1:] + vertices[:1]))
    for i, (a, b) in enumerate(edges):
        for j in range(i + 2, len(edges)):
            if i == 0 and j == len(edges) - 1:
                continue  # adjacent through the closing edge
            if _segments_cross(a, b, *edges[j]):
                problems.append("self_intersection")
                return problems
    return problems


def validate_scene(scene: Any, code: str) -> None:
    require(isinstance(scene, dict) and set(scene) == {"zones", "tripLines"}, code)
    zones, lines = scene["zones"], scene["tripLines"]
    require(isinstance(zones, list) and isinstance(lines, list) and (zones or lines), f"{code}:empty")
    require(len(zones) <= 64 and len(lines) <= 64, f"{code}:count")
    names = set()
    for zone in zones:
        require(isinstance(zone, dict) and set(zone) == {"name", "kind", "vertices", "loiteringThresholdSeconds"}, f"{code}:zone")
        name = zone["name"]
        require(isinstance(name, str) and 0 < len(name.strip()) <= 64 and name not in names, f"{code}:zone_name")
        names.add(name)
        require(zone["kind"] in ZONE_KINDS, f"{code}:zone_kind:{name}")
        threshold = zone["loiteringThresholdSeconds"]
        require(threshold is None or (isinstance(threshold, int) and 1 <= threshold <= 86400), f"{code}:loitering:{name}")
        require(isinstance(zone["vertices"], list), f"{code}:vertices:{name}")
        vertices = [_point(v, f"{code}:vertex:{name}") for v in zone["vertices"]]
        problems = polygon_problems(vertices)
        require(not problems, f"{code}:polygon:{name}:{','.join(problems)}")
    for line in lines:
        require(isinstance(line, dict) and set(line) == {"name", "a", "b", "aToBLabel", "bToALabel"}, f"{code}:line")
        name = line["name"]
        require(isinstance(name, str) and 0 < len(name.strip()) <= 64 and name not in names, f"{code}:line_name")
        names.add(name)
        a, b = _point(line["a"], f"{code}:endpoint:{name}"), _point(line["b"], f"{code}:endpoint:{name}")
        require(math.dist(a, b) >= 0.005, f"{code}:line_length:{name}")
        for label in ("aToBLabel", "bToALabel"):
            require(isinstance(line[label], str) and 0 < len(line[label]) <= 32, f"{code}:line_label:{name}")


def validate_definition(document: Any) -> dict:
    require(isinstance(document, dict) and document.get("schemaVersion") == SCHEMA, "definition_schema")
    clips = document.get("clips")
    require(isinstance(clips, list) and MIN_CLIPS <= len(clips) <= MAX_CLIPS, "definition_clip_count")
    ids, codes, originals = set(), set(), set()
    for clip in clips:
        require(isinstance(clip, dict), "definition_clip")
        cid = clip.get("clipId")
        require(isinstance(cid, str) and CLIP_ID_RE.match(cid) is not None and cid not in ids, f"definition_clip_id:{cid}")
        ids.add(cid)
        require(clip.get("sceneClass") in SCENE_CLASSES, f"definition_scene_class:{cid}")
        source = clip.get("source")
        require(isinstance(source, dict), f"definition_source:{cid}")
        require(isinstance(source.get("fileTitle"), str) and source["fileTitle"].startswith("File:"), f"definition_source_title:{cid}")
        require(isinstance(source.get("pageRevisionId"), int) and SHA1_RE.match(str(source.get("fileSha1"))) is not None, f"definition_source_identity:{cid}")
        require(SHA256_RE.match(str(source.get("originalSha256"))) is not None, f"definition_original_sha256:{cid}")
        require(isinstance(source.get("storeRelativePath"), str) and source["storeRelativePath"].startswith("media/commons/")
                and ".." not in source["storeRelativePath"].split("/"), f"definition_store_path:{cid}")
        require(source["originalSha256"] not in originals, f"definition_original_duplicate:{cid}")
        originals.add(source["originalSha256"])
        require(source.get("licenceCode") in KIT_LICENCES and clip.get("kit") is True, f"definition_licence_not_kit:{cid}")
        trim = clip.get("trim")
        require(isinstance(trim, dict) and set(trim) == {"startSeconds", "durationSeconds", "maxWidth", "fps"}, f"definition_trim:{cid}")
        require(isinstance(trim["startSeconds"], (int, float)) and trim["startSeconds"] >= 0, f"definition_trim_start:{cid}")
        require(isinstance(trim["durationSeconds"], int) and MIN_TRIM_S <= trim["durationSeconds"] <= MAX_TRIM_S, f"definition_trim_duration:{cid}")
        require(trim["maxWidth"] in (1280, 1920), f"definition_trim_width:{cid}")
        require(trim["fps"] is None or trim["fps"] in (15, 25, 30), f"definition_trim_fps:{cid}")
        derivative = clip.get("derivative")
        require(isinstance(derivative, dict) and derivative.get("fileName") == f"{cid}.mp4", f"definition_derivative:{cid}")
        require(derivative.get("sha256") is None or SHA256_RE.match(derivative["sha256"]) is not None, f"definition_derivative_sha256:{cid}")
        camera = clip.get("camera")
        require(isinstance(camera, dict) and set(camera) == {"code", "name", "timeZoneId"}, f"definition_camera:{cid}")
        require(isinstance(camera["code"], str) and CAMERA_CODE_RE.match(camera["code"]) is not None and camera["code"] not in codes, f"definition_camera_code:{cid}")
        codes.add(camera["code"])
        require(isinstance(camera["name"], str) and 0 < len(camera["name"]) <= 128, f"definition_camera_name:{cid}")
        require(isinstance(camera["timeZoneId"], str) and 0 < len(camera["timeZoneId"]) <= 64, f"definition_camera_zone:{cid}")
        start = clip.get("recordingStartLocal")
        try:
            parsed = datetime.fromisoformat(start) if isinstance(start, str) else None
        except ValueError:
            parsed = None
        require(parsed is not None and parsed.tzinfo is None, f"definition_recording_start:{cid}")
        validate_scene(clip.get("scene"), f"definition_scene:{cid}")
    return document


def load_definition(path: Path) -> dict:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CorpusError("definition_unreadable") from exc
    return validate_definition(document)


# --------------------------------------------------------------------------- trims and manifests

def ffmpeg_argv(ffmpeg: Path, clip: dict, original: Path, output: Path) -> list[str]:
    trim = clip["trim"]
    scale = f"scale='min({trim['maxWidth']},iw)':-2"
    video_filter = scale if trim["fps"] is None else f"{scale},fps={trim['fps']}"
    rendered = {"{start}": f"{trim['startSeconds']:.3f}", "{input}": str(original), "{duration}": str(trim["durationSeconds"]),
                "{filter}": video_filter, "{output}": str(output)}
    return [str(ffmpeg), *[rendered.get(part, part) for part in FFMPEG_ARGS]]


def _original_path(root: Path, clip: dict) -> Path:
    return root / "source-store" / Path(clip["source"]["storeRelativePath"])


def write_manifest(path: Path, rows: list[tuple[str, str]]) -> None:
    """SHA256SUMS format (``<sha256> *<relative path>``), sorted, LF."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(f"{digest} *{name}\n" for name, digest in sorted(rows))
    path.write_bytes(text.encode("ascii"))


def trim(definition: dict, root: Path, ffmpeg: Path, run: Callable[..., Any] = subprocess.run) -> dict:
    """Derive every clip; refuses a changed original and a derivative that differs from the recorded SHA-256."""
    ffmpeg = Path(ffmpeg)
    require(ffmpeg.is_file(), "ffmpeg_missing")
    ffmpeg_sha = sha256_file(ffmpeg)
    version = run([str(ffmpeg), "-hide_banner", "-version"], capture_output=True, check=False, timeout=60)
    require(version.returncode == 0, "ffmpeg_version_failed")
    version_line = version.stdout.decode("utf-8", "replace").splitlines()[0]
    out_dir = root / "derivatives"
    out_dir.mkdir(parents=True, exist_ok=True)
    originals, derivatives, records = [], [], []
    for clip in definition["clips"]:
        original = _original_path(root, clip)
        require(original.is_file(), f"original_missing:{clip['clipId']}")
        require(sha256_file(original) == clip["source"]["originalSha256"], f"original_changed:{clip['clipId']}")
        target = out_dir / clip["derivative"]["fileName"]
        partial = target.with_name(target.name + ".partial.mp4")
        if partial.exists():
            partial.unlink()
        argv = ffmpeg_argv(ffmpeg, clip, original, partial)
        require(sha256_file(ffmpeg) == ffmpeg_sha, "ffmpeg_changed")
        result = run(argv, capture_output=True, check=False, timeout=FFMPEG_TIMEOUT_S)
        require(result.returncode == 0 and partial.is_file(), f"ffmpeg_failed:{clip['clipId']}:{result.returncode}")
        digest = sha256_file(partial)
        expected = clip["derivative"]["sha256"]
        if expected is not None and digest != expected:
            partial.unlink()
            raise CorpusError(f"derivative_not_reproduced:{clip['clipId']}")
        if target.exists():
            require(sha256_file(target) == digest, f"derivative_differs_on_disk:{clip['clipId']}")
            partial.unlink()
        else:
            partial.replace(target)
        originals.append((f"source-store/{clip['source']['storeRelativePath']}", clip["source"]["originalSha256"]))
        derivatives.append((f"derivatives/{target.name}", digest))
        records.append({"clipId": clip["clipId"], "derivativeSha256": digest, "expectedSha256": expected,
                        "reproduced": expected == digest if expected else None,
                        "argvTemplate": FFMPEG_ARGS, "trim": clip["trim"]})
    write_manifest(root / "manifests" / "originals.sha256", originals)
    write_manifest(root / "manifests" / "derivatives.sha256", derivatives)
    record = {"schemaVersion": "mavi-poc-demo-corpus-derivation-v1", "ffmpegSha256": ffmpeg_sha, "ffmpegVersion": version_line,
              "clips": records}
    (root / "manifests" / "derivation-record.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return record


def verify_derivatives(definition: dict, root: Path) -> list[str]:
    """Offline check of every derivative (all a kit or demo host holds) against the definition."""
    problems = []
    for clip in definition["clips"]:
        cid = clip["clipId"]
        derivative = root / "derivatives" / clip["derivative"]["fileName"]
        if clip["derivative"]["sha256"] is None:
            problems.append(f"{cid}: derivative SHA-256 not recorded")
        elif not derivative.is_file():
            problems.append(f"{cid}: derivative missing")
        elif sha256_file(derivative) != clip["derivative"]["sha256"]:
            problems.append(f"{cid}: derivative SHA-256 differs")
    return problems


def verify(definition: dict, root: Path) -> list[str]:
    """Offline check of every retained original and derivative against the definition."""
    problems = []
    for clip in definition["clips"]:
        original = _original_path(root, clip)
        if not original.is_file():
            problems.append(f"{clip['clipId']}: original missing")
        elif sha256_file(original) != clip["source"]["originalSha256"]:
            problems.append(f"{clip['clipId']}: original SHA-256 differs")
    return problems + verify_derivatives(definition, root)


# --------------------------------------------------------------------------- public-API import

class Multipart:
    def __init__(self, fields: dict[str, str], file_field: str, file_path: Path):
        self.boundary = uuid.uuid4().hex
        self.fields, self.file_field, self.file_path = fields, file_field, Path(file_path)

    def body(self) -> bytes:
        parts = []
        for name, value in self.fields.items():
            parts.append(f'--{self.boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8"))
        parts.append((f'--{self.boundary}\r\nContent-Disposition: form-data; name="{self.file_field}"; '
                      f'filename="{self.file_path.name}"\r\nContent-Type: video/mp4\r\n\r\n').encode("utf-8"))
        parts.append(self.file_path.read_bytes())
        parts.append(f"\r\n--{self.boundary}--\r\n".encode("ascii"))
        return b"".join(parts)

    @property
    def content_type(self) -> str:
        return f"multipart/form-data; boundary={self.boundary}"


class Api:
    """Minimal JSON client for the local MAVI API (no credentials; Development has no authentication)."""

    def __init__(self, base: str, timeout: float = 600.0):
        require(re.match(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?/?$", base) is not None, "api_not_local")
        self.base, self.timeout = base.rstrip("/"), timeout

    def call(self, method: str, path: str, json_body: Any = None, multipart: Multipart | None = None) -> tuple[int, Any]:
        headers = {"Accept": "application/json"}
        data = None
        if multipart is not None:
            data, headers["Content-Type"] = multipart.body(), multipart.content_type
        elif json_body is not None:
            data, headers["Content-Type"] = json.dumps(json_body).encode("utf-8"), "application/json"
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - local API only
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
        try:
            return status, json.loads(raw.decode("utf-8")) if raw else None
        except ValueError:
            return status, None


def _problem(body: Any) -> str:
    return str(body.get("code")) if isinstance(body, dict) else "-"


def scene_request(scene: dict, expected_revision: int, note: str) -> dict:
    point = lambda xy: {"x": xy[0], "y": xy[1]}  # noqa: E731
    return {
        "expectedRevisionNumber": expected_revision, "note": note,
        "referenceFrameVideoAssetId": None, "referenceFrameOffsetMs": None,
        "zones": [{"zoneId": None, "name": z["name"], "kind": z["kind"], "enabled": True,
                   "vertices": [point(v) for v in z["vertices"]], "loiteringThresholdSeconds": z["loiteringThresholdSeconds"]}
                  for z in scene["zones"]],
        "tripLines": [{"lineId": None, "name": t["name"], "enabled": True, "a": point(t["a"]), "b": point(t["b"]),
                       "directed": True, "aToBLabel": t["aToBLabel"], "bToALabel": t["bToALabel"]} for t in scene["tripLines"]],
    }


def _geometry(zones: list, lines: list) -> Any:
    """Comparable geometry of a scene revision (server ids and timestamps ignored)."""
    pt = lambda p: (round(float(p["x"]), 6), round(float(p["y"]), 6)) if isinstance(p, dict) else (round(float(p[0]), 6), round(float(p[1]), 6))  # noqa: E731
    return (sorted((z["name"], z["kind"], tuple(pt(v) for v in z["vertices"]), z.get("loiteringThresholdSeconds")) for z in zones),
            sorted((t["name"], pt(t["a"]), pt(t["b"]), bool(t.get("directed")), t.get("aToBLabel"), t.get("bToALabel")) for t in lines))


def ensure_camera(api: Api, camera: dict) -> str:
    status, cameras = api.call("GET", "/api/cameras")
    require(status == 200 and isinstance(cameras, list), f"api_cameras:{status}")
    for existing in cameras:
        if isinstance(existing, dict) and existing.get("code") == camera["code"]:
            require(existing.get("name") == camera["name"] and existing.get("timeZoneId") == camera["timeZoneId"],
                    f"camera_mismatch:{camera['code']}")
            return existing["id"]
    status, created = api.call("POST", "/api/cameras", json_body=camera)
    require(status == 201 and isinstance(created, dict) and created.get("id"), f"camera_create:{status}:{_problem(created)}")
    return created["id"]


def ensure_asset(api: Api, camera_id: str, clip: dict, path: Path) -> dict:
    status, created = api.call("POST", "/api/videos/import", multipart=Multipart(
        {"cameraId": camera_id, "recordingStartLocal": clip["recordingStartLocal"]}, "file", path))
    if status == 409 and _problem(created) == "video_duplicate":
        status, existing = api.call("GET", f"/api/videos/{created.get('videoAssetId')}")
        require(status == 200 and isinstance(existing, dict) and existing.get("cameraId") == camera_id,
                f"asset_preexisting_elsewhere:{clip['clipId']}")
        return existing
    require(status == 201 and isinstance(created, dict) and created.get("id"), f"import_refused:{clip['clipId']}:{status}:{_problem(created)}")
    return created


def ensure_scene(api: Api, camera_id: str, clip: dict) -> int:
    status, current = api.call("GET", f"/api/cameras/{camera_id}/scene")
    require(status == 200 and isinstance(current, dict), f"api_scene:{status}")
    active = current.get("activeRevision")
    wanted = _geometry(clip["scene"]["zones"], [dict(t, directed=True) for t in clip["scene"]["tripLines"]])
    if isinstance(active, dict) and _geometry(active.get("zones") or [], active.get("tripLines") or []) == wanted:
        return int(active["revisionNumber"])
    expected = int(active["revisionNumber"]) if isinstance(active, dict) else 0
    status, saved = api.call("PUT", f"/api/cameras/{camera_id}/scene",
                             json_body=scene_request(clip["scene"], expected, f"PoC demo corpus v1: {clip['clipId']}"))
    require(status in (200, 201) and isinstance(saved, dict), f"scene_refused:{clip['clipId']}:{status}:{_problem(saved)}")
    return int(saved["revisionNumber"])


def ensure_processed(api: Api, camera_id: str, asset: dict, clip: dict, poll_s: float, timeout_s: float,
                     clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> dict:
    """Queues processing unless a run already exists, then waits for the run and its scene analysis.

    A run that completed before the active scene revision existed is not re-analysed automatically,
    so its analysis is requested explicitly (``POST /api/cameras/{id}/scene/analyses``)."""
    asset_id = asset["id"]
    reanalysed = False
    status, state = api.call("GET", f"/api/videos/{asset_id}/processing")
    require(status == 200 and isinstance(state, dict), f"api_processing:{status}")
    latest = state.get("latestRun")
    if not isinstance(latest, dict) or latest.get("status") in TERMINAL_FAILURES:
        status, queued = api.call("POST", f"/api/videos/{asset_id}/process")
        require(status == 202 and isinstance(queued, dict), f"process_refused:{clip['clipId']}:{status}:{_problem(queued)}")
    deadline = clock() + timeout_s
    while True:
        status, state = api.call("GET", f"/api/videos/{asset_id}/processing")
        require(status == 200 and isinstance(state, dict), f"api_processing:{status}")
        latest = state.get("latestRun") or {}
        run_status = latest.get("status")
        require(run_status not in TERMINAL_FAILURES, f"run_failed:{clip['clipId']}:{run_status}:{latest.get('failureCode')}")
        readiness = latest.get("analyticsReadiness")
        if run_status == "Completed" and readiness in ("Ready", "Failed"):
            require(readiness == "Ready", f"analytics_failed:{clip['clipId']}")
            return latest
        if run_status == "Completed" and readiness in ("NotConfigured", "Stale") and not reanalysed:
            status, body = api.call("POST", f"/api/cameras/{camera_id}/scene/analyses", json_body={"scope": "latestRuns"})
            require(status == 202, f"analysis_refused:{clip['clipId']}:{status}:{_problem(body)}")
            reanalysed = True
        require(clock() < deadline, f"run_timeout:{clip['clipId']}:{run_status}:{latest.get('analyticsReadiness')}")
        sleep(poll_s)


def import_corpus(definition: dict, root: Path, api: Api, process: bool = True, poll_s: float = 10.0,
                  timeout_s: float = 7200.0, only: set[str] | None = None, log: Callable[[str], None] = print) -> list[dict]:
    problems = verify_derivatives(definition, root)
    require(not problems, "derivatives_not_verified:" + "; ".join(problems))
    results = []
    for clip in definition["clips"]:
        if only and clip["clipId"] not in only:
            continue
        camera_id = ensure_camera(api, clip["camera"])
        asset = ensure_asset(api, camera_id, clip, root / "derivatives" / clip["derivative"]["fileName"])
        revision = ensure_scene(api, camera_id, clip)
        row = {"clipId": clip["clipId"], "cameraId": camera_id, "videoAssetId": asset["id"], "sceneRevision": revision}
        log(f"{clip['clipId']}: camera {clip['camera']['code']} asset {asset['id']} scene r{revision}")
        if process:
            latest = ensure_processed(api, camera_id, asset, clip, poll_s, timeout_s)
            row.update(processingRunId=latest.get("processingRunId"), tracksCreated=latest.get("tracksCreated"),
                       analyticsReadiness=latest.get("analyticsReadiness"))
            log(f"{clip['clipId']}: run {latest.get('processingRunId')} Completed, analytics {latest.get('analyticsReadiness')}")
        results.append(row)
    return results


# --------------------------------------------------------------------------- command line

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="demo_corpus", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--definition", type=Path, default=DEFAULT_DEFINITION)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    t = sub.add_parser("trim")
    t.add_argument("--root", type=Path, required=True)
    t.add_argument("--ffmpeg", type=Path, required=True)
    v = sub.add_parser("verify")
    v.add_argument("--root", type=Path, required=True)
    i = sub.add_parser("import")
    i.add_argument("--root", type=Path, required=True)
    i.add_argument("--api", default="http://localhost:62153")
    i.add_argument("--no-process", action="store_true")
    i.add_argument("--clip", action="append", help="limit to these clip ids (repeatable)")
    i.add_argument("--timeout-seconds", type=float, default=7200.0)
    args = parser.parse_args(argv)
    try:
        definition = load_definition(args.definition)
        if args.command == "validate":
            print(json.dumps({"clips": len(definition["clips"]), "valid": True}))
            return 0
        if args.command == "trim":
            record = trim(definition, args.root, args.ffmpeg)
            print(json.dumps([{k: c[k] for k in ("clipId", "derivativeSha256", "reproduced")} for c in record["clips"]], indent=2))
            return 0
        if args.command == "verify":
            problems = verify(definition, args.root)
            print(json.dumps({"problems": problems}, indent=2))
            return 1 if problems else 0
        results = import_corpus(definition, args.root, Api(args.api), not args.no_process,
                                timeout_s=args.timeout_seconds, only=set(args.clip) if args.clip else None)
        print(json.dumps(results, indent=2))
        return 0
    except CorpusError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
