"""Canonical encoding, identifiers and privacy guards shared by every S2c.1 record.

Every record is a JSON object encoded canonically (sorted keys, no insignificant
whitespace, ASCII, no NaN, one trailing newline) and identified by the SHA-256 of
those bytes. List order is part of the content: each record normalises its lists
into a documented order *before* hashing, so the same content always has the same
identity regardless of the order a producer emitted it in.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path
from uuid import UUID


class CorpusError(ValueError):
    """A record violates its contract. The message is a stable, machine-readable code."""


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
# Corpus-local pseudonymous identifiers (site, camera, source, annotator, groups, ...).
# Deliberately narrow: lower-case kebab tokens cannot carry a path, a URL or a
# human-readable location name with spaces.
PSEUDONYM_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
TOKEN_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
# Free text may use "/" ordinarily ("upper/lower"); these shapes are paths or locators.
_PATH_LIKE_RE = re.compile(
    r"(?:^|[\s\"'(=])(?:/[A-Za-z0-9._~-]|~[/\\]|[A-Za-z]:[\\/]|\\\\|\.\.[/\\])|file:|[a-z][a-z0-9+.-]*://",
    re.IGNORECASE,
)


def canonical_json(document: object) -> bytes:
    return (
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("ascii")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def document_sha256(document: object) -> str:
    return sha256_hex(canonical_json(document))


def lf_normalised_sha256(path: Path) -> str:
    """SHA-256 of a text file after CRLF -> LF only (MSR method §10)."""
    return sha256_hex(path.read_bytes().replace(b"\r\n", b"\n"))


def write_canonical(path: Path, document: object) -> str:
    data = canonical_json(document)
    path.write_bytes(data)
    return sha256_hex(data)


def read_json(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusError(f"json_unreadable:{path.name}") from exc
    if not isinstance(document, dict):
        raise CorpusError(f"json_not_object:{path.name}")
    return document


def require(condition: bool, code: str) -> None:
    if not condition:
        raise CorpusError(code)


def require_keys(document: Mapping[str, object], code: str, required: Iterable[str], optional: Iterable[str] = ()) -> None:
    required_set, allowed = set(required), set(required) | set(optional)
    missing = sorted(required_set - document.keys())
    extra = sorted(document.keys() - allowed)
    require(not missing, f"{code}:missing:{','.join(missing)}")
    require(not extra, f"{code}:unexpected:{','.join(extra)}")


def require_sha256(value: object, code: str) -> str:
    require(isinstance(value, str) and SHA256_RE.fullmatch(value) is not None, code)
    return value  # type: ignore[return-value]


def require_pseudonym(value: object, code: str) -> str:
    require(isinstance(value, str) and PSEUDONYM_RE.fullmatch(value) is not None, code)
    return value  # type: ignore[return-value]


def require_token(value: object, code: str) -> str:
    require(isinstance(value, str) and len(value) <= 64 and TOKEN_RE.fullmatch(value) is not None, code)
    return value  # type: ignore[return-value]


def require_uuid(value: object, code: str) -> str:
    require(isinstance(value, str), code)
    try:
        parsed = UUID(value)  # type: ignore[arg-type]
    except ValueError as exc:
        raise CorpusError(code) from exc
    require(str(parsed) == value, code)  # canonical lower-case hyphenated form only
    return value  # type: ignore[return-value]


def require_date(value: object, code: str) -> date:
    require(isinstance(value, str) and DATE_RE.fullmatch(value) is not None, code)
    try:
        return date.fromisoformat(value)  # type: ignore[arg-type]
    except ValueError as exc:
        raise CorpusError(code) from exc


def require_datetime(value: object, code: str) -> str:
    require(isinstance(value, str) and DATETIME_RE.fullmatch(value) is not None, code)
    return value  # type: ignore[return-value]


def require_int(value: object, code: str, minimum: int | None = None, maximum: int | None = None) -> int:
    require(isinstance(value, int) and not isinstance(value, bool), code)
    require(minimum is None or value >= minimum, code)  # type: ignore[operator]
    require(maximum is None or value <= maximum, code)  # type: ignore[operator]
    return value  # type: ignore[return-value]


def require_free_text(value: object, code: str, maximum: int = 2000) -> str:
    require(isinstance(value, str) and len(value) <= maximum, code)
    require(_PATH_LIKE_RE.search(value) is None, f"{code}:path_like")  # type: ignore[arg-type]
    return value  # type: ignore[return-value]


def refuse_path_leaks(document: object, code: str = "record_path_leak") -> None:
    """Refuse any string anywhere in a record that looks like a local path or locator.

    Durable identity is opaque (UUID, SHA-256, pseudonym). A local evidence-store
    path in a manifest would make the record machine-specific and could disclose
    private directory structure, so no record may carry one.
    """

    def walk(node: object) -> None:
        if isinstance(node, str):
            require(_PATH_LIKE_RE.search(node) is None and "\\" not in node, code)
        elif isinstance(node, Mapping):
            for key, value in node.items():
                walk(key)
                walk(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)

    walk(document)


def hash_rank(seed: str, namespace: str, key: str) -> str:
    """Deterministic, seed-dependent ordering key (never random, never insertion order)."""
    return sha256_hex(f"{seed}|{namespace}|{key}".encode("utf-8"))
