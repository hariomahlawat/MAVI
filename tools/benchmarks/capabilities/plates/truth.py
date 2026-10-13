"""Canonical plate ground truth ``benchmark-plate-truth-v1`` (Stage 4 PR-1; ADR-017 §11) and its geometry.

One document per dataset release split, written by an adapter from verified source bytes. Items are images (``still``)
or labelled frames of vehicle sequences (``sequence``, which also carry ``sequenceId``/``frameIndex``/``gtTrackId``
naming the vehicle track of the sequence's ``vehicle_tracks`` ground truth). A plate's raw label is kept verbatim;
``textUsable`` is exactly "the label normalises (``mavi-plate-normalisation-v1``) to ``ok``", so a label the
normaliser rejects is visible and counted, never dropped.

**Masked labels** (protocol §5 R6). Some releases anonymise characters (UC3M-LP blurs characters for GDPR and labels
each as ``*``). ``*`` is a *known unknown*: the label is normalised position by position (ASCII only, so NFKC is the
identity), masked positions are kept as ``*``, and a read matches only when it has exactly the truth's length and
equals it at every unmasked position (``text_matches``). A label that is all masks is unusable (``fully-masked``).

Geometry is in source pixels. A plate polygon is four corners TL, TR, BR, BL; datasets that label only boxes give an
axis-aligned polygon, which makes their skew 0 (the oblique stratum is then unavailable for that dataset and is
reported as such). The character-height proxy is the mean of the polygon's left and right edge lengths divided by the
line count (1 when the layout is unknown) — a declared proxy, not a per-character measurement.
"""

from __future__ import annotations

import math
from typing import Any

from tools.benchmarks.core.identity import S32Error, require, validate
from tools.benchmarks.plates.normalisation import NORMALISATION_ID, OK, normalise

SCHEMA = "benchmark-plate-truth-v1"
CODE = "plate_truth_invalid"
LAYOUT_LINES = {"one-line": 1, "two-line": 2, "unknown": None}


MASK = "*"


def _masked_normalise(text: str) -> tuple[str | None, str | None]:
    """``(normalised text with masks, rejection reason)`` of a label containing ``MASK`` (ASCII labels only)."""
    if not text.isascii():
        return None, "non-alphanumeric"
    kept = []
    for character in text:
        if character == MASK:
            kept.append(MASK)
            continue
        result = normalise(character)
        if result.outcome != OK and result.reason == "empty":
            continue  # a separator
        if result.outcome != OK:
            return None, result.reason
        kept.append(result.normalised)
    value = "".join(kept)
    if not value:
        return None, "empty"
    if set(value) == {MASK}:
        return None, "fully-masked"
    return value, None


def text_usability(text: str | None) -> tuple[bool, str | None]:
    """``(textUsable, textUnusableReason)`` of a raw label."""
    if text is None:
        return False, "unlabelled"
    if MASK in text:
        value, reason = _masked_normalise(text)
        return (True, None) if value is not None else (False, reason)
    result = normalise(text)
    return (True, None) if result.outcome == OK else (False, result.reason)


def masked_count(text: str | None) -> int:
    return 0 if text is None else text.count(MASK)


def truth_text(plate: dict[str, Any]) -> str:
    """The normalised ground-truth text of a text-usable plate (``MASK`` at masked positions)."""
    require(plate["textUsable"], f"{CODE}:text_unusable:{plate['plateId']}")
    if MASK in plate["text"]:
        return _masked_normalise(plate["text"])[0]  # type: ignore[return-value]
    return normalise(plate["text"]).normalised  # type: ignore[return-value]


def text_matches(read: str | None, truth: str) -> bool:
    """Exact match of a normalised read against the truth: equal length and equal at every unmasked position."""
    return read is not None and len(read) == len(truth) and all(t in (MASK, r) for r, t in zip(read, truth))


def _inside(point: list[float], width: int, height: int) -> bool:
    return 0 <= point[0] <= width and 0 <= point[1] <= height


