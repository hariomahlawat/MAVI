"""Canonical machine bytes for b-2. No permissive JSON reader is used here.

ASCII-escaped JSON is a subset of UTF-8. Keys sort lexically, arrays retain their
contract order, separators are compact and exactly one LF terminates the file.
Only exact ints are accepted for numeric machine fields; floats are deliberately
excluded (including 1.0). Measurements needing fractions use integer microseconds
or frozen rational numerator/denominator fields. No float normalisation ambiguity.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


class OperationalError(ValueError):
    """Stable refusal, with the field or artefact in the message."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise OperationalError(code)


def keys(value: object, expected: set[str], where: str) -> dict:
    require(type(value) is dict and set(value) == expected, f"{where}:fields")
    return value


def integer(value: object, where: str, minimum: int = 0) -> int:
    require(type(value) is int and value >= minimum, f"{where}:integer")
    return value


def text(value: object, where: str) -> str:
    require(type(value) is str and bool(value.strip()), f"{where}:text")
    require(not any(0xD800 <= ord(c) <= 0xDFFF for c in value), f"{where}:unicode_surrogate")
    return value


def digest(value: object, where: str) -> str:
    require(type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value),
            f"{where}:sha256")
    return value


def tokens(value: object, where: str, *, nonempty: bool = False) -> list[str]:
    require(type(value) is list, f"{where}:list")
    for item in value:
        text(item, where)
    require(value == sorted(set(value)) and (not nonempty or bool(value)), f"{where}:sorted_unique")
    return value


def _tree(value: object) -> None:
    if type(value) is dict:
        for key, item in value.items():
            text(key, "json_key")
            _tree(item)
    elif type(value) is list:
        for item in value:
            _tree(item)
    elif type(value) is str:
        text(value, "json_string")
    else:
        require(value is None or type(value) in (bool, int), "json:unsupported_number_or_type")


def canonical(value: object) -> bytes:
    _tree(value)
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                       allow_nan=False) + "\n").encode("utf-8")


def sha256(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _members(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, f"json:duplicate_key:{key}")
        result[key] = value
    return result


def parse(blob: bytes) -> dict:
    try:
        value = json.loads(blob.decode("utf-8"), object_pairs_hook=_members,
                           parse_constant=lambda _: (_ for _ in ()).throw(OperationalError("json:nonfinite")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OperationalError("json:unreadable") from exc
    require(type(value) is dict, "json:object_required")
    require(canonical(value) == blob, "json:noncanonical_bytes")
    return value


def read(path: Path) -> dict:
    try:
        return parse(path.read_bytes())
    except OSError as exc:
        raise OperationalError(f"json:missing:{path.name}") from exc
