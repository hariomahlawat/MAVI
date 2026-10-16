"""MSR revision M3: the frozen composition universe and the derived ordinary composition set (invariant C1).

A **composition group** is the set of component events (exactly two: for Stage-4 PR-2 the plate detector and the
recogniser) whose frozen ledgers carry one identical ``compositionUniverse`` block. Its canonical SHA-256 is the group
id. The block freezes, per component event, the ranking layer, ``k``, the ranking gate ids and a machine ranking rule;
and, for the group, the composition gate ids (always including ``baseline``) and the MPID.

From the frozen inputs alone the validator derives:

* each event's **component ranking** order: the rank key of every shortlisted candidate is computed from its recorded
  ``metrics`` by the frozen ``lexicographic-v1`` rule; an author-supplied key is never accepted;
* ``topK`` per event: the first ``k`` candidates passing every ranking gate. A tie across the ``k`` boundary is
  ``component_rank_ambiguous`` (owner decision O3: STOP before protected D);
* the **ordinary universe** U: the cartesian product over the component events of (topK ∪ packageable baselines),
  tuples ordered by event id, each with a derived ``compositionId``. A benchmark-only baseline is never in it (its
  disposition is not ``SHORTLISTED``).

Component rankings and top-K are diagnostics: implementation authority comes only from passing end-to-end compositions
(``m3_authority.check_composition_decision``).

Standard library only.
"""

from __future__ import annotations

import itertools
import math
import re
from collections.abc import Mapping, Sequence

from .credibility import (
    BASELINE,
    CANDIDATE_ID_RE,
    EVENT_ID_RE,
    LOCAL_ID_RE,
    SHA256_RE,
    SHORTLISTED,
    SUBTASK_RE,
    _enum,
    _fail,
    _keys,
    _list,
    _match,
    _number,
    document_sha256,
)

UNIVERSE_FIELD = "compositionUniverse"
SUPERSEDES_FIELD = "supersedes"
RANKING_SCHEMA = "mavi-model-selection-component-ranking-v1"
RANKING_RULE = "lexicographic-v1"
RANKING_LAYERS = ("A", "B")
DIRECTIONS = ("max", "min")
BASELINE_GATE = "baseline"
PASSED, FAILED = "passed", "failed"
GROUP_SIZE = 2
COMPOSITION_ID_RE = re.compile(r"^C-[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*(?:--[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*)+$")


def group_id(universe: Mapping) -> str:
    return document_sha256(universe)


def universe_of(ledger: Mapping) -> dict | None:
    return ledger.get(UNIVERSE_FIELD)


# ------------------------------------------------------------------ ledger block


