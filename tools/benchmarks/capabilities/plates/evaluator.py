"""Stage-4 model-selection evaluators A–D (plan §4.4), built on PR-3's merged plate rules, behind ONE trust boundary:

    canonical bytes → identity verification → strict parse → harness-owned immutable state → A/B/C/D

These are the evaluators plan §7 assigned to PR-1 and PR-1 omitted (register: *Correction and repair record*). The owner
decisions they encode are written in `docs/qualification/stage4/plate-selection-decision-record-2026-10-14.md` (§4a
describes this boundary). **#218 is the level-1 A–D / query harness only.** The M3 pre-D seal integration is a MANDATED
follow-up PR before PR-2 cold review 1 and ``PROTOCOL_FROZEN``.

**Governing invariant (owner).** "For fixed frozen canonical protocol/corpus bytes and fixed candidate outputs, no
caller-controlled object, subclass, property, method, iterable, parser ambiguity, configuration value, ordering, seed,
partition representation, or mutable state may alter population membership, eligibility, evidence, partition
assignment, candidate eligibility, or any A/B/C/D result."

**1. Verified bundle** (``selection_bundle``). The loader reads the committed freeze record at a fixed repository
path (by blob id, add-only across the full history, M3's isolated Git profile). The record holds the protocol, the
rosters (with each component's predeclared N4 independence verdict), the partition plan, the corpus document hashes and
the freeze-time disjointness result. The loader reads only the documents its stage needs, verifies their exact bytes,
parses them strictly, and builds private immutable state. A ``Bundle`` is only a handle: its id string selects that
state. No caller object, configuration value or expected digest enters.

**Stages** (owner points 2, 4 and 5):
- ``load_selection_bundle``: record + A/B documents only (no D path is opened);
- ``load_d_capture_bundle``: adds the D index (evidence, no truth) for candidate execution on D evidence;
- ``load_protected_d_bundle``: adds the D truth for scoring; after it no candidate can execute in the process.
Both D loaders require the verified Stage-2 resolution AND the protected-D authority, which #218 does not integrate, so
they fail closed (``protected_d_not_authorised:m3_authority_not_integrated``) until the mandated M3 integration PR.

**2. Execution envelopes** (``run_track``, ``run_detection``, ``run_reading``). They take a bundle and an item id,
never evidence. The harness:
- reads the exact prescribed image bytes (exact ``bytes``, verified by SHA-256 and size);
- runs the guarded candidate on the ranking profile at the frozen floor of a rostered identity;
- records the result in a private registry.

The caller receives a copy that carries a ``result_id``.

**3. Metrics and decisions** read ONLY harness state:
- every run or result argument is materialised once, and only its ``result_id`` string is read;
- the registry's own record is scored, so edits to a returned copy, subclasses, properties and re-iterables are
  inert;
- item ids must EQUAL the bundle's projection exactly;
- compositions and components must be in the frozen rosters (id AND identity SHA-256);
- queries, seeds, R, K, the support floor, MPID and the calibration minimum come from the frozen record only;
- TruthState is authoritative: no metric re-normalises raw truth.

**Kept unchanged:**
- D-score (owner N8) and silence = 0;
- CONTRACT_FAIL (any output-contract violation, bake-off rule);
- MPID 0.04 exact and the superiority rule;
- N3 rank-0;
- the single PD_BASE + OC5 gate with two-stage resolution (ambiguous → STOP);
- the two-stage bootstrap with R = 1,000 and integer percentile indices (24, 975).

**Caller-provided (complete list):**
1. the candidate under test: its callables (and so its outputs) and its asserted ``ComponentIdentity``, which must
   equal a rostered identity;
2. the image byte source. Its bytes are verified against the frozen SHA-256 and size;
3. the corpus directory. Its documents are verified against the committed record;
4. the Layer-A ``gates_passed`` verdict per eligible detector. It feeds only the Stage-2 derivation (a harness record
   that is not authority): it cannot open D, because both D loaders also require the protected-D authority, which
   fails closed until the M3 integration derives the gate results from the committed component ranking. (The N4
   ``independent`` verdict is no longer a caller value: it is predeclared in the frozen record.);
5. ``resolve_baseline``'s ``d_rows_read`` and ``resolved_at_utc``: reporting-only. A non-zero ``d_rows_read`` or a
   time before the freeze can only STOP; ``resolved_at_utc`` is only recorded. Neither can enable anything: Stage 2
   refuses on the harness's own fact that D data of the record was opened in this process, whatever is claimed;
6. the protected-D ``authorization`` (refused in #218; see above);
7. ``repo_root`` (tests only; the default is the harness's own repository), whose committed record is the identity.

**Disclosed limit:** an in-process caller can still write the private registries (``_register``, ``_BUNDLES``,
``_D_TRUTH_LOADED``) or replace module functions. The boundary protects reproducibility through the supported API, not
against code running in the same interpreter; in particular a candidate's own process could read the D files directly
from disk, which only the protected-D storage and authority of the integration PR can prevent.
"""

from __future__ import annotations

import copy
import hashlib
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
from tools.benchmarks.capabilities.plates import selection_bundle as sb
from tools.benchmarks.capabilities.plates.queries import CONTAINS, EXACT, QuerySet, matches, queryable
from tools.benchmarks.capabilities.plates.selection_bundle import (  # noqa: F401 - the public boundary
    BOOTSTRAP_REPLICATES,
    DETECTOR_RANKING_RULE,
    DETECTOR_RANKING_RULE_SHA256,
    FREEZE_RECORD_PATH,
    PERCENTILE_RULE,
    TOP_K,
    TOP_K_SUPPORT_FLOOR,
    Bundle,
    Partition,
    TruthState,
    canonical_bytes,
    classify_truth,
    is_reserved_truth_text,
    load_selection_bundle,
    parse_canonical,
)

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

PASS, FAIL, INSUFFICIENT = "PASS", "FAIL", "INSUFFICIENT_EVIDENCE"
MEASURED, CONTRACT_FAIL, COMPLETED = "MEASURED", "CONTRACT_FAIL", "COMPLETED"
HARNESS_FAULT = "HARNESS_FAULT"   # a run the harness could not account for: never COMPLETED, never scored (N9 rerun)

_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_CANDIDATE_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _is_sha256(value: object) -> bool:
    return type(value) is str and bool(_SHA_RE.match(value))


def _canonical_sha256(payload: object) -> str:
    """M3 ``credibility.document_sha256`` form: canonical JSON plus one LF."""
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def _fail(code: str):
    raise ValueError(code)


def _probability(value: object) -> bool:
    """Total: never raises. An exact ``int`` is compared exactly (no float conversion, so ``10**400`` cannot
    overflow); an exact ``float`` must lie in [0, 1] (NaN and ±inf fail the comparisons); any other type, including
    ``bool`` and every subclass, is not a probability."""
    kind = type(value)
    if kind is int:
        return 0 <= value <= 1
    if kind is float:
        return 0.0 <= value <= 1.0
    return False


def _integer(value: object) -> bool:
    return type(value) is int


def _ratio(numerator: int, denominator: int) -> Fraction | None:
    return Fraction(numerator, denominator) if denominator else None


def normalised_text(raw: str) -> str | None:
    """v1 normalisation of a CANDIDATE reading (never of truth: truth is typed once by the loader)."""
    result = normalise(raw)
    return result.normalised if result.outcome == OK else None


# ---------------------------------------------------------------------------------------------- the result registry
#
# Every harness result is recorded here and the caller receives a deep copy carrying its ``result_id``. Metrics and
# decisions look the id up and use the registry's own record, so nothing else about a caller object is ever read.

_RESULTS: dict[str, tuple[str, object]] = {}
_TRACK_RUN, _A_RUN, _B_RUN, _A, _B, _COMPONENT, _D, _CMP, _RES = (
    "track-run", "detection-run", "reading-run", "detection", "reading", "component", "d-score", "comparison",
    "resolution")


def _register(kind: str, obj):
    """PRIVATE: record a harness result and return the caller's copy. Tests use it to build metric fixtures."""
    result_id = secrets.token_hex(16)
    stored = replace(obj, result_id=result_id)
    _RESULTS[result_id] = (kind, stored)
    return copy.deepcopy(stored)


def _lookup(kind: str, obj: object, code: str):
    result_id = getattr(obj, "result_id", None)
    entry = _RESULTS.get(result_id) if type(result_id) is str else None
    if entry is None or entry[0] != kind:
        _fail(code)
    return entry[1]


def _materialise(values: object, code: str) -> list:
    """Owner R1: every iterable argument is consumed exactly once, at entry."""
    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        _fail(code)
    return list(values)


# ---------------------------------------------------------------------------------------------- identities


