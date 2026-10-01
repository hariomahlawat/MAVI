#!/usr/bin/env python3
"""Decide whether Task 10 applies to a pull request (qualification tooling).

Task 10's path filters used to sit on the workflow's ``pull_request`` trigger.
A path-filtered workflow does not run at all for an unrelated pull request, so
its checks never report, and a required check would wait forever. Pull requests
therefore run the workflow unconditionally, and its first job calls this tool.

* ``applicable`` -- prints ``applicable=true`` or ``applicable=false`` for the
  changed files of a pull request, read from GitHub or from ``--files``.

The globs live in ``tools/vision/task10-scope-paths.txt``. The workflow's push
trigger lists the same globs, and a test holds the two equal.

Every error answers ``true``: an unreachable API, an unreadable list, an empty
or truncated file list. Changes to the scope list, this tool or the workflow
are always in scope, whatever the list says. The tool may over-match a glob,
which only runs Task 10 unnecessarily, but never under-match one.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

SCOPE_FILE = Path(__file__).resolve().parent / "task10-scope-paths.txt"
ALWAYS_IN_SCOPE = frozenset({
    "tools/vision/task10-scope-paths.txt",
    "tools/vision/task10_scope.py",
    ".github/workflows/task10-runtime-qualification.yml",
})
# GitHub's pull request files API lists at most 3000 files.
API_FILE_LIMIT = 3000


def read_globs(path: Path = SCOPE_FILE) -> list[str]:
    globs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            if line.startswith("!"):
                raise ValueError("negated globs are not supported")
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
        elif glob[index] == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(glob[index]))
            index += 1
    return re.compile("".join(out))


def applicable(changed: list[str], globs: list[str]) -> bool:
    if not changed:
        return True  # nothing listed: cannot prove Task 10 is irrelevant
    patterns = [glob_regex(glob) for glob in globs]
    return any(
        path in ALWAYS_IN_SCOPE or any(pattern.fullmatch(path) for pattern in patterns)
        for path in changed
    )


def _get(url: str, token: str) -> object:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    request.add_unredirected_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def pull_request_files(repository: str, number: int, token: str, api: str) -> list[str] | None:
    """Every path a pull request touches, renames' old paths included, or ``None``
    when the list may be incomplete."""
    files: list[str] = []
    for page in range(1, API_FILE_LIMIT // 100 + 1):
        batch = _get(f"{api}/repos/{repository}/pulls/{number}/files?per_page=100&page={page}", token)
        if not isinstance(batch, list):
            return None
        for entry in batch:
            files.append(entry["filename"])
            if entry.get("previous_filename"):
                files.append(entry["previous_filename"])
        if len(batch) < 100:
            return files
    return None  # at the API limit: possibly truncated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    app = sub.add_parser("applicable")
    app.add_argument("--files", type=Path, help="newline-separated changed paths instead of the GitHub API")
    app.add_argument("--pull-request", type=int)
    args = parser.parse_args(argv)

    reason = "matched"
    try:
        globs = read_globs()
        if args.files is not None:
            changed: list[str] | None = [p for p in args.files.read_text(encoding="utf-8").splitlines() if p]
        else:
            changed = pull_request_files(
                os.environ["GITHUB_REPOSITORY"], args.pull_request, os.environ["GITHUB_TOKEN"],
                os.environ.get("GITHUB_API_URL", "https://api.github.com"),
            )
        if changed is None:
            result, reason = True, "file list possibly truncated"
        else:
            result = applicable(changed, globs)
            reason = f"{len(changed)} changed path(s)"
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError) as exc:
        result, reason = True, f"scope undetermined ({exc}); running Task 10"
    print(f"task10-scope: {reason}", file=sys.stderr)
    print(f"applicable={'true' if result else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
