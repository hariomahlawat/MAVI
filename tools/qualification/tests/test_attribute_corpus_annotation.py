"""S2c.1: annotation independence, adjudication, ground truth, agreement and the pilot."""

from __future__ import annotations

import copy

import pytest
from attribute_corpus_fixtures import build_corpus, policy

from attributes.corpus import task as task_module
from attributes.corpus.agreement import agreement_report, cohen_kappa, krippendorff_alpha_nominal, raw_agreement, render_markdown, verify_report_hash
from attributes.corpus.annotation import (
    AnnotationLedger,
    build_assignment,
    build_batch,
    build_ground_truth,
    build_reveal_packet,
    labels_from_csv,
    load_evaluation_view,
    parse_adjudication,
    parse_batch,
    split_ground_truth,
    unit_key,
)
from attributes.corpus.canonical import CorpusError, document_sha256
from attributes.corpus.manifest import parse_corpus
from attributes.corpus.partition import build_partition, partition_of
from attributes.corpus.pilot import pilot_report, sample_pilot_tracks
from attributes.corpus.task import load_task, parse_task

GUIDE = "d" * 64
T0 = "2026-10-05T09:00:00Z"


# ---- statistics: fixtures with hand-computed answers --------------------------------------


def test_krippendorff_alpha_and_cohen_kappa_on_a_hand_computed_fixture() -> None:
    # Units (a,a) (a,b) (b,b) (b,b): o_aa=2, o_ab=o_ba=1, o_bb=4; n=8, n_a=3, n_b=5.
    # D_o = 2/8, D_e = 2*3*5/(8*7) = 30/56 -> alpha = 1 - 0.25/0.535714 = 0.533333.
    units = [["a", "a"], ["a", "b"], ["b", "b"], ["b", "b"]]
    assert krippendorff_alpha_nominal(units) == pytest.approx(1 - 0.25 / (30 / 56))
    # p_o = 0.75; A: a=2,b=2; B: a=1,b=3 -> p_e = 0.5 -> kappa = 0.5.
    assert cohen_kappa([(u[0], u[1]) for u in units]) == pytest.approx(0.5)
    assert raw_agreement(units) == pytest.approx(0.75)


def test_classic_cohen_kappa_fixture() -> None:
    pairs = [("y", "y")] * 20 + [("y", "n")] * 5 + [("n", "y")] * 10 + [("n", "n")] * 15
    assert cohen_kappa(pairs) == pytest.approx(0.4)  # p_o = 0.7, p_e = 0.5


def test_perfect_agreement_and_no_variation_are_distinguished() -> None:
    assert krippendorff_alpha_nominal([["a", "a"], ["b", "b"]]) == pytest.approx(1.0)
    assert krippendorff_alpha_nominal([["a", "a"], ["a", "a"]]) is None  # undefined, not 1 or 0
    assert krippendorff_alpha_nominal([["a"], ["b"]]) is None


def test_alpha_handles_missing_ratings_and_three_raters() -> None:
    # Krippendorff (2011) style: unit with 3 raters contributes pairs weighted 1/(m-1).
    value = krippendorff_alpha_nominal([["a", "a", "a"], ["b", "b"], ["a", "b", "b"], ["c"]])
    assert value is not None and 0 < value < 1


# ---- workflow scaffold ----------------------------------------------------------------------


@pytest.fixture()
def world(tmp_path):
    corpus = parse_corpus(build_corpus(sites=4, cameras_per_site=3, days=12, tracks_per_source=2))
    partition = build_partition(corpus, policy(), [], {"recurrence": None, "duplicate": None})
    candidate = load_task()
    confirmed = parse_task(task_module.confirm_rules(candidate.document, "owner-1", "2026-10-01T09:00:00Z"))
    ledger = AnnotationLedger(tmp_path / "annotation-ledger.jsonl")
    ledger.register_annotator("ann-a", False, T0)
    ledger.register_annotator("ann-b", True, T0)
    return {"corpus": corpus, "partition": partition, "psha": document_sha256(partition), "task": confirmed, "ledger": ledger, "tmp": tmp_path}


def _labels_for(assignment: dict, choose) -> list[dict]:
    rows = []
    for unit in assignment["units"]:
        for attribute in unit["attributeTypes"]:
            outcome, value, reason = choose(unit, attribute)
            rows.append({"unitKind": unit["unitKind"], "trackId": unit["trackId"], "observationId": unit["observationId"], "attributeType": attribute, "outcome": outcome, "value": value, "unscorableReason": reason})
    return rows


