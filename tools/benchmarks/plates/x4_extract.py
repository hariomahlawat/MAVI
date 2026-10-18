"""Stage 4 X4-0 extraction: sequential decode, decode gate and the encoded/native crops of every Track-frame.

Development experiment only (frozen record ``x4-0-rules-v1.json``, section ``frames``). Selection-free: every
Vehicle Track-frame of the B1 Arm A per-candidate logs on the 70 pilot sequences is cut with the production
``crop_region``; Pool frames (non-A0) are encoded by the production ``JpegLadderEncoder`` at the supplemental role
cap, and every Track-frame is also carried natively (lossless PNG). Frames are decoded by the production
``iter_frames`` sequentially from frame 0 (no seek) and every decoded frame's RGB SHA-256 is recorded.

The decode gate re-cuts and re-encodes every A0 Observation from this decode at its own role cap and requires
the sealed crop SHA-256: any mismatch stops the run. Crops are stored content-addressed outside Git.

    python tools/benchmarks/plates/x4_extract.py run --inventory INV --out DIR
    python tools/benchmarks/plates/x4_extract.py verify --inventory INV DIR
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import x4_common as c  # noqa: E402
from x4_common import B1, H3, X4Error, require  # noqa: E402

PNG_LEVEL = 1


def _native_png(crop) -> bytes:
    import numpy as np
    from PIL import Image

    buffer = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(crop)).save(buffer, format="PNG", compress_level=PNG_LEVEL)
    return buffer.getvalue()


def _box(row: dict):
    from mavi_vision.common.analytical import NormalizedBoundingBox

    return NormalizedBoundingBox(row["box_x"], row["box_y"], row["box_w"], row["box_h"])


def _store(crops_dir: Path, data: bytes, ext: str) -> str:
    digest = c.sha_bytes(data)
    path = crops_dir / f"{digest}.{ext}"
    if path.exists():
        require(path.read_bytes() == data, "x4_crop_store_collision")
    else:
        path.write_bytes(data)
    return digest


def extract_sequence(sequence: str, inv: dict[str, Any], out: Path, encoder) -> dict[str, Any]:
    from mavi_vision.evidence.roles import EvidenceRole, role_cap_bytes
    from mavi_vision.quality.scoring import crop_region
    from mavi_vision.video.reader import iter_frames

    entry = inv["sequences"][sequence]
    a_index = c.load(B1 / "A" / "index.json")
    raw = (B1 / "A" / "results" / f"{sequence}.json").read_bytes()
    require(c.sha_bytes(raw) == entry["b1ResultSha256"] == a_index["results"][sequence], f"x4_b1_result:{sequence}")
    result = json.loads(raw)
    rows = c.read_log(B1 / "A" / "candidates" / f"{sequence}.jsonl.gz", entry["candidateLog"])
    require(all(r["object_class"] == "vehicle" for r in rows), f"x4_candidate_class:{sequence}")
    a0 = {}
    for track in result["tracks"]:
        if track["objectClass"] == "vehicle":
            for o in track["observations"]:
                a0[(str(track["trackId"]), o["sourceFrameNumber"])] = o
    by_frame: dict[int, list[dict]] = defaultdict(list)
    keys = set()
    for r in rows:
        key = (str(r["track_id"]), int(r["frame"]))
        require(key not in keys, f"x4_candidate_duplicate:{sequence}")
        keys.add(key)
        by_frame[int(r["frame"])].append(r)
    require(set(a0) <= keys, f"x4_a0_observation_without_candidate:{sequence}")
    video = H3 / "derived" / "sequences" / sequence / "video.mp4"
    data = video.read_bytes()
    require(c.sha_bytes(data) == entry["videoSha256"], f"x4_video_changed:{sequence}")
    crops_dir = out / "crops" / sequence
    crops_dir.mkdir(parents=True, exist_ok=False)
    supplemental_cap = role_cap_bytes(EvidenceRole.NEAR_VIEW)
    frames_log, crop_log = [], []
    gate = {"a0Observations": len(a0), "boxEqual": 0, "offsetEqual": 0, "sealedShaReproduced": 0, "failures": []}
    cpu, wall = time.process_time(), time.perf_counter()
    last_needed = max(by_frame) if by_frame else -1
    for frame in iter_frames(io.BytesIO(data)):
        frames_log.append({"frame": frame.source_frame_number, "offsetMs": frame.offset_ms,
                           "rgbSha256": c.sha_bytes(frame.image.tobytes()),
                           "shape": list(frame.image.shape)})
        for r in sorted(by_frame.get(frame.source_frame_number, ()), key=lambda r: str(r["track_id"])):
            tid = str(r["track_id"])
            require(r["offset_ms"] == frame.offset_ms, f"x4_offset_mismatch:{sequence}:{tid}:{r['frame']}")
            box = _box(r)
            crop = crop_region(frame, box)
            row = {"trackId": tid, "frame": frame.source_frame_number, "offsetMs": frame.offset_ms,
                   "nativeHeightPx": int(crop.shape[0]), "nativeWidthPx": int(crop.shape[1]),
                   "a0Role": None, "jpeg": None, "native": None, "excluded": None}
            require(row["nativeHeightPx"] == r["native_height_px"], f"x4_native_height:{sequence}:{tid}")
            observation = a0.get((tid, frame.source_frame_number))
            if observation is not None:
                row["a0Role"] = observation["role"]
                ob = observation["boundingBox"]
                box_equal = (ob["x"], ob["y"], ob["width"], ob["height"]) == (box.x, box.y, box.width, box.height)
                offset_equal = observation["offsetMs"] == frame.offset_ms
                image = encoder.encode(crop, role_cap_bytes(EvidenceRole(observation["role"])))
                reproduced = image is not None and c.sha_bytes(image.payload) == observation["crop"]["sha256"]
                gate["boxEqual"] += box_equal
                gate["offsetEqual"] += offset_equal
                gate["sealedShaReproduced"] += reproduced
                if not (box_equal and offset_equal and reproduced):
                    gate["failures"].append([tid, frame.source_frame_number, observation["role"]])
            if crop.size == 0:
                row["excluded"] = "empty_crop"
                crop_log.append(row)
                continue
            native = _native_png(crop)
            row["native"] = {"sha256": _store(crops_dir, native, "png"), "sizeBytes": len(native)}
            if observation is None:
                image = encoder.encode(crop, supplemental_cap)
                if image is None:
                    row["excluded"] = "ladder_refused"
                else:
                    row["jpeg"] = {"sha256": _store(crops_dir, image.payload, "jpg"), "sizeBytes": image.size_bytes,
                                   "width": image.width, "height": image.height, "quality": image.quality,
                                   "ladderStep": image.ladder_step}
            crop_log.append(row)
    require(len(crop_log) == len(rows), f"x4_rows_not_all_extracted:{sequence}")
    require(frames_log and frames_log[-1]["frame"] >= last_needed, f"x4_video_shorter_than_log:{sequence}")
    require([f["frame"] for f in frames_log] == list(range(len(frames_log))), f"x4_frame_numbering:{sequence}")
    timing = {"cpuSeconds": round(time.process_time() - cpu, 3), "wallSeconds": round(time.perf_counter() - wall, 3)}
    crop_log.sort(key=lambda r: (r["trackId"], r["frame"]))
    return {"frames": c.write_log(out / "frames" / f"{sequence}.jsonl.gz", frames_log),
            "crops": c.write_log(out / "manifest" / f"{sequence}.jsonl.gz", crop_log),
            "store": c.directory_digest(crops_dir), "gate": gate, "timing": timing,
            "decodedFrames": len(frames_log), "trackFrames": len(crop_log)}


def run(inventory_path: Path, out: Path) -> dict[str, Any]:
    from mavi_vision.evidence.encoder import JpegLadderEncoder
    from mavi_vision.evidence.policy import PRODUCTION_ENCODER_POLICY
    from mavi_vision.runtime.profile import load_pipeline_profile

    inv, inv_sha = c.load_inventory(inventory_path)
    git = c.require_clean_code(inv)
    require(c.sha_file(c.PROFILE) == inv["profileSha256"], "x4_profile_changed")
    policy = load_pipeline_profile(c.PROFILE).evidence.encoder
    require(policy == PRODUCTION_ENCODER_POLICY, "x4_profile_encoder_not_production")
    encoder = JpegLadderEncoder(policy)
    out.mkdir(parents=True, exist_ok=False)
    index: dict[str, Any] = {"kind": "x4-extract", "inventorySha256": inv_sha, "rulesSha256": inv["rulesSha256"],
                             "code": {"git": git, "files": inv["code"]["files"]}, "runtime": c.runtime_identity(),
                             "encoderVersion": encoder.version, "pngCompressLevel": PNG_LEVEL, "sequences": {}}
    timings = {}
    for n, s in enumerate(sorted(inv["sequences"]), start=1):
        entry = extract_sequence(s, inv, out, encoder)
        timings[s] = entry.pop("timing")
        index["sequences"][s] = entry
        g = entry["gate"]
        print(f"extract {n} {s} frames={entry['decodedFrames']} trackFrames={entry['trackFrames']} "
              f"gate={g['sealedShaReproduced']}/{g['a0Observations']}", flush=True)
        require(not g["failures"], f"x4_decode_gate_failed:{s}:{g['failures'][:3]}")
    index["gate"] = {k: sum(e["gate"][k] for e in index["sequences"].values())
                     for k in ("a0Observations", "boxEqual", "offsetEqual", "sealedShaReproduced")}
    index["gate"]["passed"] = (index["gate"]["a0Observations"] == index["gate"]["sealedShaReproduced"]
                               == index["gate"]["boxEqual"] == index["gate"]["offsetEqual"])
    c.dump(out / "index.json", index)
    c.dump(out / "timings.json", timings)
    return index


def verify(out: Path, inventory_path: Path | None = None) -> dict[str, Any]:
    index = c.load(out / "index.json")
    require(index.get("kind") == "x4-extract" and index["gate"]["passed"], "x4_extract_index_invalid")
    seqs = sorted(index["sequences"])
    if inventory_path is not None:
        inv, inv_sha = c.load_inventory(inventory_path)
        require(index["inventorySha256"] == inv_sha and seqs == sorted(inv["sequences"]), "x4_extract_inventory")
    for directory, suffix in (("frames", ".jsonl.gz"), ("manifest", ".jsonl.gz")):
        require(sorted(p.name[: -len(suffix)] for p in (out / directory).iterdir()) == seqs,
                f"x4_extract_files_extra_or_missing:{directory}")
    require(sorted(p.name for p in (out / "crops").iterdir()) == seqs, "x4_extract_files_extra_or_missing:crops")
    totals = {"frames": 0, "trackFrames": 0, "crops": 0}
    for s in seqs:
        e = index["sequences"][s]
        totals["frames"] += len(c.read_log(out / "frames" / f"{s}.jsonl.gz", e["frames"]))
        rows = c.read_log(out / "manifest" / f"{s}.jsonl.gz", e["crops"])
        totals["trackFrames"] += len(rows)
        require(c.directory_digest(out / "crops" / s) == e["store"], f"x4_extract_store_mismatch:{s}")
        referenced = {f"{r[k]['sha256']}.{ext}" for r in rows for k, ext in (("jpeg", "jpg"), ("native", "png")) if r[k]}
        require(referenced == {p.name for p in (out / "crops" / s).iterdir()}, f"x4_extract_store_differs:{s}")
        totals["crops"] += len(referenced)
    return {"verified": True, "sequences": len(seqs), **totals}


def canonical_view(out: Path) -> dict[str, Any]:
    index = c.load(out / "index.json")
    return {"inventory": index["inventorySha256"],
            "sequences": {s: (e["frames"]["canonicalSha256"], e["crops"]["canonicalSha256"], e["store"])
                          for s, e in index["sequences"].items()}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--inventory", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True)
    v = sub.add_parser("verify")
    v.add_argument("--inventory", type=Path)
    v.add_argument("out", type=Path)
    args = parser.parse_args(argv)
    if args.command == "run":
        index = run(args.inventory, args.out)
        print(json.dumps(index["gate"]))
        print(f"{args.out / 'index.json'} sha256={c.sha_file(args.out / 'index.json')}")
    else:
        print(json.dumps(verify(args.out, args.inventory)))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except X4Error as error:
        print(f"FAIL-CLOSED: {error}", file=sys.stderr)
        raise SystemExit(2)
