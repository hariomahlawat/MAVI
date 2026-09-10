from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryFile
from typing import BinaryIO, Iterator


_COPY_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class VerifiedSource:
    path: Path
    size_bytes: int
    sha256: str
    stream: BinaryIO | None = None


class SourceIntegrityError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SourceSnapshotCancelled(RuntimeError):
    def __init__(self) -> None:
        super().__init__("source_snapshot_cancelled")


def _raise_if_cancelled(
    cancel_requested: Callable[[], bool] | None,
) -> None:
    if cancel_requested is not None and cancel_requested():
        raise SourceSnapshotCancelled()


def _snapshot_verified_source(
    path: Path,
    source_stream: BinaryIO,
    *,
    expected_size_bytes: int,
    expected_sha256: str,
    cancel_requested: Callable[[], bool] | None = None,
) -> VerifiedSource:
    try:
        stat = os.fstat(source_stream.fileno())
    except OSError:
        raise SourceIntegrityError("source_read_failed") from None

    if stat.st_size != expected_size_bytes:
        raise SourceIntegrityError("source_size_mismatch")

    _raise_if_cancelled(cancel_requested)
    snapshot = TemporaryFile(mode="w+b")
    digest = sha256()
    copied_bytes = 0
    try:
        source_stream.seek(0)
        while copied_bytes < expected_size_bytes:
            _raise_if_cancelled(cancel_requested)
            remaining = expected_size_bytes - copied_bytes
            chunk = source_stream.read(min(_COPY_CHUNK_BYTES, remaining))
            if not chunk:
                raise SourceIntegrityError("source_size_mismatch")
            snapshot.write(chunk)
            digest.update(chunk)
            copied_bytes += len(chunk)

        _raise_if_cancelled(cancel_requested)
        if source_stream.read(1):
            raise SourceIntegrityError("source_size_mismatch")

        actual_sha256 = digest.hexdigest()
        if actual_sha256 != expected_sha256.lower():
            raise SourceIntegrityError("source_sha256_mismatch")

        _raise_if_cancelled(cancel_requested)
        snapshot.flush()
        snapshot.seek(0)
    except (SourceIntegrityError, SourceSnapshotCancelled):
        snapshot.close()
        raise
    except OSError:
        snapshot.close()
        raise SourceIntegrityError("source_read_failed") from None

    return VerifiedSource(
        path=path,
        size_bytes=copied_bytes,
        sha256=actual_sha256,
        stream=snapshot,
    )


@contextmanager
def open_verified_source(
    path: Path,
    *,
    expected_size_bytes: int,
    expected_sha256: str,
    cancel_requested: Callable[[], bool] | None = None,
) -> Iterator[VerifiedSource]:
    _raise_if_cancelled(cancel_requested)
    try:
        source_stream = open(path, "rb")
    except FileNotFoundError:
        raise SourceIntegrityError("source_missing") from None
    except OSError:
        raise SourceIntegrityError("source_read_failed") from None

    verified: VerifiedSource | None = None
    try:
        verified = _snapshot_verified_source(
            path,
            source_stream,
            expected_size_bytes=expected_size_bytes,
            expected_sha256=expected_sha256,
            cancel_requested=cancel_requested,
        )
        _raise_if_cancelled(cancel_requested)
        yield verified
    finally:
        source_stream.close()
        if verified is not None and verified.stream is not None:
            verified.stream.close()


def verify_source(
    path: Path,
    *,
    expected_size_bytes: int,
    expected_sha256: str,
) -> VerifiedSource:
    with open_verified_source(
        path,
        expected_size_bytes=expected_size_bytes,
        expected_sha256=expected_sha256,
    ) as verified:
        return VerifiedSource(
            path=verified.path,
            size_bytes=verified.size_bytes,
            sha256=verified.sha256,
        )
