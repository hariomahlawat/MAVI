"""GT↔MAVI Track association (S3.2d-1 plan §7, §9): the fixture family, exclusivity, determinism, mutation."""

from __future__ import annotations

import copy
import json
from fractions import Fraction

import pytest

import track_fixtures as f
from track_fixtures import follow, gt_document, mid, one, run, states, static, track
from tools.benchmarks.capabilities.vehicle_tracks import association as a
from tools.benchmarks.capabilities.vehicle_tracks import ground_truth
from tools.benchmarks.capabilities.vehicle_tracks import mavi_tracks as mt
from tools.benchmarks.capabilities.vehicle_tracks import policy as policies
from tools.benchmarks.core import descriptor as d
from tools.benchmarks.core import mavi
from tools.benchmarks.core.identity import S32Error, canonical_json, document_sha256
from tools.benchmarks.datasets import synthetic as s

B1 = (0.1, 0.1, 0.2, 0.2)
B2 = (0.6, 0.6, 0.2, 0.2)
BIG = (0.1, 0.1, 0.4, 0.4)
NOWHERE = (0.85, 0.05, 0.1, 0.1)  # inside no GT box of these fixtures


def obs(frame: int, box=B1) -> tuple[int, tuple[float, float, float, float]]:
    return 200 * frame, box


def pair_of(entry, gt_id):
    return next(pair for pair in entry["pairs"] if pair["gtTrackId"] == gt_id)


def candidate(entry, state, key, value, other_key, other_value):
    item = next(item for item in entry[state] if item[key] == value)
    return next(pair for pair in item["candidates"] if pair[other_key] == other_value)


def only(entry, **expected):
    """Every outcome list is empty except the ones given (ids in order)."""
    actual = states(entry)
    for key, value in actual.items():
        assert value == expected.get(key, []), (key, value)


# One-to-one and overlap floors


def test_perfect_one_to_one():
    entry = one(gt_document({"1": static(B1, range(10))}), run(track(1, follow(B1, range(10)), [obs(2), obs(7)])))
    only(entry, assigned=["1"], assignedMavi=[mid(1)])
    pair = entry["pairs"][0]
    assert pair["overlapFrames"] == 10 and pair["longestContainedRun"] == 10
    assert pair["containment"]["value"] == pair["gtCoverage"]["value"] == pair["maviCoverage"]["value"] == 1.0
    assert pair["meanNormalisedDistance"] == 0.0 and pair["spotCheckIoU"] == [1.0, 1.0]


def test_partial_overlap_above_and_below_the_frame_floor():
    document = gt_document({"1": static(B1, range(4))})
    above = one(document, run(track(1, follow(B1, range(3)), [obs(1)])))
    only(above, assigned=["1"], assignedMavi=[mid(1)])
    assert above["pairs"][0]["overlapFrames"] == 3
    below = one(document, run(track(1, follow(B1, range(2)), [obs(1)])))
    only(below, unmatchedGt=["1"], unmatchedMavi=[mid(1)])


def test_low_containment_is_rejected():
    points = follow(B1, range(4)) + follow(NOWHERE, range(4, 10))
    entry = one(gt_document({"1": static(B1, range(10))}), run(track(1, points, [obs(1)])))
    only(entry, unmatchedGt=["1"], unmatchedMavi=[mid(1)])


# Fragments, duplicates, merges


def test_short_fragment_on_a_long_gt_is_not_an_assignment():
    entry = one(gt_document({"1": static(B1, range(10))}), run(track(1, follow(B1, range(4)), [obs(1)])))
    only(entry, unmatchedGt=["1"], unmatchedMavi=[mid(1)])


def test_two_fragments_covering_the_gt_make_it_fragmented():
    entry = one(gt_document({"1": static(B1, range(10))}),
                run(track(1, follow(B1, range(4)), [obs(1)]), track(2, follow(B1, range(4, 8)), [obs(5)])))
    only(entry, fragmentedGt=["1"], unmatchedMavi=[mid(1), mid(2)])


def test_one_ineligible_track_alone_never_makes_a_gt_fragmented():
    # Alternating support fails continuity; a single Track is not a split (plan §7.4 fragmentedGt).
    points = [(200 * k, *((0.2, 0.2) if k % 2 == 0 else (0.9, 0.1))) for k in range(10)]
    entry = one(gt_document({"1": static(B1, range(10))}), run(track(1, points, [obs(0)])))
    only(entry, unmatchedGt=["1"], unmatchedMavi=[mid(1)])


