"""A–D evaluators and the query generator on synthetic fixtures only (no dataset, no model)."""

from __future__ import annotations

import dataclasses
import hashlib
import io
import math
import random
import uuid
from fractions import Fraction

import pytest
from PIL import Image

from mavi_vision.plates import pipeline
from mavi_vision.plates.inference import PlateBox, Reading, VerifiedCrop
from mavi_vision.plates.pipeline import PlateRecord, RankedReading
from tools.benchmarks.capabilities.plates import evaluator as ev
from tools.benchmarks.capabilities.plates import queries as q

PARAMS = q.QueryParameters(interior_offset=1, negatives_per_plate=2, seed="synthetic-seed")
MANIFEST = hashlib.sha256(b"synthetic-population-manifest").hexdigest()
OTHER_MANIFEST = hashlib.sha256(b"another-population").hexdigest()
FLOOR = 0.25


def gen(truths, manifest=MANIFEST):
    return q.generate(truths, PARAMS, manifest)


def population_of(items, manifest=MANIFEST):
    """Fixture: the closed population these items describe (in the event this is the frozen corpus manifest)."""
    return ev.closed_population([ev.PopulationTrack(i.track_id, i.cluster, i.truth, i.run is not ev.NO_RUN)
                                 for i in items], manifest)


def bind(queries, items, manifest=MANIFEST):
    return dict(population=population_of(items, manifest), generator_config_sha256=queries.generator_config_sha256,
                query_set_sha256=queries.query_set_sha256)


def _h(text):
    return hashlib.sha256(text.encode()).hexdigest()


def ident(candidate_id):
    return ev.ComponentIdentity(candidate_id, _h(candidate_id))


DET, REC, OC5, PD_BASE = ident("PD2-S"), ident("OC1-XS"), ident("OC5-BEST"), ident("PD2-N")
EVENTS = ("msr-ocr-2026-01", "GATE-BASE", "msr-plate-detector-2026-01")


def comp(candidate_id, independent, support, primary, second, third, contract_fail=False, kind="detector"):
    """Test fixture only: a ranking-path component score with chosen metrics."""
    return ev._seal(ev._COMPONENT, ev.ComponentScore(candidate_id, independent, support, primary, second, third,
                                                     contract_fail, _h(candidate_id), kind))


def relabel(score, detector, recogniser):
    """Test fixture only: a ranking-path D score for a chosen composition (builds fixtures cheaply)."""
    return ev._seal(ev._D, dataclasses.replace(score, detector=ident(detector), recogniser=ident(recogniser), seal=""))


def C(detector, recogniser, score):
    """Fixture: a sealed score is re-sealed under the named composition; an unsealed (forged/diagnostic) one is
    wrapped unchanged so the code under test sees it as it is."""
    if isinstance(score, ev.TrackScore) and ev._is_sealed(ev._D, score):
        score = relabel(score, detector, recogniser)
    return ev.CompositionScore(score)


def read(items):
    return ev.evaluate_reading(items, recogniser=REC)


def detect(items, detector_floor=FLOOR):
    """Hand-built A items: the diagnostic path (never sealed)."""
    return ev.diagnostic_evaluate_detection(items, detector_floor)


def detect_ranked(items, detector_floor=FLOOR):
    return ev.evaluate_detection(items, detector_floor, detector=DET)


def with_d(base, d, **changes):
    """Test fixture only: a ranking-path D score with a chosen D value."""
    return ev._seal(ev._D, dataclasses.replace(base, d_score=d, seal="", **changes))


# Stage 1 (synthetic): the frozen eligible detector universe, OC5 identity, Layer-A gates, freeze time and rule.
FREEZE = ev.BaselineFreeze((("PD1-X", _h("PD1-X")), ("PD2-N", _h("PD2-N")), ("PD2-S", _h("PD2-S"))),
                           "OC5-BEST", _h("OC5-BEST"), _h("layer-a-gates"), "2026-10-01T00:00:00Z", *EVENTS, 7)
WHEN = "2026-10-14T00:00:00Z"


def _layer_a(passed=("PD2-N", "PD2-S"), metrics=None, identities=None):
    metrics = metrics or {"PD1-X": (0.99, 0.0, 0.99), "PD2-N": (0.95, 0.10, 0.90), "PD2-S": (0.93, 0.05, 0.92)}
    identities = identities or {}
    return [ev.LayerAResult(comp(d, True, 100, *metrics[d]), identities.get(d, h), d in passed)
            for d, h in FREEZE.eligible_detectors]


RESOLUTION = ev.resolve_baseline(FREEZE, _layer_a(), d_rows_read=0, resolved_at_utc=WHEN)
LAYER_A = _layer_a()


def gate(composition, baseline, resolution=RESOLUTION, **kwargs):
    return ev.baseline_gate(composition, baseline, resolution, FREEZE, LAYER_A, **kwargs)


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
    q.verify(first)


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
    items = [ev.DetectionItem("c1", (SQUARE,), ((10, 10, 20, 10, 0.9), (60, 60, 5, 5, 0.8)), "day", (100, 100)),
             ev.DetectionItem("c2", (((0, 0), (10, 0), (10, 10), (0, 10)),), ((0, 0, 10, 10, 0.1),), "night", (100, 100))]
    result = detect(items, detector_floor=FLOOR)
    assert (result.outcome, result.plates, result.covered, result.recall) == (ev.MEASURED, 2, 1, Fraction(1, 2))
    assert result.below_floor_proposals == 1 and result.false_plates_per_crop == Fraction(1, 2)
    assert result.per_stratum["day"]["status"] == ev.INSUFFICIENT


def test_five_junk_proposals_are_a_contract_fail_not_a_good_score():
    junk = tuple((x, 0, 40, 40, 0.9) for x in range(0, 50, 10))  # would cover the plate several times over
    result = detect([ev.DetectionItem("c", (SQUARE,), junk, crop_size=(100, 100))], detector_floor=FLOOR)
    assert result.outcome == ev.CONTRACT_FAIL and result.recall is None
    assert result.contract_violations == ("plate_detector_output_exceeds_bound:c",)


@pytest.mark.parametrize("proposal, code", [
    ((10, 10, 20, 10, float("nan")), "score_out_of_range"),  # review: was counted "below floor"
    ((10, 10, 20, 10, 1.5), "score_out_of_range"),
    ((10.5, 10, 20, 10, 0.9), "box_not_integer"),
    ((10, 10, 0, 10, 0.9), "box_degenerate"),
    ((-1, 10, 20, 10, 0.9), "box_degenerate"),
    ((50, 10, 20, 10, 0.9), "box_outside_crop"),
    ((10, 10, 20), "not_a_proposal"),
])
def test_any_malformed_proposal_is_a_contract_fail_in_a(proposal, code):
    result = detect([ev.DetectionItem("c", (SQUARE,), (proposal,), crop_size=(64, 32))], FLOOR)
    assert result.outcome == ev.CONTRACT_FAIL and code in result.contract_violations[0]


def test_a_coverage_is_exact_at_the_threshold():
    wide, short = ((0, 0), (100, 0), (100, 1), (0, 1)), ((0, 0), (20, 0), (20, 1), (0, 1))
    assert ev.coverage(wide, (0, 0, 95, 1)) == Fraction(95, 100)
    assert ev.coverage(short, (0, 0, 19, 1)) == Fraction(19, 20)
    for polygon, width in ((wide, 95), (short, 19)):
        result = detect([ev.DetectionItem("c", (polygon,), ((0, 0, width, 1, 0.9),), crop_size=(100, 1))], FLOOR)
        assert result.covered == 1  # exactly 0.95 is covered
    below = detect([ev.DetectionItem("c", (wide,), ((0, 0, 94, 1, 0.9),), crop_size=(100, 1))], FLOOR)
    assert below.covered == 0


# ---------------------------------------------------------------------------------------------- B / C


def _plate(*readings):
    return ev.ranking_plate_record([Reading(t, c) for t, c in readings], recogniser=REC)


