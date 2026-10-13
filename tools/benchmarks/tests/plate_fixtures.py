"""Deterministic fixtures for the Stage 4 plate harness tests (never measurement evidence)."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from tools.benchmarks.capabilities.plates import instruments, truth as truths
from tools.benchmarks.capabilities.plates.instruments import Reading


class HeightInstrument:
    """Reads ``text`` when the region is at least ``min_height`` pixels tall, otherwise nothing (a resolution model)."""

    def __init__(self, instrument_id: str, text: str, min_height: int, role: str = "generic",
                 fail: bool = False) -> None:
        self.instrument_id = instrument_id
        self._text, self._min, self._role, self._fail = text, min_height, role, fail
        self.calls = 0

    def identity(self) -> dict[str, Any]:
        return {"instrumentId": self.instrument_id, "role": self._role, "instrumentSha256": "0" * 64}

    def read(self, region: np.ndarray) -> Reading:
        self.calls += 1
        if self._fail:
            raise RuntimeError("fixture failure")
        return Reading(self._text if region.shape[0] >= self._min else "", 0.9)


class SpecHeightInstrument(instruments._Pinned):
    """The ``fixture-height`` adapter for spec-driven tests: configuration ``{text, minHeight}``."""

    def __init__(self, spec: dict[str, Any], files: dict[str, Path]) -> None:
        super().__init__(spec, files)
        self._inner = HeightInstrument(spec["instrumentId"], spec["configuration"]["text"],
                                       spec["configuration"]["minHeight"])

    def read(self, region: np.ndarray) -> Reading:
        return self._inner.read(region)


def write_spec(directory: Path, model_root: Path, instrument_id: str, role: str, text: str, min_height: int) -> Path:
    model_dir = model_root / instrument_id
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "weights.bin").write_bytes(instrument_id.encode("utf-8"))
    import hashlib

    spec = {"schemaVersion": instruments.SPEC_SCHEMA, "instrumentId": instrument_id, "adapter": "fixture-height",
            "role": role, "packages": {}, "configuration": {"text": text, "minHeight": min_height},
            "modelFiles": [{"path": "weights.bin",
                            "sha256": hashlib.sha256(instrument_id.encode("utf-8")).hexdigest()}]}
    path = directory / f"{instrument_id}.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def scene(width: int = 640, height: int = 480, seed: int = 7) -> np.ndarray:
    """A textured RGB frame (seeded noise over a gradient), so JPEG sizes behave like natural imagery."""
    rng = np.random.default_rng(seed)
    gradient = np.linspace(0, 200, width, dtype=np.float64)[None, :, None] * np.ones((height, 1, 3))
    noise = rng.integers(0, 56, size=(height, width, 3))
    return np.clip(gradient + noise, 0, 255).astype(np.uint8)


def png(image: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(image).save(buffer, format="PNG")
    return buffer.getvalue()


def jpeg(image: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(image).save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def still_item(item_id: str, image: np.ndarray, plate_box: tuple[float, float, float, float], text: str | None,
               vehicle_box: dict[str, float] | None, layout: str = "one-line") -> dict[str, Any]:
    return {"itemId": item_id, "imagePath": f"images/{item_id}.png", "imageSha256": "0" * 64,
            "frameSize": {"width": image.shape[1], "height": image.shape[0]}, "sequenceId": None, "frameIndex": None,
            "gtTrackId": None, "vehicleBox": vehicle_box, "vehicleClass": "car",
            "plates": [truths.plate("plate", truths.box_polygon(*plate_box), text, layout)]}


def ufpr_annotation(vehicle: tuple[int, int, int, int], plate: tuple[int, int, int, int], text: str = "ABC-1234",
                    kind: str = "car", extra: str = "") -> bytes:
    lines = ["camera: GoPro Hero4 Silver", "position_vehicle: " + " ".join(map(str, vehicle)), f"\ttype: {kind}",
             "\tmake: Fiat", "\tmodel: Uno", "\tyear: 2010", f"plate: {text}",
             "position_plate: " + " ".join(map(str, plate)), "\tchar 1: 1 1 2 2"]
    return ("\n".join(lines) + "\n" + extra).encode("utf-8")


def write_ufpr(root: Path, sequences: dict[str, dict[str, Any]]) -> Path:
    """A UFPR-ALPR-layout source tree: ``{sequence: {split, frames: 30, size, annotation(index) -> bytes}}``."""
    for sequence, spec in sequences.items():
        directory = root / spec["split"] / sequence
        directory.mkdir(parents=True)
        width, height = spec.get("size", (64, 48))
        for number in range(1, spec.get("frames", 30) + 1):
            image = np.full((height, width, 3), number, dtype=np.uint8)
            (directory / f"{sequence}[{number:02d}].png").write_bytes(png(image))
            (directory / f"{sequence}[{number:02d}].txt").write_bytes(spec["annotation"](number - 1))
    return root
