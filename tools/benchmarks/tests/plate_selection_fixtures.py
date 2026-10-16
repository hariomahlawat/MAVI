"""Synthetic fixtures for the plate-selection harness: frozen records committed in temporary Git repositories, and
canonical corpus documents. No dataset, no model.

Every ``build`` writes the four corpus documents, builds the freeze record with the real freeze-construction tool
(``selection_freeze``; a record edited by ``mutate_record`` or forged with ``forge_record`` is assembled by hand with
the same attestation helper), commits it at ``FREEZE_RECORD_PATH`` in a fresh temporary repository and loads the
bundle through the real loader. The expected identities therefore always come from a committed record, never from a
value passed beside the content.

**Protected D in tests.** #218 integrates no protected-D authority, so the real D loaders refuse every request
(``selection_bundle._authorise_protected_d``). Tests that exercise D scoring patch that one function, inside
``authorised()`` only, with a stub accepting only the test object ``TEST_AUTHORITY``. Scoring-semantics tests also run
candidates after a D score, which the harness refuses within one process; ``Corpus.full`` therefore ends its load with
``new_process()`` (forget the in-process "protected truth read" mark), modelling a separate scoring process. The order
itself (capture, then truth, then no execution) is proven without that reset in ``test_plates_selection_boundary``.
"""

from __future__ import annotations

import atexit
import contextlib
import dataclasses
import hashlib
import io
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from PIL import Image

from mavi_vision.plates.inference import PlateBox, Reading
from tools.benchmarks.capabilities.plates import evaluator as ev
from tools.benchmarks.capabilities.plates import queries as q
from tools.benchmarks.capabilities.plates import selection_bundle as sb
from tools.benchmarks.capabilities.plates import selection_freeze as sf

PARAMS = q.QueryParameters(interior_offset=1, negatives_per_plate=2, seed="synthetic-seed")
FLOOR = 0.25
NS = uuid.NAMESPACE_URL
WHEN = "2026-10-14T00:00:00Z"
EVENTS = ("msr-ocr-2026-01", "GATE-BASE", "msr-plate-detector-2026-01")
DETECTORS = ("PD1-X", "PD2-N", "PD2-S")
RECOGNISERS = ("OC1-XS", "OC2-A", "OC2-B")
AB, D = ev.Partition.AB_SELECTION, ev.Partition.PROTECTED_D


def _h(text):
    return hashlib.sha256(text.encode()).hexdigest()


def ident(candidate_id):
    return ev.ComponentIdentity(candidate_id, _h(candidate_id))


DET, REC, OC5, PD_BASE = ident("PD2-S"), ident("OC1-XS"), ident("OC5-BEST"), ident("PD2-N")

_ROOT = Path(tempfile.mkdtemp(prefix="mavi-plate-selection-", dir=os.environ.get("TMP") or None))
atexit.register(shutil.rmtree, _ROOT, True)


# ---------------------------------------------------------------------------------------------- images


def _jpeg(size, colour=(200, 200, 200)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="JPEG")
    return buffer.getvalue()


IMAGES: dict[str, bytes] = {}


def _stored(content: bytes) -> tuple[str, int]:
    sha = hashlib.sha256(content).hexdigest()
    IMAGES[sha] = content
    return sha, len(content)


def images(observation_id, sha256):
    return IMAGES[sha256]


def oid(tid, k):
    return str(uuid.uuid5(NS, f"{tid}/{k}"))


def tuuid(tid):
    return str(uuid.uuid5(NS, f"track/{tid}"))


def evidence_row(tid, k, role="near-view"):
    seed = hashlib.sha256(f"{tid}/{k}".encode()).digest()
    sha, size = _stored(_jpeg((64, 32), (seed[0], seed[1], seed[2])))
    return {"observationId": oid(tid, k), "rank": k, "role": role, "sha256": sha, "sizeBytes": size}


def plate_image(i):
    """A distinct GT plate-crop image per B plate."""
    sha, size = _stored(_jpeg((40, 12), (i * 3 % 256, 90, 160)))
    return {"observationId": oid(f"plate{i}", 0), "rank": 0, "role": "gt-plate-crop", "sha256": sha,
            "sizeBytes": size}


