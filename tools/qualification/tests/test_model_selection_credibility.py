"""Discriminating tests for the candidate credibility gate (candidate-credibility.md).

Each test breaks exactly one rule of an otherwise valid synthetic ledger or decision
summary and asserts the specific refusal code, so removing a guard fails its test.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from model_selection.credibility import (
    CredibilityError,
    credibility_class,
    document_sha256,
    validate_decision,
    validate_ledger,
    validate_repository,
)
from model_selection_fixtures import (
    baseline,
    claim,
    commit,
    decision,
    emerging,
    established,
    evidence,
    excluded,
    exact,
    items,
    ledger,
    method,
    reference,
    settle,
    sha,
)

REPO = Path(__file__).resolve().parents[3]
CHECK = REPO / "tools" / "qualification" / "model_selection_check.py"


def refused(code, function, *args):
    with pytest.raises(CredibilityError) as caught:
        function(*args)
    assert str(caught.value).split(":", 1)[0] == code, str(caught.value)


def entry_of(document, candidate_id):
    return next(e for e in document["candidates"] if e["candidateId"] == candidate_id)


def resettle(document, candidate_id, at="2026-10-05"):
    settle(entry_of(document, candidate_id), at=at)
    return document


# ------------------------------------------------------------------ baseline fixture


def test_synthetic_ledger_classifies_every_category():
    summary = validate_ledger(ledger())
    assert {c: s["class"] for c, s in summary.items()} == {
        "VC-B0": "mavi-owned",
        "VC-EST": "established",
        "VC-EMG": "emerging",
        "VC-REF": "reference-only",
        "VC-EXC": "excluded-discovery",
        "VC-MTH": "emerging",
    }
    assert summary["VC-MTH"]["provenanceConfidence"] == "Medium"
    assert summary["VC-REF"]["provenanceConfidence"] == "Low"


def test_classification_is_deterministic_and_order_independent():
    first = ledger()
    second = copy.deepcopy(first)
    for entry in second["candidates"]:
        entry["evidence"].reverse()
    assert validate_ledger(first) == validate_ledger(second)


# ------------------------------------------------------------ I3: computed, not asserted


def test_declared_class_must_equal_computed_class():
    document = ledger()
    entry_of(document, "VC-EMG")["classification"]["class"] = "established"
    refused("declared_class_differs_from_computed", validate_ledger, document)


def test_declared_confidence_must_equal_computed():
    document = ledger()
    entry_of(document, "VC-REF")["classification"]["provenanceConfidence"] = "High"
    refused("declared_confidence_differs_from_computed", validate_ledger, document)


# ------------------------------------------------------------- I2: benchmark laundering


def test_five_repetitions_of_one_readme_figure_do_not_establish():
    entry = emerging()
    assert credibility_class(entry, items(entry)) == "emerging"
    # even with established-grade publication, repetitions count for nothing
    entry["publication"] = established()["publication"]
    assert credibility_class(entry, items(entry)) == "emerging"


def test_claim_origin_must_be_the_root_not_a_repetition():
    entry = emerging()
    entry["claims"][0]["originEvidenceId"] = "E-COPY0"
    refused("claim_origin_is_repetition", validate_ledger, ledger(entry))


def test_repetition_must_name_what_it_repeats():
    entry = emerging()
    del entry["evidence"][1]["repeats"]
    refused("repetition_without_origin", validate_ledger, ledger(entry))


def test_repetition_chain_cycle_is_refused():
    entry = emerging()
    entry["evidence"][1]["repeats"] = "E-COPY2"
    entry["evidence"][3]["repeats"] = "E-COPY0"
    refused("repetition_cycle", validate_ledger, ledger(entry))


def test_repetition_cannot_be_dressed_as_reproduction_fields():
    entry = emerging()
    entry["evidence"][1]["scope"] = "method"
    refused("repetition_cannot_carry", validate_ledger, ledger(entry))


def test_independent_item_reusing_first_party_source_is_refused():
    entry = established()
    entry["evidence"][1]["source"] = entry["evidence"][0]["source"] + "/"
    refused("independent_evidence_reuses_first_party_source", validate_ledger, ledger(entry))


def test_independent_producer_cannot_be_an_author_group():
    entry = established()
    entry["evidence"][1]["producer"]["group"] = "est-lab"
    refused("independent_producer_is_author", validate_ledger, ledger(entry))


def test_independent_evidence_requires_independent_relation():
    entry = established()
    entry["evidence"][1]["producer"]["relation"] = "author-affiliated"
    refused("independent_evidence_not_independent", validate_ledger, ledger(entry))


def test_first_party_claim_cannot_be_labelled_independent():
    entry = established()
    entry["evidence"][0]["producer"] = {"group": "someone-else", "relation": "independent"}
    refused("first_party_claim_not_from_authors", validate_ledger, ledger(entry))


def test_one_group_counts_once():
    entry = established()
    entry["evidence"][2]["producer"]["group"] = "other-lab"  # adoption from the reproducing group
    assert credibility_class(entry, items(entry)) == "emerging"


def test_adoption_alone_is_not_independent_technical_evidence():
    entry = established()
    entry["evidence"][1] = evidence("E-ADOPT2", "adoption", "third-team", "independent",
                                    scope="method", independenceBasis="separate")
    assert credibility_class(entry, items(entry)) == "emerging"


def test_popularity_signals_are_never_counted():
    entry = emerging()
    entry["popularitySignals"] = [
        {"signal": s, "value": "1000000", "observedOn": "2026-10-01", "source": "https://example.invalid/x"}
        for s in ("github-stars", "downloads", "citations")
    ]
    assert credibility_class(entry, items(entry)) == "emerging"
    validate_ledger(ledger(entry))


def test_checkpoint_needs_exact_scope_independent_technical_evidence():
    entry = established()
    entry["evidence"][1]["scope"] = "method"
    del entry["evidence"][1]["reproducedArtefact"]
    assert credibility_class(entry, items(entry)) == "emerging"
    method_entry = method()
    method_entry["identity"]["publisher"] = "original-organisation"
    method_entry["identity"]["derivation"] = None
    method_entry["evidence"] += [
        evidence("E-BENCH", "independent-benchmark", "bench-server", "independent", scope="method",
                 independenceBasis="server computes the score"),
        evidence("E-ADOPT", "adoption", "framework-team", "independent", scope="method", independenceBasis="separate"),
    ]
    assert credibility_class(method_entry, items(method_entry)) == "established"


def test_benchmark_server_scope_is_method():
    entry = established()
    entry["evidence"][1]["type"] = "independent-benchmark"
    refused("benchmark_scope_is_method", validate_ledger, ledger(entry))


def test_established_requires_recognised_publication():
    entry = established()
    entry["publication"] = {"status": "preprint", "venue": None, "reference": "https://example.invalid/p", "basis": None}
    assert credibility_class(entry, items(entry)) == "emerging"


def test_peer_reviewed_requires_venue_and_established_preprint_requires_basis():
    entry = established()
    entry["publication"]["venue"] = None
    refused("text_required", validate_ledger, ledger(entry))
    entry = established()
    entry["publication"] = {"status": "preprint-established-group", "venue": None,
                            "reference": "https://example.invalid/p", "basis": None}
    refused("text_required", validate_ledger, ledger(entry))


# ------------------------------------------------------------ I1: provenance and shortlist


def test_third_party_upload_cannot_be_shortlisted():
    entry = reference()
    entry["disposition"] = established()["disposition"]
    refused("disposition_not_allowed_for_class", validate_ledger, ledger(entry))


def test_unpinned_checkpoint_is_low_confidence_and_cannot_be_shortlisted():
    entry = established()
    entry["identity"]["files"][0]["sha256"] = "UNKNOWN"
    assert credibility_class(entry, items(entry)) == "reference-only"
    entry = established()
    entry["identity"]["revision"] = "v1.0"  # a floating tag is not immutable
    assert credibility_class(entry, items(entry)) == "reference-only"


def test_unknown_source_is_excluded_discovery():
    entry = established()
    entry["identity"]["repository"] = "UNKNOWN"
    assert credibility_class(entry, items(entry)) == "excluded-discovery"
    entry = established()
    entry["authors"]["groups"] = []
    entry["evidence"] = [evidence("E-PAPER", "first-party-claim", "x", "author-affiliated")]
    assert credibility_class(entry, items(entry)) == "excluded-discovery"


def test_integrity_conflict_excludes():
    entry = established()
    entry["identity"]["integrityConflict"] = "retrieved bytes differ from the published hash"
    assert credibility_class(entry, items(entry)) == "excluded-discovery"


def test_excluded_discovery_can_only_be_not_shortlisted_for_credibility():
    entry = excluded()
    entry["disposition"] = reference()["disposition"]
    refused("disposition_not_allowed_for_class", validate_ledger, ledger(entry))
    entry = excluded()
    entry["disposition"]["reasonClass"] = "technical"
    refused("excluded_discovery_reason_is_credibility", validate_ledger, ledger(entry))


def test_undocumented_architecture_is_reference_only():
    entry = established()
    entry["architecture"]["documentedBy"] = None
    assert credibility_class(entry, items(entry)) == "reference-only"


def test_architecture_documented_by_a_repetition_does_not_count():
    entry = emerging()
    entry["architecture"]["documentedBy"] = "E-COPY0"
    assert credibility_class(entry, items(entry)) == "reference-only"


def test_no_quality_claim_is_reference_only():
    entry = established()
    entry["claims"] = []
    assert credibility_class(entry, items(entry)) == "reference-only"


def test_framework_conversion_without_documented_derivation_is_low():
    entry = method()
    entry["identity"]["derivation"]["fromSha256"] = "UNKNOWN"
    assert credibility_class(entry, items(entry)) == "reference-only"
    entry = method()
    entry["identity"]["derivation"] = None
    refused("derivation_required", validate_ledger, ledger(entry))


def test_medium_provenance_never_reaches_established():
    entry = method()
    entry["evidence"] += established()["evidence"][2:]
    entry["evidence"].append(evidence("E-BENCH", "independent-benchmark", "bench", "independent",
                                      scope="method", independenceBasis="server"))
    assert credibility_class(entry, items(entry)) == "emerging"


def test_shortlist_requires_snapshotted_claim_origin():
    entry = established()
    entry["evidence"][0]["retrievedSha256"] = "UNKNOWN"
    refused("shortlist_requires_snapshotted_claims", validate_ledger, ledger(entry))


def test_method_shortlist_requires_immutable_code_revision():
    entry = method()
    entry["methodCode"]["revision"] = "main"
    refused("shortlist_requires_method_revision", validate_ledger, ledger(entry))


def test_credibility_reason_must_match_evidence():
    entry = emerging()
    entry["disposition"] = reference()["disposition"]
    refused("credibility_reason_contradicts_evidence", validate_ledger, ledger(entry))


def test_evaluation_permission_reference_only_keeps_computed_class():
    entry = established()
    entry["disposition"] = dict(reference()["disposition"], reasonClass="evaluation-permission",
                                reason="evaluation not permitted by its terms")
    assert validate_ledger(ledger(entry))["VC-EST"]["class"] == "established"


def test_not_shortlisted_needs_reason_and_reference_only_needs_revisit_trigger():
    entry = established()
    entry["disposition"] = {"status": "NOT_SHORTLISTED", "reasonClass": "technical", "reason": None,
                            "revisitTrigger": None, "decidedBy": "r"}
    refused("text_required", validate_ledger, ledger(entry))
    entry = reference()
    entry["disposition"]["revisitTrigger"] = None
    refused("text_required", validate_ledger, ledger(entry))


# ------------------------------------------------------- I9/I12: no bake-off, no licence


@pytest.mark.parametrize("status", ["EVALUATED", "TECHNICALLY_SELECTED", "TECHNICAL_ALTERNATIVE", "REJECTED_TECHNICAL"])
def test_ledger_cannot_record_a_bake_off_outcome(status):
    document = ledger()
    entry_of(document, "VC-EST")["disposition"]["status"] = status
    refused("value_not_allowed", validate_ledger, document)


def test_ledger_rejects_mavi_measurement_fields():
    document = ledger()
    entry_of(document, "VC-EST")["maviResult"] = {"aurc": 0.1}
    refused("unknown_field", validate_ledger, document)
    document = ledger()
    entry_of(document, "VC-EST")["evidence"][0]["type"] = "mavi-measurement"
    refused("value_not_allowed", validate_ledger, document)


@pytest.mark.parametrize("key", ["licence", "weightsLicense", "licenceStatus"])
def test_ledger_has_no_licence_field_anywhere(key):
    document = ledger()
    entry_of(document, "VC-EST")["identity"][key] = "CLEARED"
    refused("licence_field_in_ledger", validate_ledger, document)


def test_licence_never_changes_classification():
    entry = established()
    before = credibility_class(entry, items(entry))
    document = ledger(entry)
    decision_a = decision(ledger(baseline(), established(), emerging(), method()))
    assert before == validate_ledger(document)["VC-EST"]["class"] == "established"
    assert "licence" not in json.dumps(document).lower() and "licence" in json.dumps(decision_a)


# --------------------------------------------------- I8/I10: history, promotion, identity


def test_new_evidence_that_changes_class_needs_a_history_entry():
    entry = settle(emerging())
    entry["evidence"] += [
        evidence("E-REPRO", "independent-reproduction", "other-lab", "independent", recorded="2026-10-03",
                 scope="exact-checkpoint", reproducedArtefact=exact("emg"), independenceBasis="no shared authors"),
        evidence("E-ADOPT", "adoption", "framework-team", "independent", recorded="2026-10-03",
                 scope="method", independenceBasis="separate"),
    ]
    entry["publication"] = established()["publication"]
    document = ledger(baseline())
    document["candidates"].append(entry)
    entry["classification"] = {"class": "established", "provenanceConfidence": "High"}
    refused("class_change_not_recorded", validate_ledger, document)
    settle(entry, at="2026-10-04", reason="independent reproduction and adoption recorded")
    assert validate_ledger(document)["VC-EMG"]["class"] == "established"
    assert [r["to"] for r in entry["classificationHistory"]] == ["emerging", "established"]


def test_promotion_cannot_be_backdated_ahead_of_its_evidence():
    entry = established()
    for item in entry["evidence"][1:]:
        item["recordedAt"] = "2026-10-10"
    document = ledger(entry)  # settle() dated 2026-10-02, before the independent evidence
    refused("promotion_not_supported_on_date", validate_ledger, document)


def test_history_cannot_cite_evidence_recorded_later():
    document = ledger()
    entry = entry_of(document, "VC-EMG")
    entry["evidence"][1]["recordedAt"] = "2026-11-01"
    refused("history_cites_later_evidence", validate_ledger, document)


def test_history_must_chain_and_be_reviewed_by_someone_else():
    document = ledger()
    entry_of(document, "VC-EST")["classificationHistory"][0]["reviewedBy"] = "synthetic-curator"
    refused("history_reviewer_not_independent", validate_ledger, document)
    document = ledger()
    entry_of(document, "VC-EST")["classificationHistory"][0]["from"] = "emerging"
    refused("history_chain_broken", validate_ledger, document)


def test_history_is_required():
    document = ledger()
    entry_of(document, "VC-EST")["classificationHistory"] = []
    refused("history_required", validate_ledger, document)


def test_identity_edit_without_history_entry_is_refused():
    document = ledger()
    entry_of(document, "VC-EST")["identity"]["tag"] = "v1.1"
    refused("identity_change_not_recorded", validate_ledger, document)


def test_same_name_different_checkpoint_needs_a_new_entry():
    document = ledger()
    entry = entry_of(document, "VC-EST")
    entry["identity"]["files"][0]["sha256"] = sha("weights-est-v2")
    entry["evidence"][1]["reproducedArtefact"] = {"sha256": sha("weights-est-v2")}
    settle(entry, at="2026-10-06", reason="upstream replaced the weights")
    refused("checkpoint_changed_under_same_candidate", validate_ledger, document)


def test_exact_scope_evidence_must_name_the_same_bytes():
    entry = established()
    entry["evidence"][1]["reproducedArtefact"] = {"sha256": sha("some-other-weights")}
    refused("evidence_artefact_mismatch", validate_ledger, ledger(entry))
    entry = established()
    entry["evidence"][1]["reproducedArtefact"] = {"repository": entry["identity"]["repository"],
                                                   "revision": commit("other")}
    refused("evidence_artefact_mismatch", validate_ledger, ledger(entry))


def test_exact_scope_by_repository_and_revision_is_accepted():
    entry = established()
    entry["evidence"][1]["reproducedArtefact"] = {"repository": entry["identity"]["repository"],
                                                   "revision": entry["identity"]["revision"]}
    assert validate_ledger(ledger(entry))["VC-EST"]["class"] == "established"


def test_two_entries_cannot_share_weight_bytes():
    twin = established("VC-TWIN", "est")
    refused("weight_hash_shared_by_two_candidates", validate_ledger, ledger(established(), twin))


def test_retracted_evidence_demotes_and_needs_a_history_entry():
    document = ledger()
    entry = entry_of(document, "VC-EST")
    entry["evidence"][1]["retracted"] = {"at": "2026-10-20", "reason": "reproduction withdrawn"}
    refused("declared_class_differs_from_computed", validate_ledger, document)
    entry["classification"]["class"] = "emerging"
    refused("class_change_not_recorded", validate_ledger, document)
    settle(entry, at="2026-10-21", reason="independent reproduction withdrawn")
    assert validate_ledger(document)["VC-EST"]["class"] == "emerging"


# ------------------------------------------------------------------- I11: person/vehicle


def test_person_claim_cannot_support_a_vehicle_candidate():
    entry = established()
    entry["claims"][0]["objectClass"] = "person"
    refused("claim_object_class_mismatch", validate_ledger, ledger(entry))


def test_claim_subtask_must_belong_to_the_candidate_and_event():
    entry = established()
    entry["claims"][0]["subTask"] = "T-PC"
    refused("claim_subtask_outside_candidate", validate_ledger, ledger(entry))
    entry = established()
    entry["subTasks"] = ["T-PC"]
    refused("candidate_subtasks_invalid", validate_ledger, ledger(entry))


def test_person_ledger_is_separate():
    entry = established("PC-1", "pc")
    entry["subTasks"] = ["T-PC"]
    entry["claims"] = [claim("C1", "E-PAPER", subtask="T-PC", object_class="person")]
    document = ledger(entry, object_class="person", capability="person-attributes", subtasks=("T-PC", "T-PO"))
    assert validate_ledger(document)["PC-1"]["class"] == "established"
    document["eventId"] = "msr-vehicle-attributes-2026-01"
    refused("event_id_mismatch", validate_ledger, document)


# ---------------------------------------------------------------- decision summary (§8)


def full():
    return ledger(baseline(), established(), emerging(), reference(), excluded(), method())


def test_consistent_decision_is_accepted_and_emerging_winner_stays_recorded():
    document = full()
    summary = decision(document)
    validate_decision(summary, document)
    assert summary["strongestEvaluatedTechnical"] == "VC-EMG"
    assert summary["implementation"]["components"] == ["VC-EST"]


def test_shortlisted_candidate_cannot_be_dropped_from_the_evaluation():
    document = full()
    summary = decision(document)
    summary["evaluated"] = [r for r in summary["evaluated"] if r["candidateId"] != "VC-EMG"]
    del summary["licence"]["VC-EMG"]
    refused("evaluated_set_differs_from_shortlist", validate_decision, summary, document)


def test_reference_only_candidate_cannot_be_evaluated():
    document = full()
    summary = decision(document)
    summary["evaluated"].append(dict(summary["evaluated"][1], candidateId="VC-REF",
                                     artefactSha256s=[sha("weights-ref")]))
    summary["licence"]["VC-REF"] = {"dev-profile": "CLEARED"}
    refused("evaluated_set_differs_from_shortlist", validate_decision, summary, document)


def test_strongest_technical_ignores_licence():
    document = full()
    licence = {c: {"dev-profile": "CLEARED"} for c in ("VC-B0", "VC-EST", "VC-MTH")}
    licence["VC-EMG"] = {"dev-profile": "CONSTRAINED"}
    summary = decision(document, licence=licence)
    validate_decision(summary, document)
    assert summary["strongestEvaluatedTechnical"] == "VC-EMG"
    assert summary["strongestClearedPerProfile"]["dev-profile"] == "VC-EST"
    summary["strongestEvaluatedTechnical"] = "VC-EST"  # hide the constrained winner
    refused("strongest_technical_not_maximal", validate_decision, summary, document)


def test_strongest_cleared_is_derived_not_asserted():
    document = full()
    summary = decision(document)
    summary["strongestClearedPerProfile"]["dev-profile"] = "VC-MTH"
    refused("strongest_cleared_not_derived", validate_decision, summary, document)
    licence = {c: {"dev-profile": "NOT_CLEARED"} for c in ("VC-B0", "VC-EST", "VC-EMG", "VC-MTH")}
    summary = decision(document, licence=licence, implementation=None)
    validate_decision(summary, document)
    summary["strongestClearedPerProfile"]["dev-profile"] = "VC-EST"
    refused("strongest_cleared_not_derived", validate_decision, summary, document)


def test_highest_task_quality_is_over_every_evaluated_candidate():
    document = full()
    summary = decision(document)
    summary["evaluated"][1]["taskQualityScore"] = 0.99  # VC-EST
    refused("highest_task_quality_not_maximal", validate_decision, summary, document)


def test_emerging_candidate_cannot_be_implemented_without_promotion():
    document = full()
    summary = decision(document, implementation=("VC-EMG",))
    refused("implementation_requires_established", validate_decision, summary, document)


def test_implementation_must_be_cleared_for_every_profile():
    document = full()
    licence = {c: {"dev-profile": "CLEARED"} for c in ("VC-B0", "VC-EMG", "VC-MTH")}
    licence["VC-EST"] = {"dev-profile": "REVIEW_PENDING"}
    summary = decision(document, licence=licence)
    refused("implementation_not_cleared_for_every_profile", validate_decision, summary, document)


def test_implementation_must_pass_technical_gates():
    document = full()
    summary = decision(document)
    row = next(r for r in summary["evaluated"] if r["candidateId"] == "VC-EST")
    row["technicalGates"], row["comparativeScore"] = "failed", None
    refused("implementation_failed_technical_gate", validate_decision, summary, document)


def test_implementation_promotion_must_precede_the_decision():
    document = full()
    summary = decision(document)
    summary["decidedOn"] = "2026-10-01"
    refused("implementation_promotion_after_decision", validate_decision, summary, document)


def test_implementation_only_from_qualification_pending():
    document = full()
    summary = decision(document, state="TECHNICAL_DECISION_RECORDED")
    refused("implementation_before_qualification_pending", validate_decision, summary, document)


def test_evaluated_bytes_must_equal_ledger_identity():
    document = full()
    summary = decision(document)
    row = next(r for r in summary["evaluated"] if r["candidateId"] == "VC-EST")
    row["artefactSha256s"] = [sha("weights-est-v2")]
    refused("evaluated_artefact_differs_from_ledger", validate_decision, summary, document)
    summary = decision(document)
    row = next(r for r in summary["evaluated"] if r["candidateId"] == "VC-MTH")
    row["artefactSha256s"] = [sha("mavi-head")]  # backbone bytes missing
    refused("evaluated_artefact_differs_from_ledger", validate_decision, summary, document)


def test_baseline_evaluation_needs_a_mavi_commit():
    document = full()
    summary = decision(document)
    summary["evaluated"][0]["maviRevision"] = None
    refused("malformed", validate_decision, summary, document)


def test_decision_binds_one_ledger_by_hash_and_event():
    document = full()
    summary = decision(document)
    entry_of(document, "VC-EXC")["caveats"].append("edited after the decision")
    refused("decision_ledger_hash_mismatch", validate_decision, summary, document)
    document = full()
    summary = decision(document)
    summary["eventId"] = "msr-vehicle-attributes-2026-02"
    refused("decision_event_mismatch", validate_decision, summary, document)


def test_outcome_is_consistent_with_state_and_implementation():
    document = full()
    summary = decision(document)
    summary["outcome"] = "SELECTED_FOR_PACKAGING"
    refused("outcome_before_closed", validate_decision, summary, document)
    summary = decision(document, state="CLOSED")
    validate_decision(summary, document)
    summary["outcome"] = "BASELINE_SELECTED"
    refused("outcome_implementation_inconsistent", validate_decision, summary, document)
    summary = decision(document, state="CLOSED", implementation=("VC-B0",))
    summary["outcome"] = "BASELINE_SELECTED"
    validate_decision(summary, document)
    summary["outcome"] = "SELECTED_FOR_PACKAGING"
    refused("outcome_implementation_inconsistent", validate_decision, summary, document)


def test_strongest_reported_must_resolve_to_a_ledger_claim():
    document = full()
    summary = decision(document)
    summary["strongestReported"] = {"candidateId": "VC-REF", "claimId": "C1"}
    validate_decision(summary, document)  # a reference-only candidate may be the strongest reported
    summary["strongestReported"] = {"candidateId": "VC-REF", "claimId": "C9"}
    refused("strongest_reported_unresolved", validate_decision, summary, document)


# ------------------------------------------------------------------- repository and CLI


def test_committed_ledgers_and_decisions_validate():
    validate_repository(REPO)


def test_repository_scan_refuses_misplaced_ledger(tmp_path):
    folder = tmp_path / "docs" / "qualification" / "model-selection" / "person-attributes"
    folder.mkdir(parents=True)
    (folder / "msr-vehicle-attributes-2026-01-evidence-ledger.json").write_text(json.dumps(full()))
    refused("ledger_location_mismatch", validate_repository, tmp_path)


def test_repository_scan_refuses_decision_without_ledger(tmp_path):
    folder = tmp_path / "docs" / "qualification" / "model-selection" / "vehicle-attributes"
    folder.mkdir(parents=True)
    (folder / "msr-vehicle-attributes-2026-01-decision.json").write_text("{}")
    refused("decision_without_ledger", validate_repository, tmp_path)


def test_cli_reports_classes_and_refusals(tmp_path):
    good = tmp_path / "ledger.json"
    good.write_text(json.dumps(full()))
    result = subprocess.run([sys.executable, str(CHECK), "ledger", str(good)], capture_output=True, text=True)
    assert result.returncode == 0 and json.loads(result.stdout)["VC-EXC"]["class"] == "excluded-discovery"
    bad = full()
    entry_of(bad, "VC-REF")["disposition"]["status"] = "SHORTLISTED"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad))
    result = subprocess.run([sys.executable, str(CHECK), "ledger", str(path)], capture_output=True, text=True)
    assert result.returncode == 1 and "refused" in json.loads(result.stdout)


def test_module_imports_no_network_library():
    source = (REPO / "tools/qualification/model_selection/credibility.py").read_text()
    for module in ("urllib", "http", "socket", "requests"):
        assert f"import {module}" not in source and f"from {module}" not in source
