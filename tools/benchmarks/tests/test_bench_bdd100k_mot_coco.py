"""The derived (COCO-format) BDD100K MOT val adapter, on synthetic fixtures (no dataset bytes).

The fixture annotation is made from the raw Scalabel fixtures by an independent re-statement of the official
conversion, so the central discriminating test compares derived ground truth with the raw adapter's on the same
labels. Tests pin the fixture's own SHA-256 in place of the real derivative's (one test proves the real pin).
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import bdd_coco_fixtures as c
import bdd_fixtures as b
from tools.benchmarks import datasets, prepare
from tools.benchmarks.capabilities.vehicle_tracks import ground_truth as gt_module
from tools.benchmarks.core import descriptor as descriptors
from tools.benchmarks.core import mapping as mappings
from tools.benchmarks.core._stage3 import ROOT
from tools.benchmarks.core.identity import S32Error, canonical_json
from tools.benchmarks.datasets import bdd100k_mot as raw
from tools.benchmarks.datasets import bdd100k_mot_coco as cc

TEMPLATE = ROOT / "docs/qualification/stage3/benchmarks/bdd100k-mot-2020-cocofmt.descriptor-template.json"
MAPPING = ROOT / "docs/qualification/stage3/benchmarks/bdd100k-mot-2020-cocofmt.mapping.json"


def source(tmp_path: Path, monkeypatch, document=None, **kwargs):
    root = c.write_source(tmp_path / "source", document, **kwargs)
    monkeypatch.setattr(cc, "ANNOTATION_SHA256", hashlib.sha256((root / c.ANNOTATION).read_bytes()).hexdigest())
    frozen = descriptors.freeze(cc.descriptor(), root)
    return root, frozen, descriptors.reconcile(frozen, root)


def gt(tmp_path, monkeypatch, sequence=b.SEQ_A, document=None, **kwargs):
    root, frozen, entries = source(tmp_path, monkeypatch, document, **kwargs)
    return cc.Bdd100kMotCocoAdapter().ground_truth(root, entries, frozen, "val", sequence)


def refusal(tmp_path, monkeypatch, change, sequence=b.SEQ_A) -> str:
    document = c.convert(b.labels())
    change(document)
    with pytest.raises(S32Error) as caught:
        gt(tmp_path, monkeypatch, sequence, document)
    return str(caught.value)


def raw_gt(tmp_path, sequence):
    root = b.write_source(tmp_path / "raw")
    frozen = descriptors.freeze(raw.descriptor(), root)
    return raw.Bdd100kMotAdapter().ground_truth(root, descriptors.reconcile(frozen, root), frozen, "val", sequence)


# Provenance, template, mapping


def test_committed_template_and_mapping_are_the_canonical_renderings():
    assert TEMPLATE.read_bytes() == canonical_json(cc.descriptor())
    assert MAPPING.read_bytes() == canonical_json(cc.mapping())
    template, _ = descriptors.load(TEMPLATE)
    assert template["manifest"]["entries"] == []
    assert template["datasetId"] != raw.DATASET_ID and "derivative" in template["release"]
    assert template["source"]["kind"] == "research-mirror" and cc.ANNOTATION_SHA256 in \
        template["source"]["credibilityBasis"]


def test_the_real_derivative_is_pinned():
    assert cc.ANNOTATION_SHA256 == "074ff79555483296cf7ccadddeeceeec7a83452c900506dc46588ed3a3e65d5d"


def test_mapping_scores_exactly_the_four_v1_classes():
    rows = mappings.check_against(cc.mapping(), cc.descriptor())
    mappings.require_emitted(rows, cc.Bdd100kMotCocoAdapter().native_classes())
    assert {k: r["maviClass"] for k, r in rows.items() if r["kind"] == "exact"} == {
        "car": "car", "truck": "truck", "bus": "bus", "motorcycle": "motorcycle"}
    assert all(r.get("unsupportedKind") == "outside-capability" for r in rows.values() if r["kind"] != "exact")
    assert not {"trailer", "van", "caravan", "other-vehicle"} & set(rows)  # never claimed as measured classes


def test_a_different_annotation_is_refused_before_it_is_parsed(tmp_path, monkeypatch):
    root, frozen, entries = source(tmp_path, monkeypatch, document={"not": "the converter output"})
    monkeypatch.setattr(cc, "ANNOTATION_SHA256", "0" * 64)
    with pytest.raises(S32Error, match="^adapter_source_unverified:annotation_sha256$"):
        datasets.discover(cc.Bdd100kMotCocoAdapter(), root, entries, "val")


def test_a_missing_annotation_is_refused(tmp_path, monkeypatch):
    root = c.write_source(tmp_path / "source")
    (root / c.ANNOTATION).unlink()
    frozen = descriptors.freeze(cc.descriptor(), root)
    with pytest.raises(S32Error, match=f"^source_manifest_incomplete:{c.ANNOTATION}$"):
        datasets.discover(cc.Bdd100kMotCocoAdapter(), root, descriptors.reconcile(frozen, root), "val")


def test_registry_and_descriptor_binding(tmp_path, monkeypatch):
    assert isinstance(prepare.adapter("bdd100k-mot-coco"), cc.Bdd100kMotCocoAdapter)
    root, frozen, entries = source(tmp_path, monkeypatch)
    with pytest.raises(S32Error, match="^adapter_descriptor_mismatch:datasetId$"):
        cc.Bdd100kMotCocoAdapter().ground_truth(root, entries, raw.descriptor(), "val", b.SEQ_A)


# Semantics


def test_derived_ground_truth_equals_the_raw_adapters_except_distractors(tmp_path, monkeypatch):
    for sequence in (b.SEQ_A, b.SEQ_B):
        derived = gt_module.validate(gt(tmp_path / sequence, monkeypatch, sequence))
        reference = raw_gt(tmp_path / sequence, sequence)
        assert derived["instants"] == reference["instants"] and derived["frameSize"] == reference["frameSize"]
        official = {"van": "car", "other-vehicle": "car"}  # the official name and ignored mappings
        reference_tracks = {t["gtTrackId"]: t for t in reference["tracks"]}
        for track in derived["tracks"]:
            other = reference_tracks.pop(track["gtTrackId"])  # identity: the raw label id, not instance_id
            assert track["nativeClass"] == official.get(other["nativeClass"], other["nativeClass"])
            assert [f["box"] for f in track["frames"]] == [f["box"] for f in other["frames"]]  # inclusive boxes
            assert [f["frameIndex"] for f in track["frames"]] == [f["frameIndex"] for f in other["frames"]]
            if other["nativeClass"] != "other-vehicle":  # the only distractor: ignored on the derived path
                assert track["frames"] == other["frames"]  # including ignore, for genuine crowd too
        assert not reference_tracks


def test_genuine_crowd_is_ordinary_gt_and_a_distractor_is_ignored(tmp_path, monkeypatch):
    a = {t["gtTrackId"]: t for t in gt(tmp_path / "a", monkeypatch, b.SEQ_A)["tracks"]}
    assert a["3"]["nativeClass"] == "pedestrian" and len(a["3"]["frames"]) == 2
    assert not any(f["ignore"] for t in a.values() for f in t["frames"])  # crowd (1, 0) is ordinary GT
    document = c.convert(b.labels())
    assert {(a["scalabel_id"], a["iscrowd"], a["ignore"]) for a in document["annotations"]
            if a["iscrowd"]} == {("3", 1, 0), ("8", 1, 1)}  # crowd vs former distractor
    bb = {t["gtTrackId"]: t for t in gt(tmp_path / "b", monkeypatch, b.SEQ_B)["tracks"]}
    assert bb["8"]["nativeClass"] == "car" and all(f["ignore"] for f in bb["8"]["frames"])  # 'other vehicle'
    assert bb["9"]["nativeClass"] == "car" and not any(f["ignore"] for f in bb["9"]["frames"])  # 'van' folded


def test_iscrowd_alone_never_marks_a_frame_ignored(tmp_path, monkeypatch):
    document = c.convert(b.labels())
    reference = gt(tmp_path / "a", monkeypatch, b.SEQ_A, copy.deepcopy(document))
    next(a for a in document["annotations"] if a["scalabel_id"] == "1" and a["image_id"] == 1)["iscrowd"] = 1
    assert gt(tmp_path / "b", monkeypatch, b.SEQ_A, document) == reference


def test_flipping_ignore_from_0_to_1_changes_only_that_frames_ignore(tmp_path, monkeypatch):
    document = c.convert(b.labels())
    reference = gt(tmp_path / "a", monkeypatch, b.SEQ_A, copy.deepcopy(document))
    target = next(a for a in document["annotations"] if a["scalabel_id"] == "3" and a["image_id"] == 1)
    assert (target["iscrowd"], target["ignore"]) == (1, 0)  # a genuine crowd pedestrian
    target["ignore"] = 1
    mutated = gt(tmp_path / "b", monkeypatch, b.SEQ_A, document)
    changed = [(t["gtTrackId"], f["frameIndex"]) for t, u in zip(reference["tracks"], mutated["tracks"])
               for f, g in zip(t["frames"], u["frames"]) if f != g]
    assert changed == [("3", 0)]
    track = next(t for t in mutated["tracks"] if t["gtTrackId"] == "3")
    assert [f["ignore"] for f in track["frames"]] == [True, False]


def test_genuine_crowd_reaches_association_exactly_as_on_the_raw_path(tmp_path, monkeypatch):
    # Association reads only the class-free projection, so equal projections mean the frozen policy treats the
    # genuine-crowd track identically on both paths.
    derived = gt_module.project(gt(tmp_path / "d", monkeypatch, b.SEQ_A))
    reference = gt_module.project(raw_gt(tmp_path / "r", b.SEQ_A))
    assert derived.instants == reference.instants and derived.ignore_regions == reference.ignore_regions
    crowd = [next(t for t in s.tracks if t.gt_track_id == "3") for s in (derived, reference)]
    assert crowd[0] == crowd[1] and not any(frame.ignore for frame in crowd[0].frames)


def test_a_track_whose_class_changes_is_ignored_evidence_not_scored(tmp_path, monkeypatch):
    document = c.convert(b.labels())
    frame3 = {i["id"] for i in document["images"] if i["frame_id"] == 3 and i["video_id"] == 1}
    next(a for a in document["annotations"] if a["scalabel_id"] == "1" and a["image_id"] in frame3)["category_id"] = 4
    tracks = {t["gtTrackId"]: t for t in gt(tmp_path, monkeypatch, b.SEQ_A, document)["tracks"]}
    assert tracks["1"]["nativeClass"] == "car" and all(f["ignore"] for f in tracks["1"]["frames"])
    assert not any(f["ignore"] for f in tracks["2"]["frames"])  # other tracks untouched


def test_frame_paths_come_from_file_name(tmp_path, monkeypatch):
    root, frozen, entries = source(tmp_path, monkeypatch)
    adapter = cc.Bdd100kMotCocoAdapter()
    assert datasets.discover(adapter, root, entries, "val") == [b.SEQ_A, b.SEQ_B]
    assert adapter.frame_paths(root, entries, "val", b.SEQ_B)[0] == (
        0, f"images/track/val/{b.SEQ_B}/{b.SEQ_B}-0000001.jpg")


# Fail closed


def _first(document, key):
    return document[key][0]


@pytest.mark.parametrize("change, code", [
    (lambda d: d.update(info={}), "annotation:fields"),
    (lambda d: d["categories"].reverse(), "annotation:categories"),
    (lambda d: _first(d, "annotations").update(ignore=1), f"{b.SEQ_A}:crowd"),  # ignore without iscrowd
    (lambda d: _first(d, "annotations").update(iscrowd=1, ignore=1, category_id=5), f"{b.SEQ_A}:ignore_category"),
    (lambda d: _first(d, "annotations").update(iscrowd=2), f"{b.SEQ_A}:crowd"),
    (lambda d: _first(d, "annotations").update(iscrowd=True), f"{b.SEQ_A}:crowd"),
    (lambda d: _first(d, "annotations").update(category_id=9), f"{b.SEQ_A}:category"),
    (lambda d: _first(d, "annotations").update(bbox=[2, 3, 0, 8]), f"{b.SEQ_A}:box"),
    (lambda d: _first(d, "annotations").update(bbox=[2, 3, 12]), f"{b.SEQ_A}:box"),
    (lambda d: _first(d, "annotations").update(scalabel_id=5), f"{b.SEQ_A}:object_id"),
    (lambda d: _first(d, "annotations").update(instance_id=2), f"{b.SEQ_A}:instance_id"),
    (lambda d: d["annotations"].append(dict(_first(d, "annotations"), id=10_000)), f"{b.SEQ_A}:duplicate_track_id"),
    (lambda d: _first(d, "annotations").pop("area"), "annotation:annotation"),
    (lambda d: _first(d, "images").update(file_name="elsewhere/x.jpg"), f"{b.SEQ_A}:file_name"),
    (lambda d: _first(d, "images").update(file_name=f"{b.SEQ_A}/../x.jpg"), f"{b.SEQ_A}:file_name"),
    (lambda d: d["images"][1].update(frame_id=0), f"{b.SEQ_A}:duplicate_frame_index"),
    (lambda d: _first(d, "images").update(width=1280), f"{b.SEQ_A}:frame_size"),
    (lambda d: _first(d, "videos").update(name="bad name"), "annotation:video"),
])
def test_malformed_derived_annotations_are_refused(tmp_path, monkeypatch, change, code):
    assert refusal(tmp_path, monkeypatch, change) == f"adapter_label_invalid:{code}"


def test_declared_size_must_match_the_frames(tmp_path, monkeypatch):
    document = c.convert(b.labels())
    for image in document["images"]:
        image.update(width=32, height=18)
    with pytest.raises(S32Error, match=f"^adapter_frame_invalid:{b.SEQ_A}:frame_size$"):
        gt(tmp_path, monkeypatch, b.SEQ_A, document)


def test_an_annotated_video_without_its_images_is_refused(tmp_path, monkeypatch):
    videos = b.labels()
    del videos[b.SEQ_B]
    root, frozen, entries = source(tmp_path, monkeypatch, videos=videos)
    with pytest.raises(S32Error, match=f"^source_manifest_incomplete:sequence:{b.SEQ_B}$"):
        datasets.discover(cc.Bdd100kMotCocoAdapter(), root, entries, "val")


def test_images_of_an_unannotated_video_are_refused(tmp_path, monkeypatch):
    videos = b.labels()
    videos["f0000003-c0000003"] = copy.deepcopy(videos[b.SEQ_B])
    for frame in videos["f0000003-c0000003"]:
        frame["videoName"] = "f0000003-c0000003"
        frame["name"] = frame["name"].replace(b.SEQ_B, "f0000003-c0000003")
    root, frozen, entries = source(tmp_path, monkeypatch, videos=videos)
    with pytest.raises(S32Error, match="^source_manifest_incomplete:sequence:f0000003-c0000003$"):
        datasets.discover(cc.Bdd100kMotCocoAdapter(), root, entries, "val")


def test_only_the_val_split_is_supported(tmp_path, monkeypatch):
    root, frozen, entries = source(tmp_path, monkeypatch)
    with pytest.raises(S32Error, match="^adapter_split_unsupported:train$"):
        cc.Bdd100kMotCocoAdapter().discover(root, entries, "train")


# Lineage check


def test_lineage_is_consistent_for_an_official_conversion():
    document = c.convert(b.labels())
    for video, frames in b.labels().items():
        report = cc.lineage(document, frames)
        assert report["mismatches"] == [] and report["rawFrames"] == report["derivedFrames"]
        assert report["comparedBoxes"] == sum(len(f["labels"]) for f in frames)


def test_a_uniform_raw_id_prefix_is_reported_unless_declared():
    # The pinned Scalabel reference writes 'a-00122062' where the derivative records '00122062'.
    raw_frames = [dict(frame, labels=[dict(label, id=f"a-{label['id']}") for label in frame["labels"]])
                  for frame in b.labels()[b.SEQ_A]]
    document = c.convert(b.labels())
    assert {m[0] for m in cc.lineage(document, raw_frames)["mismatches"]} == {"track_ids"}
    assert cc.lineage(document, raw_frames, raw_id=lambda v: v.removeprefix("a-"))["mismatches"] == []


@pytest.mark.parametrize("change, kind", [
    (lambda d: d["images"].append(dict(d["images"][0], id=9_999, frame_id=99)), "frame_missing_in_raw"),
    (lambda d: d["images"].pop(1), "frame_missing_in_derived"),
    (lambda a: a.update(bbox=[a["bbox"][0] + 1, *a["bbox"][1:]]), "bbox"),
    (lambda a: a.update(iscrowd=1 - a["iscrowd"]), "crowd"),
    (lambda a: a.update(ignore=1), "ignore"),
    (lambda a: a.update(category_id=a["category_id"] % 8 + 1), "category"),
    (lambda a: a.update(scalabel_id="999"), "track_ids"),
])
def test_lineage_reports_each_material_difference(change, kind):
    document = c.convert(b.labels())
    if kind.startswith("frame_missing"):
        change(document)  # an image record with no annotations, or a dropped one: frame sets must still match
        document["annotations"] = [a for a in document["annotations"]
                                   if a["image_id"] in {i["id"] for i in document["images"]}]
    else:
        change(document["annotations"][0])
    report = cc.lineage(document, b.labels()[b.SEQ_A])
    assert [m[0] for m in report["mismatches"]] == [kind]


def test_derived_annotation_parse_is_reused_not_repeated(tmp_path, monkeypatch):
    root, frozen, entries = source(tmp_path, monkeypatch)
    adapter = cc.Bdd100kMotCocoAdapter()
    calls = []
    original = cc.parse
    monkeypatch.setattr(cc, "parse", lambda data: calls.append(1) or original(data))
    adapter.discover(root, entries, "val")
    adapter.ground_truth(root, entries, frozen, "val", b.SEQ_A)
    adapter.frame_paths(root, entries, "val", b.SEQ_B)
    assert len(calls) == 1
    assert json.loads((root / c.ANNOTATION).read_text())["videos"][0]["name"] == b.SEQ_A
