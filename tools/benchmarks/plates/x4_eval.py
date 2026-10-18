"""Stage 4 X4-0 evaluation: frozen selection, arm texts, the A0 parity gate, metrics, ceilings and the decision.

Development experiment only; every rule is the frozen ``x4-0-rules-v1.json``. Order is part of the method:

1. inputs are verified fail-closed (inventory, extraction, inference);
2. **selection** (``x4_select``) runs on the per-candidate logs and, for P1, on detector scores only, and its
   digest is fixed *before* any truth, association or pilot outcome is read;
3. every arm's Track texts are computed by the seam summariser, whose equality with the production
   ``summarise_track`` is asserted on every A0 Track (a real ``LeaseTrack`` of <= 4 observations);
4. only then are the O5 truth, the frozen association and the pilot result read: the A0 parity gate
   (52/110, 110/110 per-Track agreement, identical crop set) stops the evaluation on failure;
5. metrics, cost accounting, ceilings and the frozen decision.

    python tools/benchmarks/plates/x4_eval.py a0-gate --inventory INV --infer SEALED_DIR --out A0.json
    python tools/benchmarks/plates/x4_eval.py --inventory INV --extract DIR --infer DIR --out EVAL.json
    python tools/benchmarks/plates/x4_eval.py equal EVAL1 EVAL2
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from math import comb
from pathlib import Path
from typing import Any
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent))
import x4_common as c  # noqa: E402
import x4_select  # noqa: E402
from x4_common import B1, O5, PILOT_EXPORTS, PILOT_RESULT, X4Error, require  # noqa: E402

K_ARMS = ("A-4", "A-8", "A-4-native", "A-8-native")
ARMS = ("A0", "A-4", "A-8", "A-all", "A-4-native", "A-8-native", "A-all-native", "P1")
CEILING_ARMS = ("X2-native-A0-frames",)
A0_HITS = 52


def _uuid(text: str) -> UUID:
    return UUID(c.sha_bytes(text.encode())[:32])


# crop records -> production dataclasses ---------------------------------------------------------------------------

def crop_record(record: dict, observation_id: UUID, role: str, rank: int):
    from mavi_vision.plates.pipeline import CropRecord, DetectionRecord, PlateRecord, RankedReading

    detections = tuple(DetectionRecord(tuple(d["box"]), d["score"], None if d["plate"] is None else PlateRecord(
        d["plate"]["plateIndex"], d["plate"]["outcome"],
        tuple(RankedReading(r["rank"], r["rawText"], r["rawLineCount"], r["confidence"]) for r in d["plate"]["readings"])))
        for d in record["detections"])
    # An over-bound model output (production: the attempt fails) contributes no plate: an abstention here.
    invalid = record["status"] == "output_invalid"
    return CropRecord(observation_id, role, rank, "abstained" if invalid else record["status"],
                      "detector_error" if invalid else record["reason"], record["width"], record["height"], detections)


def seam_summary(crops: tuple) -> tuple[tuple, ...]:
    """The production ``summarise_track`` text rule over any number of crop records (the X4 experiment seam).

    Returns ``(text, supportCount, maxConfidence, bestObservationId, bestPlateIndex)`` per distinct text, sorted by
    text; empty when no crop is scored (production: Track unavailable, no texts).
    """
    from mavi_vision.plates.contracts import CROP_SCORED, PLATE_READ
    from mavi_vision.plates.normalisation import OK, normalise

    if not any(crop.status == CROP_SCORED for crop in crops):
        return ()
    groups: dict[str, list] = {}
    for crop in crops:
        for _, plate in crop.plates():
            if plate.outcome != PLATE_READ:
                continue
            first = plate.readings[0]
            result = normalise(first.raw_text)
            if result.outcome != OK or result.normalised is None:
                continue
            groups.setdefault(result.normalised, []).append(
                (first.confidence, crop.evidence_rank, plate.plate_index, crop.observation_id))
    out = []
    for text in sorted(groups):
        members = groups[text]
        best = min(members, key=lambda item: (-item[0], item[1], item[2]))
        out.append((text, len(members), max(item[0] for item in members), best[3], best[2]))
    return tuple(out)


def production_summary(sequence: str, track_id: str, observations: list[dict], crops: tuple) -> tuple[tuple, ...]:
    from mavi_vision.plates.contracts import LeaseObservation, LeaseTrack
    from mavi_vision.plates.pipeline import TRACK_ANALYSED, summarise_track

    lease = LeaseTrack.model_validate({"trackId": _uuid(f"{sequence}/{track_id}"), "objectClass": "vehicle",
                                       "observations": tuple(LeaseObservation.model_validate({
                                           "observationId": crop.observation_id, "role": o["role"],
                                           "evidenceRank": o["rank"], "sizeBytes": o["crop"]["sizeBytes"],
                                           "sha256": o["crop"]["sha256"]}) for o, crop in zip(observations, crops))})
    summary = summarise_track(lease, crops)
    if summary.outcome != TRACK_ANALYSED:
        return ()
    return tuple((t.normalised_text, t.support_count, t.max_confidence, t.best_observation_id, t.best_plate_index)
                 for t in summary.texts)


def consensus(texts: tuple[tuple, ...]) -> str | None:
    """Secondary aggregation: highest support, then higher max confidence, then lexicographically smaller."""
    if not texts:
        return None
    return min(texts, key=lambda t: (-t[1], -t[2], t[0]))[0]


def max_score(record: dict) -> float | None:
    return max((d["score"] for d in record["detections"]), default=None)


def ocr_reads(record: dict) -> int:
    return sum(1 for d in record["detections"] if d["plate"] is not None)


# load ---------------------------------------------------------------------------------------------------------------

def load_inputs(inventory: Path, extract: Path, infer: Path) -> dict[str, Any]:
    import x4_extract
    import x4_infer

    inv, inv_sha = c.load_inventory(inventory)
    if extract is not None:
        x4_extract.verify(extract, inventory)
    x4_infer.verify(infer, extract)
    ext_index, inf_index = (c.load(extract / "index.json") if extract else None), c.load(infer / "index.json")
    require(inf_index["inventorySha256"] == inv_sha and (ext_index is None or ext_index["inventorySha256"] == inv_sha),
            "x4_eval_inventory_binding")
    require(inf_index["scope"] == ("all" if extract is not None else "sealed-only"), "x4_eval_infer_scope")
    a_index = c.load(B1 / "A" / "index.json")
    data: dict[str, Any] = {"inv": inv, "invSha": inv_sha, "seqs": sorted(inv["sequences"]), "tracks": {},
                            "records": {}, "timings": c.load(infer / "timings.json"),
                            "frames": {}, "inputs": {"inventory": inv_sha,
                                                     "extractIndex": c.sha_file(extract / "index.json") if extract else None,
                                                     "inferIndex": c.sha_file(infer / "index.json"),
                                                     "rules": inv["rulesSha256"]}}
    for s in data["seqs"]:
        entry = inv["sequences"][s]
        raw = (B1 / "A" / "results" / f"{s}.json").read_bytes()
        require(c.sha_bytes(raw) == entry["b1ResultSha256"] == a_index["results"][s], f"x4_eval_b1_result:{s}")
        result = json.loads(raw)
        candidates = c.read_log(B1 / "A" / "candidates" / f"{s}.jsonl.gz", entry["candidateLog"])
        manifest = (c.read_log(extract / "manifest" / f"{s}.jsonl.gz", ext_index["sequences"][s]["crops"])
                    if extract else [])
        records = {r["sha256"]: r["record"] for r in c.read_log(infer / "records" / f"{s}.jsonl.gz",
                                                                 inf_index["records"][s])}
        data["records"][s] = records
        data.setdefault("allSealedCrops", set()).update(o["crop"]["sha256"] for t in result["tracks"] for o in t["observations"])
        data["frames"][s] = ext_index["sequences"][s]["decodedFrames"] if extract else None
        by_track_c, by_track_m = defaultdict(list), defaultdict(dict)
        for r in candidates:
            by_track_c[str(r["track_id"])].append(r)
        for r in manifest:
            by_track_m[r["trackId"]][r["frame"]] = r
        for track in result["tracks"]:
            if track["objectClass"] != "vehicle":
                continue
            tid = str(track["trackId"])
            for o in track["observations"]:
                require(o["crop"]["sha256"] in records, f"x4_eval_sealed_record_missing:{s}:{tid}")
            data["tracks"][(s, tid)] = {"observations": track["observations"], "candidates": by_track_c[tid],
                                        "manifest": by_track_m[tid]}
    require(len(data["tracks"]) == inv["totals"]["vehicleTracks"], "x4_eval_catalogue_size")
    return data


# selection (no truth) ---------------------------------------------------------------------------------------------

def select_all(data: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Every arm's extra frames per Track, from candidate logs (A-K) and detector scores (P1) only."""
    out = {}
    for (s, tid), t in sorted(data["tracks"].items()):
        records = data["records"][s]
        a0_frames = [o["sourceFrameNumber"] for o in t["observations"]]
        available = [f for f, r in t["manifest"].items() if r["jpeg"] and r["native"]]
        pool = x4_select.pool(t["candidates"], a0_frames, available)
        chosen = {f"K{k}": list(x4_select.select_k(pool, k)) for k in x4_select.KS}
        a0_scores = [max_score(records[o["crop"]["sha256"]]) for o in t["observations"]]
        pool_scores = {r["frame"]: max_score(records[t["manifest"][r["frame"]]["jpeg"]["sha256"]]) for r in pool}
        p1 = x4_select.select_p1(a0_scores, pool_scores)
        out[(s, tid)] = {**chosen, "P1": [] if p1 is None else [p1], "pool": [r["frame"] for r in pool],
                         "a0Frames": a0_frames,
                         "excluded": sorted((f, r["excluded"]) for f, r in t["manifest"].items() if r["excluded"])}
    return out


