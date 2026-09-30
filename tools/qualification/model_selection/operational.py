"""S2c.2b-2 pure decisions. b-1 outcomes are inputs, never fitted here."""
from __future__ import annotations

import itertools
from pathlib import Path

from . import quality_statistics as b1
from .canonical import canonical, digest, integer, keys, require, text, tokens, read

CONTRACT = Path("docs/qualification/model-selection/s2c-operational-selection-contract.json")
PROTOCOL = Path("docs/qualification/model-selection/s2c-operational-selection.md")
PROJECTION_BEGIN = "<!-- BEGIN S2C_B2_CONTRACT_PROJECTION -->"
PROJECTION_END = "<!-- END S2C_B2_CONTRACT_PROJECTION -->"
PROTECTED = {"superior", "non-inferior", "equivalent"}


def contract() -> dict:
    """Code-pinned method, with event-specific owner numbers intentionally absent."""
    dispositions = {s: "defined" for s in b1.EXPECTED_DEFERRED}
    for s in ("pareto-axes", "pareto-directions", "pareto-normalization", "dominance-semantics",
              "non-dominated-set-construction", "sub-task-finalist-ordering"):
        dispositions[s] = "retired-as-selection-authority"
    dispositions["disabled-attribute-frontier-treatment"] = "required-scope-gate"
    statements = {
        "b1": "b-1 retains populations, calibration, partitions, gates, support, margins and paired outcomes.",
        "freeze": "Complete executable units, claims, family, fallback, workload, host, limits and objective precede selection.",
        "quality": "MPID precedes E; F protects directly against every other member of original E; no peeling or transitivity.",
        "joint": "J is F or the valid frozen fallback; technical selection uses exact person x vehicle pairs.",
        "uncertainty": "Hstar is min H_up over admitted pairs; T contains every pair with H_lo <= Hstar.",
        "implementation": "Credibility and licence enter K only; C_impl is K_person x K_vehicle; recompute T_impl.",
        "retention": "Canonical immutable quality results precede retained linear joint versions, which precede decision-v2.",
        "scope": "500-camera capacity is a validated projection on declared loads/hardware, never blanket qualification.",
        "e3": "Candidate-specific E3 contradiction reopens incomplete evidence; no selection rescue.",
    }
    return {
        "schema": "mavi-s2c-operational-selection-v1", "method": "s2c-2b2",
        "prerequisite": {"schema": b1.SCHEMA, "method": b1.METHOD,
                         "deferredDispositions": dispositions, "redefinesB1": False},
        "experimentFreeze": {"completeManifest": True, "labelFreePreScreen": True,
                             "selectionMutation": False, "frozenTestSelection": False},
        "wholeJob": {"fifo": ["queuedAtUtc", "id"], "attemptConsumedAt": "claim",
                     "retryRetainsQueue": True, "deadlineFrom": "firstClaimedAtUtc",
                     "claimAtDeadline": False, "leaseDeadlineCap": True,
                     "phaseCFence": "ownership", "publicationProtection": "phaseA-plus-lease-capped-at-deadline-plus-lease",
                     "boundedPublicationIsOperationalGate": True, "checkpointReuse": False,
                     "completedAtUtc": "phase-C-transaction-sample", "acknowledgementIsCommit": False},
        "hostProfile": {"defaultHostClasses": 1, "topologySearch": "frozen-label-free"},
        "workloadFamily": {"requiredShapes": ["typical", "small-burst", "10k-boundary", "mixed", "recovery", "500-camera"]},
        "compositionAccounting": {"exactExecutableUnits": True, "standaloneRankPruning": False, "PO-B0Selectable": False},
        "qualityDecisionClaims": {"nonempty": True, "directions": ["higher", "lower"],
                                  "family": "all-ordered-manifest-pairs-times-Q", "protection": "direct-all-original-E"},
        "mpidExtensionRule": {"beforeQualityProtection": True, "defaultUnavailable": "exclude-pending-ADR",
                              "requiredOutcome": "superior", "allRequiredComparators": True},
        "scaleProjection": {"cameraTarget": 500, "fluidIsDeadlineProof": False,
                            "replay": "bounded-whole-job", "E2": "real-S2b-runner-inference-seam",
                            "E3": "held-out-integrated-engineering", "qualificationClaim": False},
        "jointOperationalSelection": {"population": "J_person-times-J_vehicle", "identity": "exact-pair",
                                      "bounds": "same-replay-lower-upper-frozen-demand", "technicalSet": "H_lo<=min-H_up"},
        "finalSelection": {"qualityFallbackChangesF": False, "credibilityChangesT": False,
                           "credibilityChangesTr": False, "implementationPopulation": "K_person-times-K_vehicle",
                           "implementationOptimum": "recomputed-before-owner-choice", "setValued": True},
        "msrRepresentation": {"revision": "msr-v1-m2", "S2cDecision": "mavi-model-selection-decision-v2",
                              "nonS2cDecision": "mavi-model-selection-decision-v1", "earlyImplementation": False},
        "historicalOrdering": {"weightedWinner": False, "paretoWinner": False, "rankSumComposition": False},
        "ownerInputs": {"numericalTargets": "event-frozen", "freezeBeforeRead": "reviewed-attestation-until-S2c3"},
        "frozenInvariants": {k: True for k in statements}, "invariantStatements": statements,
    }


