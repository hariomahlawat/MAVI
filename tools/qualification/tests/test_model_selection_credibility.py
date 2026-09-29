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

from model_selection import credibility as module
from model_selection.credibility import (
    REPORTED_LABEL,
    CredibilityError,
    credibility_class,
    document_sha256,
    lf_normalised_sha256,
    validate_decision,
    validate_evolution,
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
    shortlist_emerging,
    technical,
)

REPO = Path(__file__).resolve().parents[3]
CHECK = REPO / "tools" / "qualification" / "model_selection_check.py"


def refused(code, function, *args):
    with pytest.raises(CredibilityError) as caught:
        function(*args)
    assert str(caught.value).split(":", 1)[0] == code, str(caught.value)


def entry_of(document, candidate_id):
    return next(e for e in document["candidates"] if e["candidateId"] == candidate_id)


def full():
    return ledger(baseline(), established(), emerging(), reference(), excluded(), method())


# ------------------------------------------------------------------ baseline fixture


def test_synthetic_ledger_classifies_every_category():
    summary = validate_ledger(full())
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
    first = full()
    second = copy.deepcopy(first)
    for entry in second["candidates"]:
        entry["evidence"].reverse()
    assert validate_ledger(first) == validate_ledger(second)


# ------------------------------------------------------------ I3: computed, not asserted


def test_declared_class_must_equal_computed_class():
    document = full()
    entry_of(document, "VC-EMG")["classification"]["class"] = "established"
    refused("declared_class_differs_from_computed", validate_ledger, document)


def test_declared_confidence_must_equal_computed():
    document = full()
    entry_of(document, "VC-REF")["classification"]["provenanceConfidence"] = "High"
    refused("declared_confidence_differs_from_computed", validate_ledger, document)


# ------------------------------------------------------------- I2: benchmark laundering


def test_five_repetitions_of_one_readme_figure_do_not_establish():
    entry = emerging()
    assert credibility_class(entry, items(entry)) == "emerging"
    entry["publication"] = established()["publication"]
    assert credibility_class(entry, items(entry)) == "emerging"


def test_claim_origin_must_be_the_root_not_a_repetition():
    entry = emerging()
    entry["claims"][0]["originEvidenceId"] = "E-COPY0"
    refused("claim_origin_is_repetition", validate_ledger, ledger(entry))


def test_claim_origin_must_be_primary_evidence():
    entry = established()
    entry["evidence"].append(evidence("E-BLOG", "public-scrutiny", "blogger", "independent"))
    entry["claims"][0]["originEvidenceId"] = "E-BLOG"
    refused("claim_origin_not_primary", validate_ledger, ledger(entry))


def test_architecture_must_be_documented_first_party():
    entry = established()
    entry["architecture"]["documentedBy"] = "E-REPRO"
    assert credibility_class(entry, items(entry)) == "reference-only"


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
    refused("field_not_allowed_for_type", validate_ledger, ledger(entry))


def test_retyping_a_repeating_page_as_independent_is_refused():
    entry = emerging()
    copy_page = entry["evidence"][1]
    entry["evidence"].append(technical("E-FAKE", "independent-reproduction", "site-0x", scope="method",
                                       source=copy_page["source"]))
    refused("independent_evidence_not_distinct", validate_ledger, ledger(entry))


@pytest.mark.parametrize("variant", ["{}#table-2", "{}?ref=x", "{}/", "HTTP://{}"])
def test_url_variants_of_one_document_are_not_independent(variant):
    entry = established()
    first_party = entry["evidence"][0]["source"]
    bare = first_party.split("://", 1)[1]
    entry["evidence"][1]["source"] = variant.format(first_party if not variant.startswith("HTTP") else bare)
    refused("independent_evidence_not_distinct", validate_ledger, ledger(entry))


def test_identifying_query_and_arxiv_variants_are_normalised():
    entry = established()
    entry["evidence"][1]["source"] = "https://openreview.net/forum?id=AAA"
    entry["evidence"][2]["source"] = "https://openreview.net/forum?id=BBB&utm_source=x"
    assert validate_ledger(ledger(entry))["VC-EST"]["class"] == "established"
    for first, second in (
        ("https://arxiv.org/abs/2601.01234", "https://export.arxiv.org/pdf/2601.01234v2.pdf"),
        ("https://arxiv.org/abs/2601.01234", "https://huggingface.co/papers/2601.01234"),
        ("https://arxiv.org/abs/cs/0601001", "https://arxiv.org/pdf/cs/0601001v1"),
        ("https://openreview.net/forum?id=AAA", "https://openreview.net/pdf?id=AAA"),
    ):
        entry = established()
        entry["evidence"][0]["source"], entry["evidence"][1]["source"] = first, second
        refused("independent_evidence_not_distinct", validate_ledger, ledger(entry))


def test_same_retrieved_bytes_are_not_independent():
    entry = established()
    entry["evidence"][2]["retrievedSha256"] = entry["evidence"][1]["retrievedSha256"]
    refused("independent_evidence_not_distinct", validate_ledger, ledger(entry))


def test_independent_producer_cannot_be_an_author_group():
    entry = established()
    entry["evidence"][1]["producer"]["group"] = "est-lab"
    refused("independent_producer_is_author", validate_ledger, ledger(entry))


def test_affiliated_group_cannot_double_as_independent():
    entry = established()
    entry["authors"]["affiliatedGroups"] = ["x-spinoff"]
    entry["evidence"][1]["producer"]["group"] = "x-spinoff"
    refused("independent_producer_is_author", validate_ledger, ledger(entry))


def test_affiliated_first_party_group_must_be_declared():
    entry = established()
    entry["evidence"][0]["producer"] = {"group": "undeclared", "relation": "author-affiliated"}
    refused("affiliated_group_not_declared", validate_ledger, ledger(entry))


