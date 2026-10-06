"""The VisDrone2019-MOT adapter on synthetic fixtures in the release layout (H4; no dataset bytes)."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

from bdd_fixtures import jpeg_header
from tools.benchmarks import datasets, prepare
from tools.benchmarks.capabilities.vehicle_tracks import ground_truth as gt_module
from tools.benchmarks.core import descriptor as descriptors
from tools.benchmarks.core import mapping as mappings
from tools.benchmarks.core._stage3 import ROOT
from tools.benchmarks.core.identity import S32Error, canonical_json, from_rational
from tools.benchmarks.datasets import visdrone_mot as vd

TEMPLATE = ROOT / "docs/qualification/stage3/benchmarks/visdrone2019-mot.descriptor-template.json"
MAPPING = ROOT / "docs/qualification/stage3/benchmarks/visdrone2019-mot.mapping.json"
ADAPTER = vd.VisDroneMotAdapter()
SEQ = "uav0000001_00000_v"
W, H = 100, 50
# frame, id, x, y, w, h, score, category, truncation, occlusion
ROWS = [
    (1, 1, 10, 10, 20, 10, 1, 4, 0, 0),    # car, frames 1-3
    (2, 1, 12, 10, 20, 10, 1, 4, 0, 0),
    (3, 1, 14, 10, 20, 10, 1, 4, 0, 1),
    (1, 2, 50, 20, 10, 10, 1, 6, 0, 0),    # truck, frame 2 ignored (score 0)
    (2, 2, 50, 20, 10, 10, 0, 6, 0, 0),
    (1, 3, 5, 5, 4, 4, 1, 1, 0, 0),        # pedestrian
    (2, 2, 0, 0, 30, 30, 0, 0, 0, 0),      # ignored region reusing id 2
    (1, 4, 80, 40, 40, 20, 1, 9, 1, 0),    # bus, clipped at the right and bottom edges
    (1, 5, 30, 30, 5, 5, 1, 4, 0, 0),      # id 5 changes class: car then van -> ignored throughout
    (2, 5, 30, 30, 5, 5, 1, 5, 0, 0),
    (1, 6, 60, 5, 4, 4, 1, 11, 0, 0),      # others: ignored on every frame
]


def write_source(root: Path, rows=ROWS, frames: int = 3, split: str = "val", sequence: str = SEQ) -> Path:
    base = root / f"VisDrone2019-MOT-{split}"
    (base / "annotations").mkdir(parents=True, exist_ok=True)
    (base / "annotations" / f"{sequence}.txt").write_bytes(
        "".join(",".join(str(v) for v in row) + "\n" for row in rows).encode("ascii"))
    images = base / "sequences" / sequence
    images.mkdir(parents=True, exist_ok=True)
    for number in range(1, frames + 1):
        (images / f"{number:07d}.jpg").write_bytes(jpeg_header(W, H))
    return root


def ground_truth(tmp_path: Path, rows=ROWS, frames: int = 3) -> dict:
    root = write_source(tmp_path / "src", rows, frames)
    document = descriptors.freeze(vd.descriptor(), root)
    entries = descriptors.reconcile(document, root)
    assert datasets.discover(ADAPTER, root, entries, "val") == [SEQ]
    return ADAPTER.ground_truth(root, entries, document, "val", SEQ)


def test_committed_template_and_mapping_are_the_canonical_renderings():
    assert TEMPLATE.read_bytes() == canonical_json(vd.descriptor())
    assert MAPPING.read_bytes() == canonical_json(vd.mapping())
    template, _ = descriptors.load(TEMPLATE)
    assert template["manifest"] == {"kind": "file-hashes", "entries": []}
    assert template["frameTime"] == {"kind": "index-at-fps", "fpsNumerator": 30, "fpsDenominator": 1}
    assert template["researchUse"]["status"] == "RESEARCH-UNCERTAIN"
    assert "visdrone2019-mot" in prepare.ADAPTERS


def test_mapping_scores_only_the_four_vehicle_classes():
    mapping, _ = mappings.load(MAPPING)
    rows = mappings.check_against(mapping, vd.descriptor())
    mappings.require_emitted(rows, ADAPTER.native_classes())
    assert {n: r["maviClass"] for n, r in rows.items() if r["kind"] == "exact"} == {
        "bus": "bus", "car": "car", "motor": "motorcycle", "truck": "truck"}
    assert {n for n, r in rows.items() if r.get("unsupportedKind") == "vehicle-unresolved"} == {
        "awning-tricycle", "others", "tricycle", "van"}


def test_ground_truth_tracks_ignores_regions_and_timing(tmp_path):
    document = gt_module.validate(ground_truth(tmp_path))
    assert document["frameSize"] == {"width": W, "height": H}
    assert [i["frameIndex"] for i in document["instants"]] == [0, 1, 2]
    assert [from_rational(i["videoOffsetMs"], "x") for i in document["instants"]] == [0, Fraction(100, 3), Fraction(200, 3)]
    tracks = {t["gtTrackId"]: t for t in document["tracks"]}
    assert {k: t["nativeClass"] for k, t in tracks.items()} == {
        "1": "car", "2": "truck", "3": "pedestrian", "4": "bus", "5": "car", "6": "others"}
    assert all(f["ignore"] for f in tracks["6"]["frames"])                 # others -> ignored throughout
    assert [f["frameIndex"] for f in tracks["1"]["frames"]] == [0, 1, 2]
    assert [f["ignore"] for f in tracks["2"]["frames"]] == [False, True]   # score 0 -> ignored frame
    assert all(f["ignore"] for f in tracks["5"]["frames"])                 # class change -> ignored throughout
    assert tracks["1"]["frames"][0]["box"] == {"x": 0.1, "y": 0.2, "width": 0.2, "height": 0.2}
    assert tracks["4"]["frames"][0]["box"] == {"x": 0.8, "y": 0.8, "width": 0.2, "height": 0.2}  # clipped
    assert document["ignoreRegions"] == [{"frameIndex": 1, "box": {"x": 0.0, "y": 0.0, "width": 0.3, "height": 0.6}}]


def test_frame_numbers_must_be_contiguous_from_one(tmp_path):
    root = write_source(tmp_path / "src")
    (root / "VisDrone2019-MOT-val" / "sequences" / SEQ / "0000002.jpg").unlink()
    document = descriptors.freeze(vd.descriptor(), root)
    entries = descriptors.reconcile(document, root)
    with pytest.raises(S32Error, match="source_manifest_incomplete:sequence"):
        datasets.discover(ADAPTER, root, entries, "val")


@pytest.mark.parametrize(
    ("row", "code"),
    [((4, 1, 10, 10, 20, 10, 1, 4, 0, 0), "frame_index"),
     ((1, 1, 10, 10, 0, 10, 1, 4, 0, 0), "box"),
     ((1, 1, 10, 10, 20, 10, 2, 4, 0, 0), "score"),
     ((1, 1, 10, 10, 20, 10, 1, 12, 0, 0), "category"),
     ((1, 1, 200, 10, 20, 10, 1, 4, 0, 0), "box_outside_image")],
    ids=["frame-beyond-images", "empty-box", "score", "category", "outside"],
)
def test_malformed_rows_are_refused(tmp_path, row, code):
    with pytest.raises(S32Error, match=f"adapter_label_invalid:{SEQ}:{code}"):
        ground_truth(tmp_path, rows=[row])


def test_a_descriptor_with_other_timing_is_refused(tmp_path):
    root = write_source(tmp_path / "src")
    document = descriptors.freeze(vd.descriptor(), root)
    document["frameTime"] = {"kind": "index-at-fps", "fpsNumerator": 25, "fpsDenominator": 1}
    entries = descriptors.reconcile(document, root)
    with pytest.raises(S32Error, match="adapter_descriptor_mismatch:frameTime"):
        ADAPTER.ground_truth(root, entries, document, "val", SEQ)


# --------------------------------------------------------------------------- odd frame dimensions (prepare padding)


def test_odd_dimensions_are_padded_and_gt_is_reexpressed_in_the_padded_frame():
    gt = {"sequenceId": SEQ, "split": "val", "frameSize": {"width": 101, "height": 51},
          "instants": [{"frameIndex": 0, "videoOffsetMs": {"numerator": 0, "denominator": 1}}],
          "tracks": [{"gtTrackId": "1", "nativeClass": "car", "frames": [
              {"frameIndex": 0, "videoOffsetMs": {"numerator": 0, "denominator": 1}, "ignore": False,
               "box": {"x": 0.5, "y": 0.5, "width": 0.25, "height": 0.25}}]}],
          "ignoreRegions": [{"frameIndex": 0, "box": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}}]}
    padded, record = prepare.pad_to_even(gt)
    assert padded["frameSize"] == {"width": 102, "height": 52}
    assert record == {"sourceSize": {"width": 101, "height": 51}, "encodedSize": {"width": 102, "height": 52},
                      "filter": "pad=102:52:0:0:black"}
    box = padded["tracks"][0]["frames"][0]["box"]
    # The same pixels: x = 50.5 px, width = 25.25 px, in a frame one pixel wider.
    assert box["x"] * 102 == pytest.approx(50.5) and box["width"] * 102 == pytest.approx(25.25)
    assert box["y"] * 52 == pytest.approx(25.5) and box["height"] * 52 == pytest.approx(12.75)
    assert padded["ignoreRegions"][0]["box"]["height"] * 52 == pytest.approx(51)
    even = dict(gt, frameSize={"width": 100, "height": 50})
    assert prepare.pad_to_even(even) == (even, None)


def test_prepare_encodes_odd_sized_frames_with_padding(tmp_path, media_pack):
    import json
    import subprocess

    import s32b_fixtures  # tools/stage3/tests, on the path through the media_pack fixture

    from tools.benchmarks.datasets.bdd100k_mot import jpeg_size

    root = write_source(tmp_path / "src", rows=ROWS[:3], frames=3)
    ffmpeg = s32b_fixtures.tool_path(Path(media_pack), "ffmpeg")
    for path in sorted((root / "VisDrone2019-MOT-val" / "sequences" / SEQ).glob("*.jpg")):
        subprocess.run([str(ffmpeg), "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=101x51",
                        "-frames:v", "1", "-pix_fmt", "yuvj444p", "-q:v", "3", str(path)], check=True, capture_output=True)
        assert jpeg_size(path.read_bytes(), "x") == (101, 51), "the fixture frame is not odd-sized"
    document = descriptors.freeze(vd.descriptor(), root)
    (tmp_path / "frozen.json").write_bytes(canonical_json(document))
    prepare.prepare(descriptor_path=tmp_path / "frozen.json", source_root=root, split="val",
                    adapter_id="visdrone2019-mot", media_tools_dir=Path(media_pack), out=tmp_path / "derived")
    manifest, _, documents = prepare.load(tmp_path / "derived")
    (row,) = manifest["sequences"]
    assert row["padding"]["sourceSize"] == {"width": 101, "height": 51}
    assert documents[SEQ]["frameSize"] == {"width": 102, "height": 52}
    assert json.loads((tmp_path / "derived" / "sequences" / SEQ / "ground-truth.json").read_bytes())["frameSize"]["height"] == 52
