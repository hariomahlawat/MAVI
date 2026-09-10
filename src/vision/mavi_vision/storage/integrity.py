from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
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


def _verify_open_stream(
    path: Path,
    stream: BinaryIO,
    *,
    expected_size_bytes: int,
    expected_sha256: str,
) -> VerifiedSource:
    try:
        stat = Path(path).stat()
        stream_stat = Path(f"/proc/self/fd/{stream.fileno()}").stat() if Path("/proc/self/fd").exists() else None
    except FileNotFoundError:
        raise SourceIntegrityError("source_missing") from None
    except OSError:
        stream_stat = None
        try:
            stat = path.stat()
        except OSError:
            raise SourceIntegrityError("source_read_failed") from None

    size_bytes = stream_stat.st_size if stream_stat is not None else stat.st_size
    if size_bytes != expected_size_bytes:
        raise SourceIntegrityError("source_size_mismatch")

    digest = sha256()
    try:
        stream.seek(0)
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        stream.seek(0)
    except OSError:
        raise SourceIntegrityError("source_read_failed") from None

    actual_sha256 = digest.hexdigest()
    if actual_sha256 != expected_sha256.lower():
        raise SourceIntegrityError("source_sha256_mismatch")

    return VerifiedSource(path=path, size_bytes=size_bytes, sha256=actual_sha256, stream=stream)


@contextmanager
def open_verified_source(
    path: Path,
    *,
    expected_size_bytes: int,
    expected_sha256: str,
) -> Iterator[VerifiedSource]:
    try:
        stream = open(path, "rb")
    except FileNotFoundError:
        raise SourceIntegrityError("source_missing") from None
    except OSError:
        raise SourceIntegrityError("source_read_failed") from None

    try:
        yield _verify_open_stream(
            path,
            stream,
            expected_size_bytes=expected_size_bytes,
            expected_sha256=expected_sha256,
        )
    finally:
        stream.close()


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