def test_full_lifetime_track_beats_a_half_duplicate_fragment():
    entry = one(gt_document({"1": static(B1, range(10))}),
                run(track(1, follow(B1, range(10)), [obs(2)]), track(2, follow(B1, range(5)), [obs(2)])))
    only(entry, assigned=["1"], assignedMavi=[mid(1)], fragmentMavi=[mid(2)])


def test_track_spanning_two_identities_70_30_assigns_the_first_and_merges_the_second():
    document = gt_document({"1": static(B1, range(7)), "2": static(B2, range(7, 10))})
    points = follow(B1, range(7)) + follow(B2, range(7, 10))
    entry = one(document, run(track(1, points, [obs(2), obs(8, B2)])))
    only(entry, assigned=["1"], assignedMavi=[mid(1)], mergedGt=["2"])
    assert pair_of(entry, "1")["maviCoverage"]["numerator"] == 7


def test_track_spanning_two_identities_50_50_is_assigned_to_neither():
    document = gt_document({"1": static(B1, range(5)), "2": static(B2, range(5, 10))})
    points = follow(B1, range(5)) + follow(B2, range(5, 10))
    entry = one(document, run(track(1, points, [obs(2), obs(7, B2)])))
    only(entry, ambiguousGt=["1", "2"], unmatchedMavi=[mid(1)])


def test_missed_vehicle_concurrent_with_a_tracked_one_is_unmatched_not_merged():
    document = gt_document({"1": static(B1, range(10)), "2": static(B2, range(10))})
    entry = one(document, run(track(1, follow(B1, range(10)), [obs(2)])))
    only(entry, assigned=["1"], assignedMavi=[mid(1)], unmatchedGt=["2"])


def test_gt_meeting_both_merged_and_fragmented_conditions_is_counted_once_as_merged():
    h, g_box = B1, B2
    document = gt_document({"g": static(g_box, range(10, 20)), "h": static(h, range(10))})
    spanning = follow(h, range(10)) + follow(g_box, range(10, 15))      # assigned to h; covers half of g
    fragment_b = follow(g_box, range(15, 18))
    fragment_c = follow(g_box, range(17, 20))
    entry = one(document, run(track(1, spanning, [obs(3, h)]), track(2, fragment_b, [obs(16, g_box)]),
                              track(3, fragment_c, [obs(18, g_box)])))
    only(entry, assigned=["h"], assignedMavi=[mid(1)], mergedGt=["g"], unmatchedMavi=[mid(2), mid(3)])


# Nearest-centre exclusivity


def test_queue_of_overlapping_boxes_gives_each_centre_to_one_gt():
    left, right = (0.1, 0.1, 0.3, 0.2), (0.3, 0.1, 0.3, 0.2)  # overlap in x 0.3–0.4
    document = gt_document({"L": static(left, range(6)), "R": static(right, range(6))})
    near_left = [(200 * k, 0.33, 0.2) for k in range(6)]   # inside both; nearer L's centre (0.25)
    near_right = [(200 * k, 0.37, 0.2) for k in range(6)]  # inside both; nearer R's centre (0.45)
    entry = one(document, run(track(1, near_left, [obs(1, left)]), track(2, near_right, [obs(1, right)])))
    only(entry, assigned=["L", "R"], assignedMavi=[mid(1), mid(2)])
    assert pair_of(entry, "L")["maviTrackId"] == mid(1) and pair_of(entry, "R")["maviTrackId"] == mid(2)
    # The losing pairs have zero containment: a centre supports at most one GT per frame.
    all_pairs = a._Sequence(ground_truth.project(document),
                            run(track(1, near_left, [obs(1, left)]), track(2, near_right, [obs(1, right)])),
                            policies.v1(), Fraction(5), True).candidates()
    contained = {(pair.gt, pair.mavi): pair.contained for pair in all_pairs}
    assert contained[("L", mid(2))] == 0 and contained[("R", mid(1))] == 0
    assert contained[("L", mid(1))] == 6 and contained[("R", mid(2))] == 6


# IoU verification


def test_wrong_box_fails_verification_on_both_sides():
    tiny = (0.28, 0.28, 0.04, 0.04)
    entry = one(gt_document({"1": static(BIG, range(10))}), run(track(1, follow(BIG, range(10)), [obs(2, tiny)])))
    only(entry, unverifiedGt=["1"], unverifiedMavi=[mid(1)])
    assert candidate(entry, "unverifiedGt", "gtTrackId", "1", "maviTrackId", mid(1))["spotCheckIoU"][0] < 0.3