def validate_document(document: Any) -> dict[str, Any]:
    """Schema plus the rules a schema cannot state; returns the document."""
    validate(document, SCHEMA, CODE)
    require(document["normalisationId"] == NORMALISATION_ID, f"{CODE}:normalisation")
    sequence = document["kind"] == "sequence"
    ids = [item["itemId"] for item in document["items"]]
    require(ids == sorted(set(ids)), f"{CODE}:item_order")
    for item in document["items"]:
        where = item["itemId"]
        width, height = item["frameSize"]["width"], item["frameSize"]["height"]
        linked = (item["sequenceId"], item["frameIndex"], item["gtTrackId"])
        if sequence:
            require(all(value is not None for value in linked), f"{CODE}:sequence_fields:{where}")
            # One item per (frame, ground-truth track): several vehicles share a frame.
            require(where == f"{item['sequenceId']}/{item['frameIndex']:06d}/{item['gtTrackId']}",
                    f"{CODE}:item_id:{where}")
        else:
            require(all(value is None for value in linked), f"{CODE}:still_fields:{where}")
        box = item["vehicleBox"]
        if box is not None:
            require(box["x"] + box["width"] <= width and box["y"] + box["height"] <= height,
                    f"{CODE}:vehicle_box:{where}")
        plate_ids = [plate["plateId"] for plate in item["plates"]]
        require(plate_ids == sorted(set(plate_ids)), f"{CODE}:plate_order:{where}")
        for plate in item["plates"]:
            require(all(_inside(point, width, height) for point in plate["polygon"]),
                    f"{CODE}:polygon:{where}:{plate['plateId']}")
            left, top, right, bottom = polygon_rect(plate["polygon"])
            require(right > left and bottom > top, f"{CODE}:polygon_degenerate:{where}:{plate['plateId']}")
            require(LAYOUT_LINES[plate["layout"]] == plate["lineCount"], f"{CODE}:layout:{where}:{plate['plateId']}")
            usable, reason = text_usability(plate["text"])
            require(plate["textUsable"] == usable and plate["textUnusableReason"] == reason
                    and plate["maskedCharacters"] == masked_count(plate["text"]),
                    f"{CODE}:text_usability:{where}:{plate['plateId']}")
    paths = [(entry["path"], entry["reason"]) for entry in document["exclusions"]]
    require(paths == sorted(set(paths)), f"{CODE}:exclusion_order")
    return document


def plate(plate_id: str, polygon: list[list[float]], text: str | None, layout: str, *,
          illumination: str = "unknown", occluded: bool | None = None) -> dict[str, Any]:
    """A plate entry with its usability derived from the label (adapters never set usability by hand)."""
    usable, reason = text_usability(text)
    return {"plateId": plate_id, "polygon": polygon, "text": text, "lineCount": LAYOUT_LINES[layout],
            "layout": layout, "illumination": illumination, "occluded": occluded, "textUsable": usable,
            "textUnusableReason": reason, "maskedCharacters": masked_count(text)}


def box_polygon(x: float, y: float, width: float, height: float) -> list[list[float]]:
    return [[x, y], [x + width, y], [x + width, y + height], [x, y + height]]


# Geometry


def polygon_rect(polygon: list[list[float]]) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def _length(a: list[float], b: list[float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def plate_height_px(polygon: list[list[float]]) -> float:
    return (_length(polygon[0], polygon[3]) + _length(polygon[1], polygon[2])) / 2.0


def plate_width_px(polygon: list[list[float]]) -> float:
    return (_length(polygon[0], polygon[1]) + _length(polygon[3], polygon[2])) / 2.0


def char_height_px(polygon: list[list[float]], line_count: int | None) -> float:
    return plate_height_px(polygon) / (line_count or 1)


def skew_degrees(polygon: list[list[float]]) -> float:
    """The absolute angle of the top edge to the horizontal, in degrees (0 for a box-only label)."""
    dx, dy = polygon[1][0] - polygon[0][0], polygon[1][1] - polygon[0][1]
    return abs(math.degrees(math.atan2(dy, dx))) if (dx or dy) else 0.0


__all__ = ["S32Error", "SCHEMA", "box_polygon", "char_height_px", "plate", "plate_height_px", "plate_width_px",
           "polygon_rect", "skew_degrees", "text_matches", "text_usability", "truth_text", "validate_document"]
