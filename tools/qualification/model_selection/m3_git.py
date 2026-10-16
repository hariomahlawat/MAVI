"""MSR revision M3: the fail-closed Git layer and the one reachable-history walk (authority redesign, invariants A6/A1).

Every Git call here runs with a fixed environment (``GIT_NO_REPLACE_OBJECTS=1``, ``GIT_TERMINAL_PROMPT=0``,
``LC_ALL=C``, ``GIT_OPTIONAL_LOCKS=0``, and no inherited ``GIT_DIR``-style overrides). A non-zero exit raises
``GitCommandError`` (code ``git_command_failed``) carrying the arguments, the return code and the tail of stderr. It is a
``CredibilityError``, so it is always a refusal, and it is never mapped by a caller to "mismatch", "absent", "deleted"
or "success": an infrastructure failure stays distinguishable from an integrity finding.

Historical content is read **by blob id** from the walk (``read_blobs``, one ``git cat-file --batch`` process), never
by ``git show <commit>:<path>``. A missing object raises ``git_object_missing``.

Authority needs complete, unaltered history: ``git_history_state`` refuses a shallow clone, a graft file and a
directory that is not the top of a Git work tree. Replace objects are ignored (``GIT_NO_REPLACE_OBJECTS``).

Standard library only.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .credibility import MODEL_SELECTION_DIR, CredibilityError, _fail

# Environment variables that would redirect ``git -C <repo>`` to another repository or object store.
_STRIPPED = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR",
             "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM")
_FIXED = {"GIT_NO_REPLACE_OBJECTS": "1", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"}
STDERR_TAIL = 2000


class GitCommandError(CredibilityError):
    """A Git command failed (non-zero exit). Always a refusal; never an integrity verdict.

    ``str(error)`` starts with the stable code (``git_command_failed`` or ``git_object_missing``)."""

    def __init__(self, code: str, args: tuple[str, ...], returncode: int, stderr: str):
        self.code, self.git_args, self.returncode, self.stderr = code, tuple(args), returncode, stderr
        super().__init__(f"{code}:{' '.join(args[:3])}:rc={returncode}:{stderr.strip()}")


def git_environment() -> dict[str, str]:
    environment = {k: v for k, v in os.environ.items() if k not in _STRIPPED}
    environment.update(_FIXED)
    return environment


def _run(repo: Path, args: tuple[str, ...], data: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], input=data, capture_output=True, check=False,
                          env=git_environment())


def _git(repo: Path, *args: str, input: bytes | None = None) -> bytes:  # noqa: A002 - mirrors subprocess
    """Run Git; return stdout. Any non-zero exit raises ``GitCommandError`` (fail closed)."""
    completed = _run(Path(repo), args, input)
    if completed.returncode != 0:
        raise GitCommandError("git_command_failed", args, completed.returncode,
                              completed.stderr.decode("utf-8", "replace")[-STDERR_TAIL:])
    return completed.stdout


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    """``git merge-base --is-ancestor``: rc 0 is True, rc 1 is False, anything else raises ``GitCommandError``."""
    args = ("merge-base", "--is-ancestor", ancestor, descendant)
    completed = _run(Path(repo), args)
    if completed.returncode in (0, 1):
        return completed.returncode == 0
    raise GitCommandError("git_command_failed", args, completed.returncode,
                          completed.stderr.decode("utf-8", "replace")[-STDERR_TAIL:])


def strictly_before(repo: Path, earlier: str, later: str) -> bool:
    return earlier != later and is_ancestor(repo, earlier, later)


def read_blobs(repo: Path, blob_ids: Iterable[str]) -> dict[str, bytes]:
    """Read blobs by id in one ``git cat-file --batch`` process. A missing object raises ``git_object_missing``."""
    ids = sorted(set(blob_ids))
    if not ids:
        return {}
    out = _git(repo, "cat-file", "--batch", input=("\n".join(ids) + "\n").encode("ascii"))
    found: dict[str, bytes] = {}
    position = 0
    for blob_id in ids:
        end = out.index(b"\n", position)
        header = out[position:end].decode("ascii", "replace").split()
        position = end + 1
        if len(header) == 2 and header[1] == "missing":
            raise GitCommandError("git_object_missing", ("cat-file", "--batch", blob_id), 0, f"{blob_id} missing")
        if len(header) != 3 or header[0] != blob_id or header[1] != "blob":
            raise GitCommandError("git_command_failed", ("cat-file", "--batch", blob_id), 0,
                                  f"unexpected cat-file header: {' '.join(header)}")
        size = int(header[2])
        found[blob_id] = out[position:position + size]
        position += size + 1  # content, then LF
    return found


def git_history_state(repo: Path) -> str:
    """``"full"`` or a refusal. ``model_selection_history_unavailable:<state>`` for ``absent`` (not the top of a Git
    work tree), ``shallow`` or ``grafts_present``; any other Git failure is raised as itself (``GitCommandError``)."""
    repo = Path(repo)
    completed = _run(repo, ("rev-parse", "--show-toplevel"))
    if completed.returncode == 128 and b"not a git repository" in completed.stderr.lower():
        raise _fail("model_selection_history_unavailable", f"{repo.name}:absent")
    if completed.returncode != 0:
        raise GitCommandError("git_command_failed", ("rev-parse", "--show-toplevel"), completed.returncode,
                              completed.stderr.decode("utf-8", "replace")[-STDERR_TAIL:])
    top = completed.stdout.decode("utf-8", "replace").strip()
    if Path(top).resolve() != repo.resolve():
        raise _fail("model_selection_history_unavailable", f"{repo.name}:absent")
    if _git(repo, "rev-parse", "--is-shallow-repository").decode().strip() == "true":
        raise _fail("model_selection_history_unavailable", f"{repo.name}:shallow")
    grafts = _git(repo, "rev-parse", "--git-path", "info/grafts").decode("utf-8", "replace").strip()
    graft_path = Path(grafts) if Path(grafts).is_absolute() else repo / grafts
    if os.environ.get("GIT_GRAFT_FILE") or graft_path.exists():
        raise _fail("model_selection_history_unavailable", f"{repo.name}:grafts_present")
    return "full"


def first_add_commit(repo: Path, adds: Iterable[str], where: str) -> str:
    """The unique add that is an ancestor of every other add (earliest by ancestry, never by lexical order)."""
    adds = sorted(set(adds))
    if not adds:
        raise _fail("artefact_not_committed", where)
    earliest = [a for a in adds if all(a == b or is_ancestor(repo, a, b) for b in adds)]
    if len(earliest) != 1:
        raise _fail("artefact_first_add_ambiguous", where)
    return earliest[0]


@dataclass
class History:
    """One reachable-history walk of the model-selection directory (every commit, every parent edge)."""
    changes: list[tuple[str, str, str, str, str]] = field(default_factory=list)  # commit, status, path, old, new
    adds: dict[str, set[str]] = field(default_factory=dict)
    deletes: dict[str, set[str]] = field(default_factory=dict)
    rewrites: dict[str, set[str]] = field(default_factory=dict)  # M or T
    blobs: dict[str, set[str]] = field(default_factory=dict)  # every non-null blob a path ever held
    head_tree: dict[str, str] = field(default_factory=dict)  # path -> blob id in HEAD

    def paths(self) -> set[str]:
        return set(self.blobs) | set(self.deletes)


def model_selection_history(repo: Path) -> History:
    """Exactly one ``git log --full-history --sparse --diff-merges=separate --root --raw --no-renames --no-abbrev -z``
    walk of ``docs/qualification/model-selection`` from HEAD, plus the HEAD tree of that directory. Requires full
    history (``git_history_state``)."""
    repo = Path(repo)
    git_history_state(repo)
    folder = MODEL_SELECTION_DIR.as_posix()
    out = _git(repo, "log", "--full-history", "--sparse", "--diff-merges=separate", "--root", "--raw",
               "--no-renames", "--no-abbrev", "-z", "--format=@@%H", "HEAD", "--", folder)
    history = History()
    tokens = out.decode("utf-8", "surrogateescape").split("\0")
    commit = None
    index = 0
    while index < len(tokens):
        token = tokens[index].lstrip("\n")
        index += 1
        if token.startswith("@@"):
            commit = token[2:].strip()
        elif token.startswith(":"):
            if commit is None or index >= len(tokens):
                raise GitCommandError("git_command_failed", ("log",), 0, "unparseable raw history")
            path = tokens[index]
            index += 1
            _old_mode, _new_mode, old, new, status = token[1:].split()[:5]
            kind = status[0]
            history.changes.append((commit, kind, path, old, new))
            if kind == "A":
                history.adds.setdefault(path, set()).add(commit)
            elif kind == "D":
                history.deletes.setdefault(path, set()).add(commit)
            elif kind in ("M", "T"):
                history.rewrites.setdefault(path, set()).add(commit)
            if kind in ("A", "M", "T") and set(new) != {"0"}:
                history.blobs.setdefault(path, set()).add(new)
    for line in _git(repo, "ls-tree", "-r", "-z", "HEAD", "--", folder).decode("utf-8", "surrogateescape").split("\0"):
        if line:
            meta, _, path = line.partition("\t")
            history.head_tree[path] = meta.split()[2]
    return history


def worktree_status(repo: Path, paths: Iterable[str]) -> dict[str, str]:
    """``{path: porcelain status}`` for the given paths (untracked included). Empty when clean."""
    paths = sorted(set(paths))
    if not paths:
        return {}
    out = _git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *paths)
    found = {}
    for entry in out.decode("utf-8", "surrogateescape").split("\0"):
        if len(entry) > 3:
            found[entry[3:]] = entry[:2]
    return found


def resolve_commit(repo: Path, revision: str) -> str:
    return _git(repo, "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}").decode().strip()


def ref_commit_or_none(repo: Path, ref: str) -> str | None:
    """The commit a local ref names, or None when the ref does not exist (any other failure raises)."""
    args = ("rev-parse", "--verify", "-q", "--end-of-options", f"{ref}^{{commit}}")
    completed = _run(Path(repo), args)
    if completed.returncode == 0:
        return completed.stdout.decode().strip()
    if completed.returncode == 1 and not completed.stderr.strip():
        return None
    raise GitCommandError("git_command_failed", args, completed.returncode,
                          completed.stderr.decode("utf-8", "replace")[-STDERR_TAIL:])


def blob_texts(repo: Path, blobs: Mapping[str, Iterable[str]]) -> dict[str, dict[str, str]]:
    """``{path: {blob id: text}}`` for every listed blob (one cat-file process)."""
    wanted = {b for ids in blobs.values() for b in ids}
    raw = read_blobs(repo, wanted)
    return {path: {b: raw[b].decode("utf-8", "replace") for b in ids} for path, ids in blobs.items()}
