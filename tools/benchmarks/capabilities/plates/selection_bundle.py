"""Stage-4 plate selection: the verified corpus bundle — the harness trust boundary (owner instruction 2026-10-14).

    canonical bytes  →  identity verification  →  strict parse  →  harness-owned immutable state  →  A/B/C/D

**Independent identity.** The expected identities come from ONE committed freeze record at the fixed repository path
``FREEZE_RECORD_PATH``. The loader reads it itself (never a parameter beside the content), through M3's isolated Git
profile (``m3_git``: no system/global configuration, no inherited ``GIT_*``, replace objects ignored, full history
required). The record is read **by blob id from HEAD**, its work-tree copy must be clean, and its path must be
**add-only across the full reachable history**: every change to the path is an addition of exactly the HEAD blob, so an
edit-and-recommit, a delete-and-re-add or a merge that alters it after the freeze is refused
(``freeze_record_not_add_only``). The freeze commit is the record's unique first add. What this cannot stop locally is
a rewrite of history itself; pinning the record SHA-256 in the M3 frozen ledgers on the protected default branch (live
anchor) is the mandated integration PR (decision record §6). The record holds:
- the protocol: query parameters and seed, bootstrap seed, R, the percentile rule, MPID, the calibration minimum,
  K, the top-K support floor and each detector's pinned floor;
- the roster: the detector and recogniser universes with identity SHA-256s and each component's predeclared N4
  independence verdict, the benchmark-only OC5 identity, the ranking rule, the Layer-A gate set, the events and the
  freeze time;
- the site-level partition plan;
- the SHA-256 of each of the four corpus documents: A/B index, A/B truth, D index and D truth;
- the cross-partition disjointness result and its hash, established by the freeze-construction tool
  (``selection_freeze``) when the record was built.

**Content.** The four corpus documents are read from a caller-named directory under fixed file names. Each must hash
to its frozen SHA-256, then parse STRICTLY:
- ASCII only;
- duplicate keys, NaN and Infinity are refused;
- re-serialisation in the canonical form must reproduce the bytes exactly. The canonical form is: keys sorted, no
  whitespace (``,`` and ``:`` separators), ``\\uXXXX`` escapes for non-ASCII, the shortest round-trip float form,
  and one final LF;
- every object has exactly its schema keys and exact primitive types, and every array is in its canonical order.

**State.** Verified primitives become private, immutable harness objects held in a private registry. A loaded
``Bundle`` is only a handle: its ``bundle_id`` string selects harness state, and no other attribute of a caller object
is read. A/B and protected D are ONE paired corpus under one partition plan (sites in exactly one partition, with case
and whitespace aliases refused; Track ids, MAVI Track uuids, observation ids and content SHA-256s unique across BOTH
partitions). The cross-partition check runs at freeze construction and is recorded in the record; it is re-run on the
real D index whenever D is opened.

**Stages** (owner points 2 and 5). Each stage opens only what it needs:
- ``SELECTION`` (``load_selection_bundle``): the record and the two A/B documents. **No D path is opened** — Layer A/B/C,
  top-K and the Stage-2 resolution run with the D files absent;
- ``D_CAPTURE`` (``evaluator.load_d_capture_bundle``): adds the D index (evidence, no truth) for candidate execution on
  D evidence;
- ``PROTECTED_D`` (``evaluator.load_protected_d_bundle``): adds the D truth for scoring. Loading it ends candidate
  execution for the process: every execution envelope refuses afterwards, and the truth cannot be loaded while a
  candidate callable is running.

Both D stages require the verified Stage-2 resolution AND the protected-D authority (``_authorise_protected_d``). In
#218 no authority is integrated, so the D stages **fail closed** in production; the M3 bridge
(``m3_authority.open_protected_d``) is the mandated integration PR.

**Truth.** The documents use the human states ``TEXT``, ``NO_PLATE``, ``UNREADABLE`` and ``NO_GT_VEHICLE``. For human
text the harness DERIVES the typed state:
- ``TEXT`` when the text normalises under v1 (unchanged) AND the normalised text has at least one ``[A-Z]`` and one
  ``[0-9]``. This letter-and-digit rule is the owner's Stage-4 corpus eligibility rule, not part of v1;
- ``UNSUPPORTED_TEXT`` otherwise. The text is retained and never refused.

Reserved syntax is malformed input and is refused. It means exactly the two encodings the repository has defined for
non-text truth, and nothing else (no placeholder-word blacklist):
1. text equal to a truth-state name (``TEXT``, ``UNSUPPORTED_TEXT``, ``NO_PLATE``, ``UNREADABLE``,
   ``NO_GT_VEHICLE``), ignoring case, whitespace, ``_`` and ``-``;
2. the ``<…>`` sentinel/control-token syntax: a text that BOTH begins with ``<`` AND ends with ``>`` (the harness
   sentinels ``<no-plate>``, ``<unreadable>``, ``<no-gt-vehicle>`` of 2f849818 and the control-token rule of
   e1e7b08f). A text with only one of the two brackets is ordinary human text (v1 rejects ``<``/``>``, so it is
   ``UNSUPPORTED_TEXT``).

After loading, the typed state is authoritative: no metric re-normalises raw truth.
"""

