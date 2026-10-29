"""The embedding analysis identity, the pipeline profile and Model Pack verification (ADR-021 §1–§3).

The identity is immutable (ADR-013 §11): the model id and version, the SHA-256 of the model manifest's raw bytes,
its embedding dimension, and the pipeline profile id, version and raw-byte SHA-256. Its canonical text is JSON with
sorted keys, no whitespace, UTF-8 and one trailing LF; the fingerprint is the SHA-256 of that text.
``contracts/test-vectors/embedding-identity-v1.json`` pins both for the .NET platform and this worker.
Device, runtime variant and commit are provenance, never identity.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, ValidationError

from mavi_vision.embeddings.contracts import (
    AGGREGATION_ID,
    CAPABILITY_ID,
    IDENTITY_SCHEMA_VERSION,
    MAXIMUM_TEXT_CHARACTERS,
    PIPELINE_SCHEMA_VERSION,
    PREPROCESSING_ID,
    IdentityContract,
)
from mavi_vision.runtime.manifest import ReleaseMetadataError
from mavi_vision.runtime.model_manifest_v2 import ModelManifestV2, parse_model_manifest_v2

TEXT_TOKEN_LENGTH = 64
_HASH_BLOCK = 1 << 20


class EmbeddingPipelineProfile(BaseModel):
    """``mavi-embedding-pipeline-v1``: preprocessing, aggregation and the crop floor the identity pins."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, populate_by_name=False)

    schema_version: Literal["mavi-embedding-pipeline-v1"] = Field(alias="schemaVersion")
    pipeline_id: StrictStr = Field(alias="pipelineId", max_length=64, pattern=r"^[a-z](?:-?[a-z0-9])*$")
    pipeline_version: StrictStr = Field(alias="pipelineVersion", pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    development_only: StrictBool = Field(alias="developmentOnly")
    model_manifest: StrictStr = Field(alias="modelManifest", min_length=1, max_length=512)
    dimension: StrictInt = Field(ge=1, le=4096)
    preprocessing: Literal["siglip2-fixed-224-v1"]
    aggregation: Literal["mean-l2-v1"]
    minimum_crop_side: StrictInt = Field(alias="minimumCropSide", ge=1, le=4096)
    object_classes: tuple[Literal["Person", "Vehicle"], ...] = Field(alias="objectClasses", min_length=1)
    text_maximum_tokens: Literal[64] = Field(alias="textMaximumTokens")
    text_maximum_characters: StrictInt = Field(alias="textMaximumCharacters", ge=1, le=MAXIMUM_TEXT_CHARACTERS)


@dataclass(frozen=True, slots=True)
class EmbeddingIdentity:
    model_id: str
    model_version: str
    manifest_sha256: str
    dimension: int
    pipeline_id: str
    pipeline_version: str
    pipeline_sha256: str

    def document(self) -> dict[str, object]:
        return {
            "model": {
                "dimension": self.dimension,
                "id": self.model_id,
                "manifestSha256": self.manifest_sha256,
                "version": self.model_version,
            },
            "pipeline": {"id": self.pipeline_id, "sha256": self.pipeline_sha256, "version": self.pipeline_version},
            "schemaVersion": IDENTITY_SCHEMA_VERSION,
        }

    @property
    def canonical(self) -> str:
        return json.dumps(self.document(), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical.encode("utf-8")).hexdigest()

    def matches(self, contract: IdentityContract) -> bool:
        """Whether a leased identity is exactly this one, member by member and by fingerprint."""
        return (
            contract.fingerprint == self.fingerprint
            and contract.model.id == self.model_id
            and contract.model.version == self.model_version
            and contract.model.manifest_sha256 == self.manifest_sha256
            and contract.model.dimension == self.dimension
            and contract.pipeline.id == self.pipeline_id
            and contract.pipeline.version == self.pipeline_version
            and contract.pipeline.sha256 == self.pipeline_sha256
        )


@dataclass(frozen=True, slots=True)
class ResolvedEmbeddingPack:
    identity: EmbeddingIdentity
    profile: EmbeddingPipelineProfile
    manifest: ModelManifestV2


def _read(path: Path, code: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ValueError(code) from exc


def load_pipeline_profile(path: Path) -> tuple[EmbeddingPipelineProfile, str]:
    """The profile and the SHA-256 of its raw bytes."""
    payload = _read(path, "embedding_pipeline_profile_unreadable")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("embedding_pipeline_profile_invalid") from exc
    if not isinstance(document, dict) or document.get("schemaVersion") != PIPELINE_SCHEMA_VERSION:
        raise ValueError("embedding_pipeline_profile_schema_unsupported")
    try:
        profile = EmbeddingPipelineProfile.model_validate_json(payload)
    except ValidationError as exc:
        raise ValueError("embedding_pipeline_profile_invalid") from exc
    if profile.preprocessing != PREPROCESSING_ID or profile.aggregation != AGGREGATION_ID:
        raise ValueError("embedding_pipeline_profile_unsupported")
    return profile, hashlib.sha256(payload).hexdigest()


def load_embedding_manifest(path: Path) -> tuple[ModelManifestV2, str, int]:
    """The parsed manifest v2, the SHA-256 of its raw bytes and its ``embedding.dimension``."""
    payload = _read(path, "embedding_manifest_unreadable")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("embedding_manifest_invalid") from exc
    try:
        manifest = parse_model_manifest_v2(document)
    except ReleaseMetadataError as exc:
        raise ValueError(f"embedding_manifest_invalid:{exc.code}") from exc
    if CAPABILITY_ID not in manifest.capability_ids:
        raise ValueError("embedding_manifest_capability_missing")
    section = manifest.capability_specific.get(CAPABILITY_ID)
    dimension = None if section is None else section.get("dimension")
    if not isinstance(dimension, int) or isinstance(dimension, bool) or not 1 <= dimension <= 4096:
        raise ValueError("embedding_manifest_dimension_invalid")
    return manifest, hashlib.sha256(payload).hexdigest(), dimension


def resolve_embedding_pack(manifest_path: Path, profile_path: Path) -> ResolvedEmbeddingPack:
    """The identity the worker leases with, from the manifest and profile bytes alone."""
    profile, profile_sha256 = load_pipeline_profile(profile_path)
    manifest, manifest_sha256, dimension = load_embedding_manifest(manifest_path)
    if PurePosixPath(profile.model_manifest).name != manifest_path.name:
        raise ValueError("embedding_profile_manifest_mismatch")
    if profile.dimension != dimension:
        raise ValueError("embedding_profile_dimension_mismatch")
    identity = EmbeddingIdentity(
        model_id=manifest.model_id,
        model_version=manifest.model_version,
        manifest_sha256=manifest_sha256,
        dimension=dimension,
        pipeline_id=profile.pipeline_id,
        pipeline_version=profile.pipeline_version,
        pipeline_sha256=profile_sha256,
    )
    return ResolvedEmbeddingPack(identity, profile, manifest)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(_HASH_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_model_pack(manifest: ModelManifestV2, model_root: Path) -> Mapping[str, Path]:
    """Every manifest artefact, hash-verified under ``model_root``, by artefact role; any mismatch refuses the pack.

    Paths are the manifest's logical relative paths (validated by the manifest parser), resolved under the root and
    refused if they escape it. Nothing is loaded before every artefact has been verified.
    """
    root = model_root.resolve()
    verified: dict[str, Path] = {}
    for artifact in manifest.artifacts:
        path = (root / PurePosixPath(artifact.relative_path)).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"embedding_model_artifact_path_invalid:{artifact.artifact_role}")
        if not path.is_file():
            raise ValueError(f"embedding_model_artifact_missing:{artifact.artifact_role}")
        try:
            actual = file_sha256(path)
        except OSError as exc:
            raise ValueError(f"embedding_model_artifact_unreadable:{artifact.artifact_role}") from exc
        if actual != artifact.sha256:
            raise ValueError(f"embedding_model_artifact_hash_mismatch:{artifact.artifact_role}")
        verified[artifact.artifact_role] = path
    return verified


__all__ = [
    "EmbeddingIdentity",
    "EmbeddingPipelineProfile",
    "ResolvedEmbeddingPack",
    "TEXT_TOKEN_LENGTH",
    "file_sha256",
    "load_embedding_manifest",
    "load_pipeline_profile",
    "resolve_embedding_pack",
    "verify_model_pack",
]