@dataclass(frozen=True, slots=True)
class ComponentIdentity:
    """A candidate component. ``identity_sha256`` is M3's ``identitySha256``. A caller-supplied identity is only a claim:
    the harness reads its two strings and requires them to equal a frozen roster entry."""

    candidate_id: str
    identity_sha256: str

    def __post_init__(self):
        if not (type(self.candidate_id) is str and _CANDIDATE_RE.match(self.candidate_id)):
            raise ValueError("component_identity_id_malformed")
        if not _is_sha256(self.identity_sha256):
            raise ValueError("component_identity_sha256_malformed")


def _claim(value: object, code: str) -> tuple[str, str]:
    cid, sha = getattr(value, "candidate_id", None), getattr(value, "identity_sha256", None)
    if type(cid) is not str or type(sha) is not str:
        _fail(code)
    return cid, sha


def _rostered(value: object, universe: Mapping[str, str], code: str) -> ComponentIdentity:
    """Owner R3: the identity must be a frozen roster entry by id AND identity SHA-256; the harness's own copy is used."""
    cid, sha = _claim(value, f"{code}_identity_required")
    if universe.get(cid) != sha:
        _fail(f"{code}_not_in_the_frozen_roster")
    return ComponentIdentity(cid, sha)


def _detectors(state) -> Mapping[str, str]:
    return state.roster.detectors


def _recognisers(state, *, benchmark: bool) -> Mapping[str, str]:
    out = dict(state.roster.recognisers)
    if benchmark:
        out[state.roster.benchmark_id] = state.roster.benchmark_sha256
    return out


def _composition(state, composition: object, code: str) -> tuple[ComponentIdentity, ComponentIdentity]:
    pair = _materialise(composition, f"{code}_composition_malformed")
    if len(pair) != 2:
        _fail(f"{code}_composition_malformed")
    return (_rostered(pair[0], _detectors(state), f"{code}_detector"),
            _rostered(pair[1], _recognisers(state, benchmark=True), f"{code}_recogniser"))


# ---------------------------------------------------------------------------------------------- bundle projections


def _part(state, partition: Partition, code: str, *, truth: bool = True):
    part = state.part(partition)
    if truth and not part.truth_loaded:
        _fail(f"{code}_requires_the_protected_d_bundle")   # the selection stage never reads the D truth
    return part


def layer_digest(bundle: object, layer: str) -> str:
    """The digest of a layer's frozen projection (A crops, B plates, C plates, D Tracks)."""
    return _layer_digest(sb._state_of(bundle), layer)


def _layer_digest(state, layer: str) -> str:
    if layer not in ("A", "B", "C", "D"):
        _fail("layer_unknown")
    part = state.d if layer == "D" else state.ab
    if not part.index_loaded:
        _fail("layer_d_requires_a_protected_d_stage")   # the selection stage never opens the D index
    rows = {"A": sorted(part.crops), "B": sorted(part.b_plates), "C": sorted(part.c_plates),
            "D": sorted(part.tracks)}[layer]
    return _canonical_sha256({"partition": part.digest, "layer": layer, "items": rows})


def queries_for(bundle: object, partition: Partition = Partition.PROTECTED_D) -> QuerySet:
    """The query set, generated from the partition's typed TEXT truths and the frozen query configuration only."""
    return _queries(sb._state_of(bundle), partition)


def _queries(state, partition: Partition) -> QuerySet:
    if partition not in (Partition.AB_SELECTION, Partition.PROTECTED_D):
        _fail("queries_partition_unknown")
    part = _part(state, partition, "queries")
    truths = [t.supported for t in part.tracks.values() if t.state is TruthState.TEXT]
    return query_module.generate(truths, state.protocol.query, part.digest)


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
    """The bake-off detector contract: an exact list/tuple of at most ``bound`` exact ``PlateBox`` with exact-int
    geometry inside the crop and a score in [0, 1]."""
    if type(boxes) not in (list, tuple):
        return "plate_detector_output_invalid@not_a_list"
    if len(boxes) > bound:
        return f"plate_detector_output_exceeds_bound@count={len(boxes)}"
    for index, box in enumerate(boxes):
        if type(box) is not PlateBox:
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
    """The bake-off recogniser contract: an exact list/tuple of at most ``bound`` exact ``Reading`` with exact-``str``
    valid raw text, a confidence in [0, 1] and a strict rank order. In the PRODUCT a non-strict order is a crop
    abstention; in the BAKE-OFF it is a FAIL."""
    if type(readings) not in (list, tuple):
        return "plate_recogniser_output_invalid@not_a_list"
    if len(readings) > bound:
        return f"plate_recogniser_output_exceeds_bound@count={len(readings)}"
    for index, reading in enumerate(readings):
        if type(reading) is not Reading:
            return f"plate_recogniser_output_invalid@item={index}:not_a_reading"
        if type(reading.raw_text) is not str or not is_raw_text(reading.raw_text):
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


# Candidate code may raise ANY BaseException, including one whose ``__str__``/``__repr__``, class name or metaclass is
# hostile. The evidence formatter below cannot fail: the message is ``BaseException.__str__`` (the exception's ``args``;
# the candidate's own ``__str__``/``__repr__`` is never called), the class name is read through ``type``'s own slot (a
# metaclass cannot intercept it), both inside a ``BaseException`` catch, and any failure or non-``str`` result becomes
# a stable placeholder.
#
# THE CANDIDATE BOUNDARY (``_guarded``; cold reviews of 5735c63c P2-1 and df921fa6 P2, one root cause: the harness
# assumed its own handling of candidate-controlled values never raises, and PR-3's broad product handler turned any
# such exception into a silent, scored abstention). One boundary encloses everything that touches candidate-controlled
# values: the call, the output validation and the copy into harness-owned values. Any BaseException anywhere inside it
# flags the guard FIRST, so it is a CONTRACT_FAIL (decision record, Contract row), never a COMPLETED run. Behind it,
# the validators are total (they never raise), and a backstop refuses to call a run COMPLETED unless every crop was
# scored with nothing flagged: anything PR-3 did not score without a harness flag is HARNESS_FAULT, never scored.
# ``KeyboardInterrupt`` and ``SystemExit`` raised inside candidate code are recorded as CONTRACT_FAIL for that run and
# then re-raised, so an operator interrupt or a process exit is honoured. A later rerun of that run can still produce a
# COMPLETED record: limiting reruns (N9: one, for a proven infrastructure fault with identical bytes and configuration)
# is procedural and belongs to the event integration (decision record §6, disclosed residual).
_UNPRINTABLE, _NON_STR = "<unprintable>", "<non-str>"
_ABORTS = (KeyboardInterrupt, SystemExit)
_TYPE_NAME = type.__dict__["__name__"]


def _safe_text(read: Callable[[], object]) -> str:
    try:
        value = read()
    except BaseException:  # noqa: BLE001 - a hostile __str__/__name__ must never escape the formatter
        return _UNPRINTABLE
    return value if type(value) is str else _NON_STR


def _exception_evidence(exc: BaseException) -> str:
    """``<class name>:<message>`` of a candidate exception; never raises, never returns a non-``str``."""
    cls = type(exc)
    name = _safe_text(lambda: _TYPE_NAME.__get__(cls, type))
    message = _safe_text(lambda: BaseException.__str__(exc))
    return f"{name}:{message[:160]}"


_NO_OUTPUT = object()   # the boundary's "violation recorded, no usable output" result


def _guarded(guard: _Guard, component: str, where: str, call: Callable[[], object],
             validate: Callable[[object], str | None], copy: Callable[[object], object]) -> object:
    """THE candidate boundary. ``call`` runs the candidate, ``validate`` checks its output (a violation is flagged and
    ``_NO_OUTPUT`` returned), ``copy`` turns valid output into harness-owned values. Any BaseException raised in any of
    the three flags the guard FIRST (``plate_<component>_<phase>@<where>:<evidence>``), then propagates."""
    phase = "runtime_error"
    try:
        output = call()
        phase = "output_unvalidatable"
        violation = validate(output)
        if violation is not None:
            guard.flag(f"{violation}:{where}")
            return _NO_OUTPUT
        phase = "output_uncopyable"
        return copy(output)
    except BaseException as exc:  # noqa: BLE001 - flagged FIRST (a FAIL), then re-raised by the caller's rule
        guard.flag(f"plate_{component}_{phase}@{where}:{_exception_evidence(exc)}")
        raise


class _CheckedDetector:
    """The candidate detector behind the boundary; PR-3 sees ONE harness-owned copy of valid output, else ``[]``."""

    def __init__(self, inner: PlateDetector, guard: _Guard, bound: int) -> None:
        self.inner, self.guard, self.bound = inner, guard, bound

    def detect(self, crop, verified: VerifiedCrop):
        width, height = crop.size   # the harness-decoded image
        out = _guarded(self.guard, "detector", f"obs={verified.observation_id}",
                       lambda: self.inner.detect(crop, verified),
                       lambda boxes: detector_output_violation(boxes, width, height, self.bound), list)
        return [] if out is _NO_OUTPUT else out


