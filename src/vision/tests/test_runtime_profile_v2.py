from __future__ import annotations

import pytest

from mavi_vision.runtime.manifest import ReleaseMetadataError
from mavi_vision.runtime.runtime_profile_v2 import classify_runtime_variants, parse_runtime_profile_v2
from mavi_vision.runtime.variants import VariantClass
from tests.component_binding_v2_fixtures import baseline

TRACKED_LOCKS = ("linux-x86_64-cpu", "windows-x86_64-cpu", "windows-x86_64-cuda")
DEV_EVIDENCE = {
    "capturedAtUtc": "2026-09-19T10:46:36Z",
    "evidenceBundleSha256": "b" * 64,
    "hostObservationSha256": "e" * 64,
    "operatorReference": "fixture-host",
    "sourceHeadSha": "3" * 40,
}


def _code(document) -> str:
    with pytest.raises(ReleaseMetadataError) as error:
        parse_runtime_profile_v2(document)
    return error.value.code


def test_generated_profile_carries_no_model_identity_and_is_family_identity() -> None:
    document = baseline("runtimeProfile")
    assert "checkpoint" not in document and "resolvedConfig" not in document
    assert all("resolvedConfigSha256" not in v for v in document["platformVariants"].values())
    profile = parse_runtime_profile_v2(document)
    assert profile.runtime_pack_family_id == profile.runtime_profile_id == "mmdetection-phase1-v1"


def test_repository_variants_classify_linux_cuda_as_known_not_releasable() -> None:
    classes = classify_runtime_variants(parse_runtime_profile_v2(baseline("runtimeProfile")), tracked_lock_variants=TRACKED_LOCKS)
    assert dict(classes) == {
        "linux-x86_64-cpu": VariantClass.DEPLOYABLE,
        "windows-x86_64-cpu": VariantClass.DEPLOYABLE,
        "windows-x86_64-cuda": VariantClass.DEPLOYABLE,
        "linux-x86_64-cuda": VariantClass.KNOWN_NOT_RELEASABLE,
    }


@pytest.mark.parametrize(("mutate", "code"), [
    (lambda d: d.update(checkpoint={"publisher": "x", "artifact": "a/b", "sha256": "0" * 64}), "runtime_profile_invalid"),
    (lambda d: d.update(resolvedConfig={}), "runtime_profile_invalid"),
    (lambda d: d["platformVariants"]["windows-x86_64-cpu"].update(resolvedConfigSha256="0" * 64), "runtime_profile_invalid"),
    (lambda d: d["platformVariants"].pop("linux-x86_64-cuda"), "runtime_platform_variants_incomplete"),
    (lambda d: d["releaseLocks"].pop("linux-x86_64-cuda"), "runtime_release_locks_incomplete"),
    (lambda d: d["releaseLocks"].update({"linux-x86_64-cuda": {"status": "pending-wheelhouse-freeze"}}), "runtime_variant_classification_invalid:linux-x86_64-cuda"),
    (lambda d: d["platformVariants"]["windows-x86_64-cpu"].pop("pythonIdentity"), "runtime_platform_evidence_required"),
    (lambda d: d.update(qualificationStatus="qualified"), "runtime_qualified_with_pending_gate"),
    (lambda d: d.update(runtimeProfileId="Mmdet Phase1"), "runtime_profile_id_invalid"),
])
def test_runtime_profile_rules_fail_closed(mutate, code) -> None:
    document = baseline("runtimeProfile")
    mutate(document)
    assert _code(document) == code


@pytest.mark.parametrize("schema", ["1.0", 2, "2"])
def test_v1_or_malformed_schema_version_is_rejected(schema) -> None:
    document = baseline("runtimeProfile")
    document["schemaVersion"] = schema
    assert _code(document) == "runtime_profile_schema_unsupported"


def test_mutation_guard_non_pending_variant_without_lock_file_is_not_class_a() -> None:
    # Loader-valid: linux CUDA as qualified-development-hardware with full evidence,
    # release lock still pending, and no lock file. Dropping the variant-status
    # requirement from class A would accept it as class A.
    document = baseline("runtimeProfile")
    reference = document["platformVariants"]["windows-x86_64-cuda"]
    document["platformVariants"]["linux-x86_64-cuda"] = {
        "status": "qualified-development-hardware",
        "pythonIdentity": {**reference["pythonIdentity"], "version": reference["pythonIdentity"]["version"]},
        "binaryVersions": reference["binaryVersions"],
        "developmentEvidence": DEV_EVIDENCE,
    }
    profile = parse_runtime_profile_v2(document)
    with pytest.raises(ReleaseMetadataError) as error:
        classify_runtime_variants(profile, tracked_lock_variants=TRACKED_LOCKS)
    assert error.value.code == "runtime_variant_classification_invalid:linux-x86_64-cuda"


def test_lock_file_for_a_pending_variant_is_inconsistent() -> None:
    profile = parse_runtime_profile_v2(baseline("runtimeProfile"))
    with pytest.raises(ReleaseMetadataError) as error:
        classify_runtime_variants(profile, tracked_lock_variants=(*TRACKED_LOCKS, "linux-x86_64-cuda"))
    assert error.value.code == "runtime_variant_classification_invalid:linux-x86_64-cuda"


def test_deployable_variant_without_lock_file_is_inconsistent() -> None:
    profile = parse_runtime_profile_v2(baseline("runtimeProfile"))
    with pytest.raises(ReleaseMetadataError) as error:
        classify_runtime_variants(profile, tracked_lock_variants=("linux-x86_64-cpu", "windows-x86_64-cuda"))
    assert error.value.code == "runtime_variant_classification_invalid:windows-x86_64-cpu"


def test_lock_file_for_unknown_variant_is_rejected() -> None:
    profile = parse_runtime_profile_v2(baseline("runtimeProfile"))
    with pytest.raises(ReleaseMetadataError) as error:
        classify_runtime_variants(profile, tracked_lock_variants=(*TRACKED_LOCKS, "linux-arm64-cpu"))
    assert error.value.code == "runtime_variant_unknown:linux-arm64-cpu"
