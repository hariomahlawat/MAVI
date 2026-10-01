"""CODEOWNERS: @hariomahlawat owns every path. GitHub applies the last matching
rule, so a later rule without him would silently replace him."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

VERIFY_REPO_PATH = Path(__file__).parents[3] / "tools" / "verify_repo.py"


def _load_verify_repo():
    spec = importlib.util.spec_from_file_location("verify_repo_code_owners", VERIFY_REPO_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verifier = _load_verify_repo()


def test_the_committed_code_owners_pass() -> None:
    text = (VERIFY_REPO_PATH.parents[1] / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
    assert verifier.code_owner_problems(text) == []
    errors: list[str] = []
    verifier.check_code_owners(errors)
    assert errors == []


def test_overrides_that_keep_the_owner_pass() -> None:
    text = "# comment\n* @hariomahlawat\n/docs/ @hariomahlawat @someone   # inline comment\n"
    assert verifier.code_owner_problems(text) == []


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("* @hariomahlawat\n/docs/ @someone\n", "replaces the owners without @hariomahlawat"),
        ("* @hariomahlawat\n/docs/\n", "has no owners"),
        ("* @someone\n", "replaces the owners without @hariomahlawat"),
        ("/src/ @hariomahlawat\n* @hariomahlawat\n", "first rule must be the '*' default"),
        ("# only comments\n\n", "has no rules"),
        ("* @hariomahlawat-other\n", "replaces the owners without @hariomahlawat"),
    ],
)
def test_a_rule_that_drops_the_owner_is_refused(text: str, fragment: str) -> None:
    assert any(fragment in problem for problem in verifier.code_owner_problems(text))


def test_a_missing_file_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verifier, "ROOT", tmp_path)
    errors: list[str] = []
    verifier.check_code_owners(errors)
    assert errors == ["Missing .github/CODEOWNERS"]
