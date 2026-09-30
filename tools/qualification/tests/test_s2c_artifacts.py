"""Repository-only immutable-chain and staged-decision adversaries."""
from __future__ import annotations

import copy
import importlib
import importlib.util
from pathlib import Path

import pytest

from model_selection.canonical import canonical, parse, sha256
from model_selection_fixtures import baseline, ledger, settle
from test_s2c_operational import capability, candidate, gates, matrix
from test_s2c_replay import job, service, policy, T0


@pytest.fixture
def artefacts():
    name = "model_selection.s2c_artifacts"
    if importlib.util.find_spec(name) is None:
        class Missing:
            def __getattr__(self, name):
                def missing(*args, **kwargs): pytest.fail(f"artefact {name} implementation missing")
                return missing
        return Missing()
    return importlib.import_module(name)


@pytest.mark.parametrize("blob", [b'{"x":1,"x":2}\n', b'{"x":true,"x":1}\n', b'{"x":NaN}\n',
                                 b'{"x":Infinity}\n', b'{"x":1.0}\n', b'{"x":1}', b'{ "x":1}\n',
                                 b'{"x":1}\r\n', b'\xef\xbb\xbf{"x":1}\n', b'{"x":"\\ud800"}\n'])
def test_canonical_refusals(blob):
    with pytest.raises(ValueError): parse(blob)


def test_unicode_has_one_canonical_utf8_representation():
    blob = canonical({"x": "\u00e9", "number": 1})
    assert blob == b'{"number":1,"x":"\\u00e9"}\n'
    assert parse(blob) == {"number": 1, "x": "\u00e9"}


def measurement_sources(a, root, experiment, row):
    row['measurementReferences'] = {}
    for kind, fields in a.MEASUREMENT_FIELDS.items():
        source = {'schema':'mavi-s2c-engineering-measurements-v1','kind':kind,'pair':row['pair'],
                  'identitySha256':row['identitySha256'],'hostProfileSha256':experiment['hostProfileSha256'],
                  'recordedBy':'synthetic-test','recordedAtUtc':T0,'measurements':{k:row[k] for k in fields},'transactions':[]}
        if kind == 'serverTiming':
            source['transactions'] = [{'jobId':'j','claimedAtUtc':T0,'phaseAAtUtc':'2026-09-01T00:00:03.000000Z',
                                       'completedAtUtc':'2026-09-01T00:00:03.000000Z','committedAtUtc':'2026-09-01T00:00:04.000000Z',
                                       'acknowledgedAtUtc':'2026-09-01T00:00:06.000000Z'}]
        row['measurementReferences'][kind] = a.retain_evidence(root, source)


