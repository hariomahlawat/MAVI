"""MSR revision M3, Amendment A1 (Stage-4 integration plan Rev 5, IP-1): the regression matrix rows of plan §10.1.

Synthetic fixtures only (shared with ``test_model_selection_m3.py``); no protected D, no network, no real event.

Matrix rows (plan §10.1; X and R are specified by §4.1 and §4.2, enumerated here):

* **X1-X7 exact D scoring (§4.1).** X1 ``dScoreExact`` shape (integers, reduced, denominator bound, null iff the display
  is null); X2 the float ``dScore`` / ``comparativeScore`` are displays equal to ``float(exact)`` (float against float);
  X3 the exact MPID boundary 131/150 vs 5/6 at MPID 0.04 (= 1/25 exactly) passes where the float path fails; X4 exact
  rational ties stay permitted ties; X5 two distinct rationals with one display float: the composition ranking and
  ``strongestEvaluatedComposition`` follow the exact maximum (no collision refusal); X6 the same through the
  per-component projection (``strongestEvaluatedTechnical``, rows); X7 ``strongestClearedPerProfile`` exact, and M1
  decisions unchanged (float maxima, float ties).
* **R1-R7 ``lexicographic-missing-last-v1`` (§4.2).** R1 a null ``last`` metric on a passing row ranks after every
  finite value; R2 a null ``forbidden`` metric on a passing row is refused and STOPs the seal; R3 a failing row may
  carry nulls and is never ranked; R4 ``lexicographic-v1`` unchanged; R5 the rule shape is closed; R6 non-finite or
  non-number metrics are invalid; R7 nulls never invent a score (ties still STOP) and the Stage-4 constants and the
  published ranking schema accept the permitted case.
* **P1-P3 minimum evaluable population (§4.10).** P1 one evaluable candidate STOPs; P2 every candidate failing a
  ranking gate STOPs, and an empty U is refused at the pre-D gate; P3 a RESOLVED seal with one evaluable candidate is
  not derivable.
* **AB1-AB3 abandonment (§4.7).** AB1 the two new reasons are accepted with a committed D-manifest result; AB2 any other
  reason is refused; AB3 abandonment after a decision is refused for the new reasons too.
* **MB1-MB3 D-result / manifest binding (§6.6, M3 side of §3 item 11).** MB1 every row and the baseline cite a
  committed group D manifest; MB2 a result cited twice is refused; MB3 two manifests with one result are refused.
"""

from __future__ import annotations

import copy
import json
import math
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

import test_model_selection_m3 as base
from model_selection import baseline_seal as bs
from model_selection import m3_authority as ma
from model_selection import m3_universe as mu
from model_selection.credibility import CredibilityError, document_sha256, validate_decision, validate_ledger, \
    validate_repository
from model_selection_fixtures import decision, sha

EVENT, PARTNER_EVENT, GATE = base.EVENT, base.PARTNER_EVENT, base.GATE
refused, code_of = base.refused, base.code_of

BIG = Fraction(4 * 10**18 + 1, 5 * 10**18)  # distinct from 4/5, same display float 0.8 (plan probe)
BASE = Fraction(1, 2)


def exact(value: Fraction | None):
    return None if value is None else {"numerator": value.numerator, "denominator": value.denominator}


def mpid_of(state) -> Fraction:
    return Fraction(Decimal(str(state.universe["mpid"])))


def default_scores() -> dict[str, Fraction]:
    return {cid: Fraction(str(v)) for cid, v in base.D_SCORES.items()}


def exact_block(state, scores=None, *, base_score=BASE, anchor=base.ANCHOR, implementation="C-PD-A--VC-EST"):
    """A ``compositionAuthority`` block carrying canonical exact D scores and their float displays."""
    scores = default_scores() if scores is None else scores
    mpid = mpid_of(state)
    rows, passing = [], {}
    for item in state.ordinary:
        cid = item["compositionId"]
        score = scores.get(cid)
        passed = score is not None and base_score is not None and score - base_score >= mpid
        gates = {"baseline": "passed" if passed else "failed", "consistent-wrong": "passed"}
        technical = "passed" if all(v == "passed" for v in gates.values()) else "failed"
        if technical == "passed":
            passing[cid] = score
        rows.append({"compositionId": cid, "components": copy.deepcopy(item["components"]), "gates": gates,
                     "dScore": None if score is None else float(score), "dScoreExact": exact(score),
                     "technicalGates": technical,
                     "comparativeScore": float(score) if technical == "passed" else None,
                     "dResultSha256": sha(f"d-{cid}"), "baselineSealSha256s": {GATE: state.seal_sha256}})
    ranked = sorted(passing, key=lambda c: (-passing[c], c))
    finalists = {e: sorted({c["candidateId"] for comp in ranked for c in
                            next(i for i in state.ordinary if i["compositionId"] == comp)["components"]
                            if c["eventId"] == e}) for e in (PARTNER_EVENT, EVENT)}
    return {"groupId": state.group_id, "anchorCommit": anchor,
            "baselineSeals": [{"compositionId": GATE, "sealSha256": state.seal_sha256, "status": "RESOLVED",
                               "sealCommit": state.s0}],
            "dExecutionStartedAt": base.D_STARTED, "incumbent": None,
            "baseline": {"compositionId": GATE, "compositionSha256": state.seal["compositionSha256"],
                         "dScore": None if base_score is None else float(base_score), "dScoreExact": exact(base_score),
                         "dResultSha256": sha("d-baseline")},
            "topK": copy.deepcopy(state.top_k), "componentFinalists": finalists, "compositionCandidates": rows,
            "rankedCompositions": ranked, "frontier": ranked[:1],
            "strongestEvaluatedComposition": ranked[0] if ranked else None,
            "implementationComposition": implementation}


