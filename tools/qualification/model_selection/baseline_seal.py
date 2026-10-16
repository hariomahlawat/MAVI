"""MSR revision M3: the committed pre-D seal of the group's gate-only baseline composition.

Normative text: ``docs/qualification/model-selection/proposals/m3-benchmark-only-baseline.md`` (rules 4, 4a, 9 and
the authority section) and ``candidate-credibility.md`` §4.4 and §8. This module holds the seal level only:

* the **Stage-1 rule**, frozen in the benchmark-only baseline's ledger entry (``benchmarkBaseline.compositions[]``,
  exactly one): the partner event (the other member of the composition group), the finite ``eligiblePartners`` with
  exact identity hashes, the recorded ``excludedPartners``, the derivation rule and the gate scope. The partner's
  ranking gates and ranking rule are the partner event's entry in the frozen ``compositionUniverse``;
* the **baseline seal** ``<event-id>-baseline-seal-<compositionId>.json`` (``mavi-model-selection-baseline-seal-v1``),
  status ``RESOLVED`` or ``STOPPED``, canonical JSON, identified by its canonical SHA-256 (no self-hash).

A RESOLVED seal is valid only if it is exactly what ``derive_baseline_seal`` re-derives from the frozen ledger, the
protocol hash, the partner event's frozen ledger and the committed component rankings of both group events. It binds
the component-ranking hashes, the universe hash and the hash of the derived ordinary composition set U
(``m3_universe.derive_ordinary_universe``), so U is sealed before protected D. Any failed prerequisite, a partner tie,
or a tie across a top-K boundary (owner decision O3) is a STOPPED seal; a STOPPED seal is terminal (owner decision O1)
and permits no protected D.

The group-level authority (history, chronology, anchors, the decision binding and the only pre-D entry point
``open_protected_d``) is ``m3_authority.py``. Standard library only.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from .credibility import (
    BENCHMARK_BASELINE,
    CANDIDATE_ID_RE,
    EVENT_ID_RE,
    LOCAL_ID_RE,
    MODEL_SELECTION_DIR,
    SHA256_RE,
    SHORTLISTED,
    CredibilityError,
    _enum,
    _fail,
    _instant,
    _keys,
    _list,
    _match,
    _text,
    canonical_json,
    document_sha256,
    read_json,
    validate_ledger,
)
from .m3_universe import (
    UNIVERSE_FIELD,
    best_partner,
    check_component_ranking,
    derive_ordinary_universe,
    group_id,
    ordinary_compositions_sha256,
    ranking_gates_sha256,
    ranking_rule_sha256,
)

SEAL_SCHEMA = "mavi-model-selection-baseline-seal-v1"
RESOLVED, STOPPED = "RESOLVED", "STOPPED"
SEAL_STATUSES = (RESOLVED, STOPPED)
GATE_SCOPE_ALL = "all-ordinary-compositions"
# "listed-compositions" stays DISABLED (convergence review P1-B): compositions are identified by their derived
# component tuple, and the baseline gates every composition of the sealed universe.
GATE_SCOPE_LISTED_DISABLED = "listed-compositions"
GATE_SCOPES = (GATE_SCOPE_ALL,)
DERIVATION_RULE = "highest-ranked-partner-passing-every-layer-a-gate"
DERIVATION_RULES = (DERIVATION_RULE,)
D_NOT_STARTED, D_ACCESSED = "NOT_STARTED", "ACCESSED"
STOP_REASONS = (
    "no-partner-passed-layer-a",
    "partner-event-missing",
    "partner-event-inconsistent",
    "partner-universe-inconsistent",
    "identity-mismatch",
    "resolution-ambiguous",
    "component-rank-ambiguous",
    "component-ranking-inconsistent",
    "protected-d-accessed",
    "prerequisite-failed",
)
SEAL_INFIX = "-baseline-seal-"
RANKING_SUFFIX = "-component-ranking.json"
RANKING_INFIX = "-component-ranking"
LEGACY_LAYER_A_INFIX = "-layer-a-"  # the pre-redesign artefact; refused wherever it appears
D_MANIFEST_INFIX = "-d-manifest-"
D_MANIFEST_SCHEMA = "mavi-model-selection-d-manifest-v1"
ARTEFACT_INFIXES = (SEAL_INFIX, RANKING_INFIX, LEGACY_LAYER_A_INFIX, D_MANIFEST_INFIX)

_COMMON = ("schema", "status", "eventId", "capabilityId", "compositionId", "benchmarkBaselineId",
           "benchmarkComponentIdentitySha256", "protocolSha256", "frozenLedgerSha256", "stage1RuleSha256",
           "eligibleUniverseSha256", "layerAGatesSha256", "partnerRankingRuleSha256", "gateScope", "partnerEventId",
           "partnerFrozenLedgerSha256", "compositionUniverseSha256", "componentRankingSha256s", "protectedDState",
           "recordedAt", "recordedBy")
RESOLVED_FIELDS = (*_COMMON, "partnerCandidateId", "partnerIdentitySha256", "compositionSha256",
                   "ordinaryCompositionsSha256")
STOPPED_FIELDS = (*_COMMON, "stopReason", "stopDetail", "stopEvidenceSha256s", "protectedDAccessedAt")
SEAL_CITATION_RE = re.compile(r"^Baseline seal (?P<id>[A-Za-z][A-Za-z0-9-]{0,63}) SHA-256: (?P<sha>[0-9a-f]{64}) *$",
                              re.MULTILINE)


def seal_citation(composition_id: str, digest: str) -> str:
    """The exact record line that cites a committed seal."""
    return f"Baseline seal {composition_id} SHA-256: {digest}"


def record_seal_citations(text: str) -> dict[str, list[str]]:
    cited: dict[str, list[str]] = {}
    for match in SEAL_CITATION_RE.finditer(text.replace("\r\n", "\n")):
        cited.setdefault(match["id"], []).append(match["sha"])
    return cited


# ------------------------------------------------------------------ identities


def benchmark_component_identity_sha256(entry: Mapping) -> str:
    """The benchmark-only component's exact identity: pinned files, configuration, adapter and host bytes."""
    block = entry["benchmarkBaseline"]
    return document_sha256({"candidateId": entry["candidateId"], "identity": entry["identity"],
                            "configurationSha256": block["configurationSha256"],
                            "adapterSha256": block["adapterSha256"], "hostManifests": block["hostManifests"]})


