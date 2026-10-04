"""The BDD100K MOT adapter on synthetic Scalabel-format fixtures (S3.2d-1 plan §16 slice 4; no dataset bytes)."""

from __future__ import annotations

import copy
import json
import shutil
from fractions import Fraction
from pathlib import Path

import pytest

import bdd_fixtures as b
from tools.benchmarks import datasets, prepare
from tools.benchmarks.capabilities.vehicle_tracks import ground_truth as gt_module
from tools.benchmarks.core import descriptor as descriptors
from tools.benchmarks.core import mapping as mappings
from tools.benchmarks.core._stage3 import ROOT
from tools.benchmarks.core.identity import S32Error, canonical_json, from_rational
from tools.benchmarks.datasets import bdd100k_mot as bdd

TEMPLATE = ROOT / "docs/qualification/stage3/benchmarks/bdd100k-mot-2020.descriptor-template.json"
MAPPING = ROOT / "docs/qualification/stage3/benchmarks/bdd100k-mot-2020.mapping.json"
ADAPTER = bdd.Bdd100kMotAdapter()


def frozen_source(tmp_path: Path, documents=None, image=None) -> tuple[Path, dict, dict]:
    root = b.write_source(tmp_path / "source", documents, image=image)
    document = descriptors.freeze(bdd.descriptor(), root)
    return root, document, descriptors.reconcile(document, root)


def gt(tmp_path: Path, sequence: str = b.SEQ_A, documents=None, image=None) -> dict:
    root, document, entries = frozen_source(tmp_path, documents, image)
    return ADAPTER.ground_truth(root, entries, document, "val", sequence)


def refusal(tmp_path: Path, change, sequence: str = b.SEQ_A) -> str:
    with pytest.raises(S32Error) as caught:
        gt(tmp_path, sequence, b.mutated(change))
    return str(caught.value)


# Committed descriptor template and mapping


def test_committed_template_and_mapping_are_the_canonical_renderings():
    assert TEMPLATE.read_bytes() == canonical_json(bdd.descriptor())
    assert MAPPING.read_bytes() == canonical_json(bdd.mapping())
    template, _ = descriptors.load(TEMPLATE)
    assert template["manifest"] == {"kind": "file-hashes", "entries": []}  # pre-acquisition: never a fake freeze
    assert template["frameTime"] == {"kind": "index-at-fps", "fpsNumerator": 5, "fpsDenominator": 1}
    assert "ignoreSemantics" not in template and template["access"]["mechanism"] == "agreement"


def test_mapping_is_complete_for_the_taxonomy_and_the_adapter():
    mapping, _ = mappings.load(MAPPING)
    rows = mappings.check_against(mapping, bdd.descriptor())
    mappings.require_emitted(rows, ADAPTER.native_classes())
    assert {native: row["maviClass"] for native, row in rows.items() if row["kind"] == "exact"} == {
        "bus": "bus", "car": "car", "motorcycle": "motorcycle", "truck": "truck"}
    assert {native for native, row in rows.items() if row.get("unsupportedKind") == "vehicle-unresolved"} == {
        "caravan", "other-vehicle", "trailer", "van"}
    assert all(row["reason"] for row in rows.values())


def test_every_accepted_raw_category_maps_to_a_declared_native_class():
    declared = set(descriptors.native_classes(bdd.descriptor()))
    assert set(bdd.CATEGORIES.values()) == declared == ADAPTER.native_classes()
    eight = {"pedestrian", "rider", "car", "truck", "bus", "train", "motorcycle", "bicycle"}
    assert eight <= set(bdd.CATEGORIES) and bdd.ALIASES == {
        "bike": "bicycle", "motor": "motorcycle", "person": "pedestrian"}
    assert bdd.CATEGORIES["van"] == "van" and bdd.CATEGORIES["caravan"] == "caravan"  # never folded into car


def test_a_descriptor_declaring_crowd_as_ignore_is_refused():
    document = bdd.descriptor()
    document["ignoreSemantics"] = [{"kind": "attribute", "name": "crowd", "treatment": "ignore-region"}]
    with pytest.raises(S32Error, match="^descriptor_invalid"):
        descriptors.check(document)


# Canonical ground truth