def validate_contract(document: dict) -> None:
    # Comparing canonical bytes, rather than dict equality, avoids bool/int equality.
    require(canonical(document) == canonical(contract()), "operational_contract:authority_or_fields")


def render_contract_projection(document: dict) -> str:
    validate_contract(document)
    lines = [PROJECTION_BEGIN, "_Generated from `s2c-operational-selection-contract.json`._", ""]
    for section in sorted(document):
        value = document[section]
        lines += [f"### {section}", "", "```json", canonical(value).decode().rstrip(), "```", ""]
    return "\n".join(lines + [PROJECTION_END])


def validate_repository(repo: Path) -> list[str]:
    b1.validate_repository(repo)
    document = read(repo / CONTRACT)
    validate_contract(document)
    blob = (repo / PROTOCOL).read_bytes()
    begin, end = PROJECTION_BEGIN.encode(), PROJECTION_END.encode()
    require(blob.count(begin) == blob.count(end) == 1, "operational_projection:structure")
    require(blob[blob.index(begin):blob.index(end)+len(end)] == render_contract_projection(document).encode(),
            "operational_projection:bytes")
    return [str(CONTRACT), str(PROTOCOL)]


def validate_unit(unit: dict) -> None:
    keys(unit, {"unitId", "kind", "components", "configurationSha256", "enabledAttributes", "extension", "existingGraph"}, "unit")
    text(unit["unitId"], "unitId")
    require(unit["unitId"] != "PO-B0", "unit:nonpackageable_reference")
    require(unit["kind"] in ("learned", "baseline", "disabled"), "unit:kind")
    tokens(unit["components"], "components", nonempty=unit["kind"] != "disabled")
    tokens(unit["enabledAttributes"], "enabledAttributes")
    require(unit["kind"] != "disabled" or (not unit["components"] and not unit["enabledAttributes"]), "disabled:scope")
    digest(unit["configurationSha256"], "configurationSha256")
    require(type(unit["extension"]) is bool and type(unit["existingGraph"]) is bool, "unit:bool")
    require(not (unit["extension"] and unit["existingGraph"]), "unit:graph")


def validate_capability(cap: dict) -> None:
    keys(cap, {"scope", "units", "fallback", "claims", "mpidClaims", "mpidComparatorUnavailable",
               "noComparatorAuthoritySha256", "simultaneousFamily", "gateIds"}, "capability")
    tokens(cap["scope"], "scope", nonempty=True)
    tokens(cap["gateIds"], "gateIds", nonempty=True)
    require({"absolute-quality", "engineering", "support"} <= set(cap["gateIds"]), "gates:incomplete_authority")
    require(type(cap["units"]) is list and bool(cap["units"]), "units:nonempty")
    ids = []
    for unit in cap["units"]:
        validate_unit(unit)
        require(unit["kind"] != "disabled", "manifest:disabled_only_fallback")
        ids.append(unit["unitId"])
    require(ids == sorted(set(ids)), "units:sorted_unique")
    if cap["fallback"] is not None:
        validate_unit(cap["fallback"])
        require(cap["fallback"]["kind"] in ("baseline", "disabled"), "fallback:kind")
        if cap["fallback"]["unitId"] in ids:
            require(cap["fallback"] == next(u for u in cap["units"] if u["unitId"] == cap["fallback"]["unitId"]), "fallback:identity")
    require(type(cap["claims"]) is list and bool(cap["claims"]), "Q:missing")
    claims = []
    for q in cap["claims"]:
        keys(q, {"claimId", "direction", "marginsSha256"}, "claim")
        claims.append(text(q["claimId"], "claimId"))
        require(q["direction"] in ("higher", "lower"), "claim:direction")
        digest(q["marginsSha256"], "claim:margins")
    require(claims == sorted(set(claims)), "Q:sorted_unique")
    tokens(cap["mpidClaims"], "mpidClaims", nonempty=True)
    require(set(cap["mpidClaims"]) <= set(claims), "mpid:claims")
    require(cap["mpidComparatorUnavailable"] in ("exclude-pending-ADR", "admit-under-governing-route"), "mpid:disposition")
    if cap["mpidComparatorUnavailable"] == "admit-under-governing-route":
        digest(cap["noComparatorAuthoritySha256"], "mpid:authority")
    else:
        require(cap["noComparatorAuthoritySha256"] is None, "mpid:authority")
    family = [{"a": a, "b": b, "claimId": q} for a, b in itertools.permutations(ids, 2) for q in claims]
    require(cap["simultaneousFamily"] == family, "simultaneous_family:incomplete_or_order")


