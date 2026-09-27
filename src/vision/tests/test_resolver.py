"""The v2 composition root: one binding, resolved for the observed variant (S2a.3).

Plan §5 and §6: every identity the worker reports comes from this resolution,
and every inconsistency fails closed with a stable code. Each test below breaks
exactly one relationship of an otherwise self-consistent overlay
(``tests/resolver_overlay.py``) and names the code.

This suite replaces the v1 ``verify_release_selection`` suite deleted at the
cut-over; each v1 behaviour kept by ADR-014 is re-stated against v2 here
(unverified-in-Production, pending gate, qualification identity and hash drift,
artefact byte change, runtime identity drift, profile-scoped policy, stale
policy, missing profile evidence, Development CUDA not satisfying Production).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from mavi_vision.runtime.binding import load_component_binding
from mavi_vision.runtime.component_identity import RuntimePackIdentityInputs, runtime_pack_id
from mavi_vision.runtime.manifest import ReleaseMetadataError
from mavi_vision.runtime.resolver import (
    INSTALLED_PACK,
    UNPACKED_ENVIRONMENT,
    CompletionContract,
    load_role_family,
    resolve_completion_contract,
)
from mavi_vision.runtime.variants import VariantClass
from tests.component_binding_v2_fixtures import (
    REPOSITORY,
    V1_BINDING,
    V1_MANIFEST,
    V1_QUALIFICATION,
    V1_RUNTIME_PROFILE_BYTES,
    V2_BINDING,
)
from tests.resolver_overlay import EMITTABLE, Overlay, sha256_bytes


@pytest.fixture
def overlay(tmp_path: Path) -> Overlay:
    return Overlay.create(tmp_path)


def _code(action) -> str:
    with pytest.raises(ReleaseMetadataError) as raised:
        action()
    return raised.value.code


# --------------------------------------------------------------------------- happy paths


def test_development_resolves_an_unpacked_environment_truthfully(overlay: Overlay) -> None:
    resolved = overlay.resolve()

    assert resolved.runtime_pack.runtime_pack_source == UNPACKED_ENVIRONMENT
    assert resolved.runtime_pack.runtime_pack_id is None
    assert resolved.runtime_variant == "linux-x86_64-cpu"
    assert resolved.component_binding_sha256 == sha256_bytes(overlay.binding_path.read_bytes())
    assert resolved.completion == CompletionContract(version="3.2", override=None)
    capability = resolved.capabilities["detector"]
    assert capability.model_pack_id == overlay.derived_model_pack_id()
    assert capability.manifest_sha256 == sha256_bytes(overlay.manifest_path.read_bytes())
    assert capability.qualification_sha256 == sha256_bytes(overlay.record_path.read_bytes())
    selection = resolved.detector_selection()
    assert selection.verification_status == "unverified"
    assert selection.checkpoint_path == (
        overlay.model_root / overlay.manifest["artifacts"][0]["relativePath"]
    ).resolve()
    assert selection.detector.model_id == overlay.manifest["modelId"]


def test_production_resolves_a_verified_installed_pack(overlay: Overlay) -> None:
    profile, policy_sha = overlay.qualify_for_production()
    resolved = overlay.resolve(
        profile.runtime_variant,
        production_mode=True,
        installed=True,
        profile_requirement=profile,
        deployment_profile_policy_sha256=policy_sha,
    )

    assert resolved.runtime_pack.runtime_pack_source == INSTALLED_PACK
    # Re-derived from the installed manifest and equal to the binding's pin.
    assert resolved.runtime_pack.runtime_pack_id == (
        overlay.binding["runtimePacks"][0]["variants"]["windows-x86_64-cpu"]["runtimePackId"]
    )
    assert resolved.detector_selection().verification_status == "verified"


def test_the_committed_composition_resolves_up_to_the_model_store(tmp_path: Path) -> None:
    """The committed files are self-consistent; only the absent model bytes refuse."""
    from tests.resolver_overlay import PIPELINE_PROFILE
    from mavi_vision.runtime.resolver import RoleComposition, RoleCompositionInputs

    binding = load_component_binding(V2_BINDING)
    composition = RoleComposition(
        RoleCompositionInputs(
            component_binding_path=V2_BINDING,
            role_id="vision",
            overlay_root=REPOSITORY,
            model_root=tmp_path / "empty-store",
            pipeline_profile_path=PIPELINE_PROFILE,
            runtime_pack_manifest_path=None,
            production_mode=False,
        ),
        completion=CompletionContract(version="3.2", override=None),
        binding=binding,
    )
    assert _code(lambda: composition.resolve(runtime_variant="linux-x86_64-cpu", python_version="3.12.14")) == (
        "model_artifact_missing:checkpoint"
    )


def test_the_committed_family_classifies_every_variant(tmp_path: Path) -> None:
    family = load_role_family(binding=load_component_binding(V2_BINDING), role_id="vision", overlay_root=REPOSITORY)
    assert dict(family.variant_classes) == {
        "linux-x86_64-cpu": VariantClass.DEPLOYABLE,
        "linux-x86_64-cuda": VariantClass.KNOWN_NOT_RELEASABLE,
        "windows-x86_64-cpu": VariantClass.DEPLOYABLE,
        "windows-x86_64-cuda": VariantClass.DEPLOYABLE,
    }


def test_every_class_b_binding_id_is_the_lock_derived_id() -> None:
    binding = json.loads(V2_BINDING.read_text(encoding="utf-8"))
    runtime_dir = REPOSITORY / "src/vision/runtime/mmdetection-phase1-v1"
    runtime = json.loads((runtime_dir / "runtime.json").read_text(encoding="utf-8"))
    variants = binding["runtimePacks"][0]["variants"]
    assert set(variants) == {"linux-x86_64-cpu", "windows-x86_64-cpu", "windows-x86_64-cuda"}
    for variant, entry in variants.items():
        derived = runtime_pack_id(
            RuntimePackIdentityInputs(
                platform_variant=variant,
                python_version=runtime["platformVariants"][variant]["pythonIdentity"]["version"],
                third_party_lock_sha256=hashlib.sha256((runtime_dir / f"{variant}.lock").read_bytes()).hexdigest(),
                runtime_requirements_sha256=hashlib.sha256(
                    (runtime_dir / f"{variant}.requirements.txt").read_bytes()
                ).hexdigest(),
                native_abi=entry["nativeAbi"],
            )
        )
        assert derived == entry["runtimePackId"], variant


# --------------------------------------------------------------------------- role and binding


def test_an_unknown_role_is_refused(overlay: Overlay) -> None:
    binding = load_component_binding(overlay.binding_path)
    assert _code(lambda: load_role_family(binding=binding, role_id="attributes", overlay_root=overlay.root)) == (
        "role_unknown:attributes"
    )


def test_a_disabled_binding_blocks_its_role(overlay: Overlay) -> None:
    overlay.binding["capabilityBindings"][0]["enabled"] = False
    overlay.write()
    assert _code(overlay.resolve) == "capability_binding_disabled"


def test_a_role_capability_without_a_binding_is_refused(overlay: Overlay) -> None:
    overlay.binding["capabilityBindings"] = []
    overlay.write(sync=False)
    assert _code(lambda: load_component_binding(overlay.binding_path)) == "capability_binding_missing:vision:detector"


def test_an_unimplemented_capability_never_starts(overlay: Overlay) -> None:
    overlay.binding["roles"][0]["capabilityIds"] = ["detector", "embedding"]
    overlay.binding["capabilityBindings"].append(
        {
            "capabilityId": "embedding",
            "roleId": "vision",
            "modelPackId": overlay.derived_model_pack_id(),
            "qualificationId": overlay.record["qualificationId"],
            "enabled": True,
        }
    )
    overlay.write()
    assert _code(overlay.resolve) == "capability_not_implemented:embedding"


def test_the_family_must_be_its_runtime_profile(overlay: Overlay) -> None:
    overlay.runtime["runtimeProfileId"] = "mmdetection-phase1-v9"
    overlay.write()
    assert _code(overlay.resolve) == "runtime_family_profile_mismatch:mmdetection-phase1-v1"


def test_a_family_without_a_runtime_profile_is_unknown(overlay: Overlay) -> None:
    overlay.runtime_path.unlink()
    assert _code(overlay.resolve) == "runtime_family_unknown:mmdetection-phase1-v1"


# --------------------------------------------------------------------------- P-17 variant classes


def test_class_a_cannot_be_declared_in_the_binding(overlay: Overlay) -> None:
    variants = overlay.binding["runtimePacks"][0]["variants"]
    variants["linux-x86_64-cuda"] = dict(variants["windows-x86_64-cuda"])
    overlay.write()
    assert _code(overlay.resolve) == "binding_variant_not_releasable:linux-x86_64-cuda"


def test_class_b_must_be_declared_in_the_binding(overlay: Overlay) -> None:
    del overlay.binding["runtimePacks"][0]["variants"]["windows-x86_64-cuda"]
    overlay.write()
    assert _code(overlay.resolve) == "binding_variant_missing:windows-x86_64-cuda"


def test_p17_class_a_variant_status_mutation_is_refused(overlay: Overlay) -> None:
    """Mutation 1: the class-A variant claims a status while no lock file exists."""
    overlay.runtime["platformVariants"]["linux-x86_64-cuda"] = dict(
        overlay.runtime["platformVariants"]["windows-x86_64-cuda"]
    )
    overlay.write()
    assert _code(overlay.resolve) == "runtime_variant_classification_invalid:linux-x86_64-cuda"


def test_p17_class_a_release_lock_status_mutation_is_refused(overlay: Overlay) -> None:
    """Mutation 2: the class-A lock claims qualification while the variant is pending."""
    overlay.runtime["releaseLocks"]["linux-x86_64-cuda"] = {
        "status": "qualified-offline-lock",
        "artifact": "linux-x86_64-cuda.lock",
        "sha256": "0" * 64,
    }
    overlay.write()
    assert _code(overlay.resolve) == "runtime_variant_classification_invalid:linux-x86_64-cuda"


def test_a_class_a_variant_never_starts(overlay: Overlay) -> None:
    assert _code(lambda: overlay.resolve("linux-x86_64-cuda")) == "runtime_variant_not_declared:linux-x86_64-cuda"


def test_a_record_cannot_name_a_runtime_pack_for_class_a(overlay: Overlay) -> None:
    overlay.record["variants"]["linux-x86_64-cuda"]["runtimePackId"] = "mavi-runtime-v2-" + "1" * 64
    overlay.write()
    assert _code(overlay.resolve) == "qualification_runtime_pack_forbidden:linux-x86_64-cuda"


def test_a_record_must_name_the_binding_runtime_pack_for_class_b(overlay: Overlay) -> None:
    overlay.record["variants"]["windows-x86_64-cpu"]["runtimePackId"] = "mavi-runtime-v2-" + "1" * 64
    overlay.write()
    assert _code(overlay.resolve) == "qualification_runtime_pack_mismatch:windows-x86_64-cpu"


# --------------------------------------------------------------------------- Runtime Pack


def test_a_pinned_runtime_pack_id_no_lock_derives_is_refused(overlay: Overlay) -> None:
    overlay.binding["runtimePacks"][0]["variants"]["windows-x86_64-cpu"]["runtimePackId"] = (
        "mavi-runtime-v2-" + "1" * 64
    )
    overlay.write()
    # Refused at family load, for a variant this host never observes.
    assert _code(overlay.resolve) == "runtime_pack_binding_id_mismatch:windows-x86_64-cpu"


@pytest.mark.parametrize(
    ("suffix", "code"),
    [(".lock", "runtime_lock_binding_mismatch"), (".requirements.txt", "runtime_requirements_binding_mismatch")],
)
def test_a_tracked_lock_or_requirements_change_is_refused(overlay: Overlay, suffix: str, code: str) -> None:
    # windows-x86_64-cuda: its lock is pending, so only the binding cross-check sees it (P-13).
    path = overlay.runtime_path.parent / f"windows-x86_64-cuda{suffix}"
    path.write_bytes(path.read_bytes() + b"# drift\n")
    assert _code(overlay.resolve) == f"{code}:windows-x86_64-cuda"


def test_a_qualified_lock_change_is_refused(overlay: Overlay) -> None:
    path = overlay.runtime_path.parent / "linux-x86_64-cpu.lock"
    path.write_bytes(path.read_bytes() + b"# drift\n")
    assert _code(overlay.resolve) == "runtime_release_lock_hash_mismatch"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"runtimePackId": "mavi-runtime-v2-" + "1" * 64}, "runtime_pack_manifest_mismatch:id"),
        ({"schemaVersion": "mavi-vision-runtime-pack-v1"}, "runtime_pack_manifest_invalid"),
        ({"nativeAbi": ""}, "runtime_pack_manifest_invalid"),
    ],
)
def test_an_installed_pack_whose_identity_does_not_re_derive_is_refused(
    overlay: Overlay, change: dict, code: str
) -> None:
    overlay.install_pack("linux-x86_64-cpu", **change)
    assert _code(lambda: overlay.resolve(installed=True)) == code


def test_an_installed_pack_with_other_inputs_is_not_the_binding_pack(overlay: Overlay) -> None:
    document = overlay.pack_manifest_for("linux-x86_64-cpu")
    document["nativeAbi"] = "glibc-2.40-other"
    document["runtimePackId"] = runtime_pack_id(
        RuntimePackIdentityInputs(
            platform_variant=document["platformVariant"],
            python_version=document["pythonVersion"],
            third_party_lock_sha256=document["thirdPartyLockSha256"],
            runtime_requirements_sha256=document["runtimeRequirementsSha256"],
            native_abi=document["nativeAbi"],
        )
    )
    overlay.install_pack("linux-x86_64-cpu", **document)
    assert _code(lambda: overlay.resolve(installed=True)) == "runtime_pack_manifest_mismatch:binding"


def test_an_installed_pack_for_another_variant_is_refused(overlay: Overlay) -> None:
    overlay.install_pack("windows-x86_64-cpu")
    assert _code(lambda: overlay.resolve("linux-x86_64-cpu", installed=True)) == "runtime_pack_variant_mismatch"


def test_an_installed_pack_on_another_interpreter_is_refused(overlay: Overlay) -> None:
    overlay.install_pack("linux-x86_64-cpu")
    assert _code(lambda: overlay.resolve(installed=True, python_version="3.12.15")) == (
        "runtime_pack_manifest_mismatch:python"
    )


def test_an_unreadable_pack_manifest_is_invalid(overlay: Overlay) -> None:
    overlay.pack_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    overlay.pack_manifest_path.write_bytes(b"{not json")
    assert _code(lambda: overlay.resolve(installed=True)) == "runtime_pack_manifest_invalid"


# --------------------------------------------------------------------------- Model Pack


def test_a_binding_naming_no_manifest_is_refused(overlay: Overlay) -> None:
    overlay.binding["capabilityBindings"][0]["modelPackId"] = "mavi-model-v2-" + "1" * 64
    overlay.write(sync=False)
    assert _code(overlay.resolve) == "model_manifest_missing:mavi-model-v2-" + "1" * 64


def test_two_manifests_deriving_one_id_are_ambiguous(overlay: Overlay) -> None:
    shutil.copyfile(overlay.manifest_path, overlay.manifest_path.with_name("copy.json"))
    assert _code(overlay.resolve) == f"model_manifest_ambiguous:{overlay.derived_model_pack_id()}"


def test_a_manifest_for_another_family_is_incompatible(overlay: Overlay) -> None:
    overlay.manifest["runtimeCompatibility"]["runtimePackFamilyIds"] = ["other-family-v1"]
    overlay.write()
    assert _code(overlay.resolve) == "model_runtime_incompatible"


@pytest.mark.parametrize("role", ["checkpoint", "resolved-config", "licence-notice"])
def test_an_artefact_byte_change_is_refused(overlay: Overlay, role: str) -> None:
    item = next(item for item in overlay.manifest["artifacts"] if item["artifactRole"] == role)
    (overlay.model_root / item["relativePath"]).write_bytes(b"tampered")
    assert _code(overlay.resolve) == f"model_artifact_hash_mismatch:{role}"


@pytest.mark.parametrize("role", ["checkpoint", "licence-notice"])
def test_a_missing_artefact_is_refused(overlay: Overlay, role: str) -> None:
    item = next(item for item in overlay.manifest["artifacts"] if item["artifactRole"] == role)
    (overlay.model_root / item["relativePath"]).unlink()
    assert _code(overlay.resolve) == f"model_artifact_missing:{role}"


def test_the_licence_notice_is_identity_bearing(overlay: Overlay) -> None:
    before = overlay.derived_model_pack_id()
    overlay.artifacts["licence-notice"] = overlay.artifacts["licence-notice"] + b"\n"
    overlay.write()
    assert overlay.derived_model_pack_id() != before
    # Re-derived consistently, the new pack still resolves: the id is the bytes'.
    assert overlay.resolve().capabilities["detector"].model_pack_id == overlay.derived_model_pack_id()


def test_a_v1_manifest_in_the_index_is_refused_not_ignored(overlay: Overlay) -> None:
    shutil.copyfile(V1_MANIFEST, overlay.manifest_path.with_name("rtmdet-m-coco-phase1-v1.json"))
    assert _code(overlay.resolve) == "model_manifest_schema_unsupported"


# --------------------------------------------------------------------------- qualification


def test_a_binding_naming_no_record_is_refused(overlay: Overlay) -> None:
    overlay.binding["capabilityBindings"][0]["qualificationId"] = "rtmdet-m-coco-phase1-v9"
    overlay.write()
    assert _code(overlay.resolve) == "qualification_record_missing:rtmdet-m-coco-phase1-v9"


def test_two_records_with_one_id_are_ambiguous(overlay: Overlay) -> None:
    shutil.copyfile(overlay.record_path, overlay.record_path.with_name("copy.json"))
    assert _code(overlay.resolve) == "qualification_record_ambiguous:rtmdet-m-coco-phase1-v2"


def test_a_record_for_another_model_pack_is_refused(overlay: Overlay) -> None:
    overlay.write()
    overlay.record["modelPackId"] = "mavi-model-v2-" + "1" * 64
    overlay.write(sync=False)
    assert _code(overlay.resolve) == "model_pack_id_mismatch"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda record: record.update(modelId="other-model"),
        lambda record: record.update(modelManifestSha256="1" * 64),
        lambda record: record["artifactSha256"].update({"checkpoint": "1" * 64}),
        lambda record: record["artifactSha256"].update({"licence-notice": "1" * 64}),
        lambda record: record.update(runtimeProfileSha256="1" * 64),
        lambda record: record["outputContract"].update(schemaId="detector-output-v9"),
    ],
    ids=["model-id", "manifest-sha", "checkpoint-sha", "licence-sha", "runtime-profile-sha", "output-schema"],
)
def test_record_identity_drift_is_refused(overlay: Overlay, mutate) -> None:
    mutate(overlay.record)
    overlay.write(sync=False)
    assert _code(overlay.resolve) == "qualification_identity_mismatch"


def test_a_runtime_profile_change_invalidates_the_record(overlay: Overlay) -> None:
    """v1 'runtime identity drift': the family profile's bytes are qualified evidence."""
    overlay.runtime["platformVariants"]["linux-x86_64-cpu"]["workflowRunId"] = "1"
    overlay.write(sync=False)
    assert _code(overlay.resolve) == "qualification_identity_mismatch"


