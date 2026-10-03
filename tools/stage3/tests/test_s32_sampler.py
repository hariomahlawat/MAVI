"""T3: the prediction-blind sampler (algorithm s3-2-video-quota-diversity-v1)."""

from __future__ import annotations

import ast
import copy
import itertools
import json
from fractions import Fraction
from pathlib import Path

import pytest

import s32fixtures as f
import s32pipeline as p
import sample_tracks as st

a = f.a


def layout(predictions: dict[str, str | None] | None = None, confidence: float = 0.7) -> dict[str, list[f.TrackSpec]]:
    """Twelve Vehicle Tracks on two cameras plus a Person; predictions are the only thing that varies."""
    predictions = predictions or {}
    tracks = {"CAM-A": [], "CAM-B": []}
    for number in range(1, 13):
        camera = "CAM-A" if number <= 7 else "CAM-B"
        tracks[camera].append(f.TrackSpec(
            number=number, subclass=predictions.get(str(number), "car"), start=300 * number, end=300 * number + 400 * (number % 5 + 1),
            box=(0.05 * (number % 4), 0.1, 0.1 + 0.05 * (number % 6), 0.2 + 0.03 * (number % 3)), quality=0.3 + 0.05 * (number % 7),
            roles=("Representative", "NearView")[: 1 + number % 2], mean_confidence=confidence,
            track_id=f"00000000-0000-4000-8000-{number:012d}"))
    tracks["CAM-A"].append(f.TrackSpec(number=90, object_class="Person", subclass=None,
                                       track_id="00000000-0000-4000-8000-000000000090"))
    return tracks


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return f.build_world(tmp_path_factory.mktemp("sampler") / "world", layout())


def make(world: f.World, out: Path, **kwargs) -> dict:
    p.run(st.main, p.sample(world, out, **kwargs))
    return json.loads(out.read_text(encoding="utf-8"))


def refused(capsys, args: list[str], code: str, out: Path) -> None:
    assert st.main(args) == 2
    assert f"refused {code}" in capsys.readouterr().err
    assert not out.exists()


def selection(document: dict) -> tuple:
    return (tuple((s["processingRunId"], s["trackId"], tuple(sorted(s["bins"].items()))) for s in document["selected"]),
            tuple((s["processingRunId"], s["trackId"]) for s in document["overlapSelected"]),
            tuple(sorted((run, v["quota"], v["overlapQuota"]) for run, v in document["allocation"].items())))


# Determinism and record


def test_sample_is_deterministic_and_records_its_bindings(world, tmp_path):
    first = (tmp_path / "a.json")
    second = (tmp_path / "b.json")
    document = make(world, first, target=8)
    make(world, second, target=8)
    assert first.read_bytes() == second.read_bytes()
    assert document["design"] == {"kind": "continuation", "samplingAlgorithm": st.ALGORITHM,
                                  "parameters": {"overlapFraction": 0.2}, "releaseId": "synthetic-release-1",
                                  "parentSampleSha256s": []}
    assert document["requirements"] == {"sha256": a.sha256_hex(world.requirements.read_bytes()),
                                        "gitCommit": world.commit, "gitPath": a.REQUIREMENTS_GIT_PATH}
    assert document["derivationSha256s"] == sorted(a.sha256_hex(d.read_bytes()) for d in world.derivations())
    assert document["releaseRecordSha256"] == "e" * 64
    assert document["excluded"] == {"not-vehicle": 1}
    assert sum(v["quota"] for v in document["allocation"].values()) == 8 == len(document["selected"])


# Blindness


def test_selection_ignores_every_prediction_and_confidence(tmp_path):
    baseline = f.build_world(tmp_path / "w1", layout())
    permuted = f.build_world(tmp_path / "w2", layout({str(n): v for n, v in zip(range(1, 13), itertools.cycle(
        ["truck", None, "bus", "motorcycle", "car"]))}, confidence=0.31))
    deleted = f.build_world(tmp_path / "w3", layout({str(n): None for n in range(1, 13)}, confidence=0.99))
    results = [selection(make(w, tmp_path / f"s{i}.json", target=9)) for i, w in enumerate((baseline, permuted, deleted))]
    assert results[0] == results[1] == results[2]


