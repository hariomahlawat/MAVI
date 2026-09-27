from __future__ import annotations

import copy
import json

import pytest

from mavi_vision.runtime.manifest import ReleaseMetadataError
from mavi_vision.runtime.model_manifest_v2 import load_model_manifest_v2, parse_model_manifest_v2
from mavi_vision.runtime.model_pack_identity import (
    ModelPackArtifactIdentity,
    ModelPackIdentityInputsV2,
    model_pack_id_v2,
)
from tests.component_binding_v2_fixtures import FIXTURES, REPOSITORY, baseline


def _detector() -> dict:
    return json.loads((FIXTURES / "detector-fixture-v2.json").read_text(encoding="utf-8"))


def _code(document: object) -> str:
    with pytest.raises(ReleaseMetadataError) as error:
        parse_model_manifest_v2(document)
    return error.value.code


def test_generated_rtmdet_manifest_is_capability_neutral_with_a_detector_section() -> None:
    manifest = parse_model_manifest_v2(baseline("manifest"))
    assert manifest.capability_ids == ("detector",)
    assert [artifact.artifact_role for artifact in manifest.artifacts] == ["checkpoint", "licence-notice", "resolved-config"]
    assert manifest.pack_directory == "rtmdet-m-coco-phase1-v1"
    assert manifest.verification_status == "unverified" and manifest.qualification_id is None
    assert manifest.licence_review_status == "pending-review"
    section = manifest.detector_section()
    assert section.checkpoint.sha256 == "229f527ca88498e8894a778a62a878a322b4a3ea2cae09ea537d34b7e907792b"
    assert section.resolved_config.sha256 == "377d9f57abf6a73a6c308f765b70fc571715448c62998819d609d2eebc7c5ee3"


def test_model_pack_id_is_derived_not_authored() -> None:
    manifest = parse_model_manifest_v2(_detector())
    expected = model_pack_id_v2(
        ModelPackIdentityInputsV2(
            model_id="detector-fixture",
            model_version="0.0.1",
            capability_ids=("detector",),
            artifacts=tuple(ModelPackArtifactIdentity(a.artifact_role, a.sha256) for a in manifest.artifacts),
        )
    )
    assert manifest.model_pack_id == expected


def test_embedding_fixture_loads_without_any_detector_field() -> None:
    manifest = load_model_manifest_v2(FIXTURES / "embedding-fixture-v2.json")
    assert manifest.capability_ids == ("embedding",)
    assert "detector" not in manifest.capability_specific
    with pytest.raises(ReleaseMetadataError) as error:
        manifest.detector_section()
    assert error.value.code == "capability_section_missing:detector"


def test_authored_model_pack_id_is_rejected() -> None:
    document = _detector()
    document["modelPackId"] = "mavi-model-v2-" + "0" * 64
    assert _code(document) == "model_manifest_invalid"


def test_authored_byte_size_is_rejected() -> None:
    document = _detector()
    document["artifacts"][0]["sizeBytes"] = 1024
    assert _code(document) == "model_manifest_invalid"


@pytest.mark.parametrize("schema", ["1.0", 2, "2", None])
def test_wrong_or_v1_schema_version_is_rejected(schema) -> None:
    document = _detector()
    document["schemaVersion"] = schema
    assert _code(document) == "model_manifest_schema_unsupported"


def test_v1_manifest_is_rejected() -> None:
    from tests.component_binding_v2_fixtures import V1_MANIFEST

    assert _code(json.loads(V1_MANIFEST.read_text(encoding="utf-8"))) == "model_manifest_schema_unsupported"


