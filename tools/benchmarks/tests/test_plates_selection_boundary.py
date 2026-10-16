"""The #218 trust boundary, attacked (owner instruction 2026-10-14).

Governing invariant: for fixed frozen canonical protocol/corpus bytes and fixed candidate outputs, no caller-controlled
object, subclass, property, method, iterable, parser ambiguity, configuration value, ordering, seed, partition
representation or mutable state may alter population membership, eligibility, evidence, partition assignment,
candidate eligibility or any A/B/C/D result.

Each test reproduces a previously successful #218 attack (probe sets cold218, cold218b, cold218d, cold218e, cold218f,
cold218g) or a new attack class, and shows one of:
  (i)  the supported API cannot express it; or
  (ii) the frozen identity changes, or the input is refused.
Attacks on a caller's COPY of a harness result are shown to be inert (the harness scores its own record), which is
outcome (i): a copy is never an input.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
from fractions import Fraction

import pytest

from mavi_vision.plates.inference import PlateBox, Reading
from tools.benchmarks.capabilities.plates import evaluator as ev
from tools.benchmarks.capabilities.plates import selection_bundle as sb
from tools.benchmarks.tests import plate_selection_fixtures as fx
from tools.benchmarks.tests.plate_selection_fixtures import (
    DET,
    GOOD_BOX,
    OC5,
    PD_BASE,
    REC,
    WHEN,
    C,
    Outputs,
    R,
    T,
    _h,
    _plate_text,
    build,
    comp,
    compare,
    crop,
    default_protocol,
    default_roster,
    gate,
    ident,
    images,
    layer_a_for,
    outputs_of,
    plate,
    population,
    run,
    runs_for,
    score,
    stored,
)

POLY = (((1, 1), (20, 1), (20, 10), (1, 10)),)


def _ab(*tracks, crops=None, **kw):
    """An A/B-partition corpus with one crop per Track (its first evidence image)."""
    crops = crops if crops is not None else [crop(f"c-{t.track_id}", t.track_id, 0, POLY) for t in tracks]
    return build(list(tracks), crops, **kw)


def _raw_load(record_bytes, docs_bytes, name, stage=sb.SELECTION):
    repo = fx.commit_record(record_bytes, name)
    directory = fx._ROOT / f"{name}-corpus"
    for key, data in docs_bytes.items():
        fx.write(directory / sb.DOCUMENT_FILES[key], data)
    selection = ev.load_selection_bundle(directory, repo_root=repo)
    if stage == sb.SELECTION:
        return selection
    layer_a = [ev.LayerAResult(comp(selection.ab_digest, d, 100, *m), _h(d), d != "PD1-X")
               for d, m in zip(fx.DETECTORS, ((0.99, 0.0, 0.99), (0.95, 0.1, 0.9), (0.93, 0.05, 0.92)))]
    resolution = ev.resolve_baseline(selection, layer_a, d_rows_read=0, resolved_at_utc=WHEN)
    loader = ev.load_d_capture_bundle if stage == sb.D_CAPTURE else ev.load_protected_d_bundle
    return fx.d_load(loader, directory, repo, resolution, layer_a)


def _good_docs():
    corpus = population(2)
    return corpus, {k: (corpus.directory / f).read_bytes() for k, f in sb.DOCUMENT_FILES.items()}



@pytest.fixture(autouse=True)
def _each_test_is_a_fresh_scoring_process():
    """Every test starts with no protected truth marked read in this process (see ``plate_selection_fixtures``)."""
    fx.new_process()
    yield
    fx.new_process()

# ---------------------------------------------------------------------------------------------- (1) independent identity


def test_the_api_has_no_expected_digest_or_corpus_object_parameter():
    """(i) The caller cannot supply content AND the digest that blesses it: no entry point takes a manifest, an
    expected digest, a configuration, a partition plan or a freeze; the identities come from the committed record."""
    for name in ("run_track", "run_detection", "run_reading", "evaluate_a", "evaluate_b", "evaluate_c", "evaluate_d",
                 "diagnostic_evaluate_d_at_floor", "top_k", "resolve_baseline", "verify_resolution", "baseline_gate",
                 "paired_cluster_bootstrap", "rankable_compositions", "diagnostic_ocr_uplift", "queries_for",
                 "layer_digest"):
        parameters = set(inspect.signature(getattr(ev, name)).parameters)
        assert not parameters & {"manifest", "expected_manifest_digest", "config", "freeze", "partition_plan",
                                 "replicates", "seed", "mpid", "k", "minimum_support", "queries"}, name
    assert set(inspect.signature(ev.load_selection_bundle).parameters) == {"corpus_dir", "repo_root"}
    for loader in (ev.load_d_capture_bundle, ev.load_protected_d_bundle):
        assert set(inspect.signature(loader).parameters) == {"corpus_dir", "resolution", "layer_a_results",
                                                             "authorization", "repo_root"}
    for gone in ("EvaluationManifest", "ProtocolConfig", "PartitionPlan", "Truth", "TEXT", "UNSUPPORTED_TEXT",
                 "manifest_digest", "verify_manifest", "partition_plan_digest"):
        assert not hasattr(ev, gone), gone
    assert ev.baseline_freeze(population(1).sel).freeze_record_sha256 == population(1).sel.record_sha256
    assert not hasattr(sb, "state_of")  # harness state is never handed to a caller (private `_state_of`)


def test_content_must_match_the_committed_record():
    corpus, docs = _good_docs()
    record = (corpus.repo / sb.FREEZE_RECORD_PATH).read_bytes()
    edited = dict(docs, dTruth=docs["dTruth"].replace(b"KA00AB1000", b"KA00AB1001"))
    with pytest.raises(ValueError, match="corpus_document_not_the_frozen_document:dTruth"):
        _raw_load(record, edited, "content-edited", stage=sb.PROTECTED)
    with pytest.raises(ValueError, match="corpus_document_absent:abIndex"):
        _raw_load(record, {k: v for k, v in docs.items() if k != "abIndex"}, "content-missing")


def test_the_record_must_be_committed_and_unedited(tmp_path):
    corpus, docs = _good_docs()
    record = (corpus.repo / sb.FREEZE_RECORD_PATH).read_bytes()
    bundle = _raw_load(record, docs, "committed-once")
    path = fx._ROOT / "committed-once" / sb.FREEZE_RECORD_PATH
    path.write_bytes(record.replace(b'"bootstrapSeed":7', b'"bootstrapSeed":8'))  # an uncommitted seed swap
    with pytest.raises(ValueError, match="differs_from_its_commit"):
        ev.load_selection_bundle(fx._ROOT / "committed-once-corpus", repo_root=fx._ROOT / "committed-once")
    path.write_bytes(record)
    assert ev.load_selection_bundle(fx._ROOT / "committed-once-corpus",
                                    repo_root=fx._ROOT / "committed-once").bundle_id == bundle.bundle_id
    with pytest.raises(ValueError, match="freeze_record_absent"):
        ev.load_selection_bundle(corpus.directory, repo_root=tmp_path)
    fx.write(tmp_path / sb.FREEZE_RECORD_PATH, record)   # present but not in any repository
    with pytest.raises(ValueError, match="freeze_record_not_committed|not_a_repository_root"):
        ev.load_selection_bundle(corpus.directory, repo_root=tmp_path)
    nested = corpus.repo / "config" / "nested"
    fx.write(nested / sb.FREEZE_RECORD_PATH, record)   # a record inside a repository, below its root
    with pytest.raises(ValueError, match="not_a_repository_root"):
        ev.load_selection_bundle(corpus.directory, repo_root=nested)


def test_a_recommitted_change_is_a_different_identity_and_frozen_results_are_refused():
    """(ii) Changing content and recommitting a matching record yields new digests; the frozen corpus's runs and
    resolution are refused under it (probe cold218e 10, cold218g)."""
    corpus = population(3)
    runs = runs_for(corpus, outputs_of(3, lambda i: [_plate_text(i)]))
    edited = population(3, mutate=lambda docs: docs["dTruth"]["truths"][0].update(text="KA00AB1999"))
    assert (edited.sel.record_sha256, edited.d_digest) != (corpus.sel.record_sha256, corpus.d_digest)
    with pytest.raises(ValueError, match="result_of_another_partition_or_bundle"):
        score(edited, runs)
    with pytest.raises(ev.BaselineStop, match="of_another_freeze"):
        ev.verify_resolution(edited.full, corpus.resolution, corpus.layer_a)


# ---------------------------------------------------------------------------------------------- (2) strict parsing


@pytest.mark.parametrize("transform, code", [
    (lambda b: b.replace(b'{"partition"', b'{"partition":"AB_SELECTION","partition"', 1), "duplicate_key"),
    (lambda b: json.dumps(json.loads(b), indent=1).encode() + b"\n", "not_canonical"),          # whitespace
    (lambda b: json.dumps(dict(reversed(list(json.loads(b).items()))), separators=(",", ":")).encode() + b"\n",
     "not_canonical"),                                                                             # key order
    (lambda b: b.replace(b'"rank":0', b'"rank":0.0', 1), "evidence_malformed"),                    # int as float
    (lambda b: b.replace(b'"rank":0', b'"rank":0e0', 1), "not_canonical"),                       # number form
    (lambda b: b.replace(b'"rank":0', b'"rank":-0', 1), "not_canonical"),
    (lambda b: b.replace(b'"rank":0', b'"rank":NaN', 1), "non_finite_number"),
    (lambda b: b.replace(b'"rank":0', b'"rank":1e400', 1), "non_finite_number|not_canonical"),
    (lambda b: b.replace(b'"AB_SELECTION"', b'"\\u0041B_SELECTION"', 1), "not_canonical"),         # escape
    (lambda b: b.replace(b'"AB_SELECTION"', "\"AB_SELECTION \"".encode(), 1), "not_ascii"),
    (lambda b: b"\xef\xbb\xbf" + b, "not_ascii"),                                                  # BOM
    (lambda b: b[:-1] + b"\r\n", "not_canonical"),                                                 # CRLF
    (lambda b: b[:-1], "not_canonical"),                                                           # no final LF
    (lambda b: b.replace(b'"trackId"', b'"trackID"', 1), "malformed"),                             # unknown key
])
def test_documents_parse_strictly(transform, code):
    """(ii) Every non-canonical or ambiguous representation of a document is refused, even when the committed record
    names its exact bytes."""
    corpus, docs = _good_docs()
    data = transform(docs["abIndex"])
    name = f"strict-{sb.document_sha256(data)[:16]}"
    edited = dict(docs, abIndex=data)
    record = dict(corpus.record)
    record["documents"] = dict(record["documents"], abIndex=sb.document_sha256(data))
    record["disjointness"] = sb.disjointness_attestation(record["documents"])
    with pytest.raises(ValueError, match=code):
        _raw_load(sb.canonical_bytes(record), edited, name)


def test_the_record_parses_strictly():
    corpus, docs = _good_docs()
    record = sb.canonical_bytes(corpus.record)
    for n, (data, code) in enumerate((
            (record.replace(b'{"bootstrapReplicates"', b'{"bootstrapSeed":8,"bootstrapReplicates"', 1),
             "duplicate_key"),
            (json.dumps(corpus.record, indent=2, sort_keys=True).encode() + b"\n", "not_canonical"),
            (record.replace(b'"bootstrapSeed":7', b'"bootstrapSeed":7.0', 1), "protocol_malformed"),
            (record.replace(b'"topK":3', b'"topK":3.0', 1), "top_k_not_frozen_value"))):
        with pytest.raises(ValueError, match=code):
            _raw_load(data, docs, f"record-strict-{n}")


# ---------------------------------------------------------------------------------------------- (3) caller objects


def test_no_caller_domain_object_reaches_scoring_probe_cold218g():
    """cold218g: a Truth subclass (supported_text), a ProtocolConfig subclass (row → seeds), an EvidenceImage
    subclass (row → substituted bytes) and a PartitionPlan subclass (row → every site PROTECTED_D) each kept the
    digest and changed D, seeds, evidence or partitions. (i) None of these types exist; truth, configuration,
    evidence and partitions are parsed from verified bytes into harness state the caller never holds."""
    for name in ("Truth", "ProtocolConfig", "PartitionPlan", "EvaluationManifest", "ManifestTrack", "ManifestCrop",
                 "ManifestPlate"):
        assert not hasattr(ev, name) and not hasattr(sb, name)
    corpus = population(3)
    runs = runs_for(corpus, outputs_of(3, lambda i: [_plate_text(i)]))
    first = score(corpus, runs)
    # image substitution through the only caller hook, the byte source: refused (ii)
    substitute = fx._stored(fx._jpeg((64, 32), (1, 2, 3)))[0]
    with pytest.raises(ValueError, match="image_integrity_failed"):
        ev.run_track(corpus.capture, "t0", detector=GOOD_BOX, recogniser=fx.Recogniser(["x"]), detector_identity=DET,
                     recogniser_identity=REC, images=lambda o, s: fx.IMAGES[substitute])

    class Bytes(bytes):
        pass

    with pytest.raises(ValueError, match="image_integrity_failed"):  # an exact-bytes rule, not a subclass
        ev.run_track(corpus.capture, "t0", detector=GOOD_BOX, recogniser=fx.Recogniser(["x"]), detector_identity=DET,
                     recogniser_identity=REC, images=lambda o, s: Bytes(images(o, s)))
    assert score(corpus, runs).d_score == first.d_score == 1


def test_result_subclasses_properties_and_mutation_are_inert():
    """cold218e 9 / probes2: relabelled, edited, object.__setattr__-mutated or subclassed copies of harness runs
    and scores. (i) Only the ``result_id`` string is read; the harness scores its own record."""
    corpus = population(3)
    runs = runs_for(corpus, outputs_of(3, lambda i: [_plate_text(i)]))
    silent = runs_for(corpus, outputs_of(3, lambda i: [""]))
    truth = score(corpus, runs).d_score

    class EvilRun(ev.TrackRun):
        __slots__ = ()

        def __getattribute__(self, name):   # every field but the id reports the silent run
            if name in ("record", "state", "track_id", "evidence"):
                return object.__getattribute__(silent[0], name)
            return object.__getattribute__(self, name)

    evil = EvilRun(*[getattr(runs[0], f.name) for f in dataclasses.fields(ev.TrackRun)])
    object.__setattr__(runs[1], "record", silent[1].record)   # the caller's copy only
    object.__setattr__(runs[2], "state", ev.CONTRACT_FAIL)
    assert score(corpus, [evil, runs[1], runs[2]]).d_score == truth == 1
    s = score(corpus, silent)
    s.accounting["text"] = 999
    object.__setattr__(s, "d_score", Fraction(1))
    assert stored(ev._D, s).d_score == 0 and stored(ev._D, s).accounting["text"] == 3

    class Handle:
        bundle_id = "0" * 64

    with pytest.raises(ValueError, match="bundle_not_loaded_by_the_harness"):
        score(dataclasses.replace(corpus, _full=Handle()), runs)

    class EvilStr(str):
        def __eq__(self, other):
            return True

        __hash__ = str.__hash__

    with pytest.raises(ValueError, match="not_from_the_harness"):
        score(corpus, [dataclasses.replace(runs[0], result_id=EvilStr(runs[0].result_id))] + runs[1:])


def test_identity_claims_must_equal_the_frozen_roster():
    """R3 (cold218e probes2 alias identity): a composition or run identity must be a roster entry by id AND SHA;
    subclasses and str subclasses are refused."""
    corpus = population(2)
    alias = ev.ComponentIdentity("PD2-S", _h("retrained"))
    with pytest.raises(ValueError, match="run_detector_not_in_the_frozen_roster"):
        run(corpus, "t0", [""], det=alias)
    runs = runs_for(corpus, outputs_of(2, lambda i: [""]))
    with pytest.raises(ValueError, match="d_detector_not_in_the_frozen_roster"):
        score(corpus, runs, composition=(alias, REC))
    with pytest.raises(ValueError, match="d_recogniser_not_in_the_frozen_roster"):
        score(corpus, runs, composition=(DET, ev.ComponentIdentity("OC9-ALIAS", OC5.identity_sha256)))

    class Liar(ev.ComponentIdentity):
        __slots__ = ()

        def __getattribute__(self, name):
            if name == "candidate_id":
                return type("S", (str,), {})("PD2-S")
            return object.__getattribute__(self, name)

    liar = object.__new__(Liar)
    object.__setattr__(liar, "identity_sha256", _h("PD2-S"))
    with pytest.raises(ValueError, match="identity_required"):
        score(corpus, runs, composition=(liar, REC))
    with pytest.raises(ValueError, match="composition_malformed"):
        score(corpus, runs, composition=(DET, REC, OC5))


def test_a_bundle_handle_is_read_once_per_call():
    """New attack class: a handle whose ``bundle_id`` alternates between two genuine bundles cannot show one bundle's
    population to the run checks and another's queries or resolution to the score."""
    base = population(3)
    other = population(3, mutate_record=lambda r: r["protocol"]["query"].update(seed="alternate"))
    runs = runs_for(base, outputs_of(3, lambda i: [_plate_text(i)]))

    class Alternating:
        def __init__(self):
            self.reads = 0

        @property
        def bundle_id(self):
            self.reads += 1
            return (base.full if self.reads == 1 else other.full).bundle_id

    handle = Alternating()
    result = ev.evaluate_d(handle, runs, composition=(DET, REC))
    assert handle.reads == 1 and result.query_set_sha256 == ev.queries_for(base.full).query_set_sha256
    assert ev.queries_for(base.full).query_set_sha256 != ev.queries_for(other.full).query_set_sha256
    handle = Alternating()
    compare_result = ev.paired_cluster_bootstrap(handle, runs, runs, composition_a=(DET, REC),
                                                 composition_b=(DET, REC), resolution=base.resolution,
                                                 layer_a_results=base.layer_a)
    assert handle.reads == 1 and compare_result.outcome == "insufficient-clusters"

