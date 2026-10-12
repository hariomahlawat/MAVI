"""UFPR-ALPR and VOC plate adapters on fixture trees, and the truth → E-A → verdict command path."""

from __future__ import annotations

import json

import numpy as np
import pytest

from tools.benchmarks.capabilities.plates import instruments, truth as truths
from tools.benchmarks.core import descriptor as descriptors
from tools.benchmarks.core._stage3 import ROOT
from tools.benchmarks.core.identity import S32Error, canonical_json, sha256_hex
from tools.benchmarks.datasets import uc3m_lp, ufpr_alpr, voc_plates
from tools.benchmarks.plates import cli
from plate_fixtures import SpecHeightInstrument, jpeg, scene, ufpr_annotation, write_spec, write_ufpr

TOOLING = {"toolingCommit": "0" * 40, "toolingSha256": "0" * 64, "toolingFiles": [{"path": "x", "sha256": "0" * 64}]}


def _good(index):
    return ufpr_annotation((5, 5, 50, 38), (20, 30, 16, 6), "ABC-1234")


def _ufpr(tmp_path, sequences):
    root = write_ufpr(tmp_path / "source", sequences)
    frozen = descriptors.freeze(ufpr_alpr.descriptor(), root)
    path = tmp_path / "descriptor.json"
    path.write_bytes(canonical_json(frozen))
    return root, frozen, path


def test_ufpr_descriptor_and_discovery(tmp_path):
    root, frozen, _ = _ufpr(tmp_path, {"track0001": {"split": "testing", "annotation": _good},
                                       "track0002": {"split": "testing", "annotation": _good, "frames": 29},
                                       "track0003": {"split": "training", "annotation": _good}})
    entries = descriptors.reconcile(frozen, root)
    adapter = ufpr_alpr.UfprAlprAdapter()
    assert adapter.discover(root, entries, "testing") == ["track0001"]  # the 29-frame sequence has a gap
    gt = adapter.ground_truth(root, entries, frozen, "testing", "track0001")
    assert gt["tracks"][0]["nativeClass"] == "car" and len(gt["tracks"][0]["frames"]) == 30
    assert gt["tracks"][0]["frames"][0]["box"] == {"x": 5 / 64, "y": 5 / 48, "width": 50 / 64, "height": 38 / 48}
    items, exclusions = adapter.plate_items(root, entries, "testing", "track0001")
    assert len(items) == 30 and exclusions == []
    plate = items[0]["plates"][0]
    assert (plate["text"], plate["textUsable"], plate["layout"], plate["lineCount"]) == ("ABC-1234", True,
                                                                                       "one-line", 1)
    assert items[0]["imageSha256"] == sha256_hex((root / items[0]["imagePath"]).read_bytes())


@pytest.mark.parametrize("annotation,reason", [
    (ufpr_annotation((5, 5, 50, 38), (20, 30, 16, 6), extra="colour: red\n"), "unknown-key"),
    (b"camera: x\nposition_vehicle: 1 1 2 2\ntype: car\nposition_plate: 1 1 2 2\n", "missing-plate"),
    (ufpr_annotation((5, 5, 50, 38), (20, 30, 16, 6), kind="truck"), "type"),
    (ufpr_annotation((5, 5, 70, 38), (20, 30, 16, 6)), "box-outside-image"),
    (ufpr_annotation((5, 5, 50, 38), (20, 30, 0, 6)), "plate-box"),
])
def test_ufpr_refuses_malformed_annotations(tmp_path, annotation, reason):
    root, frozen, _ = _ufpr(tmp_path, {"track0001": {"split": "testing",
                                                     "annotation": lambda i: annotation if i == 3 else _good(i)}})
    entries = descriptors.reconcile(frozen, root)
    adapter = ufpr_alpr.UfprAlprAdapter()
    items, exclusions = adapter.plate_items(root, entries, "testing", "track0001")
    assert len(items) == 29 and exclusions == [{"path": "testing/track0001/track0001[04].txt", "reason": reason}]
    with pytest.raises(S32Error):
        adapter.ground_truth(root, entries, frozen, "testing", "track0001")