def test_ground_truth_tracks_classes_boxes_and_timing(tmp_path):
    document = gt_module.validate(gt(tmp_path))
    assert document["frameSize"] == {"width": 64, "height": 36} and "ignoreRegions" not in document
    assert [i["frameIndex"] for i in document["instants"]] == [0, 1, 2, 3]
    assert [from_rational(i["videoOffsetMs"], "x") for i in document["instants"]] == [0, 200, 400, 600]
    tracks = {t["gtTrackId"]: t for t in document["tracks"]}
    assert {k: t["nativeClass"] for k, t in tracks.items()} == {
        "1": "car", "2": "truck", "3": "pedestrian", "4": "bus", "5": "rider", "6": "motorcycle"}
    first = tracks["1"]["frames"][0]
    assert first["box"] == {"x": 2 / 64, "y": 3 / 36, "width": 12 / 64, "height": 8 / 36}  # inclusive x2, y2
    fractional = tracks["1"]["frames"][2]["box"]
    assert fractional["x"] == float(Fraction(6.5) / 64) and fractional["width"] == 12 / 64
    edge = tracks["4"]["frames"][2]["box"]  # x2 = 64 = image width: the inclusive extent is clipped to the image
    assert edge["x"] + edge["width"] == 1.0 and edge["width"] == 31 / 64 and edge["height"] == 18 / 36
    crowd = tracks["3"]["frames"]
    assert len(crowd) == 2 and not any(frame["ignore"] for frame in crowd)  # crowd stays ordinary GT
    assert all(not f["ignore"] for t in document["tracks"] for f in t["frames"])


def test_second_sequence_keeps_empty_frames_aliases_and_distractors(tmp_path):
    document = gt_module.validate(gt(tmp_path, b.SEQ_B))
    assert [i["frameIndex"] for i in document["instants"]] == [0, 1, 2]  # the frame without labels is an instant
    assert {t["gtTrackId"]: t["nativeClass"] for t in document["tracks"]} == {
        "1": "bicycle", "10": "motorcycle", "7": "train", "8": "other-vehicle", "9": "van"}  # alias motor; van kept
    assert [f["frameIndex"] for f in document["tracks"][2]["frames"]] == [0, 2]  # ids sort as text: 1, 10, 7


def test_discovery_frame_paths_and_track_ids_are_stable(tmp_path):
    root, document, entries = frozen_source(tmp_path)
    assert datasets.discover(ADAPTER, root, entries, "val") == [b.SEQ_A, b.SEQ_B]
    paths = ADAPTER.frame_paths(root, entries, "val", b.SEQ_B)
    assert paths[0] == (0, f"images/track/val/{b.SEQ_B}/{b.SEQ_B}-0000001.jpg")  # from name, not from the index
    once = canonical_json(ADAPTER.ground_truth(root, entries, document, "val", b.SEQ_A))
    assert canonical_json(ADAPTER.ground_truth(root, entries, document, "val", b.SEQ_A)) == once


def test_record_order_in_the_label_file_does_not_change_ground_truth(tmp_path):
    reference = canonical_json(gt(tmp_path / "a"))
    shuffled = b.mutated(lambda d: d[b.SEQ_A].reverse())
    assert canonical_json(gt(tmp_path / "b", documents=shuffled)) == reference


def test_other_splits_and_packages_are_not_members_of_the_val_split(tmp_path):
    root = b.write_source(tmp_path / "source")
    b.write_source(root, {"f0000009-c0000009": b.labels()[b.SEQ_B]}, split="train")
    (root / "README.txt").write_text("operator notes", encoding="utf-8")
    document = descriptors.freeze(bdd.descriptor(), root)
    entries = descriptors.reconcile(document, root)
    assert datasets.discover(ADAPTER, root, entries, "val") == [b.SEQ_A, b.SEQ_B]


# Refusals (deterministic codes, never raw exceptions)