def apply_exact(summary, state, event_id):
    """Composition-derived rows by the EXACT projection (maximum exact score over the candidate's passing
    compositions), float displays, and the exact M1 maxima."""
    block_ = summary["compositionAuthority"]
    passing = {r["compositionId"]: Fraction(r["dScoreExact"]["numerator"], r["dScoreExact"]["denominator"])
               for r in block_["compositionCandidates"] if r["technicalGates"] == "passed"}
    members = {r["compositionId"]: r["components"] for r in block_["compositionCandidates"]}
    best: dict[str, Fraction] = {}
    for row in summary["evaluated"]:
        if row["technicalGates"] == "n/a":
            continue
        scores = [s for comp, s in passing.items()
                  if any(c["eventId"] == event_id and c["candidateId"] == row["candidateId"] for c in members[comp])]
        row.update(technicalGates="passed" if scores else "failed",
                   comparativeScore=float(max(scores)) if scores else None)
        if scores:
            best[row["candidateId"]] = max(scores)
    top = min(best, key=lambda c: (-best[c], c)) if best else None
    summary["strongestEvaluatedTechnical"] = top
    summary["strongestClearedPerProfile"] = {p: top for p in summary["targetProfiles"]}
    return summary


def exact_decision(state, event_id=EVENT, *, block_=None, state_name="QUALIFICATION_PENDING", implementation="default"):
    block_ = exact_block(state) if block_ is None else block_
    summary = base.group_decision(state, event_id, block_=copy.deepcopy(block_), state_name=state_name,
                                  implementation=implementation)
    return apply_exact(summary, state, event_id)


def check(summary, state, event_id=EVENT):
    document = state.frozen_by_event[event_id]
    validate_decision(summary, document, document, group=state)


def row_of(block_, cid):
    return next(r for r in block_["compositionCandidates"] if r["compositionId"] == cid)


# ================================================================== X1-X7: exact D scoring


@pytest.mark.parametrize("value, code", [
    ({"numerator": 4}, "d_score_exact_malformed"),
    ({"numerator": 4, "denominator": 5, "extra": 1}, "d_score_exact_malformed"),
    ({"numerator": 4.0, "denominator": 5}, "d_score_exact_malformed"),
    ({"numerator": True, "denominator": 5}, "d_score_exact_malformed"),
    ({"numerator": 0, "denominator": 0}, "d_score_exact_malformed"),
    ({"numerator": 1, "denominator": 2**63}, "d_score_exact_malformed"),
    ({"numerator": -1, "denominator": 5}, "d_score_exact_malformed"),
    ({"numerator": 6, "denominator": 5}, "d_score_exact_malformed"),
    ("9/10", "d_score_exact_malformed"),
    (None, "d_score_exact_malformed"),
    ({"numerator": 18, "denominator": 20}, "d_score_exact_not_reduced"),
    ({"numerator": 0, "denominator": 5}, "d_score_exact_not_reduced"),
])
@pytest.mark.parametrize("where", ["row", "baseline"])
def test_x1_d_score_exact_shape_is_validated(value, code, where):
    state = base.group()
    summary = exact_decision(state)
    target = row_of(summary["compositionAuthority"], "C-PD-A--VC-EMG") if where == "row" \
        else summary["compositionAuthority"]["baseline"]
    target["dScoreExact"] = value
    refused(code, check, summary, state)