# ---------------------------------------------------------------------------------------------- corpus items


@dataclasses.dataclass(frozen=True)
class State:
    name: str


NO_PLATE, UNREADABLE, NO_GT_VEHICLE = State("NO_PLATE"), State("UNREADABLE"), State("NO_GT_VEHICLE")


@dataclasses.dataclass
class T:
    """A test-side Track: ``truth`` is human text or a ``State``; ``n`` evidence images (0: no MAVI Track)."""

    track_id: str
    site: str
    truth: object
    n: int = 1

    def __post_init__(self):
        self.evidence = [evidence_row(self.track_id, k) for k in range(self.n)]
        self.mavi = tuuid(self.track_id) if self.n else None

    def index_row(self):
        return {"evidence": self.evidence, "maviTrackUuid": self.mavi, "site": self.site, "trackId": self.track_id}

    def truth_row(self):
        if isinstance(self.truth, State):
            return {"state": self.truth.name, "text": None, "trackId": self.track_id}
        return {"state": "TEXT", "text": self.truth, "trackId": self.track_id}


def crop(crop_id, track_id, k, polygons):
    return {"cropId": crop_id, "observationId": oid(track_id, k), "polygons": [[list(p) for p in poly]
                                                                              for poly in polygons],
            "trackId": track_id}


def plate(plate_id, track_id, b=None, c=None):
    """``b``: the plate-image index (a B item); ``c``: the evidence index (a C item)."""
    return {"observationId": None if c is None else oid(track_id, c), "plateId": plate_id,
            "plateImage": None if b is None else plate_image(b), "trackId": track_id}


# ---------------------------------------------------------------------------------------------- record and bundle


def default_protocol(detectors=DETECTORS):
    return {"bootstrapReplicates": 1000, "bootstrapSeed": 7, "calibrationMinimumClusters": 60,
            "detectorFloors": [[d, FLOOR] for d in sorted(detectors)], "mpid": "4/100",
            "percentileRule": ev.PERCENTILE_RULE,
            "query": {"interiorOffset": PARAMS.interior_offset, "negativesPerPlate": PARAMS.negatives_per_plate,
                      "seed": PARAMS.seed},
            "topK": 3, "topKSupportFloor": 50}


def default_roster(detectors=DETECTORS, recognisers=RECOGNISERS, dependent=()):
    """``dependent``: component ids whose predeclared N4 verdict is "not demonstrably independent"."""
    return {"benchmarkOnly": ["OC5-BEST", _h("OC5-BEST")], "compositionId": EVENTS[1],
            "detectors": [[d, _h(d), d not in dependent] for d in sorted(detectors)], "eventId": EVENTS[0],
            "frozenAtUtc": "2026-10-01T00:00:00Z", "layerAGatesSha256": _h("layer-a-gates"),
            "partnerEventId": EVENTS[2], "rankingRuleSha256": ev.DETECTOR_RANKING_RULE_SHA256,
            "recognisers": [[r, _h(r), r not in dependent] for r in sorted(recognisers)]}


TEST_AUTHORITY = object()   # the only value the test stub accepts (never accepted by the harness itself)


@contextlib.contextmanager
def authorised():
    """TEST ONLY: stand in for the (not yet integrated) protected-D authority for the duration of the block."""
    real = sb._authorise_protected_d

    def stub(selection_state, authorization, resolution):
        if authorization is not TEST_AUTHORITY:
            real(selection_state, authorization, resolution)

    sb._authorise_protected_d = stub
    try:
        yield
    finally:
        sb._authorise_protected_d = real


def new_process():
    """TEST ONLY: forget that protected truth was read in this process (a separate process in production)."""
    sb._D_TRUTH_LOADED.clear()


def fresh_process():
    """TEST ONLY: as a new process: no protected-D state, no protected marks, no cached D handles."""
    for key in [k for k, state in sb._BUNDLES.items() if state.stage != sb.SELECTION]:
        del sb._BUNDLES[key]
    sb._D_TRUTH_LOADED.clear()
    sb._D_DATA_LOADED.clear()
    for corpus in _CACHE.values():
        corpus._full = corpus._capture = None


