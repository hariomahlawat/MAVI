"""The synthetic dataset adapter (S3.2d-1 slice 1): fixed data in, the same canonical ground truth out."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tools.benchmarks import datasets
from tools.benchmarks.core import descriptor as d
from tools.benchmarks.core.identity import S32Error, canonical_json, document_sha256
from tools.benchmarks.datasets import synthetic as s


def prepared(source, frozen):
    entries = d.reconcile(frozen, source)
    adapter = s.SyntheticAdapter()
    return entries, adapter


def test_source_is_byte_identical_across_generations(tmp_path):
    first, second = s.source_files(), s.source_files()
    assert first == second
    a, b = s.write_source(tmp_path / "a"), s.write_source(tmp_path / "b")
    assert d.manifest_entries(a) == d.manifest_entries(b)


def test_discovery_finds_exactly_the_described_sequences(source, frozen):
    entries, adapter = prepared(source, frozen)
    assert datasets.discover(adapter, source, entries, "val") == ["seq-a", "seq-b"]
    assert datasets.discover(adapter, source, entries, "train") == ["seq-c"]


def test_a_half_described_sequence_is_refused_at_discovery(tmp_path):
    source = s.write_source(tmp_path / "source")
    shutil.rmtree(source / "frames" / "val" / "seq-b")  # removed before the manifest was frozen
    frozen = d.freeze(s.descriptor(), source)
    entries, adapter = prepared(source, frozen)
    with pytest.raises(S32Error, match="^source_manifest_incomplete:sequence:seq-b$"):
        datasets.discover(adapter, source, entries, "val")


def test_ground_truth_shape_and_values(source, frozen):
    entries, adapter = prepared(source, frozen)
    gt = adapter.ground_truth(source, entries, frozen, "val", "seq-a")
    assert gt["sequenceId"] == "seq-a" and gt["frameSize"] == {"width": s.WIDTH, "height": s.HEIGHT}
    assert [instant["frameIndex"] for instant in gt["instants"]] == list(range(8))
    assert gt["instants"][3]["videoOffsetMs"] == {"numerator": 600, "denominator": 1}
    assert [track["gtTrackId"] for track in gt["tracks"]] == ["1", "2", "3"]
    assert {track["gtTrackId"]: track["nativeClass"] for track in gt["tracks"]} == {
        "1": "car", "2": "truck", "3": "pedestrian"}
    car = gt["tracks"][0]["frames"]
    assert [frame["frameIndex"] for frame in car] == list(range(8))
    assert car[0]["box"] == {"x": 1 / 32, "y": 2 / 18, "width": 6 / 32, "height": 4 / 18}
    assert car[7]["box"]["x"] == 15 / 32
    pedestrian = gt["tracks"][2]["frames"]
    assert [frame["ignore"] for frame in pedestrian] == [False, False, False, True, False]
    truck = gt["tracks"][1]["frames"]
    assert truck[0]["frameIndex"] == 2 and truck[0]["videoOffsetMs"] == {"numerator": 400, "denominator": 1}


def test_ground_truth_is_byte_identical_and_hash_stable(source, frozen, tmp_path):
    entries, adapter = prepared(source, frozen)
    first = {seq: canonical_json(adapter.ground_truth(source, entries, frozen, "val", seq)) for seq in ("seq-a", "seq-b")}
    other = s.write_source(tmp_path / "other")
    other_entries = d.reconcile(frozen, other)
    second = {seq: canonical_json(adapter.ground_truth(other, other_entries, frozen, "val", seq))
              for seq in ("seq-a", "seq-b")}
    assert first == second
    assert all(b"\r" not in data for data in first.values())
    assert s.ground_truth_sha256(json.loads(first["seq-a"])) == document_sha256(json.loads(first["seq-a"]))


def test_ground_truth_changes_with_a_native_class(source, frozen):
    entries, adapter = prepared(source, frozen)
    gt = adapter.ground_truth(source, entries, frozen, "val", "seq-a")
    changed = json.loads(canonical_json(gt))
    changed["tracks"][1]["nativeClass"] = "bus"
    assert s.ground_truth_sha256(changed) != s.ground_truth_sha256(gt)


def test_adapter_reads_only_verified_bytes(source, frozen):
    entries, adapter = prepared(source, frozen)
    path = source / s.annotation_path("val", "seq-a")
    path.write_bytes(path.read_bytes().replace(b'"truck"', b'"lorry"'))
    with pytest.raises(S32Error, match="^source_manifest_mismatch:annotations/val/seq-a.json$"):
        adapter.ground_truth(source, entries, frozen, "val", "seq-a")


@pytest.mark.parametrize("edit, code", [
    (lambda labels: labels["frames"][0]["objects"][0].update(category="lorry"), "adapter_label_invalid:seq-a:class"),
    (lambda labels: labels["frames"][0]["objects"][0].update(box=[5, 5, 5, 9]), "adapter_label_invalid:seq-a:object"),
    (lambda labels: labels["frames"][0]["objects"][0].update(box=[0, 0, 40, 4]), "adapter_label_invalid:seq-a:object"),
    (lambda labels: labels["frames"][1].update(index=0), "adapter_label_invalid:seq-a:frame_order"),
    (lambda labels: labels["frames"][5]["objects"][0].update(category="bus"),
     "adapter_label_invalid:seq-a:class_change"),
    (lambda labels: labels.update(width=64), "adapter_label_invalid:seq-a$"),
    (lambda labels: labels["frames"].__setitem__(2, None), "adapter_label_invalid:seq-a:frame$"),
    (lambda labels: labels["frames"][2].pop("index"), "adapter_label_invalid:seq-a:frame$"),
    (lambda labels: labels["frames"][2].update(index="2"), "adapter_label_invalid:seq-a:frame$"),
    (lambda labels: labels["frames"][2].update(objects="car"), "adapter_label_invalid:seq-a:frame$"),
    (lambda labels: labels["frames"][2]["objects"].append(None), "adapter_label_invalid:seq-a:frame$"),
    (lambda labels: labels["frames"][2]["objects"][0].update(id=""), "adapter_label_invalid:seq-a:object_id$"),
    (lambda labels: labels["frames"][2]["objects"][0].update(id="track 1"), "adapter_label_invalid:seq-a:object_id$"),
    (lambda labels: labels["frames"][2]["objects"][0].update(id="-1"), "adapter_label_invalid:seq-a:object_id$"),
    (lambda labels: labels["frames"][2]["objects"][0].update(id="x" * 257), "adapter_label_invalid:seq-a:object_id$"),
    (lambda labels: labels["frames"][2]["objects"][0].update(id=1), "adapter_label_invalid:seq-a:object_id$"),
    # Two boxes for native id "1" in one labelled frame: refused, never deduplicated or merged.
    (lambda labels: labels["frames"][2]["objects"].append(
        {**labels["frames"][2]["objects"][0], "box": [0, 0, 2, 2]}), "adapter_label_invalid:seq-a:duplicate_track_id$"),
])
def test_malformed_labels_are_refused(tmp_path, edit, code):
    source = s.write_source(tmp_path / "source")
    path = source / s.annotation_path("val", "seq-a")
    labels = json.loads(path.read_bytes())
    edit(labels)
    path.write_bytes(canonical_json(labels))
    frozen = d.freeze(s.descriptor(), source)
    entries, adapter = prepared(source, frozen)
    with pytest.raises(S32Error, match=f"^{code}"):
        adapter.ground_truth(source, entries, frozen, "val", "seq-a")


def test_one_box_per_gt_identity_per_labelled_instant(source, frozen):
    entries, adapter = prepared(source, frozen)
    for split, sequences in s.SEQUENCES.items():
        for sequence in sequences:
            gt = adapter.ground_truth(source, entries, frozen, split, sequence)
            for track in gt["tracks"]:
                indices = [frame["frameIndex"] for frame in track["frames"]]
                assert len(indices) > 1 and indices == sorted(set(indices))  # one id across frames is valid
                assert s.GT_TRACK_ID.fullmatch(track["gtTrackId"])


def test_track_id_rule_matches_the_association_contract():
    schema = json.loads((Path(__file__).resolve().parents[3] / "contracts" / "schemas" /
                         "benchmark-association-v1.schema.json").read_text(encoding="utf-8"))
    gt_track_id = schema["$defs"]["gtEntry"]["properties"]["gtTrackId"]
    assert gt_track_id["pattern"] == "^" + s.GT_TRACK_ID.pattern.replace("{0,255}", "*") + "$"
    assert gt_track_id["maxLength"] == 256 and gt_track_id["minLength"] == 1


def test_malformed_nested_labels_are_refused_at_discovery_too(tmp_path):
    source = s.write_source(tmp_path / "source")
    path = source / s.annotation_path("val", "seq-a")
    labels = json.loads(path.read_bytes())
    labels["frames"][0] = None
    path.write_bytes(canonical_json(labels))
    frozen = d.freeze(s.descriptor(), source)
    entries, adapter = prepared(source, frozen)
    with pytest.raises(S32Error, match="^adapter_label_invalid:seq-a:frame$"):
        datasets.discover(adapter, source, entries, "val")


def test_labelled_frame_without_an_image_is_refused(tmp_path):
    source = s.write_source(tmp_path / "source")
    (source / s.frame_path("val", "seq-a", 6)).unlink()
    frozen = d.freeze(s.descriptor(), source)
    entries, adapter = prepared(source, frozen)
    with pytest.raises(S32Error, match="^adapter_frame_missing:seq-a:6$"):
        adapter.ground_truth(source, entries, frozen, "val", "seq-a")
    with pytest.raises(S32Error, match="^source_manifest_incomplete:sequence:seq-a$"):
        datasets.discover(adapter, source, entries, "val")


def test_adapter_identity_and_classes():
    adapter = s.SyntheticAdapter()
    assert (adapter.adapter_id, adapter.adapter_version) == ("synthetic", "1")
    assert adapter.native_classes() == set(d.native_classes(s.descriptor()))
