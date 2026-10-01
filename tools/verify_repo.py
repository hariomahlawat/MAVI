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
    "models/manifests/rtmdet-m-coco-phase1-v2.json",
    "models/qualifications/rtmdet-m-coco-phase1-v2.json",
    "src/vision/config/components/phase1-bindings-v2.json",
    "config/acceptance/capability-gate-sets-v1.json",
    "src/vision/config/pipelines/phase1-detection-tracking-v1.json",
    "src/vision/runtime/mmdetection-phase1-v1/runtime.json",
    "contracts/schemas/vision-job-lease-v2.schema.json",
    "contracts/schemas/vision-job-complete-v2.schema.json",
    "contracts/schemas/vision-job-complete-v3.schema.json",
    "contracts/schemas/vision-job-complete-v3.1.schema.json",
    "contracts/schemas/vision-job-finalization-response-v3.1.schema.json",
    "contracts/schemas/vision-job-complete-v3.2.schema.json",
    "contracts/schemas/vision-job-finalization-response-v3.2.schema.json",
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
    ".mp4", ".avi", ".mov", ".mkv", ".m4v", ".webm", ".ogv", ".ogg", ".mpg", ".mpeg",
    ".pem", ".key", ".pfx", ".p12",
}

PROHIBITED_DISTRIBUTABLE_SUFFIXES = {
    ".exe", ".dll", ".msi", ".msix", ".zip", ".7z", ".rar", ".nupkg",
    ".so", ".pyd", ".dylib",
}

MAX_UNAPPROVED_TRACKED_FILE_BYTES = 10 * 1024 * 1024

# S2c.1 corpus areas hold manifests, hashes and reports only: an image there is almost
# certainly a private evidence crop that must stay in the Corpus Custodian's store.
PRIVATE_EVIDENCE_AREAS = (
    "docs/qualification/stage2-s2c",
    "docs/qualification/model-selection",
    "tools/qualification/attributes",
    "tools/qualification/source_acquisition",
)
PROHIBITED_EVIDENCE_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".tif", ".tiff", ".heic"}

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
COMPONENT_BINDING_ROOT = ROOT / "src/vision/config/components"
RELEASE_TEXT_ROOTS = [
    MANIFEST_ROOT,
    QUALIFICATION_ROOT,
    PIPELINE_PROFILE_ROOT,
    RUNTIME_PROFILE_ROOT,
    COMPONENT_BINDING_ROOT,
]


def fail(message: str, errors: list[str]) -> None:
    errors.append(message)


def check_required_paths(errors: list[str]) -> None:
    for relative in REQUIRED_PATHS:
        if not (ROOT / relative).exists():
            fail(f"Missing required path: {relative}", errors)


CODE_OWNERS_PATH = ".github/CODEOWNERS"
REQUIRED_CODE_OWNER = "@hariomahlawat"
# GitHub uses the first CODEOWNERS file it finds in .github/, the root, docs/,
# and ignores a file larger than 3 MB.
IGNORED_CODE_OWNERS_PATHS = ("CODEOWNERS", "docs/CODEOWNERS")
CODE_OWNERS_MAX_BYTES = 3 * 1024 * 1024
# The aggregate checks required on main. Each must be produced by exactly one
# workflow job, or another job of the same name could satisfy the requirement.
REQUIRED_CHECK_NAMES = ("quality", "Task 10 qualification")


def _code_owner_tokens(line: str) -> list[str]:
    """Split a CODEOWNERS line as GitHub does: whitespace separates tokens unless
    escaped with a backslash, and a token starting with '#' begins a comment."""
    tokens: list[str] = []
    current = ""
    escaped = False
    for char in line:
        if escaped:
            current += char
            escaped = False
        elif char == "\\":
            current += char
            escaped = True
        elif char.isspace():
            if current:
                tokens.append(current)
            current = ""
        else:
            current += char
    if current:
        tokens.append(current)
    for index, token in enumerate(tokens):
        if token.startswith("#"):
            return tokens[:index]
    return tokens


