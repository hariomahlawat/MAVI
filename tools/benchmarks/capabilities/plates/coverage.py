"""Experiment E-B — Track evidence coverage (Stage 4 plan §3.1, §3.4.4).

Inputs are the harness's own evidence: labelled vehicle sequences processed by real MAVI (``prepare`` → ``execute``),
the deterministic ``benchmark-association-v1`` artefact (ADR-017 §6; predictions never consulted), the runs' T1
exports with their sealed evidence crops (every byte verified against the export's SHA-256 and size), and the
sequence plate truth. ``h_min`` comes from a bound E-A result.

For every ground-truth vehicle track with at least one text-usable plate frame:

* **oracle-readable** — some labelled source frame's native plate region has character height ≥ ``h_min`` and is
  read exactly by an instrument;
* **evidence-readable** — the track's associated MAVI Track has some evidence crop in which the plate region, mapped
  from that frame's labelled plate through the production crop geometry, is read exactly by an instrument.

C = R_ev / R_oracle, where R_oracle counts oracle-readable tracks and R_ev those of them that are evidence-readable.
"Read by an instrument" is the union over the pinned instruments (the plan's "an instrument"); per-instrument C is
reported beside it. A ground-truth track that association left without a MAVI Track (``unmatchedGt``,
``ambiguousGt``, ``mergedGt``, ``fragmentedGt``, ``unverifiedGt``) stays in the denominator and is not
evidence-readable, with its state recorded; tracks with no text-usable plate are counted separately and never enter
R_oracle. An observation whose frame carries no plate label is recorded (``no_plate_label_at_frame``), never read
against a guessed plate.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Callable

import numpy as np

from tools.benchmarks.capabilities.plates import measure, truth as truths
from tools.benchmarks.capabilities.plates.adequacy import SUPPORT_FLOOR, read
from tools.benchmarks.capabilities.plates.instruments import Instrument
from tools.benchmarks.core.identity import rational, require

from mavi_vision.common.analytical import NormalizedBoundingBox

CODE = "plate_coverage_invalid"
UNMATCHED_STATES = ("ambiguousGt", "mergedGt", "fragmentedGt", "unverifiedGt", "unmatchedGt")


@dataclass(frozen=True, slots=True)
class EvidenceObservation:
    role: str
    rank: int
    source_frame_number: int
    box: tuple[float, float, float, float]  # normalised x, y, width, height as exported
    load: Callable[[], bytes]  # the verified evidence JPEG bytes


@dataclass(frozen=True, slots=True)
class PlateFrame:
    frame_index: int
    plate: dict[str, Any]
    load_native: Callable[[], np.ndarray]


def _clamped(box: tuple[float, float, float, float]) -> NormalizedBoundingBox:
    x, y, w, h = (max(0.0, min(1.0, value)) for value in box)
    return NormalizedBoundingBox(x, y, min(w, 1.0 - x), min(h, 1.0 - y))


def _union(reads: dict[str, dict[str, Any]]) -> bool:
    return any(entry.get("agreement") is True for entry in reads.values())


def evaluate_track(frames: list[PlateFrame], observations: list[EvidenceObservation] | None,
                   frame_size: tuple[int, int], instruments: list[Instrument], h_min_px: float) -> dict[str, Any]:
    """Oracle and evidence readability of one ground-truth track (``observations`` None: no MAVI Track)."""
    usable = {frame.frame_index: frame for frame in frames if frame.plate["textUsable"]}
    oracle_frames = []
    oracle_by = {instrument.instrument_id: False for instrument in instruments}
    for index in sorted(usable):
        frame = usable[index]
        polygon = frame.plate["polygon"]
        height = truths.char_height_px(polygon, frame.plate["lineCount"])
        if height < h_min_px:
            continue
        image = frame.load_native()
        rect = measure.pixel_rect(*truths.polygon_rect(polygon), image.shape[1], image.shape[0])
        truth_text = truths.truth_text(frame.plate)
        reads = {i.instrument_id: read(i, measure.region(image, rect), truth_text) for i in instruments}
        for instrument_id, entry in reads.items():
            oracle_by[instrument_id] |= entry.get("agreement") is True
        oracle_frames.append({"frameIndex": index, "charHeightPx": height, "reads": reads})
    evidence = []
    evidence_by = {instrument.instrument_id: False for instrument in instruments}
    roles: set[str] = set()
    for observation in observations or []:
        frame = usable.get(observation.source_frame_number)
        entry: dict[str, Any] = {"role": observation.role, "rank": observation.rank,
                                 "sourceFrameNumber": observation.source_frame_number}
        if frame is None:
            entry["skipped"] = "no_plate_label_at_frame"
            evidence.append(entry)
            continue
        box = _clamped(observation.box)
        origin = measure.crop_origin(frame_size[0], frame_size[1], box)
        image = measure.decode_image(observation.load())
        encoded_size = (image.shape[1], image.shape[0])
        mapped, share = measure.map_into_crop(truths.polygon_rect(frame.plate["polygon"]), origin, encoded_size)
        entry["plateInsideShare"] = share
        entry["charHeightPx"] = truths.char_height_px(frame.plate["polygon"], frame.plate["lineCount"]) * (
            encoded_size[1] / max(1, origin[3] - origin[1]))
        if share <= 0:
            entry["skipped"] = "plate_outside_crop"
            evidence.append(entry)
            continue
        region = measure.region(image, measure.pixel_rect(*mapped, *encoded_size))
        truth_text = truths.truth_text(frame.plate)
        entry["reads"] = {i.instrument_id: read(i, region, truth_text) for i in instruments}
        for instrument_id, result in entry["reads"].items():
            if result.get("agreement") is True:
                evidence_by[instrument_id] = True
                roles.add(observation.role)
        evidence.append(entry)
    return {"oracleReadable": any(oracle_by.values()), "oracleReadableBy": oracle_by,
            "evidenceReadable": any(evidence_by.values()), "evidenceReadableBy": evidence_by,
            "rolesPreservingReading": sorted(roles), "oracleFrames": oracle_frames, "evidence": evidence}


def _ratio(numerator: int, denominator: int) -> dict[str, Any]:
    return {"numerator": numerator, "denominator": denominator,
            "value": None if denominator == 0 else rational(Fraction(numerator, denominator)),
            "sufficient": denominator >= SUPPORT_FLOOR}


def summarise(tracks: list[dict[str, Any]], instrument_ids: list[str]) -> dict[str, Any]:
    """C over the evaluated tracks (each ``{gtTrackId, state, usablePlate, result}``)."""
    population = [track for track in tracks if track["usablePlate"]]
    oracle = [track for track in population if track["result"]["oracleReadable"]]
    evidence = [track for track in oracle if track["result"]["evidenceReadable"]]
    per_instrument = {}
    for instrument_id in instrument_ids:
        o = [t for t in population if t["result"]["oracleReadableBy"][instrument_id]]
        e = [t for t in o if t["result"]["evidenceReadableBy"][instrument_id]]
        per_instrument[instrument_id] = _ratio(len(e), len(o))
    by_state: dict[str, int] = {}
    for track in oracle:
        if not track["result"]["evidenceReadable"]:
            by_state[track["state"]] = by_state.get(track["state"], 0) + 1
    by_role: dict[str, int] = {}
    for track in evidence:
        for role in track["result"]["rolesPreservingReading"]:
            by_role[role] = by_role.get(role, 0) + 1
    errors = {instrument_id: sum(1 for track in population for frame in track["result"]["oracleFrames"]
                                 if "error" in frame["reads"][instrument_id])
              + sum(1 for track in population for entry in track["result"]["evidence"]
                    if "error" in entry.get("reads", {}).get(instrument_id, {}))
              for instrument_id in instrument_ids}
    return {"gtTracks": len(tracks), "withoutUsablePlate": len(tracks) - len(population),
            "rOracle": len(oracle), "rEvidence": len(evidence), "coverage": _ratio(len(evidence), len(oracle)),
            "coverageByInstrument": per_instrument, "oracleNotEvidenceByState": dict(sorted(by_state.items())),
            "evidenceReadableTracksByRole": dict(sorted(by_role.items())), "instrumentErrors": errors,
            "matchedOracleNotEvidence": by_state.get("matched", 0)}


def association_states(entry: dict[str, Any]) -> dict[str, tuple[str, str | None]]:
    """``gtTrackId → (state, maviTrackId | None)`` of one ``benchmark-association-v1`` sequence entry."""
    states: dict[str, tuple[str, str | None]] = {}
    for pair in entry["pairs"]:
        states[pair["gtTrackId"]] = ("matched", pair["maviTrackId"])
    for state in (*UNMATCHED_STATES, "ignoredGt"):
        for item in entry.get(state, []):
            require(item["gtTrackId"] not in states, f"{CODE}:gt_state_duplicate:{item['gtTrackId']}")
            states[item["gtTrackId"]] = (state, None)
    return states
