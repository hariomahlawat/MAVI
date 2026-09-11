#!/usr/bin/env python3
"""Probe a fully local MAVI Phase-1 vision runtime with a real RTMDet inference.

This utility is deliberately strict: it accepts only explicit local config/checkpoint
paths, validates them before importing heavyweight ML packages, and never resolves a
model-zoo alias or remote URL. It is qualification tooling, not production worker code.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import traceback
from contextlib import contextmanager, redirect_stdout
from pathlib import Path, PureWindowsPath
from typing import Any, Iterator
from urllib.parse import urlsplit


class ProbeConfigurationError(RuntimeError):
    pass


def parse_local_path(value: str) -> Path:
    """Return a filesystem path while rejecting URL/model-hub style inputs."""
    # urllib treats ``C:\\...`` / ``C:/...`` as URL scheme ``c``. Recognise a
    # genuinely absolute Windows filesystem path before applying URL rejection so
    # the same strict local-only contract works on both qualification platforms.
    if PureWindowsPath(value).is_absolute():
        return Path(value)

    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        raise ProbeConfigurationError("artifact_url_forbidden")
    return Path(value)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_local_artifacts(
    config: Path,
    checkpoint: Path,
    *,
    expected_checkpoint_sha256: str,
) -> None:
    if not config.is_file():
        raise ProbeConfigurationError("config_missing")
    if not checkpoint.is_file():
        raise ProbeConfigurationError("checkpoint_missing")
    if len(expected_checkpoint_sha256) != 64 or any(
        character not in "0123456789abcdef"
        for character in expected_checkpoint_sha256.lower()
    ):
        raise ProbeConfigurationError("checkpoint_digest_invalid")
    if sha256_file(checkpoint) != expected_checkpoint_sha256.lower():
        raise ProbeConfigurationError("checkpoint_digest_mismatch")


def reviewed_checkpoint_globals() -> list[object]:
    """Return only the types reviewed in the official RTMDet-M checkpoint."""
    import numpy as np
    from mmengine.logging.history_buffer import HistoryBuffer
    from numpy._core.multiarray import _reconstruct, scalar

    # The official RTMDet-M checkpoint was produced with the historical
    # numpy.core module identity, while NumPy 2.x serializes the same reviewed
    # callables under numpy._core. PyTorch 2.6 matches the serialized global
    # name exactly, so both explicit aliases are required. This remains a finite
    # reviewed allowlist; no discovered-name or process-global permissions are used.
    return [
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


@contextmanager
def restricted_checkpoint_loading_scope() -> Iterator[None]:
    """Temporarily permit the reviewed metadata types under restricted loading."""
    import torch

    with torch.serialization.safe_globals(reviewed_checkpoint_globals()):
        yield


def _distribution_version(name: str) -> str:
    return importlib.metadata.version(name)


def python_runtime_identity() -> dict[str, Any]:
    """Return the exact interpreter identity used for qualification."""
    return {
        "python": platform.python_version(),
        "pythonImplementation": platform.python_implementation(),
        "pythonBuild": list(platform.python_build()),
        "pythonCompiler": platform.python_compiler(),
    }


def _version_record(*, device: str) -> dict[str, Any]:
    # Heavy imports are intentionally delayed until after local artifact preflight.
    import av
    import cv2
    import mmcv
    import mmdet
    import mmengine
    import numpy as np
    import scipy
    import supervision
    import torch
    import torchvision

    record: dict[str, Any] = {
        **python_runtime_identity(),
        "platform": platform.platform(),
        "torch": torch.__version__,
        "torchvision": torchvision.__version__,
        "mmcv": mmcv.__version__,
        "mmengine": mmengine.__version__,
        "mmdet": mmdet.__version__,
        "trackers": _distribution_version("trackers"),
        "supervision": supervision.__version__,
        "scipy": scipy.__version__,
        "numpy": np.__version__,
        "opencv": cv2.__version__,
        "opencvPython": _distribution_version("opencv-python"),
        "pillow": _distribution_version("Pillow"),
        "av": av.__version__,
        "device": device,
        "os": platform.system(),
        "machine": platform.machine(),
        "commitSha": os.environ.get("GITHUB_SHA"),
        "pullRequestHeadSha": os.environ.get("MAVI_PR_HEAD_SHA") or None,
        "workflowRunId": os.environ.get("GITHUB_RUN_ID"),
        "workflowJob": os.environ.get("GITHUB_JOB"),
    }
    if device.startswith("cuda"):
        record.update(
            {
                "torchCuda": torch.version.cuda,
                "cudaAvailable": bool(torch.cuda.is_available()),
                "gpuName": (
                    torch.cuda.get_device_name(0)
                    if torch.cuda.is_available()
                    else None
                ),
            }
        )
    return record


def validate_prediction_arrays(
    boxes: Any,
    scores: Any,
    labels: Any,
    *,
    class_count: int,
) -> None:
    import numpy as np

    if boxes.ndim != 2 or boxes.shape[1] != 4:
        raise RuntimeError("prediction_boxes_shape_invalid")
    if scores.ndim != 1 or labels.ndim != 1:
        raise RuntimeError("prediction_vector_shape_invalid")
    if boxes.shape[0] != scores.shape[0] or scores.shape[0] != labels.shape[0]:
        raise RuntimeError("prediction_length_mismatch")
    if not np.isfinite(boxes).all() or not np.isfinite(scores).all():
        raise RuntimeError("prediction_numeric_value_invalid")
    if not np.issubdtype(labels.dtype, np.integer):
        raise RuntimeError("prediction_labels_type_invalid")
    if class_count < 1:
        raise RuntimeError("prediction_vocabulary_invalid")
    if labels.size and ((labels < 0).any() or (labels >= class_count).any()):
        raise RuntimeError("prediction_label_range_invalid")


def run_probe(
    config: Path,
    checkpoint: Path,
    *,
    expected_checkpoint_sha256: str,
    device: str,
) -> dict[str, Any]:
    validate_local_artifacts(
        config,
        checkpoint,
        expected_checkpoint_sha256=expected_checkpoint_sha256,
    )

    import numpy as np
    from mmdet.apis import inference_detector, init_detector

    if device == "cuda":
        device = "cuda:0"
    elif device != "cpu":
        raise ProbeConfigurationError("device_invalid")

    with restricted_checkpoint_loading_scope():
        model = init_detector(str(config), str(checkpoint), device=device)

    # MAVI frames are RGB. MMDetection ndarray inference expects backend BGR input,
    # so qualification exercises the exact production boundary rather than a gray
    # image that could hide a channel-order regression.
    image_rgb = np.zeros((64, 96, 3), dtype=np.uint8)
    image_rgb[..., 0] = 17
    image_rgb[..., 1] = 83
    image_rgb[..., 2] = 191
    image_bgr = np.ascontiguousarray(image_rgb[..., ::-1])
    prediction = inference_detector(model, image_bgr)
    if prediction is None:
        raise RuntimeError("inference_result_missing")

    instances = prediction.pred_instances
    boxes = instances.bboxes.detach().cpu().numpy()
    scores = instances.scores.detach().cpu().numpy()
    labels = instances.labels.detach().cpu().numpy()
    classes = model.dataset_meta.get("classes")
    if not isinstance(classes, (list, tuple)) or not classes:
        raise RuntimeError("prediction_vocabulary_invalid")
    validate_prediction_arrays(boxes, scores, labels, class_count=len(classes))

    result = _version_record(device=device)
    result["predictionType"] = type(prediction).__name__
    result["predictionCount"] = int(scores.shape[0])
    result["checkpoint"] = {
        "path": str(checkpoint.resolve()),
        "sha256": expected_checkpoint_sha256.lower(),
    }
    result["config"] = {
        "path": str(config.resolve()),
        "sha256": sha256_file(config),
    }
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=parse_local_path)
    parser.add_argument("--checkpoint", required=True, type=parse_local_path)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--device", required=True, choices=("cpu", "cuda"))
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        validate_local_artifacts(
            args.config,
            args.checkpoint,
            expected_checkpoint_sha256=args.checkpoint_sha256,
        )
        # Third-party loaders write progress to stdout. Keep stdout reserved for
        # one machine-readable result and route diagnostics to the error log.
        with redirect_stdout(sys.stderr):
            result = run_probe(
                args.config,
                args.checkpoint,
                expected_checkpoint_sha256=args.checkpoint_sha256,
                device=args.device,
            )
    except ProbeConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        print(json.dumps({"error": str(exc), "status": "failed"}, sort_keys=True))
        return 2
    except Exception as exc:
        print(f"runtime_probe_failed:{type(exc).__name__}:{exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "errorType": type(exc).__name__,
                    "status": "failed",
                },
                sort_keys=True,
            )
        )
        return 1

    result["status"] = "passed"
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
