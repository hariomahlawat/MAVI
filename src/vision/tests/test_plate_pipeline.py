"""The plate role's per-crop analysis, Track summary and encoding (Stage 4 PR-3).

The golden tests rebuild the crop records of ``contracts/examples/plate-predictions-v1.example.json`` and
require the summary and both encoders to reproduce the checked-in artefact byte for byte and the
completion example's facts exactly — the examples whose SHA-256 and digest the .NET tests pin.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from uuid import UUID

import pytest
from PIL import Image

from mavi_vision.plates import contracts
from dataclasses import replace

from mavi_vision.plates.adapters import AdapterRequest, AdapterUnavailable, components_for
from mavi_vision.plates.adapters.fixture import FIXTURE_ADAPTER_ID
from mavi_vision.plates.inference import PlateBox, Reading, VerifiedCrop
from mavi_vision.plates.parameters import load_parameters
from mavi_vision.plates.pipeline import (
    CropRecord,
    DetectionRecord,
    OutputInvalid,
    PlateRecord,
    RankedReading,
    analyse_crop,
    excluded_crop,
    summarise_track,
    unavailable_crop,
)
from mavi_vision.plates.predictions import completion_tracks, encode_completion, encode_predictions

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "contracts" / "examples"
PARAMETERS = load_parameters((ROOT / "tests" / "fixtures" / "plates" / "fixture-parameters-v1.json").read_bytes())
LEASE = contracts.PlateLease.model_validate_json((EXAMPLES / "plate-lease-v1.example.json").read_bytes())
PREDICTIONS_BYTES = (EXAMPLES / "plate-predictions-v1.example.json").read_bytes()
PREDICTIONS = json.loads(PREDICTIONS_BYTES)
COMPLETION = json.loads((EXAMPLES / "plate-complete-v1.example.json").read_text(encoding="utf-8"))


def _records_from_example(track: dict) -> tuple[CropRecord, ...]:
    crops = []
    for crop in track["crops"]:
        detections = []
        for detection in crop["detections"]:
            plate = detection["plate"]
            detections.append(DetectionRecord(
                tuple(detection["box"]),
                detection["score"],
                None if plate is None else PlateRecord(
                    plate["plateIndex"], plate["outcome"],
                    tuple(RankedReading(item["rank"], item["rawText"], item["rawLineCount"], item["confidence"]) for item in plate["readings"]),
                ),
            ))
        crops.append(CropRecord(UUID(crop["observationId"]), crop["role"], crop["evidenceRank"], crop["status"], crop["reason"],
                                crop["cropWidth"], crop["cropHeight"], tuple(detections)))
    return tuple(crops)


def _example_tracks():
    return tuple(
        summarise_track(lease_track, _records_from_example(track))
        for lease_track, track in zip(LEASE.tracks, PREDICTIONS["tracks"], strict=True)
    )


def test_the_summary_reproduces_the_example_decisions() -> None:
    for record, track in zip(_example_tracks(), PREDICTIONS["tracks"], strict=True):
        assert (record.outcome, record.reason) == (track["outcome"], track["reason"])
        assert [
            {"bestPlate": {"observationId": str(text.best_observation_id), "plateIndex": text.best_plate_index},
             "maxConfidence": text.max_confidence, "supportCount": text.support_count}
            for text in record.texts
        ] == track["texts"]


def test_the_encoder_reproduces_the_sealed_example_byte_for_byte() -> None:
    assert encode_predictions(LEASE, _example_tracks()) == PREDICTIONS_BYTES


def test_the_completion_facts_equal_the_completion_example() -> None:
    assert completion_tracks(_example_tracks(), PARAMETERS) == COMPLETION["payload"]["tracks"]
    body = json.loads(encode_completion(
        LEASE, "plates-01", COMPLETION["provenance"], _example_tracks(), PARAMETERS,
        prediction_size_bytes=len(PREDICTIONS_BYTES), prediction_sha256=hashlib.sha256(PREDICTIONS_BYTES).hexdigest()))
    assert body == COMPLETION


# --- Per-crop analysis ------------------------------------------------------------------------------


def _jpeg(width: int = 200, height: int = 150, shade: int = 90) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (shade, shade, shade)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _verified(content: bytes, observation=None) -> VerifiedCrop:
    observation = observation or LEASE.tracks[0].observations[0]
    return VerifiedCrop(str(observation.observation_id), observation.role, observation.evidence_rank,
                        hashlib.sha256(content).hexdigest(), content)


class _Detector:
    def __init__(self, boxes=None, error=False):
        self.boxes, self.error = boxes or [], error

    def detect(self, crop, verified):
        if self.error:
            raise RuntimeError("model fault")
        return list(self.boxes)


class _Recogniser:
    def __init__(self, readings=None, error=False):
        self.readings, self.error = readings or [], error
        self.regions = []

    def read(self, region, verified, box):
        if self.error:
            raise RuntimeError("model fault")
        self.regions.append(region.size)
        return list(self.readings)


OBSERVATION = LEASE.tracks[0].observations[0]


def test_every_proposal_is_retained_in_order_and_one_plate_is_selected_by_the_floor() -> None:
    boxes = [PlateBox(10, 10, 40, 10, 0.3), PlateBox(5, 5, 40, 10, 0.9)]
    recogniser = _Recogniser([Reading("KA01AB1234", 0.8)])
    record = analyse_crop(OBSERVATION, _verified(_jpeg()), _Detector(boxes), recogniser, PARAMETERS)
    assert record.status == contracts.CROP_SCORED
    assert (record.width, record.height) == (200, 150)
    # Both proposals are recorded; maxPlatesPerCrop = 1 selects the best one only.
    assert [detection.score for detection in record.detections] == [0.9, 0.3]
    assert record.detections[0].plate is not None and record.detections[1].plate is None
    assert recogniser.regions == [(40, 10)]


def test_output_beyond_a_configured_bound_fails_the_attempt_and_is_never_truncated() -> None:
    three = [PlateBox(10, 10, 40, 10, 0.3), PlateBox(5, 5, 40, 10, 0.9), PlateBox(60, 60, 40, 10, 0.2)]
    with pytest.raises(OutputInvalid, match="plate_detector_output_exceeds_bound"):
        analyse_crop(OBSERVATION, _verified(_jpeg()), _Detector(three), _Recogniser(), PARAMETERS)
    four = [Reading("A", 0.9), Reading("B", 0.8), Reading("C", 0.7), Reading("D", 0.6)]
    with pytest.raises(OutputInvalid, match="plate_recogniser_output_exceeds_bound"):
        analyse_crop(OBSERVATION, _verified(_jpeg()), _Detector([PlateBox(5, 5, 40, 10, 0.9)]), _Recogniser(four), PARAMETERS)


@pytest.mark.parametrize("vector", [item for item in json.loads((ROOT / "contracts" / "test-vectors" / "plate-reading-order-v1.json")
                                                         .read_text(encoding="utf-8"))["vectors"] if item["refused"]],
                         ids=lambda item: item["name"])
def test_a_duplicate_reading_abstains_its_crop_and_keeps_its_proposals(vector: dict) -> None:
    readings = [Reading(item["rawText"], item["confidence"]) for item in vector["readings"]]
    boxes = [PlateBox(5, 5, 40, 10, 0.9), PlateBox(60, 60, 40, 10, 0.4)]
    record = analyse_crop(OBSERVATION, _verified(_jpeg()), _Detector(boxes), _Recogniser(readings), PARAMETERS)
    assert (record.status, record.reason) == (contracts.CROP_ABSTAINED, "ocr_output_invalid")
    # Nothing is dropped or de-duplicated into a plate: both proposals are kept, without a plate.
    assert [detection.score for detection in record.detections] == [0.9, 0.4]
    assert all(detection.plate is None for detection in record.detections)


def test_one_crop_with_a_duplicate_reading_never_fails_its_track() -> None:
    first, second = LEASE.tracks[0].observations[0], LEASE.tracks[0].observations[1]
    track = LEASE.tracks[0].model_copy(update={"observations": (first, second)})
    box = [PlateBox(5, 5, 40, 10, 0.9)]
    duplicate = analyse_crop(first, _verified(_jpeg(), first), _Detector(box),
                             _Recogniser([Reading("KA01AB1234", 0.9), Reading("KA01AB1234", 0.9)]), PARAMETERS)
    honest = analyse_crop(second, _verified(_jpeg(), second), _Detector(box), _Recogniser([Reading("KA01AB1234", 0.9)]), PARAMETERS)
    summary = summarise_track(track, (duplicate, honest))
    assert duplicate.status == contracts.CROP_ABSTAINED and honest.status == contracts.CROP_SCORED
    assert summary.outcome == contracts.TRACK_ANALYSED
    assert [text.normalised_text for text in summary.texts] == ["KA01AB1234"]


def test_the_count_bound_is_checked_before_the_items() -> None:
    # Over-bound output with a malformed item is still a contract violation, never an abstention.
    malformed = [PlateBox(10, 10, 40, 10, 0.3), PlateBox(5, 5, 40, 10, 0.9), PlateBox(-1, 60, 40, 10, 0.2)]
    with pytest.raises(OutputInvalid, match="plate_detector_output_exceeds_bound"):
        analyse_crop(OBSERVATION, _verified(_jpeg()), _Detector(malformed), _Recogniser(), PARAMETERS)
    readings = [Reading("A", 0.9), Reading("B", 0.8), Reading("C", 0.7), Reading("D", 7.0)]
    with pytest.raises(OutputInvalid, match="plate_recogniser_output_exceeds_bound"):
        analyse_crop(OBSERVATION, _verified(_jpeg()), _Detector([PlateBox(5, 5, 40, 10, 0.9)]), _Recogniser(readings), PARAMETERS)


def test_no_box_above_the_detector_floor_selects_no_plate() -> None:
    record = analyse_crop(OBSERVATION, _verified(_jpeg()), _Detector([PlateBox(5, 5, 40, 10, 0.2)]), _Recogniser(), PARAMETERS)
    assert record.status == contracts.CROP_SCORED
    assert record.detections[0].plate is None


def test_readings_are_ranked_bounded_and_kept_above_the_ocr_floor() -> None:
    readings = [Reading("B", 0.6), Reading("D", 0.1), Reading("C", 0.9)]
    record = analyse_crop(OBSERVATION, _verified(_jpeg()), _Detector([PlateBox(5, 5, 40, 10, 0.9)]), _Recogniser(readings), PARAMETERS)
    plate = record.detections[0].plate
    assert plate is not None and plate.outcome == contracts.PLATE_READ
    # Every reading is retained in rank order; only those at or above the floor are kept as facts.
    assert [(item.rank, item.raw_text) for item in plate.readings] == [(0, "C"), (1, "B"), (2, "D")]
    track = summarise_track(LEASE.tracks[0].model_copy(update={"observations": (OBSERVATION,)}), (record,))
    kept = completion_tracks((track,), PARAMETERS)[0]["plateObservations"][0]["readings"]
    assert [item["rawText"] for item in kept] == ["C", "B"]


def test_ties_break_on_raw_text() -> None:
    readings = [Reading("B", 0.6), Reading("A", 0.6)]
    record = analyse_crop(OBSERVATION, _verified(_jpeg()), _Detector([PlateBox(5, 5, 40, 10, 0.9)]), _Recogniser(readings), PARAMETERS)
    assert [item.raw_text for item in record.detections[0].plate.readings] == ["A", "B"]


def test_a_plate_whose_best_reading_is_below_the_floor_is_unreadable_with_no_kept_reading() -> None:
    record = analyse_crop(OBSERVATION, _verified(_jpeg()), _Detector([PlateBox(5, 5, 40, 10, 0.9)]),
                          _Recogniser([Reading("KA0", 0.31)]), PARAMETERS)
    plate = record.detections[0].plate
    assert plate is not None and plate.outcome == contracts.PLATE_UNREADABLE
    assert [item.raw_text for item in plate.readings] == ["KA0"]  # still in the artefact
    track = summarise_track(LEASE.tracks[0].model_copy(update={"observations": (OBSERVATION,)}), (record,))
    assert completion_tracks((track,), PARAMETERS)[0]["plateObservations"][0]["readings"] == []
    assert track.texts == ()


@pytest.mark.parametrize(
    ("content", "detector", "recogniser", "reason"),
    [
        (b"not a jpeg", _Detector(), _Recogniser(), "decode_failed"),
        (None, _Detector(error=True), _Recogniser(), "detector_error"),
        (None, _Detector([PlateBox(190, 5, 40, 10, 0.9)]), _Recogniser(), "detector_error"),
        (None, _Detector([PlateBox(5, 5, 40, 10, 1.5)]), _Recogniser(), "detector_error"),
        (None, _Detector([PlateBox(5, 5, 40, 10, 0.9)]), _Recogniser(error=True), "ocr_error"),
        (None, _Detector([PlateBox(5, 5, 40, 10, 0.9)]), _Recogniser([Reading("K" * 33, 0.9)]), "ocr_output_invalid"),
        (None, _Detector([PlateBox(5, 5, 40, 10, 0.9)]), _Recogniser([Reading("KA\u000001", 0.9)]), "ocr_output_invalid"),
        (None, _Detector([PlateBox(5, 5, 40, 10, 0.9)]), _Recogniser([Reading("KA01", float("nan"))]), "ocr_output_invalid"),
    ],
)
def test_faults_abstain_the_crop_and_never_become_facts(content, detector, recogniser, reason) -> None:
    record = analyse_crop(OBSERVATION, _verified(content or _jpeg()), detector, recogniser, PARAMETERS)
    assert (record.status, record.reason) == (contracts.CROP_ABSTAINED, reason)
    assert all(detection.plate is None for detection in record.detections)
    assert list(record.plates()) == []


def test_a_track_with_no_scored_crop_is_unavailable_with_its_most_severe_reason() -> None:
    track = LEASE.tracks[0]
    first, second, third, fourth = track.observations
    abstained = analyse_crop(second, _verified(b"broken", second), _Detector(), _Recogniser(), PARAMETERS)
    crops = (excluded_crop(first), abstained, unavailable_crop(third, "evidence_missing"), excluded_crop(fourth))
    assert summarise_track(track, crops).reason == "evidence_missing"
    crops = (excluded_crop(first), abstained, excluded_crop(third), excluded_crop(fourth))
    assert summarise_track(track, crops).reason == "evidence_decode_failed"
    crops = tuple(excluded_crop(item) for item in track.observations)
    record = summarise_track(track, crops)
    assert (record.outcome, record.reason) == (contracts.TRACK_UNAVAILABLE, "no_accepted_evidence")
    empty = track.model_copy(update={"observations": ()})
    assert summarise_track(empty, ()).reason == "no_accepted_evidence"


def test_a_scored_crop_without_plates_is_analysed_not_unavailable() -> None:
    track = LEASE.tracks[0].model_copy(update={"observations": (OBSERVATION,)})
    record = analyse_crop(OBSERVATION, _verified(_jpeg()), _Detector(), _Recogniser(), PARAMETERS)
    summary = summarise_track(track, (record,))
    assert (summary.outcome, summary.reason, summary.texts) == (contracts.TRACK_ANALYSED, None, ())


def test_every_leased_crop_is_accounted_for_exactly_once() -> None:
    track = LEASE.tracks[0]
    with pytest.raises(OutputInvalid):
        summarise_track(track, tuple(excluded_crop(item) for item in track.observations[:-1]))
    with pytest.raises(OutputInvalid):
        unavailable_crop(OBSERVATION, "network_blip")


# --- The Development fixture ------------------------------------------------------------------------


def test_the_fixture_is_deterministic_and_produces_a_schema_shaped_artefact() -> None:
    detector, recogniser = _fixture(seed="mavi-stage4-pr3-fixture-v1", development_only=True, production_mode=False)
    tracks = []
    for lease_track in LEASE.tracks:
        crops = tuple(
            analyse_crop(item, _verified(_jpeg(320 + item.evidence_rank * 40, 240, 40 + 20 * item.evidence_rank + lease_track.track_id.int % 50), item),
                         detector, recogniser, PARAMETERS)
            for item in lease_track.observations
        )
        tracks.append(summarise_track(lease_track, crops))
    first = encode_predictions(LEASE, tuple(tracks))
    assert first == encode_predictions(LEASE, tuple(tracks))
    document = json.loads(first)
    assert document["schemaVersion"] == contracts.PREDICTIONS_SCHEMA_VERSION
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "contracts" / "schemas" / "plate-predictions-v1.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(document, schema)


@pytest.mark.parametrize(
    ("development_only", "production_mode", "seed", "code"),
    [
        (True, True, "seed", "plate_fixture_forbidden_in_production"),
        (False, False, "seed", "plate_fixture_forbidden_in_production"),
        (True, False, None, "plate_fixture_seed_required"),
    ],
)
def test_the_fixture_is_refused_outside_development(development_only, production_mode, seed, code) -> None:
    with pytest.raises(AdapterUnavailable, match=code):
        _fixture(seed=seed, development_only=development_only, production_mode=production_mode)


def test_an_unknown_adapter_is_refused() -> None:
    with pytest.raises(AdapterUnavailable, match="plate_adapter_unknown"):
        components_for(AdapterRequest("plate-detector", "some-model", {}), AdapterRequest("ocr", FIXTURE_ADAPTER_ID, {}),
                       parameters=replace(PARAMETERS, fixture_seed="seed"), development_only=True, production_mode=False)


def _fixture(*, seed, development_only, production_mode):
    return components_for(AdapterRequest("plate-detector", FIXTURE_ADAPTER_ID, {}), AdapterRequest("ocr", FIXTURE_ADAPTER_ID, {}),
                          parameters=replace(PARAMETERS, fixture_seed=seed), development_only=development_only,
                          production_mode=production_mode)