class _CheckedRecogniser:
    def __init__(self, inner: PlateRecogniser, guard: _Guard, bound: int) -> None:
        self.inner, self.guard, self.bound = inner, guard, bound

    def read(self, region, verified: VerifiedCrop, box: PlateBox):
        out = _guarded(self.guard, "recogniser", f"obs={verified.observation_id}",
                       lambda: self.inner.read(region, verified, box),
                       lambda readings: recogniser_output_violation(readings, self.bound), list)
        return [] if out is _NO_OUTPUT else out


# ---------------------------------------------------------------------------------------------- execution envelopes

ImageSource = Callable[[str, str], bytes]   # (observation id, SHA-256) → the exact image bytes


def _executable(bundle: object):
    """The state of a bundle on which candidate code may run: never the protected-D (truth) stage."""
    state = sb._state_of(bundle)
    if state.stage == sb.PROTECTED:
        _fail("candidate_execution_on_the_protected_d_bundle")
    return state


def _image_bytes(images: ImageSource, ref) -> bytes:
    """The harness reads the prescribed image and verifies the exact ``bytes``. A mismatch is a corpus integrity
    failure (the run is refused), never a candidate result."""
    content = images(ref.observation_id, ref.sha256)
    if type(content) is not bytes or len(content) != ref.size_bytes \
            or hashlib.sha256(content).hexdigest() != ref.sha256:
        _fail("corpus_image_integrity_failed")
    return content


def _floor(state, detector: ComponentIdentity) -> float:
    return state.protocol.floors[detector.candidate_id]


@dataclass(frozen=True, slots=True)
class EvidenceImage:
    """A copy of one frozen evidence image (informational)."""

    observation_id: str
    role: str
    evidence_rank: int
    sha256: str
    size_bytes: int


def _evidence(images) -> tuple[EvidenceImage, ...]:
    return tuple(EvidenceImage(e.observation_id, e.role, e.rank, e.sha256, e.size_bytes) for e in images)


@dataclass(frozen=True, slots=True)
class TrackRun:
    """The D/C execution of one composition on one Track's exact evidence (registry record or a caller's copy)."""

    partition_digest: str
    track_id: str
    mavi_track_uuid: str
    evidence: tuple[EvidenceImage, ...]
    detector: ComponentIdentity
    recogniser: ComponentIdentity
    parameters: PlateParameters
    state: str                      # COMPLETED | CONTRACT_FAIL | HARNESS_FAULT
    record: TrackRecord | None
    contract_violation: str | None
    result_id: str = ""


def lease_observation(observation_id, role: str, evidence_rank: int, size_bytes: int, sha256: str) -> LeaseObservation:
    return LeaseObservation.model_validate({"observationId": observation_id, "role": role,
                                            "evidenceRank": evidence_rank, "sizeBytes": size_bytes, "sha256": sha256})


def _track(state, track_id: object, code: str):
    if type(track_id) is not str:
        _fail(f"{code}_track_not_in_bundle")
    for part in (state.ab, state.d):
        track = part.tracks.get(track_id)
        if track is not None:
            return part, track
    _fail(f"{code}_track_not_in_bundle")


def run_track(bundle: object, track_id: str, *, detector: PlateDetector, recogniser: PlateRecogniser,
              detector_identity: ComponentIdentity, recogniser_identity: ComponentIdentity,
              images: ImageSource) -> TrackRun:
    """Run PR-3 with the guarded candidate on EXACTLY the frozen Track's evidence, at the frozen floor. A protected-D
    Track runs only from the D-capture bundle (D evidence, no D truth); no candidate runs once D truth is loaded."""
    with sb._candidate_execution():
        return _run_track(bundle, track_id, detector, recogniser, detector_identity, recogniser_identity, images)


def _run_track(bundle, track_id, detector, recogniser, detector_identity, recogniser_identity, images) -> TrackRun:
    state = _executable(bundle)
    det = _rostered(detector_identity, _detectors(state), "run_detector")
    rec = _rostered(recogniser_identity, _recognisers(state, benchmark=True), "run_recogniser")
    part, track = _track(state, track_id, "run")
    if part.partition is Partition.PROTECTED_D and state.stage != sb.D_CAPTURE:
        _fail("run_d_track_requires_the_d_capture_bundle")
    if not track.has_mavi_evidence:
        _fail("run_track_has_no_mavi_evidence")  # NO_RUN is derived from the bundle, never executed
    parameters = ranking_parameters(_floor(state, det))
    contents = [_image_bytes(images, ref) for ref in track.evidence]
    observations = tuple(lease_observation(UUID(e.observation_id), e.role, e.rank, e.size_bytes, e.sha256)
                         for e in track.evidence)
    lease = LeaseTrack.model_validate({"trackId": UUID(track.mavi_track_uuid), "objectClass": "vehicle",
                                       "observations": observations})
    guard = _Guard()
    checked_detector = _CheckedDetector(detector, guard, parameters.max_detections_per_crop)
    checked_recogniser = _CheckedRecogniser(recogniser, guard, parameters.max_readings_per_plate)

    def result(run_state, record, violation):
        return _register(_TRACK_RUN, TrackRun(part.digest, track.track_id, track.mavi_track_uuid,
                                              _evidence(track.evidence), det, rec, parameters, run_state, record,
                                              violation))

    def unaccounted(where: str, what: str):
        return result(HARNESS_FAULT, None, f"harness_fault@{where}:{what}")

    records = []
    for ref, content, observation in zip(track.evidence, contents, observations):
        verified = VerifiedCrop(ref.observation_id, ref.role, ref.rank, ref.sha256, content)
        where = f"obs={ref.observation_id}"
        try:
            record = analyse_crop(observation, verified, checked_detector, checked_recogniser, parameters)
        except BaseException as exc:  # noqa: BLE001 - PR-3 raised (OutputInvalid) or a raise passed its handlers
            if guard.violation is not None:
                failed = result(CONTRACT_FAIL, None, guard.violation)
            else:
                failed = unaccounted(where, f"raised:{_exception_evidence(exc)}")
            if isinstance(exc, _ABORTS):
                raise
            return failed
        if guard.violation is not None:
            return result(CONTRACT_FAIL, None, guard.violation)
        if record.status != CROP_SCORED:
            # Backstop (invariant 3): no PR-3 non-scored outcome — the abstentions decode_failed, detector_error,
            # ocr_error, ocr_output_invalid, or an unavailability — can occur here without a harness flag, because the
            # boundary hands PR-3 only verified bytes and valid, copied output. Reaching it means the boundary was
            # bypassed: the run is unaccounted, never COMPLETED and never scored.
            return unaccounted(where, f"crop_{record.status}:{record.reason}")
        records.append(record)
    try:
        summary = summarise_track(lease, tuple(records))
    except BaseException as exc:  # noqa: BLE001 - harness-owned records only: an unaccounted fault
        failed = unaccounted("track", f"summary:{_exception_evidence(exc)}")
        if isinstance(exc, _ABORTS):
            raise
        return failed
    return result(COMPLETED, summary, None)


@dataclass(frozen=True, slots=True)
class DetectionRun:
    """The A execution of one detector on one frozen crop."""

    partition_digest: str
    crop_id: str
    image: EvidenceImage
    detector: ComponentIdentity
    detector_floor: float
    state: str
    proposals: tuple[tuple[int, int, int, int, float], ...]
    crop_size: tuple[int, int] | None
    contract_violation: str | None
    result_id: str = ""


def _evidence_of(part, track_id: str, observation_id: str):
    return next(e for e in part.tracks[track_id].evidence if e.observation_id == observation_id)


def run_detection(bundle: object, crop_id: str, *, detector: PlateDetector, detector_identity: ComponentIdentity,
                  images: ImageSource) -> DetectionRun:
    """Run the guarded detector on EXACTLY the frozen crop's evidence image (A/B partition only)."""
    with sb._candidate_execution():
        return _run_detection(bundle, crop_id, detector, detector_identity, images)