from __future__ import annotations

import enum
import hashlib
import json
import math
import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType
from uuid import UUID

from mavi_vision.plates.contracts import is_raw_text
from mavi_vision.plates.normalisation import OK, normalise

from tools.benchmarks.capabilities.plates.queries import QueryParameters
from tools.qualification.model_selection import m3_git
from tools.qualification.model_selection.credibility import CredibilityError

FREEZE_RECORD_PATH = "config/benchmarks/plates/selection-freeze-v1.json"
RECORD_SCHEMA = "mavi-plate-selection-freeze-v1"
INDEX_SCHEMA = "mavi-plate-selection-index-v1"
TRUTH_SCHEMA = "mavi-plate-selection-truth-v1"
DOCUMENT_FILES = {"abIndex": "ab-index.json", "abTruth": "ab-truth.json", "dIndex": "d-index.json",
                  "dTruth": "d-truth.json"}

BOOTSTRAP_REPLICATES = 1000                   # frozen R (owner T)
TOP_K = 3                                     # plan §4.1: K per sub-task (frozen)
TOP_K_SUPPORT_FLOOR = 50                      # owner N3/N4: minimum support to enter top-K (frozen)
PERCENTILE_RULE = "floor(25(R-1)/1000), ceil(975(R-1)/1000)"
MPID_TEXT = "4/100"
DETECTOR_RANKING_RULE = ("mavi-plate-detector-rank-v2: Layer-A gate pass required; recall at coverage desc; "
                         "false plates per crop asc; AP50 desc; missing metric sorts last; equal rank keys among the "
                         "passing detectors STOP the event (ambiguous; no id tie-break)")
DETECTOR_RANKING_RULE_SHA256 = hashlib.sha256(DETECTOR_RANKING_RULE.encode("utf-8")).hexdigest()

EVIDENCE_ROLES = ("near-view", "far-view", "best-plate", "representative")
PLATE_IMAGE_ROLE = "gt-plate-crop"
SELECTION, D_CAPTURE, PROTECTED = "SELECTION", "D_CAPTURE", "PROTECTED_D"   # bundle stages
DISJOINT = "DISJOINT"
DISJOINTNESS_CHECKS = ("site", "trackId", "maviTrackUuid", "observationId", "contentSha256")
M3_ORDINARY_COMPOSITION_PREFIX = "C-"   # M3 baseline_seal.ORDINARY_ID_PREFIX: reserved for derived ordinary ids

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CANDIDATE_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*$")
_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_EVENT_RE = re.compile(r"^msr-[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?-\d{4}-\d{2}$")
_COMPOSITION_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,63}$")


class Partition(enum.Enum):
    AB_SELECTION = "AB_SELECTION"      # Layer A/B/C (component selection)
    PROTECTED_D = "PROTECTED_D"        # Layer D (ranking)


class TruthState(enum.Enum):
    TEXT = "TEXT"                          # v1-normalisable human text with ≥ 1 letter and ≥ 1 digit
    UNSUPPORTED_TEXT = "UNSUPPORTED_TEXT"  # any other non-reserved human text: retained, never a recall denominator
    NO_PLATE = "NO_PLATE"
    UNREADABLE = "UNREADABLE"
    NO_GT_VEHICLE = "NO_GT_VEHICLE"


HUMAN_STATES = ("TEXT", "NO_PLATE", "UNREADABLE", "NO_GT_VEHICLE")   # the document vocabulary
_RESERVED = frozenset(re.sub(r"[\s_-]", "", s.value) for s in TruthState)


# ---------------------------------------------------------------------------------------------- canonical JSON


