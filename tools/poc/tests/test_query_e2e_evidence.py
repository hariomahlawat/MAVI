"""Offline tests for the PoC S9 structured-query evidence reader: protocol first, loopback refusal, percentiles,
determinism, windows and the cross-checks against the surfaces the contract reuses."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import query_e2e_evidence as qe  # noqa: E402


def test_the_api_must_be_loopback():
    with pytest.raises(SystemExit, match="loopback"):
        qe.get("http://192.168.1.10:5000", "/api/query/contract")


def test_nearest_rank_percentile():
    values = [float(v) for v in range(1, 21)]
    assert qe.percentile(values, 0.95) == 19.0
    assert qe.percentile(values, 0.5) == 10.0
    assert qe.percentile([5.0], 0.95) == 5.0


def test_stability_ignores_only_the_snapshot():
    a = {"snapshot": {"visibilitySequence": 1}, "result": {"value": 3}}
    b = {"snapshot": {"visibilitySequence": 2}, "result": {"value": 3}}
    c = {"snapshot": {"visibilitySequence": 2}, "result": {"value": 4}}
    assert qe.stable(a) == qe.stable(b)
    assert qe.stable(a) != qe.stable(c)


def test_recording_window_snaps_outward_and_bucket_keeps_the_bound():
    window = qe.recording_window([
        {"recordingStartUtc": "2026-01-01T10:00:30Z", "recordingEndUtc": "2026-01-01T10:03:10Z"},
        {"recordingStartUtc": "2026-01-03T10:00:00Z", "recordingEndUtc": "2026-01-03T10:01:00Z"},
    ])
    assert window == ("2026-01-01T10:00:00Z", "2026-01-03T10:01:00Z")
    assert qe.bucket_for(*window) == 900  # 2 days: 300 s would be 577 buckets, over 512


def test_run_refuses_without_a_predeclared_protocol(tmp_path):
    with pytest.raises(SystemExit, match="predeclared"):
        qe.run("http://127.0.0.1:1", tmp_path)


def test_protocol_records_the_budget_and_every_query(tmp_path):
    path = qe.write_protocol(tmp_path)
    protocol = json.loads(path.read_text(encoding="utf-8"))
    assert protocol["budget"]["milliseconds"] == qe.BUDGET_P95_MS
    assert len(protocol["set"]) == len(qe.LATENCY_SET)
    units = {item["unit"] for item in protocol["set"]}
    ops = {item["operation"]["op"] for item in protocol["set"]}
    assert units == {"track", "event", "entity"}
    assert ops == {"find", "count", "countDistinct", "groupBy", "timeBucket", "first", "last", "top", "compare"}


def test_crosscheck_compares_counts_with_track_search_timeline_and_stage3(monkeypatch):
    camera = {"id": "C1", "code": "POC-S2-01"}
    videos = [{"cameraId": "c1", "recordingStartUtc": "2026-01-01T10:00:30Z", "recordingEndUtc": "2026-01-01T10:03:10Z"}]

    def get(api, path):
        if path.startswith("/api/cameras/C1/events?"):
            return {"ruleCounts": [{"ruleId": "line-crossing", "count": 2}, {"ruleId": "zone-dwell", "count": 0}],
                    "coverage": {"complete": True}}
        if path.startswith("/api/cameras/C1/analytics/aggregates?"):
            return {"lines": [{"lineId": "L1", "aToBCounts": [1, 0], "bToACounts": [0, 1]}]}
        if path.startswith("/api/tracks?"):
            return {"items": [{}, {}, {}], "nextCursor": None}
        raise AssertionError(path)

    def post(api, body):
        operation, where = body["operation"], body["where"]
        if body["unit"] == "track":
            return 200, {"result": {"value": 3}, "coverage": {"complete": True}}, 1.0
        if operation["op"] == "groupBy":
            return 200, {"result": {"groups": [{"key": "line-crossing", "count": 2}]}, "coverage": {"complete": True}}, 1.0
        return 200, {"result": {"value": 1}, "coverage": {"complete": True}}, 1.0

    monkeypatch.setattr(qe, "get", get)
    monkeypatch.setattr(qe, "post_query", post)
    [row] = qe.crosscheck("http://127.0.0.1:1", [camera], videos)
    assert row["trackCount"] == {"query": 3, "trackSearch": 3, "coverageComplete": True, "equal": True}
    assert row["eventsByRule"]["equal"] is True
    assert row["crossings"][0]["equal"] is True


def _withheld_world(monkeypatch):
    camera = {"id": "C1", "code": "POC-S2-01"}
    videos = [{"cameraId": "c1", "recordingStartUtc": "2026-01-01T10:00:30Z", "recordingEndUtc": "2026-01-01T10:03:10Z"}]

    def get(api, path):
        if path.startswith("/api/cameras/C1/events?"):
            return {"ruleCounts": [], "coverage": {"complete": False}}
        if path.startswith("/api/cameras/C1/analytics/aggregates?"):
            return {"lines": [{"lineId": "L1", "aToBCounts": [0], "bToACounts": [0]}]}
        if path.startswith("/api/tracks?"):
            return {"items": [], "nextCursor": None}
        raise AssertionError(path)

    def post(api, body):
        return 200, {"result": {"kind": "withheld", "value": None, "groups": None}, "coverage": {"complete": False}}, 1.0

    monkeypatch.setattr(qe, "get", get)
    monkeypatch.setattr(qe, "post_query", post)
    return camera, videos


def test_a_withheld_answer_never_counts_as_agreement(monkeypatch):
    camera, videos = _withheld_world(monkeypatch)
    [row] = qe.crosscheck("http://127.0.0.1:1", [camera], videos)
    # Empty maps and missing values would compare equal; incomplete coverage must make every check fail instead.
    assert row["eventsByRule"]["query"] == row["eventsByRule"]["timeline"] == {}
    assert row["eventsByRule"]["equal"] is False
    assert row["trackCount"]["equal"] is False
    assert row["crossings"][0]["equal"] is False


def test_corpus_scope_names_only_the_demo_cameras(monkeypatch):
    cameras = [{"id": "C2", "code": "POC-S2-02"}, {"id": "C1", "code": "POC-S2-01"}]
    body = qe.materialise("http://127.0.0.1:1", "track-count", "track", {"op": "count"}, {}, "corpus", cameras, [],
                          ("2026-01-01T10:00:00Z", "2026-01-01T11:00:00Z"))
    assert body["where"]["cameraIds"] == ["c1", "c2"]