def _run_detection(bundle, crop_id, detector, detector_identity, images) -> DetectionRun:
    state = _executable(bundle)
    det = _rostered(detector_identity, _detectors(state), "run_detector")
    crop = state.ab.crops.get(crop_id) if type(crop_id) is str else None
    if crop is None:
        _fail("run_crop_not_in_bundle")
    ref = _evidence_of(state.ab, crop.track_id, crop.observation_id)
    floor = _floor(state, det)
    content = _image_bytes(images, ref)
    try:
        image = decode_crop(content)
    except CropDecodeError as exc:
        raise ValueError("corpus_image_undecodable") from exc
    width, height = image.size
    verified = VerifiedCrop(ref.observation_id, ref.role, ref.rank, ref.sha256, content)

    def result(run_state, proposals, violation):
        return _register(_A_RUN, DetectionRun(state.ab.digest, crop.crop_id, _evidence((ref,))[0], det, floor,
                                              run_state, proposals, (width, height), violation))

    guard, where = _Guard(), f"obs={ref.observation_id}"
    try:
        out = _guarded(guard, "detector", where, lambda: detector.detect(image, verified),
                       lambda boxes: detector_output_violation(boxes, width, height, MAXIMUM_DETECTIONS_PER_CROP),
                       lambda boxes: tuple((b.x, b.y, b.width, b.height, float(b.score)) for b in boxes))
    except BaseException as exc:  # noqa: BLE001 - recorded, never leaked (aborts re-raised after recording)
        if guard.violation is not None:
            failed = result(CONTRACT_FAIL, (), guard.violation)
        else:
            failed = result(HARNESS_FAULT, (), f"harness_fault@{where}:raised:{_exception_evidence(exc)}")
        if isinstance(exc, _ABORTS):
            raise
        return failed
    if guard.violation is not None:
        return result(CONTRACT_FAIL, (), guard.violation)
    return result(COMPLETED, out, None)


@dataclass(frozen=True, slots=True)
class ReadRun:
    """The B execution of one recogniser on one frozen GT plate crop."""

    partition_digest: str
    plate_id: str
    image: EvidenceImage
    recogniser: ComponentIdentity
    state: str
    plate: PlateRecord | None
    contract_violation: str | None
    result_id: str = ""


def _rank_plate(readings: Sequence[Reading], parameters: PlateParameters) -> PlateRecord:
    """PR-3's ranking through its public contract (equal to ``pipeline._plate``, proven by test)."""
    ordered = sorted(readings, key=lambda item: reading_rank_key(item.confidence, item.raw_text))
    ranked = tuple(RankedReading(rank, item.raw_text, raw_line_count(item.raw_text), float(item.confidence))
                   for rank, item in enumerate(ordered))
    outcome = PLATE_READ if ranked and ranked[0].confidence >= parameters.ocr_confidence_floor else PLATE_UNREADABLE
    return PlateRecord(0, outcome, ranked)


def run_reading(bundle: object, plate_id: str, *, recogniser: PlateRecogniser,
                recogniser_identity: ComponentIdentity, images: ImageSource) -> ReadRun:
    """Run the guarded recogniser on EXACTLY the frozen GT plate crop (whole image as the plate region; A/B only)."""
    with sb._candidate_execution():
        return _run_reading(bundle, plate_id, recogniser, recogniser_identity, images)


def _run_reading(bundle, plate_id, recogniser, recogniser_identity, images) -> ReadRun:
    state = _executable(bundle)
    rec = _rostered(recogniser_identity, _recognisers(state, benchmark=True), "run_recogniser")
    plate = state.ab.b_plates.get(plate_id) if type(plate_id) is str else None
    if plate is None:
        _fail("run_plate_not_in_bundle")
    ref = plate.image
    content = _image_bytes(images, ref)
    try:
        image = decode_crop(content)
    except CropDecodeError as exc:
        raise ValueError("corpus_image_undecodable") from exc
    verified = VerifiedCrop(ref.observation_id, ref.role, ref.rank, ref.sha256, content)

    def result(run_state, record, violation):
        return _register(_B_RUN, ReadRun(state.ab.digest, plate.plate_id, _evidence((ref,))[0], rec, run_state, record,
                                         violation))

    guard, where = _Guard(), f"obs={ref.observation_id}"
    whole = PlateBox(0, 0, image.size[0], image.size[1], 1.0)
    try:
        out = _guarded(guard, "recogniser", where, lambda: recogniser.read(image, verified, whole),
                       lambda readings: recogniser_output_violation(readings, MAXIMUM_READINGS_PER_PLATE),
                       lambda readings: _rank_plate(list(readings), ranking_parameters(0.0)))
    except BaseException as exc:  # noqa: BLE001 - recorded, never leaked (aborts re-raised after recording)
        if guard.violation is not None:
            failed = result(CONTRACT_FAIL, None, guard.violation)
        else:
            failed = result(HARNESS_FAULT, None, f"harness_fault@{where}:raised:{_exception_evidence(exc)}")
        if isinstance(exc, _ABORTS):
            raise
        return failed
    if guard.violation is not None:
        return result(CONTRACT_FAIL, None, guard.violation)
    return result(COMPLETED, out, None)


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
    """DIAGNOSTIC ONLY: readings ranked at a declared diagnostic OCR floor (an unregistered PlateRecord)."""
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
    partition_digest: str
    layer_digest: str
    detector: ComponentIdentity
    result_id: str = ""


def _require_complete(runs: list, kind: str, id_of: Callable, expected_ids: Iterable[str], digest: str,
                      code: str) -> dict:
    """Owner invariant 5: registry results of THIS partition whose ids EQUAL the expected projection exactly."""
    out: dict = {}
    for run in runs:
        stored = _lookup(kind, run, f"{code}_result_not_from_the_harness")
        if getattr(stored, "state", None) == HARNESS_FAULT:
            _fail(f"{code}_harness_fault_run_cannot_be_scored")   # unaccounted: rerun under N9, never scored
        if stored.partition_digest != digest:
            _fail(f"{code}_result_of_another_partition_or_bundle")
        key = id_of(stored)
        if key in out:
            _fail(f"{code}_duplicate_result")
        out[key] = stored
    if set(out) != set(expected_ids):
        _fail(f"{code}_results_do_not_equal_the_bundle_items")
    return out


def evaluate_a(bundle: object, runs: Iterable[DetectionRun], *, detector: ComponentIdentity) -> DetectionResult:
    """A: recall at coverage ≥ 0.95 over EXACTLY the A/B partition's crops. Any output-contract violation is a FAIL
    (nothing scored, truncated or re-selected); valid proposals below the frozen floor are counted only as reported."""
    state = sb._state_of(bundle)
    runs = _materialise(runs, "a_runs_malformed")
    det = _rostered(detector, _detectors(state), "a_detector")
    part = state.ab
    by_crop = _require_complete(runs, _A_RUN, lambda r: r.crop_id, part.crops, part.digest, "a")
    floor = _floor(state, det)
    for crop_id, run in by_crop.items():
        crop = part.crops[crop_id]
        if run.detector != det:
            _fail("a_result_from_another_detector")
        ref = _evidence_of(part, crop.track_id, crop.observation_id)
        if run.image != _evidence((ref,))[0] or run.detector_floor != floor:
            _fail("a_result_not_the_bundle_execution")
    layer = _layer_digest(state, "A")
    violations = tuple(f"{r.contract_violation}:{c}" for c, r in sorted(by_crop.items()) if r.state == CONTRACT_FAIL)
    if violations:
        return _register(_A, DetectionResult(CONTRACT_FAIL, violations, 0, 0, None, None, None, 0, part.digest, layer,
                                             det))
    plates = covered = false = below = 0
    scored: list[tuple[float, str, int, bool]] = []
    for crop_id in sorted(by_crop):
        run, crop = by_crop[crop_id], part.crops[crop_id]
        polygons = list(crop.polygons)
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
    return _register(_A, DetectionResult(MEASURED, (), plates, covered, _ratio(covered, plates),
                                         _ratio(false, len(by_crop)), ap, below, part.digest, layer, det))


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
    plates: int                       # TEXT plates: the EM / CER / top-k-hit denominator
    exact: int
    em: Fraction | None
    cer: float | None
    ece: float | None
    top_k_hit: Fraction | None
    risk_coverage: tuple[tuple[float, float], ...]
    unsupported_truths: int
    partition_digest: str
    layer_digest: str
    recogniser: ComponentIdentity
    result_id: str = ""


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


def _reading_result(layer: str, part, layer_hash: str, recogniser: ComponentIdentity,
                    per_plate: Mapping[str, tuple[PlateRecord | None, str | None]]) -> ReadResult:
    """B/C from the typed truth (never re-normalised). TEXT plates are the EM/CER/top-k-hit denominators. An
    UNSUPPORTED_TEXT plate is excluded from them only: a prediction against it is WRONG (correctness 0) in ECE and
    risk–coverage, and the risk–coverage denominator is every plate."""
    violations = tuple(f"{violation}:{pid}" for pid, (_, violation) in sorted(per_plate.items()) if violation)
    if violations:
        return _register(_B, ReadResult(layer, CONTRACT_FAIL, violations, 0, 0, None, None, None, None, (), 0,
                                        part.digest, layer_hash, recogniser))
    rows: list[tuple[str, bool, float, float | None, bool]] = []
    predictions: list[tuple[float, bool, str]] = []
    unsupported = 0
    for pid in sorted(per_plate):
        plate_item = (part.b_plates.get(pid) or part.c_plates.get(pid))
        track = part.tracks[plate_item.track_id]
        plate = per_plate[pid][0]
        read = plate is not None and plate.outcome == PLATE_READ
        confidence = plate.readings[0].confidence if read else None
        if track.state is TruthState.UNSUPPORTED_TEXT:
            unsupported += 1
            if read:
                predictions.append((confidence, False, pid))
            continue
        truth = track.supported
        predicted, any_rank = "", False
        if read:
            predicted = normalised_text(plate.readings[0].raw_text) or ""
            any_rank = any(normalised_text(r.raw_text) == truth for r in plate.readings)
            predictions.append((confidence, predicted == truth, pid))
        rows.append((pid, predicted == truth, cer(predicted, truth), confidence, any_rank))
    n = len(rows)
    exact = sum(r[1] for r in rows)
    ranked = sorted(predictions, key=lambda t: (-t[0], t[2]))
    total = len(per_plate)
    curve, correct = [], 0
    for k, (_, e, _) in enumerate(ranked, 1):
        correct += e
        curve.append((k / total, 1 - correct / k))
    return _register(_B, ReadResult(layer, MEASURED, (), n, exact, _ratio(exact, n),
                                    sum(r[2] for r in rows) / n if n else None, _ece(ranked),
                                    _ratio(sum(r[4] for r in rows), n), tuple(curve), unsupported, part.digest,
                                    layer_hash, recogniser))