def test_ufpr_motorcycle_plate_is_two_line(tmp_path):
    def moto(index):
        return ufpr_annotation((5, 5, 50, 38), (20, 30, 12, 10), "ABC1234", kind="motorcycle")
    root, frozen, _ = _ufpr(tmp_path, {"track0009": {"split": "testing", "annotation": moto}})
    items, _ = ufpr_alpr.UfprAlprAdapter().plate_items(root, descriptors.reconcile(frozen, root), "testing",
                                                       "track0009")
    assert (items[0]["vehicleClass"], items[0]["plates"][0]["layout"], items[0]["plates"][0]["lineCount"]) == (
        "motorcycle", "two-line", 2)


def test_truth_command_refuses_a_tampered_source(tmp_path):
    root, _, descriptor_path = _ufpr(tmp_path, {"track0001": {"split": "testing", "annotation": _good}})
    (root / "testing" / "track0001" / "track0001[01].txt").write_bytes(b"camera: tampered\n")
    with pytest.raises(S32Error, match="source_manifest_mismatch"):
        cli.build_truth(descriptor_path, root, ufpr_alpr.ADAPTER_ID, "testing")


# VOC


def _voc(name="number_plate", text_attribute=True, size=(320, 240), box=(100, 120, 180, 150), dtd=False):
    attributes = "<attribute><name>rotation</name><value>0.0</value></attribute>"
    if text_attribute:
        attributes += "<attribute><name>number_plate_text</name><value>KA 01 AB 1234</value></attribute>"
    head = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e "x">]>' if dtd else ""
    return (f"{head}<annotation><size><width>{size[0]}</width><height>{size[1]}</height></size><object>"
            f"<name>{name}</name><occluded>0</occluded><bndbox><xmin>{box[0]}</xmin><ymin>{box[1]}</ymin>"
            f"<xmax>{box[2]}</xmax><ymax>{box[3]}</ymax></bndbox><attributes>{attributes}</attributes></object>"
            f"</annotation>").encode("utf-8")


def _voc_tree(tmp_path, annotations):
    root = tmp_path / "voc"
    (root / "Annotations").mkdir(parents=True)
    (root / "images").mkdir()
    for stem, data in annotations.items():
        (root / "images" / f"{stem}.jpg").write_bytes(jpeg(scene(320, 240)))
        (root / "Annotations" / f"{stem}.xml").write_bytes(data)
    frozen = descriptors.freeze(voc_plates.descriptor("0" * 40), root)
    return root, descriptors.reconcile(frozen, root)


def test_voc_reads_text_and_marks_unlabelled(tmp_path):
    root, entries = _voc_tree(tmp_path, {"image_0001": _voc(text_attribute=False), "image_0002": _voc()})
    items, exclusions = voc_plates.VocPlatesAdapter().plate_items(root, entries)
    assert exclusions == []
    assert items[0]["plates"][0]["textUnusableReason"] == "unlabelled"
    assert items[1]["plates"][0]["text"] == "KA 01 AB 1234" and items[1]["plates"][0]["textUsable"]
    assert items[1]["vehicleBox"] is None and items[1]["plates"][0]["occluded"] is False


@pytest.mark.parametrize("data,reason", [
    (_voc(dtd=True), "dtd"), (_voc(size=(321, 240)), "size-mismatch"), (_voc(name="car"), "object-name"),
    (_voc(box=(100, 120, 400, 150)), "box-outside-image"), (b"<annotation>", "xml"),
])
def test_voc_refusals_are_listed(tmp_path, data, reason):
    root, entries = _voc_tree(tmp_path, {"image_0001": data})
    items, exclusions = voc_plates.VocPlatesAdapter().plate_items(root, entries)
    assert items == [] and exclusions == [{"path": "Annotations/image_0001.xml", "reason": reason}]


