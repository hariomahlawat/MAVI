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
    "contracts/schemas/vision-job-complete-v3.3.schema.json",
    "contracts/schemas/vision-job-finalization-response-v3.3.schema.json",
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
    escaped with a backslash. Only a whole line starting with '#' is a comment;
    rule lines containing '#' are refused by ``code_owner_problems``."""
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
    return tokens


def code_owner_problems(text: str) -> list[str]:
    """GitHub applies the last matching CODEOWNERS rule, so every rule must keep
    the required owner, and the first rule must be the catch-all default owned by
    exactly that owner."""
    problems: list[str] = []
    rules = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if raw.lstrip().startswith("#"):
            continue  # a comment line
        tokens = _code_owner_tokens(raw)
        if not tokens:
            continue
        if "#" in raw:
            # GitHub has no inline comments: it may skip such a line as invalid
            # (leaving its paths to an earlier rule, or unowned) or read the text
            # as owners. Either way the line does not say what it appears to.
            problems.append(f"{CODE_OWNERS_PATH}:{number}: '#' on a rule line; CODEOWNERS has no inline comments")
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


QUALITY_SCOPE_FILE = "tools/ci/quality-scope.json"


def quality_scope_problems(scope_text: str, workflow: str) -> list[str]:
    """The Quality Gate's scope list and its workflow describe the same lanes:
    every lane the list declares gates a job (`if: needs.scope.outputs.<lane>
    != 'false'`), is exported by the scope job and is required by `quality`
    with that same output; and no job is gated by a lane the list does not
    declare. A lane missing on either side would be run never or required never."""
    problems: list[str] = []
    try:
        lanes = set(json.loads(scope_text)["lanes"])
    except (ValueError, KeyError, TypeError) as exc:
        return [f"{QUALITY_SCOPE_FILE}: cannot read its lanes ({exc})"]
    gated = set(re.findall(r"^    if: needs\.scope\.outputs\.([a-z0-9-]+) != 'false'$", workflow, re.M))
    exported = set(re.findall(r"^      ([a-z0-9-]+): \$\{\{ steps\.scope\.outputs\.\1 \}\}$", workflow, re.M))
    required = set(re.findall(r"'\$\{\{ needs\.scope\.outputs\.([a-z0-9-]+) \}\}'", workflow))
    for lane in sorted(lanes - gated):
        problems.append(f"{QUALITY_SCOPE_FILE} declares lane '{lane}', which gates no job in quality-gate.yml")
    for lane in sorted(gated - lanes):
        problems.append(f"quality-gate.yml gates a job on scope lane '{lane}', which {QUALITY_SCOPE_FILE} does not declare")
    for lane in sorted(lanes - exported):
        problems.append(f"quality-gate.yml's scope job does not export lane '{lane}'")
    for lane in sorted(lanes - required):
        problems.append(f"quality-gate.yml's quality job does not require lane '{lane}' by its scope output")
    return problems


VISUAL_QA_TESTS = "tools/web-visual-qa/test"


def visual_test_group_problems(workflow: str, test_files: dict[str, str]) -> list[str]:
    """Every harness test file that declares end-to-end tests with `e2eIt` is
    named in the workflow's end-to-end step: such a test is skipped in the unit
    group by design, so a file the end-to-end groups never run would skip it in
    every group, silently."""
    step = re.search(r"- name: Test the harness \(end-to-end group\)\n(?:.*\n)*?\s+run: (.+)\n", workflow)
    if step is None:
        return ["quality-gate.yml has no 'Test the harness (end-to-end group)' step"]
    named = set(re.findall(r"tools/web-visual-qa/test/[A-Za-z0-9_.-]+\.mjs", step.group(1)))
    problems: list[str] = []
    for name, text in sorted(test_files.items()):
        if re.search(r"\be2eIt\b", text) and f"{VISUAL_QA_TESTS}/{name}" not in named:
            problems.append(f"{VISUAL_QA_TESTS}/{name} declares end-to-end tests (e2eIt) but is not run by the workflow's end-to-end step")
    for path in sorted(named):
        if path.split("/")[-1] not in test_files:
            problems.append(f"quality-gate.yml's end-to-end step names {path}, which does not exist")
    return problems


def check_quality_scope(errors: list[str]) -> None:
    try:
        scope_text = (ROOT / QUALITY_SCOPE_FILE).read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/quality-gate.yml").read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"Cannot read the Quality Gate scope or workflow: {exc}", errors)
        return
    for problem in quality_scope_problems(scope_text, workflow):
        fail(problem, errors)
    test_files = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted((ROOT / VISUAL_QA_TESTS).glob("*.test.mjs"))
    }
    for problem in visual_test_group_problems(workflow, test_files):
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


POC_CUDA_CONTRACT = "config/vision/windows-cuda-development-build-v2.json"
POC_CUDA_LOCK = "src/vision/runtime/mmdetection-phase1-v1/windows-x86_64-cuda-sm75-sm89.lock"


def check_poc_cuda_build_contract(errors: list[str]) -> None:
    """Keep the PoC sm_75;sm_89 build contract (plan D9, ADR-020) honest.

    It must stay scoped to poc-single-host, keep CUDA fail-closed, agree with
    its catalogue entry and with the frozen v1 toolchain identity it shares,
    and its lock may differ from the v1 CUDA lock only in the MMCV wheel.
    """
    contract_path = ROOT / POC_CUDA_CONTRACT
    lock_path = ROOT / POC_CUDA_LOCK
    contract = _read_json_or_none(contract_path)
    if contract is None:
        if lock_path.exists():
            fail("The PoC sm_75;sm_89 CUDA lock exists without its v2 build contract.", errors)
        return
    if not isinstance(contract, dict) or contract.get("schemaVersion") != "mavi-windows-cuda-development-build-v2":
        fail("Windows CUDA development build contract v2 is invalid or has an unsupported schema.", errors)
        return
    scope = contract.get("deploymentProfileScope")
    if not isinstance(scope, dict) or scope.get("profiles") != ["poc-single-host"]:
        fail("Windows CUDA build contract v2 must serve the poc-single-host profile only.", errors)
    runtime_policy = contract.get("runtimePolicy")
    if not isinstance(runtime_policy, dict) or any(
        runtime_policy.get(name) is not False
        for name in ("explicitCudaMayFallbackToCpu", "cudaToolkitRequiredAtRuntime", "compilerRequiredAtRuntime")
    ):
        fail("Windows CUDA build contract v2 must keep CUDA fail-closed and the build toolchain out of the runtime.", errors)
    qualification = contract.get("qualification")
    if not isinstance(qualification, dict) or qualification.get("status") != "unqualified":
        fail("Windows CUDA build contract v2 must not claim a qualification; A7 earns it on the host.", errors)
    mmcv = contract.get("mmcv") if isinstance(contract.get("mmcv"), dict) else {}
    arch_list = (mmcv.get("buildEnvironment") or {}).get("TORCH_CUDA_ARCH_LIST")
    targets = contract.get("targetGpus") if isinstance(contract.get("targetGpus"), list) else []
    expected_arch_list = ";".join(str(item.get("computeCapability")) for item in targets if isinstance(item, dict)) + "+PTX"
    if arch_list != contract.get("torchCudaArchList") or arch_list != expected_arch_list:
        fail("Windows CUDA build contract v2 TORCH_CUDA_ARCH_LIST must spell its targetGpus.", errors)

    toolchain = contract.get("toolchain") if isinstance(contract.get("toolchain"), dict) else {}
    frozen = toolchain.get("verificationStatus") == "verified" and all(
        _frozen_toolchain_value(name, toolchain.get(name))
        for name in ("msvcToolset", "windowsSdkVersion", "cudaToolkitVersion")
    )
    if not frozen:
        fail("Windows CUDA build contract v2 has no verified, frozen toolchain identity.", errors)
    v1 = _read_json_or_none(ROOT / "config/vision/windows-cuda-development-build-v1.json")
    v1 = v1 if isinstance(v1, dict) else {}
    for key in ("platformVariant", "pythonVersion", "torchBinaryVersion", "torchvisionBinaryVersion", "cudaRuntimeFamily"):
        if contract.get(key) != v1.get(key):
            fail(f"Windows CUDA build contract v2 must keep v1's {key}; only the target GPUs differ.", errors)
    for name in ("msvcToolset", "windowsSdkVersion", "cudaToolkitVersion"):
        if toolchain.get(name) != (v1.get("toolchain") or {}).get(name):
            fail(f"Windows CUDA build contracts v1 and v2 disagree on the toolchain field '{name}'.", errors)

    catalog = _read_json_or_none(ROOT / "config/dependencies/offline-binary-catalog-v1.json")
    candidate = ((catalog or {}).get("visionRuntime") or {}).get("windowsCudaPocSm89Candidate") if isinstance(catalog, dict) else None
    if not isinstance(candidate, dict):
        fail("Offline binary catalogue has no windowsCudaPocSm89Candidate for the v2 build contract.", errors)
        return
    if candidate.get("buildContract") != POC_CUDA_CONTRACT or candidate.get("nativeAbi") != contract.get("nativeAbi"):
        fail("Offline catalogue windowsCudaPocSm89Candidate does not name the v2 contract and its native ABI.", errors)
    if candidate.get("targetComputeCapabilities") != [item.get("computeCapability") for item in targets if isinstance(item, dict)]:
        fail("Offline catalogue windowsCudaPocSm89Candidate target GPUs differ from the v2 contract.", errors)
    candidate_toolchain = candidate.get("buildToolchain") if isinstance(candidate.get("buildToolchain"), dict) else {}
    for contract_name, candidate_name in (
        ("msvcToolset", "msvcToolset"),
        ("windowsSdkVersion", "windowsSdk"),
        ("cudaToolkitVersion", "cudaToolkit"),
        ("msvcCompilerVersion", "msvcCompilerVersion"),
    ):
        if toolchain.get(contract_name) != candidate_toolchain.get(candidate_name):
            fail(f"Windows CUDA build contract v2 and its catalogue entry disagree on '{contract_name}'.", errors)
    if candidate.get("deploymentProfileScope") != ["poc-single-host"]:
        fail("Offline catalogue windowsCudaPocSm89Candidate must be scoped to poc-single-host.", errors)
    # The catalogue status is what the PoC installer discloses for this pack. Nothing
    # qualifies it yet (A7 is the bound host observation), so it is exactly this value.
    if candidate.get("status") != "built-hashed-locked" or contract.get("status") != "built-hashed-locked":
        fail("The PoC sm_75;sm_89 build must stay built-hashed-locked in its contract and catalogue until A7 qualifies it.", errors)
    # The ABI is derived from the contract by the tool that builds the pack, never typed.
    try:
        tools_vision = str(Path(__file__).resolve().parent / "vision")
        if tools_vision not in sys.path:
            sys.path.insert(0, tools_vision)
        from build_runtime_pack import derive_native_abi  # noqa: PLC0415
        derived_abi = derive_native_abi(contract)
    except Exception as exc:  # noqa: BLE001 - any refusal is a contract defect
        fail(f"Windows CUDA build contract v2 native ABI cannot be derived: {exc}", errors)
        derived_abi = None
    if derived_abi is not None and contract.get("nativeAbi") != derived_abi:
        fail("Windows CUDA build contract v2 nativeAbi is not the one its toolchain and targetGpus derive.", errors)
    if contract.get("nativeAbi") == v1.get("nativeAbi"):
        fail("Windows CUDA build contracts v1 and v2 must have different native ABIs.", errors)

    if not lock_path.exists():
        if candidate.get("lock") is not None:
            fail("Offline catalogue names a PoC sm_75;sm_89 CUDA lock that is not committed.", errors)
        return
    if not frozen:
        fail("The PoC sm_75;sm_89 CUDA lock cannot be committed before the v2 toolchain is verified.", errors)
    lock_bytes = lock_path.read_bytes()
    if candidate.get("lock") != POC_CUDA_LOCK or candidate.get("lockSha256") != hashlib.sha256(lock_bytes).hexdigest():
        fail("Offline catalogue windowsCudaPocSm89Candidate does not pin the committed PoC CUDA lock.", errors)
    # The dependency policy moves with the dependency (CLAUDE.md): its PoC entries must
    # pin the same lock and the same onnxruntime-gpu wheel as the catalogue.
    policy = _read_json_or_none(ROOT / "config/dependencies/offline-dependency-policy-v1.json")
    python_policy = ((policy or {}).get("ecosystemStrategies") or {}).get("python") or {} if isinstance(policy, dict) else {}
    policy_variant = (python_policy.get("pocCudaRuntimeVariants") or {}).get("windows-x86_64-cuda-sm75-sm89") or {}
    if policy_variant.get("lock") != POC_CUDA_LOCK or policy_variant.get("lockSha256") != hashlib.sha256(lock_bytes).hexdigest():
        fail("Offline dependency policy pocCudaRuntimeVariants does not pin the committed PoC CUDA lock.", errors)
    policy_ort = python_policy.get("pocOnnxRuntimeGpu") or {}
    catalogue_ort = ((catalog or {}).get("visionRuntime") or {}).get("onnxruntimeGpuDevelopmentCandidate") or {}
    catalogue_wheels = [item for item in catalogue_ort.get("wheels") or [] if isinstance(item, dict)]
    if (
        len(catalogue_wheels) != 1
        or policy_ort.get("requirement") != f"onnxruntime-gpu=={catalogue_ort.get('version')}"
        or policy_ort.get("wheelSha256") != catalogue_wheels[0].get("sha256")
    ):
        fail("Offline dependency policy pocOnnxRuntimeGpu and the catalogue's onnxruntime-gpu pin disagree.", errors)
    v1_lock = (ROOT / "src/vision/runtime/mmdetection-phase1-v1/windows-x86_64-cuda.lock").read_text(encoding="utf-8")

    def _without_mmcv(text: str) -> list[str]:
        return [line for line in text.splitlines() if not line.startswith("mmcv==")]

    v1_mmcv = [line for line in v1_lock.splitlines() if line.startswith("mmcv==")]
    v2_mmcv = [line for line in lock_bytes.decode("utf-8").splitlines() if line.startswith("mmcv==")]
    expected_pin = f"mmcv=={mmcv.get('version')} --hash=sha256:"
    if (
        _without_mmcv(lock_bytes.decode("utf-8")) != _without_mmcv(v1_lock)
        or len(v2_mmcv) != 1
        or len(v1_mmcv) != 1
        or v2_mmcv == v1_mmcv
        or not v2_mmcv[0].startswith(expected_pin)
        or not v1_mmcv[0].startswith(expected_pin)
    ):
        fail("The PoC sm_75;sm_89 CUDA lock must equal the v1 CUDA lock except for its own MMCV wheel hash.", errors)
    elif v2_mmcv[0].split("sha256:")[-1] != candidate.get("mmcvWheelSha256"):
        fail("Offline catalogue windowsCudaPocSm89Candidate mmcvWheelSha256 differs from the PoC CUDA lock.", errors)

    if str(VISION_ROOT) not in sys.path:
        sys.path.insert(0, str(VISION_ROOT))
    try:
        from mavi_vision.runtime.component_identity import RuntimePackIdentityInputs, runtime_pack_id
    except ImportError as exc:
        fail(f"Runtime Pack identity tooling could not be imported: {exc}", errors)
        return
    requirements = ROOT / "src/vision/runtime/mmdetection-phase1-v1/windows-x86_64-cuda.requirements.txt"
    derived = runtime_pack_id(
        RuntimePackIdentityInputs(
            platform_variant="windows-x86_64-cuda",
            python_version=str(contract.get("pythonVersion")),
            third_party_lock_sha256=hashlib.sha256(lock_bytes).hexdigest(),
            runtime_requirements_sha256=str(candidate.get("runtimeRequirementsSha256")),
            native_abi=str(contract.get("nativeAbi")),
        )
    )
    if candidate.get("runtimePackId") != derived:
        fail("Offline catalogue windowsCudaPocSm89Candidate runtimePackId does not derive from its lock and ABI.", errors)
    v1_requirements_sha = None
    binding = _read_json_or_none(ROOT / "src/vision/config/components/phase1-bindings-v2.json")
    if isinstance(binding, dict):
        for family in binding.get("runtimePacks") or []:
            entry = ((family or {}).get("variants") or {}).get("windows-x86_64-cuda")
            if isinstance(entry, dict):
                v1_requirements_sha = entry.get("runtimeRequirementsSha256")
    if not requirements.exists() or candidate.get("runtimeRequirementsSha256") != v1_requirements_sha:
        fail("The PoC sm_75;sm_89 Runtime Pack must use the v1 CUDA requirements projection.", errors)
    # The binding declares the pack as the Development build sm75-sm89 (ADR-014 amendment
    # 2026-10-29); the resolver checks its identity, this checks it is the catalogue's pack.
    declared = []
    if isinstance(binding, dict):
        for family in binding.get("runtimePacks") or []:
            for build in (((family or {}).get("developmentBuilds") or {}).get("windows-x86_64-cuda") or []):
                if isinstance(build, dict) and build.get("buildId") == "sm75-sm89":
                    declared.append(build)
    targets = [item.get("computeCapability") for item in contract.get("targetGpus") or [] if isinstance(item, dict)]
    if (
        len(declared) != 1
        or declared[0].get("runtimePackId") != candidate.get("runtimePackId")
        or declared[0].get("nativeAbi") != contract.get("nativeAbi")
        or declared[0].get("computeCapabilities") != targets
    ):
        fail("The release binding must declare the catalogue's sm_75;sm_89 pack as Development build sm75-sm89 for the contract's target GPUs.", errors)


def _read_json_or_none(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def check_development_runtime_families(policy: dict, tracked: list[Path], errors: list[str]) -> None:
    """A runtime family on a named (Development-only) graph is a declared dependency surface (Issue #225).

    Its requirements roots and its lock bytes must equal the policy's ``developmentRuntimeFamilies`` entry, so a
    library added to such a family cannot bypass the offline packaging, verification and licence record.
    """
    python = (policy.get("ecosystemStrategies") or {}).get("python") or {}
    declared = python.get("developmentRuntimeFamilies") or {}
    if not isinstance(declared, dict):
        fail("Offline dependency policy developmentRuntimeFamilies must be an object.", errors)
        return
    actual: set[str] = set()
    for path in tracked:
        relative = path.relative_to(ROOT).as_posix()
        if not (relative.startswith("src/vision/runtime/") and path.name == "runtime.json"):
            continue
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue  # the release-metadata check reports it
        if profile.get("runtimeGraph") is None:
            continue
        family = path.parent.name
        actual.add(family)
        entry = declared.get(family)
        if not isinstance(entry, dict) or entry.get("runtimeProfile") != relative:
            fail(f"Runtime family {family} is not declared in the offline dependency policy developmentRuntimeFamilies.", errors)
            continue
        for field in ("scope", "purpose", "packagedBy", "installedBy", "verification", "licences"):
            if not entry.get(field):
                fail(f"Offline dependency policy entry for {family} lacks {field}.", errors)
        variants = entry.get("variants") or {}
        locks = {lock.name[: -len(".lock")] for lock in path.parent.glob("*.lock") if lock in set(tracked)}
        if set(variants) != locks:
            fail(f"Offline dependency policy entry for {family} does not list exactly its tracked locks.", errors)
            continue
        for variant, values in variants.items():
            requirements = path.parent / f"{variant}.requirements.txt"
            lock = path.parent / f"{variant}.lock"
            roots = [line for line in requirements.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
            if sorted(values.get("requirements") or []) != sorted(roots):
                fail(f"Runtime family {family} {variant} requirements changed without the offline dependency policy.", errors)
            if values.get("lockSha256") != hashlib.sha256(lock.read_bytes()).hexdigest():
                fail(f"Runtime family {family} {variant} lock changed without the offline dependency policy.", errors)
    for family in sorted(set(declared) - actual):
        fail(f"Offline dependency policy declares runtime family {family}, which has no tracked runtime profile.", errors)


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
        if not relative.startswith(("src/", "tests/", "tools/dotnet/")):
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

    check_development_runtime_families(policy, tracked, errors)

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
    check_poc_cuda_build_contract(errors)

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
    "windowsSdkBuild": re.compile(r"^10\.0\.\d+\.\d+$"),
}
_WINDOWS_CPU_BUILD_SDK_PACKAGES = ("microsoft.windows.sdk.cpp", "microsoft.windows.sdk.cpp.x64")


def check_windows_cpu_build_toolchain(errors: list[str]) -> None:
    """Keep the pinned Windows CPU MMCV build toolchain identical across its three records.

    The offline binary catalogue, the dependency policy and the Task 12 workflow
    each state the fixed-version Build Tools bootstrapper, the exact compiler
    and linker builds and the exact Windows SDK build packages. The committed
    Windows CPU lock is reproducible only under that compiler and SDK, so any
    one record drifting from the others fails closed.
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
    sdk_build = toolchain["windowsSdkBuild"]
    if not sdk_build.startswith(toolchain["windowsSdk"].rsplit(".", 1)[0] + "."):
        fail("Windows CPU build toolchain SDK build is not a build of its windowsSdk.", errors)
        return
    packages = toolchain.get("windowsSdkPackages")
    sdk_hashes: list[str] = []
    for package_id in _WINDOWS_CPU_BUILD_SDK_PACKAGES:
        package = next(
            (item for item in packages if isinstance(item, dict) and item.get("id") == package_id),
            None,
        ) if isinstance(packages, list) else None
        package_sha = package.get("sha256") if package else None
        expected_url = (
            f"https://api.nuget.org/v3-flatcontainer/{package_id}/{sdk_build}/{package_id}.{sdk_build}.nupkg"
        )
        if not isinstance(package_sha, str) or re.fullmatch(r"[0-9a-f]{64}", package_sha) is None \
                or package.get("url") != expected_url:
            fail(f"Windows CPU build toolchain SDK package {package_id} is not a pinned NuGet payload.", errors)
            return
        sdk_hashes.append(package_sha)
    sdk_path = f"C:\\MaviBuildTools\\winsdk-{sdk_build}"
    if sdk_path not in str(toolchain.get("placement", "")):
        fail(f"Windows CPU build toolchain placement does not name the pinned SDK path {sdk_path}.", errors)
    policy_id = toolchain.get("policyId")
    entries = policy.get("nativeAndToolchain", []) if isinstance(policy, dict) else []
    entry = next((item for item in entries if isinstance(item, dict) and item.get("id") == policy_id), None)
    if entry is None:
        fail(f"Windows CPU build toolchain references unknown policy {policy_id!r}.", errors)
    else:
        verification = str(entry.get("verification", ""))
        for value in (sha256, toolchain["compilerVersion"], toolchain["linkerVersion"], sdk_build, *sdk_hashes):
            if value not in verification:
                fail(f"Dependency policy {policy_id} does not state the pinned {value}.", errors)
    # The workflow is where the pin takes effect.
    for required in (
        f"MAVI_VS_BUILDTOOLS_URL: {url}",
        f"MAVI_VS_BUILDTOOLS_SHA256: {sha256}",
        f'if ($clVersion -ne "{toolchain["compilerVersion"]}")',
        f'if ($linkVersion -ne "{toolchain["linkerVersion"]}")',
        f"x64 {toolchain['windowsSdk']} -vcvars_ver={toolchain['msvcToolset']}",
        f"MAVI_WINSDK_VERSION: {sdk_build}",
        f"MAVI_WINSDK_CPP_SHA256: {sdk_hashes[0]}",
        f"MAVI_WINSDK_CPP_X64_SHA256: {sdk_hashes[1]}",
        f"MAVI_WINSDK_PATH: {sdk_path}",
        "dotnet nuget verify --all $file",
        '"LIB={0}" -f ((@(& $keep $env:LIB) + $lib) -join ";")',
        '"INCLUDE={0}" -f ((@(& $keep $env:INCLUDE) + $include) -join ";")',
        "foreach ($entry in Get-ChildItem Env:) {",
        'throw "unpinned_windows_sdk_in_$($entry.Name)"',
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
        # PostgreSQL contrib behind the plate-text trigram index (Stage 4 PR-4).
        "pg-trgm-pg18-win-x64",
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
        "vision-job-complete-v3.3", "vision-job-finalization-response-v3.3",
        # Stage 3 S3.2 measurement artefacts (development tooling; never an API surface).
        "vehicle-subclass-measurement-export-v1",
        "vehicle-subclass-sample-v1", "vehicle-subclass-labeling-pack-v1", "vehicle-subclass-track-labels-v1",
        "vehicle-subclass-adjudication-v1", "vehicle-subclass-requirements-v1", "vehicle-subclass-measurement-v1",
        "vehicle-subclass-requirement-comparison-v1",
        # Stage 3 S3.2b media, derivation and Development-host execution artefacts.
        "vehicle-subclass-media-probe-v1", "vehicle-subclass-source-pool-v1", "vehicle-subclass-derivation-v1",
        "vehicle-subclass-ingestion-map-v1", "vehicle-subclass-t9-execution-v1",
        # Stage 3 S3.2d-1 benchmark harness contracts (development tooling; never an API surface).
        "benchmark-dataset-release-v1", "benchmark-class-mapping-v1", "benchmark-association-v1",
        "benchmark-vehicle-subclass-result-v1",
        # Stage 4 PR-3 plate control plane (ADR-013 implementation amendment 2026-10-13).
        "plate-lease-v1", "plate-complete-v1", "plate-predictions-v1",
        # PoC S4 embedding control plane (ADR-021).
        "embedding-lease-v1", "embedding-complete-v1", "embedding-text-query-lease-v1", "embedding-text-query-complete-v1",
        # PoC S6 face control plane (ADR-022).
        "face-lease-v1", "face-complete-v1", "face-query-lease-v1", "face-query-complete-v1",
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
    check_completion_v33_contract(errors)
    check_plate_contract(errors)
    check_embedding_contract(errors)
    check_face_contract(errors)


def embedding_identity(manifest_path: Path, profile_path: Path) -> tuple[str, str]:
    """ADR-021 identity: canonical JSON (sorted keys, compact, trailing LF) of the manifest and profile, and its SHA-256."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    identity = {
        "schemaVersion": "mavi-embedding-identity-v1",
        "model": {
            "id": manifest["modelId"],
            "version": manifest["modelVersion"],
            "manifestSha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "dimension": profile["dimension"],
        },
        "pipeline": {
            "id": profile["pipelineId"],
            "version": profile["pipelineVersion"],
            "sha256": hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        },
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":")) + "\n"
    return canonical, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def check_embedding_contract(errors: list[str]) -> None:
    """The embedding identity vectors re-derive from the committed files, and the examples agree with them."""
    vectors = json.loads((ROOT / "contracts/test-vectors/embedding-identity-v1.json").read_text(encoding="utf-8"))
    for vector in vectors["vectors"]:
        manifest_path, profile_path = ROOT / vector["modelManifest"], ROOT / vector["pipelineProfile"]
        if not (ROOT / "models").is_dir() and not (ROOT / "src").is_dir():
            # A contracts-only tree (the contract drift tests) has no manifests or profiles to re-derive from.
            continue
        if not (manifest_path.is_file() and profile_path.is_file()):
            # In a full tree a missing or renamed file fails closed rather than silently disabling the check.
            fail(f"Embedding identity vector {vector['name']} names a missing manifest or profile.", errors)
            continue
        canonical, fingerprint = embedding_identity(manifest_path, profile_path)
        if canonical != vector["canonicalIdentity"] or fingerprint != vector["fingerprint"]:
            fail(f"Embedding identity vector {vector['name']} no longer matches its manifest and profile.", errors)
    lease = json.loads((ROOT / "contracts/examples/embedding-lease-v1.example.json").read_text(encoding="utf-8"))
    complete = json.loads((ROOT / "contracts/examples/embedding-complete-v1.example.json").read_text(encoding="utf-8"))
    development = vectors["vectors"][0]
    if lease["identity"]["fingerprint"] != development["fingerprint"] or \
            complete["provenance"]["identityFingerprint"] != development["fingerprint"]:
        fail("Embedding contract examples do not carry the development identity fingerprint.", errors)
    if [track["trackId"] for track in lease["tracks"]] != [track["trackId"] for track in complete["tracks"]]:
        fail("The embedding completion example does not describe the lease example's Tracks in order.", errors)


def face_identity(manifest_path: Path, profile_path: Path) -> tuple[str, str]:
    """ADR-022 identity: the ADR-021 identity shape under ``mavi-face-identity-v1``, and its SHA-256."""
    canonical, _ = embedding_identity(manifest_path, profile_path)
    identity = json.loads(canonical)
    identity["schemaVersion"] = "mavi-face-identity-v1"
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":")) + "\n"
    return canonical, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def check_face_contract(errors: list[str]) -> None:
    """The face identity vectors re-derive from the committed files, and the examples agree with them and each other."""
    vectors = json.loads((ROOT / "contracts/test-vectors/face-identity-v1.json").read_text(encoding="utf-8"))
    for vector in vectors["vectors"]:
        manifest_path, profile_path = ROOT / vector["modelManifest"], ROOT / vector["pipelineProfile"]
        if not (ROOT / "models").is_dir() and not (ROOT / "src").is_dir():
            continue
        if not (manifest_path.is_file() and profile_path.is_file()):
            fail(f"Face identity vector {vector['name']} names a missing manifest or profile.", errors)
            continue
        canonical, fingerprint = face_identity(manifest_path, profile_path)
        if canonical != vector["canonicalIdentity"] or fingerprint != vector["fingerprint"]:
            fail(f"Face identity vector {vector['name']} no longer matches its manifest and profile.", errors)
    examples = ROOT / "contracts/examples"
    lease = json.loads((examples / "face-lease-v1.example.json").read_text(encoding="utf-8"))
    complete = json.loads((examples / "face-complete-v1.example.json").read_text(encoding="utf-8"))
    query_lease = json.loads((examples / "face-query-lease-v1.example.json").read_text(encoding="utf-8"))
    first = vectors["vectors"][0]["fingerprint"]
    if {lease["identity"]["fingerprint"], complete["provenance"]["identityFingerprint"], query_lease["identity"]["fingerprint"]} != {first}:
        fail("Face contract examples do not carry the first face identity vector's fingerprint.", errors)
    if [track["trackId"] for track in lease["tracks"]] != [track["trackId"] for track in complete["tracks"]]:
        fail("The face completion example does not describe the lease example's Tracks in order.", errors)
    leased = {track["trackId"]: {o["observationId"] for o in track["observations"]} for track in lease["tracks"]}
    for track in complete["tracks"]:
        if any(face["observationId"] not in leased[track["trackId"]] for face in track["faces"]):
            fail("The face completion example names an observation its Track did not lease.", errors)
        if (track["outcome"] == "observed") != any(face["usable"] for face in track["faces"]):
            fail("A face completion example Track is 'observed' exactly when it has a usable face.", errors)


def check_face_profiles(tracked: list[Path], manifests: dict, errors: list[str], root: Path = ROOT) -> set[str]:
    """PoC S6 (ADR-022 §2-§3): the faces role is composed from explicit paths, like the embeddings role.

    Every tracked face pipeline profile is a developmentOnly ``mavi-face-pipeline-v1`` that names a tracked, unverified
    ``embedding`` manifest with no qualification ID, whose dimension it repeats, whose runtime family is a declared
    Development runtime family, and which carries the face detector and embedder artefact roles. Returns the Model
    Pack ids those profiles bind.
    """
    bound: set[str] = set()
    by_path = {manifest_path.resolve(): (pack_id, manifest) for pack_id, (manifest_path, manifest, _hash) in manifests.items()}
    policy_path = root / "config/dependencies/offline-dependency-policy-v1.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8")) if policy_path.is_file() else {}
    families = ((policy.get("ecosystemStrategies") or {}).get("python") or {}).get("developmentRuntimeFamilies") or {}
    tracked_set = {path.resolve() for path in tracked}
    for path in tracked:
        relative = path.relative_to(root).as_posix()
        if not (relative.startswith("src/vision/config/faces/") and relative.endswith(".json")):
            continue
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            fail(f"Face pipeline profile {relative} is not valid JSON.", errors)
            continue
        if profile.get("schemaVersion") != "mavi-face-pipeline-v1" or profile.get("developmentOnly") is not True:
            fail(f"Face pipeline profile {relative} must be mavi-face-pipeline-v1 and developmentOnly.", errors)
            continue
        threshold = profile.get("referenceThreshold") or {}
        if not isinstance(threshold.get("cosine"), float) or not str(threshold.get("provenance") or "").strip():
            fail(f"Face pipeline profile {relative} must state a reference threshold and its provenance (ADR-022 §7).", errors)
            continue
        manifest_path = (root / str(profile.get("modelManifest"))).resolve()
        if manifest_path not in tracked_set or manifest_path not in by_path:
            fail(f"Face pipeline profile {relative} names no tracked model manifest.", errors)
            continue
        pack_id, manifest = by_path[manifest_path]
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        family_ids = (document.get("runtimeCompatibility") or {}).get("runtimePackFamilyIds") or []
        roles = {artifact.get("artifactRole") for artifact in document.get("artifacts") or []}
        if (document.get("capabilityIds") != ["embedding"] or manifest.verification_status != "unverified"
                or manifest.qualification_id is not None
                or ((document.get("capabilitySpecific") or {}).get("embedding") or {}).get("dimension") != profile.get("dimension")
                or not {"onnx-face-detector", "onnx-face-embedder", "licence-notice", "licence-notice-detector"} <= roles
                or not family_ids or any(family not in families for family in family_ids)):
            fail(f"Face pipeline profile {relative} binds a manifest that is not an unverified, unqualified face pipeline "
                 "pack of its dimension on a declared Development runtime family.", errors)
            continue
        bound.add(pack_id)
    return bound


def check_embedding_profiles(tracked: list[Path], manifests: dict, errors: list[str], root: Path = ROOT) -> set[str]:
    """PoC S4 (ADR-021 §2-§3): the embeddings role is composed from explicit paths, not a Component Binding.

    Every tracked embedding pipeline profile is developmentOnly and names a tracked, unverified ``embedding``
    manifest with no qualification ID, whose dimension it repeats and whose runtime family is a declared
    Development runtime family. Returns the Model Pack ids those profiles bind.
    """
    bound: set[str] = set()
    by_path = {manifest_path.resolve(): (pack_id, manifest) for pack_id, (manifest_path, manifest, _hash) in manifests.items()}
    families: dict | None = None
    tracked_set = {path.resolve() for path in tracked}
    for path in tracked:
        relative = path.relative_to(root).as_posix()
        if not (relative.startswith("src/vision/config/embeddings/") and relative.endswith(".json")):
            continue
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            fail(f"Embedding pipeline profile {relative} is not valid JSON.", errors)
            continue
        if profile.get("schemaVersion") != "mavi-embedding-pipeline-v1" or profile.get("developmentOnly") is not True:
            fail(f"Embedding pipeline profile {relative} must be mavi-embedding-pipeline-v1 and developmentOnly.", errors)
            continue
        manifest_path = (root / str(profile.get("modelManifest"))).resolve()
        if manifest_path not in tracked_set or manifest_path not in by_path:
            fail(f"Embedding pipeline profile {relative} names no tracked model manifest.", errors)
            continue
        pack_id, manifest = by_path[manifest_path]
        if families is None:
            policy_path = root / "config/dependencies/offline-dependency-policy-v1.json"
            policy = json.loads(policy_path.read_text(encoding="utf-8")) if policy_path.is_file() else {}
            families = ((policy.get("ecosystemStrategies") or {}).get("python") or {}).get("developmentRuntimeFamilies") or {}
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        family_ids = (document.get("runtimeCompatibility") or {}).get("runtimePackFamilyIds") or []
        if (document.get("capabilityIds") != ["embedding"] or manifest.verification_status != "unverified"
                or manifest.qualification_id is not None
                or ((document.get("capabilitySpecific") or {}).get("embedding") or {}).get("dimension") != profile.get("dimension")
                or not family_ids or any(family not in families for family in family_ids)):
            fail(f"Embedding pipeline profile {relative} binds a manifest that is not an unverified, unqualified embedding "
                 "pack of its dimension on a declared Development runtime family.", errors)
            continue
        bound.add(pack_id)
    return bound


def check_plate_contract(errors: list[str]) -> None:
    """The plate examples agree with each other and with the identity, digest and bound vectors.

    The .NET tests (``PlateContractTests``) re-derive the identity, the digest and the bound arithmetic;
    this check holds the checked-in artefacts to each other so neither side can drift silently.
    """
    examples = ROOT / "contracts/examples"
    vectors = ROOT / "contracts/test-vectors"
    lease = json.loads((examples / "plate-lease-v1.example.json").read_text(encoding="utf-8"))
    completion = json.loads((examples / "plate-complete-v1.example.json").read_text(encoding="utf-8"))
    predictions_bytes = (examples / "plate-predictions-v1.example.json").read_bytes()
    predictions = json.loads(predictions_bytes)
    canonical = (json.dumps(predictions, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
    if canonical != predictions_bytes:
        fail("The PlatePredictions example must be canonical JSON (sorted keys, compact, ASCII, one trailing LF).", errors)

    artifact = completion["payload"]["predictionArtifact"]
    if artifact["sizeBytes"] != len(predictions_bytes) or artifact["sha256"] != hashlib.sha256(predictions_bytes).hexdigest():
        fail("The plate completion example must describe the PlatePredictions example's exact bytes.", errors)

    identity = json.loads((vectors / "plate-identity-v1.json").read_text(encoding="utf-8"))["vectors"][0]
    if hashlib.sha256(identity["canonicalIdentity"].encode("ascii")).hexdigest() != identity["fingerprint"]:
        fail("plate-identity-v1.json: the fingerprint must be the SHA-256 of the canonical identity.", errors)
    if lease["identity"]["fingerprint"] != identity["fingerprint"] or predictions["identityFingerprint"] != identity["fingerprint"]:
        fail("The plate lease and predictions examples must name the identity vector's fingerprint.", errors)
    normalisation_sha = hashlib.sha256((vectors / "plate-normalisation-v1.json").read_bytes()).hexdigest()
    if f'"sha256":"{normalisation_sha}"' not in identity["canonicalIdentity"]:
        fail("The plate identity must pin the SHA-256 of plate-normalisation-v1.json.", errors)

    lease_tracks = [(track["trackId"], [item["observationId"] for item in track["observations"]]) for track in lease["tracks"]]
    artefact_tracks = [(track["trackId"], [item["observationId"] for item in track["crops"]]) for track in predictions["tracks"]]
    completion_tracks = [track["trackId"] for track in completion["payload"]["tracks"]]
    if lease_tracks != artefact_tracks or [track for track, _ in lease_tracks] != completion_tracks:
        fail("The plate examples must cover every leased Track and crop exactly once, in lease order.", errors)

    digest = json.loads((vectors / "plate-completion-v1-digest.json").read_text(encoding="utf-8"))
    if hashlib.sha256((ROOT / digest["example"]).read_bytes()).hexdigest() != digest["exampleSha256"]:
        fail("The plate completion example changed without re-pinning its digest vector.", errors)
    if not re.fullmatch(r"[0-9a-f]{64}", digest.get("digest", "")):
        fail("The plate completion digest vector must pin a lower-case SHA-256 digest.", errors)

    bound = json.loads((vectors / "plate-artifact-bound-v1.json").read_text(encoding="utf-8"))
    for vector in bound["vectors"]:
        fits = vector["worstCaseArtifactBytes"] <= bound["maximumBytes"] and vector["worstCaseCompletionBytes"] <= bound["maximumBytes"]
        if fits != vector["accepted"]:
            fail(f"plate-artifact-bound-v1.json: vector {vector['name']} is accepted only when both worst cases fit.", errors)


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


# Completion 3.3 (Stage 3, ADR-016): the 3.2 body plus the detector-native vehicle
# subclass. This is the one statement of that delta; the published 3.3 schema must
# equal it applied to the published 3.2 schema.
COMPLETION_V33_SUBCLASS_VALUES = ("car", "truck", "bus", "motorcycle")
COMPLETION_V33_EXAMPLES = (
    "vision-job-complete-v3.3.example.json",
    "vision-job-complete-v3.3-unpacked-environment.example.json",
)


def expected_completion_v33_schema(v32: dict) -> dict:
    schema = json.loads(json.dumps(v32))
    schema["title"] = "vision-job-complete-v3.3"
    schema["properties"]["schemaVersion"] = {"const": "3.3"}
    defs = schema["$defs"]
    defs["objectSubclass"] = {
        "$comment": "mavi-vehicle-subclass-v1; mirrored by mavi_vision.common.subclass and VisionResultValidator.",
        "enum": list(COMPLETION_V33_SUBCLASS_VALUES),
    }
    track = defs["track"]
    # Present only when the Track-level vote resolved a value; never null (ADR-016).
    track["properties"]["objectSubclass"] = {"$ref": "#/$defs/objectSubclass"}
    track["allOf"] = [
        *track.get("allOf", []),
        {
            "if": {"properties": {"objectClass": {"const": "person"}}, "required": ["objectClass"]},
            "then": {"not": {"required": ["objectSubclass"]}},
        },
    ]
    schema["properties"]["objectSubclassVocabulary"] = {"const": "mavi-vehicle-subclass-v1"}
    # The source names the pipeline profile that resolved every subclass in the body;
    # the platform checks that it equals provenance.pipelineProfileSha256.
    schema["properties"]["objectSubclassSource"] = {
        "type": "string", "minLength": 80, "maxLength": 80, "pattern": "^detector-native:[0-9a-f]{64}$",
    }
    schema["required"] = [*schema["required"], "objectSubclassVocabulary", "objectSubclassSource"]
    return schema


def expected_finalization_response_v33_schema(v32: dict) -> dict:
    schema = json.loads(json.dumps(v32))
    schema["title"] = "vision-job-finalization-response-v3.3"
    schema["description"] = schema["description"].replace("Completion 3.2 acknowledgement", "Completion 3.3 acknowledgement", 1)
    schema["properties"]["schemaVersion"] = {"const": "3.3"}
    return schema


def completion_v33_invalid_cases() -> list[dict]:
    """The shared 3.3 negative corpus, each case applied to its golden example."""
    bases = {
        "installed": "contracts/examples/vision-job-complete-v3.3.example.json",
        "unpacked": "contracts/examples/vision-job-complete-v3.3-unpacked-environment.example.json",
    }
    corpus = json.loads((ROOT / "contracts/test-vectors/control-plane-v3.3-invalid.json").read_text())
    cases = []
    for case in corpus["cases"]:
        payload = json.loads((ROOT / bases[case["base"]]).read_text())
        if "schemaVersion" in case:
            payload["schemaVersion"] = case["schemaVersion"]
        for field in case.get("remove", []):
            del payload[field]
        payload.update(case.get("set", {}))
        for edit in case.get("tracks", []):
            track = payload["tracks"][edit["index"]]
            for field in edit.get("remove", []):
                del track[field]
            track.update(edit.get("set", {}))
        cases.append({"name": case["name"], "code": case["code"], "rejectedBy": case["rejectedBy"], "payload": payload})
    return cases


def check_completion_v33_contract(errors: list[str]) -> None:
    """Completion 3.3: exactly the pinned delta over 3.2, its negative corpus and golden digests."""
    schemas = ROOT / "contracts/schemas"
    v32 = json.loads((schemas / "vision-job-complete-v3.2.schema.json").read_text())
    v33 = json.loads((schemas / "vision-job-complete-v3.3.schema.json").read_text())
    if v33 != expected_completion_v33_schema(v32):
        fail("Completion v3.3 schema must equal v3.2 plus the pinned vehicle-subclass delta.", errors)
    response_v32 = json.loads((schemas / "vision-job-finalization-response-v3.2.schema.json").read_text())
    response_v33 = json.loads((schemas / "vision-job-finalization-response-v3.3.schema.json").read_text())
    if response_v33 != expected_finalization_response_v33_schema(response_v32):
        fail("Finalization response v3.3 schema must equal v3.2 apart from title, description and version.", errors)

    validator = jsonschema.Draft202012Validator(v33, format_checker=jsonschema.FormatChecker())
    for name in COMPLETION_V33_EXAMPLES:
        example = json.loads((ROOT / "contracts/examples" / name).read_text())
        for error in validator.iter_errors(example):
            fail(f"Contract example {name} is invalid: {error.message}", errors)
        if example.get("objectSubclassSource") != "detector-native:" + example["provenance"]["pipelineProfileSha256"]:
            fail(f"Contract example {name} must name its own pipeline profile as the subclass source.", errors)

    stems = {"3.2": "vision-job-complete-v3.2", "3.3": "vision-job-complete-v3.3"}
    for case in completion_v33_invalid_cases():
        case_validator = jsonschema.Draft202012Validator(
            json.loads((schemas / f"{stems[case['payload']['schemaVersion']]}.schema.json").read_text()),
            format_checker=jsonschema.FormatChecker())
        schema_valid = not list(case_validator.iter_errors(case["payload"]))
        if case["rejectedBy"] == "schema" and schema_valid:
            fail(f"Invalid completion v3.3 case was accepted by the schema: {case['name']}", errors)
        if case["rejectedBy"] == "validator" and not schema_valid:
            fail(f"Completion v3.3 case '{case['name']}' must be schema-valid so it exercises the platform validator.", errors)

    vectors = json.loads((ROOT / "contracts/test-vectors/vision-job-complete-v3.3-digest.json").read_text())["vectors"]
    if sorted(vector["example"] for vector in vectors) != sorted(f"contracts/examples/{name}" for name in COMPLETION_V33_EXAMPLES):
        fail("Completion v3.3 digest vectors must pin exactly the installed-pack and unpacked-environment examples.", errors)
    for vector in vectors:
        example_sha = hashlib.sha256((ROOT / vector["example"]).read_bytes()).hexdigest()
        if example_sha != vector.get("exampleSha256"):
            fail(f"Completion v3.3 example {vector['example']} changed without re-pinning its digest vector.", errors)
        if not re.fullmatch(r"[0-9a-f]{64}", vector.get("completionDigest", "")):
            fail("Completion v3.3 digest vectors must pin lower-case SHA-256 digests.", errors)


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
        from mavi_vision.plates.profile import load_plate_pipeline
        from mavi_vision.runtime.development_binding import (
            DEVELOPMENT_PRODUCERS_PATH,
            PLATE_PROFILE_DIRECTORY,
            check_release_binding_pin,
            check_replacement_binding,
            check_role_binding,
            load_development_producers,
        )
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
    plate_profile_root = root / PLATE_PROFILE_DIRECTORY
    release_roots = [manifest_root, qualification_root, pipeline_root, runtime_root, binding_root, plate_profile_root]
    producers_path = root / DEVELOPMENT_PRODUCERS_PATH

    def rel(path: Path) -> str:
        return path.relative_to(root).as_posix()

    tracked = tracked_files() if tracked is None else tracked
    tracked_set = set(tracked)
    release_files = sorted(
        file_path
        for file_path in tracked
        if file_path.suffix.lower() in {".json", ".lock"}
        and (
            any(file_path.is_relative_to(release_root) for release_root in release_roots)
            or file_path == producers_path
        )
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

    # ---- 1. Model Pack manifests, by derived id (P-3) and by modelId. One model may
    # have several packs (ADR-014 2026-10-06 note: the Stage-3 test-scale pack keeps the
    # checkpoint's modelId), each with its own modelVersion; a binding binds at most one.
    manifests: dict[str, tuple[Path, object, str]] = {}
    manifests_by_model: dict[str, list[tuple[Path, object, str]]] = {}
    model_versions: set[tuple[str, str]] = set()
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
        if (manifest.model_id, manifest.model_version) in model_versions:
            fail(f"Duplicate modelId/modelVersion in release manifests: {manifest.model_id} {manifest.model_version}", errors)
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
        model_versions.add((manifest.model_id, manifest.model_version))
        manifests_by_model.setdefault(manifest.model_id, []).append((path, manifest, manifest_hash))

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
        entries = manifests_by_model.get(profile.model_id)
        if not entries:
            fail(f"Pipeline profile {profile.profile_id} references unknown modelId {profile.model_id}.", errors)
            continue
        for _manifest_path, manifest, _manifest_hash in entries:
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

    # ---- 5. Component bindings: exactly one release binding, plus the Development
    # replacement bindings the producer registry declares (ADR-014 2026-10-06 note).
    # Any other additional binding still fails binding_multiple_not_supported.
    binding_paths = json_under(binding_root)
    if not binding_paths:
        fail("No component binding is tracked under src/vision/config/components.", errors)
        return
    producers = None
    if producers_path in tracked_set:
        try:
            producers = load_development_producers(producers_path)
        except ReleaseMetadataError as exc:
            fail(f"Development producer registry invalid: {rel(producers_path)} ({exc.code})", errors)
            return
    declared = {} if producers is None else {root / item.binding_path: item for item in producers.producers}
    role_declared = {} if producers is None else {root / item.binding_path: item for item in producers.role_bindings}
    release_paths = [path for path in binding_paths if path not in declared and path not in role_declared]
    if len(release_paths) != 1:
        fail(
            "binding_multiple_not_supported: exactly one release component binding must be tracked besides the "
            f"declared Development replacement bindings; found {', '.join(rel(path) for path in release_paths) or 'none'}.",
            errors,
        )
        return
    (binding_path,) = release_paths
    try:
        binding = load_component_binding(binding_path)
    except ReleaseMetadataError as exc:
        fail(f"Component binding invalid (v2 only; a v1 binding is refused): {rel(binding_path)} ({exc.code})", errors)
        return

    # (path, binding, None) for the release binding; (path, binding, (producer, profile entry))
    # for each Development replacement binding.
    bindings: list[tuple[Path, object, object]] = [(binding_path, binding, None)]
    if producers is not None:
        try:
            check_release_binding_pin(
                producers,
                release_binding_path=rel(binding_path),
                release_binding_sha256=binding.component_binding_sha256,
            )
        except ReleaseMetadataError as exc:
            fail(f"Development producer registry does not pin the release binding: {rel(producers_path)} ({exc.code})", errors)
            return
        for path, producer in declared.items():
            if path not in tracked_set:
                fail(f"Development producer {producer.producer_id} names an untracked binding {rel(path)} (development_binding_missing).", errors)
                continue
            try:
                candidate = load_component_binding(path)
                check_replacement_binding(release=binding, candidate=candidate, replaces=producer.replaces)
            except ReleaseMetadataError as exc:
                fail(f"Development replacement binding invalid: {rel(path)} ({exc.code})", errors)
                continue
            profile_entry = next(
                (entry for entry in profiles.values() if entry[0] == root / producer.pipeline_profile_path), None
            )
            if profile_entry is None:
                fail(
                    f"Development producer {producer.producer_id} names an untracked or invalid pipeline profile "
                    f"{producer.pipeline_profile_path} (development_binding_profile_missing).",
                    errors,
                )
                continue
            if not profile_entry[1].development_only:
                fail(
                    f"Development producer {producer.producer_id} runs with {producer.pipeline_profile_path}, "
                    "which is not developmentOnly (development_binding_profile_not_development).",
                    errors,
                )
                continue
            bindings.append((path, candidate, (producer, profile_entry)))

    # Development role bindings (ADR-014 amendment 2026-10-17): a role the release binding lacks (plates), with a
    # Development-only plate pipeline profile that its every record pins and unverified manifests only.
    role_profiles: dict[Path, tuple[object, str]] = {}
    for path, role_binding in role_declared.items():
        if path not in tracked_set:
            fail(f"Development role binding {role_binding.role_binding_id} names an untracked binding {rel(path)} (development_binding_missing).", errors)
            continue
        profile_path = root / role_binding.pipeline_profile_path
        try:
            candidate = load_component_binding(path)
            check_role_binding(release=binding, candidate=candidate, role_ids=role_binding.role_ids)
            if profile_path not in tracked_set:
                raise ReleaseMetadataError("development_role_binding_profile_missing")
            plate_profile = load_plate_pipeline(profile_path)
        except ReleaseMetadataError as exc:
            fail(f"Development role binding invalid: {rel(path)} ({exc.code})", errors)
            continue
        if not plate_profile.development_only:
            fail(f"Development role binding {role_binding.role_binding_id} runs with {role_binding.pipeline_profile_path}, "
                 "which is not developmentOnly (development_binding_profile_not_development).", errors)
            continue
        role_profiles[path] = (plate_profile, sha256_release_file(profile_path))
        bindings.append((path, candidate, None))
    # Every tracked plate pipeline file is a declared profile or one of its two pinned siblings.
    allowed_plate_files: set[Path] = set()
    for item in role_declared.values():
        profile_path = root / item.pipeline_profile_path
        allowed_plate_files.add(profile_path)
        try:
            document = json.loads(profile_path.read_text(encoding="utf-8"))
            allowed_plate_files.update(profile_path.parent / document[key]["file"] for key in ("summaryPolicy", "parameters"))
        except (OSError, ValueError, KeyError, TypeError):
            pass
    for path in json_under(plate_profile_root):
        if path not in allowed_plate_files:
            fail(f"Plate pipeline file {rel(path)} is declared by no Development role binding.", errors)

    bound_records: set[str] = set()
    bound_packs: set[str] = set()
    for current_path, current, development in bindings:
        bound_packs.update(item.model_pack_id for item in current.capability_bindings)
        bound_models = [
            manifests[item.model_pack_id][1].model_id
            for item in current.capability_bindings
            if item.model_pack_id in manifests
        ]
        if len(set(bound_models)) != len(bound_models):
            fail(f"Component binding {rel(current_path)} binds two Model Packs of one modelId.", errors)
        for role in current.roles.values():
            # Family known, P-2, locks verified, P-17 classes from the tracked lock
            # files, binding variants == class-B set, every pinned id lock-derived.
            try:
                family = load_role_family(binding=current, role_id=role.role_id, overlay_root=root)
            except ReleaseMetadataError as exc:
                fail(f"Component binding role {role.role_id} is inconsistent with its runtime family: {exc.code}", errors)
                continue
            runtime_profile = family.runtime_profile
            binding_variants = current.family_variants(role.runtime_pack_family_id)
            for capability_binding in current.bindings_for_role(role.role_id):
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
                    # The release binding never runs a Development-only profile; a replaced
                    # capability runs exactly the profile its producer declares.
                    if development is None and current_path not in role_profiles and profile_entry[1].development_only:
                        fail(
                            f"Release binding qualification {record.qualification_id} pins the Development-only "
                            f"profile {profile_entry[1].profile_id} (release_binding_development_profile).",
                            errors,
                        )
                    if (
                        development is not None
                        and (role.role_id, capability_id) in development[0].replaces
                        and profile_entry[0] != development[1][0]
                    ):
                        fail(
                            f"Qualification {record.qualification_id} of Development producer "
                            f"{development[0].producer_id} pins {rel(profile_entry[0])}, not its declared profile "
                            f"{development[0].pipeline_profile_path} (development_binding_profile_mismatch).",
                            errors,
                        )
                if current_path in role_profiles:
                    plate_profile, plate_profile_sha = role_profiles[current_path]
                    if (record.pipeline_profile_id, record.pipeline_profile_sha256) != (plate_profile.pipeline_id, plate_profile_sha):
                        fail(
                            f"Qualification {record.qualification_id} of a Development role binding does not pin its "
                            f"declared plate profile (development_role_binding_profile_mismatch).",
                            errors,
                        )
                    if manifest.verification_status != "unverified":
                        fail(
                            f"Development role binding {rel(current_path)} binds a verified manifest {manifest.model_id} "
                            "(development_role_binding_verified_manifest).",
                            errors,
                        )
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
    bound_packs |= check_embedding_profiles(tracked, manifests, errors, root)
    bound_packs |= check_face_profiles(tracked, manifests, errors, root)
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
    check_quality_scope(errors)
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
    print(" - contract examples: 44 (incl. completion v3, v3.2 and v3.3 goldens, digest pins and invalid vectors, the S3.2 measurement, media, derivation and T9 artefacts, the S3.2d-1 benchmark harness contracts, the Stage-4 plate control plane, the PoC S4 embedding and the PoC S6 face control planes)")
    print(" - Task-17 acceptance schemas/configuration: validated")
    print(" - production Internet URL scan: clean")
    print(" - tracked model/media/secret/wheel scan: clean")
    print(" - Task-10 release metadata: every tracked record and relationship validated")
    print(" - Task-12 release resolver/lock scan: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
