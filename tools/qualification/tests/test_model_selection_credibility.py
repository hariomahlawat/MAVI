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
    return ledger(baseline(), established(), emerging(), reference(), excluded(), method(), capability="synthetic-colour")


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
    {"source": "docs/qualification/model-selection/vehicle-attributes/msr-synthetic-colour-2026-01.md"},
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
    refused("licence_reasoning_in_ledger", validate_ledger, ledger(entry))
    entry = established()
    entry["disposition"] = dict(reference()["disposition"], reasonClass="availability", reason="licence NC, cannot bundle")
    refused("licence_reasoning_in_ledger", validate_ledger, ledger(entry))


@pytest.mark.parametrize("where", ["summary", "caveat", "signal"])
def test_licence_reasoning_is_refused_in_any_ledger_text(where):
    entry = established()
    if where == "summary":
        entry["evidence"][1]["summary"] = "weights licence forbids redistribution"
    elif where == "caveat":
        entry["caveats"] = ["non-commercial licence"]
    else:
        entry["popularitySignals"] = [{"signal": "other", "value": "1", "observedOn": "2026-06-01",
                                       "source": "https://example.invalid/LICENSE"}]
    refused("licence_reasoning_in_ledger", validate_ledger, ledger(entry))


def test_evaluation_permission_disposition_may_discuss_terms():
    entry = established()
    entry["disposition"] = dict(reference()["disposition"], reasonClass="evaluation-permission",
                                reason="the weights licence does not permit evaluation",
                                revisitTrigger="licence terms change")
    assert validate_ledger(ledger(entry))["VC-EST"]["disposition"] == "REFERENCE_ONLY"


def test_promoted_shortlist_keeps_its_second_reviewer():
    entry = shortlist_emerging(established())
    entry["disposition"]["reviewedBy"] = entry["disposition"]["decidedBy"]
    refused("shortlist_reviewer_not_independent", validate_ledger, ledger(entry))


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
    document["eventId"] = "msr-synthetic-colour-2026-01"
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
    folder = tmp_path / "docs" / "qualification" / "model-selection" / "synthetic-colour"
    folder.mkdir(parents=True, exist_ok=True)
    document = full() if current is None else current
    (folder / "msr-synthetic-colour-2026-01-evidence-ledger.json").write_text(json.dumps(document))
    if snapshot is not None:
        (folder / "msr-synthetic-colour-2026-01-evidence-ledger-decided.json").write_text(json.dumps(snapshot))
    if frozen is not None:
        (folder / "msr-synthetic-colour-2026-01-evidence-ledger-frozen.json").write_text(json.dumps(frozen))
    if protocol:
        cited = document_sha256(frozen) if frozen is not None else ""
        protocol_path = folder / "msr-synthetic-colour-2026-01-protocol.md"
        frozen_on = frozen["frozenOn"] if frozen is not None else ""
        protocol_path.write_text(f"Frozen ledger SHA-256: {cited}\nFrozen on: {frozen_on}\n")
        if record:
            (folder / "msr-synthetic-colour-2026-01.md").write_text(
                f"Protocol SHA-256: {lf_normalised_sha256(protocol_path)}\n")
    if decision_doc is not None:
        (folder / "msr-synthetic-colour-2026-01-decision.json").write_text(json.dumps(decision_doc))
    return folder, document


def test_committed_ledgers_and_decisions_validate():
    validate_repository(REPO)


def complete_event(tmp_path, current=None):
    folder, _ = write_event(tmp_path, frozen=full(), snapshot=full(), current=current)
    summary = decision(full())
    summary["protocolSha256"] = lf_normalised_sha256(folder / "msr-synthetic-colour-2026-01-protocol.md")
    decision_path = folder / "msr-synthetic-colour-2026-01-decision.json"
    decision_path.write_text(json.dumps(summary))
    record_path = folder / "msr-synthetic-colour-2026-01.md"
    snapshot_path = folder / "msr-synthetic-colour-2026-01-evidence-ledger-decided.json"
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
    snapshot_path = folder / "msr-synthetic-colour-2026-01-evidence-ledger-decided.json"
    rewritten = json.loads(snapshot_path.read_text())
    entry_of(rewritten, "VC-EXC")["caveats"].append("rewritten after the decision")
    snapshot_path.write_text(json.dumps(rewritten))
    refused("decision_hash_not_recorded_in_record", validate_repository, tmp_path)