def test_voc_unpaired_files_are_a_manifest_refusal(tmp_path):
    root, entries = _voc_tree(tmp_path, {"image_0001": _voc()})
    entries.pop("images/image_0001.jpg")
    with pytest.raises(S32Error, match="unpaired"):
        voc_plates.VocPlatesAdapter().plate_items(root, entries)


# Instruments and the command path


@pytest.fixture
def fixture_adapter(monkeypatch):
    monkeypatch.setitem(instruments.ADAPTERS, "fixture-height", SpecHeightInstrument)


def test_instrument_model_files_are_verified(tmp_path, fixture_adapter):
    spec = write_spec(tmp_path, tmp_path / "models", "inst-a", "generic", "X", 1)
    assert instruments.load(spec, tmp_path / "models").identity()["instrumentSha256"]
    (tmp_path / "models" / "inst-a" / "weights.bin").write_bytes(b"tampered")
    with pytest.raises(S32Error, match="model_sha256"):
        instruments.load(spec, tmp_path / "models")
    (tmp_path / "models" / "inst-a" / "extra.bin").write_bytes(b"x")
    with pytest.raises(S32Error, match="model_files"):
        instruments.load(spec, tmp_path / "models")


def test_truth_to_encoding_loss_to_verdict(tmp_path, fixture_adapter):
    def annotation(index):
        return ufpr_annotation((100, 80, 900, 700), (400, 600, 150, 40), "ABC-1234")
    root, _, descriptor_path = _ufpr(tmp_path, {"track0001": {"split": "testing", "annotation": annotation,
                                                              "size": (1280, 960)}})
    truth_path = tmp_path / "truth.json"
    cli._write(cli.build_truth(descriptor_path, root, ufpr_alpr.ADAPTER_ID, "testing"), truth_path,
               truths.SCHEMA)
    models = tmp_path / "models"
    specs = [write_spec(tmp_path, models, "inst-a", "generic", "ABC1234", 1),
             write_spec(tmp_path, models, "inst-b", "plate-specific", "ABC1234", 1)]
    ea = cli.run_ea(truth_path=truth_path, descriptor_path=descriptor_path, source_root=root,
                    instrument_specs=specs, model_root=models, tooling=TOOLING)
    assert len(ea["rows"]) == 30 and ea["summary"]["counts"]["textUsable"] == 30
    # 30 plates are below the 50-plate support floor: h_min, and therefore the verdict, are NOT MEASURED.
    assert ea["summary"]["hMin"]["notMeasuredReason"] == "top_bin_insufficient"
    ea_path = tmp_path / "ea.json"
    cli._write(ea, ea_path, cli.RESULT)
    verdict = cli.run_verdict(ea_path=ea_path, eb_path=None, tooling=TOOLING)
    assert verdict["summary"]["verdict"] == "NOT_MEASURED"
    assert "coverage_not_measured" in verdict["summary"]["reasons"]
    with pytest.raises(S32Error, match="two_instruments_required"):
        cli.run_ea(truth_path=truth_path, descriptor_path=descriptor_path, source_root=root,
                   instrument_specs=specs[:1], model_root=models, tooling=TOOLING)
    assert json.loads(ea_path.read_bytes())["protocol"]["path"] == cli.PROTOCOL


# Committed release records


@pytest.mark.parametrize("name,document", [
    ("ufpr-alpr", lambda: ufpr_alpr.descriptor()),
    ("uc3m-lp", lambda: uc3m_lp.descriptor()),
    ("datacluster-indian-number-plates-sample",
     lambda: voc_plates.descriptor("2bb7cd4e46e58af4f6fa413ce8e205ac69e605a7")),
])
def test_committed_descriptor_templates_are_the_adapters_descriptors(name, document):
    path = ROOT / "docs/qualification/stage4/benchmarks" / f"{name}.descriptor-template.json"
    assert path.read_bytes() == canonical_json(document())