@pytest.mark.parametrize(("mutate", "code"), [
    (lambda d: d["licence"].update(noticeArtifactRole="missing"), "model_licence_notice_role_invalid"),
    # the notice cannot be re-pointed at another artefact (review P2-1)
    (lambda d: (d["licence"].update(noticeArtifactRole="checkpoint"), d["artifacts"].pop(1)), "model_licence_notice_role_invalid"),
    (lambda d: d["capabilitySpecific"]["detector"].update(resolvedConfigArtifactRole="checkpoint"), "detector_section_artifact_roles_invalid"),
    (lambda d: d["capabilitySpecific"]["detector"].update(checkpointArtifactRole="licence-notice"), "detector_section_artifact_roles_invalid"),
    # identity-bearing text is restricted so one name cannot have two encodings
    (lambda d: d.update(modelId="Detector Fixture"), "model_id_invalid"),
    (lambda d: d.update(modelId="d\u00e9tecteur"), "model_id_invalid"),
    (lambda d: d.update(modelVersion="1.0 beta"), "model_version_invalid"),
    (lambda d: d["capabilitySpecific"]["detector"]["classVocabulary"].append("pe\nrson"), "model_vocabulary_entry_invalid"),
    (lambda d: d["artifacts"].pop(1), "model_licence_notice_missing"),
    (lambda d: d.update(capabilityIds=["embedding", "detector"]), "model_capabilities_unordered_or_duplicate"),
    (lambda d: d.update(capabilityIds=["detector", "detector"]), "model_capabilities_unordered_or_duplicate"),
    (lambda d: d.update(capabilityIds=[]), "model_capabilities_empty"),
    (lambda d: d.update(capabilityIds=["face-recognition"]), "capability_unknown:face-recognition"),
    (lambda d: d["artifacts"][1].update(artifactRole="checkpoint"), "model_artifact_role_duplicate"),
    (lambda d: d["artifacts"][1].update(relativePath="detector-fixture-v1/model.pth"), "model_artifact_path_duplicate"),
    (lambda d: d["artifacts"][1].update(relativePath="other-pack/LICENSE"), "model_pack_directory_not_unique"),
    (lambda d: d["artifacts"][1].update(relativePath="LICENSE"), "model_artifact_path_invalid"),
    (lambda d: d["artifacts"][1].update(relativePath="detector-fixture-v1/../LICENSE"), "model_artifact_path_invalid"),
    (lambda d: d["artifacts"][1].update(sha256="A" * 64), "model_artifact_sha256_invalid"),
    (lambda d: d["artifacts"][1].update(artifactRole="Licence"), "model_artifact_role_invalid"),
    (lambda d: d.update(capabilitySpecific={}), "capability_section_missing:detector"),
    (lambda d: d["capabilitySpecific"]["detector"].update(checkpointArtifactRole="weights"), "detector_section_artifact_missing"),
    (lambda d: d["capabilitySpecific"]["detector"].update(extra=True), "capability_section_invalid:detector"),
    (lambda d: d["capabilitySpecific"].update(embedding={"dimension": 8}), "capability_section_unbound:embedding"),
    (lambda d: d.update(capabilityIds=["detector", "ocr"], capabilitySpecific={**d["capabilitySpecific"], "ocr": {}}), "capability_section_unsupported:ocr"),
    (lambda d: d.update(verificationStatus="verified"), "verified_manifest_requires_qualification"),
    (lambda d: d.update(verificationStatus="verified", qualificationId="q"), "verified_manifest_requires_licence_approval"),
    (lambda d: d.update(purpose="phase1"), "model_manifest_invalid"),
    (lambda d: d.update(checkpoint={"relativePath": "a/b", "sha256": "0" * 64}), "model_manifest_invalid"),
])
def test_manifest_rules_fail_closed(mutate, code) -> None:
    document = _detector()
    mutate(document)
    assert _code(document) == code


@pytest.mark.parametrize(("dimension", "code"), [
    (0, "embedding_section_invalid"),
    ("512", "capability_section_invalid:embedding"),
    (512.0, "capability_section_invalid:embedding"),
    (True, "capability_section_invalid:embedding"),
])
def test_embedding_section_must_be_well_formed(dimension, code) -> None:
    document = json.loads((FIXTURES / "embedding-fixture-v2.json").read_text(encoding="utf-8"))
    broken = copy.deepcopy(document)
    broken["capabilitySpecific"]["embedding"]["dimension"] = dimension
    assert _code(broken) == code


def test_duplicate_json_key_is_rejected(tmp_path) -> None:
    path = tmp_path / "manifest.json"
    text = (FIXTURES / "detector-fixture-v2.json").read_text(encoding="utf-8")
    path.write_text(text.replace('"verificationStatus": "unverified",', '"verificationStatus": "verified", "verificationStatus": "unverified",'), encoding="utf-8")
    with pytest.raises(ReleaseMetadataError) as error:
        load_model_manifest_v2(path)
    assert error.value.code == "model_manifest_invalid"


def test_capability_sections_are_deeply_immutable() -> None:
    manifest = parse_model_manifest_v2(_detector())
    vocabulary = manifest.capability_specific["detector"]["classVocabulary"]
    assert isinstance(vocabulary, tuple)
    with pytest.raises(TypeError):
        manifest.capability_specific["detector"]["backend"] = "other"  # type: ignore[index]


@pytest.mark.parametrize("field", ["publisher", "sourceRepository", "sourceRevision"])
@pytest.mark.parametrize("value", [
    "http://example.invalid/repo",
    "https://example.invalid/repo",
    "HTTPS://EXAMPLE.INVALID/REPO",
    "git+ssh://example.invalid/repo",
    "ssh://example.invalid/repo",
    "ftp://example.invalid/file",
    "s3://bucket/key",
    "hf://org/model",
    "mim://mmdet/model",
    "modelzoo://rtmdet",
    "torchvision://weights",
    "openmmlab://rtmdet",
])
def test_provenance_cannot_encode_a_network_locator(field, value) -> None:
    document = _detector()
    document["provenance"][field] = value
    assert _code(document) == "model_provenance_network_locator"


def test_provenance_rule_covers_every_release_locator() -> None:
    from mavi_vision.runtime.manifest import RELEASE_NETWORK_LOCATORS

    for locator in RELEASE_NETWORK_LOCATORS:
        document = _detector()
        document["provenance"]["sourceRepository"] = f"{locator}example"
        assert _code(document) == "model_provenance_network_locator", locator


def test_plain_repository_identifier_is_accepted() -> None:
    manifest_document = baseline("manifest")
    assert manifest_document["provenance"]["sourceRepository"] == "open-mmlab/mmdetection"
    parse_model_manifest_v2(manifest_document)


def test_verify_repo_uses_the_one_locator_rule() -> None:
    import importlib.util

    from mavi_vision.runtime import manifest

    spec = importlib.util.spec_from_file_location("verify_repo_s2a1", REPOSITORY / "tools" / "verify_repo.py")
    assert spec is not None and spec.loader is not None
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    assert not hasattr(verifier, "RELEASE_NETWORK_LOCATORS")
    for locator in manifest.RELEASE_NETWORK_LOCATORS:
        assert verifier.find_release_network_hazard(f"x {locator}y") == locator
    assert verifier.find_release_network_hazard("open-mmlab/mmdetection") is None
