"""B1 (#228) experiment seam: NearView-only role isolation, the frozen sharpness rule, the composition seam and
fail-closed, canonical run records. Development experiment tooling; production code is not modified."""
from __future__ import annotations

import dataclasses
import gzip
import importlib.util
import json
import random
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from mavi_vision.common.analytical import NormalizedBoundingBox, ObjectClass
from mavi_vision.detection.interfaces import DetectionCandidate
from mavi_vision.evidence.encoder import EncodedImage
from mavi_vision.evidence.policy import SCORE_SCALE
from mavi_vision.evidence.quality import CandidateQuality, FrameContext
from mavi_vision.evidence.roles import EvidenceRole
from mavi_vision.evidence.selector import EvidenceSelector
from mavi_vision.quality.scoring import _normalized_sharpness
from mavi_vision.tracking.interfaces import TrackCandidate
from mavi_vision.video.reader import DecodedFrame
from tests.profile_fixtures import PRODUCTION_EVIDENCE_POLICY as POLICY

_PLATES = Path(__file__).resolve().parents[1] / "plates"
sys.path.insert(0, str(_PLATES))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _PLATES / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


b1 = _load("b1_nearview")
b1_run = _load("b1_run")

REP, NEAR = EvidenceRole.REPRESENTATIVE, EvidenceRole.NEAR_VIEW
EARLY, LATE = EvidenceRole.EARLY_DIVERSE, EvidenceRole.LATE_DIVERSE
FLOOR = POLICY.sharpness_floor


@dataclasses.dataclass
class Spec:
    score: float = 0.5
    area: float = 0.1
    sharpness: float = 0.5
    edge: float = 0.1
    occlusion: float = 0.0
    b1: float | None = None
    confidence: float = 0.9
    box: NormalizedBoundingBox = NormalizedBoundingBox(0.2, 0.2, 0.3, 0.4)


class StubScorer:
    version = "stub"

    def __init__(self, specs):
        self.specs = specs
        self.calls = 0

    def score(self, context, candidate):
        self.calls += 1
        s = self.specs[context.frame.source_frame_number]
        micro = round(s.score * SCORE_SCALE)
        return CandidateQuality(s.sharpness, s.edge, s.area, s.occlusion, micro, micro)


class StubEncoder:
    version = "stub"

    def __init__(self, refuse=()):
        self.refuse = set(refuse)

    def encode(self, crop, cap_bytes):
        frame = int(crop[0, 0, 0])
        return None if frame in self.refuse else EncodedImage(bytes([frame]) * 10, crop.shape[1], crop.shape[0], 85, 0)


def _frame(number):
    return DecodedFrame(source_frame_number=number, offset_ms=number * 200,
                        image=np.full((40, 40, 3), number % 256, dtype=np.uint8))


def _run(selector_factory, specs, object_class=ObjectClass.VEHICLE):
    selector = selector_factory()
    for number in sorted(specs):
        s = specs[number]
        candidate = TrackCandidate("t-1", object_class, s.confidence, s.box)
        detection = DetectionCandidate(object_class, s.confidence, s.box)
        selector.observe(FrameContext(_frame(number), (detection,)), candidate)
    return selector


def _production(specs, encoder=None):
    return lambda: EvidenceSelector(policy=POLICY, scorer=StubScorer(specs), encoder=encoder or StubEncoder(),
                                    track_start_ms=0)


def _b1(specs, sink, mode="active", encoder=None, calls=None):
    def sharpness(frame, box):
        if calls is not None:
            calls.append(frame.source_frame_number)
        return specs[frame.source_frame_number].b1
    return lambda: b1.B1NearViewSelector(policy=POLICY, scorer=StubScorer(specs), encoder=encoder or StubEncoder(),
                                         track_start_ms=0, sink=sink, mode=mode, sharpness=sharpness)


def _frames(selector):
    return {h.role: (h.source_frame_number, h.qualified) for h in selector.holders()}


def _resolved(selector):
    return [(r.rank, r.role, r.evidence.source_frame_number) for r in selector.resolve()]


def _near_stream():
    """Frame 0 qualified small view; frame 10 a larger, sharpness-only-rejected view (B1 passes)."""
    return {0: Spec(score=0.6, area=0.05, sharpness=0.2),
            10: Spec(score=0.4, area=0.2, sharpness=0.03, b1=0.07,
                     box=NormalizedBoundingBox(0.1, 0.1, 0.5, 0.4))}


# role isolation and sharpness-only admission ------------------------------------------------------------------------