@pytest.mark.parametrize("change, code", [
    (lambda d: d[b.SEQ_A][0]["labels"].append(b._label("1", "car", (40, 1, 45, 4))), "duplicate_track_id"),
    (lambda d: d[b.SEQ_A][0]["labels"][0].update(category=7), "category"),
    (lambda d: d[b.SEQ_A][0]["labels"][0].update(category="scooter"), "category"),
    (lambda d: d[b.SEQ_A][0]["labels"][0]["box2d"].pop("x2"), "box"),
    (lambda d: d[b.SEQ_A][0]["labels"][0]["box2d"].update(x1="2"), "box"),
    (lambda d: d[b.SEQ_A][0]["labels"][0]["box2d"].update(x1=True), "box"),
    (lambda d: d[b.SEQ_A][0]["labels"][0]["box2d"].update(x1=20, x2=10), "box"),
    (lambda d: d[b.SEQ_A][0]["labels"][0].pop("box2d"), "box"),
    (lambda d: d[b.SEQ_A][0]["labels"][0]["box2d"].update(x1=64, x2=70), "box_outside_image"),
    (lambda d: d[b.SEQ_A][1]["labels"][0].update(category="truck"), "class_change"),
    (lambda d: d[b.SEQ_A][0]["labels"][0].update(id="has space"), "object_id"),
    (lambda d: d[b.SEQ_A][0]["labels"][0].update(id=1), "object_id"),
    (lambda d: d[b.SEQ_A][1].update(frameIndex=0), "duplicate_frame_index"),
    (lambda d: d[b.SEQ_A][1].update(videoName=b.SEQ_B), "video_name"),
    (lambda d: d[b.SEQ_A][1].update(frameIndex=-1), "frame_index"),
    (lambda d: d[b.SEQ_A][1].update(labels={"id": "1"}), "labels"),
    (lambda d: d[b.SEQ_A][0]["labels"].append("car"), "label"),
])
def test_malformed_labels_are_refused(tmp_path, change, code):
    assert refusal(tmp_path, change) == f"adapter_label_invalid:{b.SEQ_A}:{code}"


@pytest.mark.parametrize("name", ["../escape.jpg", "a/b.jpg", "C:x.jpg", ".hidden.jpg"])
def test_unsafe_frame_names_are_refused(tmp_path, name):
    documents = b.labels()
    root = b.write_source(tmp_path / "source", documents)
    documents[b.SEQ_A][0]["name"] = name
    target = root / "labels/box_track_20/val" / f"{b.SEQ_A}.json"
    target.write_text(json.dumps(documents[b.SEQ_A]), encoding="utf-8")
    document = descriptors.freeze(bdd.descriptor(), root)
    entries = descriptors.reconcile(document, root)
    with pytest.raises(S32Error, match=f"^adapter_label_invalid:{b.SEQ_A}:frame_name$"):
        ADAPTER.frame_paths(root, entries, "val", b.SEQ_A)


def test_unsafe_sequence_id_is_refused(tmp_path):
    root = b.write_source(tmp_path / "source", {"bad name": b.labels()[b.SEQ_B]})
    document = descriptors.freeze(bdd.descriptor(), root)
    entries = descriptors.reconcile(document, root)
    with pytest.raises(S32Error, match="^adapter_label_invalid:bad name:sequence_id$"):
        datasets.discover(ADAPTER, root, entries, "val")


def test_label_file_that_is_not_json_or_not_a_list_is_refused(tmp_path):
    for number, text in enumerate(["{not json", '{"frames": []}', "[]"]):
        root = b.write_source(tmp_path / f"s{number}")
        (root / "labels/box_track_20/val" / f"{b.SEQ_A}.json").write_text(text, encoding="utf-8")
        document = descriptors.freeze(bdd.descriptor(), root)
        entries = descriptors.reconcile(document, root)
        with pytest.raises(S32Error, match=f"^adapter_label_invalid:{b.SEQ_A}"):
            datasets.discover(ADAPTER, root, entries, "val")


def test_missing_frame_leaves_the_sequence_incomplete(tmp_path):
    root = b.write_source(tmp_path / "source")
    (root / "images/track/val" / b.SEQ_A / f"{b.SEQ_A}-0000003.jpg").unlink()  # frameIndex 2
    document = descriptors.freeze(bdd.descriptor(), root)
    entries = descriptors.reconcile(document, root)
    with pytest.raises(S32Error, match=f"^source_manifest_incomplete:sequence:{b.SEQ_A}$"):
        datasets.discover(ADAPTER, root, entries, "val")
    with pytest.raises(S32Error, match=f"^adapter_frame_missing:{b.SEQ_A}:2$"):
        ADAPTER.ground_truth(root, entries, document, "val", b.SEQ_A)


def test_frame_images_must_be_jpegs_of_one_size(tmp_path):
    with pytest.raises(S32Error, match=f"^adapter_frame_invalid:{b.SEQ_A}:0$"):
        gt(tmp_path / "a", image=b"P6\n1 1\n255\n\x00\x00\x00")
    root = b.write_source(tmp_path / "b" / "source")
    (root / "images/track/val" / b.SEQ_A / f"{b.SEQ_A}-0000002.jpg").write_bytes(b.jpeg_header(32, 18))
    document = descriptors.freeze(bdd.descriptor(), root)
    with pytest.raises(S32Error, match=f"^adapter_frame_invalid:{b.SEQ_A}:frame_size$"):
        ADAPTER.ground_truth(root, descriptors.reconcile(document, root), document, "val", b.SEQ_A)


