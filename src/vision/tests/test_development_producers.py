"""Stage-3 Development producers (ADR-014 note 2026-10-06): identities, rules, fence and attestation.

Two Development replacement bindings, ``a2-scale640`` and ``a2-scale1280``, run the
one A2 Development pipeline profile and differ causally only in the detector Model
Pack (test Resize/Pad 640 vs 1280). The release binding, profile, Model Pack and
qualification record must stay byte-identical; a Development producer must never
resolve in Production; and each producer's attestation must carry its own binding
and Model Pack identity with the same pipeline-profile SHA.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from mavi_vision.runtime.binding import load_component_binding
from mavi_vision.runtime.development_binding import (
    check_release_binding_pin,
    check_replacement_binding,
    load_development_producers,
    parse_development_producers,
)
from mavi_vision.runtime.interfaces import RuntimeMetadata
from mavi_vision.runtime.manifest import ReleaseMetadataError
from mavi_vision.runtime.model_manifest_v2 import load_model_manifest_v2
from mavi_vision.runtime.profile import load_pipeline_profile
from mavi_vision.runtime.provenance import build_runtime_provenance
from mavi_vision.runtime.qualification_v2 import load_capability_gate_sets, load_qualification_record_v2
from tests.component_binding_v2_fixtures import REPOSITORY
from tests.development_producer_overlay import (
    A2_PROFILE,
    DevelopmentRepository,
    make_producer,
    write_json,
)
from tests.resolver_overlay import Overlay, _dump, sha256_bytes
from tests.test_runtime_provenance import LIVE_VERSIONS, _platform

RELEASE_BINDING = REPOSITORY / "src/vision/config/components/phase1-bindings-v2.json"
RELEASE_PROFILE = REPOSITORY / "src/vision/config/pipelines/phase1-detection-tracking-v1.json"
RELEASE_MANIFEST = REPOSITORY / "models/manifests/rtmdet-m-coco-phase1-v2.json"
RELEASE_RECORD = REPOSITORY / "models/qualifications/rtmdet-m-coco-phase1-v2.json"
REGISTRY = REPOSITORY / "src/vision/config/development-producers-v1.json"
MANIFEST_1280 = REPOSITORY / "models/manifests/rtmdet-m-coco-phase1-scale1280-v2.json"
RECORD_640 = REPOSITORY / "models/qualifications/rtmdet-m-coco-phase1-a2-scale640-dev-v1.json"
RECORD_1280 = REPOSITORY / "models/qualifications/rtmdet-m-coco-phase1-a2-scale1280-dev-v1.json"
GATE_SETS = REPOSITORY / "config/acceptance/capability-gate-sets-v1.json"

# The release identity this slice must not move (PR #173 baseline, main@864ddfe4).
RELEASE_SHA256 = {
    RELEASE_BINDING: "7ef226193232b90b0a20f8648a95f21e0bbc9416b353605c9be6d81262abe205",
    RELEASE_PROFILE: "afb03b6c4da61fbf6021ef855307f80c5b7206996e7e21c8d297394b091a18bf",
    RELEASE_MANIFEST: "bc8127c1c00513a90f1b00325dcae3d4f31243ef1ce04ebe38350f945cb79c90",
    RELEASE_RECORD: "2c2ba3d674cebf18955af1b224ef41c8c1a1fbc189cc28a6d605436c46c2a224",
}
RELEASE_PACK = "mavi-model-v2-86754e364c7560c407b531900de58eb5e66fd365685677f8f24a5a61b3186700"

VERIFY_REPO_PATH = REPOSITORY / "tools" / "verify_repo.py"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _diff(left: object, right: object, path: str = "") -> dict[str, tuple[object, object]]:
    if isinstance(left, dict) and isinstance(right, dict):
        out: dict[str, tuple[object, object]] = {}
        for key in sorted(set(left) | set(right)):
            out.update(_diff(left.get(key, "<absent>"), right.get(key, "<absent>"), f"{path}.{key}" if path else key))
        return out
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        out = {}
        for index, (a, b) in enumerate(zip(left, right)):
            out.update(_diff(a, b, f"{path}[{index}]"))
        return out
    return {} if left == right and type(left) is type(right) else {path: (left, right)}


# =========================================================================== tracked identities


def test_the_release_identity_is_byte_identical() -> None:
    for path, expected in RELEASE_SHA256.items():
        assert _sha(path) == expected, path


def test_the_registry_pins_the_release_binding_and_declares_both_producers() -> None:
    producers = load_development_producers(REGISTRY)
    release = load_component_binding(RELEASE_BINDING)
    check_release_binding_pin(
        producers,
        release_binding_path="src/vision/config/components/phase1-bindings-v2.json",
        release_binding_sha256=release.component_binding_sha256,
    )
    assert [item.producer_id for item in producers.producers] == ["a2-scale640", "a2-scale1280"]
    assert {item.pipeline_profile_path for item in producers.producers} == {
        "src/vision/config/pipelines/phase1-detection-tracking-a2-v1.json"
    }
    for item in producers.producers:
        assert item.replaces == frozenset({("vision", "detector")})
        candidate = load_component_binding(REPOSITORY / item.binding_path)
        check_replacement_binding(release=release, candidate=candidate, replaces=item.replaces)


def test_the_a2_profile_is_the_release_profile_with_activation_061_and_a_development_identity() -> None:
    differences = _diff(_json(RELEASE_PROFILE), _json(A2_PROFILE))
    assert differences == {
        "schemaVersion": ("1.2", "1.3"),
        "profileId": ("phase1-detection-tracking-v1", "phase1-detection-tracking-a2"),
        "profileVersion": ("1.3.0-candidate", "1.0.0-development"),
        "developmentOnly": ("<absent>", True),
        "tracker.trackActivationThreshold": (0.7, 0.61),
    }
    profile = load_pipeline_profile(A2_PROFILE)
    assert profile.development_only is True
    assert load_pipeline_profile(RELEASE_PROFILE).development_only is False
    tracker = profile.tracker
    assert (tracker.high_confidence_threshold, tracker.track_activation_threshold, tracker.minimum_iou_threshold,
            tracker.minimum_consecutive_frames, tracker.lost_track_buffer_seconds, tracker.reference_frame_rate) == (
        0.6, 0.61, 0.1, 2, 1.0, 30.0)


def test_the_1280_manifest_differs_from_the_base_only_in_version_pack_directory_and_resolved_config() -> None:
    base, scaled = _json(RELEASE_MANIFEST), _json(MANIFEST_1280)
    differences = _diff(base, scaled)
    assert set(differences) == {
        "modelVersion",
        "artifacts[0].relativePath",
        "artifacts[1].relativePath",
        "artifacts[2].relativePath",
        "artifacts[2].sha256",
        "provenance.publisher",
    }
    by_role = {item["artifactRole"]: item for item in scaled["artifacts"]}
    base_by_role = {item["artifactRole"]: item for item in base["artifacts"]}
    for role in ("checkpoint", "licence-notice"):
        assert by_role[role]["sha256"] == base_by_role[role]["sha256"]
    assert by_role["resolved-config"]["sha256"] == "6ef856f49ef450242c9ef855fcbf21a5d8ef5db3ba92d10f201cd3778e382047"
    assert base_by_role["resolved-config"]["sha256"] == "377d9f57abf6a73a6c308f765b70fc571715448c62998819d609d2eebc7c5ee3"
    manifest = load_model_manifest_v2(MANIFEST_1280)
    assert manifest.model_id == load_model_manifest_v2(RELEASE_MANIFEST).model_id
    assert manifest.model_pack_id != RELEASE_PACK
    assert manifest.verification_status == "unverified" and manifest.qualification_id is None


def test_both_development_records_are_pending_and_pin_the_one_a2_profile() -> None:
    gate_sets = load_capability_gate_sets(GATE_SETS)
    a2_sha = _sha(A2_PROFILE)
    for path, manifest_path in ((RECORD_640, RELEASE_MANIFEST), (RECORD_1280, MANIFEST_1280)):
        document = _json(path)
        assert document["overallResult"] == "pending"
        assert document["qualifiedProfiles"] == [] and document["profileQualifications"] == {} and document["evidence"] == {}
        assert "supersedes" not in document
        for variant in document["variants"].values():
            assert variant["status"] == "pending" and set(variant["gates"].values()) == {"pending"}
        record = load_qualification_record_v2(path, gate_sets=gate_sets)
        assert (record.pipeline_profile_id, record.pipeline_profile_sha256) == ("phase1-detection-tracking-a2", a2_sha)
        assert record.model_pack_id == load_model_manifest_v2(manifest_path).model_pack_id
        assert record.model_manifest_sha256 == _sha(manifest_path)
    # The 640 comparator reuses the release Model Pack bytes; only its policy pin differs.
    assert _json(RECORD_640)["modelPackId"] == RELEASE_PACK == _json(RELEASE_RECORD)["modelPackId"]
    release_record = _json(RELEASE_RECORD)
    assert set(_diff(release_record, _json(RECORD_640))) == {
        "qualificationId",
        "policies.pipelineProfileId",
        "policies.pipelineProfileSha256",
        "supersedes",
    }


def test_the_two_producer_bindings_differ_only_in_identity_and_the_detector_pack() -> None:
    producers = load_development_producers(REGISTRY)
    scale640 = REPOSITORY / producers.producer("a2-scale640").binding_path
    scale1280 = REPOSITORY / producers.producer("a2-scale1280").binding_path
    assert set(_diff(_json(scale640), _json(scale1280))) == {
        "bindingId",
        "capabilityBindings[0].modelPackId",
        "capabilityBindings[0].qualificationId",
    }
    shas = {_sha(scale640), _sha(scale1280), _sha(RELEASE_BINDING)}
    assert len(shas) == 3
    assert load_component_binding(scale640).capability_bindings[0].model_pack_id == RELEASE_PACK
    assert load_component_binding(scale1280).capability_bindings[0].model_pack_id == load_model_manifest_v2(MANIFEST_1280).model_pack_id


# =========================================================================== schema 1.3 profiles


@pytest.mark.parametrize(
    "mutate",
    [
        lambda doc: doc.pop("developmentOnly"),
        lambda doc: doc.update(developmentOnly="true"),
        lambda doc: doc.update(developmentOnly=1),
        lambda doc: doc.update(schemaVersion="1.2"),
    ],
    ids=["1.3-without-flag", "string-flag", "integer-flag", "1.2-with-flag"],
)
def test_the_development_flag_is_required_by_13_and_refused_by_12(tmp_path: Path, mutate) -> None:
    document = _json(A2_PROFILE)
    mutate(document)
    path = tmp_path / "profile.json"
    write_json(path, document)
    with pytest.raises(ReleaseMetadataError, match="pipeline_profile_invalid"):
        load_pipeline_profile(path)


# =========================================================================== replacement rules


def _release():
    return load_component_binding(RELEASE_BINDING)


def _candidate(tmp_path: Path, mutate) -> object:
    document = _json(REPOSITORY / "src/vision/config/components/development-phase1-a2-scale1280-v1.json")
    mutate(document)
    path = tmp_path / "candidate.json"
    write_json(path, document)
    return load_component_binding(path)


DETECTOR = frozenset({("vision", "detector")})


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda doc: doc.update(bindingId="phase1-a2-scale1280-v1"), "development_binding_id_invalid"),
        (lambda doc: doc["runtimePacks"][0]["variants"]["windows-x86_64-cpu"].update(nativeAbi="other-abi"), "development_binding_runtime_packs_changed"),
        (lambda doc: doc["roles"][0].update(entryPoint="mavi_vision.other.main"), "development_binding_roles_changed"),
        (lambda doc: doc["roles"][0].update(provenanceContract="vision-job-complete-v3.2"), "development_binding_roles_changed"),
        (lambda doc: doc["capabilityBindings"][0].update(enabled=False), "development_binding_capability_disabled:vision:detector"),
        (lambda doc: doc["capabilityBindings"][0].update(qualificationId="rtmdet-m-coco-phase1-v2"), "development_binding_reuses_release_qualification:vision:detector"),
    ],
    ids=["id-prefix", "runtime-pack", "entry-point", "provenance-contract", "disabled", "release-record"],
)
def test_a_replacement_binding_changes_only_the_declared_capability(tmp_path: Path, mutate, code: str) -> None:
    with pytest.raises(ReleaseMetadataError, match=f"^{code}$"):
        check_replacement_binding(release=_release(), candidate=_candidate(tmp_path, mutate), replaces=DETECTOR)


def test_an_undeclared_capability_replacement_is_refused(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path, lambda doc: None)
    with pytest.raises(ReleaseMetadataError, match="^development_binding_capability_unauthorised:vision:detector$"):
        check_replacement_binding(release=_release(), candidate=candidate, replaces=frozenset())


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda doc: doc["producers"][0]["replaces"].append({"roleId": "attributes", "capabilityId": "person-attributes"}), "development_binding_capability_unauthorised:attributes:person-attributes"),
        (lambda doc: doc["producers"][0].update(bindingPath="src/vision/config/components/phase1-a2-scale640-v1.json"), "development_producers_path_invalid"),
        (lambda doc: doc["producers"][0].update(bindingPath="src/vision/config/development-phase1-a2-scale640-v1.json"), "development_producers_path_invalid"),
        (lambda doc: doc["producers"][0].update(pipelineProfilePath="../phase1-detection-tracking-a2-v1.json"), "development_producers_path_invalid"),
        (lambda doc: doc["producers"][1].update(producerId="a2-scale640"), "development_producers_duplicate:producer_id"),
        (lambda doc: doc["producers"][1].update(bindingPath=doc["producers"][0]["bindingPath"]), "development_producers_duplicate:binding_path"),
        (lambda doc: doc["producers"][0].update(replaces=[]), "development_producers_invalid:replaces:a2-scale640"),
        (lambda doc: doc["releaseBinding"].update(path="src/vision/config/components/development-phase1-a2-scale640-v1.json"), "development_producers_release_binding_invalid"),
        (lambda doc: doc.update(producers=[]), "development_producers_invalid:producers"),
        (lambda doc: doc.update(schemaVersion="mavi-vision-development-producers-v2"), "development_producers_schema_unsupported"),
    ],
    ids=["attributes", "no-prefix", "wrong-directory", "traversal", "duplicate-id", "duplicate-binding", "no-replacement", "release-is-development", "empty", "schema"],
)
def test_the_registry_constrains_what_may_be_declared(mutate, code: str) -> None:
    document = _json(REGISTRY)
    mutate(document)
    with pytest.raises(ReleaseMetadataError, match=f"^{code}"):
        parse_development_producers(document)


def test_a_stale_or_foreign_release_pin_is_refused() -> None:
    producers = load_development_producers(REGISTRY)
    with pytest.raises(ReleaseMetadataError, match="^development_producers_release_binding_stale$"):
        check_release_binding_pin(producers, release_binding_path=producers.release_binding_path, release_binding_sha256="1" * 64)
    with pytest.raises(ReleaseMetadataError, match="^development_producers_release_binding_mismatch$"):
        check_release_binding_pin(producers, release_binding_path="src/vision/config/components/other.json",
                                  release_binding_sha256=producers.release_binding_sha256)


# =========================================================================== verify_repo


def _load_verify_repo():
    spec = importlib.util.spec_from_file_location("verify_repo_development_producers", VERIFY_REPO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFY = _load_verify_repo()


@pytest.fixture
def repository(tmp_path: Path) -> DevelopmentRepository:
    return DevelopmentRepository.create(tmp_path)


def _errors(repository: DevelopmentRepository) -> list[str]:
    errors: list[str] = []
    VERIFY.check_vision_release_metadata(errors, root=repository.root, tracked=repository.tracked())
    return errors


def _only(repository: DevelopmentRepository, fragment: str) -> None:
    errors = _errors(repository)
    assert errors, "the mutation was not detected"
    assert any(fragment in error for error in errors), errors


def test_the_development_fixture_baseline_is_clean(repository: DevelopmentRepository) -> None:
    assert _errors(repository) == []


def test_an_undeclared_second_binding_still_fails(repository: DevelopmentRepository) -> None:
    write_json(repository.binding_path.with_name("development-phase1-undeclared-v1.json"), repository.binding)
    _only(repository, "binding_multiple_not_supported")


def test_a_declared_binding_that_is_not_tracked_fails(repository: DevelopmentRepository) -> None:
    repository.binding_path.unlink()
    _only(repository, "development_binding_missing")


def test_a_development_profile_that_is_not_development_only_fails(repository: DevelopmentRepository) -> None:
    document = _json(repository.profile_path)
    document["developmentOnly"] = False
    write_json(repository.profile_path, document)
    repository.record["policies"]["pipelineProfileSha256"] = sha256_bytes(repository.profile_path.read_bytes())
    repository.write()
    _only(repository, "development_binding_profile_not_development")


def test_a_record_that_pins_other_profile_bytes_fails(repository: DevelopmentRepository) -> None:
    repository.record["policies"]["pipelineProfileSha256"] = "1" * 64
    repository.write()
    _only(repository, "qualification_policy_mismatch")


def test_a_record_that_pins_the_release_profile_fails(repository: DevelopmentRepository) -> None:
    repository.record["policies"] = dict(repository.overlay.record["policies"])
    repository.write()
    _only(repository, "development_binding_profile_mismatch")


def test_a_binding_to_a_model_pack_no_manifest_derives_fails(repository: DevelopmentRepository) -> None:
    repository.binding["capabilityBindings"][0]["modelPackId"] = "mavi-model-v2-" + "1" * 64
    repository.write()
    _only(repository, "which no manifest derives")


def test_a_record_for_another_model_pack_fails(repository: DevelopmentRepository) -> None:
    repository.record["modelPackId"] = "mavi-model-v2-" + "1" * 64
    repository.write()
    _only(repository, "model_pack_id_mismatch")


def test_a_record_whose_resolved_config_is_not_the_manifest_fails(repository: DevelopmentRepository) -> None:
    repository.record["artifactSha256"]["resolved-config"] = "1" * 64
    repository.write()
    _only(repository, "qualification_identity_mismatch")


def test_a_development_binding_that_changes_a_role_fails(repository: DevelopmentRepository) -> None:
    repository.binding["roles"][0]["provenanceContract"] = "vision-job-complete-v3.2"
    repository.write()
    _only(repository, "development_binding_roles_changed")


def test_a_registry_that_replaces_an_unauthorised_capability_fails(repository: DevelopmentRepository) -> None:
    repository.registry["producers"][0]["replaces"].append({"roleId": "vision", "capabilityId": "person-attributes"})
    repository.write()
    _only(repository, "development_binding_capability_unauthorised:vision:person-attributes")


def test_a_stale_release_pin_fails(repository: DevelopmentRepository) -> None:
    # The release binding moves after the registry was pinned to it (the registry is not re-pinned).
    repository.overlay.binding["bindingId"] = "phase1-v3"
    repository.overlay.write()
    _only(repository, "development_producers_release_binding_stale")


def test_a_missing_release_base_fails(repository: DevelopmentRepository) -> None:
    repository.registry["releaseBinding"]["path"] = "src/vision/config/components/phase1-bindings-v3.json"
    repository.write()
    _only(repository, "development_producers_release_binding_mismatch")


def test_the_release_binding_may_not_run_a_development_profile(repository: DevelopmentRepository) -> None:
    overlay = repository.overlay
    overlay.record["policies"] = dict(repository.record["policies"])
    overlay.write(sync=False)
    repository.write()
    _only(repository, "release_binding_development_profile")


def test_a_second_pack_of_one_model_needs_its_own_version(repository: DevelopmentRepository) -> None:
    other = copy.deepcopy(repository.overlay.manifest)
    for item in other["artifacts"]:
        item["relativePath"] = "rtmdet-m-coco-phase1-scale1280-v1/" + item["relativePath"].split("/", 1)[1]
    other["artifacts"][2]["sha256"] = "2" * 64
    write_json(repository.root / "models/manifests/other.json", other)
    _only(repository, "Duplicate modelId/modelVersion")


def test_a_second_pack_of_one_model_bound_by_a_development_binding_passes(repository: DevelopmentRepository) -> None:
    other = copy.deepcopy(repository.overlay.manifest)
    other["modelVersion"] = "1.0.0-dev.scale1280"
    for item in other["artifacts"]:
        item["relativePath"] = "rtmdet-m-coco-phase1-scale1280-v1/" + item["relativePath"].split("/", 1)[1]
    other["artifacts"][2]["sha256"] = "2" * 64
    path = repository.root / "models/manifests/rtmdet-m-coco-phase1-scale1280-v2.json"
    write_json(path, other)
    pack = load_model_manifest_v2(path).model_pack_id
    repository.record["modelPackId"] = pack
    repository.record["modelManifestSha256"] = sha256_bytes(path.read_bytes())
    repository.record["artifactSha256"]["resolved-config"] = "2" * 64
    repository.binding["capabilityBindings"][0]["modelPackId"] = pack
    repository.write()
    assert _errors(repository) == []
    # ... and then the release Model Pack must still be bound by the release binding alone.
    assert repository.overlay.binding["capabilityBindings"][0]["modelPackId"] == repository.overlay.derived_model_pack_id()


def test_an_unbound_second_pack_of_one_model_fails(repository: DevelopmentRepository) -> None:
    other = copy.deepcopy(repository.overlay.manifest)
    other["modelVersion"] = "1.0.0-dev.scale1280"
    for item in other["artifacts"]:
        item["relativePath"] = "rtmdet-m-coco-phase1-scale1280-v1/" + item["relativePath"].split("/", 1)[1]
    write_json(repository.root / "models/manifests/rtmdet-m-coco-phase1-scale1280-v2.json", other)
    _only(repository, "is bound by no capability binding")


# =========================================================================== resolver: fence and attestation


def _producer(tmp_path: Path, *, scale1280: bool) -> Overlay:
    overlay = Overlay.create(tmp_path / ("scale1280" if scale1280 else "scale640"))
    suffix = "1280" if scale1280 else "640"
    make_producer(
        overlay,
        binding_id=f"development-phase1-a2-scale{suffix}-v1",
        qualification_id=f"rtmdet-m-coco-phase1-a2-scale{suffix}-dev-v1",
        scale1280=scale1280,
    )
    return overlay


def _code(call) -> str:
    with pytest.raises(ReleaseMetadataError) as caught:
        call()
    return caught.value.code


def _provenance(overlay: Overlay, variant: str = "linux-x86_64-cpu"):
    overlay.install_pack(variant)
    resolved = overlay.resolve(variant, installed=True)
    selection = resolved.detector_selection()
    return build_runtime_provenance(
        selection=selection,
        runtime_metadata=RuntimeMetadata(
            backend="mmdetection",
            model_id=selection.detector.model_id,
            device="cpu",
            versions=LIVE_VERSIONS,
            ordered_class_vocabulary=selection.detector.class_vocabulary,
        ),
        configured_device_policy="cpu",
        configured_device_index=0,
        production_mode=False,
        platform_identity=_platform(),
        ffmpeg_version="7.1",
    )


def test_each_producer_attests_its_own_binding_and_pack_and_the_same_a2_profile(tmp_path: Path) -> None:
    scale640, scale1280 = _producer(tmp_path, scale1280=False), _producer(tmp_path, scale1280=True)
    first, second = _provenance(scale640), _provenance(scale1280)
    a2_sha = _sha(A2_PROFILE)
    for overlay, provenance in ((scale640, first), (scale1280, second)):
        assert provenance.pipeline_profile_sha256 == a2_sha
        assert (provenance.pipeline_profile_id, provenance.pipeline_profile_version) == ("phase1-detection-tracking-a2", "1.0.0-development")
        assert provenance.component_binding_sha256 == sha256_bytes(overlay.binding_path.read_bytes())
        assert provenance.model_pack_id == overlay.derived_model_pack_id()
        assert provenance.qualification_id == overlay.record["qualificationId"]
        assert provenance.qualification_sha256 == sha256_bytes(overlay.record_path.read_bytes())
        assert provenance.resolved_config_sha256 == overlay.record["artifactSha256"]["resolved-config"]
        assert provenance.runtime_pack_source == "installed-pack"
        assert provenance.runtime_pack_id == overlay.binding["runtimePacks"][0]["variants"]["linux-x86_64-cpu"]["runtimePackId"]
        assert provenance.capability_id == "detector"
        assert provenance.verification_status == "unverified"
        assert provenance.tracker_parameters.track_activation_threshold == 0.61
    # Causal attribution: one profile, two bindings, two Model Packs, one checkpoint.
    assert first.pipeline_profile_sha256 == second.pipeline_profile_sha256
    assert first.component_binding_sha256 != second.component_binding_sha256
    assert first.model_pack_id != second.model_pack_id
    assert first.resolved_config_sha256 != second.resolved_config_sha256
    assert first.checkpoint_sha256 == second.checkpoint_sha256
    assert first.model_id == second.model_id and first.model_version != second.model_version
    assert first.runtime_pack_id == second.runtime_pack_id
    assert first.tracker_parameters == second.tracker_parameters


@pytest.mark.parametrize("scale1280", [False, True], ids=["a2-scale640", "a2-scale1280"])
def test_a_development_producer_never_resolves_in_production(tmp_path: Path, scale1280: bool) -> None:
    overlay = _producer(tmp_path, scale1280=scale1280)
    # Every other Production claim made consistently: only the profile fence remains.
    profile, policy_sha = overlay.qualify_for_production()
    code = _code(lambda: overlay.resolve(
        profile.runtime_variant,
        production_mode=True,
        installed=True,
        profile_requirement=profile,
        deployment_profile_policy_sha256=policy_sha,
    ))
    assert code == "detector_development_profile_forbidden"


def test_a_development_binding_with_the_release_profile_does_not_resolve(tmp_path: Path) -> None:
    overlay = _producer(tmp_path, scale1280=True)
    record_pins = dict(overlay.record["policies"])
    overlay.pipeline_path.write_bytes(RELEASE_PROFILE.read_bytes())
    assert overlay.record["policies"] == record_pins  # the record still pins the A2 profile
    assert _code(lambda: overlay.resolve()) == "qualification_policy_mismatch"
    assert _code(lambda: overlay.resolve(production_mode=True)) == "qualification_policy_mismatch"


def test_the_release_composition_still_resolves_in_production(tmp_path: Path) -> None:
    overlay = Overlay.create(tmp_path)
    profile, policy_sha = overlay.qualify_for_production()
    resolved = overlay.resolve(
        profile.runtime_variant,
        production_mode=True,
        installed=True,
        profile_requirement=profile,
        deployment_profile_policy_sha256=policy_sha,
    )
    assert resolved.pipeline_profile.development_only is False
    assert resolved.pipeline_profile_sha256 == RELEASE_SHA256[RELEASE_PROFILE]
