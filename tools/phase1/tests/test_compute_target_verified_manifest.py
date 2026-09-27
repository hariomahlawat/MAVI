"""The S2a.3 fence on ``compute_target_verified_manifest.py``.

The v1 behaviour (flip ``verificationStatus`` to ``verified`` and fill in
``qualificationId``) was the retired v1 promotion model; its tests were deleted.
A v2 verified manifest is undefined in S2a.3, so every entry point refuses with
the shared fence code and never creates the requested output.
"""

from __future__ import annotations

import inspect
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from phase1_v2_support import (
    COMMITTED_MANIFEST,
    PHASE1_ROOT,
    committed_release_hashes,
    load_tool,
    sha256_file,
)

mod = load_tool("target_manifest", "compute_target_verified_manifest.py")
FENCE = "v2_promotion_not_supported_by_this_slice"
SCRIPT = PHASE1_ROOT / "compute_target_verified_manifest.py"


@pytest.mark.parametrize("with_output", [False, True])
def test_the_cli_refuses_and_creates_no_output(tmp_path: Path, with_output: bool) -> None:
    before = committed_release_hashes()
    candidate = tmp_path / "candidate.json"
    shutil.copyfile(COMMITTED_MANIFEST, candidate)
    candidate_sha = sha256_file(candidate)
    output = tmp_path / "verified.json"
    argv = ["--manifest", str(candidate), "--qualification-id", "rtmdet-m-coco-phase1-v2"]
    if with_output:
        argv += ["--output", str(output)]

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *argv],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    # No target hash is printed: there is no v2 target to name.
    assert json.loads(completed.stdout) == {"ok": False, "code": FENCE}
    assert not output.exists()
    assert sha256_file(candidate) == candidate_sha
    assert committed_release_hashes() == before


def test_the_in_process_main_refuses(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "verified.json"
    code = mod.main(
        ["--manifest", str(COMMITTED_MANIFEST), "--qualification-id", "q", "--output", str(output)]
    )
    assert code == 2
    assert json.loads(capsys.readouterr().out) == {"ok": False, "code": FENCE}
    assert not output.exists()


def test_building_a_target_manifest_is_refused_for_the_committed_candidate() -> None:
    before = committed_release_hashes()
    candidate = json.loads(COMMITTED_MANIFEST.read_text(encoding="utf-8"))
    with pytest.raises(mod.TargetManifestError) as raised:
        mod.build_target_manifest(candidate, "rtmdet-m-coco-phase1-v2")
    assert raised.value.code == FENCE
    assert candidate["verificationStatus"] == "unverified"
    assert candidate["qualificationId"] is None
    assert committed_release_hashes() == before


def test_no_function_in_the_tool_escapes_the_fence() -> None:
    defined = {
        name
        for name, value in inspect.getmembers(mod, inspect.isfunction)
        if value.__module__ == mod.__name__
    }
    assert defined == {"build_target_manifest", "main"}