def fixture(a, root, *, event_pair_id="msr-synthetic-2026-01", horizon_us=60_000_000):
    from model_selection import operational as op
    from model_selection import quality_statistics as b1
    from model_selection.canonical import read
    from model_selection_fixtures import evaluated_row

    source = Path(__file__).resolve().parents[3]
    for path in (op.CONTRACT, b1.CONTRACT, op.PROTOCOL, b1.NORMATIVE_DOC):
        target = root/path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((source/path).read_bytes())
    caps, frozen = {}, {}
    for c, uid, object_class, sub in (("person", "PC-B0", "person", ("T-PC", "T-PO")),
                                      ("vehicle", "VC-B0", "vehicle", ("T-VC",))):
        entry = baseline(uid)
        entry["subTasks"] = list(sub)
        settle(entry)
        frozen[c] = ledger(entry, object_class=object_class, capability=c+"-attributes", subtasks=sub)
        frozen[c]["frozenOn"] = "2026-06-10"
        frozen[c]["methodRevision"] = "msr-v1-m2"
        caps[c] = capability((uid,))
        caps[c]["units"] = [candidate(uid, kind="baseline")]
        caps[c]["fallback"] = caps[c]["units"][0]
    experiment = {"schema": a.EXPERIMENT_SCHEMA, "eventPairId": event_pair_id,
                  "events": {c: frozen[c]["eventId"] for c in frozen},
                  "ledgerHashes": {c: a.retain_evidence(root, frozen[c]) for c in frozen},
                  "qualityContractHash": sha256(b1.read_contract(source/b1.CONTRACT)),
                  "operationalContractHash": sha256(read(source/op.CONTRACT)),
                  "frozenOn": "2026-06-10", "sealedViewOn": "2026-06-10",
                  "freezeAttestation": {"recordedBy": "owner", "reviewedBy": "independent", "beforeSelectionRead": True},
                  "capabilities": caps, "profiles": ["dev"], "hostClassId": "host",
                  "hostProfileSha256": "e"*64, "objective": "minimum-supported-installed-hosts",
                  "workersPerHost": 1, "reserveHosts": 0, "maximumHosts": 4,
                  "wholeJob": policy(), "workloads": [{"workloadId": "typical", "jobs": [job()], "outages": [],
                  "startAtUtc": T0, "endAtUtc": "2026-09-01T00:01:00.000000Z"}],
                  "requiredWorkloadIds": ["typical"], "uncertainty": {"lowerErrorPpm": 0, "upperErrorPpm": 0},
                  "limits": {"maxWarmUs": 20_000_000, "maxQueueToPublicationUs": 30_000_000,
                             "maxBacklog": 10, "maxRamBytesPerHost": 1000, "maxIoBytesPerSecond": 1000},
                  "componentArtefacts": {c: {u["candidateId"]: {k: v for k, v in evaluated_row(u, score=0).items()
                     if k in ("candidateId", "artefactSha256s", "maviTrainedArtefacts", "maviRevision")}
                     for u in frozen[c]["candidates"]} for c in frozen}}
    common = experiment["workloads"][0]
    experiment["workloads"] = []
    for role in sorted(op.contract()["workloadFamily"]["requiredShapes"]):
        w = {**copy.deepcopy(common), "workloadId": role, "role": role, "cameraCount": 500 if role == "500-camera" else None}
        if role == "10k-boundary": w["jobs"] = [job(personTracks=10000, shape="boundary")]
        if role == "small-burst": w["jobs"] = [job("a"), job("b")]
        if role == "mixed": w["jobs"] = [job("a"), job("b", personTracks=10000, shape="boundary")]
        if role == "recovery": w["outages"] = [{"workerIds": ["w-00000"], "lostAtUtc": "2026-09-01T00:00:01.000000Z", "readyAtUtc": "2026-09-01T00:00:02.000000Z", "publicationLost": True}]
        experiment["workloads"].append(w)
    for w in experiment["workloads"]:
        for j in w["jobs"]:
            j["cropsPerTrack"] = {c:[1]*j[c+"Tracks"] for c in ("person","vehicle")}
            j["evidenceSetBytes"] = 10
    experiment["requiredWorkloadIds"] = [w["workloadId"] for w in experiment["workloads"]]
    host = {'schema':'mavi-s2c-host-profile-v1','hostClassId':'host','cpuModel':'synthetic CPU','physicalCores':2,'logicalCores':2,
            'smtEnabled':False,'ramBytes':1000,'osVersion':'synthetic OS','storage':{'kind':'local','readBytesPerSecond':1000,'writeBytesPerSecond':1000},
            'apiPlacement':'local','coResidentIdentities':[],'threadSettings':{'inferenceThreads':1,'runtimeThreads':1,'decodeThreads':1},
            'workerProcessCounts':[1],'powerPolicy':'fixed','runtimeFamily':'synthetic','runtimeManifestSha256':'e'*64}
    experiment['hostProfileSha256'] = a.retain_evidence(root, host)
    experiment['limits']['maxBootToReadyUs'] = 20_000_000
    experiment['workloadEnvelope'] = {'targetCameraCount':500,'cameraClasses':[{'classId':'small','proportionPpm':1_000_000,'description':'sparse synthetic release class'}],
        'correlatedBusyPeriods':[],'releaseCadenceUs':60_000_000,'runDurationUs':60_000_000,'jobsPerInterval':{'small':1},
        'tracksPerJob':{'person':[{'minimum':10,'maximum':10000,'count':1}],'vehicle':[{'minimum':0,'maximum':0,'count':1}]},
        'cropsPerTrack':[{'minimum':1,'maximum':3,'count':10}],'evidenceSetBytes':[{'minimum':1,'maximum':100,'count':1}],
        'initialBacklog':0,'burstWorkloadIds':['small-burst'],'failureWorkloadIds':['recovery'],
        'drainLimitUs':30_000_000,'storageLimitBytes':1000,'apiMaxRequestsPerSecond':100}
    if horizon_us != 60_000_000:
        from model_selection.job_replay import instant, utc
        for workload in experiment['workloads']:
            workload['endAtUtc'] = utc(instant(workload['startAtUtc'], 'startAtUtc')+horizon_us)
        experiment['workloadEnvelope']['releaseCadenceUs'] = horizon_us
        experiment['workloadEnvelope']['runDurationUs'] = horizon_us
    exp_hash = a.retain_evidence(root, experiment)
    quality = {}
    for c in caps:
        protocol = root/a.ROOT/(c+"-attributes")/(frozen[c]["eventId"]+"-protocol.md")
        protocol.parent.mkdir(parents=True, exist_ok=True)
        protocol.write_text(f"Frozen {experiment['frozenOn']} {exp_hash} {experiment['ledgerHashes'][c]} "
                            f"{experiment['qualityContractHash']} {experiment['operationalContractHash']}\n")
        a.retain_protocol(root, exp_hash, c, protocol.read_bytes())
        evidence = {"schema": a.QUALITY_EVIDENCE_SCHEMA, "experimentSha256": exp_hash, "capability": c,
                    "gateResults": gates(caps[c]), "pairwise": matrix(caps[c]), "partition": "selection"}
        evidence_hash = a.retain_evidence(root, evidence)
        q = a.build_quality(root, exp_hash, c, evidence_hash)
        quality[c] = a.retain_evidence(root, q)
    pair = {"personUnitId": "PC-B0", "vehicleUnitId": "VC-B0"}
    evidence = {"schema": a.OPERATIONAL_EVIDENCE_SCHEMA, "experimentSha256": exp_hash,
                "pairs": [{"pair": pair, "identitySha256": a.runtime_identity(experiment, pair), "lowerServices": {"small": service(), "boundary": service()},
                           "upperServices": {"small": service(), "boundary": service()}, "ramBytesPerHost": 100,
                           "ioBytesPerSecond": 10, "runtimeCompatible": True, "evidenceComplete": True, "e2TraceSha256": "f"*64}]}
    row = evidence["pairs"][0]
    from model_selection.operational_inputs import job_service_shape
    row["serviceCoverage"] = {shape: [job_service_shape(next(j for w in experiment["workloads"] for j in w["jobs"] if j["shape"] == shape))]
                              for shape in ("small", "boundary")}
    trace = {"schema": "mavi-s2c-e2-runner-evidence-v1", "apiMode": "real-platform", "pair": pair,
             "identitySha256": row["identitySha256"], "workerId": "w-00000",
             "attempts": [{"status": "completed", "failureCode": None}],
             "calls": [{"operation": name, "startedAtUtc": T0, "finishedAtUtc": T0,
                        "durationUs": 0, "outcome": "returned"} for name in ("lease", "read_evidence", "upload", "complete")]}
    # Hypothetical evidence in a temporary synthetic repository, never an actual
    # platform measurement or a committed candidate evaluation.
    row["e2TraceSha256"] = a.retain_evidence(root, trace)
    row.update(lowerReadyUs=0, upperReadyUs=0, apiRequestsPerSecond=10,
               footprint={'modelPackBytes':100,'runtimePackBytes':100,'deploymentGrowthBytes':100})
    measurement_sources(a, root, experiment, row)
    evidence_hash = a.retain_evidence(root, evidence)
    joint = a.build_technical(root, exp_hash, quality, evidence_hash)
    return experiment, exp_hash, quality, joint


def test_retained_technical_then_implementation_is_linear_byte_preserving(artefacts, tmp_path):
    exp, eh, q, technical = fixture(artefacts, tmp_path)
    first = artefacts.retain_joint(tmp_path, technical)
    licence = {c: {u["unitId"]: {"dev": "CLEARED"} for u in exp["capabilities"][c]["units"]} for c in ("person", "vehicle")}
    implementation = artefacts.build_implementation(tmp_path, first, exp["ledgerHashes"],
                                                    {"person": "2026-09-01", "vehicle": "2026-09-01"}, licence,
                                                    technical["technicalStage"]["operationalEvidenceSha256"])
    second = artefacts.retain_joint(tmp_path, implementation)
    versions = artefacts.validate_chain(tmp_path, exp["eventPairId"])
    assert len(versions) == 2
    assert versions[second]["technicalStage"] == versions[first]["technicalStage"]
    assert implementation["implementationStage"]["outputs"]["T_impl"] == technical["technicalStage"]["selection"]["T"]
    with pytest.raises(ValueError, match="exists|version|predecessor"): artefacts.retain_joint(tmp_path, technical)


@pytest.mark.parametrize("mutation", ["delete", "rewrite", "hash", "active", "gap", "fork", "stage", "order", "technical"])
def test_chain_refuses_retention_and_index_attacks(artefacts, tmp_path, mutation):
    exp, eh, q, technical = fixture(artefacts, tmp_path)
    first = artefacts.retain_joint(tmp_path, technical)
    licence = {c: {u["unitId"]: {"dev": "CLEARED"} for u in exp["capabilities"][c]["units"]} for c in ("person", "vehicle")}
    doc = artefacts.build_implementation(tmp_path, first, exp["ledgerHashes"], {c: "2026-09-01" for c in licence}, licence,
                                         technical["technicalStage"]["operationalEvidenceSha256"])
    artefacts.retain_joint(tmp_path, doc)
    index_path = tmp_path/artefacts.ROOT/"s2c-joint"/(exp["eventPairId"]+"-joint-index.json")
    index = parse(index_path.read_bytes())
    path = tmp_path/index["versions"][0]["path"]
    if mutation == "delete": path.unlink()
    if mutation == "rewrite": path.write_bytes(canonical({**technical, "eventPairId": "changed"}))
    if mutation == "hash": index["versions"][0]["sha256"] = "0"*64
    if mutation == "active": index["active"] = first
    if mutation == "gap": index["versions"].pop(0)
    if mutation == "fork": index["versions"][1]["supersedes"] = None
    if mutation == "stage": index["versions"][1]["stage"] = "technical"
    if mutation == "order": index["versions"].reverse()
    if mutation == "technical":
        path = tmp_path/index["versions"][1]["path"]
        doc["technicalStage"]["selection"]["T"] = []
        path.write_bytes(canonical(doc))
        index["versions"][1]["sha256"] = sha256(doc)
        index["active"] = sha256(doc)
    index_path.write_bytes(canonical(index))
    with pytest.raises(ValueError): artefacts.validate_chain(tmp_path, exp["eventPairId"])