def test_three_verification_failed_tracks_count_the_gt_once():
    tiny = (0.28, 0.28, 0.04, 0.04)
    tracks = [track(n, follow(BIG, range(10)), [obs(2, tiny)]) for n in (1, 2, 3)]
    entry = one(gt_document({"1": static(BIG, range(10))}), run(*tracks))
    only(entry, unverifiedGt=["1"], unverifiedMavi=[mid(1), mid(2), mid(3)])


def test_verification_failures_on_an_assigned_gt_stay_on_the_mavi_side():
    tiny = (0.28, 0.28, 0.04, 0.04)
    entry = one(gt_document({"1": static(BIG, range(10))}),
                run(track(1, follow(BIG, range(10)), [obs(2, BIG)]),
                    track(2, follow(BIG, range(10), dx=0.01), [obs(2, tiny)]),
                    track(3, follow(BIG, range(10), dx=-0.01), [obs(2, tiny)])))
    result = states(entry)
    assert result["assigned"] == ["1"] and not result["unverifiedGt"]  # coverage-limited GT rate unchanged
    assert sorted(result["fragmentMavi"] + result["unverifiedMavi"]) == [mid(2), mid(3)]


def test_only_a_verification_failure_makes_a_pair_unverified():
    # The alternating Track fails continuity; with a bad IoU too it is still unmatched, not unverified.
    tiny = (0.28, 0.28, 0.04, 0.04)
    points = [(200 * k, *((0.3, 0.3) if k % 2 == 0 else (0.9, 0.1))) for k in range(10)]
    entry = one(gt_document({"1": static(BIG, range(10))}), run(track(1, points, [obs(0, tiny)])))
    only(entry, unmatchedGt=["1"], unmatchedMavi=[mid(1)])


def test_no_observation_on_the_gt_span_fails_verification():
    entry = one(gt_document({"1": static(B1, range(10)), "2": static(B2, range(12, 14))}),
                run(track(1, follow(B1, range(10)), [obs(13, B2)])))
    assert states(entry)["unverifiedGt"] == ["1"]


def test_interpolated_box_at_an_observation_between_labels():
    moving = {k: (0.1 + 0.05 * k, 0.1, 0.2, 0.2) for k in range(10)}
    points = [(int(round(1000 * i / 30)), 0.2 + 0.05 * (1000 * i / 30) / 200, 0.2) for i in range(0, 55)]
    halfway_box = (0.1 + 0.05 * 0.5, 0.1, 0.2, 0.2)  # the GT box at 100 ms
    entry = one(gt_document({"1": moving}), run(track(1, points, [(100, halfway_box)]), rate=Fraction(30)))
    assert entry["pairs"][0]["spotCheckIoU"][0] > 0.999


# Sparse labels and high-rate Tracks


def test_thirty_fps_track_against_five_hertz_labels_is_judged_on_evaluable_points():
    points = [(int(round(1000 * i / 30)), 0.2, 0.2) for i in range(0, 60)]  # 2 s of 30 fps
    entry = one(gt_document({"1": static(B1, range(10))}), run(track(1, points, [(1000, B1)]), rate=Fraction(30)))
    pair = entry["pairs"][0]
    assert pair["maviCoverage"]["value"] == 1.0 and pair["maviCoverage"]["denominator"] == 10


def test_thirty_fps_track_on_the_object_at_a_minority_of_instants_fails_purity():
    points = [(int(round(1000 * i / 30)), *((0.2, 0.2) if i < 24 else (0.9, 0.1))) for i in range(60)]
    document = gt_document({"1": static(B1, range(4))}, frames=10)
    entry = one(document, run(track(1, points, [(200, B1)]), rate=Fraction(30)))
    only(entry, unmatchedGt=["1"], unmatchedMavi=[mid(1)])
    pair = candidate(entry, "unmatchedGt", "gtTrackId", "1", "maviTrackId", mid(1))
    assert pair["gtCoverage"]["value"] == 1.0 and pair["maviCoverage"]["value"] == 0.4


# Continuity (labelled-frame adjacency)


