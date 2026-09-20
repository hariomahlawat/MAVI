"""The tools that derive the closure must not require the closure.

`write_requirements_projection.py` says which wheels to download. On the host
it failed with `ModuleNotFoundError: No module named 'numpy'`, because
`from mavi_vision.runtime.requirements_projection import ...` executes
`mavi_vision/runtime/__init__.py`, which re-exports `interfaces` and
`mmdetection`. So the tool that decides what to install needed the install to
have already happened.

CI could not catch it: `vision-runtime-component-boundary.yml` loads the same
module by file path and never imports the package at all.

These tests run each tool in a subprocess whose import system refuses the
entire runtime stack. A tool that reaches for any of it fails loudly, in an
environment that models the one the operator actually bootstraps.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "tools" / "vision"

#: Everything a fresh C2 bootstrap has *not* installed yet. `packaging` is
#: absent on purpose: it is the one third-party import these modules make, and
#: the runbook's bootstrap installs it.
FORBIDDEN = (
    "numpy",
    "torch",
    "torchvision",
    "mmcv",
    "mmdet",
    "mmengine",
    "cv2",
    "av",
    "scipy",
    "PIL",
    "pydantic",
    "pydantic_settings",
    "supervision",
    "trackers",
    "httpx",
    "msgpack",
)

_BLOCKER = textwrap.dedent(
    """
    import sys

    FORBIDDEN = {forbidden!r}


    class _Blocker:
        def find_module(self, name, path=None):
            return self.find_spec(name, path)

        def find_spec(self, name, path=None, target=None):
            root = name.split(".")[0]
            if root in FORBIDDEN:
                raise ModuleNotFoundError(
                    "blocked by test: " + name, name=name
                )
            return None


    sys.meta_path.insert(0, _Blocker())
    sys.argv = {argv!r}
    import runpy
    runpy.run_path({tool!r}, run_name="__main__")
    """
)


def _run_isolated(tool: str, argv: list[str]) -> subprocess.CompletedProcess[str]:
    script = _BLOCKER.format(
        forbidden=FORBIDDEN,
        argv=[tool, *argv],
        tool=str(TOOLS / tool),
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )


def test_the_projection_tool_runs_without_the_runtime_stack(tmp_path: Path) -> None:
    """The exact command C2.3a runs, in the environment C2.3a runs it in."""
    output = tmp_path / "windows-x86_64-cuda.requirements.txt"
    result = _run_isolated(
        "write_requirements_projection.py",
        [
            "--platform-variant",
            "windows-x86_64-cuda",
            "--python-version",
            "3.12.10",
            "--output",
            str(output),
        ],
    )

    assert "No module named 'numpy'" not in result.stderr, result.stderr
    assert result.returncode == 0, result.stderr
    body = output.read_text(encoding="utf-8")
    # Not merely "it ran": it produced the real closure.
    assert "# platform-variant: windows-x86_64-cuda" in body
    assert "av==16.1.0" in body
    assert "pillow==11.3.0" in body
    assert "trackers==2.6.0" in body


@pytest.mark.parametrize(
    "tool",
    [
        "write_requirements_projection.py",
        "build_wheelhouse_manifest.py",
        "freeze_offline_lock.py",
        "build_runtime_pack.py",
    ],
)
def test_every_c2_c3_tool_imports_without_the_runtime_stack(tool: str) -> None:
    """Fixing one and leaving the rest moves the failure a few minutes later.

    All four are invoked in sequence by C2.3, C2.4 and C3.1, and all four
    reached `mavi_vision.runtime.*` through the eager package `__init__`.
    """
    result = _run_isolated(tool, ["--help"])

    assert "blocked by test" not in result.stderr, result.stderr
    assert "ModuleNotFoundError" not in result.stderr, result.stderr
    # argparse exits 0 on --help; anything else means the import failed.
    assert result.returncode == 0, result.stderr


def test_the_blocker_actually_blocks() -> None:
    """A guard that cannot fail proves nothing.

    If the meta-path finder silently stopped working, every test above would
    pass on an environment that has NumPy installed -- which this one does.
    """
    script = _BLOCKER.format(
        forbidden=FORBIDDEN,
        argv=["x"],
        tool=str(TOOLS / "does_not_matter.py"),
    ).replace(
        'import runpy\nrunpy.run_path',
        'import numpy  # noqa: F401\nimport runpy\nrunpy.run_path',
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )

    assert result.returncode != 0
    assert "blocked by test: numpy" in result.stderr


def test_the_bootstrap_leaves_a_real_package_alone() -> None:
    """In a full environment the application must behave exactly as before."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_vision_package_bootstrap", TOOLS / "vision_package_bootstrap.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    import mavi_vision  # noqa: F401  -- already imported by the suite

    assert module.install_lightweight_vision_package() is False


def test_the_bootstrap_refuses_a_missing_package(tmp_path: Path) -> None:
    """A silent no-op would surface later as a confusing ImportError."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_vision_package_bootstrap_missing", TOOLS / "vision_package_bootstrap.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    saved = sys.modules.pop("mavi_vision", None)
    try:
        with pytest.raises(ModuleNotFoundError):
            module.install_lightweight_vision_package(tmp_path)
    finally:
        if saved is not None:
            sys.modules["mavi_vision"] = saved
