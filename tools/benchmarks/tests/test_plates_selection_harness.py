"""A–D evaluators and the query generator on synthetic fixtures only (no dataset, no model)."""

from __future__ import annotations

import dataclasses
import hashlib
import io
import random
import uuid
from fractions import Fraction

import pytest
from PIL import Image

from mavi_vision.plates.inference import PlateBox, Reading
from mavi_vision.plates.pipeline import PlateRecord, RankedReading
from tools.benchmarks.capabilities.plates import evaluator as ev
from tools.benchmarks.capabilities.plates import queries as q

PARAMS = q.QueryParameters(interior_offset=1, negatives_per_plate=2, seed="synthetic-seed")
MANIFEST = hashlib.sha256(b"synthetic-population-manifest").hexdigest()
OTHER_MANIFEST = hashlib.sha256(b"another-population").hexdigest()


def gen(truths, manifest=MANIFEST):
    return q.generate(truths, PARAMS, manifest)


def _h(text):
    return hashlib.sha256(text.encode()).hexdigest()


# Stage 1 (synthetic): the frozen eligible detector universe, OC5 identity, Layer-A gates and ranking rule.
FREEZE = ev.BaselineFreeze((("PD1-X", _h("PD1-X")), ("PD2-N", _h("PD2-N")), ("PD2-S", _h("PD2-S"))),
                           "OC5-BEST", _h("OC5-BEST"), _h("layer-a-gates"))
WHEN = "2026-10-14T00:00:00Z"


def _layer_a(passed=("PD2-N", "PD2-S"), metrics=None, identities=None):
    metrics = metrics or {"PD1-X": (0.99, 0.0, 0.99), "PD2-N": (0.95, 0.10, 0.90), "PD2-S": (0.93, 0.05, 0.92)}
    identities = identities or {}
    return [ev.LayerAResult(ev.ComponentScore(d, True, 100, *metrics[d]), identities.get(d, h), d in passed)
            for d, h in FREEZE.eligible_detectors]


RESOLUTION = ev.resolve_baseline(FREEZE, _layer_a(), d_rows_read=0, resolved_at_utc=WHEN)


# ---------------------------------------------------------------------------------------------- queries


def test_queries_are_deterministic_bounded_and_fixed_by_the_plan():
    first = gen(["KA01AB1234", "ka-01 ab 1234", "KA01CD99", "MH12", "ab@1", "22BH1234AA", "7ABC123"])
    second = gen(["7ABC123", "KA01CD99", "KA01AB1234", "MH12", "22BH1234AA"])
    assert first.queries == second.queries and first.query_set_sha256 == second.query_set_sha256
    assert first.rejected_truths == ("ab@1",)
    texts = {(x.query_class, x.text): x for x in first.queries}
    assert texts[("full", "KA01AB1234")].match == q.EXACT
    assert texts[("prefix", "KA01")].sources == ("KA01AB1234", "KA01CD99")
    assert texts[("suffix", "1234")].sources == ("22BH1234AA", "KA01AB1234")  # terminal four DIGITS
    assert q.last_digit_suffix("7ABC123") is None and q.last_digit_suffix("KA01CD99") is None
    assert first.skipped["suffix"] == 3  # 7ABC123, KA01CD99, MH12: absence recorded, nothing fabricated
    assert (q.PREFIX_LENGTH, q.SUFFIX_DIGITS, q.INTERIOR_LENGTH) == (4, 4, 5)
    for query in first.queries:
        assert q.queryable(query.text)
        if query.query_class == q.NEGATIVE:
            assert not any(query.text in t for t in first.truths)


def test_query_identity_is_bound_to_the_population():
    one, other = gen(["KA01AB1234"]), gen(["KA01AB1234"], OTHER_MANIFEST)
    assert one.generator_config_sha256 == other.generator_config_sha256
    assert one.query_set_sha256 != other.query_set_sha256
    with pytest.raises(ValueError, match="manifest"):
        q.generate(["KA01AB1234"], PARAMS, "not-a-sha")