@pytest.mark.parametrize("frames, inside, longest, eligible", [
    (6, {0, 2, 4}, 1, False),                       # points only on frames 1, 3, 5
    (6, {0, 1, 2}, 3, True),                        # frames 1–3
    (10, set(range(10)) - {4}, 5, True),            # 1–4 and 6–10
    (5, {0, 1, 3, 4}, 2, False),                    # 1–2 and 4–5
    (10, {0, 2, 4, 6, 8}, 1, False),                # alternating, valid IoU
])
def test_continuity_runs_over_labelled_frame_adjacency(frames, inside, longest, eligible):
    points = [(200 * k, *((0.2, 0.2) if k in inside else (0.9, 0.1))) for k in range(frames)]
    if frames == 6 and inside == {0, 2, 4}:
        points = [(200 * k, 0.2, 0.2) for k in sorted(inside)]  # no point at all on frames 2, 4, 6
    entry = one(gt_document({"1": static(B1, range(frames))}), run(track(1, points, [obs(min(inside))])))
    if eligible:
        assert entry["pairs"][0]["longestContainedRun"] == longest
    else:
        assert not entry["pairs"]
        found = candidate(entry, "unmatchedGt", "gtTrackId", "1", "maviTrackId", mid(1))
        assert found["longestContainedRun"] == longest


# Ambiguity


def test_identical_duplicate_tracks_make_the_gt_ambiguous():
    entry = one(gt_document({"1": static(B1, range(10))}),
                run(track(1, follow(B1, range(10)), [obs(2)]), track(2, follow(B1, range(10)), [obs(2)])))
    only(entry, ambiguousGt=["1"], unmatchedMavi=[mid(1), mid(2)])


def test_symmetric_crossing_with_an_identity_switch_is_ambiguous():
    first = {k: (0.1 + 0.06 * k, 0.4, 0.2, 0.2) for k in range(10)}  # crosses `second` between frames 4 and 5
    second = {k: (0.64 - 0.06 * k, 0.4, 0.2, 0.2) for k in range(10)}
    centre = lambda box: (box[0] + 0.1, 0.5)  # noqa: E731
    m1 = [(200 * k, *centre(first[k] if k < 5 else second[k])) for k in range(10)]
    m2 = [(200 * k, *centre(second[k] if k < 5 else first[k])) for k in range(10)]
    entry = one(gt_document({"1": first, "2": second}),
                run(track(1, m1, [obs(4, first[4])]), track(2, m2, [obs(4, second[4])])))
    only(entry, ambiguousGt=["1", "2"], unmatchedMavi=[mid(1), mid(2)])


def test_nearer_track_wins_over_an_equal_coverage_track_near_the_edge():
    entry = one(gt_document({"1": static(BIG, range(10))}),
                run(track(1, follow(BIG, range(10)), [obs(2, BIG)]),
                    track(2, follow(BIG, range(10), dx=0.15), [obs(2, BIG)])))
    only(entry, assigned=["1"], assignedMavi=[mid(1)], fragmentMavi=[mid(2)])


def test_identical_scores_are_resolved_by_the_deterministic_order_whatever_the_input_order():
    document = gt_document({"1": static(B1, range(10)), "2": static(B2, range(10))})
    tracks = [track(1, follow(B1, range(10)), [obs(2)]), track(2, follow(B2, range(10)), [obs(2, B2)])]
    forward = f.associate([document], [run(*tracks)])
    reverse_doc = copy.deepcopy(document)
    backward = f.associate([reverse_doc], [run(*reversed(tracks))])
    assert canonical_json(forward) == canonical_json(backward)
    only(forward["sequences"][0], assigned=["1", "2"], assignedMavi=[mid(1), mid(2)])


# Ignore


def test_track_wholly_inside_an_ignore_region_is_ignored_mavi():
    document = gt_document({"1": static(B1, range(10))}, regions=[(k, NOWHERE) for k in range(10)])
    entry = one(document, run(track(1, follow(B1, range(10)), [obs(2)]), track(2, follow(NOWHERE, range(10)))))
    only(entry, assigned=["1"], assignedMavi=[mid(1)], ignoredMavi=[mid(2)])
    assert entry["ignoredMavi"][0] == {"maviTrackId": mid(2), "evaluablePoints": 10, "pointsInIgnoreRegions": 10}


