"""Shared primitives for the strict, versioned component-binding v2 schemas.

Every v2 loader (component binding, source model manifest, runtime profile,
qualification record, capability gate sets) validates through these helpers so
that one rule has exactly one implementation.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from mavi_vision.runtime.manifest import ReleaseMetadataError, validate_release_text_file

KEBAB_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_ERROR_CODE_RE = re.compile(r"^[a-z][a-z0-9_]*(?::[A-Za-z0-9._-]+)*$")


class StrictModel(BaseModel):
    """Unknown fields are rejected; parsed values are immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=False)


def require_text(value: str, *, code: str) -> str:
    if (
        not value
        or value != value.strip()
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise ValueError(code)
    return value


def require_optional_text(value: str | None, *, code: str) -> str | None:
    return None if value is None else require_text(value, code=code)


def require_kebab_id(value: str, *, code: str) -> str:
    if KEBAB_ID_RE.fullmatch(value) is None:
        raise ValueError(code)
    return value


def release_error(exc: ValidationError, *, default_code: str) -> ReleaseMetadataError:
    """Map a schema failure to a stable code.

    A validator that raised ``ValueError("<code>")`` surfaces that code; any
    structural failure (missing field, wrong type, unknown field, wrong literal)
    surfaces ``default_code`` so callers never see pydantic wording.
    """
    for error in exc.errors():
        if error.get("type") == "value_error":
            message = str(error.get("ctx", {}).get("error", ""))
            if _ERROR_CODE_RE.fullmatch(message):
                return ReleaseMetadataError(message)
    return ReleaseMetadataError(default_code)


class _DuplicateKey(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def parse_release_json_bytes(payload: bytes, *, code: str) -> dict[str, Any]:
    """Parse v2 release JSON; a duplicate object key is a failure, never last-wins."""
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey) as exc:
        raise ReleaseMetadataError(code) from exc
    if not isinstance(value, dict):
        raise ReleaseMetadataError(code)
    return value


def read_release_json_v2(path: Path, *, code: str) -> tuple[dict[str, Any], bytes]:
    """Read UTF-8/LF release text once; return the parsed object and the exact bytes."""
    payload = validate_release_text_file(path)
    return parse_release_json_bytes(payload, code=code), payload


__all__ = [
    "KEBAB_ID_RE",
    "parse_release_json_bytes",
    "read_release_json_v2",
    "require_optional_text",
    "StrictModel",
    "release_error",
    "require_kebab_id",
    "require_text",
]
