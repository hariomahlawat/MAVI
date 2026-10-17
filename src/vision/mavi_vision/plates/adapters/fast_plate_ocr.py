"""``fast-plate-ocr-onnx-v1``: the fast-plate-ocr CCT recogniser run directly on ONNX Runtime (Issue #225 pilot).

The pre- and post-processing of ``fast-plate-ocr`` 1.1.0 (MIT; ``core/process.py`` and
``inference/plate_recognizer.py``) re-implemented over the pack's own plate config, so the product runtime needs
``onnxruntime``, ``numpy``, ``opencv-python-headless`` and ``PyYAML`` and not the library and its CLI/training
dependencies. Equivalence with the library on the same crops is a recorded Development check, not assumed.

* input: the RGB plate region resized to the config's ``img_width x img_height`` with OpenCV ``INTER_LINEAR`` and
  no aspect preservation (the only configuration this adapter accepts), uint8 NHWC, batch of one;
* output ``plate``: ``max_plate_slots x len(alphabet)`` probabilities; per-slot argmax, trailing ``pad_char``
  removed (the library's ``remove_pad_char``);
* reading (PR-3 bridge rule): an empty text is **no reading** (``[]``, the plate is Unreadable); otherwise one
  ``Reading(raw_text, confidence)`` with the text verbatim and confidence the mean of the per-slot maxima over the
  emitted characters. Two-row plates are read as one string (the model has no row separator).
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import numpy as np
from PIL import Image

from mavi_vision.plates.adapters.onnx import SessionFactory, cpu_session, read_yaml, resize_linear, rgb_array
from mavi_vision.plates.inference import PlateBox, Reading, VerifiedCrop

ADAPTER_ID = "fast-plate-ocr-onnx-v1"
SLOTS = frozenset({"onnx-model", "plate-config"})
PLATE_OUTPUT = "plate"


class PlateConfig:
    def __init__(self, document: object) -> None:
        if not isinstance(document, dict):
            raise ValueError("plate_adapter_config_invalid")
        try:
            self.max_plate_slots = int(document["max_plate_slots"])
            self.alphabet = str(document["alphabet"])
            self.pad_char = str(document["pad_char"])
            self.img_height = int(document["img_height"])
            self.img_width = int(document["img_width"])
            keep_aspect_ratio = document.get("keep_aspect_ratio", False)
            interpolation = document.get("interpolation", "linear")
            colour = document.get("image_color_mode", "grayscale")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("plate_adapter_config_invalid") from exc
        if (self.max_plate_slots < 1 or len(self.alphabet) < 2 or len(set(self.alphabet)) != len(self.alphabet)
                or len(self.pad_char) != 1 or self.pad_char not in self.alphabet
                or self.img_height < 1 or self.img_width < 1):
            raise ValueError("plate_adapter_config_invalid")
        if keep_aspect_ratio is not False or interpolation != "linear" or colour != "rgb":
            raise ValueError("plate_adapter_config_unsupported")


def decode(output: np.ndarray, config: PlateConfig) -> tuple[str, float | None]:
    probabilities = np.asarray(output, dtype=np.float64).reshape(config.max_plate_slots, len(config.alphabet))
    indices = probabilities.argmax(axis=-1)
    text = "".join(config.alphabet[index] for index in indices).rstrip(config.pad_char)
    if not text:
        return "", None
    confidence = float(np.mean(probabilities.max(axis=-1)[: len(text)]))
    if not np.isfinite(confidence):
        raise ValueError("plate_recogniser_confidence_invalid")
    # Softmax maxima are probabilities; float32 rounding may overshoot 1 by an ulp, which is not a fault.
    return text, min(1.0, max(0.0, confidence))


class FastPlateOcrRecogniser:
    def __init__(self, artifacts: Mapping[str, Path], *, session_factory: SessionFactory = cpu_session) -> None:
        if set(artifacts) != SLOTS:
            raise ValueError("plate_adapter_artifacts_invalid")
        self._config = PlateConfig(read_yaml(artifacts["plate-config"]))
        self._session = session_factory(artifacts["onnx-model"])
        self._input = self._session.get_inputs()[0].name
        names = [output.name for output in self._session.get_outputs()]
        self._output = PLATE_OUTPUT if PLATE_OUTPUT in names else names[0]

    def read(self, region: Image.Image, verified: VerifiedCrop, box: PlateBox) -> list[Reading]:
        rgb = rgb_array(region)
        resized = resize_linear(rgb, self._config.img_width, self._config.img_height)
        tensor = np.ascontiguousarray(resized[None], dtype=np.uint8)
        output = self._session.run([self._output], {self._input: tensor})[0]
        text, confidence = decode(output, self._config)
        if not text or confidence is None:
            return []
        return [Reading(text, confidence)]


__all__ = ["ADAPTER_ID", "SLOTS", "FastPlateOcrRecogniser", "PlateConfig", "decode"]
