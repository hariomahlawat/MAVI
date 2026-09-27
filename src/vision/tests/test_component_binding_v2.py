from __future__ import annotations

import hashlib
import json

import pytest

from mavi_vision.runtime.binding import load_component_binding, parse_component_binding
from mavi_vision.runtime.component_relationships import check_binding_variants, check_record_variants
from mavi_vision.runtime.manifest import ReleaseMetadataError
from mavi_vision.runtime.qualification_v2 import parse_qualification_record_v2
from mavi_vision.runtime.runtime_profile_v2 import classify_runtime_variants, parse_runtime_profile_v2
from tests.component_binding_v2_fixtures import V1_BINDING, baseline, gate_sets

SHA = "0" * 64
ATTRIBUTES_ROLE = {
    "roleId": "attributes",
    "runtimePackFamilyId": "mmdetection-phase1-v1",
    "capabilityIds": ["person-attributes", "vehicle-attributes"],
    "entryPoint": "mavi_vision.worker.main",
    "readinessContract": "worker-health-v2",
    "provenanceContract": "vision-job-complete-v3.2",
}


def _binding(document: dict):
    return parse_component_binding(document, component_binding_sha256=SHA)


def _code(document) -> str:
    with pytest.raises(ReleaseMetadataError) as error:
        _binding(document)
    return error.value.code


def _classes():
    return classify_runtime_variants(
        parse_runtime_profile_v2(baseline("runtimeProfile")),
        tracked_lock_variants=("linux-x86_64-cpu", "windows-x86_64-cpu", "windows-x86_64-cuda"),
    )


def test_generated_binding_has_the_adr_014_shape() -> None:
    binding = _binding(baseline("binding"))
    variants = binding.family_variants("mmdetection-phase1-v1")
    assert set(variants) == {"windows-x86_64-cpu", "linux-x86_64-cpu", "windows-x86_64-cuda"}
    role = binding.role("vision")
    assert (role.entry_point, role.readiness_contract, role.provenance_contract) == (
        "mavi_vision.worker.main", "worker-health-v2", "vision-job-complete-v3.2")
    (detector,) = binding.bindings_for_role("vision")
    assert detector.capability_id == "detector" and detector.enabled
    assert detector.qualification_id == "rtmdet-m-coco-phase1-v2"
    assert detector.model_pack_id.startswith("mavi-model-v2-")


def test_runtime_pack_ids_are_carried_unchanged_from_v1() -> None:
    v1 = json.loads(V1_BINDING.read_text(encoding="utf-8"))["runtimePacks"]
    variants = _binding(baseline("binding")).family_variants("mmdetection-phase1-v1")
    assert {name: entry.runtime_pack_id for name, entry in variants.items()} == {
        name: entry["runtimePackId"] for name, entry in v1.items()}


def test_component_binding_sha_is_the_exact_file_bytes(tmp_path) -> None:
    path = tmp_path / "binding.json"
    payload = (json.dumps(baseline("binding"), indent=2) + "\n").encode()
    path.write_bytes(payload)
    assert load_component_binding(path).component_binding_sha256 == hashlib.sha256(payload).hexdigest()
    path.write_bytes(payload.replace(b'"phase1-v2"', b'"phase1-v3"'))
    assert load_component_binding(path).component_binding_sha256 != hashlib.sha256(payload).hexdigest()


def test_bom_or_crlf_binding_file_is_rejected(tmp_path) -> None:
    path = tmp_path / "binding.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(baseline("binding")).encode())
    with pytest.raises(ReleaseMetadataError, match="release_text_bom_forbidden"):
        load_component_binding(path)


@pytest.mark.parametrize("schema", ["mavi-vision-component-requirements-v1", 2, "2", "mavi-vision-component-binding-v3"])
def test_wrong_or_v1_schema_version_is_rejected(schema) -> None:
    document = baseline("binding")
    document["schemaVersion"] = schema
    assert _code(document) == "component_binding_schema_unsupported"


def test_v1_binding_file_is_rejected() -> None:
    assert _code(json.loads(V1_BINDING.read_text(encoding="utf-8"))) == "component_binding_schema_unsupported"


def _extra_binding(document: dict, capability_id: str, role_id: str = "vision") -> dict:
    return {"capabilityId": capability_id, "roleId": role_id, "modelPackId": "mavi-model-v2-" + "1" * 64,
            "qualificationId": "q", "enabled": True}