def d_load(loader, directory, repo, resolution, layer_a):
    with authorised():
        return loader(directory, resolution=resolution, layer_a_results=layer_a, authorization=TEST_AUTHORITY,
                      repo_root=repo)


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def git(root: Path, *args: str) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "-C", str(root), "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
                    "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false", *args], check=True,
                   capture_output=True, env=env)


def git_out(root: Path, *args: str, input: bytes | None = None) -> str:  # noqa: A002
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(["git", "-C", str(root), "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
                           "-c", "core.autocrlf=false", *args], check=True, capture_output=True, env=env,
                          input=input).stdout.decode().strip()


def commit_record(data: bytes, name: str | None = None) -> Path:
    """A fresh repository whose HEAD holds ``data`` at the frozen record path."""
    root = _ROOT / (name or f"repo-{hashlib.sha256(data).hexdigest()[:20]}")
    if (root / sb.FREEZE_RECORD_PATH).is_file():
        return root
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    write(root / sb.FREEZE_RECORD_PATH, data)
    git(root, "add", sb.FREEZE_RECORD_PATH)
    git(root, "commit", "-q", "-m", "freeze")
    return root


@dataclasses.dataclass
class Corpus:
    """A built corpus: its committed repository, its document directory, the documents and the loaded bundles."""

    repo: Path
    directory: Path
    docs: dict
    record: dict
    tracks: list
    sel: object
    _full: object = None
    resolution: object = None
    layer_a: list | None = None
    _capture: object = None

    @property
    def capture(self):
        """The D-capture bundle (D evidence, no D truth): where candidates run on protected-D Tracks."""
        if self._capture is None:
            self._capture = d_load(ev.load_d_capture_bundle, self.directory, self.repo, self.resolution, self.layer_a)
        return self._capture

    @property
    def full(self):
        """The protected-D bundle (D truth) for scoring; see the module note on ``new_process``."""
        if self._full is None:
            self._full = d_load(ev.load_protected_d_bundle, self.directory, self.repo, self.resolution, self.layer_a)
            new_process()
        return self._full

    @property
    def ab_digest(self):
        return self.sel.ab_digest

    @property
    def d_digest(self):
        return self.sel.d_digest

    def track(self, tid):
        return next(t for t in self.all_tracks if t.track_id == tid)

    def evidence(self, tid):
        return tuple(ev.EvidenceImage(e["observationId"], e["role"], e["rank"], e["sha256"], e["sizeBytes"])
                     for e in self.track(tid).evidence)

    def bundle_for(self, tid):
        return self.capture if self.track(tid) in self.d_tracks else self.sel


_CACHE: dict[bytes, Corpus] = {}


def documents(ab_tracks, d_tracks, crops=(), plates=()):
    return {"abIndex": {"partition": "AB_SELECTION", "schema": sb.INDEX_SCHEMA,
                        "tracks": [t.index_row() for t in sorted(ab_tracks, key=lambda t: t.track_id)]},
            "abTruth": {"crops": sorted(crops, key=lambda c: c["cropId"]), "partition": "AB_SELECTION",
                        "plates": sorted(plates, key=lambda p: p["plateId"]), "schema": sb.TRUTH_SCHEMA,
                        "truths": [t.truth_row() for t in sorted(ab_tracks, key=lambda t: t.track_id)]},
            "dIndex": {"partition": "PROTECTED_D", "schema": sb.INDEX_SCHEMA,
                       "tracks": [t.index_row() for t in sorted(d_tracks, key=lambda t: t.track_id)]},
            "dTruth": {"crops": [], "partition": "PROTECTED_D", "plates": [], "schema": sb.TRUTH_SCHEMA,
                       "truths": [t.truth_row() for t in sorted(d_tracks, key=lambda t: t.track_id)]}}


