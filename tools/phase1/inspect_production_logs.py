#!/usr/bin/env python3
"""Inspect final production acceptance logs for hidden online dependencies."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit


class LogInspectionError(ValueError):
    pass


URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
SUSPICIOUS_RE = re.compile(
    r"\b(?:telemetry|analytics|phone[- ]home|activation|"
    r"licen[cs](?:e|ing|ed)|license[- ]server|licence[- ]server)\b",
    re.IGNORECASE,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_text(
    text: str,
    *,
    allowed_hosts: set[str],
) -> tuple[list[str], list[str]]:
    external: list[str] = []
    suspicious: list[str] = []

    for match in URL_RE.finditer(text):
        raw = match.group(0).rstrip(".,);]")
        host = (urlsplit(raw).hostname or "").lower()
        if not host:
            external.append(raw)
            continue
        if host not in allowed_hosts:
            external.append(raw)

    for line in text.splitlines():
        if SUSPICIOUS_RE.search(line):
            suspicious.append(line.strip())

    return sorted(set(external)), sorted(set(suspicious))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--mavi-build", required=True)
    parser.add_argument("--formal-e2e", type=Path, required=True)
    parser.add_argument("--empty-scene", type=Path, required=True)
    parser.add_argument("--failure-reprocess", type=Path, required=True)
    parser.add_argument("--log", action="append", default=[])
    parser.add_argument("--allowed-host", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.output.exists():
            raise LogInspectionError("production_log_evidence_exists")
        if not args.log:
            raise LogInspectionError("production_log_input_missing")
        if (
            len(args.source_commit) not in {40, 64}
            or any(ch not in "0123456789abcdef" for ch in args.source_commit)
            or not args.mavi_build
            or args.mavi_build == "unknown-development"
        ):
            raise LogInspectionError("production_log_release_identity_invalid")

        allowed_hosts = {
            "localhost",
            "127.0.0.1",
            "::1",
            *(item.strip().lower() for item in args.allowed_host if item.strip()),
        }

        external_hits: list[str] = []
        suspicious_hits: list[str] = []
        required_roles = {
            "api", "iis", "postgres",
            "formal-worker", "empty-worker", "failure-worker",
        }
        log_paths: dict[str, Path] = {}
        for item in args.log:
            if "=" not in item:
                raise LogInspectionError("production_log_argument_invalid")
            role, raw_path = item.split("=", 1)
            if role not in required_roles or role in log_paths or not raw_path:
                raise LogInspectionError("production_log_argument_invalid")
            log_paths[role] = Path(raw_path)
        if set(log_paths) != required_roles:
            raise LogInspectionError("production_log_roles_incomplete")

        logs = []
        for role, path in sorted(log_paths.items()):
            raw = path.read_bytes()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise LogInspectionError("production_log_not_utf8") from exc
            external, suspicious = inspect_text(
                text,
                allowed_hosts=allowed_hosts,
            )
            external_hits.extend(external)
            suspicious_hits.extend(suspicious)
            logs.append({
                "role": role,
                "path": path.name,
                "sizeBytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            })

        external_hits = sorted(set(external_hits))
        suspicious_hits = sorted(set(suspicious_hits))
        if external_hits:
            raise LogInspectionError(
                "production_external_network_reference_detected"
            )
        if suspicious_hits:
            raise LogInspectionError(
                "production_telemetry_or_licence_reference_detected"
            )

        value = {
            "schemaVersion": "mavi-production-log-inspection-evidence-v1",
            "sourceCommit": args.source_commit,
            "maviBuild": args.mavi_build,
            "formalE2eSha256": sha256_file(args.formal_e2e),
            "emptySceneDiagnosticSha256": sha256_file(args.empty_scene),
            "failureReprocessSha256": sha256_file(args.failure_reprocess),
            "allowedHosts": sorted(allowed_hosts),
            "logs": sorted(logs, key=lambda item: item["role"]),
            "result": {
                "passed": True,
                "externalUrlHits": [],
                "telemetryOrLicenceHits": [],
                "failureCodes": [],
            },
        }
        args.output.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (OSError, LogInspectionError) as exc:
        print(json.dumps({"ok": False, "code": str(exc)}, sort_keys=True))
        return 2

    print(
        json.dumps(
            {"ok": True, "sha256": sha256_file(args.output)},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
