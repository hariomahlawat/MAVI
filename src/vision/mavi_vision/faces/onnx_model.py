"""The ONNX adapter of the ``faces`` role (ADR-022 §2–§3; ``embeddings-onnx-v1`` runtime only).

Two ONNX Runtime sessions over the hash-verified pack bytes: ``detector.onnx`` (YuNet 2026may, dynamic
``[1, 3, H, W]``, decoded by :mod:`mavi_vision.faces.detector`) and ``embedder.onnx`` (AdaFace IR-50 or SFace,
``[N, 3, 112, 112]`` -> ``[N, D]``). Device resolution is the embeddings role's (ADR-008, never a silent
substitution): both sessions are created together and must share the resolved provider.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

import numpy as np

from mavi_vision.embeddings.onnx_model import DeviceResolution, create_sessions, import_onnxruntime
from mavi_vision.faces.contracts import DETECTOR_ARTIFACT_ROLE, EMBEDDER_ARTIFACT_ROLE
from mavi_vision.faces.detector import STRIDES, FaceDetection, detect_faces
from mavi_vision.faces.identity import DetectorSettings
from mavi_vision.faces.model import embedder_input

_LOGGER = logging.getLogger(__name__)
DETECTOR_OUTPUTS = tuple(f"{kind}_{stride}" for kind in ("cls", "obj", "bbox", "kps") for stride in STRIDES)


class OnnxFaceModel:
    """:class:`~mavi_vision.faces.model.FaceModel` over the YuNet detector and one embedder."""

    def __init__(self, detector: Any, embedder: Any, *, dimension: int, preprocessing: str, settings: DetectorSettings,
                 resolution: DeviceResolution, onnxruntime_version: str) -> None:
        self._detector = detector
        self._embedder = embedder
        self._dimension = dimension
        self._preprocessing = preprocessing
        self._settings = settings
        self._input = embedder.get_inputs()[0].name
        batch = embedder.get_inputs()[0].shape[0]
        # SFace is exported with a fixed batch of one; AdaFace with a dynamic batch.
        self._fixed_batch = batch if isinstance(batch, int) and batch > 0 else None
        self.resolution = resolution
        self.onnxruntime_version = onnxruntime_version

    @property
    def dimension(self) -> int:
        return self._dimension

    def detect(self, rgb: np.ndarray) -> list[FaceDetection]:
        return detect_faces(self._detector, rgb, score_threshold=self._settings.score_threshold,
                            nms_threshold=self._settings.nms_threshold, top_k=self._settings.top_k)

    def embed(self, faces: list[np.ndarray]) -> np.ndarray:
        if not faces:
            return np.zeros((0, self._dimension), dtype=np.float32)
        batch = np.stack([embedder_input(face, self._preprocessing) for face in faces]).astype(np.float32, copy=False)
        if self._fixed_batch == 1:
            rows = [np.asarray(self._embedder.run(None, {self._input: batch[i:i + 1]})[0]) for i in range(len(faces))]
            return np.concatenate(rows)
        return np.asarray(self._embedder.run(None, {self._input: batch})[0])


def _check_signatures(detector: Any, embedder: Any) -> None:
    if [item.name for item in detector.get_inputs()] != ["input"]:
        raise ValueError("face_detector_signature_invalid")
    if not set(DETECTOR_OUTPUTS) <= {item.name for item in detector.get_outputs()}:
        raise ValueError("face_detector_signature_invalid")
    inputs = embedder.get_inputs()
    if len(inputs) != 1 or list(inputs[0].shape[1:]) != [3, 112, 112] or len(embedder.get_outputs()) != 1:
        raise ValueError("face_embedder_signature_invalid")


def load_onnx_face_model(artifacts: Mapping[str, Path], *, dimension: int, preprocessing: str,
                         settings: DetectorSettings, device_policy: str, device_index: int = 0,
                         cuda_dll_directory: Path | None = None, ort: ModuleType | None = None) -> OnnxFaceModel:
    """The adapter over artefacts the caller has already hash-verified (:func:`identity.verify_model_pack`)."""
    try:
        detector_path = artifacts[DETECTOR_ARTIFACT_ROLE]
        embedder_path = artifacts[EMBEDDER_ARTIFACT_ROLE]
    except KeyError as exc:
        raise ValueError(f"face_model_artifact_role_missing:{exc.args[0]}") from None
    module = ort if ort is not None else import_onnxruntime(cuda_dll_directory)
    (detector, embedder), resolution = create_sessions(module, (detector_path, embedder_path),
                                                       device_policy=device_policy, device_index=device_index)
    _check_signatures(detector, embedder)
    _LOGGER.info("Face sessions on %s (%s, %s)", resolution.actual_device, resolution.execution_provider, resolution.reason)
    return OnnxFaceModel(detector, embedder, dimension=dimension, preprocessing=preprocessing, settings=settings,
                         resolution=resolution, onnxruntime_version=str(module.__version__))


__all__ = ["DETECTOR_OUTPUTS", "OnnxFaceModel", "load_onnx_face_model"]
