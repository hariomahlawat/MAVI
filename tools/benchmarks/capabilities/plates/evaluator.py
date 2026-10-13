"""Stage-4 model-selection evaluators A–D (plan §4.4), built on PR-3's merged plate rules.

These are the evaluators plan §7 assigned to PR-1. They were not delivered with PR-1; this module repairs that (see the
register's repair record). They read **no** dataset by themselves: every function takes in-memory ground truth and
candidate outputs. A–D run candidate outputs through ``mavi_vision.plates.pipeline`` (``analyse_crop``,
``summarise_track``), so the per-crop bounds (≤ 2 proposals, ≤ 1 accepted plate, ≤ 3 readings), reading order,
``Read``/``Unreadable``, abstention reasons and the ``plate-track-text-rank0`` summary are the product's own. Text is
normalised only by the frozen ``mavi-plate-normalisation-v1``. Confidence is reading-level; no per-character score is
assumed.

* **A** — plate detection on ground-truth vehicle crops: recall at coverage ≥ ``coverage_threshold`` of the GT
  plate polygon by any proposal; diagnostics: false plates per crop, AP50 (VOC all-point, greedy IoU ≥ 0.5).
* **B** — OCR on ground-truth plate crops: normalised exact match of the rank-0 reading of a ``Read`` plate;
  diagnostics: CER, ECE (equal-mass bins), risk–coverage.
* **C** — OCR on the composition's own accepted plate (PR-3 selection), same truth as B.
* **D** — end-to-end Track level on a **fully labelled, closed** Track population: D-score = unweighted mean of
  full-plate Track recall at ``exact``, partial-query Track precision at ``contains`` and partial-query Track recall
  at ``contains`` (owner decision N8). Consistent-wrong (N3), conflicting and unreadable rates are diagnostics; the
  consistent-wrong rate is gated.
* Comparisons: hierarchical paired cluster bootstrap (MSR §8.1) with the owner's MPID and minimum cluster count.

Values the owner has decided (2026-10-13) are module constants the protocol references; values still open are
required parameters with no default.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from uuid import UUID

from mavi_vision.plates.contracts import (
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

from tools.benchmarks.capabilities.plates.queries import CONTAINS, EXACT, NEGATIVE, QuerySet, matches

# Owner decisions 2026-10-13 (protocol plates-2026-01 §3.3, §7).
PLAN_COVERAGE_THRESHOLD = 0.95          # plan §4.4 A
RANKING_OCR_CONFIDENCE_FLOOR = 0.0      # D6: the only floor that may affect D, gates or selection
DIAGNOSTIC_OCR_FLOORS = (0.3, 0.5, 0.7)  # D6: diagnostics only; never D-score, gates or selection
MPID = 0.04                             # D7a (revised 2026-10-13), on D-score
ABSOLUTE_MINIMUM_CLUSTERS = 60          # D7b: an absolute floor only, never "adequately powered". The required
                                        # D-ranking cluster count is frozen in the protocol from the final
                                        # candidate-blind power calculation and passed as ``required_clusters``.
CONSISTENT_WRONG_LIMIT = 0.02           # plan §4.5, N3
CONSISTENT_WRONG_SUPPORT = 50           # N3
P14_TOLERANCE = 0.02                    # N5 (PR-6 agreement), recorded here for the protocol

PASS, FAIL, INSUFFICIENT = "PASS", "FAIL", "INSUFFICIENT_EVIDENCE"
NO_PLATE = "<no-plate>"  # a fully labelled Track whose vehicle shows no plate (truth known: no text)


def evaluation_parameters(detector_confidence_floor: float,
                          ocr_confidence_floor: float = RANKING_OCR_CONFIDENCE_FLOOR) -> PlateParameters:
    """PR-3 parameters at the frozen 2/1/3 bounds (D6). The detector floor is each candidate's pinned default."""
    return PlateParameters(MAXIMUM_DETECTIONS_PER_CROP, MAXIMUM_PLATES_PER_CROP, MAXIMUM_READINGS_PER_PLATE,
                           float(detector_confidence_floor), float(ocr_confidence_floor), frozenset(), None)


