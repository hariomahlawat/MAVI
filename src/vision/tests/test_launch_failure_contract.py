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

# PowerShell accepts several spellings of the same call -- a quoted code, named
# parameters, a backtick continuation before the message. A regex that only
# understands the current spelling would let a brand-new uncoded refusal through
# in any of the others, so the parsed count is cross-checked against every
# occurrence of the helper's name.
# `Invoke-MaviLaunchStep` forwards a code it was given, so its own call site
# names a variable rather than a literal and is deliberately not counted.
_ANY_CALL = re.compile(r"(?<!function )Stop-MaviLaunch\b(?!\s*\$)", re.ASCII)
_CALL = re.compile(
    r"Stop-MaviLaunch\s+(?:-Code\s+)?['\"]?(launch_[a-z0-9_]+)", re.ASCII
)
_STEP = re.compile(
    r"Invoke-MaviLaunchStep\s+(?:-Code\s+)?['\"]?(launch_[a-z0-9_]+)", re.ASCII
)


def _launcher_text() -> str:
    return LAUNCHER.read_text(encoding="utf-8")


def _emitted_codes() -> set[str]:
    text = _launcher_text()
    return set(_CALL.findall(text)) | set(_STEP.findall(text))


def test_the_launcher_emits_only_contracted_codes():
    assert _emitted_codes() <= LAUNCH_FAILURE_CODES


def test_every_contracted_code_is_actually_reachable():
    """A code nothing can emit is a code nobody can be told to look up."""
    assert LAUNCH_FAILURE_CODES <= _emitted_codes()


def test_the_vocabulary_is_closed_and_syntactically_stable():
    assert LAUNCH_FAILURE_CODES
    for code in LAUNCH_FAILURE_CODES:
        assert re.fullmatch(r"launch_[a-z][a-z0-9_]{0,63}", code, re.ASCII), code


def test_every_helper_call_site_is_parsed_by_the_contract_scraper():
    """A call the scraper cannot read is a code the contract cannot police."""
    text = _launcher_text()

    parsed = len(_CALL.findall(text))
    present = len(_ANY_CALL.findall(text))

    assert parsed == present, (
        f"{present - parsed} Stop-MaviLaunch call(s) are written in a form the "
        "contract scraper does not recognise"
    )


def test_no_fail_closed_refusal_bypasses_the_coded_helper():
    """A bare `throw` would reintroduce exactly the uncoded prose this replaced.

    PowerShell is case-insensitive, so `Throw` runs just as well as `throw`, and
    a bare `throw` rethrow carries no code at all.
    """
    text = _launcher_text()
    throws = [
        line.strip()
        for line in text.splitlines()
        if not line.strip().startswith("#")
        and re.search(r"(^|[;{}\s])throw\b", line, re.IGNORECASE)
    ]

    # The only `throw` left is the one inside Stop-MaviLaunch itself.
    assert len(throws) == 1, throws
    assert LAUNCH_FAILURE_PREFIX in throws[0]


def test_the_emitted_form_is_machine_parseable():
    text = _launcher_text()

    assert f'throw "{LAUNCH_FAILURE_PREFIX}:${{Code}}: $Message"' in text


def test_every_refusal_still_carries_an_operator_message():
    """A code alone does not tell an operator which file to look at.

    Counted as a set, not a total: emitting one code from two call sites is
    legitimate, and this test is about message quality rather than arity.
    """
    calls = re.findall(
        r"Stop-MaviLaunch\s+([a-z][a-z0-9_]*)\s+\"([^\"]+)\"", _launcher_text()
    )

    assert {code for code, _ in calls}
    for code, message in calls:
        assert len(message.strip()) > 20, code


def test_module_originated_refusals_are_coded_at_the_launcher_boundary():
    """The setup modules raise prose; the launcher is where it gains a code."""
    text = _launcher_text()
    wrapped = set(_STEP.findall(text))

    assert wrapped, "no module refusal is wrapped with a stable code"
    assert wrapped <= LAUNCH_FAILURE_CODES
    for assertion in (
        "Assert-MaviVisionRuntimePackManifest",
        "Assert-MaviVisionRuntimeInstalledStatePreflight",
        "Assert-MaviVisionInstalledRuntimeClosure",
        "Assert-MaviVisionModelPackManifest",
        "Assert-MaviVisionInstalledModelPackIntegrity",
        "Assert-MaviVisionWorkerComponentCompatibility",
    ):
        call = text.index(assertion)
        preceding = text.rfind("Invoke-MaviLaunchStep", 0, call)
        line_start = text.rfind("\n", 0, call)
        assert preceding > line_start, assertion


