"""Stage-4 model-selection evaluators A–D (plan §4.4), built on PR-3's merged plate rules.

These are the evaluators plan §7 assigned to PR-1 and PR-1 omitted. This module repairs that (register: *Correction and
repair record*). The owner decisions it encodes are written in
`docs/qualification/stage4/plate-selection-decision-record-2026-10-14.md`. It reads **no** dataset by itself: every
function takes in-memory ground truth and candidate outputs.

* **Product rules, not re-implementations.**
  - Track outcomes come from ``mavi_vision.plates.pipeline`` (``analyse_crop``, ``summarise_track``): the 2/1/3 bounds, proposal ordering, detector floor, reading order, ``Read``/``Unreadable``, abstention reasons and the ``plate-track-text-rank0`` summary.
  - Text is normalised only by the frozen ``mavi-plate-normalisation-v1``.
  - Confidence is reading-level.
* **Contract violations are hard FAILs** (owner item 11). A detector emitting more than the bound, a recogniser over its bound, or malformed output that PR-3 treats as an attempt failure makes the whole evaluation ``CONTRACT_FAIL``. The exact failure is kept; nothing is scored through it, truncated or treated as one bad Track.
* **Ranking floor enforced in code** (D6, owner item 15). D, top-K inputs, the gates and the bootstrap accept only runs and plate records on the ranking profile (2/1/3 bounds, OCR floor 0, no excluded roles). The diagnostic floors {0.3, 0.5, 0.7} exist only behind ``diagnostic_evaluate_at_floor`` and ``diagnostic_plate_record``, whose outputs the ranking path refuses.
* **Candidate silence scores zero** (owner item 1).
  - On a valid closed population, a composition that returns nothing has exact recall 0, contains recall 0 and contains precision 0, so its D-score is defined.
  - ``INSUFFICIENT_EVIDENCE`` is reserved for corpus deficiency: no queryable plate-bearing Track, no positive Track–query pair, or no contains query.
* **Baseline gate** (N2 revised): one hard gate against the frozen single baseline composition PD_BASE + OC5 resolved in two stages: the eligible detector universe, OC5 identity, Layer-A gates and ranking rule are frozen at PROTOCOL_FROZEN; ``resolve_baseline`` then derives and seals PD_BASE after Layer A and before any D data. Detector-matched Tesseract runs are diagnostic only (``diagnostic_ocr_uplift``).
* **Superiority** (owner item 2): A is ``superior`` to B iff
  - the observed ΔD = D_A − D_B ≥ MPID 0.04 (exact rationals);
  - the paired hierarchical 95 % interval for ΔD excludes zero in A's favour;
  - the cluster count meets the frozen ``required_clusters`` (≥ 60).
* **Exact arithmetic.** D terms, ΔD and every bootstrap replicate are exact ``Fraction`` values. No epsilon is used.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from fractions import Fraction
from uuid import UUID

from mavi_vision.plates.contracts import (
    CROP_ABSTAINED,
    CROP_SCORED,
    MAXIMUM_DETECTIONS_PER_CROP,
    MAXIMUM_PLATES_PER_CROP,
    MAXIMUM_READINGS_PER_PLATE,
    PLATE_READ,
    PLATE_UNREADABLE,
    TRACK_ANALYSED,
    LeaseObservation,
    LeaseTrack,
)
from mavi_vision.plates.inference import PlateDetector, PlateRecogniser, VerifiedCrop
from mavi_vision.plates.normalisation import OK, normalise
from mavi_vision.plates.parameters import PlateParameters
from mavi_vision.plates.pipeline import CropRecord, OutputInvalid, TrackRecord, analyse_crop, summarise_track

from tools.benchmarks.capabilities.plates.queries import CONTAINS, EXACT, QuerySet, matches, queryable

# Decision record: docs/qualification/stage4/plate-selection-decision-record-2026-10-14.md
PLAN_COVERAGE_THRESHOLD = Fraction(95, 100)   # plan §4.4 A (plan-derived)
RANKING_OCR_CONFIDENCE_FLOOR = 0.0            # owner D6
DIAGNOSTIC_OCR_FLOORS = (0.3, 0.5, 0.7)       # owner D6: diagnostic only
MPID = Fraction(4, 100)                       # owner D7a (2026-10-14)
ABSOLUTE_MINIMUM_CLUSTERS = 60                # owner D7b / P-80: absolute floor only, never "adequately powered"
CONSISTENT_WRONG_LIMIT = Fraction(2, 100)     # plan §4.5, owner N3
SUPPORT_FLOOR = 50                            # owner N3; strata below it are INSUFFICIENT_EVIDENCE
P14_TOLERANCE = Fraction(2, 100)              # owner N5
ECE_BINS = 10                                 # proposed frozen protocol value (decision record §3): equal-mass bins
CLUSTER_UNIT = "physical-capture-site"        # owner item 4 / C2

PASS, FAIL, INSUFFICIENT = "PASS", "FAIL", "INSUFFICIENT_EVIDENCE"
MEASURED, CONTRACT_FAIL = "MEASURED", "CONTRACT_FAIL"
NO_PLATE = "<no-plate>"            # real GT vehicle displaying no plate: truth = no text
UNREADABLE = "<unreadable>"        # real GT vehicle, text not establishable by the frozen human rule
NO_GT_VEHICLE = "<no-gt-vehicle>"  # MAVI Track matching no GT vehicle in the closed population: a false Track


def ranking_parameters(detector_confidence_floor: float) -> PlateParameters:
    """The only parameters the ranking path accepts: 2/1/3 bounds, OCR floor 0, the candidate's pinned detector floor."""
    return PlateParameters(MAXIMUM_DETECTIONS_PER_CROP, MAXIMUM_PLATES_PER_CROP, MAXIMUM_READINGS_PER_PLATE,
                           float(detector_confidence_floor), RANKING_OCR_CONFIDENCE_FLOOR, frozenset(), None)


def is_ranking_profile(parameters: PlateParameters) -> bool:
    return (parameters.max_detections_per_crop == MAXIMUM_DETECTIONS_PER_CROP
            and parameters.max_plates_per_crop == MAXIMUM_PLATES_PER_CROP
            and parameters.max_readings_per_plate == MAXIMUM_READINGS_PER_PLATE
            and parameters.ocr_confidence_floor == RANKING_OCR_CONFIDENCE_FLOOR
            and not parameters.excluded_roles)


