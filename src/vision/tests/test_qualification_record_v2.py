from __future__ import annotations

import pytest

from mavi_vision.runtime.manifest import ReleaseMetadataError
from mavi_vision.runtime.qualification_v2 import parse_capability_gate_sets, parse_qualification_record_v2
from tests.component_binding_v2_fixtures import baseline, gate_sets

EVIDENCE = {"kind": "workflow", "reference": "run-1", "sha256": "e" * 64}
COMMON = ("offline-install", "licence", "startup-readiness", "runtime-compatibility", "bounded-failure-recovery", "provenance-completeness")
DETECTOR = ("detection-tracking-accuracy", "cctv-quality-baseline", "recovery-performance")


def _code(document) -> str:
    with pytest.raises(ReleaseMetadataError) as error:
        parse_qualification_record_v2(document, gate_sets=gate_sets())
    return error.value.code


def _pass_variant(document: dict, variant: str) -> None:
    entry = document["variants"][variant]
    entry["gates"] = {gate: "passed" for gate in entry["gates"]}
    entry["status"] = "passed"
    document["evidence"][variant] = {gate: dict(EVIDENCE) for gate in entry["gates"]}


def test_generated_rtmdet_record_is_pending_everywhere_and_capability_scoped() -> None:
    record = parse_qualification_record_v2(baseline("qualification"), gate_sets=gate_sets())
    assert record.capability_id == "detector"
    assert record.overall_result == "pending"
    assert record.gate_set_ids == ("common-v1", "detector-v1")
    assert all(v.status == "pending" and set(v.gates.values()) == {"pending"} for v in record.variants.values())
    assert record.variants["linux-x86_64-cuda"].runtime_pack_id is None
    assert all(record.variants[v].runtime_pack_id for v in ("windows-x86_64-cpu", "linux-x86_64-cpu", "windows-x86_64-cuda"))
    assert set(record.variants["windows-x86_64-cpu"].gates) == set(COMMON) | set(DETECTOR)
    assert record.supersedes_qualification_id == "rtmdet-m-coco-phase1-v1"


def test_gate_names_are_capability_gates_not_variant_names() -> None:
    record = parse_qualification_record_v2(baseline("qualification"), gate_sets=gate_sets())
    for variant in record.variants.values():
        assert not set(variant.gates) & set(record.variants)


def test_a_fully_evidenced_deployable_variant_may_pass() -> None:
    document = baseline("qualification")
    _pass_variant(document, "windows-x86_64-cpu")
    record = parse_qualification_record_v2(document, gate_sets=gate_sets())
    assert record.variants["windows-x86_64-cpu"].status == "passed"
    assert record.overall_result == "pending"


@pytest.mark.parametrize(("mutate", "code"), [
    (lambda d: d["variants"].pop("linux-x86_64-cuda"), "qualification_variant_missing:linux-x86_64-cuda"),
    (lambda d: d["variants"].update({"linux-arm64-cuda": dict(d["variants"]["linux-x86_64-cuda"])}), "qualification_variant_unknown:linux-arm64-cuda"),
    (lambda d: d["variants"]["windows-x86_64-cpu"]["gates"].pop("licence"), "qualification_variant_gates_mismatch:windows-x86_64-cpu"),
    (lambda d: d["variants"]["windows-x86_64-cpu"]["gates"].update({"windows-offline-install": "pending"}), "qualification_variant_gates_mismatch:windows-x86_64-cpu"),
    (lambda d: d.update(gateSetIds=["common-v1", "attributes-v1"]), "qualification_gate_set_unknown:attributes-v1"),
    (lambda d: d.update(gateSetIds=["common-v1", "common-v1"]), "qualification_gate_sets_invalid"),
    (lambda d: d["variants"]["windows-x86_64-cpu"].update(status="passed"), "qualification_variant_status_mismatch:windows-x86_64-cpu"),
    (lambda d: d.update(overallResult="passed"), "qualification_overall_result_mismatch"),
    (lambda d: d["variants"]["windows-x86_64-cpu"]["gates"].update(licence="passed"), "qualification_passed_gate_missing_evidence:windows-x86_64-cpu:licence"),
    (lambda d: d["evidence"].update({"windows-x86_64-cpu": {"licence": dict(EVIDENCE)}}), "qualification_evidence_for_pending_gate:windows-x86_64-cpu:licence"),
    (lambda d: d["variants"]["windows-x86_64-cpu"].update(runtimePackId="mavi-runtime-v1-" + "0" * 64), "qualification_runtime_pack_id_invalid"),
    (lambda d: d.update(modelPackId="mavi-model-v1-" + "0" * 64), "qualification_model_pack_id_invalid"),
    (lambda d: d.update(capabilityId="face-recognition"), "capability_unknown:face-recognition"),
    (lambda d: d.update(qualificationRecordId=d.pop("qualificationId")), "qualification_record_invalid"),
    (lambda d: d.update(requiredGates={}), "qualification_record_invalid"),
    (lambda d: d.update(checkpointSha256="0" * 64), "qualification_record_invalid"),
    (lambda d: d.update(qualifiedProfiles=["P3"]), "qualification_profile_index_mismatch"),
])
def test_record_rules_fail_closed(mutate, code) -> None:
    document = baseline("qualification")
    mutate(document)
    assert _code(document) == code