def test_the_two_policy_refusals_are_the_explicit_cuda_fail_closed_path():
    """These are where explicit CUDA refuses rather than run on the wrong pack."""
    assert "launch_cuda_policy_requires_cuda_pack" in LAUNCH_FAILURE_CODES
    assert "launch_cpu_policy_requires_cpu_pack" in LAUNCH_FAILURE_CODES

    text = _launcher_text()
    assert (
        'Stop-MaviLaunch launch_cuda_policy_requires_cuda_pack' in text
    )


MODULE = LAUNCHER.parent / "Mavi.VisionRuntime.Common.psm1"


def _bound_pack_status_mapping() -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for status, code in re.findall(
        r'\$bound\.Status -eq "([a-z-]+)"\) \{ Stop-MaviLaunch (launch_[a-z0-9_]+)',
        _launcher_text(),
    ):
        mapping.setdefault(status, set()).add(code)
    return mapping


def _resolver_statuses() -> set[str]:
    module = MODULE.read_text(encoding="utf-8")
    start = module.index("function Resolve-MaviVisionBoundModelPacks")
    end = module.index("\nfunction ", start + 1)
    return set(re.findall(r'\$status = "([a-z-]+)"', module[start:end]))


def test_every_store_lookup_outcome_has_exactly_its_contracted_code():
    """S2a plan §7 items 2-3: the store scan's outcomes are refusals with fixed codes.

    The scan lives in the module so it can be tested without starting Python;
    the launcher is where each outcome gains its code, so the mapping is pinned
    here and a new outcome the launcher does not map fails this test.
    """
    assert _bound_pack_status_mapping() == {
        "not-installed": {"launch_model_pack_not_installed"},
        "ambiguous": {"launch_model_pack_ambiguous"},
        "state-missing": {"launch_model_pack_not_installed"},
        "state-unsupported": {"launch_model_state_schema_unsupported"},
    }
    assert _resolver_statuses() == set(_bound_pack_status_mapping()) | {"installed"}


def test_the_launcher_removes_every_retired_composition_variable():
    """The worker refuses any retired variable, so the launcher must never pass one on."""
    from mavi_vision.common.settings import RETIRED_COMPOSITION_ENVIRONMENT

    module = MODULE.read_text(encoding="utf-8")
    declared = re.search(
        r"^\$script:VisionRetiredCompositionEnvironment = @\(([^)]*)\)",
        module,
        re.MULTILINE,
    )
    assert declared, "the module no longer declares the retired composition list"
    assert set(re.findall(r'"([A-Z_]+)"', declared.group(1))) == set(
        RETIRED_COMPOSITION_ENVIRONMENT
    )

    text = _launcher_text()
    assert "Clear-MaviVisionRetiredCompositionEnvironment" in text
    for name in RETIRED_COMPOSITION_ENVIRONMENT:
        assert not re.search(rf"\$env:{name}\s*=", text, re.IGNORECASE), name
    assert not re.search(r"\$env:MAVI_COMPLETION_SCHEMA_OVERRIDE\s*=", text, re.IGNORECASE)


def test_the_launcher_composes_the_worker_from_the_v2_binding():
    text = _launcher_text()
    for assignment in (
        r'\$env:MAVI_COMPONENT_BINDING_PATH = \$componentBindingPath',
        r'\$env:MAVI_ROLE_ID = "vision"',
        r"\$env:MAVI_OVERLAY_ROOT = \$RepositoryRoot",
        r"\$env:MAVI_RUNTIME_PACK_MANIFEST_PATH = \$runtimeManifestPath",
        r"\$env:MAVI_MODEL_ROOT = \$modelRoot",
        r"\$env:MAVI_PIPELINE_PROFILE_PATH = \$pipelinePath",
    ):
        assert re.search(assignment, text), assignment
    assert "phase1-bindings-v2.json" in text
    assert "mmdetection-phase1-v1.json" not in text


def test_launch_codes_are_not_worker_failure_codes():
    """They are raised before the worker exists and never reach the control plane."""
    from mavi_vision.common.control_plane import DEVICE_RESOLUTION_REASONS

    assert not (LAUNCH_FAILURE_CODES & set(DEVICE_RESOLUTION_REASONS))