def test_a_mutant_that_reads_the_prediction_is_caught(tmp_path, monkeypatch):
    baseline = f.build_world(tmp_path / "w1", layout())
    permuted = f.build_world(tmp_path / "w2", layout({str(n): ("truck" if n % 2 else "car") for n in range(1, 13)}))
    honest = _blind = st._blind

    def leaking(run_id, track):  # a mutant: quality derived from the predicted subclass
        blind = honest(run_id, track)
        leaked = 1.0 if track["objectSubclass"] == "car" else 0.0
        return st.BlindTrack(blind.run_id, blind.track_id, blind.object_class, blind.start_ms, blind.end_ms,
                             tuple(st.BlindObservation(o.role, o.rank, o.width, o.height, leaked, o.evidence) for o in blind.observations))

    monkeypatch.setattr(st, "_blind", leaking)
    assert selection(make(baseline, tmp_path / "m1.json", target=6)) != selection(make(permuted, tmp_path / "m2.json", target=6))
    assert _blind is honest


def test_the_blind_projection_is_an_allow_list_without_prediction_members():
    fields = set(st.BlindTrack.__dataclass_fields__) | set(st.BlindObservation.__dataclass_fields__)
    assert not fields & {"objectSubclass", "subclass", "confidence", "meanConfidence", "maxConfidence"}
    source = Path(st.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    allowed = next(node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                   and any(getattr(t, "id", None) == "PREDICTION_MEMBERS" for t in node.targets))
    allowed_lines = set(range(allowed.lineno, allowed.end_lineno + 1))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in st.PREDICTION_MEMBERS:
            assert node.lineno in allowed_lines, f"prediction member {node.value!r} read at line {node.lineno}"


# Allocation, terciles, balancing


def test_allocation_floors_proportional_remainder_and_exhausted_videos():
    floors, quotas = st.allocate({"a": 10, "b": 6, "c": 2}, 12, 12 // 6, "seed")
    assert floors == {"a": 2, "b": 2, "c": 2} and quotas == {"a": 6, "b": 4, "c": 2}  # c exhausted at its floor
    floors, quotas = st.allocate({"a": 1, "b": 9}, 6, 6 // 4, "seed")
    assert floors == {"a": 1, "b": 1} and quotas == {"a": 1, "b": 5}


def test_largest_remainder_tie_goes_to_the_smallest_alloc_hash():
    _, quotas = st.allocate({"run-x": 5, "run-y": 5}, 5, 1, "tie-seed")
    winner = min(("run-x", "run-y"), key=lambda r: a.h("tie-seed", "alloc", r))
    assert quotas[winner] == 3 and sum(quotas.values()) == 5


def test_quotas_always_sum_to_target_and_never_exceed_availability():
    for available in itertools.product(range(0, 5), repeat=3):
        counts = {f"v{i}": n for i, n in enumerate(available)}
        for target in range(1, sum(available) + 1):
            _, quotas = st.allocate(counts, target, target // 6, "s")
            assert sum(quotas.values()) == target
            assert all(quotas[v] <= counts[v] for v in counts)


def test_tercile_cuts_break_ties_by_hash():
    tracks = [st.BlindTrack("run", f"t{i}", "Vehicle", 0, 1, ()) for i in range(6)]
    values = {("run", "t0"): 1.0, ("run", "t1"): 1.0, ("run", "t2"): 1.0, ("run", "t3"): 2.0, ("run", "t4"): 2.0, ("run", "t5"): 5.0}
    bins = st._tercile_bins(tracks, values, "seed")
    ones = sorted(("t0", "t1", "t2"), key=lambda t: a.h("seed", "run", t))
    twos = sorted(("t3", "t4"), key=lambda t: a.h("seed", "run", t))
    order = ones + twos + ["t5"]
    assert [bins[("run", t)] for t in order] == [0, 0, 1, 1, 2, 2]


def _imbalance(chosen, bins, quota):
    return sum((sum(1 for t in chosen if bins[d][(t.run_id, t.track_id)] == b) - Fraction(quota, 3)) ** 2
               for d in st.DIMENSIONS for b in range(3))


def test_greedy_balancing_beats_hash_order_on_a_skewed_video(monkeypatch):
    seed = "balance"
    candidates = [st.BlindTrack("run", f"t{i:02d}", "Vehicle", 0, 1, ()) for i in range(12)]
    hash_order = sorted(candidates, key=lambda t: a.h(seed, t.run_id, t.track_id))
    # The first six in hash order share bin 0 in every dimension; the rest spread over bins 1 and 2.
    bins = {d: {} for d in st.DIMENSIONS}
    for position, track in enumerate(hash_order):
        for k, d in enumerate(st.DIMENSIONS):
            bins[d][(track.run_id, track.track_id)] = 0 if position < 6 else 1 + (position + k) % 2
    chosen = st._greedy(candidates, 6, bins, seed)
    # Hash order is t00 t07 t08 t04 t02 t10 | t11 t05 t03 t09 t06 t01 (bin 0 in every dimension before the bar).
    # By hand: t00 (all scores 0, smallest hash); t11 and t05 (score 0: their bins are still empty); then every
    # candidate scores 5 and the smallest hash, t07, wins; then bin-0 Tracks score 10, so t03 and t09 (score 5).
    assert [t.track_id for t in chosen] == ["t00", "t11", "t05", "t07", "t03", "t09"]
    assert [t.track_id for t in hash_order] == ["t00", "t07", "t08", "t04", "t02", "t10", "t11", "t05", "t03", "t09", "t06", "t01"]
    assert _imbalance(chosen, bins, 6) < _imbalance(hash_order[:6], bins, 6)
    # A mutant that ignores the bins degenerates to hash order and loses the balance.
    monkeypatch.setattr(st, "DIMENSIONS", ())
    mutant = st._greedy(candidates, 6, bins, seed)
    assert [t.track_id for t in mutant] == [t.track_id for t in hash_order[:6]]


def test_overlap_allocation_is_a_subset_with_one_per_video(world, tmp_path):
    document = make(world, tmp_path / "s.json", target=10, overlap="0.3")
    selected = {(s["processingRunId"], s["trackId"]) for s in document["selected"]}
    overlap = [(s["processingRunId"], s["trackId"]) for s in document["overlapSelected"]]
    assert set(overlap) <= selected and len(overlap) == 3  # ceil(0.3 × 10)
    per_run = {run: sum(1 for r, _ in overlap if r == run) for run in document["allocation"]}
    assert per_run == {run: v["overlapQuota"] for run, v in document["allocation"].items()}
    assert all(v["overlapFloor"] == 1 for v in document["allocation"].values())
    # 0.2 × 120 is 24, not 25: the fraction is exact, never a float product.
    assert st.math.ceil(Fraction(repr(0.2)) * 120) == 24


# Bindings and design


def test_requirements_must_be_committed_unchanged_and_an_ancestor(world, tmp_path, capsys):
    out = tmp_path / "s.json"
    original = world.requirements.read_bytes()
    try:
        world.requirements.write_bytes(original + b"\n")
        refused(capsys, p.sample(world, out, target=4), "requirements_not_committed", out)
    finally:
        world.requirements.write_bytes(original)
    args = p.sample(world, out, target=4)
    args[args.index("--requirements-commit") + 1] = "0" * 40
    refused(capsys, args, "requirements_not_committed", out)


def test_requirements_commit_that_is_not_an_ancestor_of_head_is_refused(tmp_path, capsys):
    world = f.build_world(tmp_path / "w", layout())
    f.git(world.repository, "checkout", "-q", "-b", "side")
    world.requirements.write_bytes(world.requirements.read_bytes() + b" ")
    f.git(world.repository, "commit", "-q", "-am", "side change")
    side = f.git(world.repository, "rev-parse", "HEAD")
    f.git(world.repository, "checkout", "-q", "-")
    args = p.sample(world, tmp_path / "s.json", target=4)
    args[args.index("--requirements-commit") + 1] = side
    world.requirements.write_bytes(world.requirements.read_bytes() + b" ")
    refused(capsys, args, "requirements_not_committed", tmp_path / "s.json")


def test_exclusion_samples_never_reappear(world, tmp_path):
    first = make(world, tmp_path / "pilot.json", target=6)
    second = make(world, tmp_path / "next.json", target=4, seed="next", exclude=[tmp_path / "pilot.json"])
    first_tracks = {s["trackId"] for s in first["selected"]}
    assert not first_tracks & {s["trackId"] for s in second["selected"]}
    assert second["excluded"]["previously-sampled"] == 6
    pilot_sha = a.sha256_hex((tmp_path / "pilot.json").read_bytes())
    assert second["design"]["parentSampleSha256s"] == [pilot_sha] == second["excludedSampleSha256s"]


@pytest.mark.parametrize("design, reason, code", [
    (None, None, "design_invalid"),
    ("pilot", None, "design_invalid"),
    ("continuation", "rare buses", "design_invalid"),
    ("supplemental", None, "design_invalid"),
    ("supplemental", "", "design_invalid"),
    ("supplemental", "two\nlines", "design_invalid"),
    ("supplemental", "x" * 201, "design_invalid"),
])
def test_design_and_reason_rules(world, tmp_path, capsys, design, reason, code):
    args = p.sample(world, tmp_path / "s.json", target=4, reason=reason)
    if design is None:
        index = args.index("--design")
        del args[index:index + 2]
    else:
        args[args.index("--design") + 1] = design
    refused(capsys, args, code, tmp_path / "s.json")


def test_supplemental_records_its_reason(world, tmp_path):
    document = make(world, tmp_path / "s.json", target=4, design="supplemental", reason="x" * 200)
    assert document["design"]["kind"] == "supplemental" and document["design"]["reason"] == "x" * 200


def test_continuation_must_draw_from_exactly_the_pilot_pool(world, tmp_path, capsys):
    make(world, tmp_path / "pilot.json", target=4)
    # Omitted export.
    out = tmp_path / "c1.json"
    refused(capsys, p.sample(world, out, target=2, exclude=[tmp_path / "pilot.json"], exports=world.exports()[:1],
                             derivations=world.derivations()[:1]), "continuation_pool_mismatch", out)
    # Added export: a third video the pilot never had.
    extra = f.build_world(tmp_path / "extra", {"CAM-C": f.numbered(70, 2)}, base=5)
    added = tmp_path / "c2.json"
    args = p.sample(world, added, target=2, exclude=[tmp_path / "pilot.json"],
                    exports=[*world.exports(), *extra.exports()], derivations=[*world.derivations(), *extra.derivations()])
    refused(capsys, args, "continuation_pool_mismatch", added)
    # The same pool is accepted.
    make(world, tmp_path / "c3.json", target=2, seed="c3", exclude=[tmp_path / "pilot.json"])


def test_every_export_must_be_exactly_one_authorised_derivation(world, tmp_path, capsys):
    out = tmp_path / "s.json"
    refused(capsys, p.sample(world, out, target=4, derivations=world.derivations()[:1]), "export_not_derived", out)
    other = Path(tmp_path / "other-release.json")
    source = world.videos[1].source_path.read_bytes()
    f.write_derivation(other, source=source, release_id="another-release", release_record_sha="d" * 64)
    refused(capsys, p.sample(world, out, target=4, derivations=[world.derivations()[0], other]), "export_not_derived", out)
    blocked = tmp_path / "blocked.json"
    document = json.loads(world.derivations()[1].read_text(encoding="utf-8"))
    document["authorisation"]["blockers"] = ["determination-missing"]
    blocked.write_bytes(a.canonical_json(document))
    refused(capsys, p.sample(world, out, target=4, derivations=[world.derivations()[0], blocked]), "derivation_invalid", out)


def test_target_larger_than_the_usable_pool_is_refused(world, tmp_path, capsys):
    out = tmp_path / "s.json"
    refused(capsys, p.sample(world, out, target=13), "target_exceeds_pool", out)


def test_tracks_without_verifiable_evidence_are_excluded_not_sampled(tmp_path):
    world = f.build_world(tmp_path / "w", layout())
    export = json.loads(world.videos[0].export_path.read_text(encoding="utf-8"))
    for observation in export["tracks"][0]["observations"]:
        (world.videos[0].export_path.parent / observation["evidencePath"]).unlink()
    document = make(world, tmp_path / "s.json", target=4)
    assert document["excluded"]["no-verified-evidence"] == 1
    assert export["tracks"][0]["id"] not in {s["trackId"] for s in document["selected"]}


def test_existing_output_is_refused(world, tmp_path, capsys):
    out = tmp_path / "s.json"
    out.write_text("keep", encoding="utf-8")
    assert st.main(p.sample(world, out, target=4)) == 2
    assert out.read_text(encoding="utf-8") == "keep"
    assert "refused output_exists" in capsys.readouterr().err


def test_continuation_after_a_wider_supplemental_checks_the_pilot_only(tmp_path, capsys):
    world = f.build_world(tmp_path / "w", {**layout(), "CAM-C": f.numbered(80, 3)})
    two = [e for e in world.exports() if "export-2" not in str(e)]
    two_derivations = [d for d in world.derivations() if "derivation-2" not in str(d)]
    pilot = tmp_path / "pilot.json"
    make(world, pilot, target=6, exports=two, derivations=two_derivations)
    wider = tmp_path / "wider.json"
    make(world, wider, target=4, seed="wider", design="supplemental", reason="third camera", exclude=[pilot])
    # The continuation excludes both earlier samples; its pool is the pilot's two videos.
    follow = make(world, tmp_path / "follow.json", target=3, seed="follow", exclude=[pilot, wider], exports=two,
                  derivations=two_derivations)
    assert follow["design"]["kind"] == "continuation" and len(follow["design"]["parentSampleSha256s"]) == 2
    # A design the pilot does not share is refused before any labelling.
    out = tmp_path / "other.json"
    refused(capsys, p.sample(world, out, target=3, seed="other", exclude=[pilot], exports=two,
                             derivations=two_derivations, overlap="0.5"), "continuation_design_mismatch", out)
    # A continuation whose only parent is supplemental has no pilot to continue.
    refused(capsys, p.sample(world, out, target=3, seed="orphan", exclude=[wider]), "continuation_pool_mismatch", out)


def test_every_exported_video_counts_in_the_allocation(tmp_path):
    shapes = layout()
    shapes["CAM-C"] = [f.TrackSpec(number=95, object_class="Person", subclass=None,
                                   track_id="00000000-0000-4000-8000-000000000095")]
    world = f.build_world(tmp_path / "w", shapes)
    document = make(world, tmp_path / "s.json", target=6)
    assert len(document["allocation"]) == 3
    empty = next(v for v in document["allocation"].values() if v["cameraCode"] == "CAM-C")
    assert empty == {**empty, "available": 0, "floor": 0, "quota": 0}
    assert all(v["floor"] == 1 for v in document["allocation"].values() if v["available"])  # 6 // (2 × 3)
    assert set(document["strata"]["lumaDecoder"]) == {"pillow", "numpy"}
