from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


@dataclass(frozen=True, slots=True)
class VerifiedSource:
    path: Path
    size_bytes: int
    sha256: str


class SourceIntegrityError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def verify_source(
    path: Path,
    *,
    expected_size_bytes: int,
    expected_sha256: str,
) -> VerifiedSource:
    try:
        stat = path.stat()
    except FileNotFoundError:
        raise SourceIntegrityError("source_missing") from None
    except OSError:
        raise SourceIntegrityError("source_read_failed") from None

    if not path.is_file():
        raise SourceIntegrityError("source_read_failed")

    if stat.st_size != expected_size_bytes:
        raise SourceIntegrityError("source_size_mismatch")

    digest = sha256()
    try:
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except FileNotFoundError:
        raise SourceIntegrityError("source_missing") from None
    except OSError:
        raise SourceIntegrityError("source_read_failed") from None

    actual_sha256 = digest.hexdigest()
    if actual_sha256 != expected_sha256:
        raise SourceIntegrityError("source_sha256_mismatch")

    return VerifiedSource(path=path, size_bytes=stat.st_size, sha256=actual_sha256)