@pytest.mark.parametrize("mutation", ["quality_hash", "gate_hash", "derived_F", "cycle", "experiment", "unknown"])
def test_artefact_refuses_hash_and_derivation_attacks(artefacts, tmp_path, mutation):
    exp, eh, q, joint = fixture(artefacts, tmp_path)
    if mutation == "quality_hash": joint["qualityResultHashes"]["person"] = "0"*64
    if mutation == "gate_hash":
        quality = artefacts.resolve(tmp_path, q["person"])
        quality["qualityEvidenceSha256"] = "0"*64
        with pytest.raises(ValueError): artefacts.retain_evidence(tmp_path, quality)
        return
    if mutation == "derived_F": joint["technicalStage"]["J_person"] = []
    if mutation == "cycle": joint["eventDecisionHashes"] = {"person": "a"*64}
    if mutation == "experiment": joint["experimentSha256"] = "0"*64
    if mutation == "unknown": joint["surprise"] = True
    with pytest.raises(ValueError): artefacts.validate_joint(tmp_path, joint, predecessor=None)


def decisions(a, root, *, state="TECHNICAL_DECISION_RECORDED"):
    exp, eh, q, technical = fixture(a, root)
    joint_hash = a.retain_joint(root, technical)
    if state != "TECHNICAL_DECISION_RECORDED":
        a.retain_event_pair(root, {c: a.build_event_decision(root, joint_hash, c, "TECHNICAL_DECISION_RECORDED", "2026-09-01", None, None) for c in ("person", "vehicle")})
        licence = {c: {u["unitId"]: {"dev": "CLEARED"} for u in exp["capabilities"][c]["units"]} for c in ("person", "vehicle")}
        impl = a.build_implementation(root, joint_hash, exp["ledgerHashes"], {c: "2026-09-01" for c in licence}, licence,
                                      technical["technicalStage"]["operationalEvidenceSha256"])
        joint_hash = a.retain_joint(root, impl)
    return {c: a.build_event_decision(root, joint_hash, c, state, "2026-09-01", None, None) for c in ("person", "vehicle")}


def test_decision_v2_technical_state_and_nonS2c_v1_boundary(artefacts, tmp_path):
    docs = decisions(artefacts, tmp_path)
    artefacts.validate_event_pair(tmp_path, docs)
    from model_selection import credibility as cred
    from model_selection_fixtures import decision
    frozen = ledger(baseline())
    legacy = decision(frozen, implementation=None)
    with pytest.raises(ValueError, match="s2c_requires_decision_v2"):
        cred.validate_decision(legacy, frozen, frozen)


@pytest.mark.parametrize("mutation", ["early_pair", "early_Tr", "early_Timpl", "premature_outcome", "wrong_stage", "wrong_joint_hash",
                                     "quality_hash", "technical_T", "quality_F", "weighted", "pair_coordinates", "different_pair"])
def test_decision_state_and_exact_pair_refusals(artefacts, tmp_path, mutation):
    docs = decisions(artefacts, tmp_path)
    d = docs["person"]
    if mutation == "early_pair": d["implementationPair"] = {"personUnitId": "PC-B0", "vehicleUnitId": "VC-B0"}
    if mutation == "early_Tr": d["profileClearedSet"] = {}
    if mutation == "early_Timpl": d["implementationEligibleSet"] = []
    if mutation == "premature_outcome": d["outcome"] = "NO_QUALIFIABLE_CANDIDATE"
    if mutation == "wrong_joint_hash": d["jointOperationalDecisionSha256"] = "0"*64
    if mutation == "quality_hash": d["qualityResultSha256"] = "0"*64
    if mutation == "technical_T": d["technicalSelectedSet"] = []
    if mutation == "quality_F": d["qualityAcceptableSet"] = []
    if mutation == "weighted": d["comparativeScore"] = 100
    if mutation == "wrong_stage": d["eventState"] = "QUALIFICATION_PENDING"
    if mutation in ("pair_coordinates", "different_pair"):
        docs = decisions(artefacts, tmp_path/"impl", state="QUALIFICATION_PENDING")
        d = docs["person"]
        d["implementationPair"] = {"personUnitId": "PC-B0", "vehicleUnitId": "MISSING" if mutation == "pair_coordinates" else "VC-B0"}
        d["ownerChoice"] = {"decidedBy": "owner", "rationale": "synthetic choice"}
        with pytest.raises(ValueError): artefacts.validate_event_pair(tmp_path/"impl", docs)
        return
    with pytest.raises(ValueError): artefacts.validate_event_pair(tmp_path, docs)


def test_closed_baseline_pair_outcomes_and_pending_licence_refused(artefacts, tmp_path):
    docs = decisions(artefacts, tmp_path, state="QUALIFICATION_PENDING")
    artefacts.retain_event_pair(tmp_path, docs)
    joint_hash = docs["person"]["jointOperationalDecisionSha256"]
    chosen = {"personUnitId": "PC-B0", "vehicleUnitId": "VC-B0"}
    owner = {"decidedBy": "owner", "rationale": "synthetic owner choice"}
    closed = {c: artefacts.build_event_decision(tmp_path, joint_hash, c, "CLOSED", "2026-09-01", chosen, owner) for c in docs}
    artefacts.validate_event_pair(tmp_path, closed)
    assert {d["outcome"] for d in closed.values()} == {"BASELINE_SELECTED"}
    closed["person"]["outcome"] = "NO_QUALIFIABLE_CANDIDATE"
    with pytest.raises(ValueError): artefacts.validate_event_pair(tmp_path, closed)


def test_schemas_and_repository_checker_are_present_and_synchronised():
    repo = Path(__file__).resolve().parents[3]
    for name in ("mavi-s2c-quality-result-v1", "mavi-s2c-joint-operational-decision-v1", "mavi-s2c-joint-index-v1", "mavi-model-selection-decision-v2"):
        path = repo/"tools/qualification/model_selection/schemas"/(name+".schema.json")
        assert path.is_file(), f"missing schema {name}"
    source = (repo/"tools/verify_repo.py").read_text()
    assert "check_model_selection_protocols(errors)" in source