def test_a_verified_manifest_must_name_its_record(overlay: Overlay) -> None:
    overlay.qualify_for_production()
    overlay.manifest["qualificationId"] = "rtmdet-m-coco-phase1-v9"
    overlay.write()
    assert _code(overlay.resolve) == "qualification_identity_mismatch"


def test_a_detector_record_must_carry_its_policies(overlay: Overlay) -> None:
    overlay.record.pop("policies")
    overlay.write(sync=False)
    assert _code(overlay.resolve) == "qualification_policies_required:detector"


@pytest.mark.parametrize("field", ["pipelineProfileId", "pipelineProfileSha256"])
def test_a_record_for_another_pipeline_policy_is_refused(overlay: Overlay, field: str) -> None:
    overlay.record["policies"][field] = "1" * 64 if field.endswith("Sha256") else "phase1-other-v1"
    overlay.write(sync=False)
    assert _code(overlay.resolve) == "qualification_policy_mismatch"


def test_the_live_pipeline_profile_is_reconciled_not_copied(overlay: Overlay) -> None:
    raw = json.loads(overlay.pipeline_path.read_text(encoding="utf-8"))
    raw["detectorInferenceFloor"] = 0.06
    overlay.pipeline_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    assert _code(overlay.resolve) == "qualification_policy_mismatch"


