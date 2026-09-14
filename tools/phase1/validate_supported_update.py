#!/usr/bin/env python3
"""Validate that an offline-update source is an exact supported prior MAVI artifact."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

PHASE1_ROOT = Path(__file__).resolve().parent
if str(PHASE1_ROOT) not in sys.path:
    sys.path.insert(0, str(PHASE1_ROOT))

MANIFEST_TOOL = Path(__file__).with_name("build_application_artifact_manifest.py")
SPEC = importlib.util.spec_from_file_location("mavi_app_manifest", MANIFEST_TOOL)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("application_manifest_import_failed")
app_manifest = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = app_manifest
SPEC.loader.exec_module(app_manifest)

from policy_identity import PolicyIdentityError, canonical_supported_updates  # noqa: E402


class SupportedUpdateError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate(policy_path: Path, prior_manifest_path: Path, prior_root: Path) -> dict:
    canonical_policy, policy_sha = canonical_supported_updates(policy_path)
    try:
        policy = json.loads(canonical_policy.read_text(encoding="utf-8"))
        prior = json.loads(prior_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SupportedUpdateError("supported_update_json_invalid") from exc
    if not isinstance(policy, dict) or policy.get("schemaVersion") != "mavi-phase1-supported-updates-v1":
        raise SupportedUpdateError("supported_updates_policy_invalid")
    if not isinstance(prior, dict) or prior.get("schemaVersion") != "mavi-application-artifact-v1":
        raise SupportedUpdateError("update_prior_manifest_invalid")

    releases = policy.get("priorReleases")
    if not isinstance(releases, list):
        raise SupportedUpdateError("supported_updates_policy_invalid")
    matches = [
        item for item in releases
        if isinstance(item, dict) and item.get("sourceCommit") == prior.get("sourceCommit")
    ]
    if len(matches) != 1:
        raise SupportedUpdateError("update_prior_release_not_supported")
    selected = matches[0]
    expected_sha = selected.get("applicationManifestSha256")
    if (
        not isinstance(expected_sha, str)
        or len(expected_sha) != 64
        or any(ch not in "0123456789abcdef" for ch in expected_sha)
    ):
        raise SupportedUpdateError("update_prior_release_identity_not_frozen")
    actual_sha = sha256_file(prior_manifest_path)
    if actual_sha != expected_sha:
        raise SupportedUpdateError("update_prior_release_manifest_mismatch")

    migration_policy = selected.get("migrationPolicy")
    if migration_policy not in {"none", "required"}:
        raise SupportedUpdateError("update_migration_policy_invalid")

    try:
        app_manifest.verify_manifest(prior_root, prior)
    except app_manifest.ApplicationArtifactError as exc:
        raise SupportedUpdateError("update_prior_release_integrity_failed") from exc

    return {
        "sourceCommit": prior["sourceCommit"],
        "build": prior["build"],
        "applicationManifestSha256": actual_sha,
        "migrationPolicy": migration_policy,
        "supportedUpdatesPolicySha256": policy_sha,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--prior-manifest", type=Path, required=True)
    parser.add_argument("--prior-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        value = validate(args.policy, args.prior_manifest, args.prior_root)
    except (SupportedUpdateError, OSError, KeyError, PolicyIdentityError) as exc:
        print(json.dumps({"ok": False, "code": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, **value}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
