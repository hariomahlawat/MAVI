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


def _offline_lock_bytes(
    variant: str,
    *,
    python_version: str,
    torch_version: str,
    torchvision_version: str,
) -> bytes:
    versions = {
        "av": "16.1.0",
        "mavi-vision": "0.1.0",
        "mmcv": "2.1.0",
        "mmdet": "3.3.0",
        "mmengine": "0.10.7",
        "numpy": "2.5.3",
        "opencv-python": "5.0.0.93",
        "pillow": "11.3.0",
        "scipy": "1.18.1",
        "supervision": "0.30.2",
        "torch": torch_version,
        "torchvision": torchvision_version,
        "trackers": "2.6.0",
    }
    rows = [
        "# schema: mavi-offline-lock-v1",
        f"# platform-variant: {variant}",
        f"# python-version: {python_version}",
    ]
    for name, version in sorted(versions.items()):
        digest = _sha(f"{variant}:{name}:{version}".encode("utf-8"))
        rows.append(f"{name}=={version} --hash=sha256:{digest}")
    return ("\n".join(rows) + "\n").encode("utf-8")


def _profile_payload() -> dict:
    return {
        "schemaVersion": "1.0",
        "profileId": "phase1-detection-tracking-v1",
        "profileVersion": "1.1.0-candidate",
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
            "referenceFrameRate": 30.0,
            "trackActivationThreshold": 0.7,
            "highConfidenceThreshold": 0.6,
            "minimumIouThreshold": 0.1,
            "minimumConsecutiveFrames": 2,
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
    runtime_qualified = verified
    platform_variants = {
        "linux-x86_64-cpu": {
            "status": "qualified-hosted-cpu",
            "workflowRunId": "1001",
            "jobId": "2001",
            "evidenceHeadSha": "1" * 40,
            "resolvedConfigSha256": config_hash,
            "pythonIdentity": {
                "version": "3.12.14",
                "implementation": "CPython",
                "build": ["main", "fixture"],
                "compiler": "GCC fixture",
            },
            "binaryVersions": {
                "torch": "2.6.0+cpu",
                "torchvision": "0.21.0+cpu",
            },
        },
        "windows-x86_64-cpu": {
            "status": "qualified-hosted-cpu",
            "workflowRunId": "1002",
            "jobId": "2002",
            "evidenceHeadSha": "2" * 40,
            "resolvedConfigSha256": config_hash,
            "pythonIdentity": {
                "version": "3.12.10",
                "implementation": "CPython",
                "build": ["fixture", "fixture"],
                "compiler": "MSC fixture",
            },
            "binaryVersions": {
                "torch": "2.6.0+cpu",
                "torchvision": "0.21.0+cpu",
            },
        },
        "linux-x86_64-cuda": (
            {
                "status": "qualified-hardware",
                "workflowRunId": "1003",
                "jobId": "2003",
                "evidenceHeadSha": "3" * 40,
                "resolvedConfigSha256": config_hash,
                "pythonIdentity": {
                    "version": "3.12.14",
                    "implementation": "CPython",
                    "build": ["fixture", "fixture"],
                    "compiler": "qualified fixture",
                },
                "binaryVersions": {
                    "torch": "2.6.0+cu124",
                    "torchvision": "0.21.0+cu124",
                },
            }
            if runtime_qualified
            else {"status": "pending-hardware-qualification"}
        ),
        "windows-x86_64-cuda": (
            {
                "status": "qualified-hardware",
                "workflowRunId": "1004",
                "jobId": "2004",
                "evidenceHeadSha": "4" * 40,
                "resolvedConfigSha256": config_hash,
                "pythonIdentity": {
                    "version": "3.12.14",
                    "implementation": "CPython",
                    "build": ["fixture", "fixture"],
                    "compiler": "qualified fixture",
                },
                "binaryVersions": {
                    "torch": "2.6.0+cu124",
                    "torchvision": "0.21.0+cu124",
                },
            }
            if runtime_qualified
            else {"status": "pending-hardware-qualification"}
        ),
    }
    release_lock_variants = (
        "linux-x86_64-cpu",
        "windows-x86_64-cpu",
        "linux-x86_64-cuda",
        "windows-x86_64-cuda",
    )
    lock_payloads: dict[str, bytes] = {}
    if runtime_qualified:
        lock_dir = tmp_path / "locks"
        lock_dir.mkdir()
        for variant in release_lock_variants:
            variant_identity = platform_variants[variant]
            binary_versions = variant_identity["binaryVersions"]
            python_version = variant_identity["pythonIdentity"]["version"]
            payload = _offline_lock_bytes(
                variant,
                python_version=python_version,
                torch_version=binary_versions["torch"],
                torchvision_version=binary_versions["torchvision"],
            )
            lock_payloads[variant] = payload
            (lock_dir / f"{variant}.lock").write_bytes(payload)

    release_locks = {
        variant: (
            {
                "status": "qualified-offline-lock",
                "artifact": f"locks/{variant}.lock",
                "sha256": _sha(lock_payloads[variant]),
            }
            if runtime_qualified
            else {
                "status": (
                    "pending-wheelhouse-freeze"
                    if variant.endswith("-cpu")
                    else "pending-hardware-qualification"
                )
            }
        )
        for variant in release_lock_variants
    }
    _write_json(
        runtime_path,
        {
            "schemaVersion": "1.0",
            "runtimeProfileId": "runtime-a",
            "qualificationStatus": "qualified" if runtime_qualified else "partial",
            "pythonMinor": "3.12",
            "semanticGraph": {
                "torch": "2.6.0",
                "torchvision": "0.21.0",
                "mmcv": "2.1.0",
                "mmengine": "0.10.7",
                "mmdet": "3.3.0",
                "trackers": "2.6.0",
                "supervision": "0.30.2",
                "scipy": "1.18.1",
                "numpy": "2.5.3",
                "opencv": "5.0.0",
                "av": "16.1.0",
                "opencvPython": "5.0.0.93",
                "pillow": "11.3.0",
            },
            "checkpoint": {
                "publisher": "OpenMMLab",
                "artifact": "checkpoint.pth",
                "sha256": checkpoint_hash,
            },
            "platformVariants": platform_variants,
            "releaseLocks": release_locks,
            "resolvedConfig": {
                "artifact": "config.py",
                "sha256": config_hash,
                "format": "python",
                "encoding": "utf-8",
                "lineEndings": "lf",
                "selfContained": True,
            },
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
    assert selection.runtime_qualification_status == "qualified"
    assert selection.runtime_semantic_graph["torch"] == "2.6.0"
    assert (
        selection.runtime_platform_variants["linux-x86_64-cpu"].status
        == "qualified-hosted-cpu"
    )
    assert selection.runtime_platform_variants["linux-x86_64-cpu"].binary_versions == {
        "torch": "2.6.0+cpu",
        "torchvision": "0.21.0+cpu",
    }
    assert (
        selection.runtime_platform_variants["linux-x86_64-cuda"].status
        == "qualified-hardware"
    )
    assert (
        selection.runtime_release_locks["linux-x86_64-cpu"].status
        == "qualified-offline-lock"
    )
    assert (
        selection.runtime_release_locks["linux-x86_64-cpu"].sha256
        == _sha((tmp_path / "locks/linux-x86_64-cpu.lock").read_bytes())
    )


def test_runtime_profile_requires_binary_versions_for_qualified_variant(
    tmp_path: Path,
) -> None:
    paths = _release_fixture(tmp_path, verified=False)
    runtime = json.loads(paths["runtime"].read_text(encoding="utf-8"))
    runtime["platformVariants"]["linux-x86_64-cpu"].pop("binaryVersions")
    _write_json(paths["runtime"], runtime)

    with pytest.raises(ReleaseMetadataError, match="runtime_profile_invalid"):
        verify_release_selection(
            model_root=paths["model_root"],
            manifest_path=paths["manifest"],
            profile_path=paths["profile"],
            runtime_profile_path=paths["runtime"],
            allow_unverified=True,
        )


def test_runtime_profile_rejects_binary_semantic_version_mismatch(
    tmp_path: Path,
) -> None:
    paths = _release_fixture(tmp_path, verified=False)
    runtime = json.loads(paths["runtime"].read_text(encoding="utf-8"))
    runtime["platformVariants"]["linux-x86_64-cpu"]["binaryVersions"]["torch"] = (
        "2.7.0+cpu"
    )
    _write_json(paths["runtime"], runtime)

    with pytest.raises(ReleaseMetadataError, match="runtime_profile_invalid"):
        verify_release_selection(
            model_root=paths["model_root"],
            manifest_path=paths["manifest"],
            profile_path=paths["profile"],
            runtime_profile_path=paths["runtime"],
            allow_unverified=True,
        )


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
    assert selection.runtime_qualification_status == "partial"
    assert selection.runtime_semantic_graph["mmdet"] == "3.3.0"
    assert (
        selection.runtime_release_locks["linux-x86_64-cpu"].status
        == "pending-wheelhouse-freeze"
    )


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

def test_verified_release_requires_qualified_runtime_profile(tmp_path: Path) -> None:
    paths = _release_fixture(tmp_path, verified=True, all_gates_passed=True)
    runtime = json.loads(paths["runtime"].read_text(encoding="utf-8"))
    runtime["qualificationStatus"] = "partial"
    _write_json(paths["runtime"], runtime)

    qualification = json.loads(paths["qualification"].read_text(encoding="utf-8"))
    qualification["runtimeProfileSha256"] = _sha(paths["runtime"].read_bytes())
    _write_json(paths["qualification"], qualification)

    with pytest.raises(ReleaseMetadataError, match="runtime_profile_not_qualified"):
        verify_release_selection(
            model_root=paths["model_root"],
            manifest_path=paths["manifest"],
            profile_path=paths["profile"],
            runtime_profile_path=paths["runtime"],
            qualification_path=paths["qualification"],
        )

