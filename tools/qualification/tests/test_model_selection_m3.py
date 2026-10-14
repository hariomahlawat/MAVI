"""Method revision M3: benchmark-only baseline component and derived gate-only baseline composition.

Synthetic fixtures only (model_selection_fixtures.py). Every name, hash and date is invented.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
from pathlib import Path

import pytest

from model_selection import baseline_seal as bs
from model_selection.credibility import (
    CredibilityError,
    canonical_json,
    document_sha256,
    lf_normalised_sha256,
    validate_decision,
    validate_evolution,
    validate_ledger,
    validate_repository,
)
from model_selection_fixtures import (
    RECORDED,
    base_entry,
    baseline,
    checkpoint_identity,
    decision,
    emerging,
    established,
    evaluated_row,
    excluded,
    ledger,
    reference,
    sha,
)

EVENT = "msr-vehicle-colour-2026-01"
PARTNER_EVENT = "msr-plate-detector-2026-01"
GATE = "GATE-BASE"
PROTOCOL = sha("protocol")
SEALED_AT = "2026-07-01T10:00:00Z"
D_STARTED = "2026-07-02T09:00:00Z"
GATE_IDS = ["contract", "recall-floor"]


def refused(code, function, *args, **kwargs):
    with pytest.raises(CredibilityError) as error:
        function(*args, **kwargs)
    assert str(error.value).split(":")[0] == code, str(error.value)


def identity_of(label):
    return document_sha256(checkpoint_identity(label))


def partner_ledger(*entries):
    return ledger(*(entries or (established("PD-A", "pda"), established("PD-B", "pdb"))), capability="plate-detector")


def partners():
    return [{"candidateId": "PD-A", "identitySha256": identity_of("pda")},
            {"candidateId": "PD-B", "identitySha256": identity_of("pdb")}]


def stage1(**changes):
    rule = {"compositionId": GATE, "partnerEventId": PARTNER_EVENT, "eligiblePartners": partners(),
            "excludedPartners": [], "partnerRankingRuleSha256": sha("rule"), "layerAGatesSha256": sha("gates"),
            "layerAGateIds": list(GATE_IDS), "derivationRule": bs.DERIVATION_RULE, "gateScope": bs.GATE_SCOPE_ALL}
    rule.update(changes)
    return rule


def block():
    return {
        "purpose": "recogniser of the single gate-only baseline composition",
        "protocolSection": "protocol section 2.4",
        "configurationSha256": sha("bob-configuration"),
        "adapterSha256": sha("bob-adapter"),
        "hostManifests": {"dev-profile": [
            {"path": "bin/tool.exe", "kind": "executable", "sha256": sha("exe"), "size": 10},
            {"path": "lib/core.dll", "kind": "runtime-library", "sha256": sha("dll"), "size": 20},
            {"path": "share/model.bin", "kind": "data", "sha256": sha("weights-bob"), "size": 30}]},
        "evaluationPermissions": [
            {"artefactKind": "executable", "sha256s": [sha("exe")], "decidedBy": "synthetic-owner",
             "decidedOn": RECORDED, "primarySourceSha256": sha("terms-page")},
            {"artefactKind": "model-data", "sha256s": [sha("weights-bob")], "decidedBy": "synthetic-owner",
             "decidedOn": RECORDED, "primarySourceSha256": sha("data-terms")},
            {"artefactKind": "runtime-libraries", "sha256s": [sha("dll")], "decidedBy": "synthetic-owner",
             "decidedOn": RECORDED, "primarySourceSha256": sha("library-terms")},
        ],
        "compositions": [stage1()],
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


def plain_ledger():
    """The same event without its benchmark-only baseline."""
    return m3_ledger(baseline(), established(), emerging())


def layer_a(document, partner, *, ranks=None, gates=None, **changes):
    ranks = ranks or {"PD-A": [False, -0.9, "PD-A"], "PD-B": [False, -0.8, "PD-B"]}
    gates = gates or {"PD-A": {g: "passed" for g in GATE_IDS}, "PD-B": {g: "passed" for g in GATE_IDS}}
    rows = [{"candidateId": p["candidateId"], "identitySha256": p["identitySha256"], "gates": gates[p["candidateId"]],
             "rankKey": ranks[p["candidateId"]], "measurementSha256": sha(f"layer-a-{p['candidateId']}")}
            for p in partners()]
    result = bs.layer_a_result_document(document, GATE, partner, rows, sha("raw-layer-a"))
    result.update(changes)
    return result


def evidence(document, partner=None, result=None, seal=None):
    partner = partner_ledger() if partner is None else partner
    result = layer_a(document, partner) if result is None else result
    if seal is None:
        seal = bs.derive_baseline_seal(document, GATE, protocol_sha256=PROTOCOL, partner_ledger=partner,
                                       layer_a=result, recorded_at=SEALED_AT, recorded_by="synthetic-harness")
    return {GATE: {"seal": seal, "layerA": result, "partnerLedger": partner}}


def component(event_id, candidate_id, identity):
    return {"eventId": event_id, "candidateId": candidate_id, "identitySha256": identity}


def composition(document, composition_id, partner_id, candidate_id, gates, score, seal_sha):
    own = {e["candidateId"]: e for e in document["candidates"]}[candidate_id]
    return {"compositionId": composition_id,
            "components": [component(PARTNER_EVENT, partner_id, identity_of(partner_id.lower().replace("-", ""))),
                           component(EVENT, candidate_id, document_sha256(own["identity"]))],
            "gates": {GATE: gates}, "technicalGates": "passed" if score is not None else "failed",
            "comparativeScore": score, "dResultSha256": sha(f"d-{composition_id}"),
            "baselineSealSha256s": {GATE: seal_sha}}


def bob_row(document, seal_sha):
    entry = next(e for e in document["candidates"] if e["candidateId"] == "VC-BOB")
    row = evaluated_row(entry, score=0.0)
    row.update(technicalGates="n/a", comparativeScore=None, taskQualityScore=None,
               hostManifestSha256s={p: document_sha256(m) for p, m in entry["benchmarkBaseline"]["hostManifests"].items()},
               baselineSealSha256s={GATE: seal_sha})
    return row


def m3_block(document, proof, **changes):
    seal = proof[GATE]["seal"]
    digest = document_sha256(seal)
    resolved = seal["status"] == bs.RESOLVED
    result = {
        "baselineSeals": [{"compositionId": GATE, "sealSha256": digest, "status": seal["status"],
                           "sealCommit": "c" * 40}],
        "dExecutionStartedAt": D_STARTED if resolved else seal.get("protectedDAccessedAt"),
        "incumbent": None,
        "topK": ["VC-EMG", "VC-EST"],
        "componentFinalists": ["VC-EST"],
        "compositionCandidates": [
            composition(document, "C-B-EMG", "PD-B", "VC-EMG", "passed", 0.9, digest),
            composition(document, "C-A-EST", "PD-A", "VC-EST", "passed", 0.7, digest),
            composition(document, "C-A-B0", "PD-A", "VC-B0", "failed", None, digest),
        ] if resolved else [],
        "rankedCompositions": ["C-B-EMG", "C-A-EST"] if resolved else [],
        "frontier": ["C-B-EMG"] if resolved else [],
        "strongestEvaluatedComposition": "C-B-EMG" if resolved else None,
    }
    result.update(changes)
    return result


def m3_decision(document, proof=None, **kwargs):
    proof = evidence(document) if proof is None else proof
    summary = decision(document, **kwargs)
    summary["evaluated"].append(bob_row(document, document_sha256(proof[GATE]["seal"])))
    summary["benchmarkOnlyBaselines"] = m3_block(document, proof)
    return summary


def check(summary, document, proof):
    validate_decision(summary, document, document, baseline_evidence=proof)


# ------------------------------------------------------------------ positive


def test_benchmark_baseline_is_accepted_measured_sealed_and_never_ranked():
    document = m3_ledger()
    summary = validate_ledger(document)
    assert summary["VC-BOB"] == {"class": "reference-only", "provenanceConfidence": "High",
                                 "disposition": "BENCHMARK_BASELINE"}
    proof = evidence(document)
    seal = proof[GATE]["seal"]
    assert seal["status"] == "RESOLVED" and seal["partnerCandidateId"] == "PD-A"
    assert bs.verify_baseline_seal(seal, frozen=document, protocol_sha256=PROTOCOL,
                                   partner_ledger=proof[GATE]["partnerLedger"],
                                   layer_a=proof[GATE]["layerA"]) == document_sha256(seal)
    check(m3_decision(document, proof), document, proof)


def test_seal_carries_every_machine_enforced_field():
    """P2-1: every identity the enforcement depends on is a seal field, not prose."""
    document = m3_ledger()
    proof = evidence(document)
    seal = proof[GATE]["seal"]
    assert set(seal) == set(bs.RESOLVED_FIELDS)
    bob_entry = document["candidates"][-1]
    rule = bob_entry["benchmarkBaseline"]["compositions"][0]
    assert seal["benchmarkComponentIdentitySha256"] == bs.benchmark_component_identity_sha256(bob_entry)
    assert seal["layerAGatesSha256"] == rule["layerAGatesSha256"]
    assert seal["partnerRankingRuleSha256"] == rule["partnerRankingRuleSha256"]
    assert seal["stage1RuleSha256"] == document_sha256(rule)
    assert seal["eligibleUniverseSha256"] == document_sha256(rule["eligiblePartners"])
    assert seal["partnerFrozenLedgerSha256"] == document_sha256(proof[GATE]["partnerLedger"])
    assert seal["layerAResultSha256"] == document_sha256(proof[GATE]["layerA"])
    assert seal["frozenLedgerSha256"] == document_sha256(document)
    assert seal["protocolSha256"] == PROTOCOL
    assert seal["gateScope"] == "all-ordinary-compositions"
    assert seal["protectedDState"] == "NOT_STARTED"
    assert seal["compositionSha256"] == bs.composition_sha256(EVENT, GATE, "VC-BOB",
                                                             seal["benchmarkComponentIdentitySha256"],
                                                             PARTNER_EVENT, "PD-A", identity_of("pda"))
    for field in bs.RESOLVED_FIELDS:
        if field in ("recordedAt", "recordedBy"):
            continue
        broken = copy.deepcopy(seal)
        del broken[field]
        with pytest.raises(CredibilityError):
            bs.verify_baseline_seal(broken, frozen=document, protocol_sha256=PROTOCOL,
                                    partner_ledger=proof[GATE]["partnerLedger"], layer_a=proof[GATE]["layerA"])
    self_hashed = dict(seal, recordSha256=document_sha256(seal))
    refused("unknown_field", bs.verify_baseline_seal, self_hashed, frozen=document, protocol_sha256=PROTOCOL,
            partner_ledger=proof[GATE]["partnerLedger"], layer_a=proof[GATE]["layerA"])


def test_bob_scoring_highest_cannot_be_named_anywhere():
    document = m3_ledger()
    proof = evidence(document)
    summary = m3_decision(document, proof)
    for gates, score, quality in (("passed", 9.9, 9.9), ("n/a", 9.9, None), ("n/a", None, 9.9), ("failed", None, 0.0)):
        changed = copy.deepcopy(summary)
        changed["evaluated"][-1].update(technicalGates=gates, comparativeScore=score, taskQualityScore=quality)
        refused("benchmark_baseline_row_scored", check, changed, document, proof)
    for field in ("highestTaskQualityEvaluated", "strongestEvaluatedTechnical"):
        changed = copy.deepcopy(summary)
        changed[field] = "VC-BOB"
        refused("benchmark_baseline_in_derived_output", check, changed, document, proof)
    changed = copy.deepcopy(summary)
    changed["strongestReported"]["candidateId"] = "VC-BOB"
    refused("benchmark_baseline_in_derived_output", check, changed, document, proof)
    changed = copy.deepcopy(summary)
    changed["strongestClearedPerProfile"]["dev-profile"] = "VC-BOB"
    refused("benchmark_baseline_in_derived_output", check, changed, document, proof)
    changed = copy.deepcopy(summary)
    changed["implementation"]["components"] = ["VC-BOB"]
    refused("benchmark_baseline_in_derived_output", check, changed, document, proof)
    changed = copy.deepcopy(summary)
    changed["licence"]["VC-BOB"] = {"dev-profile": "CLEARED"}
    refused("unknown_field", check, changed, document, proof)


def test_bob_must_be_evaluated_on_its_pinned_bytes_and_host_manifests():
    document = m3_ledger()
    proof = evidence(document)
    summary = m3_decision(document, proof)
    changed = copy.deepcopy(summary)
    changed["evaluated"].pop()
    refused("evaluated_set_differs_from_shortlist", check, changed, document, proof)
    changed = copy.deepcopy(summary)
    changed["evaluated"][-1]["hostManifestSha256s"]["dev-profile"] = sha("other bytes")
    refused("benchmark_baseline_host_manifest_mismatch", check, changed, document, proof)
    changed = copy.deepcopy(summary)
    del changed["evaluated"][-1]["hostManifestSha256s"]["dev-profile"]
    refused("benchmark_baseline_host_manifest_mismatch", check, changed, document, proof)
    changed = copy.deepcopy(summary)
    changed["evaluated"][-1]["artefactSha256s"] = [sha("re-pinned weights")]
    refused("evaluated_artefact_differs_from_ledger", check, changed, document, proof)
    changed = copy.deepcopy(summary)
    changed["evaluated"][0]["hostManifestSha256s"] = {}
    refused("host_manifests_only_for_benchmark_baseline", check, changed, document, proof)
    changed = copy.deepcopy(summary)
    changed["evaluated"][-1]["baselineSealSha256s"] = {GATE: sha("another seal")}
    refused("benchmark_baseline_row_seal_mismatch", check, changed, document, proof)
    changed = copy.deepcopy(summary)
    del changed["evaluated"][-1]["baselineSealSha256s"]
    refused("benchmark_baseline_row_seal_mismatch", check, changed, document, proof)


def test_host_manifest_profiles_reconcile_exactly_with_target_profiles():
    """Review P3: the pinned host manifests are exactly the decision's declared target profiles."""
    document = m3_ledger()
    proof = evidence(document)
    summary = m3_decision(document, proof)
    for profiles in (["other-profile"], ["dev-profile", "prod-profile"]):
        changed = copy.deepcopy(summary)
        changed["targetProfiles"] = profiles
        changed["licence"] = {c: {p: "CLEARED" for p in profiles} for c in changed["licence"]}
        changed["strongestClearedPerProfile"] = {p: "VC-EMG" for p in profiles}
        refused("benchmark_baseline_host_profiles_differ_from_target_profiles", check, changed, document, proof)


