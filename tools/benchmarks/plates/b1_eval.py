"""Stage 4 B1 (#228) evaluation: preflight counters, per-arm O5 evaluation and Track-level gain/loss accounting.

Development experiment tooling. Each arm is verified fail-closed (``b1_run.verify``) before it is read. The
per-arm evaluation is ``x1_eval.evaluate`` itself (frozen association policy, ``coverage.evaluate_track``, pinned
instruments) against the O5 human-reviewed truth and E-A; nothing frozen is re-written.

    python tools/benchmarks/plates/b1_eval.py preflight --inventory INV --arm-dir PREFLIGHT --out P.json
    python tools/benchmarks/plates/b1_eval.py evaluate --inventory INV --arm-dir D --out D-eval.json
    python tools/benchmarks/plates/b1_eval.py account --inventory INV --a A --b B --preflight P --a-eval AE
        --b-eval BE --out ACCOUNT.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
for _p in (ROOT, ROOT / "src" / "vision", ROOT / "tools" / "vision" / "dev", ROOT / "tools" / "benchmarks" / "plates"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import b1_run  # noqa: E402
from b1_run import H3, MODEL_ROOT, PLATES, X1, B1Error, read_log, require, sha_bytes, sha_file  # noqa: E402

O5 = PLATES / "results-human-reviewed"
VEHICLE_ROLES = ("representative", "near-view", "early-diverse", "late-diverse")


def _load(path: Path) -> Any:
    return json.loads(path.read_bytes())


def _logs(arm_dir: Path, kind: str) -> dict[str, list[dict]]:
    index = _load(arm_dir / "index.json")
    key = {"candidates": "candidateLogs", "b1": "b1Logs"}[kind]
    return {s: read_log(arm_dir / kind / f"{s}.jsonl.gz", e) for s, e in sorted(index[key].items())}


def _results(arm_dir: Path) -> dict[str, dict]:
    index = _load(arm_dir / "index.json")
    out = {}
    for s, digest in sorted(index["results"].items()):
        raw = (arm_dir / "results" / f"{s}.json").read_bytes()
        require(sha_bytes(raw) == digest, f"b1_result_mismatch:{s}")
        out[s] = json.loads(raw)
    return out


def shape(result: dict) -> list:
    return [(t["trackId"], t["objectClass"], t["trajectory"]["sha256"],
             [(o["role"], o["rank"], o["sourceFrameNumber"], o["crop"]["sha256"]) for o in t["observations"]])
            for t in result["tracks"]]


# preflight ----------------------------------------------------------------------------------------------------------

def preflight(inventory: Path, arm_dir: Path) -> dict[str, Any]:
    checked = b1_run.verify(arm_dir, inventory)
    index = _load(arm_dir / "index.json")
    require(index["arm"] == "preflight" and index["mode"] == "shadow", "b1_not_preflight_arm")
    c = Counter()
    by_gate = Counter()
    b1_only_tracks, b1_only_sequences, opportunity_tracks = set(), set(), set()
    for s, rows in _logs(arm_dir, "candidates").items():
        for r in rows:
            c["vehicleCandidates"] += 1
            c["nativeHeightAbove128"] += r["native_height_px"] > 128
            if r["pass_sharpness"]:
                continue
            c["failOriginalSharpness"] += 1
            if r["b1_sharpness"] is None:
                c["failOriginalSharpness_b1Undefined_height<=128"] += 1
                continue
            if not r["pass_sharpness_b1"]:
                c["failOriginalSharpness_b1BelowFloor"] += 1
                continue
            c["failOriginal_passB1"] += 1
            blocking = [g for g, ok in (("confidence", r["pass_confidence"]), ("edge", r["pass_edge"]),
                                        ("occlusion", r["pass_occlusion"])) if not ok]
            by_gate["+".join(blocking) or "none"] += 1
            if r["b1_only"]:
                c["threeConditions_b1Only"] += 1
                b1_only_tracks.add((s, str(r["track_id"])))
                b1_only_sequences.add(s)
    shadow = _logs(arm_dir, "b1")
    for s, rows in shadow.items():
        for r in rows:
            c["shadowB1OnlyObserved"] += 1
            c["shadowNearViewOpportunity"] += r["opportunity"]
            c["shadowBlockedNearDuplicateOfRepresentative"] += r["nearDuplicateOfRepresentative"]
            c["shadowBlockedGrowthHysteresis"] += (not r["nearDuplicateOfRepresentative"]) and not r["growthAllows"]
            if r["opportunity"]:
                opportunity_tracks.add((s, r["trackId"]))
    require(c["shadowB1OnlyObserved"] == c["threeConditions_b1Only"], "b1_preflight_shadow_count_differs")
    return {"kind": "b1-preflight", "rule": index["rule"], "armIndexSha256": sha_file(arm_dir / "index.json"),
            "inventorySha256": index["inventorySha256"], "verified": checked,
            "counters": dict(sorted(c.items())), "failOriginalPassB1_blockedBy": dict(sorted(by_gate.items())),
            "b1OnlyTracks": len(b1_only_tracks), "b1OnlySequences": len(b1_only_sequences),
            "nearViewOpportunityTracks": len(opportunity_tracks),
            "stopRuleNull": c["threeConditions_b1Only"] == 0}


# evaluate -----------------------------------------------------------------------------------------------------------

def evaluate(inventory: Path, arm_dir: Path) -> dict[str, Any]:
    import x1_eval

    b1_run.verify(arm_dir, inventory)
    inv = _load(inventory)
    truth, ea = O5 / "truth-val.json", O5 / "ea.json"
    require(sha_file(truth) == inv["o5"]["truth"] and sha_file(ea) == inv["o5"]["ea"], "b1_o5_inputs_changed")
    document = x1_eval.evaluate(arm_dir, H3, truth, ea, b1_run.INSTRUMENT_SPECS, MODEL_ROOT)
    document["kind"] = "b1-track-coverage"
    document["inputs"]["inventory"] = sha_file(inventory)
    return document


# account ------------------------------------------------------------------------------------------------------------

def _key(row: dict) -> tuple[str, str]:
    return row["sequenceId"], row["gtTrackId"]


def _readable(row: dict) -> bool:
    return bool(row["usablePlate"] and row["result"] and row["result"]["evidenceReadable"])


def _oracle(row: dict) -> bool:
    return bool(row["usablePlate"] and row["result"] and row["result"]["oracleReadable"])


def _parity_eb(a_eval: dict, eb: dict) -> dict[str, Any]:
    a = {_key(r): r for r in a_eval["rows"]}
    f = {_key(r): r for r in eb["rows"]}
    differences = sorted(k for k in set(a) | set(f) if k not in a or k not in f
                         or (a[k]["state"], a[k]["usablePlate"], _oracle(a[k]), _readable(a[k]))
                         != (f[k]["state"], f[k]["usablePlate"], _oracle(f[k]), _readable(f[k])))
    return {"rowsArmA": len(a), "rowsEb": len(f), "differences": [list(k) for k in differences],
            "armA": [a_eval["summary"]["rEvidence"], a_eval["summary"]["rOracle"]],
            "eb": [eb["summary"]["rEvidence"], eb["summary"]["rOracle"]]}


def _platform_parity(a_results: dict[str, dict]) -> dict[str, Any]:
    from tools.stage3 import artefacts

    exports = artefacts.load_exports(sorted((H3 / "exec" / "exports").rglob("*.json")))
    by_run = {e.run_id: e for e in exports.values()}
    association = json.loads(next((H3 / "results").rglob("association.json")).read_bytes())
    run_of = {e["sequenceId"]: e["processingRunId"] for e in association["sequences"]}
    different = []
    for s, result in a_results.items():
        export = by_run.get(run_of.get(s))
        platform = Counter(o["evidenceSha256"] for t in export.tracks for o in t["observations"]) if export else None
        mine = Counter(o["crop"]["sha256"] for t in result["tracks"] for o in t["observations"])
        if platform != mine:
            different.append(s)
    return {"identical": len(a_results) - len(different), "different": different}


def _by_role(track: dict) -> dict[str, dict]:
    return {o["role"]: o for o in track["observations"]}


def _evidence_entries(eval_doc: dict) -> dict[tuple[str, str, str], dict]:
    out = {}
    for row in eval_doc["rows"]:
        if row["result"] and row["maviTrackId"]:
            for e in row["result"]["evidence"]:
                out[(row["sequenceId"], str(row["maviTrackId"]), e["role"])] = e
    return out


def _outcome(entry: dict | None) -> str:
    if entry is None:
        return "track-not-evaluated (no usable plate or unassociated)"
    if "skipped" in entry:
        return f"unmeasurable:{entry['skipped']}"
    return "read" if any(r.get("agreement") is True for r in entry["reads"].values()) else "not-read"


def account(inventory: Path, a_dir: Path, b_dir: Path, p_dir: Path, a_eval_path: Path, b_eval_path: Path
            ) -> dict[str, Any]:
    inv = _load(inventory)
    verified = {name: b1_run.verify(d, inventory) for name, d in (("A", a_dir), ("B", b_dir), ("preflight", p_dir))}
    a_index, b_index = _load(a_dir / "index.json"), _load(b_dir / "index.json")
    require(a_index["arm"] == "A" and a_index["mode"] == "production", "b1_arm_a_invalid")
    require(b_index["arm"] == "B" and b_index["mode"] == "active", "b1_arm_b_invalid")
    require(a_index["inventorySha256"] == b_index["inventorySha256"] == sha_file(inventory), "b1_arms_inventory")
    a_eval, b_eval = _load(a_eval_path), _load(b_eval_path)
    for doc, index_path in ((a_eval, a_dir), (b_eval, b_dir)):
        require(doc["inputs"]["armIndex"] == sha_file(index_path / "index.json"), "b1_eval_not_of_arm")
        require(doc["inputs"]["truth"] == inv["o5"]["truth"], "b1_eval_truth_not_o5")
    eb_path = O5 / "eb.json"
    require(sha_file(eb_path) == inv["o5"]["eb"], "b1_eb_changed")
    eb = _load(eb_path)
    a_res, b_res, p_res = _results(a_dir), _results(b_dir), _results(p_dir)
    x1_index = _load(X1 / "baseline" / "index.json")

    # Parity ------------------------------------------------------------------------------------------------------
    x1_diff = []
    for s in sorted(a_res):
        raw = (X1 / "baseline" / "results" / f"{s}.json").read_bytes()
        require(sha_bytes(raw) == x1_index["results"][s], f"b1_x1_result_mismatch:{s}")
        if shape(json.loads(raw)) != shape(a_res[s]):
            x1_diff.append(s)
    parity = {"armAvsX1Baseline": {"identical": len(a_res) - len(x1_diff), "different": x1_diff},
              "armAvsPlatformH3Evidence": _platform_parity(a_res),
              "preflightShadowVsArmA": {"different": [s for s in a_res if shape(p_res[s]) != shape(a_res[s])]},
              "armAEvalVsO5Eb": _parity_eb(a_eval, eb)}
    parity_ok = (not x1_diff and not parity["armAvsPlatformH3Evidence"]["different"]
                 and not parity["preflightShadowVsArmA"]["different"]
                 and not parity["armAEvalVsO5Eb"]["differences"] and parity["armAEvalVsO5Eb"]["armA"] == [53, 79])

    # Controls: tracks, trajectories, Person and Representative ----------------------------------------------------
    controls = Counter()
    control_failures = []
    for s in sorted(a_res):
        ta = {str(t["trackId"]): t for t in a_res[s]["tracks"]}
        tb = {str(t["trackId"]): t for t in b_res[s]["tracks"]}
        if set(ta) != set(tb):
            control_failures.append([s, "track-set"])
            continue
        for tid, t in ta.items():
            u = tb[tid]
            controls["tracks"] += 1
            if t["trajectory"]["sha256"] != u["trajectory"]["sha256"] or t["objectClass"] != u["objectClass"]:
                control_failures.append([s, tid, "trajectory"])
            if t["objectClass"] == "person":
                controls["personTracks"] += 1
                if [(o["role"], o["rank"], o["sourceFrameNumber"], o["crop"]["sha256"]) for o in t["observations"]] != \
                        [(o["role"], o["rank"], o["sourceFrameNumber"], o["crop"]["sha256"]) for o in u["observations"]]:
                    control_failures.append([s, tid, "person-evidence"])
            else:
                controls["vehicleTracks"] += 1
                ra, rb = _by_role(t).get("representative"), _by_role(u).get("representative")
                if (ra or {}).get("crop") != (rb or {}).get("crop") or (ra or {}).get("sourceFrameNumber") != (
                        rb or {}).get("sourceFrameNumber"):
                    control_failures.append([s, tid, "representative"])

    # Changed Vehicle evidence, classified ------------------------------------------------------------------------
    a_cand, b_cand = _logs(a_dir, "candidates"), _logs(b_dir, "candidates")
    cand = {arm: {(s, str(r["track_id"]), r["frame"]): r for s, rows in logs.items() for r in rows}
            for arm, logs in (("A", a_cand), ("B", b_cand))}
    b1_logs = _logs(b_dir, "b1")
    a_entries, b_entries = _evidence_entries(a_eval), _evidence_entries(b_eval)
    oracle_tracks = {(r["sequenceId"], str(r["maviTrackId"])): _key(r) for r in b_eval["rows"]
                     if r["maviTrackId"] and _oracle(r)}
    labelled_tracks = {(r["sequenceId"], str(r["maviTrackId"])) for r in b_eval["rows"]
                       if r["maviTrackId"] and r["usablePlate"]}
    changes = []
    bytes_by_role = {"A": Counter(), "B": Counter()}
    counts_by_role = {"A": Counter(), "B": Counter()}
    for arm, results in (("A", a_res), ("B", b_res)):
        for result in results.values():
            for t in result["tracks"]:
                if t["objectClass"] == "vehicle":
                    for o in t["observations"]:
                        bytes_by_role[arm][o["role"]] += o["crop"]["sizeBytes"]
                        counts_by_role[arm][o["role"]] += 1
    for s in sorted(a_res):
        tb = {str(t["trackId"]): t for t in b_res[s]["tracks"]}
        for t in a_res[s]["tracks"]:
            if t["objectClass"] != "vehicle":
                continue
            tid = str(t["trackId"])
            ra, rb = _by_role(t), _by_role(tb[tid])
            for role in VEHICLE_ROLES:
                old, new = ra.get(role), rb.get(role)
                if old is None and new is None:
                    continue
                if old and new and old["crop"]["sha256"] == new["crop"]["sha256"] \
                        and old["sourceFrameNumber"] == new["sourceFrameNumber"]:
                    continue
                kind = "added" if old is None else "removed" if new is None else "replaced"
                if role == "near-view":
                    cause = "b1-admitted" if new and new.get("b1Admitted") else "near-view-displaced-by-b1-history"
                else:
                    cause = "diversity-cascade" if role != "representative" else "REPRESENTATIVE-CHANGED"

                def describe(o, entries, arm_key):
                    if o is None:
                        return None
                    rec = cand[arm_key].get((s, tid, o["sourceFrameNumber"]))
                    box = o["boundingBox"]
                    return {"frame": o["sourceFrameNumber"], "offsetMs": o["offsetMs"], "rank": o["rank"],
                            "cropSha256": o["crop"]["sha256"], "cropBytes": o["crop"]["sizeBytes"],
                            "boxArea": box["width"] * box["height"], "confidence": o["confidence"],
                            "qualityMicro": o["qualityMicro"], "b1Admitted": o.get("b1Admitted", False),
                            "sharpness": rec["sharpness"] if rec else None,
                            "b1Sharpness": rec["b1_sharpness"] if rec else None,
                            "outcome": _outcome(entries.get((s, tid, role)))}
                changes.append({"sequenceId": s, "trackId": tid, "role": role, "kind": kind, "cause": cause,
                                "gtTrack": list(oracle_tracks[(s, tid)]) if (s, tid) in oracle_tracks else None,
                                "onUsablePlateTrack": (s, tid) in labelled_tracks,
                                "A": describe(old, a_entries, "A"), "B": describe(new, b_entries, "B")})

    # Track-level gains and losses on the O5 primary population ------------------------------------------------------
    a_rows, b_rows = {_key(r): r for r in a_eval["rows"]}, {_key(r): r for r in b_eval["rows"]}
    require(set(a_rows) == set(b_rows), "b1_eval_population_differs")
    a_or = {k for k, r in a_rows.items() if _oracle(r)}
    b_or = {k for k, r in b_rows.items() if _oracle(r)}
    require(a_or == b_or, "b1_oracle_population_differs")
    state_changes = sorted(k for k in a_rows if a_rows[k]["state"] != b_rows[k]["state"]
                           or a_rows[k]["maviTrackId"] != b_rows[k]["maviTrackId"])
    gains = sorted(k for k in a_or if not _readable(a_rows[k]) and _readable(b_rows[k]))
    losses = sorted(k for k in a_or if _readable(a_rows[k]) and not _readable(b_rows[k]))
    role_shift = sorted(k for k in a_or if _readable(a_rows[k]) and _readable(b_rows[k]) and
                        a_rows[k]["result"]["rolesPreservingReading"] != b_rows[k]["result"]["rolesPreservingReading"])

    # Ceilings: for every oracle-readable Track not evidence-readable in Arm A --------------------------------------
    a_cand_idx = cand["A"]
    ceiling = []
    for k in sorted(a_or - {k for k in a_or if _readable(a_rows[k])}):
        row = a_rows[k]
        entry = {"gtTrack": list(k), "state": row["state"], "maviTrackId": row["maviTrackId"]}
        if row["state"] == "matched":
            tid = str(row["maviTrackId"])
            frames = []
            for oracle_frame in row["result"]["oracleFrames"]:
                readable = any(r.get("agreement") is True for r in oracle_frame["reads"].values())
                rec = a_cand_idx.get((k[0], tid, oracle_frame["frameIndex"]))
                frames.append({"frame": oracle_frame["frameIndex"], "plateCharPx": oracle_frame["charHeightPx"],
                               "nativeReadable": readable, "candidate": None if rec is None else {
                                   "qualifiedOriginal": rec["qualified_original"], "b1Only": rec["b1_only"],
                                   "sharpness": rec["sharpness"], "b1Sharpness": rec["b1_sharpness"],
                                   "nativeHeightPx": rec["native_height_px"],
                                   "failing": [g for g in ("confidence", "sharpness", "edge", "occlusion")
                                               if not rec[f"pass_{g}"]]}})
            track_rows = [r for r in a_cand[k[0]] if str(r["track_id"]) == tid]
            entry.update(oracleFrames=frames,
                         b1OnlyAtNativeReadableFrame=any(f["nativeReadable"] and f["candidate"] and
                                                         f["candidate"]["b1Only"] for f in frames),
                         b1OnlyCandidatesOnTrack=sum(r["b1_only"] for r in track_rows),
                         b1HeldOnTrack=sum(1 for r in b1_logs[k[0]] if r["trackId"] == tid and r["held"]))
        ceiling.append(entry)
    ceiling_matched = [c for c in ceiling if c["state"] == "matched"]

    # Admission accounting of b1-only candidates in Arm B ------------------------------------------------------------
    admission = Counter()
    for rows in b1_logs.values():
        for r in rows:
            admission["b1Only"] += 1
            if r["nearDuplicateOfRepresentative"]:
                admission["rejected_nearDuplicateOfRepresentative"] += 1
            elif not r["growthAllows"]:
                admission["rejected_growthHysteresis"] += 1
            elif r.get("encodeRefused"):
                admission["rejected_encoderRoleCap"] += 1
            else:
                admission["heldAsNearView"] += 1
    final_admitted = sum(1 for c in changes if c["B"] and c["B"]["b1Admitted"])
    per_sequence = {s: {"b1Only": len(b1_logs[s]), "held": sum(r["held"] for r in b1_logs[s]),
                        "changedObservations": sum(1 for c in changes if c["sequenceId"] == s)} for s in sorted(a_res)}
    timings = {arm: _load(d / "timings.json") for arm, d in (("A", a_dir), ("B", b_dir))}
    net = len(gains) - len(losses)
    if not parity_ok or control_failures:
        decision = "NO RESULT (parity or control failure)"
    elif net <= 0 or (losses and net <= 1):
        decision = "A"
    elif not losses and net >= 2:
        decision = "C"
    else:
        decision = "B"
    changed_tracks = {(c["sequenceId"], c["trackId"]) for c in changes}
    return {
        "kind": "b1-account", "rule": b_index["rule"],
        "inputs": {"inventory": sha_file(inventory), "armA": sha_file(a_dir / "index.json"),
                   "armB": sha_file(b_dir / "index.json"), "preflight": sha_file(p_dir / "index.json"),
                   "armAEval": sha_file(a_eval_path), "armBEval": sha_file(b_eval_path), "o5Eb": sha_file(eb_path)},
        "verified": verified, "parity": parity, "parityOk": parity_ok,
        "controls": {**dict(controls), "failures": control_failures},
        "coverage": {"armA": [a_eval["summary"]["rEvidence"], a_eval["summary"]["rOracle"]],
                     "armB": [b_eval["summary"]["rEvidence"], b_eval["summary"]["rOracle"]],
                     "armAByInstrument": a_eval["summary"]["coverageByInstrument"],
                     "armBByInstrument": b_eval["summary"]["coverageByInstrument"],
                     "armAByRole": a_eval["summary"]["evidenceReadableTracksByRole"],
                     "armBByRole": b_eval["summary"]["evidenceReadableTracksByRole"],
                     "armAFailuresByState": a_eval["summary"]["oracleNotEvidenceByState"],
                     "armBFailuresByState": b_eval["summary"]["oracleNotEvidenceByState"]},
        "gains": [list(k) for k in gains], "losses": [list(k) for k in losses], "netGain": net,
        "readableTracksWithChangedPreservingRoles": [list(k) for k in role_shift],
        "associationStateChanges": [list(k) for k in state_changes],
        "ceiling": {"oracleNotEvidenceArmA": len(ceiling), "matched": len(ceiling_matched),
                    "unassociatedOrFragmented": len(ceiling) - len(ceiling_matched),
                    "matchedWithB1OnlyAtNativeReadableFrame": sum(c["b1OnlyAtNativeReadableFrame"]
                                                                  for c in ceiling_matched),
                    "matchedWithAnyB1OnlyCandidate": sum(c["b1OnlyCandidatesOnTrack"] > 0 for c in ceiling_matched),
                    "matchedWithB1Held": sum(c["b1HeldOnTrack"] > 0 for c in ceiling_matched),
                    "tracks": ceiling},
        "admission": dict(admission), "b1AdmittedNearViewsInFinalEvidence": final_admitted,
        "evidence": {"changedObservations": len(changes), "changedTracks": len(changed_tracks),
                     "byCause": dict(Counter(c["cause"] for c in changes)),
                     "byRoleKind": dict(Counter(f"{c['role']}:{c['kind']}" for c in changes)),
                     "onOracleReadableTracks": sum(1 for c in changes if c["gtTrack"]),
                     "onUsablePlateTracks": sum(1 for c in changes if c["onUsablePlateTrack"]),
                     "outcomesB": dict(Counter(c["B"]["outcome"] for c in changes if c["B"])),
                     "outcomesA": dict(Counter(c["A"]["outcome"] for c in changes if c["A"])),
                     "vehicleCropBytesByRole": {k: dict(v) for k, v in bytes_by_role.items()},
                     "vehicleObservationsByRole": {k: dict(v) for k, v in counts_by_role.items()},
                     "changes": changes},
        "sequences": {"total": len(a_res), "withB1Only": sum(1 for v in per_sequence.values() if v["b1Only"]),
                      "withChangedEvidence": sum(1 for v in per_sequence.values() if v["changedObservations"]),
                      "perSequence": per_sequence},
        "resources": {arm: {"wallSeconds": round(sum(v["wallSeconds"] for v in t.values()), 1),
                            "cpuSeconds": round(sum(v["cpuSeconds"] for v in t.values()), 1)}
                      for arm, t in timings.items()},
        "decisionByFrozenRule": decision,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("preflight")
    e = sub.add_parser("evaluate")
    for s in (p, e):
        s.add_argument("--inventory", type=Path, required=True)
        s.add_argument("--arm-dir", type=Path, required=True)
        s.add_argument("--out", type=Path, required=True)
    a = sub.add_parser("account")
    for name in ("inventory", "a", "b", "preflight", "a-eval", "b-eval", "out"):
        a.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(argv)
    require(not args.out.exists(), f"b1_output_exists:{args.out}")
    if args.command == "preflight":
        document = preflight(args.inventory, args.arm_dir)
    elif args.command == "evaluate":
        document = evaluate(args.inventory, args.arm_dir)
    else:
        document = account(args.inventory, args.a, args.b, args.preflight, args.a_eval, args.b_eval)
    data = json.dumps(document, indent=1, sort_keys=True, default=str).encode("utf-8")
    args.out.write_bytes(data)
    print(f"{args.out} sha256={sha_bytes(data)}")
    if args.command != "evaluate":
        print(json.dumps({k: v for k, v in document.items() if k in (
            "counters", "failOriginalPassB1_blockedBy", "b1OnlyTracks", "nearViewOpportunityTracks", "stopRuleNull",
            "parityOk", "coverage", "gains", "losses", "netGain", "admission", "decisionByFrozenRule")}, indent=1))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except B1Error as error:
        print(f"FAIL-CLOSED: {error}", file=sys.stderr)
        raise SystemExit(2)
