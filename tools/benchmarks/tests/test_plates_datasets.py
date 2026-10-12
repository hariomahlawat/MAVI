"""UFPR-ALPR and VOC plate adapters on fixture trees, and the truth → E-A → verdict command path."""

from __future__ import annotations

import json

import numpy as np
import pytest

from tools.benchmarks.capabilities.plates import instruments, truth as truths
from tools.benchmarks.core import descriptor as descriptors
from tools.benchmarks.core._stage3 import ROOT
from tools.benchmarks.core.identity import S32Error, canonical_json, sha256_hex
from tools.benchmarks.datasets import ufpr_alpr, voc_plates
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
    ("datacluster-indian-number-plates-sample",
     lambda: voc_plates.descriptor("2bb7cd4e46e58af4f6fa413ce8e205ac69e605a7")),
])
def test_committed_descriptor_templates_are_the_adapters_descriptors(name, document):
    path = ROOT / "docs/qualification/stage4/benchmarks" / f"{name}.descriptor-template.json"
    assert path.read_bytes() == canonical_json(document())