# ------------------------------------------------------------------ class restriction, pinning, permissions


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


def test_bob_requires_high_provenance_manifests_and_stage1_rule():
    unpinned = bob()
    unpinned["identity"]["files"][0]["sha256"] = "UNKNOWN"
    refused("benchmark_baseline_requires_pinned_provenance", validate_ledger, m3_ledger(unpinned))
    third_party = bob(entry=reference())
    refused("benchmark_baseline_requires_pinned_provenance", validate_ledger, m3_ledger(third_party))
    for mutate, code in (
        (lambda b: b.pop("hostManifests"), "missing_field"),
        (lambda b: b.update(hostManifests={}), "benchmark_baseline_host_manifest_required"),
        (lambda b: b["hostManifests"].update({"dev-linux-cpu": []}), "benchmark_baseline_host_manifest_required"),
        (lambda b: b["hostManifests"]["dev-profile"].reverse(), "benchmark_baseline_manifest_not_sorted_unique"),
        (lambda b: b["hostManifests"]["dev-profile"][0].update(sha256="UNKNOWN"), "malformed"),
        (lambda b: b["hostManifests"]["dev-profile"][0].update(size=0), "number_required"),
        (lambda b: b.update(configurationSha256="UNKNOWN"), "malformed"),
        (lambda b: b.pop("adapterSha256"), "missing_field"),
        (lambda b: b["compositions"][0]["eligiblePartners"].reverse(), "eligible_partners_not_sorted_unique"),
        (lambda b: b["compositions"][0]["eligiblePartners"].append(
            {"candidateId": "VC-BOB", "identitySha256": sha("x")}), "benchmark_baseline_cannot_be_its_own_partner"),
        (lambda b: b["compositions"].append(copy.deepcopy(b["compositions"][0])), "duplicate_composition_id"),
        (lambda b: b["compositions"][0].update(derivationRule="the owner picks a good detector"), "value_not_allowed"),
        (lambda b: b["compositions"][0].update(gateScope="whatever the protocol says"), "value_not_allowed"),
        (lambda b: b["compositions"][0].update(layerAGateIds=[]), "layer_a_gates_not_sorted_unique"),
        (lambda b: b["compositions"][0].update(layerAGateIds=["z", "a"]), "layer_a_gates_not_sorted_unique"),
        (lambda b: b["compositions"][0].pop("gateScope"), "missing_field"),
        (lambda b: b["compositions"][0].update(partnerEventId="msr-x"), "malformed"),
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


def test_evaluation_permission_is_bound_per_exact_artefact():
    """Review P3: one vague permission for "all" is refused; executable, libraries and model data are bound."""
    vague = [{"artefact": "all", "decidedBy": "x", "decidedOn": RECORDED, "primarySourceSha256": sha("p")}]
    for mutate, code in (
        (lambda b: b.update(evaluationPermissions=vague), "missing_field"),
        (lambda b: b.update(evaluationPermissions=[]), "benchmark_baseline_permission_required"),
        (lambda b: b["evaluationPermissions"].pop(1), "benchmark_baseline_permission_required"),
        (lambda b: b["evaluationPermissions"].pop(0), "benchmark_baseline_permission_required"),
        (lambda b: b["evaluationPermissions"].pop(2), "benchmark_baseline_permission_required"),
        # cold review P3-6: a data file cannot be filed under the executable permission, nor retyped in the manifest
        (lambda b: b["evaluationPermissions"][0].update(sha256s=sorted([sha("exe"), sha("weights-bob")])),
         "benchmark_baseline_permission_not_bound"),
        (lambda b: b["hostManifests"]["dev-profile"][2].update(kind="executable"), "benchmark_baseline_permission_not_bound"),
        (lambda b: b["hostManifests"]["dev-profile"][2].update(kind="script"), "value_not_allowed"),
        (lambda b: b["hostManifests"]["dev-profile"][2].pop("kind"), "missing_field"),
        (lambda b: b["evaluationPermissions"].append(copy.deepcopy(b["evaluationPermissions"][0])),
         "benchmark_baseline_permission_kind_duplicate"),
        (lambda b: b["evaluationPermissions"][0].update(sha256s=sorted([sha("exe"), sha("dll")])) or
         b["evaluationPermissions"][2].update(sha256s=[sha("dll")]), "benchmark_baseline_permission_not_bound"),
        (lambda b: b["evaluationPermissions"][1].update(sha256s=[sha("other data")]),
         "benchmark_baseline_permission_not_bound"),
        (lambda b: b["evaluationPermissions"][0].update(sha256s=[]), "benchmark_baseline_permission_not_sorted_unique"),
        (lambda b: b["evaluationPermissions"][0].update(artefactKind="everything"), "value_not_allowed"),
        (lambda b: b["hostManifests"]["dev-profile"].insert(0, {"path": "a/unpermitted.dll", "kind": "runtime-library", "sha256": sha("new"),
                                                                 "size": 1}), "benchmark_baseline_permission_not_bound"),
    ):
        entry = bob()
        mutate(entry["benchmarkBaseline"])
        refused(code, validate_ledger, m3_ledger(entry))


def test_same_event_partner_universe_must_be_the_shortlisted_identities():
    """Review P2-2: a non-shortlisted or wrongly identified partner of the same event is refused."""
    for partner, code in (
        ({"candidateId": "VC-EST", "identitySha256": sha("not its identity")}, "baseline_partner_not_in_partner_shortlist"),
        ({"candidateId": "VC-REF", "identitySha256": identity_of("ref")}, "baseline_partner_not_in_partner_shortlist"),
        ({"candidateId": "VC-ZZZ", "identitySha256": sha("z")}, "baseline_partner_not_in_partner_shortlist"),
    ):
        entry = bob()
        entry["benchmarkBaseline"]["compositions"][0].update(partnerEventId=EVENT, eligiblePartners=[partner])
        refused(code, validate_ledger, m3_ledger(baseline(), established(), reference(), entry))
    b0 = {"candidateId": "VC-B0", "identitySha256": document_sha256({"repository": "MAVI", "revision": "UNKNOWN"}),
          "reason": "the deterministic baseline is not a detector"}
    entry = bob()
    entry["benchmarkBaseline"]["compositions"][0].update(
        partnerEventId=EVENT, eligiblePartners=[{"candidateId": "VC-EST", "identitySha256": identity_of("est")}],
        excludedPartners=[b0])
    validate_ledger(m3_ledger(baseline(), established(), entry))
    # cold review P3-4: a silent subset of the shortlist is refused; the exclusion needs a recorded reason
    entry["benchmarkBaseline"]["compositions"][0]["excludedPartners"] = []
    refused("baseline_partner_universe_not_the_shortlist", validate_ledger, m3_ledger(baseline(), established(), entry))
    entry["benchmarkBaseline"]["compositions"][0]["excludedPartners"] = [dict(b0, reason=" ")]
    refused("text_required", validate_ledger, m3_ledger(baseline(), established(), entry))


# ------------------------------------------------------------------ immutability after freeze


def test_bob_set_identity_and_composition_rule_are_fixed_after_freeze():
    frozen = m3_ledger()
    for mutate in (
        lambda e: e["benchmarkBaseline"]["hostManifests"]["dev-profile"][0].update(sha256=sha("swapped")) or
        e["benchmarkBaseline"]["evaluationPermissions"][0].update(sha256s=[sha("swapped")]),
        lambda e: e["benchmarkBaseline"].update(configurationSha256=sha("other configuration")),
        lambda e: e["benchmarkBaseline"].update(adapterSha256=sha("other adapter")),
        lambda e: e["benchmarkBaseline"]["compositions"][0]["eligiblePartners"].append(
            {"candidateId": "PD-C", "identitySha256": sha("PD-C")}),
        lambda e: e["benchmarkBaseline"]["compositions"][0].update(partnerRankingRuleSha256=sha("new rule")),
        lambda e: e["benchmarkBaseline"]["compositions"][0].update(layerAGateIds=["contract"]),
        lambda e: e["benchmarkBaseline"]["evaluationPermissions"][0].update(decidedBy="someone else"),
        lambda e: e["disposition"].update(reason="changed after freeze"),
    ):
        later = copy.deepcopy(frozen)
        mutate(later["candidates"][-1])
        refused("frozen_benchmark_baseline_field_changed", validate_evolution, frozen, later)
    removed = copy.deepcopy(frozen)
    removed["candidates"][-1]["disposition"] = {"status": "REFERENCE_ONLY", "reasonClass": "credibility",
                                                "reason": "held", "revisitTrigger": "never", "decidedBy": "x"}
    del removed["candidates"][-1]["benchmarkBaseline"]
    refused("benchmark_baselines_changed_after_freeze", validate_evolution, frozen, removed)
    refused("benchmark_baselines_changed_after_freeze", validate_evolution, plain_ledger(), frozen)


def test_bob_cannot_promote_itself():
    document = m3_ledger()
    promoted = copy.deepcopy(document)
    promoted["candidates"][-1]["evidence"].append(
        {"evidenceId": "E-MAVI", "type": "independent-benchmark", "producer": {"group": "mavi-bakeoff",
         "relation": "independent"}, "source": "evidence-store:plates/run", "locator": "D", "retrievedOn": RECORDED,
         "retrievedSha256": sha("run"), "recordedAt": RECORDED, "summary": "MAVI bake-off D-score",
         "scope": "method", "independenceBasis": "MAVI", "subTask": "T-VC", "objectClass": "vehicle"})
    refused("mavi_evidence_in_ledger", validate_ledger, promoted)
    established_bob = bob(entry=established("VC-BOB", "bob"))
    refused("benchmark_baseline_class", validate_ledger, m3_ledger(established_bob))


# ------------------------------------------------------------------ P1-2: the committed pre-D seal


def test_reseal_to_another_partner_with_a_recomputed_hash_is_refused():
    """The reviewer's attack: seal PD-A, bind D to it, then reseal to PD-B and recompute the seal's own hash."""
    document = m3_ledger()
    proof = evidence(document)
    summary = m3_decision(document, proof)
    check(summary, document, proof)
    swapped = dict(proof[GATE]["seal"], partnerCandidateId="PD-B", partnerIdentitySha256=identity_of("pdb"))
    swapped["compositionSha256"] = bs.composition_sha256(EVENT, GATE, "VC-BOB", swapped["benchmarkComponentIdentitySha256"],
                                                         PARTNER_EVENT, "PD-B", identity_of("pdb"))
    attack = {GATE: dict(proof[GATE], seal=swapped)}
    # 1. the swapped seal is not what the frozen rule derives from the committed Layer-A result
    refused("baseline_seal_partner_not_derived", check, summary, document, attack)
    # 2. the decision is re-pointed at the new seal hash as well: still not derivable
    rebound = copy.deepcopy(summary)
    digest = document_sha256(swapped)
    rebound["benchmarkOnlyBaselines"] = m3_block(document, attack)
    rebound["evaluated"][-1]["baselineSealSha256s"] = {GATE: digest}
    refused("baseline_seal_partner_not_derived", check, rebound, document, attack)
    # 3. the Layer-A result is forged too so that PD-B derives: the D results and the BOB row still carry PD-A's seal
    forged = layer_a(document, proof[GATE]["partnerLedger"], ranks={"PD-A": [False, -0.5, "PD-A"],
                                                                    "PD-B": [False, -0.8, "PD-B"]})
    resealed = evidence(document, partner=proof[GATE]["partnerLedger"], result=forged)
    assert resealed[GATE]["seal"]["partnerCandidateId"] == "PD-B"
    refused("decision_baseline_seal_mismatch", check, summary, document, resealed)
    half = copy.deepcopy(summary)
    half["benchmarkOnlyBaselines"]["baselineSeals"][0]["sealSha256"] = document_sha256(resealed[GATE]["seal"])
    refused("benchmark_baseline_row_seal_mismatch", check, half, document, resealed)
    half["evaluated"][-1]["baselineSealSha256s"] = {GATE: document_sha256(resealed[GATE]["seal"])}
    refused("d_result_baseline_seal_mismatch", check, half, document, resealed)


def test_layer_a_result_hash_is_bound():
    document = m3_ledger()
    proof = evidence(document)
    arbitrary = dict(proof[GATE]["seal"], layerAResultSha256=sha("anything at all"))
    refused("baseline_seal_differs_from_frozen_inputs", bs.verify_baseline_seal, arbitrary, frozen=document,
            protocol_sha256=PROTOCOL, partner_ledger=proof[GATE]["partnerLedger"], layer_a=proof[GATE]["layerA"])
    for field, value in (("protocolSha256", sha("other protocol")), ("frozenLedgerSha256", sha("x")),
                         ("benchmarkComponentIdentitySha256", sha("x")), ("stage1RuleSha256", sha("x")),
                         ("eligibleUniverseSha256", sha("x")), ("layerAGatesSha256", sha("x")),
                         ("partnerRankingRuleSha256", sha("x")), ("partnerFrozenLedgerSha256", sha("x")),
                         ("compositionSha256", sha("x")), ("partnerEventId", "msr-plate-detector-2026-02")):
        changed = dict(proof[GATE]["seal"], **{field: value})
        refused("baseline_seal_differs_from_frozen_inputs", bs.verify_baseline_seal, changed, frozen=document,
                protocol_sha256=PROTOCOL, partner_ledger=proof[GATE]["partnerLedger"], layer_a=proof[GATE]["layerA"])
    for field, value, code in (("protectedDState", "ACCESSED", "baseline_seal_d_state_contradicted"),
                               ("recordedAt", "2026-06-09T23:59:59Z", "baseline_resolved_before_freeze"),
                               ("recordedAt", "2026-07-01 10:00:00", "instant_malformed"),
                               ("compositionId", "GATE-OTHER", "gate_only_composition_not_frozen"),
                               ("schema", "mavi-model-selection-baseline-seal-v0", "schema_unsupported")):
        changed = dict(proof[GATE]["seal"], **{field: value})
        refused(code, bs.verify_baseline_seal, changed, frozen=document, protocol_sha256=PROTOCOL,
                partner_ledger=proof[GATE]["partnerLedger"], layer_a=proof[GATE]["layerA"])


def test_partner_event_must_exist_and_reconcile():
    """Review P2-2: the partner event exists, and the frozen universe is its shortlist with the same identities."""
    document = m3_ledger()
    proof = evidence(document)
    seal = proof[GATE]["seal"]
    refused("baseline_seal_not_derivable", bs.verify_baseline_seal, seal, frozen=document, protocol_sha256=PROTOCOL,
            partner_ledger=None, layer_a=proof[GATE]["layerA"])
    unshortlisted = partner_ledger(established("PD-A", "pda"), reference("PD-B", "pdb"))
    refused("baseline_partner_not_in_partner_shortlist", check, m3_decision(document, proof), document,
            {GATE: dict(proof[GATE], partnerLedger=unshortlisted)})
    other_event = ledger(established("PD-A", "pda"), established("PD-B", "pdb"), capability="plate-finder")
    refused("baseline_partner_event_mismatch", check, m3_decision(document, proof), document,
            {GATE: dict(proof[GATE], partnerLedger=other_event)})
    retrained = partner_ledger(established("PD-A", "pda-retrained"), established("PD-B", "pdb"))
    refused("baseline_partner_not_in_partner_shortlist", check, m3_decision(document, proof), document,
            {GATE: dict(proof[GATE], partnerLedger=retrained)})


@pytest.mark.parametrize("mutate, code", [
    (lambda r: r["results"][0].update(identitySha256=sha("PD-A retrained")), "layer_a_identity_mismatch"),
    (lambda r: r["results"][0].update(candidateId="PD-Z"), "layer_a_partner_outside_frozen_universe"),
    (lambda r: r["results"].pop(), "layer_a_result_inconsistent_with_frozen_universe"),
    (lambda r: r["results"].append(copy.deepcopy(r["results"][0])), "layer_a_result_inconsistent_with_frozen_universe"),
    (lambda r: r["results"][0]["gates"].pop("contract"), "layer_a_gates_mismatch"),
    (lambda r: r["results"][0]["gates"].update(extra="passed"), "layer_a_gates_mismatch"),
    (lambda r: r["results"][0]["gates"].update(contract="maybe"), "value_not_allowed"),
    (lambda r: r["results"][1].update(rankKey=[False, -0.9, "PD-A"]), "layer_a_rank_ambiguous"),
    (lambda r: r["results"][1].update(rankKey=[0, -0.8, "PD-B"]), "layer_a_rank_key_malformed"),
    (lambda r: r["results"][1].update(rankKey=[]), "layer_a_rank_key_malformed"),
    (lambda r: r["results"][1].update(rankKey=[None]), "layer_a_rank_key_malformed"),
    (lambda r: r.update(partnerRankingRuleSha256=sha("another rule")), "baseline_ranking_rule_mismatch"),
    (lambda r: r.update(layerAGatesSha256=sha("other gates")), "layer_a_gates_mismatch"),
    (lambda r: r.update(compositionId="GATE-OTHER"), "layer_a_result_not_for_this_composition"),
    (lambda r: r.update(partnerFrozenLedgerSha256=sha("x")), "baseline_partner_event_mismatch"),
])
def test_layer_a_result_must_reconcile_with_the_frozen_rule(mutate, code):
    document = m3_ledger()
    partner = partner_ledger()
    result = layer_a(document, partner)
    mutate(result)
    refused(code, bs.check_layer_a_result, result, document, GATE, partner)


def test_derivation_is_the_highest_ranked_partner_passing_every_gate():
    document = m3_ledger()
    partner = partner_ledger()
    gates = {"PD-A": {"contract": "passed", "recall-floor": "failed"}, "PD-B": {g: "passed" for g in GATE_IDS}}
    result = layer_a(document, partner, gates=gates)
    proof = evidence(document, partner=partner, result=result)
    assert proof[GATE]["seal"]["partnerCandidateId"] == "PD-B"
    wrong = dict(proof[GATE]["seal"], partnerCandidateId="PD-A", partnerIdentitySha256=identity_of("pda"))
    refused("baseline_seal_partner_not_derived", bs.verify_baseline_seal, wrong, frozen=document,
            protocol_sha256=PROTOCOL, partner_ledger=partner, layer_a=result)


# ------------------------------------------------------------------ P2-5: STOPPED baseline resolution


def stopped_evidence(document):
    partner = partner_ledger()
    gates = {p: {g: "failed" for g in GATE_IDS} for p in ("PD-A", "PD-B")}
    return evidence(document, partner=partner, result=layer_a(document, partner, gates=gates))


def test_no_passing_partner_produces_an_immutable_stopped_record():
    document = m3_ledger()
    proof = stopped_evidence(document)
    seal = proof[GATE]["seal"]
    assert seal["status"] == "STOPPED" and seal["stopReason"] == "no-partner-passed-layer-a"
    assert set(seal) == set(bs.STOPPED_FIELDS)
    assert "partnerCandidateId" not in seal and "compositionSha256" not in seal
    bs.verify_baseline_seal(seal, frozen=document, protocol_sha256=PROTOCOL,
                            partner_ledger=proof[GATE]["partnerLedger"], layer_a=proof[GATE]["layerA"])
    # a STOPPED record cannot name a replacement baseline
    named = dict(seal, partnerCandidateId="PD-A")
    refused("unknown_field", bs.verify_baseline_seal, named, frozen=document, protocol_sha256=PROTOCOL,
            partner_ledger=proof[GATE]["partnerLedger"], layer_a=proof[GATE]["layerA"])
    # its stop reason must not contradict the inputs
    resolvable = evidence(document)
    fake = dict(seal, layerAResultSha256=document_sha256(resolvable[GATE]["layerA"]))
    refused("baseline_stop_reason_contradicted", bs.verify_baseline_seal, fake, frozen=document,
            protocol_sha256=PROTOCOL, partner_ledger=resolvable[GATE]["partnerLedger"],
            layer_a=resolvable[GATE]["layerA"])
    refused("baseline_stop_evidence_required", bs.verify_baseline_seal, dict(seal, stopEvidenceSha256s=[]),
            frozen=document, protocol_sha256=PROTOCOL, partner_ledger=proof[GATE]["partnerLedger"],
            layer_a=proof[GATE]["layerA"])
    refused("value_not_allowed", bs.verify_baseline_seal, dict(seal, stopReason="owner preferred another"),
            frozen=document, protocol_sha256=PROTOCOL, partner_ledger=proof[GATE]["partnerLedger"],
            layer_a=proof[GATE]["layerA"])


@pytest.mark.parametrize("partner, result, accessed, reason", [
    (None, "default", 0, "partner-event-missing"),
    ("unshortlisted", "default", 0, "partner-universe-inconsistent"),
    ("default", None, 0, "prerequisite-failed"),
    ("default", "tie", 0, "resolution-ambiguous"),
    ("default", "identity", 0, "identity-mismatch"),
    ("default", "default", 3, "protected-d-accessed"),
])
def test_every_failed_prerequisite_stops_without_a_baseline(partner, result, accessed, reason):
    document = m3_ledger()
    good = partner_ledger()
    partner_doc = {None: None, "default": good,
                   "unshortlisted": partner_ledger(established("PD-A", "pda"), reference("PD-B", "pdb"))}[partner]
    result_doc = None if result is None else layer_a(document, good)
    if result == "tie":
        result_doc["results"][1]["rankKey"] = list(result_doc["results"][0]["rankKey"])
    if result == "identity":
        result_doc["results"][0]["identitySha256"] = sha("PD-A retrained")
    seal = bs.derive_baseline_seal(document, GATE, protocol_sha256=PROTOCOL, partner_ledger=partner_doc,
                                   layer_a=result_doc, recorded_at=SEALED_AT, recorded_by="synthetic-harness",
                                   protected_d_rows_read=accessed,
                                   protected_d_accessed_at="2026-07-01T09:00:00Z" if accessed else None)
    assert seal["status"] == "STOPPED" and seal["stopReason"] == reason
    assert seal["protectedDState"] == ("ACCESSED" if accessed else "NOT_STARTED")
    bs.verify_baseline_seal(seal, frozen=document, protocol_sha256=PROTOCOL, partner_ledger=partner_doc,
                            layer_a=result_doc)


def test_stopped_event_holds_no_decision_summary_at_all():
    """Convergence review P1-A (owner, strict): a STOPPED all-gating baseline refuses every decision summary, before
    any M1 rule runs. No outcome is fabricated: the event stays PLANNED for owner action."""
    document = m3_ledger()
    proof = stopped_evidence(document)
    for state in ("TECHNICAL_DECISION_RECORDED", "QUALIFICATION_PENDING", "CLOSED"):
        for implementation in (None, ("VC-EST",), ("VC-B0",)):
            summary = m3_decision(document, proof, state=state, implementation=implementation)
            for outcome in ((None,) if state != "CLOSED" else
                            ("INCUMBENT_RETAINED", "NO_QUALIFIABLE_CANDIDATE", "BASELINE_SELECTED",
                             "SELECTED_FOR_PACKAGING")):
                summary["outcome"] = outcome
                refused("baseline_stopped_decision_refused", check, summary, document, proof)

# ------------------------------------------------------------------ P2-4: outcome invariance


def _ordinary_variants():
    """Ordinary M1 decisions (some valid, some not) over the event without its benchmark-only baseline."""
    def closed(outcome, implementation, failed=()):
        def build(document):
            summary = decision(document, state="CLOSED", implementation=implementation)
            for row in summary["evaluated"]:
                if row["candidateId"] in failed:
                    row.update(technicalGates="failed", comparativeScore=None)
            passing = {r["candidateId"]: r["comparativeScore"] for r in summary["evaluated"]
                       if r["technicalGates"] == "passed"}
            best = max(passing, key=passing.get) if passing else None
            summary.update(strongestEvaluatedTechnical=best, strongestClearedPerProfile={"dev-profile": best},
                           outcome=outcome)
            return summary
        return build
    every = ("VC-B0", "VC-EST", "VC-EMG")
    return {
        "selected": closed("SELECTED_FOR_PACKAGING", ("VC-EST",)),
        "incumbent-retained-some-pass": closed("INCUMBENT_RETAINED", None),
        "incumbent-retained-all-failed": closed("INCUMBENT_RETAINED", None, failed=every),
        "nqc-all-failed": closed("NO_QUALIFIABLE_CANDIDATE", None, failed=every),
        "nqc-some-pass": closed("NO_QUALIFIABLE_CANDIDATE", None),
        "baseline-selected": closed("BASELINE_SELECTED", ("VC-B0",)),
        "baseline-selected-all-learned-failed": closed("BASELINE_SELECTED", ("VC-B0",), failed=("VC-EST", "VC-EMG")),
        "baseline-selected-without-baseline": closed("BASELINE_SELECTED", None, failed=every),
        "selected-without-implementation": closed("SELECTED_FOR_PACKAGING", None),
        "selected-baseline-only": closed("SELECTED_FOR_PACKAGING", ("VC-B0",)),
        "incumbent-with-implementation": closed("INCUMBENT_RETAINED", ("VC-EST",)),
        "emerging-implemented": closed("SELECTED_FOR_PACKAGING", ("VC-EMG",)),
        "failed-gate-implemented": closed("SELECTED_FOR_PACKAGING", ("VC-EST",), failed=("VC-EST",)),
    }


def _verdict(function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except CredibilityError as error:
        return str(error).split(":")[0]
    return "valid"


@pytest.mark.parametrize("name", sorted(_ordinary_variants()))
def test_adding_a_benchmark_only_baseline_never_changes_the_m1_outcome(name):
    build = _ordinary_variants()[name]
    plain = plain_ledger()
    without = _verdict(validate_decision, build(plain), plain, plain)
    for stopped in (False, True):
        document = m3_ledger()
        proof = stopped_evidence(document) if stopped else evidence(document)
        summary = build(document)
        summary["evaluated"].append(bob_row(document, document_sha256(proof[GATE]["seal"])))
        summary["benchmarkOnlyBaselines"] = m3_block(document, proof)
        # RESOLVED: the M1 verdict is unchanged. STOPPED (all-gating, the only scope): no decision beyond PLANNED.
        expected = "baseline_stopped_decision_refused" if stopped else without
        assert _verdict(check, summary, document, proof) == expected, (name, stopped)


def test_removing_the_benchmark_only_baseline_never_changes_the_m1_outcome():
    for name, build in sorted(_ordinary_variants().items()):
        document = m3_ledger()
        proof = evidence(document)
        summary = build(document)
        summary["evaluated"].append(bob_row(document, document_sha256(proof[GATE]["seal"])))
        summary["benchmarkOnlyBaselines"] = m3_block(document, proof)
        with_bob = _verdict(check, summary, document, proof)
        plain = plain_ledger()
        stripped = build(plain)
        assert _verdict(validate_decision, stripped, plain, plain) == with_bob, name


def test_known_valid_outcomes_stay_valid_with_a_bob():
    variants = _ordinary_variants()
    for name in ("selected", "incumbent-retained-all-failed", "incumbent-retained-some-pass", "baseline-selected",
                 "nqc-all-failed"):
        document = m3_ledger()
        proof = evidence(document)
        summary = variants[name](document)
        summary["evaluated"].append(bob_row(document, document_sha256(proof[GATE]["seal"])))
        summary["benchmarkOnlyBaselines"] = m3_block(document, proof)
        check(summary, document, proof)


# ------------------------------------------------------------------ P2-3: mandatory exclusion from ranking


def test_m3_block_is_mandatory_when_the_event_holds_a_bob():
    document = m3_ledger()
    proof = evidence(document)
    summary = m3_decision(document, proof)
    del summary["benchmarkOnlyBaselines"]
    refused("missing_field", check, summary, document, proof)
    for field in bs.M3_DECISION_KEYS:
        changed = m3_decision(document, proof)
        del changed["benchmarkOnlyBaselines"][field]
        refused("missing_field", check, changed, document, proof)
    refused("m3_decision_requires_baseline_evidence", validate_decision, m3_decision(document, proof), document,
            document)


@pytest.mark.parametrize("field", ["topK", "componentFinalists", "frontier", "rankedCompositions"])
@pytest.mark.parametrize("intruder", ["VC-BOB", GATE])
def test_bob_and_gate_only_composition_never_enter_a_ranked_set(field, intruder):
    document = m3_ledger()
    proof = evidence(document)
    summary = m3_decision(document, proof)
    summary["benchmarkOnlyBaselines"][field] = summary["benchmarkOnlyBaselines"][field] + [intruder]
    refused("benchmark_baseline_in_ranked_set", check, summary, document, proof)


@pytest.mark.parametrize("field", ["incumbent", "strongestEvaluatedComposition"])
@pytest.mark.parametrize("intruder", ["VC-BOB", GATE])
def test_bob_and_gate_only_composition_are_never_incumbent_or_winner(field, intruder):
    document = m3_ledger()
    proof = evidence(document)
    summary = m3_decision(document, proof)
    summary["benchmarkOnlyBaselines"][field] = intruder
    refused("benchmark_baseline_in_derived_output", check, summary, document, proof)


def test_bob_never_enters_an_ordinary_composition_candidate():
    document = m3_ledger()
    proof = evidence(document)
    digest = document_sha256(proof[GATE]["seal"])
    bob_identity = document_sha256(document["candidates"][-1]["identity"])
    cases = []
    as_component = composition(document, "C-A-EST", "PD-A", "VC-EST", "passed", 0.7, digest)
    as_component["components"][1] = component(EVENT, "VC-BOB", bob_identity)
    cases.append(as_component)
    disguised = composition(document, "C-A-EST", "PD-A", "VC-EST", "passed", 0.7, digest)
    disguised["components"][1]["identitySha256"] = bob_identity
    cases.append(disguised)
    named = composition(document, GATE, "PD-A", "VC-EST", "passed", 0.7, digest)
    cases.append(named)
    for intruder in cases:
        summary = m3_decision(document, proof)
        summary["benchmarkOnlyBaselines"]["compositionCandidates"][1] = intruder
        refused("benchmark_baseline_in_composition_candidate", check, summary, document, proof)


@pytest.mark.parametrize("mutate, code", [
    (lambda c: c["components"][0].update(candidateId="PD-Z"), "composition_component_not_in_partner_shortlist"),
    (lambda c: c["components"][0].update(identitySha256=sha("wrong")), "composition_component_identity_mismatch"),
    (lambda c: c["components"][0].update(eventId="msr-unrelated-2026-01"), "composition_component_event_not_declared"),
    (lambda c: c["components"][1].update(candidateId="VC-REF"), "composition_component_not_evaluated"),
    (lambda c: c["components"].pop(), "composition_components_invalid"),
    (lambda c: c["components"].reverse(), "composition_components_invalid"),
    (lambda c: c.update(gates={}), "composition_hard_gate_mapping_invalid"),
    (lambda c: c.update(gates={"GATE-OTHER": "passed"}), "composition_hard_gate_mapping_invalid"),
    (lambda c: c["gates"].update({GATE: "failed"}), "composition_failed_hard_gate_ranked"),
    (lambda c: c.update(baselineSealSha256s={GATE: sha("another seal")}), "d_result_baseline_seal_mismatch"),
    (lambda c: c.update(baselineSealSha256s={}), "d_result_baseline_seal_mismatch"),
    (lambda c: c.update(compositionId="VC-EST"), "composition_id_collides"),
    (lambda c: c.update(dResultSha256="UNKNOWN"), "malformed"),
])
def test_every_ordinary_composition_maps_to_the_single_sealed_baseline(mutate, code):
    document = m3_ledger()
    proof = evidence(document)
    summary = m3_decision(document, proof)
    mutate(summary["benchmarkOnlyBaselines"]["compositionCandidates"][1])
    refused(code, check, summary, document, proof)


def test_ranked_compositions_and_winner_are_derived():
    document = m3_ledger()
    proof = evidence(document)
    for field, value, code in (
        ("rankedCompositions", ["C-A-EST", "C-B-EMG"], "ranked_compositions_not_derived"),
        ("rankedCompositions", ["C-B-EMG"], "ranked_compositions_not_derived"),
        ("rankedCompositions", ["C-B-EMG", "C-A-EST", "C-A-B0"], "ranked_compositions_not_derived"),
        ("strongestEvaluatedComposition", "C-A-EST", "strongest_composition_not_derived"),
        ("strongestEvaluatedComposition", None, "strongest_composition_not_derived"),
        ("frontier", ["C-A-B0"], "frontier_member_not_passing"),
        ("topK", ["VC-REF"], "ranked_set_member_not_evaluated"),
        ("topK", ["VC-EST", "VC-EST"], "ranked_set_not_unique"),
        ("incumbent", "VC-REF", "incumbent_not_evaluated"),
    ):
        summary = m3_decision(document, proof)
        summary["benchmarkOnlyBaselines"][field] = value
        refused(code, check, summary, document, proof)
    summary = m3_decision(document, proof)
    summary["benchmarkOnlyBaselines"]["incumbent"] = "VC-EST"
    check(summary, document, proof)


def test_seal_and_d_start_are_consistent():
    """Review P3: one D start for the event, strictly after every seal and no later than the decision."""
    document = m3_ledger()
    proof = evidence(document)
    for value, code in ((SEALED_AT, "baseline_resolved_after_d_started"),
                        ("2026-06-30T10:00:00Z", "baseline_resolved_after_d_started"),
                        ("2026-09-02T00:00:00Z", "d_started_after_decision"),
                        (None, "instant_malformed")):
        summary = m3_decision(document, proof)
        summary["benchmarkOnlyBaselines"]["dExecutionStartedAt"] = value
        refused(code, check, summary, document, proof)
    for mutate, code in (
        (lambda s: s.update(sealSha256=sha("x")), "decision_baseline_seal_mismatch"),
        (lambda s: s.update(status="STOPPED"), "decision_baseline_seal_mismatch"),
        (lambda s: s.update(compositionId="GATE-OTHER"), "gate_only_composition_not_frozen"),
    ):
        summary = m3_decision(document, proof)
        mutate(summary["benchmarkOnlyBaselines"]["baselineSeals"][0])
        refused(code, check, summary, document, proof)
    summary = m3_decision(document, proof)
    summary["benchmarkOnlyBaselines"]["baselineSeals"] = []
    refused("gate_only_composition_unresolved", check, summary, document, proof)
    summary = m3_decision(document, proof)
    summary["benchmarkOnlyBaselines"]["baselineSeals"] *= 2
    refused("gate_only_composition_resolved_twice", check, summary, document, proof)
    unsealed = {GATE: dict(proof[GATE], seal=None)}
    refused("gate_only_composition_unresolved", check, m3_decision(document, proof), document, unsealed)


# ------------------------------------------------------------------ scope


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
    for field in ("benchmarkOnlyBaselines", "gateOnlyBaselineResolutions", "rankedSets"):
        with_field = copy.deepcopy(summary)
        with_field[field] = []
        refused("unknown_field", validate_decision, with_field, plain, plain)
    row = copy.deepcopy(summary)
    row["evaluated"][0]["technicalGates"] = "n/a"
    row["evaluated"][0]["comparativeScore"] = None
    refused("value_not_allowed", validate_decision, row, plain, plain)


# ------------------------------------------------------------------ repository mode


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def write_frozen_event(repo: Path, document, *, record_extra=""):
    folder = repo / "docs" / "qualification" / "model-selection" / document["capabilityId"]
    event = document["eventId"]
    write(folder / f"{event}-evidence-ledger.json", json.dumps(document))
    write(folder / f"{event}-evidence-ledger-frozen.json", json.dumps(document))
    protocol = write(folder / f"{event}-protocol.md",
                     f"Frozen ledger SHA-256: {document_sha256(document)}\nFrozen on: {document['frozenOn']}\n")
    write(folder / f"{event}.md", f"Protocol SHA-256: {lf_normalised_sha256(protocol)}\n{record_extra}")
    return folder, lf_normalised_sha256(protocol)


def build_repository(repo: Path, *, stopped=False, with_decision=True, cite_seal=True):
    document = m3_ledger()
    partner = partner_ledger()
    write_frozen_event(repo, partner)
    folder, protocol_sha = write_frozen_event(repo, document)
    gates = {p: {g: "failed" for g in GATE_IDS} for p in ("PD-A", "PD-B")} if stopped else None
    result = layer_a(document, partner, gates=gates)
    seal = bs.derive_baseline_seal(document, GATE, protocol_sha256=protocol_sha, partner_ledger=partner,
                                   layer_a=result, recorded_at=SEALED_AT, recorded_by="synthetic-harness")
    write(bs.layer_a_path(repo, document, GATE), canonical_json(result).decode())
    write(bs.seal_path(repo, document, GATE), canonical_json(seal).decode())
    record = folder / f"{EVENT}.md"
    if cite_seal:
        write(record, record.read_text() + bs.seal_citation(GATE, document_sha256(seal)) + "\n")
    if with_decision:
        # A decision holds D results: the seal must be committed first, in a strict ancestor (owner decision 2).
        git(repo, "init", "-q")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "freeze and seal")
        proof = {GATE: {"seal": seal, "layerA": result, "partnerLedger": partner}}
        summary = m3_decision(document, proof, **({"state": "TECHNICAL_DECISION_RECORDED", "implementation": None}
                                                  if stopped else {}))
        summary["protocolSha256"] = protocol_sha
        summary["benchmarkOnlyBaselines"]["baselineSeals"][0]["sealCommit"] = git(repo, "rev-parse", "HEAD")
        decision_path = write(folder / f"{EVENT}-decision.json", json.dumps(summary))
        snapshot_path = write(folder / f"{EVENT}-evidence-ledger-decided.json", json.dumps(document))
        write(record, record.read_text() + f"Decision SHA-256: {lf_normalised_sha256(decision_path)}\n"
              f"Snapshot SHA-256: {lf_normalised_sha256(snapshot_path)}\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "decision")
    return document, partner, seal, folder


def test_repository_scan_verifies_committed_seal_and_decision(tmp_path):
    build_repository(tmp_path)
    checked = validate_repository(tmp_path)
    assert any(path.endswith(f"{bs.SEAL_INFIX}{GATE}.json") for path in checked)
    assert any(path.endswith(f"{bs.LAYER_A_INFIX}{GATE}.json") for path in checked)


def test_repository_scan_accepts_a_stopped_event_without_decision(tmp_path):
    build_repository(tmp_path, stopped=True, with_decision=False)
    validate_repository(tmp_path)


def test_repository_scan_refuses_uncited_noncanonical_or_orphan_seals(tmp_path):
    build_repository(tmp_path / "a", with_decision=False, cite_seal=False)
    refused("baseline_seal_not_recorded", validate_repository, tmp_path / "a")
    document, _partner, seal, folder = build_repository(tmp_path / "b", with_decision=False)
    write(bs.seal_path(tmp_path / "b", document, GATE), json.dumps(seal, indent=2))
    refused("baseline_seal_not_canonical", validate_repository, tmp_path / "b")
    document, _partner, seal, folder = build_repository(tmp_path / "c", with_decision=False)
    write(folder / f"{EVENT}{bs.SEAL_INFIX}GATE-STRAY.json", canonical_json(seal).decode())
    refused("baseline_artefact_without_frozen_composition", validate_repository, tmp_path / "c")
    build_repository(tmp_path / "d", with_decision=False)
    partner_file = tmp_path / "d" / "docs" / "qualification" / "model-selection" / "plate-detector" / \
        f"{PARTNER_EVENT}-evidence-ledger-frozen.json"
    partner_file.unlink()
    (partner_file.parent / f"{PARTNER_EVENT}-protocol.md").unlink()
    (partner_file.parent / f"{PARTNER_EVENT}.md").unlink()
    refused("baseline_seal_not_derivable", validate_repository, tmp_path / "d")


def test_repository_scan_refuses_a_decision_without_seal(tmp_path):
    document, _partner, seal, folder = build_repository(tmp_path)
    bs.seal_path(tmp_path, document, GATE).unlink()
    refused("baseline_seal_cited_without_file", validate_repository, tmp_path)
    record = folder / f"{EVENT}.md"
    write(record, record.read_text().replace(bs.seal_citation(GATE, document_sha256(seal)) + "\n", ""))
    refused("baseline_artefact_rewritten_in_history", validate_repository, tmp_path)  # a committed seal removed


def test_repository_scan_refuses_a_reseal_after_d(tmp_path):
    """P1-2 in repository mode: D and the decision bound to PD-A; seal and Layer-A rewritten to PD-B."""
    document, partner, seal, folder = build_repository(tmp_path)
    forged = layer_a(document, partner, ranks={"PD-A": [False, -0.5, "PD-A"], "PD-B": [False, -0.8, "PD-B"]})
    protocol_sha = lf_normalised_sha256(folder / f"{EVENT}-protocol.md")
    reseal = bs.derive_baseline_seal(document, GATE, protocol_sha256=protocol_sha, partner_ledger=partner,
                                     layer_a=forged, recorded_at=SEALED_AT, recorded_by="synthetic-harness")
    assert reseal["partnerCandidateId"] == "PD-B"
    write(bs.layer_a_path(tmp_path, document, GATE), canonical_json(forged).decode())
    write(bs.seal_path(tmp_path, document, GATE), canonical_json(reseal).decode())
    refused("baseline_seal_not_recorded", validate_repository, tmp_path)
    record = folder / f"{EVENT}.md"
    write(record, record.read_text() + bs.seal_citation(GATE, document_sha256(reseal)) + "\n")
    refused("baseline_seal_cited_twice", validate_repository, tmp_path)
    write(record, record.read_text().replace(document_sha256(seal), document_sha256(reseal)))
    refused("baseline_seal_cited_twice", validate_repository, tmp_path)
    write(record, record.read_text().replace(bs.seal_citation(GATE, document_sha256(reseal)) + "\n", "", 1))
    refused("baseline_artefact_rewritten_in_history", validate_repository, tmp_path)


# ------------------------------------------------------------------ harness API (git)


def git(repo: Path, *args: str) -> str:
    environment = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    return subprocess.run(["git", "-C", str(repo), "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false", *args],
                          capture_output=True, text=True, check=True, env=environment).stdout.strip()


def committed_repository(repo: Path, **kwargs):
    built = build_repository(repo, with_decision=False, **kwargs)
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "freeze and seal")
    return built


def test_harness_requires_the_exact_committed_resolved_seal(tmp_path):
    document, _partner, seal, folder = committed_repository(tmp_path / "a")
    binding = bs.require_committed_baseline_seal(tmp_path / "a", EVENT, "vehicle-colour", GATE)
    assert binding.seal_sha256 == document_sha256(seal) and binding.partner_candidate_id == "PD-A"
    assert binding.seal_commit == git(tmp_path / "a", "rev-parse", "HEAD")
    write(bs.seal_path(tmp_path / "a", document, GATE), canonical_json(dict(seal, recordedBy="someone")).decode())
    refused("baseline_seal_not_committed", bs.require_committed_baseline_seal, tmp_path / "a", EVENT,
            "vehicle-colour", GATE)
    committed_repository(tmp_path / "b", stopped=True)
    refused("baseline_seal_stopped_no_d", bs.require_committed_baseline_seal, tmp_path / "b", EVENT,
            "vehicle-colour", GATE)


def test_d_manifest_bound_to_a_seal_refuses_a_later_reseal(tmp_path):
    repo = tmp_path / "r"
    document, partner, seal, folder = committed_repository(repo)
    binding = bs.require_committed_baseline_seal(repo, EVENT, "vehicle-colour", GATE)
    manifest = {"baselineSeals": [{"compositionId": GATE, "sealSha256": binding.seal_sha256,
                                   "sealCommit": binding.seal_commit}]}
    bs.verify_d_manifest_binding(manifest, repo, EVENT, "vehicle-colour")
    for rows in ([], [dict(manifest["baselineSeals"][0], sealSha256=sha("x"))],
                 [dict(manifest["baselineSeals"][0], compositionId="GATE-OTHER")]):
        refused("d_manifest_baseline_seal_mismatch", bs.verify_d_manifest_binding, {"baselineSeals": rows}, repo,
                EVENT, "vehicle-colour")
    # Later commit: Layer-A forged so PD-B derives, seal recomputed, record re-cited. The D manifest still cites A.
    forged = layer_a(document, partner, ranks={"PD-A": [False, -0.5, "PD-A"], "PD-B": [False, -0.8, "PD-B"]})
    protocol_sha = lf_normalised_sha256(folder / f"{EVENT}-protocol.md")
    reseal = bs.derive_baseline_seal(document, GATE, protocol_sha256=protocol_sha, partner_ledger=partner,
                                     layer_a=forged, recorded_at=SEALED_AT, recorded_by="synthetic-harness")
    write(bs.layer_a_path(repo, document, GATE), canonical_json(forged).decode())
    write(bs.seal_path(repo, document, GATE), canonical_json(reseal).decode())
    record = folder / f"{EVENT}.md"
    write(record, record.read_text().replace(document_sha256(seal), document_sha256(reseal)))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "reseal")
    refused("d_manifest_baseline_seal_mismatch", bs.verify_d_manifest_binding, manifest, repo, EVENT,
            "vehicle-colour")
    stale_commit = dict(manifest["baselineSeals"][0], sealSha256=document_sha256(reseal))
    refused("d_manifest_baseline_seal_mismatch", bs.verify_d_manifest_binding, {"baselineSeals": [stale_commit]},
            repo, EVENT, "vehicle-colour")