def test_independent_evidence_requires_independent_relation():
    entry = established()
    entry["authors"]["affiliatedGroups"] = ["other-lab"]
    entry["evidence"][1]["producer"]["relation"] = "author-affiliated"
    refused("independent_evidence_not_independent", validate_ledger, ledger(entry))


def test_first_party_claim_cannot_be_labelled_independent():
    entry = established()
    entry["evidence"][0]["producer"] = {"group": "someone-else", "relation": "independent"}
    refused("first_party_claim_not_from_authors", validate_ledger, ledger(entry))


def test_one_group_counts_once():
    entry = established()
    entry["evidence"][2]["producer"]["group"] = "other-lab"
    assert credibility_class(entry, items(entry)) == "emerging"


def test_adoption_alone_is_not_independent_technical_evidence():
    entry = established()
    entry["evidence"][1] = evidence("E-ADOPT2", "adoption", "third-team", "independent",
                                    scope="method", independenceBasis="separate")
    assert credibility_class(entry, items(entry)) == "emerging"


def test_popularity_signals_are_never_counted():
    entry = emerging()
    entry["popularitySignals"] = [
        {"signal": s, "value": "1000000", "observedOn": "2026-06-01", "source": "https://example.invalid/x"}
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
        technical("E-BENCH", "independent-benchmark", "bench-server", scope="method"),
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


# ------------------------------------------------ MAVI results are never external evidence


@pytest.mark.parametrize("change", [
    {"producer": {"group": "mavi", "relation": "independent"}},
    {"producer": {"group": "mavi-bakeoff", "relation": "independent"}},
    {"source": "docs/qualification/model-selection/vehicle-attributes/msr-vehicle-attributes-2026-01.md"},
    {"source": "evidence/bakeoff/results.json"},
    {"source": "https://github.com/hariomahlawat/MAVI/blob/main/x.md"},
    {"source": "evidence-store://sha256/abc"},
    {"source": "https://intranet.invalid/msr-vehicle-attributes-2026-01/results"},
    {"locator": "MAVI selection partition, table 3"},
    {"independenceBasis": "run by the MAVI team"},
])
def test_mavi_measurement_cannot_enter_the_ledger(change):
    entry = established()
    entry["evidence"][1].update(change)
    refused("mavi_evidence_in_ledger", validate_ledger, ledger(entry))


@pytest.mark.parametrize("source", [
    "https://github.com/someone/mavic-aerial-vehicles",
    "https://paperswithcode.com/task/model-selection/latest",
    "https://primavision.example.org/report",
    "https://example.invalid/MAVIS-Street/results",
    "https://www.microsoft.com/en-us/research/uploads/MSR-TR-2019-12.pdf",
    "https://vendor.example.org/docs/qualification/report.html",
])
def test_unrelated_names_are_not_mistaken_for_mavi(source):
    entry = established()
    entry["evidence"][1]["source"] = source
    assert validate_ledger(ledger(entry))["VC-EST"]["class"] == "established"


@pytest.mark.parametrize("where", ["summary", "caveat"])
def test_mavi_result_wording_is_refused_in_summary_and_caveats(where):
    entry = established()
    if where == "summary":
        entry["evidence"][1]["summary"] = "MAVI bake-off winner, all gates pass"
    else:
        entry["caveats"] = ["passed the MAVI selection partition"]
    refused("mavi_evidence_in_ledger", validate_ledger, ledger(entry))


def test_openreview_notes_are_distinct_documents():
    entry = established()
    entry["evidence"][0]["source"] = "https://openreview.net/forum?id=AAA"
    entry["evidence"][1]["source"] = "https://openreview.net/forum?id=AAA&noteId=BBB"
    assert validate_ledger(ledger(entry))["VC-EST"]["class"] == "established"


def test_an_author_named_mavi_is_not_refused():
    entry = established()
    entry["evidence"][1]["summary"] = "reproduction by A. Mavi et al."
    assert validate_ledger(ledger(entry))["VC-EST"]["class"] == "established"


def test_mavi_dataset_claim_is_refused():
    entry = established()
    entry["claims"][0]["dataset"] = "MAVI selection partition"
    refused("mavi_evidence_in_ledger", validate_ledger, ledger(entry))


def test_mavi_cannot_be_an_author_group_of_an_external_candidate():
    entry = established()
    entry["authors"]["groups"] = ["mavi"]
    entry["evidence"][0]["producer"]["group"] = "mavi"
    refused("mavi_evidence_in_ledger", validate_ledger, ledger(entry))


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
    entry["identity"]["revision"] = "v1.0"
    assert credibility_class(entry, items(entry)) == "reference-only"


def test_unknown_source_is_excluded_discovery():
    entry = established()
    entry["identity"]["repository"] = "UNKNOWN"
    assert credibility_class(entry, items(entry)) == "excluded-discovery"
    entry = established()
    entry["authors"]["groups"] = []
    assert credibility_class(entry, items(entry)) == "excluded-discovery"


def test_integrity_conflict_excludes_from_its_date():
    entry = established()
    entry["identity"]["integrityConflict"] = {"at": "2026-07-01", "reason": "retrieved bytes differ from the published hash"}
    assert credibility_class(entry, items(entry)) == "excluded-discovery"
    assert credibility_class(entry, items(entry), module.date(2026, 6, 15)) == "established"


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
    entry["evidence"].append(technical("E-BENCH", "independent-benchmark", "bench", scope="method"))
    assert credibility_class(entry, items(entry)) == "emerging"


def test_shortlist_requires_snapshotted_evidence():
    entry = established()
    entry["evidence"][0]["retrievedSha256"] = "UNKNOWN"
    refused("shortlist_requires_snapshotted_evidence", validate_ledger, ledger(entry))
    entry = established()
    entry["evidence"][1]["retrievedSha256"] = "UNKNOWN"
    refused("shortlist_requires_snapshotted_evidence", validate_ledger, ledger(entry))


def test_method_shortlist_requires_immutable_code_revision():
    entry = method()
    entry["methodCode"]["revision"] = "main"
    refused("shortlist_requires_method_revision", validate_ledger, ledger(entry))


def test_emerging_defaults_to_reference_only():
    assert validate_ledger(ledger(emerging(shortlisted=False)))["VC-EMG"]["disposition"] == "REFERENCE_ONLY"


def test_shortlisting_emerging_needs_basis_and_second_reviewer():
    entry = emerging()
    del entry["disposition"]["emergingShortlistBasis"]
    refused("text_required", validate_ledger, ledger(entry))
    entry = emerging()
    entry["disposition"]["reviewedBy"] = " Synthetic-Reviewer "
    refused("shortlist_reviewer_not_independent", validate_ledger, ledger(entry))
    entry = shortlist_emerging(established())
    validate_ledger(ledger(entry))  # kept on record after a promotion
    entry = shortlist_emerging(reference())
    entry["disposition"]["status"] = "REFERENCE_ONLY"
    refused("shortlist_basis_only_for_emerging", validate_ledger, ledger(entry))


def test_established_candidate_cannot_be_parked_for_credibility():
    entry = established()
    entry["disposition"] = reference()["disposition"]
    refused("credibility_reason_contradicts_evidence", validate_ledger, ledger(entry))


def test_evaluation_permission_reference_only_keeps_computed_class():
    entry = established()
    entry["disposition"] = dict(reference()["disposition"], reasonClass="evaluation-permission",
                                reason="evaluation not permitted by its terms")
    assert validate_ledger(ledger(entry))["VC-EST"]["class"] == "established"


def test_licence_cannot_be_a_technical_not_shortlisted_reason():
    entry = established()
    entry["disposition"] = {"status": "NOT_SHORTLISTED", "reasonClass": "technical",
                            "reason": "weights licence is non-commercial", "revisitTrigger": None, "decidedBy": "r"}
    refused("licence_reason_not_allowed", validate_ledger, ledger(entry))
    entry = established()
    entry["disposition"] = dict(reference()["disposition"], reasonClass="availability", reason="licence NC, cannot bundle")
    refused("licence_reason_not_allowed", validate_ledger, ledger(entry))


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
    document = full()
    entry_of(document, "VC-EST")["disposition"]["status"] = status
    refused("value_not_allowed", validate_ledger, document)


def test_ledger_rejects_mavi_measurement_fields():
    document = full()
    entry_of(document, "VC-EST")["maviResult"] = {"aurc": 0.1}
    refused("unknown_field", validate_ledger, document)
    document = full()
    entry_of(document, "VC-EST")["evidence"][0]["type"] = "mavi-measurement"
    refused("value_not_allowed", validate_ledger, document)


@pytest.mark.parametrize("key", ["licence", "weightsLicense", "licenceStatus"])
def test_ledger_has_no_licence_field_anywhere(key):
    document = full()
    entry_of(document, "VC-EST")["identity"][key] = "CLEARED"
    refused("licence_field_in_ledger", validate_ledger, document)


def test_licence_never_changes_classification_or_technical_outputs():
    document = full()
    constrained = {c: {"dev-profile": "NOT_CLEARED"} for c in ("VC-B0", "VC-EST", "VC-EMG", "VC-MTH")}
    a = decision(document, implementation=None)
    b = decision(document, licence=constrained, implementation=None)
    validate_decision(a, document, document)
    validate_decision(b, document, document)
    assert a["strongestEvaluatedTechnical"] == b["strongestEvaluatedTechnical"] == "VC-EMG"
    assert a["highestTaskQualityEvaluated"] == b["highestTaskQualityEvaluated"]
    assert "licen" not in json.dumps(document).lower()


# --------------------------------------------------- I8/I10: history, promotion, identity


def promote(entry, at="2026-06-04"):
    entry["evidence"] += [
        technical("E-REPRO", "independent-reproduction", "other-lab", recorded="2026-06-03",
                  scope="exact-checkpoint", reproducedArtefact=exact("emg")),
        evidence("E-ADOPT", "adoption", "framework-team", "independent", recorded="2026-06-03",
                 scope="method", independenceBasis="separate"),
    ]
    entry["publication"] = established()["publication"]
    return entry


def test_new_evidence_that_changes_class_needs_a_history_entry():
    entry = settle(emerging())
    promote(entry)
    entry["disposition"] = established()["disposition"]
    document = ledger(baseline())
    document["candidates"].append(entry)
    entry["classification"] = {"class": "established", "provenanceConfidence": "High"}
    refused("class_change_not_recorded", validate_ledger, document)
    settle(entry, at="2026-06-04", reason="independent reproduction and adoption recorded")
    assert validate_ledger(document)["VC-EMG"]["class"] == "established"
    assert [r["to"] for r in entry["classificationHistory"]] == ["emerging", "established"]


def test_promotion_cannot_be_backdated_ahead_of_its_evidence():
    entry = established()
    for item in entry["evidence"][1:]:
        item["recordedAt"] = item["retrievedOn"] = "2026-06-10"
    refused("history_overclaims_on_date", validate_ledger, ledger(entry))


def test_promotion_must_cite_the_evidence_it_relies_on():
    document = full()
    entry_of(document, "VC-EST")["classificationHistory"][0]["evidenceIds"] = ["E-PAPER"]
    refused("promotion_not_supported_by_cited_evidence", validate_ledger, document)


def test_history_entry_cannot_overclaim_on_its_date():
    document = full()
    entry = entry_of(document, "VC-EMG")
    first = dict(entry["classificationHistory"][0], at="2026-06-02", to="emerging")
    entry["classificationHistory"] = [dict(first, **{"from": None}), dict(first, **{"from": "emerging"})]
    validate_ledger(document)  # a repeated but true entry is harmless
    entry = entry_of(document, "VC-REF")  # pinned third-party upload: reference-only on every date
    entry["classificationHistory"].insert(0, dict(entry["classificationHistory"][0], at="2026-06-01", to="emerging"))
    entry["classificationHistory"][1]["from"] = "emerging"
    refused("history_overclaims_on_date", validate_ledger, document)


def test_evidence_cannot_be_recorded_before_it_was_retrieved():
    entry = established()
    entry["evidence"][1]["retrievedOn"] = "2026-06-20"
    refused("recorded_before_retrieved", validate_ledger, ledger(entry))


def test_future_dates_are_refused(monkeypatch):
    monkeypatch.setattr(module, "_today", lambda: module.date(2026, 5, 1))
    refused("date_in_future", validate_ledger, full())


def test_history_cannot_cite_evidence_recorded_later():
    document = full()
    entry = entry_of(document, "VC-EMG")
    entry["evidence"][1]["recordedAt"] = entry["evidence"][1]["retrievedOn"] = "2026-08-01"
    refused("history_cites_later_evidence", validate_ledger, document)


def test_history_must_chain_and_be_reviewed_by_someone_else():
    document = full()
    entry_of(document, "VC-EST")["classificationHistory"][0]["reviewedBy"] = " Synthetic-Curator"
    refused("history_reviewer_not_independent", validate_ledger, document)
    document = full()
    entry_of(document, "VC-EST")["classificationHistory"][0]["from"] = "emerging"
    refused("history_chain_broken", validate_ledger, document)


def test_history_is_required():
    document = full()
    entry_of(document, "VC-EST")["classificationHistory"] = []
    refused("history_required", validate_ledger, document)


def test_identity_edit_without_history_entry_is_refused():
    document = full()
    entry_of(document, "VC-EST")["identity"]["tag"] = "v1.1"
    refused("identity_change_not_recorded", validate_ledger, document)


def test_same_name_different_checkpoint_needs_a_new_entry():
    document = full()
    entry = entry_of(document, "VC-EST")
    entry["identity"]["files"][0]["sha256"] = sha("weights-est-v2")
    entry["evidence"][1]["reproducedArtefact"] = {"sha256s": [sha("weights-est-v2")]}
    settle(entry, at="2026-06-06", reason="upstream replaced the weights")
    refused("checkpoint_changed_under_same_candidate", validate_ledger, document)


def test_exact_scope_evidence_must_name_all_the_same_bytes():
    entry = established()
    entry["evidence"][1]["reproducedArtefact"] = {"sha256s": [sha("some-other-weights")]}
    refused("evidence_artefact_mismatch", validate_ledger, ledger(entry))
    entry = established()
    entry["identity"]["files"].append({"path": "tokenizer.json", "sha256": sha("tok")})
    entry["evidence"][1]["reproducedArtefact"] = {"sha256s": [sha("tok")]}  # one shared file only
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


def test_two_checkpoint_entries_cannot_share_weight_bytes():
    twin = established("VC-TWIN", "est")
    refused("weight_hash_shared_by_two_candidates", validate_ledger, ledger(established(), twin))


def test_method_entries_may_share_one_backbone():
    first = method("PC-1", "shared")
    second = method("PO-1", "shared")
    for entry, subtask in ((first, "T-PC"), (second, "T-PO")):
        entry["subTasks"] = [subtask]
        entry["claims"] = [claim("C1", "E-PAPER", subtask=subtask, object_class="person")]
    document = ledger(first, second, object_class="person", capability="person-attributes", subtasks=("T-PC", "T-PO"))
    assert set(validate_ledger(document)) == {"PC-1", "PO-1"}
    entry_of(document, "PO-1")["identity"]["tag"] = "v2"
    settle(entry_of(document, "PO-1"), at="2026-06-05")
    refused("weight_hash_shared_by_two_candidates", validate_ledger, document)


def test_retracted_evidence_demotes_and_needs_a_history_entry():
    document = full()
    entry = entry_of(document, "VC-EST")
    entry["evidence"][1]["retracted"] = {"at": "2026-07-20", "reason": "reproduction withdrawn"}
    refused("declared_class_differs_from_computed", validate_ledger, document)
    entry["classification"]["class"] = "emerging"
    refused("class_change_not_recorded", validate_ledger, document)
    settle(entry, at="2026-07-21", reason="independent reproduction withdrawn")
    entry["disposition"] = emerging()["disposition"]
    assert validate_ledger(document)["VC-EST"]["class"] == "emerging"


# ------------------------------------------------ after freeze the ledger only grows


def test_frozen_ledger_evolution_is_append_only():
    frozen = full()
    grown = copy.deepcopy(frozen)
    entry_of(grown, "VC-EXC")["caveats"].append("later note")
    validate_evolution(frozen, grown)

    rewritten = copy.deepcopy(frozen)
    entry_of(rewritten, "VC-REF")["evidence"][0]["summary"] = "rewritten"
    refused("frozen_evidence_changed", validate_evolution, frozen, rewritten)

    removed = copy.deepcopy(frozen)
    entry = entry_of(removed, "VC-EXC")
    entry["caveats"] = []
    removed["candidates"].remove(entry)
    refused("frozen_candidate_removed", validate_evolution, frozen, removed)


def test_shortlist_cannot_change_after_freeze():
    frozen = full()
    edited = copy.deepcopy(frozen)
    entry_of(edited, "VC-EMG")["disposition"] = {"status": "DEFERRED", "reasonClass": "resources",
                                                  "reason": "no time", "revisitTrigger": "later", "decidedBy": "r"}
    refused("shortlist_changed_after_freeze", validate_evolution, frozen, edited)
    summary = decision(edited, frozen=frozen)
    refused("shortlist_changed_after_freeze", validate_decision, summary, edited, frozen)


def test_frozen_history_cannot_be_rewritten():
    frozen = full()
    edited = copy.deepcopy(frozen)
    entry_of(edited, "VC-EST")["classificationHistory"][0]["reason"] = "different story"
    refused("frozen_list_rewritten", validate_evolution, frozen, edited)


def test_frozen_retraction_is_allowed_but_kept():
    frozen = full()
    edited = copy.deepcopy(frozen)
    entry = entry_of(edited, "VC-EXC")
    entry["evidence"][0]["retracted"] = {"at": "2026-07-01", "reason": "withdrawn"}
    validate_evolution(frozen, edited)
    entry["evidence"][0]["retracted"]["at"] = "2026-06-05"  # dated before the freeze
    refused("appended_before_freeze", validate_evolution, frozen, edited)


def test_evidence_and_promotions_after_freeze_cannot_be_backdated():
    frozen = full()
    edited = copy.deepcopy(frozen)
    entry = entry_of(edited, "VC-EMG")
    entry["evidence"] += [
        technical("E-REPRO", "independent-reproduction", "other-lab", recorded="2026-06-05",
                  scope="exact-checkpoint", reproducedArtefact=exact("emg")),
        evidence("E-ADOPT", "adoption", "framework-team", "independent", recorded="2026-06-05",
                 scope="method", independenceBasis="separate"),
    ]
    entry["publication"] = established()["publication"]
    settle(entry, at="2026-06-06")
    refused("appended_before_freeze", validate_evolution, frozen, edited)


def test_backdated_evidence_alone_is_refused_after_freeze():
    frozen = full()
    edited = copy.deepcopy(frozen)
    entry = entry_of(edited, "VC-REF")
    entry["evidence"].append(evidence("E-NOTE", "public-scrutiny", "watcher", "independent", recorded="2026-06-05"))
    refused("appended_before_freeze", validate_evolution, frozen, edited)


def test_backdated_history_alone_is_refused_after_freeze():
    frozen = full()
    edited = copy.deepcopy(frozen)
    entry = entry_of(edited, "VC-REF")
    entry["classificationHistory"].append(dict(entry["classificationHistory"][-1], at="2026-06-05",
                                               **{"from": "reference-only"}, reason="re-examined"))
    refused("appended_before_freeze", validate_evolution, frozen, edited)


def test_frozen_ledger_needs_its_date():
    frozen = full()
    del frozen["frozenOn"]
    refused("frozen_ledger_without_date", validate_evolution, frozen, full())


def test_frozen_shortlisted_entry_cannot_be_edited():
    frozen = full()
    for field, value in (("candidateName", "renamed"),
                         ("architecture", {"description": "edited", "documentedBy": "E-PAPER"})):
        edited = copy.deepcopy(frozen)
        entry = entry_of(edited, "VC-EST")
        entry[field] = value
        settle(entry, at="2026-07-01")
        refused("frozen_shortlisted_field_changed", validate_evolution, frozen, edited)


def test_corrected_inputs_need_a_new_entry_but_do_not_invalidate_old_ones():
    document = full()
    entry = entry_of(document, "VC-EST")
    entry["publication"] = {"status": "preprint", "venue": None, "reference": "https://example.invalid/p", "basis": None}
    entry["classification"]["class"] = "emerging"
    refused("class_change_not_recorded", validate_ledger, document)
    settle(entry, at="2026-07-01", reason="venue claim was wrong; preprint only")
    entry["disposition"] = emerging()["disposition"]
    assert validate_ledger(document)["VC-EST"]["class"] == "emerging"


def test_input_edit_without_history_entry_is_refused():
    document = full()
    entry_of(document, "VC-EST")["authors"]["names"].append("Another Author")
    refused("classification_input_change_not_recorded", validate_ledger, document)


def test_history_on_superseded_inputs_only_precedes_current_ones():
    document = full()
    entry = entry_of(document, "VC-EST")
    bogus = dict(entry["classificationHistory"][0], at="2026-06-03", **{"from": "established"},
                 inputsSha256=sha("some other inputs"))
    entry["classificationHistory"].append(bogus)
    entry["classificationHistory"].append(dict(entry["classificationHistory"][0], at="2026-06-04",
                                               **{"from": "established"}))
    refused("history_entry_on_superseded_inputs", validate_ledger, document)


# ------------------------------------------------------------------- I11: person/vehicle


def test_person_claim_cannot_support_a_vehicle_candidate():
    entry = established()
    entry["claims"][0]["objectClass"] = "person"
    refused("claim_object_class_mismatch", validate_ledger, ledger(entry))


def test_person_reproduction_cannot_support_a_vehicle_candidate():
    entry = established()
    entry["evidence"][1]["objectClass"] = "person"
    refused("evidence_object_class_mismatch", validate_ledger, ledger(entry))


def test_claim_subtask_must_belong_to_the_candidate_and_event():
    entry = established()
    entry["claims"][0]["subTask"] = "T-PC"
    refused("claim_subtask_outside_candidate", validate_ledger, ledger(entry))
    entry = established()
    entry["subTasks"] = ["T-PC"]
    refused("candidate_subtasks_invalid", validate_ledger, ledger(entry))


def test_known_event_scope_cannot_be_widened():
    document = ledger(baseline(), object_class="person", capability="person-attributes",
                      subtasks=("T-PC", "T-PO", "T-VC"))
    refused("event_scope_mismatch", validate_ledger, document)


def test_person_ledger_is_separate():
    entry = established("PC-1", "pc")
    entry["subTasks"] = ["T-PC"]
    entry["claims"] = [claim("C1", "E-PAPER", subtask="T-PC", object_class="person")]
    entry["evidence"][1].update(subTask="T-PC", objectClass="person")
    document = ledger(entry, object_class="person", capability="person-attributes", subtasks=("T-PC", "T-PO"))
    assert validate_ledger(document)["PC-1"]["class"] == "established"
    document["eventId"] = "msr-vehicle-attributes-2026-01"
    refused("event_id_mismatch", validate_ledger, document)


# ---------------------------------------------------------------- decision summary (§8)


def test_consistent_decision_is_accepted_and_emerging_winner_stays_recorded():
    document = full()
    summary = decision(document)
    validate_decision(summary, document, document)
    assert summary["strongestEvaluatedTechnical"] == "VC-EMG"
    assert summary["implementation"]["components"] == ["VC-EST"]


def test_shortlisted_candidate_cannot_be_dropped_from_the_evaluation():
    document = full()
    summary = decision(document)
    summary["evaluated"] = [r for r in summary["evaluated"] if r["candidateId"] != "VC-EMG"]
    del summary["licence"]["VC-EMG"]
    refused("evaluated_set_differs_from_shortlist", validate_decision, summary, document, document)


def test_reference_only_candidate_cannot_be_evaluated():
    document = full()
    summary = decision(document)
    summary["evaluated"].append(dict(summary["evaluated"][1], candidateId="VC-REF",
                                     artefactSha256s=[sha("weights-ref")]))
    summary["licence"]["VC-REF"] = {"dev-profile": "CLEARED"}
    refused("evaluated_set_differs_from_shortlist", validate_decision, summary, document, document)


def test_strongest_technical_ignores_licence():
    document = full()
    licence = {c: {"dev-profile": "CLEARED"} for c in ("VC-B0", "VC-EST", "VC-MTH")}
    licence["VC-EMG"] = {"dev-profile": "CONSTRAINED"}
    summary = decision(document, licence=licence)
    validate_decision(summary, document, document)
    assert summary["strongestEvaluatedTechnical"] == "VC-EMG"
    assert summary["strongestClearedPerProfile"]["dev-profile"] == "VC-EST"
    summary["strongestEvaluatedTechnical"] = "VC-EST"
    refused("strongest_technical_not_maximal", validate_decision, summary, document, document)


def test_strongest_cleared_is_derived_not_asserted():
    document = full()
    summary = decision(document)
    summary["strongestClearedPerProfile"]["dev-profile"] = "VC-MTH"
    refused("strongest_cleared_not_derived", validate_decision, summary, document, document)
    licence = {c: {"dev-profile": "NOT_CLEARED"} for c in ("VC-B0", "VC-EST", "VC-EMG", "VC-MTH")}
    summary = decision(document, licence=licence, implementation=None)
    validate_decision(summary, document, document)
    summary["strongestClearedPerProfile"]["dev-profile"] = "VC-EST"
    refused("strongest_cleared_not_derived", validate_decision, summary, document, document)


def test_highest_task_quality_is_over_every_evaluated_candidate():
    document = full()
    summary = decision(document)
    next(r for r in summary["evaluated"] if r["candidateId"] == "VC-EST")["taskQualityScore"] = 0.99
    refused("highest_task_quality_not_maximal", validate_decision, summary, document, document)


def test_emerging_candidate_cannot_be_implemented_without_promotion():
    document = full()
    summary = decision(document, implementation=("VC-EMG",))
    refused("implementation_requires_established", validate_decision, summary, document, document)


def test_implementation_class_is_the_one_on_the_decision_date():
    document = full()
    entry = entry_of(document, "VC-EST")
    entry["evidence"][1]["retracted"] = {"at": "2026-07-01", "reason": "withdrawn"}
    entry["classification"]["class"] = "emerging"
    settle(entry, at="2026-07-02")
    entry["evidence"].append(technical("E-REPRO2", "independent-reproduction", "third-lab", recorded="2026-09-10",
                                       scope="exact-checkpoint", reproducedArtefact=exact("est")))
    entry["classification"]["class"] = "established"
    settle(entry, at="2026-09-11")
    assert [r["to"] for r in entry["classificationHistory"]] == ["established", "emerging", "established"]
    summary = decision(document, frozen=full())  # decided 2026-09-01; the snapshot holds a later entry
    refused("decision_snapshot_postdates_decision", validate_decision, summary, document, full())


def test_implementation_must_be_cleared_for_every_profile():
    document = full()
    licence = {c: {"dev-profile": "CLEARED"} for c in ("VC-B0", "VC-EMG", "VC-MTH")}
    licence["VC-EST"] = {"dev-profile": "REVIEW_PENDING"}
    summary = decision(document, licence=licence)
    refused("implementation_not_cleared_for_every_profile", validate_decision, summary, document, document)


def test_implementation_must_pass_technical_gates():
    document = full()
    summary = decision(document)
    row = next(r for r in summary["evaluated"] if r["candidateId"] == "VC-EST")
    row["technicalGates"], row["comparativeScore"] = "failed", None
    refused("implementation_failed_technical_gate", validate_decision, summary, document, document)


def test_implementation_promotion_must_precede_the_decision():
    document = full()
    summary = decision(document)
    summary["decidedOn"] = "2026-06-01"  # before the promotion the snapshot records
    refused("decision_snapshot_postdates_decision", validate_decision, summary, document, document)


def test_implementation_only_from_qualification_pending():
    document = full()
    summary = decision(document, state="TECHNICAL_DECISION_RECORDED")
    refused("implementation_before_qualification_pending", validate_decision, summary, document, document)


def test_evaluated_bytes_must_equal_ledger_identity():
    document = full()
    summary = decision(document)
    row = next(r for r in summary["evaluated"] if r["candidateId"] == "VC-EST")
    row["artefactSha256s"] = [sha("weights-est-v2")]
    refused("evaluated_artefact_differs_from_ledger", validate_decision, summary, document, document)
    summary = decision(document)
    row = next(r for r in summary["evaluated"] if r["candidateId"] == "VC-MTH")
    row["artefactSha256s"] = sorted(row["artefactSha256s"] + [sha("hf-randomuser-finetune")])
    refused("evaluated_artefact_differs_from_ledger", validate_decision, summary, document, document)


def test_method_must_declare_its_mavi_trained_artefacts_and_checkpoint_none():
    document = full()
    summary = decision(document)
    row = next(r for r in summary["evaluated"] if r["candidateId"] == "VC-MTH")
    row["maviTrainedArtefacts"], row["artefactSha256s"] = [], [sha("weights-mth")]
    refused("method_without_mavi_trained_artefact", validate_decision, summary, document, document)
    summary = decision(document)
    row = next(r for r in summary["evaluated"] if r["candidateId"] == "VC-EST")
    row["maviTrainedArtefacts"] = [{"sha256": sha("x"), "trainingManifestSha256": sha("m")}]
    refused("checkpoint_has_mavi_trained_artefacts", validate_decision, summary, document, document)


def test_baseline_evaluation_needs_a_mavi_commit():
    document = full()
    summary = decision(document)
    summary["evaluated"][0]["maviRevision"] = None
    refused("malformed", validate_decision, summary, document, document)


def test_decision_binds_the_ledger_and_the_frozen_ledger():
    document = full()
    summary = decision(document)
    entry_of(document, "VC-EXC")["caveats"].append("edited after the decision")
    refused("decision_ledger_hash_mismatch", validate_decision, summary, document, full())
    document = full()
    summary = decision(document)
    summary["frozenLedgerSha256"] = sha("another frozen ledger")
    refused("decision_frozen_ledger_hash_mismatch", validate_decision, summary, document, document)
    summary = decision(document)
    summary["eventId"] = "msr-vehicle-attributes-2026-02"
    refused("decision_event_mismatch", validate_decision, summary, document, document)


def test_outcome_is_consistent_with_state_and_implementation():
    document = full()
    summary = decision(document)
    summary["outcome"] = "SELECTED_FOR_PACKAGING"
    refused("outcome_before_closed", validate_decision, summary, document, document)
    summary = decision(document, state="CLOSED")
    validate_decision(summary, document, document)
    summary["outcome"] = "BASELINE_SELECTED"
    refused("outcome_implementation_inconsistent", validate_decision, summary, document, document)
    summary = decision(document, state="CLOSED", implementation=("VC-B0",))
    summary["outcome"] = "BASELINE_SELECTED"
    validate_decision(summary, document, document)
    summary["outcome"] = "SELECTED_FOR_PACKAGING"
    refused("outcome_implementation_inconsistent", validate_decision, summary, document, document)


def test_strongest_reported_resolves_and_is_labelled():
    document = full()
    summary = decision(document)
    summary["strongestReported"] = {"candidateId": "VC-REF", "claimId": "C1", "label": REPORTED_LABEL}
    validate_decision(summary, document, document)
    summary["strongestReported"]["claimId"] = "C9"
    refused("strongest_reported_unresolved", validate_decision, summary, document, document)
    summary["strongestReported"] = {"candidateId": "VC-REF", "claimId": "C1", "label": "best"}
    refused("strongest_reported_label", validate_decision, summary, document, document)


# ------------------------------------------------------------------- repository and CLI


def write_event(tmp_path, *, frozen=None, protocol=True, record=True, decision_doc=None, snapshot=None, current=None):
    folder = tmp_path / "docs" / "qualification" / "model-selection" / "vehicle-attributes"
    folder.mkdir(parents=True, exist_ok=True)
    document = full() if current is None else current
    (folder / "msr-vehicle-attributes-2026-01-evidence-ledger.json").write_text(json.dumps(document))
    if snapshot is not None:
        (folder / "msr-vehicle-attributes-2026-01-evidence-ledger-decided.json").write_text(json.dumps(snapshot))
    if frozen is not None:
        (folder / "msr-vehicle-attributes-2026-01-evidence-ledger-frozen.json").write_text(json.dumps(frozen))
    if protocol:
        cited = document_sha256(frozen) if frozen is not None else ""
        protocol_path = folder / "msr-vehicle-attributes-2026-01-protocol.md"
        frozen_on = frozen["frozenOn"] if frozen is not None else ""
        protocol_path.write_text(f"Frozen ledger SHA-256: {cited}\nFrozen on: {frozen_on}\n")
        if record:
            (folder / "msr-vehicle-attributes-2026-01.md").write_text(
                f"Protocol SHA-256: {lf_normalised_sha256(protocol_path)}\n")
    if decision_doc is not None:
        (folder / "msr-vehicle-attributes-2026-01-decision.json").write_text(json.dumps(decision_doc))
    return folder, document


def test_committed_ledgers_and_decisions_validate():
    validate_repository(REPO)


def complete_event(tmp_path, current=None):
    folder, _ = write_event(tmp_path, frozen=full(), snapshot=full(), current=current)
    summary = decision(full())
    summary["protocolSha256"] = lf_normalised_sha256(folder / "msr-vehicle-attributes-2026-01-protocol.md")
    decision_path = folder / "msr-vehicle-attributes-2026-01-decision.json"
    decision_path.write_text(json.dumps(summary))
    record_path = folder / "msr-vehicle-attributes-2026-01.md"
    snapshot_path = folder / "msr-vehicle-attributes-2026-01-evidence-ledger-decided.json"
    record_path.write_text(record_path.read_text() + f"Decision SHA-256: {lf_normalised_sha256(decision_path)}\n"
                           f"Decision snapshot SHA-256: {lf_normalised_sha256(snapshot_path)}\n")
    return folder


def test_repository_scan_accepts_a_complete_event(tmp_path):
    complete_event(tmp_path)
    assert len(validate_repository(tmp_path)) == 4


def test_nothing_added_after_the_decision_is_dated_before_it(tmp_path):
    current = full()
    entry = entry_of(current, "VC-EMG")
    entry["evidence"].append(technical("E-LATE", "independent-reproduction", "late-lab", recorded="2026-08-01",
                                       scope="exact-checkpoint", reproducedArtefact=exact("emg")))
    settle(entry, at="2026-08-02")
    complete_event(tmp_path, current=current)
    refused("appended_before_freeze", validate_repository, tmp_path)


def test_record_carries_decision_and_snapshot_hashes(tmp_path):
    folder = complete_event(tmp_path)
    snapshot_path = folder / "msr-vehicle-attributes-2026-01-evidence-ledger-decided.json"
    rewritten = json.loads(snapshot_path.read_text())
    entry_of(rewritten, "VC-EXC")["caveats"].append("rewritten after the decision")
    snapshot_path.write_text(json.dumps(rewritten))
    refused("decision_hash_not_recorded_in_record", validate_repository, tmp_path)


def test_orphan_snapshot_is_refused(tmp_path):
    folder, _ = write_event(tmp_path, frozen=full(), snapshot={})
    refused("snapshot_without_decision", validate_repository, tmp_path)


def test_decision_requires_its_ledger_snapshot(tmp_path):
    folder = complete_event(tmp_path)
    (folder / "msr-vehicle-attributes-2026-01-evidence-ledger-decided.json").unlink()
    refused("decision_without_snapshot", validate_repository, tmp_path)


def test_frozen_on_cannot_predate_the_frozen_contents():
    frozen = full()
    frozen["frozenOn"] = "2026-01-01"
    edited = copy.deepcopy(frozen)
    refused("sealed_copy_postdates_its_seal", validate_evolution, frozen, edited)


def test_new_candidates_after_freeze_are_dated_after_it():
    frozen = full()
    edited = copy.deepcopy(frozen)
    late = ledger(reference("VC-LATE", "late"))["candidates"][0]  # dated 2026-06-01/02
    edited["candidates"].append(late)
    refused("appended_before_freeze", validate_evolution, frozen, edited)


def test_shortlisted_claims_are_fixed_after_freeze():
    frozen = full()
    edited = copy.deepcopy(frozen)
    entry = entry_of(edited, "VC-EST")
    entry["claims"].append(claim("C2", "E-PAPER"))
    settle(entry, at="2026-07-01")
    refused("frozen_shortlisted_field_changed", validate_evolution, frozen, edited)


def test_shared_bytes_are_checked_against_every_earlier_entry():
    shared = method("VC-M", "same")
    a = established("VC-A", "same")
    b = established("VC-B", "same")
    for entry in (a, b):
        shortlist_emerging(entry)
        entry["identity"] = copy.deepcopy(shared["identity"])
        entry["evidence"].append(copy.deepcopy(shared["evidence"][-1]))
    refused("weight_hash_shared_by_two_candidates", validate_ledger, ledger(shared, a, b))


def test_repository_scan_binds_the_protocol_hash(tmp_path):
    write_event(tmp_path, frozen=full(), snapshot=full(), decision_doc=decision(full()))
    refused("decision_protocol_hash_mismatch", validate_repository, tmp_path)


def test_repository_scan_requires_protocol_to_cite_frozen_ledger(tmp_path):
    folder, _ = write_event(tmp_path, frozen=full())
    (folder / "msr-vehicle-attributes-2026-01-protocol.md").write_text("no hash here\n")
    refused("frozen_ledger_not_cited_by_protocol", validate_repository, tmp_path)


def test_repository_scan_refuses_decision_without_frozen_ledger(tmp_path):
    write_event(tmp_path, protocol=False, decision_doc={})
    refused("decision_without_frozen_ledger", validate_repository, tmp_path)


def test_protocol_requires_frozen_ledger_and_record_citation(tmp_path):
    folder, _ = write_event(tmp_path)
    refused("protocol_without_frozen_ledger", validate_repository, tmp_path)
    folder, _ = write_event(tmp_path / "b", frozen=full(), record=False)
    refused("protocol_hash_not_recorded_in_record", validate_repository, tmp_path / "b")
    folder = tmp_path / "c" / "docs" / "qualification" / "model-selection" / "vehicle-attributes"
    folder.mkdir(parents=True)
    (folder / "msr-vehicle-attributes-2026-01-protocol.md").write_text("protocol without any ledger\n")
    refused("protocol_without_frozen_ledger", validate_repository, tmp_path / "c")


def test_repository_scan_refuses_misplaced_ledger(tmp_path):
    folder = tmp_path / "docs" / "qualification" / "model-selection" / "person-attributes"
    folder.mkdir(parents=True)
    (folder / "msr-vehicle-attributes-2026-01-evidence-ledger.json").write_text(json.dumps(full()))
    refused("ledger_location_mismatch", validate_repository, tmp_path)


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
    for name in ("urllib", "http", "socket", "requests"):
        assert f"import {name}" not in source and f"from {name}" not in source