def normalised_truth(raw: str) -> str | None:
    result = normalise(raw)
    return result.normalised if result.outcome == OK else None


def _ratio(numerator: int, denominator: int) -> Fraction | None:
    return Fraction(numerator, denominator) if denominator else None


# ---------------------------------------------------------------------------------------------- running PR-3 rules


@dataclass(frozen=True, slots=True)
class EvidenceCrop:
    observation_id: UUID
    role: str
    evidence_rank: int
    sha256: str
    content: bytes


@dataclass(frozen=True, slots=True)
class TrackRun:
    """A Track's PR-3 outcome under ``parameters``, or the exact contract violation (kept for audit, never scored)."""

    record: TrackRecord | None
    contract_violation: str | None
    parameters: PlateParameters


def lease_observation(observation_id: UUID, role: str, evidence_rank: int, size_bytes: int, sha256: str
                      ) -> LeaseObservation:
    return LeaseObservation.model_validate({"observationId": observation_id, "role": role,
                                            "evidenceRank": evidence_rank, "sizeBytes": size_bytes, "sha256": sha256})


def lease_track(track_id: UUID, observations: tuple[LeaseObservation, ...]) -> LeaseTrack:
    return LeaseTrack.model_validate({"trackId": track_id, "objectClass": "vehicle", "observations": observations})


def run_track(track_id: UUID, crops: Sequence[EvidenceCrop], detector: PlateDetector, recogniser: PlateRecogniser,
              parameters: PlateParameters) -> TrackRun:
    observations = tuple(lease_observation(c.observation_id, c.role, c.evidence_rank, len(c.content), c.sha256)
                         for c in crops)
    track = lease_track(track_id, observations)
    records = []
    try:
        for crop, observation in zip(crops, observations):
            verified = VerifiedCrop(str(crop.observation_id), crop.role, crop.evidence_rank, crop.sha256, crop.content)
            records.append(analyse_crop(observation, verified, detector, recogniser, parameters))
    except OutputInvalid as exc:
        return TrackRun(None, str(exc), parameters)
    return TrackRun(summarise_track(track, tuple(records)), None, parameters)


def _refloor(record: TrackRecord, floor: float) -> TrackRecord:
    crops = []
    for crop in record.crops:
        detections = []
        for detection in crop.detections:
            plate = detection.plate
            if plate is not None:
                outcome = PLATE_READ if plate.readings and plate.readings[0].confidence >= floor else PLATE_UNREADABLE
                plate = replace(plate, outcome=outcome)
            detections.append(replace(detection, plate=plate))
        crops.append(replace(crop, detections=tuple(detections)))
    observations = tuple(lease_observation(c.observation_id, c.role, c.evidence_rank, 1, "0" * 64) for c in crops)
    return summarise_track(lease_track(record.track_id, observations), tuple(crops))


# ---------------------------------------------------------------------------------------------- A


def _polygon_area(points: Sequence[tuple[float, float]]) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, list(points[1:]) + [points[0]]))) / 2


def _clip(points: list[tuple[float, float]], inside: Callable, cut: Callable) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for index, current in enumerate(points):
        previous = points[index - 1]
        if inside(current):
            if not inside(previous):
                out.append(cut(previous, current))
            out.append(current)
        elif inside(previous):
            out.append(cut(previous, current))
    return out


def coverage(polygon: Sequence[tuple[float, float]], box: tuple[float, float, float, float]) -> float:
    """Share of the GT polygon's area inside the axis-aligned box ``(x1, y1, x2, y2)`` (Sutherland–Hodgman)."""
    area = _polygon_area(polygon)
    if area <= 0:
        return 0.0
    x1, y1, x2, y2 = box
    points = [(float(x), float(y)) for x, y in polygon]

    def at_x(xv):
        return lambda p, q: (xv, p[1] + (q[1] - p[1]) * (xv - p[0]) / (q[0] - p[0]))

    def at_y(yv):
        return lambda p, q: (p[0] + (q[0] - p[0]) * (yv - p[1]) / (q[1] - p[1]), yv)

    for inside, cut in ((lambda p: p[0] >= x1, at_x(x1)), (lambda p: p[0] <= x2, at_x(x2)),
                        (lambda p: p[1] >= y1, at_y(y1)), (lambda p: p[1] <= y2, at_y(y2))):
        points = _clip(points, inside, cut)
        if not points:
            return 0.0
    return min(1.0, _polygon_area(points) / area)


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    w = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - w * h
    return w * h / union if union > 0 else 0.0


@dataclass(frozen=True, slots=True)
class DetectionItem:
    """One GT vehicle crop: GT plate polygons and the detector's proposals ``(x, y, w, h, score)`` as emitted."""

    crop_id: str
    plates: tuple[tuple[tuple[float, float], ...], ...]
    proposals: tuple[tuple[int, int, int, int, float], ...]
    stratum: str | None = None


def detection_item_from_crop(crop_id: str, plates, crop: CropRecord, stratum: str | None = None) -> DetectionItem:
    proposals = tuple((*d.box, d.score) for d in crop.detections) if crop.status in (CROP_SCORED, CROP_ABSTAINED) else ()
    return DetectionItem(crop_id, tuple(plates), proposals, stratum)


@dataclass(frozen=True, slots=True)
class DetectionResult:
    outcome: str                      # MEASURED | CONTRACT_FAIL
    contract_violations: tuple[str, ...]
    plates: int
    covered: int
    recall: Fraction | None
    false_plates_per_crop: Fraction | None
    ap50: float | None
    below_floor_proposals: int
    per_stratum: dict = field(default_factory=dict)


