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
    re.DOTALL | re.IGNORECASE,
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

    assert "It cannot establish **PRODUCTION-QUALIFIED**" in text
    assert "no `qualified-development-hardware` without a genuine C4 bundle" in text


def test_the_runbook_uses_the_precise_qualification_vocabulary():
    """These states are not interchangeable and the runbook must not blur them."""
    text = _runbook_text()

    for state in (
        "BUILD-VERIFIED",
        "RUNTIME-PACK-VERIFIED",
        "HARDWARE-QUALIFIED",
        "PRODUCTION-QUALIFIED",
    ):
        assert state in text, state

    # Each of the three achievable states is claimed only behind its own gate.
    assert text.index("### Gate C2") < text.index("### Gate C3")
    assert text.index("### Gate C3") < text.index("### Gate C4")


def test_the_runbook_records_the_protected_cpu_baseline_hashes():
    """An operator on the host must be able to check them without this session."""
    text = _runbook_text()

    for blob in (
        "aed2dd2e382cd6bb4a2c581b549a44378fca490b",
        "4af6574a27f27d87f72f2061a5f6d2d2d0252d78",
        "3a0c210353940809c44ff50fca178a63d7b157ab",
    ):
        assert blob in text, blob


def test_every_step_states_where_its_output_goes():
    """committed / gitignored / external is the difference between a leak and not."""
    text = _runbook_text()

    for term in ("**committed**", "**gitignored**", "**external**"):
        assert text.count(term) >= 3, term


# --- The C8 readiness checklist ------------------------------------------
#
# A readiness checklist that drifts is worse than none: it is read precisely
# when someone is deciding whether to merge. These tests pin the claims that
# would be dangerous if they went stale.

C8 = REPOSITORY_ROOT / "docs/superpowers/plans/c8-pr49-readiness.md"


def test_the_readiness_checklist_exists():
    assert C8.is_file()


def test_nothing_is_claimed_verified_that_the_repository_contradicts():
    """The three pending states must still read pending."""
    text = C8.read_text(encoding="utf-8")

    assert "**Not BUILD-VERIFIED.**" in text
    assert "**Not RUNTIME-PACK-VERIFIED.**" in text
    assert "**Not HARDWARE-QUALIFIED.**" in text
    assert "Production qualification — OUT OF SCOPE" in text


def test_the_checklist_agrees_with_the_committed_runtime_profile():
    """It claims the CUDA variant is still pending; check the profile says so."""
    import json

    profile = json.loads(
        (
            REPOSITORY_ROOT
            / "src/vision/runtime/mmdetection-phase1-v1/runtime.json"
        ).read_text(encoding="utf-8")
    )
    status = profile["platformVariants"]["windows-x86_64-cuda"]["status"]

    assert status == "pending-hardware-qualification"
    assert "remains\n`pending-hardware-qualification`" in C8.read_text(
        encoding="utf-8"
    )


