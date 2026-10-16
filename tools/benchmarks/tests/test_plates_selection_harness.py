"""A–D evaluators and the query generator, through the verified bundle → execution envelope → harness record boundary.

Synthetic fixtures only (no dataset, no model). Each corpus is a set of canonical documents named by a freeze record
committed in a temporary Git repository (``plate_selection_fixtures``). The real committed record and corpus are an
integration prerequisite before the PR-2 freeze. Trust-boundary attacks are in ``test_plates_selection_boundary``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import math
import random
import uuid
from fractions import Fraction

import pytest

from mavi_vision.plates import pipeline
from mavi_vision.plates.inference import PlateBox, VerifiedCrop
from mavi_vision.plates.pipeline import PlateRecord, RankedReading
from tools.benchmarks.capabilities.plates import evaluator as ev
from tools.benchmarks.capabilities.plates import queries as q
from tools.benchmarks.tests import plate_selection_fixtures as fx
from tools.benchmarks.tests.plate_selection_fixtures import (
    DET,
    EVENTS,
    FLOOR,
    GOOD_BOX,
    NO_GT_VEHICLE,
    NO_PLATE,
    OC5,
    PARAMS,
    PD_BASE,
    REC,
    UNREADABLE,
    WHEN,
    C,
    Detector,
    Outputs,
    R,
    Recogniser,
    T,
    _h,
    _plate_text,
    build,
    comp,
    compare,
    crop,
    default_roster,
    gate,
    ident,
    images,
    layer_a_for,
    oid,
    outputs_of,
    plate,
    population,
    run,
    runs_for,
    score,
    stored,
    tuuid,
    with_d,
)

MANIFEST = hashlib.sha256(b"synthetic-population-manifest").hexdigest()
OTHER_MANIFEST = hashlib.sha256(b"another-population").hexdigest()


def gen(truths, manifest=MANIFEST):
    return q.generate(truths, PARAMS, manifest)


def TOPK(corpus, scores, kind):  # noqa: N802
    return ev.top_k(corpus.sel, scores, kind)



@pytest.fixture(autouse=True)
def _each_test_is_a_fresh_scoring_process():
    """Every test starts with no protected truth marked read in this process (see ``plate_selection_fixtures``)."""
    fx.new_process()
    yield
    fx.new_process()

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
    assert first.skipped["suffix"] == 3
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
    assert len([x for x in result.queries if x.text == "1234"]) == 2


def test_query_lengths_are_not_parameters():
    with pytest.raises(TypeError):
        q.QueryParameters(prefix_length=4, interior_offset=1, negatives_per_plate=1, seed="s")  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        q.QueryParameters(0, 1, "s")


def test_d_queries_come_from_the_bundle_and_its_frozen_record():
    corpus = build([T("a", "s1", "KA01AB1234"), T("b", "s2", NO_PLATE)])
    queries = ev.queries_for(corpus.full)
    assert queries.truths == ("KA01AB1234",) and queries.population_manifest_sha256 == corpus.d_digest
    assert queries.query_set_sha256 == gen(["KA01AB1234"], corpus.d_digest).query_set_sha256
    with pytest.raises(ValueError, match="requires_the_protected_d_bundle"):
        ev.queries_for(corpus.sel)  # the selection stage never reads the D truth


# ---------------------------------------------------------------------------------------------- execution envelopes


def test_runs_are_bound_to_their_track_evidence_and_identity():
    corpus = build([T("t0", "s0", "KA01AB1234", n=2), T("t1", "s1", "MH12AB0001"), T("t2", "s2", NO_PLATE, n=0)])
    r0 = run(corpus, "t0", ["KA01AB1234", "KA01AB1234"])
    assert (r0.state, r0.track_id, r0.mavi_track_uuid, r0.evidence) == (ev.COMPLETED, "t0", tuuid("t0"),
                                                                          corpus.evidence("t0"))
    assert (r0.partition_digest, r0.detector, r0.recogniser) == (corpus.d_digest, DET, REC)
    assert ev.is_ranking_profile(r0.parameters, FLOOR)
    with pytest.raises(ValueError, match="no_mavi_evidence"):  # NO_RUN is derived, never executed or supplied
        run(corpus, "t2", [])
    with pytest.raises(ValueError, match="not_in_bundle"):
        run(corpus, "t9", [], bundle=corpus.capture)
    with pytest.raises(ValueError, match="run_detector_not_in_the_frozen_roster"):
        run(corpus, "t1", ["x"], det=ident("PD7-NEW"))
    with pytest.raises(ValueError, match="image_integrity_failed"):
        ev.run_track(corpus.capture, "t1", detector=GOOD_BOX, recogniser=Recogniser(["x"]), detector_identity=DET,
                     recogniser_identity=REC, images=lambda o, s: images(o, s) + b"x")
    with pytest.raises(ValueError, match="run_track_not_in_bundle"):   # the selection stage never opens the D index
        run(corpus, "t1", ["x"], bundle=corpus.sel)
    with pytest.raises(ValueError, match="candidate_execution_on_the_protected_d_bundle"):
        run(corpus, "t1", ["x"], bundle=corpus.full)


def test_candidate_silence_is_a_completed_run_not_no_run():
    corpus = population(3)
    silent = runs_for(corpus, outputs_of(3, lambda i: [""]))
    assert {r.state for r in silent} == {ev.COMPLETED}
    result = score(corpus, silent)
    assert (result.outcome, result.d_status) == (ev.MEASURED, ev.MEASURED)
    assert (result.exact_recall, result.contains_recall, result.contains_precision, result.d_score) == (0, 0, 0, 0)


# ---------------------------------------------------------------------------------------------- generic attacks (D)


def test_population_completeness_and_substitution_attacks():
    corpus = population(4)
    runs = runs_for(corpus, outputs_of(4, lambda i: [_plate_text(i)]))
    assert score(corpus, runs).d_score == 1
    hand_built = ev.TrackRun(*[getattr(runs[0], f.name) for f in dataclasses.fields(ev.TrackRun)][:-1])
    attacks = {
        "omission": (runs[1:], "do_not_equal_the_bundle_items"),
        "duplication": (runs + [runs[0]], "duplicate_result"),
        "cross_track_reuse": ([runs[1]] + runs[1:], "duplicate_result"),
        "caller_built": ([hand_built] + runs[1:], "not_from_the_harness"),
    }
    for name, (attack, code) in attacks.items():
        with pytest.raises(ValueError, match=code):
            score(corpus, attack)
    # Edits to a returned copy are inert: the harness scores its own record (relabelling or reducing evidence on the
    # copy changes nothing).
    edited = [dataclasses.replace(runs[0], track_id="t9", evidence=())] + runs[1:]
    assert score(corpus, edited).d_score == 1


def test_contract_fail_cannot_be_escaped():
    """Review 5, P1-A/P1-B through the boundary: a failed run stays CONTRACT_FAIL; omission is never NO_RUN."""

    class Flaky:
        def detect(self, crop, verified):
            if verified.evidence_rank == 1:
                return [PlateBox(1, 1, 20, 10, float("nan"))]
            return [PlateBox(1, 1, 20, 10, 0.9)]

    corpus = build([T("t0", "s0", _plate_text(0), n=2)] + [T(f"t{i}", f"site{i}", _plate_text(i)) for i in range(1, 5)])
    failed = run(corpus, "t0", [_plate_text(0)] * 2, detector=Flaky())
    others = [run(corpus, f"t{i}", [_plate_text(i)]) for i in range(1, 5)]
    assert failed.state == ev.CONTRACT_FAIL and "score_out_of_range" in failed.contract_violation
    assert score(corpus, [failed] + others).outcome == ev.CONTRACT_FAIL
    with pytest.raises(ValueError, match="do_not_equal_the_bundle_items"):
        score(corpus, others)  # omission (or "NO_RUN") is not available
    healed = dataclasses.replace(failed, state=ev.COMPLETED, contract_violation=None)
    assert score(corpus, [healed] + others).outcome == ev.CONTRACT_FAIL  # an edited copy is inert


def test_alias_identity_and_composition_checks():
    corpus = population(3)
    runs = runs_for(corpus, outputs_of(3, lambda i: [_plate_text(i)]))
    with pytest.raises(ValueError, match="identity_is_not_the_composition"):
        score(corpus, runs, composition=(PD_BASE, REC))
    mixed = runs[:2] + [run(corpus, "t2", [_plate_text(2)], det=PD_BASE)]
    with pytest.raises(ValueError, match="identity_is_not_the_composition"):
        score(corpus, mixed)


# ---------------------------------------------------------------------------------------------- A


SQUARE = ((10, 10), (30, 10), (30, 20), (10, 20))


def _crop_corpus(polygons_by_crop):
    tracks = [T(f"t{i}", f"s{i}", _plate_text(i)) for i in range(len(polygons_by_crop))]
    crops = [crop(f"c{i}", f"t{i}", 0, polys) for i, polys in enumerate(polygons_by_crop)]
    return build(tracks, crops=crops)


def detect_runs(corpus, detector, det=DET):
    return [ev.run_detection(corpus.sel, c["cropId"], detector=detector, detector_identity=det, images=images)
            for c in corpus.docs["abTruth"]["crops"]]


def test_detection_metrics_and_floor():
    corpus = _crop_corpus([(SQUARE,), (((0, 0), (10, 0), (10, 10), (0, 10)),)])
    detectors = [Detector([PlateBox(10, 10, 20, 10, 0.9), PlateBox(40, 20, 5, 5, 0.8)]),
                 Detector([PlateBox(0, 0, 10, 10, 0.1)])]
    runs = [ev.run_detection(corpus.sel, c["cropId"], detector=d, detector_identity=DET, images=images)
            for c, d in zip(corpus.docs["abTruth"]["crops"], detectors)]
    result = ev.evaluate_a(corpus.sel, runs, detector=DET)
    assert (result.outcome, result.plates, result.covered, result.recall) == (ev.MEASURED, 2, 1, Fraction(1, 2))
    assert result.below_floor_proposals == 1 and result.false_plates_per_crop == Fraction(1, 2)
    assert result.layer_digest == ev.layer_digest(corpus.sel, "A")


@pytest.mark.parametrize("box, code", [
    (PlateBox(10, 10, 20, 10, float("nan")), "score_out_of_range"),  # was "below floor" before review 5
    (PlateBox(10, 10, 20, 10, 1.5), "score_out_of_range"),
    (PlateBox(10.5, 10, 20, 10, 0.9), "box_not_integer"),
    (PlateBox(10, 10, 0, 10, 0.9), "box_degenerate"),
    (PlateBox(50, 10, 20, 10, 0.9), "box_outside_crop"),
    (PlateBox(10, 10, 100000, 10, 0.9), "box_outside_crop"),
    ((10, 10, 20, 10, 0.9), "not_a_platebox"),
])
def test_any_malformed_proposal_is_a_contract_fail_in_a(box, code):
    corpus = _crop_corpus([(SQUARE,)])
    result = ev.evaluate_a(corpus.sel, detect_runs(corpus, Detector([box])), detector=DET)
    assert result.outcome == ev.CONTRACT_FAIL and code in result.contract_violations[0]


def test_five_junk_proposals_are_a_contract_fail_not_a_good_score():
    corpus = _crop_corpus([(SQUARE,)])
    junk = Detector([PlateBox(x, 0, 10, 10, 0.9) for x in range(0, 50, 10)])
    result = ev.evaluate_a(corpus.sel, detect_runs(corpus, junk), detector=DET)
    assert result.outcome == ev.CONTRACT_FAIL and "exceeds_bound@count=5" in result.contract_violations[0]


def test_a_coverage_is_exact_at_the_threshold():
    wide, short = ((0, 0), (100, 0), (100, 1), (0, 1)), ((0, 0), (20, 0), (20, 1), (0, 1))
    assert ev.coverage(wide, (0, 0, 95, 1)) == Fraction(95, 100)
    assert ev.coverage(short, (0, 0, 19, 1)) == Fraction(19, 20)
    corpus = _crop_corpus([(short,)])
    exact = ev.evaluate_a(corpus.sel, detect_runs(corpus, Detector([PlateBox(0, 0, 19, 1, 0.9)])), detector=DET)
    below = ev.evaluate_a(corpus.sel, detect_runs(corpus, Detector([PlateBox(0, 0, 18, 1, 0.9)])), detector=DET)
    assert (exact.covered, below.covered) == (1, 0)


def test_a_population_attacks():
    corpus = _crop_corpus([(SQUARE,), (SQUARE,)])
    good = detect_runs(corpus, GOOD_BOX)
    bad = ev.run_detection(corpus.sel, "c0", detector=Detector([PlateBox(1, 1, 20, 10, float("nan"))]),
                           detector_identity=DET, images=images)
    assert ev.evaluate_a(corpus.sel, [bad, good[1]], detector=DET).outcome == ev.CONTRACT_FAIL
    for attack, code in (([good[1]], "do_not_equal_the_bundle_items"), (good + [good[0]], "duplicate_result"),
                         ([good[1], good[1]], "duplicate_result")):
        with pytest.raises(ValueError, match=code):
            ev.evaluate_a(corpus.sel, attack, detector=DET)
    edited = [dataclasses.replace(good[0], proposals=())] + good[1:]
    assert ev.evaluate_a(corpus.sel, edited, detector=DET).covered == ev.evaluate_a(corpus.sel, good,
                                                                                  detector=DET).covered
    with pytest.raises(ValueError, match="another_detector"):
        ev.evaluate_a(corpus.sel, detect_runs(corpus, GOOD_BOX, det=PD_BASE), detector=DET)


# ---------------------------------------------------------------------------------------------- B / C


def _plate_corpus(texts, *, b=True, c=False):
    tracks = [T(f"t{i}", f"s{i}", text) for i, text in enumerate(texts)]
    plates = [plate(f"p{i}", f"t{i}", b=i if b else None, c=0 if c else None) for i in range(len(texts))]
    return build(tracks, plates=plates)


def read_runs(corpus, outputs, rec=REC):
    """``outputs`` maps plate id → the recogniser's reading list."""
    return [ev.run_reading(corpus.sel, pid, recogniser=Outputs([outputs[pid]]), recogniser_identity=rec,
                           images=images) for pid in sorted(outputs)]


