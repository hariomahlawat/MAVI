from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from mavi_vision.runtime.component_identity import (
    ModelPackIdentityInputs,
    RuntimePackIdentityInputs,
    model_pack_id,
    runtime_pack_id,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_runtime_requirements_projection_is_forced_to_lf_on_checkout() -> None:
    repository_root = Path(__file__).parents[3]
    attributes = (repository_root / ".gitattributes").read_text(encoding="utf-8")
    assert "*.requirements.txt text eol=lf" in attributes.splitlines()


def test_task12_heavy_trigger_excludes_ordinary_first_party_source() -> None:
    repository_root = Path(__file__).parents[3]
    workflow = (repository_root / ".github/workflows/task12-offline-bundle.yml").read_text(
        encoding="utf-8"
    )
    forbidden = {
        "src/vision/mavi_vision/**",
        "src/vision/**",
        "src/vision/tests/**",
    }
    for path in forbidden:
        assert f"- '{path}'" not in workflow
    # Only runtime-boundary implementation files may directly trigger Task 12.
    for required in (
        "src/vision/mavi_vision/runtime/offline_lock.py",
        "src/vision/mavi_vision/runtime/requirements_projection.py",
        "src/vision/mavi_vision/runtime/component_identity.py",
        "src/vision/pyproject.toml",
        "src/vision/runtime/mmdetection-phase1-v1/**",
    ):
        assert f"- '{required}'" in workflow


def test_component_requirements_bind_current_runtime_and_model_inputs() -> None:
    repository_root = Path(__file__).parents[3]
    runtime_root = repository_root / "src/vision/runtime/mmdetection-phase1-v1"
    component_path = (
        repository_root
        / "src/vision/config/components/mmdetection-phase1-v1.json"
    )
    components = json.loads(component_path.read_text(encoding="utf-8"))
    assert components["schemaVersion"] == "mavi-vision-component-requirements-v1"
    assert components["runtimeProfileId"] == "mmdetection-phase1-v1"

    expected_native_abi = {
        "windows-x86_64-cpu": "win_amd64-msvc-14.44-sdk-10.0.26100.0",
        "linux-x86_64-cpu": "glibc-2.39-libstdcxx-GLIBCXX_3.4.33-gcc-14.2.0-linux_x86_64",
    }
    expected_python = {
        "windows-x86_64-cpu": "3.12.10",
        "linux-x86_64-cpu": "3.12.14",
    }
    # Plan Gate C5 requires Development `Auto` to keep choosing CPU until the
    # Application Overlay binding lands. That holds today only because no CUDA
    # Runtime Pack is declared here, which nothing else asserts. C5 must delete
    # this deliberately rather than drift past it.
    assert set(components["runtimePacks"]) == {
        "windows-x86_64-cpu",
        "linux-x86_64-cpu",
    }

    for variant, binding in components["runtimePacks"].items():
        lock_hash = _sha(runtime_root / f"{variant}.lock")
        requirements_hash = _sha(runtime_root / f"{variant}.requirements.txt")
        assert binding["thirdPartyLockSha256"] == lock_hash
        assert binding["runtimeRequirementsSha256"] == requirements_hash
        assert binding["nativeAbi"] == expected_native_abi[variant]
        expected_id = runtime_pack_id(
            RuntimePackIdentityInputs(
                platform_variant=variant,
                python_version=expected_python[variant],
                third_party_lock_sha256=lock_hash,
                runtime_requirements_sha256=requirements_hash,
                native_abi=expected_native_abi[variant],
            )
        )
        assert binding["runtimePackId"] == expected_id

    model_source = json.loads(
        (repository_root / "models/manifests/rtmdet-m-coco-phase1-v1.json").read_text(
            encoding="utf-8"
        )
    )
    model = components["modelPack"]
    assert model["modelId"] == model_source["modelId"]
    assert model["checkpointSha256"] == model_source["checkpoint"]["sha256"]
    assert model["resolvedConfigSha256"] == model_source["resolvedConfig"]["sha256"]
    assert model["modelPackId"] == model_pack_id(
        ModelPackIdentityInputs(
            model_id=model["modelId"],
            checkpoint_sha256=model["checkpointSha256"],
            resolved_config_sha256=model["resolvedConfigSha256"],
        )
    )


def test_every_declared_runtime_pack_is_covered_by_the_boundary_gate():
    """The gate that enforces Gate C5's identity contract is matrix-driven.

    `vision-runtime-component-boundary.yml` recomputes each Runtime Pack ID from
    the tracked lock, the regenerated requirements projection and a declared
    native ABI, and requires exact equality with the component binding. It runs
    one job per matrix row, so a variant declared in the component config but
    absent from the matrix is simply never checked -- the gate would pass by
    having nothing to say. C5 adds `windows-x86_64-cuda` to that config, and
    this is what makes it add the matrix row too.
    """
    repository_root = Path(__file__).resolve().parents[3]
    components = json.loads(
        (
            repository_root
            / "src/vision/config/components/mmdetection-phase1-v1.json"
        ).read_text(encoding="utf-8")
    )
    workflow = (
        repository_root
        / ".github/workflows/vision-runtime-component-boundary.yml"
    ).read_text(encoding="utf-8")

    covered = set(re.findall(r"^\s*- variant:\s*(\S+)\s*$", workflow, re.MULTILINE))

    assert covered == set(components["runtimePacks"])


def test_every_setup_powershell_module_is_parsed_by_the_acceptance_gate():
    """A module nothing parses is a syntax error nobody sees until Windows.

    `Mavi.VisionRuntime.Integrity.psm1` -- the Auto integrity preflight -- was
    the one module missing from the list, so a parse error in it would have
    surfaced only indirectly, through whichever script imports it.
    """
    repository_root = Path(__file__).resolve().parents[3]
    workflow = (
        repository_root / ".github/workflows/task17-acceptance.yml"
    ).read_text(encoding="utf-8")

    modules = {
        path.name
        for path in (repository_root / "tools/setup").glob("*.psm1")
    }

    assert modules, "no PowerShell modules found to check"
    for module in sorted(modules):
        assert f'"tools/setup/{module}"' in workflow, module


# ---------------------------------------------------------------------------
# The CUDA acquisition closure
#
# C2.3 originally named four packages by hand. On the host that resolved
# Pillow 12.3.0 against a frozen pillow==11.3.0 and silently omitted fifteen
# other pinned roots. These pin that the derivation -- which is what the
# runbook now drives acquisition from -- actually carries them.
# ---------------------------------------------------------------------------

import importlib.util as _importlib_util
import sys as _sys


def _cuda_projection():
    root = Path(__file__).resolve().parents[3]
    spec = _importlib_util.spec_from_file_location(
        "_projection_for_acquisition",
        root / "src/vision/mavi_vision/runtime/requirements_projection.py",
    )
    module = _importlib_util.module_from_spec(spec)
    _sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_runtime_requirements_projection(
        root / "src/vision/pyproject.toml",
        platform_variant="windows-x86_64-cuda",
        python_version="3.12.10",
    )


@pytest.mark.parametrize(
    "requirement",
    [
        "av==16.1.0",
        "trackers==2.6.0",
        "supervision==0.30.2",
        "pillow==11.3.0",
        "scipy==1.18.1",
        "opencv-python==5.0.0.93",
        "numpy==2.5.3",
        "mmcv==2.1.0",
        "mmdet==3.3.0",
        "mmengine==0.10.7",
        "torch==2.6.0",
        "torchvision==0.21.0",
    ],
)
def test_the_cuda_projection_carries_every_frozen_root(requirement: str) -> None:
    """Each of these was either missing from, or contradicted by, the hand list."""
    assert requirement in _cuda_projection().requirements


def test_the_cuda_projection_pins_pillow_below_twelve() -> None:
    """The exact contradiction the host hit: PyPI offered 12.3.0."""
    pillow = [
        item
        for item in _cuda_projection().requirements
        if item.startswith("pillow")
    ]
    assert "pillow==11.3.0" in pillow
    assert any("<12" in item for item in pillow)


def test_the_hand_written_subset_was_not_a_closure() -> None:
    """Names the regression rather than merely preventing it.

    Four packages against twenty-one roots. If a later edit shrinks the
    derivation back towards that, this says so.
    """
    derived = {
        item.split("=")[0].split("<")[0].split(">")[0]
        for item in _cuda_projection().requirements
    }
    hand_written = {"mmengine", "mmdet", "numpy", "pillow"}

    assert hand_written < derived
    assert len(derived - hand_written) >= 10