def bob_payload_hashes(entry: Mapping) -> set[str]:
    """The benchmark-only component's executable, model, data and identity payload hashes (owner decision O7).

    Runtime-library dependencies are excluded: ordinary candidates may share them. Every other BOB hash is forbidden in
    any ordinary candidate, whatever the kind that candidate gives the file."""
    files = {item["sha256"] for item in entry["identity"]["files"]}
    files |= {item["sha256"] for listed in entry["benchmarkBaseline"]["hostManifests"].values() for item in listed
              if item["kind"] != "runtime-library"}
    return files


def candidate_file_hashes(entry: Mapping) -> set[str]:
    return {item["sha256"] for item in entry["identity"].get("files") or ()}


def candidate_identity_sha256(entry: Mapping) -> str:
    """A candidate's exact identity: the canonical SHA-256 of its ledger ``identity`` block."""
    return document_sha256(entry["identity"])


def composition_sha256(event_id: str, composition_id: str, benchmark_id: str, benchmark_identity: str,
                       partner_event_id: str, partner_id: str, partner_identity: str) -> str:
    return document_sha256({"role": "gate-only-baseline-composition", "eventId": event_id,
                            "compositionId": composition_id,
                            "benchmarkComponent": {"candidateId": benchmark_id, "identitySha256": benchmark_identity},
                            "partner": {"eventId": partner_event_id, "candidateId": partner_id,
                                        "identitySha256": partner_identity}})