# ------------------------------------------------------------------ committed ledgers are untouched


IMMUTABLE_SUFFIXES = ("-evidence-ledger-frozen.json", "-evidence-ledger-decided.json", "-protocol.md")


def _git_in_repo(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False,
                          cwd=Path(__file__).resolve().parents[3])


def test_committed_frozen_artefacts_never_change_and_no_ledger_turns_m3_retroactively():
    """Against the merge-base with origin/main: a frozen ledger, decision snapshot, protocol, seal, Layer-A result or
    D manifest that existed there is never modified or deleted, and no ledger that existed there switches to
    msr-v1-m3 (M3 is not retroactive). Added files are allowed (a new event, PR-2's own ledgers). CI checks out full
    history for this test; outside CI it is skipped only when origin/main is unavailable."""
    base = _git_in_repo("merge-base", "origin/main", "HEAD")
    if base.returncode != 0:
        if os.environ.get("GITHUB_ACTIONS") == "true":
            pytest.fail("origin/main is unavailable in CI: the qualification checkout must fetch full history")
        pytest.skip("origin/main is not available in this local checkout")
    base_sha = base.stdout.strip()
    diff = _git_in_repo("diff", "--name-status", "--no-renames", base_sha, "HEAD", "--",
                        "docs/qualification/model-selection")
    assert diff.returncode == 0, diff.stderr
    for line in diff.stdout.splitlines():
        status, _, path = line.partition(chr(9))
        name = Path(path).name
        if status[0] == "A":
            continue
        immutable = name.startswith("msr-") and name.endswith(IMMUTABLE_SUFFIXES) or name.startswith("msr-") and any(
            infix in name for infix in (bs.SEAL_INFIX, bs.LAYER_A_INFIX, bs.D_MANIFEST_INFIX))
        assert not immutable, f"{status} {path}"
        if status[0] == "M" and name.endswith("-evidence-ledger.json"):
            before = json.loads(_git_in_repo("show", f"{base_sha}:{path}").stdout)
            after = json.loads((Path(__file__).resolve().parents[3] / path).read_text(encoding="utf-8"))
            assert not (before.get("methodRevision") != "msr-v1-m3" and after.get("methodRevision") == "msr-v1-m3"), path