def test_a_v1_record_in_the_index_is_refused_not_ignored(overlay: Overlay) -> None:
    shutil.copyfile(V1_QUALIFICATION, overlay.record_path.with_name("rtmdet-m-coco-phase1-v1.json"))
    assert _code(overlay.resolve) == "qualification_record_schema_unsupported"


# --------------------------------------------------------------------------- legacy inputs


def test_a_v1_binding_is_refused(overlay: Overlay) -> None:
    assert _code(lambda: load_component_binding(V1_BINDING)) == "component_binding_schema_unsupported"


def test_a_v1_runtime_profile_is_refused(overlay: Overlay) -> None:
    shutil.copyfile(V1_RUNTIME_PROFILE_BYTES, overlay.runtime_path)
    assert _code(overlay.resolve) == "runtime_profile_schema_unsupported"


# --------------------------------------------------------------------------- Production policy


def _production(overlay: Overlay, variant: str | None = None, *, profile=None, policy_sha=None, installed=True):
    return overlay.resolve(
        variant or profile.runtime_variant,
        production_mode=True,
        installed=installed,
        profile_requirement=profile,
        deployment_profile_policy_sha256=policy_sha,
    )


def test_production_refuses_an_unverified_manifest(overlay: Overlay) -> None:
    from mavi_vision.runtime.deployment_profiles import select_profile
    from tests.resolver_overlay import DEPLOYMENT_PROFILES

    profile, sha = select_profile("P3", DEPLOYMENT_PROFILES)
    overlay.install_pack("windows-x86_64-cpu")
    assert _code(lambda: _production(overlay, profile=profile, policy_sha=sha)) == "unverified_release_forbidden"


