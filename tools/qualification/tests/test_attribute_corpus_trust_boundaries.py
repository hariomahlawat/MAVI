"""S2c.1 trust boundaries: assignment completeness, canonical reveals, pilot-bound freezes.

Synthetic fixtures prove the tooling only; they are never corpus evidence.
"""

from __future__ import annotations

import copy

import pytest
from attribute_corpus_fixtures import passing_pilot_report
from test_attribute_corpus_annotation import (  # noqa: F401 - the ``world`` fixture
    GUIDE,
    T0,
    _adjudication,
    _assignments,
    _default_choice,
    _disagree_on_backpack,
    _labels_for,
    _pilot,
    world,
)

from attributes.corpus import task as task_module
from attributes.corpus.annotation import (
    AnnotationLedger,
    build_assignment,
    build_batch,
    build_ground_truth,
    build_reveal_packet,
    parse_adjudication,
    parse_batch,
    unit_key,
)
from attributes.corpus.canonical import CorpusError, document_sha256
from attributes.corpus.pilot import sample_pilot_tracks
from attributes.corpus.task import load_task, parse_task

DECISION = {
    "schemaVersion": "mavi-attribute-task-freeze-decision-v1",
    "decidedBy": "owner-1",
    "decidedAt": "2026-10-09T09:00:00Z",
    "valueMerges": [],
    "attributeMerges": [],
    "valueRemovals": [],
    "attributeRemovals": [],
    "rationale": "fixture decision",
}


# ---- P2-1: no issued assignment may be silently abandoned ------------------------------------


def _issue(world, name, annotator, phase, units, task=None):
    task = task or (world["task"] if phase == "pilot" else world["frozen"])
    assignment = build_assignment(name, annotator, phase, "independent", units, world["corpus"], world["partition"], world["psha"], task, GUIDE)
    world["ledger"].issue_assignment(assignment, T0)
    return assignment


def _submit(world, assignment, task=None, choose=_default_choice):
    task = task or (world["task"] if assignment["phase"] == "pilot" else world["frozen"])
    batch = build_batch(f"batch-{assignment['assignmentId']}", assignment, T0, _labels_for(assignment, choose), None, task)
    world["ledger"].submit_batch(batch, assignment, T0)
    return batch, parse_batch(batch, assignment, task)


def test_an_unsubmitted_main_assignment_blocks_ground_truth(world) -> None:
    made, batches = _pilot(world, phase="main")
    track = sorted(world["corpus"].tracks)[-1]
    _issue(world, "main-extra", "ann-a", "main", [("track", track, None)])  # issued, never submitted
    with pytest.raises(CorpusError, match="ledger_assignments_unsubmitted:main:1"):
        build_ground_truth(world["corpus"], world["partition"], world["psha"], world["frozen"], batches, [], world["ledger"], _assignments(made))


def test_an_unsubmitted_pilot_assignment_blocks_pilot_completeness(world) -> None:
    _pilot(world)
    track = sample_pilot_tracks(world["corpus"], world["partition"], 60, "other")[-1]
    _issue(world, "pilot-extra", "ann-b", "pilot", [("track", track, None)])
    with pytest.raises(CorpusError, match="ledger_assignments_unsubmitted:pilot:1"):
        world["ledger"].require_phase_complete("pilot")
    world["ledger"].require_phase_complete("main")  # other phases unaffected


def test_every_issued_assignment_submitted_once_passes_and_duplicates_are_refused(world) -> None:
    made, batches = _pilot(world, phase="main")
    world["ledger"].require_phase_complete("main")
    build_ground_truth(world["corpus"], world["partition"], world["psha"], world["frozen"], batches, [], world["ledger"], _assignments(made))
    again = build_batch("batch-again", made["ann-a"], T0, _labels_for(made["ann-a"], _default_choice), None, world["frozen"])
    with pytest.raises(CorpusError, match="ledger_batch_already_submitted"):
        world["ledger"].submit_batch(again, made["ann-a"], T0)


