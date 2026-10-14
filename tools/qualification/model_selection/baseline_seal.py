"""MSR revision M3: the committed pre-D seal of a gate-only baseline composition.

Normative text: ``docs/qualification/model-selection/proposals/m3-benchmark-only-baseline.md`` (rules 4, 4a, 5, 9) and
``candidate-credibility.md`` §4.4 and §8. Three artefacts sit beside the event's MSR files, in
``docs/qualification/model-selection/<capabilityId>/``:

* the **Stage-1 rule**, frozen in the benchmark-only baseline's ledger entry (``benchmarkBaseline.compositions[]``):
  partner event, finite ``eligiblePartners`` with exact identity hashes, Layer-A gate ids and gate-set hash, partner
  ranking/tie-break rule hash, derivation rule and gate scope;
* the **Layer-A result** ``<event-id>-layer-a-<compositionId>.json`` (``mavi-model-selection-layer-a-result-v1``):
  per eligible partner, its exact identity, every frozen Layer-A gate result and its rank key under the frozen rule;
* the **baseline seal** ``<event-id>-baseline-seal-<compositionId>.json`` (``mavi-model-selection-baseline-seal-v1``),
  status ``RESOLVED`` or ``STOPPED``. It is committed, canonical JSON, and cited by the event record **before** any
  protected D data is read. Its identity is its canonical SHA-256 (``seal_sha256``); it holds no self-hash.

A RESOLVED seal is valid only if it is exactly what ``derive_baseline_seal`` re-derives from the frozen ledger, the
protocol hash, the partner event's frozen ledger and the Layer-A result. Re-sealing to another partner therefore
needs a different Layer-A result, and every D artefact and the decision summary carry the seal hash, so a change after
D is refused wherever the earlier hash was recorded (``verify_d_manifest_binding``, the decision check and the
repository check). A STOPPED seal names no partner and no composition, and permits no D execution.

Harness obligation (README §14.3): before reading any protected D data, call ``require_committed_baseline_seal`` for
every frozen gate-only composition of the event; refuse D unless every seal is RESOLVED; record the returned seal
SHA-256 and seal commit in every protected D manifest and result (``baselineSeals``); and check each D manifest with
``verify_d_manifest_binding`` before it is scored.

Standard library only; ``require_committed_baseline_seal`` and ``verify_d_manifest_binding`` run ``git`` locally.
"""

from __future__ import annotations

