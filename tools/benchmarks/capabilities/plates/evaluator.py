"""Stage-4 model-selection evaluators A–D (plan §4.4), built on PR-3's merged plate rules, behind ONE boundary:

    frozen evaluation manifest  →  execution envelope  →  sealed result  →  metric

These are the evaluators plan §7 assigned to PR-1 and PR-1 omitted (register: *Correction and repair record*). The owner
decisions they encode are written in `docs/qualification/stage4/plate-selection-decision-record-2026-10-14.md`.
**#218 is the level-1 A–D / query harness only.** The M3 pre-D seal integration is a MANDATED follow-up PR before PR-2
cold review 1 and ``PROTOCOL_FROZEN``.

**1. The manifest is the single root** (``EvaluationManifest``). It canonically defines, as candidate-independent
corpus facts:
- sites, and Track identity with typed truth (``Truth``/``TruthState``: TEXT, NO_PLATE, UNREADABLE, NO_GT_VEHICLE;
  anything else fails closed);
- each Track's MAVI Track id and its exact evidence images (``EvidenceImage``: observation id, role, rank, SHA-256,
  size). ``has_mavi_evidence`` is DERIVED from them, never supplied;
- the A items (``ManifestCrop``: an evidence image and its GT plate polygons) and the B/C items (``ManifestPlate``:
  plate text, the GT plate-crop image for B, the evidence observation for C). Each is a frozen projection of the manifest;
- the protocol configuration (``ProtocolConfig``): query parameters and seed, bootstrap seed, R, percentile rule,
  MPID, calibration minimum and each candidate's pinned detector floor.

``manifest_digest`` is computed from the canonical contents. Every entry point takes the manifest AND an independent
expected digest (a frozen input), and recomputes and compares. A modified manifest arriving with a freshly recomputed
hash is refused.

**2. Execution envelopes** (``run_track``, ``run_detection``, ``run_reading``) take the manifest and an item id, never
evidence. The harness reads the exact manifest-prescribed images (verified by SHA-256 and size) through an image source,
runs the guarded candidate on the ranking profile at the frozen floor, and returns a sealed result. Each result binds:
- the manifest digest, the layer and the item/Track id;
- the exact evidence used;
- the candidate identity and the frozen parameters;
- the terminal state: COMPLETED, or CONTRACT_FAIL with the exact evidence.

A subset, superset, reordered, substituted or empty evidence set cannot be produced. A Track without evidence cannot be
run, because NO_RUN is derived from the manifest. Candidate silence is a COMPLETED result with empty output.

**3. Metrics** (``evaluate_a`` / ``evaluate_b`` / ``evaluate_c`` / ``evaluate_d``, ``paired_cluster_bootstrap``):
- They accept only sealed results of the same manifest, and the result item ids must EQUAL the manifest projection
  exactly: no missing, duplicate, extra, substituted or relabelled items.
- Queries are generated inside from the manifest truths and the frozen query configuration.
- R, the seed and the calibration minimum come from the manifest configuration. The comparison also re-verifies the
  sealed baseline resolution, which binds the ``BaselineFreeze``, which binds the manifest digest.

**Kept unchanged:** D-score (owner N8), silence = 0, CONTRACT_FAIL (any output-contract violation, bake-off rule),
MPID 0.04 exact, the superiority rule, N3 rank-0, the single PD_BASE + OC5 gate with two-stage resolution
(ambiguous → STOP), and the two-stage bootstrap with R = 1,000 and integer percentile indices.

**Seals.** Results carry an HMAC seal under a per-process key. An edited or hand-built result is refused. An
in-process caller can still call the private ``_seal``; this is disclosed (P3-5).

**Caller-provided (complete list):**
1. the frozen expected digests (manifest; and, within it, the configuration);
2. the real corpus manifest content, until the committed corpus/MAVI-association manifest exists. That manifest is an
   integration prerequisite before the PR-2 freeze;
3. the candidate under test (its callables and its asserted ``ComponentIdentity``), and Layer-A ``gates_passed`` plus
   the ``BaselineFreeze`` (mandated M3 integration follow-up);
4. the N4 ``independent`` verdict;
5. ``resolve_baseline``'s self-attested ``d_rows_read`` and ``resolved_at_utc`` (the time is only format-checked and
   not before the freeze). Their binding to Git chronology and the committed pre-D seal is an M3-chronology integration
   item.

Seal forgery through the private ``_seal`` by an in-process caller is NOT prevented (disclosed, P3-5).
"""

from __future__ import annotations

import enum
import hashlib
import hmac
import json
import math
import random
import re
import secrets
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from fractions import Fraction
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
    has_strict_rank_order,
    is_raw_text,
    raw_line_count,
    reading_rank_key,
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
from mavi_vision.plates.pipeline import (
    OutputInvalid,
    PlateRecord,
    RankedReading,
    TrackRecord,
    analyse_crop,
    summarise_track,
)

from tools.benchmarks.capabilities.plates import queries as query_module
from tools.benchmarks.capabilities.plates.queries import CONTAINS, EXACT, QueryParameters, QuerySet, matches, queryable

# Decision record: docs/qualification/stage4/plate-selection-decision-record-2026-10-14.md
PLAN_COVERAGE_THRESHOLD = Fraction(95, 100)   # plan §4.4 A (plan-derived)
RANKING_OCR_CONFIDENCE_FLOOR = 0.0            # owner D6
DIAGNOSTIC_OCR_FLOORS = (0.3, 0.5, 0.7)       # owner D6: diagnostic only
MPID = Fraction(4, 100)                       # owner D7a (2026-10-14)
ABSOLUTE_MINIMUM_CLUSTERS = 60                # owner D7b / P-80: absolute floor only, never "adequately powered"
CONSISTENT_WRONG_LIMIT = Fraction(2, 100)     # plan §4.5, owner N3
SUPPORT_FLOOR = 50                            # owner N3; strata below it are INSUFFICIENT_EVIDENCE
P14_TOLERANCE = Fraction(2, 100)              # owner N5
ECE_BINS = 10                                 # equal-mass: item k of n in bin ⌊k·10/n⌋
CLUSTER_UNIT = "physical-capture-site"        # owner item 4 / C2
BOOTSTRAP_REPLICATES = 1000                   # frozen R (owner T)
PERCENTILE_RULE = "floor(25(R-1)/1000), ceil(975(R-1)/1000)"
MANIFEST_SCHEMA = "mavi-plate-selection-evaluation-manifest-v1"

PASS, FAIL, INSUFFICIENT = "PASS", "FAIL", "INSUFFICIENT_EVIDENCE"
MEASURED, CONTRACT_FAIL, COMPLETED = "MEASURED", "CONTRACT_FAIL", "COMPLETED"

