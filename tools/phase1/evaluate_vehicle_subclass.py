#!/usr/bin/env python3
"""Measure the detector-native vehicle subclass against MAVI's own labels (Stage 3, ADR-016).

Development measurement only: it is not a Task 17/18 acceptance criterion. Matching is
the Phase-1 evaluator's own (``evaluate_ground_truth.evaluate``), so a Track is scored
for its subclass exactly when it matched a ground-truth Vehicle event there. Only
events that carry a ``vehicleSubclass`` label are scored.

**Attribution.** A measurement is bound to what produced the predictions, using the
provenance MAVI already records:

- every Track names its ``processingRunId``, and that run's attestation
  (``GET /api/processing-runs/{id}/attestation``) must be supplied;
- all attested runs must share one producer identity (model, checkpoint, resolved
  config, pipeline profile, runtime profile, qualification, component binding, MAVI
  commit), and each must have contributed Tracks;
- the attested pipeline profile must be the profile under measurement (its file is
  hashed here);
- every Vehicle Track must carry the v1 vocabulary and the source
  ``detector-native:<its run's attested pipelineProfileSha256>``; Person Tracks carry
  no subclass data.

Anything absent, malformed or inconsistent fails closed. The subclass members are
removed only at the boundary into the Phase-1 Track matcher, which knows nothing of
them. The report records the producer identity, the runs and the hash of every input.

Each matched, labelled event is ``resolved`` (the vote resolved a subclass, correct or
not) or ``abstained``. Coverage is resolved over matched, and accuracy is stated both
over resolved and over matched, so abstention is never hidden.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate_ground_truth as evaluator  # noqa: E402

SCHEMA_VERSION = "mavi-vehicle-subclass-evaluation-v2"
VOCABULARY_V1 = "mavi-vehicle-subclass-v1"
SOURCE_PREFIX = "detector-native:"
VALUES_V1 = evaluator.VEHICLE_SUBCLASS_VALUES_V1
UNDETERMINED = "undetermined"
_SUBCLASS_KEYS = ("objectSubclass", "objectSubclassVocabulary", "objectSubclassSource")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
# Attestation members that identify the producer; every attested run must agree on all.
_PRODUCER_SHA256 = ("modelManifestSha256", "checkpointSha256", "resolvedConfigSha256",
                    "pipelineProfileSha256", "runtimeProfileSha256")
_PRODUCER_OPTIONAL_SHA256 = ("qualificationSha256", "componentBindingSha256")
# maviCommit too: the vote is code as well as configuration.
_PRODUCER_TEXT = ("modelId", "modelVersion", "pipelineProfileId", "pipelineProfileVersion",
                  "runtimeProfileId", "runtimeVariant", "verificationStatus", "maviCommit")


class SubclassEvaluationError(ValueError):
    pass


def _text(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != "" and value == value.strip()


def _validate_attestation(attestation: Any) -> dict[str, Any]:
    if not isinstance(attestation, dict):
        raise SubclassEvaluationError("attestation_invalid")
    for key in ("processingRunId", "videoAssetId", *_PRODUCER_TEXT):
        if not _text(attestation.get(key)):
            raise SubclassEvaluationError(f"attestation_field_invalid:{key}")
    for key in _PRODUCER_SHA256:
        if not isinstance(attestation.get(key), str) or not _SHA256.fullmatch(attestation[key]):
            raise SubclassEvaluationError(f"attestation_field_invalid:{key}")
    for key in _PRODUCER_OPTIONAL_SHA256:
        value = attestation.get(key)
        if value is not None and (not isinstance(value, str) or not _SHA256.fullmatch(value)):
            raise SubclassEvaluationError(f"attestation_field_invalid:{key}")
    return attestation


def _producer(attestations: list[dict[str, Any]], measured_profile_sha256: str) -> dict[str, Any]:
    if not attestations:
        raise SubclassEvaluationError("attestation_missing")
    runs = [_validate_attestation(item)["processingRunId"] for item in attestations]
    if len(set(runs)) != len(runs):
        raise SubclassEvaluationError("attestation_run_duplicate")
    keys = (*_PRODUCER_TEXT, *_PRODUCER_SHA256, *_PRODUCER_OPTIONAL_SHA256)
    identities = {tuple(item.get(key) for key in keys) for item in attestations}
    if len(identities) != 1:
        raise SubclassEvaluationError("attestation_producers_differ")
    producer = {key: attestations[0].get(key) for key in keys}
    if producer["pipelineProfileSha256"] != measured_profile_sha256:
        raise SubclassEvaluationError("attestation_pipeline_profile_mismatch")
    producer["subclassSource"] = SOURCE_PREFIX + measured_profile_sha256
    producer["processingRunIds"] = sorted(runs)
    return producer


def _track_outcome(track: dict[str, Any], runs: dict[str, dict[str, Any]], source: str) -> str | None:
    """The Track's outcome label (a v1 value or ``undetermined``); ``None`` for a Person."""
    run_id = track.get("processingRunId")
    run = runs.get(run_id) if isinstance(run_id, str) else None
    if run is None:
        raise SubclassEvaluationError("track_run_not_attested")
    if track.get("videoAssetId") != run["videoAssetId"]:
        raise SubclassEvaluationError("track_video_not_the_attested_run")
    subclass = track.get("objectSubclass")
    vocabulary = track.get("objectSubclassVocabulary")
    track_source = track.get("objectSubclassSource")
    if track.get("objectClass") != "Vehicle":
        if subclass is not None or vocabulary is not None or track_source is not None:
            raise SubclassEvaluationError("track_subclass_on_person")
        return None
    if vocabulary is None or track_source is None:
        raise SubclassEvaluationError("track_subclass_provenance_missing")
    if vocabulary != VOCABULARY_V1:
        raise SubclassEvaluationError("track_subclass_vocabulary_invalid")
    if track_source != source:
        raise SubclassEvaluationError("track_subclass_source_mismatch")
    if subclass is None:
        return UNDETERMINED
    if subclass not in VALUES_V1:
        raise SubclassEvaluationError("track_subclass_invalid")
    return subclass


