"""The owner's five outstanding #218 points (2026-10-16) and the reconciliation with merged M3 (#220), attacked.

1. Freeze-record root of trust: what stops an edit-and-recommit of the committed record after the freeze.
2. Protected-D isolation: Layer A runs with no D index and no D truth present (file opens instrumented).
3. Reserved TEXT: exactly the repository's defined encodings; every earlier probe string classified.
4. M3 authority inputs: ``gates_passed`` / ``independent`` / ``d_rows_read`` / ``resolved_at_utc`` cannot open D or
   change scoring; D access fails closed on the not-yet-integrated authority.
5. Candidate execution in-process: capture on D evidence, then D truth, then no execution; nothing reachable from a
   candidate callable.

Synthetic data only. The protected-D authority is stubbed only inside ``fx.authorised()`` (see the fixtures module).
"""

from __future__ import annotations

import dataclasses
import inspect
import os
import shutil
import sys
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType

import pytest

from tools.benchmarks.capabilities.plates import evaluator as ev
from tools.benchmarks.capabilities.plates import selection_bundle as sb
from tools.benchmarks.capabilities.plates import selection_freeze as sf
from tools.benchmarks.tests import plate_selection_fixtures as fx
from tools.benchmarks.tests.plate_selection_fixtures import (
    DET,
    DETECTORS,
    EVENTS,
    GOOD_BOX,
    OC5,
    PD_BASE,
    REC,
    WHEN,
    Outputs,
    R,
    T,
    _h,
    _plate_text,
    build,
    comp,
    crop,
    images,
    layer_a_for,
    plate,
)
from tools.qualification.model_selection import baseline_seal, credibility, m3_authority, m3_universe

POLY = (((1, 1), (20, 1), (20, 10), (1, 10)),)


@pytest.fixture(autouse=True)
def _fresh():
    fx.fresh_process()
    yield
    fx.fresh_process()


# ---------------------------------------------------------------------------------------------- file-open instruments


class Opens:
    """Every path the interpreter opens, stats or lists while active (audit hook + ``os.stat``/``os.scandir``)."""

    active: list = []
    _installed = False

    def __init__(self):
        self.paths: list[str] = []

    @classmethod
    def _hook(cls, event, args):
        if cls.active and event in ("open", "os.listdir", "os.scandir") and args:
            target = args[0]
            if isinstance(target, (str, bytes, os.PathLike)):
                cls.active[-1].paths.append(os.fsdecode(target))

    def __enter__(self):
        if not Opens._installed:
            sys.addaudithook(Opens._hook)
            Opens._installed = True
        Opens.active.append(self)
        self._stat = os.stat

        def stat(path, *a, **kw):
            if isinstance(path, (str, bytes, os.PathLike)):
                self.paths.append(os.fsdecode(path))
            return self._stat(path, *a, **kw)

        os.stat = stat
        return self

    def __exit__(self, *exc):
        os.stat = self._stat
        Opens.active.remove(self)

    def touched(self, *names) -> list[str]:
        return [p for p in self.paths if any(Path(p).name == n for n in names)]


D_FILES = (sb.DOCUMENT_FILES["dIndex"], sb.DOCUMENT_FILES["dTruth"])


# ---------------------------------------------------------------------------------------------- point 1: root of trust


def _repo_with(record: bytes, name: str) -> Path:
    root = fx._ROOT / f"p1-{name}"
    if root.exists():
        shutil.rmtree(root)
    return fx.commit_record(record, f"p1-{name}")


def _good():
    corpus = fx.population(2)
    return corpus, (corpus.repo / sb.FREEZE_RECORD_PATH).read_bytes()


def _load(repo, corpus):
    return ev.load_selection_bundle(corpus.directory, repo_root=repo)


def _commit_file(repo: Path, data: bytes, message: str, path: str = sb.FREEZE_RECORD_PATH) -> None:
    fx.write(repo / path, data)
    fx.git(repo, "add", path)
    fx.git(repo, "commit", "-q", "-m", message)


def test_point1_the_committed_record_loads_and_names_its_first_add():
    corpus, record = _good()
    repo = _repo_with(record, "first-add")
    first = fx.git_out(repo, "rev-parse", "HEAD")
    _commit_file(repo, b"unrelated\n", "later work", "README.txt")
    bundle = _load(repo, corpus)
    assert bundle.freeze_commit == first != fx.git_out(repo, "rev-parse", "HEAD")
    assert bundle.record_sha256 == sb.document_sha256(record)


@pytest.mark.parametrize("attack", ["edit-recommit", "same-semantics-recommit", "delete-readd-same",
                                    "delete-readd-other", "merge-alters", "retype-symlink"])