def test_same_literal_from_two_classes_scores_once():
    result = gen(["1234ABCD5678", "XY1234"])
    merged = [m for m in result.metric_queries if m.text == "1234"]
    assert len(merged) == 1 and merged[0].classes == ("prefix", "suffix")
    assert len([x for x in result.queries if x.text == "1234"]) == 2  # provenance kept


def test_query_lengths_are_not_parameters():
    with pytest.raises(TypeError):
        q.QueryParameters(prefix_length=4, interior_offset=1, negatives_per_plate=1, seed="s")  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        q.QueryParameters(0, 1, "s")


# ---------------------------------------------------------------------------------------------- A


SQUARE = ((10, 10), (30, 10), (30, 20), (10, 20))


def test_detection_metrics_floor_and_strata():
    items = [ev.DetectionItem("c1", (SQUARE,), ((10, 10, 20, 10, 0.9), (60, 60, 5, 5, 0.8)), "day"),
             ev.DetectionItem("c2", (((0, 0), (10, 0), (10, 10), (0, 10)),), ((0, 0, 10, 10, 0.1),), "night")]
    result = ev.evaluate_detection(items, detector_floor=0.25)
    assert (result.outcome, result.plates, result.covered, result.recall) == (ev.MEASURED, 2, 1, Fraction(1, 2))
    assert result.below_floor_proposals == 1 and result.false_plates_per_crop == Fraction(1, 2)
    assert result.per_stratum["day"]["status"] == ev.INSUFFICIENT


def test_five_junk_proposals_are_a_contract_fail_not_a_good_score():
    junk = tuple((x, 0, 40, 40, 0.9) for x in range(0, 50, 10))  # would cover the plate several times over
    result = ev.evaluate_detection([ev.DetectionItem("c", (SQUARE,), junk)], detector_floor=0.25)
    assert result.outcome == ev.CONTRACT_FAIL and result.recall is None
    assert result.contract_violations == ("plate_detector_output_exceeds_bound:c",)


# ---------------------------------------------------------------------------------------------- B / C


def _plate(*readings):
    return ev.ranking_plate_record([Reading(t, c) for t, c in readings])


def test_reading_rules_follow_pr3_and_floors_are_separated():
    assert _plate(("KA01AB1234", 0.01)).plate.outcome == "read"  # ranking floor 0
    assert _plate(("X", 0.5), ("X", 0.5)).plate is None and _plate(("", 0.5)).plate is None
    over = _plate(("A", 0.1), ("B", 0.2), ("C", 0.3), ("D", 0.4))
    assert over.contract_violation == "plate_recogniser_output_exceeds_bound"
    diagnostic = ev.diagnostic_plate_record([Reading("KA01", 0.2)], 0.5)
    assert diagnostic.plate.outcome == "unreadable"
    with pytest.raises(ValueError, match="ranking_profile"):
        ev.evaluate_reading([ev.ReadItem("p", "KA01", diagnostic)])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="not_declared"):
        ev.diagnostic_plate_record([Reading("KA01", 0.2)], 0.0)
    plate = _plate(("KA01", 0.5)).plate
    assert isinstance(plate, PlateRecord) and isinstance(plate.readings[0], RankedReading)
    failed = ev.evaluate_reading([ev.ReadItem("p", "KA01", over)])
    assert failed.outcome == ev.CONTRACT_FAIL and failed.em is None


def test_reading_metrics_and_input_order_invariance():
    items = [ev.ReadItem("p1", "KA01AB1234", _plate(("ka01 ab1234", 0.9))),
             ev.ReadItem("p2", "KA01AB1234", _plate(("KA01AB1284", 0.8), ("KA01AB1234", 0.7))),
             ev.ReadItem("p3", "KA01AB1234", ev.RankingPlate(None)), ev.ReadItem("p4", "a@b", ev.RankingPlate(None)),
             ev.ReadItem("p5", "MH12AB0001", _plate(("MH12AB0001", 0.8)))]
    result = ev.evaluate_reading(items)
    assert (result.plates, result.exact, result.unsupported_truths) == (4, 2, 1)
    assert result.em == Fraction(1, 2) and result.top_k_hit == Fraction(3, 4)
    for seed in range(5):
        shuffled = list(items)
        random.Random(seed).shuffle(shuffled)
        again = ev.evaluate_reading(shuffled)
        assert (again.ece, again.risk_coverage, again.em) == (result.ece, result.risk_coverage, result.em)
    assert ev.c_minus_b(result, result) == 0