import math
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from .credibility import (
    BENCHMARK_BASELINE,
    IMMUTABLE_REVISION_RE,
    CANDIDATE_ID_RE,
    EVENT_ID_RE,
    FROZEN_SUFFIX,
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

SEAL_SCHEMA = "mavi-model-selection-baseline-seal-v1"
LAYER_A_SCHEMA = "mavi-model-selection-layer-a-result-v1"
RESOLVED, STOPPED = "RESOLVED", "STOPPED"
SEAL_STATUSES = (RESOLVED, STOPPED)
GATE_SCOPE_ALL = "all-ordinary-compositions"
GATE_SCOPES = (GATE_SCOPE_ALL,)
DERIVATION_RULE = "highest-ranked-partner-passing-every-layer-a-gate"
DERIVATION_RULES = (DERIVATION_RULE,)
D_NOT_STARTED, D_ACCESSED = "NOT_STARTED", "ACCESSED"
PASSED, FAILED = "passed", "failed"
STOP_REASONS = (
    "no-partner-passed-layer-a",
    "partner-event-missing",
    "partner-event-inconsistent",
    "partner-universe-inconsistent",
    "identity-mismatch",
    "resolution-ambiguous",
    "protected-d-accessed",
    "prerequisite-failed",
)
SEAL_INFIX = "-baseline-seal-"
LAYER_A_INFIX = "-layer-a-"

_COMMON = ("schema", "status", "eventId", "capabilityId", "compositionId", "benchmarkBaselineId",
           "benchmarkComponentIdentitySha256", "protocolSha256", "frozenLedgerSha256", "stage1RuleSha256",
           "eligibleUniverseSha256", "layerAGatesSha256", "partnerRankingRuleSha256", "gateScope", "partnerEventId",
           "partnerFrozenLedgerSha256", "layerAResultSha256", "protectedDState", "recordedAt", "recordedBy")
RESOLVED_FIELDS = (*_COMMON, "partnerCandidateId", "partnerIdentitySha256", "compositionSha256")
STOPPED_FIELDS = (*_COMMON, "stopReason", "stopDetail", "stopEvidenceSha256s", "protectedDAccessedAt")
# The event record cites each seal on one structured line (cold review P1-1). Exactly one line per composition, and
# its hash must be the seal file's: a second line, or a changed seal under an old line, is refused.
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


def benchmark_file_hashes(entry: Mapping) -> set[str]:
    """Every file hash of a benchmark-only component: pinned identity files and every host-manifest file."""
    files = {item["sha256"] for item in entry["identity"]["files"]}
    files |= {item["sha256"] for listed in entry["benchmarkBaseline"]["hostManifests"].values() for item in listed}
    return files


def candidate_file_hashes(entry: Mapping) -> set[str]:
    return {item["sha256"] for item in entry["identity"].get("files") or ()}


def candidate_identity_sha256(entry: Mapping) -> str:
    """A partner's exact identity: the canonical SHA-256 of its ledger ``identity`` block (as ``identitySha256``)."""
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


def partner_capability(event_id: str) -> str:
    return event_id[len("msr-"):-len("-yyyy-nn")]


# ------------------------------------------------------------------ Stage 1 (ledger)


def check_stage1_rule(composition: Mapping, entry: Mapping, where: str) -> None:
    """Structural checks of one frozen Stage-1 rule (called from the ledger check)."""
    _keys(composition, ("compositionId", "partnerEventId", "eligiblePartners", "excludedPartners",
                        "partnerRankingRuleSha256", "layerAGatesSha256", "layerAGateIds", "derivationRule",
                        "gateScope"), where)
    _match(composition["compositionId"], LOCAL_ID_RE, f"{where}.compositionId")
    _match(composition["partnerEventId"], EVENT_ID_RE, f"{where}.partnerEventId")
    _match(composition["partnerRankingRuleSha256"], SHA256_RE, f"{where}.partnerRankingRuleSha256")
    _match(composition["layerAGatesSha256"], SHA256_RE, f"{where}.layerAGatesSha256")
    _enum(composition["derivationRule"], DERIVATION_RULES, f"{where}.derivationRule")
    _enum(composition["gateScope"], GATE_SCOPES, f"{where}.gateScope")
    gate_ids = _list(composition["layerAGateIds"], f"{where}.layerAGateIds")
    for index, gate in enumerate(gate_ids):
        _match(gate, LOCAL_ID_RE, f"{where}.layerAGateIds[{index}]")
    if not gate_ids or gate_ids != sorted(set(gate_ids)):
        raise _fail("layer_a_gates_not_sorted_unique", f"{where}.layerAGateIds")
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
    # Cold review P3-4: every shortlisted candidate of the partner event that is not eligible is listed here with the
    # recorded reason, so the frozen universe is the partner shortlist exactly, never a silent subset.
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
    with that identity, together they are exactly its shortlist, and no eligible partner shares a file with the
    benchmark-only component (its bytes re-listed under another identity, cold review P3-3)."""
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
    forbidden = benchmark_file_hashes(benchmark_entry)
    for partner in composition["eligiblePartners"]:
        if candidate_file_hashes(entries[partner["candidateId"]]) & forbidden:
            raise _fail("benchmark_baseline_bytes_as_partner", f"{where}.{partner['candidateId']}")


# ------------------------------------------------------------------ Layer A


def _rank_key(value: object, where: str) -> tuple:
    key = _list(value, where)
    if not key:
        raise _fail("layer_a_rank_key_malformed", where)
    for item in key:
        if isinstance(item, float) and not math.isfinite(item):
            raise _fail("layer_a_rank_key_malformed", where)
        if not isinstance(item, (bool, int, float, str)):
            raise _fail("layer_a_rank_key_malformed", where)
    return tuple(key)


def _kind(item: object) -> str:
    return "bool" if isinstance(item, bool) else "number" if isinstance(item, (int, float)) else "text"


def check_layer_a_result(document: object, frozen: Mapping, composition_id: str,
                         partner_ledger: Mapping | None) -> str | None:
    """Validate a Layer-A result against the frozen Stage-1 rule; return the derived partner, or None.

    None means no partner passed every frozen gate. A rank tie among passing partners is ambiguous and refused,
    as is any partner, identity, gate or rule that differs from the frozen universe."""
    where = "layerA"
    declared = frozen_compositions(frozen)
    if composition_id not in declared:
        raise _fail("gate_only_composition_not_frozen", where)
    rule = declared[composition_id][1]
    _keys(document, ("schema", "eventId", "compositionId", "partnerEventId", "partnerFrozenLedgerSha256",
                     "layerAGatesSha256", "layerAGateIds", "partnerRankingRuleSha256", "results", "evidenceSha256"),
          where)
    if document["schema"] != LAYER_A_SCHEMA:
        raise _fail("schema_unsupported", f"{where}.schema")
    if (document["eventId"], document["compositionId"]) != (frozen["eventId"], composition_id):
        raise _fail("layer_a_result_not_for_this_composition", where)
    if document["partnerEventId"] != rule["partnerEventId"]:
        raise _fail("baseline_partner_event_mismatch", f"{where}.partnerEventId")
    if partner_ledger is None:
        raise _fail("baseline_partner_event_missing", f"{where}.partnerEventId")
    if document["partnerFrozenLedgerSha256"] != document_sha256(partner_ledger):
        raise _fail("baseline_partner_event_mismatch", f"{where}.partnerFrozenLedgerSha256")
    if document["layerAGatesSha256"] != rule["layerAGatesSha256"] or document["layerAGateIds"] != rule["layerAGateIds"]:
        raise _fail("layer_a_gates_mismatch", where)
    if document["partnerRankingRuleSha256"] != rule["partnerRankingRuleSha256"]:
        raise _fail("baseline_ranking_rule_mismatch", f"{where}.partnerRankingRuleSha256")
    _match(document["evidenceSha256"], SHA256_RE, f"{where}.evidenceSha256")
    universe = {p["candidateId"]: p["identitySha256"] for p in rule["eligiblePartners"]}
    rows = _list(document["results"], f"{where}.results")
    ids, passing, kinds = [], {}, None
    for index, row in enumerate(rows):
        at = f"{where}.results[{index}]"
        _keys(row, ("candidateId", "identitySha256", "gates", "rankKey", "measurementSha256"), at)
        candidate = row["candidateId"]
        if candidate not in universe:
            raise _fail("layer_a_partner_outside_frozen_universe", at)
        if row["identitySha256"] != universe[candidate]:
            raise _fail("layer_a_identity_mismatch", at)
        _match(row["measurementSha256"], SHA256_RE, f"{at}.measurementSha256")
        gates = row["gates"]
        if not isinstance(gates, dict) or sorted(gates) != rule["layerAGateIds"]:
            raise _fail("layer_a_gates_mismatch", f"{at}.gates")
        for gate, result in gates.items():
            _enum(result, (PASSED, FAILED), f"{at}.gates.{gate}")
        key = _rank_key(row["rankKey"], f"{at}.rankKey")
        shape = tuple(_kind(item) for item in key)
        if kinds is not None and shape != kinds:
            raise _fail("layer_a_rank_key_malformed", f"{at}.rankKey")
        kinds = shape
        ids.append(candidate)
        if all(result == PASSED for result in gates.values()):
            passing[candidate] = key
    if ids != sorted(set(ids)) or set(ids) != set(universe):
        raise _fail("layer_a_result_inconsistent_with_frozen_universe", f"{where}.results")
    if not passing:
        return None
    best = min(passing.values())
    winners = [candidate for candidate, key in passing.items() if key == best]
    if len(winners) != 1:
        raise _fail("layer_a_rank_ambiguous", f"{where}.results")
    return winners[0]


# ------------------------------------------------------------------ Stage 2 (seal)


def _common(frozen: Mapping, composition_id: str, protocol_sha256: str, partner_ledger: Mapping | None,
            layer_a: Mapping | None, recorded_at: str, recorded_by: str, status: str) -> dict:
    entry, rule = frozen_compositions(frozen)[composition_id]
    return {
        "schema": SEAL_SCHEMA, "status": status, "eventId": frozen["eventId"], "capabilityId": frozen["capabilityId"],
        "compositionId": composition_id, "benchmarkBaselineId": entry["candidateId"],
        "benchmarkComponentIdentitySha256": benchmark_component_identity_sha256(entry),
        "protocolSha256": protocol_sha256, "frozenLedgerSha256": document_sha256(frozen),
        "stage1RuleSha256": document_sha256(rule), "eligibleUniverseSha256": document_sha256(rule["eligiblePartners"]),
        "layerAGatesSha256": rule["layerAGatesSha256"], "partnerRankingRuleSha256": rule["partnerRankingRuleSha256"],
        "gateScope": rule["gateScope"], "partnerEventId": rule["partnerEventId"],
        "partnerFrozenLedgerSha256": None if partner_ledger is None else document_sha256(partner_ledger),
        "layerAResultSha256": None if layer_a is None else document_sha256(layer_a),
        "protectedDState": D_NOT_STARTED, "recordedAt": recorded_at, "recordedBy": recorded_by,
    }


_STOP_FOR_CODE = {
    "baseline_partner_event_missing": "partner-event-missing",
    "baseline_partner_event_mismatch": "partner-event-inconsistent",
    "baseline_partner_not_in_partner_shortlist": "partner-universe-inconsistent",
    "baseline_partner_universe_not_the_shortlist": "partner-universe-inconsistent",
    "benchmark_baseline_bytes_as_partner": "partner-universe-inconsistent",
    "layer_a_partner_outside_frozen_universe": "partner-universe-inconsistent",
    "layer_a_result_inconsistent_with_frozen_universe": "partner-universe-inconsistent",
    "layer_a_identity_mismatch": "identity-mismatch",
    "layer_a_rank_ambiguous": "resolution-ambiguous",
}


def derive_baseline_seal(frozen: Mapping, composition_id: str, *, protocol_sha256: str,
                         partner_ledger: Mapping | None, layer_a: Mapping | None, recorded_at: str,
                         recorded_by: str, protected_d_rows_read: int = 0,
                         protected_d_accessed_at: str | None = None) -> dict:
    """Stage 2, deterministically: the RESOLVED seal, or the STOPPED seal with its exact reason. Never chooses."""
    validate_ledger(frozen)
    if composition_id not in frozen_compositions(frozen):
        raise _fail("gate_only_composition_not_frozen", composition_id)

    def stopped(reason: str, detail: str, *, accessed: bool = False) -> dict:
        seal = _common(frozen, composition_id, protocol_sha256, partner_ledger, layer_a, recorded_at, recorded_by,
                       STOPPED)
        evidence = sorted({h for h in (seal["frozenLedgerSha256"], seal["partnerFrozenLedgerSha256"],
                                       seal["layerAResultSha256"]) if h is not None})
        seal.update(stopReason=reason, stopDetail=detail, stopEvidenceSha256s=evidence,
                    protectedDState=D_ACCESSED if accessed else D_NOT_STARTED,
                    protectedDAccessedAt=protected_d_accessed_at if accessed else None)
        return seal

    if protected_d_rows_read != 0:
        # Cold review P3-2: a stop for protected-D access records when D was accessed.
        _instant(protected_d_accessed_at, "protectedDAccessedAt")
        return stopped("protected-d-accessed", f"{protected_d_rows_read} protected D rows read before resolution",
                       accessed=True)
    benchmark_entry, rule = frozen_compositions(frozen)[composition_id]
    try:
        if partner_ledger is None:
            raise _fail("baseline_partner_event_missing", rule["partnerEventId"])
        validate_ledger(partner_ledger)
        check_partner_universe(rule, partner_ledger, "partner", benchmark_entry)
        if layer_a is None:
            return stopped("prerequisite-failed", "no Layer-A result")
        partner = check_layer_a_result(layer_a, frozen, composition_id, partner_ledger)
    except CredibilityError as error:
        code = str(error).split(":")[0]
        return stopped(_STOP_FOR_CODE.get(code, "prerequisite-failed"), str(error))
    if partner is None:
        return stopped("no-partner-passed-layer-a", "no eligible partner passed every frozen Layer-A gate")
    seal = _common(frozen, composition_id, protocol_sha256, partner_ledger, layer_a, recorded_at, recorded_by,
                   RESOLVED)
    identity = {p["candidateId"]: p["identitySha256"] for p in rule["eligiblePartners"]}[partner]
    seal.update(partnerCandidateId=partner, partnerIdentitySha256=identity,
                compositionSha256=composition_sha256(frozen["eventId"], composition_id, seal["benchmarkBaselineId"],
                                                     seal["benchmarkComponentIdentitySha256"], rule["partnerEventId"],
                                                     partner, identity))
    return seal


def verify_baseline_seal(seal: object, *, frozen: Mapping, protocol_sha256: str, partner_ledger: Mapping | None,
                         layer_a: Mapping | None) -> str:
    """Verify a seal against its frozen inputs; return its SHA-256. Any mismatch is a refusal.

    A RESOLVED seal must equal the re-derivation field for field (apart from its audit time and author). A STOPPED
    seal must carry the frozen identities, name no partner or composition, and its reason must not be contradicted by
    the inputs supplied."""
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
    expected = _common(frozen, seal["compositionId"], protocol_sha256, partner_ledger, layer_a, seal["recordedAt"],
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
        # Cold review P3-1: a stop may not claim an input was absent while it is supplied, and a recorded hash must
        # match the supplied artefact. Only an artefact absent now leaves its recorded hash unchecked.
        for field, supplied in (("partnerFrozenLedgerSha256", partner_ledger), ("layerAResultSha256", layer_a)):
            if supplied is not None and seal[field] is None:
                raise _fail("baseline_stop_reason_contradicted", f"{where}.{field}")
            if supplied is None:
                expected[field] = seal[field]
                if seal[field] is not None:
                    _match(seal[field], SHA256_RE, f"{where}.{field}")
        expected["protectedDState"] = seal["protectedDState"]
        for field in _COMMON:
            if seal[field] != expected[field]:
                raise _fail("baseline_seal_differs_from_frozen_inputs", f"{where}.{field}")
        if partner_ledger is not None and layer_a is not None and not accessed:
            # With both inputs supplied the stop must be exactly the one the frozen rule derives from them.
            derived = derive_baseline_seal(frozen, seal["compositionId"], protocol_sha256=protocol_sha256,
                                           partner_ledger=partner_ledger, layer_a=layer_a,
                                           recorded_at=seal["recordedAt"], recorded_by=seal["recordedBy"])
            if derived["status"] == RESOLVED or derived["stopReason"] != seal["stopReason"]:
                raise _fail("baseline_stop_reason_contradicted", f"{where}.stopReason")
        return seal_sha256(seal)
    if seal["protectedDState"] != D_NOT_STARTED:
        raise _fail("baseline_seal_d_state_contradicted", f"{where}.protectedDState")
    derived = derive_baseline_seal(frozen, seal["compositionId"], protocol_sha256=protocol_sha256,
                                   partner_ledger=partner_ledger, layer_a=layer_a, recorded_at=seal["recordedAt"],
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
    return repo / MODEL_SELECTION_DIR / capability_id


def seal_path(repo: Path, frozen: Mapping, composition_id: str) -> Path:
    return event_folder(repo, frozen["capabilityId"]) / f"{frozen['eventId']}{SEAL_INFIX}{composition_id}.json"


def layer_a_path(repo: Path, frozen: Mapping, composition_id: str) -> Path:
    return event_folder(repo, frozen["capabilityId"]) / f"{frozen['eventId']}{LAYER_A_INFIX}{composition_id}.json"


def partner_frozen_path(repo: Path, partner_event_id: str) -> Path:
    return event_folder(repo, partner_capability(partner_event_id)) / f"{partner_event_id}{FROZEN_SUFFIX}"


def read_canonical(path: Path, code: str) -> dict:
    """A seal or Layer-A file is canonical JSON, so its file hash and its document hash coincide."""
    document = read_json(path)
    if path.read_bytes().replace(b"\r\n", b"\n") != canonical_json(document):
        raise _fail(code, path.name)
    return document


def load_baseline_evidence(repo: Path, frozen: Mapping) -> dict[str, dict]:
    """``{compositionId: {"seal", "layerA", "partnerLedger"}}`` from the committed files (None when absent)."""
    evidence: dict[str, dict] = {}
    for composition_id, (_entry, rule) in sorted(frozen_compositions(frozen).items()):
        seal_file, layer_file = seal_path(repo, frozen, composition_id), layer_a_path(repo, frozen, composition_id)
        partner_file = partner_frozen_path(repo, rule["partnerEventId"])
        evidence[composition_id] = {
            "seal": read_canonical(seal_file, "baseline_seal_not_canonical") if seal_file.is_file() else None,
            "layerA": read_canonical(layer_file, "layer_a_result_not_canonical") if layer_file.is_file() else None,
            "partnerLedger": read_json(partner_file) if partner_file.is_file() else None,
        }
    return evidence


def verify_event_seals(evidence: Mapping[str, Mapping], frozen: Mapping, protocol_sha256: str) -> dict[str, dict]:
    """Verify every present seal; return ``{compositionId: {"sha256", "status", "seal"}}`` for the sealed ones."""
    verified = {}
    declared = frozen_compositions(frozen)
    for composition_id, item in sorted(evidence.items()):
        if composition_id not in declared:
            raise _fail("gate_only_composition_not_frozen", f"evidence.{composition_id}")
        partner = item.get("partnerLedger")
        if partner is not None:
            validate_ledger(partner)
            check_partner_universe(declared[composition_id][1], partner, f"partner.{composition_id}",
                                   declared[composition_id][0])
        if item.get("seal") is None:
            continue
        digest = verify_baseline_seal(item["seal"], frozen=frozen, protocol_sha256=protocol_sha256,
                                      partner_ledger=partner, layer_a=item.get("layerA"))
        verified[composition_id] = {"sha256": digest, "status": item["seal"]["status"], "seal": item["seal"]}
    return verified


def validate_repository_seals(repo: Path, root: Path, frozen_by_event: Mapping[Path, Mapping],
                              protocol_sha_by_event: Mapping[Path, str]) -> list[str]:
    """Repository mode: every seal and Layer-A file belongs to a frozen composition (or is a superseded STOPPED seal),
    is canonical and verifies against its frozen inputs; the event record cites each seal on exactly one structured
    line carrying the seal file's hash; and, where full Git history is available, every seal and Layer-A file was
    only ever added and every record citation never changed (``check_seal_history``). Returns the files checked."""
    checked = []
    expected = set()
    for event, frozen in sorted(frozen_by_event.items(), key=lambda item: str(item[0])):
        if not frozen_compositions(frozen):
            continue
        evidence = load_baseline_evidence(repo, frozen)
        verified = verify_event_seals(evidence, frozen, protocol_sha_by_event[event])
        for composition_id in frozen_compositions(frozen):
            for path in (seal_path(repo, frozen, composition_id), layer_a_path(repo, frozen, composition_id)):
                expected.add(path.resolve())
                if path.is_file():
                    checked.append(path.relative_to(repo).as_posix())
            if evidence[composition_id]["layerA"] is not None and evidence[composition_id]["partnerLedger"] is not None \
                    and composition_id not in verified:
                # A Layer-A result committed before its seal must already be consistent with the frozen rule.
                check_layer_a_result(evidence[composition_id]["layerA"], frozen, composition_id,
                                     evidence[composition_id]["partnerLedger"])
    for pattern in (f"*/msr-*{SEAL_INFIX}*.json", f"*/msr-*{LAYER_A_INFIX}*.json"):
        for path in sorted(root.glob(pattern)):
            if path.resolve() in expected:
                continue
            if SEAL_INFIX in path.name and _superseded_stop(path, frozen_by_event):
                checked.append(path.relative_to(repo).as_posix())
                continue
            if LAYER_A_INFIX in path.name:
                # the Layer-A result a superseded STOPPED seal cites stays with it
                seal_file = path.with_name(path.name.replace(LAYER_A_INFIX, SEAL_INFIX, 1))
                if seal_file.is_file() and _superseded_stop(seal_file, frozen_by_event) and \
                        read_canonical(seal_file, "baseline_seal_not_canonical")["layerAResultSha256"] == \
                        document_sha256(read_canonical(path, "layer_a_result_not_canonical")):
                    checked.append(path.relative_to(repo).as_posix())
                    continue
            raise _fail("baseline_artefact_without_frozen_composition", path.relative_to(repo).as_posix())
    for event in sorted(frozen_by_event, key=str):
        check_record_citations(event)
    if any(SEAL_INFIX in path or LAYER_A_INFIX in path for path in checked):
        checked.append(f"git-history:{check_seal_history(repo, root)}")
    return checked


def _event_seal_files(event: Path) -> dict[str, Path]:
    prefix = f"{event.name}{SEAL_INFIX}"
    return {path.name[len(prefix):-len(".json")]: path for path in event.parent.glob(f"{prefix}*.json")}


def check_record_citations(event: Path) -> None:
    """Cold review P1-1: the record cites each seal of the event on exactly one structured line
    (``seal_citation``) whose hash is the seal file's, and cites no seal that does not exist. A seal replaced in
    place therefore needs its citation line edited, which ``check_seal_history`` refuses where Git history exists."""
    record = event.parent / f"{event.name}.md"
    cited = record_seal_citations(record.read_text(encoding="utf-8") if record.is_file() else "")
    seals = _event_seal_files(event)
    for composition_id, path in sorted(seals.items()):
        hashes = cited.get(composition_id, [])
        if len(hashes) > 1:
            raise _fail("baseline_seal_cited_twice", path.name)
        if hashes != [document_sha256(read_canonical(path, "baseline_seal_not_canonical"))]:
            raise _fail("baseline_seal_not_recorded", path.name)
    for composition_id in sorted(set(cited) - set(seals)):
        raise _fail("baseline_seal_cited_without_file", f"{event.name}:{composition_id}")


def git_history_state(repo: Path) -> str:
    """``full`` when ``repo`` is the top of a Git work tree with complete history, else ``shallow`` or ``absent``."""
    try:
        top = _git(repo, "rev-parse", "--show-toplevel").decode().strip()
    except CredibilityError:
        return "absent"
    if Path(top).resolve() != Path(repo).resolve():
        return "absent"
    if _git(repo, "rev-parse", "--is-shallow-repository").decode().strip() == "true":
        return "shallow"
    return "full"


def check_seal_history(repo: Path, root: Path) -> str:
    """Seal and Layer-A files are add-only and record citations never change (cold review P1-1).

    With full history: no commit may modify, delete, rename or retype a seal or Layer-A file, a tracked one may not
    be modified in the working tree, and every version of each event record in history must cite each composition
    with the same single hash it cites now (or not yet at all). Without history (no Git, a shallow clone) the check
    cannot run; it returns ``shallow`` or ``absent`` and the add-only property is a reviewer item (M1 §9)."""
    state = git_history_state(repo)
    if state != "full":
        return state
    paths = sorted({*root.glob(f"*/msr-*{SEAL_INFIX}*.json"), *root.glob(f"*/msr-*{LAYER_A_INFIX}*.json")})
    for path in paths:
        relative = path.relative_to(repo).as_posix()
        log = _git(repo, "log", "--format=", "--name-status", "--no-renames", "--", relative).decode().split()
        if any(token in ("M", "D", "T") for token in log[0::2]):
            raise _fail("baseline_artefact_rewritten_in_history", relative)
        status = _git(repo, "status", "--porcelain", "--", relative).decode()
        if status and not status.startswith("??") and not status.startswith("A "):
            raise _fail("baseline_artefact_rewritten_in_history", relative)
    for record in sorted({path.parent / (path.name.split(SEAL_INFIX)[0] + ".md")
                          for path in paths if SEAL_INFIX in path.name}):
        if not record.is_file():
            continue
        relative = record.relative_to(repo).as_posix()
        now = record_seal_citations(record.read_text(encoding="utf-8"))
        for commit in _git(repo, "log", "--format=%H", "--", relative).decode().split():
            try:
                text = _git(repo, "show", f"{commit}:{relative}").decode("utf-8")
            except CredibilityError:
                continue  # the record did not exist at that commit
            for composition_id, hashes in record_seal_citations(text).items():
                if now.get(composition_id) != hashes:
                    raise _fail("baseline_seal_citation_changed", f"{relative}:{composition_id}")
    return state


def check_decision_seal_commits(repo: Path, decision: Mapping, frozen: Mapping) -> str:
    """Cold review P3-5: where Git history is available, each decision ``baselineSeals[].sealCommit`` must hold
    exactly the cited seal bytes. Without history the commit is format-checked only (reviewer item)."""
    state = git_history_state(repo)
    if state != "full":
        return state
    for row in decision["benchmarkOnlyBaselines"]["baselineSeals"]:
        path = seal_path(Path(repo), frozen, row["compositionId"])
        try:
            committed = _committed_bytes_sha(Path(repo), row["sealCommit"], path)
        except CredibilityError:
            committed = None  # no such commit, or the seal is not in it
        if committed != row["sealSha256"]:
            raise _fail("decision_baseline_seal_commit_mismatch", row["compositionId"])
    return state


def _superseded_stop(path: Path, frozen_by_event: Mapping[Path, Mapping]) -> bool:
    """A STOPPED seal of a composition that a later protocol revision replaced (with a new composition id) is kept as
    immutable history: it permits nothing, so it is accepted when it is canonical, STOPPED and belongs to this event.
    Its record citation is checked like every other (``check_record_citations``). A RESOLVED seal is never accepted
    without its frozen composition, and a superseded composition id is never reused."""
    event_id = path.name.split(SEAL_INFIX)[0]
    event = path.parent / event_id
    if event not in frozen_by_event:
        return False
    seal = read_canonical(path, "baseline_seal_not_canonical")
    named = f"{event_id}{SEAL_INFIX}{seal.get('compositionId')}.json"
    if seal.get("status") != STOPPED or seal.get("eventId") != event_id or path.name != named:
        return False
    _keys(seal, STOPPED_FIELDS, path.name)
    return seal["compositionId"] not in frozen_compositions(frozen_by_event[event])


# ------------------------------------------------------------------ harness API


@dataclass(frozen=True)
class SealBinding:
    """What a protected D manifest/result records for one gate-only composition."""
    composition_id: str
    seal_sha256: str
    seal_commit: str
    partner_candidate_id: str
    partner_identity_sha256: str
    composition_sha256: str


def _git(repo: Path, *args: str) -> bytes:
    completed = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if completed.returncode != 0:
        raise _fail("baseline_seal_git_unavailable", " ".join(args[:2]))
    return completed.stdout


def _committed_bytes_sha(repo: Path, commit: str, path: Path) -> str:
    import hashlib
    blob = _git(repo, "show", f"{commit}:{path.relative_to(repo).as_posix()}")
    return hashlib.sha256(blob.replace(b"\r\n", b"\n")).hexdigest()


def require_committed_baseline_seal(repo: Path, event_id: str, capability_id: str, composition_id: str) -> SealBinding:
    """Call before reading any protected D data. Refuses unless the exact seal file is committed, unmodified in the
    working tree, cited by the event record, RESOLVED and re-derivable from the frozen inputs."""
    repo = Path(repo)
    folder = event_folder(repo, capability_id)
    frozen_file = folder / f"{event_id}{FROZEN_SUFFIX}"
    if not frozen_file.is_file():
        raise _fail("frozen_ledger_missing", frozen_file.name)
    frozen = read_json(frozen_file)
    validate_ledger(frozen)
    if composition_id not in frozen_compositions(frozen):
        raise _fail("gate_only_composition_not_frozen", composition_id)
    path = seal_path(repo, frozen, composition_id)
    if not path.is_file():
        raise _fail("baseline_seal_missing", path.name)
    relative = path.relative_to(repo).as_posix()
    _git(repo, "ls-files", "--error-unmatch", "--", relative)
    if _git(repo, "status", "--porcelain", "--", relative).strip():
        raise _fail("baseline_seal_not_committed", path.name)
    commit = _git(repo, "log", "-n", "1", "--format=%H", "--", relative).decode().strip()
    from .credibility import PROTOCOL_SUFFIX, lf_normalised_sha256
    protocol = folder / f"{event_id}{PROTOCOL_SUFFIX}"
    if not protocol.is_file():
        raise _fail("protocol_missing", protocol.name)
    evidence = load_baseline_evidence(repo, frozen)
    verified = verify_event_seals({composition_id: evidence[composition_id]}, frozen, lf_normalised_sha256(protocol))
    item = verified[composition_id]
    check_record_citations(folder / event_id)
    if item["status"] != RESOLVED:
        raise _fail("baseline_seal_stopped_no_d", f"{path.name}:{item['seal']['stopReason']}")
    if _committed_bytes_sha(repo, commit, path) != item["sha256"]:
        raise _fail("baseline_seal_not_committed", path.name)
    seal = item["seal"]
    return SealBinding(composition_id, item["sha256"], commit, seal["partnerCandidateId"],
                       seal["partnerIdentitySha256"], seal["compositionSha256"])


def verify_d_manifest_binding(manifest: Mapping, repo: Path, event_id: str, capability_id: str) -> None:
    """A protected D manifest or result must carry ``baselineSeals``: for every frozen gate-only composition of the
    event, ``{"compositionId", "sealSha256", "sealCommit"}`` equal to the committed seal now. A re-seal after D is
    therefore refused, and so is a manifest citing a commit that does not hold those seal bytes."""
    repo = Path(repo)
    frozen = read_json(event_folder(repo, capability_id) / f"{event_id}{FROZEN_SUFFIX}")
    rows = _list(manifest.get("baselineSeals"), "manifest.baselineSeals")
    cited = {}
    for index, row in enumerate(rows):
        _keys(row, ("compositionId", "sealSha256", "sealCommit"), f"manifest.baselineSeals[{index}]")
        cited[row["compositionId"]] = row
    if sorted(cited) != sorted(frozen_compositions(frozen)) or len(cited) != len(rows):
        raise _fail("d_manifest_baseline_seal_mismatch", "manifest.baselineSeals")
    for composition_id, row in cited.items():
        binding = require_committed_baseline_seal(repo, event_id, capability_id, composition_id)
        if row["sealSha256"] != binding.seal_sha256:
            raise _fail("d_manifest_baseline_seal_mismatch", composition_id)
        path = seal_path(repo, frozen, composition_id)
        if _committed_bytes_sha(repo, row["sealCommit"], path) != binding.seal_sha256:
            raise _fail("d_manifest_baseline_seal_mismatch", f"{composition_id}.sealCommit")


def layer_a_result_document(frozen: Mapping, composition_id: str, partner_ledger: Mapping,
                            results: Sequence[Mapping], evidence_sha256: str) -> dict:
    """Build the canonical Layer-A result a harness commits (results: candidateId, identitySha256, gates, rankKey,
    measurementSha256)."""
    rule = frozen_compositions(frozen)[composition_id][1]
    return {"schema": LAYER_A_SCHEMA, "eventId": frozen["eventId"], "compositionId": composition_id,
            "partnerEventId": rule["partnerEventId"], "partnerFrozenLedgerSha256": document_sha256(partner_ledger),
            "layerAGatesSha256": rule["layerAGatesSha256"], "layerAGateIds": list(rule["layerAGateIds"]),
            "partnerRankingRuleSha256": rule["partnerRankingRuleSha256"],
            "results": sorted((dict(r) for r in results), key=lambda r: r["candidateId"]),
            "evidenceSha256": evidence_sha256}


# ------------------------------------------------------------------ decision summary v1 (M3 block)


M3_DECISION_FIELD = "benchmarkOnlyBaselines"
M3_DECISION_KEYS = ("baselineSeals", "dExecutionStartedAt", "incumbent", "topK", "componentFinalists",
                    "compositionCandidates", "rankedCompositions", "frontier", "strongestEvaluatedComposition")
_COMPOSITION_KEYS = ("compositionId", "components", "gates", "technicalGates", "comparativeScore", "dResultSha256",
                     "baselineSealSha256s")


def _unique_members(value: object, where: str) -> list:
    members = _list(value, where)
    if not all(isinstance(m, str) for m in members) or len(set(members)) != len(members):
        raise _fail("ranked_set_not_unique", where)
    return members


def check_m3_decision(decision: Mapping, *, entries: Mapping[str, dict], frozen: Mapping, evaluated: Mapping[str, dict],
                      ranked: Mapping[str, dict], evidence: Mapping[str, Mapping]) -> None:
    """M3 rules 3-5 and 9 on a decision summary v1 whose frozen ledger holds a benchmark-only baseline.

    The block is mandatory, so exclusion from every ranked, derived and implementation role is always checked:
    seals (by hash and status), the one D start, the incumbent, top-K, component finalists, the ordinary composition
    candidates with their hard-gate mapping to the sealed baseline, ranked compositions, the frontier and the
    strongest evaluated composition. The outcome is NOT read here: it is the ordinary M1 outcome (rule 5)."""
    where = f"decision.{M3_DECISION_FIELD}"
    block = _keys(decision.get(M3_DECISION_FIELD), M3_DECISION_KEYS, where)
    declared = frozen_compositions(frozen)
    benchmark = {e["candidateId"] for e in frozen["candidates"] if e["disposition"]["status"] == BENCHMARK_BASELINE}
    gate_ids = set(declared)
    forbidden = benchmark | gate_ids
    verified = verify_event_seals(evidence, frozen, decision["protocolSha256"])

    cited: dict[str, dict] = {}
    for index, row in enumerate(_list(block["baselineSeals"], f"{where}.baselineSeals")):
        at = f"{where}.baselineSeals[{index}]"
        _keys(row, ("compositionId", "sealSha256", "status", "sealCommit"), at)
        _match(row["sealCommit"], IMMUTABLE_REVISION_RE, f"{at}.sealCommit")  # verified against Git in repository mode
        if row["compositionId"] in cited:
            raise _fail("gate_only_composition_resolved_twice", at)
        if row["compositionId"] not in gate_ids:
            raise _fail("gate_only_composition_not_frozen", at)
        cited[row["compositionId"]] = row
    for composition_id in sorted(gate_ids):
        if composition_id not in cited or composition_id not in verified:
            raise _fail("gate_only_composition_unresolved", f"{where}.baselineSeals.{composition_id}")
        if (cited[composition_id]["sealSha256"], cited[composition_id]["status"]) != \
                (verified[composition_id]["sha256"], verified[composition_id]["status"]):
            raise _fail("decision_baseline_seal_mismatch", f"{where}.baselineSeals.{composition_id}")
    seals = {c: verified[c]["sha256"] for c in sorted(gate_ids)}
    stopped = any(verified[c]["status"] == STOPPED for c in gate_ids)

    for candidate_id in sorted(benchmark):
        expected = {c: seals[c] for c, (entry, _rule) in declared.items() if entry["candidateId"] == candidate_id}
        if evaluated[candidate_id].get("baselineSealSha256s") != expected:
            raise _fail("benchmark_baseline_row_seal_mismatch", f"decision.evaluated.{candidate_id}")

    started = block["dExecutionStartedAt"]
    accessed = sorted(verified[c]["seal"]["protectedDAccessedAt"] for c in gate_ids
                      if verified[c]["status"] == STOPPED and verified[c]["seal"]["protectedDState"] == D_ACCESSED)
    if accessed:
        # Cold review P3-2: protected D was accessed before resolution; the decision records that access, never "no D".
        if started != accessed[0]:
            raise _fail("baseline_d_access_not_recorded", f"{where}.dExecutionStartedAt")
    elif stopped:
        if started is not None:
            raise _fail("baseline_stopped_d_started", f"{where}.dExecutionStartedAt")
    elif gate_ids:
        start = _instant(started, f"{where}.dExecutionStartedAt")
        for composition_id in sorted(gate_ids):
            if not _instant(verified[composition_id]["seal"]["recordedAt"], "seal.recordedAt") < start:
                raise _fail("baseline_resolved_after_d_started", f"{where}.dExecutionStartedAt")
        if start.date() > date.fromisoformat(decision["decidedOn"]):
            raise _fail("d_started_after_decision", f"{where}.dExecutionStartedAt")
    elif started is not None:
        _instant(started, f"{where}.dExecutionStartedAt")

    incumbent = block["incumbent"]
    if incumbent is not None:
        _text(incumbent, f"{where}.incumbent")
        if incumbent in forbidden:
            raise _fail("benchmark_baseline_in_derived_output", f"{where}.incumbent")
        if incumbent not in ranked:
            raise _fail("incumbent_not_evaluated", f"{where}.incumbent")
    for field in ("topK", "componentFinalists"):
        for member in _unique_members(block[field], f"{where}.{field}"):
            if member in forbidden:
                raise _fail("benchmark_baseline_in_ranked_set", f"{where}.{field}")
            if member not in ranked:
                raise _fail("ranked_set_member_not_evaluated", f"{where}.{field}")

    partner_ledgers = {rule["partnerEventId"]: (evidence.get(c) or {}).get("partnerLedger")
                       for c, (_entry, rule) in declared.items()}
    forbidden_identities = {candidate_identity_sha256(entries[b]) for b in benchmark}
    forbidden_files = set().union(*(benchmark_file_hashes(entries[b]) for b in benchmark))
    passing: dict[str, float] = {}
    composition_ids: set[str] = set()
    for index, composition in enumerate(_list(block["compositionCandidates"], f"{where}.compositionCandidates")):
        at = f"{where}.compositionCandidates[{index}]"
        _keys(composition, _COMPOSITION_KEYS, at)
        composition_id = _match(composition["compositionId"], LOCAL_ID_RE, f"{at}.compositionId")
        if composition_id in forbidden:
            raise _fail("benchmark_baseline_in_composition_candidate", f"{at}.compositionId")
        if composition_id in composition_ids or composition_id in entries:
            raise _fail("composition_id_collides", f"{at}.compositionId")
        composition_ids.add(composition_id)
        if stopped:
            raise _fail("baseline_stopped_no_d_result", at)
        components = _list(composition["components"], f"{at}.components")
        keys = []
        for cindex, component in enumerate(components):
            cat = f"{at}.components[{cindex}]"
            _keys(component, ("eventId", "candidateId", "identitySha256"), cat)
            event_id = _match(component["eventId"], EVENT_ID_RE, f"{cat}.eventId")
            candidate_id = _match(component["candidateId"], CANDIDATE_ID_RE, f"{cat}.candidateId")
            _match(component["identitySha256"], SHA256_RE, f"{cat}.identitySha256")
            keys.append((event_id, candidate_id))
            if component["identitySha256"] in forbidden_identities or \
                    (event_id == frozen["eventId"] and candidate_id in benchmark):
                raise _fail("benchmark_baseline_in_composition_candidate", cat)
            if event_id == frozen["eventId"]:
                if candidate_id not in ranked:
                    raise _fail("composition_component_not_evaluated", cat)
                own = entries[candidate_id]
            elif event_id in partner_ledgers:
                ledger = partner_ledgers[event_id]
                if ledger is None:
                    raise _fail("baseline_partner_event_missing", cat)
                own = {e["candidateId"]: e for e in ledger["candidates"]}.get(candidate_id)
                if own is None or own["disposition"]["status"] != SHORTLISTED:
                    raise _fail("composition_component_not_in_partner_shortlist", cat)
            else:
                raise _fail("composition_component_event_not_declared", cat)
            if component["identitySha256"] != candidate_identity_sha256(own):
                raise _fail("composition_component_identity_mismatch", cat)
            if candidate_file_hashes(own) & forbidden_files:
                # cold review P3-3: the benchmark-only bytes re-listed under another identity
                raise _fail("benchmark_baseline_in_composition_candidate", cat)
        if len(keys) < 2 or keys != sorted(set(keys)):
            raise _fail("composition_components_invalid", f"{at}.components")
        gates = composition["gates"]
        if not isinstance(gates, dict) or set(gates) != gate_ids:
            raise _fail("composition_hard_gate_mapping_invalid", f"{at}.gates")
        for gate, result in gates.items():
            _enum(result, (PASSED, FAILED), f"{at}.gates.{gate}")
        if composition["baselineSealSha256s"] != seals:
            raise _fail("d_result_baseline_seal_mismatch", f"{at}.baselineSealSha256s")
        _match(composition["dResultSha256"], SHA256_RE, f"{at}.dResultSha256")
        technical = _enum(composition["technicalGates"], (PASSED, FAILED), f"{at}.technicalGates")
        if technical == PASSED:
            if any(result != PASSED for result in gates.values()):
                raise _fail("composition_failed_hard_gate_ranked", f"{at}.technicalGates")
            score = composition["comparativeScore"]
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
                raise _fail("number_required", f"{at}.comparativeScore")
            passing[composition_id] = float(score)
        elif composition["comparativeScore"] is not None:
            raise _fail("failed_gate_has_score", f"{at}.comparativeScore")

    order = _unique_members(block["rankedCompositions"], f"{where}.rankedCompositions")
    if any(member in forbidden for member in order):
        raise _fail("benchmark_baseline_in_ranked_set", f"{where}.rankedCompositions")
    if set(order) != set(passing) or any(passing[a] < passing[b] for a, b in zip(order, order[1:])):
        raise _fail("ranked_compositions_not_derived", f"{where}.rankedCompositions")
    strongest = block["strongestEvaluatedComposition"]
    if strongest is not None:
        _text(strongest, f"{where}.strongestEvaluatedComposition")
    if strongest in forbidden:
        raise _fail("benchmark_baseline_in_derived_output", f"{where}.strongestEvaluatedComposition")
    best = max(passing.values()) if passing else None
    if (strongest is None) != (best is None) or (strongest is not None and passing.get(strongest) != best):
        raise _fail("strongest_composition_not_derived", f"{where}.strongestEvaluatedComposition")
    passing_candidates = {c for c, row in ranked.items() if row["technicalGates"] == PASSED}
    for member in _unique_members(block["frontier"], f"{where}.frontier"):
        if member in forbidden:
            raise _fail("benchmark_baseline_in_ranked_set", f"{where}.frontier")
        if member not in passing and member not in passing_candidates:
            raise _fail("frontier_member_not_passing", f"{where}.frontier")
