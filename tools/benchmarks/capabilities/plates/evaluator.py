"""Stage-4 model-selection evaluators A–D (plan §4.4), built on PR-3's merged plate rules.

These are the evaluators plan §7 assigned to PR-1 and PR-1 omitted. This module repairs that (register: *Correction and
repair record*). The owner decisions it encodes are written in
`docs/qualification/stage4/plate-selection-decision-record-2026-10-14.md`. It reads **no** dataset by itself: every
function takes in-memory ground truth and candidate outputs.

* **Product rules, not re-implementations.**
  - Track outcomes come from ``mavi_vision.plates.pipeline`` (``analyse_crop``, ``summarise_track``): the 2/1/3 bounds, proposal ordering, detector floor, reading order, ``Read``/``Unreadable``, abstention reasons and the ``plate-track-text-rank0`` summary.
  - Text is normalised only by the frozen ``mavi-plate-normalisation-v1``.
  - Confidence is reading-level.
  - B ranks readings with PR-3's public contract functions (``reading_rank_key``, ``raw_line_count``). A test proves the result equals PR-3's internal ``_plate``.
* **Any output-contract violation is a hard FAIL** (owner ruling, item 11). This is the BAKE-OFF rule. The product treats some of these per crop (for example a non-strict reading order is an ``ocr_output_invalid`` abstention), and the bake-off does not.
  - Harness validators wrap the candidate detector and recogniser. Any out-of-contract item, a raised exception, or over-bound output makes the run ``CONTRACT_FAIL`` across A, B, C and D. Out-of-contract items include:
    - a box that is not a ``PlateBox``, not integer, degenerate or outside the crop;
    - a score or confidence that is non-finite or outside [0, 1];
    - invalid raw text;
    - a non-strict reading order.
  - The exact evidence is kept: the code, the observation, the item and the exception type.
  - Nothing is scored through, truncated or treated as one bad Track.
  - A runtime exception is a FAIL under N9. The one permitted rerun, for a proven infrastructure fault with identical bytes, is a procedural decision outside this module.
* **Ranking provenance is sealed.** Ranking objects carry an HMAC seal under a per-process key. They are constructed only inside the ranking path: ``run_track``, ``ranking_plate_record`` / ``accepted_plate`` / ``not_read``, ``evaluate_detection``, ``evaluate_reading``, ``detector_component`` / ``recogniser_component`` and ``evaluate_tracks``.
  - **What is enforced:** any field edit of a sealed object (including its parameters or its component identity) breaks the seal and is refused. A hand-built object has no valid seal and is refused.
  - **What is not:** a caller with module access can still call the private ``_seal``. The seal protects against relabelling through the public API, not against a hostile in-process caller (P3-5, disclosed).
* **Composition identity is sealed** (review P1-1). ``run_track`` binds the detector and recogniser ``ComponentIdentity`` (candidate id + identity SHA-256) into the sealed run. ``evaluate_tracks`` requires every run to carry the stated identities and seals them into the ``TrackScore``. ``CompositionScore`` has no labels of its own: its ids come from the sealed score. The baseline gate checks the baseline score's sealed identities against the resolution's M3 ``compositionSha256``, and the benchmark-only refusal reads sealed identities. The identity values themselves are asserted once, at ``run_track``, by the harness that loaded the pinned bytes.
  - Diagnostics have distinct types (``DiagnosticPlate``, ``DiagnosticTrackScore``), which carry no seal. Every decision function refuses them: ``evaluate_reading``, ``top_k``, ``baseline_gate``, ``rankable_compositions``, the bootstrap and the comparison.
* **Candidate silence scores zero** (owner item 1). On a valid closed population, a composition returning nothing has D terms 0. ``INSUFFICIENT_EVIDENCE`` is reserved for corpus deficiency.
* **Baseline gate** (N2 revised, two-stage addendum): one hard gate against the sealed PD_BASE + OC5. Every consumer re-derives the resolution from the ``BaselineFreeze`` and the Layer-A results (``verify_resolution``).
* **Superiority** (owner item 2): observed ΔD ≥ MPID, the paired hierarchical 95 % interval excludes zero, and clusters ≥ ``required_clusters``. Exact rationals, integer percentile indices.
* **Query binding** (item 12): every D function regenerates the query set from its own truths, parameters and population, and checks it against the frozen generator-config and query-set SHA-256 arguments.

**Caller-provided values (labelled, not proven here; the protocol and review bind them):**
- the ``ComponentIdentity`` given to ``run_track`` (after that it is sealed and cannot be relabelled), to ``ranking_plate_record`` for B on GT crops, and to ``evaluate_reading`` / ``evaluate_detection``;
- the query-set SHA-256 arguments: checked against the regenerated set, but their frozen values come from the protocol;
- the bootstrap ``seed`` (a frozen protocol input; R is fixed at ``BOOTSTRAP_REPLICATES``);
- the frozen calibration minimum given to the comparison (``required_clusters`` = max(60, it) is computed here);
- ``TrackItem.cluster``: the site identity;
- ``TrackItem.truth``: the adjudicated ground truth;
- ``LayerAResult.gates_passed`` and ``identity_sha256``;
- the pinned detector floor passed to ``evaluate_detection`` / ``evaluate_tracks``. ``evaluate_tracks`` checks that every run used exactly that floor;
- ``ComponentScore.independent``: the N4 exposure verdict;
- ``resolve_baseline``'s ``d_rows_read``. The resolution time is format-checked and must not precede the freeze;
- ``DetectionItem`` built by hand, rather than with ``detection_item_from_run``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import random
import re
import secrets
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
    has_strict_rank_order,
    is_raw_text,
    raw_line_count,
    reading_rank_key,
)
from mavi_vision.plates.inference import PlateBox, PlateDetector, PlateRecogniser, Reading, VerifiedCrop
from mavi_vision.plates.normalisation import OK, normalise
from mavi_vision.plates.parameters import PlateParameters
from mavi_vision.plates.pipeline import (
    CropRecord,
    OutputInvalid,
    PlateRecord,
    RankedReading,
    TrackRecord,
    analyse_crop,
    summarise_track,
)

from tools.benchmarks.capabilities.plates import queries as query_module
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
ECE_BINS = 10                                 # proposed frozen value: equal-mass, item k of n in bin ⌊k·10/n⌋
CLUSTER_UNIT = "physical-capture-site"        # owner item 4 / C2
BOOTSTRAP_REPLICATES = 1000                   # frozen R (matches the predeclared calibration, owner T)

PASS, FAIL, INSUFFICIENT = "PASS", "FAIL", "INSUFFICIENT_EVIDENCE"
MEASURED, CONTRACT_FAIL = "MEASURED", "CONTRACT_FAIL"
NO_PLATE = "<no-plate>"            # real GT vehicle displaying no plate: truth = no text
UNREADABLE = "<unreadable>"        # real GT vehicle, text not establishable by the frozen human rule
NO_GT_VEHICLE = "<no-gt-vehicle>"  # MAVI Track matching no GT vehicle in the closed population: a false Track

_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_CANDIDATE_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*$")
_EVENT_RE = re.compile(r"^msr-[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?-\d{4}-\d{2}$")


@dataclass(frozen=True, slots=True)
class ComponentIdentity:
    """A candidate component as the ranking path saw it. ``identity_sha256`` is M3's ``identitySha256``: the canonical
    SHA-256 of the candidate's ledger ``identity`` block. For the benchmark-only component it is M3's benchmark
    component identity."""

    candidate_id: str
    identity_sha256: str

    def __post_init__(self):
        if not (isinstance(self.candidate_id, str) and _CANDIDATE_RE.match(self.candidate_id)):
            raise ValueError("component_identity_id_malformed")
        if not (isinstance(self.identity_sha256, str) and re.fullmatch(r"[0-9a-f]{64}", self.identity_sha256)):
            raise ValueError("component_identity_sha256_malformed")


def _identity(value: object, code: str) -> ComponentIdentity:
    if not isinstance(value, ComponentIdentity):
        raise ValueError(code)
    return value

# ---------------------------------------------------------------------------------------------- ranking seals

_SEAL_KEY = secrets.token_bytes(32)
_RUN, _PLATE, _A, _B, _COMPONENT, _D = "run", "plate", "detection", "reading", "component", "d-score"


def _mac(kind: str, obj) -> str:
    body = repr(replace(obj, seal=""))
    return hmac.new(_SEAL_KEY, f"{kind}\x00{body}".encode("utf-8"), hashlib.sha256).hexdigest()


def _seal(kind: str, obj):
    """Ranking-path constructor only. Tests use it to build fixtures; it is not an API."""
    return replace(obj, seal=_mac(kind, replace(obj, seal="")))


def _is_sealed(kind: str, obj) -> bool:
    return isinstance(getattr(obj, "seal", None), str) and hmac.compare_digest(obj.seal, _mac(kind, obj))


def _require(kind: str, obj, code: str) -> None:
    if not _is_sealed(kind, obj):
        raise ValueError(code)


def _probability(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1


def _integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def ranking_parameters(detector_confidence_floor: float) -> PlateParameters:
    """The only parameters the ranking path accepts: 2/1/3 bounds, OCR floor 0, the candidate's pinned detector floor."""
    return PlateParameters(MAXIMUM_DETECTIONS_PER_CROP, MAXIMUM_PLATES_PER_CROP, MAXIMUM_READINGS_PER_PLATE,
                           float(detector_confidence_floor), RANKING_OCR_CONFIDENCE_FLOOR, frozenset(), None)


