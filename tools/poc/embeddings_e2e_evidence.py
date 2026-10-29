"""PoC S4 end-to-end evidence (register rows C5.2-C5.4): what the running platform did with the demo clips.

Reads the platform's own records (PostgreSQL through ``psql``, read-only queries) and its API, and writes one JSON:

* every embedding analysis: status, attempts, Tracks embedded/unavailable, wall time from first claim to completion,
  the worker's provenance (device, execution provider), and the ProcessingRun it belongs to, whose status and
  visibility sequence are compared with the run's own record (an embedding unit never changes them);
* similarity latency at the demo-corpus scale: ``GET /api/tracks/{id}/similar`` for every embedded Track (first page
  and snapshot replay), p50/p95/max, and whether every replay returned the identical ranking;
* appearance-query latency for a fixed list of texts (after their vectors are cached), p50/p95/max;
* ``tracks.entity_id`` is null everywhere and no Entity exists (similarity never writes identity).

    python tools/poc/embeddings_e2e_evidence.py --api http://127.0.0.1:62163 --psql <psql.exe> \
        --database mavi_poc_s4 --out <dir>/e2e-evidence.json   (PGPASSWORD/PGHOST/PGPORT/PGUSER from the environment)
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TEXTS = ["person", "car", "person in a dark jacket", "white car", "person carrying a bag"]


def sql(psql: str, database: str, query: str) -> list[dict]:
    wrapped = f"SELECT coalesce(json_agg(t), '[]'::json) FROM ({query}) t"
    output = subprocess.run([psql, "-X", "-A", "-t", "-d", database, "-c", wrapped], check=True, capture_output=True,
                            text=True, encoding="utf-8").stdout
    return json.loads(output.strip() or "[]")


def get(api: str, path: str) -> tuple[int, dict, float]:
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(api + path, timeout=60) as response:  # noqa: S310 - loopback API only
            body = json.loads(response.read())
            status = response.status
    except urllib.error.HTTPError as error:
        body = json.loads(error.read() or b"{}")
        status = error.code
    return status, body, (time.perf_counter() - started) * 1000


def summary(values: list[float]) -> dict:
    ordered = sorted(values)
    if not ordered:
        return {"count": 0}
    return {"count": len(ordered), "p50Ms": round(statistics.median(ordered), 1),
            "p95Ms": round(ordered[int(0.95 * (len(ordered) - 1))], 1), "maxMs": round(ordered[-1], 1)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", required=True)
    parser.add_argument("--psql", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    analyses = sql(args.psql, args.database, """
        SELECT a.id, a.processing_run_id, a.status, a.attempt_count, a.tracks_embedded, a.tracks_unavailable,
               a.identity_fingerprint, a.model_id, a.model_version,
               extract(epoch FROM (a.completed_at_utc - a.first_claimed_at_utc)) AS wall_seconds,
               a.provenance_json, r.status AS run_status, r.visibility_sequence AS run_visibility,
               (SELECT count(*) FROM tracks t WHERE t.processing_run_id = a.processing_run_id) AS run_tracks,
               (SELECT count(*) FROM observations o JOIN tracks t ON t.id = o.track_id
                 WHERE t.processing_run_id = a.processing_run_id) AS run_crops
        FROM embedding_analyses a JOIN processing_runs r ON r.id = a.processing_run_id ORDER BY a.queued_at_utc""")
    reasons = sql(args.psql, args.database, """
        SELECT outcome, coalesce(unavailable_reason, '') AS reason, count(*) AS tracks
        FROM track_embeddings GROUP BY outcome, unavailable_reason ORDER BY outcome, reason""")
    embedded = [row["track_id"] for row in sql(args.psql, args.database,
                "SELECT track_id FROM track_embeddings WHERE outcome = 'Embedded' ORDER BY track_id")]
    identity = sql(args.psql, args.database,
                   "SELECT count(*) FILTER (WHERE entity_id IS NOT NULL) AS with_entity, count(*) AS tracks, "
                   "(SELECT count(*) FROM entities) AS entities FROM tracks")[0]

    first, replay, stable, cross_camera, examples = [], [], True, 0, []
    for track_id in embedded:
        status, body, elapsed = get(args.api, f"/api/tracks/{track_id}/similar?k=10")
        if status != 200 or body.get("state") != "ready":
            continue
        first.append(elapsed)
        ids = [item["track"]["id"] for item in body["candidates"]]
        snapshot = urllib.parse.quote(body["snapshot"])
        status, again, elapsed = get(args.api, f"/api/tracks/{track_id}/similar?k=10&snapshot={snapshot}")
        replay.append(elapsed)
        stable = stable and status == 200 and [item["track"]["id"] for item in again["candidates"]] == ids
        query_camera = None
        cameras = {item["track"]["cameraCode"] for item in body["candidates"]}
        if body["candidates"]:
            status, detail, _ = get(args.api, f"/api/tracks/{track_id}")
            query_camera = (detail.get("camera") or {}).get("code") if status == 200 else None
            cross_camera += int(any(code != query_camera for code in cameras))
        if len(examples) < 5 and body["candidates"]:
            examples.append({"queryTrackId": track_id, "queryCamera": query_camera, "label": body["label"],
                             "top3": [{"trackId": item["track"]["id"], "camera": item["track"]["cameraCode"],
                                       "objectClass": item["track"]["objectClass"], "score": item["score"]}
                                      for item in body["candidates"][:3]]})

    appearance, appearance_examples = [], []
    for text in TEXTS:
        quoted = urllib.parse.quote(text)
        for _ in range(30):  # the first request queues the text; the worker embeds it
            status, body, elapsed = get(args.api, f"/api/tracks?appearanceQuery={quoted}&limit=20")
            if status != 503:
                break
            time.sleep(1)
        for _ in range(5):
            status, body, elapsed = get(args.api, f"/api/tracks?appearanceQuery={quoted}&limit=20")
            if status == 200:
                appearance.append(elapsed)
        if status == 200:
            appearance_examples.append({"text": text, "label": body["appearance"]["label"],
                                        "top3": [{"trackId": item["id"], "camera": item["cameraCode"],
                                                  "objectClass": item["objectClass"], "score": item["appearanceScore"]}
                                                 for item in body["items"][:3]]})

    result = {
        "schemaVersion": "mavi-poc-s4-e2e-evidence-v1",
        "analyses": analyses,
        "trackOutcomes": reasons,
        "embeddedTracks": len(embedded),
        "identity": identity,
        "similar": {"firstPage": summary(first), "snapshotReplay": summary(replay), "replayIdentical": stable,
                    "queriesWithACrossCameraCandidate": cross_camera, "examples": examples},
        "appearance": {"latency": summary(appearance), "examples": appearance_examples},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("trackOutcomes", "embeddedTracks", "identity", "similar")}, indent=2,
                     default=str)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
