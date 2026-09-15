#!/usr/bin/env python3
"""Canonical Task-17 CCTV quality corpus evidence construction/verification."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

PHASE1_ROOT = Path(__file__).resolve().parent
ROOT = PHASE1_ROOT.parents[1]
if str(PHASE1_ROOT) not in sys.path:
    sys.path.insert(0, str(PHASE1_ROOT))

import evaluate_ground_truth as evaluator  # noqa: E402
import verify_phase1_evidence as evidence_verifier  # noqa: E402

SUPPORTED_CLASSES = ("Person", "Vehicle")


class QualityCorpusError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QualityCorpusError(code) from exc
    if not isinstance(value, dict):
        raise QualityCorpusError(code)
    return value


def validate_schema(value: dict[str, Any], schema_path: Path, code: str) -> None:
    schema = load_json(schema_path, code + "_schema_unavailable")
    errors = sorted(
        Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).iter_errors(value),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        path = "/".join(str(item) for item in errors[0].absolute_path)
        raise QualityCorpusError(code + "_schema_invalid:" + path)


def parse_named_paths(values: list[str], code: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for raw in values:
        if "=" not in raw:
            raise QualityCorpusError(code)
        case_id, path = raw.split("=", 1)
        if not case_id or not path or case_id in result:
            raise QualityCorpusError(code)
        result[case_id] = Path(path)
    return result


def _metric(matched: int, denominator: int) -> float | None:
    return matched / denominator if denominator else None


def summary_from_counts(
    ground_truth: int,
    produced: int,
    matched: int,
) -> dict[str, Any]:
    if (
        any(isinstance(value, bool) or not isinstance(value, int) for value in (ground_truth, produced, matched))
        or ground_truth < 0
        or produced < 0
        or matched < 0
        or matched > ground_truth
        or matched > produced
    ):
        raise QualityCorpusError("quality_counts_invalid")
    missed = ground_truth - matched
    unmatched = produced - matched
    precision = _metric(matched, produced)
    recall = _metric(matched, ground_truth)
    f1 = (
        None
        if precision is None
        or recall is None
        or precision + recall == 0
        else 2 * precision * recall / (precision + recall)
    )
    return {
        "groundTruthEventCount": ground_truth,
        "producedTrackCount": produced,
        "matchedCount": matched,
        "missedCount": missed,
        "unmatchedTrackCount": unmatched,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _same_metric(observed: Any, expected: float | None) -> bool:
    if expected is None:
        return observed is None
    return (
        isinstance(observed, (int, float))
        and not isinstance(observed, bool)
        and math.isfinite(float(observed))
        and math.isclose(float(observed), expected, rel_tol=0.0, abs_tol=1e-12)
    )


def validate_summary(row: Any, code: str) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise QualityCorpusError(code)
    required = {
        "groundTruthEventCount",
        "producedTrackCount",
        "matchedCount",
        "missedCount",
        "unmatchedTrackCount",
        "precision",
        "recall",
        "f1",
    }
    if not required.issubset(row):
        raise QualityCorpusError(code)
    expected = summary_from_counts(
        row["groundTruthEventCount"],
        row["producedTrackCount"],
        row["matchedCount"],
    )
    if (
        row["missedCount"] != expected["missedCount"]
        or row["unmatchedTrackCount"] != expected["unmatchedTrackCount"]
        or not _same_metric(row["precision"], expected["precision"])
        or not _same_metric(row["recall"], expected["recall"])
        or not _same_metric(row["f1"], expected["f1"])
    ):
        raise QualityCorpusError(code)
    return expected


def derive_qualification(
    per_class: dict[str, dict[str, Any]],
    profile: dict[str, Any],
) -> dict[str, Any]:
    failures: list[str] = []
    thresholds = profile.get("classThresholds")
    if not isinstance(thresholds, dict):
        raise QualityCorpusError("quality_thresholds_invalid")
    for object_class in SUPPORTED_CLASSES:
        row = per_class[object_class]
        if row["groundTruthEventCount"] <= 0:
            failures.append(object_class + ":coverage_zero")
            continue
        class_thresholds = thresholds.get(object_class)
        if not isinstance(class_thresholds, dict):
            raise QualityCorpusError("quality_thresholds_invalid")
        for metric in ("precision", "recall", "f1"):
            threshold = class_thresholds.get(metric)
            actual = row.get(metric)
            if (
                isinstance(threshold, bool)
                or not isinstance(threshold, (int, float))
                or not 0 <= float(threshold) <= 1
            ):
                raise QualityCorpusError("quality_thresholds_invalid")
            if actual is None or float(actual) < float(threshold):
                failures.append(object_class + ":" + metric)
    return {"passed": not failures, "failures": failures}


def validate_evaluation_metrics(
    metrics: Any,
    profile: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(metrics, dict):
        raise QualityCorpusError("quality_metrics_invalid")
    validate_schema(
        metrics,
        PHASE1_ROOT / "phase1-evaluation-result.schema.json",
        "quality_metrics",
    )
    if metrics.get("mode") != "qualification":
        raise QualityCorpusError("quality_metrics_not_qualification")
    expected_per_class: dict[str, dict[str, Any]] = {}
    for object_class in SUPPORTED_CLASSES:
        expected_per_class[object_class] = validate_summary(
            metrics["perClass"][object_class],
            "quality_metrics_counts_invalid:" + object_class,
        )
        if len(metrics["perClass"][object_class]["temporalIou"]) != expected_per_class[object_class]["matchedCount"]:
            raise QualityCorpusError("quality_temporal_iou_count_invalid:" + object_class)
        if len(metrics["perClass"][object_class]["spatialIou"]) != expected_per_class[object_class]["matchedCount"]:
            raise QualityCorpusError("quality_spatial_iou_count_invalid:" + object_class)

    expected_overall = validate_summary(
        metrics["overall"],
        "quality_metrics_overall_invalid",
    )
    matching = metrics.get("matching")
    if not isinstance(matching, list) or len(matching) != expected_overall["matchedCount"]:
        raise QualityCorpusError("quality_matching_count_invalid")
    event_ids = [item.get("eventId") for item in matching if isinstance(item, dict)]
    track_ids = [item.get("trackId") for item in matching if isinstance(item, dict)]
    if (
        len(event_ids) != len(matching)
        or len(track_ids) != len(matching)
        or len(set(event_ids)) != len(event_ids)
        or len(set(track_ids)) != len(track_ids)
    ):
        raise QualityCorpusError("quality_matching_identity_invalid")
    summed = summary_from_counts(
        sum(row["groundTruthEventCount"] for row in expected_per_class.values()),
        sum(row["producedTrackCount"] for row in expected_per_class.values()),
        sum(row["matchedCount"] for row in expected_per_class.values()),
    )
    for field in (
        "groundTruthEventCount",
        "producedTrackCount",
        "matchedCount",
        "missedCount",
        "unmatchedTrackCount",
    ):
        if expected_overall[field] != summed[field]:
            raise QualityCorpusError("quality_metrics_overall_class_sum_mismatch")
    for field in ("precision", "recall", "f1"):
        if not _same_metric(expected_overall[field], summed[field]):
            raise QualityCorpusError("quality_metrics_overall_class_sum_mismatch")

    derived = derive_qualification(expected_per_class, profile)
    qualification = metrics.get("qualification")
    if (
        not isinstance(qualification, dict)
        or qualification.get("passed") != derived["passed"]
        or qualification.get("failures") != derived["failures"]
    ):
        raise QualityCorpusError("quality_metrics_qualification_mismatch")
    return {
        "perClass": expected_per_class,
        "overall": expected_overall,
        "qualification": derived,
    }


def aggregate_case_metrics(
    case_metrics: list[dict[str, Any]],
    profile: dict[str, Any],
) -> dict[str, Any]:
    if not case_metrics:
        raise QualityCorpusError("quality_corpus_cases_empty")
    per_class: dict[str, dict[str, Any]] = {}
    for object_class in SUPPORTED_CLASSES:
        per_class[object_class] = summary_from_counts(
            sum(item["perClass"][object_class]["groundTruthEventCount"] for item in case_metrics),
            sum(item["perClass"][object_class]["producedTrackCount"] for item in case_metrics),
            sum(item["perClass"][object_class]["matchedCount"] for item in case_metrics),
        )
    overall = summary_from_counts(
        sum(row["groundTruthEventCount"] for row in per_class.values()),
        sum(row["producedTrackCount"] for row in per_class.values()),
        sum(row["matchedCount"] for row in per_class.values()),
    )
    return {
        "perClass": per_class,
        "overall": overall,
        "qualification": derive_qualification(per_class, profile),
    }


def _case_map(corpus: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cases = corpus.get("cases")
    if not isinstance(cases, list) or not cases:
        raise QualityCorpusError("quality_corpus_cases_invalid")
    result: dict[str, dict[str, Any]] = {}
    media: set[str] = set()
    for item in cases:
        if not isinstance(item, dict):
            raise QualityCorpusError("quality_corpus_cases_invalid")
        case_id = item.get("caseId")
        media_sha = item.get("mediaSha256")
        if (
            not isinstance(case_id, str)
            or not case_id
            or case_id in result
            or not isinstance(media_sha, str)
            or media_sha in media
        ):
            raise QualityCorpusError("quality_corpus_case_identity_invalid")
        result[case_id] = item
        media.add(media_sha)
    return result


def build_expected_evidence(
    *,
    source_commit: str,
    mavi_build: str,
    target_verified_manifest_sha256: str,
    acceptance_profile_sha256: str,
    corpus_manifest: Path,
    profile: dict[str, Any],
    case_evidence: dict[str, Path],
    ground_truth: dict[str, Path],
) -> dict[str, Any]:
    corpus = load_json(corpus_manifest, "quality_corpus_invalid")
    validate_schema(
        corpus,
        ROOT / "sample-data" / "ground-truth" / "phase1-corpus.schema.json",
        "quality_corpus",
    )
    corpus_sha = sha256_file(corpus_manifest)
    if profile.get("qualificationCorpusManifestSha256") != corpus_sha:
        raise QualityCorpusError("quality_corpus_not_approved")
    expected_cases = _case_map(corpus)
    if set(case_evidence) != set(expected_cases):
        raise QualityCorpusError("quality_case_evidence_set_mismatch")
    if set(ground_truth) != set(expected_cases):
        raise QualityCorpusError("quality_ground_truth_set_mismatch")

    rows: list[dict[str, Any]] = []
    normalized_metrics: list[dict[str, Any]] = []
    for case_id in sorted(expected_cases):
        mapping = expected_cases[case_id]
        evidence_path = case_evidence[case_id]
        gt_path = ground_truth[case_id]
        evidence = load_json(evidence_path, "quality_case_evidence_invalid:" + case_id)
        validate_schema(
            evidence,
            PHASE1_ROOT / "phase1-acceptance-evidence.schema.json",
            "quality_case_evidence:" + case_id,
        )
        try:
            evidence_verifier.verify_acceptance(
                evidence,
                expected_source_commit=source_commit,
                expected_acceptance_profile_sha256=acceptance_profile_sha256,
                expected_qualification_corpus_sha256=corpus_sha,
            )
        except evidence_verifier.EvidenceError as exc:
            raise QualityCorpusError(
                "quality_case_evidence_invalid:" + case_id + ":" + exc.code
            ) from exc
        if (
            evidence.get("mode") != "formal"
            or evidence.get("targetVerifiedManifestSha256") != target_verified_manifest_sha256
            or evidence.get("attestation", {}).get("maviBuild") != mavi_build
        ):
            raise QualityCorpusError("quality_case_release_binding_mismatch:" + case_id)

        gt = load_json(gt_path, "quality_ground_truth_invalid:" + case_id)
        validate_schema(
            gt,
            ROOT / "sample-data" / "ground-truth" / "phase1-ground-truth.schema.json",
            "quality_ground_truth:" + case_id,
        )
        try:
            evaluator.validate_ground_truth(gt, profile)
        except evaluator.EvaluationError as exc:
            raise QualityCorpusError(
                "quality_ground_truth_invalid:" + case_id + ":" + exc.code
            ) from exc
        gt_sha = sha256_file(gt_path)
        media_sha = evidence["sourceMedia"]["localSha256"]
        gt_evidence = evidence.get("groundTruth")
        if (
            mapping.get("mediaSha256") != media_sha
            or mapping.get("groundTruthManifestSha256") != gt_sha
            or gt.get("videoSha256") != media_sha
            or gt.get("durationMs") != evidence["video"]["durationMs"]
            or not isinstance(gt_evidence, dict)
            or gt_evidence.get("groundTruthManifestSha256") != gt_sha
            or gt_evidence.get("videoSha256") != media_sha
            or gt_evidence.get("corpusManifestSha256") != corpus_sha
        ):
            raise QualityCorpusError("quality_case_media_binding_mismatch:" + case_id)

        metrics = validate_evaluation_metrics(evidence.get("metrics"), profile)
        normalized_metrics.append(metrics)
        rows.append({
            "caseId": case_id,
            "mediaSha256": media_sha,
            "groundTruthManifestSha256": gt_sha,
            "acceptanceEvidenceSha256": sha256_file(evidence_path),
            "videoAssetId": evidence["video"]["id"],
            "processingRunId": evidence["processing"]["processingRunId"],
            "metrics": evidence["metrics"],
        })

    aggregate = aggregate_case_metrics(normalized_metrics, profile)
    return {
        "schemaVersion": "mavi-cctv-quality-corpus-evidence-v1",
        "sourceCommit": source_commit,
        "maviBuild": mavi_build,
        "targetVerifiedManifestSha256": target_verified_manifest_sha256,
        "acceptanceProfileSha256": acceptance_profile_sha256,
        "corpusManifestSha256": corpus_sha,
        "cases": rows,
        "aggregate": aggregate,
        "result": {
            "passed": aggregate["qualification"]["passed"],
            "failureCodes": [] if aggregate["qualification"]["passed"] else list(aggregate["qualification"]["failures"]),
        },
    }


def validate_quality_corpus_evidence(
    value: dict[str, Any],
    *,
    source_commit: str,
    mavi_build: str,
    target_verified_manifest_sha256: str,
    acceptance_profile_sha256: str,
    corpus_manifest: Path,
    profile: dict[str, Any],
    case_evidence: dict[str, Path],
    ground_truth: dict[str, Path],
    require_passed: bool,
) -> dict[str, Any]:
    validate_schema(
        value,
        PHASE1_ROOT / "cctv-quality-corpus-evidence.schema.json",
        "quality_corpus_evidence",
    )
    expected = build_expected_evidence(
        source_commit=source_commit,
        mavi_build=mavi_build,
        target_verified_manifest_sha256=target_verified_manifest_sha256,
        acceptance_profile_sha256=acceptance_profile_sha256,
        corpus_manifest=corpus_manifest,
        profile=profile,
        case_evidence=case_evidence,
        ground_truth=ground_truth,
    )
    if value != expected:
        raise QualityCorpusError("quality_corpus_evidence_recalculation_mismatch")
    if require_passed and expected["aggregate"]["qualification"]["passed"] is not True:
        raise QualityCorpusError("quality_corpus_not_passed")
    return expected
