from __future__ import annotations

import codecs
import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


_SHA256_LENGTH = 64


class ReleaseMetadataError(ValueError):
    """Stable validation failure for release metadata and trusted artifacts."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    relative_path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ModelManifest:
    schema_version: str
    model_id: str
    model_version: str
    purpose: str
    backend: str
    architecture: str
    class_vocabulary: tuple[str, ...]
    checkpoint: ArtifactRef
    resolved_config: ArtifactRef
    runtime_profile_id: str
    verification_status: Literal["verified", "unverified"]
    qualification_id: str | None


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _ArtifactRefSchema(_StrictModel):
    relative_path: str = Field(alias="relativePath")
    sha256: str

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        validate_logical_relative_path(value)
        return value

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        validate_sha256_hex(value)
        return value


class _ModelManifestSchema(_StrictModel):
    schema_version: Literal["1.0"] = Field(alias="schemaVersion")
    model_id: str = Field(alias="modelId")
    model_version: str = Field(alias="modelVersion")
    purpose: str
    backend: str
    architecture: str
    class_vocabulary: tuple[str, ...] = Field(alias="classVocabulary")
    checkpoint: _ArtifactRefSchema
    resolved_config: _ArtifactRefSchema = Field(alias="resolvedConfig")
    runtime_profile_id: str = Field(alias="runtimeProfileId")
    verification_status: Literal["verified", "unverified"] = Field(alias="verificationStatus")
    qualification_id: str | None = Field(alias="qualificationId")

    @field_validator(
        "model_id",
        "model_version",
        "purpose",
        "backend",
        "architecture",
        "runtime_profile_id",
    )
    @classmethod
    def validate_nonempty_text(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("release_metadata_text_invalid")
        return value

    @field_validator("class_vocabulary")
    @classmethod
    def validate_vocabulary(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("model_vocabulary_empty")
        if any(not item or item != item.strip() for item in value):
            raise ValueError("model_vocabulary_entry_invalid")
        if len(set(value)) != len(value):
            raise ValueError("model_vocabulary_duplicate")
        return value

    @model_validator(mode="after")
    def validate_verification_relationship(self) -> "_ModelManifestSchema":
        if self.verification_status == "verified" and not self.qualification_id:
            raise ValueError("verified_manifest_requires_qualification")
        if self.qualification_id is not None and (
            not self.qualification_id or self.qualification_id != self.qualification_id.strip()
        ):
            raise ValueError("qualification_id_invalid")
        return self


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


def load_model_manifest(path: Path) -> ModelManifest:
    raw = read_release_json(path, code="model_manifest_invalid")
    try:
        parsed = _ModelManifestSchema.model_validate(raw)
    except ValidationError as exc:
        raise ReleaseMetadataError("model_manifest_invalid") from exc

    return ModelManifest(
        schema_version=parsed.schema_version,
        model_id=parsed.model_id,
        model_version=parsed.model_version,
        purpose=parsed.purpose,
        backend=parsed.backend,
        architecture=parsed.architecture,
        class_vocabulary=parsed.class_vocabulary,
        checkpoint=ArtifactRef(
            relative_path=parsed.checkpoint.relative_path,
            sha256=parsed.checkpoint.sha256,
        ),
        resolved_config=ArtifactRef(
            relative_path=parsed.resolved_config.relative_path,
            sha256=parsed.resolved_config.sha256,
        ),
        runtime_profile_id=parsed.runtime_profile_id,
        verification_status=parsed.verification_status,
        qualification_id=parsed.qualification_id,
    )


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
