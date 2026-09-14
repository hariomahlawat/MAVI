from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "qualify_offline_variant.py"
SPEC = importlib.util.spec_from_file_location("offline_variant", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def test_observed_windows_contract_is_not_linux(monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    monkeypatch.setattr(mod.platform, "machine", lambda: "AMD64")
    observed = mod.observed_host({"portability": "qualified-platform"})
    assert observed == {
        "osFamily": "windows",
        "architecture": "x86_64",
        "distribution": None,
        "distributionVersion": None,
        "nativeAbi": "win_amd64",
        "portability": "qualified-platform",
    }


def test_venv_python_path_matches_host(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    assert mod._venv_python(tmp_path) == tmp_path / "Scripts" / "python.exe"
    monkeypatch.setattr(mod.platform, "system", lambda: "Linux")
    assert mod._venv_python(tmp_path) == tmp_path / "bin" / "python"