def is_ranking_profile(parameters: PlateParameters, detector_floor: float | None = None) -> bool:
    """The ranking profile; with ``detector_floor``, also exactly the candidate's pinned detector floor."""
    return (parameters.max_detections_per_crop == MAXIMUM_DETECTIONS_PER_CROP
            and parameters.max_plates_per_crop == MAXIMUM_PLATES_PER_CROP
            and parameters.max_readings_per_plate == MAXIMUM_READINGS_PER_PLATE
            and parameters.ocr_confidence_floor == RANKING_OCR_CONFIDENCE_FLOOR
            and not parameters.excluded_roles
            and (detector_floor is None or parameters.detector_confidence_floor == float(detector_floor)))


def normalised_truth(raw: str) -> str | None:
    result = normalise(raw)
    return result.normalised if result.outcome == OK else None


def _ratio(numerator: int, denominator: int) -> Fraction | None:
    return Fraction(numerator, denominator) if denominator else None


# ---------------------------------------------------------------------------------------------- output contract


def detector_output_violation(boxes: object, width: int, height: int, bound: int) -> str | None:
    """The bake-off detector contract: a list of at most ``bound`` integer ``PlateBox`` inside the crop, score in [0, 1]."""
    if not isinstance(boxes, (list, tuple)):
        return "plate_detector_output_invalid@not_a_list"
    if len(boxes) > bound:
        return f"plate_detector_output_exceeds_bound@count={len(boxes)}"
    for index, box in enumerate(boxes):
        if not isinstance(box, PlateBox):
            return f"plate_detector_output_invalid@item={index}:not_a_platebox"
        if not all(_integer(v) for v in (box.x, box.y, box.width, box.height)):
            return f"plate_detector_output_invalid@item={index}:box_not_integer"
        if not _probability(box.score):
            return f"plate_detector_output_invalid@item={index}:score_out_of_range"
        if box.x < 0 or box.y < 0 or box.width < 1 or box.height < 1:
            return f"plate_detector_output_invalid@item={index}:box_degenerate"
        if box.x + box.width > width or box.y + box.height > height:
            return f"plate_detector_output_invalid@item={index}:box_outside_crop"
    return None


def recogniser_output_violation(readings: object, bound: int) -> str | None:
    """The bake-off recogniser contract: at most ``bound`` ``Reading`` with valid raw text, confidence in [0, 1] and a
    strict rank order. In the PRODUCT a non-strict order is a crop abstention; in the BAKE-OFF it is a FAIL."""
    if not isinstance(readings, (list, tuple)):
        return "plate_recogniser_output_invalid@not_a_list"
    if len(readings) > bound:
        return f"plate_recogniser_output_exceeds_bound@count={len(readings)}"
    for index, reading in enumerate(readings):
        if not isinstance(reading, Reading):
            return f"plate_recogniser_output_invalid@item={index}:not_a_reading"
        if not is_raw_text(reading.raw_text):
            return f"plate_recogniser_output_invalid@item={index}:invalid_raw_text"
        if not _probability(reading.confidence):
            return f"plate_recogniser_output_invalid@item={index}:confidence_out_of_range"
    if not has_strict_rank_order(list(readings)):
        return "plate_recogniser_output_invalid@non_strict_rank_order"
    return None


class _Guard:
    __slots__ = ("violation",)

    def __init__(self) -> None:
        self.violation: str | None = None

    def flag(self, text: str) -> None:
        if self.violation is None:
            self.violation = text


def _exception_evidence(exc: BaseException) -> str:
    return f"{type(exc).__name__}:{str(exc)[:160]}"


class _CheckedDetector:
    """Harness validator: records the first contract violation, then lets PR-3 behave exactly as in the product."""

    def __init__(self, inner: PlateDetector, guard: _Guard, bound: int) -> None:
        self.inner, self.guard, self.bound = inner, guard, bound

    def detect(self, crop, verified: VerifiedCrop):
        where = f"obs={verified.observation_id}"
        try:
            boxes = self.inner.detect(crop, verified)
        except Exception as exc:  # noqa: BLE001 - recorded as a FAIL, then re-raised for PR-3's own handling
            self.guard.flag(f"plate_detector_runtime_error@{where}:{_exception_evidence(exc)}")
            raise
        width, height = crop.size
        violation = detector_output_violation(boxes, width, height, self.bound)
        if violation is not None:
            self.guard.flag(f"{violation}:{where}")
        return boxes


class _CheckedRecogniser:
    def __init__(self, inner: PlateRecogniser, guard: _Guard, bound: int) -> None:
        self.inner, self.guard, self.bound = inner, guard, bound

    def read(self, region, verified: VerifiedCrop, box: PlateBox):
        where = f"obs={verified.observation_id}"
        try:
            readings = self.inner.read(region, verified, box)
        except Exception as exc:  # noqa: BLE001
            self.guard.flag(f"plate_recogniser_runtime_error@{where}:{_exception_evidence(exc)}")
            raise
        violation = recogniser_output_violation(readings, self.bound)
        if violation is not None:
            self.guard.flag(f"{violation}:{where}")
        return readings


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
    """A Track's PR-3 outcome under ``parameters``, or the exact contract violation (kept for audit, never scored).
    Only ``run_track`` produces a sealed run."""

    record: TrackRecord | None
    contract_violation: str | None
    parameters: PlateParameters
    detector: ComponentIdentity | None = None
    recogniser: ComponentIdentity | None = None
    seal: str = ""


