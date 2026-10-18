"""Stage 4 B1 (#228): experiment-only NearView seam with scale-normalised sharpness. Development tooling only.

The frozen candidate is ``docs/qualification/stage4/b1-candidate-v1.json``; this module implements it and
nothing else. Production ``mavi_vision`` code and the release profile are not modified:

* ``b1_sharpness`` is the production sharpness formula over the whole Vehicle crop after a downscale-only
  resize to 128 px height (Pillow BILINEAR); undefined (``None``) when the native crop is 128 px tall or less.
* ``B1NearViewSelector`` subclasses the production ``EvidenceSelector``. Every candidate first runs through the
  unchanged production ``observe``; only for a *b1-only* candidate (fails the original sharpness floor, passes
  ``b1_sharpness`` and every unchanged confidence/edge/occlusion gate) is the unchanged production NearView rule
  then applied, with the holders as they stand. A b1-only candidate never reaches Representative qualification,
  EarlyDiverse or LateDiverse. A NearView it wins is held with ``qualified=False`` (B1-experiment-admitted).
  ``mode="shadow"`` records the opportunity without holding anything (preflight).
* ``b1_composition`` is the composition seam: ``VideoProcessor`` constructs ``process_video.EvidenceSelector``
  per Track, so the experiment arm swaps that one name for the duration of a run and restores it.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
from PIL import Image

from mavi_vision.common.analytical import NormalizedBoundingBox, ObjectClass
from mavi_vision.evidence import selector as selector_module
from mavi_vision.evidence.quality import CandidateQuality
from mavi_vision.evidence.roles import EvidenceRole
from mavi_vision.evidence.selector import EvidenceSelector
from mavi_vision.quality.scoring import _normalized_sharpness, crop_region

ROOT = Path(__file__).resolve().parents[3]
FROZEN_RECORD = ROOT / "docs" / "qualification" / "stage4" / "b1-candidate-v1.json"
RULE_ID = "b1-nearview-scale-normalised-sharpness-v1"
TARGET_HEIGHT_PX = 128
_FULL = NormalizedBoundingBox(0.0, 0.0, 1.0, 1.0)


def frozen_record() -> tuple[dict[str, Any], str]:
    data = FROZEN_RECORD.read_bytes()
    record = json.loads(data)
    if record["id"] != RULE_ID or record["intervention"]["targetHeightPx"] != TARGET_HEIGHT_PX:
        raise RuntimeError("b1_frozen_record_mismatch")
    return record, hashlib.sha256(data).hexdigest()


def resized_width(width: int, height: int) -> int:
    return max(1, round(width * TARGET_HEIGHT_PX / height))


def b1_sharpness_of_crop(crop: np.ndarray) -> float | None:
    """The frozen experimental sharpness of one RGB crop; ``None`` when it would need upscaling (or is empty)."""
    height, width = crop.shape[:2]
    if height <= TARGET_HEIGHT_PX or width == 0:
        return None
    image = Image.fromarray(np.ascontiguousarray(crop))
    resized = np.asarray(image.resize((resized_width(width, height), TARGET_HEIGHT_PX), Image.Resampling.BILINEAR))
    return _normalized_sharpness(SimpleNamespace(image=resized), _FULL)


def b1_sharpness(frame, box: NormalizedBoundingBox) -> float | None:
    return b1_sharpness_of_crop(crop_region(frame, box))


def native_crop_height(frame, box: NormalizedBoundingBox) -> int:
    return int(crop_region(frame, box).shape[0])


def gates(policy, candidate, quality: CandidateQuality) -> dict[str, bool]:
    """The production qualification gates, each by name (the production rule is their conjunction)."""
    return {"confidence": candidate.confidence >= policy.confidence_floor,
            "sharpness": quality.sharpness >= policy.sharpness_floor,
            "edge": quality.edge_margin >= policy.edge_margin_floor,
            "occlusion": quality.occlusion_iou < policy.occlusion_iou_ceiling}


def assess(policy, candidate, quality: CandidateQuality, b1_value: float | None) -> dict[str, Any]:
    g = gates(policy, candidate, quality)
    original = all(g.values())
    vehicle = candidate.object_class is ObjectClass.VEHICLE
    pass_b1 = vehicle and b1_value is not None and b1_value >= policy.sharpness_floor
    near_b1 = original or (pass_b1 and g["confidence"] and g["edge"] and g["occlusion"])
    return {"gates": g, "passSharpnessB1": pass_b1, "qualifiedOriginal": original, "qualifiedNearB1": near_b1,
            "b1Only": near_b1 and not original}


class _LastQuality:
    """Transparent scorer proxy that remembers the last score, so the subclass never scores a candidate twice."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.version = getattr(inner, "version", None)
        self.last: CandidateQuality | None = None

    def score(self, context, candidate):
        self.last = self._inner.score(context, candidate)
        return self.last