def evaluate_detection(items: Iterable[DetectionItem], detector_floor: float) -> DetectionResult:
    """A. More than ``MAXIMUM_DETECTIONS_PER_CROP`` proposals in any crop is a contract FAIL for the evaluation
    (owner item 14): nothing is scored, truncated or re-selected. Proposals below the pinned detector floor are not
    counted (PR-3 cannot accept them) and are reported."""
    items = list(items)
    violations = tuple(f"plate_detector_output_exceeds_bound:{i.crop_id}" for i in items
                       if len(i.proposals) > MAXIMUM_DETECTIONS_PER_CROP)
    if violations:
        return DetectionResult(CONTRACT_FAIL, violations, 0, 0, None, None, None, 0, {})
    plates = covered = false = below = 0
    strata: dict[str, list[int]] = {}
    scored: list[tuple[float, str, int, bool]] = []
    for item in items:
        kept = [p for p in item.proposals if p[4] >= detector_floor]
        below += len(item.proposals) - len(kept)
        boxes = [(x, y, x + w, y + h) for x, y, w, h, _ in kept]
        hit = sum(1 for polygon in item.plates
                  if any(Fraction(coverage(polygon, b)) >= PLAN_COVERAGE_THRESHOLD for b in boxes))
        plates += len(item.plates)
        covered += hit
        if item.stratum is not None:
            bucket = strata.setdefault(item.stratum, [0, 0])
            bucket[0] += len(item.plates)
            bucket[1] += hit
        false += sum(1 for b in boxes if not any(Fraction(coverage(p, b)) >= PLAN_COVERAGE_THRESHOLD for p in item.plates))
        gt_boxes = [(min(x for x, _ in p), min(y for _, y in p), max(x for x, _ in p), max(y for _, y in p))
                    for p in item.plates]
        taken: set[int] = set()
        for index in sorted(range(len(boxes)), key=lambda i: (-kept[i][4], i)):
            best, best_iou = None, 0.5
            for g, gt in enumerate(gt_boxes):
                value = _iou(boxes[index], gt)
                if g not in taken and value >= best_iou:
                    best, best_iou = g, value
            if best is not None:
                taken.add(best)
            scored.append((kept[index][4], item.crop_id, index, best is not None))
    ap = None
    if plates:
        scored.sort(key=lambda s: (-s[0], s[1], s[2]))
        tp, points = 0, []
        for rank, (_, _, _, hit) in enumerate(scored, 1):
            tp += hit
            points.append((tp / plates, tp / rank))
        ap, previous_recall = 0.0, 0.0
        for i, (recall, _) in enumerate(points):
            ap += (recall - previous_recall) * max(p for _, p in points[i:])
            previous_recall = recall
    per_stratum = {name: {"support": s, "recall": _ratio(c, s), "status": MEASURED if s >= SUPPORT_FLOOR else INSUFFICIENT}
                   for name, (s, c) in sorted(strata.items())}
    return DetectionResult(MEASURED, (), plates, covered, _ratio(covered, plates), _ratio(false, len(items)), ap, below,
                           per_stratum)


# ---------------------------------------------------------------------------------------------- B and C


def cer(predicted: str, truth: str) -> float:
    previous = list(range(len(truth) + 1))
    for i, a in enumerate(predicted, 1):
        current = [i]
        for j, b in enumerate(truth, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1] / max(len(truth), 1)


@dataclass(frozen=True, slots=True)
class RankingPlate:
    """A PR-3 ``PlateRecord`` produced on the ranking profile (OCR floor 0), or the contract violation."""

    plate: object | None
    contract_violation: str | None = None


@dataclass(frozen=True, slots=True)
class DiagnosticPlate:
    """DIAGNOSTIC ONLY: a plate record at a diagnostic floor. Refused by every ranking path."""

    plate: object | None
    floor: float


def _plate_record(readings, parameters: PlateParameters):
    from mavi_vision.plates.contracts import has_strict_rank_order, is_raw_text
    from mavi_vision.plates.pipeline import _plate  # the product's own rule, not a re-implementation

    readings = list(readings)
    if len(readings) > parameters.max_readings_per_plate:
        raise OutputInvalid("plate_recogniser_output_exceeds_bound")
    if not all(is_raw_text(r.raw_text) and isinstance(r.confidence, (int, float)) and not isinstance(r.confidence, bool)
               and math.isfinite(r.confidence) and 0 <= r.confidence <= 1 for r in readings) \
            or not has_strict_rank_order(readings):
        return None  # PR-3 crop abstention ocr_output_invalid: proposals kept, readings not (ADR-013 item 15)
    return _plate(0, readings, parameters)


def ranking_plate_record(readings) -> RankingPlate:
    """B on GT plate crops, ranked exactly as PR-3 does, at the ranking floor 0. Over-bound output is a contract FAIL."""
    try:
        return RankingPlate(_plate_record(readings, ranking_parameters(0.0)))
    except OutputInvalid as exc:
        return RankingPlate(None, str(exc))


def diagnostic_plate_record(readings, floor: float) -> DiagnosticPlate:
    if floor not in DIAGNOSTIC_OCR_FLOORS:
        raise ValueError("diagnostic_floor_not_declared")
    parameters = replace(ranking_parameters(0.0), ocr_confidence_floor=floor)
    return DiagnosticPlate(_plate_record(readings, parameters), floor)


@dataclass(frozen=True, slots=True)
class ReadItem:
    """One GT plate (raw truth) and the composition's ranking-profile plate for it (``plate`` None ⇒ not read)."""

    plate_id: str
    truth: str
    result: RankingPlate
    stratum: str | None = None


@dataclass(frozen=True, slots=True)
class ReadResult:
    outcome: str
    contract_violations: tuple[str, ...]
    plates: int
    exact: int
    em: Fraction | None
    cer: float | None
    ece: float | None
    top_k_hit: Fraction | None
    risk_coverage: tuple[tuple[float, float], ...]
    unsupported_truths: int
    per_stratum: dict = field(default_factory=dict)


