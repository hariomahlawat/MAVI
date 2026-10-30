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

**Protocol ``s6-face-coverage-v2``** (``--protocol v2``), frozen 2026-10-29 before any detection on its clips
(owner decision D-S6-2(a); clips added by S2 amendment A6):

* **Unit and primary:** identical to v1 (score >= 0.9, shorter side >= 32 px), over the Person Tracks of the
  clips added by A6 only (``--clip``), so v1's numbers are not re-read.
* **Threshold rule (decides the role's detector threshold, 0.9 or 0.8).** The *band* is every detection with
  0.8 <= score < 0.9 and shorter side >= 32 px on those clips. Move to 0.8 only if all three hold:
  (i) the band holds at least 5 detections; (ii) in one diagnostic look at every band detection (technical
  rationale: decide whether the band is faces; recorded as counts only, no labels kept, the temporary sheet
  deleted) at least 90 % are faces, passed back as ``--band-face-count``; (iii) the band adds at least one
  Person Track with a usable face that 0.9 does not have. Otherwise keep 0.9.
* The run without ``--band-face-count`` writes the band list for the look and reports the decision as
  pending; the second run with the count computes it from the same detections.

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
BAND_LOW = 0.8
BAND_MINIMUM_DETECTIONS = 5
BAND_MINIMUM_FACE_SHARE = 0.9
BAND_MINIMUM_ADDED_TRACKS = 1


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--crops", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--detector", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--protocol", choices=("v1", "v2"), default="v1")
    parser.add_argument("--clip", action="append", help="v2: limit to these clip files (repeatable)")
    parser.add_argument("--band-face-count", type=int, help="v2: band detections judged faces in the diagnostic look")
    args = parser.parse_args()
    protocol = PROTOCOL if args.protocol == "v1" else "s6-face-coverage-v2"
    if args.protocol == "v2" and not args.clip:
        raise SystemExit("v2 needs --clip")

    import onnxruntime as ort  # noqa: PLC0415

    session = ort.InferenceSession(str(args.detector), providers=["CPUExecutionProvider"])
    rows = [line.split("|") for line in args.crops.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.protocol == "v2":
        rows = [row for row in rows if row[0] in set(args.clip)]
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
        "protocol": protocol,
        "detector": {"file": args.detector.name, "sha256": sha256(args.detector), "scoreThreshold": SCORE_THRESHOLD,
                     "nmsThreshold": NMS_THRESHOLD, "topK": TOP_K, "onnxruntime": ort.__version__},
        "primaryMinSide": PRIMARY_MIN_SIDE,
        "crops": len(rows), "hashMismatches": mismatches,
        "personTracks": total, "tracksWithUsableFace": usable_total,
        "usableShare": round(usable_total / total, 4) if total else None,
        "clips": clips,
    }
    if args.protocol == "v2":
        band = [
            {"clip": c["clip"], "trackId": c["trackId"], "observationId": c["observationId"], **f}
            for c in per_crop for f in c["faces"]
            if BAND_LOW <= f["score"] < SCORE_THRESHOLD and min(f["width"], f["height"]) >= PRIMARY_MIN_SIDE
        ]
        added = sorted(
            {b["trackId"] for b in band}
            - {c["trackId"] for c in per_crop for f in c["faces"]
               if f["score"] >= SCORE_THRESHOLD and min(f["width"], f["height"]) >= PRIMARY_MIN_SIDE}
        )
        if args.band_face_count is None:
            decision = "pending_diagnostic_look"
        else:
            if not 0 <= args.band_face_count <= len(band):
                raise SystemExit("--band-face-count out of range")
            holds = (len(band) >= BAND_MINIMUM_DETECTIONS
                     and args.band_face_count >= BAND_MINIMUM_FACE_SHARE * len(band)
                     and len(added) >= BAND_MINIMUM_ADDED_TRACKS)
            decision = "0.8" if holds else "0.9"
        summary["thresholdRule"] = {
            "bandDetections": len(band), "bandFaceCount": args.band_face_count,
            "tracksAddedByBand": len(added), "decision": decision,
        }
    args.out.mkdir(parents=True, exist_ok=True)
    if args.protocol == "v2":
        (args.out / "band-detections.json").write_text(json.dumps(band, indent=1) + "\n", encoding="utf-8")
    (args.out / "coverage-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (args.out / "coverage-detections.json").write_text(json.dumps(per_crop, indent=1) + "\n", encoding="utf-8")
    print(f"{protocol}: {usable_total}/{total} Person Tracks with a usable face; hash mismatches {mismatches}")
    for c in clips:
        print(f"  {c['clip']}: {c['tracksWithUsableFace']}/{c['personTracks']} usable, {c['tracksWithAnyFace']} any face, "
              f"crop side median {c['cropShorterSideMedian']}")
    return 0 if mismatches == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
