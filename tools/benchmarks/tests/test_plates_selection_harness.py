"""A–D evaluators and the query generator, through the manifest → execution envelope → sealed result boundary.

Synthetic fixtures only (no dataset, no model). The manifest and its expected digest here are a synthetic freeze
artefact; the real committed corpus manifest is an integration prerequisite before the PR-2 freeze.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import io
import math
import random
import uuid
from fractions import Fraction

import pytest
from PIL import Image

from mavi_vision.plates import pipeline
from mavi_vision.plates.inference import PlateBox, Reading, VerifiedCrop
from mavi_vision.plates.pipeline import PlateRecord, RankedReading
from tools.benchmarks.capabilities.plates import evaluator as ev
from tools.benchmarks.capabilities.plates import queries as q

PARAMS = q.QueryParameters(interior_offset=1, negatives_per_plate=2, seed="synthetic-seed")
MANIFEST = hashlib.sha256(b"synthetic-population-manifest").hexdigest()
OTHER_MANIFEST = hashlib.sha256(b"another-population").hexdigest()
FLOOR = 0.25
NS = uuid.NAMESPACE_URL


def gen(truths, manifest=MANIFEST):
    return q.generate(truths, PARAMS, manifest)


def _h(text):
    return hashlib.sha256(text.encode()).hexdigest()


def ident(candidate_id):
    return ev.ComponentIdentity(candidate_id, _h(candidate_id))


DET, REC, OC5, PD_BASE = ident("PD2-S"), ident("OC1-XS"), ident("OC5-BEST"), ident("PD2-N")
EVENTS = ("msr-ocr-2026-01", "GATE-BASE", "msr-plate-detector-2026-01")
DETECTOR_IDS = ("PD1-X", "PD2-M", "PD2-N", "PD2-S", "PD5-V6S", "PD9-X")
CONFIG = ev.ProtocolConfig(PARAMS, 7, 60, tuple((d, FLOOR) for d in DETECTOR_IDS))
WHEN = "2026-10-14T00:00:00Z"


# ---------------------------------------------------------------------------------------------- corpus fixtures


def _jpeg(size, colour=(200, 200, 200)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="JPEG")
    return buffer.getvalue()


JPEG = _jpeg((64, 32))
SHA = hashlib.sha256(JPEG).hexdigest()
IMAGES = {SHA: JPEG}


def plate_image(i):
    """A distinct GT plate-crop image per B plate (the manifest refuses one image under two plates)."""
    content = _jpeg((40, 12), (i * 3 % 256, 90, 160))
    sha = hashlib.sha256(content).hexdigest()
    IMAGES[sha] = content
    return ev.EvidenceImage(oid(f"plate{i}", 0), "gt-plate-crop", 0, sha, len(content))


def images(ref):
    return IMAGES[ref.sha256]


def oid(tid, k):
    return str(uuid.uuid5(NS, f"{tid}/{k}"))


def tuuid(tid):
    return str(uuid.uuid5(NS, f"track/{tid}"))


def evidence_image(name):
    """A distinct evidence image per observation (the manifest refuses two images with the same bytes)."""
    seed = hashlib.sha256(name.encode()).digest()
    content = _jpeg((64, 32), (seed[0], seed[1], seed[2]))
    sha = hashlib.sha256(content).hexdigest()
    IMAGES[sha] = content
    return sha, len(content)


def evidence(tid, n):
    out = []
    for k in range(n):
        sha, size = evidence_image(f"{tid}/{k}")
        out.append(ev.EvidenceImage(oid(tid, k), "near-view", k, sha, size))
    return tuple(out)


def truth_of(text):
    return ev.TEXT(text) if ev.normalised_truth(text) else ev.UNSUPPORTED_TEXT(text)


def T(tid, site, truth, n=1):
    """A manifest Track with ``n`` evidence images (``n=0``: no MAVI Track/evidence)."""
    truth = truth if isinstance(truth, ev.Truth) else truth_of(truth)
    return ev.ManifestTrack(tid, site, truth, tuuid(tid) if n else None, evidence(tid, n))


AB, D = ev.Partition.AB_SELECTION, ev.Partition.PROTECTED_D


@dataclasses.dataclass(frozen=True)
class M:
    m: ev.EvaluationManifest
    digest: str          # the synthetic frozen expected digest (an independent input to every call)
    twin: "M | None" = None

    @property
    def ab(self):
        return self if self.m.partition is AB else self.twin

    @property
    def d(self):
        return self if self.m.partition is D else self.twin


def _register(manifest):
    result = M(manifest, ev.manifest_digest(manifest))
    _MANIFESTS[result.digest] = result
    return result


def _sites(tracks):
    return {getattr(t, "site", None) for t in tracks} - {None}


def build(tracks, crops=(), plates=(), config=CONFIG, manifest_id="synthetic", partition=None, twin_tracks=None,
          plan=None):
    """One partition's manifest plus a minimal twin of the other partition sharing one site-level plan. Fixtures put
    A/B items in the A/B partition and everything else in the protected D partition."""
    partition = partition or (AB if crops or plates else D)
    other = D if partition is AB else AB
    if twin_tracks is None:
        twin_tracks = [T("twin-ab" if other is AB else "twin-d", "twin-ab-site" if other is AB else "twin-d-site",
                         "KA99AB0001" if other is AB else "KA98AB0002")]
    plan = plan or ev.PartitionPlan("plan", tuple(sorted([(s, partition) for s in _sites(tracks) if isinstance(s, str)]
                                                         + [(s, other) for s in _sites(twin_tracks)],
                                                         key=lambda x: x[0])))
    twin = _register(ev.EvaluationManifest("twin", other, plan, tuple(twin_tracks), (), (), config))
    me = _register(ev.EvaluationManifest(manifest_id, partition, plan, tuple(tracks), tuple(crops), tuple(plates),
                                         config))
    result = M(me.m, me.digest, twin)
    _MANIFESTS[result.digest] = result
    _MANIFESTS[twin.digest] = M(twin.m, twin.digest, result)
    return result


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


def run(mf, tid, reads=None, *, n_boxes=1, det=DET, rec=REC, detector=None, recogniser=None):
    return ev.run_track(mf.m, mf.digest, tid, detector=detector or boxes(n_boxes),
                        recogniser=recogniser or Recogniser(reads or []), detector_identity=det, recogniser_identity=rec,
                        images=images)


def runs_for(mf, outputs, **kw):
    """One run per evidence Track; ``outputs`` maps Track id → reads (one per evidence image)."""
    return [run(mf, t.track_id, outputs[t.track_id], **kw) for t in mf.m.tracks if t.has_mavi_evidence]


def score(mf, runs, composition=(DET, REC)):
    return ev.evaluate_d(mf.m, mf.digest, runs, composition=composition)


def _plate_text(i):
    return f"KA{i % 100:02d}AB{1000 + i}"


def population(n, sites=None):
    return build([T(f"t{i}", sites(i) if sites else f"site{i}", _plate_text(i)) for i in range(n)])


def outputs_of(n, read):
    return {f"t{i}": read(i) for i in range(n)}


def R(*readings):
    return [Reading(t, c) for t, c in readings]


# ---------------------------------------------------------------------------------------------- baseline fixtures


def comp(mf_digest, candidate_id, independent, support, primary, second, third, contract_fail=False,
         kind="detector"):
    """Fixture only: a sealed component score with chosen metrics on the manifest ``mf_digest``."""
    return ev._seal(ev._COMPONENT, ev.ComponentScore(candidate_id, independent, support, primary, second, third,
                                                     contract_fail, _h(candidate_id), kind, mf_digest, _h("m")))


RECOGNISERS = tuple((r, _h(r)) for r in ("OC1-XS", "OC2-A", "OC2-B"))


def digests_of(key):
    """(A/B manifest digest, D manifest digest, plan digest) for a fixture manifest digest, or synthetic values."""
    mf = _MANIFESTS.get(key)
    if mf is None:
        return key, "b" * 64, "c" * 64
    return mf.ab.digest, mf.d.digest, ev.partition_plan_digest(mf.m.partition_plan)


def ab_digest(key):
    return digests_of(key)[0]


def freeze_for(key, **changes):
    ab, d, plan = digests_of(key)
    fields = dict(eligible_detectors=(("PD1-X", _h("PD1-X")), ("PD2-N", _h("PD2-N")), ("PD2-S", _h("PD2-S"))),
                  benchmark_only_id="OC5-BEST", benchmark_only_identity_sha256=_h("OC5-BEST"),
                  layer_a_gates_sha256=_h("layer-a-gates"), frozen_at_utc="2026-10-01T00:00:00Z", event_id=EVENTS[0],
                  composition_id=EVENTS[1], partner_event_id=EVENTS[2], eligible_recognisers=RECOGNISERS,
                  ab_manifest_digest=ab, d_manifest_digest=d, partition_plan_digest=plan)
    fields.update(changes)
    return ev.BaselineFreeze(**fields)


def layer_a_for(key, passed=("PD2-N", "PD2-S"), metrics=None, identities=None):
    metrics = metrics or {"PD1-X": (0.99, 0.0, 0.99), "PD2-N": (0.95, 0.10, 0.90), "PD2-S": (0.93, 0.05, 0.92)}
    identities = identities or {}
    return [ev.LayerAResult(comp(ab_digest(key), d, True, 100, *metrics[d]), identities.get(d, _h(d)), d in passed)
            for d in ("PD1-X", "PD2-N", "PD2-S")]


@functools.lru_cache(maxsize=None)
def baseline_for(mf_digest):
    freeze = freeze_for(mf_digest)
    layer_a = layer_a_for(mf_digest)
    return freeze, layer_a, ev.resolve_baseline(freeze, layer_a, d_rows_read=0, resolved_at_utc=WHEN)


def gate(mf, composition, baseline, resolution=None, **kwargs):
    freeze, layer_a, sealed = baseline_for(mf.digest)
    return ev.baseline_gate(composition, baseline, resolution or sealed, freeze, layer_a, **kwargs)


def relabel(score_, detector, recogniser):
    """Fixture only: a sealed D score for a chosen composition (cheap gate fixtures)."""
    return ev._seal(ev._D, dataclasses.replace(score_, detector=ident(detector), recogniser=ident(recogniser), seal=""))


def C(detector, recogniser, score_):
    if isinstance(score_, ev.TrackScore) and ev._is_sealed(ev._D, score_):
        score_ = relabel(score_, detector, recogniser)
    return ev.CompositionScore(score_)


def with_d(base, d, **changes):
    return ev._seal(ev._D, dataclasses.replace(base, d_score=d, seal="", **changes))


def TOPK(scores, kind, freeze, mf=None):  # noqa: N802
    """top_k on the manifest the freeze belongs to (K and the support floor come from its frozen config)."""
    mf = mf or _MANIFESTS[freeze.ab_manifest_digest]
    return ev.top_k(scores, kind, freeze=freeze, manifest=mf.m, expected_manifest_digest=mf.digest)


_MANIFESTS: dict = {}


def compare(mf, ra, rb, **overrides):
    freeze, layer_a, resolution = baseline_for(mf.digest)
    arguments = dict(composition_a=(DET, REC), composition_b=(DET, REC), freeze=freeze, resolution=resolution,
                     layer_a_results=layer_a)
    arguments.update(overrides)
    return ev.paired_cluster_bootstrap(mf.m, mf.digest, ra, rb, **arguments)


# ---------------------------------------------------------------------------------------------- queries


def test_queries_are_deterministic_bounded_and_fixed_by_the_plan():
    first = gen(["KA01AB1234", "ka-01 ab 1234", "KA01CD99", "MH12", "ab@1", "22BH1234AA", "7ABC123"])
    second = gen(["7ABC123", "KA01CD99", "KA01AB1234", "MH12", "22BH1234AA"])
    assert first.queries == second.queries and first.query_set_sha256 == second.query_set_sha256
    assert first.rejected_truths == ("ab@1",)
    texts = {(x.query_class, x.text): x for x in first.queries}
    assert texts[("full", "KA01AB1234")].match == q.EXACT
    assert texts[("prefix", "KA01")].sources == ("KA01AB1234", "KA01CD99")
    assert texts[("suffix", "1234")].sources == ("22BH1234AA", "KA01AB1234")  # terminal four DIGITS
    assert q.last_digit_suffix("7ABC123") is None and q.last_digit_suffix("KA01CD99") is None
    assert first.skipped["suffix"] == 3
    assert (q.PREFIX_LENGTH, q.SUFFIX_DIGITS, q.INTERIOR_LENGTH) == (4, 4, 5)
    for query in first.queries:
        assert q.queryable(query.text)
        if query.query_class == q.NEGATIVE:
            assert not any(query.text in t for t in first.truths)
    q.verify(first)


def test_query_identity_is_bound_to_the_population():
    one, other = gen(["KA01AB1234"]), gen(["KA01AB1234"], OTHER_MANIFEST)
    assert one.generator_config_sha256 == other.generator_config_sha256
    assert one.query_set_sha256 != other.query_set_sha256
    with pytest.raises(ValueError, match="manifest"):
        q.generate(["KA01AB1234"], PARAMS, "not-a-sha")


def test_same_literal_from_two_classes_scores_once():
    result = gen(["1234ABCD5678", "XY1234"])
    merged = [m for m in result.metric_queries if m.text == "1234"]
    assert len(merged) == 1 and merged[0].classes == ("prefix", "suffix")
    assert len([x for x in result.queries if x.text == "1234"]) == 2


def test_query_lengths_are_not_parameters():
    with pytest.raises(TypeError):
        q.QueryParameters(prefix_length=4, interior_offset=1, negatives_per_plate=1, seed="s")  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        q.QueryParameters(0, 1, "s")


def test_d_queries_come_from_the_manifest_and_its_frozen_config():
    mf = build([T("a", "s1", "KA01AB1234"), T("b", "s2", ev.NO_PLATE)])
    queries = ev.queries_for(mf.m, mf.digest)
    assert queries.truths == ("KA01AB1234",) and queries.population_manifest_sha256 == mf.digest
    assert queries.query_set_sha256 == gen(["KA01AB1234"], mf.digest).query_set_sha256
    other = build(mf.m.tracks, config=dataclasses.replace(CONFIG, query=q.QueryParameters(2, 1, "another-seed")))
    assert other.digest != mf.digest  # the query configuration is part of the manifest identity


# ---------------------------------------------------------------------------------------------- the manifest


def test_manifest_digest_is_an_independent_frozen_input():
    mf = population(3)
    tampered = dataclasses.replace(mf.m, tracks=mf.m.tracks[:2])
    with pytest.raises(ValueError, match="not_the_frozen_manifest"):
        ev.verify_manifest(tampered, mf.digest)
    # a modified manifest with its own recomputed hash is a DIFFERENT corpus: results of the frozen one are refused
    recomputed = ev.manifest_digest(tampered)
    runs = runs_for(mf, outputs_of(3, lambda i: [_plate_text(i)]))
    with pytest.raises(ValueError, match="result_of_another_manifest"):
        ev.evaluate_d(tampered, recomputed, runs[:2], composition=(DET, REC))
    with pytest.raises(ValueError, match="expected_digest_malformed"):
        ev.verify_manifest(mf.m, "frozen")


def test_typed_truth_fails_closed():
    for bad in ("NO_PLATE", "<no-plate>", None):
        with pytest.raises(ValueError, match="truth_state_not_typed"):
            ev.Truth(bad)  # type: ignore[arg-type]
    for sentinel in ("<NO-PLATE>", "NO_PLATE", "UNREADABLE", "NO-GT-VEHICLE", "unreadable", "no plate", "<NO_PLATE"):
        with pytest.raises(ValueError, match="looks_like_a_sentinel"):
            ev.TEXT(sentinel)
    with pytest.raises(ValueError, match="truth_text_required"):
        ev.TEXT(" ")
    with pytest.raises(ValueError, match="truth_text_only_for_text"):
        ev.Truth(ev.TruthState.NO_PLATE, "KA01")
    assert ev.TEXT("KA01AB1234").supported_text == "KA01AB1234" and ev.UNSUPPORTED_TEXT("a@b").supported_text is None
    for placeholder in ("UNREADBLE", "NOPLAT", "N/A", "NONE", "NULL", "UNKNOWN", "ILLEGIBLE", "nil", "AB"):
        with pytest.raises(ValueError, match="placeholder_not_a_plate|looks_like_a_sentinel"):
            ev.TEXT(placeholder)  # never silently becomes supported text
    with pytest.raises(ValueError, match="does_not_normalise_use_unsupported_text"):
        ev.TEXT("KA01AB12३४")
    with pytest.raises(ValueError, match="normalises_use_text"):
        ev.UNSUPPORTED_TEXT("KA01AB1234")
    for state in (ev.TruthState.NO_PLATE, ev.TruthState.UNREADABLE, ev.TruthState.NO_GT_VEHICLE):
        with pytest.raises(ValueError, match="truth_text_only_for_text"):
            ev.Truth(state, "KA01AB1234")


@pytest.mark.parametrize("mutate, code", [
    (lambda t: [t[0], dataclasses.replace(t[1], track_id="t0")], "track_ids_not_unique"),
    (lambda t: [dataclasses.replace(t[0], truth=ev.NO_GT_VEHICLE, mavi_track_uuid=None, evidence=())] + t[1:],
     "no_gt_vehicle_without_mavi_evidence"),
    (lambda t: [dataclasses.replace(t[0], mavi_track_uuid=None)] + t[1:], "evidence_without_mavi_track"),
    (lambda t: [dataclasses.replace(t[0], evidence=())] + t[1:], "mavi_track_without_evidence"),
    (lambda t: [dataclasses.replace(t[0], evidence=t[0].evidence * 2)] + t[1:], "evidence_ids_not_unique|ranks"),
    (lambda t: [dataclasses.replace(t[0], evidence=(dataclasses.replace(t[0].evidence[0], observation_id="obs"),))]
     + t[1:], "evidence_malformed"),
    (lambda t: [dataclasses.replace(t[0], truth="KA01")] + t[1:], "track_malformed"),
])
def test_manifest_structure_is_validated(mutate, code):
    tracks = list(population(2).m.tracks)
    mf = build(mutate(tracks))
    with pytest.raises(ValueError, match=code):
        ev.verify_manifest(mf.m, mf.digest)


def test_manifest_config_is_frozen_structurally():
    tracks = population(2).m.tracks
    for config, code in ((dataclasses.replace(CONFIG, bootstrap_replicates=999), "replicates_not_frozen_value"),
                         (dataclasses.replace(CONFIG, percentile_rule="nearest"), "rule_not_frozen"),
                         (dataclasses.replace(CONFIG, mpid="0.04"), "rule_not_frozen"),
                         (dataclasses.replace(CONFIG, detector_floors=(("PD2-S", float("nan")),)), "floors_malformed")):
        mf = build(tracks, config=config)
        with pytest.raises(ValueError, match=code):
            ev.verify_manifest(mf.m, mf.digest)
    seeded = build(tracks, config=dataclasses.replace(CONFIG, bootstrap_seed=8))
    assert seeded.digest != build(tracks).digest  # a seed substitution is a different manifest identity


# ---------------------------------------------------------------------------------------------- execution envelopes


def test_runs_are_bound_to_their_track_evidence_and_identity():
    mf = build([T("t0", "s0", "KA01AB1234", n=2), T("t1", "s1", "MH12AB0001"), T("t2", "s2", ev.NO_PLATE, n=0)])
    r0 = run(mf, "t0", ["KA01AB1234", "KA01AB1234"])
    assert (r0.state, r0.track_id, r0.mavi_track_uuid, r0.evidence) == (ev.COMPLETED, "t0", tuuid("t0"),
                                                                          mf.m.tracks[0].evidence)
    assert (r0.manifest_digest, r0.detector, r0.recogniser) == (mf.digest, DET, REC)
    assert ev.is_ranking_profile(r0.parameters, FLOOR)
    with pytest.raises(ValueError, match="no_mavi_evidence"):  # NO_RUN is derived, never executed or supplied
        run(mf, "t2", [])
    with pytest.raises(ValueError, match="not_in_manifest"):
        run(mf, "t9", [])
    with pytest.raises(ValueError, match="detector_floor_not_frozen"):
        run(mf, "t1", ["x"], det=ident("PD7-NEW"))
    with pytest.raises(ValueError, match="image_integrity_failed"):
        ev.run_track(mf.m, mf.digest, "t1", detector=GOOD_BOX, recogniser=Recogniser(["x"]), detector_identity=DET,
                     recogniser_identity=REC, images=lambda ref: JPEG + b"x")


def test_candidate_silence_is_a_completed_run_not_no_run():
    mf = population(3)
    silent = runs_for(mf, outputs_of(3, lambda i: [""]))
    assert {r.state for r in silent} == {ev.COMPLETED}
    result = score(mf, silent)
    assert (result.outcome, result.d_status) == (ev.MEASURED, ev.MEASURED)
    assert (result.exact_recall, result.contains_recall, result.contains_precision, result.d_score) == (0, 0, 0, 0)


# ---------------------------------------------------------------------------------------------- generic attacks (D)


def test_population_completeness_and_substitution_attacks():
    mf = population(4)
    runs = runs_for(mf, outputs_of(4, lambda i: [_plate_text(i)]))
    assert score(mf, runs).d_score == 1
    hand_built = ev.TrackRun(*[getattr(runs[0], f.name) for f in dataclasses.fields(ev.TrackRun)][:-1])
    attacks = {
        "omission": (runs[1:], "do_not_equal_the_manifest_items"),
        "duplication": (runs + [runs[0]], "duplicate_result"),
        "cross_track_reuse": ([runs[1]] + runs[1:], "duplicate_result"),
        "relabelled_track": ([dataclasses.replace(runs[0], track_id="t9")] + runs[1:], "not_sealed"),
        "reduced_evidence": ([dataclasses.replace(runs[0], evidence=())] + runs[1:], "not_sealed"),
        "caller_built": ([hand_built] + runs[1:], "not_sealed"),
    }
    for name, (attack, code) in attacks.items():
        with pytest.raises(ValueError, match=code):
            score(mf, attack)


def test_evidence_set_attacks_cannot_produce_a_valid_run():
    """Reduced, empty, reordered or superset evidence lists exist only in another manifest, so their runs are of
    another manifest; the frozen manifest has exactly one execution per Track."""
    mf = build([T("t0", "s0", "KA01AB1234", n=2), T("t1", "s1", "MH12AB0001")])
    good = [run(mf, "t0", ["KA01AB1234"] * 2), run(mf, "t1", ["MH12AB0001"])]
    base = mf.m.tracks[0]
    reranked = lambda refs: tuple(dataclasses.replace(e, evidence_rank=k) for k, e in enumerate(refs))  # noqa: E731
    variants = {"reduced": base.evidence[:1], "empty": (), "reordered": reranked(base.evidence[::-1]),
                "superset": reranked(base.evidence + evidence("extra", 1))}
    for refs in variants.values():
        changed = dataclasses.replace(base, evidence=refs, mavi_track_uuid=base.mavi_track_uuid if refs else None)
        other = build([changed, mf.m.tracks[1]])
        assert other.digest != mf.digest
        if refs:
            foreign = run(other, "t0", ["KA01AB1234"] * len(refs))
            with pytest.raises(ValueError, match="result_of_another_manifest"):
                score(mf, [foreign, good[1]])
        with pytest.raises(ValueError, match="not_the_frozen_manifest"):
            score(dataclasses.replace(mf, m=other.m), good)  # the modified manifest against the frozen digest


def test_contract_fail_cannot_be_escaped_through_the_manifest():
    """Review 5, P1-A/P1-B through the boundary: a failed run stays CONTRACT_FAIL; a fake no-evidence state is a
    different manifest and fails against the frozen digest."""

    class Flaky:
        def detect(self, crop, verified):
            if verified.evidence_rank == 1:
                return [PlateBox(1, 1, 20, 10, float("nan"))]
            return [PlateBox(1, 1, 20, 10, 0.9)]

    mf = build([T("t0", "s0", _plate_text(0), n=2)] + [T(f"t{i}", f"site{i}", _plate_text(i)) for i in range(1, 5)])
    failed = run(mf, "t0", [_plate_text(0)] * 2, detector=Flaky())
    others = [run(mf, f"t{i}", [_plate_text(i)]) for i in range(1, 5)]
    assert failed.state == ev.CONTRACT_FAIL and "score_out_of_range" in failed.contract_violation
    assert score(mf, [failed] + others).outcome == ev.CONTRACT_FAIL
    with pytest.raises(ValueError, match="do_not_equal_the_manifest_items"):
        score(mf, others)  # omission (or "NO_RUN") is not available
    fake = build([dataclasses.replace(mf.m.tracks[0], mavi_track_uuid=None, evidence=())] + list(mf.m.tracks[1:]))
    with pytest.raises(ValueError, match="not_the_frozen_manifest"):
        ev.evaluate_d(fake.m, mf.digest, others, composition=(DET, REC))
    with pytest.raises(ValueError, match="no_mavi_evidence"):
        run(fake, "t0", [])


def test_alias_identity_and_composition_checks():
    mf = population(3)
    runs = runs_for(mf, outputs_of(3, lambda i: [_plate_text(i)]))
    with pytest.raises(ValueError, match="identity_is_not_the_composition"):
        score(mf, runs, composition=(PD_BASE, REC))
    mixed = runs[:2] + [run(mf, "t2", [_plate_text(2)], det=PD_BASE)]
    with pytest.raises(ValueError, match="identity_is_not_the_composition"):
        score(mf, mixed)


# ---------------------------------------------------------------------------------------------- A


SQUARE = ((10, 10), (30, 10), (30, 20), (10, 20))


def _crop_manifest(polygons_by_crop):
    tracks = [T(f"t{i}", f"s{i}", _plate_text(i)) for i in range(len(polygons_by_crop))]
    crops = [ev.ManifestCrop(f"c{i}", f"t{i}", oid(f"t{i}", 0), tuple(polys)) for i, polys in enumerate(polygons_by_crop)]
    return build(tracks, crops=crops)


def detect_runs(mf, detector, det=DET):
    return [ev.run_detection(mf.m, mf.digest, c.crop_id, detector=detector, detector_identity=det, images=images)
            for c in mf.m.crops]


def test_detection_metrics_and_floor():
    mf = _crop_manifest([(SQUARE,), (((0, 0), (10, 0), (10, 10), (0, 10)),)])
    detectors = [Detector([PlateBox(10, 10, 20, 10, 0.9), PlateBox(40, 20, 5, 5, 0.8)]),
                 Detector([PlateBox(0, 0, 10, 10, 0.1)])]
    runs = [ev.run_detection(mf.m, mf.digest, c.crop_id, detector=d, detector_identity=DET, images=images)
            for c, d in zip(mf.m.crops, detectors)]
    result = ev.evaluate_a(mf.m, mf.digest, runs, detector=DET)
    assert (result.outcome, result.plates, result.covered, result.recall) == (ev.MEASURED, 2, 1, Fraction(1, 2))
    assert result.below_floor_proposals == 1 and result.false_plates_per_crop == Fraction(1, 2)
    assert result.layer_digest == ev.layer_digest(mf.m, mf.digest, "A")


@pytest.mark.parametrize("box, code", [
    (PlateBox(10, 10, 20, 10, float("nan")), "score_out_of_range"),  # was "below floor" before review 5
    (PlateBox(10, 10, 20, 10, 1.5), "score_out_of_range"),
    (PlateBox(10.5, 10, 20, 10, 0.9), "box_not_integer"),
    (PlateBox(10, 10, 0, 10, 0.9), "box_degenerate"),
    (PlateBox(50, 10, 20, 10, 0.9), "box_outside_crop"),
    (PlateBox(10, 10, 100000, 10, 0.9), "box_outside_crop"),
    ((10, 10, 20, 10, 0.9), "not_a_platebox"),
])
def test_any_malformed_proposal_is_a_contract_fail_in_a(box, code):
    mf = _crop_manifest([(SQUARE,)])
    result = ev.evaluate_a(mf.m, mf.digest, detect_runs(mf, Detector([box])), detector=DET)
    assert result.outcome == ev.CONTRACT_FAIL and code in result.contract_violations[0]


def test_five_junk_proposals_are_a_contract_fail_not_a_good_score():
    mf = _crop_manifest([(SQUARE,)])
    junk = Detector([PlateBox(x, 0, 10, 10, 0.9) for x in range(0, 50, 10)])
    result = ev.evaluate_a(mf.m, mf.digest, detect_runs(mf, junk), detector=DET)
    assert result.outcome == ev.CONTRACT_FAIL and "exceeds_bound@count=5" in result.contract_violations[0]


def test_a_coverage_is_exact_at_the_threshold():
    wide, short = ((0, 0), (100, 0), (100, 1), (0, 1)), ((0, 0), (20, 0), (20, 1), (0, 1))
    assert ev.coverage(wide, (0, 0, 95, 1)) == Fraction(95, 100)
    assert ev.coverage(short, (0, 0, 19, 1)) == Fraction(19, 20)
    mf = _crop_manifest([(short,)])
    exact = ev.evaluate_a(mf.m, mf.digest, detect_runs(mf, Detector([PlateBox(0, 0, 19, 1, 0.9)])), detector=DET)
    below = ev.evaluate_a(mf.m, mf.digest, detect_runs(mf, Detector([PlateBox(0, 0, 18, 1, 0.9)])), detector=DET)
    assert (exact.covered, below.covered) == (1, 0)


def test_a_population_attacks():
    mf = _crop_manifest([(SQUARE,), (SQUARE,)])
    good = detect_runs(mf, GOOD_BOX)
    bad = ev.run_detection(mf.m, mf.digest, "c0", detector=Detector([PlateBox(1, 1, 20, 10, float("nan"))]),
                           detector_identity=DET, images=images)
    assert ev.evaluate_a(mf.m, mf.digest, [bad, good[1]], detector=DET).outcome == ev.CONTRACT_FAIL
    for attack, code in (([good[1]], "do_not_equal_the_manifest_items"), (good + [good[0]], "duplicate_result"),
                         ([good[1], good[1]], "duplicate_result"),
                         ([dataclasses.replace(good[0], proposals=())] + good[1:], "not_sealed")):
        with pytest.raises(ValueError, match=code):
            ev.evaluate_a(mf.m, mf.digest, attack, detector=DET)
    with pytest.raises(ValueError, match="another_detector"):
        ev.evaluate_a(mf.m, mf.digest, detect_runs(mf, GOOD_BOX, det=PD_BASE), detector=DET)


# ---------------------------------------------------------------------------------------------- B / C


def _plate_manifest(texts, *, b=True, c=False):
    tracks = [T(f"t{i}", f"s{i}", text) for i, text in enumerate(texts)]
    plates = [ev.ManifestPlate(f"p{i}", f"t{i}", text, plate_image(i) if b else None, oid(f"t{i}", 0) if c else None)
              for i, text in enumerate(texts)]
    return build(tracks, plates=plates)


def read_runs(mf, outputs, rec=REC):
    """``outputs`` maps plate id → the recogniser's reading list."""
    return [ev.run_reading(mf.m, mf.digest, pid, recogniser=Outputs([outputs[pid]]), recogniser_identity=rec,
                           images=images) for pid in sorted(outputs)]


