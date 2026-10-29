"""The model boundary of the ``embeddings`` role, preprocessing and vector encoding (ADR-021 §1).

Model-specific code stays behind :class:`EmbeddingModel`. ``embed_images`` takes verified JPEG bytes and
``embed_texts`` normalised appearance texts; both return raw float32 rows (``[N, dimension]``) which the runner
L2-normalises and checks. :class:`FixtureEmbeddingModel` is a deterministic stand-in for tests and Development
fixtures only: it never runs in production because the role itself refuses production mode.
"""

from __future__ import annotations

import base64
import hashlib
import io
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from PIL import Image

IMAGE_SIZE = 224


class EmbeddingModel(Protocol):
    @property
    def dimension(self) -> int: ...

    def embed_images(self, crops: list[bytes]) -> np.ndarray: ...

    def embed_texts(self, texts: list[str]) -> np.ndarray: ...


class OutputInvalid(ValueError):
    """The model produced a vector the contract cannot carry (wrong shape, non-finite or zero)."""


@dataclass(frozen=True, slots=True)
class DecodedCrop:
    width: int
    height: int

    @property
    def shorter_side(self) -> int:
        return min(self.width, self.height)


def inspect_crop(data: bytes) -> DecodedCrop | None:
    """Fully decode verified crop bytes; ``None`` when the bytes are not a decodable image."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            width, height = image.size
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
    if width < 1 or height < 1:
        return None
    return DecodedCrop(width, height)


def preprocess(data: bytes) -> np.ndarray:
    """``siglip2-fixed-224-v1``: RGB, bilinear 224x224, ``(x/255 - 0.5)/0.5``, NCHW ``[1, 3, 224, 224]``.

    Identical to ``tools/poc/embeddings_spike.py::preprocess``, applied to bytes instead of a path.
    """
    with Image.open(io.BytesIO(data)) as image:
        rgb = image.convert("RGB").resize((IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.BILINEAR)
    array = np.asarray(rgb, dtype=np.float32) / 255.0
    array = (array - 0.5) / 0.5
    return array.transpose(2, 0, 1)[None, ...]


def l2_normalise_rows(matrix: np.ndarray, dimension: int) -> np.ndarray:
    """Each row divided by its L2 norm; a wrong shape, a non-finite value or a zero row is ``OutputInvalid``."""
    array = np.asarray(matrix)
    if array.ndim != 2 or array.shape[1] != dimension:
        raise OutputInvalid(f"embedding output shape {tuple(array.shape)} is not [N, {dimension}]")
    array = array.astype(np.float64)
    if not np.all(np.isfinite(array)):
        raise OutputInvalid("embedding output is not finite")
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    if np.any(norms <= 1e-12):
        raise OutputInvalid("embedding output has a zero vector")
    return array / norms


def mean_l2(rows: np.ndarray, dimension: int) -> np.ndarray:
    """``mean-l2-v1``: normalise each crop vector, average, normalise the mean again (float64 throughout)."""
    normalised = l2_normalise_rows(rows, dimension)
    if normalised.shape[0] < 1:
        raise OutputInvalid("no crop vector to aggregate")
    mean = normalised.mean(axis=0, keepdims=True)
    return l2_normalise_rows(mean, dimension)[0]


def encode_vector(vector: np.ndarray, dimension: int) -> str:
    """Little-endian float32, standard padded base64; finite and of unit norm within the contract's tolerance."""
    values = np.asarray(vector, dtype="<f4")
    if values.shape != (dimension,) or not np.all(np.isfinite(values)):
        raise OutputInvalid("embedding vector has the wrong shape or is not finite")
    if abs(float(np.linalg.norm(values.astype(np.float64))) - 1.0) > 1e-3:
        raise OutputInvalid("embedding vector is not unit-norm")
    return base64.b64encode(values.tobytes()).decode("ascii")


def decode_vector(text: str, dimension: int) -> np.ndarray:
    raw = base64.b64decode(text, validate=True)
    if len(raw) != 4 * dimension:
        raise ValueError("embedding vector length mismatch")
    return np.frombuffer(raw, dtype="<f4").astype(np.float32)


class FixtureEmbeddingModel:
    """Deterministic unit vectors seeded by the SHA-256 of each input (tests and Development fixtures only)."""

    def __init__(self, dimension: int) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def _vector(self, domain: bytes, payload: bytes) -> np.ndarray:
        seed = int.from_bytes(hashlib.sha256(domain + payload).digest()[:8], "little")
        vector = np.random.default_rng(seed).standard_normal(self._dimension)
        return (vector / np.linalg.norm(vector)).astype(np.float32)

    def embed_images(self, crops: list[bytes]) -> np.ndarray:
        if not crops:
            return np.zeros((0, self._dimension), dtype=np.float32)
        return np.stack([self._vector(b"image:", crop) for crop in crops])

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dimension), dtype=np.float32)
        return np.stack([self._vector(b"text:", text.encode("utf-8")) for text in texts])


__all__ = [
    "DecodedCrop",
    "EmbeddingModel",
    "FixtureEmbeddingModel",
    "IMAGE_SIZE",
    "OutputInvalid",
    "decode_vector",
    "encode_vector",
    "inspect_crop",
    "l2_normalise_rows",
    "mean_l2",
    "preprocess",
]
