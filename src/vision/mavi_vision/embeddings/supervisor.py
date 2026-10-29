"""Startup and readiness of the ``embeddings`` role (PoC S4; ADR-021 §2–§3).

Composition is explicit and Development-only: settings -> pipeline profile and model manifest (identity from their
raw bytes) -> every manifest artefact SHA-256 verified under the model root -> the ONNX adapter on the resolved
device -> provenance. The supervisor is READY only when all of that succeeds; otherwise it is UNAVAILABLE with a
stable reason, and an UNAVAILABLE worker never leases, so it can never consume an attempt it cannot serve.

The role is not composed through the Component Binding resolver: that path would need a binding, a runtime-family
qualification record and an ``embedding`` role contract in the resolver, all for a Development-only pilot whose
identity the manifest and profile bytes already pin. ``embedding`` therefore stays out of the resolver's implemented
capabilities and role entry points.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Mapping

from mavi_vision.embeddings.contracts import ROLE_ID, RUNTIME_PROFILE_ID, WORKER_VERSION
from mavi_vision.embeddings.identity import EmbeddingIdentity, EmbeddingPipelineProfile, resolve_embedding_pack, verify_model_pack
from mavi_vision.embeddings.model import EmbeddingModel
from mavi_vision.embeddings.onnx_model import DeviceResolution, load_onnx_model, runtime_variant
from mavi_vision.embeddings.settings import EmbeddingWorkerSettings

_LOGGER = logging.getLogger(__name__)


class EmbeddingRuntimeState(StrEnum):
    STARTING = "starting"
    READY = "ready"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class LoadedModel:
    model: EmbeddingModel
    resolution: DeviceResolution
    onnxruntime_version: str


ModelFactory = Callable[[Mapping[str, Path], int, EmbeddingWorkerSettings], LoadedModel]


def onnx_model_factory(artifacts: Mapping[str, Path], dimension: int, settings: EmbeddingWorkerSettings) -> LoadedModel:
    model = load_onnx_model(artifacts, dimension=dimension, device_policy=settings.device_policy,
                            device_index=settings.device_index, cuda_dll_directory=settings.cuda_dll_directory)
    return LoadedModel(model, model.resolution, model.onnxruntime_version)


@dataclass(frozen=True, slots=True)
class EmbeddingRuntime:
    identity: EmbeddingIdentity
    profile: EmbeddingPipelineProfile
    model: EmbeddingModel
    provenance: Mapping[str, object]


def build_provenance(identity: EmbeddingIdentity, loaded: LoadedModel) -> dict[str, object]:
    """``embedding-complete-v1`` provenance: the producing runtime, truthfully; never part of the identity."""
    return {
        "roleId": ROLE_ID,
        "identityFingerprint": identity.fingerprint,
        "runtimeProfileId": RUNTIME_PROFILE_ID,
        "runtimeVariant": runtime_variant(loaded.resolution),
        "executionProvider": loaded.resolution.execution_provider,
        "actualDevice": loaded.resolution.actual_device,
        "deviceResolutionReason": loaded.resolution.reason,
        "onnxRuntimeVersion": loaded.onnxruntime_version,
        "workerVersion": WORKER_VERSION,
    }


class EmbeddingSupervisor:
    def __init__(self, settings: EmbeddingWorkerSettings, *, model_factory: ModelFactory = onnx_model_factory) -> None:
        self._settings = settings
        self._model_factory = model_factory
        self._state = EmbeddingRuntimeState.STARTING
        self._reason: str | None = None
        self._runtime: EmbeddingRuntime | None = None

    @property
    def state(self) -> EmbeddingRuntimeState:
        return self._state

    @property
    def unavailable_reason(self) -> str | None:
        return self._reason

    @property
    def runtime(self) -> EmbeddingRuntime:
        if self._runtime is None:
            raise RuntimeError("embedding_runtime_not_ready")
        return self._runtime

    def start(self) -> None:
        settings = self._settings
        try:
            if settings.production_mode:
                raise ValueError("embedding_role_development_only")
            resolved = resolve_embedding_pack(settings.embedding_manifest_path, settings.pipeline_profile_path)
            if not resolved.profile.development_only:
                raise ValueError("embedding_profile_not_development")
            # Every artefact is verified before any byte is handed to a model loader.
            artifacts = verify_model_pack(resolved.manifest, settings.model_root)
            loaded = self._model_factory(artifacts, resolved.identity.dimension, settings)
            if loaded.model.dimension != resolved.identity.dimension:
                raise ValueError("embedding_model_dimension_mismatch")
            provenance = build_provenance(resolved.identity, loaded)
        except ValueError as exc:
            self._reason = str(exc).split("\n", 1)[0][:128] or "embedding_startup_failed"
            self._state = EmbeddingRuntimeState.UNAVAILABLE
            _LOGGER.error("MAVI embeddings runtime UNAVAILABLE: %s", self._reason)
            return
        self._runtime = EmbeddingRuntime(resolved.identity, resolved.profile, loaded.model, provenance)
        self._state = EmbeddingRuntimeState.READY
        _LOGGER.info("MAVI embeddings runtime READY: identity %s (%s %s, %s on %s)", resolved.identity.fingerprint,
                     resolved.identity.model_id, resolved.identity.model_version, loaded.resolution.execution_provider,
                     loaded.resolution.actual_device)


__all__ = [
    "EmbeddingRuntime",
    "EmbeddingRuntimeState",
    "EmbeddingSupervisor",
    "LoadedModel",
    "ModelFactory",
    "build_provenance",
    "onnx_model_factory",
]
