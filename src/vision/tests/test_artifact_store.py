from __future__ import annotations

from hashlib import sha256
import os
from uuid import UUID

import pytest

import mavi_vision.storage.artifact_store_posix as artifact_store_posix_module
from mavi_vision.storage.artifact_store import (
    StagingArtifactError,
    StagingArtifactStore,
    superseded_attempt_number,
)


JOB_ID = UUID("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761")
OTHER_JOB_ID = UUID("018fa7b6-2b31-7f42-9f33-9fd9f6fdd762")
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


# --- Superseded-attempt cleanup (S1.1) ----------------------------------------


def _staged(root, job_id, attempt: int, payload: bytes):
    descriptor = StagingArtifactStore(root, job_id, attempt).write_bytes(
        "thumbnails/person-000001.jpg", payload, "image/jpeg"
    )
    return root.joinpath(*descriptor.storage_key.split("/"))


def _job_dir(root, job_id=JOB_ID):
    return root / "staging" / str(job_id)


@pytest.mark.parametrize(
    ("name", "current", "expected"),
    [
        ("attempt-0001", 2, 1),
        ("attempt-0001", 3, 1),
        ("attempt-0002", 3, 2),
        ("attempt-12345", 12346, 12345),
        # Never the current or a later attempt.
        ("attempt-0002", 2, None),
        ("attempt-0003", 2, None),
        # Never anything this store does not itself produce.
        ("attempt-0000", 5, None),
        ("attempt-001", 5, None),
        ("attempt-00001", 5, None),
        ("attempt-0001.tmp", 5, None),
        ("attempt-0001 ", 5, None),
        ("Attempt-0001", 5, None),
        ("attempt-+001", 5, None),
        ("attempt-١٢٣٤", 9999, None),
        ("keep.bin", 5, None),
    ],
)
def test_superseded_attempt_selection_is_canonical_and_strictly_older(
    name, current, expected
) -> None:
    assert superseded_attempt_number(name, current) == expected


def test_cleanup_superseded_attempts_removes_only_older_attempts_of_this_job(
    tmp_path,
) -> None:
    first = _staged(tmp_path, JOB_ID, 1, b"one")
    second = _staged(tmp_path, JOB_ID, 2, b"two")
    current = _staged(tmp_path, JOB_ID, 3, b"three")
    later = _staged(tmp_path, JOB_ID, 4, b"four")
    other_job = _staged(tmp_path, OTHER_JOB_ID, 1, b"other")
    stray = _job_dir(tmp_path) / "attempt-001"
    stray.mkdir()
    (stray / "keep.bin").write_bytes(b"stray")

    StagingArtifactStore(tmp_path, JOB_ID, 3).cleanup_superseded_attempts()

    assert not first.exists() and not first.parent.parent.exists()
    assert not second.exists() and not second.parent.parent.exists()
    assert current.read_bytes() == b"three"
    assert later.read_bytes() == b"four"
    assert other_job.read_bytes() == b"other"
    assert (stray / "keep.bin").read_bytes() == b"stray"


def test_cleanup_superseded_attempts_is_a_noop_for_the_first_attempt(tmp_path) -> None:
    current = _staged(tmp_path, JOB_ID, 1, b"one")

    StagingArtifactStore(tmp_path, JOB_ID, 1).cleanup_superseded_attempts()

    assert current.read_bytes() == b"one"


def test_cleanup_superseded_attempts_tolerates_missing_staging(tmp_path) -> None:
    StagingArtifactStore(tmp_path, JOB_ID, 2).cleanup_superseded_attempts()

    assert not (tmp_path / "staging").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX no-follow fixture")
def test_cleanup_superseded_attempts_never_follows_a_linked_attempt(tmp_path) -> None:
    target = tmp_path / "videos"
    target.mkdir()
    keep = target / "keep.mp4"
    keep.write_bytes(b"keep")
    job = _job_dir(tmp_path)
    job.mkdir(parents=True)
    (job / "attempt-0001").symlink_to(target, target_is_directory=True)

    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        StagingArtifactStore(tmp_path, JOB_ID, 2).cleanup_superseded_attempts()

    assert keep.read_bytes() == b"keep"


@pytest.mark.skipif(os.name != "posix", reason="POSIX no-follow fixture")
def test_cleanup_superseded_attempts_does_not_follow_links_inside_an_attempt(
    tmp_path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    keep = outside / "keep.bin"
    keep.write_bytes(b"keep")
    stale = _staged(tmp_path, JOB_ID, 1, b"one")
    (stale.parent / "escape").symlink_to(outside, target_is_directory=True)

    StagingArtifactStore(tmp_path, JOB_ID, 2).cleanup_superseded_attempts()

    assert not stale.parent.parent.exists()
    assert keep.read_bytes() == b"keep"


@pytest.mark.skipif(os.name != "posix", reason="POSIX no-follow fixture")
def test_cleanup_superseded_attempts_rejects_a_linked_job_root(tmp_path) -> None:
    target = tmp_path / "videos"
    (target / "attempt-0001").mkdir(parents=True)
    keep = target / "attempt-0001" / "keep.mp4"
    keep.write_bytes(b"keep")
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / str(JOB_ID)).symlink_to(target, target_is_directory=True)

    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        StagingArtifactStore(tmp_path, JOB_ID, 2).cleanup_superseded_attempts()

    assert keep.read_bytes() == b"keep"


