"""Method revision M3: benchmark-only baseline component and derived gate-only baseline composition.

Synthetic fixtures only (model_selection_fixtures.py). Every name, hash and date is invented.
"""

from __future__ import annotations

import copy
import subprocess

import pytest

from model_selection.credibility import (
    CredibilityError,
    document_sha256,
    validate_decision,
    validate_evolution,
    validate_ledger,
)
from model_selection_fixtures import (
    RECORDED,
    baseline,
    base_entry,
    decision,
    emerging,
    established,
    evaluated_row,
    excluded,
    ledger,
    reference,
    sha,
)

PARTNERS = [{"candidateId": "PD-A", "identitySha256": sha("PD-A")},
            {"candidateId": "PD-B", "identitySha256": sha("PD-B")}]


def refused(code, function, *args, **kwargs):
    with pytest.raises(CredibilityError) as error:
        function(*args, **kwargs)
    assert str(error.value).split(":")[0] == code, str(error.value)


def block():
    return {
        "purpose": "recogniser of the single gate-only baseline composition",
        "protocolSection": "protocol section 2.4",
        "configurationSha256": sha("bob-configuration"),
        "adapterSha256": sha("bob-adapter"),
        "hostManifests": {
            "dev-windows-cpu": [{"path": "bin/tool.exe", "sha256": sha("exe"), "size": 10},
                                {"path": "lib/core.dll", "sha256": sha("dll"), "size": 20}],
            "dev-linux-cpu": [{"path": "bin/tool", "sha256": sha("elf"), "size": 12}],
        },
        "evaluationPermissions": [{"artefact": "executable, runtime libraries and model data",
                                   "decidedBy": "synthetic-owner", "decidedOn": RECORDED,
                                   "primarySourceSha256": sha("terms-page")}],
        "compositions": [{"compositionId": "GATE-BASE", "partnerEventId": "msr-plate-detector-2026-01",
                          "eligiblePartners": copy.deepcopy(PARTNERS), "partnerRankingRuleSha256": sha("rule"),
                          "layerAGatesSha256": sha("gates"),
                          "derivationRule": "highest-ranked partner passing every frozen Layer-A gate"}],
    }


def bob(candidate_id="VC-BOB", label="bob", *, entry=None):
    if entry is None:
        entry = base_entry(candidate_id, label)
        entry["claims"] = []  # no traceable task-quality claim: computes reference-only
    entry["disposition"] = {"status": "BENCHMARK_BASELINE", "reasonClass": "technical",
                            "reason": "measured only to define the frozen gate-only baseline composition",
                            "revisitTrigger": None, "decidedBy": "synthetic-owner"}
    entry["benchmarkBaseline"] = block()
    return entry


def m3_ledger(*entries, revision="msr-v1-m3", capability="vehicle-colour"):
    document = ledger(*(entries or (baseline(), established(), emerging(), bob())), capability=capability)
    document["methodRevision"] = revision
    return document


def resolution(**changes):
    record = {"compositionId": "GATE-BASE", "benchmarkBaselineId": "VC-BOB", "partnerCandidateId": "PD-A",
              "partnerIdentitySha256": sha("PD-A"), "partnerRankingRuleSha256": sha("rule"),
              "layerAResultSha256": sha("layer-a"), "resolvedAt": "2026-07-01T10:00:00Z",
              "dExecutionStartedAt": "2026-07-01T11:00:00Z"}
    record.update(changes)
    record["recordSha256"] = document_sha256(record)
    return record


def bob_row(document):
    entry = next(e for e in document["candidates"] if e["candidateId"] == "VC-BOB")
    row = evaluated_row(entry, score=0.0)
    row.update(technicalGates="n/a", comparativeScore=None, taskQualityScore=None,
               hostManifestSha256s={p: document_sha256(m) for p, m in entry["benchmarkBaseline"]["hostManifests"].items()})
    return row


def m3_decision(document, **kwargs):
    summary = decision(document, **kwargs)
    summary["evaluated"].append(bob_row(document))
    summary["gateOnlyBaselineResolutions"] = [resolution()]
    return summary


