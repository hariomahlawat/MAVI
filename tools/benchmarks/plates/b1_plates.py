"""Stage 4 B1 (#228) Phase 2: both arms' sealed Vehicle evidence through the #226 PD5/OC1-S plate path, offline.

Development measurement only. The product plate role's own code runs on every Vehicle Track of an arm: the
``components_for`` adapters (``ppocr-db-onnx-v1`` PD5-V5M, ``fast-plate-ocr-onnx-v1`` OC1-S) with the pilot's
committed parameters (``development-plates-onnx-pilot-parameters-v1.json``) and the staged pilot packs (SHA-256
checked against ``tools/vision/plates-pilot-payloads-v1.json``), ``pipeline.analyse_crop`` per crop and
``pipeline.summarise_track`` per Track. A crop's analysis is a function of its bytes alone, so it is computed once
per distinct crop SHA-256 and shared by both arms.

An exact search hit for a text-usable ground-truth Track is the platform's exact search predicate evaluated
offline: the arm's associated MAVI Track (association state ``matched``) has the normalised truth text among its
Track texts. Other Tracks carrying the same text are counted as other returned Tracks. NOT measured here: the
live platform API, its catalogue and its run-readiness; this is the identical model/pipeline/summary code, not the
identical deployment. Nothing selects or changes crops; the plate outputs never reach the selector.

    python tools/benchmarks/plates/b1_plates.py --a A --a-eval AE --b B --b-eval BE --out OUT.json
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[3]
for _p in (ROOT, ROOT / "src" / "vision"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

PACKS = Path("E:/MAVI-Working/anpr-pilot/models")
PARAMETERS = ROOT / "src" / "vision" / "config" / "plates" / "development-plates-onnx-pilot-parameters-v1.json"
PAYLOADS = ROOT / "tools" / "vision" / "plates-pilot-payloads-v1.json"
TRUTH = Path("E:/MAVI-Controlled/Benchmarks/stage4-bdd-plates/results-human-reviewed/truth-val.json")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _uuid(text: str) -> UUID:
    return UUID(_sha(text.encode())[:32])


def components():
    from mavi_vision.plates.adapters import DETECTOR_CAPABILITY, OCR_CAPABILITY, AdapterRequest, components_for
    from mavi_vision.plates.parameters import load_parameters

    payloads = json.loads(PAYLOADS.read_bytes())["payloads"]
    verified = {}
    for p in payloads:
        path = PACKS / p["packDirectory"] / p["file"]
        if path.exists():
            if _sha(path.read_bytes()) != p["sha256"]:
                raise SystemExit(f"b1_plates_pack_mismatch:{p['packDirectory']}/{p['file']}")
            verified[f"{p['packDirectory']}/{p['file']}"] = p["sha256"]
    pd5, oc1 = PACKS / "plates-pd5-v5m-dev-v1", PACKS / "plates-oc1-s-dev-v1"
    for needed in ("plates-pd5-v5m-dev-v1/inference.onnx", "plates-pd5-v5m-dev-v1/inference.yml",
                   "plates-oc1-s-dev-v1/cct_s_v2_global.onnx", "plates-oc1-s-dev-v1/cct_s_v2_global_plate_config.yaml"):
        if needed not in verified:
            raise SystemExit(f"b1_plates_pack_unverified:{needed}")
    parameters = load_parameters(PARAMETERS.read_bytes())
    detector, recogniser = components_for(
        AdapterRequest(DETECTOR_CAPABILITY, "ppocr-db-onnx-v1",
                       {"onnx-model": pd5 / "inference.onnx", "inference-config": pd5 / "inference.yml"}),
        AdapterRequest(OCR_CAPABILITY, "fast-plate-ocr-onnx-v1",
                       {"onnx-model": oc1 / "cct_s_v2_global.onnx",
                        "plate-config": oc1 / "cct_s_v2_global_plate_config.yaml"}),
        parameters=parameters, development_only=True, production_mode=False)
    return detector, recogniser, parameters, {"packs": verified, "parametersSha256": _sha(PARAMETERS.read_bytes())}


def truth_texts() -> dict[tuple[str, str], list[str]]:
    from tools.benchmarks.capabilities.plates import truth as truths

    out: dict[tuple[str, str], set[str]] = {}
    for item in json.loads(TRUTH.read_bytes())["items"]:
        for plate in item["plates"]:
            if plate["textUsable"]:
                out.setdefault((item["sequenceId"], item["gtTrackId"]), set()).add(truths.truth_text(plate))
    return {k: sorted(v) for k, v in out.items()}


def analyse_arm(arm_dir: Path, cache: dict, detector, recogniser, parameters) -> dict[tuple[str, str], list[str]]:
    from mavi_vision.plates.contracts import LeaseObservation, LeaseTrack
    from mavi_vision.plates.inference import VerifiedCrop
    from mavi_vision.plates.pipeline import TRACK_ANALYSED, analyse_crop, summarise_track

    index = json.loads((arm_dir / "index.json").read_bytes())
    texts = {}
    for sequence, digest in sorted(index["results"].items()):
        raw = (arm_dir / "results" / f"{sequence}.json").read_bytes()
        if _sha(raw) != digest:
            raise SystemExit(f"b1_plates_result_mismatch:{sequence}")
        result = json.loads(raw)
        for track in result["tracks"]:
            if track["objectClass"] != "vehicle":
                continue
            observations, crops = [], []
            for o in track["observations"]:
                data = (arm_dir / "staging" / sequence / o["crop"]["storageKey"]).read_bytes()
                if _sha(data) != o["crop"]["sha256"] or len(data) != o["crop"]["sizeBytes"]:
                    raise SystemExit(f"b1_plates_crop_mismatch:{sequence}")
                oid = _uuid(f"{sequence}/{track['trackId']}/{o['role']}")
                lease = LeaseObservation.model_validate({"observationId": oid, "role": o["role"], "evidenceRank": o["rank"],
                                                      "sizeBytes": len(data), "sha256": o["crop"]["sha256"]})
                observations.append(lease)
                key = o["crop"]["sha256"]
                if key not in cache:
                    cache[key] = analyse_crop(lease, VerifiedCrop(str(oid), o["role"], o["rank"], key, data),
                                              detector, recogniser, parameters)
                record = cache[key]
                crops.append(dataclasses.replace(record, observation_id=lease.observation_id, role=o["role"], evidence_rank=o["rank"]))
            summary = summarise_track(LeaseTrack.model_validate({
                "trackId": _uuid(f"{sequence}/{track['trackId']}"), "objectClass": "vehicle",
                "observations": tuple(observations)}), tuple(crops))
            texts[(sequence, str(track["trackId"]))] = [t.normalised_text for t in summary.texts] if summary.outcome == TRACK_ANALYSED else []
    return texts


def hits(eval_doc: dict, texts: dict, truth: dict) -> dict[str, Any]:
    from mavi_vision.plates.normalisation import OK, normalise

    by_text: dict[str, set] = {}
    for key, values in texts.items():
        for value in values:
            by_text.setdefault(value, set()).add(key)
    rows = {}
    for row in eval_doc["rows"]:
        key = (row["sequenceId"], row["gtTrackId"])
        if not row["usablePlate"] or key not in truth:
            continue
        wanted = {r.normalised for r in (normalise(t) for t in truth[key]) if r.outcome == OK and r.normalised}
        mavi = (row["sequenceId"], str(row["maviTrackId"])) if row["state"] == "matched" and row["maviTrackId"] else None
        hit = bool(mavi and wanted & set(texts.get(mavi, [])))
        returned = set().union(*(by_text.get(w, set()) for w in wanted)) if wanted else set()
        rows[f"{key[0]}/{key[1]}"] = {"state": row["state"], "oracleReadable": bool(row["result"]["oracleReadable"]),
                                      "hit": hit, "otherTracksReturned": len(returned - ({mavi} if mavi else set()))}
    return rows


PILOT = Path("E:/MAVI-Working/anpr-pilot-cuda")


def pilot_parity(a_dir: Path, a_rows: dict) -> dict[str, Any]:
    """Diagnostic: #226's live result on its 70 sequences vs Arm A offline (crop identity and per-Track hit)."""
    result = json.loads((PILOT / "out" / "pilot-result.json").read_bytes())
    pilot_hits = {f"{t['sequenceId']}/{t['gtTrackId']}": t["cause"] == "search_hit" for t in result["tracks"]}
    sequences = {t["sequenceId"] for t in result["tracks"]} | {s for s in result.get("perSequence", {})}
    pilot_crops = {p.stem for p in (PILOT / "exports").rglob("evidence/*.jpg")}
    index = json.loads((a_dir / "index.json").read_bytes())
    mine = set()
    for sequence in sorted(index["results"]):
        if sequence in sequences:
            for track in json.loads((a_dir / "results" / f"{sequence}.json").read_bytes())["tracks"]:
                mine |= {o["crop"]["sha256"] for o in track["observations"]}
    agree = sum(1 for k, v in pilot_hits.items() if k in a_rows and a_rows[k]["hit"] == v)
    return {"pilotSearchHits": sum(pilot_hits.values()), "pilotTracks": len(pilot_hits),
            "armAOfflineHitsOnPilotTracks": sum(a_rows[k]["hit"] for k in pilot_hits if k in a_rows),
            "perTrackHitAgreement": agree,
            "disagreements": sorted(k for k, v in pilot_hits.items() if k in a_rows and a_rows[k]["hit"] != v),
            "cropSetsEqual": pilot_crops == mine, "pilotCrops": len(pilot_crops), "armACropsOnPilotSequences": len(mine),
            "pilotCropsMissingFromArmA": len(pilot_crops - mine), "armACropsMissingFromPilot": len(mine - pilot_crops)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    for name in ("a", "a-eval", "b", "b-eval", "out"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        raise SystemExit("b1_plates_output_exists")
    detector, recogniser, parameters, identity = components()
    truth = truth_texts()
    cache: dict = {}
    arms = {}
    for name, arm_dir, eval_path in (("A", args.a, args.a_eval), ("B", args.b, args.b_eval)):
        texts = analyse_arm(arm_dir, cache, detector, recogniser, parameters)
        arms[name] = {"index": _sha((arm_dir / "index.json").read_bytes()), "eval": _sha(eval_path.read_bytes()),
                      "rows": hits(json.loads(eval_path.read_bytes()), texts, truth),
                      "tracksWithText": sum(1 for v in texts.values() if v)}
    a, b = arms["A"]["rows"], arms["B"]["rows"]
    if set(a) != set(b):
        raise SystemExit("b1_plates_population_differs")
    summary = {name: {"textUsableGtTracks": len(rows), "hits": sum(r["hit"] for r in rows.values()),
                      "oracleReadable": sum(r["oracleReadable"] for r in rows.values()),
                      "hitsAmongOracleReadable": sum(r["hit"] and r["oracleReadable"] for r in rows.values()),
                      "otherTracksReturned": sum(r["otherTracksReturned"] for r in rows.values())}
               for name, rows in (("A", a), ("B", b))}
    document = {"kind": "b1-plates-offline", "identity": identity, "distinctCropsAnalysed": len(cache),
                "pilotParity": pilot_parity(args.a, a),
                "summary": summary, "gained": sorted(k for k in a if not a[k]["hit"] and b[k]["hit"]),
                "lost": sorted(k for k in a if a[k]["hit"] and not b[k]["hit"]),
                "otherReturnedChanged": sorted(k for k in a if a[k]["otherTracksReturned"] != b[k]["otherTracksReturned"]),
                "arms": arms}
    data = json.dumps(document, indent=1, sort_keys=True).encode("utf-8")
    args.out.write_bytes(data)
    print(json.dumps({k: document[k] for k in ("distinctCropsAnalysed", "summary", "gained", "lost",
                                                "otherReturnedChanged")}, indent=1))
    print(f"{args.out} sha256={_sha(data)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