def arm_crops(arm: str, t: dict, sel: dict) -> tuple[list[tuple[str, str, int]], list[str]]:
    """The arm's crops for one Track as (sha, role, rank), and its scouting-only crops (P1)."""
    sealed = [(o["crop"]["sha256"], o["role"], o["rank"]) for o in t["observations"]]
    if arm == "A0":
        return sealed, []
    if arm == "X2-native-A0-frames":
        extra = [t["manifest"][o["sourceFrameNumber"]]["native"]["sha256"] for o in t["observations"]
                 if t["manifest"][o["sourceFrameNumber"]]["native"]]
    elif arm == "P1":
        extra = [t["manifest"][f]["jpeg"]["sha256"] for f in sel["P1"]]
        scouting = [t["manifest"][f]["jpeg"]["sha256"] for f in sel["pool"] if f not in sel["P1"]]
        return sealed + [(sha, "x4-extra", 4 + i) for i, sha in enumerate(extra)], scouting
    else:
        k = arm.split("-")[1]
        kind = "native" if arm.endswith("-native") else "jpeg"
        extra = [t["manifest"][f][kind]["sha256"] for f in sel[f"K{k}"]]
    return sealed + [(sha, "x4-extra", 4 + i) for i, sha in enumerate(extra)], []


def arm_frames_needed(arm: str, sel: dict) -> list[int]:
    if arm == "A0":
        return []
    if arm == "X2-native-A0-frames":
        return sel["a0Frames"]
    if arm == "P1":
        return sel["pool"]
    return sel[f"K{arm.split('-')[1]}"]