def code_owner_problems(text: str) -> list[str]:
    """GitHub applies the last matching CODEOWNERS rule, so every rule must keep
    the required owner, and the first rule must be the catch-all default owned by
    exactly that owner."""
    problems: list[str] = []
    rules = []
    for number, raw in enumerate(text.splitlines(), start=1):
        tokens = _code_owner_tokens(raw)
        if not tokens:
            continue
        pattern, *owners = tokens
        rules.append((number, pattern, owners))
        if not owners:
            problems.append(f"{CODE_OWNERS_PATH}:{number}: '{pattern}' has no owners, leaving matching paths unowned")
        elif REQUIRED_CODE_OWNER not in owners:
            problems.append(f"{CODE_OWNERS_PATH}:{number}: '{pattern}' replaces the owners without {REQUIRED_CODE_OWNER}")
    if not rules:
        problems.append(f"{CODE_OWNERS_PATH} has no rules")
    elif rules[0][1:] != ("*", [REQUIRED_CODE_OWNER]):
        problems.append(f"{CODE_OWNERS_PATH}: the first rule must be exactly '* {REQUIRED_CODE_OWNER}'")
    return problems


def check_code_owners(errors: list[str]) -> None:
    path = ROOT / CODE_OWNERS_PATH
    for ignored in IGNORED_CODE_OWNERS_PATHS:
        if (ROOT / ignored).exists():
            fail(f"{ignored} is ignored by GitHub while {CODE_OWNERS_PATH} exists; keep a single CODEOWNERS file", errors)
    if not path.is_file():
        fail(f"Missing {CODE_OWNERS_PATH}", errors)
        return
    data = path.read_bytes()
    if len(data) > CODE_OWNERS_MAX_BYTES:
        fail(f"{CODE_OWNERS_PATH} exceeds GitHub's 3 MB limit and would be ignored", errors)
    for problem in code_owner_problems(data.decode("utf-8")):
        fail(problem, errors)


def required_check_name_problems(workflows: dict[str, str]) -> list[str]:
    """Each required check name is the ``name:`` of exactly one job across all workflows."""
    seen: dict[str, list[str]] = {name: [] for name in REQUIRED_CHECK_NAMES}
    for workflow, text in sorted(workflows.items()):
        for match in re.finditer(r"^    name: (.+?)\s*$", text, re.M):
            name = match.group(1).strip().strip("'\"")
            if name in seen:
                seen[name].append(workflow)
    return [
        f"required check '{name}' is produced by {len(found)} workflow jobs ({', '.join(found) or 'none'}), not exactly one"
        for name, found in seen.items()
        if len(found) != 1
    ]


def check_required_check_names(errors: list[str]) -> None:
    workflows = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    }
    for problem in required_check_name_problems(workflows):
        fail(problem, errors)


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


_WINDOWS_CPU_BUILD_TOOLCHAIN_SHAPES = {
    "bootstrapperSha256": re.compile(r"^[0-9a-f]{64}$"),
    "compilerVersion": re.compile(r"^19\.\d+\.\d+\.\d+$"),
    "linkerVersion": re.compile(r"^14\.\d+\.\d+\.\d+$"),
    "msvcToolset": re.compile(r"^\d+\.\d+$"),
    "windowsSdk": re.compile(r"^\d+\.\d+\.\d+\.\d+$"),
}


