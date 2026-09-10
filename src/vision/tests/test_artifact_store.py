from __future__ import annotations

from hashlib import sha256
from uuid import UUID

import pytest

from mavi_vision.storage.artifact_store import StagingArtifactError, StagingArtifactStore


JOB_ID = UUID("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761")


def test_writes_atomic_artifact_and_returns_descriptor(tmp_path) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID)
    content = b"trajectory"

    descriptor = store.write_bytes(
        "trajectories/track-001.msgpack",
        content,
        "application/msgpack",
    )

    assert descriptor.storage_key == (
        "staging/018fa7b6-2b31-7f42-9f33-9fd9f6fdd761/"
        "trajectories/track-001.msgpack"
    )
    assert descriptor.size_bytes == len(content)
    assert descriptor.sha256 == sha256(content).hexdigest()
    assert (
        tmp_path
        / "staging"
        / str(JOB_ID)
        / "trajectories"
        / "track-001.msgpack"
    ).read_bytes() == content


def test_generates_canonical_thumbnail_and_trajectory_keys(tmp_path) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID)

    assert store.thumbnail_key("person_001") == (
        "staging/018fa7b6-2b31-7f42-9f33-9fd9f6fdd761/"
        "thumbnails/person_001.jpg"
    )
    assert store.trajectory_key("person_001") == (
        "staging/018fa7b6-2b31-7f42-9f33-9fd9f6fdd761/"
        "trajectories/person_001.msgpack"
    )


def test_rejects_unsafe_track_ids_and_relative_names(tmp_path) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID)

    with pytest.raises(StagingArtifactError):
        store.thumbnail_key("../escape")
    with pytest.raises(StagingArtifactError):
        store.write_bytes("../escape.bin", b"x", "application/octet-stream")
    with pytest.raises(StagingArtifactError):
        store.write_bytes("/absolute.bin", b"x", "application/octet-stream")
    with pytest.raises(StagingArtifactError):
        store.write_bytes("bad\\path.bin", b"x", "application/octet-stream")


def test_rejects_symlink_escape(tmp_path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    staging = tmp_path / "staging" / str(JOB_ID)
    staging.mkdir(parents=True)
    (staging / "escape").symlink_to(outside, target_is_directory=True)
    store = StagingArtifactStore(tmp_path, JOB_ID)

    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        store.write_bytes("escape/file.bin", b"x", "application/octet-stream")


def test_rejected_intermediate_symlink_does_not_create_outside_directories(tmp_path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside-tree"
    outside.mkdir()
    job_root = tmp_path / "staging" / str(JOB_ID)
    job_root.mkdir(parents=True)
    (job_root / "escape").symlink_to(outside, target_is_directory=True)
    store = StagingArtifactStore(tmp_path, JOB_ID)

    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        store.write_bytes("escape/new/file.bin", b"x", "application/octet-stream")

    assert not (outside / "new").exists()


def test_rejects_symlinked_job_root_and_cleanup_preserves_target(tmp_path) -> None:
    target = tmp_path / "videos"
    target.mkdir()
    source = target / "keep.mp4"
    source.write_bytes(b"keep")
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / str(JOB_ID)).symlink_to(target, target_is_directory=True)

    store = StagingArtifactStore(tmp_path, JOB_ID)

    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        store.write_bytes("thumbnails/a.jpg", b"x", "image/jpeg")
    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        store.cleanup()

    assert source.read_bytes() == b"keep"


def test_cleanup_removes_only_current_job_staging_area(tmp_path) -> None:
    other = tmp_path / "staging" / "other-job" / "keep.bin"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"keep")
    store = StagingArtifactStore(tmp_path, JOB_ID)
    store.write_bytes("data.bin", b"remove", "application/octet-stream")

    store.cleanup()

    assert not (tmp_path / "staging" / str(JOB_ID)).exists()
    assert other.read_bytes() == b"keep"
