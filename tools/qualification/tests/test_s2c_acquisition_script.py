"""Static and behavioural checks for the S2c Slice A acquisition script.

The script only downloads when a person runs it on the Development machine; these tests never
touch the network. Behaviour tests run in PowerShell with a fake downloader when pwsh exists.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "tools/qualification/model_selection/acquire_s2c_candidates.ps1"
BEHAVIOUR = REPO / "tools/qualification/tests/s2c_acquisition_behaviour.ps1"

PERMITTED_URL_PREFIXES = (
    "https://huggingface.co/google/siglip2-base-patch16-224/resolve/75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2/",
    "https://huggingface.co/facebook/dinov2-small/resolve/ed25f3a31f01632728cabb09d1542f84ab7b0056/",
    "https://storage.openvinotoolkit.org/repositories/open_model_zoo/2023.0/models_bin/1/",
)


def text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_script_is_utf8_lf_without_bom():
    raw = SCRIPT.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw and raw.endswith(b"\n")


def test_only_permitted_sources_are_reachable():
    source = text()
    # Every literal URL is a permitted immutable prefix, a fixed allow-listed host, or a record link.
    for url in re.findall(r"https://[^\s'\"()$]+", source):
        if "$" in url:
            continue
        assert url.startswith(("https://huggingface.co/", "https://storage.openvinotoolkit.org/", "https://github.com/openvinotoolkit/open_model_zoo")), url
    built = re.findall(r'"https://huggingface\.co/\$repo/resolve/\$rev/\$name"', source)
    assert len(built) == 1
    for rev in ("75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2", "ed25f3a31f01632728cabb09d1542f84ab7b0056", "a6946b6d6ce42cbf4278df20275fab199655fc7d"):
        assert rev in source


def test_prohibited_candidates_have_no_source():
    lowered = text().lower()
    for token in ("huggingface.co/facebook/dinov3", "awiros/person-attribute-recognition/resolve",
                  "mobilenet_v3_small-047dcff4.pth", "download.pytorch.org", "pan.baidu.com", "dropbox"):
        assert token not in lowered, token
    for token in ("hf_token", "bearer", "defaultrequestheaders", "get-credential"):
        assert token not in lowered, token


def test_publisher_hashes_are_wired():
    source = text()
    for value in (
        "612923381c76ec5a9bed335d1c48827e3f2e506ac31b044b63b2031fadee6a0b",  # SigLIP 2 model.safetensors
        "ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1",  # DINOv2 model.safetensors
    ):
        assert source.count(value) == 1, value
    # Eight OMZ FP32 files (xml + bin for 0230, 0234, 0238, 0042), each with a published SHA-384.
    assert len(re.findall(r"& \$omz '[a-z0-9-]+' '(?:bin|xml)' \d+ '[0-9a-f]{96}'", source)) == 8


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh not available")
def test_powershell_behaviour_suite():
    result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-File", str(BEHAVIOUR)],
                            capture_output=True, text=True, timeout=600, cwd=REPO)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL S2C ACQUISITION BEHAVIOUR TESTS PASSED" in result.stdout


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh not available")
def test_script_parses():
    command = ("$t=$null;$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile("
               f"'{SCRIPT}',[ref]$t,[ref]$e); if ($e.Count) {{ $e | % {{ $_.Message }}; exit 1 }}")
    result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def test_resume_and_retry_contract_is_bounded():
    source = text()
    # Only the six clearly transient HTTP statuses are retried; the attempt limit is fixed at 5.
    assert source.count("@(408, 429, 500, 502, 503, 504) -contains $code") == 1
    assert "[int]$MaxAttempts = 5" in source and "[Math]::Pow(2, $attempt)" in source
    # A resume sends exactly "Range: bytes=<offset>-", and bytes are appended only after the
    # 206 Content-Range has been validated against the offset and the expected size.
    assert 'RangeHeaderValue]::Parse("bytes=$RangeStart-")' in source
    assert source.count("[IO.FileMode]::Append") == 1
    sink = source[source.index("if ($StatusCode -eq 206) {"):source.index("[IO.FileMode]::Append")]
    assert "Resolve-MaviContentRange -ContentRange $ContentRange -Offset $mviLength -ExpectedSize $mviExpected" in sink
    # The CLI exposes no transport, sleep or catalog override.
    param_block = source[source.index("[CmdletBinding()]"):source.index("Set-StrictMode")]
    assert set(re.findall(r"\$([A-Za-z]+)\s*(?:=|\))", param_block)) <= {"Root", "DryRun"}