# ---------------------------------------------------------------------------------------------- D fixtures


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 32), (200, 200, 200)).save(buffer, format="JPEG")
    return buffer.getvalue()


JPEG = _jpeg()
SHA = hashlib.sha256(JPEG).hexdigest()


class Detector:
    def __init__(self, boxes):
        self.boxes = boxes

    def detect(self, crop, verified):
        return list(self.boxes)


class Recogniser:
    def __init__(self, texts):
        self.texts = list(texts)

    def read(self, region, verified, box):
        text = self.texts.pop(0)
        return [Reading(text, 0.9)] if text else []


def _track(track_id, cluster, truth, readings, *, boxes=1, parameters=None):
    crops = [ev.EvidenceCrop(uuid.uuid5(uuid.NAMESPACE_URL, f"{track_id}/{i}"), "near-view", i, SHA, JPEG)
             for i in range(len(readings))]
    detector = Detector([PlateBox(1 + k, 1, 20, 10, 0.9 - 0.1 * k) for k in range(boxes)])
    run = ev.run_track(uuid.uuid5(uuid.NAMESPACE_URL, track_id), crops, detector, Recogniser(readings),
                       parameters or ev.ranking_parameters(0.25))
    return ev.TrackItem(track_id, cluster, truth, run)


def _plate_text(i):
    return f"KA{i % 100:02d}AB{1000 + i}"


def _population(n, read):
    return [_track(f"t{i}", f"site{i}", _plate_text(i), read(i)) for i in range(n)]


def _queries(items, manifest=MANIFEST):
    special = (ev.NO_PLATE, ev.UNREADABLE, ev.NO_GT_VEHICLE)
    return gen([i.truth for i in items if i.truth not in special and ev.normalised_truth(i.truth)], manifest)


def score(items, queries=None):
    return ev.evaluate_tracks(items, queries or _queries(items), population_manifest_sha256=MANIFEST)


# ---------------------------------------------------------------------------------------------- D


def test_d_score_on_a_closed_population_exactly():
    items = [_track("t1", "s1", "KA01AB1234", ["KA01AB1234"]),
             _track("t2", "s1", "MH12CD5678", ["MH12CD5670", "MH12CD5670"]),
             _track("t3", "s2", ev.NO_PLATE, ["KA01ZZ9999"]),
             _track("t5", "s2", ev.NO_GT_VEHICLE, ["DL3CAB0002"]),
             ev.TrackItem("t4", "s2", "DL3CAB0001", None)]
    queries = _queries(items)
    result = score(items, queries)
    assert result.outcome == ev.MEASURED and result.counts.exact_denominator == 3
    assert result.exact_recall == Fraction(1, 3)
    contains = [m for m in queries.metric_queries if m.match == q.CONTAINS]
    reads = {"t1": ("KA01AB1234", "KA01AB1234"), "t2": ("MH12CD5670", "MH12CD5678"), "t3": ("KA01ZZ9999", None),
             "t5": ("DL3CAB0002", None)}
    returned = [(t, m.text) for t, (text, _) in reads.items() for m in contains if m.text in text]
    correct = [(t, x) for t, x in returned
               if reads[t][1] is not None and x in reads[t][1] and not dict((m.text, m) for m in contains)[x].negative_only]
    assert result.counts.returned_pairs == len(returned) > 0
    assert result.contains_precision == Fraction(len(correct), len(returned))
    assert result.d_score == (result.exact_recall + result.contains_recall + result.contains_precision) / 3
    assert result.counts.consistent_wrong == 1 and result.counts.multi_source == 1
    assert result.consistent_wrong_status == ev.INSUFFICIENT
    assert result.accounting["no-gt-vehicle"] == 1 and result.accounting["no-plate"] == 1