# ---------------------------------------------------------------------------------------------- (4) iterables


class Flip:
    """A re-iterable that yields a different list on every iteration and counts iterations."""

    def __init__(self, *lists):
        self.lists, self.count = lists, 0

    def __iter__(self):
        items = self.lists[min(self.count, len(self.lists) - 1)]
        self.count += 1
        return iter(items)


def test_every_iterable_is_materialised_once():
    """R1 (cold218g: runs_a iterated three times in the comparison). Each entry consumes its iterable once, so a
    re-iterable cannot show one population to a check and another to the score."""
    corpus = population(60)
    good = runs_for(corpus, outputs_of(60, lambda i: [_plate_text(i)]))
    silent = runs_for(corpus, outputs_of(60, lambda i: [""]))
    flip = Flip(good, silent)
    assert score(corpus, flip).d_score == 1 and flip.count == 1
    assert score(corpus, (r for r in good)).d_score == 1
    other = runs_for(corpus, outputs_of(60, lambda i: [""]), rec=ident("OC2-A"))
    flip_a = Flip(good, silent)
    result = compare(corpus, flip_a, other, composition_b=(DET, ident("OC2-A")))
    assert flip_a.count == 1 and result.outcome == "superior"
    layer_a = Flip(layer_a_for(corpus), [])
    with pytest.raises(ev.BaselineStop):   # D was read: resolution refuses — but the iterable is consumed once
        ev.resolve_baseline(corpus.sel, layer_a, d_rows_read=0, resolved_at_utc=WHEN)
    selection = build([T("it0", "iter-site", _plate_text(0))], resolve=False)
    la = Flip(layer_a_for(selection), [])
    assert ev.resolve_baseline(selection.sel, la, d_rows_read=0, resolved_at_utc=WHEN).pd_base_id == "PD2-N"
    assert la.count == 1
    crops_corpus = _ab(T("ia", "ia-site", "KA01AB1234"))
    det_runs = [ev.run_detection(crops_corpus.sel, "c-ia", detector=GOOD_BOX, detector_identity=DET, images=images)]
    flip_det = Flip(det_runs, [])
    assert ev.evaluate_a(crops_corpus.sel, flip_det, detector=DET).outcome == ev.MEASURED and flip_det.count == 1
    scores = [comp(selection, d, 100, 0.9 - i / 10, 0.1, 0.9) for i, d in enumerate(fx.DETECTORS)]
    flip_k = Flip(scores, [])
    assert ev.top_k(selection.sel, flip_k, "detector") == list(fx.DETECTORS) and flip_k.count == 1
    composition = Flip([DET, REC], [PD_BASE, OC5])
    assert score(corpus, good, composition=composition).detector == DET and composition.count == 1


