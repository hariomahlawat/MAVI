from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


PHASE1_ROOT = Path(__file__).resolve().parents[1]
if str(PHASE1_ROOT) not in sys.path:
    sys.path.insert(0, str(PHASE1_ROOT))

# The worker refuses to start on any of these (settings_v1_composition_rejected);
# the Development-only override and a stray Runtime Pack manifest are scrubbed too.
RETIRED = (
    "MAVI_MODEL_MANIFEST_PATH",
    "MAVI_QUALIFICATION_RECORD_PATH",
    "MAVI_RUNTIME_PROFILE_PATH",
    "MAVI_COMPLETION_SCHEMA_VERSION",
)
SCRUBBED = RETIRED + ("MAVI_COMPLETION_SCHEMA_OVERRIDE", "MAVI_RUNTIME_PACK_MANIFEST_PATH")


def _load(name: str, filename: str):
    path = PHASE1_ROOT / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _args(tmp_path: Path, *, profile_id: str, requires_cuda: bool):
    return SimpleNamespace(
        bundle_dir=tmp_path / "bundle",
        base_url="http://mavi.local",
        mode="formal",
        media_root=tmp_path / "media",
        mavi_build="build-a",
        source_commit="a" * 40,
        selected_profile=SimpleNamespace(
            profile_id=profile_id,
            requires_cuda=requires_cuda,
        ),
        device_index=0,
    )


@pytest.fixture
def inherited_retired_environment(monkeypatch) -> None:
    for name in SCRUBBED:
        monkeypatch.setenv(name, "/inherited/" + name.lower())
    # Case-insensitive, as pydantic-settings reads the worker environment.
    monkeypatch.setenv("mavi_model_manifest_path", "/inherited/lowercase")


def _assert_v2_bundle_composition(env: dict[str, str], bundle: Path) -> None:
    release = bundle / "release"
    assert env["MAVI_COMPONENT_BINDING_PATH"] == str(
        (release / "src/vision/config/components/phase1-bindings-v2.json").resolve()
    )
    assert env["MAVI_ROLE_ID"] == "vision"
    assert env["MAVI_OVERLAY_ROOT"] == str(release.resolve())
    assert env["MAVI_MODEL_ROOT"] == str((release / "models").resolve())
    assert env["MAVI_PIPELINE_PROFILE_PATH"] == str(
        (release / "src/vision/config/pipelines/phase1-detection-tracking-v1.json").resolve()
    )
    assert env["MAVI_DEPLOYMENT_PROFILE_POLICY_PATH"] == str(
        (release / "config/acceptance/phase1-deployment-profiles-v1.json").resolve()
    )
    scrubbed = {name.upper() for name in SCRUBBED}
    assert not [name for name in env if name.upper() in scrubbed]


def test_formal_scenario_worker_environment_binds_profile_and_policy(
    tmp_path: Path,
    inherited_retired_environment: None,
) -> None:
    mod = _load(
        "run_production_scenario_profile_env",
        "run_production_scenario.py",
    )
    args = _args(
        tmp_path,
        profile_id="P1",
        requires_cuda=True,
    )

    env = mod.worker_environment(args)

    assert env["MAVI_PRODUCTION_MODE"] == "true"
    assert env["MAVI_DEPLOYMENT_PROFILE"] == "P1"
    assert env["MAVI_DEVICE_POLICY"] == "cuda"
    _assert_v2_bundle_composition(env, args.bundle_dir)


def test_failure_reprocess_worker_environment_binds_profile_and_policy(
    tmp_path: Path,
    inherited_retired_environment: None,
) -> None:
    mod = _load(
        "qualify_failure_reprocess_profile_env",
        "qualify_failure_reprocess.py",
    )
    args = _args(
        tmp_path,
        profile_id="P3",
        requires_cuda=False,
    )

    env = mod.worker_environment(args, args.bundle_dir)

    assert env["MAVI_PRODUCTION_MODE"] == "true"
    assert env["MAVI_DEPLOYMENT_PROFILE"] == "P3"
    assert env["MAVI_DEVICE_POLICY"] == "cpu"
    _assert_v2_bundle_composition(env, args.bundle_dir)


def test_the_scrubbed_list_is_the_workers_own_retired_list() -> None:
    import release_composition
    from mavi_vision.common.settings import RETIRED_COMPOSITION_ENVIRONMENT

    assert set(RETIRED_COMPOSITION_ENVIRONMENT) == set(RETIRED)
    assert set(release_composition.SCRUBBED_WORKER_ENVIRONMENT) == set(SCRUBBED)