def check_universe_block(ledger: Mapping) -> None:
    """Structure of a frozen ``compositionUniverse`` (called from ``validate_ledger`` for ``msr-v1-m3`` only)."""
    where = f"ledger.{UNIVERSE_FIELD}"
    block = _keys(ledger[UNIVERSE_FIELD], ("componentEvents", "compositionGateIds", "mpid",
                                           "includePackageableBaselines"), where)
    events = _list(block["componentEvents"], f"{where}.componentEvents")
    ids = []
    for index, item in enumerate(events):
        at = f"{where}.componentEvents[{index}]"
        _keys(item, ("eventId", "subTask", "rankingLayer", "k", "rankingGateIds", "rankingRule"), at)
        ids.append(_match(item["eventId"], EVENT_ID_RE, f"{at}.eventId"))
        _match(item["subTask"], SUBTASK_RE, f"{at}.subTask")
        _enum(item["rankingLayer"], RANKING_LAYERS, f"{at}.rankingLayer")
        if isinstance(item["k"], bool) or not isinstance(item["k"], int) or item["k"] < 1:
            raise _fail("composition_universe_k_invalid", f"{at}.k")
        gates = _list(item["rankingGateIds"], f"{at}.rankingGateIds")
        for gindex, gate in enumerate(gates):
            _match(gate, LOCAL_ID_RE, f"{at}.rankingGateIds[{gindex}]")
        if gates != sorted(set(gates)):
            raise _fail("ranking_gates_not_sorted_unique", f"{at}.rankingGateIds")
        check_ranking_rule(item["rankingRule"], f"{at}.rankingRule")
    if ids != sorted(set(ids)) or len(ids) != GROUP_SIZE:
        # one gate-only baseline composition (BOB + one partner) must cover every component slot
        raise _fail("composition_universe_events_invalid", f"{where}.componentEvents")
    if ledger["eventId"] not in ids:
        raise _fail("composition_universe_excludes_own_event", f"{where}.componentEvents")
    own = next(item for item in events if item["eventId"] == ledger["eventId"])
    if own["subTask"] not in ledger["subTasks"]:
        raise _fail("composition_universe_subtask_outside_event", f"{where}.componentEvents")
    gates = _list(block["compositionGateIds"], f"{where}.compositionGateIds")
    for gindex, gate in enumerate(gates):
        _match(gate, LOCAL_ID_RE, f"{where}.compositionGateIds[{gindex}]")
    if gates != sorted(set(gates)) or BASELINE_GATE not in gates:
        raise _fail("composition_gates_invalid", f"{where}.compositionGateIds")
    if _number(block["mpid"], f"{where}.mpid") < 0:
        raise _fail("composition_universe_mpid_invalid", f"{where}.mpid")
    if block["includePackageableBaselines"] is not True:
        raise _fail("composition_universe_must_include_packageable_baselines", f"{where}.includePackageableBaselines")


def check_ranking_rule(rule: object, where: str) -> None:
    _keys(rule, ("rule", "keys"), where)
    _enum(rule["rule"], (RANKING_RULE,), f"{where}.rule")
    keys = _list(rule["keys"], f"{where}.keys")
    metrics = []
    for index, key in enumerate(keys):
        _keys(key, ("metric", "direction"), f"{where}.keys[{index}]")
        metrics.append(_match(key["metric"], LOCAL_ID_RE, f"{where}.keys[{index}].metric"))
        _enum(key["direction"], DIRECTIONS, f"{where}.keys[{index}].direction")
    if not metrics or len(set(metrics)) != len(metrics):
        raise _fail("ranking_rule_keys_invalid", f"{where}.keys")


def check_supersedes_block(ledger: Mapping) -> None:
    where = f"ledger.{SUPERSEDES_FIELD}"
    block = _keys(ledger[SUPERSEDES_FIELD], ("eventId", "frozenLedgerSha256", "stoppedSealSha256s"), where)
    _match(block["eventId"], EVENT_ID_RE, f"{where}.eventId")
    if block["eventId"] == ledger["eventId"] or \
            not re.fullmatch(rf"msr-{re.escape(ledger['capabilityId'])}-\d{{4}}-\d{{2}}", block["eventId"]):
        raise _fail("supersedes_event_invalid", f"{where}.eventId")
    _match(block["frozenLedgerSha256"], SHA256_RE, f"{where}.frozenLedgerSha256")
    seals = _list(block["stoppedSealSha256s"], f"{where}.stoppedSealSha256s")
    for value in seals:
        _match(value, SHA256_RE, f"{where}.stoppedSealSha256s")
    if not seals or seals != sorted(set(seals)):
        raise _fail("supersedes_seals_invalid", f"{where}.stoppedSealSha256s")


def component_event(universe: Mapping, event_id: str) -> dict:
    for item in universe["componentEvents"]:
        if item["eventId"] == event_id:
            return item
    raise _fail("composition_universe_event_unknown", event_id)


def ranking_rule_sha256(universe: Mapping, event_id: str) -> str:
    return document_sha256(component_event(universe, event_id)["rankingRule"])


def ranking_gates_sha256(universe: Mapping, event_id: str) -> str:
    return document_sha256(component_event(universe, event_id)["rankingGateIds"])


# ------------------------------------------------------------------ component ranking