class B1NearViewSelector(EvidenceSelector):
    __slots__ = ("_b1_sink", "_b1_mode", "_b1_sharpness", "_b1_proxy")

    def __init__(self, *, policy, scorer, encoder, track_start_ms: int, sink: list[dict], mode: str = "active",
                 sharpness: Callable[[Any, NormalizedBoundingBox], float | None] = b1_sharpness) -> None:
        if mode not in ("active", "shadow"):
            raise ValueError("b1_mode_invalid")
        proxy = _LastQuality(scorer)
        super().__init__(policy=policy, scorer=proxy, encoder=encoder, track_start_ms=track_start_ms)
        self._b1_proxy, self._b1_sink, self._b1_mode, self._b1_sharpness = proxy, sink, mode, sharpness

    def observe(self, context, candidate) -> None:
        super().observe(context, candidate)  # the unchanged production rules, every role
        if candidate.object_class is not ObjectClass.VEHICLE:
            return
        quality = self._b1_proxy.last
        g = gates(self._policy, candidate, quality)
        if g["sharpness"] or not (g["confidence"] and g["edge"] and g["occlusion"]):
            return  # production-qualified (already handled) or blocked by an unchanged gate
        value = self._b1_sharpness(context.frame, candidate.bounding_box)
        if not assess(self._policy, candidate, quality, value)["b1Only"]:
            return
        frame = context.frame
        view = selector_module._View(frame.offset_ms, frame.source_frame_number, candidate.bounding_box)
        representative, near_view = self._holders[0], self._holders[1]
        duplicate = self._near_duplicate(view, representative)
        grew = near_view is None or self._area_grew(quality.area, near_view.area)
        opportunity = not duplicate and grew
        row = {"trackId": str(candidate.track_id), "frame": frame.source_frame_number, "offsetMs": frame.offset_ms,
               "area": quality.area, "sharpness": quality.sharpness, "b1Sharpness": value,
               "nearDuplicateOfRepresentative": duplicate, "growthAllows": grew, "opportunity": opportunity,
               "heldBefore": None if near_view is None else near_view.source_frame_number,
               "mode": self._b1_mode, "held": False}
        if opportunity and self._b1_mode == "active":
            before = self._holders[1]
            self._try_hold(EvidenceRole.NEAR_VIEW, context, candidate, quality, False)
            row["held"] = self._holders[1] is not before
            row["encodeRefused"] = not row["held"]
        self._b1_sink.append(row)


@contextlib.contextmanager
def b1_composition(factory: Callable[..., EvidenceSelector]) -> Iterator[None]:
    """Make ``VideoProcessor`` build ``factory(**kwargs)`` instead of the production selector, for one run only."""
    from mavi_vision.pipeline import process_video

    if process_video.EvidenceSelector is not EvidenceSelector:
        raise RuntimeError("b1_composition_not_production_at_entry")
    process_video.EvidenceSelector = factory
    try:
        yield
    finally:
        process_video.EvidenceSelector = EvidenceSelector


class B1RecordingScorer:
    """Wraps the X1 ``RecordingScorer`` (production gates per candidate) and adds the B1 scalars to its row.

    Observation only: the returned quality is the inner scorer's, unchanged, in every arm.
    """

    def __init__(self, recording, policy, sink: list[dict]) -> None:
        self._recording, self._policy, self._sink = recording, policy, sink
        self.version = getattr(recording, "version", None)

    def score(self, context, candidate):
        quality = self._recording.score(context, candidate)
        row = self._sink[-1]
        if candidate.object_class is ObjectClass.VEHICLE:
            value = b1_sharpness(context.frame, candidate.bounding_box)
            a = assess(self._policy, candidate, quality, value)
            row.update(native_height_px=native_crop_height(context.frame, candidate.bounding_box),
                       b1_sharpness=value, pass_sharpness_b1=a["passSharpnessB1"],
                       qualified_original=a["qualifiedOriginal"], qualified_near_b1=a["qualifiedNearB1"],
                       b1_only=a["b1Only"])
        return quality
