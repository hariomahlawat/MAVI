from __future__ import annotations

import ast
import importlib.metadata
import os
import platform
import re
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any, ContextManager
from urllib.parse import urlsplit

import numpy as np
from numpy.typing import NDArray

from mavi_vision.runtime.activity import InferenceActivity
from mavi_vision.runtime.errors import (
    GpuOutOfMemoryError,
    GpuRuntimeError,
    InferenceContractError,
    ProcessingDependencyError,
    RuntimeCompatibilityError,
)
from mavi_vision.runtime.interfaces import (
    PixelBoxXYXY,
    RawDetection,
    RuntimeMetadata,
)
from mavi_vision.runtime.manifest import (
    ArtifactRef,
    ReleaseMetadataError,
    resolve_release_artifact,
    sha256_release_file,
    validate_logical_relative_path,
    validate_release_text_file,
)
from mavi_vision.runtime.qualification import VerifiedReleaseSelection


_DEVICE_PATTERN = re.compile(r"(?:cpu|cuda:(\d+))", re.ASCII)
_FATAL_CUDA_MARKERS = (
    "cuda error",
    "device-side assert",
    "device side assert",
    "illegal memory access",
    "driver shutting down",
    "cuda context",
    "cudnn_status_internal_error",
    "cudnn_status_execution_failed",
)


@dataclass(frozen=True, slots=True)
class _MMDetectionBindings:
    config_fromfile: Callable[[str], Any]
    init_detector: Callable[[Any, str, str], Any]
    inference_detector: Callable[[Any, NDArray[np.uint8]], Any]
    checkpoint_scope: Callable[[], ContextManager[None]]
    versions: Mapping[str, str]
    cuda_oom_error_type: type[BaseException]
    cuda_is_available: Callable[[], bool]
    cuda_device_count: Callable[[], int]
    cuda_empty_cache: Callable[[], None]


def _semantic_version(value: str) -> str:
    if not value:
        raise RuntimeCompatibilityError("runtime_dependency_version_missing")
    return value.split("+", 1)[0]


def _runtime_variant_name(
    *,
    device: str,
    system: str | None = None,
    machine: str | None = None,
) -> str:
    os_name = (system or platform.system()).casefold()
    architecture = (machine or platform.machine()).casefold()

    if os_name == "linux":
        platform_name = "linux"
    elif os_name == "windows":
        platform_name = "windows"
    else:
        raise RuntimeCompatibilityError("runtime_platform_unsupported")

    if architecture not in {"x86_64", "amd64"}:
        raise RuntimeCompatibilityError("runtime_architecture_unsupported")

    accelerator = "cuda" if device.startswith("cuda:") else "cpu"
    return f"{platform_name}-x86_64-{accelerator}"


def _load_backend_bindings() -> _MMDetectionBindings:
    """Load heavyweight ML dependencies only when constructing the runtime."""
    try:
        import av
        import cv2
        import mmcv
        import mmdet
        import mmengine
        import scipy
        import supervision
        import torch
        import torchvision
        from mmdet.apis import inference_detector, init_detector
        from mmengine.config import Config
        from mmengine.logging.history_buffer import HistoryBuffer
        from numpy._core.multiarray import _reconstruct, scalar
    except Exception as exc:
        raise RuntimeCompatibilityError(
            f"runtime_dependency_import_failed:{type(exc).__name__}"
        ) from exc

    try:
        versions = {
            "torch": torch.__version__,
            "torchvision": torchvision.__version__,
            "mmcv": mmcv.__version__,
            "mmengine": mmengine.__version__,
            "mmdet": mmdet.__version__,
            "trackers": importlib.metadata.version("trackers"),
            "supervision": supervision.__version__,
            "scipy": scipy.__version__,
            "numpy": np.__version__,
            "opencv": cv2.__version__,
            "opencvPython": importlib.metadata.version("opencv-python"),
            "av": av.__version__,
            "pillow": importlib.metadata.version("Pillow"),
        }
    except Exception as exc:
        raise RuntimeCompatibilityError(
            f"runtime_dependency_version_probe_failed:{type(exc).__name__}"
        ) from exc

    reviewed_globals: list[object] = [
        HistoryBuffer,
        (_reconstruct, "numpy.core.multiarray._reconstruct"),
        (_reconstruct, "numpy._core.multiarray._reconstruct"),
        np.ndarray,
        np.dtype,
        type(np.dtype(np.float64)),
        type(np.dtype(np.int64)),
        (scalar, "numpy.core.multiarray.scalar"),
        (scalar, "numpy._core.multiarray.scalar"),
    ]

    def checkpoint_scope() -> ContextManager[None]:
        return torch.serialization.safe_globals(reviewed_globals)

    cuda_oom_error_type = getattr(
        torch.cuda,
        "OutOfMemoryError",
        MemoryError,
    )

    return _MMDetectionBindings(
        config_fromfile=lambda path: Config.fromfile(path),
        init_detector=init_detector,
        inference_detector=inference_detector,
        checkpoint_scope=checkpoint_scope,
        versions=MappingProxyType(versions),
        cuda_oom_error_type=cuda_oom_error_type,
        cuda_is_available=torch.cuda.is_available,
        cuda_device_count=torch.cuda.device_count,
        cuda_empty_cache=torch.cuda.empty_cache,
    )


