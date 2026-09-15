from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "quality_corpus.py"
SPEC = importlib.util.spec_from_file_location("quality_corpus_tests", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def profile() -> dict:
    return {
        "schemaVersion": "mavi-phase1-acceptance-profile-v1",
        "mode": "qualification",
        "qualificationCorpusManifestSha256": "9" * 64,
        "matching": {
            "minimumTemporalIou": 0.5,
            "minimumSpatialIou": 0.5,
            "maximumInterpolationSpanMs": 2000,
            "iouFixedPrecisionScale": 1000000,
            "iouRounding": "half-up",
        },
        "requiredClasses": ["Person", "Vehicle"],
        "classThresholds": {
            "Person": {"precision": 0.8, "recall": 0.8, "f1": 0.8},
            "Vehicle": {"precision": 0.8, "recall": 0.8, "f1": 0.8},
        },
    }


def summary(gt: int, produced: int, matched: int) -> dict:
    value = mod.summary_from_counts(gt, produced, matched)
    return {**value, "temporalIou": [0.9] * matched, "spatialIou": [0.9] * matched}


def metrics(person: tuple[int, int, int], vehicle: tuple[int, int, int]) -> dict:
    p = summary(*person)
    v = summary(*vehicle)
    overall = mod.summary_from_counts(
        p["groundTruthEventCount"] + v["groundTruthEventCount"],
        p["producedTrackCount"] + v["producedTrackCount"],
        p["matchedCount"] + v["matchedCount"],
    )
    per_class = {
        "Person": mod.validate_summary(p, "p"),
        "Vehicle": mod.validate_summary(v, "v"),
    }
    qualification = mod.derive_qualification(per_class, profile())
    return {
        "schemaVersion": "mavi-phase1-evaluation-result-v1",
        "mode": "qualification",
        "perClass": {"Person": p, "Vehicle": v},
        "overall": overall,
        "matching": [
            {
                "eventId": f"event-{index}",
                "trackId": f"track-{index}",
                "spatialIou": 0.9,
                "temporalIou": 0.9,
            }
            for index in range(overall["matchedCount"])
        ],
        "qualification": qualification,
    }


def test_quality_metrics_reject_forged_pass(monkeypatch):
    value = metrics((10, 10, 5), (10, 10, 10))
    value["qualification"] = {"passed": True, "failures": []}
    monkeypatch.setattr(mod, "validate_schema", lambda *_: None)
    with pytest.raises(
        mod.QualityCorpusError,
        match="quality_metrics_qualification_mismatch",
    ):
        mod.validate_evaluation_metrics(value, profile())


def test_quality_metrics_reject_raw_count_metric_inconsistency(monkeypatch):
    value = metrics((10, 10, 10), (10, 10, 10))
    value["perClass"]["Person"]["precision"] = 0.25
    monkeypatch.setattr(mod, "validate_schema", lambda *_: None)
    with pytest.raises(
        mod.QualityCorpusError,
        match="quality_metrics_counts_invalid:Person",
    ):
        mod.validate_evaluation_metrics(value, profile())


def test_corpus_aggregate_can_qualify_classes_across_separate_cases(monkeypatch):
    monkeypatch.setattr(mod, "validate_schema", lambda *_: None)
    person_case = mod.validate_evaluation_metrics(
        metrics((10, 10, 10), (0, 0, 0)),
        profile(),
    )
    vehicle_case = mod.validate_evaluation_metrics(
        metrics((0, 0, 0), (10, 10, 10)),
        profile(),
    )
    aggregate = mod.aggregate_case_metrics([person_case, vehicle_case], profile())
    assert aggregate["perClass"]["Person"]["groundTruthEventCount"] == 10
    assert aggregate["perClass"]["Vehicle"]["groundTruthEventCount"] == 10
    assert aggregate["qualification"] == {"passed": True, "failures": []}


def test_build_expected_requires_exact_complete_case_set(tmp_path: Path, monkeypatch):
    corpus = {
        "schemaVersion": "mavi-phase1-corpus-v1",
        "corpusId": "q",
        "cases": [
            {"caseId": "a", "mediaSha256": "1" * 64, "groundTruthManifestSha256": "2" * 64},
            {"caseId": "b", "mediaSha256": "3" * 64, "groundTruthManifestSha256": "4" * 64},
        ],
    }
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(corpus), encoding="utf-8")
    monkeypatch.setattr(mod, "validate_schema", lambda *_: None)
    p = profile()
    p["qualificationCorpusManifestSha256"] = mod.sha256_file(corpus_path)
    with pytest.raises(
        mod.QualityCorpusError,
        match="quality_case_evidence_set_mismatch",
    ):
        mod.build_expected_evidence(
            source_commit="a" * 40,
            mavi_build="build-a",
            target_verified_manifest_sha256="b" * 64,
            acceptance_profile_sha256="c" * 64,
            corpus_manifest=corpus_path,
            profile=p,
            case_evidence={"a": tmp_path / "a.json"},
            ground_truth={
                "a": tmp_path / "a-gt.json",
                "b": tmp_path / "b-gt.json",
            },
        )