def test_published_schemas_accept_derived_seals_and_layer_a_results():
    jsonschema = pytest.importorskip("jsonschema")
    schemas = Path(__file__).resolve().parents[1] / "model_selection" / "schemas"
    seal_schema = json.loads((schemas / "mavi-model-selection-baseline-seal-v1.schema.json").read_text())
    layer_schema = json.loads((schemas / "mavi-model-selection-layer-a-result-v1.schema.json").read_text())
    document = m3_ledger()
    for proof in (evidence(document), stopped_evidence(document)):
        jsonschema.validate(proof[GATE]["seal"], seal_schema)
        jsonschema.validate(proof[GATE]["layerA"], layer_schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(dict(stopped_evidence(document)[GATE]["seal"], partnerCandidateId="PD-A"), seal_schema)
    d_schema = json.loads((schemas / "mavi-model-selection-d-manifest-v1.schema.json").read_text())
    binding = bs.SealBinding(GATE, document_sha256(evidence(document)[GATE]["seal"]), "a" * 40, "PD-A",
                             identity_of("pda"), sha("composition"))
    jsonschema.validate(bs.d_manifest_document(document, "RUN-1", sha("d"), [binding]), d_schema)


def test_a_stop_survives_later_inputs_and_a_protocol_revision(tmp_path):
    """A STOPPED seal is immutable history after a protocol revision with a new composition id. While its frozen
    composition is current, a stop that claims an input was absent is refused once that input is supplied (cold
    review P3-1). A superseded RESOLVED seal is refused."""
    document = m3_ledger()
    missing = bs.derive_baseline_seal(document, GATE, protocol_sha256=PROTOCOL, partner_ledger=None, layer_a=None,
                                      recorded_at=SEALED_AT, recorded_by="synthetic-harness")
    assert missing["stopReason"] == "partner-event-missing"
    proof = evidence(document)
    bs.verify_baseline_seal(missing, frozen=document, protocol_sha256=PROTOCOL, partner_ledger=None, layer_a=None)
    refused("baseline_stop_reason_contradicted", bs.verify_baseline_seal, missing, frozen=document,
            protocol_sha256=PROTOCOL, partner_ledger=proof[GATE]["partnerLedger"], layer_a=proof[GATE]["layerA"])

    repo = tmp_path / "revised"
    old, _partner, stopped_seal, folder = build_repository(repo, stopped=True, with_decision=False)
    revised_entry = bob()
    revised_entry["benchmarkBaseline"]["compositions"][0]["compositionId"] = "GATE-BASE-R1"
    revised = m3_ledger(baseline(), established(), emerging(), revised_entry)
    revised["frozenOn"] = "2026-07-05"
    record = folder / f"{EVENT}.md"
    history = record.read_text()
    write_frozen_event(repo, revised, record_extra=history)
    validate_repository(repo)
    write(record, record.read_text().replace(document_sha256(stopped_seal), "0" * 64))
    refused("baseline_seal_not_recorded", validate_repository, repo)

    repo = tmp_path / "resolved"
    old, _partner, resolved_seal, folder = build_repository(repo, with_decision=False)
    for path in folder.glob(f"{EVENT}-decision.json"):
        path.unlink()
    record = folder / f"{EVENT}.md"
    write_frozen_event(repo, revised, record_extra=record.read_text())
    refused("baseline_artefact_without_frozen_composition", validate_repository, repo)


# ------------------------------------------------------------------ cold review of f24dcf5e (every confirmed probe)

NL = chr(10)


def cite(record, composition_id, digest):
    write(record, record.read_text() + bs.seal_citation(composition_id, digest) + NL)


def test_cold_p1_1_stopped_seal_replaced_in_place_by_resolved_is_refused(tmp_path):
    """Probe 1: a cited STOPPED seal; Layer-A rewritten so the gates pass; the seal overwritten RESOLVED and its hash
    appended to the record. Without Git the double citation is refused; with Git the modify commit is refused."""
    document, partner, stopped_seal, folder = build_repository(tmp_path, stopped=True, with_decision=False)
    validate_repository(tmp_path)
    good = layer_a(document, partner)
    protocol_sha = lf_normalised_sha256(folder / f"{EVENT}-protocol.md")
    resolved = bs.derive_baseline_seal(document, GATE, protocol_sha256=protocol_sha, partner_ledger=partner,
                                       layer_a=good, recorded_at="2026-07-03T10:00:00Z", recorded_by="later")
    write(bs.layer_a_path(tmp_path, document, GATE), canonical_json(good).decode())
    write(bs.seal_path(tmp_path, document, GATE), canonical_json(resolved).decode())
    record = folder / f"{EVENT}.md"
    refused("baseline_seal_not_recorded", validate_repository, tmp_path)
    cite(record, GATE, document_sha256(resolved))
    refused("baseline_seal_cited_twice", validate_repository, tmp_path)


def test_cold_p1_1_resolved_seal_swapped_before_the_decision_is_refused(tmp_path):
    """Probe 3: PD-A sealed and cited; Layer-A, seal and record rewritten to PD-B before any decision."""
    document, partner, seal, folder = build_repository(tmp_path, with_decision=False)
    forged = layer_a(document, partner, ranks={"PD-A": [False, -0.5, "PD-A"], "PD-B": [False, -0.8, "PD-B"]})
    protocol_sha = lf_normalised_sha256(folder / f"{EVENT}-protocol.md")
    reseal = bs.derive_baseline_seal(document, GATE, protocol_sha256=protocol_sha, partner_ledger=partner,
                                     layer_a=forged, recorded_at=SEALED_AT, recorded_by="x")
    write(bs.layer_a_path(tmp_path, document, GATE), canonical_json(forged).decode())
    write(bs.seal_path(tmp_path, document, GATE), canonical_json(reseal).decode())
    record = folder / f"{EVENT}.md"
    cite(record, GATE, document_sha256(reseal))
    refused("baseline_seal_cited_twice", validate_repository, tmp_path)


def test_cold_p1_1_git_history_makes_seals_add_only(tmp_path):
    """With full Git history an in-place rewrite of the seal and of its record line is refused even when the
    working tree is self-consistent; without history the state is reported, never claimed."""
    repo = tmp_path / "g"
    document, partner, seal, folder = committed_repository(repo)
    assert any(item == "git-history:full" for item in validate_repository(repo))
    forged = layer_a(document, partner, ranks={"PD-A": [False, -0.5, "PD-A"], "PD-B": [False, -0.8, "PD-B"]})
    protocol_sha = lf_normalised_sha256(folder / f"{EVENT}-protocol.md")
    reseal = bs.derive_baseline_seal(document, GATE, protocol_sha256=protocol_sha, partner_ledger=partner,
                                     layer_a=forged, recorded_at=SEALED_AT, recorded_by="x")
    write(bs.layer_a_path(repo, document, GATE), canonical_json(forged).decode())
    write(bs.seal_path(repo, document, GATE), canonical_json(reseal).decode())
    record = folder / f"{EVENT}.md"
    write(record, record.read_text().replace(document_sha256(seal), document_sha256(reseal)))
    refused("baseline_artefact_rewritten_in_history", validate_repository, repo)  # uncommitted modification
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "reseal in place")
    refused("baseline_artefact_rewritten_in_history", validate_repository, repo)  # a modify commit
    # the record line alone rewritten in history (seal file re-added under the same name after a delete)
    repo2 = tmp_path / "h"
    document, partner, seal, folder = committed_repository(repo2)
    record = folder / f"{EVENT}.md"
    write(record, record.read_text().replace(document_sha256(seal), "f" * 64))
    git(repo2, "commit", "-q", "-am", "edit citation")
    write(record, record.read_text().replace("f" * 64, document_sha256(seal)))
    git(repo2, "commit", "-q", "-am", "restore citation")
    refused("baseline_seal_citation_changed", validate_repository, repo2)
    plain_dir = tmp_path / "nogit"
    build_repository(plain_dir, with_decision=False)
    assert "git-history:absent" in validate_repository(plain_dir)


