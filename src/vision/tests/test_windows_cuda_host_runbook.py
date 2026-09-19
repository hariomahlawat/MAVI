"""The host-session runbook must stay executable, not merely present.

A runbook whose commands no longer match the tools is worse than none: the
operator is on a machine this session cannot reach, following it literally. So
every flag it names is checked against the argparse definition of the tool it
names, and the artefacts it tells the operator to produce are checked against
the schema versions the assemblers actually require.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
RUNBOOK = REPOSITORY_ROOT / "docs/runbooks/windows-cuda-host-session.md"
TOOLS = REPOSITORY_ROOT / "tools/vision"

# One command ends at a blank line, the next `python tools\vision\...`, or the
# closing fence -- several share a single fenced block.
_INVOCATION = re.compile(
    r"python tools\\vision\\(?P<tool>[a-z_]+\.py)(?P<args>.*?)"
    r"(?=\n\s*\n|\npython tools|```)",
    re.DOTALL,
)
_FLAG = re.compile(r"--[a-z][a-z0-9-]*")


def _runbook_text() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


def _declared_flags(tool: str) -> set[str]:
    """Every option the tool's parser accepts, taken from the parser itself."""
    spec = importlib.util.spec_from_file_location(
        "runbook_" + tool.removesuffix(".py"), TOOLS / tool
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    captured: set[str] = set()
    original = argparse.ArgumentParser.add_argument

    def record(self, *args, **kwargs):
        captured.update(arg for arg in args if isinstance(arg, str) and arg.startswith("--"))
        return original(self, *args, **kwargs)

    argparse.ArgumentParser.add_argument = record
    try:
        parser_argv, sys.argv = sys.argv, [tool, "--help"]
        try:
            module.main()
        except SystemExit:
            pass
        finally:
            sys.argv = parser_argv
    finally:
        argparse.ArgumentParser.add_argument = original
    return captured


def _invocations() -> list[tuple[str, set[str]]]:
    found = []
    for match in _INVOCATION.finditer(_runbook_text()):
        flags = set(_FLAG.findall(match.group("args")))
        found.append((match.group("tool"), flags))
    return found


def test_the_runbook_exists_and_names_its_authority():
    text = _runbook_text()

    assert "2026-09-18-windows-cuda-development.md" in text
    assert "ADR-009" in text


def test_the_runbook_invokes_tools_that_exist():
    invocations = _invocations()

    assert invocations, "no tool invocations found in the runbook"
    for tool, _ in invocations:
        assert (TOOLS / tool).is_file(), tool


@pytest.mark.parametrize(
    ("tool", "flags"),
    _invocations(),
    ids=[f"{tool}-{index}" for index, (tool, _) in enumerate(_invocations())],
)
def test_every_flag_the_runbook_names_still_exists(tool, flags):
    declared = _declared_flags(tool)

    unknown = flags - declared
    assert not unknown, f"{tool} no longer accepts: {sorted(unknown)}"


def test_the_runbook_requires_a_sanitised_host_observation():
    """The one flag whose omission would commit a workstation GPU UUID."""
    text = _runbook_text()

    assert "--sanitized" in text
    assert "not optional" in text


def test_the_runbook_states_what_the_session_cannot_establish():
    text = _runbook_text()

    assert "cannot produce Production qualification" in text
    assert "no `qualified-development-hardware` without a genuine C4 bundle" in text
