#!/usr/bin/env python3
"""Create the immutable Task-17 final production acceptance execution context."""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--mavi-build", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.output.exists():
        raise SystemExit("production_acceptance_context_exists")
    if (
        len(args.source_commit) not in {40, 64}
        or any(ch not in "0123456789abcdef" for ch in args.source_commit)
        or not args.mavi_build
        or args.mavi_build == "unknown-development"
    ):
        raise SystemExit("production_acceptance_context_identity_invalid")

    value = {
        "schemaVersion": "mavi-production-acceptance-context-v1",
        "acceptanceExecutionId": str(uuid.uuid4()),
        "sourceCommit": args.source_commit,
        "maviBuild": args.mavi_build,
        "startedAtUtc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    args.output.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"ok": True, "sha256": sha256_file(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
