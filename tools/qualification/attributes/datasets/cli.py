"""Command line for external dataset releases (Development only; no network).

    verify-release --release RELEASE.json --root STORE [--purpose P ...] [--operation O ...] [--member PATH]
    build-person   --pa100k-release R --pa100k-root DIR --upar-release R --upar-root DIR --out-dir DIR [--smoke]
    measure        --still-dataset M --pa100k-release R --pa100k-root DIR --upar-release R --out FILE [--role ROLE ...] [--probe-config C]

verify-release prints the release SHA-256, file problems and use blockers as JSON. Exit 0
only when every file verifies and the requested use is authorised; 1 otherwise; 2 on a
refused record.

build-person writes ``still-dataset.json`` and ``near-duplicates.json`` (canonical JSON)
into a new directory outside Git and prints their SHA-256s. Exit 2 when the build is
refused.

measure writes one canonical ``mavi-attribute-component-result-v1`` file (outside Git,
never overwriting) and prints its SHA-256. Default role: ``benchmark``. Exit 2 when
refused.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from attributes.corpus.canonical import CorpusError, canonical_json, sha256_hex
from source_acquisition.acquire import git_worktree_ancestor

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
    b = sub.add_parser("build-person")
    for name in ("--pa100k-release", "--pa100k-root", "--upar-release", "--upar-root", "--out-dir"):
        b.add_argument(name, required=True, type=Path)
    b.add_argument("--smoke", action="store_true")
    m = sub.add_parser("measure")
    for name in ("--still-dataset", "--pa100k-release", "--pa100k-root", "--upar-release", "--out"):
        m.add_argument(name, required=True, type=Path)
    m.add_argument("--role", action="append", default=None)
    m.add_argument("--probe-config", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.command == "build-person":
        return _build_person(args)
    if args.command == "measure":
        return _measure(args)
    try:
        release = parse_release(json.loads(args.release.read_text(encoding="utf-8")))
        problems = verify_release_files(release, args.root)
        blockers = authorise_release_use(release, args.purpose, args.operation, args.member)
    except (CorpusError, ReleaseError, ValueError, OSError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"releaseSha256": release_sha256(release), "fileProblems": problems, "blockers": blockers}, indent=2, sort_keys=True))
    return 0 if not problems and not blockers else 1


def _build_person(args) -> int:
    from .still_manifest import build_person_manifest, still_dataset_sha256

    try:
        out = args.out_dir.expanduser().resolve()
        if git_worktree_ancestor(out) is not None:
            raise ReleaseError("output directory is inside a Git worktree; refusing")
        if out.exists():
            raise ReleaseError("output directory already exists; refusing to overwrite")
        pa = parse_release(json.loads(args.pa100k_release.read_text(encoding="utf-8")))
        up = parse_release(json.loads(args.upar_release.read_text(encoding="utf-8")))
        manifest, report = build_person_manifest(pa, args.pa100k_root, up, args.upar_root, smoke=args.smoke)
    except (CorpusError, ReleaseError, ValueError, OSError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    out.mkdir(parents=True)
    (out / "still-dataset.json").write_bytes(canonical_json(manifest))
    (out / "near-duplicates.json").write_bytes(canonical_json(report))
    print(json.dumps({"stillDatasetSha256": still_dataset_sha256(manifest), "nearDuplicatesSha256": sha256_hex(canonical_json(report)),
                      "counts": manifest["counts"], "refusedSamples": len(manifest["refusedSamples"]),
                      "exactDuplicateDrops": len(manifest["exactDuplicateDrops"]), "nearDuplicates": report["totals"]}, indent=2, sort_keys=True))
    return 0


def _measure(args) -> int:
    from .colour_probe import CONFIG_PATH, load_probe_config, probe_sha256
    from .measure import load_manifest_file, measure_person, result_sha256

    try:
        out = args.out.expanduser().resolve()
        if git_worktree_ancestor(out.parent) is not None:
            raise ReleaseError("output is inside a Git worktree; refusing")
        if out.exists():
            raise ReleaseError("output already exists; refusing to overwrite")
        manifest = load_manifest_file(args.still_dataset)
        pa = parse_release(json.loads(args.pa100k_release.read_text(encoding="utf-8")))
        up = parse_release(json.loads(args.upar_release.read_text(encoding="utf-8")))
        config = load_probe_config(args.probe_config or CONFIG_PATH)
        result = measure_person(manifest, pa, args.pa100k_root, up, args.role or ["benchmark"], config)
    except (CorpusError, ReleaseError, ValueError, OSError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "xb") as handle:
        handle.write(canonical_json(result))
    print(json.dumps({"componentResultSha256": result_sha256(result), "stillDatasetSha256": result["evidence"]["stillDatasetSha256"],
                      "methodConfigSha256": probe_sha256(config), "rolesMeasured": result["rolesMeasured"]}, indent=2, sort_keys=True))
    return 0