def test_production_requires_an_installed_runtime_pack(overlay: Overlay) -> None:
    profile, sha = overlay.qualify_for_production()
    assert _code(lambda: _production(overlay, profile=profile, policy_sha=sha, installed=False)) == (
        "runtime_pack_required"
    )


def test_production_refuses_a_variant_the_record_has_not_passed(overlay: Overlay) -> None:
    profile, sha = overlay.qualify_for_production()
    overlay.install_pack("linux-x86_64-cpu")
    assert _code(lambda: _production(overlay, "linux-x86_64-cpu", profile=profile, policy_sha=sha)) == (
        "qualification_variant_not_passed"
    )


def test_production_requires_the_deployment_profile(overlay: Overlay) -> None:
    overlay.qualify_for_production()
    assert _code(lambda: _production(overlay, "windows-x86_64-cpu")) == "qualification_profile_requirement_incomplete"


def test_production_refuses_a_profile_for_another_variant(overlay: Overlay) -> None:
    profile, sha = overlay.qualify_for_production()
    overlay.pass_variant("linux-x86_64-cpu")
    overlay.write()
    overlay.install_pack("linux-x86_64-cpu")
    assert _code(lambda: _production(overlay, "linux-x86_64-cpu", profile=profile, policy_sha=sha)) == (
        "production_deployment_profile_runtime_variant_mismatch"
    )