def evaluate_reading(items: Iterable[ReadItem]) -> ReadResult:
    """B/C: EM of the rank-0 reading of a ``Read`` plate. ECE uses ``ECE_BINS`` equal-mass bins over the total order
    (confidence descending, then ``plate_id``), so it does not depend on input order (owner item 16)."""
    items = list(items)
    for item in items:
        if not isinstance(item.result, RankingPlate):
            raise ValueError("reading_not_on_ranking_profile")
    violations = tuple(f"{i.result.contract_violation}:{i.plate_id}" for i in items if i.result.contract_violation)
    if violations:
        return ReadResult(CONTRACT_FAIL, violations, 0, 0, None, None, None, None, (), 0, {})
    rows: list[tuple[str, bool, float, float | None, bool, str | None]] = []
    unsupported = 0
    for item in items:
        truth = normalised_truth(item.truth) if item.truth else None
        if truth is None:
            unsupported += 1
            continue
        predicted, confidence, any_rank = "", None, False
        plate = item.result.plate
        if plate is not None and plate.outcome == PLATE_READ:
            confidence = plate.readings[0].confidence
            predicted = normalised_truth(plate.readings[0].raw_text) or ""
            any_rank = any(normalised_truth(r.raw_text) == truth for r in plate.readings)
        rows.append((item.plate_id, predicted == truth, cer(predicted, truth), confidence, any_rank, item.stratum))
    n = len(rows)
    exact = sum(r[1] for r in rows)
    ranked = sorted([(r[3], r[1], r[0]) for r in rows if r[3] is not None], key=lambda t: (-t[0], t[2]))
    ece = None
    if ranked:
        size = math.ceil(len(ranked) / ECE_BINS)
        ece = 0.0
        for start in range(0, len(ranked), size):
            chunk = ranked[start:start + size]
            ece += len(chunk) / len(ranked) * abs(sum(c for c, _, _ in chunk) / len(chunk)
                                                  - sum(e for _, e, _ in chunk) / len(chunk))
    curve, correct = [], 0
    for k, (_, e, _) in enumerate(ranked, 1):
        correct += e
        curve.append((k / n, 1 - correct / k))
    strata: dict[str, list[int]] = {}
    for row in rows:
        if row[5] is not None:
            bucket = strata.setdefault(row[5], [0, 0])
            bucket[0] += 1
            bucket[1] += row[1]
    per_stratum = {name: {"support": s, "em": _ratio(c, s), "status": MEASURED if s >= SUPPORT_FLOOR else INSUFFICIENT}
                   for name, (s, c) in sorted(strata.items())}
    return ReadResult(MEASURED, (), n, exact, _ratio(exact, n), sum(r[2] for r in rows) / n if n else None, ece,
                      _ratio(sum(r[4] for r in rows), n), tuple(curve), unsupported, per_stratum)


def c_minus_b(c: ReadResult, b: ReadResult) -> Fraction | None:
    """Diagnostic only: the detector-attributable EM loss (C − B) on the same plates."""
    return None if c.em is None or b.em is None else c.em - b.em


def accepted_plate(crop: CropRecord) -> RankingPlate:
    """C: the composition's own accepted plate in a scored crop (PR-3 selection)."""
    if crop.status != CROP_SCORED:
        return RankingPlate(None)
    return RankingPlate(next((plate for _, plate in crop.plates()), None))


# ---------------------------------------------------------------------------------------------- top-K (N4)


@dataclass(frozen=True, slots=True)
class ComponentScore:
    candidate_id: str
    independent: bool              # False unless the qualifying release is demonstrably independent (N4)
    support: int
    primary: float | None          # A: recall at coverage; B: EM
    second: float | None           # A: false plates per crop (lower better); B: CER (lower better)
    third: float | None            # A: AP50 (higher better); B: ECE (lower better)
    contract_fail: bool = False


def top_k(scores: Iterable[ComponentScore], k: int, minimum_support: int, kind: str) -> list[str]:
    """N4 tie-breaks. Missing metrics sort last; contract-failed or non-independent components never enter."""
    if kind not in ("detector", "recogniser"):
        raise ValueError("top_k_kind")

    def high(value):
        return (value is None, -(value or 0))

    def low(value):
        return (value is None, value or 0)

    eligible = [s for s in scores if s.independent and not s.contract_fail and s.support >= minimum_support]
    if kind == "detector":
        key = lambda s: (high(s.primary), low(s.second), high(s.third), s.candidate_id)  # noqa: E731
    else:
        key = lambda s: (high(s.primary), low(s.second), low(s.third), s.candidate_id)  # noqa: E731
    return [s.candidate_id for s in sorted(eligible, key=key)[:k]]


# ---------------------------------------------------------------------------------------------- D (N8, N3)


@dataclass(frozen=True, slots=True)
class TrackItem:
    """One Track of a fully labelled, closed population (one physical capture site = ``cluster``).

    ``truth``: raw GT plate text, ``NO_PLATE``, ``UNREADABLE`` or ``NO_GT_VEHICLE``. ``run`` None means the GT vehicle has
    no MAVI Track or no evidence: not read, still in every denominator.
    """

    track_id: str
    cluster: str
    truth: str
    run: TrackRun | None


@dataclass(frozen=True, slots=True)
class TrackCounts:
    exact_denominator: int = 0
    exact_hits: int = 0
    positive_pairs: int = 0
    hit_pairs: int = 0
    returned_pairs: int = 0
    correct_returned: int = 0
    multi_source: int = 0
    consistent_wrong: int = 0
    analysed: int = 0
    no_text: int = 0
    conflicting: int = 0
    unreadable_returned_pairs: int = 0

    def __add__(self, other: "TrackCounts") -> "TrackCounts":
        return TrackCounts(*(getattr(self, n) + getattr(other, n) for n in TrackCounts.__dataclass_fields__))


@dataclass(frozen=True, slots=True)
class TrackScore:
    outcome: str                    # MEASURED | CONTRACT_FAIL
    d_status: str                   # MEASURED | INSUFFICIENT_EVIDENCE (corpus deficiency only) | CONTRACT_FAIL
    exact_recall: Fraction | None
    contains_recall: Fraction | None
    contains_precision: Fraction | None
    d_score: Fraction | None
    counts: TrackCounts
    consistent_wrong_rate: Fraction | None
    consistent_wrong_status: str
    consistent_wrong_conditional_rate: Fraction | None
    conflicting_rate: Fraction | None
    no_text_rate: Fraction | None   # analysed Tracks with no Track text / analysed Tracks
    contract_violations: tuple[str, ...]
    accounting: dict                # every Track counted: text, unsupported, unqueryable, no-plate, unreadable, no-gt


@dataclass(frozen=True, slots=True)
class _Prepared:
    track_id: str
    cluster: str
    kind: str          # "plate" | "no-plate" | "no-gt-vehicle" | "unsupported" | "unreadable"
    truth: str | None
    run: TrackRun | None


