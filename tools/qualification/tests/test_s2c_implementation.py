from __future__ import annotations

import copy

import pytest

from test_s2c_operational import op, capability, candidate, measured, pair
from model_selection_fixtures import baseline, emerging, established, ledger


def data():
    caps = {"person": capability(("VC-EMG",)), "vehicle": capability(("VC-EST",))}
    for cap in caps.values(): cap["fallback"] = candidate("VC-B0", kind="baseline")
    quality = {"person": {"J": ["VC-EMG"], "fallbackOperationallyAvailable": True},
               "vehicle": {"J": ["VC-EST"], "fallbackOperationallyAvailable": True}}
    snapshots = {"person": ledger(emerging(), baseline()), "vehicle": ledger(established(), baseline())}
    licence = {c: {u["unitId"]: {"one": "CLEARED", "two": "CLEARED"}
                   for u in cap["units"]+[cap["fallback"]]} for c, cap in caps.items()}
    rows = [measured(p, v, lo, lo) for p, v, lo in [("VC-EMG", "VC-EST", 1), ("VC-B0", "VC-EST", 4),
                                                    ("VC-B0", "VC-B0", 8), ("VC-EMG", "VC-B0", 5)]]
    return caps, quality, rows, licence, snapshots


def evaluate(op, values=None):
    return op.implementation_sets(*(values or data()), {"person": "2026-09-01", "vehicle": "2026-09-01"},
                                  ["one", "two"], "host", ["warm", "recovery"])


def test_emerging_technical_winner_stays_visible_person_falls_back_vehicle_preserved(op):
    result = evaluate(op)
    assert result["T_r"] == {"one": [pair("VC-EMG", "VC-EST")], "two": [pair("VC-EMG", "VC-EST")]}
    assert result["K_person"] == ["VC-B0"]
    assert result["K_vehicle"] == ["VC-EST"]
    assert result["T_impl"] == [pair("VC-B0", "VC-EST")]


def test_every_component_of_person_composition_must_be_implementable(op):
    values = data()
    values[0]["person"]["units"][0]["components"] = ["VC-EMG", "VC-EST"]
    values[4]["person"] = ledger(emerging(), established(), baseline())
    assert evaluate(op, values)["K_person"] == ["VC-B0"]


def test_licence_filter_recomputes_impl_optimum_does_not_intersect_profile_optima(op):
    values = data()
    cap = values[0]["person"]
    cap["units"] = [candidate("VC-B0", kind="baseline"), candidate("VC-EST")]
    values[1]["person"]["J"] = ["VC-B0", "VC-EST"]
    values[1]["vehicle"]["J"] = ["VC-B0", "VC-EST"]
    values[4]["person"] = ledger(baseline(), established())
    values[3]["person"] = {"VC-B0": {"one": "CLEARED", "two": "CLEARED"},
                           "VC-EST": {"one": "CLEARED", "two": "NOT_CLEARED"}}
    values[3]["vehicle"]["VC-EST"]["one"] = "NOT_CLEARED"
    values[2][:] = [measured(p, v, n, n) for p, v, n in [("VC-EST", "VC-B0", 1), ("VC-B0", "VC-EST", 2),
                                                        ("VC-B0", "VC-B0", 5), ("VC-EST", "VC-EST", 3)]]
    result = evaluate(op, values)
    assert result["T_r"]["one"] == [pair("VC-EST", "VC-B0")]
    assert result["T_r"]["two"] == [pair("VC-B0", "VC-EST")]
    assert result["T_impl"] == [pair("VC-B0", "VC-B0")]


def test_fallback_in_J_survives_Cr_C_all(op):
    values = data()
    values[1]["person"]["J"] = ["VC-B0"]
    result = evaluate(op, values)
    assert result["C_all"] == [pair("VC-B0", "VC-EST")]


def test_disabled_fallback_is_vacuously_implementable_but_needs_own_clearance(op):
    values = data()
    disabled = candidate("DISABLED", kind="disabled")
    disabled["enabledAttributes"] = []
    values[0]["person"]["fallback"] = disabled
    del values[3]["person"]["VC-B0"]
    values[3]["person"]["DISABLED"] = {"one": "CLEARED", "two": "CLEARED"}
    values[2].append(measured("DISABLED", "VC-EST", 3, 3))
    assert evaluate(op, values)["K_person"] == ["DISABLED"]
    values[3]["person"]["DISABLED"]["two"] = "REVIEW_PENDING"
    result = evaluate(op, values)
    assert result["K_person"] == [] and result["pending"] is True


def test_missing_licence_or_decision_date_backdated_before_history_refused(op):
    values = data()
    del values[3]["person"]["VC-EMG"]["two"]
    with pytest.raises(ValueError): evaluate(op, values)
    values = data()
    with pytest.raises(ValueError):
        op.implementation_sets(*values, {"person": "2026-05-01", "vehicle": "2026-05-01"},
                               ["one", "two"], "host", ["warm", "recovery"])


def test_failed_fallback_cannot_enter_K_even_when_licence_cleared(op):
    values = data()
    values[1]["person"]["fallbackOperationallyAvailable"] = False
    assert evaluate(op, values)["K_person"] == []



def test_implementation_preserves_relevant_unresolved_status(op):
    values = data()
    row = next(r for r in values[2] if r["pair"] == pair("VC-B0", "VC-EST"))
    row.update(evidenceComplete=False, H_lo=None, H_up=None)
    result = evaluate(op, values)
    assert result["T_impl"] == []
    assert result["unresolvedOperationalPairs"] == [row["pair"]]
    # An inadmissible emerging pair cannot change the implementation population.
    row["evidenceComplete"] = True
    row["H_lo"] = row["H_up"] = 4
    values[2][0].update(evidenceComplete=False, H_lo=None, H_up=None)
    result = evaluate(op, values)
    assert result["unresolvedOperationalPairs"] == []
    assert result["unresolvedProfilePairs"]["one"] == [values[2][0]["pair"]]