def canonical_bytes(value: object) -> bytes:
    """The ONE canonical form: sorted keys, ``,``/``:`` separators, ASCII with ``\\uXXXX`` escapes, NaN/Infinity
    refused, one final LF."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return (text + "\n").encode("ascii")


def document_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_canonical(data: object, code: str) -> object:
    """Strict parse: exact ``bytes``, ASCII, no duplicate key, no NaN/Infinity, and the canonical re-serialisation must
    equal the input bytes (so whitespace, key order, number forms and escapes have exactly one representation)."""
    if type(data) is not bytes:
        raise ValueError(f"{code}_not_bytes")
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{code}_not_ascii") from exc

    def pairs(items):
        keys = [k for k, _ in items]
        if len(keys) != len(set(keys)):
            raise ValueError(f"{code}_duplicate_key")
        return dict(items)

    def constant(name):
        raise ValueError(f"{code}_non_finite_number")

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{code}_not_json") from exc
    try:
        again = canonical_bytes(value)
    except ValueError as exc:  # an out-of-range float such as 1e400
        raise ValueError(f"{code}_non_finite_number") from exc
    if again != data:
        raise ValueError(f"{code}_not_canonical")
    return value


# ---------------------------------------------------------------------------------------------- primitive checks


def _fail(code: str):
    raise ValueError(code)


def _obj(value: object, keys: tuple[str, ...], code: str) -> dict:
    if type(value) is not dict or set(value) != set(keys):
        _fail(code)
    return value


def _list(value: object, code: str) -> list:
    if type(value) is not list:
        _fail(code)
    return value


def _str(value: object, code: str, pattern: re.Pattern | None = None) -> str:
    if type(value) is not str or not value or (pattern is not None and not pattern.match(value)):
        _fail(code)
    return value


def _int(value: object, code: str, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        _fail(code)
    return value


def _sha(value: object, code: str) -> str:
    return _str(value, code, _SHA_RE)


def _uuid(value: object, code: str) -> str:
    _str(value, code)
    try:
        if str(UUID(value)) != value:
            _fail(code)
    except ValueError:
        _fail(code)
    return value


def _number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _sorted_unique(keys: list, code: str) -> None:
    if keys != sorted(set(keys)) or len(keys) != len(set(keys)):
        _fail(code)


def _polygon_area(points) -> Fraction:
    return abs(sum((x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, list(points[1:]) + [points[0]])),
                   Fraction(0))) / 2


def _polygon(value: object, code: str) -> tuple[tuple[float, float], ...]:
    points = _list(value, code)
    if len(points) < 3:
        _fail(code)
    out = []
    for point in points:
        if type(point) is not list or len(point) != 2 or not all(_number(v) and v >= 0 for v in point):
            _fail(code)
        out.append((point[0], point[1]))
    if _polygon_area([(Fraction(x), Fraction(y)) for x, y in out]) <= 0:
        _fail(code)
    return tuple(out)


# ---------------------------------------------------------------------------------------------- truth classification


def is_reserved_truth_text(text: str) -> bool:
    """Reserved syntax, exactly the repository's defined encodings of non-text truth: a truth-state name (case,
    whitespace, ``_`` and ``-`` ignored) or a ``<…>`` sentinel/control token (begins with ``<`` AND ends with ``>``)."""
    stripped = text.strip()
    return (stripped.startswith("<") and stripped.endswith(">")) or \
        re.sub(r"[\s_-]", "", stripped).upper() in _RESERVED


def classify_truth(state: object, text: object) -> tuple[TruthState, str | None, str | None]:
    """(typed state, raw text, supported normalised text) for one document truth. Unknown states and reserved syntax
    fail closed; non-text states carry no text; human text is TEXT or UNSUPPORTED_TEXT, never refused for content."""
    if type(state) is not str or state not in HUMAN_STATES:
        _fail("truth_state_unknown")
    if state != "TEXT":
        if text is not None:
            _fail("truth_text_only_for_text")
        return TruthState(state), None, None
    if type(text) is not str or not is_raw_text(text) or text != text.strip():
        _fail("truth_text_malformed")
    if is_reserved_truth_text(text):
        _fail("truth_text_is_reserved_syntax")
    result = normalise(text)
    supported = result.normalised if result.outcome == OK else None
    if supported is not None and re.search(r"[A-Z]", supported) and re.search(r"[0-9]", supported):
        return TruthState.TEXT, text, supported
    return TruthState.UNSUPPORTED_TEXT, text, None


# ---------------------------------------------------------------------------------------------- harness-owned state


@dataclass(frozen=True, slots=True)
class _Image:
    observation_id: str
    role: str
    rank: int
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class _Track:
    track_id: str
    site: str
    partition: Partition
    mavi_track_uuid: str | None
    evidence: tuple[_Image, ...]
    state: TruthState | None          # None: the D truth is not loaded at the selection stage
    text: str | None
    supported: str | None             # the v1-normalised TEXT truth (TEXT only)

    @property
    def has_mavi_evidence(self) -> bool:
        return bool(self.evidence)


@dataclass(frozen=True, slots=True)
class _Crop:
    crop_id: str
    track_id: str
    observation_id: str
    polygons: tuple[tuple[tuple[float, float], ...], ...]


@dataclass(frozen=True, slots=True)
class _Plate:
    plate_id: str
    track_id: str
    image: _Image | None
    observation_id: str | None


@dataclass(frozen=True, slots=True)
class _Protocol:
    query: QueryParameters
    bootstrap_seed: int
    replicates: int
    calibration_minimum: int
    top_k: int
    support_floor: int
    floors: MappingProxyType          # detector id → pinned floor


@dataclass(frozen=True, slots=True)
class _Roster:
    detectors: MappingProxyType       # id → identity SHA-256
    recognisers: MappingProxyType
    independent: MappingProxyType     # component id → the predeclared N4 independence verdict (frozen, never a caller input)
    benchmark_id: str
    benchmark_sha256: str
    layer_a_gates_sha256: str
    frozen_at_utc: str
    event_id: str
    composition_id: str
    partner_event_id: str
    ranking_rule_sha256: str


@dataclass(frozen=True, slots=True)
class _Part:
    partition: Partition
    digest: str
    tracks: MappingProxyType          # track id → _Track
    crops: MappingProxyType
    b_plates: MappingProxyType
    c_plates: MappingProxyType
    truth_loaded: bool
    index_loaded: bool


@dataclass(frozen=True, slots=True)
class _State:
    bundle_id: str
    stage: str
    record_sha256: str
    freeze_commit: str
    plan_digest: str
    sites: MappingProxyType           # site → Partition
    protocol: _Protocol
    roster: _Roster
    ab: _Part
    d: _Part

    def part(self, partition: Partition) -> _Part:
        return self.ab if partition is Partition.AB_SELECTION else self.d


@dataclass(frozen=True, slots=True)
class Bundle:
    """A handle on verified harness state. Only ``bundle_id`` is ever read back; the rest is informational."""

    bundle_id: str
    stage: str
    record_sha256: str
    freeze_commit: str
    ab_digest: str
    d_digest: str
    plan_digest: str


_BUNDLES: dict[str, _State] = {}
_D_DATA_LOADED: set[str] = set()      # record SHA-256s whose protected-D index or truth this process has opened
_D_TRUTH_LOADED: set[str] = set()     # record SHA-256s (or freeze constructions) whose protected-D truth was read
_CANDIDATE_ACTIVE = [0]               # depth of candidate execution in progress (owner point 5)


def _state_of(bundle: object) -> _State:
    """The harness state a handle names. Only the id string is read; unknown ids are refused."""
    key = getattr(bundle, "bundle_id", None)
    if type(key) is not str or key not in _BUNDLES:
        _fail("bundle_not_loaded_by_the_harness")
    return _BUNDLES[key]


def d_truth_loaded(record_sha256: str) -> bool:
    return record_sha256 in _D_TRUTH_LOADED


def d_data_loaded(record_sha256: str) -> bool:
    """Any protected-D data (index or truth) of this record was opened in this process (Stage 2 is then over)."""
    return record_sha256 in _D_DATA_LOADED


def protected_truth_resident() -> bool:
    """True once ANY protected-D truth has been read in this process: candidate execution is then refused."""
    return bool(_D_TRUTH_LOADED)


@contextmanager
def _candidate_execution() -> Iterator[None]:
    """Owner point 5. Every execution envelope runs inside this guard: no candidate code runs once protected-D truth
    has been read in this process, and the D truth cannot be read while candidate code is running."""
    if _D_TRUTH_LOADED:
        _fail("candidate_execution_after_protected_d_truth_loaded")
    _CANDIDATE_ACTIVE[0] += 1
    try:
        yield
    finally:
        _CANDIDATE_ACTIVE[0] -= 1


def _authorise_protected_d(selection_state: _State, authorization: object, resolution: object) -> None:
    """THE harness side of the pre-D gate, called before any protected-D path is opened (owner point 4).

    #218 integrates no protected-D authority, so it refuses every request (fail closed). The mandated integration PR
    replaces this body with the M3 bridge: ``m3_authority.open_protected_d`` called BY THE HARNESS (never a
    caller-built ``DAuthorization``, which is a plain dataclass), the record SHA-256 bound to both M3 frozen ledgers,
    the harness resolution equal to the committed RESOLVED seal (partner id and identity, composition SHA-256), and the
    returned anchor/seal bound into every D manifest (decision record §6). A caller-supplied verdict
    (``gates_passed``, ``independent``, ``d_rows_read``) can never satisfy it."""
    raise ValueError("protected_d_not_authorised:m3_authority_not_integrated")


# ---------------------------------------------------------------------------------------------- the freeze record


def _harness_repository() -> Path:
    return Path(__file__).resolve().parents[4]


def _read_record(repo_root: Path) -> tuple[bytes, str]:
    """The committed record bytes (by blob id from HEAD) and its freeze commit (the unique first add), under M3's
    isolated Git profile and full-history walk. Refusals: absent, not committed, not the repository root, an
    incomplete history (shallow or grafted), a dirty or index-hidden work-tree copy, or any history that is not
    add-only for the record path (owner point 1)."""
    root = repo_root.resolve()
    if not (root / FREEZE_RECORD_PATH).is_file():
        _fail("freeze_record_absent")
    try:
        history = m3_git.path_history(root, FREEZE_RECORD_PATH)   # refuses a non-root, shallow or grafted history
    except CredibilityError as exc:
        code = str(exc)
        if code.startswith("model_selection_history_unavailable"):
            reason = code.rsplit(":", 1)[-1]
            if reason == "absent":
                _fail("freeze_record_root_is_not_a_repository_root")
            _fail(f"freeze_record_history_incomplete:{reason}")
        _fail(f"freeze_record_not_committed:{code[:200]}")
    try:
        blob = history.head_tree.get(FREEZE_RECORD_PATH)
        if blob is None:
            _fail("freeze_record_not_committed")
        if m3_git.worktree_status(root, [FREEZE_RECORD_PATH]):
            _fail("freeze_record_differs_from_its_commit")   # an uncommitted edit is never the record
        if history.deletes.get(FREEZE_RECORD_PATH) or history.rewrites.get(FREEZE_RECORD_PATH) \
                or history.blobs.get(FREEZE_RECORD_PATH) != {blob}:
            _fail("freeze_record_not_add_only")   # edited, retyped or deleted at some commit of the reachable history
        commit = m3_git.first_add_commit(root, history.adds.get(FREEZE_RECORD_PATH, ()), "freezeRecord")
        data = m3_git.read_blobs(root, [blob])[blob]
    except CredibilityError as exc:   # a Git failure or an ambiguous first add is a refusal, never a pass
        code = str(exc)
        if code.startswith("worktree_index_flags_hide_changes"):
            _fail("freeze_record_differs_from_its_commit:index_flags_hide_changes")
        _fail(f"freeze_record_not_committed:{code[:200]}")
    return data, commit


def _identity_rows(value: object, code: str) -> tuple[MappingProxyType, dict[str, bool]]:
    """Rows ``[candidate id, identity SHA-256, independent]``. The N4 independence verdict is predeclared in the
    frozen record (owner point 4), never a caller input."""
    rows = _list(value, code)
    out, independent = {}, {}
    for row in rows:
        if type(row) is not list or len(row) != 3 or type(row[2]) is not bool:
            _fail(code)
        candidate = _str(row[0], code, _CANDIDATE_RE)
        out[candidate], independent[candidate] = _sha(row[1], code), row[2]
    _sorted_unique([r[0] for r in rows], code)
    if not out:
        _fail(code)
    return MappingProxyType(out), independent


def disjointness_attestation(documents: dict[str, str]) -> dict:
    """The freeze-construction result recorded in the record: the four documents named by these SHA-256s were checked
    together and share no site, Track id, MAVI uuid, observation id or image content across the partitions. It is a
    record of the check (``selection_freeze.construct_freeze_record``), re-run on the real D index when D opens."""
    checks = list(DISJOINTNESS_CHECKS)
    return {"checks": checks, "result": DISJOINT,
            "sha256": document_sha256(canonical_bytes({"checks": checks, "documents": dict(documents),
                                                       "result": DISJOINT}))}


def _parse_record(data: bytes) -> tuple[_Protocol, _Roster, dict[str, Partition], str, dict[str, str]]:
    record = _obj(parse_canonical(data, "freeze_record"), ("schema", "protocol", "roster", "partitionPlan",
                                                            "documents", "disjointness"), "freeze_record_malformed")
    if record["schema"] != RECORD_SCHEMA:
        _fail("freeze_record_schema")
    p = _obj(record["protocol"], ("query", "bootstrapSeed", "bootstrapReplicates", "percentileRule", "mpid",
                                  "calibrationMinimumClusters", "topK", "topKSupportFloor", "detectorFloors"),
             "freeze_protocol_malformed")
    q = _obj(p["query"], ("interiorOffset", "negativesPerPlate", "seed"), "freeze_protocol_malformed")
    query = QueryParameters(_int(q["interiorOffset"], "freeze_protocol_malformed", 1),
                            _int(q["negativesPerPlate"], "freeze_protocol_malformed", 0),
                            _str(q["seed"], "freeze_protocol_malformed"))
    if p["bootstrapReplicates"] != BOOTSTRAP_REPLICATES or type(p["bootstrapReplicates"]) is not int:
        _fail("freeze_protocol_replicates_not_frozen_value")
    if (type(p["topK"]) is not int or p["topK"] != TOP_K or type(p["topKSupportFloor"]) is not int
            or p["topKSupportFloor"] != TOP_K_SUPPORT_FLOOR):
        _fail("freeze_protocol_top_k_not_frozen_value")
    if p["percentileRule"] != PERCENTILE_RULE or p["mpid"] != MPID_TEXT:
        _fail("freeze_protocol_rule_not_frozen")
    floors_rows = _list(p["detectorFloors"], "freeze_protocol_detector_floors_malformed")
    floors = {}
    for row in floors_rows:
        if (type(row) is not list or len(row) != 2 or type(row[1]) not in (int, float) or not math.isfinite(row[1])
                or not 0 <= row[1] <= 1):
            _fail("freeze_protocol_detector_floors_malformed")
        floors[_str(row[0], "freeze_protocol_detector_floors_malformed", _CANDIDATE_RE)] = float(row[1])
    _sorted_unique([r[0] for r in floors_rows], "freeze_protocol_detector_floors_malformed")
    protocol = _Protocol(query, _int(p["bootstrapSeed"], "freeze_protocol_malformed"), BOOTSTRAP_REPLICATES,
                         _int(p["calibrationMinimumClusters"], "freeze_protocol_malformed", 1), TOP_K,
                         TOP_K_SUPPORT_FLOOR, MappingProxyType(floors))
    r = _obj(record["roster"], ("detectors", "recognisers", "benchmarkOnly", "rankingRuleSha256",
                                "layerAGatesSha256", "frozenAtUtc", "eventId", "compositionId", "partnerEventId"),
             "freeze_roster_malformed")
    detectors, independent = _identity_rows(r["detectors"], "freeze_roster_detectors_malformed")
    recognisers, independent_ocr = _identity_rows(r["recognisers"], "freeze_roster_recognisers_malformed")
    benchmark = _list(r["benchmarkOnly"], "freeze_roster_malformed")
    if len(benchmark) != 2:
        _fail("freeze_roster_malformed")
    benchmark_id = _str(benchmark[0], "freeze_roster_malformed", _CANDIDATE_RE)
    benchmark_sha = _sha(benchmark[1], "freeze_roster_malformed")
    if benchmark_id in detectors or benchmark_id in recognisers:
        _fail("freeze_roster_benchmark_only_component_in_a_universe")
    if set(detectors) & set(recognisers):
        _fail("freeze_roster_identity_under_two_ids")
    hashes = [*detectors.values(), *recognisers.values(), benchmark_sha]
    if len(set(hashes)) != len(hashes):
        _fail("freeze_roster_identity_under_two_ids")
    if set(floors) != set(detectors):
        _fail("freeze_protocol_detector_floors_are_not_the_detector_universe")
    if r["rankingRuleSha256"] != DETECTOR_RANKING_RULE_SHA256:
        _fail("freeze_roster_ranking_rule_not_the_frozen_rule")
    composition_id = _str(r["compositionId"], "freeze_roster_composition_id_malformed", _COMPOSITION_RE)
    if composition_id.startswith(M3_ORDINARY_COMPOSITION_PREFIX):
        _fail("freeze_roster_composition_id_reserved")   # M3: "C-" is the derived ordinary-composition namespace
    roster = _Roster(detectors, recognisers, MappingProxyType({**independent, **independent_ocr}), benchmark_id,
                     benchmark_sha, _sha(r["layerAGatesSha256"], "freeze_roster_malformed"),
                     _str(r["frozenAtUtc"], "freeze_roster_time_malformed", _UTC_RE),
                     _str(r["eventId"], "freeze_roster_event_id_malformed", _EVENT_RE), composition_id,
                     _str(r["partnerEventId"], "freeze_roster_event_id_malformed", _EVENT_RE),
                     DETECTOR_RANKING_RULE_SHA256)
    if roster.event_id == roster.partner_event_id:
        _fail("freeze_roster_partner_event_is_the_baseline_event")   # M3: the partner is the OTHER group member
    plan = _obj(record["partitionPlan"], ("planId", "sites"), "freeze_partition_plan_malformed")
    _str(plan["planId"], "freeze_partition_plan_malformed", _ID_RE)
    rows = _list(plan["sites"], "freeze_partition_plan_malformed")
    sites: dict[str, Partition] = {}
    for row in rows:
        if type(row) is not list or len(row) != 2 or row[1] not in ("AB_SELECTION", "PROTECTED_D"):
            _fail("freeze_partition_plan_malformed")
        site = _str(row[0], "freeze_partition_plan_malformed")
        if site in sites:
            _fail("freeze_partition_plan_site_in_two_partitions")
        sites[site] = Partition(row[1])
    if any(s != s.strip() or not s.isprintable() for s in sites) or \
            len({s.casefold() for s in sites}) != len(sites):
        _fail("freeze_partition_plan_site_not_canonical")  # "s1", "s1 " and "S1" are one site, never two
    _sorted_unique([row[0] for row in rows], "freeze_partition_plan_not_in_canonical_order")
    if set(sites.values()) != set(Partition):
        _fail("freeze_partition_plan_needs_both_partitions")
    documents = _obj(record["documents"], tuple(DOCUMENT_FILES), "freeze_documents_malformed")
    for value in documents.values():
        _sha(value, "freeze_documents_malformed")
    if record["disjointness"] != disjointness_attestation(dict(documents)):
        _fail("freeze_record_disjointness_not_attested")   # owner point 2: established at freeze construction
    return protocol, roster, sites, document_sha256(canonical_bytes(plan)), dict(documents)


# ---------------------------------------------------------------------------------------------- corpus documents


def _image(value: object, roles: tuple[str, ...], code: str) -> _Image:
    v = _obj(value, ("observationId", "role", "rank", "sha256", "sizeBytes"), code)
    if v["role"] not in roles:
        _fail(code)
    return _Image(_uuid(v["observationId"], code), v["role"], _int(v["rank"], code, 0), _sha(v["sha256"], code),
                  _int(v["sizeBytes"], code, 1))


def _read_document(directory: Path, key: str, expected_sha256: str) -> object:
    path = directory / DOCUMENT_FILES[key]
    if not path.is_file():
        _fail(f"corpus_document_absent:{key}")
    data = path.read_bytes()
    if document_sha256(data) != expected_sha256:
        _fail(f"corpus_document_not_the_frozen_document:{key}")
    return parse_canonical(data, f"corpus_document_{key}")


def _index(value: object, partition: Partition, sites: dict[str, Partition]) -> list[dict]:
    doc = _obj(value, ("schema", "partition", "tracks"), "index_malformed")
    if doc["schema"] != INDEX_SCHEMA or doc["partition"] != partition.value:
        _fail("index_is_not_this_partition")
    rows = _list(doc["tracks"], "index_malformed")
    out = []
    for row in rows:
        t = _obj(row, ("trackId", "site", "maviTrackUuid", "evidence"), "index_track_malformed")
        track_id = _str(t["trackId"], "index_track_malformed", _ID_RE)
        site = _str(t["site"], "index_track_malformed")
        if sites.get(site) is not partition:
            _fail("index_site_not_in_this_partition")   # site-disjoint partitions (protocol §3.1)
        evidence = tuple(_image(e, EVIDENCE_ROLES, "index_evidence_malformed")
                         for e in _list(t["evidence"], "index_evidence_malformed"))
        ranks = [e.rank for e in evidence]
        if ranks != sorted(set(ranks)):
            _fail("index_evidence_ranks_not_strictly_ordered")
        uuid = None if t["maviTrackUuid"] is None else _uuid(t["maviTrackUuid"], "index_track_malformed")
        if bool(evidence) != (uuid is not None):
            _fail("index_mavi_track_and_evidence_disagree")
        out.append({"trackId": track_id, "site": site, "uuid": uuid, "evidence": evidence})
    _sorted_unique([t["trackId"] for t in out], "index_tracks_not_in_canonical_order")
    if not out:
        _fail("index_without_tracks")
    return out


def _truth(value: object, partition: Partition, index: list[dict]) -> tuple[dict, list[_Crop], list[_Plate]]:
    doc = _obj(value, ("schema", "partition", "truths", "crops", "plates"), "truth_malformed")
    if doc["schema"] != TRUTH_SCHEMA or doc["partition"] != partition.value:
        _fail("truth_is_not_this_partition")
    truths = {}
    rows = _list(doc["truths"], "truth_malformed")
    for row in rows:
        t = _obj(row, ("trackId", "state", "text"), "truth_row_malformed")
        truths[_str(t["trackId"], "truth_row_malformed", _ID_RE)] = classify_truth(t["state"], t["text"])
    _sorted_unique([r["trackId"] for r in rows], "truth_rows_not_in_canonical_order")
    if list(truths) != [t["trackId"] for t in index]:
        _fail("truth_tracks_are_not_the_index_tracks")
    by_track = {t["trackId"]: t for t in index}
    for tid, (state, _, _) in truths.items():
        if state is TruthState.NO_GT_VEHICLE and not by_track[tid]["evidence"]:
            _fail("truth_no_gt_vehicle_without_mavi_evidence")  # by definition a MAVI Track
    crops, plates = [], []
    crop_rows = _list(doc["crops"], "truth_crops_malformed")
    plate_rows = _list(doc["plates"], "truth_plates_malformed")
    if partition is Partition.PROTECTED_D and (crop_rows or plate_rows):
        _fail("truth_d_partition_holds_a_b_items")   # A/B/C project only from the A/B partition
    for row in crop_rows:
        c = _obj(row, ("cropId", "trackId", "observationId", "polygons"), "truth_crop_malformed")
        track = by_track.get(c["trackId"])
        if track is None or c["observationId"] not in {e.observation_id for e in track["evidence"]}:
            _fail("truth_crop_not_an_evidence_image_of_this_partition")
        polygons = tuple(_polygon(p, "truth_crop_polygon_malformed")
                         for p in _list(c["polygons"], "truth_crop_polygon_malformed"))
        if polygons and truths[c["trackId"]][0] in (TruthState.NO_PLATE, TruthState.NO_GT_VEHICLE):
            _fail("truth_crop_polygon_contradicts_truth")
        crops.append(_Crop(_str(c["cropId"], "truth_crop_malformed", _ID_RE), c["trackId"], c["observationId"],
                           polygons))
    _sorted_unique([c.crop_id for c in crops], "truth_crops_not_in_canonical_order")
    for row in plate_rows:
        p = _obj(row, ("plateId", "trackId", "plateImage", "observationId"), "truth_plate_malformed")
        track = by_track.get(p["trackId"])
        if track is None or truths[p["trackId"]][0] not in (TruthState.TEXT, TruthState.UNSUPPORTED_TEXT):
            _fail("truth_plate_not_on_a_text_track_of_this_partition")
        image = None if p["plateImage"] is None else _image(p["plateImage"], (PLATE_IMAGE_ROLE,),
                                                            "truth_plate_image_malformed")
        observation = p["observationId"]
        if observation is not None and observation not in {e.observation_id for e in track["evidence"]}:
            _fail("truth_plate_not_in_an_evidence_image")
        if image is None and observation is None:
            _fail("truth_plate_in_no_layer")
        plates.append(_Plate(_str(p["plateId"], "truth_plate_malformed", _ID_RE), p["trackId"], image, observation))
    _sorted_unique([p.plate_id for p in plates], "truth_plates_not_in_canonical_order")
    _unique([c.observation_id for c in crops], "truth_two_crops_on_one_evidence_image")
    _unique([(p.track_id, p.observation_id) for p in plates if p.observation_id is not None],
            "truth_two_c_plates_on_one_evidence_image")
    return truths, crops, plates


def _unique(values: list, code: str) -> None:
    if len(values) != len(set(values)):
        _fail(code)


def _part(partition: Partition, digest: str, index: list[dict] | None, truth) -> _Part:
    truths, crops, plates = truth if truth is not None else ({}, [], [])
    tracks = {}
    for t in index or ():
        state, text, supported = truths.get(t["trackId"], (None, None, None))
        tracks[t["trackId"]] = _Track(t["trackId"], t["site"], partition, t["uuid"], t["evidence"], state, text,
                                      supported)
    return _Part(partition, digest, MappingProxyType(tracks), MappingProxyType({c.crop_id: c for c in crops}),
                 MappingProxyType({p.plate_id: p for p in plates if p.image is not None}),
                 MappingProxyType({p.plate_id: p for p in plates if p.observation_id is not None}),
                 truth is not None, index is not None)


def check_disjoint(ab_index: list[dict], ab_plates: list[_Plate], d_index: list[dict]) -> None:
    """The paired corpus (R2): Track ids, MAVI uuids, observation ids and content SHA-256s are unique across BOTH
    partitions (sites are disjoint by the plan and the per-partition site check)."""
    everything = ab_index + d_index
    images = [e for t in everything for e in t["evidence"]] + [p.image for p in ab_plates if p.image is not None]
    _unique([t["trackId"] for t in everything], "bundle_track_id_in_two_partitions")
    _unique([t["uuid"] for t in everything if t["uuid"] is not None], "bundle_mavi_track_shared_by_two_tracks")
    _unique([e.observation_id for e in images], "bundle_observation_shared_by_two_images")
    _unique([e.sha256 for e in images], "bundle_content_shared_by_two_images")


def partition_digest(record_sha256: str, partition: Partition) -> str:
    return document_sha256(canonical_bytes({"freezeRecordSha256": record_sha256, "partition": partition.value}))


def _load(corpus_dir: object, repo_root: object, stage: str,
          precondition: Callable[[_State], None] | None = None) -> Bundle:
    """Open ONLY what the stage needs (owner point 2). ``SELECTION``: the record and the two A/B documents; no D path
    is constructed or opened. ``D_CAPTURE`` adds the D index; ``PROTECTED_D`` adds the D truth. For a D stage,
    ``precondition(selection_state)`` (the verified Stage-2 resolution and the protected-D authority, supplied by the
    evaluator) runs before any D path is touched; the D data is marked read before it is opened (fail safe)."""
    if stage not in (SELECTION, D_CAPTURE, PROTECTED):
        _fail("bundle_stage_unknown")
    if not isinstance(corpus_dir, (str, os.PathLike)):
        _fail("corpus_directory_malformed")
    if stage == PROTECTED and _CANDIDATE_ACTIVE[0]:
        _fail("protected_d_truth_load_during_candidate_execution")
    root = _harness_repository() if repo_root is None else Path(os.fspath(repo_root))
    data, commit = _read_record(root)
    protocol, roster, sites, plan_digest, documents = _parse_record(data)
    record_sha = document_sha256(data)
    directory = Path(os.fspath(corpus_dir))
    ab_index = _index(_read_document(directory, "abIndex", documents["abIndex"]), Partition.AB_SELECTION, sites)
    ab_truth = _truth(_read_document(directory, "abTruth", documents["abTruth"]), Partition.AB_SELECTION, ab_index)
    ab = _part(Partition.AB_SELECTION, partition_digest(record_sha, Partition.AB_SELECTION), ab_index, ab_truth)
    d_digest = partition_digest(record_sha, Partition.PROTECTED_D)

    def state_for(name: str, d_part: _Part) -> _State:
        bundle_id = document_sha256(canonical_bytes({"freezeRecordSha256": record_sha, "stage": name}))
        return _State(bundle_id, name, record_sha, commit, plan_digest, MappingProxyType(dict(sites)), protocol,
                      roster, ab, d_part)

    state = state_for(SELECTION, _part(Partition.PROTECTED_D, d_digest, None, None))
    if stage != SELECTION:
        if precondition is None:
            _fail("protected_d_not_authorised:no_precondition")
        precondition(state)
        if stage == PROTECTED and _CANDIDATE_ACTIVE[0]:
            _fail("protected_d_truth_load_during_candidate_execution")
        _D_DATA_LOADED.add(record_sha)
        d_index = _index(_read_document(directory, "dIndex", documents["dIndex"]), Partition.PROTECTED_D, sites)
        check_disjoint(ab_index, ab_truth[2], d_index)   # the recorded attestation, re-verified on the real D index
        d_truth = None
        if stage == PROTECTED:
            _D_TRUTH_LOADED.add(record_sha)
            d_truth = _truth(_read_document(directory, "dTruth", documents["dTruth"]), Partition.PROTECTED_D,
                             d_index)
        state = state_for(stage, _part(Partition.PROTECTED_D, d_digest, d_index, d_truth))
    _BUNDLES[state.bundle_id] = state
    return Bundle(state.bundle_id, stage, record_sha, commit, ab.digest, d_digest, plan_digest)


def load_selection_bundle(corpus_dir, *, repo_root=None) -> Bundle:
    """The selection stage (Layer A/B/C, top-K, the Stage-2 resolution): the frozen record and the A/B documents ONLY.
    No D index or D truth is opened or needed; the D partition digest is the record's commitment."""
    return _load(corpus_dir, repo_root, SELECTION)
