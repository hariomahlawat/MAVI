"""S3.2b-1 T9: the ingestion map and ``ingest_source_pool`` against a stubbed API (never a real MAVI host)."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

import artefacts as a
import ingest_source_pool as t9
import ingestion_map as im
import s32b_fixtures as f
import s32fixtures as s32
from t9_stub import StubApi

HERE = Path(__file__).resolve().parent
STAGE = "docs/qualification/stage3"
CONVENTION = b"# Synthetic S3.2 ingestion convention\n\nSynthetic fixture; not a real convention.\n"
CAMERAS = {"c0": "Europe/London", "c1": "America/New_York", "c2": "UTC"}


class World:
    """A committed synthetic pool, map and convention; passthrough derivations; a stub API."""

    def __init__(self, root: Path, *, map_edit=None, pool_edit=None, pool_digest: bool = False,
                 members: int = 6) -> None:
        self.root = root
        self.members = {f"cams/c{i % 3}/clip-{i:02d}.mp4": f"synthetic video {i}".encode() * 4 for i in range(members)}
        self.files = {**self.members, "meta/recording-times.csv": b"member,start\n"}
        self.release_document = f.release_document(self.files)
        self.release = f.write_release(root / "release.json", self.release_document)
        self.release_sha = f.release_sha256(self.release_document)
        self.repository = root / "repo"
        self.repository.mkdir()
        s32.git(self.repository, "init", "-q")
        (self.repository / STAGE).mkdir(parents=True)
        (self.repository / STAGE / "s3-2-ingestion-convention.md").write_bytes(CONVENTION)
        s32.git(self.repository, "add", "-A")
        s32.git(self.repository, "commit", "-q", "-m", "convention")
        self.convention_commit = s32.git(self.repository, "rev-parse", "HEAD")

        self.pool = {
            "schemaVersion": "vehicle-subclass-source-pool-v1", "releaseId": f.RELEASE_ID,
            "releaseRecordSha256": self.release_sha, "kind": "pilot",
            "selectionProcedure": {"id": "s3-2-source-pool-manual-v1"},
            "members": [{"member": name, "sha256": a.sha256_hex(data), "sizeBytes": len(data),
                         "probeSha256": a.sha256_hex(b"probe " + data), "sourceCamera": name.split("/")[1],
                         "inclusionReason": "camera diversity"} for name, data in sorted(self.members.items())],
        }
        if pool_edit:
            pool_edit(self.pool)
        self.pool_bytes = a.canonical_json(self.pool)
        self.pool_sha = a.sha256_hex(self.pool_bytes)
        self.map = self.default_map()
        if map_edit:
            map_edit(self.map, self)
        self.map_bytes = a.canonical_json(self.map)
        self.pool_digest = pool_digest
        pool_path = STAGE + ("/s3-2-source-pool.sha256" if pool_digest else "/s3-2-source-pool.json")
        (self.repository / pool_path).write_bytes(f"{self.pool_sha}\n".encode() if pool_digest else self.pool_bytes)
        (self.repository / STAGE / "s3-2-ingestion-map.json").write_bytes(self.map_bytes)
        s32.git(self.repository, "add", "-A")
        s32.git(self.repository, "commit", "-q", "-m", "pool and map")
        self.commit = s32.git(self.repository, "rev-parse", "HEAD")
        # The controlled-store copy of the pool when only its digest is committed.
        self.pool_file = root / "pool.json" if pool_digest else self.repository / pool_path
        if pool_digest:
            self.pool_file.write_bytes(self.pool_bytes)

        self.derivations = []
        for name, data in sorted(self.members.items()):
            directory = root / "derived" / name.replace("/", "_")
            directory.mkdir(parents=True)
            (directory / "video.mp4").write_bytes(data)
            s32.write_derivation(directory / "derivation-manifest.json", source=data, release_id=f.RELEASE_ID,
                                 release_record_sha=self.release_sha, member=name)
            self.derivations.append(directory)
        self.profile = root / "profile.json"
        self.profile.write_bytes(json.dumps(s32.PROFILE).encode())
        self.export_root = root / "exports"
        self.export_root.mkdir()
        self.journal = root / "journal.json"
        self.api = StubApi(root / "stub")
        self.tamper = ""

    def default_map(self) -> dict:
        cameras = [{"sourceCamera": c, "cameraCode": im.camera_code(c), "name": f"Synthetic camera {c}",
                    "timeZoneId": zone} for c, zone in CAMERAS.items()]
        members = []
        for i, name in enumerate(sorted(self.members)):
            if i % 2:
                recording = {"source": "release-metadata",
                             "evidence": {"releaseRecordSha256": self.release_sha, "member": "meta/recording-times.csv"}}
            else:
                recording = {"source": "development-convention",
                             "convention": {"sha256": a.sha256_hex(CONVENTION), "gitCommit": self.convention_commit,
                                            "gitPath": f"{STAGE}/s3-2-ingestion-convention.md"}}
            members.append({"member": name, "cameraCode": im.camera_code(name.split("/")[1]),
                            "recordingStartLocal": f"2026-01-0{1 + i % 7}T10:00:00", "recordingTime": recording})
        return {"schemaVersion": "vehicle-subclass-ingestion-map-v1", "sourcePoolSha256": self.pool_sha,
                "cameras": cameras, "members": members}

    def args(self, out: str = "execution.json", **over) -> list[str]:
        pool = (["--source-pool", str(self.pool_file), "--source-pool-digest",
                 str(self.repository / STAGE / "s3-2-source-pool.sha256"), "--source-pool-digest-commit", self.commit]
                if self.pool_digest else ["--source-pool", str(self.pool_file), "--source-pool-commit", self.commit])
        values = [
            "--repository", str(self.repository), *pool,
            "--ingestion-map", str(self.repository / STAGE / "s3-2-ingestion-map.json"),
            "--ingestion-map-commit", self.commit, "--release", str(self.release),
            *[x for d in self.derivations for x in ("--derivation", str(d))],
            "--pipeline-profile", str(self.profile), "--api", self.api.url, "--journal", str(self.journal),
            "--export-root", str(self.export_root), "--export-exe", sys.executable,
            f"--export-arg={HERE / 't9_stub_export.py'}", "--export-arg=--state",
            f"--export-arg={self.api.state.root / 'export-state.json'}", f"--export-arg=--tamper={self.tamper}",
            "--poll-seconds", "0", "--poll-timeout-seconds", "30", "--out", str(self.root / out)]
        return values

    def run(self, capsys, out: str = "execution.json") -> tuple[int, str]:
        code = t9.main(self.args(out))
        captured = capsys.readouterr()
        return code, captured.err + captured.out


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    w.api.close()


def refused(world, capsys, code, *, no_calls=False, out="execution.json"):
    status, text = world.run(capsys, out)
    assert status == 2 and f"refused {code}" in text, text
    assert not (world.root / out).exists()
    if no_calls:
        assert world.api.state.calls == []


# ---------------------------------------------------------------- happy path and record


def test_a_complete_execution_record(world, capsys, monkeypatch):
    # An unreachable proxy in the environment: T9 talks to the local API directly or not at all.
    for variable in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.setenv(variable, "http://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    status, text = world.run(capsys)
    assert status == 0, text
    data = (world.root / "execution.json").read_bytes()
    assert text.strip() == a.sha256_hex(data)
    record = json.loads(data)
    a.validate(record, "vehicle-subclass-t9-execution-v1", "unexpected")
    assert record["sourcePoolSha256"] == world.pool_sha
    assert record["sourcePoolBinding"] == {"gitCommit": world.commit, "gitPath": f"{STAGE}/s3-2-source-pool.json"}
    assert record["ingestionMapSha256"] == a.sha256_hex(world.map_bytes)
    assert record["releaseRecordSha256"] == world.release_sha
    assert record["measuredProfileSha256"] == a.sha256_hex(world.profile.read_bytes())
    # Camera and time fields come only from the map.
    assert [{k: c[k] for k in ("sourceCamera", "cameraCode", "name", "timeZoneId")} for c in record["cameras"]] == \
        sorted(world.map["cameras"], key=lambda c: c["cameraCode"])
    by_member = {m["member"]: m for m in world.map["members"]}
    for member in record["members"]:
        source = by_member[member["member"]]
        assert {k: member[k] for k in ("cameraCode", "recordingStartLocal", "recordingTime")} == \
            {k: source[k] for k in ("cameraCode", "recordingStartLocal", "recordingTime")}
        assert member["derivedSha256"] == a.sha256_hex(world.members[member["member"]])
    # No native-media pack identity and no local path.
    text = data.decode()
    for forbidden in ("ffmpeg", "ffprobe", "mediaTools", "manifestSha", str(world.root), world.root.as_posix(),
                      "127.0.0.1", "journal"):
        assert forbidden not in text
    imports = [c for c in world.api.state.calls if c == ("POST", "/api/videos/import")]
    assert len(imports) == 6


def test_the_record_is_deterministic_for_the_same_catalogue_ids(tmp_path, capsys):
    records = []
    for name in ("one", "two"):
        (tmp_path / name).mkdir()
        w = World(tmp_path / name)
        try:
            # The convention commit differs per repository; compare the API-derived parts.
            assert w.run(capsys)[0] == 0
            record = json.loads((w.root / "execution.json").read_bytes())
            records.append([{k: m[k] for k in ("member", "videoAssetId", "processingRunId", "exportSha256",
                                                 "attestationSha256", "derivationManifestSha256")}
                            for m in record["members"]])
        finally:
            w.api.close()
    assert records[0] == records[1]


def test_the_digest_file_binding(tmp_path, capsys):
    w = World(tmp_path, pool_digest=True)
    try:
        assert w.run(capsys)[0] == 0
        record = json.loads((w.root / "execution.json").read_bytes())
        assert record["sourcePoolBinding"]["gitPath"] == f"{STAGE}/s3-2-source-pool.sha256"
        w.pool_file.write_bytes(w.pool_bytes.replace(b"camera diversity", b"camera diversitx"))
        refused(w, capsys, "t9_source_pool:digest_mismatch", out="second.json")
    finally:
        w.api.close()


# ---------------------------------------------------------------- refusals before any API call


def _edit_map(edit):
    return lambda m, w: edit(m, w)


MAP_REFUSALS = [
    ("missing", lambda m, w: m["members"].pop(), "ingestion_map_invalid:missing_member"),
    ("extra", lambda m, w: m["members"].append({**m["members"][0], "member": "cams/c0/other.mp4"}),
     "ingestion_map_invalid:extra_member"),
    ("duplicate", lambda m, w: m["members"].append(copy.deepcopy(m["members"][0])), "ingestion_map_invalid:duplicate_member"),
    ("unknown camera", lambda m, w: m["members"][0].update(cameraCode="S32-NOPE"), "ingestion_map_invalid:unknown_camera"),
    ("member camera", lambda m, w: m["members"][0].update(cameraCode="S32-C1"), "ingestion_map_invalid:member_camera"),
    ("duplicate code", lambda m, w: m["cameras"].append({**m["cameras"][0], "sourceCamera": "c0!"}),
     "ingestion_map_invalid:duplicate_camera_code"),
    ("two cameras for one source", lambda m, w: m["cameras"].append({**m["cameras"][0], "cameraCode": "S32-C0-B"}),
     "ingestion_map_invalid:duplicate_source_camera"),
    ("code not derived", lambda m, w: [c.update(cameraCode="S32-CAM0") for c in m["cameras"] if c["sourceCamera"] == "c0"]
     and [e.update(cameraCode="S32-CAM0") for e in m["members"] if e["cameraCode"] == "S32-C0"],
     "ingestion_map_invalid:camera_code"),
    ("windows zone", lambda m, w: m["cameras"][0].update(timeZoneId="GMT Standard Time"), "ingestion_map_invalid:schema"),
    ("non-iana zone", lambda m, w: m["cameras"][0].update(timeZoneId="Mars/Olympus_Mons"), "ingestion_map_invalid:time_zone"),
    ("posix zone", lambda m, w: m["cameras"][0].update(timeZoneId="posixrules"), "ingestion_map_invalid:time_zone"),
    ("offset", lambda m, w: m["members"][0].update(recordingStartLocal="2026-01-01T10:00:00Z"), "ingestion_map_invalid:schema"),
    ("malformed", lambda m, w: m["members"][0].update(recordingStartLocal="2026-02-30T10:00:00"),
     "ingestion_map_invalid:recording_start_malformed"),
    ("nonexistent", lambda m, w: m["members"][0].update(recordingStartLocal="2026-03-29T01:30:00"),
     "ingestion_map_invalid:recording_start_nonexistent"),
    ("ambiguous", lambda m, w: m["members"][0].update(recordingStartLocal="2026-10-25T01:30:00"),
     "ingestion_map_invalid:recording_start_ambiguous"),
    ("pool hash", lambda m, w: m.update(sourcePoolSha256="0" * 64), "ingestion_map_invalid:source_pool"),
    ("release evidence release", lambda m, w: m["members"][1]["recordingTime"]["evidence"].update(releaseRecordSha256="0" * 64),
     "ingestion_map_invalid:release_evidence"),
    ("release evidence member", lambda m, w: m["members"][1]["recordingTime"]["evidence"].update(member="meta/none.csv"),
     "ingestion_map_invalid:release_evidence"),
    ("convention hash", lambda m, w: m["members"][0]["recordingTime"]["convention"].update(sha256="0" * 64),
     "ingestion_map_invalid:convention:differs_from_commit"),
    ("convention commit", lambda m, w: m["members"][0]["recordingTime"]["convention"].update(gitCommit="1" * 40),
     "ingestion_map_invalid:convention:not_in_commit"),
]


@pytest.mark.parametrize("name, edit, code", MAP_REFUSALS, ids=[r[0] for r in MAP_REFUSALS])
def test_map_refusals_happen_before_any_api_call(tmp_path, capsys, name, edit, code):
    w = World(tmp_path, map_edit=edit)
    try:
        refused(w, capsys, code, no_calls=True)
    finally:
        w.api.close()


@pytest.mark.parametrize("value", ["C:/Users/someone/camera", "from /home/someone/cam"])
def test_camera_name_with_a_local_path_is_refused_before_any_api_call(tmp_path, capsys, value):
    w = World(tmp_path, map_edit=lambda m, _: m["cameras"][0].update(name=value))
    try:
        refused(w, capsys, "ingestion_map_invalid:camera_name", no_calls=True)
    finally:
        w.api.close()


def test_source_camera_text_with_a_local_path_is_refused(world):
    document = copy.deepcopy(world.map)
    document["cameras"][0]["sourceCamera"] = "D:\\clips\\c0"
    with pytest.raises(a.S32Error) as raised:
        im.check(document, pool=world.pool, pool_sha256=world.pool_sha, release=f.rel.parse_release(
            copy.deepcopy(world.release_document)), release_sha256=world.release_sha, repository=world.repository)
    assert str(raised.value).startswith("ingestion_map_invalid:source_camera")


def test_a_non_loopback_api_is_refused_before_any_call(world, capsys):
    args = world.args()
    args[args.index("--api") + 1] = "http://192.0.2.10:5000"
    assert t9.main(args) == 2 and "refused t9_api_not_local" in capsys.readouterr().err
    assert world.api.state.calls == []


def test_a_redirect_is_refused_and_never_followed(world, capsys):
    """A 3xx from the loopback API never causes another request, even to another local server."""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading

    hits = []

    class Sentinel(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"[]")

        do_POST = do_GET

    sentinel = HTTPServer(("127.0.0.1", 0), Sentinel)
    thread = threading.Thread(target=sentinel.serve_forever, daemon=True)
    thread.start()
    try:
        world.api.state.redirect_to = f"http://127.0.0.1:{sentinel.server_address[1]}"
        refused(world, capsys, "t9_api_redirect_refused:307")
        assert hits == []
        assert len(world.api.state.calls) == 1  # the one refused request; nothing after it
    finally:
        sentinel.shutdown()
        sentinel.server_close()


@pytest.mark.parametrize("edit, code", [
    (lambda p: p.update(profileVersion="1.2.0"), "t9_profile_not_s32:profileVersion"),
    (lambda p: p.update(profileId="phase1-detection-tracking-v2"), "t9_profile_not_s32:profileId"),
    (lambda p: p.update(schemaVersion="1.1"), "t9_profile_not_s32:schemaVersion"),
    (lambda p: p.pop("vehicleSubclass"), "t9_profile_not_s32:vehicleSubclass"),
    (lambda p: p["vehicleSubclass"].update(vocabularyId="mavi-vehicle-subclass-v2"), "t9_profile_not_s32:vehicleSubclass"),
])
def test_only_the_s32_measurement_profile_is_accepted_before_any_api_call(world, capsys, edit, code):
    profile = copy.deepcopy(s32.PROFILE)
    edit(profile)
    world.profile.write_bytes(json.dumps(profile).encode())
    refused(world, capsys, code, no_calls=True)


def test_the_merged_stage3_profile_passes_the_identity_gate():
    shipped = a.ROOT / "src/vision/config/pipelines/phase1-detection-tracking-v1.json"
    t9.require_measurement_profile(shipped.read_bytes())


def test_an_import_recording_start_other_than_the_maps_is_refused(world, capsys):
    world.api.state.shift_start = True
    refused(world, capsys, "t9_import_refused:recording")


def test_a_journalled_asset_whose_recording_start_changed_is_refused(world, capsys):
    world.api.state.substitute_run = True
    refused(world, capsys, "t9_run_substituted")
    world.api.state.substitute_run = False
    world.api.state.videos[0]["recordingStartUtc"] = "1999-01-01T00:00:00+00:00"
    refused(world, capsys, "t9_asset_preexisting:journal")


@pytest.mark.parametrize("edit, code", [
    (lambda pool: pool["members"].append(copy.deepcopy(pool["members"][0])), "t9_source_pool:duplicate_member"),
    (lambda pool: pool["members"].append({**pool["members"][0], "member": "cams/c0/alias.mp4"}),
     "t9_source_pool:duplicate_content"),
])
def test_a_committed_pool_with_duplicate_rows_is_refused_before_any_api_call(tmp_path, capsys, edit, code):
    w = World(tmp_path, pool_edit=edit)
    try:
        refused(w, capsys, code, no_calls=True)
    finally:
        w.api.close()


def test_the_valid_map_mixes_release_metadata_and_the_convention(world):
    sources = {m["recordingTime"]["source"] for m in world.map["members"]}
    assert sources == {"release-metadata", "development-convention"}


def test_camera_codes_are_deterministic():
    assert im.camera_code("c0") == "S32-C0"
    assert im.camera_code("Cam 7/north_gate") == "S32-CAM-7-NORTH-GATE"
    assert im.camera_code("x" * 40) == "S32-" + "X" * 28 and len(im.camera_code("x" * 40)) == 32
    assert im.camera_code("c0!") == im.camera_code("c0?")  # a collision is a duplicate camera code


def test_binding_and_input_refusals_before_any_api_call(world, capsys):
    (world.repository / STAGE / "s3-2-ingestion-map.json").write_bytes(world.map_bytes + b" ")
    refused(world, capsys, "ingestion_map_invalid", no_calls=True)
    (world.repository / STAGE / "s3-2-ingestion-map.json").write_bytes(world.map_bytes)
    world.pool_file.write_bytes(a.canonical_json({**world.pool, "kind": "supplemental"}))
    refused(world, capsys, "t9_source_pool", no_calls=True)
    world.pool_file.write_bytes(world.pool_bytes)
    world.release.write_bytes(json.dumps(f.release_document({**world.files, "x.mp4": b"x"})).encode())
    refused(world, capsys, "t9_release_mismatch", no_calls=True)


@pytest.mark.parametrize("damage, code", [
    (lambda w: w.derivations.pop(), "t9_derivation_missing"),
    (lambda w: w.derivations.append(w.derivations[0]), "t9_derivation_duplicate"),
    (lambda w: (w.derivations[0] / "video.mp4").write_bytes(b"other bytes"), "t9_derivation_invalid:derivation_output_inconsistent"),
    (lambda w: s32.write_derivation(w.derivations[0] / "derivation-manifest.json", source=(w.derivations[0] / "video.mp4").read_bytes(),
                                    release_id=f.RELEASE_ID, release_record_sha="0" * 64,
                                    member=sorted(w.members)[0]), "t9_derivation_release"),
    (lambda w: s32.write_derivation(w.derivations[0] / "derivation-manifest.json", source=(w.derivations[0] / "video.mp4").read_bytes(),
                                    release_id=f.RELEASE_ID, release_record_sha=w.release_sha,
                                    member="cams/c0/not-in-pool.mp4"), "t9_derivation_not_in_pool"),
    (lambda w: (w.derivations[0] / "derivation-manifest.json").write_bytes(b'{"schemaVersion": "x"}'),
     "t9_derivation_invalid"),
])
def test_derivation_refusals_happen_before_any_api_call(world, capsys, damage, code):
    damage(world)
    refused(world, capsys, code, no_calls=True)


def test_a_derivation_of_different_member_bytes_is_refused(world, capsys):
    directory = world.derivations[0]
    other = b"a different derivation of the member"
    (directory / "video.mp4").write_bytes(other)
    s32.write_derivation(directory / "derivation-manifest.json", source=other, release_id=f.RELEASE_ID,
                         release_record_sha=world.release_sha, member=sorted(world.members)[0])
    refused(world, capsys, "t9_derivation_source", no_calls=True)


# ---------------------------------------------------------------- fresh catalogue and runs


def test_a_preexisting_camera_or_video_is_not_a_fresh_catalogue(world, capsys):
    world.api.state.cameras.append({"id": "01a0ffb2-0000-7000-8000-00000000ffff", "code": "OLD", "name": "Old",
                                    "timeZoneId": "UTC"})
    refused(world, capsys, "t9_catalogue_not_fresh:cameras")
    world.api.state.cameras.clear()
    # A member imported earlier as a different derivation (another SHA-256): hashes never prove freshness.
    world.api.state.videos.append({"id": "01a0ffb2-0000-7000-8000-00000000fffe", "cameraId": "x", "sha": "0" * 64,
                                   "upload": ""})
    refused(world, capsys, "t9_catalogue_not_fresh:videos")


def test_a_duplicate_answer_the_journal_does_not_explain_is_refused(world, capsys):
    # A listing that does not show the asset (defence in depth): the import answers video_duplicate.
    name = sorted(world.members)[0]
    world.api.state.hide_videos = True
    world.api.state.videos.append({"id": "01a0ffb2-0000-7000-8000-00000000fffd", "cameraId": "x",
                                   "sha": a.sha256_hex(world.members[name]), "upload": ""})
    refused(world, capsys, "t9_asset_preexisting")


def test_runs_are_never_taken_from_outside_the_journal(world, capsys):
    world.api.state.process_conflict = True
    refused(world, capsys, "t9_run_substituted:active")


def test_a_substituted_latest_run_is_refused(world, capsys):
    world.api.state.substitute_run = True
    refused(world, capsys, "t9_run_substituted")


def test_resume_within_the_same_instance_uses_the_journal(world, capsys):
    failing = a.sha256_hex(world.members[sorted(world.members)[3]])
    world.api.state.fail_run_for = {failing}
    refused(world, capsys, "t9_run_failed:Failed")
    journal = json.loads(world.journal.read_bytes())
    assert len(journal["cameras"]) == 3
    queued = {m: r["processingRunId"] for m, r in journal["members"].items() if r.get("processingRunId")}
    assert len(queued) == 4  # journalled before polling, including the failed one
    # The failed run is the journalled one; it is never replaced by another run silently.
    world.api.state.fail_run_for = set()
    refused(world, capsys, "t9_run_failed:Failed")
    calls_before = list(world.api.state.calls)
    assert calls_before.count(("POST", "/api/cameras")) == 3  # never re-created


def test_resume_completes_without_reimporting_or_requeueing(world, capsys):
    world.api.state.running_polls = 0
    world.api.state.substitute_run = True
    refused(world, capsys, "t9_run_substituted")
    world.api.state.substitute_run = False
    status, text = world.run(capsys)
    assert status == 0, text
    calls = world.api.state.calls
    assert calls.count(("POST", "/api/cameras")) == 3
    assert calls.count(("POST", "/api/videos/import")) == 6
    assert len([c for c in calls if c[0] == "POST" and c[1].endswith("/process")]) == 6


def test_a_camera_changed_since_the_journal_is_refused(world, capsys):
    world.api.state.substitute_run = True
    refused(world, capsys, "t9_run_substituted")
    world.api.state.substitute_run = False
    world.api.state.cameras[0]["name"] = "Renamed"
    refused(world, capsys, "t9_camera_mismatch")


def test_a_journal_of_another_instance_is_refused(world, capsys):
    world.journal.write_bytes(json.dumps({"schemaVersion": "s3-2-t9-journal-v1", "sourcePoolSha256": "0" * 64,
                                          "ingestionMapSha256": "0" * 64, "cameras": {}, "members": {}}).encode())
    refused(world, capsys, "t9_journal_mismatch")


# ---------------------------------------------------------------- exit checks


@pytest.mark.parametrize("tamper, code", [
    ("source", "t9_export_mismatch:source"),
    ("video", "t9_export_mismatch:video"),
    ("run", "t9_run_substituted:export"),
    ("fail", "t9_export_failed"),
    ("status", "export_invalid:schema"),
    ("camera", "t9_export_mismatch:camera"),
    ("profile", "t9_producer:attestation_pipeline_profile_mismatch"),
    ("producer", "t9_producer:attestation_producers_differ"),
])
def test_exit_checks(world, capsys, tamper, code):
    world.tamper = tamper
    refused(world, capsys, code)


def test_an_existing_output_is_refused_before_any_api_call(world, capsys):
    (world.root / "execution.json").write_bytes(b"x")
    status, text = world.run(capsys)
    assert status == 2 and "refused output_exists" in text and world.api.state.calls == []


# ---------------------------------------------------------------- sample verifier


@pytest.fixture
def executed(world, capsys):
    assert world.run(capsys)[0] == 0
    return world, json.loads((world.root / "execution.json").read_bytes())


def _sample(path: Path, record: dict, **over) -> Path:
    document = json.loads((a.ROOT / "contracts/examples/vehicle-subclass-sample-v1.example.json").read_bytes())
    document.update({"exportSha256s": sorted(m["exportSha256"] for m in record["members"]),
                     "derivationSha256s": sorted(m["derivationManifestSha256"] for m in record["members"]),
                     "releaseRecordSha256": record["releaseRecordSha256"]})
    document.update(over)
    path.write_bytes(a.canonical_json(document))
    return path


def test_the_sample_verifier_accepts_the_exact_sets(executed, capsys):
    world, record = executed
    sample = _sample(world.root / "sample.json", record)
    assert t9.main(["--verify-sample", str(sample), "--execution", str(world.root / "execution.json")]) == 0


@pytest.mark.parametrize("over, code", [
    (lambda r: {"exportSha256s": sorted(m["exportSha256"] for m in r["members"])[1:]}, "t9_sample_mismatch:exports"),
    (lambda r: {"derivationSha256s": sorted(m["derivationManifestSha256"] for m in r["members"])[:-1]},
     "t9_sample_mismatch:derivations"),
    (lambda r: {"releaseRecordSha256": "0" * 64}, "t9_sample_mismatch:release"),
])
def test_the_sample_verifier_refuses_any_other_set(executed, capsys, over, code):
    world, record = executed
    sample = _sample(world.root / "sample.json", record, **over(record))
    assert t9.main(["--verify-sample", str(sample), "--execution", str(world.root / "execution.json")]) == 2
    assert f"refused {code}" in capsys.readouterr().err