def test_orphan_snapshot_is_refused(tmp_path):
    folder, _ = write_event(tmp_path, frozen=full(), snapshot={})
    refused("snapshot_without_decision", validate_repository, tmp_path)


def test_working_ledger_and_snapshot_need_not_carry_frozen_on(tmp_path):
    current, snapshot = full(), full()
    del current["frozenOn"], snapshot["frozenOn"]
    folder, _ = write_event(tmp_path, frozen=full(), snapshot=snapshot, current=current)
    summary = decision(snapshot, frozen=full())
    summary["protocolSha256"] = lf_normalised_sha256(folder / "msr-synthetic-colour-2026-01-protocol.md")
    decision_path = folder / "msr-synthetic-colour-2026-01-decision.json"
    decision_path.write_text(json.dumps(summary))
    record_path = folder / "msr-synthetic-colour-2026-01.md"
    snapshot_path = folder / "msr-synthetic-colour-2026-01-evidence-ledger-decided.json"
    record_path.write_text(record_path.read_text() + f"{lf_normalised_sha256(decision_path)}\n"
                           f"{lf_normalised_sha256(snapshot_path)}\n")
    assert len(validate_repository(tmp_path)) == 4


def test_decision_requires_its_ledger_snapshot(tmp_path):
    folder = complete_event(tmp_path)
    (folder / "msr-synthetic-colour-2026-01-evidence-ledger-decided.json").unlink()
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
    (folder / "msr-synthetic-colour-2026-01-protocol.md").write_text("no hash here\n")
    refused("frozen_ledger_not_cited_by_protocol", validate_repository, tmp_path)


def test_repository_scan_refuses_decision_without_frozen_ledger(tmp_path):
    write_event(tmp_path, protocol=False, decision_doc={})
    refused("decision_without_frozen_ledger", validate_repository, tmp_path)


def test_protocol_requires_frozen_ledger_and_record_citation(tmp_path):
    folder, _ = write_event(tmp_path)
    refused("protocol_without_frozen_ledger", validate_repository, tmp_path)
    folder, _ = write_event(tmp_path / "b", frozen=full(), record=False)
    refused("protocol_hash_not_recorded_in_record", validate_repository, tmp_path / "b")
    folder = tmp_path / "c" / "docs" / "qualification" / "model-selection" / "synthetic-colour"
    folder.mkdir(parents=True)
    (folder / "msr-synthetic-colour-2026-01-protocol.md").write_text("protocol without any ledger\n")
    refused("protocol_without_frozen_ledger", validate_repository, tmp_path / "c")


def test_repository_scan_refuses_misplaced_ledger(tmp_path):
    folder = tmp_path / "docs" / "qualification" / "model-selection" / "person-attributes"
    folder.mkdir(parents=True)
    (folder / "msr-synthetic-colour-2026-01-evidence-ledger.json").write_text(json.dumps(full()))
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


# ------------------------------------------------- plate domain term: exact whole value only (M3 final round)

U = chr


def fw(text):
    return "".join(U(0xff00 + ord(ch) - 0x20) if ch != " " else " " for ch in text)


# The only values exempt from the licence scan: the whole field is the plate domain term, after normalisation.
EXEMPT_WHOLE_VALUES = [
    "license plate", "license plates", "licence plate", "licence plates", "License Plate", "LICENCE PLATES",
    "  license plate  ", "license" + U(0xa0) + "plate", "license" + U(0x3000) + "plates", "license" + U(9) + "plate",
    "lic" + U(0x200b) + "ense plate", "LICEN" + U(0xad) + "CE PLATE", fw("license plate"), fw("licence plates"),
]

OWNER_REFUSED = [
    "License plate weights to anyone", "Vendors: license plate weights to OEMs", "build & license plate models",
    "buy / license plate software", "vehicle and license plate crops", "applied to license plate recognition",
    "multi-line license plates", "license-plate", "licence-plate", "license plate.", '"license plate"',
    "(license plate)", "[license plate]", "license plate...", "license plate" + U(0x2026), "- license plate",
    "* license plate", "1. license plate", "a) license plate", "license plate:", "the license plate",
    "license plate detector", "license plates and licence plates", "license plate license plate",
    "https://huggingface.co/example-org/yolo-license-plate-detection", "yolo-license-plates.onnx",
]