@pytest.mark.parametrize(("mutate", "code"), [
    # ordering and uniqueness (P-5)
    (lambda d: (d["roles"][0]["capabilityIds"].append("embedding"),
                d["capabilityBindings"].insert(0, _extra_binding(d, "embedding"))), "capability_bindings_unordered"),
    (lambda d: (d["roles"][0]["capabilityIds"].append("embedding"),
                d["capabilityBindings"].extend([_extra_binding(d, "embedding"), _extra_binding(d, "embedding")])), "capability_binding_duplicate"),
    (lambda d: d["roles"].append(dict(d["roles"][0])), "role_duplicate"),
    (lambda d: d["runtimePacks"].append(dict(d["runtimePacks"][0])), "runtime_family_duplicate"),
    (lambda d: d["roles"][0]["capabilityIds"].append("detector"), "role_capability_duplicate"),
    # role relationships and required-ness per role (P-6)
    (lambda d: d["roles"][0].update(runtimePackFamilyId="mmdetection-phase2-v1"), "runtime_family_unknown:mmdetection-phase2-v1"),
    (lambda d: d["capabilityBindings"][0].update(roleId="attributes"), "role_unknown:attributes"),
    (lambda d: d["roles"][0]["capabilityIds"].append("embedding"), "capability_binding_missing:vision:embedding"),
    (lambda d: d["roles"].append(dict(ATTRIBUTES_ROLE)), "capability_binding_missing:attributes:person-attributes"),
    (lambda d: (d["roles"].append({**ATTRIBUTES_ROLE, "capabilityIds": ["person-attributes"]}),
                d["capabilityBindings"].append(_extra_binding(d, "person-attributes", "vision"))), "capability_not_served_by_role:vision:person-attributes"),
    (lambda d: d.update(roles=[]), "component_binding_invalid:roles"),
    (lambda d: d["roles"][0].update(capabilityIds=["face-recognition"]), "capability_unknown:face-recognition"),
    (lambda d: d["capabilityBindings"][0].update(capabilityId="Detector"), "capability_id_invalid"),
    # role contract fields
    (lambda d: d["roles"][0].pop("entryPoint"), "component_binding_invalid"),
    (lambda d: d["roles"][0].pop("readinessContract"), "component_binding_invalid"),
    (lambda d: d["roles"][0].pop("provenanceContract"), "component_binding_invalid"),
    (lambda d: d["roles"][0].update(entryPoint="mavi_vision/worker/main.py"), "component_binding_invalid:entryPoint"),
    (lambda d: d["roles"][0].update(readinessContract="worker-health-v9"), "role_readiness_contract_unknown:worker-health-v9"),
    (lambda d: d["roles"][0].update(provenanceContract="vision-job-complete-v3.1"), "role_provenance_contract_unknown:vision-job-complete-v3.1"),
    (lambda d: d["roles"][0].update(roleId="Vision"), "component_binding_invalid:roleId"),
    # qualification reference naming (ADR-014 amendment)
    (lambda d: d["capabilityBindings"][0].update(qualificationRecordId=d["capabilityBindings"][0].pop("qualificationId")), "component_binding_invalid"),
    # identities
    (lambda d: d["capabilityBindings"][0].update(modelPackId="mavi-model-v1-" + "0" * 64), "component_binding_invalid:modelPackId"),
    (lambda d: d["runtimePacks"][0]["variants"]["windows-x86_64-cpu"].update(runtimePackId="mavi-runtime-v1-" + "0" * 64), "component_binding_invalid:runtimePackId"),
    (lambda d: d["runtimePacks"][0]["variants"]["windows-x86_64-cpu"].update(thirdPartyLockSha256="x"), "component_binding_invalid:sha256"),
    (lambda d: d["runtimePacks"][0]["variants"].update({"linux-arm64-cpu": d["runtimePacks"][0]["variants"]["linux-x86_64-cpu"]}), "binding_variant_unknown:linux-arm64-cpu"),
    # no model identity coupled back into a Runtime Pack entry
    (lambda d: d["runtimePacks"][0]["variants"]["windows-x86_64-cpu"].update(checkpointSha256="0" * 64), "component_binding_invalid"),
    (lambda d: d.update(modelPack={}), "component_binding_invalid"),
    (lambda d: d.update(runtimePackId="mavi-runtime-v2-" + "0" * 64), "component_binding_invalid"),
    (lambda d: d["capabilityBindings"][0].update(optional=True), "component_binding_invalid"),
])
def test_binding_rules_fail_closed(mutate, code) -> None:
    document = baseline("binding")
    mutate(document)
    assert _code(document) == code


@pytest.mark.parametrize("value", ["yes", "true", 1, 0, None])
def test_enabled_must_be_a_json_boolean(value) -> None:
    document = baseline("binding")
    document["capabilityBindings"][0]["enabled"] = value
    assert _code(document) == "component_binding_invalid"