def normalised_truth(raw: str) -> str | None:
    result = normalise(raw)
    return result.normalised if result.outcome == OK else None


# ---------------------------------------------------------------------------------------------- running PR-3 rules


@dataclass(frozen=True, slots=True)
class EvidenceCrop:
    """One evidence crop of a Track: its verified bytes and role (``LeaseObservation`` fields)."""

    observation_id: UUID
    role: str
    evidence_rank: int
    sha256: str
    content: bytes


@dataclass(frozen=True, slots=True)
class TrackRun:
    """A Track's PR-3 outcome, or the contract violation that failed it (``plate_output_invalid``; N9: FAIL)."""

    record: TrackRecord | None
    contract_violation: str | None


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
        return TrackRun(None, str(exc))
    return TrackRun(summarise_track(track, tuple(records)), None)


def refloor(record: TrackRecord, floor: float) -> TrackRecord:
    """DIAGNOSTIC ONLY (D6): the Track as PR-3 would publish it at another OCR floor. Never used for D, gates or
    selection. Readings are kept; only ``Read``/``Unreadable`` and the Track texts are re-derived."""
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
    """One GT vehicle crop: its GT plate polygons and the detector's proposals ``(x, y, w, h, score)`` (as PR-3
    records them, integer pixels)."""

    crop_id: str
    plates: tuple[tuple[tuple[float, float], ...], ...]
    proposals: tuple[tuple[int, int, int, int, float], ...]


@dataclass(frozen=True, slots=True)
class DetectionResult:
    plates: int
    covered: int
    recall: float | None
    false_plates_per_crop: float | None
    ap50: float | None


def evaluate_detection(items: Iterable[DetectionItem], coverage_threshold: float = PLAN_COVERAGE_THRESHOLD
                       ) -> DetectionResult:
    items = list(items)
    plates = covered = false = 0
    scored: list[tuple[float, str, int, bool]] = []
    for item in items:
        boxes = [(x, y, x + w, y + h) for x, y, w, h, _ in item.proposals]
        plates += len(item.plates)
        covered += sum(1 for polygon in item.plates if any(coverage(polygon, b) >= coverage_threshold for b in boxes))
        false += sum(1 for b in boxes if not any(coverage(p, b) >= coverage_threshold for p in item.plates))
        gt_boxes = [(min(x for x, _ in p), min(y for _, y in p), max(x for x, _ in p), max(y for _, y in p))
                    for p in item.plates]
        taken: set[int] = set()
        order = sorted(range(len(boxes)), key=lambda i: (-item.proposals[i][4], i))
        for index in order:
            best, best_iou = None, 0.5
            for g, gt in enumerate(gt_boxes):
                value = _iou(boxes[index], gt)
                if g not in taken and value >= best_iou:
                    best, best_iou = g, value
            if best is not None:
                taken.add(best)
            scored.append((item.proposals[index][4], item.crop_id, index, best is not None))
    ap = None
    if plates:
        scored.sort(key=lambda s: (-s[0], s[1], s[2]))
        tp = 0
        points = []
        for rank, (_, _, _, hit) in enumerate(scored, 1):
            tp += hit
            points.append((tp / plates, tp / rank))
        ap = 0.0
        previous_recall = 0.0
        for i, (recall, _) in enumerate(points):
            precision = max(p for r, p in points[i:])
            ap += (recall - previous_recall) * precision
            previous_recall = recall
    return DetectionResult(plates, covered, covered / plates if plates else None,
                           false / len(items) if items else None, ap)


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
class ReadItem:
    """One GT plate (truth raw text) and the composition's plate outcome: the PR-3 ``PlateRecord`` read from it, or
    ``None`` when no plate was accepted/read (abstained, unavailable, no detection: counted as not read)."""

    plate_id: str
    truth: str
    plate: object | None  # mavi_vision.plates.pipeline.PlateRecord


