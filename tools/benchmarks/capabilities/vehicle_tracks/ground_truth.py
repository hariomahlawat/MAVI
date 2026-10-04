"""Canonical vehicle-track ground truth: validation and the class-free association projection (plan §7 inputs).

The canonical document of one sequence (written by a dataset adapter; its hash is ``groundTruthSha256``)::

    {sequenceId, split, frameSize {width, height},
     instants [{frameIndex, videoOffsetMs {numerator, denominator}}],          # every labelled instant, ascending
     tracks [{gtTrackId, nativeClass, frames [{frameIndex, videoOffsetMs, box {x, y, width, height}, ignore}]}],
     ignoreRegions [{frameIndex, box}]}                                       # optional; verified ignore semantics

Boxes are normalised, top-left ``x, y`` plus ``width, height`` (the T1 export convention). ``project`` returns the
only view association receives: GT track ids, labelled-instant positions and times, boxes and ignore flags. The
native class is validated and then dropped; it never reaches association.

**Frame-level ignore (plan §7).** An ``ignore`` frame is removed from its track before any computation and its box
becomes ignore-region evidence for that instant. A track left with fewer than ``minOverlapFrames`` non-ignored
frames is an *ignored track*: in no population, never assigned, and all of its boxes become ignore regions.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from tools.benchmarks.core.identity import S32Error, from_rational, require

CODE = "ground_truth_invalid"
GT_TRACK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}")
SPLIT = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")  # the descriptor's split-name slug
_EPSILON = 1e-9  # pixel-to-normalised conversion may overshoot 1.0 by one ulp


@dataclass(frozen=True, slots=True)
class Box:
    x: float
    y: float
    width: float
    height: float

    @property
    def centre(self) -> tuple[float, float]:
        return self.x + self.width / 2.0, self.y + self.height / 2.0

    @property
    def diagonal(self) -> float:
        return math.hypot(self.width, self.height)

    def contains(self, cx: float, cy: float) -> bool:
        return self.x <= cx <= self.x + self.width and self.y <= cy <= self.y + self.height

    def iou(self, other: "Box") -> float:
        left, top = max(self.x, other.x), max(self.y, other.y)
        right = min(self.x + self.width, other.x + other.width)
        bottom = min(self.y + self.height, other.y + other.height)
        intersection = max(0.0, right - left) * max(0.0, bottom - top)
        union = self.width * self.height + other.width * other.height - intersection
        # Floating-point rounding can put identical boxes a few ulps above 1; IoU is in [0, 1] by definition.
        return min(1.0, max(0.0, intersection / union)) if union > 0 else 0.0

    def interpolate(self, other: "Box", weight: Fraction) -> "Box":
        """The box ``weight`` of the way from ``self`` to ``other`` (``weight`` exact in [0, 1])."""
        w = float(weight)
        return Box(self.x + (other.x - self.x) * w, self.y + (other.y - self.y) * w,
                   self.width + (other.width - self.width) * w, self.height + (other.height - self.height) * w)


@dataclass(frozen=True, slots=True)
class GtFrame:
    instant: int  # position in GtSequence.instants
    box: Box
    ignore: bool


@dataclass(frozen=True, slots=True)
class GtTrack:
    gt_track_id: str
    frames: tuple[GtFrame, ...]  # every labelled frame of the track, ignored ones included, ascending

    @property
    def evaluable(self) -> tuple[GtFrame, ...]:
        return tuple(frame for frame in self.frames if not frame.ignore)


@dataclass(frozen=True, slots=True)
class GtSequence:
    sequence_id: str
    instants: tuple[Fraction, ...]  # labelled instants (media ms), strictly increasing
    tracks: tuple[GtTrack, ...]  # sorted by gt_track_id
    ignore_regions: tuple[tuple[int, Box], ...]  # (instant, box) from verified ignore semantics


def box(document: Any, code: str, tolerance: float = _EPSILON) -> Box:
    """A normalised box; ``tolerance`` admits the overshoot of the source's number format (one double ulp for
    adapter conversions; single-precision rounding for T1 export boxes)."""
    require(isinstance(document, dict) and set(document) == {"x", "y", "width", "height"}, code)
    values = [document[key] for key in ("x", "y", "width", "height")]
    require(all(type(value) in (int, float) and math.isfinite(value) for value in values), code)
    x, y, width, height = (float(value) for value in values)
    require(x >= -tolerance and y >= -tolerance and width > 0 and height > 0, code)
    require(x + width <= 1 + tolerance and y + height <= 1 + tolerance, code)
    return Box(x, y, width, height)


def _instants(document: dict[str, Any]) -> tuple[dict[int, int], tuple[Fraction, ...]]:
    rows = document.get("instants")
    require(isinstance(rows, list) and rows, f"{CODE}:instants")
    positions: dict[int, int] = {}
    times: list[Fraction] = []
    last_index = -1
    for row in rows:
        require(isinstance(row, dict) and set(row) == {"frameIndex", "videoOffsetMs"}, f"{CODE}:instants")
        index = row["frameIndex"]
        require(type(index) is int and index >= 0, f"{CODE}:instants")
        time = from_rational(row["videoOffsetMs"], f"{CODE}:instant_time")
        require(index > last_index and (not times or time > times[-1]), f"{CODE}:instants_order")
        last_index = index
        positions[index] = len(times)
        times.append(time)
    return positions, tuple(times)


def validate(document: Any) -> dict[str, Any]:
    """The canonical GT document, checked strictly; refusals are ``ground_truth_invalid:<where>``."""
    project(document)
    return document


def project(document: Any) -> GtSequence:
    """The class-free association view of one canonical GT document."""
    try:
        return _project(document)
    except S32Error:
        raise
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
        raise S32Error(f"{CODE}:malformed") from exc


def _project(document: Any) -> GtSequence:
    require(isinstance(document, dict), CODE)
    allowed = {"sequenceId", "split", "frameSize", "instants", "tracks", "ignoreRegions"}
    require(set(document) <= allowed and set(document) >= allowed - {"ignoreRegions"}, f"{CODE}:fields")
    sequence_id = document["sequenceId"]
    require(isinstance(sequence_id, str) and GT_TRACK_ID.fullmatch(sequence_id), f"{CODE}:sequenceId")
    require(isinstance(document["split"], str) and SPLIT.fullmatch(document["split"]), f"{CODE}:split")
    size = document["frameSize"]
    require(isinstance(size, dict) and set(size) == {"width", "height"}
            and all(type(size[key]) is int and size[key] > 0 for key in size), f"{CODE}:frameSize")
    positions, times = _instants(document)
    tracks: list[GtTrack] = []
    rows = document["tracks"]
    require(isinstance(rows, list), f"{CODE}:tracks")
    previous_id: str | None = None
    for row in rows:
        require(isinstance(row, dict) and set(row) == {"gtTrackId", "nativeClass", "frames"}, f"{CODE}:track")
        track_id = row["gtTrackId"]
        require(isinstance(track_id, str) and GT_TRACK_ID.fullmatch(track_id), f"{CODE}:gtTrackId")
        require(previous_id is None or track_id > previous_id, f"{CODE}:track_order")
        previous_id = track_id
        require(isinstance(row["nativeClass"], str) and row["nativeClass"], f"{CODE}:nativeClass")
        frames: list[GtFrame] = []
        require(isinstance(row["frames"], list) and row["frames"], f"{CODE}:frames:{track_id}")
        for frame in row["frames"]:
            require(isinstance(frame, dict) and set(frame) == {"frameIndex", "videoOffsetMs", "box", "ignore"},
                    f"{CODE}:frame:{track_id}")
            position = positions.get(frame["frameIndex"]) if type(frame["frameIndex"]) is int else None
            require(position is not None, f"{CODE}:frame_not_an_instant:{track_id}")
            require(not frames or position > frames[-1].instant, f"{CODE}:frame_order:{track_id}")
            require(from_rational(frame["videoOffsetMs"], f"{CODE}:frame_time:{track_id}") == times[position],
                    f"{CODE}:frame_time:{track_id}")
            require(type(frame["ignore"]) is bool, f"{CODE}:ignore:{track_id}")
            frames.append(GtFrame(position, box(frame["box"], f"{CODE}:box:{track_id}"), frame["ignore"]))
        tracks.append(GtTrack(track_id, tuple(frames)))
    regions: list[tuple[int, Box]] = []
    for region in document.get("ignoreRegions", []):
        require(isinstance(region, dict) and set(region) == {"frameIndex", "box"}, f"{CODE}:ignoreRegions")
        position = positions.get(region["frameIndex"]) if type(region["frameIndex"]) is int else None
        require(position is not None, f"{CODE}:ignoreRegions")
        regions.append((position, box(region["box"], f"{CODE}:ignoreRegions")))
    return GtSequence(sequence_id, times, tuple(tracks), tuple(regions))