# ---------------------------------------------------------------------------------------------- (5) configuration


@pytest.mark.parametrize("change, code", [
    (lambda r: r["protocol"].update(topK=4), "top_k_not_frozen_value"),
    (lambda r: r["protocol"].update(topKSupportFloor=0), "top_k_not_frozen_value"),
    (lambda r: r["protocol"].update(bootstrapReplicates=999), "replicates_not_frozen_value"),
    (lambda r: r["protocol"].update(percentileRule="nearest"), "rule_not_frozen"),
    (lambda r: r["protocol"].update(mpid="0.04"), "rule_not_frozen"),
    (lambda r: r["protocol"].update(calibrationMinimumClusters=0), "protocol_malformed"),
    (lambda r: r["protocol"].update(detectorFloors=[["PD1-X", 0.25], ["PD2-N", 0.25]]), "not_the_detector_universe"),
    (lambda r: r["protocol"].update(detectorFloors=[["PD1-X", 1.5], ["PD2-N", 0.25], ["PD2-S", 0.25]]),
     "floors_malformed"),
    (lambda r: r["roster"].update(recognisers=[["OC1-XS", _h("OC1-XS"), True], ["OC5-BEST", _h("OC5-BEST"), True]]),
     "benchmark_only_component_in_a_universe"),
    (lambda r: r["roster"].update(recognisers=[["OC1-XS", _h("PD2-S"), True]]), "identity_under_two_ids"),
    (lambda r: r["roster"].update(recognisers=[["OC9-X", _h("OC5-BEST"), True]]), "identity_under_two_ids"),
    (lambda r: r["roster"].update(recognisers=[["PD2-S", _h("OC9"), True]]), "identity_under_two_ids"),
    (lambda r: r["roster"].update(recognisers=[]), "recognisers_malformed"),
    (lambda r: r["roster"].update(recognisers=[["OC2-B", _h("OC2-B"), True], ["OC2-A", _h("OC2-A"), True]]),
     "recognisers_malformed"),
    # owner point 4: the N4 verdict is a frozen bool per component, never absent, never a truthy stand-in
    (lambda r: r["roster"].update(recognisers=[["OC1-XS", _h("OC1-XS")]]), "recognisers_malformed"),
    (lambda r: r["roster"].update(recognisers=[["OC1-XS", _h("OC1-XS"), 1]]), "recognisers_malformed"),
    (lambda r: r["roster"].update(detectors=[[d, _h(d), "yes"] for d in fx.DETECTORS]), "detectors_malformed"),
    # M3 reconciliation: "C-" is M3's derived ordinary-composition namespace; the partner is the other event
    (lambda r: r["roster"].update(compositionId="C-GATE"), "composition_id_reserved"),
    (lambda r: r["roster"].update(partnerEventId=r["roster"]["eventId"]), "partner_event_is_the_baseline_event"),
    # owner point 2: the disjointness result is the construction tool's, bound to the four document hashes
    (lambda r: r.pop("disjointness"), "freeze_record_malformed"),
    (lambda r: r["disjointness"].update(result="OVERLAP"), "disjointness_not_attested"),
    (lambda r: r["disjointness"].update(sha256=_h("x")), "disjointness_not_attested"),
    (lambda r: r["roster"].update(rankingRuleSha256=_h("another rule")), "ranking_rule_not_the_frozen_rule"),
    (lambda r: r["roster"].update(frozenAtUtc="yesterday"), "time_malformed"),
    (lambda r: r.update(schema="v0"), "freeze_record_schema"),
])
def test_score_affecting_configuration_is_frozen_in_the_record(change, code):
    """(ii) K, the support floor, R, the rule, MPID, the calibration minimum, floors, rosters and OC5 exclusion are
    bound by the record and pinned; a substitution is refused."""
    with pytest.raises(ValueError, match=code):
        population(2, mutate_record=change)