def test_reading_rules_follow_pr3_and_any_violation_fails():
    corpus = _plate_corpus(["KA01AB1234"])
    assert ev.evaluate_b(corpus.sel, read_runs(corpus, {"p0": R(("KA01AB1234", 0.01))}), recogniser=REC).em == 1
    for readings, code in ((R(("X", 0.5), ("X", 0.5)), "non_strict_rank_order"), (R(("", 0.5)), "invalid_raw_text"),
                           (R(("KA01", 1.5)), "confidence_out_of_range"),
                           (R(("KA01", float("nan"))), "confidence_out_of_range"),
                           ([("KA01", 0.5)], "not_a_reading"),
                           (R(("A", 0.1), ("B", 0.2), ("C", 0.3), ("D", 0.4)), "exceeds_bound")):
        result = ev.evaluate_b(corpus.sel, read_runs(corpus, {"p0": readings}), recogniser=REC)
        assert result.outcome == ev.CONTRACT_FAIL and code in result.contract_violations[0] and result.em is None
    assert ev.diagnostic_plate_record(R(("KA01", 0.2)), 0.5).outcome == "unreadable"
    with pytest.raises(ValueError, match="not_declared"):
        ev.diagnostic_plate_record(R(("KA01", 0.2)), 0.0)


def test_public_ranking_equals_pr3_internal_ranking():
    parameters = ev.ranking_parameters(FLOOR)
    for readings in (R(("KA01", 0.5)), R(("B", 0.2), ("A", 0.2), ("C", 0.9)), R(("KA\n01", 0.3), ("KA01", 0.3)), []):
        assert ev._rank_plate(readings, parameters) == pipeline._plate(0, readings, parameters)
    plate_record = ev._rank_plate(R(("KA01", 0.5)), parameters)
    assert isinstance(plate_record, PlateRecord) and isinstance(plate_record.readings[0], RankedReading)


