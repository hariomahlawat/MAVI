"""PoC S9 (register C8.1, C8.2): read-only evidence of the structured query contract on the demo corpus.

Development tooling only, standard library only, loopback API only. It creates nothing and reads no media; every
number is pipeline output, not ground truth.

``protocol`` writes the predeclared latency protocol (the query set, repetitions and budget) before anything is
measured, so the budget cannot be fitted to the result. ``run`` then:

1. **Cross-checks** the contract against the read surfaces it reuses, on every demo camera over its own recording
   window: Track ``count`` equals the number of Tracks Track search pages through; Event ``count`` and ``groupBy rule``
   equal the events timeline's rule counts; on every enabled trip line the Event ``count`` per direction equals the
   Stage 3 aggregate.
2. **Measures latency** of the predeclared query set (every unit and every operation) at the corpus's real scale:
   warm-up requests, then sequential timed repetitions of each, client wall time over loopback HTTP. Each query's
   envelopes must be identical across repetitions once the snapshot block is removed (determinism).

    python tools/poc/query_e2e_evidence.py protocol --out <dir>
    python tools/poc/query_e2e_evidence.py run --api http://127.0.0.1:62199 --out <dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEMO_PREFIX = "POC-S2-"
CONTRACT = "mavi-query-v1"
WARMUP = 2
REPETITIONS = 20
# Predeclared (written by `protocol` before any measurement): the 95th percentile of every query's client wall time on
# the Development laptop, loopback, one request at a time. A Development observation, not a performance qualification.
BUDGET_P95_MS = 1000.0
BUCKETS = (60, 300, 900, 3600, 21600, 86400)
MAXIMUM_BUCKETS = 512


def _opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _check(api: str) -> None:
    if urllib.parse.urlparse(api).hostname not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("REFUSED: the API must be loopback")


def get(api: str, path: str):
    _check(api)
    with _opener().open(api.rstrip("/") + path, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def post_query(api: str, query: dict) -> tuple[int, dict, float]:
    """One query: (status, body, elapsed milliseconds of the whole request and response read)."""
    _check(api)
    request = urllib.request.Request(
        api.rstrip("/") + "/api/query",
        data=json.dumps(query).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with _opener().open(request, timeout=120) as response:
            body = response.read()
            status = response.status
    except urllib.error.HTTPError as error:
        body = error.read()
        status = error.code
    elapsed = (time.perf_counter() - started) * 1000.0
    return status, json.loads(body.decode("utf-8")), elapsed


def iso(instant: datetime) -> str:
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def recording_window(videos: list[dict]) -> tuple[str, str]:
    """The recordings' span, snapped outward to whole minutes (the Events page's default)."""
    start = min(parse(v["recordingStartUtc"]) for v in videos).timestamp()
    end = max(parse(v["recordingEndUtc"]) for v in videos).timestamp()
    start = math.floor(start / 60) * 60
    end = math.ceil(end / 60) * 60
    return iso(datetime.fromtimestamp(start, timezone.utc)), iso(datetime.fromtimestamp(end, timezone.utc))


def bucket_for(from_utc: str, to_utc: str) -> int:
    span = (parse(to_utc) - parse(from_utc)).total_seconds()
    return next(size for size in BUCKETS if math.ceil(span / size) <= MAXIMUM_BUCKETS)


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile: the smallest value with at least ``fraction`` of the values at or below it."""
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


def stable(envelope: dict) -> str:
    """The envelope without its snapshot block: what must not change between repetitions."""
    copy = dict(envelope)
    copy.pop("snapshot", None)
    return json.dumps(copy, sort_keys=True, separators=(",", ":"))


def query(unit: str, window: tuple[str, str], operation: dict, **where) -> dict:
    return {
        "contractVersion": CONTRACT,
        "unit": unit,
        "where": {"timeWindow": {"fromUtc": window[0], "toUtc": window[1]}, **where},
        "operation": operation,
    }


# --- The predeclared latency set ----------------------------------------------------------------------------------

