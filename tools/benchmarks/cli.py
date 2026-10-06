#!/usr/bin/env python3
"""The benchmark harness command line (S3.2d-1 plan §11). Windows-first; refusals print ``refused <code>``.

Commands:

    python -m tools.benchmarks.cli describe --descriptor <release.json> [--mapping <mapping.json>]
        validates the descriptor (and the mapping against its taxonomy), prints its status and access
        preconditions, and refuses a BLOCKED release.
    python -m tools.benchmarks.cli describe --descriptor <release.json> --freeze-manifest
            --source-root <dir> --out <frozen.json>
        computes the source manifest (every file: path, size, SHA-256) into a descriptor whose manifest is
        empty, writes the frozen descriptor once and prints its SHA-256. Mandatory after acquisition.

    python -m tools.benchmarks.cli prepare --descriptor <frozen.json> --source-root <dir> --split <name>
            --adapter <id> --media-tools <ffmpeg pack> --out <new derived dir>
        reconciles the whole manifest, writes canonical ground truth and the derived MP4s, prints the derivation
        manifest's SHA-256.
    python -m tools.benchmarks.cli execute --derived <dir> --pipeline-profile <file> --api <loopback url>
            --journal <file> --exports <dir> --evidence-root <dir> --export-exe <exe> [--export-arg <arg>...]
        one MAVI processing run per prepared sequence on a fresh, dedicated catalogue (the T9 pattern), each
        exported to <exports>/<processingRunId>/; prints one line per sequence.
    python -m tools.benchmarks.cli evaluate --descriptor <frozen.json> --derived <dir> --exports <dir>
            --evidence-root <dir> --mapping <mapping.json> --policy <policy.json> --requirements <file>
            --pipeline-profile <file> --out <results root>
        association, then evaluation and the report, written once to <results root>/<benchmarkRunId>; prints the
        run id.
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


def prepare(args: argparse.Namespace) -> str:
    from tools.benchmarks import prepare as preparation

    return preparation.prepare(descriptor_path=args.descriptor, source_root=args.source_root, split=args.split,
                               adapter_id=args.adapter, media_tools_dir=args.media_tools, out=args.out)


def execute(args: argparse.Namespace) -> str:
    from tools.benchmarks import execute as execution

    rows = execution.execute(derived=args.derived, profile_path=args.pipeline_profile, api_url=args.api,
                             journal_path=args.journal, export_root=args.exports,
                             export_command=[str(args.export_exe), *args.export_arg],
                             evidence_root=args.evidence_root, poll_seconds=args.poll_seconds,
                             development_producer=args.development_producer)
    lines = [f"{row['sequenceId']} {row['processingRunId']} {row['exportSha256']}" for row in rows]
    if args.development_producer is not None:
        lines.insert(0, f"developmentProducer {args.development_producer}")
    return "\n".join(lines)


def evaluate(args: argparse.Namespace) -> str:
    from tools.benchmarks import run

    return run.evaluate(descriptor_path=args.descriptor, derived=args.derived, exports_dir=args.exports,
                        evidence_root=args.evidence_root, mapping_path=args.mapping, policy_path=args.policy,
                        requirements_path=args.requirements, profile_path=args.pipeline_profile, out=args.out)


COMMANDS = {"describe": describe, "prepare": prepare, "execute": execute, "evaluate": evaluate}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tools.benchmarks.cli", description=__doc__.splitlines()[0])
    commands = p.add_subparsers(dest="command", required=True)
    d = commands.add_parser("describe", help="validate a release descriptor; optionally freeze its manifest")
    d.add_argument("--descriptor", type=Path, required=True)
    d.add_argument("--mapping", type=Path)
    d.add_argument("--freeze-manifest", action="store_true")
    d.add_argument("--source-root", type=Path)
    d.add_argument("--out", type=Path)
    pr = commands.add_parser("prepare", help="reconcile, write canonical ground truth and derived MP4s")
    for name in ("--descriptor", "--source-root", "--media-tools", "--out"):
        pr.add_argument(name, type=Path, required=True)
    pr.add_argument("--split", required=True)
    pr.add_argument("--adapter", required=True)
    ex = commands.add_parser("execute", help="run MAVI once per prepared sequence and export each run")
    for name in ("--derived", "--pipeline-profile", "--journal", "--exports", "--evidence-root", "--export-exe"):
        ex.add_argument(name, type=Path, required=True)
    ex.add_argument("--api", required=True)
    ex.add_argument("--export-arg", action="append", default=[])
    ex.add_argument("--poll-seconds", type=float, default=5.0)
    ex.add_argument("--development-producer", default=None,
                    help="required for the A2 Development profile (a2-scale640 | a2-scale1280); refused otherwise")
    ev = commands.add_parser("evaluate", help="associate, evaluate and report one prepared benchmark run")
    for name in ("--descriptor", "--derived", "--exports", "--evidence-root", "--mapping", "--policy",
                 "--requirements", "--pipeline-profile", "--out"):
        ev.add_argument(name, type=Path, required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        output = COMMANDS[args.command](args)
    except S32Error as exc:
        print(f"refused {exc}", file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