def check_windows_cpu_build_toolchain(errors: list[str]) -> None:
    """Keep the pinned Windows CPU MMCV build toolchain identical across its three records.

    The offline binary catalogue, the dependency policy and the Task 12 workflow
    each state the fixed-version Build Tools bootstrapper and the exact compiler
    and linker builds. The committed Windows CPU lock is reproducible only under
    that compiler, so any one record drifting from the others fails closed.
    """
    catalog = _read_json_or_none(ROOT / "config/dependencies/offline-binary-catalog-v1.json")
    policy = _read_json_or_none(ROOT / "config/dependencies/offline-dependency-policy-v1.json")
    try:
        workflow = (ROOT / ".github/workflows/task12-offline-bundle.yml").read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"Cannot read the Task 12 workflow: {exc}", errors)
        return
    vision = catalog.get("visionRuntime") if isinstance(catalog, dict) else None
    toolchain = vision.get("windowsCpuBuildToolchain") if isinstance(vision, dict) else None
    if not isinstance(toolchain, dict):
        fail("Offline binary catalogue has no Windows CPU build toolchain.", errors)
        return
    for field, shape in _WINDOWS_CPU_BUILD_TOOLCHAIN_SHAPES.items():
        value = toolchain.get(field)
        if not isinstance(value, str) or shape.fullmatch(value) is None:
            fail(f"Windows CPU build toolchain {field} is not a frozen identity.", errors)
            return
    url = toolchain.get("bootstrapperUrl")
    sha256 = toolchain["bootstrapperSha256"]
    if not isinstance(url, str) or not url.startswith("https://download.visualstudio.microsoft.com/") \
            or f"/{sha256}/" not in url:
        fail("Windows CPU build toolchain bootstrapper URL is not the pinned Microsoft payload.", errors)
        return
    if toolchain.get("platformVariant") != "windows-x86_64-cpu":
        fail("Windows CPU build toolchain names the wrong platform variant.", errors)
    policy_id = toolchain.get("policyId")
    entries = policy.get("nativeAndToolchain", []) if isinstance(policy, dict) else []
    entry = next((item for item in entries if isinstance(item, dict) and item.get("id") == policy_id), None)
    if entry is None:
        fail(f"Windows CPU build toolchain references unknown policy {policy_id!r}.", errors)
    else:
        verification = str(entry.get("verification", ""))
        for value in (sha256, toolchain["compilerVersion"], toolchain["linkerVersion"]):
            if value not in verification:
                fail(f"Dependency policy {policy_id} does not state the pinned {value}.", errors)
    # The workflow is where the pin takes effect.
    for required in (
        f"MAVI_VS_BUILDTOOLS_URL: {url}",
        f"MAVI_VS_BUILDTOOLS_SHA256: {sha256}",
        f'if ($clVersion -ne "{toolchain["compilerVersion"]}")',
        f'if ($linkVersion -ne "{toolchain["linkerVersion"]}")',
        f"x64 {toolchain['windowsSdk']} -vcvars_ver={toolchain['msvcToolset']}",
    ):
        if required not in workflow:
            fail(f"Task 12 workflow does not carry the catalogued Windows CPU toolchain pin: {required}", errors)


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
        "vision-job-complete-v3.1", "vision-job-finalization-response-v3.1",
        "vision-job-complete-v3.2", "vision-job-finalization-response-v3.2",
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
    check_completion_v32_contract(errors)


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

    # Completion 3.1 is the 3.0 body under the asynchronous exchange version and nothing
    # else (S1.4 B3 plan section 5.1): the schemas may differ only in title and version.
    v31 = json.loads((schemas / "vision-job-complete-v3.1.schema.json").read_text())
    expected = json.loads(json.dumps(v3))
    expected["title"] = "vision-job-complete-v3.1"
    expected["properties"]["schemaVersion"] = {"const": "3.1"}
    if v31 != expected:
        fail("Completion v3.1 schema must equal v3 apart from its title and schemaVersion const.", errors)
    example_v3 = (ROOT / "contracts/examples/vision-job-complete-v3.example.json").read_text(encoding="utf-8")
    example_v31 = (ROOT / "contracts/examples/vision-job-complete-v3.1.example.json").read_text(encoding="utf-8")
    if example_v31 != example_v3.replace('"schemaVersion": "3.0"', '"schemaVersion": "3.1"', 1):
        fail("Completion v3.1 example must be the v3 golden example with only its schemaVersion changed.", errors)

    digest = json.loads((ROOT / "contracts/test-vectors/vision-job-complete-v3-digest.json").read_text())
    example_sha = hashlib.sha256((ROOT / digest["example"]).read_bytes()).hexdigest()
    if example_sha != digest["exampleSha256"]:
        fail("Completion v3 golden example changed without re-pinning its digest vector.", errors)
    if not re.fullmatch(r"[0-9a-f]{64}", digest.get("completionDigest", "")):
        fail("Completion v3 digest vector must pin a lower-case SHA-256 digest.", errors)


# Completion 3.2 (Stage 2 S2a plan P-7, section 4.5): the 3.1 body plus five
# component-identity provenance members. This is the one statement of that delta;
# the published 3.2 schema must equal it applied to the published 3.1 schema.
COMPLETION_V32_CAPABILITY_IDS = (
    "detector", "embedding", "ocr", "person-attributes", "plate-detector", "vehicle-attributes",
)
COMPLETION_V32_REQUIRED_PROVENANCE = ("capabilityId", "modelPackId", "runtimePackSource", "componentBindingSha256")
COMPLETION_V32_EXAMPLES = (
    "vision-job-complete-v3.2.example.json",
    "vision-job-complete-v3.2-unpacked-environment.example.json",
)