# ------------------------------------------------------------------ positive


def test_benchmark_baseline_is_accepted_measured_and_never_ranked():
    document = m3_ledger()
    summary = validate_ledger(document)
    assert summary["VC-BOB"] == {"class": "reference-only", "provenanceConfidence": "High",
                                 "disposition": "BENCHMARK_BASELINE"}
    validate_decision(m3_decision(document), document, document)


def test_bob_scoring_highest_cannot_be_named_anywhere():
    document = m3_ledger()
    summary = m3_decision(document)
    row = summary["evaluated"][-1]
    for gates, score, quality in (("passed", 9.9, 9.9), ("n/a", 9.9, None), ("n/a", None, 9.9), ("failed", None, 0.0)):
        changed = copy.deepcopy(summary)
        changed["evaluated"][-1].update(technicalGates=gates, comparativeScore=score, taskQualityScore=quality)
        refused("benchmark_baseline_row_scored", validate_decision, changed, document, document)
    assert row["technicalGates"] == "n/a"
    for field in ("highestTaskQualityEvaluated", "strongestEvaluatedTechnical"):
        changed = copy.deepcopy(summary)
        changed[field] = "VC-BOB"
        refused("benchmark_baseline_in_derived_output", validate_decision, changed, document, document)
    changed = copy.deepcopy(summary)
    changed["strongestReported"]["candidateId"] = "VC-BOB"
    refused("benchmark_baseline_in_derived_output", validate_decision, changed, document, document)
    changed = copy.deepcopy(summary)
    changed["strongestClearedPerProfile"]["dev-profile"] = "VC-BOB"
    refused("benchmark_baseline_in_derived_output", validate_decision, changed, document, document)
    changed = copy.deepcopy(summary)
    changed["implementation"]["components"] = ["VC-BOB"]
    refused("benchmark_baseline_in_derived_output", validate_decision, changed, document, document)
    changed = copy.deepcopy(summary)
    changed["licence"]["VC-BOB"] = {"dev-profile": "CLEARED"}
    refused("unknown_field", validate_decision, changed, document, document)


def test_bob_must_be_evaluated_on_its_pinned_bytes_and_host_manifests():
    document = m3_ledger()
    summary = m3_decision(document)
    changed = copy.deepcopy(summary)
    changed["evaluated"].pop()
    refused("evaluated_set_differs_from_shortlist", validate_decision, changed, document, document)
    changed = copy.deepcopy(summary)
    changed["evaluated"][-1]["hostManifestSha256s"]["dev-linux-cpu"] = sha("other bytes")
    refused("benchmark_baseline_host_manifest_mismatch", validate_decision, changed, document, document)
    changed = copy.deepcopy(summary)
    del changed["evaluated"][-1]["hostManifestSha256s"]["dev-linux-cpu"]
    refused("benchmark_baseline_host_manifest_mismatch", validate_decision, changed, document, document)
    changed = copy.deepcopy(summary)
    changed["evaluated"][-1]["artefactSha256s"] = [sha("re-pinned weights")]
    refused("evaluated_artefact_differs_from_ledger", validate_decision, changed, document, document)
    changed = copy.deepcopy(summary)
    changed["evaluated"][0]["hostManifestSha256s"] = {}
    refused("host_manifests_only_for_benchmark_baseline", validate_decision, changed, document, document)


# ------------------------------------------------------------------ class restriction and pinning


@pytest.mark.parametrize("make", [established, lambda: emerging(shortlisted=False), excluded, baseline])
def test_benchmark_baseline_is_refused_for_every_class_but_reference_only(make):
    entry = bob(entry=make())
    refused("benchmark_baseline_class", validate_ledger, m3_ledger(entry))


def test_reference_only_role_requires_m3_ledger_and_v1_scope():
    refused("benchmark_baseline_requires_m3", validate_ledger, m3_ledger(revision="msr-v1-m1"))
    refused("m2_scope_unsupported", validate_ledger, m3_ledger(revision="msr-v1-m2"))
    s2c = m3_ledger(revision="msr-v1-m2", capability="vehicle-attributes")
    refused("benchmark_baseline_requires_m3", validate_ledger, s2c)
    refused("m3_scope_unsupported", validate_ledger, m3_ledger(capability="vehicle-attributes"))