def lease_observation(observation_id: UUID, role: str, evidence_rank: int, size_bytes: int, sha256: str
                      ) -> LeaseObservation:
    return LeaseObservation.model_validate({"observationId": observation_id, "role": role,
                                            "evidenceRank": evidence_rank, "sizeBytes": size_bytes, "sha256": sha256})


def lease_track(track_id: UUID, observations: tuple[LeaseObservation, ...]) -> LeaseTrack:
    return LeaseTrack.model_validate({"trackId": track_id, "objectClass": "vehicle", "observations": observations})


def run_track(track_id: UUID, crops: Sequence[EvidenceCrop], detector: PlateDetector, recogniser: PlateRecogniser,
              parameters: PlateParameters, *, detector_identity: ComponentIdentity,
              recogniser_identity: ComponentIdentity) -> TrackRun:
    """Run PR-3 on one Track with the guarded candidate components. The stated identities are sealed into the run."""
    ids = (_identity(detector_identity, "run_detector_identity_required"),
           _identity(recogniser_identity, "run_recogniser_identity_required"))
    observations = tuple(lease_observation(c.observation_id, c.role, c.evidence_rank, len(c.content), c.sha256)
                         for c in crops)
    track = lease_track(track_id, observations)
    guard = _Guard()
    checked_detector = _CheckedDetector(detector, guard, parameters.max_detections_per_crop)
    checked_recogniser = _CheckedRecogniser(recogniser, guard, parameters.max_readings_per_plate)
    records = []
    for crop, observation in zip(crops, observations):
        verified = VerifiedCrop(str(crop.observation_id), crop.role, crop.evidence_rank, crop.sha256, crop.content)
        try:
            record = analyse_crop(observation, verified, checked_detector, checked_recogniser, parameters)
        except OutputInvalid as exc:
            return _seal(_RUN, TrackRun(None, guard.violation or str(exc), parameters, *ids))
        if guard.violation is not None:
            return _seal(_RUN, TrackRun(None, guard.violation, parameters, *ids))
        records.append(record)
    try:
        summary = summarise_track(track, tuple(records))
    except OutputInvalid as exc:
        return _seal(_RUN, TrackRun(None, str(exc), parameters, *ids))
    return _seal(_RUN, TrackRun(summary, None, parameters, *ids))


def _require_run(run: TrackRun, code: str) -> None:
    if not isinstance(run, TrackRun):
        raise ValueError(code)
    _require(_RUN, run, code)


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


def _polygon_area(points: Sequence[tuple[Fraction, Fraction]]) -> Fraction:
    return abs(sum((x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, list(points[1:]) + [points[0]])),
                   Fraction(0))) / 2


def _clip(points: list, inside: Callable, cut: Callable) -> list:
    out: list = []
    for index, current in enumerate(points):
        previous = points[index - 1]
        if inside(current):
            if not inside(previous):
                out.append(cut(previous, current))
            out.append(current)
        elif inside(previous):
            out.append(cut(previous, current))
    return out


def coverage(polygon: Sequence[tuple[float, float]], box: tuple[float, float, float, float]) -> Fraction:
    """Exact share of the GT polygon's area inside the box ``(x1, y1, x2, y2)`` (Sutherland–Hodgman over rationals;
    every float coordinate is converted exactly, so a 95/100 share compares equal to the 0.95 threshold)."""
    points = [(Fraction(x), Fraction(y)) for x, y in polygon]
    area = _polygon_area(points)
    if area <= 0:
        return Fraction(0)
    x1, y1, x2, y2 = (Fraction(v) for v in box)

    def at_x(xv):
        return lambda p, q: (xv, p[1] + (q[1] - p[1]) * (xv - p[0]) / (q[0] - p[0]))

    def at_y(yv):
        return lambda p, q: (p[0] + (q[0] - p[0]) * (yv - p[1]) / (q[1] - p[1]), yv)

    for inside, cut in ((lambda p: p[0] >= x1, at_x(x1)), (lambda p: p[0] <= x2, at_x(x2)),
                        (lambda p: p[1] >= y1, at_y(y1)), (lambda p: p[1] <= y2, at_y(y2))):
        points = _clip(points, inside, cut)
        if not points:
            return Fraction(0)
    return min(Fraction(1), _polygon_area(points) / area)


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    w = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - w * h
    return w * h / union if union > 0 else 0.0


@dataclass(frozen=True, slots=True)
class DetectionItem:
    """One GT vehicle crop: GT plate polygons and the detector's proposals ``(x, y, w, h, score)`` as emitted.
    ``crop_size`` enables the inside-the-crop check; ``contract_violation`` carries a failed run's evidence."""

    crop_id: str
    plates: tuple[tuple[tuple[float, float], ...], ...]
    proposals: tuple[tuple[int, int, int, int, float], ...]
    stratum: str | None = None
    crop_size: tuple[int, int] | None = None   # required unless ``contract_violation`` is set (review P3-2)
    contract_violation: str | None = None
    detector: ComponentIdentity | None = None  # set by ``detection_item_from_run`` from the sealed run


def detection_item_from_run(crop_id: str, plates, run: TrackRun, observation_id: UUID,
                            stratum: str | None = None) -> DetectionItem:
    """A from a sealed ranking-path run: the crop's emitted proposals, or the run's contract violation."""
    _require_run(run, "a_run_not_from_ranking_path")
    if run.contract_violation is not None or run.record is None:
        return DetectionItem(crop_id, tuple(plates), (), stratum, None, run.contract_violation or "run_without_record",
                             run.detector)
    crop = next((c for c in run.record.crops if c.observation_id == observation_id), None)
    if crop is None:
        raise ValueError("a_observation_not_in_run")
    proposals = tuple((*d.box, d.score) for d in crop.detections) if crop.status in (CROP_SCORED, CROP_ABSTAINED) else ()
    size = (crop.width, crop.height) if crop.width is not None and crop.height is not None else None
    return DetectionItem(crop_id, tuple(plates), proposals, stratum, size, None, run.detector)


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
    detector: ComponentIdentity | None = None
    seal: str = ""


def _proposal_violation(item: DetectionItem) -> str | None:
    if item.contract_violation is not None:
        return item.contract_violation
    if len(item.proposals) > MAXIMUM_DETECTIONS_PER_CROP:
        return "plate_detector_output_exceeds_bound"
    for index, p in enumerate(item.proposals):
        if not (isinstance(p, tuple) and len(p) == 5):
            return f"plate_detector_output_invalid@item={index}:not_a_proposal"
        x, y, w, h, score = p
        if not all(_integer(v) for v in (x, y, w, h)):
            return f"plate_detector_output_invalid@item={index}:box_not_integer"
        if not _probability(score):
            return f"plate_detector_output_invalid@item={index}:score_out_of_range"
        if x < 0 or y < 0 or w < 1 or h < 1:
            return f"plate_detector_output_invalid@item={index}:box_degenerate"
        if item.crop_size is not None and (x + w > item.crop_size[0] or y + h > item.crop_size[1]):
            return f"plate_detector_output_invalid@item={index}:box_outside_crop"
    return None


