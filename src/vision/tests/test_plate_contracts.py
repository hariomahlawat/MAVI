"""The worker side of the plate contract (Stage 4 PR-3; ADR-013 implementation amendment 2026-10-13).

Held to the same cross-language vectors as ``Mavi.Application.Tests.Plates``: normalisation, the
identity, the artefact/completion bound, and the checked-in examples.
"""

from __future__ import annotations

import hashlib
import json
import sys
import unicodedata
from pathlib import Path

import pytest

from mavi_vision.plates import contracts
from mavi_vision.plates.normalisation import normalise
from mavi_vision.plates.parameters import ParametersInvalid, load_parameters
from mavi_vision.plates.predictions import canonical_json

ROOT = Path(__file__).resolve().parents[3]
VECTORS = ROOT / "contracts" / "test-vectors"
EXAMPLES = ROOT / "contracts" / "examples"


def _json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


NORMALISATION = _json(VECTORS / "plate-normalisation-v1.json")


@pytest.mark.parametrize("vector", NORMALISATION["vectors"], ids=lambda item: item["id"])
def test_normalisation_matches_the_shared_vector(vector: dict) -> None:
    result = normalise(vector["raw"])
    assert (result.raw, result.normalised, result.outcome, result.reason, result.format_class) == (
        vector["raw"], vector["normalised"], vector["outcome"], vector["reason"], vector["formatClass"])


def test_the_normalisation_sha_is_the_vector_file_sha() -> None:
    assert contracts.NORMALISATION_SHA256 == hashlib.sha256((VECTORS / "plate-normalisation-v1.json").read_bytes()).hexdigest()
    assert NORMALISATION["normalisationId"] == contracts.NORMALISATION_ID


def test_the_identity_vector_fingerprint_is_the_sha_of_its_canonical_bytes() -> None:
    vector = _json(VECTORS / "plate-identity-v1.json")["vectors"][0]
    canonical = vector["canonicalIdentity"]
    assert hashlib.sha256(canonical.encode("ascii")).hexdigest() == vector["fingerprint"]
    document = json.loads(canonical)
    assert canonical_json(document).decode("ascii") == canonical
    assert document["schemaVersion"] == contracts.IDENTITY_SCHEMA_VERSION
    assert document["normalisation"] == {"id": contracts.NORMALISATION_ID, "sha256": contracts.NORMALISATION_SHA256}
    assert [item["capabilityId"] for item in document["capabilities"]] == list(contracts.CAPABILITIES)


@pytest.mark.parametrize("vector", _json(VECTORS / "plate-artifact-bound-v1.json")["vectors"], ids=lambda item: item["name"])
def test_the_worst_case_sizes_match_the_cross_language_vectors(vector: dict) -> None:
    shape = (vector["maxDetectionsPerCrop"], vector["maxPlatesPerCrop"], vector["maxReadingsPerPlate"])
    assert contracts.worst_case_prediction_artifact_bytes(*shape) == vector["worstCaseArtifactBytes"]
    assert contracts.worst_case_completion_body_bytes(*shape) == vector["worstCaseCompletionBytes"]
    assert contracts.is_admissible_profile_shape(*shape) is vector["accepted"]


def test_the_bounded_v1_profile_is_the_worst_case_and_fits_the_cap() -> None:
    shape = (contracts.MAXIMUM_DETECTIONS_PER_CROP, contracts.MAXIMUM_PLATES_PER_CROP, contracts.MAXIMUM_READINGS_PER_PLATE)
    assert shape == (2, 1, 3)
    assert contracts.worst_case_prediction_artifact_bytes(*shape) <= contracts.MAXIMUM_PREDICTION_ARTIFACT_BYTES
    for outside in ((3, 1, 3), (2, 2, 1), (2, 1, 4)):
        assert not contracts.is_admissible_profile_shape(*outside)
        with pytest.raises(ValueError):
            contracts.worst_case_prediction_artifact_bytes(*outside)


_U = "00000000-0000-0000-0000-000000000000"
_WORST_DOUBLE = 2.2250738585072014e-308
_WORST_RAW = "\u0001" * contracts.MAXIMUM_RAW_TEXT_LENGTH  # every unit escapes to \u0001