def test_published_schemas_accept_recomputed_artefacts(artefacts, tmp_path):
    import json
    import jsonschema
    exp, _, qualities, technical = fixture(artefacts, tmp_path)
    first = artefacts.retain_joint(tmp_path, technical)
    licence = {c: {u["unitId"]: {"dev": "CLEARED"} for u in exp["capabilities"][c]["units"]} for c in ("person", "vehicle")}
    implementation = artefacts.build_implementation(tmp_path, first, exp["ledgerHashes"],
                 {c: "2026-09-01" for c in licence}, licence, technical["technicalStage"]["operationalEvidenceSha256"])
    second = artefacts.retain_joint(tmp_path, implementation)
    documents = [artefacts.resolve(tmp_path, q) for q in qualities.values()]+[technical, implementation]
    documents.append(parse((tmp_path/artefacts.ROOT/"s2c-joint"/(exp["eventPairId"]+"-joint-index.json")).read_bytes()))
    initial = {c: artefacts.build_event_decision(tmp_path, first, c, "TECHNICAL_DECISION_RECORDED", "2026-09-01", None, None) for c in ("person", "vehicle")}
    artefacts.retain_event_pair(tmp_path, initial)
    documents += list(initial.values()) + [artefacts.build_event_decision(tmp_path, second, "person", "QUALIFICATION_PENDING", "2026-09-01", None, None)]
    source = Path(__file__).resolve().parents[3]
    for doc in documents:
        schema = json.loads((source/"tools/qualification/model_selection/schemas"/(doc["schema"]+".schema.json")).read_bytes())
        jsonschema.Draft202012Validator(schema).validate(doc)


def test_exact_pair_refused_even_when_both_coordinates_occur(artefacts, tmp_path, monkeypatch):
    docs = decisions(artefacts, tmp_path, state="QUALIFICATION_PENDING")
    joint_hash = docs["person"]["jointOperationalDecisionSha256"]
    joint = artefacts.find_joint(tmp_path, joint_hash)
    joint["implementationStage"]["outputs"]["T_impl"] = [
        {"personUnitId": "P1", "vehicleUnitId": "V1"},
        {"personUnitId": "P2", "vehicleUnitId": "V2"}]
    monkeypatch.setattr(artefacts, "find_joint", lambda *_: joint)
    # Isolate exact-pair membership from retention: this synthetic joint has
    # deliberately changed bytes under the original hash. Real retained-chain
    # continuity is exercised separately without mocking either validator.
    monkeypatch.setattr(artefacts, "_event_predecessor", lambda *_: None)
    with pytest.raises(ValueError, match="exact_pair_not_in_T_impl"):
        artefacts.build_event_decision(tmp_path, joint_hash, "person", "QUALIFICATION_PENDING", "2026-09-01",
            {"personUnitId": "P1", "vehicleUnitId": "V2"}, {"decidedBy": "owner", "rationale": "invalid cross"})


def test_runtime_identity_must_bind_exact_frozen_pair_configuration(artefacts, tmp_path):
    exp, eh, _, joint = fixture(artefacts, tmp_path)
    evidence = artefacts.resolve(tmp_path, joint["technicalStage"]["operationalEvidenceSha256"])
    evidence["pairs"][0]["identitySha256"] = "0"*64
    mutated = artefacts.retain_evidence(tmp_path, evidence)
    with pytest.raises(ValueError, match="runtime_identity"):
        artefacts.operational_measurements(tmp_path, exp, eh, mutated)


def test_quality_result_has_immutable_event_address(artefacts, tmp_path):
    exp, _, qualities, _ = fixture(artefacts, tmp_path)
    for c, identity in qualities.items():
        path = tmp_path/artefacts.ROOT/(c+"-attributes")/(exp["events"][c]+"-quality-result.json")
        assert path.read_bytes() == canonical(artefacts.resolve(tmp_path, identity))


def test_missing_required_workload_role_is_refused(artefacts, tmp_path):
    exp, *_ = fixture(artefacts, tmp_path)
    exp["workloads"] = exp["workloads"][:1]
    exp["requiredWorkloadIds"] = [exp["workloads"][0]["workloadId"]]
    with pytest.raises(ValueError, match="workload.*family"):
        artefacts.validate_experiment(tmp_path, exp)


def test_e2_reference_requires_retained_matching_real_runner_trace(artefacts, tmp_path):
    exp, eh, _, joint = fixture(artefacts, tmp_path)
    evidence = artefacts.resolve(tmp_path, joint["technicalStage"]["operationalEvidenceSha256"])
    row = evidence["pairs"][0]
    row["e2TraceSha256"] = "0"*64
    h = artefacts.retain_evidence(tmp_path, evidence)
    with pytest.raises(ValueError): artefacts.operational_measurements(tmp_path, exp, eh, h)


def test_incomplete_operational_evidence_is_reportable_without_host_claim(artefacts, tmp_path):
    exp, eh, q, joint = fixture(artefacts, tmp_path)
    evidence = artefacts.resolve(tmp_path, joint["technicalStage"]["operationalEvidenceSha256"])
    row = evidence["pairs"][0]
    row["evidenceComplete"] = False
    for k in set(row)-{"pair", "identitySha256", "evidenceComplete"}: row[k] = None
    h = artefacts.retain_evidence(tmp_path, evidence)
    result = artefacts.build_technical(tmp_path, eh, q, h)
    assert result["technicalStage"]["selection"]["outcome"] == "TECHNICAL_EVIDENCE_INCOMPLETE"
    assert result["technicalStage"]["selection"]["T"] == []


def test_pending_implementation_can_resolve_licence_without_reopening_technical(artefacts, tmp_path):
    exp, _, _, technical = fixture(artefacts, tmp_path)
    first = artefacts.retain_joint(tmp_path, technical)
    licence = {c: {u["unitId"]: {"dev": "REVIEW_PENDING"} for u in exp["capabilities"][c]["units"]} for c in ("person", "vehicle")}
    pending = artefacts.build_implementation(tmp_path, first, exp["ledgerHashes"], {c: "2026-09-01" for c in licence},
                licence, technical["technicalStage"]["operationalEvidenceSha256"])
    second = artefacts.retain_joint(tmp_path, pending)
    for c in licence:
        for u in licence[c]: licence[c][u]["dev"] = "CLEARED"
    resolved = artefacts.build_implementation(tmp_path, second, exp["ledgerHashes"], {c: "2026-09-02" for c in licence},
                licence, technical["technicalStage"]["operationalEvidenceSha256"])
    third = artefacts.retain_joint(tmp_path, resolved)
    assert len(artefacts.validate_chain(tmp_path, exp["eventPairId"])) == 3
    assert canonical(resolved["technicalStage"]) == canonical(technical["technicalStage"])
    assert resolved["implementationStage"]["outputs"]["T_impl"] == technical["technicalStage"]["selection"]["T"]
    assert resolved["supersedes"] == second and third != second


def test_earlier_event_pair_versions_cannot_be_deleted_together_with_renumbering(artefacts, tmp_path):
    docs = decisions(artefacts, tmp_path)
    artefacts.retain_event_pair(tmp_path, docs)
    first = docs["person"]["jointOperationalDecisionSha256"]
    technical = artefacts.find_joint(tmp_path, first)
    exp = artefacts.resolve(tmp_path, technical["experimentSha256"])
    licence = {c: {u["unitId"]: {"dev": "CLEARED"} for u in exp["capabilities"][c]["units"]} for c in ("person", "vehicle")}
    implementation = artefacts.build_implementation(tmp_path, first, exp["ledgerHashes"], {c: "2026-09-01" for c in licence},
                  licence, technical["technicalStage"]["operationalEvidenceSha256"])
    second = artefacts.retain_joint(tmp_path, implementation)
    later = {c: artefacts.build_event_decision(tmp_path, second, c, "QUALIFICATION_PENDING", "2026-09-01", None, None) for c in docs}
    artefacts.retain_event_pair(tmp_path, later)
    eid = exp["events"]["vehicle"]
    directory = tmp_path/artefacts.ROOT/"vehicle-attributes"
    (directory/(eid+"-decision-v1.json")).unlink()
    (directory/(eid+"-decision-v2.json")).rename(directory/(eid+"-decision-v1.json"))
    with pytest.raises(ValueError): artefacts.validate_repository(tmp_path)