def _default_choice(unit, attribute):
    if attribute == "subject-validity":
        return ("value", "valid", None)
    if attribute == "vehicle-colour":
        return ("value", "white", None)
    if attribute.endswith("colour"):
        return ("value", "blue", None)
    if attribute == "person-headwear":
        return ("unscorable", None, "not-visible")
    return ("value", "absent", None)


def _pilot(world, choose_b=None, size=40, choose_a=None):
    tracks = sample_pilot_tracks(world["corpus"], world["partition"], size, "pilot-seed")
    units = [("track", t, None) for t in tracks]
    made = {}
    for annotator in ("ann-a", "ann-b"):
        made[annotator] = build_assignment(f"pilot-{annotator}", annotator, "pilot", "independent", units, world["corpus"], world["partition"], world["psha"], world["task"], GUIDE)
        world["ledger"].issue_assignment(made[annotator], T0)
    batches = []
    for annotator, choose in (("ann-a", choose_a or _default_choice), ("ann-b", choose_b or _default_choice)):
        batch = build_batch(f"batch-{annotator}", made[annotator], T0, _labels_for(made[annotator], choose), 600, world["task"])
        world["ledger"].submit_batch(batch, made[annotator], T0)
        batches.append((batch, parse_batch(batch, made[annotator], world["task"])))
    return made, batches


def test_pilot_is_drawn_from_training_only_and_is_camera_stratified(world) -> None:
    tracks = sample_pilot_tracks(world["corpus"], world["partition"], 30, "s")
    parts = partition_of(world["partition"])
    assert all(parts[t] == "training" for t in tracks)
    cameras = {world["corpus"].source_of(t).camera_id for t in tracks}
    assert len(cameras) >= 3
    frozen = next(t for t, p in parts.items() if p == "frozen-test")
    with pytest.raises(CorpusError, match="pilot_outside_training"):
        build_assignment("pilot-x", "ann-a", "pilot", "independent", [("track", frozen, None)], world["corpus"], world["partition"], world["psha"], world["task"], GUIDE)


def test_pilot_needs_owner_confirmed_thresholds(world) -> None:
    track = sample_pilot_tracks(world["corpus"], world["partition"], 1, "s")[0]
    with pytest.raises(CorpusError, match="pilot_rules_not_owner_confirmed"):
        build_assignment("pilot-x", "ann-a", "pilot", "independent", [("track", track, None)], world["corpus"], world["partition"], world["psha"], load_task(), GUIDE)


def test_main_labelling_needs_the_frozen_task(world) -> None:
    track = next(iter(world["corpus"].tracks))
    with pytest.raises(CorpusError, match="assignment_main_requires_frozen_task"):
        build_assignment("main-x", "ann-a", "main", "independent", [("track", track, None)], world["corpus"], world["partition"], world["psha"], world["task"], GUIDE)


def test_assignment_packets_carry_no_labels(world) -> None:
    made, _ = _pilot(world)
    for assignment in made.values():
        text = str(assignment)
        assert "outcome" not in text and "value" not in assignment["units"][0]


def test_mutation_annotator_b_cannot_submit_after_seeing_a(world) -> None:
    """Mutation 8: a reveal packet before B's independent submission is refused, and B cannot
    submit an independent batch for units already revealed to B."""
    tracks = sample_pilot_tracks(world["corpus"], world["partition"], 5, "s")
    units = [("track", t, None) for t in tracks]
    a = build_assignment("pilot-a", "ann-a", "pilot", "independent", units, world["corpus"], world["partition"], world["psha"], world["task"], GUIDE)
    b = build_assignment("pilot-b", "ann-b", "pilot", "independent", units, world["corpus"], world["partition"], world["psha"], world["task"], GUIDE)
    world["ledger"].issue_assignment(a, T0)
    world["ledger"].issue_assignment(b, T0)
    batch_a = build_batch("batch-a", a, T0, _labels_for(a, _default_choice), None, world["task"])
    world["ledger"].submit_batch(batch_a, a, T0)
    packet = build_reveal_packet("reveal-1", "ann-b", [unit_key("track", t, None) for t in tracks], [(batch_a, parse_batch(batch_a, a, world["task"]))])
    with pytest.raises(CorpusError, match="ledger_reveal_before_independent_submission"):
        world["ledger"].issue_reveal(packet, T0)
    # Even if a packet reached B out of band and was logged, B's independent batch is refused.
    world["ledger"].append("reveal-issued", {"packetId": "leak", "recipientId": "ann-b", "units": sorted(unit_key("track", t, None) for t in tracks), "packetSha256": "e" * 64}, T0)
    batch_b = build_batch("batch-b", b, T0, _labels_for(b, _default_choice), None, world["task"])
    with pytest.raises(CorpusError, match="independence_violated"):
        world["ledger"].submit_batch(batch_b, b, T0)