def _size(document: object) -> int:
    return len(json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)) + 1  # + separator


def test_each_byte_envelope_bounds_its_maximal_element() -> None:
    """The bound is honest: no element an honest worker emits is larger than its declared envelope."""
    reason = max(contracts.TRACK_UNAVAILABLE_REASONS_BY_SEVERITY + tuple(contracts.CROP_ABSTENTION_REASONS), key=len)
    role = max(contracts.ROLES, key=len)
    reading = {"confidence": _WORST_DOUBLE, "rank": 4, "rawLineCount": 2, "rawText": _WORST_RAW}
    assert _size(reading) <= contracts.ARTIFACT_READING_ENVELOPE_BYTES + contracts.RAW_TEXT_WORST_CASE_BYTES
    plate = {"outcome": "unreadable", "plateIndex": 7, "readings": []}
    assert _size(plate) <= contracts.ARTIFACT_PLATE_ENVELOPE_BYTES
    detection = {"box": [4095, 4095, 4096, 4096], "plate": None, "score": _WORST_DOUBLE}
    assert _size(detection) <= contracts.ARTIFACT_DETECTION_ENVELOPE_BYTES
    crop = {"cropHeight": 4096, "cropWidth": 4096, "detections": [], "evidenceRank": 3,
            "observationId": _U, "reason": reason, "role": role, "status": "unavailable"}
    assert _size(crop) <= contracts.ARTIFACT_CROP_ENVELOPE_BYTES
    text = {"bestPlate": {"observationId": _U, "plateIndex": 7}, "maxConfidence": _WORST_DOUBLE, "supportCount": 32}
    assert _size(text) <= contracts.ARTIFACT_TEXT_ENVELOPE_BYTES
    track = {"crops": [], "outcome": "unavailable", "reason": reason, "texts": [], "trackId": _U}
    assert _size(track) <= contracts.ARTIFACT_TRACK_ENVELOPE_BYTES

    c_reading = {"rank": 4, "rawText": _WORST_RAW, "rawLineCount": 2, "confidence": _WORST_DOUBLE}
    assert _size(c_reading) <= contracts.COMPLETION_READING_ENVELOPE_BYTES + contracts.RAW_TEXT_WORST_CASE_BYTES
    c_observation = {"sourceObservationId": _U, "plateIndex": 7, "box": {"x": 4095, "y": 4095, "width": 4096, "height": 4096},
                     "cropWidth": 4096, "cropHeight": 4096, "detectorConfidence": _WORST_DOUBLE, "outcome": "unreadable",
                     "readings": []}
    assert _size(c_observation) <= contracts.COMPLETION_OBSERVATION_ENVELOPE_BYTES
    c_text = {"bestPlate": {"sourceObservationId": _U, "plateIndex": 7}, "supportCount": 32, "maxConfidence": _WORST_DOUBLE}
    assert _size(c_text) <= contracts.COMPLETION_TEXT_ENVELOPE_BYTES
    c_track = {"trackId": _U, "outcome": "unavailable", "reason": reason, "plateObservations": [], "texts": []}
    assert _size(c_track) <= contracts.COMPLETION_TRACK_ENVELOPE_BYTES


def test_the_header_envelopes_bound_the_examples() -> None:
    predictions = json.loads((EXAMPLES / "plate-predictions-v1.example.json").read_text(encoding="utf-8"))
    header = dict(predictions, tracks=[])
    assert _size(header) <= contracts.ARTIFACT_HEADER_BYTES
    completion = json.loads((EXAMPLES / "plate-complete-v1.example.json").read_text(encoding="utf-8"))
    completion["payload"]["tracks"] = []
    # Provenance at its longest member bounds (schema): runtime family/variant/build 128, device 64.
    provenance = completion["provenance"]
    provenance.update(runtimePackFamilyId="f" * 128, runtimeVariant="v" * 128, maviBuild="b" * 128, actualDevice="d" * 64,
                      runtimePackId="mavi-runtime-v2-" + "0" * 64, workerId=None)
    for capability in provenance["capabilities"]:
        capability.update(qualificationId="q" * 256, qualificationSha256="0" * 64)
    assert _size(completion) <= contracts.COMPLETION_HEADER_BYTES


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("KA01AB1234", True),
        ("KA 01 AB 1234", True),
        ("MH12\nDE 4321", True),
        ("\u0915\u093e01", True),
        ("\U0001f697A1", True),
        ("", False),
        ("\nKA01", False),
        ("KA01\n", False),
        ("KA\n01\nAB", False),
        ("KA\t01", False),
        ("KA\r\n01", False),
        ("KA\u007f01", False),
        ("KA\u000001", False),
        ("KA\ufffe01", True),  # kept verbatim; normalisation rejects it (v1 vectors)
        ("KA\uffff01", True),
        ("\ud83dA", False),
        ("A\ude97", False),
        ("1" * 33, False),
        ("1" * 32, True),
        ("\U0001f697" * 16, True),
        ("\U0001f697" * 16 + "A", False),
    ],
)
def test_raw_text_follows_the_wire_rule(value: str, expected: bool) -> None:
    assert contracts.is_raw_text(value) is expected