def test_seed_roster_and_query_substitutions_change_the_identity():
    """(ii) A seed, roster or query-parameter substitution is a different committed record: new digests, and the
    frozen corpus's results are refused under it (cold218d probe 2/3 seed shopping)."""
    base = population(2)
    runs = runs_for(base, outputs_of(2, lambda i: [_plate_text(i)]))
    variants = [population(2, mutate_record=lambda r: r["protocol"].update(bootstrapSeed=8)),
                population(2, mutate_record=lambda r: r["protocol"]["query"].update(seed="another")),
                population(2, roster=default_roster(recognisers=("OC1-XS", "OC2-A")))]
    for variant in variants:
        assert variant.d_digest != base.d_digest and variant.ab_digest != base.ab_digest
        with pytest.raises(ValueError, match="result_of_another_partition_or_bundle"):
            score(variant, runs)
    assert ev.queries_for(variants[1].full).query_set_sha256 != ev.queries_for(base.full).query_set_sha256


# ---------------------------------------------------------------------------------------------- (6) partitions


def test_swapped_partitions_and_moved_sites_are_refused():
    """(ii) A/B and D documents swapped, a site moved to the other partition, a site under two spellings, a site in
    both partitions, a plan with one partition only."""
    corpus, docs = _good_docs()
    swapped = dict(docs, abIndex=docs["dIndex"], dIndex=docs["abIndex"])
    record = dict(corpus.record, documents={k: sb.document_sha256(v) for k, v in swapped.items()})
    record["disjointness"] = sb.disjointness_attestation(record["documents"])
    with pytest.raises(ValueError, match="index_is_not_this_partition"):
        _raw_load(sb.canonical_bytes(record), swapped, "swapped-partitions")
    for n, sites in enumerate(([["site0", "AB_SELECTION"], ["site1", "PROTECTED_D"], ["twin-ab-site", "AB_SELECTION"]],
                               [["site0", "PROTECTED_D"], ["site1", "PROTECTED_D"], ["twin-ab-site", "PROTECTED_D"]],
                               [["SITE0", "AB_SELECTION"], ["site0", "PROTECTED_D"], ["site1", "PROTECTED_D"],
                                ["twin-ab-site", "AB_SELECTION"]],
                               [["site0", "PROTECTED_D"], ["site0 ", "AB_SELECTION"], ["site1", "PROTECTED_D"],
                                ["twin-ab-site", "AB_SELECTION"]],
                               [["site0", "PROTECTED_D"], ["site0", "AB_SELECTION"], ["site1", "PROTECTED_D"],
                                ["twin-ab-site", "AB_SELECTION"]])):
        with pytest.raises(ValueError, match="site_not_in_this_partition|needs_both_partitions|site_not_canonical"
                                             "|site_in_two_partitions"):
            build([T("t0", "site0", _plate_text(0)), T("t1", "site1", _plate_text(1))], sites=sites)