def quality_sets(cap: dict, gate_results: dict, matrix: list[dict]) -> dict:
    validate_capability(cap)
    units = {u["unitId"]: u for u in cap["units"]}
    all_units = dict(units)
    if cap["fallback"] is not None:
        all_units[cap["fallback"]["unitId"]] = cap["fallback"]
    keys(gate_results, set(all_units), "gate_results")
    passes = {}
    quality_passes = {}
    for uid, row in gate_results.items():
        keys(row, {"preScreen", "preScreenPartition", "results", "evidenceClass"}, f"gates:{uid}")
        require(row["preScreenPartition"] == "label-free", "pre_screen:partition")
        require(row["preScreen"] in ("pass", "exclude"), "pre_screen:result")
        require(row["evidenceClass"] in ("M-D", "M-E"), "gates:measured_evidence_required")
        keys(row["results"], set(cap["gateIds"]), "gates")
        require(all(v in ("pass", "fail", "insufficient-evidence", "missing") for v in row["results"].values()), "gates:outcome")
        scope_pass = set(cap["scope"]) <= set(all_units[uid]["enabledAttributes"])
        quality_passes[uid] = scope_pass and all(v == "pass" for g, v in row["results"].items() if g != "engineering")
        passes[uid] = scope_pass and row["preScreen"] == "pass" and all(v == "pass" for v in row["results"].values())
        if all_units[uid]["kind"] == "disabled":
            passes[uid] = row["preScreen"] == "pass" and all(v == "pass" for v in row["results"].values())
    require(type(matrix) is list, "pairwise_family:list")
    require([{k: r.get(k) for k in ("a", "b", "claimId")} for r in matrix] == cap["simultaneousFamily"], "pairwise_family:incomplete_or_order")
    outcomes = {}
    for row in matrix:
        keys(row, {"a", "b", "claimId", "outcome"}, "comparison")
        require(row["outcome"] in b1.EXPECTED_OUTCOMES, "comparison:b1_outcome")
        outcomes[row["a"], row["b"], row["claimId"]] = row["outcome"]
    claims = [q["claimId"] for q in cap["claims"]]
    eligible = {uid for uid in units if passes[uid]}
    graph = {uid for uid in units if units[uid]["existingGraph"] and quality_passes[uid]}
    statuses = {}
    for uid in sorted(eligible):
        if not units[uid]["extension"]:
            statuses[uid] = "NOT_EXTENSION"
            continue
        comparators = sorted(graph & eligible or graph)
        if not comparators:
            statuses[uid] = "MPID_COMPARATOR_UNAVAILABLE"
            if cap["mpidComparatorUnavailable"] == "exclude-pending-ADR": eligible.remove(uid)
        elif all(outcomes[uid, b, q] == "superior" if q in cap["mpidClaims"] else outcomes[uid, b, q] in PROTECTED
                 for b in comparators for q in claims):
            statuses[uid] = "PASS"
        else:
            statuses[uid] = "FAIL"
            eligible.remove(uid)
    E = sorted(eligible)
    F = [a for a in E if all(outcomes[a, b, q] in PROTECTED for b in E if a != b for q in claims)]
    outcome = "QUALITY_PROTECTED_SET" if F else ("NO_QUALITY_PROTECTED_TECHNICAL_CHOICE" if E else "NO_TECHNICALLY_ELIGIBLE_CANDIDATE")
    causes = sorted({outcomes[a, b, q] for a in E for b in E if a != b for q in claims if outcomes[a, b, q] not in PROTECTED})
    fallback = cap["fallback"]
    J = F or ([fallback["unitId"]] if fallback is not None and passes[fallback["unitId"]] else [])
    return {"E": E, "F": F, "J": J, "mpidStatus": statuses, "qualityOutcome": outcome, "qualityOutcomeReason": causes,
            "fallbackOperationallyAvailable": fallback is not None and passes[fallback["unitId"]]}