def test_cancellation_only_for_an_identical_replacement_before_any_label_is_visible(world) -> None:
    world["ledger"].register_annotator("ann-c", True, T0)
    world["ledger"].register_annotator("ann-d", True, T0)
    units = [("track", t, None) for t in sorted(world["corpus"].tracks)[:3]]
    leaving = _issue(world, "main-leaving", "ann-a", "main", units)
    other = _issue(world, "main-b", "ann-b", "main", units)
    with pytest.raises(CorpusError, match="ledger_cancel_requires_replacement"):
        world["ledger"].cancel_assignment("main-leaving", "custodian-1", "annotator left", "no-such", T0)
    narrower = _issue(world, "main-narrow", "ann-d", "main", units[:2])
    with pytest.raises(CorpusError, match="ledger_cancel_replacement_mismatch"):
        world["ledger"].cancel_assignment("main-leaving", "custodian-1", "annotator left", narrower["assignmentId"], T0)
    _submit(world, narrower)
    replacement = _issue(world, "main-c", "ann-c", "main", units)
    world["ledger"].cancel_assignment("main-leaving", "custodian-1", "annotator left", replacement["assignmentId"], T0)
    with pytest.raises(CorpusError, match="ledger_batch_assignment_cancelled"):
        _submit(world, leaving)
    with pytest.raises(CorpusError, match="ledger_cancel_duplicate"):
        world["ledger"].cancel_assignment("main-leaving", "custodian-1", "again", replacement["assignmentId"], T0)
    with pytest.raises(CorpusError, match="ledger_assignments_unsubmitted:main:2"):
        world["ledger"].require_phase_complete("main")  # the replacement and ann-b are still open
    _submit(world, other)
    _submit(world, replacement)
    world["ledger"].require_phase_complete("main")


def test_late_cancellation_after_labels_or_a_reveal_is_refused(world) -> None:
    world["ledger"].register_annotator("ann-c", True, T0)
    units = [("track", t, None) for t in sorted(world["corpus"].tracks)[:3]]
    a = _issue(world, "main-a", "ann-a", "main", units)
    b = _issue(world, "main-b", "ann-b", "main", units)
    replacement_a = _issue(world, "main-ca", "ann-c", "main", units)
    batch_a = _submit(world, a)[0]
    with pytest.raises(CorpusError, match="ledger_cancel_after_submission"):  # its labels exist
        world["ledger"].cancel_assignment("main-a", "custodian-1", "unfavourable labels", replacement_a["assignmentId"], T0)
    batch_b = _submit(world, b)[0]
    batch_c = _submit(world, replacement_a)[0]
    keys = [unit_key(*u) for u in units]
    shown = [batch_a, batch_b, batch_c]
    world["ledger"].issue_reveal(build_reveal_packet("reveal-1", "ann-c", keys, "main", shown), shown, T0)
    world["ledger"].register_annotator("ann-e", True, T0)
    world["ledger"].register_annotator("ann-f", True, T0)
    late = _issue(world, "main-late", "ann-e", "main", units)
    replacement_late = _issue(world, "main-late-f", "ann-f", "main", units)
    with pytest.raises(CorpusError, match="ledger_cancel_after_reveal"):
        world["ledger"].cancel_assignment(late["assignmentId"], "custodian-1", "after the reveal", replacement_late["assignmentId"], T0)


# ---- P2-2: a reveal is canonical and an adjudication resolves a real conflict ---------------


def _conflict(world):
    made, batches = _pilot(world, choose_b=_disagree_on_backpack, phase="main")
    object_class = {unit_key(u["unitKind"], u["trackId"], u["observationId"]): u["objectClass"] for u in made["ann-a"]["units"]}
    units = sorted({l.unit for _, labels in batches for l in labels if l.attribute_type == "person-backpack"})
    return made, batches, object_class, units