def make_record(docs_bytes, sites, protocol=None, roster=None, plan_id="plan"):
    documents = {k: hashlib.sha256(v).hexdigest() for k, v in docs_bytes.items()}
    return {"disjointness": sb.disjointness_attestation(documents), "documents": documents,
            "partitionPlan": {"planId": plan_id, "sites": sites},
            "protocol": protocol or default_protocol(), "roster": roster or default_roster(),
            "schema": sb.RECORD_SCHEMA}


def construct(directory, record):
    """The real freeze-construction tool on ``directory`` (it marks protected truth read; tests then forget it)."""
    try:
        return sf.construct_freeze_record(directory, protocol=record["protocol"], roster=record["roster"],
                                          partition_plan=record["partitionPlan"])
    finally:
        sb._D_TRUTH_LOADED.discard("freeze-construction")


def build(tracks, crops=(), plates=(), *, partition=None, twin=None, sites=None, protocol=None, roster=None,
          mutate=None, mutate_record=None, raw=None, resolve=True, forge_record=False):
    """One corpus. ``tracks`` go to ``partition`` (A/B when there are A/B items, else protected D); ``twin`` (default:
    one Track) is the other partition. ``mutate(docs)`` edits the document objects before serialisation (the record
    then names the edited bytes); ``raw`` replaces document bytes outright; ``mutate_record(record)`` edits the record.
    ``forge_record`` skips the construction tool (a hand-assembled record whose attestation was never checked).
    The default baseline is resolved before any protected-D load."""
    partition = partition or (AB if crops or plates else D)
    if twin is None:
        twin = [T("twin-ab", "twin-ab-site", "KA99AB0001")] if partition is D else \
            [T("twin-d", "twin-d-site", "KA98AB0002")]
    ab_tracks, d_tracks = (list(tracks), list(twin)) if partition is AB else (list(twin), list(tracks))
    docs = documents(ab_tracks, d_tracks, crops, plates)
    if mutate is not None:
        mutate(docs)
    docs_bytes = {k: sb.canonical_bytes(v) for k, v in docs.items()}
    if raw:
        docs_bytes.update(raw)
    if sites is None:
        sites = sorted({(t.site, "AB_SELECTION") for t in ab_tracks} | {(t.site, "PROTECTED_D") for t in d_tracks})
        sites = [list(s) for s in sites]
    record = make_record(docs_bytes, sites, protocol, roster)
    if mutate_record is not None:
        mutate_record(record)
    record_bytes = sb.canonical_bytes(record)
    key = record_bytes + b"\x00" + b"\x00".join(docs_bytes[k] for k in sorted(docs_bytes))
    if key in _CACHE:
        cached = _CACHE[key]
        if resolve and cached.resolution is None and _resolvable(record):
            _resolve(cached)   # the same record built earlier with resolve=False (never D-loaded without one)
        return cached
    directory = _ROOT / f"corpus-{hashlib.sha256(key).hexdigest()[:20]}"
    for name, data in docs_bytes.items():
        write(directory / sb.DOCUMENT_FILES[name], data)
    if mutate_record is None and not forge_record:
        assert construct(directory, record) == record_bytes   # the real tool builds exactly this record
    repo = commit_record(record_bytes)
    sel = ev.load_selection_bundle(directory, repo_root=repo)
    corpus = Corpus(repo, directory, docs, record, list(tracks), sel)
    corpus.all_tracks = ab_tracks + d_tracks
    corpus.d_tracks = d_tracks
    if resolve and _resolvable(record):
        _resolve(corpus)
    _CACHE[key] = corpus
    return corpus


def _resolvable(record) -> bool:
    return set(r[0] for r in record["roster"]["detectors"]) == set(DETECTORS)


def _resolve(corpus) -> None:
    corpus.layer_a = layer_a_for(corpus)
    corpus.resolution = ev.resolve_baseline(corpus.sel, corpus.layer_a, d_rows_read=0, resolved_at_utc=WHEN)


# ---------------------------------------------------------------------------------------------- candidates


class Detector:
    def __init__(self, boxes):
        self.boxes = boxes

    def detect(self, crop, verified):
        return list(self.boxes)