# UC3M-LP


def _uc3m_json(stem, size=(320, 240), lp_id="AD-24*0JV*", polygon=((100, 120), (180, 118), (181, 140), (101, 142))):
    return json.dumps({"imagePath": "unrelated.jpg", "imageWidth": size[0], "imageHeight": size[1],
                       "lps": [{"lp_id": lp_id, "poly_coord": [list(p) for p in polygon], "characters": []}]}).encode()


def _uc3m_tree(tmp_path, annotations, listed=None):
    root = tmp_path / "uc3m"
    (root / "test").mkdir(parents=True)
    for stem, data in annotations.items():
        (root / "test" / f"{stem}.jpg").write_bytes(jpeg(scene(320, 240)))
        (root / "test" / f"{stem}.json").write_bytes(data)
    (root / "test.txt").write_text("\n".join(listed if listed is not None else sorted(annotations)) + "\n")
    frozen = descriptors.freeze(uc3m_lp.descriptor(), root)
    return root, descriptors.reconcile(frozen, root)


def test_uc3m_masked_plate_lighting_and_layout(tmp_path):
    root, entries = _uc3m_tree(tmp_path, {"00001": _uc3m_json("00001"),
                                          "00002": _uc3m_json("00002", lp_id="BN-1234***")})
    items, exclusions = uc3m_lp.Uc3mLpAdapter().plate_items(root, entries, "test")
    assert exclusions == []
    first, second = items[0]["plates"][0], items[1]["plates"][0]
    assert (first["text"], first["maskedCharacters"], first["illumination"], first["layout"]) == (
        "24*0JV*", 2, "day", "one-line")
    assert (second["illumination"], second["layout"], items[1]["vehicleClass"]) == ("night", "two-line", "motorcycle")
    assert items[0]["vehicleBox"] is None and items[0]["imagePath"] == "test/00001.jpg"


@pytest.mark.parametrize("data,reason", [
    (_uc3m_json("x", size=(321, 240)), "size-mismatch"), (_uc3m_json("x", lp_id="FD-123"), "lp-id"),
    (_uc3m_json("x", polygon=((1, 1), (2, 2), (3, 3))), "polygon"),
    (_uc3m_json("x", polygon=((1, 1), (400, 2), (3, 3), (4, 4))), "polygon-outside-image"), (b"{", "json"),
])
def test_uc3m_refusals_are_listed(tmp_path, data, reason):
    root, entries = _uc3m_tree(tmp_path, {"00001": data})
    items, exclusions = uc3m_lp.Uc3mLpAdapter().plate_items(root, entries, "test")
    assert items == [] and exclusions == [{"path": "test/00001.json", "reason": reason}]


def test_uc3m_split_list_must_match_the_files(tmp_path):
    root, entries = _uc3m_tree(tmp_path, {"00001": _uc3m_json("00001")}, listed=["00001", "00002"])
    with pytest.raises(S32Error, match="split_list"):
        uc3m_lp.Uc3mLpAdapter().plate_items(root, entries, "test")


def test_vehicle_candidates_must_bind_the_truth():
    with pytest.raises(S32Error):
        path = ROOT / "contracts" / "test-vectors" / "plate-normalisation-v1.json"  # not a candidates file
        cli._candidates(path, "0" * 64)


# Bounded annotation (protocol R8) and the BDD plate-label adapter


