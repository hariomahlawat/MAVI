from __future__ import annotations

import errno
import os
import re
import shutil
import stat
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from mavi_vision.common.analytical import ArtifactDescriptor


_TRACK_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}\Z")
_DIR_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_FILE_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_SECURE_DIRFD_AVAILABLE = (
    os.name == "posix"
    and hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
)


class StagingArtifactError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class StagingArtifactStore:
    """Hardened filesystem store scoped to exactly one job lease attempt."""

    def __init__(self, media_root: Path, job_id: UUID, attempt_count: int) -> None:
        if attempt_count < 1:
            raise ValueError("attempt_count_must_be_positive")
        self._media_root = media_root.resolve()
        self._job_id = job_id
        self._attempt_count = attempt_count
        self._attempt_name = f"attempt-{attempt_count:04d}"

    @property
    def job_id(self) -> UUID:
        return self._job_id

    @property
    def attempt_count(self) -> int:
        return self._attempt_count

    def thumbnail_key(self, track_id: str) -> str:
        self._validate_track_id(track_id)
        return (
            f"staging/{self._job_id}/{self._attempt_name}/"
            f"thumbnails/{track_id}.jpg"
        )

    def trajectory_key(self, track_id: str) -> str:
        self._validate_track_id(track_id)
        return (
            f"staging/{self._job_id}/{self._attempt_name}/"
            f"trajectories/{track_id}.msgpack"
        )

    def write_bytes(
        self,
        relative_name: str,
        content: bytes,
        media_type: str,
        *,
        authorize_publish: Callable[[], None] | None = None,
    ) -> ArtifactDescriptor:
        self._require_secure_dirfd()
        parts = self._validate_relative_name(relative_name)
        parent_fd, opened_fds = self._open_parent_chain(parts[:-1], create=True)
        destination_name = parts[-1]
        temp_name = f".{destination_name}.{uuid4().hex}.tmp"
        temp_exists = False
        destination_published = False

        try:
            self._reject_unsafe_destination(parent_fd, destination_name)
            expected_parent = os.fstat(parent_fd)

            try:
                temp_fd = os.open(
                    temp_name,
                    _FILE_FLAGS,
                    0o600,
                    dir_fd=parent_fd,
                )
            except OSError as exc:
                raise StagingArtifactError("staging_write_failed") from exc
            temp_exists = True

            try:
                with os.fdopen(temp_fd, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
            except OSError as exc:
                raise StagingArtifactError("staging_write_failed") from exc

            self._reject_unsafe_destination(parent_fd, destination_name)

            # The temporary file is complete and durable, but no destination has
            # changed yet. Re-authorize at this exact side-effect boundary so an
            # expired or cancelled lease cannot publish after expensive preparation
            # or temporary-file I/O. Authorization exceptions propagate unchanged.
            if authorize_publish is not None:
                authorize_publish()

            try:
                os.replace(
                    temp_name,
                    destination_name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                )
            except (OSError, TypeError, NotImplementedError) as exc:
                raise StagingArtifactError("staging_write_failed") from exc
            temp_exists = False
            destination_published = True

            try:
                self._assert_logical_parent_identity(parts[:-1], expected_parent)
            except StagingArtifactError:
                self._unlink_best_effort(parent_fd, destination_name)
                destination_published = False
                raise
        except Exception:
            # This also covers an ownership guard rejecting publication. Never wrap
            # that exception as a staging failure; remove any unpublished temporary
            # file (or a publication we already know must be rolled back) and rethrow
            # the original error so lease-loss semantics remain intact end-to-end.
            if temp_exists:
                self._unlink_best_effort(parent_fd, temp_name)
            if destination_published:
                self._unlink_best_effort(parent_fd, destination_name)
            raise
        finally:
            self._close_fds(opened_fds)

        storage_key = (
            f"staging/{self._job_id}/{self._attempt_name}/{'/'.join(parts)}"
        )
        return ArtifactDescriptor(
            storage_key=storage_key,
            media_type=media_type,
            size_bytes=len(content),
            sha256=sha256(content).hexdigest(),
        )

    def cleanup(self) -> None:
        """Delete only this lease attempt's staging subtree.

        The job directory is intentionally retained. Removing it would create a race
        with another lease attempt whose sibling subtree is already active.
        """

        self._require_secure_dirfd(require_safe_rmtree=True)
        root_fd = self._open_media_root_fd()
        staging_fd: int | None = None
        job_fd: int | None = None
        try:
            try:
                staging_fd = os.open("staging", _DIR_FLAGS, dir_fd=root_fd)
            except FileNotFoundError:
                return
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise StagingArtifactError("staging_path_escape") from exc
                raise StagingArtifactError("staging_cleanup_failed") from exc

            try:
                job_fd = os.open(str(self._job_id), _DIR_FLAGS, dir_fd=staging_fd)
            except FileNotFoundError:
                return
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise StagingArtifactError("staging_path_escape") from exc
                raise StagingArtifactError("staging_cleanup_failed") from exc

            try:
                attempt_stat = os.stat(
                    self._attempt_name,
                    dir_fd=job_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return
            except OSError as exc:
                raise StagingArtifactError("staging_cleanup_failed") from exc

            if not stat.S_ISDIR(attempt_stat.st_mode):
                raise StagingArtifactError("staging_path_escape")

            try:
                shutil.rmtree(self._attempt_name, dir_fd=job_fd)
            except FileNotFoundError:
                return
            except OSError as exc:
                raise StagingArtifactError("staging_cleanup_failed") from exc
        finally:
            if job_fd is not None:
                os.close(job_fd)
            if staging_fd is not None:
                os.close(staging_fd)
            os.close(root_fd)

    def _open_parent_chain(
        self,
        relative_parts: tuple[str, ...],
        *,
        create: bool,
    ) -> tuple[int, list[int]]:
        root_fd = self._open_media_root_fd()
        opened_fds = [root_fd]
        current_fd = root_fd
        try:
            for part in (
                "staging",
                str(self._job_id),
                self._attempt_name,
                *relative_parts,
            ):
                next_fd = self._open_directory_at(current_fd, part, create=create)
                opened_fds.append(next_fd)
                current_fd = next_fd
            return current_fd, opened_fds
        except Exception:
            self._close_fds(opened_fds)
            raise

    def _open_media_root_fd(self) -> int:
        try:
            return os.open(self._media_root, _DIR_FLAGS)
        except FileNotFoundError as exc:
            raise StagingArtifactError("media_root_missing") from exc
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise StagingArtifactError("staging_path_escape") from exc
            raise StagingArtifactError("staging_write_failed") from exc

    @staticmethod
    def _open_directory_at(parent_fd: int, name: str, *, create: bool) -> int:
        try:
            return os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
        except FileNotFoundError:
            if not create:
                raise StagingArtifactError("staging_path_race") from None
            try:
                os.mkdir(name, 0o700, dir_fd=parent_fd)
            except FileExistsError:
                pass
            except OSError as exc:
                raise StagingArtifactError("staging_write_failed") from exc
            try:
                return os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise StagingArtifactError("staging_path_escape") from exc
                raise StagingArtifactError("staging_write_failed") from exc
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise StagingArtifactError("staging_path_escape") from exc
            raise StagingArtifactError("staging_write_failed") from exc

    def _assert_logical_parent_identity(
        self,
        relative_parts: tuple[str, ...],
        expected_parent: os.stat_result,
    ) -> None:
        opened_fds: list[int] = []
        try:
            parent_fd, opened_fds = self._open_parent_chain(
                relative_parts,
                create=False,
            )
            actual_parent = os.fstat(parent_fd)
            if (
                actual_parent.st_dev != expected_parent.st_dev
                or actual_parent.st_ino != expected_parent.st_ino
            ):
                raise StagingArtifactError("staging_path_race")
        except StagingArtifactError as exc:
            if exc.code == "staging_path_escape":
                raise
            raise StagingArtifactError("staging_path_race") from exc
        finally:
            if opened_fds:
                self._close_fds(opened_fds)

    @staticmethod
    def _reject_unsafe_destination(parent_fd: int, name: str) -> None:
        try:
            destination_stat = os.stat(
                name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return
        except OSError as exc:
            raise StagingArtifactError("staging_write_failed") from exc
        if not stat.S_ISREG(destination_stat.st_mode):
            raise StagingArtifactError("staging_path_escape")

    @staticmethod
    def _unlink_best_effort(parent_fd: int, name: str) -> None:
        try:
            os.unlink(name, dir_fd=parent_fd)
        except OSError:
            pass

    @staticmethod
    def _close_fds(fds: list[int]) -> None:
        for fd in reversed(fds):
            try:
                os.close(fd)
            except OSError:
                pass

    @staticmethod
    def _require_secure_dirfd(*, require_safe_rmtree: bool = False) -> None:
        if not _SECURE_DIRFD_AVAILABLE:
            raise StagingArtifactError("secure_staging_unavailable")
        if require_safe_rmtree and not getattr(shutil.rmtree, "avoids_symlink_attacks", False):
            raise StagingArtifactError("secure_staging_unavailable")

    @staticmethod
    def _validate_track_id(track_id: str) -> None:
        if _TRACK_ID_PATTERN.fullmatch(track_id) is None:
            raise StagingArtifactError("track_id_invalid")

    @staticmethod
    def _validate_relative_name(relative_name: str) -> tuple[str, ...]:
        if (
            not relative_name
            or relative_name.startswith(("/", "\\"))
            or "\\" in relative_name
        ):
            raise StagingArtifactError("staging_relative_name_invalid")
        parts = tuple(relative_name.split("/"))
        if any(part in {"", ".", ".."} for part in parts):
            raise StagingArtifactError("staging_relative_name_invalid")
        if ":" in parts[0]:
            raise StagingArtifactError("staging_relative_name_invalid")
        return parts