def test_partially_ignored_gt():
    gt = {k: (("ignore", B1) if k in (3, 4, 5) else B1) for k in range(10)}
    entry = one(gt_document({"1": gt}),
                run(track(1, follow(B1, range(10)), [obs(1)]), track(2, follow(B1, [4]))))
    pair = pair_of(entry, "1")
    assert pair["gtCoverage"]["denominator"] == 7 and pair["gtCoverage"]["numerator"] == 7
    assert pair["maviCoverage"] == {"numerator": 7, "denominator": 7, "value": 1.0}
    assert pair["longestContainedRun"] == 7  # ignored frames neither break nor extend a run
    assert states(entry)["ignoredMavi"] == [mid(2)]  # a point on an ignored frame counts for ignoredMavi only


def test_three_valid_and_seven_ignored_frames_do_not_fail_purity():
    gt = {k: (B1 if k < 3 else ("ignore", B1)) for k in range(10)}
    entry = one(gt_document({"1": gt}), run(track(1, follow(B1, range(10)), [obs(1)])))
    pair = pair_of(entry, "1")
    assert pair["maviCoverage"] == {"numerator": 3, "denominator": 3, "value": 1.0}


def test_observations_on_or_across_ignored_frames_are_excluded_from_the_gate():
    gt = {k: (("ignore", B1) if k == 5 else B1) for k in range(10)}
    garbage = (0.7, 0.7, 0.1, 0.1)
    labelled = one(gt_document({"1": gt}), run(track(1, follow(B1, range(10)), [obs(2), obs(5, garbage)])))
    assert labelled["pairs"][0]["spotCheckIoU"] == [1.0]
    points = [(int(round(1000 * i / 30)), 0.2, 0.2) for i in range(60)]
    high = one(gt_document({"1": gt}),
               run(track(1, points, [(400, B1), (900, garbage)]), rate=Fraction(30)))  # 900 ms: between 4 and 5
    assert high["pairs"][0]["spotCheckIoU"] == [1.0]


def test_high_rate_track_inside_an_ignore_region_matches_the_labelled_rate_result():
    regions = [(k, NOWHERE) for k in range(10)]
    document = gt_document({"1": static(B1, range(10))}, regions=regions)
    at_five = one(document, run(track(1, follow(B1, range(10)), [obs(2)]), track(2, follow(NOWHERE, range(10)))))
    thirty = [(int(round(1000 * i / 30)), 0.9, 0.1) for i in range(60)]
    at_thirty = one(document, run(track(1, [(int(round(1000 * i / 30)), 0.2, 0.2) for i in range(60)], [(400, B1)]),
                                  track(2, thirty), rate=Fraction(30)))
    assert at_five["ignoredMavi"] == at_thirty["ignoredMavi"] == [
        {"maviTrackId": mid(2), "evaluablePoints": 10, "pointsInIgnoreRegions": 10}]


def test_too_short_gt_is_ignored_and_its_short_track_does_not_pollute_unmatched():
    document = gt_document({"1": static(B1, range(10)), "2": static(B2, range(2))})
    entry = one(document, run(track(1, follow(B1, range(10)), [obs(2)]), track(2, follow(B2, range(2)))))
    only(entry, assigned=["1"], assignedMavi=[mid(1)], ignoredGt=["2"], ignoredMavi=[mid(2)])
    assert entry["ignoredGt"] == [{"gtTrackId": "2", "nonIgnoredFrames": 2}]


# Outcome exclusivity and the artefact


def test_every_gt_and_track_appears_in_exactly_one_outcome():
    document = gt_document({"a": static(B1, range(10)), "b": static(B2, range(10)), "c": static(BIG, range(2))})
    entry = one(document, run(track(1, follow(B1, range(10)), [obs(2)]), track(2, follow(B2, range(4)), [obs(1, B2)]),
                              track(3, follow(NOWHERE, range(10)))))
    result = states(entry)
    gt_ids = result["assigned"] + sum((result[k] for k in (*a.GT_STATES, "ignoredGt")), [])
    mavi_ids = result["assignedMavi"] + sum((result[k] for k in a.MAVI_STATES), [])
    assert sorted(gt_ids) == ["a", "b", "c"] and sorted(mavi_ids) == [mid(1), mid(2), mid(3)]


