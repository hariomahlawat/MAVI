from __future__ import annotations

from hashlib import sha256
import os
from uuid import UUID

import pytest

import mavi_vision.storage.artifact_store_posix as artifact_store_posix_module
from mavi_vision.storage.artifact_store import StagingArtifactError, StagingArtifactStore


JOB_ID = UUID("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761")
ATTEMPT = 1
ATTEMPT_NAME = "attempt-0001"


def test_writes_atomic_artifact_and_returns_descriptor(tmp_path) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)
    content = b"trajectory"

    descriptor = store.write_bytes(
        "trajectories/track-001.msgpack",
        content,
        "application/msgpack",
    )

    assert descriptor.storage_key == (
        "staging/018fa7b6-2b31-7f42-9f33-9fd9f6fdd761/attempt-0001/"
        "trajectories/track-001.msgpack"
    )
    assert descriptor.size_bytes == len(content)
    assert descriptor.sha256 == sha256(content).hexdigest()
    assert (
        tmp_path
        / "staging"
        / str(JOB_ID)
        / ATTEMPT_NAME
        / "trajectories"
        / "track-001.msgpack"
    ).read_bytes() == content


def test_generates_canonical_thumbnail_and_trajectory_keys(tmp_path) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)

    assert store.job_id == JOB_ID
    assert store.attempt_count == ATTEMPT
    assert store.thumbnail_key("person_001") == (
        "staging/018fa7b6-2b31-7f42-9f33-9fd9f6fdd761/attempt-0001/"
        "thumbnails/person_001.jpg"
    )
    assert store.trajectory_key("person_001") == (
        "staging/018fa7b6-2b31-7f42-9f33-9fd9f6fdd761/attempt-0001/"
        "trajectories/person_001.msgpack"
    )


def test_rejects_non_positive_attempt_count(tmp_path) -> None:
    with pytest.raises(ValueError, match="attempt_count_must_be_positive"):
        StagingArtifactStore(tmp_path, JOB_ID, 0)


def test_rejects_unsafe_track_ids_and_relative_names(tmp_path) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)

    with pytest.raises(StagingArtifactError):
        store.thumbnail_key("../escape")
    with pytest.raises(StagingArtifactError):
        store.write_bytes("../escape.bin", b"x", "application/octet-stream")
    with pytest.raises(StagingArtifactError):
        store.write_bytes("/absolute.bin", b"x", "application/octet-stream")
    with pytest.raises(StagingArtifactError):
        store.write_bytes("bad\\path.bin", b"x", "application/octet-stream")


@pytest.mark.skipif(os.name != "posix", reason="POSIX no-follow fixture")
def test_rejects_symlink_escape(tmp_path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    attempt_root = tmp_path / "staging" / str(JOB_ID) / ATTEMPT_NAME
    attempt_root.mkdir(parents=True)
    (attempt_root / "escape").symlink_to(outside, target_is_directory=True)
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)

    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        store.write_bytes("escape/file.bin", b"x", "application/octet-stream")


@pytest.mark.skipif(os.name != "posix", reason="POSIX no-follow fixture")
def test_rejected_intermediate_symlink_does_not_create_outside_directories(tmp_path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside-tree"
    outside.mkdir()
    attempt_root = tmp_path / "staging" / str(JOB_ID) / ATTEMPT_NAME
    attempt_root.mkdir(parents=True)
    (attempt_root / "escape").symlink_to(outside, target_is_directory=True)
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)

    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        store.write_bytes("escape/new/file.bin", b"x", "application/octet-stream")

    assert not (outside / "new").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX no-follow fixture")
def test_rejects_symlinked_job_root_and_cleanup_preserves_target(tmp_path) -> None:
    target = tmp_path / "videos"
    target.mkdir()
    source = target / "keep.mp4"
    source.write_bytes(b"keep")
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / str(JOB_ID)).symlink_to(target, target_is_directory=True)

    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)

    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        store.write_bytes("thumbnails/a.jpg", b"x", "image/jpeg")
    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        store.cleanup()

    assert source.read_bytes() == b"keep"


@pytest.mark.skipif(os.name != "posix", reason="POSIX no-follow fixture")
def test_directory_swap_during_write_cannot_redirect_artifact_outside_root(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)
    store.write_bytes("safe/seed.bin", b"seed", "application/octet-stream")

    attempt_root = tmp_path / "staging" / str(JOB_ID) / ATTEMPT_NAME
    safe_parent = attempt_root / "safe"
    detached_parent = attempt_root / "safe-detached"
    outside = tmp_path.parent / f"{tmp_path.name}-outside-race"
    outside.mkdir()

    real_open = artifact_store_posix_module.os.open
    swapped = False

    def racing_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if (
            not swapped
            and isinstance(path, str)
            and path.startswith(".race.bin.")
            and dir_fd is not None
        ):
            safe_parent.rename(detached_parent)
            safe_parent.symlink_to(outside, target_is_directory=True)
            swapped = True
        if dir_fd is None:
            return real_open(path, flags, mode)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(artifact_store_posix_module.os, "open", racing_open)

    with pytest.raises(StagingArtifactError, match="staging_path_(?:race|escape)"):
        store.write_bytes("safe/race.bin", b"payload", "application/octet-stream")

    assert swapped is True
    assert not (outside / "race.bin").exists()
    assert not (detached_parent / "race.bin").exists()


def test_attempts_with_same_relative_artifact_are_isolated(tmp_path) -> None:
    first = StagingArtifactStore(tmp_path, JOB_ID, 1)
    second = StagingArtifactStore(tmp_path, JOB_ID, 2)

    first_descriptor = first.write_bytes("same.bin", b"attempt-one", "application/octet-stream")
    second_descriptor = second.write_bytes("same.bin", b"attempt-two", "application/octet-stream")

    first_path = tmp_path.joinpath(*first_descriptor.storage_key.split("/"))
    second_path = tmp_path.joinpath(*second_descriptor.storage_key.split("/"))
    assert first_path.read_bytes() == b"attempt-one"
    assert second_path.read_bytes() == b"attempt-two"
    assert first_path != second_path

    first.cleanup()

    assert not first_path.exists()
    assert second_path.read_bytes() == b"attempt-two"


def test_cleanup_removes_only_current_attempt_staging_area(tmp_path) -> None:
    other_job = tmp_path / "staging" / "other-job" / "keep.bin"
    other_job.parent.mkdir(parents=True)
    other_job.write_bytes(b"keep")
    other_attempt = StagingArtifactStore(tmp_path, JOB_ID, 2)
    other_descriptor = other_attempt.write_bytes("keep.bin", b"other-attempt", "application/octet-stream")
    other_attempt_path = tmp_path.joinpath(*other_descriptor.storage_key.split("/"))
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)
    store.write_bytes("data.bin", b"remove", "application/octet-stream")

    store.cleanup()

    assert not (tmp_path / "staging" / str(JOB_ID) / ATTEMPT_NAME).exists()
    assert other_attempt_path.read_bytes() == b"other-attempt"
    assert other_job.read_bytes() == b"keep"
