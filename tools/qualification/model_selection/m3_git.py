"""MSR revision M3: the fail-closed Git layer and the one reachable-history walk (authority redesign, invariants A6/A1).

Every M3 Git call runs under ONE isolated execution profile (``git_environment`` and ``_run``; no per-call-site
guards). System and global configuration are disabled (``GIT_CONFIG_NOSYSTEM=1``, ``GIT_CONFIG_GLOBAL`` = the null
device); every inherited ``GIT_*`` variable is dropped except the trace switches (``GIT_TRACE*``), so no environment
can redirect the repository, the object store, the configuration (``GIT_CONFIG_COUNT``/``KEY``/``VALUE``,
``GIT_CONFIG_PARAMETERS``), URL rewriting, SSH, askpass or the exec path; and fixed ``-c`` options pin
``core.longpaths=true`` (Windows MAX_PATH), no fsmonitor or untracked cache, no colour, no signature display, no path
quoting and no relative diffs. ``GIT_NO_REPLACE_OBJECTS=1``, ``GIT_TERMINAL_PROMPT=0``, ``LC_ALL=C`` and
``GIT_OPTIONAL_LOCKS=0`` are set. The repository's own ``.git/config`` still applies to repository-local commands; the
canonical-remote check therefore never runs inside the repository (``m3_authority.check_live_anchor`` runs it inside a
fresh bare repository it creates), and a repository-less call (``repo=None``) must name its working directory and runs
with ``GIT_CEILING_DIRECTORIES`` at that directory's parent, so no enclosing repository (and none of its
``url.*.insteadOf`` or other configuration) is ever discovered (IP-5 I1). The one explicit carry-over is line-ending
normalisation for work-tree status (``core.autocrlf``/``core.eol``, validated, read without any injected
``GIT_CONFIG_*``; IP-5 I4), so a normal Windows checkout is not misread as modified.

Work-tree status (``worktree_status``) closes the filter, ignore and index-flag routes (IP-5 I2): ignored files are
reported (``!!``) and count as dirty; a ``filter``, ``ident`` or ``working-tree-encoding`` attribute on a checked path
(from any attributes source) refuses before ``git status`` runs (no clean filter is ever executed). ``git status``
still trusts Git's stat cache, so a same-size, mtime-preserving edit can stay invisible to it (reproduced on Windows,
where ctime is the creation time). Status alone is therefore never the integrity check for a file whose content
matters: callers compare such a file with its committed blob by content (``immutable_blob_matches``); M3 does so for
every committed event file (``m3_authority.check_event_history``).

A non-zero exit raises ``GitCommandError`` (code ``git_command_failed``) carrying the arguments, the return code and
the tail of stderr. It is a ``CredibilityError``, so it is always a refusal, and it is never mapped by a caller to
"mismatch", "absent", "deleted" or "success": an infrastructure failure stays distinguishable from an integrity
finding. A cleanliness check (``worktree_status``) also refuses any stderr output with exit 0 (for example a file Git
could not stat) and index flags that hide work-tree changes (skip-worktree, assume-unchanged).

Historical content is read **by blob id** from the walk (``read_blobs``, one ``git cat-file --batch`` process), never
by ``git show <commit>:<path>``. A missing object raises ``git_object_missing``.

Authority needs complete, unaltered history: ``git_history_state`` refuses a shallow clone, a graft file and a
directory that is not the top of a Git work tree. Replace objects are ignored (``GIT_NO_REPLACE_OBJECTS``).

Standard library only.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .credibility import MODEL_SELECTION_DIR, CredibilityError, _fail

# Inherited GIT_* variables that are kept: tracing only (they change no behaviour; the Windows diagnostic uses them).
_KEPT = frozenset({"GIT_TRACE", "GIT_TRACE_SETUP", "GIT_TRACE_PERFORMANCE", "GIT_TRACE2", "GIT_TRACE2_PERF",
                   "GIT_TRACE2_EVENT", "GIT_TRACE2_BRIEF"})
_FIXED = {"GIT_NO_REPLACE_OBJECTS": "1", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0",
          "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
ISOLATION_OPTIONS = ("-c", "core.longpaths=true", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
                     "-c", "color.ui=never", "-c", "log.showSignature=false", "-c", "core.quotePath=false",
                     "-c", "diff.relative=false", "-c", "core.safecrlf=false")
_LINE_ENDING_VALUES = {"core.autocrlf": ("true", "false", "input"), "core.eol": ("lf", "crlf", "native")}
# The only inherited GIT_* variables the line-ending read keeps: they locate the user's ordinary configuration files.
_LINE_ENDING_KEPT = frozenset({"GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM"})
# Attributes that make ``git status`` compare a transformed work-tree file (a clean filter, keyword expansion or a
# re-encoding) and can therefore hide an edit; on a checked path each must be unspecified (or explicitly unset).
STATUS_ALTERING_ATTRIBUTES = ("filter", "ident", "working-tree-encoding")
STDERR_TAIL = 2000


class GitCommandError(CredibilityError):
    """A Git command failed (non-zero exit). Always a refusal; never an integrity verdict.

    ``str(error)`` starts with the stable code (``git_command_failed`` or ``git_object_missing``)."""

    def __init__(self, code: str, args: tuple[str, ...], returncode: int, stderr: str):
        self.code, self.git_args, self.returncode, self.stderr = code, tuple(args), returncode, stderr
        super().__init__(f"{code}:{' '.join(args[:3])}:rc={returncode}:{stderr.strip()}")


def git_environment() -> dict[str, str]:
    """The isolated environment of every M3 Git call."""
    environment = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_") or k.upper() in _KEPT}
    environment.update(_FIXED)
    return environment


def _run(repo: Path | None, args: tuple[str, ...], data: bytes | None = None, *, options: tuple[str, ...] = (),
         cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run Git under the isolated profile, in ``repo`` (``-C``) or, with ``repo=None``, in ``cwd`` only.

    A repository-less call must name ``cwd`` (a directory the caller created) and runs with ``GIT_CEILING_DIRECTORIES``
    set to its parent: Git can then never discover an enclosing repository, whose configuration would otherwise apply
    (I1)."""
    environment = git_environment()
    if repo is not None:
        location: tuple[str, ...] = ("-C", str(repo))
    else:
        if cwd is None:
            raise ValueError("a repository-less M3 Git call must name its working directory")
        location = ()
        environment["GIT_CEILING_DIRECTORIES"] = str(Path(cwd).resolve().parent)
    return subprocess.run(["git", *ISOLATION_OPTIONS, *options, *location, *args], input=data, capture_output=True,
                          check=False, env=environment, cwd=None if cwd is None else str(cwd))


