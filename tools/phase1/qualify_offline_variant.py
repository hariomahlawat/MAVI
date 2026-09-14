#!/usr/bin/env python3
"""Execute one Task-17 disconnected runtime/worker qualification variant."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import venv
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PHASE1_ROOT = ROOT / "tools" / "phase1"
VISION_TOOLS = ROOT / "tools" / "vision"
VISION_ROOT = ROOT / "src" / "vision"
for candidate in (PHASE1_ROOT, VISION_TOOLS, VISION_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import build_offline_bundle  # noqa: E402
import verify_phase1_evidence as evidence_verifier  # noqa: E402


class VariantQualificationError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VariantQualificationError("variant_json_invalid") from exc
    if not isinstance(value, dict):
        raise VariantQualificationError("variant_json_invalid")
    return value


def verify_bundle(bundle: Path) -> tuple[dict[str, Any], str]:
    manifest_path = bundle / "bundle-manifest.json"
    manifest = read_json(manifest_path)
    try:
        build_offline_bundle._verify_bundled_release_selection(
            bundle, manifest.get("releaseStatus")
        )
    except Exception as exc:
        raise VariantQualificationError("variant_bundle_release_invalid") from exc
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise VariantQualificationError("variant_bundle_manifest_invalid")
    expected = set()
    for item in artifacts:
        if not isinstance(item, dict):
            raise VariantQualificationError("variant_bundle_manifest_invalid")
        relative = item.get("relativePath")
        if not isinstance(relative, str):
            raise VariantQualificationError("variant_bundle_manifest_invalid")
        logical = PurePosixPath(relative)
        if logical.is_absolute() or ".." in logical.parts:
            raise VariantQualificationError("variant_bundle_path_invalid")
        path = bundle.joinpath(*logical.parts)
        if not path.is_file() or path.stat().st_size != item.get("sizeBytes") or sha256_file(path) != item.get("sha256"):
            raise VariantQualificationError("variant_bundle_integrity_failed")
        expected.add(relative)
    actual = {
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file() and path.name != "bundle-manifest.json"
    }
    if actual != expected:
        raise VariantQualificationError("variant_bundle_file_set_mismatch")
    return manifest, sha256_file(manifest_path)


def _linux_distribution() -> tuple[str, str]:
    values: dict[str, str] = {}
    for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"')
    return values.get("ID", ""), values.get("VERSION_ID", "")


def _glibc_version() -> str:
    libc, version = platform.libc_ver()
    if libc != "glibc" or not version:
        raise VariantQualificationError("variant_glibc_identity_unavailable")
    return version


def _libstdcxx_max() -> str:
    completed = subprocess.run(["ldconfig", "-p"], check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise VariantQualificationError("variant_libstdcxx_identity_unavailable")
    candidates = []
    for line in completed.stdout.splitlines():
        if "libstdc++.so.6" in line and "=>" in line:
            candidates.append(Path(line.split("=>", 1)[1].strip()))
    for candidate in candidates:
        try:
            data = candidate.read_bytes()
        except OSError:
            continue
        versions = set(
            match.decode("ascii")
            for match in re.findall(rb"GLIBCXX_3\.4\.\d+", data)
        )
        if versions:
            return max(versions, key=lambda value: tuple(int(x) for x in value.split("_", 1)[1].split(".")))
    raise VariantQualificationError("variant_libstdcxx_identity_unavailable")


def observed_host(expected: dict[str, Any]) -> dict[str, Any]:
    system = platform.system().lower()
    machine = platform.machine().lower()
    architecture = "x86_64" if machine in {"x86_64", "amd64"} else machine
    if system == "linux":
        distribution, distribution_version = _linux_distribution()
        native_abi = (
            f"glibc-{_glibc_version()}-libstdcxx-{_libstdcxx_max()}-linux_x86_64"
        )
        return {
            "osFamily": "linux",
            "architecture": architecture,
            "distribution": distribution,
            "distributionVersion": distribution_version,
            "nativeAbi": native_abi,
            "portability": expected.get("portability"),
        }
    if system == "windows":
        return {
            "osFamily": "windows",
            "architecture": architecture,
            "distribution": None,
            "distributionVersion": None,
            "nativeAbi": "win_amd64",
            "portability": expected.get("portability"),
        }
    raise VariantQualificationError("variant_host_os_unsupported")


def observed_runtime_platform() -> dict[str, Any]:
    python_build = list(platform.python_build())
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "pythonVersion": platform.python_version(),
        "pythonImplementation": platform.python_implementation(),
        "pythonBuild": python_build,
        "pythonCompiler": platform.python_compiler(),
    }


def assert_outbound_internet_unavailable() -> dict[str, Any]:
    proxy_names = (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
    )
    configured_proxies = {
        name: value
        for name in proxy_names
        if (value := os.environ.get(name))
    }
    if configured_proxies:
        raise VariantQualificationError("variant_outbound_proxy_configured")

    probes = (
        ("1.1.1.1", 443),
        ("8.8.8.8", 53),
        ("pypi.org", 443),
        ("github.com", 443),
        ("www.microsoft.com", 443),
    )
    observations = []
    for host, port in probes:
        reachable = False
        try:
            with socket.create_connection((host, port), timeout=2.0):
                reachable = True
        except (TimeoutError, OSError):
            pass
        observations.append({"host": host, "port": port, "reachable": reachable})
        if reachable:
            raise VariantQualificationError(
                f"variant_outbound_internet_reachable:{host}:{port}"
            )
    return {
        "proxyEnvironmentAbsent": True,
        "probes": observations,
        "passed": True,
    }


def _venv_python(root: Path) -> Path:
    if platform.system().lower() == "windows":
        return root / "Scripts" / "python.exe"
    return root / "bin" / "python"


def run_command(args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, capture_output=True, text=True, env=env)


def qualify(args: argparse.Namespace) -> dict[str, Any]:
    if not args.network_isolated:
        raise VariantQualificationError("variant_network_isolation_not_asserted")
    network_isolation = assert_outbound_internet_unavailable()
    manifest, manifest_sha = verify_bundle(args.bundle_dir)
    if manifest.get("platformVariant") != args.variant:
        raise VariantQualificationError("variant_bundle_variant_mismatch")
    if manifest.get("sourceCommit") != args.source_commit:
        raise VariantQualificationError("variant_source_commit_mismatch")
    if platform.python_version() != manifest.get("pythonVersion"):
        raise VariantQualificationError("variant_python_identity_mismatch")

    expected_host = manifest.get("hostCompatibility")
    if not isinstance(expected_host, dict):
        raise VariantQualificationError("variant_host_contract_missing")
    actual_host = observed_host(expected_host)
    if actual_host != expected_host:
        raise VariantQualificationError("variant_host_compatibility_mismatch")

    if args.venv.exists():
        raise VariantQualificationError("variant_venv_not_clean")
    venv.EnvBuilder(with_pip=True, clear=False, symlinks=False).create(args.venv)
    python = _venv_python(args.venv)
    if not python.is_file():
        raise VariantQualificationError("variant_venv_python_missing")

    lock = args.bundle_dir / "release" / "runtime" / "mmdetection-phase1-v1" / f"{args.variant}.lock"
    wheels = args.bundle_dir / "wheels"
    install_args = [
        str(python), "-m", "pip", "install",
        "--no-index", "--only-binary=:all:", "--require-hashes",
        "--find-links", str(wheels), "-r", str(lock),
    ]
    environment = dict(os.environ)
    environment.update({
        "PIP_NO_INDEX": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    })
    install = run_command(install_args, env=environment)
    if install.returncode != 0:
        raise VariantQualificationError("variant_offline_install_failed")
    check = run_command([str(python), "-m", "pip", "check"], env=environment)
    if check.returncode != 0:
        raise VariantQualificationError("variant_pip_check_failed")

    release_models = args.bundle_dir / "release" / "models"
    model_manifest = read_json(release_models / "manifests" / "rtmdet-m-coco-phase1-v1.json")
    checkpoint_ref = model_manifest.get("checkpoint", {})
    config_ref = model_manifest.get("resolvedConfig", {})
    checkpoint = release_models / PurePosixPath(checkpoint_ref["relativePath"])
    config = release_models / PurePosixPath(config_ref["relativePath"])
    device = "cuda" if args.variant.endswith("-cuda") else "cpu"

    probe = run_command([
        str(python),
        str(ROOT / "tools" / "vision" / "probe_runtime.py"),
        "--config", str(config),
        "--checkpoint", str(checkpoint),
        "--checkpoint-sha256", checkpoint_ref["sha256"],
        "--device", device,
    ], env=environment)
    if probe.returncode != 0:
        raise VariantQualificationError("variant_runtime_probe_failed")
    try:
        probe_value = json.loads(probe.stdout)
    except json.JSONDecodeError as exc:
        raise VariantQualificationError("variant_runtime_probe_invalid") from exc
    if probe_value.get("status") != "passed":
        raise VariantQualificationError("variant_runtime_probe_failed")
    actual_device = probe_value.get("device")
    if device == "cpu" and actual_device != "cpu":
        raise VariantQualificationError("variant_cpu_device_mismatch")
    if device == "cuda" and not (
        isinstance(actual_device, str) and actual_device.startswith("cuda:")
    ):
        raise VariantQualificationError("variant_cuda_device_mismatch")

    worker = read_json(args.worker_flow_evidence)
    try:
        evidence_verifier._validate_schema(
            worker,
            PHASE1_ROOT / "phase1-acceptance-evidence.schema.json",
        )
        evidence_verifier.verify_acceptance(
            worker,
            expected_source_commit=args.source_commit,
            expected_acceptance_profile_sha256=sha256_file(args.acceptance_profile),
        )
    except evidence_verifier.EvidenceError as exc:
        raise VariantQualificationError(
            "variant_worker_flow_evidence_invalid:" + exc.code
        ) from exc

    attestation = worker.get("attestation", {})
    if (
        worker.get("mode") != "formal"
        or worker.get("targetVerifiedManifestSha256") != args.target_verified_manifest_sha256
        or attestation.get("runtimeVariant") != args.variant
        or attestation.get("candidateBundleManifestSha256") != manifest_sha
        or attestation.get("candidateSelectedLockSha256") != manifest.get("lockSha256")
        or attestation.get("platform") != observed_runtime_platform()
        or worker.get("evidenceReads", {}).get("passed", 0) <= 0
    ):
        raise VariantQualificationError("variant_worker_flow_evidence_invalid")
    if device == "cpu" and attestation.get("actualDevice") != "cpu":
        raise VariantQualificationError("variant_worker_flow_device_mismatch")
    if device == "cuda" and not (
        isinstance(attestation.get("actualDevice"), str)
        and attestation["actualDevice"].startswith("cuda:")
    ):
        raise VariantQualificationError("variant_worker_flow_device_mismatch")

    return {
        "schemaVersion": "mavi-offline-variant-evidence-v1",
        "sourceCommit": args.source_commit,
        "targetVerifiedManifestSha256": args.target_verified_manifest_sha256,
        "acceptanceProfileSha256": sha256_file(args.acceptance_profile),
        "variant": args.variant,
        "bundleMode": manifest["releaseStatus"],
        "bundleManifestSha256": manifest_sha,
        "releaseLockSha256": manifest["lockSha256"],
        "expectedHostCompatibility": expected_host,
        "observedHostCompatibility": actual_host,
        "installCommand": " ".join(install_args),
        "installExitCode": install.returncode,
        "pipCheckPassed": True,
        "runtimeStarted": True,
        "realInferencePassed": True,
        "workerFlowPassed": True,
        "workerFlowEvidenceSha256": sha256_file(args.worker_flow_evidence),
        "actualDevice": actual_device,
        "outboundNetworkUnavailable": True,
        "networkIsolation": network_isolation,
        "firstRunDownloadObserved": False,
        "result": "passed",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--variant", required=True, choices=(
        "windows-x86_64-cpu", "windows-x86_64-cuda",
        "linux-x86_64-cpu", "linux-x86_64-cuda",
    ))
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--target-verified-manifest-sha256", required=True)
    parser.add_argument("--worker-flow-evidence", type=Path, required=True)
    parser.add_argument("--acceptance-profile", type=Path, required=True)
    parser.add_argument("--venv", type=Path, required=True)
    parser.add_argument("--network-isolated", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise VariantQualificationError("variant_output_exists")
        value = qualify(args)
        args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")
    except (VariantQualificationError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"ok": False, "code": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, "sha256": sha256_file(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
