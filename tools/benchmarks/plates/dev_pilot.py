"""Issue #225 Development ANPR pilot: measure plate search and attribute failures on the pilot's real MAVI runs.

Development diagnostics only — not a selection, qualification or acceptance measurement, and never a substitute for
the frozen E-B result. Inputs are the pilot's own runs on a dedicated catalogue: the T1 export of each processing
run (with its sealed evidence crops and trajectories), the R8 human-reviewed sequence truth, the derived H3 sequences'
canonical ground truth, and the live product API (Track detail ``plates`` and ``GET /api/tracks?plateText=``).

Per ground-truth track with a text-usable plate, the predeclared first-matching cause (the pilot checkpoint records
the order before any plate output existed):

1. ``track_association`` — association (frozen POLICY_V1) left the GT track without exactly one MAVI Track;
2. ``evidence_unavailable`` — the run's plate readiness is not Ready, or the Track outcome is Unavailable;
3. ``search_hit`` (success) — the exact search for the normalised R8 text returns the associated Track;
4. ``searchable_text_missing`` — a kept reading normalises to the truth, yet the search does not return the Track;
5. ``source_evidence`` — no evidence crop is readable by the frozen instruments from the R8 geometry
   (``coverage.evaluate_track``, ``h_min``); sub-cause ``unmeasurable`` when no crop had a label inside it;
6. ``detector_miss`` — an evidence-readable crop exists, but in none of them does the selected plate box cover at
   least half of the mapped truth rectangle;
7. ``ocr_error`` — otherwise: the detector selected the plate and the reading was wrong or unreadable.

Run with the Stage-4 instrument environment (tools/benchmarks/plates/requirements-instruments.txt) and
PYTHONPATH=<repo>;<repo>/src/vision.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
from collections import Counter
from fractions import Fraction
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools/stage3"))

from tools.benchmarks.capabilities.plates import coverage, measure, truth as truths  # noqa: E402
from tools.benchmarks.capabilities.plates import instruments as instrument_module  # noqa: E402
from tools.benchmarks.capabilities.vehicle_tracks import association as associations  # noqa: E402
from tools.benchmarks.capabilities.vehicle_tracks import ground_truth as gt_module  # noqa: E402
from tools.benchmarks.capabilities.vehicle_tracks import mavi_tracks, policy as policies  # noqa: E402
from tools.benchmarks.core._stage3 import artefacts  # noqa: E402
from tools.benchmarks.plates import cli as pilot_cli  # noqa: E402

import mavi_api  # noqa: E402  (tools/stage3)

from mavi_vision.plates.normalisation import OK, normalise  # noqa: E402

SCHEMA = "mavi-anpr-dev-pilot-result-v1"
LABELLED_RATE = Fraction(5, 1)
DETECTOR_COVERAGE = 0.5


def _get(api: mavi_api.Api, path: str) -> Any:
    status, body = api.call("GET", path)
    if status != 200:
        raise RuntimeError(f"api {path} -> {status}")
    return body


def export_runs(runs: dict[str, str], profile: Path, export_root: Path, export_exe: Path) -> dict[str, Path]:
    paths = {}
    for sequence, run in sorted(runs.items()):
        directory = export_root / run
        if not directory.exists():
            result = subprocess.run([str(export_exe), "--run", run, "--pipeline-profile", str(profile), "--out", str(directory)],
                                    capture_output=True, check=False)
            if result.returncode != 0:
                raise RuntimeError(f"export failed for {run}: {result.stderr.decode(errors='replace')[:400]}")
        paths[sequence] = directory / artefacts.EXPORT_FILE_NAME
    return paths


def _covers(box: dict[str, int], truth_rect: tuple[float, float, float, float]) -> float:
    """Share of the mapped truth rectangle covered by a selected plate box (crop pixels)."""
    left, top, right, bottom = truth_rect
    area = max(0.0, right - left) * max(0.0, bottom - top)
    if area <= 0:
        return 0.0
    ix = max(0.0, min(right, box["x"] + box["width"]) - max(left, box["x"]))
    iy = max(0.0, min(bottom, box["y"] + box["height"]) - max(top, box["y"]))
    return ix * iy / area


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    pilot = Path(args.pilot)
    subset = json.loads((pilot / "subset.json").read_text(encoding="utf-8"))
    journal = json.loads((pilot / "journal.json").read_text(encoding="utf-8"))
    truth = json.loads(Path(args.truth).read_text(encoding="utf-8"))
    derived = Path(args.derived)
    api = mavi_api.Api(args.api)
    sequences = [item["sequenceId"] for item in subset["sequences"]]
    runs = {s: journal["members"][s]["processingRunId"] for s in sequences}
    exports_by_sequence = export_runs(runs, Path(args.pipeline_profile), Path(args.exports), Path(args.export_exe))
    loaded = artefacts.load_exports(list(exports_by_sequence.values()))
    exports = {export.run_id: export for export in loaded.values()}
    instruments = [instrument_module.load(Path(spec), Path(args.instrument_models)) for spec in args.instrument_spec]
    policy = policies.v1()
    evidence_root = Path(args.evidence_root)

    frames_by_track: dict[tuple[str, str], list[coverage.PlateFrame]] = {}
    source_root = Path(args.source_root)
    for item in truth["items"]:
        def load_native(path: str = item["imagePath"]) -> Any:
            return measure.decode_image((source_root / path).read_bytes())
        for plate in item["plates"]:
            frames_by_track.setdefault((item["sequenceId"], item["gtTrackId"]), []).append(
                coverage.PlateFrame(item["frameIndex"], plate, load_native))

    rows, per_sequence, run_rows = [], {}, []
    for sequence in sequences:
        run_id = runs[sequence]
        export = exports[run_id]
        readiness = _get(api, f"/api/processing/runs/{run_id}/plates")
        run_rows.append({"sequenceId": sequence, "processingRunId": run_id, "videoAssetId": journal["members"][sequence]["videoAssetId"],
                         "exportSha256": next(sha for sha, e in loaded.items() if e.run_id == run_id),
                         "plateReadiness": readiness.get("state"), "vehicleTracks": sum(1 for t in export.tracks if t.get("objectClass") == "Vehicle")})
        gt_document = json.loads((derived / "sequences" / sequence / "ground-truth.json").read_text(encoding="utf-8"))
        mavi_run = mavi_tracks.project(export, evidence_root)
        entry, _, _ = associations.associate_sequence(gt_module.project(gt_document), mavi_run, policy, LABELLED_RATE, True)
        states = coverage.association_states(entry)
        rate = mavi_tracks.frame_rate(export)
        size = (export.video["width"], export.video["height"])
        observations: dict[str, list[coverage.EvidenceObservation]] = {}
        for track in export.tracks:
            for item in track["observations"]:
                observations.setdefault(track["id"], []).append(coverage.EvidenceObservation(
                    item["evidenceRole"], item["evidenceRank"], item["sourceFrameNumber"],
                    tuple(item["boundingBox"][k] for k in ("x", "y", "width", "height")),
                    pilot_cli._verified_evidence(export, item)))
        for spec in next(s for s in subset["sequences"] if s["sequenceId"] == sequence)["tracks"]:
            gt_id = spec["gtTrackId"]
            state, mavi_id = states.get(gt_id, ("absent", None))
            frames = frames_by_track.get((sequence, gt_id), [])
            truth_texts = sorted({truths.truth_text(f.plate) for f in frames if f.plate["textUsable"]})
            result = coverage.evaluate_track(frames, observations.get(mavi_id) if mavi_id else None, size, instruments, args.h_min)
            row: dict[str, Any] = {"sequenceId": sequence, "gtTrackId": gt_id, "truthTexts": truth_texts,
                                   "associationState": state, "maviTrackId": mavi_id,
                                   "oracleReadable": result["oracleReadable"], "evidenceReadable": result["evidenceReadable"]}
            row.update(_attribute(api, row, result, frames, observations.get(mavi_id) or [], size, readiness))
            rows.append(row)
        per_sequence[sequence] = {"gtTextTracks": sum(1 for r in rows if r["sequenceId"] == sequence),
                                  "searchHits": sum(1 for r in rows if r["sequenceId"] == sequence and r["cause"] == "search_hit")}

    queries = _search_precision(api, rows)
    summary = _summarise(rows, run_rows, queries)
    return {"schemaVersion": SCHEMA, "note": "Development diagnostics only; not selection, qualification or acceptance evidence.",
            "inputs": {"subsetTruthSha256": subset["truthSha256"], "hMinPx": args.h_min,
                       "instruments": [i.identity() for i in instruments], "associationPolicySha256": policy.sha256},
            "runs": run_rows, "perSequence": per_sequence, "tracks": rows, "queries": queries, "summary": summary}


def _attribute(api, row, result, frames, observations, size, readiness) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if row["associationState"] != "matched":
        return {"cause": "track_association", "subCause": row["associationState"]}
    detail = _get(api, f"/api/tracks/{row['maviTrackId']}")
    plates = detail.get("plates") or {}
    out["plateReadiness"] = plates.get("readiness")
    out["trackOutcome"] = plates.get("trackOutcome")
    out["trackTexts"] = [t["normalisedText"] for t in plates.get("texts") or []]
    plate_observations = plates.get("observations") or []
    out["plateObservations"] = len(plate_observations)
    out["readObservations"] = sum(1 for o in plate_observations if o["outcome"] == "Read")
    out["evidenceObservations"] = len(observations)
    if plates.get("readiness") != "Ready" or plates.get("trackOutcome") != "Analysed":
        return {**out, "cause": "evidence_unavailable", "subCause": plates.get("unavailableReason") or plates.get("readiness")}
    truths_normalised = {t for t in row["truthTexts"]}
    hit = False
    for text in sorted(truths_normalised):
        query = urllib.parse.urlencode({"plateText": text, "plateMatch": "exact", "limit": 100})
        found = _get(api, f"/api/tracks?{query}")
        if any(item["id"] == row["maviTrackId"] for item in found.get("items", [])):
            hit = True
    if hit:
        return {**out, "cause": "search_hit"}
    kept = {r.get("normalisedText") for o in plate_observations for r in o["readings"] if r.get("normalisedText")}
    if kept & truths_normalised:
        return {**out, "cause": "searchable_text_missing"}
    if not result["evidenceReadable"]:
        measured = [e for e in result["evidence"] if "reads" in e]
        return {**out, "cause": "source_evidence", "subCause": "poor" if measured else "unmeasurable",
                "labelledCrops": len(measured)}
    # Evidence-readable crops: did the selected plate box cover the mapped truth rectangle in any of them?
    usable = {f.frame_index: f for f in frames if f.plate["textUsable"]}
    by_frame = {}
    for observation in plate_observations:
        by_frame.setdefault(observation["sourceFrameNumber"], []).append(observation)
    readable_frames = [e["sourceFrameNumber"] for e in result["evidence"]
                       if any(r.get("agreement") is True for r in e.get("reads", {}).values())]
    best = 0.0
    selected_any = False
    for number in readable_frames:
        frame = usable[number]
        crop_obs = next(o for o in observations if o.source_frame_number == number)
        origin = measure.crop_origin(size[0], size[1], coverage._clamped(crop_obs.box))
        for plate in by_frame.get(number, []):
            selected_any = True
            box = plate["box"]
            mapped, _ = measure.map_into_crop(truths.polygon_rect(frame.plate["polygon"]), origin,
                                              (box["cropWidth"], box["cropHeight"]))
            best = max(best, _covers(box, mapped))
    out["bestTruthCoverage"] = round(best, 3)
    if best < DETECTOR_COVERAGE:
        return {**out, "cause": "detector_miss", "subCause": "other_region_selected" if selected_any else "no_plate_selected"}
    return {**out, "cause": "ocr_error"}


def _search_precision(api, rows) -> list[dict[str, Any]]:
    by_text: dict[str, set[str]] = {}
    for row in rows:
        for text in row["truthTexts"]:
            by_text.setdefault(text, set())
            if row.get("maviTrackId") and row["associationState"] == "matched":
                by_text[text].add(row["maviTrackId"])
    queries = []
    for text in sorted(by_text):
        if normalise(text).outcome != OK:
            queries.append({"text": text, "skipped": "truth_not_normalisable"})
            continue
        query = urllib.parse.urlencode({"plateText": text, "plateMatch": "exact", "limit": 100})
        found = _get(api, f"/api/tracks?{query}")
        returned = [item["id"] for item in found.get("items", [])]
        queries.append({"text": text, "returned": len(returned), "correct": len(set(returned) & by_text[text]),
                        "falseMatches": len(set(returned) - by_text[text]), "plateCoverage": found.get("plateCoverage")})
    return queries


def _summarise(rows, run_rows, queries) -> dict[str, Any]:
    causes = Counter(row["cause"] for row in rows)
    oracle = [row for row in rows if row["oracleReadable"]]
    return {"gtTextTracks": len(rows), "causes": dict(sorted(causes.items())),
            "subCauses": dict(sorted(Counter(f"{r['cause']}:{r.get('subCause')}" for r in rows if r.get("subCause")).items())),
            "searchHits": causes.get("search_hit", 0),
            "oracleReadableTracks": len(oracle),
            "oracleReadableCauses": dict(sorted(Counter(row["cause"] for row in oracle).items())),
            "evidenceReadableTracks": sum(1 for row in rows if row["evidenceReadable"]),
            "evidenceReadableOfOracle": sum(1 for row in oracle if row["evidenceReadable"]),
            "matchedTracks": sum(1 for row in rows if row["associationState"] == "matched"),
            "runs": len(run_rows), "runsReady": sum(1 for r in run_rows if r["plateReadiness"] == "Ready"),
            "queries": len([q for q in queries if "skipped" not in q]),
            "queriesSkipped": len([q for q in queries if "skipped" in q]),
            "queriesWithCorrectHit": sum(1 for q in queries if q.get("correct")),
            "falseMatchesTotal": sum(q.get("falseMatches", 0) for q in queries)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pilot", required=True, help="the pilot working directory (subset.json, journal.json)")
    parser.add_argument("--truth", required=True)
    parser.add_argument("--derived", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--api", required=True)
    parser.add_argument("--pipeline-profile", required=True)
    parser.add_argument("--exports", required=True)
    parser.add_argument("--export-exe", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--instrument-spec", action="append", required=True)
    parser.add_argument("--instrument-models", required=True)
    parser.add_argument("--h-min", type=float, default=32.0)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    result = evaluate(args)
    out = Path(args.out)
    if out.exists():
        raise SystemExit("output_exists")
    out.write_text(json.dumps(result, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
