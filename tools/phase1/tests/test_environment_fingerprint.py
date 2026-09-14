from __future__ import annotations

import importlib.util
import sys
import venv
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "environment_fingerprint.py"
SPEC = importlib.util.spec_from_file_location("environment_fingerprint", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def _python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if sys.platform.startswith("win") else "bin/python")


def test_two_venvs_sharing_base_interpreter_have_distinct_environment_identity(tmp_path: Path):
    first = tmp_path / "venv-a"
    second = tmp_path / "venv-b"
    venv.EnvBuilder(with_pip=False).create(first)
    venv.EnvBuilder(with_pip=False).create(second)

    one = mod.fingerprint(_python(first))
    two = mod.fingerprint(_python(second))

    assert one["workerResolvedPythonSha256"] == two["workerResolvedPythonSha256"]
    assert one["workerVenvRootSha256"] != two["workerVenvRootSha256"]
    assert one["workerEnvironmentSha256"] != two["workerEnvironmentSha256"]


def test_environment_fingerprint_is_stable_for_same_venv(tmp_path: Path):
    root = tmp_path / "venv"
    venv.EnvBuilder(with_pip=False).create(root)
    python = _python(root)

    assert mod.fingerprint(python) == mod.fingerprint(python)