def _prepare(items: Sequence[TrackItem], queries: QuerySet, population_manifest_sha256: str
             ) -> tuple[list[_Prepared], dict]:
    if queries.population_manifest_sha256 != population_manifest_sha256:
        raise ValueError("d_queries_bound_to_another_population")
    seen: set[str] = set()
    prepared = []
    accounting = {"text": 0, "unsupported": 0, "unqueryable": 0, "no-plate": 0, "unreadable": 0, "no-gt-vehicle": 0}
    for item in items:
        if not isinstance(item.truth, str) or not item.truth.strip():
            raise ValueError("d_truth_empty_or_missing")
        if item.track_id in seen:
            raise ValueError("d_population_duplicate_track")
        seen.add(item.track_id)
        if item.truth in (NO_PLATE, NO_GT_VEHICLE, UNREADABLE):
            kind = {NO_PLATE: "no-plate", NO_GT_VEHICLE: "no-gt-vehicle", UNREADABLE: "unreadable"}[item.truth]
            accounting[kind] += 1
            prepared.append(_Prepared(item.track_id, item.cluster, kind, None, item.run))
            continue
        truth = normalised_truth(item.truth)
        if truth is None:
            accounting["unsupported"] += 1
            prepared.append(_Prepared(item.track_id, item.cluster, "unsupported", None, item.run))
            continue
        accounting["text"] += 1
        accounting["unqueryable"] += not queryable(truth)
        prepared.append(_Prepared(item.track_id, item.cluster, "plate", truth, item.run))
    supported = {p.truth for p in prepared if p.kind == "plate"}
    if set(queries.truths) != supported:
        raise ValueError("d_queries_not_bound_to_population")
    for p in prepared:
        if p.run is not None and not is_ranking_profile(p.run.parameters):
            raise ValueError("d_run_not_on_ranking_profile")
    return prepared, accounting


def _texts(run: TrackRun | None) -> tuple[str, ...]:
    if run is None or run.record is None or run.record.outcome != TRACK_ANALYSED:
        return ()
    return tuple(text.normalised_text for text in run.record.texts)


def _valid_reading_sources(run: TrackRun | None) -> list[tuple[UUID, str]]:
    if run is None or run.record is None:
        return []
    out = []
    for crop in run.record.crops:
        for _, plate in crop.plates():
            if plate.outcome == PLATE_READ:
                for reading in plate.readings:
                    text = normalised_truth(reading.raw_text)
                    if text is not None:
                        out.append((crop.observation_id, text))
    return out


def _counts(p: _Prepared, queries: QuerySet) -> TrackCounts:
    """Per-Track counts. Unreadable Tracks have unknown truth: excluded from every precision and recall term, with
    their returned pairs counted for accounting. Unsupported-truth Tracks stay in precision: their returns are wrong."""
    texts = _texts(p.run)
    exact_den = exact_hit = positive = hits = returned = correct = multi = wrong = unreadable_returned = 0
    if p.kind == "plate" and queryable(p.truth):
        exact_den = 1
        exact_hit = int(any(matches(EXACT, p.truth, t) for t in texts))
    for query in queries.metric_queries:
        if query.match != CONTAINS:
            continue
        found = any(matches(CONTAINS, query.text, t) for t in texts)
        if p.kind == "unreadable":
            unreadable_returned += found
            continue
        relevant = p.kind == "plate" and not query.negative_only and query.text in p.truth
        positive += relevant
        hits += relevant and found
        returned += found
        correct += relevant and found
    if p.kind == "plate":
        readings = _valid_reading_sources(p.run)
        if len({source for source, _ in readings}) >= 2:
            multi = 1
            values = {text for _, text in readings}
            wrong = int(len(values) == 1 and p.truth not in values)
    analysed = int(p.run is not None and p.run.record is not None and p.run.record.outcome == TRACK_ANALYSED)
    return TrackCounts(exact_den, exact_hit, positive, hits, returned, correct, multi, wrong, analysed,
                       int(analysed and not texts), int(analysed and len(texts) >= 2), unreadable_returned)


def _d_terms(counts: TrackCounts, contains_queries: int) -> tuple[Fraction | None, Fraction | None, Fraction | None]:
    """Owner item 1: candidate silence scores zero; None only for a corpus deficiency."""
    exact = _ratio(counts.exact_hits, counts.exact_denominator)
    recall = _ratio(counts.hit_pairs, counts.positive_pairs)
    if not contains_queries:
        precision = None
    elif counts.returned_pairs:
        precision = Fraction(counts.correct_returned, counts.returned_pairs)
    else:
        precision = Fraction(0)
    return exact, recall, precision


def _d_score(counts: TrackCounts, contains_queries: int) -> Fraction | None:
    parts = _d_terms(counts, contains_queries)
    return None if any(part is None for part in parts) else sum(parts) / 3


def _contains_queries(queries: QuerySet) -> int:
    return sum(1 for q in queries.metric_queries if q.match == CONTAINS)


def _score(prepared: Sequence[_Prepared], queries: QuerySet, accounting: dict) -> TrackScore:
    violations = tuple(f"{p.run.contract_violation}:{p.track_id}" for p in prepared
                       if p.run is not None and p.run.contract_violation is not None)
    total = TrackCounts()
    for p in prepared:
        total = total + _counts(p, queries)
    plate_bearing = sum(1 for p in prepared if p.kind == "plate")
    rate = _ratio(total.consistent_wrong, plate_bearing)
    if violations:
        cw_status = FAIL
    elif plate_bearing < SUPPORT_FLOOR:
        cw_status = INSUFFICIENT
    else:
        cw_status = PASS if rate <= CONSISTENT_WRONG_LIMIT else FAIL
    exact, recall, precision = _d_terms(total, _contains_queries(queries))
    d = None if violations else _d_score(total, _contains_queries(queries))
    d_status = CONTRACT_FAIL if violations else (MEASURED if d is not None else INSUFFICIENT)
    return TrackScore(CONTRACT_FAIL if violations else MEASURED, d_status, exact, recall, precision, d, total, rate,
                      cw_status, _ratio(total.consistent_wrong, total.multi_source),
                      _ratio(total.conflicting, total.analysed), _ratio(total.no_text, total.analysed), violations,
                      dict(accounting))


def evaluate_tracks(items: Sequence[TrackItem], queries: QuerySet, *, population_manifest_sha256: str) -> TrackScore:
    """D on the ranking profile only. Any contract violation makes the composition CONTRACT_FAIL (never scored)."""
    prepared, accounting = _prepare(items, queries, population_manifest_sha256)
    return _score(prepared, queries, accounting)