def test_ledger_detects_tampering(world) -> None:
    _pilot(world)
    path = world["tmp"] / "annotation-ledger.jsonl"
    lines = path.read_text().splitlines()
    lines[2] = lines[2].replace("ann-a", "ann-z")
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(CorpusError, match="ledger_entry_tampered|ledger_chain_broken"):
        AnnotationLedger(path)


def test_batches_must_be_complete_and_valid(world) -> None:
    tracks = sample_pilot_tracks(world["corpus"], world["partition"], 2, "s")
    a = build_assignment("pilot-a", "ann-a", "pilot", "independent", [("track", t, None) for t in tracks], world["corpus"], world["partition"], world["psha"], world["task"], GUIDE)
    labels = _labels_for(a, _default_choice)
    with pytest.raises(CorpusError, match="batch_incomplete"):
        build_batch("b1", a, T0, labels[1:], None, world["task"])
    bad = copy.deepcopy(labels)
    bad[1]["value"] = "magenta"
    with pytest.raises(CorpusError, match="label_invalid"):
        build_batch("b1", a, T0, bad, None, world["task"])
    invalid_subject = copy.deepcopy(labels)
    invalid_subject[0]["value"] = "non-subject"
    with pytest.raises(CorpusError, match="batch_invalid_subject_has_value"):
        build_batch("b1", a, T0, invalid_subject, None, world["task"])


def test_csv_submission_round_trips() -> None:
    text = "unitKind,trackId,observationId,attributeType,outcome,value,unscorableReason\ntrack,00000000-0000-0000-0000-000000000001,,person-backpack,unscorable,,occluded\n"
    rows = labels_from_csv(text)
    assert rows == [{"unitKind": "track", "trackId": "00000000-0000-0000-0000-000000000001", "observationId": None, "attributeType": "person-backpack", "outcome": "unscorable", "value": None, "unscorableReason": "occluded"}]
    with pytest.raises(CorpusError, match="batch_csv_columns"):
        labels_from_csv("a,b\n1,2\n")


def _disagree_on_backpack(unit, attribute):
    if attribute == "person-backpack":
        return ("value", "present", None)
    return _default_choice(unit, attribute)


def test_conflicts_require_adjudication_and_originals_are_kept(world) -> None:
    """Mutation 9: adjudication never overwrites the original labels."""
    made, batches = _pilot(world, choose_b=_disagree_on_backpack)
    with pytest.raises(CorpusError, match="ground_truth_unresolved_conflicts"):
        build_ground_truth(world["corpus"], world["partition"], world["psha"], world["task"], batches, [], world["ledger"])
    conflict_units = sorted({l.unit for _, labels in batches for l in labels if l.attribute_type == "person-backpack"})
    packet = build_reveal_packet("reveal-1", "ann-a", conflict_units, batches)
    world["ledger"].issue_reveal(packet, T0)
    object_class = {unit_key(u["unitKind"], u["trackId"], u["observationId"]): u["objectClass"] for u in made["ann-a"]["units"]}
    adjudication = {
        "schemaVersion": "mavi-attribute-adjudication-v1",
        "adjudicationId": "adj-1",
        "adjudicatorId": "ann-a",
        "revealPacketSha256": document_sha256(packet),
        "decidedAt": T0,
        "decisions": [
            {"unit": u, "attributeType": "person-backpack", "outcome": "unscorable", "value": None, "unscorableReason": "ambiguous", "rationale": "strap only"}
            for u in conflict_units if object_class[u] == "person"
        ],
    }
    truth = build_ground_truth(world["corpus"], world["partition"], world["psha"], world["task"], batches, [parse_adjudication(adjudication, world["task"], object_class)], world["ledger"])
    row = next(r for r in truth["rows"] if r["attributeType"] == "person-backpack")
    assert row["resolution"] == "adjudicated"
    assert {l["value"] for l in row["labels"]} == {"absent", "present"}, "both original labels survive"
    # Mutation 10: unscorable stays unscorable — never silently a negative.
    assert row["final"] == {"outcome": "unscorable", "value": None, "unscorableReason": "ambiguous"}