# --- S1.2b internal primitives: streamed publish, append, bounded read, leaf remove


def _attempt_dir(root, attempt: int = ATTEMPT):
    return root / "staging" / str(JOB_ID) / f"attempt-{attempt:04d}"


def test_write_stream_publishes_concatenation_with_incremental_descriptor(tmp_path) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)
    chunks = [b"alpha", b"", bytearray(b"-beta-"), memoryview(b"gamma")]
    content = b"alpha-beta-gamma"

    descriptor = store.write_stream("trajectories/t.msgpack", iter(chunks), "application/msgpack")

    assert descriptor.storage_key.endswith("/attempt-0001/trajectories/t.msgpack")
    assert descriptor.size_bytes == len(content)
    assert descriptor.sha256 == sha256(content).hexdigest()
    assert (_attempt_dir(tmp_path) / "trajectories" / "t.msgpack").read_bytes() == content


def test_write_stream_source_failure_leaves_no_destination_or_temp(tmp_path) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)

    def failing():
        yield b"partial"
        raise ValueError("trajectory_spool_corrupt")

    with pytest.raises(ValueError, match="trajectory_spool_corrupt"):
        store.write_stream("trajectories/t.msgpack", failing(), "application/msgpack")

    assert list((_attempt_dir(tmp_path) / "trajectories").iterdir()) == []


def test_write_stream_denied_authority_publishes_nothing(tmp_path) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)

    def deny() -> None:
        raise RuntimeError("lease_lost")

    with pytest.raises(RuntimeError, match="lease_lost"):
        store.write_stream("trajectories/t.msgpack", [b"x"], "application/msgpack", authorize_publish=deny)

    assert list((_attempt_dir(tmp_path) / "trajectories").iterdir()) == []


def test_write_stream_rejects_non_bytes_chunks(tmp_path) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)

    with pytest.raises(StagingArtifactError, match="staging_write_failed"):
        store.write_stream("t.bin", ["text"], "application/octet-stream")  # type: ignore[list-item]


def test_append_bytes_accumulates_and_reports_size(tmp_path) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)
    name = store.spool_relative_name("person_001")

    assert name == "spool/person_001.traj"
    assert store.append_bytes(name, b"a" * 24) == 24
    assert store.append_bytes(name, b"b" * 48) == 72
    assert (_attempt_dir(tmp_path) / "spool" / "person_001.traj").read_bytes() == b"a" * 24 + b"b" * 48


def test_read_chunks_is_bounded_sequential_and_exact(tmp_path) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)
    content = bytes(range(256)) * 10
    store.append_bytes("spool/t.traj", content)

    chunks = list(store.read_chunks("spool/t.traj", chunk_bytes=96, expected_size=len(content)))

    assert b"".join(chunks) == content
    assert all(len(chunk) == 96 for chunk in chunks[:-1])
    assert 0 < len(chunks[-1]) <= 96


@pytest.mark.parametrize("expected_size", [2559, 2561, 0])
def test_read_chunks_fails_closed_on_size_mismatch(tmp_path, expected_size: int) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)
    store.append_bytes("spool/t.traj", b"x" * 2560)

    with pytest.raises(StagingArtifactError, match="staging_read_size_mismatch"):
        b"".join(store.read_chunks("spool/t.traj", chunk_bytes=100, expected_size=expected_size))


def test_read_chunks_of_missing_file_fails_closed(tmp_path) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)

    with pytest.raises(StagingArtifactError, match="staging_read_failed"):
        list(store.read_chunks("spool/t.traj", chunk_bytes=24, expected_size=24))
    store.append_bytes("spool/other.traj", b"x")
    with pytest.raises(StagingArtifactError, match="staging_read_failed"):
        list(store.read_chunks("spool/t.traj", chunk_bytes=24, expected_size=24))


def test_remove_deletes_only_the_named_leaf(tmp_path) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)
    store.append_bytes("spool/a.traj", b"a")
    store.append_bytes("spool/b.traj", b"b")

    assert store.remove("spool/a.traj") is True
    assert store.remove("spool/a.traj") is False
    assert store.remove("never/created.traj") is False
    assert sorted(p.name for p in (_attempt_dir(tmp_path) / "spool").iterdir()) == ["b.traj"]


def test_remove_refuses_a_directory_and_has_no_recursive_form(tmp_path) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)
    store.append_bytes("spool/nested/a.traj", b"a")

    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        store.remove("spool/nested")

    assert (_attempt_dir(tmp_path) / "spool" / "nested" / "a.traj").read_bytes() == b"a"
    public = {name for name in dir(StagingArtifactStore) if not name.startswith("_")}
    assert not {name for name in public if "tree" in name or "recursive" in name or "rmtree" in name}