def diagnostic_evaluate_at_floor(items: Sequence[TrackItem], queries: QuerySet, floor: float, *,
                                 population_manifest_sha256: str) -> TrackScore:
    """DIAGNOSTIC ONLY (D6): D as PR-3 would publish it at another OCR floor. Its result type is the same, but it is
    never an input to top-K, gates or the bootstrap, which recompute from ranking-profile runs themselves."""
    if floor not in DIAGNOSTIC_OCR_FLOORS:
        raise ValueError("diagnostic_floor_not_declared")
    prepared, accounting = _prepare(items, queries, population_manifest_sha256)
    refloored = []
    for p in prepared:
        run = p.run
        if run is not None and run.record is not None:
            run = TrackRun(_refloor(run.record, floor), None, replace(run.parameters, ocr_confidence_floor=floor))
        refloored.append(replace(p, run=run))
    score = _score(refloored, queries, accounting)
    return replace(score, accounting={**score.accounting, "diagnosticFloor": floor})


# ---------------------------------------------------------------------------------------------- comparison


@dataclass(frozen=True, slots=True)
class Comparison:
    outcome: str  # superior | not-superior | insufficient-clusters | insufficient-evidence | contract-fail
    difference: Fraction | None
    lower: Fraction | None
    upper: Fraction | None
    clusters: int
    required_clusters: int
    cluster_unit: str
    insufficient_replicates: int
    cluster_signs: dict
    per_cluster: dict


def _pairing(items_a: Sequence[TrackItem], items_b: Sequence[TrackItem]) -> None:
    key = lambda i: (i.track_id, i.truth, i.cluster)  # noqa: E731
    if [key(i) for i in items_a] != [key(i) for i in items_b]:
        raise ValueError("paired_population_mismatch")


def _draws(rng: random.Random, members: dict[str, list[int]], names: list[str]) -> list[int]:
    picked = []
    for _ in names:
        group = members[names[rng.randrange(len(names))]]
        picked.extend(group[rng.randrange(len(group))] for _ in group)
    return picked


def bootstrap_replicates(items_a, items_b, queries, *, replicates: int, seed: int, population_manifest_sha256: str,
                         slow: bool = False) -> list[Fraction | None]:
    """Exact ΔD per replicate (sites with replacement, then Tracks within each drawn site). ``slow=True``
    re-evaluates every resampled population from the Tracks; the fast path sums precomputed per-Track counts. Tests
    prove the two are identical."""
    if not (isinstance(replicates, int) and replicates >= 1):
        raise ValueError("bootstrap_replicates_invalid")
    pa, _ = _prepare(items_a, queries, population_manifest_sha256)
    pb, _ = _prepare(items_b, queries, population_manifest_sha256)
    members: dict[str, list[int]] = {}
    for index, p in enumerate(pa):
        members.setdefault(p.cluster, []).append(index)
    names = sorted(members)
    n_contains = _contains_queries(queries)
    counts_a = [_counts(p, queries) for p in pa]
    counts_b = [_counts(p, queries) for p in pb]
    rng = random.Random(seed)
    out: list[Fraction | None] = []
    for _ in range(replicates):
        picked = _draws(rng, members, names)
        if slow:
            renamed = lambda ps: [replace(ps[i], track_id=f"{ps[i].track_id}#{n}") for n, i in enumerate(picked)]  # noqa: E731
            da = _score(renamed(pa), queries, {}).d_score
            db = _score(renamed(pb), queries, {}).d_score
        else:
            ta, tb = TrackCounts(), TrackCounts()
            for i in picked:
                ta, tb = ta + counts_a[i], tb + counts_b[i]
            da, db = _d_score(ta, n_contains), _d_score(tb, n_contains)
        out.append(None if da is None or db is None else da - db)
    return out


def paired_cluster_bootstrap(items_a: Sequence[TrackItem], items_b: Sequence[TrackItem], queries: QuerySet, *,
                             replicates: int, seed: int, required_clusters: int, population_manifest_sha256: str,
                             cluster_unit: str = CLUSTER_UNIT, mpid: Fraction = MPID) -> Comparison:
    """The frozen superiority rule (owner item 2): ``superior`` iff
    - observed ΔD ≥ MPID (exact);
    - the paired hierarchical 95 % percentile interval excludes zero in A's favour (lower bound > 0, exact);
    - clusters ≥ ``required_clusters`` (protocol-frozen, ≥ 60).

    A replicate is undefined only when the resampled corpus lacks support (no positive pair or no queryable plate).
    That refuses the interval as ``insufficient-evidence``. Candidate silence scores zero and never removes a
    replicate."""
    if cluster_unit != CLUSTER_UNIT:
        raise ValueError("cluster_unit_must_be_physical_capture_site")
    if not (isinstance(required_clusters, int) and required_clusters >= ABSOLUTE_MINIMUM_CLUSTERS):
        raise ValueError("required_clusters_below_absolute_minimum")
    if not (isinstance(replicates, int) and replicates >= 1):
        raise ValueError("bootstrap_replicates_invalid")
    _pairing(items_a, items_b)
    a = evaluate_tracks(items_a, queries, population_manifest_sha256=population_manifest_sha256)
    b = evaluate_tracks(items_b, queries, population_manifest_sha256=population_manifest_sha256)
    clusters = sorted({i.cluster for i in items_a})
    per_cluster, signs = {}, {"a": 0, "b": 0, "tie": 0, "insufficient": 0}

    def result(outcome, difference=None, lower=None, upper=None, insufficient=0):
        return Comparison(outcome, difference, lower, upper, len(clusters), required_clusters, cluster_unit,
                          insufficient, signs, per_cluster)

    if a.outcome == CONTRACT_FAIL or b.outcome == CONTRACT_FAIL:
        return result("contract-fail")
    if a.d_score is None or b.d_score is None:
        return result("insufficient-evidence")
    pa, _ = _prepare(items_a, queries, population_manifest_sha256)
    pb, _ = _prepare(items_b, queries, population_manifest_sha256)
    n_contains = _contains_queries(queries)
    for name in clusters:
        ca, cb = TrackCounts(), TrackCounts()
        for p, q in zip(pa, pb):
            if p.cluster == name:
                ca, cb = ca + _counts(p, queries), cb + _counts(q, queries)
        da, db = _d_score(ca, n_contains), _d_score(cb, n_contains)
        value = None if da is None or db is None else da - db
        per_cluster[name] = value
        signs["insufficient" if value is None else "a" if value > 0 else "b" if value < 0 else "tie"] += 1
    observed = a.d_score - b.d_score
    if len(clusters) < required_clusters:
        return result("insufficient-clusters", observed)
    values = bootstrap_replicates(items_a, items_b, queries, replicates=replicates, seed=seed,
                                  population_manifest_sha256=population_manifest_sha256)
    insufficient = sum(v is None for v in values)
    if insufficient:
        return result("insufficient-evidence", observed, insufficient=insufficient)
    values.sort()
    lower = values[int(0.025 * (len(values) - 1))]
    upper = values[int(math.ceil(0.975 * (len(values) - 1)))]
    superior = observed >= mpid and lower > 0
    return result("superior" if superior else "not-superior", observed, lower, upper)


