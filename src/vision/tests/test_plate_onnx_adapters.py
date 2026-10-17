"""Synthetic-crop tests of the Issue #225 Development ONNX plate adapters and of their registry.

They need numpy, scipy and Pillow only: the ONNX sessions are fakes, and the two helpers the adapters take from the
``plates-onnx-v1`` runtime (OpenCV resize and the YAML reader) are replaced by numpy/JSON equivalents, so the pre- and
post-processing, the PR-3 box mapping, the row merge, the bound and the decoding run in CI. The real models are
exercised by ``test_plate_onnx_pilot.py`` where the local packs and runtime are present.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from mavi_vision.plates import adapters as registry
from mavi_vision.plates.adapters import AdapterRequest, AdapterUnavailable, components_for
from mavi_vision.plates.adapters import fast_plate_ocr, ppocr_db
from mavi_vision.plates.adapters.fixture import FIXTURE_ADAPTER_ID
from mavi_vision.plates.inference import PlateBox, Reading
from mavi_vision.plates.parameters import PlateParameters

PARAMETERS = PlateParameters(max_detections_per_crop=2, max_plates_per_crop=1, max_readings_per_plate=1,
                             detector_confidence_floor=0.6, ocr_confidence_floor=0.5, excluded_roles=frozenset(),
                             fixture_seed=None)
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_"


def _nearest(image: np.ndarray, width: int, height: int) -> np.ndarray:
    return np.asarray(Image.fromarray(np.ascontiguousarray(image)).resize((width, height), Image.NEAREST))


@pytest.fixture(autouse=True)
def runtime_free(monkeypatch):
    """Replace the two runtime-only helpers; JSON is a YAML subset, so the configs below are written as JSON."""
    reader = lambda path: json.loads(Path(path).read_text(encoding="utf-8"))  # noqa: E731
    for module in (ppocr_db, fast_plate_ocr):
        monkeypatch.setattr(module, "read_yaml", reader)
        monkeypatch.setattr(module, "resize_linear", _nearest)


class FakeSession:
    def __init__(self, outputs, *, output_names=("plate",)) -> None:
        self._outputs = outputs
        self.output_names = output_names
        self.feeds: list[np.ndarray] = []

    def get_inputs(self):
        return [SimpleNamespace(name="x")]

    def get_outputs(self):
        return [SimpleNamespace(name=name) for name in self.output_names]

    def run(self, names, feeds):
        tensor = feeds["x"]
        self.feeds.append(tensor)
        return [self._outputs(tensor) if callable(self._outputs) else self._outputs]


def _db_config(tmp_path: Path) -> Path:
    path = tmp_path / "inference.yml"
    path.write_text(json.dumps({"PostProcess": {"name": "DBPostProcess", "thresh": 0.3, "box_thresh": 0.6,
                                                "max_candidates": 1000, "unclip_ratio": 1.5}}), encoding="utf-8")
    return path


def _plate_config(tmp_path: Path, **overrides) -> Path:
    document = {"max_plate_slots": 10, "alphabet": ALPHABET, "pad_char": "_", "img_height": 64, "img_width": 128,
                "keep_aspect_ratio": False, "interpolation": "linear", "image_color_mode": "rgb", **overrides}
    path = tmp_path / "plate_config.yaml"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- PP-OCR DB proposer


def test_db_resize_rounds_to_32_and_never_upscales() -> None:
    assert ppocr_db.db_resize_shape(180, 240) == (192, 256)
    assert ppocr_db.db_resize_shape(1080, 1920) == (544, 960)
    assert ppocr_db.db_resize_shape(5, 5) == (32, 32)


def test_db_boxes_are_axis_aligned_unclipped_and_scaled() -> None:
    probability = np.zeros((64, 64))
    probability[10:20, 8:40] = 0.9   # a strong line
    probability[40:42, 5:7] = 0.9    # too small: dropped
    probability[50:60, 30:50] = 0.4  # above thresh, below box_thresh: dropped
    rows = ppocr_db.db_boxes(probability, 0.3, 0.6, 1.5, 2.0, 0.5, 1000)
    assert rows.shape == (1, 5)
    x1, y1, x2, y2, score = rows[0]
    distance = (32 * 10) * 1.5 / (2 * (32 + 10))
    assert (x1, y1, x2, y2) == pytest.approx(((8 - distance) * 0.5, (10 - distance) * 2, (40 + distance) * 0.5, (20 + distance) * 2))
    assert score == pytest.approx(0.9)


def test_vertical_stack_merges_a_two_row_plate_and_keeps_others() -> None:
    upper = [10, 10, 50, 20, 0.9]
    lower = [12, 22, 48, 32, 0.7]
    elsewhere = [100, 100, 140, 110, 0.8]
    merged = ppocr_db.merge_rows(np.array([lower, elsewhere, upper]))
    assert merged.tolist() == [[10, 10, 50, 32, pytest.approx(0.8)], [100, 100, 140, 110, 0.8]]


def test_pr3_mapping_floors_ceils_clips_and_drops() -> None:
    boxes = ppocr_db.to_plate_boxes(np.array([[1.4, 2.6, 10.2, 8.0, 0.75], [-3, -3, 0.0, 5, 0.9], [50, 1, 70, 9, 1.0]]), 64, 32)
    assert boxes == [PlateBox(1, 2, 10, 6, 0.75), PlateBox(50, 1, 14, 8, 1.0)]
    with pytest.raises(ValueError, match="plate_detector_score_invalid"):
        ppocr_db.to_plate_boxes(np.array([[0, 0, 5, 5, 1.2]]), 64, 32)


def test_the_detector_maps_a_synthetic_crop_and_respects_the_configured_top_k(tmp_path: Path) -> None:
    def probability_map(tensor: np.ndarray) -> np.ndarray:
        assert tensor.dtype == np.float32 and tensor.shape[:2] == (1, 3)
        height, width = tensor.shape[2:]
        out = np.zeros((1, 1, height, width), dtype=np.float32)
        out[0, 0, 100:120, 40:120] = 0.95   # the plate line (score 0.95)
        out[0, 0, 20:30, 20:60] = 0.7       # badge text (0.7)
        out[0, 0, 150:160, 150:200] = 0.65  # another text region (0.65): beyond the top-2
        return out

    session = FakeSession(probability_map)
    detector = ppocr_db.PpOcrDbPlateDetector({"onnx-model": tmp_path / "m.onnx", "inference-config": _db_config(tmp_path)},
                                             max_detections=2, session_factory=lambda path: session)
    crop = Image.new("RGB", (240, 180), (90, 90, 90))
    boxes = detector.detect(crop, None)
    assert session.feeds[0].shape == (1, 3, 192, 256)
    assert [round(box.score, 2) for box in boxes] == [0.95, 0.7]
    plate = boxes[0]
    # Map pixels scale back by 240/256 horizontally and 180/192 vertically, after the unclip distance.
    assert 0 <= plate.x < 40 * 240 / 256 and plate.x + plate.width <= 240 and plate.y + plate.height <= 180


def test_the_detector_refuses_a_foreign_config_or_slots(tmp_path: Path) -> None:
    config = tmp_path / "other.yml"
    config.write_text(json.dumps({"PostProcess": {"name": "CTCLabelDecode"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="plate_adapter_config_invalid"):
        ppocr_db.PpOcrDbPlateDetector({"onnx-model": tmp_path / "m", "inference-config": config}, max_detections=2,
                                      session_factory=lambda path: FakeSession(None))
    with pytest.raises(ValueError, match="plate_adapter_artifacts_invalid"):
        ppocr_db.PpOcrDbPlateDetector({"onnx-model": tmp_path / "m"}, max_detections=2, session_factory=lambda path: FakeSession(None))


# --------------------------------------------------------------------------- fast-plate-ocr recogniser


def _one_hot(text: str, slots: int = 10, probability: float = 0.9) -> np.ndarray:
    out = np.full((1, slots * len(ALPHABET)), (1 - probability) / (len(ALPHABET) - 1), dtype=np.float32)
    for slot, char in enumerate(text.ljust(slots, "_")):
        out[0, slot * len(ALPHABET) + ALPHABET.index(char)] = probability
    return out


def test_decoding_strips_trailing_padding_and_averages_the_emitted_characters(tmp_path: Path) -> None:
    config = fast_plate_ocr.PlateConfig(json.loads(_plate_config(tmp_path).read_text(encoding="utf-8")))
    text, confidence = fast_plate_ocr.decode(_one_hot("ABC1234"), config)
    assert (text, confidence) == ("ABC1234", pytest.approx(0.9))
    assert fast_plate_ocr.decode(_one_hot(""), config) == ("", None)


def test_the_recogniser_feeds_a_uint8_nhwc_resize_and_returns_one_reading(tmp_path: Path) -> None:
    session = FakeSession(_one_hot("KA01AB1234", probability=0.8))
    recogniser = fast_plate_ocr.FastPlateOcrRecogniser({"onnx-model": tmp_path / "m", "plate-config": _plate_config(tmp_path)},
                                                       session_factory=lambda path: session)
    readings = recogniser.read(Image.new("RGB", (90, 30), (250, 250, 250)), None, PlateBox(0, 0, 90, 30, 0.9))
    assert readings == [Reading("KA01AB1234", pytest.approx(0.8))]
    assert session.feeds[0].shape == (1, 64, 128, 3) and session.feeds[0].dtype == np.uint8


def test_an_empty_reading_is_no_reading(tmp_path: Path) -> None:
    recogniser = fast_plate_ocr.FastPlateOcrRecogniser({"onnx-model": tmp_path / "m", "plate-config": _plate_config(tmp_path)},
                                                       session_factory=lambda path: FakeSession(_one_hot("")))
    assert recogniser.read(Image.new("RGB", (90, 30)), None, PlateBox(0, 0, 90, 30, 0.9)) == []


@pytest.mark.parametrize("override", [{"keep_aspect_ratio": True}, {"interpolation": "cubic"}, {"image_color_mode": "grayscale"}])
def test_a_plate_config_this_adapter_does_not_reproduce_is_refused(tmp_path: Path, override) -> None:
    with pytest.raises(ValueError, match="plate_adapter_config_unsupported"):
        fast_plate_ocr.FastPlateOcrRecogniser({"onnx-model": tmp_path / "m", "plate-config": _plate_config(tmp_path, **override)},
                                              session_factory=lambda path: FakeSession(None))


# --------------------------------------------------------------------------- the registry


def _real(tmp_path: Path) -> tuple[AdapterRequest, AdapterRequest]:
    return (AdapterRequest("plate-detector", "ppocr-db-onnx-v1", {"onnx-model": tmp_path / "d.onnx", "inference-config": tmp_path / "d.yml"}),
            AdapterRequest("ocr", "fast-plate-ocr-onnx-v1", {"onnx-model": tmp_path / "r.onnx", "plate-config": tmp_path / "r.yml"}))


def test_the_registry_slots_equal_the_adapter_modules() -> None:
    assert registry.MODEL_ADAPTERS[ppocr_db.ADAPTER_ID].slots == ppocr_db.SLOTS
    assert registry.MODEL_ADAPTERS[fast_plate_ocr.ADAPTER_ID].slots == fast_plate_ocr.SLOTS


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda p: (p, False, True), "plate_adapter_development_only"),
        (lambda p: (p, False, False), "plate_adapter_development_only"),
        (lambda p: (replace(p, fixture_seed="mavi-stage4-pr3-fixture-v1"), True, False), "plate_fixture_seed_with_model_adapter"),
    ],
)
def test_a_real_adapter_is_development_only_and_never_reached_through_the_fixture_seed(tmp_path: Path, change, code) -> None:
    parameters, development_only, production_mode = change(PARAMETERS)
    detector, recogniser = _real(tmp_path)
    with pytest.raises(AdapterUnavailable, match=code):
        components_for(detector, recogniser, parameters=parameters, development_only=development_only, production_mode=production_mode)


def test_each_capability_is_resolved_from_its_own_pack(tmp_path: Path) -> None:
    detector, recogniser = _real(tmp_path)
    swapped = (replace(detector, adapter_id=recogniser.adapter_id, artifacts=recogniser.artifacts), recogniser)
    with pytest.raises(AdapterUnavailable, match="plate_adapter_capability_mismatch"):
        components_for(*swapped, parameters=PARAMETERS, development_only=True, production_mode=False)
    with pytest.raises(AdapterUnavailable, match="plate_adapter_artifacts_invalid"):
        components_for(replace(detector, artifacts={"onnx-model": tmp_path / "d.onnx"}), recogniser, parameters=PARAMETERS,
                       development_only=True, production_mode=False)
    with pytest.raises(AdapterUnavailable, match="plate_adapter_fixture_mixed"):
        components_for(detector, AdapterRequest("ocr", FIXTURE_ADAPTER_ID, {}), parameters=replace(PARAMETERS, fixture_seed="s"),
                       development_only=True, production_mode=False)


def test_independent_selection_builds_the_two_named_adapters(tmp_path: Path, monkeypatch) -> None:
    built = []
    replaced = {}
    for adapter_id, registration in registry.MODEL_ADAPTERS.items():
        replaced[adapter_id] = replace(
            registration, build=lambda artifacts, parameters, adapter_id=adapter_id: built.append((adapter_id, dict(artifacts))) or adapter_id)
    monkeypatch.setattr(registry, "MODEL_ADAPTERS", MappingProxyType(replaced))
    detector, recogniser = _real(tmp_path)
    assert components_for(detector, recogniser, parameters=PARAMETERS, development_only=True, production_mode=False) == (
        "ppocr-db-onnx-v1", "fast-plate-ocr-onnx-v1")
    assert [item[0] for item in built] == ["ppocr-db-onnx-v1", "fast-plate-ocr-onnx-v1"]


def test_a_load_failure_is_a_stable_refusal(tmp_path: Path) -> None:
    detector, recogniser = _real(tmp_path)  # no such files: the YAML read fails
    with pytest.raises(AdapterUnavailable, match="^plate_adapter_load_failed"):
        components_for(detector, recogniser, parameters=PARAMETERS, development_only=True, production_mode=False)
