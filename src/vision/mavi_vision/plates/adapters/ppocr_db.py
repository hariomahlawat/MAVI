"""``ppocr-db-onnx-v1``: a PP-OCR DB text-line detector used as a plate-region proposer (Issue #225 pilot).

Ported from the read-only PR-2 benchmark adapter (``stage4/pr2-model-selection-prep`` @ 8790a412,
``tools/benchmarks/plates/candidates/{adapters,geometry,pr3}.py``) without behavioural change:

* pre-processing: PaddleOCR ``DetResizeForTest`` (long side scaled down to 960, never up; each side rounded to a
  multiple of 32), BGR, ``/255`` and ImageNet mean/std, NCHW float32;
* post-processing: the declared **axis-aligned** DB variant (4-connected components of the map thresholded at
  ``thresh``, mean-probability box score, ``box_thresh``, unclip distance ``area * unclip_ratio / perimeter``), with
  ``thresh``/``box_thresh``/``unclip_ratio``/``max_candidates`` read from the pack's own ``inference.yml``;
* the frozen ``vertical-stack-v1`` row merge (owner decision D10a): a text line merged with the line directly
  below it into one two-row plate proposal;
* proposals ordered by score and bounded by the profile's ``maxDetectionsPerCrop`` **as the model's configured
  top-k** (the YOLO ``max_det`` analogue), so the PR-3 bound is respected by configuration, never by truncation in
  the role code;
* PR-3 box mapping: ``floor`` the top-left, ``ceil`` the bottom-right, clip to the crop, drop a box under one pixel;
  a non-finite score or one outside [0, 1] is a detector fault.

A text-line detector is not a plate detector: it proposes any text on the vehicle. That is a property of the
pilot composition (Decision 1 alternative), reported as such, not corrected here.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Mapping

import numpy as np
from PIL import Image

from mavi_vision.plates.adapters.onnx import SessionFactory, cpu_session, read_yaml, resize_linear, rgb_array
from mavi_vision.plates.inference import PlateBox, VerifiedCrop

ADAPTER_ID = "ppocr-db-onnx-v1"
SLOTS = frozenset({"onnx-model", "inference-config"})

LIMIT_SIDE_LEN = 960
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
MIN_SIZE = 3.0
ROW_MERGE_MIN_HORIZONTAL_OVERLAP = 0.5  # of the narrower box's width
ROW_MERGE_MAX_VERTICAL_GAP = 0.5        # of the shorter box's height
ROW_MERGE_MAX_HEIGHT_RATIO = 2.0


def db_resize_shape(height: int, width: int, limit_side_len: int = LIMIT_SIDE_LEN) -> tuple[int, int]:
    if height <= 0 or width <= 0:
        raise ValueError("db_shape")
    ratio = min(1.0, limit_side_len / max(height, width))
    new_h = max(int(round(height * ratio / 32) * 32), 32)
    new_w = max(int(round(width * ratio / 32) * 32), 32)
    return new_h, new_w


def _components(binary: np.ndarray) -> list[tuple[slice, slice]]:
    from scipy import ndimage  # noqa: PLC0415 - plates-onnx-v1 runtime only

    labels, _ = ndimage.label(binary)
    return [(region[0], region[1]) for region in ndimage.find_objects(labels) if region is not None]


def db_boxes(probability: np.ndarray, thresh: float, box_thresh: float, unclip_ratio: float,
             scale_y: float, scale_x: float, max_candidates: int) -> np.ndarray:
    """Axis-aligned DB post-processing of one ``H x W`` map; rows ``(x1, y1, x2, y2, score)`` in crop pixels."""
    probability = np.asarray(probability, dtype=np.float64)
    if probability.ndim != 2:
        raise ValueError("db_probability_shape")
    height, width = probability.shape
    boxes = []
    for rows, cols in _components(probability > thresh)[:max_candidates]:
        y1, y2, x1, x2 = rows.start, rows.stop, cols.start, cols.stop
        if min(y2 - y1, x2 - x1) < MIN_SIZE:
            continue
        score = float(probability[y1:y2, x1:x2].mean())
        if score < box_thresh:
            continue
        w, h = x2 - x1, y2 - y1
        distance = (w * h) * unclip_ratio / (2 * (w + h))
        ux1, uy1 = max(x1 - distance, 0.0), max(y1 - distance, 0.0)
        ux2, uy2 = min(x2 + distance, float(width)), min(y2 + distance, float(height))
        if min(ux2 - ux1, uy2 - uy1) < MIN_SIZE + 2:
            continue
        boxes.append((ux1 * scale_x, uy1 * scale_y, ux2 * scale_x, uy2 * scale_y, score))
    boxes.sort(key=lambda b: (round(b[1], 6), round(b[0], 6)))
    return np.asarray(boxes, dtype=np.float64).reshape(-1, 5)


def _stackable(upper: np.ndarray, lower: np.ndarray) -> bool:
    width = min(upper[2] - upper[0], lower[2] - lower[0])
    height = min(upper[3] - upper[1], lower[3] - lower[1])
    if width <= 0 or height <= 0:
        return False
    overlap = min(upper[2], lower[2]) - max(upper[0], lower[0])
    gap = lower[1] - upper[3]
    ratio = max(upper[3] - upper[1], lower[3] - lower[1]) / height
    return (overlap >= ROW_MERGE_MIN_HORIZONTAL_OVERLAP * width and -0.5 * height <= gap
            <= ROW_MERGE_MAX_VERTICAL_GAP * height and ratio <= ROW_MERGE_MAX_HEIGHT_RATIO)


def merge_rows(boxes: np.ndarray) -> np.ndarray:
    """``vertical-stack-v1``: pair each line with the first stackable line below it; sorted by score, then position."""
    boxes = np.asarray(boxes, dtype=np.float64).reshape(-1, 5)
    order = sorted(range(len(boxes)), key=lambda i: (boxes[i, 1], boxes[i, 0], i))
    used: set[int] = set()
    merged = []
    for position, i in enumerate(order):
        if i in used:
            continue
        partner = next((j for j in order[position + 1:] if j not in used and _stackable(boxes[i], boxes[j])), None)
        if partner is None:
            merged.append(boxes[i])
            used.add(i)
            continue
        a, b = boxes[i], boxes[partner]
        merged.append(np.array([min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]), (a[4] + b[4]) / 2]))
        used.update((i, partner))
    out = np.asarray(merged, dtype=np.float64).reshape(-1, 5)
    keys = sorted(range(len(out)), key=lambda k: (-out[k, 4], out[k, 1], out[k, 0]))
    return out[keys]


def to_plate_boxes(rows: np.ndarray, width: int, height: int) -> list[PlateBox]:
    """The PR-3 conformance mapping (fixed before any pilot result)."""
    boxes = []
    for x1, y1, x2, y2, score in np.asarray(rows, dtype=np.float64).reshape(-1, 5):
        if not (math.isfinite(score) and 0 <= score <= 1):
            raise ValueError("plate_detector_score_invalid")
        left, top = max(0, math.floor(x1)), max(0, math.floor(y1))
        right, bottom = min(width, math.ceil(x2)), min(height, math.ceil(y2))
        if right - left < 1 or bottom - top < 1:
            continue
        boxes.append(PlateBox(int(left), int(top), int(right - left), int(bottom - top), float(score)))
    return boxes


class PpOcrDbPlateDetector:
    def __init__(self, artifacts: Mapping[str, Path], *, max_detections: int,
                 session_factory: SessionFactory = cpu_session) -> None:
        if set(artifacts) != SLOTS:
            raise ValueError("plate_adapter_artifacts_invalid")
        if max_detections < 1:
            raise ValueError("plate_adapter_bound_invalid")
        post = read_yaml(artifacts["inference-config"])["PostProcess"]
        if post.get("name") != "DBPostProcess":
            raise ValueError("plate_adapter_config_invalid")
        self._thresh = float(post["thresh"])
        self._box_thresh = float(post["box_thresh"])
        self._unclip_ratio = float(post["unclip_ratio"])
        self._max_candidates = int(post["max_candidates"])
        self._max_detections = int(max_detections)
        self._session = session_factory(artifacts["onnx-model"])
        self._input = self._session.get_inputs()[0].name

    def detect(self, crop: Image.Image, verified: VerifiedCrop) -> list[PlateBox]:
        rgb = rgb_array(crop)
        height, width = rgb.shape[:2]
        new_h, new_w = db_resize_shape(height, width)
        bgr = resize_linear(np.ascontiguousarray(rgb[:, :, ::-1]), new_w, new_h).astype(np.float32) / 255.0
        tensor = np.ascontiguousarray(((bgr - MEAN) / STD).transpose(2, 0, 1)[None], dtype=np.float32)
        probability = self._session.run(None, {self._input: tensor})[0][0, 0]
        rows = db_boxes(probability, self._thresh, self._box_thresh, self._unclip_ratio,
                        height / probability.shape[0], width / probability.shape[1], self._max_candidates)
        rows = merge_rows(rows)[: self._max_detections]
        return to_plate_boxes(rows, width, height)


__all__ = ["ADAPTER_ID", "SLOTS", "PpOcrDbPlateDetector", "db_boxes", "db_resize_shape", "merge_rows", "to_plate_boxes"]
