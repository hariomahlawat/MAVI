"""Method revision M3: benchmark-only baseline, composition group and group authority (PR #220 authority redesign).

Synthetic fixtures only (model_selection_fixtures.py). Every name, hash and date is invented. The group is two
component events: the recogniser ``msr-vehicle-colour-2026-01`` (holds the benchmark-only baseline VC-BOB) and the
detector ``msr-plate-detector-2026-01`` (holds the partner PD_BASE). Git-backed tests build real temporary
repositories; nothing here calls the network or the GitHub API (the anchor remote is a local bare repository and the
ruleset API is an injected fake).
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from fractions import Fraction
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from model_selection import baseline_seal as bs
from model_selection import m3_authority as ma
from model_selection import m3_git as mg
from model_selection import m3_universe as mu
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
PARTNER_PROTOCOL = sha("partner-protocol")
SEALED_AT = "2026-07-01T10:00:00Z"
D_STARTED = "2026-07-02T09:00:00Z"
PD_GATES = ["contract", "recall-floor"]
VC_GATES = ["contract"]
S0 = "c" * 40
ANCHOR = "a" * 40
MPID = 0.02
BASE_D = 0.5
D_SCORES = {"C-PD-A--VC-EMG": 0.9, "C-PD-B--VC-EMG": 0.85, "C-PD-A--VC-EST": 0.7, "C-PD-B--VC-EST": 0.6,
            "C-PD-A--VC-B0": 0.3, "C-PD-B--VC-B0": 0.2}
PD_METRICS = {"PD-A": {"recall": 0.9}, "PD-B": {"recall": 0.8}}
VC_METRICS = {"VC-B0": {"cer": 0.5, "em": 0.2}, "VC-EST": {"cer": 0.2, "em": 0.7}, "VC-EMG": {"cer": 0.1, "em": 0.9}}


def refused(code, function, *args, **kwargs):
    with pytest.raises(CredibilityError) as error:
        function(*args, **kwargs)
    assert str(error.value).split(":")[0] == code, str(error.value)


def code_of(function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except CredibilityError as error:
        return str(error).split(":")[0]
    return "accepted"


def identity_of(label):
    return document_sha256(checkpoint_identity(label))


def universe(**changes):
    block = {
        "componentEvents": [
            {"eventId": PARTNER_EVENT, "subTask": "T-VC", "rankingLayer": "A", "k": 3, "rankingGateIds": list(PD_GATES),
             "rankingRule": {"rule": "lexicographic-v1", "keys": [{"metric": "recall", "direction": "max"}]}},
            {"eventId": EVENT, "subTask": "T-VC", "rankingLayer": "B", "k": 3, "rankingGateIds": list(VC_GATES),
             "rankingRule": {"rule": "lexicographic-v1", "keys": [{"metric": "em", "direction": "max"},
                                                                  {"metric": "cer", "direction": "min"}]}},
        ],
        "compositionGateIds": ["baseline", "consistent-wrong"],
        "mpid": MPID,
        "includePackageableBaselines": True,
    }
    block.update(changes)
    return block


def as_m3(document, block=None):
    document["methodRevision"] = "msr-v1-m3"
    document["compositionUniverse"] = universe() if block is None else block
    return document


def partner_ledger(*entries, block=None):
    document = ledger(*(entries or (established("PD-A", "pda"), established("PD-B", "pdb"))),
                      capability="plate-detector")
    return as_m3(document, block)


def partners():
    return [{"candidateId": "PD-A", "identitySha256": identity_of("pda")},
            {"candidateId": "PD-B", "identitySha256": identity_of("pdb")}]


def stage1(**changes):
    rule = {"compositionId": GATE, "partnerEventId": PARTNER_EVENT, "eligiblePartners": partners(),
            "excludedPartners": [], "derivationRule": bs.DERIVATION_RULE, "gateScope": bs.GATE_SCOPE_ALL}
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


def m3_ledger(*entries, revision="msr-v1-m3", capability="vehicle-colour", block_=None):
    document = ledger(*(entries or (baseline(), established(), emerging(), bob())), capability=capability)
    document["methodRevision"] = revision
    if revision == "msr-v1-m3":
        document["compositionUniverse"] = universe() if block_ is None else block_
    return document


def plain_ledger():
    """An M1 event with the same ordinary candidates and no M3 role."""
    return ledger(baseline(), established(), emerging(), capability="vehicle-colour")


def ranking(frozen, metrics=None, gates=None):
    item = mu.component_event(frozen["compositionUniverse"], frozen["eventId"])
    metrics = metrics or (PD_METRICS if frozen["eventId"] == PARTNER_EVENT else VC_METRICS)
    default = {"recall": 0.1} if frozen["eventId"] == PARTNER_EVENT else {"cer": 0.9, "em": 0.1}
    gates = gates or {}
    identities = mu.shortlist_identities(frozen)
    rows = [{"candidateId": c, "identitySha256": identities[c],
             "gates": copy.deepcopy(gates.get(c)) or {g: "passed" for g in item["rankingGateIds"]},
             "metrics": copy.deepcopy(metrics.get(c, default)), "measurementSha256": sha(f"measurement-{c}")} for c in sorted(identities)]
    return mu.component_ranking_document(frozen, rows, sha(f"raw-{frozen['eventId']}"))


def all_failed(frozen):
    item = mu.component_event(frozen["compositionUniverse"], frozen["eventId"])
    return {c: {g: "failed" for g in item["rankingGateIds"]} for c in mu.shortlist_identities(frozen)}


def rankings_of(document, partner, *, own=None, other=None):
    return {EVENT: ranking(document) if own is None else own,
            PARTNER_EVENT: ranking(partner) if other is None else other}


def derive(document, partner, rankings, **kwargs):
    return bs.derive_baseline_seal(document, GATE, protocol_sha256=kwargs.pop("protocol", PROTOCOL),
                                   partner_ledger=partner, rankings=rankings, recorded_at=SEALED_AT,
                                   recorded_by="synthetic-harness", **kwargs)


def group(document=None, partner=None, rankings=None, seal="derive", s0=S0):
    document = m3_ledger() if document is None else document
    partner = partner_ledger() if partner is None else partner
    rankings = rankings_of(document, partner) if rankings is None else rankings
    if seal == "derive":
        seal = derive(document, partner, rankings)
    return ma.derive_group_state({EVENT: document, PARTNER_EVENT: partner}, {EVENT: PROTOCOL, PARTNER_EVENT: PARTNER_PROTOCOL},
                                 rankings, seal, s0=s0)


def as_fraction(value):
    """M3 Amendment A1: a D score as its exact rational (a float literal is read as written, ``0.9`` -> 9/10)."""
    if value is None or isinstance(value, Fraction):
        return value
    return Fraction(Decimal(str(value)))


def exact_of(value):
    value = as_fraction(value)
    return None if value is None else {"numerator": value.numerator, "denominator": value.denominator}


def display_of(value):
    value = as_fraction(value)
    return None if value is None else float(value)


def authority_block(state, *, scores=None, base=BASE_D, anchor=ANCHOR, implementation="C-PD-A--VC-EST",
                    mpid=MPID):
    """A consistent ``compositionAuthority`` block: exact ``dScoreExact`` (M3-A1) with ``dScore`` its float display."""
    scores = D_SCORES if scores is None else scores
    rows, passing = [], {}
    for item in state.ordinary:
        cid = item["compositionId"]
        score = as_fraction(scores.get(cid))
        baseline_passed = score is not None and base is not None and \
            score - as_fraction(base) >= as_fraction(mpid)
        gates = {"baseline": "passed" if baseline_passed else "failed", "consistent-wrong": "passed"}
        technical = "passed" if all(v == "passed" for v in gates.values()) else "failed"
        if technical == "passed":
            passing[cid] = score
        rows.append({"compositionId": cid, "components": copy.deepcopy(item["components"]), "gates": gates,
                     "dScore": display_of(score), "dScoreExact": exact_of(score), "technicalGates": technical,
                     "comparativeScore": display_of(score) if technical == "passed" else None,
                     "dResultSha256": sha(f"d-{cid}"), "baselineSealSha256s": {GATE: state.seal_sha256}})
    ranked = sorted(passing, key=lambda c: (-passing[c], c))
    finalists = {e: sorted({c["candidateId"] for comp in ranked for c in
                            next(i for i in state.ordinary if i["compositionId"] == comp)["components"]
                            if c["eventId"] == e}) for e in (PARTNER_EVENT, EVENT)}
    return {"groupId": state.group_id, "anchorCommit": anchor,
            "baselineSeals": [{"compositionId": GATE, "sealSha256": state.seal_sha256, "status": "RESOLVED",
                               "sealCommit": state.s0}],
            "dExecutionStartedAt": D_STARTED, "incumbent": None,
            "baseline": {"compositionId": GATE, "compositionSha256": state.seal["compositionSha256"],
                         "dScore": display_of(base), "dScoreExact": exact_of(base),
                         "dResultSha256": sha("d-baseline")},
            "topK": copy.deepcopy(state.top_k), "componentFinalists": finalists, "compositionCandidates": rows,
            "rankedCompositions": ranked, "frontier": ranked[:1],
            "strongestEvaluatedComposition": ranked[0] if ranked else None,
            "implementationComposition": implementation}


def bob_row(document, seal_sha):
    entry = next(e for e in document["candidates"] if e["candidateId"] == "VC-BOB")
    row = evaluated_row(entry, score=0.0)
    row.update(technicalGates="n/a", comparativeScore=None, taskQualityScore=None,
               hostManifestSha256s={p: document_sha256(m) for p, m in entry["benchmarkBaseline"]["hostManifests"].items()},
               baselineSealSha256s={GATE: seal_sha})
    return row


def apply_rows(summary, state, event_id):
    """Set every ordinary row to its composition-derived values (the exact projection, M3-A1, displayed as a float)
    and recompute the M1 derived fields from the exact projection."""
    block_ = summary["compositionAuthority"]
    passing = {r["compositionId"]: Fraction(r["dScoreExact"]["numerator"], r["dScoreExact"]["denominator"])
               for r in block_["compositionCandidates"] if r["technicalGates"] == "passed"}
    technical = {}
    for row in summary["evaluated"]:
        if row["technicalGates"] == "n/a":
            continue
        scores = [s for comp, s in passing.items() if any(
            c["eventId"] == event_id and c["candidateId"] == row["candidateId"]
            for c in next(r for r in block_["compositionCandidates"] if r["compositionId"] == comp)["components"])]
        row.update(technicalGates="passed" if scores else "failed",
                   comparativeScore=float(max(scores)) if scores else None)
        if scores:
            technical[row["candidateId"]] = max(scores)
    best = min(technical, key=lambda c: (-technical[c], c)) if technical else None
    summary["strongestEvaluatedTechnical"] = best
    summary["strongestClearedPerProfile"] = {p: best for p in summary["targetProfiles"]}
    return summary


def group_decision(state, event_id=EVENT, *, block_=None, state_name="QUALIFICATION_PENDING", implementation="default"):
    document = state.frozen_by_event[event_id]
    if event_id == EVENT:
        components = ("VC-EST",) if implementation == "default" else implementation
        summary = decision(document, state=state_name, implementation=components)
        summary["evaluated"].append(bob_row(document, state.seal_sha256))
    else:
        components = ("PD-A",) if implementation == "default" else implementation
        summary = decision(document, scores={"PD-A": 0.9, "PD-B": 0.85}, state=state_name, implementation=components)
        summary["strongestReported"] = {"candidateId": "PD-A", "claimId": "C1",
                                        "label": summary["strongestReported"]["label"]}
    summary["protocolSha256"] = state.protocol_by_event[event_id]
    if components is None and block_ is None:
        block_ = authority_block(state, implementation=None)
    summary["compositionAuthority"] = authority_block(state) if block_ is None else block_
    return apply_rows(summary, state, event_id)


def check(summary, state, event_id=EVENT):
    document = state.frozen_by_event[event_id]
    validate_decision(summary, document, document, group=state)


# ================================================================== ledger: BOB, universe, P3, R1


def test_benchmark_baseline_is_accepted_measured_sealed_and_never_ranked():
    document = m3_ledger()
    summary = validate_ledger(document)
    assert summary["VC-BOB"] == {"class": "reference-only", "provenanceConfidence": "High",
                                 "disposition": "BENCHMARK_BASELINE"}
    state = group(document)
    assert state.seal["status"] == "RESOLVED" and state.seal["partnerCandidateId"] == "PD-A"
    assert [i["compositionId"] for i in state.ordinary] == sorted(D_SCORES)
    assert all("VC-BOB" not in json.dumps(i) for i in state.ordinary)
    check(group_decision(state), state)
    check(group_decision(state, PARTNER_EVENT), state, PARTNER_EVENT)


def test_m3_requires_the_group_universe_and_m1_m2_refuse_it():
    document = m3_ledger()
    del document["compositionUniverse"]
    refused("m3_requires_composition_universe", validate_ledger, document)
    refused("composition_universe_requires_m3", validate_ledger, as_m3(plain_ledger()) | {"methodRevision": "msr-v1-m1"})
    m1 = plain_ledger()
    m1["supersedes"] = {"eventId": "msr-vehicle-colour-2025-01", "frozenLedgerSha256": sha("x"),
                        "stoppedSealSha256s": [sha("s")]}
    refused("composition_universe_requires_m3", validate_ledger, m1)  # O6: a superseding event stays M3
    validate_ledger(partner_ledger())  # a group member without a BOB


@pytest.mark.parametrize("mutate, code", [
    (lambda u: u.update(componentEvents=u["componentEvents"][:1]), "composition_universe_events_invalid"),
    (lambda u: u["componentEvents"].reverse(), "composition_universe_events_invalid"),
    (lambda u: u["componentEvents"].append(copy.deepcopy(u["componentEvents"][0]) | {"eventId": "msr-zz-2026-01"}),
     "composition_universe_events_invalid"),
    (lambda u: u["componentEvents"][1].update(k=0), "composition_universe_k_invalid"),
    (lambda u: u["componentEvents"][1].update(k=True), "composition_universe_k_invalid"),
    (lambda u: u["componentEvents"][0].update(rankingGateIds=["z", "a"]), "ranking_gates_not_sorted_unique"),
    (lambda u: u["componentEvents"][0]["rankingRule"].update(rule="owner-preference"), "value_not_allowed"),
    (lambda u: u["componentEvents"][0]["rankingRule"].update(keys=[]), "ranking_rule_keys_invalid"),
    (lambda u: u["componentEvents"][1]["rankingRule"]["keys"].append({"metric": "em", "direction": "min"}),
     "ranking_rule_keys_invalid"),
    (lambda u: u["componentEvents"][1]["rankingRule"]["keys"][0].update(direction="up"), "value_not_allowed"),
    (lambda u: u["componentEvents"][1].update(subTask="T-PD"), "composition_universe_subtask_outside_event"),
    (lambda u: u["componentEvents"][1].update(eventId="msr-vehicle-colour-2026-02"),
     "composition_universe_excludes_own_event"),
    (lambda u: u.update(compositionGateIds=["consistent-wrong"]), "composition_gates_invalid"),
    (lambda u: u.update(compositionGateIds=["consistent-wrong", "baseline"]), "composition_gates_invalid"),
    (lambda u: u.update(mpid=-0.1), "composition_universe_mpid_invalid"),
    (lambda u: u.update(mpid="0.02"), "number_required"),
    (lambda u: u.update(includePackageableBaselines=False), "composition_universe_must_include_packageable_baselines"),
    (lambda u: u.update(extra=1), "unknown_field"),
])
def test_composition_universe_is_a_closed_machine_block(mutate, code):
    block_ = universe()
    mutate(block_)
    refused(code, validate_ledger, m3_ledger(block_=block_))


def test_bob_partner_is_the_other_group_member_and_one_baseline_per_group():
    entry = bob()
    entry["benchmarkBaseline"]["compositions"][0]["partnerEventId"] = EVENT
    refused("baseline_partner_event_not_in_group", validate_ledger, m3_ledger(baseline(), established(), entry))
    entry = bob()
    entry["benchmarkBaseline"]["compositions"][0]["partnerEventId"] = "msr-plate-finder-2026-01"
    refused("baseline_partner_event_not_in_group", validate_ledger, m3_ledger(baseline(), established(), entry))
    two = bob()
    second = copy.deepcopy(two["benchmarkBaseline"]["compositions"][0])
    second["compositionId"] = "GATE-TWO"
    two["benchmarkBaseline"]["compositions"].append(second)
    refused("composition_universe_requires_one_baseline", validate_ledger, m3_ledger(baseline(), established(), two))
    other = bob("VC-BOB2", "bob2")
    other["benchmarkBaseline"]["compositions"][0]["compositionId"] = "GATE-TWO"
    for item in other["benchmarkBaseline"]["hostManifests"]["dev-profile"]:
        if item["kind"] == "data":
            item["sha256"] = sha("weights-bob2")
    other["benchmarkBaseline"]["evaluationPermissions"][1]["sha256s"] = [sha("weights-bob2")]
    refused("composition_universe_requires_one_baseline", validate_ledger,
            m3_ledger(baseline(), established(), bob(), other))
    # a second BOB in the partner event: the group holds two baselines
    partner_bob = bob("PD-BOB", "pdbob")
    partner_bob["benchmarkBaseline"]["compositions"][0].update(compositionId="GATE-P", partnerEventId=EVENT,
                                                               eligiblePartners=[
                                                                   {"candidateId": "VC-EMG", "identitySha256": identity_of("emg")},
                                                                   {"candidateId": "VC-EST", "identitySha256": identity_of("est")}],
                                                               excludedPartners=[{"candidateId": "VC-B0", "identitySha256": document_sha256(
                                                                   {"repository": "MAVI", "revision": "UNKNOWN"}), "reason": "not a recogniser"}])
    for item in partner_bob["benchmarkBaseline"]["hostManifests"]["dev-profile"]:
        if item["kind"] == "data":
            item["sha256"] = sha("weights-pdbob")
    partner_bob["benchmarkBaseline"]["evaluationPermissions"][1]["sha256s"] = [sha("weights-pdbob")]
    two_groups = partner_ledger(established("PD-A", "pda"), established("PD-B", "pdb"), partner_bob)
    validate_ledger(two_groups)
    refused("composition_universe_requires_one_baseline", group, partner=two_groups, seal=None)


@pytest.mark.parametrize("make", [established, lambda: emerging(shortlisted=False), excluded, baseline])
def test_benchmark_baseline_is_refused_for_every_class_but_reference_only(make):
    refused("benchmark_baseline_class", validate_ledger, m3_ledger(bob(entry=make())))


def test_reference_only_role_requires_m3_ledger_and_v1_scope():
    refused("benchmark_baseline_requires_m3", validate_ledger, m3_ledger(revision="msr-v1-m1"))
    refused("m2_scope_unsupported", validate_ledger, m3_ledger(revision="msr-v1-m2"))
    refused("benchmark_baseline_requires_m3", validate_ledger,
            m3_ledger(revision="msr-v1-m2", capability="vehicle-attributes"))
    refused("m3_scope_unsupported", validate_ledger, m3_ledger(capability="vehicle-attributes"))


def test_bob_requires_high_provenance_manifests_and_stage1_rule():
    unpinned = bob()
    unpinned["identity"]["files"][0]["sha256"] = "UNKNOWN"
    refused("benchmark_baseline_requires_pinned_provenance", validate_ledger, m3_ledger(unpinned))
    refused("benchmark_baseline_requires_pinned_provenance", validate_ledger, m3_ledger(bob(entry=reference())))
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
        (lambda b: b["compositions"][0].pop("gateScope"), "missing_field"),
        (lambda b: b["compositions"][0].update(partnerEventId="msr-x"), "malformed"),
        (lambda b: b["compositions"][0].update(partnerRankingRuleSha256=sha("opaque")), "unknown_field"),
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
    none = bob()
    none["benchmarkBaseline"]["compositions"] = []
    refused("benchmark_baseline_without_gate", validate_ledger, m3_ledger(none))  # cold review P3-6


def test_evaluation_permission_is_bound_per_exact_artefact():
    vague = [{"artefact": "all", "decidedBy": "x", "decidedOn": RECORDED, "primarySourceSha256": sha("p")}]
    for mutate, code in (
        (lambda b: b.update(evaluationPermissions=vague), "missing_field"),
        (lambda b: b.update(evaluationPermissions=[]), "benchmark_baseline_permission_required"),
        (lambda b: b["evaluationPermissions"].pop(1), "benchmark_baseline_permission_required"),
        (lambda b: b["evaluationPermissions"].pop(0), "benchmark_baseline_permission_required"),
        (lambda b: b["evaluationPermissions"].pop(2), "benchmark_baseline_permission_required"),
        (lambda b: b["evaluationPermissions"][0].update(sha256s=sorted([sha("exe"), sha("weights-bob")])),
         "benchmark_baseline_permission_not_bound"),
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
        (lambda b: b["hostManifests"]["dev-profile"].insert(0, {"path": "a/unpermitted.dll", "kind": "runtime-library",
                                                                 "sha256": sha("new"), "size": 1}),
         "benchmark_baseline_permission_not_bound"),
    ):
        entry = bob()
        mutate(entry["benchmarkBaseline"])
        refused(code, validate_ledger, m3_ledger(entry))


# ---- probe_manifest (cold review): every probe is a permanent test


def _bob_with(mutate):
    entry = bob()
    mutate(entry)
    return m3_ledger(baseline(), established(), emerging(), entry)


def test_probe_manifest_profile_without_executable_is_refused():
    def second_profile_without_executable(b):
        b["benchmarkBaseline"]["hostManifests"]["prod-profile"] = [
            {"path": "share/model.bin", "kind": "data", "sha256": sha("weights-bob"), "size": 30}]
    refused("benchmark_baseline_profile_without_executable", validate_ledger, _bob_with(second_profile_without_executable))


def test_probe_manifest_pinned_model_absent_from_a_host_manifest_is_refused():
    def model_not_in_manifest(b):
        manifest = b["benchmarkBaseline"]["hostManifests"]["dev-profile"]
        b["benchmarkBaseline"]["hostManifests"]["dev-profile"] = [f for f in manifest if f["kind"] != "data"]
    refused("benchmark_baseline_identity_file_not_in_manifest", validate_ledger, _bob_with(model_not_in_manifest))


def test_probe_manifest_pinned_identity_file_retyped_is_refused():
    def pinned_model_retyped_as_executable(b):
        manifest = b["benchmarkBaseline"]["hostManifests"]["dev-profile"]
        for f in manifest:
            if f["kind"] == "data":
                f["kind"] = "executable"
        perms = {p["artefactKind"]: p for p in b["benchmarkBaseline"]["evaluationPermissions"]}
        perms["executable"]["sha256s"] = sorted({f["sha256"] for f in manifest if f["kind"] == "executable"})
    refused("benchmark_baseline_identity_file_not_data", validate_ledger, _bob_with(pinned_model_retyped_as_executable))


def test_probe_manifest_same_bytes_under_two_kinds_is_refused():
    def same_hash_two_kinds(b):
        manifest = b["benchmarkBaseline"]["hostManifests"]["dev-profile"]
        manifest.append({"path": "share/zz.bin", "kind": "data", "sha256": sha("exe"), "size": 10})
        perms = {p["artefactKind"]: p for p in b["benchmarkBaseline"]["evaluationPermissions"]}
        perms["model-data"]["sha256s"] = sorted({*perms["model-data"]["sha256s"], sha("exe")})
    refused("benchmark_baseline_hash_kind_conflict", validate_ledger, _bob_with(same_hash_two_kinds))
    def across_profiles(b):
        b["benchmarkBaseline"]["hostManifests"]["prod-profile"] = [
            {"path": "bin/tool.exe", "kind": "runtime-library", "sha256": sha("exe"), "size": 10},
            {"path": "bin/x.exe", "kind": "executable", "sha256": sha("x-exe"), "size": 10},
            {"path": "share/model.bin", "kind": "data", "sha256": sha("weights-bob"), "size": 30}]
    refused("benchmark_baseline_hash_kind_conflict", validate_ledger, _bob_with(across_profiles))


def test_probe_manifest_runtime_library_retyped_executable_is_the_declared_residual():
    """O7 residual: semantic misclassification inside the BOB's OWN manifest stays a reviewer item."""
    def dll_under_executable(b):
        manifest = b["benchmarkBaseline"]["hostManifests"]["dev-profile"]
        for f in manifest:
            if f["kind"] == "runtime-library":
                f["kind"] = "executable"
        perms = b["benchmarkBaseline"]["evaluationPermissions"]
        b["benchmarkBaseline"]["evaluationPermissions"] = [p for p in perms if p["artefactKind"] != "runtime-libraries"]
        for p in b["benchmarkBaseline"]["evaluationPermissions"]:
            if p["artefactKind"] == "executable":
                p["sha256s"] = sorted({sha("exe"), sha("dll")})
    validate_ledger(_bob_with(dll_under_executable))