def test_x1_null_exact_iff_null_display_and_the_field_is_mandatory():
    state = base.group()
    scores = dict(default_scores(), **{"C-PD-B--VC-B0": None})
    summary = exact_decision(state, block_=exact_block(state, scores))
    check(summary, state)  # null display and null exact together: accepted (no D score, gate failed)
    changed = copy.deepcopy(summary)
    row_of(changed["compositionAuthority"], "C-PD-B--VC-B0")["dScoreExact"] = exact(Fraction(1, 5))
    refused("d_score_exact_malformed", check, changed, state)
    for where in ("row", "baseline"):
        changed = copy.deepcopy(summary)
        target = row_of(changed["compositionAuthority"], "C-PD-A--VC-EMG") if where == "row" \
            else changed["compositionAuthority"]["baseline"]
        del target["dScoreExact"]
        refused("missing_field", check, changed, state)
    largest = Fraction(1, 2**63 - 1)
    assert ma._exact_score(1 / (2**63 - 1), exact(largest), "x") == largest  # the bound itself is allowed


def test_x2_the_float_display_is_derived_from_the_exact_value():
    state = base.group()
    summary = exact_decision(state)
    check(summary, state)
    for mutate in (lambda b: row_of(b, "C-PD-A--VC-EMG").update(dScore=0.9000000000000001),
                   lambda b: b["baseline"].update(dScore=0.5000000000000001)):
        changed = copy.deepcopy(summary)
        mutate(changed["compositionAuthority"])
        refused("d_score_display_not_derived", check, changed, state)
    changed = copy.deepcopy(summary)
    row_of(changed["compositionAuthority"], "C-PD-A--VC-EMG")["comparativeScore"] = 0.9000000000000001
    refused("composition_score_not_derived", check, changed, state)
    changed = copy.deepcopy(summary)
    next(r for r in changed["evaluated"] if r["candidateId"] == "VC-EMG")["comparativeScore"] = 0.9000000000000001
    refused("row_score_not_composition_derived", check, changed, state)
    # the probe: a float never equals a Fraction, the display equals float(exact)
    assert 0.8 != Fraction(4, 5) and 0.8 == float(Fraction(4, 5))


def test_x3_the_exact_mpid_boundary_131_150_vs_5_6_passes():
    """Decision record §6.2 item 8: D = 131/150 against the baseline 5/6 is exactly ΔD = 1/25 = MPID 0.04 (PASS);
    the JSON floats give 0.0399999999999999 (the pre-A1 M3 path failed it)."""
    block_ = base.universe(mpid=0.04)
    state = base.group(base.m3_ledger(block_=block_), base.partner_ledger(block=block_))
    assert mpid_of(state) == Fraction(1, 25)
    candidate, baseline = Fraction(131, 150), Fraction(5, 6)
    assert candidate - baseline == Fraction(1, 25)
    assert Decimal(str(float(candidate))) - Decimal(str(float(baseline))) < Decimal(str(0.04))  # the float path
    below = candidate - Fraction(1, 10**15)
    for score, passes in ((candidate, True), (below, False)):
        scores = {cid: (score if cid == "C-PD-A--VC-EMG" else None) for cid in base.D_SCORES}
        summary = exact_decision(state, block_=exact_block(state, scores, base_score=baseline, implementation=None),
                                 state_name="TECHNICAL_DECISION_RECORDED", implementation=None)
        assert row_of(summary["compositionAuthority"], "C-PD-A--VC-EMG")["gates"]["baseline"] == \
            ("passed" if passes else "failed")
        check(summary, state)
        flipped = copy.deepcopy(summary)
        row_of(flipped["compositionAuthority"], "C-PD-A--VC-EMG")["gates"]["baseline"] = \
            "failed" if passes else "passed"
        refused("composition_baseline_gate_not_derived", check, flipped, state)


def test_x4_exact_rational_ties_remain_permitted_ties():
    state = base.group()
    scores = dict(default_scores(), **{"C-PD-A--VC-EMG": Fraction(9, 10), "C-PD-A--VC-EST": Fraction(9, 10)})
    summary = exact_decision(state, block_=exact_block(state, scores))
    check(summary, state)
    block_ = summary["compositionAuthority"]
    assert block_["rankedCompositions"][:2] == ["C-PD-A--VC-EMG", "C-PD-A--VC-EST"]
    swapped = copy.deepcopy(summary)
    order = swapped["compositionAuthority"]["rankedCompositions"]
    order[0], order[1] = order[1], order[0]
    swapped["compositionAuthority"]["strongestEvaluatedComposition"] = "C-PD-A--VC-EST"
    swapped["compositionAuthority"]["frontier"] = ["C-PD-A--VC-EST"]
    check(swapped, state)  # no invented tie-break: either order and either strongest
    for name in ("VC-EMG", "VC-EST"):
        changed = copy.deepcopy(summary)
        changed["strongestEvaluatedTechnical"] = name
        changed["strongestClearedPerProfile"] = {"dev-profile": name}
        check(changed, state)


