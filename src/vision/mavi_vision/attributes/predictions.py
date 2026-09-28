"""Aggregation and canonical encoding of one analysis (ADR-013 §12–§14; S2b plan §11).

One in-memory result produces both the ``AttributePredictions`` artefact and the completion
body, so the artefact's decisions and the completion's final rows are the same values by
construction (the platform re-checks them value by value). The artefact is canonical JSON —
sorted keys, compact separators, ASCII only, no NaN, one trailing LF — and the platform
hashes the received bytes, never a re-serialisation.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Mapping
from uuid import UUID

from mavi_vision.attributes.contracts import (
    CONTROL_VERSION,
    MAXIMUM_PREDICTION_ARTIFACT_BYTES,
    OUTCOME_ANALYSED,
    OUTCOME_OBSERVED,
    OUTCOME_UNAVAILABLE,
    OUTCOME_UNKNOWN,
    PREDICTIONS_MEDIA_TYPE,
    PREDICTIONS_SCHEMA_VERSION,
    AttributeLease,
    LeaseTrack,
)
from mavi_vision.attributes.pipeline import AggregationPolicy, AttributeDefinition

# When no crop of a Track could be scored, the Track's reason is the most severe of its crops'.
_REASON_PRIORITY = ("evidence_integrity_failed", "evidence_missing", "evidence_decode_failed")


@dataclass(frozen=True, slots=True)
class ObservationResult:
    observation_id: UUID
    evidence_rank: int
    scores: Mapping[str, Mapping[str, float]] | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    attribute_type: str
    outcome: str
    value: str | None
    confidence: float | None
    supporting_observation_id: UUID | None


@dataclass(frozen=True, slots=True)
class TrackResult:
    track_id: UUID
    outcome: str
    reason: str | None
    observations: tuple[ObservationResult, ...]
    decisions: tuple[Decision, ...]


class OutputInvalid(ValueError):
    """The worker's own result cannot form a valid artefact: a terminal attempt failure."""


def aggregate_track(
    track: LeaseTrack,
    observations: tuple[ObservationResult, ...],
    attributes: tuple[AttributeDefinition, ...],
    policy: AggregationPolicy,
) -> TrackResult:
    """``mean-score-argmax``: the mean of each value's scores over the scored crops; the best
    value is Observed if its mean reaches the policy's minimum confidence, otherwise Unknown."""
    if policy.method != "mean-score-argmax":
        raise OutputInvalid("aggregation_method_unsupported")
    if not track.observations:
        return TrackResult(track.track_id, OUTCOME_UNAVAILABLE, "no_accepted_evidence", (), ())
    scored = [item for item in observations if item.scores is not None]
    if not scored:
        reasons = {item.reason for item in observations}
        reason = next(candidate for candidate in _REASON_PRIORITY if candidate in reasons)
        return TrackResult(track.track_id, OUTCOME_UNAVAILABLE, reason, observations, ())

    decisions: list[Decision] = []
    for attribute in sorted(attributes, key=lambda item: item.attribute_type):
        means: dict[str, float] = {}
        for value in attribute.values:
            values = [item.scores[attribute.attribute_type][value] for item in scored]  # type: ignore[index]
            if not all(math.isfinite(score) for score in values):
                raise OutputInvalid("attribute_score_not_finite")
            means[value] = sum(values) / len(values)
        # Ties resolve to the first value in schema (ordinal) order.
        best = max(attribute.values, key=lambda value: (means[value], -attribute.values.index(value)))
        confidence = means[best]
        if not 0.0 <= confidence <= 1.0:
            raise OutputInvalid("attribute_confidence_out_of_range")
        if confidence < policy.minimum_confidence:
            decisions.append(Decision(attribute.attribute_type, OUTCOME_UNKNOWN, None, None, None))
            continue
        # The supporting crop: the scored crop that scored the decided value highest; ties
        # resolve to the lower evidence rank.
        supporting = max(
            scored, key=lambda item: (item.scores[attribute.attribute_type][best], -item.evidence_rank)  # type: ignore[index]
        )
        decisions.append(Decision(attribute.attribute_type, OUTCOME_OBSERVED, best, confidence, supporting.observation_id))
    return TrackResult(track.track_id, OUTCOME_ANALYSED, None, observations, tuple(decisions))


def canonical_json(document: object) -> bytes:
    return (json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


def encode_predictions(lease: AttributeLease, tracks: tuple[TrackResult, ...]) -> bytes:
    identity = lease.identity
    document = {
        "aggregationPolicy": {
            "id": identity.aggregation_policy_id,
            "sha256": identity.aggregation_policy_sha256,
            "version": identity.aggregation_policy_version,
        },
        "analysisId": str(lease.analysis_id),
        "attributeSchema": {
            "id": identity.attribute_schema_id,
            "sha256": identity.attribute_schema_sha256,
            "version": identity.attribute_schema_version,
        },
        "identityFingerprint": identity.fingerprint,
        "schemaVersion": PREDICTIONS_SCHEMA_VERSION,
        "tracks": [
            {
                "decisions": [_decision(item) for item in track.decisions],
                "observations": [
                    {
                        "observationId": str(item.observation_id),
                        "reason": item.reason,
                        "scores": None if item.scores is None else {key: dict(value) for key, value in item.scores.items()},
                        "status": "scored" if item.scores is not None else "unavailable",
                    }
                    for item in track.observations
                ],
                "outcome": track.outcome,
                "reason": track.reason,
                "trackId": str(track.track_id),
            }
            for track in tracks
        ],
    }
    try:
        encoded = canonical_json(document)
    except ValueError as exc:
        raise OutputInvalid("attribute_predictions_not_encodable") from exc
    if len(encoded) > MAXIMUM_PREDICTION_ARTIFACT_BYTES:
        raise OutputInvalid("attribute_predictions_too_large")
    return encoded


def encode_completion(
    lease: AttributeLease,
    worker_id: str,
    provenance: Mapping[str, object],
    tracks: tuple[TrackResult, ...],
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
            "predictionArtifact": {
                "mediaType": PREDICTIONS_MEDIA_TYPE,
                "sizeBytes": prediction_size_bytes,
                "sha256": prediction_sha256,
            },
            "tracks": [
                {
                    "trackId": str(track.track_id),
                    "outcome": track.outcome,
                    "reason": track.reason,
                    "attributes": [_decision(item) for item in track.decisions],
                }
                for track in tracks
            ],
        },
    }
    return canonical_json(body)


def _decision(item: Decision) -> dict[str, object]:
    return {
        "attributeType": item.attribute_type,
        "confidence": item.confidence,
        "outcome": item.outcome,
        "supportingObservationId": None if item.supporting_observation_id is None else str(item.supporting_observation_id),
        "value": item.value,
    }


__all__ = [
    "Decision",
    "ObservationResult",
    "OutputInvalid",
    "TrackResult",
    "aggregate_track",
    "canonical_json",
    "encode_completion",
    "encode_predictions",
]