def evaluate_b(bundle: object, runs: Iterable[ReadRun], *, recogniser: ComponentIdentity) -> ReadResult:
    """B: EM of the rank-0 reading over EXACTLY the A/B partition's B plates (GT plate crops)."""
    state = sb._state_of(bundle)
    runs = _materialise(runs, "b_runs_malformed")
    rec = _rostered(recogniser, _recognisers(state, benchmark=True), "b_recogniser")
    part = state.ab
    by_plate = _require_complete(runs, _B_RUN, lambda r: r.plate_id, part.b_plates, part.digest, "b")
    for pid, run in by_plate.items():
        if run.recogniser != rec:
            _fail("b_result_from_another_recogniser")
        if run.image != _evidence((part.b_plates[pid].image,))[0]:
            _fail("b_result_not_the_bundle_execution")
    per_plate = {pid: (run.plate, run.contract_violation) for pid, run in by_plate.items()}
    return _reading_result("B", part, _layer_digest(state, "B"), rec, per_plate)


def c_minus_b(c: ReadResult, b: ReadResult) -> Fraction | None:
    """Diagnostic only: the detector-attributable EM loss (C − B), from C and B results of the same partition and
    recogniser."""
    c = _lookup(_B, c, "c_minus_b_result_not_from_the_harness")
    b = _lookup(_B, b, "c_minus_b_result_not_from_the_harness")
    if (c.layer, b.layer) != ("C", "B") or c.partition_digest != b.partition_digest or c.recogniser != b.recogniser:
        _fail("c_minus_b_results_not_comparable")
    return None if c.em is None or b.em is None else c.em - b.em


# ---------------------------------------------------------------------------------------------- top-K (N4)


@dataclass(frozen=True, slots=True)
class ComponentScore:
    candidate_id: str
    support: int
    primary: float | None          # A: recall at coverage; B: EM
    second: float | None           # A: false plates per crop (lower better); B: CER (lower better)
    third: float | None            # A: AP50 (higher better); B: ECE (lower better)
    contract_fail: bool
    identity_sha256: str
    kind: str                      # "detector" | "recogniser"
    partition_digest: str
    measurement_sha256: str        # canonical hash of the A/B result it was built from
    result_id: str = ""


def _float(value) -> float | None:
    return None if value is None else float(value)


def _measurement_sha256(result) -> str:
    return _canonical_sha256({"result": repr(replace(result, result_id=""))})


def detector_component(result: DetectionResult) -> ComponentScore:
    stored = _lookup(_A, result, "component_detection_result_not_from_the_harness")
    who = stored.detector
    return _register(_COMPONENT, ComponentScore(who.candidate_id, stored.plates, _float(stored.recall),
                                                _float(stored.false_plates_per_crop), stored.ap50,
                                                stored.outcome == CONTRACT_FAIL, who.identity_sha256, "detector",
                                                stored.partition_digest, _measurement_sha256(stored)))


def recogniser_component(result: ReadResult) -> ComponentScore:
    stored = _lookup(_B, result, "component_read_result_not_from_the_harness")
    if stored.layer != "B":
        _fail("component_read_result_not_layer_b")
    who = stored.recogniser
    return _register(_COMPONENT, ComponentScore(who.candidate_id, stored.plates, _float(stored.em),
                                                stored.cer, stored.ece, stored.outcome == CONTRACT_FAIL,
                                                who.identity_sha256, "recogniser", stored.partition_digest,
                                                _measurement_sha256(stored)))


def _rank_values(s: ComponentScore):
    def high(value):
        return (value is None, -(value or 0))

    def low(value):
        return (value is None, value or 0)

    if s.kind == "detector":
        return (high(s.primary), low(s.second), high(s.third))
    return (high(s.primary), low(s.second), low(s.third))


def top_k(bundle: object, scores: Iterable[ComponentScore], kind: str) -> list[str]:
    """N4 tie-breaks over harness component scores of ``kind`` on the bundle's A/B partition. K and the support floor
    are the frozen record's values. The roster must EQUAL the frozen universe (no omission, no outsider, never empty);
    contract-failed components, components below the support floor and components the frozen record does not declare
    independent (N4, predeclared) never enter; the benchmark-only component is refused."""
    state = sb._state_of(bundle)
    if kind not in ("detector", "recogniser"):
        _fail("top_k_kind")
    stored = [_lookup(_COMPONENT, s, "top_k_score_not_from_the_harness")
              for s in _materialise(scores, "top_k_scores_malformed")]
    if len({s.candidate_id for s in stored}) != len(stored):
        _fail("top_k_duplicate_candidate")
    roster = state.roster
    for s in stored:
        if s.kind != kind:
            _fail("top_k_score_of_another_kind")
        if s.candidate_id == roster.benchmark_id or s.identity_sha256 == roster.benchmark_sha256:
            _fail("benchmark_only_component_cannot_enter_top_k")
        if s.partition_digest != state.ab.digest:
            _fail("top_k_score_not_on_the_frozen_partition")
    universe = dict(roster.detectors if kind == "detector" else roster.recognisers)
    if {s.candidate_id: s.identity_sha256 for s in stored} != universe:
        _fail("top_k_roster_is_not_the_frozen_universe")
    eligible = [s for s in stored if roster.independent[s.candidate_id] and not s.contract_fail
                and s.support >= state.protocol.support_floor]
    return [s.candidate_id for s in sorted(eligible, key=lambda s: (_rank_values(s), s.candidate_id))
            [:state.protocol.top_k]]


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
    """A ranking-path D result, recorded only by ``evaluate_d`` and bound to its partition and query set."""

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
    partition_digest: str = ""
    query_set_sha256: str = ""
    detector: ComponentIdentity | None = None
    recogniser: ComponentIdentity | None = None
    result_id: str = ""


@dataclass(frozen=True, slots=True)
class DiagnosticTrackScore:
    """DIAGNOSTIC ONLY (D6): D at a declared diagnostic OCR floor. A distinct, unregistered type every decision
    refuses."""

    floor: float
    values: TrackScore


@dataclass(frozen=True, slots=True)
class _Prepared:
    track_id: str
    cluster: str
    kind: str          # "plate" | "no-plate" | "no-gt-vehicle" | "unsupported" | "unreadable"
    truth: str | None
    run: TrackRun | None


def _track_runs(state, part, runs: list, composition: tuple[ComponentIdentity, ComponentIdentity]
                ) -> dict[str, TrackRun]:
    """Owner invariants 3–5: exactly one harness run per evidence Track, of this rostered composition, on exactly its
    evidence; none for a Track without evidence (NO_RUN is derived)."""
    detector, recogniser = composition
    expected = [tid for tid, t in part.tracks.items() if t.has_mavi_evidence]
    by_track = _require_complete(runs, _TRACK_RUN, lambda r: r.track_id, expected, part.digest, "d")
    floor = _floor(state, detector)
    for tid, run in by_track.items():
        track = part.tracks[tid]
        if (run.detector, run.recogniser) != (detector, recogniser):
            _fail("d_run_identity_is_not_the_composition")
        if run.mavi_track_uuid != track.mavi_track_uuid or run.evidence != _evidence(track.evidence):
            _fail("d_run_is_not_the_bundle_execution")
        if not is_ranking_profile(run.parameters, floor):
            _fail("d_run_not_on_ranking_profile")
    return by_track


