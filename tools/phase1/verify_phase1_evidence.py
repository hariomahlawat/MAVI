#!/usr/bin/env python3
"""Validate transferred Task-17 evidence without mutating it."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


class EvidenceError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError("evidence_json_invalid") from exc
    if not isinstance(value, dict):
        raise EvidenceError("evidence_root_invalid")
    return value


def _validate_schema(value: dict[str, Any], schema_path: Path) -> None:
    schema = _load(schema_path)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        raise EvidenceError("evidence_schema_invalid:" + "/".join(str(x) for x in errors[0].absolute_path))


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_acceptance(
    value: dict[str, Any],
    *,
    expected_source_commit: str | None = None,
    expected_acceptance_profile_sha256: str | None = None,
    expected_qualification_corpus_sha256: str | None = None,
) -> None:
    if expected_source_commit is not None and value["sourceCommit"] != expected_source_commit:
        raise EvidenceError("acceptance_source_commit_mismatch")
    if (
        expected_acceptance_profile_sha256 is not None
        and value["acceptanceProfileSha256"] != expected_acceptance_profile_sha256
    ):
        raise EvidenceError("acceptance_profile_hash_mismatch")
    if value["attestation"]["processingRunId"] != value["processing"]["processingRunId"]:
        raise EvidenceError("acceptance_processing_run_identity_mismatch")
    if not value["attestation"]["comparisonPassed"]:
        raise EvidenceError("acceptance_attestation_mismatch")
    source = value["sourceMedia"]
    if not source["matched"] or len({source["localSha256"], source["streamedSha256"], source["etagSha256"]}) != 1:
        raise EvidenceError("acceptance_source_integrity_failed")
    if value["camera"]["id"] != value["video"]["cameraId"]:
        raise EvidenceError("acceptance_camera_video_mismatch")
    if value["tracks"]["orphanCount"] != 0:
        raise EvidenceError("acceptance_orphan_track_detected")
    if len(value["tracks"]["trackIds"]) != value["tracks"]["total"]:
        raise EvidenceError("acceptance_track_identity_count_mismatch")
    if not value["sourceRange"]["passed"] or value["sourceRange"]["statusCode"] != 206:
        raise EvidenceError("acceptance_source_range_failed")

    if value["mode"] == "formal":
        gt = value.get("groundTruth")
        if gt is None or not gt["bindingPassed"]:
            raise EvidenceError("acceptance_ground_truth_binding_failed")
        if gt["videoSha256"] != source["localSha256"] or gt["durationMs"] != value["video"]["durationMs"]:
            raise EvidenceError("acceptance_ground_truth_media_mismatch")
        if (
            expected_qualification_corpus_sha256 is not None
            and gt["corpusManifestSha256"] != expected_qualification_corpus_sha256
        ):
            raise EvidenceError("acceptance_qualification_corpus_mismatch")
        if value["tracks"]["total"] <= 0 or value["tracks"]["detailsResolved"] <= 0:
            raise EvidenceError("acceptance_formal_no_tracks")
        reads = value["evidenceReads"]
        if reads["attempted"] <= 0 or reads["passed"] <= 0 or reads["representativeArtifactId"] is None:
            raise EvidenceError("acceptance_formal_no_evidence")
        if reads["streamedSha256"] != reads["etagSha256"]:
            raise EvidenceError("acceptance_representative_integrity_failed")
        if value["metrics"] is None:
            raise EvidenceError("acceptance_formal_metrics_missing")

    if value["result"]["passed"] and value["result"]["failureCodes"]:
        raise EvidenceError("acceptance_passed_with_failures")
    if not value["result"]["passed"]:
        raise EvidenceError("acceptance_result_failed")


def verify_offline_install(
    value: dict[str, Any],
    *,
    expected_source_commit: str | None = None,
    expected_acceptance_profile_sha256: str | None = None,
) -> None:
    if expected_source_commit is not None and value["sourceCommit"] != expected_source_commit:
        raise EvidenceError("offline_source_commit_mismatch")
    if (
        expected_acceptance_profile_sha256 is not None
        and value["acceptanceProfileSha256"] != expected_acceptance_profile_sha256
    ):
        raise EvidenceError("offline_acceptance_profile_mismatch")

    os_name = value["os"]
    required = {
        "windows": {"windows-x86_64-cpu", "windows-x86_64-cuda"},
        "linux": {"linux-x86_64-cpu", "linux-x86_64-cuda"},
    }[os_name]
    actual = {item["variant"] for item in value["variants"]}
    if actual != required:
        raise EvidenceError("offline_variant_coverage_incomplete")

    strict_tokens = ("--no-index", "--only-binary=:all:", "--require-hashes", "--find-links")
    for item in value["variants"]:
        if not item["variant"].startswith(os_name + "-"):
            raise EvidenceError("offline_variant_os_mismatch")
        if any(token not in item["installCommand"] for token in strict_tokens):
            raise EvidenceError("offline_install_command_not_strict")
        if item["expectedHostCompatibility"] != item["observedHostCompatibility"]:
            raise EvidenceError("offline_host_compatibility_mismatch")
        required_true = (
            "pipCheckPassed", "runtimeStarted", "realInferencePassed",
            "workerFlowPassed", "outboundNetworkUnavailable"
        )
        if item["installExitCode"] != 0 or any(not item[name] for name in required_true):
            raise EvidenceError("offline_variant_not_proven")
        if item["firstRunDownloadObserved"]:
            raise EvidenceError("offline_first_run_download_detected")
        if item["variant"].endswith("-cpu") and item["actualDevice"] != "cpu":
            raise EvidenceError("offline_cpu_device_mismatch")
        if item["variant"].endswith("-cuda") and not item["actualDevice"].startswith("cuda:"):
            raise EvidenceError("offline_cuda_device_mismatch")
        if item["result"] != "passed":
            raise EvidenceError("offline_variant_failed")

    if value["result"] != "passed":
        raise EvidenceError("offline_os_gate_failed")


def verify_manifest(manifest_path: Path, root: Path) -> None:
    value = _load(manifest_path)
    if value.get("schemaVersion") != "mavi-evidence-package-manifest-v1":
        raise EvidenceError("evidence_manifest_schema_invalid")
    files = value.get("files")
    if not isinstance(files, list) or not files:
        raise EvidenceError("evidence_manifest_files_invalid")
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "sizeBytes", "sha256"}:
            raise EvidenceError("evidence_manifest_entry_invalid")
        relative = item["path"]
        if not isinstance(relative, str) or not relative or relative in seen or relative.startswith(("/", "\\")) or ".." in Path(relative).parts:
            raise EvidenceError("evidence_manifest_path_invalid")
        seen.add(relative)
        target = (root / relative).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError as exc:
            raise EvidenceError("evidence_manifest_path_escape") from exc
        if not target.is_file() or target.stat().st_size != item["sizeBytes"] or _sha(target) != item["sha256"]:
            raise EvidenceError("evidence_manifest_integrity_failed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acceptance", type=Path)
    parser.add_argument("--offline-install", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--package-root", type=Path)
    parser.add_argument("--expected-source-commit")
    parser.add_argument("--expected-acceptance-profile-sha256")
    parser.add_argument("--expected-qualification-corpus-sha256")
    parser.add_argument("--acceptance-schema", type=Path, default=Path(__file__).with_name("phase1-acceptance-evidence.schema.json"))
    parser.add_argument("--offline-schema", type=Path, default=Path(__file__).with_name("offline-install-evidence.schema.json"))
    args = parser.parse_args()

    if not any((args.acceptance, args.offline_install, args.manifest)):
        parser.error("at least one evidence input is required")
    if args.manifest and not args.package_root:
        parser.error("--package-root is required with --manifest")

    try:
        if args.acceptance:
            value = _load(args.acceptance)
            _validate_schema(value, args.acceptance_schema)
            verify_acceptance(
                value,
                expected_source_commit=args.expected_source_commit,
                expected_acceptance_profile_sha256=args.expected_acceptance_profile_sha256,
                expected_qualification_corpus_sha256=args.expected_qualification_corpus_sha256,
            )
        if args.offline_install:
            value = _load(args.offline_install)
            _validate_schema(value, args.offline_schema)
            verify_offline_install(
                value,
                expected_source_commit=args.expected_source_commit,
                expected_acceptance_profile_sha256=args.expected_acceptance_profile_sha256,
            )
        if args.manifest:
            verify_manifest(args.manifest, args.package_root)
    except EvidenceError as exc:
        print(json.dumps({"ok": False, "code": exc.code}, sort_keys=True))
        return 2

    print(json.dumps({"ok": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
