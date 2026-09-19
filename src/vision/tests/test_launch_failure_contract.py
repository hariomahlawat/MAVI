"""The launcher's fail-closed refusals are a closed, mirrored vocabulary.

Explicit `CUDA` never falls back, so a refusal from the Windows launcher is the
entire outcome of that run. Until these codes existed, every one of those
outcomes was a sentence of English: unclassifiable by an operator runbook,
incomparable between two hosts, and impossible for the C7 failure matrix to
record as anything stable.

These tests bind the two mirrors together the same way the device-resolution
reason vocabulary is bound, so a code cannot be added, renamed or dropped on one
side alone. They read the launcher as text, which is the only way to check it
from here -- PowerShell is not executed in hosted CI.
"""

from __future__ import annotations

import re
from pathlib import Path

from mavi_vision.runtime.launch_failures import (
    LAUNCH_FAILURE_CODES,
    LAUNCH_FAILURE_PREFIX,
)


LAUNCHER = (
    Path(__file__).resolve().parents[3]
    / "tools"
    / "setup"
    / "Start-MaviVisionWorker.ps1"
)

_CALL = re.compile(r"Stop-MaviLaunch\s+([a-z][a-z0-9_]*)\s+\"", re.ASCII)


def _launcher_text() -> str:
    return LAUNCHER.read_text(encoding="utf-8")


def _emitted_codes() -> set[str]:
    return set(_CALL.findall(_launcher_text()))


def test_the_launcher_emits_only_contracted_codes():
    assert _emitted_codes() <= LAUNCH_FAILURE_CODES


def test_every_contracted_code_is_actually_reachable():
    """A code nothing can emit is a code nobody can be told to look up."""
    assert LAUNCH_FAILURE_CODES <= _emitted_codes()


def test_the_vocabulary_is_closed_and_syntactically_stable():
    assert LAUNCH_FAILURE_CODES
    for code in LAUNCH_FAILURE_CODES:
        assert re.fullmatch(r"launch_[a-z][a-z0-9_]{0,63}", code, re.ASCII), code


def test_no_fail_closed_refusal_bypasses_the_coded_helper():
    """A bare `throw` would reintroduce exactly the uncoded prose this replaced."""
    text = _launcher_text()
    throws = [
        line.strip()
        for line in text.splitlines()
        if re.search(r"(^|[;{}\s])throw\s", line)
    ]

    # The only `throw` left is the one inside Stop-MaviLaunch itself.
    assert len(throws) == 1, throws
    assert LAUNCH_FAILURE_PREFIX in throws[0]


def test_the_emitted_form_is_machine_parseable():
    text = _launcher_text()

    assert f'throw "{LAUNCH_FAILURE_PREFIX}:${{Code}}: $Message"' in text


def test_every_refusal_still_carries_an_operator_message():
    """A code alone does not tell an operator which file to look at."""
    calls = re.findall(
        r"Stop-MaviLaunch\s+[a-z][a-z0-9_]*\s+\"([^\"]+)\"", _launcher_text()
    )

    assert len(calls) == len(LAUNCH_FAILURE_CODES)
    for message in calls:
        assert len(message.strip()) > 20, message


def test_the_two_policy_refusals_are_the_explicit_cuda_fail_closed_path():
    """These are where explicit CUDA refuses rather than run on the wrong pack."""
    assert "launch_cuda_policy_requires_cuda_pack" in LAUNCH_FAILURE_CODES
    assert "launch_cpu_policy_requires_cpu_pack" in LAUNCH_FAILURE_CODES

    text = _launcher_text()
    assert (
        'Stop-MaviLaunch launch_cuda_policy_requires_cuda_pack' in text
    )


def test_launch_codes_are_not_worker_failure_codes():
    """They are raised before the worker exists and never reach the control plane."""
    from mavi_vision.common.control_plane import DEVICE_RESOLUTION_REASONS

    assert not (LAUNCH_FAILURE_CODES & set(DEVICE_RESOLUTION_REASONS))
