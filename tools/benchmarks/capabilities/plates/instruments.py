"""OCR measuring instruments for the evidence-adequacy experiments (Stage 4 plan §3.1 E-A step 5).

An instrument **measures the evidence**; it is not a Stage-4 selection candidate and its result never ranks a model.
Two diverse pretrained readers are used (one plate-specific, one generic) so no single model's bias decides the
verdict. Each is pinned by a ``benchmark-plate-instrument-v1`` specification: the adapter, the exact package
versions, the configuration, and every model file by relative path and SHA-256. ``load`` re-hashes every model file
before the instrument is built and refuses a missing, extra-unlisted or mismatched file (``instrument_invalid``), so a
result names exactly the bytes that produced it.

Instrument packages live only in the Development benchmark environment declared by
``tools/benchmarks/plates/requirements-instruments.txt``; they are never a MAVI runtime dependency and are imported
lazily, so the harness and its tests run without them.

``read`` takes one RGB uint8 plate region and returns the raw text (two-line output joined by LF, top line first) and
an optional confidence. An exception inside the instrument is recorded per read as ``instrument_error`` and makes that
instrument's results NOT MEASURED (verdict rule), never a silent miss.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

import numpy as np

from tools.benchmarks.core.identity import S32Error, document_sha256, require

SPEC_SCHEMA = "benchmark-plate-instrument-v1"
CODE = "instrument_invalid"


@dataclass(frozen=True, slots=True)
class Reading:
    text: str
    confidence: float | None


class Instrument(Protocol):
    instrument_id: str

    def identity(self) -> dict[str, Any]: ...

    def read(self, region: np.ndarray) -> Reading: ...


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_spec(path: Path) -> dict[str, Any]:
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    require(isinstance(spec, dict) and spec.get("schemaVersion") == SPEC_SCHEMA, f"{CODE}:schema")
    for key in ("instrumentId", "adapter", "role", "packages", "configuration", "modelFiles"):
        require(key in spec, f"{CODE}:field:{key}")
    require(spec["role"] in ("plate-specific", "generic", "annotation-plate-detector"), f"{CODE}:role")
    paths = [item["path"] for item in spec["modelFiles"]]
    require(paths == sorted(set(paths)), f"{CODE}:model_file_order")
    return spec


def verify_model_files(spec: dict[str, Any], model_root: Path) -> dict[str, Path]:
    """Every listed model file present with its SHA-256; nothing else in the instrument's model directory."""
    root = Path(model_root) / spec["instrumentId"]
    require(root.is_dir(), f"{CODE}:model_root:{spec['instrumentId']}")
    present = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    listed = [item["path"] for item in spec["modelFiles"]]
    require(present == listed, f"{CODE}:model_files:{spec['instrumentId']}")
    files = {}
    for item in spec["modelFiles"]:
        path = root / item["path"]
        require(_sha256(path) == item["sha256"], f"{CODE}:model_sha256:{item['path']}")
        files[item["path"]] = path
    return files


def verify_packages(spec: dict[str, Any]) -> None:
    for name, version in sorted(spec["packages"].items()):
        try:
            installed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise S32Error(f"{CODE}:package_missing:{name}") from exc
        require(installed == version, f"{CODE}:package_version:{name}:{installed}")


class _Pinned:
    def __init__(self, spec: dict[str, Any], files: dict[str, Path]) -> None:
        self.instrument_id = spec["instrumentId"]
        self._spec = spec
        self._files = files

    def identity(self) -> dict[str, Any]:
        spec = self._spec
        body = {"instrumentId": spec["instrumentId"], "adapter": spec["adapter"], "role": spec["role"],
                "packages": spec["packages"], "configuration": spec["configuration"],
                "modelFiles": spec["modelFiles"]}
        return {**body, "instrumentSha256": document_sha256(body)}


def _single_thread_session_options():
    """ONNX Runtime CPU session options for reproducible reads: one intra-op and one inter-op thread, sequential."""
    import onnxruntime  # noqa: PLC0415 (benchmark environment only)

    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
    return options


