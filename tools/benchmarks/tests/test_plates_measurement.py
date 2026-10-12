"""E-A over the production crop and encoder, h_min/ΔEM derivation, and E-B coverage denominators."""

from __future__ import annotations

from fractions import Fraction

import numpy as np
import pytest

from mavi_vision.common.analytical import NormalizedBoundingBox
from mavi_vision.evidence.encoder import JpegLadderEncoder, encoding_ladder
from mavi_vision.evidence.policy import PRODUCTION_ENCODER_POLICY
from tools.benchmarks.capabilities.plates import adequacy, coverage, measure, truth as truths
from plate_fixtures import HeightInstrument, scene, still_item


# Production path equivalence and encoder regression


@pytest.mark.parametrize("box", [(0.1, 0.2, 0.3, 0.4), (0.0, 0.0, 1.0, 1.0), (0.333, 0.271, 0.401, 0.5149),
                                 (0.9, 0.9, 0.1, 0.1)])
def test_crop_origin_is_crop_region(box):
    image = scene(321, 207)
    normalised = NormalizedBoundingBox(*box)
    left, top, right, bottom = measure.crop_origin(321, 207, normalised)
    assert np.array_equal(measure.vehicle_crop(image, normalised), image[top:bottom, left:right])


def test_encode_is_the_production_encoder_byte_for_byte():
    crop = scene(700, 500)
    for role, cap in measure.ROLE_CAPS.items():
        ours = measure.encode(crop, role)
        theirs = JpegLadderEncoder(PRODUCTION_ENCODER_POLICY).encode(crop, cap)
        assert ours is not None and theirs is not None and ours.payload == theirs.payload


def test_encoder_policy_and_caps_are_the_adr_013_bounds():
    identity = measure.encoder_identity()
    assert (identity["maxLongEdgePx"], identity["representativeCapBytes"], identity["supplementalCapBytes"],
            identity["floorLongEdgePx"], identity["floorQuality"]) == (1024, 64 * 1024, 160 * 1024, 128, 50)
    assert identity["encoderVersion"] == "evidence-jpeg-ladder-v1"


def test_golden_smooth_crop_is_admitted_at_the_first_step():
    crop = np.repeat(np.linspace(0, 255, 400, dtype=np.uint8)[None, :, None], 300, axis=0).repeat(3, axis=2)
    for role in measure.ROLE_CAPS:
        encoded = measure.encode(crop, role)
        assert (encoded.width, encoded.height, encoded.quality, encoded.ladder_step) == (400, 300, 85, 0)


def test_golden_textured_crop_walks_the_ladder_within_its_cap():
    crop = scene(1400, 1000, seed=3)
    ladder = encoding_ladder(1400, 1000, PRODUCTION_ENCODER_POLICY)
    for role, cap in measure.ROLE_CAPS.items():
        encoded = measure.encode(crop, role)
        assert encoded is not None and encoded.size_bytes <= cap
        step = ladder[encoded.ladder_step]
        assert (max(encoded.width, encoded.height), encoded.quality) == (step.long_edge, step.quality)
    assert measure.encode(crop, "representative").ladder_step > measure.encode(crop, "supplemental").ladder_step


def test_measurements_are_deterministic():
    region = scene(60, 20)
    assert measure.laplacian_variance(region) == measure.laplacian_variance(region.copy())
    assert measure.laplacian_variance(scene(2, 2)) is None
    assert measure.cer("AB12", "AB123") == pytest.approx(0.2)
    assert measure.cer(None, "AB") == 1.0


def test_map_into_crop_scales_and_reports_the_inside_share():
    mapped, share = measure.map_into_crop((110, 60, 130, 70), (100, 50, 300, 250), (100, 100))
    assert mapped == (5.0, 5.0, 15.0, 10.0) and share == 1.0
    _, partial = measure.map_into_crop((290, 60, 310, 70), (100, 50, 300, 250), (100, 100))
    assert partial == pytest.approx(0.5)


# E-A rows


def _rows(instruments, plate_h=24, vehicle=True, text="AB1234"):
    image = scene(1600, 1200)
    item = still_item("img-1", image, (700, 900, 3 * plate_h, plate_h), text,
                      {"x": 400, "y": 300, "width": 800, "height": 700} if vehicle else None)
    return adequacy.measure_item(item, image, instruments)


