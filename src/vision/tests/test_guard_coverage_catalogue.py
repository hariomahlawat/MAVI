"""The guard-coverage catalogue must keep tracking the code it polices.

`tools/vision/check_guard_coverage.py` neutralises each named guard and requires
a test to fail. Running all of it takes a minute, so the quality gate does that;
what belongs in the ordinary suite is the cheap half: every guard the catalogue
names still exists, exactly once, in the file it names.

Without this, the catalogue rots silently in the most misleading direction. A
guard that is reworded or moved makes its entry unmatchable, and a mutation
harness that cannot find its target is indistinguishable from one whose targets
are all well tested -- it just stops asking the question.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tools" / "vision" / "check_guard_coverage.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_guard_coverage", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load()


def test_the_catalogue_is_not_empty():
    assert MODULE.MUTATIONS


@pytest.mark.parametrize(
    "mutation", MODULE.MUTATIONS, ids=lambda item: item.label
)
def test_every_named_guard_still_exists_exactly_once(mutation):
    source = (ROOT / mutation.path).read_text(encoding="utf-8")

    occurrences = source.count(mutation.original)

    assert occurrences == 1, (
        f"{mutation.path} contains {occurrences} occurrences of the guard "
        f"line for {mutation.label!r}; the catalogue can no longer target it"
    )


def test_every_weakening_actually_changes_the_source(mutation=None):
    for entry in MODULE.MUTATIONS:
        assert entry.original != entry.weakened, entry.label


def test_the_catalogue_covers_every_fail_closed_tool():
    """C4, C6, C7 and the C2 reproducibility checkers all hold such guards.

    Set equality rather than a subset: a tool that grows a fail-closed guard
    and is not added here is exactly the gap this harness exists to close, and
    a subset assertion would not notice.
    """
    covered = {mutation.path for mutation in MODULE.MUTATIONS}

    assert covered == {
        "tools/vision/build_development_hardware_evidence.py",
        "tools/vision/build_development_e2e_evidence.py",
        "tools/vision/build_failure_matrix_evidence.py",
        "tools/vision/native_binary_metadata.py",
        "tools/vision/compare_wheel_reproducibility.py",
        "tools/vision/compare_native_object_trees.py",
    }


def test_the_suites_it_runs_exist():
    for suite in MODULE.SUITES:
        assert (ROOT / "src" / "vision" / suite).is_file(), suite


def test_the_catalogue_names_each_assemblers_headline_guard():
    """A catalogue that covers the periphery and not the centre asks nothing.

    These four are the rules each tool's own docstring leads with, and each was
    unnamed until an integrated review pointed it out.
    """
    labels = {mutation.label for mutation in MODULE.MUTATIONS}

    for headline in (
        "C6 stops refusing a CUDA case that ran on CPU",
        "C4 stops requiring on-device native ops",
        "C4 stops refusing an unsanitised host observation",
        "C7 stops refusing a fail-closed case that reports a device",
    ):
        assert headline in labels, headline
