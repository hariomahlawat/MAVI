from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "qualify_offline_variant.py"
SPEC = importlib.util.spec_from_file_location("offline_variant", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def test_observed_windows_contract_is_not_linux(monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    monkeypatch.setattr(mod.platform, "machine", lambda: "AMD64")
    observed = mod.observed_host({"portability": "qualified-platform"})
    assert observed == {
        "osFamily": "windows",
        "architecture": "x86_64",
        "distribution": None,
        "distributionVersion": None,
        "nativeAbi": "win_amd64",
        "portability": "qualified-platform",
    }


def test_venv_python_path_matches_host(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    assert mod._venv_python(tmp_path) == tmp_path / "Scripts" / "python.exe"
    monkeypatch.setattr(mod.platform, "system", lambda: "Linux")
    assert mod._venv_python(tmp_path) == tmp_path / "bin" / "python"


def _worker(platform_value):
    return {
        "mode": "formal",
        "targetVerifiedManifestSha256": "a" * 64,
        "attestation": {
            "verificationStatus": "unverified",
            "runtimeVariant": "linux-x86_64-cpu",
            "candidateBundleManifestSha256": "b" * 64,
            "candidateSelectedLockSha256": "c" * 64,
            "productionBundleManifestSha256": None,
            "platformLockSha256": None,
            "maviBuild": "build-a",
            "platform": platform_value,
            "actualDevice": "cpu",
        },
        "evidenceReads": {"passed": 1},
    }


def test_worker_flow_binding_rejects_other_bundle():
    platform_value = {"system": "Linux"}
    value = _worker(platform_value)
    value["attestation"]["candidateBundleManifestSha256"] = "d" * 64
    with pytest.raises(mod.VariantQualificationError, match="variant_worker_flow_evidence_invalid"):
        mod.assert_worker_flow_binding(
            value,
            variant="linux-x86_64-cpu",
            bundle_mode="qualification-candidate",
            target_verified_manifest_sha256="a" * 64,
            bundle_manifest_sha256="b" * 64,
            release_lock_sha256="c" * 64,
            runtime_platform=platform_value,
            device="cpu",
            expected_mavi_build="build-a",
        )


def test_worker_flow_binding_rejects_other_host():
    expected_platform = {"system": "Linux", "release": "qualified"}
    value = _worker({"system": "Linux", "release": "different"})
    with pytest.raises(mod.VariantQualificationError, match="variant_worker_flow_evidence_invalid"):
        mod.assert_worker_flow_binding(
            value,
            variant="linux-x86_64-cpu",
            bundle_mode="qualification-candidate",
            target_verified_manifest_sha256="a" * 64,
            bundle_manifest_sha256="b" * 64,
            release_lock_sha256="c" * 64,
            runtime_platform=expected_platform,
            device="cpu",
            expected_mavi_build="build-a",
        )


def test_worker_flow_binding_rejects_reused_candidate_evidence_for_production():
    platform_value = {"system": "Linux"}
    value = _worker(platform_value)
    with pytest.raises(mod.VariantQualificationError, match="variant_worker_flow_evidence_invalid"):
        mod.assert_worker_flow_binding(
            value,
            variant="linux-x86_64-cpu",
            bundle_mode="production",
            target_verified_manifest_sha256="a" * 64,
            bundle_manifest_sha256="b" * 64,
            release_lock_sha256="c" * 64,
            runtime_platform=platform_value,
            device="cpu",
            expected_mavi_build="build-a",
        )


def test_bundle_file_set_rejects_nested_same_named_manifest(tmp_path: Path):
    stage = tmp_path / "bundle"
    stage.mkdir()
    (stage / "bundle-manifest.json").write_text("{}\n", encoding="utf-8")
    nested = stage / "release" / "unexpected"
    nested.mkdir(parents=True)
    (nested / "bundle-manifest.json").write_text("{}\n", encoding="utf-8")

    manifest = mod.build_offline_bundle.BundleManifest(
        schema_version="1.0",
        bundle_id="bundle-a",
        release_status="production",
        source_commit="a" * 40,
        platform_variant="linux-x86_64-cpu",
        python_version="3.12.14",
        model_id="rtmdet-m-coco-phase1-v1",
        runtime_profile_id="mmdetection-phase1-v1",
        lock_sha256="b" * 64,
        deployment_profile="P3",
        deployment_profile_policy_sha256="c" * 64,
        host_compatibility=mod.build_offline_bundle.BundleHostCompatibility(
            os_family="linux",
            architecture="x86_64",
            distribution="ubuntu",
            distribution_version="24.04",
            native_abi="glibc-2.39-libstdcxx-GLIBCXX_3.4.33-linux_x86_64",
            portability="qualified-host-only",
        ),
        artifacts=(),
    )

    with pytest.raises(
        mod.build_offline_bundle.OfflineBundleError,
        match="bundle_artifact_set_mismatch",
    ):
        mod.build_offline_bundle._verify_staged_bundle(stage, manifest)


def test_qualified_bundle_rejects_nested_same_named_manifest(tmp_path: Path, monkeypatch):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "bundle-manifest.json").write_text(
        '{"artifacts":[],"platformVariant":"linux-x86_64-cpu"}\n',
        encoding="utf-8",
    )
    nested = bundle / "release" / "unexpected"
    nested.mkdir(parents=True)
    (nested / "bundle-manifest.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(
        mod.build_offline_bundle,
        "verify_bundled_release_manifest",
        lambda *_: None,
    )
    with pytest.raises(
        mod.VariantQualificationError,
        match="variant_bundle_file_set_mismatch",
    ):
        mod.verify_bundle(bundle)


def test_production_worker_flow_requires_embedded_profile_policy(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    args = __import__("types").SimpleNamespace(
        worker_flow_output=tmp_path / "worker.json",
        bundle_dir=bundle,
    )
    with pytest.raises(
        mod.VariantQualificationError,
        match="variant_production_profile_binding_missing",
    ):
        mod.run_installed_worker_flow(
            args,
            python=tmp_path / "python",
            environment={},
            manifest={
                "releaseStatus": "production",
                "deploymentProfile": "P3",
            },
            manifest_sha="a" * 64,
        )


RETIRED = (
    "MAVI_MODEL_MANIFEST_PATH",
    "MAVI_QUALIFICATION_RECORD_PATH",
    "MAVI_RUNTIME_PROFILE_PATH",
    "MAVI_COMPLETION_SCHEMA_VERSION",
    "MAVI_COMPLETION_SCHEMA_OVERRIDE",
    "MAVI_RUNTIME_PACK_MANIFEST_PATH",
)


def test_candidate_worker_flow_composes_the_bundle_through_the_binding(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The worker and the E2E check get the v2 composition; nothing retired is passed on."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    output = tmp_path / "worker.json"
    args = __import__("types").SimpleNamespace(
        worker_flow_output=output,
        bundle_dir=bundle,
        base_url="http://mavi.local",
        variant="linux-x86_64-cpu",
        media_root=tmp_path / "media",
        expected_mavi_build="build-a",
        source_commit="a" * 40,
        device_index=0,
        camera_code="c",
        camera_name="n",
        camera_timezone="UTC",
        recording_local="2026-01-01T00:00:00",
        video=tmp_path / "v.mp4",
        processing_timeout_seconds=5,
        environment_label="e",
        target_verified_manifest_sha256="0" * 64,
        acceptance_profile=tmp_path / "a.json",
        corpus_manifest=tmp_path / "corpus.json",
        ground_truth=tmp_path / "gt.json",
        worker_startup_seconds=0,
    )
    inherited = {name: "/inherited" for name in RETIRED}
    inherited["PATH"] = "/usr/bin"
    captured: dict[str, object] = {}

    class FakeProcess:
        def __init__(self, command, *, env, **_):
            captured["worker_command"] = command
            captured["worker_env"] = env

        def poll(self):
            return None

        def terminate(self):
            captured["terminated"] = True

        def wait(self, timeout=None):
            return 0

    def fake_run_command(command, *, env=None):
        captured["e2e_command"] = command
        captured["e2e_env"] = env
        output.write_text("{}\n", encoding="utf-8")
        return __import__("types").SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(mod, "run_command", fake_run_command)
    monkeypatch.setattr(mod.time, "sleep", lambda _: None)

    mod.run_installed_worker_flow(
        args,
        python=tmp_path / "python",
        environment=inherited,
        manifest={"releaseStatus": "qualification-candidate"},
        manifest_sha="a" * 64,
    )

    worker_env = captured["worker_env"]
    release = bundle / "release"
    assert worker_env["MAVI_COMPONENT_BINDING_PATH"] == str(
        (release / "src/vision/config/components/phase1-bindings-v2.json").resolve()
    )
    assert worker_env["MAVI_ROLE_ID"] == "vision"
    assert worker_env["MAVI_OVERLAY_ROOT"] == str(release.resolve())
    assert worker_env["MAVI_MODEL_ROOT"] == str((release / "models").resolve())
    assert worker_env["MAVI_PIPELINE_PROFILE_PATH"] == str(
        (release / "src/vision/config/pipelines/phase1-detection-tracking-v1.json").resolve()
    )
    assert worker_env["MAVI_PRODUCTION_MODE"] == "false"
    assert worker_env["PATH"] == "/usr/bin"
    for env in (worker_env, captured["e2e_env"]):
        assert not set(RETIRED) & set(env)
    command = captured["e2e_command"]
    assert "--component-binding" in command and "--overlay-root" in command
    for retired in ("--model-manifest", "--runtime-profile", "--qualification-record"):
        assert retired not in command
    assert command[command.index("--overlay-root") + 1] == str(release)


def _staged_bundle(tmp_path: Path) -> tuple[Path, dict]:
    """A bundle whose ``release/`` is the self-consistent v2 overlay in the bundle layout."""
    import hashlib
    import shutil

    from phase1_v2_support import REPOSITORY, overlay_type

    overlay = overlay_type().create(tmp_path / "source")
    bundle = tmp_path / "bundle"
    release = bundle / "release"
    shutil.copytree(overlay.root, release)
    (release / "binding.json").unlink()
    (release / "pipeline.json").unlink()
    binding = release / "src/vision/config/components/phase1-bindings-v2.json"
    binding.parent.mkdir(parents=True)
    shutil.copyfile(overlay.binding_path, binding)
    pipeline = release / "src/vision/config/pipelines/phase1-detection-tracking-v1.json"
    pipeline.parent.mkdir(parents=True)
    shutil.copyfile(overlay.pipeline_path, pipeline)
    shutil.copytree(overlay.model_root, release / "models", dirs_exist_ok=True)
    policy = REPOSITORY / "config/acceptance/phase1-deployment-profiles-v1.json"
    shutil.copyfile(policy, release / "config/acceptance/phase1-deployment-profiles-v1.json")
    manifest = {
        "releaseStatus": "qualification-candidate",
        "platformVariant": "linux-x86_64-cpu",
        "deploymentProfile": None,
        "deploymentProfilePolicySha256": hashlib.sha256(policy.read_bytes()).hexdigest(),
    }
    return bundle, manifest


def test_bundle_paths_come_from_resolving_the_release_overlay(tmp_path: Path) -> None:
    import release_composition

    bundle, manifest = _staged_bundle(tmp_path)
    resolved = release_composition.resolve_staged_bundle(bundle, manifest)
    selection = resolved.detector_selection()
    release = (bundle / "release").resolve()

    assert resolved.runtime_pack.lock_path == bundle / "release/src/vision/runtime/mmdetection-phase1-v1/linux-x86_64-cpu.lock"
    assert selection.checkpoint_path.resolve().is_relative_to(release / "models")
    assert selection.resolved_config_path.resolve().is_relative_to(release / "models")
    assert resolved.capabilities["detector"].manifest_path == (
        bundle / "release/models/manifests/rtmdet-m-coco-phase1-v2.json"
    )
    assert selection.verification_status == "unverified"
    assert resolved.runtime_pack.runtime_pack_source == "unpacked-environment"


def test_a_production_bundle_cannot_resolve_after_the_cut_over(tmp_path: Path) -> None:
    import release_composition

    bundle, manifest = _staged_bundle(tmp_path)
    manifest.update({"releaseStatus": "production", "deploymentProfile": "P3", "platformVariant": "windows-x86_64-cpu"})
    with pytest.raises(mod.build_offline_bundle.OfflineBundleError, match="unverified_release_forbidden"):
        release_composition.resolve_staged_bundle(bundle, manifest)
