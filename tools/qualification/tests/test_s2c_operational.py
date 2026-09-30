"""Synthetic counterexamples: no model, imagery or selection evidence is used."""
from __future__ import annotations

import copy
import importlib
import importlib.util
import itertools

import pytest


@pytest.fixture
def op():
    name = "model_selection.operational"
    if importlib.util.find_spec(name) is None:
        class Missing:
            def __getattr__(self, name):
                def missing(*args):
                    pytest.fail(f"b-2 {name} implementation missing")
                return missing
        return Missing()
    return importlib.import_module(name)


def candidate(name, *, kind="learned", extension=False):
    return {"unitId": name, "kind": kind, "components": [] if kind == "disabled" else [name],
            "configurationSha256": "a" * 64, "enabledAttributes": ["colour"],
            "extension": extension, "existingGraph": not extension}


def capability(names=("A", "B", "C"), *, fallback=True):
    units = [candidate(name) for name in names]
    return {"scope": ["colour"], "units": units,
            "fallback": candidate("BASE", kind="baseline") if fallback else None,
            "claims": [{"claimId": "colour", "direction": "higher", "marginsSha256": "b" * 64}],
            "mpidClaims": ["colour"], "mpidComparatorUnavailable": "exclude-pending-ADR",
            "noComparatorAuthoritySha256": None,
            "simultaneousFamily": [{"a": a, "b": b, "claimId": "colour"}
                                   for a, b in itertools.permutations(names, 2)],
            "gateIds": ["absolute-quality", "engineering", "support"]}


def gates(cap):
    return {u["unitId"]: {"preScreen": "pass", "preScreenPartition": "label-free",
            "results": {g: "pass" for g in cap["gateIds"]}, "evidenceClass": "M-D"}
            for u in cap["units"] + ([cap["fallback"]] if cap["fallback"] else [])}


def matrix(cap, default="non-inferior"):
    return [{**row, "outcome": default} for row in cap["simultaneousFamily"]]


def change(rows, a, b, outcome):
    next(row for row in rows if row["a"] == a and row["b"] == b)["outcome"] = outcome


def pair(p, v):
    return {"personUnitId": p, "vehicleUnitId": v}


def measured(p, v, lo, up, **changes):
    row = {"pair": pair(p, v), "H_lo": lo, "H_up": up, "hostClassId": "host",
           "evidenceComplete": True, "constraints": {"warm": True, "recovery": True},
           "operationalEvidenceSha256": "d" * 64}
    row.update(changes)
    return row


def test_direct_protection_is_not_transitive_or_iterative(op):
    cap = capability()
    rows = matrix(cap)
    change(rows, "A", "C", "inconclusive")
    change(rows, "B", "A", "inconclusive")
    change(rows, "C", "B", "inconclusive")
    result = op.quality_sets(cap, gates(cap), rows)
    assert result["E"] == ["A", "B", "C"]
    assert result["F"] == []
    assert result["J"] == ["BASE"]
    assert result["qualityOutcome"] == "NO_QUALITY_PROTECTED_TECHNICAL_CHOICE"


def test_noisy_eligible_comparator_cannot_be_deleted(op):
    cap = capability()
    rows = matrix(cap)
    change(rows, "A", "C", "insufficient-evidence")
    assert "A" not in op.quality_sets(cap, gates(cap), rows)["F"]
    with pytest.raises(ValueError, match="family"):
        op.quality_sets(cap, gates(cap), [r for r in rows if "C" not in (r["a"], r["b"])])


def test_multidimensional_cross_trade_blocks_both(op):
    cap = capability(("A", "B"))
    cap["claims"].append({"claimId": "robustness", "direction": "lower", "marginsSha256": "c" * 64})
    cap["simultaneousFamily"] += [{"a": a, "b": b, "claimId": "robustness"}
                                  for a, b in itertools.permutations(("A", "B"), 2)]
    cap["simultaneousFamily"].sort(key=lambda r: (r["a"], r["b"], r["claimId"]))
    rows = matrix(cap)
    next(r for r in rows if r["a"] == "A" and r["claimId"] == "robustness")["outcome"] = "inconclusive"
    change(rows, "B", "A", "inconclusive")
    assert op.quality_sets(cap, gates(cap), rows)["F"] == []


