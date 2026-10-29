"""PoC S6 usable-face coverage on the demo corpus (register C5A.2; protocol ``s6-face-coverage-v1``).

Frozen before it ran (2026-10-29). The question is the roadmap entry decision for Stage 5A: on the demo
corpus, for what share of Person Tracks does the Evidence Set the ``faces`` role would read contain at least
one face large enough to embed?

* **Unit:** a Person Track of the Completed ProcessingRun of each demo clip.
* **Input:** every accepted ``EvidenceCrop`` of the Track's Observations, exactly the set a post-Track role
  leases (ADR-013 §4), each verified against its recorded size and SHA-256 before decoding.
* **Detector:** YuNet ``face_detection_yunet_2026may.onnx`` through ``mavi_vision.faces.detector`` (the role's
  own decoder) on ONNX Runtime CPU, at the crop's native resolution (padded, never resized). Publisher defaults:
  score >= 0.9, NMS IoU 0.3, top-k 5000.
* **Usable face (primary):** a detection whose box's shorter side is at least **32 px** in source pixels.
  Below about 32 px, face recognition accuracy collapses on surveillance-resolution benchmarks (e.g.
  QMUL-SurvFace, TinyFace), so smaller faces are recorded but not counted as usable.
* **Primary number:** per clip, Person Tracks with at least one usable face / Person Tracks.
* **Sensitivity (reported, not decided on):** shorter side 16, 24, 32, 48, 64 px × score 0.6, 0.9.
* **No ground truth:** detector output only. Coverage is "the detector found a face of usable size", not
  "a face is present"; false detections and missed faces are possible and are not labelled.

Usage::

    python -I tools/poc/faces_coverage.py --crops crops.tsv --evidence-root <root> \
        --detector face_detection_yunet_2026may.onnx --out <dir>

``crops.tsv`` is ``clip|run_id|track_id|observation_id|evidence_rank|storage_key|size_bytes|sha256``.
Requires ``onnxruntime``, ``numpy`` and ``Pillow`` (the ``embeddings-onnx-v1`` runtime).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src" / "vision"))

from mavi_vision.faces.detector import detect_faces  # noqa: E402

PROTOCOL = "s6-face-coverage-v1"
SCORE_THRESHOLD = 0.9
NMS_THRESHOLD = 0.3
TOP_K = 5000
PRIMARY_MIN_SIDE = 32
SENSITIVITY_SIDES = (16, 24, 32, 48, 64)
SENSITIVITY_SCORES = (0.6, 0.9)
FLOOR_SCORE = min(SENSITIVITY_SCORES)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--crops", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--detector", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    import onnxruntime as ort  # noqa: PLC0415

    session = ort.InferenceSession(str(args.detector), providers=["CPUExecutionProvider"])
    rows = [line.split("|") for line in args.crops.read_text(encoding="utf-8").splitlines() if line.strip()]
    per_crop: list[dict] = []
    mismatches = 0
    for clip, run_id, track_id, observation_id, rank, key, size, digest in rows:
        if not key.startswith("evidence/"):
            raise SystemExit(f"unexpected storage key {key}")
        path = args.evidence_root / key[len("evidence/"):]
        data = path.read_bytes()
        if len(data) != int(size) or hashlib.sha256(data).hexdigest() != digest:
            mismatches += 1
            continue
        rgb = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"))
        # One detection pass at the lowest sensitivity score; the higher score is a filter of the same pass.
        faces = detect_faces(session, rgb, score_threshold=FLOOR_SCORE, nms_threshold=NMS_THRESHOLD, top_k=TOP_K)
        per_crop.append({
            "clip": clip, "runId": run_id, "trackId": track_id, "observationId": observation_id,
            "evidenceRank": int(rank), "sha256": digest, "cropWidth": int(rgb.shape[1]), "cropHeight": int(rgb.shape[0]),
            "faces": [
                {"x": round(f.x, 2), "y": round(f.y, 2), "width": round(f.width, 2), "height": round(f.height, 2),
                 "score": round(f.score, 4), "landmarks": [[round(x, 2), round(y, 2)] for x, y in f.landmarks]}
                for f in faces
            ],
        })

    tracks: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for crop in per_crop:
        tracks[crop["clip"]][crop["trackId"]].append(crop)

    def track_has(crops: list[dict], min_side: float, score: float) -> bool:
        return any(min(f["width"], f["height"]) >= min_side and f["score"] >= score for c in crops for f in c["faces"])

    clips = []
    for clip in sorted(tracks):
        by_track = tracks[clip]
        n = len(by_track)
        usable = sum(track_has(c, PRIMARY_MIN_SIDE, SCORE_THRESHOLD) for c in by_track.values())
        any_face = sum(track_has(c, 0, SCORE_THRESHOLD) for c in by_track.values())
        crop_sides = [min(c["cropWidth"], c["cropHeight"]) for cs in by_track.values() for c in cs]
        face_sides = sorted(
            min(f["width"], f["height"]) for cs in by_track.values() for c in cs for f in c["faces"] if f["score"] >= SCORE_THRESHOLD
        )
        clips.append({
            "clip": clip,
            "personTracks": n,
            "crops": sum(len(c) for c in by_track.values()),
            "tracksWithAnyFace": any_face,
            "tracksWithUsableFace": usable,
            "usableShare": round(usable / n, 4) if n else None,
            "cropShorterSideMedian": float(np.median(crop_sides)) if crop_sides else None,
            "faceShorterSides": [round(s, 1) for s in face_sides],
            "sensitivity": {
                f"score{score}": {str(side): sum(track_has(c, side, score) for c in by_track.values()) for side in SENSITIVITY_SIDES}
                for score in SENSITIVITY_SCORES
            },
        })

    total = sum(c["personTracks"] for c in clips)
    usable_total = sum(c["tracksWithUsableFace"] for c in clips)
    summary = {
        "protocol": PROTOCOL,
        "detector": {"file": args.detector.name, "sha256": sha256(args.detector), "scoreThreshold": SCORE_THRESHOLD,
                     "nmsThreshold": NMS_THRESHOLD, "topK": TOP_K, "onnxruntime": ort.__version__},
        "primaryMinSide": PRIMARY_MIN_SIDE,
        "crops": len(rows), "hashMismatches": mismatches,
        "personTracks": total, "tracksWithUsableFace": usable_total,
        "usableShare": round(usable_total / total, 4) if total else None,
        "clips": clips,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "coverage-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (args.out / "coverage-detections.json").write_text(json.dumps(per_crop, indent=1) + "\n", encoding="utf-8")
    print(f"{PROTOCOL}: {usable_total}/{total} Person Tracks with a usable face; hash mismatches {mismatches}")
    for c in clips:
        print(f"  {c['clip']}: {c['tracksWithUsableFace']}/{c['personTracks']} usable, {c['tracksWithAnyFace']} any face, "
              f"crop side median {c['cropShorterSideMedian']}")
    return 0 if mismatches == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
