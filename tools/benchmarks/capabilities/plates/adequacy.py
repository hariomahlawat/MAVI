"""Experiment E-A — encoding loss (Stage 4 plan §3.1, §3.4; protocol ``docs/qualification/stage4/adequacy-protocol.md``).

For every ground-truth plate: associate it with its vehicle box; cut the **production** tight vehicle crop; encode it
with the **production** encoder at the Representative (64 KiB) and supplemental (160 KiB) caps; map the plate into each
encoded crop; measure pixel size, blur and encoder reductions; and read the plate region from the native image and
from each encoded crop with every pinned instrument.

``measure_item`` produces the rows; ``summarise`` is a pure function of rows (exact rationals throughout) that derives
``h_min`` and the encoding loss ΔEM per instrument and cap, with strata. Nothing is dropped silently: every plate is a
row, and every population names what it excludes and why.

**Vehicle association (still images).** A plate's candidate vehicle boxes are the dataset's own box when it has one.
A candidate qualifies when it contains at least ``CONTAINMENT`` of the plate rectangle's area; the smallest-area
qualifying box wins (ties: smaller ``y``, then ``x``). No qualifying box → ``unassociated`` (counted; such a plate
cannot be put through the crop and is excluded from ΔEM with that reason).

**h_min (§3.4.1).** Bins of native character height with lower bounds ``CHAR_HEIGHT_BINS`` px. The reference
instrument is the one with the higher native EM in the top bin (ties: higher overall native EM, then instrument id).
``h_min`` is the lower bound of the smallest bin ``b`` such that ``b`` and every larger bin have support ≥
``SUPPORT_FLOOR`` and reference EM ≥ ``H_MIN_RATIO`` × the top bin's EM. A top bin below the support floor, or with
EM 0, leaves ``h_min`` NOT MEASURED.

**ΔEM (§3.4.2).** For each instrument and cap, over text-usable, associated plates with native character height ≥
``h_min``: ΔEM = 100 × (native exact − encoded exact) / n percentage points. A plate whose role was not admitted by
the encoder, or that lies outside the crop, counts as not read exactly in that role (the loss is real). n below the
support floor → insufficient.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Callable, Iterable

import numpy as np

from tools.benchmarks.capabilities.plates import measure, truth as truths
from tools.benchmarks.capabilities.plates.instruments import Instrument
from tools.benchmarks.core.identity import rational, require
from tools.benchmarks.plates.normalisation import normalise

CONTAINMENT = Fraction(9, 10)
CHAR_HEIGHT_BINS = (0, 10, 15, 20, 32)
SUPPORT_FLOOR = 50
H_MIN_RATIO = Fraction(9, 10)
OBLIQUE_DEGREES = 15.0
ROLES = ("representative", "supplemental")
CODE = "plate_adequacy_invalid"


# Association


def associate_vehicle(plate_rect: tuple[float, float, float, float],
                      candidates: Iterable[dict[str, float]]) -> dict[str, float] | None:
    left, top, right, bottom = plate_rect
    area = (right - left) * (bottom - top)
    qualifying = []
    for box in candidates:
        inside_w = max(0.0, min(right, box["x"] + box["width"]) - max(left, box["x"]))
        inside_h = max(0.0, min(bottom, box["y"] + box["height"]) - max(top, box["y"]))
        if area > 0 and Fraction(inside_w * inside_h) / Fraction(area) >= CONTAINMENT:
            qualifying.append(box)
    if not qualifying:
        return None
    return min(qualifying, key=lambda box: (box["width"] * box["height"], box["y"], box["x"]))


# Reading


def read(instrument: Instrument, region: np.ndarray, truth_text: str | None) -> dict[str, Any]:
    """One instrument read, recorded with its raw text, normalisation and exactness against the truth."""
    if region.size == 0:
        return {"skipped": "empty_region"}
    try:
        reading = instrument.read(region)
    except Exception as exc:  # noqa: BLE001 - an instrument failure is evidence, recorded and never hidden
        return {"error": f"instrument_error:{type(exc).__name__}"}
    result = normalise(reading.text)
    exact = truth_text is not None and result.normalised == truth_text
    return {"raw": reading.text, "normalised": result.normalised, "normalisationOutcome": result.outcome,
            "confidence": reading.confidence, "exact": exact,
            "cer": None if truth_text is None else measure.cer(result.normalised, truth_text)}


# Rows


def measure_item(item: dict[str, Any], image: np.ndarray, instruments: list[Instrument],
                 vehicle_candidates: list[dict[str, float]] | None = None) -> list[dict[str, Any]]:
    """One row per plate of ``item`` (the decoded source image). The dataset's own vehicle box is the only candidate
    when it has one; otherwise ``vehicle_candidates`` (phase-1 detector boxes, pixels) are."""
    height, width = image.shape[0], image.shape[1]
    require((width, height) == (item["frameSize"]["width"], item["frameSize"]["height"]),
            f"{CODE}:frame_size:{item['itemId']}")
    candidates = [item["vehicleBox"]] if item["vehicleBox"] is not None else list(vehicle_candidates or [])
    rows = []
    for plate in item["plates"]:
        polygon = plate["polygon"]
        plate_rect = truths.polygon_rect(polygon)
        truth_text = truths.truth_text(plate) if plate["textUsable"] else None
        native_rect = measure.pixel_rect(*plate_rect, width, height)
        native_region = measure.region(image, native_rect)
        row: dict[str, Any] = {
            "itemId": item["itemId"], "plateId": plate["plateId"], "vehicleClass": item["vehicleClass"],
            "layout": plate["layout"], "illumination": plate["illumination"], "occluded": plate["occluded"],
            "textUsable": plate["textUsable"], "truthText": truth_text,
            "native": {"charHeightPx": truths.char_height_px(polygon, plate["lineCount"]),
                       "widthPx": truths.plate_width_px(polygon), "skewDegrees": truths.skew_degrees(polygon),
                       "blur": measure.laplacian_variance(native_region)},
            "reads": {instrument.instrument_id: {"native": read(instrument, native_region, truth_text)}
                      for instrument in instruments},
        }
        vehicle = associate_vehicle(plate_rect, candidates)
        row["association"] = "unassociated" if vehicle is None else (
            "dataset-vehicle-box" if item["vehicleBox"] is not None else "detector-vehicle-box")
        row["roles"] = {}
        if vehicle is not None:
            box = measure.normalised_box(vehicle, width, height)
            origin = measure.crop_origin(width, height, box)
            crop = measure.vehicle_crop(image, box)
            require(crop.shape[:2] == (origin[3] - origin[1], origin[2] - origin[0]), f"{CODE}:crop_origin")
            for role in ROLES:
                row["roles"][role], regions = _role(crop, origin, plate_rect, plate, role)
                for instrument in instruments:
                    row["reads"][instrument.instrument_id][role] = (
                        {"skipped": regions["skipped"]} if "skipped" in regions
                        else read(instrument, regions["region"], truth_text))
        rows.append(row)
    return rows


def _role(crop: np.ndarray, origin: tuple[int, int, int, int], plate_rect: tuple[float, float, float, float],
          plate: dict[str, Any], role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    encoded = measure.encode(crop, role)
    crop_h, crop_w = crop.shape[0], crop.shape[1]
    if encoded is None:
        return {"admitted": False, "cropWidth": crop_w, "cropHeight": crop_h}, {"skipped": "not_admitted"}
    decoded = measure.decode_image(encoded.payload)
    mapped, share = measure.map_into_crop(plate_rect, origin, (encoded.width, encoded.height))
    scale = encoded.height / crop_h
    entry = {"admitted": True, "cropWidth": crop_w, "cropHeight": crop_h, "encodedWidth": encoded.width,
             "encodedHeight": encoded.height, "quality": encoded.quality, "ladderStep": encoded.ladder_step,
             "bytes": encoded.size_bytes, "scale": scale, "plateInsideShare": share,
             "charHeightPx": truths.char_height_px(plate["polygon"], plate["lineCount"]) * scale,
             "widthPx": truths.plate_width_px(plate["polygon"]) * (encoded.width / crop_w)}
    if share <= 0:
        entry["blur"] = None
        return entry, {"skipped": "plate_outside_crop"}
    rect = measure.pixel_rect(*mapped, encoded.width, encoded.height)
    region = measure.region(decoded, rect)
    entry["blur"] = measure.laplacian_variance(region)
    return entry, {"region": region}


# Summary (pure)


def _exact(entry: dict[str, Any] | None) -> bool:
    return bool(entry) and entry.get("exact") is True


def instrument_failed(rows: list[dict[str, Any]], instrument_id: str) -> int:
    return sum(1 for row in rows for entry in row["reads"][instrument_id].values() if "error" in entry)


def char_bin(height: float) -> int:
    return max(bound for bound in CHAR_HEIGHT_BINS if height >= bound)


def _rate(k: int, n: int) -> dict[str, Any] | None:
    return None if n == 0 else {"exact": k, "n": n, "rate": rational(Fraction(k, n))}


def h_min(rows: list[dict[str, Any]], instrument_ids: list[str]) -> dict[str, Any]:
    """The §3.4.1 derivation: per-instrument native EM by bin, the reference instrument and ``h_min`` (or null)."""
    population = [row for row in rows if row["textUsable"]]
    table: dict[str, dict[int, tuple[int, int]]] = {}
    for instrument_id in instrument_ids:
        counts = {bound: [0, 0] for bound in CHAR_HEIGHT_BINS}
        for row in population:
            bound = char_bin(row["native"]["charHeightPx"])
            counts[bound][1] += 1
            counts[bound][0] += _exact(row["reads"][instrument_id]["native"])
        table[instrument_id] = {bound: (k, n) for bound, (k, n) in counts.items()}
    top = CHAR_HEIGHT_BINS[-1]

    def top_rate(instrument_id: str) -> Fraction:
        k, n = table[instrument_id][top]
        return Fraction(k, n) if n else Fraction(-1)

    def overall(instrument_id: str) -> Fraction:
        k = sum(pair[0] for pair in table[instrument_id].values())
        n = sum(pair[1] for pair in table[instrument_id].values())
        return Fraction(k, n) if n else Fraction(-1)

    reference = sorted(instrument_ids, key=lambda i: (-top_rate(i), -overall(i), i))[0] if instrument_ids else None
    bins = {instrument_id: [{"lowerPx": bound, **(_rate(*table[instrument_id][bound]) or {"exact": 0, "n": 0})}
                            for bound in CHAR_HEIGHT_BINS] for instrument_id in instrument_ids}
    value, reason = None, None
    if reference is None:
        reason = "no_instrument"
    else:
        k_top, n_top = table[reference][top]
        if n_top < SUPPORT_FLOOR:
            reason = "top_bin_insufficient"
        elif k_top == 0:
            reason = "top_bin_zero"
        else:
            target = H_MIN_RATIO * Fraction(k_top, n_top)
            for bound in reversed(CHAR_HEIGHT_BINS):
                k, n = table[reference][bound]
                if n < SUPPORT_FLOOR or Fraction(k, n) < target:
                    break
                value = bound
    return {"referenceInstrument": reference, "hMinPx": value, "notMeasuredReason": reason, "bins": bins,
            "ratio": rational(H_MIN_RATIO), "supportFloor": SUPPORT_FLOOR}


def _delta(population: list[dict[str, Any]], instrument_id: str, role: str) -> dict[str, Any]:
    n = len(population)
    native = sum(_exact(row["reads"][instrument_id]["native"]) for row in population)
    encoded = sum(_exact(row["reads"][instrument_id].get(role)) for row in population)
    delta = None if n == 0 else Fraction(100 * (native - encoded), n)
    # Plates of one sequence are correlated: the number of distinct sequences (vehicles; an image for stills) is
    # reported beside n (protocol §5, stated limitation).
    sources = len({row["itemId"].split("/", 1)[0] for row in population})
    return {"n": n, "distinctSources": sources, "nativeExact": native, "encodedExact": encoded,
            "deltaEmPp": None if delta is None else {"numerator": delta.numerator, "denominator": delta.denominator},
            "sufficient": n >= SUPPORT_FLOOR}


def _tertiles(values: list[float]) -> tuple[float, float] | None:
    if len(values) < 3:
        return None
    ordered = sorted(values)
    return ordered[len(ordered) // 3], ordered[(2 * len(ordered)) // 3]


def _strata(population: list[dict[str, Any]]) -> dict[str, Callable[[dict[str, Any]], str]]:
    blurs = [row["native"]["blur"] for row in population if row["native"]["blur"] is not None]
    cuts = _tertiles(blurs)

    def blur(row: dict[str, Any]) -> str:
        value = row["native"]["blur"]
        if value is None or cuts is None:
            return "unavailable"
        return "low" if value < cuts[0] else ("mid" if value < cuts[1] else "high")

    skew_available = any(row["native"]["skewDegrees"] > 0 for row in population)
    return {
        "vehicleClass": lambda row: row["vehicleClass"],
        "layout": lambda row: row["layout"],
        "illumination": lambda row: row["illumination"],
        "occluded": lambda row: {True: "occluded", False: "visible", None: "unknown"}[row["occluded"]],
        "charHeightBin": lambda row: f">={char_bin(row['native']['charHeightPx'])}px",
        "blurTertile": blur,
        "oblique": (lambda row: "oblique" if row["native"]["skewDegrees"] > OBLIQUE_DEGREES else "frontal")
        if skew_available else (lambda row: "unavailable-box-only-labels"),
    }


def summarise(rows: list[dict[str, Any]], instrument_ids: list[str]) -> dict[str, Any]:
    counts = {"plates": len(rows), "textUsable": sum(row["textUsable"] for row in rows),
              "textUnusable": sum(not row["textUsable"] for row in rows),
              "unassociated": sum(row["textUsable"] and row["association"] == "unassociated" for row in rows)}
    failures = {instrument_id: instrument_failed(rows, instrument_id) for instrument_id in instrument_ids}
    derivation = h_min(rows, instrument_ids)
    summary: dict[str, Any] = {"counts": counts, "instrumentErrors": failures, "hMin": derivation}
    threshold = derivation["hMinPx"]
    if threshold is None:
        summary["encodingLoss"] = None
        return summary
    eligible = [row for row in rows if row["textUsable"] and row["native"]["charHeightPx"] >= threshold]
    population = [row for row in eligible if row["association"] != "unassociated"]
    summary["population"] = {"atOrAboveHMin": len(eligible), "associated": len(population),
                             "excludedUnassociated": len(eligible) - len(population)}
    strata = _strata(population)
    loss: dict[str, Any] = {}
    for instrument_id in instrument_ids:
        loss[instrument_id] = {}
        for role in ROLES:
            by_stratum = {}
            for name, key in strata.items():
                groups: dict[str, list[dict[str, Any]]] = {}
                for row in population:
                    groups.setdefault(key(row), []).append(row)
                by_stratum[name] = {value: _delta(groups[value], instrument_id, role) for value in sorted(groups)}
            loss[instrument_id][role] = {"overall": _delta(population, instrument_id, role), "strata": by_stratum}
    summary["encodingLoss"] = loss
    return summary