def texts_all(data: dict[str, Any], selections: dict) -> tuple[dict, dict, dict]:
    """Per arm, per Track: seam texts; per arm cost; and the seam-vs-production equality check on A0."""
    texts: dict[str, dict] = {arm: {} for arm in ARMS + CEILING_ARMS}
    cost = {arm: defaultdict(float) for arm in ARMS + CEILING_ARMS}
    needed = {arm: defaultdict(int) for arm in ARMS + CEILING_ARMS}
    seam_equal, seam_checked = 0, 0
    for (s, tid), t in sorted(data["tracks"].items()):
        records, timings, sel = data["records"][s], data["timings"][s], selections[(s, tid)]
        for arm in ARMS + CEILING_ARMS:
            crops_spec, scouting = arm_crops(arm, t, sel)
            crops = []
            for sha, role, rank in crops_spec:
                oid = _uuid(f"{s}/{tid}/{role}") if role != "x4-extra" else _uuid(f"{s}/{tid}/{arm}/{rank}/{sha}")
                crops.append(crop_record(records[sha], oid, role, rank))
            crops = tuple(crops)
            summary = seam_summary(crops)
            texts[arm][(s, tid)] = summary
            if arm == "A0":
                seam_checked += 1
                seam_equal += summary == production_summary(s, tid, t["observations"], crops)
            k = cost[arm]
            k["crops"] += len(crops_spec)
            k["extraFrames"] += len(crops_spec) - len(t["observations"])
            k["detectorPasses"] += len(crops_spec) + len(scouting)
            k["ocrReads"] += sum(ocr_reads(records[sha]) for sha, _, _ in crops_spec)
            k["detectorCpuSeconds"] += sum(timings[sha]["detectCpu"] for sha in [x[0] for x in crops_spec] + scouting)
            k["ocrCpuSeconds"] += sum(timings[sha]["readCpu"] for sha, _, _ in crops_spec)
            k["outputInvalidCrops"] += sum(records[sha]["status"] == "output_invalid" for sha, _, _ in crops_spec)
            frames = arm_frames_needed(arm, sel)
            if frames:
                needed[arm][s] = max(needed[arm][s], max(frames) + 1)
    for arm in cost:
        cost[arm]["framesDecodedSequential"] = sum(needed[arm].values())
        cost[arm]["sequencesDecoded"] = len(needed[arm])
        cost[arm]["plateInferenceCpuSeconds"] = cost[arm]["detectorCpuSeconds"] + cost[arm]["ocrCpuSeconds"]
        cost[arm] = {k: (round(v, 3) if isinstance(v, float) and not float(v).is_integer() else int(v))
                     for k, v in sorted(cost[arm].items())}
    return texts, cost, {"a0Tracks": seam_checked, "equal": seam_equal, "passed": seam_checked == seam_equal}