COLD_B_CASES = [
 # must refuse (owner)
 "build and license plate models","permission to license plate weights","buy or license plate software",
 # punctuation conjunctions
 "build & license plate models","build + license plate models","buy / license plate software","buy | license plate software",
 "buy \u00b7 license plate software","copy, license plate weights","copy; license plate weights",
 "build &license plate models","build and/or license plate models","build and / license plate models",
 "we copy\u2026 license plate weights","Vendors: license plate weights to OEMs","Vendors. License plate weights to OEMs!",
 "the \"vendors\" license plate weights","the 'vendors' license plate weights","vendors' license plate weights",
 "(we) license plate weights","we (license plate weights)","*license plate weights*","we * license plate weights",
 "we\u3000& license plate weights", "build \uff06 license plate models", "build ＆license plate",
 # allowlist entry as verb context
 "makers of ALPR license plate weights commercially","firms that sell OCR license plate models","the car license plate models",
 "any license plate weights you want","License plate weights to anyone","License plates under MIT",
 "who per license plate", "per license plate weights",
 # prefixes
 "sub-license plate","sublicense plate","re-license plate","re license plate","open-license plate","the sub\u00adlicense plate",
 "the sub\u200blicense plate","the sub\u2011license plate","x-license plate","the-license plate","sub_license plate",
 "sub\u2010license plate", "sub\u2e3alicense plate", "sub~license plate", "sub~ license plate", "sub ~ license plate",
 "sub\u02d7license plate", "sub\u2027license plate", "sub\u2022license plate", "sub \u2022 license plate",
 "sub\u00a0license plate", "sub\u2063license plate", "sub\u034flicense plate", "sub\u180elicense plate", "sub\u3164license plate",
 "sub\u115flicense plate", "sub\u2800license plate", "sub\uffa0license plate",
 # look-alikes
 "the l\u0456cense plate weights","the \u217cicense plate","\u0430nd license plate","\uff41nd license plate","the licen\u0455e plate",
 "\u0430nd license plate", "th\u0435 license plate", "and\u0301 license plate", "\u24d0nd license plate", "\U0001d41a\U0001d427\U0001d41d license plate",
 "the license plate license","the license plate, licensed under MIT","the license plates; re-licensed",
 "the l1cense plate", "the lic\u0435nse", "the \u029fi\u1d04\u1d07\u0274se",
 # benign expected
 "the license plate detector","indian licence-plate dataset","number plate","yolov11-license-plate-detection",
 "https://huggingface.co/foo/yolov11-license-plate-detection","license_plate_detector.pt","ALPR / license plate",
 "Vehicle license plate","a licence plate","LICENSE PLATE","license-plates", "keremberke/yolov8n-license-plate-extraction",
 "license plate", "plates (license plate)",
]

COLD_B_LIST = [
    "Owners of the car license plate data to insurers",
    "Makers of every vehicle license plate weights for a fee",
    "We require that each LPR license plate weights separately",
    "Suppliers to the front license plate models",
    "Vendors who sell to ALPR license plate models commercially",
    "We build \"and\" license plate models",
    "weights (license plate models to OEMs)",
    "The authors [license plate weights] under CC-BY",
    "a) license plate weights to third parties",
    "1. License plate weights to anyone",
    "build > license plate", "buy = license plate", "build ... license plate", "build \u2026license plate",
]