def test_unsupported_truth_stays_and_cannot_improve_precision():
    plain = _track("p", "s1", "KA01AB1234", ["KA01AB1234"])
    adversarial = _track("u", "s2", "KA01AB12३४", ["KA01AB1234"])  # unsupported truth, reads a real-looking text
    queries = gen(["KA01AB1234"])
    without = score([plain], queries)
    with_unsupported = score([plain, adversarial], queries)
    assert with_unsupported.accounting["unsupported"] == 1
    assert with_unsupported.counts.exact_denominator == without.counts.exact_denominator  # no recall denominator
    assert with_unsupported.counts.positive_pairs == without.counts.positive_pairs
    assert with_unsupported.counts.returned_pairs > without.counts.returned_pairs
    assert with_unsupported.counts.correct_returned == without.counts.correct_returned
    assert with_unsupported.contains_precision < without.contains_precision


def test_unreadable_is_accounted_not_silent():
    items = [_track("p", "s1", "KA01AB1234", ["KA01AB1234"]), _track("r", "s1", ev.UNREADABLE, ["KA01AB1234"])]
    result = score(items)
    assert result.accounting["unreadable"] == 1 and result.counts.unreadable_returned_pairs > 0
    assert result.contains_precision == 1  # unknown truth is neither right nor wrong


def test_population_binding_and_truth_refusals():
    plain = [_track("p", "s1", "KA01AB1234", ["KA01AB1234"])]
    with pytest.raises(ValueError, match="another_population"):
        ev.evaluate_tracks(plain, gen(["KA01AB1234"], OTHER_MANIFEST), population_manifest_sha256=MANIFEST)
    with pytest.raises(ValueError, match="not_bound"):
        score(plain, gen(["KA01AB1234", "MH12AB0001"]))
    with pytest.raises(ValueError, match="truth_empty"):
        score([ev.TrackItem("e", "s", " ", None)], gen([]))


def test_contract_violation_fails_the_whole_composition():
    items = [_track("t1", "s1", "KA01AB1234", ["KA01AB1234"]),
             _track("t2", "s2", "MH12AB0001", ["MH12AB0001"], boxes=3)]
    result = score(items)
    assert (result.outcome, result.d_status, result.d_score) == (ev.CONTRACT_FAIL, ev.CONTRACT_FAIL, None)
    assert result.contract_violations == ("plate_detector_output_exceeds_bound:t2",)
    assert result.consistent_wrong_status == ev.FAIL
    base = score([items[0]])
    gate = ev.baseline_gate(ev.CompositionScore("PD2-S", "OC1-XS", result), ev.CompositionScore("PD2-N", "OC5-BEST", base),
                            RESOLUTION)
    assert gate == ev.FAIL
    with pytest.raises(ev.BaselineStop, match="baseline_contract_violation"):  # never replaced: the event stops
        ev.baseline_gate(ev.CompositionScore("PD2-S", "OC1-XS", base), ev.CompositionScore("PD2-N", "OC5-BEST", result),
                         RESOLUTION)


def test_ranking_floor_is_enforced_and_diagnostics_are_separate():
    floored = ev.PlateParameters(2, 1, 3, 0.25, 0.5, frozenset(), None)
    items = [_track("t1", "s1", "KA01AB1234", ["KA01AB1234"], parameters=floored)]
    with pytest.raises(ValueError, match="ranking_profile"):
        score(items)
    ranked = [_track("t1", "s1", "KA01AB1234", ["KA01AB1234"])]
    diagnostic = ev.diagnostic_evaluate_at_floor(ranked, _queries(ranked), 0.5, population_manifest_sha256=MANIFEST)
    assert diagnostic.accounting["diagnosticFloor"] == 0.5
    assert score(ranked).d_score == ev.evaluate_tracks(ranked, _queries(ranked), population_manifest_sha256=MANIFEST).d_score
    with pytest.raises(ValueError, match="not_declared"):
        ev.diagnostic_evaluate_at_floor(ranked, _queries(ranked), 0.0, population_manifest_sha256=MANIFEST)


