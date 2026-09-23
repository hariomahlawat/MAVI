"""Deterministic bounded JPEG encoding of evidence crops (ADR-013 §5, plan §6.1)."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Protocol

import numpy as np
from PIL import Image

from mavi_vision.evidence.errors import EvidenceError
from mavi_vision.evidence.policy import EncoderPolicy


@dataclass(frozen=True, slots=True)
class LadderStep:
    """One encoding attempt: long edge in pixels and JPEG quality."""

    long_edge: int
    quality: int


@dataclass(frozen=True, slots=True)
class EncodedImage:
    """An admitted JPEG and how it was produced; the only pixels a holder keeps."""

    payload: bytes
    width: int
    height: int
    quality: int
    ladder_step: int

    @property
    def size_bytes(self) -> int:
        return len(self.payload)


class EvidenceEncoder(Protocol):
    version: str

    def encode(self, crop: np.ndarray, cap_bytes: int) -> EncodedImage | None: ...


def encoding_ladder(width: int, height: int, policy: EncoderPolicy) -> tuple[LadderStep, ...]:
    """The exact sequence of attempts for a crop of ``width`` × ``height``.

    q85 then q75 at the starting size (the crop's own long edge, capped at 1024,
    never upscaled); then q75 while the long edge shrinks by ×0.8 (floored, never
    below 128); then q65, q55, q50 at that final size. Integer arithmetic only.
    """
    if width < 1 or height < 1:
        raise EvidenceError("evidence_crop_invalid")
    long_edge = min(max(width, height), policy.max_long_edge_px)
    first, second = policy.ladder_qualities
    steps = [LadderStep(long_edge, first), LadderStep(long_edge, second)]
    scale = policy.ladder_scale
    while long_edge > policy.floor_long_edge_px:
        long_edge = max(
            policy.floor_long_edge_px,
            (long_edge * scale.numerator) // scale.denominator,
        )
        steps.append(LadderStep(long_edge, second))
    steps.extend(LadderStep(long_edge, quality) for quality in policy.floor_qualities)
    return tuple(steps)


def scaled_size(width: int, height: int, long_edge: int) -> tuple[int, int]:
    """Dimensions with the long side at ``long_edge``; the other side rounded half up."""
    source_long = max(width, height)
    if long_edge >= source_long:
        return width, height

    def scale(edge: int) -> int:
        return max(1, (2 * edge * long_edge + source_long) // (2 * source_long))

    if width >= height:
        return long_edge, scale(height)
    return scale(width), long_edge


class JpegLadderEncoder:
    """Pillow JPEG with fixed options, walking the fixed ladder until the cap fits.

    Output bytes are reproducible within one qualified runtime variant (locked
    Pillow build). Across variants only dimensions, the cap and decodability are
    claimed (plan §8).
    """

    def __init__(self, policy: EncoderPolicy) -> None:
        self._policy = policy
        self.version = policy.encoder_version

    def encode(self, crop: np.ndarray, cap_bytes: int) -> EncodedImage | None:
        if (
            not isinstance(crop, np.ndarray)
            or crop.dtype != np.uint8
            or crop.ndim != 3
            or crop.shape[2] != 3
        ):
            raise EvidenceError("evidence_crop_invalid")
        height, width = int(crop.shape[0]), int(crop.shape[1])
        if width == 0 or height == 0:
            return None
        if cap_bytes < 1:
            raise EvidenceError("evidence_cap_invalid")

        source = Image.fromarray(np.ascontiguousarray(crop))
        resized: dict[tuple[int, int], Image.Image] = {}
        for index, step in enumerate(encoding_ladder(width, height, self._policy)):
            size = scaled_size(width, height, step.long_edge)
            image = resized.get(size)
            if image is None:
                image = (
                    source
                    if size == (width, height)
                    else source.resize(size, Image.Resampling.LANCZOS)
                )
                # Only the current size is kept; ladder sizes never repeat after
                # they shrink, so this holds at most one resized image.
                resized = {size: image}
            payload = _encode_jpeg(image, step.quality)
            if len(payload) <= cap_bytes:
                return EncodedImage(
                    payload=payload,
                    width=size[0],
                    height=size[1],
                    quality=step.quality,
                    ladder_step=index,
                )
        return None


def _encode_jpeg(image: Image.Image, quality: int) -> bytes:
    buffer = BytesIO()
    image.save(
        buffer,
        format="JPEG",
        quality=quality,
        optimize=False,
        progressive=False,
        subsampling=2,
    )
    return buffer.getvalue()
