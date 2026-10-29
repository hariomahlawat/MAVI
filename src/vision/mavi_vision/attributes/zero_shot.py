"""SigLIP 2 zero-shot attribute inferencer (PoC S5; ADR-021 amendment 2026-10-29; zero-shot, Development).

The inferencer replaces the S2b fixture behind the unchanged ``AttributeInferencer`` seam: lease, evidence
transport, digest verification, ``mean-score-argmax`` aggregation, the sealed artefact and completion are the S2b
code. It scores one verified crop against text prototypes built from the prompts in the pipeline's parameters
document (whose SHA-256 is part of the analysis identity, so a prompt or threshold change is a new identity).

Per attribute:

* ``categorical`` (a colour): ``p = softmax(logitScale * cos(image, prototype_v))`` over the schema's values;
* ``presence`` (schema values exactly ``["present"]``): ``p = softmax`` over the ``present`` and ``absent``
  prototypes, and only ``present`` is emitted, so the outcome is ``present`` or Unknown and never a negative claim
  (Stage-2 plan §13: ``Absent`` needs qualified negative semantics, which a zero-shot model does not have).

Each ``p`` is mapped through the attribute's abstention threshold ``t`` by the monotone piecewise-linear
``g(p) = 0.5 p / t`` below ``t`` and ``0.5 + 0.5 (p - t) / (1 - t)`` above it, so the aggregation policy's single
``minimumConfidence`` of 0.5 applies each attribute's own threshold. A row's confidence is therefore an
abstention-normalised score (0.5 is the threshold), not a probability.

A crop whose shorter side is under ``minimumCropSide`` contributes zero scores (no evidence): S4 found small crops
collapse into a generic cluster (ADR-021 §1). Because the aggregation averages over every scored crop, small crops
can only move a Track towards Unknown, never towards a value.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Mapping

import numpy as np

from mavi_vision.attributes.inference import CropDecodeError, VerifiedCrop
from mavi_vision.attributes.pipeline import AttributeDefinition, AttributeSchema
from mavi_vision.embeddings.model import EmbeddingModel, inspect_crop, l2_normalise_rows

INFERENCER_ID = "siglip2-zero-shot-v1"
KIND_CATEGORICAL = "categorical"
KIND_PRESENCE = "presence"
PRESENT = "present"
ABSTENTION_SCORE = 0.5
MAXIMUM_PROMPTS_PER_VALUE = 8
MAXIMUM_PROMPT_CHARACTERS = 200
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*\.json$")
_TEXT_BATCH = 16


def _fail(detail: str) -> ValueError:
    return ValueError(f"attribute_zero_shot_parameters_invalid:{detail}")


@dataclass(frozen=True, slots=True)
class ZeroShotAttribute:
    attribute_type: str
    kind: str
    threshold: float
    # Categorical: one prompt list per schema value, in schema order. Presence: (present, absent).
    prompts: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class ZeroShotParameters:
    model_manifest_file: str
    model_manifest_sha256: str
    logit_scale: float
    minimum_crop_side: int
    attributes: Mapping[str, ZeroShotAttribute]


def is_zero_shot(parameters: Mapping[str, object]) -> bool:
    return parameters.get("inferencer") == INFERENCER_ID


def _prompts(value: object, detail: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAXIMUM_PROMPTS_PER_VALUE:
        raise _fail(detail)
    prompts = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item) > MAXIMUM_PROMPT_CHARACTERS or item != item.strip():
            raise _fail(detail)
        prompts.append(item)
    if len(set(prompts)) != len(prompts):
        raise _fail(detail)
    return tuple(prompts)


def _number(value: object, detail: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise _fail(detail)
    return float(value)


def parse_zero_shot_parameters(parameters: Mapping[str, object], schema: AttributeSchema) -> ZeroShotParameters:
    """The ``siglip2-zero-shot-v1`` parameters, checked exactly against the attribute schema, or a refusal."""
    expected = {"inferencer", "disclosure", "modelManifest", "logitScale", "minimumCropSide", "attributes"}
    if set(parameters) != expected or parameters["inferencer"] != INFERENCER_ID:
        raise _fail("keys")
    if parameters["disclosure"] != "zero-shot, Development":
        raise _fail("disclosure")
    manifest = parameters["modelManifest"]
    if not isinstance(manifest, Mapping) or set(manifest) != {"file", "sha256"}:
        raise _fail("modelManifest")
    file_name, sha256 = manifest["file"], manifest["sha256"]
    if not isinstance(file_name, str) or _FILE_NAME_RE.fullmatch(file_name) is None:
        raise _fail("modelManifest")
    if not isinstance(sha256, str) or _SHA256_RE.fullmatch(sha256) is None:
        raise _fail("modelManifest")
    logit_scale = _number(parameters["logitScale"], "logitScale")
    if not 1.0 <= logit_scale <= 1000.0:
        raise _fail("logitScale")
    side = parameters["minimumCropSide"]
    if isinstance(side, bool) or not isinstance(side, int) or not 1 <= side <= 1024:
        raise _fail("minimumCropSide")
    documents = parameters["attributes"]
    if not isinstance(documents, Mapping) or set(documents) != {item.attribute_type for item in schema.attributes}:
        raise _fail("attributes")
    attributes: dict[str, ZeroShotAttribute] = {}
    for definition in schema.attributes:
        name = definition.attribute_type
        document = documents[name]
        if not isinstance(document, Mapping) or set(document) != {"kind", "threshold", "prompts"}:
            raise _fail(name)
        threshold = _number(document["threshold"], f"{name}:threshold")
        if not 0.0 < threshold < 1.0:
            raise _fail(f"{name}:threshold")
        prompts = document["prompts"]
        if not isinstance(prompts, Mapping):
            raise _fail(f"{name}:prompts")
        if document["kind"] == KIND_CATEGORICAL:
            if len(definition.values) < 2 or set(prompts) != set(definition.values):
                raise _fail(f"{name}:prompts")
            lists = tuple(_prompts(prompts[value], f"{name}:{value}") for value in definition.values)
        elif document["kind"] == KIND_PRESENCE:
            if definition.values != (PRESENT,) or set(prompts) != {"present", "absent"}:
                raise _fail(f"{name}:prompts")
            lists = (_prompts(prompts["present"], f"{name}:present"), _prompts(prompts["absent"], f"{name}:absent"))
        else:
            raise _fail(f"{name}:kind")
        attributes[name] = ZeroShotAttribute(name, document["kind"], threshold, lists)
    return ZeroShotParameters(file_name, sha256, logit_scale, side, attributes)


def abstention_score(probability: float, threshold: float) -> float:
    """The monotone map that puts ``threshold`` at the policy's 0.5: ``g(t) = 0.5``, ``g(0) = 0``, ``g(1) = 1``."""
    if probability < threshold:
        value = ABSTENTION_SCORE * probability / threshold
    else:
        value = ABSTENTION_SCORE + ABSTENTION_SCORE * (probability - threshold) / (1.0 - threshold)
    return min(1.0, max(0.0, value))


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits)
    weights = np.exp(shifted)
    return weights / np.sum(weights)


