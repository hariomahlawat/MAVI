from __future__ import annotations

from enum import StrEnum


class EvidenceRole(StrEnum):
    """The four Track Evidence Set roles (ADR-013 §4); values are wire tokens."""

    REPRESENTATIVE = "representative"
    NEAR_VIEW = "near-view"
    EARLY_DIVERSE = "early-diverse"
    LATE_DIVERSE = "late-diverse"


# Canonical order: evaluation order in the selector, resolution precedence at
# retirement, admission rounds, rank order and wire accounting order.
ROLE_ORDER: tuple[EvidenceRole, ...] = (
    EvidenceRole.REPRESENTATIVE,
    EvidenceRole.NEAR_VIEW,
    EvidenceRole.EARLY_DIVERSE,
    EvidenceRole.LATE_DIVERSE,
)
SUPPLEMENTAL_ROLES: tuple[EvidenceRole, ...] = ROLE_ORDER[1:]

# ADR-013 §5 product bounds (bytes of the encoded JPEG).
REPRESENTATIVE_CAP_BYTES = 64 * 1024
SUPPLEMENTAL_CAP_BYTES = 160 * 1024
# ADR-013 §6 run-level EvidenceCrop quota.
RUN_EVIDENCE_CROP_QUOTA_BYTES = 1024 * 1024 * 1024


def role_cap_bytes(role: EvidenceRole) -> int:
    return (
        REPRESENTATIVE_CAP_BYTES
        if role is EvidenceRole.REPRESENTATIVE
        else SUPPLEMENTAL_CAP_BYTES
    )


def role_index(role: EvidenceRole) -> int:
    return ROLE_ORDER.index(role)