@dataclass(frozen=True, slots=True)
class CompositionScore:
    detector_id: str
    recogniser_id: str
    score: TrackScore


# ------------------------------------------------------------------ baseline resolution (N2 revised + addendum 2026-10-14)
#
# Stage 1 (at PROTOCOL_FROZEN) freezes a ``BaselineFreeze``:
# - the eligible detector universe with exact identity hashes;
# - the complete OC5 benchmark-only identity;
# - the Layer-A gate set hash;
# - the detector ranking/tie-break rule (``DETECTOR_RANKING_RULE``);
# - the fact that PD_BASE + OC5 is the single hard D baseline gating every ordinary D composition.
#
# Stage 2 (after Layer A, before any protected D data is read) derives PD_BASE mechanically with
# ``resolve_baseline``, which returns an immutable, self-hashing ``BaselineResolution``. There is no owner input
# and no substitution. "No survivor", "ambiguous" and "inconsistent" each stop the event (``BaselineStop``).

DETECTOR_RANKING_RULE = ("mavi-plate-detector-rank-v1: Layer-A gate pass required; recall at coverage desc; "
                         "false plates per crop asc; AP50 desc; missing metric sorts last; candidate id asc (ordinal)")
DETECTOR_RANKING_RULE_SHA256 = hashlib.sha256(DETECTOR_RANKING_RULE.encode("utf-8")).hexdigest()
D_NOT_STARTED = "D_NOT_STARTED"
BASELINE_RULE = "PD_BASE+OC5 is the single hard D baseline and gates every ordinary D composition"


class BaselineStop(Exception):
    """The D event stops. There is no baseline and no D ranking. The reason is ``args[0]``."""


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _canonical_sha256(payload: dict) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _detector_key(s: ComponentScore):
    def high(value):
        return (value is None, -(value or 0))

    def low(value):
        return (value is None, value or 0)

    return (high(s.primary), low(s.second), high(s.third), s.candidate_id)


@dataclass(frozen=True, slots=True)
class BaselineFreeze:
    """Stage 1, frozen in the protocol at PROTOCOL_FROZEN."""
    eligible_detectors: tuple[tuple[str, str], ...]   # (detector id, exact identity SHA-256), sorted, unique
    benchmark_only_id: str                             # OC5: the benchmark-only (reference-only) component
    benchmark_only_identity_sha256: str
    layer_a_gates_sha256: str
    ranking_rule_sha256: str = DETECTOR_RANKING_RULE_SHA256

    def __post_init__(self):
        ids = [d for d, _ in self.eligible_detectors]
        if not ids or ids != sorted(set(ids)):
            raise ValueError("baseline_freeze_detectors_must_be_sorted_unique_nonempty")
        if self.benchmark_only_id in ids:
            raise ValueError("baseline_freeze_benchmark_only_component_cannot_be_a_detector_candidate")
        hashes = [h for _, h in self.eligible_detectors] + [self.benchmark_only_identity_sha256,
                                                             self.layer_a_gates_sha256, self.ranking_rule_sha256]
        if not all(_is_sha256(h) for h in hashes):
            raise ValueError("baseline_freeze_hash_malformed")
        if self.ranking_rule_sha256 != DETECTOR_RANKING_RULE_SHA256:
            raise ValueError("baseline_freeze_ranking_rule_not_the_frozen_rule")

    def freeze_sha256(self) -> str:
        return _canonical_sha256({"eligibleDetectors": [list(d) for d in self.eligible_detectors],
                                  "benchmarkOnlyId": self.benchmark_only_id,
                                  "benchmarkOnlyIdentitySha256": self.benchmark_only_identity_sha256,
                                  "layerAGatesSha256": self.layer_a_gates_sha256,
                                  "rankingRuleSha256": self.ranking_rule_sha256,
                                  "baselineRule": BASELINE_RULE})


@dataclass(frozen=True, slots=True)
class LayerAResult:
    """One eligible detector's Layer-A result on the A/B partition: gate verdict plus ranking metrics."""
    score: ComponentScore
    identity_sha256: str      # the exact identity that produced the result
    gates_passed: bool


@dataclass(frozen=True, slots=True)
class BaselineResolution:
    """Stage 2 record. It is immutable: ``record_sha256`` covers every other field, and ``verify_resolution`` re-derives it."""
    freeze_sha256: str
    pd_base_id: str
    pd_base_identity_sha256: str
    benchmark_only_id: str
    benchmark_only_identity_sha256: str
    layer_a_result_sha256: str
    ranking_rule_sha256: str
    composition_sha256: str
    resolved_at_utc: str
    d_state: str
    record_sha256: str

    def payload(self) -> dict:
        return {"freezeSha256": self.freeze_sha256, "pdBaseId": self.pd_base_id,
                "pdBaseIdentitySha256": self.pd_base_identity_sha256, "benchmarkOnlyId": self.benchmark_only_id,
                "benchmarkOnlyIdentitySha256": self.benchmark_only_identity_sha256,
                "layerAResultSha256": self.layer_a_result_sha256, "rankingRuleSha256": self.ranking_rule_sha256,
                "compositionSha256": self.composition_sha256, "resolvedAtUtc": self.resolved_at_utc,
                "dState": self.d_state}


def layer_a_result_sha256(results: Sequence[LayerAResult]) -> str:
    rows = [{"id": r.score.candidate_id, "identity": r.identity_sha256, "gatesPassed": r.gates_passed,
             "contractFail": r.score.contract_fail, "support": r.score.support,
             "metrics": [None if v is None else repr(v) for v in (r.score.primary, r.score.second, r.score.third)]}
            for r in sorted(results, key=lambda r: r.score.candidate_id)]
    return _canonical_sha256({"layerA": rows})