def test_validate_corpus_rejects_forged_aggregate_decision(tmp_path: Path, monkeypatch):
    corpus = {
        "schemaVersion": "mavi-phase1-corpus-v1",
        "corpusId": "q",
        "cases": [{
            "caseId": "case-1",
            "mediaSha256": "1" * 64,
            "groundTruthManifestSha256": "",
        }],
    }
    gt = {
        "schemaVersion": "mavi-phase1-ground-truth-v1",
        "videoSha256": "1" * 64,
        "durationMs": 1000,
        "cameraCode": "Q",
        "evaluationWindows": [{"startOffsetMs": 0, "endOffsetMs": 1000}],
        "events": [],
    }
    gt_path = tmp_path / "gt.json"
    gt_path.write_text(json.dumps(gt), encoding="utf-8")
    corpus["cases"][0]["groundTruthManifestSha256"] = mod.sha256_file(gt_path)
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(corpus), encoding="utf-8")
    p = profile()
    p["qualificationCorpusManifestSha256"] = mod.sha256_file(corpus_path)

    evidence = {
        "mode": "formal",
        "sourceCommit": "a" * 40,
        "targetVerifiedManifestSha256": "b" * 64,
        "acceptanceProfileSha256": "c" * 64,
        "attestation": {"maviBuild": "build-a"},
        "sourceMedia": {"localSha256": "1" * 64},
        "video": {"id": "11111111-1111-4111-8111-111111111111", "durationMs": 1000},
        "processing": {"processingRunId": "22222222-2222-4222-8222-222222222222"},
        "groundTruth": {
            "groundTruthManifestSha256": mod.sha256_file(gt_path),
            "videoSha256": "1" * 64,
            "corpusManifestSha256": mod.sha256_file(corpus_path),
        },
        "metrics": metrics((10, 10, 10), (10, 10, 10)),
    }
    evidence_path = tmp_path / "case.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    monkeypatch.setattr(mod, "validate_schema", lambda *_: None)
    monkeypatch.setattr(mod.evidence_verifier, "verify_acceptance", lambda *_, **__: None)
    monkeypatch.setattr(mod.evaluator, "validate_ground_truth", lambda *_, **__: gt)

    expected = mod.build_expected_evidence(
        source_commit="a" * 40,
        mavi_build="build-a",
        target_verified_manifest_sha256="b" * 64,
        acceptance_profile_sha256="c" * 64,
        corpus_manifest=corpus_path,
        profile=p,
        case_evidence={"case-1": evidence_path},
        ground_truth={"case-1": gt_path},
    )
    forged = json.loads(json.dumps(expected))
    forged["aggregate"]["perClass"]["Person"]["matchedCount"] = 1
    with pytest.raises(
        mod.QualityCorpusError,
        match="quality_corpus_evidence_recalculation_mismatch",
    ):
        mod.validate_quality_corpus_evidence(
            forged,
            source_commit="a" * 40,
            mavi_build="build-a",
            target_verified_manifest_sha256="b" * 64,
            acceptance_profile_sha256="c" * 64,
            corpus_manifest=corpus_path,
            profile=p,
            case_evidence={"case-1": evidence_path},
            ground_truth={"case-1": gt_path},
            require_passed=True,
        )
