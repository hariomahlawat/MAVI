from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "evaluate_ground_truth.py"
SPEC = importlib.util.spec_from_file_location("phase1_evaluator", MODULE_PATH)
assert SPEC and SPEC.loader
ev = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ev)


def profile(mode="baseline"):
    value = {
        "schemaVersion": "mavi-phase1-acceptance-profile-v1",
        "mode": mode,
        "matching": {
            "minimumTemporalIou": 0.5,
            "minimumSpatialIou": 0.5,
            "maximumInterpolationSpanMs": 2000,
            "iouFixedPrecisionScale": 1000000,
            "iouRounding": "half-up",
        },
        "requiredClasses": ["Person", "Vehicle"],
        "classThresholds": {"Person": None, "Vehicle": None},
        "emptyScene": {"maximumUnmatchedTracks": None},
    }
    if mode == "qualification":
        value["classThresholds"] = {
            "Person": {"precision": 0.5, "recall": 0.5, "f1": 0.5},
            "Vehicle": {"precision": 0.5, "recall": 0.5, "f1": 0.5},
        }
    return value


def event(event_id, cls, start, end, x):
    return {
        "eventId": event_id,
        "objectClass": cls,
        "startOffsetMs": start,
        "endOffsetMs": end,
        "spatialSamples": [
            {"offsetMs": start, "boundingBox": {"x": x, "y": 0.1, "width": 0.2, "height": 0.2}},
            {"offsetMs": end, "boundingBox": {"x": x, "y": 0.1, "width": 0.2, "height": 0.2}},
        ],
    }


def ground_truth(events):
    return {
        "schemaVersion": "mavi-phase1-ground-truth-v1",
        "videoSha256": "a" * 64,
        "durationMs": 10000,
        "cameraCode": "QUAL",
        "evaluationWindows": [{"startOffsetMs": 0, "endOffsetMs": 10000}],
        "events": events,
    }


def track(track_id, cls, start, end, offset, x):
    return {
        "id": track_id,
        "processingRunId": "run",
        "videoAssetId": "video",
        "objectClass": cls,
        "startOffsetMs": start,
        "endOffsetMs": end,
        "representative": {
            "videoOffsetMs": offset,
            "boundingBox": {"x": x, "y": 0.1, "width": 0.2, "height": 0.2},
        },
    }


def test_spatial_identity_prevents_temporal_false_match():
    gt = ground_truth([event("p1", "Person", 1000, 4000, 0.1)])
    tracks = [track("t1", "Person", 1000, 4000, 2000, 0.7)]
    result = ev.evaluate(gt, tracks, profile())
    assert result["overall"]["matchedCount"] == 0


def test_maximum_cardinality_precedes_local_quality():
    gt = ground_truth([
        event("a", "Person", 1000, 4000, 0.10),
        event("b", "Person", 1000, 4000, 0.20),
    ])
    tracks = [
        track("t1", "Person", 1000, 4000, 2000, 0.15),
        track("t2", "Person", 1000, 4000, 2000, 0.10),
    ]
    result = ev.evaluate(gt, tracks, profile())
    assert result["overall"]["matchedCount"] == 2
    assert {(m["eventId"], m["trackId"]) for m in result["matching"]} == {("a", "t2"), ("b", "t1")}


def test_qualification_requires_both_supported_classes():
    gt = ground_truth([event("p1", "Person", 1000, 4000, 0.1)])
    tracks = [track("t1", "Person", 1000, 4000, 2000, 0.1)]
    result = ev.evaluate(gt, tracks, profile("qualification"))
    assert result["qualification"]["passed"] is False
    assert "Vehicle:coverage_zero" in result["qualification"]["failures"]


def test_baseline_allows_measurement_without_thresholds():
    gt = ground_truth([])
    result = ev.evaluate(gt, [], profile())
    assert result["mode"] == "baseline"
    assert result["qualification"]["passed"] is None


def test_qualification_profile_rejects_missing_thresholds():
    p = profile("qualification")
    p["classThresholds"]["Vehicle"] = None
    with pytest.raises(ev.EvaluationError, match="qualification_threshold_missing"):
        ev.validate_profile(p)


def test_ground_truth_rejects_excessive_spatial_gap():
    gt = ground_truth([event("p1", "Person", 1000, 4000, 0.1)])
    with pytest.raises(ev.EvaluationError, match="spatial_sample_gap_invalid"):
        ev.validate_ground_truth(gt, profile())


def test_matching_tie_break_is_deterministic():
    gt = ground_truth([
        event("a", "Person", 1000, 3000, 0.1),
        event("b", "Person", 1000, 3000, 0.1),
    ])
    tracks = [
        track("t2", "Person", 1000, 3000, 2000, 0.1),
        track("t1", "Person", 1000, 3000, 2000, 0.1),
    ]
    first = ev.evaluate(gt, tracks, profile())["matching"]
    second = ev.evaluate(copy.deepcopy(gt), list(reversed(copy.deepcopy(tracks))), profile())["matching"]
    assert [(x["eventId"], x["trackId"]) for x in first] == [("a", "t1"), ("b", "t2")]
    assert [(x["eventId"], x["trackId"]) for x in first] == [(x["eventId"], x["trackId"]) for x in second]
