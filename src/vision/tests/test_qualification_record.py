from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mavi_vision.runtime.manifest import ReleaseMetadataError
from mavi_vision.runtime.qualification import (
    MANDATORY_QUALIFICATION_GATES,
    load_qualification_record,
    verify_release_selection,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _profile_payload() -> dict:
    return {
        "schemaVersion": "1.0",
        "profileId": "phase1-detection-tracking-v1",
        "profileVersion": "1.0.0-candidate",
        "modelId": "model-a",
        "detectorInferenceFloor": 0.05,
        "allowedSourceClasses": ["person", "car", "motorcycle", "bus", "truck"],
        "classMapping": {
            "person": "person",
            "car": "vehicle",
            "motorcycle": "vehicle",
            "bus": "vehicle",
            "truck": "vehicle",
        },
        "tracker": {
            "trackActivationThreshold": 0.25,
            "highConfidenceThreshold": 0.6,
            "minimumMatchingThreshold": 0.8,
            "minimumConsecutiveFrames": 1,
            "lostTrackBufferSeconds": 1.0,
        },
        "framePolicy": "every-frame",
    }


def _release_fixture(
    tmp_path: Path,
    *,
    verified: bool,
    all_gates_passed: bool = True,
) -> dict[str, Path]:
    model_root = tmp_path / "models"
    release = model_root / "release"
    release.mkdir(parents=True)
    checkpoint_path = release / "checkpoint.pth"
    config_path = release / "config.py"
    checkpoint_path.write_bytes(b"checkpoint-v1")
    config_path.write_bytes(b"model = dict(type='RTMDet')\n")
    checkpoint_hash = _sha(checkpoint_path.read_bytes())
    config_hash = _sha(config_path.read_bytes())

    runtime_path = tmp_path / "runtime.json"
    _write_json(
        runtime_path,
        {
            "schemaVersion": "1.0",
            "runtimeProfileId": "runtime-a",
            "checkpoint": {"sha256": checkpoint_hash},
            "resolvedConfig": {"sha256": config_hash},
        },
    )

    profile_path = tmp_path / "profile.json"
    _write_json(profile_path, _profile_payload())

    qualification_id = "qualification-a" if verified else None
    manifest_path = tmp_path / "manifest.json"
    _write_json(
        manifest_path,
        {
            "schemaVersion": "1.0",
            "modelId": "model-a",
            "modelVersion": "1.0.0",
            "purpose": "test",
            "backend": "mmdetection",
            "architecture": "rtmdet-m",
            "classVocabulary": ["person", "car", "motorcycle", "bus", "truck"],
            "checkpoint": {
                "relativePath": "release/checkpoint.pth",
                "sha256": checkpoint_hash,
            },
            "resolvedConfig": {
                "relativePath": "release/config.py",
                "sha256": config_hash,
            },
            "runtimeProfileId": "runtime-a",
            "verificationStatus": "verified" if verified else "unverified",
            "qualificationId": qualification_id,
        },
    )

    qualification_path = tmp_path / "qualification.json"
    gate_status = {
        gate_name: (
            "passed"
            if all_gates_passed
            else ("passed" if gate_name == "windows-x86_64-cpu" else "pending")
        )
        for gate_name in sorted(MANDATORY_QUALIFICATION_GATES)
    }
    evidence = {
        gate_name: {
            "kind": "test",
            "reference": f"evidence:{gate_name}",
            "sha256": _sha(f"evidence:{gate_name}".encode("utf-8")),
        }
        for gate_name, status in gate_status.items()
        if status == "passed"
    }
    _write_json(
        qualification_path,
        {
            "schemaVersion": "1.0",
            "qualificationId": qualification_id or "qualification-a",
            "modelId": "model-a",
            "modelManifestSha256": _sha(manifest_path.read_bytes()),
            "checkpointSha256": checkpoint_hash,
            "resolvedConfigSha256": config_hash,
            "pipelineProfileId": "phase1-detection-tracking-v1",
            "pipelineProfileSha256": _sha(profile_path.read_bytes()),
            "runtimeProfileId": "runtime-a",
            "runtimeProfileSha256": _sha(runtime_path.read_bytes()),
            "requiredGates": gate_status,
            "evidence": evidence,
            "overallResult": "passed" if all_gates_passed else "pending",
        },
    )

    return {
        "model_root": model_root,
        "checkpoint": checkpoint_path,
        "config": config_path,
        "runtime": runtime_path,
        "profile": profile_path,
        "manifest": manifest_path,
        "qualification": qualification_path,
    }


def test_verified_release_selection_checks_all_exact_byte_relationships(
    tmp_path: Path,
) -> None:
    paths = _release_fixture(tmp_path, verified=True, all_gates_passed=True)

    selection = verify_release_selection(
        model_root=paths["model_root"],
        manifest_path=paths["manifest"],
        profile_path=paths["profile"],
        runtime_profile_path=paths["runtime"],
        qualification_path=paths["qualification"],
    )

    assert selection.verification_status == "verified"
    assert selection.checkpoint_path == paths["checkpoint"].resolve()
    assert selection.resolved_config_path == paths["config"].resolve()
    assert selection.qualification is not None
    assert selection.qualification.overall_result == "passed"


def test_unverified_release_requires_explicit_development_opt_in(tmp_path: Path) -> None:
    paths = _release_fixture(tmp_path, verified=False)

    with pytest.raises(ReleaseMetadataError, match="unverified_release_forbidden"):
        verify_release_selection(
            model_root=paths["model_root"],
            manifest_path=paths["manifest"],
            profile_path=paths["profile"],
            runtime_profile_path=paths["runtime"],
        )

    selection = verify_release_selection(
        model_root=paths["model_root"],
        manifest_path=paths["manifest"],
        profile_path=paths["profile"],
        runtime_profile_path=paths["runtime"],
        allow_unverified=True,
    )

    assert selection.verification_status == "unverified"
    assert selection.qualification is None


def test_verified_release_rejects_pending_mandatory_gate(tmp_path: Path) -> None:
    paths = _release_fixture(tmp_path, verified=True, all_gates_passed=False)

    with pytest.raises(ReleaseMetadataError, match="qualification_not_passed"):
        verify_release_selection(
            model_root=paths["model_root"],
            manifest_path=paths["manifest"],
            profile_path=paths["profile"],
            runtime_profile_path=paths["runtime"],
            qualification_path=paths["qualification"],
        )


def test_verified_release_rejects_qualification_hash_mismatch(tmp_path: Path) -> None:
    paths = _release_fixture(tmp_path, verified=True, all_gates_passed=True)
    qualification = json.loads(paths["qualification"].read_text(encoding="utf-8"))
    qualification["pipelineProfileSha256"] = "0" * 64
    _write_json(paths["qualification"], qualification)

    with pytest.raises(ReleaseMetadataError, match="qualification_identity_mismatch"):
        verify_release_selection(
            model_root=paths["model_root"],
            manifest_path=paths["manifest"],
            profile_path=paths["profile"],
            runtime_profile_path=paths["runtime"],
            qualification_path=paths["qualification"],
        )


def test_release_selection_rejects_checkpoint_byte_change(tmp_path: Path) -> None:
    paths = _release_fixture(tmp_path, verified=False)
    paths["checkpoint"].write_bytes(b"tampered")

    with pytest.raises(ReleaseMetadataError, match="checkpoint_hash_mismatch"):
        verify_release_selection(
            model_root=paths["model_root"],
            manifest_path=paths["manifest"],
            profile_path=paths["profile"],
            runtime_profile_path=paths["runtime"],
            allow_unverified=True,
        )


def test_release_selection_rejects_runtime_identity_drift(tmp_path: Path) -> None:
    paths = _release_fixture(tmp_path, verified=False)
    runtime = json.loads(paths["runtime"].read_text(encoding="utf-8"))
    runtime["runtimeProfileId"] = "other-runtime"
    _write_json(paths["runtime"], runtime)

    with pytest.raises(ReleaseMetadataError, match="runtime_profile_id_mismatch"):
        verify_release_selection(
            model_root=paths["model_root"],
            manifest_path=paths["manifest"],
            profile_path=paths["profile"],
            runtime_profile_path=paths["runtime"],
            allow_unverified=True,
        )


def test_qualification_record_requires_evidence_for_passed_gate(tmp_path: Path) -> None:
    paths = _release_fixture(tmp_path, verified=True, all_gates_passed=True)
    qualification = json.loads(paths["qualification"].read_text(encoding="utf-8"))
    qualification["evidence"].pop("windows-x86_64-cpu")
    _write_json(paths["qualification"], qualification)

    with pytest.raises(ReleaseMetadataError, match="qualification_record_invalid"):
        load_qualification_record(paths["qualification"])


def test_qualification_record_rejects_unknown_fields(tmp_path: Path) -> None:
    paths = _release_fixture(tmp_path, verified=True, all_gates_passed=True)
    qualification = json.loads(paths["qualification"].read_text(encoding="utf-8"))
    qualification["unexpected"] = True
    _write_json(paths["qualification"], qualification)

    with pytest.raises(ReleaseMetadataError, match="qualification_record_invalid"):
        load_qualification_record(paths["qualification"])

def test_qualification_record_requires_integrity_hash_for_passed_evidence(
    tmp_path: Path,
) -> None:
    paths = _release_fixture(tmp_path, verified=True, all_gates_passed=True)
    qualification = json.loads(paths["qualification"].read_text(encoding="utf-8"))
    qualification["evidence"]["windows-x86_64-cpu"].pop("sha256")
    _write_json(paths["qualification"], qualification)

    with pytest.raises(ReleaseMetadataError, match="qualification_record_invalid"):
        load_qualification_record(paths["qualification"])


def test_qualification_record_rejects_malformed_evidence_hash(tmp_path: Path) -> None:
    paths = _release_fixture(tmp_path, verified=True, all_gates_passed=True)
    qualification = json.loads(paths["qualification"].read_text(encoding="utf-8"))
    qualification["evidence"]["windows-x86_64-cpu"]["sha256"] = "A" * 64
    _write_json(paths["qualification"], qualification)

    with pytest.raises(ReleaseMetadataError, match="qualification_record_invalid"):
        load_qualification_record(paths["qualification"])

