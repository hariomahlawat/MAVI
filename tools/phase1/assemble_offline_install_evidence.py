#!/usr/bin/env python3
"""Assemble profile-scoped offline-install qualification evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PHASE1_ROOT = Path(__file__).resolve().parent
if str(PHASE1_ROOT) not in sys.path:
    sys.path.insert(0, str(PHASE1_ROOT))

import deployment_profiles  # noqa: E402


class AssembleError(ValueError):
    pass


def load(path: Path) -> tuple[dict[str, Any], str]:
    data = path.read_bytes()
    value = json.loads(data)
    if not isinstance(value, dict):
        raise AssembleError("offline_variant_evidence_invalid")
    return value, hashlib.sha256(data).hexdigest()


def assemble(args: argparse.Namespace) -> dict[str, Any]:
    profile, policy_sha = deployment_profiles.select_profile(
        args.deployment_profile,
        args.deployment_profile_policy,
    )
    item, item_sha = load(args.variant)
    expected_variant = profile.runtime_variant
    expected_os = expected_variant.split("-", 1)[0]

    if item.get("schemaVersion") != "mavi-offline-variant-evidence-v1":
        raise AssembleError("offline_variant_schema_invalid")
    if (
        item.get("variant") != expected_variant
        or item.get("result") != "passed"
    ):
        raise AssembleError("offline_variant_not_passed")
    if item.get("bundleMode") is None:
        raise AssembleError("offline_bundle_mode_missing")

    return {
        "schemaVersion": "mavi-offline-install-evidence-v2",
        "sourceCommit": item.get("sourceCommit"),
        "targetVerifiedManifestSha256": item.get(
            "targetVerifiedManifestSha256"
        ),
        "acceptanceProfileSha256": item.get(
            "acceptanceProfileSha256"
        ),
        "maviBuild": item.get("maviBuild"),
        "deploymentProfile": profile.profile_id,
        "deploymentProfilePolicySha256": policy_sha,
        "os": expected_os,
        "bundleMode": item.get("bundleMode"),
        "isolationMethod": args.isolation_method,
        "variantEvidenceSha256": {
            expected_variant: item_sha,
        },
        "variants": [
            {
                "variant": expected_variant,
                "bundleManifestSha256": item["bundleManifestSha256"],
                "releaseLockSha256": item["releaseLockSha256"],
                "expectedHostCompatibility": item[
                    "expectedHostCompatibility"
                ],
                "observedHostCompatibility": item[
                    "observedHostCompatibility"
                ],
                "installCommand": item["installCommand"],
                "installExitCode": item["installExitCode"],
                "pipCheckPassed": item["pipCheckPassed"],
                "runtimeStarted": item["runtimeStarted"],
                "realInferencePassed": item["realInferencePassed"],
                "workerFlowPassed": item["workerFlowPassed"],
                "workerFlowEvidenceSha256": item[
                    "workerFlowEvidenceSha256"
                ],
                "workerPythonSha256": item["workerPythonSha256"],
                "workerEnvironmentSha256": item[
                    "workerEnvironmentSha256"
                ],
                "workerVenvRootSha256": item[
                    "workerVenvRootSha256"
                ],
                "workerResolvedPythonSha256": item[
                    "workerResolvedPythonSha256"
                ],
                "hostIdentitySha256": item["hostIdentitySha256"],
                "workerCommandSha256": item["workerCommandSha256"],
                "workerLogSha256": item["workerLogSha256"],
                "actualDevice": item["actualDevice"],
                "outboundNetworkUnavailable": item[
                    "outboundNetworkUnavailable"
                ],
                "networkIsolation": item["networkIsolation"],
                "firstRunDownloadObserved": item[
                    "firstRunDownloadObserved"
                ],
                "result": item["result"],
            }
        ],
        "result": "passed",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
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
    parser.add_argument("--variant", type=Path, required=True)
    parser.add_argument("--isolation-method", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise AssembleError("offline_output_exists")
        value = assemble(args)
        required = (
            "sourceCommit",
            "targetVerifiedManifestSha256",
            "acceptanceProfileSha256",
            "maviBuild",
        )
        if any(
            not isinstance(value.get(key), str)
            or not value[key]
            for key in required
        ):
            raise AssembleError("offline_variant_identity_incomplete")
        args.output.write_text(
            json.dumps(value, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (
        AssembleError,
        OSError,
        json.JSONDecodeError,
        KeyError,
        deployment_profiles.DeploymentProfileError,
    ) as exc:
        code = getattr(exc, "code", str(exc))
        print(json.dumps({"ok": False, "code": code}, sort_keys=True))
        return 2
    print(json.dumps({"ok": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
