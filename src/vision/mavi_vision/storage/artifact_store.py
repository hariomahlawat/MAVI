from __future__ import annotations

import os
import re
from collections.abc import Callable
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
    def write_bytes(
        self,
        parts: tuple[str, ...],
        content: bytes,
        *,
        authorize_publish: Callable[[], None] | None,
    ) -> None: ...

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

    def write_bytes(
        self,
        relative_name: str,
        content: bytes,
        media_type: str,
        *,
        authorize_publish: Callable[[], None] | None = None,
    ) -> ArtifactDescriptor:
        parts = self._validate_relative_name(relative_name)
        self._backend.write_bytes(
            parts,
            content,
            authorize_publish=authorize_publish,
        )

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