def test_point1_rewriting_and_recommitting_the_record_is_refused(attack):
    """The attack the owner named: edit the committed record after the freeze and recommit it. Every variant that
    keeps history (edit, re-serialise, delete and re-add, alter on a branch and merge, retype) is refused, whatever
    the new content is (``freeze_record_not_add_only``)."""
    corpus, record = _good()
    repo = _repo_with(record, attack)
    edited = record.replace(b'"bootstrapSeed":7', b'"bootstrapSeed":8')
    if attack == "edit-recommit":
        _commit_file(repo, edited, "seed swap after the freeze")
    elif attack == "same-semantics-recommit":
        _commit_file(repo, record + b"\n", "whitespace")
        _commit_file(repo, record, "and back to the frozen bytes")
    elif attack == "delete-readd-same":
        fx.git(repo, "rm", "-q", sb.FREEZE_RECORD_PATH)
        fx.git(repo, "commit", "-q", "-m", "remove")
        _commit_file(repo, record, "re-add identical bytes")
    elif attack == "delete-readd-other":
        fx.git(repo, "rm", "-q", sb.FREEZE_RECORD_PATH)
        fx.git(repo, "commit", "-q", "-m", "remove")
        _commit_file(repo, edited, "re-add different bytes")
    elif attack == "merge-alters":
        fx.git(repo, "checkout", "-q", "-b", "side")
        _commit_file(repo, edited, "side edit")
        fx.git(repo, "checkout", "-q", "-")
        fx.git(repo, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    elif attack == "retype-symlink":
        fx.git(repo, "rm", "-q", "--cached", sb.FREEZE_RECORD_PATH)
        blob = fx.git_out(repo, "hash-object", "-w", "--stdin", input=b"selection-freeze-v1.json")
        fx.git(repo, "update-index", "--add", "--cacheinfo", f"120000,{blob},{sb.FREEZE_RECORD_PATH}")
        fx.git(repo, "commit", "-q", "-m", "retype")
        fx.git(repo, "rm", "-q", "--cached", sb.FREEZE_RECORD_PATH)
        _commit_file(repo, record, "back to a file")
    with pytest.raises(ValueError, match="freeze_record_not_add_only"):
        _load(repo, corpus)


def test_point1_uncommitted_hidden_or_redirected_records_are_refused_or_inert(monkeypatch):
    corpus, record = _good()
    repo = _repo_with(record, "hidden")
    path = repo / sb.FREEZE_RECORD_PATH
    edited = record.replace(b'"bootstrapSeed":7', b'"bootstrapSeed":8')
    path.write_bytes(edited)   # an uncommitted edit
    with pytest.raises(ValueError, match="freeze_record_differs_from_its_commit"):
        _load(repo, corpus)
    fx.git(repo, "update-index", "--skip-worktree", sb.FREEZE_RECORD_PATH)   # hide the edit from status
    with pytest.raises(ValueError, match="freeze_record_differs_from_its_commit"):
        _load(repo, corpus)
    fx.git(repo, "update-index", "--no-skip-worktree", sb.FREEZE_RECORD_PATH)
    path.write_bytes(record)
    # A replace object for the record blob, and an environment pointing Git at another repository holding another
    # record: both are ignored by M3's isolated profile, so the committed bytes stay the record.
    blob = fx.git_out(repo, "rev-parse", f"HEAD:{sb.FREEZE_RECORD_PATH}")
    other = fx.git_out(repo, "hash-object", "-w", "--stdin", input=edited)
    fx.git(repo, "replace", blob, other)
    assert _load(repo, corpus).record_sha256 == sb.document_sha256(record)
    decoy = _repo_with(edited, "decoy")
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(decoy))
    assert _load(repo, corpus).record_sha256 == sb.document_sha256(record)


def test_point1_an_incomplete_history_is_refused():
    corpus, record = _good()
    repo = _repo_with(record, "shallow-source")
    _commit_file(repo, b"one\n", "c2", "a.txt")
    _commit_file(repo, b"two\n", "c3", "a.txt")
    shallow = fx._ROOT / "p1-shallow"
    if shallow.exists():
        shutil.rmtree(shallow)
    fx.git(fx._ROOT, "clone", "-q", "--depth", "1", f"file://{repo.as_posix()}", str(shallow))
    with pytest.raises(ValueError, match="freeze_record_history_incomplete:shallow"):
        _load(shallow, corpus)


def test_point1_residual_a_history_rewrite_is_a_new_identity_and_frozen_results_do_not_transfer():
    """What a local check cannot stop: rewriting history itself (amend). The rewritten record is a DIFFERENT identity
    (record SHA-256, partition digests, freeze commit), so nothing frozen under the original carries over. Pinning the
    record SHA-256 in both M3 frozen ledgers on the protected default branch is the integration PR (§6)."""
    corpus, record = _good()
    repo = _repo_with(record, "rewrite")
    original = _load(repo, corpus)
    rewritten = sb.canonical_bytes({**sb.parse_canonical(record, "r"),
                                    "protocol": {**sb.parse_canonical(record, "r")["protocol"], "bootstrapSeed": 8}})
    fx.write(repo / sb.FREEZE_RECORD_PATH, rewritten)
    fx.git(repo, "add", sb.FREEZE_RECORD_PATH)
    fx.git(repo, "commit", "-q", "--amend", "-m", "freeze (rewritten)")
    fx.git(repo, "reflog", "expire", "--expire=now", "--all")
    fx.git(repo, "gc", "-q", "--prune=now")
    again = _load(repo, corpus)
    assert again.record_sha256 != original.record_sha256 and again.freeze_commit != original.freeze_commit
    assert (again.ab_digest, again.d_digest) != (original.ab_digest, original.d_digest)
    with pytest.raises(ev.BaselineStop, match="of_another_freeze"):
        ev.verify_resolution(again, corpus.resolution, corpus.layer_a)


# ---------------------------------------------------------------------------------------------- point 2: isolation


def _ab_corpus():
    tracks = [T(f"a{i}", f"a-site{i}", _plate_text(i)) for i in range(3)]
    crops = [crop(f"c{i}", f"a{i}", 0, POLY) for i in range(3)]
    plates = [plate(f"p{i}", f"a{i}", b=i) for i in range(3)]
    return build(tracks, crops=crops, plates=plates, twin=[T("d0", "d-site", "KA77QQ7777")])