def test_sharpness_only_rejected_large_vehicle_enters_near_view_only():
    specs, sink = _near_stream(), []
    production = _run(_production(specs), specs)
    candidate = _run(_b1(specs, sink), specs)
    assert production.holder(NEAR) is None
    assert _frames(candidate)[NEAR] == (10, False)  # experiment-admitted, never release-qualified
    assert candidate.holder(REP).source_frame_number == production.holder(REP).source_frame_number == 0
    assert candidate.holder(EARLY) is None and candidate.holder(LATE) is None
    assert candidate.stats.candidates_qualified == production.stats.candidates_qualified == 1
    assert [(r["frame"], r["held"], r["opportunity"]) for r in sink] == [(10, True, True)]


def test_b1_only_candidate_never_takes_early_or_late_or_qualified_representative():
    # Frame 0 fallback-only (fails confidence); frames 10, 20 b1-only: they never qualify the Representative.
    specs = {0: Spec(score=0.3, confidence=0.4),
             10: Spec(score=0.2, area=0.2, sharpness=0.01, b1=0.2, box=NormalizedBoundingBox(0.1, 0.1, 0.5, 0.4)),
             20: Spec(score=0.25, area=0.3, sharpness=0.01, b1=0.2, box=NormalizedBoundingBox(0.05, 0.05, 0.6, 0.5))}
    production = _run(_production(specs), specs)
    candidate = _run(_b1(specs, []), specs)
    assert candidate.holder(REP) == production.holder(REP)
    assert candidate.holder(REP).qualified is False and candidate.holder(REP).source_frame_number == 0
    assert candidate.holder(EARLY) is None and candidate.holder(LATE) is None
    assert _frames(candidate)[NEAR] == (20, False)  # grew past frame 10 under the unchanged hysteresis
    # The NearView rule sees the Representative as it stands: a b1-only frame that just became the fallback
    # Representative is a near-duplicate of it and takes no second role.
    specs[20] = dataclasses.replace(specs[20], score=0.95)
    sink = []
    candidate = _run(_b1(specs, sink), specs)
    assert candidate.holder(REP).source_frame_number == 20 and _frames(candidate)[NEAR] == (10, False)
    assert sink[-1]["frame"] == 20 and sink[-1]["nearDuplicateOfRepresentative"] is True


@pytest.mark.parametrize("blocked", [dict(edge=0.0), dict(edge=0.004), dict(confidence=0.49), dict(occlusion=0.3)])
def test_unchanged_gates_still_reject(blocked):
    specs = _near_stream()
    specs[10] = dataclasses.replace(specs[10], **blocked)
    sink = []
    candidate = _run(_b1(specs, sink), specs)
    assert candidate.holder(NEAR) is None and sink == []
    assert _resolved(candidate) == _resolved(_run(_production(specs), specs))


def test_b1_value_below_floor_or_undefined_is_not_admitted():
    for value in (None, FLOOR - 1e-9):
        specs = _near_stream()
        specs[10] = dataclasses.replace(specs[10], b1=value)
        sink = []
        assert _run(_b1(specs, sink), specs).holder(NEAR) is None and sink == []


def test_growth_hysteresis_and_duplicate_rules_are_unchanged():
    specs = _near_stream()
    specs[5] = Spec(score=0.5, area=0.18, sharpness=0.2, box=NormalizedBoundingBox(0.15, 0.15, 0.45, 0.4))
    specs[10] = dataclasses.replace(specs[10], area=0.18 * 1.25)  # boundary: not strictly grown
    sink = []
    candidate = _run(_b1(specs, sink), specs)
    assert _frames(candidate)[NEAR] == (5, True)
    assert sink[0]["growthAllows"] is False and sink[0]["held"] is False
    # Near-duplicate of the Representative (within 500 ms and IoU >= 0.85): never held.
    dup = {0: Spec(score=0.6, area=0.05, sharpness=0.2),
           1: Spec(score=0.4, area=0.2, sharpness=0.03, b1=0.07)}
    sink = []
    assert _run(_b1(dup, sink), dup).holder(NEAR) is None
    assert sink[0]["nearDuplicateOfRepresentative"] is True


def test_encode_refusal_keeps_previous_holder():
    specs = _near_stream()
    sink = []
    candidate = _run(_b1(specs, sink, encoder=StubEncoder(refuse={10})), specs)
    assert candidate.holder(NEAR) is None
    assert sink[0]["held"] is False and sink[0]["encodeRefused"] is True


def test_person_selection_is_unchanged_and_never_assessed():
    specs = _near_stream()
    calls = []
    candidate = _run(_b1(specs, [], calls=calls), specs, ObjectClass.PERSON)
    assert calls == []
    assert _resolved(candidate) == _resolved(_run(_production(specs), specs, ObjectClass.PERSON))


