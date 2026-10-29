"""PoC S5 spike: zero-shot SigLIP 2 attribute scores over held H3 Tracks, and per-attribute abstention calibration.

Protocol ``s5-zero-shot-calibration-v2`` (``docs/qualification/poc/s5-zero-shot-protocol-v2.json``). Calibration measures
the **Track-level decision that ships**: every accepted crop of a held Track is scored, crops under the minimum side
contribute zero scores, and the decision is the runtime's own ``abstention_score`` + ``aggregate_track``
(``mean-score-argmax`` at 0.5), evaluated for each candidate threshold. Labels are per Track.

Three steps; each writes under ``--out`` (``E:\\MAVI-Controlled\\PoC\\S5\\spike``), never into the repository.

``select``    Seeded held set from the read-only H3 exports (the S4 spike's source): Person and Vehicle Tracks with at
              least one crop whose shorter side is >= 80 px; all the Track's crops are kept (SHA-256 checked); at most
              ``MAX_TRACKS_PER_RUN`` Tracks per run; ``PER_CLASS`` per class; seeded calibration/check halves. Writes
              ``selection.json``, ``labels-template.csv`` (one row per Track) and ``contact-sheet.html`` (all the
              Track's crops side by side).
``score``     The SigLIP 2 Model Pack over every crop >= the minimum side: per attribute the softmax ``p`` per value
              (threshold-free). Writes ``scores-<device>.json``.
``calibrate`` Reads ``labels.csv`` (the template, filled in), refuses any unlabelled applicable cell, and per attribute
              chooses the threshold on the calibration half by the protocol's rule; reports precision (Wilson 95%)
              and coverage on the check half. Writes ``calibration.json`` and ``thresholds.json``.

A label is a schema value, ``present`` / ``absent`` for a presence attribute, or ``unscorable``. An Observed decision on
a Track labelled ``unscorable`` counts as wrong; an abstention is never wrong (it is coverage, reported separately).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import random
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "src" / "vision"))

from PIL import Image  # noqa: E402

from mavi_vision.attributes.contracts import LeaseTrack  # noqa: E402
from mavi_vision.attributes.pipeline import load_attribute_pipeline  # noqa: E402
from mavi_vision.attributes.predictions import ObservationResult, aggregate_track  # noqa: E402
from mavi_vision.attributes.zero_shot import KIND_PRESENCE, PRESENT, abstention_score, parse_zero_shot_parameters  # noqa: E402

PROFILE = REPOSITORY / "src/vision/config/attributes/development-attributes-siglip2-zero-shot-v1.json"
MANIFEST = REPOSITORY / "models/manifests/embeddings-siglip2-base-p16-224-dev-v1.json"
PROTOCOL = REPOSITORY / "docs/qualification/poc/s5-zero-shot-protocol-v2.json"
SEED = 20261029_5
PER_CLASS = 100
MAX_TRACKS_PER_RUN = 4
MIN_SIDE = 80
CLASSES = {"Person": "person", "Vehicle": "vehicle"}
UNSCORABLE = "unscorable"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def wilson(successes: int, trials: int, z: float = 1.959964) -> list[float] | None:
    if trials == 0:
        return None
    p = successes / trials
    centre = (p + z * z / (2 * trials)) / (1 + z * z / trials)
    half = z * ((p * (1 - p) / trials + z * z / (4 * trials * trials)) ** 0.5) / (1 + z * z / trials)
    return [round(centre - half, 4), round(centre + half, 4)]


def _profile():
    profile = load_attribute_pipeline(PROFILE)
    return profile, parse_zero_shot_parameters(profile.parameters, profile.schema)


def select(exports_root: Path, out: Path) -> None:
    profile, _ = _profile()
    tracks: dict[str, list[dict]] = {name: [] for name in CLASSES}
    for export_path in sorted(exports_root.glob("*/subclass-measurement-export.json")):
        export = json.loads(export_path.read_text(encoding="utf-8"))
        run_id = export["processingRun"]["processingRunId"]
        for track in sorted(export["tracks"], key=lambda t: t["id"]):
            if track["objectClass"] not in CLASSES:
                continue
            crops = []
            for obs in track["observations"]:
                path = export_path.parent / obs["evidencePath"]
                if not path.is_file():
                    continue
                data = path.read_bytes()
                if sha256_bytes(data) != obs["evidenceSha256"]:
                    raise SystemExit(f"hash mismatch: {path}")
                with Image.open(io.BytesIO(data)) as image:
                    width, height = image.size
                crops.append({"path": str(path), "sha256": obs["evidenceSha256"], "width": width, "height": height})
            if any(min(c["width"], c["height"]) >= MIN_SIDE for c in crops):
                crops.sort(key=lambda c: c["sha256"])
                tracks[track["objectClass"]].append({"runId": run_id, "trackId": track["id"],
                                                     "objectClass": track["objectClass"], "crops": crops})
    rng = random.Random(SEED)
    chosen: list[dict] = []
    stats = {}
    for name in CLASSES:
        pool = tracks[name]
        rng.shuffle(pool)
        per_run: dict[str, int] = {}
        picked = []
        for item in pool:
            if per_run.get(item["runId"], 0) >= MAX_TRACKS_PER_RUN:
                continue
            per_run[item["runId"]] = per_run.get(item["runId"], 0) + 1
            picked.append(item)
            if len(picked) == PER_CLASS:
                break
        stats[name] = {"eligibleTracks": len(pool), "selected": len(picked), "runs": len(per_run),
                       "crops": sum(len(item["crops"]) for item in picked)}
        chosen.extend(picked)
    rng.shuffle(chosen)
    for index, item in enumerate(chosen):
        item["itemId"] = f"s5-{index:03d}"
        item["half"] = "calibration" if index % 2 == 0 else "check"
    chosen.sort(key=lambda item: item["itemId"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "selection.json").write_text(json.dumps({"protocol": "s5-zero-shot-calibration-v2", "seed": SEED,
                                                    "stats": stats, "items": chosen}, indent=2), encoding="utf-8")
    columns = [item.attribute_type for item in profile.schema.attributes]
    with open(out / "labels-template.csv", "w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["itemId", "objectClass", *columns])
        for item in chosen:
            object_class = CLASSES[item["objectClass"]]
            writer.writerow([item["itemId"], item["objectClass"],
                             *["" if definition.object_class == object_class else "n/a" for definition in profile.schema.attributes]])
    rows = "\n".join(
        f'<div class="track"><b>{item["itemId"]} {item["objectClass"]}</b><br>'
        + "".join(f'<img src="file:///{html.escape(c["path"].replace(chr(92), "/"))}" title="{c["width"]}x{c["height"]}">'
                  for c in item["crops"]) + "</div>"
        for item in chosen)
    vocabulary = "<br>".join(f"<b>{d.attribute_type}</b>: {', '.join(d.values)}"
                             + (" (label present / absent)" if d.values == (PRESENT,) else "")
                             + " or unscorable" for d in profile.schema.attributes)
    (out / "contact-sheet.html").write_text(
        "<!doctype html><meta charset=utf-8><title>S5 held Tracks</title><style>.track{display:inline-block;margin:6px;"
        "padding:4px;border:1px solid #ccc;font:12px sans-serif;vertical-align:top}img{max-height:200px;max-width:200px;"
        "margin:2px}</style><p>One label per Track (all its crops are shown). " + vocabulary + "</p>" + rows,
        encoding="utf-8")
    print(json.dumps(stats, indent=2))


def score(out: Path, model_root: Path, device: str) -> None:
    from mavi_vision.attributes.zero_shot import SiglipZeroShotInferencer
    from mavi_vision.embeddings.identity import verify_model_pack
    from mavi_vision.embeddings.model import l2_normalise_rows
    from mavi_vision.embeddings.onnx_model import load_onnx_model
    from mavi_vision.runtime.model_manifest_v2 import load_model_manifest_v2

    profile, parameters = _profile()
    manifest = load_model_manifest_v2(MANIFEST)
    model = load_onnx_model(verify_model_pack(manifest, model_root), dimension=768, device_policy=device)
    inferencer = SiglipZeroShotInferencer(model, parameters)
    selection = json.loads((out / "selection.json").read_text(encoding="utf-8"))
    results = []
    for item in selection["items"]:
        object_class = CLASSES[item["objectClass"]]
        crops = []
        for crop in item["crops"]:
            data = Path(crop["path"]).read_bytes()
            if sha256_bytes(data) != crop["sha256"]:
                raise SystemExit(f"hash mismatch: {crop['path']}")
            if min(crop["width"], crop["height"]) < parameters.minimum_crop_side:
                crops.append({"sha256": crop["sha256"], "small": True, "probabilities": None})
                continue
            image = l2_normalise_rows(model.embed_images([data]), 768)[0]
            probabilities = {}
            for definition in profile.schema.for_object_class(object_class):
                p = inferencer.probabilities(image, definition.attribute_type)
                if parameters.attributes[definition.attribute_type].kind == KIND_PRESENCE:
                    probabilities[definition.attribute_type] = {PRESENT: float(p[0])}
                else:
                    probabilities[definition.attribute_type] = {v: float(p[i]) for i, v in enumerate(definition.values)}
            crops.append({"sha256": crop["sha256"], "small": False, "probabilities": probabilities})
        results.append({"itemId": item["itemId"], "crops": crops})
    document = {"protocol": "s5-zero-shot-calibration-v2", "profileSha256": profile.sha256,
                "parametersSha256": profile.parameters_sha256, "device": device, "items": results}
    (out / f"scores-{device}.json").write_text(json.dumps(document, indent=2), encoding="utf-8")
    print(f"scored {sum(len(r['crops']) for r in results)} crops of {len(results)} Tracks on {device}")


def track_decision(scored: dict, definition, threshold: float, policy) -> str | None:
    """The runtime's Track decision for one attribute at ``threshold``: abstention_score per crop, then aggregate_track."""
    lease_track = LeaseTrack.model_validate_json(json.dumps({
        "trackId": "00000000-0000-7000-8000-000000000001", "objectClass": definition.object_class,
        "observations": [{"observationId": f"00000000-0000-7000-8000-{index:012d}", "role": "representative",
                          "evidenceRank": index, "sizeBytes": 1, "sha256": crop["sha256"]}
                         for index, crop in enumerate(scored["crops"])],
    }))
    observations = []
    for index, crop in enumerate(scored["crops"]):
        if crop["small"]:
            values = {value: 0.0 for value in definition.values}
        else:
            values = {value: abstention_score(crop["probabilities"][definition.attribute_type][value], threshold)
                      for value in definition.values}
        observations.append(ObservationResult(lease_track.observations[index].observation_id, index,
                                              scores={definition.attribute_type: values}))
    decision = aggregate_track(lease_track, tuple(observations), (definition,), policy).decisions[0]
    return decision.value if decision.outcome == "observed" else None