def test_cold_p3_1_fabricated_stop_is_refused_when_the_inputs_exist(tmp_path):
    """Probe 2: a STOPPED partner-event-missing seal committed while the partner frozen ledger and a resolvable
    Layer-A result are in the repository."""
    document, partner, seal, folder = build_repository(tmp_path, with_decision=False)
    protocol_sha = lf_normalised_sha256(folder / f"{EVENT}-protocol.md")
    for partner_doc, result_doc in ((None, None), (partner, None)):
        fake = bs.derive_baseline_seal(document, GATE, protocol_sha256=protocol_sha, partner_ledger=partner_doc,
                                       layer_a=result_doc, recorded_at=SEALED_AT, recorded_by="x")
        assert fake["status"] == "STOPPED"
        record = folder / f"{EVENT}.md"
        write(record, record.read_text().replace(document_sha256(seal), document_sha256(fake)))
        write(bs.seal_path(tmp_path, document, GATE), canonical_json(fake).decode())
        refused("baseline_stop_reason_contradicted", validate_repository, tmp_path)
        seal = fake
    # a stop whose reason differs from the one the inputs derive is refused too
    wrong = dict(stopped_evidence(document)[GATE]["seal"], stopReason="identity-mismatch")
    proof = stopped_evidence(document)
    refused("baseline_stop_reason_contradicted", bs.verify_baseline_seal, wrong, frozen=document,
            protocol_sha256=PROTOCOL, partner_ledger=proof[GATE]["partnerLedger"], layer_a=proof[GATE]["layerA"])


