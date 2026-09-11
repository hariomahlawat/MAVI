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
MANIFEST_ROOT = ROOT / "models/manifests"
QUALIFICATION_ROOT = ROOT / "models/qualifications"
PIPELINE_PROFILE_ROOT = ROOT / "src/vision/config/pipelines"
RUNTIME_PROFILE_ROOT = ROOT / "src/vision/runtime"
RELEASE_TEXT_ROOTS = [
    MANIFEST_ROOT,
    QUALIFICATION_ROOT,
    PIPELINE_PROFILE_ROOT,
    RUNTIME_PROFILE_ROOT,
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
    """Validate every tracked Task-10 release metadata record and relationship."""
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
            load_runtime_profile,
            verify_qualification_relationships,
        )
    except ImportError as exc:
        fail(f"Vision release metadata tooling could not be imported: {exc}", errors)
        return

    tracked = tracked_files()
    release_files = sorted(
        file_path
        for file_path in tracked
        if file_path.suffix.lower() in {".json", ".lock"}
        and any(file_path.is_relative_to(root) for root in RELEASE_TEXT_ROOTS)
    )
    for file_path in release_files:
        try:
            validate_release_text_file(file_path)
        except ReleaseMetadataError as exc:
            fail(
                f"Release text is not deterministic UTF-8/LF: "
                f"{file_path.relative_to(ROOT)} ({exc.code})",
                errors,
            )

    manifest_paths = sorted(
        path
        for path in tracked
        if path.suffix.lower() == ".json" and path.is_relative_to(MANIFEST_ROOT)
    )
    profile_paths = sorted(
        path
        for path in tracked
        if path.suffix.lower() == ".json" and path.is_relative_to(PIPELINE_PROFILE_ROOT)
    )
    qualification_paths = sorted(
        path
        for path in tracked
        if path.suffix.lower() == ".json" and path.is_relative_to(QUALIFICATION_ROOT)
    )
    runtime_json_paths = sorted(
        path
        for path in tracked
        if path.suffix.lower() == ".json" and path.is_relative_to(RUNTIME_PROFILE_ROOT)
    )
    runtime_paths = [path for path in runtime_json_paths if path.name == "runtime.json"]
    for path in runtime_json_paths:
        if path.name != "runtime.json":
            fail(
                f"Unrecognized runtime release JSON must not bypass validation: "
                f"{path.relative_to(ROOT)}",
                errors,
            )

    manifests: dict[str, tuple[Path, object, str]] = {}
    profiles: dict[str, tuple[Path, object, str]] = {}
    qualifications: dict[str, tuple[Path, object, str]] = {}
    runtimes: dict[str, tuple[Path, str, str, str, str, str]] = {}

    for path in manifest_paths:
        try:
            manifest = load_model_manifest(path)
            manifest_hash = sha256_release_file(path)
        except ReleaseMetadataError as exc:
            fail(
                f"Model manifest invalid: {path.relative_to(ROOT)} ({exc.code})",
                errors,
            )
            continue
        if manifest.model_id in manifests:
            fail(f"Duplicate modelId in release manifests: {manifest.model_id}", errors)
            continue
        manifests[manifest.model_id] = (path, manifest, manifest_hash)

    for path in profile_paths:
        try:
            profile = load_pipeline_profile(path)
            profile_hash = sha256_release_file(path)
        except ReleaseMetadataError as exc:
            fail(
                f"Pipeline profile invalid: {path.relative_to(ROOT)} ({exc.code})",
                errors,
            )
            continue
        if profile.profile_id in profiles:
            fail(f"Duplicate profileId in release profiles: {profile.profile_id}", errors)
            continue
        profiles[profile.profile_id] = (path, profile, profile_hash)

    for path in qualification_paths:
        try:
            qualification = load_qualification_record(path)
            qualification_hash = sha256_release_file(path)
        except ReleaseMetadataError as exc:
            fail(
                f"Qualification record invalid: {path.relative_to(ROOT)} ({exc.code})",
                errors,
            )
            continue
        if qualification.qualification_id in qualifications:
            fail(
                f"Duplicate qualificationId in qualification records: "
                f"{qualification.qualification_id}",
                errors,
            )
            continue
        qualifications[qualification.qualification_id] = (
            path,
            qualification,
            qualification_hash,
        )

    for path in runtime_paths:
        try:
            runtime_profile = load_runtime_profile(path)
            runtime_hash = sha256_release_file(path)
        except ReleaseMetadataError as exc:
            fail(
                f"Runtime profile invalid: {path.relative_to(ROOT)} ({exc.code})",
                errors,
            )
            continue
        runtime_id = runtime_profile.runtime_profile_id
        if runtime_id in runtimes:
            fail(f"Duplicate runtimeProfileId: {runtime_id}", errors)
            continue
        runtimes[runtime_id] = (
            path,
            runtime_hash,
            runtime_profile.checkpoint.sha256,
            runtime_profile.resolved_config.sha256,
            runtime_id,
            runtime_profile.qualification_status,
        )

    for profile_path, profile, _profile_hash in profiles.values():
        manifest_entry = manifests.get(profile.model_id)
        if manifest_entry is None:
            fail(
                f"Pipeline profile {profile.profile_id} references unknown modelId "
                f"{profile.model_id}.",
                errors,
            )
            continue
        try:
            validate_profile_against_manifest(profile, manifest_entry[1])
        except ReleaseMetadataError as exc:
            fail(
                f"Pipeline profile relationship invalid: "
                f"{profile_path.relative_to(ROOT)} ({exc.code})",
                errors,
            )

    for manifest_path, manifest, _manifest_hash in manifests.values():
        runtime_entry = runtimes.get(manifest.runtime_profile_id)
        if runtime_entry is None:
            fail(
                f"Model manifest {manifest.model_id} references unknown runtimeProfileId "
                f"{manifest.runtime_profile_id}.",
                errors,
            )
            continue

        (
            _runtime_path,
            _runtime_hash,
            checkpoint_hash,
            config_hash,
            _runtime_id,
            runtime_qualification_status,
        ) = runtime_entry
        if checkpoint_hash != manifest.checkpoint.sha256:
            fail(
                f"Runtime checkpoint hash does not match manifest {manifest.model_id}.",
                errors,
            )
        if config_hash != manifest.resolved_config.sha256:
            fail(
                f"Runtime resolved-config hash does not match manifest {manifest.model_id}.",
                errors,
            )

        if manifest.verification_status == "unverified" and manifest.qualification_id is not None:
            fail(
                f"Unverified manifest {manifest.model_id} must not claim a qualification ID.",
                errors,
            )

        if manifest.verification_status == "verified":
            if runtime_qualification_status != "qualified":
                fail(
                    f"Verified manifest {manifest.model_id} requires a qualified runtime "
                    f"profile; found {runtime_qualification_status}.",
                    errors,
                )
                continue
            qualification_entry = qualifications.get(manifest.qualification_id or "")
            if qualification_entry is None:
                fail(
                    f"Verified manifest {manifest.model_id} references missing qualification "
                    f"{manifest.qualification_id}.",
                    errors,
                )
                continue
            qualification = qualification_entry[1]
            profile_entry = profiles.get(qualification.pipeline_profile_id)
            if profile_entry is None:
                fail(
                    f"Verified qualification {qualification.qualification_id} references "
                    f"unknown profileId {qualification.pipeline_profile_id}.",
                    errors,
                )
                continue
            try:
                verify_qualification_relationships(
                    qualification=qualification,
                    manifest=manifest,
                    manifest_sha256=sha256_release_file(manifest_path),
                    profile=profile_entry[1],
                    profile_sha256=profile_entry[2],
                    runtime_profile_id=runtime_entry[4],
                    runtime_profile_sha256=runtime_entry[1],
                    require_passed=True,
                )
            except ReleaseMetadataError as exc:
                fail(
                    f"Verified release relationship invalid for {manifest.model_id}: "
                    f"{exc.code}",
                    errors,
                )

    for qualification_path, qualification, _qualification_hash in qualifications.values():
        manifest_entry = manifests.get(qualification.model_id)
        if manifest_entry is None:
            fail(
                f"Qualification {qualification.qualification_id} references unknown modelId "
                f"{qualification.model_id}.",
                errors,
            )
            continue
        profile_entry = profiles.get(qualification.pipeline_profile_id)
        if profile_entry is None:
            fail(
                f"Qualification {qualification.qualification_id} references unknown profileId "
                f"{qualification.pipeline_profile_id}.",
                errors,
            )
            continue
        runtime_entry = runtimes.get(qualification.runtime_profile_id)
        if runtime_entry is None:
            fail(
                f"Qualification {qualification.qualification_id} references unknown "
                f"runtimeProfileId {qualification.runtime_profile_id}.",
                errors,
            )
            continue

        manifest = manifest_entry[1]
        try:
            verify_qualification_relationships(
                qualification=qualification,
                manifest=manifest,
                manifest_sha256=manifest_entry[2],
                profile=profile_entry[1],
                profile_sha256=profile_entry[2],
                runtime_profile_id=runtime_entry[4],
                runtime_profile_sha256=runtime_entry[1],
                require_passed=False,
            )
        except ReleaseMetadataError as exc:
            fail(
                f"Qualification relationship invalid: "
                f"{qualification_path.relative_to(ROOT)} ({exc.code})",
                errors,
            )
            continue

        if manifest.verification_status == "unverified" and qualification.overall_result != "pending":
            fail(
                f"Qualification {qualification.qualification_id} must remain pending while "
                f"manifest {manifest.model_id} is unverified.",
                errors,
            )

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
    print(" - Task-10 release metadata: every tracked record and relationship validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
