"""PoC S5 person-attribute calibration on UPAR/PA-100K, protocol ``s5-zero-shot-calibration-v3``.

``docs/qualification/poc/s5-zero-shot-protocol-v3.json`` governs; this tool only executes it. Images are read in memory
from the pinned PA-100K ``data.zip`` in the controlled store and are never written anywhere; outputs (selection, scores,
calibration) go under ``--out`` (``E:\\MAVI-Controlled\\PoC\\S5\\upar``), never into the repository.

``select``    Eligible = a UPAR Task-1 row and shorter side >= 80 px. Tuning split: PA-100K official train labelled by
              UPAR train; held split: PA-100K official test labelled by UPAR val. 1500 per split, seeded.
``score``     SigLIP 2 softmax ``p`` per person attribute for every selected image (threshold-free).
``calibrate`` Per attribute, the protocol's rule on the tuning split through the runtime's Track decision (each image a
              one-crop Track, ``attributes_zero_shot_spike.track_decision``); held-split precision (Wilson 95%) and
              coverage. Writes ``calibration.json`` and ``thresholds.json`` (the four person attributes plus the
              predeclared vehicle-colour 0.5).
"""

from __future__ import annotations

import argparse
import io
import json
import random
import sys
import zipfile
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "src" / "vision"))
sys.path.insert(0, str(REPOSITORY / "tools" / "qualification"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image  # noqa: E402

from attributes.datasets.adapters import pa100k, upar  # noqa: E402
from attributes_zero_shot_spike import MANIFEST, PROFILE, track_decision, wilson  # noqa: E402
from mavi_vision.attributes.pipeline import load_attribute_pipeline  # noqa: E402
from mavi_vision.attributes.zero_shot import KIND_PRESENCE, PRESENT, parse_zero_shot_parameters  # noqa: E402

PROTOCOL = REPOSITORY / "docs/qualification/poc/s5-zero-shot-protocol-v3.json"
DATASETS = Path(r"E:\MAVI-Controlled\SourceMedia\S2c\2026-01\datasets")
PA100K = DATASETS / "pa-100k-2017"
UPAR = DATASETS / "upar-challenge-2027-a19ab2fb" / "data" / "annotations" / "task1"
SEED = 20261030_5
PER_SPLIT = 1500
MIN_SIDE = 80
SPLITS = {"tuning": ("train", "train"), "held": ("test", "val")}  # name -> (PA-100K split, UPAR split)
COLOURS = ("black", "blue", "brown", "green", "grey", "orange", "pink", "purple", "red", "white", "yellow")
PERSON_ATTRIBUTES = ("person-carried-bag", "person-headwear", "person-lower-colour", "person-upper-colour")
UNSCORABLE = "unscorable"


def map_labels(columns: dict) -> dict[str, str]:
    """Protocol v3 mapping of one UPAR Task-1 row to the frozen vocabulary."""
    labels = {}
    for attribute, prefix in (("person-upper-colour", "UpperBody-Color-"), ("person-lower-colour", "LowerBody-Color-")):
        positives = [c for c in COLOURS if columns[prefix + c.capitalize()] == 1]
        labels[attribute] = positives[0] if len(positives) == 1 and columns[prefix + "Other"] == 0 else UNSCORABLE
    labels["person-carried-bag"] = "present" if columns["Accessory-Backpack"] == 1 or columns["Accessory-Bag"] == 1 else "absent"
    labels["person-headwear"] = "present" if columns["Accessory-Hat"] == 1 else "absent"
    return labels


def _pinned(path: Path, expected: tuple[int, str]) -> bytes:
    import hashlib
    data = path.read_bytes()
    if (len(data), hashlib.sha256(data).hexdigest()) != expected:
        raise SystemExit(f"not the pinned bytes: {path}")
    return data


def select(out: Path) -> None:
    rows = pa100k.parse_annotation(zipfile.ZipFile(PA100K / pa100k.ANNOTATION_ARCHIVE).read(pa100k.ANNOTATION_MEMBER))
    split_of = {row["memberPath"]: row["sourceSplit"] for row in rows}
    truth = {}
    for upar_split in ("train", "val"):
        relative = upar.FILES[upar_split]
        data = _pinned(UPAR / upar_split / "gt.csv", upar.PINNED_FILES[relative])
        parsed, _ = upar.parse_csv(data, upar_split)
        for member, row in parsed.items():
            truth[member] = (upar_split, row["labels"])
    archive = zipfile.ZipFile(PA100K / pa100k.IMAGE_ARCHIVE)
    rng = random.Random(SEED)
    selection = {}
    stats = {}
    for name, (pa_split, upar_split) in SPLITS.items():
        pool = sorted(m for m, s in split_of.items() if s == pa_split and m in truth and truth[m][0] == upar_split)
        rng.shuffle(pool)
        chosen, seen, too_small = [], 0, 0
        for member in pool:
            seen += 1
            with Image.open(io.BytesIO(archive.read(member))) as image:
                width, height = image.size
            if min(width, height) < MIN_SIDE:
                too_small += 1
                continue
            chosen.append({"member": member, "width": width, "height": height, "labels": map_labels(truth[member][1])})
            if len(chosen) == PER_SPLIT:
                break
        stats[name] = {"paSplit": pa_split, "uparSplit": upar_split, "pool": len(pool), "examined": seen,
                       "tooSmall": too_small, "eligibleShareOfExamined": round((seen - too_small) / seen, 4),
                       "selected": len(chosen)}
        selection[name] = chosen
    out.mkdir(parents=True, exist_ok=True)
    (out / "selection.json").write_text(json.dumps({"protocol": "s5-zero-shot-calibration-v3", "seed": SEED,
                                                    "stats": stats, "splits": selection}, indent=1), encoding="utf-8")
    print(json.dumps(stats, indent=2))


def score(out: Path, model_root: Path, device: str) -> None:
    from mavi_vision.attributes.zero_shot import SiglipZeroShotInferencer
    from mavi_vision.embeddings.identity import verify_model_pack
    from mavi_vision.embeddings.model import l2_normalise_rows
    from mavi_vision.embeddings.onnx_model import load_onnx_model
    from mavi_vision.runtime.model_manifest_v2 import load_model_manifest_v2

    profile = load_attribute_pipeline(PROFILE)
    parameters = parse_zero_shot_parameters(profile.parameters, profile.schema)
    model = load_onnx_model(verify_model_pack(load_model_manifest_v2(MANIFEST), model_root), dimension=768, device_policy=device)
    inferencer = SiglipZeroShotInferencer(model, parameters)
    archive = zipfile.ZipFile(PA100K / pa100k.IMAGE_ARCHIVE)
    selection = json.loads((out / "selection.json").read_text(encoding="utf-8"))
    scores: dict[str, dict] = {}
    for name, items in selection["splits"].items():
        for item in items:
            image = l2_normalise_rows(model.embed_images([archive.read(item["member"])]), 768)[0]
            probabilities = {}
            for definition in profile.schema.for_object_class("person"):
                p = inferencer.probabilities(image, definition.attribute_type)
                if parameters.attributes[definition.attribute_type].kind == KIND_PRESENCE:
                    probabilities[definition.attribute_type] = {PRESENT: float(p[0])}
                else:
                    probabilities[definition.attribute_type] = {v: float(p[i]) for i, v in enumerate(definition.values)}
            scores[item["member"]] = probabilities
    (out / f"scores-{device}.json").write_text(json.dumps({"protocol": "s5-zero-shot-calibration-v3",
                                                          "parametersSha256": profile.parameters_sha256,
                                                          "device": device, "scores": scores}), encoding="utf-8")
    print(f"scored {len(scores)} images on {device}")


def calibrate(out: Path, device: str) -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    persons = protocol["persons"]
    profile = load_attribute_pipeline(PROFILE)
    selection = json.loads((out / "selection.json").read_text(encoding="utf-8"))["splits"]
    scores = json.loads((out / f"scores-{device}.json").read_text(encoding="utf-8"))["scores"]
    grid = [round(persons["thresholdGrid"]["start"] + i * persons["thresholdGrid"]["step"], 4)
            for i in range(persons["thresholdGrid"]["count"])]
    report, thresholds = {}, {}
    for name in PERSON_ATTRIBUTES:
        definition = next(item for item in profile.schema.attributes if item.attribute_type == name)

        def measure(split: str, threshold: float) -> dict:
            items = selection[split]
            observed = correct = scorable = 0
            for item in items:
                label = item["labels"][name]
                scorable += int(label != UNSCORABLE)
                track = {"crops": [{"sha256": "0" * 64, "small": False, "probabilities": scores[item["member"]]}]}
                decision = track_decision(track, definition, threshold, profile.aggregation)
                if decision is None:
                    continue
                observed += 1
                correct += int(decision == label)
            return {"images": len(items), "scorable": scorable, "observed": observed, "correct": correct,
                    "precision": round(correct / observed, 4) if observed else None,
                    "precisionWilson95": wilson(correct, observed),
                    "coverage": round(observed / len(items), 4) if items else None}

        chosen = None
        sweep = []
        for threshold in grid:
            result = measure("tuning", threshold)
            sweep.append({"threshold": threshold, **{k: result[k] for k in ("observed", "precision")}})
            if chosen is None and result["observed"] >= persons["minimumObserved"] and result["precision"] is not None \
                    and result["precision"] >= persons["targetPrecision"]:
                chosen = threshold
        thresholds[name] = chosen if chosen is not None else persons["fallbackThreshold"]
        report[name] = {"threshold": thresholds[name], "metTarget": chosen is not None, "tuningSweep": sweep,
                        "tuning": measure("tuning", thresholds[name]), "held": measure("held", thresholds[name])}
    thresholds["vehicle-colour"] = 0.5  # predeclared, uncalibrated (protocol v3 'vehicles')
    (out / "calibration.json").write_text(json.dumps({"protocol": protocol["protocolId"], "attributes": report}, indent=2),
                                          encoding="utf-8")
    (out / "thresholds.json").write_text(json.dumps(dict(sorted(thresholds.items())), indent=2), encoding="utf-8")
    print(json.dumps({k: {"t": v["threshold"], "met": v["metTarget"], "held": v["held"]} for k, v in report.items()}, indent=1))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=["select", "score", "calibrate"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model-root", type=Path)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    args = parser.parse_args()
    if args.step == "select":
        select(args.out)
    elif args.step == "score":
        if args.model_root is None:
            parser.error("--model-root is required for score")
        score(args.out, args.model_root, args.device)
    else:
        calibrate(args.out, args.device)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