class Recogniser:
    def __init__(self, texts):
        self.texts = list(texts)
        self.initial = list(texts)

    def read(self, region, verified, box):
        text = self.texts.pop(0)
        return [Reading(text, 0.9)] if text else []


class Outputs:
    """A recogniser returning the given reading lists in order."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.initial = list(outputs)

    def read(self, region, verified, box):
        return self.outputs.pop(0)


def boxes(n=1):
    return Detector([PlateBox(1 + k, 1, 20, 10, 0.9 - 0.1 * k) for k in range(n)])


GOOD_BOX = Detector([PlateBox(1, 1, 20, 10, 0.9)])


def R(*readings):
    return [Reading(t, c) for t, c in readings]


def run(corpus, tid, reads=None, *, n_boxes=1, det=DET, rec=REC, detector=None, recogniser=None, bundle=None):
    return ev.run_track(bundle or corpus.bundle_for(tid), tid, detector=detector or boxes(n_boxes),
                        recogniser=recogniser or Recogniser(reads or []), detector_identity=det,
                        recogniser_identity=rec, images=images)


def runs_for(corpus, outputs, **kw):
    """One run per evidence Track of the corpus's own Tracks; ``outputs`` maps Track id → reads."""
    return [run(corpus, t.track_id, outputs[t.track_id], **kw) for t in corpus.tracks if t.n]


def score(corpus, runs, composition=(DET, REC)):
    return ev.evaluate_d(corpus.full, runs, composition=composition)


def _plate_text(i):
    return f"KA{i % 100:02d}AB{1000 + i}"


def population(n, sites=None, **kw):
    return build([T(f"t{i}", sites(i) if sites else f"site{i}", _plate_text(i)) for i in range(n)], **kw)


def outputs_of(n, read):
    return {f"t{i}": read(i) for i in range(n)}


# ---------------------------------------------------------------------------------------------- baseline fixtures


def comp(digest, candidate_id, support, primary, second, third, contract_fail=False, kind="detector"):
    """Fixture only (private registry): a component score with chosen metrics on the partition ``digest``."""
    if not isinstance(digest, str):
        digest = digest.ab_digest
    return ev._register(ev._COMPONENT, ev.ComponentScore(candidate_id, support, primary, second, third,
                                                         contract_fail, _h(candidate_id), kind, digest, _h("m")))


def layer_a_for(corpus, passed=("PD2-N", "PD2-S"), metrics=None, identities=None):
    metrics = metrics or {"PD1-X": (0.99, 0.0, 0.99), "PD2-N": (0.95, 0.10, 0.90), "PD2-S": (0.93, 0.05, 0.92)}
    identities = identities or {}
    return [ev.LayerAResult(comp(corpus, d, 100, *metrics[d]), identities.get(d, _h(d)), d in passed)
            for d in DETECTORS]


def gate(corpus, composition, baseline, resolution=None):
    return ev.baseline_gate(corpus.full, composition, baseline, resolution or corpus.resolution, corpus.layer_a)


def stored(kind, result):
    return ev._lookup(kind, result, "fixture")


def relabel(score_, detector, recogniser):
    """Fixture only (private registry): a D score for a chosen composition (cheap gate fixtures)."""
    base = stored(ev._D, score_)
    return ev._register(ev._D, dataclasses.replace(base, detector=ident(detector), recogniser=ident(recogniser),
                                                   result_id=""))


def C(detector, recogniser, score_):
    try:
        score_ = relabel(score_, detector, recogniser)
    except ValueError:
        pass
    return ev.CompositionScore(score_)


def with_d(base, d, **changes):
    return ev._register(ev._D, dataclasses.replace(stored(ev._D, base), d_score=d, result_id="", **changes))


def compare(corpus, ra, rb, **overrides):
    arguments = dict(composition_a=(DET, REC), composition_b=(DET, REC), resolution=corpus.resolution,
                     layer_a_results=corpus.layer_a)
    arguments.update(overrides)
    return ev.paired_cluster_bootstrap(corpus.full, ra, rb, **arguments)