def test_artefact_body_hash_and_check_refuse_tampering():
    artefact = f.associate([gt_document({"1": static(B1, range(10))})], [run(track(1, follow(B1, range(10)), [obs(2)]))])
    body = {key: artefact[key] for key in ("policy", "sequences", "alignment")}
    assert artefact["associationBodySha256"] == document_sha256(body)
    tampered = copy.deepcopy(artefact)
    tampered["sequences"][0]["pairs"][0]["overlapFrames"] = 9
    with pytest.raises(S32Error, match="^association_invalid:body_sha256$"):
        a.check(tampered)
    doubled = copy.deepcopy(artefact)
    doubled["sequences"][0]["unmatchedGt"] = [{"gtTrackId": "1", "candidates": []}]
    doubled["associationBodySha256"] = document_sha256({k: doubled[k] for k in ("policy", "sequences", "alignment")})
    with pytest.raises(S32Error, match="^association_invalid:gt_counted_twice:seq-1$"):
        a.check(doubled)


def test_association_is_written_once(tmp_path):
    artefact = f.associate([gt_document({"1": static(B1, range(10))})], [run(track(1, follow(B1, range(10)), [obs(2)]))])
    data = a.write(artefact, tmp_path / "association.json")
    assert data == canonical_json(artefact)
    with pytest.raises(S32Error, match="^output_exists$"):
        a.write(artefact, tmp_path / "association.json")


def test_envelope_must_bind_the_policy_and_the_ground_truth():
    document = gt_document({"1": static(B1, range(10))})
    mavi_run = run(track(1, follow(B1, range(10)), [obs(2)]))
    policy = policies.v1()
    other = policies.load({**policies.POLICY_V1, "minOverlapFrames": 4})
    envelope = f.envelope_for([document], other)
    with pytest.raises(S32Error, match="^association_policy_invalid:not_bound$"):
        a.associate(envelope=envelope, policy=policy, sequences=[(document, mavi_run)], labelled_rate=Fraction(5))
    envelope = f.envelope_for([document], policy)
    changed = copy.deepcopy(document)
    changed["tracks"][0]["nativeClass"] = "bus"
    with pytest.raises(S32Error, match="^association_invalid:ground_truth_hash:seq-1$"):
        a.associate(envelope=envelope, policy=policy, sequences=[(changed, mavi_run)], labelled_rate=Fraction(5))
    with pytest.raises(S32Error, match="^association_invalid:sequences$"):
        a.associate(envelope=envelope, policy=policy, sequences=[], labelled_rate=Fraction(5))


def test_policy_change_changes_identity_and_threshold():
    document = gt_document({"1": static(B1, range(4))})
    mavi_run = run(track(1, follow(B1, range(3)), [obs(1)]))
    strict = policies.load({**policies.POLICY_V1, "minOverlapFrames": 4})
    assert strict.sha256 != policies.v1().sha256
    assert states(f.one(document, mavi_run))["assigned"] == ["1"]
    assert states(f.one(document, mavi_run, policy=strict))["assigned"] == []


@pytest.mark.parametrize("edit, code", [
    (lambda doc: doc.update(minContainment={"numerator": 2, "denominator": 4}),
     "association_policy_invalid:not_lowest_terms"),
    (lambda doc: doc.update(minContainment={"numerator": 3, "denominator": 2}), "association_policy_invalid:minContainment"),
    (lambda doc: doc.update(version="v2"), "association_policy_invalid:schema:version"),
    (lambda doc: doc.update(timeToleranceMs=10), "association_policy_invalid:schema"),
    (lambda doc: doc.pop("minConsecutiveContainedFrames"), "association_policy_invalid:schema"),
])
def test_invalid_policies_are_refused(edit, code):
    document = copy.deepcopy(policies.POLICY_V1)
    edit(document)
    with pytest.raises(S32Error, match=f"^{code}"):
        policies.load(document)


def test_policy_v1_is_the_frozen_defaults():
    p = policies.v1()
    assert (p.min_overlap_frames, p.min_containment, p.min_gt_coverage, p.min_mavi_coverage, p.min_spot_check_iou,
            p.ambiguity_margin, p.distance_ambiguity_margin, p.min_consecutive_contained_frames) == (
        3, Fraction(1, 2), Fraction(1, 2), Fraction(1, 2), Fraction(3, 10), Fraction(1, 10), Fraction(1, 10), 3)
    assert policies.POLICY_V1["alignment"] == "midpoint-windows-v1"


def test_mixed_source_rates_are_refused():
    documents = [gt_document({"1": static(B1, range(4))}, sequence="s1"),
                 gt_document({"1": static(B1, range(4))}, sequence="s2")]
    runs = [run(track(1, follow(B1, range(4)), [obs(1)])), run(track(2, follow(B1, range(4)), [obs(1)]),
                                                                rate=Fraction(30), video=2)]
    with pytest.raises(S32Error, match="^association_invalid:mixed_source_rate$"):
        f.associate(documents, runs)