_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_CANDIDATE_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*$")
_EVENT_RE = re.compile(r"^msr-[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?-\d{4}-\d{2}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(_SHA_RE.match(value))


def _canonical_sha256(payload: object) -> str:
    """M3 ``credibility.document_sha256`` form: canonical JSON plus one LF."""
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n"
    return hashlib.sha256(text.encode("ascii")).hexdigest()


# ---------------------------------------------------------------------------------------------- seals

_SEAL_KEY = secrets.token_bytes(32)
_TRACK_RUN, _A_RUN, _B_RUN, _A, _B, _COMPONENT, _D = (
    "track-run", "detection-run", "reading-run", "detection", "reading", "component", "d-score")


def _mac(kind: str, obj) -> str:
    body = repr(replace(obj, seal=""))
    return hmac.new(_SEAL_KEY, f"{kind}\x00{body}".encode("utf-8"), hashlib.sha256).hexdigest()


def _seal(kind: str, obj):
    """Ranking-path constructor only. Tests use it to build metric fixtures; it is not an API."""
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


def _ratio(numerator: int, denominator: int) -> Fraction | None:
    return Fraction(numerator, denominator) if denominator else None


def normalised_truth(raw: str) -> str | None:
    result = normalise(raw)
    return result.normalised if result.outcome == OK else None


# ---------------------------------------------------------------------------------------------- identities


@dataclass(frozen=True, slots=True)
class ComponentIdentity:
    """A candidate component. ``identity_sha256`` is M3's ``identitySha256`` (canonical SHA-256 of the ledger identity
    block); for the benchmark-only component it is M3's benchmark component identity."""

    candidate_id: str
    identity_sha256: str

    def __post_init__(self):
        if not (isinstance(self.candidate_id, str) and _CANDIDATE_RE.match(self.candidate_id)):
            raise ValueError("component_identity_id_malformed")
        if not _is_sha256(self.identity_sha256):
            raise ValueError("component_identity_sha256_malformed")


def _identity(value: object, code: str) -> ComponentIdentity:
    if not isinstance(value, ComponentIdentity):
        raise ValueError(code)
    return value


# ---------------------------------------------------------------------------------------------- the manifest


class TruthState(enum.Enum):
    TEXT = "TEXT"
    NO_PLATE = "NO_PLATE"
    UNREADABLE = "UNREADABLE"
    NO_GT_VEHICLE = "NO_GT_VEHICLE"


_STATE_NAMES = frozenset(re.sub(r"[^A-Z0-9]", "", s.value) for s in TruthState)


@dataclass(frozen=True, slots=True)
class Truth:
    """Typed GT truth. Only ``TruthState`` members are accepted (a misspelt state fails closed); TEXT carries the raw
    adjudicated text, the others carry none."""

    state: TruthState
    text: str | None = None

    def __post_init__(self):
        if not isinstance(self.state, TruthState):
            raise ValueError("truth_state_not_typed")
        if self.state is TruthState.TEXT:
            if not (isinstance(self.text, str) and self.text.strip()):
                raise ValueError("truth_text_required")
            if self.text.strip().startswith("<") and self.text.strip().endswith(">"):
                raise ValueError("truth_text_looks_like_a_sentinel")  # a misspelt state never becomes text
            if re.sub(r"[^A-Za-z0-9]", "", self.text).upper() in _STATE_NAMES:
                raise ValueError("truth_text_looks_like_a_sentinel")  # "UNREADABLE", "no-gt-vehicle", …
        elif self.text is not None:
            raise ValueError("truth_text_only_for_text")

    @property
    def supported_text(self) -> str | None:
        return normalised_truth(self.text) if self.state is TruthState.TEXT else None


def TEXT(text: str) -> Truth:  # noqa: N802 - a typed-truth constructor
    return Truth(TruthState.TEXT, text)


NO_PLATE, UNREADABLE, NO_GT_VEHICLE = (Truth(TruthState.NO_PLATE), Truth(TruthState.UNREADABLE),
                                       Truth(TruthState.NO_GT_VEHICLE))


@dataclass(frozen=True, slots=True)
class EvidenceImage:
    """One exact evidence image: observation id, lease role and rank, and its bytes' SHA-256 and size."""

    observation_id: str
    role: str
    evidence_rank: int
    sha256: str
    size_bytes: int

    def row(self) -> list:
        return [self.observation_id, self.role, self.evidence_rank, self.sha256, self.size_bytes]


@dataclass(frozen=True, slots=True)
class ManifestTrack:
    track_id: str
    site: str                                   # physical capture site (cluster)
    truth: Truth
    mavi_track_uuid: str | None = None          # the MAVI Track (association), if any
    evidence: tuple[EvidenceImage, ...] = ()    # its evidence images, in lease order

    @property
    def has_mavi_evidence(self) -> bool:
        """DERIVED from the association: a MAVI Track with evidence exists for this GT vehicle."""
        return bool(self.evidence)


@dataclass(frozen=True, slots=True)
class ManifestCrop:
    """An A item: one evidence image of a Track, and its GT plate polygons."""

    crop_id: str
    track_id: str
    observation_id: str
    plates: tuple


@dataclass(frozen=True, slots=True)
class ManifestPlate:
    """A B/C item: a GT plate's text. ``plate_image`` (the GT plate crop) makes it a B item; ``observation_id`` (the
    evidence image it lies in) makes it a C item."""

    plate_id: str
    track_id: str
    text: str
    plate_image: EvidenceImage | None = None
    observation_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProtocolConfig:
    """The selection-protocol values, hashed into the manifest digest (owner invariant 8)."""

    query: QueryParameters
    bootstrap_seed: int
    calibration_minimum_clusters: int
    detector_floors: tuple[tuple[str, float], ...]   # (detector candidate id, pinned floor), sorted
    top_k: int = 3                                   # plan §4.1: K per sub-task
    top_k_support_floor: int = SUPPORT_FLOOR         # owner N3/N4: minimum support to enter top-K
    bootstrap_replicates: int = BOOTSTRAP_REPLICATES
    percentile_rule: str = PERCENTILE_RULE
    mpid: str = "4/100"

    def row(self) -> dict:
        return {"query": {"interiorOffset": self.query.interior_offset,
                          "negativesPerPlate": self.query.negatives_per_plate, "seed": self.query.seed},
                "bootstrapSeed": self.bootstrap_seed, "bootstrapReplicates": self.bootstrap_replicates,
                "percentileRule": self.percentile_rule, "mpid": self.mpid,
                "calibrationMinimumClusters": self.calibration_minimum_clusters,
                "topK": self.top_k, "topKSupportFloor": self.top_k_support_floor,
                "detectorFloors": [[c, repr(float(f))] for c, f in self.detector_floors]}


@dataclass(frozen=True, slots=True)
class EvaluationManifest:
    manifest_id: str
    tracks: tuple[ManifestTrack, ...]
    crops: tuple[ManifestCrop, ...]
    plates: tuple[ManifestPlate, ...]
    config: ProtocolConfig


def _polygons(plates) -> list:
    return [[[x, y] for x, y in polygon] for polygon in plates]


def _truth_row(truth) -> list:
    if isinstance(truth, Truth):
        return [truth.state.value, truth.text]
    return ["<untyped>", repr(truth)]  # refused by verify_manifest


def _manifest_document(m: EvaluationManifest) -> dict:
    return {"schema": MANIFEST_SCHEMA, "manifestId": m.manifest_id,
            "tracks": [[t.track_id, t.site, *_truth_row(t.truth), t.mavi_track_uuid,
                        [e.row() for e in t.evidence]] for t in m.tracks],
            "crops": [[c.crop_id, c.track_id, c.observation_id, _polygons(c.plates)] for c in m.crops],
            "plates": [[p.plate_id, p.track_id, p.text, None if p.plate_image is None else p.plate_image.row(),
                        p.observation_id] for p in m.plates],
            "config": m.config.row()}


def manifest_digest(manifest: EvaluationManifest) -> str:
    """The canonical identity of the manifest (structure is validated by ``verify_manifest``)."""
    return _canonical_sha256(_manifest_document(manifest))


@dataclass(frozen=True)
class _Verified:
    manifest: EvaluationManifest
    digest: str
    tracks: Mapping[str, ManifestTrack]
    crops: Mapping[str, ManifestCrop]
    b_plates: Mapping[str, ManifestPlate]
    c_plates: Mapping[str, ManifestPlate]
    floors: Mapping[str, float]


def _is_uuid(value: object) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False


def _unique_or_empty(values: list, code: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(code)


def _unique(ids: list, code: str) -> None:
    if len(ids) != len(set(ids)) or not all(isinstance(i, str) and i for i in ids):
        raise ValueError(code)


def verify_manifest(manifest: EvaluationManifest, expected_manifest_digest: str) -> _Verified:
    """Validate the manifest structure, recompute its digest from the canonical contents, and require it to equal the
    INDEPENDENT frozen expected digest. Every execution envelope and metric calls this."""
    if not isinstance(manifest, EvaluationManifest):
        raise ValueError("manifest_type")
    if not _is_sha256(expected_manifest_digest):
        raise ValueError("manifest_expected_digest_malformed")
    tracks, crops, plates, config = manifest.tracks, manifest.crops, manifest.plates, manifest.config
    _unique([t.track_id for t in tracks], "manifest_track_ids_not_unique")
    _unique([c.crop_id for c in crops], "manifest_crop_ids_not_unique")
    _unique([p.plate_id for p in plates], "manifest_plate_ids_not_unique")
    if not tracks:
        raise ValueError("manifest_without_tracks")
    by_track: dict[str, ManifestTrack] = {}
    for t in tracks:
        if not (isinstance(t, ManifestTrack) and isinstance(t.truth, Truth) and isinstance(t.site, str) and t.site):
            raise ValueError("manifest_track_malformed")
        observations = [e.observation_id for e in t.evidence]
        if not all(isinstance(e, EvidenceImage) and _is_sha256(e.sha256) and _integer(e.size_bytes) and e.size_bytes > 0
                   for e in t.evidence):
            raise ValueError("manifest_evidence_malformed")
        if observations:
            _unique(observations, "manifest_evidence_ids_not_unique")
        if not all(_is_uuid(i) for i in observations) or (t.mavi_track_uuid is not None and not _is_uuid(t.mavi_track_uuid)):
            raise ValueError("manifest_ids_not_canonical_uuids")
        if t.evidence and not (isinstance(t.mavi_track_uuid, str) and t.mavi_track_uuid):
            raise ValueError("manifest_evidence_without_mavi_track")
        if not t.evidence and t.mavi_track_uuid is not None:
            raise ValueError("manifest_mavi_track_without_evidence")
        if t.truth.state is TruthState.NO_GT_VEHICLE and not t.evidence:
            raise ValueError("manifest_no_gt_vehicle_without_mavi_evidence")  # by definition a MAVI Track
        by_track[t.track_id] = t
    # Review 6, P2-1: no alias items. One MAVI Track per GT Track, one owner per evidence image, one A crop per image,
    # one C plate per (Track, image), one B plate per GT plate-crop image.
    _unique_or_empty([t.mavi_track_uuid for t in tracks if t.mavi_track_uuid is not None],
                     "manifest_mavi_track_shared_by_two_tracks")
    _unique_or_empty([e.observation_id for t in tracks for e in t.evidence], "manifest_evidence_shared_by_two_tracks")
    _unique_or_empty([c.observation_id for c in crops], "manifest_two_crops_on_one_evidence_image")
    _unique_or_empty([(p.track_id, p.observation_id) for p in plates if p.observation_id is not None],
                     "manifest_two_c_plates_on_one_evidence_image")
    _unique_or_empty([p.plate_image.observation_id for p in plates if isinstance(p.plate_image, EvidenceImage)],
                     "manifest_two_b_plates_on_one_image")
    _unique_or_empty([p.plate_image.sha256 for p in plates if isinstance(p.plate_image, EvidenceImage)],
                     "manifest_two_b_plates_on_one_image")
    for c in crops:
        track = by_track.get(c.track_id)
        if track is None or c.observation_id not in {e.observation_id for e in track.evidence}:
            raise ValueError("manifest_crop_not_an_evidence_image")
    b_plates, c_plates = {}, {}
    for p in plates:
        track = by_track.get(p.track_id)
        if track is None or track.truth.state is not TruthState.TEXT or not (isinstance(p.text, str) and p.text.strip()):
            raise ValueError("manifest_plate_malformed")
        if p.text != track.truth.text:
            raise ValueError("manifest_plate_text_differs_from_its_track_truth")
        if p.plate_image is None and p.observation_id is None:
            raise ValueError("manifest_plate_in_no_layer")
        if p.plate_image is not None:
            if not (isinstance(p.plate_image, EvidenceImage) and _is_sha256(p.plate_image.sha256)):
                raise ValueError("manifest_plate_image_malformed")
            b_plates[p.plate_id] = p
        if p.observation_id is not None:
            if p.observation_id not in {e.observation_id for e in track.evidence}:
                raise ValueError("manifest_plate_not_in_an_evidence_image")
            c_plates[p.plate_id] = p
    if not isinstance(config, ProtocolConfig) or not isinstance(config.query, QueryParameters):
        raise ValueError("manifest_config_malformed")
    if not _integer(config.bootstrap_replicates) or config.bootstrap_replicates != BOOTSTRAP_REPLICATES:
        raise ValueError("manifest_config_replicates_not_frozen_value")
    if not (_integer(config.top_k) and config.top_k >= 1 and _integer(config.top_k_support_floor)
            and config.top_k_support_floor >= 0):
        raise ValueError("manifest_config_top_k_malformed")
    if config.percentile_rule != PERCENTILE_RULE or config.mpid != "4/100":
        raise ValueError("manifest_config_rule_not_frozen")
    if not (_integer(config.bootstrap_seed) and _integer(config.calibration_minimum_clusters)
            and config.calibration_minimum_clusters >= 1):
        raise ValueError("manifest_config_malformed")
    floor_ids = [c for c, _ in config.detector_floors]
    if floor_ids != sorted(set(floor_ids)) or not all(_probability(f) for _, f in config.detector_floors):
        raise ValueError("manifest_config_detector_floors_malformed")
    digest = manifest_digest(manifest)
    if digest != expected_manifest_digest:
        raise ValueError("manifest_not_the_frozen_manifest")  # a modified manifest with a recomputed hash fails here
    return _Verified(manifest, digest, by_track, {c.crop_id: c for c in crops}, b_plates, c_plates,
                     dict(config.detector_floors))


def layer_digest(manifest: EvaluationManifest, expected_manifest_digest: str, layer: str) -> str:
    """The digest of a layer's frozen projection of the manifest (A crops, B plates, C plates, D Tracks)."""
    v = verify_manifest(manifest, expected_manifest_digest)
    rows = {"A": sorted(v.crops), "B": sorted(v.b_plates), "C": sorted(v.c_plates), "D": sorted(v.tracks)}[layer]
    return _canonical_sha256({"manifest": v.digest, "layer": layer, "items": rows})


# ---------------------------------------------------------------------------------------------- output contract


def ranking_parameters(detector_confidence_floor: float) -> PlateParameters:
    """The ranking profile: 2/1/3 bounds, OCR floor 0, the candidate's pinned detector floor."""
    return PlateParameters(MAXIMUM_DETECTIONS_PER_CROP, MAXIMUM_PLATES_PER_CROP, MAXIMUM_READINGS_PER_PLATE,
                           float(detector_confidence_floor), RANKING_OCR_CONFIDENCE_FLOOR, frozenset(), None)


def is_ranking_profile(parameters: PlateParameters, detector_floor: float | None = None) -> bool:
    return (parameters.max_detections_per_crop == MAXIMUM_DETECTIONS_PER_CROP
            and parameters.max_plates_per_crop == MAXIMUM_PLATES_PER_CROP
            and parameters.max_readings_per_plate == MAXIMUM_READINGS_PER_PLATE
            and parameters.ocr_confidence_floor == RANKING_OCR_CONFIDENCE_FLOOR
            and not parameters.excluded_roles
            and parameters.fixture_seed is None
            and (detector_floor is None or parameters.detector_confidence_floor == float(detector_floor)))


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


# ---------------------------------------------------------------------------------------------- execution envelopes

ImageSource = Callable[[EvidenceImage], bytes]


def _image_bytes(images: ImageSource, ref: EvidenceImage) -> bytes:
    """The harness reads the manifest-prescribed image and verifies it. A mismatch is a corpus integrity failure (the
    run is refused), never a candidate result."""
    content = images(ref)
    if not isinstance(content, (bytes, bytearray)) or len(content) != ref.size_bytes \
            or hashlib.sha256(bytes(content)).hexdigest() != ref.sha256:
        raise ValueError("corpus_image_integrity_failed")
    return bytes(content)


def _floor_for(v: _Verified, detector: ComponentIdentity) -> float:
    if detector.candidate_id not in v.floors:
        raise ValueError("detector_floor_not_frozen_in_manifest")
    return float(v.floors[detector.candidate_id])


@dataclass(frozen=True, slots=True)
class TrackRun:
    """The sealed D/C execution of one composition on one manifest Track's exact evidence."""

    manifest_digest: str
    track_id: str
    mavi_track_uuid: str
    evidence: tuple[EvidenceImage, ...]
    detector: ComponentIdentity
    recogniser: ComponentIdentity
    parameters: PlateParameters
    state: str                      # COMPLETED | CONTRACT_FAIL
    record: TrackRecord | None
    contract_violation: str | None
    seal: str = ""


def lease_observation(observation_id, role: str, evidence_rank: int, size_bytes: int, sha256: str) -> LeaseObservation:
    return LeaseObservation.model_validate({"observationId": observation_id, "role": role,
                                            "evidenceRank": evidence_rank, "sizeBytes": size_bytes, "sha256": sha256})


def run_track(manifest: EvaluationManifest, expected_manifest_digest: str, track_id: str, *, detector: PlateDetector,
              recogniser: PlateRecogniser, detector_identity: ComponentIdentity,
              recogniser_identity: ComponentIdentity, images: ImageSource) -> TrackRun:
    """Run PR-3 with the guarded candidate on EXACTLY the manifest Track's evidence, at the frozen floor."""
    v = verify_manifest(manifest, expected_manifest_digest)
    det = _identity(detector_identity, "run_detector_identity_required")
    rec = _identity(recogniser_identity, "run_recogniser_identity_required")
    track = v.tracks.get(track_id)
    if track is None:
        raise ValueError("run_track_not_in_manifest")
    if not track.has_mavi_evidence:
        raise ValueError("run_track_has_no_mavi_evidence")  # NO_RUN is derived from the manifest, never executed
    parameters = ranking_parameters(_floor_for(v, det))
    contents = [_image_bytes(images, ref) for ref in track.evidence]
    observations = tuple(lease_observation(UUID(e.observation_id), e.role, e.evidence_rank, e.size_bytes, e.sha256)
                         for e in track.evidence)
    lease = LeaseTrack.model_validate({"trackId": UUID(track.mavi_track_uuid), "objectClass": "vehicle",
                                       "observations": observations})
    guard = _Guard()
    checked_detector = _CheckedDetector(detector, guard, parameters.max_detections_per_crop)
    checked_recogniser = _CheckedRecogniser(recogniser, guard, parameters.max_readings_per_plate)

    def result(state, record, violation):
        return _seal(_TRACK_RUN, TrackRun(v.digest, track_id, track.mavi_track_uuid, track.evidence, det, rec, parameters,
                                          state, record, violation))

    records = []
    for ref, content, observation in zip(track.evidence, contents, observations):
        verified = VerifiedCrop(ref.observation_id, ref.role, ref.evidence_rank, ref.sha256, content)
        try:
            record = analyse_crop(observation, verified, checked_detector, checked_recogniser, parameters)
        except OutputInvalid as exc:
            return result(CONTRACT_FAIL, None, guard.violation or str(exc))
        if guard.violation is not None:
            return result(CONTRACT_FAIL, None, guard.violation)
        records.append(record)
    try:
        summary = summarise_track(lease, tuple(records))
    except OutputInvalid as exc:
        return result(CONTRACT_FAIL, None, str(exc))
    return result(COMPLETED, summary, None)


@dataclass(frozen=True, slots=True)
class DetectionRun:
    """The sealed A execution of one detector on one manifest crop."""

    manifest_digest: str
    crop_id: str
    image: EvidenceImage
    detector: ComponentIdentity
    detector_floor: float
    state: str
    proposals: tuple[tuple[int, int, int, int, float], ...]
    crop_size: tuple[int, int] | None
    contract_violation: str | None
    seal: str = ""


def run_detection(manifest: EvaluationManifest, expected_manifest_digest: str, crop_id: str, *,
                  detector: PlateDetector, detector_identity: ComponentIdentity, images: ImageSource) -> DetectionRun:
    """Run the guarded detector on EXACTLY the manifest crop's evidence image."""
    v = verify_manifest(manifest, expected_manifest_digest)
    det = _identity(detector_identity, "run_detector_identity_required")
    crop = v.crops.get(crop_id)
    if crop is None:
        raise ValueError("run_crop_not_in_manifest")
    ref = next(e for e in v.tracks[crop.track_id].evidence if e.observation_id == crop.observation_id)
    floor = _floor_for(v, det)
    content = _image_bytes(images, ref)
    try:
        image = decode_crop(content)
    except CropDecodeError as exc:
        raise ValueError("corpus_image_undecodable") from exc
    width, height = image.size
    verified = VerifiedCrop(ref.observation_id, ref.role, ref.evidence_rank, ref.sha256, content)

    def result(state, proposals, violation):
        return _seal(_A_RUN, DetectionRun(v.digest, crop_id, ref, det, floor, state, proposals, (width, height),
                                          violation))

    try:
        boxes = detector.detect(image, verified)
    except Exception as exc:  # noqa: BLE001
        return result(CONTRACT_FAIL, (), f"plate_detector_runtime_error@obs={ref.observation_id}:"
                                          f"{_exception_evidence(exc)}")
    violation = detector_output_violation(boxes, width, height, MAXIMUM_DETECTIONS_PER_CROP)
    if violation is not None:
        return result(CONTRACT_FAIL, (), f"{violation}:obs={ref.observation_id}")
    return result(COMPLETED, tuple((b.x, b.y, b.width, b.height, float(b.score)) for b in boxes), None)


@dataclass(frozen=True, slots=True)
class ReadRun:
    """The sealed B execution of one recogniser on one manifest GT plate crop."""

    manifest_digest: str
    plate_id: str
    image: EvidenceImage
    recogniser: ComponentIdentity
    state: str
    plate: PlateRecord | None
    contract_violation: str | None
    seal: str = ""


def _rank_plate(readings: Sequence[Reading], parameters: PlateParameters) -> PlateRecord:
    """PR-3's ranking through its public contract (equal to ``pipeline._plate``, proven by test)."""
    ordered = sorted(readings, key=lambda item: reading_rank_key(item.confidence, item.raw_text))
    ranked = tuple(RankedReading(rank, item.raw_text, raw_line_count(item.raw_text), float(item.confidence))
                   for rank, item in enumerate(ordered))
    outcome = PLATE_READ if ranked and ranked[0].confidence >= parameters.ocr_confidence_floor else PLATE_UNREADABLE
    return PlateRecord(0, outcome, ranked)


def run_reading(manifest: EvaluationManifest, expected_manifest_digest: str, plate_id: str, *,
                recogniser: PlateRecogniser, recogniser_identity: ComponentIdentity, images: ImageSource) -> ReadRun:
    """Run the guarded recogniser on EXACTLY the manifest GT plate crop (whole image as the plate region)."""
    v = verify_manifest(manifest, expected_manifest_digest)
    rec = _identity(recogniser_identity, "run_recogniser_identity_required")
    plate = v.b_plates.get(plate_id)
    if plate is None:
        raise ValueError("run_plate_not_in_manifest")
    ref = plate.plate_image
    content = _image_bytes(images, ref)
    try:
        image = decode_crop(content)
    except CropDecodeError as exc:
        raise ValueError("corpus_image_undecodable") from exc
    verified = VerifiedCrop(ref.observation_id, ref.role, ref.evidence_rank, ref.sha256, content)

    def result(state, record, violation):
        return _seal(_B_RUN, ReadRun(v.digest, plate_id, ref, rec, state, record, violation))

    try:
        readings = recogniser.read(image, verified, PlateBox(0, 0, image.size[0], image.size[1], 1.0))
    except Exception as exc:  # noqa: BLE001
        return result(CONTRACT_FAIL, None, f"plate_recogniser_runtime_error@obs={ref.observation_id}:"
                                           f"{_exception_evidence(exc)}")
    violation = recogniser_output_violation(readings, MAXIMUM_READINGS_PER_PLATE)
    if violation is not None:
        return result(CONTRACT_FAIL, None, f"{violation}:obs={ref.observation_id}")
    return result(COMPLETED, _rank_plate(list(readings), ranking_parameters(0.0)), None)


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
    lease = LeaseTrack.model_validate({"trackId": record.track_id, "objectClass": "vehicle",
                                       "observations": observations})
    return summarise_track(lease, tuple(crops))


def diagnostic_plate_record(readings, floor: float) -> PlateRecord | None:
    """DIAGNOSTIC ONLY: readings ranked at a declared diagnostic OCR floor (an unsealed PlateRecord)."""
    if floor not in DIAGNOSTIC_OCR_FLOORS:
        raise ValueError("diagnostic_floor_not_declared")
    if recogniser_output_violation(readings, MAXIMUM_READINGS_PER_PLATE) is not None:
        return None
    return _rank_plate(list(readings), replace(ranking_parameters(0.0), ocr_confidence_floor=floor))


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
    """Exact share of the GT polygon's area inside the box ``(x1, y1, x2, y2)`` (Sutherland–Hodgman over rationals)."""
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
class DetectionResult:
    outcome: str                      # MEASURED | CONTRACT_FAIL
    contract_violations: tuple[str, ...]
    plates: int
    covered: int
    recall: Fraction | None
    false_plates_per_crop: Fraction | None
    ap50: float | None
    below_floor_proposals: int
    manifest_digest: str
    layer_digest: str
    detector: ComponentIdentity
    seal: str = ""


def _require_complete(runs: Iterable, kind: str, id_of: Callable, expected_ids: Iterable[str], digest: str,
                      code: str) -> dict:
    """Owner invariant 5: sealed results of THIS manifest whose ids EQUAL the expected projection exactly."""
    out: dict = {}
    for run in runs:
        _require(kind, run, f"{code}_result_not_sealed")
        if run.manifest_digest != digest:
            raise ValueError(f"{code}_result_of_another_manifest")
        key = id_of(run)
        if key in out:
            raise ValueError(f"{code}_duplicate_result")
        out[key] = run
    if set(out) != set(expected_ids):
        raise ValueError(f"{code}_results_do_not_equal_the_manifest_items")
    return out


def evaluate_a(manifest: EvaluationManifest, expected_manifest_digest: str, runs: Iterable[DetectionRun], *,
               detector: ComponentIdentity) -> DetectionResult:
    """A: recall at coverage ≥ 0.95 over EXACTLY the manifest crops. Any output-contract violation is a FAIL (nothing
    scored, truncated or re-selected); valid proposals below the frozen floor are counted only as reported."""
    v = verify_manifest(manifest, expected_manifest_digest)
    det = _identity(detector, "a_detector_identity_required")
    by_crop = _require_complete(runs, _A_RUN, lambda r: r.crop_id, v.crops, v.digest, "a")
    for crop_id, run in by_crop.items():
        crop = v.crops[crop_id]
        if run.detector != det:
            raise ValueError("a_result_from_another_detector")
        ref = next(e for e in v.tracks[crop.track_id].evidence if e.observation_id == crop.observation_id)
        if run.image != ref or run.detector_floor != _floor_for(v, det):
            raise ValueError("a_result_not_the_manifest_execution")
    layer = layer_digest(manifest, expected_manifest_digest, "A")
    violations = tuple(f"{r.contract_violation}:{c}" for c, r in sorted(by_crop.items()) if r.state == CONTRACT_FAIL)
    if violations:
        return _seal(_A, DetectionResult(CONTRACT_FAIL, violations, 0, 0, None, None, None, 0, v.digest, layer, det))
    floor = _floor_for(v, det)
    plates = covered = false = below = 0
    scored: list[tuple[float, str, int, bool]] = []
    for crop_id in sorted(by_crop):
        run, crop = by_crop[crop_id], v.crops[crop_id]
        polygons = [tuple((x, y) for x, y in p) for p in crop.plates]
        kept = [p for p in run.proposals if p[4] >= floor]
        below += len(run.proposals) - len(kept)
        boxes = [(x, y, x + w, y + h) for x, y, w, h, _ in kept]
        hit = sum(1 for polygon in polygons if any(coverage(polygon, b) >= PLAN_COVERAGE_THRESHOLD for b in boxes))
        plates += len(polygons)
        covered += hit
        false += sum(1 for b in boxes if not any(coverage(p, b) >= PLAN_COVERAGE_THRESHOLD for p in polygons))
        gt_boxes = [(min(x for x, _ in p), min(y for _, y in p), max(x for x, _ in p), max(y for _, y in p))
                    for p in polygons]
        taken: set[int] = set()
        for index in sorted(range(len(boxes)), key=lambda i: (-kept[i][4], i)):
            best, best_iou = None, 0.5
            for g, gt in enumerate(gt_boxes):
                value = _iou(boxes[index], gt)
                if g not in taken and value >= best_iou:
                    best, best_iou = g, value
            if best is not None:
                taken.add(best)
            scored.append((kept[index][4], crop_id, index, best is not None))
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
    return _seal(_A, DetectionResult(MEASURED, (), plates, covered, _ratio(covered, plates),
                                     _ratio(false, len(by_crop)), ap, below, v.digest, layer, det))


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
class ReadResult:
    layer: str                        # "B" | "C"
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
    manifest_digest: str
    layer_digest: str
    recogniser: ComponentIdentity
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


def _reading_result(layer: str, v: _Verified, layer_hash: str, recogniser: ComponentIdentity,
                    per_plate: Mapping[str, tuple[PlateRecord | None, str | None]], texts: Mapping[str, str]) -> ReadResult:
    violations = tuple(f"{violation}:{pid}" for pid, (_, violation) in sorted(per_plate.items()) if violation)
    if violations:
        return _seal(_B, ReadResult(layer, CONTRACT_FAIL, violations, 0, 0, None, None, None, None, (), 0, v.digest,
                                    layer_hash, recogniser))
    rows: list[tuple[str, bool, float, float | None, bool]] = []
    unsupported = 0
    for pid in sorted(per_plate):
        truth = normalised_truth(texts[pid])
        if truth is None:
            unsupported += 1
            continue
        plate = per_plate[pid][0]
        predicted, confidence, any_rank = "", None, False
        if plate is not None and plate.outcome == PLATE_READ:
            confidence = plate.readings[0].confidence
            predicted = normalised_truth(plate.readings[0].raw_text) or ""
            any_rank = any(normalised_truth(r.raw_text) == truth for r in plate.readings)
        rows.append((pid, predicted == truth, cer(predicted, truth), confidence, any_rank))
    n = len(rows)
    exact = sum(r[1] for r in rows)
    ranked = sorted([(r[3], r[1], r[0]) for r in rows if r[3] is not None], key=lambda t: (-t[0], t[2]))
    curve, correct = [], 0
    for k, (_, e, _) in enumerate(ranked, 1):
        correct += e
        curve.append((k / n, 1 - correct / k))
    return _seal(_B, ReadResult(layer, MEASURED, (), n, exact, _ratio(exact, n), sum(r[2] for r in rows) / n if n else None,
                                _ece(ranked), _ratio(sum(r[4] for r in rows), n), tuple(curve), unsupported, v.digest,
                                layer_hash, recogniser))


def evaluate_b(manifest: EvaluationManifest, expected_manifest_digest: str, runs: Iterable[ReadRun], *,
               recogniser: ComponentIdentity) -> ReadResult:
    """B: EM of the rank-0 reading over EXACTLY the manifest's B plates (GT plate crops)."""
    v = verify_manifest(manifest, expected_manifest_digest)
    rec = _identity(recogniser, "b_recogniser_identity_required")
    by_plate = _require_complete(runs, _B_RUN, lambda r: r.plate_id, v.b_plates, v.digest, "b")
    for pid, run in by_plate.items():
        if run.recogniser != rec:
            raise ValueError("b_result_from_another_recogniser")
        if run.image != v.b_plates[pid].plate_image:
            raise ValueError("b_result_not_the_manifest_execution")
    per_plate = {pid: (run.plate, run.contract_violation) for pid, run in by_plate.items()}
    return _reading_result("B", v, layer_digest(manifest, expected_manifest_digest, "B"), rec, per_plate,
                           {pid: v.b_plates[pid].text for pid in by_plate})


def c_minus_b(c: ReadResult, b: ReadResult) -> Fraction | None:
    """Diagnostic only: the detector-attributable EM loss (C − B), from sealed C and B results of the same manifest and
    recogniser."""
    _require(_B, c, "c_minus_b_result_not_sealed")
    _require(_B, b, "c_minus_b_result_not_sealed")
    if (c.layer, b.layer) != ("C", "B") or c.manifest_digest != b.manifest_digest or c.recogniser != b.recogniser:
        raise ValueError("c_minus_b_results_not_comparable")
    return None if c.em is None or b.em is None else c.em - b.em


# ---------------------------------------------------------------------------------------------- top-K (N4)


@dataclass(frozen=True, slots=True)
class ComponentScore:
    candidate_id: str
    independent: bool              # caller-provided N4 verdict: demonstrably independent qualifying release
    support: int
    primary: float | None          # A: recall at coverage; B: EM
    second: float | None           # A: false plates per crop (lower better); B: CER (lower better)
    third: float | None            # A: AP50 (higher better); B: ECE (lower better)
    contract_fail: bool
    identity_sha256: str
    kind: str                      # "detector" | "recogniser"
    manifest_digest: str
    measurement_sha256: str        # canonical hash of the sealed A/B result it was built from
    seal: str = ""


def _float(value) -> float | None:
    return None if value is None else float(value)


def _measurement_sha256(result) -> str:
    return _canonical_sha256({"result": repr(replace(result, seal=""))})


def detector_component(independent: bool, result: DetectionResult) -> ComponentScore:
    _require(_A, result, "component_detection_result_not_from_ranking_path")
    who = result.detector
    return _seal(_COMPONENT, ComponentScore(who.candidate_id, bool(independent), result.plates, _float(result.recall),
                                            _float(result.false_plates_per_crop), result.ap50,
                                            result.outcome == CONTRACT_FAIL, who.identity_sha256, "detector",
                                            result.manifest_digest, _measurement_sha256(result)))


def recogniser_component(independent: bool, result: ReadResult) -> ComponentScore:
    _require(_B, result, "component_read_result_not_from_ranking_path")
    if result.layer != "B":
        raise ValueError("component_read_result_not_layer_b")
    who = result.recogniser
    return _seal(_COMPONENT, ComponentScore(who.candidate_id, bool(independent), result.plates, _float(result.em),
                                            result.cer, result.ece, result.outcome == CONTRACT_FAIL,
                                            who.identity_sha256, "recogniser", result.manifest_digest,
                                            _measurement_sha256(result)))


def top_k(scores: Iterable[ComponentScore], kind: str, *, freeze: "BaselineFreeze", manifest: EvaluationManifest,
          expected_manifest_digest: str) -> list[str]:
    """N4 tie-breaks over sealed scores of ``kind`` measured on the frozen manifest. K and the support floor are the
    frozen ``ProtocolConfig`` values (review 6, P2-2). Missing metrics sort last; contract-failed or non-independent
    components never enter; the benchmark-only component (by id OR identity) and duplicate candidates are refused."""
    if kind not in ("detector", "recogniser"):
        raise ValueError("top_k_kind")
    if not isinstance(freeze, BaselineFreeze):
        raise ValueError("top_k_requires_the_baseline_freeze")
    v = verify_manifest(manifest, expected_manifest_digest)
    if freeze.manifest_digest != v.digest:
        raise ValueError("top_k_freeze_is_for_another_manifest")
    k, minimum_support = v.manifest.config.top_k, v.manifest.config.top_k_support_floor
    scores = list(scores)
    if len({s.candidate_id for s in scores}) != len(scores):
        raise ValueError("top_k_duplicate_candidate")
    benchmark = freeze.benchmark
    for s in scores:
        _require(_COMPONENT, s, "top_k_score_not_from_ranking_path")
        if s.kind != kind:
            raise ValueError("top_k_score_of_another_kind")
        if s.candidate_id == benchmark.candidate_id or s.identity_sha256 == benchmark.identity_sha256:
            raise ValueError("benchmark_only_component_cannot_enter_top_k")
        if s.manifest_digest != freeze.manifest_digest:
            raise ValueError("top_k_score_not_on_the_frozen_manifest")

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
    """A ranking-path D result, sealed only by ``evaluate_d`` and bound to its manifest and query set."""

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
    no_text_rate: Fraction | None
    contract_violations: tuple[str, ...]
    accounting: dict
    manifest_digest: str = ""
    query_set_sha256: str = ""
    detector: ComponentIdentity | None = None
    recogniser: ComponentIdentity | None = None
    seal: str = ""


@dataclass(frozen=True, slots=True)
class DiagnosticTrackScore:
    """DIAGNOSTIC ONLY (D6): D at a declared diagnostic OCR floor. A distinct, unsealed type every decision refuses."""

    floor: float
    values: TrackScore


@dataclass(frozen=True, slots=True)
class _Prepared:
    track_id: str
    cluster: str
    kind: str          # "plate" | "no-plate" | "no-gt-vehicle" | "unsupported" | "unreadable"
    truth: str | None
    run: TrackRun | None


def queries_for(manifest: EvaluationManifest, expected_manifest_digest: str) -> QuerySet:
    """The D query set, generated from the manifest truths and the frozen query configuration only."""
    v = verify_manifest(manifest, expected_manifest_digest)
    truths = [t.truth.text for t in v.manifest.tracks if t.truth.state is TruthState.TEXT and t.truth.supported_text]
    return query_module.generate(truths, v.manifest.config.query, v.digest)


def _track_runs(v: _Verified, runs: Iterable[TrackRun], composition: tuple[ComponentIdentity, ComponentIdentity]
                ) -> dict[str, TrackRun]:
    """Owner invariants 3–5: exactly one sealed run per evidence Track, of this composition, on exactly its evidence;
    none for a Track without evidence (NO_RUN is derived)."""
    detector, recogniser = (_identity(composition[0], "d_detector_identity_required"),
                            _identity(composition[1], "d_recogniser_identity_required"))
    expected = [tid for tid, t in v.tracks.items() if t.has_mavi_evidence]
    by_track = _require_complete(runs, _TRACK_RUN, lambda r: r.track_id, expected, v.digest, "d")
    floor = _floor_for(v, detector)
    for tid, run in by_track.items():
        track = v.tracks[tid]
        if (run.detector, run.recogniser) != (detector, recogniser):
            raise ValueError("d_run_identity_is_not_the_composition")
        if run.mavi_track_uuid != track.mavi_track_uuid or run.evidence != track.evidence:
            raise ValueError("d_run_is_not_the_manifest_execution")
        if not is_ranking_profile(run.parameters, floor):
            raise ValueError("d_run_not_on_ranking_profile")
    return by_track


def _prepare(v: _Verified, by_track: Mapping[str, TrackRun]) -> tuple[list[_Prepared], dict]:
    prepared = []
    accounting = {"text": 0, "unsupported": 0, "unqueryable": 0, "no-plate": 0, "unreadable": 0, "no-gt-vehicle": 0}
    for tid in sorted(v.tracks):
        track = v.tracks[tid]
        run = by_track.get(tid)
        state = track.truth.state
        if state is not TruthState.TEXT:
            kind = {TruthState.NO_PLATE: "no-plate", TruthState.NO_GT_VEHICLE: "no-gt-vehicle",
                    TruthState.UNREADABLE: "unreadable"}[state]
            accounting[kind] += 1
            prepared.append(_Prepared(tid, track.site, kind, None, run))
            continue
        truth = track.truth.supported_text
        if truth is None:
            accounting["unsupported"] += 1
            prepared.append(_Prepared(tid, track.site, "unsupported", None, run))
            continue
        accounting["text"] += 1
        accounting["unqueryable"] += not queryable(truth)
        prepared.append(_Prepared(tid, track.site, "plate", truth, run))
    return prepared, accounting


def _texts(run: TrackRun | None) -> tuple[str, ...]:
    if run is None or run.record is None or run.record.outcome != TRACK_ANALYSED:
        return ()
    return tuple(text.normalised_text for text in run.record.texts)


def _rank0_sources(run: TrackRun | None) -> list[tuple[UUID, str]]:
    """N3 (owner 2026-10-14): one entry per Read plate observation, holding its RANK-0 reading normalised by v1."""
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
    if violations:
        # Nothing is published as if computed: every term and rate is None, as in A and B.
        return TrackScore(CONTRACT_FAIL, CONTRACT_FAIL, None, None, None, None, TrackCounts(), None, FAIL, None, None,
                          None, violations, dict(accounting))
    total = TrackCounts()
    for p in prepared:
        total = total + _counts(p, queries)
    plate_bearing = sum(1 for p in prepared if p.kind == "plate")
    rate = _ratio(total.consistent_wrong, plate_bearing)
    if plate_bearing < SUPPORT_FLOOR:
        cw_status = INSUFFICIENT
    else:
        cw_status = PASS if rate <= CONSISTENT_WRONG_LIMIT else FAIL
    exact, recall, precision = _d_terms(total, _contains_queries(queries))
    d = _d_score(total, _contains_queries(queries))
    return TrackScore(MEASURED, MEASURED if d is not None else INSUFFICIENT, exact, recall, precision, d, total, rate,
                      cw_status, _ratio(total.consistent_wrong, total.multi_source),
                      _ratio(total.conflicting, total.analysed), _ratio(total.no_text, total.analysed), violations,
                      dict(accounting))


def evaluate_d(manifest: EvaluationManifest, expected_manifest_digest: str, runs: Iterable[TrackRun], *,
               composition: tuple[ComponentIdentity, ComponentIdentity]) -> TrackScore:
    """D (owner N8) over EXACTLY the manifest population, for the composition whose sealed runs these are. Any contract
    violation is CONTRACT_FAIL; candidate silence scores 0."""
    v = verify_manifest(manifest, expected_manifest_digest)
    by_track = _track_runs(v, runs, composition)
    queries = queries_for(manifest, expected_manifest_digest)
    prepared, accounting = _prepare(v, by_track)
    score = replace(_score(prepared, queries, accounting), manifest_digest=v.digest,
                    query_set_sha256=queries.query_set_sha256, detector=composition[0], recogniser=composition[1])
    return _seal(_D, score)


def diagnostic_evaluate_d_at_floor(manifest: EvaluationManifest, expected_manifest_digest: str,
                                   runs: Iterable[TrackRun], floor: float, *,
                                   composition: tuple[ComponentIdentity, ComponentIdentity]) -> DiagnosticTrackScore:
    """DIAGNOSTIC ONLY (D6): D as PR-3 would publish it at another OCR floor (a ``DiagnosticTrackScore``)."""
    if floor not in DIAGNOSTIC_OCR_FLOORS:
        raise ValueError("diagnostic_floor_not_declared")
    v = verify_manifest(manifest, expected_manifest_digest)
    by_track = _track_runs(v, runs, composition)
    queries = queries_for(manifest, expected_manifest_digest)
    prepared, accounting = _prepare(v, by_track)
    refloored = []
    for p in prepared:
        run = p.run
        if run is not None and run.record is not None:
            run = replace(run, record=_refloor(run.record, floor), seal="")
        refloored.append(replace(p, run=run))
    score = _score(refloored, queries, accounting)
    return DiagnosticTrackScore(floor, replace(score, accounting={**score.accounting, "diagnosticFloor": floor}))


def evaluate_c(manifest: EvaluationManifest, expected_manifest_digest: str, runs: Iterable[TrackRun], *,
               composition: tuple[ComponentIdentity, ComponentIdentity]) -> ReadResult:
    """C: EM of the composition's own accepted plate for EXACTLY the manifest's C plates, derived from its sealed D runs
    (PR-3 selection). "Not read" arises only from the run (no accepted plate, or an abstained crop)."""
    v = verify_manifest(manifest, expected_manifest_digest)
    by_track = _track_runs(v, runs, composition)
    layer = layer_digest(manifest, expected_manifest_digest, "C")
    violations = tuple(f"{r.contract_violation}:{tid}" for tid, r in sorted(by_track.items())
                       if r.state == CONTRACT_FAIL)
    if violations:
        # Review 6, P3-1: ANY violation in the composition's runs is CONTRACT_FAIL, not only on a C plate's Track.
        return _seal(_B, ReadResult("C", CONTRACT_FAIL, violations, 0, 0, None, None, None, None, (), 0, v.digest,
                                    layer, composition[1]))
    per_plate: dict[str, tuple[PlateRecord | None, str | None]] = {}
    for pid, plate in v.c_plates.items():
        run = by_track[plate.track_id]
        if run.contract_violation is not None or run.record is None:
            per_plate[pid] = (None, run.contract_violation or "run_without_record")
            continue
        crop = next(c for c in run.record.crops if str(c.observation_id) == plate.observation_id)
        accepted = next((p for _, p in crop.plates()), None) if crop.status == CROP_SCORED else None
        per_plate[pid] = (accepted, None)
    return _reading_result("C", v, layer_digest(manifest, expected_manifest_digest, "C"), composition[1], per_plate,
                           {pid: v.c_plates[pid].text for pid in per_plate})


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
    manifest_digest: str


def _frozen_mpid(mpid: object) -> Fraction:
    if not isinstance(mpid, Fraction) or mpid != MPID:
        raise ValueError("mpid_must_be_the_frozen_fraction")
    return mpid


def percentile_indices(replicates: int) -> tuple[int, int]:
    """⌊0.025·(R−1)⌋ and ⌈0.975·(R−1)⌉ in integer arithmetic (``PERCENTILE_RULE``)."""
    return (25 * (replicates - 1)) // 1000, -((-975 * (replicates - 1)) // 1000)


def required_clusters(calibration_minimum: int) -> int:
    """Owner D7b / P-80: max(60, the frozen candidate-blind calibration minimum)."""
    if not (isinstance(calibration_minimum, int) and not isinstance(calibration_minimum, bool)
            and calibration_minimum >= 1):
        raise ValueError("calibration_minimum_invalid")
    return max(ABSOLUTE_MINIMUM_CLUSTERS, calibration_minimum)


def _draws(rng: random.Random, members: dict[str, list[int]], names: list[str]) -> list[int]:
    picked = []
    for _ in names:
        group = members[names[rng.randrange(len(names))]]
        picked.extend(group[rng.randrange(len(group))] for _ in group)
    return picked


def _bootstrap_replicates(manifest: EvaluationManifest, expected_manifest_digest: str, runs_a, runs_b, *,
                          composition_a, composition_b, replicates: int | None = None, seed: int | None = None,
                          slow: bool = False) -> list[Fraction | None]:
    """PRIVATE. Exact ΔD per replicate (sites with replacement, then Tracks within each drawn site). R and the seed
    default to the frozen configuration (tests may pass small values to prove fast = slow). A contract-violating run is
    refused, never resampled as silence."""
    v = verify_manifest(manifest, expected_manifest_digest)
    replicates = v.manifest.config.bootstrap_replicates if replicates is None else replicates
    seed = v.manifest.config.bootstrap_seed if seed is None else seed
    if not (_integer(replicates) and replicates >= 1):
        raise ValueError("bootstrap_replicates_invalid")
    queries = queries_for(manifest, expected_manifest_digest)
    pa, _ = _prepare(v, _track_runs(v, runs_a, composition_a))
    pb, _ = _prepare(v, _track_runs(v, runs_b, composition_b))
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


def paired_cluster_bootstrap(manifest: EvaluationManifest, expected_manifest_digest: str, runs_a, runs_b, *,
                             composition_a: tuple[ComponentIdentity, ComponentIdentity],
                             composition_b: tuple[ComponentIdentity, ComponentIdentity], freeze: "BaselineFreeze",
                             resolution: "BaselineResolution", layer_a_results: Sequence["LayerAResult"],
                             mpid: Fraction = MPID) -> Comparison:
    """The frozen superiority rule (owner item 2): ``superior`` iff observed ΔD ≥ MPID (exact), the paired hierarchical
    95 % percentile interval excludes zero in A's favour, and clusters ≥ max(60, the frozen calibration minimum).
    R, the seed and the calibration minimum come from the manifest configuration; the comparison re-verifies the
    resolution, which binds the freeze, which binds the manifest digest."""
    mpid = _frozen_mpid(mpid)
    v = verify_manifest(manifest, expected_manifest_digest)
    verify_resolution(freeze, resolution, layer_a_results)
    if freeze.manifest_digest != v.digest:
        raise ValueError("comparison_freeze_is_for_another_manifest")
    config = v.manifest.config
    needed = required_clusters(config.calibration_minimum_clusters)
    a = evaluate_d(manifest, expected_manifest_digest, runs_a, composition=composition_a)
    b = evaluate_d(manifest, expected_manifest_digest, runs_b, composition=composition_b)
    _refuse_benchmark_only(a, freeze)
    _refuse_benchmark_only(b, freeze)
    clusters = sorted({t.site for t in v.manifest.tracks})
    per_cluster, signs = {}, {"a": 0, "b": 0, "tie": 0, "insufficient": 0}

    def result(outcome, difference=None, lower=None, upper=None, insufficient=0):
        return Comparison(outcome, difference, lower, upper, len(clusters), needed, CLUSTER_UNIT, insufficient, signs,
                          per_cluster, v.digest)

    if a.outcome == CONTRACT_FAIL or b.outcome == CONTRACT_FAIL:
        return result("contract-fail")
    if a.d_score is None or b.d_score is None:
        return result("insufficient-evidence")
    queries = queries_for(manifest, expected_manifest_digest)
    pa, _ = _prepare(v, _track_runs(v, runs_a, composition_a))
    pb, _ = _prepare(v, _track_runs(v, runs_b, composition_b))
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
    values = _bootstrap_replicates(manifest, expected_manifest_digest, runs_a, runs_b, composition_a=composition_a,
                                   composition_b=composition_b)
    insufficient = sum(v_ is None for v_ in values)
    if insufficient:
        return result("insufficient-evidence", observed, insufficient=insufficient)
    values.sort()
    low_index, high_index = percentile_indices(len(values))
    lower, upper = values[low_index], values[high_index]
    superior = observed >= mpid and lower > 0
    return result("superior" if superior else "not-superior", observed, lower, upper)


@dataclass(frozen=True, slots=True)
class CompositionScore:
    """A composition's ranking-path D score; its ids are the sealed identities inside ``score``."""

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
# Stage 1 (at PROTOCOL_FROZEN) freezes a ``BaselineFreeze``: the eligible detector universe with exact identities, the
# OC5 benchmark-only identity, the events and gate-only composition id that M3's ``compositionSha256`` binds, the
# Layer-A gate set hash, the freeze time, the frozen evaluation manifest digest, and the ranking rule (ambiguity
# STOPS). Stage 2 derives PD_BASE mechanically (``resolve_baseline``) from Layer-A results measured on that manifest.
# The committed pre-D seal (M3 ``baseline_seal``) and Git chronology are the MANDATED #218↔M3 integration PR.

DETECTOR_RANKING_RULE = ("mavi-plate-detector-rank-v2: Layer-A gate pass required; recall at coverage desc; "
                         "false plates per crop asc; AP50 desc; missing metric sorts last; equal rank keys among the "
                         "passing detectors STOP the event (ambiguous; no id tie-break)")
DETECTOR_RANKING_RULE_SHA256 = hashlib.sha256(DETECTOR_RANKING_RULE.encode("utf-8")).hexdigest()
D_NOT_STARTED = "D_NOT_STARTED"
BASELINE_RULE = "PD_BASE+OC5 is the single hard D baseline and gates every ordinary D composition"
LAYER_A_ARTEFACT_SCHEMA = "mavi-plate-harness-layer-a-result-v1"


class BaselineStop(Exception):
    """The D event stops. There is no baseline and no D ranking. The reason is ``args[0]``."""


def m3_composition_sha256(event_id: str, composition_id: str, benchmark: ComponentIdentity, partner_event_id: str,
                          partner: ComponentIdentity) -> str:
    """Exactly M3 ``baseline_seal.composition_sha256`` (msr/m1-plate-domain-and-baseline-role @ f24dcf5e)."""
    return _canonical_sha256({"role": "gate-only-baseline-composition", "eventId": event_id,
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

    return (high(s.primary), low(s.second), high(s.third))


@dataclass(frozen=True, slots=True)
class BaselineFreeze:
    """Stage 1, frozen in the protocol at PROTOCOL_FROZEN."""
    eligible_detectors: tuple[tuple[str, str], ...]   # (detector id, M3 identitySha256), sorted, unique
    benchmark_only_id: str
    benchmark_only_identity_sha256: str
    layer_a_gates_sha256: str
    frozen_at_utc: str
    event_id: str
    composition_id: str
    partner_event_id: str
    manifest_digest: str                               # the frozen evaluation manifest (owner invariant 8)
    ranking_rule_sha256: str = DETECTOR_RANKING_RULE_SHA256

    def __post_init__(self):
        ids = [d for d, _ in self.eligible_detectors]
        if not ids or ids != sorted(set(ids)):
            raise ValueError("baseline_freeze_detectors_must_be_sorted_unique_nonempty")
        if self.benchmark_only_id in ids:
            raise ValueError("baseline_freeze_benchmark_only_component_cannot_be_a_detector_candidate")
        identities = [h for _, h in self.eligible_detectors] + [self.benchmark_only_identity_sha256]
        if len(set(identities)) != len(identities):
            raise ValueError("baseline_freeze_identity_under_two_ids")
        hashes = [h for _, h in self.eligible_detectors] + [self.benchmark_only_identity_sha256,
                                                             self.layer_a_gates_sha256, self.ranking_rule_sha256,
                                                             self.manifest_digest]
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
                                  "layerAGatesSha256": self.layer_a_gates_sha256, "frozenAtUtc": self.frozen_at_utc,
                                  "eventId": self.event_id, "compositionId": self.composition_id,
                                  "partnerEventId": self.partner_event_id, "manifestDigest": self.manifest_digest,
                                  "rankingRuleSha256": self.ranking_rule_sha256, "baselineRule": BASELINE_RULE})


@dataclass(frozen=True, slots=True)
class LayerAResult:
    """One eligible detector's Layer-A result: its sealed A component score (on the frozen manifest) and the frozen
    gates' verdict (``gates_passed``, caller-provided until the M3 integration)."""
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


def layer_a_result_document(freeze: BaselineFreeze, results: Sequence[LayerAResult]) -> dict:
    """The canonical Layer-A result artefact #218 emits (owner invariant 9), derived from the frozen manifest.

    Its per-partner rows use M3's ``layer_a_result_document`` keys (candidateId, identitySha256, gates, rankKey,
    measurementSha256) and ``evidenceSha256`` = the manifest digest. The event-level M3 fields (eventId, compositionId,
    partner frozen-ledger hash, gate ids) and the per-gate dictionary are reconciled in the mandated #218↔M3
    integration PR: until then ``gates`` holds the single frozen Layer-A verdict, and the hash differs from M3's."""
    rows = [{"candidateId": r.score.candidate_id, "identitySha256": r.identity_sha256,
             "gates": {"layer-a": "passed" if r.gates_passed else "failed"},
             "rankKey": [None if v is None else repr(v) for v in (r.score.primary, r.score.second, r.score.third)],
             "measurementSha256": r.score.measurement_sha256} for r in results]
    return {"schema": LAYER_A_ARTEFACT_SCHEMA, "layerAGatesSha256": freeze.layer_a_gates_sha256,
            "partnerRankingRuleSha256": freeze.ranking_rule_sha256, "partnerEventId": freeze.partner_event_id,
            "results": sorted(rows, key=lambda r: r["candidateId"]), "evidenceSha256": freeze.manifest_digest}


def layer_a_result_sha256(freeze: BaselineFreeze, results: Sequence[LayerAResult]) -> str:
    return _canonical_sha256(layer_a_result_document(freeze, results))


def resolve_baseline(freeze: BaselineFreeze, results: Sequence[LayerAResult], *, d_rows_read: int,
                     resolved_at_utc: str) -> BaselineResolution:
    """Stage 2. Derive PD_BASE mechanically from the frozen rule. It raises ``BaselineStop`` and never chooses."""
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
        raise BaselineStop("layer_a_result_inconsistent_with_frozen_detector_universe")
    for r in results:
        if not _is_sealed(_COMPONENT, r.score):
            raise BaselineStop(f"layer_a_result_not_from_ranking_path:{r.score.candidate_id}")
        if r.score.kind != "detector":
            raise BaselineStop(f"layer_a_result_not_a_detector_result:{r.score.candidate_id}")
        if r.score.manifest_digest != freeze.manifest_digest:
            raise BaselineStop(f"layer_a_result_not_on_the_frozen_manifest:{r.score.candidate_id}")
        if r.identity_sha256 != eligible[r.score.candidate_id] or r.score.identity_sha256 != r.identity_sha256:
            raise BaselineStop(f"layer_a_identity_mismatch:{r.score.candidate_id}")
        if r.gates_passed and r.score.contract_fail:
            raise BaselineStop(f"layer_a_result_inconsistent_gate_pass_with_contract_fail:{r.score.candidate_id}")
        if r.gates_passed and any(v is not None and not math.isfinite(v)
                                  for v in (r.score.primary, r.score.second, r.score.third)):
            raise BaselineStop(f"layer_a_rank_ambiguous_non_finite_metric:{r.score.candidate_id}")
    survivors = sorted((r.score for r in results if r.gates_passed), key=lambda s: (_detector_key(s), s.candidate_id))
    if not survivors:
        raise BaselineStop("no_detector_passed_layer_a")
    if len(survivors) > 1 and _detector_key(survivors[0]) == _detector_key(survivors[1]):
        raise BaselineStop("layer_a_rank_ambiguous")  # owner N2 addendum and M3: ambiguity stops, no id tie-break
    pd_base = survivors[0].candidate_id
    composition = m3_composition_sha256(freeze.event_id, freeze.composition_id, freeze.benchmark,
                                        freeze.partner_event_id, ComponentIdentity(pd_base, eligible[pd_base]))
    unsealed = BaselineResolution(
        freeze_sha256=freeze.freeze_sha256(), pd_base_id=pd_base, pd_base_identity_sha256=eligible[pd_base],
        benchmark_only_id=freeze.benchmark_only_id,
        benchmark_only_identity_sha256=freeze.benchmark_only_identity_sha256,
        layer_a_result_sha256=layer_a_result_sha256(freeze, results), ranking_rule_sha256=freeze.ranking_rule_sha256,
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
    if sealed != current:
        raise BaselineStop("baseline_resolution_changed_after_seal")


def _refuse_benchmark_only(score: TrackScore, freeze: BaselineFreeze) -> None:
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
    """N2 (revised): ONE hard gate against the sealed baseline composition PD_BASE + OC5: observed
    D − D(PD_BASE + OC5) ≥ MPID (exact). A composition contract violation is FAIL; a baseline contract failure or a
    non-evaluable baseline stops the event; a silent baseline scores 0; a corpus-deficient composition is
    INSUFFICIENT_EVIDENCE. Both scores must be on the freeze's manifest."""
    mpid = _frozen_mpid(mpid)
    verify_resolution(freeze, resolution, layer_a_results)
    base = _require_d(baseline.score, "gate_baseline_score_not_a_ranking_d_score")
    candidate = _require_d(composition.score, "gate_composition_score_not_a_ranking_d_score")
    if base.recogniser != freeze.benchmark or _composition_of(base, freeze) != resolution.composition_sha256:
        raise ValueError("baseline_is_not_the_sealed_pd_base_composition")
    _refuse_benchmark_only(candidate, freeze)
    if not (candidate.manifest_digest == base.manifest_digest == freeze.manifest_digest
            and candidate.query_set_sha256 == base.query_set_sha256):
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
    """Exactly the ordinary compositions that PASS the single baseline gate; the benchmark-only component is refused."""
    out = []
    for composition in compositions:
        _refuse_benchmark_only(composition.score, freeze)
        if baseline_gate(composition, baseline, resolution, freeze, layer_a_results) == PASS:
            out.append(composition)
    return out


def diagnostic_ocr_uplift(composition: CompositionScore, matched_baseline: CompositionScore,
                          freeze: BaselineFreeze) -> Fraction | None:
    """DIAGNOSTIC ONLY (N2 revised): D(PDx + OCy) − D(PDx + OC5) at a fixed detector, on the same manifest."""
    a = _require_d(composition.score, "diagnostic_uplift_score_not_a_ranking_d_score")
    b = _require_d(matched_baseline.score, "diagnostic_uplift_score_not_a_ranking_d_score")
    if b.detector != a.detector or b.recogniser != freeze.benchmark:
        raise ValueError("diagnostic_baseline_not_detector_matched")
    if (a.manifest_digest, a.query_set_sha256) != (b.manifest_digest, b.query_set_sha256):
        raise ValueError("diagnostic_scores_not_on_the_same_population_and_query_set")
    if CONTRACT_FAIL in (a.outcome, b.outcome) or a.d_score is None or b.d_score is None:
        return None
    return a.d_score - b.d_score