def collided_scores() -> dict[str, Fraction]:
    return {"C-PD-A--VC-EMG": Fraction(4, 5), "C-PD-A--VC-EST": BIG, "C-PD-B--VC-EMG": Fraction(7, 10),
            "C-PD-B--VC-EST": Fraction(3, 5), "C-PD-A--VC-B0": Fraction(3, 10), "C-PD-B--VC-B0": Fraction(1, 5)}


def test_x5_distinct_rationals_with_one_display_float_select_the_exact_maximum_composition():
    assert float(BIG) == float(Fraction(4, 5)) == 0.8 and BIG > Fraction(4, 5)
    state = base.group()
    summary = exact_decision(state, block_=exact_block(state, collided_scores()))
    block_ = summary["compositionAuthority"]
    assert block_["rankedCompositions"][:2] == ["C-PD-A--VC-EST", "C-PD-A--VC-EMG"]
    assert row_of(block_, "C-PD-A--VC-EST")["dScore"] == row_of(block_, "C-PD-A--VC-EMG")["dScore"] == 0.8
    check(summary, state)  # no collision refusal, no new terminal state
    weaker = copy.deepcopy(summary)
    weaker["compositionAuthority"]["strongestEvaluatedComposition"] = "C-PD-A--VC-EMG"
    refused("strongest_composition_not_derived", check, weaker, state)
    swapped = copy.deepcopy(summary)
    order = swapped["compositionAuthority"]["rankedCompositions"]
    order[0], order[1] = order[1], order[0]
    refused("ranked_compositions_not_derived", check, swapped, state)


def test_x6_the_per_component_projection_uses_the_exact_maximum():
    state = base.group()
    block_ = exact_block(state, collided_scores())
    summary = exact_decision(state, block_=block_)
    rows = {r["candidateId"]: r for r in summary["evaluated"]}
    assert rows["VC-EST"]["comparativeScore"] == rows["VC-EMG"]["comparativeScore"] == 0.8
    assert summary["strongestEvaluatedTechnical"] == "VC-EST"
    check(summary, state)
    weaker = copy.deepcopy(summary)
    weaker["strongestEvaluatedTechnical"] = "VC-EMG"
    refused("strongest_technical_not_maximal", check, weaker, state)
    partner = exact_decision(state, PARTNER_EVENT, block_=block_)
    assert partner["strongestEvaluatedTechnical"] == "PD-A"
    check(partner, state, PARTNER_EVENT)
    derived = ma.check_composition_decision(summary, state, EVENT)
    assert derived["VC-EST"] == ("passed", BIG) and derived["VC-EMG"] == ("passed", Fraction(4, 5))
    assert derived["VC-B0"] == ("failed", None)


def test_x7_the_cleared_projection_is_exact_and_m1_maxima_are_unchanged():
    state = base.group()
    summary = exact_decision(state, block_=exact_block(state, collided_scores()))
    weaker = copy.deepcopy(summary)
    weaker["strongestClearedPerProfile"] = {"dev-profile": "VC-EMG"}
    refused("strongest_cleared_not_derived", check, weaker, state)
    # M1 (no compositionUniverse): float maxima, an equal-float tie stays a tie, nothing else changes
    plain = base.plain_ledger()
    m1 = decision(plain, scores={"VC-B0": 0.2, "VC-EST": 0.8, "VC-EMG": 0.8})
    for name in ("VC-EST", "VC-EMG"):
        m1["strongestEvaluatedTechnical"] = name
        m1["strongestClearedPerProfile"] = {"dev-profile": name}
        validate_decision(m1, plain, plain)
    m1["strongestEvaluatedTechnical"] = "VC-B0"
    refused("strongest_technical_not_maximal", validate_decision, m1, plain, plain)
    for field in ("dScoreExact",):
        refused("unknown_field", validate_decision, dict(copy.deepcopy(m1), **{field: {}}), plain, plain)


# ================================================================== R1-R7: lexicographic-missing-last-v1


def missing_last_universe(**changes):
    block_ = base.universe(**changes)
    block_["componentEvents"][0]["rankingRule"] = {
        "rule": "lexicographic-missing-last-v1",
        "keys": [{"metric": "recall", "direction": "max", "missing": "forbidden"}]}
    block_["componentEvents"][1]["rankingRule"] = {
        "rule": "lexicographic-missing-last-v1",
        "keys": [{"metric": "em", "direction": "max", "missing": "forbidden"},
                 {"metric": "cer", "direction": "min", "missing": "forbidden"},
                 {"metric": "ece", "direction": "min", "missing": "last"}]}
    return block_


