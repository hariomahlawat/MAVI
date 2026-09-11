#!/usr/bin/env python3
"""Validate the MAVI repository's architecture and offline-production guardrails."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import jsonschema
except ImportError:  # pragma: no cover - developer environment guard
    jsonschema = None

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PATHS = [
    "MAVI.sln",
    "AGENTS.md",
    "CLAUDE.md",
    "src/platform/Mavi.Domain/Mavi.Domain.csproj",
    "src/platform/Mavi.Contracts/Mavi.Contracts.csproj",
    "src/platform/Mavi.Application/Mavi.Application.csproj",
    "src/platform/Mavi.Infrastructure/Mavi.Infrastructure.csproj",
    "src/platform/Mavi.Api/Mavi.Api.csproj",
    "src/web/mavi-web/package.json",
    "src/vision/pyproject.toml",
    ".gitattributes",
    "models/manifests/rtmdet-m-coco-phase1-v1.json",
    "models/qualifications/rtmdet-m-coco-phase1-v1.json",
    "src/vision/config/pipelines/phase1-detection-tracking-v1.json",
    "src/vision/runtime/mmdetection-phase1-v1/runtime.json",
    "contracts/schemas/vision-job-lease-v2.schema.json",
    "contracts/schemas/vision-result.schema.json",
    "contracts/schemas/worker-health-v2.schema.json",
]

ALLOWED_REFERENCES = {
    "Mavi.Domain": set(),
    "Mavi.Contracts": set(),
    "Mavi.Application": {"Mavi.Domain", "Mavi.Contracts"},
    "Mavi.Infrastructure": {"Mavi.Application", "Mavi.Domain", "Mavi.Contracts"},
    "Mavi.Api": {"Mavi.Application", "Mavi.Infrastructure", "Mavi.Contracts"},
}

PROHIBITED_TRACKED_SUFFIXES = {
    ".pt", ".pth", ".onnx", ".engine", ".plan", ".safetensors", ".gguf",
    ".mp4", ".avi", ".mov", ".mkv", ".m4v", ".webm",
    ".pem", ".key", ".pfx", ".p12",
}

PRODUCTION_SCAN_ROOTS = [
    ROOT / "src/platform",
    ROOT / "src/vision/mavi_vision",
    ROOT / "src/web/mavi-web/src",
]
PRODUCTION_SCAN_FILES = [ROOT / "src/web/mavi-web/index.html"]
DEVELOPMENT_ONLY_FILES = {
    ROOT / "src/platform/Mavi.Api/Properties/launchSettings.json",
}
URL_PATTERN = re.compile(r"https?://", re.IGNORECASE)

VISION_ROOT = ROOT / "src/vision"
MODEL_MANIFEST = ROOT / "models/manifests/rtmdet-m-coco-phase1-v1.json"
QUALIFICATION_RECORD = ROOT / "models/qualifications/rtmdet-m-coco-phase1-v1.json"
PIPELINE_PROFILE = ROOT / "src/vision/config/pipelines/phase1-detection-tracking-v1.json"
RUNTIME_PROFILE = ROOT / "src/vision/runtime/mmdetection-phase1-v1/runtime.json"
RELEASE_TEXT_ROOTS = [
    ROOT / "models/manifests",
    ROOT / "models/qualifications",
    ROOT / "src/vision/config/pipelines",
    ROOT / "src/vision/runtime",
]


def fail(message: str, errors: list[str]) -> None:
    errors.append(message)


def check_required_paths(errors: list[str]) -> None:
    for relative in REQUIRED_PATHS:
        if not (ROOT / relative).exists():
            fail(f"Missing required path: {relative}", errors)


def check_project_references(errors: list[str]) -> None:
    platform = ROOT / "src/platform"
    for project, expected in ALLOWED_REFERENCES.items():
        project_file = platform / project / f"{project}.csproj"
        if not project_file.exists():
            continue
        tree = ET.parse(project_file)
        actual = {
            Path(ref.attrib["Include"].replace("\\", "/")).stem
            for ref in tree.findall(".//ProjectReference")
        }
        if actual != expected:
            fail(
                f"{project} references {sorted(actual)}; expected {sorted(expected)}",
                errors,
            )


def check_contracts(errors: list[str]) -> None:
    if jsonschema is None:
        fail("Python package 'jsonschema' is required to validate contract examples.", errors)
        return

    stems = [
        "vision-job-lease-request-v2", "vision-job-lease-v2", "vision-job-heartbeat-v2",
        "vision-job-heartbeat-response-v2", "vision-job-fail-v2", "worker-health-v2", "vision-result",
    ]
    pairs = [(stem, f"{stem}.example.json") for stem in stems]
    for stem, example_name in pairs:
        schema = json.loads((ROOT / "contracts/schemas" / f"{stem}.schema.json").read_text())
        example = json.loads((ROOT / "contracts/examples" / example_name).read_text())
        try:
            jsonschema.validate(instance=example, schema=schema, format_checker=jsonschema.FormatChecker())
        except jsonschema.ValidationError as exc:
            fail(f"Contract example {example_name} is invalid: {exc.message}", errors)

    vectors = json.loads((ROOT / "contracts/test-vectors/control-plane-v2-invalid.json").read_text())
    for vector in vectors:
        schema = json.loads((ROOT / "contracts/schemas" / f"{vector['schema']}.schema.json").read_text())
        try:
            jsonschema.validate(instance=vector["payload"], schema=schema, format_checker=jsonschema.FormatChecker())
        except jsonschema.ValidationError:
            continue
        fail(f"Invalid contract vector was accepted: {vector['name']}", errors)


def check_production_urls(errors: list[str]) -> None:
    files = [
        path
        for path in tracked_files()
        if path not in DEVELOPMENT_ONLY_FILES
        and (
            path in PRODUCTION_SCAN_FILES
            or any(path.is_relative_to(root) for root in PRODUCTION_SCAN_ROOTS)
        )
    ]

    for path in files:
        if path.suffix.lower() not in {".cs", ".json", ".py", ".ts", ".tsx", ".css", ".html"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if URL_PATTERN.search(text):
            fail(f"Production source contains an Internet URL: {path.relative_to(ROOT)}", errors)


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / item.decode() for item in result.stdout.split(b"\0") if item]


def check_tracked_binaries_and_secrets(errors: list[str]) -> None:
    for path in tracked_files():
        if path.suffix.lower() in PROHIBITED_TRACKED_SUFFIXES:
            fail(f"Prohibited model/media/secret file is tracked: {path.relative_to(ROOT)}", errors)
        if path.name in {".env", "secrets.json"}:
            fail(f"Prohibited secret file is tracked: {path.relative_to(ROOT)}", errors)


def check_vision_release_metadata(errors: list[str]) -> None:
    """Validate Task-10 release metadata without claiming pending gates passed."""
    if str(VISION_ROOT) not in sys.path:
        sys.path.insert(0, str(VISION_ROOT))

    try:
        from mavi_vision.runtime.manifest import (
            ReleaseMetadataError,
            load_model_manifest,
            sha256_release_file,
            validate_release_text_file,
        )
        from mavi_vision.runtime.profile import (
            load_pipeline_profile,
            validate_profile_against_manifest,
        )
        from mavi_vision.runtime.qualification import (
            load_qualification_record,
            load_runtime_identity,
            verify_qualification_relationships,
        )
    except ImportError as exc:
        fail(f"Vision release metadata tooling could not be imported: {exc}", errors)
        return

    release_files = [
        file_path
        for file_path in tracked_files()
        if file_path.suffix.lower() in {".json", ".lock"}
        and any(file_path.is_relative_to(root) for root in RELEASE_TEXT_ROOTS)
    ]
    for file_path in release_files:
        try:
            validate_release_text_file(file_path)
        except ReleaseMetadataError as exc:
            fail(
                f"Release text is not deterministic UTF-8/LF: "
                f"{file_path.relative_to(ROOT)} ({exc.code})",
                errors,
            )

    try:
        manifest = load_model_manifest(MODEL_MANIFEST)
        profile = load_pipeline_profile(PIPELINE_PROFILE)
        qualification = load_qualification_record(QUALIFICATION_RECORD)
        validate_profile_against_manifest(profile, manifest)

        manifest_hash = sha256_release_file(MODEL_MANIFEST)
        profile_hash = sha256_release_file(PIPELINE_PROFILE)
        runtime_hash = sha256_release_file(RUNTIME_PROFILE)
        runtime_id, runtime_checkpoint_hash, runtime_config_hash = load_runtime_identity(
            RUNTIME_PROFILE
        )

        if manifest.verification_status != "unverified":
            fail(
                "Task-10 manifest must remain unverified until final Task-14 qualification.",
                errors,
            )
        if manifest.qualification_id is not None:
            fail(
                "Unverified Task-10 manifest must not claim a qualification ID.",
                errors,
            )

        if runtime_id != manifest.runtime_profile_id:
            fail("Runtime profile ID does not match model manifest.", errors)
        if runtime_checkpoint_hash != manifest.checkpoint.sha256:
            fail("Runtime checkpoint hash does not match model manifest.", errors)
        if runtime_config_hash != manifest.resolved_config.sha256:
            fail("Runtime resolved-config hash does not match model manifest.", errors)

        verify_qualification_relationships(
            qualification=qualification,
            manifest=manifest,
            manifest_sha256=manifest_hash,
            profile=profile,
            profile_sha256=profile_hash,
            runtime_profile_id=runtime_id,
            runtime_profile_sha256=runtime_hash,
            require_passed=False,
        )

        if qualification.overall_result != "pending":
            fail(
                "Pre-Task-14 qualification record must remain explicitly pending.",
                errors,
            )
    except ReleaseMetadataError as exc:
        fail(f"Vision release metadata invalid: {exc.code}", errors)


def main() -> int:
    errors: list[str] = []
    check_required_paths(errors)
    check_project_references(errors)
    check_contracts(errors)
    check_production_urls(errors)
    check_tracked_binaries_and_secrets(errors)
    check_vision_release_metadata(errors)

    if errors:
        print("MAVI repository verification FAILED")
        for error in errors:
            print(f" - {error}")
        return 1

    print("MAVI repository verification PASSED")
    print(f" - required paths: {len(REQUIRED_PATHS)}")
    print(f" - project boundaries: {len(ALLOWED_REFERENCES)}")
    print(" - contract examples: 7")
    print(" - production Internet URL scan: clean")
    print(" - tracked model/media/secret scan: clean")
    print(" - Task-10 release metadata: valid, explicitly unverified/pending")
    return 0


if __name__ == "__main__":
    sys.exit(main())
