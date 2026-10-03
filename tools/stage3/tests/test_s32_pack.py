"""T4: the blind labelling pack and its offline page."""

from __future__ import annotations

import io
import json
import re
import shutil
from pathlib import Path

import numpy
import pytest
from PIL import Image

import build_labeling_pack as bp
import s32fixtures as f
import s32pipeline as p

a = f.a
LAYOUT = {
    "CAM-A": [f.TrackSpec(number=1, subclass="car", roles=("Representative", "NearView")),
              f.TrackSpec(number=2, subclass="truck", box=(0.1, 0.2, 0.3, 0.4)),
              f.TrackSpec(number=3, subclass=None, roles=("Representative", "EarlyDiverse", "LateDiverse"))],
    "CAM-B": [f.TrackSpec(number=10, subclass="bus"), f.TrackSpec(number=11, subclass="motorcycle")],
}
for tracks in LAYOUT.values():
    for spec in tracks:
        spec.track_id = f"00000000-0000-4000-8000-{spec.number:012d}"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("pack")
    world = f.build_world(root / "world", LAYOUT)
    sample = root / "sample.json"
    p.run(p.sample_tracks.main, p.sample(world, sample, target=5, overlap="0.4"))
    primary, overlap = root / "primary", root / "overlap"
    p.run(bp.main, p.pack(world, sample, primary))
    p.run(bp.main, p.pack(world, sample, overlap, view="overlap", parent=primary))
    return world, sample, primary, overlap, root


def tree(directory: Path) -> dict[str, bytes]:
    return {path.relative_to(directory).as_posix(): path.read_bytes() for path in sorted(directory.rglob("*")) if path.is_file()}


def refused(capsys, args, code, out):
    assert bp.main(args) == 2
    assert f"refused {code}" in capsys.readouterr().err
    assert not out.exists()
    assert not any(path.name.startswith(f".{out.name}.partial") for path in out.parent.iterdir())


def test_pack_bytes_are_deterministic(built, tmp_path):
    world, sample, primary, _, _ = built
    again = tmp_path / "again"
    p.run(bp.main, p.pack(world, sample, again))
    assert tree(again) == tree(primary)


def test_manifest_lists_every_file_except_itself_and_pack_data(built):
    _, _, primary, _, _ = built
    manifest = json.loads((primary / bp.MANIFEST).read_text(encoding="utf-8"))
    listed = [entry["path"] for entry in manifest["files"]]
    assert len(listed) == len(set(listed))
    assert set(listed) == set(tree(primary)) - {bp.MANIFEST, bp.PACK_DATA}
    assert {"index.html", "labeling.js", "labeling.css", bp.GUIDE} <= set(listed)
    assert "packSha256" not in manifest
    verified, pack_sha = bp.verify_pack(primary)
    assert pack_sha == a.sha256_hex((primary / bp.MANIFEST).read_bytes())
    assert f'"packSha256":"{pack_sha}"' in (primary / bp.PACK_DATA).read_text(encoding="utf-8")


def test_edited_pack_data_or_file_is_refused(built, tmp_path):
    _, _, primary, _, _ = built
    copy = tmp_path / "copy"
    shutil.copytree(primary, copy)
    (copy / bp.PACK_DATA).write_bytes((copy / bp.PACK_DATA).read_bytes().replace(b'"items"', b'"items" '))
    with pytest.raises(a.S32Error, match="pack_data_mismatch"):
        bp.verify_pack(copy)
    shutil.rmtree(copy)
    shutil.copytree(primary, copy)
    (copy / "labeling.js").write_bytes(b"// edited\n")
    with pytest.raises(a.S32Error, match="pack_file_changed"):
        bp.verify_pack(copy)
    shutil.rmtree(copy)
    shutil.copytree(primary, copy)
    (copy / "extra.txt").write_text("x", encoding="utf-8")
    with pytest.raises(a.S32Error, match="pack_inventory_mismatch"):
        bp.verify_pack(copy)


