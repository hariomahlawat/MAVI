"""Bounded plate annotation of a public vehicle-sequence benchmark for E-B (protocol §4.2 R8; Stage 4 PR-1).

Public vehicle-tracking benchmarks (BDD100K MOT) carry independent ground-truth vehicle Tracks with per-frame boxes but
no plate labels. This tool adds **verified** plate labels in three steps, keeping machine output apart from truth:

1. ``propose`` — machine pre-annotation, **never ground truth**. A pinned pretrained plate *detector* (not an OCR
   instrument, not MAVI) proposes one plate box per selected frame inside the ground-truth vehicle box. Frames are
   selected without MAVI predictions for the oracle (every labelled frame whose ground-truth vehicle box is at least
   ``MIN_VEHICLE_WIDTH`` pixels wide), plus — so the evidence can be located — the frames of the associated MAVI
   Track's evidence observations.
2. ``sheets`` — verification sheets. **Text sheets** show each candidate track's largest proposed plate, enlarged and
   numbered, with **no machine reading** printed, so the transcription is blind to both OCR instruments. **Geometry
   sheets** draw each proposed box on its vehicle crop for an accept/reject decision.
3. ``labels`` — a ``benchmark-plate-labels-v1`` document from the proposals and the verification decisions: a track
   carries a plate text only if its transcription was recorded as legible, and a frame carries a plate box only if
   its geometry was accepted. Everything else is absent (no label), never guessed.

The verifier's identity is recorded with the decisions. The OCR instruments never supply a label, so oracle and
evidence readability are measured against text they did not produce; the plate detector supplies geometry only, and
is neither an instrument nor the system under test.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from tools.benchmarks.capabilities.plates import instruments as instrument_module, measure
from tools.benchmarks.core import descriptor as descriptors
from tools.benchmarks.core.identity import canonical_json, read_artefact, require, sha256_hex, write_once
from tools.benchmarks.capabilities.vehicle_tracks import association as associations
from tools.benchmarks.core._stage3 import artefacts

VEHICLE_CLASSES = ("bus", "car", "motorcycle", "truck")
MIN_VEHICLE_WIDTH = 200  # px: frames whose ground-truth vehicle is at least this wide are oracle candidates
CANDIDATE_PLATE_WIDTH = 30  # px: a track enters text verification when its largest proposed plate is this wide
# The bounded labelling set (R8, fixed before any label): the SELECTED_TRACKS candidates with the widest proposed plate
# (ties: sequence, track), and per track its ORACLE_FRAMES widest-plate oracle frames plus every evidence frame. The
# selection reads only the annotation detector's geometry — never MAVI's outcome and never an OCR instrument.
SELECTED_TRACKS = 240
ORACLE_FRAMES = 3
PAD = 0.1  # detector input: the ground-truth vehicle box padded by 10 % per side (clamped)
DETECTOR_CONFIDENCE = 0.25
LABELS = "benchmark-plate-labels-v1"
PROPOSALS = "benchmark-plate-proposals-v1"


def _detector(spec_path: Path, model_root: Path):
    from open_image_models.detection.core.yolo_v9.inference import YoloV9Detector  # benchmark environment only

    spec = instrument_module.load_spec(spec_path)
    files = instrument_module.verify_model_files(spec, model_root)
    instrument_module.verify_packages(spec)
    options = instrument_module._single_thread_session_options()
    detector = YoloV9Detector(model_path=files[spec["configuration"]["onnxModel"]], class_labels=["License Plate"],
                              conf_thresh=DETECTOR_CONFIDENCE, providers=["CPUExecutionProvider"],
                              sess_options=options)
    body = {key: spec[key] for key in ("instrumentId", "adapter", "role", "packages", "configuration", "modelFiles")}
    return detector, {**body, "specSha256": sha256_hex(Path(spec_path).read_bytes())}


def _pixel_box(box: dict[str, float], width: int, height: int) -> tuple[float, float, float, float]:
    return box["x"] * width, box["y"] * height, (box["x"] + box["width"]) * width, (box["y"] + box["height"]) * height


def _propose_frame(detector, image: np.ndarray, vehicle: tuple[float, float, float, float]) -> dict[str, Any] | None:
    import cv2

    height, width = image.shape[:2]
    left, top, right, bottom = vehicle
    pad_x, pad_y = (right - left) * PAD, (bottom - top) * PAD
    rect = measure.pixel_rect(left - pad_x, top - pad_y, right + pad_x, bottom + pad_y, width, height)
    crop = measure.region(image, rect)
    best = None
    for result in detector.predict(cv2.cvtColor(crop, cv2.COLOR_RGB2BGR)):
        b = result.bounding_box
        x1, y1, x2, y2 = b.x1 + rect.left, b.y1 + rect.top, b.x2 + rect.left, b.y2 + rect.top
        # Inside the ground-truth vehicle box (the plate belongs to this vehicle, not a neighbour).
        if x1 < left - 1 or y1 < top - 1 or x2 > right + 1 or y2 > bottom + 1 or x2 <= x1 or y2 <= y1:
            continue
        if best is None or result.confidence > best["confidence"]:
            best = {"box": [float(x1), float(y1), float(x2), float(y2)], "confidence": float(result.confidence)}
    return best


def propose(*, descriptor_path: Path, source_root: Path, derived: Path, association_path: Path, exports_dir: Path,
            detector_spec: Path, model_root: Path, out: Path) -> str:
    document, descriptor_sha, entries = descriptors.load(descriptor_path) + (None,)
    entries = descriptors.reconcile(document, source_root)
    association, _, association_sha = read_artefact(association_path, associations.SCHEMA, associations.CODE)
    require(association["envelope"]["dataset"]["descriptorSha256"] == descriptor_sha, "proposals:descriptor")
    exports = artefacts.load_exports(sorted(Path(exports_dir).rglob("*.json")))
    by_run = {export.run_id: export for export in exports.values()}
    manifest = json.loads((Path(derived) / "derivation-manifest.json").read_bytes())
    frames_of = {row["sequenceId"]: row["sourceFrames"] for row in manifest["sequences"]}
    detector, identity = _detector(detector_spec, model_root)
    tracks = []
    for entry in sorted(association["sequences"], key=lambda e: e["sequenceId"]):
        sequence = entry["sequenceId"]
        gt_bytes = (Path(derived) / "sequences" / sequence / "ground-truth.json").read_bytes()
        require(sha256_hex(gt_bytes) == next(s["groundTruthSha256"] for s in manifest["sequences"]
                                             if s["sequenceId"] == sequence), f"proposals:gt_hash:{sequence}")
        gt = json.loads(gt_bytes)
        width, height = gt["frameSize"]["width"], gt["frameSize"]["height"]
        mavi = {pair["gtTrackId"]: pair["maviTrackId"] for pair in entry["pairs"]}
        export = by_run[entry["processingRunId"]]
        observations = {track["id"]: [o["sourceFrameNumber"] for o in track["observations"]] for track in export.tracks}
        images: dict[int, np.ndarray] = {}
        for track in gt["tracks"]:
            if track["nativeClass"] not in VEHICLE_CLASSES:
                continue
            boxes = {f["frameIndex"]: f["box"] for f in track["frames"] if not f["ignore"]}
            oracle = [i for i, box in boxes.items() if box["width"] * width >= MIN_VEHICLE_WIDTH]
            if not oracle:
                continue
            evidence = [i for i in observations.get(mavi.get(track["gtTrackId"]), []) if i in boxes]
            proposals = {}
            for index in sorted(set(oracle) | set(evidence)):
                if index not in images:
                    images[index] = measure.decode_image(
                        descriptors.read_verified(entries, source_root, frames_of[sequence][index]))
                proposal = _propose_frame(detector, images[index], _pixel_box(boxes[index], width, height))
                proposals[str(index)] = {"vehicleBox": list(_pixel_box(boxes[index], width, height)),
                                         "oracleCandidate": index in oracle, "evidenceFrame": index in evidence,
                                         "imagePath": frames_of[sequence][index], "plate": proposal}
            tracks.append({"sequenceId": sequence, "gtTrackId": track["gtTrackId"],
                           "nativeClass": track["nativeClass"], "maviTrackId": mavi.get(track["gtTrackId"]),
                           "frames": proposals})
        images.clear()
    document_out = {"schemaVersion": PROPOSALS, "descriptorSha256": descriptor_sha,
                    "associationSha256": association_sha, "detector": identity,
                    "rule": {"minVehicleWidthPx": MIN_VEHICLE_WIDTH, "pad": PAD,
                             "detectorConfidence": DETECTOR_CONFIDENCE}, "tracks": tracks}
    data = canonical_json(document_out)
    write_once(out, data)
    return sha256_hex(data)


# Sheets


def _plate_width(frame: dict[str, Any]) -> float:
    return frame["plate"]["box"][2] - frame["plate"]["box"][0] if frame["plate"] else 0.0


def candidates(proposals: dict[str, Any], limit: int = SELECTED_TRACKS) -> list[dict[str, Any]]:
    """The bounded labelling set, numbered in (sequence, track) order: the ``limit`` tracks with the widest proposed
    plate (at least ``CANDIDATE_PLATE_WIDTH``); each keeps its ``ORACLE_FRAMES`` widest-plate oracle frames and every
    evidence frame (``frames``), and names its widest-plate frame (``bestFrame``)."""
    found = []
    for track in proposals["tracks"]:
        widths = sorted(((_plate_width(f), int(i)) for i, f in track["frames"].items()
                         if f["plate"] and f["oracleCandidate"]), key=lambda w: (-w[0], w[1]))
        if widths and widths[0][0] >= CANDIDATE_PLATE_WIDTH:
            keep = {str(i) for _, i in widths[:ORACLE_FRAMES]} | {
                i for i, f in track["frames"].items() if f["evidenceFrame"]}
            frames = {i: f for i, f in track["frames"].items() if i in keep}
            found.append({**track, "frames": frames, "bestFrame": str(widths[0][1]), "_width": widths[0][0]})
    found.sort(key=lambda t: (-t["_width"], t["sequenceId"], t["gtTrackId"]))
    chosen = sorted(found[:limit], key=lambda t: (t["sequenceId"], t["gtTrackId"]))
    return [{**{k: v for k, v in track.items() if k != "_width"}, "candidate": f"T{n:04d}"}
            for n, track in enumerate(chosen, start=1)]


def sheets(*, proposals_path: Path, descriptor_path: Path, source_root: Path, out_dir: Path, per_sheet: int = 20) -> int:
    from PIL import Image, ImageDraw

    proposals = json.loads(Path(proposals_path).read_bytes())
    document, _ = descriptors.load(descriptor_path)
    entries = descriptors.reconcile(document, source_root)
    tracks = candidates(proposals)
    out_dir.mkdir(parents=True, exist_ok=False)
    cache: dict[str, np.ndarray] = {}

    def image(path: str) -> np.ndarray:
        if path not in cache:
            cache.clear()
            cache[path] = measure.decode_image(descriptors.read_verified(entries, source_root, path))
        return cache[path]

    def tile(pixels: np.ndarray, label: str, size: tuple[int, int]) -> Image.Image:
        picture = Image.fromarray(pixels).resize(size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (size[0], size[1] + 18), "white")
        canvas.paste(picture, (0, 18))
        ImageDraw.Draw(canvas).text((2, 2), label, fill="black")
        return canvas

    # Text sheets: the largest proposed plate of each candidate, enlarged, with no machine reading.
    text_tiles = []
    for track in tracks:
        frame = track["frames"][track["bestFrame"]]
        x1, y1, x2, y2 = frame["plate"]["box"]
        pad_x, pad_y = (x2 - x1) * 0.15, (y2 - y1) * 0.3
        pixels = image(frame["imagePath"])
        rect = measure.pixel_rect(x1 - pad_x, y1 - pad_y, x2 + pad_x, y2 + pad_y, pixels.shape[1], pixels.shape[0])
        text_tiles.append(tile(measure.region(pixels, rect), track["candidate"], (360, 120)))
    geometry_tiles = []
    for track in tracks:
        for index in sorted(track["frames"], key=int):
            frame = track["frames"][index]
            if not frame["plate"]:
                continue
            pixels = image(frame["imagePath"]).copy()
            vx1, vy1, vx2, vy2 = frame["vehicleBox"]
            rect = measure.pixel_rect(vx1, vy1, vx2, vy2, pixels.shape[1], pixels.shape[0])
            crop = Image.fromarray(measure.region(pixels, rect))
            draw = ImageDraw.Draw(crop)
            x1, y1, x2, y2 = frame["plate"]["box"]
            draw.rectangle([x1 - rect.left, y1 - rect.top, x2 - rect.left, y2 - rect.top], outline=(255, 0, 0), width=2)
            geometry_tiles.append(tile(np.asarray(crop), f"{track['candidate']}/{int(index)}", (240, 180)))
    count = 0
    for name, tiles, columns in (("text", text_tiles, 4), ("geometry", geometry_tiles, 6)):
        for start in range(0, len(tiles), per_sheet):
            chunk = tiles[start:start + per_sheet]
            w, h = chunk[0].size
            rows = (len(chunk) + columns - 1) // columns
            sheet = Image.new("RGB", (columns * w, rows * h), "white")
            for k, t in enumerate(chunk):
                sheet.paste(t, ((k % columns) * w, (k // columns) * h))
            sheet.save(out_dir / f"{name}-{start // per_sheet + 1:03d}.png")
            count += 1
    (out_dir / "candidates.json").write_text(json.dumps([{"candidate": t["candidate"], "sequenceId": t["sequenceId"],
                                                          "gtTrackId": t["gtTrackId"]} for t in tracks], indent=1))
    return count


# Labels


def labels(*, proposals_path: Path, decisions_path: Path, out: Path) -> str:
    """Verified labels: text only where transcribed legible; boxes only where geometry was accepted."""
    proposals_bytes = Path(proposals_path).read_bytes()
    proposals = json.loads(proposals_bytes)
    decisions = json.loads(Path(decisions_path).read_bytes())
    require(isinstance(decisions.get("verifier"), dict) and decisions["verifier"].get("method"), "labels:verifier")
    texts, rejected = decisions["texts"], set(decisions.get("rejectedGeometry", []))
    tracks = []
    for track in candidates(proposals):
        text = texts.get(track["candidate"])
        require(track["candidate"] in texts, f"labels:undecided:{track['candidate']}")
        frames = {index: frame["plate"]["box"] for index, frame in track["frames"].items()
                  if frame["plate"] and f"{track['candidate']}/{int(index)}" not in rejected}
        tracks.append({"candidate": track["candidate"], "sequenceId": track["sequenceId"],
                       "gtTrackId": track["gtTrackId"], "nativeClass": track["nativeClass"], "text": text,
                       "frames": {index: {"plateBox": box, "imagePath": track["frames"][index]["imagePath"],
                                          "vehicleBox": track["frames"][index]["vehicleBox"]}
                                  for index, box in sorted(frames.items(), key=lambda kv: int(kv[0]))}})
    document = {"schemaVersion": LABELS, "proposalsSha256": hashlib.sha256(proposals_bytes).hexdigest(),
                "descriptorSha256": proposals["descriptorSha256"], "verifier": decisions["verifier"],
                "tracks": tracks}
    data = canonical_json(document)
    write_once(out, data)
    return sha256_hex(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools.benchmarks.plates.annotate")
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("propose")
    for name in ("descriptor", "source-root", "derived", "association", "exports", "detector-spec", "model-root",
                 "out"):
        p.add_argument(f"--{name}", type=Path, required=True)
    s = commands.add_parser("sheets")
    for name in ("proposals", "descriptor", "source-root", "out-dir"):
        s.add_argument(f"--{name}", type=Path, required=True)
    lab = commands.add_parser("labels")
    for name in ("proposals", "decisions", "out"):
        lab.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "propose":
        print(propose(descriptor_path=args.descriptor, source_root=args.source_root, derived=args.derived,
                      association_path=args.association, exports_dir=args.exports, detector_spec=args.detector_spec,
                      model_root=args.model_root, out=args.out))
    elif args.command == "sheets":
        print(sheets(proposals_path=args.proposals, descriptor_path=args.descriptor, source_root=args.source_root,
                     out_dir=args.out_dir))
    else:
        print(labels(proposals_path=args.proposals, decisions_path=args.decisions, out=args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
