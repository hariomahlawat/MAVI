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
import assemble_production_acceptance as production_acceptance  # noqa: E402
from production_acceptance_context import (  # noqa: E402
    AcceptanceContextError,
    load_context as load_acceptance_context,
)
from policy_identity import (  # noqa: E402
    PolicyIdentityError,
    canonical_acceptance_profile,
    CANONICAL_SUPPORTED_UPDATES,
    sha256_file as policy_sha256_file,
)


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
    supported_updates_policy_sha256: str,
    schema_path: Path,
) -> dict[str, Any]:
    value = load_json(path)
    validate_schema(value, schema_path)
    require_source_commit(value, source_commit, "application_lifecycle")
    if value.get("mode") != expected_mode:
        raise ClosureError("application_lifecycle_mode_mismatch")
    hosting = value.get("hosting")
    if (
        not isinstance(hosting, dict)
        or hosting.get("passed") is not True
        or hosting.get("physicalPath") != value.get("destination")
    ):
        raise ClosureError("application_lifecycle_iis_binding_mismatch")
    if value.get("internetUnavailable") is not True:
        raise ClosureError("application_lifecycle_not_offline")
    if value.get("observedHealth", {}).get("commit") != source_commit:
        raise ClosureError("application_lifecycle_health_mismatch")
    if value.get("supportedUpdatesPolicySha256") != supported_updates_policy_sha256:
        raise ClosureError("application_lifecycle_supported_updates_policy_mismatch")
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
    mavi_build: str | None,
    acceptance_profile_sha256: str,
    schema_path: Path,
) -> dict[str, Any]:
    value = load_json(path)
    validate_schema(value, schema_path)
    require_source_commit(value, source_commit, "backup_restore")
    if value.get("cleanRestoreTarget") is not True or not _passed_result(value):
        raise ClosureError("backup_restore_not_passed")
    if value.get("acceptanceProfileSha256") != acceptance_profile_sha256:
        raise ClosureError("backup_restore_acceptance_profile_mismatch")
    if (
        mavi_build is not None
        and value.get("liveStorageTopology", {}).get("maviBuild") != mavi_build
    ):
        raise ClosureError("backup_restore_mavi_build_mismatch")
    if value.get("sourceDatabaseIdentity") == value.get("restoreDatabaseIdentity"):
        raise ClosureError("backup_restore_database_targets_not_distinct")
    return value


def validate_quality(
    path: Path,
    source_commit: str,
    acceptance_profile_sha256: str,
    expected_corpus_sha256: str | None,
    expected_mavi_build: str | None,
) -> dict[str, Any]:
    value = load_json(path)
    validate_schema(value, Path(__file__).with_name("phase1-acceptance-evidence.schema.json"))
    require_source_commit(value, source_commit, "quality")
    evidence_verifier.verify_acceptance(
        value,
        expected_source_commit=source_commit,
        expected_acceptance_profile_sha256=acceptance_profile_sha256,
        expected_qualification_corpus_sha256=expected_corpus_sha256,
    )
    if value.get("mode") != "formal":
        raise ClosureError("quality_formal_mode_required")
    if expected_mavi_build is not None and value.get("attestation", {}).get("maviBuild") != expected_mavi_build:
        raise ClosureError("quality_mavi_build_mismatch")
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
    acceptance_profile: dict[str, Any],
    expected_mavi_build: str | None,
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
    if expected_mavi_build is not None and value.get("maviBuild") != expected_mavi_build:
        raise ClosureError("performance_mavi_build_mismatch")
    thresholds = acceptance_profile.get("performanceThresholds")
    if not isinstance(thresholds, dict) or value.get("thresholds") != thresholds:
        raise ClosureError("performance_thresholds_mismatch")
    if (
        value.get("processingFps", 0) < thresholds["minimumProcessingFps"]
        or value.get("p95EndToEndLatencyMs", float("inf")) > thresholds["maximumP95LatencyMs"]
        or value.get("memoryGrowthBytes", float("inf")) > thresholds["maximumSoakGrowthBytes"]
    ):
        raise ClosureError("performance_recalculation_failed")
    if not _passed_result(value):
        raise ClosureError("performance_not_passed")
    return value


