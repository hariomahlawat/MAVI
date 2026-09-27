"""Closed registry of capability ids (ADR-014 §1-§2; S2a plan P-4).

A capability id is a stable contract name, never a model name. Schemas accept
any id that is syntactically valid and in this registry; only implemented
capabilities can start a role.
"""

from __future__ import annotations

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

IMPLEMENTED_CAPABILITIES = frozenset({"detector"})


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


__all__ = [
    "IMPLEMENTED_CAPABILITIES",
    "KNOWN_CAPABILITIES",
    "require_implemented_capability",
    "require_known_capability",
]
