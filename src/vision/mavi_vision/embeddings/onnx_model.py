"""The SigLIP 2 ONNX adapter of the ``embeddings`` role (ADR-021 §1–§2; ``embeddings-onnx-v1`` runtime only).

Two ONNX Runtime sessions over hash-verified pack bytes: ``vision.onnx`` (``pixel_values`` float32
``[N, 3, 224, 224]`` -> ``image_embeds`` ``[N, D]``) and ``text.onnx`` (``input_ids`` int64 ``[N, 64]`` ->
``text_embeds`` ``[N, D]``), plus the pack's SentencePiece ``tokenizer.model``.

Device policy (ADR-008: never a silent substitution):

* ``cpu`` -> ``CPUExecutionProvider`` (``explicit_cpu``);
* ``cuda`` -> ``CUDAExecutionProvider`` or refusal: the provider must be available and the first active provider of
  both sessions, otherwise the role does not start (``explicit_cuda``);
* ``auto`` (Development) -> CUDA when it is available and becomes active (``cuda_selected``), else CPU
  (``cuda_unavailable``).

``onnxruntime`` and ``sentencepiece`` are imported here, lazily, and nowhere else in the role.
"""

from __future__ import annotations

import logging
import os
import platform
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, Mapping

import numpy as np

from mavi_vision.embeddings.model import preprocess
from mavi_vision.embeddings.tokenizer import TEXT_LENGTH, SentencePieceEncoder, load_sentencepiece, sentencepiece_ids

_LOGGER = logging.getLogger(__name__)

VISION_ARTIFACT_ROLE = "onnx-vision-encoder"
TEXT_ARTIFACT_ROLE = "onnx-text-encoder"
TOKENIZER_ARTIFACT_ROLE = "text-tokenizer"
CPU_PROVIDER = "CPUExecutionProvider"
CUDA_PROVIDER = "CUDAExecutionProvider"

# Handles returned by os.add_dll_directory must stay alive for the directory to stay on the search path.
_DLL_DIRECTORY_HANDLES: list[Any] = []


@dataclass(frozen=True, slots=True)
class DeviceResolution:
    execution_provider: Literal["CPUExecutionProvider", "CUDAExecutionProvider"]
    actual_device: str
    reason: str

    @property
    def is_cuda(self) -> bool:
        return self.execution_provider == CUDA_PROVIDER


def runtime_variant(resolution: DeviceResolution) -> str:
    system = "windows" if platform.system() == "Windows" else "linux"
    return f"{system}-x86_64-{'cuda' if resolution.is_cuda else 'cpu'}"


def import_onnxruntime(cuda_dll_directory: Path | None) -> ModuleType:
    """``onnxruntime``, after putting ``cuda_dll_directory`` on the DLL search path when one is configured."""
    if cuda_dll_directory is not None:
        add = getattr(os, "add_dll_directory", None)
        if add is None:
            raise ValueError("embedding_cuda_dll_directory_unsupported")
        if not cuda_dll_directory.is_dir():
            raise ValueError("embedding_cuda_dll_directory_missing")
        _DLL_DIRECTORY_HANDLES.append(add(str(cuda_dll_directory)))
        # The CUDA provider DLL loads cuDNN's sub-libraries through the ordinary PATH search, which
        # os.add_dll_directory does not affect; this process's PATH only, as tools/poc/embeddings_spike.py does.
        os.environ["PATH"] = str(cuda_dll_directory) + os.pathsep + os.environ.get("PATH", "")
    try:
        import onnxruntime  # noqa: PLC0415 - embeddings-onnx-v1 runtime only
    except ImportError as exc:
        raise ValueError("embedding_onnxruntime_unavailable") from exc
    return onnxruntime


class OnnxSiglip2Model:
    """:class:`~mavi_vision.embeddings.model.EmbeddingModel` over the two SigLIP 2 towers."""

    def __init__(self, vision: Any, text: Any, tokenizer: SentencePieceEncoder, *, dimension: int,
                 resolution: DeviceResolution, onnxruntime_version: str) -> None:
        self._vision = vision
        self._text = text
        self._tokenizer = tokenizer
        self._dimension = dimension
        self.resolution = resolution
        self.onnxruntime_version = onnxruntime_version

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_images(self, crops: list[bytes]) -> np.ndarray:
        if not crops:
            return np.zeros((0, self._dimension), dtype=np.float32)
        batch = np.concatenate([preprocess(crop) for crop in crops]).astype(np.float32, copy=False)
        return np.asarray(self._vision.run(["image_embeds"], {"pixel_values": batch})[0])

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dimension), dtype=np.float32)
        ids = np.asarray([sentencepiece_ids(self._tokenizer, text, TEXT_LENGTH) for text in texts], dtype=np.int64)
        return np.asarray(self._text.run(["text_embeds"], {"input_ids": ids})[0])


