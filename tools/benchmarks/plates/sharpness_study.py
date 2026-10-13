"""Stage 4 sharpness-floor diagnostic at large NearView crops (owner decision 2026-10-13). Measurement only.

Question: why can visibly useful large plate views fall below the generic ``sharpnessFloor`` (0.05)? Nothing here
changes the release profile, the selector or any acceptance criterion.

Inputs (all existing, hash-bound): the X1 baseline arm (the selector's own per-candidate records, which are the
release profile's exact values on the processed video frames), its E-B evaluation (association and per-frame native
reads at labelled frames with plate character height ≥ h_min), the frozen plate truth and the frozen descriptor
(source images).

Population: every labelled frame of a matched ground-truth vehicle whose plate is text-usable and at least
``h_min`` tall, where the matched MAVI Track has a candidate. "Readable" = a pinned instrument reads the plate
exactly at that native frame (the E-B oracle read).

Measured per frame:
* the selector's sharpness, area and qualification (from the run records);
* the production metric recomputed on the source JPEG at the MAVI box (validation of the image path);
* the same metric on the labelled plate rectangle only (dilution: is the plate itself sharp?);
* the same metric on the MAVI crop rescaled to a fixed 128-px height, and at ×0.5 (scale dependence).
Plus, across all Vehicle candidates, the within-Track rank correlation between sharpness and box area.

    python tools/benchmarks/plates/sharpness_study.py --x1 X1_DIR --h3 H3_DIR --truth TRUTH --out OUT.json
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path
from statistics import median
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "src" / "vision")]

from PIL import Image  # noqa: E402

from mavi_vision.common.analytical import NormalizedBoundingBox  # noqa: E402
from mavi_vision.quality.scoring import _normalized_sharpness  # noqa: E402
from tools.benchmarks.capabilities.plates import measure, truth as truths  # noqa: E402
from tools.benchmarks.core import descriptor as descriptors  # noqa: E402

FLOOR = 0.05
FIXED_HEIGHT = 128


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metric(pixels: np.ndarray) -> float:
    """The production sharpness of a whole RGB array (the box is the full array)."""
    return _normalized_sharpness(SimpleNamespace(image=pixels), NormalizedBoundingBox(0.0, 0.0, 1.0, 1.0))


def rescaled(pixels: np.ndarray, height: int) -> np.ndarray:
    image = Image.fromarray(pixels)
    width = max(1, round(image.width * height / max(1, image.height)))
    return np.asarray(image.resize((width, height), Image.Resampling.BILINEAR))


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3:
        return None
    ra, rb = np.argsort(np.argsort(a)).astype(float), np.argsort(np.argsort(b)).astype(float)
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def tertiles(values: list[float]) -> tuple[float, float]:
    return float(np.quantile(values, 1 / 3)), float(np.quantile(values, 2 / 3))


def study(x1: Path, h3: Path, truth_path: Path) -> dict:
    evaluation = json.loads((x1 / "baseline-eval.json").read_bytes())
    truth = json.loads(truth_path.read_bytes())
    plates = {(i["sequenceId"], i["gtTrackId"], i["frameIndex"]): i for i in truth["items"]}
    candidates: dict[str, dict[tuple[str, int], dict]] = {}
    within: list[float] = []
    for path in sorted((x1 / "baseline" / "candidates").glob("*.jsonl.gz")):
        sequence = path.name[: -len(".jsonl.gz")]
        by_track: dict[str, list[dict]] = {}
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                by_track.setdefault(str(row["track_id"]), []).append(row)
        candidates[sequence] = {(t, r["frame"]): r for t, rows in by_track.items() for r in rows}
        for rows in by_track.values():
            if len(rows) >= 10:
                rho = spearman([r["area"] for r in rows], [r["sharpness"] for r in rows])
                if rho is not None:
                    within.append(rho)
    document, _ = descriptors.load(h3 / "desc" / "frozen.json")
    entries = descriptors.reconcile(document, h3 / "src")
    frames = []
    for row in evaluation["rows"]:
        if row["state"] != "matched" or not row["usablePlate"] or not row["result"]:
            continue
        for oracle in row["result"]["oracleFrames"]:
            record = candidates[row["sequenceId"]].get((row["maviTrackId"], oracle["frameIndex"]))
            if record is None:
                continue
            item = plates[(row["sequenceId"], row["gtTrackId"], oracle["frameIndex"])]
            pixels = measure.decode_image(descriptors.read_verified(entries, h3 / "src", item["imagePath"]))
            height, width = pixels.shape[:2]
            box = NormalizedBoundingBox(record["box_x"], record["box_y"], record["box_w"], record["box_h"])
            crop = np.asarray(_crop_view(pixels, box))
            plate = next(p for p in item["plates"] if p["textUsable"])
            rect = measure.pixel_rect(*truths.polygon_rect(plate["polygon"]), width, height)
            frames.append({
                "track": f"{row['sequenceId']}/{row['gtTrackId']}", "frame": oracle["frameIndex"],
                "readable": any(r.get("agreement") is True for r in oracle["reads"].values()),
                "plateCharPx": oracle["charHeightPx"], "area": record["area"], "boxHeightPx": crop.shape[0],
                "selectorSharpness": record["sharpness"], "passSharpness": record["pass_sharpness"],
                "qualified": record["qualified"],
                "jpegSharpness": metric(crop),
                "plateSharpness": metric(measure.region(pixels, rect)),
                "fixedHeightSharpness": metric(rescaled(crop, FIXED_HEIGHT)),
                "halfScaleSharpness": metric(rescaled(crop, max(2, crop.shape[0] // 2)))})
    return summarise(frames, within) | {"frames": frames}


def _crop_view(pixels: np.ndarray, box: NormalizedBoundingBox) -> np.ndarray:
    from mavi_vision.quality.scoring import crop_region
    return crop_region(SimpleNamespace(image=pixels), box)


def summarise(frames: list[dict], within: list[float]) -> dict:
    readable = [f for f in frames if f["readable"]]
    failing = [f for f in readable if not f["passSharpness"]]
    low, high = tertiles([f["area"] for f in frames]) if frames else (0.0, 0.0)

    def band(f):
        return "small" if f["area"] <= low else "medium" if f["area"] <= high else "large"

    by_band = {}
    for name in ("small", "medium", "large"):
        group = [f for f in frames if band(f) == name]
        group_readable = [f for f in group if f["readable"]]
        by_band[name] = {"frames": len(group), "readable": len(group_readable),
                         "readableFailingSharpness": sum(not f["passSharpness"] for f in group_readable),
                         "medianSelectorSharpness": median([f["selectorSharpness"] for f in group]) if group else None}
    agree = [abs(f["jpegSharpness"] - f["selectorSharpness"]) for f in frames]
    return {
        "floor": FLOOR, "population": len(frames), "readable": len(readable),
        "readableFailingSharpness": len(failing),
        "notReadableFailingSharpness": sum(not f["passSharpness"] for f in frames if not f["readable"]),
        "areaTertileBounds": [low, high], "byArea": by_band,
        "withinTrackSpearmanAreaVsSharpness": {"tracks": len(within),
                                              "median": median(within) if within else None,
                                              "shareNegative": (sum(r < 0 for r in within) / len(within)) if within else None},
        "validationJpegVsVideoAbsDiff": {"median": median(agree) if agree else None, "max": max(agree) if agree else None},
        "readableFailing": {
            "medianSelectorSharpness": median([f["selectorSharpness"] for f in failing]) if failing else None,
            "medianPlateSharpness": median([f["plateSharpness"] for f in failing]) if failing else None,
            "plateRegionAtOrAboveFloor": sum(f["plateSharpness"] >= FLOOR for f in failing),
            "fixedHeightAtOrAboveFloor": sum(f["fixedHeightSharpness"] >= FLOOR for f in failing),
            "halfScaleAtOrAboveFloor": sum(f["halfScaleSharpness"] >= FLOOR for f in failing),
            "medianFixedHeightSharpness": median([f["fixedHeightSharpness"] for f in failing]) if failing else None,
            "medianHalfScaleSharpness": median([f["halfScaleSharpness"] for f in failing]) if failing else None},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--x1", type=Path, required=True)
    parser.add_argument("--h3", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit(f"refusing to overwrite {args.out}")
    result = study(args.x1, args.h3, args.truth)
    result["inputs"] = {"baselineIndex": _sha(args.x1 / "baseline" / "index.json"),
                        "baselineEval": _sha(args.x1 / "baseline-eval.json"), "truth": _sha(args.truth),
                        "descriptor": _sha(args.h3 / "desc" / "frozen.json")}
    data = json.dumps(result, indent=1, sort_keys=True).encode("utf-8")
    args.out.write_bytes(data)
    print(json.dumps({k: v for k, v in result.items() if k != "frames"}, indent=1))
    print(f"{args.out} sha256={hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
