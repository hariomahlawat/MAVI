from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType
from typing import Mapping, Protocol, Sequence, runtime_checkable

import numpy as np
from numpy.typing import NDArray


def _require_nonempty(value: str, *, code: str) -> str:
    if not value or value != value.strip():
        raise ValueError(code)
    return value


@dataclass(frozen=True, slots=True)
class PixelBoxXYXY:
    """Detector-native bounding box in original decoded-frame pixel coordinates."""

    x1: float
    y1: float
    x2: float
    y2: float

    def __post_init__(self) -> None:
        if not all(isfinite(value) for value in (self.x1, self.y1, self.x2, self.y2)):
            raise ValueError("raw_detection_bbox_non_finite")


@dataclass(frozen=True, slots=True)
class RawDetection:
    """Framework-neutral detector output before MAVI clipping/class normalization."""

    source_class: str
    confidence: float
    bounding_box: PixelBoxXYXY

    def __post_init__(self) -> None:
        _require_nonempty(
            self.source_class,
            code="raw_detection_source_class_invalid",
        )
        if not isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("raw_detection_confidence_invalid")


@dataclass(frozen=True, slots=True)
class RuntimeMetadata:
    """Immutable runtime identity exposed by a detector backend."""

    backend: str
    model_id: str
    device: str
    versions: Mapping[str, str]
    ordered_class_vocabulary: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_nonempty(self.backend, code="runtime_backend_invalid")
        _require_nonempty(self.model_id, code="runtime_model_id_invalid")
        _require_nonempty(self.device, code="runtime_device_invalid")

        versions = dict(self.versions)
        if not versions:
            raise ValueError("runtime_versions_required")
        for name, version in versions.items():
            _require_nonempty(name, code="runtime_version_name_invalid")
            _require_nonempty(version, code="runtime_version_value_invalid")
        object.__setattr__(self, "versions", MappingProxyType(versions))

        vocabulary = tuple(self.ordered_class_vocabulary)
        if not vocabulary:
            raise ValueError("runtime_vocabulary_required")
        if any(not item or item != item.strip() for item in vocabulary):
            raise ValueError("runtime_vocabulary_entry_invalid")
        if len(set(vocabulary)) != len(vocabulary):
            raise ValueError("runtime_vocabulary_duplicate")
        object.__setattr__(self, "ordered_class_vocabulary", vocabulary)


@runtime_checkable
class DetectorRuntime(Protocol):
    @property
    def metadata(self) -> RuntimeMetadata: ...

    def warmup(self) -> None: ...

    def infer(self, image_rgb: NDArray[np.uint8]) -> Sequence[RawDetection]: ...

    def close(self) -> None: ...
