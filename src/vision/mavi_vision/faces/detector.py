"""YuNet face detection over one evidence crop (ADR-022 §2; numpy only, the session is injected).

The YuNet ONNX graph (OpenCV Zoo ``face_detection_yunet_2026may``, MIT) takes a BGR float32 image
``[1, 3, H, W]`` with ``H`` and ``W`` multiples of 32 and no normalisation, and returns per stride
(8, 16, 32) the class and objectness scores, box offsets and five landmark offsets per anchor. This
module pads the crop (never resizes it), decodes the anchors exactly as OpenCV's ``FaceDetectorYN``
does, and applies greedy NMS. Coordinates are in the crop's own pixels.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence

import numpy as np

STRIDES = (8, 16, 32)
PAD_MULTIPLE = 32


class OnnxSession(Protocol):
    def run(self, output_names: Sequence[str] | None, input_feed: dict[str, Any]) -> list[Any]: ...


@dataclass(frozen=True, slots=True)
class FaceDetection:
    """One face in crop pixels: box ``(x, y, w, h)``, five landmarks (right eye, left eye, nose, right and
    left mouth corner, as the subject faces the camera) and the score ``sqrt(cls * obj)``."""

    x: float
    y: float
    width: float
    height: float
    score: float
    landmarks: tuple[tuple[float, float], ...]

    @property
    def min_side(self) -> float:
        return min(self.width, self.height)


def padded_input(rgb: np.ndarray) -> tuple[np.ndarray, int, int]:
    """The ``[1, 3, H', W']`` float32 BGR tensor of an ``[H, W, 3]`` uint8 RGB crop, zero-padded bottom-right
    to multiples of 32, and the padded size."""
    if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.dtype != np.uint8:
        raise ValueError("face_crop_not_rgb8")
    height, width = rgb.shape[:2]
    pad_h = ((height - 1) // PAD_MULTIPLE + 1) * PAD_MULTIPLE
    pad_w = ((width - 1) // PAD_MULTIPLE + 1) * PAD_MULTIPLE
    canvas = np.zeros((pad_h, pad_w, 3), dtype=np.float32)
    canvas[:height, :width, :] = rgb[:, :, ::-1]
    return np.ascontiguousarray(canvas.transpose(2, 0, 1)[None]), pad_h, pad_w


def decode(outputs: dict[str, np.ndarray], pad_h: int, pad_w: int, score_threshold: float) -> list[FaceDetection]:
    """Every anchor whose score reaches ``score_threshold``, before NMS."""
    found: list[FaceDetection] = []
    for stride in STRIDES:
        rows, cols = pad_h // stride, pad_w // stride
        cls = np.clip(outputs[f"cls_{stride}"].reshape(-1), 0.0, 1.0)
        obj = np.clip(outputs[f"obj_{stride}"].reshape(-1), 0.0, 1.0)
        bbox = outputs[f"bbox_{stride}"].reshape(-1, 4)
        kps = outputs[f"kps_{stride}"].reshape(-1, 10)
        if cls.shape[0] != rows * cols:
            raise ValueError("face_detector_output_shape")
        scores = np.sqrt(cls * obj)
        for index in np.nonzero(scores >= score_threshold)[0]:
            row, col = divmod(int(index), cols)
            cx = (col + float(bbox[index, 0])) * stride
            cy = (row + float(bbox[index, 1])) * stride
            w = float(np.exp(bbox[index, 2])) * stride
            h = float(np.exp(bbox[index, 3])) * stride
            marks = tuple(
                ((float(kps[index, 2 * n]) + col) * stride, (float(kps[index, 2 * n + 1]) + row) * stride)
                for n in range(5)
            )
            found.append(FaceDetection(cx - w / 2, cy - h / 2, w, h, float(scores[index]), marks))
    return found


def _iou(a: FaceDetection, b: FaceDetection) -> float:
    x1, y1 = max(a.x, b.x), max(a.y, b.y)
    x2, y2 = min(a.x + a.width, b.x + b.width), min(a.y + a.height, b.y + b.height)
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = a.width * a.height + b.width * b.height - inter
    return inter / union if union > 0 else 0.0


def non_maximum_suppression(faces: list[FaceDetection], iou_threshold: float, top_k: int) -> list[FaceDetection]:
    """Greedy NMS, highest score first; ties keep decode order, so the result is deterministic."""
    ordered = sorted(faces, key=lambda face: -face.score)[:top_k]
    kept: list[FaceDetection] = []
    for face in ordered:
        if all(_iou(face, other) <= iou_threshold for other in kept):
            kept.append(face)
    return kept


def clip_to_crop(face: FaceDetection, height: int, width: int) -> FaceDetection | None:
    """The detection with its box clipped to the crop (padding is not image); ``None`` when nothing is left."""
    x1, y1 = max(0.0, face.x), max(0.0, face.y)
    x2, y2 = min(float(width), face.x + face.width), min(float(height), face.y + face.height)
    if x2 <= x1 or y2 <= y1:
        return None
    return FaceDetection(x1, y1, x2 - x1, y2 - y1, face.score, face.landmarks)


def detect_faces(
    session: OnnxSession,
    rgb: np.ndarray,
    *,
    score_threshold: float,
    nms_threshold: float,
    top_k: int,
) -> list[FaceDetection]:
    """YuNet over one RGB crop at its native resolution."""
    tensor, pad_h, pad_w = padded_input(rgb)
    names = [f"{kind}_{stride}" for kind in ("cls", "obj", "bbox", "kps") for stride in STRIDES]
    values = session.run(names, {"input": tensor})
    outputs = {name: np.asarray(value, dtype=np.float32) for name, value in zip(names, values, strict=True)}
    height, width = rgb.shape[:2]
    kept = non_maximum_suppression(decode(outputs, pad_h, pad_w, score_threshold), nms_threshold, top_k)
    return [clipped for face in kept if (clipped := clip_to_crop(face, height, width)) is not None]
