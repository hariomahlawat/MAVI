"""Strict, acyclic S2c machine evidence and repository-addressed retention.

Evidence files are content addressed. Joint versions are version addressed and
create-only; an index is re-derived from the complete retained directory. No Git
history is required to resolve any predecessor or cited version. Coordinated
rewrites of all roots still require review: hashes do not authenticate their author.
"""
from __future__ import annotations

import copy
import hashlib
import itertools
import os
import re
from datetime import date
from pathlib import Path

from . import credibility as cred
from . import operational as op
from . import operational_inputs as inputs
from . import quality_statistics as b1
from .canonical import OperationalError, canonical, digest, integer, keys, parse, read, require, sha256, text, tokens
from .job_replay import POLICY_KEYS, instant, replay, utc

ROOT = Path("docs/qualification/model-selection")
EXPERIMENT_SCHEMA = "mavi-s2c-experiment-v1"
QUALITY_EVIDENCE_SCHEMA = "mavi-s2c-quality-evidence-v1"
QUALITY_SCHEMA = "mavi-s2c-quality-result-v1"
OPERATIONAL_EVIDENCE_SCHEMA = "mavi-s2c-operational-evidence-v1"
JOINT_SCHEMA = "mavi-s2c-joint-operational-decision-v1"
INDEX_SCHEMA = "mavi-s2c-joint-index-v1"
DECISION_SCHEMA = "mavi-model-selection-decision-v2"
CAPS = {"person", "vehicle"}
EXPERIMENT_KEYS = {"schema", "eventPairId", "events", "ledgerHashes", "qualityContractHash", "operationalContractHash",
                   "frozenOn", "sealedViewOn", "freezeAttestation", "capabilities", "profiles", "hostClassId",
                   "hostProfileSha256", "objective", "workersPerHost", "reserveHosts", "maximumHosts", "wholeJob",
                   "workloads", "workloadEnvelope", "requiredWorkloadIds", "uncertainty", "limits", "componentArtefacts"}
QUALITY_KEYS = {"schema", "eventId", "capability", "frozenLedgerSha256", "protocolSha256", "qualityContractHash",
                "operationalContractHash", "experimentSha256", "qualityEvidenceSha256", "decisionClaimsSha256",
                "pairwiseMatrixSha256", "gateResultsSha256", "outputs"}
JOINT_KEYS = {"schema", "eventPairId", "version", "stage", "supersedes", "events", "ledgerHashes",
              "qualityResultHashes", "qualityContractHash", "operationalContractHash", "experimentSha256",
              "technicalStage", "implementationStage", "revision"}
DECISION_KEYS = {"decisionVersion", "supersedesEventDecisionSha256", "schema", "methodRevision", "eventId", "capability", "eventState", "outcome", "decidedOn",
                 "experimentSha256", "qualityResultSha256", "jointOperationalDecisionSha256", "ledgerSha256",
                 "frozenLedgerSha256", "protocolSha256", "qualityContractHash", "operationalContractHash",
                 "decisionEvidenceHash", "evaluated", "technicalEligibleSet", "qualityAcceptableSet",
                 "pairwiseMatrixSha256", "decisionClaimsSha256", "mpidStatus", "highestTaskQualityEvaluatedSet",
                 "qualityOutcomeReason", "technicalSelectionOutcome", "technicalSelectedSet", "technicalWinner",
                 "profileClearedSet", "implementationEligibleSet", "implementationPair", "ownerChoice"}
CONSTRAINTS = ["api", "cold", "footprint", "bounds", "io", "memory", "publication", "queue", "recovery", "runtime", "warm"]
PAIR_ID = re.compile(r"^msr-[a-z0-9]+(?:-[a-z0-9]+)*-\d{4}-\d{2}$")