LATENCY_SET = [
    # (name, unit, operation, extra where, scope) where scope is "corpus" (every camera, the corpus window) or a clip
    # id (one camera over its own window, with its first enabled line or zone where named).
    ("track-find-200", "track", {"op": "find", "limit": 200}, {}, "corpus"),
    ("track-count", "track", {"op": "count"}, {}, "corpus"),
    ("track-count-distinct-camera", "track", {"op": "countDistinct", "field": "camera"}, {}, "corpus"),
    ("track-group-by-class", "track", {"op": "groupBy", "by": "objectClass"}, {}, "corpus"),
    ("track-top-5-cameras-vehicles", "track", {"op": "top", "by": "camera", "k": 5}, {"objectClass": "Vehicle"}, "corpus"),
    ("track-time-bucket", "track", {"op": "timeBucket"}, {}, "corpus"),
    ("track-first", "track", {"op": "first"}, {}, "corpus"),
    ("track-last", "track", {"op": "last"}, {}, "corpus"),
    ("track-compare-previous-window", "track", {"op": "compare"}, {}, "corpus"),
    ("track-line-a-to-b-hourly-s2-04", "track", {"op": "timeBucket", "bucketSeconds": 3600}, {"line": "aToB"}, "s2-04"),
    ("track-zone-count-s2-08", "track", {"op": "count"}, {"zone": True}, "s2-08"),
    ("event-find-200", "event", {"op": "find", "limit": 200}, {}, "corpus"),
    ("event-count", "event", {"op": "count"}, {}, "corpus"),
    ("event-group-by-rule", "event", {"op": "groupBy", "by": "rule"}, {}, "corpus"),
    ("event-top-5-cameras", "event", {"op": "top", "by": "camera", "k": 5}, {}, "corpus"),
    ("event-count-distinct-track", "event", {"op": "countDistinct", "field": "track"}, {}, "corpus"),
    ("event-crossings-time-bucket-s2-04", "event", {"op": "timeBucket"}, {"ruleIds": ["line-crossing"], "line": "any"}, "s2-04"),
    ("entity-count", "entity", {"op": "count"}, {}, "corpus"),
    ("track-attributes-count", "track", {"op": "count"}, {"attributes": [{"type": "upper-colour", "value": "red"}]}, "corpus"),
    ("track-plate-count", "track", {"op": "count"}, {"plateText": {"text": "AB1", "match": "contains"}}, "corpus"),
]