def pair_key(pair: dict) -> tuple[str, str]:
    keys(pair, {"personUnitId", "vehicleUnitId"}, "pair")
    return text(pair["personUnitId"], "personUnitId"), text(pair["vehicleUnitId"], "vehicleUnitId")


def product(person: list[str], vehicle: list[str]) -> list[dict]:
    return [{"personUnitId": p, "vehicleUnitId": v} for p in person for v in vehicle]


def select_pairs(population: list[dict], measurements: list[dict], host: str, constraints: list[str]) -> dict:
    identities = [pair_key(p) for p in population]
    require(identities == sorted(set(identities)), "population:sorted_unique_pairs")
    rows = {}
    for row in measurements:
        keys(row, {"pair", "H_lo", "H_up", "hostClassId", "evidenceComplete", "constraints", "operationalEvidenceSha256"}, "joint_measurement")
        identity = pair_key(row["pair"])
        require(identity not in rows, "joint_measurement:duplicate_pair")
        require(row["hostClassId"] == host, "joint_measurement:host_class")
        require(type(row["evidenceComplete"]) is bool, "joint_measurement:evidence_bool")
        keys(row["constraints"], set(constraints), "joint_constraints")
        require(all(type(v) is bool for v in row["constraints"].values()), "joint_constraints:bool")
        digest(row["operationalEvidenceSha256"], "operational_evidence")
        if row["evidenceComplete"]:
            for bound in ("H_lo", "H_up"):
                if row[bound] is None:
                    require(row["constraints"].get("bounds") is False, "host_bounds:unbounded_without_failure")
                else:
                    integer(row[bound], bound, 1)
            if row["H_lo"] is not None and row["H_up"] is not None:
                require(row["H_lo"] <= row["H_up"], "host_bounds:order")
        else:
            require(row["H_lo"] is row["H_up"] is None, "incomplete:bounds")
        rows[identity] = row
    require(set(identities) <= set(rows), "joint_measurement:population_missing")
    admitted = [p for p in population if rows[pair_key(p)]["evidenceComplete"] and all(rows[pair_key(p)]["constraints"].values())]
    Hstar = min((rows[pair_key(p)]["H_up"] for p in admitted), default=None)
    T = [p for p in admitted if rows[pair_key(p)]["H_lo"] <= Hstar]
    unresolved = [p for p in population if not rows[pair_key(p)]["evidenceComplete"]]
    if not population: outcome = "NO_OPERATIONALLY_COMPLETE_IDENTITY"
    elif unresolved: outcome = "TECHNICAL_EVIDENCE_INCOMPLETE"
    elif not admitted: outcome = "NO_OPERATIONALLY_FEASIBLE_PAIR"
    else: outcome = "UNIQUE_TECHNICAL_WINNER" if len(T) == 1 else "TECHNICAL_TIED_SET"
    return {"admitted": admitted, "Hstar": Hstar, "T": T, "outcome": outcome, "unresolved": unresolved}


def fluid_screen(arrivals: list[int], capacity: list[int]) -> list[int]:
    require(len(arrivals) == len(capacity), "fluid:length")
    backlog, result = 0, []
    for a, c in zip(arrivals, capacity):
        backlog = max(0, backlog + integer(a, "arrival") - integer(c, "capacity"))
        result.append(backlog)
    return result


def e3_disposition(cause: str) -> str:
    require(cause in ("candidate-specific", "candidate-independent"), "E3:no_rescue")
    return "TECHNICAL_EVIDENCE_INCOMPLETE_REOPEN" if cause == "candidate-specific" else "NUMBERED_METHOD_REVISION_RECOMPUTE_ALL"