def test_the_bundle_e2e_arguments_use_the_v2_composition(tmp_path: Path) -> None:
    import release_composition

    arguments = release_composition.bundle_e2e_arguments(tmp_path / "bundle")
    pairs = dict(zip(arguments[::2], arguments[1::2]))
    release = tmp_path / "bundle" / "release"
    assert pairs == {
        "--component-binding": str(release / "src/vision/config/components/phase1-bindings-v2.json"),
        "--overlay-root": str(release),
        "--model-root": str(release / "models"),
        "--pipeline-profile": str(release / "src/vision/config/pipelines/phase1-detection-tracking-v1.json"),
        "--bundle-dir": str(tmp_path / "bundle"),
    }


def test_the_failure_reprocess_manifest_comparison_reads_the_resolved_v2_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Read-only: the bundled manifest the resolver binds must equal the target hash."""
    mod = _load("qualify_failure_reprocess_manifest", "qualify_failure_reprocess.py")
    manifest = tmp_path / "bundle/release/models/manifests/any-name.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(b"{}\n")
    before = manifest.read_bytes()
    target = mod.sha256_file(manifest)
    profile = SimpleNamespace(profile_id="P3", runtime_variant="windows-x86_64-cpu", requires_cuda=False)
    bundle = {
        "releaseStatus": "production",
        "deploymentProfile": "P3",
        "deploymentProfilePolicySha256": "f" * 64,
        "platformVariant": "windows-x86_64-cpu",
        "lockSha256": "1" * 64,
    }
    monkeypatch.setattr(mod.deployment_profiles, "select_profile", lambda *_: (profile, "f" * 64))
    monkeypatch.setattr(mod.e2e, "_validate_bundle", lambda *_: (bundle, "2" * 64))
    monkeypatch.setattr(
        mod,
        "environment_fingerprint",
        lambda _: {
            "workerEnvironmentSha256": "3" * 64,
            "workerVenvRootSha256": "4" * 64,
            "workerResolvedPythonSha256": "5" * 64,
        },
    )
    python = tmp_path / "python"
    python.write_bytes(b"python")
    variant = tmp_path / "variant.json"
    variant.write_text(
        __import__("json").dumps({
            "schemaVersion": "mavi-offline-variant-evidence-v1",
            "variant": "windows-x86_64-cpu",
            "bundleMode": "production",
            "sourceCommit": "a" * 40,
            "maviBuild": "build-a",
            "targetVerifiedManifestSha256": target,
            "bundleManifestSha256": "2" * 64,
            "releaseLockSha256": "1" * 64,
            "workerPythonSha256": mod.sha256_file(python),
            "workerEnvironmentSha256": "3" * 64,
            "workerVenvRootSha256": "4" * 64,
            "workerResolvedPythonSha256": "5" * 64,
            "result": "passed",
        }),
        encoding="utf-8",
    )
    resolved = SimpleNamespace(capabilities={"detector": SimpleNamespace(manifest_path=manifest)})
    seen = []

    def resolve(bundle_dir, value):
        seen.append((bundle_dir, value))
        return resolved

    monkeypatch.setattr(mod.release_composition, "resolve_staged_bundle", resolve)
    args = SimpleNamespace(
        deployment_profile="P3",
        deployment_profile_policy=tmp_path / "policy.json",
        variant_evidence=variant,
        bundle_dir=tmp_path / "bundle",
        source_commit="a" * 40,
        mavi_build="build-a",
        target_verified_manifest_sha256=target,
        worker_python=python,
    )

    mod.validate_production_inputs(args)
    assert seen == [(args.bundle_dir, bundle)]
    assert manifest.read_bytes() == before

    args.target_verified_manifest_sha256 = "9" * 64
    variant_value = __import__("json").loads(variant.read_text(encoding="utf-8"))
    variant_value["targetVerifiedManifestSha256"] = "9" * 64
    variant.write_text(__import__("json").dumps(variant_value), encoding="utf-8")
    with pytest.raises(mod.FailureReprocessError, match="failure_reprocess_model_manifest_mismatch"):
        mod.validate_production_inputs(args)

    def refuse(*_):
        raise mod.e2e.build_offline_bundle.OfflineBundleError("runtime_pack_required")

    monkeypatch.setattr(mod.release_composition, "resolve_staged_bundle", refuse)
    with pytest.raises(mod.FailureReprocessError, match="failure_reprocess_bundle_release_invalid"):
        mod.validate_production_inputs(args)