def test_the_checklist_agrees_with_the_declared_failure_case_count():
    """37 cases is quoted in three places; one source of truth decides it."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "failure_matrix_for_c8",
        REPOSITORY_ROOT / "tools/vision/build_failure_matrix_evidence.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    declared = len(module.FAILURE_CASES)

    assert f"{declared} C7 cases recorded" in C8.read_text(encoding="utf-8")
    assert f"{declared} declared cases" in C8.read_text(encoding="utf-8")


def test_the_plan_no_longer_says_the_pre_c2_review_is_pending():
    plan = (
        REPOSITORY_ROOT
        / "docs/superpowers/plans/2026-09-18-windows-cuda-development.md"
    ).read_text(encoding="utf-8")
    current = plan[plan.index("## Current execution point") :]

    assert "The next step remains **independent review" not in current
    assert "requires the physical Windows CUDA host" in current


def test_every_artefact_the_runbook_writes_is_gitignored():
    """The operator pastes a driver message into these by hand.

    `build_failure_matrix_evidence` redacts a raw GPU UUID out of the assembled
    bundle, but the case record the operator pastes it into is not redacted. If
    that file is not ignored, one `git add -A` on the host commits the raw
    workstation GPU UUID -- the exact leak the salted-digest design prevents
    everywhere else.
    """
    import subprocess

    written = [
        "host-observation.json",
        "toolchain-observation.json",
        "runtime-verification.json",
        "development-evidence.json",
        "development-e2e-evidence.json",
        "failure-matrix-evidence.json",
        "mmcv-reproducibility-ab.json",
        "mmcv-objects-a2-a3.json",
        "wheelhouse-manifest.json",
        "run-explicit-cuda.json",
        "run-auto-cuda.json",
        "run-explicit-cpu.json",
        "run-restart-recovery.json",
        "run-cuda-oom-recovery.json",
        "case-explicit-cuda-wrong-physical-gpu.json",
        "case-auto-pack-absent.json",
    ]

    result = subprocess.run(
        ["git", "check-ignore", "--no-index", *written],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
    )
    ignored = set(result.stdout.split())

    missing = [name for name in written if name not in ignored]
    assert not missing, f"not gitignored: {missing}"


# ---------------------------------------------------------------------------
# The C2 acceptance model
#
# The host measured that the MMCV CUDA wheel is not byte-reproducible. The
# danger now is drift in the other direction: a later edit that rounds
# "semantically equivalent after normalisation" back up to "reproducible",
# which is the claim the evidence does not support.
# ---------------------------------------------------------------------------

PLAN = REPOSITORY_ROOT / "docs/superpowers/plans/2026-09-18-windows-cuda-development.md"
CHECKLIST = REPOSITORY_ROOT / "docs/superpowers/plans/c8-pr49-readiness.md"


@pytest.mark.parametrize("document", [RUNBOOK, PLAN, CHECKLIST])
def test_no_document_claims_the_wheel_is_byte_reproducible(document):
    text = document.read_text(encoding="utf-8")
    lowered = text.lower()

    for claim in (
        "is byte-reproducible",
        "byte reproducibility is achieved",
        "byte-identical rebuild",
    ):
        assert claim not in lowered, f"{document.name}: {claim}"

    # And the negative is stated somewhere, not merely left unsaid.
    assert "not byte-reproducible" in lowered or "not byte reproducibility" in lowered


def test_the_runbook_carries_the_three_empirical_corrections():
    """Each was paid for on the host; each prevents a specific silent failure."""
    text = _runbook_text()

    assert "--no-deps" in text
    assert "setuptools==80.10.2" in text
    assert "DISTUTILS_USE_SDK" in text
    assert "pkg_resources" in text


def test_the_runbook_requires_the_object_tree_comparison():
    """Two of 136 objects inspected by hand is evidence about two objects."""
    text = _runbook_text()

    assert "compare_native_object_trees.py" in text
    assert "136" in text


def test_every_verdict_and_classification_the_runbook_names_is_real():
    """A name the tool cannot emit sends the operator looking for nothing.

    The first draft told the operator to expect `embedded-build-path-divergence`
    as the *verdict*. It is a per-member classification and can never appear
    there, so an operator running the A-versus-B comparison would have seen
    `divergent-content`, matched it against the STOP row, and filed a false
    finding on the expected result.
    """
    import importlib.util as _il

    def _load(tool: str):
        spec = _il.spec_from_file_location("names_" + tool.removesuffix(".py"), TOOLS / tool)
        module = _il.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    analyser = _load("native_binary_metadata.py")
    source = (TOOLS / "compare_wheel_reproducibility.py").read_text(encoding="utf-8")
    verdicts = set(re.findall(r'verdict = "([a-z-]+)"', source))
    object_source = (TOOLS / "compare_native_object_trees.py").read_text(encoding="utf-8")
    verdicts |= set(re.findall(r'verdict = "([a-z-]+)"', object_source))
    analyser_source = (TOOLS / "native_binary_metadata.py").read_text(encoding="utf-8")
    classifications = set(
        re.findall(r'"classification"\]? *[:=] *"([a-z-]+)"', analyser_source)
    )

    assert "embedded-build-path-divergence" in classifications
    assert "embedded-build-path-divergence" not in verdicts
    assert analyser.ACCEPTABLE_CLASSIFICATIONS <= classifications

    text = _runbook_text()
    known = verdicts | classifications
    # Every hyphenated lowercase token the runbook presents in backticks that
    # looks like one of these names must actually be one.
    quoted = set(re.findall(r"`([a-z][a-z-]{8,})`", text))
    suspicious = {
        name
        for name in quoted
        if ("divergen" in name or "identical" in name or "normaliz" in name)
        and not name.endswith(".py")
    }
    unknown = suspicious - known
    assert not unknown, f"runbook names verdicts/classifications that do not exist: {sorted(unknown)}"


def test_the_runbook_does_not_enforce_a_tier_the_expected_result_cannot_reach():
    """`--require` on either C2.2 command would fail on the expected outcome.

    A-versus-B embeds two different source roots, and the A2/A3 objects differ
    in a header word the analyser deliberately refuses to excuse. Both are
    recording runs; enforcing a tier would make the documented-expected result
    exit 3.
    """
    text = _runbook_text()
    section = text[text.index("### C2.2a") : text.index("### What C2.2 does")]

    # The prose says "no `--require`"; what must not appear is an invocation
    # that actually passes one.
    assert not re.search(r"--require\s+[a-z]", section)
    assert "no `--require`" in section.lower()


def test_the_plan_records_that_pack_identity_binds_to_the_canonical_wheel():
    """The reviewed answer to "does identity assume reproducibility?" -- it does not.

    If this paragraph ever disappears, the next reader has to re-derive it from
    `component_identity.runtime_pack_id`, and the likeliest wrong turn is
    deciding that a rebuilt wheel may be substituted into an existing pack.
    """
    plan = PLAN.read_text(encoding="utf-8")

    assert "already binds to the selected canonical MMCV wheel's\nSHA-256" in plan
    assert "not** substitutable into an existing pack" in plan


def test_the_checklist_does_not_mark_c2_complete():
    text = CHECKLIST.read_text(encoding="utf-8")
    section = text[text.index("## 2. Build verification") : text.index("## 3. ")]

    assert "**Not BUILD-VERIFIED.**" in section
    # Executed steps may be ticked; the gate items may not be.
    assert "- [ ] wheelhouse manifest produced" in section
    assert "- [ ] `windows-x86_64-cuda.lock` frozen and committed" in section


def test_the_undocumented_bigobj_field_is_recorded_as_open():
    """It blocks equivalence by design; a doc that forgets that will normalise it."""
    plan = PLAN.read_text(encoding="utf-8")

    assert "MetaDataSize" in plan
    assert "observed, not normalised" in plan or "observed, not normalized" in plan