class FastPlateOcr(_Pinned):
    """``fast-plate-ocr`` (plate-specific recogniser, ONNX Runtime CPU) from pinned local model files.

    Verified against fast-plate-ocr 1.1.0: ``LicensePlateRecognizer(onnx_model_path=, plate_config_path=,
    providers=, sess_options=)``; ``run(array, return_confidence=True)`` returns ``PlatePrediction`` objects with
    ``plate`` (padding removed by the library) and per-slot ``char_probs``. In-memory arrays must already be in the
    model's colour mode (``image_color_mode`` of the plate config), so an RGB region is passed as RGB, or converted to
    grey for a greyscale model. The confidence is the mean probability of the slots that produced characters.
    """

    def __init__(self, spec: dict[str, Any], files: dict[str, Path]) -> None:
        super().__init__(spec, files)
        from fast_plate_ocr import LicensePlateRecognizer  # noqa: PLC0415 (benchmark environment only)

        configuration = spec["configuration"]
        self._model = LicensePlateRecognizer(onnx_model_path=str(files[configuration["onnxModel"]]),
                                             plate_config_path=str(files[configuration["plateConfig"]]),
                                             providers=["CPUExecutionProvider"],
                                             sess_options=_single_thread_session_options())
        self._grey = self._model.config.image_color_mode == "grayscale"

    def read(self, region: np.ndarray) -> Reading:
        image = region
        if self._grey:
            import cv2  # noqa: PLC0415

            image = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)[..., None]
        prediction = self._model.run_one(np.ascontiguousarray(image), return_confidence=True)
        text = prediction.plate
        probabilities = prediction.char_probs
        confidence = None
        if probabilities is not None and len(text):
            confidence = float(np.mean(np.asarray(probabilities, dtype=np.float64)[: len(text)]))
        return Reading(text, confidence)


class RapidOcrRecogniser(_Pinned):
    """``rapidocr-onnxruntime`` (PP-OCRv4 detection + recognition, ONNX Runtime CPU) on the given plate region.

    Verified against rapidocr-onnxruntime 1.4.4: an in-memory array is taken as BGR. Detection finds the text lines
    of the region (so a two-row plate is read as two lines, top first, joined by LF); recognition reads each. No
    angle classifier. ``text_score`` 0 keeps every recognised line (the instrument reports, it does not filter).
    """

    def __init__(self, spec: dict[str, Any], files: dict[str, Path]) -> None:
        super().__init__(spec, files)
        from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415 (benchmark environment only)

        configuration = spec["configuration"]
        self._engine = RapidOCR(det_model_path=str(files[configuration["detModel"]]),
                                rec_model_path=str(files[configuration["recModel"]]),
                                cls_model_path=str(files[configuration["clsModel"]]),
                                det_use_cuda=False, rec_use_cuda=False, cls_use_cuda=False,
                                intra_op_num_threads=1, inter_op_num_threads=1, text_score=0.0)

    def read(self, region: np.ndarray) -> Reading:
        import cv2  # noqa: PLC0415

        bgr = np.ascontiguousarray(cv2.cvtColor(region, cv2.COLOR_RGB2BGR))
        result, _ = self._engine(bgr, use_det=True, use_cls=False, use_rec=True, text_score=0.0)
        if not result:
            return Reading("", None)
        # Lines top to bottom (then left to right) by their box's top-left corner.
        lines = sorted(result, key=lambda line: (min(p[1] for p in line[0]), min(p[0] for p in line[0])))
        text = "\n".join(str(line[1]) for line in lines)
        confidence = float(np.mean([float(line[2]) for line in lines]))
        return Reading(text, confidence)


ADAPTERS: dict[str, Callable[[dict[str, Any], dict[str, Path]], Instrument]] = {
    "fast-plate-ocr": FastPlateOcr,
    "rapidocr-onnxruntime": RapidOcrRecogniser,
}


def load(spec_path: Path, model_root: Path) -> Instrument:
    spec = load_spec(spec_path)
    require(spec["adapter"] in ADAPTERS, f"{CODE}:adapter:{spec['adapter']}")
    files = verify_model_files(spec, model_root)
    verify_packages(spec)
    return ADAPTERS[spec["adapter"]](spec, files)
