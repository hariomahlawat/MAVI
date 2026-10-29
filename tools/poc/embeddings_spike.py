"""PoC S4 spike: SigLIP 2 retrieval sanity and latency on held H3 Track evidence crops.

Development evidence only (ADR-020, principle 6a). The protocol below is frozen before any
outcome is read and is written to ``protocol.json`` next to the results; it is not changed
after results are seen.

Question: does the exported SigLIP 2 image tower, run offline from a local pack through ONNX
Runtime, rank another crop of the same Track above crops of other Tracks (a sanity check, not a
retrieval benchmark), and what does one crop cost on CPU and on CUDA?

Selection (deterministic, read-only over ``--exports``):
  * each ``subclass-measurement-export.json`` under the exports root, sorted by run id;
  * a crop is eligible when its JPEG decodes, its SHA-256 equals ``evidenceSha256`` and its
    shorter side is at least ``MIN_SIDE`` pixels;
  * a Track is eligible with at least two eligible crops; its pair is the earliest and the
    latest eligible crop by ``videoOffsetMs`` (largest temporal separation, so the pair is not
    two adjacent frames);
  * eligible Tracks are shuffled with ``SEED``; at most ``MAX_TRACKS_PER_RUN`` per run are kept,
    in shuffled order, until ``TRACKS`` Tracks (``2 * TRACKS`` crops) are selected.

Metrics (each crop is a query against the other 2*TRACKS-1 crops, cosine similarity):
  * R@1: the nearest neighbour is the partner crop; chance is 1/(2*TRACKS-1);
  * MRR and median rank of the partner;
  * same-run R@1: the gallery is restricted to crops from the same video (hard negatives: same
    scene, same lighting, often same class);
  * same-class R@1: the gallery is restricted to crops of the same object class;
  * the same metrics for a trivial baseline (16x16 RGB thumbnail, mean-centred, cosine), so a
    pass cannot come from scale or colour alone.
Sanity criterion (frozen): R@1 >= 0.50 overall and SigLIP MRR > baseline MRR. Otherwise the slice
stops and reports.

Latency: batch 1, ``WARMUP`` warm-up runs then every selected crop once, per device; median and
p95 of preprocessing+inference wall time; plus batch-16 throughput.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import statistics
import time
from pathlib import Path

import numpy as np
from PIL import Image

SEED = 20261029
MIN_SIDE = 24
TRACKS = 100
MAX_TRACKS_PER_RUN = 4
WARMUP = 10
IMAGE_SIZE = 224


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def select(exports_root: Path) -> tuple[list[dict], dict]:
    runs = sorted(exports_root.glob("*/subclass-measurement-export.json"))
    tracks: list[dict] = []
    rejected = {"hash_mismatch": 0, "too_small": 0, "missing": 0}
    for export_path in runs:
        export = json.loads(export_path.read_text(encoding="utf-8"))
        run_id = export["processingRun"]["processingRunId"]
        for track in sorted(export["tracks"], key=lambda t: t["id"]):
            crops = []
            for obs in track["observations"]:
                path = export_path.parent / obs["evidencePath"]
                if not path.is_file():
                    rejected["missing"] += 1
                    continue
                data = path.read_bytes()
                if sha256_bytes(data) != obs["evidenceSha256"]:
                    rejected["hash_mismatch"] += 1
                    continue
                with Image.open(io.BytesIO(data)) as image:
                    width, height = image.size
                if min(width, height) < MIN_SIDE:
                    rejected["too_small"] += 1
                    continue
                crops.append(
                    {
                        "path": str(path),
                        "sha256": obs["evidenceSha256"],
                        "offsetMs": obs["videoOffsetMs"],
                        "width": width,
                        "height": height,
                    }
                )
            if len(crops) >= 2:
                crops.sort(key=lambda c: (c["offsetMs"], c["sha256"]))
                tracks.append(
                    {
                        "runId": run_id,
                        "trackId": track["id"],
                        "objectClass": track["objectClass"],
                        "pair": [crops[0], crops[-1]],
                    }
                )
    rng = random.Random(SEED)
    rng.shuffle(tracks)
    per_run: dict[str, int] = {}
    chosen = []
    for track in tracks:
        if per_run.get(track["runId"], 0) >= MAX_TRACKS_PER_RUN:
            continue
        per_run[track["runId"]] = per_run.get(track["runId"], 0) + 1
        chosen.append(track)
        if len(chosen) == TRACKS:
            break
    stats = {"runs": len(runs), "eligibleTracks": len(tracks), "rejectedCrops": rejected,
             "selectedRuns": len(per_run)}
    return chosen, stats


def preprocess(path: str) -> np.ndarray:
    """SigLIP 2 fixed-resolution preprocessing: RGB, bilinear 224x224, (x/255 - 0.5)/0.5, NCHW."""
    with Image.open(path) as image:
        rgb = image.convert("RGB").resize((IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.BILINEAR)
    array = np.asarray(rgb, dtype=np.float32) / 255.0
    array = (array - 0.5) / 0.5
    return array.transpose(2, 0, 1)[None, ...]


def thumbnail(path: str) -> np.ndarray:
    with Image.open(path) as image:
        rgb = image.convert("RGB").resize((16, 16), Image.Resampling.BILINEAR)
    vector = np.asarray(rgb, dtype=np.float32).reshape(-1)
    return vector - vector.mean()


def l2(matrix: np.ndarray) -> np.ndarray:
    return matrix / np.linalg.norm(matrix, axis=1, keepdims=True).clip(min=1e-12)


def retrieval(vectors: np.ndarray, items: list[dict]) -> dict:
    sims = l2(vectors) @ l2(vectors).T
    n = len(items)
    ranks, same_run_hits, same_class_hits = [], [], []
    for i in range(n):
        partner = i ^ 1  # crops are stored pairwise: 2k and 2k+1 belong to Track k
        order = [j for j in np.argsort(-sims[i], kind="stable") if j != i]
        ranks.append(order.index(partner) + 1)
        run_gallery = [j for j in order if items[j]["runId"] == items[i]["runId"]]
        same_run_hits.append(run_gallery[0] == partner)
        class_gallery = [j for j in order if items[j]["objectClass"] == items[i]["objectClass"]]
        same_class_hits.append(class_gallery[0] == partner)
    same_run_sizes = [sum(1 for j in range(n) if j != i and items[j]["runId"] == items[i]["runId"])
                      for i in range(n)]
    return {
        "queries": n,
        "recallAt1": sum(1 for r in ranks if r == 1) / n,
        "recallAt5": sum(1 for r in ranks if r <= 5) / n,
        "mrr": sum(1 / r for r in ranks) / n,
        "medianRank": statistics.median(ranks),
        "chanceRecallAt1": 1 / (n - 1),
        "sameRunRecallAt1": sum(same_run_hits) / n,
        "sameRunChanceRecallAt1": statistics.mean(1 / s for s in same_run_sizes),
        "sameClassRecallAt1": sum(same_class_hits) / n,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exports", type=Path, required=True)
    parser.add_argument("--pack", type=Path, required=True, help="local Model Pack payload directory (vision.onnx)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--devices", default="cpu,cuda")
    parser.add_argument("--cuda-dll-dir", type=Path, help="directory holding the CUDA 12 / cuDNN 9 DLLs")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    if args.cuda_dll_dir:
        import os
        os.add_dll_directory(str(args.cuda_dll_dir))
        os.environ["PATH"] = str(args.cuda_dll_dir) + os.pathsep + os.environ["PATH"]
    import onnxruntime as ort

    protocol = {
        "seed": SEED, "minSide": MIN_SIDE, "tracks": TRACKS, "maxTracksPerRun": MAX_TRACKS_PER_RUN,
        "warmup": WARMUP, "imageSize": IMAGE_SIZE,
        "criterion": "recallAt1 >= 0.50 and siglip.mrr > baseline.mrr",
        "script": "tools/poc/embeddings_spike.py",
    }
    (args.out / "protocol.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")

    chosen, stats = select(args.exports)
    items = []
    for track in chosen:
        for crop in track["pair"]:
            items.append({"runId": track["runId"], "trackId": track["trackId"],
                          "objectClass": track["objectClass"], **crop})
    (args.out / "selection.json").write_text(
        json.dumps({"stats": stats, "crops": items}, indent=2), encoding="utf-8")

    vision_path = args.pack / "vision.onnx"

    results: dict = {"selection": stats, "classes": {}, "devices": {}}
    for item in items:
        results["classes"][item["objectClass"]] = results["classes"].get(item["objectClass"], 0) + 1

    embeddings = None
    for device in args.devices.split(","):
        providers = ["CPUExecutionProvider"] if device == "cpu" else [
            "CUDAExecutionProvider", "CPUExecutionProvider"]
        session = ort.InferenceSession(str(vision_path), providers=providers)
        actual = session.get_providers()[0]
        if device == "cuda" and actual != "CUDAExecutionProvider":
            results["devices"][device] = {"error": "cuda_provider_unavailable", "providers": session.get_providers()}
            continue
        name = session.get_inputs()[0].name
        for _ in range(WARMUP):
            session.run(None, {name: preprocess(items[0]["path"])})
        timings, vectors = [], []
        for item in items:
            start = time.perf_counter()
            output = session.run(None, {name: preprocess(item["path"])})[0]
            timings.append((time.perf_counter() - start) * 1000)
            vectors.append(output[0])
        batch = np.concatenate([preprocess(item["path"]) for item in items[:16]])
        start = time.perf_counter()
        for _ in range(3):
            session.run(None, {name: batch})
        batch_ms = (time.perf_counter() - start) * 1000 / 3
        timings.sort()
        matrix = np.stack(vectors)
        np.save(args.out / f"embeddings-{device}.npy", matrix)
        results["devices"][device] = {
            "provider": actual,
            "batch1MedianMs": statistics.median(timings),
            "batch1P95Ms": timings[int(0.95 * (len(timings) - 1))],
            "batch16MsPerCrop": batch_ms / 16,
            "retrieval": retrieval(matrix, items),
        }
        if embeddings is None:
            embeddings = matrix
        else:
            agreement = np.sum(l2(embeddings) * l2(matrix), axis=1)
            results["devices"][device]["minCosineVsFirstDevice"] = float(agreement.min())

    baseline = np.stack([thumbnail(item["path"]) for item in items])
    results["baseline16x16"] = retrieval(baseline, items)
    first = next(v for v in results["devices"].values() if "retrieval" in v)
    results["criterionMet"] = (first["retrieval"]["recallAt1"] >= 0.50
                               and first["retrieval"]["mrr"] > results["baseline16x16"]["mrr"])
    suffix = "-".join(args.devices.split(","))
    (args.out / f"results-{suffix}.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    return 0 if results["criterionMet"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
