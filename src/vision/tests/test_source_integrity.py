from __future__ import annotations

from hashlib import sha256

import pytest

from mavi_vision.storage.integrity import SourceIntegrityError, verify_source


def test_verify_source_accepts_matching_file(tmp_path) -> None:
    source = tmp_path / "input.mp4"
    source.write_bytes(b"video")
    digest = sha256(b"video").hexdigest()

    verified = verify_source(source, expected_size_bytes=5, expected_sha256=digest)

    assert verified.path == source
    assert verified.size_bytes == 5
    assert verified.sha256 == digest


def test_verify_source_accepts_uppercase_lease_sha_and_returns_canonical_lowercase(tmp_path) -> None:
    source = tmp_path / "input.mp4"
    source.write_bytes(b"video")
    digest = sha256(b"video").hexdigest()

    verified = verify_source(
        source,
        expected_size_bytes=5,
        expected_sha256=digest.upper(),
    )

    assert verified.sha256 == digest


def test_verify_source_rejects_missing_file(tmp_path) -> None:
    source = tmp_path / "missing.mp4"

    with pytest.raises(SourceIntegrityError) as exc_info:
        verify_source(source, expected_size_bytes=5, expected_sha256="0" * 64)

    assert exc_info.value.code == "source_missing"


def test_verify_source_rejects_size_mismatch(tmp_path) -> None:
    source = tmp_path / "input.mp4"
    source.write_bytes(b"video")

    with pytest.raises(SourceIntegrityError) as exc_info:
        verify_source(source, expected_size_bytes=6, expected_sha256=sha256(b"video").hexdigest())

    assert exc_info.value.code == "source_size_mismatch"


def test_verify_source_rejects_sha_mismatch(tmp_path) -> None:
    source = tmp_path / "input.mp4"
    source.write_bytes(b"video")

    with pytest.raises(SourceIntegrityError) as exc_info:
        verify_source(source, expected_size_bytes=5, expected_sha256="0" * 64)

    assert exc_info.value.code == "source_sha256_mismatch"


def test_verify_source_maps_read_failure(monkeypatch, tmp_path) -> None:
    source = tmp_path / "input.mp4"
    source.write_bytes(b"video")

    def fail_open(*args, **kwargs):
        raise OSError("denied")

    monkeypatch.setattr("builtins.open", fail_open)

    with pytest.raises(SourceIntegrityError) as exc_info:
        verify_source(source, expected_size_bytes=5, expected_sha256=sha256(b"video").hexdigest())

    assert exc_info.value.code == "source_read_failed"