def expected_completion_v32_schema(v31: dict) -> dict:
    schema = json.loads(json.dumps(v31))
    schema["title"] = "vision-job-complete-v3.2"
    schema["properties"]["schemaVersion"] = {"const": "3.2"}
    defs = schema["$defs"]
    defs["capabilityId"] = {
        "$comment": "Closed capability registry; mirrored by mavi_vision.runtime.capabilities and VisionRuntimeProvenanceParser.",
        "type": "string",
        "enum": list(COMPLETION_V32_CAPABILITY_IDS),
    }
    # Fixed lengths as well as patterns: Python's re treats '$' as matching before a
    # trailing newline, exactly why sha256 carries min/maxLength.
    defs["modelPackId"] = {"type": "string", "minLength": 78, "maxLength": 78, "pattern": "^mavi-model-v2-[0-9a-f]{64}$"}
    defs["runtimePackId"] = {"type": "string", "minLength": 80, "maxLength": 80, "pattern": "^mavi-runtime-v2-[0-9a-f]{64}$"}
    provenance = defs["provenance"]
    provenance["properties"].update({
        "capabilityId": {"$ref": "#/$defs/capabilityId"},
        "modelPackId": {"$ref": "#/$defs/modelPackId"},
        "runtimePackId": {"anyOf": [{"$ref": "#/$defs/runtimePackId"}, {"type": "null"}]},
        "runtimePackSource": {"enum": ["installed-pack", "unpacked-environment"]},
        "componentBindingSha256": {"$ref": "#/$defs/sha256"},
    })
    provenance["required"] = [*provenance["required"], *COMPLETION_V32_REQUIRED_PROVENANCE]
    provenance["allOf"] = [
        *provenance["allOf"],
        {
            "if": {"properties": {"runtimePackSource": {"const": "installed-pack"}}, "required": ["runtimePackSource"]},
            "then": {"required": ["runtimePackId"], "properties": {"runtimePackId": {"$ref": "#/$defs/runtimePackId"}}},
        },
        {
            # Unpacked execution names no Runtime Pack and is never verified (ADR-014).
            "if": {"properties": {"runtimePackSource": {"const": "unpacked-environment"}}, "required": ["runtimePackSource"]},
            "then": {"properties": {"runtimePackId": {"type": "null"}, "verificationStatus": {"const": "unverified"}}},
        },
    ]
    return schema


def expected_finalization_response_v32_schema(v31: dict) -> dict:
    schema = json.loads(json.dumps(v31))
    schema["title"] = "vision-job-finalization-response-v3.2"
    schema["description"] = schema["description"].replace("Completion 3.1 acknowledgement", "Completion 3.2 acknowledgement", 1)
    schema["properties"]["schemaVersion"] = {"const": "3.2"}
    return schema


def completion_v32_invalid_cases() -> list[dict]:
    """The shared 3.2 negative corpus, each case applied to its golden example."""
    bases = {
        "installed": "contracts/examples/vision-job-complete-v3.2.example.json",
        "unpacked": "contracts/examples/vision-job-complete-v3.2-unpacked-environment.example.json",
    }
    corpus = json.loads((ROOT / "contracts/test-vectors/control-plane-v3.2-invalid.json").read_text())
    cases = []
    for case in corpus["cases"]:
        payload = json.loads((ROOT / bases[case["base"]]).read_text())
        if "schemaVersion" in case:
            payload["schemaVersion"] = case["schemaVersion"]
        for field in case.get("remove", []):
            del payload["provenance"][field]
        payload["provenance"].update(case.get("set", {}))
        cases.append({"name": case["name"], "code": case["code"], "payload": payload})
    return cases