COLD_A_REFUSE = [
 "sub-license plate weights", "sub license plate weights", "sublicense plate weights", "Sub-Licence-plate",
 "re-licence plates", "relicense plate", "cross-license plate", "un-licensed plate", "unlicense plate",
 "sub\u2010license plate", "sub\u2014license plate", "sub\u00a0license plate", "sub\u200blicense plate",
 "sub\u200b-\u200blicense plate", "sub-\u200blicense plate", "SUB\uff0dLICENSE PLATE", fw("sub-license plate"),
 "sub/license plate", "sub.license plate", "(sub)license plate", "sub_license plate",
 "you may license plate weights", "we license plates", "To license plate data", "freely license plate data",
 "license plate licensed under MIT", "licence-plate weights; licence: CC-BY-NC",
 "license plate sublicensable", "licence plate (licensed)",
 "l\u0456cense", "lic\u0435nse plate", "\u217cicense", "lice\u0578se",
 "\uff2c\uff49\uff43\uff45\uff4e\uff53\uff45", "LICENSE", "license-free", "licensor", "licensee", "licensing",
 "open-license plate weights", "open license plate weights", "free-license plate weights",
 "commercial-license plate weights", "permissive license plate weights", "research-license plate weights",
 "royalty-free license plate weights", "MIT license plate weights", "apache license plate weights",
 "GPL-license plate weights", "proprietary license plate weights", "trans-license plate", "post-license plate",
 "super-license plate", "semi-license plate", "para-license plate", "all-license plate",
 "Vendors license plate weights commercially", "Authors license plate models under AGPL",
 "They will license plate models", "Ultralytics license plate weights under AGPL-3.0",
 "users can't license plate models", "the right to sub-license plate", "the right to sub- license plate",
 "license\u2060plate", "license\u00adplate",
 "re\u0301-license plate", "\u0455ub-license plate", "s\u0075\u0062-license plate",
 "sub\u2028license plate", "sub\u3000license plate", "sub\ufe63license plate", "sub\u2212license plate",
 "sub\u00b7license plate", "sub\u2022license plate", "sub\u30fclicense plate",
]

COLD_A_PLATE_TEXT = [
 "license plate", "licence plate", "License Plate", "LICENCE-PLATE", "license-plates", "licence plates",
 "Licence-plate detector", "license\u2011plate", "license\u00a0plate", "lic\u200bense plate",
 "\uff4c\uff49\uff43\uff45\uff4e\uff53\uff45 \uff50\uff4c\uff41\uff54\uff45",
 "the license plate", "vehicle license plate", "detects license plates in images", "reads licence-plate text",
 "a license plate reader", "Indian license plates", "license plate recognition (LPR)", "car's license plate",
 "license plate, number plate", "ALPR / license plate", "\"license plate\"", "on license plates.", "license-plate OCR",
 "CCPD license plate dataset", "multi-line license plates", "dual-row licence plates", "double-line license plate",
 "non-standard license plates", "under-exposed license plates", "self-driving license plate dataset",
 "over-exposed license plates", "pre-processed license plates", "re-identification license plate",
 "license plates and licence plates", "number/license plate", "license plate/ number plate",
 "OCR to license plate text", "Applied to license plate images", "and license plates", "license\tplate",
 "trained on CCPD and license plates", "license plates or vehicles", "cars, trucks and license plates",
 "license  plate",
]


def _in_scan(value):
    from model_selection.credibility import has_licence_wording
    return has_licence_wording(value)


@pytest.mark.parametrize("value", EXEMPT_WHOLE_VALUES)
def test_only_the_whole_plate_domain_value_is_exempt(value):
    entry = established()
    entry["caveats"] = [value]
    validate_ledger(ledger(entry))


ALL_PROBES = sorted(set(OWNER_REFUSED + COLD_B_CASES + COLD_B_LIST + COLD_A_REFUSE + COLD_A_PLATE_TEXT))


@pytest.mark.parametrize("value", [v for v in ALL_PROBES if " ".join(v.split()).casefold() not in
                                   ("license plate", "license plates", "licence plate", "licence plates")
                                   and "licen" in v.casefold()])
def test_every_other_value_containing_licence_letters_is_refused(value):
    entry = established()
    entry["caveats"] = [value]
    refused("licence_reasoning_in_ledger", validate_ledger, ledger(entry))


def test_probe_values_with_obfuscated_letters_are_refused_too():
    """Values whose "licen" is hidden by look-alikes, format characters or full-width letters are refused unless the
    whole value normalises to the plate domain term."""
    from model_selection.credibility import _normalise_text, _skeleton
    exempt = {"license plate", "license plates", "licence plate", "licence plates"}
    for value in ALL_PROBES:
        normal = _normalise_text(value)
        if "licen" in _skeleton(normal) and normal not in exempt:
            assert _in_scan(value), ascii(value)


