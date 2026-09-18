from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys


PHASE1_ROOT = Path(__file__).resolve().parents[1]
if str(PHASE1_ROOT) not in sys.path:
    sys.path.insert(0, str(PHASE1_ROOT))


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


def test_formal_scenario_worker_environment_binds_profile_and_policy(
    tmp_path: Path,
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
    assert env["MAVI_DEPLOYMENT_PROFILE_POLICY_PATH"] == str(
        (
            args.bundle_dir
            / "release"
            / "config"
            / "acceptance"
            / "phase1-deployment-profiles-v1.json"
        ).resolve()
    )


def test_failure_reprocess_worker_environment_binds_profile_and_policy(
    tmp_path: Path,
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
    assert env["MAVI_DEPLOYMENT_PROFILE_POLICY_PATH"] == str(
        (
            args.bundle_dir
            / "release"
            / "config"
            / "acceptance"
            / "phase1-deployment-profiles-v1.json"
        ).resolve()
    )