def test_reading_metrics_and_input_order_invariance():
    corpus = _plate_corpus(["KA01AB1234", "KA01AB1234", "KA01AB1234", "a@b", "MH12AB0001"])
    outputs = {"p0": R(("ka01 ab1234", 0.9)), "p1": R(("KA01AB1284", 0.8), ("KA01AB1234", 0.7)), "p2": [],
               "p3": [], "p4": R(("MH12AB0001", 0.8))}
    runs = read_runs(corpus, outputs)
    result = ev.evaluate_b(corpus.sel, runs, recogniser=REC)
    assert (result.plates, result.exact, result.unsupported_truths) == (4, 2, 1)
    assert result.em == Fraction(1, 2) and result.top_k_hit == Fraction(3, 4)
    for seed in range(5):
        shuffled = list(runs)
        random.Random(seed).shuffle(shuffled)
        again = ev.evaluate_b(corpus.sel, shuffled, recogniser=REC)
        assert (again.ece, again.risk_coverage, again.em) == (result.ece, result.risk_coverage, result.em)
    with pytest.raises(ValueError, match="not_comparable"):  # review 6, P3-3: needs a C and B pair
        ev.c_minus_b(result, result)


def test_unsupported_text_predictions_are_wrong_in_ece_and_risk_coverage():
    """Owner (2026-10-14): an UNSUPPORTED_TEXT plate is out of the EM/CER/top-k-hit denominators only; a prediction
    against it has correctness 0 in ECE and risk–coverage, whose coverage denominator is every plate."""
    plain = _plate_corpus(["KA01AB1234"])
    mixed = _plate_corpus(["KA01AB1234", "UNKNOWN"])
    a = ev.evaluate_b(plain.sel, read_runs(plain, {"p0": R(("KA01AB1234", 0.9))}), recogniser=REC)
    b = ev.evaluate_b(mixed.sel, read_runs(mixed, {"p0": R(("KA01AB1234", 0.9)), "p1": R(("UNKNOWN", 0.95))}),
                      recogniser=REC)
    assert (b.plates, b.em, b.unsupported_truths) == (1, 1, 1) and a.em == 1
    assert b.risk_coverage == ((0.5, 1.0), (1.0, 0.5))  # the unsupported prediction is wrong and still counted
    assert a.ece == pytest.approx(0.1) and b.ece == pytest.approx(0.5 * 0.95 + 0.5 * 0.1)


def test_b_population_attacks():
    corpus = _plate_corpus(["KA01AB1234", "MH12AB0001"])
    runs = read_runs(corpus, {"p0": R(("KA01", 2.0)), "p1": R(("MH12AB0001", 0.9))})
    assert ev.evaluate_b(corpus.sel, runs, recogniser=REC).outcome == ev.CONTRACT_FAIL
    for attack, code in (([runs[1]], "do_not_equal_the_bundle_items"), (runs + [runs[0]], "duplicate_result")):
        with pytest.raises(ValueError, match=code):
            ev.evaluate_b(corpus.sel, attack, recogniser=REC)
    healed = [dataclasses.replace(runs[0], plate=None, contract_violation=None, state=ev.COMPLETED), runs[1]]
    assert ev.evaluate_b(corpus.sel, healed, recogniser=REC).outcome == ev.CONTRACT_FAIL  # an edited copy is inert
    honest_silence = read_runs(corpus, {"p0": [], "p1": R(("MH12AB0001", 0.9))})
    assert ev.evaluate_b(corpus.sel, honest_silence, recogniser=REC).outcome == ev.MEASURED
    with pytest.raises(ValueError, match="another_recogniser"):
        ev.evaluate_b(corpus.sel, read_runs(corpus, {"p0": [], "p1": []}, rec=OC5), recogniser=REC)
    for name in ("not_read", "ReadItem", "DetectionItem", "TrackItem", "EvaluationManifest", "ProtocolConfig",
                 "verify_manifest", "Truth", "PartitionPlan"):
        assert not hasattr(ev, name)  # no caller-assembled corpus, item or configuration can reach a metric


