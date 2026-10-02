"""Command line for external dataset releases (Development only; no network).

    verify-release --release RELEASE.json --root STORE [--purpose P ...] [--operation O ...] [--member PATH]

Prints the release SHA-256, file problems and use blockers as JSON. Exit 0 only when every
file verifies and the requested use is authorised; 1 otherwise; 2 on a refused record.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from attributes.corpus.canonical import CorpusError

from .release import ReleaseError, authorise_release_use, parse_release, release_sha256, verify_release_files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="attribute_dataset", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("verify-release")
    v.add_argument("--release", required=True, type=Path)
    v.add_argument("--root", required=True, type=Path)
    v.add_argument("--purpose", action="append", required=True)
    v.add_argument("--operation", action="append", default=[])
    v.add_argument("--member")
    args = parser.parse_args(argv)
    try:
        release = parse_release(json.loads(args.release.read_text(encoding="utf-8")))
        problems = verify_release_files(release, args.root)
        blockers = authorise_release_use(release, args.purpose, args.operation, args.member)
    except (CorpusError, ReleaseError, ValueError, OSError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"releaseSha256": release_sha256(release), "fileProblems": problems, "blockers": blockers}, indent=2, sort_keys=True))
    return 0 if not problems and not blockers else 1
