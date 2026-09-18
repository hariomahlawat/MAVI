#!/usr/bin/env python3
"""Fail-closed Task-17 release promotion constructor.

The tool never edits authoritative release metadata in place. It builds candidate
promoted files in an output directory and validates them through the canonical
release verifier before they may be copied into the repository by a reviewed
status/evidence-only commit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PHASE1_ROOT = Path(__file__).resolve().parent
VISION_ROOT = ROOT / "src" / "vision"
for candidate in (PHASE1_ROOT, VISION_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from mavi_vision.runtime.manifest import (  # noqa: E402
    ReleaseMetadataError,
    read_release_json,
    sha256_release_file,
)
from mavi_vision.runtime.qualification import (  # noqa: E402
    MANDATORY_QUALIFICATION_GATES,
    load_qualification_record,
    load_runtime_profile,
    verify_release_selection,
)
import verify_phase1_evidence as evidence_verifier  # noqa: E402
import quality_corpus  # noqa: E402
import deployment_profiles  # noqa: E402
from compute_target_verified_manifest import build_target_manifest, sha256_bytes as target_sha256_bytes  # noqa: E402
from jsonschema import Draft202012Validator  # noqa: E402
from policy_identity import PolicyIdentityError, canonical_acceptance_profile  # noqa: E402


class PromotionError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def canonical_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_dict(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromotionError(code) from exc
    if not isinstance(value, dict):
        raise PromotionError(code)
    return value


def _validate_external_schema(value: dict[str, Any], schema_path: Path, code: str) -> None:
    schema = _load_dict(schema_path, code + "_schema_unavailable")
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        raise PromotionError(code + "_schema_invalid")


def _canonical_policy(path: Path) -> tuple[dict[str, Any], str]:
    canonical, profile_sha = canonical_acceptance_profile(path)
    profile = _load_dict(canonical, "promotion_acceptance_profile_invalid")
    if profile.get("mode") != "qualification":
        raise PromotionError("promotion_acceptance_profile_not_qualification")
    corpus_sha = profile.get("qualificationCorpusManifestSha256")
    if (
        not isinstance(corpus_sha, str)
        or len(corpus_sha) != 64
        or any(ch not in "0123456789abcdef" for ch in corpus_sha)
    ):
        raise PromotionError("promotion_qualification_corpus_not_approved")
    thresholds = profile.get("performanceThresholds")
    if not isinstance(thresholds, dict):
        raise PromotionError("promotion_performance_thresholds_not_approved")
    return profile, profile_sha


def evidence_passed(value: dict[str, Any]) -> bool:
    result = value.get("result")
    if result == "passed":
        return True
    if isinstance(result, dict) and result.get("passed") is True and not result.get("failureCodes"):
        return True
    return False


def _validate_schema(value: dict[str, Any], schema_name: str) -> None:
    schema_path = PHASE1_ROOT / schema_name
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromotionError("promotion_schema_unavailable:" + schema_name) from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        raise PromotionError(
            "promotion_evidence_schema_invalid:"
            + schema_name
            + ":"
            + "/".join(str(x) for x in errors[0].absolute_path)
        )


def _validate_platform_variant_evidence(
    gate: str,
    value: dict[str, Any],
    acceptance_profile_sha256: str,
    expected_mavi_build: str,
    deployment_profile_id: str,
    deployment_profile_policy_sha256: str,
    runtime_variant: str,
) -> None:
    _validate_schema(value, "offline-variant-evidence.schema.json")
    if value.get("variant") != gate:
        raise PromotionError("promotion_variant_evidence_gate_mismatch:" + gate)
    if value.get("acceptanceProfileSha256") != acceptance_profile_sha256:
        raise PromotionError("promotion_variant_profile_mismatch:" + gate)
    if value.get("maviBuild") != expected_mavi_build:
        raise PromotionError("promotion_variant_build_mismatch:" + gate)
    if value.get("bundleMode") != "qualification-candidate":
        raise PromotionError("promotion_variant_evidence_not_candidate:" + gate)
    if value.get("expectedHostCompatibility") != value.get("observedHostCompatibility"):
        raise PromotionError("promotion_variant_host_mismatch:" + gate)
    if (
        value.get("installExitCode") != 0
        or value.get("pipCheckPassed") is not True
        or value.get("runtimeStarted") is not True
        or value.get("realInferencePassed") is not True
        or value.get("workerFlowPassed") is not True
        or value.get("outboundNetworkUnavailable") is not True
        or value.get("firstRunDownloadObserved") is not False
        or value.get("result") != "passed"
    ):
        raise PromotionError("promotion_variant_evidence_not_passed:" + gate)
    device = value.get("actualDevice")
    if gate.endswith("-cpu") and device != "cpu":
        raise PromotionError("promotion_variant_device_mismatch:" + gate)
    if gate.endswith("-cuda") and not (
        isinstance(device, str) and device.startswith("cuda:")
    ):
        raise PromotionError("promotion_variant_device_mismatch:" + gate)


def _validate_offline_os_evidence(
    gate: str,
    value: dict[str, Any],
    source_commit: str,
    acceptance_profile_sha256: str,
    expected_mavi_build: str,
) -> None:
    _validate_schema(value, "offline-install-evidence.schema.json")
    evidence_verifier.verify_offline_install(
        value,
        expected_source_commit=source_commit,
        expected_acceptance_profile_sha256=acceptance_profile_sha256,
    )
    if value.get("maviBuild") != expected_mavi_build:
        raise PromotionError("promotion_offline_build_mismatch:" + gate)
    expected_os = "windows" if gate == "windows-offline-install" else "linux"
    if value.get("os") != expected_os:
        raise PromotionError("promotion_offline_os_mismatch:" + gate)
    if value.get("bundleMode") != "qualification-candidate":
        raise PromotionError("promotion_offline_evidence_not_candidate:" + gate)


def _validate_offline_aggregate_bindings(
    gate_evidence: dict[str, Path],
    required_variants: frozenset[str],
) -> None:
    for os_name in ("windows", "linux"):
        aggregate_gate = f"{os_name}-offline-install"
        if aggregate_gate not in gate_evidence:
            continue
        aggregate = _load_dict(
            gate_evidence[aggregate_gate],
            "promotion_offline_evidence_invalid:" + aggregate_gate,
        )
        hashes = aggregate.get("variantEvidenceSha256")
        if not isinstance(hashes, dict):
            raise PromotionError(
                "promotion_offline_variant_evidence_binding_mismatch:"
                + aggregate_gate
            )
        for variant in sorted(required_variants):
            if not variant.startswith(os_name + "-"):
                continue
            variant_path = gate_evidence.get(variant)
            if (
                variant_path is None
                or hashes.get(variant) != sha256_file_bytes(variant_path)
            ):
                raise PromotionError(
                    "promotion_offline_variant_evidence_binding_mismatch:"
                    + aggregate_gate
                    + ":"
                    + variant
                )


def _validate_quality_evidence(
    value: dict[str, Any],
    source_commit: str,
    acceptance_profile_sha256: str,
    acceptance_profile: dict[str, Any],
    corpus_manifest_path: Path,
    case_evidence: dict[str, Path],
    ground_truth: dict[str, Path],
    expected_mavi_build: str,
    target_verified_manifest_sha256: str,
) -> None:
    try:
        quality_corpus.validate_quality_corpus_evidence(
            value,
            source_commit=source_commit,
            mavi_build=expected_mavi_build,
            target_verified_manifest_sha256=target_verified_manifest_sha256,
            acceptance_profile_sha256=acceptance_profile_sha256,
            corpus_manifest=corpus_manifest_path,
            profile=acceptance_profile,
            case_evidence=case_evidence,
            ground_truth=ground_truth,
            require_passed=True,
        )
    except quality_corpus.QualityCorpusError as exc:
        raise PromotionError("promotion_quality_invalid:" + exc.code) from exc


def _validate_performance_evidence(
    value: dict[str, Any],
    acceptance_profile_sha256: str,
    acceptance_profile: dict[str, Any],
    expected_mavi_build: str,
    *,
    deployment_profile_id: str,
    deployment_profile_policy_sha256: str,
    runtime_variant: str,
) -> None:
    _validate_schema(value, "recovery-performance-evidence.schema.json")
    if value.get("acceptanceProfileSha256") != acceptance_profile_sha256:
        raise PromotionError("promotion_performance_profile_mismatch")
    if value.get("maviBuild") != expected_mavi_build:
        raise PromotionError("promotion_performance_build_mismatch")
    if (
        value.get("schemaVersion")
        != "mavi-profile-recovery-performance-evidence-v2"
        or value.get("deploymentProfile") != deployment_profile_id
        or value.get("deploymentProfilePolicySha256")
        != deployment_profile_policy_sha256
        or value.get("runtimeVariant") != runtime_variant
    ):
        raise PromotionError("promotion_performance_profile_binding_mismatch")
    expected = acceptance_profile.get("performanceThresholds")
    if not isinstance(expected, dict) or value.get("thresholds") != expected:
        raise PromotionError("promotion_performance_thresholds_mismatch")
    if not evidence_passed(value):
        raise PromotionError("promotion_performance_not_passed")
    if (
        value.get("processingFps", 0) < expected["minimumProcessingFps"]
        or value.get("p95EndToEndLatencyMs", float("inf")) > expected["maximumP95LatencyMs"]
        or value.get("memoryGrowthBytes", float("inf")) > expected["maximumSoakGrowthBytes"]
    ):
        raise PromotionError("promotion_performance_recalculation_failed")

def validate_gate_evidence(
    gate: str,
    value: dict[str, Any],
    *,
    source_commit: str,
    target_verified_manifest_sha256: str,
    acceptance_profile_sha256: str,
    acceptance_profile: dict[str, Any],
    quality_corpus_manifest: Path,
    quality_case_evidence: dict[str, Path],
    quality_ground_truth: dict[str, Path],
    expected_mavi_build: str,
    deployment_profile_id: str,
    deployment_profile_policy_sha256: str,
    runtime_variant: str,
) -> None:
    if value.get("sourceCommit") != source_commit:
        raise PromotionError("promotion_evidence_source_mismatch:" + gate)
    if value.get("targetVerifiedManifestSha256") != target_verified_manifest_sha256:
        raise PromotionError("promotion_evidence_target_manifest_mismatch:" + gate)
    if gate in {
        "windows-x86_64-cpu",
        "windows-x86_64-cuda",
        "linux-x86_64-cpu",
        "linux-x86_64-cuda",
    }:
        _validate_platform_variant_evidence(
            gate, value, acceptance_profile_sha256, expected_mavi_build
        )
        return
    if gate in {"windows-offline-install", "linux-offline-install"}:
        _validate_offline_os_evidence(
            gate, value, source_commit, acceptance_profile_sha256, expected_mavi_build
        )
        return
    if gate == "cctv-quality-baseline":
        _validate_quality_evidence(
            value,
            source_commit,
            acceptance_profile_sha256,
            acceptance_profile,
            quality_corpus_manifest,
            quality_case_evidence,
            quality_ground_truth,
            expected_mavi_build,
            target_verified_manifest_sha256,
        )
        return
    if gate == "linux-nvidia-recovery-performance":
        _validate_performance_evidence(
            value,
            acceptance_profile_sha256,
            acceptance_profile,
            expected_mavi_build,
            deployment_profile_id=deployment_profile_id,
            deployment_profile_policy_sha256=deployment_profile_policy_sha256,
            runtime_variant=runtime_variant,
        )
        return
    raise PromotionError("promotion_gate_unknown:" + gate)


def load_gate_evidence(
    path: Path,
    *,
    gate: str,
    expected_source_commit: str,
    target_verified_manifest_sha256: str,
    acceptance_profile_sha256: str,
    acceptance_profile: dict[str, Any],
    quality_corpus_manifest: Path,
    quality_case_evidence: dict[str, Path],
    quality_ground_truth: dict[str, Path],
    expected_mavi_build: str,
    deployment_profile_id: str,
    deployment_profile_policy_sha256: str,
    runtime_variant: str,
) -> dict[str, str]:
    try:
        payload = path.read_bytes()
        value = json.loads(payload)
    except (OSError, json.JSONDecodeError) as exc:
        raise PromotionError("promotion_evidence_invalid:" + gate) from exc
    if not isinstance(value, dict):
        raise PromotionError("promotion_evidence_invalid:" + gate)

    validate_gate_evidence(
        gate,
        value,
        source_commit=expected_source_commit,
        target_verified_manifest_sha256=target_verified_manifest_sha256,
        acceptance_profile_sha256=acceptance_profile_sha256,
        acceptance_profile=acceptance_profile,
        quality_corpus_manifest=quality_corpus_manifest,
        quality_case_evidence=quality_case_evidence,
        quality_ground_truth=quality_ground_truth,
        expected_mavi_build=expected_mavi_build,
        deployment_profile_id=deployment_profile_id,
        deployment_profile_policy_sha256=deployment_profile_policy_sha256,
        runtime_variant=runtime_variant,
    )

    return {
        "kind": "task17-evidence",
        "reference": path.name,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def parse_gate_arguments(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise PromotionError("promotion_gate_argument_invalid")
        gate, raw_path = value.split("=", 1)
        if gate not in MANDATORY_QUALIFICATION_GATES or gate in result or not raw_path:
            raise PromotionError("promotion_gate_argument_invalid")
        result[gate] = Path(raw_path)
    return result


def _assert_runtime_ready(
    runtime_raw: dict[str, Any],
    required_variants: frozenset[str],
) -> None:
    variants = runtime_raw.get("platformVariants")
    locks = runtime_raw.get("releaseLocks")
    if not isinstance(variants, dict) or not isinstance(locks, dict):
        raise PromotionError("promotion_runtime_metadata_invalid")
    for variant in sorted(required_variants):
        if variant not in variants or variant not in locks:
            raise PromotionError("promotion_runtime_variant_missing:" + variant)
        expected_status = (
            "qualified-hardware"
            if variant.endswith("-cuda")
            else "qualified-hosted-cpu"
        )
        if variants[variant].get("status") != expected_status:
            raise PromotionError("promotion_runtime_variant_not_qualified:" + variant)
        if locks[variant].get("status") != "qualified-offline-lock":
            raise PromotionError("promotion_runtime_lock_not_qualified:" + variant)


def build_promoted_metadata(
    *,
    manifest_raw: dict[str, Any],
    qualification_raw: dict[str, Any],
    runtime_raw: dict[str, Any],
    gate_evidence: dict[str, Path],
    expected_source_commit: str,
    acceptance_profile_sha256: str,
    acceptance_profile: dict[str, Any],
    quality_corpus_manifest: Path,
    quality_case_evidence: dict[str, Path],
    quality_ground_truth: dict[str, Path],
    expected_mavi_build: str,
    deployment_profile_id: str,
    deployment_profile_policy_sha256: str,
    required_gates: frozenset[str],
    required_variants: frozenset[str],
    current_manifest_bytes: bytes | None = None,
) -> tuple[bytes, bytes]:
    verification_status = manifest_raw.get("verificationStatus")
    qualification_id = qualification_raw.get("qualificationId")
    if not isinstance(qualification_id, str) or not qualification_id:
        raise PromotionError("promotion_qualification_id_invalid")

    if verification_status == "unverified":
        if manifest_raw.get("qualificationId") is not None:
            raise PromotionError("promotion_manifest_pending_qualification_unexpected")
        if qualification_raw.get("overallResult") != "pending":
            raise PromotionError("promotion_initial_qualification_not_pending")
        target_manifest_bytes = build_target_manifest(
            manifest_raw,
            qualification_id,
        )
    elif verification_status == "verified":
        if manifest_raw.get("qualificationId") != qualification_id:
            raise PromotionError("promotion_manifest_qualification_mismatch")
        target_manifest_bytes = (
            current_manifest_bytes
            if current_manifest_bytes is not None
            else canonical_json(manifest_raw)
        )
        try:
            current_manifest_value = json.loads(
                target_manifest_bytes.decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PromotionError(
                "promotion_current_manifest_bytes_invalid"
            ) from exc
        if current_manifest_value != manifest_raw:
            raise PromotionError(
                "promotion_current_manifest_bytes_mismatch"
            )
    else:
        raise PromotionError("promotion_manifest_status_invalid")

    target_manifest_sha = target_sha256_bytes(
        target_manifest_bytes
    )
    if (
        verification_status == "verified"
        and qualification_raw.get("modelManifestSha256")
        != target_manifest_sha
    ):
        raise PromotionError(
            "promotion_verified_manifest_hash_mismatch"
        )

    current_gates = qualification_raw.get("requiredGates")
    current_evidence = qualification_raw.get("evidence")
    if (
        not isinstance(current_gates, dict)
        or set(current_gates)
        != MANDATORY_QUALIFICATION_GATES
    ):
        raise PromotionError("promotion_gate_set_changed")
    if not isinstance(current_evidence, dict):
        raise PromotionError("promotion_evidence_map_invalid")

    qualified_profiles = qualification_raw.get(
        "qualifiedProfiles", []
    )
    profile_qualifications = qualification_raw.get(
        "profileQualifications", {}
    )
    if (
        not isinstance(qualified_profiles, list)
        or len(set(qualified_profiles)) != len(qualified_profiles)
        or not isinstance(profile_qualifications, dict)
        or set(qualified_profiles) != set(profile_qualifications)
    ):
        raise PromotionError(
            "promotion_existing_profile_index_invalid"
        )
    if verification_status == "unverified" and qualified_profiles:
        raise PromotionError(
            "promotion_unverified_manifest_has_qualified_profiles"
        )

    _assert_runtime_ready(runtime_raw, required_variants)

    missing = sorted(required_gates - set(gate_evidence))
    if missing:
        raise PromotionError(
            "promotion_evidence_missing:" + ",".join(missing)
        )
    if set(gate_evidence) != required_gates:
        raise PromotionError("promotion_evidence_set_invalid")

    _validate_offline_aggregate_bindings(
        gate_evidence,
        required_variants,
    )
    evidence: dict[str, dict[str, str]] = dict(
        current_evidence
    )
    gates = dict(current_gates)
    profile_evidence: dict[str, dict[str, str]] = {}

    runtime_variant = next(iter(required_variants))
    for gate, path in sorted(gate_evidence.items()):
        if gate in {
            "windows-offline-install",
            "linux-offline-install",
        }:
            offline_value = _load_dict(
                path,
                "promotion_offline_evidence_invalid:" + gate,
            )
            if (
                offline_value.get("deploymentProfile")
                != deployment_profile_id
                or offline_value.get(
                    "deploymentProfilePolicySha256"
                )
                != deployment_profile_policy_sha256
            ):
                raise PromotionError(
                    "promotion_offline_profile_binding_mismatch:"
                    + gate
                )

        gate_record = load_gate_evidence(
            path,
            gate=gate,
            expected_source_commit=expected_source_commit,
            target_verified_manifest_sha256=target_manifest_sha,
            acceptance_profile_sha256=acceptance_profile_sha256,
            acceptance_profile=acceptance_profile,
            quality_corpus_manifest=quality_corpus_manifest,
            quality_case_evidence=quality_case_evidence,
            quality_ground_truth=quality_ground_truth,
            expected_mavi_build=expected_mavi_build,
            deployment_profile_id=deployment_profile_id,
            deployment_profile_policy_sha256=(
                deployment_profile_policy_sha256
            ),
            runtime_variant=runtime_variant,
        )
        evidence[gate] = gate_record
        profile_evidence[gate] = gate_record
        gates[gate] = "passed"

    if any(
        gates.get(gate) != "passed"
        for gate in required_gates
    ):
        raise PromotionError("promotion_gate_not_passed")
    if any(
        gate not in profile_evidence
        for gate in required_gates
    ):
        raise PromotionError(
            "promotion_profile_gate_evidence_missing"
        )

    updated_profile_qualifications = dict(
        profile_qualifications
    )
    updated_profile_qualifications[
        deployment_profile_id
    ] = {
        "deploymentProfilePolicySha256":
            deployment_profile_policy_sha256,
        "runtimeVariant": runtime_variant,
        "evidence": {
            key: profile_evidence[key]
            for key in sorted(profile_evidence)
        },
    }
    updated_qualified_profiles = sorted(
        updated_profile_qualifications
    )

    qualification = dict(qualification_raw)
    qualification["modelManifestSha256"] = target_manifest_sha
    qualification["requiredGates"] = gates
    qualification["evidence"] = {
        key: evidence[key]
        for key in sorted(evidence)
    }
    qualification["qualifiedProfiles"] = (
        updated_qualified_profiles
    )
    qualification["profileQualifications"] = {
        key: updated_profile_qualifications[key]
        for key in updated_qualified_profiles
    }
    qualification["overallResult"] = (
        "passed"
        if all(
            status == "passed"
            for status in gates.values()
        )
        else "pending"
    )

    return target_manifest_bytes, canonical_json(qualification)



def validate_promoted_outputs(
    *,
    model_root: Path,
    manifest_bytes: bytes,
    qualification_bytes: bytes,
    profile_path: Path,
    runtime_profile_path: Path,
    deployment_profiles_by_id: dict[
        str, deployment_profiles.DeploymentProfile
    ],
    deployment_profile_policy_sha256: str,
) -> None:
    try:
        qualification_raw = json.loads(
            qualification_bytes.decode("utf-8")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromotionError(
            "promotion_qualification_output_invalid"
        ) from exc
    qualified_profiles = qualification_raw.get(
        "qualifiedProfiles"
    )
    if (
        not isinstance(qualified_profiles, list)
        or not qualified_profiles
    ):
        raise PromotionError(
            "promotion_qualified_profiles_empty"
        )

    with tempfile.TemporaryDirectory(
        prefix="mavi-task18-promotion-"
    ) as directory:
        root = Path(directory)
        manifest_path = root / "manifest.json"
        qualification_path = root / "qualification.json"
        manifest_path.write_bytes(manifest_bytes)
        qualification_path.write_bytes(
            qualification_bytes
        )

        for profile_id in qualified_profiles:
            selected = deployment_profiles_by_id.get(
                profile_id
            )
            if selected is None:
                raise PromotionError(
                    "promotion_profile_unknown:"
                    + str(profile_id)
                )
            try:
                verify_release_selection(
                    model_root=model_root,
                    manifest_path=manifest_path,
                    profile_path=profile_path,
                    runtime_profile_path=runtime_profile_path,
                    qualification_path=qualification_path,
                    allow_unverified=False,
                    required_profile=profile_id,
                    required_gates=(
                        selected.qualification_gates
                    ),
                    required_runtime_variant=(
                        selected.runtime_variant
                    ),
                    required_deployment_profile_policy_sha256=(
                        deployment_profile_policy_sha256
                    ),
                )
            except ReleaseMetadataError as exc:
                raise PromotionError(
                    "promotion_release_validation_failed:"
                    + profile_id
                    + ":"
                    + exc.code
                ) from exc



def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--pipeline-profile", type=Path, required=True)
    parser.add_argument("--runtime-profile", type=Path, required=True)
    parser.add_argument("--acceptance-profile", type=Path, required=True)
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
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--expected-mavi-build", required=True)
    parser.add_argument("--quality-corpus-manifest", type=Path, required=True)
    parser.add_argument("--quality-case-evidence", action="append", default=[])
    parser.add_argument("--quality-ground-truth", action="append", default=[])
    parser.add_argument("--gate-evidence", action="append", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    try:
        if not args.expected_mavi_build or args.expected_mavi_build == "unknown-development":
            raise PromotionError("promotion_mavi_build_not_frozen")
        gate_evidence = parse_gate_arguments(args.gate_evidence)
        quality_case_evidence = quality_corpus.parse_named_paths(
            args.quality_case_evidence,
            "promotion_quality_case_argument_invalid",
        )
        quality_ground_truth = quality_corpus.parse_named_paths(
            args.quality_ground_truth,
            "promotion_quality_ground_truth_argument_invalid",
        )
        manifest_raw = read_release_json(args.manifest, code="model_manifest_invalid")
        qualification_raw = read_release_json(args.qualification, code="qualification_record_invalid")
        runtime_raw = read_release_json(args.runtime_profile, code="runtime_profile_invalid")
        acceptance_profile, acceptance_profile_sha256 = _canonical_policy(args.acceptance_profile)
        (
            deployment_profiles_by_id,
            deployment_policy_sha256,
        ) = deployment_profiles.load_policy(
            args.deployment_profile_policy
        )
        selected_profile = deployment_profiles_by_id[
            args.deployment_profile
        ]
        required_gates = (
            selected_profile.qualification_gates
        )
        required_variants = (
            selected_profile.required_runtime_variants
        )

        current_qualification = load_qualification_record(
            args.qualification
        )
        load_runtime_profile(args.runtime_profile)

        if manifest_raw.get("verificationStatus") == "verified":
            if not current_qualification.qualified_profiles:
                raise PromotionError(
                    "promotion_verified_manifest_has_no_profile"
                )
            for profile_id in (
                current_qualification.qualified_profiles
            ):
                existing = deployment_profiles_by_id.get(
                    profile_id
                )
                existing_record = (
                    current_qualification
                    .profile_qualifications.get(profile_id)
                )
                if (
                    existing is None
                    or existing_record is None
                ):
                    raise PromotionError(
                        "promotion_existing_profile_unknown:"
                        + profile_id
                    )
                if (
                    existing_record
                    .deployment_profile_policy_sha256
                    != deployment_policy_sha256
                ):
                    raise PromotionError(
                        "promotion_existing_profile_policy_stale:"
                        + profile_id
                    )
                verify_release_selection(
                    model_root=args.model_root,
                    manifest_path=args.manifest,
                    profile_path=args.pipeline_profile,
                    runtime_profile_path=args.runtime_profile,
                    qualification_path=args.qualification,
                    allow_unverified=False,
                    required_profile=profile_id,
                    required_gates=(
                        existing.qualification_gates
                    ),
                    required_runtime_variant=(
                        existing.runtime_variant
                    ),
                    required_deployment_profile_policy_sha256=(
                        deployment_policy_sha256
                    ),
                )
        else:
            verify_release_selection(
                model_root=args.model_root,
                manifest_path=args.manifest,
                profile_path=args.pipeline_profile,
                runtime_profile_path=args.runtime_profile,
                qualification_path=args.qualification,
                allow_unverified=True,
            )

        manifest_bytes, qualification_bytes = build_promoted_metadata(
            manifest_raw=manifest_raw,
            qualification_raw=qualification_raw,
            runtime_raw=runtime_raw,
            gate_evidence=gate_evidence,
            expected_source_commit=args.source_commit,
            acceptance_profile_sha256=acceptance_profile_sha256,
            acceptance_profile=acceptance_profile,
            quality_corpus_manifest=args.quality_corpus_manifest,
            quality_case_evidence=quality_case_evidence,
            quality_ground_truth=quality_ground_truth,
            expected_mavi_build=args.expected_mavi_build,
            deployment_profile_id=selected_profile.profile_id,
            deployment_profile_policy_sha256=deployment_policy_sha256,
            required_gates=required_gates,
            required_variants=required_variants,
            current_manifest_bytes=args.manifest.read_bytes(),
        )
        validate_promoted_outputs(
            model_root=args.model_root,
            manifest_bytes=manifest_bytes,
            qualification_bytes=qualification_bytes,
            profile_path=args.pipeline_profile,
            runtime_profile_path=args.runtime_profile,
            deployment_profiles_by_id=(
                deployment_profiles_by_id
            ),
            deployment_profile_policy_sha256=(
                deployment_policy_sha256
            ),
        )
    except (
        PromotionError,
        ReleaseMetadataError,
        PolicyIdentityError,
        quality_corpus.QualityCorpusError,
    ) as exc:
        code = getattr(exc, "code", str(exc))
        print(json.dumps({"ok": False, "code": code}, sort_keys=True))
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_out = args.output_dir / args.manifest.name
    qualification_out = args.output_dir / args.qualification.name
    if manifest_out.exists() or qualification_out.exists():
        print(json.dumps({"ok": False, "code": "promotion_output_exists"}, sort_keys=True))
        return 2
    manifest_out.write_bytes(manifest_bytes)
    qualification_out.write_bytes(qualification_bytes)
    print(json.dumps({
        "ok": True,
        "manifestSha256": sha256_file(manifest_out),
        "qualificationSha256": sha256_file(qualification_out),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