def test_reading_rules_follow_pr3_and_any_violation_fails():
    assert _plate(("KA01AB1234", 0.01)).plate.outcome == "read"  # ranking floor 0
    # Bake-off rule (owner ruling 8/11): these are contract FAILs, not "not read" (review P1-1).
    assert "non_strict_rank_order" in _plate(("X", 0.5), ("X", 0.5)).contract_violation
    assert "invalid_raw_text" in _plate(("", 0.5)).contract_violation
    assert "confidence_out_of_range" in _plate(("KA01", 1.5)).contract_violation
    assert "confidence_out_of_range" in _plate(("KA01", float("nan"))).contract_violation
    assert "not_a_reading" in ev.ranking_plate_record([("KA01", 0.5)], recogniser=REC).contract_violation
    over = _plate(("A", 0.1), ("B", 0.2), ("C", 0.3), ("D", 0.4))
    assert over.contract_violation.startswith("plate_recogniser_output_exceeds_bound")
    diagnostic = ev.diagnostic_plate_record([Reading("KA01", 0.2)], 0.5)
    assert diagnostic.plate.outcome == "unreadable"
    with pytest.raises(ValueError, match="ranking_profile"):
        read([ev.ReadItem("p", "KA01", diagnostic)])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="not_declared"):
        ev.diagnostic_plate_record([Reading("KA01", 0.2)], 0.0)
    plate = _plate(("KA01", 0.5)).plate
    assert isinstance(plate, PlateRecord) and isinstance(plate.readings[0], RankedReading)
    for bad in (over, _plate(("X", 0.5), ("X", 0.5))):
        failed = read([ev.ReadItem("p", "KA01", bad)])
        assert failed.outcome == ev.CONTRACT_FAIL and failed.em is None


def test_public_ranking_equals_pr3_internal_ranking():
    parameters = ev.ranking_parameters(FLOOR)
    for readings in ([Reading("KA01", 0.5)], [Reading("B", 0.2), Reading("A", 0.2), Reading("C", 0.9)],
                     [Reading("KA\n01", 0.3), Reading("KA01", 0.3)], []):
        assert ev._rank_plate(readings, parameters) == pipeline._plate(0, readings, parameters)


def test_reading_metrics_and_input_order_invariance():
    items = [ev.ReadItem("p1", "KA01AB1234", _plate(("ka01 ab1234", 0.9))),
             ev.ReadItem("p2", "KA01AB1234", _plate(("KA01AB1284", 0.8), ("KA01AB1234", 0.7))),
             ev.ReadItem("p3", "KA01AB1234", ev.not_read()), ev.ReadItem("p4", "a@b", ev.not_read()),
             ev.ReadItem("p5", "MH12AB0001", _plate(("MH12AB0001", 0.8)))]
    result = read(items)
    assert (result.plates, result.exact, result.unsupported_truths) == (4, 2, 1)
    assert result.em == Fraction(1, 2) and result.top_k_hit == Fraction(3, 4)
    for seed in range(5):
        shuffled = list(items)
        random.Random(seed).shuffle(shuffled)
        again = read(shuffled)
        assert (again.ece, again.risk_coverage, again.em) == (result.ece, result.risk_coverage, result.em)
    assert ev.c_minus_b(result, result) == 0
    with pytest.raises(ValueError, match="ranking_profile"):  # a hand-built plate is not ranking provenance
        read([ev.ReadItem("p", "KA01", ev.RankingPlate(None))])