def test_row_measures_native_and_both_roles():
    row = _rows([HeightInstrument("a", "AB1234", 10), HeightInstrument("b", "AB1234", 10, "plate-specific")])[0]
    assert row["association"] == "dataset-vehicle-box" and row["textUsable"]
    for role in ("representative", "supplemental"):
        assert row["roles"][role]["admitted"] and row["roles"][role]["plateInsideShare"] == 1.0
        assert row["reads"]["a"][role]["exact"] is True
    assert row["native"]["charHeightPx"] == 24
    assert row["roles"]["representative"]["scale"] <= row["roles"]["supplemental"]["scale"] <= 1.0


def test_resolution_loss_is_measured_not_assumed():
    # The instrument needs 23 px; the crop's down-scaling in the 64 KiB role drops the plate below it.
    row = _rows([HeightInstrument("a", "AB1234", 23), HeightInstrument("b", "AB1234", 23, "plate-specific")])[0]
    assert row["reads"]["a"]["native"]["exact"] is True
    assert row["reads"]["a"]["representative"]["exact"] is False


def test_unassociated_plate_is_a_row_without_roles():
    row = _rows([HeightInstrument("a", "AB1234", 1)], vehicle=False)[0]
    assert row["association"] == "unassociated" and row["roles"] == {}


def test_detector_candidates_are_used_only_without_a_dataset_box():
    image = scene(800, 600)
    item = still_item("img", image, (300, 400, 60, 20), "AB1234", None)
    rows = adequacy.measure_item(item, image, [HeightInstrument("a", "AB1234", 1)],
                                 [{"x": 0, "y": 0, "width": 100, "height": 100},
                                  {"x": 200, "y": 300, "width": 400, "height": 200}])
    assert rows[0]["association"] == "detector-vehicle-box"


def test_instrument_failure_is_recorded_not_hidden():
    rows = _rows([HeightInstrument("a", "AB1234", 1, fail=True), HeightInstrument("b", "AB1234", 1)])
    assert adequacy.instrument_failed(rows, "a") == 3 and adequacy.instrument_failed(rows, "b") == 0


def test_vehicle_association_prefers_the_smallest_containing_box():
    boxes = [{"x": 0, "y": 0, "width": 500, "height": 500}, {"x": 90, "y": 90, "width": 100, "height": 100},
             {"x": 100, "y": 100, "width": 20, "height": 5}]
    assert adequacy.associate_vehicle((100, 100, 120, 110), boxes) == boxes[1]
    assert adequacy.associate_vehicle((100, 100, 120, 110), [{"x": 0, "y": 0, "width": 105, "height": 500}]) is None


# h_min and ΔEM (pure)


def _synthetic_row(height, native_exact, encoded_exact, association="dataset-vehicle-box", usable=True):
    read = {"native": {"exact": native_exact}, "supplemental": {"exact": encoded_exact},
            "representative": {"exact": encoded_exact}}
    return {"itemId": f"seq{int(height)}/{id(read) % 1000:06d}", "textUsable": usable, "association": association, "vehicleClass": "car", "layout": "one-line",
            "illumination": "day", "occluded": None,
            "native": {"charHeightPx": height, "blur": float(height), "skewDegrees": 0.0},
            "reads": {"a": read, "b": read}}


def _bin(height, n, exact, encoded=None):
    return [_synthetic_row(height, i < exact, i < (exact if encoded is None else encoded)) for i in range(n)]


def test_h_min_is_the_smallest_bin_of_a_qualifying_tail():
    rows = _bin(40, 60, 54) + _bin(25, 60, 50) + _bin(17, 60, 49) + _bin(12, 60, 20) + _bin(5, 60, 0)
    derivation = adequacy.h_min(rows, ["a", "b"])
    # top EM 0.9; target 0.81; 25 px: 50/60 ≥ 0.81, 17 px: 49/60 ≥ 0.81, 12 px: 20/60 < 0.81.
    assert derivation["hMinPx"] == 15 and derivation["referenceInstrument"] == "a"


def test_h_min_tail_stops_at_an_insufficient_bin():
    rows = _bin(40, 60, 54) + _bin(25, 10, 10) + _bin(17, 60, 59)
    assert adequacy.h_min(rows, ["a"])["hMinPx"] == 32


@pytest.mark.parametrize("rows,reason", [(_bin(40, 49, 49), "top_bin_insufficient"), (_bin(40, 60, 0), "top_bin_zero")])
def test_h_min_not_measured(rows, reason):
    derivation = adequacy.h_min(rows, ["a"])
    assert derivation["hMinPx"] is None and derivation["notMeasuredReason"] == reason