@pytest.mark.parametrize("mutate", [
    lambda d: d["variants"]["linux-x86_64-cuda"].update(status="passed"),
    lambda d: _pass_variant(d, "linux-x86_64-cuda"),
    lambda d: (d["variants"]["linux-x86_64-cuda"]["gates"].update(licence="passed"),
               d["evidence"].update({"linux-x86_64-cuda": {"licence": dict(EVIDENCE)}})),
])
def test_variant_without_runtime_pack_can_never_pass(mutate) -> None:
    document = baseline("qualification")
    mutate(document)
    assert _code(document).startswith(("qualification_pending_variant_claims_pass:linux-x86_64-cuda",
                                       "qualification_variant_status_mismatch:linux-x86_64-cuda"))


def test_profile_qualification_on_pending_variant_is_rejected() -> None:
    document = baseline("qualification")
    document["qualifiedProfiles"] = ["P2"]
    document["profileQualifications"] = {
        "P2": {
            "deploymentProfilePolicySha256": "f" * 64,
            "runtimeVariant": "linux-x86_64-cuda",
            "evidence": {"licence": dict(EVIDENCE)},
        }
    }
    assert _code(document) == "qualification_pending_variant_claims_pass:linux-x86_64-cuda"


@pytest.mark.parametrize("schema", ["1.0", 2])
def test_v1_or_malformed_record_schema_is_rejected(schema) -> None:
    document = baseline("qualification")
    document["schemaVersion"] = schema
    assert _code(document) == "qualification_record_schema_unsupported"


def _gate_sets_document(**gate_sets_value):
    return {"schemaVersion": "mavi-capability-gate-sets-v1", "gateSets": gate_sets_value}


@pytest.mark.parametrize(("gate_sets_document", "code"), [
    (_gate_sets_document(), "gate_sets_empty"),
    (_gate_sets_document(**{"a-v1": {"scope": "common", "gates": []}}), "gate_set_empty:a-v1"),
    (_gate_sets_document(**{"a-v1": {"scope": "common", "gates": ["x"]}, "b-v1": {"scope": "capability", "capabilityIds": ["detector"], "gates": ["x"]}}), "gate_name_duplicate:x"),
    (_gate_sets_document(**{"a-v1": {"scope": "common", "gates": ["Bad Gate"]}}), "gate_name_invalid"),
    (_gate_sets_document(**{"a-v1": {"scope": "common", "capabilityIds": ["detector"], "gates": ["x"]}}), "gate_set_scope_invalid:a-v1"),
    (_gate_sets_document(**{"a-v1": {"scope": "capability", "gates": ["x"]}}), "gate_set_scope_invalid:a-v1"),
    (_gate_sets_document(**{"a-v1": {"scope": "capability", "capabilityIds": ["face-recognition"], "gates": ["x"]}}), "capability_unknown:face-recognition"),
    ({"schemaVersion": "mavi-capability-gate-sets-v2", "gateSets": {"a-v1": {"scope": "common", "gates": ["x"]}}}, "gate_sets_invalid"),
    (_gate_sets_document(**{"a-v1": ["x"]}), "gate_sets_invalid"),
])
def test_gate_set_policy_fails_closed(gate_sets_document, code) -> None:
    with pytest.raises(ReleaseMetadataError) as error:
        parse_capability_gate_sets(gate_sets_document)
    assert error.value.code == code


