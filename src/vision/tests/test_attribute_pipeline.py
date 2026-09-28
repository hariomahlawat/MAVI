"""The attribute pipeline profile and the analysis identity (ADR-013 §11, §16; S2b).

The platform derives the same identity from the same files; both sides are pinned to
``contracts/test-vectors/visual-attribute-identity-v1.json``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from mavi_vision.attributes.pipeline import (
    MAXIMUM_PREDICTION_ARTIFACT_BYTES,
    AttributeDefinition,
    worst_case_prediction_artifact_bytes,
    attribute_identity,
    canonical_identity_bytes,
    load_attribute_pipeline,
)
from mavi_vision.runtime.manifest import ReleaseMetadataError

REPOSITORY = Path(__file__).resolve().parents[3]
FIXTURE = REPOSITORY / "tests/fixtures/visual-attributes"
VECTORS = REPOSITORY / "contracts/test-vectors/visual-attribute-identity-v1.json"


@pytest.fixture()
def profile_dir(tmp_path: Path) -> Path:
    target = tmp_path / "profile"
    shutil.copytree(FIXTURE, target)
    return target


def _vector() -> dict:
    return json.loads(VECTORS.read_text(encoding="utf-8"))["vectors"][0]


def test_the_identity_vector_is_reproduced() -> None:
    vector = _vector()
    profile = load_attribute_pipeline(REPOSITORY / vector["pipelineProfile"])
    identity = attribute_identity(profile, vector["capabilities"])

    assert canonical_identity_bytes(profile, identity.capabilities).decode("ascii") == vector["canonicalIdentity"]
    assert identity.fingerprint == vector["fingerprint"]
    assert [item.capability_id for item in identity.capabilities] == ["person-attributes", "vehicle-attributes"]
    assert profile.development_only is True


def test_the_identity_does_not_depend_on_binding_order() -> None:
    vector = _vector()
    profile = load_attribute_pipeline(REPOSITORY / vector["pipelineProfile"])
    reversed_order = dict(reversed(list(vector["capabilities"].items())))
    assert attribute_identity(profile, reversed_order).fingerprint == vector["fingerprint"]


def test_a_different_model_pack_is_a_different_identity() -> None:
    vector = _vector()
    profile = load_attribute_pipeline(REPOSITORY / vector["pipelineProfile"])
    changed = dict(vector["capabilities"], **{"vehicle-attributes": "mavi-model-v2-" + "3" * 64})
    assert attribute_identity(profile, changed).fingerprint != vector["fingerprint"]


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("fixture-attribute-schema-v1.json", "attribute_schema_invalid:sha256_mismatch"),
        ("fixture-aggregation-policy-v1.json", "aggregation_policy_invalid:sha256_mismatch"),
        ("fixture-parameters-v1.json", "attribute_parameters_invalid:sha256_mismatch"),
    ],
)
def test_a_tampered_sibling_fails_closed(profile_dir: Path, name: str, code: str) -> None:
    path = profile_dir / name
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ReleaseMetadataError, match=f"^{code}$"):
        load_attribute_pipeline(profile_dir / "fixture-pipeline-v1.json")


def test_a_carriage_return_fails_closed(profile_dir: Path) -> None:
    path = profile_dir / "fixture-pipeline-v1.json"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(ReleaseMetadataError, match="^release_text_cr_forbidden$"):
        load_attribute_pipeline(path)


def test_the_bound_capabilities_must_be_exactly_the_schema_s(profile_dir: Path) -> None:
    profile = load_attribute_pipeline(profile_dir / "fixture-pipeline-v1.json")
    with pytest.raises(ReleaseMetadataError, match="^attribute_capabilities_schema_mismatch$"):
        attribute_identity(profile, {"person-attributes": "mavi-model-v2-" + "1" * 64})


@pytest.mark.parametrize("name", ["../fixture-attribute-schema-v1.json", "sub/fixture-attribute-schema-v1.json"])
def test_a_sibling_outside_the_profile_directory_is_refused(profile_dir: Path, name: str) -> None:
    path = profile_dir / "fixture-pipeline-v1.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["attributeSchema"]["file"] = name
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ReleaseMetadataError, match="^attribute_schema_invalid$"):
        load_attribute_pipeline(path)


def _rewrite_schema(profile_dir: Path, mutate) -> Path:
    import hashlib

    schema_path = profile_dir / "fixture-attribute-schema-v1.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    mutate(schema)
    payload = (json.dumps(schema, indent=2) + "\n").encode("utf-8")
    schema_path.write_bytes(payload)
    profile_path = profile_dir / "fixture-pipeline-v1.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["attributeSchema"]["sha256"] = hashlib.sha256(payload).hexdigest()
    profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    return profile_path


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda s: s["attributes"].reverse(), "attribute_schema_invalid:attributes_order"),
        (lambda s: s["attributes"][0]["values"].reverse(), "attribute_schema_invalid:values_order"),
        (lambda s: s["attributes"][0].update(objectClass="vehicle"), "attribute_schema_invalid:objectClass"),
        (lambda s: s["attributes"][0].update(capabilityId="ocr"), "attribute_schema_invalid:capabilityId"),
        (lambda s: s["attributes"][0].update(attributeType="Upper"), "attribute_schema_invalid:attributeType"),
        (lambda s: s["attributes"][0].update(values=[]), "attribute_schema_invalid:values"),
    ],
)
def test_schema_rules_fail_closed(profile_dir: Path, mutate, code: str) -> None:
    path = _rewrite_schema(profile_dir, mutate)
    with pytest.raises(ReleaseMetadataError, match=f"^{code}$"):
        load_attribute_pipeline(path)


def test_the_per_class_attribute_bound_is_enforced(profile_dir: Path) -> None:
    def nine_person_attributes(schema: dict) -> None:
        schema["attributes"] = [
            {"attributeType": f"fixture-person-{index}", "capabilityId": "person-attributes",
             "objectClass": "person", "values": ["dark", "light"]}
            for index in range(9)
        ] + [schema["attributes"][-1]]

    path = _rewrite_schema(profile_dir, nine_person_attributes)
    with pytest.raises(ReleaseMetadataError, match="^attribute_schema_invalid:object_class_limit$"):
        load_attribute_pipeline(path)


# --- The artefact bound (plan §15; implementation record §4) ---------------------------------

BOUND_VECTORS = json.loads(
    (REPOSITORY / "contracts/test-vectors/visual-attribute-artifact-bound-v1.json").read_text(encoding="utf-8")
)


def _attributes(vector: dict) -> tuple[AttributeDefinition, ...]:
    return tuple(
        AttributeDefinition(item["attributeType"], item["capabilityId"], item["objectClass"], tuple(item["values"]))
        for item in vector["attributes"]
    )


def test_the_worst_case_artefact_size_matches_the_cross_language_vectors() -> None:
    assert BOUND_VECTORS["maximumBytes"] == MAXIMUM_PREDICTION_ARTIFACT_BYTES
    for vector in BOUND_VECTORS["vectors"]:
        size = worst_case_prediction_artifact_bytes(_attributes(vector))
        assert size == vector["worstCaseBytes"], vector["name"]
        assert (size <= MAXIMUM_PREDICTION_ARTIFACT_BYTES) is vector["accepted"], vector["name"]


@pytest.mark.parametrize(("name", "code"), [("largest-accepted", None), ("smallest-refused", "attribute_schema_invalid:artifact_bound")])
def test_a_schema_whose_worst_case_artefact_exceeds_the_upload_cap_is_refused(profile_dir: Path, name: str, code: str | None) -> None:
    vector = next(item for item in BOUND_VECTORS["vectors"] if item["name"] == name)

    def replace(schema: dict) -> None:
        # The fixture's vehicle attribute keeps both bound capabilities; it sorts first.
        schema["attributes"] = [schema["attributes"][-1], *vector["attributes"]]

    path = _rewrite_schema(profile_dir, replace)
    if code is None:
        assert load_attribute_pipeline(path).schema.attributes
        return
    with pytest.raises(ReleaseMetadataError, match=f"^{code}$"):
        load_attribute_pipeline(path)