def ml_group_inputs(k=3):
    block_ = missing_last_universe()
    for item in block_["componentEvents"]:
        item["k"] = k
    return base.m3_ledger(block_=block_), base.partner_ledger(block=block_)


VC_ML = {"VC-B0": {"em": 0.2, "cer": 0.5, "ece": 0.4}, "VC-EST": {"em": 0.9, "cer": 0.1, "ece": None},
         "VC-EMG": {"em": 0.9, "cer": 0.1, "ece": 0.3}}


def test_r1_a_null_last_metric_on_a_passing_row_ranks_after_every_finite_value():
    document, partner = ml_group_inputs()
    validate_ledger(document)
    checked = mu.check_component_ranking(base.ranking(document, metrics=VC_ML), document)
    assert checked["VC-EST"]["key"] == ((0, -0.9), (0, 0.1), (1, 0.0))
    assert checked["VC-EMG"]["key"] == ((0, -0.9), (0, 0.1), (0, 0.3))
    assert mu.derive_top_k(checked, 1) == ["VC-EMG"] and mu.derive_top_k(checked, 2) == ["VC-EMG", "VC-EST"]
    rankings = base.rankings_of(document, partner, own=base.ranking(document, metrics=VC_ML))
    seal = base.derive(document, partner, rankings)
    assert seal["status"] == "RESOLVED"  # the valid silent candidate counts and enters U
    state = base.group(document, partner, rankings)
    assert "VC-EST" in state.top_k[EVENT]


@pytest.mark.parametrize("metric", ["em", "cer"])
def test_r2_a_null_forbidden_metric_on_a_passing_row_is_refused_and_stops(metric):
    document, partner = ml_group_inputs()
    metrics = copy.deepcopy(VC_ML)
    metrics["VC-EMG"][metric] = None
    ranking = base.ranking(document, metrics=metrics)
    refused("component_ranking_mandatory_metric_missing", mu.check_component_ranking, ranking, document)
    seal = base.derive(document, partner, base.rankings_of(document, partner, own=ranking))
    assert seal["status"] == "STOPPED" and seal["stopReason"] == "component-ranking-inconsistent"
    bs.verify_baseline_seal(seal, frozen=document, protocol_sha256=base.PROTOCOL, partner_ledger=partner,
                            rankings=base.rankings_of(document, partner, own=ranking))
    detector = base.ranking(partner, metrics={"PD-A": {"recall": None}, "PD-B": {"recall": 0.8}})
    refused("component_ranking_mandatory_metric_missing", mu.check_component_ranking, detector, partner)


def test_r3_a_failing_row_may_carry_nulls_and_is_never_ranked():
    """CONTRACT_FAIL / UNEVALUABLE rows fail a ranking gate: nulls are allowed, the row is never ranked or evaluable."""
    document, partner = ml_group_inputs()
    metrics = dict(VC_ML, **{"VC-EMG": {"em": None, "cer": None, "ece": None}})
    ranking = base.ranking(document, metrics=metrics, gates={"VC-EMG": {"contract": "failed"}})
    checked = mu.check_component_ranking(ranking, document)
    assert checked["VC-EMG"]["passed"] is False and "VC-EMG" not in mu.derive_top_k(checked, 3)
    detector = base.ranking(partner, metrics={"PD-A": {"recall": 0.9}, "PD-B": {"recall": None}},
                            gates={"PD-B": {"contract": "failed", "recall-floor": "failed"}})
    assert mu.check_component_ranking(detector, partner)["PD-B"]["passed"] is False
    # the failed row is no successful evidence: with it the VC event has one evaluable candidate left (P1)
    seal = base.derive(document, partner, base.rankings_of(document, partner, own=ranking))
    assert seal["status"] == "STOPPED" and seal["stopReason"] == "insufficient-evaluable-candidates"


def test_r4_lexicographic_v1_is_unchanged():
    document = base.m3_ledger()
    checked = mu.check_component_ranking(base.ranking(document), document)
    assert checked["VC-EMG"]["key"] == (-0.9, 0.1)  # plain floats, as before
    nulls = base.ranking(document, metrics=dict(base.VC_METRICS, **{"VC-EMG": {"em": None, "cer": 0.1}}),
                         gates={"VC-EMG": {"contract": "failed"}})
    refused("number_required", mu.check_component_ranking, nulls, document)  # even on a failing row
    with_missing = base.universe()
    with_missing["componentEvents"][1]["rankingRule"]["keys"][0]["missing"] = "last"
    refused("unknown_field", validate_ledger, base.m3_ledger(block_=with_missing))
    assert mu.RANKING_RULES == ("lexicographic-v1", "lexicographic-missing-last-v1")