def test_reading_rules_follow_pr3_and_any_violation_fails():
    mf = _plate_manifest(["KA01AB1234"])
    assert ev.evaluate_b(mf.m, mf.digest, read_runs(mf, {"p0": R(("KA01AB1234", 0.01))}), recogniser=REC).em == 1
    for readings, code in ((R(("X", 0.5), ("X", 0.5)), "non_strict_rank_order"), (R(("", 0.5)), "invalid_raw_text"),
                           (R(("KA01", 1.5)), "confidence_out_of_range"),
                           (R(("KA01", float("nan"))), "confidence_out_of_range"),
                           ([("KA01", 0.5)], "not_a_reading"),
                           (R(("A", 0.1), ("B", 0.2), ("C", 0.3), ("D", 0.4)), "exceeds_bound")):
        result = ev.evaluate_b(mf.m, mf.digest, read_runs(mf, {"p0": readings}), recogniser=REC)
        assert result.outcome == ev.CONTRACT_FAIL and code in result.contract_violations[0] and result.em is None
    assert ev.diagnostic_plate_record(R(("KA01", 0.2)), 0.5).outcome == "unreadable"
    with pytest.raises(ValueError, match="not_declared"):
        ev.diagnostic_plate_record(R(("KA01", 0.2)), 0.0)