def test_cold_p3_2_an_accessed_stop_records_the_d_access():
    """A protected-d-accessed stop records when D was accessed; its seal is checked, and no decision may follow it."""
    document = m3_ledger()
    partner = partner_ledger()
    result = layer_a(document, partner)
    with pytest.raises(CredibilityError):
        bs.derive_baseline_seal(document, GATE, protocol_sha256=PROTOCOL, partner_ledger=partner, layer_a=result,
                                recorded_at=SEALED_AT, recorded_by="x", protected_d_rows_read=5)
    seal = bs.derive_baseline_seal(document, GATE, protocol_sha256=PROTOCOL, partner_ledger=partner, layer_a=result,
                                   recorded_at=SEALED_AT, recorded_by="x", protected_d_rows_read=5,
                                   protected_d_accessed_at="2026-07-01T09:00:00Z")
    assert seal["protectedDState"] == "ACCESSED" and seal["protectedDAccessedAt"] == "2026-07-01T09:00:00Z"
    bs.verify_baseline_seal(seal, frozen=document, protocol_sha256=PROTOCOL, partner_ledger=partner, layer_a=result)
    proof = {GATE: {"seal": seal, "layerA": result, "partnerLedger": partner}}
    summary = m3_decision(document, proof, state="TECHNICAL_DECISION_RECORDED", implementation=None)
    refused("baseline_stopped_decision_refused", check, summary, document, proof)
    for field, value in (("protectedDAccessedAt", None), ("protectedDAccessedAt", "2026-07-02T09:00:00Z")):
        refused("baseline_seal_d_state_contradicted" if value else "instant_malformed", bs.verify_baseline_seal,
                dict(seal, **{field: value}), frozen=document, protocol_sha256=PROTOCOL, partner_ledger=partner,
                layer_a=result)
    not_accessed = stopped_evidence(document)[GATE]["seal"]
    refused("baseline_seal_d_state_contradicted", bs.verify_baseline_seal,
            dict(not_accessed, protectedDAccessedAt=SEALED_AT), frozen=document, protocol_sha256=PROTOCOL,
            partner_ledger=stopped_evidence(document)[GATE]["partnerLedger"],
            layer_a=stopped_evidence(document)[GATE]["layerA"])

def test_cold_p3_3_bob_bytes_under_another_identity_are_refused():
    """Probe 7b: the BOB's weights re-listed in the partner event as PD-TESS (another identity document)."""
    document = m3_ledger()
    twin = established("PD-TESS", "bob")
    twin["identity"]["tag"] = "v1.0-mirror"
    partner = partner_ledger(established("PD-A", "pda"), established("PD-B", "pdb"), twin)
    tess = {"candidateId": "PD-TESS", "identitySha256": document_sha256(twin["identity"]),
            "reason": "not a detector release of interest"}
    excluded_doc = copy.deepcopy(document)
    excluded_doc["candidates"][-1]["benchmarkBaseline"]["compositions"][0]["excludedPartners"] = [tess]
    excluded_doc = m3_ledger(*[e for e in excluded_doc["candidates"]])
    proof = evidence(excluded_doc, partner=partner)
    summary = m3_decision(excluded_doc, proof)
    digest = document_sha256(proof[GATE]["seal"])
    est = next(e for e in excluded_doc["candidates"] if e["candidateId"] == "VC-EST")
    smuggled = {"compositionId": "C-TESS", "components": [
        component(PARTNER_EVENT, "PD-TESS", document_sha256(twin["identity"])),
        component(EVENT, "VC-EST", document_sha256(est["identity"]))],
        "gates": {GATE: "passed"}, "technicalGates": "passed", "comparativeScore": 0.95,
        "dResultSha256": sha("d"), "baselineSealSha256s": {GATE: digest}}
    block_ = summary["benchmarkOnlyBaselines"]
    block_["compositionCandidates"].append(smuggled)
    block_["rankedCompositions"] = ["C-TESS"] + block_["rankedCompositions"]
    block_["strongestEvaluatedComposition"] = "C-TESS"
    block_["frontier"] = ["C-TESS"]
    refused("benchmark_baseline_in_composition_candidate", check, summary, excluded_doc, proof)
    # and as an eligible partner of the gate-only composition
    as_partner = copy.deepcopy(document)
    rule = as_partner["candidates"][-1]["benchmarkBaseline"]["compositions"][0]
    rule["eligiblePartners"] = sorted(partners() + [{k: tess[k] for k in ("candidateId", "identitySha256")}],
                                      key=lambda p: p["candidateId"])
    as_partner = m3_ledger(*as_partner["candidates"])
    refused("benchmark_baseline_bytes_as_partner", bs.check_partner_universe,
            as_partner["candidates"][-1]["benchmarkBaseline"]["compositions"][0], partner, "p",
            as_partner["candidates"][-1])