class SiglipZeroShotInferencer:
    """``AttributeInferencer`` over the SigLIP 2 Model Pack; text prototypes are built once, at construction."""

    def __init__(self, model: EmbeddingModel, parameters: ZeroShotParameters) -> None:
        self._model = model
        self._parameters = parameters
        texts: list[str] = []
        spans: dict[str, list[tuple[int, int]]] = {}
        for name, attribute in parameters.attributes.items():
            spans[name] = []
            for prompts in attribute.prompts:
                spans[name].append((len(texts), len(texts) + len(prompts)))
                texts.extend(prompts)
        vectors = np.concatenate(
            [l2_normalise_rows(model.embed_texts(texts[start:start + _TEXT_BATCH]), model.dimension)
             for start in range(0, len(texts), _TEXT_BATCH)]
        )
        # Prompt ensembling: the prototype of a value is the normalised mean of its prompts' unit vectors.
        self._prototypes = {
            name: l2_normalise_rows(np.stack([vectors[start:end].mean(axis=0) for start, end in items]), model.dimension)
            for name, items in spans.items()
        }

    @property
    def parameters(self) -> ZeroShotParameters:
        return self._parameters

    def probabilities(self, image: np.ndarray, attribute_type: str) -> np.ndarray:
        """``p`` for one unit image vector: per schema value (categorical) or ``[present, absent]`` (presence)."""
        logits = self._parameters.logit_scale * (self._prototypes[attribute_type] @ image)
        return _softmax(logits)

    def score(
        self, crop: VerifiedCrop, attributes: tuple[AttributeDefinition, ...]
    ) -> Mapping[str, Mapping[str, float]]:
        decoded = inspect_crop(crop.content)
        if decoded is None:
            raise CropDecodeError("crop is not a decodable image")
        if decoded.shorter_side < self._parameters.minimum_crop_side:
            return {item.attribute_type: {value: 0.0 for value in item.values} for item in attributes}
        image = l2_normalise_rows(self._model.embed_images([crop.content]), self._model.dimension)[0]
        scores: dict[str, dict[str, float]] = {}
        for definition in attributes:
            attribute = self._parameters.attributes[definition.attribute_type]
            probabilities = self.probabilities(image, definition.attribute_type)
            if attribute.kind == KIND_PRESENCE:
                scores[definition.attribute_type] = {PRESENT: abstention_score(float(probabilities[0]), attribute.threshold)}
            else:
                scores[definition.attribute_type] = {
                    value: abstention_score(float(probabilities[index]), attribute.threshold)
                    for index, value in enumerate(definition.values)
                }
        return scores


__all__ = [
    "ABSTENTION_SCORE",
    "INFERENCER_ID",
    "SiglipZeroShotInferencer",
    "ZeroShotAttribute",
    "ZeroShotParameters",
    "abstention_score",
    "is_zero_shot",
    "parse_zero_shot_parameters",
]