def test_a_reveal_omitting_a_submitted_batch_is_refused(world) -> None:
    made, batches, _, units = _conflict(world)
    only_a = [batches[0][0]]
    favourable = build_reveal_packet("reveal-1", "ann-a", units, "main", only_a)
    with pytest.raises(CorpusError, match="ledger_reveal_batches_incomplete:1"):
        world["ledger"].issue_reveal(favourable, only_a, T0)
    everything = [b for b, _ in batches]
    trimmed = build_reveal_packet("reveal-1", "ann-a", units, "main", everything)
    trimmed["labels"] = [l for l in trimmed["labels"] if l["annotatorId"] == "ann-a"]
    with pytest.raises(CorpusError, match="ledger_reveal_packet_not_canonical"):
        world["ledger"].issue_reveal(trimmed, everything, T0)


def test_adjudication_is_limited_to_real_conflicts_in_the_packet(world) -> None:
    made, batches, object_class, units = _conflict(world)
    everything = [b for b, _ in batches]
    packet = build_reveal_packet("reveal-1", "ann-a", units, "main", everything)
    assert packet["conflictKeys"] and all(k.endswith("|person-backpack") for k in packet["conflictKeys"])
    world["ledger"].issue_reveal(packet, everything, T0)
    consensus = _adjudication(packet, "ann-a", units[:1], object_class)
    consensus["decisions"][0]["attributeType"] = "person-bag"  # both annotators agreed on it
    with pytest.raises(CorpusError, match="ledger_adjudication_without_conflict"):
        world["ledger"].record_adjudication(consensus, T0)
    elsewhere = _adjudication(packet, "ann-a", units[:1], object_class)
    elsewhere["decisions"][0]["attributeType"] = "person-upper-colour"  # never in conflict
    with pytest.raises(CorpusError, match="ledger_adjudication_without_conflict"):
        world["ledger"].record_adjudication(elsewhere, T0)
    forged_hash = dict(_adjudication(packet, "ann-a", units, object_class), revealPacketSha256="e" * 64)
    with pytest.raises(CorpusError, match="ledger_adjudication_packet_not_issued"):
        world["ledger"].record_adjudication(forged_hash, T0)
    genuine = _adjudication(packet, "ann-a", units, object_class)
    world["ledger"].record_adjudication(genuine, T0)
    truth = build_ground_truth(world["corpus"], world["partition"], world["psha"], world["frozen"], batches, [parse_adjudication(genuine, world["frozen"], object_class)], world["ledger"], _assignments(made))
    assert {r["resolution"] for r in truth["rows"] if r["attributeType"] == "person-backpack"} == {"adjudicated"}


def test_ground_truth_refuses_an_adjudication_that_overrides_consensus(world) -> None:
    """Even if a ledger entry were hand-made, ground truth refuses a consensus override."""
    made, batches = _pilot(world, phase="main")
    object_class = {unit_key(u["unitKind"], u["trackId"], u["observationId"]): u["objectClass"] for u in made["ann-a"]["units"]}
    unit = next(u for u, c in sorted(object_class.items()) if c == "person")
    override = _adjudication({"packetId": "x"}, "ann-a", [unit], object_class)
    override["revealPacketSha256"] = "f" * 64
    sha = document_sha256(override)
    world["ledger"].append("adjudication-recorded", {"adjudicationId": "adj-1", "adjudicatorId": "ann-a", "adjudicationSha256": sha, "keys": [f"{unit}|person-backpack"], "supersedes": None}, T0)
    with pytest.raises(CorpusError, match="ground_truth_adjudication_without_conflict"):
        build_ground_truth(world["corpus"], world["partition"], world["psha"], world["frozen"], batches, [parse_adjudication(override, world["frozen"], object_class)], world["ledger"], _assignments(made))


# ---- P2-3: the frozen task must follow the pilot's verdicts ----------------------------------


def _candidate():
    return parse_task(task_module.confirm_rules(load_task().document, "owner-1", "2026-10-01T09:00:00Z"))


