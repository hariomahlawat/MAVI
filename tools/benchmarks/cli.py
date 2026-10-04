#!/usr/bin/env python3
"""The benchmark harness command line (S3.2d-1 plan §11). Windows-first; refusals print ``refused <code>``.

Slice 1 provides ``describe`` only:

    python -m tools.benchmarks.cli describe --descriptor <release.json> [--mapping <mapping.json>]
        validates the descriptor (and the mapping against its taxonomy), prints its status and access
        preconditions, and refuses a BLOCKED release.
    python -m tools.benchmarks.cli describe --descriptor <release.json> --freeze-manifest
            --source-root <dir> --out <frozen.json>
        computes the source manifest (every file: path, size, SHA-256) into a descriptor whose manifest is
        empty, writes the frozen descriptor once and prints its SHA-256. Mandatory after acquisition.

``prepare``, ``execute`` and ``evaluate`` arrive with the slices that implement them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.benchmarks.core import descriptor as descriptors  # noqa: E402
from tools.benchmarks.core import mapping as mappings  # noqa: E402
from tools.benchmarks.core.identity import S32Error, canonical_json, require, sha256_hex, write_once  # noqa: E402


def describe(args: argparse.Namespace) -> str:
    document, sha = descriptors.load(args.descriptor)
    descriptors.require_usable(document)
    if args.mapping is not None:
        mapping, _ = mappings.load(args.mapping)
        mappings.check_against(mapping, document)
    if args.freeze_manifest:
        require(args.source_root is not None and args.out is not None, "arguments_invalid:--source-root,--out")
        # A descriptor written inside the source root would itself become an unlisted source file, and every
        # later reconciliation would refuse it as unexpected: refuse the path, however it is spelled.
        require(not args.out.resolve().is_relative_to(args.source_root.resolve()),
                "arguments_invalid:--out_inside_source_root")
        require(not args.out.exists(), "output_exists")
        data = canonical_json(descriptors.freeze(document, args.source_root))
        write_once(args.out, data)
        return sha256_hex(data)
    require(args.source_root is None and args.out is None, "arguments_invalid:--freeze-manifest")
    research = document["researchUse"]
    lines = [
        f"descriptor {sha}",
        f"dataset {document['datasetId']} release {document['release']}",
        f"research-use {research['status']}: {research['basis']}",
        f"manifest {document['manifest']['kind']} entries {len(document['manifest']['entries'])}"
        + ("" if document["manifest"]["entries"] else " (not frozen; prepare will refuse)"),
        *(f"precondition {item}" for item in document["access"]["preconditions"]),
    ]
    return "\n".join(lines)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tools.benchmarks.cli", description=__doc__.splitlines()[0])
    commands = p.add_subparsers(dest="command", required=True)
    d = commands.add_parser("describe", help="validate a release descriptor; optionally freeze its manifest")
    d.add_argument("--descriptor", type=Path, required=True)
    d.add_argument("--mapping", type=Path)
    d.add_argument("--freeze-manifest", action="store_true")
    d.add_argument("--source-root", type=Path)
    d.add_argument("--out", type=Path)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        output = describe(args)
    except S32Error as exc:
        print(f"refused {exc}", file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