# ---- R1 / owner decision O7: BOB payload bytes are forbidden in every ordinary candidate


def _ordinary_pinning(file_hash, label="clone"):
    entry = emerging("VC-CLN", label)
    entry["identity"]["files"].append({"path": "extra/file.bin", "sha256": file_hash})
    return entry


def bob_with_vocabulary():
    entry = bob()
    entry["benchmarkBaseline"]["hostManifests"]["dev-profile"].append(
        {"path": "share/vocab.bin", "kind": "data", "sha256": sha("vocab"), "size": 5})
    entry["benchmarkBaseline"]["evaluationPermissions"][1]["sha256s"] = sorted([sha("weights-bob"), sha("vocab")])
    return entry


@pytest.mark.parametrize("payload", ["exe", "vocab"])
def test_ordinary_candidate_pinning_a_bob_payload_file_is_refused_whatever_its_kind(payload):
    document = m3_ledger(baseline(), established(), emerging(), _ordinary_pinning(sha(payload)), bob_with_vocabulary())
    refused("benchmark_baseline_bytes_in_ordinary_candidate", validate_ledger, document)
    # the BOB's pinned identity file is refused too (already by the M1 one-entry-per-checkpoint rule)
    assert code_of(validate_ledger, m3_ledger(baseline(), established(), emerging(),
                                              _ordinary_pinning(sha("weights-bob")), bob())) != "accepted"


def test_ordinary_candidate_may_share_a_bob_runtime_library():
    validate_ledger(m3_ledger(baseline(), established(), emerging(), _ordinary_pinning(sha("dll")), bob()))


def test_relabelling_a_bob_executable_as_a_runtime_library_in_an_ordinary_candidate_is_no_bypass():
    """Ordinary candidates carry no kind: every one of their files is compared with every BOB payload hash."""
    clone = _ordinary_pinning(sha("exe"))
    clone["identity"]["files"][-1]["path"] = "lib/runtime-library-really.dll"
    refused("benchmark_baseline_bytes_in_ordinary_candidate", validate_ledger,
            m3_ledger(baseline(), established(), emerging(), clone, bob()))


def test_partner_event_candidate_pinning_bob_bytes_is_refused_by_the_group():
    twin = established("PD-TESS", "bob")  # the BOB weights under another identity in the partner event
    twin["identity"]["tag"] = "v1.0-mirror"
    partner = partner_ledger(established("PD-A", "pda"), established("PD-B", "pdb"), twin)
    rule_doc = m3_ledger()
    rule = rule_doc["candidates"][-1]["benchmarkBaseline"]["compositions"][0]
    rule["excludedPartners"] = [{"candidateId": "PD-TESS", "identitySha256": document_sha256(twin["identity"]),
                                 "reason": "not a release of interest"}]
    document = m3_ledger(*rule_doc["candidates"])
    refused("benchmark_baseline_bytes_in_ordinary_candidate", group, document, partner, seal=None)
    rule["eligiblePartners"] = sorted(partners() + [{"candidateId": "PD-TESS",
                                                     "identitySha256": document_sha256(twin["identity"])}],
                                      key=lambda p: p["candidateId"])
    rule["excludedPartners"] = []
    document = m3_ledger(*rule_doc["candidates"])
    refused("benchmark_baseline_bytes_as_partner", bs.check_partner_universe, rule, partner, "p",
            document["candidates"][-1])


# ---- immutability after freeze


def test_bob_set_identity_universe_and_composition_rule_are_fixed_after_freeze():
    frozen = m3_ledger()
    for mutate in (
        lambda e: e["benchmarkBaseline"]["hostManifests"]["dev-profile"][0].update(sha256=sha("swapped")) or
        e["benchmarkBaseline"]["evaluationPermissions"][0].update(sha256s=[sha("swapped")]),
        lambda e: e["benchmarkBaseline"].update(configurationSha256=sha("other configuration")),
        lambda e: e["benchmarkBaseline"].update(adapterSha256=sha("other adapter")),
        lambda e: e["benchmarkBaseline"]["compositions"][0]["eligiblePartners"].append(
            {"candidateId": "PD-C", "identitySha256": sha("PD-C")}),
        lambda e: e["benchmarkBaseline"]["evaluationPermissions"][0].update(decidedBy="someone else"),
        lambda e: e["disposition"].update(reason="changed after freeze"),
    ):
        later = copy.deepcopy(frozen)
        mutate(later["candidates"][-1])
        refused("frozen_benchmark_baseline_field_changed", validate_evolution, frozen, later)
    for field, value in (("compositionUniverse", universe(mpid=0.5)),
                         ("supersedes", {"eventId": "msr-vehicle-colour-2025-01", "frozenLedgerSha256": sha("x"),
                                         "stoppedSealSha256s": [sha("s")]})):
        later = copy.deepcopy(frozen)
        later[field] = value
        refused("frozen_ledger_scope_changed", validate_evolution, frozen, later)
    removed = copy.deepcopy(frozen)
    removed["candidates"][-1]["disposition"] = {"status": "REFERENCE_ONLY", "reasonClass": "credibility",
                                                "reason": "held", "revisitTrigger": "never", "decidedBy": "x"}
    del removed["candidates"][-1]["benchmarkBaseline"]
    refused("benchmark_baselines_changed_after_freeze", validate_evolution, frozen, removed)


def test_bob_cannot_promote_itself():
    document = m3_ledger()
    promoted = copy.deepcopy(document)
    promoted["candidates"][-1]["evidence"].append(
        {"evidenceId": "E-MAVI", "type": "independent-benchmark", "producer": {"group": "mavi-bakeoff",
         "relation": "independent"}, "source": "evidence-store:plates/run", "locator": "D", "retrievedOn": RECORDED,
         "retrievedSha256": sha("run"), "recordedAt": RECORDED, "summary": "MAVI bake-off D-score",
         "scope": "method", "independenceBasis": "MAVI", "subTask": "T-VC", "objectClass": "vehicle"})
    refused("mavi_evidence_in_ledger", validate_ledger, promoted)
    refused("benchmark_baseline_class", validate_ledger, m3_ledger(bob(entry=established("VC-BOB", "bob"))))


def test_listed_compositions_scope_is_disabled():
    entry = bob()
    entry["benchmarkBaseline"]["compositions"][0]["gateScope"] = "listed-compositions"
    refused("gate_scope_listed_compositions_disabled", validate_ledger, m3_ledger(entry))
    assert bs.GATE_SCOPES == ("all-ordinary-compositions",)


# ================================================================== component ranking, top-K and U (C1)


def test_rank_key_is_derived_from_metrics_by_the_frozen_rule():
    document = m3_ledger()
    result = mu.check_component_ranking(ranking(document), document)
    assert result["VC-EMG"]["key"] == (-0.9, 0.1) and result["VC-B0"]["key"] == (-0.2, 0.5)
    authored = ranking(document)
    authored["rows"][0]["rankKey"] = [0]
    refused("unknown_field", mu.check_component_ranking, authored, document)
    # changing a metric changes the order: no author key can be smuggled in
    swapped = ranking(document, metrics=dict(VC_METRICS, **{"VC-EST": {"cer": 0.0, "em": 0.95}}))
    assert mu.derive_top_k(mu.check_component_ranking(swapped, document), 1) == ["VC-EST"]


@pytest.mark.parametrize("mutate, code", [
    (lambda r: r["rows"][0].update(identitySha256=sha("retrained")), "component_ranking_identity_mismatch"),
    (lambda r: r["rows"][0].update(candidateId="VC-REF"), "component_ranking_candidate_not_shortlisted"),
    (lambda r: r["rows"][0].update(candidateId="VC-BOB"), "component_ranking_candidate_not_shortlisted"),
    (lambda r: r["rows"].pop(), "component_ranking_not_the_shortlist"),
    (lambda r: r["rows"].append(copy.deepcopy(r["rows"][0])), "component_ranking_not_the_shortlist"),
    (lambda r: r["rows"][0]["gates"].pop("contract"), "component_ranking_gates_mismatch"),
    (lambda r: r["rows"][0]["gates"].update(extra="passed"), "component_ranking_gates_mismatch"),
    (lambda r: r["rows"][0]["gates"].update(contract="maybe"), "value_not_allowed"),
    (lambda r: r["rows"][0]["metrics"].pop("em"), "component_ranking_metrics_mismatch"),
    (lambda r: r["rows"][0]["metrics"].update(extra=1.0), "component_ranking_metrics_mismatch"),
    (lambda r: r["rows"][0]["metrics"].update(em=float("inf")), "number_required"),
    (lambda r: r["rows"][0]["metrics"].update(em=True), "number_required"),
    (lambda r: r.update(rankingRuleSha256=sha("another rule")), "component_ranking_rule_mismatch"),
    (lambda r: r.update(rankingGateIds=[]), "component_ranking_rule_mismatch"),
    (lambda r: r.update(compositionUniverseSha256=sha("x")), "component_ranking_universe_mismatch"),
    (lambda r: r.update(eventId=PARTNER_EVENT), "component_ranking_not_for_this_event"),
    (lambda r: r.update(frozenLedgerSha256=sha("x")), "component_ranking_not_for_this_event"),
    (lambda r: r.update(schema="mavi-model-selection-layer-a-result-v1"), "schema_unsupported"),
])
def test_component_ranking_must_reconcile_with_the_frozen_inputs(mutate, code):
    document = m3_ledger()
    result = ranking(document)
    mutate(result)
    refused(code, mu.check_component_ranking, result, document)


def test_top_k_tie_at_the_boundary_stops_before_protected_d():
    """Owner decision O3: an unresolved tie across the top-K boundary is a STOP before protected D."""
    document = m3_ledger(block_=universe(componentEvents=[universe()["componentEvents"][0],
                                                          dict(universe()["componentEvents"][1], k=1)]))
    partner = partner_ledger(block=document["compositionUniverse"])
    tie = ranking(document, metrics=dict(VC_METRICS, **{"VC-EST": dict(VC_METRICS["VC-EMG"])}))
    refused("component_rank_ambiguous", mu.derive_top_k, mu.check_component_ranking(tie, document), 1)
    seal = derive(document, partner, rankings_of(document, partner, own=tie))
    assert seal["status"] == "STOPPED" and seal["stopReason"] == "component-rank-ambiguous"
    bs.verify_baseline_seal(seal, frozen=document, protocol_sha256=PROTOCOL, partner_ledger=partner,
                            rankings=rankings_of(document, partner, own=tie))
    # a tie inside the top K is harmless
    inside = ranking(document, metrics=dict(VC_METRICS, **{"VC-B0": dict(VC_METRICS["VC-EST"])}))
    assert sorted(mu.derive_top_k(mu.check_component_ranking(inside, document), 3)) == ["VC-B0", "VC-EMG", "VC-EST"]


def test_partner_tie_stops_and_a_failing_partner_is_skipped():
    document, partner = m3_ledger(), partner_ledger()
    tie = ranking(partner, metrics={"PD-A": {"recall": 0.8}, "PD-B": {"recall": 0.8}})
    seal = derive(document, partner, rankings_of(document, partner, other=tie))
    assert seal["status"] == "STOPPED" and seal["stopReason"] == "resolution-ambiguous"
    # a third eligible partner keeps two evaluable detectors (M3-A1 minimum population) while PD-A fails a gate
    entry = bob()
    entry["benchmarkBaseline"]["compositions"][0]["eligiblePartners"] = partners() + [
        {"candidateId": "PD-C", "identitySha256": identity_of("pdc")}]
    document = m3_ledger(baseline(), established(), emerging(), entry)
    partner = partner_ledger(established("PD-A", "pda"), established("PD-B", "pdb"), established("PD-C", "pdc"))
    gates = {"PD-A": {"contract": "passed", "recall-floor": "failed"}}
    skip = ranking(partner, metrics={"PD-A": {"recall": 0.9}, "PD-B": {"recall": 0.8}, "PD-C": {"recall": 0.7}},
                   gates=gates)
    seal = derive(document, partner, rankings_of(document, partner, other=skip))
    assert seal["partnerCandidateId"] == "PD-B"
    wrong = dict(seal, partnerCandidateId="PD-A", partnerIdentitySha256=identity_of("pda"))
    refused("baseline_seal_partner_not_derived", bs.verify_baseline_seal, wrong, frozen=document,
            protocol_sha256=PROTOCOL, partner_ledger=partner, rankings=rankings_of(document, partner, other=skip))


def test_ordinary_universe_is_derived_with_packageable_baselines_and_never_the_bob():
    state = group()
    assert [i["compositionId"] for i in state.ordinary] == sorted(D_SCORES)
    assert state.top_k == {PARTNER_EVENT: ["PD-A", "PD-B"], EVENT: ["VC-EMG", "VC-EST", "VC-B0"]}
    narrow = universe(componentEvents=[dict(universe()["componentEvents"][0], k=1),
                                       dict(universe()["componentEvents"][1], k=1)])
    document = m3_ledger(block_=narrow)
    partner = partner_ledger(block=narrow)
    state = group(document, partner)
    # top-1 per event plus the packageable baseline VC-B0 (plan §4.1), never the BOB
    assert [i["compositionId"] for i in state.ordinary] == ["C-PD-A--VC-B0", "C-PD-A--VC-EMG"]
    assert mu.composition_id(["PD-A", "VC-EST"]) == "C-PD-A--VC-EST"
    assert mu.COMPOSITION_ID_RE.match("C-PD-A--VC-EST") and not mu.COMPOSITION_ID_RE.match("C-PD-A-VC-EST")


# ================================================================== the seal


def test_seal_carries_every_machine_enforced_field():
    document, partner = m3_ledger(), partner_ledger()
    rankings = rankings_of(document, partner)
    seal = derive(document, partner, rankings)
    assert set(seal) == set(bs.RESOLVED_FIELDS)
    entry = document["candidates"][-1]
    rule = entry["benchmarkBaseline"]["compositions"][0]
    assert seal["benchmarkComponentIdentitySha256"] == bs.benchmark_component_identity_sha256(entry)
    assert seal["stage1RuleSha256"] == document_sha256(rule)
    assert seal["eligibleUniverseSha256"] == document_sha256(rule["eligiblePartners"])
    assert seal["layerAGatesSha256"] == document_sha256(PD_GATES)
    assert seal["partnerRankingRuleSha256"] == document_sha256(universe()["componentEvents"][0]["rankingRule"])
    assert seal["compositionUniverseSha256"] == mu.group_id(universe())
    assert seal["componentRankingSha256s"] == {e: document_sha256(r) for e, r in rankings.items()}
    assert seal["ordinaryCompositionsSha256"] == mu.ordinary_compositions_sha256(group(document, partner).ordinary)
    assert seal["partnerFrozenLedgerSha256"] == document_sha256(partner)
    assert seal["frozenLedgerSha256"] == document_sha256(document)
    assert seal["gateScope"] == "all-ordinary-compositions" and seal["protectedDState"] == "NOT_STARTED"
    for field in bs.RESOLVED_FIELDS:
        if field in ("recordedAt", "recordedBy"):
            continue
        broken = copy.deepcopy(seal)
        del broken[field]
        with pytest.raises(CredibilityError):
            bs.verify_baseline_seal(broken, frozen=document, protocol_sha256=PROTOCOL, partner_ledger=partner,
                                    rankings=rankings)
    refused("unknown_field", bs.verify_baseline_seal, dict(seal, recordSha256=document_sha256(seal)), frozen=document,
            protocol_sha256=PROTOCOL, partner_ledger=partner, rankings=rankings)