def _prepare(part, by_track: Mapping[str, TrackRun]) -> tuple[list[_Prepared], dict]:
    prepared = []
    accounting = {"text": 0, "unsupported": 0, "unqueryable": 0, "no-plate": 0, "unreadable": 0, "no-gt-vehicle": 0}
    for tid in sorted(part.tracks):
        track = part.tracks[tid]
        run = by_track.get(tid)
        state = track.state
        if state is not TruthState.TEXT:
            # UNSUPPORTED_TEXT (owner 2026-10-14): kept, excluded only from text-recall denominators, returns are wrong.
            kind = {TruthState.NO_PLATE: "no-plate", TruthState.NO_GT_VEHICLE: "no-gt-vehicle",
                    TruthState.UNREADABLE: "unreadable", TruthState.UNSUPPORTED_TEXT: "unsupported"}[state]
            accounting[kind] += 1
            prepared.append(_Prepared(tid, track.site, kind, None, run))
            continue
        accounting["text"] += 1
        accounting["unqueryable"] += not queryable(track.supported)
        prepared.append(_Prepared(tid, track.site, "plate", track.supported, run))
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
                text = normalised_text(plate.readings[0].raw_text)
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


def _d_inputs(state, runs: object, composition: object, code: str):
    """The protected-D inputs from ONE resolved bundle state (the handle is read once per public call)."""
    runs = _materialise(runs, f"{code}_runs_malformed")
    who = _composition(state, composition, code)
    part = _part(state, Partition.PROTECTED_D, code)
    by_track = _track_runs(state, part, runs, who)
    queries = _queries(state, Partition.PROTECTED_D)
    prepared, accounting = _prepare(part, by_track)
    return part, who, queries, prepared, accounting


def evaluate_d(bundle: object, runs: Iterable[TrackRun], *, composition) -> TrackScore:
    """D (owner N8) over EXACTLY the protected-D population, for the rostered composition whose harness runs these
    are. Any contract violation is CONTRACT_FAIL; candidate silence scores 0. Protected-D bundle only."""
    part, who, queries, prepared, accounting = _d_inputs(sb._state_of(bundle), runs, composition, "d")
    score = replace(_score(prepared, queries, accounting), partition_digest=part.digest,
                    query_set_sha256=queries.query_set_sha256, detector=who[0], recogniser=who[1])
    return _register(_D, score)


def diagnostic_evaluate_d_at_floor(bundle: object, runs: Iterable[TrackRun], floor: float, *,
                                   composition) -> DiagnosticTrackScore:
    """DIAGNOSTIC ONLY (D6): D as PR-3 would publish it at another OCR floor (a ``DiagnosticTrackScore``)."""
    if floor not in DIAGNOSTIC_OCR_FLOORS:
        raise ValueError("diagnostic_floor_not_declared")
    _, _, queries, prepared, accounting = _d_inputs(sb._state_of(bundle), runs, composition, "d")
    refloored = []
    for p in prepared:
        run = p.run
        if run is not None and run.record is not None:
            run = replace(run, record=_refloor(run.record, floor), result_id="")
        refloored.append(replace(p, run=run))
    score = _score(refloored, queries, accounting)
    return DiagnosticTrackScore(floor, replace(score, accounting={**score.accounting, "diagnosticFloor": floor}))


def evaluate_c(bundle: object, runs: Iterable[TrackRun], *, composition) -> ReadResult:
    """C: EM of the composition's own accepted plate for EXACTLY the A/B partition's C plates, derived from its harness
    runs (PR-3 selection). "Not read" arises only from the run (no accepted plate, or an abstained crop)."""
    state = sb._state_of(bundle)
    runs = _materialise(runs, "c_runs_malformed")
    who = _composition(state, composition, "c")
    part = state.ab
    by_track = _track_runs(state, part, runs, who)
    layer = _layer_digest(state, "C")
    violations = tuple(f"{r.contract_violation}:{tid}" for tid, r in sorted(by_track.items())
                       if r.state == CONTRACT_FAIL)
    if violations:
        # Review 6, P3-1: ANY violation in the composition's runs is CONTRACT_FAIL, not only on a C plate's Track.
        return _register(_B, ReadResult("C", CONTRACT_FAIL, violations, 0, 0, None, None, None, None, (), 0,
                                        part.digest, layer, who[1]))
    per_plate: dict[str, tuple[PlateRecord | None, str | None]] = {}
    for pid, plate in part.c_plates.items():
        run = by_track[plate.track_id]
        crop = next(c for c in run.record.crops if str(c.observation_id) == plate.observation_id)
        accepted = next((p for _, p in crop.plates()), None) if crop.status == CROP_SCORED else None
        per_plate[pid] = (accepted, None)
    return _reading_result("C", part, layer, who[1], per_plate)


def _d_score_of(score: object, code: str) -> TrackScore:
    """The harness's own ranking D record named by ``score`` (diagnostic and unrecorded scores are refused)."""
    return _lookup(_D, score, code)


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
    partition_digest: str
    result_id: str = ""


def percentile_indices(replicates: int) -> tuple[int, int]:
    """⌊0.025·(R−1)⌋ and ⌈0.975·(R−1)⌉ in integer arithmetic (``PERCENTILE_RULE``)."""
    return (25 * (replicates - 1)) // 1000, -((-975 * (replicates - 1)) // 1000)


def required_clusters(calibration_minimum: int) -> int:
    """Owner D7b / P-80: max(60, the frozen candidate-blind calibration minimum)."""
    if not (type(calibration_minimum) is int and calibration_minimum >= 1):
        raise ValueError("calibration_minimum_invalid")
    return max(ABSOLUTE_MINIMUM_CLUSTERS, calibration_minimum)


def _draws(rng: random.Random, members: dict[str, list[int]], names: list[str]) -> list[int]:
    picked = []
    for _ in names:
        group = members[names[rng.randrange(len(names))]]
        picked.extend(group[rng.randrange(len(group))] for _ in group)
    return picked


def _replicates(pa: list[_Prepared], pb: list[_Prepared], queries: QuerySet, replicates: int, seed: int,
                slow: bool) -> list[Fraction | None]:
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


def _bootstrap_replicates(bundle: object, runs_a, runs_b, *, composition_a, composition_b, replicates: int,
                          seed: int, slow: bool = False) -> list[Fraction | None]:
    """PRIVATE TEST HOOK: exact ΔD per replicate at an explicit R and seed (proves fast = slow). The comparison uses
    only the frozen R and seed."""
    if not (_integer(replicates) and replicates >= 1 and _integer(seed)):
        raise ValueError("bootstrap_replicates_invalid")
    state = sb._state_of(bundle)
    _, _, queries, pa, _ = _d_inputs(state, runs_a, composition_a, "d")
    _, _, _, pb, _ = _d_inputs(state, runs_b, composition_b, "d")
    return _replicates(pa, pb, queries, replicates, seed, slow)


def paired_cluster_bootstrap(bundle: object, runs_a, runs_b, *, composition_a, composition_b, resolution,
                             layer_a_results) -> Comparison:
    """The frozen superiority rule (owner item 2): ``superior`` iff observed ΔD ≥ MPID (exact), the paired hierarchical
    95 % percentile interval excludes zero in A's favour, and clusters ≥ max(60, the frozen calibration minimum).
    R, the seed and the calibration minimum come from the frozen record; the sealed resolution is re-verified."""
    state = sb._state_of(bundle)
    runs_a = _materialise(runs_a, "comparison_runs_malformed")
    runs_b = _materialise(runs_b, "comparison_runs_malformed")
    _verified_resolution(state, resolution, layer_a_results)
    part, who_a, queries, pa, _ = _d_inputs(state, runs_a, composition_a, "d")
    _, who_b, _, pb, _ = _d_inputs(state, runs_b, composition_b, "d")
    for who in (*who_a, *who_b):
        _refuse_benchmark_only(who, state)
    needed = required_clusters(state.protocol.calibration_minimum)
    a = _score(pa, queries, {})
    b = _score(pb, queries, {})
    clusters = sorted({t.site for t in part.tracks.values()})
    per_cluster, signs = {}, {"a": 0, "b": 0, "tie": 0, "insufficient": 0}

    def result(outcome, difference=None, lower=None, upper=None, insufficient=0):
        return _register(_CMP, Comparison(outcome, difference, lower, upper, len(clusters), needed, CLUSTER_UNIT,
                                          insufficient, dict(signs), dict(per_cluster), part.digest))

    if a.outcome == CONTRACT_FAIL or b.outcome == CONTRACT_FAIL:
        return result("contract-fail")
    if a.d_score is None or b.d_score is None:
        return result("insufficient-evidence")
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
    values = _replicates(pa, pb, queries, state.protocol.replicates, state.protocol.bootstrap_seed, False)
    insufficient = sum(v_ is None for v_ in values)
    if insufficient:
        return result("insufficient-evidence", observed, insufficient=insufficient)
    values.sort()
    low_index, high_index = percentile_indices(len(values))
    lower, upper = values[low_index], values[high_index]
    superior = observed >= MPID and lower > 0
    return result("superior" if superior else "not-superior", observed, lower, upper)