@pytest.mark.parametrize("data", [b"", b"\xff\xd8", b"\xff\xd8\xff\xda\x00\x02", b"\xff\xd8\xff\xc0\x00\x40"])
def test_truncated_jpeg_headers_are_refused(data):
    with pytest.raises(S32Error, match="^bad$"):
        bdd.jpeg_size(data, "bad")


@pytest.mark.parametrize("change, field", [
    (lambda d: d.update(datasetId="synthetic-vehicles"), "datasetId"),
    (lambda d: d.update(release="MOT 2021"), "release"),
    (lambda d: d.update(task="detection"), "task"),
    (lambda d: d.update(frameTime={"kind": "index-at-fps", "fpsNumerator": 30, "fpsDenominator": 1}), "frameTime"),
    (lambda d: d["nativeTaxonomy"].pop(), "nativeTaxonomy"),
    (lambda d: d["nativeTaxonomy"].append({"code": "scooter", "name": "Scooter", "definition": "Invented."}),
     "nativeTaxonomy"),
])
def test_descriptor_semantics_that_shape_ground_truth_are_bound(tmp_path, change, field):
    root, document, entries = frozen_source(tmp_path)
    altered = copy.deepcopy(document)
    change(altered)
    with pytest.raises(S32Error, match=f"^adapter_descriptor_mismatch:{field}$"):
        ADAPTER.ground_truth(root, entries, altered, "val", b.SEQ_A)


def test_definition_wording_does_not_change_ground_truth(tmp_path):
    root, document, entries = frozen_source(tmp_path)
    reworded = copy.deepcopy(document)
    reworded["nativeTaxonomy"][0]["definition"] = "Reworded definition."
    assert ADAPTER.ground_truth(root, entries, reworded, "val", b.SEQ_A) == ADAPTER.ground_truth(
        root, entries, document, "val", b.SEQ_A)


# prepare integration (adapter registry only; the shared reconcile/encode path)


def test_prepare_resolves_the_adapter_from_the_registry():
    assert isinstance(prepare.adapter("bdd100k-mot"), bdd.Bdd100kMotAdapter)


def test_removing_one_sequence_annotation_and_frames_together_is_still_refused(tmp_path):
    root, document, _ = frozen_source(tmp_path)
    descriptor_path = tmp_path / "descriptor.json"
    descriptor_path.write_bytes(canonical_json(document))
    (root / "labels/box_track_20/val" / f"{b.SEQ_B}.json").unlink()
    shutil.rmtree(root / "images/track/val" / b.SEQ_B)
    with pytest.raises(S32Error, match=f"^source_manifest_incomplete:images/track/val/{b.SEQ_B}/"):
        prepare.prepare(descriptor_path=descriptor_path, source_root=root, split="val", adapter_id="bdd100k-mot",
                        media_tools_dir=tmp_path / "no-pack", out=tmp_path / "derived")
    assert not (tmp_path / "derived").exists()


def test_prepare_encodes_the_labelled_frames_and_writes_canonical_ground_truth(tmp_path, media_pack):
    from tools.benchmarks.core._stage3 import artefacts  # noqa: F401  (puts tools/stage3 on the path)
    import media_tools

    root = b.write_source(tmp_path / "source")
    b.encode_real_jpegs(root, media_tools.load(media_pack, "ffmpeg").path)
    document = descriptors.freeze(bdd.descriptor(), root)
    descriptor_path = tmp_path / "descriptor.json"
    descriptor_path.write_bytes(canonical_json(document))
    prepare.prepare(descriptor_path=descriptor_path, source_root=root, split="val", adapter_id="bdd100k-mot",
                    media_tools_dir=media_pack, out=tmp_path / "derived")
    manifest, _, documents = prepare.load(tmp_path / "derived")
    assert manifest["adapter"] == {"id": "bdd100k-mot", "version": "1"}
    assert manifest["frameRate"] == {"numerator": 5, "denominator": 1}
    assert [(row["sequenceId"], row["frameCount"]) for row in manifest["sequences"]] == [(b.SEQ_A, 4), (b.SEQ_B, 3)]
    entries = descriptors.reconcile(document, root)
    for sequence in (b.SEQ_A, b.SEQ_B):
        assert documents[sequence] == ADAPTER.ground_truth(root, entries, document, "val", sequence)