@pytest.mark.parametrize("field, value", [
    ("protocolSha256", sha("other protocol")), ("frozenLedgerSha256", sha("x")),
    ("benchmarkComponentIdentitySha256", sha("x")), ("stage1RuleSha256", sha("x")),
    ("eligibleUniverseSha256", sha("x")), ("layerAGatesSha256", sha("x")), ("partnerRankingRuleSha256", sha("x")),
    ("partnerFrozenLedgerSha256", sha("x")), ("compositionSha256", sha("x")), ("compositionUniverseSha256", sha("x")),
    ("ordinaryCompositionsSha256", sha("x")), ("componentRankingSha256s", {EVENT: sha("x"), PARTNER_EVENT: sha("y")}),
    ("partnerEventId", "msr-plate-detector-2026-02"),
])
def test_every_seal_binding_is_rederived(field, value):
    document, partner = m3_ledger(), partner_ledger()
    rankings = rankings_of(document, partner)
    changed = dict(derive(document, partner, rankings), **{field: value})
    refused("baseline_seal_differs_from_frozen_inputs", bs.verify_baseline_seal, changed, frozen=document,
            protocol_sha256=PROTOCOL, partner_ledger=partner, rankings=rankings)


def test_reseal_to_another_partner_with_a_recomputed_hash_is_refused():
    """The reviewer's attack: seal PD-A, bind D to it, then reseal to PD-B and recompute the seal's own hash."""
    document, partner = m3_ledger(), partner_ledger()
    state = group(document, partner)
    summary = group_decision(state)
    check(summary, state)
    swapped = dict(state.seal, partnerCandidateId="PD-B", partnerIdentitySha256=identity_of("pdb"))
    refused("baseline_seal_partner_not_derived", group, document, partner, seal=swapped)
    forged = rankings_of(document, partner, other=ranking(partner, metrics={"PD-A": {"recall": 0.5},
                                                                             "PD-B": {"recall": 0.8}}))
    resealed = group(document, partner, rankings=forged)
    assert resealed.seal["partnerCandidateId"] == "PD-B"
    # the BOB row, then the seal row, then the baseline composition and the sealed U still carry the first seal
    refused("benchmark_baseline_row_seal_mismatch", check, summary, resealed)
    summary["evaluated"][-1]["baselineSealSha256s"] = {GATE: resealed.seal_sha256}
    refused("decision_baseline_seal_mismatch", check, summary, resealed)
    summary["compositionAuthority"]["baselineSeals"][0]["sealSha256"] = resealed.seal_sha256
    refused("decision_baseline_composition_mismatch", check, summary, resealed)


def test_partner_event_must_exist_reconcile_and_share_the_group():
    document, partner = m3_ledger(), partner_ledger()
    rankings = rankings_of(document, partner)
    seal = derive(document, partner, rankings)
    refused("baseline_seal_not_derivable", bs.verify_baseline_seal, seal, frozen=document, protocol_sha256=PROTOCOL,
            partner_ledger=None, rankings=rankings)
    unshortlisted = partner_ledger(established("PD-A", "pda"), reference("PD-B", "pdb"))
    assert derive(document, unshortlisted, rankings)["stopReason"] == "partner-universe-inconsistent"
    other_group = partner_ledger(block=universe(mpid=0.1))
    assert derive(document, other_group, rankings)["stopReason"] == "partner-event-inconsistent"
    refused("composition_universe_differs_between_events", group, document, other_group, rankings, seal=None)


# ---- STOPPED (terminal, O1)


def stopped_group(document=None, partner=None):
    document = m3_ledger() if document is None else document
    partner = partner_ledger() if partner is None else partner
    rankings = rankings_of(document, partner, other=ranking(partner, gates=all_failed(partner)))
    return group(document, partner, rankings)


def test_no_passing_partner_produces_an_immutable_stopped_record():
    """With every partner-event candidate failing a ranking gate the derived reason is, since M3 Amendment A1, the
    minimum evaluable population (checked before the partner); ``no-partner-passed-layer-a`` stays reachable when
    only excluded partners pass (``test_model_selection_m3_a1.py``)."""
    state = stopped_group()
    seal = state.seal
    assert seal["status"] == "STOPPED" and seal["stopReason"] == "insufficient-evaluable-candidates"
    assert set(seal) == set(bs.STOPPED_FIELDS) and state.ordinary is None
    args = dict(frozen=state.frozen_by_event[EVENT], protocol_sha256=PROTOCOL,
                partner_ledger=state.frozen_by_event[PARTNER_EVENT], rankings=state.rankings)
    refused("unknown_field", bs.verify_baseline_seal, dict(seal, partnerCandidateId="PD-A"), **args)
    refused("baseline_stop_evidence_required", bs.verify_baseline_seal, dict(seal, stopEvidenceSha256s=[]), **args)
    refused("value_not_allowed", bs.verify_baseline_seal, dict(seal, stopReason="owner preferred another"), **args)
    refused("baseline_stop_reason_contradicted", bs.verify_baseline_seal, dict(seal, stopReason="identity-mismatch"),
            **args)


@pytest.mark.parametrize("partner, rank, accessed, reason", [
    (None, "default", 0, "partner-event-missing"),
    ("unshortlisted", "default", 0, "partner-universe-inconsistent"),
    ("default", None, 0, "prerequisite-failed"),
    ("default", "tie", 0, "resolution-ambiguous"),
    ("default", "identity", 0, "identity-mismatch"),
    ("default", "malformed", 0, "component-ranking-inconsistent"),
    ("default", "default", 3, "protected-d-accessed"),
])
def test_every_failed_prerequisite_stops_without_a_baseline(partner, rank, accessed, reason):
    document = m3_ledger()
    good = partner_ledger()
    partner_doc = {None: None, "default": good,
                   "unshortlisted": partner_ledger(established("PD-A", "pda"), reference("PD-B", "pdb"))}[partner]
    rankings = rankings_of(document, good)
    if rank is None:
        rankings[PARTNER_EVENT] = None
    elif rank == "tie":
        rankings[PARTNER_EVENT] = ranking(good, metrics={"PD-A": {"recall": 0.5}, "PD-B": {"recall": 0.5}})
    elif rank == "identity":
        rankings[PARTNER_EVENT]["rows"][0]["identitySha256"] = sha("PD-A retrained")
    elif rank == "malformed":
        rankings[EVENT]["rows"].pop()
    seal = bs.derive_baseline_seal(document, GATE, protocol_sha256=PROTOCOL, partner_ledger=partner_doc,
                                   rankings=rankings, recorded_at=SEALED_AT, recorded_by="synthetic-harness",
                                   protected_d_rows_read=accessed,
                                   protected_d_accessed_at="2026-07-01T09:00:00Z" if accessed else None)
    assert seal["status"] == "STOPPED" and seal["stopReason"] == reason
    assert seal["protectedDState"] == ("ACCESSED" if accessed else "NOT_STARTED")
    bs.verify_baseline_seal(seal, frozen=document, protocol_sha256=PROTOCOL, partner_ledger=partner_doc,
                            rankings=rankings)


def test_fabricated_stop_is_refused_when_the_inputs_exist():
    """Cold review P3-1: a stop cannot claim a supplied input was absent; with every input its reason is derived."""
    document, partner = m3_ledger(), partner_ledger()
    rankings = rankings_of(document, partner)
    for supplied_partner, supplied in ((None, {EVENT: None, PARTNER_EVENT: None}),
                                       (partner, {EVENT: rankings[EVENT], PARTNER_EVENT: None})):
        fake = derive(document, supplied_partner, supplied)
        assert fake["status"] == "STOPPED"
        refused("baseline_stop_reason_contradicted", bs.verify_baseline_seal, fake, frozen=document,
                protocol_sha256=PROTOCOL, partner_ledger=partner, rankings=rankings)


def test_an_accessed_stop_records_the_d_access():
    document, partner = m3_ledger(), partner_ledger()
    rankings = rankings_of(document, partner)
    with pytest.raises(CredibilityError):
        derive(document, partner, rankings, protected_d_rows_read=5)
    seal = derive(document, partner, rankings, protected_d_rows_read=5,
                  protected_d_accessed_at="2026-07-01T09:00:00Z")
    assert seal["protectedDState"] == "ACCESSED"
    args = dict(frozen=document, protocol_sha256=PROTOCOL, partner_ledger=partner, rankings=rankings)
    bs.verify_baseline_seal(seal, **args)
    refused("instant_malformed", bs.verify_baseline_seal, dict(seal, protectedDAccessedAt=None), **args)
    refused("baseline_seal_d_state_contradicted", bs.verify_baseline_seal,
            dict(seal, protectedDAccessedAt="2026-07-02T09:00:00Z"), **args)


@pytest.mark.parametrize("state_name, implementation, outcome", [
    ("TECHNICAL_DECISION_RECORDED", None, None), ("QUALIFICATION_PENDING", ("VC-EST",), None),
    ("CLOSED", None, "INCUMBENT_RETAINED"), ("CLOSED", None, "NO_QUALIFIABLE_CANDIDATE"),
    ("CLOSED", ("VC-B0",), "BASELINE_SELECTED"), ("CLOSED", ("VC-EST",), "SELECTED_FOR_PACKAGING"),
])
def test_stopped_group_holds_no_decision_summary_at_all(state_name, implementation, outcome):
    state = stopped_group()
    resolved = group()
    summary = group_decision(resolved, state_name=state_name, implementation=implementation)
    summary["outcome"] = outcome
    summary["evaluated"][-1]["baselineSealSha256s"] = {GATE: state.seal_sha256}
    refused("baseline_stopped_decision_refused", check, summary, state)


# ================================================================== the decision binding (C2-C6, probe_gate)


def _rebuild(state, summary, event_id=EVENT):
    """Keep a hand-edited block self-consistent for the M1 rules (rows re-derived)."""
    return apply_rows(summary, state, event_id)


def test_probe_gate_1_every_composition_failing_the_baseline_cannot_leave_a_winner():
    state = group()
    low = {cid: BASE_D for cid in D_SCORES}  # every composition misses the baseline gate by MPID
    honest = group_decision(state, block_=authority_block(state, scores=low, implementation=None),
                            state_name="TECHNICAL_DECISION_RECORDED", implementation=None)
    check(honest, state)
    assert honest["strongestEvaluatedTechnical"] is None
    assert all(r["technicalGates"] == "failed" for r in honest["evaluated"] if r["technicalGates"] != "n/a")
    # the probe: candidates keep being top-K / finalists / frontier / winner while their compositions failed
    attack = copy.deepcopy(honest)
    attack["compositionAuthority"]["frontier"] = ["VC-EST"]
    refused("frontier_member_not_ranked_composition", check, attack, state)
    attack = copy.deepcopy(honest)
    attack["compositionAuthority"]["componentFinalists"] = {PARTNER_EVENT: ["PD-A"], EVENT: ["VC-EST"]}
    refused("component_finalists_not_derived", check, attack, state)
    attack = copy.deepcopy(honest)
    row = next(r for r in attack["evaluated"] if r["candidateId"] == "VC-EST")
    row.update(technicalGates="passed", comparativeScore=0.7)
    attack["strongestEvaluatedTechnical"] = "VC-EST"
    attack["strongestClearedPerProfile"] = {"dev-profile": "VC-EST"}
    refused("row_technical_gates_not_composition_derived", check, attack, state)
    attack = copy.deepcopy(honest)
    attack["strongestEvaluatedTechnical"] = "VC-EMG"
    refused("strongest_technical_without_passing_candidate", check, attack, state)
    attack = group_decision(state, block_=authority_block(state, scores=low, implementation=None),
                            implementation=("VC-EST",))
    refused("implementation_failed_technical_gate", check, attack, state)  # its row is composition-derived: failed


def test_probe_gate_2_and_3_an_incomplete_composition_set_is_refused():
    state = group()
    empty = group_decision(state)
    block_ = empty["compositionAuthority"]
    block_.update(compositionCandidates=[], rankedCompositions=[], frontier=[], strongestEvaluatedComposition=None)
    refused("composition_set_differs_from_sealed_universe", check, empty, state)
    omitted = group_decision(state)
    block_ = omitted["compositionAuthority"]
    block_["compositionCandidates"] = [c for c in block_["compositionCandidates"] if c["technicalGates"] == "passed"]
    refused("composition_set_differs_from_sealed_universe", check, omitted, state)


def test_probe_gate_4_implementation_from_a_failed_composition_is_refused():
    state = group()
    summary = group_decision(state, implementation=("VC-B0",))
    summary["compositionAuthority"]["implementationComposition"] = "C-PD-A--VC-B0"
    refused("implementation_composition_not_ranked", check, summary, state)
    other = group_decision(state, block_=authority_block(state, implementation="C-PD-A--VC-EMG"))
    refused("implementation_not_composition_component", check, other, state)  # VC-EST is not that composition's
    required = group_decision(state)
    required["compositionAuthority"]["implementationComposition"] = None
    refused("implementation_composition_required", check, required, state)
    none = group_decision(state, implementation=None)
    none["compositionAuthority"]["implementationComposition"] = "C-PD-A--VC-EST"
    refused("implementation_composition_without_implementation", check, none, state)


def test_probe_gate_5_frontier_of_individual_candidates_is_refused():
    state = group()
    summary = group_decision(state)
    summary["compositionAuthority"]["frontier"] = ["VC-EMG", "VC-EST"]
    refused("frontier_member_not_ranked_composition", check, summary, state)


@pytest.mark.parametrize("mutate, code", [
    (lambda b: b["compositionCandidates"].append(dict(copy.deepcopy(b["compositionCandidates"][0]),
                                                      compositionId="C-PD-C--VC-EST")),
     "composition_set_differs_from_sealed_universe"),
    (lambda b: b["compositionCandidates"][0].update(compositionId="C-PD-Z--VC-B0"),
     "composition_set_differs_from_sealed_universe"),
    (lambda b: b["compositionCandidates"].append(copy.deepcopy(b["compositionCandidates"][0])),
     "composition_set_differs_from_sealed_universe"),
    (lambda b: b["compositionCandidates"][0]["components"][1].update(candidateId="VC-EMG"),
     "composition_components_not_derived"),
    (lambda b: b["compositionCandidates"][0]["components"][1].update(identitySha256=sha("x")),
     "composition_components_not_derived"),
    (lambda b: next(c for c in b["compositionCandidates"] if c["compositionId"] == "C-PD-A--VC-B0")["gates"].update(
        baseline="passed"), "composition_baseline_gate_not_derived"),
    (lambda b: next(c for c in b["compositionCandidates"] if c["compositionId"] == "C-PD-A--VC-EMG")["gates"].update(
        baseline="failed"), "composition_baseline_gate_not_derived"),
    (lambda b: next(c for c in b["compositionCandidates"] if c["compositionId"] == "C-PD-A--VC-EMG").update(
        technicalGates="failed", comparativeScore=None), "composition_technical_gates_not_derived"),
    (lambda b: next(c for c in b["compositionCandidates"] if c["compositionId"] == "C-PD-A--VC-EMG").update(
        comparativeScore=0.99), "composition_score_not_derived"),
    (lambda b: b["compositionCandidates"][0]["gates"].pop("consistent-wrong"), "composition_hard_gate_mapping_invalid"),
    (lambda b: b["compositionCandidates"][0]["gates"].update({"consistent-wrong": "maybe"}), "value_not_allowed"),
    (lambda b: b["compositionCandidates"][0].update(baselineSealSha256s={GATE: sha("x")}),
     "d_result_baseline_seal_mismatch"),
    (lambda b: b["compositionCandidates"][0].update(dResultSha256="UNKNOWN"), "malformed"),
    (lambda b: b["compositionCandidates"][0].update(compositionId=GATE), "benchmark_baseline_in_composition_candidate"),
    (lambda b: b["compositionCandidates"][0]["components"][1].update(  # a BOB tuple smuggled into U's place
        candidateId="VC-BOB", identitySha256=identity_of("bob")), "composition_components_not_derived"),
    (lambda b: b["compositionCandidates"].append({**copy.deepcopy(b["compositionCandidates"][0]),
                                                  "compositionId": "C-PD-A--VC-BOB"}),
     "composition_set_differs_from_sealed_universe"),
    (lambda b: b.update(rankedCompositions=list(reversed(b["rankedCompositions"]))), "ranked_compositions_not_derived"),
    (lambda b: b.update(rankedCompositions=b["rankedCompositions"][:-1]), "ranked_compositions_not_derived"),
    (lambda b: b.update(rankedCompositions=b["rankedCompositions"] + ["C-PD-A--VC-B0"]),
     "ranked_compositions_not_derived"),
    (lambda b: b.update(strongestEvaluatedComposition="C-PD-A--VC-EST"), "strongest_composition_not_derived"),
    (lambda b: b.update(strongestEvaluatedComposition=None), "strongest_composition_not_derived"),
    (lambda b: b.update(frontier=["C-PD-A--VC-B0"]), "frontier_member_not_ranked_composition"),
    (lambda b: b["topK"][EVENT].reverse(), "top_k_not_derived"),
    (lambda b: b["topK"].update({EVENT: ["VC-EST", "VC-EMG", "VC-B0", "VC-REF"]}), "top_k_not_derived"),
    (lambda b: b["componentFinalists"][EVENT].append("VC-B0"), "component_finalists_not_derived"),
    (lambda b: b.update(incumbent="VC-REF"), "incumbent_not_evaluated"),
    (lambda b: b.update(groupId=sha("other group")), "d_artefact_group_mismatch"),
    (lambda b: b.update(anchorCommit="HEAD"), "malformed"),
    (lambda b: b["baseline"].update(compositionSha256=sha("x")), "decision_baseline_composition_mismatch"),
    (lambda b: b["baseline"].update(dScore=None, dScoreExact=None), "baseline_d_unavailable"),
    (lambda b: b["baseline"].update(dScore=None), "d_score_exact_malformed"),
])
def test_the_decision_block_is_recomputed_never_trusted(mutate, code):
    state = group()
    summary = group_decision(state)
    mutate(summary["compositionAuthority"])
    refused(code, check, summary, state)


@pytest.mark.parametrize("field", ["rankedCompositions", "frontier"])
@pytest.mark.parametrize("intruder", ["VC-BOB", GATE])
def test_bob_and_gate_only_composition_never_enter_a_ranked_set(field, intruder):
    state = group()
    summary = group_decision(state)
    summary["compositionAuthority"][field] = summary["compositionAuthority"][field] + [intruder]
    refused("benchmark_baseline_in_ranked_set", check, summary, state)


@pytest.mark.parametrize("field", ["incumbent", "strongestEvaluatedComposition", "implementationComposition"])
@pytest.mark.parametrize("intruder", ["VC-BOB", GATE])
def test_bob_and_gate_only_composition_are_never_incumbent_winner_or_implementation(field, intruder):
    state = group()
    summary = group_decision(state)
    summary["compositionAuthority"][field] = intruder
    refused("benchmark_baseline_in_derived_output", check, summary, state)


def test_bob_never_in_top_k_or_finalists():
    state = group()
    for field in ("topK", "componentFinalists"):
        summary = group_decision(state)
        summary["compositionAuthority"][field][EVENT].append("VC-BOB")
        refused("benchmark_baseline_in_ranked_set", check, summary, state)


def test_bob_scoring_highest_cannot_be_named_anywhere():
    state = group()
    summary = group_decision(state)
    for gates, score, quality in (("passed", 9.9, 9.9), ("n/a", 9.9, None), ("n/a", None, 9.9), ("failed", None, 0.0)):
        changed = copy.deepcopy(summary)
        changed["evaluated"][-1].update(technicalGates=gates, comparativeScore=score, taskQualityScore=quality)
        refused("benchmark_baseline_row_scored", check, changed, state)
    for field in ("highestTaskQualityEvaluated", "strongestEvaluatedTechnical"):
        changed = copy.deepcopy(summary)
        changed[field] = "VC-BOB"
        refused("benchmark_baseline_in_derived_output", check, changed, state)
    changed = copy.deepcopy(summary)
    changed["strongestReported"]["candidateId"] = "VC-BOB"
    refused("benchmark_baseline_in_derived_output", check, changed, state)
    changed = copy.deepcopy(summary)
    changed["strongestClearedPerProfile"]["dev-profile"] = "VC-BOB"
    refused("benchmark_baseline_in_derived_output", check, changed, state)
    changed = copy.deepcopy(summary)
    changed["implementation"]["components"] = ["VC-BOB"]
    refused("benchmark_baseline_in_derived_output", check, changed, state)
    changed = copy.deepcopy(summary)
    changed["licence"]["VC-BOB"] = {"dev-profile": "CLEARED"}
    refused("unknown_field", check, changed, state)