@pytest.mark.parametrize(
    "name",
    ["../escape.traj", "/abs.traj", "spool\\x.traj", "spool/../x.traj", "spool//x.traj", "./x.traj", "C:x.traj", ""],
)
def test_new_primitives_reject_traversal_names(tmp_path, name: str) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)

    with pytest.raises(StagingArtifactError, match="staging_relative_name_invalid"):
        store.append_bytes(name, b"x")
    with pytest.raises(StagingArtifactError, match="staging_relative_name_invalid"):
        store.write_stream(name, [b"x"], "application/octet-stream")
    with pytest.raises(StagingArtifactError, match="staging_relative_name_invalid"):
        list(store.read_chunks(name, chunk_bytes=1, expected_size=1))
    with pytest.raises(StagingArtifactError, match="staging_relative_name_invalid"):
        store.remove(name)
    assert not (tmp_path / "escape.traj").exists()
    assert not (tmp_path.parent / "escape.traj").exists()


@pytest.mark.parametrize("track_id", ["../x", "a/b", "", "x" * 65, "a\\b"])
def test_spool_name_rejects_unsafe_track_ids(tmp_path, track_id: str) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)

    with pytest.raises(StagingArtifactError, match="track_id_invalid"):
        store.spool_relative_name(track_id)


def test_new_primitives_are_attempt_scoped(tmp_path) -> None:
    first = StagingArtifactStore(tmp_path, JOB_ID, 1)
    second = StagingArtifactStore(tmp_path, JOB_ID, 2)
    other_job = StagingArtifactStore(tmp_path, OTHER_JOB_ID, 1)
    first.append_bytes("spool/t.traj", b"one")

    assert second.append_bytes("spool/t.traj", b"second") == 6
    assert second.remove("spool/t.traj") is True
    assert other_job.remove("spool/t.traj") is False
    assert b"".join(first.read_chunks("spool/t.traj", chunk_bytes=8, expected_size=3)) == b"one"

    first.cleanup()
    assert not _attempt_dir(tmp_path, 1).exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX no-follow fixture")
def test_append_read_and_remove_never_follow_a_leaf_symlink(tmp_path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside-leaf"
    outside.mkdir()
    target = outside / "target.bin"
    target.write_bytes(b"keep")
    spool = _attempt_dir(tmp_path) / "spool"
    spool.mkdir(parents=True)
    (spool / "t.traj").symlink_to(target)
    (spool / "dangling.traj").symlink_to(outside / "created-through-link.bin")
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)

    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        store.append_bytes("spool/t.traj", b"x")
    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        store.append_bytes("spool/dangling.traj", b"x")
    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        list(store.read_chunks("spool/t.traj", chunk_bytes=4, expected_size=4))
    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        store.remove("spool/t.traj")

    assert target.read_bytes() == b"keep"
    assert (spool / "t.traj").is_symlink()
    assert not (outside / "created-through-link.bin").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX no-follow fixture")
def test_append_read_and_remove_refuse_a_symlinked_ancestor(tmp_path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside-ancestor"
    outside.mkdir()
    (outside / "t.traj").write_bytes(b"keep")
    attempt = _attempt_dir(tmp_path)
    attempt.mkdir(parents=True)
    (attempt / "spool").symlink_to(outside, target_is_directory=True)
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)

    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        store.append_bytes("spool/t.traj", b"x")
    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        list(store.read_chunks("spool/t.traj", chunk_bytes=4, expected_size=4))
    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        store.remove("spool/t.traj")

    assert (outside / "t.traj").read_bytes() == b"keep"


@pytest.mark.skipif(os.name != "posix", reason="POSIX no-follow fixture")
def test_append_and_read_refuse_a_hard_linked_file(tmp_path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside-hardlink"
    outside.mkdir()
    target = outside / "target.bin"
    target.write_bytes(b"keep")
    spool = _attempt_dir(tmp_path) / "spool"
    spool.mkdir(parents=True)
    try:
        os.link(target, spool / "t.traj")
    except OSError:
        pytest.skip("hard links unavailable across these directories")
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)

    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        store.append_bytes("spool/t.traj", b"x")
    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        list(store.read_chunks("spool/t.traj", chunk_bytes=4, expected_size=4))

    assert target.read_bytes() == b"keep"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO fixture")
def test_append_and_read_refuse_a_fifo_without_blocking(tmp_path) -> None:
    spool = _attempt_dir(tmp_path) / "spool"
    spool.mkdir(parents=True)
    os.mkfifo(spool / "t.traj")
    store = StagingArtifactStore(tmp_path, JOB_ID, ATTEMPT)

    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        store.append_bytes("spool/t.traj", b"x")
    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        list(store.read_chunks("spool/t.traj", chunk_bytes=4, expected_size=4))
    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        store.remove("spool/t.traj")