def shortlist_identities(frozen: Mapping) -> dict[str, str]:
    """``{candidateId: identitySha256}`` of the frozen SHORTLISTED candidates (never a benchmark-only baseline)."""
    return {e["candidateId"]: document_sha256(e["identity"]) for e in frozen["candidates"]
            if e["disposition"]["status"] == SHORTLISTED}


def packageable_baselines(frozen: Mapping) -> list[str]:
    """Plan §4.1 "plus any packageable baseline": the SHORTLISTED ``mavi-baseline`` candidates."""
    return sorted(e["candidateId"] for e in frozen["candidates"]
                  if e["disposition"]["status"] == SHORTLISTED and e["candidateKind"] == BASELINE)


def component_ranking_document(frozen: Mapping, rows: Sequence[Mapping], evidence_sha256: str) -> dict:
    """The canonical component ranking a harness commits as ``<event-id>-component-ranking.json`` (rows:
    candidateId, identitySha256, gates, metrics, measurementSha256)."""
    universe = frozen[UNIVERSE_FIELD]
    item = component_event(universe, frozen["eventId"])
    return {"schema": RANKING_SCHEMA, "eventId": frozen["eventId"], "frozenLedgerSha256": document_sha256(frozen),
            "compositionUniverseSha256": group_id(universe), "rankingLayer": item["rankingLayer"],
            "rankingGateIds": list(item["rankingGateIds"]), "rankingRuleSha256": document_sha256(item["rankingRule"]),
            "rows": sorted((dict(r) for r in rows), key=lambda r: r["candidateId"]),
            "evidenceSha256": evidence_sha256}


def rank_key(metrics: Mapping[str, float], rule: Mapping) -> tuple:
    """The frozen ``lexicographic-v1`` key: lower ranks higher; ``max`` metrics are negated. No id tie-break."""
    return tuple(-metrics[k["metric"]] if k["direction"] == "max" else metrics[k["metric"]] for k in rule["keys"])


def check_component_ranking(document: object, frozen: Mapping) -> dict:
    """Validate an event's component ranking against its frozen ledger; return ``{candidateId: {"key", "passed"}}``.

    The rows are exactly the frozen shortlist with the frozen identities; every frozen ranking gate has a result;
    ``metrics`` hold exactly the rule's metrics as finite numbers; the rank key is derived here."""
    where = "componentRanking"
    universe = frozen.get(UNIVERSE_FIELD)
    if universe is None:
        raise _fail("component_ranking_without_universe", where)
    item = component_event(universe, frozen["eventId"])
    _keys(document, ("schema", "eventId", "frozenLedgerSha256", "compositionUniverseSha256", "rankingLayer",
                     "rankingGateIds", "rankingRuleSha256", "rows", "evidenceSha256"), where)
    if document["schema"] != RANKING_SCHEMA:
        raise _fail("schema_unsupported", f"{where}.schema")
    if document["eventId"] != frozen["eventId"] or document["frozenLedgerSha256"] != document_sha256(frozen):
        raise _fail("component_ranking_not_for_this_event", where)
    if document["compositionUniverseSha256"] != group_id(universe):
        raise _fail("component_ranking_universe_mismatch", where)
    if (document["rankingLayer"], document["rankingGateIds"], document["rankingRuleSha256"]) != \
            (item["rankingLayer"], item["rankingGateIds"], document_sha256(item["rankingRule"])):
        raise _fail("component_ranking_rule_mismatch", where)
    _match(document["evidenceSha256"], SHA256_RE, f"{where}.evidenceSha256")
    shortlist = shortlist_identities(frozen)
    metrics_needed = sorted(k["metric"] for k in item["rankingRule"]["keys"])
    result: dict[str, dict] = {}
    ids = []
    for index, row in enumerate(_list(document["rows"], f"{where}.rows")):
        at = f"{where}.rows[{index}]"
        _keys(row, ("candidateId", "identitySha256", "gates", "metrics", "measurementSha256"), at)
        candidate = _match(row["candidateId"], CANDIDATE_ID_RE, f"{at}.candidateId")
        if candidate not in shortlist:
            raise _fail("component_ranking_candidate_not_shortlisted", at)
        if row["identitySha256"] != shortlist[candidate]:
            raise _fail("component_ranking_identity_mismatch", at)
        _match(row["measurementSha256"], SHA256_RE, f"{at}.measurementSha256")
        gates = row["gates"]
        if not isinstance(gates, dict) or sorted(gates) != item["rankingGateIds"]:
            raise _fail("component_ranking_gates_mismatch", f"{at}.gates")
        for gate, value in gates.items():
            _enum(value, (PASSED, FAILED), f"{at}.gates.{gate}")
        metrics = row["metrics"]
        if not isinstance(metrics, dict) or sorted(metrics) != metrics_needed:
            raise _fail("component_ranking_metrics_mismatch", f"{at}.metrics")
        values = {m: _number(v, f"{at}.metrics.{m}") for m, v in metrics.items()}
        ids.append(candidate)
        result[candidate] = {"key": rank_key(values, item["rankingRule"]),
                             "passed": all(v == PASSED for v in gates.values())}
    if ids != sorted(set(ids)) or set(ids) != set(shortlist):
        raise _fail("component_ranking_not_the_shortlist", f"{where}.rows")
    return result