def test_selection_view_refuses_frozen_labels(world) -> None:
    """Mutation 6: the evaluation view can never carry frozen-test rows."""
    rows = [{"unit": "u", "trackId": "t", "partition": "frozen-test"}]
    base = {"schemaVersion": "mavi-attribute-ground-truth-v1", "rows": rows, "view": "evaluation", "frozenExcluded": True}
    with pytest.raises(CorpusError, match="frozen_test_labels_refused"):
        load_evaluation_view(base)
    evaluation, frozen = split_ground_truth({"schemaVersion": "mavi-attribute-ground-truth-v1", "rows": rows + [{"unit": "v", "trackId": "t2", "partition": "tuning"}]}, None)
    assert [r["partition"] for r in load_evaluation_view(evaluation)] == ["tuning"]
    with pytest.raises(CorpusError, match="evaluation_view_not_frozen_excluded"):
        load_evaluation_view(frozen)


def test_agreement_report_on_a_known_disagreement(world) -> None:
    made, batches = _pilot(world, choose_b=_disagree_on_backpack)
    assignments = {a["assignmentId"]: a for a in made.values()}
    report = agreement_report("pilot", world["corpus"], world["partition"], world["psha"], world["task"].sha256, batches, assignments, world["ledger"].annotators(), set(), set(world["ledger"].batch_hashes()))
    verify_report_hash(report)
    backpack = next(a for a in report["attributes"] if a["attributeType"] == "person-backpack")
    assert backpack["full"]["rawAgreement"] == 0.0
    assert backpack["confusion"] == {"absent|present": backpack["doubleLabelledUnits"]}
    assert backpack["doubleLabelledWithIndependentAnnotator"] == backpack["doubleLabelledUnits"]
    headwear = next(a for a in report["attributes"] if a["attributeType"] == "person-headwear")
    assert headwear["unscorableRate"] == 1.0
    assert headwear["value"]["undefinedReason"] == "no_double_labelled_units"
    assert set(backpack["support"]["partition"]) == {"training"}
    assert "synthetic fixture" in render_markdown(report)


def test_pilot_report_and_freeze_apply_only_predeclared_changes(world) -> None:
    def confuse_grey_white(unit, attribute):
        if attribute == "person-upper-colour":
            return ("value", "grey", None)
        return _default_choice(unit, attribute)

    def white(unit, attribute):
        if attribute == "person-upper-colour":
            return ("value", "white", None)
        return _default_choice(unit, attribute)

    made, batches = _pilot(world, choose_a=confuse_grey_white, choose_b=white)
    assignments = {a["assignmentId"]: a for a in made.values()}
    registered = set(world["ledger"].batch_hashes())
    report = pilot_report(world["task"], world["corpus"], world["partition"], world["psha"], batches, assignments, world["ledger"].annotators(), registered)
    unregistered = build_batch("batch-x", made["ann-a"], T0, _labels_for(made["ann-a"], _default_choice), None, world["task"])
    with pytest.raises(CorpusError, match="agreement_batch_not_in_ledger"):
        pilot_report(world["task"], world["corpus"], world["partition"], world["psha"], [(unregistered, parse_batch(unregistered, made["ann-a"], world["task"])), batches[1]], assignments, world["ledger"].annotators(), registered)
    world2 = world
    merge = next(m for m in report["valueMergeRecommendations"] if m["attributeType"] == "person-upper-colour" and m["values"] == ["grey", "white"])
    assert merge["recommendMerge"] is True
    decision = {
        "schemaVersion": "mavi-attribute-task-freeze-decision-v1",
        "decidedBy": "owner-1",
        "decidedAt": "2026-10-09T09:00:00Z",
        "valueMerges": [{"attributeType": "person-upper-colour", "values": ["grey", "white"], "mergedValue": "grey"}],
        "attributeMerges": [],
        "valueRemovals": [{"attributeType": "person-upper-colour", "value": "multicolour"}],
        "attributeRemovals": ["person-headwear"],
        "rationale": "pilot confusion; headwear not labelable",
    }
    frozen = parse_task(task_module.freeze_task(world2["task"], report, decision))
    assert frozen.status == "frozen"
    assert "white" not in frozen.attribute("person-upper-colour").allowed_values
    assert "white" in frozen.attribute("person-lower-colour").allowed_values
    with pytest.raises(CorpusError):
        frozen.attribute("person-headwear")
    not_declared = copy.deepcopy(decision)
    not_declared["valueMerges"] = [{"attributeType": "person-upper-colour", "values": ["blue", "green"], "mergedValue": "blue"}]
    with pytest.raises(CorpusError, match="not_predeclared"):
        task_module.freeze_task(world2["task"], report, not_declared)
    new_name = copy.deepcopy(decision)
    new_name["valueMerges"][0]["mergedValue"] = "light"
    with pytest.raises(CorpusError, match="must_be_member"):
        task_module.freeze_task(world2["task"], report, new_name)