def evaluate_detection(items: Iterable[DetectionItem], detector_floor: float, *,
                       detector: ComponentIdentity) -> DetectionResult:
    """A. Any detector output-contract violation is a FAIL for the evaluation (owner item 11), including more than
    ``MAXIMUM_DETECTIONS_PER_CROP`` proposals, a non-finite score or a malformed box. Nothing is scored, truncated or
    re-selected. Valid proposals below the pinned detector floor are not counted (PR-3 cannot accept them) and are
    reported."""
    detector = _identity(detector, "a_detector_identity_required")
    items = list(items)
    for item in items:
        if item.contract_violation is None and item.crop_size is None:
            raise ValueError("a_item_without_crop_size")  # the outside-crop check can never be skipped
        if item.detector is not None and item.detector != detector:
            raise ValueError("a_item_from_another_detector")
    violations = tuple(f"{v}:{i.crop_id}" for i in items if (v := _proposal_violation(i)) is not None)
    if violations:
        return _seal(_A, DetectionResult(CONTRACT_FAIL, violations, 0, 0, None, None, None, 0, {}, detector))
    plates = covered = false = below = 0
    strata: dict[str, list[int]] = {}
    scored: list[tuple[float, str, int, bool]] = []
    for item in items:
        kept = [p for p in item.proposals if p[4] >= detector_floor]
        below += len(item.proposals) - len(kept)
        boxes = [(x, y, x + w, y + h) for x, y, w, h, _ in kept]
        hit = sum(1 for polygon in item.plates if any(coverage(polygon, b) >= PLAN_COVERAGE_THRESHOLD for b in boxes))
        plates += len(item.plates)
        covered += hit
        if item.stratum is not None:
            bucket = strata.setdefault(item.stratum, [0, 0])
            bucket[0] += len(item.plates)
            bucket[1] += hit
        false += sum(1 for b in boxes if not any(coverage(p, b) >= PLAN_COVERAGE_THRESHOLD for p in item.plates))
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
    return _seal(_A, DetectionResult(MEASURED, (), plates, covered, _ratio(covered, plates), _ratio(false, len(items)),
                                     ap, below, per_stratum, detector))


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
    """A PR-3 ``PlateRecord`` on the ranking profile (OCR floor 0), or the contract violation. Sealed by the ranking
    path only (``ranking_plate_record``, ``accepted_plate``, ``not_read``)."""

    plate: PlateRecord | None
    contract_violation: str | None = None
    recogniser: ComponentIdentity | None = None
    seal: str = ""


@dataclass(frozen=True, slots=True)
class DiagnosticPlate:
    """DIAGNOSTIC ONLY: a plate record at a diagnostic floor. Refused by every ranking path."""

    plate: PlateRecord | None
    floor: float
    contract_violation: str | None = None


def _rank_plate(readings: Sequence[Reading], parameters: PlateParameters) -> PlateRecord:
    """PR-3's ranking through its public contract (equal to ``pipeline._plate``, proven by test)."""
    ordered = sorted(readings, key=lambda item: reading_rank_key(item.confidence, item.raw_text))
    ranked = tuple(RankedReading(rank, item.raw_text, raw_line_count(item.raw_text), float(item.confidence))
                   for rank, item in enumerate(ordered))
    outcome = PLATE_READ if ranked and ranked[0].confidence >= parameters.ocr_confidence_floor else PLATE_UNREADABLE
    return PlateRecord(0, outcome, ranked)


def _plate_record(readings, parameters: PlateParameters) -> tuple[PlateRecord | None, str | None]:
    violation = recogniser_output_violation(readings, parameters.max_readings_per_plate)
    if violation is not None:
        return None, violation
    return _rank_plate(list(readings), parameters), None


def ranking_plate_record(readings, *, recogniser: ComponentIdentity) -> RankingPlate:
    """B on GT plate crops, ranked as PR-3 does, at the ranking floor 0. Any contract violation is a FAIL."""
    recogniser = _identity(recogniser, "b_recogniser_identity_required")
    plate, violation = _plate_record(readings, ranking_parameters(0.0))
    return _seal(_PLATE, RankingPlate(plate, violation, recogniser))


def not_read() -> RankingPlate:
    """A GT plate the composition did not read (no plate reached B/C): scored as not read."""
    return _seal(_PLATE, RankingPlate(None))


def diagnostic_plate_record(readings, floor: float) -> DiagnosticPlate:
    if floor not in DIAGNOSTIC_OCR_FLOORS:
        raise ValueError("diagnostic_floor_not_declared")
    parameters = replace(ranking_parameters(0.0), ocr_confidence_floor=floor)
    plate, violation = _plate_record(readings, parameters)
    return DiagnosticPlate(plate, floor, violation)


@dataclass(frozen=True, slots=True)
class ReadItem:
    """One GT plate (raw truth) and the composition's ranking-profile plate for it."""

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
    recogniser: ComponentIdentity | None = None
    seal: str = ""