def test_each_layer_projects_only_from_its_partition_and_stage():
    corpus = _ab(T("a0", "ab-site", "KA01AB1234"), twin=[T("d0", "d-site", "KA02AB1234")])
    with pytest.raises(ValueError, match="requires_the_protected_d_bundle"):
        ev.evaluate_d(corpus.sel, [], composition=(DET, REC))   # the selection stage holds no D truth
    with pytest.raises(ValueError, match="run_track_not_in_bundle"):   # no D index at the selection stage
        run(corpus, "d0", ["KA02AB1234"], bundle=corpus.sel)
    ab_run = run(corpus, "a0", ["KA01AB1234"])
    with pytest.raises(ValueError, match="result_of_another_partition_or_bundle"):
        ev.evaluate_d(corpus.full, [ab_run], composition=(DET, REC))   # a D run on an A/B Track
    d_run = run(corpus, "d0", ["KA02AB1234"])
    with pytest.raises(ValueError, match="result_of_another_partition_or_bundle"):
        ev.evaluate_c(corpus.sel, [d_run], composition=(DET, REC))
    assert ev.evaluate_d(corpus.full, [d_run], composition=(DET, REC)).d_score == 1
    assert not sb.d_truth_loaded(build([T("fresh", "fresh-site", "KA03AB1234")], resolve=False).sel.record_sha256)