def test_bob_must_be_evaluated_on_its_pinned_bytes_and_host_manifests():
    state = group()
    summary = group_decision(state)
    for mutate, code in (
        (lambda s: s["evaluated"].pop(), "evaluated_set_differs_from_shortlist"),
        (lambda s: s["evaluated"][-1]["hostManifestSha256s"].update({"dev-profile": sha("other")}),
         "benchmark_baseline_host_manifest_mismatch"),
        (lambda s: s["evaluated"][-1]["hostManifestSha256s"].pop("dev-profile"),
         "benchmark_baseline_host_manifest_mismatch"),
        (lambda s: s["evaluated"][-1].update(artefactSha256s=[sha("re-pinned weights")]),
         "evaluated_artefact_differs_from_ledger"),
        (lambda s: s["evaluated"][0].update(hostManifestSha256s={}), "host_manifests_only_for_benchmark_baseline"),
        (lambda s: s["evaluated"][-1].update(baselineSealSha256s={GATE: sha("another seal")}),
         "benchmark_baseline_row_seal_mismatch"),
        (lambda s: s["evaluated"][-1].pop("baselineSealSha256s"), "benchmark_baseline_row_seal_mismatch"),
    ):
        changed = copy.deepcopy(summary)
        mutate(changed)
        refused(code, check, changed, state)
    for profiles in (["other-profile"], ["dev-profile", "prod-profile"]):
        changed = copy.deepcopy(summary)
        changed["targetProfiles"] = profiles
        changed["licence"] = {c: {p: "CLEARED" for p in profiles} for c in changed["licence"]}
        changed["strongestClearedPerProfile"] = {p: "VC-EMG" for p in profiles}
        refused("benchmark_baseline_host_profiles_differ_from_target_profiles", check, changed, state)


def test_row_values_are_composition_derived_in_both_group_events():
    state = group()
    for event_id, candidate in ((EVENT, "VC-EMG"), (PARTNER_EVENT, "PD-B")):
        summary = group_decision(state, event_id)
        check(summary, state, event_id)
        changed = copy.deepcopy(summary)
        next(r for r in changed["evaluated"] if r["candidateId"] == candidate)["comparativeScore"] = 0.1
        refused("row_score_not_composition_derived", check, changed, state, event_id)
    summary = group_decision(state)
    row = next(r for r in summary["evaluated"] if r["candidateId"] == "VC-B0")
    assert row["technicalGates"] == "failed"  # VC-B0's compositions miss the baseline gate
    row.update(technicalGates="passed", comparativeScore=0.3)
    refused("row_technical_gates_not_composition_derived", check, summary, state)


def test_seal_and_d_start_are_consistent():
    state = group()
    for value, code in ((SEALED_AT, "baseline_resolved_after_d_started"),
                        ("2026-06-30T10:00:00Z", "baseline_resolved_after_d_started"),
                        ("2026-09-02T00:00:00Z", "d_started_after_decision"), (None, "instant_malformed")):
        summary = group_decision(state)
        summary["compositionAuthority"]["dExecutionStartedAt"] = value
        refused(code, check, summary, state)
    for mutate, code in ((lambda s: s.update(sealSha256=sha("x")), "decision_baseline_seal_mismatch"),
                         (lambda s: s.update(status="STOPPED"), "decision_baseline_seal_mismatch"),
                         (lambda s: s.update(sealCommit="d" * 40), "decision_baseline_seal_mismatch"),
                         (lambda s: s.update(compositionId="GATE-OTHER"), "decision_baseline_seal_mismatch")):
        summary = group_decision(state)
        mutate(summary["compositionAuthority"]["baselineSeals"][0])
        refused(code, check, summary, state)
    summary = group_decision(state)
    summary["compositionAuthority"]["baselineSeals"] *= 2
    refused("gate_only_composition_unresolved", check, summary, state)
    refused("gate_only_composition_unresolved", check, group_decision(state), group(seal=None))


def test_decision_requires_group_authority_and_v2_refuses_m3():
    state = group()
    document = state.frozen_by_event[EVENT]
    refused("m3_decision_requires_group_authority", validate_decision, group_decision(state), document, document)
    v2 = {"schema": "mavi-model-selection-decision-v2", "eventId": document["eventId"]}
    refused("m3_v2_unsupported", validate_decision, v2, document, document)
    partner = state.frozen_by_event[PARTNER_EVENT]
    refused("m3_v2_unsupported", validate_decision, v2 | {"eventId": PARTNER_EVENT}, partner, partner)
    plain = plain_ledger()
    with pytest.raises(CredibilityError) as error:  # without M3 the v2 path is reached exactly as before
        validate_decision(v2, plain, plain)
    assert str(error.value).startswith("decision_v2_requires_repository")
    other = group(m3_ledger(block_=universe(mpid=0.1)), partner_ledger(block=universe(mpid=0.1)))
    refused("d_artefact_group_mismatch", validate_decision, group_decision(state), document, document, group=other)


def test_m1_decisions_without_m3_reject_m3_fields():
    plain = plain_ledger()
    summary = decision(plain)
    validate_decision(summary, plain, plain)
    for field in ("compositionAuthority", "benchmarkOnlyBaselines", "rankedSets"):
        refused("unknown_field", validate_decision, dict(copy.deepcopy(summary), **{field: {}}), plain, plain)
    row = copy.deepcopy(summary)
    row["evaluated"][0].update(technicalGates="n/a", comparativeScore=None)
    refused("value_not_allowed", validate_decision, row, plain, plain)


def _outcome_variants():
    return {"selected": ("CLOSED", ("VC-EST",), "SELECTED_FOR_PACKAGING"),
            "incumbent": ("CLOSED", None, "INCUMBENT_RETAINED"),
            "nqc": ("CLOSED", None, "NO_QUALIFIABLE_CANDIDATE"),
            "baseline-selected": ("CLOSED", ("VC-B0",), "BASELINE_SELECTED"),
            "selected-without-implementation": ("CLOSED", None, "SELECTED_FOR_PACKAGING"),
            "incumbent-with-implementation": ("CLOSED", ("VC-EST",), "INCUMBENT_RETAINED"),
            "emerging-implemented": ("CLOSED", ("VC-EMG",), "SELECTED_FOR_PACKAGING")}


@pytest.mark.parametrize("name", sorted(_outcome_variants()))
def test_outcome_is_the_ordinary_m1_outcome_over_composition_derived_rows(name):
    """Rule 5 restated: the BOB never appears in an output; with the rows the compositions derive, the ordinary M1
    outcome rules decide exactly as they do for the same rows on an M1 event without any M3 role."""
    state_name, implementation, outcome = _outcome_variants()[name]
    state = group()
    impl_comp = {("VC-EST",): "C-PD-A--VC-EST", ("VC-EMG",): "C-PD-A--VC-EMG",
                 ("VC-B0",): "C-PD-A--VC-B0", None: None}[implementation]
    summary = group_decision(state, state_name=state_name, implementation=implementation,
                             block_=authority_block(state, implementation=impl_comp))
    summary["outcome"] = outcome
    with_m3 = code_of(check, summary, state)
    plain = plain_ledger()
    stripped = copy.deepcopy(summary)
    del stripped["compositionAuthority"]
    stripped["evaluated"] = [r for r in stripped["evaluated"] if r["candidateId"] != "VC-BOB"]
    stripped.update(ledgerSha256=document_sha256(plain), frozenLedgerSha256=document_sha256(plain))
    without = code_of(validate_decision, stripped, plain, plain)
    if with_m3 == "implementation_composition_not_ranked":
        assert without in ("implementation_failed_technical_gate", "accepted") or without.startswith("outcome")
    else:
        assert with_m3 == without, (name, with_m3, without)


# ================================================================== git-backed: repository, history, anchors


def git(repo: Path, *args: str) -> str:
    environment = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    return subprocess.run(["git", "-C", str(repo), "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false",
                           "-c", "init.defaultBranch=main", "-c", "core.longpaths=true", *args],
                          capture_output=True, text=True, check=True, env=environment).stdout.strip()


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def folder_of(repo: Path, event_id: str) -> Path:
    return repo / "docs" / "qualification" / "model-selection" / bs.capability_of(event_id)


def write_event(repo: Path, document, *, record_extra="") -> str:
    folder = folder_of(repo, document["eventId"])
    event = document["eventId"]
    write(folder / f"{event}-evidence-ledger.json", json.dumps(document))
    write(folder / f"{event}-evidence-ledger-frozen.json", json.dumps(document))
    protocol = write(folder / f"{event}-protocol.md",
                     f"Frozen ledger SHA-256: {document_sha256(document)}\nFrozen on: {document['frozenOn']}\n")
    write(folder / f"{event}.md", f"Protocol SHA-256: {lf_normalised_sha256(protocol)}\n{record_extra}")
    return lf_normalised_sha256(protocol)


def append(path: Path, line: str) -> None:
    write(path, path.read_text(encoding="utf-8") + line + "\n")


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return git(repo, "rev-parse", "HEAD")


class Built:
    """A real temporary repository holding one composition group."""

    def __init__(self, path: Path, document, partner, protocols):
        self.path, self.document, self.partner, self.protocols = path, document, partner, protocols
        self.rankings: dict = {EVENT: None, PARTNER_EVENT: None}
        self.seal = None
        self.commits: dict[str, str] = {}
        self.remote: str | None = None

    @property
    def folder(self) -> Path:
        return folder_of(self.path, EVENT)

    @property
    def pfolder(self) -> Path:
        return folder_of(self.path, PARTNER_EVENT)

    def record(self, event_id=EVENT) -> Path:
        return folder_of(self.path, event_id) / f"{event_id}.md"

    def seal_path(self) -> Path:
        return bs.seal_path(self.path, self.document, GATE)

    def state(self):
        return ma.derive_group_state({EVENT: self.document, PARTNER_EVENT: self.partner}, self.protocols,
                                     self.rankings, self.seal, s0=self.commits.get("S0"))


def write_rankings(built: Built, *, stopped=False):
    partner_gates = all_failed(built.partner) if stopped else None
    built.rankings = rankings_of(built.document, built.partner, other=ranking(built.partner, gates=partner_gates))
    for event_id, document in built.rankings.items():
        path = folder_of(built.path, event_id) / f"{event_id}{bs.RANKING_SUFFIX}"
        ma.write_canonical(path, document)
        append(built.record(event_id), ma.ranking_citation(event_id, document_sha256(document)))


def write_seal(built: Built):
    built.seal = derive(built.document, built.partner, built.rankings, protocol=built.protocols[EVENT])
    ma.write_canonical(built.seal_path(), built.seal)
    append(built.record(), bs.seal_citation(GATE, document_sha256(built.seal)))


def build(path: Path, *, stopped=False, stages=("freeze", "rank", "seal"), document=None, partner=None) -> Built:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    document = m3_ledger() if document is None else document
    partner = partner_ledger() if partner is None else partner
    protocols = {EVENT: write_event(path, document), PARTNER_EVENT: write_event(path, partner)}
    built = Built(path, document, partner, protocols)
    built.commits["F"] = commit(path, "F: freeze the group")
    if "rank" in stages:
        write_rankings(built, stopped=stopped)
        built.commits["R"] = commit(path, "R: component rankings")
    if "seal" in stages:
        write_seal(built)
        built.commits["S0"] = commit(path, "S0: baseline seal")
    return built


def publish(built: Built) -> str:
    """The canonical repository stand-in: a local bare repository whose default branch is the current HEAD."""
    bare = built.path.parent / f"{built.path.name}-canonical.git"
    if not bare.exists():
        git(built.path.parent, "init", "-q", "--bare", str(bare))
    git(built.path, "push", "-q", "-f", str(bare), "HEAD:refs/heads/main")
    built.remote = str(bare)
    return built.remote


REQUIRED_CHECKS = (("Task 10 qualification", 15368), ("quality", 15368))


def protected_api(*, enforcement="active", include=("~DEFAULT_BRANCH",), exclude=(),
                  rules=("deletion", "non_fast_forward", "pull_request", "required_status_checks"), bypass=(),
                  applied=True, fail=None, checks=REQUIRED_CHECKS, strict=True, merge_methods=("merge",),
                  identity=("hariomahlawat/MAVI", "main"), applied_rules=None):
    """A fake GitHub API shaped like the live ruleset 23662752 (read-only ``gh api`` 2026-10-17)."""
    calls = []
    parameters = {
        "pull_request": {"required_approving_review_count": 0, "required_review_thread_resolution": True,
                         **({} if merge_methods is None else {"allowed_merge_methods": list(merge_methods)})},
        "required_status_checks": {"strict_required_status_checks_policy": strict, "do_not_enforce_on_create": False,
                                   "required_status_checks": [{"context": c, "integration_id": i} for c, i in checks]},
    }

    def rule(t):
        return {"type": t, **({"parameters": copy.deepcopy(parameters[t])} if t in parameters else {})}

    def api(path):
        calls.append(path)
        if fail is not None and fail in path:
            raise CredibilityError("protected_default_branch_unverifiable:simulated API failure")
        if path == "repos/hariomahlawat/MAVI":
            return {"full_name": identity[0], "default_branch": identity[1], "id": 1}
        if path.endswith("rulesets?includes_parents=true"):
            return [{"id": 7, "enforcement": enforcement, "target": "branch"}]
        if path.endswith("rules/branches/main"):
            if not applied:
                return []
            return [{**rule(t), "ruleset_id": 7} for t in (rules if applied_rules is None else applied_rules)]
        if path.endswith("rulesets/7"):
            return {"id": 7, "enforcement": enforcement, "target": "branch",
                    "conditions": {"ref_name": {"include": list(include), "exclude": list(exclude)}},
                    "rules": [rule(t) for t in rules], "bypass_actors": list(bypass)}
        raise AssertionError(f"unexpected API path {path}")
    api.calls = calls
    return api


def open_d(built: Built, *, remote=None, api=None):
    """open_protected_d with a local bare repository standing in for the canonical one (the explicit test seam)."""
    with ma.canonical_for_tests(remote or built.remote or publish(built)), \
            ma.github_api_for_tests(api or protected_api()):
        return ma.open_protected_d(built.path, EVENT)


def commit_d(built: Built, auth, run="RUN-1") -> Path:
    manifest = ma.d_manifest_document(auth, run, sha(f"d-{run}"))
    path = built.folder / f"{EVENT}{bs.D_MANIFEST_INFIX}{run}.json"
    ma.write_canonical(path, manifest)
    built.commits[run] = commit(built.path, f"protected D {run}")
    git(built.path, "update-ref", "refs/remotes/origin/main", auth.anchor_commit)  # what CI's checkout fetches
    return path


def commit_d_results(built: Built, auth, block_) -> None:
    """M3-A1: one committed group D manifest per D result the block cites (rows and baseline), after the anchor."""
    cited = [(r["compositionId"], r["dResultSha256"]) for r in block_["compositionCandidates"]]
    cited.append((GATE, block_["baseline"]["dResultSha256"]))
    for name, result in cited:
        run = f"R-{name}"
        ma.write_canonical(built.folder / f"{EVENT}{bs.D_MANIFEST_INFIX}{run}.json",
                           ma.d_manifest_document(auth, run, result))
    commit(built.path, "protected D results")
    git(built.path, "update-ref", "refs/remotes/origin/main", auth.anchor_commit)


def commit_decisions(built: Built, auth, *, base=BASE_D, state_name="QUALIFICATION_PENDING", chosen=True,
                     mutate=None, mutate_partner=None, with_results=True):
    state = built.state()
    block_ = authority_block(state, anchor=auth.anchor_commit, base=base,
                             implementation="C-PD-A--VC-EST" if chosen else None)
    if mutate is not None:
        mutate(block_)
    if with_results:
        commit_d_results(built, auth, block_)
    for event_id in (EVENT, PARTNER_EVENT):
        own = copy.deepcopy(block_)
        if mutate_partner is not None and event_id == PARTNER_EVENT:
            mutate_partner(own)
        summary = group_decision(state, event_id, block_=own, state_name=state_name,
                                 implementation="default" if chosen else None)
        folder = folder_of(built.path, event_id)
        decision_path = write(folder / f"{event_id}-decision.json", json.dumps(summary))
        snapshot_path = write(folder / f"{event_id}-evidence-ledger-decided.json",
                              json.dumps(state.frozen_by_event[event_id]))
        append(built.record(event_id), f"Decision SHA-256: {lf_normalised_sha256(decision_path)}")
        append(built.record(event_id), f"Decision snapshot SHA-256: {lf_normalised_sha256(snapshot_path)}")
    built.commits["decision"] = commit(built.path, "technical decision")


def full_flow(path: Path):
    built = build(path)
    auth = open_d(built)
    git(built.path, "update-ref", "refs/remotes/origin/main", auth.anchor_commit)
    ma.verify_d_manifest_binding(ma.d_manifest_document(auth, "RUN-1", sha("d-RUN-1")), built.path)  # before scoring
    manifest = commit_d(built, auth)
    return built, auth, manifest


# ---- positive


def test_repository_accepts_a_sealed_group_and_reports_its_files(tmp_path):
    built = build(tmp_path / "r")
    checked = validate_repository(built.path)
    assert built.seal_path().relative_to(built.path).as_posix() in checked and "git-history:full" in checked
    assert (built.folder / f"{EVENT}{bs.RANKING_SUFFIX}").relative_to(built.path).as_posix() in checked


@pytest.mark.parametrize("stages", [("freeze",), ("freeze", "rank")])
def test_repository_accepts_every_stage_before_the_seal(tmp_path, stages):
    validate_repository(build(tmp_path / "r", stages=stages).path)


def test_repository_accepts_a_stopped_group_without_d(tmp_path):
    built = build(tmp_path / "r", stopped=True)
    assert built.seal["status"] == "STOPPED"
    validate_repository(built.path)


def test_full_protected_d_flow(tmp_path):
    """F < R < S0 -> published -> open_protected_d (anchor) -> D manifest -> decisions in both group events."""
    built, auth, manifest = full_flow(tmp_path / "r")
    assert auth.anchor_commit == built.commits["S0"] and auth.seals[0].seal_commit == built.commits["S0"]
    assert auth.ordinary_compositions_sha256 == built.seal["ordinaryCompositionsSha256"]
    commit_decisions(built, auth)
    checked = validate_repository(built.path)
    assert manifest.relative_to(built.path).as_posix() in checked


def test_open_protected_d_uses_only_the_injected_ruleset_api(tmp_path):
    built = build(tmp_path / "r")
    api = protected_api()
    open_d(built, api=api)
    assert any("rulesets" in c for c in api.calls) and any("rules/branches/main" in c for c in api.calls)
    assert ma.CANONICAL_ORIGIN == "https://github.com/hariomahlawat/MAVI.git"


# ---- record citations and stray artefacts


def test_rankings_and_seal_must_be_cited_exactly_once_and_canonical(tmp_path):
    built = build(tmp_path / "a", stages=("freeze",))
    write_rankings(built)
    citation = ma.ranking_citation(EVENT, document_sha256(built.rankings[EVENT]))
    write(built.record(), built.record().read_text().replace(citation + "\n", ""))
    commit(built.path, "R without the record citation")  # committed: the work tree is never authority (P2-1)
    refused("component_ranking_not_recorded", validate_repository, built.path)
    append(built.record(), citation)
    append(built.record(), citation)
    commit(built.path, "the citation, twice")
    refused("component_ranking_cited_twice", validate_repository, built.path)
    built = build(tmp_path / "b", stages=("freeze", "rank"))
    write_seal(built)
    write(built.seal_path(), json.dumps(built.seal, indent=2))
    commit(built.path, "a non-canonical seal")
    refused("baseline_seal_not_canonical", validate_repository, built.path)
    built = build(tmp_path / "b2")
    write(built.seal_path(), json.dumps(built.seal, indent=2))
    refused("baseline_artefact_rewritten_in_history", validate_repository, built.path)  # committed, then edited
    built = build(tmp_path / "c")
    ma.write_canonical(built.folder / f"{EVENT}{bs.SEAL_INFIX}GATE-STRAY.json", built.seal)
    refused("baseline_artefact_without_frozen_composition", validate_repository, built.path)
    built = build(tmp_path / "d")
    ma.write_canonical(built.folder / f"{EVENT}{bs.LEGACY_LAYER_A_INFIX}{GATE}.json", {"schema": "legacy"})
    refused("legacy_layer_a_artefact", validate_repository, built.path)
    built = build(tmp_path / "e")
    ma.write_canonical(built.pfolder / f"{PARTNER_EVENT}{bs.SEAL_INFIX}{GATE}.json", built.seal)
    refused("baseline_artefact_without_frozen_composition", validate_repository, built.path)
    built = build(tmp_path / "f", stages=("freeze",))
    append(built.record(), bs.seal_citation(GATE, sha("no file")))
    commit(built.path, "a seal citation without a seal file")
    refused("baseline_seal_cited_without_file", validate_repository, built.path)