def test_closed_cannot_hide_available_implementation(artefacts, tmp_path):
    docs = decisions(artefacts, tmp_path, state='QUALIFICATION_PENDING')
    artefacts.retain_event_pair(tmp_path, docs)
    with pytest.raises(ValueError, match='implementation_available'):
        artefacts.build_event_decision(tmp_path, docs['person']['jointOperationalDecisionSha256'], 'person', 'CLOSED', '2026-09-01', None, None)


def test_decision_cannot_predate_frozen_experiment(artefacts, tmp_path):
    docs = decisions(artefacts, tmp_path)
    with pytest.raises(ValueError, match='before_freeze'):
        artefacts.build_event_decision(tmp_path, docs['person']['jointOperationalDecisionSha256'], 'person', 'TECHNICAL_DECISION_RECORDED', '2026-01-01', None, None)


def test_raw_operational_evidence_cannot_change_with_unchanged_host_result(artefacts, tmp_path):
    exp, eh, q, technical = fixture(artefacts, tmp_path)
    first = artefacts.retain_joint(tmp_path, technical)
    evidence = artefacts.resolve(tmp_path, technical['technicalStage']['operationalEvidenceSha256'])
    evidence['pairs'][0]['ramBytesPerHost'] = 900
    revised = artefacts.retain_evidence(tmp_path, evidence)
    licence = {c: {u['unitId']: {'dev': 'CLEARED'} for u in exp['capabilities'][c]['units']} for c in ('person','vehicle')}
    with pytest.raises(ValueError, match='technical_operational_evidence_changed'):
        artefacts.build_implementation(tmp_path, first, exp['ledgerHashes'], {c:'2026-09-01' for c in licence}, licence, revised)


def test_current_protocol_changes_cannot_rewrite_historical_quality(artefacts, tmp_path):
    exp, eh, q, technical = fixture(artefacts, tmp_path)
    current = tmp_path/artefacts.ROOT/'person-attributes'/(exp['events']['person']+'-protocol.md')
    current.write_text('A later protocol revision.\n')
    artefacts.validate_quality(tmp_path, artefacts.resolve(tmp_path, q['person']))


def test_deleting_both_predecessor_events_and_renaming_does_not_hide_gap(artefacts, tmp_path):
    docs = decisions(artefacts, tmp_path, state='QUALIFICATION_PENDING')
    artefacts.retain_event_pair(tmp_path, docs)
    for c, doc in docs.items():
        directory = tmp_path/artefacts.ROOT/(c+'-attributes')
        (directory/(doc['eventId']+'-decision-v1.json')).unlink()
        (directory/(doc['eventId']+'-decision-v2.json')).rename(directory/(doc['eventId']+'-decision-v1.json'))
    with pytest.raises(ValueError): artefacts.validate_repository(tmp_path)


def install_active_ledgers(a, root, docs):
    from model_selection import credibility as cred
    for c, doc in docs.items():
        directory = root/a.ROOT/(c+'-attributes')
        frozen = a.resolve(root, doc['frozenLedgerSha256'])
        for suffix in (cred.LEDGER_SUFFIX, cred.FROZEN_SUFFIX):
            (directory/(doc['eventId']+suffix)).write_bytes(canonical(frozen))
        record = directory/(doc['eventId']+'.md')
        hashes = [cred.lf_normalised_sha256(directory/(doc['eventId']+cred.PROTOCOL_SUFFIX)), sha256(doc)]
        if doc['ledgerSha256']:
            snapshot = a.resolve(root, doc['ledgerSha256'])
            (directory/(doc['eventId']+cred.SNAPSHOT_SUFFIX)).write_bytes(canonical(snapshot))
            hashes.append(sha256(snapshot))
        record.write_text('\n'.join(hashes)+'\n')


@pytest.mark.parametrize('mutation', ['scope','frozen','record','snapshot','working'])
def test_v2_active_repository_binding_cannot_bypass_m1(artefacts, tmp_path, mutation):
    from model_selection import credibility as cred
    docs = decisions(artefacts, tmp_path, state='QUALIFICATION_PENDING')
    artefacts.retain_event_pair(tmp_path, docs)
    install_active_ledgers(artefacts, tmp_path, docs)
    cred.validate_repository(tmp_path)
    d = docs['person']; directory = tmp_path/artefacts.ROOT/'person-attributes'
    if mutation == 'scope':
        d['eventId'] = docs['vehicle']['eventId']
        (directory/(docs['person']['eventId']+cred.DECISION_SUFFIX)).write_bytes(canonical(d))
    if mutation == 'record': (directory/(d['eventId']+'.md')).write_text('omitted hashes\n')
    if mutation in ('snapshot','working','frozen'):
        suffix = {'snapshot':cred.SNAPSHOT_SUFFIX,'working':cred.LEDGER_SUFFIX,'frozen':cred.FROZEN_SUFFIX}[mutation]
        path = directory/(d['eventId']+suffix)
        value = parse(path.read_bytes()); value['candidates'][0]['maviRevision'] = 'rewritten'
        path.write_bytes(canonical(value))
    with pytest.raises(ValueError): cred.validate_repository(tmp_path)


def test_host_profile_reference_must_resolve_and_match_class(artefacts, tmp_path):
    exp, *_ = fixture(artefacts, tmp_path)
    exp['hostProfileSha256'] = '0'*64
    with pytest.raises(ValueError): artefacts.validate_experiment(tmp_path, exp)


def test_operational_projection_retains_required_views(artefacts, tmp_path):
    _, _, _, joint = fixture(artefacts, tmp_path)
    reports = joint['technicalStage']['projectionReports']
    assert reports and {r['bound'] for r in reports} == {'lower','upper'}
    metrics = reports[0]['workloads'][0]
    assert {'queueToPublicationUs','claimToPhaseAUs','claimToPublicationUs','publicationToAcknowledgementUs',
            'waitingJobs','unfinishedTracks','oldestQueueAgeUs','retriedJobs','phaseADeadlineMisses','ownerSlaMisses','drainAtUtc'} <= metrics.keys()


def test_cold_start_and_footprint_are_operational_admission_constraints(artefacts, tmp_path):
    exp, eh, q, joint = fixture(artefacts, tmp_path)
    evidence = artefacts.resolve(tmp_path, joint['technicalStage']['operationalEvidenceSha256'])
    row = evidence['pairs'][0]
    assert {'lowerReadyUs','upperReadyUs','footprint','measurementReferences'} <= row.keys()
    row['lowerReadyUs'] = row['upperReadyUs'] = 25_000_000
    measurement_sources(artefacts, tmp_path, exp, row)
    result = artefacts.build_technical(tmp_path, eh, q, artefacts.retain_evidence(tmp_path, evidence))
    assert result['technicalStage']['selection']['T'] == []
    assert result['technicalStage']['measurements'][0]['constraints']['cold'] is False