def test_shadow_mode_holds_nothing_and_records_the_opportunity():
    specs, sink = _near_stream(), []
    shadow = _run(_b1(specs, sink, mode="shadow"), specs)
    assert _resolved(shadow) == _resolved(_run(_production(specs), specs))
    assert sink[0]["opportunity"] is True and sink[0]["held"] is False


def test_scorer_runs_once_per_candidate():
    specs = _near_stream()
    selector = _b1(specs, [])()
    for number in sorted(specs):
        s = specs[number]
        selector.observe(FrameContext(_frame(number), (DetectionCandidate(ObjectClass.VEHICLE, s.confidence, s.box),)),
                         TrackCandidate("t-1", ObjectClass.VEHICLE, s.confidence, s.box))
    assert selector._scorer._inner.calls == 2


def test_without_b1_only_candidates_the_seam_equals_production_on_random_streams():
    rng = random.Random(228)
    for _ in range(300):
        specs = {}
        for number in range(rng.randint(1, 25)):
            x, y = rng.uniform(0, 0.4), rng.uniform(0, 0.4)
            specs[number * rng.randint(1, 8)] = Spec(
                score=rng.uniform(0, 1), area=rng.uniform(0.01, 0.4), sharpness=rng.choice([0.01, 0.04, 0.06, 0.3]),
                edge=rng.choice([0.0, 0.004, 0.01, 0.1]), occlusion=rng.choice([0.0, 0.29, 0.31]),
                confidence=rng.choice([0.3, 0.5, 0.9]), b1=rng.choice([None, 0.01, 0.049]),
                box=NormalizedBoundingBox(x, y, rng.uniform(0.05, 0.5), rng.uniform(0.05, 0.5)))
        refuse = {n for n in specs if rng.random() < 0.1}
        production = _run(_production(specs, StubEncoder(refuse)), specs)
        for mode in ("active", "shadow"):
            candidate = _run(_b1(specs, [], mode=mode, encoder=StubEncoder(refuse)), specs)
            assert candidate.holders() == production.holders()
            assert _resolved(candidate) == _resolved(production)


def test_representative_identical_on_random_streams_with_b1_only_candidates():
    rng = random.Random(1228)
    for _ in range(300):
        specs = {}
        for number in range(rng.randint(1, 25)):
            x, y = rng.uniform(0, 0.4), rng.uniform(0, 0.4)
            specs[number * rng.randint(1, 8)] = Spec(
                score=rng.uniform(0, 1), area=rng.uniform(0.01, 0.4), sharpness=rng.choice([0.01, 0.04, 0.06, 0.3]),
                edge=rng.choice([0.0, 0.01, 0.1]), confidence=rng.choice([0.4, 0.9]), b1=rng.choice([None, 0.07]),
                box=NormalizedBoundingBox(x, y, rng.uniform(0.05, 0.5), rng.uniform(0.05, 0.5)))
        production = _run(_production(specs), specs)
        candidate = _run(_b1(specs, []), specs)
        assert candidate.holder(REP) == production.holder(REP)
        held = candidate.holder(NEAR)
        if held is not None and not held.qualified:
            spec = specs[held.source_frame_number]
            assert spec.sharpness < FLOOR <= spec.b1 and spec.edge >= POLICY.edge_margin_floor


# the frozen sharpness rule ------------------------------------------------------------------------------------------

def test_frozen_record_matches_the_implementation():
    record, digest = b1.frozen_record()
    assert record["id"] == b1.RULE_ID and record["intervention"]["targetHeightPx"] == b1.TARGET_HEIGHT_PX == 128
    assert "BILINEAR" in record["intervention"]["interpolation"] and len(digest) == 64


def test_b1_sharpness_never_upscales_and_matches_the_declared_resize():
    rng = np.random.default_rng(7)
    assert b1.b1_sharpness_of_crop(rng.integers(0, 255, (128, 300, 3), dtype=np.uint8)) is None
    assert b1.b1_sharpness_of_crop(rng.integers(0, 255, (40, 60, 3), dtype=np.uint8)) is None
    assert b1.b1_sharpness_of_crop(np.zeros((0, 0, 3), dtype=np.uint8)) is None
    crop = rng.integers(0, 255, (257, 199, 3), dtype=np.uint8)
    expected = np.asarray(Image.fromarray(crop).resize((round(199 * 128 / 257), 128), Image.Resampling.BILINEAR))
    assert expected.shape == (128, 99, 3)
    full = NormalizedBoundingBox(0.0, 0.0, 1.0, 1.0)
    assert b1.b1_sharpness_of_crop(crop) == _normalized_sharpness(type("F", (), {"image": expected}), full)
    # A non-contiguous view (as crop_region returns) gives the same value as its copy.
    frame = rng.integers(0, 255, (400, 400, 3), dtype=np.uint8)
    assert b1.b1_sharpness_of_crop(frame[10:300, 20:250]) == b1.b1_sharpness_of_crop(frame[10:300, 20:250].copy())


