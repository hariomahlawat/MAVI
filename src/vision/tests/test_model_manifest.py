from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mavi_vision.runtime.manifest import (
    ArtifactRef,
    ReleaseMetadataError,
    load_model_manifest,
    resolve_release_artifact,
)


def _manifest_payload() -> dict:
    digest = "a" * 64
    return {
        "schemaVersion": "1.0",
        "modelId": "model-a",
        "modelVersion": "1.0.0",
        "purpose": "test",
        "backend": "mmdetection",
        "architecture": "rtmdet-m",
        "classVocabulary": ["person", "car", "motorcycle", "bus", "truck"],
        "checkpoint": {"relativePath": "release/checkpoint.pth", "sha256": digest},
        "resolvedConfig": {"relativePath": "release/config.py", "sha256": digest},
        "runtimeProfileId": "runtime-a",
        "verificationStatus": "unverified",
        "qualificationId": None,
    }


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")


def test_model_manifest_loads_strict_valid_metadata(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    _write_json(path, _manifest_payload())

    manifest = load_model_manifest(path)

    assert manifest.model_id == "model-a"
    assert manifest.class_vocabulary == ("person", "car", "motorcycle", "bus", "truck")
    assert manifest.verification_status == "unverified"


@pytest.mark.parametrize(
    "relative_path",
    [
        "/absolute/checkpoint.pth",
        "../checkpoint.pth",
        "release/../checkpoint.pth",
        "release\\checkpoint.pth",
        "C:/checkpoint.pth",
        "model://checkpoint",
        "release//checkpoint.pth",
    ],
)
def test_model_manifest_rejects_unsafe_artifact_paths(
    tmp_path: Path,
    relative_path: str,
) -> None:
    payload = _manifest_payload()
    payload["checkpoint"]["relativePath"] = relative_path
    path = tmp_path / "manifest.json"
    _write_json(path, payload)

    with pytest.raises(ReleaseMetadataError, match="model_manifest_invalid"):
        load_model_manifest(path)


@pytest.mark.parametrize("digest", ["ABC" * 21 + "A", "g" * 64, "a" * 63])
def test_model_manifest_rejects_malformed_sha256(tmp_path: Path, digest: str) -> None:
    payload = _manifest_payload()
    payload["checkpoint"]["sha256"] = digest
    path = tmp_path / "manifest.json"
    _write_json(path, payload)

    with pytest.raises(ReleaseMetadataError, match="model_manifest_invalid"):
        load_model_manifest(path)


@pytest.mark.parametrize("vocabulary", [[], ["person", "person"], ["person", ""]])
def test_model_manifest_rejects_invalid_vocabulary(
    tmp_path: Path,
    vocabulary: list[str],
) -> None:
    payload = _manifest_payload()
    payload["classVocabulary"] = vocabulary
    path = tmp_path / "manifest.json"
    _write_json(path, payload)

    with pytest.raises(ReleaseMetadataError, match="model_manifest_invalid"):
        load_model_manifest(path)


def test_verified_manifest_requires_qualification_id(tmp_path: Path) -> None:
    payload = _manifest_payload()
    payload["verificationStatus"] = "verified"
    path = tmp_path / "manifest.json"
    _write_json(path, payload)

    with pytest.raises(ReleaseMetadataError, match="model_manifest_invalid"):
        load_model_manifest(path)


def test_model_manifest_rejects_unknown_fields(tmp_path: Path) -> None:
    payload = _manifest_payload()
    payload["unexpected"] = True
    path = tmp_path / "manifest.json"
    _write_json(path, payload)

    with pytest.raises(ReleaseMetadataError, match="model_manifest_invalid"):
        load_model_manifest(path)


def test_release_artifact_resolution_rejects_link_component(tmp_path: Path) -> None:
    root = tmp_path / "models"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "checkpoint.pth").write_bytes(b"checkpoint")

    link = root / "release"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    artifact = ArtifactRef(
        relative_path="release/checkpoint.pth",
        sha256=hashlib.sha256(b"checkpoint").hexdigest(),
    )

    with pytest.raises(ReleaseMetadataError, match="release_artifact_link_forbidden"):
        resolve_release_artifact(root, artifact)


def test_release_artifact_resolution_returns_contained_file(tmp_path: Path) -> None:
    root = tmp_path / "models"
    release = root / "release"
    release.mkdir(parents=True)
    checkpoint = release / "checkpoint.pth"
    checkpoint.write_bytes(b"checkpoint")
    artifact = ArtifactRef(
        relative_path="release/checkpoint.pth",
        sha256=hashlib.sha256(b"checkpoint").hexdigest(),
    )

    assert resolve_release_artifact(root, artifact) == checkpoint.resolve()
