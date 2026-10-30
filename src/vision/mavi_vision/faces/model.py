"""The model boundary of the ``faces`` role: decoding, embedder preprocessing and thumbnails (ADR-022 §3).

Model-specific code stays behind :class:`FaceModel`: ``detect`` returns the YuNet detections at the profile's score
threshold for one RGB crop, and ``embed`` returns raw float32 rows (``[N, dimension]``) for aligned 112×112 RGB
faces, which the runner L2-normalises and checks. :class:`FixtureFaceModel` is a deterministic stand-in for tests
only; the role itself refuses production mode.
"""

from __future__ import annotations

import base64
import hashlib
import io
from typing import Callable, Protocol

import numpy as np
from PIL import Image

from mavi_vision.embeddings.model import OutputInvalid, decode_vector, encode_vector, l2_normalise_rows
from mavi_vision.faces.contracts import MAXIMUM_QUERY_IMAGE_PIXELS, THUMBNAIL_JPEG_QUALITY
from mavi_vision.faces.detector import FaceDetection

_QUERY_FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG"}
# Evidence crops are bounded by their accepted size (16 MiB); this bounds their decoded area as well.
MAXIMUM_CROP_PIXELS = 8192 * 8192


class FaceModel(Protocol):
    @property
    def dimension(self) -> int: ...

    def detect(self, rgb: np.ndarray) -> list[FaceDetection]: ...

    def embed(self, faces: list[np.ndarray]) -> np.ndarray: ...


class QueryImageInvalid(ValueError):
    """A query image that is not a decodable JPEG or PNG of its declared type within the bounds."""


def _decode(image: Image.Image, maximum_pixels: int) -> np.ndarray:
    width, height = image.size
    if width < 1 or height < 1 or width * height > maximum_pixels:
        raise ValueError("image dimensions outside the bounds")
    image.load()
    return np.ascontiguousarray(np.asarray(image.convert("RGB"), dtype=np.uint8))


def decode_crop(data: bytes) -> np.ndarray | None:
    """Verified evidence bytes as an ``[H, W, 3]`` uint8 RGB array; ``None`` when they are not a decodable image."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            return _decode(image, MAXIMUM_CROP_PIXELS)
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def decode_query_image(data: bytes, mime_type: str, maximum_bytes: int) -> np.ndarray:
    """A query image as RGB: only JPEG or PNG, the format its declared type names, within the byte and pixel bounds.

    The pixel bound is checked from the header before any pixel is decoded (a decompression-bomb guard that does
    not depend on Pillow's process-wide ``MAX_IMAGE_PIXELS``).
    """
    expected = _QUERY_FORMATS.get(mime_type)
    if expected is None:
        raise QueryImageInvalid("query image type is not image/jpeg or image/png")
    if not 1 <= len(data) <= maximum_bytes:
        raise QueryImageInvalid("query image size outside the bound")
    try:
        with Image.open(io.BytesIO(data), formats=[expected]) as image:
            return _decode(image, MAXIMUM_QUERY_IMAGE_PIXELS)
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise QueryImageInvalid("query image is not a decodable image of its declared type") from exc


def embedder_input(aligned: np.ndarray, preprocessing: str) -> np.ndarray:
    """``[3, 112, 112]`` float32 from an aligned RGB face: ``adaface-ir50-v1`` ``(x/255 - 0.5)/0.5``; ``sface-v1``
    raw 0-255 RGB. Identical to ``tools/poc/faces_embedder_spike.py::embedder_input``."""
    if aligned.shape != (112, 112, 3) or aligned.dtype != np.uint8:
        raise ValueError("face_aligned_shape")
    x = aligned.astype(np.float32)
    if preprocessing == "adaface-ir50-v1":
        x = (x / 255.0 - 0.5) / 0.5
    elif preprocessing != "sface-v1":
        raise ValueError("face_preprocessing_unsupported")
    return x.transpose(2, 0, 1)


def thumbnail_jpeg(aligned: np.ndarray) -> str:
    """The aligned 112×112 face as a standard-base64 JPEG (quality 90): the only face image the role produces, and
    only for a usable face of a transient query (ADR-022 §4)."""
    buffer = io.BytesIO()
    Image.fromarray(aligned).save(buffer, "JPEG", quality=THUMBNAIL_JPEG_QUALITY)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class FixtureFaceModel:
    """Tests only: detections from a callable over the decoded crop; deterministic unit vectors per aligned face."""

    def __init__(self, dimension: int, detections: Callable[[np.ndarray], list[FaceDetection]] | None = None) -> None:
        self._dimension = dimension
        self._detections = detections or (lambda rgb: [])

    @property
    def dimension(self) -> int:
        return self._dimension

    def detect(self, rgb: np.ndarray) -> list[FaceDetection]:
        return list(self._detections(rgb))

    def embed(self, faces: list[np.ndarray]) -> np.ndarray:
        if not faces:
            return np.zeros((0, self._dimension), dtype=np.float32)
        rows = []
        for face in faces:
            seed = int.from_bytes(hashlib.sha256(b"face:" + face.tobytes()).digest()[:8], "little")
            vector = np.random.default_rng(seed).standard_normal(self._dimension)
            rows.append((vector / np.linalg.norm(vector)).astype(np.float32))
        return np.stack(rows)


__all__ = [
    "FaceModel",
    "FixtureFaceModel",
    "MAXIMUM_CROP_PIXELS",
    "OutputInvalid",
    "QueryImageInvalid",
    "decode_crop",
    "decode_query_image",
    "decode_vector",
    "embedder_input",
    "encode_vector",
    "l2_normalise_rows",
    "thumbnail_jpeg",
]