def test_bob_requires_high_provenance_manifests_and_permissions():
    unpinned = bob()
    unpinned["identity"]["files"][0]["sha256"] = "UNKNOWN"
    refused("benchmark_baseline_requires_pinned_provenance", validate_ledger, m3_ledger(unpinned))
    third_party = bob(entry=reference())
    refused("benchmark_baseline_requires_pinned_provenance", validate_ledger, m3_ledger(third_party))
    for mutate, code in (
        (lambda b: b.pop("hostManifests"), "missing_field"),
        (lambda b: b.update(hostManifests={}), "benchmark_baseline_host_manifest_required"),
        (lambda b: b["hostManifests"].update({"dev-linux-cpu": []}), "benchmark_baseline_host_manifest_required"),
        (lambda b: b["hostManifests"]["dev-windows-cpu"].reverse(), "benchmark_baseline_manifest_not_sorted_unique"),
        (lambda b: b["hostManifests"]["dev-windows-cpu"][0].update(sha256="UNKNOWN"), "malformed"),
        (lambda b: b["hostManifests"]["dev-windows-cpu"][0].update(size=0), "number_required"),
        (lambda b: b.update(evaluationPermissions=[]), "benchmark_baseline_permission_required"),
        (lambda b: b.update(configurationSha256="UNKNOWN"), "malformed"),
        (lambda b: b.pop("adapterSha256"), "missing_field"),
        (lambda b: b["compositions"][0]["eligiblePartners"].reverse(), "eligible_partners_not_sorted_unique"),
        (lambda b: b["compositions"][0]["eligiblePartners"].append(
            {"candidateId": "VC-BOB", "identitySha256": sha("x")}), "benchmark_baseline_cannot_be_its_own_partner"),
        (lambda b: b["compositions"].append(copy.deepcopy(b["compositions"][0])), "duplicate_composition_id"),
    ):
        entry = bob()
        mutate(entry["benchmarkBaseline"])
        refused(code, validate_ledger, m3_ledger(entry))
    stray = established()
    stray["benchmarkBaseline"] = block()
    refused("benchmark_baseline_block_without_role", validate_ledger, m3_ledger(stray))
    missing = bob()
    del missing["benchmarkBaseline"]
    refused("not_object", validate_ledger, m3_ledger(missing))
    collides = bob()
    collides["benchmarkBaseline"]["compositions"][0]["compositionId"] = "VC-EST"
    refused("gate_only_composition_id_collides", validate_ledger, m3_ledger(established(), collides))


# ------------------------------------------------------------------ immutability after freeze


def test_bob_set_identity_and_composition_rule_are_fixed_after_freeze():
    frozen = m3_ledger()
    for mutate in (
        lambda e: e["benchmarkBaseline"]["hostManifests"]["dev-linux-cpu"][0].update(sha256=sha("swapped")),
        lambda e: e["benchmarkBaseline"].update(configurationSha256=sha("other configuration")),
        lambda e: e["benchmarkBaseline"].update(adapterSha256=sha("other adapter")),
        lambda e: e["benchmarkBaseline"]["compositions"][0]["eligiblePartners"].append(
            {"candidateId": "PD-C", "identitySha256": sha("PD-C")}),
        lambda e: e["benchmarkBaseline"]["compositions"][0].update(partnerRankingRuleSha256=sha("new rule")),
        lambda e: e["benchmarkBaseline"]["evaluationPermissions"][0].update(decidedBy="someone else"),
    ):
        later = copy.deepcopy(frozen)
        mutate(later["candidates"][-1])
        refused("frozen_benchmark_baseline_field_changed", validate_evolution, frozen, later)
    removed = copy.deepcopy(frozen)
    removed["candidates"][-1]["disposition"] = {"status": "REFERENCE_ONLY", "reasonClass": "credibility",
                                                "reason": "held", "revisitTrigger": "never", "decidedBy": "x"}
    del removed["candidates"][-1]["benchmarkBaseline"]
    refused("benchmark_baselines_changed_after_freeze", validate_evolution, frozen, removed)
    plain = m3_ledger(baseline(), established(), emerging())
    refused("benchmark_baselines_changed_after_freeze", validate_evolution, plain, frozen)


