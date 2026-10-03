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

**Track-label mode** (S3.2 plan T2; ``--track-labels``): human labels attach to MAVI's own
Tracks, so truth joins by ``(processingRunId, trackId)`` from frozen label files and never goes
through event matching. It produces ``vehicle-subclass-measurement-v1``: subclass classification
*given that MAVI produced the Track*, from T1 exports, T3 samples and T5 labels/adjudications.

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


# Track-label mode (Stage 3, S3.2 plan T2)
#
# Human labels attach to MAVI's own Tracks, so truth joins by (processingRunId, trackId)
# straight from frozen label files; the event matcher above is never involved. The result
# measures subclass classification *given that MAVI produced the Track*.

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stage3"))
import artefacts as s32  # noqa: E402

TRACK_RESULT_SCHEMA = "vehicle-subclass-measurement-v1"


def _fraction(numerator: int, denominator: int) -> dict[str, Any]:
    """An exact fraction with its denominator; the value is ``None`` when undefined."""
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None}


def _human_label(entry: dict[str, Any]) -> tuple[str, str | None]:
    return entry["label"], entry.get("unknownReason")


def _section(entries: list[dict[str, Any]], reliability: dict[str, Any] | None, sample_shas: list[str]) -> dict[str, Any]:
    """Every metric of one set of labelled Tracks. Human ``unknown`` is reported, never scored;
    MAVI's abstention (``undetermined``) is never a correct classification."""
    from fractions import Fraction

    classes, outcomes = s32.CLASSES, s32.OUTCOMES
    confusion = {truth: dict.fromkeys(outcomes, 0) for truth in classes}
    unknown_row = dict.fromkeys(outcomes, 0)
    human_unknown = dict.fromkeys(s32.UNKNOWN_REASONS, 0)
    for entry in entries:
        if entry["label"] == s32.UNKNOWN:
            human_unknown[entry["unknownReason"]] += 1
            unknown_row[entry["outcome"]] += 1
        else:
            confusion[entry["label"]][entry["outcome"]] += 1
    evaluable = sum(sum(row.values()) for row in confusion.values())
    abstained = sum(row[s32.UNDETERMINED] for row in confusion.values())
    resolved = evaluable - abstained
    correct = sum(confusion[c][c] for c in classes)
    per_class = {}
    for c in classes:
        support = sum(confusion[c].values())
        predicted = sum(confusion[t][c] for t in classes)
        per_class[c] = {"support": support, "predicted": predicted, "correct": confusion[c][c],
                        "precision": _fraction(confusion[c][c], predicted),
                        "recall": _fraction(confusion[c][c], support)}
    supported = [c for c in classes if per_class[c]["support"] > 0]
    macro = sum((Fraction(per_class[c]["correct"], per_class[c]["support"]) for c in supported), Fraction(0))
    macro = macro / len(supported) if supported else None
    metrics = {
        "labelledTracks": len(entries),
        "humanUnknown": human_unknown,
        "evaluableTracks": evaluable,
        "resolved": resolved,
        "abstained": abstained,
        "coverageOverEvaluable": _fraction(resolved, evaluable),
        "confusion": confusion,
        "unknownRow": unknown_row,
        "perClass": per_class,
        "accuracyOverEvaluable": _fraction(correct, evaluable),
        "accuracyOverResolved": _fraction(correct, resolved),
        "macroRecallOverClassesWithSupport": {
            "classes": supported,
            "numerator": macro.numerator if macro is not None else 0,
            "denominator": macro.denominator if macro is not None else 0,
            "value": float(macro) if macro is not None else None,
        },
    }
    return {
        "sampleSha256s": sorted(sample_shas),
        "metrics": metrics,
        "clusters": _clusters(entries),
        "errorReferences": sorted(
            ({"itemId": e["itemId"], "packSha256": e["packSha256"], "processingRunId": e["processingRunId"],
              "trackId": e["trackId"], "label": e["label"], "predicted": e["outcome"]}
             for e in entries if e["label"] != s32.UNKNOWN and e["outcome"] != e["label"]),
            key=lambda r: (r["processingRunId"], r["trackId"])),
        "reliability": reliability,
    }


