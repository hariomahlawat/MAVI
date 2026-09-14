from __future__ import annotations

import base64
import hashlib
import importlib.util
import subprocess
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


def _site_packages(python: Path) -> Path:
    completed = subprocess.run(
        [str(python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(completed.stdout.strip())


def test_environment_fingerprint_changes_for_unrecorded_injected_file(tmp_path: Path):
    root = tmp_path / "venv"
    venv.EnvBuilder(with_pip=False).create(root)
    python = _python(root)
    before = mod.fingerprint(python)

    injected = _site_packages(python) / "unexpected_injection.py"
    injected.parent.mkdir(parents=True, exist_ok=True)
    injected.write_text("VALUE = 1\n", encoding="utf-8")

    after = mod.fingerprint(python)
    assert after["workerEnvironmentSha256"] != before["workerEnvironmentSha256"]


def test_environment_fingerprint_rejects_recorded_file_tamper(tmp_path: Path):
    root = tmp_path / "venv"
    venv.EnvBuilder(with_pip=False).create(root)
    python = _python(root)
    site = _site_packages(python)
    site.mkdir(parents=True, exist_ok=True)

    package = site / "demo_module.py"
    original = b"VALUE = 1\n"
    package.write_bytes(original)
    dist_info = site / "demo_pkg-1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: demo-pkg\nVersion: 1.0\n",
        encoding="utf-8",
    )
    digest = base64.urlsafe_b64encode(hashlib.sha256(original).digest()).decode("ascii").rstrip("=")
    (dist_info / "RECORD").write_text(
        f"demo_module.py,sha256={digest},{len(original)}\n"
        "demo_pkg-1.0.dist-info/METADATA,,\n"
        "demo_pkg-1.0.dist-info/RECORD,,\n",
        encoding="utf-8",
    )

    mod.fingerprint(python)
    package.write_bytes(b"VALUE = 2\n")

    try:
        mod.fingerprint(python)
    except mod.EnvironmentFingerprintError as exc:
        assert str(exc) == "worker_distribution_record_hash_mismatch"
    else:
        raise AssertionError("tampered recorded package file was accepted")
