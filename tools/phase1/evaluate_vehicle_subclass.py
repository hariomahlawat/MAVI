#!/usr/bin/env python3
"""Measure the detector-native vehicle subclass against MAVI's own labels (Stage 3, ADR-016).

Development measurement only: it is not a Task 17/18 acceptance criterion. Matching is
the Phase-1 evaluator's own (``evaluate_ground_truth.evaluate``), so a Track is scored
for its subclass exactly when it matched a ground-truth Vehicle event there. Only
events that carry a ``vehicleSubclass`` label are scored.

Each matched, labelled event has one of three outcomes:

- ``resolved``: the Track's vote resolved a subclass (correct or not);
- ``abstained``: the Track was processed by Stage 3 but its vote abstained;
- ``not-available``: the Track predates Stage 3 (no vocabulary recorded).

The report keeps the denominators explicit: coverage is resolved over matched, and
accuracy is stated both over resolved and over matched, so abstention is never hidden.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate_ground_truth as evaluator  # noqa: E402

SCHEMA_VERSION = "mavi-vehicle-subclass-evaluation-v1"
VOCABULARY_V1 = "mavi-vehicle-subclass-v1"
VALUES_V1 = evaluator.VEHICLE_SUBCLASS_VALUES_V1
UNDETERMINED = "undetermined"
NOT_AVAILABLE = "not-available"
_SUBCLASS_KEYS = ("objectSubclass", "objectSubclassVocabulary")


class SubclassEvaluationError(ValueError):
    pass


def _track_subclass(track: dict[str, Any]) -> str:
    """The Track's outcome label: a vocabulary value, ``undetermined`` or ``not-available``."""
    subclass = track.get("objectSubclass")
    vocabulary = track.get("objectSubclassVocabulary")
    if vocabulary is None:
        if subclass is not None:
            raise SubclassEvaluationError("track_subclass_without_vocabulary")
        return NOT_AVAILABLE
    if vocabulary != VOCABULARY_V1 or track.get("objectClass") != "Vehicle":
        raise SubclassEvaluationError("track_subclass_vocabulary_invalid")
    if subclass is None:
        return UNDETERMINED
    if subclass not in VALUES_V1:
        raise SubclassEvaluationError("track_subclass_invalid")
    return subclass


def evaluate(gt: dict[str, Any], tracks: list[dict[str, Any]], profile: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(tracks, list):
        raise SubclassEvaluationError("tracks_invalid")
    outcomes_by_track = {}
    plain_tracks = []
    for track in tracks:
        if not isinstance(track, dict):
            raise SubclassEvaluationError("tracks_invalid")
        outcomes_by_track[track.get("id")] = _track_subclass(track)
        plain_tracks.append({key: value for key, value in track.items() if key not in _SUBCLASS_KEYS})

    # The Phase-1 evaluator validates everything else and owns the matching.
    phase1 = evaluator.evaluate(gt, plain_tracks, profile)
    labels = {event["eventId"]: event["vehicleSubclass"] for event in gt["events"] if "vehicleSubclass" in event}
    matched = {item["eventId"]: item["trackId"] for item in phase1["matching"] if item["eventId"] in labels}

    columns = (*VALUES_V1, UNDETERMINED, NOT_AVAILABLE)
    confusion = {truth: dict.fromkeys(columns, 0) for truth in VALUES_V1}
    for event_id, track_id in matched.items():
        confusion[labels[event_id]][outcomes_by_track[track_id]] += 1

    resolved = sum(confusion[t][p] for t in VALUES_V1 for p in VALUES_V1)
    correct = sum(confusion[v][v] for v in VALUES_V1)
    abstained = sum(confusion[t][UNDETERMINED] for t in VALUES_V1)
    not_available = sum(confusion[t][NOT_AVAILABLE] for t in VALUES_V1)
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
        "labelledVehicleEvents": len(labels),
        "matchedLabelledEvents": len(matched),
        "unmatchedLabelledEvents": len(labels) - len(matched),
        "outcomes": {"resolved": resolved, "abstained": abstained, "notAvailable": not_available},
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
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        print("evaluate_vehicle_subclass: output already exists; refusing to overwrite", file=sys.stderr)
        return 2
    try:
        gt = json.loads(args.ground_truth.read_text(encoding="utf-8"))
        tracks = json.loads(args.tracks.read_text(encoding="utf-8"))
        profile = json.loads(args.profile.read_text(encoding="utf-8"))
        report = evaluate(gt, tracks, profile)
    except (OSError, json.JSONDecodeError, evaluator.EvaluationError, SubclassEvaluationError) as exc:
        print(f"evaluate_vehicle_subclass: {exc}", file=sys.stderr)
        return 2
    report["inputs"] = {
        "groundTruthSha256": _sha256(args.ground_truth),
        "tracksSha256": _sha256(args.tracks),
        "profileSha256": _sha256(args.profile),
    }
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