def _git(repo: Path, *args: str, input: bytes | None = None) -> bytes:  # noqa: A002 - mirrors subprocess
    """Run Git; return stdout. Any non-zero exit raises ``GitCommandError`` (fail closed)."""
    completed = _run(Path(repo), args, input)
    if completed.returncode != 0:
        raise GitCommandError("git_command_failed", args, completed.returncode,
                              completed.stderr.decode("utf-8", "replace")[-STDERR_TAIL:])
    return completed.stdout


def line_ending_options(repo: Path) -> tuple[str, ...]:
    """The repository user's effective ``core.autocrlf``/``core.eol`` (the only settings carried into the isolated
    profile, and only for work-tree status). Read with the user's ordinary configuration files (system, global,
    repository) only: every inherited ``GIT_*`` variable is dropped except the ones that locate those files
    (``_LINE_ENDING_KEPT``), so ``GIT_CONFIG_PARAMETERS``, ``GIT_CONFIG_COUNT``, ``GIT_CONFIG_KEY_*`` and
    ``GIT_CONFIG_VALUE_*`` injection is inert (I4). Any value outside the documented set refuses."""
    environment = {k: v for k, v in os.environ.items()
                   if not k.upper().startswith("GIT_") or k.upper() in _LINE_ENDING_KEPT}
    found: list[str] = []
    for key, allowed in _LINE_ENDING_VALUES.items():
        completed = subprocess.run(["git", "-C", str(repo), "config", "--get", key], capture_output=True, check=False,
                                   env=environment)
        if completed.returncode == 1:
            continue
        value = completed.stdout.decode("utf-8", "replace").strip().lower()
        if completed.returncode != 0 or value not in allowed:
            raise GitCommandError("git_command_failed", ("config", "--get", key), completed.returncode,
                                  f"unsupported {key}={value!r} {completed.stderr.decode('utf-8', 'replace')}")
        found += ["-c", f"{key}={value}"]
    return tuple(found)


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
    try:
        same = Path(top).resolve() == repo.resolve() or os.path.samefile(top, repo)  # 8.3 names, case on Windows
    except OSError:
        same = False
    if not same:
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
    return path_history(repo, MODEL_SELECTION_DIR.as_posix())