def _decision(**changes):
    decision = copy.deepcopy(DECISION)
    decision.update(changes)
    return decision


def test_a_passing_attribute_may_be_retained() -> None:
    candidate = _candidate()
    frozen = parse_task(task_module.freeze_task(candidate, passing_pilot_report(candidate), _decision()))
    assert frozen.attribute("person-backpack")


def test_a_failing_attribute_is_removed_or_merged_never_retained() -> None:
    candidate = _candidate()
    report = passing_pilot_report(candidate, {"person-backpack": {"value": {"krippendorffAlpha": 0.3}}})
    with pytest.raises(CorpusError, match="freeze_failing_attribute_retained:person-backpack"):
        task_module.freeze_task(candidate, report, _decision())
    frozen = parse_task(task_module.freeze_task(candidate, report, _decision(attributeRemovals=["person-backpack"])))
    with pytest.raises(CorpusError):
        frozen.attribute("person-backpack")
    # A pre-declared attribute merge resolves it only if the pilot recommended that merge.
    merge = _decision(attributeMerges=[{"attributeTypes": ["person-backpack", "person-bag"]}])
    with pytest.raises(CorpusError, match="freeze_failing_attribute_retained:person-backpack"):
        task_module.freeze_task(candidate, report, merge)
    recommended = copy.deepcopy(report)
    recommended["attributeMergeRecommendations"] = [{"attributeTypes": ["person-backpack", "person-bag"], "recommendMerge": True}]
    del recommended["reportSha256"]
    recommended["reportSha256"] = document_sha256(recommended)
    assert parse_task(task_module.freeze_task(candidate, recommended, merge)).attribute("person-carried-bag")


def test_a_value_merge_resolves_only_a_value_agreement_failure_it_was_recommended_for() -> None:
    candidate = _candidate()
    merge = _decision(valueMerges=[{"attributeType": "person-upper-colour", "values": ["grey", "white"], "mergedValue": "grey"}])

    def report(stats, recommend):
        document = passing_pilot_report(candidate, {"person-upper-colour": stats})
        document["valueMergeRecommendations"] = [{"attributeType": "person-upper-colour", "values": ["grey", "white"], "recommendMerge": recommend}]
        del document["reportSha256"]
        document["reportSha256"] = document_sha256(document)
        return document

    value_failure = {"value": {"krippendorffAlpha": 0.4}}
    assert "grey" in parse_task(task_module.freeze_task(candidate, report(value_failure, True), merge)).attribute("person-upper-colour").allowed_values
    with pytest.raises(CorpusError, match="freeze_failing_attribute_retained:person-upper-colour"):
        task_module.freeze_task(candidate, report(value_failure, False), merge)
    scorability_failure = {"value": {"krippendorffAlpha": 0.4}, "scorability": {"krippendorffAlpha": 0.2}}
    with pytest.raises(CorpusError, match="freeze_failing_attribute_retained:person-upper-colour"):
        task_module.freeze_task(candidate, report(scorability_failure, True), merge)


def test_insufficient_pilot_evidence_is_never_an_implicit_pass() -> None:
    candidate = _candidate()
    thin = passing_pilot_report(candidate, {"vehicle-colour": {"doubleLabelledUnits": 10}})
    with pytest.raises(CorpusError, match="freeze_unresolved_insufficient_evidence:vehicle-colour"):
        task_module.freeze_task(candidate, thin, _decision())
    unlabelled = passing_pilot_report(candidate, {"vehicle-colour": None})
    with pytest.raises(CorpusError, match="freeze_unresolved_insufficient_evidence:vehicle-colour"):
        task_module.freeze_task(candidate, unlabelled, _decision())
    task_module.freeze_task(candidate, thin, _decision(attributeRemovals=["vehicle-colour"]))


