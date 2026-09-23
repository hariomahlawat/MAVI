from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable, Iterator
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from uuid import UUID

from mavi_vision.common.analytical import ArtifactDescriptor


_TRACK_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}\Z")
_ATTEMPT_NAME_PATTERN = re.compile(r"attempt-([0-9]{4,10})\Z")


def attempt_directory_name(attempt_count: int) -> str:
    return f"attempt-{attempt_count:04d}"


def superseded_attempt_number(name: str, current_attempt_count: int) -> int | None:
    """Return the attempt number of a canonical sibling older than the current one.

    Only names this store itself produces (``attempt-NNNN``, zero-padded to four
    digits, canonical) qualify. Anything else under the job directory -- a later
    attempt, an unrecognised name, a non-canonical spelling -- is never selected.
    """
    match = _ATTEMPT_NAME_PATTERN.fullmatch(name)
    if match is None:
        return None
    number = int(match.group(1))
    if number < 1 or attempt_directory_name(number) != name:
        return None
    return number if number < current_attempt_count else None


class StagingArtifactError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _StagingBackend(Protocol):
    def write_chunks(
        self,
        parts: tuple[str, ...],
        chunks: Iterable[bytes],
        *,
        authorize_publish: Callable[[], None] | None,
    ) -> None: ...

    def append_bytes(self, parts: tuple[str, ...], content: bytes) -> int: ...

    def read_chunks(
        self,
        parts: tuple[str, ...],
        chunk_bytes: int,
    ) -> Iterator[bytes]: ...

    def remove_file(self, parts: tuple[str, ...]) -> bool: ...

    def cleanup(self) -> None: ...

    def cleanup_superseded_attempts(self, current_attempt_count: int) -> None: ...


class StagingArtifactStore:
    """Security-hardened filesystem store scoped to one lease attempt.

    The public API is platform-neutral. Platform backends own only filesystem
    mechanics; logical-name validation, attempt scoping and descriptor generation
    stay here so POSIX and Windows cannot drift semantically.
    """

    def __init__(self, media_root: Path, job_id: UUID, attempt_count: int) -> None:
        if attempt_count < 1:
            raise ValueError("attempt_count_must_be_positive")
        self._media_root = media_root.resolve()
        self._job_id = job_id
        self._attempt_count = attempt_count
        self._attempt_name = attempt_directory_name(attempt_count)
        self._backend = self._create_backend()

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

    def spool_relative_name(self, track_id: str) -> str:
        """Name of a Track's internal trajectory spool inside this attempt.

        Spool objects are worker-internal scratch: never published, never
        referenced by a descriptor, and removed with the attempt directory.
        """
        self._validate_track_id(track_id)
        return f"spool/{track_id}.traj"

    def write_bytes(
        self,
        relative_name: str,
        content: bytes,
        media_type: str,
        *,
        authorize_publish: Callable[[], None] | None = None,
    ) -> ArtifactDescriptor:
        return self.write_stream(
            relative_name,
            (content,),
            media_type,
            authorize_publish=authorize_publish,
        )

    def write_stream(
        self,
        relative_name: str,
        chunks: Iterable[bytes],
        media_type: str,
        *,
        authorize_publish: Callable[[], None] | None = None,
    ) -> ArtifactDescriptor:
        """Publish the concatenation of ``chunks`` atomically, never holding it whole.

        The same hardened temp-file, fsync and atomic-replace path as
        ``write_bytes``; the descriptor's size and SHA-256 are computed from the
        exact bytes handed to the file while they stream. An exception raised by
        the chunk source aborts the write and leaves no destination or temp file.
        """
        parts = self._validate_relative_name(relative_name)
        digest = sha256()
        size = 0

        def counted() -> Iterator[bytes]:
            nonlocal size
            for chunk in chunks:
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    raise StagingArtifactError("staging_write_failed")
                digest.update(chunk)
                size += len(chunk)
                yield chunk

        self._backend.write_chunks(
            parts,
            counted(),
            authorize_publish=authorize_publish,
        )

        storage_key = (
            f"staging/{self._job_id}/{self._attempt_name}/{'/'.join(parts)}"
        )
        return ArtifactDescriptor(
            storage_key=storage_key,
            media_type=media_type,
            size_bytes=size,
            sha256=digest.hexdigest(),
        )

    def append_bytes(self, relative_name: str, content: bytes) -> int:
        """Append to an attempt-scoped internal file; return its size afterwards.

        Open, append, close: no handle outlives the call and nothing is synced,
        because the file is scratch that the attempt re-derives or discards. A
        link, directory or multiply-linked file at the name is refused. This is
        not a publication and is not lease-fenced; only ``write_stream`` and
        ``write_bytes`` publish.
        """
        parts = self._validate_relative_name(relative_name)
        return self._backend.append_bytes(parts, bytes(content))

    def read_chunks(
        self,
        relative_name: str,
        *,
        chunk_bytes: int,
        expected_size: int,
    ) -> Iterator[bytes]:
        """Yield an internal file sequentially in reads of at most ``chunk_bytes``.

        Fails closed (``staging_read_size_mismatch``) unless the file holds
        exactly ``expected_size`` bytes, so a truncated, extended or swapped file
        is never consumed silently. One handle is open only while iterating.
        """
        parts = self._validate_relative_name(relative_name)
        if chunk_bytes < 1 or expected_size < 0:
            raise ValueError("staging_read_bounds_invalid")
        total = 0
        for chunk in self._backend.read_chunks(parts, chunk_bytes):
            total += len(chunk)
            if total > expected_size:
                raise StagingArtifactError("staging_read_size_mismatch")
            yield chunk
        if total != expected_size:
            raise StagingArtifactError("staging_read_size_mismatch")

    def remove(self, relative_name: str) -> bool:
        """Remove exactly one regular file of this attempt; ``False`` if absent.

        Only the named leaf entry is removed. A directory, link or reparse point
        at the name is refused (``staging_path_escape``) and left in place; there
        is deliberately no recursive form -- whole attempts go through
        ``cleanup``.
        """
        parts = self._validate_relative_name(relative_name)
        return self._backend.remove_file(parts)

    def cleanup(self) -> None:
        """Delete only this lease attempt's staging subtree."""
        self._backend.cleanup()

    def cleanup_superseded_attempts(self) -> None:
        """Delete staging left by earlier attempts of this job, and nothing else.

        Authority is the platform lease: this store is scoped to the attempt number
        the platform issued, and the platform refuses completion from every lower
        attempt of the job, so their staging can never be accepted. Later attempts
        (this worker's lease may already have lapsed) and other jobs are never
        touched; a stale lower attempt can only ever delete below its own number.
        """
        self._backend.cleanup_superseded_attempts(self._attempt_count)

    def _create_backend(self) -> _StagingBackend:
        if os.name == "posix":
            from mavi_vision.storage.artifact_store_posix import PosixStagingBackend

            return PosixStagingBackend(
                self._media_root,
                self._job_id,
                self._attempt_name,
            )
        if os.name == "nt":
            from mavi_vision.storage.artifact_store_windows import WindowsStagingBackend

            return WindowsStagingBackend(
                self._media_root,
                self._job_id,
                self._attempt_name,
            )
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