@dataclass(frozen=True, slots=True)
class CompositionScore:
    """A composition's ranking-path D score; its ids are the harness record's identities."""

    score: TrackScore

    @property
    def detector(self) -> ComponentIdentity:
        return _d_score_of(self.score, "composition_score_not_a_ranking_d_score").detector

    @property
    def recogniser(self) -> ComponentIdentity:
        return _d_score_of(self.score, "composition_score_not_a_ranking_d_score").recogniser

    @property
    def detector_id(self) -> str:
        return self.detector.candidate_id

    @property
    def recogniser_id(self) -> str:
        return self.recogniser.candidate_id


# ------------------------------------------------------------------ baseline resolution (N2 revised + addendum 2026-10-14)
#
# Stage 1 (PROTOCOL_FROZEN) is the committed freeze record: the eligible detector universe with exact identities, the
# recogniser universe, the OC5 benchmark-only identity, the events and gate-only composition id that M3's
# ``compositionSha256`` binds, the Layer-A gate set hash, the freeze time and the ranking rule (ambiguity STOPS).
# Stage 2 derives PD_BASE mechanically (``resolve_baseline``) from Layer-A results measured on the A/B partition. The
# committed pre-D seal (M3 ``baseline_seal``) and Git chronology are the MANDATED #218↔M3 integration PR.

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


@dataclass(frozen=True, slots=True)
class BaselineFreeze:
    """Stage 1, a read-only view of the committed freeze record (never a caller input)."""
    eligible_detectors: tuple[tuple[str, str], ...]
    eligible_recognisers: tuple[tuple[str, str], ...]
    benchmark_only_id: str
    benchmark_only_identity_sha256: str
    layer_a_gates_sha256: str
    frozen_at_utc: str
    event_id: str
    composition_id: str
    partner_event_id: str
    ab_partition_digest: str
    d_partition_digest: str
    partition_plan_digest: str
    freeze_record_sha256: str
    ranking_rule_sha256: str

    @property
    def benchmark(self) -> ComponentIdentity:
        return ComponentIdentity(self.benchmark_only_id, self.benchmark_only_identity_sha256)

    def freeze_sha256(self) -> str:
        return _canonical_sha256({"freezeRecordSha256": self.freeze_record_sha256, "baselineRule": BASELINE_RULE})


def baseline_freeze(bundle: object) -> BaselineFreeze:
    state = sb._state_of(bundle)
    r = state.roster
    return BaselineFreeze(tuple(sorted(r.detectors.items())), tuple(sorted(r.recognisers.items())), r.benchmark_id,
                          r.benchmark_sha256, r.layer_a_gates_sha256, r.frozen_at_utc, r.event_id, r.composition_id,
                          r.partner_event_id, state.ab.digest, state.d.digest, state.plan_digest, state.record_sha256,
                          r.ranking_rule_sha256)


@dataclass(frozen=True, slots=True)
class LayerAResult:
    """One eligible detector's Layer-A result: its harness A component score and the frozen gates' verdict
    (``gates_passed``). The verdict is a caller value until the M3 integration derives it from the committed component
    ranking; it shapes only the Stage-2 harness record, never D access (``load_d_capture_bundle``)."""
    score: ComponentScore
    identity_sha256: str
    gates_passed: bool


@dataclass(frozen=True, slots=True)
class BaselineResolution:
    """Stage 2 record (harness registry). ``record_sha256`` covers every other field; it is re-derived on every use."""
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
    result_id: str = ""

    def payload(self) -> dict:
        return {"freezeSha256": self.freeze_sha256, "pdBaseId": self.pd_base_id,
                "pdBaseIdentitySha256": self.pd_base_identity_sha256, "benchmarkOnlyId": self.benchmark_only_id,
                "benchmarkOnlyIdentitySha256": self.benchmark_only_identity_sha256,
                "layerAResultSha256": self.layer_a_result_sha256, "rankingRuleSha256": self.ranking_rule_sha256,
                "compositionSha256": self.composition_sha256, "resolvedAtUtc": self.resolved_at_utc,
                "dState": self.d_state}


def _layer_a(results: object) -> list[tuple[ComponentScore, str, bool]]:
    """Primitive copies of the Layer-A results: the harness component record, the identity string and the bool."""
    out = []
    for r in _materialise(results, "layer_a_results_malformed"):
        identity, gates = getattr(r, "identity_sha256", None), getattr(r, "gates_passed", None)
        try:
            score = _lookup(_COMPONENT, getattr(r, "score", None), "x")
        except ValueError:
            raise BaselineStop("layer_a_result_not_from_the_harness") from None
        if type(identity) is not str or type(gates) is not bool:
            raise BaselineStop(f"layer_a_result_malformed:{score.candidate_id}")
        out.append((score, identity, gates))
    return out


def _layer_a_document(state, results: list[tuple[ComponentScore, str, bool]]) -> dict:
    rows = [{"candidateId": s.candidate_id, "identitySha256": identity,
             "gates": {"layer-a": "passed" if passed else "failed"},
             "rankKey": [None if v is None else repr(v) for v in (s.primary, s.second, s.third)],
             "measurementSha256": s.measurement_sha256} for s, identity, passed in results]
    return {"schema": LAYER_A_ARTEFACT_SCHEMA, "layerAGatesSha256": state.roster.layer_a_gates_sha256,
            "partnerRankingRuleSha256": state.roster.ranking_rule_sha256,
            "partnerEventId": state.roster.partner_event_id,
            "results": sorted(rows, key=lambda r: r["candidateId"]), "evidenceSha256": state.ab.digest}


def layer_a_result_document(bundle: object, results) -> dict:
    """The canonical Layer-A result artefact #218 emits (owner invariant 9), derived from the A/B partition.

    Its per-partner rows use M3's ``layer_a_result_document`` keys (candidateId, identitySha256, gates, rankKey,
    measurementSha256) and ``evidenceSha256`` = the A/B partition digest. The event-level M3 fields and the per-gate
    dictionary are reconciled in the mandated #218↔M3 integration PR; until then the hash differs from M3's."""
    return _layer_a_document(sb._state_of(bundle), _layer_a(results))


def layer_a_result_sha256(bundle: object, results) -> str:
    return _canonical_sha256(layer_a_result_document(bundle, results))


def _detector_key(s: ComponentScore):
    return _rank_values(s)


def _derive(state, results: list[tuple[ComponentScore, str, bool]], resolved_at_utc: object) -> BaselineResolution:
    """Stage 2 from the frozen record and the Layer-A results. It raises ``BaselineStop`` and never chooses."""
    roster = state.roster
    if not (type(resolved_at_utc) is str and _UTC_RE.match(resolved_at_utc)):
        raise BaselineStop("baseline_resolution_time_malformed")
    if resolved_at_utc < roster.frozen_at_utc:
        raise BaselineStop("baseline_resolution_before_freeze")
    eligible = dict(roster.detectors)
    seen = [s.candidate_id for s, _, _ in results]
    if len(seen) != len(set(seen)):
        raise BaselineStop("layer_a_result_ambiguous_duplicate_detector")
    if set(seen) != set(eligible):
        raise BaselineStop("layer_a_result_inconsistent_with_frozen_detector_universe")
    for s, identity, passed in results:
        if s.kind != "detector":
            raise BaselineStop(f"layer_a_result_not_a_detector_result:{s.candidate_id}")
        if s.partition_digest != state.ab.digest:
            raise BaselineStop(f"layer_a_result_not_on_the_frozen_partition:{s.candidate_id}")
        if identity != eligible[s.candidate_id] or s.identity_sha256 != identity:
            raise BaselineStop(f"layer_a_identity_mismatch:{s.candidate_id}")
        if passed and s.contract_fail:
            raise BaselineStop(f"layer_a_result_inconsistent_gate_pass_with_contract_fail:{s.candidate_id}")
        if passed and any(v is not None and not math.isfinite(v) for v in (s.primary, s.second, s.third)):
            raise BaselineStop(f"layer_a_rank_ambiguous_non_finite_metric:{s.candidate_id}")
    survivors = sorted((s for s, _, passed in results if passed), key=lambda s: (_detector_key(s), s.candidate_id))
    if not survivors:
        raise BaselineStop("no_detector_passed_layer_a")
    if len(survivors) > 1 and _detector_key(survivors[0]) == _detector_key(survivors[1]):
        raise BaselineStop("layer_a_rank_ambiguous")  # owner N2 addendum and M3: ambiguity stops, no id tie-break
    pd_base = survivors[0].candidate_id
    benchmark = ComponentIdentity(roster.benchmark_id, roster.benchmark_sha256)
    composition = m3_composition_sha256(roster.event_id, roster.composition_id, benchmark, roster.partner_event_id,
                                        ComponentIdentity(pd_base, eligible[pd_base]))
    unsealed = BaselineResolution(
        freeze_sha256=_canonical_sha256({"freezeRecordSha256": state.record_sha256, "baselineRule": BASELINE_RULE}),
        pd_base_id=pd_base, pd_base_identity_sha256=eligible[pd_base], benchmark_only_id=roster.benchmark_id,
        benchmark_only_identity_sha256=roster.benchmark_sha256,
        layer_a_result_sha256=_canonical_sha256(_layer_a_document(state, results)),
        ranking_rule_sha256=roster.ranking_rule_sha256, composition_sha256=composition,
        resolved_at_utc=resolved_at_utc, d_state=D_NOT_STARTED, record_sha256="")
    return replace(unsealed, record_sha256=_canonical_sha256(unsealed.payload()))