def _clusters(entries: list[dict[str, Any]]) -> dict[str, Any]:
    def counts(group: list[dict[str, Any]]) -> dict[str, Any]:
        confusion = {t: dict.fromkeys(s32.OUTCOMES, 0) for t in s32.CLASSES}
        for e in group:
            if e["label"] != s32.UNKNOWN:
                confusion[e["label"]][e["outcome"]] += 1
        evaluable = [e for e in group if e["label"] != s32.UNKNOWN]
        return {"labelledTracks": len(group), "evaluableTracks": len(evaluable),
                "resolved": sum(1 for e in evaluable if e["outcome"] != s32.UNDETERMINED),
                "correct": sum(1 for e in evaluable if e["outcome"] == e["label"]), "confusion": confusion}

    videos: dict[str, list[dict[str, Any]]] = {}
    cameras: dict[str, list[dict[str, Any]]] = {}
    for e in entries:
        videos.setdefault(e["processingRunId"], []).append(e)
        cameras.setdefault(e["cameraCode"], []).append(e)
    return {
        "videoCount": len(videos),
        "cameraCount": len(cameras),
        "perVideo": [{"processingRunId": run, "videoAssetId": group[0]["videoAssetId"], "cameraCode": group[0]["cameraCode"],
                      **counts(group)} for run, group in sorted(videos.items())],
        "perCamera": [{"cameraCode": code, "videoCount": len({e["processingRunId"] for e in group}), **counts(group)}
                      for code, group in sorted(cameras.items())],
    }


def _reliability(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any] | None:
    """Agreement between the two original frozen label files (never the adjudication's copies)."""
    if not pairs:
        return None
    matrix = {first: dict.fromkeys(s32.LABELS, 0) for first in s32.LABELS}
    for primary, overlap in pairs:
        matrix[primary["label"]][overlap["label"]] += 1
    return {"overlapTracks": len(pairs),
            "labelAgreements": sum(1 for p, o in pairs if p["label"] == o["label"]),
            "exactAgreements": sum(1 for p, o in pairs if _human_label(p) == _human_label(o)),
            "disagreement": matrix}


