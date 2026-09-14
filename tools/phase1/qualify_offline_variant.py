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
import time
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
from policy_identity import PolicyIdentityError, canonical_acceptance_profile  # noqa: E402


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


def observed_runtime_platform(
    python: Path,
    *,
    env: dict[str, str],
) -> dict[str, Any]:
    script = (
        "import json,platform;"
        "b=platform.python_build();"
        "print(json.dumps({"
        "'system':platform.system(),"
        "'release':platform.release(),"
        "'version':platform.version(),"
        "'machine':platform.machine(),"
        "'processor':platform.processor() or 'unknown',"
        "'pythonVersion':platform.python_version(),"
        "'pythonImplementation':platform.python_implementation(),"
        "'pythonBuild':[b[0],b[1]],"
        "'pythonCompiler':platform.python_compiler()"
        "},sort_keys=True))"
    )
    completed = run_command([str(python), "-c", script], env=env)
    if completed.returncode != 0:
        raise VariantQualificationError("variant_runtime_platform_unavailable")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise VariantQualificationError("variant_runtime_platform_invalid") from exc
    if not isinstance(value, dict):
        raise VariantQualificationError("variant_runtime_platform_invalid")
    return value

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


def assert_worker_flow_binding(
    worker: dict[str, Any],
    *,
    variant: str,
    bundle_mode: str,
    target_verified_manifest_sha256: str,
    bundle_manifest_sha256: str,
    release_lock_sha256: str,
    runtime_platform: dict[str, Any],
    device: str,
    expected_mavi_build: str,
) -> None:
    attestation = worker.get("attestation", {})
    common_invalid = (
        worker.get("mode") != "formal"
        or worker.get("targetVerifiedManifestSha256") != target_verified_manifest_sha256
        or attestation.get("runtimeVariant") != variant
        or attestation.get("platform") != runtime_platform
        or attestation.get("maviBuild") != expected_mavi_build
        or worker.get("evidenceReads", {}).get("passed", 0) <= 0
    )
    if common_invalid:
        raise VariantQualificationError("variant_worker_flow_evidence_invalid")

    if bundle_mode == "qualification-candidate":
        if (
            attestation.get("verificationStatus") != "unverified"
            or attestation.get("candidateBundleManifestSha256") != bundle_manifest_sha256
            or attestation.get("candidateSelectedLockSha256") != release_lock_sha256
            or attestation.get("productionBundleManifestSha256") is not None
        ):
            raise VariantQualificationError("variant_worker_flow_evidence_invalid")
    elif bundle_mode == "production":
        if (
            attestation.get("verificationStatus") != "verified"
            or attestation.get("productionBundleManifestSha256") != bundle_manifest_sha256
            or attestation.get("platformLockSha256") != release_lock_sha256
            or attestation.get("candidateBundleManifestSha256") is not None
            or attestation.get("candidateSelectedLockSha256") is not None
        ):
            raise VariantQualificationError("variant_worker_flow_evidence_invalid")
    else:
        raise VariantQualificationError("variant_bundle_mode_invalid")

    actual = attestation.get("actualDevice")
    if device == "cpu" and actual != "cpu":
        raise VariantQualificationError("variant_worker_flow_device_mismatch")
    if device == "cuda" and not (
        isinstance(actual, str) and actual.startswith("cuda:")
    ):
        raise VariantQualificationError("variant_worker_flow_device_mismatch")


def _command_sha256(arguments: list[str]) -> str:
    return hashlib.sha256("\0".join(arguments).encode("utf-8")).hexdigest()


