"""Content-derived identities for reusable MAVI Vision components."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RUNTIME_SCHEMA = "mavi-vision-runtime-pack-v2"
_MODEL_SCHEMA = "mavi-vision-model-pack-v1"


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


@dataclass(frozen=True, slots=True)
class ModelPackIdentityInputs:
    model_id: str
    checkpoint_sha256: str
    resolved_config_sha256: str


def _validate_text(value: str) -> None:
    if not value or value != value.strip() or "\x00" in value or "\r" in value or "\n" in value:
        raise ComponentIdentityError("component_identity_text_invalid")


def _validate_sha256(value: str) -> None:
    if _SHA256_RE.fullmatch(value) is None:
        raise ComponentIdentityError("component_identity_sha256_invalid")


def _digest_payload(payload: dict[str, str]) -> str:
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
    return f"mavi-runtime-v2-{_digest_payload(payload)}"


def model_pack_id(inputs: ModelPackIdentityInputs) -> str:
    _validate_text(inputs.model_id)
    _validate_sha256(inputs.checkpoint_sha256)
    _validate_sha256(inputs.resolved_config_sha256)
    payload = {
        "schemaVersion": _MODEL_SCHEMA,
        **asdict(inputs),
    }
    return f"mavi-model-v1-{_digest_payload(payload)}"


__all__ = [
    "ComponentIdentityError",
    "ModelPackIdentityInputs",
    "RuntimePackIdentityInputs",
    "model_pack_id",
    "runtime_pack_id",
]