def evaluate(
    gt: dict[str, Any],
    tracks: list[dict[str, Any]],
    profile: dict[str, Any],
    attestations: list[dict[str, Any]],
    measured_profile_sha256: str,
) -> dict[str, Any]:
    if not isinstance(tracks, list) or not all(isinstance(track, dict) for track in tracks):
        raise SubclassEvaluationError("tracks_invalid")
    if not isinstance(attestations, list):
        raise SubclassEvaluationError("attestation_invalid")
    producer = _producer(attestations, measured_profile_sha256)
    runs = {item["processingRunId"]: item for item in attestations}
    if not all(isinstance(track.get("id"), str) for track in tracks):
        raise SubclassEvaluationError("tracks_invalid")
    outcomes_by_track = {
        track["id"]: _track_outcome(track, runs, producer["subclassSource"]) for track in tracks
    }
    # Every attested run must have contributed Tracks: the report names exactly its producers.
    if set(runs) != {track["processingRunId"] for track in tracks}:
        raise SubclassEvaluationError("attestation_without_tracks")
    # The boundary into the Phase-1 matcher: it validates everything else and owns matching.
    plain_tracks = [{key: value for key, value in track.items() if key not in _SUBCLASS_KEYS} for track in tracks]
    phase1 = evaluator.evaluate(gt, plain_tracks, profile)
    labels = {event["eventId"]: event["vehicleSubclass"] for event in gt["events"] if "vehicleSubclass" in event}
    matched = {item["eventId"]: item["trackId"] for item in phase1["matching"] if item["eventId"] in labels}

    columns = (*VALUES_V1, UNDETERMINED)
    confusion = {truth: dict.fromkeys(columns, 0) for truth in VALUES_V1}
    for event_id, track_id in matched.items():
        confusion[labels[event_id]][outcomes_by_track[track_id]] += 1

    resolved = sum(confusion[t][p] for t in VALUES_V1 for p in VALUES_V1)
    correct = sum(confusion[v][v] for v in VALUES_V1)
    abstained = sum(confusion[t][UNDETERMINED] for t in VALUES_V1)
    per_subclass = {}
    for value in VALUES_V1:
        support = sum(confusion[value].values())
        predicted = sum(confusion[t][value] for t in VALUES_V1)
        per_subclass[value] = {
            "labelledEvents": sum(1 for label in labels.values() if label == value),
            "matchedEvents": support,
            "resolved": sum(confusion[value][p] for p in VALUES_V1),
            "correct": confusion[value][value],
            "recallOverMatched": evaluator._metric(confusion[value][value], support),
            "precisionOverPredicted": evaluator._metric(confusion[value][value], predicted),
        }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "vocabulary": VOCABULARY_V1,
        "semantics": "detector-reported vehicle type; development measurement, not an acceptance criterion",
        "producer": producer,
        "labelledVehicleEvents": len(labels),
        "matchedLabelledEvents": len(matched),
        "unmatchedLabelledEvents": len(labels) - len(matched),
        "outcomes": {"resolved": resolved, "abstained": abstained},
        "correct": correct,
        "coverageOverMatched": evaluator._metric(resolved, len(matched)),
        "accuracyOverResolved": evaluator._metric(correct, resolved),
        "accuracyOverMatched": evaluator._metric(correct, len(matched)),
        "confusion": confusion,
        "perSubclass": per_subclass,
        "matching": [{"eventId": event_id, "trackId": matched[event_id]} for event_id in sorted(matched)],
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--tracks", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True, help="Phase-1 acceptance profile (matching rules)")
    parser.add_argument("--pipeline-profile", type=Path, required=True, help="the pipeline profile under measurement")
    parser.add_argument("--attestation", type=Path, action="append", required=True,
                        help="a processing-run attestation; one per run the Tracks came from")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        print("evaluate_vehicle_subclass: output already exists; refusing to overwrite", file=sys.stderr)
        return 2
    try:
        gt = json.loads(args.ground_truth.read_text(encoding="utf-8"))
        tracks = json.loads(args.tracks.read_text(encoding="utf-8"))
        profile = json.loads(args.profile.read_text(encoding="utf-8"))
        attestations = [json.loads(path.read_text(encoding="utf-8")) for path in args.attestation]
        pipeline_profile_sha256 = _sha256(args.pipeline_profile)
        report = evaluate(gt, tracks, profile, attestations, pipeline_profile_sha256)
    except (OSError, json.JSONDecodeError, evaluator.EvaluationError, SubclassEvaluationError) as exc:
        print(f"evaluate_vehicle_subclass: {exc}", file=sys.stderr)
        return 2
    report["inputs"] = {
        "groundTruthSha256": _sha256(args.ground_truth),
        "tracksSha256": _sha256(args.tracks),
        "profileSha256": _sha256(args.profile),
        "pipelineProfileSha256": pipeline_profile_sha256,
        "attestationSha256": sorted(_sha256(path) for path in args.attestation),
    }
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