def test_public_ranking_equals_pr3_internal_ranking():
    parameters = ev.ranking_parameters(FLOOR)
    for readings in (R(("KA01", 0.5)), R(("B", 0.2), ("A", 0.2), ("C", 0.9)), R(("KA\n01", 0.3), ("KA01", 0.3)), []):
        assert ev._rank_plate(readings, parameters) == pipeline._plate(0, readings, parameters)
    plate = ev._rank_plate(R(("KA01", 0.5)), parameters)
    assert isinstance(plate, PlateRecord) and isinstance(plate.readings[0], RankedReading)


def test_reading_metrics_and_input_order_invariance():
    mf = _plate_manifest(["KA01AB1234", "KA01AB1234", "KA01AB1234", "a@b", "MH12AB0001"])
    outputs = {"p0": R(("ka01 ab1234", 0.9)), "p1": R(("KA01AB1284", 0.8), ("KA01AB1234", 0.7)), "p2": [],
               "p3": [], "p4": R(("MH12AB0001", 0.8))}
    runs = read_runs(mf, outputs)
    result = ev.evaluate_b(mf.m, mf.digest, runs, recogniser=REC)
    assert (result.plates, result.exact, result.unsupported_truths) == (4, 2, 1)
    assert result.em == Fraction(1, 2) and result.top_k_hit == Fraction(3, 4)
    for seed in range(5):
        shuffled = list(runs)
        random.Random(seed).shuffle(shuffled)
        again = ev.evaluate_b(mf.m, mf.digest, shuffled, recogniser=REC)
        assert (again.ece, again.risk_coverage, again.em) == (result.ece, result.risk_coverage, result.em)
    with pytest.raises(ValueError, match="not_comparable"):  # review 6, P3-3: needs a sealed C and B pair
        ev.c_minus_b(result, result)


def test_b_population_attacks():
    mf = _plate_manifest(["KA01AB1234", "MH12AB0001"])
    runs = read_runs(mf, {"p0": R(("KA01", 2.0)), "p1": R(("MH12AB0001", 0.9))})
    assert ev.evaluate_b(mf.m, mf.digest, runs, recogniser=REC).outcome == ev.CONTRACT_FAIL
    for attack, code in (([runs[1]], "do_not_equal_the_manifest_items"), (runs + [runs[0]], "duplicate_result"),
                         ([dataclasses.replace(runs[0], plate=None, contract_violation=None, state=ev.COMPLETED),
                           runs[1]], "not_sealed")):
        with pytest.raises(ValueError, match=code):
            ev.evaluate_b(mf.m, mf.digest, attack, recogniser=REC)
    honest_silence = read_runs(mf, {"p0": [], "p1": R(("MH12AB0001", 0.9))})
    assert ev.evaluate_b(mf.m, mf.digest, honest_silence, recogniser=REC).outcome == ev.MEASURED
    with pytest.raises(ValueError, match="another_recogniser"):
        ev.evaluate_b(mf.m, mf.digest, read_runs(mf, {"p0": [], "p1": []}, rec=OC5), recogniser=REC)
    assert not hasattr(ev, "not_read") and not hasattr(ev, "ReadItem") and not hasattr(ev, "DetectionItem")
    assert not hasattr(ev, "TrackItem")  # no caller-assembled item can reach a metric