@pytest.mark.parametrize("mutate, code", [
    (lambda keys: keys[2].pop("missing"), "missing_field"),
    (lambda keys: keys[2].update(missing="first"), "value_not_allowed"),
    (lambda keys: keys[2].update(missing=None), "value_not_allowed"),
    (lambda keys: keys[2].update(default=0.0), "unknown_field"),
])
def test_r5_the_missing_last_rule_shape_is_closed(mutate, code):
    validate_ledger(base.m3_ledger(block_=missing_last_universe()))
    block_ = missing_last_universe()
    mutate(block_["componentEvents"][1]["rankingRule"]["keys"])
    refused(code, validate_ledger, base.m3_ledger(block_=block_))
    other = missing_last_universe()
    other["componentEvents"][1]["rankingRule"]["rule"] = "lexicographic-missing-first-v1"
    refused("value_not_allowed", validate_ledger, base.m3_ledger(block_=other))


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan, True, "0.5", [0.5]])
@pytest.mark.parametrize("gated", [False, True])
def test_r6_a_non_finite_or_non_number_metric_is_invalid(value, gated):
    document, _partner = ml_group_inputs()
    metrics = copy.deepcopy(VC_ML)
    metrics["VC-EMG"]["ece"] = value
    gates = {"VC-EMG": {"contract": "failed"}} if gated else None
    refused("component_ranking_metric_invalid", mu.check_component_ranking,
            base.ranking(document, metrics=metrics, gates=gates), document)


def test_r7_nulls_never_invent_a_score_and_the_stage4_constants_are_accepted():
    document, partner = ml_group_inputs(k=1)
    metrics = dict(VC_ML, **{"VC-EMG": {"em": 0.9, "cer": 0.1, "ece": None}})  # two null-ECE rows, equal keys
    ranking = base.ranking(document, metrics=metrics)
    refused("component_rank_ambiguous", mu.derive_top_k, mu.check_component_ranking(ranking, document), 1)
    seal = base.derive(document, partner, base.rankings_of(document, partner, own=ranking))
    assert seal["status"] == "STOPPED" and seal["stopReason"] == "component-rank-ambiguous"
    # Stage-4 constants (plan §4.2)
    stage4 = base.universe(mpid=0.04)
    stage4["componentEvents"][0].update(rankingGateIds=["contract", "evaluable", "independent", "support"],
                                        rankingRule={"rule": "lexicographic-missing-last-v1", "keys": [
                                            {"metric": "recallAtCoverage", "direction": "max", "missing": "forbidden"},
                                            {"metric": "falsePlatesPerCrop", "direction": "min",
                                             "missing": "forbidden"},
                                            {"metric": "ap50", "direction": "max", "missing": "forbidden"}]})
    stage4["componentEvents"][1].update(rankingGateIds=["contract", "evaluable", "independent", "support"],
                                        rankingRule={"rule": "lexicographic-missing-last-v1", "keys": [
                                            {"metric": "em", "direction": "max", "missing": "forbidden"},
                                            {"metric": "cer", "direction": "min", "missing": "forbidden"},
                                            {"metric": "ece", "direction": "min", "missing": "last"}]})
    validate_ledger(base.m3_ledger(block_=stage4))
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((Path(__file__).resolve().parents[1] / "model_selection" / "schemas" /
                         "mavi-model-selection-component-ranking-v1.schema.json").read_text())
    jsonschema.validate(base.ranking(document, metrics=VC_ML), schema)


# ================================================================== P1-P3: minimum evaluable population


def test_p1_one_evaluable_candidate_in_an_event_stops():
    document, partner = base.m3_ledger(), base.partner_ledger()
    own = base.ranking(document, gates={"VC-EMG": {"contract": "failed"}})  # VC-EST and the mavi-baseline VC-B0 pass
    rankings = base.rankings_of(document, partner, own=own)
    seal = base.derive(document, partner, rankings)
    assert seal["status"] == "STOPPED" and seal["stopReason"] == "insufficient-evaluable-candidates"
    bs.verify_baseline_seal(seal, frozen=document, protocol_sha256=base.PROTOCOL, partner_ledger=partner,
                            rankings=rankings)  # derived, so re-derived
    other = base.derive(document, partner, rankings_of_pd_failing_one(document, partner))
    assert other["stopReason"] == "insufficient-evaluable-candidates"
    fabricated = dict(seal, stopReason="no-partner-passed-layer-a")
    refused("baseline_stop_reason_contradicted", bs.verify_baseline_seal, fabricated, frozen=document,
            protocol_sha256=base.PROTOCOL, partner_ledger=partner, rankings=rankings)


def rankings_of_pd_failing_one(document, partner):
    return base.rankings_of(document, partner, other=base.ranking(
        partner, gates={"PD-B": {"contract": "passed", "recall-floor": "failed"}}))


