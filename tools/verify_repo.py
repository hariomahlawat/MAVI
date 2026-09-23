#!/usr/bin/env python3
"""Validate the MAVI repository's architecture and offline-production guardrails."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tomllib
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
    "CONTRIBUTING.md",
    ".github/pull_request_template.md",
    "Setup-MAVI-Development.cmd",
    "config/dependencies/offline-dependency-policy-v1.json",
    "config/dependencies/offline-binary-catalog-v1.json",
    "docs/architecture/dependency-and-offline-packaging-policy.md",
    "docs/architecture/offline-binary-inventory.md",
    "vendor/offline-binary-kit/README.md",
    "tools/setup/New-MaviOfflineBinaryKit.ps1",
    "tools/setup/Test-MaviOfflineBinaryKit.ps1",
    "tools/setup/Prepare-MaviFfmpegWindows.ps1",
    "docs/runbooks/local-development.md",
    "docs/runbooks/mavi-offline-setup.md",
    "docs/runbooks/offline-readiness.md",
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
    "contracts/schemas/vision-job-complete-v2.schema.json",
    "contracts/schemas/vision-job-complete-v3.schema.json",
    "contracts/schemas/worker-health-v2.schema.json",
    "config/acceptance/phase1-acceptance-v1.json",
    "config/acceptance/phase1-supported-updates-v1.json",
    "config/acceptance/phase1-production-prerequisites-v1.json",
    "sample-data/ground-truth/phase1-ground-truth.schema.json",
    "sample-data/ground-truth/phase1-corpus.schema.json",
    "sample-data/ground-truth/phase1-example.json",
    "tools/phase1/phase1-acceptance-evidence.schema.json",
    "tools/phase1/phase1-evaluation-result.schema.json",
    "tools/phase1/cctv-quality-corpus-evidence.schema.json",
    "tools/phase1/quality_corpus.py",
    "tools/phase1/assemble_quality_corpus_evidence.py",
    "tools/phase1/offline-install-evidence.schema.json",
    "tools/phase1/application-lifecycle-evidence.schema.json",
    "tools/phase1/authoritative-state-check.schema.json",
    "tools/phase1/backup-restore-evidence.schema.json",
    "tools/phase1/offline-variant-evidence.schema.json",
    "tools/phase1/recovery-performance-evidence.schema.json",
    "tools/phase1/production-acceptance-evidence.schema.json",
    "tools/phase1/production-prerequisite-policy.schema.json",
    "tools/phase1/production-prerequisite-observation.schema.json",
    "tools/phase1/production-prerequisite-evidence.schema.json",
    "tools/phase1/production-scenario-evidence.schema.json",
    "tools/phase1/production-failure-reprocess-evidence.schema.json",
    "tools/phase1/production-log-inspection-evidence.schema.json",
    "tools/phase1/production-acceptance-context.schema.json",
    "tools/phase1/production-log-checkpoint.schema.json",
    "tools/phase1/collect_production_prerequisites.py",
    "tools/phase1/validate_production_prerequisites.py",
    "tools/phase1/run_production_scenario.py",
    "tools/phase1/qualify_failure_reprocess.py",
    "tools/phase1/inspect_production_logs.py",
    "tools/phase1/create_production_acceptance_context.py",
    "tools/phase1/capture_production_log_checkpoints.py",
    "tools/phase1/production_acceptance_context.py",
    "tools/phase1/topology_identity.py",
    "tools/phase1/environment_fingerprint.py",
    "tools/phase1/assemble_production_acceptance.py",
]

ALLOWED_REFERENCES = {
    "Mavi.Domain": set(),
    "Mavi.Contracts": set(),
    "Mavi.Application": {"Mavi.Domain", "Mavi.Contracts"},
    "Mavi.Infrastructure": {"Mavi.Application", "Mavi.Domain", "Mavi.Contracts"},
    "Mavi.Api": {"Mavi.Application", "Mavi.Infrastructure", "Mavi.Contracts"},
}

PROHIBITED_TRACKED_SUFFIXES = {
    ".pt", ".pth", ".onnx", ".engine", ".plan", ".safetensors", ".gguf", ".whl",
    ".mp4", ".avi", ".mov", ".mkv", ".m4v", ".webm",
    ".pem", ".key", ".pfx", ".p12",
}

PROHIBITED_DISTRIBUTABLE_SUFFIXES = {
    ".exe", ".dll", ".msi", ".msix", ".zip", ".7z", ".rar", ".nupkg",
    ".so", ".pyd", ".dylib",
}

MAX_UNAPPROVED_TRACKED_FILE_BYTES = 10 * 1024 * 1024

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
RELEASE_NETWORK_LOCATORS = (
    "http://",
    "https://",
    "git+",
    "ssh://",
    "ftp://",
    "s3://",
    "hf://",
    "mim://",
    "modelzoo://",
    "torchvision://",
    "openmmlab://",
)

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


# Each frozen toolchain identity is validated by shape, not by the absence of
# known placeholder words. A deny-list only rejects the sentinels someone
# thought of: "TODO", "n/a" or "-" would pass one and let a CUDA lock through.
_CUDA_TOOLCHAIN_IDENTITY_SHAPES = {
    # CUDA Toolkit, e.g. "12.4"
    "cudaToolkitVersion": re.compile(r"^\d+\.\d+$"),
    "cudaToolkit": re.compile(r"^\d+\.\d+$"),
    # MSVC toolset, e.g. "14.44.35207"
    "msvcToolset": re.compile(r"^\d+\.\d+\.\d+$"),
    # Windows SDK, e.g. "10.0.26100.0"
    "windowsSdkVersion": re.compile(r"^\d+\.\d+\.\d+\.\d+$"),
    "windowsSdk": re.compile(r"^\d+\.\d+\.\d+\.\d+$"),
}


def _frozen_toolchain_value(name: str, value: object) -> bool:
    """A toolchain identity counts as frozen only when it has a real identity.

    Absence, null, and anything that is not a version of the expected shape
    must fail closed.
    """
    shape = _CUDA_TOOLCHAIN_IDENTITY_SHAPES.get(name)
    if shape is None:
        raise KeyError(f"unknown toolchain identity field: {name}")
    return isinstance(value, str) and shape.fullmatch(value) is not None


def check_windows_cuda_build_contract(errors: list[str]) -> None:
    """Keep the Windows CUDA build contract and its lock gate fail-closed."""
    contract_path = ROOT / "config/vision/windows-cuda-development-build-v1.json"
    catalog_path = ROOT / "config/dependencies/offline-binary-catalog-v1.json"
    cuda_lock = (
        ROOT
        / "src/vision/runtime/mmdetection-phase1-v1"
        / "windows-x86_64-cuda.lock"
    )

    contract = _read_json_or_none(contract_path)
    if not isinstance(contract, dict):
        fail("Windows CUDA development build contract is missing or invalid.", errors)
        contract_toolchain: dict = {}
    else:
        if contract.get("schemaVersion") != "mavi-windows-cuda-development-build-v1":
            fail(
                "Windows CUDA development build contract schema is unsupported.",
                errors,
            )
        raw_toolchain = contract.get("toolchain")
        contract_toolchain = raw_toolchain if isinstance(raw_toolchain, dict) else {}
        if not contract_toolchain:
            fail(
                "Windows CUDA development build contract declares no toolchain.",
                errors,
            )
        runtime_policy = contract.get("runtimePolicy")
        if not isinstance(runtime_policy, dict) or (
            runtime_policy.get("explicitCudaMayFallbackToCpu") is not False
            or runtime_policy.get("cudaToolkitRequiredAtRuntime") is not False
            or runtime_policy.get("compilerRequiredAtRuntime") is not False
        ):
            fail(
                "Windows CUDA build contract must keep CUDA fail-closed and the "
                "build toolchain out of the runtime.",
                errors,
            )

    contract_verified = contract_toolchain.get("verificationStatus") == "verified"
    contract_frozen = contract_verified and all(
        _frozen_toolchain_value(name, contract_toolchain.get(name))
        for name in ("msvcToolset", "windowsSdkVersion", "cudaToolkitVersion")
    )
    if contract_verified and not contract_frozen:
        fail(
            "Windows CUDA build contract claims a verified toolchain without a "
            "frozen MSVC toolset, Windows SDK and CUDA Toolkit identity.",
            errors,
        )

    catalog = _read_json_or_none(catalog_path)
    candidate = None
    if isinstance(catalog, dict):
        vision_runtime = catalog.get("visionRuntime")
        if isinstance(vision_runtime, dict):
            candidate = vision_runtime.get("windowsCudaDevelopmentCandidate")
    if not isinstance(candidate, dict):
        fail("Offline binary catalogue has no Windows CUDA candidate.", errors)
        candidate = {}
    candidate_toolchain = candidate.get("buildToolchain")
    if not isinstance(candidate_toolchain, dict):
        candidate_toolchain = {}

    catalogue_frozen = all(
        _frozen_toolchain_value(name, candidate_toolchain.get(name))
        for name in ("msvcToolset", "windowsSdk", "cudaToolkit")
    )

    if contract_frozen:
        # One frozen toolchain identity, not two that can drift apart. This
        # holds as soon as the contract is verified, not only once a lock
        # exists, so the catalogue cannot quietly lack the identity.
        if not catalogue_frozen:
            fail(
                "Windows CUDA build contract is verified but the offline "
                "catalogue does not carry the frozen toolchain identity.",
                errors,
            )
        else:
            for contract_name, candidate_name in (
                ("msvcToolset", "msvcToolset"),
                ("windowsSdkVersion", "windowsSdk"),
                ("cudaToolkitVersion", "cudaToolkit"),
            ):
                if contract_toolchain.get(
                    contract_name
                ) != candidate_toolchain.get(candidate_name):
                    fail(
                        "Windows CUDA build contract and offline catalogue "
                        "disagree on the frozen toolchain field "
                        f"'{contract_name}'.",
                        errors,
                    )

    if not cuda_lock.exists():
        return

    if not contract_frozen or not catalogue_frozen:
        fail(
            "A Windows CUDA lock cannot be committed before the MSVC/CUDA "
            "toolchain preflight is verified and frozen in both the build "
            "contract and the offline binary catalogue.",
            errors,
        )


def _read_json_or_none(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def check_dependency_policy(errors: list[str]) -> None:
    """Keep direct dependency changes coupled to the offline deployment policy."""

    policy_path = ROOT / "config/dependencies/offline-dependency-policy-v1.json"
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"Offline dependency policy is invalid JSON: {exc}", errors)
        return

    if policy.get("schemaVersion") != "mavi-offline-dependency-policy-v1":
        fail("Offline dependency policy schemaVersion is invalid.", errors)
        return

    managed = policy.get("managedSources")
    if not isinstance(managed, dict):
        fail("Offline dependency policy has no managedSources object.", errors)
        return

    tracked = tracked_files()

    # .NET: every tracked project with a PackageReference must be represented.
    actual_dotnet: dict[str, dict[str, str]] = {}
    for project in tracked:
        if project.suffix.lower() != ".csproj":
            continue
        relative = project.relative_to(ROOT).as_posix()
        if not (relative.startswith("src/") or relative.startswith("tests/")):
            continue
        try:
            tree = ET.parse(project)
        except ET.ParseError as exc:
            fail(f"Cannot parse project dependency surface {relative}: {exc}", errors)
            continue

        packages: dict[str, str] = {}
        for reference in tree.findall(".//PackageReference"):
            name = reference.attrib.get("Include")
            version = reference.attrib.get("Version")
            if version is None:
                version_element = reference.find("Version")
                version = version_element.text if version_element is not None else None
            if name and version:
                packages[name] = version.strip()
            elif name:
                fail(
                    f"PackageReference {name} in {relative} must declare an explicit version.",
                    errors,
                )
        if packages:
            actual_dotnet[relative] = dict(sorted(packages.items()))

    expected_dotnet_raw = managed.get("dotnet")
    if not isinstance(expected_dotnet_raw, dict):
        fail("Offline dependency policy dotnet surface is missing.", errors)
    else:
        expected_dotnet = {
            path: dict(sorted(packages.items()))
            for path, packages in expected_dotnet_raw.items()
            if isinstance(packages, dict)
        }
        if actual_dotnet != expected_dotnet:
            fail(
                "Direct .NET dependencies changed without a matching update to "
                "config/dependencies/offline-dependency-policy-v1.json.",
                errors,
            )

    # npm: every tracked source package.json is policy-controlled.
    actual_npm: dict[str, dict[str, dict[str, str]]] = {}
    for package_json in tracked:
        relative = package_json.relative_to(ROOT).as_posix()
        if package_json.name != "package.json":
            continue
        try:
            payload = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            fail(f"Cannot parse npm dependency surface {relative}: {exc}", errors)
            continue
        actual_npm[relative] = {
            "dependencies": dict(sorted((payload.get("dependencies") or {}).items())),
            "devDependencies": dict(sorted((payload.get("devDependencies") or {}).items())),
        }

    expected_npm_raw = managed.get("npm")
    if not isinstance(expected_npm_raw, dict):
        fail("Offline dependency policy npm surface is missing.", errors)
    else:
        expected_npm = {
            path: {
                "dependencies": dict(sorted((values.get("dependencies") or {}).items())),
                "devDependencies": dict(sorted((values.get("devDependencies") or {}).items())),
            }
            for path, values in expected_npm_raw.items()
            if isinstance(values, dict)
        }
        if actual_npm != expected_npm:
            fail(
                "Direct npm dependencies changed without a matching update to "
                "config/dependencies/offline-dependency-policy-v1.json.",
                errors,
            )

    # Python: every tracked src pyproject plus repository verification requirements.
    actual_python: dict[str, dict[str, object]] = {}
    for pyproject in tracked:
        relative = pyproject.relative_to(ROOT).as_posix()
        if pyproject.name != "pyproject.toml":
            continue
        try:
            payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            fail(f"Cannot parse Python dependency surface {relative}: {exc}", errors)
            continue
        project = payload.get("project") or {}
        optional = project.get("optional-dependencies") or {}
        build_system = payload.get("build-system") or {}
        actual_python[relative] = {
            "projectDependencies": sorted(project.get("dependencies") or []),
            "optionalDependencies": {
                key: sorted(value)
                for key, value in sorted(optional.items())
            },
            "buildSystemRequires": sorted(build_system.get("requires") or []),
        }

    for requirements_path in tracked:
        relative = requirements_path.relative_to(ROOT).as_posix()
        if not re.fullmatch(r"requirements[^/]*\.txt", requirements_path.name, re.IGNORECASE):
            continue
        if not (relative.startswith("src/") or relative.startswith("tools/")):
            continue
        requirements = [
            line.strip()
            for line in requirements_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        actual_python[relative] = {
            "requirements": sorted(requirements),
        }

    expected_python_raw = managed.get("python")
    if not isinstance(expected_python_raw, dict):
        fail("Offline dependency policy Python surface is missing.", errors)
    else:
        expected_python: dict[str, dict[str, object]] = {}
        for source_path, values in expected_python_raw.items():
            if not isinstance(values, dict):
                continue
            if source_path.endswith("pyproject.toml"):
                optional = values.get("optionalDependencies") or {}
                expected_python[source_path] = {
                    "projectDependencies": sorted(values.get("projectDependencies") or []),
                    "optionalDependencies": {
                        key: sorted(value)
                        for key, value in sorted(optional.items())
                    },
                    "buildSystemRequires": sorted(values.get("buildSystemRequires") or []),
                }
            else:
                expected_python[source_path] = {
                    "requirements": sorted(values.get("requirements") or []),
                }
        if actual_python != expected_python:
            fail(
                "Direct Python dependencies changed without a matching update to "
                "config/dependencies/offline-dependency-policy-v1.json.",
                errors,
            )

    strategies = policy.get("ecosystemStrategies")
    if not isinstance(strategies, dict) or set(strategies) != {"dotnet", "npm", "python"}:
        fail("Offline dependency policy ecosystemStrategies must cover dotnet, npm and python.", errors)
    else:
        for ecosystem, values in strategies.items():
            if not isinstance(values, dict) or any(
                not isinstance(values.get(field), str) or not values.get(field)
                for field in ("developmentOffline", "productionOffline", "changeRule")
            ):
                fail(
                    f"Offline dependency strategy is incomplete for {ecosystem}.",
                    errors,
                )

    native = policy.get("nativeAndToolchain")
    required_native_fields = {
        "id",
        "scope",
        "stagingPath",
        "packagedAs",
        "setupIntegration",
        "verification",
        "licenceHandling",
    }
    if not isinstance(native, list) or not native:
        fail("Offline dependency policy must declare native/toolchain dependencies.", errors)
    else:
        seen_ids: set[str] = set()
        for entry in native:
            if not isinstance(entry, dict) or not required_native_fields.issubset(entry):
                fail("Offline native/toolchain dependency entry is incomplete.", errors)
                continue
            dependency_id = entry.get("id")
            if not isinstance(dependency_id, str) or not dependency_id or dependency_id in seen_ids:
                fail("Offline native/toolchain dependency IDs must be unique and non-empty.", errors)
                continue
            seen_ids.add(dependency_id)
            for field in required_native_fields - {"id", "scope"}:
                if not isinstance(entry.get(field), str) or not entry.get(field):
                    fail(
                        f"Offline native/toolchain dependency {dependency_id} has empty {field}.",
                        errors,
                    )
            if not isinstance(entry.get("scope"), list) or not entry["scope"]:
                fail(
                    f"Offline native/toolchain dependency {dependency_id} has no scope.",
                    errors,
                )

    required_cuda_policy_ids = {
        "nvidia-driver-win-x64",
        "cuda-toolkit-12.4-win-x64-build",
        "msvc-cuda-build-toolchain-win-x64",
        "vcredist-win-x64",
    }
    declared_native_ids = {
        entry.get("id")
        for entry in native
        if isinstance(entry, dict)
        and isinstance(entry.get("id"), str)
    } if isinstance(native, list) else set()
    missing_cuda_policy = required_cuda_policy_ids - declared_native_ids
    if missing_cuda_policy:
        fail(
            "Windows CUDA dependency policy is incomplete: "
            + str(sorted(missing_cuda_policy)),
            errors,
        )

    python_strategy = (
        strategies.get("python")
        if isinstance(strategies, dict)
        else None
    )
    cuda_acquisition = (
        python_strategy.get("cudaAcquisition")
        if isinstance(python_strategy, dict)
        else None
    )
    if not isinstance(cuda_acquisition, dict):
        fail(
            "Python dependency strategy has no Windows CUDA acquisition policy.",
            errors,
        )
    else:
        if cuda_acquisition.get("connectedPreparationOnly") is not True:
            fail(
                "Windows CUDA wheel acquisition must be connected-preparation-only.",
                errors,
            )
        if cuda_acquisition.get("pytorchIndex") != (
            "https://download.pytorch.org/whl/cu124"
        ):
            fail(
                "Windows CUDA PyTorch index is not the frozen cu124 candidate.",
                errors,
            )

    check_windows_cuda_build_contract(errors)

    review = policy.get("requiredChangeReview")
    if not isinstance(review, list) or len(review) < 8 or any(
        not isinstance(item, str) or not item.strip() for item in review
    ):
        fail("Offline dependency policy requiredChangeReview is incomplete.", errors)

    policy_reference = "docs/architecture/dependency-and-offline-packaging-policy.md"
    documentation_contract = [
        ROOT / "README.md",
        ROOT / "AGENTS.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / "database/README.md",
        ROOT / "docs/architecture/README.md",
        ROOT / "docs/runbooks/local-development.md",
        ROOT / "docs/runbooks/mavi-offline-setup.md",
        ROOT / "docs/runbooks/offline-readiness.md",
        ROOT / "docs/runbooks/phase1-acceptance.md",
        ROOT / "infrastructure/development/README.md",
        ROOT / "infrastructure/windows/README.md",
        ROOT / "infrastructure/linux/README.md",
        ROOT / "infrastructure/offline-bundle/README.md",
    ]
    for document in documentation_contract:
        try:
            content = document.read_text(encoding="utf-8")
        except OSError as exc:
            fail(f"Cannot read dependency-governance document {document}: {exc}", errors)
            continue
        if policy_reference not in content:
            fail(
                f"Dependency-governance document does not reference the canonical policy: "
                f"{document.relative_to(ROOT)}",
                errors,
            )


def check_offline_binary_catalog(errors: list[str]) -> None:
    """Validate the repository-owned external-binary/version baseline."""

    catalog_path = ROOT / "config/dependencies/offline-binary-catalog-v1.json"
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"Offline binary catalog is invalid JSON: {exc}", errors)
        return

    if catalog.get("schemaVersion") != "mavi-offline-binary-catalog-v1":
        fail("Offline binary catalog schemaVersion is invalid.", errors)
        return

    git_policy = catalog.get("gitPolicy")
    if not isinstance(git_policy, dict):
        fail("Offline binary catalog has no gitPolicy object.", errors)
    else:
        if git_policy.get("trackedThirdPartyExecutables") is not False:
            fail("Offline binary catalog must prohibit tracked third-party executables.", errors)
        if git_policy.get("maximumUnapprovedTrackedFileBytes") != MAX_UNAPPROVED_TRACKED_FILE_BYTES:
            fail(
                "Offline binary catalog tracked-file size policy does not match repository verification.",
                errors,
            )

    components = catalog.get("applicationAndSetup")
    required_ids = {
        "postgresql-win-x64",
        "pgvector-pg18-win-x64",
        "ffmpeg-win-x64",
        "dotnet-hosting-win-x64",
        "dotnet-sdk-win-x64",
        "node-win-x64",
        "python-development-win-x64",
        "developer-nuget-cache",
        "developer-npm-cache",
        "developer-python-wheelhouse",
    }
    if not isinstance(components, list):
        fail("Offline binary catalog applicationAndSetup must be a list.", errors)
        components = []

    by_id: dict[str, dict[str, object]] = {}
    required_fields = {
        "id",
        "role",
        "profiles",
        "versionPolicy",
        "baselineVersion",
        "dependencyPolicyId",
        "exactVersionSource",
        "binaryKitPath",
        "releasePath",
        "verification",
        "licence",
    }
    for component in components:
        if not isinstance(component, dict) or not required_fields.issubset(component):
            fail("Offline binary catalog component is incomplete.", errors)
            continue
        component_id = component.get("id")
        if not isinstance(component_id, str) or not component_id or component_id in by_id:
            fail("Offline binary catalog component IDs must be unique and non-empty.", errors)
            continue
        by_id[component_id] = component
        if not isinstance(component.get("profiles"), list) or not component["profiles"]:
            fail(f"Offline binary catalog component {component_id} has no profiles.", errors)
        for field in required_fields - {"id", "profiles"}:
            if not isinstance(component.get(field), str) or not component[field]:
                fail(f"Offline binary catalog component {component_id} has empty {field}.", errors)

    missing = required_ids - set(by_id)
    if missing:
        fail(f"Offline binary catalog is missing required components: {sorted(missing)}", errors)

    ffmpeg_component = by_id.get("ffmpeg-win-x64")
    if ffmpeg_component is not None:
        acquisition = ffmpeg_component.get("acquisitionSource")
        if not isinstance(acquisition, dict):
            fail("Offline binary catalog FFmpeg entry has no acquisitionSource.", errors)
        else:
            required_acquisition_fields = {
                "connectedPreparationOnly",
                "provider",
                "archiveName",
                "url",
                "sha256",
                "upstreamSourceCommit",
            }
            if not required_acquisition_fields.issubset(acquisition):
                fail("Offline binary catalog FFmpeg acquisitionSource is incomplete.", errors)
            else:
                if acquisition.get("connectedPreparationOnly") is not True:
                    fail("FFmpeg acquisition must be connected-preparation-only.", errors)
                url = acquisition.get("url")
                if not isinstance(url, str) or not url.startswith("https://"):
                    fail("FFmpeg acquisition URL must be HTTPS.", errors)
                sha = acquisition.get("sha256")
                if (
                    not isinstance(sha, str)
                    or len(sha) != 64
                    or any(ch not in "0123456789abcdef" for ch in sha)
                ):
                    fail("FFmpeg acquisition SHA-256 is invalid.", errors)
                archive_name = acquisition.get("archiveName")
                if (
                    not isinstance(archive_name, str)
                    or not archive_name.endswith(".zip")
                    or "/" in archive_name
                    or "\\" in archive_name
                ):
                    fail("FFmpeg acquisition archiveName must be a simple ZIP filename.", errors)
                baseline = ffmpeg_component.get("baselineVersion")
                if (
                    not isinstance(baseline, str)
                    or baseline in {"", "from-staged-manifest"}
                ):
                    fail("FFmpeg connected-preparation baseline version must be pinned.", errors)

    try:
        dependency_policy = json.loads(
            (ROOT / "config/dependencies/offline-dependency-policy-v1.json").read_text(
                encoding="utf-8"
            )
        )
        policy_ids = {
            item.get("id")
            for item in dependency_policy.get("nativeAndToolchain", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        for component_id, component in by_id.items():
            policy_id = component.get("dependencyPolicyId")
            if policy_id not in policy_ids:
                fail(
                    f"Offline binary catalog component {component_id} references unknown "
                    f"dependency policy group {policy_id!r}.",
                    errors,
                )
        vision = catalog.get("visionRuntime")
        if isinstance(vision, dict) and vision.get("dependencyPolicyId") not in policy_ids:
            fail("Offline binary catalog vision runtime references an unknown dependency policy group.", errors)
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"Unable to reconcile offline binary catalog with dependency policy: {exc}", errors)

    try:
        global_json = json.loads((ROOT / "global.json").read_text(encoding="utf-8"))
        sdk_version = str(global_json["sdk"]["version"])
        catalog_sdk = str(by_id.get("dotnet-sdk-win-x64", {}).get("baselineVersion", ""))
        if sdk_version != catalog_sdk:
            fail(
                f"Offline binary catalog .NET SDK baseline {catalog_sdk!r} "
                f"does not match global.json {sdk_version!r}.",
                errors,
            )
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        fail(f"Unable to reconcile global.json with offline binary catalog: {exc}", errors)

    try:
        runtime = json.loads(
            (ROOT / "src/vision/runtime/mmdetection-phase1-v1/runtime.json").read_text(
                encoding="utf-8"
            )
        )
        vision = catalog.get("visionRuntime")
        if not isinstance(vision, dict):
            fail("Offline binary catalog has no visionRuntime object.", errors)
        else:
            if vision.get("runtimeProfileId") != runtime.get("runtimeProfileId"):
                fail("Offline binary catalog vision runtime profile ID is stale.", errors)
            if vision.get("semanticGraph") != runtime.get("semanticGraph"):
                fail("Offline binary catalog vision semantic graph is stale.", errors)
            catalog_python = vision.get("python")
            if not isinstance(catalog_python, dict):
                fail("Offline binary catalog vision Python identities are missing.", errors)
            else:
                for variant in ("windows-x86_64-cpu", "linux-x86_64-cpu"):
                    observed = (
                        runtime.get("platformVariants", {})
                        .get(variant, {})
                        .get("pythonIdentity", {})
                        .get("version")
                    )
                    if catalog_python.get(variant) != observed:
                        fail(
                            f"Offline binary catalog Python version for {variant} "
                            f"does not match runtime qualification metadata.",
                            errors,
                        )
                for variant in ("windows-x86_64-cuda", "linux-x86_64-cuda"):
                    runtime_status = runtime.get("platformVariants", {}).get(variant, {}).get("status")
                    if runtime_status == "pending-hardware-qualification":
                        if catalog_python.get(variant) != "pending-hardware-qualification":
                            fail(
                                f"Offline binary catalog must keep {variant} pending until "
                                "hardware qualification freezes its Python identity.",
                                errors,
                            )
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"Unable to reconcile vision runtime with offline binary catalog: {exc}", errors)


def check_contracts(errors: list[str]) -> None:
    if jsonschema is None:
        fail("Python package 'jsonschema' is required to validate contract examples.", errors)
        return

    stems = [
        "vision-job-lease-request-v2", "vision-job-lease-v2", "vision-job-heartbeat-v2",
        "vision-job-heartbeat-response-v2", "vision-job-fail-v2", "vision-job-complete-v2", "worker-health-v2",
        "vision-job-complete-v3",
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

    check_completion_v3_contract(errors)


def check_completion_v3_contract(errors: list[str]) -> None:
    """Completion 3.0 (S1.2): shared definitions, invalid vectors and the pinned golden."""
    schemas = ROOT / "contracts/schemas"
    v2 = json.loads((schemas / "vision-job-complete-v2.schema.json").read_text())
    v3 = json.loads((schemas / "vision-job-complete-v3.schema.json").read_text())
    # Provenance and artefact grammar are one boundary across both completion versions.
    for name in ("sha256", "artifact", "boundingBox", "platform", "gpu", "trackerParameters", "provenance", "identityText", "detailText"):
        if v2["$defs"].get(name) != v3["$defs"].get(name):
            fail(f"Completion v3 schema definition '{name}' drifted from v2.", errors)
    if "representative" in v3["$defs"]["track"]["properties"]:
        fail("Completion v3 tracks must carry observations, not the v2 representative member.", errors)

    validator = jsonschema.Draft202012Validator(v3, format_checker=jsonschema.FormatChecker())
    vectors = json.loads((ROOT / "contracts/test-vectors/control-plane-v3-invalid.json").read_text())
    for vector in vectors:
        schema_valid = not list(validator.iter_errors(vector["payload"]))
        if vector["rejectedBy"] == "schema" and schema_valid:
            fail(f"Invalid completion v3 vector was accepted by the schema: {vector['name']}", errors)
        if vector["rejectedBy"] == "validator" and not schema_valid:
            fail(f"Completion v3 vector '{vector['name']}' must be schema-valid so it exercises the platform validator.", errors)

    digest = json.loads((ROOT / "contracts/test-vectors/vision-job-complete-v3-digest.json").read_text())
    example_sha = hashlib.sha256((ROOT / digest["example"]).read_bytes()).hexdigest()
    if example_sha != digest["exampleSha256"]:
        fail("Completion v3 golden example changed without re-pinning its digest vector.", errors)
    if not re.fullmatch(r"[0-9a-f]{64}", digest.get("completionDigest", "")):
        fail("Completion v3 digest vector must pin a lower-case SHA-256 digest.", errors)


def check_phase1_acceptance_assets(errors: list[str]) -> None:
    if jsonschema is None:
        fail("Python package 'jsonschema' is required to validate Task-17 assets.", errors)
        return

    schema_paths = [
        ROOT / "sample-data/ground-truth/phase1-ground-truth.schema.json",
        ROOT / "sample-data/ground-truth/phase1-corpus.schema.json",
        ROOT / "tools/phase1/phase1-acceptance-evidence.schema.json",
        ROOT / "tools/phase1/phase1-evaluation-result.schema.json",
        ROOT / "tools/phase1/cctv-quality-corpus-evidence.schema.json",
        ROOT / "tools/phase1/offline-install-evidence.schema.json",
        ROOT / "tools/phase1/application-lifecycle-evidence.schema.json",
        ROOT / "tools/phase1/authoritative-state-check.schema.json",
        ROOT / "tools/phase1/backup-restore-evidence.schema.json",
        ROOT / "tools/phase1/offline-variant-evidence.schema.json",
        ROOT / "tools/phase1/recovery-performance-evidence.schema.json",
        ROOT / "tools/phase1/production-acceptance-evidence.schema.json",
        ROOT / "tools/phase1/production-acceptance-context.schema.json",
        ROOT / "tools/phase1/production-log-checkpoint.schema.json",
        ROOT / "tools/phase1/production-prerequisite-policy.schema.json",
        ROOT / "tools/phase1/production-prerequisite-observation.schema.json",
        ROOT / "tools/phase1/production-prerequisite-evidence.schema.json",
        ROOT / "tools/phase1/production-scenario-evidence.schema.json",
        ROOT / "tools/phase1/production-failure-reprocess-evidence.schema.json",
        ROOT / "tools/phase1/production-log-inspection-evidence.schema.json",
    ]
    schemas = {}
    for path in schema_paths:
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator.check_schema(schema)
            schemas[path.name] = schema
        except (OSError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
            fail(f"Task-17 schema invalid: {path.relative_to(ROOT)} ({exc})", errors)

    ground_truth_schema = schemas.get("phase1-ground-truth.schema.json")
    if ground_truth_schema is not None:
        try:
            example = json.loads(
                (ROOT / "sample-data/ground-truth/phase1-example.json").read_text(
                    encoding="utf-8"
                )
            )
            jsonschema.validate(
                instance=example,
                schema=ground_truth_schema,
                format_checker=jsonschema.FormatChecker(),
            )
        except (OSError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
            message = getattr(exc, "message", str(exc))
            fail(f"Task-17 ground-truth example invalid: {message}", errors)

    try:
        profile = json.loads(
            (ROOT / "config/acceptance/phase1-acceptance-v1.json").read_text(
                encoding="utf-8"
            )
        )
        if profile.get("schemaVersion") != "mavi-phase1-acceptance-profile-v1":
            fail("Task-17 acceptance profile schemaVersion is invalid.", errors)
        if profile.get("requiredClasses") != ["Person", "Vehicle"]:
            fail("Task-17 acceptance profile must require Person and Vehicle.", errors)
        corpus_sha = profile.get("qualificationCorpusManifestSha256")
        if profile.get("mode") == "qualification":
            if (
                not isinstance(corpus_sha, str)
                or len(corpus_sha) != 64
                or any(ch not in "0123456789abcdef" for ch in corpus_sha)
            ):
                fail("Task-17 qualification corpus identity is not approved.", errors)
        elif corpus_sha is not None and (
            not isinstance(corpus_sha, str)
            or len(corpus_sha) != 64
            or any(ch not in "0123456789abcdef" for ch in corpus_sha)
        ):
            fail("Task-17 qualification corpus identity is invalid.", errors)

        thresholds = profile.get("classThresholds")
        if not isinstance(thresholds, dict) or set(thresholds) != {"Person", "Vehicle"}:
            fail("Task-17 acceptance profile class thresholds are incomplete.", errors)
        if profile.get("mode") == "qualification":
            for object_class in ("Person", "Vehicle"):
                if not isinstance(thresholds.get(object_class), dict):
                    fail(
                        f"Task-17 qualification threshold missing for {object_class}.",
                        errors,
                    )
        performance = profile.get("performanceThresholds")
        if performance is not None and set(performance) != {
            "minimumProcessingFps",
            "maximumP95LatencyMs",
            "maximumSoakGrowthBytes",
        }:
            fail("Task-17 performance threshold policy is incomplete.", errors)
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"Task-17 acceptance profile is invalid JSON: {exc}", errors)

    try:
        updates = json.loads(
            (ROOT / "config/acceptance/phase1-supported-updates-v1.json").read_text(
                encoding="utf-8"
            )
        )
        if updates.get("schemaVersion") != "mavi-phase1-supported-updates-v1":
            fail("Task-17 supported update policy schemaVersion is invalid.", errors)
        releases = updates.get("priorReleases")
        if not isinstance(releases, list) or not releases:
            fail("Task-17 supported update policy must name at least one prior release.", errors)
        else:
            seen = set()
            for release in releases:
                commit = release.get("sourceCommit") if isinstance(release, dict) else None
                policy = release.get("migrationPolicy") if isinstance(release, dict) else None
                has_application_manifest_sha = (
                    isinstance(release, dict)
                    and "applicationManifestSha256" in release
                )
                application_manifest_sha = (
                    release.get("applicationManifestSha256")
                    if isinstance(release, dict)
                    else None
                )
                if (
                    not isinstance(commit, str)
                    or len(commit) not in {40, 64}
                    or any(ch not in "0123456789abcdef" for ch in commit)
                    or commit in seen
                ):
                    fail("Task-17 supported update release identity is invalid.", errors)
                    continue
                seen.add(commit)
                if policy not in {"none", "required"}:
                    fail(
                        f"Task-17 migration policy is invalid for prior release {commit}.",
                        errors,
                    )
                migration_script_sha = (
                    release.get("migrationScriptSha256")
                    if isinstance(release, dict)
                    else None
                )
                if policy == "required":
                    if (
                        not isinstance(migration_script_sha, str)
                        or len(migration_script_sha) != 64
                        or any(ch not in "0123456789abcdef" for ch in migration_script_sha)
                    ):
                        fail(
                            f"Task-17 migration script hash is not frozen for prior release {commit}.",
                            errors,
                        )
                elif migration_script_sha is not None:
                    fail(
                        f"Task-17 migration script hash must be null when migration is not required for {commit}.",
                        errors,
                    )
                if not has_application_manifest_sha:
                    fail(
                        f"Task-17 prior application manifest hash field is missing for {commit}.",
                        errors,
                    )
                elif application_manifest_sha is not None and (
                    not isinstance(application_manifest_sha, str)
                    or len(application_manifest_sha) != 64
                    or any(ch not in "0123456789abcdef" for ch in application_manifest_sha)
                ):
                    fail(
                        f"Task-17 prior application manifest hash is invalid for {commit}.",
                        errors,
                    )
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"Task-17 supported update policy is invalid JSON: {exc}", errors)


    try:
        prerequisites = json.loads(
            (ROOT / "config/acceptance/phase1-production-prerequisites-v1.json").read_text(
                encoding="utf-8"
            )
        )
        schema = schemas.get("production-prerequisite-policy.schema.json")
        if schema is not None:
            jsonschema.validate(
                instance=prerequisites,
                schema=schema,
                format_checker=jsonschema.FormatChecker(),
            )
        if prerequisites.get("approvalStatus") == "approved":
            for section in (
                "windowsOperationalPlane",
                "database",
                "linuxVisionWorker",
            ):
                values = prerequisites.get(section)
                if (
                    not isinstance(values, dict)
                    or any(not isinstance(value, str) or not value for value in values.values())
                ):
                    fail(
                        "Task-17 approved production prerequisite baseline is not fully frozen.",
                        errors,
                    )
    except (OSError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
        message = getattr(exc, "message", str(exc))
        fail(f"Task-17 production prerequisite policy is invalid: {message}", errors)

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


def find_release_network_hazard(text: str) -> str | None:
    lowered = text.lower()
    for locator in RELEASE_NETWORK_LOCATORS:
        if locator in lowered:
            return locator
    return None


def check_runtime_lock_file(path: Path, errors: list[str]) -> None:
    if str(VISION_ROOT) not in sys.path:
        sys.path.insert(0, str(VISION_ROOT))

    try:
        from mavi_vision.runtime.offline_lock import (
            OfflineLockError,
            load_offline_runtime_lock,
        )
    except ImportError as exc:
        fail(f"Offline lock tooling could not be imported: {exc}", errors)
        return

    try:
        load_offline_runtime_lock(path)
    except OfflineLockError as exc:
        try:
            display = path.relative_to(ROOT)
        except ValueError:
            display = path
        fail(
            f"Runtime release lock invalid: {display} ({exc.code})",
            errors,
        )


def check_tracked_binaries_and_secrets(errors: list[str]) -> None:
    for path in tracked_files():
        suffix = path.suffix.lower()
        relative = path.relative_to(ROOT)
        if suffix in PROHIBITED_TRACKED_SUFFIXES:
            fail(f"Prohibited model/media/secret file is tracked: {relative}", errors)
        if suffix in PROHIBITED_DISTRIBUTABLE_SUFFIXES:
            fail(
                f"Third-party/generated distributable payload must live in the offline binary kit, "
                f"not ordinary Git: {relative}",
                errors,
            )
        try:
            if path.stat().st_size > MAX_UNAPPROVED_TRACKED_FILE_BYTES:
                fail(
                    f"Tracked file exceeds the {MAX_UNAPPROVED_TRACKED_FILE_BYTES // (1024 * 1024)} MiB "
                    f"ordinary-Git limit and requires an explicit packaging decision: {relative}",
                    errors,
                )
        except OSError as exc:
            fail(f"Unable to inspect tracked file size for {relative}: {exc}", errors)
        if path.name in {".env", "secrets.json"}:
            fail(f"Prohibited secret file is tracked: {relative}", errors)


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
            verify_runtime_release_locks,
        )
    except ImportError as exc:
        fail(f"Vision release metadata tooling could not be imported: {exc}", errors)
        return

    tracked = tracked_files()
    tracked_set = set(tracked)
    release_files = sorted(
        file_path
        for file_path in tracked
        if file_path.suffix.lower() in {".json", ".lock"}
        and any(file_path.is_relative_to(root) for root in RELEASE_TEXT_ROOTS)
    )
    for file_path in release_files:
        try:
            payload = validate_release_text_file(file_path)
        except ReleaseMetadataError as exc:
            fail(
                f"Release text is not deterministic UTF-8/LF: "
                f"{file_path.relative_to(ROOT)} ({exc.code})",
                errors,
            )
            continue

        hazard = find_release_network_hazard(payload.decode("utf-8"))
        if hazard is not None:
            fail(
                f"Release metadata contains an online resolver locator "
                f"{hazard!r}: {file_path.relative_to(ROOT)}",
                errors,
            )

        if file_path.suffix.lower() == ".lock":
            check_runtime_lock_file(file_path, errors)

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
            verified_locks = verify_runtime_release_locks(path, runtime_profile)
            runtime_hash = sha256_release_file(path)
        except ReleaseMetadataError as exc:
            fail(
                f"Runtime profile invalid: {path.relative_to(ROOT)} ({exc.code})",
                errors,
            )
            continue

        for variant, lock_path in verified_locks.items():
            if lock_path not in tracked_set:
                fail(
                    f"Qualified runtime lock for {variant} is not tracked: "
                    f"{lock_path.relative_to(ROOT)}",
                    errors,
                )
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
    check_dependency_policy(errors)
    check_offline_binary_catalog(errors)
    check_contracts(errors)
    check_phase1_acceptance_assets(errors)
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
    print(" - direct dependency/offline packaging policy: synchronized")
    print(" - offline binary/version catalog: synchronized")
    print(" - ordinary Git executable/archive/large-file gate: clean")
    print(" - contract examples: 8 (incl. completion v3 golden, digest pin and invalid vectors)")
    print(" - Task-17 acceptance schemas/configuration: validated")
    print(" - production Internet URL scan: clean")
    print(" - tracked model/media/secret/wheel scan: clean")
    print(" - Task-10 release metadata: every tracked record and relationship validated")
    print(" - Task-12 release resolver/lock scan: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
