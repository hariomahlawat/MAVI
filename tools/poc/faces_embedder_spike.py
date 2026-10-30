"""PoC S6 embedder spike: AdaFace IR-50 against SFace on LFW (protocol ``s6-embedder-spike-v1``; ADR-022 §2, §7).

Frozen before it ran (2026-10-29). Plan decision D6 lets the spike choose the embedder. ADR-017 asks for an
established benchmark, and LFW's standard 6,000-pair verification protocol is the one used here. Development
evidence only: no MAVI-owned labels, and the LFW images never leave the Development host.

* **Data:** LFW (original, not funneled), ``lfw.tgz`` and ``pairs.txt`` as distributed by scikit-learn's mirror;
  10 folds of 300 matched and 300 mismatched pairs.
* **Pipeline:** the role's own code: ``mavi_vision.faces.detector`` (YuNet 2026may) on the whole image, score
  >= 0.5; the detection whose box contains the image centre with the highest score (else the highest score);
  ``mavi_vision.faces.align`` to 112×112; the pack's embedder; L2-normalised; cosine. A pair with an undetected
  image scores -1 (counted as a failure, never dropped).
* **Conditions:** ``native``; ``face32``: the whole image downscaled (bilinear) so the native detection's shorter
  side becomes 32 px, then detected, aligned and embedded again: the CCTV-like case the coverage protocol calls
  the floor of a usable face.
* **Metrics:** 10-fold accuracy (each fold's threshold maximises accuracy on the other nine folds); the cosine at
  FAR = 0.1 % and 1 % over the 3,000 mismatched pairs, and TAR there.
* **Decision (frozen):** AdaFace if its ONNX parity >= 0.999, its ``native`` accuracy >= 99.0 % and its ``face32``
  accuracy >= SFace's; otherwise SFace if its ``native`` accuracy >= 98.0 %; otherwise stop and report.
* **Reference threshold** of the chosen pipeline: its ``face32`` cosine at FAR = 0.1 %.

    python -I tools/poc/faces_embedder_spike.py --lfw <dir with lfw/> --pairs pairs.txt --packs <pack root> --out <dir>
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src" / "vision"))

from mavi_vision.faces.align import align_face  # noqa: E402
from mavi_vision.faces.detector import detect_faces  # noqa: E402

PROTOCOL = "s6-embedder-spike-v1"
DETECTION_SCORE = 0.5
FACE32 = 32.0
PACKS = {
    "adaface": ("faces-yunet-adaface-ir50-dev-v1", "adaface-ir50-v1"),
    "sface": ("faces-yunet-sface-dev-v1", "sface-v1"),
}


def embedder_input(aligned: np.ndarray, preprocessing: str) -> np.ndarray:
    """``[3, 112, 112]`` float32 from an aligned RGB face: AdaFace ``(x/255 - 0.5)/0.5``; SFace raw 0-255 RGB."""
    x = aligned.astype(np.float32)
    if preprocessing == "adaface-ir50-v1":
        x = (x / 255.0 - 0.5) / 0.5
    return x.transpose(2, 0, 1)


def pick(faces, height: int, width: int):
    if not faces:
        return None
    cx, cy = width / 2.0, height / 2.0
    central = [f for f in faces if f.x <= cx <= f.x + f.width and f.y <= cy <= f.y + f.height]
    return max(central or faces, key=lambda f: f.score)


def read_pairs(path: Path) -> list[tuple[str, int, str, int, bool]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    pairs = []
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) == 3:
            pairs.append((parts[0], int(parts[1]), parts[0], int(parts[2]), True))
        elif len(parts) == 4:
            pairs.append((parts[0], int(parts[1]), parts[2], int(parts[3]), False))
    if len(pairs) != 6000:
        raise SystemExit(f"expected 6000 pairs, read {len(pairs)}")
    return pairs


def ten_fold_accuracy(scores: np.ndarray, same: np.ndarray) -> float:
    folds = np.arange(len(scores)) // 600
    candidates = np.unique(scores)
    accuracies = []
    for fold in range(10):
        train, test = folds != fold, folds == fold
        best = max(candidates, key=lambda t: (((scores[train] >= t) == same[train]).mean(), -t))
        accuracies.append(((scores[test] >= best) == same[test]).mean())
    return float(np.mean(accuracies))


def operating_point(scores: np.ndarray, same: np.ndarray, far: float) -> dict:
    negatives = np.sort(scores[~same])[::-1]
    allowed = int(np.floor(far * len(negatives)))
    threshold = float(np.nextafter(negatives[allowed], np.inf))
    return {"far": far, "threshold": round(threshold, 4), "tar": round(float((scores[same] >= threshold).mean()), 4)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lfw", type=Path, required=True)
    parser.add_argument("--pairs", type=Path, required=True)
    parser.add_argument("--packs", type=Path, required=True)
    parser.add_argument("--build-record", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    import onnxruntime as ort  # noqa: PLC0415

    ort.set_default_logger_severity(3)
    providers = ["CPUExecutionProvider"]
    detector = ort.InferenceSession(str(args.packs / PACKS["adaface"][0] / "detector.onnx"), providers=providers)
    embedders = {name: ort.InferenceSession(str(args.packs / pack / "embedder.onnx"), providers=providers) for name, (pack, _) in PACKS.items()}
    pairs = read_pairs(args.pairs)
    same = np.array([p[4] for p in pairs])
    images = sorted({(a, i) for a, i, _, _, _ in pairs} | {(b, j) for _, _, b, j, _ in pairs})

    vectors = {(name, condition): {} for name in PACKS for condition in ("native", "face32")}
    failures = {"native": 0, "face32": 0}
    sides: list[float] = []
    latency = {name: [] for name in PACKS}
    for person, index in images:
        path = args.lfw / "lfw" / person / f"{person}_{index:04d}.jpg"
        rgb = np.asarray(Image.open(path).convert("RGB"))
        native = pick(detect_faces(detector, rgb, score_threshold=DETECTION_SCORE, nms_threshold=0.3, top_k=5000), *rgb.shape[:2])
        if native is None:
            failures["native"] += 1
            failures["face32"] += 1
            continue
        sides.append(native.min_side)
        scale = FACE32 / native.min_side
        small = np.asarray(Image.fromarray(rgb).resize(
            (max(1, round(rgb.shape[1] * scale)), max(1, round(rgb.shape[0] * scale))), Image.Resampling.BILINEAR))
        low = pick(detect_faces(detector, small, score_threshold=DETECTION_SCORE, nms_threshold=0.3, top_k=5000), *small.shape[:2])
        if low is None:
            failures["face32"] += 1
        for name, (_, preprocessing) in PACKS.items():
            for condition, image, face in (("native", rgb, native), ("face32", small, low)):
                if face is None:
                    continue
                batch = embedder_input(align_face(image, face.landmarks), preprocessing)[None]
                started = time.perf_counter()
                output = embedders[name].run(None, {embedders[name].get_inputs()[0].name: batch})[0][0]
                latency[name].append((time.perf_counter() - started) * 1000.0)
                vectors[(name, condition)][(person, index)] = output / np.linalg.norm(output)

    results = {}
    for (name, condition), table in vectors.items():
        scores = np.array([
            float(table[(a, i)] @ table[(b, j)]) if (a, i) in table and (b, j) in table else -1.0
            for a, i, b, j, _ in pairs
        ])
        results.setdefault(name, {})[condition] = {
            "tenFoldAccuracy": round(ten_fold_accuracy(scores, same), 4),
            "pairsWithFailure": int((scores == -1.0).sum()),
            "operatingPoints": [operating_point(scores, same, far) for far in (0.001, 0.01)],
        }
        results[name]["embedLatencyMsMedian"] = round(statistics.median(latency[name]), 2)

    build = json.loads(args.build_record.read_text(encoding="utf-8"))
    parity = build["packs"][PACKS["adaface"][0]]["build"]["parityMinCosine"]
    ada, sf = results["adaface"], results["sface"]
    if parity >= 0.999 and ada["native"]["tenFoldAccuracy"] >= 0.99 and ada["face32"]["tenFoldAccuracy"] >= sf["face32"]["tenFoldAccuracy"]:
        chosen = "adaface"
    elif sf["native"]["tenFoldAccuracy"] >= 0.98:
        chosen = "sface"
    else:
        chosen = None
    summary = {
        "protocol": PROTOCOL,
        "images": len(images),
        "detectionFailures": failures,
        "nativeFaceShorterSideMedian": round(statistics.median(sides), 1),
        "adafaceParityMinCosine": parity,
        "onnxruntime": ort.__version__,
        "results": results,
        "chosen": chosen,
        "referenceThreshold": None if chosen is None else results[chosen]["face32"]["operatingPoints"][0],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "embedder-spike-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if chosen else 1


if __name__ == "__main__":
    raise SystemExit(main())
