"""Stage 4 X1 evaluation: E-B Track coverage of one ``x1_run.py`` arm, under the frozen rules.

Development experiment tooling (owner decision O3, 2026-10-13). Nothing frozen is changed or re-written: the frozen
association policy and rates are read from the frozen Stage-3 association artefact, the plate truth, the E-A
``h_min`` and both pinned instruments are the frozen E-B inputs, and the per-track rule is
``coverage.evaluate_track`` itself.

Each arm's in-process result is projected like a T1 export: Vehicle Tracks only, boxes in single precision (as the
export stores them), trajectories decoded from their sealed bytes (SHA-256 verified), evidence crops verified by
SHA-256 and size before they are read. Track identities are the arm's own (a new ProcessingRun per arm and sequence).

    python tools/benchmarks/plates/x1_eval.py evaluate --arm-dir D --h3 H --truth T --ea EA \
        --instrument SPEC --instrument SPEC --model-root M --out OUT.json
    python tools/benchmarks/plates/x1_eval.py compare --baseline B.json --candidate C.json --frozen-eb EB.json \
        --root-cause RC.json --baseline-dir D --candidate-dir D --out OUT.json
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "src" / "vision")]

from tools.benchmarks.capabilities.plates import coverage, measure  # noqa: E402
from tools.benchmarks.capabilities.vehicle_tracks import association as associations  # noqa: E402
from tools.benchmarks.capabilities.vehicle_tracks import ground_truth as gt_module  # noqa: E402
from tools.benchmarks.capabilities.vehicle_tracks import policy as policies  # noqa: E402
from tools.benchmarks.capabilities.vehicle_tracks import trajectory  # noqa: E402
from tools.benchmarks.capabilities.vehicle_tracks.ground_truth import box as gt_box  # noqa: E402
from tools.benchmarks.capabilities.vehicle_tracks.mavi_tracks import (  # noqa: E402
    SINGLE_PRECISION_TOLERANCE, MaviRun, MaviTrack, Observation)
from tools.benchmarks.core.identity import from_rational, require  # noqa: E402
from tools.benchmarks.plates import cli  # noqa: E402

FROZEN_ASSOCIATION = "results/bea73d13cd76bcd432319cab88a763d2af6139a34c013e2e93b71363a17f9f9b/association.json"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _f32(value: float) -> float:
    return float(np.float32(value))


def _box(box: dict[str, float]) -> tuple[float, float, float, float]:
    return tuple(_f32(box[k]) for k in ("x", "y", "width", "height"))


def _sealed(staging: Path, artefact: dict[str, Any]) -> bytes:
    data = (staging / artefact["storageKey"]).read_bytes()
    require(len(data) == artefact["sizeBytes"] and _sha(data) == artefact["sha256"],
            f"x1_artefact_hash_mismatch:{artefact['storageKey']}")
    return data


def project(result: dict[str, Any], staging: Path, rate: Fraction) -> MaviRun:
    tracks = []
    vehicles = [t for t in result["tracks"] if t["objectClass"] == "vehicle"]
    for track in sorted(vehicles, key=lambda t: str(t["trackId"])):
        observations = sorted(
            (Observation(o["offsetMs"], gt_box(dict(zip(("x", "y", "width", "height"), _box(o["boundingBox"]))),
                                               f"x1_box:{track['trackId']}", SINGLE_PRECISION_TOLERANCE))
             for o in track["observations"]), key=lambda o: o.offset_ms)
        tracks.append(MaviTrack(str(track["trackId"]), trajectory.decode(_sealed(staging, track["trajectory"])),
                                tuple(observations)))
    return MaviRun(result["sequenceId"], result["processingRunId"], rate, tuple(tracks), "", result["videoSha256"],
                   frozenset(t["trajectory"]["sha256"] for t in vehicles), "", "")


def evaluate(arm_dir: Path, h3: Path, truth_path: Path, ea_path: Path, specs: list[Path], model_root: Path
             ) -> dict[str, Any]:
    descriptor_path, source_root = h3 / "desc" / "frozen.json", h3 / "src"
    document, descriptor_sha, entries = cli._reconciled(descriptor_path, source_root)
    truth, truth_sha = cli._truth(truth_path, descriptor_sha)
    ea, _, ea_sha = cli.read_artefact(ea_path, cli.RESULT, "plate_result_invalid")
    h_min = ea["summary"]["hMin"]["hMinPx"]
    frozen_path = h3 / FROZEN_ASSOCIATION
    frozen = json.loads(frozen_path.read_bytes())
    policy = policies.load(frozen["policy"])
    labelled = from_rational(frozen["alignment"]["labelledRate"], "x1")
    source = from_rational(frozen["alignment"]["sourceRate"], "x1")
    labelled_mode = associations.labelled_rate_mode(document, source, labelled)
    loaded, spec_shas = cli._instruments(specs, model_root)
    frames_by_track: dict[tuple[str, str], list[coverage.PlateFrame]] = {}
    for item in truth["items"]:
        def load_native(path: str = item["imagePath"]) -> Any:
            return measure.decode_image(cli.descriptors.read_verified(entries, source_root, path))
        for plate in item["plates"]:
            frames_by_track.setdefault((item["sequenceId"], item["gtTrackId"]), []).append(
                coverage.PlateFrame(item["frameIndex"], plate, load_native))
    index = json.loads((arm_dir / "index.json").read_bytes())
    rows, association_entries = [], []
    for sequence in sorted(index["results"]):
        raw = (arm_dir / "results" / f"{sequence}.json").read_bytes()
        require(_sha(raw) == index["results"][sequence], f"x1_result_hash_mismatch:{sequence}")
        result = json.loads(raw)
        staging = arm_dir / "staging" / sequence
        gt_document = json.loads((h3 / "derived" / "sequences" / sequence / "ground-truth.json").read_bytes())
        entry, _, _ = associations.associate_sequence(gt_module.project(gt_document), project(result, staging, source),
                                                      policy, labelled, labelled_mode)
        association_entries.append(entry)
        observations: dict[str, list[coverage.EvidenceObservation]] = {}
        for track in result["tracks"]:
            if track["objectClass"] != "vehicle":
                continue
            for o in track["observations"]:
                def load(artefact: dict[str, Any] = o["crop"]) -> bytes:
                    return _sealed(staging, artefact)
                observations.setdefault(str(track["trackId"]), []).append(coverage.EvidenceObservation(
                    o["role"], o["rank"], o["sourceFrameNumber"], _box(o["boundingBox"]), load))
        size = (gt_document["frameSize"]["width"], gt_document["frameSize"]["height"])
        for gt_id, (state, mavi_id) in sorted(coverage.association_states(entry).items()):
            if state == "ignoredGt":
                continue
            frames = frames_by_track.get((sequence, gt_id), [])
            usable = any(frame.plate["textUsable"] for frame in frames)
            result_row = coverage.evaluate_track(frames, observations.get(mavi_id) if mavi_id else None, size,
                                                 loaded, h_min) if usable else None
            rows.append({"sequenceId": sequence, "gtTrackId": gt_id, "state": state, "maviTrackId": mavi_id,
                         "usablePlate": usable, "result": result_row})
        print(f"evaluated {sequence}", flush=True)
    ids = [instrument.instrument_id for instrument in loaded]
    return {"kind": "x1-track-coverage", "arm": index["arm"], "rule": index.get("rule"),
            "inputs": {"armIndex": _sha((arm_dir / "index.json").read_bytes()), "truth": truth_sha,
                       "descriptor": descriptor_sha, "encodingLoss": ea_sha,
                       "frozenAssociation": _sha(frozen_path.read_bytes()), "instrumentSpecs": sorted(spec_shas)},
            "instruments": [instrument.identity() for instrument in loaded],
            "association": association_entries, "rows": rows,
            "summary": {"hMinPx": h_min, **coverage.summarise(rows, ids)}}


# compare

def _key(row: dict[str, Any]) -> tuple[str, str]:
    return row["sequenceId"], row["gtTrackId"]


def _oracle(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {_key(r): r for r in rows if r["usablePlate"] and r["result"]["oracleReadable"]}


def _observations(arm_dir: Path) -> dict[tuple[str, str, str, int], dict[str, Any]]:
    """(sequence, trackId, role, rank) → observation, for Vehicle Tracks."""
    out = {}
    for path in sorted((arm_dir / "results").glob("*.json")):
        result = json.loads(path.read_bytes())
        for track in result["tracks"]:
            if track["objectClass"] == "vehicle":
                for o in track["observations"]:
                    out[(result["sequenceId"], str(track["trackId"]), o["role"], o["rank"])] = o
    return out


def _qualification(arm_dir: Path) -> dict[tuple[str, str, int], dict[str, Any]]:
    out = {}
    for path in sorted((arm_dir / "candidates").glob("*.jsonl.gz")):
        sequence = path.name[:-len(".jsonl.gz")]
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                out[(sequence, str(row["track_id"]), row["frame"])] = row
    return out


def compare(baseline: dict[str, Any], candidate: dict[str, Any], frozen_eb: dict[str, Any], root_cause: dict[str, Any],
            baseline_dir: Path, candidate_dir: Path) -> dict[str, Any]:
    b_oracle, c_oracle = _oracle(baseline["rows"]), _oracle(candidate["rows"])
    evaluated = {row["sequenceId"] for row in baseline["rows"]}
    f_oracle = _oracle([row for row in frozen_eb["rows"] if row["sequenceId"] in evaluated])
    require(set(b_oracle) == set(c_oracle), "x1_oracle_population_differs")

    def readable(rows, key):
        return rows[key]["result"]["evidenceReadable"]

    def matched_c(oracle):
        matched = [k for k, r in oracle.items() if r["state"] == "matched"]
        return {"numerator": sum(readable(oracle, k) for k in matched), "denominator": len(matched)}

    selection = [(x["sequenceId"], x["gtTrackId"]) for x in root_cause["matchedNotReadable"]
                 if x["cause"].startswith("selection: every")]
    recovered = [k for k in selection if k in c_oracle and readable(c_oracle, k)]
    regressions = sorted(k for k in b_oracle if readable(b_oracle, k) and not readable(c_oracle, k))
    gains = sorted(k for k in b_oracle if not readable(b_oracle, k) and readable(c_oracle, k))
    state_changes = sorted(k for k in b_oracle if b_oracle[k]["state"] != c_oracle[k]["state"])
    frozen_diff = sorted(k for k in set(f_oracle) | set(b_oracle)
                         if k not in f_oracle or k not in b_oracle or readable(f_oracle, k) != readable(b_oracle, k)
                         or f_oracle[k]["state"] != b_oracle[k]["state"])

    # Negative controls on the evidence itself: every Vehicle observation whose crop changed.
    b_obs, c_obs = _observations(baseline_dir), _observations(candidate_dir)
    b_q, c_q = _qualification(baseline_dir), _qualification(candidate_dir)
    changed = []
    for key in sorted(set(b_obs) | set(c_obs)):
        old, new = b_obs.get(key), c_obs.get(key)
        if old and new and old["crop"]["sha256"] == new["crop"]["sha256"]:
            continue
        sequence, track = key[0], key[1]

        def describe(o, q):
            if o is None:
                return None
            box = o["boundingBox"]
            row = q.get((sequence, track, o["sourceFrameNumber"]), {})
            return {"frame": o["sourceFrameNumber"], "confidence": o["confidence"], "qualityMicro": o["qualityMicro"],
                    "cropBytes": o["crop"]["sizeBytes"], "boxArea": box["width"] * box["height"],
                    "bottomGap": 1.0 - (box["y"] + box["height"]), "sharpness": row.get("sharpness"),
                    "qualifiedInArm": row.get("qualified")}
        changed.append({"sequenceId": sequence, "trackId": track, "role": key[2], "rank": key[3],
                        "baseline": describe(old, b_q), "candidate": describe(new, c_q)})
    present = [c for c in changed if c["baseline"] and c["candidate"]]

    def share(predicate):
        return sum(1 for c in present if predicate(c)), len(present)

    labelled_tracks = {(r["sequenceId"], r["maviTrackId"]) for r in candidate["rows"] if r["maviTrackId"]}
    evidence_rows = {}
    for row in candidate["rows"]:
        if row["result"] and row["maviTrackId"]:
            for e in row["result"]["evidence"]:
                evidence_rows[(row["sequenceId"], row["maviTrackId"], e["role"], e["rank"])] = e
    changed_labelled = [c for c in changed if (c["sequenceId"], c["trackId"]) in labelled_tracks and c["candidate"]]
    labelled_outcomes: dict[str, int] = {}
    for c in changed_labelled:
        e = evidence_rows.get((c["sequenceId"], c["trackId"], c["role"], c["rank"]))
        outcome = "not-evaluated" if e is None else e.get("skipped") or (
            "read" if any(r.get("agreement") is True for r in e["reads"].values()) else "not-read")
        labelled_outcomes[outcome] = labelled_outcomes.get(outcome, 0) + 1

    def ratio(summary):
        return {"numerator": summary["rEvidence"], "denominator": summary["rOracle"]}

    return {
        "kind": "x1-comparison", "rule": candidate["rule"],
        "inputs": {"baseline": baseline["inputs"], "candidate": candidate["inputs"]},
        "theoreticalMaximum": {"recoverable": len(selection), "bestCoverage": {"numerator": 51 + len(selection),
                                                                               "denominator": 77},
                               "note": "61/77 = 0.792 is MARGINAL (0.70 <= C < 0.80), not ADEQUATE"},
        "frozen": ratio(frozen_eb["summary"]),
        "baseline": {"coverage": ratio(baseline["summary"]), "matchedTrackCoverage": matched_c(b_oracle),
                     "byInstrument": baseline["summary"]["coverageByInstrument"]},
        "candidate": {"coverage": ratio(candidate["summary"]), "matchedTrackCoverage": matched_c(c_oracle),
                      "byInstrument": candidate["summary"]["coverageByInstrument"]},
        "baselineVsFrozenDifferences": [list(k) for k in frozen_diff],
        "selectionFailures": [{"track": list(k), "recovered": k in recovered} for k in selection],
        "recovered": len(recovered), "gains": [list(k) for k in gains], "regressions": [list(k) for k in regressions],
        "associationStateChanges": [list(k) for k in state_changes],
        "evidence": {
            "vehicleObservationsBaseline": len(b_obs), "vehicleObservationsCandidate": len(c_obs),
            "changedObservations": len(changed), "changedOnLabelledTracks": len(changed_labelled),
            "changedOnLabelledTracksOutcome": dict(sorted(labelled_outcomes.items())),
            "changedPresentInBoth": len(present),
            "candidateTouchesBottom": share(lambda c: c["candidate"]["bottomGap"] <= 0.005),
            "candidateLowerConfidence": share(lambda c: c["candidate"]["confidence"] < c["baseline"]["confidence"]),
            "candidateLowerQualityMicro": share(lambda c: c["candidate"]["qualityMicro"] < c["baseline"]["qualityMicro"]),
            "candidateSmallerCrop": share(lambda c: c["candidate"]["cropBytes"] < c["baseline"]["cropBytes"]),
            "candidateLowerSharpness": share(lambda c: (c["candidate"]["sharpness"] or 0) < (c["baseline"]["sharpness"] or 0)),
            "candidateUnqualified": sum(1 for c in changed if c["candidate"] and c["candidate"]["qualifiedInArm"] is False),
            "changes": changed}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    e = sub.add_parser("evaluate")
    e.add_argument("--arm-dir", type=Path, required=True)
    e.add_argument("--h3", type=Path, required=True)
    e.add_argument("--truth", type=Path, required=True)
    e.add_argument("--ea", type=Path, required=True)
    e.add_argument("--instrument", type=Path, action="append", required=True)
    e.add_argument("--model-root", type=Path, required=True)
    e.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("compare")
    for name in ("baseline", "candidate", "frozen-eb", "root-cause", "baseline-dir", "candidate-dir", "out"):
        c.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "evaluate":
        document = evaluate(args.arm_dir, args.h3, args.truth, args.ea, args.instrument, args.model_root)
    else:
        def load(path):
            return json.loads(Path(path).read_bytes())
        document = compare(load(args.baseline), load(args.candidate), load(args.frozen_eb), load(args.root_cause),
                           args.baseline_dir, args.candidate_dir)
    require(not args.out.exists(), f"x1_output_exists:{args.out}")
    data = json.dumps(document, indent=1, sort_keys=True, default=str).encode("utf-8")
    args.out.write_bytes(data)
    print(f"{args.out} sha256={_sha(data)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