def _without_d(corpus, name, how):
    directory = fx._ROOT / f"p2-{name}"
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    for key in ("abIndex", "abTruth"):
        shutil.copyfile(corpus.directory / sb.DOCUMENT_FILES[key], directory / sb.DOCUMENT_FILES[key])
    if how == "unreadable":   # a directory under each D file name: any attempt to read it fails
        for name_ in D_FILES:
            (directory / name_).mkdir()
    return directory


def _layer_a_path(corpus, directory):
    """The whole Layer-A path: selection load, every detector on every crop, A, components, top-K, the Layer-A
    artefact and the Stage-2 resolution; plus B on the GT plate crops."""
    bundle = ev.load_selection_bundle(directory, repo_root=corpus.repo)
    scores = []
    behaviour = {"PD1-X": fx.Detector([fx.PlateBox(1, 1, 20, 10, 0.9)]),                       # the best detector
                 "PD2-N": fx.Detector([fx.PlateBox(1, 1, 20, 10, 0.9), fx.PlateBox(30, 1, 20, 10, 0.8)]),
                 "PD2-S": fx.Detector([])}
    for d in DETECTORS:
        who = fx.ident(d)
        runs = [ev.run_detection(bundle, c["cropId"], detector=behaviour[d], detector_identity=who, images=images)
                for c in corpus.docs["abTruth"]["crops"]]
        scores.append(ev.detector_component(ev.evaluate_a(bundle, runs, detector=who)))
    reads = [ev.run_reading(bundle, f"p{i}", recogniser=Outputs([R((_plate_text(i), 0.9))]), recogniser_identity=REC,
                            images=images) for i in range(3)]
    b = ev.evaluate_b(bundle, reads, recogniser=REC)
    top = ev.top_k(bundle, scores, "detector")
    layer_a = [ev.LayerAResult(s, s.identity_sha256, True) for s in scores]
    document = ev.layer_a_result_document(bundle, layer_a)
    resolution = ev.resolve_baseline(bundle, layer_a, d_rows_read=0, resolved_at_utc=WHEN)
    return bundle, b, top, document, resolution, layer_a


@pytest.mark.parametrize("how", ["absent", "unreadable"])
def test_point2_layer_a_runs_with_no_d_index_and_no_d_truth_present(how):
    corpus = _ab_corpus()
    directory = _without_d(corpus, how, how)
    with Opens() as opened:
        bundle, b, top, document, resolution, layer_a = _layer_a_path(corpus, directory)
    assert opened.touched(*D_FILES) == []                       # no D path was opened, stat-ed or listed
    assert opened.touched(sb.DOCUMENT_FILES["abIndex"]) and opened.touched(sb.DOCUMENT_FILES["abTruth"])
    assert bundle.stage == sb.SELECTION and b.outcome == ev.MEASURED and top == []   # support 3 < the floor 50
    assert document["evidenceSha256"] == bundle.ab_digest and resolution.d_state == ev.D_NOT_STARTED
    assert not sb.d_data_loaded(bundle.record_sha256)
    state = sb._state_of(bundle)
    assert not state.d.index_loaded and not state.d.tracks and bundle.d_digest == corpus.d_digest
    with pytest.raises(ValueError, match="layer_d_requires_a_protected_d_stage"):
        ev.layer_digest(bundle, "D")
    # The D stages need the files the record names: absent or unreadable, they refuse (after the authority).
    with pytest.raises(ValueError, match="corpus_document_absent:dIndex"):
        fx.d_load(ev.load_d_capture_bundle, directory, corpus.repo, resolution, layer_a)


def test_point2_disjointness_is_established_at_freeze_construction_and_recorded():
    corpus = _ab_corpus()
    record = sb.parse_canonical((corpus.repo / sb.FREEZE_RECORD_PATH).read_bytes(), "r")
    assert record["disjointness"] == sb.disjointness_attestation(record["documents"])
    assert record["disjointness"]["result"] == sb.DISJOINT
    assert record["disjointness"]["checks"] == list(sb.DISJOINTNESS_CHECKS)
    assert sf.construct_freeze_record(corpus.directory, protocol=record["protocol"], roster=record["roster"],
                                      partition_plan=record["partitionPlan"]) == sb.canonical_bytes(record)
    assert sb.protected_truth_resident()   # the tool read D truth: this process may no longer execute candidates
    with pytest.raises(ValueError, match="candidate_execution_after_protected_d_truth_loaded"):
        ev.run_detection(corpus.sel, "c0", detector=GOOD_BOX, detector_identity=DET, images=images)


@pytest.mark.parametrize("key", ["dIndex", "dTruth"])
def test_point2_wrong_or_missing_protected_d_freeze_inputs_are_refused(key):
    corpus = fx.population(2)
    directory = fx._ROOT / f"p2-wrong-{key}"
    if directory.exists():
        shutil.rmtree(directory)
    shutil.copytree(corpus.directory, directory)
    target = directory / sb.DOCUMENT_FILES[key]
    target.write_bytes(target.read_bytes().replace(b"KA00AB1000", b"KA00AB1001").replace(b'"rank":0', b'"rank":1'))
    loader = ev.load_d_capture_bundle if key == "dIndex" else ev.load_protected_d_bundle
    with pytest.raises(ValueError, match=f"corpus_document_not_the_frozen_document:{key}"):
        fx.d_load(loader, directory, corpus.repo, corpus.resolution, corpus.layer_a)
    target.unlink()
    with pytest.raises(ValueError, match=f"corpus_document_absent:{key}"):
        fx.d_load(loader, directory, corpus.repo, corpus.resolution, corpus.layer_a)