def test_pilot_thresholds_cannot_be_lowered_after_the_pilot() -> None:
    candidate = _candidate()
    report = passing_pilot_report(candidate, {"person-backpack": {"value": {"krippendorffAlpha": 0.5}}})
    lowered = copy.deepcopy(report)
    lowered["pilotDecisionRules"]["minimumValueAlpha"] = 0.4  # would turn the failure into "keep"
    del lowered["reportSha256"]
    lowered["reportSha256"] = document_sha256(lowered)
    with pytest.raises(CorpusError, match="freeze_pilot_rules_differ_from_confirmed"):
        task_module.freeze_task(candidate, lowered, _decision())
    with pytest.raises(CorpusError, match="rules_override_lowers"):
        task_module.confirm_rules(load_task().document, "owner-1", "2026-10-01T09:00:00Z", {"minimumValueAlpha": 0.4})


# ---- the ledger is re-checked, not trusted (second focused review) ---------------------------


def _loader(*documents):
    by_sha = {document_sha256(d): d for d in documents}

    def load(sha, what):
        if sha not in by_sha:
            raise CorpusError(f"f1_record_missing:{what}")
        return by_sha[sha]

    return load


def test_replay_accepts_the_tool_written_ledger(world) -> None:
    made, batches = _pilot(world, choose_b=_disagree_on_backpack, phase="main")
    AnnotationLedger.replay(world["ledger"].entries, _loader(*made.values(), *(b for b, _ in batches)))


def test_replay_refuses_a_hand_written_cancellation(world) -> None:
    """A cancellation the tool would refuse (no fresh replacement) cannot shrink the sample."""
    units = [("track", t, None) for t in sorted(world["corpus"].tracks)[:3]]
    a = _issue(world, "main-a", "ann-a", "main", units)
    b = _issue(world, "main-b", "ann-b", "main", units)
    batch_a = _submit(world, a)[0]
    world["ledger"].append("assignment-cancelled", {"assignmentId": "main-b", "actor": "custodian-1", "reason": "hand-written", "replacementAssignmentId": "no-such"}, T0)
    world["ledger"].require_phase_complete("main")  # the ledger alone is fooled...
    with pytest.raises(CorpusError, match="ledger_cancel_requires_replacement"):
        AnnotationLedger.replay(world["ledger"].entries, _loader(a, b, batch_a))  # ...the replay is not


def test_replay_refuses_adjudications_the_tool_would_refuse(world) -> None:
    made, batches, object_class, units = _conflict(world)
    documents = [b for b, _ in batches]
    # On a packet never issued, by someone who is not its recipient:
    packet = build_reveal_packet("reveal-x", "ann-b", units[:1], "main", documents)
    forged = _adjudication(packet, "ann-a", units, object_class)
    world["ledger"].append("adjudication-recorded", {"adjudicationId": forged["adjudicationId"], "adjudicatorId": "ann-a", "adjudicationSha256": document_sha256(forged), "keys": sorted(f"{u}|person-backpack" for u in units), "supersedes": None}, T0)
    with pytest.raises(CorpusError, match="ledger_adjudication_packet_not_issued"):
        AnnotationLedger.replay(world["ledger"].entries, _loader(*made.values(), *documents, packet, forged))


def test_ground_truth_refuses_a_reason_only_override(world) -> None:
    def other_reason(unit, attribute):
        return ("unscorable", None, "occluded") if attribute == "person-headwear" else _default_choice(unit, attribute)

    made, batches = _pilot(world, choose_b=other_reason, phase="main")
    object_class = {unit_key(u["unitKind"], u["trackId"], u["observationId"]): u["objectClass"] for u in made["ann-a"]["units"]}
    unit = next(u for u, c in sorted(object_class.items()) if c == "person")
    override = _adjudication({"packetId": "x"}, "ann-a", [unit], object_class)
    override["decisions"] = [{"unit": unit, "attributeType": "person-headwear", "outcome": "value", "value": "present", "unscorableReason": None, "rationale": "override"}]
    override["revealPacketSha256"] = "f" * 64
    world["ledger"].append("adjudication-recorded", {"adjudicationId": "adj-1", "adjudicatorId": "ann-a", "adjudicationSha256": document_sha256(override), "keys": [f"{unit}|person-headwear"], "supersedes": None}, T0)
    with pytest.raises(CorpusError, match="ground_truth_adjudication_overrides_consensus"):
        build_ground_truth(world["corpus"], world["partition"], world["psha"], world["frozen"], batches, [parse_adjudication(override, world["frozen"], object_class)], world["ledger"], _assignments(made))