def check_completion_v32_contract(errors: list[str]) -> None:
    """Completion 3.2: exactly the pinned delta over 3.1, and its golden digest vectors."""
    schemas = ROOT / "contracts/schemas"
    v31 = json.loads((schemas / "vision-job-complete-v3.1.schema.json").read_text())
    v32 = json.loads((schemas / "vision-job-complete-v3.2.schema.json").read_text())
    if v32 != expected_completion_v32_schema(v31):
        fail("Completion v3.2 schema must equal v3.1 plus the pinned component-identity delta.", errors)
    response_v31 = json.loads((schemas / "vision-job-finalization-response-v3.1.schema.json").read_text())
    response_v32 = json.loads((schemas / "vision-job-finalization-response-v3.2.schema.json").read_text())
    if response_v32 != expected_finalization_response_v32_schema(response_v31):
        fail("Finalization response v3.2 schema must equal v3.1 apart from title, description and version.", errors)

    validator = jsonschema.Draft202012Validator(v32, format_checker=jsonschema.FormatChecker())
    for name in COMPLETION_V32_EXAMPLES:
        example = json.loads((ROOT / "contracts/examples" / name).read_text())
        for error in validator.iter_errors(example):
            fail(f"Contract example {name} is invalid: {error.message}", errors)

    for case in completion_v32_invalid_cases():
        schema = {"3.0": "vision-job-complete-v3", "3.1": "vision-job-complete-v3.1", "3.2": "vision-job-complete-v3.2"}[
            case["payload"]["schemaVersion"]]
        case_validator = jsonschema.Draft202012Validator(
            json.loads((schemas / f"{schema}.schema.json").read_text()), format_checker=jsonschema.FormatChecker())
        if not list(case_validator.iter_errors(case["payload"])):
            fail(f"Invalid completion v3.2 case was accepted by the {schema} schema: {case['name']}", errors)

    vectors = json.loads((ROOT / "contracts/test-vectors/vision-job-complete-v3.2-digest.json").read_text())["vectors"]
    if sorted(vector["example"] for vector in vectors) != sorted(f"contracts/examples/{name}" for name in COMPLETION_V32_EXAMPLES):
        fail("Completion v3.2 digest vectors must pin exactly the installed-pack and unpacked-environment examples.", errors)
    for vector in vectors:
        example_sha = hashlib.sha256((ROOT / vector["example"]).read_bytes()).hexdigest()
        if example_sha != vector.get("exampleSha256"):
            fail(f"Completion v3.2 example {vector['example']} changed without re-pinning its digest vector.", errors)
        if not re.fullmatch(r"[0-9a-f]{64}", vector.get("completionDigest", "")):
            fail("Completion v3.2 digest vectors must pin lower-case SHA-256 digests.", errors)


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
    """Delegate to the one release-network-locator rule in ``mavi_vision.runtime.manifest``."""
    if str(VISION_ROOT) not in sys.path:
        sys.path.insert(0, str(VISION_ROOT))
    from mavi_vision.runtime.manifest import find_release_network_hazard as _find

    return _find(text)


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
        if suffix in PROHIBITED_EVIDENCE_IMAGE_SUFFIXES and any(
            relative.as_posix().startswith(area + "/") for area in PRIVATE_EVIDENCE_AREAS
        ):
            fail(f"Image file tracked in an S2c corpus area (evidence crops stay outside Git): {relative}", errors)