# ---------------------------------------------------------------------------------------------- point 3: reserved TEXT

# Every string of the earlier probe sets (cold218f probe1/4, cold218g probe a, cold218d probe 2) and the defined
# sentinels. TEXT = v1 + letter + digit; UNSUPPORTED = retained; RESERVED = refused as malformed input.
PROBE_TABLE = {
    "UNREADBLE": "UNSUPPORTED", "UNREADABL": "UNSUPPORTED", "NOPLAT": "UNSUPPORTED", "NO_PLAT": "UNSUPPORTED",
    "NO-GT": "UNSUPPORTED", "NOGTVEHICLE1": "TEXT", "N/A": "UNSUPPORTED", "NA": "UNSUPPORTED",
    "NONE": "UNSUPPORTED", "NULL": "UNSUPPORTED", "UNKNOWN": "UNSUPPORTED", "ILLEGIBLE": "UNSUPPORTED",
    "<UNREADBLE": "UNSUPPORTED", "[UNREADABLE]": "UNSUPPORTED", "{NO_PLATE}": "UNSUPPORTED",
    "UNREADABLE.": "UNSUPPORTED", "UNREAD": "UNSUPPORTED", "NOPLATE0": "TEXT", "TEXT": "RESERVED",
    "1234": "UNSUPPORTED", "123456": "UNSUPPORTED", "ABCD": "UNSUPPORTED", "KA01AB1234": "TEXT",
    "<NO-PLATE>": "RESERVED", "<no-plate>": "RESERVED", "<unreadable>": "RESERVED", "<no-gt-vehicle>": "RESERVED",
    "NO_PLATE": "RESERVED", "No Plate": "RESERVED", "unreadable": "RESERVED", "NO_GT_VEHICLE": "RESERVED",
    "UNSUPPORTED_TEXT": "RESERVED",
}


def test_point3_every_probe_string_is_classified_by_the_defined_encodings_only():
    for text, expected in PROBE_TABLE.items():
        if expected == "RESERVED":
            with pytest.raises(ValueError, match="reserved_syntax"):
                ev.classify_truth("TEXT", text)
            continue
        state, raw, supported = ev.classify_truth("TEXT", text)
        assert raw == text and state is (ev.TruthState.TEXT if expected == "TEXT" else ev.TruthState.UNSUPPORTED_TEXT)
        assert (supported is None) == (expected != "TEXT")


# ---------------------------------------------------------------------------------------------- point 4: authority


@pytest.mark.parametrize("authorization", [None, True, "authorised", fx.TEST_AUTHORITY, "group-id",
                                           m3_authority.DAuthorization("0" * 64, "0" * 40, (), "0" * 64,
                                                                       "msr-ocr-2026-01")])
def test_point4_no_value_opens_protected_d_without_the_integrated_authority(authorization):
    """D access is gated on the integration capability, which does not exist in #218 and so fails closed — for every
    value, including a hand-built M3 ``DAuthorization`` (a plain dataclass) and the test object outside the stub.
    Nothing of D is opened."""
    corpus = fx.population(2)
    with Opens() as opened:
        for loader in (ev.load_d_capture_bundle, ev.load_protected_d_bundle):
            with pytest.raises(ValueError, match="protected_d_not_authorised:m3_authority_not_integrated"):
                loader(corpus.directory, resolution=corpus.resolution, layer_a_results=corpus.layer_a,
                       authorization=authorization, repo_root=corpus.repo)
    assert opened.touched(*D_FILES) == [] and not sb.d_data_loaded(corpus.sel.record_sha256)


def test_point4_gates_passed_true_without_evidence_cannot_open_d_or_change_scoring():
    corpus = fx.population(2)
    forged = layer_a_for(corpus, passed=("PD1-X", "PD2-N", "PD2-S"))   # PD1-X "passes" with no evidence
    forged_resolution = ev.resolve_baseline(corpus.sel, forged, d_rows_read=0, resolved_at_utc=WHEN)
    assert forged_resolution.pd_base_id == "PD1-X" != corpus.resolution.pd_base_id   # a different harness record
    with Opens() as opened, pytest.raises(ValueError, match="m3_authority_not_integrated"):
        ev.load_d_capture_bundle(corpus.directory, resolution=forged_resolution, layer_a_results=forged,
                                 authorization=fx.TEST_AUTHORITY, repo_root=corpus.repo)
    assert opened.touched(*D_FILES) == []
    # Even where a (test-stubbed) authority admits D, the frozen gate binds the harness's OWN resolution: scores of the
    # forged derivation are refused under the genuine one and vice versa (no mixing).
    runs = fx.runs_for(corpus, fx.outputs_of(2, lambda i: [_plate_text(i)]))
    base = fx.score(corpus, runs)
    with pytest.raises(ev.BaselineStop, match="differs_from_frozen_derivation"):
        ev.baseline_gate(corpus.full, fx.C("PD2-S", "OC1-XS", base), fx.C("PD2-N", "OC5-BEST", base),
                         corpus.resolution, forged)


