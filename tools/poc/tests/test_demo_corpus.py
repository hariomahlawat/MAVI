"""Offline tests for the PoC S2 demo-corpus tool: definition and scene rules, trims, import order and idempotence."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import demo_corpus as dc  # noqa: E402


def _clip(index: int) -> dict:
    cid = f"clip-{index:02d}"
    return {
        "clipId": cid, "sceneClass": "junction", "kit": True,
        "source": {"fileTitle": f"File:Clip {index}.webm", "pageId": 1000 + index, "pageRevisionId": 5000 + index,
                   "fileSha1": f"{index:040x}", "originalSha256": hashlib.sha256(f"original-{index}".encode()).hexdigest(),
                   "storeRelativePath": f"media/commons/{1000 + index}/{index:040x}/Clip_{index}.webm", "licenceCode": "cc-by-4.0"},
        "trim": {"startSeconds": 0, "durationSeconds": 60, "maxWidth": 1920, "fps": None},
        "derivative": {"fileName": f"{cid}.mp4", "sha256": None},
        "camera": {"code": f"POC-{index:02d}", "name": f"Demo {index}", "timeZoneId": "Asia/Kolkata"},
        "recordingStartLocal": "2026-10-01T09:00:00",
        "scene": {"zones": [{"name": "Zone A", "kind": "General", "vertices": [[0.1, 0.1], [0.5, 0.1], [0.5, 0.5], [0.1, 0.5]],
                             "loiteringThresholdSeconds": 120}],
                  "tripLines": [{"name": "Gate", "a": [0.2, 0.8], "b": [0.8, 0.8], "aToBLabel": "In", "bToALabel": "Out"}]},
    }


def _definition(count: int = 8) -> dict:
    return {"schemaVersion": dc.SCHEMA, "clips": [_clip(i) for i in range(1, count + 1)]}


def test_committed_definition_is_valid():
    dc.load_definition(dc.DEFAULT_DEFINITION)


def test_committed_definition_binds_every_derivative_and_kit_licence():
    definition = dc.load_definition(dc.DEFAULT_DEFINITION)
    for clip in definition["clips"]:
        assert clip["derivative"]["sha256"] is not None, clip["clipId"]
        assert clip["source"]["licenceCode"] in dc.KIT_LICENCES


def test_definition_accepts_minimal_valid():
    dc.validate_definition(_definition())


@pytest.mark.parametrize("count", [7, 13])
def test_definition_clip_count_bounds(count):
    with pytest.raises(dc.CorpusError, match="definition_clip_count"):
        dc.validate_definition(_definition(count))


@pytest.mark.parametrize("licence", ["cc-by-sa-4.0", "pd", "cc-by-nc-4.0", None])
def test_non_kit_licence_refused(licence):
    document = _definition()
    document["clips"][0]["source"]["licenceCode"] = licence
    with pytest.raises(dc.CorpusError, match="definition_licence_not_kit"):
        dc.validate_definition(document)


def test_duplicate_camera_code_refused():
    document = _definition()
    document["clips"][1]["camera"]["code"] = document["clips"][0]["camera"]["code"]
    with pytest.raises(dc.CorpusError, match="definition_camera_code"):
        dc.validate_definition(document)


@pytest.mark.parametrize("duration", [59, 181])
def test_trim_window_bounds(duration):
    document = _definition()
    document["clips"][0]["trim"]["durationSeconds"] = duration
    with pytest.raises(dc.CorpusError, match="definition_trim_duration"):
        dc.validate_definition(document)


def test_store_path_traversal_refused():
    document = _definition()
    document["clips"][0]["source"]["storeRelativePath"] = "media/commons/../../escape.webm"
    with pytest.raises(dc.CorpusError, match="definition_store_path"):
        dc.validate_definition(document)


def test_polygon_rules():
    assert dc.polygon_problems([(0, 0), (1, 0), (1, 1), (0, 1)]) == []
    assert "self_intersection" in dc.polygon_problems([(0, 0), (1, 1), (1, 0), (0, 1)])
    assert dc.polygon_problems([(0, 0), (1, 0)]) == ["vertex_count"]
    assert "area" in dc.polygon_problems([(0, 0), (0.5, 0.5), (1, 1)])


@pytest.mark.parametrize("mutate, code", [
    (lambda s: s["zones"][0].__setitem__("kind", "restricted"), "zone_kind"),
    (lambda s: s["zones"][0]["vertices"].__setitem__(0, [1.2, 0.1]), "vertex"),
    (lambda s: s["tripLines"][0].__setitem__("b", [0.201, 0.8]), "line_length"),
    (lambda s: s["tripLines"][0].__setitem__("name", "Zone A"), "line_name"),
    (lambda s: s["zones"][0].__setitem__("loiteringThresholdSeconds", 0), "loitering"),
    (lambda s: s["tripLines"][0].__setitem__("aToBLabel", "x" * 33), "line_label"),
])
def test_scene_rules_mirror_server(mutate, code):
    document = _definition()
    mutate(document["clips"][0]["scene"])
    with pytest.raises(dc.CorpusError, match=code):
        dc.validate_definition(document)


def test_ffmpeg_argv_is_pinned_and_deterministic(tmp_path):
    clip = _clip(1)
    clip["trim"].update(startSeconds=12.5, fps=25)
    argv = dc.ffmpeg_argv(Path("ffmpeg.exe"), clip, tmp_path / "in.webm", tmp_path / "out.mp4")
    assert argv[argv.index("-ss") + 1] == "12.500"
    assert argv[argv.index("-t") + 1] == "60"
    assert argv[argv.index("-vf") + 1] == "scale='min(1920,iw)':-2,fps=25"
    for flag in ("-threads", "-an", "+bitexact", "-map_metadata"):
        assert flag in argv
    assert argv[argv.index("-threads") + 1] == "1"


def _write_original(root: Path, clip: dict) -> None:
    path = root / "source-store" / clip["source"]["storeRelativePath"]
    path.parent.mkdir(parents=True, exist_ok=True)
    data = f"bytes-{clip['clipId']}".encode()
    path.write_bytes(data)
    clip["source"]["originalSha256"] = hashlib.sha256(data).hexdigest()


def _fake_run(calls):
    def run(argv, **_kwargs):
        calls.append(argv)
        if "-version" in argv:
            return SimpleNamespace(returncode=0, stdout=b"ffmpeg version 9.0.1-test\n")
        Path(argv[-1]).write_bytes(b"derived:" + Path(argv[argv.index("-i") + 1]).read_bytes())
        return SimpleNamespace(returncode=0, stdout=b"")
    return run


def test_trim_writes_derivatives_and_manifests(tmp_path):
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"ffmpeg")
    definition = _definition()
    for clip in definition["clips"]:
        _write_original(tmp_path, clip)
    calls = []
    record = dc.trim(definition, tmp_path, ffmpeg, run=_fake_run(calls))
    assert len(record["clips"]) == 8 and record["ffmpegVersion"] == "ffmpeg version 9.0.1-test"
    sums = (tmp_path / "manifests" / "derivatives.sha256").read_text().splitlines()
    assert len(sums) == 8 and sums[0].endswith("*derivatives/clip-01.mp4")
    for clip, row in zip(definition["clips"], record["clips"]):
        clip["derivative"]["sha256"] = row["derivativeSha256"]
    assert dc.verify(definition, tmp_path) == []
    # A rerun reproduces the recorded hashes.
    again = dc.trim(definition, tmp_path, ffmpeg, run=_fake_run([]))
    assert all(row["reproduced"] for row in again["clips"])


def test_trim_refuses_changed_original_and_unreproduced_derivative(tmp_path):
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"ffmpeg")
    definition = _definition()
    for clip in definition["clips"]:
        _write_original(tmp_path, clip)
    changed = copy.deepcopy(definition)
    changed["clips"][0]["source"]["originalSha256"] = "0" * 64
    with pytest.raises(dc.CorpusError, match="original_changed:clip-01"):
        dc.trim(changed, tmp_path, ffmpeg, run=_fake_run([]))
    definition["clips"][0]["derivative"]["sha256"] = "f" * 64
    with pytest.raises(dc.CorpusError, match="derivative_not_reproduced:clip-01"):
        dc.trim(definition, tmp_path, ffmpeg, run=_fake_run([]))
    assert not (tmp_path / "derivatives" / "clip-01.mp4").exists()


class FakeApi:
    """In-memory stand-in for the MAVI endpoints the importer calls."""

    def __init__(self):
        self.calls, self.cameras, self.videos, self.scenes, self.runs = [], [], {}, {}, {}

    def call(self, method, path, json_body=None, multipart=None):
        self.calls.append((method, path))
        if (method, path) == ("GET", "/api/cameras"):
            return 200, list(self.cameras)
        if (method, path) == ("POST", "/api/cameras"):
            camera = dict(json_body, id=f"cam-{len(self.cameras)}")
            self.cameras.append(camera)
            return 201, camera
        if (method, path) == ("POST", "/api/videos/import"):
            name = multipart.file_path.name
            if name in self.videos:
                return 409, {"code": "video_duplicate", "videoAssetId": self.videos[name]["id"]}
            video = {"id": f"vid-{name}", "cameraId": multipart.fields["cameraId"]}
            self.videos[name] = video
            return 201, video
        parts = path.strip("/").split("/")
        if method == "GET" and parts[:2] == ["api", "videos"] and len(parts) == 3:
            return 200, next(v for v in self.videos.values() if v["id"] == parts[2])
        if parts[:2] == ["api", "cameras"] and parts[3:] == ["scene"]:
            camera = parts[2]
            if method == "GET":
                return 200, {"cameraId": camera, "activeRevision": self.scenes.get(camera)}
            current = self.scenes.get(camera)
            if json_body["expectedRevisionNumber"] != (current["revisionNumber"] if current else 0):
                return 409, {"code": "SceneRevisionConflict"}
            revision = {"revisionNumber": json_body["expectedRevisionNumber"] + 1,
                        "zones": json_body["zones"], "tripLines": json_body["tripLines"]}
            self.scenes[camera] = revision
            return 201, revision
        if parts[:2] == ["api", "videos"] and parts[3:] == ["process"]:
            self.runs[parts[2]] = {"processingRunId": f"run-{parts[2]}", "status": "Completed", "analyticsReadiness": "Ready", "tracksCreated": 3}
            return 202, {"processingRunId": f"run-{parts[2]}"}
        if parts[:2] == ["api", "videos"] and parts[3:] == ["processing"]:
            return 200, {"latestRun": self.runs.get(parts[2])}
        raise AssertionError(f"unexpected call {method} {path}")


def _imported_root(tmp_path: Path, definition: dict) -> Path:
    for clip in definition["clips"]:
        path = tmp_path / "derivatives" / clip["derivative"]["fileName"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(clip["clipId"].encode())
        clip["derivative"]["sha256"] = hashlib.sha256(clip["clipId"].encode()).hexdigest()
    return tmp_path


def test_import_order_and_idempotence(tmp_path):
    definition = _definition()
    root = _imported_root(tmp_path, definition)
    api = FakeApi()
    results = dc.import_corpus(definition, root, api, poll_s=0, log=lambda _m: None)
    assert [r["sceneRevision"] for r in results] == [1] * 8
    first = [c for c in api.calls if c[0] != "GET"][:4]
    assert [c[1] for c in first] == ["/api/cameras", "/api/videos/import", "/api/cameras/cam-0/scene", "/api/videos/vid-clip-01.mp4/process"]
    # Second run: same cameras, duplicate assets reused, identical scenes not re-saved, completed runs not re-queued.
    api.calls.clear()
    again = dc.import_corpus(definition, root, api, poll_s=0, log=lambda _m: None)
    assert [r["videoAssetId"] for r in again] == [r["videoAssetId"] for r in results]
    assert [r["sceneRevision"] for r in again] == [1] * 8
    assert not any(m == "PUT" or p.endswith("/process") or p == "/api/cameras" and m == "POST" for m, p in api.calls)


def test_import_refuses_mismatched_camera_and_unverified_derivative(tmp_path):
    definition = _definition()
    root = _imported_root(tmp_path, definition)
    api = FakeApi()
    api.cameras.append({"id": "x", "code": "POC-01", "name": "Something else", "timeZoneId": "Asia/Kolkata"})
    with pytest.raises(dc.CorpusError, match="camera_mismatch:POC-01"):
        dc.import_corpus(definition, root, api, poll_s=0, log=lambda _m: None)
    (root / "derivatives" / "clip-02.mp4").write_bytes(b"tampered")
    with pytest.raises(dc.CorpusError, match="derivatives_not_verified"):
        dc.import_corpus(definition, root, FakeApi(), poll_s=0, log=lambda _m: None)


def test_failed_run_is_reported(tmp_path):
    definition = _definition()
    root = _imported_root(tmp_path, definition)
    api = FakeApi()
    original = api.call

    def failing(method, path, json_body=None, multipart=None):
        status, body = original(method, path, json_body, multipart)
        if path.endswith("/process"):
            api.runs[path.split("/")[3]].update(status="Failed", failureCode="worker_failed")
        return status, body

    api.call = failing
    with pytest.raises(dc.CorpusError, match="run_failed:clip-01:Failed:worker_failed"):
        dc.import_corpus(definition, root, api, poll_s=0, log=lambda _m: None)


def test_api_must_be_local():
    with pytest.raises(dc.CorpusError, match="api_not_local"):
        dc.Api("https://example.org")
    dc.Api("http://localhost:62153")


def test_committed_definition_round_trips_as_json():
    text = dc.DEFAULT_DEFINITION.read_text(encoding="utf-8")
    assert json.loads(text)["schemaVersion"] == dc.SCHEMA