def test_production_refuses_a_profile_the_record_does_not_qualify(overlay: Overlay) -> None:
    profile, sha = overlay.qualify_for_production()
    other = dataclasses.replace(profile, profile_id="P9")
    assert _code(lambda: _production(overlay, profile=other, policy_sha=sha)) == "qualification_profile_not_qualified"


def test_production_refuses_a_profile_qualified_on_another_variant(overlay: Overlay) -> None:
    profile, sha = overlay.qualify_for_production()
    overlay.pass_variant("linux-x86_64-cpu")
    overlay.record["profileQualifications"]["P3"]["runtimeVariant"] = "linux-x86_64-cpu"
    overlay.write()
    assert _code(lambda: _production(overlay, profile=profile, policy_sha=sha)) == (
        "qualification_profile_runtime_variant_mismatch"
    )


def test_production_refuses_a_stale_deployment_policy(overlay: Overlay) -> None:
    profile, _sha = overlay.qualify_for_production()
    assert _code(lambda: _production(overlay, profile=profile, policy_sha="1" * 64)) == (
        "qualification_profile_policy_mismatch"
    )


def test_production_requires_profile_evidence_for_every_variant_gate(overlay: Overlay) -> None:
    profile, sha = overlay.qualify_for_production()
    overlay.record["profileQualifications"]["P3"]["evidence"].pop("licence")
    overlay.write()
    assert _code(lambda: _production(overlay, profile=profile, policy_sha=sha)) == (
        "qualification_profile_evidence_missing"
    )