def test_an_m3_artefact_outside_its_event_folder_is_refused(tmp_path):
    built = build(tmp_path / "r")
    stray = folder_of(built.path, PARTNER_EVENT) / f"{EVENT}{bs.SEAL_INFIX}{GATE}.json"
    ma.write_canonical(stray, built.seal)
    refused("m3_artefact_location_mismatch", validate_repository, built.path)
    commit(built.path, "a seal filed in another event's folder")
    stray.unlink()
    commit(built.path, "and removed again")
    refused("m3_artefact_location_mismatch", validate_repository, built.path)  # history keeps it in view


def test_an_uncommitted_freeze_is_accepted_until_artefacts_appear(tmp_path):
    path = tmp_path / "r"
    path.mkdir()
    git(path, "init", "-q")
    commit(path, "unrelated root")
    document, partner = m3_ledger(), partner_ledger()
    built = Built(path, document, partner, {EVENT: write_event(path, document), PARTNER_EVENT: write_event(path, partner)})
    validate_repository(path)
    write_rankings(built)
    refused("m3_chronology_unproven", validate_repository, path)


def test_no_ranking_no_seal_means_no_protected_d(tmp_path):
    refused("d_not_authorised", open_d, build(tmp_path / "a", stages=("freeze",)))
    refused("d_not_authorised", open_d, build(tmp_path / "b", stages=("freeze", "rank")))


# ---- A: the sticky audit domain (probe_vanish and its variants)


def _rewrite_frozen_to(built: Built, document):
    write_event(built.path, document, record_extra=built.record().read_text().split("\n", 1)[1])


def _rewrite_protocol(built: Built):
    """An honest-looking revision in place: the protocol changes and the record cites the new hash as well."""
    protocol = built.folder / f"{EVENT}-protocol.md"
    append(protocol, "Revision 2: a looser gate.")
    append(built.record(), f"Protocol SHA-256: {lf_normalised_sha256(protocol)}")


A_ATTACKS = {
    "frozen-to-non-m3": (lambda b: _rewrite_frozen_to(b, plain_ledger()), "m3_frozen_file_rewritten"),
    "bob-dropped": (lambda b: _rewrite_frozen_to(b, m3_ledger(baseline(), established(), emerging())),
                    "m3_frozen_file_rewritten"),
    "all-artefacts-deleted": (lambda b: [p.unlink() for p in list(b.folder.glob(f"{EVENT}-*.json"))
                                         if ma.artefact_event(p.name)], "baseline_artefact_deleted_in_history"),
    "protocol-rewritten": (lambda b: _rewrite_protocol(b), "m3_frozen_file_rewritten"),
    "record-line-removed": (lambda b: write(b.record(), "\n".join(
        line for line in b.record().read_text().splitlines() if not line.startswith("Component ranking")) + "\n"),
        "m3_record_line_removed"),
    "seal-deleted": (lambda b: b.seal_path().unlink(), "baseline_artefact_deleted_in_history"),
    "event-erased": (lambda b: shutil.rmtree(b.folder), "m3_event_erased"),
}


def _apply(built: Built, mutate, mode: str):
    repo = built.path
    if mode == "direct":
        mutate(built)
        commit(repo, "attack")
        return
    if mode == "merge-resolution":
        git(repo, "checkout", "-q", "-b", "side")
        commit(repo, "side work")
        git(repo, "checkout", "-q", "main")
        commit(repo, "main work")
        git(repo, "merge", "-q", "--no-ff", "--no-commit", "side")
        mutate(built)
        commit(repo, "merge whose resolution carries the attack")
        return
    git(repo, "checkout", "-q", "-b", "side")
    mutate(built)
    commit(repo, "attack on a side branch")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge the side branch", "side")


@pytest.mark.parametrize("mode", ["direct", "merge-resolution", "side-branch"])
@pytest.mark.parametrize("attack", sorted(A_ATTACKS))
def test_a_history_attack_is_refused_in_every_shape(tmp_path, attack, mode):
    mutate, code = A_ATTACKS[attack]
    built = build(tmp_path / "r", stopped=(attack == "seal-deleted"))
    _apply(built, mutate, mode)
    refused(code, validate_repository, built.path)


@pytest.mark.parametrize("variant", ["resolved-with-d", "stopped"])
def test_probe_vanish_erasing_every_m3_artefact_under_a_bob_free_revision_is_refused(tmp_path, variant):
    if variant == "stopped":
        built = build(tmp_path / "r", stopped=True)
    else:
        built, _auth, _manifest = full_flow(tmp_path / "r")
    validate_repository(built.path)
    _rewrite_frozen_to(built, plain_ledger())
    write(built.record(), f"Protocol SHA-256: {lf_normalised_sha256(built.folder / f'{EVENT}-protocol.md')}\n")
    for path in list(built.folder.glob(f"{EVENT}-*.json")):
        if ma.artefact_event(path.name):
            path.unlink()
    commit(built.path, "revision drops the BOB and erases its seal, rankings and D manifests")
    refused("m3_frozen_file_rewritten", validate_repository, built.path)


def test_the_domain_is_sticky_and_comes_from_the_walk_only(tmp_path):
    built = build(tmp_path / "r", stopped=True)
    shutil.rmtree(built.folder)
    shutil.rmtree(built.pfolder)
    commit(built.path, "erase both events completely")
    history = mg.model_selection_history(built.path)
    domain = ma.model_selection_domain(built.path, history)
    assert {EVENT, PARTNER_EVENT} <= set(domain.events)
    refused("m3_event_erased", validate_repository, built.path)


# ---- probe_repo A: the gate and the repository refuse with the same code


@pytest.mark.parametrize("attack", ["record-without-protocol-line", "shortlist-edited"])
def test_probe_repo_a_gate_and_repository_refuse_with_the_same_code(tmp_path, attack):
    built = build(tmp_path / "r")
    publish(built)
    if attack == "record-without-protocol-line":
        write(built.record(), "\n".join(line for line in built.record().read_text().splitlines()
                                        if not line.startswith("Protocol SHA-256")) + "\n")
    else:
        working = built.folder / f"{EVENT}-evidence-ledger.json"
        document = json.loads(working.read_text())
        for entry in document["candidates"]:
            if entry["candidateId"] == "VC-EMG":
                entry["disposition"] = {"status": "NOT_SHORTLISTED", "reasonClass": "technical",
                                        "reason": "dropped after results", "revisitTrigger": None, "decidedBy": "x"}
        write(working, json.dumps(document))
    commit(built.path, attack)
    repository = code_of(validate_repository, built.path)
    gate = code_of(open_d, built)
    assert repository == gate and repository != "accepted", (repository, gate)


# ---- B: one predicate; D only with the group's seal RESOLVED (P2-1)


def test_p2_1_a_stopped_or_missing_composition_keeps_d_closed(tmp_path):
    refused("d_not_authorised", open_d, build(tmp_path / "stopped", stopped=True))
    refused("d_not_authorised", open_d, build(tmp_path / "unsealed", stages=("freeze", "rank")))


def test_shared_predicate_is_the_only_authority_path():
    import inspect
    assert "check_group_authority(" in inspect.getsource(ma.validate_repository_m3)
    assert "check_group_authority(" in inspect.getsource(ma.open_protected_d)
    assert "_validate_repository(" in inspect.getsource(ma.open_protected_d)
    assert "_validate_repository(" in inspect.getsource(ma.verify_d_manifest_binding)
    assert not hasattr(bs, "require_committed_baseline_seal") and not hasattr(bs, "_git_ok")
    source = inspect.getsource(ma) + inspect.getsource(mg) + inspect.getsource(bs)
    assert '"show"' not in source and "continue  # the record was deleted" not in source


# ---- E/O1/O6: STOPPED is terminal; revision = new events with supersedes (probe_repo B)


NEW_EVENT, NEW_PARTNER = "msr-vehicle-colour-2026-02", "msr-plate-detector-2026-02"


def superseding_group(built: Built, *, seal_hashes=None, line=True):
    """Re-freeze both group events under new ids that supersede the STOPPED ones."""
    revised = universe(componentEvents=[dict(universe()["componentEvents"][0], eventId=NEW_PARTNER),
                                        dict(universe()["componentEvents"][1], eventId=NEW_EVENT)])
    stopped_seal = document_sha256(built.seal)
    for old, new, make in ((EVENT, NEW_EVENT, lambda: m3_ledger(block_=revised)),
                           (PARTNER_EVENT, NEW_PARTNER, lambda: partner_ledger(block=revised))):
        document = make()
        document["eventId"] = new
        if new == NEW_EVENT:
            document["candidates"][-1]["benchmarkBaseline"]["compositions"][0]["partnerEventId"] = NEW_PARTNER
        document["frozenOn"] = "2026-07-05"
        old_doc = built.document if old == EVENT else built.partner
        document["supersedes"] = {"eventId": old, "frozenLedgerSha256": document_sha256(old_doc),
                                  "stoppedSealSha256s": seal_hashes or [stopped_seal]}
        write_event(built.path, document)
        if line:
            append(built.record(old), ma.superseded_line(new))


def test_probe_repo_b1_rewriting_a_stopped_event_is_refused_and_the_new_event_route_works(tmp_path):
    built = build(tmp_path / "r", stopped=True)
    validate_repository(built.path)
    refused("d_not_authorised", open_d, built)
    # B1: the stopped event's frozen ledger is revised in place to drop the BOB
    rewrite = build(tmp_path / "b1", stopped=True)
    _rewrite_frozen_to(rewrite, m3_ledger(baseline(), established(), emerging()))
    commit(rewrite.path, "drop the benchmark-only baseline after the stop")
    refused("m3_frozen_file_rewritten", validate_repository, rewrite.path)
    # a new event of the stopped capability without supersedes is refused while the stop is unsuperseded
    other = build(tmp_path / "plain-new", stopped=True)
    later = plain_ledger()
    later["eventId"] = NEW_EVENT
    later["frozenOn"] = "2026-07-05"
    write_event(other.path, later)
    commit(other.path, "a new M1 event of the stopped capability")
    refused("stopped_event_not_superseded", validate_repository, other.path)
    # the legitimate route: both group events superseded by new M3 events; the old ones stay audited
    superseding_group(built)
    commit(built.path, "re-freeze under new event ids that supersede the stopped group")
    validate_repository(built.path)
    history = mg.model_selection_history(built.path)
    assert {EVENT, PARTNER_EVENT} <= set(ma.model_selection_domain(built.path, history).events)
    refused("d_not_authorised", open_d, built)  # the superseded group never opens D


@pytest.mark.parametrize("defect, code", [("seal-hash", "supersedes_target_not_stopped"),
                                          ("record-line", "superseded_record_line_missing")])
def test_supersession_must_cite_the_stop_exactly(tmp_path, defect, code):
    built = build(tmp_path / "r", stopped=True)
    if defect == "seal-hash":
        superseding_group(built, seal_hashes=[sha("another seal")])
    else:
        superseding_group(built, line=False)
    commit(built.path, "supersede")
    refused(code, validate_repository, built.path)


def test_a_resolved_group_cannot_be_superseded(tmp_path):
    built = build(tmp_path / "r")
    superseding_group(built)
    commit(built.path, "supersede a resolved group")
    refused("supersedes_target_not_stopped", validate_repository, built.path)


def test_a_superseded_line_needs_its_superseding_event(tmp_path):
    built = build(tmp_path / "r", stopped=True)
    append(built.record(), ma.superseded_line("msr-vehicle-colour-2026-09"))
    commit(built.path, "claim a successor that does not exist")
    refused("superseded_line_without_superseding_event", validate_repository, built.path)


# ---- O4: baseline D unavailable after D opened -> ABANDONED, no M1 outcome


def test_baseline_d_unavailable_refuses_the_decision_and_abandons_the_group(tmp_path):
    built, auth, manifest = full_flow(tmp_path / "r")
    state = built.state()
    summary = group_decision(state, block_=authority_block(state, base=None, anchor=auth.anchor_commit))
    refused("baseline_d_unavailable", check, summary, state)
    evidence = json.loads(manifest.read_text())["resultSha256"]
    for event_id in (EVENT, PARTNER_EVENT):
        append(built.record(event_id), ma.abandonment_line("baseline-d-unavailable", evidence))
    commit(built.path, "ABANDONED: the baseline D result cannot be evaluated")
    validate_repository(built.path)
    refused("d_not_authorised", open_d, built)
    commit_decisions(built, auth)
    # a decision after the abandonment is refused (the decision now also sits in the event's committed history)
    assert code_of(validate_repository, built.path) in ("event_abandoned_decision_refused", "abandonment_after_decision")


def test_abandonment_must_cover_the_group_and_cite_a_d_result(tmp_path):
    built, auth, manifest = full_flow(tmp_path / "r")
    evidence = json.loads(manifest.read_text())["resultSha256"]
    append(built.record(), ma.abandonment_line("baseline-d-unavailable", evidence))
    commit(built.path, "abandon one event only")
    refused("group_abandonment_incomplete", validate_repository, built.path)
    built = build(tmp_path / "b")
    for event_id in (EVENT, PARTNER_EVENT):
        append(built.record(event_id), ma.abandonment_line("baseline-d-unavailable", sha("no D was opened")))
    commit(built.path, "abandon without protected D")
    refused("abandonment_without_protected_d", validate_repository, built.path)
    refused("abandonment_reason_not_allowed", ma.abandonment_line, "owner-preferred", sha("x"))


# ---- D: chronology and the external anchor


def test_d1_ranking_in_the_seal_or_freeze_commit_is_refused(tmp_path):
    built = build(tmp_path / "rs", stages=("freeze",))
    write_rankings(built)
    write_seal(built)
    commit(built.path, "rankings and seal in one commit")
    refused("m3_chronology_violated", validate_repository, built.path)
    path = tmp_path / "fr"
    path.mkdir()
    git(path, "init", "-q")
    document, partner = m3_ledger(), partner_ledger()
    built = Built(path, document, partner, {EVENT: write_event(path, document),
                                            PARTNER_EVENT: write_event(path, partner)})
    write_rankings(built)
    commit(path, "freeze and rankings in one commit")
    refused("m3_chronology_violated", validate_repository, path)
    built = build(tmp_path / "uncommitted", stages=("freeze",))
    write_rankings(built)
    write_seal(built)
    refused("m3_file_differs_from_commit", validate_repository, built.path)  # uncommitted record citations (P2-1)
    git(built.path, "add", "--", built.record().relative_to(built.path).as_posix(),
        built.record(PARTNER_EVENT).relative_to(built.path).as_posix())
    git(built.path, "commit", "-q", "-m", "record citations committed, ranking and seal files not")
    refused("m3_chronology_unproven", validate_repository, built.path)


def test_d2_the_seal_must_be_published_on_the_canonical_default_branch(tmp_path):
    built = build(tmp_path / "r", stages=("freeze", "rank"))
    remote = publish(built)  # published before the seal
    write_seal(built)
    built.commits["S0"] = commit(built.path, "S0 not pushed")
    refused("seal_not_published", open_d, built, remote=remote)
    # a forged local remote-tracking ref and origin URL are never read at D open
    git(built.path, "update-ref", "refs/remotes/origin/main", built.commits["S0"])
    git(built.path, "remote", "add", "origin", str(tmp_path / "anything"))
    refused("seal_not_published", open_d, built, remote=remote)
    publish(built)
    assert open_d(built, remote=remote).anchor_commit == built.commits["S0"]


def test_d2_offline_or_ambiguous_remote_refuses(tmp_path):
    built = build(tmp_path / "r")
    refused("anchor_unavailable", open_d, built, remote=str(tmp_path / "no-such-remote.git"))
    bare = tmp_path / "empty.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    refused("anchor_unavailable", open_d, built, remote=str(bare))  # no refs/heads/main: ls-remote exits 2


def test_d2_the_validated_state_is_the_published_state(tmp_path):
    built = build(tmp_path / "r")
    publish(built)
    append(built.record(), "a local, uncommitted note")
    refused("m3_file_differs_from_commit", open_d, built)  # the repository predicate refuses it first (P2-1)
    git(built.path, "checkout", "-q", "--", ".")
    append(built.record(PARTNER_EVENT), "Note: committed but never published")
    commit(built.path, "unpublished group change")
    refused("group_state_differs_from_anchor", open_d, built)


def test_d3_recorded_anchor_is_reverified(tmp_path):
    built, auth, manifest = full_flow(tmp_path / "r")
    validate_repository(built.path)
    git(built.path, "update-ref", "-d", "refs/remotes/origin/main")
    refused("anchor_unverifiable", validate_repository, built.path)
    git(built.path, "update-ref", "refs/remotes/origin/main", built.commits["F"])  # stale
    refused("anchor_unverifiable", validate_repository, built.path)


def test_d3_a_d_manifest_must_descend_from_its_anchor(tmp_path):
    built = build(tmp_path / "r")
    auth = open_d(built)
    git(built.path, "checkout", "-q", "-b", "early", built.commits["R"])
    path = built.folder / f"{EVENT}{bs.D_MANIFEST_INFIX}RUN-9.json"
    ma.write_canonical(path, ma.d_manifest_document(auth, "RUN-9", sha("d-9")))
    commit(built.path, "a D manifest committed before the anchor")
    git(built.path, "checkout", "-q", "main")
    git(built.path, "merge", "-q", "--no-ff", "-m", "merge the early D manifest", "early")
    git(built.path, "update-ref", "refs/remotes/origin/main", auth.anchor_commit)
    refused("d_artefact_not_after_anchor", validate_repository, built.path)


def test_d3_manifest_rows_are_bound_to_the_authority(tmp_path):
    built = build(tmp_path / "r")
    auth = open_d(built)
    git(built.path, "update-ref", "refs/remotes/origin/main", auth.anchor_commit)
    base = ma.d_manifest_document(auth, "RUN-1", sha("d"))
    ma.verify_d_manifest_binding(base, built.path)
    for mutate, code in ((lambda m: m.update(groupId=sha("x")), "d_artefact_group_mismatch"),
                         (lambda m: m.update(ordinaryCompositionsSha256=sha("x")), "d_artefact_universe_mismatch"),
                         (lambda m: m["baselineSeals"][0].update(sealSha256=sha("x")),
                          "d_manifest_baseline_seal_mismatch"),
                         (lambda m: m["baselineSeals"][0].update(sealCommit=built.commits["R"]),
                          "d_manifest_baseline_seal_mismatch"),
                         (lambda m: m.update(anchorCommit=built.commits["R"]), "anchor_precedes_seal"),
                         (lambda m: m.update(anchorCommit="e" * 40), "anchor_not_in_head")):
        manifest = copy.deepcopy(base)
        mutate(manifest)
        refused(code, ma.verify_d_manifest_binding, manifest, built.path)


def _orphan_replay(built: Built, stages) -> None:
    git(built.path, "checkout", "-q", "--orphan", "rewritten", built.commits["F"])
    commit(built.path, "F' replayed")
    for stage in stages:
        git(built.path, "checkout", "-q", built.commits[stage], "--", ".")
        commit(built.path, f"{stage}' replayed")
    git(built.path, "branch", "-D", "main")
    git(built.path, "update-ref", "-d", "refs/remotes/origin/main")
    git(built.path, "reflog", "expire", "--expire=now", "--all")
    git(built.path, "gc", "-q", "--prune=now")


def test_probe_repo_c1_orphan_rewrite_is_refused(tmp_path):
    """The whole history replayed on an orphan branch (each stage its own commit, so the chronology still holds) and
    the original pruned: the D manifest's S0 and anchor are no longer in HEAD's history; rebinding it is a rewrite;
    and a fresh anchor is unobtainable because the canonical default branch still holds the original history."""
    built, auth, manifest = full_flow(tmp_path / "r")
    validate_repository(built.path)
    _orphan_replay(built, ("R", "S0", "RUN-1"))
    assert code_of(validate_repository, built.path) in ("d_manifest_baseline_seal_mismatch", "anchor_not_in_head")
    rebound = json.loads(manifest.read_text())
    rebound["baselineSeals"][0]["sealCommit"] = git(built.path, "rev-parse", "HEAD~1")
    ma.write_canonical(manifest, rebound)
    commit(built.path, "rebind the D manifest to the replayed seal commit")
    refused("baseline_artefact_rewritten_in_history", validate_repository, built.path)
    fresh = build(tmp_path / "fresh")
    publish(fresh)
    _orphan_replay(fresh, ("R", "S0"))
    validate_repository(fresh.path)
    refused("seal_not_published", open_d, fresh)


