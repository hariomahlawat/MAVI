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
from compute_target_verified_manifest import build_target_manifest, sha256_bytes as target_sha256_bytes  # noqa: E402
from jsonschema import Draft202012Validator  # noqa: E402


class PromotionError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def canonical_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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
) -> None:
    _validate_schema(value, "offline-variant-evidence.schema.json")
    if value.get("variant") != gate:
        raise PromotionError("promotion_variant_evidence_gate_mismatch:" + gate)
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
) -> None:
    _validate_schema(value, "offline-install-evidence.schema.json")
    evidence_verifier.verify_offline_install(
        value,
        expected_source_commit=source_commit,
    )
    expected_os = "windows" if gate == "windows-offline-install" else "linux"
    if value.get("os") != expected_os:
        raise PromotionError("promotion_offline_os_mismatch:" + gate)
    if value.get("bundleMode") != "qualification-candidate":
        raise PromotionError("promotion_offline_evidence_not_candidate:" + gate)


def _validate_quality_evidence(
    value: dict[str, Any],
    source_commit: str,
    acceptance_profile_sha256: str,
) -> None:
    _validate_schema(value, "phase1-acceptance-evidence.schema.json")
    evidence_verifier.verify_acceptance(
        value,
        expected_source_commit=source_commit,
        expected_acceptance_profile_sha256=acceptance_profile_sha256,
    )
    metrics = value.get("metrics")
    if (
        value.get("mode") != "formal"
        or not isinstance(metrics, dict)
        or metrics.get("mode") != "qualification"
        or metrics.get("qualification", {}).get("passed") is not True
    ):
        raise PromotionError("promotion_quality_not_formally_qualified")
    per_class = metrics.get("perClass")
    if not isinstance(per_class, dict):
        raise PromotionError("promotion_quality_per_class_missing")
    for object_class in ("Person", "Vehicle"):
        row = per_class.get(object_class)
        if not isinstance(row, dict) or row.get("groundTruthEventCount", 0) <= 0:
            raise PromotionError("promotion_quality_class_coverage_missing:" + object_class)


def _validate_performance_evidence(
    value: dict[str, Any],
    acceptance_profile_sha256: str,
) -> None:
    _validate_schema(value, "recovery-performance-evidence.schema.json")
    if value.get("acceptanceProfileSha256") != acceptance_profile_sha256:
        raise PromotionError("promotion_performance_profile_mismatch")
    if not evidence_passed(value):
        raise PromotionError("promotion_performance_not_passed")


