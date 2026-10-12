"""Pixel measurements over MAVI's **production** evidence path (Stage 4 plan §3.1 E-A steps 2–4).

The tight vehicle crop is ``mavi_vision.quality.scoring.crop_region`` and the encoding is
``mavi_vision.evidence.encoder.JpegLadderEncoder`` under ``PRODUCTION_ENCODER_POLICY`` at the ADR-013 role caps — the
same code VisionJob runs, imported, never re-implemented. ``crop_origin`` restates the crop's floor rule only to map
plate coordinates into the crop; a test pins it to ``crop_region``'s pixels, so the two cannot drift apart.

Text and image metrics: CER is the Levenshtein distance over the ground truth length; blur is the variance of the
4-neighbour Laplacian of the grey plate region (ITU-R BT.601 luma, float64), a deterministic sharpness proxy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from io import BytesIO

import numpy as np
from PIL import Image

from mavi_vision.common.analytical import NormalizedBoundingBox
from mavi_vision.evidence.encoder import EncodedImage, JpegLadderEncoder
from mavi_vision.evidence.policy import PRODUCTION_ENCODER_POLICY
from mavi_vision.evidence.roles import REPRESENTATIVE_CAP_BYTES, SUPPLEMENTAL_CAP_BYTES
from mavi_vision.quality.scoring import crop_region
from mavi_vision.video.reader import DecodedFrame

# The two ADR-013 §5 caps: Representative (64 KiB) and every supplemental role, NearView included (160 KiB).
ROLE_CAPS = {"representative": REPRESENTATIVE_CAP_BYTES, "supplemental": SUPPLEMENTAL_CAP_BYTES}
ENCODER = JpegLadderEncoder(PRODUCTION_ENCODER_POLICY)


def encoder_identity() -> dict[str, object]:
    policy = PRODUCTION_ENCODER_POLICY
    return {"encoderVersion": policy.encoder_version, "maxLongEdgePx": policy.max_long_edge_px,
            "representativeCapBytes": REPRESENTATIVE_CAP_BYTES, "supplementalCapBytes": SUPPLEMENTAL_CAP_BYTES,
            "floorLongEdgePx": policy.floor_long_edge_px, "floorQuality": policy.floor_quality,
            "pillowVersion": Image.__version__}


def decode_image(data: bytes) -> np.ndarray:
    """RGB uint8 pixels of an encoded image (PNG/JPEG), decoded once."""
    with Image.open(BytesIO(data)) as image:
        return np.asarray(image.convert("RGB"), dtype=np.uint8).copy()


def normalised_box(box: dict[str, float], width: int, height: int) -> NormalizedBoundingBox:
    """A pixel box as the normalised box the detector would have produced (clamped into the frame)."""
    x, y = max(0.0, box["x"] / width), max(0.0, box["y"] / height)
    w = min(box["width"] / width, 1.0 - x)
    h = min(box["height"] / height, 1.0 - y)
    return NormalizedBoundingBox(x, y, w, h)


def crop_origin(width: int, height: int, box: NormalizedBoundingBox) -> tuple[int, int, int, int]:
    """``(left, top, right, bottom)`` of ``crop_region``'s pixels (its floor/ceil rule)."""
    left = max(0, min(width, int(math.floor(box.x * width))))
    top = max(0, min(height, int(math.floor(box.y * height))))
    right = max(left, min(width, int(math.ceil((box.x + box.width) * width))))
    bottom = max(top, min(height, int(math.ceil((box.y + box.height) * height))))
    return left, top, right, bottom


def vehicle_crop(image: np.ndarray, box: NormalizedBoundingBox) -> np.ndarray:
    """The production tight crop of ``box`` (``crop_region`` on a decoded frame)."""
    return np.ascontiguousarray(crop_region(DecodedFrame(source_frame_number=0, offset_ms=0, image=image), box))


def encode(crop: np.ndarray, role: str) -> EncodedImage | None:
    """The production encoding at the role's cap; ``None`` when the ladder cannot fit the cap (not admitted)."""
    return ENCODER.encode(crop, ROLE_CAPS[role])


@dataclass(frozen=True, slots=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def empty(self) -> bool:
        return self.width <= 0 or self.height <= 0


def pixel_rect(left: float, top: float, right: float, bottom: float, width: int, height: int) -> Rect:
    """The covering integer rectangle (floor/ceil), clamped to the image."""
    return Rect(max(0, min(width, math.floor(left))), max(0, min(height, math.floor(top))),
                max(0, min(width, math.ceil(right))), max(0, min(height, math.ceil(bottom))))


def region(image: np.ndarray, rect: Rect) -> np.ndarray:
    return np.ascontiguousarray(image[rect.top:rect.bottom, rect.left:rect.right])


def map_into_crop(rect: tuple[float, float, float, float], origin: tuple[int, int, int, int],
                  encoded_size: tuple[int, int]) -> tuple[tuple[float, float, float, float], float]:
    """A source-pixel rectangle in encoded-crop pixels, and the share of its area that lies inside the crop."""
    left, top, right, bottom = rect
    o_left, o_top, o_right, o_bottom = origin
    crop_w, crop_h = o_right - o_left, o_bottom - o_top
    sx, sy = encoded_size[0] / crop_w, encoded_size[1] / crop_h
    inside_w = max(0.0, min(right, o_right) - max(left, o_left))
    inside_h = max(0.0, min(bottom, o_bottom) - max(top, o_top))
    area = (right - left) * (bottom - top)
    share = (inside_w * inside_h) / area if area > 0 else 0.0
    mapped = ((left - o_left) * sx, (top - o_top) * sy, (right - o_left) * sx, (bottom - o_top) * sy)
    return mapped, share


def laplacian_variance(rgb: np.ndarray) -> float | None:
    """Variance of the 4-neighbour Laplacian of the luma; ``None`` below 3×3 pixels."""
    if rgb.ndim != 3 or rgb.shape[0] < 3 or rgb.shape[1] < 3:
        return None
    luma = rgb[..., 0].astype(np.float64) * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114
    lap = (luma[:-2, 1:-1] + luma[2:, 1:-1] + luma[1:-1, :-2] + luma[1:-1, 2:] - 4.0 * luma[1:-1, 1:-1])
    return float(lap.var())


def levenshtein(a: str, b: str, wildcard: str | None = None) -> int:
    """Edit distance; a ``wildcard`` character in ``b`` substitutes for any character at no cost."""
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            substitution = 0 if ca == cb or cb == wildcard else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + substitution))
        previous = current
    return previous[-1]


def cer(prediction: str | None, truth: str, masked: bool = False) -> float:
    """Character error rate of a normalised prediction (``None`` — rejected or no reading — is all deletions). With
    ``masked``, a ``*`` in the truth is a known-unknown character that any read character matches."""
    return levenshtein(prediction or "", truth, "*" if masked else None) / len(truth)