def test_ece_uses_equal_mass_bins():
    rows = [(0.9 - i * 0.01, i % 2 == 0, f"q{i:02d}") for i in range(11)]
    bins = {}
    for k in range(11):
        bins.setdefault(k * ev.ECE_BINS // 11, []).append(k)
    assert len(bins) == 10 and {len(v) for v in bins.values()} == {1, 2}
    expected = sum(len(v) / 11 * abs(sum(rows[k][0] for k in v) / len(v) - sum(rows[k][1] for k in v) / len(v))
                   for v in bins.values())
    assert ev._ece(rows) == pytest.approx(expected, abs=0)


def test_c_comes_only_from_the_composition_runs():
    corpus = _plate_corpus(["KA01AB1234", "MH12AB0001"], b=False, c=True)
    good = runs_for(corpus, {"t0": ["KA01AB1234"], "t1": ["MH12AB0001"]})
    result = ev.evaluate_c(corpus.sel, good, composition=(DET, REC))
    assert (result.layer, result.em, result.recogniser) == ("C", 1, REC)
    silent_t1 = [good[0], run(corpus, "t1", [""])]
    assert ev.evaluate_c(corpus.sel, silent_t1, composition=(DET, REC)).em == Fraction(1, 2)
    failed = [good[0], run(corpus, "t1", ["MH12AB0001"], n_boxes=3)]
    assert ev.evaluate_c(corpus.sel, failed, composition=(DET, REC)).outcome == ev.CONTRACT_FAIL
    with pytest.raises(ValueError, match="do_not_equal_the_bundle_items"):
        ev.evaluate_c(corpus.sel, good[:1], composition=(DET, REC))
    with pytest.raises(ValueError, match="component_read_result_not_layer_b"):
        ev.recogniser_component(result)


# ---------------------------------------------------------------------------------------------- D


def test_d_score_on_a_closed_population_exactly():
    corpus = build([T("t1", "s1", "KA01AB1234"), T("t2", "s1", "MH12CD5678", n=2), T("t3", "s2", NO_PLATE),
                    T("t5", "s2", NO_GT_VEHICLE), T("t4", "s2", "DL3CAB0001", n=0)])
    runs = runs_for(corpus, {"t1": ["KA01AB1234"], "t2": ["MH12CD5670", "MH12CD5670"], "t3": ["KA01ZZ9999"],
                             "t5": ["DL3CAB0002"]})
    queries = ev.queries_for(corpus.full)
    result = score(corpus, runs)
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
    assert (result.partition_digest, result.query_set_sha256) == (corpus.d_digest, queries.query_set_sha256)


def test_unsupported_truth_stays_and_cannot_improve_precision():
    plain = build([T("p", "s1", "KA01AB1234")])
    both = build([T("p", "s1", "KA01AB1234"), T("u", "s2", "KA01AB12३४")])
    without = score(plain, runs_for(plain, {"p": ["KA01AB1234"]}))
    with_unsupported = score(both, runs_for(both, {"p": ["KA01AB1234"], "u": ["KA01AB1234"]}))
    assert with_unsupported.accounting["unsupported"] == 1
    assert with_unsupported.counts.exact_denominator == without.counts.exact_denominator
    assert with_unsupported.counts.positive_pairs == without.counts.positive_pairs
    assert with_unsupported.counts.returned_pairs > without.counts.returned_pairs
    assert with_unsupported.counts.correct_returned == without.counts.correct_returned
    assert with_unsupported.contains_precision < without.contains_precision


def test_unreadable_is_accounted_not_silent():
    corpus = build([T("p", "s1", "KA01AB1234"), T("r", "s1", UNREADABLE)])
    result = score(corpus, runs_for(corpus, {"p": ["KA01AB1234"], "r": ["KA01AB1234"]}))
    assert result.accounting["unreadable"] == 1 and result.counts.unreadable_returned_pairs > 0
    assert result.contains_precision == 1


def test_contract_violation_fails_the_whole_composition_and_publishes_no_terms():
    corpus = build([T("t1", "s1", "KA01AB1234"), T("t2", "s2", "MH12AB0001")])
    runs = [run(corpus, "t1", ["KA01AB1234"]), run(corpus, "t2", ["MH12AB0001"], n_boxes=3)]
    result = score(corpus, runs)
    assert (result.outcome, result.d_status, result.d_score) == (ev.CONTRACT_FAIL, ev.CONTRACT_FAIL, None)
    assert result.contract_violations[0].startswith("plate_detector_output_exceeds_bound@count=3:obs=")
    assert result.contract_violations[0].endswith(":t2")
    assert (result.exact_recall, result.contains_recall, result.contains_precision, result.consistent_wrong_rate,
            result.consistent_wrong_conditional_rate, result.conflicting_rate, result.no_text_rate) == (None,) * 7
    assert result.counts == ev.TrackCounts() and result.consistent_wrong_status == ev.FAIL
    base = score(corpus, runs_for(corpus, {"t1": ["KA01AB1234"], "t2": ["MH12AB0001"]}))
    assert gate(corpus, C("PD2-S", "OC1-XS", result), C("PD2-N", "OC5-BEST", base)) == ev.FAIL
    with pytest.raises(ev.BaselineStop, match="baseline_contract_violation"):
        gate(corpus, C("PD2-S", "OC1-XS", base), C("PD2-N", "OC5-BEST", result))


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


def _fresh(recogniser):
    """The parametrised recogniser fixtures are consumed by one run; rebuild an equivalent one."""
    if isinstance(recogniser, Outputs):
        return Outputs(list(recogniser.initial))
    if isinstance(recogniser, Recogniser):
        return Recogniser(list(recogniser.initial))
    return recogniser


@pytest.mark.parametrize("detector, recogniser, code", [
    (_OutOfBounds(), Recogniser(["KA01AB1234"]), "box_outside_crop"),
    (_NaNScore(), Recogniser(["KA01AB1234"]), "score_out_of_range"),
    (_NotABox(), Recogniser(["KA01AB1234"]), "not_a_platebox"),
    (_FloatBox(), Recogniser(["KA01AB1234"]), "box_not_integer"),
    (_Crash(), Recogniser([]), "plate_detector_runtime_error"),
    (GOOD_BOX, Outputs([R(("KA01", 1.5))]), "confidence_out_of_range"),
    (GOOD_BOX, Outputs([R(("", 0.5))]), "invalid_raw_text"),
    (GOOD_BOX, Outputs([R(("KA01", 0.5), ("KA01", 0.5))]), "non_strict_rank_order"),
    (GOOD_BOX, Outputs([["KA01"]]), "not_a_reading"),
    (GOOD_BOX, _CrashOcr(), "plate_recogniser_runtime_error"),
])
def test_any_output_contract_violation_is_a_hard_fail_in_d_and_c(detector, recogniser, code):
    corpus = _plate_corpus(["KA01AB1234"], b=False, c=True)
    result = run(corpus, "t0", detector=detector, recogniser=recogniser)
    assert result.state == ev.CONTRACT_FAIL and result.record is None and code in result.contract_violation
    assert f"obs={oid('t0', 0)}" in result.contract_violation
    assert ev.evaluate_c(corpus.sel, [result], composition=(DET, REC)).outcome == ev.CONTRACT_FAIL
    d_corpus = build([T("t0", "s0", "KA01AB1234")])
    d = score(d_corpus, [run(d_corpus, "t0", detector=detector, recogniser=_fresh(recogniser))])
    assert (d.outcome, d.d_score) == (ev.CONTRACT_FAIL, None)


def test_product_abstains_where_the_bake_off_fails():
    corpus = build([T("p", "s", "KA01AB1234")])
    ref = corpus.evidence("p")[0]
    content = images(ref.observation_id, ref.sha256)
    observation = ev.lease_observation(uuid.UUID(ref.observation_id), "near-view", 0, len(content), ref.sha256)
    verified = VerifiedCrop(ref.observation_id, "near-view", 0, ref.sha256, content)
    duplicate = R(("KA01", 0.5), ("KA01", 0.5))
    product = pipeline.analyse_crop(observation, verified, GOOD_BOX, Outputs([duplicate]), ev.ranking_parameters(FLOOR))
    assert (product.status, product.reason) == ("abstained", "ocr_output_invalid")
    assert "non_strict_rank_order" in run(corpus, "p", recogniser=Outputs([duplicate])).contract_violation


def test_diagnostic_floor_is_a_separate_type():
    corpus = population(1)
    runs = runs_for(corpus, outputs_of(1, lambda i: [_plate_text(i)]))
    diagnostic = ev.diagnostic_evaluate_d_at_floor(corpus.full, runs, 0.5, composition=(DET, REC))
    assert isinstance(diagnostic, ev.DiagnosticTrackScore) and diagnostic.values.accounting["diagnosticFloor"] == 0.5
    with pytest.raises(ValueError, match="not_declared"):
        ev.diagnostic_evaluate_d_at_floor(corpus.full, runs, 0.0, composition=(DET, REC))


def test_gates_and_decisions_refuse_diagnostic_and_unrecorded_scores():
    corpus = population(3)
    ranked = runs_for(corpus, outputs_of(3, lambda i: [_plate_text(i)]))
    silent = score(corpus, runs_for(corpus, outputs_of(3, lambda i: [""])))
    diag = ev.diagnostic_evaluate_d_at_floor(corpus.full, ranked, 0.7, composition=(DET, REC))
    for forged in (diag, diag.values, dataclasses.replace(silent, result_id="0" * 32)):
        with pytest.raises(ValueError, match="not_a_ranking_d_score"):
            gate(corpus, C("PD2-S", "OC1", silent), C("PD2-N", "OC5-BEST", forged))
        with pytest.raises(ValueError, match="not_a_ranking_d_score"):
            gate(corpus, C("PD2-S", "OC1", forged), C("PD2-N", "OC5-BEST", silent))
        with pytest.raises(ValueError, match="not_a_ranking_d_score"):
            ev.diagnostic_ocr_uplift(corpus.full, C("PD2-S", "OC1", forged), C("PD2-S", "OC5-BEST", silent))
    raised = dataclasses.replace(silent, d_score=Fraction(1))  # an edited copy is the harness record again
    assert stored(ev._D, raised).d_score == 0
    with pytest.raises(ValueError, match="not_from_the_harness"):
        ev.top_k(corpus.sel, [ev.ComponentScore("OC2-A", 100, 0.9, 0.1, 0.1, False, _h("OC2-A"), "recogniser",
                                                corpus.ab_digest, _h("m"))], "recogniser")


def test_silent_baseline_and_corpus_deficiency():
    corpus = population(3)
    silent = score(corpus, runs_for(corpus, outputs_of(3, lambda i: [""])))
    good = score(corpus, runs_for(corpus, outputs_of(3, lambda i: [_plate_text(i)])))
    assert gate(corpus, C("PD2-N", "OC1-XS", good), C("PD2-N", "OC5-BEST", silent)) == ev.PASS
    deficient_corpus = build([T("n", "s1", NO_PLATE)])
    deficient = score(deficient_corpus, runs_for(deficient_corpus, {"n": ["KA01AB1234"]}))
    assert deficient.d_status == ev.INSUFFICIENT and deficient.d_score is None
    bound = with_d(deficient, None, partition_digest=corpus.d_digest, query_set_sha256=silent.query_set_sha256)
    assert gate(corpus, C("PD2-N", "OC1-XS", bound), C("PD2-N", "OC5-BEST", silent)) == ev.INSUFFICIENT
    with pytest.raises(ev.BaselineStop, match="baseline_not_evaluable"):
        gate(corpus, C("PD2-N", "OC1-XS", good), C("PD2-N", "OC5-BEST", with_d(good, None)))
    with pytest.raises(ValueError, match="same_population_and_query_set"):
        gate(corpus, C("PD2-N", "OC1-XS", deficient), C("PD2-N", "OC5-BEST", silent))


def test_mpid_boundary_is_exact_and_pinned():
    corpus = population(1)
    base = score(corpus, runs_for(corpus, outputs_of(1, lambda i: [_plate_text(i)])))

    def check(high, low, detector="PD2-S"):
        return gate(corpus, C(detector, "OC1-XS", with_d(base, high)), C("PD2-N", "OC5-BEST", with_d(base, low)))

    assert 0.47 - 0.43 < 0.04
    assert check(Fraction(47, 100), Fraction(43, 100)) == ev.PASS
    assert check(Fraction(4, 100), Fraction(0)) == ev.PASS
    assert check(Fraction(399, 10000), Fraction(0)) == ev.FAIL
    assert check(Fraction(1, 3) + Fraction(4, 100), Fraction(1, 3)) == ev.PASS
    assert check(Fraction(4, 100), Fraction(0), detector="PD1-X") == ev.PASS
    with pytest.raises(TypeError):  # MPID is a frozen constant, not a parameter
        ev.baseline_gate(corpus.full, C("PD2-S", "OC1-XS", base), C("PD2-N", "OC5-BEST", base), corpus.resolution,
                         corpus.layer_a, mpid=Fraction(3, 100))
    with pytest.raises(ValueError, match="sealed_pd_base"):
        gate(corpus, C("PD2-S", "OC1-XS", base), C("PD2-S", "OC5-BEST", base))
    with pytest.raises(ValueError, match="sealed_pd_base"):
        gate(corpus, C("PD2-S", "OC1-XS", base), C("PD2-N", "OC2-V6S", base))


# ---------------------------------------------------------------------------------------------- baseline resolution


def _selection_only(**kw):
    """A corpus whose D truth is never loaded (fresh record), so Stage 2 can be resolved repeatedly."""
    return build([T("t0", "stage2-only-site", _plate_text(0))], resolve=False, **kw)


def test_pd_base_resolves_mechanically_from_the_frozen_rule():
    corpus = _selection_only(protocol=None)
    sel, layer_a = corpus.sel, layer_a_for(corpus)
    resolution = ev.resolve_baseline(sel, layer_a, d_rows_read=0, resolved_at_utc=WHEN)
    assert resolution.pd_base_id == "PD2-N"
    assert resolution.pd_base_identity_sha256 == _h("PD2-N")
    assert resolution.layer_a_result_sha256 == ev.layer_a_result_sha256(sel, layer_a)
    assert resolution.d_state == ev.D_NOT_STARTED and resolution.resolved_at_utc == WHEN
    again = ev.resolve_baseline(sel, list(reversed(layer_a)), d_rows_read=0, resolved_at_utc=WHEN)
    assert again.payload() == resolution.payload()
    ev.verify_resolution(sel, resolution, layer_a)
    tied = {"PD1-X": (0.9, 0.1, 0.9), "PD2-N": (0.9, 0.1, 0.9), "PD2-S": (0.9, 0.1, 0.9)}
    with pytest.raises(ev.BaselineStop, match="layer_a_rank_ambiguous"):
        ev.resolve_baseline(sel, layer_a_for(corpus, ("PD2-S", "PD2-N"), tied), d_rows_read=0, resolved_at_utc=WHEN)
    second = {"PD1-X": (0.9, 0.1, 0.9), "PD2-N": (0.9, 0.2, 0.99), "PD2-S": (0.9, 0.1, 0.5)}
    assert ev.resolve_baseline(sel, layer_a_for(corpus, ("PD2-S", "PD2-N"), second), d_rows_read=0,
                               resolved_at_utc=WHEN).pd_base_id == "PD2-S"
    missing = {"PD1-X": (0.9, 0.1, 0.9), "PD2-N": (None, 0.0, 0.99), "PD2-S": (0.1, 0.9, 0.1)}
    assert ev.resolve_baseline(sel, layer_a_for(corpus, ("PD2-S", "PD2-N"), missing), d_rows_read=0,
                               resolved_at_utc=WHEN).pd_base_id == "PD2-S"


def test_layer_a_artefact_is_canonical_and_m3_shaped():
    corpus = _selection_only()
    layer_a = layer_a_for(corpus)
    resolution = ev.resolve_baseline(corpus.sel, layer_a, d_rows_read=0, resolved_at_utc=WHEN)
    document = ev.layer_a_result_document(corpus.sel, layer_a)
    assert document["evidenceSha256"] == corpus.ab_digest
    assert [r["candidateId"] for r in document["results"]] == ["PD1-X", "PD2-N", "PD2-S"]
    assert set(document["results"][0]) == {"candidateId", "identitySha256", "gates", "rankKey", "measurementSha256"}
    assert resolution.layer_a_result_sha256 == ev._canonical_sha256(document)


def test_pd_base_resolution_stops_and_never_chooses():
    corpus = _selection_only()

    def stop(reason, results, **kw):
        with pytest.raises(ev.BaselineStop, match=reason):
            ev.resolve_baseline(corpus.sel, results, d_rows_read=kw.get("d_rows_read", 0),
                                resolved_at_utc=kw.get("when", WHEN))

    stop("no_detector_passed_layer_a", layer_a_for(corpus, passed=()))
    stop("after_d_data_read", layer_a_for(corpus), d_rows_read=1)
    stop("before_freeze", layer_a_for(corpus), when="2026-09-30T23:59:59Z")
    stop("time_malformed", layer_a_for(corpus), when="2026-10-14 00:00")
    outsider = layer_a_for(corpus) + [ev.LayerAResult(comp(corpus, "PD9-NEW", 100, 1.0, 0.0, 1.0),
                                                      _h("PD9-NEW"), True)]
    stop("inconsistent_with_frozen_detector_universe", outsider)
    stop("inconsistent_with_frozen_detector_universe", layer_a_for(corpus)[1:])
    stop("ambiguous_duplicate_detector", layer_a_for(corpus) + layer_a_for(corpus)[1:2])
    stop("identity_mismatch:PD2-N", layer_a_for(corpus, identities={"PD2-N": _h("PD2-N-retrained")}))
    failed = layer_a_for(corpus)
    failed[1] = dataclasses.replace(failed[1], score=comp(corpus, "PD2-N", 100, 0.95, 0.1, 0.9,
                                                          contract_fail=True))
    stop("gate_pass_with_contract_fail:PD2-N", failed)
    stop("non_finite_metric:PD2-N", layer_a_for(corpus, metrics={"PD1-X": (0.9, 0.1, 0.9),
                                                                 "PD2-N": (float("nan"), 0.1, 0.9),
                                                                 "PD2-S": (0.9, 0.1, 0.9)}))
    elsewhere = layer_a_for(corpus)
    elsewhere[1] = dataclasses.replace(elsewhere[1], score=comp("b" * 64, "PD2-N", 100, 0.95, 0.1, 0.9))
    stop("not_on_the_frozen_partition:PD2-N", elsewhere)
    recogniser_kind = layer_a_for(corpus)
    recogniser_kind[1] = dataclasses.replace(recogniser_kind[1], score=comp(corpus, "PD2-N", 100, 0.95, 0.1, 0.9,
                                                                            kind="recogniser"))
    stop("not_a_detector_result:PD2-N", recogniser_kind)
    unrecorded = layer_a_for(corpus)
    unrecorded[1] = dataclasses.replace(unrecorded[1], score=dataclasses.replace(unrecorded[1].score, result_id="x"))
    stop("not_from_the_harness", unrecorded)
    stop("layer_a_result_malformed", [dataclasses.replace(r, gates_passed=1) for r in layer_a_for(corpus)])


def test_sealed_resolution_cannot_change_or_be_forged_and_oc5_is_never_rankable():
    corpus = population(1)
    base = score(corpus, runs_for(corpus, outputs_of(1, lambda i: [_plate_text(i)])))
    resolution, layer_a = corpus.resolution, corpus.layer_a
    swapped = dataclasses.replace(resolution, pd_base_id="PD2-S")   # an edited copy names the harness record
    with pytest.raises(ValueError, match="sealed_pd_base"):
        gate(corpus, C("PD2-S", "OC1-XS", base), C("PD2-S", "OC5-BEST", base), resolution=swapped)
    forged = dataclasses.replace(resolution, result_id="f" * 32)
    with pytest.raises(ev.BaselineStop, match="not_from_the_harness"):
        gate(corpus, C("PD2-S", "OC1-XS", base), C("PD1-X", "OC5-BEST", base), resolution=forged)
    drifted = layer_a_for(corpus, passed=("PD2-S",))
    with pytest.raises(ev.BaselineStop, match="differs_from_frozen_derivation"):
        ev.verify_resolution(corpus.full, resolution, drifted)
    with pytest.raises(ev.BaselineStop, match="after_d_data_loaded"):
        ev.resolve_baseline(corpus.sel, drifted, d_rows_read=0, resolved_at_utc=WHEN)  # D is loaded: Stage 2 is over
    baseline = C("PD2-N", "OC5-BEST", with_d(base, Fraction(1, 2)))
    passing = C("PD2-S", "OC1-XS", with_d(base, Fraction(9, 10)))
    failing = C("PD1-X", "OC2-V6S", with_d(base, Fraction(1, 2)))
    assert ev.rankable_compositions(corpus.full, [passing, failing], baseline, resolution, layer_a) == [passing]
    for bad in (C("PD2-N", "OC5-BEST", base), C("PD2-S", "OC5-BEST", base)):
        with pytest.raises(ValueError, match="cannot_be_ranked"):
            ev.rankable_compositions(corpus.full, [passing, bad], baseline, resolution, layer_a)


def test_composition_identity_is_bound_through_the_real_path():
    corpus = population(3)
    pd1x = ident("PD1-X")
    s_oc5 = score(corpus, runs_for(corpus, outputs_of(3, lambda i: [_plate_text(i)]), det=pd1x, rec=OC5), (pd1x, OC5))
    s_base = score(corpus, runs_for(corpus, outputs_of(3, lambda i: [""]), det=PD_BASE, rec=OC5), (PD_BASE, OC5))
    s_ord = score(corpus, runs_for(corpus, outputs_of(3, lambda i: [_plate_text(i)])))
    resolution, layer_a = corpus.resolution, corpus.layer_a
    composition, baseline = ev.CompositionScore(s_oc5), ev.CompositionScore(s_base)
    assert (composition.detector_id, composition.recogniser_id) == ("PD1-X", "OC5-BEST")
    with pytest.raises(ValueError, match="cannot_be_ranked"):
        ev.rankable_compositions(corpus.full, [composition], baseline, resolution, layer_a)
    relabelled = ev.CompositionScore(dataclasses.replace(s_oc5, recogniser=ident("OC2-A")))  # inert copy edit
    assert relabelled.recogniser_id == "OC5-BEST"
    with pytest.raises(ValueError, match="sealed_pd_base"):
        gate(corpus, ev.CompositionScore(s_ord), ev.CompositionScore(s_ord))
    with pytest.raises(ValueError, match="sealed_pd_base"):
        gate(corpus, ev.CompositionScore(s_ord), composition)
    assert gate(corpus, ev.CompositionScore(s_ord), baseline) == ev.PASS
    vector = "fb6fffc212d8de2f3c6d67af7ff5c7186c633fd28bf1936d1d4e393c1753d8d3"  # M3 baseline_seal @ f24dcf5e
    assert ev.m3_composition_sha256(*EVENTS[:2], OC5, EVENTS[2], PD_BASE) == vector == resolution.composition_sha256


def test_benchmark_only_component_never_enters_top_k():
    corpus = _plate_corpus([_plate_text(i) for i in range(60)])

    def component(who):
        runs = read_runs(corpus, {f"p{i}": R((_plate_text(i), 0.9)) for i in range(60)}, rec=who)
        return ev.recogniser_component(ev.evaluate_b(corpus.sel, runs, recogniser=who))

    with pytest.raises(ValueError, match="run_recogniser_not_in_the_frozen_roster"):
        component(ev.ComponentIdentity("OC9-ALIAS", OC5.identity_sha256))
    with pytest.raises(ValueError, match="cannot_enter_top_k"):
        TOPK(corpus, [component(OC5)], "recogniser")
    ordinary = [component(ident(r)) for r in ("OC1-XS", "OC2-A", "OC2-B")]
    assert TOPK(corpus, ordinary, "recogniser") == ["OC1-XS", "OC2-A", "OC2-B"]
    with pytest.raises(ValueError, match="another_kind"):
        TOPK(corpus, ordinary, "detector")
    elsewhere = _plate_corpus([_plate_text(i) for i in range(2)])
    with pytest.raises(ValueError, match="not_on_the_frozen_partition"):
        TOPK(elsewhere, ordinary, "recogniser")


def test_top_k_is_deterministic_and_excludes_failures():
    detectors = ("PD2-M", "PD2-N", "PD2-S", "PD5-V5M", "PD5-V6S", "PD9-X")
    corpus = population(1, roster=default_roster(detectors, ("OC2-A", "OC2-B"), dependent=("PD5-V5M",)), protocol=None,
                        resolve=False,
                        mutate_record=lambda r: r["protocol"].update(
                            detectorFloors=[[d, FLOOR] for d in detectors]))
    scores = [comp(corpus, "PD2-S", 100, 0.9, 0.1, 0.8), comp(corpus, "PD2-N", 100, 0.9, 0.1, 0.9),
              comp(corpus, "PD5-V5M", 100, 0.99, 0.0, 0.99), comp(corpus, "PD2-M", 10, 1, 0, 1),
              comp(corpus, "PD5-V6S", 100, None, None, None),
              comp(corpus, "PD9-X", 100, 1.0, 0.0, 1.0, contract_fail=True)]
    assert TOPK(corpus, scores, "detector") == ["PD2-N", "PD2-S", "PD5-V6S"]
    ocr = [comp(corpus, "OC2-B", 60, 0.8, 0.1, 0.2, kind="recogniser"),
           comp(corpus, "OC2-A", 60, 0.8, 0.1, None, kind="recogniser")]
    with pytest.raises(ValueError, match="duplicate_candidate"):  # review 6, P3-4
        TOPK(corpus, [ocr[0], ocr[0]], "recogniser")
    assert TOPK(corpus, ocr, "recogniser") == ["OC2-B", "OC2-A"]
    crops_corpus = _crop_corpus([(((1, 1), (21, 1), (21, 11), (1, 11)),)])
    built = ev.detector_component(ev.evaluate_a(crops_corpus.sel, detect_runs(crops_corpus, GOOD_BOX), detector=DET))
    assert (built.candidate_id, built.primary, built.kind, built.partition_digest) == (
        "PD2-S", 1.0, "detector", crops_corpus.ab_digest)
    with pytest.raises(TypeError):   # owner point 4: N4 independence is the frozen record's verdict, not a parameter
        ev.detector_component(True, ev.evaluate_a(crops_corpus.sel, detect_runs(crops_corpus, GOOD_BOX),
                                                  detector=DET))


def test_detector_matched_tesseract_is_diagnostic_only():
    corpus = population(1)
    base = score(corpus, runs_for(corpus, outputs_of(1, lambda i: [_plate_text(i)])))
    high = C("PD2-S", "OC1-XS", with_d(base, Fraction(1, 2)))
    matched = C("PD2-S", "OC5-BEST", with_d(base, Fraction(1, 5)))
    assert ev.diagnostic_ocr_uplift(corpus.full, high, matched) == Fraction(3, 10)
    with pytest.raises(ValueError, match="not_detector_matched"):
        ev.diagnostic_ocr_uplift(corpus.full, high, C("PD2-N", "OC5-BEST", base))
    failed = C("PD2-S", "OC5-BEST", with_d(base, None, outcome=ev.CONTRACT_FAIL))
    assert ev.diagnostic_ocr_uplift(corpus.full, high, failed) is None
    other = population(2)
    elsewhere = score(other, runs_for(other, outputs_of(2, lambda i: [""])))
    with pytest.raises(ValueError, match="same_population"):
        ev.diagnostic_ocr_uplift(corpus.full, high, C("PD2-S", "OC5-BEST", elsewhere))


# ---------------------------------------------------------------------------------------------- N3 (owner 2026-10-14)


WRONG, RIGHT = "KA01AB1235", "KA01AB1234"


def _n3(*outputs_per_track):
    tracks = [T(f"n{i}", "s", RIGHT, n=len(outputs)) for i, outputs in enumerate(outputs_per_track)]
    corpus = build(tracks)
    runs = [run(corpus, t.track_id, recogniser=Outputs(outputs), detector=GOOD_BOX)
            for t, outputs in zip(tracks, outputs_per_track)]
    return score(corpus, runs).counts


def test_n3_uses_rank0_only_probe2_alternates_case():
    a = _n3([R((WRONG, 0.9)), R((WRONG, 0.9))])
    b = _n3([R((WRONG, 0.9), ("KA01AB1299", 0.1)), R((WRONG, 0.9), ("KA01AB1288", 0.1))])
    assert (a.consistent_wrong, b.consistent_wrong) == (1, 1)


def test_n3_owner_edge_semantics():
    assert _n3([R((WRONG, 0.9), ("KA01AB1299", 0.2), ("KA01AB1277", 0.1)), R((WRONG, 0.9), ("KA01AB1288", 0.1))]
               ).consistent_wrong == 1
    assert _n3([R((WRONG, 0.9), (RIGHT, 0.5)), R((WRONG, 0.9), (RIGHT, 0.5))]).consistent_wrong == 1
    assert _n3([R((WRONG, 0.9)), R((RIGHT, 0.9)), R((WRONG, 0.9))]).consistent_wrong == 0
    conflicting = _n3([R((WRONG, 0.9)), R(("KA01AB1236", 0.9))])
    assert (conflicting.consistent_wrong, conflicting.multi_source, conflicting.conflicting) == (0, 1, 1)
    single = _n3([R((WRONG, 0.9)), []])
    assert (single.consistent_wrong, single.multi_source) == (0, 0)
    unnormalisable = _n3([R((WRONG, 0.9)), R(("@@", 0.9), (WRONG, 0.5))])
    assert (unnormalisable.consistent_wrong, unnormalisable.multi_source) == (0, 0)
    assert _n3([R((WRONG, 0.9)), R((WRONG, 0.9)), R(("KA01AB1236", 0.9))]).consistent_wrong == 0
    assert _n3([R((WRONG, 0.9)), R((WRONG, 0.9)), R((WRONG, 0.8))]).consistent_wrong == 1
    assert _n3([R((WRONG, 0.9)), R((WRONG, 0.9)), R(("KA01-AB/1234!", 0.9))]).consistent_wrong == 1


def test_n3_denominators_are_unchanged():
    tracks = [T("w", "s", RIGHT, n=2), T("one", "s", RIGHT), T("ok", "s", RIGHT, n=2), T("none", "s", RIGHT, n=0),
              T("np", "s", NO_PLATE, n=2)]
    corpus = build(tracks)
    outputs = {"w": [R((WRONG, 0.9))] * 2, "one": [R((WRONG, 0.9))], "ok": [R((RIGHT, 0.9))] * 2,
               "np": [R((WRONG, 0.9))] * 2}
    runs = [run(corpus, tid, recogniser=Outputs(out), detector=GOOD_BOX) for tid, out in outputs.items()]
    result = score(corpus, runs)
    assert result.consistent_wrong_rate == Fraction(1, 4)
    assert result.consistent_wrong_conditional_rate == Fraction(1, 2)
    assert result.consistent_wrong_status == ev.INSUFFICIENT


# ---------------------------------------------------------------------------------------------- comparison


@pytest.fixture(scope="module")
def pair():
    corpus = population(70)
    good = runs_for(corpus, outputs_of(70, lambda i: [_plate_text(i)]))
    silent = runs_for(corpus, outputs_of(70, lambda i: [""]))
    half = runs_for(corpus, outputs_of(70, lambda i: [_plate_text(i) if i % 2 else ""]))
    near = runs_for(corpus, outputs_of(70, lambda i: [_plate_text(i) if i % 25 else ""]))
    return corpus, good, silent, half, near


def test_superiority_rule_and_determinism(pair):
    corpus, good, silent, half, near = pair
    first = compare(corpus, good, silent)
    assert first.outcome == "superior" and first.difference == 1 and first.lower > 0
    second = compare(corpus, good, silent)
    assert dataclasses.replace(first, result_id="") == dataclasses.replace(second, result_id="")
    assert first.cluster_signs == {"a": 70, "b": 0, "tie": 0, "insufficient": 0}
    assert compare(corpus, good, half).outcome == "superior"
    small = compare(corpus, good, near)
    assert small.difference < ev.MPID and small.outcome == "not-superior"
    assert compare(corpus, good, good).outcome == "not-superior"
    with pytest.raises(TypeError):
        compare(corpus, good, silent, mpid=0.04)  # MPID is not a parameter


def test_interval_must_exclude_zero_even_above_mpid():
    corpus = population(70, sites=lambda i: "siteA" if i < 10 else f"site{i}")
    a = runs_for(corpus, outputs_of(70, lambda i: [_plate_text(i)]))
    b = runs_for(corpus, outputs_of(70, lambda i: ["" if i < 10 else _plate_text(i)]))
    result = compare(corpus, a, b)
    assert result.difference >= ev.MPID
    assert result.lower <= 0 and result.outcome == "not-superior"


def test_percentile_indices_are_exact_integers():
    for r in range(1, 20001):
        assert ev.percentile_indices(r) == (math.floor(Fraction(25, 1000) * (r - 1)),
                                            math.ceil(Fraction(975, 1000) * (r - 1)))
    assert ev.percentile_indices(ev.BOOTSTRAP_REPLICATES) == (24, 975)


def test_fast_bootstrap_equals_re_evaluation(pair):
    corpus, good, _, half, _ = pair
    kwargs = dict(composition_a=(DET, REC), composition_b=(DET, REC), replicates=15, seed=11)
    assert ev._bootstrap_replicates(corpus.full, good, half, **kwargs) == \
        ev._bootstrap_replicates(corpus.full, good, half, slow=True, **kwargs)


def test_fast_bootstrap_on_multi_track_sites_equals_independent_evaluation():
    truths = ["KA01AB1234", "MH12CD5678"]
    tracks, out_a, out_b = [], {}, {}
    for site in range(6):
        for k, truth in enumerate(truths + truths[:1]):
            tid = f"s{site}t{k}"
            tracks.append(T(tid, f"site{site}", truth))
            out_a[tid] = [truth if (site + k) % 3 else "KA01AB1235"]
            out_b[tid] = [truth if (site + k) % 2 else ""]
    corpus = build(tracks)
    a, b = runs_for(corpus, out_a), runs_for(corpus, out_b)
    kwargs = dict(composition_a=(DET, REC), composition_b=(DET, REC), replicates=40, seed=5)
    fast = ev._bootstrap_replicates(corpus.full, a, b, **kwargs)
    assert fast == ev._bootstrap_replicates(corpus.full, a, b, slow=True, **kwargs)
    # Independent re-run: rebuild each replicate's population as its own corpus and score it with evaluate_d.
    ordered = sorted(tracks, key=lambda t: t.track_id)
    members: dict[str, list[int]] = {}
    for index, t in enumerate(ordered):
        members.setdefault(t.site, []).append(index)
    names = sorted(members)
    rng = random.Random(5)
    checked = 0
    for value in fast:
        picked = ev._draws(rng, members, names)
        if {ordered[i].truth for i in picked} != set(truths) or checked >= 20:
            continue
        sub_tracks = [T(f"{ordered[i].track_id}x{n}", ordered[i].site, ordered[i].truth) for n, i in enumerate(picked)]
        sub = build(sub_tracks)
        ra = [run(sub, t.track_id, out_a[t.track_id.split("x")[0]]) for t in sub_tracks]
        rb = [run(sub, t.track_id, out_b[t.track_id.split("x")[0]]) for t in sub_tracks]
        assert score(sub, ra).d_score - score(sub, rb).d_score == value
        checked += 1
    assert checked >= 20


def test_comparison_refusals_and_no_silent_drops(pair):
    corpus, good, silent, _, _ = pair
    with pytest.raises(ValueError, match="do_not_equal_the_bundle_items"):
        compare(corpus, good, silent[1:])
    assert ev._bootstrap_replicates(corpus.full, good, silent, composition_a=(DET, REC), composition_b=(DET, REC),
                                    replicates=50, seed=1).count(None) == 0
    violating = [run(corpus, "t0", [_plate_text(0)], n_boxes=3)] + good[1:]
    assert compare(corpus, violating, silent).outcome == "contract-fail"
    with pytest.raises(ValueError, match="contract_violating_run"):
        ev._bootstrap_replicates(corpus.full, violating, silent, composition_a=(DET, REC),
                                 composition_b=(DET, REC), replicates=5, seed=1)
    pd1x = ident("PD1-X")
    oc5_runs = runs_for(corpus, outputs_of(70, lambda i: [_plate_text(i)]), det=pd1x, rec=OC5)
    with pytest.raises(ValueError, match="cannot_be_ranked"):
        compare(corpus, oc5_runs, silent, composition_a=(pd1x, OC5))


def test_comparison_config_is_the_frozen_one(pair):
    corpus, good, silent, _, _ = pair
    assert ev.BOOTSTRAP_REPLICATES == 1000
    seeded = population(70, mutate_record=lambda r: r["protocol"].update(bootstrapSeed=3))  # seed substitution
    assert seeded.sel.record_sha256 != corpus.sel.record_sha256 and seeded.d_digest != corpus.d_digest
    with pytest.raises(ValueError, match="result_of_another_partition_or_bundle"):
        compare(seeded, good, silent)  # runs of the frozen corpus are refused under another seed's record
    with pytest.raises(ev.BaselineStop, match="of_another_freeze"):
        ev.paired_cluster_bootstrap(seeded.full, good, silent, composition_a=(DET, REC), composition_b=(DET, REC),
                                    resolution=corpus.resolution, layer_a_results=corpus.layer_a)
    higher = population(70, mutate_record=lambda r: r["protocol"].update(calibrationMinimumClusters=71))
    hr = runs_for(higher, outputs_of(70, lambda i: [_plate_text(i)]))
    hs = runs_for(higher, outputs_of(70, lambda i: [""]))
    assert compare(higher, hr, hs).outcome == "insufficient-clusters"  # max(60, 71) from the frozen record


def test_required_clusters_is_max_of_floor_and_calibration():
    assert [ev.required_clusters(v) for v in (1, 59, 60, 61, 140)] == [60, 60, 60, 61, 140]
    for bad in (0, -1, True, 60.0, None):
        with pytest.raises(ValueError, match="calibration_minimum_invalid"):
            ev.required_clusters(bad)


# ---------------------------------------------------------------------------------------------- sixth/seventh review


def test_c_minus_b_needs_matching_harness_results():
    corpus = _plate_corpus(["KA01AB1234", "MH12AB0001"], b=True, c=True)
    b = ev.evaluate_b(corpus.sel, read_runs(corpus, {"p0": R(("KA01AB1234", 0.9)), "p1": R(("MH12AB0001", 0.9))}),
                      recogniser=REC)
    c = ev.evaluate_c(corpus.sel, runs_for(corpus, {"t0": ["KA01AB1234"], "t1": [""]}), composition=(DET, REC))
    assert ev.c_minus_b(c, b) == Fraction(-1, 2)
    assert ev.c_minus_b(dataclasses.replace(c, em=Fraction(1)), b) == Fraction(-1, 2)  # an edited copy is inert
    with pytest.raises(ValueError, match="not_from_the_harness"):
        ev.c_minus_b(dataclasses.replace(c, result_id=""), b)
    other_rec = ev.evaluate_b(corpus.sel, read_runs(corpus, {"p0": [], "p1": []}, rec=OC5), recogniser=OC5)
    with pytest.raises(ValueError, match="not_comparable"):
        ev.c_minus_b(c, other_rec)


def test_any_violation_in_the_composition_makes_c_a_contract_fail():
    """Review 6, P3-1: a violation on a Track that holds no C plate still fails C (probe 6)."""
    corpus = build([T("t0", "s0", "KA01AB1234"), T("t1", "s1", "KA02AB1234")], plates=[plate("p0", "t0", c=0)])
    bad = run(corpus, "t1", recogniser=Outputs([R(("KA02AB1234", 1.5))]))
    good = run(corpus, "t0", ["KA01AB1234"])
    assert bad.state == ev.CONTRACT_FAIL
    assert ev.evaluate_c(corpus.sel, [good, bad], composition=(DET, REC)).outcome == ev.CONTRACT_FAIL


def test_unsupported_text_is_typed_and_counted_wrong_for_precision():
    """Owner decision: human truth outside v1 or the letter+digit rule is UNSUPPORTED_TEXT, kept with its raw text,
    excluded from text-recall denominators, and every return against it is wrong for precision."""
    plain = build([T("p", "s1", "KA01AB1234")])
    mixed = build([T("p", "s1", "KA01AB1234"), T("u", "s2", "UNKNOWN")])
    track = ev.sb._state_of(mixed.full).d.tracks["u"]
    assert (track.state, track.text, track.supported) == (ev.TruthState.UNSUPPORTED_TEXT, "UNKNOWN", None)
    without = score(plain, runs_for(plain, {"p": ["KA01AB1234"]}))
    with_u = score(mixed, runs_for(mixed, {"p": ["KA01AB1234"], "u": ["KA01AB1234"]}))
    assert with_u.counts.exact_denominator == without.counts.exact_denominator  # recall denominators unchanged
    assert with_u.counts.correct_returned == without.counts.correct_returned  # never a correct return
    assert with_u.contains_precision < without.contains_precision


def test_comparison_is_a_harness_record():
    corpus = population(3)
    runs = runs_for(corpus, outputs_of(3, lambda i: [_plate_text(i)]))
    result = compare(corpus, runs, runs)
    assert stored(ev._CMP, result).outcome == result.outcome
    assert stored(ev._CMP, dataclasses.replace(result, outcome="superior")).outcome == result.outcome
