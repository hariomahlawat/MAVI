"""Synthetic Scalabel-format BDD100K MOT source trees (no dataset bytes; every value invented here).

Two val sequences in the canonical layout. Frame ``frameIndex`` k is stored as ``<video>-<k + 1>.jpg``, as in the
official layout, so a test can tell a path read from ``name`` from one guessed from a number. Images are either a
header-only JPEG (enough for the adapter's SOF reader) or, for ``prepare``, real JPEGs encoded by the FFmpeg pack.
"""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

WIDTH, HEIGHT = 64, 36
SEQ_A, SEQ_B = "f0000001-a0000001", "f0000002-b0000002"


def _label(track_id: str, category: str, box: tuple[float, float, float, float], **attributes: bool) -> dict:
    x1, y1, x2, y2 = box
    return {"id": track_id, "category": category,
            "attributes": {"occluded": False, "truncated": False, "crowd": False, **attributes},
            "box2d": {"x1": x1, "y1": y1, "x2": x2, "y2": y2}}


def _sequence(video: str, frames: list[list[dict]]) -> list[dict[str, Any]]:
    return [{"name": f"{video}-{index + 1:07d}.jpg", "videoName": video, "frameIndex": index,
             "attributes": {"weather": "clear"}, "labels": labels} for index, labels in enumerate(frames)]


def labels() -> dict[str, list[dict[str, Any]]]:
    """Per sequence, the Scalabel frame list. Covers all eight box-tracking classes, a crowd object, occluded and
    truncated attributes, a distractor class, an official raw-name alias, a frame without labels and an edge box
    whose inclusive extent reaches past the image."""
    a = [
        [_label("1", "car", (2, 3, 13, 10)), _label("2", "truck", (20, 4, 35, 15), occluded=True),
         _label("3", "pedestrian", (50, 10, 53, 20), crowd=True)],
        [_label("1", "car", (4, 3, 15, 10)), _label("2", "truck", (21, 4, 36, 15)),
         _label("3", "pedestrian", (50, 11, 53, 21), crowd=True), _label("4", "bus", (30, 18, 60, 33))],
        [_label("1", "car", (6.5, 3.25, 17.5, 10.25), truncated=True), _label("4", "bus", (31, 18, 63, 33)),
         _label("5", "rider", (0, 20, 3, 30)), _label("6", "motorcycle", (0, 25, 4, 34))],
        [_label("1", "car", (8, 3, 19, 10)), _label("4", "bus", (33, 18, 64, 35))],
    ]
    b = [
        [_label("1", "bicycle", (5, 5, 9, 12)), _label("7", "train", (10, 0, 60, 20))],
        [],
        [_label("7", "train", (12, 0, 62, 20)), _label("8", "other vehicle", (40, 25, 50, 32)),
         _label("9", "van", (20, 22, 30, 30)), _label("10", "motor", (2, 26, 6, 34))],
    ]
    return {SEQ_A: _sequence(SEQ_A, a), SEQ_B: _sequence(SEQ_B, b)}


def jpeg_header(width: int = WIDTH, height: int = HEIGHT) -> bytes:
    """SOI, a JFIF APP0 segment, a baseline SOF0 segment and EOI: enough for the adapter's size reader."""
    app0 = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0\x00\x11\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big") + (
        b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01")
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


def write_source(root: Path, documents: dict[str, list[dict]] | None = None, split: str = "val",
                 image: bytes | None = None) -> Path:
    root = Path(root)
    documents = labels() if documents is None else documents
    for video, frames in documents.items():
        target = root / "labels" / "box_track_20" / split / f"{video}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(frames, indent=1), encoding="utf-8")
        for frame in frames:
            path = root / "images" / "track" / split / video / frame["name"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(jpeg_header() if image is None else image)
    return root


def encode_real_jpegs(root: Path, ffmpeg: Path) -> None:
    """Replaces every header-only frame with a real JPEG encoded by the pack's FFmpeg (distinct grey levels)."""
    for number, path in enumerate(sorted((root / "images").rglob("*.jpg"))):
        level = (37 * number) % 200 + 20
        ppm = path.with_suffix(".ppm")
        ppm.write_bytes(f"P6\n{WIDTH} {HEIGHT}\n255\n".encode() + bytes([level, 255 - level, level // 2])
                        * (WIDTH * HEIGHT))
        subprocess.run([str(ffmpeg), "-nostdin", "-loglevel", "error", "-y", "-i", str(ppm), "-q:v", "3",
                        str(path)], check=True, capture_output=True)
        ppm.unlink()


def mutated(change) -> dict[str, list[dict]]:
    documents = copy.deepcopy(labels())
    change(documents)
    return documents