def test_duplicate_json_key_is_rejected(tmp_path) -> None:
    path = tmp_path / "binding.json"
    text = json.dumps(baseline("binding"), indent=2)
    path.write_text(text.replace('"enabled": true', '"enabled": false, "enabled": true'), encoding="utf-8")
    with pytest.raises(ReleaseMetadataError) as error:
        load_component_binding(path)
    assert error.value.code == "component_binding_invalid"


@pytest.mark.parametrize("value", ["abi\twith-tab", "abi\u0000"])
def test_identity_text_rejects_control_characters(value) -> None:
    document = baseline("binding")
    document["runtimePacks"][0]["variants"]["windows-x86_64-cpu"]["nativeAbi"] = value
    assert _code(document) == "component_binding_invalid:nativeAbi"


def test_invalid_binding_sha_argument_is_a_stable_error() -> None:
    with pytest.raises(ReleaseMetadataError) as error:
        parse_component_binding(baseline("binding"), component_binding_sha256="not-a-sha")
    assert error.value.code == "component_binding_sha256_invalid"


def test_disabled_binding_is_retained_but_visible() -> None:
    document = baseline("binding")
    document["capabilityBindings"][0]["enabled"] = False
    (binding,) = _binding(document).bindings_for_role("vision")
    assert binding.enabled is False


def test_binding_declares_exactly_the_deployable_variants() -> None:
    variants = _binding(baseline("binding")).family_variants("mmdetection-phase1-v1")
    check_binding_variants(binding_variants=variants, variant_classes=_classes())


def test_binding_omitting_a_deployable_variant_is_rejected() -> None:
    document = baseline("binding")
    document["runtimePacks"][0]["variants"].pop("linux-x86_64-cpu")
    with pytest.raises(ReleaseMetadataError) as error:
        check_binding_variants(binding_variants=_binding(document).family_variants("mmdetection-phase1-v1"), variant_classes=_classes())
    assert error.value.code == "binding_variant_missing:linux-x86_64-cpu"


def test_binding_declaring_a_known_not_releasable_variant_is_rejected() -> None:
    document = baseline("binding")
    document["runtimePacks"][0]["variants"]["linux-x86_64-cuda"] = dict(document["runtimePacks"][0]["variants"]["linux-x86_64-cpu"])
    with pytest.raises(ReleaseMetadataError) as error:
        check_binding_variants(binding_variants=_binding(document).family_variants("mmdetection-phase1-v1"), variant_classes=_classes())
    assert error.value.code == "binding_variant_not_releasable:linux-x86_64-cuda"


def _record(mutate=None):
    document = baseline("qualification")
    if mutate:
        mutate(document)
    return parse_qualification_record_v2(document, gate_sets=gate_sets())


def test_record_check_is_safe_without_the_binding_check_first() -> None:
    document = baseline("binding")
    document["runtimePacks"][0]["variants"].pop("linux-x86_64-cpu")
    with pytest.raises(ReleaseMetadataError) as error:
        check_record_variants(record=_record(), binding_variants=_binding(document).family_variants("mmdetection-phase1-v1"), variant_classes=_classes())
    assert error.value.code == "binding_variant_missing:linux-x86_64-cpu"


def test_record_variants_cross_check_the_binding() -> None:
    variants = _binding(baseline("binding")).family_variants("mmdetection-phase1-v1")
    check_record_variants(record=_record(), binding_variants=variants, variant_classes=_classes())


@pytest.mark.parametrize(("mutate", "code"), [
    (lambda d: d["variants"]["windows-x86_64-cpu"].update(runtimePackId=None), "qualification_runtime_pack_required:windows-x86_64-cpu"),
    (lambda d: d["variants"]["linux-x86_64-cpu"].update(runtimePackId=None), "qualification_runtime_pack_required:linux-x86_64-cpu"),
    (lambda d: d["variants"]["windows-x86_64-cuda"].update(runtimePackId=None), "qualification_runtime_pack_required:windows-x86_64-cuda"),
    (lambda d: d["variants"]["linux-x86_64-cuda"].update(runtimePackId="mavi-runtime-v2-" + "9" * 64), "qualification_runtime_pack_forbidden:linux-x86_64-cuda"),
    (lambda d: d["variants"]["windows-x86_64-cpu"].update(runtimePackId="mavi-runtime-v2-" + "9" * 64), "qualification_runtime_pack_mismatch:windows-x86_64-cpu"),
])
def test_record_variant_identity_rules_fail_closed(mutate, code) -> None:
    variants = _binding(baseline("binding")).family_variants("mmdetection-phase1-v1")
    with pytest.raises(ReleaseMetadataError) as error:
        check_record_variants(record=_record(mutate), binding_variants=variants, variant_classes=_classes())
    assert error.value.code == code
