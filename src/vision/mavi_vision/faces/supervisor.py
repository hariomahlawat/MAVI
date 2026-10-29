"""Startup and readiness of the ``faces`` role (PoC S6; ADR-022 §2–§3).

Composition is explicit and Development-only, as for the embeddings role: settings -> pipeline profile and model
manifest (identity from their raw bytes) -> every manifest artefact SHA-256 verified under the model root -> the ONNX
adapter (detector and embedder) on the resolved device -> provenance. The supervisor is READY only when all of that
succeeds; otherwise it is UNAVAILABLE with a stable reason, and an UNAVAILABLE worker never leases.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Mapping

from mavi_vision.embeddings.onnx_model import DeviceResolution, runtime_variant
from mavi_vision.faces.contracts import ROLE_ID, RUNTIME_PROFILE_ID, WORKER_VERSION
from mavi_vision.faces.identity import FaceIdentity, FacePipelineProfile, resolve_face_pack, verify_model_pack
from mavi_vision.faces.model import FaceModel
from mavi_vision.faces.onnx_model import load_onnx_face_model
from mavi_vision.faces.settings import FaceWorkerSettings

_LOGGER = logging.getLogger(__name__)


class FaceRuntimeState(StrEnum):
    STARTING = "starting"
    READY = "ready"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class LoadedModel:
    model: FaceModel
    resolution: DeviceResolution
    onnxruntime_version: str


ModelFactory = Callable[[Mapping[str, Path], FacePipelineProfile, FaceWorkerSettings], LoadedModel]


def onnx_model_factory(artifacts: Mapping[str, Path], profile: FacePipelineProfile, settings: FaceWorkerSettings) -> LoadedModel:
    model = load_onnx_face_model(artifacts, dimension=profile.dimension, preprocessing=profile.preprocessing,
                                 settings=profile.detector, device_policy=settings.device_policy,
                                 device_index=settings.device_index, cuda_dll_directory=settings.cuda_dll_directory)
    return LoadedModel(model, model.resolution, model.onnxruntime_version)


@dataclass(frozen=True, slots=True)
class FaceRuntime:
    identity: FaceIdentity
    profile: FacePipelineProfile
    model: FaceModel
    provenance: Mapping[str, object]


def build_provenance(identity: FaceIdentity, loaded: LoadedModel) -> dict[str, object]:
    """``face-complete-v1`` provenance: the producing runtime, truthfully; never part of the identity."""
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


class FaceSupervisor:
    def __init__(self, settings: FaceWorkerSettings, *, model_factory: ModelFactory = onnx_model_factory) -> None:
        self._settings = settings
        self._model_factory = model_factory
        self._state = FaceRuntimeState.STARTING
        self._reason: str | None = None
        self._runtime: FaceRuntime | None = None

    @property
    def state(self) -> FaceRuntimeState:
        return self._state

    @property
    def unavailable_reason(self) -> str | None:
        return self._reason

    @property
    def runtime(self) -> FaceRuntime:
        if self._runtime is None:
            raise RuntimeError("face_runtime_not_ready")
        return self._runtime

    def start(self) -> None:
        settings = self._settings
        try:
            if settings.production_mode:
                raise ValueError("face_role_development_only")
            resolved = resolve_face_pack(settings.face_manifest_path, settings.face_pipeline_profile_path)
            if not resolved.profile.development_only:
                raise ValueError("face_profile_not_development")
            # Every artefact is verified before any byte is handed to a model loader.
            artifacts = verify_model_pack(resolved.manifest, settings.model_root)
            loaded = self._model_factory(artifacts, resolved.profile, settings)
            if loaded.model.dimension != resolved.identity.dimension:
                raise ValueError("face_model_dimension_mismatch")
            provenance = build_provenance(resolved.identity, loaded)
        except ValueError as exc:
            self._reason = str(exc).split("\n", 1)[0][:128] or "face_startup_failed"
            self._state = FaceRuntimeState.UNAVAILABLE
            _LOGGER.error("MAVI faces runtime UNAVAILABLE: %s", self._reason)
            return
        self._runtime = FaceRuntime(resolved.identity, resolved.profile, loaded.model, provenance)
        self._state = FaceRuntimeState.READY
        _LOGGER.info("MAVI faces runtime READY: identity %s (%s %s, %s on %s)", resolved.identity.fingerprint,
                     resolved.identity.model_id, resolved.identity.model_version, loaded.resolution.execution_provider,
                     loaded.resolution.actual_device)


__all__ = [
    "FaceRuntime",
    "FaceRuntimeState",
    "FaceSupervisor",
    "LoadedModel",
    "ModelFactory",
    "build_provenance",
    "onnx_model_factory",
]