def test_candidate_silence_scores_zero_and_corpus_deficiency_is_insufficient():
    silent = _population(3, lambda i: [""])
    result = score(silent)
    assert (result.outcome, result.d_status) == (ev.MEASURED, ev.MEASURED)
    assert (result.exact_recall, result.contains_recall, result.contains_precision, result.d_score) == (0, 0, 0, 0)
    good = score(_population(3, lambda i: [_plate_text(i)]))
    assert ev.baseline_gate(ev.CompositionScore("PD2-N", "OC1-XS", good), ev.CompositionScore("PD2-N", "OC5-BEST", result),
                            RESOLUTION) == ev.PASS  # a silent Tesseract baseline is valid and scores 0
    no_plates = [_track("n", "s1", ev.NO_PLATE, ["KA01AB1234"])]
    deficient = score(no_plates, gen([]))
    assert deficient.d_status == ev.INSUFFICIENT and deficient.d_score is None
    assert ev.baseline_gate(ev.CompositionScore("PD2-N", "OC1-XS", deficient),
                            ev.CompositionScore("PD2-N", "OC5-BEST", result), RESOLUTION) == ev.INSUFFICIENT
    with pytest.raises(ev.BaselineStop, match="baseline_not_evaluable"):
        ev.baseline_gate(ev.CompositionScore("PD2-N", "OC1-XS", good),
                         ev.CompositionScore("PD2-N", "OC5-BEST", deficient), RESOLUTION)


def test_mpid_boundary_is_exact():
    base = score(_population(1, lambda i: [_plate_text(i)]))

    def gate(high, low, detector="PD2-S"):
        return ev.baseline_gate(ev.CompositionScore(detector, "OC1-XS", dataclasses.replace(base, d_score=high)),
                                ev.CompositionScore("PD2-N", "OC5-BEST", dataclasses.replace(base, d_score=low)),
                                RESOLUTION)

    assert 0.47 - 0.43 < 0.04  # the float trap the exact path avoids
    assert gate(Fraction(47, 100), Fraction(43, 100)) == ev.PASS
    assert gate(Fraction(4, 100), Fraction(0)) == ev.PASS
    assert gate(Fraction(399, 10000), Fraction(0)) == ev.FAIL
    assert gate(Fraction(1, 3) + Fraction(4, 100), Fraction(1, 3)) == ev.PASS
    assert gate(Fraction(4, 100), Fraction(0), detector="PD1-X") == ev.PASS  # one baseline for every detector
    with pytest.raises(ValueError, match="sealed_pd_base"):  # a detector-matched PD2-S + OC5 is not the hard baseline
        ev.baseline_gate(ev.CompositionScore("PD2-S", "OC1-XS", base), ev.CompositionScore("PD2-S", "OC5-BEST", base),
                         RESOLUTION)
    with pytest.raises(ValueError, match="sealed_pd_base"):
        ev.baseline_gate(ev.CompositionScore("PD2-S", "OC1-XS", base), ev.CompositionScore("PD2-N", "OC2-V6S", base),
                         RESOLUTION)


# ---------------------------------------------------------------------------------------------- baseline resolution


