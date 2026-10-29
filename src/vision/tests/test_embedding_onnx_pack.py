"""The real SigLIP 2 pack through the ``embeddings`` adapter (PoC S4; ADR-021). Development, opt-in.

Runs only when ``MAVI_EMBEDDINGS_MODEL_ROOT`` names the directory holding ``embeddings-siglip2-base-p16-224-dev-v1/``
and the interpreter has ``onnxruntime`` and ``sentencepiece`` (the ``embeddings-onnx-v1`` environment with pytest
added); it is skipped with the reason otherwise. The pack is never in Git.
"""

from __future__ import annotations

import importlib.util
import io
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from mavi_vision.embeddings.identity import resolve_embedding_pack, verify_model_pack
from mavi_vision.embeddings.model import l2_normalise_rows
from mavi_vision.embeddings.tokenizer import load_sentencepiece, sentencepiece_ids

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MODEL_ROOT = os.environ.get("MAVI_EMBEDDINGS_MODEL_ROOT")

pytestmark = [
    pytest.mark.skipif(not MODEL_ROOT, reason="MAVI_EMBEDDINGS_MODEL_ROOT is not set (the SigLIP 2 pack is not in Git)"),
    pytest.mark.skipif(importlib.util.find_spec("onnxruntime") is None or importlib.util.find_spec("sentencepiece") is None,
                       reason="onnxruntime and sentencepiece are only in the embeddings-onnx-v1 environment"),
]


@pytest.fixture(scope="module")
def model_and_artifacts():
    from mavi_vision.embeddings.onnx_model import load_onnx_model

    resolved = resolve_embedding_pack(REPOSITORY_ROOT / "models/manifests/embeddings-siglip2-base-p16-224-dev-v1.json",
                                      REPOSITORY_ROOT / "src/vision/config/embeddings/development-embeddings-siglip2-v1.json")
    artifacts = verify_model_pack(resolved.manifest, Path(MODEL_ROOT))
    return load_onnx_model(artifacts, dimension=768, device_policy="cpu"), artifacts


def _crop(tmp_path: Path) -> tuple[bytes, Path]:
    rng = np.random.default_rng(7)
    buffer = io.BytesIO()
    Image.fromarray(rng.integers(0, 255, (160, 120, 3), dtype=np.uint8)).save(buffer, "JPEG", quality=90)
    path = tmp_path / "crop.jpg"
    path.write_bytes(buffer.getvalue())
    return buffer.getvalue(), path


def test_image_vectors_equal_the_spike_preprocessing_on_the_same_session(model_and_artifacts, tmp_path: Path) -> None:
    model, artifacts = model_and_artifacts
    spec = importlib.util.spec_from_file_location("embeddings_spike", REPOSITORY_ROOT / "tools/poc/embeddings_spike.py")
    spike = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(spike)
    data, path = _crop(tmp_path)
    import onnxruntime

    session = onnxruntime.InferenceSession(str(artifacts["onnx-vision-encoder"]), providers=["CPUExecutionProvider"])
    reference = session.run(None, {"pixel_values": spike.preprocess(str(path))})[0]
    ours = model.embed_images([data])
    assert ours.shape == (1, 768)
    assert float(np.sum(l2_normalise_rows(ours, 768) * l2_normalise_rows(reference, 768))) >= 0.9999


def test_text_vectors_and_tokenizer(model_and_artifacts) -> None:
    model, artifacts = model_and_artifacts
    ids = sentencepiece_ids(load_sentencepiece(artifacts["text-tokenizer"]), "A Car")
    assert len(ids) == 64 and 1 in ids and ids[ids.index(1) + 1:] == [0] * (63 - ids.index(1))
    vectors = l2_normalise_rows(model.embed_texts(["a car", "a person"]), 768)
    assert vectors.shape == (2, 768) and float(vectors[0] @ vectors[1]) < 0.999
