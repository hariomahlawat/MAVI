"""Closed registry of capability ids (ADR-014 §1-§2; S2a plan P-4).

A capability id is a stable contract name, never a model name. Schemas accept
any id that is syntactically valid and in this registry; only implemented
capabilities can start a role.
"""

from __future__ import annotations

from types import MappingProxyType

from mavi_vision.runtime.schema_common import require_kebab_id

KNOWN_CAPABILITIES = frozenset(
    {
        "detector",
        "person-attributes",
        "vehicle-attributes",
        "plate-detector",
        "ocr",
        "embedding",
    }
)

IMPLEMENTED_CAPABILITIES = frozenset({"detector", "person-attributes", "vehicle-attributes"})

# The input each implemented capability's runtime consumes: (kind, colourSpace).
# MMDetectionRuntime is fed RGB frame arrays and provenance attests
# ``inputColourSpace = RGB``, so a Model Pack declaring anything else is refused.
# The attribute capabilities (S2b) consume one accepted EvidenceCrop JPEG, read
# through the lease-scoped evidence endpoint and decoded to RGB.
IMPLEMENTED_INPUT_CONTRACTS = MappingProxyType(
    {
        "detector": ("video-frame-rgb", "RGB"),
        "person-attributes": ("evidence-crop-jpeg", "RGB"),
        "vehicle-attributes": ("evidence-crop-jpeg", "RGB"),
    }
)


def require_known_capability(value: str) -> str:
    require_kebab_id(value, code="capability_id_invalid")
    if value not in KNOWN_CAPABILITIES:
        raise ValueError(f"capability_unknown:{value}")
    return value


def require_implemented_capability(value: str) -> str:
    require_known_capability(value)
    if value not in IMPLEMENTED_CAPABILITIES:
        raise ValueError(f"capability_not_implemented:{value}")
    return value


def require_implemented_input_contract(
    capability_id: str, *, kind: str, colour_space: str | None
) -> None:
    if IMPLEMENTED_INPUT_CONTRACTS.get(capability_id) != (kind, colour_space):
        raise ValueError(f"model_input_contract_unsupported:{capability_id}")


__all__ = [
    "IMPLEMENTED_CAPABILITIES",
    "IMPLEMENTED_INPUT_CONTRACTS",
    "KNOWN_CAPABILITIES",
    "require_implemented_capability",
    "require_implemented_input_contract",
    "require_known_capability",
]