def test_pd_base_resolves_mechanically_from_the_frozen_rule():
    assert RESOLUTION.pd_base_id == "PD2-N"  # PD1-X ranks higher but failed Layer A
    assert RESOLUTION.pd_base_identity_sha256 == _h("PD2-N")
    assert RESOLUTION.benchmark_only_identity_sha256 == _h("OC5-BEST")
    assert RESOLUTION.ranking_rule_sha256 == ev.DETECTOR_RANKING_RULE_SHA256
    assert RESOLUTION.layer_a_result_sha256 == ev.layer_a_result_sha256(_layer_a())
    assert RESOLUTION.d_state == ev.D_NOT_STARTED and RESOLUTION.resolved_at_utc == WHEN
    assert ev.resolve_baseline(FREEZE, list(reversed(_layer_a())), d_rows_read=0, resolved_at_utc=WHEN) == RESOLUTION
    ev.verify_resolution(FREEZE, RESOLUTION, _layer_a())
    # The frozen tie-break: equal primary -> lower false plates per crop -> higher AP50 -> candidate id.
    tied = {"PD1-X": (0.9, 0.1, 0.9), "PD2-N": (0.9, 0.1, 0.9), "PD2-S": (0.9, 0.1, 0.9)}
    assert ev.resolve_baseline(FREEZE, _layer_a(("PD2-S", "PD2-N"), tied), d_rows_read=0,
                               resolved_at_utc=WHEN).pd_base_id == "PD2-N"
    second = {"PD1-X": (0.9, 0.1, 0.9), "PD2-N": (0.9, 0.2, 0.99), "PD2-S": (0.9, 0.1, 0.5)}
    assert ev.resolve_baseline(FREEZE, _layer_a(("PD2-S", "PD2-N"), second), d_rows_read=0,
                               resolved_at_utc=WHEN).pd_base_id == "PD2-S"
    missing = {"PD1-X": (0.9, 0.1, 0.9), "PD2-N": (None, 0.0, 0.99), "PD2-S": (0.1, 0.9, 0.1)}
    assert ev.resolve_baseline(FREEZE, _layer_a(("PD2-S", "PD2-N"), missing), d_rows_read=0,
                               resolved_at_utc=WHEN).pd_base_id == "PD2-S"


def test_pd_base_resolution_stops_and_never_chooses():
    def stop(reason, results, **kw):
        with pytest.raises(ev.BaselineStop, match=reason):
            ev.resolve_baseline(FREEZE, results, d_rows_read=kw.get("d_rows_read", 0), resolved_at_utc=WHEN)

    stop("no_detector_passed_layer_a", _layer_a(passed=()))
    stop("after_d_data_read", _layer_a(), d_rows_read=1)
    outsider = _layer_a() + [ev.LayerAResult(ev.ComponentScore("PD9-NEW", True, 100, 1.0, 0.0, 1.0), _h("PD9-NEW"), True)]
    stop("inconsistent_with_frozen_detector_universe", outsider)  # cannot resolve to an unfrozen detector
    stop("inconsistent_with_frozen_detector_universe", _layer_a()[1:])
    stop("ambiguous_duplicate_detector", _layer_a() + _layer_a()[1:2])
    stop("identity_mismatch:PD2-N", _layer_a(identities={"PD2-N": _h("PD2-N-retrained")}))
    failed = _layer_a()
    failed[1] = dataclasses.replace(failed[1], score=dataclasses.replace(failed[1].score, contract_fail=True))
    stop("gate_pass_with_contract_fail:PD2-N", failed)
    stop("non_finite_metric:PD2-N", _layer_a(metrics={"PD1-X": (0.9, 0.1, 0.9), "PD2-N": (float("nan"), 0.1, 0.9),
                                                      "PD2-S": (0.9, 0.1, 0.9)}))
    with pytest.raises(ValueError, match="benchmark_only_component_cannot_be_a_detector_candidate"):
        ev.BaselineFreeze((("OC5-BEST", _h("x")), ("PD2-N", _h("PD2-N"))), "OC5-BEST", _h("o"), _h("g"))
    with pytest.raises(ValueError, match="ranking_rule_not_the_frozen_rule"):
        ev.BaselineFreeze(FREEZE.eligible_detectors, "OC5-BEST", _h("o"), _h("g"), _h("another rule"))
    with pytest.raises(ValueError, match="sorted_unique_nonempty"):
        ev.BaselineFreeze((), "OC5-BEST", _h("o"), _h("g"))