def test_downscaling_raises_the_scale_dependent_metric_on_a_smooth_large_crop():
    ramp = np.tile(np.linspace(0, 255, 300).astype(np.uint8)[None, :, None], (300, 1, 3))
    full = NormalizedBoundingBox(0.0, 0.0, 1.0, 1.0)
    assert b1.b1_sharpness_of_crop(ramp) > _normalized_sharpness(type("F", (), {"image": ramp}), full)


# composition seam ---------------------------------------------------------------------------------------------------

def test_composition_seam_swaps_and_restores_the_production_selector():
    from mavi_vision.pipeline import process_video

    def factory(**kwargs):
        return None

    with b1.b1_composition(factory):
        assert process_video.EvidenceSelector is factory
    assert process_video.EvidenceSelector is EvidenceSelector
    with pytest.raises(ZeroDivisionError):
        with b1.b1_composition(factory):
            raise ZeroDivisionError
    assert process_video.EvidenceSelector is EvidenceSelector
    process_video.EvidenceSelector = factory
    try:
        with pytest.raises(RuntimeError, match="not_production"):
            with b1.b1_composition(factory):
                pass
    finally:
        process_video.EvidenceSelector = EvidenceSelector


# canonical, fail-closed records -------------------------------------------------------------------------------------

def test_logs_are_deterministic_and_tamper_evident(tmp_path):
    rows = [{"b": 1.5, "a": "x"}, {"a": "y", "b": None}]
    first, second = tmp_path / "1.jsonl.gz", tmp_path / "2.jsonl.gz"
    e1, e2 = b1_run.write_log(first, rows), b1_run.write_log(second, rows)
    assert e1 == e2 and first.read_bytes() == second.read_bytes()
    assert first.read_bytes()[4:8] == b"\x00\x00\x00\x00"  # gzip MTIME 0
    assert b1_run.read_log(first, e1) == rows
    with pytest.raises(b1_run.B1Error, match="rowcount"):
        b1_run.read_log(first, {**e1, "rows": 3})
    second.write_bytes(gzip.compress(b'{"a":"x","b":1.5}\n', mtime=0))
    with pytest.raises(b1_run.B1Error, match="gzip"):
        b1_run.read_log(second, e1)
    with pytest.raises(b1_run.B1Error, match="canonical"):
        b1_run.read_log(second, {**e1, "gzipSha256": b1_run.sha_file(second)})
    loose = b'{"b": 1.5, "a": "x"}\n'
    second.write_bytes(gzip.compress(loose, mtime=0))
    with pytest.raises(b1_run.B1Error, match="not_canonical"):
        b1_run.read_log(second, {"rows": 1, "gzipSha256": b1_run.sha_file(second),
                                 "canonicalSha256": b1_run.sha_bytes(loose)})


def _arm(root: Path, sequences=("s1", "s2"), arm="B") -> Path:
    index = {"kind": "b1-arm", "arm": arm, "inventorySha256": "i", "results": {}, "candidateLogs": {}, "b1Logs": {},
             "staging": {}, "inputs": {}}
    for s in sequences:
        staging = root / "staging" / s
        crop = staging / "staging" / "job" / "evidence" / "v-1.jpg"
        trajectory = staging / "staging" / "job" / "trajectories" / "v-1.msgpack"
        crop.parent.mkdir(parents=True)
        trajectory.parent.mkdir(parents=True)
        crop.write_bytes(b"jpeg-" + s.encode())
        trajectory.write_bytes(b"traj-" + s.encode())

        def artefact(path):
            return {"storageKey": path.relative_to(staging).as_posix(), "sha256": b1_run.sha_file(path),
                    "sizeBytes": path.stat().st_size}
        result = {"sequenceId": s, "videoSha256": "v" + s, "tracks": [
            {"trackId": "v-1", "objectClass": "vehicle", "trajectory": artefact(trajectory),
             "observations": [{"role": "near-view", "rank": 1, "sourceFrameNumber": 3, "crop": artefact(crop)}]}]}
        (root / "results").mkdir(parents=True, exist_ok=True)
        (root / "results" / f"{s}.json").write_bytes(json.dumps(result, sort_keys=True).encode())
        index["results"][s] = b1_run.sha_file(root / "results" / f"{s}.json")
        index["candidateLogs"][s] = b1_run.write_log(root / "candidates" / f"{s}.jsonl.gz", [{"frame": 3}])
        index["b1Logs"][s] = b1_run.write_log(root / "b1" / f"{s}.jsonl.gz", [{"frame": 3, "held": True}])
        index["staging"][s] = b1_run._staging_digest(staging)
        index["inputs"][s] = {"videoSha256": "v" + s, "detectionsSha256": "d" + s}
    (root / "index.json").write_bytes(json.dumps(index, sort_keys=True).encode())
    return root


