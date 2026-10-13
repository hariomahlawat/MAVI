"""The two seams a plate model replaces (Stage 4 plan §2.4).

A ``PlateDetector`` receives one decoded, verified evidence crop and returns plate boxes in that crop's
pixel space; a ``PlateRecogniser`` receives one plate region and returns ranked raw readings. Each is a
capability (``plate-detector``, ``ocr``) with its own Model Pack, so replacing one changes one
``modelPackId``. Everything around them — lease, evidence verification, decode, selection, summary,
encoding, upload, completion — is role code a real model uses unchanged. Two-line plates are the
recogniser adapter's concern: it returns the lines joined by one LF, top line first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PIL import Image


class CropDecodeError(ValueError):
    """Verified bytes that no decoder can read: the crop abstains with ``decode_failed``."""


@dataclass(frozen=True, slots=True)
class VerifiedCrop:
    """An accepted crop whose bytes matched their recorded size and SHA-256."""

    observation_id: str
    role: str
    evidence_rank: int
    sha256: str
    content: bytes


@dataclass(frozen=True, slots=True)
class PlateBox:
    """A detector box in decoded-crop pixel coordinates, with the detector's score in [0, 1]."""

    x: int
    y: int
    width: int
    height: int
    score: float


@dataclass(frozen=True, slots=True)
class Reading:
    """One OCR hypothesis: raw text exactly as the model emitted it, and its confidence in [0, 1]."""

    raw_text: str
    confidence: float


class PlateDetector(Protocol):
    def detect(self, crop: Image.Image, verified: VerifiedCrop) -> list[PlateBox]:
        """Every plate box the model proposes; raising is a ``detector_error`` abstention."""
        ...


class PlateRecogniser(Protocol):
    def read(self, region: Image.Image, verified: VerifiedCrop, box: PlateBox) -> list[Reading]:
        """Readings for one plate region; raising is an ``ocr_error`` abstention."""
        ...


def decode_crop(content: bytes) -> Image.Image:
    """Decode verified evidence bytes once, as RGB. Anything undecodable is ``CropDecodeError``."""
    from io import BytesIO

    try:
        with Image.open(BytesIO(content)) as image:
            image.load()
            return image.convert("RGB")
    except Exception as exc:  # Pillow raises several unrelated types for corrupt input.
        raise CropDecodeError("plate_crop_undecodable") from exc


__all__ = [
    "CropDecodeError",
    "PlateBox",
    "PlateDetector",
    "PlateRecogniser",
    "Reading",
    "VerifiedCrop",
    "decode_crop",
]
