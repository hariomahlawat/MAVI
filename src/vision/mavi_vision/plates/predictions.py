"""Canonical encoding of one plate analysis: the ``PlatePredictions`` artefact and the completion body.

Both come from the same ``TrackRecord`` values (``pipeline.py``). The artefact is canonical JSON —
sorted keys, compact separators, ASCII only, no NaN, one trailing LF — and the platform hashes the
received bytes, never a re-serialisation (ADR-013 implementation amendment 2026-09-28, item 6).
Shapes: ``contracts/schemas/plate-predictions-v1.schema.json`` and ``plate-complete-v1.schema.json``.
"""

from __future__ import annotations

import json
from typing import Mapping

from mavi_vision.plates.contracts import (
    CONTROL_VERSION,
    MAXIMUM_COMPLETION_REQUEST_BYTES,
    MAXIMUM_PREDICTION_ARTIFACT_BYTES,
    NORMALISATION_ID,
    PREDICTIONS_MEDIA_TYPE,
    PREDICTIONS_SCHEMA_VERSION,
    PlateLease,
)
from mavi_vision.plates.parameters import PlateParameters
from mavi_vision.plates.pipeline import CropRecord, OutputInvalid, TrackRecord, kept_readings


def canonical_json(document: object) -> bytes:
    return (json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


def _crop(crop: CropRecord) -> dict[str, object]:
    return {
        "cropHeight": crop.height,
        "cropWidth": crop.width,
        "detections": [
            {
                "box": list(detection.box),
                "plate": None
                if detection.plate is None
                else {
                    "outcome": detection.plate.outcome,
                    "plateIndex": detection.plate.plate_index,
                    "readings": [
                        {"confidence": item.confidence, "rank": item.rank, "rawLineCount": item.raw_line_count, "rawText": item.raw_text}
                        for item in detection.plate.readings
                    ],
                },
                "score": detection.score,
            }
            for detection in crop.detections
        ],
        "evidenceRank": crop.evidence_rank,
        "observationId": str(crop.observation_id),
        "reason": crop.reason,
        "role": crop.role,
        "status": crop.status,
    }


def encode_predictions(lease: PlateLease, tracks: tuple[TrackRecord, ...]) -> bytes:
    identity = lease.identity
    document = {
        "analysisId": str(lease.analysis_id),
        "identityFingerprint": identity.fingerprint,
        "normalisation": {"id": NORMALISATION_ID, "sha256": identity.normalisation.sha256},
        "parametersSha256": identity.parameters_sha256,
        "pipeline": {"id": identity.pipeline_id, "version": identity.pipeline_version},
        "schemaVersion": PREDICTIONS_SCHEMA_VERSION,
        "summaryPolicy": {
            "id": identity.summary_policy.id,
            "sha256": identity.summary_policy.sha256,
            "version": identity.summary_policy.version,
        },
        "tracks": [
            {
                "crops": [_crop(crop) for crop in track.crops],
                "outcome": track.outcome,
                "reason": track.reason,
                "texts": [
                    {
                        "bestPlate": {"observationId": str(text.best_observation_id), "plateIndex": text.best_plate_index},
                        "maxConfidence": text.max_confidence,
                        "supportCount": text.support_count,
                    }
                    for text in track.texts
                ],
                "trackId": str(track.track_id),
            }
            for track in tracks
        ],
    }
    try:
        encoded = canonical_json(document)
    except ValueError as exc:
        raise OutputInvalid("plate_predictions_not_encodable") from exc
    if len(encoded) > MAXIMUM_PREDICTION_ARTIFACT_BYTES:
        raise OutputInvalid("plate_predictions_too_large")
    return encoded


def completion_tracks(tracks: tuple[TrackRecord, ...], parameters: PlateParameters) -> list[dict[str, object]]:
    """The completion's relational facts: kept readings carry raw text only (the platform normalises)."""
    result: list[dict[str, object]] = []
    for track in tracks:
        observations = []
        for crop in track.crops:
            for detection, plate in crop.plates():
                x, y, width, height = detection.box
                observations.append({
                    "sourceObservationId": str(crop.observation_id),
                    "plateIndex": plate.plate_index,
                    "box": {"x": x, "y": y, "width": width, "height": height},
                    "cropWidth": crop.width,
                    "cropHeight": crop.height,
                    "detectorConfidence": detection.score,
                    "outcome": plate.outcome,
                    "readings": [
                        {"rank": item.rank, "rawText": item.raw_text, "rawLineCount": item.raw_line_count, "confidence": item.confidence}
                        for item in kept_readings(plate, parameters)
                    ],
                })
        result.append({
            "trackId": str(track.track_id),
            "outcome": track.outcome,
            "reason": track.reason,
            "plateObservations": observations,
            "texts": [
                {
                    "bestPlate": {"sourceObservationId": str(text.best_observation_id), "plateIndex": text.best_plate_index},
                    "supportCount": text.support_count,
                    "maxConfidence": text.max_confidence,
                }
                for text in track.texts
            ],
        })
    return result


def encode_completion(
    lease: PlateLease,
    worker_id: str,
    provenance: Mapping[str, object],
    tracks: tuple[TrackRecord, ...],
    parameters: PlateParameters,
    *,
    prediction_size_bytes: int,
    prediction_sha256: str,
) -> bytes:
    body = {
        "schemaVersion": CONTROL_VERSION,
        "analysisId": str(lease.analysis_id),
        "workerId": worker_id,
        "attemptCount": lease.attempt_count,
        "provenance": dict(provenance),
        "payload": {
            "predictionArtifact": {"mediaType": PREDICTIONS_MEDIA_TYPE, "sizeBytes": prediction_size_bytes, "sha256": prediction_sha256},
            "tracks": completion_tracks(tracks, parameters),
        },
    }
    encoded = canonical_json(body)
    if len(encoded) > MAXIMUM_COMPLETION_REQUEST_BYTES:
        raise OutputInvalid("plate_completion_too_large")
    return encoded
