from __future__ import annotations

import pytest

from mavi_vision.runtime.component_identity import (
    ComponentIdentityError,
    RuntimePackIdentityInputs,
    runtime_pack_id,
)
import mavi_vision.runtime.component_identity as component_identity

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


def test_the_v1_model_pack_identity_is_retired_from_the_runtime() -> None:
    # S2a.3: the Model Pack identity is the v2 derivation (plan P-3, P-15) in
    # mavi_vision.runtime.model_pack_identity; no runtime path derives a v1 id.
    for retired in ("ModelPackIdentityInputs", "model_pack_id", "_MODEL_SCHEMA"):
        assert not hasattr(component_identity, retired), retired


def test_the_runtime_pack_identities_the_cut_over_consumed_are_unchanged() -> None:
    """The binding pins exactly the ids main carried before S2a.3 (byte-identical)."""
    import json
    from pathlib import Path

    expected = {
        "linux-x86_64-cpu": "mavi-runtime-v2-bd94fded938183dce8dc50390d48e97d913d9dad9dc98b528a962ad32314ff61",
        "windows-x86_64-cpu": "mavi-runtime-v2-5d6229da58554bc951ddc8bd719574c1b33109a7916afdf717339d8847e39e61",
        "windows-x86_64-cuda": "mavi-runtime-v2-89fd8bfcc32fb1bd8ab77f0deb9f33675ae228c75ffd11f13e6838e990003a1d",
    }
    binding = json.loads(
        (Path(__file__).resolve().parents[1] / "config" / "components" / "phase1-bindings-v2.json").read_text(
            encoding="utf-8"
        )
    )
    pinned = {
        variant: entry["runtimePackId"]
        for family in binding["runtimePacks"]
        for variant, entry in family["variants"].items()
    }
    assert pinned == expected


def test_component_identity_rejects_non_sha256_fingerprint() -> None:
    with pytest.raises(ComponentIdentityError, match="component_identity_sha256_invalid"):
        runtime_pack_id(_runtime(third_party_lock_sha256="not-a-sha"))
