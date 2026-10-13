"""A–D evaluators and the query generator on synthetic fixtures only (no dataset, no model)."""

from __future__ import annotations

import hashlib
import io
import uuid

import pytest
from PIL import Image

from mavi_vision.plates.inference import PlateBox, Reading
from mavi_vision.plates.pipeline import PlateRecord, RankedReading
from tools.benchmarks.capabilities.plates import evaluator as ev
from tools.benchmarks.capabilities.plates import queries as q

PARAMS = q.QueryParameters(prefix_length=4, suffix_length=4, interior_length=5, interior_offset=1,
                           negatives_per_plate=2, seed="synthetic-seed")


# Query generator


def test_queries_are_deterministic_bounded_and_deduplicated():
    first = q.generate(["KA01AB1234", "ka-01 ab 1234", "KA01CD99", "MH12", "ab@1"], PARAMS)
    second = q.generate(["KA01CD99", "KA01AB1234", "MH12"], PARAMS)
    assert first.queries == second.queries
    assert first.rejected_truths == ("ab@1",)
    texts = {(x.query_class, x.text): x for x in first.queries}
    assert texts[("full", "KA01AB1234")].match == q.EXACT
    assert texts[("prefix", "KA01")].sources == ("KA01AB1234", "KA01CD99")  # one query, both sources
    assert ("interior", "A01AB") in texts and ("suffix", "1234") in texts
    assert first.skipped["interior"] >= 1 and first.skipped["prefix"] >= 1  # MH12 has no interior or prefix
    for query in first.queries:
        assert 3 <= len(query.text) <= 15 and set(query.text) <= set(q.ALPHABET)
        if query.query_class == q.NEGATIVE:
            assert not any(query.text in t for t in first.truths)
            assert min(q.levenshtein(query.text, t) for t in query.sources) in (1, 2)


def test_query_parameters_have_no_hidden_defaults():
    with pytest.raises(TypeError):
        q.QueryParameters(prefix_length=4, suffix_length=4, interior_length=5)  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        q.QueryParameters(4, 4, 5, 0, 1, "s")


# A


def test_coverage_and_detection_metrics():
    square = ((10, 10), (30, 10), (30, 20), (10, 20))
    assert ev.coverage(square, (0, 0, 100, 100)) == 1.0
    assert ev.coverage(square, (20, 0, 100, 100)) == pytest.approx(0.5)
    items = [ev.DetectionItem("c1", (square,), ((10, 10, 20, 10, 0.9), (60, 60, 5, 5, 0.8))),
             ev.DetectionItem("c2", (((0, 0), (10, 0), (10, 10), (0, 10)),), ())]
    result = ev.evaluate_detection(items)
    assert (result.plates, result.covered, result.recall) == (2, 1, 0.5)
    assert result.false_plates_per_crop == 0.5 and result.ap50 == pytest.approx(0.5)


# B / C


def _plate(*readings):
    return ev.plate_record_from_readings([Reading(t, c) for t, c in readings], ev.evaluation_parameters(0.25))


def test_reading_rules_follow_pr3():
    assert _plate(("KA01AB1234", 0.2)).outcome == "read"  # OCR floor 0 for ranking (D6)
    assert _plate(("X", 0.5), ("X", 0.5)) is None  # duplicate: ocr_output_invalid abstention
    assert _plate(("", 0.5)) is None  # empty raw text is not a reading
    with pytest.raises(ev.OutputInvalid):
        _plate(("A", 0.1), ("B", 0.2), ("C", 0.3), ("D", 0.4))
    floored = ev.plate_record_from_readings([Reading("KA01", 0.2)], ev.evaluation_parameters(0.25, 0.5))
    assert floored.outcome == "unreadable"


def test_reading_metrics():
    items = [ev.ReadItem("p1", "KA01AB1234", _plate(("ka01 ab1234", 0.9))),
             ev.ReadItem("p2", "KA01AB1234", _plate(("KA01AB1284", 0.8))),
             ev.ReadItem("p3", "KA01AB1234", None),
             ev.ReadItem("p4", "a@b", None)]
    result = ev.evaluate_reading(items, ece_bins=2)
    assert (result.plates, result.exact, result.unsupported_truths) == (3, 1, 1)
    assert result.em == pytest.approx(1 / 3)
    assert result.cer == pytest.approx((0 + 0.1 + 1.0) / 3)
    assert result.ece == pytest.approx(0.5 * abs(0.9 - 1) + 0.5 * abs(0.8 - 0))


# Running PR-3 rules end to end


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 32), (200, 200, 200)).save(buffer, format="JPEG")
    return buffer.getvalue()


class Detector:
    def __init__(self, boxes):
        self.boxes = boxes

    def detect(self, crop, verified):
        return list(self.boxes)


class Recogniser:
    def __init__(self, readings):
        self.readings = readings

    def read(self, region, verified, box):
        return list(self.readings)


def _crops(n):
    content = _jpeg()
    sha = hashlib.sha256(content).hexdigest()
    return [ev.EvidenceCrop(uuid.uuid4(), "near-view", i, sha, content) for i in range(n)]