@dataclass(frozen=True, slots=True)
class ReadResult:
    plates: int
    exact: int
    em: float | None
    cer: float | None
    ece: float | None
    risk_coverage: tuple[tuple[float, float], ...]
    unsupported_truths: int


def plate_record_from_readings(readings, parameters: PlateParameters):
    """B on GT plate crops: rank and classify a recogniser's readings exactly as PR-3 does (``_plate``)."""
    from mavi_vision.plates.contracts import has_strict_rank_order, is_raw_text
    from mavi_vision.plates.pipeline import _plate  # the product's own rule, not a re-implementation

    readings = list(readings)
    if len(readings) > parameters.max_readings_per_plate:
        raise OutputInvalid("plate_recogniser_output_exceeds_bound")
    if not all(is_raw_text(r.raw_text) and isinstance(r.confidence, (int, float)) and not isinstance(r.confidence, bool)
               and math.isfinite(r.confidence) and 0 <= r.confidence <= 1 for r in readings) \
            or not has_strict_rank_order(readings):
        return None  # ocr_output_invalid abstention: no readings kept (ADR-013 item 15 exception)
    return _plate(0, readings, parameters)


def evaluate_reading(items: Iterable[ReadItem], ece_bins: int) -> ReadResult:
    """EM of the rank-0 reading of a ``Read`` plate; ``ece_bins`` (equal-mass) is an explicit parameter."""
    rows: list[tuple[bool, float, float | None]] = []
    unsupported = 0
    for item in items:
        truth = normalised_truth(item.truth)
        if truth is None:
            unsupported += 1
            continue
        predicted, confidence = "", None
        plate = item.plate
        if plate is not None and plate.outcome == PLATE_READ:
            first = plate.readings[0]
            confidence = first.confidence
            predicted = normalised_truth(first.raw_text) or ""
        rows.append((predicted == truth, cer(predicted, truth), confidence))
    n = len(rows)
    exact = sum(r[0] for r in rows)
    with_confidence = sorted([(c, e) for e, _, c in rows if c is not None], key=lambda t: -t[0])
    ece = None
    if with_confidence and ece_bins >= 1:
        size = math.ceil(len(with_confidence) / ece_bins)
        ece = 0.0
        for start in range(0, len(with_confidence), size):
            chunk = with_confidence[start:start + size]
            ece += len(chunk) / len(with_confidence) * abs(sum(c for c, _ in chunk) / len(chunk)
                                                          - sum(e for _, e in chunk) / len(chunk))
    curve = []
    correct = 0
    for k, (_, e) in enumerate(with_confidence, 1):
        correct += e
        curve.append((k / n, 1 - correct / k))
    return ReadResult(n, exact, exact / n if n else None, sum(r[1] for r in rows) / n if n else None, ece,
                      tuple(curve), unsupported)


def accepted_plate(crop: CropRecord):
    """C: the composition's own accepted plate in a scored crop (PR-3 selection), or ``None``."""
    if crop.status != CROP_SCORED:
        return None
    return next((plate for _, plate in crop.plates()), None)


# ---------------------------------------------------------------------------------------------- top-K (N4)


@dataclass(frozen=True, slots=True)
class ComponentScore:
    candidate_id: str
    independent: bool       # False when any exposure on the qualifying release makes the pair reference-only
    support: int
    primary: float          # A: recall at coverage; B: EM
    second: float           # A: false plates per crop (lower better); B: CER (lower better)
    third: float            # A: AP50 (higher better); B: ECE (lower better)


def top_k(scores: Iterable[ComponentScore], k: int, minimum_support: int, kind: str) -> list[str]:
    """N4: only independent pairs with sufficient common support enter; deterministic tie-breaks:
    detectors — primary, then lower false plates per crop, then higher AP50, then lexical id;
    recognisers — EM, then lower CER, then lower ECE, then lexical id."""
    if kind not in ("detector", "recogniser"):
        raise ValueError("top_k_kind")
    eligible = [s for s in scores if s.independent and s.support >= minimum_support]
    if kind == "detector":
        key = lambda s: (-s.primary, s.second, -s.third, s.candidate_id)  # noqa: E731
    else:
        key = lambda s: (-s.primary, s.second, s.third, s.candidate_id)  # noqa: E731
    return [s.candidate_id for s in sorted(eligible, key=key)[:k]]


