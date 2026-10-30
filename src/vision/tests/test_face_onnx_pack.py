"""The ONNX face adapter against a real face pack directory (PoC S6; ADR-022 §2).

The pack bytes are not in Git: these tests run only when ``MAVI_FACES_PACK_DIR`` names a built pack directory
(``faces-yunet-adaface-ir50-dev-v1`` or ``faces-yunet-sface-dev-v1``, from ``tools/vision/build_face_packs.py``) and
``onnxruntime`` is importable.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from mavi_vision.faces.identity import DetectorSettings

PACK = os.environ.get("MAVI_FACES_PACK_DIR")
pytestmark = pytest.mark.skipif(not PACK, reason="MAVI_FACES_PACK_DIR is not set (the face packs are not in Git)")


def _model():
    pytest.importorskip("onnxruntime")
    from mavi_vision.faces.onnx_model import load_onnx_face_model

    root = Path(PACK)
    adaface = "adaface" in root.name
    settings = DetectorSettings.model_validate_json('{"scoreThreshold":0.9,"nmsThreshold":0.3,"topK":5000}')
    return load_onnx_face_model({"onnx-face-detector": root / "detector.onnx", "onnx-face-embedder": root / "embedder.onnx"},
                                dimension=512 if adaface else 128, preprocessing="adaface-ir50-v1" if adaface else "sface-v1",
                                settings=settings, device_policy="cpu")


def test_the_pack_loads_detects_nothing_in_noise_and_embeds_a_batch() -> None:
    model = _model()
    noise = np.random.default_rng(0).integers(0, 255, (96, 64, 3), dtype=np.uint8)
    assert model.detect(noise) == []
    faces = [np.full((112, 112, 3), value, np.uint8) for value in (40, 200)]
    rows = model.embed(faces)
    assert rows.shape == (2, model.dimension) and np.all(np.isfinite(rows))