def _proposals():
    def frame(path, plate, oracle=True, evidence=False):
        return {"vehicleBox": [100.0, 100.0, 500.0, 400.0], "oracleCandidate": oracle, "evidenceFrame": evidence,
                "imagePath": path, "plate": plate}
    big = {"box": [250.0, 300.0, 330.0, 325.0], "confidence": 0.9}
    small = {"box": [250.0, 300.0, 270.0, 306.0], "confidence": 0.8}
    return {"schemaVersion": "benchmark-plate-proposals-v1", "descriptorSha256": "d" * 64, "tracks": [
        {"sequenceId": "s1", "gtTrackId": "7", "nativeClass": "car", "maviTrackId": "m",
         "frames": {"3": frame("img/a.jpg", big), "4": frame("img/b.jpg", small, evidence=True), "5": frame("img/c.jpg", None)}},
        {"sequenceId": "s1", "gtTrackId": "8", "nativeClass": "truck", "maviTrackId": None,
         "frames": {"3": frame("img/a.jpg", small)}},
        {"sequenceId": "s0", "gtTrackId": "1", "nativeClass": "bus", "maviTrackId": None,
         "frames": {"0": frame("img/z.jpg", big)}}]}


def test_candidates_are_numbered_deterministically_and_need_a_wide_plate():
    from tools.benchmarks.plates import annotate

    found = annotate.candidates(_proposals())
    assert [(c["candidate"], c["sequenceId"], c["gtTrackId"], c["bestFrame"]) for c in found] == [
        ("T0001", "s0", "1", "0"), ("T0002", "s1", "7", "3")]


def test_labels_keep_only_verified_text_and_accepted_geometry(tmp_path):
    from tools.benchmarks.plates import annotate

    proposals = tmp_path / "p.json"
    proposals.write_text(json.dumps(_proposals()))
    decisions = tmp_path / "d.json"
    decisions.write_text(json.dumps({"verifier": {"method": "blind visual transcription"},
                                     "texts": {"T0001": None, "T0002": "7ABC123"},
                                     "rejectedGeometry": ["T0002/4"]}))
    annotate.labels(proposals_path=proposals, decisions_path=decisions, out=tmp_path / "labels.json")
    labels = json.loads((tmp_path / "labels.json").read_bytes())
    t1, t2 = labels["tracks"]
    assert t1["text"] is None and list(t1["frames"]) == ["0"]
    assert t2["text"] == "7ABC123" and list(t2["frames"]) == ["3"]  # frame 4 rejected, frame 5 had no proposal
    undecided = tmp_path / "u.json"
    undecided.write_text(json.dumps({"verifier": {"method": "x"}, "texts": {"T0001": None}}))
    with pytest.raises(S32Error, match="undecided:T0002"):
        annotate.labels(proposals_path=proposals, decisions_path=undecided, out=tmp_path / "labels2.json")


def test_bdd_plate_labels_become_sequence_truth(tmp_path):
    from tools.benchmarks.datasets import bdd_plate_labels
    from tools.benchmarks.plates import annotate

    proposals = tmp_path / "p.json"
    proposals.write_text(json.dumps(_proposals()))
    decisions = tmp_path / "d.json"
    decisions.write_text(json.dumps({"verifier": {"method": "blind"}, "texts": {"T0001": None, "T0002": "7ABC123"}}))
    annotate.labels(proposals_path=proposals, decisions_path=decisions, out=tmp_path / "labels.json")
    entries = {path: {"sha256": "e" * 64} for path in ("img/a.jpg", "img/b.jpg", "img/z.jpg")}
    items = bdd_plate_labels.plate_items((tmp_path / "labels.json").read_bytes(), entries, "d" * 64,
                                         lambda path: (1280, 720))
    assert [item["itemId"] for item in items] == ["s0/000000/1", "s1/000003/7", "s1/000004/7"]
    assert items[1]["plates"][0]["textUsable"] and items[1]["vehicleClass"] == "car"
    assert items[0]["plates"][0]["textUnusableReason"] == "unlabelled" and items[0]["vehicleClass"] == "commercial"
    with pytest.raises(S32Error, match="descriptor"):
        bdd_plate_labels.plate_items((tmp_path / "labels.json").read_bytes(), entries, "0" * 64, lambda p: (1, 1))
