from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "phase1_e2e_check.py"
SPEC = importlib.util.spec_from_file_location("phase1_e2e", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def selection(status="unverified"):
    return SimpleNamespace(verification_status=status)


def expected():
    return {
        "modelId": "rtmdet-m",
        "modelManifestSha256": "1" * 64,
        "checkpointSha256": "2" * 64,
        "resolvedConfigSha256": "3" * 64,
        "pipelineProfileId": "phase1",
        "pipelineProfileSha256": "4" * 64,
        "runtimeProfileId": "runtime-v1",
        "runtimeProfileSha256": "5" * 64,
        "qualificationSha256": "6" * 64,
    }


def attestation(status="unverified", lock=None):
    value = dict(expected())
    value.update({
        "processingRunId": "11111111-1111-1111-1111-111111111111",
        "verificationStatus": status,
        "runtimeVariant": "linux-x86_64-cpu",
        "actualDevice": "cpu",
        "maviBuild": "build-a",
        "maviCommit": "a" * 40,
        "platformLockSha256": lock,
    })
    return value


def bundle(mode="qualification-candidate"):
    return {
        "releaseStatus": mode,
        "platformVariant": "linux-x86_64-cpu",
        "lockSha256": "7" * 64,
    }


def test_candidate_lock_is_proven_by_bundle_not_persisted_provenance():
    result = mod._compare_attestation(
        attestation(),
        selection(),
        expected(),
        bundle(),
        "8" * 64,
        "a" * 40,
    )
    assert result["platformLockSha256"] is None
    assert result["candidateSelectedLockSha256"] == "7" * 64


def test_candidate_rejects_persisted_lock():
    with pytest.raises(mod.AcceptanceError, match="qualification_candidate_persisted_lock_unexpected"):
        mod._compare_attestation(
            attestation(lock="7" * 64),
            selection(),
            expected(),
            bundle(),
            "8" * 64,
            "a" * 40,
        )


def test_production_requires_persisted_lock_match():
    prod_attestation = attestation("verified", lock="7" * 64)
    result = mod._compare_attestation(
        prod_attestation,
        selection("verified"),
        expected(),
        bundle("production"),
        "8" * 64,
        "a" * 40,
    )
    assert result["platformLockSha256"] == "7" * 64

    prod_attestation["platformLockSha256"] = "9" * 64
    with pytest.raises(mod.AcceptanceError, match="qualification_production_lock_mismatch"):
        mod._compare_attestation(
            prod_attestation,
            selection("verified"),
            expected(),
            bundle("production"),
            "8" * 64,
            "a" * 40,
        )


def test_ground_truth_for_different_media_fails_before_evaluation(tmp_path: Path):
    media_sha = "a" * 64
    gt = {
        "schemaVersion": "mavi-phase1-ground-truth-v1",
        "videoSha256": "b" * 64,
        "durationMs": 1000,
        "cameraCode": "QUAL",
        "evaluationWindows": [{"startOffsetMs": 0, "endOffsetMs": 1000}],
        "events": [],
    }
    gt_path = tmp_path / "gt.json"
    gt_path.write_text(json.dumps(gt, sort_keys=True), encoding="utf-8")
    gt_sha = mod.sha256_file(gt_path)
    corpus = {
        "schemaVersion": "mavi-phase1-corpus-v1",
        "corpusId": "test",
        "cases": [{
            "caseId": "case-1",
            "mediaSha256": media_sha,
            "groundTruthManifestSha256": gt_sha,
        }],
    }
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(corpus, sort_keys=True), encoding="utf-8")

    with pytest.raises(mod.AcceptanceError, match="qualification_ground_truth_video_mismatch"):
        mod._corpus_binding(corpus_path, gt_path, media_sha, 1000)


class StatusClient:
    def __init__(self, rows):
        self.rows = iter(rows)

    def json(self, method, path):
        return next(self.rows)


def test_poll_rejects_superseding_run():
    client = StatusClient([{
        "videoStatus": "Processing",
        "latestRun": {
            "processingRunId": "22222222-2222-2222-2222-222222222222",
            "status": "Running",
        },
    }])
    with pytest.raises(mod.AcceptanceError, match="qualification_processing_run_superseded"):
        mod._poll_completed_run(
            client,
            "video",
            "11111111-1111-1111-1111-111111111111",
            5,
        )


def test_recording_identity_rejects_ambiguous_wall_time():
    with pytest.raises(mod.AcceptanceError, match="qualification_recording_time_ambiguous"):
        mod._recording_identity("2026-11-01T01:30:00", "America/New_York")