def test_ece_uses_equal_mass_bins():
    rows = [(0.9 - i * 0.01, i % 2 == 0, f"q{i:02d}") for i in range(11)]
    bins = {}
    for k in range(11):
        bins.setdefault(k * ev.ECE_BINS // 11, []).append(k)
    assert len(bins) == 10 and {len(v) for v in bins.values()} == {1, 2}
    expected = sum(len(v) / 11 * abs(sum(rows[k][0] for k in v) / len(v) - sum(rows[k][1] for k in v) / len(v))
                   for v in bins.values())
    assert ev._ece(rows) == pytest.approx(expected, abs=0)


def test_c_comes_only_from_the_composition_runs():
    mf = _plate_manifest(["KA01AB1234", "MH12AB0001"], b=False, c=True)
    good = runs_for(mf, {"t0": ["KA01AB1234"], "t1": ["MH12AB0001"]})
    result = ev.evaluate_c(mf.m, mf.digest, good, composition=(DET, REC))
    assert (result.layer, result.em, result.recogniser) == ("C", 1, REC)
    silent_t1 = [good[0], run(mf, "t1", [""])]
    assert ev.evaluate_c(mf.m, mf.digest, silent_t1, composition=(DET, REC)).em == Fraction(1, 2)
    failed = [good[0], run(mf, "t1", ["MH12AB0001"], n_boxes=3)]
    assert ev.evaluate_c(mf.m, mf.digest, failed, composition=(DET, REC)).outcome == ev.CONTRACT_FAIL
    with pytest.raises(ValueError, match="do_not_equal_the_manifest_items"):
        ev.evaluate_c(mf.m, mf.digest, good[:1], composition=(DET, REC))
    with pytest.raises(ValueError, match="component_read_result_not_layer_b"):
        ev.recogniser_component(True, result)


# ---------------------------------------------------------------------------------------------- D


def test_d_score_on_a_closed_population_exactly():
    mf = build([T("t1", "s1", "KA01AB1234"), T("t2", "s1", "MH12CD5678", n=2), T("t3", "s2", ev.NO_PLATE),
                T("t5", "s2", ev.NO_GT_VEHICLE), T("t4", "s2", "DL3CAB0001", n=0)])
    runs = runs_for(mf, {"t1": ["KA01AB1234"], "t2": ["MH12CD5670", "MH12CD5670"], "t3": ["KA01ZZ9999"],
                         "t5": ["DL3CAB0002"]})
    queries = ev.queries_for(mf.m, mf.digest)
    result = score(mf, runs)
    assert result.outcome == ev.MEASURED and result.counts.exact_denominator == 3
    assert result.exact_recall == Fraction(1, 3)
    contains = [m for m in queries.metric_queries if m.match == q.CONTAINS]
    reads = {"t1": ("KA01AB1234", "KA01AB1234"), "t2": ("MH12CD5670", "MH12CD5678"), "t3": ("KA01ZZ9999", None),
             "t5": ("DL3CAB0002", None)}
    returned = [(t, m.text) for t, (text, _) in reads.items() for m in contains if m.text in text]
    correct = [(t, x) for t, x in returned
               if reads[t][1] is not None and x in reads[t][1] and not dict((m.text, m) for m in contains)[x].negative_only]
    assert result.counts.returned_pairs == len(returned) > 0
    assert result.contains_precision == Fraction(len(correct), len(returned))
    assert result.d_score == (result.exact_recall + result.contains_recall + result.contains_precision) / 3
    assert result.counts.consistent_wrong == 1 and result.counts.multi_source == 1
    assert result.consistent_wrong_status == ev.INSUFFICIENT
    assert result.accounting["no-gt-vehicle"] == 1 and result.accounting["no-plate"] == 1
    assert (result.manifest_digest, result.query_set_sha256) == (mf.digest, queries.query_set_sha256)


def test_unsupported_truth_stays_and_cannot_improve_precision():
    plain = build([T("p", "s1", "KA01AB1234")])
    both = build([T("p", "s1", "KA01AB1234"), T("u", "s2", "KA01AB12३४")])
    without = score(plain, runs_for(plain, {"p": ["KA01AB1234"]}))
    with_unsupported = score(both, runs_for(both, {"p": ["KA01AB1234"], "u": ["KA01AB1234"]}))
    assert with_unsupported.accounting["unsupported"] == 1
    assert with_unsupported.counts.exact_denominator == without.counts.exact_denominator
    assert with_unsupported.counts.positive_pairs == without.counts.positive_pairs
    assert with_unsupported.counts.returned_pairs > without.counts.returned_pairs
    assert with_unsupported.counts.correct_returned == without.counts.correct_returned
    assert with_unsupported.contains_precision < without.contains_precision


def test_unreadable_is_accounted_not_silent():
    mf = build([T("p", "s1", "KA01AB1234"), T("r", "s1", ev.UNREADABLE)])
    result = score(mf, runs_for(mf, {"p": ["KA01AB1234"], "r": ["KA01AB1234"]}))
    assert result.accounting["unreadable"] == 1 and result.counts.unreadable_returned_pairs > 0
    assert result.contains_precision == 1


def test_contract_violation_fails_the_whole_composition_and_publishes_no_terms():
    mf = build([T("t1", "s1", "KA01AB1234"), T("t2", "s2", "MH12AB0001")])
    runs = [run(mf, "t1", ["KA01AB1234"]), run(mf, "t2", ["MH12AB0001"], n_boxes=3)]
    result = score(mf, runs)
    assert (result.outcome, result.d_status, result.d_score) == (ev.CONTRACT_FAIL, ev.CONTRACT_FAIL, None)
    assert result.contract_violations[0].startswith("plate_detector_output_exceeds_bound@count=3:obs=")
    assert result.contract_violations[0].endswith(":t2")
    assert (result.exact_recall, result.contains_recall, result.contains_precision, result.consistent_wrong_rate,
            result.consistent_wrong_conditional_rate, result.conflicting_rate, result.no_text_rate) == (None,) * 7
    assert result.counts == ev.TrackCounts() and result.consistent_wrong_status == ev.FAIL
    base = score(mf, runs_for(mf, {"t1": ["KA01AB1234"], "t2": ["MH12AB0001"]}))
    assert gate(mf, C("PD2-S", "OC1-XS", result), C("PD2-N", "OC5-BEST", base)) == ev.FAIL
    with pytest.raises(ev.BaselineStop, match="baseline_contract_violation"):
        gate(mf, C("PD2-S", "OC1-XS", base), C("PD2-N", "OC5-BEST", result))


class _OutOfBounds:
    def detect(self, crop, verified):
        return [PlateBox(0, 0, 500, 500, 0.9)]


class _NaNScore:
    def detect(self, crop, verified):
        return [PlateBox(1, 1, 20, 10, float("nan"))]


class _NotABox:
    def detect(self, crop, verified):
        return [(1, 1, 20, 10, 0.9)]


class _FloatBox:
    def detect(self, crop, verified):
        return [PlateBox(1.5, 1, 20, 10, 0.9)]


class _Crash:
    def detect(self, crop, verified):
        raise RuntimeError("model fault")


class _CrashOcr:
    def read(self, region, verified, box):
        raise MemoryError("ocr fault")


def _fresh(recogniser):
    """The parametrised recogniser fixtures are consumed by one run; rebuild an equivalent one."""
    if isinstance(recogniser, Outputs):
        return Outputs(list(recogniser.initial))
    if isinstance(recogniser, Recogniser):
        return Recogniser(list(recogniser.initial))
    return recogniser


@pytest.mark.parametrize("detector, recogniser, code", [
    (_OutOfBounds(), Recogniser(["KA01AB1234"]), "box_outside_crop"),
    (_NaNScore(), Recogniser(["KA01AB1234"]), "score_out_of_range"),
    (_NotABox(), Recogniser(["KA01AB1234"]), "not_a_platebox"),
    (_FloatBox(), Recogniser(["KA01AB1234"]), "box_not_integer"),
    (_Crash(), Recogniser([]), "plate_detector_runtime_error"),
    (GOOD_BOX, Outputs([R(("KA01", 1.5))]), "confidence_out_of_range"),
    (GOOD_BOX, Outputs([R(("", 0.5))]), "invalid_raw_text"),
    (GOOD_BOX, Outputs([R(("KA01", 0.5), ("KA01", 0.5))]), "non_strict_rank_order"),
    (GOOD_BOX, Outputs([["KA01"]]), "not_a_reading"),
    (GOOD_BOX, _CrashOcr(), "plate_recogniser_runtime_error"),
])
def test_any_output_contract_violation_is_a_hard_fail_in_d_and_c(detector, recogniser, code):
    mf = _plate_manifest(["KA01AB1234"], b=False, c=True)
    result = run(mf, "t0", detector=detector, recogniser=recogniser)
    assert result.state == ev.CONTRACT_FAIL and result.record is None and code in result.contract_violation
    assert f"obs={oid('t0', 0)}" in result.contract_violation
    assert ev.evaluate_c(mf.m, mf.digest, [result], composition=(DET, REC)).outcome == ev.CONTRACT_FAIL
    d_mf = build([T("t0", "s0", "KA01AB1234")])
    d = score(d_mf, [run(d_mf, "t0", detector=detector, recogniser=_fresh(recogniser))])
    assert (d.outcome, d.d_score) == (ev.CONTRACT_FAIL, None)


def test_product_abstains_where_the_bake_off_fails():
    mf = build([T("p", "s", "KA01AB1234")])
    ref = mf.m.tracks[0].evidence[0]
    observation = ev.lease_observation(uuid.UUID(ref.observation_id), "near-view", 0, len(JPEG), SHA)
    verified = VerifiedCrop(ref.observation_id, "near-view", 0, SHA, JPEG)
    duplicate = R(("KA01", 0.5), ("KA01", 0.5))
    product = pipeline.analyse_crop(observation, verified, GOOD_BOX, Outputs([duplicate]), ev.ranking_parameters(FLOOR))
    assert (product.status, product.reason) == ("abstained", "ocr_output_invalid")
    assert "non_strict_rank_order" in run(mf, "p", recogniser=Outputs([duplicate])).contract_violation


def test_diagnostic_floor_is_a_separate_type():
    mf = population(1)
    runs = runs_for(mf, outputs_of(1, lambda i: [_plate_text(i)]))
    diagnostic = ev.diagnostic_evaluate_d_at_floor(mf.m, mf.digest, runs, 0.5, composition=(DET, REC))
    assert isinstance(diagnostic, ev.DiagnosticTrackScore) and diagnostic.values.accounting["diagnosticFloor"] == 0.5
    with pytest.raises(ValueError, match="not_declared"):
        ev.diagnostic_evaluate_d_at_floor(mf.m, mf.digest, runs, 0.0, composition=(DET, REC))


def test_gates_and_decisions_refuse_diagnostic_and_forged_scores():
    mf = population(3)
    ranked = runs_for(mf, outputs_of(3, lambda i: [_plate_text(i)]))
    silent = score(mf, runs_for(mf, outputs_of(3, lambda i: [""])))
    diag = ev.diagnostic_evaluate_d_at_floor(mf.m, mf.digest, ranked, 0.7, composition=(DET, REC))
    freeze = baseline_for(mf.digest)[0]
    for forged in (diag, diag.values, dataclasses.replace(silent, d_score=Fraction(1))):
        with pytest.raises(ValueError, match="not_a_ranking_d_score"):
            gate(mf, C("PD2-S", "OC1", silent), C("PD2-N", "OC5-BEST", forged))
        with pytest.raises(ValueError, match="not_a_ranking_d_score"):
            gate(mf, C("PD2-S", "OC1", forged), C("PD2-N", "OC5-BEST", silent))
        with pytest.raises(ValueError, match="not_a_ranking_d_score"):
            ev.diagnostic_ocr_uplift(C("PD2-S", "OC1", forged), C("PD2-S", "OC5-BEST", silent), freeze)
    forged_floor = dataclasses.replace(ranked[0], parameters=ev.ranking_parameters(0.1))
    with pytest.raises(ValueError, match="not_sealed"):
        score(mf, [forged_floor] + ranked[1:])
    with pytest.raises(ValueError, match="not_from_ranking_path"):
        TOPK([ev.ComponentScore("OC2-A", True, 100, 0.9, 0.1, 0.1, False, _h("OC2-A"), "recogniser", mf.digest,
                                 _h("m"))], "recogniser", freeze)


def test_silent_baseline_and_corpus_deficiency():
    mf = population(3)
    silent = score(mf, runs_for(mf, outputs_of(3, lambda i: [""])))
    good = score(mf, runs_for(mf, outputs_of(3, lambda i: [_plate_text(i)])))
    assert gate(mf, C("PD2-N", "OC1-XS", good), C("PD2-N", "OC5-BEST", silent)) == ev.PASS
    deficient_mf = build([T("n", "s1", ev.NO_PLATE)])
    deficient = score(deficient_mf, runs_for(deficient_mf, {"n": ["KA01AB1234"]}))
    assert deficient.d_status == ev.INSUFFICIENT and deficient.d_score is None
    bound = with_d(deficient, None, manifest_digest=mf.digest, query_set_sha256=silent.query_set_sha256)
    assert gate(mf, C("PD2-N", "OC1-XS", bound), C("PD2-N", "OC5-BEST", silent)) == ev.INSUFFICIENT
    with pytest.raises(ev.BaselineStop, match="baseline_not_evaluable"):
        gate(mf, C("PD2-N", "OC1-XS", good), C("PD2-N", "OC5-BEST", with_d(good, None)))
    with pytest.raises(ValueError, match="same_population_and_query_set"):
        gate(mf, C("PD2-N", "OC1-XS", deficient), C("PD2-N", "OC5-BEST", silent))


def test_mpid_boundary_is_exact_and_pinned():
    mf = population(1)
    base = score(mf, runs_for(mf, outputs_of(1, lambda i: [_plate_text(i)])))

    def check(high, low, detector="PD2-S", **kwargs):
        return gate(mf, C(detector, "OC1-XS", with_d(base, high)), C("PD2-N", "OC5-BEST", with_d(base, low)), **kwargs)

    assert 0.47 - 0.43 < 0.04
    assert check(Fraction(47, 100), Fraction(43, 100)) == ev.PASS
    assert check(Fraction(4, 100), Fraction(0)) == ev.PASS
    assert check(Fraction(399, 10000), Fraction(0)) == ev.FAIL
    assert check(Fraction(1, 3) + Fraction(4, 100), Fraction(1, 3)) == ev.PASS
    assert check(Fraction(4, 100), Fraction(0), detector="PD1-X") == ev.PASS
    for mpid in (0.04, Fraction(3, 100)):
        with pytest.raises(ValueError, match="frozen_fraction"):
            check(Fraction(47, 100), Fraction(43, 100), mpid=mpid)
    with pytest.raises(ValueError, match="sealed_pd_base"):
        gate(mf, C("PD2-S", "OC1-XS", base), C("PD2-S", "OC5-BEST", base))
    with pytest.raises(ValueError, match="sealed_pd_base"):
        gate(mf, C("PD2-S", "OC1-XS", base), C("PD2-N", "OC2-V6S", base))


# ---------------------------------------------------------------------------------------------- baseline resolution


FIXED = "a" * 64


def test_pd_base_resolves_mechanically_from_the_frozen_rule():
    freeze, layer_a, resolution = baseline_for(FIXED)
    assert resolution.pd_base_id == "PD2-N"
    assert resolution.pd_base_identity_sha256 == _h("PD2-N")
    assert resolution.layer_a_result_sha256 == ev.layer_a_result_sha256(freeze, layer_a)
    assert resolution.d_state == ev.D_NOT_STARTED and resolution.resolved_at_utc == WHEN
    assert ev.resolve_baseline(freeze, list(reversed(layer_a)), d_rows_read=0, resolved_at_utc=WHEN) == resolution
    ev.verify_resolution(freeze, resolution, layer_a)
    tied = {"PD1-X": (0.9, 0.1, 0.9), "PD2-N": (0.9, 0.1, 0.9), "PD2-S": (0.9, 0.1, 0.9)}
    with pytest.raises(ev.BaselineStop, match="layer_a_rank_ambiguous"):
        ev.resolve_baseline(freeze, layer_a_for(FIXED, ("PD2-S", "PD2-N"), tied), d_rows_read=0, resolved_at_utc=WHEN)
    second = {"PD1-X": (0.9, 0.1, 0.9), "PD2-N": (0.9, 0.2, 0.99), "PD2-S": (0.9, 0.1, 0.5)}
    assert ev.resolve_baseline(freeze, layer_a_for(FIXED, ("PD2-S", "PD2-N"), second), d_rows_read=0,
                               resolved_at_utc=WHEN).pd_base_id == "PD2-S"
    missing = {"PD1-X": (0.9, 0.1, 0.9), "PD2-N": (None, 0.0, 0.99), "PD2-S": (0.1, 0.9, 0.1)}
    assert ev.resolve_baseline(freeze, layer_a_for(FIXED, ("PD2-S", "PD2-N"), missing), d_rows_read=0,
                               resolved_at_utc=WHEN).pd_base_id == "PD2-S"


def test_layer_a_artefact_is_canonical_and_m3_shaped():
    freeze, layer_a, resolution = baseline_for(FIXED)
    document = ev.layer_a_result_document(freeze, layer_a)
    assert document["evidenceSha256"] == FIXED
    assert [r["candidateId"] for r in document["results"]] == ["PD1-X", "PD2-N", "PD2-S"]
    assert set(document["results"][0]) == {"candidateId", "identitySha256", "gates", "rankKey", "measurementSha256"}
    assert resolution.layer_a_result_sha256 == ev._canonical_sha256(document)


def test_pd_base_resolution_stops_and_never_chooses():
    freeze = baseline_for(FIXED)[0]

    def stop(reason, results, **kw):
        with pytest.raises(ev.BaselineStop, match=reason):
            ev.resolve_baseline(freeze, results, d_rows_read=kw.get("d_rows_read", 0),
                                resolved_at_utc=kw.get("when", WHEN))

    stop("no_detector_passed_layer_a", layer_a_for(FIXED, passed=()))
    stop("after_d_data_read", layer_a_for(FIXED), d_rows_read=1)
    stop("before_freeze", layer_a_for(FIXED), when="2026-09-30T23:59:59Z")
    stop("time_malformed", layer_a_for(FIXED), when="2026-10-14 00:00")
    outsider = layer_a_for(FIXED) + [ev.LayerAResult(comp(FIXED, "PD9-NEW", True, 100, 1.0, 0.0, 1.0), _h("PD9-NEW"),
                                                     True)]
    stop("inconsistent_with_frozen_detector_universe", outsider)
    stop("inconsistent_with_frozen_detector_universe", layer_a_for(FIXED)[1:])
    stop("ambiguous_duplicate_detector", layer_a_for(FIXED) + layer_a_for(FIXED)[1:2])
    stop("identity_mismatch:PD2-N", layer_a_for(FIXED, identities={"PD2-N": _h("PD2-N-retrained")}))
    failed = layer_a_for(FIXED)
    failed[1] = dataclasses.replace(failed[1], score=comp(FIXED, "PD2-N", True, 100, 0.95, 0.1, 0.9, contract_fail=True))
    stop("gate_pass_with_contract_fail:PD2-N", failed)
    stop("non_finite_metric:PD2-N", layer_a_for(FIXED, metrics={"PD1-X": (0.9, 0.1, 0.9),
                                                                "PD2-N": (float("nan"), 0.1, 0.9),
                                                                "PD2-S": (0.9, 0.1, 0.9)}))
    other_manifest = layer_a_for(FIXED)
    other_manifest[1] = dataclasses.replace(other_manifest[1], score=comp("b" * 64, "PD2-N", True, 100, 0.95, 0.1, 0.9))
    stop("not_on_the_frozen_manifest:PD2-N", other_manifest)
    recogniser_kind = layer_a_for(FIXED)
    recogniser_kind[1] = dataclasses.replace(recogniser_kind[1], score=comp(FIXED, "PD2-N", True, 100, 0.95, 0.1, 0.9,
                                                                            kind="recogniser"))
    stop("not_a_detector_result:PD2-N", recogniser_kind)
    with pytest.raises(ValueError, match="benchmark_only_component_cannot_be_a_detector_candidate"):
        freeze_for(FIXED, eligible_detectors=(("OC5-BEST", _h("x")), ("PD2-N", _h("PD2-N"))))
    with pytest.raises(ValueError, match="ranking_rule_not_the_frozen_rule"):
        freeze_for(FIXED, ranking_rule_sha256=_h("another rule"))
    with pytest.raises(ValueError, match="sorted_unique_nonempty"):
        freeze_for(FIXED, eligible_detectors=())
    with pytest.raises(ValueError, match="time_malformed"):
        freeze_for(FIXED, frozen_at_utc="yesterday")


def test_sealed_resolution_cannot_change_or_be_forged_and_oc5_is_never_rankable():
    mf = population(1)
    base = score(mf, runs_for(mf, outputs_of(1, lambda i: [_plate_text(i)])))
    freeze, layer_a, resolution = baseline_for(mf.digest)
    swapped = dataclasses.replace(resolution, pd_base_id="PD2-S")
    with pytest.raises(ev.BaselineStop, match="record_altered"):
        gate(mf, C("PD2-S", "OC1-XS", base), C("PD2-S", "OC5-BEST", base), resolution=swapped)
    forged = dataclasses.replace(resolution, pd_base_id="PD1-X")
    forged = dataclasses.replace(forged, record_sha256=ev._canonical_sha256(forged.payload()))
    with pytest.raises(ev.BaselineStop, match="differs_from_frozen_derivation"):
        gate(mf, C("PD2-S", "OC1-XS", base), C("PD1-X", "OC5-BEST", base), resolution=forged)
    other = ev.resolve_baseline(freeze, layer_a_for(mf.digest, passed=("PD2-S",)), d_rows_read=0, resolved_at_utc=WHEN)
    with pytest.raises(ev.BaselineStop, match="changed_after_seal"):
        ev.assert_resolution_unchanged(resolution, other)
    late = dataclasses.replace(resolution, d_state="D_STARTED")
    late = dataclasses.replace(late, record_sha256=ev._canonical_sha256(late.payload()))
    with pytest.raises(ev.BaselineStop, match="not_sealed_before_d"):
        ev.verify_resolution(freeze, late, layer_a)
    baseline = C("PD2-N", "OC5-BEST", with_d(base, Fraction(1, 2)))
    passing = C("PD2-S", "OC1-XS", with_d(base, Fraction(9, 10)))
    failing = C("PD1-X", "OC2-V6S", with_d(base, Fraction(1, 2)))
    assert ev.rankable_compositions([passing, failing], baseline, resolution, freeze, layer_a) == [passing]
    for bad in (C("PD2-N", "OC5-BEST", base), C("PD2-S", "OC5-BEST", base)):
        with pytest.raises(ValueError, match="cannot_be_ranked"):
            ev.rankable_compositions([passing, bad], baseline, resolution, freeze, layer_a)


def test_composition_identity_is_sealed_through_the_real_path():
    mf = population(3)
    pd1x = ident("PD1-X")
    s_oc5 = score(mf, runs_for(mf, outputs_of(3, lambda i: [_plate_text(i)]), det=pd1x, rec=OC5), (pd1x, OC5))
    s_base = score(mf, runs_for(mf, outputs_of(3, lambda i: [""]), det=PD_BASE, rec=OC5), (PD_BASE, OC5))
    s_ord = score(mf, runs_for(mf, outputs_of(3, lambda i: [_plate_text(i)])))
    freeze, layer_a, resolution = baseline_for(mf.digest)
    composition, baseline = ev.CompositionScore(s_oc5), ev.CompositionScore(s_base)
    assert (composition.detector_id, composition.recogniser_id) == ("PD1-X", "OC5-BEST")
    with pytest.raises(ValueError, match="cannot_be_ranked"):
        ev.rankable_compositions([composition], baseline, resolution, freeze, layer_a)
    with pytest.raises(ValueError, match="not_a_ranking_d_score"):
        ev.rankable_compositions([ev.CompositionScore(dataclasses.replace(s_oc5, recogniser=ident("OC2-A")))],
                                 baseline, resolution, freeze, layer_a)
    with pytest.raises(ValueError, match="sealed_pd_base"):
        gate(mf, ev.CompositionScore(s_ord), ev.CompositionScore(s_ord))
    with pytest.raises(ValueError, match="sealed_pd_base"):
        gate(mf, ev.CompositionScore(s_ord), composition)
    assert gate(mf, ev.CompositionScore(s_ord), baseline) == ev.PASS
    vector = "fb6fffc212d8de2f3c6d67af7ff5c7186c633fd28bf1936d1d4e393c1753d8d3"  # M3 baseline_seal @ f24dcf5e
    assert ev.m3_composition_sha256(*EVENTS[:2], OC5, EVENTS[2], PD_BASE) == vector == resolution.composition_sha256


def test_benchmark_only_component_never_enters_top_k():
    mf = _plate_manifest([_plate_text(i) for i in range(60)])
    freeze = freeze_for(mf.digest, eligible_recognisers=(("OC1-XS", _h("OC1-XS")),))

    def component(who):
        runs = read_runs(mf, {f"p{i}": R((_plate_text(i), 0.9)) for i in range(60)}, rec=who)
        return ev.recogniser_component(True, ev.evaluate_b(mf.m, mf.digest, runs, recogniser=who))

    for who in (ev.ComponentIdentity("OC9-ALIAS", OC5.identity_sha256), OC5):
        with pytest.raises(ValueError, match="cannot_enter_top_k"):
            TOPK([component(who)], "recogniser", freeze)
    ordinary = component(REC)
    assert TOPK([ordinary], "recogniser", freeze) == ["OC1-XS"]
    with pytest.raises(ValueError, match="another_kind"):
        TOPK([ordinary], "detector", freeze)
    with pytest.raises(ValueError, match="freeze_is_for_another_manifest"):
        TOPK([ordinary], "recogniser", freeze_for(FIXED), mf)
    with pytest.raises(ValueError, match="requires_the_baseline_freeze"):
        TOPK([ordinary], "recogniser", None, mf)


def test_top_k_is_deterministic_and_excludes_failures():
    real = ab_digest(population(1).digest)
    detectors = ("PD2-M", "PD2-N", "PD2-S", "PD5-V5M", "PD5-V6S", "PD9-X")
    freeze = freeze_for(real, eligible_detectors=tuple((d, _h(d)) for d in detectors),
                        eligible_recognisers=tuple((r, _h(r)) for r in ("OC2-A", "OC2-B")))
    scores = [comp(real, "PD2-S", True, 100, 0.9, 0.1, 0.8), comp(real, "PD2-N", True, 100, 0.9, 0.1, 0.9),
              comp(real, "PD5-V5M", False, 100, 0.99, 0.0, 0.99), comp(real, "PD2-M", True, 10, 1, 0, 1),
              comp(real, "PD5-V6S", True, 100, None, None, None),
              comp(real, "PD9-X", True, 100, 1.0, 0.0, 1.0, contract_fail=True)]
    assert TOPK(scores, "detector", freeze) == ["PD2-N", "PD2-S", "PD5-V6S"]
    ocr = [comp(real, "OC2-B", True, 60, 0.8, 0.1, 0.2, kind="recogniser"),
           comp(real, "OC2-A", True, 60, 0.8, 0.1, None, kind="recogniser")]
    with pytest.raises(ValueError, match="duplicate_candidate"):  # review 6, P3-4
        TOPK([ocr[0], ocr[0]], "recogniser", freeze)
    assert TOPK(ocr, "recogniser", freeze) == ["OC2-B", "OC2-A"]
    mf = _crop_manifest([(((1, 1), (21, 1), (21, 11), (1, 11)),)])
    built = ev.detector_component(True, ev.evaluate_a(mf.m, mf.digest, detect_runs(mf, GOOD_BOX), detector=DET))
    assert (built.candidate_id, built.primary, built.kind, built.manifest_digest) == ("PD2-S", 1.0, "detector",
                                                                                     mf.digest)


def test_detector_matched_tesseract_is_diagnostic_only():
    mf = population(1)
    base = score(mf, runs_for(mf, outputs_of(1, lambda i: [_plate_text(i)])))
    freeze = baseline_for(mf.digest)[0]
    high = C("PD2-S", "OC1-XS", with_d(base, Fraction(1, 2)))
    matched = C("PD2-S", "OC5-BEST", with_d(base, Fraction(1, 5)))
    assert ev.diagnostic_ocr_uplift(high, matched, freeze) == Fraction(3, 10)
    with pytest.raises(ValueError, match="not_detector_matched"):
        ev.diagnostic_ocr_uplift(high, C("PD2-N", "OC5-BEST", base), freeze)
    failed = C("PD2-S", "OC5-BEST", with_d(base, None, outcome=ev.CONTRACT_FAIL))
    assert ev.diagnostic_ocr_uplift(high, failed, freeze) is None
    other = population(2)
    elsewhere = score(other, runs_for(other, outputs_of(2, lambda i: [""])))
    with pytest.raises(ValueError, match="same_population"):
        ev.diagnostic_ocr_uplift(high, C("PD2-S", "OC5-BEST", elsewhere), freeze)


# ---------------------------------------------------------------------------------------------- N3 (owner 2026-10-14)


WRONG, RIGHT = "KA01AB1235", "KA01AB1234"


def _n3(*outputs_per_track):
    tracks = [T(f"n{i}", "s", RIGHT, n=len(outputs)) for i, outputs in enumerate(outputs_per_track)]
    mf = build(tracks)
    runs = [run(mf, t.track_id, recogniser=Outputs(outputs), detector=GOOD_BOX)
            for t, outputs in zip(tracks, outputs_per_track)]
    return score(mf, runs).counts


def test_n3_uses_rank0_only_probe2_alternates_case():
    a = _n3([R((WRONG, 0.9)), R((WRONG, 0.9))])
    b = _n3([R((WRONG, 0.9), ("KA01AB1299", 0.1)), R((WRONG, 0.9), ("KA01AB1288", 0.1))])
    assert (a.consistent_wrong, b.consistent_wrong) == (1, 1)


def test_n3_owner_edge_semantics():
    assert _n3([R((WRONG, 0.9), ("KA01AB1299", 0.2), ("KA01AB1277", 0.1)), R((WRONG, 0.9), ("KA01AB1288", 0.1))]
               ).consistent_wrong == 1
    assert _n3([R((WRONG, 0.9), (RIGHT, 0.5)), R((WRONG, 0.9), (RIGHT, 0.5))]).consistent_wrong == 1
    assert _n3([R((WRONG, 0.9)), R((RIGHT, 0.9)), R((WRONG, 0.9))]).consistent_wrong == 0
    conflicting = _n3([R((WRONG, 0.9)), R(("KA01AB1236", 0.9))])
    assert (conflicting.consistent_wrong, conflicting.multi_source, conflicting.conflicting) == (0, 1, 1)
    single = _n3([R((WRONG, 0.9)), []])
    assert (single.consistent_wrong, single.multi_source) == (0, 0)
    unnormalisable = _n3([R((WRONG, 0.9)), R(("@@", 0.9), (WRONG, 0.5))])
    assert (unnormalisable.consistent_wrong, unnormalisable.multi_source) == (0, 0)
    assert _n3([R((WRONG, 0.9)), R((WRONG, 0.9)), R(("KA01AB1236", 0.9))]).consistent_wrong == 0
    assert _n3([R((WRONG, 0.9)), R((WRONG, 0.9)), R((WRONG, 0.8))]).consistent_wrong == 1
    assert _n3([R((WRONG, 0.9)), R((WRONG, 0.9)), R(("KA01-AB/1234!", 0.9))]).consistent_wrong == 1


def test_n3_denominators_are_unchanged():
    tracks = [T("w", "s", RIGHT, n=2), T("one", "s", RIGHT), T("ok", "s", RIGHT, n=2), T("none", "s", RIGHT, n=0),
              T("np", "s", ev.NO_PLATE, n=2)]
    mf = build(tracks)
    outputs = {"w": [R((WRONG, 0.9))] * 2, "one": [R((WRONG, 0.9))], "ok": [R((RIGHT, 0.9))] * 2,
               "np": [R((WRONG, 0.9))] * 2}
    runs = [run(mf, tid, recogniser=Outputs(out), detector=GOOD_BOX) for tid, out in outputs.items()]
    result = score(mf, runs)
    assert result.consistent_wrong_rate == Fraction(1, 4)
    assert result.consistent_wrong_conditional_rate == Fraction(1, 2)
    assert result.consistent_wrong_status == ev.INSUFFICIENT


# ---------------------------------------------------------------------------------------------- comparison


@pytest.fixture(scope="module")
def pair():
    mf = population(70)
    good = runs_for(mf, outputs_of(70, lambda i: [_plate_text(i)]))
    silent = runs_for(mf, outputs_of(70, lambda i: [""]))
    half = runs_for(mf, outputs_of(70, lambda i: [_plate_text(i) if i % 2 else ""]))
    near = runs_for(mf, outputs_of(70, lambda i: [_plate_text(i) if i % 25 else ""]))
    return mf, good, silent, half, near


def test_superiority_rule_and_determinism(pair):
    mf, good, silent, half, near = pair
    first = compare(mf, good, silent)
    assert first.outcome == "superior" and first.difference == 1 and first.lower > 0
    assert first == compare(mf, good, silent)
    assert first.cluster_signs == {"a": 70, "b": 0, "tie": 0, "insufficient": 0}
    assert compare(mf, good, half).outcome == "superior"
    small = compare(mf, good, near)
    assert small.difference < ev.MPID and small.outcome == "not-superior"
    assert compare(mf, good, good).outcome == "not-superior"
    with pytest.raises(ValueError, match="frozen_fraction"):
        compare(mf, good, silent, mpid=0.04)


def test_interval_must_exclude_zero_even_above_mpid():
    mf = population(70, sites=lambda i: "siteA" if i < 10 else f"site{i}")
    a = runs_for(mf, outputs_of(70, lambda i: [_plate_text(i)]))
    b = runs_for(mf, outputs_of(70, lambda i: ["" if i < 10 else _plate_text(i)]))
    result = compare(mf, a, b)
    assert result.difference >= ev.MPID
    assert result.lower <= 0 and result.outcome == "not-superior"


def test_percentile_indices_are_exact_integers():
    for r in range(1, 20001):
        assert ev.percentile_indices(r) == (math.floor(Fraction(25, 1000) * (r - 1)),
                                            math.ceil(Fraction(975, 1000) * (r - 1)))


def test_fast_bootstrap_equals_re_evaluation(pair):
    mf, good, _, half, _ = pair
    kwargs = dict(composition_a=(DET, REC), composition_b=(DET, REC), replicates=15, seed=11)
    assert ev._bootstrap_replicates(mf.m, mf.digest, good, half, **kwargs) == \
        ev._bootstrap_replicates(mf.m, mf.digest, good, half, slow=True, **kwargs)


def test_fast_bootstrap_on_multi_track_sites_equals_independent_evaluation():
    truths = ["KA01AB1234", "MH12CD5678"]
    tracks, out_a, out_b = [], {}, {}
    for site in range(6):
        for k, truth in enumerate(truths + truths[:1]):
            tid = f"s{site}t{k}"
            tracks.append(T(tid, f"site{site}", truth))
            out_a[tid] = [truth if (site + k) % 3 else "KA01AB1235"]
            out_b[tid] = [truth if (site + k) % 2 else ""]
    mf = build(tracks)
    a, b = runs_for(mf, out_a), runs_for(mf, out_b)
    kwargs = dict(composition_a=(DET, REC), composition_b=(DET, REC), replicates=40, seed=5)
    fast = ev._bootstrap_replicates(mf.m, mf.digest, a, b, **kwargs)
    assert fast == ev._bootstrap_replicates(mf.m, mf.digest, a, b, slow=True, **kwargs)
    # Independent re-run: rebuild each replicate's population as its own manifest and score it with evaluate_d.
    ordered = sorted(tracks, key=lambda t: t.track_id)
    members: dict[str, list[int]] = {}
    for index, t in enumerate(ordered):
        members.setdefault(t.site, []).append(index)
    names = sorted(members)
    rng = random.Random(5)
    checked = 0
    for value in fast:
        picked = ev._draws(rng, members, names)
        if {ordered[i].truth.text for i in picked} != set(truths):
            continue
        sub_tracks = [T(f"{ordered[i].track_id}x{n}", ordered[i].site, ordered[i].truth) for n, i in enumerate(picked)]
        sub = build(sub_tracks)
        ra = [run(sub, t.track_id, out_a[t.track_id.split("x")[0]]) for t in sub_tracks]
        rb = [run(sub, t.track_id, out_b[t.track_id.split("x")[0]]) for t in sub_tracks]
        assert score(sub, ra).d_score - score(sub, rb).d_score == value
        checked += 1
    assert checked >= 20


def test_comparison_refusals_and_no_silent_drops(pair):
    mf, good, silent, _, _ = pair
    with pytest.raises(ValueError, match="do_not_equal_the_manifest_items"):
        compare(mf, good, silent[1:])
    assert ev._bootstrap_replicates(mf.m, mf.digest, good, silent, composition_a=(DET, REC), composition_b=(DET, REC),
                                    replicates=50, seed=1).count(None) == 0
    violating = [run(mf, "t0", [_plate_text(0)], n_boxes=3)] + good[1:]
    assert compare(mf, violating, silent).outcome == "contract-fail"
    with pytest.raises(ValueError, match="contract_violating_run"):
        ev._bootstrap_replicates(mf.m, mf.digest, violating, silent, composition_a=(DET, REC),
                                 composition_b=(DET, REC), replicates=5, seed=1)
    pd1x, alias = ident("PD1-X"), ev.ComponentIdentity("OC9-ALIAS", OC5.identity_sha256)
    oc5_runs = runs_for(mf, outputs_of(70, lambda i: [_plate_text(i)]), det=pd1x, rec=alias)
    with pytest.raises(ValueError, match="cannot_be_ranked"):
        compare(mf, oc5_runs, silent, composition_a=(pd1x, alias))


def test_comparison_config_is_the_frozen_one(pair):
    mf, good, silent, _, _ = pair
    assert ev.BOOTSTRAP_REPLICATES == 1000 and mf.m.config.bootstrap_replicates == 1000
    other = build(mf.m.tracks, config=dataclasses.replace(CONFIG, bootstrap_seed=3))  # seed substitution
    freeze, layer_a, resolution = baseline_for(mf.digest)
    with pytest.raises(ValueError, match="freeze_is_for_another_manifest"):
        ev.paired_cluster_bootstrap(other.m, other.digest, good, silent, composition_a=(DET, REC),
                                    composition_b=(DET, REC), freeze=freeze, resolution=resolution,
                                    layer_a_results=layer_a)
    with pytest.raises(ev.BaselineStop, match="not_on_the_frozen_manifest"):  # another freeze, another seed
        compare(mf, good, silent, freeze=freeze_for(other.digest))
    other_freeze, other_la, other_res = baseline_for(other.digest)
    with pytest.raises(ValueError, match="freeze_is_for_another_manifest"):
        compare(mf, good, silent, freeze=other_freeze, resolution=other_res, layer_a_results=other_la)
    with pytest.raises(ValueError, match="result_of_another_manifest"):
        ev.paired_cluster_bootstrap(other.m, other.digest, good, silent, composition_a=(DET, REC),
                                    composition_b=(DET, REC), freeze=other_freeze, resolution=other_res,
                                    layer_a_results=other_la)
    higher = build(mf.m.tracks, config=dataclasses.replace(CONFIG, calibration_minimum_clusters=71))
    hr = runs_for(higher, outputs_of(70, lambda i: [_plate_text(i)]))
    hs = runs_for(higher, outputs_of(70, lambda i: [""]))
    assert compare(higher, hr, hs).outcome == "insufficient-clusters"  # max(60, 71) from the frozen config


def test_required_clusters_is_max_of_floor_and_calibration():
    assert [ev.required_clusters(v) for v in (1, 59, 60, 61, 140)] == [60, 60, 60, 61, 140]
    for bad in (0, -1, True, 60.0, None):
        with pytest.raises(ValueError, match="calibration_minimum_invalid"):
            ev.required_clusters(bad)


# ---------------------------------------------------------------------------------------------- sixth cold review


def test_manifest_refuses_alias_items():
    """Review 6, P2-1 (probes): no item may alias another."""
    t0, t1 = T("t0", "s0", "KA01AB1234"), T("t1", "s1", "KA02AB1234")
    obs0 = t0.evidence[0].observation_id
    square = (SQUARE,)
    cases = {
        "two_crops_on_one_evidence_image": dict(tracks=[t0], crops=[ev.ManifestCrop("c0", "t0", obs0, square),
                                                                     ev.ManifestCrop("c1", "t0", obs0, square)]),
        "mavi_track_shared_by_two_tracks": dict(tracks=[t0, dataclasses.replace(t1, mavi_track_uuid=t0.mavi_track_uuid,
                                                                               evidence=t0.evidence)]),
        "evidence_shared_by_two_tracks": dict(tracks=[t0, dataclasses.replace(t1, evidence=t0.evidence)]),
        "two_c_plates_on_one_evidence_image": dict(tracks=[t0], plates=[
            ev.ManifestPlate("p0", "t0", "KA01AB1234", None, obs0), ev.ManifestPlate("p1", "t0", "KA01AB1234", None, obs0)]),
        "plate_text_differs_from_its_track_truth": dict(tracks=[t0], plates=[
            ev.ManifestPlate("p0", "t0", "MH12ZZ9999", None, obs0)]),
        "two_b_plates_on_one_image": dict(tracks=[t0, t1], plates=[
            ev.ManifestPlate("p0", "t0", "KA01AB1234", plate_image(0)),
            ev.ManifestPlate("p1", "t1", "KA02AB1234", dataclasses.replace(plate_image(0), observation_id=oid("x", 0)))]),
    }
    for code, parts in cases.items():
        mf = build(parts["tracks"], parts.get("crops", ()), parts.get("plates", ()))
        with pytest.raises(ValueError, match=code):
            ev.verify_manifest(mf.m, mf.digest)


def test_any_violation_in_the_composition_makes_c_a_contract_fail():
    """Review 6, P3-1: a violation on a Track that holds no C plate still fails C (probe 6)."""
    t0, t1 = T("t0", "s0", "KA01AB1234"), T("t1", "s1", "KA02AB1234")
    mf = build([t0, t1], plates=[ev.ManifestPlate("p0", "t0", "KA01AB1234", None, t0.evidence[0].observation_id)])
    bad = run(mf, "t1", recogniser=Outputs([R(("KA02AB1234", 1.5))]))
    good = run(mf, "t0", ["KA01AB1234"])
    assert bad.state == ev.CONTRACT_FAIL
    assert ev.evaluate_c(mf.m, mf.digest, [good, bad], composition=(DET, REC)).outcome == ev.CONTRACT_FAIL


def test_c_minus_b_needs_sealed_matching_results():
    mf = _plate_manifest(["KA01AB1234", "MH12AB0001"], b=True, c=True)
    b = ev.evaluate_b(mf.m, mf.digest, read_runs(mf, {"p0": R(("KA01AB1234", 0.9)), "p1": R(("MH12AB0001", 0.9))}),
                      recogniser=REC)
    c = ev.evaluate_c(mf.m, mf.digest, runs_for(mf, {"t0": ["KA01AB1234"], "t1": [""]}), composition=(DET, REC))
    assert ev.c_minus_b(c, b) == Fraction(-1, 2)
    with pytest.raises(ValueError, match="not_sealed"):
        ev.c_minus_b(dataclasses.replace(c, em=Fraction(1)), b)
    other_rec = ev.evaluate_b(mf.m, mf.digest, read_runs(mf, {"p0": [], "p1": []}, rec=OC5), recogniser=OC5)
    with pytest.raises(ValueError, match="not_comparable"):
        ev.c_minus_b(c, other_rec)


def test_top_k_protocol_values_and_identity_aliases_are_frozen():
    mf = population(1)
    config = mf.m.config
    assert (config.top_k, config.top_k_support_floor) == (ev.TOP_K, ev.TOP_K_SUPPORT_FLOOR) == (3, 50)
    ab = ab_digest(mf.digest)
    ids = tuple(f"PD{i}-X" for i in range(5))
    freeze = freeze_for(mf.digest, eligible_detectors=tuple((d, _h(d)) for d in ids))
    scores = [comp(ab, f"PD{i}-X", True, 100, 0.9 - i / 100, 0.1, 0.9) for i in range(5)]
    assert TOPK(scores, "detector", freeze) == ["PD0-X", "PD1-X", "PD2-X"]
    low = [comp(ab, "PD2-S", True, 49, 0.9, 0.1, 0.9)]
    assert TOPK(low, "detector", freeze_for(mf.digest, eligible_detectors=(("PD2-S", _h("PD2-S")),))) == []
    for roster, label in ((scores[:4], "omission"), (scores + [comp(ab, "PD9-X", True, 100, 1, 0, 1)], "outsider"),
                          ([], "empty")):
        with pytest.raises(ValueError, match="roster_is_not_the_frozen_universe"):  # review 7, P2-2
            TOPK(roster, "detector", freeze)
    with pytest.raises(ValueError, match="identity_under_two_ids"):
        freeze_for(mf.digest, eligible_detectors=(("PD2-S", _h("PD2-S")), ("PD2-T", _h("PD2-S"))))
    with pytest.raises(ValueError, match="identity_under_two_ids"):
        freeze_for(mf.digest, eligible_detectors=(("PD2-S", _h("OC5-BEST")),))
    for bad, code in ((dataclasses.replace(CONFIG, bootstrap_replicates=1000.0), "replicates_not_frozen_value"),
                      (dataclasses.replace(CONFIG, top_k=4), "top_k_not_frozen_value"),
                      (dataclasses.replace(CONFIG, top_k_support_floor=50.0), "top_k_not_frozen_value")):
        other = build(mf.m.tracks, config=bad)
        with pytest.raises(ValueError, match=code):
            ev.verify_manifest(other.m, other.digest)


# ---------------------------------------------------------------------------------------------- review 7


POLY = (((1, 1), (20, 1), (20, 10), (1, 10)),)


def _verify(mf):
    return ev.verify_manifest(mf.m, mf.digest)


def _ab_and_d():
    """A/B partition (site ab-site) and protected D partition (site d-site) sharing one site-level plan."""
    plan = ev.PartitionPlan("plan", (("ab-site", AB), ("d-site", D)))
    ab = build([T("a0", "ab-site", "KA01AB1234")], [ev.ManifestCrop("c0", "a0", oid("a0", 0), POLY)], plan=plan,
               twin_tracks=[T("d0", "d-site", "KA02AB1234")], manifest_id="ab")
    return ab, ab.d


def test_partitions_are_site_disjoint_and_projected_separately():
    """Review 7, P1-1: A/B/C come only from the A/B partition, D only from the protected D partition."""
    ab, d = _ab_and_d()
    assert ab.m.partition is AB and d.m.partition is D and ab.m.partition_plan == d.m.partition_plan
    _verify(ab), _verify(d)
    # a site in both partitions
    overlap = ev.PartitionPlan("plan", (("ab-site", AB), ("ab-site", D), ("d-site", D)))
    with pytest.raises(ValueError, match="site_in_two_partitions"):
        _verify(build([T("a0", "ab-site", "KA01AB1234")], [ev.ManifestCrop("c0", "a0", oid("a0", 0), POLY)],
                      plan=overlap, twin_tracks=[T("d0", "d-site", "KA02AB1234")]))
    for spelt in ("ab-site ", "AB-SITE"):  # one site under two spellings is still one site
        plan = ev.PartitionPlan("plan", (("ab-site", AB), (spelt, D)))
        with pytest.raises(ValueError, match="site_not_canonical"):
            _verify(build([T("a0", "ab-site", "KA01AB1234")], [ev.ManifestCrop("c0", "a0", oid("a0", 0), POLY)],
                          plan=plan, twin_tracks=[T("d0", spelt, "KA02AB1234")]))
    # an A item from a D-partition Track: the Track cannot enter the A/B manifest, and without it the crop is orphaned
    plan = ev.PartitionPlan("plan", (("ab-site", AB), ("d-site", D)))
    with pytest.raises(ValueError, match="site_not_in_this_partition"):
        _verify(build([T("a0", "ab-site", "KA01AB1234"), T("d0", "d-site", "KA02AB1234")],
                      [ev.ManifestCrop("c0", "d0", oid("d0", 0), POLY)], plan=plan,
                      twin_tracks=[T("d1", "d-site", "KA03AB1234")]))
    with pytest.raises(ValueError, match="manifest_crop"):
        _verify(build([T("a0", "ab-site", "KA01AB1234")], [ev.ManifestCrop("c0", "d0", oid("d0", 0), POLY)],
                      plan=plan, twin_tracks=[T("d0", "d-site", "KA02AB1234")]))
    # the D partition holds no A/B items
    with pytest.raises(ValueError, match="d_partition_holds_a_b_items"):
        _verify(build([T("d0", "d-site", "KA02AB1234")], [ev.ManifestCrop("c0", "d0", oid("d0", 0), POLY)],
                      partition=D, plan=plan, twin_tracks=[T("a0", "ab-site", "KA01AB1234")]))
    # A runs only from the A/B partition, D runs only from the D partition
    with pytest.raises(ValueError, match="is_not_the_ab_selection_partition"):
        ev.evaluate_a(d.m, d.digest, [], detector=DET)
    with pytest.raises(ValueError, match="is_not_the_ab_selection_partition"):
        ev.run_detection(d.m, d.digest, "c0", detector=GOOD_BOX, detector_identity=DET, images=images)
    with pytest.raises(ValueError, match="is_not_the_protected_d_partition"):
        score(ab, [run(ab, "a0", ["KA01AB1234"])])
    with pytest.raises(ValueError, match="result_of_another_manifest"):  # a D run on an A/B Track
        score(d, [run(ab, "a0", ["KA01AB1234"])])
    assert score(d, [run(d, "d0", ["KA02AB1234"])]).d_score == 1


def test_gate_and_layer_a_work_on_separate_partition_manifests():
    """Review 7, P1-1: the freeze binds the A/B digest, the D digest and the plan; Layer-A resolution and top-K
    need only the A/B manifest (no D truth is read), and the gate needs both scores on the D manifest."""
    ab, d = _ab_and_d()
    freeze = freeze_for(ab.digest)
    assert (freeze.ab_manifest_digest, freeze.d_manifest_digest) == (ab.digest, d.digest)
    layer_a = layer_a_for(ab.digest)
    del _MANIFESTS[d.digest]  # Layer-A resolution and top-K run with no D manifest present
    try:
        resolution = ev.resolve_baseline(freeze, layer_a, d_rows_read=0, resolved_at_utc=WHEN)
        assert resolution.pd_base_id == "PD2-N"
        scores = [comp(ab.digest, r, True, 100, 0.9 - i / 10, 0.1, 0.9, kind="recogniser")
                  for i, (r, _) in enumerate(RECOGNISERS)]
        assert TOPK(scores, "recogniser", freeze, ab) == ["OC1-XS", "OC2-A", "OC2-B"]
        with pytest.raises(ValueError, match="is_not_the_ab_selection_partition"):
            ev.top_k(scores, "recogniser", freeze=freeze, manifest=d.m, expected_manifest_digest=d.digest)
    finally:
        _MANIFESTS[d.digest] = d
    on_d = score(d, [run(d, "d0", ["KA02AB1234"])])
    assert isinstance(ev.baseline_gate(C("PD2-S", "OC1-XS", on_d), C("PD2-N", "OC5-BEST", on_d), resolution,
                                       freeze, layer_a), str)
    with pytest.raises(ValueError, match="gate_scores_not_on_the_same_population"):  # D scores off the frozen D digest
        resolve_d_freeze = freeze_for(ab.digest, d_manifest_digest="e" * 64)
        ev.baseline_gate(C("PD2-S", "OC1-XS", on_d), C("PD2-N", "OC5-BEST", on_d),
                         ev.resolve_baseline(resolve_d_freeze, layer_a, d_rows_read=0, resolved_at_utc=WHEN),
                         resolve_d_freeze, layer_a)
    with pytest.raises(ev.BaselineStop, match="layer_a_result_not_on_the_frozen_manifest"):
        ev.resolve_baseline(freeze_for(ab.digest), layer_a_for("f" * 64), d_rows_read=0, resolved_at_utc=WHEN)


def test_unsupported_text_is_typed_and_counted_wrong_for_precision():
    """Owner decision (review 7): human truth that does not normalise is UNSUPPORTED_TEXT, kept with its raw text,
    excluded from text-recall denominators, and every return against it is wrong for precision."""
    u = ev.UNSUPPORTED_TEXT("KA01AB12३४")
    assert u.state is ev.TruthState.UNSUPPORTED_TEXT and u.text == "KA01AB12३४" and u.supported_text is None
    plain = build([T("p", "s1", "KA01AB1234")])
    mixed = build([T("p", "s1", "KA01AB1234"), T("u", "s2", u)])
    without = score(plain, runs_for(plain, {"p": ["KA01AB1234"]}))
    with_u = score(mixed, runs_for(mixed, {"p": ["KA01AB1234"], "u": ["KA01AB1234"]}))
    assert with_u.counts.exact_denominator == without.counts.exact_denominator  # recall denominators unchanged
    assert with_u.counts.correct_returned == without.counts.correct_returned  # never a correct return
    assert with_u.contains_precision < without.contains_precision
    for bad in ("UNREADBLE", "NOPLAT", "N/A", "NONE", "NULL", "UNKNOWN", "ILLEGIBLE", "NOPLATE0", "NOGTVEHICLE1",
                "UNREADABLE.", "[UNREADABLE]", "TEXT"):
        with pytest.raises(ValueError, match="placeholder|sentinel|does_not_normalise"):
            ev.TEXT(bad)
    for state in ("TEXT", "NO PLATE", None):
        with pytest.raises(ValueError, match="truth_state_not_typed"):
            ev.Truth(state, "KA01AB1234")


def test_evidence_and_plate_image_fields_are_validated():
    """Review 7, P3-2: role, rank, size, UUID and SHA-256 on every evidence and B plate image."""
    good = T("a", "s1", "KA01AB1234", 2)
    for change in (dict(role=12345), dict(role="side-view"), dict(evidence_rank=-1), dict(evidence_rank=True),
                   dict(size_bytes=0), dict(size_bytes=-1), dict(observation_id="obs"), dict(sha256="x" * 64)):
        broken = dataclasses.replace(good, evidence=(dataclasses.replace(good.evidence[0], **change),
                                                     good.evidence[1]))
        with pytest.raises(ValueError, match="evidence_malformed"):
            _verify(build([broken]))
    with pytest.raises(ValueError, match="ranks_not_strictly_ordered"):
        _verify(build([dataclasses.replace(good, evidence=good.evidence[::-1])]))
    for change in (dict(size_bytes=-1), dict(observation_id="not-a-uuid"), dict(role=None)):
        image = dataclasses.replace(plate_image(4), **change)
        with pytest.raises(ValueError, match="plate_image_malformed"):
            _verify(build([T("a", "s1", "KA01AB1234")], plates=[ev.ManifestPlate("p1", "a", "KA01AB1234", image)]))


def test_evidence_bytes_cannot_alias_across_images():
    """Review 7, P3-3: two images with the same bytes (SHA-256) are one image, never two items."""
    a, b = T("a", "s1", "KA01AB1234"), T("b", "s2", "KA02AB1234")
    b = dataclasses.replace(b, evidence=(dataclasses.replace(b.evidence[0], sha256=a.evidence[0].sha256,
                                                             size_bytes=a.evidence[0].size_bytes),))
    with pytest.raises(ValueError, match="evidence_bytes_shared_by_two_images"):
        _verify(build([a, b]))
    image = dataclasses.replace(plate_image(4), sha256=a.evidence[0].sha256)
    with pytest.raises(ValueError, match="shared|alias|not_unique"):
        _verify(build([a], plates=[ev.ManifestPlate("p1", "a", "KA01AB1234", image)]))


def test_crop_geometry_agrees_with_truth_and_polygons_are_valid():
    """Review 7, P3-1: no GT polygon on NO_PLATE / NO_GT_VEHICLE; every polygon is a valid finite region. A TEXT
    crop may have no polygon (the plate is out of that frame)."""
    for truth in (ev.NO_PLATE, ev.NO_GT_VEHICLE):
        with pytest.raises(ValueError, match="polygon_contradicts_truth"):
            _verify(build([T("a", "s1", truth)], [ev.ManifestCrop("c1", "a", oid("a", 0), POLY)]))
    _verify(build([T("a", "s1", "KA01AB1234")], [ev.ManifestCrop("c1", "a", oid("a", 0), ())]))
    for polygon in (((True, 1), (2, 1), (2, 2)), ((1, 1), (2, 1)), ((1, 1), (2, 2), (3, 3)), ((-1, 1), (5, 1), (5, 5)),
                    (("1", 1), (5, 1), (5, 5))):
        with pytest.raises(ValueError, match="polygon_malformed"):
            _verify(build([T("a", "s1", "KA01AB1234")], [ev.ManifestCrop("c1", "a", oid("a", 0), (polygon,))]))
    with pytest.raises(ValueError):
        _verify(build([T("a", "s1", "KA01AB1234")],
                      [ev.ManifestCrop("c1", "a", oid("a", 0), (((float("nan"), 1), (5, 1), (5, 5)),))]))


def test_recogniser_universe_is_frozen_and_rosters_must_equal_it():
    """Review 7, P2-2: detector and recogniser rosters equal the frozen universes exactly; OC5 is outside both."""
    mf = _plate_manifest([_plate_text(i) for i in range(60)])
    for recognisers in ((), (("OC2-B", _h("OC2-B")), ("OC2-A", _h("OC2-A"))), (("OC2-A", _h("OC2-A")),) * 2):
        with pytest.raises(ValueError, match="recognisers_must_be_sorted_unique_nonempty"):
            freeze_for(mf.digest, eligible_recognisers=recognisers)
    with pytest.raises(ValueError, match="benchmark_only"):
        freeze_for(mf.digest, eligible_recognisers=(("OC5-BEST", _h("OC5-BEST")),))
    with pytest.raises(ValueError, match="identity|alias"):
        freeze_for(mf.digest, eligible_recognisers=(("OC2-A", _h("PD1-X")),))
    freeze = freeze_for(mf.digest)
    full = [comp(mf.digest, r, True, 100, 0.9, 0.1, 0.9, kind="recogniser") for r, _ in RECOGNISERS]
    assert len(TOPK(full, "recogniser", freeze)) == 3
    for roster in (full[1:], full + [comp(mf.digest, "OC9-Z", True, 100, 1, 0, 1, kind="recogniser")], []):
        with pytest.raises(ValueError, match="roster_is_not_the_frozen_universe"):
            TOPK(roster, "recogniser", freeze)


def test_comparison_is_sealed():
    """Review 7, P3-5: a paired comparison is a sealed result; any edit breaks the seal."""
    mf = population(3)
    runs = runs_for(mf, outputs_of(3, lambda i: [_plate_text(i)]))
    result = compare(mf, runs, runs)
    assert ev._is_sealed(ev._CMP, result)
    assert not ev._is_sealed(ev._CMP, dataclasses.replace(result, outcome="superior"))
    other = freeze_for(mf.digest, d_manifest_digest="e" * 64)
    layer_a = layer_a_for(mf.digest)
    with pytest.raises(ValueError, match="freeze_is_for_another_manifest"):
        compare(mf, runs, runs, freeze=other, layer_a_results=layer_a,
                resolution=ev.resolve_baseline(other, layer_a, d_rows_read=0, resolved_at_utc=WHEN))