def seal_sha256(seal: Mapping) -> str:
    return document_sha256(seal)


def frozen_compositions(frozen: Mapping) -> dict[str, tuple[dict, dict]]:
    """``{compositionId: (benchmark-only entry, frozen Stage-1 rule)}`` of a frozen ledger."""
    found: dict[str, tuple[dict, dict]] = {}
    for entry in frozen["candidates"]:
        if entry["disposition"]["status"] == BENCHMARK_BASELINE:
            for composition in entry["benchmarkBaseline"]["compositions"]:
                found[composition["compositionId"]] = (entry, composition)
    return found


def capability_of(event_id: str) -> str:
    return event_id[len("msr-"):-len("-yyyy-nn")]



# ------------------------------------------------------------------ Stage 1 (ledger)


def check_stage1_rule(composition: Mapping, entry: Mapping, where: str) -> None:
    """Structural checks of one frozen Stage-1 rule (called from the ledger check)."""
    _keys(composition, ("compositionId", "partnerEventId", "eligiblePartners", "excludedPartners", "derivationRule",
                        "gateScope"), where)
    _match(composition["compositionId"], LOCAL_ID_RE, f"{where}.compositionId")
    _match(composition["partnerEventId"], EVENT_ID_RE, f"{where}.partnerEventId")
    _enum(composition["derivationRule"], DERIVATION_RULES, f"{where}.derivationRule")
    if composition["gateScope"] == GATE_SCOPE_LISTED_DISABLED:
        raise _fail("gate_scope_listed_compositions_disabled", f"{where}.gateScope")
    _enum(composition["gateScope"], GATE_SCOPES, f"{where}.gateScope")
    partners = _list(composition["eligiblePartners"], f"{where}.eligiblePartners")
    partner_ids = []
    for index, partner in enumerate(partners):
        _keys(partner, ("candidateId", "identitySha256"), f"{where}.eligiblePartners[{index}]")
        partner_ids.append(_match(partner["candidateId"], CANDIDATE_ID_RE, f"{where}.eligiblePartners[{index}]"))
        _match(partner["identitySha256"], SHA256_RE, f"{where}.eligiblePartners[{index}].identitySha256")
    if not partner_ids or partner_ids != sorted(set(partner_ids)):
        raise _fail("eligible_partners_not_sorted_unique", f"{where}.eligiblePartners")
    if entry["candidateId"] in partner_ids:
        raise _fail("benchmark_baseline_cannot_be_its_own_partner", f"{where}.eligiblePartners")
    excluded_ids = []
    for index, partner in enumerate(_list(composition["excludedPartners"], f"{where}.excludedPartners")):
        at = f"{where}.excludedPartners[{index}]"
        _keys(partner, ("candidateId", "identitySha256", "reason"), at)
        excluded_ids.append(_match(partner["candidateId"], CANDIDATE_ID_RE, f"{at}.candidateId"))
        _match(partner["identitySha256"], SHA256_RE, f"{at}.identitySha256")
        _text(partner["reason"], f"{at}.reason")
    if excluded_ids != sorted(set(excluded_ids)) or set(excluded_ids) & set(partner_ids):
        raise _fail("excluded_partners_not_sorted_unique_disjoint", f"{where}.excludedPartners")


