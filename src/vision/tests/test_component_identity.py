from __future__ import annotations

import pytest

from mavi_vision.runtime.component_identity import (
    ComponentIdentityError,
    ModelPackIdentityInputs,
    RuntimePackIdentityInputs,
    model_pack_id,
    runtime_pack_id,
)

_A = "a" * 64
_B = "b" * 64
_C = "c" * 64
_D = "d" * 64


def _runtime(**overrides) -> RuntimePackIdentityInputs:
    values = {
        "platform_variant": "windows-x86_64-cpu",
        "python_version": "3.12.10",
        "third_party_lock_sha256": _A,
        "runtime_requirements_sha256": _B,
        "native_abi": "win_amd64",
    }
    values.update(overrides)
    return RuntimePackIdentityInputs(**values)


def test_runtime_pack_identity_is_stable_for_identical_component_inputs() -> None:
    assert runtime_pack_id(_runtime()) == runtime_pack_id(_runtime())
    assert runtime_pack_id(_runtime()).startswith("mavi-runtime-v2-")


def test_runtime_pack_identity_changes_for_material_runtime_inputs() -> None:
    baseline = runtime_pack_id(_runtime())

    assert runtime_pack_id(_runtime(third_party_lock_sha256=_C)) != baseline
    assert runtime_pack_id(_runtime(runtime_requirements_sha256=_D)) != baseline
    assert runtime_pack_id(_runtime(python_version="3.12.11")) != baseline
    assert runtime_pack_id(_runtime(native_abi="different-abi")) != baseline


def test_runtime_pack_identity_has_no_application_commit_input() -> None:
    fields = RuntimePackIdentityInputs.__dataclass_fields__
    assert "source_commit" not in fields
    assert "application_commit" not in fields


def test_model_pack_identity_depends_only_on_model_bytes_and_identity() -> None:
    baseline = model_pack_id(
        ModelPackIdentityInputs(
            model_id="rtmdet-m-coco-phase1-v1",
            checkpoint_sha256=_A,
            resolved_config_sha256=_B,
        )
    )
    same = model_pack_id(
        ModelPackIdentityInputs(
            model_id="rtmdet-m-coco-phase1-v1",
            checkpoint_sha256=_A,
            resolved_config_sha256=_B,
        )
    )
    changed_checkpoint = model_pack_id(
        ModelPackIdentityInputs(
            model_id="rtmdet-m-coco-phase1-v1",
            checkpoint_sha256=_C,
            resolved_config_sha256=_B,
        )
    )

    assert baseline == same
    assert changed_checkpoint != baseline
    assert baseline.startswith("mavi-model-v1-")


def test_component_identity_rejects_non_sha256_fingerprint() -> None:
    with pytest.raises(ComponentIdentityError, match="component_identity_sha256_invalid"):
        runtime_pack_id(_runtime(third_party_lock_sha256="not-a-sha"))