def test_ece_refuses_duplicate_ids_and_uses_equal_mass_bins():
    items = [ev.ReadItem("p", "KA01AB1234", _plate(("KA01AB1234", 0.5))),
             ev.ReadItem("p", "KA01AB1234", _plate(("KA01AB0000", 0.5)))]
    with pytest.raises(ValueError, match="duplicate_plate_id"):
        read(items)
    rows = [(0.9 - i * 0.01, i % 2 == 0, f"q{i:02d}") for i in range(11)]
    bins = {}
    for k in range(11):
        bins.setdefault(k * ev.ECE_BINS // 11, []).append(k)
    assert len(bins) == 10 and {len(v) for v in bins.values()} == {1, 2}  # true equal-mass, not ⌈n/10⌉ chunks
    expected = sum(len(v) / 11 * abs(sum(rows[k][0] for k in v) / len(v) - sum(rows[k][1] for k in v) / len(v))
                   for v in bins.values())
    assert ev._ece(rows) == pytest.approx(expected, abs=0)


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


class Outputs:
    """A recogniser returning the given reading lists in order."""

    def __init__(self, outputs):
        self.outputs = list(outputs)

    def read(self, region, verified, box):
        return self.outputs.pop(0)


def _crops(track_id, n):
    return [ev.EvidenceCrop(uuid.uuid5(uuid.NAMESPACE_URL, f"{track_id}/{i}"), "near-view", i, SHA, JPEG)
            for i in range(n)]


def _track(track_id, cluster, truth, readings, *, boxes=1, parameters=None, det=DET, rec=REC):
    detector = Detector([PlateBox(1 + k, 1, 20, 10, 0.9 - 0.1 * k) for k in range(boxes)])
    run = ev.run_track(uuid.uuid5(uuid.NAMESPACE_URL, track_id), _crops(track_id, len(readings)), detector,
                       Recogniser(readings), parameters or ev.ranking_parameters(FLOOR), detector_identity=det,
                       recogniser_identity=rec)
    return ev.TrackItem(track_id, cluster, truth, run)


def _plate_text(i):
    return f"KA{i % 100:02d}AB{1000 + i}"


def _population(n, read):
    return [_track(f"t{i}", f"site{i}", _plate_text(i), read(i)) for i in range(n)]


def _queries(items, manifest=MANIFEST):
    special = (ev.NO_PLATE, ev.UNREADABLE, ev.NO_GT_VEHICLE)
    return gen([i.truth for i in items if i.truth not in special and ev.normalised_truth(i.truth)], manifest)


def score(items, queries=None, floor=FLOOR, composition=None, population=None):
    queries = queries or _queries(items)
    run = next((i.run for i in items if isinstance(i.run, ev.TrackRun)), None)
    detector, recogniser = composition or ((run.detector, run.recogniser) if run is not None else (DET, REC))
    return ev.evaluate_tracks(items, queries, detector_floor=floor, detector=detector, recogniser=recogniser,
                              **dict(bind(queries, items), **({"population": population} if population else {})))


# ---------------------------------------------------------------------------------------------- D


def test_d_score_on_a_closed_population_exactly():
    items = [_track("t1", "s1", "KA01AB1234", ["KA01AB1234"]),
             _track("t2", "s1", "MH12CD5678", ["MH12CD5670", "MH12CD5670"]),
             _track("t3", "s2", ev.NO_PLATE, ["KA01ZZ9999"]),
             _track("t5", "s2", ev.NO_GT_VEHICLE, ["DL3CAB0002"]),
             ev.TrackItem("t4", "s2", "DL3CAB0001", ev.NO_RUN)]
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
    assert (result.population_manifest_sha256, result.query_set_sha256) == (MANIFEST, queries.query_set_sha256)


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
    other = gen(["KA01AB1234"], OTHER_MANIFEST)
    with pytest.raises(ValueError, match="another_population"):
        ev.evaluate_tracks(plain, other, detector_floor=FLOOR, detector=DET, recogniser=REC, **bind(other, plain))
    with pytest.raises(ValueError, match="not_bound"):
        score(plain, gen(["KA01AB1234", "MH12AB0001"]))
    with pytest.raises(ValueError, match="truth_empty"):
        score([ev.TrackItem("e", "s", " ", ev.NO_RUN)], gen([]))


def test_query_set_hashes_are_recomputed_not_trusted():
    ranked = _population(3, lambda i: [_plate_text(i)])
    queries = _queries(ranked)
    tampered = dataclasses.replace(queries, metric_queries=queries.metric_queries[:1])  # SHA fields kept
    with pytest.raises(ValueError, match="do_not_match"):
        ev.evaluate_tracks(ranked, tampered, detector_floor=FLOOR, detector=DET, recogniser=REC, **bind(queries, ranked))
    relabelled = dataclasses.replace(queries, generator_config_sha256="0" * 64)
    with pytest.raises(ValueError, match="do_not_match"):
        ev.evaluate_tracks(ranked, relabelled, detector_floor=FLOOR, detector=DET, recogniser=REC, **bind(queries, ranked))
    other_params = q.generate(queries.truths, q.QueryParameters(2, 1, "another-seed"), MANIFEST)
    with pytest.raises(ValueError, match="generator_config_not_frozen"):
        ev.evaluate_tracks(ranked, other_params, detector_floor=FLOOR, detector=DET, recogniser=REC, **bind(queries, ranked))
    with pytest.raises(ValueError, match="query_set_not_frozen"):
        ev.evaluate_tracks(ranked, queries, detector_floor=FLOOR, detector=DET, recogniser=REC, **dict(bind(queries, ranked), query_set_sha256="1" * 64))
    with pytest.raises(ValueError, match="do_not_match"):
        ev._bootstrap_replicates(ranked, ranked, tampered, replicates=2, seed=1, detector_floor_a=FLOOR,
                                detector_floor_b=FLOOR, composition_a=(DET, REC), composition_b=(DET, REC), **bind(queries, ranked))


def test_contract_violation_fails_the_whole_composition():
    items = [_track("t1", "s1", "KA01AB1234", ["KA01AB1234"]),
             _track("t2", "s2", "MH12AB0001", ["MH12AB0001"], boxes=3)]
    result = score(items)
    assert (result.outcome, result.d_status, result.d_score) == (ev.CONTRACT_FAIL, ev.CONTRACT_FAIL, None)
    assert len(result.contract_violations) == 1
    assert result.contract_violations[0].startswith("plate_detector_output_exceeds_bound@count=3:obs=")
    assert result.contract_violations[0].endswith(":t2")
    assert result.consistent_wrong_status == ev.FAIL
    base = score([items[0], _track("t2", "s2", "MH12AB0001", ["MH12AB0001"])])
    assert gate(C("PD2-S", "OC1-XS", result), C("PD2-N", "OC5-BEST", base)) == ev.FAIL
    with pytest.raises(ev.BaselineStop, match="baseline_contract_violation"):  # never replaced: the event stops
        gate(C("PD2-S", "OC1-XS", base), C("PD2-N", "OC5-BEST", result))


# ---------------------------------------------------------------------------------------------- P1-1 probes


class _OutOfBounds:
    def detect(self, crop, verified):
        return [PlateBox(0, 0, 500, 500, 0.9)]


class _NaNScore:
    def detect(self, crop, verified):
        return [PlateBox(1, 1, 20, 10, float("nan"))]


class _NotABox:
    def detect(self, crop, verified):
        return [(1, 1, 20, 10, 0.9)]


class _FloatBox:
    def detect(self, crop, verified):
        return [PlateBox(1.5, 1, 20, 10, 0.9)]


class _Crash:
    def detect(self, crop, verified):
        raise RuntimeError("model fault")


class _CrashOcr:
    def read(self, region, verified, box):
        raise MemoryError("ocr fault")


GOOD_BOX = Detector([PlateBox(1, 1, 20, 10, 0.9)])


@pytest.mark.parametrize("detector, recogniser, code", [
    (_OutOfBounds(), Recogniser(["KA01AB1234"]), "box_outside_crop"),
    (_NaNScore(), Recogniser(["KA01AB1234"]), "score_out_of_range"),
    (_NotABox(), Recogniser(["KA01AB1234"]), "not_a_platebox"),
    (_FloatBox(), Recogniser(["KA01AB1234"]), "box_not_integer"),
    (_Crash(), Recogniser([]), "plate_detector_runtime_error"),
    (GOOD_BOX, Outputs([[Reading("KA01", 1.5)]]), "confidence_out_of_range"),
    (GOOD_BOX, Outputs([[Reading("", 0.5)]]), "invalid_raw_text"),
    (GOOD_BOX, Outputs([[Reading("KA01", 0.5), Reading("KA01", 0.5)]]), "non_strict_rank_order"),
    (GOOD_BOX, Outputs([["KA01"]]), "not_a_reading"),
    (GOOD_BOX, _CrashOcr(), "plate_recogniser_runtime_error"),
])
def test_any_output_contract_violation_is_a_hard_fail_in_d(detector, recogniser, code):
    crops = _crops("m", 1)
    run = ev.run_track(uuid.uuid5(uuid.NAMESPACE_URL, "m"), crops, detector, recogniser, ev.ranking_parameters(FLOOR),
                       detector_identity=DET, recogniser_identity=REC)
    assert run.record is None and code in run.contract_violation
    assert f"obs={crops[0].observation_id}" in run.contract_violation  # exact evidence kept
    result = score([ev.TrackItem("m", "s", "KA01AB1234", run)])
    assert (result.outcome, result.d_score) == (ev.CONTRACT_FAIL, None)  # never silence scored as 0
    observation = crops[0].observation_id
    item = ev.detection_item_from_run("m", (SQUARE,), run, observation, detector_floor=FLOOR)
    assert detect_ranked([item]).outcome == ev.CONTRACT_FAIL  # A
    c = read([ev.ReadItem("m", "KA01AB1234", ev.accepted_plate(run, observation))])
    assert c.outcome == ev.CONTRACT_FAIL  # C


def test_product_abstains_where_the_bake_off_fails():
    crops = _crops("p", 1)
    observation = ev.lease_observation(crops[0].observation_id, "near-view", 0, len(JPEG), SHA)
    verified = VerifiedCrop(str(crops[0].observation_id), "near-view", 0, SHA, JPEG)
    duplicate = [Reading("KA01", 0.5), Reading("KA01", 0.5)]
    product = pipeline.analyse_crop(observation, verified, GOOD_BOX, Outputs([duplicate]), ev.ranking_parameters(FLOOR))
    assert (product.status, product.reason) == ("abstained", "ocr_output_invalid")  # PR-3 product rule, unchanged
    run = ev.run_track(uuid.uuid5(uuid.NAMESPACE_URL, "p"), crops, GOOD_BOX, Outputs([duplicate]),
                       ev.ranking_parameters(FLOOR), detector_identity=DET, recogniser_identity=REC)
    assert "non_strict_rank_order" in run.contract_violation  # owner's bake-off rule


def test_valid_runs_are_unchanged_by_the_guards():
    run = _track("ok", "s", "KA01AB1234", ["KA01AB1234"]).run
    assert run.contract_violation is None and run.record.outcome == "analysed"
    observation = run.record.crops[0].observation_id
    item = ev.detection_item_from_run("ok", (SQUARE,), run, observation, detector_floor=FLOOR)
    assert item.crop_size == (64, 32) and len(item.proposals) == 1
    assert ev.accepted_plate(run, observation).plate.readings[0].raw_text == "KA01AB1234"


# ---------------------------------------------------------------------------------------------- P2-1 diagnostics


def test_ranking_floor_is_enforced_and_diagnostics_are_separate():
    floored = ev.PlateParameters(2, 1, 3, 0.25, 0.5, frozenset(), None)
    items = [_track("t1", "s1", "KA01AB1234", ["KA01AB1234"], parameters=floored)]
    with pytest.raises(ValueError, match="ranking_profile"):
        score(items)
    ranked = [_track("t1", "s1", "KA01AB1234", ["KA01AB1234"])]
    queries = _queries(ranked)
    diagnostic = ev.diagnostic_evaluate_at_floor(ranked, queries, 0.5, detector_floor=FLOOR, detector=DET, recogniser=REC, **bind(queries, ranked))
    assert isinstance(diagnostic, ev.DiagnosticTrackScore) and diagnostic.values.accounting["diagnosticFloor"] == 0.5
    with pytest.raises(ValueError, match="not_declared"):
        ev.diagnostic_evaluate_at_floor(ranked, queries, 0.0, detector_floor=FLOOR, detector=DET, recogniser=REC, **bind(queries, ranked))
    with pytest.raises(ValueError, match="pinned_detector_floor"):
        score(ranked, floor=0.3)


def test_gates_and_decisions_refuse_diagnostic_and_forged_scores():
    ranked = _population(3, lambda i: [_plate_text(i)])
    queries = _queries(ranked)
    silent = score(_population(3, lambda i: [""]))
    diag = ev.diagnostic_evaluate_at_floor(ranked, queries, 0.7, detector_floor=FLOOR, detector=DET, recogniser=REC, **bind(queries, ranked))
    for forged in (diag, diag.values, dataclasses.replace(silent, d_score=Fraction(1))):
        with pytest.raises(ValueError, match="not_a_ranking_d_score"):
            gate(C("PD2-S", "OC1", silent), C("PD2-N", "OC5-BEST", forged))
        with pytest.raises(ValueError, match="not_a_ranking_d_score"):
            gate(C("PD2-S", "OC1", forged), C("PD2-N", "OC5-BEST", silent))
        with pytest.raises(ValueError, match="not_a_ranking_d_score"):
            ev.diagnostic_ocr_uplift(C("PD2-S", "OC1", forged),
                                     C("PD2-S", "OC5-BEST", silent), FREEZE)
    # A refloored (diagnostic) record relabelled as a ranking run is refused on the ranking path.
    relabelled = ev.TrackRun(ev._refloor(ranked[0].run.record, 0.95), None, ev.ranking_parameters(FLOOR))
    forged_items = [dataclasses.replace(ranked[0], run=relabelled)] + ranked[1:]
    with pytest.raises(ValueError, match="not_from_ranking_path"):
        score(forged_items, queries, composition=(DET, REC))
    with pytest.raises(ValueError, match="not_from_ranking_path"):
        ev._bootstrap_replicates(forged_items, ranked, queries, replicates=2, seed=1, detector_floor_a=FLOOR,
                                detector_floor_b=FLOOR, composition_a=(DET, REC), composition_b=(DET, REC), **bind(queries, ranked))
    relabel_floor = dataclasses.replace(ranked[0].run, parameters=ev.ranking_parameters(0.1))
    with pytest.raises(ValueError, match="not_from_ranking_path"):
        score([dataclasses.replace(ranked[0], run=relabel_floor)] + ranked[1:], queries, composition=(DET, REC))
    with pytest.raises(ValueError, match="not_from_ranking_path"):
        ev.top_k([ev.ComponentScore("OC2-A", True, 100, 0.9, 0.1, 0.1)], 1, 50, "recogniser",
                 freeze=FREEZE)
    with pytest.raises(ValueError, match="not_from_ranking_path"):
        ev.detector_component(True, dataclasses.replace(detect([], FLOOR), plates=99))


def test_candidate_silence_scores_zero_and_corpus_deficiency_is_insufficient():
    silent_items = _population(3, lambda i: [""])
    result = score(silent_items)
    assert (result.outcome, result.d_status) == (ev.MEASURED, ev.MEASURED)
    assert (result.exact_recall, result.contains_recall, result.contains_precision, result.d_score) == (0, 0, 0, 0)
    good = score(_population(3, lambda i: [_plate_text(i)]))
    assert gate(C("PD2-N", "OC1-XS", good),
                C("PD2-N", "OC5-BEST", result)) == ev.PASS  # a silent baseline is valid and scores 0
    no_plates = [_track("n", "s1", ev.NO_PLATE, ["KA01AB1234"])]
    deficient = score(no_plates, gen([]))
    assert deficient.d_status == ev.INSUFFICIENT and deficient.d_score is None
    deficient_bound = with_d(deficient, None, query_set_sha256=result.query_set_sha256,
                             generator_config_sha256=result.generator_config_sha256,
                             population_digest=result.population_digest)
    assert gate(C("PD2-N", "OC1-XS", deficient_bound),
                C("PD2-N", "OC5-BEST", result)) == ev.INSUFFICIENT
    with pytest.raises(ev.BaselineStop, match="baseline_not_evaluable"):
        gate(C("PD2-N", "OC1-XS", good), C("PD2-N", "OC5-BEST", with_d(good, None)))
    with pytest.raises(ValueError, match="same_population_and_query_set"):  # P3: scores bound to one population
        gate(C("PD2-N", "OC1-XS", deficient), C("PD2-N", "OC5-BEST", result))


def test_mpid_boundary_is_exact_and_pinned():
    base = score(_population(1, lambda i: [_plate_text(i)]))

    def check(high, low, detector="PD2-S", **kwargs):
        return gate(C(detector, "OC1-XS", with_d(base, high)),
                    C("PD2-N", "OC5-BEST", with_d(base, low)), **kwargs)

    assert 0.47 - 0.43 < 0.04  # the float trap the exact path avoids
    assert check(Fraction(47, 100), Fraction(43, 100)) == ev.PASS
    assert check(Fraction(4, 100), Fraction(0)) == ev.PASS
    assert check(Fraction(399, 10000), Fraction(0)) == ev.FAIL
    assert check(Fraction(1, 3) + Fraction(4, 100), Fraction(1, 3)) == ev.PASS
    assert check(Fraction(4, 100), Fraction(0), detector="PD1-X") == ev.PASS  # one baseline for every detector
    for mpid in (0.04, Fraction(3, 100)):
        with pytest.raises(ValueError, match="frozen_fraction"):
            check(Fraction(47, 100), Fraction(43, 100), mpid=mpid)
    with pytest.raises(ValueError, match="sealed_pd_base"):  # a detector-matched PD2-S + OC5 is not the hard baseline
        gate(C("PD2-S", "OC1-XS", base), C("PD2-S", "OC5-BEST", base))
    with pytest.raises(ValueError, match="sealed_pd_base"):
        gate(C("PD2-S", "OC1-XS", base), C("PD2-N", "OC2-V6S", base))


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
    with pytest.raises(ev.BaselineStop, match="layer_a_rank_ambiguous"):  # review 4 P2-3a: ambiguity STOPS
        ev.resolve_baseline(FREEZE, _layer_a(("PD2-S", "PD2-N"), tied), d_rows_read=0, resolved_at_utc=WHEN)
    tied_below = {"PD1-X": (0.9, 0.1, 0.9), "PD2-N": (0.95, 0.1, 0.9), "PD2-S": (0.9, 0.1, 0.9)}
    assert ev.resolve_baseline(FREEZE, _layer_a(("PD2-S", "PD2-N", "PD1-X"), tied_below), d_rows_read=0,
                               resolved_at_utc=WHEN).pd_base_id == "PD2-N"  # a tie below the top does not matter
    second = {"PD1-X": (0.9, 0.1, 0.9), "PD2-N": (0.9, 0.2, 0.99), "PD2-S": (0.9, 0.1, 0.5)}
    assert ev.resolve_baseline(FREEZE, _layer_a(("PD2-S", "PD2-N"), second), d_rows_read=0,
                               resolved_at_utc=WHEN).pd_base_id == "PD2-S"
    missing = {"PD1-X": (0.9, 0.1, 0.9), "PD2-N": (None, 0.0, 0.99), "PD2-S": (0.1, 0.9, 0.1)}
    assert ev.resolve_baseline(FREEZE, _layer_a(("PD2-S", "PD2-N"), missing), d_rows_read=0,
                               resolved_at_utc=WHEN).pd_base_id == "PD2-S"


def test_pd_base_resolution_stops_and_never_chooses():
    def stop(reason, results, **kw):
        with pytest.raises(ev.BaselineStop, match=reason):
            ev.resolve_baseline(FREEZE, results, d_rows_read=kw.get("d_rows_read", 0),
                                resolved_at_utc=kw.get("when", WHEN))

    stop("no_detector_passed_layer_a", _layer_a(passed=()))
    stop("after_d_data_read", _layer_a(), d_rows_read=1)
    stop("before_freeze", _layer_a(), when="2026-09-30T23:59:59Z")
    stop("time_malformed", _layer_a(), when="2026-10-14 00:00")
    outsider = _layer_a() + [ev.LayerAResult(comp("PD9-NEW", True, 100, 1.0, 0.0, 1.0), _h("PD9-NEW"), True)]
    stop("inconsistent_with_frozen_detector_universe", outsider)  # cannot resolve to an unfrozen detector
    stop("inconsistent_with_frozen_detector_universe", _layer_a()[1:])
    stop("ambiguous_duplicate_detector", _layer_a() + _layer_a()[1:2])
    stop("identity_mismatch:PD2-N", _layer_a(identities={"PD2-N": _h("PD2-N-retrained")}))
    failed = _layer_a()
    failed[1] = dataclasses.replace(failed[1], score=comp("PD2-N", True, 100, 0.95, 0.1, 0.9, contract_fail=True))
    stop("gate_pass_with_contract_fail:PD2-N", failed)
    stop("non_finite_metric:PD2-N", _layer_a(metrics={"PD1-X": (0.9, 0.1, 0.9), "PD2-N": (float("nan"), 0.1, 0.9),
                                                      "PD2-S": (0.9, 0.1, 0.9)}))
    hand_built = _layer_a()
    hand_built[1] = dataclasses.replace(hand_built[1], score=ev.ComponentScore("PD2-N", True, 100, 0.95, 0.1, 0.9))
    stop("not_from_ranking_path:PD2-N", hand_built)
    with pytest.raises(ValueError, match="benchmark_only_component_cannot_be_a_detector_candidate"):
        ev.BaselineFreeze((("OC5-BEST", _h("x")), ("PD2-N", _h("PD2-N"))), "OC5-BEST", _h("o"), _h("g"), WHEN, *EVENTS, 7)
    with pytest.raises(ValueError, match="ranking_rule_not_the_frozen_rule"):
        ev.BaselineFreeze(FREEZE.eligible_detectors, "OC5-BEST", _h("o"), _h("g"), WHEN, *EVENTS, 7,
                          ranking_rule_sha256=_h("another rule"))
    with pytest.raises(ValueError, match="sorted_unique_nonempty"):
        ev.BaselineFreeze((), "OC5-BEST", _h("o"), _h("g"), WHEN, *EVENTS, 7)
    with pytest.raises(ValueError, match="time_malformed"):
        ev.BaselineFreeze(FREEZE.eligible_detectors, "OC5-BEST", _h("o"), _h("g"), "yesterday", *EVENTS, 7)


def test_sealed_resolution_cannot_change_or_be_forged_and_oc5_is_never_rankable():
    base = score(_population(1, lambda i: [_plate_text(i)]))
    swapped = dataclasses.replace(RESOLUTION, pd_base_id="PD2-S")  # an edit without re-sealing
    with pytest.raises(ev.BaselineStop, match="record_altered"):
        gate(C("PD2-S", "OC1-XS", base), C("PD2-S", "OC5-BEST", base), swapped)
    forged = dataclasses.replace(RESOLUTION, pd_base_id="PD1-X")  # review P2-2: forged AND re-sealed
    forged = dataclasses.replace(forged, record_sha256=ev._canonical_sha256(forged.payload()))
    with pytest.raises(ev.BaselineStop, match="differs_from_frozen_derivation"):
        gate(C("PD2-S", "OC1-XS", base), C("PD1-X", "OC5-BEST", base), forged)
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
    baseline = C("PD2-N", "OC5-BEST", with_d(base, Fraction(1, 2)))
    passing = C("PD2-S", "OC1-XS", with_d(base, Fraction(9, 10)))
    failing = C("PD1-X", "OC2-V6S", with_d(base, Fraction(1, 2)))
    assert ev.rankable_compositions([passing, failing], baseline, RESOLUTION, FREEZE, LAYER_A) == [passing]
    for bad in (C("PD2-N", "OC5-BEST", base), C("PD2-S", "OC5-BEST", base)):
        with pytest.raises(ValueError, match="cannot_be_ranked"):
            ev.rankable_compositions([passing, bad], baseline, RESOLUTION, FREEZE, LAYER_A)
        with pytest.raises(ValueError, match="cannot_be_ranked"):
            gate(bad, baseline)


def test_benchmark_only_component_never_enters_top_k():
    ocr = [comp("OC2-A", True, 100, 0.8, 0.1, 0.1, kind="recogniser"),
           comp("OC5-BEST", True, 100, 0.99, 0.0, 0.0, kind="recogniser")]
    with pytest.raises(ValueError, match="cannot_enter_top_k"):
        ev.top_k(ocr, 2, 50, "recogniser", freeze=FREEZE)
    assert ev.top_k(ocr[:1], 2, 50, "recogniser", freeze=FREEZE) == ["OC2-A"]
    with pytest.raises(TypeError):
        ev.top_k(ocr, 2, 50, "recogniser")  # type: ignore[call-arg]  # P2-5: the refusal is not opt-in
    with pytest.raises(ValueError, match="requires_the_baseline_freeze"):
        ev.top_k(ocr, 2, 50, "recogniser", freeze=None)


def test_detector_matched_tesseract_is_diagnostic_only():
    base = score(_population(1, lambda i: [_plate_text(i)]))
    high = C("PD2-S", "OC1-XS", with_d(base, Fraction(1, 2)))
    matched = C("PD2-S", "OC5-BEST", with_d(base, Fraction(1, 5)))
    assert ev.diagnostic_ocr_uplift(high, matched, FREEZE) == Fraction(3, 10)
    with pytest.raises(ValueError, match="not_detector_matched"):
        ev.diagnostic_ocr_uplift(high, C("PD2-N", "OC5-BEST", base), FREEZE)
    failed = C("PD2-S", "OC5-BEST", with_d(base, None, outcome=ev.CONTRACT_FAIL))
    assert ev.diagnostic_ocr_uplift(high, failed, FREEZE) is None  # a diagnostic, never a stop or a gate verdict


# ---------------------------------------------------------------------------------------------- N3 (owner 2026-10-14)


def _n3_item(track_id, outputs, truth="KA01AB1234"):
    crops = _crops(track_id, len(outputs))
    result = ev.run_track(uuid.uuid5(uuid.NAMESPACE_URL, track_id), crops, GOOD_BOX, Outputs(outputs),
                          ev.ranking_parameters(FLOOR), detector_identity=DET, recogniser_identity=REC)
    return ev.TrackItem(track_id, "s", truth, result)


def _n3(*outputs_per_track):
    items = [_n3_item(f"n{i}", outputs) for i, outputs in enumerate(outputs_per_track)]
    return score(items, gen(["KA01AB1234"])).counts


WRONG, RIGHT = "KA01AB1235", "KA01AB1234"


def test_n3_uses_rank0_only_probe2_alternates_case():
    # Review probe2: both rank-0 agree on a wrong text; alternates differ. Under rank-0 N3 both trip.
    a = _n3([[Reading(WRONG, 0.9)], [Reading(WRONG, 0.9)]])
    b = _n3([[Reading(WRONG, 0.9), Reading("KA01AB1299", 0.1)], [Reading(WRONG, 0.9), Reading("KA01AB1288", 0.1)]])
    assert (a.consistent_wrong, b.consistent_wrong) == (1, 1)


def test_n3_owner_edge_semantics():
    # 1. same wrong rank-0 plus differing low-ranked alternatives
    assert _n3([[Reading(WRONG, 0.9), Reading("KA01AB1299", 0.2), Reading("KA01AB1277", 0.1)],
                [Reading(WRONG, 0.9), Reading("KA01AB1288", 0.1)]]).consistent_wrong == 1
    # 2. same wrong rank-0 plus a correct rank-1
    assert _n3([[Reading(WRONG, 0.9), Reading(RIGHT, 0.5)], [Reading(WRONG, 0.9), Reading(RIGHT, 0.5)]]
               ).consistent_wrong == 1
    # 3. one correct rank-0 prevents it
    assert _n3([[Reading(WRONG, 0.9)], [Reading(RIGHT, 0.9)], [Reading(WRONG, 0.9)]]).consistent_wrong == 0
    # 4. conflicting wrong rank-0 values: not consistent-wrong, conflict diagnostic kept
    conflicting = _n3([[Reading(WRONG, 0.9)], [Reading("KA01AB1236", 0.9)]])
    assert (conflicting.consistent_wrong, conflicting.multi_source, conflicting.conflicting) == (0, 1, 1)
    # 5. one valid rank-0 source: not eligible, not in the conditional denominator
    single = _n3([[Reading(WRONG, 0.9)], []])
    assert (single.consistent_wrong, single.multi_source) == (0, 0)
    unnormalisable = _n3([[Reading(WRONG, 0.9)], [Reading("@@", 0.9), Reading(WRONG, 0.5)]])
    assert (unnormalisable.consistent_wrong, unnormalisable.multi_source) == (0, 0)  # a bad rank-0 gives no support
    # 6. three observations: all qualifying rank-0 readings participate, never a cherry-picked pair
    assert _n3([[Reading(WRONG, 0.9)], [Reading(WRONG, 0.9)], [Reading("KA01AB1236", 0.9)]]).consistent_wrong == 0
    assert _n3([[Reading(WRONG, 0.9)], [Reading(WRONG, 0.9)], [Reading(WRONG, 0.8)]]).consistent_wrong == 1


def test_n3_denominators_are_unchanged():
    # 7. primary = all evaluable supported plate-bearing Tracks; conditional = Tracks with ≥ 2 rank-0 sources.
    items = [_n3_item("w", [[Reading(WRONG, 0.9)], [Reading(WRONG, 0.9)]]),
             _n3_item("one", [[Reading(WRONG, 0.9)]]),
             _n3_item("ok", [[Reading(RIGHT, 0.9)], [Reading(RIGHT, 0.9)]]),
             ev.TrackItem("none", "s", "KA01AB1234", ev.NO_RUN),
             _n3_item("np", [[Reading(WRONG, 0.9)], [Reading(WRONG, 0.9)]], truth=ev.NO_PLATE)]
    result = score(items, gen(["KA01AB1234"]))
    assert result.consistent_wrong_rate == Fraction(1, 4)
    assert result.consistent_wrong_conditional_rate == Fraction(1, 2)
    assert result.consistent_wrong_status == ev.INSUFFICIENT  # support 4 < 50


# ---------------------------------------------------------------------------------------------- comparison


@pytest.fixture(scope="module")
def pair():
    good = _population(70, lambda i: [_plate_text(i)])
    silent = _population(70, lambda i: [""])
    half = _population(70, lambda i: [_plate_text(i) if i % 2 else ""])
    near = _population(70, lambda i: [_plate_text(i) if i % 25 else ""])  # ΔD ≈ 0.03 < MPID
    return good, silent, half, near, _queries(good)


def compare(a, b, queries, **overrides):
    arguments = dict(calibration_minimum_clusters=60, detector_floor_a=FLOOR, detector_floor_b=FLOOR,
                     composition_a=(DET, REC), composition_b=(DET, REC), freeze=FREEZE, **bind(queries, a))
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
    with pytest.raises(ValueError, match="frozen_fraction"):
        compare(good, silent, queries, mpid=0.04)


def test_interval_must_exclude_zero_even_above_mpid():
    # One site carries the whole difference: observed ΔD ≥ MPID, but resampling frequently drops it.
    a = [_track(f"t{i}", "siteA" if i < 10 else f"site{i}", _plate_text(i), [_plate_text(i)]) for i in range(70)]
    b = [_track(f"t{i}", "siteA" if i < 10 else f"site{i}", _plate_text(i), ["" if i < 10 else _plate_text(i)])
         for i in range(70)]
    queries = _queries(a)
    result = compare(a, b, queries)
    assert result.difference >= ev.MPID
    assert result.outcome == ("superior" if result.lower > 0 else "not-superior")
    assert result.lower <= 0 and result.outcome == "not-superior"


def test_percentile_indices_are_exact_integers():
    for r in range(1, 20001):
        assert ev.percentile_indices(r) == (math.floor(Fraction(25, 1000) * (r - 1)),
                                            math.ceil(Fraction(975, 1000) * (r - 1)))


def test_fast_bootstrap_equals_re_evaluation(pair):
    good, _, half, _, queries = pair
    kwargs = dict(replicates=15, seed=11, detector_floor_a=FLOOR, detector_floor_b=FLOOR, composition_a=(DET, REC), composition_b=(DET, REC), **bind(queries, good))
    assert ev._bootstrap_replicates(good, half, queries, **kwargs) == \
        ev._bootstrap_replicates(good, half, queries, slow=True, **kwargs)


def test_fast_bootstrap_on_multi_track_sites_equals_independent_evaluation():
    truths = ["KA01AB1234", "MH12CD5678"]
    a, b = [], []
    for site in range(6):
        for k, truth in enumerate(truths + truths[:1]):
            tid = f"s{site}t{k}"
            a.append(_track(tid, f"site{site}", truth, [truth if (site + k) % 3 else "KA01AB1235"]))
            b.append(_track(tid, f"site{site}", truth, [truth if (site + k) % 2 else ""]))
    queries = gen(truths)
    kwargs = dict(replicates=40, seed=5, detector_floor_a=FLOOR, detector_floor_b=FLOOR, composition_a=(DET, REC), composition_b=(DET, REC), **bind(queries, a))
    fast = ev._bootstrap_replicates(a, b, queries, **kwargs)
    assert fast == ev._bootstrap_replicates(a, b, queries, slow=True, **kwargs)
    # Independent re-run: rebuild each replicate's population and score it with evaluate_tracks itself.
    members: dict[str, list[int]] = {}
    for index, item in enumerate(a):
        members.setdefault(item.cluster, []).append(index)
    names = sorted(members)
    rng = random.Random(5)
    checked = 0
    for value in fast:
        picked = ev._draws(rng, members, names)
        if {a[i].truth for i in picked} != set(truths):
            continue  # this replicate lacks a truth, so the frozen query set does not bind to it
        rebuilt = lambda items: [dataclasses.replace(items[i], track_id=f"{items[i].track_id}#{n}")  # noqa: E731
                                 for n, i in enumerate(picked)]
        independent = score(rebuilt(a), queries).d_score - score(rebuilt(b), queries).d_score
        assert independent == value
        checked += 1
    assert checked >= 20


def test_bootstrap_refusals_and_no_silent_drops(pair):
    good, silent, half, _, queries = pair
    assert compare(good, silent, queries, calibration_minimum_clusters=100).outcome == "insufficient-clusters"
    assert compare(good, silent, queries, calibration_minimum_clusters=59).required_clusters == 60  # max(60, x)
    assert compare(good, silent, queries, calibration_minimum_clusters=71).outcome == "insufficient-clusters"
    with pytest.raises(ValueError, match="calibration_minimum_invalid"):
        compare(good, silent, queries, calibration_minimum_clusters=0)
    for replicates in (0, 1, 999, 2000):  # review P2-1: R is the frozen value, nothing else
        with pytest.raises(ValueError, match="frozen_value"):
            compare(good, silent, queries, replicates=replicates)
    with pytest.raises(ValueError, match="physical_capture_site"):
        compare(good, silent, queries, cluster_unit="sequence")
    for field, value in (("cluster", "other"), ("truth", "KA00AB9999")):
        changed = [dataclasses.replace(silent[0], **{field: value})] + silent[1:]
        with pytest.raises(ValueError, match="paired_population_mismatch"):
            compare(good, changed, queries)
        with pytest.raises(ValueError, match="paired_population_mismatch"):  # P3: the bootstrap checks pairing too
            ev._bootstrap_replicates(good, changed, queries, replicates=2, seed=1, detector_floor_a=FLOOR,
                                    detector_floor_b=FLOOR, composition_a=(DET, REC), composition_b=(DET, REC), **bind(queries, good))
    assert ev._bootstrap_replicates(good, silent, queries, replicates=50, seed=1, detector_floor_a=FLOOR,
                                   detector_floor_b=FLOOR, composition_a=(DET, REC), composition_b=(DET, REC), **bind(queries, good)).count(None) == 0  # silence never drops
    violating = [_track("t0", "site0", _plate_text(0), [_plate_text(0)], boxes=3)] + good[1:]
    assert compare(violating, silent, queries).outcome == "contract-fail"


def test_top_k_is_deterministic_and_excludes_failures():
    scores = [comp("PD2-S", True, 100, 0.9, 0.1, 0.8), comp("PD2-N", True, 100, 0.9, 0.1, 0.9),
              comp("PD5-V5M", False, 100, 0.99, 0.0, 0.99), comp("PD2-M", True, 10, 1, 0, 1),
              comp("PD5-V6S", True, 100, None, None, None),
              comp("PD9-X", True, 100, 1.0, 0.0, 1.0, contract_fail=True)]
    assert ev.top_k(scores, 3, 50, "detector", freeze=FREEZE) == ["PD2-N", "PD2-S", "PD5-V6S"]
    ocr = [comp("OC2-B", True, 60, 0.8, 0.1, 0.2, kind="recogniser"), comp("OC2-A", True, 60, 0.8, 0.1, None,
                                                                            kind="recogniser")]
    assert ev.top_k(ocr, 2, 50, "recogniser", freeze=FREEZE) == ["OC2-B", "OC2-A"]
    assert (ev.MPID, ev.ABSOLUTE_MINIMUM_CLUSTERS, ev.RANKING_OCR_CONFIDENCE_FLOOR) == (Fraction(4, 100), 60, 0.0)
    params = ev.ranking_parameters(FLOOR)
    assert (params.max_detections_per_crop, params.max_plates_per_crop, params.max_readings_per_plate,
            params.ocr_confidence_floor) == (2, 1, 3, 0.0)
    # Components are built from ranking-path results only.
    run = _track("z", "s", "KA01AB1234", ["KA01AB1234"]).run
    item = ev.detection_item_from_run("z", (((1, 1), (21, 1), (21, 11), (1, 11)),), run,
                                      run.record.crops[0].observation_id, detector_floor=FLOOR)
    built = ev.detector_component(True, detect_ranked([item]))
    assert (built.primary, built.support, built.contract_fail, built.kind) == (1.0, 1, False, "detector")
    reading = read([ev.ReadItem("p", "KA01AB1234", _plate(("KA01AB1234", 0.9)))])
    assert (ev.recogniser_component(True, reading).primary, ev.recogniser_component(True, reading).kind) == \
        (1.0, "recogniser")


# ---------------------------------------------------------------------------------------------- third cold review


def _composition_population(n, read, det, rec):
    return [_track(f"t{i}", f"site{i}", _plate_text(i), read(i), det=det, rec=rec) for i in range(n)]


def test_composition_identity_is_sealed_not_a_label():
    """Review P1-1 probes, on the real path (no fixture relabelling)."""
    pd1x = ident("PD1-X")
    good_oc5 = _composition_population(3, lambda i: [_plate_text(i)], pd1x, OC5)   # really PD1-X + OC5
    true_base = _composition_population(3, lambda i: [""], PD_BASE, OC5)         # really PD2-N + OC5
    ordinary = _composition_population(3, lambda i: [_plate_text(i)], DET, REC)  # really PD2-S + OC1-XS
    queries = _queries(good_oc5)
    s_oc5, s_base, s_ord = score(good_oc5, queries), score(true_base, queries), score(ordinary, queries)
    assert (s_oc5.detector, s_oc5.recogniser) == (pd1x, OC5)
    composition = ev.CompositionScore(s_oc5)
    assert (composition.detector_id, composition.recogniser_id) == ("PD1-X", "OC5-BEST")  # derived, not labelled
    baseline = ev.CompositionScore(s_base)
    # 1) a PDx+OC5 score cannot be relabelled as an ordinary composition and ranked
    with pytest.raises(ValueError, match="cannot_be_ranked"):
        ev.rankable_compositions([composition], baseline, RESOLUTION, FREEZE, LAYER_A)
    relabelled = dataclasses.replace(s_oc5, recogniser=ident("OC2-A"))
    with pytest.raises(ValueError, match="not_a_ranking_d_score"):
        ev.rankable_compositions([ev.CompositionScore(relabelled)], baseline, RESOLUTION, FREEZE, LAYER_A)
    # 2) an arbitrary score cannot stand in as the sealed baseline
    with pytest.raises(ValueError, match="sealed_pd_base"):
        gate(ev.CompositionScore(s_ord), ev.CompositionScore(s_ord))
    with pytest.raises(ValueError, match="sealed_pd_base"):
        gate(ev.CompositionScore(s_ord), composition)  # PD1-X + OC5 is not PD_BASE + OC5
    assert gate(ev.CompositionScore(s_ord), baseline) == ev.PASS  # the true baseline works
    assert ev.rankable_compositions([ev.CompositionScore(s_ord)], baseline, RESOLUTION, FREEZE, LAYER_A) != []
    # 3) the D score refuses runs from another composition than the one stated
    with pytest.raises(ValueError, match="identity_is_not_the_composition"):
        score(ordinary, queries, composition=(PD_BASE, REC))
    with pytest.raises(ValueError, match="identity_is_not_the_composition"):
        score(ordinary[:2] + good_oc5[2:], queries)
    # 4) the comparison refuses a benchmark-only composition by its sealed identity
    a = _composition_population(70, lambda i: [_plate_text(i)], pd1x, OC5)
    b = _composition_population(70, lambda i: [""], DET, REC)
    with pytest.raises(ValueError, match="cannot_be_ranked"):
        compare(a, b, _queries(a), composition_a=(pd1x, OC5), composition_b=(DET, REC))


def test_composition_hash_is_m3s():
    vector = "fb6fffc212d8de2f3c6d67af7ff5c7186c633fd28bf1936d1d4e393c1753d8d3"  # M3 baseline_seal @ f24dcf5e
    assert ev.m3_composition_sha256(*EVENTS[:2], OC5, EVENTS[2], PD_BASE) == vector
    assert RESOLUTION.composition_sha256 == vector


def test_components_take_their_id_from_the_sealed_result():
    run = _track("y", "s", "KA01AB1234", ["KA01AB1234"]).run
    detection = detect_ranked([ev.detection_item_from_run("y", (SQUARE,), run, run.record.crops[0].observation_id,
                                                          detector_floor=FLOOR)])
    built = ev.detector_component(True, detection)
    assert (built.candidate_id, built.identity_sha256) == (DET.candidate_id, DET.identity_sha256)
    with pytest.raises(TypeError):
        ev.detector_component("ANY", True, detection)  # type: ignore[call-arg]
    run = _track("x", "s", "KA01AB1234", ["KA01AB1234"], det=ident("PD5-V6S")).run
    item = ev.detection_item_from_run("x", (SQUARE,), run, run.record.crops[0].observation_id, detector_floor=FLOOR)
    with pytest.raises(ValueError, match="another_detector"):
        detect_ranked([item])


def test_one_replicate_cannot_declare_superiority(pair):
    good, silent, _, _, queries = pair
    with pytest.raises(ValueError, match="frozen_value"):
        compare(good, silent, queries, replicates=1)
    assert ev.BOOTSTRAP_REPLICATES == 1000 and compare(good, silent, queries).outcome == "superior"


def test_required_clusters_is_max_of_floor_and_calibration():
    assert [ev.required_clusters(v) for v in (1, 59, 60, 61, 140)] == [60, 60, 60, 61, 140]
    for bad in (0, -1, True, 60.0, None):
        with pytest.raises(ValueError, match="calibration_minimum_invalid"):
            ev.required_clusters(bad)


def test_bootstrap_refuses_contract_violating_runs(pair):
    good, _, _, _, queries = pair
    violating = [_track(f"t{i}", f"site{i}", _plate_text(i), [_plate_text(i)], boxes=3) for i in range(70)]
    assert score(violating, queries).outcome == ev.CONTRACT_FAIL
    with pytest.raises(ValueError, match="contract_violating_run"):
        ev._bootstrap_replicates(good, violating, queries, replicates=5, seed=1, detector_floor_a=FLOOR,
                                 detector_floor_b=FLOOR, composition_a=(DET, REC), composition_b=(DET, REC),
                                 **bind(queries, good))
    assert not hasattr(ev, "bootstrap_replicates")  # private: decisions go through paired_cluster_bootstrap
    assert compare(good, violating, queries).outcome == "contract-fail"


def test_detection_item_must_carry_its_crop_size():
    huge = ev.DetectionItem("c", (SQUARE,), ((10, 10, 100000, 10, 0.9),))
    with pytest.raises(ValueError, match="without_crop_size"):
        detect([huge])
    sized = dataclasses.replace(huge, crop_size=(64, 32))
    assert detect([sized]).outcome == ev.CONTRACT_FAIL


def test_n3_non_normalising_rank0_gives_no_support():
    items = [_track("t1", "s1", "KA01AB1234", ["KA01AB1235", "KA01AB1235", "KA01-AB/1234!"])]
    assert score(items).counts.consistent_wrong == 1  # owner rule: a bad rank-0 neither breaks nor supports


# ---------------------------------------------------------------------------------------------- fourth cold review


def _with_violation_at_zero(items, drop):
    run = ev.run_track(uuid.uuid5(uuid.NAMESPACE_URL, "t0"), _crops("t0", 1), _NaNScore(), Recogniser([_plate_text(0)]),
                       ev.ranking_parameters(FLOOR), detector_identity=DET, recogniser_identity=REC)
    assert "score_out_of_range" in run.contract_violation
    return [dataclasses.replace(items[0], run=ev.NO_RUN if drop else run)] + items[1:]


def test_population_digest_binds_compared_scores():
    """Review 4, P1-1 (probe1): dropping a violating run, or a subset of Tracks, cannot pass the gate or compare."""
    base_items = _composition_population(70, lambda i: [""], PD_BASE, OC5)
    queries = _queries(base_items)
    baseline = ev.CompositionScore(score(base_items, queries))
    candidate = _composition_population(70, lambda i: [_plate_text(i)], DET, REC)
    violating = score(_with_violation_at_zero(candidate, drop=False), queries)
    assert (violating.outcome, violating.d_score) == (ev.CONTRACT_FAIL, None)
    dropped = score(_with_violation_at_zero(candidate, drop=True), queries)
    assert dropped.outcome == ev.MEASURED and dropped.population_digest != baseline.score.population_digest
    with pytest.raises(ValueError, match="same_population"):
        gate(ev.CompositionScore(dropped), baseline)
    other_rec = ident("OC2-X")
    b = _composition_population(70, lambda i: [""], DET, other_rec)
    with pytest.raises(ValueError, match="no_evidence_track_must_be_no_run"):  # B ran t0: the population disagrees
        compare(_with_violation_at_zero(candidate, drop=True), b, queries, composition_b=(DET, other_rec))
    # subsetting: dropping the junk NO_GT_VEHICLE Tracks changes the digest, so the subset cannot be gated
    extra = [_track(f"ngv{i}", f"site{i}", ev.NO_GT_VEHICLE, [_plate_text(i)[:6] + "ZZ"]) for i in range(70)]
    base_extra = [_track(f"ngv{i}", f"site{i}", ev.NO_GT_VEHICLE, [""], det=PD_BASE, rec=OC5) for i in range(70)]
    baseline_full = ev.CompositionScore(score(base_items + base_extra, queries))
    full, subset = score(candidate + extra, queries), score(candidate, queries)
    assert full.d_score < subset.d_score and full.population_digest != subset.population_digest
    with pytest.raises(ValueError, match="same_population"):
        gate(ev.CompositionScore(subset), baseline_full)  # same labels, smaller population: refused
    assert gate(ev.CompositionScore(full), baseline_full) in (ev.PASS, ev.FAIL)  # the full population is gated
    # cluster relabelling is folded into the digest as well
    moved = [dataclasses.replace(i, cluster=f"site{k % 30}") for k, i in enumerate(candidate)]
    assert score(moved, queries).population_digest != subset.population_digest
    assert gate(ev.CompositionScore(subset), baseline) == ev.PASS  # same population: the gate works


def test_contract_fail_publishes_no_d_terms():
    items = [_track("t1", "s1", "KA01AB1234", ["KA01AB1234"]), _track("t2", "s2", "MH12AB0001", ["MH12AB0001"], boxes=3)]
    result = score(items)
    assert result.outcome == ev.CONTRACT_FAIL
    assert (result.exact_recall, result.contains_recall, result.contains_precision, result.d_score,
            result.consistent_wrong_rate, result.consistent_wrong_conditional_rate, result.conflicting_rate,
            result.no_text_rate) == (None,) * 8
    assert result.counts == ev.TrackCounts() and result.consistent_wrong_status == ev.FAIL


def test_top_k_refuses_oc5_by_identity_and_wrong_kinds():
    """Review 4, P2-2 and P3 (probe2), via the public API."""
    alias = ev.ComponentIdentity("OC9-ALIAS", OC5.identity_sha256)
    def component(who):
        items = [ev.ReadItem(f"p{i}", "KA01AB1234", ev.ranking_plate_record([Reading("KA01AB1234", 0.9)],
                                                                            recogniser=who)) for i in range(60)]
        return ev.recogniser_component(True, ev.evaluate_reading(items, recogniser=who))
    for who in (alias, OC5):
        with pytest.raises(ValueError, match="cannot_enter_top_k"):
            ev.top_k([component(who)], 3, 50, "recogniser", freeze=FREEZE)
    ordinary = component(REC)
    assert ev.top_k([ordinary], 3, 50, "recogniser", freeze=FREEZE) == ["OC1-XS"]
    with pytest.raises(ValueError, match="another_kind"):
        ev.top_k([ordinary], 3, 50, "detector", freeze=FREEZE)
    pd1 = ident("PD1-X")
    as_detector = ev.recogniser_component(True, ev.evaluate_reading(
        [ev.ReadItem(f"p{i}", "KA01AB1234", ev.ranking_plate_record([Reading("KA01AB1234", 0.9)], recogniser=pd1))
         for i in range(60)], recogniser=pd1))
    layer_a = [ev.LayerAResult(as_detector, as_detector.identity_sha256, True)] + \
        [x for x in _layer_a() if x.score.candidate_id != "PD1-X"]
    with pytest.raises(ev.BaselineStop, match="not_a_detector_result"):
        ev.resolve_baseline(FREEZE, layer_a, d_rows_read=0, resolved_at_utc=WHEN)


def test_hand_built_a_items_never_reach_the_ranking_path():
    fake = [ev.DetectionItem(f"c{i}", (((0, 0), (10, 0), (10, 5), (0, 5)),), ((0, 0, 10, 5, 0.99),), None, (64, 32))
            for i in range(100)]
    with pytest.raises(ValueError, match="not_from_ranking_path"):
        ev.evaluate_detection(fake, FLOOR, detector=ident("PD1-X"))
    diagnostic = ev.diagnostic_evaluate_detection(fake, FLOOR)
    assert diagnostic.recall == 1 and not ev._is_sealed(ev._A, diagnostic)
    with pytest.raises(ValueError, match="not_from_ranking_path"):
        ev.detector_component(True, diagnostic)
    run = _track("f", "s", "KA01AB1234", ["KA01AB1234"]).run
    with pytest.raises(ValueError, match="ranking_profile_or_floor"):
        ev.detection_item_from_run("f", (SQUARE,), run, run.record.crops[0].observation_id, detector_floor=0.5)
    seeded = dataclasses.replace(ev.ranking_parameters(FLOOR), fixture_seed="abc")
    assert not ev.is_ranking_profile(seeded, FLOOR)
    with pytest.raises(ValueError, match="ranking_profile"):
        score([_track("g", "s", "KA01AB1234", ["KA01AB1234"], parameters=seeded)])


def test_diagnostic_uplift_needs_the_same_population():
    ordinary = _composition_population(3, lambda i: [""], DET, REC)
    queries = _queries(ordinary)
    s = score(ordinary, queries)
    truths = ["ZZ01AB9999", "ZZ02AB9998", "ZZ03AB9997"]
    other = [dataclasses.replace(x, truth=t) for x, t in
             zip(_composition_population(3, lambda i: [_plate_text(i)], DET, OC5), truths)]
    q2 = gen(truths, OTHER_MANIFEST)
    o = ev.evaluate_tracks(other, q2, detector_floor=FLOOR, detector=DET, recogniser=OC5, **bind(q2, other, OTHER_MANIFEST))
    with pytest.raises(ValueError, match="same_population"):
        ev.diagnostic_ocr_uplift(ev.CompositionScore(s), ev.CompositionScore(o), FREEZE)


def test_bootstrap_seed_is_the_frozen_one():
    assert FREEZE.bootstrap_seed == 7
    with pytest.raises(TypeError):
        ev.paired_cluster_bootstrap([], [], None, seed=1)  # type: ignore[call-arg]  # no caller seed
    with pytest.raises(ValueError, match="bootstrap_seed_invalid"):
        ev.BaselineFreeze(FREEZE.eligible_detectors, "OC5-BEST", _h("o"), _h("g"), WHEN, *EVENTS, True)


# ---------------------------------------------------------------------------------------------- closed population (owner)


def test_population_digest_is_candidate_independent_and_run_states_are_explicit():
    candidate = _composition_population(70, lambda i: [_plate_text(i)], DET, REC)
    silent = _composition_population(70, lambda i: [""], DET, REC)
    queries = _queries(candidate)
    frozen = population_of(candidate)
    # 1. the same population with different candidate outputs (and outcomes) has the same digest
    failing = [_track("t0", "site0", _plate_text(0), [_plate_text(0)], boxes=3)] + candidate[1:]
    digests = {score(items, queries, population=frozen).population_digest for items in (candidate, silent, failing)}
    assert digests == {frozen.digest}
    assert score(failing, queries, population=frozen).outcome == ev.CONTRACT_FAIL
    # 2. dropping or adding a Track is refused against the frozen population
    with pytest.raises(ValueError, match="do_not_cover_the_closed_population"):
        score(candidate[1:], queries, population=frozen)
    with pytest.raises(ValueError, match="do_not_cover_the_closed_population"):
        score(candidate + [_track("x", "site0", _plate_text(0), [""])], queries, population=frozen)
    # 3. a contract-failed run cannot become NO_RUN (or vanish) to escape CONTRACT_FAIL
    with pytest.raises(ValueError, match="evidence_track_without_a_sealed_run"):
        score(_with_violation_at_zero(candidate, drop=True), queries, population=frozen)
    with pytest.raises(ValueError, match="evidence_track_without_a_sealed_run"):
        score([dataclasses.replace(candidate[0], run=None)] + candidate[1:], queries, population=frozen)
    # ... and a caller who rewrites the population to say "no evidence" gets a different digest
    rewritten = population_of(_with_violation_at_zero(candidate, drop=True))
    assert rewritten.digest != frozen.digest
    # 4. pairing mismatch (another truth or site) is refused
    with pytest.raises(ValueError, match="paired_population_mismatch"):
        compare(candidate, [dataclasses.replace(silent[0], cluster="elsewhere")] + silent[1:], queries)
    with pytest.raises(ValueError, match="does_not_match_the_population"):
        score([dataclasses.replace(candidate[0], cluster="elsewhere")] + candidate[1:], queries, population=frozen)
    # 5. cluster relabelling changes the digest
    moved = [dataclasses.replace(i, cluster=f"site{k % 30}") for k, i in enumerate(candidate)]
    assert population_of(moved).digest != frozen.digest
    # a hand-made population object is refused
    with pytest.raises(ValueError, match="not_from_closed_population"):
        score(candidate, queries, population=dataclasses.replace(frozen, digest="0" * 64))