def test_encoding_loss_population_and_delta():
    rows = (_bin(40, 60, 60, encoded=54) + [_synthetic_row(40, True, False, association="unassociated")] * 5
            + [_synthetic_row(40, False, False, usable=False)] * 7)
    summary = adequacy.summarise(rows, ["a", "b"])
    overall = summary["encodingLoss"]["a"]["supplemental"]["overall"]
    assert summary["population"] == {"atOrAboveHMin": 65, "associated": 60, "excludedUnassociated": 5}
    assert (overall["n"], overall["nativeExact"], overall["encodedExact"]) == (60, 60, 54)
    assert overall["distinctSources"] == 1  # every synthetic row of one height shares one sequence
    assert Fraction(overall["deltaEmPp"]["numerator"], overall["deltaEmPp"]["denominator"]) == 10
    assert summary["counts"]["textUnusable"] == 7
    assert summary["encodingLoss"]["a"]["supplemental"]["strata"]["oblique"] == {
        "unavailable-box-only-labels": overall}


def test_no_h_min_means_no_encoding_loss():
    assert adequacy.summarise(_bin(40, 10, 10), ["a"])["encodingLoss"] is None


# E-B coverage


def _frames(count=3, height=20, text="AB1234", usable=True):
    image = scene(400, 300)
    plate = truths.plate("plate", truths.box_polygon(150, 200, 60, height), text if usable else None, "one-line")
    return [coverage.PlateFrame(index, plate, lambda: image) for index in range(count)], image


def _observation(image, frame=1, role="near-view", box=(0.25, 0.5, 0.5, 0.25)):
    left, top, right, bottom = measure.crop_origin(400, 300, NormalizedBoundingBox(*box))
    encoded = measure.encode(np.ascontiguousarray(image[top:bottom, left:right]), "supplemental")
    return coverage.EvidenceObservation(role, 1, frame, box, lambda: encoded.payload)


def test_track_readable_in_native_and_evidence():
    frames, image = _frames()
    result = coverage.evaluate_track(frames, [_observation(image)], (400, 300), [HeightInstrument("a", "AB1234", 5)],
                                     10)
    assert result["oracleReadable"] and result["evidenceReadable"]
    assert result["rolesPreservingReading"] == ["near-view"]


def test_unmatched_track_stays_in_the_denominator():
    frames, image = _frames()
    instruments = [HeightInstrument("a", "AB1234", 5)]
    matched = coverage.evaluate_track(frames, [_observation(image)], (400, 300), instruments, 10)
    unmatched = coverage.evaluate_track(frames, None, (400, 300), instruments, 10)
    no_label = coverage.evaluate_track(frames, [_observation(image, frame=9)], (400, 300), instruments, 10)
    tracks = [{"gtTrackId": "g1", "state": "matched", "usablePlate": True, "result": matched},
              {"gtTrackId": "g2", "state": "unmatchedGt", "usablePlate": True, "result": unmatched},
              {"gtTrackId": "g3", "state": "matched", "usablePlate": True, "result": no_label},
              {"gtTrackId": "g4", "state": "matched", "usablePlate": False, "result": None}]
    summary = coverage.summarise(tracks, ["a"])
    assert (summary["rOracle"], summary["rEvidence"], summary["withoutUsablePlate"]) == (3, 1, 1)
    assert summary["coverage"]["numerator"] == 1 and summary["coverage"]["denominator"] == 3
    assert summary["coverage"]["sufficient"] is False
    assert summary["oracleNotEvidenceByState"] == {"matched": 1, "unmatchedGt": 1}
    assert no_label["evidence"][0]["skipped"] == "no_plate_label_at_frame"


def test_plate_below_h_min_is_not_oracle_readable():
    frames, _ = _frames(height=8)
    result = coverage.evaluate_track(frames, None, (400, 300), [HeightInstrument("a", "AB1234", 1)], 10)
    assert result["oracleReadable"] is False and result["oracleFrames"] == []


def test_zero_denominator_has_no_value():
    assert coverage.summarise([], ["a"])["coverage"] == {"numerator": 0, "denominator": 0, "value": None,
                                                         "sufficient": False}


def test_association_states_are_exclusive():
    entry = {"pairs": [{"gtTrackId": "g1", "maviTrackId": "m1"}], "unmatchedGt": [{"gtTrackId": "g2"}],
             "ambiguousGt": [{"gtTrackId": "g1"}]}
    with pytest.raises(Exception, match="gt_state_duplicate"):
        coverage.association_states(entry)


def test_masked_cer_treats_a_mask_as_any_character():
    assert measure.cer("2410JV7", "24*0JV*", masked=True) == 0
    assert measure.cer("2410JV", "24*0JV*", masked=True) == pytest.approx(1 / 7)
    assert measure.cer("2410JV7", "24*0JV*") == pytest.approx(2 / 7)
