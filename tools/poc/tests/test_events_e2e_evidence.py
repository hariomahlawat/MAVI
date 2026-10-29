"""Offline tests for the PoC S8 events evidence reader: window, loopback refusal, crossing agreement, table."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import events_e2e_evidence as ev  # noqa: E402

CAMERA = "c1"
LINE = "l1"


def fake_api(aggregate_counts):
    timeline = {
        "sceneRevisionId": "r", "sceneRevisionNumber": 2, "analyticsAlgorithmVersion": "scene-analytics-v1",
        "catalogueVersion": "mavi-events-v1", "truncated": False,
        "coverage": {"complete": True},
        "ruleCounts": [{"ruleId": "line-crossing", "count": 1}],
        "crossingCounts": [{"lineId": LINE, "name": "Gate", "aToBLabel": "In", "bToALabel": "Out",
                            "aToBCounts": [1, 0, 0, 0], "bToACounts": [0, 0, 0, 0]}],
        "events": [{"eventId": "e1", "ruleId": "line-crossing", "startUtc": "s", "endUtc": "s", "startOffsetMs": 1,
                    "endOffsetMs": 1, "primaryTrackId": "t", "objectClass": "Vehicle", "zoneName": None,
                    "lineName": "Gate", "directionLabel": "In", "participantCount": 1}],
    }
    responses = {
        "/api/events/catalogue": {"rules": [{"ruleId": "line-crossing"}, {"ruleId": "repeated-visit"}]},
        "/api/cameras/": [{"id": CAMERA, "code": "POC-S2-01", "name": "one"}, {"id": "x", "code": "OTHER", "name": "x"}],
        "/api/videos": [{"cameraId": CAMERA, "recordingStartUtc": "2026-01-01T10:00:30Z",
                         "recordingEndUtc": "2026-01-01T10:03:10Z"}],
        "/api/events/e1": {"event": {}, "parameters": []},
    }

    def get(api, path):
        if path.startswith(f"/api/cameras/{CAMERA}/events?"):
            return timeline
        if path.startswith(f"/api/cameras/{CAMERA}/analytics/aggregates?"):
            return {"lines": [{"lineId": LINE, "aToBCounts": aggregate_counts, "bToACounts": [0, 0, 0, 0]}]}
        return responses[path]

    return get


def test_the_window_covers_the_recordings_in_whole_minutes():
    assert ev._window([{"recordingStartUtc": "2026-01-01T10:00:30Z", "recordingEndUtc": "2026-01-01T10:03:10Z"}]) == (
        "2026-01-01T10:00:00Z", "2026-01-01T10:04:00Z", 60)


def test_a_non_loopback_api_is_refused():
    with pytest.raises(SystemExit):
        ev._get("http://example.org", "/api/events/catalogue")


@pytest.mark.parametrize(("aggregate", "agrees"), [([1, 0, 0, 0], True), ([0, 1, 0, 0], False)])
def test_crossing_counts_are_compared_with_the_stage_three_aggregate(monkeypatch, aggregate, agrees):
    monkeypatch.setattr(ev, "_get", fake_api(aggregate))

    record = ev.collect("http://127.0.0.1:1")

    clip = record["clips"][0]
    assert [c["code"] for c in record["clips"]] == ["POC-S2-01"]
    assert clip["crossingCountsEqualStage3Aggregate"] is agrees
    assert clip["byRuleAndPlace"] == {"line-crossing @ Gate (In)": 1}
    assert set(clip["sampleDetails"]) == {"line-crossing"}
    assert "| POC-S2-01 | complete | 1 | off |" in ev.table(record)