def test_sealed_resolution_cannot_change_and_oc5_is_never_rankable():
    base = score(_population(1, lambda i: [_plate_text(i)]))
    swapped = dataclasses.replace(RESOLUTION, pd_base_id="PD2-S")  # an edit without re-sealing
    with pytest.raises(ev.BaselineStop, match="record_altered"):
        ev.baseline_gate(ev.CompositionScore("PD2-S", "OC1-XS", base), ev.CompositionScore("PD2-S", "OC5-BEST", base),
                         swapped)
    other = ev.resolve_baseline(FREEZE, _layer_a(passed=("PD2-S",)), d_rows_read=0, resolved_at_utc=WHEN)
    with pytest.raises(ev.BaselineStop, match="changed_after_seal"):
        ev.assert_resolution_unchanged(RESOLUTION, other)
    with pytest.raises(ev.BaselineStop, match="differs_from_frozen_derivation"):  # re-sealed but not the derivation
        ev.verify_resolution(FREEZE, other, _layer_a())
    late = dataclasses.replace(RESOLUTION, d_state="D_STARTED")
    late = dataclasses.replace(late, record_sha256=ev._canonical_sha256(late.payload()))
    with pytest.raises(ev.BaselineStop, match="not_sealed_before_d"):
        ev.verify_resolution(FREEZE, late, _layer_a())
    ev.assert_resolution_unchanged(RESOLUTION, ev.resolve_baseline(FREEZE, _layer_a(), d_rows_read=0, resolved_at_utc=WHEN))
    ordinary = [ev.CompositionScore("PD2-S", "OC1-XS", base), ev.CompositionScore("PD1-X", "OC2-V6S", base)]
    assert ev.rankable_compositions(ordinary, RESOLUTION) == ordinary
    for bad in (ev.CompositionScore("PD2-N", "OC5-BEST", base), ev.CompositionScore("PD2-S", "OC5-BEST", base)):
        with pytest.raises(ValueError, match="cannot_be_ranked"):
            ev.rankable_compositions(ordinary + [bad], RESOLUTION)
        with pytest.raises(ValueError, match="cannot_be_ranked|sealed_pd_base"):
            ev.baseline_gate(bad, ev.CompositionScore("PD2-N", "OC5-BEST", base), RESOLUTION)


def test_detector_matched_tesseract_is_diagnostic_only():
    base = score(_population(1, lambda i: [_plate_text(i)]))
    high = ev.CompositionScore("PD2-S", "OC1-XS", dataclasses.replace(base, d_score=Fraction(1, 2)))
    matched = ev.CompositionScore("PD2-S", "OC5-BEST", dataclasses.replace(base, d_score=Fraction(1, 5)))
    assert ev.diagnostic_ocr_uplift(high, matched, "OC5-BEST") == Fraction(3, 10)
    with pytest.raises(ValueError, match="not_detector_matched"):
        ev.diagnostic_ocr_uplift(high, ev.CompositionScore("PD2-N", "OC5-BEST", base), "OC5-BEST")
    failed = ev.CompositionScore("PD2-S", "OC5-BEST", dataclasses.replace(base, outcome=ev.CONTRACT_FAIL, d_score=None))
    assert ev.diagnostic_ocr_uplift(high, failed, "OC5-BEST") is None  # a diagnostic, never a stop or a gate verdict


# ---------------------------------------------------------------------------------------------- comparison


@pytest.fixture(scope="module")
def pair():
    good = _population(70, lambda i: [_plate_text(i)])
    silent = _population(70, lambda i: [""])
    half = _population(70, lambda i: [_plate_text(i) if i % 2 else ""])
    near = _population(70, lambda i: [_plate_text(i) if i % 25 else ""])  # ΔD ≈ 0.03 < MPID
    return good, silent, half, near, _queries(good)


def compare(a, b, queries, **overrides):
    arguments = dict(replicates=200, seed=7, required_clusters=60, population_manifest_sha256=MANIFEST)
    arguments.update(overrides)
    return ev.paired_cluster_bootstrap(a, b, queries, **arguments)


def test_superiority_rule_and_determinism(pair):
    good, silent, half, near, queries = pair
    first = compare(good, silent, queries)
    assert first.outcome == "superior" and first.difference == 1 and first.lower > 0
    assert first == compare(good, silent, queries)
    assert first.cluster_signs == {"a": 70, "b": 0, "tie": 0, "insufficient": 0}
    assert compare(good, half, queries).outcome == "superior"
    small = compare(good, near, queries)
    assert small.difference < ev.MPID and small.outcome == "not-superior"  # observed below MPID
    assert compare(good, good, queries).outcome == "not-superior"