def test_no_positional_noun_inference_remains():
    import model_selection.credibility as module
    for name in ("_NOUN_CONTEXT", "_plate_phrase_is_noun", "_PLATE_PHRASE_RE", "_CLAUSE_ENDS"):
        assert not hasattr(module, name), name
    assert module._PLATE_DOMAIN_VALUES == {"license plate", "license plates", "licence plate", "licence plates"}


def test_licence_keys_never_take_the_exemption():
    for key in ("license plate", "license_plate", "licensePlate", "plateLicence", "l" + U(0x456) + "cense"):
        document = ledger(established())
        document["candidates"][0][key] = 1
        refused("licence_field_in_ledger", validate_ledger, document)


def test_pure_non_latin_words_never_fold_to_licence():
    cyrillic = "".join(map(U, (0x43b, 0x438, 0x446, 0x435, 0x43d, 0x437, 0x438, 0x44f)))
    greek = "".join(map(U, (0x3bb, 0x3b9, 0x3ba, 0x3b5, 0x3bd, 0x3c3, 0x3b5)))
    assert not _in_scan(cyrillic) and not _in_scan(greek)



# ------------------------------------------------- typed exact identifier exemptions (M3 final round, item 3)

REPO_URL = "https://huggingface.co/example-org/yolov11-license-plate-detection"
FILE_NAME = "yolo-v9-s-608-license-plates-end2end.onnx"
SOURCE_URL = "https://example.invalid/example-org/License-Plate-Detection/README.md"


def identified_entry():
    entry = established()
    entry["identity"]["repository"] = REPO_URL
    entry["identity"]["files"][0]["path"] = FILE_NAME
    entry["evidence"][0]["source"] = SOURCE_URL
    return entry


def exemptions(*items):
    return [dict(zip(("candidateId", "fieldKind", "value", "reason"), item)) for item in items]


DECLARED = exemptions(("VC-EST", "repository-url", REPO_URL, "upstream repository name"),
                      ("VC-EST", "artefact-filename", FILE_NAME, "upstream release asset name"),
                      ("VC-EST", "source-url", SOURCE_URL, "upstream README location"))


def identified_ledger(declared=None, entry=None):
    document = ledger(entry or identified_entry())
    if declared is not None:
        document["identifierExemptions"] = declared
    return document


def test_declared_exact_identifiers_are_exempt_in_their_declared_fields_only():
    validate_ledger(identified_ledger(DECLARED))
    refused("licence_reasoning_in_ledger", validate_ledger, identified_ledger())  # undeclared: refused


@pytest.mark.parametrize("field", ["caveat", "summary", "locator", "candidateName", "reason"])
def test_the_same_literal_in_prose_is_refused(field):
    entry = identified_entry()
    if field == "caveat":
        entry["caveats"] = [REPO_URL]
    elif field == "summary":
        entry["evidence"][0]["summary"] = REPO_URL
    elif field == "locator":
        entry["evidence"][0]["locator"] = FILE_NAME
    elif field == "candidateName":
        entry["candidateName"] = REPO_URL
    else:
        declared = [dict(DECLARED[0], reason=f"named {REPO_URL}")] + DECLARED[1:]
        refused("licence_reasoning_in_ledger", validate_ledger, identified_ledger(declared, entry))
        return
    refused("licence_reasoning_in_ledger", validate_ledger, identified_ledger(DECLARED, entry))


@pytest.mark.parametrize("value", [REPO_URL + "x", REPO_URL[:-1], REPO_URL.rsplit("/", 1)[0] + "/",
                                   "https://huggingface.co/example-org/", "license-plate-detection",
                                   REPO_URL.upper(), REPO_URL + "/", " " + REPO_URL, "*license-plate*",
                                   ".*license-plate.*", "https://huggingface.co/*"])
def test_only_whole_value_equality_matches(value):
    declared = [dict(DECLARED[0], value=value)] + DECLARED[1:]
    with pytest.raises(CredibilityError):
        validate_ledger(identified_ledger(declared))