def validate_production_acceptance_record(
    path: Path,
    *,
    source_commit: str,
    mavi_build: str,
    manifest_sha256: str,
    acceptance_profile_sha256: str,
    application_manifest_sha256: str,
    acceptance_context: Path,
    server_log_checkpoint: Path,
    prerequisite_evidence: Path,
    fresh_install: Path,
    offline_update: Path,
    backup_restore: Path,
    production_variants: dict[str, Path],
    formal_scenario: Path,
    production_e2e: Path,
    empty_scene_scenario: Path,
    empty_scene_e2e: Path,
    failure_reprocess: Path,
    log_inspection: Path,
    variant_bundle_hashes: dict[str, str],
    variant_lock_hashes: dict[str, str],
) -> dict[str, Any]:
    value = load_json(path)
    validate_schema(
        value,
        Path(__file__).with_name("production-acceptance-evidence.schema.json"),
    )
    expected_variant_evidence = {
        variant: sha256_file(production_variants[variant])
        for variant in production_acceptance.VARIANTS
    }
    if (
        value.get("acceptanceContextSha256") != sha256_file(acceptance_context)
        or value.get("serverLogCheckpointSha256") != sha256_file(server_log_checkpoint)
        or value.get("sourceCommit") != source_commit
        or value.get("maviBuild") != mavi_build
        or value.get("verifiedModelManifestSha256") != manifest_sha256
        or value.get("acceptanceProfileSha256") != acceptance_profile_sha256
        or value.get("applicationManifestSha256") != application_manifest_sha256
        or value.get("prerequisiteEvidenceSha256") != sha256_file(prerequisite_evidence)
        or value.get("freshInstallEvidenceSha256") != sha256_file(fresh_install)
        or value.get("offlineUpdateEvidenceSha256") != sha256_file(offline_update)
        or value.get("backupRestoreEvidenceSha256") != sha256_file(backup_restore)
        or value.get("productionVariantEvidenceSha256") != expected_variant_evidence
        or value.get("productionBundleManifestSha256") != variant_bundle_hashes
        or value.get("productionReleaseLockSha256") != variant_lock_hashes
        or value.get("formalScenarioEvidenceSha256") != sha256_file(formal_scenario)
        or value.get("finalE2eEvidenceSha256") != sha256_file(production_e2e)
        or value.get("emptySceneScenarioEvidenceSha256") != sha256_file(empty_scene_scenario)
        or value.get("emptySceneE2eEvidenceSha256") != sha256_file(empty_scene_e2e)
        or value.get("failureReprocessEvidenceSha256") != sha256_file(failure_reprocess)
        or value.get("logInspectionEvidenceSha256") != sha256_file(log_inspection)
        or not _passed_result(value)
    ):
        raise ClosureError("production_acceptance_binding_mismatch")
    return value