def test_interval_must_exclude_zero_even_above_mpid():
    # One site carries the whole difference: observed ΔD ≥ MPID, but resampling frequently drops it.
    a = [_track(f"t{i}", "siteA" if i < 10 else f"site{i}", _plate_text(i), [_plate_text(i)]) for i in range(70)]
    b = [_track(f"t{i}", "siteA" if i < 10 else f"site{i}", _plate_text(i), ["" if i < 10 else _plate_text(i)])
         for i in range(70)]
    queries = _queries(a)
    result = ev.paired_cluster_bootstrap(a, b, queries, replicates=300, seed=3, required_clusters=60,
                                         population_manifest_sha256=MANIFEST)
    assert result.difference >= ev.MPID
    assert result.outcome == ("superior" if result.lower > 0 else "not-superior")
    assert result.lower <= 0 and result.outcome == "not-superior"


def test_fast_bootstrap_equals_re_evaluation(pair):
    good, _, half, _, queries = pair
    kwargs = dict(replicates=15, seed=11, population_manifest_sha256=MANIFEST)
    assert ev.bootstrap_replicates(good, half, queries, **kwargs) == \
        ev.bootstrap_replicates(good, half, queries, slow=True, **kwargs)


def test_bootstrap_refusals_and_no_silent_drops(pair):
    good, silent, half, _, queries = pair
    assert compare(good, silent, queries, required_clusters=100).outcome == "insufficient-clusters"
    with pytest.raises(ValueError, match="absolute_minimum"):
        compare(good, silent, queries, required_clusters=59)
    with pytest.raises(ValueError, match="replicates"):
        compare(good, silent, queries, replicates=0)
    with pytest.raises(ValueError, match="physical_capture_site"):
        compare(good, silent, queries, cluster_unit="sequence")
    for field, value in (("cluster", "other"), ("truth", "KA00AB9999")):
        changed = [dataclasses.replace(silent[0], **{field: value})] + silent[1:]
        with pytest.raises(ValueError, match="paired_population_mismatch"):
            compare(good, changed, queries)
    assert ev.bootstrap_replicates(good, silent, queries, replicates=50, seed=1,
                                   population_manifest_sha256=MANIFEST).count(None) == 0  # silence never drops
    violating = [_track("t0", "site0", _plate_text(0), [_plate_text(0)], boxes=3)] + good[1:]
    assert compare(violating, silent, queries).outcome == "contract-fail"


def test_top_k_is_deterministic_and_excludes_failures():
    scores = [ev.ComponentScore("PD2-S", True, 100, 0.9, 0.1, 0.8), ev.ComponentScore("PD2-N", True, 100, 0.9, 0.1, 0.9),
              ev.ComponentScore("PD5-V5M", False, 100, 0.99, 0.0, 0.99), ev.ComponentScore("PD2-M", True, 10, 1, 0, 1),
              ev.ComponentScore("PD5-V6S", True, 100, None, None, None),
              ev.ComponentScore("PD9-X", True, 100, 1.0, 0.0, 1.0, contract_fail=True)]
    assert ev.top_k(scores, 3, 50, "detector") == ["PD2-N", "PD2-S", "PD5-V6S"]
    ocr = [ev.ComponentScore("OC2-B", True, 60, 0.8, 0.1, 0.2), ev.ComponentScore("OC2-A", True, 60, 0.8, 0.1, None)]
    assert ev.top_k(ocr, 2, 50, "recogniser") == ["OC2-B", "OC2-A"]
    assert (ev.MPID, ev.ABSOLUTE_MINIMUM_CLUSTERS, ev.RANKING_OCR_CONFIDENCE_FLOOR) == (Fraction(4, 100), 60, 0.0)
    params = ev.ranking_parameters(0.25)
    assert (params.max_detections_per_crop, params.max_plates_per_crop, params.max_readings_per_plate,
            params.ocr_confidence_floor) == (2, 1, 3, 0.0)
