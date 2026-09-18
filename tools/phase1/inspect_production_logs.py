#!/usr/bin/env python3
"""Inspect only the final production acceptance-window log segments."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker

PHASE1_ROOT = Path(__file__).resolve().parent
SERVER_ROLES = {"api", "iis", "postgres"}
WORKER_ROLES = {"formal-worker", "empty-worker", "failure-worker"}
ALL_ROLES = SERVER_ROLES | WORKER_ROLES


class LogInspectionError(ValueError):
    pass


URL_RE = re.compile(
    r"(?:https?|ftp|s3|hf|mim|ssh)://[^\s\"'<>]+|git\+https?://[^\s\"'<>]+",
    re.IGNORECASE,
)
SUSPICIOUS_RE = re.compile(
    r"\b(?:telemetry|analytics|phone[- ]home|activation|"
    r"licen[cs](?:e|ing|ed)|license[- ]server|licence[- ]server)\b",
    re.IGNORECASE,
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_json(path: Path, code: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LogInspectionError(code) from exc
    if not isinstance(value, dict):
        raise LogInspectionError(code)
    return value


def validate_schema(value: dict, schema_name: str, code: str) -> None:
    schema = load_json(PHASE1_ROOT / schema_name, code + "_schema_unavailable")
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        raise LogInspectionError(code + "_schema_invalid")


def validate_allowed_host(host: str) -> str:
    value = host.strip().lower().rstrip(".")
    if not value:
        raise LogInspectionError("production_allowed_host_invalid")
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        if "." not in value or value.endswith((".local", ".lan", ".internal")):
            return value
        raise LogInspectionError("production_allowed_host_not_internal")
    if not (address.is_loopback or address.is_private or address.is_link_local):
        raise LogInspectionError("production_allowed_host_not_internal")
    return value


def inspect_text(text: str, *, allowed_hosts: set[str]) -> tuple[list[str], list[str]]:
    external: list[str] = []
    suspicious: list[str] = []
    for match in URL_RE.finditer(text):
        raw = match.group(0).rstrip(".,);]")
        host = (urlsplit(raw).hostname or "").lower()
        if not host or host not in allowed_hosts:
            external.append(raw)
    for line in text.splitlines():
        if SUSPICIOUS_RE.search(line):
            suspicious.append(line.strip())
    return sorted(set(external)), sorted(set(suspicious))


def parse_logs(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for item in values:
        if "=" not in item:
            raise LogInspectionError("production_log_argument_invalid")
        role, raw_path = item.split("=", 1)
        if role not in ALL_ROLES or role in result or not raw_path:
            raise LogInspectionError("production_log_argument_invalid")
        result[role] = Path(raw_path)
    if set(result) != ALL_ROLES:
        raise LogInspectionError("production_log_roles_incomplete")
    return result


def load_context(path: Path, source_commit: str, mavi_build: str) -> tuple[dict, str]:
    value = load_json(path, "production_acceptance_context_invalid")
    validate_schema(value, "production-acceptance-context.schema.json", "production_acceptance_context")
    if value.get("sourceCommit") != source_commit or value.get("maviBuild") != mavi_build:
        raise LogInspectionError("production_acceptance_context_identity_mismatch")
    return value, sha256_file(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--mavi-build", required=True)
    parser.add_argument("--acceptance-context", type=Path, required=True)
    parser.add_argument("--server-log-checkpoint", type=Path, required=True)
    parser.add_argument("--formal-scenario", type=Path, required=True)
    parser.add_argument("--formal-e2e", type=Path, required=True)
    parser.add_argument("--empty-scene-scenario", type=Path, required=True)
    parser.add_argument("--empty-scene", type=Path, required=True)
    parser.add_argument("--failure-reprocess", type=Path, required=True)
    parser.add_argument("--log", action="append", default=[])
    parser.add_argument("--allowed-host", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.output.exists():
            raise LogInspectionError("production_log_evidence_exists")
        if (
            len(args.source_commit) not in {40, 64}
            or any(ch not in "0123456789abcdef" for ch in args.source_commit)
            or not args.mavi_build
            or args.mavi_build == "unknown-development"
        ):
            raise LogInspectionError("production_log_release_identity_invalid")

        context, context_sha = load_context(
            args.acceptance_context,
            args.source_commit,
            args.mavi_build,
        )
        checkpoint = load_json(
            args.server_log_checkpoint,
            "production_log_checkpoint_invalid",
        )
        validate_schema(
            checkpoint,
            "production-log-checkpoint.schema.json",
            "production_log_checkpoint",
        )
        if (
            checkpoint.get("acceptanceExecutionId") != context["acceptanceExecutionId"]
            or checkpoint.get("acceptanceContextSha256") != context_sha
        ):
            raise LogInspectionError("production_log_checkpoint_context_mismatch")

        formal_scenario = load_json(args.formal_scenario, "production_formal_scenario_invalid")
        empty_scenario = load_json(args.empty_scene_scenario, "production_empty_scenario_invalid")
        failure = load_json(args.failure_reprocess, "production_failure_reprocess_invalid")
        for value in (formal_scenario, empty_scenario, failure):
            if (
                value.get("acceptanceExecutionId") != context["acceptanceExecutionId"]
                or value.get("acceptanceContextSha256") != context_sha
            ):
                raise LogInspectionError("production_log_scenario_context_mismatch")

        allowed_hosts = {"localhost", "127.0.0.1", "::1"}
        for item in args.allowed_host:
            allowed_hosts.add(validate_allowed_host(item))

        log_paths = parse_logs(args.log)
        checkpoints = {
            item["role"]: item
            for item in checkpoint["logs"]
            if isinstance(item, dict)
        }
        if set(checkpoints) != SERVER_ROLES:
            raise LogInspectionError("production_log_checkpoint_roles_incomplete")

        external_hits: list[str] = []
        suspicious_hits: list[str] = []
        logs: list[dict] = []
        for role, path in sorted(log_paths.items()):
            raw = path.read_bytes()
            if role in SERVER_ROLES:
                cp = checkpoints[role]
                if str(path.resolve()) != cp.get("path"):
                    raise LogInspectionError("production_log_checkpoint_path_mismatch:" + role)
                start = int(cp["startOffset"])
                if len(raw) < start or sha256_bytes(raw[:start]) != cp.get("prefixSha256"):
                    raise LogInspectionError("production_log_checkpoint_prefix_mismatch:" + role)
                segment = raw[start:]
                if not segment:
                    raise LogInspectionError("production_log_acceptance_segment_empty:" + role)
            else:
                start = 0
                segment = raw
                if not segment:
                    raise LogInspectionError("production_log_empty:" + role)

            try:
                text = segment.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise LogInspectionError("production_log_not_utf8:" + role) from exc
            external, suspicious = inspect_text(text, allowed_hosts=allowed_hosts)
            external_hits.extend(external)
            suspicious_hits.extend(suspicious)
            logs.append({
                "role": role,
                "path": str(path.resolve()),
                "startOffset": start,
                "endOffset": len(raw),
                "segmentSizeBytes": len(segment),
                "segmentSha256": sha256_bytes(segment),
            })

        external_hits = sorted(set(external_hits))
        suspicious_hits = sorted(set(suspicious_hits))
        if external_hits:
            raise LogInspectionError("production_external_network_reference_detected")
        if suspicious_hits:
            raise LogInspectionError("production_telemetry_or_licence_reference_detected")

        value = {
            "schemaVersion": "mavi-production-log-inspection-evidence-v1",
            "acceptanceExecutionId": context["acceptanceExecutionId"],
            "acceptanceContextSha256": context_sha,
            "serverLogCheckpointSha256": sha256_file(args.server_log_checkpoint),
            "acceptanceStartedAtUtc": context["startedAtUtc"],
            "inspectionCompletedAtUtc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "sourceCommit": args.source_commit,
            "maviBuild": args.mavi_build,
            "formalScenarioSha256": sha256_file(args.formal_scenario),
            "formalE2eSha256": sha256_file(args.formal_e2e),
            "emptySceneScenarioSha256": sha256_file(args.empty_scene_scenario),
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

    print(json.dumps({"ok": True, "sha256": sha256_file(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