# truth-side evaluation (only after selection and texts are fixed) -------------------------------------------------

def gt_population(data: dict[str, Any]) -> tuple[dict, dict, dict]:
    import b1_plates

    inv = data["inv"]
    require(c.sha_file(O5 / "truth-val.json") == inv["o5Truth"], "x4_eval_truth_changed")
    require(c.sha_file(B1 / "A-eval.json") == inv["b1"]["armAEval"], "x4_eval_a_eval_changed")
    require(c.sha_file(PILOT_RESULT) == inv["pilot"]["sha256"], "x4_eval_pilot_changed")
    truth = b1_plates.truth_texts()
    a_eval = c.load(B1 / "A-eval.json")
    pilot = c.load(PILOT_RESULT)
    from mavi_vision.plates.normalisation import OK, normalise

    gts = {}
    for row in a_eval["rows"]:
        key = (row["sequenceId"], row["gtTrackId"])
        if not row["usablePlate"] or key not in truth:
            continue
        wanted = sorted({r.normalised for r in (normalise(t) for t in truth[key]) if r.outcome == OK and r.normalised})
        mavi = (row["sequenceId"], str(row["maviTrackId"])) if row["state"] == "matched" and row["maviTrackId"] else None
        gts[f"{key[0]}/{key[1]}"] = {"state": row["state"], "mavi": mavi, "wanted": wanted,
                                     "oracleReadable": bool(row["result"]["oracleReadable"])}
    pilot_tracks = {f"{t['sequenceId']}/{t['gtTrackId']}": t for t in pilot["tracks"]}
    require(set(gts) == set(pilot_tracks), "x4_eval_gt_population_not_pilot")
    require(all(k.split("/")[0] in set(data["seqs"]) for k in gts), "x4_eval_gt_outside_catalogue")
    return gts, pilot_tracks, a_eval