# ---------------------------------------------------------------------------------------------- D (N8, N3)


@dataclass(frozen=True, slots=True)
class TrackItem:
    """One Track of a fully labelled, closed population. ``truth`` is the raw GT plate text, or ``NO_PLATE`` for a
    labelled Track without a visible plate; unknown truth is refused. ``run`` is ``None`` when the GT vehicle has no
    MAVI Track or no evidence (counted as not read)."""

    track_id: str
    cluster: str
    truth: str
    run: TrackRun | None


@dataclass(frozen=True, slots=True)
class TrackScore:
    exact_recall: float | None
    contains_recall: float | None
    contains_precision: float | None
    d_score: float | None
    exact_denominator: int
    positive_pairs: int
    returned_pairs: int
    consistent_wrong: int
    consistent_wrong_denominator: int
    consistent_wrong_rate: float | None
    consistent_wrong_status: str
    multi_reading_tracks: int
    consistent_wrong_conditional_rate: float | None
    conflicting_rate: float | None
    unreadable_rate: float | None
    contract_violations: int


def _texts(item: TrackItem) -> tuple[str, ...]:
    if item.run is None or item.run.record is None or item.run.record.outcome != TRACK_ANALYSED:
        return ()
    return tuple(text.normalised_text for text in item.run.record.texts)


def _valid_readings(item: TrackItem) -> list[tuple[UUID, str]]:
    """Every valid normalised reading (all kept ranks) of the Track's Read plates, with its source observation."""
    if item.run is None or item.run.record is None:
        return []
    out = []
    for crop in item.run.record.crops:
        for _, plate in crop.plates():
            if plate.outcome != PLATE_READ:
                continue
            for reading in plate.readings:
                text = normalised_truth(reading.raw_text)
                if text is not None:
                    out.append((crop.observation_id, text))
    return out


def evaluate_tracks(items: Sequence[TrackItem], queries: QuerySet) -> TrackScore:
    truths: dict[str, str | None] = {}
    evaluable = []
    for item in items:
        if not isinstance(item.truth, str):
            raise ValueError("d_population_not_fully_labelled")
        if item.track_id in truths:
            raise ValueError("d_population_duplicate_track")
        truth = None if item.truth == NO_PLATE else normalised_truth(item.truth)
        if item.truth != NO_PLATE and truth is None:
            continue  # unsupported truth (normalisation rejects it): not evaluable, never guessed
        truths[item.track_id] = truth
        evaluable.append(item)
    items = evaluable
    plate_bearing = [i for i in items if truths[i.track_id] is not None]
    texts = {i.track_id: _texts(i) for i in items}

    exact_hits = sum(1 for i in plate_bearing if truths[i.track_id] in texts[i.track_id])
    exact_n = len(plate_bearing)

    positive = hits = returned = correct_returned = 0
    for query in queries.queries:
        if query.match != CONTAINS:
            continue
        for item in items:
            truth = truths[item.track_id]
            relevant = truth is not None and query.query_class != NEGATIVE and query.text in truth
            found = any(matches(query, t) for t in texts[item.track_id])
            positive += relevant
            hits += relevant and found
            returned += found
            correct_returned += found and truth is not None and query.text in truth
    exact_recall = exact_hits / exact_n if exact_n else None
    contains_recall = hits / positive if positive else None
    precision = correct_returned / returned if returned else None
    parts = (exact_recall, contains_recall, precision)
    d_score = sum(parts) / 3 if all(p is not None for p in parts) else None

    wrong = multi = 0
    for item in plate_bearing:
        readings = _valid_readings(item)
        if len({source for source, _ in readings}) < 2:
            continue
        multi += 1
        values = {text for _, text in readings}
        if len(values) == 1 and truths[item.track_id] not in values:
            wrong += 1
    rate = wrong / exact_n if exact_n else None
    status = INSUFFICIENT if exact_n < CONSISTENT_WRONG_SUPPORT else (PASS if rate <= CONSISTENT_WRONG_LIMIT else FAIL)
    analysed = [i for i in items if i.run is not None and i.run.record is not None
                and i.run.record.outcome == TRACK_ANALYSED]
    conflicting = sum(1 for i in analysed if len(texts[i.track_id]) >= 2)
    unreadable = sum(1 for i in analysed if not texts[i.track_id])
    violations = sum(1 for i in items if i.run is not None and i.run.contract_violation is not None)
    return TrackScore(exact_recall, contains_recall, precision, d_score, exact_n, positive, returned, wrong, exact_n,
                      rate, status, multi, wrong / multi if multi else None,
                      conflicting / len(analysed) if analysed else None,
                      unreadable / len(analysed) if analysed else None, violations)


