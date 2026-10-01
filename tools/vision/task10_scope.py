#!/usr/bin/env python3
"""Decide whether Task 10 applies to a pull request (qualification tooling).

Task 10's path filters used to sit on the workflow's ``pull_request`` trigger.
A path-filtered workflow does not run at all for an unrelated pull request, so
its checks never report, and a required check would wait forever. Pull requests
therefore run the workflow unconditionally, and its first job calls this tool.

* ``applicable --files F`` -- prints ``applicable=true`` or ``applicable=false``
  for the changed paths in ``F``, NUL-separated as ``git diff -z`` writes them
  (or newline-separated).

The scope job runs on the pull request's merge commit, the commit GitHub runs
the workflow from and reads the old path filter from. It lists the changed
paths with ``git diff --no-renames --name-only -z HEAD^1 HEAD``, which reports
both the old and the new path of a rename. So the list, this tool and the diff
all describe the commit being qualified.

The globs live in ``tools/vision/task10-scope-paths.txt``. The workflow's push
trigger lists the same globs, and a test holds the two equal.

Every error answers ``true``, as does an empty file list. Changes to the scope
list, this tool or the workflow are always in scope, whatever the list says.
Only a subset of GitHub's glob syntax is supported: ``*`` and ``**``. A list
using anything else is refused, which also answers ``true``. On that subset,
matching is never narrower than GitHub's.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SCOPE_FILE = Path(__file__).resolve().parent / "task10-scope-paths.txt"
ALWAYS_IN_SCOPE = frozenset({
    "tools/vision/task10-scope-paths.txt",
    "tools/vision/task10_scope.py",
    ".github/workflows/task10-runtime-qualification.yml",
})
# GitHub path-filter syntax this tool does not model. "?" means "zero or one of
# the preceding character" there, so treating it as one character would be narrower.
UNSUPPORTED_GLOB_CHARACTERS = frozenset("?+[]{}!")


def read_globs(path: Path = SCOPE_FILE) -> list[str]:
    globs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            unsupported = UNSUPPORTED_GLOB_CHARACTERS & set(line)
            if unsupported:
                raise ValueError(f"unsupported glob syntax {sorted(unsupported)} in {line!r}")
            globs.append(line)
    if not globs:
        raise ValueError("empty scope")
    return globs


def glob_regex(glob: str) -> re.Pattern[str]:
    """GitHub path-filter semantics, never narrower: ``*`` stays within one path
    segment, and ``**`` spans any number of segments, including none."""
    out = []
    index = 0
    while index < len(glob):
        if glob.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
        elif glob.startswith("/**", index) and index + 3 == len(glob):
            out.append("(?:/.*)?")
            index += 3
        elif glob.startswith("**", index):
            out.append(".*")
            index += 2
        elif glob[index] == "*":
            out.append("[^/]*")
            index += 1
        else:
            out.append(re.escape(glob[index]))
            index += 1
    # DOTALL: Git allows a newline inside a path, and "**" must span it too.
    return re.compile("".join(out), re.DOTALL)


def applicable(changed: list[str], globs: list[str]) -> bool:
    if not changed:
        return True  # nothing listed: cannot prove Task 10 is irrelevant
    patterns = [glob_regex(glob) for glob in globs]
    return any(
        path in ALWAYS_IN_SCOPE or any(pattern.fullmatch(path) for pattern in patterns)
        for path in changed
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    app = sub.add_parser("applicable")
    app.add_argument("--files", type=Path, required=True, help="changed paths, NUL- or newline-separated")
    args = parser.parse_args(argv)

    try:
        globs = read_globs()
        data = args.files.read_bytes().decode("utf-8")
        # NUL-separated (git diff -z) keeps a newline inside a path intact.
        changed = [p for p in data.split("\0" if "\0" in data else "\n") if p]
        result = applicable(changed, globs)
        reason = f"{len(changed)} changed path(s)"
    except Exception as exc:  # noqa: BLE001 - any doubt means Task 10 applies
        result, reason = True, f"scope undetermined ({type(exc).__name__}: {exc}); running Task 10"
    print(f"task10-scope: {reason}", file=sys.stderr)
    print(f"applicable={'true' if result else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
