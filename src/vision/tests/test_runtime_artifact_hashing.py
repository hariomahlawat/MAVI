from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from mavi_vision.runtime.manifest import (
    ReleaseMetadataError,
    sha256_release_file,
    validate_release_text_file,
)


def test_sha256_release_file_hashes_exact_bytes_without_normalization(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_bytes(b'{"value":1}\n')
    second.write_bytes(b'{ "value": 1 }\n')

    assert sha256_release_file(first) == hashlib.sha256(first.read_bytes()).hexdigest()
    assert sha256_release_file(second) == hashlib.sha256(second.read_bytes()).hexdigest()
    assert sha256_release_file(first) != sha256_release_file(second)


def test_release_text_rejects_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "release.json"
    path.write_bytes(b"\xef\xbb\xbf" + b'{"value":1}\n')

    with pytest.raises(ReleaseMetadataError, match="release_text_bom_forbidden"):
        validate_release_text_file(path)


def test_release_json_rejects_crlf_bytes(tmp_path: Path) -> None:
    path = tmp_path / "release.json"
    path.write_bytes(b'{"value":1}\r\n')

    with pytest.raises(ReleaseMetadataError, match="release_text_cr_forbidden"):
        validate_release_text_file(path)


def test_release_lock_rejects_carriage_return(tmp_path: Path) -> None:
    path = tmp_path / "runtime.lock"
    path.write_bytes(b"package==1.0 --hash=sha256:" + b"a" * 64 + b"\r\n")

    with pytest.raises(ReleaseMetadataError, match="release_text_cr_forbidden"):
        validate_release_text_file(path)


def test_release_text_accepts_utf8_lf(tmp_path: Path) -> None:
    path = tmp_path / "release.json"
    payload = '{"name":"MAVI"}\n'.encode("utf-8")
    path.write_bytes(payload)

    assert validate_release_text_file(path) == payload