def test_reviewer_visible_files_leak_no_prediction_or_identifier(built):
    world, _, primary, overlap, _ = built
    for directory in (primary, overlap):
        payload = json.loads((directory / bp.PACK_DATA).read_text(encoding="utf-8")
                             .removeprefix("window.MAVI_PACK = ").rstrip(";\n"))
        # Structure is an allow-list: item ids and image paths with fixed role captions only.
        assert set(payload) == {"packSha256", "guide", "items"}
        for item in payload["items"]:
            assert set(item) == {"itemId", "views"}
            for view in item["views"]:
                assert set(view) == {"path", "label"}
                assert re.fullmatch(r"(crop|context) (Representative|NearView|EarlyDiverse|LateDiverse)", view["label"])
        visible = b"".join(data for name, data in tree(directory).items()
                           if name != bp.MANIFEST and not name.endswith((".jpg", ".png"))).decode("utf-8")
        for forbidden in ("objectSubclass", "Confidence", "confidence", "detector-native", "attestation",
                          world.profile_sha, "rtmdet", "maviCommit"):
            assert forbidden not in visible, forbidden
        for video in world.videos:
            assert video.run_id not in visible and video.video_id not in visible
            for track in video.tracks:
                assert track.track_id not in visible
        # Label words exist only as the page's choices, never as a value attached to an item.
        assert not re.search(r'"(car|truck|bus|motorcycle)"', (directory / bp.PACK_DATA).read_text(encoding="utf-8"))


def test_static_page_makes_no_network_calls():
    for name in bp.TEMPLATE_FILES:
        text = (bp.TEMPLATES / name).read_text(encoding="utf-8")
        assert "http://" not in text and "https://" not in text
        assert "fetch(" not in text and "XMLHttpRequest" not in text and "import(" not in text
        assert "\r" not in text


def test_context_frame_draws_the_observation_box():
    rgb = numpy.full((120, 160, 3), 90, dtype=numpy.uint8)
    png = bp.render_context(rgb, {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5})
    image = numpy.asarray(Image.open(io.BytesIO(png)).convert("RGB"))
    assert tuple(image[30, 40]) == (255, 0, 0)   # top-left corner of the box
    assert tuple(image[89, 119]) == (255, 0, 0)  # bottom-right corner
    assert tuple(image[60, 80]) == (90, 90, 90)  # interior untouched
    assert tuple(image[5, 5]) == (90, 90, 90)    # outside untouched


def test_pack_context_images_are_decoded_frames_with_the_box(built):
    world, _, primary, _, _ = built
    manifest = json.loads((primary / bp.MANIFEST).read_text(encoding="utf-8"))
    item = next(i for i in manifest["items"] if i["trackId"] == world.track(2).track_id)
    context = next(v for v in item["views"] if v["kind"] == "context")
    image = numpy.asarray(Image.open(primary / context["path"]).convert("RGB")).astype(int)
    x0, y0 = round(0.1 * 160), round(0.2 * 120)
    assert tuple(image[y0, x0]) == (255, 0, 0)
    grey = image[5, 150]
    assert max(abs(grey - 100)) <= 6  # the decoded grey frame of CAM-A (lossy codec)
    assert manifest["extraction"]["renderRuleVersion"] == "context-v1"
    assert manifest["extraction"]["decoder"]["av"]


def test_crlf_templates_give_identical_bytes_and_identity(built, tmp_path):
    world, sample, primary, _, _ = built
    templates = tmp_path / "crlf"
    templates.mkdir()
    for name in bp.TEMPLATE_FILES:
        (templates / name).write_bytes((bp.TEMPLATES / name).read_bytes().replace(b"\n", b"\r\n"))
    out = tmp_path / "crlf-pack"
    p.run(bp.main, p.pack(world, sample, out, templates=templates))
    assert tree(out) == tree(primary)
    for name, data in tree(out).items():
        if not name.endswith((".jpg", ".png")):
            assert b"\r" not in data and not data.startswith(b"\xef\xbb\xbf"), name