def check_partner_universe(composition: Mapping, partner_ledger: Mapping, where: str, benchmark_entry: Mapping) -> None:
    """The frozen universe reconciles with the partner event: each eligible or excluded partner is shortlisted there
    with that identity, together they are exactly its shortlist, and no eligible partner holds a BOB payload file."""
    if partner_ledger["eventId"] != composition["partnerEventId"]:
        raise _fail("baseline_partner_event_mismatch", where)
    entries = {e["candidateId"]: e for e in partner_ledger["candidates"]}
    listed = [*composition["eligiblePartners"], *composition["excludedPartners"]]
    for partner in listed:
        entry = entries.get(partner["candidateId"])
        if (entry is None or entry["disposition"]["status"] != SHORTLISTED
                or candidate_identity_sha256(entry) != partner["identitySha256"]):
            raise _fail("baseline_partner_not_in_partner_shortlist", f"{where}.{partner['candidateId']}")
    shortlist = {c for c, e in entries.items() if e["disposition"]["status"] == SHORTLISTED}
    if {p["candidateId"] for p in listed} != shortlist:
        raise _fail("baseline_partner_universe_not_the_shortlist", where)
    forbidden = bob_payload_hashes(benchmark_entry)
    for partner in composition["eligiblePartners"]:
        if candidate_file_hashes(entries[partner["candidateId"]]) & forbidden:
            raise _fail("benchmark_baseline_bytes_as_partner", f"{where}.{partner['candidateId']}")


# ------------------------------------------------------------------ Stage 2 (seal)


def _ranking_hashes(universe: Mapping, rankings: Mapping[str, Mapping | None]) -> dict[str, str | None]:
    return {item["eventId"]: (None if rankings.get(item["eventId"]) is None
                              else document_sha256(rankings[item["eventId"]]))
            for item in universe["componentEvents"]}


def _common(frozen: Mapping, composition_id: str, protocol_sha256: str, partner_ledger: Mapping | None,
            rankings: Mapping[str, Mapping | None], recorded_at: str, recorded_by: str, status: str) -> dict:
    entry, rule = frozen_compositions(frozen)[composition_id]
    universe = frozen[UNIVERSE_FIELD]
    partner_event = rule["partnerEventId"]
    return {
        "schema": SEAL_SCHEMA, "status": status, "eventId": frozen["eventId"], "capabilityId": frozen["capabilityId"],
        "compositionId": composition_id, "benchmarkBaselineId": entry["candidateId"],
        "benchmarkComponentIdentitySha256": benchmark_component_identity_sha256(entry),
        "protocolSha256": protocol_sha256, "frozenLedgerSha256": document_sha256(frozen),
        "stage1RuleSha256": document_sha256(rule), "eligibleUniverseSha256": document_sha256(rule["eligiblePartners"]),
        "layerAGatesSha256": ranking_gates_sha256(universe, partner_event),
        "partnerRankingRuleSha256": ranking_rule_sha256(universe, partner_event),
        "gateScope": rule["gateScope"], "partnerEventId": partner_event,
        "partnerFrozenLedgerSha256": None if partner_ledger is None else document_sha256(partner_ledger),
        "compositionUniverseSha256": group_id(universe),
        "componentRankingSha256s": _ranking_hashes(universe, rankings),
        "protectedDState": D_NOT_STARTED, "recordedAt": recorded_at, "recordedBy": recorded_by,
    }


_STOP_FOR_CODE = {
    "baseline_partner_event_missing": "partner-event-missing",
    "baseline_partner_event_mismatch": "partner-event-inconsistent",
    "baseline_partner_not_in_group": "partner-event-inconsistent",
    "baseline_partner_not_in_partner_shortlist": "partner-universe-inconsistent",
    "baseline_partner_universe_not_the_shortlist": "partner-universe-inconsistent",
    "benchmark_baseline_bytes_as_partner": "partner-universe-inconsistent",
    "component_ranking_identity_mismatch": "identity-mismatch",
    "partner_rank_ambiguous": "resolution-ambiguous",
    "component_rank_ambiguous": "component-rank-ambiguous",
    "component_ranking_not_for_this_event": "component-ranking-inconsistent",
    "component_ranking_universe_mismatch": "component-ranking-inconsistent",
    "component_ranking_rule_mismatch": "component-ranking-inconsistent",
    "component_ranking_candidate_not_shortlisted": "component-ranking-inconsistent",
    "component_ranking_not_the_shortlist": "component-ranking-inconsistent",
    "component_ranking_gates_mismatch": "component-ranking-inconsistent",
    "component_ranking_metrics_mismatch": "component-ranking-inconsistent",
}