def test_bob_cannot_promote_itself_or_enter_a_ranked_set():
    document = m3_ledger()
    summary = m3_decision(document)
    summary["rankedSets"] = {"top-k-recogniser": ["VC-EST", "VC-EMG"], "finalists": ["VC-EST"]}
    validate_decision(summary, document, document)
    for members, code in ((["VC-EST", "VC-BOB"], "benchmark_baseline_in_ranked_set"),
                          (["GATE-BASE"], "ranked_set_member_not_evaluated")):
        changed = copy.deepcopy(summary)
        changed["rankedSets"]["frontier"] = members
        refused(code, validate_decision, changed, document, document)
    # MAVI's own measurement can never enter the ledger as evidence for the baseline (I4).
    promoted = copy.deepcopy(document)
    promoted["candidates"][-1]["evidence"].append(
        {"evidenceId": "E-MAVI", "type": "independent-benchmark", "producer": {"group": "mavi-bakeoff",
         "relation": "independent"}, "source": "evidence-store:plates/run", "locator": "D", "retrievedOn": RECORDED,
         "retrievedSha256": sha("run"), "recordedAt": RECORDED, "summary": "MAVI bake-off D-score",
         "scope": "method", "independenceBasis": "MAVI", "subTask": "T-VC", "objectClass": "vehicle"})
    refused("mavi_evidence_in_ledger", validate_ledger, promoted)
    # Any external promotion out of reference-only ends the role: the ledger is refused, never silently re-ranked.
    established_bob = bob(entry=established("VC-BOB", "bob"))
    refused("benchmark_baseline_class", validate_ledger, m3_ledger(established_bob))


# ------------------------------------------------------------------ outcome and scope


def _closed_without_ranked_pass(document, outcome):
    summary = m3_decision(document, state="CLOSED", implementation=None)
    for row in summary["evaluated"][:-1]:
        row.update(technicalGates="failed", comparativeScore=None)
    summary.update(strongestEvaluatedTechnical=None, strongestClearedPerProfile={"dev-profile": None},
                   outcome=outcome)
    return summary


def test_no_outcome_can_follow_from_a_bob_alone():
    document = m3_ledger()
    validate_decision(_closed_without_ranked_pass(document, "NO_QUALIFIABLE_CANDIDATE"), document, document)
    for outcome in ("BASELINE_SELECTED", "INCUMBENT_RETAINED"):
        refused("m3_outcome_requires_no_qualifiable_candidate", validate_decision,
                _closed_without_ranked_pass(document, outcome), document, document)
    selected = _closed_without_ranked_pass(document, "BASELINE_SELECTED")
    selected["implementation"] = {"components": ["VC-BOB"], "decidedBy": "o", "rationale": "r"}
    refused("benchmark_baseline_in_derived_output", validate_decision, selected, document, document)


def test_decision_v2_refuses_any_bob_and_is_otherwise_unchanged():
    document = m3_ledger()
    v2 = {"schema": "mavi-model-selection-decision-v2", "eventId": document["eventId"]}
    refused("m3_v2_unsupported", validate_decision, v2, document, document)
    plain = ledger(baseline(), established(), emerging(), capability="vehicle-colour")
    with pytest.raises(CredibilityError) as error:  # without a BOB the v2 path is reached exactly as before
        validate_decision(v2, plain, plain)
    assert str(error.value).startswith("decision_v2_requires_repository")


