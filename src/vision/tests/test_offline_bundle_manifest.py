from __future__ import annotations

from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import zipfile
import sys

import pytest

from mavi_vision.runtime.offline_lock import (
    LockedDistribution,
    OfflineRuntimeLock,
    serialize_offline_runtime_lock,
)


BUNDLE_TOOL_PATH = (
    Path(__file__).parents[3] / "tools" / "vision" / "build_offline_bundle.py"
)


def _load_bundle_tool():
    spec = importlib.util.spec_from_file_location(
        "build_offline_bundle",
        BUNDLE_TOOL_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("build_offline_bundle_module_unloadable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_wheel(
    root: Path,
    *,
    filename: str,
    name: str,
    version: str,
) -> Path:
    path = root / filename
    root.mkdir(parents=True, exist_ok=True)
    dist_info = f"{name.replace('-', '_')}-{version}.dist-info"
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{dist_info}/METADATA", metadata)
    return path


def _fixture_inputs(tmp_path: Path):
    tool = _load_bundle_tool()
    source = tmp_path / "source"
    wheelhouse = source / "wheelhouse"
    mavi_wheel = _write_wheel(
        wheelhouse,
        filename="mavi_vision-0.1.0-py3-none-any.whl",
        name="mavi-vision",
        version="0.1.0",
    )
    torch_wheel = _write_wheel(
        wheelhouse,
        filename="torch-2.6.0+cpu-py3-none-any.whl",
        name="torch",
        version="2.6.0+cpu",
    )
    lock = OfflineRuntimeLock(
        schema_version="mavi-offline-lock-v1",
        platform_variant="linux-x86_64-cpu",
        python_version="3.12.14",
        distributions=tuple(
            sorted(
                (
                    LockedDistribution(
                        "mavi-vision",
                        "0.1.0",
                        tool.sha256_file(mavi_wheel),
                    ),
                    LockedDistribution(
                        "torch",
                        "2.6.0+cpu",
                        tool.sha256_file(torch_wheel),
                    ),
                ),
                key=lambda item: item.name,
            )
        ),
    )

    files: dict[str, Path] = {}
    payloads = {
        "manifest": b'{"verificationStatus":"unverified"}\n',
        "qualification": b'{"overallResult":"pending"}\n',
        "profile": b'{"profileId":"profile-a"}\n',
        "runtime": b'{"runtimeProfileId":"runtime-a"}\n',
        "checkpoint": b"checkpoint",
        "config": b"model = dict(type='RTMDet')\n",
        "lock": serialize_offline_runtime_lock(lock),
    }
    for name, payload in payloads.items():
        path = source / f"{name}.bin"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        files[name] = path

    return tool, tool.VerifiedBundleInputs(
        source_commit="1" * 40,
        release_status="qualification-candidate",
        platform_variant="linux-x86_64-cpu",
        python_version="3.12.14",
        model_id="model-a",
        runtime_profile_id="runtime-a",
        model_manifest_path=files["manifest"],
        qualification_path=files["qualification"],
        pipeline_profile_path=files["profile"],
        runtime_profile_path=files["runtime"],
        runtime_lock_path=files["lock"],
        checkpoint_path=files["checkpoint"],
        resolved_config_path=files["config"],
        checkpoint_sha256=tool.sha256_file(files["checkpoint"]),
        resolved_config_sha256=tool.sha256_file(files["config"]),
        wheelhouse=wheelhouse,
    )


def _relative_file_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_same_inputs_create_identical_bundle_bytes(tmp_path: Path) -> None:
    tool, inputs = _fixture_inputs(tmp_path)
    first = tmp_path / "out-a"
    second = tmp_path / "out-b"

    first_manifest = tool.build_bundle_from_verified_inputs(inputs, first)
    second_manifest = tool.build_bundle_from_verified_inputs(inputs, second)

    assert first_manifest == second_manifest
    assert _relative_file_bytes(first) == _relative_file_bytes(second)


def test_bundle_manifest_lists_every_product_file_once_except_itself(
    tmp_path: Path,
) -> None:
    tool, inputs = _fixture_inputs(tmp_path)
    output = tmp_path / "bundle"

    tool.build_bundle_from_verified_inputs(inputs, output)

    payload = json.loads((output / "bundle-manifest.json").read_text(encoding="utf-8"))
    manifest_paths = [item["relativePath"] for item in payload["artifacts"]]
    actual_paths = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file() and path.name != "bundle-manifest.json"
    }

    assert "bundle-manifest.json" not in manifest_paths
    assert len(manifest_paths) == len(set(manifest_paths))
    assert set(manifest_paths) == actual_paths
    assert payload["releaseStatus"] == "qualification-candidate"
    assert payload["sourceCommit"] == "1" * 40
    assert "generatedAt" not in payload
    assert "hostname" not in payload


@pytest.mark.parametrize(
    "value",
    [
        "/absolute/file",
        "../escape",
        "release/../escape",
        r"release\windows",
        "",
    ],
)
def test_bundle_logical_paths_are_strictly_relative_posix(
    value: str,
) -> None:
    tool = _load_bundle_tool()

    with pytest.raises(tool.OfflineBundleError, match="bundle_path_invalid"):
        tool.validate_bundle_relative_path(value)