# ---------------------------------------------------------------------------------------------- (7) cross-partition R2


def test_cross_partition_aliases_are_refused():
    """R2: Track ids, MAVI uuids, observations and content SHA-256s are unique across BOTH partitions."""
    a = T("x0", "ab-site", "KA01AB1234")
    cases = {
        "track_id_in_two_partitions": T("x0", "d-site", "KA02AB1234"),
        "mavi_track_shared_by_two_tracks": dataclasses.replace(T("x1", "d-site", "KA02AB1234")),
        "observation_shared_by_two_images": T("x2", "d-site", "KA02AB1234"),
        "content_shared_by_two_images": T("x3", "d-site", "KA02AB1234"),
    }
    cases["mavi_track_shared_by_two_tracks"].mavi = a.mavi
    cases["observation_shared_by_two_images"].evidence = [dict(cases["observation_shared_by_two_images"].evidence[0],
                                                               observationId=a.evidence[0]["observationId"])]
    cases["content_shared_by_two_images"].evidence = [dict(cases["content_shared_by_two_images"].evidence[0],
                                                           sha256=a.evidence[0]["sha256"],
                                                           sizeBytes=a.evidence[0]["sizeBytes"])]
    for code, d_track in cases.items():
        with pytest.raises(ValueError, match=f"bundle_{code}"):   # owner point 2: refused at freeze construction
            _ab(a, twin=[d_track])
        # A hand-assembled record claiming disjointness: Layer A never sees D, so the selection stage loads, and the
        # claim is re-verified on the real D index the moment D is opened (no D-stage bundle exists).
        forged = _ab(a, twin=[d_track], forge_record=True)
        assert forged.sel.stage == sb.SELECTION
        with pytest.raises(ValueError, match=f"bundle_{code}"):
            forged.capture
    evidence_sha = a.evidence[0]
    image = dict(fx.plate_image(1), sha256=evidence_sha["sha256"], sizeBytes=evidence_sha["sizeBytes"])
    with pytest.raises(ValueError, match="bundle_content_shared_by_two_images"):
        build([a], plates=[dict(plate("p0", "x0", b=1), plateImage=image)], twin=[T("y", "d-site", "KA02AB1234")])
    with pytest.raises(ValueError, match="truth_d_partition_holds_a_b_items"):   # refused at freeze construction
        build([T("dz", "dz-site", "KA02AB1234")],
              mutate=lambda docs: docs["dTruth"]["crops"].append(crop("c", "dz", 0, POLY)))
    forged = build([T("dz", "dz-site", "KA02AB1234")], forge_record=True,
                   mutate=lambda docs: docs["dTruth"]["crops"].append(crop("c", "dz", 0, POLY)))
    with pytest.raises(ValueError, match="truth_d_partition_holds_a_b_items"):   # and again when D truth is opened
        forged.full


# ---------------------------------------------------------------------------------------------- (8) evidence / truth