def write_protocol(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / "latency-protocol.json"
    path.write_text(json.dumps({
        "schema": "mavi-poc-s9-latency-protocol-v1",
        "contract": CONTRACT,
        "writtenAtUtc": iso(datetime.now(timezone.utc)),
        "warmup": WARMUP,
        "repetitions": REPETITIONS,
        "budget": {"statistic": "p95 nearest-rank, client wall time, loopback HTTP, sequential", "milliseconds": BUDGET_P95_MS},
        "determinism": "every repetition of a query returns the same envelope once the snapshot block is removed",
        "set": [{"name": n, "unit": u, "operation": o, "where": w, "scope": s} for n, u, o, w, s in LATENCY_SET],
        "note": "Development observation on the Development laptop (ADR-020); not a performance qualification.",
    }, indent=2) + "\n", encoding="utf-8")
    return path


# --- Run ------------------------------------------------------------------------------------------------------------

def _clip_scope(api: str, cameras: list[dict], videos: list[dict], clip: str):
    camera = next(c for c in cameras if c["code"].lower().startswith((DEMO_PREFIX + clip.split("-")[1]).lower()))
    own = [v for v in videos if v["cameraId"].lower() == camera["id"].lower()]
    scene = get(api, f"/api/cameras/{camera['id']}/scene")
    return camera, recording_window(own), scene["activeRevision"]


def materialise(api: str, name: str, unit: str, operation: dict, where: dict, scope: str, cameras, videos, corpus):
    operation = dict(operation)
    where = dict(where)
    if scope == "corpus":
        # Every demo camera, by id: a Development database may hold other cameras, which the corpus does not include.
        window = corpus
        where["cameraIds"] = sorted(camera["id"].lower() for camera in cameras)
    else:
        camera, window, revision = _clip_scope(api, cameras, videos, scope)
        where["cameraIds"] = [camera["id"].lower()]
        if "line" in where:
            line = next(item for item in revision["tripLines"] if item["enabled"])
            where["line"] = {"lineId": line["lineId"]} if where["line"] == "any" else {"lineId": line["lineId"], "direction": where["line"]}
        if where.get("zone") is True:
            zone = next(item for item in revision["zones"] if item["enabled"])
            where["zone"] = {"zoneId": zone["zoneId"]}
    if operation["op"] == "timeBucket" and "bucketSeconds" not in operation:
        operation["bucketSeconds"] = bucket_for(*window)
    if operation["op"] == "compare":
        start, end = parse(window[0]), parse(window[1])
        operation["baseline"] = {"fromUtc": iso(start - (end - start)), "toUtc": iso(start)}
    return query(unit, window, operation, **where)


EXPECTED_KIND = {
    "find": "rows", "first": "rows", "last": "rows", "count": "value", "countDistinct": "value",
    "groupBy": "groups", "top": "groups", "timeBucket": "buckets", "compare": "comparison",
}


def kind_as_expected(query_body: dict, envelope: dict) -> bool:
    """The answer is the kind its operation implies, not merely a 200.

    The Entity unit answers ``empty`` (no Entity data before S7). A whole-scope answer may be ``withheld`` only when
    every incomplete coverage component says why with a not-configured reason, the expected state of a capability this
    runtime does not run; any other withheld answer, or a mismatched kind, is a failed measurement.
    """
    kind = (envelope.get("result") or {}).get("kind")
    if query_body["unit"] == "entity":
        return kind == "empty"
    if kind == "withheld":
        incomplete = [c for c in (envelope.get("coverage") or {}).get("components", []) if not c.get("complete")]
        return bool(incomplete) and all(str(c.get("reason") or "").endswith("not_configured") for c in incomplete)
    return kind == EXPECTED_KIND[query_body["operation"]["op"]]


def measure(api: str, queries: list[tuple[str, dict]]) -> list[dict]:
    rows = []
    for name, body in queries:
        for _ in range(WARMUP):
            post_query(api, body)
        timings, statuses, shapes = [], set(), set()
        first = None
        for _ in range(REPETITIONS):
            status, envelope, elapsed = post_query(api, body)
            timings.append(elapsed)
            statuses.add(status)
            shapes.add(stable(envelope))
            first = first or envelope
        rows.append({
            "name": name,
            "query": body,
            "statuses": sorted(statuses),
            "deterministic": len(shapes) == 1,
            "p50Ms": round(statistics.median(timings), 1),
            "p95Ms": round(percentile(timings, 0.95), 1),
            "maxMs": round(max(timings), 1),
            "withinBudget": percentile(timings, 0.95) <= BUDGET_P95_MS,
            "kindAsExpected": isinstance(first, dict) and kind_as_expected(body, first),
            "resultKind": (first.get("result") or {}).get("kind") if isinstance(first, dict) else None,
            "coverageComplete": (first.get("coverage") or {}).get("complete") if isinstance(first, dict) else None,
            "envelope": first,
        })
    return rows


def _paged_track_count(api: str, camera_id: str, window: tuple[str, str]) -> int:
    total, cursor = 0, None
    while True:
        params = {"cameraId": camera_id, "fromUtc": window[0], "toUtc": window[1], "limit": 100}
        if cursor:
            params["cursor"] = cursor
        page = get(api, "/api/tracks?" + urllib.parse.urlencode(params))
        total += len(page["items"])
        cursor = page.get("nextCursor")
        if not cursor:
            return total


def crosscheck(api: str, cameras: list[dict], videos: list[dict]) -> list[dict]:
    rows = []
    for camera in cameras:
        own = [v for v in videos if v["cameraId"].lower() == camera["id"].lower()]
        if not own:
            continue
        window = recording_window(own)
        ids = [camera["id"].lower()]
        bucket = bucket_for(*window)
        _, track_count, _ = post_query(api, query("track", window, {"op": "count"}, cameraIds=ids))
        _, by_rule, _ = post_query(api, query("event", window, {"op": "groupBy", "by": "rule"}, cameraIds=ids))
        timeline = get(api, f"/api/cameras/{camera['id']}/events?" + urllib.parse.urlencode(
            {"fromUtc": window[0], "toUtc": window[1], "bucketSeconds": bucket, "limit": 5000}))
        aggregate = get(api, f"/api/cameras/{camera['id']}/analytics/aggregates?" + urllib.parse.urlencode(
            {"fromUtc": window[0], "toUtc": window[1], "bucketSeconds": bucket}))
        searched = _paged_track_count(api, camera["id"], window)
        # The timeline lists every rule that ran, with its zero; groupBy has a group only where a record exists. Under
        # complete coverage an absent group is that zero, so the two agree when the timeline's non-zero counts do.
        timeline_rules = {item["ruleId"]: item["count"] for item in timeline["ruleCounts"] if item["count"] > 0}
        query_rules = {group["key"]: group["count"] for group in (by_rule["result"].get("groups") or [])}
        events_complete = by_rule["coverage"]["complete"] and timeline["coverage"]["complete"]
        lines = []
        for line in aggregate.get("lines", []):
            counts = {}
            line_complete = True
            for direction in ("aToB", "bToA"):
                _, answer, _ = post_query(api, query(
                    "event", window, {"op": "count"}, cameraIds=ids, ruleIds=["line-crossing"],
                    line={"lineId": line["lineId"], "direction": direction}))
                counts[direction] = answer["result"].get("value")
                line_complete = line_complete and answer["coverage"]["complete"]
            stage3 = {"aToB": sum(line["aToBCounts"]), "bToA": sum(line["bToACounts"])}
            # Equal only as an answer: a withheld count (incomplete coverage) never agrees, whatever it is compared with.
            lines.append({"lineId": line["lineId"], "query": counts, "stage3": stage3, "coverageComplete": line_complete,
                          "equal": line_complete and counts == stage3})
        rows.append({
            "code": camera["code"],
            "window": window,
            "trackCount": {"query": track_count["result"].get("value"), "trackSearch": searched,
                           "coverageComplete": track_count["coverage"]["complete"],
                           "equal": track_count["coverage"]["complete"] and track_count["result"].get("value") == searched},
            # A withheld groupBy has no groups and an incomplete timeline may list none: two empty maps are not agreement.
            "eventsByRule": {"query": query_rules, "timeline": timeline_rules, "coverageComplete": events_complete,
                             "equal": events_complete and query_rules == timeline_rules},
            "crossings": lines,
        })
    return rows


def run(api: str, out: Path) -> int:
    protocol = out / "latency-protocol.json"
    if not protocol.is_file():
        raise SystemExit("REFUSED: write the predeclared protocol first (`protocol --out`).")
    contract = get(api, "/api/query/contract")
    cameras = sorted((c for c in get(api, "/api/cameras/") if c["code"].startswith(DEMO_PREFIX)), key=lambda c: c["code"])
    camera_ids = {c["id"].lower() for c in cameras}
    videos = [v for v in get(api, "/api/videos") if v["cameraId"].lower() in camera_ids]
    corpus = recording_window(videos)

    checks = crosscheck(api, cameras, videos)
    queries = [(n, materialise(api, n, u, o, w, s, cameras, videos, corpus)) for n, u, o, w, s in LATENCY_SET]
    latency = measure(api, queries)

    record = {
        "schema": "mavi-poc-s9-query-run-v1",
        "api": api,
        "contractVersion": contract["contractVersion"],
        "protocolSha256": hashlib.sha256(protocol.read_bytes()).hexdigest(),
        "host": {"platform": platform.platform(), "python": platform.python_version()},
        "measuredAtUtc": iso(datetime.now(timezone.utc)),
        "corpus": {"cameras": len(cameras), "videos": len(videos), "window": corpus},
        "crosscheck": checks,
        "latency": latency,
    }
    (out / "query-run.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    print(f"{'clip':<12} {'tracks q/search':>16} {'events by rule':>15} {'crossings = Stage 3':>20}")
    for row in checks:
        crossings = "n/a" if not row["crossings"] else ("yes" if all(item["equal"] for item in row["crossings"]) else "NO")
        print(f"{row['code']:<12} {str(row['trackCount']['query']) + '/' + str(row['trackCount']['trackSearch']):>16} "
              f"{'equal' if row['eventsByRule']['equal'] else 'DIFFER':>15} {crossings:>20}")
    print(f"\n{'query':<36} {'kind':<10} {'p50':>8} {'p95':>8} {'max':>8}  det  budget")
    for row in latency:
        print(f"{row['name']:<36} {str(row['resultKind']):<10} {row['p50Ms']:>8} {row['p95Ms']:>8} {row['maxMs']:>8}  "
              f"{'yes' if row['deterministic'] else 'NO':<4} {'ok' if row['withinBudget'] else 'OVER'}"
              f"{'' if row['kindAsExpected'] else '  UNEXPECTED KIND'}")

    agree = all(r["trackCount"]["equal"] and r["eventsByRule"]["equal"] and all(c["equal"] for c in r["crossings"]) for r in checks)
    within = all(r["withinBudget"] and r["deterministic"] and r["statuses"] == [200] and r["kindAsExpected"] for r in latency)
    print(f"\ncross-checks agree: {agree}; latency within budget, deterministic and of the expected kind: {within}")
    return 0 if agree and within else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="query_e2e_evidence")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("protocol")
    p.add_argument("--out", required=True, type=Path)
    r = sub.add_parser("run")
    r.add_argument("--api", required=True)
    r.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "protocol":
        print(write_protocol(args.out))
        return 0
    return run(args.api, args.out)


if __name__ == "__main__":
    sys.exit(main())
