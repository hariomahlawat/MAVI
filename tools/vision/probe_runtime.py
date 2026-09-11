#!/usr/bin/env python3
"""Probe a fully local MAVI Phase-1 vision runtime with a real RTMDet inference.

This utility is deliberately strict: it accepts only explicit local config/checkpoint
paths, validates them before importing heavyweight ML packages, and never resolves a
model-zoo alias or remote URL. It is qualification tooling, not production worker code.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class ProbeConfigurationError(RuntimeError):
    pass


def parse_local_path(value: str) -> Path:
    """Return a filesystem path while rejecting URL/model-hub style inputs."""
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        raise ProbeConfigurationError("artifact_url_forbidden")
    return Path(value)


def validate_local_artifacts(config: Path, checkpoint: Path) -> None:
    if not config.is_file():
        raise ProbeConfigurationError("config_missing")
    if not checkpoint.is_file():
        raise ProbeConfigurationError("checkpoint_missing")


def _distribution_version(name: str) -> str:
    return importlib.metadata.version(name)


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
        "python": platform.python_version(),
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
        "av": av.__version__,
        "device": device,
        "os": platform.system(),
        "machine": platform.machine(),
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


def run_probe(config: Path, checkpoint: Path, *, device: str) -> dict[str, Any]:
    validate_local_artifacts(config, checkpoint)

    import numpy as np
    from mmdet.apis import inference_detector, init_detector

    if device == "cuda":
        device = "cuda:0"
    elif device != "cpu":
        raise ProbeConfigurationError("device_invalid")

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

    result = _version_record(device=device)
    result["predictionType"] = type(prediction).__name__
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=parse_local_path)
    parser.add_argument("--checkpoint", required=True, type=parse_local_path)
    parser.add_argument("--device", required=True, choices=("cpu", "cuda"))
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        validate_local_artifacts(args.config, args.checkpoint)
        result = run_probe(args.config, args.checkpoint, device=args.device)
    except ProbeConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"runtime_probe_failed:{type(exc).__name__}:{exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
