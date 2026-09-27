"""Content-derived identities for reusable MAVI Vision components."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Mapping

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA256_RE = SHA256_RE
RUNTIME_PACK_ID_PREFIX = "mavi-runtime-v2-"
RUNTIME_PACK_ID_RE = re.compile(r"^mavi-runtime-v2-[0-9a-f]{64}$")
_RUNTIME_SCHEMA = "mavi-vision-runtime-pack-v2"


class ComponentIdentityError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class RuntimePackIdentityInputs:
    platform_variant: str
    python_version: str
    third_party_lock_sha256: str
    runtime_requirements_sha256: str
    native_abi: str


def validate_identity_text(value: str) -> None:
    if not value or value != value.strip() or "\x00" in value or "\r" in value or "\n" in value:
        raise ComponentIdentityError("component_identity_text_invalid")


_validate_text = validate_identity_text


def _validate_sha256(value: str) -> None:
    if _SHA256_RE.fullmatch(value) is None:
        raise ComponentIdentityError("component_identity_sha256_invalid")


def canonical_identity_digest(payload: Mapping[str, object]) -> str:
    """SHA-256 of the one canonical JSON encoding used by every pack identity.

    Sorted keys, compact separators, ASCII-only and a trailing newline. Runtime
    Pack v2 and Model Pack v2 identities both hash through this function.
    """
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


_digest_payload = canonical_identity_digest


def runtime_pack_id(inputs: RuntimePackIdentityInputs) -> str:
    for value in (
        inputs.platform_variant,
        inputs.python_version,
        inputs.native_abi,
    ):
        _validate_text(value)
    _validate_sha256(inputs.third_party_lock_sha256)
    _validate_sha256(inputs.runtime_requirements_sha256)
    payload = {
        "schemaVersion": _RUNTIME_SCHEMA,
        **asdict(inputs),
    }
    return RUNTIME_PACK_ID_PREFIX + canonical_identity_digest(payload)


__all__ = [
    "ComponentIdentityError",
    "RUNTIME_PACK_ID_PREFIX",
    "RUNTIME_PACK_ID_RE",
    "SHA256_RE",
    "RuntimePackIdentityInputs",
    "canonical_identity_digest",
    "runtime_pack_id",
    "validate_identity_text",
]
