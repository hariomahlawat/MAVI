"""S3.2b-1 T8: MP4 derivation (``derive_mp4``) against synthetic media and synthetic release records."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import artefacts as a
import derive_mp4 as d
import s32b_fixtures as f
import s32fixtures as s32

LIMIT = 3 * 1024 ** 3
STORE_FILES = {"videos/a.mp4": "h264.mp4", "videos/b.mkv": "h264.mkv", "videos/c.mkv": "mpeg4.mkv",
               "videos/q.mov": "quicktime.mov", "videos/audio.mp4": "audio-only.mp4", "videos/two.mp4": "two-video.mp4"}


class Setup:
    def __init__(self, root: Path, pack: Path, media: dict[str, bytes], det=..., excluded=()) -> None:
        self.root, self.pack = root, pack
        self.members = {path: media[name] for path, name in STORE_FILES.items()}
        self.store = f.write_store(root / "store", self.members)
        self.document = f.release_document(self.members, det=det, excluded=excluded)
        self.release = f.write_release(root / "release.json", self.document)

    def derive(self, member: str, mode: str, out: str = "out", limit: int = LIMIT, **over) -> bytes:
        kwargs = dict(media_tools_dir=self.pack, release_path=self.release, release_root=self.store, member=member,
                      mode=mode, max_import_bytes=limit, out=self.root / out)
        kwargs.update(over)
        return d.derive(**kwargs)


@pytest.fixture
def setup(tmp_path, media_pack, media):
    return Setup(tmp_path, media_pack, media)


def refused(code: str, call, out: Path | None = None) -> None:
    with pytest.raises(a.S32Error) as raised:
        call()
    assert str(raised.value).startswith(code), str(raised.value)
    if out is not None:
        assert not out.exists()
        assert not [p for p in out.parent.iterdir() if p.name.startswith(f".{out.name}.partial-")]


def manifest(out: Path) -> dict:
    return json.loads((out / d.MANIFEST).read_bytes())


# ---------------------------------------------------------------- modes


def test_passthrough_is_a_byte_copy_with_no_ffmpeg_identity(setup, media):
    data = setup.derive("videos/a.mp4", "passthrough")
    out = setup.root / "out"
    assert sorted(p.name for p in out.iterdir()) == [d.MANIFEST, d.VIDEO]
    assert (out / d.VIDEO).read_bytes() == media["h264.mp4"]
    document = manifest(out)
    assert (out / d.MANIFEST).read_bytes() == data == a.canonical_json(document)
    assert document["outputSha256"] == document["sourceSha256"] == a.sha256_hex(media["h264.mp4"])
    assert document["authorisation"] == {"purposes": ["benchmarking", "development"], "operations": [], "blockers": []}
    assert document["ffmpegVersion"] is None and document["ffmpegSha256"] is None and document["args"] == []
    assert document["release"] == {"releaseId": f.RELEASE_ID, "releaseRecordSha256": f.release_sha256(setup.document),
                                   "member": "videos/a.mp4"}
    assert document["importLimitBytes"] == LIMIT


@pytest.mark.parametrize("member, mode", [("videos/b.mkv", "remux"), ("videos/c.mkv", "transcode"),
                                          ("videos/q.mov", "remux"), ("videos/a.mp4", "transcode")])
def test_remux_and_transcode_use_the_pinned_binary_and_args(setup, media_pack, member, mode):
    setup.derive(member, mode)
    document = manifest(setup.root / "out")
    ffmpeg = f.tool_path(media_pack, "ffmpeg")
    assert document["ffmpegSha256"] == a.sha256_hex(ffmpeg.read_bytes())
    assert document["ffmpegVersion"] == f.manifest_of(media_pack)["version"]
    assert document["args"] == d.ARGS[mode] and "{input}" in document["args"] and "{output}" in document["args"]
    assert document["authorisation"]["operations"] == ["create-derivatives"]
    assert document["sourceSha256"] == a.sha256_hex(setup.members[member]) != document["outputSha256"]
    assert document["sourceMedia"]["sourceSha256"] == document["sourceSha256"]
    assert document["outputMedia"]["sourceSha256"] == document["outputSha256"]
    assert document["outputMedia"]["maviImport"]["containerSupported"] and document["outputMedia"]["videoStreamCount"] == 1
    if mode == "transcode":
        assert document["outputMedia"]["video"]["codec"] == "h264"


def test_the_pinned_args_are_the_plans_exact_lists():
    common = "-nostdin -hide_banner -loglevel error -i {input} -map 0:v:0".split()
    tail = ("-an -sn -dn -map_metadata -1 -map_chapters -1 -fflags +bitexact -flags:v +bitexact -movflags +faststart "
            "-f mp4 {output}").split()
    assert d.ARGS["remux"] == [*common, "-c:v", "copy", *tail]
    assert d.ARGS["transcode"] == [*common, *"-c:v libx264 -preset slow -crf 16 -pix_fmt yuv420p -threads 1".split(), *tail]


@pytest.mark.parametrize("member, mode", [("videos/a.mp4", "passthrough"), ("videos/b.mkv", "remux"),
                                          ("videos/c.mkv", "transcode")])
def test_every_mode_repeats_byte_identically(setup, member, mode):
    first = setup.derive(member, mode, out="first")
    second = setup.derive(member, mode, out="second")
    assert first == second
    assert (setup.root / "first" / d.VIDEO).read_bytes() == (setup.root / "second" / d.VIDEO).read_bytes()


# ---------------------------------------------------------------- preconditions (no fallback)


@pytest.mark.parametrize("member, mode, code", [
    ("videos/b.mkv", "passthrough", "derivation_passthrough_not_importable"),
    ("videos/q.mov", "passthrough", "derivation_passthrough_not_importable"),
    ("videos/c.mkv", "remux", "derivation_remux_codec_unsupported"),
    ("videos/audio.mp4", "transcode", "derivation_probe_failed:video_streams"),
    ("videos/two.mp4", "passthrough", "derivation_probe_failed:video_streams"),
    ("videos/a.mp4", "copy", "derivation_mode_invalid"),
])
def test_mode_preconditions_refuse_without_output(setup, member, mode, code):
    refused(code, lambda: setup.derive(member, mode), setup.root / "out")


def test_the_import_size_limit_is_the_hosts(setup, media):
    limit = len(media["h264.mp4"]) - 1
    refused("derivation_passthrough_not_importable", lambda: setup.derive("videos/a.mp4", "passthrough", limit=limit),
            setup.root / "out")
    refused("derivation_output_not_importable", lambda: setup.derive("videos/b.mkv", "remux", limit=10), setup.root / "out")
    refused("derivation_import_limit_invalid", lambda: setup.derive("videos/a.mp4", "passthrough", limit=0))


# ---------------------------------------------------------------- release and root


def test_release_and_store_failures(setup, tmp_path):
    out = setup.root / "out"
    refused("derivation_member_not_listed", lambda: setup.derive("videos/missing.mp4", "passthrough"), out)
    malformed = tmp_path / "malformed.json"
    malformed.write_bytes(b'{"schemaVersion": "mavi-attribute-dataset-release-v1"}')
    refused("derivation_release_invalid", lambda: setup.derive("videos/a.mp4", "passthrough", release_path=malformed), out)
    (setup.store / "videos/b.mkv").write_bytes(setup.members["videos/b.mkv"] + b"x")
    refused("derivation_release_files_mismatch", lambda: setup.derive("videos/a.mp4", "passthrough"), out)
    (setup.store / "videos/b.mkv").write_bytes(b"y" * len(setup.members["videos/b.mkv"]))
    refused("derivation_release_files_mismatch", lambda: setup.derive("videos/a.mp4", "passthrough"), out)
    (setup.store / "videos/b.mkv").unlink()
    refused("derivation_release_files_mismatch", lambda: setup.derive("videos/a.mp4", "passthrough"), out)


def test_a_release_root_inside_git_is_refused(tmp_path, media_pack, media):
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    inside = Setup(repository, media_pack, media)
    refused("derivation_release_root_invalid", lambda: inside.derive("videos/a.mp4", "passthrough", out="../out"),
            tmp_path / "out")


def test_an_output_inside_git_is_refused(setup):
    subprocess.run(["git", "init", "-q", str(setup.root / "repo")], check=True)
    refused("derivation_output_in_git", lambda: setup.derive("videos/a.mp4", "passthrough", out="repo/out"),
            setup.root / "repo" / "out")


def test_the_release_root_refusal_names_no_path(tmp_path, media_pack, media):
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    inside = Setup(repository, media_pack, media)
    with pytest.raises(a.S32Error) as raised:
        inside.derive("videos/a.mp4", "passthrough", out="../out")
    assert str(raised.value) == "derivation_release_root_invalid"


def test_an_excluded_member_is_refused(tmp_path, media_pack, media):
    excluded = Setup(tmp_path, media_pack, media, excluded=("videos/a.mp4",))
    refused("derivation_member_excluded", lambda: excluded.derive("videos/a.mp4", "passthrough"), tmp_path / "out")


def test_a_member_changed_after_verification_is_refused(setup, monkeypatch):
    original = d._copy_hashed

    def changed(source, target):  # the store changes between verification and the copy
        sha, size = original(source, target)
        return "0" * 64, size

    monkeypatch.setattr(d, "_copy_hashed", changed)
    refused("derivation_member_changed", lambda: setup.derive("videos/a.mp4", "passthrough"), setup.root / "out")


@pytest.mark.parametrize("det, mode, code", [
    (None, "passthrough", "derivation_not_authorised:determination-missing"),
    (f.determination(inventory={**f.INVENTORY_ALL, "create-derivatives": "pending-r5"}), "remux",
     "derivation_not_authorised:rights-operation-pending-r5:create-derivatives"),
    (f.determination(inventory={**f.INVENTORY_ALL, "create-derivatives": "not-granted"}), "transcode",
     "derivation_not_authorised:rights-operation-not-granted:create-derivatives"),
])
def test_authorisation_blockers_leave_no_output(tmp_path, media_pack, media, det, mode, code):
    blocked = Setup(tmp_path, media_pack, media, det=det)
    member = "videos/a.mp4" if mode == "passthrough" else "videos/b.mkv"
    refused(code, lambda: blocked.derive(member, mode), tmp_path / "out")


def test_passthrough_needs_no_create_derivatives_but_remux_does(tmp_path, media_pack, media):
    det = f.determination(inventory={**f.INVENTORY_ALL, "create-derivatives": "not-granted"})
    partial = Setup(tmp_path, media_pack, media, det=det)
    partial.derive("videos/a.mp4", "passthrough")
    refused("derivation_not_authorised", lambda: partial.derive("videos/b.mkv", "remux", out="remux"),
            tmp_path / "remux")


# ---------------------------------------------------------------- failures and output


def test_an_ffmpeg_failure_leaves_no_output(setup, monkeypatch):
    monkeypatch.setitem(d.ARGS, "remux", [*d.ARGS["remux"][:-3], "-f", "no-such-muxer", "{output}"])
    refused("derivation_ffmpeg_failed", lambda: setup.derive("videos/b.mkv", "remux"), setup.root / "out")


def test_an_existing_destination_is_refused(setup):
    (setup.root / "out").mkdir()
    refused("output_exists", lambda: setup.derive("videos/a.mp4", "passthrough"))


def test_an_unverified_pack_is_refused(setup, tmp_path):
    pack = f.clone_pack(setup.pack, tmp_path / "bad-pack")
    manifest_document = f.manifest_of(pack)
    manifest_document["version"] = "not-this-version"
    f.rewrite_manifest(pack, manifest_document)
    refused("media_tools_invalid", lambda: setup.derive("videos/a.mp4", "passthrough", media_tools_dir=pack),
            setup.root / "out")


def test_the_manifest_records_no_local_path(setup):
    setup.derive("videos/b.mkv", "remux")
    text = (setup.root / "out" / d.MANIFEST).read_text(encoding="utf-8")
    for local in (str(setup.root), str(setup.pack), str(setup.store), setup.root.as_posix(), "\\", "store"):
        assert local not in text


def test_cli_prints_the_manifest_sha(setup, capsys):
    args = ["--media-tools", str(setup.pack), "--release", str(setup.release), "--release-root", str(setup.store),
            "--member", "videos/a.mp4", "--mode", "passthrough", "--max-import-bytes", str(LIMIT),
            "--out", str(setup.root / "cli")]
    assert d.main(args) == 0
    assert capsys.readouterr().out.strip() == a.sha256_hex((setup.root / "cli" / d.MANIFEST).read_bytes())
    assert d.main(args) == 2 and "refused output_exists" in capsys.readouterr().err


# ---------------------------------------------------------------- contract and T3


def test_the_schema_pins_the_mode_constants(setup):
    setup.derive("videos/b.mkv", "remux")
    document = manifest(setup.root / "out")
    a.validate(document, "vehicle-subclass-derivation-v1", "unexpected")
    for mutate in (lambda m: m.update(args=d.ARGS["transcode"]),
                   lambda m: m.update(ffmpegSha256=None),
                   lambda m: m["authorisation"].update(operations=[]),
                   lambda m: m["authorisation"].update(blockers=["determination-missing"]),
                   lambda m: m["authorisation"].update(purposes=["development"]),
                   lambda m: m["outputMedia"]["maviImport"].update(containerSupported=False),
                   lambda m: m.update(mode="passthrough"),
                   lambda m: m["sourceMedia"]["video"].update(codec="hevc"),
                   lambda m: m.update(localPath="x")):
        mutated = json.loads(json.dumps(document))
        mutate(mutated)
        with pytest.raises(a.S32Error):
            a.validate(mutated, "vehicle-subclass-derivation-v1", "derivation_invalid")


@pytest.mark.parametrize("member, mode", [("videos/a.mp4", "passthrough"), ("videos/b.mkv", "remux"),
                                          ("videos/c.mkv", "transcode")])
def test_t3_accepts_a_generated_manifest_of_each_mode(setup, member, mode):
    import sample_tracks

    setup.derive(member, mode)
    out = setup.root / "out"
    video = (out / d.VIDEO).read_bytes()
    export = s32.write_export(setup.root / "export", run_id="01a0ffb2-cb2e-77c1-9f44-256be4fcc300",
                              video_id="01a0ffb2-c9b2-73ea-8fcd-11523f478800", camera="S32-CAM", source=video,
                              profile_sha="f" * 64, tracks=[s32.TrackSpec(1)])
    exports = a.load_exports([export])
    used, release_id, release_record = sample_tracks._derivations([out / d.MANIFEST], exports)
    assert used == [a.sha256_hex((out / d.MANIFEST).read_bytes())]
    assert (release_id, release_record) == (f.RELEASE_ID, f.release_sha256(setup.document))