def test_probe_repo_c1_main_rewrite_is_blocked_by_the_ruleset_check(tmp_path):
    built = build(tmp_path / "r")
    for api, code in ((protected_api(enforcement="disabled"), "protected_default_branch_unverified"),
                      (protected_api(include=()), "protected_default_branch_unverified"),
                      (protected_api(include=("refs/heads/release",)), "protected_default_branch_unverified"),
                      (protected_api(exclude=("~DEFAULT_BRANCH",)), "protected_default_branch_unverified"),
                      (protected_api(rules=("deletion",)), "protected_default_branch_unverified"),
                      (protected_api(rules=("non_fast_forward",)), "protected_default_branch_unverified"),
                      (protected_api(bypass=({"actor_type": "RepositoryRole", "actor_id": 5},)),
                       "protected_default_branch_unverified"),
                      (protected_api(applied=False), "protected_default_branch_unverified"),
                      (protected_api(fail="rulesets"), "protected_default_branch_unverifiable")):
        refused(code, open_d, built, api=api)
    assert verify_protection(protected_api(include=("refs/heads/main",))) == 7


def verify_protection(api):
    with ma.github_api_for_tests(api):
        return ma.verify_default_branch_protection()


def test_ruleset_api_shape_errors_fail_closed():
    refused("protected_default_branch_unverifiable", verify_protection, lambda path: {"message": "x"})

    def raises(path):
        raise OSError("gh not installed")
    refused("protected_default_branch_unverifiable", verify_protection, raises)
    base = protected_api()

    def no_bypass_field(path):
        detail = base(path)
        if isinstance(detail, dict):
            detail.pop("bypass_actors", None)
        return detail
    refused("protected_default_branch_unverified", verify_protection, no_bypass_field)


# ---- A6 / clarification 4: Git errors are classified refusals, never verdicts


def test_probe_repo_e1_injected_git_failure_is_a_typed_refusal(tmp_path, monkeypatch):
    built = build(tmp_path / "r")
    original = mg._run

    def failing(repo, args, data=None, **kwargs):
        if args and args[0] == "cat-file":
            return subprocess.CompletedProcess(["git", *args], 128, b"", b"fatal: simulated object store failure")
        return original(repo, args, data, **kwargs)
    monkeypatch.setattr(mg, "_run", failing)
    with pytest.raises(mg.GitCommandError) as error:
        validate_repository(built.path)
    assert error.value.code == "git_command_failed" and error.value.returncode == 128
    assert "simulated object store failure" in error.value.stderr
    assert str(error.value).startswith("git_command_failed:cat-file")


def test_p2_2_a_missing_object_is_git_object_missing_never_accepted(tmp_path):
    built = build(tmp_path / "r")
    blob = git(built.path, "rev-parse", f"HEAD:{built.record().relative_to(built.path).as_posix()}")
    loose = built.path / ".git" / "objects" / blob[:2] / blob[2:]
    os.chmod(loose, 0o666)  # loose objects are read-only (Windows refuses to delete them otherwise)
    loose.unlink()
    refused("git_object_missing", validate_repository, built.path)


def test_history_must_be_full_and_unaltered(tmp_path):
    built = build(tmp_path / "deep")
    commit(built.path, "later work")
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", built.path.as_uri(), str(shallow)], check=True,
                   capture_output=True)
    refused("model_selection_history_unavailable", validate_repository, shallow)
    nogit = tmp_path / "nogit"
    shutil.copytree(built.path, nogit, ignore=shutil.ignore_patterns(".git"))
    refused("model_selection_history_unavailable", validate_repository, nogit)
    write(built.path / ".git" / "info" / "grafts", built.commits["S0"] + "\n")
    with pytest.raises(CredibilityError) as error:
        validate_repository(built.path)
    assert str(error.value).startswith("model_selection_history_unavailable") and "grafts_present" in str(error.value)


def test_replace_objects_are_ignored(tmp_path):
    built = build(tmp_path / "r")
    record_rel = built.record().relative_to(built.path).as_posix()
    blob = git(built.path, "rev-parse", f"HEAD:{record_rel}")
    forged = subprocess.run(["git", "-C", str(built.path), "hash-object", "-w", "--stdin"], input=b"forged\n",
                            capture_output=True, check=True).stdout.decode().strip()
    git(built.path, "replace", blob, forged)
    assert mg.read_blobs(built.path, [blob])[blob] == built.record().read_bytes().replace(b"\r\n", b"\n")
    validate_repository(built.path)


def test_git_environment_cannot_redirect_the_repository(tmp_path, monkeypatch):
    built = build(tmp_path / "r")
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    git(decoy, "init", "-q")
    commit(decoy, "decoy")
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(decoy))
    assert "GIT_DIR" not in mg.git_environment() and mg.git_environment()["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert mg.resolve_commit(built.path, "HEAD") == built.commits["S0"]


def test_first_add_is_the_earliest_by_ancestry_not_lexical_order(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q")
    first = commit(repo, "first")
    second = first
    for attempt in range(200):
        second = commit(repo, f"second {attempt}")
        if second < first:
            break
        git(repo, "reset", "-q", "--hard", first)
    assert second < first  # the descendant sorts first lexically
    assert mg.first_add_commit(repo, {first, second}, "x") == first
    git(repo, "checkout", "-q", "--orphan", "island")
    island = commit(repo, "unrelated root")
    refused("artefact_first_add_ambiguous", mg.first_add_commit, repo, {second, island}, "x")


def test_a_d_manifest_added_inside_a_merge_is_found(tmp_path):
    built = build(tmp_path / "r")
    auth = open_d(built)
    git(built.path, "checkout", "-q", "-b", "side")
    commit(built.path, "side work")
    git(built.path, "checkout", "-q", "main")
    commit(built.path, "main work")
    git(built.path, "merge", "-q", "--no-ff", "--no-commit", "side")
    path = built.folder / f"{EVENT}{bs.D_MANIFEST_INFIX}RUN-1.json"
    ma.write_canonical(path, ma.d_manifest_document(auth, "RUN-1", sha("d")))
    merge = commit(built.path, "a merge adds the D manifest")
    git(built.path, "update-ref", "refs/remotes/origin/main", auth.anchor_commit)
    history = mg.model_selection_history(built.path)
    assert history.adds[path.relative_to(built.path).as_posix()] == {merge}
    validate_repository(built.path)


# ---- convergence P1-C history attacks, re-run against the one predicate


def _attack_stopped_to_resolved_in_place(tmp_path):
    built = build(tmp_path / "s2r", stopped=True)
    old = document_sha256(built.seal)
    good = rankings_of(built.document, built.partner)
    for event_id, document in good.items():
        old_ranking = document_sha256(built.rankings[event_id])
        ma.write_canonical(folder_of(built.path, event_id) / f"{event_id}{bs.RANKING_SUFFIX}", document)
        write(built.record(event_id), built.record(event_id).read_text().replace(old_ranking,
                                                                                 document_sha256(document)))
    built.rankings = good
    resolved = derive(built.document, built.partner, built.rankings, protocol=built.protocols[EVENT])
    ma.write_canonical(built.seal_path(), resolved)
    write(built.record(), built.record().read_text().replace(old, document_sha256(resolved)))
    commit(built.path, "reseal in place")
    return built


def _attack_deleted_d_manifest(tmp_path):
    built, _auth, manifest = full_flow(tmp_path / "del")
    manifest.unlink()
    commit(built.path, "drop D manifest")
    return built


def _attack_delete_and_recreate(tmp_path):
    built = build(tmp_path / "rec")
    data = built.seal_path().read_bytes()
    built.seal_path().unlink()
    commit(built.path, "delete seal")
    built.seal_path().write_bytes(data)
    commit(built.path, "re-create")
    return built


def _attack_rename_and_back(tmp_path):
    built = build(tmp_path / "ren")
    rel = built.seal_path().relative_to(built.path).as_posix()
    git(built.path, "mv", rel, rel + ".tmp")
    commit(built.path, "rename away")
    git(built.path, "mv", rel + ".tmp", rel)
    commit(built.path, "rename back")
    return built


def _attack_mode_change(tmp_path):
    built = build(tmp_path / "mode")
    git(built.path, "update-index", "--chmod=+x", built.seal_path().relative_to(built.path).as_posix())
    git(built.path, "commit", "-q", "-m", "chmod")
    return built


def _attack_citation_changed_and_reverted(tmp_path):
    built = build(tmp_path / "cite")
    original = built.record().read_text()
    write(built.record(), original.replace(document_sha256(built.seal), "0" * 64))
    commit(built.path, "bad citation")
    write(built.record(), original)
    commit(built.path, "revert citation")
    return built


def _attack_evil_merge_rewrite(tmp_path):
    built = build(tmp_path / "evil")
    git(built.path, "checkout", "-q", "-b", "side")
    commit(built.path, "side")
    git(built.path, "checkout", "-q", "main")
    commit(built.path, "main")
    git(built.path, "merge", "-q", "--no-ff", "--no-commit", "side")
    changed = dict(built.seal, recordedBy="someone else")
    ma.write_canonical(built.seal_path(), changed)
    write(built.record(), built.record().read_text().replace(document_sha256(built.seal), document_sha256(changed)))
    commit(built.path, "evil merge")
    return built


def _attack_branch_reseal_merged(tmp_path):
    built = build(tmp_path / "branch")
    git(built.path, "checkout", "-q", "-b", "side", built.commits["R"])
    changed = dict(built.seal, recordedBy="side branch")
    ma.write_canonical(built.seal_path(), changed)
    append(built.record(), bs.seal_citation(GATE, document_sha256(changed)))
    commit(built.path, "side reseal")
    git(built.path, "checkout", "-q", "main")
    subprocess.run(["git", "-C", str(built.path), "-c", "user.name=t", "-c", "user.email=t@example.invalid", "merge",
                    "-q", "--no-ff", "--no-commit", "-X", "theirs", "side"], capture_output=True, check=False)
    ma.write_canonical(built.seal_path(), changed)
    commit(built.path, "merge side reseal")
    return built


def _attack_shallow_clone(tmp_path):
    built = build(tmp_path / "deep")
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", built.path.as_uri(), str(shallow)], check=True,
                   capture_output=True)
    built.path = shallow
    return built


HISTORY_ATTACKS = {
    "stopped-to-resolved-in-place": _attack_stopped_to_resolved_in_place,
    "deleted-d-manifest": _attack_deleted_d_manifest,
    "delete-and-recreate": _attack_delete_and_recreate,
    "rename-and-back": _attack_rename_and_back,
    "mode-change": _attack_mode_change,
    "citation-changed-and-reverted": _attack_citation_changed_and_reverted,
    "evil-merge-rewrite": _attack_evil_merge_rewrite,
    "branch-reseal-merged": _attack_branch_reseal_merged,
    "shallow-clone": _attack_shallow_clone,
}


@pytest.mark.parametrize("attack", sorted(HISTORY_ATTACKS))
def test_gate_and_repository_refuse_every_history_attack(tmp_path, attack):
    built = HISTORY_ATTACKS[attack](tmp_path)
    repository = code_of(validate_repository, built.path)
    with ma.canonical_for_tests(str(tmp_path / "unused.git")), ma.github_api_for_tests(protected_api()):
        gate = code_of(ma.open_protected_d, built.path, EVENT)
    assert repository != "accepted" and gate != "accepted", (attack, repository, gate)
    assert repository == gate, (attack, repository, gate)  # the gate runs the repository predicate first


def test_cli_style_decision_check_runs_the_repository_predicate(tmp_path):
    built, auth, _manifest = full_flow(tmp_path / "r")
    commit_decisions(built, auth)
    decision_doc = json.loads((built.folder / f"{EVENT}-decision.json").read_text())
    snapshot = json.loads((built.folder / f"{EVENT}-evidence-ledger-decided.json").read_text())
    validate_decision(decision_doc, snapshot, snapshot, repo=built.path)
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", built.path.as_uri(), str(shallow)], check=True,
                   capture_output=True)
    refused("model_selection_history_unavailable", validate_decision, decision_doc, snapshot, snapshot, repo=shallow)


def test_group_decisions_must_carry_the_identical_authority_block(tmp_path):
    built, auth, _manifest = full_flow(tmp_path / "r")
    commit_decisions(built, auth, mutate_partner=lambda b: b.update(frontier=b["rankedCompositions"][:2]))
    refused("composition_authority_differs_between_group_events", validate_repository, built.path)


def test_a_decision_needs_an_opened_protected_d(tmp_path):
    built = build(tmp_path / "r")
    auth = open_d(built)
    git(built.path, "update-ref", "refs/remotes/origin/main", auth.anchor_commit)
    commit_decisions(built, auth, with_results=False)
    refused("decision_without_d_manifest", validate_repository, built.path)


def test_the_recorded_composition_block_is_never_rewritten(tmp_path):
    built, auth, _manifest = full_flow(tmp_path / "r")
    commit_decisions(built, auth, state_name="TECHNICAL_DECISION_RECORDED", chosen=False)
    validate_repository(built.path)
    commit_decisions(built, auth)  # the implementation composition is chosen later: allowed
    validate_repository(built.path)
    commit_decisions(built, auth, mutate=lambda b: b.update(frontier=b["rankedCompositions"][:2]))
    refused("composition_authority_rewritten", validate_repository, built.path)


def test_a_stopped_group_holds_no_d_manifest(tmp_path):
    built = build(tmp_path / "r", stopped=True)
    manifest = {"schema": bs.D_MANIFEST_SCHEMA, "eventId": EVENT, "manifestId": "RUN-1",
                "groupId": built.state().group_id, "resultSha256": sha("d"), "anchorCommit": built.commits["S0"],
                "ordinaryCompositionsSha256": sha("u"),
                "baselineSeals": [{"compositionId": GATE, "sealSha256": document_sha256(built.seal),
                                   "sealCommit": built.commits["S0"]}]}
    ma.write_canonical(built.folder / f"{EVENT}{bs.D_MANIFEST_INFIX}RUN-1.json", manifest)
    commit(built.path, "D under a stop")
    refused("baseline_stopped_no_d_result", validate_repository, built.path)


# ================================================================== repository-wide guards


IMMUTABLE_SUFFIXES = ("-evidence-ledger-frozen.json", "-evidence-ledger-decided.json", "-protocol.md")


def _git_in_repo(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False,
                          cwd=Path(__file__).resolve().parents[3])


def test_committed_frozen_artefacts_never_change_and_no_ledger_turns_m3_retroactively():
    """Against the merge-base with origin/main: a frozen ledger, decision snapshot, protocol or M3 artefact that existed
    there is never modified or deleted, and no ledger that existed there switches to msr-v1-m3 (M3 is not
    retroactive). CI checks out full history for this test; outside CI it is skipped only when origin/main is
    unavailable."""
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
        immutable = name.startswith("msr-") and (name.endswith(IMMUTABLE_SUFFIXES) or ma.artefact_event(name))
        assert not immutable, f"{status} {path}"
        if status[0] == "M" and name.endswith("-evidence-ledger.json"):
            before = json.loads(_git_in_repo("show", f"{base_sha}:{path}").stdout)
            after = json.loads((Path(__file__).resolve().parents[3] / path).read_text(encoding="utf-8"))
            assert not (before.get("methodRevision") != "msr-v1-m3" and after.get("methodRevision") == "msr-v1-m3"), path