def test_cold_p3_4_partner_universe_subset_needs_recorded_exclusions():
    """Probe 4: the frozen universe is the partner shortlist exactly; an excluded partner carries its reason."""
    document = m3_ledger()
    rule = document["candidates"][-1]["benchmarkBaseline"]["compositions"][0]
    rule["eligiblePartners"] = [partners()[1]]
    subset = m3_ledger(*document["candidates"])
    refused("baseline_partner_universe_not_the_shortlist", bs.check_partner_universe,
            subset["candidates"][-1]["benchmarkBaseline"]["compositions"][0], partner_ledger(), "p",
            subset["candidates"][-1])
    rule["excludedPartners"] = [dict(partners()[0], reason="fails the frozen input-size requirement")]
    recorded = m3_ledger(*document["candidates"])
    bs.check_partner_universe(recorded["candidates"][-1]["benchmarkBaseline"]["compositions"][0], partner_ledger(),
                              "p", recorded["candidates"][-1])
    rule["excludedPartners"] = [dict(partners()[1], reason="duplicate")]
    refused("excluded_partners_not_sorted_unique_disjoint", validate_ledger, m3_ledger(*document["candidates"]))


def test_cold_p3_5_decision_seal_commit_is_bound_where_git_history_exists(tmp_path):
    repo = tmp_path / "r"
    document, partner, seal, folder = committed_repository(repo)
    commit = git(repo, "rev-parse", "HEAD")
    proof = {GATE: {"seal": seal, "layerA": json.loads(bs.layer_a_path(repo, document, GATE).read_text()),
                    "partnerLedger": partner}}
    summary = m3_decision(document, proof)
    summary["protocolSha256"] = lf_normalised_sha256(folder / f"{EVENT}-protocol.md")
    summary["benchmarkOnlyBaselines"]["baselineSeals"][0]["sealCommit"] = commit
    decision_path = write(folder / f"{EVENT}-decision.json", json.dumps(summary))
    snapshot_path = write(folder / f"{EVENT}-evidence-ledger-decided.json", json.dumps(document))
    record = folder / f"{EVENT}.md"
    write(record, record.read_text() + f"Decision SHA-256: {lf_normalised_sha256(decision_path)}" + NL +
          f"Snapshot SHA-256: {lf_normalised_sha256(snapshot_path)}" + NL)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "decision")
    validate_repository(repo)
    summary["benchmarkOnlyBaselines"]["baselineSeals"][0]["sealCommit"] = "0" * 40
    write(decision_path, json.dumps(summary))
    write(record, record.read_text() + f"Decision SHA-256: {lf_normalised_sha256(decision_path)}" + NL)
    refused("d_artefact_seal_commit_mismatch", validate_repository, repo)
    refused("malformed", check, dict(summary, benchmarkOnlyBaselines=dict(
        summary["benchmarkOnlyBaselines"], baselineSeals=[dict(summary["benchmarkOnlyBaselines"]["baselineSeals"][0],
                                                                sealCommit="HEAD")])), document, proof)


def test_cold_p3_6_bob_without_a_gate_is_refused():
    """Probe 14: a benchmark-only component with zero gate-only compositions."""
    entry = bob()
    entry["benchmarkBaseline"]["compositions"] = []
    refused("benchmark_baseline_without_gate", validate_ledger, m3_ledger(entry))



# ------------------------------------------------------------------ owner decision 2: seal chronology (real git)


def seal_then_d(tmp_path, name="d1"):
    """A committed seal, then a protected-D manifest bound to it in a later commit."""
    repo = tmp_path / name
    document, partner, seal, folder = committed_repository(repo)
    binding = bs.require_committed_baseline_seal(repo, EVENT, "vehicle-colour", GATE)
    manifest = bs.d_manifest_document(document, "RUN-1", sha("d-result"), [binding])
    path = folder / f"{EVENT}{bs.D_MANIFEST_INFIX}RUN-1.json"
    write(path, canonical_json(manifest).decode())
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "protected D run 1")
    return repo, document, partner, seal, folder, manifest, path


def test_chronology_seal_strictly_before_d_is_accepted(tmp_path):
    repo, *_ = seal_then_d(tmp_path)
    checked = validate_repository(repo)
    assert any(bs.D_MANIFEST_INFIX in item for item in checked) and "git-history:full" in checked


def test_chronology_seal_and_d_in_the_same_commit_is_refused(tmp_path):
    """The seal and its first protected-D manifest first appear in one commit: not proof that the seal came first."""
    repo = tmp_path / "same"
    document, partner, seal, folder = committed_repository(repo)
    sealed = git(repo, "rev-parse", "HEAD")
    manifest = {"schema": bs.D_MANIFEST_SCHEMA, "eventId": EVENT, "manifestId": "RUN-1", "resultSha256": sha("d"),
                "baselineSeals": [{"compositionId": GATE, "sealSha256": document_sha256(seal), "sealCommit": sealed}]}
    write(folder / f"{EVENT}{bs.D_MANIFEST_INFIX}RUN-1.json", canonical_json(manifest).decode())
    validate_repository(repo)  # not yet committed: the seal commit is in HEAD's history
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--amend", "-m", "seal and D manifest in one commit")
    refused("d_artefact_seal_commit_not_ancestral", validate_repository, repo)
    # citing the very commit that added both is refused too (the manifest had to be rewritten to name it)
    together = git(repo, "rev-parse", "HEAD")
    manifest["baselineSeals"][0]["sealCommit"] = together
    write(folder / f"{EVENT}{bs.D_MANIFEST_INFIX}RUN-1.json", canonical_json(manifest).decode())
    refused("d_artefact_seal_commit_not_ancestral", validate_repository, repo)
    repo2 = tmp_path / "self"
    document, partner, seal, folder = build_repository(repo2, with_decision=False)
    git(repo2, "init", "-q")
    git(repo2, "add", "-A")
    git(repo2, "commit", "-q", "-m", "seal")
    manifest["baselineSeals"][0]["sealCommit"] = git(repo2, "rev-parse", "HEAD")
    write(folder / f"{EVENT}{bs.D_MANIFEST_INFIX}RUN-1.json", canonical_json(manifest).decode())
    git(repo2, "add", "-A")
    git(repo2, "commit", "-q", "--amend", "--no-edit")
    refused("d_artefact_seal_commit_not_ancestral", validate_repository, repo2)


def test_chronology_non_ancestor_seal_commit_is_refused(tmp_path):
    repo, document, partner, seal, folder, manifest, path = seal_then_d(tmp_path)
    # a side branch holding the same seal bytes: it contains the seal but is not an ancestor of the manifest
    git(repo, "checkout", "-q", "-b", "side", "HEAD~1")
    git(repo, "commit", "-q", "--allow-empty", "-m", "side commit")
    side = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-")
    other = dict(manifest, manifestId="RUN-2",
                 baselineSeals=[dict(manifest["baselineSeals"][0], sealCommit=side)])
    write(folder / f"{EVENT}{bs.D_MANIFEST_INFIX}RUN-2.json", canonical_json(other).decode())
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "protected D run 2")
    refused("d_artefact_seal_commit_not_ancestral", validate_repository, repo)


def test_chronology_modified_seal_and_second_hash_are_refused(tmp_path):
    repo, document, partner, seal, folder, manifest, path = seal_then_d(tmp_path)
    changed = dict(seal, recordedBy="someone else")
    write(bs.seal_path(repo, document, GATE), canonical_json(changed).decode())
    record = folder / f"{EVENT}.md"
    write(record, record.read_text().replace(document_sha256(seal), document_sha256(changed)))
    refused("d_manifest_baseline_seal_mismatch", validate_repository, repo)  # D cites the first hash
    git(repo, "commit", "-q", "-am", "modify the seal")
    refused("d_manifest_baseline_seal_mismatch", validate_repository, repo)
    # a second D manifest citing the new hash: two hashes for one composition across D artefacts
    repo, document, partner, seal, folder, manifest, path = seal_then_d(tmp_path, "d2")
    second = dict(manifest, manifestId="RUN-2",
                  baselineSeals=[dict(manifest["baselineSeals"][0], sealSha256=sha("another seal"))])
    write(folder / f"{EVENT}{bs.D_MANIFEST_INFIX}RUN-2.json", canonical_json(second).decode())
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "second hash")
    refused("d_manifest_baseline_seal_mismatch", validate_repository, repo)


@pytest.mark.parametrize("swap", ["stopped-to-resolved", "pd-a-to-pd-b"])
def test_chronology_reseal_after_d_is_refused(tmp_path, swap):
    repo = tmp_path / swap
    if swap == "stopped-to-resolved":
        document, partner, seal, folder = committed_repository(repo, stopped=True)
        manifest = {"schema": bs.D_MANIFEST_SCHEMA, "eventId": EVENT, "manifestId": "RUN-1",
                    "resultSha256": sha("d"), "baselineSeals": [{"compositionId": GATE,
                                                                 "sealSha256": document_sha256(seal),
                                                                 "sealCommit": git(repo, "rev-parse", "HEAD")}]}
        write(folder / f"{EVENT}{bs.D_MANIFEST_INFIX}RUN-1.json", canonical_json(manifest).decode())
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "D under a stop")
        refused("baseline_stopped_no_d_result", validate_repository, repo)
        new_layer = layer_a(document, partner)
    else:
        repo, document, partner, seal, folder, manifest, path = seal_then_d(tmp_path, swap)
        validate_repository(repo)
        new_layer = layer_a(document, partner, ranks={"PD-A": [False, -0.5, "PD-A"], "PD-B": [False, -0.8, "PD-B"]})
    protocol_sha = lf_normalised_sha256(folder / f"{EVENT}-protocol.md")
    reseal = bs.derive_baseline_seal(document, GATE, protocol_sha256=protocol_sha, partner_ledger=partner,
                                     layer_a=new_layer, recorded_at="2026-07-03T10:00:00Z", recorded_by="later")
    assert reseal["status"] == "RESOLVED"
    write(bs.layer_a_path(repo, document, GATE), canonical_json(new_layer).decode())
    write(bs.seal_path(repo, document, GATE), canonical_json(reseal).decode())
    record = folder / f"{EVENT}.md"
    write(record, record.read_text().replace(document_sha256(seal), document_sha256(reseal)))
    git(repo, "commit", "-q", "-am", "reseal")
    reseal_commit = git(repo, "rev-parse", "HEAD")
    for item in folder.glob(f"{EVENT}{bs.D_MANIFEST_INFIX}*.json"):
        bound = json.loads(item.read_text())
        bound["baselineSeals"][0].update(sealSha256=document_sha256(reseal), sealCommit=reseal_commit)
        write(item, canonical_json(bound).decode())
    git(repo, "commit", "-q", "-am", "rebind D")
    # the rebound D manifests cite a seal commit newer than the commit that added them
    refused("d_artefact_seal_commit_not_ancestral", validate_repository, repo)


def test_chronology_needs_full_history_for_an_event_with_d(tmp_path):
    repo, document, partner, seal, folder, manifest, path = seal_then_d(tmp_path)
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", repo.as_uri(), str(shallow)], check=True,
                   capture_output=True)
    refused("baseline_seal_history_unavailable", validate_repository, shallow)
    copy_dir = tmp_path / "nogit"
    import shutil
    shutil.copytree(repo, copy_dir, ignore=shutil.ignore_patterns(".git"))
    refused("baseline_seal_history_unavailable", validate_repository, copy_dir)



# ------------------------------------------------------------------ final round, item 1: scoped STOPPED semantics


def test_stopped_pr2_shape_permits_no_protected_d_and_no_selection():
    """PR-2 shape, strict: with the one gate-only baseline STOPPED, nothing beyond PLANNED is recorded: no winner,
    frontier, top-K, finalists, ranked or scored composition, no implementation and no outcome of any kind."""
    document = m3_ledger()
    proof = stopped_evidence(document)
    base = m3_decision(document, proof, state="TECHNICAL_DECISION_RECORDED", implementation=None)
    resolved = m3_block(document, evidence(document))
    variants = {"empty": lambda b, s: None}
    for field in ("topK", "componentFinalists"):
        variants[field] = lambda b, s, f=field: b.update({f: ["VC-EST"]})
    variants["frontier"] = lambda b, s: b.update(frontier=["VC-EST"])
    variants["winner"] = lambda b, s: s.update(strongestEvaluatedTechnical="VC-EMG")
    variants["compositions"] = lambda b, s: b.update(
        compositionCandidates=resolved["compositionCandidates"], rankedCompositions=resolved["rankedCompositions"],
        strongestEvaluatedComposition=resolved["strongestEvaluatedComposition"], frontier=resolved["frontier"],
        dExecutionStartedAt=D_STARTED)
    variants["incumbent"] = lambda b, s: b.update(incumbent="VC-EST")
    for name, mutate in variants.items():
        for state, implementation, outcome in (("TECHNICAL_DECISION_RECORDED", None, None),
                                               ("QUALIFICATION_PENDING", ("VC-EST",), None),
                                               ("CLOSED", None, "INCUMBENT_RETAINED"),
                                               ("CLOSED", None, "NO_QUALIFIABLE_CANDIDATE"),
                                               ("CLOSED", ("VC-B0",), "BASELINE_SELECTED"),
                                               ("CLOSED", ("VC-EST",), "SELECTED_FOR_PACKAGING")):
            summary = m3_decision(document, proof, state=state, implementation=implementation)
            summary["outcome"] = outcome
            mutate(summary["benchmarkOnlyBaselines"], summary)
            refused("baseline_stopped_decision_refused", check, summary, document, proof)
    assert base["eventState"] == "TECHNICAL_DECISION_RECORDED"

