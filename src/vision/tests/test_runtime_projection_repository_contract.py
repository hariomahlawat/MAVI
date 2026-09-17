from __future__ import annotations

import hashlib
import json
from pathlib import Path

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


def test_component_requirements_bind_current_runtime_and_model_inputs() -> None:
    repository_root = Path(__file__).parents[3]
    runtime_root = repository_root / "src/vision/runtime/mmdetection-phase1-v1"
    components = json.loads((runtime_root / "components.json").read_text(encoding="utf-8"))
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