@pytest.mark.parametrize("mutate, code", [
    (lambda d: d["abIndex"]["tracks"][0]["evidence"].append(dict(d["abIndex"]["tracks"][0]["evidence"][0], rank=1)),
     "observation_shared_by_two_images"),
    (lambda d: d["abIndex"]["tracks"][0]["evidence"][0].update(role="side-view"), "index_evidence_malformed"),
    (lambda d: d["abIndex"]["tracks"][0]["evidence"][0].update(sizeBytes=0), "index_evidence_malformed"),
    (lambda d: d["abIndex"]["tracks"][0]["evidence"][0].update(observationId="obs"), "index_evidence_malformed"),
    (lambda d: d["abIndex"]["tracks"][0]["evidence"][0].update(observationId=d["abIndex"]["tracks"][0]["evidence"][0]
                                                               ["observationId"].upper()), "index_evidence_malformed"),
    (lambda d: d["abIndex"]["tracks"][0].update(maviTrackUuid=None), "mavi_track_and_evidence_disagree"),
    (lambda d: d["abIndex"]["tracks"].reverse(), "not_in_canonical_order"),
    (lambda d: d["abTruth"]["crops"].append(dict(d["abTruth"]["crops"][0], cropId="c-z")), "two_crops_on_one"),
    (lambda d: d["abTruth"]["crops"][0].update(polygons=[[[True, 1], [2, 1], [2, 2]]]), "polygon_malformed"),
    (lambda d: d["abTruth"]["crops"][0].update(polygons=[[[1, 1], [2, 2], [3, 3]]]), "polygon_malformed"),
    (lambda d: d["abTruth"]["truths"][0].update(state="NO_PLATE", text=None), "polygon_contradicts_truth"),
    (lambda d: d["abTruth"]["truths"][0].update(state="NO_GT_VEHICLE", text=None), "polygon_contradicts_truth"),
    (lambda d: d["abTruth"]["truths"].pop(), "truth_tracks_are_not_the_index_tracks"),
])
def test_evidence_and_truth_documents_are_validated(mutate, code):
    tracks = [T("e0", "e-site0", "KA01AB1234"), T("e1", "e-site1", "KA02AB1234")]
    with pytest.raises(ValueError, match=code):
        _ab(*tracks, mutate=mutate)


def test_truth_state_manipulation_and_letter_digit_classification():
    """Owner truth semantics (cold218f probe1, cold218g probe a): TEXT needs v1 AND ≥1 letter AND ≥1 digit; other
    non-reserved human text is UNSUPPORTED_TEXT (retained, never refused); reserved syntax and unknown states are
    malformed; non-text states carry no text."""
    supported = {"KA01AB1234": "KA01AB1234", "ka 01 ab 1234": "KA01AB1234", "NOPLATE0": "NOPLATE0"}
    for text, normalised in supported.items():
        assert ev.classify_truth("TEXT", text) == (ev.TruthState.TEXT, text, normalised)
    for text in ("UNKNOWN", "NONE", "NA", "N/A", "NULL", "ILLEGIBLE", "UNREADBLE", "NOPLAT", "1234", "123456",
                 "ABCD", "KA01AB12३४", "[UNREADABLE]", "UNREADABLE.", "a@b"):
        assert ev.classify_truth("TEXT", text) == (ev.TruthState.UNSUPPORTED_TEXT, text, None), text
    for text in ("NO_PLATE", "no plate", "No-Plate", "UNREADABLE", "unreadable", "NO_GT_VEHICLE", "TEXT",
                 "UNSUPPORTED_TEXT", "<NO_PLATE>", "<no-plate>", "<unreadable>", "<no-gt-vehicle>", "<anything>",
                 "< x >"):
        with pytest.raises(ValueError, match="reserved_syntax"):
            ev.classify_truth("TEXT", text)
    for text in ("<anything", "x>", "<UNREADBLE", "KA01AB1234>"):   # one bracket only: not a defined encoding
        assert ev.classify_truth("TEXT", text) == (ev.TruthState.UNSUPPORTED_TEXT, text, None), text
    for state in ("UNSUPPORTED_TEXT", "text", "No_Plate", "UNREADBLE", None, 1):
        with pytest.raises(ValueError, match="truth_state_unknown"):
            ev.classify_truth(state, "KA01AB1234")
    for state in ("NO_PLATE", "UNREADABLE", "NO_GT_VEHICLE"):
        with pytest.raises(ValueError, match="truth_text_only_for_text"):
            ev.classify_truth(state, "KA01AB1234")
    for text in (" KA01AB1234", "KA01AB1234\n", "", None, 5):
        with pytest.raises(ValueError, match="truth_text_malformed"):
            ev.classify_truth("TEXT", text)
    corpus = build([T("u0", "u-site", "UNKNOWN"), T("u1", "u-site", "KA01AB1234")])
    track = sb._state_of(corpus.full).d.tracks["u0"]
    assert (track.state, track.text) == (ev.TruthState.UNSUPPORTED_TEXT, "UNKNOWN")
    assert ev.queries_for(corpus.full).truths == ("KA01AB1234",)   # B/C/D read the typed state, never re-normalise


def test_b_and_c_use_the_typed_state_not_the_raw_text():
    """P1-A (convergence review): ``_reading_result`` re-normalised raw truth. Now a letters-only human text that
    v1 CAN normalise ("UNKNOWN") is UNSUPPORTED_TEXT in B and C: out of EM, wrong in ECE/risk–coverage."""
    corpus = build([T("b0", "b-site0", "KA01AB1234"), T("b1", "b-site1", "UNKNOWN")],
                   plates=[plate("p0", "b0", b=10, c=0), plate("p1", "b1", b=11, c=0)])
    b = ev.evaluate_b(corpus.sel, [ev.run_reading(corpus.sel, pid, recogniser=Outputs([R((t, 0.9))]),
                                                  recogniser_identity=REC, images=images)
                                   for pid, t in (("p0", "KA01AB1234"), ("p1", "UNKNOWN"))], recogniser=REC)
    assert (b.plates, b.exact, b.em, b.unsupported_truths) == (1, 1, 1, 1)
    assert b.risk_coverage[-1] == (1.0, 0.5)
    c = ev.evaluate_c(corpus.sel, [run(corpus, "b0", ["KA01AB1234"]), run(corpus, "b1", ["UNKNOWN"])],
                      composition=(DET, REC))
    assert (c.plates, c.em, c.unsupported_truths) == (1, 1, 1)