def test_run_track_uses_product_rules_and_bounds():
    params = ev.evaluation_parameters(0.25)
    run = ev.run_track(uuid.UUID(int=99), _crops(2), Detector([PlateBox(1, 1, 20, 10, 0.9)]),
                       Recogniser([Reading("KA01AB1234", 0.4)]), params)
    assert run.contract_violation is None
    assert [t.normalised_text for t in run.record.texts] == ["KA01AB1234"] and run.record.texts[0].support_count == 2
    over = ev.run_track(uuid.UUID(int=98), _crops(1), Detector([PlateBox(1, 1, 5, 5, 0.9)] * 3),
                        Recogniser([]), params)
    assert over.record is None and over.contract_violation == "plate_detector_output_exceeds_bound"
    diagnostic = ev.refloor(run.record, 0.5)
    assert diagnostic.texts == () and run.record.texts  # diagnostic only; the original is unchanged


def _item(track_id, truth, readings, cluster="s1"):
    crops = _crops(len(readings))
    detector = Detector([PlateBox(1, 1, 20, 10, 0.9)])
    records = []
    for crop, reading in zip(crops, readings):
        run = ev.run_track(uuid.UUID(int=1000 + len(records)), [crop], detector,
                           Recogniser([Reading(reading, 0.9)] if reading else []), ev.evaluation_parameters(0.25))
        records.append(run.record.crops[0])
    from mavi_vision.plates.pipeline import summarise_track
    track = ev.lease_track(uuid.uuid5(uuid.NAMESPACE_URL, track_id),
                           tuple(ev.lease_observation(c.observation_id, "near-view", c.evidence_rank, 1, "0" * 64)
                                 for c in records))
    return ev.TrackItem(track_id, cluster, truth, ev.TrackRun(summarise_track(track, tuple(records)), None))


def test_d_score_on_a_closed_population_and_consistent_wrong():
    items = [_item("t1", "KA01AB1234", ["KA01AB1234"]),
             _item("t2", "MH12CD5678", ["MH12CD5670", "MH12CD5670"]),  # consistent wrong (2 sources)
             _item("t3", ev.NO_PLATE, ["KA01ZZ9999"]),  # labelled no-plate Track with a spurious reading
             ev.TrackItem("t4", "s2", "DL3CAB0001", None)]  # no MAVI Track: not read
    queries = q.generate([i.truth for i in items if i.truth != ev.NO_PLATE], PARAMS)
    score = ev.evaluate_tracks(items, queries)
    assert score.exact_denominator == 3 and score.exact_recall == pytest.approx(1 / 3)
    assert score.consistent_wrong == 1 and score.multi_reading_tracks == 1
    assert score.consistent_wrong_status == ev.INSUFFICIENT  # denominator 3 < 50
    assert score.contains_precision is not None and score.contains_precision < 1  # t3's prefix KA01 hit is wrong
    assert score.d_score == pytest.approx((score.exact_recall + score.contains_recall + score.contains_precision) / 3)


def test_d_refuses_unlabelled_tracks_and_bootstrap_needs_clusters():
    with pytest.raises(ValueError, match="fully_labelled"):
        ev.evaluate_tracks([ev.TrackItem("t", "s", None, None)], q.generate([], PARAMS))  # type: ignore[arg-type]
    items = [_item(f"t{i}", "KA01AB1234", ["KA01AB1234"], cluster=f"s{i}") for i in range(3)]
    queries = q.generate(["KA01AB1234"], PARAMS)
    result = ev.paired_cluster_bootstrap(items, items, queries, replicates=10, seed=1)
    assert result.outcome == "insufficient-clusters" and result.clusters == 3
    small = ev.paired_cluster_bootstrap(items, items, queries, replicates=20, seed=1, minimum_clusters=2)
    assert small.difference == 0 and small.outcome == "not-superior"


def test_top_k_and_gates():
    scores = [ev.ComponentScore("PD2-S", True, 100, 0.9, 0.1, 0.8), ev.ComponentScore("PD2-N", True, 100, 0.9, 0.1, 0.9),
              ev.ComponentScore("PD5-V5M", False, 100, 0.99, 0.0, 0.99), ev.ComponentScore("PD2-M", True, 10, 1, 0, 1)]
    assert ev.top_k(scores, 3, 50, "detector") == ["PD2-N", "PD2-S"]
    ocr = [ev.ComponentScore("OC2-B", True, 60, 0.8, 0.1, 0.2), ev.ComponentScore("OC2-A", True, 60, 0.8, 0.1, 0.2)]
    assert ev.top_k(ocr, 1, 50, "recogniser") == ["OC2-A"]
    assert ev.baseline_gate(0.62, 0.60) == ev.PASS and ev.baseline_gate(0.61, 0.60) == ev.FAIL
    assert ev.baseline_gate(None, 0.6) == ev.INSUFFICIENT
    assert (ev.MPID, ev.MINIMUM_INDEPENDENT_CLUSTERS, ev.RANKING_OCR_CONFIDENCE_FLOOR) == (0.02, 60, 0.0)
    params = ev.evaluation_parameters(0.25)
    assert (params.max_detections_per_crop, params.max_plates_per_crop, params.max_readings_per_plate) == (2, 1, 3)


def test_plate_record_type_is_the_products():
    plate = _plate(("KA01", 0.5))
    assert isinstance(plate, PlateRecord) and isinstance(plate.readings[0], RankedReading)