def test_point4_independence_is_the_frozen_records_verdict_only():
    corpus = fx.population(1, roster=fx.default_roster(dependent=("PD2-S",)), resolve=False)
    scores = [comp(corpus, d, 100, 0.99 - i / 100, 0.0, 0.9) for i, d in enumerate(DETECTORS)]
    assert ev.top_k(corpus.sel, scores, "detector") == ["PD1-X", "PD2-N"]   # PD2-S declared not independent
    plain = fx.population(1, resolve=False)
    assert ev.top_k(plain.sel, [comp(plain, d, 100, 0.99 - i / 100, 0.0, 0.9) for i, d in enumerate(DETECTORS)],
                    "detector") == list(DETECTORS)
    for name in ("detector_component", "recogniser_component", "top_k", "resolve_baseline"):
        assert "independent" not in inspect.signature(getattr(ev, name)).parameters
    assert "independent" not in {f.name for f in dataclasses.fields(ev.ComponentScore)}
    state = sb._state_of(corpus.sel)
    assert isinstance(state.roster.independent, MappingProxyType)
    with pytest.raises(TypeError):
        state.roster.independent["PD2-S"] = True   # harness state is immutable


def test_point4_d_rows_read_and_resolved_at_utc_are_reporting_only():
    corpus = fx.build([T("r0", "r-site", _plate_text(0))], resolve=False)
    layer_a = layer_a_for(corpus)
    one = ev.resolve_baseline(corpus.sel, layer_a, d_rows_read=0, resolved_at_utc=WHEN)
    two = ev.resolve_baseline(corpus.sel, layer_a, d_rows_read=0, resolved_at_utc="2026-12-31T23:59:59Z")
    same = ("pd_base_id", "pd_base_identity_sha256", "composition_sha256", "layer_a_result_sha256",
            "freeze_sha256", "ranking_rule_sha256", "d_state")
    assert all(getattr(one, f) == getattr(two, f) for f in same) and one.record_sha256 != two.record_sha256
    for claim in (1, -1, True, 0.0):   # a claim can only STOP
        with pytest.raises(ev.BaselineStop, match="after_d_data_read"):
            ev.resolve_baseline(corpus.sel, layer_a, d_rows_read=claim, resolved_at_utc=WHEN)
    # Claiming 0 rows after D was actually opened is refused on the harness's own fact.
    fx.d_load(ev.load_d_capture_bundle, corpus.directory, corpus.repo, one, layer_a)
    with pytest.raises(ev.BaselineStop, match="after_d_data_loaded"):
        ev.resolve_baseline(corpus.sel, layer_a, d_rows_read=0, resolved_at_utc=WHEN)
    # Both resolutions gate identically (the time is only recorded).
    full = fx.d_load(ev.load_protected_d_bundle, corpus.directory, corpus.repo, one, layer_a)
    fx.new_process()
    runs = [ev.run_track(fx.d_load(ev.load_d_capture_bundle, corpus.directory, corpus.repo, one, layer_a), "r0",
                         detector=GOOD_BOX, recogniser=fx.Recogniser([_plate_text(0)]), detector_identity=DET,
                         recogniser_identity=REC, images=images)]
    base_runs = [ev.run_track(fx.d_load(ev.load_d_capture_bundle, corpus.directory, corpus.repo, one, layer_a), "r0",
                              detector=GOOD_BOX, recogniser=fx.Recogniser([""]), detector_identity=PD_BASE,
                              recogniser_identity=OC5, images=images)]
    candidate = ev.CompositionScore(ev.evaluate_d(full, runs, composition=(DET, REC)))
    baseline = ev.CompositionScore(ev.evaluate_d(full, base_runs, composition=(PD_BASE, OC5)))
    assert ev.baseline_gate(full, candidate, baseline, one, layer_a) == \
        ev.baseline_gate(full, candidate, baseline, two, layer_a) == ev.PASS


# ---------------------------------------------------------------------------------------------- point 5: ordering


def _ordered_corpus():
    return fx.build([T(f"o{i}", f"o-site{i}", f"ZQ{i}9XY{7000 + i}") for i in range(3)],
                    crops=[], plates=[], partition=fx.D, twin=[T("oab", "oab-site", "KA55AB5555")])


def test_point5_capture_then_truth_then_no_candidate_execution():
    corpus = _ordered_corpus()
    capture = fx.d_load(ev.load_d_capture_bundle, corpus.directory, corpus.repo, corpus.resolution, corpus.layer_a)
    with Opens() as opened:
        runs = [ev.run_track(capture, f"o{i}", detector=GOOD_BOX, recogniser=fx.Recogniser([f"ZQ{i}9XY{7000 + i}"]),
                             detector_identity=DET, recogniser_identity=REC, images=images) for i in range(3)]
    assert opened.touched(sb.DOCUMENT_FILES["dTruth"]) == []   # execution never touches the D truth
    state = sb._state_of(capture)
    assert all(t.state is None and t.text is None for t in state.d.tracks.values()) and not state.d.truth_loaded
    with pytest.raises(ValueError, match="requires_the_protected_d_bundle"):
        ev.evaluate_d(capture, runs, composition=(DET, REC))   # no scoring without the truth stage
    full = fx.d_load(ev.load_protected_d_bundle, corpus.directory, corpus.repo, corpus.resolution, corpus.layer_a)
    assert sb.protected_truth_resident()
    for attempt in (
            lambda: ev.run_track(capture, "o0", detector=GOOD_BOX, recogniser=fx.Recogniser(["x"]),
                                 detector_identity=DET, recogniser_identity=REC, images=images),
            lambda: ev.run_track(corpus.sel, "oab", detector=GOOD_BOX, recogniser=fx.Recogniser(["x"]),
                                 detector_identity=DET, recogniser_identity=REC, images=images),
            lambda: ev.run_reading(corpus.sel, "none", recogniser=Outputs([[]]), recogniser_identity=REC,
                                   images=images),
            lambda: ev.run_detection(corpus.sel, "none", detector=GOOD_BOX, detector_identity=DET, images=images)):
        with pytest.raises(ValueError, match="candidate_execution_after_protected_d_truth_loaded"):
            attempt()
    assert ev.evaluate_d(full, runs, composition=(DET, REC)).d_score == 1   # outputs captured before the truth


