from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mavi_vision.runtime.manifest import ReleaseMetadataError
from mavi_vision.runtime.qualification import (
    load_runtime_profile,
    verify_runtime_release_locks,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _runtime_payload() -> dict:
    config_hash = _sha("config")
    return {
        "schemaVersion": "1.0",
        "runtimeProfileId": "runtime-a",
        "qualificationStatus": "partial",
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
            "sha256": _sha("checkpoint"),
        },
        "platformVariants": {
            "linux-x86_64-cpu": {
                "status": "qualified-hosted-cpu",
                "workflowRunId": "1001",
                "jobId": "2001",
                "evidenceHeadSha": "1" * 40,
                "resolvedConfigSha256": config_hash,
            },
            "windows-x86_64-cpu": {
                "status": "qualified-hosted-cpu",
                "workflowRunId": "1002",
                "jobId": "2002",
                "evidenceHeadSha": "2" * 40,
                "resolvedConfigSha256": config_hash,
            },
            "linux-x86_64-cuda": {
                "status": "pending-hardware-qualification",
            },
            "windows-x86_64-cuda": {
                "status": "pending-hardware-qualification",
            },
        },
        "releaseLocks": {
            "linux-x86_64-cpu": {"status": "pending-wheelhouse-freeze"},
            "windows-x86_64-cpu": {"status": "pending-wheelhouse-freeze"},
            "linux-x86_64-cuda": {"status": "pending-hardware-qualification"},
            "windows-x86_64-cuda": {"status": "pending-hardware-qualification"},
        },
        "resolvedConfig": {
            "artifact": "config.py",
            "sha256": config_hash,
            "format": "python",
            "encoding": "utf-8",
            "lineEndings": "lf",
            "selfContained": True,
        },
    }


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")


def test_runtime_profile_loads_complete_partial_profile(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json"
    _write(path, _runtime_payload())

    profile = load_runtime_profile(path)

    assert profile.runtime_profile_id == "runtime-a"
    assert profile.qualification_status == "partial"
    assert profile.semantic_graph.mmdet == "3.3.0"
    assert set(profile.platform_variants) == {
        "linux-x86_64-cpu",
        "windows-x86_64-cpu",
        "linux-x86_64-cuda",
        "windows-x86_64-cuda",
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.pop("semanticGraph"),
        lambda payload: payload.__setitem__("unexpected", True),
        lambda payload: payload["semanticGraph"].pop("mmcv"),
        lambda payload: payload["platformVariants"].pop("windows-x86_64-cuda"),
        lambda payload: payload["releaseLocks"].pop("linux-x86_64-cuda"),
    ],
)
def test_runtime_profile_rejects_incomplete_or_unknown_metadata(
    tmp_path: Path,
    mutation,
) -> None:
    payload = _runtime_payload()
    mutation(payload)
    path = tmp_path / "runtime.json"
    _write(path, payload)

    with pytest.raises(ReleaseMetadataError, match="runtime_profile_invalid"):
        load_runtime_profile(path)


def test_qualified_platform_requires_integrity_evidence(tmp_path: Path) -> None:
    payload = _runtime_payload()
    payload["platformVariants"]["linux-x86_64-cpu"].pop("evidenceHeadSha")
    path = tmp_path / "runtime.json"
    _write(path, payload)

    with pytest.raises(ReleaseMetadataError, match="runtime_profile_invalid"):
        load_runtime_profile(path)


def test_runtime_profile_rejects_variant_config_hash_drift(tmp_path: Path) -> None:
    payload = _runtime_payload()
    payload["platformVariants"]["linux-x86_64-cpu"]["resolvedConfigSha256"] = "0" * 64
    path = tmp_path / "runtime.json"
    _write(path, payload)

    with pytest.raises(ReleaseMetadataError, match="runtime_profile_invalid"):
        load_runtime_profile(path)


def test_qualified_runtime_cannot_retain_pending_platform_or_lock(tmp_path: Path) -> None:
    payload = _runtime_payload()
    payload["qualificationStatus"] = "qualified"
    path = tmp_path / "runtime.json"
    _write(path, payload)

    with pytest.raises(ReleaseMetadataError, match="runtime_profile_invalid"):
        load_runtime_profile(path)


def test_qualified_release_lock_requires_artifact_and_hash(tmp_path: Path) -> None:
    payload = _runtime_payload()
    payload["releaseLocks"]["linux-x86_64-cpu"] = {
        "status": "qualified-offline-lock",
        "artifact": "locks/linux-x86_64-cpu.lock",
    }
    path = tmp_path / "runtime.json"
    _write(path, payload)

    with pytest.raises(ReleaseMetadataError, match="runtime_profile_invalid"):
        load_runtime_profile(path)

def test_qualified_runtime_lock_bytes_are_verified(tmp_path: Path) -> None:
    payload = _runtime_payload()
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    lock_path = lock_dir / "linux-x86_64-cpu.lock"
    lock_path.write_bytes(b"package==1.0\n")
    payload["releaseLocks"]["linux-x86_64-cpu"] = {
        "status": "qualified-offline-lock",
        "artifact": "locks/linux-x86_64-cpu.lock",
        "sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
    }
    runtime_path = tmp_path / "runtime.json"
    _write(runtime_path, payload)
    profile = load_runtime_profile(runtime_path)

    verified = verify_runtime_release_locks(runtime_path, profile)

    assert verified["linux-x86_64-cpu"] == lock_path.resolve()


def test_qualified_runtime_lock_tamper_fails_closed(tmp_path: Path) -> None:
    payload = _runtime_payload()
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    lock_path = lock_dir / "linux-x86_64-cpu.lock"
    lock_path.write_bytes(b"package==1.0\n")
    payload["releaseLocks"]["linux-x86_64-cpu"] = {
        "status": "qualified-offline-lock",
        "artifact": "locks/linux-x86_64-cpu.lock",
        "sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
    }
    runtime_path = tmp_path / "runtime.json"
    _write(runtime_path, payload)
    profile = load_runtime_profile(runtime_path)
    lock_path.write_bytes(b"package==2.0\n")

    with pytest.raises(ReleaseMetadataError, match="runtime_release_lock_hash_mismatch"):
        verify_runtime_release_locks(runtime_path, profile)

