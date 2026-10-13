"""The identity-bearing plate parameters file ``mavi-plate-parameters-v1`` (ADR-013 item 11, 13, 14).

Loaded fail-closed, exactly as the platform's release parser will: unknown members, out-of-range
values and a profile shape whose worst-case artefact or completion exceeds 64 MiB are refused.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

from mavi_vision.plates.contracts import ROLES, is_admissible_profile_shape

PARAMETERS_SCHEMA: str = "mavi-plate-parameters-v1"
_KEYS = frozenset(
    {
        "schemaVersion",
        "maxDetectionsPerCrop",
        "maxPlatesPerCrop",
        "maxReadingsPerPlate",
        "detectorConfidenceFloor",
        "ocrConfidenceFloor",
        "excludedRoles",
        "fixtureSeed",
    }
)


class ParametersInvalid(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PlateParameters:
    max_detections_per_crop: int
    max_plates_per_crop: int
    max_readings_per_plate: int
    detector_confidence_floor: float
    ocr_confidence_floor: float
    excluded_roles: frozenset[str]
    fixture_seed: str | None


def _integer(document: dict, key: str) -> int:
    value = document.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ParametersInvalid(f"plate_parameters_invalid:{key}")
    return value


def _floor(document: dict, key: str) -> float:
    value = document.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ParametersInvalid(f"plate_parameters_invalid:{key}")
    return float(value)


def load_parameters(content: bytes) -> PlateParameters:
    try:
        document = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ParametersInvalid("plate_parameters_invalid:json") from exc
    if not isinstance(document, dict) or not set(document) <= _KEYS or document.get("schemaVersion") != PARAMETERS_SCHEMA:
        raise ParametersInvalid("plate_parameters_invalid:shape")
    detections = _integer(document, "maxDetectionsPerCrop")
    plates = _integer(document, "maxPlatesPerCrop")
    readings = _integer(document, "maxReadingsPerPlate")
    if not is_admissible_profile_shape(detections, plates, readings):
        raise ParametersInvalid("plate_parameters_invalid:worst_case_exceeds_cap")
    roles = document.get("excludedRoles")
    if not isinstance(roles, list) or not all(role in ROLES for role in roles) or len(set(roles)) != len(roles):
        raise ParametersInvalid("plate_parameters_invalid:excludedRoles")
    seed = document.get("fixtureSeed")
    if seed is not None and (not isinstance(seed, str) or not seed):
        raise ParametersInvalid("plate_parameters_invalid:fixtureSeed")
    return PlateParameters(
        max_detections_per_crop=detections,
        max_plates_per_crop=plates,
        max_readings_per_plate=readings,
        detector_confidence_floor=_floor(document, "detectorConfidenceFloor"),
        ocr_confidence_floor=_floor(document, "ocrConfidenceFloor"),
        excluded_roles=frozenset(roles),
        fixture_seed=seed,
    )
