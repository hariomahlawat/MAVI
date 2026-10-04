"""Reading sealed MAVI trajectory artefacts (format v1; ``src/vision/mavi_vision/video/trajectory.py``).

``{"v": 1, "points": [[offset_ms, center_x, center_y], …]}`` in msgpack: integer media offsets in ms, strictly
increasing, and normalised centres in [0, 1]. A trajectory carries no box size. The bytes are located by hash under
the evidence root, read once, re-hashed, and only then decoded; every malformed payload is a refusal
(``trajectory_invalid:<reason>``), never a raw msgpack, type or index error.
"""

from __future__ import annotations

import math
from pathlib import Path

import msgpack

from tools.benchmarks.core import mavi
from tools.benchmarks.core._stage3 import artefacts
from tools.benchmarks.core.identity import S32Error, require, sha256_hex

Point = tuple[int, float, float]
CODE = "trajectory_invalid"


def decode(data: bytes) -> tuple[Point, ...]:
    try:
        document = msgpack.unpackb(data, raw=False, strict_map_key=True, use_list=True)
    except (msgpack.ExtraData, msgpack.FormatError, msgpack.StackError, ValueError, TypeError, OverflowError) as exc:
        raise S32Error(f"{CODE}:malformed") from exc
    require(isinstance(document, dict) and set(document) == {"v", "points"}, f"{CODE}:fields")
    require(type(document["v"]) is int and document["v"] == 1, "trajectory_format_unsupported")
    rows = document["points"]
    require(isinstance(rows, list) and rows, f"{CODE}:points")
    points: list[Point] = []
    for row in rows:
        require(isinstance(row, list) and len(row) == 3, f"{CODE}:point")
        offset, cx, cy = row
        require(type(offset) is int and offset >= 0, f"{CODE}:offset")
        for value in (cx, cy):
            require(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1, f"{CODE}:centre")
        require(not points or offset > points[-1][0], f"{CODE}:offsets_not_increasing")
        points.append((offset, float(cx), float(cy)))
    return tuple(points)


def read(evidence_root: Path, sha256: str) -> tuple[Point, ...]:
    """The decoded trajectory whose sealed bytes hash to ``sha256`` (verified on the bytes decoded)."""
    path = mavi.locate_trajectory(evidence_root, sha256)
    data = artefacts.read_bytes(path, "trajectory_missing")
    require(sha256_hex(data) == sha256, f"trajectory_hash_mismatch:{sha256}")
    return decode(data)