def check_vision_release_metadata(
    errors: list[str],
    *,
    root: Path = ROOT,
    tracked: list[Path] | None = None,
) -> None:
    """Validate the vision release metadata as one component-binding-v2 composition.

    Plan §6 (S2a.3). Every file under the release roots is loaded by the one v2
    loader (a v1 file fails, it is never read); the binding is cross-checked
    against the runtime family's P-17 variant classes and tracked locks, the
    Model Pack manifests (by derived id), the qualification records and the live
    pipeline profiles, with the same relationship rules the runtime resolver
    applies (``check_record_identity``, ``check_record_policies``,
    ``load_role_family``). ``root``/``tracked`` exist for the negative fixtures.
    """
    if str(VISION_ROOT) not in sys.path:
        sys.path.insert(0, str(VISION_ROOT))

    try:
        from mavi_vision.runtime.binding import load_component_binding
        from mavi_vision.runtime.component_relationships import check_record_variants
        from mavi_vision.runtime.manifest import (
            ReleaseMetadataError,
            sha256_release_file,
            validate_release_text_file,
        )
        from mavi_vision.runtime.model_manifest_v2 import load_model_manifest_v2
        from mavi_vision.runtime.profile import (
            load_pipeline_profile,
            validate_profile_against_manifest,
        )
        from mavi_vision.runtime.qualification import verify_runtime_release_locks
        from mavi_vision.runtime.qualification_v2 import (
            load_capability_gate_sets,
            load_qualification_record_v2,
        )
        from mavi_vision.runtime.resolver import (
            DETECTOR_CAPABILITY,
            check_capability_input_contract,
            check_record_identity,
            check_record_policies,
            load_role_family,
        )
        from mavi_vision.runtime.runtime_profile_v2 import load_runtime_profile_v2
    except ImportError as exc:
        fail(f"Vision release metadata tooling could not be imported: {exc}", errors)
        return

    manifest_root = root / "models/manifests"
    qualification_root = root / "models/qualifications"
    pipeline_root = root / "src/vision/config/pipelines"
    runtime_root = root / "src/vision/runtime"
    binding_root = root / "src/vision/config/components"
    release_roots = [manifest_root, qualification_root, pipeline_root, runtime_root, binding_root]

    def rel(path: Path) -> str:
        return path.relative_to(root).as_posix()

    tracked = tracked_files() if tracked is None else tracked
    tracked_set = set(tracked)
    release_files = sorted(
        file_path
        for file_path in tracked
        if file_path.suffix.lower() in {".json", ".lock"}
        and any(file_path.is_relative_to(release_root) for release_root in release_roots)
    )
    for file_path in release_files:
        try:
            payload = validate_release_text_file(file_path)
        except ReleaseMetadataError as exc:
            fail(f"Release text is not deterministic UTF-8/LF: {rel(file_path)} ({exc.code})", errors)
            continue
        hazard = find_release_network_hazard(payload.decode("utf-8"))
        if hazard is not None:
            fail(f"Release metadata contains an online resolver locator {hazard!r}: {rel(file_path)}", errors)
        if file_path.suffix.lower() == ".lock":
            check_runtime_lock_file(file_path, errors)

    def json_under(directory: Path) -> list[Path]:
        return sorted(path for path in tracked if path.suffix.lower() == ".json" and path.is_relative_to(directory))

    runtime_json_paths = json_under(runtime_root)
    for path in runtime_json_paths:
        if path.name != "runtime.json":
            fail(f"Unrecognized runtime release JSON must not bypass validation: {rel(path)}", errors)

    # ---- 1. Model Pack manifests, by derived id (P-3) and by modelId.
    manifests: dict[str, tuple[Path, object, str]] = {}
    manifests_by_model: dict[str, tuple[Path, object, str]] = {}
    pack_directories: dict[str, str] = {}
    for path in json_under(manifest_root):
        try:
            manifest = load_model_manifest_v2(path)
            manifest_hash = sha256_release_file(path)
        except ReleaseMetadataError as exc:
            fail(f"Model manifest invalid (v2 only; a v1 manifest is refused): {rel(path)} ({exc.code})", errors)
            continue
        if manifest.model_pack_id in manifests:
            fail(f"Two manifests derive one modelPackId {manifest.model_pack_id}: {rel(path)}", errors)
            continue
        if manifest.model_id in manifests_by_model:
            fail(f"Duplicate modelId in release manifests: {manifest.model_id}", errors)
            continue
        if manifest.pack_directory in pack_directories:
            fail(
                f"Model pack directory {manifest.pack_directory} is shared by {rel(path)} and "
                f"{pack_directories[manifest.pack_directory]} (P-10)",
                errors,
            )
            continue
        pack_directories[manifest.pack_directory] = rel(path)
        manifests[manifest.model_pack_id] = (path, manifest, manifest_hash)
        manifests_by_model[manifest.model_id] = (path, manifest, manifest_hash)

    # ---- 2. Pipeline profiles (kept v1 schema; P-9 keeps the path setting).
    profiles: dict[str, tuple[Path, object, str]] = {}
    for path in json_under(pipeline_root):
        try:
            profile = load_pipeline_profile(path)
            profile_hash = sha256_release_file(path)
        except ReleaseMetadataError as exc:
            fail(f"Pipeline profile invalid: {rel(path)} ({exc.code})", errors)
            continue
        if profile.profile_id in profiles:
            fail(f"Duplicate profileId in release profiles: {profile.profile_id}", errors)
            continue
        profiles[profile.profile_id] = (path, profile, profile_hash)
    for profile_path, profile, _hash in profiles.values():
        entry = manifests_by_model.get(profile.model_id)
        if entry is None:
            fail(f"Pipeline profile {profile.profile_id} references unknown modelId {profile.model_id}.", errors)
            continue
        manifest = entry[1]
        try:
            section = manifest.detector_section()
            validate_profile_against_manifest(profile, model_id=manifest.model_id, class_vocabulary=section.class_vocabulary)
        except ReleaseMetadataError as exc:
            fail(f"Pipeline profile relationship invalid: {rel(profile_path)} ({exc.code})", errors)

    # ---- 3. Runtime family profiles (v2 only), locks verified and tracked.
    runtimes: dict[str, tuple[Path, object]] = {}
    for path in [path for path in runtime_json_paths if path.name == "runtime.json"]:
        try:
            runtime_profile = load_runtime_profile_v2(path)
            verified_locks = verify_runtime_release_locks(path, runtime_profile)
        except ReleaseMetadataError as exc:
            fail(f"Runtime profile invalid (v2 only; a v1 profile is refused): {rel(path)} ({exc.code})", errors)
            continue
        for variant, lock_path in verified_locks.items():
            if lock_path not in tracked_set:
                fail(f"Qualified runtime lock for {variant} is not tracked: {rel(lock_path)}", errors)
        if runtime_profile.runtime_profile_id in runtimes:
            fail(f"Duplicate runtimeProfileId: {runtime_profile.runtime_profile_id}", errors)
            continue
        runtimes[runtime_profile.runtime_profile_id] = (path, runtime_profile)

    # ---- 4. Qualification records (v2 only), gate sets enforced (P-12).
    records: dict[str, tuple[Path, object, str]] = {}
    try:
        gate_sets = load_capability_gate_sets(root / "config/acceptance/capability-gate-sets-v1.json")
    except ReleaseMetadataError as exc:
        fail(f"Capability gate sets invalid: {exc.code}", errors)
        gate_sets = None
    if gate_sets is not None:
        for path in json_under(qualification_root):
            try:
                record = load_qualification_record_v2(path, gate_sets=gate_sets)
                record_hash = sha256_release_file(path)
            except ReleaseMetadataError as exc:
                fail(f"Qualification record invalid (v2 only; a v1 record is refused): {rel(path)} ({exc.code})", errors)
                continue
            if record.qualification_id in records:
                fail(f"Duplicate qualificationId in qualification records: {record.qualification_id}", errors)
                continue
            records[record.qualification_id] = (path, record, record_hash)

    # ---- 5. The component binding: exactly one, v2 only.
    binding_paths = json_under(binding_root)
    if not binding_paths:
        fail("No component binding is tracked under src/vision/config/components.", errors)
        return
    if len(binding_paths) > 1:
        fail(
            "binding_multiple_not_supported: more than one component binding is tracked "
            f"({', '.join(rel(path) for path in binding_paths)}) and no release-profile overlay exists.",
            errors,
        )
        return
    (binding_path,) = binding_paths
    try:
        binding = load_component_binding(binding_path)
    except ReleaseMetadataError as exc:
        fail(f"Component binding invalid (v2 only; a v1 binding is refused): {rel(binding_path)} ({exc.code})", errors)
        return

    bound_records: set[str] = set()
    for role in binding.roles.values():
        # Family known, P-2, locks verified, P-17 classes from the tracked lock
        # files, binding variants == class-B set, every pinned id lock-derived.
        try:
            family = load_role_family(binding=binding, role_id=role.role_id, overlay_root=root)
        except ReleaseMetadataError as exc:
            fail(f"Component binding role {role.role_id} is inconsistent with its runtime family: {exc.code}", errors)
            continue
        runtime_profile = family.runtime_profile
        binding_variants = binding.family_variants(role.runtime_pack_family_id)
        for capability_binding in binding.bindings_for_role(role.role_id):
            capability_id = capability_binding.capability_id
            manifest_entry = manifests.get(capability_binding.model_pack_id)
            if manifest_entry is None:
                fail(
                    f"Capability binding {role.role_id}:{capability_id} names modelPackId "
                    f"{capability_binding.model_pack_id}, which no manifest derives.",
                    errors,
                )
                continue
            manifest_path, manifest, manifest_hash = manifest_entry
            if capability_id not in manifest.capability_ids:
                fail(f"Model Pack {manifest.model_id} does not provide bound capability {capability_id}.", errors)
                continue
            if role.runtime_pack_family_id not in manifest.runtime_pack_family_ids:
                fail(f"Model Pack {manifest.model_id} is not compatible with family {role.runtime_pack_family_id}.", errors)
                continue
            try:
                check_capability_input_contract(manifest=manifest, capability_id=capability_id)
            except ReleaseMetadataError as exc:
                fail(f"Model Pack {manifest.model_id} input contract is not the one {capability_id} consumes ({exc.code}).", errors)
                continue
            record_entry = records.get(capability_binding.qualification_id)
            if record_entry is None:
                fail(
                    f"Capability binding {role.role_id}:{capability_id} names qualification "
                    f"{capability_binding.qualification_id}, which no record declares.",
                    errors,
                )
                continue
            record_path, record, _record_hash = record_entry
            bound_records.add(record.qualification_id)
            try:
                check_record_identity(
                    record=record,
                    manifest=manifest,
                    manifest_sha256=manifest_hash,
                    capability_id=capability_id,
                    model_pack_id=capability_binding.model_pack_id,
                    runtime_pack_family_id=role.runtime_pack_family_id,
                    runtime_profile_sha256=family.runtime_profile_sha256,
                )
                check_record_variants(
                    record=record,
                    binding_variants=binding_variants,
                    variant_classes=family.variant_classes,
                )
            except ReleaseMetadataError as exc:
                fail(f"Qualification relationship invalid: {rel(record_path)} ({exc.code})", errors)
                continue
            # Pipeline policy reconciled live against the tracked profile (plan §17).
            profile_entry = profiles.get(record.pipeline_profile_id or "")
            if capability_id == DETECTOR_CAPABILITY and profile_entry is None:
                fail(
                    f"Qualification {record.qualification_id} names unknown pipeline profile "
                    f"{record.pipeline_profile_id}.",
                    errors,
                )
                continue
            if profile_entry is not None:
                try:
                    check_record_policies(
                        record=record,
                        capability_id=capability_id,
                        pipeline_profile_id=profile_entry[1].profile_id,
                        pipeline_profile_sha256=profile_entry[2],
                    )
                except ReleaseMetadataError as exc:
                    fail(f"Qualification policy invalid: {rel(record_path)} ({exc.code})", errors)
            # Retained anti-promotion rules (plan §6.6).
            if manifest.verification_status == "verified" and runtime_profile.qualification_status != "qualified":
                fail(
                    f"Verified manifest {manifest.model_id} requires a qualified runtime profile; "
                    f"found {runtime_profile.qualification_status}.",
                    errors,
                )
            if manifest.verification_status == "unverified" and (
                record.overall_result != "pending"
                or any(variant.status != "pending" for variant in record.variants.values())
            ):
                fail(
                    f"Qualification {record.qualification_id} must remain pending while manifest "
                    f"{manifest.model_id} is unverified.",
                    errors,
                )

    for manifest_path, manifest, _hash in manifests.values():
        if manifest.verification_status == "unverified" and manifest.qualification_id is not None:
            fail(f"Unverified manifest {manifest.model_id} must not claim a qualification ID.", errors)
    for qualification_id, (record_path, _record, _hash) in records.items():
        if qualification_id not in bound_records:
            fail(f"Qualification record {rel(record_path)} is bound by no capability binding.", errors)
    bound_packs = {item.model_pack_id for item in binding.capability_bindings}
    for model_pack_id, (manifest_path, _manifest, _hash) in manifests.items():
        if model_pack_id not in bound_packs:
            fail(f"Model manifest {rel(manifest_path)} is bound by no capability binding.", errors)


