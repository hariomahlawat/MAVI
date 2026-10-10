#!/usr/bin/env python3
"""Decide which MAVI Quality Gate lanes a pull request's changed paths make
applicable.

The Quality Gate's aggregate check, ``quality``, must report on every pull
request into ``main``, so the workflow runs unconditionally and its first job
calls this tool on the pull request's merge commit (the Task 10 pattern,
``tools/vision/task10_scope.py``). The expensive lanes then run only where the
change can reach them, and ``quality`` requires every applicable lane to
succeed and every non-applicable lane to have been skipped.

* ``lanes --files F`` -- prints one ``<lane>=true|false`` line per lane for
  the changed paths in ``F`` (NUL-separated as ``git diff -z`` writes them, or
  newline-separated), plus ``reason=<text>``.

Rules (``tools/ci/quality-scope.json``):

* a path matching a lane's globs makes that lane applicable;
* a path in ``always`` makes every lane applicable (the gate's own workflow
  and this tool);
* a path matching only ``inert`` globs makes no lane applicable (documents,
  Markdown, editor and Git metadata) -- the always-run repository-contract
  job still validates it;
* a path matching nothing is unknown and makes every lane applicable;
* an empty list, an unreadable list, an unparseable scope or any other error
  makes every lane applicable. Any doubt answers "run".

A rename lists both its old and new path (``git diff --no-renames``), so a
file moved out of a lane still runs that lane once.

Only ``*`` and ``**`` of GitHub's glob syntax are supported; a list using
anything else is refused, which answers "run everything". On that subset the
matching is never narrower than GitHub's.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCOPE_FILE = Path(__file__).resolve().parent / "quality-scope.json"
UNSUPPORTED_GLOB_CHARACTERS = frozenset("?+[]{}!")


class ScopeError(ValueError):
    """The scope list cannot be trusted; every lane applies."""


def glob_regex(glob: str) -> re.Pattern[str]:
    """GitHub path-filter semantics, never narrower: ``*`` stays within one
    path segment and ``**`` spans any number of segments, including none."""
    unsupported = UNSUPPORTED_GLOB_CHARACTERS & set(glob)
    if unsupported:
        raise ScopeError(f"unsupported glob syntax {sorted(unsupported)} in {glob!r}")
    out: list[str] = []
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
    return re.compile("".join(out), re.DOTALL)


def read_scope(path: Path = SCOPE_FILE) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ScopeError(f"cannot read {path.name}: {exc}") from exc
    lanes = raw.get("lanes")
    if not isinstance(lanes, dict) or not lanes:
        raise ScopeError("no lanes declared")
    scope = {
        "always": [glob_regex(g) for g in raw.get("always", [])],
        "inert": [glob_regex(g) for g in raw.get("inert", [])],
        "lanes": {},
    }
    for lane, globs in lanes.items():
        if not re.fullmatch(r"[a-z][a-z0-9-]*", lane):
            raise ScopeError(f"lane name {lane!r} is not a workflow-safe identifier")
        if not isinstance(globs, list) or not globs:
            raise ScopeError(f"lane {lane!r} has no globs")
        scope["lanes"][lane] = [glob_regex(g) for g in globs]
    return scope


def classify(path: str, scope: dict) -> tuple[str, frozenset[str]]:
    """One path's verdict: ``("always"|"lanes"|"inert"|"unknown", lanes)``."""
    every = frozenset(scope["lanes"])
    if any(p.fullmatch(path) for p in scope["always"]):
        return "always", every
    hit = frozenset(lane for lane, patterns in scope["lanes"].items() if any(p.fullmatch(path) for p in patterns))
    if hit:
        return "lanes", hit
    if any(p.fullmatch(path) for p in scope["inert"]):
        return "inert", frozenset()
    return "unknown", every


def applicable_lanes(changed: list[str], scope: dict) -> tuple[dict[str, bool], str]:
    """Which lanes apply, and why, for a list of changed paths."""
    every = list(scope["lanes"])
    if not changed:
        return {lane: True for lane in every}, "no changed paths listed; running every lane"
    applicable: set[str] = set()
    reasons: list[str] = []
    for path in changed:
        kind, lanes = classify(path, scope)
        applicable |= lanes
        if kind == "always":
            reasons.append(f"{path}: gate workflow or scope tool; every lane")
        elif kind == "unknown":
            reasons.append(f"{path}: not classified; every lane")
    if not reasons:
        reasons.append(f"{len(changed)} changed path(s), {len(applicable)} lane(s) applicable")
    return {lane: lane in applicable for lane in every}, "; ".join(reasons[:5])


def read_changed(path: Path) -> list[str]:
    data = path.read_bytes().decode("utf-8")
    # NUL-separated (git diff -z) keeps a newline inside a path intact.
    return [p for p in data.split("\0" if "\0" in data else "\n") if p]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    lanes_cmd = sub.add_parser("lanes")
    lanes_cmd.add_argument("--files", type=Path, required=True, help="changed paths, NUL- or newline-separated")
    args = parser.parse_args(argv)

    try:
        scope = read_scope()
        verdict, reason = applicable_lanes(read_changed(args.files), scope)
    except Exception as exc:  # noqa: BLE001 - any doubt means every lane runs
        try:
            names = list(json.loads(SCOPE_FILE.read_text(encoding="utf-8"))["lanes"])
        except Exception:  # noqa: BLE001
            names = []
        verdict = {lane: True for lane in names}
        reason = f"scope undetermined ({type(exc).__name__}: {exc}); running every lane"
        if not names:
            # Not even the lane names can be read: the step fails, every lane is
            # skipped for want of a scope decision, and `quality` fails on the
            # scope job's result — never a pass.
            print(f"quality-scope: {reason}", file=sys.stderr)
            return 1
    print(f"quality-scope: {reason}", file=sys.stderr)
    for lane, on in verdict.items():
        print(f"{lane}={'true' if on else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