def run_installed_worker_flow(
    args: argparse.Namespace,
    *,
    python: Path,
    environment: dict[str, str],
    manifest: dict[str, Any],
    manifest_sha: str,
) -> tuple[dict[str, Any], str, str, str]:
    if args.worker_flow_output.exists():
        raise VariantQualificationError("variant_worker_flow_output_exists")
    worker_log = args.worker_flow_output.with_suffix(args.worker_flow_output.suffix + ".worker.log")
    if worker_log.exists():
        raise VariantQualificationError("variant_worker_log_exists")

    release_models = args.bundle_dir / "release" / "models"
    release_runtime = args.bundle_dir / "release" / "runtime" / "mmdetection-phase1-v1"
    model_manifest = release_models / "manifests" / "rtmdet-m-coco-phase1-v1.json"
    qualification = release_models / "qualifications" / "rtmdet-m-coco-phase1-v1.json"
    pipeline_profile = args.bundle_dir / "release" / "config" / "pipelines" / "phase1-detection-tracking-v1.json"
    runtime_profile = release_runtime / "runtime.json"

    worker_env = dict(environment)
    worker_env.update({
        "MAVI_API_BASE_URL": args.base_url,
        "MAVI_WORKER_ID": f"task17-{args.variant}",
        "MAVI_MEDIA_ROOT": str(args.media_root.resolve()),
        "MAVI_MODEL_ROOT": str(release_models.resolve()),
        "MAVI_MODEL_MANIFEST_PATH": str(model_manifest.resolve()),
        "MAVI_PIPELINE_PROFILE_PATH": str(pipeline_profile.resolve()),
        "MAVI_RUNTIME_PROFILE_PATH": str(runtime_profile.resolve()),
        "MAVI_QUALIFICATION_RECORD_PATH": str(qualification.resolve()),
        "MAVI_BUILD_ID": args.expected_mavi_build,
        "MAVI_COMMIT_SHA": args.source_commit,
        "MAVI_DEVICE_POLICY": "cuda" if args.variant.endswith("-cuda") else "cpu",
        "MAVI_DEVICE_INDEX": str(args.device_index),
        "MAVI_PRODUCTION_MODE": "true" if manifest["releaseStatus"] == "production" else "false",
        "MAVI_POLL_INTERVAL_SECONDS": "0.25",
    })
    worker_command = [str(python), "-m", "mavi_vision.worker.main"]

    e2e_command = [
        str(python),
        str(PHASE1_ROOT / "phase1_e2e_check.py"),
        "--mode", "formal",
        "--base-url", args.base_url,
        "--camera-code", args.camera_code,
        "--camera-name", args.camera_name,
        "--camera-timezone", args.camera_timezone,
        "--recording-local", args.recording_local,
        "--video", str(args.video),
        "--processing-timeout-seconds", str(args.processing_timeout_seconds),
        "--environment-label", args.environment_label,
        "--source-commit", args.source_commit,
        "--expected-mavi-build", args.expected_mavi_build,
        "--target-verified-manifest-sha256", args.target_verified_manifest_sha256,
        "--model-root", str(release_models),
        "--model-manifest", str(model_manifest),
        "--pipeline-profile", str(pipeline_profile),
        "--runtime-profile", str(runtime_profile),
        "--qualification-record", str(qualification),
        "--bundle-dir", str(args.bundle_dir),
        "--acceptance-profile", str(args.acceptance_profile),
        "--corpus-manifest", str(args.corpus_manifest),
        "--ground-truth", str(args.ground_truth),
        "--output", str(args.worker_flow_output),
    ]

    args.worker_flow_output.parent.mkdir(parents=True, exist_ok=True)
    with worker_log.open("w", encoding="utf-8", newline="\n") as log_stream:
        process = subprocess.Popen(
            worker_command,
            env=worker_env,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            time.sleep(args.worker_startup_seconds)
            if process.poll() is not None:
                raise VariantQualificationError("variant_worker_startup_failed")
            completed = run_command(e2e_command, env=environment)
            if completed.returncode != 0:
                raise VariantQualificationError("variant_worker_flow_execution_failed")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)

    worker = read_json(args.worker_flow_output)
    return (
        worker,
        sha256_file(args.worker_flow_output),
        sha256_file(worker_log),
        _command_sha256(worker_command),
    )

def qualify(args: argparse.Namespace) -> dict[str, Any]:
    if not args.network_isolated:
        raise VariantQualificationError("variant_network_isolation_not_asserted")
    canonical_profile, acceptance_profile_sha = canonical_acceptance_profile(args.acceptance_profile)
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

    runtime_platform = observed_runtime_platform(python, env=environment)
    worker, worker_evidence_sha, worker_log_sha, worker_command_sha = run_installed_worker_flow(
        args,
        python=python,
        environment=environment,
        manifest=manifest,
        manifest_sha=manifest_sha,
    )
    try:
        evidence_verifier._validate_schema(
            worker,
            PHASE1_ROOT / "phase1-acceptance-evidence.schema.json",
        )
        profile_value = read_json(canonical_profile)
        approved_corpus_sha = profile_value.get("qualificationCorpusManifestSha256")
        if not isinstance(approved_corpus_sha, str):
            approved_corpus_sha = None
        evidence_verifier.verify_acceptance(
            worker,
            expected_source_commit=args.source_commit,
            expected_acceptance_profile_sha256=acceptance_profile_sha,
            expected_qualification_corpus_sha256=approved_corpus_sha,
        )
    except evidence_verifier.EvidenceError as exc:
        raise VariantQualificationError(
            "variant_worker_flow_evidence_invalid:" + exc.code
        ) from exc

    assert_worker_flow_binding(
        worker,
        variant=args.variant,
        bundle_mode=manifest["releaseStatus"],
        target_verified_manifest_sha256=args.target_verified_manifest_sha256,
        bundle_manifest_sha256=manifest_sha,
        release_lock_sha256=manifest["lockSha256"],
        runtime_platform=runtime_platform,
        device=device,
        expected_mavi_build=args.expected_mavi_build,
    )

    return {
        "schemaVersion": "mavi-offline-variant-evidence-v1",
        "sourceCommit": args.source_commit,
        "targetVerifiedManifestSha256": args.target_verified_manifest_sha256,
        "acceptanceProfileSha256": acceptance_profile_sha,
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
        "workerFlowEvidenceSha256": worker_evidence_sha,
        "workerPythonSha256": sha256_file(python),
        "workerCommandSha256": worker_command_sha,
        "workerLogSha256": worker_log_sha,
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
    parser.add_argument("--acceptance-profile", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--camera-code", required=True)
    parser.add_argument("--camera-name", required=True)
    parser.add_argument("--camera-timezone", required=True)
    parser.add_argument("--recording-local", required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--environment-label", required=True)
    parser.add_argument("--expected-mavi-build", required=True)
    parser.add_argument("--corpus-manifest", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--worker-flow-output", type=Path, required=True)
    parser.add_argument("--processing-timeout-seconds", type=float, default=900.0)
    parser.add_argument("--worker-startup-seconds", type=float, default=3.0)
    parser.add_argument("--device-index", type=int, default=0)
    parser.add_argument("--venv", type=Path, required=True)
    parser.add_argument("--network-isolated", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise VariantQualificationError("variant_output_exists")
        value = qualify(args)
        args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")
    except (VariantQualificationError, OSError, KeyError, TypeError, PolicyIdentityError) as exc:
        print(json.dumps({"ok": False, "code": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, "sha256": sha256_file(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