# ---------------------------------------------------------------------------------------------- (9) earlier probes


def test_earlier_probe_attacks_stay_closed():
    """cold218 P-A/P-E, cold218b probe 1/2, cold218d probe 1/5, cold218e: hand-built items, relabelled compositions,
    caller-chosen detector ids, NO_RUN substitution, zero-crop or subset reruns, runs of another composition."""
    corpus = population(3)
    good = runs_for(corpus, outputs_of(3, lambda i: [_plate_text(i)]))
    # (i) inexpressible: no item types, no evidence argument, no NO_RUN value, no caller candidate id for a result
    for name in ("TrackItem", "DetectionItem", "ReadItem", "NO_RUN", "not_read", "closed_population",
                 "evaluate_tracks", "evaluate_detection", "evaluate_reading", "ranking_plate_record"):
        assert not hasattr(ev, name)
    assert "evidence" not in inspect.signature(ev.run_track).parameters
    assert set(inspect.signature(ev.detector_component).parameters) == {"result"}
    # relabelling a composition: the identity comes from the harness record
    relabelled = ev.CompositionScore(dataclasses.replace(score(corpus, good), detector=PD_BASE, recogniser=OC5))
    assert (relabelled.detector_id, relabelled.recogniser_id) == ("PD2-S", "OC1-XS")
    # (ii) a run of another composition / omission / duplication
    with pytest.raises(ValueError, match="identity_is_not_the_composition"):
        score(corpus, good[:2] + [run(corpus, "t2", [_plate_text(2)], det=PD_BASE)])
    with pytest.raises(ValueError, match="do_not_equal_the_bundle_items"):
        score(corpus, good[:2])
    # R, seed, MPID and the calibration minimum are not parameters (cold218b probe 2, cold218d probe 2/3)
    with pytest.raises(TypeError):
        compare(corpus, good, good, replicates=1)
    with pytest.raises(TypeError):
        compare(corpus, good, good, seed=3)
    with pytest.raises(TypeError):
        compare(corpus, good, good, calibration_minimum_clusters=1)


def test_candidate_outputs_of_the_wrong_exact_type_are_contract_failures():
    """New attack class: a candidate returning subclassed containers, boxes, readings or strings whose behaviour can
    vary between the harness check and PR-3's use. The bake-off contract requires exact types (CONTRACT_FAIL)."""
    corpus = population(1)

    class Shifty(list):
        def __iter__(self):
            return iter([PlateBox(0, 0, 500, 500, 0.9)])

    class Box(PlateBox):
        pass

    class Text(str):
        pass

    class Det:
        def __init__(self, out):
            self.out = out

        def detect(self, crop, verified):
            return self.out

    cases = [(Det(Shifty([PlateBox(1, 1, 20, 10, 0.9)])), fx.Recogniser(["KA00AB1000"]), "not_a_list"),
             (Det([Box(1, 1, 20, 10, 0.9)]), fx.Recogniser(["KA00AB1000"]), "not_a_platebox"),
             (GOOD_BOX, Outputs([[Reading(Text("KA00AB1000"), 0.9)]]), "invalid_raw_text"),
             (GOOD_BOX, Outputs([[Reading("KA00AB1000", True)]]), "confidence_out_of_range")]
    for detector, recogniser, code in cases:
        result = run(corpus, "t0", detector=detector, recogniser=recogniser)
        assert result.state == ev.CONTRACT_FAIL and code in result.contract_violation


def test_resolution_and_gate_use_only_harness_records():
    corpus = population(1)
    base = score(corpus, runs_for(corpus, outputs_of(1, lambda i: [_plate_text(i)])))
    resolution = corpus.resolution
    assert ev.assert_resolution_unchanged(resolution, dataclasses.replace(resolution, pd_base_id="PD1-X")) is None
    with pytest.raises(ev.BaselineStop, match="not_from_the_harness"):
        gate(corpus, C("PD2-S", "OC1-XS", base), C("PD2-N", "OC5-BEST", base),
             resolution=ev.BaselineResolution(**{f.name: getattr(resolution, f.name)
                                                  for f in dataclasses.fields(ev.BaselineResolution)
                                                  if f.name != "result_id"}))
    flipped = layer_a_for(corpus, passed=("PD1-X", "PD2-N", "PD2-S"))
    with pytest.raises(ev.BaselineStop, match="differs_from_frozen_derivation"):  # cold218b probe 2: gate flip
        ev.baseline_gate(corpus.full, C("PD2-S", "OC1-XS", base), C("PD2-N", "OC5-BEST", base), resolution, flipped)
    with pytest.raises(ev.BaselineStop, match="after_d_data_loaded"):  # cold218 P-D: no post-hoc Stage 2
        ev.resolve_baseline(corpus.sel, flipped, d_rows_read=0, resolved_at_utc="2099-01-01T00:00:00Z")
    assert default_protocol()["topK"] == ev.TOP_K and ev.MPID == Fraction(4, 100)