def test_non_utf8_template_is_refused(built, tmp_path, capsys):
    world, sample, _, _, _ = built
    templates = tmp_path / "bad"
    shutil.copytree(bp.TEMPLATES, templates)
    (templates / "labeling.css").write_bytes(b"\xff\xfe broken")
    refused(capsys, p.pack(world, sample, tmp_path / "out", templates=templates), "pack_asset_not_utf8", tmp_path / "out")


def test_primary_and_overlap_share_tracks_but_no_item_ids(built):
    _, sample, primary, overlap, _ = built
    first = json.loads((primary / bp.MANIFEST).read_text(encoding="utf-8"))
    second = json.loads((overlap / bp.MANIFEST).read_text(encoding="utf-8"))
    sample_doc = json.loads(sample.read_text(encoding="utf-8"))
    assert {i["trackId"] for i in second["items"]} == {s["trackId"] for s in sample_doc["overlapSelected"]}
    assert {i["trackId"] for i in second["items"]} <= {i["trackId"] for i in first["items"]}
    assert not {i["itemId"] for i in first["items"]} & {i["itemId"] for i in second["items"]}
    assert second["viewKind"] == "overlap" and second["parentPackSha256"] == a.sha256_hex((primary / bp.MANIFEST).read_bytes())
    assert "parentPackSha256" not in first


def test_parent_pack_rules(built, tmp_path, capsys):
    world, sample, primary, overlap, root = built
    refused(capsys, p.pack(world, sample, tmp_path / "o1", view="overlap"), "parent_pack_invalid", tmp_path / "o1")
    refused(capsys, p.pack(world, sample, tmp_path / "o2", parent=primary), "parent_pack_invalid", tmp_path / "o2")
    refused(capsys, p.pack(world, sample, tmp_path / "o3", view="overlap", parent=overlap), "parent_pack_invalid", tmp_path / "o3")
    edited = tmp_path / "edited-parent"
    shutil.copytree(primary, edited)
    manifest = json.loads((edited / bp.MANIFEST).read_text(encoding="utf-8"))
    manifest["seed"] = "another"
    (edited / bp.MANIFEST).write_bytes(a.canonical_json(manifest))
    refused(capsys, p.pack(world, sample, tmp_path / "o4", view="overlap", parent=edited), "parent_pack_invalid", tmp_path / "o4")
    other_sample = tmp_path / "other-sample.json"
    p.run(p.sample_tracks.main, p.sample(world, other_sample, target=4, seed="other"))
    refused(capsys, p.pack(world, other_sample, tmp_path / "o5", view="overlap", parent=primary), "parent_pack_invalid", tmp_path / "o5")


def test_parent_built_under_another_guide_commit_is_refused(tmp_path, capsys):
    world = f.build_world(tmp_path / "w", LAYOUT)
    sample = tmp_path / "s.json"
    p.run(p.sample_tracks.main, p.sample(world, sample, target=4, overlap="0.5"))
    primary = tmp_path / "primary"
    p.run(bp.main, p.pack(world, sample, primary))
    world.guide.write_bytes(world.guide.read_bytes() + b"\n## Amended\n")
    f.git(world.repository, "commit", "-q", "-am", "guide amended")
    world.commit = f.git(world.repository, "rev-parse", "HEAD")
    refused(capsys, p.pack(world, sample, tmp_path / "o", view="overlap", parent=primary), "parent_pack_invalid:guide", tmp_path / "o")


def test_guide_must_be_committed_unchanged_and_is_copied(built, tmp_path, capsys):
    world, sample, primary, _, _ = built
    assert (primary / bp.GUIDE).read_bytes() == a.canonical_text(world.guide.read_bytes(), "x")
    original = world.guide.read_bytes()
    try:
        world.guide.write_bytes(original + b"edited")
        refused(capsys, p.pack(world, sample, tmp_path / "g"), "labeling_guide_not_committed", tmp_path / "g")
    finally:
        world.guide.write_bytes(original)