def test_p2_every_candidate_failing_a_ranking_gate_stops_and_an_empty_universe_is_refused():
    document, partner = base.m3_ledger(), base.partner_ledger()
    support = {c: {"contract": "passed", "recall-floor": "failed"} for c in ("PD-A", "PD-B")}
    seal = base.derive(document, partner, base.rankings_of(document, partner,
                                                           other=base.ranking(partner, gates=support)))
    assert seal["status"] == "STOPPED" and seal["stopReason"] == "insufficient-evaluable-candidates"
    state = base.group()
    state.ordinary = []
    authority = ma.GroupAuthority(state, [PARTNER_EVENT, EVENT])
    with pytest.raises(CredibilityError) as error:
        ma._check_pre_d(None, authority)
    assert str(error.value) == "d_not_authorised:composition-universe-empty"


def test_p_no_partner_stays_reachable_when_only_excluded_partners_are_evaluable():
    """The population STOP is checked before the partner; with two evaluable but excluded partners the derived reason
    is still ``no-partner-passed-layer-a``."""
    from model_selection_fixtures import established
    entry = base.bob()
    entry["benchmarkBaseline"]["compositions"][0]["excludedPartners"] = [
        {"candidateId": c, "identitySha256": base.identity_of(label), "reason": "not a frozen partner"}
        for c, label in (("PD-C", "pdc"), ("PD-D", "pdd"))]
    from model_selection_fixtures import baseline as mavi_baseline, emerging
    document = base.m3_ledger(mavi_baseline(), established(), emerging(), entry)
    partner = base.partner_ledger(established("PD-A", "pda"), established("PD-B", "pdb"), established("PD-C", "pdc"),
                                  established("PD-D", "pdd"))
    failing = {c: {"contract": "passed", "recall-floor": "failed"} for c in ("PD-A", "PD-B")}
    rankings = base.rankings_of(document, partner, other=base.ranking(partner, gates=failing))
    seal = base.derive(document, partner, rankings)
    assert seal["status"] == "STOPPED" and seal["stopReason"] == "no-partner-passed-layer-a"
    bs.verify_baseline_seal(seal, frozen=document, protocol_sha256=base.PROTOCOL, partner_ledger=partner,
                            rankings=rankings)


def test_p3_a_resolved_seal_with_one_evaluable_candidate_is_not_derivable():
    document, partner = base.m3_ledger(), base.partner_ledger()
    own = base.ranking(document, gates={"VC-EMG": {"contract": "failed"}})
    rankings = base.rankings_of(document, partner, own=own)
    forged = base.derive(document, partner, base.rankings_of(document, partner))  # RESOLVED on full inputs
    checked = {EVENT: mu.check_component_ranking(own, document),
               PARTNER_EVENT: mu.check_component_ranking(rankings[PARTNER_EVENT], partner)}
    forged.update(componentRankingSha256s={e: document_sha256(r) for e, r in rankings.items()},
                  ordinaryCompositionsSha256=mu.ordinary_compositions_sha256(mu.derive_ordinary_universe(
                      document["compositionUniverse"], {EVENT: document, PARTNER_EVENT: partner}, checked)))
    refused("baseline_seal_not_derivable", bs.verify_baseline_seal, forged, frozen=document,
            protocol_sha256=base.PROTOCOL, partner_ledger=partner, rankings=rankings)


# ================================================================== AB1-AB3: abandonment reasons


def _abandon(built, reason, evidence):
    for e in (EVENT, PARTNER_EVENT):
        base.append(built.record(e), f"Abandoned: {reason} evidence SHA-256: {evidence}")


@pytest.mark.parametrize("reason", ["d-corpus-inadmissible", "d-evaluation-incomplete", "baseline-d-unavailable"])
def test_ab1_the_new_reasons_are_accepted_with_a_committed_manifest_result(tmp_path, reason):
    assert ma.ABANDON_REASONS == ("baseline-d-unavailable", "d-corpus-inadmissible", "d-evaluation-incomplete")
    built, _auth, manifest = base.full_flow(tmp_path / "r")
    evidence = json.loads(manifest.read_text())["resultSha256"]
    line = ma.abandonment_line(reason, evidence)
    assert line == f"Abandoned: {reason} evidence SHA-256: {evidence}"
    for e in (EVENT, PARTNER_EVENT):
        base.append(built.record(e), line)
    base.commit(built.path, f"ABANDONED: {reason}")
    validate_repository(built.path)
    refused("d_not_authorised", base.open_d, built)