def test_point5_d_truth_is_unreachable_from_inside_a_candidate_callable():
    # Truth texts that no candidate in this test session ever outputs (candidate outputs are legitimately recorded).
    truths = {f"WV{i}8RS{6100 + i}" for i in range(3)}
    corpus = fx.build([T(f"w{i}", f"w-site{i}", text) for i, text in enumerate(sorted(truths))],
                      partition=fx.D, twin=[T("wab", "wab-site", "KA56AB5656")])
    capture = fx.d_load(ev.load_d_capture_bundle, corpus.directory, corpus.repo, corpus.resolution, corpus.layer_a)
    seen = {}

    class Snooper:
        def detect(self, crop_image, verified):
            seen["strings"] = _harness_strings()
            seen["d_tracks"] = [t for s in sb._BUNDLES.values() for t in s.d.tracks.values()
                                if t.state is not None or t.text is not None]
            seen["resident"] = sb.protected_truth_resident()
            for loader in (ev.load_protected_d_bundle, ev.load_d_capture_bundle):
                try:
                    with fx.authorised():
                        loader(corpus.directory, resolution=corpus.resolution, layer_a_results=corpus.layer_a,
                               authorization=fx.TEST_AUTHORITY, repo_root=corpus.repo)
                    seen.setdefault("loaded", []).append(loader.__name__)
                except ValueError as exc:
                    seen.setdefault("refused", []).append(str(exc))
            return GOOD_BOX.detect(crop_image, verified)

    with Opens() as opened:
        result = ev.run_track(capture, "w0", detector=Snooper(), recogniser=fx.Recogniser(["x"]),
                              detector_identity=DET, recogniser_identity=REC, images=images)
    assert result.state == ev.COMPLETED
    assert not truths & seen["strings"]          # no D truth text anywhere in the harness module registries
    assert seen["d_tracks"] == [] and seen["resident"] is False
    assert seen["refused"][0] == "protected_d_truth_load_during_candidate_execution"
    assert opened.touched(sb.DOCUMENT_FILES["dTruth"]) == []
    assert not sb.d_truth_loaded(capture.record_sha256)


def _harness_strings() -> set[str]:
    """Every string reachable (depth-bounded) from the globals of the harness, M3 and PR-3 modules."""
    found: set[str] = set()
    seen: set[int] = set()

    def walk(value, depth):
        if depth > 8 or id(value) in seen:
            return
        seen.add(id(value))
        if isinstance(value, str):
            found.add(value)
        elif isinstance(value, (dict, MappingProxyType)):
            for k, v in value.items():
                walk(k, depth + 1)
                walk(v, depth + 1)
        elif isinstance(value, (list, tuple, set, frozenset)):
            for v in value:
                walk(v, depth + 1)
        elif dataclasses.is_dataclass(value) and not isinstance(value, type):
            for f in dataclasses.fields(value):
                walk(getattr(value, f.name, None), depth + 1)

    for name, module in list(sys.modules.items()):
        if module is None or not name.startswith(("tools.benchmarks.capabilities", "tools.qualification",
                                                  "mavi_vision", "model_selection")):
            continue
        for value in list(vars(module).values()):
            walk(value, 0)
    return found


# ---------------------------------------------------------------------------------------------- M3 reconciliation


def test_m3_identifier_and_canonical_forms_are_m3s():
    assert sb._CANDIDATE_RE.pattern == credibility.CANDIDATE_ID_RE.pattern
    assert sb._EVENT_RE.pattern == credibility.EVENT_ID_RE.pattern
    assert sb._COMPOSITION_RE.pattern == credibility.LOCAL_ID_RE.pattern
    assert sb._UTC_RE.pattern == credibility.UTC_INSTANT_RE.pattern
    sample = {"b": [1, 2.5, "xé"], "a": None}
    assert sb.canonical_bytes(sample) == credibility.canonical_json(sample)
    assert sb.M3_ORDINARY_COMPOSITION_PREFIX == baseline_seal.ORDINARY_ID_PREFIX
    assert ev.MPID == Fraction(Decimal("0.04"))   # M3 compares Decimal(str(json number)); 0.04 is exact in both


def test_m3_gate_only_composition_hash_is_m3s():
    pd = fx.ident("PD2-N")
    assert ev.m3_composition_sha256(EVENTS[0], EVENTS[1], OC5, EVENTS[2], pd) == baseline_seal.composition_sha256(
        EVENTS[0], EVENTS[1], OC5.candidate_id, OC5.identity_sha256, EVENTS[2], pd.candidate_id, pd.identity_sha256)


M3_DETECTOR_RULE = {"rule": m3_universe.RANKING_RULE, "keys": [{"metric": "recallAtCoverage", "direction": "max"},
                                                              {"metric": "falsePlatesPerCrop", "direction": "min"},
                                                              {"metric": "ap50", "direction": "max"}]}


