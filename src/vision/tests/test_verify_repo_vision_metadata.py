"""``verify_repo`` vision release metadata, v2 (plan §6): one negative fixture per rule.

Each test starts from a self-consistent copy of the committed composition at
the repository paths ``verify_repo`` reads (``RepositoryOverlay``), breaks one
relationship, and requires the check to name it. The baseline test proves the
fixture is clean, so every other failure is caused by its own mutation.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from tests.component_binding_v2_fixtures import V1_BINDING, V1_MANIFEST, V1_QUALIFICATION, V1_RUNTIME_PROFILE_BYTES
from tests.resolver_overlay import RepositoryOverlay, sha256_bytes

VERIFY_REPO_PATH = Path(__file__).parents[3] / "tools" / "verify_repo.py"


def _load_verify_repo():
    spec = importlib.util.spec_from_file_location("verify_repo_vision_v2", VERIFY_REPO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFY = _load_verify_repo()


@pytest.fixture
def overlay(tmp_path: Path) -> RepositoryOverlay:
    return RepositoryOverlay.create(tmp_path)


def _errors(overlay: RepositoryOverlay) -> list[str]:
    errors: list[str] = []
    VERIFY.check_vision_release_metadata(errors, root=overlay.root, tracked=overlay.tracked())
    return errors


def _only(overlay: RepositoryOverlay, fragment: str) -> None:
    errors = _errors(overlay)
    assert errors, "the mutation was not detected"
    assert any(fragment in error for error in errors), errors


def test_the_committed_repository_passes() -> None:
    errors: list[str] = []
    VERIFY.check_vision_release_metadata(errors)
    assert errors == []


def test_the_fixture_baseline_is_clean(overlay: RepositoryOverlay) -> None:
    assert _errors(overlay) == []


def test_the_binding_is_a_required_path_and_a_release_text_root() -> None:
    assert "src/vision/config/components/phase1-bindings-v2.json" in VERIFY.REQUIRED_PATHS
    assert VERIFY.COMPONENT_BINDING_ROOT in VERIFY.RELEASE_TEXT_ROOTS
    for retired in ("models/manifests/rtmdet-m-coco-phase1-v1.json", "models/qualifications/rtmdet-m-coco-phase1-v1.json"):
        assert retired not in VERIFY.REQUIRED_PATHS


# --------------------------------------------------------------------------- v1 files


def test_a_v1_manifest_is_refused(overlay: RepositoryOverlay) -> None:
    shutil.copyfile(V1_MANIFEST, overlay.root / "models/manifests/rtmdet-m-coco-phase1-v1.json")
    _only(overlay, "model_manifest_schema_unsupported")


def test_a_v1_record_is_refused(overlay: RepositoryOverlay) -> None:
    shutil.copyfile(V1_QUALIFICATION, overlay.root / "models/qualifications/rtmdet-m-coco-phase1-v1.json")
    _only(overlay, "qualification_record_schema_unsupported")


def test_a_v1_runtime_profile_is_refused(overlay: RepositoryOverlay) -> None:
    shutil.copyfile(V1_RUNTIME_PROFILE_BYTES, overlay.runtime_path)
    _only(overlay, "runtime_profile_schema_unsupported")


def test_a_v1_binding_is_refused(overlay: RepositoryOverlay) -> None:
    shutil.copyfile(V1_BINDING, overlay.binding_path)
    _only(overlay, "component_binding_schema_unsupported")


def test_a_second_binding_is_not_supported(overlay: RepositoryOverlay) -> None:
    shutil.copyfile(overlay.binding_path, overlay.binding_path.with_name("second.json"))
    _only(overlay, "binding_multiple_not_supported")


def test_no_binding_is_refused(overlay: RepositoryOverlay) -> None:
    overlay.binding_path.unlink()
    _only(overlay, "No component binding is tracked")


# --------------------------------------------------------------------------- P-17 and the binding


def test_a_class_b_variant_missing_from_the_binding(overlay: RepositoryOverlay) -> None:
    del overlay.binding["runtimePacks"][0]["variants"]["windows-x86_64-cuda"]
    overlay.write()
    # Refused by the family check (P-17), independently of the record check.
    _only(overlay, "inconsistent with its runtime family: binding_variant_missing:windows-x86_64-cuda")


def test_the_class_a_variant_declared_in_the_binding(overlay: RepositoryOverlay) -> None:
    variants = overlay.binding["runtimePacks"][0]["variants"]
    variants["linux-x86_64-cuda"] = dict(variants["windows-x86_64-cuda"])
    overlay.write()
    _only(overlay, "binding_variant_not_releasable:linux-x86_64-cuda")


def test_p17_class_a_variant_status_mutation(overlay: RepositoryOverlay) -> None:
    overlay.runtime["platformVariants"]["linux-x86_64-cuda"] = dict(overlay.runtime["platformVariants"]["windows-x86_64-cuda"])
    overlay.write()
    _only(overlay, "runtime_variant_classification_invalid:linux-x86_64-cuda")


def test_p17_class_a_release_lock_status_mutation(overlay: RepositoryOverlay) -> None:
    overlay.runtime["releaseLocks"]["linux-x86_64-cuda"] = {
        "status": "qualified-offline-lock",
        "artifact": "linux-x86_64-cuda.lock",
        "sha256": "0" * 64,
    }
    overlay.write()
    _only(overlay, "runtime_variant_classification_invalid:linux-x86_64-cuda")


def test_a_binding_lock_digest_that_is_not_the_tracked_lock(overlay: RepositoryOverlay) -> None:
    overlay.binding["runtimePacks"][0]["variants"]["windows-x86_64-cuda"]["thirdPartyLockSha256"] = "0" * 64
    overlay.write()
    _only(overlay, "runtime_lock_binding_mismatch:windows-x86_64-cuda")


def test_a_binding_runtime_pack_id_no_lock_derives(overlay: RepositoryOverlay) -> None:
    overlay.binding["runtimePacks"][0]["variants"]["linux-x86_64-cpu"]["runtimePackId"] = "mavi-runtime-v2-" + "1" * 64
    overlay.write()
    _only(overlay, "runtime_pack_binding_id_mismatch:linux-x86_64-cpu")


def test_an_unknown_family(overlay: RepositoryOverlay) -> None:
    overlay.runtime["runtimeProfileId"] = "mmdetection-phase1-v9"
    overlay.write()
    _only(overlay, "runtime_family_profile_mismatch")


def test_an_unknown_capability_id(overlay: RepositoryOverlay) -> None:
    overlay.binding["capabilityBindings"][0]["capabilityId"] = "face-recognition"
    overlay.write(sync=False)
    _only(overlay, "capability_unknown:face-recognition")


# --------------------------------------------------------------------------- records per variant


@pytest.mark.parametrize("variant", ["windows-x86_64-cpu", "linux-x86_64-cpu", "windows-x86_64-cuda"])
def test_a_null_runtime_pack_id_for_a_declared_variant(overlay: RepositoryOverlay, variant: str) -> None:
    overlay.record["variants"][variant]["runtimePackId"] = None
    overlay.write()
    _only(overlay, f"qualification_runtime_pack_required:{variant}")


def test_a_record_runtime_pack_id_other_than_the_binding(overlay: RepositoryOverlay) -> None:
    overlay.record["variants"]["windows-x86_64-cpu"]["runtimePackId"] = "mavi-runtime-v2-" + "1" * 64
    overlay.write()
    _only(overlay, "qualification_runtime_pack_mismatch:windows-x86_64-cpu")


def test_a_runtime_pack_id_for_the_class_a_variant(overlay: RepositoryOverlay) -> None:
    overlay.record["variants"]["linux-x86_64-cuda"]["runtimePackId"] = "mavi-runtime-v2-" + "1" * 64
    overlay.write()
    _only(overlay, "qualification_runtime_pack_forbidden:linux-x86_64-cuda")


def test_a_missing_record_variant(overlay: RepositoryOverlay) -> None:
    del overlay.record["variants"]["linux-x86_64-cuda"]
    overlay.write()
    _only(overlay, "qualification_variant_missing:linux-x86_64-cuda")


def test_an_unknown_record_variant(overlay: RepositoryOverlay) -> None:
    overlay.record["variants"]["linux-arm64-cuda"] = dict(overlay.record["variants"]["linux-x86_64-cuda"])
    overlay.write()
    _only(overlay, "qualification_variant_unknown:linux-arm64-cuda")


def test_the_class_a_variant_marked_passed(overlay: RepositoryOverlay) -> None:
    # A variant without a Runtime Pack can never pass (P-17 class A stays pending).
    overlay.pass_variant("linux-x86_64-cuda")
    overlay.write()
    _only(overlay, "qualification_pending_variant_claims_pass:linux-x86_64-cuda")


# --------------------------------------------------------------------------- manifests and records


def test_a_binding_naming_no_derivable_manifest(overlay: RepositoryOverlay) -> None:
    overlay.binding["capabilityBindings"][0]["modelPackId"] = "mavi-model-v2-" + "1" * 64
    overlay.write(sync=False)
    _only(overlay, "which no manifest derives")


def test_two_manifests_deriving_one_id(overlay: RepositoryOverlay) -> None:
    shutil.copyfile(overlay.manifest_path, overlay.manifest_path.with_name("copy.json"))
    _only(overlay, "Two manifests derive one modelPackId")


def test_a_shared_pack_directory(overlay: RepositoryOverlay) -> None:
    other = json.loads(overlay.manifest_path.read_text(encoding="utf-8"))
    other["modelId"] = "rtmdet-m-coco-other"
    other["artifacts"][0]["sha256"] = "1" * 64
    overlay.manifest_path.with_name("other.json").write_text(json.dumps(other, indent=2) + "\n", encoding="utf-8")
    _only(overlay, "is shared by")


def test_a_manifest_for_another_family(overlay: RepositoryOverlay) -> None:
    overlay.manifest["runtimeCompatibility"]["runtimePackFamilyIds"] = ["other-family-v1"]
    overlay.write()
    _only(overlay, "is not compatible with family")


def test_a_manifest_input_contract_the_detector_does_not_consume(overlay: RepositoryOverlay) -> None:
    overlay.manifest["inputContract"] = {"kind": "video-frame-rgb"}
    overlay.write()
    _only(overlay, "model_input_contract_unsupported:detector")


def test_a_role_entry_point_the_worker_does_not_run(overlay: RepositoryOverlay) -> None:
    overlay.binding["roles"][0]["entryPoint"] = "mavi_vision.other.main"
    overlay.write()
    _only(overlay, "role_entry_point_unsupported:vision")


def test_a_binding_naming_no_record(overlay: RepositoryOverlay) -> None:
    overlay.binding["capabilityBindings"][0]["qualificationId"] = "rtmdet-m-coco-phase1-v9"
    overlay.write()
    _only(overlay, "which no record declares")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda record: record.update(modelManifestSha256="1" * 64),
        lambda record: record["artifactSha256"].update({"licence-notice": "1" * 64}),
        lambda record: record.update(runtimeProfileSha256="1" * 64),
    ],
    ids=["manifest-sha", "licence-sha", "runtime-profile-sha"],
)
def test_record_identity_drift(overlay: RepositoryOverlay, mutate) -> None:
    mutate(overlay.record)
    overlay.write(sync=False)
    _only(overlay, "qualification_identity_mismatch")


def test_a_record_for_another_model_pack(overlay: RepositoryOverlay) -> None:
    overlay.record["modelPackId"] = "mavi-model-v2-" + "1" * 64
    overlay.write(sync=False)
    _only(overlay, "model_pack_id_mismatch")


def test_a_stale_pipeline_policy(overlay: RepositoryOverlay) -> None:
    overlay.record["policies"]["pipelineProfileSha256"] = "1" * 64
    overlay.write(sync=False)
    _only(overlay, "qualification_policy_mismatch")


def test_a_record_naming_an_unknown_pipeline_profile(overlay: RepositoryOverlay) -> None:
    overlay.record["policies"]["pipelineProfileId"] = "phase1-other-v1"
    overlay.write(sync=False)
    _only(overlay, "names unknown pipeline profile")


def test_a_pipeline_profile_for_an_unknown_model(overlay: RepositoryOverlay) -> None:
    raw = json.loads(overlay.pipeline_path.read_text(encoding="utf-8"))
    raw["modelId"] = "other-model"
    overlay.pipeline_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    overlay.write()
    _only(overlay, "references unknown modelId other-model")


def test_an_unbound_record(overlay: RepositoryOverlay) -> None:
    other = dict(overlay.record, qualificationId="rtmdet-m-coco-phase1-v9")
    (overlay.record_path.with_name("other.json")).write_text(json.dumps(other, indent=2) + "\n", encoding="utf-8")
    _only(overlay, "is bound by no capability binding")


def test_a_network_locator_in_the_binding(overlay: RepositoryOverlay) -> None:
    overlay.binding["bindingId"] = "https://example.invalid/binding"
    overlay.write()
    _only(overlay, "online resolver locator")


# --------------------------------------------------------------------------- retained anti-promotion rules (§6.6)


def test_an_unverified_manifest_claiming_a_qualification(overlay: RepositoryOverlay) -> None:
    overlay.manifest["qualificationId"] = overlay.record["qualificationId"]
    overlay.write()
    _only(overlay, "must not claim a qualification ID")


def test_a_verified_manifest_requires_a_qualified_runtime_profile(overlay: RepositoryOverlay) -> None:
    overlay.manifest["verificationStatus"] = "verified"
    overlay.manifest["qualificationId"] = overlay.record["qualificationId"]
    overlay.manifest["licence"]["reviewStatus"] = "approved"
    overlay.write()
    assert overlay.runtime["qualificationStatus"] == "partial"
    _only(overlay, "requires a qualified runtime profile")


def test_a_record_bound_to_an_unverified_manifest_stays_pending(overlay: RepositoryOverlay) -> None:
    overlay.pass_variant("windows-x86_64-cpu")
    overlay.write()
    _only(overlay, "must remain pending while manifest")


def test_the_committed_record_is_bound_to_the_committed_binding_and_pending() -> None:
    """The live facts the rules above protect, stated once."""
    root = Path(__file__).parents[3]
    record = json.loads((root / "models/qualifications/rtmdet-m-coco-phase1-v2.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "models/manifests/rtmdet-m-coco-phase1-v2.json").read_text(encoding="utf-8"))
    assert manifest["verificationStatus"] == "unverified" and manifest["qualificationId"] is None
    assert record["overallResult"] == "pending"
    assert record["variants"]["linux-x86_64-cuda"]["runtimePackId"] is None
    assert record["runtimeProfileSha256"] == sha256_bytes(
        (root / "src/vision/runtime/mmdetection-phase1-v1/runtime.json").read_bytes()
    )


def test_p17_class_a_with_a_wheelhouse_lock_status(overlay: RepositoryOverlay) -> None:
    overlay.runtime["releaseLocks"]["linux-x86_64-cuda"] = {"status": "pending-wheelhouse-freeze"}
    overlay.write()
    _only(overlay, "runtime_variant_classification_invalid:linux-x86_64-cuda")
