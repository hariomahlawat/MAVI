#!/usr/bin/env python3
"""Capture immutable start offsets for API/IIS/PostgreSQL acceptance logs."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


class LogCheckpointError(ValueError):
    pass


ROLES = {"api", "iis", "postgres"}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_context(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LogCheckpointError("production_acceptance_context_invalid") from exc
    if (
        not isinstance(value, dict)
        or value.get("schemaVersion") != "mavi-production-acceptance-context-v1"
        or not value.get("acceptanceExecutionId")
    ):
        raise LogCheckpointError("production_acceptance_context_invalid")
    return value, sha256_bytes(raw)


def parse_logs(values: list[str]) -> dict[str, Path]:
    result = {}
    for item in values:
        if "=" not in item:
            raise LogCheckpointError("production_log_checkpoint_argument_invalid")
        role, raw = item.split("=", 1)
        if role not in ROLES or role in result or not raw:
            raise LogCheckpointError("production_log_checkpoint_argument_invalid")
        result[role] = Path(raw)
    if set(result) != ROLES:
        raise LogCheckpointError("production_log_checkpoint_roles_incomplete")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acceptance-context", type=Path, required=True)
    parser.add_argument("--log", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.output.exists():
            raise LogCheckpointError("production_log_checkpoint_exists")
        context, context_sha = load_context(args.acceptance_context)
        paths = parse_logs(args.log)
        entries = []
        for role, path in sorted(paths.items()):
            raw = path.read_bytes()
            entries.append({
                "role": role,
                "path": str(path.resolve()),
                "startOffset": len(raw),
                "prefixSha256": sha256_bytes(raw),
            })
        value = {
            "schemaVersion": "mavi-production-log-checkpoint-v1",
            "acceptanceExecutionId": context["acceptanceExecutionId"],
            "acceptanceContextSha256": context_sha,
            "capturedAtUtc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "logs": entries,
        }
        args.output.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (OSError, LogCheckpointError) as exc:
        print(json.dumps({"ok": False, "code": str(exc)}, sort_keys=True))
        return 2

    print(json.dumps({"ok": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