def _create(path: Path, blob: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(blob)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise OperationalError(f"retained_file_exists:{path.name}") from exc


def retain_evidence(repo: Path, document: dict) -> str:
    if document.get("schema") == QUALITY_SCHEMA:
        validate_quality(repo, document)
    identity = sha256(document)
    path = repo/ROOT/"s2c-evidence"/(identity+".json")
    if path.exists():
        require(path.read_bytes() == canonical(document), "retained_evidence_rewritten")
    else:
        _create(path, canonical(document))
    if document.get("schema") == QUALITY_SCHEMA:
        directory = repo/ROOT/(document["capability"]+"-attributes")
        base = document["eventId"]+"-quality-result"
        original = directory/(base+".json")
        versions = [original]+sorted(directory.glob(base+"-v*.json"))
        if not any(p.is_file() and p.read_bytes() == canonical(document) for p in versions):
            target = original if not original.exists() else directory/(base+f"-v{len(versions)+1}.json")
            _create(target, canonical(document))
    return identity


def resolve(repo: Path, identity: str) -> dict:
    digest(identity, "evidence_reference")
    doc = read(repo/ROOT/"s2c-evidence"/(identity+".json"))
    require(sha256(doc) == identity, "evidence:hash_mismatch")
    return doc


def validate_experiment(repo: Path, document: dict) -> None:
    keys(document, EXPERIMENT_KEYS, "experiment")
    require(document["schema"] == EXPERIMENT_SCHEMA, "experiment:schema")
    require(type(document["eventPairId"]) is str and PAIR_ID.fullmatch(document["eventPairId"]) is not None, "eventPairId:format")
    require(document["qualityContractHash"] == sha256(b1.read_contract(repo/b1.CONTRACT)), "experiment:b1_hash")
    op.validate_contract(read(repo/op.CONTRACT))
    require(document["operationalContractHash"] == sha256(read(repo/op.CONTRACT)), "experiment:b2_hash")
    frozen_on = cred._date(document["frozenOn"], "frozenOn")
    require(frozen_on >= cred._date(document["sealedViewOn"], "sealedViewOn"), "experiment:seal_after_freeze")
    attestation = keys(document["freezeAttestation"], {"recordedBy", "reviewedBy", "beforeSelectionRead"}, "freezeAttestation")
    require(text(attestation["recordedBy"], "recordedBy").casefold() != text(attestation["reviewedBy"], "reviewedBy").casefold(), "freeze:independent_reviewer")
    require(attestation["beforeSelectionRead"] is True, "freeze:selection_access")
    for name in ("events", "ledgerHashes", "capabilities", "componentArtefacts"):
        keys(document[name], CAPS, name)
    for c in sorted(CAPS):
        frozen = resolve(repo, document["ledgerHashes"][c])
        cred.validate_ledger(frozen)
        require(frozen["methodRevision"] == "msr-v1-m2", "experiment:requires_M2")
        require(frozen["eventId"] == document["events"][c] and frozen["capabilityId"] == c+"-attributes", "experiment:event_scope")
        require("frozenOn" in frozen and date.fromisoformat(frozen["frozenOn"]) <= frozen_on, "experiment:ledger_freeze")
        cred._check_sealed_on(frozen, date.fromisoformat(frozen["frozenOn"]), "ledger:seal")
        cap = document["capabilities"][c]
        op.validate_capability(cap)
        entries = {e["candidateId"]: e for e in frozen["candidates"]}
        components = {x for u in cap["units"]+([cap["fallback"]] if cap["fallback"] else []) for x in u["components"]}
        require(components <= cred._shortlist(frozen), "experiment:components_not_frozen_shortlist")
        # Every shortlisted selectable component is accounted for; non-packageable
        # references must have REFERENCE_ONLY disposition rather than a selectable unit.
        require(components == cred._shortlist(frozen), "experiment:shortlist_component_omitted")
        keys(document["componentArtefacts"][c], components, "componentArtefacts")
        for cid, row in document["componentArtefacts"][c].items():
            keys(row, {"candidateId", "artefactSha256s", "maviTrainedArtefacts", "maviRevision"}, "componentArtefact")
            require(row["candidateId"] == cid, "componentArtefact:identity")
            cred._check_evaluated_artefact(entries[cid], row, "componentArtefact")
    tokens(document["profiles"], "profiles", nonempty=True)
    text(document["hostClassId"], "hostClassId")
    digest(document["hostProfileSha256"], "hostProfileSha256")
    require(document["objective"] == "minimum-supported-installed-hosts", "experiment:objective")
    integer(document["workersPerHost"], "workersPerHost", 1)
    integer(document["reserveHosts"], "reserveHosts")
    integer(document["maximumHosts"], "maximumHosts", 1)
    require(document["reserveHosts"] < document["maximumHosts"], "hosts:reserve")
    keys(document["wholeJob"], POLICY_KEYS, "wholeJob")
    for k, value in document["wholeJob"].items(): integer(value, k, 1)
    keys(document["uncertainty"], {"lowerErrorPpm", "upperErrorPpm"}, "uncertainty")
    for k, value in document["uncertainty"].items(): integer(value, k)
    require(document["uncertainty"]["lowerErrorPpm"] < 1_000_000, "uncertainty:lower")
    keys(document["limits"], {"maxWarmUs", "maxQueueToPublicationUs", "maxBacklog", "maxRamBytesPerHost", "maxIoBytesPerSecond", "maxBootToReadyUs"}, "limits")
    for k, value in document["limits"].items(): integer(value, k, 1)
    inputs.host_profile(resolve(repo, document["hostProfileSha256"]), document)
    require(document["maximumHosts"] <= 1000 and document["workersPerHost"] <= 1000, "hosts:bounded_search")
    tokens(document["requiredWorkloadIds"], "requiredWorkloadIds", nonempty=True)
    require(type(document["workloads"]) is list, "workloads:list")
    workload_ids = []
    for w in document["workloads"]:
        keys(w, {"workloadId", "role", "cameraCount", "jobs", "outages", "startAtUtc", "endAtUtc"}, "workload")
        workload_ids.append(text(w["workloadId"], "workloadId"))
        require(instant(w["startAtUtc"], "startAtUtc") < instant(w["endAtUtc"], "endAtUtc"), "workload:horizon")
        require(type(w["jobs"]) is list and bool(w["jobs"]), "workload:jobs")
        require(w["role"] in op.contract()["workloadFamily"]["requiredShapes"], "workload:role")
        require((type(w["cameraCount"]) is int and w["cameraCount"] == 500) if w["role"] == "500-camera"
                else w["cameraCount"] is None, "workload:camera_target")
        sizes = [j["personTracks"]+j["vehicleTracks"] for j in w["jobs"]]
        if w["role"] == "10k-boundary": require(10_000 in sizes, "workload:10k_boundary")
        if w["role"] == "mixed": require(len(set(sizes)) > 1, "workload:mixed_sizes")
        if w["role"] == "small-burst": require(len(sizes) > 1 and max(sizes) < 10_000, "workload:small_burst")
        if w["role"] == "recovery": require(bool(w["outages"]), "workload:recovery_loss")
    require(workload_ids == document["requiredWorkloadIds"], "workloads:incomplete_or_order")
    require({w["role"] for w in document["workloads"]} == set(op.contract()["workloadFamily"]["requiredShapes"]),
            "workload:incomplete_family")
    inputs.workload_envelope(document["workloadEnvelope"], document["workloads"])


def runtime_identity(experiment: dict, pair: dict) -> str:
    """Frozen executable identities, never an ambiguous scalar candidate id."""
    op.pair_key(pair)
    units = {}
    for c in sorted(CAPS):
        cap = experiment["capabilities"][c]
        manifest = cap["units"]+([cap["fallback"]] if cap["fallback"] else [])
        found = [u for u in manifest if u["unitId"] == pair[c+"UnitId"]]
        require(bool(found), "runtime_identity:unit_not_frozen")
        units[c] = found[0]
    return sha256({"pair": pair, "units": units, "componentArtefacts": experiment["componentArtefacts"],
                   "hostProfileSha256": experiment["hostProfileSha256"], "workersPerHost": experiment["workersPerHost"]})


def _protocol_bytes(experiment: dict, c: str, exp_hash: str, blob: bytes) -> None:
    require(type(blob) is bytes and not blob.startswith(b"\xef\xbb\xbf") and b"\r" not in blob
            and blob.endswith(b"\n") and not blob.endswith(b"\n\n"), "protocol:canonical_LF")
    try: contents = blob.decode("utf-8", errors="strict")
    except UnicodeError as exc: raise OperationalError("protocol:UTF8") from exc
    for value in (exp_hash, experiment["ledgerHashes"][c], experiment["qualityContractHash"], experiment["operationalContractHash"], experiment["frozenOn"]):
        require(value in contents, "protocol:frozen_input_not_cited")


def retain_protocol(repo: Path, experiment_hash: str, c: str, blob: bytes) -> str:
    require(c in CAPS, "protocol:capability")
    experiment = resolve(repo, experiment_hash)
    _protocol_bytes(experiment, c, experiment_hash, blob)
    path = repo/ROOT/(c+"-attributes")/(experiment["events"][c]+"-protocol-"+experiment_hash+".md")
    if path.exists(): require(path.read_bytes() == blob and not path.is_symlink(), "protocol:retained_rewritten")
    else: _create(path, blob)
    return hashlib.sha256(blob).hexdigest()


def _protocol_hash(repo: Path, experiment: dict, c: str, exp_hash: str) -> str:
    path = repo/ROOT/(c+"-attributes")/(experiment["events"][c]+"-protocol-"+exp_hash+".md")
    try: blob = path.read_bytes()
    except OSError as exc: raise OperationalError("protocol:missing") from exc
    require(not path.is_symlink(), "protocol:symlink")
    _protocol_bytes(experiment, c, exp_hash, blob)
    return hashlib.sha256(blob).hexdigest()


def build_quality(repo: Path, experiment_hash: str, c: str, evidence_hash: str) -> dict:
    require(c in CAPS, "quality:capability")
    experiment = resolve(repo, experiment_hash)
    validate_experiment(repo, experiment)
    evidence = resolve(repo, evidence_hash)
    keys(evidence, {"schema", "experimentSha256", "capability", "gateResults", "pairwise", "partition"}, "quality_evidence")
    require(evidence["schema"] == QUALITY_EVIDENCE_SCHEMA and evidence["experimentSha256"] == experiment_hash
            and evidence["capability"] == c and evidence["partition"] == "selection", "quality_evidence:identity_or_partition")
    cap = experiment["capabilities"][c]
    outputs = op.quality_sets(cap, evidence["gateResults"], evidence["pairwise"])
    # A set-valued pure task-quality view, independent of engineering and MPID.
    rows = {(r["a"], r["b"], r["claimId"]): r["outcome"] for r in evidence["pairwise"]}
    ids = [u["unitId"] for u in cap["units"]]
    outputs["highestTaskQualityEvaluatedSet"] = [a for a in ids if all(rows[a, b, q["claimId"]] in op.PROTECTED
                                           for b in ids if a != b for q in cap["claims"])]
    return {"schema": QUALITY_SCHEMA, "eventId": experiment["events"][c], "capability": c,
            "frozenLedgerSha256": experiment["ledgerHashes"][c], "protocolSha256": _protocol_hash(repo, experiment, c, experiment_hash),
            "qualityContractHash": experiment["qualityContractHash"], "operationalContractHash": experiment["operationalContractHash"],
            "experimentSha256": experiment_hash, "qualityEvidenceSha256": evidence_hash,
            "decisionClaimsSha256": sha256(cap["claims"]), "pairwiseMatrixSha256": sha256(evidence["pairwise"]),
            "gateResultsSha256": sha256(evidence["gateResults"]), "outputs": outputs}


def validate_quality(repo: Path, doc: dict) -> None:
    keys(doc, QUALITY_KEYS, "quality_result")
    expected = build_quality(repo, doc["experimentSha256"], doc["capability"], doc["qualityEvidenceSha256"])
    require(canonical(doc) == canonical(expected), "quality_result:derived_or_identity_mismatch")


def validate_e2_trace(trace: dict, pair: dict, identity: str) -> None:
    keys(trace, {"schema", "apiMode", "pair", "identitySha256", "workerId", "attempts", "calls"}, "E2_trace")
    require(trace["schema"] == "mavi-s2c-e2-runner-evidence-v1" and trace["apiMode"] == "real-platform"
            and trace["pair"] == pair and trace["identitySha256"] == identity, "E2_trace:identity_or_path")
    text(trace["workerId"], "E2_trace:workerId")
    require(type(trace["attempts"]) is list and bool(trace["attempts"]) and type(trace["calls"]) is list, "E2_trace:empty")
    for attempt in trace["attempts"]:
        keys(attempt, {"status", "failureCode"}, "E2_attempt")
        require(attempt["status"] in ("completed", "superseded", "failed", "lease_lost", "abandoned"), "E2_attempt:status")
        if attempt["failureCode"] is not None: text(attempt["failureCode"], "E2_attempt:failureCode")
    operations = []
    for call in trace["calls"]:
        keys(call, {"operation", "startedAtUtc", "finishedAtUtc", "durationUs", "outcome"}, "E2_call")
        operations.append(call["operation"])
        require(call["operation"] in ("lease", "heartbeat", "read_evidence", "upload", "complete", "fail"), "E2_call:operation")
        require(instant(call["startedAtUtc"], "startedAtUtc") <= instant(call["finishedAtUtc"], "finishedAtUtc"), "E2_call:clock")
        integer(call["durationUs"], "E2_call:durationUs")
        require(call["outcome"] in ("returned", "raised"), "E2_call:outcome")
    require({"lease", "read_evidence", "upload", "complete"} <= set(operations), "E2_trace:incomplete_runner_path")


MEASUREMENT_FIELDS = {
    "startup": {"lowerReadyUs", "upperReadyUs"},
    "services": {"lowerServices", "upperServices"},
    "resources": {"ramBytesPerHost", "ioBytesPerSecond", "apiRequestsPerSecond", "runtimeCompatible"},
    "footprint": {"footprint"},
    "serverTiming": {"e2TraceSha256"},
}


def _measurement_sources(repo: Path, experiment: dict, raw: dict) -> None:
    keys(raw["measurementReferences"], set(MEASUREMENT_FIELDS), "measurementReferences")
    for kind, fields in MEASUREMENT_FIELDS.items():
        source = resolve(repo, raw["measurementReferences"][kind])
        keys(source, {"schema", "kind", "pair", "identitySha256", "hostProfileSha256", "recordedBy", "recordedAtUtc", "measurements", "transactions"}, "measurementSource")
        require(source["schema"] == "mavi-s2c-engineering-measurements-v1" and source["kind"] == kind
                and source["pair"] == raw["pair"] and source["identitySha256"] == raw["identitySha256"]
                and source["hostProfileSha256"] == experiment["hostProfileSha256"], "measurementSource:identity")
        text(source["recordedBy"], "measurementSource:recordedBy")
        instant(source["recordedAtUtc"], "recordedAtUtc")
        require(canonical(source["measurements"]) == canonical({k: raw[k] for k in fields}), "measurementSource:values")
        require(type(source["transactions"]) is list, "measurementSource:transactions")
        if kind != "serverTiming": require(not source["transactions"], "measurementSource:unexpected_transactions")
        else:
            require(bool(source["transactions"]), "measurementSource:server_transactions_required")
            for row in source["transactions"]:
                fields = ["claimedAtUtc", "phaseAAtUtc", "completedAtUtc", "committedAtUtc", "acknowledgedAtUtc"]
                keys(row, {"jobId", *fields}, "serverTransaction")
                text(row["jobId"], "serverTransaction:jobId")
                times = [instant(row[k], k) for k in fields]
                require(times == sorted(times), "serverTransaction:ordering")


def _distribution(values: list[int]) -> dict:
    ordered = sorted(values)
    return {"count": len(ordered), "minimum": ordered[0] if ordered else None,
            "p95": ordered[(95*len(ordered)+99)//100-1] if ordered else None,
            "maximum": ordered[-1] if ordered else None}


def _replay_report(workload: dict, result: dict, experiment: dict) -> dict:
    distributions = {k: [] for k in ("queueToPublicationUs", "claimToPhaseAUs", "claimToPublicationUs", "publicationToAcknowledgementUs")}
    misses = sla = 0
    completed = []
    rows = list(result["jobs"].values())
    for row in rows:
        claim = instant(row["firstClaimedAtUtc"], "firstClaimedAtUtc") if row["firstClaimedAtUtc"] else None
        phase = instant(row["phaseAValidatedAtUtc"], "phaseAValidatedAtUtc") if row["phaseAValidatedAtUtc"] else None
        commit = instant(row["publicationCommittedAtUtc"], "publicationCommittedAtUtc") if row["publicationCommittedAtUtc"] else None
        ack = instant(row["completionAcknowledgedAtUtc"], "completionAcknowledgedAtUtc") if row["completionAcknowledgedAtUtc"] else None
        misses += int(claim is not None and (phase is None or phase >= claim+experiment["wholeJob"]["maximumAnalysisDurationUs"]))
        if commit is None: sla += 1
        else:
            duration = commit-instant(row["queuedAtUtc"], "queuedAtUtc")
            distributions["queueToPublicationUs"].append(duration)
            distributions["claimToPublicationUs"].append(commit-claim)
            completed.append(row["publicationCommittedAtUtc"])
            sla += int(duration > experiment["limits"]["maxQueueToPublicationUs"])
        if phase is not None: distributions["claimToPhaseAUs"].append(phase-claim)
        if ack is not None: distributions["publicationToAcknowledgementUs"].append(ack-commit)
    return {"workloadId": workload["workloadId"], "completedJobs": sum(r["status"] == "Completed" for r in rows),
            "failedJobs": sum(r["status"] == "Failed" for r in rows), "retriedJobs": sum(r["attempts"] > 1 for r in rows),
            "phaseADeadlineMisses": misses, "ownerSlaMisses": sla, "peakBacklog": result["peakBacklog"],
            "waitingJobs": result["waitingJobs"], "unfinishedTracks": result["unfinishedTracks"], "oldestQueueAgeUs": result["oldestQueueAgeUs"],
            "drainAtUtc": max(completed) if len(completed) == len(rows) else None,
            **{k: _distribution(v) for k, v in distributions.items()}}


def operational_measurements(repo: Path, experiment: dict, exp_hash: str, evidence_hash: str) -> list[dict]:
    return operational_projection(repo, experiment, exp_hash, evidence_hash)["measurements"]


def operational_projection(repo: Path, experiment: dict, exp_hash: str, evidence_hash: str) -> dict:
    """Derive both host bounds with the same replay and frozen error envelope."""
    evidence = resolve(repo, evidence_hash)
    keys(evidence, {"schema", "experimentSha256", "pairs"}, "operational_evidence")
    require(evidence["schema"] == OPERATIONAL_EVIDENCE_SCHEMA and evidence["experimentSha256"] == exp_hash,
            "operational_evidence:experiment")
    require(type(evidence["pairs"]) is list, "operational_evidence:pairs")
    rows, seen, reports = [], [], []
    units = {c: {u["unitId"]: u for u in experiment["capabilities"][c]["units"]} for c in CAPS}
    for c in CAPS:
        fallback = experiment["capabilities"][c]["fallback"]
        if fallback: units[c][fallback["unitId"]] = fallback
    for raw in evidence["pairs"]:
        keys(raw, {"pair", "identitySha256", "lowerServices", "upperServices", "ramBytesPerHost", "ioBytesPerSecond",
                   "runtimeCompatible", "evidenceComplete", "e2TraceSha256", "lowerReadyUs", "upperReadyUs",
                   "apiRequestsPerSecond", "footprint", "measurementReferences"}, "operational_pair")
        p, v = op.pair_key(raw["pair"])
        require(p in units["person"] and v in units["vehicle"], "operational_pair:unit_identity")
        seen.append((p, v))
        digest(raw["identitySha256"], "runtime_identity")
        require(raw["identitySha256"] == runtime_identity(experiment, raw["pair"]), "runtime_identity:configuration_mismatch")
        require(type(raw["evidenceComplete"]) is bool, "operational_pair:evidence_bool")
        if not raw["evidenceComplete"]:
            require(all(raw[k] is None for k in set(raw)-{"pair", "identitySha256", "evidenceComplete"}), "incomplete:claimed_measurements")
            rows.append({"pair": raw["pair"], "H_lo": None, "H_up": None, "hostClassId": experiment["hostClassId"],
                "evidenceComplete": False, "constraints": {k: False for k in CONSTRAINTS}, "operationalEvidenceSha256": evidence_hash})
            continue
        _measurement_sources(repo, experiment, raw)
        for k in ("lowerReadyUs", "upperReadyUs", "apiRequestsPerSecond"): integer(raw[k], k)
        require(raw["lowerReadyUs"] <= raw["upperReadyUs"], "startup:bounds_order")
        keys(raw["footprint"], {"modelPackBytes", "runtimePackBytes", "deploymentGrowthBytes"}, "footprint")
        for k, v in raw["footprint"].items(): integer(v, k)
        digest(raw["e2TraceSha256"], "E2_trace")
        validate_e2_trace(resolve(repo, raw["e2TraceSha256"]), raw["pair"], raw["identitySha256"])
        integer(raw["ramBytesPerHost"], "ramBytesPerHost")
        integer(raw["ioBytesPerSecond"], "ioBytesPerSecond")
        require(type(raw["runtimeCompatible"]) is bool, "runtimeCompatible:bool")
        require(type(raw["lowerServices"]) is type(raw["upperServices"]) is dict, "services:maps")
        shapes = {j["shape"] for w in experiment["workloads"] for j in w["jobs"]}
        keys(raw["lowerServices"], shapes, "lowerServices")
        keys(raw["upperServices"], shapes, "upperServices")
        for shape in shapes:
            lower, upper = raw["lowerServices"][shape], raw["upperServices"][shape]
            require(set(lower) == set(upper), "services:bounds_fields")
            require(all(type(lower[k]) is int and type(upper[k]) is int and lower[k] <= upper[k]
                        for k in ("phaseAUs", "publicationUs", "acknowledgementUs", "phaseCStampOffsetUs")), "services:bounds_order")
            require(lower["explicitFailureAtUs"] == upper["explicitFailureAtUs"] and lower["failureRetryable"] is upper["failureRetryable"], "services:frozen_failure")
        constraints = {k: True for k in CONSTRAINTS}
        constraints["runtime"] = raw["runtimeCompatible"]
        constraints["memory"] = raw["ramBytesPerHost"] <= experiment["limits"]["maxRamBytesPerHost"]
        constraints["io"] = raw["ioBytesPerSecond"] <= experiment["limits"]["maxIoBytesPerSecond"]
        constraints["api"] = raw["apiRequestsPerSecond"] <= experiment["workloadEnvelope"]["apiMaxRequestsPerSecond"]
        constraints["footprint"] = sum(raw["footprint"].values()) <= experiment["workloadEnvelope"]["storageLimitBytes"]
        bounds = []
        for bound in ("lower", "upper"):
            services = copy.deepcopy(raw[bound+"Services"])
            error = experiment["uncertainty"][bound+"ErrorPpm"]
            factor = 1_000_000 + error if bound == "upper" else 1_000_000-error
            for service in services.values():
                for field in ("phaseAUs", "publicationUs", "phaseCStampOffsetUs", "acknowledgementUs"):
                    service[field] = (service[field]*factor + (999_999 if bound == "upper" else 0))//1_000_000
            ready = (raw[bound+"ReadyUs"]*factor + (999_999 if bound == "upper" else 0))//1_000_000
            constraints["cold"] &= ready <= experiment["limits"]["maxBootToReadyUs"]
            supported = None
            last_checks = None
            # Fluid screen is only a necessary lower bound; all deadline and
            # recovery admission still comes from whole-job replay.
            fluid_hosts = experiment["reserveHosts"]+1
            for workload in experiment["workloads"]:
                demand = sum(services[j["shape"]]["phaseAUs"]+services[j["shape"]]["publicationUs"] for j in workload["jobs"])
                capacity = (instant(workload["endAtUtc"], "endAtUtc")-instant(workload["startAtUtc"], "startAtUtc"))*experiment["workersPerHost"]
                fluid_hosts = max(fluid_hosts, experiment["reserveHosts"]+(demand+capacity-1)//capacity)
            checks = {k: False for k in CONSTRAINTS}
            for hosts in range(fluid_hosts, experiment["maximumHosts"]+1):
                checks = {k: True for k in CONSTRAINTS}
                report = {"pair": raw["pair"], "bound": bound, "installedHosts": hosts, "activeHosts": hosts-experiment["reserveHosts"],
                          "workersPerHost": experiment["workersPerHost"], "coldReadyUs": ready, "workloads": []}
                for workload in experiment["workloads"]:
                    count = (hosts-experiment["reserveHosts"])*experiment["workersPerHost"]
                    workers = [{"workerId": f"w-{n:05d}", "hostId": f"h-{n//experiment['workersPerHost']:05d}",
                                "readyAtUtc": utc(instant(workload["startAtUtc"], "startAtUtc")+ready), "identitySha256": raw["identitySha256"]} for n in range(count)]
                    jobs = [{**j, "identitySha256": raw["identitySha256"]} for j in workload["jobs"]]
                    result = replay(jobs, workers, experiment["wholeJob"], services, workload["outages"],
                                    startAtUtc=workload["startAtUtc"], endAtUtc=workload["endAtUtc"])
                    metrics = _replay_report(workload, result, experiment)
                    report["workloads"].append(metrics)
                    if metrics["drainAtUtc"] is None: checks["recovery"] = False
                    else:
                        last_release = max(instant(j["queuedAtUtc"], "queuedAtUtc") for j in jobs)
                        checks["recovery"] &= instant(metrics["drainAtUtc"], "drainAtUtc")-last_release <= experiment["workloadEnvelope"]["drainLimitUs"]
                    checks["queue"] &= result["peakBacklog"] <= experiment["limits"]["maxBacklog"]
                    for row in result["jobs"].values():
                        checks["recovery"] &= row["status"] == "Completed"
                        checks["publication"] &= row["boundedPublicationPassed"] is True
                        if row["publicationCommittedAtUtc"] is None:
                            checks["queue"] = checks["warm"] = False
                        else:
                            commit = instant(row["publicationCommittedAtUtc"], "publicationCommittedAtUtc")
                            checks["warm"] &= commit-instant(row["firstClaimedAtUtc"], "firstClaimedAtUtc") <= experiment["limits"]["maxWarmUs"]
                            checks["queue"] &= commit-instant(row["queuedAtUtc"], "queuedAtUtc") <= experiment["limits"]["maxQueueToPublicationUs"]
                reports.append(report)
                last_checks = checks
                if all(checks.values()): supported = hosts; break
            bounds.append(supported)
            for k in checks: constraints[k] &= (last_checks or checks)[k]
        constraints["bounds"] = all(b is not None for b in bounds)
        # Complete evidence can demonstrate infeasibility. A finite display sentinel
        # would fabricate support; infeasible bounds remain null and admission false.
        rows.append({"pair": raw["pair"], "H_lo": min(bounds) if all(b is not None for b in bounds) else None, "H_up": max(bounds) if all(b is not None for b in bounds) else None, "hostClassId": experiment["hostClassId"],
                     "evidenceComplete": True, "constraints": constraints, "operationalEvidenceSha256": evidence_hash})
    require(seen == sorted(set(seen)), "operational_pairs:sorted_unique")
    return {"measurements": rows, "reports": reports}


def build_technical(repo: Path, experiment_hash: str, quality_hashes: dict, operational_hash: str) -> dict:
    experiment = resolve(repo, experiment_hash)
    validate_experiment(repo, experiment)
    keys(quality_hashes, CAPS, "qualityResultHashes")
    quality = {}
    for c in CAPS:
        q = resolve(repo, quality_hashes[c])
        validate_quality(repo, q)
        require(q["experimentSha256"] == experiment_hash and q["capability"] == c, "joint:quality_identity")
        quality[c] = q["outputs"]
    projection = operational_projection(repo, experiment, experiment_hash, operational_hash)
    rows = projection["measurements"]
    population = op.product(quality["person"]["J"], quality["vehicle"]["J"])
    selection = op.select_pairs(population, rows, experiment["hostClassId"], CONSTRAINTS)
    stage = {"J_person": quality["person"]["J"], "J_vehicle": quality["vehicle"]["J"], "measurements": rows,
             "operationalEvidenceSha256": operational_hash, "selection": selection, "projectionReports": projection["reports"]}
    stage["jointEvidenceSha256"] = sha256(stage)
    return {"schema": JOINT_SCHEMA, "eventPairId": experiment["eventPairId"], "version": 1, "stage": "technical", "supersedes": None,
            "events": experiment["events"], "ledgerHashes": experiment["ledgerHashes"], "qualityResultHashes": quality_hashes,
            "qualityContractHash": experiment["qualityContractHash"], "operationalContractHash": experiment["operationalContractHash"],
            "experimentSha256": experiment_hash, "technicalStage": stage, "implementationStage": None, "revision": None}


def _implementation_stage(repo, joint, snapshot_hashes, dates, licence, operational_hash):
    experiment = resolve(repo, joint["experimentSha256"])
    keys(snapshot_hashes, CAPS, "snapshotHashes")
    snapshots = {c: resolve(repo, snapshot_hashes[c]) for c in CAPS}
    keys(dates, CAPS, "decidedOn")
    for c in CAPS:
        require(cred._date(dates[c], "implementation:decidedOn") >= cred._date(experiment["frozenOn"], "frozenOn"), "implementation:before_freeze")
        frozen = resolve(repo, experiment["ledgerHashes"][c])
        cred.validate_evolution(frozen, snapshots[c])
    quality = {c: resolve(repo, joint["qualityResultHashes"][c])["outputs"] for c in CAPS}
    original = resolve(repo, joint["technicalStage"]["operationalEvidenceSha256"])
    later = resolve(repo, operational_hash)
    originals = {op.pair_key(r["pair"]): r for r in original["pairs"]}
    additions = {op.pair_key(r["pair"]): r for r in later["pairs"]}
    for ident, raw in originals.items():
        require(ident in additions and canonical(raw) == canonical(additions[ident]), "implementation:technical_operational_evidence_changed")
    projection = operational_projection(repo, experiment, joint["experimentSha256"], operational_hash)
    rows = projection["measurements"]
    # A later stage may add frozen-fallback pairs; evidence for all original technical
    # pairs must remain identical to the technical evidence, not recalibrated.
    old = {op.pair_key(r["pair"]): r for r in joint["technicalStage"]["measurements"]}
    new = {op.pair_key(r["pair"]): r for r in rows}
    for ident, row in old.items():
        require(ident in new and {k: v for k, v in row.items() if k != "operationalEvidenceSha256"}
                == {k: v for k, v in new[ident].items() if k != "operationalEvidenceSha256"}, "implementation:technical_operational_evidence_changed")
    outputs = op.implementation_sets(experiment["capabilities"], quality, rows, licence, snapshots, dates,
                                     experiment["profiles"], experiment["hostClassId"], CONSTRAINTS)
    return {"snapshotHashes": snapshot_hashes, "decidedOn": dates, "licence": licence,
            "operationalEvidenceSha256": operational_hash, "measurements": rows, "outputs": outputs, "projectionReports": projection["reports"],
            "supersedes": joint["supersedes"]}


def build_implementation(repo: Path, predecessor_hash: str, snapshot_hashes: dict, dates: dict,
                         licence: dict, operational_hash: str) -> dict:
    previous = find_joint(repo, predecessor_hash)
    require(previous["stage"] in ("technical", "implementation"), "implementation:predecessor_stage")
    doc = copy.deepcopy(previous)
    doc.update(version=previous["version"]+1, stage="implementation", supersedes=predecessor_hash)
    doc["implementationStage"] = _implementation_stage(repo, doc, snapshot_hashes, dates, licence, operational_hash)
    return doc


def validate_joint(repo: Path, doc: dict, predecessor: dict | None) -> None:
    keys(doc, JOINT_KEYS, "joint")
    require(doc["schema"] == JOINT_SCHEMA and doc["stage"] in ("technical", "implementation"), "joint:schema_or_stage")
    integer(doc["version"], "joint:version", 1)
    expected = build_technical(repo, doc["experimentSha256"], doc["qualityResultHashes"], doc["technicalStage"]["operationalEvidenceSha256"])
    for field in JOINT_KEYS - {"version", "stage", "supersedes", "implementationStage", "revision"}:
        require(canonical(doc[field]) == canonical(expected[field]), f"joint:derived:{field}")
    if predecessor is None:
        require(doc["version"] == 1 and doc["stage"] == "technical" and doc["supersedes"] is None and doc["revision"] is None, "joint:initial_version")
    else:
        require(doc["eventPairId"] == predecessor["eventPairId"] and doc["version"] == predecessor["version"]+1
                and doc["supersedes"] == sha256(predecessor), "joint:predecessor")
        if doc["stage"] == "implementation":
            require(canonical(doc["technicalStage"]) == canonical(predecessor["technicalStage"]), "joint:technical_stage_rewritten")
            require(doc["revision"] == predecessor["revision"], "joint:revision_changed_at_implementation")
            for field in ("events", "ledgerHashes", "qualityResultHashes", "qualityContractHash", "operationalContractHash", "experimentSha256"):
                require(doc[field] == predecessor[field], f"joint:implementation_redefined:{field}")
            if predecessor["stage"] == "implementation":
                for c in sorted(CAPS):
                    before = predecessor["implementationStage"]
                    after = doc["implementationStage"]
                    require(cred._date(after["decidedOn"][c], "decidedOn") >= cred._date(before["decidedOn"][c], "decidedOn"), "implementation:date_regressed")
                    cred.validate_evolution(resolve(repo, before["snapshotHashes"][c]), resolve(repo, after["snapshotHashes"][c]),
                                            since=date.fromisoformat(before["decidedOn"][c]))
        else:
            revision = keys(doc["revision"], {"number", "reason", "changes", "freshEvaluationBasisSha256"}, "revision")
            integer(revision["number"], "revision:number", 1)
            prior_number = 0 if predecessor["revision"] is None else predecessor["revision"]["number"]
            require(revision["number"] == prior_number+1, "revision:sequence")
            text(revision["reason"], "revision:reason")
            tokens(revision["changes"], "revision:changes", nonempty=True)
            allowed = {"manifest", "claims", "margins", "objective", "workload", "replay", "E2-model", "profiles"}
            require(set(revision["changes"]) <= allowed, "revision:changes")
            digest(revision["freshEvaluationBasisSha256"], "revision:fresh_basis")
            require(doc["experimentSha256"] != predecessor["experimentSha256"], "revision:unchanged_experiment")
    if doc["stage"] == "technical":
        require(doc["implementationStage"] is None, "technical:early_implementation")
    else:
        stage = keys(doc["implementationStage"], {"snapshotHashes", "decidedOn", "licence", "operationalEvidenceSha256", "measurements", "outputs", "projectionReports", "supersedes"}, "implementationStage")
        expected_stage = _implementation_stage(repo, doc, stage["snapshotHashes"], stage["decidedOn"], stage["licence"], stage["operationalEvidenceSha256"])
        require(canonical(stage) == canonical(expected_stage), "implementationStage:derived")


def _version_paths(repo, event_pair_id):
    require(type(event_pair_id) is str and PAIR_ID.fullmatch(event_pair_id) is not None, "eventPairId:format")
    directory = repo/ROOT/"s2c-joint"
    paths = list(directory.glob(event_pair_id+"-joint-*-v*.json"))
    pattern = re.compile(re.escape(event_pair_id)+r"-joint-(technical|implementation)-v([1-9][0-9]*)\.json$")
    entries = []
    for path in paths:
        match = pattern.fullmatch(path.name)
        require(match is not None and not path.is_symlink(), "joint:version_filename")
        doc = read(path)
        require(doc.get("eventPairId") == event_pair_id and doc.get("stage") == match[1]
                and type(doc.get("version")) is int and doc["version"] == int(match[2]), "joint:file_metadata")
        entries.append((int(match[2]), path, doc))
    return sorted(entries, key=lambda e: e[0])


def validate_chain(repo: Path, event_pair_id: str) -> dict[str, dict]:
    retained = _version_paths(repo, event_pair_id)
    require(bool(retained), "joint:versions_missing")
    index_path = repo/ROOT/"s2c-joint"/(event_pair_id+"-joint-index.json")
    index = read(index_path)
    keys(index, {"schema", "eventPairId", "versions", "active"}, "joint_index")
    require(index["schema"] == INDEX_SCHEMA and index["eventPairId"] == event_pair_id, "joint_index:identity")
    expected_entries, versions, previous = [], {}, None
    for n, path, doc in retained:
        require(n == len(expected_entries)+1, "joint_index:gap_or_fork")
        identity = sha256(doc)
        require(identity not in versions, "joint:ambiguous_hash")
        validate_joint(repo, doc, previous)
        expected_entries.append({"path": path.relative_to(repo).as_posix(), "stage": doc["stage"], "sha256": identity, "supersedes": doc["supersedes"]})
        versions[identity] = doc
        previous = doc
    require(canonical(index["versions"]) == canonical(expected_entries), "joint_index:file_metadata_or_order")
    require(index["active"] == expected_entries[-1]["sha256"], "joint_index:active_not_last")
    return versions


def find_joint(repo: Path, identity: str) -> dict:
    digest(identity, "joint_reference")
    hits = []
    for index in (repo/ROOT/"s2c-joint").glob("*-joint-index.json"):
        value = read(index)
        versions = validate_chain(repo, value["eventPairId"])
        if identity in versions: hits.append(versions[identity])
    require(len(hits) == 1, "joint:missing_or_ambiguous_predecessor")
    return hits[0]


def retain_joint(repo: Path, document: dict) -> str:
    eid = document["eventPairId"]
    prior = _version_paths(repo, eid)
    previous = prior[-1][2] if prior else None
    if prior: validate_chain(repo, eid)
    validate_joint(repo, document, previous)
    path = ROOT/"s2c-joint"/f"{eid}-joint-{document['stage']}-v{document['version']}.json"
    _create(repo/path, canonical(document))
    entries = [{"path": p.relative_to(repo).as_posix(), "stage": doc["stage"], "sha256": sha256(doc), "supersedes": doc["supersedes"]}
               for _, p, doc in prior]
    identity = sha256(document)
    entries.append({"path": path.as_posix(), "stage": document["stage"], "sha256": identity, "supersedes": document["supersedes"]})
    index = {"schema": INDEX_SCHEMA, "eventPairId": eid, "versions": entries, "active": identity}
    index_path = repo/ROOT/"s2c-joint"/(eid+"-joint-index.json")
    temporary = index_path.with_suffix(".json.new")
    _create(temporary, canonical(index))
    os.replace(temporary, index_path)
    validate_chain(repo, eid)
    return identity


def _event_versions(repo: Path, c: str, event_id: str) -> list[tuple[int, Path]]:
    directory = repo/ROOT/(c+"-attributes")
    pattern = re.compile(re.escape(event_id)+r"-decision-v([1-9][0-9]*)\.json$")
    versions = sorted((int(pattern.fullmatch(p.name)[1]), p) for p in directory.glob(event_id+"-decision-v*.json") if pattern.fullmatch(p.name))
    require([n for n, _ in versions] == list(range(1, len(versions)+1)), "event_decision:version_gap")
    return versions


def _event_predecessor(repo: Path, c: str, event_id: str, version: int, predecessor_hash: str | None,
                       state: str, decided_on: str, joint: dict) -> None:
    integer(version, "decisionVersion", 1)
    if version == 1:
        require(predecessor_hash is None and state == "TECHNICAL_DECISION_RECORDED", "event_decision:initial_technical_required")
        return
    digest(predecessor_hash, "event_decision:predecessor_hash")
    path = repo/ROOT/(c+"-attributes")/f"{event_id}-decision-v{version-1}.json"
    try: previous = read(path)
    except OSError as exc: raise OperationalError("event_decision:predecessor_missing") from exc
    require(not path.is_symlink() and sha256(previous) == predecessor_hash and previous["decisionVersion"] == version-1
            and previous["eventId"] == event_id and previous["capability"] == c, "event_decision:predecessor_mismatch")
    require(cred._date(decided_on, "decidedOn") >= cred._date(previous["decidedOn"], "decidedOn"), "event_decision:date_regressed")
    require(previous["eventState"] != "CLOSED", "event_decision:closed_immutable")
    previous_joint_hash = previous["jointOperationalDecisionSha256"]
    if sha256(joint) != previous_joint_hash:
        # find_joint validates the complete retained index/files, not merely
        # the supplied document's version number or supersedes field.
        older_joint = find_joint(repo, previous_joint_hash)
        require(joint["eventPairId"] == older_joint["eventPairId"]
                and joint["version"] == older_joint["version"]+1
                and joint["supersedes"] == previous_joint_hash, "event_decision:joint_continuity")
    if state == "TECHNICAL_DECISION_RECORDED" and previous["eventState"] != state:
        older_joint = find_joint(repo, previous_joint_hash)
        require(joint["stage"] == "technical" and joint["version"] > older_joint["version"]
                and joint["experimentSha256"] != older_joint["experimentSha256"], "event_decision:state_regressed")
    else:
        states = ["TECHNICAL_DECISION_RECORDED", "QUALIFICATION_PENDING", "CLOSED"]
        require(state in states and 0 <= states.index(state)-states.index(previous["eventState"]) <= 1, "event_decision:state_transition")


def build_event_decision(repo: Path, joint_hash: str, c: str, state: str, decided_on: str,
                         implementation_pair: dict | None, owner_choice: dict | None, *,
                         decision_version: int | None = None, predecessor_hash: str | None = None) -> dict:
    require(c in CAPS and state in cred.EVENT_STATES, "decision:scope_or_state")
    joint = find_joint(repo, joint_hash)
    quality = resolve(repo, joint["qualityResultHashes"][c])
    experiment = resolve(repo, joint["experimentSha256"])
    if decision_version is None:
        versions = _event_versions(repo, c, experiment["events"][c])
        decision_version = len(versions)+1
        predecessor_hash = sha256(read(versions[-1][1])) if versions else None
    _event_predecessor(repo, c, experiment["events"][c], decision_version, predecessor_hash, state, decided_on, joint)
    impl = joint["implementationStage"]
    expected_stage = "technical" if state == "TECHNICAL_DECISION_RECORDED" else "implementation"
    require(joint["stage"] == expected_stage, "decision:wrong_joint_stage")
    if state == "TECHNICAL_DECISION_RECORDED":
        require(implementation_pair is None and owner_choice is None, "decision:early_implementation")
        snapshot_hash = None
    else:
        require(impl["decidedOn"][c] == decided_on, "decision:snapshot_date")
        snapshot_hash = impl["snapshotHashes"][c]
        if implementation_pair is not None:
            op.pair_key(implementation_pair)
            require(implementation_pair in impl["outputs"]["T_impl"], "decision:exact_pair_not_in_T_impl")
            keys(owner_choice, {"decidedBy", "rationale"}, "ownerChoice")
            text(owner_choice["decidedBy"], "ownerChoice:decidedBy")
            text(owner_choice["rationale"], "ownerChoice:rationale")
        else:
            require(owner_choice is None, "decision:owner_without_pair")
    require(cred._date(decided_on, "decision:decidedOn") >= cred._date(experiment["frozenOn"], "frozenOn"), "decision:before_freeze")
    outcome = None
    if state == "CLOSED":
        require(not impl["outputs"]["pending"], "decision:pending_licence_at_closed")
        if implementation_pair is None:
            require(not impl["outputs"]["T_impl"], "decision:no_qualifiable_with_implementation_available")
            outcome = "NO_QUALIFIABLE_CANDIDATE"
        else:
            uid = implementation_pair[c+"UnitId"]
            units = experiment["capabilities"][c]["units"]
            fallback = experiment["capabilities"][c]["fallback"]
            unit = next(u for u in units+([fallback] if fallback else []) if u["unitId"] == uid)
            outcome = {"learned": "SELECTED_FOR_PACKAGING", "baseline": "BASELINE_SELECTED", "disabled": "NO_QUALIFIABLE_CANDIDATE"}[unit["kind"]]
    selection = joint["technicalStage"]["selection"]
    result = {"decisionVersion": decision_version, "supersedesEventDecisionSha256": predecessor_hash, "schema": DECISION_SCHEMA, "methodRevision": "msr-v1-m2", "eventId": experiment["events"][c],
              "capability": c, "eventState": state, "outcome": outcome, "decidedOn": decided_on,
              "experimentSha256": joint["experimentSha256"], "qualityResultSha256": joint["qualityResultHashes"][c],
              "jointOperationalDecisionSha256": joint_hash, "ledgerSha256": snapshot_hash,
              "frozenLedgerSha256": quality["frozenLedgerSha256"], "protocolSha256": quality["protocolSha256"],
              "qualityContractHash": quality["qualityContractHash"], "operationalContractHash": quality["operationalContractHash"],
              "evaluated": [{"unitId": u["unitId"], "components": u["components"], "configurationSha256": u["configurationSha256"]}
                            for u in experiment["capabilities"][c]["units"]],
              "technicalEligibleSet": quality["outputs"]["E"], "qualityAcceptableSet": quality["outputs"]["F"],
              "pairwiseMatrixSha256": quality["pairwiseMatrixSha256"], "decisionClaimsSha256": quality["decisionClaimsSha256"],
              "mpidStatus": quality["outputs"]["mpidStatus"], "highestTaskQualityEvaluatedSet": quality["outputs"]["highestTaskQualityEvaluatedSet"],
              "qualityOutcomeReason": {"outcome": quality["outputs"]["qualityOutcome"], "causes": quality["outputs"]["qualityOutcomeReason"]},
              "technicalSelectionOutcome": selection["outcome"], "technicalSelectedSet": selection["T"],
              "technicalWinner": selection["T"][0] if len(selection["T"]) == 1 else None,
              "profileClearedSet": None if impl is None else impl["outputs"]["T_r"],
              "implementationEligibleSet": None if impl is None else impl["outputs"]["T_impl"],
              "implementationPair": implementation_pair, "ownerChoice": owner_choice}
    result["decisionEvidenceHash"] = sha256({"experimentSha256": result["experimentSha256"],
                                            "qualityResultSha256": result["qualityResultSha256"],
                                            "jointOperationalDecisionSha256": joint_hash})
    return result


def validate_event_decision(repo: Path, doc: dict) -> None:
    keys(doc, DECISION_KEYS, "decision_v2")
    expected = build_event_decision(repo, doc["jointOperationalDecisionSha256"], doc["capability"], doc["eventState"],
                                    doc["decidedOn"], doc["implementationPair"], doc["ownerChoice"],
                                    decision_version=doc["decisionVersion"], predecessor_hash=doc["supersedesEventDecisionSha256"])
    require(canonical(doc) == canonical(expected), "decision_v2:derived_or_identity_mismatch")


def validate_event_pair(repo: Path, decisions: dict) -> None:
    keys(decisions, CAPS, "event_decisions")
    for doc in decisions.values(): validate_event_decision(repo, doc)
    for field in ("jointOperationalDecisionSha256", "implementationPair", "eventState", "ownerChoice", "decisionVersion"):
        require(decisions["person"][field] == decisions["vehicle"][field], f"event_decisions:pair_disagreement:{field}")
    require(decisions["person"]["capability"] == "person" and decisions["vehicle"]["capability"] == "vehicle", "event_decisions:capability")


def retain_event_pair(repo: Path, decisions: dict) -> None:
    """Retain both immutable event versions, then update their active projections."""
    validate_event_pair(repo, decisions)
    paths = []
    for c in sorted(CAPS):
        doc = decisions[c]
        directory = repo/ROOT/(c+"-attributes")
        pattern = re.compile(re.escape(doc["eventId"])+r"-decision-v([1-9][0-9]*)\.json$")
        versions = sorted((int(pattern.fullmatch(p.name)[1]), p) for p in directory.glob(doc["eventId"]+"-decision-v*.json") if pattern.fullmatch(p.name))
        require([n for n, _ in versions] == list(range(1, len(versions)+1)), "event_decision:version_gap")
        if versions:
            older = read(versions[-1][1])
            if older["ledgerSha256"] is not None and doc["ledgerSha256"] is not None:
                cred.validate_evolution(resolve(repo, older["ledgerSha256"]), resolve(repo, doc["ledgerSha256"]),
                                        since=date.fromisoformat(older["decidedOn"]))
        require(doc["decisionVersion"] == len(versions)+1, "event_decision:version_not_next")
        retained = directory/f"{doc['eventId']}-decision-v{len(versions)+1}.json"
        require(not retained.exists(), "event_decision:version_exists")
        paths.append((retained, directory/(doc["eventId"]+"-decision.json"), doc))
    for retained, _, doc in paths: _create(retained, canonical(doc))
    for _, active, doc in paths:
        temporary = active.with_suffix(".json.new")
        _create(temporary, canonical(doc))
        os.replace(temporary, active)


def validate_repository(repo: Path) -> list[str]:
    checked = op.validate_repository(repo)
    for path in sorted((repo/ROOT/"s2c-evidence").glob("*.json")):
        doc = read(path)
        require(path.stem == sha256(doc) and not path.is_symlink(), "evidence:address")
        if doc.get("schema") == EXPERIMENT_SCHEMA: validate_experiment(repo, doc)
        if doc.get("schema") == QUALITY_SCHEMA: validate_quality(repo, doc)
        if doc.get("schema") == QUALITY_SCHEMA:
            directory = repo/ROOT/(doc["capability"]+"-attributes")
            candidates = [directory/(doc["eventId"]+"-quality-result.json")]+list(directory.glob(doc["eventId"]+"-quality-result-v*.json"))
            require(sum(p.is_file() and p.read_bytes() == canonical(doc) for p in candidates) == 1,
                    "quality_result:missing_or_ambiguous_event_address")
        checked.append(path.relative_to(repo).as_posix())
    joint_directory = repo/ROOT/"s2c-joint"
    indexed = set()
    for path in sorted(joint_directory.glob("*-joint-index.json")):
        index = read(path)
        validate_chain(repo, index["eventPairId"])
        indexed |= {repo/e["path"] for e in index["versions"]}
        checked.append(path.relative_to(repo).as_posix())
    require(indexed == set(joint_directory.glob("*-joint-*-v*.json")), "joint:unindexed_version")
    checked += [p.relative_to(repo).as_posix() for p in sorted(indexed)]
    grouped = {}
    for path in sorted((repo/ROOT).glob("*-attributes/*-decision-v*.json")):
        doc = read(path)
        validate_event_decision(repo, doc)
        eid = doc["eventId"]
        match = re.fullmatch(re.escape(eid)+r"-decision-v([1-9][0-9]*)\.json", path.name)
        require(match is not None and int(match[1]) == doc["decisionVersion"], "decision:version_filename")
        grouped.setdefault(eid, []).append((int(match[1]), path, doc))
        checked.append(path.relative_to(repo).as_posix())
    paired = {}
    historical_pairs = {}
    for eid, entries in grouped.items():
        entries.sort(key=lambda e: e[0])
        require([n for n, _, _ in entries] == list(range(1, len(entries)+1)), "decision:retention_gap")
        previous = None
        for number, _, doc in entries:
            key = (find_joint(repo, doc["jointOperationalDecisionSha256"])["eventPairId"], number)
            pair = historical_pairs.setdefault(key, {})
            require(doc["capability"] not in pair, "decision:ambiguous_historical_pair")
            pair[doc["capability"]] = doc
            if previous is not None and previous["ledgerSha256"] is not None and doc["ledgerSha256"] is not None:
                cred.validate_evolution(resolve(repo, previous["ledgerSha256"]), resolve(repo, doc["ledgerSha256"]), since=date.fromisoformat(previous["decidedOn"]))
            previous = doc
        active = entries[-1][1].parent/(eid+"-decision.json")
        require(active.read_bytes() == canonical(entries[-1][2]), "decision:active_not_last")
        doc = entries[-1][2]
        paired.setdefault(doc["jointOperationalDecisionSha256"], {})[doc["capability"]] = doc
        checked.append(active.relative_to(repo).as_posix())
    for pair in paired.values(): validate_event_pair(repo, pair)
    for pair in historical_pairs.values(): validate_event_pair(repo, pair)
    for path in sorted((repo/ROOT).glob("*-attributes/*-decision.json")):
        doc = cred.read_json(path)
        if doc.get("schema") == DECISION_SCHEMA:
            require(doc.get("eventId") in grouped, "decision:unretained_version")
    return checked
