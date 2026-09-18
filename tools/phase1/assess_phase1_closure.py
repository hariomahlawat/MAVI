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
import quality_corpus  # noqa: E402
import assemble_production_acceptance as production_acceptance  # noqa: E402
import deployment_profiles  # noqa: E402
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
    mavi_build: str | None,
    application_manifest_sha256: str | None,
    supported_updates_policy_sha256: str,
    schema_path: Path,
    prior_application_manifest: Path | None = None,
    prior_acceptance_evidence: Path | None = None,
    pre_update_state_check: Path | None = None,
    post_update_state_check: Path | None = None,
) -> dict[str, Any]:
    value = load_json(path)
    validate_schema(value, schema_path)
    require_source_commit(value, source_commit, "application_lifecycle")
    if value.get("mode") != expected_mode:
        raise ClosureError("application_lifecycle_mode_mismatch")
    hosting = value.get("hosting")
    operational_api = value.get("operationalApi")
    if (
        not isinstance(hosting, dict)
        or hosting.get("passed") is not True
        or hosting.get("physicalPath") != value.get("destination")
        or not isinstance(operational_api, dict)
        or operational_api.get("passed") is not True
        or operational_api.get("hostIdentitySha256") != hosting.get("hostIdentitySha256")
    ):
        raise ClosureError("application_lifecycle_iis_binding_mismatch")
    if value.get("internetUnavailable") is not True:
        raise ClosureError("application_lifecycle_not_offline")
    if value.get("observedHealth", {}).get("commit") != source_commit:
        raise ClosureError("application_lifecycle_health_mismatch")
    if (
        mavi_build is not None
        and (
            value.get("build") != mavi_build
            or value.get("observedHealth", {}).get("build") != mavi_build
        )
    ):
        raise ClosureError("application_lifecycle_build_mismatch")
    if (
        application_manifest_sha256 is not None
        and value.get("applicationManifestSha256") != application_manifest_sha256
    ):
        raise ClosureError("application_lifecycle_manifest_mismatch")
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
        update_proofs = (
            prior_application_manifest,
            prior_acceptance_evidence,
            pre_update_state_check,
            post_update_state_check,
        )
        if any(item is None for item in update_proofs) and any(item is not None for item in update_proofs):
            raise ClosureError("offline_update_state_proof_incomplete")
        if (
            prior_application_manifest is not None
            and prior_acceptance_evidence is not None
            and pre_update_state_check is not None
            and post_update_state_check is not None
            and mavi_build is not None
            and application_manifest_sha256 is not None
        ):
            try:
                production_acceptance.validate_lifecycle(
                    path,
                    mode="offline-update",
                    source_commit=source_commit,
                    mavi_build=mavi_build,
                    application_manifest_sha256=application_manifest_sha256,
                    supported_updates_policy_sha256=supported_updates_policy_sha256,
                    prior_application_manifest=prior_application_manifest,
                    prior_acceptance_evidence=prior_acceptance_evidence,
                    pre_update_state_check=pre_update_state_check,
                    post_update_state_check=post_update_state_check,
                )
            except production_acceptance.ProductionAcceptanceError as exc:
                raise ClosureError(str(exc)) from exc
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
    source_topology = value.get("liveStorageTopology", {})
    restore_topology = value.get("restoreStorageTopology", {})
    if (
        source_topology.get("maviCommit") != source_commit
        or restore_topology.get("maviCommit") != source_commit
        or source_topology.get("databaseIdentitySha256") != value.get("sourceDatabaseIdentitySha256")
        or restore_topology.get("databaseIdentitySha256") != value.get("restoreDatabaseIdentitySha256")
    ):
        raise ClosureError("backup_restore_topology_binding_mismatch")
    if (
        mavi_build is not None
        and (
            source_topology.get("maviBuild") != mavi_build
            or restore_topology.get("maviBuild") != mavi_build
        )
    ):
        raise ClosureError("backup_restore_mavi_build_mismatch")
    if value.get("sourceDatabaseIdentitySha256") == value.get("restoreDatabaseIdentitySha256"):
        raise ClosureError("backup_restore_database_targets_not_distinct")
    return value


def validate_quality(
    path: Path,
    *,
    source_commit: str,
    acceptance_profile_sha256: str,
    acceptance_profile: dict[str, Any],
    expected_mavi_build: str,
    target_verified_manifest_sha256: str,
    corpus_manifest: Path,
    case_evidence: dict[str, Path],
    ground_truth: dict[str, Path],
) -> dict[str, Any]:
    value = load_json(path)
    try:
        return quality_corpus.validate_quality_corpus_evidence(
            value,
            source_commit=source_commit,
            mavi_build=expected_mavi_build,
            target_verified_manifest_sha256=target_verified_manifest_sha256,
            acceptance_profile_sha256=acceptance_profile_sha256,
            corpus_manifest=corpus_manifest,
            profile=acceptance_profile,
            case_evidence=case_evidence,
            ground_truth=ground_truth,
            require_passed=True,
        )
    except quality_corpus.QualityCorpusError as exc:
        raise ClosureError("quality_corpus_invalid:" + exc.code) from exc


