"""The release-artefact primitives every v2 manifest resolves through.

The v1 manifest loader was deleted at the S2a.3 cut-over (plan §5: no runtime
dual reader); its schema survives only in ``tools/vision/v1_release_schemas.py``
for the one-shot migration generator. What remains here is shared by the v2
Model Pack manifest: logical path and digest rules and contained resolution.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import mavi_vision.runtime.manifest as manifest_module
from mavi_vision.runtime.manifest import (
    ArtifactRef,
    ReleaseMetadataError,
    resolve_release_artifact,
    validate_logical_relative_path,
    validate_sha256_hex,
)
from mavi_vision.runtime.model_manifest_v2 import load_model_manifest_v2
from tests.component_binding_v2_fixtures import V1_MANIFEST


def test_the_runtime_has_no_v1_manifest_reader() -> None:
    for retired in ("ModelManifest", "load_model_manifest", "_ModelManifestSchema"):
        assert not hasattr(manifest_module, retired), retired


def test_the_last_v1_manifest_is_refused_by_the_only_reader() -> None:
    with pytest.raises(ReleaseMetadataError, match="model_manifest_schema_unsupported"):
        load_model_manifest_v2(V1_MANIFEST)


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
def test_unsafe_artifact_paths_are_rejected(relative_path: str) -> None:
    with pytest.raises(ValueError, match="release_artifact_path_invalid"):
        validate_logical_relative_path(relative_path)


@pytest.mark.parametrize("digest", ["ABC" * 21 + "A", "g" * 64, "a" * 63])
def test_malformed_sha256_is_rejected(digest: str) -> None:
    with pytest.raises(ValueError, match="sha256_invalid"):
        validate_sha256_hex(digest)


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