def test_verify_accepts_a_complete_arm(tmp_path):
    assert b1_run.verify(_arm(tmp_path / "a"))["verified"] is True


@pytest.mark.parametrize("tamper", ["missing_result", "extra_log", "result_bytes", "log_bytes", "crop_bytes",
                                    "extra_staged_file", "missing_index_entry"])
def test_verify_fails_closed(tmp_path, tamper):
    arm = _arm(tmp_path / "a")
    if tamper == "missing_result":
        (arm / "results" / "s2.json").unlink()
    elif tamper == "extra_log":
        b1_run.write_log(arm / "b1" / "s3.jsonl.gz", [])
    elif tamper == "result_bytes":
        (arm / "results" / "s1.json").write_bytes((arm / "results" / "s1.json").read_bytes() + b" ")
    elif tamper == "log_bytes":
        b1_run.write_log(arm / "candidates" / "s1.jsonl.gz", [{"frame": 4}])
    elif tamper == "crop_bytes":
        next((arm / "staging" / "s1").rglob("*.jpg")).write_bytes(b"other")
    elif tamper == "extra_staged_file":
        (arm / "staging" / "s1" / "stray.bin").write_bytes(b"x")
    else:
        index = json.loads((arm / "index.json").read_bytes())
        del index["b1Logs"]["s2"]
        (arm / "index.json").write_bytes(json.dumps(index).encode())
    with pytest.raises(b1_run.B1Error):
        b1_run.verify(arm)


def test_repeat_equality_is_on_canonical_content(tmp_path):
    first = _arm(tmp_path / "a")
    second = tmp_path / "b"
    shutil.copytree(first, second)
    assert b1_run.equal(first, second)["canonicalEqual"] is True
    third = _arm(tmp_path / "c")
    index = json.loads((third / "index.json").read_bytes())
    index["b1Logs"]["s1"] = b1_run.write_log(third / "b1" / "s1.jsonl.gz", [{"frame": 3, "held": False}])
    (third / "index.json").write_bytes(json.dumps(index).encode())
    result = b1_run.equal(first, third)
    assert result["canonicalEqual"] is False and result["differing"]["b1Logs"] == ["s1"]


def test_processing_run_identity_is_per_arm_and_sequence():
    assert b1_run.job_id("A", "s") != b1_run.job_id("B", "s") != b1_run.job_id("preflight", "s")
    assert b1_run.job_id("B", "s") == b1_run.job_id("B", "s")


# Phase 2 offline search predicate ------------------------------------------------------------------------------------

def test_offline_exact_search_hit_requires_the_associated_track_and_counts_others():
    plates = _load("b1_plates")
    eval_doc = {"rows": [
        {"sequenceId": "s", "gtTrackId": "g1", "state": "matched", "maviTrackId": "v-1", "usablePlate": True,
         "result": {"oracleReadable": True}},
        {"sequenceId": "s", "gtTrackId": "g2", "state": "fragmentedGt", "maviTrackId": None, "usablePlate": True,
         "result": {"oracleReadable": False}},
        {"sequenceId": "s", "gtTrackId": "g3", "state": "matched", "maviTrackId": "v-3", "usablePlate": False,
         "result": None}]}
    texts = {("s", "v-1"): ["ABC123"], ("s", "v-2"): ["ABC123", "XYZ9"], ("s", "v-3"): []}
    truth = {("s", "g1"): ["ABC123"], ("s", "g2"): ["XYZ9"]}
    rows = plates.hits(eval_doc, texts, truth)
    assert rows["s/g1"] == {"state": "matched", "oracleReadable": True, "hit": True, "otherTracksReturned": 1}
    assert rows["s/g2"]["hit"] is False and rows["s/g2"]["otherTracksReturned"] == 1  # unassociated: never a hit
    assert "s/g3" not in rows
