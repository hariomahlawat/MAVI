from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from mavi_vision.common.analytical import NormalizedBoundingBox
from mavi_vision.video.reader import DecodedFrame


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def crop_region(frame: DecodedFrame, bbox: NormalizedBoundingBox) -> np.ndarray:
    """The frame pixels under ``bbox`` (floor/ceil rule), as a view; may be empty."""
    return _crop(frame, bbox)


def _crop(frame: DecodedFrame, bbox: NormalizedBoundingBox) -> np.ndarray:
    height, width, _ = frame.image.shape
    left = max(0, min(width, int(np.floor(bbox.x * width))))
    top = max(0, min(height, int(np.floor(bbox.y * height))))
    right = max(left, min(width, int(np.ceil((bbox.x + bbox.width) * width))))
    bottom = max(top, min(height, int(np.ceil((bbox.y + bbox.height) * height))))
    return frame.image[top:bottom, left:right]


def _normalized_sharpness(frame: DecodedFrame, bbox: NormalizedBoundingBox) -> float:
    crop = _crop(frame, bbox)
    if crop.size == 0:
        return 0.0
    rgb = crop.astype(np.float64, copy=False)
    grayscale = 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]
    energies: list[float] = []
    if grayscale.shape[1] > 1:
        energies.append(float(np.mean(np.abs(np.diff(grayscale, axis=1)))))
    if grayscale.shape[0] > 1:
        energies.append(float(np.mean(np.abs(np.diff(grayscale, axis=0)))))
    if not energies:
        return 0.0
    return _clamp01((sum(energies) / len(energies)) / 64.0)


@dataclass(frozen=True, slots=True)
class QualityComponents:
    """The signals of quality formula v1 and its combined value."""

    sharpness: float
    area: float
    edge_margin: float
    quality: float


def quality_components(
    frame: DecodedFrame,
    bbox: NormalizedBoundingBox,
) -> QualityComponents:
    """Quality formula v1: 0.45·sharpness + 0.35·area/0.20 + 0.20·edgeMargin/0.10.

    ``sharpness`` is the mean absolute grey gradient of the crop / 64, and
    ``edge_margin`` is the box's smallest normalised distance to a frame edge
    (the truncation proxy). All three are clamped to [0, 1] inside the formula.
    """
    sharpness = _normalized_sharpness(frame, bbox)
    area = bbox.width * bbox.height
    area_score = _clamp01(area / 0.20)
    right = 1.0 - (bbox.x + bbox.width)
    bottom = 1.0 - (bbox.y + bbox.height)
    edge_margin = min(bbox.x, bbox.y, right, bottom)
    edge_margin_score = _clamp01(edge_margin / 0.10)
    quality = _clamp01(
        0.45 * sharpness + 0.35 * area_score + 0.20 * edge_margin_score
    )
    return QualityComponents(
        sharpness=sharpness,
        area=area,
        edge_margin=edge_margin,
        quality=quality,
    )


def representative_quality(
    frame: DecodedFrame,
    bbox: NormalizedBoundingBox,
) -> float:
    return quality_components(frame, bbox).quality