def test_published_schemas_accept_the_derived_documents():
    jsonschema = pytest.importorskip("jsonschema")
    schemas = Path(__file__).resolve().parents[1] / "model_selection" / "schemas"

    def load(name):
        return json.loads((schemas / name).read_text())
    seal_schema = load("mavi-model-selection-baseline-seal-v1.schema.json")
    ranking_schema = load("mavi-model-selection-component-ranking-v1.schema.json")
    d_schema = load("mavi-model-selection-d-manifest-v1.schema.json")
    assert not (schemas / "mavi-model-selection-layer-a-result-v1.schema.json").exists()
    state = group()
    jsonschema.validate(state.seal, seal_schema)
    jsonschema.validate(stopped_group().seal, seal_schema)
    for document in state.rankings.values():
        jsonschema.validate(document, ranking_schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(dict(stopped_group().seal, partnerCandidateId="PD-A"), seal_schema)
    binding = bs.SealBinding(GATE, state.seal_sha256, S0, "PD-A", identity_of("pda"), state.seal["compositionSha256"])
    auth = ma.DAuthorization(state.group_id, ANCHOR, (binding,), state.seal["ordinaryCompositionsSha256"], EVENT)
    jsonschema.validate(ma.d_manifest_document(auth, "RUN-1", sha("d")), d_schema)


# probe_licence (cold review): pinned as a permanent test. Refused cases must stay refused; the cases that pass are the
# declared residual R4 (spacing, paraphrase, confusables outside the folded table), a reviewer obligation (M1 §9).
LICENCE_PROBE = {
    "Licence restricts redistribution": True, "License Plates": False, "  licence   plate ": False,
    "license-plate": True, "license\u200b plate": False, "license\u00a0plate": False, "license\u3000plate": False,
    "license plate.": True, "lic\u00adense restricts use": True,
    "\U0001d425\U0001d422\U0001d41c\U0001d41e\U0001d427\U0001d42c\U0001d41e": True, "l\u0456cense": True,
    "\u0142icense terms forbid bundling": False, "l\u00b7icense": False, "L\u0130CENSE": True, "\u2113icense": True,
    "\u13de\u13a5cense": False, "l i c e n s e": False, "AGPL-3.0 weights; cannot be bundled in the Model Pack": False,
    "copyleft terms make redistribution impossible": False, "lisence not cleared": False, "LICENSE": True,
    "https://github.com/x/license-plate-detector": True, "\u216cicense": True,
    "\uff4c\uff49\uff43\uff45\uff4e\uff53\uff45": True, "l\u0336icense": True, "l1cense": True, "|icense": False,
    "Iicense": False,
}


@pytest.mark.parametrize("value", sorted(LICENCE_PROBE))
def test_probe_licence_cases_are_pinned(value):
    from model_selection.credibility import has_licence_wording
    assert has_licence_wording(value) is LICENCE_PROBE[value], repr(value)


# ================================================================== final convergence review (#220): permanent regressions


# ---- P2-1: every M3 event file is add-only by default; decisions are versioned, never erased


def _erase(built: Built, *, events=(EVENT, PARTNER_EVENT), decision=True, decided=True):
    for e in events:
        folder = folder_of(built.path, e)
        if decision:
            (folder / f"{e}-decision.json").unlink()
        if decided:
            (folder / f"{e}-evidence-ledger-decided.json").unlink()


def _decided(tmp_path):
    built, auth, manifest = full_flow(tmp_path / "r")
    commit_decisions(built, auth)
    validate_repository(built.path)
    return built, auth, manifest


def _abandon(built: Built, manifest: Path):
    evidence = json.loads(manifest.read_text())["resultSha256"]
    for e in (EVENT, PARTNER_EVENT):
        append(built.record(e), ma.abandonment_line("baseline-d-unavailable", evidence))


def test_p2_1_the_reviewers_two_step_escape_is_refused(tmp_path):
    """probe2: delete the decision and the decided ledger, then abandon the group."""
    built, _auth, manifest = _decided(tmp_path)
    _erase(built)
    commit(built.path, "step 1: erase the recorded decisions")
    refused("m3_versioned_file_deleted", validate_repository, built.path)
    _abandon(built, manifest)
    commit(built.path, "step 2: abandon the group")
    assert code_of(validate_repository, built.path) in ("m3_versioned_file_deleted", "abandonment_after_decision")


def test_p2_1_abandonment_is_refused_whenever_a_decision_was_ever_committed(tmp_path):
    built, _auth, manifest = _decided(tmp_path)
    _abandon(built, manifest)
    commit(built.path, "abandon after a recorded decision")
    refused("abandonment_after_decision", validate_repository, built.path)


ERASURES = {
    "decision-only": lambda b: _erase(b, decided=False),
    "decided-ledger-only": lambda b: _erase(b, decision=False),
    "one-event": lambda b: _erase(b, events=(PARTNER_EVENT,)),
}


@pytest.mark.parametrize("mode", ["direct", "merge-resolution", "side-branch"])
@pytest.mark.parametrize("erasure", sorted(ERASURES))
def test_p2_1_erasing_a_recorded_decision_is_refused_in_every_shape(tmp_path, erasure, mode):
    built, _auth, _manifest = _decided(tmp_path)
    _apply(built, ERASURES[erasure], mode)
    refused("m3_versioned_file_deleted", validate_repository, built.path)


def test_p2_1_delete_and_recreate_or_rename_of_a_decision_is_refused(tmp_path):
    built, _auth, _manifest = _decided(tmp_path)
    path = built.folder / f"{EVENT}-decision.json"
    data = path.read_bytes()
    path.unlink()
    commit(built.path, "delete the decision")
    path.write_bytes(data)
    commit(built.path, "re-create the same decision")
    refused("m3_versioned_file_deleted", validate_repository, built.path)
    built, _auth, _manifest = _decided(tmp_path / "rename")
    rel = (built.folder / f"{EVENT}-decision.json").relative_to(built.path).as_posix()
    git(built.path, "mv", rel, rel + ".bak")
    commit(built.path, "rename the decision away")
    git(built.path, "mv", rel + ".bak", rel)
    commit(built.path, "and back")
    assert code_of(validate_repository, built.path) in ("m3_versioned_file_deleted", "m3_unclassified_event_file")


def test_p2_1_legitimate_pre_decision_abandonment_still_passes(tmp_path):
    built, _auth, manifest = full_flow(tmp_path / "r")
    _abandon(built, manifest)
    commit(built.path, "ABANDONED before any decision")
    validate_repository(built.path)


def test_p2_1_an_unclassified_file_in_an_event_namespace_is_refused(tmp_path):
    for name in (f"{EVENT}-notes.txt", f"{EVENT}-decision-v2.json", f"{EVENT}-baseline-seal.json"):
        built = build(tmp_path / name.replace(".", "-"))
        write(built.folder / name, "{}")
        commit(built.path, "a file the registry does not know")
        refused("m3_unclassified_event_file", validate_repository, built.path)


def test_p2_1_every_historical_decision_block_must_agree():
    state = group()
    one = authority_block(state, implementation=None)
    chosen = authority_block(state)
    ma._check_blocks_agree([one, chosen, chosen], "d")  # null, then the chosen composition: allowed
    refused("composition_authority_rewritten", ma._check_blocks_agree,
            [chosen, authority_block(state, implementation="C-PD-A--VC-EMG")], "d")
    other = copy.deepcopy(chosen)
    other["frontier"] = other["rankedCompositions"][:2]
    refused("composition_authority_rewritten", ma._check_blocks_agree, [chosen, other], "d")


def test_p2_1_the_registry_classifies_every_event_file_and_every_policy_is_justified():
    names = {f"{EVENT}-evidence-ledger.json": "working-ledger", f"{EVENT}-evidence-ledger-frozen.json": "frozen-ledger",
             f"{EVENT}-evidence-ledger-decided.json": "decided-ledger", f"{EVENT}-protocol.md": "protocol",
             f"{EVENT}.md": "record", f"{EVENT}-addenda.md": "addenda", f"{EVENT}-decision.json": "decision",
             f"{EVENT}-component-ranking.json": "component-ranking", f"{EVENT}-baseline-seal-{GATE}.json": "seal",
             f"{EVENT}-d-manifest-RUN-1.json": "d-manifest", f"{EVENT}-layer-a-{GATE}.json": "legacy-layer-a"}
    for name, cls in names.items():
        assert ma.classify_event_file(name) == [(EVENT, cls)], name
    for cls, _suffix, policy, why in ma.EVENT_FILE_CLASSES:
        assert policy == ma.IMMUTABLE or why, cls  # every exception to add-only states its rationale


# ---- P2-2: the canonical remote is verified outside the repository's configuration


def _redirected(tmp_path):
    """The canonical stand-in holds history WITHOUT the seal; a fake holds the seal; the repository's own config
    rewrites the canonical URL to the fake (probe1)."""
    built = build(tmp_path / "r", stages=("freeze", "rank"))
    canonical = publish(built)
    write_seal(built)
    built.commits["S0"] = commit(built.path, "S0, never published")
    fake = tmp_path / "fake.git"
    git(tmp_path, "init", "-q", "--bare", str(fake))
    git(built.path, "push", "-q", str(fake), "HEAD:refs/heads/main")
    canonical_url = Path(canonical).as_uri()
    git(built.path, "config", f"url.{fake.as_uri()}.insteadOf", canonical_url)
    return built, canonical_url


def test_p2_2_insteadof_redirect_is_reproduced_and_can_no_longer_open_d(tmp_path):
    built, canonical_url = _redirected(tmp_path)
    # reproduction: ordinary Git inside the repository follows the rewrite to the fake, which holds the seal
    advertised = git(built.path, "ls-remote", canonical_url, "refs/heads/main").split()[0]
    assert advertised == built.commits["S0"]
    refused("seal_not_published", open_d, built, remote=canonical_url)


def test_p2_2_global_config_and_environment_cannot_redirect_either(tmp_path, monkeypatch):
    built, canonical_url = _redirected(tmp_path)
    git(built.path, "config", "--unset-all", f"url.{(tmp_path / 'fake.git').as_uri()}.insteadOf")
    global_config = tmp_path / "global.gitconfig"
    global_config.write_text(f'[url "{(tmp_path / "fake.git").as_uri()}"]\n\tinsteadOf = {canonical_url}\n')
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", f"url.{(tmp_path / 'fake.git').as_uri()}.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", canonical_url)
    refused("seal_not_published", open_d, built, remote=canonical_url)


def test_p2_2_the_production_check_refuses_the_file_transport(tmp_path, monkeypatch):
    built = build(tmp_path / "r")
    local = publish(built)
    monkeypatch.setattr(ma, "_canonical", lambda: (local, False))  # a local path standing in for the canonical URL
    with pytest.raises(CredibilityError) as error, ma.github_api_for_tests(protected_api()):
        ma.open_protected_d(built.path, EVENT)
    assert str(error.value).startswith("anchor_unavailable") and "rc=" in str(error.value)


def test_p2_2_legitimate_canonical_anchoring_still_works_through_the_isolated_path(tmp_path):
    built = build(tmp_path / "r")
    auth = open_d(built)  # the test seam: same isolated profile, temporary directory and checks
    assert auth.anchor_commit == built.commits["S0"]


# ---- P2-3: one isolated Git profile; fail-closed work-tree checks (Windows MAX_PATH)


def test_p2_3_one_isolated_profile_for_every_m3_git_call(monkeypatch):
    for name, value in (("GIT_CONFIG_COUNT", "1"), ("GIT_CONFIG_KEY_0", "core.longpaths"), ("GIT_CONFIG_VALUE_0", "false"),
                        ("GIT_CONFIG_PARAMETERS", "'url.x.insteadof'='y'"), ("GIT_CONFIG_GLOBAL", "/tmp/evil"),
                        ("GIT_CONFIG_SYSTEM", "/tmp/evil"), ("GIT_ALTERNATE_OBJECT_DIRECTORIES", "/tmp/o"),
                        ("GIT_OBJECT_DIRECTORY", "/tmp/o"), ("GIT_NAMESPACE", "n"), ("GIT_CEILING_DIRECTORIES", "/"),
                        ("GIT_SSH", "evil"), ("GIT_SSH_COMMAND", "evil"), ("GIT_ASKPASS", "evil"), ("GIT_EXEC_PATH", "/x"),
                        ("GIT_DIR", "/x"), ("GIT_WORK_TREE", "/x"), ("GIT_TRACE2_PERF", "/tmp/t")):
        monkeypatch.setenv(name, value)
    environment = mg.git_environment()
    leaked = sorted(k for k in environment if k.upper().startswith("GIT_") and k.upper() not in mg._KEPT
                    and k not in mg._FIXED)
    assert leaked == [], leaked
    assert environment["GIT_CONFIG_NOSYSTEM"] == "1" and environment["GIT_CONFIG_GLOBAL"] == os.devnull
    assert environment["GIT_TRACE2_PERF"] == "/tmp/t"  # tracing is kept
    assert "core.longpaths=true" in mg.ISOLATION_OPTIONS and "core.fsmonitor=false" in mg.ISOLATION_OPTIONS


def test_p2_3_system_and_global_configuration_are_not_read(tmp_path, monkeypatch):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q")
    global_config = tmp_path / "global.gitconfig"
    global_config.write_text("[alias]\n\tmavitest = status\n[core]\n\tlongpaths = false\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    assert mg._run(repo, ("config", "--get", "alias.mavitest")).returncode == 1
    assert mg._run(repo, ("config", "--get", "core.longpaths")).stdout.decode().strip() == "true"


def test_p2_3_a_modified_committed_file_beyond_max_path_is_detected(tmp_path):
    if os.name != "nt":
        assert "core.longpaths=true" in mg.ISOLATION_OPTIONS
        pytest.skip("MAX_PATH (260 characters) is a Windows limit; on this platform only the profile is checked")
    # the repository root stays short enough for Git's own .git paths; the work-tree files exceed MAX_PATH
    root = tmp_path / ("p" * max(1, 190 - len(str(tmp_path)) - 1))
    built = build(root)
    frozen = built.folder / f"{EVENT}-evidence-ledger-frozen.json"
    record = built.record()
    assert len(str(frozen)) > 260 and len(str(record)) > 260
    bare = tmp_path / "c.git"  # the canonical stand-in at a short path
    git(tmp_path, "init", "-q", "--bare", str(bare))
    git(built.path, "push", "-q", str(bare), "HEAD:refs/heads/main")
    built.remote = str(bare)
    rel = record.relative_to(built.path).as_posix()
    record.write_text(record.read_text() + "a committed record edited in a path beyond MAX_PATH\n")
    # the reviewer's evidence: without core.longpaths, status exits 0 with an empty answer and a stderr complaint
    plain = subprocess.run(["git", "-c", "core.longpaths=false", "-C", str(built.path), "status", "--porcelain", "--",
                            rel], capture_output=True, text=True, env=mg.git_environment())
    assert plain.returncode == 0 and plain.stdout == "" and plain.stderr.strip()
    assert mg.worktree_status(built.path, [rel]) == {rel: " M"}
    refused("m3_file_differs_from_commit", open_d, built)  # the content check also reads beyond MAX_PATH (P2-1)
    git(built.path, "checkout", "-q", "--", rel)
    validate_repository(built.path)  # and a clean file beyond MAX_PATH matches its blob
    frozen.write_text(frozen.read_text() + " ")
    refused("m3_frozen_file_rewritten", validate_repository, built.path)


def test_p2_3_status_stderr_with_exit_zero_is_refused(tmp_path, monkeypatch):
    built = build(tmp_path / "r")
    original = mg._run

    def noisy(repo, args, data=None, **kwargs):
        completed = original(repo, args, data, **kwargs)
        if args and args[0] == "status":
            return subprocess.CompletedProcess(completed.args, 0, completed.stdout, b"error: could not stat a file")
        return completed
    monkeypatch.setattr(mg, "_run", noisy)
    with pytest.raises(mg.GitCommandError) as error:
        mg.worktree_status(built.path, [built.record().relative_to(built.path).as_posix()])
    assert error.value.returncode == 0 and "could not stat" in error.value.stderr


@pytest.mark.parametrize("flag", ["--skip-worktree", "--assume-unchanged"])
def test_p2_3_index_flags_cannot_hide_a_work_tree_edit(tmp_path, flag):
    built = build(tmp_path / "r")
    publish(built)
    frozen = built.folder / f"{EVENT}-evidence-ledger-frozen.json"
    git(built.path, "update-index", flag, frozen.relative_to(built.path).as_posix())
    frozen.write_text(frozen.read_text() + " ")
    refused("worktree_index_flags_hide_changes", open_d, built)
    refused("worktree_index_flags_hide_changes", validate_repository, built.path)


# ---- P3-A: the baseline gate compares exact decimals


@pytest.mark.parametrize("score, base, mpid, passes", [
    (0.7, 0.5, 0.2, True), (0.6, 0.4, 0.2, True), (0.9, 0.8, 0.1, True), (0.12, 0.10, 0.02, True),
    (0.69, 0.5, 0.2, False), (0.59, 0.4, 0.2, False), (0.89, 0.8, 0.1, False), (0.11, 0.10, 0.02, False),
])
def test_p3_a_exactly_baseline_plus_mpid_passes_and_below_fails(score, base, mpid, passes):
    if passes:
        assert not score - base >= mpid  # the reviewer's cases: binary floating point gets these wrong
    block_ = universe(mpid=mpid)
    state = group(m3_ledger(block_=block_), partner_ledger(block=block_))
    scores = {cid: (score if cid == "C-PD-A--VC-EMG" else None) for cid in D_SCORES}
    summary = group_decision(state, block_=authority_block(state, scores=scores, base=base, mpid=mpid,
                                                           implementation=None),
                             state_name="TECHNICAL_DECISION_RECORDED", implementation=None)
    row = next(r for r in summary["compositionAuthority"]["compositionCandidates"]
               if r["compositionId"] == "C-PD-A--VC-EMG")
    assert row["gates"]["baseline"] == ("passed" if passes else "failed")
    check(summary, state)
    flipped = copy.deepcopy(summary)
    target = next(r for r in flipped["compositionAuthority"]["compositionCandidates"]
                  if r["compositionId"] == "C-PD-A--VC-EMG")
    target["gates"]["baseline"] = "failed" if passes else "passed"
    refused("composition_baseline_gate_not_derived", check, flipped, state)


# ---- P3-B: gate-only composition ids never enter the ordinary-id namespace


@pytest.mark.parametrize("composition_id, valid", [
    ("GATE-BASE", True), ("BASELINE-OC5", True), ("C-PD-A--VC-EST", False), ("C-X", False), ("C-GATE", False),
])
def test_p3_b_gate_only_composition_ids_cannot_collide_with_ordinary_ids(composition_id, valid):
    entry = bob()
    entry["benchmarkBaseline"]["compositions"][0]["compositionId"] = composition_id
    document = m3_ledger(baseline(), established(), emerging(), entry)
    if valid:
        validate_ledger(document)
    else:
        refused("gate_only_composition_id_reserved", validate_ledger, document)
    assert bool(mu.COMPOSITION_ID_RE.match("C-PD-A--VC-EST"))


# ---- P3-C: artefact names are parsed by suffix after a full event id


def test_p3_c_capability_ids_containing_artefact_words_parse_correctly(tmp_path):
    for capability in ("plate-layer-a-detector", "ocr-baseline-seal-reader", "x-d-manifest-y",
                       "plate-component-ranking"):
        event = f"msr-{capability}-2026-01"
        assert ma.artefact_event(f"{event}-evidence-ledger.json") is None
        assert ma.artefact_event(f"{event}-baseline-seal-GATE.json") == event
        assert ma.artefact_event(f"{event}-component-ranking.json") == event
        assert ma.classify_event_file(f"{event}.md") == [(event, "record")]
    refused("m3_artefact_name_ambiguous", ma.artefact_event,
            "msr-x-2026-01-baseline-seal-y-2026-01-baseline-seal-Z.json")
    # a non-M3 event of such a capability validates exactly as an ordinary M1 event
    document = ledger(baseline(), established(), emerging(), capability="plate-layer-a-detector")
    write_event(tmp_path, document)
    commit_tree_for_m1(tmp_path)
    validate_repository(tmp_path)


def commit_tree_for_m1(repo: Path):
    git(repo, "init", "-q")
    commit(repo, "M1 event")


# ---- P3-D: only the EXACT refs/heads/main counts


def test_p3_d_an_ambiguous_ls_remote_tail_match_neither_breaks_nor_misleads(tmp_path):
    built = build(tmp_path / "r")
    remote = publish(built)
    git(built.path, "push", "-q", remote, f"{built.commits['F']}:refs/heads/x/refs/heads/main")
    listing = git(built.path, "ls-remote", remote, "refs/heads/main")
    assert len(listing.splitlines()) == 2  # git's tail match returns both
    assert open_d(built, remote=remote).anchor_commit == built.commits["S0"]


def test_p3_d_duplicate_or_missing_exact_ref_lines_refuse(tmp_path, monkeypatch):
    built = build(tmp_path / "r")
    remote = publish(built)
    original = ma._run
    for stdout in (f"{built.commits['S0']}\trefs/heads/main\n{built.commits['F']}\trefs/heads/main\n",
                   f"{built.commits['F']}\trefs/heads/x/refs/heads/main\n"):
        def fake(repo, args, data=None, _out=stdout, **kwargs):
            if args and args[0] == "ls-remote":
                return subprocess.CompletedProcess(["git", *args], 0, _out.encode(), b"")
            return original(repo, args, data, **kwargs)
        monkeypatch.setattr(ma, "_run", fake)
        refused("anchor_unavailable", open_d, built, remote=remote)



# ================================================================== IP-5: M3 Git, gh and ruleset hardening
# Plan rev 4 §4.13 (I1-I4), §10.1 (Q1, A4). The synthetic probes of the #220 convergence review
# (``probe_git_residuals.py``) are permanent tests here; W1 is in test_trusted_tree.py.


def _nested_parent_with_insteadof(tmp_path, target_url: str, redirect_to: str) -> Path:
    """A parent repository whose local config rewrites ``target_url``; the returned directory is nested inside it."""
    parent = tmp_path / "parent"
    parent.mkdir()
    git(parent, "init", "-q")
    git(parent, "config", f"url.{redirect_to}.insteadOf", target_url)
    nested = parent / "scratch"
    nested.mkdir()
    return nested


def test_ip5_i1_probe_parent_repository_config_is_invisible_to_repository_less_git(tmp_path):
    """Probe (1): Git run with ``repo=None`` from a directory nested in another repository must not discover it."""
    nested = _nested_parent_with_insteadof(tmp_path, "https://github.com/", "file:///nonexistent-redirect/")
    completed = mg._run(None, ("config", "--get-regexp", r"url\..*"), cwd=nested)
    assert completed.returncode == 1 and completed.stdout == b"", completed.stdout


def test_ip5_i1_nested_scratch_with_insteadof_still_anchors_on_the_true_tip(tmp_path, monkeypatch):
    """The anchor's temporary directory nested in a repository whose config rewrites the canonical URL to a fake:
    ``ls-remote`` must still advertise the TRUE canonical tip (no refusal, no redirection)."""
    built = build(tmp_path / "r")
    canonical = publish(built)
    fake = tmp_path / "fake.git"
    git(tmp_path, "init", "-q", "--bare", str(fake))
    git(built.path, "push", "-q", str(fake), f"{built.commits['F']}:refs/heads/main")
    nested = _nested_parent_with_insteadof(tmp_path, Path(canonical).as_uri(), fake.as_uri())
    monkeypatch.setattr(ma.tempfile, "tempdir", str(nested))
    auth = open_d(built, remote=Path(canonical).as_uri())
    assert auth.anchor_commit == built.commits["S0"]


def test_ip5_i1_repository_less_git_requires_an_explicit_working_directory():
    with pytest.raises(ValueError):
        mg._run(None, ("version",))


def _small_repo(tmp_path):
    repo = tmp_path / "filt"
    repo.mkdir()
    git(repo, "init", "-q")
    write(repo / "a.json", '{"v":1}\n')
    commit(repo, "c")
    return repo


@pytest.mark.parametrize("attribute", ["filter=hide", "ident", "working-tree-encoding=UTF-16"])
@pytest.mark.parametrize("where", ["info-attributes", "gitattributes"])
def test_ip5_i2_probe_status_altering_attributes_are_refused(tmp_path, attribute, where):
    """Probe (2a): a repository-local clean filter (or ident / encoding) can make an edited file look clean."""
    repo = _small_repo(tmp_path)
    git(repo, "config", "filter.hide.clean", "git show HEAD:a.json")
    if where == "info-attributes":
        write(repo / ".git" / "info" / "attributes", f"a.json {attribute}\n")
    else:
        write(repo / ".gitattributes", f"a.json {attribute}\n")
        git(repo, "add", ".gitattributes")
        git(repo, "commit", "-q", "-m", "attributes")
    write(repo / "a.json", '{"v":2}\n')
    with pytest.raises(CredibilityError) as error:
        mg.worktree_status(repo, ["a.json"])
    assert str(error.value).startswith("worktree_attribute_hides_changes:a.json:"), str(error.value)


def test_ip5_i2_probe_ignored_files_are_reported_as_dirty(tmp_path):
    """Probe (2b): ``info/exclude`` (or any ignore rule) hid an untracked file from ``worktree_status``."""
    repo = _small_repo(tmp_path)
    write(repo / ".git" / "info" / "exclude", "extra.json\n")
    write(repo / "extra.json", "{}\n")
    assert mg.worktree_status(repo, ["extra.json"]) == {"extra.json": "!!"}
    assert mg.worktree_status(repo, ["a.json"]) == {}


def test_ip5_i2_an_ignored_file_in_a_group_folder_keeps_d_closed(tmp_path):
    built = build(tmp_path / "r")
    publish(built)
    write(built.path / ".git" / "info" / "exclude", "scratch-notes.txt\n")
    write(built.folder / "scratch-notes.txt", "an ignored, uncommitted file in a group folder")
    validate_repository(built.path)  # the repository check does not look at untracked files
    refused("group_state_not_clean", open_d, built)


def test_ip5_i2_a_clean_filter_on_an_m3_artefact_is_refused_by_repository_and_gate(tmp_path):
    built = build(tmp_path / "r")
    publish(built)
    rel = built.seal_path().relative_to(built.path).as_posix()
    git(built.path, "config", "filter.hide.clean", f"git show HEAD:{rel}")
    write(built.path / ".git" / "info" / "attributes", "*.json filter=hide\n")
    tampered = copy.deepcopy(built.seal)
    tampered["stopReason"] = "tampered"
    ma.write_canonical(built.seal_path(), tampered)
    refused("worktree_attribute_hides_changes", validate_repository, built.path)
    refused("worktree_attribute_hides_changes", open_d, built)


def _stat_preserving_edit(path: Path, data: bytes) -> None:
    """Replace a file's bytes with a same-size edit and restore its mtime: Git's stat cache then trusts the index (on
    Windows ctime is the creation time, so ``git status`` reports the file clean; reproduced on this host)."""
    before = path.stat()
    assert len(data) == before.st_size
    path.write_bytes(data)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))


