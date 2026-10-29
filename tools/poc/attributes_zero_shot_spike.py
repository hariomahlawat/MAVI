"""PoC S5 spike: zero-shot SigLIP 2 attribute scores over held H3 crops, and per-attribute abstention calibration.

Three steps; each writes under ``--out`` (``E:\\MAVI-Controlled\\PoC\\S5\\spike``), never into the repository.

``select``   Seeded held set from the read-only H3 exports (the S4 spike's source): Person and Vehicle Tracks
             with a crop whose shorter side is at least 80 px; per Track the largest such crop; at most
             ``MAX_TRACKS_PER_RUN`` Tracks per run; ``PER_CLASS`` per class; each crop's SHA-256 is checked against
             the export. Every item is assigned to the ``calibration`` or ``check`` half by a seeded shuffle.
             Writes ``selection.json``, ``labels-template.csv`` (one row per crop, an empty column per
             applicable attribute) and ``contact-sheet.html``.
``score``    The committed zero-shot inferencer (``src/vision/config/attributes``) over every selected crop:
             per attribute the softmax ``p`` per value. Writes ``scores-<device>.json``.
``calibrate`` Reads ``labels.csv`` (the template, filled in) and the frozen ``protocol.json``; per attribute
             chooses the threshold on the calibration half by the protocol's rule and reports precision and
             coverage on the check half. Writes ``calibration.json`` and ``thresholds.json``.

A label is a schema value, ``present`` / ``absent`` for a presence attribute, or ``unscorable``. Unscorable crops
are excluded from precision and counted in coverage only as "should abstain".
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

from mavi_vision.attributes.pipeline import load_attribute_pipeline  # noqa: E402
from mavi_vision.attributes.zero_shot import KIND_PRESENCE, parse_zero_shot_parameters  # noqa: E402

PROFILE = REPOSITORY / "src/vision/config/attributes/development-attributes-siglip2-zero-shot-v1.json"
MANIFEST = REPOSITORY / "models/manifests/embeddings-siglip2-base-p16-224-dev-v1.json"
SEED = 20261029_5
PER_CLASS = 100
MAX_TRACKS_PER_RUN = 4
MIN_SIDE = 80
CLASSES = {"Person": "person", "Vehicle": "vehicle"}


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
            best = None
            for obs in track["observations"]:
                path = export_path.parent / obs["evidencePath"]
                if not path.is_file():
                    continue
                data = path.read_bytes()
                if sha256_bytes(data) != obs["evidenceSha256"]:
                    raise SystemExit(f"hash mismatch: {path}")
                with Image.open(io.BytesIO(data)) as image:
                    width, height = image.size
                if min(width, height) < MIN_SIDE:
                    continue
                key = (width * height, obs["evidenceSha256"])
                if best is None or key > best[0]:
                    best = (key, {"path": str(path), "sha256": obs["evidenceSha256"], "width": width, "height": height})
            if best is not None:
                tracks[track["objectClass"]].append({"runId": run_id, "trackId": track["id"],
                                                     "objectClass": track["objectClass"], **best[1]})
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
        stats[name] = {"eligibleTracks": len(pool), "selected": len(picked), "runs": len(per_run)}
        chosen.extend(picked)
    rng.shuffle(chosen)
    for index, item in enumerate(chosen):
        item["itemId"] = f"s5-{index:03d}"
        item["half"] = "calibration" if index % 2 == 0 else "check"
    chosen.sort(key=lambda item: item["itemId"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "selection.json").write_text(json.dumps({"seed": SEED, "stats": stats, "items": chosen}, indent=2),
                                        encoding="utf-8")
    columns = [item.attribute_type for item in profile.schema.attributes]
    with open(out / "labels-template.csv", "w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["itemId", "objectClass", *columns])
        for item in chosen:
            object_class = CLASSES[item["objectClass"]]
            writer.writerow([item["itemId"], item["objectClass"],
                             *["" if definition.object_class == object_class else "n/a" for definition in profile.schema.attributes]])
    rows = "\n".join(
        f'<figure><img src="file:///{html.escape(item["path"].replace(chr(92), "/"))}"><figcaption>{item["itemId"]} '
        f'{item["objectClass"]} {item["width"]}x{item["height"]}</figcaption></figure>'
        for item in chosen)
    vocabulary = "<br>".join(f"<b>{d.attribute_type}</b>: {', '.join(d.values)}"
                             + (" (label present / absent)" if d.values == ("present",) else "")
                             + " or unscorable" for d in profile.schema.attributes)
    (out / "contact-sheet.html").write_text(
        "<!doctype html><meta charset=utf-8><title>S5 held crops</title><style>figure{display:inline-block;margin:6px;"
        "text-align:center;font:12px sans-serif}img{max-height:220px;max-width:220px}</style>"
        f"<p>{vocabulary}</p>{rows}", encoding="utf-8")
    print(json.dumps(stats, indent=2))


def score(out: Path, model_root: Path, device: str) -> None:
    from mavi_vision.embeddings.identity import verify_model_pack
    from mavi_vision.embeddings.model import l2_normalise_rows
    from mavi_vision.embeddings.onnx_model import load_onnx_model
    from mavi_vision.attributes.zero_shot import SiglipZeroShotInferencer
    from mavi_vision.runtime.model_manifest_v2 import load_model_manifest_v2

    profile, parameters = _profile()
    manifest = load_model_manifest_v2(MANIFEST)
    model = load_onnx_model(verify_model_pack(manifest, model_root), dimension=768, device_policy=device)
    inferencer = SiglipZeroShotInferencer(model, parameters)
    selection = json.loads((out / "selection.json").read_text(encoding="utf-8"))
    results = []
    for item in selection["items"]:
        data = Path(item["path"]).read_bytes()
        if sha256_bytes(data) != item["sha256"]:
            raise SystemExit(f"hash mismatch: {item['path']}")
        image = l2_normalise_rows(model.embed_images([data]), 768)[0]
        object_class = CLASSES[item["objectClass"]]
        probabilities = {}
        for definition in profile.schema.for_object_class(object_class):
            p = inferencer.probabilities(image, definition.attribute_type)
            if parameters.attributes[definition.attribute_type].kind == KIND_PRESENCE:
                probabilities[definition.attribute_type] = {"present": float(p[0]), "absent": float(p[1])}
            else:
                probabilities[definition.attribute_type] = {v: float(p[i]) for i, v in enumerate(definition.values)}
        results.append({"itemId": item["itemId"], "probabilities": probabilities})
    document = {"profileSha256": profile.sha256, "parametersSha256": profile.parameters_sha256,
                "device": device, "items": results}
    (out / f"scores-{device}.json").write_text(json.dumps(document, indent=2), encoding="utf-8")
    print(f"scored {len(results)} crops on {device}")


def calibrate(out: Path, device: str) -> None:
    protocol = json.loads((REPOSITORY / "docs/qualification/poc/s5-zero-shot-protocol-v1.json").read_text(encoding="utf-8"))
    profile, parameters = _profile()
    selection = {item["itemId"]: item for item in json.loads((out / "selection.json").read_text(encoding="utf-8"))["items"]}
    scores = {item["itemId"]: item["probabilities"] for item in
              json.loads((out / f"scores-{device}.json").read_text(encoding="utf-8"))["items"]}
    with open(out / "labels.csv", newline="", encoding="utf-8") as stream:
        labels = {row["itemId"]: row for row in csv.DictReader(stream)}
    grid = [round(protocol["thresholdGrid"]["start"] + i * protocol["thresholdGrid"]["step"], 4)
            for i in range(protocol["thresholdGrid"]["count"])]
    target, minimum_observed, fallback = protocol["targetPrecision"], protocol["minimumObserved"], protocol["fallbackThreshold"]
    report: dict[str, dict] = {}
    thresholds: dict[str, float] = {}
    for definition in profile.schema.attributes:
        name = definition.attribute_type
        presence = parameters.attributes[name].kind == KIND_PRESENCE

        def decide(item_id: str, threshold: float) -> str | None:
            p = scores[item_id][name]
            if presence:
                return "present" if p["present"] >= threshold else None
            best = max(definition.values, key=lambda value: (p[value], -definition.values.index(value)))
            return best if p[best] >= threshold else None

        def measure(half: str, threshold: float) -> dict:
            items = [i for i, item in selection.items() if item["half"] == half and name in scores[i]]
            observed = correct = scorable = 0
            for item_id in items:
                label = labels[item_id][name].strip()
                decision = decide(item_id, threshold)
                if label not in ("", "unscorable", "n/a"):
                    scorable += 1
                if decision is None:
                    continue
                observed += 1
                correct += int(decision == label)
            return {"items": len(items), "scorable": scorable, "observed": observed, "correct": correct,
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