def test_measurement_provenance_cannot_be_a_bare_hash(artefacts, tmp_path):
    exp, eh, _, joint = fixture(artefacts, tmp_path)
    evidence = artefacts.resolve(tmp_path, joint['technicalStage']['operationalEvidenceSha256'])
    assert 'measurementReferences' in evidence['pairs'][0]
    evidence['pairs'][0]['measurementReferences']['resources'] = '0'*64
    with pytest.raises(ValueError): artefacts.operational_measurements(tmp_path, exp, eh, artefacts.retain_evidence(tmp_path, evidence))


def technical_revision(a, root, predecessor, *, horizon_us):
    previous = a.find_joint(root, predecessor)
    _, _, _, revised = fixture(a, root, event_pair_id=previous['eventPairId'], horizon_us=horizon_us)
    revised['version'] = previous['version']+1
    revised['supersedes'] = predecessor
    revised['revision'] = {
        'number': 1 if previous['revision'] is None else previous['revision']['number']+1,
        'reason': 'Synthetic fresh engineering workload revision', 'changes': ['workload'],
        'freshEvaluationBasisSha256': a.retain_evidence(root, {'schema':'synthetic-fresh-basis', 'horizonUs':horizon_us})}
    return revised


def technical_decisions(a, root, joint_hash):
    return {c: a.build_event_decision(root, joint_hash, c, 'TECHNICAL_DECISION_RECORDED', '2026-09-01', None, None)
            for c in ('person', 'vehicle')}


def test_repeated_technical_decision_rejects_unrelated_retained_chain(artefacts, tmp_path):
    initial = decisions(artefacts, tmp_path)
    artefacts.retain_event_pair(tmp_path, initial)
    _, _, _, unrelated = fixture(artefacts, tmp_path, event_pair_id='msr-unrelated-2026-01')
    unrelated_hash = artefacts.retain_joint(tmp_path, unrelated)
    # Both chains and their original event IDs are individually valid. The attack
    # must fail specifically because event history cannot jump between them.
    artefacts.validate_chain(tmp_path, unrelated['eventPairId'])
    with pytest.raises(ValueError, match='joint_continuity'):
        later = technical_decisions(artefacts, tmp_path, unrelated_hash)
        artefacts.retain_event_pair(tmp_path, later)
        artefacts.validate_repository(tmp_path)


def test_repeated_technical_decision_accepts_unchanged_retained_reference(artefacts, tmp_path):
    initial = decisions(artefacts, tmp_path)
    artefacts.retain_event_pair(tmp_path, initial)
    later = technical_decisions(artefacts, tmp_path, initial['person']['jointOperationalDecisionSha256'])
    artefacts.retain_event_pair(tmp_path, later)
    artefacts.validate_repository(tmp_path)
    assert later['person']['decisionVersion'] == 2
    assert later['person']['supersedesEventDecisionSha256'] == sha256(initial['person'])


def test_repeated_technical_decision_accepts_immediate_retained_revision(artefacts, tmp_path):
    initial = decisions(artefacts, tmp_path)
    artefacts.retain_event_pair(tmp_path, initial)
    original = initial['person']['jointOperationalDecisionSha256']
    revised = technical_revision(artefacts, tmp_path, original, horizon_us=61_000_000)
    revised_hash = artefacts.retain_joint(tmp_path, revised)
    later = technical_decisions(artefacts, tmp_path, revised_hash)
    artefacts.retain_event_pair(tmp_path, later)
    artefacts.validate_repository(tmp_path)
    assert revised['supersedes'] == original and revised['version'] == 2
    assert later['person']['jointOperationalDecisionSha256'] == revised_hash


def test_repeated_technical_decision_rejects_skipping_valid_retained_revision(artefacts, tmp_path):
    initial = decisions(artefacts, tmp_path)
    artefacts.retain_event_pair(tmp_path, initial)
    original = initial['person']['jointOperationalDecisionSha256']
    second = artefacts.retain_joint(tmp_path, technical_revision(artefacts, tmp_path, original, horizon_us=61_000_000))
    third = artefacts.retain_joint(tmp_path, technical_revision(artefacts, tmp_path, second, horizon_us=62_000_000))
    artefacts.validate_chain(tmp_path, 'msr-synthetic-2026-01')
    with pytest.raises(ValueError, match='joint_continuity'):
        technical_decisions(artefacts, tmp_path, third)


@pytest.mark.parametrize('attack', ['fork', 'skip', 'fabricated'])
def test_repeated_technical_decision_refuses_fabricated_retained_lineage(artefacts, tmp_path, attack):
    initial = decisions(artefacts, tmp_path)
    artefacts.retain_event_pair(tmp_path, initial)
    original = initial['person']['jointOperationalDecisionSha256']
    revised = technical_revision(artefacts, tmp_path, original, horizon_us=61_000_000)
    if attack == 'fork': revised['version'] = 1
    if attack == 'skip': revised['version'] = 3
    if attack == 'fabricated': revised['supersedes'] = '0'*64
    directory = tmp_path/artefacts.ROOT/'s2c-joint'
    path = directory/f"{revised['eventPairId']}-joint-technical-v{revised['version']}.json"
    if attack == 'fork': path = directory/f"{revised['eventPairId']}-joint-implementation-v1.json"
    path.write_bytes(canonical(revised))
    identity = sha256(revised)
    index_path = directory/(revised['eventPairId']+'-joint-index.json')
    index = parse(index_path.read_bytes())
    index['versions'].append({'path':path.relative_to(tmp_path).as_posix(), 'stage':revised['stage'], 'sha256':identity, 'supersedes':revised['supersedes']})
    index['active'] = identity
    index_path.write_bytes(canonical(index))
    with pytest.raises(ValueError): technical_decisions(artefacts, tmp_path, identity)


def test_repository_refuses_preexisting_cross_chain_technical_event_versions(artefacts, tmp_path, monkeypatch):
    initial = decisions(artefacts, tmp_path)
    artefacts.retain_event_pair(tmp_path, initial)
    _, _, _, unrelated = fixture(artefacts, tmp_path, event_pair_id='msr-unrelated-2026-01')
    unrelated_hash = artefacts.retain_joint(tmp_path, unrelated)
    # Simulate documents written by the vulnerable producer. Only the event
    # continuity guard is bypassed during fixture construction; canonical bytes,
    # derived outputs, joint files and indexes retain their normal validity.
    with monkeypatch.context() as producer:
        producer.setattr(artefacts, '_event_predecessor', lambda *args: None)
        artefacts.retain_event_pair(tmp_path, technical_decisions(artefacts, tmp_path, unrelated_hash))
    for eid in ('msr-synthetic-2026-01', 'msr-unrelated-2026-01'):
        artefacts.validate_chain(tmp_path, eid)
    with pytest.raises(ValueError, match='joint_continuity'):
        artefacts.validate_repository(tmp_path)


def test_reopening_qualification_accepts_immediate_retained_technical_revision(artefacts, tmp_path):
    pending = decisions(artefacts, tmp_path, state='QUALIFICATION_PENDING')
    artefacts.retain_event_pair(tmp_path, pending)
    old = pending['person']['jointOperationalDecisionSha256']
    revised = technical_revision(artefacts, tmp_path, old, horizon_us=61_000_000)
    new = artefacts.retain_joint(tmp_path, revised)
    later = technical_decisions(artefacts, tmp_path, new)
    artefacts.retain_event_pair(tmp_path, later)
    artefacts.validate_repository(tmp_path)
    assert later['person']['decisionVersion'] == 3


