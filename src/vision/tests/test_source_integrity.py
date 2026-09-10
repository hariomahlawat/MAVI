from __future__ import annotations

import os
from hashlib import sha256

import pytest

from mavi_vision.storage.integrity import SourceIntegrityError, open_verified_source, verify_source


MIB = 1024 * 1024


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


def test_open_verified_source_remains_bound_to_verified_file_instance(tmp_path) -> None:
    source = tmp_path / "input.mp4"
    replacement = tmp_path / "replacement.mp4"
    source.write_bytes(b"original")
    replacement.write_bytes(b"changed!")
    digest = sha256(b"original").hexdigest()

    with open_verified_source(
        source,
        expected_size_bytes=len(b"original"),
        expected_sha256=digest,
    ) as verified:
        assert verified.stream is not None
        os.replace(replacement, source)
        verified.stream.seek(0)
        assert verified.stream.read() == b"original"

    assert source.read_bytes() == b"changed!"


def test_open_verified_source_decodes_owned_snapshot_after_in_place_mutation(tmp_path) -> None:
    source = tmp_path / "input.mp4"
    source.write_bytes(b"original")
    digest = sha256(b"original").hexdigest()

    with open_verified_source(
        source,
        expected_size_bytes=len(b"original"),
        expected_sha256=digest,
    ) as verified:
        assert verified.stream is not None
        with source.open("r+b") as mutable:
            mutable.seek(0)
            mutable.write(b"changed!")
            mutable.flush()
        verified.stream.seek(0)
        assert verified.stream.read() == b"original"

    assert source.read_bytes() == b"changed!"


def test_source_snapshot_cancellation_is_checked_during_chunk_copy(tmp_path) -> None:
    source = tmp_path / "large.mp4"
    payload = b"a" * (3 * MIB)
    source.write_bytes(payload)
    checks = 0

    def cancel_requested() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 3

    with pytest.raises(RuntimeError, match="source_snapshot_cancelled"):
        with open_verified_source(
            source,
            expected_size_bytes=len(payload),
            expected_sha256=sha256(payload).hexdigest(),
            cancel_requested=cancel_requested,
        ):
            pass

    assert checks >= 3


def test_source_growth_during_snapshot_is_detected_without_copying_unbounded_tail(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "growing.mp4"
    payload = b"a" * (2 * MIB)
    source.write_bytes(payload)
    expected_size = len(payload)
    expected_sha = sha256(payload).hexdigest()
    real_open = open
    observed_read_bytes = 0

    class GrowingReader:
        def __init__(self, stream) -> None:
            self._stream = stream
            self._grew = False

        def fileno(self):
            return self._stream.fileno()

        def seek(self, *args, **kwargs):
            return self._stream.seek(*args, **kwargs)

        def read(self, size=-1):
            nonlocal observed_read_bytes
            data = self._stream.read(size)
            observed_read_bytes += len(data)
            if data and not self._grew:
                with real_open(source, "ab") as growing:
                    growing.write(b"b" * (2 * MIB))
                    growing.flush()
                self._grew = True
            return data

        def close(self):
            return self._stream.close()

    def growing_open(path, mode="r", *args, **kwargs):
        stream = real_open(path, mode, *args, **kwargs)
        if path == source and mode == "rb":
            return GrowingReader(stream)
        return stream

    monkeypatch.setattr("builtins.open", growing_open)

    with pytest.raises(SourceIntegrityError) as exc_info:
        with open_verified_source(
            source,
            expected_size_bytes=expected_size,
            expected_sha256=expected_sha,
        ):
            pass

    assert exc_info.value.code == "source_size_mismatch"
    assert observed_read_bytes <= expected_size + 1


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