def evaluate_arm(texts: dict, gts: dict, aggregation: str) -> dict[str, Any]:
    def track_texts(key):
        values = texts.get(key, ())
        if aggregation == "consensus":
            top = consensus(values)
            return {top} if top else set()
        return {t[0] for t in values}

    by_text: dict[str, set] = defaultdict(set)
    for key in texts:
        for text in track_texts(key):
            by_text[text].add(key)
    rows = {}
    for g, info in sorted(gts.items()):
        wanted = set(info["wanted"])
        own = track_texts(info["mavi"]) if info["mavi"] else set()
        returned = set().union(*(by_text.get(w, set()) for w in wanted)) if wanted else set()
        rows[g] = {"hit": bool(info["mavi"] and wanted & own),
                   "wrongTrackReturns": len(returned - ({info["mavi"]} if info["mavi"] else set())),
                   "wrongTexts": sorted(own - wanted) if info["mavi"] else [],
                   "textsOnMatchedTrack": len(own)}
    with_text = sum(1 for key in texts if track_texts(key))
    pairs = sum(len(track_texts(key)) for key in texts)
    return {"rows": rows, "hits": sum(r["hit"] for r in rows.values()),
            "hitsOracleReadable": sum(r["hit"] and gts[g]["oracleReadable"] for g, r in rows.items()),
            "wrongTrackReturns": sum(r["wrongTrackReturns"] for r in rows.values()),
            "wrongTextsOnMatchedGtTracks": sum(len(r["wrongTexts"]) for r in rows.values()),
            "matchedGtTracksWithWrongText": sum(1 for r in rows.values() if r["wrongTexts"]),
            "tracksCarryingText": with_text, "catalogueTrackTextPairs": pairs}


def sign_test(gains: int, losses: int) -> float:
    n = gains + losses
    if n == 0:
        return 1.0
    return sum(comb(n, i) for i in range(gains, n + 1)) / 2 ** n


def compare(arm: dict, base: dict) -> dict[str, Any]:
    gained = sorted(g for g in base["rows"] if arm["rows"][g]["hit"] and not base["rows"][g]["hit"])
    lost = sorted(g for g in base["rows"] if base["rows"][g]["hit"] and not arm["rows"][g]["hit"])
    return {"gained": gained, "lost": lost, "G": arm["hits"] - base["hits"], "L": len(lost),
            "W": arm["wrongTrackReturns"] - base["wrongTrackReturns"], "signTestP": sign_test(len(gained), len(lost))}


def decide(primary: dict, deltas: dict, cost: dict) -> dict[str, Any]:
    """The frozen decision rule (x4-0-rules-v1 ``decisionRule``)."""
    def pursue(d):
        return d["G"] >= 8 and d["L"] == 0 and d["W"] <= 2 and d["signTestP"] <= 0.05

    def reject(d):
        return d["G"] <= 4 or d["L"] > 0 or d["W"] >= d["G"]

    per_arm = {a: {"pursue": pursue(deltas[a]), "reject": reject(deltas[a])} for a in K_ARMS}
    if any(v["pursue"] for v in per_arm.values()):
        outcome = "PURSUE"
    elif all(v["reject"] for v in per_arm.values()):
        outcome = "REJECT"
    else:
        outcome = "INCONCLUSIVE"
    out: dict[str, Any] = {"perArm": per_arm, "outcome": outcome, "designPreference": None}
    if outcome != "PURSUE":
        return out
    candidates = [a for a in K_ARMS if per_arm[a]["pursue"]]
    best = min(candidates, key=lambda a: (-deltas[a]["G"], deltas[a]["W"], a.endswith("-native"), int(a.split("-")[1])))
    k = best.split("-")[1]

    def extra(a):
        return (cost[a]["detectorPasses"] + cost[a]["ocrReads"]) - (cost["A0"]["detectorPasses"] + cost["A0"]["ocrReads"])

    p1 = deltas["P1"]
    p1_pref = (primary["P1"]["hits"] >= primary[best]["hits"] - 2 and p1["L"] == 0 and p1["W"] <= deltas[best]["W"]
               and extra("P1") <= extra(best))
    vjk = per_arm[f"A-{k}"]["pursue"] and primary[f"A-{k}"]["hits"] >= primary[f"A-{k}-native"]["hits"] - 1
    out.update(best=best, kStar=k, p1Conditions=p1_pref, visionJobKConditions=vjk,
               designPreference="P1_PREFERRED" if p1_pref else "VISIONJOB_K_PREFERRED" if vjk else "X4_NATIVE_PREFERRED")
    return out