def test_cancellation_cannot_use_another_raters_assignment_as_the_replacement(world) -> None:
    """Otherwise rater 2's pending double label could be dropped after seeing rater 1's."""
    units = [("track", t, None) for t in sorted(world["corpus"].tracks)[:3]]
    a = _issue(world, "main-a", "ann-a", "main", units)
    _issue(world, "main-b", "ann-b", "main", units)
    _submit(world, a)
    with pytest.raises(CorpusError, match="ledger_cancel_replacement_not_fresh"):
        world["ledger"].cancel_assignment("main-b", "custodian-1", "prefer rater 1", "main-a", T0)
    again = _issue(world, "main-a2", "ann-a", "main", units)  # fresh, but ann-a already labels them
    with pytest.raises(CorpusError, match="ledger_cancel_replacement_annotator_already_labels_these_units"):
        world["ledger"].cancel_assignment("main-b", "custodian-1", "prefer rater 1", again["assignmentId"], T0)


def test_units_can_be_revealed_after_a_legitimate_cancellation(world) -> None:
    world["ledger"].register_annotator("ann-c", True, T0)
    units = [("track", t, None) for t in sorted(world["corpus"].tracks)[:3]]
    a = _issue(world, "main-a", "ann-a", "main", units)
    _issue(world, "main-b", "ann-b", "main", units)
    c = _issue(world, "main-c", "ann-c", "main", units)
    world["ledger"].cancel_assignment("main-b", "custodian-1", "annotator left", "main-c", T0)
    shown = [_submit(world, a)[0], _submit(world, c, choose=_disagree_on_backpack)[0]]
    packet = build_reveal_packet("reveal-1", "ann-a", [unit_key(*u) for u in units], "main", shown)
    world["ledger"].issue_reveal(packet, shown, T0)


def test_replay_refuses_a_reveal_entry_with_invented_conflict_keys(world) -> None:
    """The packet is canonical, but the recorded conflict keys were widened by hand so that a
    consensus key could later be "adjudicated": the payload is not what the rule computes."""
    made, batches, object_class, units = _conflict(world)
    documents = [b for b, _ in batches]
    packet = build_reveal_packet("reveal-1", "ann-a", units, "main", documents)
    payload = world["ledger"]._p_reveal(packet, documents)
    payload["conflictKeys"] = sorted([*payload["conflictKeys"], f"{units[0]}|person-bag"])
    world["ledger"].append("reveal-issued", payload, T0)
    with pytest.raises(CorpusError, match="ledger_replay_payload_mismatch"):
        AnnotationLedger.replay(world["ledger"].entries, _loader(*made.values(), *documents, packet))


def test_one_replacement_cannot_cover_several_cancellations(world) -> None:
    world["ledger"].register_annotator("ann-c", True, T0)
    world["ledger"].register_annotator("ann-d", True, T0)
    units = [("track", t, None) for t in sorted(world["corpus"].tracks)[:3]]
    _issue(world, "main-a", "ann-a", "main", units)
    _issue(world, "main-b", "ann-b", "main", units)
    _issue(world, "main-c", "ann-c", "main", units)
    world["ledger"].cancel_assignment("main-a", "custodian-1", "annotator left", "main-c", T0)
    with pytest.raises(CorpusError, match="ledger_cancel_replacement_already_used"):
        world["ledger"].cancel_assignment("main-b", "custodian-1", "annotator left", "main-c", T0)