def test_listed_compositions_scope_is_disabled():
    """Convergence review P1-B: listing gated compositions by free-text id is disabled."""
    entry = bob()
    entry["benchmarkBaseline"]["compositions"][0]["gateScope"] = "listed-compositions"
    refused("gate_scope_listed_compositions_disabled", validate_ledger, m3_ledger(entry))
    entry["benchmarkBaseline"]["compositions"][0]["gatedCompositionIds"] = ["C-A-EST"]
    with pytest.raises(CredibilityError):
        validate_ledger(m3_ledger(entry))
    assert bs.GATE_SCOPES == ("all-ordinary-compositions",)


def test_renamed_composition_cannot_escape_the_gate_or_coexist_with_its_original():
    """The reviewer's rename probe: C-A-EST renamed C-Z-EST with the same components. Every ordinary composition is
    gated, so dropping the gate is refused; a renamed duplicate beside its original is refused too."""
    document = m3_ledger()
    proof = evidence(document)
    summary = m3_decision(document, proof)
    block_ = summary["benchmarkOnlyBaselines"]
    gated = next(c for c in block_["compositionCandidates"] if c["compositionId"] == "C-A-EST")
    renamed = copy.deepcopy(gated)
    renamed.update(compositionId="C-Z-EST", gates={}, baselineSealSha256s={})
    escaped = copy.deepcopy(summary)
    escaped["benchmarkOnlyBaselines"].update(compositionCandidates=[renamed], rankedCompositions=["C-Z-EST"],
                                             strongestEvaluatedComposition="C-Z-EST", frontier=["C-Z-EST"])
    refused("composition_hard_gate_mapping_invalid", check, escaped, document, proof)
    failed = copy.deepcopy(gated)
    failed.update(gates={GATE: "failed"}, technicalGates="failed", comparativeScore=None)
    duplicate = copy.deepcopy(gated)
    duplicate["compositionId"] = "C-Z-EST"
    both = copy.deepcopy(summary)
    both["benchmarkOnlyBaselines"].update(compositionCandidates=[failed, duplicate], rankedCompositions=["C-Z-EST"],
                                          strongestEvaluatedComposition="C-Z-EST", frontier=["C-Z-EST"])
    refused("composition_components_duplicate", check, both, document, proof)


# ------------------------------------------------------------------ final round, item 4: full reachable-history audit


def staged_repo(repo):
    """Commit C0: both events frozen, no Layer-A result and no seal yet. Returns the saved seal artefacts."""
    document, partner, seal, folder = build_repository(repo, with_decision=False)
    seal_p, la_p, record = bs.seal_path(repo, document, GATE), bs.layer_a_path(repo, document, GATE), folder / f"{EVENT}.md"
    saved = (seal_p.read_bytes(), la_p.read_bytes(), record.read_bytes())
    citation = (bs.seal_citation(GATE, document_sha256(seal)) + NL).encode()
    seal_p.unlink()
    la_p.unlink()
    record.write_bytes(saved[2].replace(citation, b""))
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "C0 freeze")
    return document, partner, seal, folder, (seal_p, la_p, record), saved, citation


def commit_manifest(repo, document, folder, run, binding):
    manifest = bs.d_manifest_document(document, run, sha(f"d-{run}"), [binding])
    path = folder / f"{EVENT}{bs.D_MANIFEST_INFIX}{run}.json"
    write(path, canonical_json(manifest).decode())
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"D {run}")
    return path


def test_history_merge_branch_reseal_is_refused(tmp_path):
    """Reviewer chrono.py merge_reseal_attack: PD-A sealed and D bound on main; PD-B resealed with its own D on a side
    branch from C0; a merge takes the side's seal and drops the PD-A manifest."""
    repo = tmp_path / "merge"
    document, partner, seal, folder, (seal_p, la_p, record), saved, citation = staged_repo(repo)
    main = git(repo, "branch", "--show-current")
    git(repo, "branch", "side")
    seal_p.write_bytes(saved[0])
    la_p.write_bytes(saved[1])
    record.write_bytes(saved[2])
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "C1 seal PD-A")
    commit_manifest(repo, document, folder, "RUN-1", bs.require_committed_baseline_seal(repo, EVENT, "vehicle-colour", GATE))
    validate_repository(repo)
    git(repo, "checkout", "-q", "side")
    forged = layer_a(document, partner, ranks={"PD-A": [False, -0.5, "PD-A"], "PD-B": [False, -0.8, "PD-B"]})
    protocol_sha = lf_normalised_sha256(folder / f"{EVENT}-protocol.md")
    reseal = bs.derive_baseline_seal(document, GATE, protocol_sha256=protocol_sha, partner_ledger=partner,
                                     layer_a=forged, recorded_at="2026-07-03T10:00:00Z", recorded_by="later")
    write(la_p, canonical_json(forged).decode())
    write(seal_p, canonical_json(reseal).decode())
    new_citation = (bs.seal_citation(GATE, document_sha256(reseal)) + NL).encode()
    record.write_bytes(saved[2].replace(citation, new_citation))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "X reseal PD-B")
    commit_manifest(repo, document, folder, "RUN-2", bs.require_committed_baseline_seal(repo, EVENT, "vehicle-colour", GATE))
    git(repo, "checkout", "-q", main)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid", "merge", "-q",
                    "--no-ff", "--no-commit", "-X", "theirs", "side"], capture_output=True, check=False)
    seal_p.write_bytes(canonical_json(reseal))
    la_p.write_bytes(canonical_json(forged))
    record.write_bytes(saved[2].replace(citation, new_citation))
    git(repo, "rm", "-q", "-f", str(folder / f"{EVENT}{bs.D_MANIFEST_INFIX}RUN-1.json"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "merge side (PD-B wins)")
    assert bs.read_canonical(seal_p, "x")["partnerCandidateId"] == "PD-B"
    with pytest.raises(CredibilityError) as error:
        validate_repository(repo)
    assert str(error.value).split(":")[0] in ("baseline_artefact_rewritten_in_history",
                                              "baseline_artefact_deleted_in_history"), str(error.value)


def test_history_deleted_d_manifest_is_refused(tmp_path):
    repo, document, partner, seal, folder, manifest, path = seal_then_d(tmp_path, "deleted")
    git(repo, "rm", "-q", str(path))
    git(repo, "commit", "-q", "-m", "drop D manifest")
    refused("baseline_artefact_deleted_in_history", validate_repository, repo)


def test_history_deleted_layer_a_then_fabricated_stop_is_refused(tmp_path):
    """Reviewer chrono2.py: a committed resolvable Layer-A result deleted, then a STOPPED 'no Layer-A' seal."""
    repo = tmp_path / "fab"
    document, partner, seal, folder, (seal_p, la_p, record), saved, citation = staged_repo(repo)
    la_p.write_bytes(saved[1])
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "Layer-A result")
    validate_repository(repo)
    git(repo, "rm", "-q", str(la_p))
    git(repo, "commit", "-q", "-m", "drop Layer-A")
    protocol_sha = lf_normalised_sha256(folder / f"{EVENT}-protocol.md")
    stop = bs.derive_baseline_seal(document, GATE, protocol_sha256=protocol_sha, partner_ledger=partner, layer_a=None,
                                   recorded_at="2026-07-03T10:00:00Z", recorded_by="x")
    assert stop["status"] == "STOPPED"
    write(seal_p, canonical_json(stop).decode())
    record.write_bytes(record.read_bytes() + (bs.seal_citation(GATE, document_sha256(stop)) + NL).encode())
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "STOPPED: no Layer-A")
    refused("baseline_artefact_deleted_in_history", validate_repository, repo)


def test_history_delete_and_recreate_is_refused(tmp_path):
    repo, document, partner, seal, folder, manifest, path = seal_then_d(tmp_path, "recreate")
    seal_p = bs.seal_path(repo, document, GATE)
    data = seal_p.read_bytes()
    git(repo, "rm", "-q", str(seal_p))
    git(repo, "commit", "-q", "-m", "delete seal")
    seal_p.write_bytes(data)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "re-create the same seal")
    refused("baseline_artefact_deleted_in_history", validate_repository, repo)


def test_history_seal_rewritten_inside_a_merge_is_refused(tmp_path):
    repo, document, partner, seal, folder, manifest, path = seal_then_d(tmp_path, "evil")
    main = git(repo, "branch", "--show-current")
    git(repo, "checkout", "-q", "-b", "side")
    git(repo, "commit", "-q", "--allow-empty", "-m", "side")
    git(repo, "checkout", "-q", main)
    git(repo, "commit", "-q", "--allow-empty", "-m", "main")
    git(repo, "merge", "-q", "--no-ff", "--no-commit", "side")
    changed = dict(seal, recordedBy="someone else")
    write(bs.seal_path(repo, document, GATE), canonical_json(changed).decode())
    record = folder / f"{EVENT}.md"
    write(record, record.read_text().replace(document_sha256(seal), document_sha256(changed)))
    for item in folder.glob(f"{EVENT}{bs.D_MANIFEST_INFIX}*.json"):
        bound = json.loads(item.read_text())
        bound["baselineSeals"][0]["sealSha256"] = document_sha256(changed)
        write(item, canonical_json(bound).decode())
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "evil merge rewrites the seal, record and D manifest")
    with pytest.raises(CredibilityError) as error:
        validate_repository(repo)
    assert str(error.value).split(":")[0] in ("baseline_artefact_rewritten_in_history",
                                              "d_artefact_seal_commit_mismatch"), str(error.value)


def test_history_d_manifest_added_inside_a_merge_is_found(tmp_path):
    """A D manifest first added by a merge commit: its add is found (no history simplification) and the seal commit
    must be a strict ancestor of that merge."""
    repo = tmp_path / "merge-add"
    document, partner, seal, folder, (seal_p, la_p, record), saved, citation = staged_repo(repo)
    main = git(repo, "branch", "--show-current")
    git(repo, "checkout", "-q", "-b", "side")
    seal_p.write_bytes(saved[0])
    la_p.write_bytes(saved[1])
    record.write_bytes(saved[2])
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "S seal")
    binding = bs.require_committed_baseline_seal(repo, EVENT, "vehicle-colour", GATE)
    git(repo, "checkout", "-q", main)
    git(repo, "commit", "-q", "--allow-empty", "-m", "main work")
    git(repo, "merge", "-q", "--no-ff", "--no-commit", "side")
    manifest = bs.d_manifest_document(document, "RUN-1", sha("d"), [binding])
    manifest_path = folder / f"{EVENT}{bs.D_MANIFEST_INFIX}RUN-1.json"
    write(manifest_path, canonical_json(manifest).decode())
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "merge adds the D manifest")
    merge = git(repo, "rev-parse", "HEAD")
    history = bs.artefact_history(repo, folder.relative_to(repo).as_posix())
    assert history["adds"][manifest_path.relative_to(repo).as_posix()] == {merge}
    validate_repository(repo)  # the side seal commit is a strict ancestor of the merge
    # the same merge citing a seal commit that is not its ancestor is refused
    repo2 = tmp_path / "merge-add-2"
    document, partner, seal, folder, (seal_p, la_p, record), saved, citation = staged_repo(repo2)
    main = git(repo2, "branch", "--show-current")
    git(repo2, "checkout", "-q", "-b", "side")
    seal_p.write_bytes(saved[0])
    la_p.write_bytes(saved[1])
    record.write_bytes(saved[2])
    git(repo2, "add", "-A")
    git(repo2, "commit", "-q", "-m", "S seal")
    git(repo2, "checkout", "-q", "-b", "other", "HEAD~1")
    seal_p.write_bytes(saved[0])
    la_p.write_bytes(saved[1])
    record.write_bytes(saved[2])
    git(repo2, "add", "-A")
    git(repo2, "commit", "-q", "-m", "same seal on an unrelated branch")
    stray = git(repo2, "rev-parse", "HEAD")
    git(repo2, "checkout", "-q", main)
    git(repo2, "merge", "-q", "--no-ff", "--no-commit", "side")
    manifest = bs.d_manifest_document(document, "RUN-1", sha("d"),
                                      [bs.SealBinding(GATE, document_sha256(seal), stray, "PD-A", identity_of("pda"),
                                                      sha("c"))])
    write(folder / f"{EVENT}{bs.D_MANIFEST_INFIX}RUN-1.json", canonical_json(manifest).decode())
    git(repo2, "add", "-A")
    git(repo2, "commit", "-q", "-m", "merge adds a D manifest citing an unrelated commit")
    refused("d_artefact_seal_commit_not_ancestral", validate_repository, repo2)