def a0_parity(primary_a0: dict, pilot_tracks: dict, data: dict, texts_a0: dict, a_eval: dict) -> dict[str, Any]:
    import b1_plates

    agree = sum(1 for g, t in pilot_tracks.items() if primary_a0["rows"][g]["hit"] == (t["cause"] == "search_hit"))
    pilot_crops = {p.stem for p in PILOT_EXPORTS.rglob("evidence/*.jpg")}
    mine = data["allSealedCrops"]  # every class: the pilot exported Person and Vehicle evidence
    # Cross-check with B1's own offline search predicate on the same texts (70-sequence catalogue).
    b1_rows = b1_plates.hits(a_eval, {k: [x[0] for x in v] for k, v in texts_a0.items()}, b1_plates.truth_texts())
    phase2 = c.load(B1 / "plates-phase2.json")
    phase2_rows = phase2["arms"]["A"]["rows"]
    out = {"hits": primary_a0["hits"], "perTrackAgreementWithPilot": agree, "pilotTracks": len(pilot_tracks),
           "disagreements": sorted(g for g, t in pilot_tracks.items()
                                   if primary_a0["rows"][g]["hit"] != (t["cause"] == "search_hit")),
           "cropSetEqualsPilot": pilot_crops == mine, "pilotCrops": len(pilot_crops), "a0CropsAllClasses": len(mine),
           "a0VehicleCropsDistinct": len({o["crop"]["sha256"] for t in data["tracks"].values() for o in t["observations"]}),
           "a0VehicleObservations": sum(len(t["observations"]) for t in data["tracks"].values()),
           "b1PredicateHits": sum(r["hit"] for r in b1_rows.values()),
           "b1PredicateWrongTrackReturns70": sum(r["otherTracksReturned"] for r in b1_rows.values()),
           "perTrackEqualsB1Phase2": all(phase2_rows[g]["hit"] == primary_a0["rows"][g]["hit"] for g in pilot_tracks),
           "b1Phase2WrongTrackReturns200": phase2["summary"]["A"]["otherTracksReturned"]}
    out["passed"] = (out["hits"] == A0_HITS and agree == 110 and out["cropSetEqualsPilot"]
                     and out["b1PredicateHits"] == A0_HITS and out["perTrackEqualsB1Phase2"]
                     and out["b1PredicateWrongTrackReturns70"] == primary_a0["wrongTrackReturns"])
    return out


def ceilings(primary: dict, gts: dict, pilot_tracks: dict) -> dict[str, Any]:
    matched = sorted(g for g, i in gts.items() if i["mavi"])
    brief = sorted(g for g, t in pilot_tracks.items() if (t["cause"] == "source_evidence" and t["oracleReadable"])
                   or t["cause"] in ("detector_miss", "ocr_error"))
    union_hits = sorted(g for g in gts if any(primary[a]["rows"][g]["hit"] for a in primary))
    account = c.load(B1 / "account.json")
    eb_matched = [f"{e['gtTrack'][0]}/{e['gtTrack'][1]}" for e in account["ceiling"]["tracks"] if e["state"] == "matched"]
    eb_gains = {f"{a}/{b}" for a, b in account["gains"]}
    per_track = {g: {"state": gts[g]["state"], "oracleReadable": gts[g]["oracleReadable"],
                     "pilotCause": pilot_tracks[g]["cause"], "hits": {a: primary[a]["rows"][g]["hit"] for a in primary}}
                 for g in sorted(gts)}
    x4 = primary["A-all-native"]
    return {
        "associationBound": {"label": "derived", "value": len(matched), "ofOracleReadable":
                             sum(gts[g]["oracleReadable"] for g in matched)},
        "briefPilotCauseBound": {"label": "derived (brief's <= 74)", "value": A0_HITS + len(brief), "tracks": brief,
                                 "allMatched": all(gts[g]["mavi"] for g in brief),
                                 "notOracleReadableIncluded": sorted(g for g in brief if not gts[g]["oracleReadable"]),
                                 "matchedSourceEvidenceNotOracleExcluded": sorted(
                                     g for g, t in pilot_tracks.items()
                                     if t["cause"] == "source_evidence" and not t["oracleReadable"]),
                                 "measuredRecoveredByAnyArm": sorted(g for g in brief if g in union_hits)},
        "X2": {"label": "measured", "hits": primary["X2-native-A0-frames"]["hits"],
               "hitsOracleReadable": primary["X2-native-A0-frames"]["hitsOracleReadable"], "briefEstimate": "~53"},
        "X4": {"label": "measured (A-all-native, 5 fps BDD, PD5/OC1-S)", "hits": x4["hits"],
               "hitsOracleReadable": x4["hitsOracleReadable"], "briefEstimate": "<= 74 [HYP]"},
        "X3": {"label": "measured upper bound with X4's frame access (VisionJob plate-aware selection not modelled)",
               "hits": x4["hits"], "briefEstimate": "~62"},
        "unionOfAllArms": {"label": "measured", "hits": len(union_hits),
                           "hitsOracleReadable": sum(gts[g]["oracleReadable"] for g in union_hits)},
        "unrecoveredMatched": {"label": "measured", "tracks": sorted(g for g in matched if g not in union_hits)},
        "EB79": {"label": "estimate (instrument-oracle quantity, not re-measured)", "briefEstimate": "<= 11",
                 "ebMatchedUnreadableTracks": len(eb_matched),
                 "crossTab": {g: {"b1Gain": g in eb_gains, "inPilotPopulation": g in gts,
                                  "searchHitAnyArm": g in union_hits if g in gts else None,
                                  "searchHitA0": primary["A0"]["rows"][g]["hit"] if g in gts else None}
                              for g in eb_matched}},
        "perTrack": per_track,
    }