def test_mpid_runs_before_protection_and_failure_cannot_poison_F(op):
    cap = capability(("A", "X"))
    cap["units"][1].update(extension=True, existingGraph=False)
    rows = matrix(cap)
    change(rows, "A", "X", "inconclusive")
    assert op.quality_sets(cap, gates(cap), rows)["E"] == ["A"]
    assert op.quality_sets(cap, gates(cap), rows)["F"] == ["A"]
    change(rows, "X", "A", "superior")
    assert op.quality_sets(cap, gates(cap), rows)["E"] == ["A", "X"]


def test_comparator_unavailable_is_frozen_and_not_auto_passed(op):
    cap = capability(("X",))
    cap["units"][0].update(extension=True, existingGraph=False)
    result = op.quality_sets(cap, gates(cap), [])
    assert result["E"] == []
    assert result["mpidStatus"] == {"X": "MPID_COMPARATOR_UNAVAILABLE"}


@pytest.mark.parametrize("mutation", ["Q", "direction", "family", "gate", "bool", "reference", "frozen-test"])
def test_quality_refusals(op, mutation):
    cap = capability(("A", "B"))
    evidence = gates(cap)
    rows = matrix(cap)
    if mutation == "Q": cap["claims"] = []
    if mutation == "direction": cap["claims"][0]["direction"] = "guess"
    if mutation == "family": cap["simultaneousFamily"].pop()
    if mutation == "gate": del evidence["A"]
    if mutation == "bool": evidence["A"]["results"]["support"] = True
    if mutation == "reference": cap["units"][0]["unitId"] = "PO-B0"
    if mutation == "frozen-test": evidence["A"]["preScreenPartition"] = "frozen-test"
    with pytest.raises(ValueError): op.quality_sets(cap, evidence, rows)


def test_joint_interaction_and_uncertainty_preserve_exact_pairs(op):
    rows = [measured("P1", "V1", 8, 9), measured("P1", "V2", 3, 5),
            measured("P2", "V1", 4, 4), measured("P2", "V2", 7, 8)]
    result = op.select_pairs([r["pair"] for r in rows], rows, "host", ["warm", "recovery"])
    assert result["T"] == [pair("P1", "V2"), pair("P2", "V1")]
    assert result["outcome"] == "TECHNICAL_TIED_SET"
    rows[1]["H_lo"] = 5
    assert op.select_pairs([r["pair"] for r in rows], rows, "host", ["warm", "recovery"])["T"] == [pair("P2", "V1")]


@pytest.mark.parametrize("value", [True, 1.0, float("inf"), float("nan"), -1])
def test_host_bounds_require_finite_positive_exact_integers(op, value):
    with pytest.raises(ValueError):
        op.select_pairs([pair("P", "V")], [measured("P", "V", value, 2)], "host", ["warm", "recovery"])


def test_mixed_host_class_refused(op):
    with pytest.raises(ValueError, match="host_class"):
        op.select_pairs([pair("P", "V")], [measured("P", "V", 1, 2, hostClassId="other")], "host", ["warm", "recovery"])


def test_empty_F_without_fallback_preserves_no_complete_identity(op):
    cap = capability(("A", "B"), fallback=False)
    result = op.quality_sets(cap, gates(cap), matrix(cap, "inconclusive"))
    assert result["J"] == []
    assert op.select_pairs([], [], "host", ["warm", "recovery"])["outcome"] == "NO_OPERATIONALLY_COMPLETE_IDENTITY"


def test_e3_candidate_mismatch_cannot_rescue_next_pair(op):
    assert op.e3_disposition("candidate-specific") == "TECHNICAL_EVIDENCE_INCOMPLETE_REOPEN"
    assert op.e3_disposition("candidate-independent") == "NUMBERED_METHOD_REVISION_RECOMPUTE_ALL"
    with pytest.raises(ValueError): op.e3_disposition("select-next")


def test_fluid_service_demand_does_not_claim_deadlines(op):
    assert op.fluid_screen([5, 0, 8], [3, 3, 3]) == [2, 0, 5]


def test_contract_cross_loads_b1_and_projection_is_deterministic(op):
    from pathlib import Path
    repo = Path(__file__).resolve().parents[3]
    assert op.validate_repository(repo)
    assert op.render_contract_projection(op.contract()) == op.render_contract_projection(op.contract())


@pytest.mark.parametrize("section", ["prerequisite", "wholeJob", "finalSelection", "experimentFreeze",
                                     "qualityDecisionClaims", "historicalOrdering"])
def test_contract_authority_mutations_refused(op, section):
    doc = copy.deepcopy(op.contract())
    doc[section]["unexpected"] = True
    with pytest.raises(ValueError): op.validate_contract(doc)
