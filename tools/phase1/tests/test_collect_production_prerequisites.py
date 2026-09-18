from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "collect_production_prerequisites.py"
SPEC = importlib.util.spec_from_file_location("collect_prereqs", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class FakeKey:
    def __init__(self, path: str):
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def test_windows_values_use_native_registry_api(monkeypatch):
    fake = types.SimpleNamespace()
    fake.HKEY_LOCAL_MACHINE = object()

    def open_key(_root, path):
        return FakeKey(path)

    def query_value(key, name):
        values = {
            (r"SOFTWARE\Microsoft\InetStp", "VersionString"): "Version 10.0",
            (r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "ProductName"): "Windows Server 2025",
            (r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "DisplayVersion"): "24H2",
            (r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "CurrentBuildNumber"): "26100",
        }
        return values[(key.path, name)], 1

    fake.OpenKey = open_key
    fake.QueryValueEx = query_value
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    monkeypatch.setattr(mod.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(
        mod,
        "run_text",
        lambda args: "Microsoft.AspNetCore.App 10.0.11 [C:\\Program Files\\dotnet\\shared\\Microsoft.AspNetCore.App]",
    )

    assert mod.windows_values() == {
        "windowsProductName": "Windows Server 2025",
        "windowsVersion": "24H2",
        "windowsBuild": "26100",
        "architecture": "AMD64",
        "iisVersion": "Version 10.0",
        "dotnetRuntimeVersion": "10.0.11",
    }


def test_windows_cpu_vision_values(monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    monkeypatch.setattr(mod.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(mod.platform, "python_version", lambda: "3.12.10")
    monkeypatch.setattr(mod.platform, "python_implementation", lambda: "CPython")

    assert mod.windows_vision_values(require_cuda=False) == {
        "architecture": "AMD64",
        "pythonVersion": "3.12.10",
        "pythonImplementation": "CPython",
    }


def test_windows_cuda_vision_values_capture_driver_and_cuda(monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    monkeypatch.setattr(mod.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(mod.platform, "python_version", lambda: "3.12.10")
    monkeypatch.setattr(mod.platform, "python_implementation", lambda: "CPython")

    def fake_run(args):
        if args[0] == "nvidia-smi":
            return "580.82"
        return "12.4"

    monkeypatch.setattr(mod, "run_text", fake_run)
    assert mod.windows_vision_values(require_cuda=True) == {
        "architecture": "AMD64",
        "pythonVersion": "3.12.10",
        "pythonImplementation": "CPython",
        "nvidiaDriverVersion": "580.82",
        "cudaRuntimeVersion": "12.4",
    }
