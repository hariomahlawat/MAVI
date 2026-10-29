"""PoC S5: the zero-shot SigLIP 2 attribute inferencer and its explicit Development composition.

The model is a deterministic stand-in (no ONNX Runtime here): the scoring, abstention map, schema checks,
aggregation through the unchanged S2b policy, composition refusals and truthful provenance are what is tested.
The committed release documents are held to their generator and to the identity the platform derives.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import io
import json
import shutil
import sys
from pathlib import Path
from types import MappingProxyType
from uuid import uuid4

import numpy as np
import pytest
from PIL import Image

from mavi_vision.attributes.contracts import LeaseTrack
from mavi_vision.attributes.inference import CropDecodeError, VerifiedCrop
from mavi_vision.attributes.main import RUNTIME_UNAVAILABLE_EXIT, run_worker
from mavi_vision.attributes.pipeline import AttributeSchema, load_attribute_pipeline
from mavi_vision.attributes.predictions import ObservationResult, aggregate_track
from mavi_vision.attributes.settings import AttributeWorkerSettings
from mavi_vision.attributes.zero_shot import (
    SiglipZeroShotInferencer,
    abstention_score,
    parse_zero_shot_parameters,
)
from mavi_vision.attributes.zero_shot_runtime import compose_zero_shot
from mavi_vision.runtime.model_manifest_v2 import load_model_manifest_v2

REPOSITORY = Path(__file__).resolve().parents[3]
CONFIG = REPOSITORY / "src/vision/config/attributes"
PROFILE = CONFIG / "development-attributes-siglip2-zero-shot-v1.json"
BINDING = CONFIG / "development-attributes-siglip2-binding-v1.json"
MANIFEST = REPOSITORY / "models/manifests/embeddings-siglip2-base-p16-224-dev-v1.json"
RUNTIME_PROFILE = REPOSITORY / "src/vision/runtime/embeddings-onnx-v1/runtime.json"
# The identity the committed release defines; VisualAttributeZeroShotReleaseTests pins the same value in .NET.
EXPECTED_FINGERPRINT_FILE = REPOSITORY / "contracts/test-vectors/poc-zero-shot-attribute-identity-v1.json"
DIMENSION = 8


def _jpeg(width: int, height: int, colour=(200, 30, 30)) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(stream, format="JPEG")
    return stream.getvalue()


def _crop(content: bytes, rank: int = 0) -> VerifiedCrop:
    return VerifiedCrop(str(uuid4()), rank, hashlib.sha256(content).hexdigest(), content)


class PromptModel:
    """Text vectors keyed by the first word that names a value; the image vector is set per test."""

    dimension = DIMENSION

    def __init__(self, keys: dict[str, int]) -> None:
        self._keys = keys
        self.image = np.eye(DIMENSION, dtype=np.float32)[0]

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        rows = []
        for text in texts:
            axis = next((index for word, index in self._keys.items() if f" {word} " in f" {text} "), DIMENSION - 1)
            rows.append(np.eye(DIMENSION, dtype=np.float32)[axis])
        return np.stack(rows)

    def embed_images(self, crops: list[bytes]) -> np.ndarray:
        return np.stack([self.image for _ in crops])


def _profile():
    profile = load_attribute_pipeline(PROFILE)
    return profile, parse_zero_shot_parameters(profile.parameters, profile.schema)


# --------------------------------------------------------------------------- release documents


def test_the_committed_release_documents_are_what_the_generator_writes() -> None:
    sys.path.insert(0, str(REPOSITORY / "tools" / "poc"))
    try:
        import attributes_zero_shot_profile as generator
    finally:
        sys.path.pop(0)
    for name, payload in generator.documents(generator.committed_thresholds()).items():
        assert (CONFIG / name).read_bytes() == payload, name


def test_the_profile_is_development_only_zero_shot_and_states_its_disclosure() -> None:
    profile, parameters = _profile()
    assert profile.development_only
    assert profile.parameters["disclosure"] == "zero-shot, Development"
    assert parameters.minimum_crop_side == 80
    assert profile.aggregation.minimum_confidence == 0.5
    # Presence attributes emit only "present": no negative claim is ever made.
    assert {item.attribute_type: item.values for item in profile.schema.attributes
            if parameters.attributes[item.attribute_type].kind == "presence"} == {
        "person-carried-bag": ("present",), "person-headwear": ("present",)}


def test_the_parameters_pin_the_s4_model_pack_manifest() -> None:
    _, parameters = _profile()
    assert parameters.model_manifest_file == MANIFEST.name
    assert parameters.model_manifest_sha256 == hashlib.sha256(MANIFEST.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(disclosure="Production"),
        lambda p: p.update(minimumCropSide=0),
        lambda p: p["attributes"]["vehicle-colour"].update(threshold=1.0),
        lambda p: p["attributes"]["vehicle-colour"]["prompts"].pop("red"),
        lambda p: p["attributes"]["person-headwear"]["prompts"].pop("absent"),
        lambda p: p["attributes"]["person-headwear"].update(kind="categorical"),
        lambda p: p["attributes"].pop("person-upper-colour"),
        lambda p: p["attributes"]["vehicle-colour"]["prompts"].update(red=[]),
        lambda p: p.update(extra=True),
    ],
)
def test_parameters_that_do_not_match_the_schema_are_refused(mutate) -> None:
    profile, _ = _profile()
    parameters = copy.deepcopy(json.loads(json.dumps(dict(profile.parameters))))
    mutate(parameters)
    with pytest.raises(ValueError, match="attribute_zero_shot_parameters_invalid"):
        parse_zero_shot_parameters(MappingProxyType(parameters), profile.schema)


# --------------------------------------------------------------------------- scoring


@pytest.mark.parametrize("threshold", [0.2, 0.5, 0.85])
def test_the_abstention_map_puts_each_threshold_at_the_policy_half(threshold: float) -> None:
    assert abstention_score(threshold, threshold) == pytest.approx(0.5)
    assert abstention_score(0.0, threshold) == 0.0
    assert abstention_score(1.0, threshold) == pytest.approx(1.0)
    grid = [abstention_score(p / 100, threshold) for p in range(101)]
    assert grid == sorted(grid)


def _inferencer() -> tuple[SiglipZeroShotInferencer, PromptModel]:
    _, parameters = _profile()
    model = PromptModel({"red": 0, "blue": 1, "carrying": 2, "backpack": 2, "handbag": 2})
    return SiglipZeroShotInferencer(model, parameters), model


def test_a_crop_that_matches_a_colour_prompt_scores_that_colour_above_the_threshold() -> None:
    inferencer, model = _inferencer()
    model.image = np.eye(DIMENSION, dtype=np.float32)[0]  # the "red" axis
    profile, _ = _profile()
    scores = inferencer.score(_crop(_jpeg(120, 200)), profile.schema.for_object_class("vehicle"))
    colours = scores["vehicle-colour"]
    assert max(colours, key=colours.get) == "red"
    assert colours["red"] > 0.5
    assert all(0.0 <= value <= 1.0 for value in colours.values())


def test_a_presence_attribute_emits_only_present() -> None:
    inferencer, model = _inferencer()
    model.image = np.eye(DIMENSION, dtype=np.float32)[2]  # the "carrying" axis
    profile, _ = _profile()
    scores = inferencer.score(_crop(_jpeg(100, 220)), profile.schema.for_object_class("person"))
    assert set(scores["person-carried-bag"]) == {"present"}
    assert scores["person-carried-bag"]["present"] > 0.5
    assert set(scores["person-headwear"]) == {"present"}


def test_a_crop_under_the_minimum_side_contributes_no_evidence() -> None:
    inferencer, model = _inferencer()
    profile, _ = _profile()
    scores = inferencer.score(_crop(_jpeg(60, 200)), profile.schema.for_object_class("vehicle"))
    assert set(scores["vehicle-colour"].values()) == {0.0}


def test_bytes_that_are_not_an_image_are_a_decode_failure() -> None:
    inferencer, _ = _inferencer()
    profile, _ = _profile()
    with pytest.raises(CropDecodeError):
        inferencer.score(_crop(b"\xff\xd8 not a jpeg \xff\xd9"), profile.schema.for_object_class("vehicle"))


def test_aggregation_observes_a_confident_value_and_abstains_on_an_ambiguous_one() -> None:
    inferencer, model = _inferencer()
    profile, _ = _profile()
    attributes = profile.schema.for_object_class("vehicle")
    content = _jpeg(150, 150)
    track = LeaseTrack.model_validate_json(json.dumps({
        "trackId": str(uuid4()), "objectClass": "vehicle",
        "observations": [{"observationId": str(uuid4()), "role": "representative", "evidenceRank": 0,
                          "sizeBytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}],
    }))
    observation = track.observations[0]

    def decide(image: np.ndarray):
        model.image = image.astype(np.float32)
        scores = inferencer.score(_crop(content), attributes)
        result = ObservationResult(observation.observation_id, 0, scores=scores)
        return aggregate_track(track, (result,), attributes, profile.aggregation).decisions[0]

    confident = decide(np.eye(DIMENSION)[0])
    assert (confident.outcome, confident.value) == ("observed", "red")
    # Equally close to every colour prototype (red, blue and the rest share the last axis): p is about 1/11 for each
    # value, none reaches its threshold, so the model abstains.
    ambiguous = decide((np.eye(DIMENSION)[0] + np.eye(DIMENSION)[1] + np.eye(DIMENSION)[DIMENSION - 1]) / np.sqrt(3))
    assert ambiguous.outcome == "unknown" and ambiguous.value is None


# --------------------------------------------------------------------------- composition


class _Resolution:
    actual_device = "cpu"


def _settings(tmp_path: Path, **overrides) -> AttributeWorkerSettings:
    values = {
        "api_base_url": "http://127.0.0.1:5000",
        "worker_id": "attributes-01",
        "component_binding_path": BINDING,
        "pipeline_profile_path": PROFILE,
        "attribute_model_manifest_path": MANIFEST,
        "attribute_runtime_profile_path": RUNTIME_PROFILE,
        "model_root": tmp_path,
    }
    values.update(overrides)
    return AttributeWorkerSettings(**values)


def _loader(manifest, settings):
    return PromptModel({"red": 0}), "windows-x86_64-cpu", "cpu"


def test_the_zero_shot_role_composes_with_the_s4_pack_and_truthful_provenance(tmp_path: Path) -> None:
    runtime = compose_zero_shot(_settings(tmp_path), model_loader=_loader)
    pack = load_model_manifest_v2(MANIFEST).model_pack_id
    assert [(item.capability_id, item.model_pack_id) for item in runtime.identity.capabilities] == [
        ("person-attributes", pack), ("vehicle-attributes", pack)]
    expected = json.loads(EXPECTED_FINGERPRINT_FILE.read_text(encoding="utf-8"))
    assert runtime.identity.fingerprint == expected["fingerprint"]
    provenance = runtime.provenance
    assert provenance["runtimePackSource"] == "unpacked-environment" and provenance["runtimePackId"] is None
    assert provenance["runtimePackFamilyId"] == "embeddings-onnx-v1"
    assert {item["verificationStatus"] for item in provenance["capabilities"]} == {"unverified"}
    assert {item["qualificationId"] for item in provenance["capabilities"]} == {"attributes-siglip2-zero-shot-development"}
    assert provenance["runtimeProfileSha256"] == hashlib.sha256(RUNTIME_PROFILE.read_bytes()).hexdigest()


def test_production_mode_refuses_the_zero_shot_role(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="attribute_zero_shot_development_only"):
        _settings(tmp_path, production_mode=True, deployment_profile="P1")


def _copy_release(tmp_path: Path) -> Path:
    directory = tmp_path / "release"
    shutil.copytree(CONFIG, directory)
    return directory


def test_a_binding_naming_another_model_pack_is_refused(tmp_path: Path) -> None:
    directory = _copy_release(tmp_path)
    binding = json.loads((directory / BINDING.name).read_text(encoding="utf-8"))
    binding["capabilityBindings"][0]["modelPackId"] = "mavi-model-v2-" + "0" * 64
    (directory / BINDING.name).write_text(json.dumps(binding), encoding="utf-8")
    with pytest.raises(ValueError, match="attribute_zero_shot_model_pack_mismatch"):
        compose_zero_shot(_settings(tmp_path, component_binding_path=directory / BINDING.name), model_loader=_loader)


def test_a_manifest_other_than_the_pinned_one_is_refused(tmp_path: Path) -> None:
    other = tmp_path / MANIFEST.name
    other.write_bytes(MANIFEST.read_bytes() + b" ")
    with pytest.raises(ValueError, match="attribute_zero_shot_manifest_sha256_mismatch"):
        compose_zero_shot(_settings(tmp_path, attribute_model_manifest_path=other), model_loader=_loader)


def test_a_binding_from_another_runtime_family_is_refused(tmp_path: Path) -> None:
    directory = _copy_release(tmp_path)
    binding = json.loads((directory / BINDING.name).read_text(encoding="utf-8"))
    binding["roles"][0]["runtimePackFamilyId"] = "mmdetection-phase1-v1"
    (directory / BINDING.name).write_text(json.dumps(binding), encoding="utf-8")
    with pytest.raises(ValueError, match="attribute_zero_shot_binding_invalid"):
        compose_zero_shot(_settings(tmp_path, component_binding_path=directory / BINDING.name), model_loader=_loader)


def test_an_unavailable_zero_shot_runtime_never_leases(tmp_path: Path) -> None:
    created = []

    def composer(settings):
        raise ValueError("embedding_model_artifact_missing:onnx-vision-encoder")

    code = asyncio.run(run_worker(_settings(tmp_path), client_factory=lambda **kwargs: created.append(kwargs),
                                  zero_shot_composer=composer, max_iterations=1))
    assert code == RUNTIME_UNAVAILABLE_EXIT
    assert created == []


def test_the_schema_type_used_by_the_test_is_the_committed_one() -> None:
    profile, _ = _profile()
    assert isinstance(profile.schema, AttributeSchema)
    assert [item.attribute_type for item in profile.schema.attributes] == [
        "person-carried-bag", "person-headwear", "person-lower-colour", "person-upper-colour", "vehicle-colour"]
