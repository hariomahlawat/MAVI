"""ONNX Runtime plumbing shared by the Development pilot plate adapters (Issue #225).

The adapters run on the CPU execution provider only, single-threaded and sequential, so a reading is a function of
the verified bytes alone. ``onnxruntime``, ``cv2`` and ``yaml`` live in the Development ``plates-onnx-v1`` runtime
family, never in the vision lock; they are imported when an adapter is built, so the plates package still imports
where they are absent (the fixture and the contract tests need none of them).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Protocol

import numpy as np
from PIL import Image

CPU_PROVIDER = "CPUExecutionProvider"


class Session(Protocol):
    """The part of ``onnxruntime.InferenceSession`` an adapter uses (a test supplies a fake)."""

    def get_inputs(self) -> list[Any]: ...
    def get_outputs(self) -> list[Any]: ...
    def run(self, output_names: list[str] | None, feeds: dict[str, np.ndarray]) -> list[np.ndarray]: ...


SessionFactory = Callable[[Path], Session]


def cpu_session(path: Path) -> Session:
    """One deterministic CPU session for the model at ``path`` (bytes already verified by the resolver)."""
    import onnxruntime  # noqa: PLC0415 - plates-onnx-v1 runtime only

    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
    options.log_severity_level = 3
    return onnxruntime.InferenceSession(str(path), sess_options=options, providers=[CPU_PROVIDER])


def read_yaml(path: Path) -> Any:
    import yaml  # noqa: PLC0415 - plates-onnx-v1 runtime only

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def resize_linear(image: np.ndarray, width: int, height: int) -> np.ndarray:
    """OpenCV ``INTER_LINEAR``: the interpolation both upstream pre-processors declare."""
    import cv2  # noqa: PLC0415 - plates-onnx-v1 runtime only

    return cv2.resize(image, (width, height), interpolation=cv2.INTER_LINEAR)


def rgb_array(image: Image.Image) -> np.ndarray:
    array = np.asarray(image.convert("RGB"), dtype=np.uint8)
    if array.ndim != 3 or array.shape[2] != 3 or array.shape[0] < 1 or array.shape[1] < 1:
        raise ValueError("plate_adapter_input_not_rgb")
    return np.ascontiguousarray(array)


__all__ = ["CPU_PROVIDER", "Session", "SessionFactory", "cpu_session", "read_yaml", "resize_linear", "rgb_array"]