def _m3_ranking(scores, independent):
    """The M3 ``check_component_ranking`` result shape built from harness component scores: the rank key from the
    frozen ``lexicographic-v1`` rule, passed = every harness eligibility condition (the integration PR maps them to
    ranking gates)."""
    return {s.candidate_id: {"key": m3_universe.rank_key({"recallAtCoverage": s.primary, "falsePlatesPerCrop": s.second,
                                                          "ap50": s.third}, M3_DETECTOR_RULE),
                             "passed": independent[s.candidate_id] and not s.contract_fail and s.support >= 50}
            for s in (fx.stored(ev._COMPONENT, x) for x in scores)}


def test_m3_component_ranking_top_k_and_pd_base_agree_without_ties():
    corpus = fx.population(1, resolve=False)
    metrics = {"PD1-X": (0.97, 0.10, 0.90), "PD2-N": (0.97, 0.05, 0.80), "PD2-S": (0.99, 0.30, 0.10)}
    scores = [comp(corpus, d, 100, *metrics[d]) for d in DETECTORS]
    ranking = _m3_ranking(scores, sb._state_of(corpus.sel).roster.independent)
    assert ev.top_k(corpus.sel, scores, "detector") == m3_universe.derive_top_k(ranking, 2) + ["PD1-X"] == \
        ["PD2-S", "PD2-N", "PD1-X"]
    layer_a = [ev.LayerAResult(s, fx._h(s.candidate_id), True) for s in scores]
    resolution = ev.resolve_baseline(corpus.sel, layer_a, d_rows_read=0, resolved_at_utc=WHEN)
    assert resolution.pd_base_id == m3_universe.best_partner(ranking, set(DETECTORS)) == "PD2-S"


def test_m3_ambiguity_stops_in_both_and_the_top_k_boundary_tie_is_a_recorded_difference():
    corpus = fx.population(1, resolve=False)
    tied = [comp(corpus, d, 100, 0.9, 0.1, 0.9) for d in DETECTORS]
    ranking = _m3_ranking(tied, sb._state_of(corpus.sel).roster.independent)
    with pytest.raises(ev.BaselineStop, match="layer_a_rank_ambiguous"):
        ev.resolve_baseline(corpus.sel, [ev.LayerAResult(s, fx._h(s.candidate_id), True) for s in tied],
                            d_rows_read=0, resolved_at_utc=WHEN)
    with pytest.raises(credibility.CredibilityError, match="partner_rank_ambiguous"):
        m3_universe.best_partner(ranking, set(DETECTORS))
    # Recorded difference (decision record §6, D.6 item 7): a tie ACROSS the K boundary. M3 (owner O3) stops; the
    # harness top-K cuts it by lexical id (N4 as implemented). The integration PR makes M3's derived top-K
    # authoritative; the owner question is recorded there. This test pins today's behaviour of both on purpose.
    four = ("PD1-X", "PD2-N", "PD2-S", "PD3-Z")
    wide = fx.population(1, roster=fx.default_roster(four), resolve=False,
                         mutate_record=lambda r: r["protocol"].update(detectorFloors=[[d, fx.FLOOR] for d in four]))
    tied4 = [comp(wide, d, 100, 0.9, 0.1, 0.9) for d in four]
    with pytest.raises(credibility.CredibilityError, match="component_rank_ambiguous"):
        m3_universe.derive_top_k(_m3_ranking(tied4, sb._state_of(wide.sel).roster.independent), ev.TOP_K)
    assert ev.top_k(wide.sel, tied4, "detector") == ["PD1-X", "PD2-N", "PD2-S"]


def test_m3_exact_mpid_boundary_differs_through_json_floats():
    """Recorded difference (decision record §6, D.6 item 8): the harness compares MPID exactly on rational D-scores
    (owner D7a); M3 recomputes the baseline gate from JSON-number ``dScore`` values (``Decimal(str(float))``). At the
    exact boundary they disagree, so the integration must carry exact D-scores (owner question)."""
    corpus = fx.population(1)
    base = fx.score(corpus, fx.runs_for(corpus, fx.outputs_of(1, lambda i: [_plate_text(i)])))
    candidate, baseline = Fraction(131, 150), Fraction(5, 6)
    assert candidate - baseline == ev.MPID
    assert fx.gate(corpus, fx.C("PD2-S", "OC1-XS", fx.with_d(base, candidate)),
                   fx.C("PD2-N", "OC5-BEST", fx.with_d(base, baseline))) == ev.PASS
    m3_mpid = m3_authority._exact(0.04)
    assert m3_authority._exact(float(candidate)) - m3_authority._exact(float(baseline)) < m3_mpid   # M3: FAIL


# ---------------------------------------------------------------------------------------------- cold review 5735c63c


class _Meta(type):
    @property
    def __name__(cls):   # a metaclass that makes the class name itself hostile
        raise RuntimeError("no name")


class _Unprintable:
    def __str__(self):
        raise RuntimeError("no text")


class EvilStr(Exception):
    def __str__(self):
        raise RuntimeError("no message")


class NonStr(Exception):
    def __str__(self):
        return 5   # noqa: PLE0307 - deliberately not a str


class EvilRepr(Exception):
    def __repr__(self):
        raise RuntimeError("no repr")

    def __str__(self):
        raise RuntimeError("no message")


class EvilName(Exception, metaclass=_Meta):
    pass


class Odd(BaseException):   # not an Exception: passes straight through PR-3's ``except Exception`` handlers
    pass


RAISES = {"evil __str__": lambda: EvilStr(), "__str__ returns non-str": lambda: NonStr(),
          "evil __repr__": lambda: EvilRepr(), "evil class name (metaclass)": lambda: EvilName("x"),
          "evil argument": lambda: ValueError(_Unprintable()), "BaseException subclass": lambda: Odd("x"),
          "GeneratorExit": lambda: GeneratorExit()}


