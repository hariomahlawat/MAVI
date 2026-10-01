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
    text = "# comment\n   # indented comment\n* @hariomahlawat\n/docs/ @hariomahlawat @someone\n"
    assert verifier.code_owner_problems(text) == []


@pytest.mark.parametrize(
    "line",
    [
        "* @hariomahlawat # reason",
        "/docs/ @hariomahlawat @someone   # inline comment",
        "/docs/ @someone # was @hariomahlawat",
        "/docs/ @someone\t# was @hariomahlawat",
        "/docs/ @someone #@hariomahlawat",
        "/docs/#notes @hariomahlawat",
    ],
)
def test_a_hash_on_a_rule_line_is_refused(line: str) -> None:
    """GitHub has no inline comments, so such a line may be skipped or misread."""
    text = "* @hariomahlawat\n" + line + "\n"
    assert any("no inline comments" in problem for problem in verifier.code_owner_problems(text))


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("* @hariomahlawat\n/docs/ @someone\n", "replaces the owners without @hariomahlawat"),
        ("* @hariomahlawat\n/docs/\n", "has no owners"),
        ("* @someone\n", "replaces the owners without @hariomahlawat"),
        ("/src/ @hariomahlawat\n* @hariomahlawat\n", "first rule must be exactly '* @hariomahlawat'"),
        ("# only comments\n\n", "has no rules"),
        ("* @hariomahlawat-other\n", "replaces the owners without @hariomahlawat"),
        # An escaped space keeps his handle inside the pattern.
        ("* @hariomahlawat\ndocs/x\\ @hariomahlawat @someone\n", "replaces the owners without @hariomahlawat"),
        # The default rule is owned by exactly him.
        ("* @hariomahlawat @nonexistent\n", "first rule must be exactly '* @hariomahlawat'"),
    ],
)
def test_a_rule_that_drops_the_owner_is_refused(text: str, fragment: str) -> None:
    assert any(fragment in problem for problem in verifier.code_owner_problems(text))


def test_a_missing_file_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verifier, "ROOT", tmp_path)
    errors: list[str] = []
    verifier.check_code_owners(errors)
    assert errors == ["Missing .github/CODEOWNERS"]


def test_an_ignored_second_code_owners_file_or_an_oversized_file_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(verifier, "ROOT", tmp_path)
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "CODEOWNERS").write_text("* @hariomahlawat\n", encoding="utf-8")
    errors: list[str] = []
    verifier.check_code_owners(errors)
    assert errors == []
    for ignored in ("CODEOWNERS", "docs/CODEOWNERS"):
        target = tmp_path / ignored
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("* @someone\n", encoding="utf-8")
        errors = []
        verifier.check_code_owners(errors)
        assert any(error.startswith(f"{ignored} is ignored by GitHub") for error in errors), ignored
        target.unlink()
    monkeypatch.setattr(verifier, "CODE_OWNERS_MAX_BYTES", 10)
    errors = []
    verifier.check_code_owners(errors)
    assert any("3 MB" in error for error in errors)


def test_the_required_checks_each_come_from_exactly_one_job() -> None:
    errors: list[str] = []
    verifier.check_required_check_names(errors)
    assert errors == []
    one = "jobs:\n  quality:\n    name: quality\n  gate:\n    name: Task 10 qualification\n"
    assert verifier.required_check_name_problems({"a.yml": one}) == []
    duplicated = {"a.yml": one, "b.yml": "jobs:\n  impostor:\n    name: 'quality'\n"}
    assert any("'quality' is produced by 2" in p for p in verifier.required_check_name_problems(duplicated))
    missing = {"a.yml": "jobs:\n  quality:\n    name: quality\n"}
    assert any("'Task 10 qualification' is produced by 0" in p for p in verifier.required_check_name_problems(missing))