def _sample_key(selection: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {(item["processingRunId"], item["trackId"]) for item in selection}


def evaluate_track_labels(
    samples: list[tuple[dict[str, Any], str]],
    primary_labels: list[tuple[dict[str, Any], str]],
    overlap_labels: list[tuple[dict[str, Any], str]],
    adjudications: list[tuple[dict[str, Any], str]],
    exports: dict[str, Any],
    measured_profile_sha256: str,
) -> dict[str, Any]:
    """The Track-conditional measurement over one pilot, its same-design continuations and any
    supplemental batches. Inputs are (document, SHA-256 of its exact bytes); exports are T1
    exports keyed by the SHA-256 of their exact bytes."""
    require = s32.require

    # Producer and per-Track provenance: the S3.1 checks, unchanged.
    producer = _producer([export.attestation for export in exports.values()], measured_profile_sha256)
    runs = {export.run_id: export.attestation for export in exports.values()}
    by_run = {export.run_id: export for export in exports.values()}
    outcomes: dict[tuple[str, str], str | None] = {}
    for export in exports.values():
        for track in export.tracks:
            subject = {**track, "processingRunId": export.run_id, "videoAssetId": export.video["videoAssetId"]}
            outcomes[(export.run_id, track["id"])] = _track_outcome(subject, runs, producer["subclassSource"])

    # Pairing by hash: labels to samples, overlap to primary, adjudication to both.
    sample_by_sha = dict((sha, doc) for doc, sha in samples)
    require(len(sample_by_sha) == len(samples), "batch_pairing_invalid:duplicate_sample")
    primary_by_sample: dict[str, tuple[dict[str, Any], str]] = {}
    for doc, sha in primary_labels:
        require(doc["viewKind"] == "primary", "overlap_pack_not_derived:primary_view")
        require(doc["sampleSha256"] in sample_by_sha, "batch_pairing_invalid:labels_sample")
        require(doc["sampleSha256"] not in primary_by_sample, "batch_pairing_invalid:two_primaries")
        primary_by_sample[doc["sampleSha256"]] = (doc, sha)
    require(set(primary_by_sample) == set(sample_by_sha), "batch_pairing_invalid:sample_without_labels")
    overlap_by_sample: dict[str, tuple[dict[str, Any], str]] = {}
    for doc, sha in overlap_labels:
        require(doc["viewKind"] == "overlap", "overlap_pack_not_derived:overlap_view")
        primary = primary_by_sample.get(doc["sampleSha256"])
        require(primary is not None and doc["parentPackSha256"] == primary[0]["packSha256"], "overlap_pack_not_derived")
        require(doc["sampleSha256"] not in overlap_by_sample, "batch_pairing_invalid:two_overlaps")
        overlap_by_sample[doc["sampleSha256"]] = (doc, sha)
    adjudication_by_sample: dict[str, tuple[dict[str, Any], str]] = {}
    for doc, sha in adjudications:
        matches = [s for s, (o, osha) in overlap_by_sample.items()
                   if doc["overlapLabelsSha256"] == osha and doc["primaryLabelsSha256"] == primary_by_sample[s][1]]
        require(len(matches) == 1, "batch_pairing_invalid:adjudication")
        require(matches[0] not in adjudication_by_sample, "batch_pairing_invalid:two_adjudications")
        adjudication_by_sample[matches[0]] = (doc, sha)
    require(set(adjudication_by_sample) == set(overlap_by_sample), "adjudication_missing")

    requirements = {sample["requirements"]["sha256"] for sample in sample_by_sha.values()}
    require(len(requirements) == 1, "requirements_mismatch")

    # Final truth per batch.
    batches: dict[str, dict[str, Any]] = {}
    used_exports: set[str] = set()
    for sample_sha, sample in sample_by_sha.items():
        primary, primary_sha = primary_by_sample[sample_sha]
        overlap, overlap_sha = overlap_by_sample.get(sample_sha, (None, None))
        adjudication, adjudication_sha = adjudication_by_sample.get(sample_sha, (None, None))
        require(sorted(sample["exportSha256s"]) == sorted(primary["exportSha256s"]), "labels_export_mismatch")
        for export_sha in sample["exportSha256s"]:
            require(export_sha in exports, "export_hash_mismatch")
            used_exports.add(export_sha)
        guide = primary["labelingGuideSha256"]
        if overlap is not None:
            require(sorted(overlap["exportSha256s"]) == sorted(primary["exportSha256s"]), "labels_export_mismatch")
            require(overlap["labelingGuideSha256"] == guide, "labeling_guide_mismatch")

        def resolve(labels: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
            decisions: dict[tuple[str, str], dict[str, Any]] = {}
            for d in labels["decisions"]:
                key = (d["processingRunId"], d["trackId"])
                require(key not in decisions, "labels_duplicate_decision")
                export = by_run.get(d["processingRunId"])
                require(export is not None and export.sha256 in labels["exportSha256s"]
                        and export.track(d["trackId"]) is not None, "labels_track_not_exported")
                require(export.track(d["trackId"])["objectClass"] == "Vehicle", "labels_track_not_vehicle")
                require(d["videoSourceSha256"] == export.video["sourceSha256"], "labels_video_mismatch")
                decisions[key] = d
            return decisions

        primary_decisions = resolve(primary)
        require(set(primary_decisions) == _sample_key(sample["selected"]), "labels_sample_mismatch")
        truth = {key: {"label": d["label"], **({"unknownReason": d["unknownReason"]} if "unknownReason" in d else {})}
                 for key, d in primary_decisions.items()}
        pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
        if overlap is not None:
            overlap_decisions = resolve(overlap)
            require(set(overlap_decisions) == _sample_key(sample["overlapSelected"]), "labels_sample_mismatch:overlap")
            items = {(i["processingRunId"], i["trackId"]): i for i in adjudication["items"]}
            require(set(items) == set(overlap_decisions), "adjudication_not_from_labels:items")
            for key, item in items.items():
                first = {k: v for k, v in primary_decisions[key].items() if k in ("label", "unknownReason")}
                second = {k: v for k, v in overlap_decisions[key].items() if k in ("label", "unknownReason")}
                require(item["primary"] == first and item["overlap"] == second, "adjudication_not_from_labels")
                final = {"label": item["adjudicatedLabel"],
                         **({"unknownReason": item["adjudicatedUnknownReason"]} if "adjudicatedUnknownReason" in item else {})}
                carried = first == second
                require((item["resolution"] == "carried") == carried and (not carried or final == first),
                        "adjudication_not_from_labels:resolution")
                truth[key] = final
                pairs.append((first, second))

        entries = []
        for key, final in truth.items():
            export = by_run[key[0]]
            entries.append({"processingRunId": key[0], "trackId": key[1], "itemId": primary_decisions[key]["itemId"],
                            "packSha256": primary["packSha256"], "label": final["label"],
                            "unknownReason": final.get("unknownReason"), "outcome": outcomes[key],
                            "cameraCode": export.video["cameraCode"], "videoAssetId": export.video["videoAssetId"]})
        batches[sample_sha] = {
            "sample": sample, "entries": entries, "pairs": pairs, "guide": guide,
            "inputs": {"sampleSha256": sample_sha, "designKind": sample["design"]["kind"], "labelingGuideSha256": guide,
                       "primaryPackSha256": primary["packSha256"], "primaryLabelsSha256": primary_sha,
                       "overlapPackSha256": overlap["packSha256"] if overlap else None,
                       "overlapLabelsSha256": overlap_sha, "adjudicationSha256": adjudication_sha},
        }
    require(used_exports == set(exports), "export_unused")

    # Batch design: one pilot; continuations pool only when the design is the pilot's.
    pilots = [sha for sha, b in batches.items()
              if b["sample"]["design"]["kind"] == "continuation" and not b["sample"]["design"]["parentSampleSha256s"]]
    require(len(pilots) == 1, "batch_pilot_invalid")
    pilot_sha = pilots[0]
    pilot = batches[pilot_sha]["sample"]
    seen: dict[tuple[str, str], str] = {}
    for sha, batch in batches.items():
        for entry in batch["entries"]:
            key = (entry["processingRunId"], entry["trackId"])
            require(key not in seen, "batch_tracks_overlap")
            seen[key] = sha
    continuations = []
    supplemental = []
    for sha, batch in sorted(batches.items()):
        if sha == pilot_sha:
            continue
        design = batch["sample"]["design"]
        if design["kind"] == "supplemental":
            supplemental.append(sha)
            continue
        same = (pilot_sha in design["parentSampleSha256s"]
                and design["releaseId"] == pilot["design"]["releaseId"]
                and batch["sample"]["releaseRecordSha256"] == pilot["releaseRecordSha256"]
                and design["samplingAlgorithm"] == pilot["design"]["samplingAlgorithm"]
                and design["parameters"] == pilot["design"]["parameters"]
                and batch["sample"]["requirements"]["sha256"] == pilot["requirements"]["sha256"]
                and sorted(batch["sample"]["exportSha256s"]) == sorted(pilot["exportSha256s"]))
        require(same, "continuation_design_mismatch")
        require(batch["guide"] == batches[pilot_sha]["guide"], "labeling_guide_mismatch")
        continuations.append(sha)

    def batch_section(sha: str) -> dict[str, Any]:
        batch = batches[sha]
        design = batch["sample"]["design"]
        return {"sampleSha256": sha,
                "design": {"kind": design["kind"], "parentSampleSha256s": sorted(design["parentSampleSha256s"])},
                **_section(batch["entries"], _reliability(batch["pairs"]), [sha])}

    primary_shas = [pilot_sha, *continuations]
    primary_entries = [e for sha in primary_shas for e in batches[sha]["entries"]]
    primary_pairs = [p for sha in primary_shas for p in batches[sha]["pairs"]]
    ordered = [*primary_shas, *supplemental]
    result = {
        "schemaVersion": TRACK_RESULT_SCHEMA,
        "scope": s32.SCOPE,
        "labelVocabulary": s32.LABEL_VOCABULARY,
        "subclassVocabulary": VOCABULARY_V1,
        "producer": producer,
        "inputs": {
            "measuredProfileSha256": measured_profile_sha256,
            "requirementsSha256": requirements.pop(),
            "exportSha256s": sorted(exports),
            "sourceVideoSha256s": sorted({export.video["sourceSha256"] for export in exports.values()}),
            "batches": [batches[sha]["inputs"] for sha in ordered],
        },
        "primary": _section(primary_entries, _reliability(primary_pairs), primary_shas),
        "batches": [batch_section(sha) for sha in primary_shas],
        "supplemental": [batch_section(sha) for sha in supplemental],
    }
    s32.validate(result, TRACK_RESULT_SCHEMA, "measurement_invalid")
    return result


def read_track_label_inputs(args: argparse.Namespace) -> dict[str, Any]:
    """Reads every input by its exact bytes; a document's identity is the SHA-256 of those bytes."""
    def read(paths: list[Path], schema: str, code: str) -> list[tuple[dict[str, Any], str]]:
        documents = []
        for path in paths:
            document, _, sha = s32.read_artefact(path, schema, code)
            documents.append((document, sha))
        return documents

    return {
        "samples": read(args.sample, "vehicle-subclass-sample-v1", "sample_invalid"),
        "primary_labels": read(args.track_labels, "vehicle-subclass-track-labels-v1", "labels_invalid"),
        "overlap_labels": read(args.overlap_labels, "vehicle-subclass-track-labels-v1", "labels_invalid"),
        "adjudications": read(args.adjudication, "vehicle-subclass-adjudication-v1", "adjudication_invalid"),
        "exports": s32.load_exports(args.export),
        "measured_profile_sha256": s32.sha256_hex(s32.read_bytes(args.pipeline_profile, "pipeline_profile_unreadable")),
    }


def track_label_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Track-label mode: " + __doc__.splitlines()[0])
    parser.add_argument("--sample", type=Path, action="append", required=True)
    parser.add_argument("--track-labels", type=Path, action="append", required=True)
    parser.add_argument("--overlap-labels", type=Path, action="append", default=[])
    parser.add_argument("--adjudication", type=Path, action="append", default=[])
    parser.add_argument("--export", type=Path, action="append", required=True)
    parser.add_argument("--pipeline-profile", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main_track_labels(argv: list[str]) -> int:
    args = track_label_parser().parse_args(argv)
    try:
        s32.require(not args.out.exists(), "output_exists")
        result = evaluate_track_labels(**read_track_label_inputs(args))
        s32.write_once(args.out, s32.canonical_json(result))
    except (s32.S32Error, SubclassEvaluationError) as exc:
        print(f"evaluate_vehicle_subclass: refused {exc}", file=sys.stderr)
        return 2
    return 0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--track-labels" in argv:
        return main_track_labels(argv)
    return _main_events(argv)


def _main_events(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--tracks", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True, help="Phase-1 acceptance profile (matching rules)")
    parser.add_argument("--pipeline-profile", type=Path, required=True, help="the pipeline profile under measurement")
    parser.add_argument("--attestation", type=Path, action="append", required=True,
                        help="a processing-run attestation; one per run the Tracks came from")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
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