def assess(args: argparse.Namespace) -> dict[str, Any]:
    runtime = load_runtime_profile(args.runtime_profile)
    qualification = load_qualification_record(args.qualification)
    canonical_profile_path, acceptance_profile_sha256 = canonical_acceptance_profile(args.acceptance_profile)
    acceptance_profile = load_json(canonical_profile_path)
    corpus_sha = acceptance_profile.get("qualificationCorpusManifestSha256")
    expected_corpus_sha = corpus_sha if isinstance(corpus_sha, str) else None
    supported_updates_policy_sha256 = policy_sha256_file(CANONICAL_SUPPORTED_UPDATES)

    application_manifest_sha256 = None
    expected_mavi_build = None
    if args.application_manifest is not None:
        application_manifest = load_json(args.application_manifest)
        if application_manifest.get("sourceCommit") != args.source_commit:
            raise ClosureError("application_manifest_source_commit_mismatch")
        expected_mavi_build = application_manifest.get("build")
        if (
            not isinstance(expected_mavi_build, str)
            or not expected_mavi_build
            or expected_mavi_build == "unknown-development"
        ):
            raise ClosureError("application_manifest_build_invalid")
        application_manifest_sha256 = sha256_file(args.application_manifest)

    acceptance_context = None
    acceptance_context_sha = None
    if args.acceptance_context is not None and expected_mavi_build is not None:
        acceptance_context, acceptance_context_sha = load_acceptance_context(
            args.acceptance_context,
            schema_path=PHASE1_ROOT / "production-acceptance-context.schema.json",
            expected_source_commit=args.source_commit,
            expected_mavi_build=expected_mavi_build,
        )

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
        "application-manifest": args.application_manifest,
        "acceptance-context": args.acceptance_context,
        "server-log-checkpoint": args.server_log_checkpoint,
        "production-prerequisite-evidence": args.prerequisite_evidence,
        "production-prerequisite-windows": args.windows_prerequisite_observation,
        "production-prerequisite-database": args.database_prerequisite_observation,
        "production-prerequisite-linux": args.linux_prerequisite_observation,
        "production-windows-x86_64-cpu": args.production_windows_cpu,
        "production-windows-x86_64-cuda": args.production_windows_cuda,
        "production-linux-x86_64-cpu": args.production_linux_cpu,
        "production-linux-x86_64-cuda": args.production_linux_cuda,
        "formal-production-scenario": args.formal_scenario,
        "production-e2e": args.production_e2e,
        "empty-scene-scenario": args.empty_scene_scenario,
        "empty-scene-e2e": args.empty_scene_e2e,
        "failure-reprocess": args.failure_reprocess,
        "production-log-inspection": args.log_inspection,
        "production-acceptance": args.production_acceptance,
    }
    for name, path in optional_inputs.items():
        if path is None:
            pending.append("acceptance:" + name)
    if not args.production_log:
        pending.append("acceptance:production-log-set")

    if args.fresh_install is not None:
        validate_application_lifecycle(
            args.fresh_install,
            expected_mode="fresh-install",
            source_commit=args.source_commit,
            supported_updates_policy_sha256=supported_updates_policy_sha256,
            schema_path=args.application_lifecycle_schema,
        )
        evidence_hashes["fresh-install"] = sha256_file(args.fresh_install)
    if args.offline_update is not None:
        validate_application_lifecycle(
            args.offline_update,
            expected_mode="offline-update",
            source_commit=args.source_commit,
            supported_updates_policy_sha256=supported_updates_policy_sha256,
            schema_path=args.application_lifecycle_schema,
        )
        evidence_hashes["offline-update"] = sha256_file(args.offline_update)
    if args.backup_restore is not None:
        validate_backup_restore(
            args.backup_restore,
            source_commit=args.source_commit,
            mavi_build=expected_mavi_build,
            acceptance_profile_sha256=acceptance_profile_sha256,
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
        if expected_mavi_build is not None and value.get("maviBuild") != expected_mavi_build:
            raise ClosureError("windows_offline_mavi_build_mismatch")
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
        if expected_mavi_build is not None and value.get("maviBuild") != expected_mavi_build:
            raise ClosureError("linux_offline_mavi_build_mismatch")
        evidence_hashes["linux-offline-install"] = sha256_file(args.linux_offline)
    if args.quality is not None:
        validate_quality(
            args.quality,
            args.source_commit,
            acceptance_profile_sha256,
            expected_corpus_sha,
            expected_mavi_build,
        )
        evidence_hashes["cctv-quality-baseline"] = sha256_file(args.quality)
    if args.performance is not None:
        validate_performance(
            args.performance,
            args.source_commit,
            acceptance_profile_sha256,
            acceptance_profile,
            expected_mavi_build,
        )
        evidence_hashes["linux-nvidia-recovery-performance"] = sha256_file(args.performance)

    production_variant_paths = {
        "windows-x86_64-cpu": args.production_windows_cpu,
        "windows-x86_64-cuda": args.production_windows_cuda,
        "linux-x86_64-cpu": args.production_linux_cpu,
        "linux-x86_64-cuda": args.production_linux_cuda,
    }
    production_bundle_hashes: dict[str, str] = {}
    production_lock_hashes: dict[str, str] = {}
    production_variant_values: dict[str, dict[str, Any]] = {}

    production_log_paths: dict[str, Path] = {}
    if args.production_log:
        production_log_paths = production_acceptance.parse_log_arguments(
            args.production_log
        )

    prerequisite_sha = None
    if (
        args.prerequisite_evidence is not None
        and args.windows_prerequisite_observation is not None
        and args.database_prerequisite_observation is not None
        and args.linux_prerequisite_observation is not None
        and expected_mavi_build is not None
    ):
        prerequisite_sha = production_acceptance.validate_prerequisites(
            args.prerequisite_evidence,
            windows_observation=args.windows_prerequisite_observation,
            database_observation=args.database_prerequisite_observation,
            linux_observation=args.linux_prerequisite_observation,
            source_commit=args.source_commit,
            mavi_build=expected_mavi_build,
        )
        evidence_hashes["production-prerequisites"] = prerequisite_sha

    if (
        expected_mavi_build is not None
        and all(path is not None for path in production_variant_paths.values())
    ):
        manifest_sha = sha256_file(args.manifest)
        for variant, path in production_variant_paths.items():
            assert path is not None
            evidence_sha, bundle_sha, lock_sha, value = (
                production_acceptance.validate_variant(
                    path,
                    variant=variant,
                    source_commit=args.source_commit,
                    target_manifest_sha256=manifest_sha,
                    acceptance_profile_sha256=acceptance_profile_sha256,
                    mavi_build=expected_mavi_build,
                )
            )
            evidence_hashes["production-" + variant] = evidence_sha
            production_bundle_hashes[variant] = bundle_sha
            production_lock_hashes[variant] = lock_sha
            production_variant_values[variant] = value

    formal_scenario_sha = None
    final_e2e_sha = None
    formal_log_sha = None
    empty_scenario_sha = None
    empty_e2e_sha = None
    empty_log_sha = None
    failure_sha = None
    failure_log_sha = None

    if (
        args.formal_scenario is not None
        and args.production_e2e is not None
        and expected_mavi_build is not None
        and isinstance(expected_corpus_sha, str)
        and acceptance_context is not None
        and acceptance_context_sha is not None
        and "linux-x86_64-cuda" in production_variant_values
    ):
        (
            formal_scenario_sha,
            final_e2e_sha,
            formal_log_sha,
        ) = production_acceptance.validate_scenario(
            args.formal_scenario,
            args.production_e2e,
            mode="formal",
            source_commit=args.source_commit,
            target_manifest_sha256=sha256_file(args.manifest),
            acceptance_profile_sha256=acceptance_profile_sha256,
            expected_corpus_sha256=expected_corpus_sha,
            mavi_build=expected_mavi_build,
            linux_cuda_variant_path=production_variant_paths["linux-x86_64-cuda"],
            linux_cuda_variant=production_variant_values["linux-x86_64-cuda"],
            linux_cuda_bundle_sha256=production_bundle_hashes["linux-x86_64-cuda"],
            linux_cuda_lock_sha256=production_lock_hashes["linux-x86_64-cuda"],
            acceptance_execution_id=acceptance_context["acceptanceExecutionId"],
            acceptance_context_sha256=acceptance_context_sha,
        )
        evidence_hashes["formal-production-scenario"] = formal_scenario_sha
        evidence_hashes["production-e2e"] = final_e2e_sha

    if (
        args.empty_scene_scenario is not None
        and args.empty_scene_e2e is not None
        and expected_mavi_build is not None
        and acceptance_context is not None
        and acceptance_context_sha is not None
        and "linux-x86_64-cuda" in production_variant_values
    ):
        (
            empty_scenario_sha,
            empty_e2e_sha,
            empty_log_sha,
        ) = production_acceptance.validate_scenario(
            args.empty_scene_scenario,
            args.empty_scene_e2e,
            mode="empty-scene-diagnostic",
            source_commit=args.source_commit,
            target_manifest_sha256=sha256_file(args.manifest),
            acceptance_profile_sha256=acceptance_profile_sha256,
            expected_corpus_sha256=None,
            mavi_build=expected_mavi_build,
            linux_cuda_variant_path=production_variant_paths["linux-x86_64-cuda"],
            linux_cuda_variant=production_variant_values["linux-x86_64-cuda"],
            linux_cuda_bundle_sha256=production_bundle_hashes["linux-x86_64-cuda"],
            linux_cuda_lock_sha256=production_lock_hashes["linux-x86_64-cuda"],
            acceptance_execution_id=acceptance_context["acceptanceExecutionId"],
            acceptance_context_sha256=acceptance_context_sha,
        )
        evidence_hashes["empty-scene-scenario"] = empty_scenario_sha
        evidence_hashes["empty-scene-e2e"] = empty_e2e_sha

    if (
        final_e2e_sha is not None
        and empty_e2e_sha is not None
        and final_e2e_sha == empty_e2e_sha
    ):
        raise ClosureError("production_scenarios_not_distinct")

    if (
        args.failure_reprocess is not None
        and expected_mavi_build is not None
        and acceptance_context is not None
        and acceptance_context_sha is not None
        and "linux-x86_64-cuda" in production_variant_values
    ):
        failure_sha, failure_log_sha = (
            production_acceptance.validate_failure_reprocess(
                args.failure_reprocess,
                source_commit=args.source_commit,
                mavi_build=expected_mavi_build,
                target_manifest_sha256=sha256_file(args.manifest),
                linux_cuda_variant_path=production_variant_paths["linux-x86_64-cuda"],
                linux_cuda_variant=production_variant_values["linux-x86_64-cuda"],
                linux_cuda_bundle_sha256=production_bundle_hashes["linux-x86_64-cuda"],
                linux_cuda_lock_sha256=production_lock_hashes["linux-x86_64-cuda"],
                acceptance_execution_id=acceptance_context["acceptanceExecutionId"],
                acceptance_context_sha256=acceptance_context_sha,
            )
        )
        evidence_hashes["failure-reprocess"] = failure_sha

    if (
        args.log_inspection is not None
        and production_log_paths
        and expected_mavi_build is not None
        and final_e2e_sha is not None
        and empty_e2e_sha is not None
        and failure_sha is not None
        and formal_log_sha is not None
        and empty_log_sha is not None
        and failure_log_sha is not None
        and formal_scenario_sha is not None
        and empty_scenario_sha is not None
    ):
        formal_scenario_value = load_json(args.formal_scenario)
        empty_scenario_value = load_json(args.empty_scene_scenario)
        failure_value = load_json(args.failure_reprocess)
        log_sha = production_acceptance.validate_log_inspection(
            args.log_inspection,
            context_path=args.acceptance_context,
            checkpoint_path=args.server_log_checkpoint,
            log_paths=production_log_paths,
            source_commit=args.source_commit,
            mavi_build=expected_mavi_build,
            formal_scenario_sha256=formal_scenario_sha,
            formal_e2e_sha256=final_e2e_sha,
            empty_scenario_sha256=empty_scenario_sha,
            empty_e2e_sha256=empty_e2e_sha,
            failure_sha256=failure_sha,
            formal_worker_log_sha256=formal_log_sha,
            empty_worker_log_sha256=empty_log_sha,
            failure_worker_log_sha256=failure_log_sha,
            formal_scenario=formal_scenario_value,
            empty_scenario=empty_scenario_value,
            failure_evidence=failure_value,
        )
        evidence_hashes["production-log-inspection"] = log_sha

    if args.backup_restore is not None and final_e2e_sha is not None:
        production_acceptance.validate_backup(
            args.backup_restore,
            source_commit=args.source_commit,
            acceptance_profile_sha256=acceptance_profile_sha256,
            formal_e2e_sha256=final_e2e_sha,
        )

    if (
        prerequisite_sha is not None
        and args.prerequisite_evidence is not None
        and args.fresh_install is not None
        and args.offline_update is not None
        and args.backup_restore is not None
        and "linux-x86_64-cuda" in production_variant_values
    ):
        prerequisite_value = load_json(args.prerequisite_evidence)
        topology = prerequisite_value.get("topologyIdentities", {})
        fresh_value = load_json(args.fresh_install)
        update_value = load_json(args.offline_update)
        backup_value = load_json(args.backup_restore)
        if (
            fresh_value.get("hosting", {}).get("hostIdentitySha256")
            != topology.get("windowsOperationalPlane")
            or update_value.get("hosting", {}).get("hostIdentitySha256")
            != topology.get("windowsOperationalPlane")
        ):
            raise ClosureError("production_windows_topology_mismatch")
        if backup_value.get("sourceDatabaseIdentity") != topology.get("database"):
            raise ClosureError("production_database_topology_mismatch")
        if (
            production_variant_values["linux-x86_64-cuda"].get("hostIdentitySha256")
            != topology.get("linuxVisionWorker")
        ):
            raise ClosureError("production_linux_topology_mismatch")

    if (
        args.production_acceptance is not None
        and prerequisite_sha is not None
        and expected_mavi_build is not None
        and application_manifest_sha256 is not None
        and args.fresh_install is not None
        and args.offline_update is not None
        and args.backup_restore is not None
        and args.formal_scenario is not None
        and args.production_e2e is not None
        and args.empty_scene_scenario is not None
        and args.empty_scene_e2e is not None
        and args.failure_reprocess is not None
        and args.log_inspection is not None
        and args.acceptance_context is not None
        and args.server_log_checkpoint is not None
        and production_log_paths
        and len(production_bundle_hashes) == 4
        and final_e2e_sha is not None
        and empty_e2e_sha is not None
        and failure_sha is not None
    ):
        typed_variants = {
            variant: path
            for variant, path in production_variant_paths.items()
            if path is not None
        }
        validate_production_acceptance_record(
            args.production_acceptance,
            source_commit=args.source_commit,
            mavi_build=expected_mavi_build,
            manifest_sha256=sha256_file(args.manifest),
            acceptance_profile_sha256=acceptance_profile_sha256,
            application_manifest_sha256=application_manifest_sha256,
            acceptance_context=args.acceptance_context,
            server_log_checkpoint=args.server_log_checkpoint,
            prerequisite_evidence=args.prerequisite_evidence,
            fresh_install=args.fresh_install,
            offline_update=args.offline_update,
            backup_restore=args.backup_restore,
            production_variants=typed_variants,
            formal_scenario=args.formal_scenario,
            production_e2e=args.production_e2e,
            empty_scene_scenario=args.empty_scene_scenario,
            empty_scene_e2e=args.empty_scene_e2e,
            failure_reprocess=args.failure_reprocess,
            log_inspection=args.log_inspection,
            variant_bundle_hashes=production_bundle_hashes,
            variant_lock_hashes=production_lock_hashes,
        )
        evidence_hashes["production-acceptance"] = sha256_file(
            args.production_acceptance
        )

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
    parser.add_argument("--application-manifest", type=Path)
    parser.add_argument("--acceptance-context", type=Path)
    parser.add_argument("--server-log-checkpoint", type=Path)
    parser.add_argument("--prerequisite-evidence", type=Path)
    parser.add_argument("--windows-prerequisite-observation", type=Path)
    parser.add_argument("--database-prerequisite-observation", type=Path)
    parser.add_argument("--linux-prerequisite-observation", type=Path)
    parser.add_argument("--fresh-install", type=Path)
    parser.add_argument("--offline-update", type=Path)
    parser.add_argument("--backup-restore", type=Path)
    parser.add_argument("--windows-offline", type=Path)
    parser.add_argument("--linux-offline", type=Path)
    parser.add_argument("--quality", type=Path)
    parser.add_argument("--performance", type=Path)
    parser.add_argument("--production-windows-cpu", type=Path)
    parser.add_argument("--production-windows-cuda", type=Path)
    parser.add_argument("--production-linux-cpu", type=Path)
    parser.add_argument("--production-linux-cuda", type=Path)
    parser.add_argument("--formal-scenario", type=Path)
    parser.add_argument("--production-e2e", type=Path)
    parser.add_argument("--empty-scene-scenario", type=Path)
    parser.add_argument("--empty-scene-e2e", type=Path)
    parser.add_argument("--failure-reprocess", type=Path)
    parser.add_argument("--log-inspection", type=Path)
    parser.add_argument("--production-log", action="append", default=[])
    parser.add_argument("--production-acceptance", type=Path)
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
    except (ClosureError, OSError, json.JSONDecodeError, ReleaseMetadataError, evidence_verifier.EvidenceError, PolicyIdentityError, AcceptanceContextError) as exc:
        code = getattr(exc, "code", str(exc))
        print(json.dumps({"ok": False, "code": code}, sort_keys=True))
        return 2

    print(json.dumps({"ok": True, "state": value["state"], "pending": value["pending"]}, sort_keys=True))
    if args.require_complete and value["state"] != "release-verified":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
