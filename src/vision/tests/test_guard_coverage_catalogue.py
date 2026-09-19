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


def test_the_catalogue_covers_all_three_assemblers():
    """C4, C6 and C7 each hold fail-closed guards worth pinning."""
    covered = {mutation.path for mutation in MODULE.MUTATIONS}

    assert covered == {
        "tools/vision/build_development_hardware_evidence.py",
        "tools/vision/build_development_e2e_evidence.py",
        "tools/vision/build_failure_matrix_evidence.py",
    }


def test_the_suites_it_runs_exist():
    for suite in MODULE.SUITES:
        assert (ROOT / "src" / "vision" / suite).is_file(), suite