def validate_gate_evidence(
    gate: str,
    value: dict[str, Any],
    *,
    source_commit: str,
    target_verified_manifest_sha256: str,
    acceptance_profile_sha256: str,
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
        _validate_platform_variant_evidence(gate, value)
        return
    if gate in {"windows-offline-install", "linux-offline-install"}:
        _validate_offline_os_evidence(gate, value, source_commit)
        return
    if gate == "cctv-quality-baseline":
        _validate_quality_evidence(value, source_commit, acceptance_profile_sha256)
        return
    if gate == "linux-nvidia-recovery-performance":
        _validate_performance_evidence(value, acceptance_profile_sha256)
        return
    raise PromotionError("promotion_gate_unknown:" + gate)


def load_gate_evidence(
    path: Path,
    *,
    gate: str,
    expected_source_commit: str,
    target_verified_manifest_sha256: str,
    acceptance_profile_sha256: str,
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


def _assert_runtime_ready(runtime_raw: dict[str, Any]) -> None:
    if runtime_raw.get("qualificationStatus") != "qualified":
        raise PromotionError("promotion_runtime_not_qualified")
    variants = runtime_raw.get("platformVariants")
    locks = runtime_raw.get("releaseLocks")
    required_variants = {
        "windows-x86_64-cpu",
        "windows-x86_64-cuda",
        "linux-x86_64-cpu",
        "linux-x86_64-cuda",
    }
    if not isinstance(variants, dict) or set(variants) != required_variants:
        raise PromotionError("promotion_runtime_variants_incomplete")
    if not isinstance(locks, dict) or set(locks) != required_variants:
        raise PromotionError("promotion_runtime_locks_incomplete")
    for variant in required_variants:
        expected_status = "qualified-hardware" if variant.endswith("-cuda") else "qualified-hosted-cpu"
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
) -> tuple[bytes, bytes]:
    if manifest_raw.get("verificationStatus") != "unverified" or manifest_raw.get("qualificationId") is not None:
        raise PromotionError("promotion_manifest_not_pending")
    if qualification_raw.get("overallResult") != "pending":
        raise PromotionError("promotion_qualification_not_pending")

    current_gates = qualification_raw.get("requiredGates")
    current_evidence = qualification_raw.get("evidence")
    if not isinstance(current_gates, dict) or set(current_gates) != MANDATORY_QUALIFICATION_GATES:
        raise PromotionError("promotion_gate_set_changed")
    if not isinstance(current_evidence, dict):
        raise PromotionError("promotion_evidence_map_invalid")

    _assert_runtime_ready(runtime_raw)

    qualification_id = qualification_raw.get("qualificationId")
    if not isinstance(qualification_id, str) or not qualification_id:
        raise PromotionError("promotion_qualification_id_invalid")
    target_manifest_bytes = build_target_manifest(manifest_raw, qualification_id)
    target_manifest_sha = target_sha256_bytes(target_manifest_bytes)

    missing = [
        gate
        for gate in sorted(MANDATORY_QUALIFICATION_GATES)
        if current_gates[gate] != "passed" and gate not in gate_evidence
    ]
    if missing:
        raise PromotionError("promotion_evidence_missing:" + ",".join(missing))

    evidence = dict(current_evidence)
    gates = dict(current_gates)
    for gate, path in sorted(gate_evidence.items()):
        evidence[gate] = load_gate_evidence(
            path,
            gate=gate,
            expected_source_commit=expected_source_commit,
            target_verified_manifest_sha256=target_manifest_sha,
            acceptance_profile_sha256=acceptance_profile_sha256,
        )
        gates[gate] = "passed"

    if any(gates.get(gate) != "passed" for gate in MANDATORY_QUALIFICATION_GATES):
        raise PromotionError("promotion_gate_not_passed")
    if any(gate not in evidence for gate in MANDATORY_QUALIFICATION_GATES):
        raise PromotionError("promotion_gate_evidence_missing")

    manifest_bytes = target_manifest_bytes
    final_manifest_sha = target_manifest_sha

    qualification = dict(qualification_raw)
    qualification["modelManifestSha256"] = final_manifest_sha
    qualification["requiredGates"] = gates
    qualification["evidence"] = {key: evidence[key] for key in sorted(evidence)}
    qualification["overallResult"] = "passed"
    qualification_bytes = canonical_json(qualification)
    return manifest_bytes, qualification_bytes


def validate_promoted_outputs(
    *,
    model_root: Path,
    manifest_bytes: bytes,
    qualification_bytes: bytes,
    profile_path: Path,
    runtime_profile_path: Path,
) -> None:
    with tempfile.TemporaryDirectory(prefix="mavi-task17-promotion-") as directory:
        root = Path(directory)
        manifest_path = root / "manifest.json"
        qualification_path = root / "qualification.json"
        manifest_path.write_bytes(manifest_bytes)
        qualification_path.write_bytes(qualification_bytes)
        try:
            verify_release_selection(
                model_root=model_root,
                manifest_path=manifest_path,
                profile_path=profile_path,
                runtime_profile_path=runtime_profile_path,
                qualification_path=qualification_path,
                allow_unverified=False,
            )
        except ReleaseMetadataError as exc:
            raise PromotionError("promotion_release_validation_failed:" + exc.code) from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--pipeline-profile", type=Path, required=True)
    parser.add_argument("--runtime-profile", type=Path, required=True)
    parser.add_argument("--acceptance-profile", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--gate-evidence", action="append", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    try:
        gate_evidence = parse_gate_arguments(args.gate_evidence)
        manifest_raw = read_release_json(args.manifest, code="model_manifest_invalid")
        qualification_raw = read_release_json(args.qualification, code="qualification_record_invalid")
        runtime_raw = read_release_json(args.runtime_profile, code="runtime_profile_invalid")
        acceptance_profile_sha256 = sha256_file(args.acceptance_profile)

        # Validate the current pending relationship before constructing promotion.
        verify_release_selection(
            model_root=args.model_root,
            manifest_path=args.manifest,
            profile_path=args.pipeline_profile,
            runtime_profile_path=args.runtime_profile,
            qualification_path=args.qualification,
            allow_unverified=True,
        )
        load_qualification_record(args.qualification)
        load_runtime_profile(args.runtime_profile)

        manifest_bytes, qualification_bytes = build_promoted_metadata(
            manifest_raw=manifest_raw,
            qualification_raw=qualification_raw,
            runtime_raw=runtime_raw,
            gate_evidence=gate_evidence,
            expected_source_commit=args.source_commit,
            acceptance_profile_sha256=acceptance_profile_sha256,
        )
        validate_promoted_outputs(
            model_root=args.model_root,
            manifest_bytes=manifest_bytes,
            qualification_bytes=qualification_bytes,
            profile_path=args.pipeline_profile,
            runtime_profile_path=args.runtime_profile,
        )
    except (PromotionError, ReleaseMetadataError) as exc:
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