def ordered_passing(ranking: Mapping[str, Mapping], members: set[str] | None = None) -> list[tuple[tuple, str]]:
    return sorted((row["key"], c) for c, row in ranking.items()
                  if row["passed"] and (members is None or c in members))


def derive_top_k(ranking: Mapping[str, Mapping], k: int) -> list[str]:
    """The first ``k`` candidates passing every ranking gate, by derived rank key. A tie across the boundary is
    refused (``component_rank_ambiguous``); ties inside the top ``k`` are harmless."""
    passing = ordered_passing(ranking)
    if len(passing) > k and passing[k - 1][0] == passing[k][0]:
        raise _fail("component_rank_ambiguous", f"k={k}")
    return [candidate for _key, candidate in passing[:k]]


def best_partner(ranking: Mapping[str, Mapping], eligible: set[str]) -> str | None:
    """PD_BASE: the unique best eligible partner passing every ranking gate; None when none passes."""
    passing = ordered_passing(ranking, eligible)
    if not passing:
        return None
    if len(passing) > 1 and passing[0][0] == passing[1][0]:
        raise _fail("partner_rank_ambiguous", "eligiblePartners")
    return passing[0][1]


def composition_id(candidates: Sequence[str]) -> str:
    """Derived id of an ordinary composition: ``C-`` + candidate ids (by event id) joined with ``--``. Candidate ids
    never contain ``--``, so the id decodes to exactly one tuple."""
    return "C-" + "--".join(candidates)


def derive_ordinary_universe(universe: Mapping, frozen_by_event: Mapping[str, Mapping],
                             rankings: Mapping[str, Mapping[str, Mapping]]) -> list[dict]:
    """U: every tuple over the component events of (topK ∪ packageable baselines), ordered by event id. Each item is
    ``{"compositionId", "components": [{"eventId", "candidateId", "identitySha256"}]}``, sorted by id."""
    slots = []
    for item in universe["componentEvents"]:
        event_id = item["eventId"]
        frozen = frozen_by_event[event_id]
        members = set(derive_top_k(rankings[event_id], item["k"])) | set(packageable_baselines(frozen))
        identities = shortlist_identities(frozen)
        slots.append([(event_id, c, identities[c]) for c in sorted(members)])
    found = []
    for combination in itertools.product(*slots):
        found.append({"compositionId": composition_id([c for _e, c, _i in combination]),
                      "components": [{"eventId": e, "candidateId": c, "identitySha256": i}
                                     for e, c, i in combination]})
    return sorted(found, key=lambda item: item["compositionId"])


def ordinary_compositions_sha256(ordinary: Sequence[Mapping]) -> str:
    return document_sha256(list(ordinary))


def finite(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)

