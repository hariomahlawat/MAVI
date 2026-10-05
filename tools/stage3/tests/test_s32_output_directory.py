"""``OutputDirectory``: the final move into place survives a transient Windows denial and never raises raw.

Seen on 2026-10-05 in the first real S3.2d-2 ``prepare``: all 200 sequences written, then ``os.rename`` of the
staging directory refused with ``[WinError 5] Access is denied`` by a transient handle (antivirus or the search
indexer), surfacing as a raw ``PermissionError`` with the complete output stranded in the staging directory.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import artefacts as a  # noqa: E402


def _denied(winerror: int) -> PermissionError:
    error = PermissionError(13, "Access is denied")
    error.winerror = winerror
    return error


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(a.OutputDirectory, "MOVE_RETRY_SECONDS", 0.0)


def test_a_transient_denial_is_retried_until_the_move_succeeds(tmp_path, monkeypatch, fast):
    real_rename, calls = os.rename, []

    def flaky(src, dst):
        calls.append(1)
        if len(calls) <= 3:
            raise _denied(5 if len(calls) % 2 else 32)
        real_rename(src, dst)

    monkeypatch.setattr(a.os, "rename", flaky)
    target = tmp_path / "out"
    with a.OutputDirectory(target) as staging:
        (staging / "result.json").write_bytes(b"{}")
    assert (target / "result.json").read_bytes() == b"{}" and not staging.exists() and len(calls) == 4


def test_a_persistent_denial_is_a_refusal_that_preserves_the_staging_directory(tmp_path, monkeypatch, fast):
    monkeypatch.setattr(a.os, "rename", lambda src, dst: (_ for _ in ()).throw(_denied(5)))
    target = tmp_path / "out"
    with pytest.raises(a.S32Error, match="^output_move_failed$"):
        with a.OutputDirectory(target) as staging:
            (staging / "result.json").write_bytes(b"{}")
    assert not target.exists() and (staging / "result.json").is_file()  # evidence kept, nothing half-moved


def test_a_non_transient_error_is_refused_at_once(tmp_path, monkeypatch, fast):
    calls = []

    def broken(src, dst):
        calls.append(1)
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(a.os, "rename", broken)
    with pytest.raises(a.S32Error, match="^output_move_failed$"):
        with a.OutputDirectory(tmp_path / "out"):
            pass
    assert len(calls) == 1


def test_an_existing_target_is_still_refused_before_any_move(tmp_path):
    (tmp_path / "out").mkdir()
    with pytest.raises(a.S32Error, match="^output_exists$"):
        a.OutputDirectory(tmp_path / "out")
