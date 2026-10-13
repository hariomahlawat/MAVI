"""Per-crop plate analysis and the Track-level summary (ADR-013 implementation amendment 2026-10-13,
items 13–15; Stage 4 plan §2.5, §2.7).

One in-memory record per leased crop feeds both the ``PlatePredictions`` artefact and the completion
body (``predictions.py``), so the completion's facts equal the artefact's decisions by construction;
the platform re-checks them.

Rules, all deterministic:

* The models are configured to emit within the bounded profile: at most ``maxDetectionsPerCrop``
  proposals per crop and ``maxReadingsPerPlate`` readings per plate. More is a contract violation that
  fails the attempt (``OutputInvalid`` -> ``plate_output_invalid``); nothing is ever truncated, and every
  output inside the bounds is retained in the artefact.
* Detector boxes are ordered by score (descending), then ``x, y, width, height``; every one is recorded.
* The selected plates are the leading boxes whose score reaches ``detectorConfidenceFloor``, at most
  ``maxPlatesPerCrop``; ``plateIndex`` is their position.
* Readings are ordered by confidence (descending), then raw text (ordinal), with ``rank`` = position;
  every one is recorded. A plate is ``read`` when its rank-0
  reading reaches ``ocrConfidenceFloor`` — and then the readings at or above the floor are kept — and
  ``unreadable`` otherwise.
* A crop whose role the profile excludes is ``excluded``; a missing or mismatching crop is
  ``unavailable``; decode, detector or OCR faults and out-of-contract adapter output are
  ``abstained``. Only ``scored`` crops contribute plates.
* Summary policy ``plate-track-text-rank0`` / ``distinct-rank0-normalised-text``: one text per distinct
  ``ok`` normalised rank-0 reading of the Track's read plates, with its support count, its maximum
  confidence and its best plate (highest confidence, then lower evidence rank, then lower plate index);
  texts are ordered by normalised text.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable
from uuid import UUID

from mavi_vision.plates.contracts import (
    CROP_ABSTAINED,
    CROP_EXCLUDED,
    CROP_SCORED,
    CROP_UNAVAILABLE,
    CROP_UNAVAILABLE_REASONS,
    MAXIMUM_CROP_DIMENSION,
    PLATE_READ,
    PLATE_UNREADABLE,
    TRACK_ANALYSED,
    TRACK_UNAVAILABLE,
    TRACK_UNAVAILABLE_REASONS_BY_SEVERITY,
    LeaseObservation,
    LeaseTrack,
    is_raw_text,
    raw_line_count,
)
from mavi_vision.plates.inference import (
    CropDecodeError,
    PlateBox,
    PlateDetector,
    PlateRecogniser,
    Reading,
    VerifiedCrop,
    decode_crop,
)
from mavi_vision.plates.normalisation import OK, normalise
from mavi_vision.plates.parameters import PlateParameters

SUMMARY_POLICY_METHOD = "distinct-rank0-normalised-text"

# A crop reason's Track-level consequence when the Track has no scored crop.
_TRACK_REASON = {
    "evidence_integrity_failed": "evidence_integrity_failed",
    "evidence_missing": "evidence_missing",
    "decode_failed": "evidence_decode_failed",
    "detector_error": "plate_inference_failed",
    "ocr_error": "plate_inference_failed",
    "ocr_output_invalid": "plate_inference_failed",
}


class OutputInvalid(ValueError):
    """The worker's own result cannot form a valid artefact: a terminal attempt failure."""


@dataclass(frozen=True, slots=True)
class RankedReading:
    rank: int
    raw_text: str
    raw_line_count: int
    confidence: float


@dataclass(frozen=True, slots=True)
class PlateRecord:
    plate_index: int
    outcome: str
    readings: tuple[RankedReading, ...]


@dataclass(frozen=True, slots=True)
class DetectionRecord:
    box: tuple[int, int, int, int]
    score: float
    plate: PlateRecord | None


@dataclass(frozen=True, slots=True)
class CropRecord:
    observation_id: UUID
    role: str
    evidence_rank: int
    status: str
    reason: str | None
    width: int | None
    height: int | None
    detections: tuple[DetectionRecord, ...]

    def plates(self) -> Iterable[tuple[DetectionRecord, PlateRecord]]:
        if self.status != CROP_SCORED:
            return ()
        return tuple((detection, detection.plate) for detection in self.detections if detection.plate is not None)


@dataclass(frozen=True, slots=True)
class TrackText:
    normalised_text: str
    support_count: int
    max_confidence: float
    best_observation_id: UUID
    best_plate_index: int


@dataclass(frozen=True, slots=True)
class TrackRecord:
    track_id: UUID
    outcome: str
    reason: str | None
    crops: tuple[CropRecord, ...]
    texts: tuple[TrackText, ...]