class _RaisingDetector:
    def __init__(self, make):
        self.make = make

    def detect(self, crop_image, verified):
        raise self.make()


class _RaisingRecogniser:
    def __init__(self, make):
        self.make = make

    def read(self, region, verified, box):
        raise self.make()


def _exception_corpus():
    return fx.build([T("x0", "x-site", "KA01AB1234")], [crop("cx", "x0", 0, POLY)], [plate("px", "x0", b=7)],
                    twin=[T("xd", "xd-site", "KA02AB1234")])


def _paths(corpus, make):
    """Every envelope with the raising detector and with the raising recogniser: A, B, C and D."""
    cap = corpus.capture
    yield "A detector", lambda: ev.run_detection(corpus.sel, "cx", detector=_RaisingDetector(make),
                                                 detector_identity=DET, images=images)
    yield "B recogniser", lambda: ev.run_reading(corpus.sel, "px", recogniser=_RaisingRecogniser(make),
                                                 recogniser_identity=REC, images=images)
    for layer, bundle, tid in (("C", corpus.sel, "x0"), ("D", cap, "xd")):
        yield f"{layer} detector", lambda b=bundle, t=tid: ev.run_track(
            b, t, detector=_RaisingDetector(make), recogniser=fx.Recogniser(["KA01AB1234"]), detector_identity=DET,
            recogniser_identity=REC, images=images)
        yield f"{layer} recogniser", lambda b=bundle, t=tid: ev.run_track(
            b, t, detector=GOOD_BOX, recogniser=_RaisingRecogniser(make), detector_identity=DET,
            recogniser_identity=REC, images=images)


@pytest.mark.parametrize("kind", sorted(RAISES))
def test_cold_p2_1_any_candidate_exception_is_contract_fail_never_completed(kind):
    """P2-1 (cold review of 5735c63c): a candidate exception whose text, repr, class name or base class is hostile was
    abstained by PR-3 and recorded COMPLETED. The guard is now flagged first by a formatter that cannot fail."""
    corpus = _exception_corpus()
    for name, call in _paths(corpus, RAISES[kind]):
        result = call()
        assert result.state == ev.CONTRACT_FAIL, (kind, name)
        assert "runtime_error" in result.contract_violation and type(result.contract_violation) is str, (kind, name)


@pytest.mark.parametrize("abort", [KeyboardInterrupt, SystemExit])
def test_cold_p2_1_interrupts_are_recorded_contract_fail_and_re_raised(abort):
    corpus = _exception_corpus()
    for name, call in _paths(corpus, abort):
        with pytest.raises(abort):
            call()
        kind, record = list(ev._RESULTS.values())[-1]
        assert record.state == ev.CONTRACT_FAIL and "runtime_error" in record.contract_violation, name
    assert sb._CANDIDATE_ACTIVE[0] == 0


def test_cold_p2_1_the_formatter_cannot_fail():
    for make in RAISES.values():
        text = ev._exception_evidence(make())
        assert type(text) is str and ":" in text
    # The message is BaseException's own rendering of ``args``; the candidate's ``__str__`` is never called.
    assert ev._exception_evidence(EvilStr("m")) == "EvilStr:m" and ev._exception_evidence(NonStr()) == "NonStr:"
    assert ev._exception_evidence(ValueError(_Unprintable())) == "ValueError:<unprintable>"
    assert ev._exception_evidence(EvilName("x")) == "EvilName:x"   # the slot, not the metaclass property


def test_cold_p3_1_the_private_loader_cannot_skip_the_authority():
    """P3-1: ``_load`` took an injectable precondition that could open D truth; the authority is now unconditional."""
    corpus = fx.population(2)
    with Opens() as opened:
        for stage in (sb.D_CAPTURE, sb.PROTECTED):
            with pytest.raises(ValueError, match="m3_authority_not_integrated"):
                sb._load(corpus.directory, corpus.repo, stage, lambda s: None)
            with pytest.raises(ValueError, match="m3_authority_not_integrated"):
                sb._load(corpus.directory, corpus.repo, stage, lambda s: None, fx.TEST_AUTHORITY)
            with pytest.raises(ValueError, match="no_stage_2_resolution"):
                sb._load(corpus.directory, corpus.repo, stage)
    assert opened.touched(*D_FILES) == [] and not sb.d_data_loaded(corpus.sel.record_sha256)


@pytest.mark.parametrize("mutate, code", [
    (lambda d: d["abTruth"]["crops"][0].update(trackId=["x0"]), "truth_crop_malformed"),
    (lambda d: d["abTruth"]["crops"][0].update(observationId={"o": 1}), "truth_crop_malformed"),
    (lambda d: d["abTruth"]["crops"][0].update(observationId=7), "truth_crop_malformed"),
    (lambda d: d["abTruth"]["plates"][0].update(trackId=["x0"]), "truth_plate_malformed"),
    (lambda d: d["abTruth"]["plates"][0].update(observationId=["o"]), "truth_plate_malformed"),
])
def test_cold_p3_4_wrong_typed_document_fields_are_typed_refusals(mutate, code):
    with pytest.raises(ValueError, match=code):
        fx.build([T("x0", "x-site", "KA01AB1234")], [crop("cx", "x0", 0, POLY)], [plate("px", "x0", b=7, c=0)],
                 twin=[T("xd", "xd-site", "KA02AB1234")], mutate=mutate)
