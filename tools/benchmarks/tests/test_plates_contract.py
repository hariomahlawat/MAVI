"""Normalisation v1 (shared vectors), plate truth validation and the adequacy verdict boundaries."""

from __future__ import annotations

import copy
import json
from fractions import Fraction

import pytest

from tools.benchmarks.capabilities.plates import truth as truths, verdict as verdicts
from tools.benchmarks.core._stage3 import ROOT
from tools.benchmarks.core.identity import S32Error
from tools.benchmarks.plates import normalisation

VECTORS = json.loads((ROOT / "contracts" / "test-vectors" / "plate-normalisation-v1.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("vector", VECTORS["vectors"], ids=[v["id"] for v in VECTORS["vectors"]])
def test_normalisation_matches_the_shared_vector(vector):
    result = normalisation.normalise(vector["raw"])
    assert result.raw == vector["raw"]
    assert (result.normalised, result.outcome, result.reason, result.format_class) == (
        vector["normalised"], vector["outcome"], vector["reason"], vector["formatClass"])


def test_vector_file_is_the_v1_contract():
    assert VECTORS["schemaVersion"] == "plate-normalisation-test-vectors-v1"
    assert VECTORS["normalisationId"] == normalisation.NORMALISATION_ID
    ids = [v["id"] for v in VECTORS["vectors"]]
    assert len(ids) == len(set(ids)) >= 30


def test_ill_formed_input_is_refused():
    with pytest.raises(ValueError, match="ill_formed"):
        normalisation.normalise("KA01\ud800AB")
    with pytest.raises(TypeError):
        normalisation.normalise(None)  # type: ignore[arg-type]


def test_separator_set_is_exactly_the_contract():
    rule = next(r for r in VECTORS["rules"] if r.startswith("4."))
    for character in normalisation.SEPARATORS:
        assert f"U+{ord(character):04X}" in rule


# Plate truth


def _truth(**changes):
    item = {"itemId": "seq/000000", "imagePath": "a.png", "imageSha256": "1" * 64,
            "frameSize": {"width": 100, "height": 80}, "sequenceId": "seq", "frameIndex": 0, "gtTrackId": "vehicle",
            "vehicleBox": {"x": 10, "y": 10, "width": 80, "height": 60}, "vehicleClass": "car",
            "plates": [truths.plate("plate", truths.box_polygon(40, 50, 20, 8), "AB-1234", "one-line")]}
    document = {"schemaVersion": truths.SCHEMA, "datasetId": "ufpr-alpr", "release": "r", "split": "testing",
                "descriptorSha256": "2" * 64, "adapterId": "ufpr-alpr", "adapterVersion": "1", "kind": "sequence",
                "normalisationId": "mavi-plate-normalisation-v1", "items": [item], "exclusions": []}
    for path, value in changes.items():
        target = document
        keys = path.split(".")
        for key in keys[:-1]:
            target = target[int(key)] if key.isdigit() else target[key]
        target[keys[-1]] = value
    return document


def test_valid_truth_passes():
    assert truths.validate_document(_truth())["items"][0]["plates"][0]["textUsable"] is True


@pytest.mark.parametrize("change,code", [
    ({"items.0.plates.0.polygon": [[95, 50], [120, 50], [120, 58], [95, 58]]}, "polygon"),
    ({"items.0.plates.0.textUsable": False}, "text_usability"),
    ({"items.0.plates.0.layout": "two-line"}, "layout"),
    ({"items.0.itemId": "seq/000001"}, "item_id"),
    ({"kind": "still"}, "still_fields"),
    ({"items.0.vehicleBox": {"x": 50, "y": 10, "width": 80, "height": 60}}, "vehicle_box"),
])
def test_invalid_truth_is_refused(change, code):
    with pytest.raises(S32Error, match=code):
        truths.validate_document(_truth(**change))


def test_unlabelled_and_rejected_labels_are_unusable_not_dropped():
    assert truths.plate("p", truths.box_polygon(0, 0, 4, 2), None, "unknown")["textUnusableReason"] == "unlabelled"
    rejected = truths.plate("p", truths.box_polygon(0, 0, 4, 2), "KA01–AB", "unknown")
    assert (rejected["textUsable"], rejected["textUnusableReason"]) == (False, "non-alphanumeric")


def test_geometry_proxies():
    polygon = truths.box_polygon(0, 0, 40, 20)
    assert truths.char_height_px(polygon, 2) == 10
    assert truths.char_height_px(polygon, None) == 20
    assert truths.plate_width_px(polygon) == 40
    assert truths.skew_degrees(polygon) == 0
    assert truths.skew_degrees([[0, 0], [10, 10], [10, 20], [0, 10]]) == pytest.approx(45)


# Verdict


def _decide(c=(85, 100), loss_a=Fraction(5), loss_b=Fraction(0), sufficient=True, errors=None):
    return verdicts.decide(coverage=c, coverage_sufficient=sufficient, losses={"a": loss_a, "b": loss_b},
                           losses_sufficient={"a": sufficient, "b": sufficient},
                           instrument_errors=errors or {"a": 0, "b": 0})["verdict"]


@pytest.mark.parametrize("c,loss,expected", [
    ((85, 100), Fraction(5), "ADEQUATE"),
    ((8499, 10000), Fraction(0), "MARGINAL"),
    ((70, 100), Fraction(0), "MARGINAL"),
    ((6999, 10000), Fraction(0), "INADEQUATE"),
    ((100, 100), Fraction(501, 100), "MARGINAL"),
    ((100, 100), Fraction(10), "MARGINAL"),
    ((100, 100), Fraction(1001, 100), "INADEQUATE"),
    ((100, 100), Fraction(-3), "ADEQUATE"),
    ((75, 100), Fraction(11), "INADEQUATE"),
])
def test_verdict_boundaries(c, loss, expected):
    assert _decide(c=c, loss_a=loss) == expected


def test_no_data_is_not_measured_never_adequate():
    assert _decide(c=None) == "NOT_MEASURED"
    assert _decide(c=(0, 0)) == "NOT_MEASURED"
    assert _decide(sufficient=False) == "NOT_MEASURED"
    assert _decide(loss_b=None) == "NOT_MEASURED"
    assert _decide(errors={"a": 1, "b": 0}) == "NOT_MEASURED"
    assert verdicts.decide(coverage=(90, 100), coverage_sufficient=True, losses={}, losses_sufficient={},
                           instrument_errors={})["verdict"] == "NOT_MEASURED"


def test_inadequate_takes_precedence_and_keeps_every_reason():
    result = verdicts.decide(coverage=(80, 100), coverage_sufficient=True, losses={"a": Fraction(12), "b": Fraction(6)},
                             losses_sufficient={"a": True, "b": True}, instrument_errors={"a": 0, "b": 0})
    assert result["verdict"] == "INADEQUATE"
    assert result["reasons"] == ["encoding_loss_above_10pp:a", "coverage_below_0.85", "encoding_loss_above_5pp:b"]


def test_truth_document_is_not_mutated_by_validation():
    document = _truth()
    before = copy.deepcopy(document)
    truths.validate_document(document)
    assert document == before
