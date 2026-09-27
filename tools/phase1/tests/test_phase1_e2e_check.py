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


def composition():
    return {
        "capabilityId": "detector",
        "modelPackId": "mavi-model-v2-" + "a" * 64,
        "componentBindingSha256": "c" * 64,
        "runtimePackId": None,
        "runtimePackSource": "unpacked-environment",
    }


def attestation(status="unverified", lock=None):
    value = dict(expected())
    value.update(composition())
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
        composition=composition(),
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
            composition=composition(),
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
        composition=composition(),
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
            composition=composition(),
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
            composition=composition(),
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
            "databaseIdentitySha256": "4" * 64,
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


# --------------------------------------------------------------------------- v2 composition (S2a.3)

from phase1_v2_support import (  # noqa: E402
    COMMITTED_BINDING,
    COMMITTED_PIPELINE,
    REPOSITORY,
    overlay_type,
    sha256_file,
)


@pytest.mark.parametrize(
    "key",
    ["capabilityId", "modelPackId", "componentBindingSha256", "runtimePackId", "runtimePackSource"],
)
def test_attestation_must_carry_the_resolved_component_identity(key):
    value = attestation()
    value[key] = "mavi-runtime-v2-" + "f" * 64 if key == "runtimePackId" else "other"
    with pytest.raises(mod.AcceptanceError, match="qualification_attestation_mismatch:" + key):
        mod._compare_attestation(
            value,
            selection(),
            expected(),
            bundle(),
            "8" * 64,
            "a" * 40,
            "build-a",
            composition=composition(),
        )


def _composition_args(overlay, **changes):
    values = {
        "component_binding": overlay.binding_path,
        "overlay_root": overlay.root,
        "model_root": overlay.model_root,
        "pipeline_profile": overlay.pipeline_path,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def test_expected_release_is_the_resolver_composition(tmp_path: Path):
    overlay = overlay_type().create(tmp_path)
    resolved = overlay.resolve("linux-x86_64-cpu")
    capability = resolved.capabilities["detector"]

    selection_value, expected_value, composition_value = mod._expected_release(
        _composition_args(overlay), "linux-x86_64-cpu"
    )

    assert selection_value.verification_status == "unverified"
    by_role = {item["artifactRole"]: item["sha256"] for item in overlay.manifest["artifacts"]}
    assert expected_value == {
        "modelId": overlay.manifest["modelId"],
        "modelManifestSha256": sha256_file(overlay.manifest_path),
        "checkpointSha256": by_role["checkpoint"],
        "resolvedConfigSha256": by_role["resolved-config"],
        "pipelineProfileId": resolved.pipeline_profile.profile_id,
        "pipelineProfileSha256": sha256_file(overlay.pipeline_path),
        "runtimeProfileId": "mmdetection-phase1-v1",
        "runtimeProfileSha256": sha256_file(overlay.runtime_path),
        "qualificationSha256": sha256_file(overlay.record_path),
    }
    # Identity is read from the resolver, never derived here.
    assert composition_value == {
        "capabilityId": "detector",
        "modelPackId": capability.model_pack_id,
        "componentBindingSha256": sha256_file(overlay.binding_path),
        "runtimePackId": None,
        "runtimePackSource": "unpacked-environment",
    }
    # The evidence schema's release block is unchanged by the port.
    schema = json.loads((MODULE_PATH.parent / "phase1-acceptance-evidence.schema.json").read_text(encoding="utf-8"))
    assert set(expected_value) == set(schema["$defs"]["release"]["required"])


def test_expected_release_fails_closed_without_model_bytes(tmp_path: Path):
    args = SimpleNamespace(
        component_binding=COMMITTED_BINDING,
        overlay_root=REPOSITORY,
        model_root=tmp_path / "empty-model-store",
        pipeline_profile=COMMITTED_PIPELINE,
    )
    with pytest.raises(mod.AcceptanceError, match="model_artifact_missing:checkpoint"):
        mod._expected_release(args, "linux-x86_64-cpu")


def test_expected_release_refuses_an_undeclared_variant(tmp_path: Path):
    overlay = overlay_type().create(tmp_path)
    with pytest.raises(mod.AcceptanceError, match="runtime_variant_not_declared:linux-x86_64-cuda"):
        mod._expected_release(_composition_args(overlay), "linux-x86_64-cuda")


def test_bundle_release_is_verified_through_the_v2_bundle_verifier(tmp_path: Path, monkeypatch):
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    manifest = {
        "sourceCommit": "a" * 40,
        "releaseStatus": "qualification-candidate",
        "platformVariant": "linux-x86_64-cpu",
        "artifacts": [],
    }
    (bundle_dir / "bundle-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        mod.build_offline_bundle,
        "verify_bundled_release_manifest",
        lambda stage, value: calls.append((stage, value)),
    )
    assert mod._validate_bundle(bundle_dir, "a" * 40)[0] == manifest
    assert calls == [(bundle_dir, manifest)]

    def refuse(stage, value):
        raise mod.build_offline_bundle.OfflineBundleError("runtime_pack_required")

    monkeypatch.setattr(mod.build_offline_bundle, "verify_bundled_release_manifest", refuse)
    with pytest.raises(mod.AcceptanceError, match="qualification_bundle_release_selection_invalid"):
        mod._validate_bundle(bundle_dir, "a" * 40)


@pytest.mark.parametrize("retired", ["--model-manifest", "--runtime-profile", "--qualification-record"])
def test_the_retired_path_arguments_are_refused(monkeypatch, retired):
    argv = [
        "phase1_e2e_check.py",
        "--mode", "formal",
        "--base-url", "http://mavi.local",
        "--camera-code", "c",
        "--camera-name", "n",
        "--camera-timezone", "UTC",
        "--recording-local", "2026-01-01T00:00:00",
        "--video", "v.mp4",
        "--environment-label", "e",
        "--source-commit", "a" * 40,
        "--expected-mavi-build", "b",
        "--target-verified-manifest-sha256", "0" * 64,
        "--model-root", "models",
        "--pipeline-profile", "p.json",
        "--bundle-dir", "bundle",
        "--acceptance-profile", "a.json",
        "--output", "o.json",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    args = mod.parse_args()
    assert args.component_binding == COMMITTED_BINDING
    assert args.overlay_root == REPOSITORY
    monkeypatch.setattr(sys, "argv", argv + [retired, "x.json"])
    with pytest.raises(SystemExit):
        mod.parse_args()