def resolve_baseline(freeze: BaselineFreeze, results: Sequence[LayerAResult], *, d_rows_read: int,
                     resolved_at_utc: str) -> BaselineResolution:
    """Stage 2. Derive PD_BASE mechanically from the frozen rule. It raises ``BaselineStop`` and never chooses."""
    if d_rows_read != 0:
        raise BaselineStop("baseline_resolution_after_d_data_read")
    eligible = dict(freeze.eligible_detectors)
    seen = [r.score.candidate_id for r in results]
    if len(seen) != len(set(seen)):
        raise BaselineStop("layer_a_result_ambiguous_duplicate_detector")
    if set(seen) != set(eligible):
        # a detector outside the frozen universe, or a frozen detector missing from Layer A
        raise BaselineStop("layer_a_result_inconsistent_with_frozen_detector_universe")
    for r in results:
        if r.identity_sha256 != eligible[r.score.candidate_id]:
            raise BaselineStop(f"layer_a_identity_mismatch:{r.score.candidate_id}")
        if r.gates_passed and r.score.contract_fail:
            raise BaselineStop(f"layer_a_result_inconsistent_gate_pass_with_contract_fail:{r.score.candidate_id}")
        if r.gates_passed and any(v is not None and not math.isfinite(v)
                                  for v in (r.score.primary, r.score.second, r.score.third)):
            raise BaselineStop(f"layer_a_rank_ambiguous_non_finite_metric:{r.score.candidate_id}")
    survivors = sorted((r.score for r in results if r.gates_passed), key=_detector_key)
    if not survivors:
        raise BaselineStop("no_detector_passed_layer_a")
    pd_base = survivors[0].candidate_id
    composition = _canonical_sha256({"detector": [pd_base, eligible[pd_base]],
                                     "recogniser": [freeze.benchmark_only_id, freeze.benchmark_only_identity_sha256],
                                     "role": "gate-only-baseline-composition"})
    unsealed = BaselineResolution(
        freeze_sha256=freeze.freeze_sha256(), pd_base_id=pd_base, pd_base_identity_sha256=eligible[pd_base],
        benchmark_only_id=freeze.benchmark_only_id,
        benchmark_only_identity_sha256=freeze.benchmark_only_identity_sha256,
        layer_a_result_sha256=layer_a_result_sha256(results), ranking_rule_sha256=freeze.ranking_rule_sha256,
        composition_sha256=composition, resolved_at_utc=resolved_at_utc, d_state=D_NOT_STARTED, record_sha256="")
    return replace(unsealed, record_sha256=_canonical_sha256(unsealed.payload()))


def _check_sealed(resolution: BaselineResolution) -> None:
    if resolution.record_sha256 != _canonical_sha256(resolution.payload()):
        raise BaselineStop("baseline_resolution_record_altered")
    if resolution.d_state != D_NOT_STARTED:
        raise BaselineStop("baseline_resolution_not_sealed_before_d")


def verify_resolution(freeze: BaselineFreeze, resolution: BaselineResolution, results: Sequence[LayerAResult]) -> None:
    """Re-derive Stage 2 from the frozen inputs. Any edit, substitution or drift raises ``BaselineStop``."""
    _check_sealed(resolution)
    expected = resolve_baseline(freeze, results, d_rows_read=0, resolved_at_utc=resolution.resolved_at_utc)
    if expected != resolution:
        raise BaselineStop("baseline_resolution_differs_from_frozen_derivation")


def assert_resolution_unchanged(sealed: BaselineResolution, current: BaselineResolution) -> None:
    """The sealed record is final. A later record with any different field stops the event."""
    if sealed != current:
        raise BaselineStop("baseline_resolution_changed_after_seal")


def rankable_compositions(compositions: Iterable[CompositionScore],
                          resolution: BaselineResolution) -> list[CompositionScore]:
    """The ordinary D compositions that may enter ranking, the frontier or implementation.

    Any composition containing the benchmark-only component (OC5), including the gate-only baseline composition, is
    refused outright, never silently filtered."""
    out = list(compositions)
    for c in out:
        if resolution.benchmark_only_id in (c.detector_id, c.recogniser_id):
            raise ValueError("benchmark_only_component_cannot_be_ranked")
    return out


def baseline_gate(composition: CompositionScore, baseline: CompositionScore, resolution: BaselineResolution,
                  mpid: Fraction = MPID) -> str:
    """N2 (revised): ONE hard gate against the sealed baseline composition PD_BASE + OC5.

    Rules:
    - Every ordinary composition, whatever its detector, must satisfy observed D − D(PD_BASE + OC5) ≥ MPID (exact).
    - A composition contract violation is FAIL.
    - A baseline that broke the contract, or cannot be evaluated, stops the event (``BaselineStop``); it is never replaced.
    - A silent baseline is a valid measurement that scores 0.
    - A corpus-deficient composition D is INSUFFICIENT_EVIDENCE.
    """
    _check_sealed(resolution)
    if (baseline.detector_id, baseline.recogniser_id) != (resolution.pd_base_id, resolution.benchmark_only_id):
        raise ValueError("baseline_is_not_the_sealed_pd_base_composition")
    rankable_compositions([composition], resolution)
    if baseline.score.outcome == CONTRACT_FAIL:
        raise BaselineStop("baseline_contract_violation")
    if baseline.score.d_score is None:
        raise BaselineStop("baseline_not_evaluable")
    if composition.score.outcome == CONTRACT_FAIL:
        return FAIL
    if composition.score.d_score is None:
        return INSUFFICIENT
    return PASS if composition.score.d_score - baseline.score.d_score >= mpid else FAIL


def diagnostic_ocr_uplift(composition: CompositionScore, matched_baseline: CompositionScore,
                          benchmark_only_id: str) -> Fraction | None:
    """DIAGNOSTIC ONLY (N2 revised): OCR uplift at a fixed detector, D(PDx + OCy) − D(PDx + OC5).

    It never passes or fails a composition, never enters top-K or the ranking, and never changes the baseline or MPID."""
    if matched_baseline.detector_id != composition.detector_id or matched_baseline.recogniser_id != benchmark_only_id:
        raise ValueError("diagnostic_baseline_not_detector_matched")
    if CONTRACT_FAIL in (composition.score.outcome, matched_baseline.score.outcome):
        return None
    if composition.score.d_score is None or matched_baseline.score.d_score is None:
        return None
    return composition.score.d_score - matched_baseline.score.d_score
