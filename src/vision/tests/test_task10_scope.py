"""Task 10 scope: which pull requests Task 10 applies to. Over-matching only
costs a run; under-matching would skip qualification, so every doubt is "applies"."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[3] / "tools" / "vision" / "task10_scope.py"


def _load():
    spec = importlib.util.spec_from_file_location("task10_scope", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scope = _load()
GLOBS = scope.read_globs()


@pytest.mark.parametrize(
    "path",
    [
        "src/vision/mavi_vision/tracking/bytetrack.py",
        "src/vision/mavi_vision/__init__.py",
        "src/vision/runtime/profile.json",  # "**/" spans zero directories
        "src/vision/runtime/cpu/linux/profile.json",
        "tools/qualification/s1_evidence.py",
        "tools/qualification/tests/test_s1_memory.py",
        "tools/qualification/tests/fixtures/a/b.trx",
        "tools/vision/mmcv_wheel_cache.py",
        "tools/vision/task10-scope-paths.txt",
        "tools/vision/task10_scope.py",
        ".github/workflows/task10-runtime-qualification.yml",
    ],
)
def test_a_runtime_bearing_change_applies(path: str) -> None:
    assert scope.applicable([path], GLOBS)
    assert scope.applicable(["README.md", path], GLOBS)


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "src/web/src/App.tsx",
        "src/api/Program.cs",
        "tools/qualification/model_selection/credibility.py",
        "tools/qualification/tests/test_s2c_artifacts.py",
        "src/vision/runtime/profile.yaml",
        "src/vision/tests/test_evidence_encoder_extra/nested.py",  # "*" stays in one segment
    ],
)
def test_an_unrelated_change_does_not_apply(path: str) -> None:
    assert not scope.applicable([path], GLOBS)


def test_glob_semantics_never_narrower_than_github() -> None:
    assert scope.glob_regex("a/**/*.json").fullmatch("a/x.json")
    assert scope.glob_regex("a/**/*.json").fullmatch("a/b/c/x.json")
    assert scope.glob_regex("a/**").fullmatch("a/b/c")
    assert not scope.glob_regex("a/*.py").fullmatch("a/b/c.py")
    assert scope.glob_regex("a/?.py").fullmatch("a/b.py")
    assert not scope.glob_regex("a.py").fullmatch("aXpy")


def test_the_scope_machinery_is_always_in_scope_whatever_the_list_says() -> None:
    for path in scope.ALWAYS_IN_SCOPE:
        assert scope.applicable([path], ["nothing/**"])


def test_no_files_or_an_unusable_list_means_task10_applies(tmp_path: Path) -> None:
    assert scope.applicable([], GLOBS)
    empty = tmp_path / "scope.txt"
    empty.write_text("# only comments\n", encoding="utf-8")
    with pytest.raises(ValueError):
        scope.read_globs(empty)
    empty.write_text("!src/**\n", encoding="utf-8")
    with pytest.raises(ValueError):
        scope.read_globs(empty)


def test_the_cli_answers_from_a_file_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    files = tmp_path / "files.txt"
    files.write_text("README.md\nsrc/web/src/App.tsx\n", encoding="utf-8")
    assert scope.main(["applicable", "--files", str(files)]) == 0
    assert capsys.readouterr().out.strip() == "applicable=false"
    files.write_text("README.md\nsrc/vision/mavi_vision/x.py\n", encoding="utf-8")
    scope.main(["applicable", "--files", str(files)])
    assert capsys.readouterr().out.strip() == "applicable=true"


def test_api_failure_or_truncation_means_task10_applies(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    import urllib.error

    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "t")

    def down(*_):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(scope, "_get", down)
    scope.main(["applicable", "--pull-request", "1"])
    assert capsys.readouterr().out.strip() == "applicable=true"
    monkeypatch.setattr(scope, "_get", lambda url, token: [{"filename": f"docs/{i}.md"} for i in range(100)])
    assert scope.pull_request_files("o/r", 1, "t", "https://api") is None
    scope.main(["applicable", "--pull-request", "1"])
    assert capsys.readouterr().out.strip() == "applicable=true"
    monkeypatch.delenv("GITHUB_TOKEN")
    scope.main(["applicable", "--pull-request", "1"])
    assert capsys.readouterr().out.strip() == "applicable=true"


def test_pages_and_renamed_paths_are_all_considered(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {
        1: [{"filename": f"docs/{i}.md"} for i in range(100)],
        2: [{"filename": "docs/new.py", "previous_filename": "src/vision/mavi_vision/old.py"}],
    }
    seen = []

    def get(url, token):
        page = int(url.rsplit("page=", 1)[1])
        seen.append(page)
        return pages.get(page, [])

    monkeypatch.setattr(scope, "_get", get)
    files = scope.pull_request_files("o/r", 7, "t", "https://api")
    assert seen == [1, 2] and len(files) == 102
    assert scope.applicable(files, GLOBS)  # moving a runtime file away still applies
