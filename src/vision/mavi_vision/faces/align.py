"""Five-landmark face alignment to the 112×112 ArcFace template (ADR-022 §3; numpy and Pillow only).

The similarity transform (rotation, uniform scale, translation, no reflection) that maps the detector's five
landmarks onto the standard template is estimated by Umeyama's least-squares method, as
``skimage.transform.SimilarityTransform`` and OpenCV ``FaceRecognizerSF.alignCrop`` do, and the crop is warped
with bilinear sampling. YuNet's landmark order (the subject's right eye first, which appears on the image's
left) matches the template's order.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
from PIL import Image

ALIGNED_SIZE = 112
ARCFACE_TEMPLATE = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float64,
)


def similarity_transform(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """The 2×3 matrix ``M`` minimising ``|M·[source, 1] - target|²`` over similarity transforms (Umeyama 1991)."""
    if source.shape != target.shape or source.shape[1] != 2 or source.shape[0] < 2:
        raise ValueError("face_alignment_points")
    src_mean, dst_mean = source.mean(axis=0), target.mean(axis=0)
    src, dst = source - src_mean, target - dst_mean
    covariance = dst.T @ src / source.shape[0]
    u, s, vt = np.linalg.svd(covariance)
    d = np.ones(2)
    if np.linalg.det(covariance) < 0:
        d[1] = -1.0
    rotation = u @ np.diag(d) @ vt
    variance = (src**2).sum() / source.shape[0]
    if variance <= 0:
        raise ValueError("face_alignment_degenerate")
    scale = float((s * d).sum() / variance)
    matrix = np.zeros((2, 3), dtype=np.float64)
    matrix[:, :2] = scale * rotation
    matrix[:, 2] = dst_mean - scale * rotation @ src_mean
    return matrix


def align_face(rgb: np.ndarray, landmarks: Sequence[tuple[float, float]]) -> np.ndarray:
    """The ``[112, 112, 3]`` uint8 RGB face aligned from an RGB crop and the detector's five landmarks."""
    points = np.asarray(landmarks, dtype=np.float64)
    if points.shape != (5, 2) or not np.isfinite(points).all():
        raise ValueError("face_alignment_points")
    forward = similarity_transform(points, ARCFACE_TEMPLATE)
    # Pillow maps each output pixel to an input position: pass the inverse of the forward transform.
    square = np.vstack([forward, [0.0, 0.0, 1.0]])
    inverse = np.linalg.inv(square)[:2]
    if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.dtype != np.uint8:
        raise ValueError("face_crop_not_rgb8")
    image = Image.fromarray(rgb)
    aligned = image.transform(
        (ALIGNED_SIZE, ALIGNED_SIZE),
        Image.Transform.AFFINE,
        tuple(float(v) for v in inverse.reshape(-1)),
        resample=Image.Resampling.BILINEAR,
        fillcolor=(0, 0, 0),
    )
    return np.asarray(aligned, dtype=np.uint8)