def _sessions(ort: ModuleType, paths: tuple[Path, Path], providers: list[Any]) -> tuple[Any, Any]:
    options = ort.SessionOptions()
    options.log_severity_level = 3
    return tuple(ort.InferenceSession(str(path), sess_options=options, providers=providers) for path in paths)  # type: ignore[return-value]


def _active(sessions: tuple[Any, ...], provider: str) -> bool:
    return all(session.get_providers()[:1] == [provider] for session in sessions)


def create_sessions(ort: ModuleType, paths: tuple[Path, Path], *, device_policy: str,
                    device_index: int) -> tuple[tuple[Any, Any], DeviceResolution]:
    cuda = [(CUDA_PROVIDER, {"device_id": device_index})]
    if device_policy == "cpu":
        sessions = _sessions(ort, paths, [CPU_PROVIDER])
        if not _active(sessions, CPU_PROVIDER):
            raise ValueError("embedding_cpu_provider_inactive")
        return sessions, DeviceResolution(CPU_PROVIDER, "cpu", "explicit_cpu")
    available = CUDA_PROVIDER in ort.get_available_providers()
    if device_policy == "cuda":
        if not available:
            raise ValueError("embedding_cuda_unavailable")
        try:
            sessions = _sessions(ort, paths, cuda)
        except Exception as exc:  # noqa: BLE001 - provider load faults are ONNX Runtime-specific
            raise ValueError("embedding_cuda_unavailable") from exc
        if not _active(sessions, CUDA_PROVIDER):
            # ONNX Runtime falls back to CPU when the CUDA provider cannot load: refused, never run as CPU.
            raise ValueError("embedding_cuda_provider_inactive")
        return sessions, DeviceResolution(CUDA_PROVIDER, f"cuda:{device_index}", "explicit_cuda")
    if device_policy != "auto":
        raise ValueError("embedding_device_policy_invalid")
    if available:
        try:
            sessions = _sessions(ort, paths, cuda)
        except Exception:  # noqa: BLE001
            sessions = None
        if sessions is not None and _active(sessions, CUDA_PROVIDER):
            return sessions, DeviceResolution(CUDA_PROVIDER, f"cuda:{device_index}", "cuda_selected")
    sessions = _sessions(ort, paths, [CPU_PROVIDER])
    if not _active(sessions, CPU_PROVIDER):
        raise ValueError("embedding_cpu_provider_inactive")
    return sessions, DeviceResolution(CPU_PROVIDER, "cpu", "cuda_unavailable")


def load_onnx_model(artifacts: Mapping[str, Path], *, dimension: int, device_policy: str, device_index: int = 0,
                    cuda_dll_directory: Path | None = None, ort: ModuleType | None = None) -> OnnxSiglip2Model:
    """The adapter over artefacts the caller has already hash-verified (:func:`identity.verify_model_pack`)."""
    try:
        vision_path = artifacts[VISION_ARTIFACT_ROLE]
        text_path = artifacts[TEXT_ARTIFACT_ROLE]
        tokenizer_path = artifacts[TOKENIZER_ARTIFACT_ROLE]
    except KeyError as exc:
        raise ValueError(f"embedding_model_artifact_role_missing:{exc.args[0]}") from None
    module = ort if ort is not None else import_onnxruntime(cuda_dll_directory)
    try:
        tokenizer = load_sentencepiece(tokenizer_path)
    except ImportError as exc:
        raise ValueError("embedding_sentencepiece_unavailable") from exc
    except (OSError, RuntimeError) as exc:
        raise ValueError("embedding_tokenizer_invalid") from exc
    (vision, text), resolution = create_sessions(module, (vision_path, text_path), device_policy=device_policy,
                                                 device_index=device_index)
    _check_signature(vision, "pixel_values", "image_embeds")
    _check_signature(text, "input_ids", "text_embeds")
    _LOGGER.info("Embedding sessions on %s (%s, %s)", resolution.actual_device, resolution.execution_provider, resolution.reason)
    return OnnxSiglip2Model(vision, text, tokenizer, dimension=dimension, resolution=resolution,
                            onnxruntime_version=str(module.__version__))


def _check_signature(session: Any, input_name: str, output_name: str) -> None:
    inputs = [item.name for item in session.get_inputs()]
    outputs = [item.name for item in session.get_outputs()]
    if inputs != [input_name] or output_name not in outputs:
        raise ValueError("embedding_model_signature_invalid")


__all__ = [
    "CPU_PROVIDER",
    "CUDA_PROVIDER",
    "DeviceResolution",
    "OnnxSiglip2Model",
    "create_sessions",
    "import_onnxruntime",
    "load_onnx_model",
    "runtime_variant",
]