def path_history(repo: Path, folder: str) -> History:
    """The same single reachable-history walk for one repository path (a directory or a file), under the isolated
    profile. ``model_selection_history`` is this walk of the model-selection directory; the Stage-4 plate harness uses
    it for its committed freeze record (an add-only precondition, not an authority). Requires full history."""
    repo = Path(repo)
    git_history_state(repo)
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
    """``{path: porcelain status}`` for the given paths (untracked and ignored included). Empty when clean.

    Fail closed: any stderr output (for example a path Git could not stat) is a ``GitCommandError`` even with exit 0;
    an index entry flagged skip-worktree or assume-unchanged (which hides work-tree edits from status) is refused
    (``worktree_index_flags_hide_changes``); a ``filter``/``ident``/``working-tree-encoding`` attribute on the paths or
    any tracked file under them is refused BEFORE status runs (``worktree_attribute_hides_changes``); and an ignored
    file is reported as ``!!`` (dirty), so ``.gitignore``, ``info/exclude`` or ``core.excludesFile`` cannot hide one.
    Git's stat cache can still miss a same-size, mtime-preserving edit; immutable files are therefore also checked by
    content (``immutable_blob_matches``)."""
    paths = sorted(set(paths))
    if not paths:
        return {}
    repo = Path(repo)
    options = line_ending_options(repo)
    flags_args = ("ls-files", "-v", "-z", "--", *paths)
    flagged = _run(repo, flags_args, options=options)
    flags_err = flagged.stderr.decode("utf-8", "replace")
    if flagged.returncode != 0 or flags_err.strip():
        raise GitCommandError("git_command_failed", flags_args, flagged.returncode, flags_err[-STDERR_TAIL:])
    tracked = []
    for entry in flagged.stdout.decode("utf-8", "surrogateescape").split("\0"):
        if len(entry) > 2 and (entry[0] == "S" or entry[0].islower()):
            raise _fail("worktree_index_flags_hide_changes", entry[2:])
        if len(entry) > 2:
            tracked.append(entry[2:])
    _refuse_status_altering_attributes(repo, sorted(set(paths) | set(tracked)), options)
    args = ("status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored=matching", "--", *paths)
    completed = _run(repo, args, options=options)
    stderr = completed.stderr.decode("utf-8", "replace")
    if completed.returncode != 0 or stderr.strip():
        raise GitCommandError("git_command_failed", args, completed.returncode, stderr[-STDERR_TAIL:])
    found = {}
    for entry in completed.stdout.decode("utf-8", "surrogateescape").split("\0"):
        if len(entry) > 3:
            found[entry[3:]] = entry[:2]
    return found


def _refuse_status_altering_attributes(repo: Path, paths: list[str], options: tuple[str, ...]) -> None:
    """``git check-attr`` (every attributes source Git itself uses for status) for ``STATUS_ALTERING_ATTRIBUTES``."""
    args = ("check-attr", "-z", "--stdin", *STATUS_ALTERING_ATTRIBUTES)
    data = "".join(f"{p}\0" for p in paths).encode("utf-8", "surrogateescape")
    completed = _run(repo, args, data, options=options)
    stderr = completed.stderr.decode("utf-8", "replace")
    if completed.returncode != 0 or stderr.strip():
        raise GitCommandError("git_command_failed", args, completed.returncode, stderr[-STDERR_TAIL:])
    fields = completed.stdout.decode("utf-8", "surrogateescape").split("\0")
    if len(fields) % 3 != 1 or fields[-1] != "":
        raise GitCommandError("git_command_failed", args, 0, "unparseable check-attr output")
    for index in range(0, len(fields) - 1, 3):
        path, attribute, value = fields[index:index + 3]
        if value not in ("unspecified", "unset"):
            raise _fail("worktree_attribute_hides_changes", f"{path}:{attribute}={value}")


def git_blob_id(data: bytes, object_format: str) -> str:
    """The Git object id of a blob with exactly these bytes (``sha1`` or ``sha256`` object format)."""
    return hashlib.new(object_format, b"blob %d\0" % len(data) + data).hexdigest()


def immutable_blob_matches(repo: Path, path: str, blob_id: str, *, lf_only: bool) -> bool:
    """Whether the work-tree file ``path`` (relative to ``repo``) has the content of the committed blob ``blob_id``,
    by content, never by Git's stat cache (which a same-size, mtime-preserving edit defeats). Generic and
    path-independent: the caller supplies the path and the blob id it trusts (for example a ``History.head_tree``
    entry); nothing here knows which artefact it is.

    * ``lf_only=True`` (classes that are LF-only by construction, such as canonical JSON): the work-tree bytes with
      CRLF -> LF are hashed as a blob and compared with ``blob_id``. The stated assumption is that the committed blob
      contains no CR LF; a blob that does never matches (fail closed).
    * ``lf_only=False`` (text such as Markdown): the LF-normalised work-tree bytes are compared with the LF-normalised
      committed blob bytes (read by id).
    A missing, non-regular or unreadable work-tree file never matches."""
    target = Path(repo) / path
    if os.name == "nt":  # an extended-length path: a work-tree file beyond MAX_PATH is still read, never misjudged
        absolute = str(target.resolve())
        target = Path(absolute if absolute.startswith("\\\\") else "\\\\?\\" + absolute)
    try:
        work = target.read_bytes() if target.is_file() and not target.is_symlink() else None
    except OSError:
        work = None
    if work is None:
        return False
    work = work.replace(b"\r\n", b"\n")
    if lf_only:
        object_format = {40: "sha1", 64: "sha256"}.get(len(blob_id))
        return object_format is not None and git_blob_id(work, object_format) == blob_id
    return read_blobs(repo, [blob_id])[blob_id].replace(b"\r\n", b"\n") == work


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
