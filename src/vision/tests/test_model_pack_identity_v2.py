from __future__ import annotations

import dataclasses
import hashlib
import json

import pytest

from mavi_vision.runtime.component_identity import ComponentIdentityError
from mavi_vision.runtime.model_pack_identity import (
    ModelPackArtifactIdentity,
    ModelPackIdentityInputsV2,
    model_pack_id_v2,
)

_A, _B, _C = "a" * 64, "b" * 64, "c" * 64


def _inputs(**overrides) -> ModelPackIdentityInputsV2:
    values = {
        "model_id": "rtmdet-m-coco-phase1",
        "model_version": "1.0.0",
        "capability_ids": ("detector",),
        "artifacts": (
            ModelPackArtifactIdentity("checkpoint", _A),
            ModelPackArtifactIdentity("licence-notice", _B),
            ModelPackArtifactIdentity("resolved-config", _C),
        ),
    }
    values.update(overrides)
    return ModelPackIdentityInputsV2(**values)


def test_golden_vector_pins_the_canonical_encoding() -> None:
    # Hand-written canonical JSON, independent of the implementation's serializer:
    # sorted keys, compact separators, trailing newline, sorted capabilities/artifacts.
    canonical = (
        '{"artifacts":['
        f'{{"artifactRole":"checkpoint","sha256":"{_A}"}},'
        f'{{"artifactRole":"licence-notice","sha256":"{_B}"}},'
        f'{{"artifactRole":"resolved-config","sha256":"{_C}"}}'
        '],"capabilityIds":["detector"],"modelId":"rtmdet-m-coco-phase1",'
        '"modelVersion":"1.0.0","schemaVersion":"mavi-vision-model-pack-v2"}\n'
    )
    expected = "mavi-model-v2-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert model_pack_id_v2(_inputs()) == expected


def test_identity_is_independent_of_declaration_order() -> None:
    reordered = _inputs(artifacts=tuple(reversed(_inputs().artifacts)))
    assert model_pack_id_v2(reordered) == model_pack_id_v2(_inputs())


@pytest.mark.parametrize(
    "change",
    [
        {"model_id": "other-model"},
        {"model_version": "1.0.1"},
        {"capability_ids": ("detector", "embedding")},
        {"artifacts": (ModelPackArtifactIdentity("checkpoint", _A), ModelPackArtifactIdentity("resolved-config", _C))},
        {"artifacts": (ModelPackArtifactIdentity("checkpoint", _A), ModelPackArtifactIdentity("licence-notice", _C), ModelPackArtifactIdentity("resolved-config", _C))},
        {"artifacts": (ModelPackArtifactIdentity("weights", _A), ModelPackArtifactIdentity("licence-notice", _B), ModelPackArtifactIdentity("resolved-config", _C))},
    ],
)
def test_every_material_input_changes_the_identity(change) -> None:
    assert model_pack_id_v2(_inputs(**change)) != model_pack_id_v2(_inputs())


def test_licence_notice_participates_in_the_identity() -> None:
    without_notice = _inputs(artifacts=_inputs().artifacts[::2])
    assert model_pack_id_v2(without_notice) != model_pack_id_v2(_inputs())


def test_identity_has_no_commit_size_or_qualification_input() -> None:
    fields = {field.name for field in dataclasses.fields(ModelPackIdentityInputsV2)}
    assert fields == {"model_id", "model_version", "capability_ids", "artifacts"}
    assert {field.name for field in dataclasses.fields(ModelPackArtifactIdentity)} == {"artifact_role", "sha256"}


def test_differs_from_the_v1_identity_scheme() -> None:
    assert model_pack_id_v2(_inputs()).startswith("mavi-model-v2-")


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"model_id": " padded"}, "component_identity_text_invalid"),
        ({"model_version": ""}, "component_identity_text_invalid"),
        ({"capability_ids": ()}, "component_identity_capabilities_invalid"),
        ({"capability_ids": ("detector", "detector")}, "component_identity_capabilities_invalid"),
        ({"capability_ids": ("face-recognition",)}, "component_identity_capabilities_invalid"),
        ({"artifacts": ()}, "component_identity_artifacts_invalid"),
        ({"artifacts": (ModelPackArtifactIdentity("checkpoint", _A), ModelPackArtifactIdentity("checkpoint", _B))}, "component_identity_artifacts_invalid"),
        ({"artifacts": (ModelPackArtifactIdentity("Checkpoint", _A),)}, "component_identity_artifacts_invalid"),
        ({"artifacts": (ModelPackArtifactIdentity("checkpoint", "A" * 64),)}, "component_identity_sha256_invalid"),
    ],
)
def test_malformed_identity_inputs_fail_closed(change, code) -> None:
    with pytest.raises(ComponentIdentityError) as error:
        model_pack_id_v2(_inputs(**change))
    assert error.value.code == code


def test_runtime_pack_identity_is_unchanged_by_the_shared_digest() -> None:
    # The Runtime Pack v2 ids in the repository binding must still derive exactly.
    from mavi_vision.runtime.component_identity import canonical_identity_digest

    payload = {"b": "2", "a": "1"}
    assert canonical_identity_digest(payload) == hashlib.sha256(
        (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()
    ).hexdigest()