def test_ab2_any_other_reason_is_refused(tmp_path):
    for reason in ("d-other", "owner-preferred", "D-CORPUS-INADMISSIBLE", "d-corpus-inadmissible "):
        refused("abandonment_reason_not_allowed", ma.abandonment_line, reason, sha("x"))
    built, _auth, manifest = base.full_flow(tmp_path / "r")
    _abandon(built, "d-capture-incomplete", json.loads(manifest.read_text())["resultSha256"])
    base.commit(built.path, "abandon for an unlisted reason")
    refused("abandonment_reason_not_allowed", validate_repository, built.path)
    built = base.build(tmp_path / "b")
    _abandon(built, "d-corpus-inadmissible", sha("no D was opened"))
    base.commit(built.path, "abandon without protected D")
    refused("abandonment_without_protected_d", validate_repository, built.path)


@pytest.mark.parametrize("reason", ["d-corpus-inadmissible", "d-evaluation-incomplete"])
def test_ab3_abandonment_after_a_decision_is_refused_for_the_new_reasons(tmp_path, reason):
    built, auth, manifest = base.full_flow(tmp_path / "r")
    commit_exact_decisions(built, auth)
    validate_repository(built.path)
    _abandon(built, reason, json.loads(manifest.read_text())["resultSha256"])
    base.commit(built.path, "abandon after a recorded decision")
    refused("abandonment_after_decision", validate_repository, built.path)


# ================================================================== MB1-MB3: D results bound to committed manifests


def commit_results(built, auth, block_, *, skip=(), duplicate=None):
    """One committed group D manifest per cited D result (rows and baseline), on a commit after the anchor."""
    cited = [(r["compositionId"], r["dResultSha256"]) for r in block_["compositionCandidates"]]
    cited.append((GATE, block_["baseline"]["dResultSha256"]))
    for name, result in cited:
        if name in skip:
            continue
        run = f"R-{name}"
        ma.write_canonical(built.folder / f"{EVENT}{bs.D_MANIFEST_INFIX}{run}.json",
                           ma.d_manifest_document(auth, run, result))
    if duplicate is not None:
        ma.write_canonical(built.folder / f"{EVENT}{bs.D_MANIFEST_INFIX}R-DUP.json",
                           ma.d_manifest_document(auth, "R-DUP", duplicate))
    base.commit(built.path, "protected D results")
    base.git(built.path, "update-ref", "refs/remotes/origin/main", auth.anchor_commit)


def commit_exact_decisions(built, auth, *, mutate=None, skip=(), duplicate=None):
    state = built.state()
    block_ = exact_block(state, anchor=auth.anchor_commit)
    if mutate is not None:
        mutate(block_)
    commit_results(built, auth, block_, skip=skip, duplicate=duplicate)
    for event_id in (EVENT, PARTNER_EVENT):
        summary = exact_decision(state, event_id, block_=block_)
        folder = base.folder_of(built.path, event_id)
        decision_path = base.write(folder / f"{event_id}-decision.json", json.dumps(summary))
        snapshot_path = base.write(folder / f"{event_id}-evidence-ledger-decided.json",
                                   json.dumps(state.frozen_by_event[event_id]))
        base.append(built.record(event_id), f"Decision SHA-256: {base.lf_normalised_sha256(decision_path)}")
        base.append(built.record(event_id), f"Decision snapshot SHA-256: {base.lf_normalised_sha256(snapshot_path)}")
    base.commit(built.path, "technical decision")


def test_mb1_every_row_and_the_baseline_cite_a_committed_group_manifest(tmp_path):
    built, auth, _manifest = base.full_flow(tmp_path / "ok")
    commit_exact_decisions(built, auth)
    validate_repository(built.path)
    for name, skip in (("row", ("C-PD-A--VC-EST",)), ("baseline", (GATE,))):
        built, auth, _manifest = base.full_flow(tmp_path / name)
        commit_exact_decisions(built, auth, skip=skip)
        refused("decision_d_result_without_manifest", validate_repository, built.path)


@pytest.mark.parametrize("target", ["row", "baseline"])
def test_mb2_a_d_result_cited_twice_is_refused(target):
    state = base.group()
    summary = exact_decision(state)
    block_ = summary["compositionAuthority"]
    first = row_of(block_, "C-PD-A--VC-EMG")
    if target == "row":
        row_of(block_, "C-PD-B--VC-B0")["dResultSha256"] = first["dResultSha256"]
    else:
        block_["baseline"]["dResultSha256"] = first["dResultSha256"]
    refused("decision_d_result_cited_twice", check, summary, state)


def test_mb3_two_manifests_with_one_result_are_refused(tmp_path):
    built, auth, _manifest = base.full_flow(tmp_path / "r")
    commit_results(built, auth, exact_block(built.state(), anchor=auth.anchor_commit), duplicate=sha("d-RUN-1"))
    refused("d_manifest_result_duplicated", validate_repository, built.path)