def test_windows_cuda_development_hardware_never_satisfies_production(overlay: Overlay) -> None:
    """P-13: qualified-development-hardware is not qualified-hardware."""
    from mavi_vision.runtime.deployment_profiles import select_profile
    from tests.resolver_overlay import DEPLOYMENT_PROFILES

    profile, sha = select_profile("P1", DEPLOYMENT_PROFILES)
    overlay.pass_variant("windows-x86_64-cuda")
    overlay.record["qualifiedProfiles"] = ["P1"]
    overlay.record["profileQualifications"] = {
        "P1": {
            "deploymentProfilePolicySha256": sha,
            "runtimeVariant": "windows-x86_64-cuda",
            "evidence": {
                gate: {"kind": "workflow", "reference": "run-1", "sha256": "e" * 64}
                for gate in overlay.record["variants"]["windows-x86_64-cuda"]["gates"]
            },
        }
    }
    overlay.record["overallResult"] = "passed"
    overlay.manifest["verificationStatus"] = "verified"
    overlay.manifest["qualificationId"] = overlay.record["qualificationId"]
    overlay.manifest["licence"]["reviewStatus"] = "approved"
    overlay.write()
    overlay.install_pack("windows-x86_64-cuda")
    assert _code(lambda: _production(overlay, profile=profile, policy_sha=sha)) == (
        "runtime_profile_variant_not_qualified"
    )


