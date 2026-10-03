#!/usr/bin/env python3
"""Frozen pilot source pool (Stage 3, S3.2 plan T7): ``vehicle-subclass-source-pool-v1``.

Freezes 6–10 release members chosen from source-side facts only, before any MAVI import.
The tool accepts the release record and store, the members' probe records and a human
selection; it has no option that accepts an export, attestation, label, sample or result,
so the pool cannot be chosen from MAVI output. The release is read, verified and authorised
only through ``attributes.datasets.release`` (``operations=[]``: selection uses the members
as they are). This tool produces the ``pilot`` pool; a later ``supplemental`` pool is a
separate, later step and is not produced here.

Selection file: ``{"members": [{"member", "sourceCamera", "inclusionReason"}, ...]}``.

Usage: ``freeze_source_pool.py --release <record> --release-root <dir> --probe <file>...
--selection <file> --out <file>``. ``--release-root`` is runtime-only and never recorded.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import artefacts as a  # noqa: E402
import release_bridge as rb  # noqa: E402

SCHEMA = "vehicle-subclass-source-pool-v1"
PROBE_SCHEMA = "vehicle-subclass-media-probe-v1"
PROCEDURE = "s3-2-source-pool-manual-v1"
CODE = "source_pool_invalid"
PILOT_MIN, PILOT_MAX = 6, 10
TEXT_MAX = 200


def _selection(path: Path) -> list[dict[str, str]]:
    document = a.parse_json(a.read_bytes(path, f"{CODE}:selection"), f"{CODE}:selection")
    a.require(isinstance(document, dict) and set(document) == {"members"} and isinstance(document["members"], list),
              f"{CODE}:selection")
    entries = []
    for item in document["members"]:
        a.require(isinstance(item, dict) and set(item) == {"member", "sourceCamera", "inclusionReason"},
                  f"{CODE}:selection_entry")
        a.require(isinstance(item["member"], str), f"{CODE}:selection_entry")
        entries.append({
            "member": item["member"],
            "sourceCamera": rb.free_text(item["sourceCamera"], f"{CODE}:source_camera", TEXT_MAX),
            "inclusionReason": rb.free_text(item["inclusionReason"], f"{CODE}:inclusion_reason", TEXT_MAX),
        })
    return entries


def _probes(paths: list[Path]) -> dict[str, tuple[dict[str, Any], str]]:
    """Probe records keyed by the content they describe."""
    probes: dict[str, tuple[dict[str, Any], str]] = {}
    for path in paths:
        document, _, sha = a.read_artefact(path, PROBE_SCHEMA, f"{CODE}:probe")
        a.require(document["sourceSha256"] not in probes, f"{CODE}:probe_duplicate")
        probes[document["sourceSha256"]] = (document, sha)
    return probes


def freeze(*, release_path: Path, release_root: Path, probe_paths: list[Path], selection_path: Path) -> bytes:
    release, release_sha = rb.read_release(release_path, f"{CODE}:release")
    rb.verify_store(release, release_root, f"{CODE}:release_root", f"{CODE}:release_files")
    selection = _selection(selection_path)
    names = [entry["member"] for entry in selection]
    a.require(len(names) == len(set(names)), f"{CODE}:duplicate_member")
    a.require(PILOT_MIN <= len(names) <= PILOT_MAX, f"{CODE}:member_count")
    probes = _probes(probe_paths)

    members = []
    used_probes: set[str] = set()
    for entry in selection:
        listed = rb.member_entry(release, entry["member"], f"{CODE}:member_not_listed", f"{CODE}:member_excluded")
        blockers = rb.authorise(release, entry["member"], [])
        a.require(not blockers, f"{CODE}:not_authorised:" + ",".join(blockers))
        a.require(listed["sha256"] in probes, f"{CODE}:probe_missing")
        probe, probe_sha = probes[listed["sha256"]]
        a.require(probe["sourceSizeBytes"] == listed["sizeBytes"], f"{CODE}:probe_mismatch")
        used_probes.add(listed["sha256"])
        members.append({"member": entry["member"], "sha256": listed["sha256"], "sizeBytes": listed["sizeBytes"],
                        "probeSha256": probe_sha, "sourceCamera": entry["sourceCamera"],
                        "inclusionReason": entry["inclusionReason"]})
    contents = [member["sha256"] for member in members]
    # Identical content under two names would later be one scene counted twice (export_video_duplicate).
    a.require(len(contents) == len(set(contents)), f"{CODE}:duplicate_content")
    # A probe that describes no selected member is a probe of something else.
    a.require(used_probes == set(probes), f"{CODE}:probe_unmatched")

    document = {
        "schemaVersion": SCHEMA,
        "releaseId": release["releaseId"],
        "releaseRecordSha256": release_sha,
        "kind": "pilot",
        "selectionProcedure": {"id": PROCEDURE},
        "members": sorted(members, key=lambda member: member["member"]),
    }
    a.validate(document, SCHEMA, CODE)
    return a.canonical_json(document)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--release", type=Path, required=True)
    p.add_argument("--release-root", type=Path, required=True)
    p.add_argument("--probe", type=Path, action="append", required=True)
    p.add_argument("--selection", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        a.require(not args.out.exists(), "output_exists")
        data = freeze(release_path=args.release, release_root=args.release_root, probe_paths=args.probe,
                      selection_path=args.selection)
        a.write_once(args.out, data)
    except a.S32Error as exc:
        print(f"refused {exc}", file=sys.stderr)
        return 2
    print(a.sha256_hex(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
