"""The tracked requirements projection is derived, so it must be derivable.

The boundary gate regenerates this file and requires the tracked copy to match
byte for byte, but nothing could produce one: the CPU projections were already
tracked, and C5's CUDA projection would have had to be hand-assembled. These
tests pin that the tool reproduces what is tracked today -- which is the only
evidence that it will produce a correct one tomorrow.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
RUNTIME_ROOT = ROOT / "src/vision/runtime/mmdetection-phase1-v1"
TOOL = ROOT / "tools/vision/write_requirements_projection.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "write_requirements_projection", TOOL
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load()


@pytest.mark.parametrize(
    ("variant", "python_version"),
    (
        ("windows-x86_64-cpu", "3.12.10"),
        ("linux-x86_64-cpu", "3.12.14"),
    ),
)
def test_it_reproduces_every_tracked_projection_byte_for_byte(
    variant, python_version
):
    """The gate demands byte equality, so anything less is not a reproduction."""
    tracked = (RUNTIME_ROOT / f"{variant}.requirements.txt").read_bytes()

    assert MODULE.render(variant, python_version) == tracked


def test_it_can_derive_the_cuda_projection_c5_will_need():
    rendered = MODULE.render("windows-x86_64-cuda", "3.12.10")

    assert b"# platform-variant: windows-x86_64-cuda" in rendered
    assert b"# python-version: 3.12.10" in rendered
    assert rendered.endswith(b"\n")
    assert b"\r" not in rendered


def test_the_cuda_projection_is_not_the_cpu_one_under_another_name():
    """If the two were identical the variant argument would be decoration."""
    cpu = MODULE.render("windows-x86_64-cpu", "3.12.10")
    cuda = MODULE.render("windows-x86_64-cuda", "3.12.10")

    assert cpu != cuda


def test_an_unknown_variant_is_refused():
    from mavi_vision.runtime.requirements_projection import (
        RuntimeRequirementsError,
    )

    with pytest.raises(RuntimeRequirementsError):
        MODULE.render("windows-x86_64-rocm", "3.12.10")


def test_check_mode_refuses_a_stale_tracked_projection(tmp_path, capsys):
    import json

    stale = tmp_path / "windows-x86_64-cpu.requirements.txt"
    stale.write_bytes(b"# schema: mavi-vision-runtime-requirements-v1\n")

    argv = sys.argv
    sys.argv = [
        "write_requirements_projection.py",
        "--platform-variant",
        "windows-x86_64-cpu",
        "--python-version",
        "3.12.10",
        "--check",
        "--output",
        str(stale),
    ]
    try:
        assert MODULE.main() == 2
    finally:
        sys.argv = argv

    assert json.loads(capsys.readouterr().out)["code"] == (
        "runtime_requirement_projection_stale"
    )


def test_it_never_silently_overwrites_a_differing_file(tmp_path, capsys):
    import json

    existing = tmp_path / "windows-x86_64-cuda.requirements.txt"
    existing.write_bytes(b"hand-written\n")

    argv = sys.argv
    sys.argv = [
        "write_requirements_projection.py",
        "--platform-variant",
        "windows-x86_64-cuda",
        "--python-version",
        "3.12.10",
        "--output",
        str(existing),
    ]
    try:
        assert MODULE.main() == 2
    finally:
        sys.argv = argv

    assert existing.read_bytes() == b"hand-written\n"
    assert json.loads(capsys.readouterr().out)["code"] == (
        "runtime_requirement_projection_conflict"
    )