def test_development_may_run_the_same_windows_cuda_pack_unverified(overlay: Overlay) -> None:
    overlay.install_pack("windows-x86_64-cuda")
    resolved = overlay.resolve("windows-x86_64-cuda", installed=True)
    assert resolved.runtime_pack.runtime_pack_source == INSTALLED_PACK
    assert resolved.detector_selection().verification_status == "unverified"


# --------------------------------------------------------------------------- completion contract (P-16)


def _role(contract: str = "vision-job-complete-v3.2"):
    return SimpleNamespace(provenance_contract=contract)


def test_the_role_contract_is_the_default_completion() -> None:
    assert resolve_completion_contract(_role(), override=None, production_mode=False, emittable_versions=EMITTABLE) == (
        CompletionContract(version="3.2", override=None)
    )


@pytest.mark.parametrize("override", ["3.0", "3.1"])
def test_the_development_override_selects_a_pre_cut_over_version(override: str) -> None:
    contract = resolve_completion_contract(
        _role(), override=override, production_mode=False, emittable_versions=EMITTABLE
    )
    assert contract.version == override and contract.override_active


@pytest.mark.parametrize(
    ("role", "override", "production_mode", "emittable", "code"),
    [
        (_role("vision-job-complete-v3.1"), None, False, EMITTABLE, "role_provenance_contract_unknown"),
        (_role(), "3.1", True, EMITTABLE, "completion_override_forbidden_in_production"),
        (_role(), "3.2", False, EMITTABLE, "completion_override_invalid"),
        (_role(), "2.0", False, EMITTABLE, "completion_override_invalid"),
        (_role(), None, False, ("3.0", "3.1"), "role_provenance_contract_mismatch"),
    ],
)
def test_the_completion_contract_fails_closed(role, override, production_mode, emittable, code) -> None:
    with pytest.raises(ReleaseMetadataError, match=code):
        resolve_completion_contract(role, override=override, production_mode=production_mode, emittable_versions=emittable)


def test_an_overridden_role_logs_that_it_is_non_qualifying(overlay: Overlay, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="mavi_vision.runtime.resolver"):
        resolved = overlay.resolve(override="3.1")
    assert resolved.completion.override_active
    assert any("completion_schema_override_active" in record.getMessage() for record in caplog.records)


def test_production_refuses_the_override_before_resolution(overlay: Overlay) -> None:
    with pytest.raises(ReleaseMetadataError, match="completion_override_forbidden_in_production"):
        overlay.composition(production_mode=True, override="3.1")


def test_an_unverified_manifest_cannot_claim_a_record(overlay: Overlay) -> None:
    overlay.manifest["qualificationId"] = overlay.record["qualificationId"]
    overlay.write()
    assert _code(overlay.resolve) == "unverified_manifest_claims_qualification"


def test_a_binding_to_a_pack_without_the_capability_is_refused(overlay: Overlay) -> None:
    from mavi_vision.runtime.model_manifest_v2 import load_model_manifest_v2

    fixture = Path(__file__).resolve().parent / "fixtures/model-manifests/embedding-fixture-v2.json"
    target = overlay.manifest_path.with_name("embedding-fixture-v2.json")
    shutil.copyfile(fixture, target)
    overlay.binding["capabilityBindings"][0]["modelPackId"] = load_model_manifest_v2(target).model_pack_id
    overlay.write(sync=False)
    assert _code(overlay.resolve) == "model_capability_mismatch:detector"
