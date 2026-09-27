"""Derived v2 Model Pack identity (ADR-014 §3; ADR-007 2026-09-27 note; P-3).

``modelPackId`` is never authored. It is computed from material inputs only:
the pack-identity schema, model id and version, the sorted capability ids and
every artefact's role and SHA-256 (the licence notice included). Application
commit, build provenance and qualification bookkeeping are never inputs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mavi_vision.runtime.capabilities import require_known_capability
from mavi_vision.runtime.component_identity import (
    SHA256_RE,
    ComponentIdentityError,
    canonical_identity_digest,
    validate_identity_text,
)
from mavi_vision.runtime.schema_common import KEBAB_ID_RE

MODEL_PACK_IDENTITY_SCHEMA = "mavi-vision-model-pack-v2"
MODEL_PACK_ID_PREFIX = "mavi-model-v2-"
MODEL_PACK_ID_RE = re.compile(r"^mavi-model-v2-[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ModelPackArtifactIdentity:
    artifact_role: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ModelPackIdentityInputsV2:
    model_id: str
    model_version: str
    capability_ids: tuple[str, ...]
    artifacts: tuple[ModelPackArtifactIdentity, ...]


def model_pack_id_v2(inputs: ModelPackIdentityInputsV2) -> str:
    validate_identity_text(inputs.model_id)
    validate_identity_text(inputs.model_version)
    if not inputs.capability_ids or len(set(inputs.capability_ids)) != len(inputs.capability_ids):
        raise ComponentIdentityError("component_identity_capabilities_invalid")
    for capability_id in inputs.capability_ids:
        try:
            require_known_capability(capability_id)
        except ValueError as exc:
            raise ComponentIdentityError("component_identity_capabilities_invalid") from exc
    roles = [artifact.artifact_role for artifact in inputs.artifacts]
    if not roles or len(set(roles)) != len(roles):
        raise ComponentIdentityError("component_identity_artifacts_invalid")
    for artifact in inputs.artifacts:
        if KEBAB_ID_RE.fullmatch(artifact.artifact_role) is None:
            raise ComponentIdentityError("component_identity_artifacts_invalid")
        if SHA256_RE.fullmatch(artifact.sha256) is None:
            raise ComponentIdentityError("component_identity_sha256_invalid")

    payload = {
        "schemaVersion": MODEL_PACK_IDENTITY_SCHEMA,
        "modelId": inputs.model_id,
        "modelVersion": inputs.model_version,
        "capabilityIds": sorted(inputs.capability_ids),
        "artifacts": [
            {"artifactRole": artifact.artifact_role, "sha256": artifact.sha256}
            for artifact in sorted(inputs.artifacts, key=lambda item: item.artifact_role)
        ],
    }
    return MODEL_PACK_ID_PREFIX + canonical_identity_digest(payload)


__all__ = [
    "MODEL_PACK_IDENTITY_SCHEMA",
    "MODEL_PACK_ID_PREFIX",
    "MODEL_PACK_ID_RE",
    "ModelPackArtifactIdentity",
    "ModelPackIdentityInputsV2",
    "model_pack_id_v2",
]
