"""The closed, versioned registry of plate capability adapters (Stage 4 plan §2.4; ADR-013 item 8; Issue #225).

Each Model Pack names its adapter through ``capabilitySpecific.<capabilityId>.adapterId``, and the detector and the
recogniser are resolved **independently**, each from its own pack: replacing one changes one ``modelPackId``. An id
outside this registry, or one registered for the other capability, is refused, never guessed.

* ``plates-fixture-v1`` is the Development fixture. It serves both capabilities from one pack, needs the profile's
  ``fixtureSeed`` and is refused in Production or under a profile that is not ``developmentOnly``.
* ``ppocr-db-onnx-v1`` (``plate-detector``) and ``fast-plate-ocr-onnx-v1`` (``ocr``) are the Issue #225 Development
  pilot adapters. They run real pretrained ONNX models from the pack's hash-verified artefacts, are refused when the
  profile carries a ``fixtureSeed`` (a real adapter is never selected through the fixture), and are refused in
  Production and under a profile that is not ``developmentOnly``: they are unqualified Development components, not
  a Model Selection Event outcome.

Model adapters are built lazily, so this module imports without the ``plates-onnx-v1`` runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping

from mavi_vision.plates.adapters.fixture import FIXTURE_ADAPTER_ID, FixturePlateDetector, FixturePlateRecogniser
from mavi_vision.plates.inference import PlateDetector, PlateRecogniser
from mavi_vision.plates.parameters import PlateParameters

DETECTOR_CAPABILITY = "plate-detector"
OCR_CAPABILITY = "ocr"


class AdapterUnavailable(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AdapterRequest:
    """What one Model Pack asks for: its adapter id and its artefact paths by the adapter's slot names."""

    capability_id: str
    adapter_id: str
    artifacts: Mapping[str, Path]


@dataclass(frozen=True, slots=True)
class _Registration:
    capability_id: str
    slots: frozenset[str]
    build: Callable[[Mapping[str, Path], PlateParameters], object]


def _ppocr_db(artifacts: Mapping[str, Path], parameters: PlateParameters) -> PlateDetector:
    from mavi_vision.plates.adapters.ppocr_db import PpOcrDbPlateDetector  # noqa: PLC0415

    return PpOcrDbPlateDetector(artifacts, max_detections=parameters.max_detections_per_crop)


def _fast_plate_ocr(artifacts: Mapping[str, Path], parameters: PlateParameters) -> PlateRecogniser:
    from mavi_vision.plates.adapters.fast_plate_ocr import FastPlateOcrRecogniser  # noqa: PLC0415

    return FastPlateOcrRecogniser(artifacts)


# Slot names are repeated from the adapter modules so that the registry imports without their runtime; a test holds
# the two equal.
MODEL_ADAPTERS: Mapping[str, _Registration] = MappingProxyType(
    {
        "ppocr-db-onnx-v1": _Registration(DETECTOR_CAPABILITY, frozenset({"onnx-model", "inference-config"}), _ppocr_db),
        "fast-plate-ocr-onnx-v1": _Registration(OCR_CAPABILITY, frozenset({"onnx-model", "plate-config"}), _fast_plate_ocr),
    }
)
REGISTERED_ADAPTER_IDS = frozenset({FIXTURE_ADAPTER_ID, *MODEL_ADAPTERS})


def components_for(
    detector: AdapterRequest,
    recogniser: AdapterRequest,
    *,
    parameters: PlateParameters,
    development_only: bool,
    production_mode: bool,
) -> tuple[PlateDetector, PlateRecogniser]:
    """The detector and recogniser the two packs name, or a stable refusal code."""
    if detector.capability_id != DETECTOR_CAPABILITY or recogniser.capability_id != OCR_CAPABILITY:
        raise AdapterUnavailable("plate_adapter_capability_mismatch")
    for request in (detector, recogniser):
        if request.adapter_id not in REGISTERED_ADAPTER_IDS:
            raise AdapterUnavailable("plate_adapter_unknown")
    fixture = [request.adapter_id == FIXTURE_ADAPTER_ID for request in (detector, recogniser)]
    if any(fixture):
        if not all(fixture):
            raise AdapterUnavailable("plate_adapter_fixture_mixed")
        if production_mode or not development_only:
            raise AdapterUnavailable("plate_fixture_forbidden_in_production")
        if not parameters.fixture_seed:
            raise AdapterUnavailable("plate_fixture_seed_required")
        if detector.artifacts or recogniser.artifacts:
            raise AdapterUnavailable("plate_adapter_artifacts_invalid")
        return FixturePlateDetector(parameters.fixture_seed), FixturePlateRecogniser(parameters.fixture_seed)

    # A real model adapter: never through the fixture seed, never in Production, only under a Development profile.
    if parameters.fixture_seed is not None:
        raise AdapterUnavailable("plate_fixture_seed_with_model_adapter")
    if production_mode or not development_only:
        raise AdapterUnavailable("plate_adapter_development_only")
    built = []
    for request in (detector, recogniser):
        registration = MODEL_ADAPTERS[request.adapter_id]
        if registration.capability_id != request.capability_id:
            raise AdapterUnavailable("plate_adapter_capability_mismatch")
        if set(request.artifacts) != registration.slots:
            raise AdapterUnavailable("plate_adapter_artifacts_invalid")
        try:
            built.append(registration.build(request.artifacts, parameters))
        except ImportError as exc:
            raise AdapterUnavailable("plate_adapter_runtime_unavailable") from exc
        except ValueError as exc:
            # The adapters' own refusals are stable codes; anything else is not echoed (it may carry a path).
            code = str(exc)
            detail = f":{code}" if code.startswith("plate_adapter_") and code.replace("_", "").isalpha() else ""
            raise AdapterUnavailable(f"plate_adapter_load_failed{detail}") from exc
        except (OSError, KeyError, TypeError) as exc:
            raise AdapterUnavailable("plate_adapter_load_failed") from exc
        except Exception as exc:  # noqa: BLE001 - an ONNX Runtime load failure has its own exception types.
            raise AdapterUnavailable("plate_adapter_load_failed") from exc
    return built[0], built[1]  # type: ignore[return-value]


__all__ = [
    "AdapterRequest",
    "AdapterUnavailable",
    "DETECTOR_CAPABILITY",
    "FIXTURE_ADAPTER_ID",
    "MODEL_ADAPTERS",
    "OCR_CAPABILITY",
    "REGISTERED_ADAPTER_IDS",
    "components_for",
]
