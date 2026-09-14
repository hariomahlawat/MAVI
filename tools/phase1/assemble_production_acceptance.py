#!/usr/bin/env python3
"""Assemble and independently verify final Task-17 production acceptance evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
PHASE1_ROOT = Path(__file__).resolve().parent
if str(PHASE1_ROOT) not in sys.path:
    sys.path.insert(0, str(PHASE1_ROOT))

import verify_phase1_evidence as evidence_verifier  # noqa: E402
import inspect_production_logs as log_inspector  # noqa: E402
from production_acceptance_context import (  # noqa: E402
    AcceptanceContextError,
    load_context as load_acceptance_context,
)
from policy_identity import (  # noqa: E402
    CANONICAL_SUPPORTED_UPDATES,
    PolicyIdentityError,
    canonical_acceptance_profile,
    canonical_production_prerequisites,
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
PREREQUISITE_ROLES = {
    "windows-operational-plane": "windowsOperationalPlane",
    "database": "database",
    "linux-vision-worker": "linuxVisionWorker",
}
LOG_ROLES = {
    "api", "iis", "postgres",
    "formal-worker", "empty-worker", "failure-worker",
}


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
        Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).iter_errors(value),
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
    hosting = value.get("hosting")
    if (
        not isinstance(hosting, dict)
        or hosting.get("passed") is not True
        or hosting.get("physicalPath") != value.get("destination")
    ):
        raise ProductionAcceptanceError("production_lifecycle_iis_binding_failed")
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
) -> tuple[str, str, str, dict[str, Any]]:
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
        value,
    )


def validate_prerequisites(
    evidence_path: Path,
    *,
    windows_observation: Path,
    database_observation: Path,
    linux_observation: Path,
    source_commit: str,
    mavi_build: str,
) -> str:
    evidence = load_json(evidence_path, "production_prerequisite_evidence_invalid")
    validate_schema(
        evidence,
        "production-prerequisite-evidence.schema.json",
        "production_prerequisite_evidence",
    )
    canonical_policy, policy_sha = canonical_production_prerequisites(
        ROOT / "config" / "acceptance" / "phase1-production-prerequisites-v1.json"
    )
    policy = load_json(canonical_policy, "production_prerequisite_policy_invalid")
    validate_schema(
        policy,
        "production-prerequisite-policy.schema.json",
        "production_prerequisite_policy",
    )
    if policy.get("approvalStatus") != "approved":
        raise ProductionAcceptanceError(
            "production_prerequisite_policy_not_approved"
        )

    observations = {
        "windows-operational-plane": windows_observation,
        "database": database_observation,
        "linux-vision-worker": linux_observation,
    }
    expected_hash_fields = {
        "windows-operational-plane": "windowsObservationSha256",
        "database": "databaseObservationSha256",
        "linux-vision-worker": "linuxObservationSha256",
    }
    topology_fields = {
        "windows-operational-plane": "windowsOperationalPlane",
        "database": "database",
        "linux-vision-worker": "linuxVisionWorker",
    }
    for role, path in observations.items():
        value = load_json(path, "production_prerequisite_observation_invalid")
        validate_schema(
            value,
            "production-prerequisite-observation.schema.json",
            "production_prerequisite_observation",
        )
        policy_key = PREREQUISITE_ROLES[role]
        if (
            value.get("role") != role
            or value.get("values") != policy.get(policy_key)
            or evidence.get(policy_key) != value.get("values")
            or evidence.get(expected_hash_fields[role]) != sha256_file(path)
            or evidence.get("topologyIdentities", {}).get(topology_fields[role])
            != value.get("topologyIdentity")
        ):
            raise ProductionAcceptanceError(
                "production_prerequisite_observation_mismatch:" + role
            )

    if (
        evidence.get("sourceCommit") != source_commit
        or evidence.get("maviBuild") != mavi_build
        or evidence.get("policySha256") != policy_sha
        or not passed_result(evidence)
    ):
        raise ProductionAcceptanceError("production_prerequisite_binding_failed")
    return sha256_file(evidence_path)


def validate_scenario(
    scenario_path: Path,
    e2e_path: Path,
    *,
    mode: str,
    source_commit: str,
    target_manifest_sha256: str,
    acceptance_profile_sha256: str,
    expected_corpus_sha256: str | None,
    mavi_build: str,
    linux_cuda_variant_path: Path,
    linux_cuda_variant: dict[str, Any],
    linux_cuda_bundle_sha256: str,
    linux_cuda_lock_sha256: str,
    acceptance_execution_id: str,
    acceptance_context_sha256: str,
) -> tuple[str, str, str]:
    scenario = load_json(scenario_path, "production_scenario_invalid")
    validate_schema(
        scenario,
        "production-scenario-evidence.schema.json",
        "production_scenario",
    )
    e2e = load_json(e2e_path, "production_e2e_invalid")
    validate_schema(
        e2e,
        "phase1-acceptance-evidence.schema.json",
        "production_e2e",
    )
    try:
        evidence_verifier.verify_acceptance(
            e2e,
            expected_source_commit=source_commit,
            expected_acceptance_profile_sha256=acceptance_profile_sha256,
            expected_qualification_corpus_sha256=(
                expected_corpus_sha256 if mode == "formal" else None
            ),
        )
    except evidence_verifier.EvidenceError as exc:
        raise ProductionAcceptanceError("production_e2e_invalid:" + exc.code) from exc

    attestation = e2e.get("attestation", {})
    release_expected = e2e.get("releaseExpected", {})
    e2e_sha = sha256_file(e2e_path)
    if (
        scenario.get("mode") != mode
        or scenario.get("acceptanceExecutionId") != acceptance_execution_id
        or scenario.get("acceptanceContextSha256") != acceptance_context_sha256
        or scenario.get("sourceCommit") != source_commit
        or scenario.get("maviBuild") != mavi_build
        or scenario.get("targetVerifiedManifestSha256") != target_manifest_sha256
        or scenario.get("linuxCudaVariantEvidenceSha256")
        != sha256_file(linux_cuda_variant_path)
        or scenario.get("productionBundleManifestSha256")
        != linux_cuda_bundle_sha256
        or scenario.get("productionReleaseLockSha256")
        != linux_cuda_lock_sha256
        or scenario.get("workerPythonSha256")
        != linux_cuda_variant.get("workerPythonSha256")
        or scenario.get("workerEnvironmentSha256")
        != linux_cuda_variant.get("workerEnvironmentSha256")
        or scenario.get("workerVenvRootSha256")
        != linux_cuda_variant.get("workerVenvRootSha256")
        or scenario.get("workerResolvedPythonSha256")
        != linux_cuda_variant.get("workerResolvedPythonSha256")
        or scenario.get("e2eEvidenceSha256") != e2e_sha
        or scenario.get("networkIsolation", {}).get("passed") is not True
        or not passed_result(scenario)
        or e2e.get("mode") != mode
        or e2e.get("targetVerifiedManifestSha256") != target_manifest_sha256
        or release_expected.get("modelManifestSha256") != target_manifest_sha256
        or attestation.get("verificationStatus") != "verified"
        or attestation.get("runtimeVariant") != "linux-x86_64-cuda"
        or attestation.get("maviBuild") != mavi_build
        or attestation.get("maviCommit") != source_commit
        or attestation.get("productionBundleManifestSha256")
        != linux_cuda_bundle_sha256
        or attestation.get("platformLockSha256") != linux_cuda_lock_sha256
        or attestation.get("candidateBundleManifestSha256") is not None
        or attestation.get("candidateSelectedLockSha256") is not None
    ):
        raise ProductionAcceptanceError("production_scenario_binding_failed:" + mode)

    actual_device = attestation.get("actualDevice")
    if not isinstance(actual_device, str) or not actual_device.startswith("cuda:"):
        raise ProductionAcceptanceError("production_scenario_cuda_required:" + mode)

    if e2e_sha == linux_cuda_variant.get("workerFlowEvidenceSha256"):
        raise ProductionAcceptanceError(
            "production_scenario_reused_variant_smoke:" + mode
        )

    if mode == "empty-scene-diagnostic":
        if (
            e2e.get("groundTruth") is not None
            or e2e.get("metrics") is not None
            or e2e.get("tracks", {}).get("total") != 0
            or e2e.get("tracks", {}).get("detailsResolved") != 0
            or e2e.get("evidenceReads", {}).get("passed") != 0
        ):
            raise ProductionAcceptanceError(
                "production_empty_scene_false_positive"
            )

    return (
        sha256_file(scenario_path),
        e2e_sha,
        scenario["workerLogSha256"],
    )


def validate_failure_reprocess(
    path: Path,
    *,
    source_commit: str,
    mavi_build: str,
    target_manifest_sha256: str,
    linux_cuda_variant_path: Path,
    linux_cuda_variant: dict[str, Any],
    linux_cuda_bundle_sha256: str,
    linux_cuda_lock_sha256: str,
    acceptance_execution_id: str,
    acceptance_context_sha256: str,
) -> tuple[str, str]:
    value = load_json(path, "production_failure_reprocess_invalid")
    validate_schema(
        value,
        "production-failure-reprocess-evidence.schema.json",
        "production_failure_reprocess",
    )
    media = value.get("sourceMedia", {})
    attestation = value.get("reprocessAttestation", {})
    media_hashes = {
        media.get("localSha256"),
        media.get("afterFailureSha256"),
        media.get("afterFailureEtagSha256"),
        media.get("afterReprocessSha256"),
        media.get("afterReprocessEtagSha256"),
    }
    if (
        value.get("acceptanceExecutionId") != acceptance_execution_id
        or value.get("acceptanceContextSha256") != acceptance_context_sha256
        or value.get("sourceCommit") != source_commit
        or value.get("maviBuild") != mavi_build
        or value.get("targetVerifiedManifestSha256") != target_manifest_sha256
        or value.get("productionBundleManifestSha256")
        != linux_cuda_bundle_sha256
        or value.get("productionReleaseLockSha256")
        != linux_cuda_lock_sha256
        or value.get("linuxCudaVariantEvidenceSha256")
        != sha256_file(linux_cuda_variant_path)
        or value.get("workerPythonSha256")
        != linux_cuda_variant.get("workerPythonSha256")
        or value.get("workerEnvironmentSha256")
        != linux_cuda_variant.get("workerEnvironmentSha256")
        or value.get("workerVenvRootSha256")
        != linux_cuda_variant.get("workerVenvRootSha256")
        or value.get("workerResolvedPythonSha256")
        != linux_cuda_variant.get("workerResolvedPythonSha256")
        or value.get("firstProcessingRunId")
        == value.get("reprocessProcessingRunId")
        or len(media_hashes) != 1
        or None in media_hashes
        or value.get("trackCount", 0) <= 0
        or value.get("networkIsolation", {}).get("passed") is not True
        or attestation.get("verificationStatus") != "verified"
        or attestation.get("runtimeVariant") != "linux-x86_64-cuda"
        or attestation.get("maviBuild") != mavi_build
        or attestation.get("maviCommit") != source_commit
        or attestation.get("modelManifestSha256") != target_manifest_sha256
        or attestation.get("platformLockSha256") != linux_cuda_lock_sha256
        or not isinstance(attestation.get("actualDevice"), str)
        or not attestation["actualDevice"].startswith("cuda:")
        or not passed_result(value)
    ):
        raise ProductionAcceptanceError("production_failure_reprocess_binding_failed")
    return sha256_file(path), value["workerLogSha256"]


def parse_log_arguments(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for item in values:
        if "=" not in item:
            raise ProductionAcceptanceError("production_log_argument_invalid")
        role, raw = item.split("=", 1)
        if role not in LOG_ROLES or role in result or not raw:
            raise ProductionAcceptanceError("production_log_argument_invalid")
        result[role] = Path(raw)
    if set(result) != LOG_ROLES:
        raise ProductionAcceptanceError("production_log_roles_incomplete")
    return result


def _parse_utc(value: str, code: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ProductionAcceptanceError(code) from exc


def validate_log_inspection(
    path: Path,
    *,
    context_path: Path,
    checkpoint_path: Path,
    log_paths: dict[str, Path],
    source_commit: str,
    mavi_build: str,
    formal_scenario_sha256: str,
    formal_e2e_sha256: str,
    empty_scenario_sha256: str,
    empty_e2e_sha256: str,
    failure_sha256: str,
    formal_worker_log_sha256: str,
    empty_worker_log_sha256: str,
    failure_worker_log_sha256: str,
    formal_scenario: dict[str, Any],
    empty_scenario: dict[str, Any],
    failure_evidence: dict[str, Any],
) -> str:
    value = load_json(path, "production_log_inspection_invalid")
    validate_schema(
        value,
        "production-log-inspection-evidence.schema.json",
        "production_log_inspection",
    )
    context, context_sha = load_acceptance_context(
        context_path,
        schema_path=PHASE1_ROOT / "production-acceptance-context.schema.json",
        expected_source_commit=source_commit,
        expected_mavi_build=mavi_build,
    )
    checkpoint = load_json(checkpoint_path, "production_log_checkpoint_invalid")
    validate_schema(
        checkpoint,
        "production-log-checkpoint.schema.json",
        "production_log_checkpoint",
    )
    if (
        checkpoint.get("acceptanceExecutionId") != context["acceptanceExecutionId"]
        or checkpoint.get("acceptanceContextSha256") != context_sha
        or value.get("acceptanceExecutionId") != context["acceptanceExecutionId"]
        or value.get("acceptanceContextSha256") != context_sha
        or value.get("serverLogCheckpointSha256") != sha256_file(checkpoint_path)
    ):
        raise ProductionAcceptanceError("production_log_context_binding_failed")

    context_start = _parse_utc(context["startedAtUtc"], "production_context_time_invalid")
    checkpoint_time = _parse_utc(checkpoint["capturedAtUtc"], "production_checkpoint_time_invalid")
    formal_start = _parse_utc(formal_scenario["scenarioStartedAtUtc"], "production_formal_time_invalid")
    formal_end = _parse_utc(formal_scenario["scenarioCompletedAtUtc"], "production_formal_time_invalid")
    empty_start = _parse_utc(empty_scenario["scenarioStartedAtUtc"], "production_empty_time_invalid")
    empty_end = _parse_utc(empty_scenario["scenarioCompletedAtUtc"], "production_empty_time_invalid")
    failure_start = _parse_utc(failure_evidence["scenarioStartedAtUtc"], "production_failure_time_invalid")
    failure_end = _parse_utc(failure_evidence["scenarioCompletedAtUtc"], "production_failure_time_invalid")
    inspection_end = _parse_utc(value["inspectionCompletedAtUtc"], "production_log_time_invalid")
    if not (
        context_start <= checkpoint_time
        and checkpoint_time <= formal_start <= formal_end <= inspection_end
        and checkpoint_time <= empty_start <= empty_end <= inspection_end
        and checkpoint_time <= failure_start <= failure_end <= inspection_end
    ):
        raise ProductionAcceptanceError("production_acceptance_time_order_invalid")

    logs = value.get("logs", [])
    by_role = {item.get("role"): item for item in logs if isinstance(item, dict)}
    if set(by_role) != LOG_ROLES or set(log_paths) != LOG_ROLES:
        raise ProductionAcceptanceError("production_log_inspection_binding_failed")
    checkpoints = {
        item.get("role"): item
        for item in checkpoint.get("logs", [])
        if isinstance(item, dict)
    }
    if set(checkpoints) != {"api", "iis", "postgres"}:
        raise ProductionAcceptanceError("production_log_checkpoint_roles_incomplete")

    allowed_hosts_raw = value.get("allowedHosts")
    if not isinstance(allowed_hosts_raw, list):
        raise ProductionAcceptanceError("production_log_inspection_binding_failed")
    try:
        allowed_hosts = {log_inspector.validate_allowed_host(item) for item in allowed_hosts_raw}
    except log_inspector.LogInspectionError as exc:
        raise ProductionAcceptanceError("production_log_inspection_invalid_allowlist") from exc

    for role, raw_path in log_paths.items():
        raw = raw_path.read_bytes()
        item = by_role[role]
        if role in {"api", "iis", "postgres"}:
            cp = checkpoints[role]
            if str(raw_path.resolve()) != cp.get("path"):
                raise ProductionAcceptanceError("production_log_checkpoint_path_mismatch:" + role)
            start_offset = int(cp["startOffset"])
            if len(raw) < start_offset:
                raise ProductionAcceptanceError("production_log_checkpoint_offset_invalid:" + role)
            prefix_sha = hashlib.sha256(raw[:start_offset]).hexdigest()
            if prefix_sha != cp.get("prefixSha256"):
                raise ProductionAcceptanceError("production_log_checkpoint_prefix_mismatch:" + role)
            segment = raw[start_offset:]
        else:
            start_offset = 0
            segment = raw
        if not segment:
            raise ProductionAcceptanceError("production_log_acceptance_segment_empty:" + role)
        try:
            text = segment.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProductionAcceptanceError("production_log_not_utf8:" + role) from exc
        if (
            item.get("path") != str(raw_path.resolve())
            or item.get("startOffset") != start_offset
            or item.get("endOffset") != len(raw)
            or item.get("segmentSizeBytes") != len(segment)
            or item.get("segmentSha256") != hashlib.sha256(segment).hexdigest()
        ):
            raise ProductionAcceptanceError("production_log_file_binding_mismatch:" + role)
        external, suspicious = log_inspector.inspect_text(text, allowed_hosts=allowed_hosts)
        if external or suspicious:
            raise ProductionAcceptanceError("production_log_content_failed:" + role)

    if (
        value.get("sourceCommit") != source_commit
        or value.get("maviBuild") != mavi_build
        or value.get("formalScenarioSha256") != formal_scenario_sha256
        or value.get("formalE2eSha256") != formal_e2e_sha256
        or value.get("emptySceneScenarioSha256") != empty_scenario_sha256
        or value.get("emptySceneDiagnosticSha256") != empty_e2e_sha256
        or value.get("failureReprocessSha256") != failure_sha256
        or by_role["formal-worker"].get("segmentSha256") != formal_worker_log_sha256
        or by_role["empty-worker"].get("segmentSha256") != empty_worker_log_sha256
        or by_role["failure-worker"].get("segmentSha256") != failure_worker_log_sha256
        or value.get("result", {}).get("externalUrlHits") != []
        or value.get("result", {}).get("telemetryOrLicenceHits") != []
        or not passed_result(value)
    ):
        raise ProductionAcceptanceError("production_log_inspection_binding_failed")
    return sha256_file(path)

def validate_backup(
    path: Path,
    *,
    source_commit: str,
    acceptance_profile_sha256: str,
    formal_e2e_sha256: str,
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
        or value.get("acceptanceEvidenceSha256") != formal_e2e_sha256
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
    acceptance_context, acceptance_context_sha = load_acceptance_context(
        args.acceptance_context,
        schema_path=PHASE1_ROOT / "production-acceptance-context.schema.json",
        expected_source_commit=args.source_commit,
        expected_mavi_build=mavi_build,
    )

    prerequisite_sha = validate_prerequisites(
        args.prerequisite_evidence,
        windows_observation=args.windows_prerequisite_observation,
        database_observation=args.database_prerequisite_observation,
        linux_observation=args.linux_prerequisite_observation,
        source_commit=args.source_commit,
        mavi_build=mavi_build,
    )

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
    variant_values: dict[str, dict[str, Any]] = {}
    for variant in VARIANTS:
        evidence_sha, bundle_sha, lock_sha, value = validate_variant(
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
        variant_values[variant] = value

    linux_variant_path = variant_paths["linux-x86_64-cuda"]
    linux_variant = variant_values["linux-x86_64-cuda"]
    formal_scenario_sha, formal_e2e_sha, formal_log_sha = validate_scenario(
        args.formal_scenario,
        args.final_e2e,
        mode="formal",
        source_commit=args.source_commit,
        target_manifest_sha256=target_manifest_sha,
        acceptance_profile_sha256=profile_sha,
        expected_corpus_sha256=corpus_sha,
        mavi_build=mavi_build,
        linux_cuda_variant_path=linux_variant_path,
        linux_cuda_variant=linux_variant,
        linux_cuda_bundle_sha256=bundle_hashes["linux-x86_64-cuda"],
        linux_cuda_lock_sha256=lock_hashes["linux-x86_64-cuda"],
        acceptance_execution_id=acceptance_context["acceptanceExecutionId"],
        acceptance_context_sha256=acceptance_context_sha,
    )
    empty_scenario_sha, empty_e2e_sha, empty_log_sha = validate_scenario(
        args.empty_scene_scenario,
        args.empty_scene_e2e,
        mode="empty-scene-diagnostic",
        source_commit=args.source_commit,
        target_manifest_sha256=target_manifest_sha,
        acceptance_profile_sha256=profile_sha,
        expected_corpus_sha256=None,
        mavi_build=mavi_build,
        linux_cuda_variant_path=linux_variant_path,
        linux_cuda_variant=linux_variant,
        linux_cuda_bundle_sha256=bundle_hashes["linux-x86_64-cuda"],
        linux_cuda_lock_sha256=lock_hashes["linux-x86_64-cuda"],
        acceptance_execution_id=acceptance_context["acceptanceExecutionId"],
        acceptance_context_sha256=acceptance_context_sha,
    )
    if formal_e2e_sha == empty_e2e_sha:
        raise ProductionAcceptanceError("production_scenarios_not_distinct")

    failure_sha, failure_log_sha = validate_failure_reprocess(
        args.failure_reprocess,
        source_commit=args.source_commit,
        mavi_build=mavi_build,
        target_manifest_sha256=target_manifest_sha,
        linux_cuda_variant_path=linux_variant_path,
        linux_cuda_variant=linux_variant,
        linux_cuda_bundle_sha256=bundle_hashes["linux-x86_64-cuda"],
        linux_cuda_lock_sha256=lock_hashes["linux-x86_64-cuda"],
        acceptance_execution_id=acceptance_context["acceptanceExecutionId"],
        acceptance_context_sha256=acceptance_context_sha,
    )

    formal_scenario_value = load_json(args.formal_scenario, "production_formal_scenario_invalid")
    empty_scenario_value = load_json(args.empty_scene_scenario, "production_empty_scenario_invalid")
    failure_value = load_json(args.failure_reprocess, "production_failure_reprocess_invalid")
    production_log_paths = parse_log_arguments(args.production_log)
    log_inspection_sha = validate_log_inspection(
        args.log_inspection,
        context_path=args.acceptance_context,
        checkpoint_path=args.server_log_checkpoint,
        log_paths=production_log_paths,
        source_commit=args.source_commit,
        mavi_build=mavi_build,
        formal_scenario_sha256=formal_scenario_sha,
        formal_e2e_sha256=formal_e2e_sha,
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

    backup_sha = validate_backup(
        args.backup_restore,
        source_commit=args.source_commit,
        acceptance_profile_sha256=profile_sha,
        formal_e2e_sha256=formal_e2e_sha,
    )

    prerequisite_value = load_json(
        args.prerequisite_evidence,
        "production_prerequisite_evidence_invalid",
    )
    topology = prerequisite_value.get("topologyIdentities", {})
    fresh_value = load_json(args.fresh_install, "production_fresh_install_invalid")
    update_value = load_json(args.offline_update, "production_offline_update_invalid")
    backup_value = load_json(args.backup_restore, "production_backup_restore_invalid")
    windows_topology = topology.get("windowsOperationalPlane")
    database_topology = topology.get("database")
    linux_topology = topology.get("linuxVisionWorker")
    if (
        not isinstance(windows_topology, str)
        or fresh_value.get("hosting", {}).get("hostIdentitySha256") != windows_topology
        or update_value.get("hosting", {}).get("hostIdentitySha256") != windows_topology
    ):
        raise ProductionAcceptanceError("production_windows_topology_mismatch")
    if (
        not isinstance(database_topology, str)
        or backup_value.get("sourceDatabaseIdentity") != database_topology
    ):
        raise ProductionAcceptanceError("production_database_topology_mismatch")
    if (
        not isinstance(linux_topology, str)
        or linux_variant.get("hostIdentitySha256") != linux_topology
    ):
        raise ProductionAcceptanceError("production_linux_topology_mismatch")

    return {
        "schemaVersion": "mavi-phase1-production-acceptance-evidence-v1",
        "acceptanceExecutionId": acceptance_context["acceptanceExecutionId"],
        "acceptanceContextSha256": acceptance_context_sha,
        "serverLogCheckpointSha256": sha256_file(args.server_log_checkpoint),
        "sourceCommit": args.source_commit,
        "maviBuild": mavi_build,
        "verifiedModelManifestSha256": target_manifest_sha,
        "acceptanceProfileSha256": profile_sha,
        "applicationManifestSha256": application_manifest_sha,
        "prerequisiteEvidenceSha256": prerequisite_sha,
        "freshInstallEvidenceSha256": fresh_sha,
        "offlineUpdateEvidenceSha256": update_sha,
        "backupRestoreEvidenceSha256": backup_sha,
        "productionVariantEvidenceSha256": variant_evidence,
        "productionBundleManifestSha256": bundle_hashes,
        "productionReleaseLockSha256": lock_hashes,
        "formalScenarioEvidenceSha256": formal_scenario_sha,
        "finalE2eEvidenceSha256": formal_e2e_sha,
        "emptySceneScenarioEvidenceSha256": empty_scenario_sha,
        "emptySceneE2eEvidenceSha256": empty_e2e_sha,
        "failureReprocessEvidenceSha256": failure_sha,
        "logInspectionEvidenceSha256": log_inspection_sha,
        "result": {"passed": True, "failureCodes": []},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--acceptance-context", type=Path, required=True)
    parser.add_argument("--server-log-checkpoint", type=Path, required=True)
    parser.add_argument("--verified-model-manifest", type=Path, required=True)
    parser.add_argument("--acceptance-profile", type=Path, required=True)
    parser.add_argument("--application-artifact-root", type=Path, required=True)
    parser.add_argument("--application-manifest", type=Path, required=True)
    parser.add_argument("--prerequisite-evidence", type=Path, required=True)
    parser.add_argument("--windows-prerequisite-observation", type=Path, required=True)
    parser.add_argument("--database-prerequisite-observation", type=Path, required=True)
    parser.add_argument("--linux-prerequisite-observation", type=Path, required=True)
    parser.add_argument("--fresh-install", type=Path, required=True)
    parser.add_argument("--offline-update", type=Path, required=True)
    parser.add_argument("--production-variant", action="append", default=[])
    parser.add_argument("--formal-scenario", type=Path, required=True)
    parser.add_argument("--final-e2e", type=Path, required=True)
    parser.add_argument("--empty-scene-scenario", type=Path, required=True)
    parser.add_argument("--empty-scene-e2e", type=Path, required=True)
    parser.add_argument("--failure-reprocess", type=Path, required=True)
    parser.add_argument("--log-inspection", type=Path, required=True)
    parser.add_argument("--production-log", action="append", default=[])
    parser.add_argument("--backup-restore", type=Path, required=True)
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
        AcceptanceContextError,
        OSError,
        json.JSONDecodeError,
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
