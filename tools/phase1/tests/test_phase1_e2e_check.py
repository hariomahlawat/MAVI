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
        "platform": {
            "system": "Linux",
            "release": "6.8",
            "version": "qualified",
            "machine": "x86_64",
            "processor": "x86_64",
            "pythonVersion": "3.12.14",
            "pythonImplementation": "CPython",
            "pythonBuild": ["main", "Sep 2026"],
            "pythonCompiler": "GCC",
        },
        "gpu": None,
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
        "build-a",
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
            "build-a",
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
        "build-a",
    )
    assert result["platformLockSha256"] == "7" * 64
    assert result["productionBundleManifestSha256"] == "8" * 64

    prod_attestation["platformLockSha256"] = "9" * 64
    with pytest.raises(mod.AcceptanceError, match="qualification_production_lock_mismatch"):
        mod._compare_attestation(
            prod_attestation,
            selection("verified"),
            expected(),
            bundle("production"),
            "8" * 64,
            "a" * 40,
            "build-a",
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


def test_attestation_rejects_wrong_mavi_build():
    value = attestation()
    value["maviBuild"] = "other-build"
    with pytest.raises(mod.AcceptanceError, match="qualification_attestation_mismatch:maviBuild"):
        mod._compare_attestation(
            value,
            selection(),
            expected(),
            bundle(),
            "8" * 64,
            "a" * 40,
            "build-a",
        )


def test_empty_scene_diagnostic_rejects_any_false_positive_track():
    with pytest.raises(
        mod.AcceptanceError,
        match="qualification_empty_scene_false_positive",
    ):
        mod.assert_empty_scene_diagnostic(
            track_count=1,
            detail_count=1,
            evidence_count=1,
        )


def test_empty_scene_diagnostic_accepts_zero_detections():
    mod.assert_empty_scene_diagnostic(
        track_count=0,
        detail_count=0,
        evidence_count=0,
    )


def test_application_health_requires_exact_expected_build():
    with pytest.raises(mod.AcceptanceError, match="qualification_application_identity_mismatch"):
        mod._validate_application_health(
            {"status": "ok", "commit": "a" * 40, "build": "build-b"},
            source_commit="a" * 40,
            expected_mavi_build="build-a",
        )


def test_application_health_accepts_exact_expected_identity():
    mod._validate_application_health(
        {"status": "ok", "commit": "a" * 40, "build": "build-a"},
        source_commit="a" * 40,
        expected_mavi_build="build-a",
    )


class TopologyClient:
    def __init__(self, host_identity: str):
        self.host_identity = host_identity

    def json(self, method: str, path: str):
        assert method == "GET"
        assert path == "/api/system/storage-topology"
        return {
            "schemaVersion": "mavi-storage-topology-attestation-v1",
            "maviBuild": "build-a",
            "maviCommit": "a" * 40,
            "operationalHostIdentitySha256": self.host_identity,
            "databaseIdentity": "mavi|127.0.0.1|5432",
            "managedMediaRootIdentitySha256": "2" * 64,
            "acceptedEvidenceRootIdentitySha256": "3" * 64,
        }


def test_operational_topology_rejects_same_build_on_other_host():
    with pytest.raises(
        mod.AcceptanceError,
        match="qualification_operational_host_mismatch",
    ):
        mod._validate_operational_topology(
            TopologyClient("b" * 64),
            source_commit="a" * 40,
            expected_mavi_build="build-a",
            expected_host_identity_sha256="c" * 64,
        )


def test_authoritative_state_digest_changes_on_semantic_track_change():
    base = {
        "camera": {
            "id": "camera",
            "code": "Q",
            "name": "Qualification",
            "timeZoneId": "UTC",
            "isActive": True,
        },
        "video": {
            "id": "video",
            "cameraId": "camera",
            "recordingStartUtc": "2026-01-01T00:00:00Z",
            "recordingTimeZoneId": "UTC",
            "recordingUtcOffsetMinutes": 0,
            "durationMs": 1000,
        },
        "processingRunId": "run",
        "tracks": [{
            "id": "track",
            "objectClass": "Person",
            "startOffsetMs": 0,
            "endOffsetMs": 100,
            "representative": None,
        }],
        "source": {"sha256": "1" * 64, "etagSha256": "1" * 64},
        "representativeArtifact": {"id": None, "sha256": None, "etagSha256": None},
    }
    changed = json.loads(json.dumps(base))
    changed["tracks"][0]["objectClass"] = "Vehicle"
    assert mod._authoritative_state_sha256(base) != mod._authoritative_state_sha256(changed)