def validate_performance(
    path: Path,
    source_commit: str,
    acceptance_profile_sha256: str,
    acceptance_profile: dict[str, Any],
    expected_mavi_build: str | None,
    deployment_profile: deployment_profiles.DeploymentProfile,
    deployment_profile_policy_sha256: str,
) -> dict[str, Any]:
    value = load_json(path)
    validate_schema(
        value,
        Path(__file__).with_name(
            "recovery-performance-evidence.schema.json"
        ),
    )
    require_source_commit(value, source_commit, "performance")
    if value.get("acceptanceProfileSha256") != acceptance_profile_sha256:
        raise ClosureError("performance_profile_hash_mismatch")
    if (
        value.get("schemaVersion")
        != "mavi-profile-recovery-performance-evidence-v2"
        or value.get("deploymentProfile")
        != deployment_profile.profile_id
        or value.get("deploymentProfilePolicySha256")
        != deployment_profile_policy_sha256
        or value.get("runtimeVariant")
        != deployment_profile.runtime_variant
    ):
        raise ClosureError("performance_profile_binding_mismatch")
    actual_device = value.get("actualDevice")
    if not isinstance(actual_device, str):
        raise ClosureError("performance_device_invalid")
    if deployment_profile.requires_cuda:
        if not actual_device.startswith("cuda:"):
            raise ClosureError("performance_cuda_device_required")
    elif actual_device != "cpu":
        raise ClosureError("performance_cpu_device_required")
    if (
        expected_mavi_build is not None
        and value.get("maviBuild") != expected_mavi_build
    ):
        raise ClosureError("performance_mavi_build_mismatch")
    thresholds = acceptance_profile.get("performanceThresholds")
    if (
        not isinstance(thresholds, dict)
        or value.get("thresholds") != thresholds
    ):
        raise ClosureError("performance_thresholds_mismatch")
    if (
        value.get("processingFps", 0)
        < thresholds["minimumProcessingFps"]
        or value.get("p95EndToEndLatencyMs", float("inf"))
        > thresholds["maximumP95LatencyMs"]
        or value.get("memoryGrowthBytes", float("inf"))
        > thresholds["maximumSoakGrowthBytes"]
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
    deployment_profile: deployment_profiles.DeploymentProfile,
    deployment_profile_policy_sha256: str,
    acceptance_context: Path,
    server_log_checkpoint: Path,
    prerequisite_evidence: Path,
    fresh_install: Path,
    offline_update: Path,
    prior_application_manifest: Path,
    prior_acceptance_evidence: Path,
    pre_update_state_check: Path,
    post_update_state_check: Path,
    backup_restore: Path,
    backup_execution: Path,
    post_restore_check: Path,
    backup_set_manifest: Path,
    backup_database_manifest: Path,
    backup_managed_source_manifest: Path,
    backup_accepted_evidence_manifest: Path,
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
        Path(__file__).with_name(
            "production-acceptance-evidence.schema.json"
        ),
    )
    required_variants = deployment_profile.required_runtime_variants
    if set(production_variants) != set(required_variants):
        raise ClosureError(
            "production_acceptance_variant_set_mismatch"
        )
    expected_variant_evidence = {
        variant: sha256_file(production_variants[variant])
        for variant in required_variants
    }
    if (
        value.get("schemaVersion")
        != "mavi-phase1-production-acceptance-evidence-v2"
        or value.get("deploymentProfile")
        != deployment_profile.profile_id
        or value.get("deploymentProfilePolicySha256")
        != deployment_profile_policy_sha256
        or value.get("runtimeVariant")
        != deployment_profile.runtime_variant
        or value.get("acceptanceContextSha256")
        != sha256_file(acceptance_context)
        or value.get("serverLogCheckpointSha256")
        != sha256_file(server_log_checkpoint)
        or value.get("sourceCommit") != source_commit
        or value.get("maviBuild") != mavi_build
        or value.get("verifiedModelManifestSha256")
        != manifest_sha256
        or value.get("acceptanceProfileSha256")
        != acceptance_profile_sha256
        or value.get("applicationManifestSha256")
        != application_manifest_sha256
        or value.get("prerequisiteEvidenceSha256")
        != sha256_file(prerequisite_evidence)
        or value.get("freshInstallEvidenceSha256")
        != sha256_file(fresh_install)
        or value.get("offlineUpdateEvidenceSha256")
        != sha256_file(offline_update)
        or value.get("priorApplicationManifestSha256")
        != sha256_file(prior_application_manifest)
        or value.get("priorAcceptanceEvidenceSha256")
        != sha256_file(prior_acceptance_evidence)
        or value.get("preUpdateStateCheckSha256")
        != sha256_file(pre_update_state_check)
        or value.get("postUpdateStateCheckSha256")
        != sha256_file(post_update_state_check)
        or value.get("backupRestoreEvidenceSha256")
        != sha256_file(backup_restore)
        or value.get("backupExecutionEvidenceSha256")
        != sha256_file(backup_execution)
        or value.get("postRestoreCheckSha256")
        != sha256_file(post_restore_check)
        or value.get("backupSetManifestSha256")
        != sha256_file(backup_set_manifest)
        or value.get("backupDatabaseManifestSha256")
        != sha256_file(backup_database_manifest)
        or value.get("backupManagedSourceManifestSha256")
        != sha256_file(backup_managed_source_manifest)
        or value.get("backupAcceptedEvidenceManifestSha256")
        != sha256_file(backup_accepted_evidence_manifest)
        or value.get("productionVariantEvidenceSha256")
        != expected_variant_evidence
        or value.get("productionBundleManifestSha256")
        != variant_bundle_hashes
        or value.get("productionReleaseLockSha256")
        != variant_lock_hashes
        or value.get("formalScenarioEvidenceSha256")
        != sha256_file(formal_scenario)
        or value.get("finalE2eEvidenceSha256")
        != sha256_file(production_e2e)
        or value.get("emptySceneScenarioEvidenceSha256")
        != sha256_file(empty_scene_scenario)
        or value.get("emptySceneE2eEvidenceSha256")
        != sha256_file(empty_scene_e2e)
        or value.get("failureReprocessEvidenceSha256")
        != sha256_file(failure_reprocess)
        or value.get("logInspectionEvidenceSha256")
        != sha256_file(log_inspection)
        or not _passed_result(value)
    ):
        raise ClosureError(
            "production_acceptance_binding_mismatch"
        )
    return value


