"""The face analysis identity and the face pipeline profile (ADR-022 §2–§3; ADR-013 §11).

The identity has the shape of the embedding identity (ADR-021 §3) under its own schema version
``mavi-face-identity-v1``: the model id and version, the SHA-256 of the model manifest's raw bytes, the embedding
dimension, and the pipeline profile id, version and raw-byte SHA-256. Its canonical text is JSON with sorted keys,
no whitespace, UTF-8 and one trailing LF; the fingerprint is the SHA-256 of that text.
``contracts/test-vectors/face-identity-v1.json`` pins both for the .NET platform and this worker.

The profile pins everything that changes a face outcome: the detector thresholds, the usable-face floor, the
alignment, the embedder preprocessing and the reference threshold shown beside every candidate.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, ValidationError

from mavi_vision.embeddings.identity import load_embedding_manifest, verify_model_pack as _verify_model_pack
from mavi_vision.faces.contracts import (
    ALIGNMENT_ID,
    IDENTITY_SCHEMA_VERSION,
    MAXIMUM_QUERY_IMAGE_BYTES,
    PIPELINE_SCHEMA_VERSION,
    IdentityContract,
)
from mavi_vision.runtime.model_manifest_v2 import ModelManifestV2


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, populate_by_name=False)


class DetectorSettings(_Strict):
    score_threshold: StrictFloat = Field(alias="scoreThreshold", gt=0.0, le=1.0)
    nms_threshold: StrictFloat = Field(alias="nmsThreshold", gt=0.0, le=1.0)
    top_k: StrictInt = Field(alias="topK", ge=1, le=10_000)


class ReferenceThreshold(_Strict):
    cosine: StrictFloat = Field(ge=-1.0, le=1.0)
    provenance: StrictStr = Field(min_length=1, max_length=500)


class FacePipelineProfile(_Strict):
    """``mavi-face-pipeline-v1``."""

    schema_version: Literal["mavi-face-pipeline-v1"] = Field(alias="schemaVersion")
    pipeline_id: StrictStr = Field(alias="pipelineId", max_length=64, pattern=r"^[a-z](?:-?[a-z0-9])*$")
    pipeline_version: StrictStr = Field(alias="pipelineVersion", pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    development_only: StrictBool = Field(alias="developmentOnly")
    model_manifest: StrictStr = Field(alias="modelManifest", min_length=1, max_length=512)
    dimension: StrictInt = Field(ge=1, le=4096)
    detector: DetectorSettings
    minimum_face_side: StrictInt = Field(alias="minimumFaceSide", ge=1, le=4096)
    alignment: Literal["arcface-112-similarity-v1"]
    preprocessing: Literal["adaface-ir50-v1", "sface-v1"]
    reference_threshold: ReferenceThreshold = Field(alias="referenceThreshold")
    object_classes: tuple[Literal["Person"], ...] = Field(alias="objectClasses", min_length=1, max_length=1)
    query_image_maximum_bytes: StrictInt = Field(alias="queryImageMaximumBytes", ge=1, le=MAXIMUM_QUERY_IMAGE_BYTES)


@dataclass(frozen=True, slots=True)
class FaceIdentity:
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
class ResolvedFacePack:
    identity: FaceIdentity
    profile: FacePipelineProfile
    manifest: ModelManifestV2


def load_pipeline_profile(path: Path) -> tuple[FacePipelineProfile, str]:
    """The profile and the SHA-256 of its raw bytes."""
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ValueError("face_pipeline_profile_unreadable") from exc
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("face_pipeline_profile_invalid") from exc
    if not isinstance(document, dict) or document.get("schemaVersion") != PIPELINE_SCHEMA_VERSION:
        raise ValueError("face_pipeline_profile_schema_unsupported")
    try:
        profile = FacePipelineProfile.model_validate_json(payload)
    except ValidationError as exc:
        raise ValueError("face_pipeline_profile_invalid") from exc
    if profile.alignment != ALIGNMENT_ID:
        raise ValueError("face_pipeline_profile_unsupported")
    return profile, hashlib.sha256(payload).hexdigest()


def _face_code(exc: ValueError) -> str:
    """The shared embeddings loaders' refusal codes, in this role's vocabulary."""
    code = str(exc)
    return "face_" + code[len("embedding_"):] if code.startswith("embedding_") else f"face_{code}"


def verify_model_pack(manifest: ModelManifestV2, model_root: Path) -> Mapping[str, Path]:
    """Every manifest artefact hash-verified under ``model_root`` (the embeddings role's check), by artefact role."""
    try:
        return _verify_model_pack(manifest, model_root)
    except ValueError as exc:
        raise ValueError(_face_code(exc)) from exc


def resolve_face_pack(manifest_path: Path, profile_path: Path) -> ResolvedFacePack:
    """The identity the worker leases with, from the manifest and profile bytes alone."""
    profile, profile_sha256 = load_pipeline_profile(profile_path)
    try:
        manifest, manifest_sha256, dimension = load_embedding_manifest(manifest_path)
    except ValueError as exc:
        raise ValueError(_face_code(exc)) from exc
    if PurePosixPath(profile.model_manifest).name != manifest_path.name:
        raise ValueError("face_profile_manifest_mismatch")
    if profile.dimension != dimension:
        raise ValueError("face_profile_dimension_mismatch")
    identity = FaceIdentity(
        model_id=manifest.model_id,
        model_version=manifest.model_version,
        manifest_sha256=manifest_sha256,
        dimension=dimension,
        pipeline_id=profile.pipeline_id,
        pipeline_version=profile.pipeline_version,
        pipeline_sha256=profile_sha256,
    )
    return ResolvedFacePack(identity, profile, manifest)


__all__ = [
    "DetectorSettings",
    "FaceIdentity",
    "FacePipelineProfile",
    "ReferenceThreshold",
    "ResolvedFacePack",
    "load_pipeline_profile",
    "resolve_face_pack",
    "verify_model_pack",
]