def evaluate(inventory: Path, extract: Path, infer: Path) -> dict[str, Any]:
    data = load_inputs(inventory, extract, infer)
    selections = select_all(data)
    selection_digest = c.sha_bytes(c.canonical_lines(
        [{"sequenceId": s, "trackId": t, **v} for (s, t), v in sorted(selections.items())]))
    texts, cost, seam = texts_all(data, selections)
    require(seam["passed"], f"x4_seam_summary_differs_from_production:{seam}")
    texts_digest = c.sha_bytes(c.canonical_lines(
        [{"arm": a, "sequenceId": s, "trackId": t, "texts": [list(map(str, x)) for x in v]}
         for a in texts for (s, t), v in sorted(texts[a].items())]))
    # Truth, association and pilot outcomes are read only from here on.
    gts, pilot_tracks, a_eval = gt_population(data)
    primary = {a: evaluate_arm(texts[a], gts, "primary") for a in ARMS + CEILING_ARMS}
    secondary = {a: evaluate_arm(texts[a], gts, "consensus") for a in ARMS + CEILING_ARMS}
    parity = a0_parity(primary["A0"], pilot_tracks, data, texts["A0"], a_eval)
    require(parity["passed"], f"x4_a0_parity_failed:{ {k: v for k, v in parity.items() if k != 'disagreements'} }")
    deltas = {a: compare(primary[a], primary["A0"]) for a in ARMS + CEILING_ARMS}
    secondary_deltas = {a: {"vsA0Consensus": compare(secondary[a], secondary["A0"]),
                            "vsA0Primary": compare(secondary[a], primary["A0"])} for a in ARMS + CEILING_ARMS}
    canonical_cost = {a: {k: v for k, v in cost[a].items() if "Cpu" not in k} for a in cost}
    cpu = {a: {k: v for k, v in cost[a].items() if "Cpu" in k} for a in cost}
    pool_sizes = [len(v["pool"]) for v in selections.values()]
    canonical = {
        "kind": "x4-eval", "rules": c.RULES_ID, "selectionDigest": selection_digest, "textsDigest": texts_digest,
        "seamSummaryEqualsProduction": seam, "a0Parity": parity,
        "selection": {"tracks": len(selections), "poolFrames": sum(pool_sizes),
                      "meanPoolFramesPerTrack": round(sum(pool_sizes) / len(pool_sizes), 3),
                      "tracksWithPoolAbove8": sum(p > 8 for p in pool_sizes),
                      "excludedTrackFrames": sum(len(v["excluded"]) for v in selections.values()),
                      "p1FramesAdded": sum(len(v["P1"]) for v in selections.values())},
        "summary": {a: {k: v for k, v in primary[a].items() if k != "rows"} | {
            "G": deltas[a]["G"], "L": deltas[a]["L"], "W": deltas[a]["W"], "signTestP": deltas[a]["signTestP"],
            "gained": deltas[a]["gained"], "lost": deltas[a]["lost"]} for a in primary},
        "secondaryConsensus": {a: {k: v for k, v in secondary[a].items() if k != "rows"} | {
            "vsA0Consensus": secondary_deltas[a]["vsA0Consensus"], "vsA0Primary": secondary_deltas[a]["vsA0Primary"]}
            for a in secondary},
        "cost": canonical_cost,
        "perGtTrack": {g: {a: primary[a]["rows"][g] for a in primary} for g in sorted(gts)},
        "ceilings": ceilings(primary, gts, pilot_tracks),
        "decision": decide(primary, deltas, cost),
    }
    return {"canonical": canonical, "cpu": cpu, "inputs": data["inputs"],
            "decodedFramesPerSequence": data["frames"]}


