from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryFile
from typing import BinaryIO, Iterator


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


def _snapshot_verified_source(
    path: Path,
    source_stream: BinaryIO,
    *,
    expected_size_bytes: int,
    expected_sha256: str,
) -> VerifiedSource:
    try:
        stat = os.fstat(source_stream.fileno())
    except OSError:
        raise SourceIntegrityError("source_read_failed") from None

    if stat.st_size != expected_size_bytes:
        raise SourceIntegrityError("source_size_mismatch")

    snapshot = TemporaryFile(mode="w+b")
    digest = sha256()
    copied_bytes = 0
    try:
        source_stream.seek(0)
        while True:
            chunk = source_stream.read(1024 * 1024)
            if not chunk:
                break
            snapshot.write(chunk)
            digest.update(chunk)
            copied_bytes += len(chunk)
        snapshot.flush()
        snapshot.seek(0)
    except OSError:
        snapshot.close()
        raise SourceIntegrityError("source_read_failed") from None

    if copied_bytes != expected_size_bytes:
        snapshot.close()
        raise SourceIntegrityError("source_size_mismatch")

    actual_sha256 = digest.hexdigest()
    if actual_sha256 != expected_sha256.lower():
        snapshot.close()
        raise SourceIntegrityError("source_sha256_mismatch")

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
) -> Iterator[VerifiedSource]:
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
        )
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