def test_input_mismatches_are_refused(built, tmp_path, capsys):
    world, sample, _, _, root = built
    # A profile that is not the attested one.
    other_profile = tmp_path / "profile.json"
    other_profile.write_bytes(world.profile_path.read_bytes() + b" ")
    args = p.pack(world, sample, tmp_path / "p1")
    args[args.index("--pipeline-profile") + 1] = str(other_profile)
    refused(capsys, args, "pack_profile_mismatch", tmp_path / "p1")
    # A source whose bytes are not the export's source (mapped by hash, never by order).
    args = p.pack(world, sample, tmp_path / "p2")
    other_source = tmp_path / "other.mp4"
    f.mp4(other_source, grey=7)
    args[args.index(str(world.sources()[0]))] = str(other_source)
    refused(capsys, args, "source_missing", tmp_path / "p2")
    # The same source given twice.
    args = p.pack(world, sample, tmp_path / "p3") + ["--source", str(world.sources()[0])]
    refused(capsys, args, "source_ambiguous", tmp_path / "p3")
    # Sources in reverse order still map correctly.
    args = p.pack(world, sample, tmp_path / "p4")
    first, second = args.index(str(world.sources()[0])), args.index(str(world.sources()[1]))
    args[first], args[second] = args[second], args[first]
    p.run(bp.main, args)
    assert tree(tmp_path / "p4") == tree(root / "primary")


def test_changed_evidence_and_out_of_range_frames_are_refused(tmp_path, capsys):
    world = f.build_world(tmp_path / "w", LAYOUT)
    sample = tmp_path / "s.json"
    p.run(p.sample_tracks.main, p.sample(world, sample, target=5))
    export = json.loads(world.videos[0].export_path.read_text(encoding="utf-8"))
    evidence = world.videos[0].export_path.parent / export["tracks"][0]["observations"][1]["evidencePath"]
    original = evidence.read_bytes()
    evidence.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    refused(capsys, p.pack(world, sample, tmp_path / "e"), "pack_evidence_mismatch", tmp_path / "e")
    evidence.write_bytes(original)

    late = f.build_world(tmp_path / "late", {"CAM-Z": [f.TrackSpec(number=1, frame_shift=40)]})
    late_sample = tmp_path / "late.json"
    p.run(p.sample_tracks.main, p.sample(late, late_sample, target=1))
    refused(capsys, p.pack(late, late_sample, tmp_path / "late-pack"), "frame_outside_video", tmp_path / "late-pack")


def test_guide_checked_out_with_crlf_still_binds_under_the_lf_rule(tmp_path):
    world = f.build_world(tmp_path / "w", LAYOUT)
    (world.repository / ".gitattributes").write_text("docs/qualification/stage3/*.md text eol=lf\n", encoding="utf-8")
    f.git(world.repository, "add", ".gitattributes")
    f.git(world.repository, "commit", "-q", "-m", "lf rule")
    world.commit = f.git(world.repository, "rev-parse", "HEAD")
    f.git(world.repository, "config", "core.autocrlf", "true")
    world.guide.unlink()
    subprocess_checkout = ["-c", "core.autocrlf=true", "checkout", "--", a.LABELING_GUIDE_GIT_PATH]
    import subprocess
    subprocess.run(["git", "-C", str(world.repository), *subprocess_checkout], check=True)
    assert b"\r" not in world.guide.read_bytes()
    sample = tmp_path / "s.json"
    p.run(p.sample_tracks.main, p.sample(world, sample, target=3))
    p.run(bp.main, p.pack(world, sample, tmp_path / "pack"))


def test_a_committed_guide_that_is_not_canonical_text_is_refused(tmp_path, capsys):
    world = f.build_world(tmp_path / "w", LAYOUT)
    world.guide.write_bytes(world.guide.read_bytes().replace(b"\n", b"\r\n"))
    f.git(world.repository, "commit", "-q", "-am", "crlf guide")
    world.commit = f.git(world.repository, "rev-parse", "HEAD")
    sample = tmp_path / "s.json"
    p.run(p.sample_tracks.main, p.sample(world, sample, target=3))
    refused(capsys, p.pack(world, sample, tmp_path / "pack"), "labeling_guide_not_canonical", tmp_path / "pack")
