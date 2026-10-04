"""The S3.2 pre-registration pin (register G1/G2): T3 and T4 accept only the registered requirements and the
owner-approved labelling guide, at their commit or any later ancestor of HEAD carrying the same bytes. A later
commit with different bytes is refused even though the plain git binding accepts it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import build_labeling_pack as bp
import s32fixtures as f
import sample_tracks as st

a = f.a
pytestmark = pytest.mark.real_preregistration


def refused(code: str, call) -> None:
    with pytest.raises(a.S32Error) as raised:
        call()
    assert str(raised.value) == code


def test_registered_identities_are_the_committed_preregistration_files():
    """Editing either file now needs an explicit, reviewed change to the executable registration."""
    for git_path, registered in a.REGISTERED_SHA256.items():
        assert a.sha256_hex((a.ROOT / git_path).read_bytes()) == registered, git_path
    assert a.REGISTERED_SHA256 == {
        a.REQUIREMENTS_GIT_PATH: "ca28702f82c6845298a2cf348d7b057024923c7a0a0f4fd496097bf1b7272d75",
        a.LABELING_GUIDE_GIT_PATH: "c5f8be38be9977ea05692e1e9d45d4ca7ea9b200629316f6375640778a251fc5",
    }


@pytest.fixture
def registered_repository(tmp_path):
    """A throwaway repository: the registered files at ``first``, an unrelated descendant ``later`` with the same bytes."""
    repository = tmp_path / "repo"
    repository.mkdir()
    f.git(repository, "init", "-q")
    for git_path in a.REGISTERED_SHA256:
        target = repository / git_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((a.ROOT / git_path).read_bytes())
    f.git(repository, "add", "-A")
    f.git(repository, "commit", "-q", "-m", "registered pre-registration")
    first = f.git(repository, "rev-parse", "HEAD")
    (repository / "unrelated.txt").write_text("later work\n", encoding="utf-8")
    f.git(repository, "add", "-A")
    f.git(repository, "commit", "-q", "-m", "unrelated later commit")
    return repository, first, f.git(repository, "rev-parse", "HEAD")


def commit_change(repository: Path, git_path: str, data: bytes) -> str:
    (repository / git_path).write_bytes(data)
    f.git(repository, "commit", "-q", "-am", "post-registration change")
    return f.git(repository, "rev-parse", "HEAD")


def test_t3_accepts_the_registered_requirements_at_their_commit_and_a_later_identical_one(registered_repository):
    repository, first, later = registered_repository
    path = repository / a.REQUIREMENTS_GIT_PATH
    for commit in (first, later):
        assert st._requirements(repository, path, commit) == {
            "sha256": a.REGISTERED_REQUIREMENTS_SHA256, "gitCommit": commit, "gitPath": a.REQUIREMENTS_GIT_PATH}


def test_t3_refuses_schema_valid_requirements_changed_in_a_later_commit(registered_repository):
    repository, _, _ = registered_repository
    path = repository / a.REQUIREMENTS_GIT_PATH
    changed = json.loads(path.read_bytes())
    changed["minimumSupport"]["evaluablePerClass"] = 20  # a lowered floor, otherwise schema-valid
    data = a.canonical_json(changed)
    a.validate(changed, "vehicle-subclass-requirements-v1", "x")
    changed_commit = commit_change(repository, a.REQUIREMENTS_GIT_PATH, data)
    # The plain binding accepts the caller-selected later commit ...
    assert a.git_binding(repository, path, changed_commit, a.REQUIREMENTS_GIT_PATH, "x")["sha256"] == a.sha256_hex(data)
    # ... T3 does not.
    refused("requirements_not_preregistered", lambda: st._requirements(repository, path, changed_commit))


def test_t3_refuses_a_one_byte_change_in_a_later_commit(registered_repository):
    repository, _, _ = registered_repository
    path = repository / a.REQUIREMENTS_GIT_PATH
    changed_commit = commit_change(repository, a.REQUIREMENTS_GIT_PATH, path.read_bytes() + b"\n")
    refused("requirements_not_preregistered", lambda: st._requirements(repository, path, changed_commit))


def test_t4_accepts_the_registered_guide_at_its_commit_and_a_later_identical_one(registered_repository):
    repository, first, later = registered_repository
    path = repository / a.LABELING_GUIDE_GIT_PATH
    for commit in (first, later):
        guide, data = bp._guide(repository, path, commit)
        assert guide == {"sha256": a.REGISTERED_LABELING_GUIDE_SHA256, "gitCommit": commit,
                         "gitPath": a.LABELING_GUIDE_GIT_PATH, "path": bp.GUIDE}
        assert data == (a.ROOT / a.LABELING_GUIDE_GIT_PATH).read_bytes()


def test_t4_refuses_a_canonical_guide_changed_in_a_later_commit(registered_repository):
    repository, _, _ = registered_repository
    path = repository / a.LABELING_GUIDE_GIT_PATH
    data = path.read_bytes() + b"\n## Amendment\n\nA pickup is a car.\n"
    assert a.canonical_text(data, "x") == data
    changed_commit = commit_change(repository, a.LABELING_GUIDE_GIT_PATH, data)
    assert a.git_binding(repository, path, changed_commit, a.LABELING_GUIDE_GIT_PATH, "x")["sha256"] == a.sha256_hex(data)
    refused("labeling_guide_not_preregistered", lambda: bp._guide(repository, path, changed_commit))
