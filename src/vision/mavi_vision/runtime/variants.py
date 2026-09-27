"""The one platform-variant model (ADR-014 §4a; S2a plan P-17).

The closed universe of governed variants is defined here once. A variant's class
is derived from the runtime profile's status pair and whether a lock file is
tracked for it; it is never declared a second time anywhere else.
"""

from __future__ import annotations

from enum import Enum

RUNTIME_VARIANTS = frozenset(
    {
        "linux-x86_64-cpu",
        "windows-x86_64-cpu",
        "linux-x86_64-cuda",
        "windows-x86_64-cuda",
    }
)

PENDING_HARDWARE_QUALIFICATION = "pending-hardware-qualification"


class VariantClass(Enum):
    """A. known but not yet releasable, or B. deployable. There is no third class."""

    KNOWN_NOT_RELEASABLE = "known-not-releasable"
    DEPLOYABLE = "deployable"


def check_variant_status_pair(*, variant: str, variant_status: str, lock_status: str) -> None:
    """The part of the classification visible without the file system.

    A variant pending hardware qualification can only be class A, which also needs
    its release lock pending hardware qualification. Any other lock status on a
    pending variant can never classify and fails closed.
    """
    if variant_status == PENDING_HARDWARE_QUALIFICATION and lock_status != PENDING_HARDWARE_QUALIFICATION:
        raise ValueError(f"runtime_variant_classification_invalid:{variant}")


def classify_variant(
    *,
    variant: str,
    variant_status: str,
    lock_status: str,
    lock_file_tracked: bool,
) -> VariantClass:
    """Classify one runtime-profile variant; anything but A or B fails closed."""
    if variant not in RUNTIME_VARIANTS:
        raise ValueError(f"runtime_variant_unknown:{variant}")
    if (
        variant_status == PENDING_HARDWARE_QUALIFICATION
        and lock_status == PENDING_HARDWARE_QUALIFICATION
        and not lock_file_tracked
    ):
        return VariantClass.KNOWN_NOT_RELEASABLE
    if lock_file_tracked and variant_status != PENDING_HARDWARE_QUALIFICATION:
        return VariantClass.DEPLOYABLE
    raise ValueError(f"runtime_variant_classification_invalid:{variant}")


__all__ = [
    "PENDING_HARDWARE_QUALIFICATION",
    "RUNTIME_VARIANTS",
    "VariantClass",
    "check_variant_status_pair",
    "classify_variant",
]