def test_bundle_rejects_nonempty_destination(tmp_path: Path) -> None:
    tool, inputs = _fixture_inputs(tmp_path)
    output = tmp_path / "bundle"
    output.mkdir()
    (output / "stale.txt").write_text("stale", encoding="utf-8")

    with pytest.raises(tool.OfflineBundleError, match="bundle_destination_not_empty"):
        tool.build_bundle_from_verified_inputs(inputs, output)

    assert (output / "stale.txt").read_text(encoding="utf-8") == "stale"


def test_bundle_rejects_extra_or_missing_wheel(tmp_path: Path) -> None:
    tool, inputs = _fixture_inputs(tmp_path)
    extra = _write_wheel(
        inputs.wheelhouse,
        filename="extra-1.0-py3-none-any.whl",
        name="extra",
        version="1.0",
    )

    with pytest.raises(tool.OfflineBundleError, match="wheelhouse_distribution_mismatch"):
        tool.build_bundle_from_verified_inputs(inputs, tmp_path / "extra-output")

    extra.unlink()
    next(inputs.wheelhouse.glob("torch-*.whl")).unlink()
    with pytest.raises(tool.OfflineBundleError, match="wheelhouse_distribution_mismatch"):
        tool.build_bundle_from_verified_inputs(inputs, tmp_path / "missing-output")


def test_bundle_rejects_wheel_hash_drift(tmp_path: Path) -> None:
    tool, inputs = _fixture_inputs(tmp_path)
    wheel = next(inputs.wheelhouse.glob("torch-*.whl"))
    wheel.write_bytes(wheel.read_bytes() + b"drift")

    with pytest.raises(tool.OfflineBundleError, match="wheel_hash_mismatch"):
        tool.build_bundle_from_verified_inputs(inputs, tmp_path / "bundle")


def test_bundle_rejects_checkpoint_or_config_hash_drift(tmp_path: Path) -> None:
    tool, inputs = _fixture_inputs(tmp_path)
    inputs.checkpoint_path.write_bytes(b"changed")

    with pytest.raises(tool.OfflineBundleError, match="checkpoint_hash_mismatch"):
        tool.build_bundle_from_verified_inputs(inputs, tmp_path / "checkpoint-output")

    tool, inputs = _fixture_inputs(tmp_path / "second")
    inputs.resolved_config_path.write_bytes(b"changed")
    with pytest.raises(tool.OfflineBundleError, match="resolved_config_hash_mismatch"):
        tool.build_bundle_from_verified_inputs(inputs, tmp_path / "config-output")


def test_bundle_rejects_symlink_input_and_leaves_no_partial_output(
    tmp_path: Path,
) -> None:
    tool, inputs = _fixture_inputs(tmp_path)
    target = inputs.model_manifest_path
    link = target.with_name("manifest-link.json")
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")

    linked_inputs = replace(inputs, model_manifest_path=link)
    output = tmp_path / "bundle"

    with pytest.raises(tool.OfflineBundleError, match="bundle_input_link_forbidden"):
        tool.build_bundle_from_verified_inputs(linked_inputs, output)

    assert not output.exists()
    assert not list(tmp_path.glob(".bundle.*"))


def test_release_mode_policy_fails_closed_for_current_candidate() -> None:
    tool = _load_bundle_tool()

    tool.validate_release_mode(
        "qualification-candidate",
        verification_status="unverified",
        runtime_qualification_status="partial",
        qualification_overall_result="pending",
        all_mandatory_gates_passed=False,
    )

    with pytest.raises(tool.OfflineBundleError, match="production_release_not_qualified"):
        tool.validate_release_mode(
            "production",
            verification_status="unverified",
            runtime_qualification_status="partial",
            qualification_overall_result="pending",
            all_mandatory_gates_passed=False,
        )

    tool.validate_release_mode(
        "production",
        verification_status="verified",
        runtime_qualification_status="qualified",
        qualification_overall_result="passed",
        all_mandatory_gates_passed=True,
    )


def test_release_mode_rejects_unknown_mode() -> None:
    tool = _load_bundle_tool()

    with pytest.raises(tool.OfflineBundleError, match="bundle_release_status_invalid"):
        tool.validate_release_mode(
            "developer",
            verification_status="unverified",
            runtime_qualification_status="partial",
            qualification_overall_result="pending",
            all_mandatory_gates_passed=False,
        )


def test_install_instructions_are_offline_only(tmp_path: Path) -> None:
    tool, inputs = _fixture_inputs(tmp_path)
    output = tmp_path / "bundle"

    tool.build_bundle_from_verified_inputs(inputs, output)

    instructions = (output / "INSTALL.txt").read_text(encoding="utf-8")
    assert "--no-index" in instructions
    assert "--only-binary=:all:" in instructions
    assert "--require-hashes" in instructions
    assert "--find-links ./wheels" in instructions
    assert "3.12.14" in instructions
    assert "http://" not in instructions
    assert "https://" not in instructions
