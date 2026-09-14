#!/usr/bin/env python3
"""Assess Task-17 closure without converting missing evidence into success."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
PHASE1_ROOT = Path(__file__).resolve().parent
VISION_ROOT = ROOT / "src" / "vision"
for candidate in (PHASE1_ROOT, VISION_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from mavi_vision.runtime.manifest import ReleaseMetadataError  # noqa: E402
from mavi_vision.runtime.qualification import (  # noqa: E402
    MANDATORY_QUALIFICATION_GATES,
    load_qualification_record,
    load_runtime_profile,
    verify_release_selection,
)

import verify_phase1_evidence as evidence_verifier  # noqa: E402


class ClosureError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClosureError("closure_json_invalid:" + path.name) from exc
    if not isinstance(value, dict):
        raise ClosureError("closure_json_invalid:" + path.name)
    return value


def validate_schema(value: dict[str, Any], schema_path: Path) -> None:
    schema = load_json(schema_path)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        raise ClosureError(
            "closure_schema_invalid:"
            + schema_path.name
            + ":"
            + "/".join(str(x) for x in errors[0].absolute_path)
        )


def require_source_commit(value: dict[str, Any], source_commit: str, code: str) -> None:
    if value.get("sourceCommit") != source_commit:
        raise ClosureError(code + "_source_commit_mismatch")


def _passed_result(value: dict[str, Any]) -> bool:
    result = value.get("result")
    return (
        result == "passed"
        or (
            isinstance(result, dict)
            and result.get("passed") is True
            and not result.get("failureCodes")
        )
    )


def validate_application_lifecycle(
    path: Path,
    *,
    expected_mode: str,
    source_commit: str,
    schema_path: Path,
) -> dict[str, Any]:
    value = load_json(path)
    validate_schema(value, schema_path)
    require_source_commit(value, source_commit, "application_lifecycle")
    if value.get("mode") != expected_mode:
        raise ClosureError("application_lifecycle_mode_mismatch")
    if value.get("internetUnavailable") is not True:
        raise ClosureError("application_lifecycle_not_offline")
    if value.get("observedHealth", {}).get("commit") != source_commit:
        raise ClosureError("application_lifecycle_health_mismatch")
    if value.get("uiSmoke", {}).get("passed") is not True:
        raise ClosureError("application_lifecycle_ui_smoke_missing")
    if expected_mode == "fresh-install":
        if value.get("priorRelease") is not None:
            raise ClosureError("fresh_install_prior_release_unexpected")
        if value.get("retainedState") is not None:
            raise ClosureError("fresh_install_retained_state_unexpected")
    if expected_mode == "offline-update":
        prior = value.get("priorRelease")
        if (
            not isinstance(prior, dict)
            or prior.get("supported") is not True
            or not isinstance(prior.get("applicationManifestSha256"), str)
        ):
            raise ClosureError("offline_update_supported_prior_missing")
        retained = value.get("retainedState")
        if not isinstance(retained, dict):
            raise ClosureError("offline_update_retained_state_missing")
    if not _passed_result(value):
        raise ClosureError("application_lifecycle_not_passed")
    return value


def validate_backup_restore(
    path: Path,
    *,
    source_commit: str,
    schema_path: Path,
) -> dict[str, Any]:
    value = load_json(path)
    validate_schema(value, schema_path)
    require_source_commit(value, source_commit, "backup_restore")
    if value.get("cleanRestoreTarget") is not True or not _passed_result(value):
        raise ClosureError("backup_restore_not_passed")
    if value.get("sourceDatabaseIdentity") == value.get("restoreDatabaseIdentity"):
        raise ClosureError("backup_restore_database_targets_not_distinct")
    return value


def validate_quality(
    path: Path,
    source_commit: str,
    acceptance_profile_sha256: str,
) -> dict[str, Any]:
    value = load_json(path)
    validate_schema(value, Path(__file__).with_name("phase1-acceptance-evidence.schema.json"))
    require_source_commit(value, source_commit, "quality")
    evidence_verifier.verify_acceptance(
        value,
        expected_source_commit=source_commit,
        expected_acceptance_profile_sha256=acceptance_profile_sha256,
    )
    if value.get("mode") != "formal":
        raise ClosureError("quality_formal_mode_required")
    metrics = value.get("metrics")
    if (
        not isinstance(metrics, dict)
        or metrics.get("mode") != "qualification"
        or metrics.get("qualification", {}).get("passed") is not True
    ):
        raise ClosureError("quality_qualification_not_passed")
    per_class = metrics.get("perClass")
    if not isinstance(per_class, dict):
        raise ClosureError("quality_per_class_missing")
    for object_class in ("Person", "Vehicle"):
        row = per_class.get(object_class)
        if not isinstance(row, dict) or row.get("groundTruthEventCount", 0) <= 0:
            raise ClosureError("quality_class_coverage_missing:" + object_class)
    return value


def validate_performance(
    path: Path,
    source_commit: str,
    acceptance_profile_sha256: str,
) -> dict[str, Any]:
    value = load_json(path)
    validate_schema(value, Path(__file__).with_name("recovery-performance-evidence.schema.json"))
    require_source_commit(value, source_commit, "performance")
    if value.get("acceptanceProfileSha256") != acceptance_profile_sha256:
        raise ClosureError("performance_profile_hash_mismatch")
    if value.get("schemaVersion") != "mavi-linux-nvidia-recovery-performance-evidence-v1":
        raise ClosureError("performance_schema_invalid")
    if value.get("runtimeVariant") != "linux-x86_64-cuda":
        raise ClosureError("performance_runtime_variant_invalid")
    if not _passed_result(value):
        raise ClosureError("performance_not_passed")
    return value


def assess(args: argparse.Namespace) -> dict[str, Any]:
    runtime = load_runtime_profile(args.runtime_profile)
    qualification = load_qualification_record(args.qualification)
    acceptance_profile_sha256 = sha256_file(args.acceptance_profile)

    pending: list[str] = []
    evidence_hashes: dict[str, str] = {}

    for variant, identity in runtime.platform_variants.items():
        expected = "qualified-hardware" if variant.endswith("-cuda") else "qualified-hosted-cpu"
        if identity.status != expected:
            pending.append("runtime:" + variant)
    for variant, identity in runtime.release_locks.items():
        if identity.status != "qualified-offline-lock":
            pending.append("runtime-lock:" + variant)

    if runtime.qualification_status != "qualified":
        pending.append("runtime:qualificationStatus")

    for gate in sorted(MANDATORY_QUALIFICATION_GATES):
        if qualification.required_gates.get(gate) != "passed":
            pending.append("qualification:" + gate)
        elif gate not in qualification.evidence:
            pending.append("qualification-evidence:" + gate)

    optional_inputs = {
        "fresh-install": args.fresh_install,
        "offline-update": args.offline_update,
        "backup-restore": args.backup_restore,
        "windows-offline-install": args.windows_offline,
        "linux-offline-install": args.linux_offline,
        "cctv-quality-baseline": args.quality,
        "linux-nvidia-recovery-performance": args.performance,
    }
    for name, path in optional_inputs.items():
        if path is None:
            pending.append("acceptance:" + name)

    if args.fresh_install is not None:
        validate_application_lifecycle(
            args.fresh_install,
            expected_mode="fresh-install",
            source_commit=args.source_commit,
            schema_path=args.application_lifecycle_schema,
        )
        evidence_hashes["fresh-install"] = sha256_file(args.fresh_install)
    if args.offline_update is not None:
        validate_application_lifecycle(
            args.offline_update,
            expected_mode="offline-update",
            source_commit=args.source_commit,
            schema_path=args.application_lifecycle_schema,
        )
        evidence_hashes["offline-update"] = sha256_file(args.offline_update)
    if args.backup_restore is not None:
        validate_backup_restore(
            args.backup_restore,
            source_commit=args.source_commit,
            schema_path=args.backup_restore_schema,
        )
        evidence_hashes["backup-restore"] = sha256_file(args.backup_restore)
    if args.windows_offline is not None:
        value = load_json(args.windows_offline)
        validate_schema(value, Path(__file__).with_name("offline-install-evidence.schema.json"))
        evidence_verifier.verify_offline_install(
            value,
            expected_source_commit=args.source_commit,
            expected_acceptance_profile_sha256=acceptance_profile_sha256,
        )
        if value.get("os") != "windows":
            raise ClosureError("windows_offline_os_mismatch")
        evidence_hashes["windows-offline-install"] = sha256_file(args.windows_offline)
    if args.linux_offline is not None:
        value = load_json(args.linux_offline)
        validate_schema(value, Path(__file__).with_name("offline-install-evidence.schema.json"))
        evidence_verifier.verify_offline_install(
            value,
            expected_source_commit=args.source_commit,
            expected_acceptance_profile_sha256=acceptance_profile_sha256,
        )
        if value.get("os") != "linux":
            raise ClosureError("linux_offline_os_mismatch")
        evidence_hashes["linux-offline-install"] = sha256_file(args.linux_offline)
    if args.quality is not None:
        validate_quality(args.quality, args.source_commit, acceptance_profile_sha256)
        evidence_hashes["cctv-quality-baseline"] = sha256_file(args.quality)
    if args.performance is not None:
        validate_performance(args.performance, args.source_commit, acceptance_profile_sha256)
        evidence_hashes["linux-nvidia-recovery-performance"] = sha256_file(args.performance)

    # Only a fully promoted release may be called verified.
    promoted = False
    try:
        selection = verify_release_selection(
            model_root=args.model_root,
            manifest_path=args.manifest,
            profile_path=args.pipeline_profile,
            runtime_profile_path=args.runtime_profile,
            qualification_path=args.qualification,
            allow_unverified=False,
        )
        promoted = (
            selection.verification_status == "verified"
            and selection.runtime_qualification_status == "qualified"
        )
    except ReleaseMetadataError:
        promoted = False

    if not promoted:
        pending.append("release:promotion")

    pending = sorted(set(pending))
    state = "release-verified" if not pending else "implementation-complete-evidence-pending"
    return {
        "schemaVersion": "mavi-phase1-closure-status-v1",
        "sourceCommit": args.source_commit,
        "state": state,
        "pending": pending,
        "evidenceSha256": dict(sorted(evidence_hashes.items())),
        "releaseMetadata": {
            "manifestSha256": sha256_file(args.manifest),
            "qualificationSha256": sha256_file(args.qualification),
            "runtimeProfileSha256": sha256_file(args.runtime_profile),
            "pipelineProfileSha256": sha256_file(args.pipeline_profile),
            "acceptanceProfileSha256": acceptance_profile_sha256,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--pipeline-profile", type=Path, required=True)
    parser.add_argument("--runtime-profile", type=Path, required=True)
    parser.add_argument("--acceptance-profile", type=Path, required=True)
    parser.add_argument("--fresh-install", type=Path)
    parser.add_argument("--offline-update", type=Path)
    parser.add_argument("--backup-restore", type=Path)
    parser.add_argument("--windows-offline", type=Path)
    parser.add_argument("--linux-offline", type=Path)
    parser.add_argument("--quality", type=Path)
    parser.add_argument("--performance", type=Path)
    parser.add_argument("--application-lifecycle-schema", type=Path, default=Path(__file__).with_name("application-lifecycle-evidence.schema.json"))
    parser.add_argument("--backup-restore-schema", type=Path, default=Path(__file__).with_name("backup-restore-evidence.schema.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-complete", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.output.exists():
            raise ClosureError("closure_output_exists")
        value = assess(args)
        args.output.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (ClosureError, OSError, json.JSONDecodeError, ReleaseMetadataError, evidence_verifier.EvidenceError) as exc:
        code = getattr(exc, "code", str(exc))
        print(json.dumps({"ok": False, "code": code}, sort_keys=True))
        return 2

    print(json.dumps({"ok": True, "state": value["state"], "pending": value["pending"]}, sort_keys=True))
    if args.require_complete and value["state"] != "release-verified":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
