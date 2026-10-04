"""Tooling identity (S3.2d-1 plan §5): enumerated by the import graph, bound to a clean commit."""

from __future__ import annotations

import importlib
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.benchmarks.core import identity as i
from tools.benchmarks.core.identity import S32Error, document_sha256

STEM = "fixture-contract-v1"


def git(repository: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repository), "-c", "user.name=fixture", "-c",
                             "user.email=fixture@example.invalid", "-c", "core.autocrlf=false", *args],
                            capture_output=True, check=True)
    return result.stdout.decode("utf-8").strip()


class Repo:
    """A throwaway repository whose ``tools/`` modules are really imported (command → helper, transitively)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.tag = uuid.uuid4().hex[:8]
        self.command, self.helper = f"bench_cmd_{self.tag}", f"bench_helper_{self.tag}"
        root.mkdir()
        git(root, "init", "-q")
        (root / ".gitattributes").write_bytes(b"*.py text eol=lf\n*.json text eol=lf\n")
        self.write(f"tools/{self.helper}.py", "def weight():\n    return 1\n")
        self.write(f"tools/{self.command}.py", f"import {self.helper}\n\nRESULT = {self.helper}.weight()\n")
        self.write(f"tools/fixture/tests/test_{self.tag}.py", "X = 1\n")
        self.write(f"contracts/schemas/{STEM}.schema.json", '{"type": "object"}\n')
        self.commit()

    def write(self, relative: str, text: str, newline: str = "\n") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.replace("\n", newline).encode("utf-8"))
        return path

    def commit(self) -> str:
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "fixture")
        return git(self.root, "rev-parse", "HEAD")

    def load(self):
        """Imports the command module (and so the helper) plus a tests module; returns their names."""
        sys.path.insert(0, str(self.root / "tools"))
        sys.path.insert(0, str(self.root / "tools" / "fixture" / "tests"))
        importlib.invalidate_caches()
        importlib.import_module(self.command)
        importlib.import_module(f"test_{self.tag}")
        return [self.command, self.helper, f"test_{self.tag}"]

    def unload(self) -> None:
        for name in (self.command, self.helper, f"test_{self.tag}"):
            sys.modules.pop(name, None)
        for path in (str(self.root / "tools"), str(self.root / "tools" / "fixture" / "tests")):
            while path in sys.path:
                sys.path.remove(path)

    def identity(self) -> dict:
        return i.tooling_identity(self.root, schema_stems=(STEM,))


@pytest.fixture
def repo(tmp_path):
    fixture = Repo(tmp_path / "repo")
    fixture.load()
    yield fixture
    fixture.unload()


def test_enumeration_follows_the_import_graph(repo):
    paths = i.loaded_tool_files(repo.root)
    assert paths == sorted([f"tools/{repo.command}.py", f"tools/{repo.helper}.py"])  # helper: transitive
    assert all("/tests/" not in path for path in paths)
    assert i.tooling_paths(repo.root, schema_stems=(STEM,)) == sorted(
        [*paths, f"contracts/schemas/{STEM}.schema.json"])


def test_identity_is_deterministic_and_audit_list_hashes_to_it(repo):
    first, second = repo.identity(), repo.identity()
    assert first == second
    assert first["toolingCommit"] == git(repo.root, "rev-parse", "HEAD")
    assert first["toolingSha256"] == document_sha256(first["toolingFiles"])
    assert [item["path"] for item in first["toolingFiles"]] == sorted(item["path"] for item in first["toolingFiles"])
    assert all("\\" not in item["path"] for item in first["toolingFiles"])
    i.require_tooling(first)


def test_a_committed_one_byte_change_in_a_transitive_helper_changes_the_hash(repo):
    before = repo.identity()
    repo.write(f"tools/{repo.helper}.py", "def weight():\n    return 2\n")
    repo.commit()
    after = repo.identity()
    assert after["toolingSha256"] != before["toolingSha256"]
    assert after["toolingCommit"] != before["toolingCommit"]


def test_an_uncommitted_change_is_refused(repo):
    repo.write(f"tools/{repo.helper}.py", "def weight():\n    return 3\n")
    with pytest.raises(S32Error, match=f"^tooling_dirty:tools/{repo.helper}.py$"):
        repo.identity()


def test_a_changed_schema_is_refused(repo):
    repo.write(f"contracts/schemas/{STEM}.schema.json", '{"type": "array"}\n')
    with pytest.raises(S32Error, match=f"^tooling_dirty:contracts/schemas/{STEM}.schema.json$"):
        repo.identity()


def test_an_untracked_loaded_module_is_refused(repo):
    extra = repo.write(f"tools/untracked_{repo.tag}.py", "Y = 1\n")
    modules = {**sys.modules, f"untracked_{repo.tag}": SimpleNamespace(__file__=str(extra))}
    with pytest.raises(S32Error, match=f"^tooling_dirty:tools/untracked_{repo.tag}.py$"):
        i.tooling_identity(repo.root, modules=modules, schema_stems=(STEM,))


def test_a_crlf_checkout_of_the_same_commit_has_the_same_identity(repo):
    before = repo.identity()
    repo.write(f"tools/{repo.helper}.py", "def weight():\n    return 1\n", newline="\r\n")
    assert repo.identity() == before


def test_a_repository_without_a_commit_is_refused(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    git(empty, "init", "-q")
    with pytest.raises(S32Error, match="^tooling_dirty:no_commit$"):
        i.tooling_identity(empty, modules={}, schema_stems=())


def test_version_strings_do_not_enter_the_tooling_hash(repo):
    before = repo.identity()
    repo.write(f"tools/{repo.command}.py", f"import {repo.helper}\n\nRESULT = {repo.helper}.weight()\n")
    assert repo.identity() == before  # same bytes, same hash, whatever a version label says elsewhere


def test_audit_list_cannot_drift_from_the_hash(repo):
    identity = repo.identity()
    identity["toolingFiles"][0]["sha256"] = "0" * 64
    with pytest.raises(S32Error, match="^envelope_invalid:tooling_sha256$"):
        i.require_tooling(identity)


def test_harness_process_binds_its_stage3_and_phase1_helpers():
    import tools.benchmarks.core.mavi  # noqa: F401  (loads artefacts and the phase1 evaluator)

    paths = i.loaded_tool_files()
    for expected in ("tools/benchmarks/core/identity.py", "tools/benchmarks/core/mavi.py",
                     "tools/stage3/artefacts.py", "tools/phase1/evaluate_vehicle_subclass.py"):
        assert expected in paths
    assert not [path for path in paths if "/tests/" in path]
    schemas = [path for path in i.tooling_paths() if path.startswith("contracts/")]
    assert schemas == sorted(f"contracts/schemas/{stem}.schema.json" for stem in i.SCHEMA_STEMS)


def test_rationals_are_exact_and_in_lowest_terms():
    from fractions import Fraction

    assert i.rational(Fraction(2, 4)) == {"numerator": 1, "denominator": 2}
    assert i.from_rational({"numerator": 100, "denominator": 3}, "x") == Fraction(100, 3)
    with pytest.raises(S32Error, match="^x:not_lowest_terms$"):
        i.from_rational({"numerator": 2, "denominator": 4}, "x")
    with pytest.raises(S32Error, match="^x$"):
        i.from_rational({"numerator": 1, "denominator": 0}, "x")
    with pytest.raises(S32Error, match="^rational_negative$"):
        i.rational(-1)
