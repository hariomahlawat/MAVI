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


def test_a_nul_separated_path_with_a_newline_is_one_path(tmp_path: Path, capsys) -> None:
    files = tmp_path / "files.z"
    files.write_bytes(b"README.md\0src/vision/mavi_vision/a\nb.py\0")
    scope.main(["applicable", "--files", str(files)])
    assert capsys.readouterr().out.strip() == "applicable=true"
    assert scope.glob_regex("src/vision/mavi_vision/**").fullmatch("src/vision/mavi_vision/a\nb.py")


@pytest.mark.parametrize("glob", ["src/a?.py", "src/a+.py", "src/[ab].py", "src/{a,b}.py", "src/a!.py", "!src/**"])
def test_glob_syntax_the_tool_does_not_model_is_refused(tmp_path: Path, glob: str) -> None:
    listed = tmp_path / "scope.txt"
    listed.write_text(glob + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported glob syntax"):
        scope.read_globs(listed)


def test_any_error_means_task10_applies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    scope.main(["applicable", "--files", str(tmp_path / "absent")])
    assert capsys.readouterr().out.strip() == "applicable=true"
    files = tmp_path / "files.txt"
    files.write_text("README.md\n", encoding="utf-8")

    def boom(*_):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(scope, "read_globs", boom)
    scope.main(["applicable", "--files", str(files)])
    assert capsys.readouterr().out.strip() == "applicable=true"
    files.write_bytes(b"\xff\xfe")
    monkeypatch.undo()
    scope.main(["applicable", "--files", str(files)])
    assert capsys.readouterr().out.strip() == "applicable=true"


def _scope_step_body() -> str:
    workflow = (TOOL.parents[2] / ".github" / "workflows" / "task10-runtime-qualification.yml").read_text(encoding="utf-8")
    step = workflow.split("- name: Decide whether Task 10 applies\n", 1)[1].split("\n\n", 1)[0]
    return "\n".join(line[10:] for line in step.split("        run: |\n", 1)[1].splitlines())


def _git(repo: Path, *args: str) -> str:
    import subprocess

    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env={**__import__("os").environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}).stdout.strip()


def _commit(repo: Path, files: dict[str, str], message: str) -> None:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def _run_scope_step(repo: Path, tmp_path: Path, event: str = "pull_request", sha: str | None = None) -> tuple[int, str]:
    import subprocess

    sys.path.insert(0, str(TOOL.parents[2] / "src" / "vision" / "tests"))
    from test_runtime_metadata import _git_bash

    output = tmp_path / "out"
    output.write_text("", encoding="utf-8")
    body = _scope_step_body().replace("${{ github.event_name }}", event)
    completed = subprocess.run(
        [_git_bash(), "--noprofile", "--norc", "-eo", "pipefail", "-s"], input=body, text=True, cwd=repo,
        capture_output=True,
        env={**__import__("os").environ, "GITHUB_OUTPUT": output.as_posix(), "RUNNER_TEMP": tmp_path.as_posix(),
             "GITHUB_SHA": sha or _git(repo, "rev-parse", "HEAD")},
    )
    return completed.returncode, output.read_text(encoding="utf-8").strip()


def _repo(tmp_path: Path) -> Path:
    import shutil

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "tools" / "vision").mkdir(parents=True)
    shutil.copy(TOOL, repo / "tools" / "vision" / "task10_scope.py")
    shutil.copy(scope.SCOPE_FILE, repo / "tools" / "vision" / "task10-scope-paths.txt")
    _commit(repo, {"README.md": "base\n"}, "base")
    return repo


def _merge(repo: Path) -> str:
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge", "pr")
    return _git(repo, "rev-parse", "HEAD")


def test_the_workflow_scope_step_decides_from_the_merge_commit(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "pr")
    _commit(repo, {"docs/notes.md": "x\n"}, "docs only")
    _merge(repo)
    assert _run_scope_step(repo, tmp_path) == (0, "applicable=false")

    _git(repo, "checkout", "-q", "pr")
    # A rename out of or into the runtime tree lists both paths (--no-renames).
    (repo / "src/vision/mavi_vision").mkdir(parents=True)
    _git(repo, "mv", "README.md", "src/vision/mavi_vision/moved.md")
    _git(repo, "commit", "-q", "-m", "move into runtime")
    _merge(repo)
    assert _run_scope_step(repo, tmp_path) == (0, "applicable=true")


def test_a_glob_main_added_after_the_branch_point_still_applies(tmp_path: Path) -> None:
    """Review P2-1: the list comes from the merge commit, not the stale PR head."""
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "pr")
    _commit(repo, {"src/vision/newdir/model.py": "x\n"}, "change a path only main's list covers")
    _git(repo, "checkout", "-q", "main")
    listed = repo / "tools" / "vision" / "task10-scope-paths.txt"
    listed.write_text(listed.read_text(encoding="utf-8") + "src/vision/newdir/**\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "main extends the scope")
    _merge(repo)
    assert _run_scope_step(repo, tmp_path) == (0, "applicable=true")


def test_without_a_merge_commit_or_on_other_events_task10_applies(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _commit(repo, {"docs/notes.md": "x\n"}, "linear commit, no second parent")
    assert _run_scope_step(repo, tmp_path) == (0, "applicable=true")
    assert _run_scope_step(repo, tmp_path, sha="0" * 40) == (0, "applicable=true")
    assert _run_scope_step(repo, tmp_path, event="push") == (0, "applicable=true")
    assert _run_scope_step(repo, tmp_path, event="workflow_dispatch") == (0, "applicable=true")
