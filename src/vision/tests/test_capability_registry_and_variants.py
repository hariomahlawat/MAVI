from __future__ import annotations

import pytest

from mavi_vision.runtime.capabilities import (
    IMPLEMENTED_CAPABILITIES,
    KNOWN_CAPABILITIES,
    require_implemented_capability,
    require_known_capability,
)
from mavi_vision.runtime.qualification import _RUNTIME_VARIANTS
from mavi_vision.runtime.variants import RUNTIME_VARIANTS, VariantClass, classify_variant

PENDING = "pending-hardware-qualification"


def test_registry_contains_the_adr_014_ids_and_only_detector_is_implemented() -> None:
    assert KNOWN_CAPABILITIES == {
        "detector", "person-attributes", "vehicle-attributes", "plate-detector", "ocr", "embedding",
    }
    assert IMPLEMENTED_CAPABILITIES == {"detector"}


@pytest.mark.parametrize(("value", "code"), [
    ("face-recognition", "capability_unknown:face-recognition"),
    ("Detector", "capability_id_invalid"),
    ("detector_v2", "capability_id_invalid"),
    ("", "capability_id_invalid"),
])
def test_unknown_or_malformed_capability_fails_closed(value, code) -> None:
    with pytest.raises(ValueError, match=f"^{code}$"):
        require_known_capability(value)


def test_declared_but_unimplemented_capability_cannot_start() -> None:
    assert require_known_capability("embedding") == "embedding"
    with pytest.raises(ValueError, match="^capability_not_implemented:embedding$"):
        require_implemented_capability("embedding")
    assert require_implemented_capability("detector") == "detector"


def test_v1_and_v2_share_one_variant_universe() -> None:
    assert _RUNTIME_VARIANTS is RUNTIME_VARIANTS
    assert RUNTIME_VARIANTS == {"windows-x86_64-cpu", "windows-x86_64-cuda", "linux-x86_64-cpu", "linux-x86_64-cuda"}


def test_class_a_requires_both_pending_statuses_and_no_lock_file() -> None:
    assert classify_variant(
        variant="linux-x86_64-cuda", variant_status=PENDING, lock_status=PENDING, lock_file_tracked=False
    ) is VariantClass.KNOWN_NOT_RELEASABLE


@pytest.mark.parametrize(("variant", "variant_status", "lock_status"), [
    ("windows-x86_64-cpu", "qualified-hosted-cpu", "qualified-offline-lock"),
    ("windows-x86_64-cuda", "qualified-development-hardware", PENDING),
])
def test_class_b_requires_a_lock_file_and_a_non_pending_variant(variant, variant_status, lock_status) -> None:
    assert classify_variant(
        variant=variant, variant_status=variant_status, lock_status=lock_status, lock_file_tracked=True
    ) is VariantClass.DEPLOYABLE


@pytest.mark.parametrize(("variant_status", "lock_status", "lock_file"), [
    # Mutation guard: drop the variant-status half of class A -> this would classify as A.
    ("qualified-development-hardware", PENDING, False),
    # Mutation guard: drop the release-lock half of class A -> this would classify as A.
    (PENDING, "pending-wheelhouse-freeze", False),
    # A lock file on a variant still pending hardware qualification is inconsistent.
    (PENDING, PENDING, True),
])
def test_anything_neither_a_nor_b_fails_closed(variant_status, lock_status, lock_file) -> None:
    with pytest.raises(ValueError, match="^runtime_variant_classification_invalid:linux-x86_64-cuda$"):
        classify_variant(
            variant="linux-x86_64-cuda", variant_status=variant_status, lock_status=lock_status, lock_file_tracked=lock_file
        )


def test_variant_outside_the_universe_fails_closed() -> None:
    with pytest.raises(ValueError, match="^runtime_variant_unknown:linux-arm64-cuda$"):
        classify_variant(variant="linux-arm64-cuda", variant_status=PENDING, lock_status=PENDING, lock_file_tracked=False)