def validate_qualification_evidence_hashes(
    qualification: Any,
    observed_hashes: dict[str, str],
    required_gates: frozenset[str],
) -> None:
    for gate in sorted(required_gates):
        if qualification.required_gates.get(gate) != "passed":
            raise ClosureError(
                "qualification_gate_not_passed:" + gate
            )
        expected = qualification.evidence.get(gate)
        if expected is None:
            raise ClosureError(
                "qualification_evidence_missing:" + gate
            )
        actual = observed_hashes.get(gate)
        if actual is None:
            raise ClosureError(
                "qualification_evidence_bytes_missing:" + gate
            )
        if actual != expected.sha256:
            raise ClosureError(
                "qualification_evidence_hash_mismatch:" + gate
            )


def assess(args: argparse.Namespace) -> dict[str, Any]:
    runtime = load_runtime_profile(args.runtime_profile)
    qualification = load_qualification_record(
        args.qualification
    )
    selected_profile, deployment_policy_sha = (
        deployment_profiles.select_profile(
            args.deployment_profile,
            args.deployment_profile_policy,
        )
    )
    required_gates = selected_profile.qualification_gates
    runtime_variant = selected_profile.runtime_variant

    canonical_profile_path, acceptance_profile_sha256 = (
        canonical_acceptance_profile(args.acceptance_profile)
    )
    acceptance_profile = load_json(canonical_profile_path)
    corpus_sha = acceptance_profile.get(
        "qualificationCorpusManifestSha256"
    )
    expected_corpus_sha = (
        corpus_sha if isinstance(corpus_sha, str) else None
    )
    quality_case_paths = quality_corpus.parse_named_paths(
        args.quality_case_evidence,
        "quality_case_argument_invalid",
    )
    quality_ground_truth_paths = (
        quality_corpus.parse_named_paths(
            args.quality_ground_truth,
            "quality_ground_truth_argument_invalid",
        )
    )
    supported_updates_policy_sha256 = policy_sha256_file(
        CANONICAL_SUPPORTED_UPDATES
    )

    pending: list[str] = []
    evidence_hashes: dict[str, str] = {}
    qualification_evidence_hashes: dict[str, str] = {}

    runtime_identity = runtime.platform_variants.get(
        runtime_variant
    )
    runtime_lock = runtime.release_locks.get(runtime_variant)
    expected_runtime_status = (
        "qualified-hardware"
        if runtime_variant.endswith("-cuda")
        else "qualified-hosted-cpu"
    )
    if (
        runtime_identity is None
        or runtime_identity.status != expected_runtime_status
    ):
        pending.append("runtime:" + runtime_variant)
    if (
        runtime_lock is None
        or runtime_lock.status != "qualified-offline-lock"
    ):
        pending.append("runtime-lock:" + runtime_variant)

    if selected_profile.profile_id not in qualification.qualified_profiles:
        pending.append(
            "qualification-profile:" + selected_profile.profile_id
        )
    for gate in sorted(required_gates):
        if qualification.required_gates.get(gate) != "passed":
            pending.append("qualification:" + gate)
        elif gate not in qualification.evidence:
            pending.append("qualification-evidence:" + gate)

    application_manifest_sha256 = None
    expected_mavi_build = None
    if args.application_manifest is None:
        pending.append("acceptance:application-manifest")
    else:
        application_manifest = load_json(
            args.application_manifest
        )
        if (
            application_manifest.get("sourceCommit")
            != args.source_commit
        ):
            raise ClosureError(
                "application_manifest_source_commit_mismatch"
            )
        expected_mavi_build = application_manifest.get("build")
        if (
            not isinstance(expected_mavi_build, str)
            or not expected_mavi_build
            or expected_mavi_build
            == "unknown-development"
        ):
            raise ClosureError(
                "application_manifest_build_invalid"
            )
        application_manifest_sha256 = sha256_file(
            args.application_manifest
        )

    acceptance_context = None
    acceptance_context_sha = None
    if (
        args.acceptance_context is not None
        and expected_mavi_build is not None
    ):
        (
            acceptance_context,
            acceptance_context_sha,
        ) = load_acceptance_context(
            args.acceptance_context,
            schema_path=PHASE1_ROOT
            / "production-acceptance-context.schema.json",
            expected_source_commit=args.source_commit,
            expected_mavi_build=expected_mavi_build,
        )
    else:
        pending.append("acceptance:acceptance-context")

    common_required_inputs = {
        "server-log-checkpoint": args.server_log_checkpoint,
        "production-prerequisite-evidence":
            args.prerequisite_evidence,
        "fresh-install": args.fresh_install,
        "offline-update": args.offline_update,
        "prior-application-manifest":
            args.prior_application_manifest,
        "prior-acceptance-evidence":
            args.prior_acceptance_evidence,
        "pre-update-state-check":
            args.pre_update_state_check,
        "post-update-state-check":
            args.post_update_state_check,
        "backup-restore": args.backup_restore,
        "backup-execution": args.backup_execution,
        "post-restore-check": args.post_restore_check,
        "backup-set-manifest": args.backup_set_manifest,
        "backup-database-manifest":
            args.backup_database_manifest,
        "backup-managed-source-manifest":
            args.backup_managed_source_manifest,
        "backup-accepted-evidence-manifest":
            args.backup_accepted_evidence_manifest,
        "cctv-quality-baseline": args.quality,
        "cctv-quality-corpus-manifest":
            args.quality_corpus_manifest,
        "formal-production-scenario":
            args.formal_scenario,
        "production-e2e": args.production_e2e,
        "empty-scene-scenario":
            args.empty_scene_scenario,
        "empty-scene-e2e": args.empty_scene_e2e,
        "failure-reprocess": args.failure_reprocess,
        "production-log-inspection":
            args.log_inspection,
        "production-acceptance":
            args.production_acceptance,
    }
    for name, path in common_required_inputs.items():
        if path is None:
            pending.append("acceptance:" + name)

    if not args.prerequisite_observation:
        pending.append(
            "acceptance:production-prerequisite-observation-set"
        )
    if not args.production_variant:
        pending.append(
            "acceptance:production-variant-set"
        )
    if not args.quality_case_evidence:
        pending.append(
            "acceptance:cctv-quality-case-evidence-set"
        )
    if not args.quality_ground_truth:
        pending.append(
            "acceptance:cctv-quality-ground-truth-set"
        )
    if not args.production_log:
        pending.append("acceptance:production-log-set")
    if (
        selected_profile.performance_evidence_required
        and args.performance is None
    ):
        pending.append(
            "acceptance:profile-recovery-performance"
        )

    if (
        args.fresh_install is not None
        and expected_mavi_build is not None
        and application_manifest_sha256 is not None
    ):
        validate_application_lifecycle(
            args.fresh_install,
            expected_mode="fresh-install",
            source_commit=args.source_commit,
            mavi_build=expected_mavi_build,
            application_manifest_sha256=(
                application_manifest_sha256
            ),
            supported_updates_policy_sha256=(
                supported_updates_policy_sha256
            ),
            schema_path=args.application_lifecycle_schema,
        )
        evidence_hashes["fresh-install"] = sha256_file(
            args.fresh_install
        )

    if (
        args.offline_update is not None
        and expected_mavi_build is not None
        and application_manifest_sha256 is not None
    ):
        validate_application_lifecycle(
            args.offline_update,
            expected_mode="offline-update",
            source_commit=args.source_commit,
            mavi_build=expected_mavi_build,
            application_manifest_sha256=(
                application_manifest_sha256
            ),
            supported_updates_policy_sha256=(
                supported_updates_policy_sha256
            ),
            schema_path=args.application_lifecycle_schema,
            prior_application_manifest=(
                args.prior_application_manifest
            ),
            prior_acceptance_evidence=(
                args.prior_acceptance_evidence
            ),
            pre_update_state_check=(
                args.pre_update_state_check
            ),
            post_update_state_check=(
                args.post_update_state_check
            ),
        )
        evidence_hashes["offline-update"] = sha256_file(
            args.offline_update
        )

    if (
        args.backup_restore is not None
        and expected_mavi_build is not None
    ):
        validate_backup_restore(
            args.backup_restore,
            source_commit=args.source_commit,
            mavi_build=expected_mavi_build,
            acceptance_profile_sha256=(
                acceptance_profile_sha256
            ),
            schema_path=args.backup_restore_schema,
        )
        evidence_hashes["backup-restore"] = sha256_file(
            args.backup_restore
        )

    offline_path = (
        args.windows_offline
        if selected_profile.offline_install_gate
        == "windows-offline-install"
        else args.linux_offline
    )
    if offline_path is None:
        pending.append(
            "acceptance:"
            + selected_profile.offline_install_gate
        )
    else:
        offline_value = load_json(offline_path)
        validate_schema(
            offline_value,
            Path(__file__).with_name(
                "offline-install-evidence.schema.json"
            ),
        )
        evidence_verifier.verify_offline_install(
            offline_value,
            expected_source_commit=args.source_commit,
            expected_acceptance_profile_sha256=(
                acceptance_profile_sha256
            ),
        )
        expected_os = (
            "windows"
            if selected_profile.offline_install_gate
            == "windows-offline-install"
            else "linux"
        )
        if offline_value.get("os") != expected_os:
            raise ClosureError(
                "profile_offline_os_mismatch"
            )
        offline_sha = sha256_file(offline_path)
        evidence_hashes[
            selected_profile.offline_install_gate
        ] = offline_sha
        qualification_evidence_hashes[
            selected_profile.offline_install_gate
        ] = offline_sha
        variant_hash = offline_value.get(
            "variantEvidenceSha256", {}
        ).get(runtime_variant)
        if not isinstance(variant_hash, str):
            raise ClosureError(
                "profile_offline_variant_hash_missing"
            )
        qualification_evidence_hashes[
            runtime_variant
        ] = variant_hash

    if (
        args.quality is not None
        and args.quality_corpus_manifest is not None
        and quality_case_paths
        and quality_ground_truth_paths
        and expected_mavi_build is not None
        and isinstance(expected_corpus_sha, str)
    ):
        if (
            sha256_file(args.quality_corpus_manifest)
            != expected_corpus_sha
        ):
            raise ClosureError(
                "quality_corpus_manifest_hash_mismatch"
            )
        validate_quality(
            args.quality,
            source_commit=args.source_commit,
            acceptance_profile_sha256=(
                acceptance_profile_sha256
            ),
            acceptance_profile=acceptance_profile,
            expected_mavi_build=expected_mavi_build,
            target_verified_manifest_sha256=sha256_file(
                args.manifest
            ),
            corpus_manifest=args.quality_corpus_manifest,
            case_evidence=quality_case_paths,
            ground_truth=quality_ground_truth_paths,
        )
        quality_sha = sha256_file(args.quality)
        evidence_hashes["cctv-quality-baseline"] = (
            quality_sha
        )
        qualification_evidence_hashes[
            "cctv-quality-baseline"
        ] = quality_sha

    if (
        selected_profile.performance_evidence_required
        and args.performance is not None
        and expected_mavi_build is not None
    ):
        validate_performance(
            args.performance,
            args.source_commit,
            acceptance_profile_sha256,
            acceptance_profile,
            expected_mavi_build,
            selected_profile,
            deployment_policy_sha,
        )
        performance_sha = sha256_file(args.performance)
        evidence_hashes[
            "profile-recovery-performance"
        ] = performance_sha
        if selected_profile.performance_gate is not None:
            qualification_evidence_hashes[
                selected_profile.performance_gate
            ] = performance_sha

    observation_paths: dict[str, Path] = {}
    prerequisite_sha = None
    if args.prerequisite_observation:
        observation_paths = (
            production_acceptance
            .parse_prerequisite_observation_arguments(
                args.prerequisite_observation,
                selected_profile.required_prerequisite_roles,
            )
        )
    if (
        args.prerequisite_evidence is not None
        and observation_paths
        and expected_mavi_build is not None
        and acceptance_context is not None
        and acceptance_context_sha is not None
    ):
        prerequisite_sha = (
            production_acceptance.validate_prerequisites(
                args.prerequisite_evidence,
                observation_paths=observation_paths,
                selected_profile=selected_profile,
                deployment_policy_sha256=(
                    deployment_policy_sha
                ),
                source_commit=args.source_commit,
                mavi_build=expected_mavi_build,
                acceptance_execution_id=(
                    acceptance_context[
                        "acceptanceExecutionId"
                    ]
                ),
                acceptance_context_sha256=(
                    acceptance_context_sha
                ),
                context_started_at=(
                    acceptance_context["startedAtUtc"]
                ),
            )
        )
        evidence_hashes[
            "production-prerequisites"
        ] = prerequisite_sha

    prerequisite_value = (
        load_json(args.prerequisite_evidence)
        if prerequisite_sha is not None
        and args.prerequisite_evidence is not None
        else None
    )
    windows_operational_identity = (
        prerequisite_value.get(
            "topologyIdentities", {}
        ).get("windows-operational-plane")
        if isinstance(prerequisite_value, dict)
        else None
    )

    production_variant_paths: dict[str, Path] = {}
    if args.production_variant:
        production_variant_paths = (
            production_acceptance.parse_variant_arguments(
                args.production_variant,
                selected_profile.required_runtime_variants,
            )
        )

    production_bundle_hashes: dict[str, str] = {}
    production_lock_hashes: dict[str, str] = {}
    production_variant_values: dict[
        str, dict[str, Any]
    ] = {}
    if (
        production_variant_paths
        and expected_mavi_build is not None
    ):
        variant_path = production_variant_paths[
            runtime_variant
        ]
        (
            evidence_sha,
            bundle_sha,
            lock_sha,
            variant_value,
        ) = production_acceptance.validate_variant(
            variant_path,
            variant=runtime_variant,
            source_commit=args.source_commit,
            target_manifest_sha256=sha256_file(
                args.manifest
            ),
            acceptance_profile_sha256=(
                acceptance_profile_sha256
            ),
            mavi_build=expected_mavi_build,
        )
        evidence_hashes[
            "production-" + runtime_variant
        ] = evidence_sha
        production_bundle_hashes[
            runtime_variant
        ] = bundle_sha
        production_lock_hashes[
            runtime_variant
        ] = lock_sha
        production_variant_values[
            runtime_variant
        ] = variant_value

    production_log_paths: dict[str, Path] = {}
    if args.production_log:
        production_log_paths = (
            production_acceptance.parse_log_arguments(
                args.production_log
            )
        )

    formal_scenario_sha = None
    final_e2e_sha = None
    formal_log_sha = None
    empty_scenario_sha = None
    empty_e2e_sha = None
    empty_log_sha = None
    failure_sha = None
    failure_log_sha = None

    profile_variant_path = (
        production_variant_paths.get(runtime_variant)
    )
    profile_variant_value = (
        production_variant_values.get(runtime_variant)
    )
    profile_bundle_sha = (
        production_bundle_hashes.get(runtime_variant)
    )
    profile_lock_sha = (
        production_lock_hashes.get(runtime_variant)
    )

    common_scenario_ready = (
        expected_mavi_build is not None
        and acceptance_context is not None
        and acceptance_context_sha is not None
        and profile_variant_path is not None
        and profile_variant_value is not None
        and profile_bundle_sha is not None
        and profile_lock_sha is not None
        and isinstance(
            windows_operational_identity,
            str,
        )
    )

    if (
        common_scenario_ready
        and args.formal_scenario is not None
        and args.production_e2e is not None
        and isinstance(expected_corpus_sha, str)
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
            target_manifest_sha256=sha256_file(
                args.manifest
            ),
            acceptance_profile_sha256=(
                acceptance_profile_sha256
            ),
            expected_corpus_sha256=(
                expected_corpus_sha
            ),
            mavi_build=expected_mavi_build,
            deployment_profile=selected_profile,
            deployment_profile_policy_sha256=(
                deployment_policy_sha
            ),
            variant_path=profile_variant_path,
            variant=profile_variant_value,
            bundle_sha256=profile_bundle_sha,
            lock_sha256=profile_lock_sha,
            acceptance_execution_id=(
                acceptance_context[
                    "acceptanceExecutionId"
                ]
            ),
            acceptance_context_sha256=(
                acceptance_context_sha
            ),
            expected_operational_host_identity_sha256=(
                windows_operational_identity
            ),
        )
        evidence_hashes[
            "formal-production-scenario"
        ] = formal_scenario_sha
        evidence_hashes[
            "production-e2e"
        ] = final_e2e_sha

    if (
        common_scenario_ready
        and args.empty_scene_scenario is not None
        and args.empty_scene_e2e is not None
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
            target_manifest_sha256=sha256_file(
                args.manifest
            ),
            acceptance_profile_sha256=(
                acceptance_profile_sha256
            ),
            expected_corpus_sha256=None,
            mavi_build=expected_mavi_build,
            deployment_profile=selected_profile,
            deployment_profile_policy_sha256=(
                deployment_policy_sha
            ),
            variant_path=profile_variant_path,
            variant=profile_variant_value,
            bundle_sha256=profile_bundle_sha,
            lock_sha256=profile_lock_sha,
            acceptance_execution_id=(
                acceptance_context[
                    "acceptanceExecutionId"
                ]
            ),
            acceptance_context_sha256=(
                acceptance_context_sha
            ),
            expected_operational_host_identity_sha256=(
                windows_operational_identity
            ),
        )
        evidence_hashes[
            "empty-scene-scenario"
        ] = empty_scenario_sha
        evidence_hashes[
            "empty-scene-e2e"
        ] = empty_e2e_sha

    if (
        final_e2e_sha is not None
        and empty_e2e_sha is not None
        and final_e2e_sha == empty_e2e_sha
    ):
        raise ClosureError(
            "production_scenarios_not_distinct"
        )

    if (
        common_scenario_ready
        and args.failure_reprocess is not None
    ):
        failure_sha, failure_log_sha = (
            production_acceptance
            .validate_failure_reprocess(
                args.failure_reprocess,
                source_commit=args.source_commit,
                mavi_build=expected_mavi_build,
                target_manifest_sha256=sha256_file(
                    args.manifest
                ),
                deployment_profile=selected_profile,
                deployment_profile_policy_sha256=(
                    deployment_policy_sha
                ),
                variant_path=profile_variant_path,
                variant=profile_variant_value,
                bundle_sha256=profile_bundle_sha,
                lock_sha256=profile_lock_sha,
                acceptance_execution_id=(
                    acceptance_context[
                        "acceptanceExecutionId"
                    ]
                ),
                acceptance_context_sha256=(
                    acceptance_context_sha
                ),
                expected_operational_host_identity_sha256=(
                    windows_operational_identity
                ),
            )
        )
        evidence_hashes[
            "failure-reprocess"
        ] = failure_sha

    if (
        args.log_inspection is not None
        and production_log_paths
        and formal_scenario_sha is not None
        and final_e2e_sha is not None
        and empty_scenario_sha is not None
        and empty_e2e_sha is not None
        and failure_sha is not None
        and formal_log_sha is not None
        and empty_log_sha is not None
        and failure_log_sha is not None
        and args.server_log_checkpoint is not None
        and args.acceptance_context is not None
    ):
        formal_value = load_json(
            args.formal_scenario
        )
        empty_value = load_json(
            args.empty_scene_scenario
        )
        failure_value = load_json(
            args.failure_reprocess
        )
        if not observation_paths:
            raise ClosureError(
                "production_prerequisite_observations_missing"
            )
        production_acceptance.validate_prerequisite_observation_window(
            tuple(observation_paths.values()),
            first_scenario_started_at=min(
                formal_value["scenarioStartedAtUtc"],
                empty_value["scenarioStartedAtUtc"],
                failure_value["scenarioStartedAtUtc"],
            ),
        )
        log_sha = (
            production_acceptance
            .validate_log_inspection(
                args.log_inspection,
                context_path=args.acceptance_context,
                checkpoint_path=(
                    args.server_log_checkpoint
                ),
                log_paths=production_log_paths,
                source_commit=args.source_commit,
                mavi_build=expected_mavi_build,
                formal_scenario_sha256=(
                    formal_scenario_sha
                ),
                formal_e2e_sha256=final_e2e_sha,
                empty_scenario_sha256=(
                    empty_scenario_sha
                ),
                empty_e2e_sha256=empty_e2e_sha,
                failure_sha256=failure_sha,
                formal_worker_log_sha256=(
                    formal_log_sha
                ),
                empty_worker_log_sha256=(
                    empty_log_sha
                ),
                failure_worker_log_sha256=(
                    failure_log_sha
                ),
                formal_scenario=formal_value,
                empty_scenario=empty_value,
                failure_evidence=failure_value,
            )
        )
        evidence_hashes[
            "production-log-inspection"
        ] = log_sha

    if (
        args.backup_restore is not None
        and args.backup_execution is not None
        and args.post_restore_check is not None
        and args.backup_set_manifest is not None
        and args.backup_database_manifest is not None
        and args.backup_managed_source_manifest is not None
        and args.backup_accepted_evidence_manifest is not None
        and final_e2e_sha is not None
        and expected_mavi_build is not None
    ):
        production_acceptance.validate_backup(
            args.backup_restore,
            source_commit=args.source_commit,
            mavi_build=expected_mavi_build,
            acceptance_profile_sha256=(
                acceptance_profile_sha256
            ),
            formal_e2e_sha256=final_e2e_sha,
            execution_evidence=args.backup_execution,
            post_restore_check=args.post_restore_check,
            backup_set_manifest=args.backup_set_manifest,
            database_manifest=(
                args.backup_database_manifest
            ),
            managed_source_manifest=(
                args.backup_managed_source_manifest
            ),
            accepted_evidence_manifest=(
                args.backup_accepted_evidence_manifest
            ),
        )
        evidence_hashes[
            "backup-execution"
        ] = sha256_file(args.backup_execution)
        evidence_hashes[
            "post-restore-check"
        ] = sha256_file(args.post_restore_check)

    if (
        prerequisite_sha is not None
        and profile_variant_value is not None
        and args.fresh_install is not None
        and args.offline_update is not None
        and args.backup_restore is not None
    ):
        production_acceptance.validate_topology_binding(
            prerequisite_value,
            load_json(args.fresh_install),
            load_json(args.offline_update),
            load_json(args.backup_restore),
            profile_variant_value,
            selected_profile,
        )

    production_acceptance_ready = all(
        item is not None
        for item in (
            args.production_acceptance,
            args.application_manifest,
            args.acceptance_context,
            args.server_log_checkpoint,
            args.prerequisite_evidence,
            args.fresh_install,
            args.offline_update,
            args.prior_application_manifest,
            args.prior_acceptance_evidence,
            args.pre_update_state_check,
            args.post_update_state_check,
            args.backup_restore,
            args.backup_execution,
            args.post_restore_check,
            args.backup_set_manifest,
            args.backup_database_manifest,
            args.backup_managed_source_manifest,
            args.backup_accepted_evidence_manifest,
            args.formal_scenario,
            args.production_e2e,
            args.empty_scene_scenario,
            args.empty_scene_e2e,
            args.failure_reprocess,
            args.log_inspection,
            application_manifest_sha256,
            expected_mavi_build,
            prerequisite_sha,
            formal_scenario_sha,
            final_e2e_sha,
            empty_scenario_sha,
            empty_e2e_sha,
            failure_sha,
        )
    )
    if (
        production_acceptance_ready
        and production_log_paths
        and profile_variant_path is not None
        and args.production_acceptance is not None
    ):
        validate_production_acceptance_record(
            args.production_acceptance,
            source_commit=args.source_commit,
            mavi_build=expected_mavi_build,
            manifest_sha256=sha256_file(
                args.manifest
            ),
            acceptance_profile_sha256=(
                acceptance_profile_sha256
            ),
            application_manifest_sha256=(
                application_manifest_sha256
            ),
            deployment_profile=selected_profile,
            deployment_profile_policy_sha256=(
                deployment_policy_sha
            ),
            acceptance_context=args.acceptance_context,
            server_log_checkpoint=(
                args.server_log_checkpoint
            ),
            prerequisite_evidence=(
                args.prerequisite_evidence
            ),
            fresh_install=args.fresh_install,
            offline_update=args.offline_update,
            prior_application_manifest=(
                args.prior_application_manifest
            ),
            prior_acceptance_evidence=(
                args.prior_acceptance_evidence
            ),
            pre_update_state_check=(
                args.pre_update_state_check
            ),
            post_update_state_check=(
                args.post_update_state_check
            ),
            backup_restore=args.backup_restore,
            backup_execution=args.backup_execution,
            post_restore_check=args.post_restore_check,
            backup_set_manifest=(
                args.backup_set_manifest
            ),
            backup_database_manifest=(
                args.backup_database_manifest
            ),
            backup_managed_source_manifest=(
                args.backup_managed_source_manifest
            ),
            backup_accepted_evidence_manifest=(
                args.backup_accepted_evidence_manifest
            ),
            production_variants={
                runtime_variant: profile_variant_path
            },
            formal_scenario=args.formal_scenario,
            production_e2e=args.production_e2e,
            empty_scene_scenario=(
                args.empty_scene_scenario
            ),
            empty_scene_e2e=args.empty_scene_e2e,
            failure_reprocess=(
                args.failure_reprocess
            ),
            log_inspection=args.log_inspection,
            variant_bundle_hashes=(
                production_bundle_hashes
            ),
            variant_lock_hashes=(
                production_lock_hashes
            ),
        )
        evidence_hashes[
            "production-acceptance"
        ] = sha256_file(
            args.production_acceptance
        )

    if all(
        gate in qualification_evidence_hashes
        for gate in required_gates
    ):
        validate_qualification_evidence_hashes(
            qualification,
            qualification_evidence_hashes,
            required_gates,
        )

    promoted = False
    try:
        selection = verify_release_selection(
            model_root=args.model_root,
            manifest_path=args.manifest,
            profile_path=args.pipeline_profile,
            runtime_profile_path=args.runtime_profile,
            qualification_path=args.qualification,
            allow_unverified=False,
            required_profile=(
                selected_profile.profile_id
            ),
            required_gates=required_gates,
            required_runtime_variant=runtime_variant,
        )
        promoted = (
            selection.verification_status
            == "verified"
        )
    except ReleaseMetadataError:
        promoted = False

    if not promoted:
        pending.append("release:promotion")
    if args.production_acceptance is None:
        pending.append(
            "acceptance:production-acceptance"
        )
    elif "production-acceptance" not in evidence_hashes:
        pending.append(
            "acceptance:production-acceptance-validation"
        )

    pending = sorted(set(pending))
    state = (
        "release-verified"
        if not pending
        else "implementation-complete-evidence-pending"
    )
    return {
        "schemaVersion":
            "mavi-phase1-closure-status-v2",
        "sourceCommit": args.source_commit,
        "deploymentProfile":
            selected_profile.profile_id,
        "deploymentProfilePolicySha256":
            deployment_policy_sha,
        "runtimeVariant": runtime_variant,
        "state": state,
        "pending": pending,
        "evidenceSha256":
            dict(sorted(evidence_hashes.items())),
        "releaseMetadata": {
            "manifestSha256":
                sha256_file(args.manifest),
            "qualificationSha256":
                sha256_file(args.qualification),
            "runtimeProfileSha256":
                sha256_file(args.runtime_profile),
            "pipelineProfileSha256":
                sha256_file(args.pipeline_profile),
            "acceptanceProfileSha256":
                acceptance_profile_sha256,
        },
    }



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
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
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--qualification",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--pipeline-profile",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--runtime-profile",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--acceptance-profile",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--application-manifest",
        type=Path,
    )
    parser.add_argument(
        "--acceptance-context",
        type=Path,
    )
    parser.add_argument(
        "--server-log-checkpoint",
        type=Path,
    )
    parser.add_argument(
        "--prerequisite-evidence",
        type=Path,
    )
    parser.add_argument(
        "--prerequisite-observation",
        action="append",
        default=[],
    )
    parser.add_argument("--fresh-install", type=Path)
    parser.add_argument("--offline-update", type=Path)
    parser.add_argument(
        "--prior-application-manifest",
        type=Path,
    )
    parser.add_argument(
        "--prior-acceptance-evidence",
        type=Path,
    )
    parser.add_argument(
        "--pre-update-state-check",
        type=Path,
    )
    parser.add_argument(
        "--post-update-state-check",
        type=Path,
    )
    parser.add_argument("--backup-restore", type=Path)
    parser.add_argument("--backup-execution", type=Path)
    parser.add_argument("--post-restore-check", type=Path)
    parser.add_argument(
        "--backup-set-manifest",
        type=Path,
    )
    parser.add_argument(
        "--backup-database-manifest",
        type=Path,
    )
    parser.add_argument(
        "--backup-managed-source-manifest",
        type=Path,
    )
    parser.add_argument(
        "--backup-accepted-evidence-manifest",
        type=Path,
    )
    parser.add_argument("--windows-offline", type=Path)
    parser.add_argument("--linux-offline", type=Path)
    parser.add_argument("--quality", type=Path)
    parser.add_argument(
        "--quality-corpus-manifest",
        type=Path,
    )
    parser.add_argument(
        "--quality-case-evidence",
        action="append",
        default=[],
    )
    parser.add_argument(
        "--quality-ground-truth",
        action="append",
        default=[],
    )
    parser.add_argument("--performance", type=Path)
    parser.add_argument(
        "--production-variant",
        action="append",
        default=[],
    )
    parser.add_argument("--formal-scenario", type=Path)
    parser.add_argument("--production-e2e", type=Path)
    parser.add_argument(
        "--empty-scene-scenario",
        type=Path,
    )
    parser.add_argument("--empty-scene-e2e", type=Path)
    parser.add_argument("--failure-reprocess", type=Path)
    parser.add_argument("--log-inspection", type=Path)
    parser.add_argument(
        "--production-log",
        action="append",
        default=[],
    )
    parser.add_argument(
        "--production-acceptance",
        type=Path,
    )
    parser.add_argument(
        "--application-lifecycle-schema",
        type=Path,
        default=Path(__file__).with_name(
            "application-lifecycle-evidence.schema.json"
        ),
    )
    parser.add_argument(
        "--backup-restore-schema",
        type=Path,
        default=Path(__file__).with_name(
            "backup-restore-evidence.schema.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
    )
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
    except (
        ClosureError,
        OSError,
        json.JSONDecodeError,
        ReleaseMetadataError,
        evidence_verifier.EvidenceError,
        quality_corpus.QualityCorpusError,
        PolicyIdentityError,
        AcceptanceContextError,
        deployment_profiles.DeploymentProfileError,
    ) as exc:
        code = getattr(exc, "code", str(exc))
        print(json.dumps({"ok": False, "code": code}, sort_keys=True))
        return 2

    print(json.dumps({"ok": True, "state": value["state"], "pending": value["pending"]}, sort_keys=True))
    if args.require_complete and value["state"] != "release-verified":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