# ---------------------------------------------------------------------------------------------- comparison (D7)


@dataclass(frozen=True, slots=True)
class Comparison:
    difference: float | None
    lower: float | None
    upper: float | None
    clusters: int
    outcome: str  # superior | not-superior | insufficient-clusters


def paired_cluster_bootstrap(items_a: Sequence[TrackItem], items_b: Sequence[TrackItem], queries: QuerySet,
                             replicates: int, seed: int, required_clusters: int, mpid: float = MPID) -> Comparison:
    """Paired hierarchical bootstrap of D-score(a) − D-score(b) on the same Tracks: clusters with replacement, then
    Tracks with replacement inside each drawn cluster; 95 % percentile interval. ``superior`` needs the interval to
    exclude zero **and** the observed difference ≥ ``mpid``. ``required_clusters`` is the protocol-frozen D-ranking
    cluster count; it may not be below ``ABSOLUTE_MINIMUM_CLUSTERS``. Fewer clusters than required is
    ``insufficient-clusters`` (never a winner)."""
    by_id_b = {item.track_id: item for item in items_b}
    if [i.track_id for i in items_a] != [i.track_id for i in items_b]:
        raise ValueError("paired_population_mismatch")
    clusters: dict[str, list[TrackItem]] = {}
    for item in items_a:
        clusters.setdefault(item.cluster, []).append(item)
    names = sorted(clusters)
    a, b = evaluate_tracks(items_a, queries).d_score, evaluate_tracks(items_b, queries).d_score
    observed = None if a is None or b is None else a - b
    if not (isinstance(required_clusters, int) and required_clusters >= ABSOLUTE_MINIMUM_CLUSTERS):
        raise ValueError("required_clusters_below_absolute_minimum")
    if len(names) < required_clusters or observed is None:
        return Comparison(observed, None, None, len(names), "insufficient-clusters")
    rng = random.Random(seed)
    differences = []
    for _ in range(replicates):
        sample_a, sample_b = [], []
        for draw in range(len(names)):
            members = clusters[names[rng.randrange(len(names))]]
            for slot in range(len(members)):
                chosen = members[rng.randrange(len(members))]
                copy = f"{chosen.track_id}#{draw}.{slot}"
                sample_a.append(replace(chosen, track_id=copy))
                sample_b.append(replace(by_id_b[chosen.track_id], track_id=copy))
        da, db = evaluate_tracks(sample_a, queries).d_score, evaluate_tracks(sample_b, queries).d_score
        if da is not None and db is not None:
            differences.append(da - db)
    differences.sort()
    lower = differences[int(0.025 * (len(differences) - 1))]
    upper = differences[int(math.ceil(0.975 * (len(differences) - 1)))]
    outcome = "superior" if lower > 0 and observed >= mpid else "not-superior"
    return Comparison(observed, lower, upper, len(names), outcome)


def baseline_gate(composition_d: float | None, baseline_d: float | None, mpid: float = MPID) -> str:
    """N2: a composition with detector PDx passes only if its D-score clears PDx + OC5 by at least the MPID."""
    if composition_d is None or baseline_d is None:
        return INSUFFICIENT
    return PASS if composition_d - baseline_d >= mpid else FAIL

