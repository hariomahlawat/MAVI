#!/usr/bin/env python3
"""Validate observed production prerequisites against the canonical approved baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

PHASE1_ROOT = Path(__file__).resolve().parent
if str(PHASE1_ROOT) not in sys.path:
    sys.path.insert(0, str(PHASE1_ROOT))

from production_acceptance_context import (
    AcceptanceContextError,
    load_context as load_acceptance_context,
)
from policy_identity import (  # noqa: E402
    PolicyIdentityError,
    canonical_production_prerequisites,
)


class PrerequisiteEvidenceError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PrerequisiteEvidenceError(code) from exc
    if not isinstance(value, dict):
        raise PrerequisiteEvidenceError(code)
    return value


def validate_schema(
    value: dict[str, Any],
    schema_name: str,
    code: str,
) -> None:
    schema = load_json(PHASE1_ROOT / schema_name, code + "_schema_unavailable")
    errors = sorted(
        Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).iter_errors(value),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        raise PrerequisiteEvidenceError(code + "_schema_invalid")


def validate_observations(
    policy: dict[str, Any],
    windows: dict[str, Any],
    database: dict[str, Any],
    linux: dict[str, Any],
    *,
    acceptance_execution_id: str,
    acceptance_context_sha256: str,
    context_started_at: str,
) -> None:
    if policy.get("approvalStatus") != "approved":
        raise PrerequisiteEvidenceError(
            "production_prerequisite_policy_not_approved"
        )

    try:
        context_start = datetime.fromisoformat(context_started_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PrerequisiteEvidenceError(
            "production_prerequisite_context_time_invalid"
        ) from exc

    expected_roles = (
        (windows, "windows-operational-plane", "windowsOperationalPlane"),
        (database, "database", "database"),
        (linux, "linux-vision-worker", "linuxVisionWorker"),
    )
    for observation, role, policy_key in expected_roles:
        try:
            captured = datetime.fromisoformat(
                str(observation.get("capturedAtUtc", "")).replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise PrerequisiteEvidenceError(
                "production_prerequisite_observation_time_invalid:" + role
            ) from exc
        if (
            observation.get("acceptanceExecutionId") != acceptance_execution_id
            or observation.get("acceptanceContextSha256") != acceptance_context_sha256
            or captured < context_start
        ):
            raise PrerequisiteEvidenceError(
                "production_prerequisite_context_mismatch:" + role
            )
        if observation.get("role") != role:
            raise PrerequisiteEvidenceError(
                "production_prerequisite_role_mismatch:" + role
            )
        expected = policy.get(policy_key)
        observed = observation.get("values")
        topology_identity = observation.get("topologyIdentity")
        if (
            not isinstance(expected, dict)
            or not isinstance(observed, dict)
            or not isinstance(topology_identity, str)
            or not topology_identity
            or any(
                not isinstance(value, str) or not value
                for value in expected.values()
            )
        ):
            raise PrerequisiteEvidenceError(
                "production_prerequisite_policy_not_frozen:" + role
            )
        if observed != expected:
            raise PrerequisiteEvidenceError(
                "production_prerequisite_observation_mismatch:" + role
            )


def assemble(args: argparse.Namespace) -> dict[str, Any]:
    context, context_sha = load_acceptance_context(
        args.acceptance_context,
        schema_path=PHASE1_ROOT / "production-acceptance-context.schema.json",
        expected_source_commit=args.source_commit,
        expected_mavi_build=args.mavi_build,
    )
    canonical, policy_sha = canonical_production_prerequisites(args.policy)
    policy = load_json(canonical, "production_prerequisite_policy_invalid")
    validate_schema(
        policy,
        "production-prerequisite-policy.schema.json",
        "production_prerequisite_policy",
    )

    windows = load_json(
        args.windows_observation,
        "production_prerequisite_windows_invalid",
    )
    database = load_json(
        args.database_observation,
        "production_prerequisite_database_invalid",
    )
    linux = load_json(
        args.linux_observation,
        "production_prerequisite_linux_invalid",
    )
    for value in (windows, database, linux):
        validate_schema(
            value,
            "production-prerequisite-observation.schema.json",
            "production_prerequisite_observation",
        )

    validate_observations(
        policy,
        windows,
        database,
        linux,
        acceptance_execution_id=context["acceptanceExecutionId"],
        acceptance_context_sha256=context_sha,
        context_started_at=context["startedAtUtc"],
    )

    return {
        "schemaVersion": "mavi-production-prerequisite-evidence-v1",
        "acceptanceExecutionId": context["acceptanceExecutionId"],
        "acceptanceContextSha256": context_sha,
        "sourceCommit": args.source_commit,
        "maviBuild": args.mavi_build,
        "policySha256": policy_sha,
        "windowsObservationSha256": sha256_file(args.windows_observation),
        "databaseObservationSha256": sha256_file(args.database_observation),
        "linuxObservationSha256": sha256_file(args.linux_observation),
        "topologyIdentities": {
            "windowsOperationalPlane": windows["topologyIdentity"],
            "database": database["topologyIdentity"],
            "linuxVisionWorker": linux["topologyIdentity"],
        },
        "windowsOperationalPlane": windows["values"],
        "database": database["values"],
        "linuxVisionWorker": linux["values"],
        "result": {"passed": True, "failureCodes": []},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--acceptance-context", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--mavi-build", required=True)
    parser.add_argument("--windows-observation", type=Path, required=True)
    parser.add_argument("--database-observation", type=Path, required=True)
    parser.add_argument("--linux-observation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.output.exists():
            raise PrerequisiteEvidenceError(
                "production_prerequisite_evidence_exists"
            )
        if (
            len(args.source_commit) not in {40, 64}
            or any(
                ch not in "0123456789abcdef"
                for ch in args.source_commit
            )
            or not args.mavi_build
            or args.mavi_build == "unknown-development"
        ):
            raise PrerequisiteEvidenceError(
                "production_prerequisite_release_identity_invalid"
            )

        value = assemble(args)
        validate_schema(
            value,
            "production-prerequisite-evidence.schema.json",
            "production_prerequisite_evidence",
        )
        args.output.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (
        OSError,
        json.JSONDecodeError,
        PolicyIdentityError,
        PrerequisiteEvidenceError,
        AcceptanceContextError,
    ) as exc:
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