def test_m1_decisions_without_bob_reject_m3_fields():
    plain = ledger(baseline(), established(), emerging(), capability="vehicle-colour")
    summary = decision(plain)
    validate_decision(summary, plain, plain)
    with_field = copy.deepcopy(summary)
    with_field["gateOnlyBaselineResolutions"] = []
    refused("unknown_field", validate_decision, with_field, plain, plain)
    row = copy.deepcopy(summary)
    row["evaluated"][0]["technicalGates"] = "n/a"
    row["evaluated"][0]["comparativeScore"] = None
    refused("value_not_allowed", validate_decision, row, plain, plain)


# ------------------------------------------------------------------ two-stage resolution (addendum 2026-10-14)


def test_gate_only_composition_is_resolved_from_the_frozen_universe_before_d():
    document = m3_ledger()
    base = m3_decision(document)
    cases = (
        (resolution(partnerCandidateId="PD-Z", partnerIdentitySha256=sha("PD-Z")),
         "baseline_partner_not_in_frozen_universe"),
        (resolution(partnerIdentitySha256=sha("PD-A retrained")), "baseline_partner_not_in_frozen_universe"),
        (resolution(partnerCandidateId="VC-BOB", partnerIdentitySha256=sha("x")),
         "baseline_partner_not_in_frozen_universe"),
        (resolution(partnerRankingRuleSha256=sha("another rule")), "baseline_ranking_rule_mismatch"),
        (resolution(resolvedAt="2026-07-01T11:00:00Z"), "baseline_resolved_after_d_started"),
        (resolution(resolvedAt="2026-07-02T09:00:00Z"), "baseline_resolved_after_d_started"),
        (resolution(resolvedAt="2026-06-09T23:59:59Z"), "baseline_resolved_before_freeze"),
        (resolution(resolvedAt="2026-07-01 10:00:00"), "instant_malformed"),
        (resolution(compositionId="GATE-OTHER"), "gate_only_composition_not_frozen"),
        (resolution(benchmarkBaselineId="VC-EST"), "gate_only_composition_not_frozen"),
    )
    for record, code in cases:
        changed = copy.deepcopy(base)
        changed["gateOnlyBaselineResolutions"] = [record]
        refused(code, validate_decision, changed, document, document)
    altered = copy.deepcopy(base)
    altered["gateOnlyBaselineResolutions"][0].update(partnerCandidateId="PD-B", partnerIdentitySha256=sha("PD-B"))
    refused("baseline_resolution_record_altered", validate_decision, altered, document, document)
    for value in (None, []):
        missing = copy.deepcopy(base)
        missing["gateOnlyBaselineResolutions"] = value
        if value is None:
            del missing["gateOnlyBaselineResolutions"]
        refused("gate_only_composition_unresolved", validate_decision, missing, document, document)
    twice = copy.deepcopy(base)
    twice["gateOnlyBaselineResolutions"] = [resolution(), resolution()]
    refused("gate_only_composition_resolved_twice", validate_decision, twice, document, document)


def test_gate_only_composition_never_enters_ranking_or_implementation():
    document = m3_ledger()
    summary = m3_decision(document)
    for field in ("strongestEvaluatedTechnical", "highestTaskQualityEvaluated"):
        changed = copy.deepcopy(summary)
        changed[field] = "GATE-BASE"
        with pytest.raises(CredibilityError):
            validate_decision(changed, document, document)
    changed = copy.deepcopy(summary)
    changed["evaluated"].append(dict(changed["evaluated"][0], candidateId="GATE-BASE"))
    refused("evaluated_candidate_not_in_ledger", validate_decision, changed, document, document)
    changed = copy.deepcopy(summary)
    changed["implementation"]["components"] = ["GATE-BASE"]
    refused("implementation_not_evaluated", validate_decision, changed, document, document)


# ------------------------------------------------------------------ committed ledgers are untouched


def test_no_committed_ledger_or_decision_changed_on_this_branch():
    changed = subprocess.run(
        ["git", "diff", "--name-only", "origin/main...HEAD", "--", "docs/qualification/model-selection/*/*.json"],
        capture_output=True, text=True, check=False,
    )
    if changed.returncode != 0:
        pytest.skip("origin/main is not available in this checkout")
    assert changed.stdout.strip() == ""