def implementation_sets(capabilities: dict, quality: dict, measurements: list[dict], licence: dict,
                        snapshots: dict, decided_on: dict, profiles: list[str], host: str,
                        constraints: list[str]) -> dict:
    """M1 eligibility at K only. T_r/C_all never read credibility."""
    from . import credibility as cred
    from datetime import date

    tokens(profiles, "profiles", nonempty=True)
    for document in (capabilities, quality, licence, snapshots, decided_on):
        keys(document, {"person", "vehicle"}, "capabilities")
    units, classes, K, pending = {}, {}, {}, False
    for c in ("person", "vehicle"):
        snapshot = snapshots[c]
        summary = cred.validate_ledger(snapshot)
        decision_date = cred._date(decided_on[c], f"decidedOn:{c}")
        cred._check_sealed_on(snapshot, decision_date, "snapshot_postdates_decision")
        entries = {e["candidateId"]: e for e in snapshot["candidates"]}
        units[c] = {u["unitId"]: u for u in capabilities[c]["units"]}
        fallback = capabilities[c]["fallback"]
        if fallback is not None: units[c][fallback["unitId"]] = fallback
        keys(licence[c], set(units[c]), f"licence:{c}")
        for uid in units[c]:
            keys(licence[c][uid], set(profiles), f"licence:{c}:{uid}")
            require(all(s in cred.LICENCE_STATUSES for s in licence[c][uid].values()), "licence:status")
            pending |= any(s in ("NOT_ASSESSED", "REVIEW_PENDING") for s in licence[c][uid].values())
        classes[c] = {}

        def implementable(uid):
            unit = units[c][uid]
            component_classes = {}
            eligible = True
            for component in unit["components"]:
                require(component in entries, f"component:not_in_snapshot:{component}")
                entry = entries[component]
                history = [h for h in entry["classificationHistory"] if date.fromisoformat(h["at"]) <= decision_date]
                require(bool(history), "component:history_missing_on_decision")
                klass = summary[component]["class"]
                component_classes[component] = klass
                if klass not in cred.IMPLEMENTABLE_CLASSES or history[-1]["to"] not in cred.IMPLEMENTABLE_CLASSES:
                    eligible = False
                else:
                    require(history[-1]["inputsSha256"] == cred.classification_inputs_sha256(entry), "component:unverifiable_promotion")
                if unit["kind"] == "baseline":
                    require(entry["candidateKind"] == cred.BASELINE, "baseline:not_mavi_owned")
            classes[c][uid] = component_classes
            return eligible

        def admissible(uid):
            return implementable(uid) and all(licence[c][uid][r] == "CLEARED" for r in profiles)

        tokens(quality[c]["J"], f"J:{c}")
        require(set(quality[c]["J"]) <= set(units[c]), "J:identity")
        K[c] = [uid for uid in quality[c]["J"] if admissible(uid)]
        require(type(quality[c]["fallbackOperationallyAvailable"]) is bool, "fallback:availability_bool")
        if not K[c] and fallback is not None and quality[c]["fallbackOperationallyAvailable"] and admissible(fallback["unitId"]):
            K[c] = [fallback["unitId"]]
        # Retain class of all units, even a licence-rejected/emerging technical winner.
        for uid in units[c]: implementable(uid)
    population = product(quality["person"]["J"], quality["vehicle"]["J"])
    C_r, T_r, unresolved_profiles = {}, {}, {}
    for profile in profiles:
        C_r[profile] = [p for p in population if licence["person"][p["personUnitId"]][profile] == "CLEARED"
                        and licence["vehicle"][p["vehicleUnitId"]][profile] == "CLEARED"]
        selection = select_pairs(C_r[profile], measurements, host, constraints)
        T_r[profile] = selection["T"]
        unresolved_profiles[profile] = selection["unresolved"]
    C_all = [p for p in population if all(p in C_r[r] for r in profiles)]
    C_impl = product(K["person"], K["vehicle"])
    selection = select_pairs(C_impl, measurements, host, constraints)
    T_impl = selection["T"]
    return {"C_r": C_r, "T_r": T_r, "C_all": C_all, "K_person": K["person"], "K_vehicle": K["vehicle"],
            "C_impl": C_impl, "T_impl": T_impl, "componentClasses": classes, "pending": pending,
            "unresolvedOperationalPairs": selection["unresolved"], "unresolvedProfilePairs": unresolved_profiles}