def calibrate(out: Path, device: str) -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    profile, _ = _profile()
    selection = {item["itemId"]: item for item in json.loads((out / "selection.json").read_text(encoding="utf-8"))["items"]}
    scores = {item["itemId"]: item for item in json.loads((out / f"scores-{device}.json").read_text(encoding="utf-8"))["items"]}
    with open(out / "labels.csv", newline="", encoding="utf-8") as stream:
        labels = {row["itemId"]: row for row in csv.DictReader(stream)}
    # Every applicable cell must carry a vocabulary label: an unlabelled Track is refused, never silently counted.
    for item_id, item in selection.items():
        row = labels.get(item_id)
        if row is None:
            raise SystemExit(f"unlabelled Track: {item_id}")
        for definition in profile.schema.for_object_class(CLASSES[item["objectClass"]]):
            allowed = set(definition.values) | {UNSCORABLE} | ({"absent"} if definition.values == (PRESENT,) else set())
            if row[definition.attribute_type].strip() not in allowed:
                raise SystemExit(f"invalid label {row[definition.attribute_type]!r} for {item_id} {definition.attribute_type}")
    grid = [round(protocol["thresholdGrid"]["start"] + i * protocol["thresholdGrid"]["step"], 4)
            for i in range(protocol["thresholdGrid"]["count"])]
    target, minimum_observed, fallback = protocol["targetPrecision"], protocol["minimumObserved"], protocol["fallbackThreshold"]
    report: dict[str, dict] = {}
    thresholds: dict[str, float] = {}
    for definition in profile.schema.attributes:
        name = definition.attribute_type

        def measure(half: str, threshold: float) -> dict:
            items = [i for i, item in selection.items() if item["half"] == half and CLASSES[item["objectClass"]] == definition.object_class]
            observed = correct = scorable = 0
            for item_id in items:
                label = labels[item_id][name].strip()
                scorable += int(label != UNSCORABLE)
                decision = track_decision(scores[item_id], definition, threshold, profile.aggregation)
                if decision is None:
                    continue
                observed += 1
                correct += int(decision == label)
            return {"tracks": len(items), "scorable": scorable, "observed": observed, "correct": correct,
                    "precision": correct / observed if observed else None,
                    "precisionWilson95": wilson(correct, observed),
                    "coverage": observed / len(items) if items else None}

        chosen = None
        for threshold in grid:
            result = measure("calibration", threshold)
            if result["observed"] >= minimum_observed and result["precision"] is not None and result["precision"] >= target:
                chosen = threshold
                break
        thresholds[name] = chosen if chosen is not None else fallback
        report[name] = {"threshold": thresholds[name], "metTarget": chosen is not None,
                        "calibration": measure("calibration", thresholds[name]),
                        "check": measure("check", thresholds[name])}
    (out / "calibration.json").write_text(json.dumps({"protocol": protocol, "attributes": report}, indent=2), encoding="utf-8")
    (out / "thresholds.json").write_text(json.dumps(thresholds, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=["select", "score", "calibrate"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--exports", type=Path, default=Path(r"E:\MAVI-Controlled\Stage3\H3-attempt2\exec\exports"))
    parser.add_argument("--model-root", type=Path)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    args = parser.parse_args()
    if args.step == "select":
        select(args.exports, args.out)
    elif args.step == "score":
        if args.model_root is None:
            parser.error("--model-root is required for score")
        score(args.out, args.model_root, args.device)
    else:
        calibrate(args.out, args.device)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