# Class independence (plan §7.4, §9 mutation test)


def _synthetic_benchmark(tmp_path, mutate: bool):
    """Synthetic adapter GT for seq-a and seq-b, and T1 exports whose Vehicle Tracks follow some GT tracks."""
    source = s.write_source(tmp_path / "source")
    frozen = d.freeze(s.descriptor(), source)
    entries = d.reconcile(frozen, source)
    adapter = s.SyntheticAdapter()
    documents = [adapter.ground_truth(source, entries, frozen, "val", seq) for seq in ("seq-a", "seq-b")]
    runs = []
    for video, document in enumerate(documents, start=1):
        specs = []
        for n, gt_track in enumerate(document["tracks"], start=10 * video):
            frames = [frame for frame in gt_track["frames"]]
            box = lambda frame: (frame["box"]["x"], frame["box"]["y"], frame["box"]["width"], frame["box"]["height"])  # noqa: E731
            points = [(200 * frame["frameIndex"], box(frame)[0] + box(frame)[2] / 2, box(frame)[1] + box(frame)[3] / 2)
                      for frame in frames]
            specs.append({"n": n, "points": points, "observations": [(200 * frames[1]["frameIndex"], box(frames[1]))],
                          "subclass": "car", "confidence": 0.9})
        specs.append({"n": 90 + video, "points": [(0, 0.5, 0.5), (200, 0.5, 0.5)], "objectClass": "Person"})
        if mutate:
            for item in specs:
                if item.get("objectClass") != "Person":
                    item["subclass"] = {"car": "bus", "truck": "motorcycle"}.get(item["subclass"], "truck")
                    item["confidence"] = 0.31
            for gt_track in document["tracks"]:
                gt_track["nativeClass"] = {"car": "pedestrian", "truck": "bus", "pedestrian": "van",
                                           "bus": "car", "van": "truck", "motorcycle": "car"}[gt_track["nativeClass"]]
        path = f.write_export(tmp_path / f"run-{video}", tmp_path / "evidence", specs, video=video)
        export = next(iter(mavi.load_exports([path]).values()))
        runs.append(mt.project(export, tmp_path / "evidence"))
    mapping_sha = document_sha256(s.mapping()) if not mutate else "0" * 64
    return f.associate(documents, runs, mapping_sha256=mapping_sha)


def test_mutating_every_class_subclass_and_confidence_leaves_the_association_body_identical(tmp_path):
    base = _synthetic_benchmark(tmp_path / "base", mutate=False)
    mutated = _synthetic_benchmark(tmp_path / "mutated", mutate=True)
    assert canonical_json(base["sequences"]) == canonical_json(mutated["sequences"])
    assert base["associationBodySha256"] == mutated["associationBodySha256"]
    # Provenance legitimately differs: ground-truth hashes, mapping and so the run identity.
    assert base["envelope"]["benchmarkRunId"] != mutated["envelope"]["benchmarkRunId"]
    assert base["envelope"]["sequences"] != mutated["envelope"]["sequences"]
    assert base["envelope"]["tooling"]["mappingSha256"] != mutated["envelope"]["tooling"]["mappingSha256"]
    # The synthetic benchmark exercises real outcomes, not an empty body; Person Tracks never appear.
    totals = a.counts(base["sequences"])
    assert totals["pairs"] >= 4 and totals["ignoredGt"] == 0
    serialized = canonical_json(base["sequences"]).decode()
    assert f.mid(91) not in serialized and f.mid(92) not in serialized


def test_association_artefact_contains_no_class_subclass_or_confidence_value(tmp_path):
    artefact = _synthetic_benchmark(tmp_path, mutate=False)
    body = canonical_json({k: artefact[k] for k in ("policy", "sequences", "alignment")}).decode().lower()
    for word in ("class", "subclass", "confidence", "car", "truck", "pedestrian", "objectclass"):
        assert f'"{word}' not in body and f':"{word}"' not in body


def test_the_association_module_imports_nothing_from_any_evaluator():
    import ast
    from pathlib import Path

    package = Path(a.__file__).parent
    for module in package.glob("*.py"):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imported = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        assert not [name for name in imported if "evaluat" in name or "vehicle_subclass" in name], module.name
