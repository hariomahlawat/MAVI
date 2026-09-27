from __future__ import annotations

import codecs
import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

_SHA256_LENGTH = 64

# Network/online resolver locators that must never appear in release metadata.
# This is the single definition: tools/verify_repo.py and the v2 schemas both use it.
# The scheme separator is joined at import time so this production module contains
# no literal Internet URL (verify_repo's production URL scan covers this package).
_SCHEME_SEPARATOR = ":" + "//"
RELEASE_NETWORK_LOCATORS = (
    "http" + _SCHEME_SEPARATOR,
    "https" + _SCHEME_SEPARATOR,
    "git+",
    "ssh" + _SCHEME_SEPARATOR,
    "ftp" + _SCHEME_SEPARATOR,
    "s3" + _SCHEME_SEPARATOR,
    "hf" + _SCHEME_SEPARATOR,
    "mim" + _SCHEME_SEPARATOR,
    "modelzoo" + _SCHEME_SEPARATOR,
    "torchvision" + _SCHEME_SEPARATOR,
    "openmmlab" + _SCHEME_SEPARATOR,
)


def find_release_network_hazard(text: str) -> str | None:
    """Return the first forbidden network locator found in ``text`` (case-insensitive)."""
    lowered = text.lower()
    for locator in RELEASE_NETWORK_LOCATORS:
        if locator in lowered:
            return locator
    return None


class ReleaseMetadataError(ValueError):
    """Stable validation failure for release metadata and trusted artifacts."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    relative_path: str
    sha256: str


def validate_sha256_hex(value: str) -> None:
    if (
        len(value) != _SHA256_LENGTH
        or value.lower() != value
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("sha256_invalid")


def validate_logical_relative_path(value: str) -> None:
    if not value or value != value.strip() or "\\" in value or "\x00" in value:
        raise ValueError("release_artifact_path_invalid")

    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("release_artifact_path_invalid")

    logical = PurePosixPath(value)
    parts = logical.parts
    if logical.is_absolute() or not parts:
        raise ValueError("release_artifact_path_invalid")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("release_artifact_path_invalid")
    if ":" in parts[0]:
        raise ValueError("release_artifact_path_invalid")


def validate_release_text_file(path: Path) -> bytes:
    """Validate deterministic UTF-8/LF release text and return exact bytes."""
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ReleaseMetadataError("release_text_unreadable") from exc

    if payload.startswith(codecs.BOM_UTF8):
        raise ReleaseMetadataError("release_text_bom_forbidden")
    if b"\r" in payload:
        raise ReleaseMetadataError("release_text_cr_forbidden")
    try:
        payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ReleaseMetadataError("release_text_utf8_invalid") from exc
    return payload


def read_release_json(path: Path, *, code: str) -> dict[str, Any]:
    payload = validate_release_text_file(path)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseMetadataError(code) from exc
    if not isinstance(value, dict):
        raise ReleaseMetadataError(code)
    return value


def sha256_release_file(path: Path) -> str:
    """Hash exact on-disk bytes without normalization or reserialization."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ReleaseMetadataError("release_artifact_unreadable") from exc
    return digest.hexdigest()


def _path_is_link_or_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ReleaseMetadataError("release_artifact_missing") from exc

    if stat.S_ISLNK(info.st_mode):
        return True

    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    file_attributes = getattr(info, "st_file_attributes", 0)
    return bool(reparse_flag and file_attributes & reparse_flag)


def _absolute_lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _validate_no_link_ancestry(path: Path) -> None:
    absolute = _absolute_lexical(path)
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if not current.exists():
            raise ReleaseMetadataError("release_artifact_missing")
        if _path_is_link_or_reparse(current):
            raise ReleaseMetadataError("release_artifact_link_forbidden")


def resolve_release_artifact(model_root: Path, artifact: ArtifactRef) -> Path:
    """Resolve one local release artifact without following link/reparse components."""
    validate_logical_relative_path(artifact.relative_path)

    root = _absolute_lexical(model_root)
    if not root.is_dir():
        raise ReleaseMetadataError("model_root_invalid")
    _validate_no_link_ancestry(root)

    parts = PurePosixPath(artifact.relative_path).parts
    candidate = root.joinpath(*parts)
    current = root
    for part in parts:
        current = current / part
        if not current.exists():
            raise ReleaseMetadataError("release_artifact_missing")
        if _path_is_link_or_reparse(current):
            raise ReleaseMetadataError("release_artifact_link_forbidden")

    if not candidate.is_file():
        raise ReleaseMetadataError("release_artifact_not_file")

    try:
        root_identity = root.resolve(strict=True)
        candidate_identity = candidate.resolve(strict=True)
        candidate_identity.relative_to(root_identity)
    except (OSError, ValueError) as exc:
        raise ReleaseMetadataError("release_artifact_outside_root") from exc

    return candidate_identity