def _ece(ranked: Sequence[tuple[float, bool, str]]) -> float | None:
    """Equal-mass ECE: over the total order (confidence descending, then plate id), item k of n goes to bin
    ⌊k·ECE_BINS/n⌋, so bin sizes differ by at most one; empty bins are skipped."""
    n = len(ranked)
    if not n:
        return None
    bins: dict[int, list[tuple[float, bool, str]]] = {}
    for k, row in enumerate(ranked):
        bins.setdefault(k * ECE_BINS // n, []).append(row)
    return sum(len(chunk) / n * abs(sum(c for c, _, _ in chunk) / len(chunk) - sum(e for _, e, _ in chunk) / len(chunk))
               for chunk in bins.values())


def evaluate_reading(items: Iterable[ReadItem], *, recogniser: ComponentIdentity) -> ReadResult:
    """B/C: EM of the rank-0 reading of a ``Read`` plate. Plate ids are unique, so the ECE order is total and input
    order cannot matter (owner item 16)."""
    recogniser = _identity(recogniser, "b_recogniser_identity_required")
    items = list(items)
    for item in items:
        if not isinstance(item.result, RankingPlate) or not _is_sealed(_PLATE, item.result):
            raise ValueError("reading_not_on_ranking_profile")
        if item.result.recogniser is not None and item.result.recogniser != recogniser:
            raise ValueError("reading_from_another_recogniser")
    ids = [i.plate_id for i in items]
    if len(ids) != len(set(ids)):
        raise ValueError("reading_duplicate_plate_id")
    violations = tuple(f"{i.result.contract_violation}:{i.plate_id}" for i in items if i.result.contract_violation)
    if violations:
        return _seal(_B, ReadResult(CONTRACT_FAIL, violations, 0, 0, None, None, None, None, (), 0, {}, recogniser))
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
    return _seal(_B, ReadResult(MEASURED, (), n, exact, _ratio(exact, n), sum(r[2] for r in rows) / n if n else None,
                                _ece(ranked), _ratio(sum(r[4] for r in rows), n), tuple(curve), unsupported, per_stratum,
                                recogniser))


def c_minus_b(c: ReadResult, b: ReadResult) -> Fraction | None:
    """Diagnostic only: the detector-attributable EM loss (C − B) on the same plates."""
    return None if c.em is None or b.em is None else c.em - b.em


def accepted_plate(run: TrackRun, observation_id: UUID) -> RankingPlate:
    """C: the composition's own accepted plate in a crop of a sealed ranking-profile run (PR-3 selection)."""
    _require_run(run, "c_run_not_from_ranking_path")
    if not is_ranking_profile(run.parameters):
        raise ValueError("c_run_not_on_ranking_profile")
    if run.contract_violation is not None or run.record is None:
        return _seal(_PLATE, RankingPlate(None, run.contract_violation or "run_without_record", run.recogniser))
    crop = next((c for c in run.record.crops if c.observation_id == observation_id), None)
    if crop is None:
        raise ValueError("c_observation_not_in_run")
    if crop.status != CROP_SCORED:
        return _seal(_PLATE, RankingPlate(None, None, run.recogniser))
    return _seal(_PLATE, RankingPlate(next((plate for _, plate in crop.plates()), None), None, run.recogniser))


# ---------------------------------------------------------------------------------------------- top-K (N4)


@dataclass(frozen=True, slots=True)
class ComponentScore:
    candidate_id: str
    independent: bool              # caller-provided N4 verdict: demonstrably independent qualifying release
    support: int
    primary: float | None          # A: recall at coverage; B: EM
    second: float | None           # A: false plates per crop (lower better); B: CER (lower better)
    third: float | None            # A: AP50 (higher better); B: ECE (lower better)
    contract_fail: bool = False
    identity_sha256: str = ""      # the sealed component identity the result was produced under
    seal: str = ""


def _float(value) -> float | None:
    return None if value is None else float(value)


def detector_component(independent: bool, result: DetectionResult) -> ComponentScore:
    """The candidate id and identity come from the sealed result, never from a caller label (review P3-1)."""
    _require(_A, result, "component_detection_result_not_from_ranking_path")
    who = result.detector
    return _seal(_COMPONENT, ComponentScore(who.candidate_id, bool(independent), result.plates, _float(result.recall),
                                            _float(result.false_plates_per_crop), result.ap50,
                                            result.outcome == CONTRACT_FAIL, who.identity_sha256))


def recogniser_component(independent: bool, result: ReadResult) -> ComponentScore:
    _require(_B, result, "component_read_result_not_from_ranking_path")
    who = result.recogniser
    return _seal(_COMPONENT, ComponentScore(who.candidate_id, bool(independent), result.plates, _float(result.em),
                                            result.cer, result.ece, result.outcome == CONTRACT_FAIL,
                                            who.identity_sha256))


def top_k(scores: Iterable[ComponentScore], k: int, minimum_support: int, kind: str, *,
          benchmark_only: Iterable[str]) -> list[str]:
    """N4 tie-breaks. Missing metrics sort last; contract-failed or non-independent components never enter.

    ``benchmark_only`` (required, non-empty) names the frozen benchmark-only components (M3; OC5). One of them among
    the scores is refused outright. Every score must come from the ranking path."""
    if kind not in ("detector", "recogniser"):
        raise ValueError("top_k_kind")
    benchmark_only = frozenset(benchmark_only)
    if not benchmark_only or not all(isinstance(b, str) and b for b in benchmark_only):
        raise ValueError("top_k_requires_the_frozen_benchmark_only_ids")
    scores = list(scores)
    for s in scores:
        _require(_COMPONENT, s, "top_k_score_not_from_ranking_path")
    if {s.candidate_id for s in scores} & benchmark_only:
        raise ValueError("benchmark_only_component_cannot_enter_top_k")

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
    no MAVI Track or no evidence: not read, still in every denominator. ``cluster`` and ``truth`` are caller-provided.
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
    """A ranking-path D result. Sealed only by ``evaluate_tracks``, and bound to its population and query set."""

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
    population_manifest_sha256: str = ""
    generator_config_sha256: str = ""
    query_set_sha256: str = ""
    detector: ComponentIdentity | None = None
    recogniser: ComponentIdentity | None = None
    seal: str = ""


@dataclass(frozen=True, slots=True)
class DiagnosticTrackScore:
    """DIAGNOSTIC ONLY (D6): D at a declared diagnostic OCR floor. A distinct, unsealed type that every gate,
    comparison and ranking function refuses."""

    floor: float
    values: TrackScore


@dataclass(frozen=True, slots=True)
class _Prepared:
    track_id: str
    cluster: str
    kind: str          # "plate" | "no-plate" | "no-gt-vehicle" | "unsupported" | "unreadable"
    truth: str | None
    run: TrackRun | None


def _verify_queries(queries: QuerySet, population_manifest_sha256: str, generator_config_sha256: str,
                    query_set_sha256: str) -> None:
    """Item 12: the query set is regenerated from its own truths and parameters, and must equal itself and the frozen
    SHA-256 arguments. A self-declared hash is never trusted."""
    if queries.population_manifest_sha256 != population_manifest_sha256:
        raise ValueError("d_queries_bound_to_another_population")
    query_module.verify(queries)
    if queries.generator_config_sha256 != generator_config_sha256:
        raise ValueError("d_queries_generator_config_not_frozen")
    if queries.query_set_sha256 != query_set_sha256:
        raise ValueError("d_query_set_not_frozen")


def _prepare(items: Sequence[TrackItem], queries: QuerySet, detector_floor: float, detector: ComponentIdentity,
             recogniser: ComponentIdentity) -> tuple[list[_Prepared], dict]:
    _identity(detector, "d_detector_identity_required")
    _identity(recogniser, "d_recogniser_identity_required")
    seen: set[str] = set()
    prepared = []
    accounting = {"text": 0, "unsupported": 0, "unqueryable": 0, "no-plate": 0, "unreadable": 0, "no-gt-vehicle": 0}
    for item in items:
        if not isinstance(item.truth, str) or not item.truth.strip():
            raise ValueError("d_truth_empty_or_missing")
        if item.track_id in seen:
            raise ValueError("d_population_duplicate_track")
        seen.add(item.track_id)
        if item.run is not None:
            _require_run(item.run, "d_run_not_from_ranking_path")
            if not is_ranking_profile(item.run.parameters):
                raise ValueError("d_run_not_on_ranking_profile")
            if not is_ranking_profile(item.run.parameters, detector_floor):
                raise ValueError("d_run_not_at_the_pinned_detector_floor")
            if (item.run.detector, item.run.recogniser) != (detector, recogniser):
                raise ValueError("d_run_identity_is_not_the_composition")
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
    if not any(p.run is not None for p in prepared):
        raise ValueError("d_population_without_any_run")  # the composition identity must come from a sealed run
    return prepared, accounting


def _texts(run: TrackRun | None) -> tuple[str, ...]:
    if run is None or run.record is None or run.record.outcome != TRACK_ANALYSED:
        return ()
    return tuple(text.normalised_text for text in run.record.texts)


def _rank0_sources(run: TrackRun | None) -> list[tuple[UUID, str]]:
    """N3 (owner decision 2026-10-14): one entry per Read plate observation, holding its RANK-0 reading normalised by
    v1. Lower ranks never trigger or rescue N3. A plate with no Read result, or a rank-0 that does not normalise,
    gives no support. Runs reach here only contract-valid; a violating run is CONTRACT_FAIL before N3."""
    if run is None or run.record is None or run.contract_violation is not None:
        return []
    out = []
    for crop in run.record.crops:
        for _, plate in crop.plates():
            if plate.outcome == PLATE_READ and plate.readings:
                text = normalised_truth(plate.readings[0].raw_text)
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
        # N3: eligible with valid rank-0 texts from ≥ 2 distinct observations; consistent-wrong iff ALL of them are
        # one text and it is not the truth (so no rank-0 equals the truth). No subset of observations is chosen.
        readings = _rank0_sources(p.run)
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


def evaluate_tracks(items: Sequence[TrackItem], queries: QuerySet, *, population_manifest_sha256: str,
                    generator_config_sha256: str, query_set_sha256: str, detector_floor: float,
                    detector: ComponentIdentity, recogniser: ComponentIdentity) -> TrackScore:
    """D on the ranking profile only, at the candidate's pinned detector floor, on the frozen query set, for exactly the
    composition whose sealed runs these are. Any contract violation makes the composition CONTRACT_FAIL."""
    _verify_queries(queries, population_manifest_sha256, generator_config_sha256, query_set_sha256)
    prepared, accounting = _prepare(items, queries, detector_floor, detector, recogniser)
    score = replace(_score(prepared, queries, accounting), population_manifest_sha256=population_manifest_sha256,
                    generator_config_sha256=generator_config_sha256, query_set_sha256=query_set_sha256,
                    detector=detector, recogniser=recogniser)
    return _seal(_D, score)


def diagnostic_evaluate_at_floor(items: Sequence[TrackItem], queries: QuerySet, floor: float, *,
                                 population_manifest_sha256: str, generator_config_sha256: str,
                                 query_set_sha256: str, detector_floor: float, detector: ComponentIdentity,
                                 recogniser: ComponentIdentity) -> DiagnosticTrackScore:
    """DIAGNOSTIC ONLY (D6): D as PR-3 would publish it at another OCR floor. The result is a ``DiagnosticTrackScore``,
    which no gate, comparison or ranking function accepts."""
    if floor not in DIAGNOSTIC_OCR_FLOORS:
        raise ValueError("diagnostic_floor_not_declared")
    _verify_queries(queries, population_manifest_sha256, generator_config_sha256, query_set_sha256)
    prepared, accounting = _prepare(items, queries, detector_floor, detector, recogniser)
    refloored = []
    for p in prepared:
        run = p.run
        if run is not None and run.record is not None:
            run = TrackRun(_refloor(run.record, floor), None, replace(run.parameters, ocr_confidence_floor=floor))
        refloored.append(replace(p, run=run))
    score = _score(refloored, queries, accounting)
    return DiagnosticTrackScore(floor, replace(score, accounting={**score.accounting, "diagnosticFloor": floor}))


def _require_d(score: object, code: str) -> TrackScore:
    if isinstance(score, DiagnosticTrackScore) or not isinstance(score, TrackScore) or not _is_sealed(_D, score):
        raise ValueError(code)
    return score


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


def _frozen_mpid(mpid: object) -> Fraction:
    if not isinstance(mpid, Fraction) or mpid != MPID:
        raise ValueError("mpid_must_be_the_frozen_fraction")
    return mpid


def percentile_indices(replicates: int) -> tuple[int, int]:
    """⌊0.025·(R−1)⌋ and ⌈0.975·(R−1)⌉ in integer arithmetic (no float rounding)."""
    return (25 * (replicates - 1)) // 1000, -((-975 * (replicates - 1)) // 1000)


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


def _bootstrap_replicates(items_a, items_b, queries, *, replicates: int, seed: int, population_manifest_sha256: str,
                          generator_config_sha256: str, query_set_sha256: str, detector_floor_a: float,
                          detector_floor_b: float, composition_a: tuple[ComponentIdentity, ComponentIdentity],
                          composition_b: tuple[ComponentIdentity, ComponentIdentity],
                          slow: bool = False) -> list[Fraction | None]:
    """PRIVATE. Exact ΔD per replicate (sites with replacement, then Tracks within each drawn site). ``slow=True``
    re-evaluates every resampled population from the Tracks; the fast path sums precomputed per-Track counts. Tests
    prove the two are identical. A contract-violating run is refused, never resampled as silence (review P2-3)."""
    if not (isinstance(replicates, int) and not isinstance(replicates, bool) and replicates >= 1):
        raise ValueError("bootstrap_replicates_invalid")
    _pairing(items_a, items_b)
    _verify_queries(queries, population_manifest_sha256, generator_config_sha256, query_set_sha256)
    pa, _ = _prepare(items_a, queries, detector_floor_a, *composition_a)
    pb, _ = _prepare(items_b, queries, detector_floor_b, *composition_b)
    if any(p.run is not None and p.run.contract_violation is not None for p in (*pa, *pb)):
        raise ValueError("bootstrap_refuses_a_contract_violating_run")
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


def required_clusters(calibration_minimum: int) -> int:
    """Owner D7b / P-80: ``required_clusters`` = max(60, the frozen candidate-blind calibration minimum). The minimum
    is a frozen protocol input. Under owner rule T it is currently PENDING (the calibration STOPPED), so no value is
    encoded here."""
    if not (isinstance(calibration_minimum, int) and not isinstance(calibration_minimum, bool)
            and calibration_minimum >= 1):
        raise ValueError("calibration_minimum_invalid")
    return max(ABSOLUTE_MINIMUM_CLUSTERS, calibration_minimum)


def paired_cluster_bootstrap(items_a: Sequence[TrackItem], items_b: Sequence[TrackItem], queries: QuerySet, *,
                             seed: int, calibration_minimum_clusters: int, population_manifest_sha256: str,
                             generator_config_sha256: str, query_set_sha256: str, detector_floor_a: float,
                             detector_floor_b: float, composition_a: tuple[ComponentIdentity, ComponentIdentity],
                             composition_b: tuple[ComponentIdentity, ComponentIdentity], freeze: "BaselineFreeze",
                             replicates: int = BOOTSTRAP_REPLICATES, cluster_unit: str = CLUSTER_UNIT,
                             mpid: Fraction = MPID) -> Comparison:
    """The frozen superiority rule (owner item 2): ``superior`` iff
    - observed ΔD ≥ MPID (exact);
    - the paired hierarchical 95 % percentile interval excludes zero in A's favour (lower bound > 0, exact);
    - clusters ≥ ``required_clusters`` = max(60, the frozen calibration minimum).

    R is fixed at ``BOOTSTRAP_REPLICATES``; any other value is refused. ``seed`` is a frozen protocol input. Both
    compositions must be ordinary: one carrying the benchmark-only component (by sealed identity) is refused."""
    mpid = _frozen_mpid(mpid)
    if cluster_unit != CLUSTER_UNIT:
        raise ValueError("cluster_unit_must_be_physical_capture_site")
    needed = required_clusters(calibration_minimum_clusters)
    if replicates != BOOTSTRAP_REPLICATES or isinstance(replicates, bool):
        raise ValueError("bootstrap_replicates_must_be_the_frozen_value")
    if not (isinstance(seed, int) and not isinstance(seed, bool)):
        raise ValueError("bootstrap_seed_invalid")
    _pairing(items_a, items_b)
    binding = dict(population_manifest_sha256=population_manifest_sha256,
                   generator_config_sha256=generator_config_sha256, query_set_sha256=query_set_sha256)
    a = evaluate_tracks(items_a, queries, detector_floor=detector_floor_a, detector=composition_a[0],
                        recogniser=composition_a[1], **binding)
    b = evaluate_tracks(items_b, queries, detector_floor=detector_floor_b, detector=composition_b[0],
                        recogniser=composition_b[1], **binding)
    _refuse_benchmark_only(a, freeze)
    _refuse_benchmark_only(b, freeze)
    clusters = sorted({i.cluster for i in items_a})
    per_cluster, signs = {}, {"a": 0, "b": 0, "tie": 0, "insufficient": 0}

    def result(outcome, difference=None, lower=None, upper=None, insufficient=0):
        return Comparison(outcome, difference, lower, upper, len(clusters), needed, cluster_unit,
                          insufficient, signs, per_cluster)

    if a.outcome == CONTRACT_FAIL or b.outcome == CONTRACT_FAIL:
        return result("contract-fail")
    if a.d_score is None or b.d_score is None:
        return result("insufficient-evidence")
    pa, _ = _prepare(items_a, queries, detector_floor_a, *composition_a)
    pb, _ = _prepare(items_b, queries, detector_floor_b, *composition_b)
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
    if len(clusters) < needed:
        return result("insufficient-clusters", observed)
    values = _bootstrap_replicates(items_a, items_b, queries, replicates=replicates, seed=seed,
                                   detector_floor_a=detector_floor_a, detector_floor_b=detector_floor_b,
                                   composition_a=composition_a, composition_b=composition_b, **binding)
    insufficient = sum(v is None for v in values)
    if insufficient:
        return result("insufficient-evidence", observed, insufficient=insufficient)
    values.sort()
    low_index, high_index = percentile_indices(len(values))
    lower, upper = values[low_index], values[high_index]
    superior = observed >= mpid and lower > 0
    return result("superior" if superior else "not-superior", observed, lower, upper)


@dataclass(frozen=True, slots=True)
class CompositionScore:
    """A composition's ranking-path D score. It has NO labels of its own: the detector and recogniser are the sealed
    identities inside ``score`` (review P1-1)."""

    score: TrackScore

    @property
    def detector(self) -> ComponentIdentity:
        return _require_d(self.score, "composition_score_not_a_ranking_d_score").detector

    @property
    def recogniser(self) -> ComponentIdentity:
        return _require_d(self.score, "composition_score_not_a_ranking_d_score").recogniser

    @property
    def detector_id(self) -> str:
        return self.detector.candidate_id

    @property
    def recogniser_id(self) -> str:
        return self.recogniser.candidate_id


# ------------------------------------------------------------------ baseline resolution (N2 revised + addendum 2026-10-14)
#
# Stage 1 (at PROTOCOL_FROZEN) freezes a ``BaselineFreeze``:
# - the eligible detector universe with exact identity hashes (M3 ``identitySha256``);
# - the complete OC5 benchmark-only identity (M3 benchmark component identity);
# - the OCR event, the gate-only composition id and the partner (detector) event, which M3's ``compositionSha256``
#   binds;
# - the Layer-A gate set hash, the freeze time and the detector ranking/tie-break rule (``DETECTOR_RANKING_RULE``);
# - the fact that PD_BASE + OC5 is the single hard D baseline gating every ordinary D composition.
#
# Stage 2 (after Layer A, before any protected D data is read) derives PD_BASE mechanically with
# ``resolve_baseline``. Every consumer re-derives it from the freeze and the Layer-A results (``verify_resolution``),
# so a forged, re-sealed record is refused. The committed pre-D seal artefact (M3 ``baseline_seal``) is review
# finding P1-2, held for the owner's sequencing decision; ``composition_sha256`` here equals M3's.

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


def _m3_document_sha256(document: dict) -> str:
    """M3 ``credibility.document_sha256``: canonical JSON plus one LF."""
    text = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n"
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def m3_composition_sha256(event_id: str, composition_id: str, benchmark: ComponentIdentity, partner_event_id: str,
                          partner: ComponentIdentity) -> str:
    """Exactly M3 ``baseline_seal.composition_sha256`` (msr/m1-plate-domain-and-baseline-role @ f24dcf5e)."""
    return _m3_document_sha256({"role": "gate-only-baseline-composition", "eventId": event_id,
                                "compositionId": composition_id,
                                "benchmarkComponent": {"candidateId": benchmark.candidate_id,
                                                       "identitySha256": benchmark.identity_sha256},
                                "partner": {"eventId": partner_event_id, "candidateId": partner.candidate_id,
                                            "identitySha256": partner.identity_sha256}})


def _detector_key(s: ComponentScore):
    def high(value):
        return (value is None, -(value or 0))

    def low(value):
        return (value is None, value or 0)

    return (high(s.primary), low(s.second), high(s.third), s.candidate_id)


@dataclass(frozen=True, slots=True)
class BaselineFreeze:
    """Stage 1, frozen in the protocol at PROTOCOL_FROZEN."""
    eligible_detectors: tuple[tuple[str, str], ...]   # (detector id, M3 identitySha256), sorted, unique
    benchmark_only_id: str                             # OC5: the benchmark-only (reference-only) component
    benchmark_only_identity_sha256: str                # M3 benchmark component identity
    layer_a_gates_sha256: str
    frozen_at_utc: str                                 # YYYY-MM-DDThh:mm:ssZ
    event_id: str                                      # the event whose ledger holds OC5 (msr-ocr-…)
    composition_id: str                                # the gate-only composition id frozen in that ledger
    partner_event_id: str                              # the detector event (msr-plate-detector-…)
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
        if not (isinstance(self.frozen_at_utc, str) and _UTC_RE.match(self.frozen_at_utc)):
            raise ValueError("baseline_freeze_time_malformed")
        if not all(isinstance(e, str) and _EVENT_RE.match(e) for e in (self.event_id, self.partner_event_id)):
            raise ValueError("baseline_freeze_event_id_malformed")
        if not (isinstance(self.composition_id, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,63}", self.composition_id)):
            raise ValueError("baseline_freeze_composition_id_malformed")

    @property
    def benchmark(self) -> ComponentIdentity:
        return ComponentIdentity(self.benchmark_only_id, self.benchmark_only_identity_sha256)

    def freeze_sha256(self) -> str:
        return _canonical_sha256({"eligibleDetectors": [list(d) for d in self.eligible_detectors],
                                  "benchmarkOnlyId": self.benchmark_only_id,
                                  "benchmarkOnlyIdentitySha256": self.benchmark_only_identity_sha256,
                                  "layerAGatesSha256": self.layer_a_gates_sha256,
                                  "frozenAtUtc": self.frozen_at_utc,
                                  "eventId": self.event_id, "compositionId": self.composition_id,
                                  "partnerEventId": self.partner_event_id,
                                  "rankingRuleSha256": self.ranking_rule_sha256,
                                  "baselineRule": BASELINE_RULE})


@dataclass(frozen=True, slots=True)
class LayerAResult:
    """One eligible detector's Layer-A result on the A/B partition. ``score`` must come from the ranking path
    (``detector_component``), which fixes its candidate id and identity; ``gates_passed`` is caller-provided."""
    score: ComponentScore
    identity_sha256: str
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
    """Stage 2. Derive PD_BASE mechanically from the frozen rule. It raises ``BaselineStop`` and never chooses.

    ``d_rows_read`` is caller-asserted (the event harness counts protected-D reads); ``resolved_at_utc`` must be a UTC
    instant not before the freeze."""
    if d_rows_read != 0:
        raise BaselineStop("baseline_resolution_after_d_data_read")
    if not (isinstance(resolved_at_utc, str) and _UTC_RE.match(resolved_at_utc)):
        raise BaselineStop("baseline_resolution_time_malformed")
    if resolved_at_utc < freeze.frozen_at_utc:
        raise BaselineStop("baseline_resolution_before_freeze")
    eligible = dict(freeze.eligible_detectors)
    seen = [r.score.candidate_id for r in results]
    if len(seen) != len(set(seen)):
        raise BaselineStop("layer_a_result_ambiguous_duplicate_detector")
    if set(seen) != set(eligible):
        # a detector outside the frozen universe, or a frozen detector missing from Layer A
        raise BaselineStop("layer_a_result_inconsistent_with_frozen_detector_universe")
    for r in results:
        if not _is_sealed(_COMPONENT, r.score):
            raise BaselineStop(f"layer_a_result_not_from_ranking_path:{r.score.candidate_id}")
        if r.identity_sha256 != eligible[r.score.candidate_id] or r.score.identity_sha256 != r.identity_sha256:
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
    composition = m3_composition_sha256(freeze.event_id, freeze.composition_id, freeze.benchmark,
                                        freeze.partner_event_id, ComponentIdentity(pd_base, eligible[pd_base]))
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
    """Re-derive Stage 2 from the frozen inputs. Any edit, substitution, forgery or drift raises ``BaselineStop``."""
    _check_sealed(resolution)
    expected = resolve_baseline(freeze, results, d_rows_read=0, resolved_at_utc=resolution.resolved_at_utc)
    if expected != resolution:
        raise BaselineStop("baseline_resolution_differs_from_frozen_derivation")


def assert_resolution_unchanged(sealed: BaselineResolution, current: BaselineResolution) -> None:
    """The sealed record is final. A later record with any different field stops the event."""
    if sealed != current:
        raise BaselineStop("baseline_resolution_changed_after_seal")


def _refuse_benchmark_only(score: TrackScore, freeze: BaselineFreeze) -> None:
    """By SEALED identity: a composition containing the benchmark-only component (id or identity) is refused."""
    score = _require_d(score, "composition_score_not_a_ranking_d_score")
    benchmark = freeze.benchmark
    for who in (score.detector, score.recogniser):
        if who.candidate_id == benchmark.candidate_id or who.identity_sha256 == benchmark.identity_sha256:
            raise ValueError("benchmark_only_component_cannot_be_ranked")


def _composition_of(score: TrackScore, freeze: BaselineFreeze) -> str:
    return m3_composition_sha256(freeze.event_id, freeze.composition_id, score.recogniser, freeze.partner_event_id,
                                 score.detector)


def baseline_gate(composition: CompositionScore, baseline: CompositionScore, resolution: BaselineResolution,
                  freeze: BaselineFreeze, layer_a_results: Sequence[LayerAResult], mpid: Fraction = MPID) -> str:
    """N2 (revised): ONE hard gate against the sealed baseline composition PD_BASE + OC5.

    Rules:
    - The resolution is re-derived from ``freeze`` and ``layer_a_results`` (a forged, re-sealed record stops the event).
    - The baseline score's SEALED identities must give exactly the resolution's M3 ``compositionSha256``.
    - Both scores must be ranking-path D results on the same population and frozen query set; diagnostics are refused.
    - Every ordinary composition, whatever its detector, must satisfy observed D − D(PD_BASE + OC5) ≥ MPID (exact).
    - A composition contract violation is FAIL.
    - A baseline that broke the contract, or cannot be evaluated, stops the event (``BaselineStop``); it is never replaced.
    - A silent baseline is a valid measurement that scores 0.
    - A corpus-deficient composition D is INSUFFICIENT_EVIDENCE.
    """
    mpid = _frozen_mpid(mpid)
    verify_resolution(freeze, resolution, layer_a_results)
    base = _require_d(baseline.score, "gate_baseline_score_not_a_ranking_d_score")
    candidate = _require_d(composition.score, "gate_composition_score_not_a_ranking_d_score")
    if base.recogniser != freeze.benchmark or _composition_of(base, freeze) != resolution.composition_sha256:
        raise ValueError("baseline_is_not_the_sealed_pd_base_composition")
    _refuse_benchmark_only(candidate, freeze)
    binding = lambda s: (s.population_manifest_sha256, s.generator_config_sha256, s.query_set_sha256)  # noqa: E731
    if binding(candidate) != binding(base):
        raise ValueError("gate_scores_not_on_the_same_population_and_query_set")
    if base.outcome == CONTRACT_FAIL:
        raise BaselineStop("baseline_contract_violation")
    if base.d_score is None:
        raise BaselineStop("baseline_not_evaluable")
    if candidate.outcome == CONTRACT_FAIL:
        return FAIL
    if candidate.d_score is None:
        return INSUFFICIENT
    return PASS if candidate.d_score - base.d_score >= mpid else FAIL


def rankable_compositions(compositions: Iterable[CompositionScore], baseline: CompositionScore,
                          resolution: BaselineResolution, freeze: BaselineFreeze,
                          layer_a_results: Sequence[LayerAResult]) -> list[CompositionScore]:
    """The ordinary D compositions that may enter ranking, the frontier or implementation: exactly those that PASS
    the single baseline gate (so never CONTRACT_FAIL or INSUFFICIENT_EVIDENCE). A composition containing the
    benchmark-only component (by sealed identity), including the gate-only baseline composition, is refused outright."""
    out = []
    for composition in compositions:
        _refuse_benchmark_only(composition.score, freeze)
        if baseline_gate(composition, baseline, resolution, freeze, layer_a_results) == PASS:
            out.append(composition)
    return out


def diagnostic_ocr_uplift(composition: CompositionScore, matched_baseline: CompositionScore,
                          freeze: BaselineFreeze) -> Fraction | None:
    """DIAGNOSTIC ONLY (N2 revised): OCR uplift at a fixed detector, D(PDx + OCy) − D(PDx + OC5).

    It never passes or fails a composition, never enters top-K or the ranking, and never changes the baseline or MPID.
    The matching is by sealed identity."""
    a = _require_d(composition.score, "diagnostic_uplift_score_not_a_ranking_d_score")
    b = _require_d(matched_baseline.score, "diagnostic_uplift_score_not_a_ranking_d_score")
    if b.detector != a.detector or b.recogniser != freeze.benchmark:
        raise ValueError("diagnostic_baseline_not_detector_matched")
    if CONTRACT_FAIL in (a.outcome, b.outcome) or a.d_score is None or b.d_score is None:
        return None
    return a.d_score - b.d_score