def _same_size_variant(data: bytes) -> bytes:
    index = data.index(b"0")  # a digit inside a hash or a date: same size, still parseable
    return data[:index] + b"1" + data[index + 1:]


@pytest.mark.parametrize("kind", ["seal", "ranking", "frozen"])
def test_ip5_i2_a_status_blind_edit_of_an_immutable_file_is_caught_by_the_content_check(tmp_path, kind, monkeypatch):
    """Any status blind spot (simulated) leaves the content check. A protocol edit is not listed: its LF hash is cited
    by the record, so ``check_event_files`` refuses it first (the content check is then defence in depth)."""
    built = build(tmp_path / "r")
    path = {"seal": built.seal_path(), "ranking": built.folder / f"{EVENT}{bs.RANKING_SUFFIX}",
            "frozen": built.folder / f"{EVENT}-evidence-ledger-frozen.json"}[kind]
    data = path.read_bytes()
    path.write_bytes(data + b" " if kind == "frozen" else _same_size_variant(data))  # same document / same size
    monkeypatch.setattr(ma, "worktree_status", lambda repo, paths: {})
    code = "m3_frozen_file_rewritten" if kind == "frozen" else "baseline_artefact_rewritten_in_history"
    assert code_of(validate_repository, built.path) == code


def test_ip5_i2_a_same_size_mtime_preserving_edit_is_refused_without_simulation(tmp_path):
    built = build(tmp_path / "r")
    old = 1_600_000_000_000_000_000  # an mtime well before the index write, so the entry is not "racily clean"
    os.utime(built.seal_path(), ns=(old, old))
    git(built.path, "update-index", "--refresh")
    _stat_preserving_edit(built.seal_path(), _same_size_variant(built.seal_path().read_bytes()))
    if os.name == "nt":  # the reproduction: Git's own status is blind to this edit on Windows
        rel = built.seal_path().relative_to(built.path).as_posix()
        assert git(built.path, "status", "--porcelain", "--", rel) == ""
    refused("baseline_artefact_rewritten_in_history", validate_repository, built.path)


def test_ip5_i2_a_crlf_checkout_is_accepted(tmp_path):
    """A normal Windows checkout (``core.autocrlf=true``) of an LF-only group verifies and opens D unchanged."""
    built = build(tmp_path / "r")
    publish(built)
    git(built.path, "config", "core.autocrlf", "true")
    for path in list(built.folder.parent.rglob("*")):
        if path.is_file():
            path.unlink()
    git(built.path, "-c", "core.autocrlf=true", "checkout", "-q", "--", ".")  # the helper pins autocrlf=false
    assert b"\r\n" in built.record().read_bytes() and b"\r\n" in built.seal_path().read_bytes()
    validate_repository(built.path)
    assert open_d(built).anchor_commit == built.commits["S0"]


@pytest.mark.parametrize("lf_only", [True, False])
def test_ip5_i2_immutable_blob_matches_is_generic_and_path_independent(tmp_path, lf_only):
    repo = tmp_path / "g"
    repo.mkdir()
    git(repo, "init", "-q")
    for rel in ("any/where/record.json", "other.md"):
        write(repo / rel, '{"a":1}\n')
    commit(repo, "c")
    crlf = '{"a":1}\r\n'.encode("ascii")
    for rel in ("any/where/record.json", "other.md"):
        blob = git(repo, "rev-parse", f"HEAD:{rel}")
        assert mg.immutable_blob_matches(repo, rel, blob, lf_only=lf_only)
        (repo / rel).write_bytes(crlf)  # a CRLF checkout of an LF blob
        assert mg.immutable_blob_matches(repo, rel, blob, lf_only=lf_only)
        (repo / rel).write_bytes(b'{"a":2}\n')
        assert not mg.immutable_blob_matches(repo, rel, blob, lf_only=lf_only)
        (repo / rel).unlink()
        assert not mg.immutable_blob_matches(repo, rel, blob, lf_only=lf_only)


def test_ip5_i2_an_lf_only_class_with_a_crlf_blob_fails_closed(tmp_path):
    """The LF-only assumption is stated: a committed CRLF blob never matches its own work-tree copy as LF-only."""
    repo = tmp_path / "g"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "x.json").write_bytes('{"a":1}\r\n'.encode("ascii"))
    commit(repo, "c")
    blob = git(repo, "rev-parse", "HEAD:x.json")
    assert not mg.immutable_blob_matches(repo, "x.json", blob, lf_only=True)
    assert mg.immutable_blob_matches(repo, "x.json", blob, lf_only=False)


# ---- I3: gh environment, host identity, repository identity


def test_ip5_i3_open_protected_d_and_the_ruleset_check_take_no_api_parameter(tmp_path):
    built = build(tmp_path / "r")
    with pytest.raises(TypeError):
        ma.open_protected_d(built.path, EVENT, github_api=protected_api())
    with pytest.raises(TypeError):
        ma.verify_default_branch_protection(protected_api())
    with pytest.raises(TypeError):
        ma.check_group_authority(None, "g", mode="pre_d", github_api=protected_api())


def test_ip5_i3_the_test_seam_is_scoped_and_restored():
    api = protected_api()
    assert ma._github_api() is ma.gh_api
    with ma.github_api_for_tests(api):
        assert ma._github_api() is api
        assert ma.verify_default_branch_protection() == 7
    assert ma._github_api() is ma.gh_api


def test_ip5_i3_gh_environment_is_scrubbed_and_pinned(monkeypatch):
    for name, value in (("GH_HOST", "evil.example"), ("GH_CONFIG_DIR", "/tmp/evil"), ("GH_REPO", "evil/x"),
                        ("GH_ENTERPRISE_TOKEN", "e"), ("GITHUB_ENTERPRISE_TOKEN", "e"), ("GITHUB_API_URL", "http://x"),
                        ("GH_DEBUG", "api"), ("GH_PATH", "/tmp/gh"), ("GH_TOKEN", "t1"), ("GITHUB_TOKEN", "t2"),
                        ("SSL_CERT_FILE", "/tmp/ca.pem"), ("SSL_CERT_DIR", "/tmp/ca")):
        monkeypatch.setenv(name, value)
    environment = ma.gh_environment()
    assert environment["GH_HOST"] == "github.com" and environment["GH_PROMPT_DISABLED"] == "1"
    assert environment["GH_TOKEN"] == "t1" and environment["GITHUB_TOKEN"] == "t2"
    kept = {k.upper() for k in environment if k.upper().startswith(("GH_", "GITHUB_"))}
    assert kept <= {"GH_HOST", "GH_TOKEN", "GITHUB_TOKEN", "GH_PROMPT_DISABLED", "GH_NO_UPDATE_NOTIFIER",
                    "GH_NO_EXTENSION_UPDATE_NOTIFIER", "GH_SPINNER_DISABLED"}, kept
    assert not {"SSL_CERT_FILE", "SSL_CERT_DIR"} & {k.upper() for k in environment}


def test_ip5_i3_gh_api_pins_the_host_and_the_repository(monkeypatch):
    seen = []

    def fake_run(argv, **kwargs):
        seen.append((argv, kwargs.get("env")))
        return subprocess.CompletedProcess(argv, 0, b"{}", b"")
    monkeypatch.setattr(ma.subprocess, "run", fake_run)
    assert ma.gh_api("repos/hariomahlawat/MAVI/rulesets/1") == {}
    argv, environment = seen[-1]
    assert argv[:4] == ["gh", "api", "--hostname", "github.com"] and "--method" in argv and "GET" in argv
    assert argv[-1] == "repos/hariomahlawat/MAVI/rulesets/1" and environment["GH_HOST"] == "github.com"
    for path in ("repos/evil/MAVI", "https://evil.example/repos/hariomahlawat/MAVI", "/repos/hariomahlawat/MAVI",
                 "repos/hariomahlawat/MAVI-other", "graphql", "repos/hariomahlawat/MAVI/../evil",
                 "repos/hariomahlawat/MAVI/x y"):
        refused("protected_default_branch_unverifiable", ma.gh_api, path)


@pytest.mark.parametrize("scope", ["global", "host"])
def test_ip5_i3_a_gh_unix_socket_configuration_is_refused(tmp_path, monkeypatch, scope):
    if shutil.which("gh") is None:
        pytest.skip("the GitHub CLI is not installed on this host")
    config = tmp_path / "xdg" / "gh"
    config.mkdir(parents=True)
    if scope == "global":
        (config / "config.yml").write_text("http_unix_socket: /tmp/mavi-evil.sock\n")
    else:
        (config / "config.yml").write_text("hosts:\n  github.com:\n    http_unix_socket: /tmp/mavi-evil.sock\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("GH_CONFIG_DIR", str(tmp_path / "ignored"))  # dropped by the scrub
    refused("protected_default_branch_unverifiable", ma.gh_preflight)


def test_ip5_i3_gh_preflight_accepts_a_configuration_without_a_socket(tmp_path, monkeypatch):
    if shutil.which("gh") is None:
        pytest.skip("the GitHub CLI is not installed on this host")
    (tmp_path / "xdg" / "gh").mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    ma.gh_preflight()


def test_ip5_i3_the_production_client_runs_the_preflight_before_any_api_call(monkeypatch):
    order = []
    fake = protected_api()
    monkeypatch.setattr(ma, "gh_preflight", lambda: order.append("preflight"))
    monkeypatch.setattr(ma, "gh_api", lambda path: order.append(path) or fake(path))
    assert ma.verify_default_branch_protection() == 7
    assert order[0] == "preflight" and order[1] == "repos/hariomahlawat/MAVI"


@pytest.mark.parametrize("identity", [("hariomahlawat/MAVI-fork", "main"), ("evil/MAVI", "main"),
                                      ("hariomahlawat/mavi", "main"), ("hariomahlawat/MAVI", "master")])
def test_ip5_i3_a_redirected_repository_identity_is_refused(identity):
    refused("protected_default_branch_unverifiable", verify_protection, protected_api(identity=identity))


# ---- Q1: required `quality` check (integration 15368, strict) and merge-only protection


def test_ip5_q1_the_live_ruleset_shape_is_accepted():
    assert verify_protection(protected_api()) == 7
    assert verify_protection(protected_api(checks=(("quality", 15368),))) == 7


@pytest.mark.parametrize("changes", [
    {"checks": (("Task 10 qualification", 15368),)},
    {"checks": (("quality", 99999), ("Task 10 qualification", 15368))},
    {"checks": (("quality", None),)},
    {"checks": (("Quality", 15368),)},
    {"strict": False},
    {"strict": None},
    {"merge_methods": ("merge", "squash")},
    {"merge_methods": ("squash",)},
    {"merge_methods": ("merge", "rebase")},
    {"merge_methods": ()},
    {"merge_methods": None},
    {"rules": ("deletion", "non_fast_forward", "pull_request")},
    {"rules": ("deletion", "non_fast_forward", "required_status_checks")},
    {"applied_rules": ("deletion", "non_fast_forward", "pull_request")},
    {"applied_rules": ("deletion", "non_fast_forward", "required_status_checks")},
])
def test_ip5_q1_a_ruleset_without_the_required_check_or_merge_only_is_refused(changes):
    refused("protected_default_branch_unverified", verify_protection, protected_api(**changes))


def test_ip5_q1_the_gate_applies_the_predicate(tmp_path):
    built = build(tmp_path / "r")
    refused("protected_default_branch_unverified", open_d, built, api=protected_api(merge_methods=("merge", "squash")))
    refused("protected_default_branch_unverified", open_d, built, api=protected_api(strict=False))


# ---- I4: the line-ending carry-over ignores injected configuration


def test_ip5_i4_injected_line_ending_configuration_is_inert(tmp_path, monkeypatch):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "config", "core.eol", "lf")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "2")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.autocrlf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    monkeypatch.setenv("GIT_CONFIG_KEY_1", "core.eol")
    monkeypatch.setenv("GIT_CONFIG_VALUE_1", "crlf")
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'core.eol'='crlf'")
    assert mg.line_ending_options(repo) == ("-c", "core.autocrlf=false", "-c", "core.eol=lf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "bogus")  # an injected invalid value is not even read
    assert mg.line_ending_options(repo) == ("-c", "core.autocrlf=false", "-c", "core.eol=lf")


# ---- seams: the test-only entry points are referenced only under tests (AST scan)


def test_ip5_test_seams_are_referenced_only_under_tests():
    import ast
    repo = Path(__file__).resolve().parents[3]
    seams = {"canonical_for_tests", "github_api_for_tests", "_TEST_CANONICAL", "_TEST_GITHUB_API"}
    defining = (repo / "tools" / "qualification" / "model_selection" / "m3_authority.py").resolve()
    listed = subprocess.run(["git", "-C", str(repo), "ls-files", "-z", "--", "*.py"], capture_output=True, check=True)
    offenders = []
    for rel in listed.stdout.decode("utf-8").split("\0"):
        path = repo / rel
        if not rel or "tests" in Path(rel).parts or not path.is_file() or path.resolve() == defining:
            continue
        for node in ast.walk(ast.parse(path.read_bytes(), filename=rel)):
            if isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            elif isinstance(node, ast.alias):
                name = node.name.rsplit(".", 1)[-1]
            else:
                continue
            if name in seams:
                offenders.append(f"{rel}:{getattr(node, 'lineno', 0)}:{name}")
    assert offenders == [], offenders


# ---- cold review #222 P2-1: every committed event file is content-checked (repository mode and before protected D)


def test_ip5_cold_p2_1_probe_a_stat_blind_record_edit_cannot_open_d(tmp_path):
    """The cold-review probe (``probe_record_stat_blind.py``): the committed record lacks the seal citation (the
    committed tree is refused), and a same-size, mtime-preserving work-tree edit restores it. Git's status is blind to
    the edit on Windows; both the repository check and the gate must refuse it."""
    built = build(tmp_path / "r", stages=("freeze", "rank"))
    write_seal(built)
    record = built.record()
    text = record.read_text(encoding="utf-8")
    citation = text.rstrip("\n").split("\n")[-1]
    padding = "N" * len(citation)
    write(record, text.replace(citation, padding))
    built.commits["S0"] = commit(built.path, "S0: seal committed, citation replaced by same-length prose")
    publish(built)
    assert code_of(validate_repository, built.path) == "baseline_seal_not_recorded"
    old = 1_600_000_000_000_000_000
    os.utime(record, ns=(old, old))
    git(built.path, "update-index", "--refresh")
    _stat_preserving_edit(record, record.read_bytes().replace(padding.encode(), citation.encode()))
    rel = record.relative_to(built.path).as_posix()
    if os.name == "nt":
        assert git(built.path, "status", "--porcelain", "--", rel) == ""  # the reproduction
    refused("m3_file_differs_from_commit", validate_repository, built.path)
    refused("m3_file_differs_from_commit", open_d, built)


def _versioned_paths(built: Built) -> dict[str, Path]:
    folder = built.folder
    return {"record": built.record(), "partner-record": built.record(PARTNER_EVENT),
            "working-ledger": folder / f"{EVENT}-evidence-ledger.json",
            "decision": folder / f"{EVENT}-decision.json",
            "decided-ledger": folder / f"{EVENT}-evidence-ledger-decided.json"}


def _neutral_edit(path: Path) -> None:
    """An edit no other check sees: trailing prose in Markdown, trailing whitespace in JSON (same document)."""
    data = path.read_bytes()
    path.write_bytes(data + (b"hidden prose\n" if path.suffix == ".md" else b" "))


@pytest.mark.parametrize("kind", ["record", "partner-record", "working-ledger", "decision", "decided-ledger"])
def test_ip5_cold_p2_1_a_status_blind_edit_of_any_committed_event_file_is_refused_by_repository_mode(tmp_path, kind,
                                                                                          monkeypatch):
    built, auth, _manifest = full_flow(tmp_path / "r")
    commit_decisions(built, auth)
    validate_repository(built.path)
    _neutral_edit(_versioned_paths(built)[kind])
    monkeypatch.setattr(ma, "worktree_status", lambda repo, paths: {})  # any status blind spot
    refused("m3_file_differs_from_commit", validate_repository, built.path)


@pytest.mark.parametrize("kind", ["record", "partner-record", "working-ledger"])
def test_ip5_cold_p2_1_a_status_blind_edit_before_d_is_refused_by_the_gate(tmp_path, kind, monkeypatch):
    built = build(tmp_path / "r")
    publish(built)
    _neutral_edit(_versioned_paths(built)[kind])
    monkeypatch.setattr(ma, "worktree_status", lambda repo, paths: {})
    monkeypatch.setattr(mg, "worktree_status", lambda repo, paths: {})
    refused("m3_file_differs_from_commit", open_d, built)


@pytest.mark.parametrize("kind", ["record", "working-ledger"])
def test_ip5_cold_p2_1_a_visible_uncommitted_edit_is_refused_too(tmp_path, kind):
    built = build(tmp_path / "r")
    _neutral_edit(_versioned_paths(built)[kind])
    refused("m3_file_differs_from_commit", validate_repository, built.path)


def test_ip5_cold_p2_1_a_missing_versioned_file_hidden_from_status_is_refused(tmp_path, monkeypatch):
    built = build(tmp_path / "r")
    built.record().unlink()
    monkeypatch.setattr(ma, "worktree_status", lambda repo, paths: {})
    assert code_of(validate_repository, built.path) != "accepted"


def test_ip5_cold_p2_1_committed_version_updates_remain_valid(tmp_path):
    built, auth, _manifest = full_flow(tmp_path / "r")
    commit_decisions(built, auth)
    append(built.record(), "A later prose note in the record.")
    write(built.folder / f"{EVENT}-addenda.md", "2026-07-03: addendum.\n")
    commit(built.path, "a committed record version and addenda")
    validate_repository(built.path)
    append(built.folder / f"{EVENT}-addenda.md", "2026-07-04: second addendum.")
    commit(built.path, "a second addenda version")
    validate_repository(built.path)


def test_ip5_cold_p2_1_a_crlf_checkout_of_a_decided_group_is_accepted(tmp_path):
    built, auth, _manifest = full_flow(tmp_path / "r")
    commit_decisions(built, auth)
    git(built.path, "config", "core.autocrlf", "true")
    for path in list(built.folder.parent.rglob("*")):
        if path.is_file():
            path.unlink()
    git(built.path, "-c", "core.autocrlf=true", "checkout", "-q", "--", ".")
    assert b"\r\n" in built.record().read_bytes()
    validate_repository(built.path)


def test_ip5_cold_p2_1_every_registered_class_has_a_content_policy():
    """Enumerated from the registry, not hand-listed: every class except FORBIDDEN is content-checked; the LF-only
    (blob id) policy is exactly the canonical-JSON classes, and every other class is compared LF-normalised."""
    canonical = {cls for cls, _s, policy, _w in ma.EVENT_FILE_CLASSES if policy == ma.IMMUTABLE and cls not in
                 ("frozen-ledger", "protocol")}
    assert ma.CANONICAL_JSON_CLASSES == canonical
    assert {cls for cls, _s, policy, _w in ma.EVENT_FILE_CLASSES if policy == ma.FORBIDDEN} == {"legacy-layer-a"}