def implementation_revision(a, root, predecessor, *, decided_on='2026-09-01'):
    prior = a.find_joint(root, predecessor)
    exp = a.resolve(root, prior['experimentSha256'])
    licence = {c: {u['unitId']: {'dev':'CLEARED'} for u in exp['capabilities'][c]['units']} for c in ('person','vehicle')}
    return a.build_implementation(root, predecessor, exp['ledgerHashes'], {c:decided_on for c in licence}, licence,
                                  prior['technicalStage']['operationalEvidenceSha256'])


def test_qualification_transition_rejects_unrelated_retained_chain(artefacts, tmp_path):
    initial = decisions(artefacts, tmp_path)
    artefacts.retain_event_pair(tmp_path, initial)
    _, _, _, unrelated = fixture(artefacts, tmp_path, event_pair_id='msr-unrelated-2026-01')
    first = artefacts.retain_joint(tmp_path, unrelated)
    other_impl = artefacts.retain_joint(tmp_path, implementation_revision(artefacts, tmp_path, first))
    artefacts.validate_chain(tmp_path, unrelated['eventPairId'])
    with pytest.raises(ValueError, match='joint_continuity'):
        later = {c: artefacts.build_event_decision(tmp_path, other_impl, c, 'QUALIFICATION_PENDING', '2026-09-01', None, None)
                 for c in ('person','vehicle')}
        artefacts.retain_event_pair(tmp_path, later)
        artefacts.validate_repository(tmp_path)


def test_implementation_reference_accepts_each_immediate_retained_version(artefacts, tmp_path):
    pending = decisions(artefacts, tmp_path, state='QUALIFICATION_PENDING')
    artefacts.retain_event_pair(tmp_path, pending)
    prior = pending['person']['jointOperationalDecisionSha256']
    for _ in range(2):
        successor = artefacts.retain_joint(tmp_path, implementation_revision(artefacts, tmp_path, prior))
        later = {c: artefacts.build_event_decision(tmp_path, successor, c, 'QUALIFICATION_PENDING', '2026-09-01', None, None)
                 for c in ('person','vehicle')}
        artefacts.retain_event_pair(tmp_path, later)
        artefacts.validate_repository(tmp_path)
        assert artefacts.find_joint(tmp_path, successor)['supersedes'] == prior
        prior = successor


def test_implementation_reference_rejects_backward_progress_within_same_chain(artefacts, tmp_path):
    pending = decisions(artefacts, tmp_path, state='QUALIFICATION_PENDING')
    artefacts.retain_event_pair(tmp_path, pending)
    old = pending['person']['jointOperationalDecisionSha256']
    new = artefacts.retain_joint(tmp_path, implementation_revision(artefacts, tmp_path, old))
    later = {c: artefacts.build_event_decision(tmp_path, new, c, 'QUALIFICATION_PENDING', '2026-09-01', None, None)
             for c in ('person','vehicle')}
    artefacts.retain_event_pair(tmp_path, later)
    with pytest.raises(ValueError, match='joint_continuity'):
        artefacts.build_event_decision(tmp_path, old, 'person', 'QUALIFICATION_PENDING', '2026-09-01', None, None)


def test_qualification_cannot_skip_unrecorded_technical_revision(artefacts, tmp_path):
    initial = decisions(artefacts, tmp_path)
    artefacts.retain_event_pair(tmp_path, initial)
    original = initial['person']['jointOperationalDecisionSha256']
    revised = artefacts.retain_joint(tmp_path, technical_revision(artefacts, tmp_path, original, horizon_us=61_000_000))
    implementation = artefacts.retain_joint(tmp_path, implementation_revision(artefacts, tmp_path, revised))
    artefacts.validate_chain(tmp_path, 'msr-synthetic-2026-01')
    with pytest.raises(ValueError, match='joint_continuity'):
        artefacts.build_event_decision(tmp_path, implementation, 'person', 'QUALIFICATION_PENDING', '2026-09-01', None, None)


@pytest.mark.parametrize("incomplete", [True, False])
def test_closed_distinguishes_unresolved_from_established_infeasibility(artefacts, tmp_path, incomplete):
    exp, eh, quality, technical = fixture(artefacts, tmp_path)
    evidence = artefacts.resolve(tmp_path, technical["technicalStage"]["operationalEvidenceSha256"])
    row = evidence["pairs"][0]
    if incomplete:
        row["evidenceComplete"] = False
        for k in set(row)-{"pair", "identitySha256", "evidenceComplete"}: row[k] = None
    else:
        row["runtimeCompatible"] = False
        measurement_sources(artefacts, tmp_path, exp, row)
    evidence_hash = artefacts.retain_evidence(tmp_path, evidence)
    technical = artefacts.build_technical(tmp_path, eh, quality, evidence_hash)
    first = artefacts.retain_joint(tmp_path, technical)
    artefacts.retain_event_pair(tmp_path, technical_decisions(artefacts, tmp_path, first))
    implementation = artefacts.retain_joint(tmp_path, implementation_revision(artefacts, tmp_path, first))
    pending = {c: artefacts.build_event_decision(tmp_path, implementation, c, "QUALIFICATION_PENDING", "2026-09-01", None, None)
               for c in ("person", "vehicle")}
    artefacts.retain_event_pair(tmp_path, pending)
    assert pending["person"]["outcome"] is None
    if incomplete:
        with pytest.raises(ValueError, match="unresolved_operational"):
            artefacts.build_event_decision(tmp_path, implementation, "person", "CLOSED", "2026-09-01", None, None)
    else:
        closed = {c: artefacts.build_event_decision(tmp_path, implementation, c, "CLOSED", "2026-09-01", None, None)
                  for c in ("person", "vehicle")}
        artefacts.retain_event_pair(tmp_path, closed)
        artefacts.validate_repository(tmp_path)
        assert closed["person"]["outcome"] == "NO_QUALIFIABLE_CANDIDATE"


@pytest.mark.parametrize("attack", ["histogram", "omitted-heavy", "backlog", "busy", "crop", "evidence"])
def test_frozen_envelope_refuses_unrepresented_job_population(artefacts, tmp_path, attack):
    from model_selection.operational_inputs import workload_envelope
    exp, _, _, _ = fixture(artefacts, tmp_path)
    envelope = exp["workloadEnvelope"]
    trace = next(w for w in exp["workloads"] if w["role"] == "500-camera")
    if attack in ("histogram", "omitted-heavy"):
        envelope["tracksPerJob"]["person"] = [{"minimum":10,"maximum":10,"count":1},
                                               {"minimum":10000,"maximum":10000,"count":999 if attack == "histogram" else 1}]
    if attack == "backlog":
        envelope["initialBacklog"] = 1
        trace["jobs"].append({**copy.deepcopy(trace["jobs"][0]), "id":"backlog", "personTracks":5, "cropsPerTrack":{"person":[1]*5,"vehicle":[]},
                              "queuedAtUtc":"2026-08-31T23:59:59.000000Z"})
    if attack == "busy":
        envelope["correlatedBusyPeriods"] = [{"startOffsetUs":1_000_000,"endOffsetUs":2_000_000,"classes":["small"]}]
    if attack == "crop": envelope["cropsPerTrack"][0]["count"] += 1
    if attack == "evidence": envelope["evidenceSetBytes"][0]["count"] += 1
    with pytest.raises(ValueError, match="envelope:"):
        workload_envelope(envelope, exp["workloads"])