def _probability(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1


def excluded_crop(observation: LeaseObservation) -> CropRecord:
    return CropRecord(observation.observation_id, observation.role, observation.evidence_rank, CROP_EXCLUDED, None, None, None, ())


def unavailable_crop(observation: LeaseObservation, reason: str) -> CropRecord:
    if reason not in CROP_UNAVAILABLE_REASONS:
        raise OutputInvalid("plate_crop_reason_invalid")
    return CropRecord(observation.observation_id, observation.role, observation.evidence_rank, CROP_UNAVAILABLE, reason, None, None, ())


def analyse_crop(
    observation: LeaseObservation,
    verified: VerifiedCrop,
    detector: PlateDetector,
    recogniser: PlateRecogniser,
    parameters: PlateParameters,
) -> CropRecord:
    """Decode once, detect, select, read. Faults abstain the whole crop; they are never negative facts.

    Raises ``OutputInvalid`` when a model emits more than its configured bound: a contract violation of
    the bounded profile, which fails the attempt rather than being truncated.
    """

    def abstained(reason: str, width: int | None = None, height: int | None = None,
                  detections: tuple[DetectionRecord, ...] = ()) -> CropRecord:
        return CropRecord(observation.observation_id, observation.role, observation.evidence_rank, CROP_ABSTAINED, reason,
                          width, height, detections)

    try:
        image = decode_crop(verified.content)
    except CropDecodeError:
        return abstained("decode_failed")
    width, height = image.size
    if not (1 <= width <= MAXIMUM_CROP_DIMENSION and 1 <= height <= MAXIMUM_CROP_DIMENSION):
        return abstained("decode_failed")

    try:
        boxes = list(detector.detect(image, verified))
    except Exception:  # noqa: BLE001 - any detector fault is the crop's abstention, by contract.
        return abstained("detector_error", width, height)
    for box in boxes:
        if not (isinstance(box, PlateBox) and _probability(box.score) and box.x >= 0 and box.y >= 0 and box.width >= 1
                and box.height >= 1 and box.x + box.width <= width and box.y + box.height <= height):
            return abstained("detector_error", width, height)
    if len(boxes) > parameters.max_detections_per_crop:
        raise OutputInvalid("plate_detector_output_exceeds_bound")
    recorded = sorted(boxes, key=lambda box: (-box.score, box.x, box.y, box.width, box.height))

    selected = 0
    for box in recorded:
        if box.score < parameters.detector_confidence_floor or selected >= parameters.max_plates_per_crop:
            break
        selected += 1

    detections: list[DetectionRecord] = []
    for index, box in enumerate(recorded):
        plate: PlateRecord | None = None
        if index < selected:
            region = image.crop((box.x, box.y, box.x + box.width, box.y + box.height))
            try:
                readings = list(recogniser.read(region, verified, box))
            except Exception:  # noqa: BLE001 - any OCR fault is the crop's abstention, by contract.
                return abstained("ocr_error", width, height, _without_plates(recorded))
            if not all(isinstance(item, Reading) and is_raw_text(item.raw_text) and _probability(item.confidence)
                       for item in readings):
                return abstained("ocr_output_invalid", width, height, _without_plates(recorded))
            if len(readings) > parameters.max_readings_per_plate:
                raise OutputInvalid("plate_recogniser_output_exceeds_bound")
            plate = _plate(index, readings, parameters)
        detections.append(DetectionRecord((box.x, box.y, box.width, box.height), float(box.score), plate))
    return CropRecord(observation.observation_id, observation.role, observation.evidence_rank, CROP_SCORED, None, width, height,
                      tuple(detections))


def _without_plates(recorded: list[PlateBox]) -> tuple[DetectionRecord, ...]:
    return tuple(DetectionRecord((box.x, box.y, box.width, box.height), float(box.score), None) for box in recorded)


def _plate(index: int, readings: list[Reading], parameters: PlateParameters) -> PlateRecord:
    ordered = sorted(readings, key=lambda item: (-item.confidence, item.raw_text))
    ranked = tuple(
        RankedReading(rank, item.raw_text, raw_line_count(item.raw_text), float(item.confidence)) for rank, item in enumerate(ordered)
    )
    outcome = PLATE_READ if ranked and ranked[0].confidence >= parameters.ocr_confidence_floor else PLATE_UNREADABLE
    return PlateRecord(index, outcome, ranked)


def kept_readings(plate: PlateRecord, parameters: PlateParameters) -> tuple[RankedReading, ...]:
    """The relational readings of a plate: the ranked prefix at or above the OCR floor, or none."""
    if plate.outcome != PLATE_READ:
        return ()
    return tuple(item for item in plate.readings if item.confidence >= parameters.ocr_confidence_floor)


def summarise_track(track: LeaseTrack, crops: tuple[CropRecord, ...]) -> TrackRecord:
    if [crop.observation_id for crop in crops] != [item.observation_id for item in track.observations]:
        raise OutputInvalid("plate_crop_coverage_invalid")
    if not any(crop.status == CROP_SCORED for crop in crops):
        caused = {_TRACK_REASON[crop.reason] for crop in crops if crop.reason is not None}
        reason = next((item for item in TRACK_UNAVAILABLE_REASONS_BY_SEVERITY if item in caused), "no_accepted_evidence")
        return TrackRecord(track.track_id, TRACK_UNAVAILABLE, reason, crops, ())

    groups: dict[str, list[tuple[float, int, int, UUID]]] = {}
    for crop in crops:
        for _, plate in crop.plates():
            if plate.outcome != PLATE_READ:
                continue
            first = plate.readings[0]
            result = normalise(first.raw_text)
            if result.outcome != OK or result.normalised is None:
                continue
            groups.setdefault(result.normalised, []).append(
                (first.confidence, crop.evidence_rank, plate.plate_index, crop.observation_id))
    texts = []
    for text in sorted(groups):
        members = groups[text]
        best = min(members, key=lambda item: (-item[0], item[1], item[2]))
        texts.append(TrackText(text, len(members), max(item[0] for item in members), best[3], best[2]))
    return TrackRecord(track.track_id, TRACK_ANALYSED, None, crops, tuple(texts))


__all__ = [
    "CropRecord",
    "DetectionRecord",
    "OutputInvalid",
    "PlateRecord",
    "RankedReading",
    "SUMMARY_POLICY_METHOD",
    "TrackRecord",
    "TrackText",
    "analyse_crop",
    "excluded_crop",
    "kept_readings",
    "summarise_track",
    "unavailable_crop",
]