@dataclass(frozen=True)
class Derivation:
    """What the frozen rule derives from complete, consistent inputs."""
    partner: str
    ordinary: list
    rankings: dict


def derive_group_inputs(frozen: Mapping, composition_id: str, partner_ledger: Mapping | None,
                        rankings: Mapping[str, Mapping | None]) -> Derivation | str:
    """Derive PD_BASE and U, or return the missing-input stop detail. Inconsistent inputs raise."""
    entry, rule = frozen_compositions(frozen)[composition_id]
    universe = frozen[UNIVERSE_FIELD]
    if partner_ledger is None:
        raise _fail("baseline_partner_event_missing", rule["partnerEventId"])
    validate_ledger(partner_ledger)
    if partner_ledger.get(UNIVERSE_FIELD) != universe:
        raise _fail("baseline_partner_not_in_group", rule["partnerEventId"])
    check_partner_universe(rule, partner_ledger, "partner", entry)
    frozen_by_event = {frozen["eventId"]: frozen, partner_ledger["eventId"]: partner_ledger}
    checked = {}
    for item in universe["componentEvents"]:
        document = rankings.get(item["eventId"])
        if document is None:
            return f"no component ranking for {item['eventId']}"
        checked[item["eventId"]] = check_component_ranking(document, frozen_by_event[item["eventId"]])
    partner = best_partner(checked[rule["partnerEventId"]], {p["candidateId"] for p in rule["eligiblePartners"]})
    if partner is None:
        return "no-partner"
    ordinary = derive_ordinary_universe(universe, frozen_by_event, checked)
    return Derivation(partner, ordinary, checked)


def derive_baseline_seal(frozen: Mapping, composition_id: str, *, protocol_sha256: str,
                         partner_ledger: Mapping | None, rankings: Mapping[str, Mapping | None], recorded_at: str,
                         recorded_by: str, protected_d_rows_read: int = 0,
                         protected_d_accessed_at: str | None = None) -> dict:
    """Stage 2, deterministically: the RESOLVED seal, or the STOPPED seal with its exact reason. Never chooses."""
    validate_ledger(frozen)
    if composition_id not in frozen_compositions(frozen):
        raise _fail("gate_only_composition_not_frozen", composition_id)

    def stopped(reason: str, detail: str, *, accessed: bool = False) -> dict:
        seal = _common(frozen, composition_id, protocol_sha256, partner_ledger, rankings, recorded_at, recorded_by,
                       STOPPED)
        evidence = {seal["frozenLedgerSha256"], seal["partnerFrozenLedgerSha256"],
                    *seal["componentRankingSha256s"].values()}
        seal.update(stopReason=reason, stopDetail=detail, stopEvidenceSha256s=sorted(h for h in evidence if h),
                    protectedDState=D_ACCESSED if accessed else D_NOT_STARTED,
                    protectedDAccessedAt=protected_d_accessed_at if accessed else None)
        return seal

    if protected_d_rows_read != 0:
        _instant(protected_d_accessed_at, "protectedDAccessedAt")
        return stopped("protected-d-accessed", f"{protected_d_rows_read} protected D rows read before resolution",
                       accessed=True)
    entry, rule = frozen_compositions(frozen)[composition_id]
    try:
        derived = derive_group_inputs(frozen, composition_id, partner_ledger, rankings)
    except CredibilityError as error:
        code = str(error).split(":")[0]
        return stopped(_STOP_FOR_CODE.get(code, "prerequisite-failed"), str(error))
    if derived == "no-partner":
        return stopped("no-partner-passed-layer-a", "no eligible partner passed every frozen ranking gate")
    if isinstance(derived, str):
        return stopped("prerequisite-failed", derived)
    seal = _common(frozen, composition_id, protocol_sha256, partner_ledger, rankings, recorded_at, recorded_by,
                   RESOLVED)
    identity = {p["candidateId"]: p["identitySha256"] for p in rule["eligiblePartners"]}[derived.partner]
    seal.update(partnerCandidateId=derived.partner, partnerIdentitySha256=identity,
                compositionSha256=composition_sha256(frozen["eventId"], composition_id, seal["benchmarkBaselineId"],
                                                     seal["benchmarkComponentIdentitySha256"], rule["partnerEventId"],
                                                     derived.partner, identity),
                ordinaryCompositionsSha256=ordinary_compositions_sha256(derived.ordinary))
    return seal


