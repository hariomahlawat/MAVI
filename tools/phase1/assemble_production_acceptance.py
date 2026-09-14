#!/usr/bin/env python3
"""Assemble and verify final Task-17 production acceptance evidence.

This is intentionally post-promotion. Candidate evidence can qualify the release
for promotion, but cannot satisfy this final production-acceptance contract.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
PHASE1_ROOT = Path(__file__).resolve().parent
if str(PHASE1_ROOT) not in sys.path:
    sys.path.insert(0, str(PHASE1_ROOT))

import verify_phase1_evidence as evidence_verifier  # noqa: E402
from policy_identity import (  # noqa: E402
    CANONICAL_SUPPORTED_UPDATES,
    PolicyIdentityError,
    canonical_acceptance_profile,
    sha256_file as policy_sha256_file,
)

APP_MANIFEST_TOOL = PHASE1_ROOT / "build_application_artifact_manifest.py"
SPEC = importlib.util.spec_from_file_location("mavi_app_manifest_prod", APP_MANIFEST_TOOL)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("application_manifest_import_failed")
app_manifest_tool = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = app_manifest_tool
SPEC.loader.exec_module(app_manifest_tool)

VARIANTS = (
    "windows-x86_64-cpu",
    "windows-x86_64-cuda",
    "linux-x86_64-cpu",
    "linux-x86_64-cuda",
)


class ProductionAcceptanceError(ValueError):
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
        raise ProductionAcceptanceError(code) from exc
    if not isinstance(value, dict):
        raise ProductionAcceptanceError(code)
    return value


def validate_schema(value: dict[str, Any], schema_name: str, code: str) -> None:
    schema = load_json(PHASE1_ROOT / schema_name, code + "_schema_unavailable")
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        raise ProductionAcceptanceError(code + "_schema_invalid")


def passed_result(value: dict[str, Any]) -> bool:
    result = value.get("result")
    return (
        result == "passed"
        or (
            isinstance(result, dict)
            and result.get("passed") is True
            and not result.get("failureCodes")
        )
    )


def validate_lifecycle(
    path: Path,
    *,
    mode: str,
    source_commit: str,
    mavi_build: str,
    application_manifest_sha256: str,
    supported_updates_policy_sha256: str,
) -> str:
    value = load_json(path, "production_lifecycle_invalid")
    validate_schema(
        value,
        "application-lifecycle-evidence.schema.json",
        "production_lifecycle",
    )
    if (
        value.get("mode") != mode
        or value.get("sourceCommit") != source_commit
        or value.get("build") != mavi_build
        or value.get("applicationManifestSha256") != application_manifest_sha256
        or value.get("supportedUpdatesPolicySha256") != supported_updates_policy_sha256
        or value.get("internetUnavailable") is not True
        or value.get("observedHealth", {}).get("commit") != source_commit
        or value.get("observedHealth", {}).get("build") != mavi_build
        or value.get("uiSmoke", {}).get("passed") is not True
        or not passed_result(value)
    ):
        raise ProductionAcceptanceError("production_lifecycle_binding_failed")
    if mode == "fresh-install":
        if value.get("priorRelease") is not None or value.get("retainedState") is not None:
            raise ProductionAcceptanceError("production_fresh_install_invalid")
    else:
        prior = value.get("priorRelease")
        retained = value.get("retainedState")
        if (
            not isinstance(prior, dict)
            or prior.get("supported") is not True
            or not isinstance(retained, dict)
        ):
            raise ProductionAcceptanceError("production_offline_update_invalid")
    return sha256_file(path)


def validate_variant(
    path: Path,
    *,
    variant: str,
    source_commit: str,
    target_manifest_sha256: str,
    acceptance_profile_sha256: str,
    mavi_build: str,
) -> tuple[str, str, str]:
    value = load_json(path, "production_variant_invalid")
    validate_schema(
        value,
        "offline-variant-evidence.schema.json",
        "production_variant",
    )
    if (
        value.get("variant") != variant
        or value.get("sourceCommit") != source_commit
        or value.get("targetVerifiedManifestSha256") != target_manifest_sha256
        or value.get("acceptanceProfileSha256") != acceptance_profile_sha256
        or value.get("maviBuild") != mavi_build
        or value.get("bundleMode") != "production"
        or value.get("expectedHostCompatibility") != value.get("observedHostCompatibility")
        or value.get("installExitCode") != 0
        or value.get("pipCheckPassed") is not True
        or value.get("runtimeStarted") is not True
        or value.get("realInferencePassed") is not True
        or value.get("workerFlowPassed") is not True
        or value.get("outboundNetworkUnavailable") is not True
        or value.get("firstRunDownloadObserved") is not False
        or value.get("result") != "passed"
    ):
        raise ProductionAcceptanceError("production_variant_binding_failed:" + variant)
    device = value.get("actualDevice")
    if variant.endswith("-cpu") and device != "cpu":
        raise ProductionAcceptanceError("production_variant_device_mismatch:" + variant)
    if variant.endswith("-cuda") and not (
        isinstance(device, str) and device.startswith("cuda:")
    ):
        raise ProductionAcceptanceError("production_variant_device_mismatch:" + variant)
    return (
        sha256_file(path),
        value["bundleManifestSha256"],
        value["releaseLockSha256"],
    )


def validate_final_e2e(
    path: Path,
    *,
    source_commit: str,
    target_manifest_sha256: str,
    acceptance_profile_sha256: str,
    expected_corpus_sha256: str,
    mavi_build: str,
    linux_cuda_bundle_sha256: str,
    linux_cuda_lock_sha256: str,
) -> str:
    value = load_json(path, "production_e2e_invalid")
    validate_schema(
        value,
        "phase1-acceptance-evidence.schema.json",
        "production_e2e",
    )
    try:
        evidence_verifier.verify_acceptance(
            value,
            expected_source_commit=source_commit,
            expected_acceptance_profile_sha256=acceptance_profile_sha256,
            expected_qualification_corpus_sha256=expected_corpus_sha256,
        )
    except evidence_verifier.EvidenceError as exc:
        raise ProductionAcceptanceError("production_e2e_invalid:" + exc.code) from exc

    attestation = value.get("attestation", {})
    release_expected = value.get("releaseExpected", {})
    if (
        value.get("mode") != "formal"
        or value.get("targetVerifiedManifestSha256") != target_manifest_sha256
        or release_expected.get("modelManifestSha256") != target_manifest_sha256
        or attestation.get("verificationStatus") != "verified"
        or attestation.get("runtimeVariant") != "linux-x86_64-cuda"
        or attestation.get("maviBuild") != mavi_build
        or attestation.get("maviCommit") != source_commit
        or attestation.get("productionBundleManifestSha256") != linux_cuda_bundle_sha256
        or attestation.get("platformLockSha256") != linux_cuda_lock_sha256
        or attestation.get("candidateBundleManifestSha256") is not None
        or attestation.get("candidateSelectedLockSha256") is not None
    ):
        raise ProductionAcceptanceError("production_e2e_binding_failed")
    actual_device = attestation.get("actualDevice")
    if not isinstance(actual_device, str) or not actual_device.startswith("cuda:"):
        raise ProductionAcceptanceError("production_e2e_cuda_required")
    return sha256_file(path)


def validate_backup(
    path: Path,
    *,
    source_commit: str,
    acceptance_profile_sha256: str,
    final_e2e_sha256: str,
) -> str:
    value = load_json(path, "production_backup_restore_invalid")
    validate_schema(
        value,
        "backup-restore-evidence.schema.json",
        "production_backup_restore",
    )
    if (
        value.get("sourceCommit") != source_commit
        or value.get("acceptanceProfileSha256") != acceptance_profile_sha256
        or value.get("acceptanceEvidenceSha256") != final_e2e_sha256
        or value.get("cleanRestoreTarget") is not True
        or value.get("sourceDatabaseIdentity") == value.get("restoreDatabaseIdentity")
        or not passed_result(value)
    ):
        raise ProductionAcceptanceError("production_backup_restore_binding_failed")
    return sha256_file(path)


def parse_variant_arguments(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for item in values:
        if "=" not in item:
            raise ProductionAcceptanceError("production_variant_argument_invalid")
        variant, raw = item.split("=", 1)
        if variant not in VARIANTS or variant in result or not raw:
            raise ProductionAcceptanceError("production_variant_argument_invalid")
        result[variant] = Path(raw)
    if set(result) != set(VARIANTS):
        raise ProductionAcceptanceError("production_variant_set_incomplete")
    return result


def assemble(args: argparse.Namespace) -> dict[str, Any]:
    canonical_profile, profile_sha = canonical_acceptance_profile(args.acceptance_profile)
    profile = load_json(canonical_profile, "production_acceptance_profile_invalid")
    corpus_sha = profile.get("qualificationCorpusManifestSha256")
    if (
        profile.get("mode") != "qualification"
        or not isinstance(corpus_sha, str)
        or len(corpus_sha) != 64
    ):
        raise ProductionAcceptanceError("production_acceptance_profile_not_frozen")

    verified_manifest = load_json(
        args.verified_model_manifest,
        "production_verified_manifest_invalid",
    )
    target_manifest_sha = sha256_file(args.verified_model_manifest)
    if (
        verified_manifest.get("verificationStatus") != "verified"
        or not verified_manifest.get("qualificationId")
    ):
        raise ProductionAcceptanceError("production_verified_manifest_not_promoted")

    application_manifest = load_json(
        args.application_manifest,
        "production_application_manifest_invalid",
    )
    try:
        app_manifest_tool.verify_manifest(
            args.application_artifact_root,
            application_manifest,
        )
    except app_manifest_tool.ApplicationArtifactError as exc:
        raise ProductionAcceptanceError(
            "production_application_artifact_invalid"
        ) from exc
    source_commit = application_manifest.get("sourceCommit")
    mavi_build = application_manifest.get("build")
    if (
        source_commit != args.source_commit
        or not isinstance(mavi_build, str)
        or not mavi_build
        or mavi_build == "unknown-development"
    ):
        raise ProductionAcceptanceError("production_application_identity_mismatch")
    application_manifest_sha = sha256_file(args.application_manifest)

    supported_policy_sha = policy_sha256_file(CANONICAL_SUPPORTED_UPDATES)
    fresh_sha = validate_lifecycle(
        args.fresh_install,
        mode="fresh-install",
        source_commit=args.source_commit,
        mavi_build=mavi_build,
        application_manifest_sha256=application_manifest_sha,
        supported_updates_policy_sha256=supported_policy_sha,
    )
    update_sha = validate_lifecycle(
        args.offline_update,
        mode="offline-update",
        source_commit=args.source_commit,
        mavi_build=mavi_build,
        application_manifest_sha256=application_manifest_sha,
        supported_updates_policy_sha256=supported_policy_sha,
    )

    variant_paths = parse_variant_arguments(args.production_variant)
    variant_evidence: dict[str, str] = {}
    bundle_hashes: dict[str, str] = {}
    lock_hashes: dict[str, str] = {}
    for variant in VARIANTS:
        evidence_sha, bundle_sha, lock_sha = validate_variant(
            variant_paths[variant],
            variant=variant,
            source_commit=args.source_commit,
            target_manifest_sha256=target_manifest_sha,
            acceptance_profile_sha256=profile_sha,
            mavi_build=mavi_build,
        )
        variant_evidence[variant] = evidence_sha
        bundle_hashes[variant] = bundle_sha
        lock_hashes[variant] = lock_sha

    final_e2e_sha = validate_final_e2e(
        args.final_e2e,
        source_commit=args.source_commit,
        target_manifest_sha256=target_manifest_sha,
        acceptance_profile_sha256=profile_sha,
        expected_corpus_sha256=corpus_sha,
        mavi_build=mavi_build,
        linux_cuda_bundle_sha256=bundle_hashes["linux-x86_64-cuda"],
        linux_cuda_lock_sha256=lock_hashes["linux-x86_64-cuda"],
    )
    backup_sha = validate_backup(
        args.backup_restore,
        source_commit=args.source_commit,
        acceptance_profile_sha256=profile_sha,
        final_e2e_sha256=final_e2e_sha,
    )

    return {
        "schemaVersion": "mavi-phase1-production-acceptance-evidence-v1",
        "sourceCommit": args.source_commit,
        "maviBuild": mavi_build,
        "verifiedModelManifestSha256": target_manifest_sha,
        "acceptanceProfileSha256": profile_sha,
        "applicationManifestSha256": application_manifest_sha,
        "freshInstallEvidenceSha256": fresh_sha,
        "offlineUpdateEvidenceSha256": update_sha,
        "backupRestoreEvidenceSha256": backup_sha,
        "productionVariantEvidenceSha256": variant_evidence,
        "productionBundleManifestSha256": bundle_hashes,
        "productionReleaseLockSha256": lock_hashes,
        "finalE2eEvidenceSha256": final_e2e_sha,
        "result": {"passed": True, "failureCodes": []},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--verified-model-manifest", type=Path, required=True)
    parser.add_argument("--acceptance-profile", type=Path, required=True)
    parser.add_argument("--application-artifact-root", type=Path, required=True)
    parser.add_argument("--application-manifest", type=Path, required=True)
    parser.add_argument("--fresh-install", type=Path, required=True)
    parser.add_argument("--offline-update", type=Path, required=True)
    parser.add_argument("--backup-restore", type=Path, required=True)
    parser.add_argument("--production-variant", action="append", default=[])
    parser.add_argument("--final-e2e", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.output.exists():
            raise ProductionAcceptanceError("production_acceptance_output_exists")
        value = assemble(args)
        validate_schema(
            value,
            "production-acceptance-evidence.schema.json",
            "production_acceptance",
        )
        args.output.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (
        ProductionAcceptanceError,
        PolicyIdentityError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        print(json.dumps({"ok": False, "code": str(exc)}, sort_keys=True))
        return 2

    print(json.dumps({"ok": True, "sha256": sha256_file(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