def a0_gate(inventory: Path, infer_sealed: Path) -> dict[str, Any]:
    """Phase 0 stop gate: A0 alone, from a sealed-only inference run, before any extra frame is extracted."""
    data = load_inputs(inventory, None, infer_sealed)
    texts, seam = {}, {"a0Tracks": 0, "equal": 0}
    for (s, tid), t in sorted(data["tracks"].items()):
        crops = tuple(crop_record(data["records"][s][o["crop"]["sha256"]], _uuid(f"{s}/{tid}/{o['role']}"), o["role"],
                                  o["rank"]) for o in t["observations"])
        texts[(s, tid)] = seam_summary(crops)
        seam["a0Tracks"] += 1
        seam["equal"] += texts[(s, tid)] == production_summary(s, tid, t["observations"], crops)
    seam["passed"] = seam["a0Tracks"] == seam["equal"]
    gts, pilot_tracks, a_eval = gt_population(data)
    primary = evaluate_arm(texts, gts, "primary")
    parity = a0_parity(primary, pilot_tracks, data, texts, a_eval)
    return {"kind": "x4-a0-gate", "inputs": data["inputs"], "seamSummaryEqualsProduction": seam, "a0Parity": parity,
            "summary": {k: v for k, v in primary.items() if k != "rows"},
            "textsDigest": c.sha_bytes(c.canonical_lines([{"sequenceId": s, "trackId": t, "texts": [list(map(str, x)) for x in v]}
                                                          for (s, t), v in sorted(texts.items())])),
            "passed": seam["passed"] and parity["passed"]}


def equal(first: Path, second: Path) -> dict[str, Any]:
    a, b = c.load(first), c.load(second)
    differing = sorted(k for k in set(a["canonical"]) | set(b["canonical"]) if a["canonical"].get(k) != b["canonical"].get(k))
    return {"canonicalEqual": not differing, "differing": differing,
            "inventoryEqual": a["inputs"]["inventory"] == b["inputs"]["inventory"],
            "sha256": [c.sha_file(first), c.sha_file(second)]}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "a0-gate":
        gate = argparse.ArgumentParser()
        for name in ("inventory", "infer", "out"):
            gate.add_argument(f"--{name}", type=Path, required=True)
        args = gate.parse_args(argv[1:])
        require(not args.out.exists(), "x4_output_exists")
        document = a0_gate(args.inventory, args.infer)
        digest = c.dump(args.out, document)
        print(json.dumps({k: document[k] for k in ("seamSummaryEqualsProduction", "a0Parity", "summary", "passed")}, indent=1))
        print(f"{args.out} sha256={digest}")
        return 0 if document["passed"] else 3
    if argv and argv[0] == "equal":
        result = equal(Path(argv[1]), Path(argv[2]))
        print(json.dumps(result, indent=1))
        return 0 if result["canonicalEqual"] else 1
    parser = argparse.ArgumentParser()
    for name in ("inventory", "extract", "infer", "out"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(argv)
    require(not args.out.exists(), "x4_output_exists")
    document = evaluate(args.inventory, args.extract, args.infer)
    digest = c.dump(args.out, document)
    s = document["canonical"]
    print(json.dumps({"a0Parity": {k: v for k, v in s["a0Parity"].items()},
                      "summary": {a: {k: v for k, v in x.items() if k not in ("gained", "lost")} for a, x in s["summary"].items()},
                      "decision": s["decision"]}, indent=1))
    print(f"{args.out} sha256={digest}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except X4Error as error:
        print(f"FAIL-CLOSED: {error}", file=sys.stderr)
        raise SystemExit(2)