def verify_baseline_seal(seal: object, *, frozen: Mapping, protocol_sha256: str, partner_ledger: Mapping | None,
                         rankings: Mapping[str, Mapping | None]) -> str:
    """Verify a seal against its frozen inputs; return its SHA-256. Any mismatch is a refusal.

    A RESOLVED seal must equal the re-derivation field for field (apart from its audit time and author). A STOPPED
    seal must carry the frozen identities, name no partner or composition, record every supplied input by its hash,
    and with every input supplied its reason must be the derived one."""
    where = "seal"
    if not isinstance(seal, dict):
        raise _fail("not_object", where)
    status = _enum(seal.get("status"), SEAL_STATUSES, f"{where}.status")
    _keys(seal, RESOLVED_FIELDS if status == RESOLVED else STOPPED_FIELDS, where)
    if seal["schema"] != SEAL_SCHEMA:
        raise _fail("schema_unsupported", f"{where}.schema")
    declared = frozen_compositions(frozen)
    if seal["eventId"] != frozen["eventId"] or seal["compositionId"] not in declared:
        raise _fail("gate_only_composition_not_frozen", f"{where}.compositionId")
    _match(seal["protocolSha256"], SHA256_RE, f"{where}.protocolSha256")
    _text(seal["recordedBy"], f"{where}.recordedBy")
    recorded = _instant(seal["recordedAt"], f"{where}.recordedAt")
    frozen_on = datetime.combine(date.fromisoformat(frozen["frozenOn"]), datetime.min.time(), tzinfo=timezone.utc)
    if recorded < frozen_on:
        raise _fail("baseline_resolved_before_freeze", f"{where}.recordedAt")
    expected = _common(frozen, seal["compositionId"], protocol_sha256, partner_ledger, rankings, seal["recordedAt"],
                       seal["recordedBy"], status)
    if status == STOPPED:
        _enum(seal["stopReason"], STOP_REASONS, f"{where}.stopReason")
        _text(seal["stopDetail"], f"{where}.stopDetail")
        evidence = _list(seal["stopEvidenceSha256s"], f"{where}.stopEvidenceSha256s")
        for value in evidence:
            _match(value, SHA256_RE, f"{where}.stopEvidenceSha256s")
        if not evidence or evidence != sorted(set(evidence)):
            raise _fail("baseline_stop_evidence_required", f"{where}.stopEvidenceSha256s")
        accessed = seal["stopReason"] == "protected-d-accessed"
        if seal["protectedDState"] != (D_ACCESSED if accessed else D_NOT_STARTED):
            raise _fail("baseline_seal_d_state_contradicted", f"{where}.protectedDState")
        if accessed:
            if _instant(seal["protectedDAccessedAt"], f"{where}.protectedDAccessedAt") > recorded:
                raise _fail("baseline_seal_d_state_contradicted", f"{where}.protectedDAccessedAt")
        elif seal["protectedDAccessedAt"] is not None:
            raise _fail("baseline_seal_d_state_contradicted", f"{where}.protectedDAccessedAt")
        # A stop may not claim an input absent while it is supplied, and a recorded hash must match the supplied
        # artefact. Only an input absent now leaves its recorded hash unchecked (in repository mode, artefacts are
        # add-only, so a committed input never becomes absent).
        if partner_ledger is not None and seal["partnerFrozenLedgerSha256"] is None:
            raise _fail("baseline_stop_reason_contradicted", f"{where}.partnerFrozenLedgerSha256")
        if partner_ledger is None:
            expected["partnerFrozenLedgerSha256"] = seal["partnerFrozenLedgerSha256"]
            if seal["partnerFrozenLedgerSha256"] is not None:
                _match(seal["partnerFrozenLedgerSha256"], SHA256_RE, f"{where}.partnerFrozenLedgerSha256")
        recorded_rankings = seal["componentRankingSha256s"]
        if not isinstance(recorded_rankings, dict) or \
                set(recorded_rankings) != set(expected["componentRankingSha256s"]):
            raise _fail("baseline_seal_differs_from_frozen_inputs", f"{where}.componentRankingSha256s")
        for event_id, supplied in expected["componentRankingSha256s"].items():
            if supplied is not None and recorded_rankings[event_id] is None:
                raise _fail("baseline_stop_reason_contradicted", f"{where}.componentRankingSha256s.{event_id}")
            if supplied is None:
                expected["componentRankingSha256s"][event_id] = recorded_rankings[event_id]
                if recorded_rankings[event_id] is not None:
                    _match(recorded_rankings[event_id], SHA256_RE, f"{where}.componentRankingSha256s.{event_id}")
        expected["protectedDState"] = seal["protectedDState"]
        for field in _COMMON:
            if seal[field] != expected[field]:
                raise _fail("baseline_seal_differs_from_frozen_inputs", f"{where}.{field}")
        complete = partner_ledger is not None and all(rankings.get(e) is not None
                                                      for e in expected["componentRankingSha256s"])
        if complete and not accessed:
            derived = derive_baseline_seal(frozen, seal["compositionId"], protocol_sha256=protocol_sha256,
                                           partner_ledger=partner_ledger, rankings=rankings,
                                           recorded_at=seal["recordedAt"], recorded_by=seal["recordedBy"])
            if derived["status"] == RESOLVED or derived["stopReason"] != seal["stopReason"]:
                raise _fail("baseline_stop_reason_contradicted", f"{where}.stopReason")
        return seal_sha256(seal)
    if seal["protectedDState"] != D_NOT_STARTED:
        raise _fail("baseline_seal_d_state_contradicted", f"{where}.protectedDState")
    derived = derive_baseline_seal(frozen, seal["compositionId"], protocol_sha256=protocol_sha256,
                                   partner_ledger=partner_ledger, rankings=rankings, recorded_at=seal["recordedAt"],
                                   recorded_by=seal["recordedBy"])
    if derived["status"] != RESOLVED:
        raise _fail("baseline_seal_not_derivable", f"{where}:{derived['stopReason']}")
    for field in RESOLVED_FIELDS:
        if seal[field] != derived[field]:
            code = "baseline_seal_partner_not_derived" if field in ("partnerCandidateId", "partnerIdentitySha256") \
                else "baseline_seal_differs_from_frozen_inputs"
            raise _fail(code, f"{where}.{field}")
    return seal_sha256(seal)


# ------------------------------------------------------------------ repository files


def event_folder(repo: Path, capability_id: str) -> Path:
    return Path(repo) / MODEL_SELECTION_DIR / capability_id


def seal_path(repo: Path, frozen: Mapping, composition_id: str) -> Path:
    return event_folder(repo, frozen["capabilityId"]) / f"{frozen['eventId']}{SEAL_INFIX}{composition_id}.json"









def read_canonical(path: Path, code: str) -> dict:
    """A seal, ranking or D manifest is canonical JSON, so its file hash and its document hash coincide."""
    document = read_json(path)
    if path.read_bytes().replace(b"\r\n", b"\n") != canonical_json(document):
        raise _fail(code, path.name)
    return document


@dataclass(frozen=True)
class SealBinding:
    """What a protected D manifest/result records for the group's gate-only composition."""
    composition_id: str
    seal_sha256: str
    seal_commit: str
    partner_candidate_id: str
    partner_identity_sha256: str
    composition_sha256: str