def test_wrong_kind_missing_reason_unknown_candidate_and_prose_values_are_refused():
    for item in (("VC-EST", "artefact-filename", REPO_URL, "kind does not hold this value"),
                 ("VC-EST", "source-url", REPO_URL, "kind does not hold this value"),
                 ("VC-EST", "repository-url", REPO_URL, " "),
                 ("VC-EST", "repository-url", REPO_URL, None),
                 ("VC-ZZZ", "repository-url", REPO_URL, "unknown candidate"),
                 ("VC-EST", "any-text", REPO_URL, "kind outside the closed set"),
                 ("VC-EST", "repository-url", "license plate weights", "prose is never an identifier")):
        declared = exemptions(item) + DECLARED[1:]
        with pytest.raises(CredibilityError):
            validate_ledger(identified_ledger(declared))
    duplicate = DECLARED + [DECLARED[0]]
    refused("identifier_exemption_duplicate", validate_ledger, identified_ledger(duplicate))
    extra = [dict(DECLARED[0], pattern="*")] + DECLARED[1:]
    with pytest.raises(CredibilityError):
        validate_ledger(identified_ledger(extra))


def test_exemptions_are_fixed_by_the_freeze():
    frozen = identified_ledger(DECLARED)
    frozen["frozenOn"] = "2026-06-10"
    later = copy.deepcopy(frozen)
    later["identifierExemptions"] = [dict(DECLARED[0], reason="a different reason")] + DECLARED[1:]
    refused("identifier_exemptions_changed_after_freeze", validate_evolution, frozen, later)
    unfrozen = copy.deepcopy(frozen)
    del unfrozen["identifierExemptions"]
    later = copy.deepcopy(unfrozen)
    later["identifierExemptions"] = DECLARED
    with pytest.raises(CredibilityError):  # the frozen copy, without exemptions, is refused on its own scan
        validate_evolution(unfrozen, later)
    unfrozen_clean = ledger(established())
    unfrozen_clean["frozenOn"] = "2026-06-10"
    added = copy.deepcopy(unfrozen_clean)
    added["identifierExemptions"] = exemptions(("VC-EST", "model-identifier", "Synthetic-est", "name"))
    added["candidates"][0]["candidateName"] = "Synthetic-est"
    with pytest.raises(CredibilityError):
        validate_evolution(unfrozen_clean, added)



@pytest.mark.parametrize("value", ["the l1cense plate", "".join(map(U, (0x29f, 0x26a, 0x1d04, 0x1d07, 0x274))) + "se"])
def test_digit_and_small_capital_look_alikes_are_refused(value):
    assert _in_scan(value)


MODEL_ID = "acme-license-plate-yolo-v2"


def test_model_identifier_exempts_only_the_exact_frozen_candidate_name():
    """Owner decision: `model-identifier` maps to `candidateName` only, by exact whole-value, frozen declaration."""
    entry = established()
    entry["candidateName"] = MODEL_ID
    declared = exemptions(("VC-EST", "model-identifier", MODEL_ID, "upstream model identifier"))
    validate_ledger(identified_ledger(declared, copy.deepcopy(entry)))
    refused("licence_reasoning_in_ledger", validate_ledger, identified_ledger(None, copy.deepcopy(entry)))
    for near_miss in (MODEL_ID + "x", MODEL_ID[:-1], MODEL_ID.upper(), "acme-license-plate", "*license-plate*"):
        with pytest.raises(CredibilityError):
            validate_ledger(identified_ledger(exemptions(("VC-EST", "model-identifier", near_miss, "r")),
                                              copy.deepcopy(entry)))
    for field in ("caveats", "summary", "repository"):
        prose = copy.deepcopy(entry)
        if field == "caveats":
            prose["caveats"] = [MODEL_ID]
        elif field == "summary":
            prose["evidence"][0]["summary"] = MODEL_ID
        else:
            prose["identity"]["repository"] = MODEL_ID  # a repository field needs its own repository-url exemption
        with pytest.raises(CredibilityError):
            validate_ledger(identified_ledger(declared, prose))
    spaced = copy.deepcopy(entry)
    spaced["candidateName"] = "Acme license plate YOLO"
    refused("licence_reasoning_in_ledger", validate_ledger, identified_ledger(
        exemptions(("VC-EST", "model-identifier", "Acme license plate YOLO", "a name with spaces is prose")), spaced))