def resolve_baseline(bundle: object, results, *, d_rows_read: int, resolved_at_utc: str) -> BaselineResolution:
    """Stage 2. Derive PD_BASE mechanically from the frozen rule; refuses once D data is read.

    ``d_rows_read`` and ``resolved_at_utc`` are reporting-only (owner point 4): a non-zero claim or a time before the
    freeze STOPS and the time is recorded, but neither can enable anything. Whether D data was read is the harness's
    own in-process fact (``selection_bundle.d_data_loaded``), checked whatever the claim; Git chronology and the
    committed seal bind the time in the integration PR. The resolution is a harness record, not D authority: D opens
    only through the protected-D authority (``load_d_capture_bundle``)."""
    state = sb._state_of(bundle)
    if type(d_rows_read) is not int or d_rows_read != 0:
        raise BaselineStop("baseline_resolution_after_d_data_read")
    if sb.d_data_loaded(state.record_sha256) or sb.d_truth_loaded(state.record_sha256):
        raise BaselineStop("baseline_resolution_after_d_data_loaded")
    return _register(_RES, _derive(state, _layer_a(results), resolved_at_utc))


def _verified_resolution(state, resolution: object, results) -> BaselineResolution:
    try:
        stored = _lookup(_RES, resolution, "x")
    except ValueError:
        raise BaselineStop("baseline_resolution_not_from_the_harness") from None
    if stored.record_sha256 != _canonical_sha256(stored.payload()) or stored.d_state != D_NOT_STARTED:
        raise BaselineStop("baseline_resolution_record_altered")
    if stored.freeze_sha256 != _canonical_sha256({"freezeRecordSha256": state.record_sha256,
                                                  "baselineRule": BASELINE_RULE}):
        raise BaselineStop("baseline_resolution_of_another_freeze")
    expected = _derive(state, _layer_a(results), stored.resolved_at_utc)
    if replace(expected, result_id=stored.result_id) != stored:
        raise BaselineStop("baseline_resolution_differs_from_frozen_derivation")
    return stored


def verify_resolution(bundle: object, resolution, results) -> None:
    """Re-derive Stage 2 from the frozen record and the Layer-A results. Drift or a foreign record raises
    ``BaselineStop``."""
    _verified_resolution(sb._state_of(bundle), resolution, results)


def _pre_d(resolution: object, layer_a_results: object) -> Callable:
    """The Stage-2 check of both D stages, run on the selection state before any D path is opened: the sealed
    resolution must re-derive from the frozen record and the Layer-A results. The loader then always applies the
    protected-D authority itself (fail closed in #218)."""
    layer_a = _materialise(layer_a_results, "layer_a_results_malformed")

    def check(selection_state) -> BaselineResolution:
        return _verified_resolution(selection_state, resolution, layer_a)

    return check


def load_d_capture_bundle(corpus_dir, *, resolution, layer_a_results, authorization, repo_root=None) -> Bundle:
    """The D-capture stage: the selection documents plus the D INDEX (evidence, no truth), for candidate execution on
    protected-D evidence. Requires the verified Stage-2 resolution and the protected-D authority (fails closed in
    #218: ``protected_d_not_authorised:m3_authority_not_integrated``)."""
    return sb._load(corpus_dir, repo_root, sb.D_CAPTURE, _pre_d(resolution, layer_a_results), authorization)


def load_protected_d_bundle(corpus_dir, *, resolution, layer_a_results, authorization, repo_root=None) -> Bundle:
    """The protected-D stage: adds the D TRUTH, for scoring. Same precondition as the D-capture stage. Loading it ends
    candidate execution in this process (owner point 5), so every candidate output on D evidence is captured on the
    D-capture bundle first; it is refused while a candidate callable is running."""
    return sb._load(corpus_dir, repo_root, sb.PROTECTED, _pre_d(resolution, layer_a_results), authorization)


def assert_resolution_unchanged(sealed, current) -> None:
    a = _lookup(_RES, sealed, "resolution_not_from_the_harness")
    b = _lookup(_RES, current, "resolution_not_from_the_harness")
    if a.payload() != b.payload():
        raise BaselineStop("baseline_resolution_changed_after_seal")


def _refuse_benchmark_only(who: ComponentIdentity, state) -> None:
    if who.candidate_id == state.roster.benchmark_id or who.identity_sha256 == state.roster.benchmark_sha256:
        _fail("benchmark_only_component_cannot_be_ranked")


def _composition_of(score: TrackScore, state) -> str:
    r = state.roster
    return m3_composition_sha256(r.event_id, r.composition_id, score.recogniser, r.partner_event_id, score.detector)


def _composition_score(value: object, code: str) -> TrackScore:
    return _d_score_of(getattr(value, "score", None), code)


def baseline_gate(bundle: object, composition: CompositionScore, baseline: CompositionScore, resolution,
                  layer_a_results) -> str:
    """N2 (revised): ONE hard gate against the sealed baseline composition PD_BASE + OC5: observed
    D − D(PD_BASE + OC5) ≥ MPID (exact). A composition contract violation is FAIL; a baseline contract failure or a
    non-evaluable baseline stops the event; a silent baseline scores 0; a corpus-deficient composition is
    INSUFFICIENT_EVIDENCE. Both scores must be on the protected-D partition of this bundle."""
    return _gate(sb._state_of(bundle), composition, baseline, resolution,
                 _materialise(layer_a_results, "layer_a_results_malformed"))


def _gate(state, composition, baseline, resolution, layer_a_results) -> str:
    stored = _verified_resolution(state, resolution, layer_a_results)
    base = _composition_score(baseline, "gate_baseline_score_not_a_ranking_d_score")
    candidate = _composition_score(composition, "gate_composition_score_not_a_ranking_d_score")
    benchmark = ComponentIdentity(state.roster.benchmark_id, state.roster.benchmark_sha256)
    if base.recogniser != benchmark or _composition_of(base, state) != stored.composition_sha256:
        _fail("baseline_is_not_the_sealed_pd_base_composition")
    _refuse_benchmark_only(candidate.detector, state)
    _refuse_benchmark_only(candidate.recogniser, state)
    if not (candidate.partition_digest == base.partition_digest == state.d.digest
            and candidate.query_set_sha256 == base.query_set_sha256):
        _fail("gate_scores_not_on_the_same_population_and_query_set")
    if base.outcome == CONTRACT_FAIL:
        raise BaselineStop("baseline_contract_violation")
    if base.d_score is None:
        raise BaselineStop("baseline_not_evaluable")
    if candidate.outcome == CONTRACT_FAIL:
        return FAIL
    if candidate.d_score is None:
        return INSUFFICIENT
    return PASS if candidate.d_score - base.d_score >= MPID else FAIL


def rankable_compositions(bundle: object, compositions, baseline: CompositionScore, resolution,
                          layer_a_results) -> list[CompositionScore]:
    """Exactly the ordinary compositions that PASS the single baseline gate; the benchmark-only component is refused."""
    state = sb._state_of(bundle)
    out = []
    layer_a = _materialise(layer_a_results, "layer_a_results_malformed")
    for composition in _materialise(compositions, "compositions_malformed"):
        if _gate(state, composition, baseline, resolution, layer_a) == PASS:
            out.append(composition)
    return out


def diagnostic_ocr_uplift(bundle: object, composition: CompositionScore,
                          matched_baseline: CompositionScore) -> Fraction | None:
    """DIAGNOSTIC ONLY (N2 revised): D(PDx + OCy) − D(PDx + OC5) at a fixed detector, on the same partition."""
    state = sb._state_of(bundle)
    a = _composition_score(composition, "diagnostic_uplift_score_not_a_ranking_d_score")
    b = _composition_score(matched_baseline, "diagnostic_uplift_score_not_a_ranking_d_score")
    benchmark = ComponentIdentity(state.roster.benchmark_id, state.roster.benchmark_sha256)
    if b.detector != a.detector or b.recogniser != benchmark:
        _fail("diagnostic_baseline_not_detector_matched")
    if (a.partition_digest, a.query_set_sha256) != (b.partition_digest, b.query_set_sha256) \
            or a.partition_digest != state.d.digest:
        _fail("diagnostic_scores_not_on_the_same_population_and_query_set")
    if CONTRACT_FAIL in (a.outcome, b.outcome) or a.d_score is None or b.d_score is None:
        return None
    return a.d_score - b.d_score