def _rgb_to_bgr(image_rgb: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """Convert one MAVI RGB frame to a private contiguous BGR backend buffer."""
    if (
        not isinstance(image_rgb, np.ndarray)
        or image_rgb.dtype != np.uint8
        or image_rgb.ndim != 3
        or image_rgb.shape[2] != 3
        or image_rgb.shape[0] <= 0
        or image_rgb.shape[1] <= 0
    ):
        raise ValueError("runtime_input_image_invalid")
    return np.ascontiguousarray(image_rgb[..., ::-1])


def _derive_release_root(path: Path, logical_relative_path: str) -> Path:
    try:
        validate_logical_relative_path(logical_relative_path)
    except ValueError as exc:
        raise RuntimeCompatibilityError("release_artifact_path_invalid") from exc

    parts = PurePosixPath(logical_relative_path).parts
    absolute = Path(os.path.abspath(os.fspath(path)))
    root = absolute
    for _ in parts:
        root = root.parent
    return root


def _verified_local_artifact(
    *,
    selected_path: Path,
    release_root: Path,
    artifact: ArtifactRef,
    hash_error: str,
) -> Path:
    try:
        resolved = resolve_release_artifact(release_root, artifact)
        selected_identity = selected_path.resolve(strict=True)
    except (OSError, ReleaseMetadataError) as exc:
        raise RuntimeCompatibilityError("release_artifact_invalid") from exc

    if selected_identity != resolved:
        raise RuntimeCompatibilityError("release_artifact_selection_mismatch")
    try:
        digest = sha256_release_file(resolved)
    except ReleaseMetadataError as exc:
        raise RuntimeCompatibilityError("release_artifact_unreadable") from exc
    if digest != artifact.sha256:
        raise RuntimeCompatibilityError(hash_error)
    return resolved


def _assignment_targets(node: ast.Assign | ast.AnnAssign) -> tuple[str, ...]:
    """Collect every name stored by an assignment, including destructuring."""
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    names: list[str] = []
    for target in targets:
        for child in ast.walk(target):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                names.append(child.id)
    return tuple(names)


def _is_none_literal(value: ast.expr | None) -> bool:
    return isinstance(value, ast.Constant) and value.value is None


def _validate_resolved_config(path: Path) -> None:
    try:
        payload = validate_release_text_file(path)
        text = payload.decode("utf-8")
        if "{{" in text:
            raise RuntimeCompatibilityError(
                "resolved_config_template_reference_forbidden"
            )
        if "${" in text:
            raise RuntimeCompatibilityError(
                "resolved_config_environment_reference_forbidden"
            )
        tree = ast.parse(text, filename=path.name)
    except RuntimeCompatibilityError:
        raise
    except (ReleaseMetadataError, UnicodeDecodeError, SyntaxError) as exc:
        raise RuntimeCompatibilityError("resolved_config_invalid") from exc

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise RuntimeCompatibilityError("resolved_config_import_forbidden")
        if isinstance(node, ast.Name) and node.id == "_base_":
            raise RuntimeCompatibilityError("resolved_config_base_unresolved")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id != "dict":
                raise RuntimeCompatibilityError("resolved_config_dynamic_call_forbidden")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            # A production-resolved config must not delegate any resource lookup
            # outside the immutable hashed release. Reject URI/model-hub schemes,
            # authority/UNC references, and absolute POSIX/Windows paths. Relative
            # strings remain legal because resolved MMDetection configs contain
            # ordinary class/type names and other non-resource text constants.
            candidate = node.value.strip()
            parsed_reference = urlsplit(candidate)
            posix_path = PurePosixPath(candidate)
            windows_path = PureWindowsPath(candidate)
            if (
                parsed_reference.scheme
                or parsed_reference.netloc
                or posix_path.is_absolute()
                or bool(windows_path.anchor)
                or candidate.startswith(("~/", "~\\"))
                or ".." in posix_path.parts
                or ".." in windows_path.parts
            ):
                raise RuntimeCompatibilityError(
                    "resolved_config_external_resource_forbidden"
                )
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            names = _assignment_targets(node)
            value = node.value
            if "_base_" in names:
                raise RuntimeCompatibilityError("resolved_config_base_unresolved")
            if "custom_imports" in names and not _is_none_literal(value):
                raise RuntimeCompatibilityError(
                    "resolved_config_custom_imports_forbidden"
                )
            if any(name in {"load_from", "resume_from"} for name in names):
                if not _is_none_literal(value):
                    raise RuntimeCompatibilityError(
                        "resolved_config_external_checkpoint_forbidden"
                    )


_FORBIDDEN_RESOURCE_KEYS = frozenset(
    {
        "load_from",
        "pretrained",
        "resume_from",
    }
)


def _plain_config_view(config: Any) -> Mapping[str, Any]:
    """Return an inspectable snapshot of an MMEngine Config-like object."""
    if isinstance(config, Mapping):
        return config

    to_dict = getattr(config, "to_dict", None)
    if not callable(to_dict):
        raise RuntimeCompatibilityError("resolved_config_wrapper_invalid")

    try:
        snapshot = to_dict()
    except Exception as exc:
        raise RuntimeCompatibilityError("resolved_config_wrapper_invalid") from exc

    if not isinstance(snapshot, Mapping):
        raise RuntimeCompatibilityError("resolved_config_wrapper_invalid")
    return snapshot


def _validate_init_cfg(value: Any) -> None:
    if isinstance(value, Mapping):
        init_type = value.get("type")
        if isinstance(init_type, str) and init_type.casefold() == "pretrained":
            raise RuntimeCompatibilityError(
                "resolved_config_pretrained_init_forbidden"
            )
        _validate_loaded_config_resources(value)
        return

    if isinstance(value, (list, tuple)):
        for item in value:
            if not isinstance(item, Mapping):
                raise RuntimeCompatibilityError("resolved_config_init_cfg_invalid")
            _validate_init_cfg(item)
        return

    raise RuntimeCompatibilityError("resolved_config_init_cfg_invalid")


def _validate_loaded_config_resources(value: Any) -> None:
    """Reject model-construction directives that can load unverified bytes."""
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            if key in _FORBIDDEN_RESOURCE_KEYS and item is not None:
                raise RuntimeCompatibilityError(
                    f"resolved_config_external_resource_directive:{key}"
                )

            if key == "custom_imports" and item:
                raise RuntimeCompatibilityError(
                    "resolved_config_custom_imports_forbidden"
                )

            if key == "init_cfg" and item is not None:
                _validate_init_cfg(item)
                continue

            _validate_loaded_config_resources(item)
        return

    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_loaded_config_resources(item)


def _mapping_child(parent: Any, key: str) -> MutableMapping[str, Any]:
    try:
        child = parent[key]
    except (KeyError, TypeError) as exc:
        raise RuntimeCompatibilityError(
            f"resolved_config_missing:{key}"
        ) from exc
    if not isinstance(child, MutableMapping):
        raise RuntimeCompatibilityError(f"resolved_config_invalid:{key}")
    return child


def _apply_profile_inference_floor(config: Any, floor: float) -> None:
    if not 0.0 <= floor <= 1.0:
        raise RuntimeCompatibilityError("detector_inference_floor_invalid")
    model_cfg = _mapping_child(config, "model")
    test_cfg = _mapping_child(model_cfg, "test_cfg")
    test_cfg["score_thr"] = floor


def _actual_model_device(model: Any) -> str:
    try:
        parameters = model.parameters()
        first = next(iter(parameters))
        device = str(first.device)
    except (AttributeError, StopIteration, TypeError) as exc:
        raise RuntimeCompatibilityError("runtime_model_device_unavailable") from exc

    if _DEVICE_PATTERN.fullmatch(device) is None:
        raise RuntimeCompatibilityError("runtime_model_device_invalid")
    return device


def _to_numpy(value: Any, *, code: str) -> np.ndarray:
    if value is None:
        raise InferenceContractError(code)

    # Do not normalize backend exceptions here. CUDA execution is asynchronous,
    # so a poisoned-context error may first surface during detach()/cpu()/numpy()
    # rather than inside inference_detector(). The caller owns one common backend
    # classifier for inference and tensor materialization.
    for method_name in ("detach", "cpu"):
        method = getattr(value, method_name, None)
        if callable(method):
            value = method()
    numpy_method = getattr(value, "numpy", None)
    if callable(numpy_method):
        value = numpy_method()
    return np.asarray(value)


class MMDetectionRuntime:
    """Qualified local MMDetection runtime with no framework objects at its boundary."""

    def __init__(
        self,
        release: VerifiedReleaseSelection,
        *,
        device: str,
        activity: InferenceActivity,
    ) -> None:
        if not isinstance(activity, InferenceActivity):
            raise TypeError("inference_activity_invalid")
        if release.manifest.backend != "mmdetection":
            raise RuntimeCompatibilityError("runtime_backend_invalid")

        device_match = _DEVICE_PATTERN.fullmatch(device)
        if device_match is None:
            raise RuntimeCompatibilityError("runtime_device_invalid")

        checkpoint_root = _derive_release_root(
            release.checkpoint_path,
            release.manifest.checkpoint.relative_path,
        )
        config_root = _derive_release_root(
            release.resolved_config_path,
            release.manifest.resolved_config.relative_path,
        )
        if checkpoint_root != config_root:
            raise RuntimeCompatibilityError("release_artifact_root_mismatch")

        checkpoint_path = _verified_local_artifact(
            selected_path=release.checkpoint_path,
            release_root=checkpoint_root,
            artifact=release.manifest.checkpoint,
            hash_error="checkpoint_hash_mismatch",
        )
        config_path = _verified_local_artifact(
            selected_path=release.resolved_config_path,
            release_root=config_root,
            artifact=release.manifest.resolved_config,
            hash_error="resolved_config_hash_mismatch",
        )
        _validate_resolved_config(config_path)

        bindings = _load_backend_bindings()
        self._validate_runtime_binding(release, bindings.versions, device=device)

        if device_match.group(1) is not None:
            index = int(device_match.group(1))
            try:
                available = bindings.cuda_is_available()
                count = bindings.cuda_device_count()
            except Exception as exc:
                raise RuntimeCompatibilityError("cuda_probe_failed") from exc
            if not available:
                raise RuntimeCompatibilityError("cuda_unavailable")
            if index >= count:
                raise RuntimeCompatibilityError("cuda_device_index_invalid")

        try:
            config = bindings.config_fromfile(str(config_path))
            _validate_loaded_config_resources(_plain_config_view(config))
            _apply_profile_inference_floor(
                config,
                release.profile.detector_inference_floor,
            )
            with bindings.checkpoint_scope():
                model = bindings.init_detector(
                    config,
                    str(checkpoint_path),
                    device=device,
                )
        except RuntimeCompatibilityError:
            raise
        except Exception as exc:
            raise RuntimeCompatibilityError(
                f"mmdetection_model_construction_failed:{type(exc).__name__}"
            ) from exc

        vocabulary = self._runtime_vocabulary(model)
        if vocabulary != release.manifest.class_vocabulary:
            raise RuntimeCompatibilityError("runtime_vocabulary_mismatch")

        actual_device = _actual_model_device(model)
        if actual_device != device:
            raise RuntimeCompatibilityError("runtime_device_mismatch")

        self._release = release
        self._activity = activity
        self._bindings = bindings
        self._model = model
        self._device = actual_device
        self._vocabulary = vocabulary
        self._closed = False
        self._metadata = RuntimeMetadata(
            backend=release.manifest.backend,
            model_id=release.manifest.model_id,
            device=actual_device,
            versions=bindings.versions,
            ordered_class_vocabulary=vocabulary,
        )

    @property
    def metadata(self) -> RuntimeMetadata:
        return self._metadata

    def warmup(self) -> None:
        image_rgb = np.zeros((64, 96, 3), dtype=np.uint8)
        image_rgb[..., 0] = 17
        image_rgb[..., 1] = 83
        image_rgb[..., 2] = 191
        self.infer(image_rgb)

    def infer(self, image_rgb: NDArray[np.uint8]) -> Sequence[RawDetection]:
        if self._closed:
            raise GpuRuntimeError("mmdetection_runtime_closed")

        try:
            image_bgr = _rgb_to_bgr(image_rgb)
        except ValueError as exc:
            raise InferenceContractError(str(exc)) from exc

        self._activity.mark_started()
        try:
            try:
                prediction = self._bindings.inference_detector(
                    self._model,
                    image_bgr,
                )
                return self._convert_prediction(prediction)
            except ProcessingDependencyError:
                raise
            except Exception as exc:
                self._raise_backend_error(exc)
        finally:
            self._activity.mark_completed()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._model = None
        if self._device.startswith("cuda:"):
            try:
                self._bindings.cuda_empty_cache()
            except Exception:
                pass

    @staticmethod
    def _validate_runtime_binding(
        release: VerifiedReleaseSelection,
        actual_versions: Mapping[str, str],
        *,
        device: str,
    ) -> None:
        expected = dict(release.runtime_semantic_graph)
        if not expected:
            raise RuntimeCompatibilityError("runtime_semantic_graph_missing")
        if set(actual_versions) != set(expected):
            missing = sorted(set(expected) - set(actual_versions))
            extra = sorted(set(actual_versions) - set(expected))
            detail = ",".join(
                [
                    *(f"missing:{name}" for name in missing),
                    *(f"extra:{name}" for name in extra),
                ]
            )
            raise RuntimeCompatibilityError(
                "runtime_semantic_graph_shape_mismatch"
                + (f":{detail}" if detail else "")
            )

        for name, expected_version in expected.items():
            actual_version = actual_versions[name]
            comparable = (
                _semantic_version(actual_version)
                if name in {"torch", "torchvision"}
                else actual_version
            )
            if comparable != expected_version:
                raise RuntimeCompatibilityError(
                    f"runtime_dependency_version_mismatch:{name}"
                )

        variant_name = _runtime_variant_name(device=device)
        variant = release.runtime_platform_variants.get(variant_name)
        if variant is None:
            if release.verification_status == "verified":
                raise RuntimeCompatibilityError(
                    "runtime_platform_variant_missing"
                )
            return

        if variant.status.startswith("qualified-"):
            expected_binary_versions = variant.binary_versions
            if expected_binary_versions is None:
                raise RuntimeCompatibilityError(
                    "runtime_binary_identity_missing"
                )
            for name, expected_version in expected_binary_versions.items():
                actual_version = actual_versions.get(name)
                if actual_version != expected_version:
                    raise RuntimeCompatibilityError(
                        f"runtime_binary_version_mismatch:{name}"
                    )
        elif release.verification_status == "verified":
            raise RuntimeCompatibilityError("runtime_platform_variant_unqualified")

    @staticmethod
    def _runtime_vocabulary(model: Any) -> tuple[str, ...]:
        metadata = getattr(model, "dataset_meta", None)
        if not isinstance(metadata, Mapping):
            raise RuntimeCompatibilityError("runtime_vocabulary_missing")
        classes = metadata.get("classes")
        if not isinstance(classes, (list, tuple)) or not classes:
            raise RuntimeCompatibilityError("runtime_vocabulary_invalid")
        vocabulary = tuple(classes)
        if any(
            not isinstance(item, str) or not item or item != item.strip()
            for item in vocabulary
        ):
            raise RuntimeCompatibilityError("runtime_vocabulary_invalid")
        if len(set(vocabulary)) != len(vocabulary):
            raise RuntimeCompatibilityError("runtime_vocabulary_invalid")
        return vocabulary

    def _convert_prediction(self, prediction: Any) -> tuple[RawDetection, ...]:
        if prediction is None or isinstance(prediction, (list, tuple)):
            raise InferenceContractError("mmdetection_prediction_invalid")

        instances = getattr(prediction, "pred_instances", None)
        if instances is None:
            raise InferenceContractError("mmdetection_instances_missing")

        boxes = _to_numpy(
            getattr(instances, "bboxes", None),
            code="mmdetection_boxes_invalid",
        )
        scores = _to_numpy(
            getattr(instances, "scores", None),
            code="mmdetection_scores_invalid",
        )
        labels = _to_numpy(
            getattr(instances, "labels", None),
            code="mmdetection_labels_invalid",
        )

        if boxes.ndim != 2 or boxes.shape[1] != 4:
            raise InferenceContractError("mmdetection_boxes_shape_invalid")
        if scores.ndim != 1 or labels.ndim != 1:
            raise InferenceContractError("mmdetection_vector_shape_invalid")
        if boxes.shape[0] != scores.shape[0] or scores.shape[0] != labels.shape[0]:
            raise InferenceContractError("mmdetection_prediction_length_mismatch")
        if not np.issubdtype(boxes.dtype, np.number):
            raise InferenceContractError("mmdetection_boxes_type_invalid")
        if not np.issubdtype(scores.dtype, np.number):
            raise InferenceContractError("mmdetection_scores_type_invalid")
        if not np.issubdtype(labels.dtype, np.integer):
            raise InferenceContractError("mmdetection_labels_type_invalid")
        if not np.isfinite(boxes).all() or not np.isfinite(scores).all():
            raise InferenceContractError("mmdetection_prediction_non_finite")
        if scores.size and ((scores < 0).any() or (scores > 1).any()):
            raise InferenceContractError("mmdetection_score_range_invalid")
        if labels.size and (
            (labels < 0).any() or (labels >= len(self._vocabulary)).any()
        ):
            raise InferenceContractError("mmdetection_label_range_invalid")

        floor = self._release.profile.detector_inference_floor
        detections: list[RawDetection] = []
        for box, score, label in zip(boxes, scores, labels, strict=True):
            confidence = float(score)
            if confidence < floor:
                continue
            try:
                detections.append(
                    RawDetection(
                        source_class=self._vocabulary[int(label)],
                        confidence=confidence,
                        bounding_box=PixelBoxXYXY(
                            float(box[0]),
                            float(box[1]),
                            float(box[2]),
                            float(box[3]),
                        ),
                    )
                )
            except (TypeError, ValueError, OverflowError) as exc:
                raise InferenceContractError(
                    "mmdetection_raw_detection_invalid"
                ) from exc

        return tuple(detections)

    def _raise_backend_error(self, exc: Exception) -> None:
        if isinstance(exc, self._bindings.cuda_oom_error_type):
            raise GpuOutOfMemoryError("mmdetection_cuda_out_of_memory") from exc

        message = str(exc).casefold()
        if "cuda" in message and "out of memory" in message:
            raise GpuOutOfMemoryError("mmdetection_cuda_out_of_memory") from exc
        if any(marker in message for marker in _FATAL_CUDA_MARKERS):
            raise GpuRuntimeError(
                f"mmdetection_cuda_runtime_failed:{type(exc).__name__}"
            ) from exc

        raise InferenceContractError(
            f"mmdetection_inference_failed:{type(exc).__name__}"
        ) from exc