@pytest.mark.parametrize("field", ["personTracks", "cropsPerTrack", "evidenceSetBytes"])
def test_service_coverage_refuses_unmeasured_payload(artefacts, tmp_path, field):
    exp, eh, _, joint = fixture(artefacts, tmp_path)
    evidence = artefacts.resolve(tmp_path, joint["technicalStage"]["operationalEvidenceSha256"])
    row = evidence["pairs"][0]
    signature = row["serviceCoverage"]["small"][0]
    if field == "personTracks":
        signature[field] = 9
        signature["cropsPerTrack"]["person"].pop()
    elif field == "cropsPerTrack": signature[field]["person"][-1] = 2
    else: signature[field] = 9
    measurement_sources(artefacts, tmp_path, exp, row)
    with pytest.raises(ValueError, match="serviceCoverage:unmeasured_job_shape"):
        artefacts.operational_measurements(tmp_path, exp, eh, artefacts.retain_evidence(tmp_path, evidence))


def test_backlog_histogram_and_synchronized_busy_release_can_be_established(artefacts, tmp_path):
    from model_selection.operational_inputs import workload_envelope
    exp, _, _, _ = fixture(artefacts, tmp_path)
    trace = next(w for w in exp["workloads"] if w["role"] == "500-camera")
    envelope = exp["workloadEnvelope"]
    trace["jobs"].append({**copy.deepcopy(trace["jobs"][0]), "id":"backlog", "queuedAtUtc":"2026-08-31T23:59:59.000000Z"})
    envelope["initialBacklog"] = 1
    for c in ("person", "vehicle"): envelope["tracksPerJob"][c][0]["count"] = 2
    envelope["cropsPerTrack"][0]["count"] = 20
    envelope["evidenceSetBytes"][0]["count"] = 2
    envelope["correlatedBusyPeriods"] = [{"startOffsetUs":0,"endOffsetUs":1_000_000,"classes":["small"]}]
    workload_envelope(envelope, exp["workloads"])



def test_payload_coverage_refuses_ambiguous_cross_capability_crops():
    from model_selection.operational_inputs import job_service_shape
    with pytest.raises(ValueError, match="envelope:crops"):
        job_service_shape({"personTracks":1,"vehicleTracks":1,"cropsPerTrack":[1,5],"evidenceSetBytes":10})



def test_cross_capability_crop_allocation_requires_distinct_service_coverage():
    from model_selection.operational_inputs import service_coverage
    person_heavy = {"personTracks":1,"vehicleTracks":1,"cropsPerTrack":{"person":[5],"vehicle":[1]},"evidenceSetBytes":10}
    vehicle_heavy = {**person_heavy, "cropsPerTrack":{"person":[1],"vehicle":[5]}}
    with pytest.raises(ValueError, match="unmeasured_job_shape"):
        service_coverage({"mixed":[person_heavy]}, [{"jobs":[{**vehicle_heavy,"shape":"mixed"}]}])
    service_coverage({"mixed":[vehicle_heavy]}, [{"jobs":[{**vehicle_heavy,"shape":"mixed"}]}])


@pytest.mark.parametrize("field", ["cropsPerTrack", "evidenceSetBytes"])
def test_trace_payload_cannot_outgrow_measured_service_signature(artefacts, tmp_path, field):
    exp, _, _, joint = fixture(artefacts, tmp_path)
    job = exp["workloads"][0]["jobs"][0]
    if field == "cropsPerTrack": job[field]["person"][-1] = 2
    else: job[field] = 11
    exp_hash = artefacts.retain_evidence(tmp_path, exp)
    evidence = artefacts.resolve(tmp_path, joint["technicalStage"]["operationalEvidenceSha256"])
    evidence["experimentSha256"] = exp_hash
    with pytest.raises(ValueError, match="unmeasured_job_shape"):
        artefacts.operational_measurements(tmp_path, exp, exp_hash, artefacts.retain_evidence(tmp_path, evidence))


def test_mixed_unresolved_joint_cannot_name_or_implement_partial_winner(artefacts, tmp_path):
    exp, _, _, original = fixture(artefacts, tmp_path)
    person = exp["capabilities"]["person"]
    person["units"].append({**copy.deepcopy(person["units"][0]), "unitId":"PC-ALT"})
    person["units"].sort(key=lambda u:u["unitId"])
    person["simultaneousFamily"] = [{"a":a,"b":b,"claimId":"colour"} for a,b in (("PC-ALT","PC-B0"),("PC-B0","PC-ALT"))]
    exp_hash = artefacts.retain_evidence(tmp_path, exp)
    quality = {}
    for c in ("person","vehicle"):
        protocol = f"Frozen {exp['frozenOn']} {exp_hash} {exp['ledgerHashes'][c]} {exp['qualityContractHash']} {exp['operationalContractHash']}\n".encode()
        artefacts.retain_protocol(tmp_path, exp_hash, c, protocol)
        quality_evidence = {"schema":artefacts.QUALITY_EVIDENCE_SCHEMA,"experimentSha256":exp_hash,"capability":c,
                            "gateResults":gates(exp["capabilities"][c]),"pairwise":matrix(exp["capabilities"][c]),"partition":"selection"}
        quality[c] = artefacts.retain_evidence(tmp_path, artefacts.build_quality(tmp_path, exp_hash, c, artefacts.retain_evidence(tmp_path, quality_evidence)))
    evidence = artefacts.resolve(tmp_path, original["technicalStage"]["operationalEvidenceSha256"])
    evidence["experimentSha256"] = exp_hash
    pair = {"personUnitId":"PC-ALT","vehicleUnitId":"VC-B0"}
    incomplete = {k:None for k in evidence["pairs"][0]}
    incomplete.update(pair=pair,identitySha256=artefacts.runtime_identity(exp,pair),evidenceComplete=False)
    evidence["pairs"].insert(0,incomplete)
    evidence_hash = artefacts.retain_evidence(tmp_path,evidence)
    technical = artefacts.build_technical(tmp_path,exp_hash,quality,evidence_hash)
    first = artefacts.retain_joint(tmp_path,technical)
    initial = technical_decisions(artefacts,tmp_path,first)
    assert initial["person"]["technicalWinner"] is None
    assert initial["person"]["technicalSelectionOutcome"] == "TECHNICAL_EVIDENCE_INCOMPLETE"
    artefacts.retain_event_pair(tmp_path,initial)
    implementation = artefacts.retain_joint(tmp_path,implementation_revision(artefacts,tmp_path,first))
    with pytest.raises(ValueError, match="unresolved_operational_implementation"):
        artefacts.build_event_decision(tmp_path,implementation,"person","QUALIFICATION_PENDING","2026-09-01",
                                      {"personUnitId":"PC-B0","vehicleUnitId":"VC-B0"}, {"decidedBy":"owner","rationale":"partial winner"})