def test_repository_gate_sets_match_the_plan() -> None:
    sets = gate_sets()
    assert set(sets) == {"common-v1", "detector-v1"}
    assert (sets["common-v1"].scope, sets["common-v1"].gates) == ("common", COMMON)
    assert (sets["detector-v1"].scope, sets["detector-v1"].capability_ids, sets["detector-v1"].gates) == (
        "capability", ("detector",), DETECTOR)


def test_detector_record_without_detector_gates_is_rejected() -> None:
    document = baseline("qualification")
    document["gateSetIds"] = ["common-v1"]
    for variant in document["variants"].values():
        variant["gates"] = {gate: "pending" for gate in COMMON}
    assert _code(document) == "qualification_gate_sets_mismatch:detector"


def test_detector_gates_are_not_imposed_on_another_capability() -> None:
    document = baseline("qualification")
    document["capabilityId"] = "embedding"
    assert _code(document) == "qualification_capability_gate_set_missing:embedding"
    extended = dict(gate_sets())
    from mavi_vision.runtime.qualification_v2 import GateSet

    extended["embedding-v1"] = GateSet(scope="capability", capability_ids=("embedding",), gates=("retrieval-accuracy",))
    with pytest.raises(ReleaseMetadataError) as error:
        parse_qualification_record_v2(document, gate_sets=extended)
    assert error.value.code == "qualification_gate_sets_mismatch:embedding"


def test_gate_set_ids_must_be_in_canonical_order() -> None:
    document = baseline("qualification")
    document["gateSetIds"] = ["detector-v1", "common-v1"]
    assert _code(document) == "qualification_gate_sets_mismatch:detector"


@pytest.mark.parametrize("value", ["", " ", "a\tb"])
def test_protocol_text_must_be_well_formed(value) -> None:
    document = baseline("qualification")
    document["protocol"]["corpusId"] = value
    assert _code(document) == "qualification_protocol_invalid"


def test_profile_qualification_variant_vocabulary_is_the_shared_universe() -> None:
    import typing

    from mavi_vision.runtime.qualification import _ProfileQualificationSchema
    from mavi_vision.runtime.variants import RUNTIME_VARIANTS

    literal = _ProfileQualificationSchema.model_fields["runtime_variant"].annotation
    assert set(typing.get_args(literal)) == RUNTIME_VARIANTS


def test_policies_may_be_omitted() -> None:
    document = baseline("qualification")
    document.pop("policies")
    record = parse_qualification_record_v2(document, gate_sets=gate_sets())
    assert record.pipeline_profile_id is None and record.pipeline_profile_sha256 is None


def test_policies_may_be_explicitly_null() -> None:
    document = baseline("qualification")
    document["policies"] = {"pipelineProfileId": None, "pipelineProfileSha256": None}
    record = parse_qualification_record_v2(document, gate_sets=gate_sets())
    assert record.pipeline_profile_id is None and record.pipeline_profile_sha256 is None


def test_populated_policies_are_exposed() -> None:
    record = parse_qualification_record_v2(baseline("qualification"), gate_sets=gate_sets())
    assert record.pipeline_profile_id == "phase1-detection-tracking-v1"
    assert record.pipeline_profile_sha256 == "503225be736d9622ed110aa69e49a83dde4ae02c858d5e8fa41e527b1c4b23fb"


@pytest.mark.parametrize(("policies", "code"), [
    ({"pipelineProfileId": "phase1-detection-tracking-v1", "pipelineProfileSha256": None}, "qualification_policies_incomplete"),
    ({"pipelineProfileId": None, "pipelineProfileSha256": "5" * 64}, "qualification_policies_incomplete"),
    # "no policy" has exactly two encodings: key omitted, or both fields null
    ({"pipelineProfileId": "phase1-detection-tracking-v1"}, "qualification_record_invalid"),
    ({}, "qualification_record_invalid"),
    (None, "qualification_policies_invalid"),
    ({"pipelineProfileId": "phase1-detection-tracking-v1", "pipelineProfileSha256": "not-a-sha"}, "qualification_policies_invalid"),
    ({"pipelineProfileId": " padded", "pipelineProfileSha256": "5" * 64}, "qualification_policies_invalid"),
    ({"pipelineProfileId": "p", "pipelineProfileSha256": "5" * 64, "aggregation": "x"}, "qualification_record_invalid"),
])
def test_half_populated_or_malformed_policies_fail_closed(policies, code) -> None:
    document = baseline("qualification")
    document["policies"] = policies
    assert _code(document) == code