def test_normalisation_expands_at_most_four_characters_per_code_unit() -> None:
    worst = 0
    for code_point in range(sys.maxunicode + 1):
        if 0xD800 <= code_point <= 0xDFFF:
            continue
        text = chr(code_point)
        if not contracts.is_raw_text(text):
            continue
        result = normalise(text)
        if result.normalised is None:
            continue
        units = contracts.utf16_length(text)
        assert len(result.normalised) <= contracts.MAXIMUM_NORMALISATION_EXPANSION * units, hex(code_point)
        worst = max(worst, len(result.normalised))
    assert worst == contracts.MAXIMUM_NORMALISATION_EXPANSION, unicodedata.unidata_version


def test_the_fixture_parameters_load_and_bad_ones_are_refused() -> None:
    fixture = (ROOT / "tests" / "fixtures" / "plates" / "fixture-parameters-v1.json").read_bytes()
    parameters = load_parameters(fixture)
    assert (parameters.max_detections_per_crop, parameters.max_plates_per_crop, parameters.max_readings_per_plate) == (2, 1, 3)
    assert parameters.excluded_roles == frozenset()
    document = json.loads(fixture)
    for change in (
        {"maxReadingsPerPlate": 4},  # beyond the bounded v1 profile
        {"maxPlatesPerCrop": 2},
        {"maxDetectionsPerCrop": 3},
        {"ocrConfidenceFloor": 1.5},
        {"excludedRoles": ["bogus"]},
        {"unexpected": 1},
        {"maxDetectionsPerCrop": True},
    ):
        with pytest.raises(ParametersInvalid):
            load_parameters(json.dumps(dict(document, **change)).encode())


def test_the_lease_example_parses() -> None:
    lease = contracts.PlateLease.model_validate_json((EXAMPLES / "plate-lease-v1.example.json").read_bytes())
    assert lease.schema_version == contracts.CONTROL_VERSION
    assert [item.capability_id for item in lease.identity.capabilities] == list(contracts.CAPABILITIES)
    assert all(track.object_class == "vehicle" for track in lease.tracks)


ORDER = _json(VECTORS / "plate-reading-order-v1.json")


@pytest.mark.parametrize("vector", ORDER["vectors"], ids=lambda item: item["name"])
def test_readings_rank_in_the_cross_language_order(vector: dict) -> None:
    readings = [(item["rawText"], item["confidence"]) for item in vector["readings"]]
    ranked = sorted(range(len(readings)), key=lambda index: contracts.reading_rank_key(readings[index][1], readings[index][0]))
    assert ranked == vector["rankedIndices"]


def test_the_pipeline_ranks_a_supplementary_plane_tie_in_utf16_order() -> None:
    from mavi_vision.plates.inference import Reading
    from mavi_vision.plates.pipeline import _plate

    parameters = load_parameters((ROOT / "tests" / "fixtures" / "plates" / "fixture-parameters-v1.json").read_bytes())
    plate = _plate(0, [Reading("\uff21", 0.9), Reading("\U0001f600", 0.9)], parameters)
    # U+1F600 is the surrogate pair D83D DE00, below U+FF21 in UTF-16 order (code-point order says the reverse).
    assert [item.raw_text for item in plate.readings] == ["\U0001f600", "\uff21"]