def check_model_selection_protocols(errors: list[str]) -> None:
    sys.path.insert(0, str(ROOT / "tools/qualification"))
    from model_selection import credibility, s2c_artifacts
    try:
        credibility.validate_repository(ROOT)
        s2c_artifacts.validate_repository(ROOT)
        for path in (ROOT / "tools/qualification/model_selection/schemas").glob("*.schema.json"):
            if jsonschema is not None:
                jsonschema.Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        fail(f"Model-selection protocol refusal: {exc}", errors)


def main() -> int:
    errors: list[str] = []
    check_required_paths(errors)
    check_code_owners(errors)
    check_required_check_names(errors)
    check_project_references(errors)
    check_dependency_policy(errors)
    check_offline_binary_catalog(errors)
    check_windows_cpu_build_toolchain(errors)
    check_contracts(errors)
    check_phase1_acceptance_assets(errors)
    check_production_urls(errors)
    check_tracked_binaries_and_secrets(errors)
    check_vision_release_metadata(errors)
    check_model_selection_protocols(errors)

    if errors:
        print("MAVI repository verification FAILED")
        for error in errors:
            print(f" - {error}")
        return 1

    print("MAVI repository verification PASSED")
    print(f" - required paths: {len(REQUIRED_PATHS)}")
    print(f" - project boundaries: {len(ALLOWED_REFERENCES)}")
    print(f" - code owners: every rule keeps {REQUIRED_CODE_OWNER}")
    print(f" - required checks: {', '.join(REQUIRED_CHECK_NAMES)} each from exactly one job")
    print(" - direct dependency/offline packaging policy: synchronized")
    print(" - offline binary/version catalog: synchronized")
    print(" - ordinary Git executable/archive/large-file gate: clean")
    print(" - contract examples: 13 (incl. completion v3 and v3.2 goldens, digest pins and invalid vectors)")
    print(" - Task-17 acceptance schemas/configuration: validated")
    print(" - production Internet URL scan: clean")
    print(" - tracked model/media/secret/wheel scan: clean")
    print(" - Task-10 release metadata: every tracked record and relationship validated")
    print(" - Task-12 release resolver/lock scan: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
