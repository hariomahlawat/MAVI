#!/usr/bin/env python3
"""Validate observed production prerequisites for one declared deployment profile."""

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

import deployment_profiles  # noqa: E402
from production_acceptance_context import (  # noqa: E402
    AcceptanceContextError,
    load_context as load_acceptance_context,
)
from policy_identity import (  # noqa: E402
    PolicyIdentityError,
    canonical_production_prerequisites,
)


class PrerequisiteEvidenceError(ValueError):
    pass


ROLE_POLICY_KEYS = {
    "windows-operational-plane": "windowsOperationalPlane",
    "database": "database",
    "windows-cuda-vision-worker": "windowsCudaVisionWorker",
    "windows-cpu-vision-worker": "windowsCpuVisionWorker",
    "linux-vision-worker": "linuxVisionWorker",
}


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


def validate_schema(value: dict[str, Any], schema_name: str, code: str) -> None:
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


def parse_observation_arguments(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for item in values:
        if "=" not in item:
            raise PrerequisiteEvidenceError(
                "production_prerequisite_observation_argument_invalid"
            )
        role, raw_path = item.split("=", 1)
        if (
            role not in ROLE_POLICY_KEYS
            or role in result
            or not raw_path
        ):
            raise PrerequisiteEvidenceError(
                "production_prerequisite_observation_argument_invalid"
            )
        result[role] = Path(raw_path)
    return result


def validate_observations(
    policy: dict[str, Any],
    observations: dict[str, dict[str, Any]],
    required_roles: tuple[str, ...],
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
        context_start = datetime.fromisoformat(
            context_started_at.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise PrerequisiteEvidenceError(
            "production_prerequisite_context_time_invalid"
        ) from exc

    if set(observations) != set(required_roles):
        raise PrerequisiteEvidenceError(
            "production_prerequisite_observation_set_mismatch"
        )

    for role in required_roles:
        observation = observations[role]
        try:
            captured = datetime.fromisoformat(
                str(observation.get("capturedAtUtc", "")).replace(
                    "Z", "+00:00"
                )
            )
        except ValueError as exc:
            raise PrerequisiteEvidenceError(
                "production_prerequisite_observation_time_invalid:" + role
            ) from exc

        if (
            observation.get("acceptanceExecutionId")
            != acceptance_execution_id
            or observation.get("acceptanceContextSha256")
            != acceptance_context_sha256
            or captured < context_start
        ):
            raise PrerequisiteEvidenceError(
                "production_prerequisite_context_mismatch:" + role
            )
        if observation.get("role") != role:
            raise PrerequisiteEvidenceError(
                "production_prerequisite_role_mismatch:" + role
            )

        policy_key = ROLE_POLICY_KEYS[role]
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
    selected_profile, deployment_policy_sha = deployment_profiles.select_profile(
        args.deployment_profile,
        args.deployment_profile_policy,
    )

    canonical, policy_sha = canonical_production_prerequisites(args.policy)
    policy = load_json(canonical, "production_prerequisite_policy_invalid")
    validate_schema(
        policy,
        "production-prerequisite-policy.schema.json",
        "production_prerequisite_policy",
    )

    paths = parse_observation_arguments(args.observation)
    required_roles = selected_profile.required_prerequisite_roles
    if set(paths) != set(required_roles):
        raise PrerequisiteEvidenceError(
            "production_prerequisite_observation_set_mismatch"
        )

    observations: dict[str, dict[str, Any]] = {}
    for role in required_roles:
        value = load_json(
            paths[role],
            "production_prerequisite_observation_invalid:" + role,
        )
        validate_schema(
            value,
            "production-prerequisite-observation.schema.json",
            "production_prerequisite_observation",
        )
        observations[role] = value

    validate_observations(
        policy,
        observations,
        required_roles,
        acceptance_execution_id=context["acceptanceExecutionId"],
        acceptance_context_sha256=context_sha,
        context_started_at=context["startedAtUtc"],
    )

    return {
        "schemaVersion": "mavi-production-prerequisite-evidence-v2",
        "acceptanceExecutionId": context["acceptanceExecutionId"],
        "acceptanceContextSha256": context_sha,
        "sourceCommit": args.source_commit,
        "maviBuild": args.mavi_build,
        "deploymentProfile": selected_profile.profile_id,
        "deploymentProfilePolicySha256": deployment_policy_sha,
        "policySha256": policy_sha,
        "observationSha256": {
            role: sha256_file(paths[role])
            for role in sorted(required_roles)
        },
        "topologyIdentities": {
            role: observations[role]["topologyIdentity"]
            for role in sorted(required_roles)
        },
        "values": {
            role: observations[role]["values"]
            for role in sorted(required_roles)
        },
        "result": {"passed": True, "failureCodes": []},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument(
        "--deployment-profile-policy",
        type=Path,
        default=deployment_profiles.CANONICAL_DEPLOYMENT_PROFILES,
    )
    parser.add_argument(
        "--deployment-profile",
        choices=("P1", "P2", "P3"),
        required=True,
    )
    parser.add_argument("--acceptance-context", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--mavi-build", required=True)
    parser.add_argument(
        "--observation",
        action="append",
        default=[],
        help="ROLE=PATH; provide exactly the roles required by the selected profile",
    )
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
        PrerequisiteEvidenceError,
        PolicyIdentityError,
        AcceptanceContextError,
        deployment_profiles.DeploymentProfileError,
    ) as exc:
        code = getattr(exc, "code", str(exc))
        print(json.dumps({"ok": False, "code": code}, sort_keys=True))
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
