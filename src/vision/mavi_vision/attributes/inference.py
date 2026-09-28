"""Attribute inference: the one seam a learned model replaces (S2b plan §14).

An ``AttributeInferencer`` receives one accepted crop whose size and SHA-256 were already
verified, and returns raw per-value scores for every applicable attribute. Everything around
it — lease, heartbeat, evidence transport, verification, aggregation, encoding, upload,
completion — is production code that a real model uses unchanged.

``FixtureAttributeInferencer`` is Development-only (its pipeline profile is
``developmentOnly``, which the resolver refuses in Production). Its "decode" is a structural
JPEG envelope check and its scores are derived from the verified bytes and the fixture seed,
never from a clock or a random source, so a run is exactly reproducible.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping, Protocol

from mavi_vision.attributes.pipeline import AttributeDefinition


class CropDecodeError(ValueError):
    """Verified bytes that are not a decodable crop: the authoritative ``evidence_decode_failed``."""


@dataclass(frozen=True, slots=True)
class VerifiedCrop:
    """An accepted crop whose bytes matched their recorded size and SHA-256."""

    observation_id: str
    evidence_rank: int
    sha256: str
    content: bytes


class AttributeInferencer(Protocol):
    def score(
        self, crop: VerifiedCrop, attributes: tuple[AttributeDefinition, ...]
    ) -> Mapping[str, Mapping[str, float]]:
        """Scores per attribute type and value; raises ``CropDecodeError`` for an undecodable crop."""
        ...


class FixtureAttributeInferencer:
    """Deterministic, model-free scores for the S2b qualification fixture."""

    def __init__(self, seed: str) -> None:
        if not seed:
            raise ValueError("attribute_fixture_seed_required")
        self._seed = seed

    def score(
        self, crop: VerifiedCrop, attributes: tuple[AttributeDefinition, ...]
    ) -> Mapping[str, Mapping[str, float]]:
        content = crop.content
        # Structural decode: a JPEG starts with SOI and ends with EOI. Anything else is a crop
        # the platform accepted but no decoder can read — an authoritative condition.
        if len(content) < 4 or content[:2] != b"\xff\xd8" or content[-2:] != b"\xff\xd9":
            raise CropDecodeError("crop is not a JPEG envelope")
        scores: dict[str, dict[str, float]] = {}
        for attribute in attributes:
            raw = {
                value: int.from_bytes(
                    hashlib.sha256(f"{self._seed}\0{crop.sha256}\0{attribute.attribute_type}\0{value}".encode()).digest()[:4],
                    "big",
                )
                + 1
                for value in attribute.values
            }
            total = sum(raw.values())
            scores[attribute.attribute_type] = {value: raw[value] / total for value in attribute.values}
        return scores


def inferencer_for(profile_parameters: Mapping[str, object], *, development_only: bool) -> AttributeInferencer:
    """The inferencer a profile names. S2b ships only the fixture; a real model is S3's."""
    seed = profile_parameters.get("fixtureSeed")
    if isinstance(seed, str) and development_only:
        return FixtureAttributeInferencer(seed)
    raise ValueError("attribute_inferencer_unavailable")


__all__ = [
    "AttributeInferencer",
    "CropDecodeError",
    "FixtureAttributeInferencer",
    "VerifiedCrop",
    "inferencer_for",
]
