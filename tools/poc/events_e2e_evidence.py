"""PoC S8 (register C7.1, C7.2): read-only evidence of analytic events on the demo corpus.

Development tooling only, standard library only, loopback API only. For every demo
camera it reads the Events timeline over the camera's own recording window, the
rule catalogue, one event detail per rule that fired (its provenance envelope), and
the Stage-3 aggregate for the same window, which crossing counts must equal. It
writes one JSON record and prints a per-clip table. It creates nothing and reads no
media; every number is pipeline output, not ground truth.

    python tools/poc/events_e2e_evidence.py --api http://127.0.0.1:62188 --out <dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEMO_PREFIX = "POC-S2-"
BUCKETS = (60, 300, 900, 3600)
MAXIMUM_BUCKETS = 512


def _get(api: str, path: str):
    if urllib.parse.urlparse(api).hostname not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("REFUSED: the API must be loopback")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(api.rstrip("/") + path, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _iso(instant: datetime) -> str:
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _window(videos: list[dict]) -> tuple[str, str, int]:
    start = min(_parse(v["recordingStartUtc"]) for v in videos).timestamp()
    end = max(_parse(v["recordingEndUtc"]) for v in videos).timestamp()
    start = math.floor(start / 60) * 60
    end = math.ceil(end / 60) * 60
    bucket = next(size for size in BUCKETS if math.ceil((end - start) / size) <= MAXIMUM_BUCKETS)
    return (
        _iso(datetime.fromtimestamp(start, timezone.utc)),
        _iso(datetime.fromtimestamp(end, timezone.utc)),
        bucket,
    )


def collect(api: str) -> dict:
    catalogue = _get(api, "/api/events/catalogue")
    cameras = sorted(
        (c for c in _get(api, "/api/cameras/") if c["code"].startswith(DEMO_PREFIX)), key=lambda c: c["code"]
    )
    videos = _get(api, "/api/videos")
    clips = []
    for camera in cameras:
        own = [v for v in videos if v["cameraId"].lower() == camera["id"].lower()]
        if not own:
            clips.append({"code": camera["code"], "name": camera["name"], "videos": 0})
            continue
        from_utc, to_utc, bucket = _window(own)
        query = urllib.parse.urlencode(
            {"fromUtc": from_utc, "toUtc": to_utc, "bucketSeconds": bucket, "limit": 5000}
        )
        timeline = _get(api, f"/api/cameras/{camera['id']}/events?{query}")
        aggregate = _get(
            api,
            f"/api/cameras/{camera['id']}/analytics/aggregates?"
            + urllib.parse.urlencode({"fromUtc": from_utc, "toUtc": to_utc, "bucketSeconds": bucket}),
        )
        stage3 = {line["lineId"]: (line["aToBCounts"], line["bToACounts"]) for line in aggregate["lines"]}
        crossing_counts_equal = all(
            stage3.get(line["lineId"]) == (line["aToBCounts"], line["bToACounts"])
            for line in timeline["crossingCounts"]
        ) and len(stage3) == len(timeline["crossingCounts"])

        samples = {}
        for event in timeline["events"]:
            if event["ruleId"] not in samples:
                samples[event["ruleId"]] = _get(api, f"/api/events/{event['eventId']}")

        by_zone_rule: dict[str, int] = {}
        for event in timeline["events"]:
            where = event.get("zoneName") or event.get("lineName") or "-"
            label = f"{event['ruleId']} @ {where}" + (f" ({event['directionLabel']})" if event.get("directionLabel") else "")
            by_zone_rule[label] = by_zone_rule.get(label, 0) + 1

        clips.append(
            {
                "code": camera["code"],
                "name": camera["name"],
                "videos": len(own),
                "window": {"fromUtc": from_utc, "toUtc": to_utc, "bucketSeconds": bucket},
                "sceneRevisionId": timeline["sceneRevisionId"],
                "sceneRevisionNumber": timeline["sceneRevisionNumber"],
                "analyticsAlgorithmVersion": timeline["analyticsAlgorithmVersion"],
                "catalogueVersion": timeline["catalogueVersion"],
                "coverage": timeline["coverage"],
                "truncated": timeline["truncated"],
                "ruleCounts": {item["ruleId"]: item["count"] for item in timeline["ruleCounts"]},
                "byRuleAndPlace": dict(sorted(by_zone_rule.items())),
                "crossingTotals": [
                    {
                        "line": line["name"],
                        line["aToBLabel"]: sum(line["aToBCounts"]),
                        line["bToALabel"]: sum(line["bToACounts"]),
                    }
                    for line in timeline["crossingCounts"]
                ],
                "crossingCountsEqualStage3Aggregate": crossing_counts_equal,
                "events": [
                    {k: event[k] for k in ("eventId", "ruleId", "startUtc", "endUtc", "startOffsetMs", "endOffsetMs",
                                           "primaryTrackId", "objectClass", "zoneName", "lineName", "directionLabel",
                                           "participantCount")}
                    for event in timeline["events"]
                ],
                "sampleDetails": samples,
            }
        )
    return {
        "schemaVersion": "mavi-poc-s8-events-evidence-v1",
        "api": api,
        "readAtUtc": _iso(datetime.now(timezone.utc)),
        "catalogue": catalogue,
        "clips": clips,
    }


def table(record: dict) -> str:
    rules = [rule["ruleId"] for rule in record["catalogue"]["rules"]]
    lines = ["| Clip | Coverage | " + " | ".join(rules) + " | Crossings = Stage 3 |", "|---" * (len(rules) + 3) + "|"]
    for clip in record["clips"]:
        if not clip.get("videos"):
            lines.append(f"| {clip['code']} | no video | " + " | ".join("-" for _ in rules) + " | - |")
            continue
        coverage = "complete" if clip["coverage"]["complete"] else "INCOMPLETE"
        counts = " | ".join(str(clip["ruleCounts"].get(rule, "off")) for rule in rules)
        lines.append(f"| {clip['code']} | {coverage} | {counts} | {clip['crossingCountsEqualStage3Aggregate']} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    record = collect(args.api)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(record, indent=2, sort_keys=False).encode("utf-8")
    (out / "events-run.json").write_bytes(payload)
    (out / "events-table.md").write_text(table(record) + "\n", encoding="utf-8")
    print(table(record))
    print(f"events-run.json sha256 {hashlib.sha256(payload).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
