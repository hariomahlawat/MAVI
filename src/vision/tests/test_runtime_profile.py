from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mavi_vision.runtime.manifest import ReleaseMetadataError
from mavi_vision.runtime.qualification import verify_runtime_release_locks
from mavi_vision.runtime.runtime_profile_v2 import load_runtime_profile_v2 as load_runtime_profile

# The runtime-family rules below are the ones S2a.3 kept: since the cut-over a
# runtime profile is a v2 family profile and carries no model artefact
# (checkpoint, resolved config), so those v1 rules moved to the Model Pack.


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _qualified_cpu_lock_bytes() -> bytes:
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
        "torch": "2.6.0+cpu",
        "torchvision": "0.21.0+cpu",
        "trackers": "2.6.0",
    }
    rows = [
        "# schema: mavi-offline-lock-v1",
        "# platform-variant: linux-x86_64-cpu",
        "# python-version: 3.12.14",
    ]
    for name, version in sorted(versions.items()):
        digest = hashlib.sha256(
            f"{name}:{version}".encode("utf-8")
        ).hexdigest()
        rows.append(f"{name}=={version} --hash=sha256:{digest}")
    return ("\n".join(rows) + "\n").encode("utf-8")


def _runtime_payload() -> dict:
    return {
        "schemaVersion": "2.0",
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
        "platformVariants": {
            "linux-x86_64-cpu": {
                "status": "qualified-hosted-cpu",
                "workflowRunId": "1001",
                "jobId": "2001",
                "evidenceHeadSha": "1" * 40,
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
    ("mutation", "code"),
    [
        (lambda payload: payload.pop("semanticGraph"), "runtime_profile_invalid"),
        (lambda payload: payload.__setitem__("unexpected", True), "runtime_profile_invalid"),
        (lambda payload: payload["semanticGraph"].pop("mmcv"), "runtime_profile_invalid"),
        (lambda payload: payload["platformVariants"].pop("windows-x86_64-cuda"), "runtime_platform_variants_incomplete"),
        (lambda payload: payload["releaseLocks"].pop("linux-x86_64-cuda"), "runtime_release_locks_incomplete"),
    ],
)
def test_runtime_profile_rejects_incomplete_or_unknown_metadata(
    tmp_path: Path,
    mutation,
    code: str,
) -> None:
    payload = _runtime_payload()
    mutation(payload)
    path = tmp_path / "runtime.json"
    _write(path, payload)

    with pytest.raises(ReleaseMetadataError, match=code):
        load_runtime_profile(path)


def test_qualified_platform_requires_integrity_evidence(tmp_path: Path) -> None:
    payload = _runtime_payload()
    payload["platformVariants"]["linux-x86_64-cpu"].pop("evidenceHeadSha")
    path = tmp_path / "runtime.json"
    _write(path, payload)

    with pytest.raises(ReleaseMetadataError, match="runtime_platform_evidence_required"):
        load_runtime_profile(path)


@pytest.mark.parametrize(
    ("section", "value"),
    [
        ("checkpoint", {"publisher": "OpenMMLab", "artifact": "checkpoint.pth", "sha256": "a" * 64}),
        ("resolvedConfig", {"artifact": "config.py", "sha256": "a" * 64}),
    ],
)
def test_a_family_profile_cannot_carry_a_model_artefact(tmp_path: Path, section: str, value: dict) -> None:
    payload = _runtime_payload()
    payload[section] = value
    path = tmp_path / "runtime.json"
    _write(path, payload)

    with pytest.raises(ReleaseMetadataError, match="runtime_profile_invalid"):
        load_runtime_profile(path)


def test_a_variant_cannot_carry_a_resolved_config_digest(tmp_path: Path) -> None:
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

    with pytest.raises(ReleaseMetadataError, match="runtime_qualified_with_pending_gate"):
        load_runtime_profile(path)


def test_qualified_release_lock_requires_artifact_and_hash(tmp_path: Path) -> None:
    payload = _runtime_payload()
    payload["releaseLocks"]["linux-x86_64-cpu"] = {
        "status": "qualified-offline-lock",
        "artifact": "locks/linux-x86_64-cpu.lock",
    }
    path = tmp_path / "runtime.json"
    _write(path, payload)

    with pytest.raises(ReleaseMetadataError, match="runtime_release_lock_evidence_required"):
        load_runtime_profile(path)

def test_qualified_runtime_lock_bytes_are_verified(tmp_path: Path) -> None:
    payload = _runtime_payload()
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    lock_path = lock_dir / "linux-x86_64-cpu.lock"
    lock_path.write_bytes(_qualified_cpu_lock_bytes())
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
    lock_path.write_bytes(_qualified_cpu_lock_bytes())
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

def test_qualified_platform_requires_exact_python_identity(tmp_path: Path) -> None:
    payload = _runtime_payload()
    payload["platformVariants"]["linux-x86_64-cpu"].pop("pythonIdentity")
    path = tmp_path / "runtime.json"
    _write(path, payload)

    with pytest.raises(ReleaseMetadataError, match="runtime_platform_evidence_required"):
        load_runtime_profile(path)


def test_python_identity_must_match_declared_minor(tmp_path: Path) -> None:
    payload = _runtime_payload()
    payload["platformVariants"]["linux-x86_64-cpu"]["pythonIdentity"]["version"] = "3.11.9"
    path = tmp_path / "runtime.json"
    _write(path, payload)

    with pytest.raises(ReleaseMetadataError, match="runtime_python_minor_identity_mismatch"):
        load_runtime_profile(path)

def test_cuda_variant_rejects_hosted_cpu_status(tmp_path: Path) -> None:
    payload = _runtime_payload()
    payload["platformVariants"]["linux-x86_64-cuda"] = {
        "status": "qualified-hosted-cpu",
        "workflowRunId": "1003",
        "jobId": "2003",
        "evidenceHeadSha": "3" * 40,
        "pythonIdentity": {
            "version": "3.12.14",
            "implementation": "CPython",
            "build": ["fixture", "fixture"],
            "compiler": "fixture",
        },
        "binaryVersions": {"torch": "2.6.0+cu124", "torchvision": "0.21.0+cu124"},
    }
    path = tmp_path / "runtime.json"
    _write(path, payload)

    with pytest.raises(ReleaseMetadataError, match="runtime_cuda_variant_status_invalid"):
        load_runtime_profile(path)


def test_cpu_variant_rejects_hardware_qualification_status(tmp_path: Path) -> None:
    payload = _runtime_payload()
    payload["platformVariants"]["linux-x86_64-cpu"]["status"] = "qualified-hardware"
    path = tmp_path / "runtime.json"
    _write(path, payload)

    with pytest.raises(ReleaseMetadataError, match="runtime_cpu_variant_status_invalid"):
        load_runtime_profile(path)

