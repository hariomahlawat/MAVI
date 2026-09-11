from __future__ import annotations

import os
import subprocess
from pathlib import Path
from uuid import UUID

import pytest

import mavi_vision.storage.artifact_store_windows as windows_backend
from mavi_vision.storage.artifact_store import StagingArtifactError, StagingArtifactStore


pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="native Windows staging security tests",
)

JOB_ID = UUID("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761")
ATTEMPT_NAME = "attempt-0001"


def _junction(link: Path, target: Path) -> None:
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target.resolve())],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"failed to create NTFS junction: stdout={result.stdout!r} "
            f"stderr={result.stderr!r}"
        )


def _attempt_root(root: Path, attempt: int = 1) -> Path:
    return root / "staging" / str(JOB_ID) / f"attempt-{attempt:04d}"


def test_windows_rejects_junction_in_attempt_ancestry(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside-job-junction"
    outside.mkdir()
    keep = outside / "keep.bin"
    keep.write_bytes(b"keep")

    staging = tmp_path / "staging"
    staging.mkdir()
    _junction(staging / str(JOB_ID), outside)

    store = StagingArtifactStore(tmp_path, JOB_ID, 1)

    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        store.write_bytes("artifact.bin", b"payload", "application/octet-stream")
    with pytest.raises(StagingArtifactError, match="staging_path_escape"):
        store.cleanup()

    assert keep.read_bytes() == b"keep"
    assert not (outside / ATTEMPT_NAME).exists()


def test_windows_parent_swap_cannot_redirect_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID, 1)
    store.write_bytes("safe/seed.bin", b"seed", "application/octet-stream")

    attempt_root = _attempt_root(tmp_path)
    safe_parent = attempt_root / "safe"
    detached_parent = attempt_root / "safe-detached"
    outside = tmp_path.parent / f"{tmp_path.name}-outside-race"
    outside.mkdir()

    real_create = windows_backend._create_exclusive_child_file
    swapped = False

    def racing_create(parent, name):
        nonlocal swapped
        if not swapped and name.startswith(".race.bin."):
            safe_parent.rename(detached_parent)
            _junction(safe_parent, outside)
            swapped = True
        return real_create(parent, name)

    monkeypatch.setattr(
        windows_backend,
        "_create_exclusive_child_file",
        racing_create,
    )

    with pytest.raises(StagingArtifactError, match="staging_path_(?:race|escape)"):
        store.write_bytes(
            "safe/race.bin",
            b"payload",
            "application/octet-stream",
        )

    assert swapped is True
    assert not (outside / "race.bin").exists()
    assert not (detached_parent / "race.bin").exists()
    assert list(detached_parent.glob(".race.bin.*.tmp")) == []


def test_windows_cleanup_does_not_follow_reparse_point(tmp_path: Path) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID, 1)
    store.write_bytes("normal.bin", b"remove", "application/octet-stream")

    outside = tmp_path.parent / f"{tmp_path.name}-outside-cleanup"
    outside.mkdir()
    keep = outside / "keep.bin"
    keep.write_bytes(b"keep")
    _junction(_attempt_root(tmp_path) / "external", outside)

    store.cleanup()

    assert not _attempt_root(tmp_path).exists()
    assert keep.read_bytes() == b"keep"


def test_windows_cleanup_preserves_sibling_attempt(tmp_path: Path) -> None:
    first = StagingArtifactStore(tmp_path, JOB_ID, 1)
    second = StagingArtifactStore(tmp_path, JOB_ID, 2)
    first.write_bytes("same.bin", b"one", "application/octet-stream")
    second_descriptor = second.write_bytes(
        "same.bin",
        b"two",
        "application/octet-stream",
    )
    second_path = tmp_path.joinpath(*second_descriptor.storage_key.split("/"))

    first.cleanup()

    assert not _attempt_root(tmp_path, 1).exists()
    assert second_path.read_bytes() == b"two"


def test_windows_publish_rechecks_authority_immediately_before_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID, 1)
    events: list[str] = []
    real_replace = windows_backend._replace_child_file

    def authorize() -> None:
        events.append("authorized")

    def checked_replace(parent, temporary, destination_name):
        assert events == ["authorized"]
        events.append("replace")
        return real_replace(parent, temporary, destination_name)

    monkeypatch.setattr(windows_backend, "_replace_child_file", checked_replace)

    descriptor = store.write_bytes(
        "secure/file.bin",
        b"payload",
        "application/octet-stream",
        authorize_publish=authorize,
    )

    assert events == ["authorized", "replace"]
    assert tmp_path.joinpath(*descriptor.storage_key.split("/")).read_bytes() == b"payload"


def test_windows_denied_authority_leaves_no_destination_or_temp(
    tmp_path: Path,
) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID, 1)

    class AuthorityLost(RuntimeError):
        pass

    def deny() -> None:
        raise AuthorityLost("lost")

    with pytest.raises(AuthorityLost, match="lost"):
        store.write_bytes(
            "secure/blocked.bin",
            b"payload",
            "application/octet-stream",
            authorize_publish=deny,
        )

    parent = _attempt_root(tmp_path) / "secure"
    assert not (parent / "blocked.bin").exists()
    assert list(parent.glob(".blocked.bin.*.tmp")) == []

def test_windows_post_replace_parent_swap_rolls_back_exact_published_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID, 1)
    store.write_bytes("safe/seed.bin", b"seed", "application/octet-stream")

    attempt_root = _attempt_root(tmp_path)
    safe_parent = attempt_root / "safe"
    detached_parent = attempt_root / "safe-detached"
    outside = tmp_path.parent / f"{tmp_path.name}-outside-post-replace"
    outside.mkdir()

    real_replace = windows_backend._replace_child_file
    swapped = False

    def racing_replace(parent, temporary, destination_name):
        nonlocal swapped
        real_replace(parent, temporary, destination_name)
        if destination_name == "race.bin":
            safe_parent.rename(detached_parent)
            _junction(safe_parent, outside)
            swapped = True

    monkeypatch.setattr(windows_backend, "_replace_child_file", racing_replace)

    with pytest.raises(StagingArtifactError, match="staging_path_(?:race|escape)"):
        store.write_bytes(
            "safe/race.bin",
            b"payload",
            "application/octet-stream",
        )

    assert swapped is True
    assert not (outside / "race.bin").exists()
    assert not (detached_parent / "race.bin").exists()
    assert list(detached_parent.glob(".race.bin.*.tmp")) == []


def test_windows_rejects_component_before_unicode_string_length_wrap(
    tmp_path: Path,
) -> None:
    store = StagingArtifactStore(tmp_path, JOB_ID, 1)
    oversized_component = "x" * 32768

    with pytest.raises(
        StagingArtifactError,
        match="staging_relative_name_invalid",
    ):
        store.write_bytes(
            oversized_component,
            b"payload",
            "application/octet-stream",
        )

    attempt_root = _attempt_root(tmp_path)
    assert attempt_root.is_dir()
    assert list(attempt_root.iterdir()) == []

