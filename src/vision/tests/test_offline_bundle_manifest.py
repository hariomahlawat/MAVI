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
    package_files: dict[str, bytes] | None = None,
    requires_python: str | None = None,
    requires_dist: tuple[str, ...] = (),
) -> Path:
    path = root / filename
    root.mkdir(parents=True, exist_ok=True)
    dist_info = f"{name.replace('-', '_')}-{version}.dist-info"
    metadata_lines = [
        "Metadata-Version: 2.1",
        f"Name: {name}",
        f"Version: {version}",
    ]
    if requires_python is not None:
        metadata_lines.append(f"Requires-Python: {requires_python}")
    metadata_lines.extend(f"Requires-Dist: {item}" for item in requires_dist)
    metadata = "\n".join(metadata_lines) + "\n\n"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{dist_info}/METADATA", metadata)
        parts = filename[:-4].split("-")
        python_tag = parts[-3].split(".", 1)[0]
        abi_tag = parts[-2].split(".", 1)[0]
        platform_tag = parts[-1].split(".", 1)[0]
        wheel_metadata = (
            "Wheel-Version: 1.0\n"
            "Generator: mavi-tests\n"
            "Root-Is-Purelib: true\n"
            f"Tag: {python_tag}-{abi_tag}-{platform_tag}\n\n"
        )
        archive.writestr(f"{dist_info}/WHEEL", wheel_metadata)
        archive.writestr(f"{dist_info}/RECORD", f"{dist_info}/RECORD,,\n")
        for logical_path, payload in sorted((package_files or {}).items()):
            archive.writestr(logical_path, payload)
    return path


def _fixture_inputs(tmp_path: Path, *, bypass_revalidation: bool = True):
    tool = _load_bundle_tool()
    source = tmp_path / "source"
    mavi_source_root = source / "vision"
    package_root = mavi_source_root / "mavi_vision"
    package_root.mkdir(parents=True, exist_ok=True)
    package_init = b'__version__ = "0.1.0"\n'
    (package_root / "__init__.py").write_bytes(package_init)
    (mavi_source_root / "pyproject.toml").write_text(
        """[project]
name = "mavi-vision"
version = "0.1.0"
requires-python = ">=3.12,<3.14"
dependencies = []
""",
        encoding="utf-8",
    )

    wheelhouse = source / "wheelhouse"
    mavi_wheel = _write_wheel(
        wheelhouse,
        filename="mavi_vision-0.1.0-py3-none-any.whl",
        name="mavi-vision",
        version="0.1.0",
        package_files={"mavi_vision/__init__.py": package_init},
        requires_python=">=3.12,<3.14",
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

    tool.VISION_ROOT = mavi_source_root
    inputs = tool.VerifiedBundleInputs(
        source_commit=tool._repository_head(tool.ROOT),
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
        deployment_profile_policy_path=(
            tool.CANONICAL_DEPLOYMENT_PROFILE_POLICY
        ),
        deployment_profile_policy_sha256=tool.sha256_file(
            tool.CANONICAL_DEPLOYMENT_PROFILE_POLICY
        ),
        deployment_profile_id=None,
    )
    if bypass_revalidation:
        tool._revalidate_assembly_boundary = lambda _inputs: {
            inputs.platform_variant: inputs.runtime_lock_path,
        }
        tool._verify_bundled_release_selection = lambda _stage, _inputs: None

    return tool, inputs


def _relative_file_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_bundle_rejects_python_installer_for_non_windows_variant(
    tmp_path: Path,
) -> None:
    tool, inputs = _fixture_inputs(tmp_path)
    installer = tmp_path / "python-installer.bin"
    installer.write_bytes(b"fixture")
    inputs = replace(inputs, python_installer_path=installer)

    with pytest.raises(
        tool.OfflineBundleError,
        match="python_installer_platform_mismatch",
    ):
        tool.build_bundle_from_verified_inputs(inputs, tmp_path / "bundle")


def test_bundle_rejects_mavi_wheel_from_different_source_tree(
    tmp_path: Path,
) -> None:
    tool, inputs = _fixture_inputs(tmp_path)
    (tool.VISION_ROOT / "mavi_vision" / "__init__.py").write_text(
        '__version__ = "0.1.1"\n',
        encoding="utf-8",
    )

    with pytest.raises(tool.OfflineBundleError, match="mavi_wheel_source_mismatch"):
        tool.build_bundle_from_verified_inputs(inputs, tmp_path / "bundle")


@pytest.mark.parametrize(
    "logical_path",
    [
        "mavi_vision/native_payload.pyd",
        "mavi_vision/native_payload.so",
        "mavi_startup.pth",
    ],
)
def test_mavi_wheel_source_rejects_untracked_installable_payload(
    tmp_path: Path,
    logical_path: str,
) -> None:
    tool, inputs = _fixture_inputs(tmp_path)
    wheel = next(inputs.wheelhouse.glob("mavi_vision-*.whl"))
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr(logical_path, b"untracked executable payload")

    with pytest.raises(tool.OfflineBundleError, match="mavi_wheel_source_mismatch"):
        tool._verify_mavi_wheel_source(
            wheel_records={"mavi-vision": tool.inspect_wheel(wheel)},
            source_root=tool.VISION_ROOT,
        )


def test_mavi_wheel_source_verifies_non_python_package_files(
    tmp_path: Path,
) -> None:
    tool, inputs = _fixture_inputs(tmp_path)
    package_root = tool.VISION_ROOT / "mavi_vision"
    package_data = b'{"schemaVersion": 1}\n'
    (package_root / "schema.json").write_bytes(package_data)

    wheel = next(inputs.wheelhouse.glob("mavi_vision-*.whl"))
    wheel.unlink()
    package_init = (package_root / "__init__.py").read_bytes()
    wheel = _write_wheel(
        inputs.wheelhouse,
        filename="mavi_vision-0.1.0-py3-none-any.whl",
        name="mavi-vision",
        version="0.1.0",
        package_files={
            "mavi_vision/__init__.py": package_init,
            "mavi_vision/schema.json": package_data,
        },
        requires_python=">=3.12,<3.14",
    )

    tool._verify_mavi_wheel_source(
        wheel_records={"mavi-vision": tool.inspect_wheel(wheel)},
        source_root=tool.VISION_ROOT,
    )


def test_mavi_wheel_metadata_accepts_pyproject_optional_dependencies(
    tmp_path: Path,
) -> None:
    tool, inputs = _fixture_inputs(tmp_path)
    project = tool.VISION_ROOT / "pyproject.toml"
    project.write_text(
        project.read_text(encoding="utf-8")
        + '\n[project.optional-dependencies]\ndev = ["pytest>=8.4"]\n',
        encoding="utf-8",
    )

    wheel = next(inputs.wheelhouse.glob("mavi_vision-*.whl"))
    wheel.unlink()
    package_init = (tool.VISION_ROOT / "mavi_vision" / "__init__.py").read_bytes()
    wheel = _write_wheel(
        inputs.wheelhouse,
        filename="mavi_vision-0.1.0-py3-none-any.whl",
        name="mavi-vision",
        version="0.1.0",
        package_files={"mavi_vision/__init__.py": package_init},
        requires_python=">=3.12,<3.14",
        requires_dist=('pytest>=8.4; extra == "dev"',),
    )

    tool._verify_mavi_wheel_source(
        wheel_records={"mavi-vision": tool.inspect_wheel(wheel)},
        source_root=tool.VISION_ROOT,
    )


def test_mavi_wheel_metadata_rejects_wrong_optional_dependency_extra(
    tmp_path: Path,
) -> None:
    tool, inputs = _fixture_inputs(tmp_path)
    project = tool.VISION_ROOT / "pyproject.toml"
    project.write_text(
        project.read_text(encoding="utf-8")
        + '\n[project.optional-dependencies]\ndev = ["pytest>=8.4"]\n',
        encoding="utf-8",
    )

    wheel = next(inputs.wheelhouse.glob("mavi_vision-*.whl"))
    wheel.unlink()
    package_init = (tool.VISION_ROOT / "mavi_vision" / "__init__.py").read_bytes()
    wheel = _write_wheel(
        inputs.wheelhouse,
        filename="mavi_vision-0.1.0-py3-none-any.whl",
        name="mavi-vision",
        version="0.1.0",
        package_files={"mavi_vision/__init__.py": package_init},
        requires_python=">=3.12,<3.14",
        requires_dist=('pytest>=8.4; extra == "other"',),
    )

    with pytest.raises(tool.OfflineBundleError, match="mavi_wheel_metadata_mismatch"):
        tool._verify_mavi_wheel_source(
            wheel_records={"mavi-vision": tool.inspect_wheel(wheel)},
            source_root=tool.VISION_ROOT,
        )


def test_bundle_rejects_mavi_wheel_with_stale_project_metadata(
    tmp_path: Path,
) -> None:
    tool, inputs = _fixture_inputs(tmp_path)
    project = tool.VISION_ROOT / "pyproject.toml"
    project.write_text(
        project.read_text(encoding="utf-8").replace(
            'requires-python = ">=3.12,<3.14"',
            'requires-python = ">=3.12,<3.13"',
        ),
        encoding="utf-8",
    )

    with pytest.raises(tool.OfflineBundleError, match="mavi_wheel_metadata_mismatch"):
        tool.build_bundle_from_verified_inputs(inputs, tmp_path / "bundle")


def test_bundle_source_commit_rejects_dirty_packaged_source(
    tmp_path: Path,
) -> None:
    tool = _load_bundle_tool()
    repo = tmp_path / "repo"
    package = repo / "src" / "vision" / "mavi_vision"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("value = 1\n", encoding="utf-8")
    project = repo / "src" / "vision" / "pyproject.toml"
    project.write_text("[project]\nname='mavi-vision'\nversion='0.1.0'\n", encoding="utf-8")
    setup_cfg = repo / "src" / "vision" / "setup.cfg"
    setup_cfg.write_text("[metadata]\nname = mavi-vision\n", encoding="utf-8")
    ignore = repo / "src" / "vision" / ".gitignore"
    ignore.write_text("*.pth\n__pycache__/\n*.pyc\n", encoding="utf-8")

    def run(*args: str) -> None:
        import subprocess
        subprocess.run(
            args,
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )

    run("git", "init")
    run("git", "config", "user.email", "task12@example.invalid")
    run("git", "config", "user.name", "Task 12")
    run("git", "add", ".")
    run("git", "commit", "-m", "fixture")
    head = tool._repository_head(repo)

    (package / "dirty.py").write_text("dirty = True\n", encoding="utf-8")
    with pytest.raises(tool.OfflineBundleError, match="bundle_source_dirty"):
        tool._validate_source_commit_against_checkout(head, repo)

    (package / "dirty.py").unlink()
    (package / "__init__.py").write_text("value = 2\n", encoding="utf-8")
    with pytest.raises(tool.OfflineBundleError, match="bundle_source_dirty"):
        tool._validate_source_commit_against_checkout(head, repo)

    run("git", "checkout", "--", "src/vision/mavi_vision/__init__.py")
    setup_cfg.write_text("[metadata]\nname = changed-name\n", encoding="utf-8")
    with pytest.raises(tool.OfflineBundleError, match="bundle_source_dirty"):
        tool._validate_source_commit_against_checkout(head, repo)

    run("git", "checkout", "--", "src/vision/setup.cfg")
    ignored_payload = package / "ignored_payload.pth"
    ignored_payload.write_text("import unexpected_payload\n", encoding="utf-8")
    with pytest.raises(tool.OfflineBundleError, match="bundle_source_dirty"):
        tool._validate_source_commit_against_checkout(head, repo)

    ignored_payload.unlink()
    cache = package / "__pycache__"
    cache.mkdir()
    (cache / "generated.pyc").write_bytes(b"generated")
    tool._validate_source_commit_against_checkout(head, repo)


def test_bundle_source_commit_must_match_repository_checkout() -> None:
    tool = _load_bundle_tool()

    with pytest.raises(tool.OfflineBundleError, match="bundle_source_commit_mismatch"):
        tool._validate_source_commit_against_checkout("1" * 40, tool.ROOT)


def test_verified_bundle_inputs_cannot_redirect_mavi_source_tree(
    tmp_path: Path,
) -> None:
    tool, _ = _fixture_inputs(tmp_path)

    assert "mavi_source_root" not in tool.VerifiedBundleInputs.__dataclass_fields__


def test_direct_assembler_revalidates_candidate_metadata(
    tmp_path: Path,
) -> None:
    tool, inputs = _fixture_inputs(tmp_path, bypass_revalidation=False)

    with pytest.raises(tool.OfflineBundleError, match="model_manifest_invalid"):
        tool.build_bundle_from_verified_inputs(
            inputs,
            tmp_path / "candidate-bundle",
        )


def test_direct_assembler_rechecks_production_release_eligibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool, inputs = _fixture_inputs(tmp_path, bypass_revalidation=False)

    class Manifest:
        verification_status = "unverified"
        model_id = inputs.model_id
        checkpoint = type("Artifact", (), {"sha256": inputs.checkpoint_sha256})()
        resolved_config = type(
            "Artifact",
            (),
            {"sha256": inputs.resolved_config_sha256},
        )()

    class Qualification:
        required_gates = {}
        overall_result = "pending"

    class Platform:
        python_identity = type("PythonIdentity", (), {"version": inputs.python_version})()

    class Selection:
        manifest = Manifest()
        qualification = Qualification()
        verification_status = "unverified"
        runtime_qualification_status = "partial"
        runtime_profile_id = inputs.runtime_profile_id
        runtime_platform_variants = {inputs.platform_variant: Platform()}
        checkpoint_path = inputs.checkpoint_path
        resolved_config_path = inputs.resolved_config_path

    monkeypatch.setattr(tool, "_infer_model_root", lambda _: tmp_path)
    monkeypatch.setattr(tool, "verify_release_selection", lambda **_: Selection())
    monkeypatch.setattr(tool, "load_runtime_profile", lambda _: object())
    monkeypatch.setattr(
        tool,
        "verify_runtime_release_locks",
        lambda *_: {inputs.platform_variant: inputs.runtime_lock_path},
    )

    production_inputs = replace(
        inputs,
        release_status="production",
        platform_variant="windows-x86_64-cpu",
        deployment_profile_id="P3",
    )
    with pytest.raises(
        tool.OfflineBundleError,
        match="production_release_not_profile_qualified",
    ):
        tool.build_bundle_from_verified_inputs(
            production_inputs,
            tmp_path / "production-bundle",
        )


def test_same_inputs_create_identical_bundle_bytes(tmp_path: Path) -> None:
    tool, inputs = _fixture_inputs(tmp_path)
    first = tmp_path / "out-a"
    second = tmp_path / "out-b"

    first_manifest = tool.build_bundle_from_verified_inputs(inputs, first)
    second_manifest = tool.build_bundle_from_verified_inputs(inputs, second)

    assert first_manifest == second_manifest
    assert _relative_file_bytes(first) == _relative_file_bytes(second)


def test_bundle_carries_only_selected_runtime_lock_and_ignores_unrelated_lock(
    tmp_path: Path,
) -> None:
    tool, inputs = _fixture_inputs(tmp_path)
    selected_lock = tool.load_offline_runtime_lock(
        inputs.runtime_lock_path
    )
    unrelated_lock = OfflineRuntimeLock(
        schema_version=selected_lock.schema_version,
        platform_variant="windows-x86_64-cpu",
        python_version="3.12.10",
        distributions=selected_lock.distributions,
    )
    unrelated_lock_path = (
        tmp_path / "windows-x86_64-cpu.lock"
    )
    unrelated_lock_path.write_bytes(
        serialize_offline_runtime_lock(unrelated_lock)
    )

    # The assembly boundary deliberately returns only the selected profile
    # variant. An unrelated qualified lock must not enter this bundle.
    tool._revalidate_assembly_boundary = lambda _inputs: {
        inputs.platform_variant: inputs.runtime_lock_path,
    }

    first = tmp_path / "bundle-a"
    first_manifest = tool.build_bundle_from_verified_inputs(
        inputs,
        first,
    )

    selected_path = (
        first
        / "release"
        / "runtime"
        / "mmdetection-phase1-v1"
        / "linux-x86_64-cpu.lock"
    )
    unrelated_path = (
        first
        / "release"
        / "runtime"
        / "mmdetection-phase1-v1"
        / "windows-x86_64-cpu.lock"
    )
    assert selected_path.is_file()
    assert not unrelated_path.exists()

    artifact_variants = {
        item.platform_variant
        for item in first_manifest.artifacts
        if item.purpose == "runtime-lock"
    }
    assert artifact_variants == {"linux-x86_64-cpu"}

    changed_unrelated_lock = replace(
        unrelated_lock,
        distributions=(
            *unrelated_lock.distributions[:-1],
            replace(
                unrelated_lock.distributions[-1],
                sha256="f" * 64,
            ),
        ),
    )
    unrelated_lock_path.write_bytes(
        serialize_offline_runtime_lock(
            changed_unrelated_lock
        )
    )

    second = tmp_path / "bundle-b"
    second_manifest = tool.build_bundle_from_verified_inputs(
        inputs,
        second,
    )
    assert second_manifest.bundle_id == first_manifest.bundle_id
    assert _relative_file_bytes(second) == _relative_file_bytes(first)



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
    assert payload["sourceCommit"] == inputs.source_commit
    assert payload["hostCompatibility"] == {
        "architecture": "x86_64",
        "distribution": "ubuntu",
        "distributionVersion": "24.04",
        "nativeAbi": "glibc-2.39-libstdcxx-GLIBCXX_3.4.33-linux_x86_64",
        "osFamily": "linux",
        "portability": "qualified-host-only",
    }
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


def test_bundle_rejects_incomplete_wheel_dependency_closure(
    tmp_path: Path,
) -> None:
    tool, inputs = _fixture_inputs(tmp_path)
    wheel = next(inputs.wheelhouse.glob("mavi_vision-*.whl"))
    wheel.unlink()
    package_init = (tool.VISION_ROOT / "mavi_vision" / "__init__.py").read_bytes()
    _write_wheel(
        inputs.wheelhouse,
        filename="mavi_vision-0.1.0-py3-none-any.whl",
        name="mavi-vision",
        version="0.1.0",
        package_files={"mavi_vision/__init__.py": package_init},
        requires_python=">=3.12,<3.14",
        requires_dist=("missing-dependency>=1",),
    )

    with pytest.raises(tool.OfflineBundleError, match="wheel_dependency_missing"):
        tool.build_bundle_from_verified_inputs(
            inputs,
            tmp_path / "incomplete-dependency-output",
        )


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
        deployment_profile_id=None,
    )

    with pytest.raises(
        tool.OfflineBundleError,
        match="production_release_not_profile_qualified",
    ):
        tool.validate_release_mode(
            "production",
            verification_status="unverified",
            deployment_profile_id="P3",
        )

    with pytest.raises(
        tool.OfflineBundleError,
        match="production_release_not_profile_qualified",
    ):
        tool.validate_release_mode(
            "production",
            verification_status="verified",
            deployment_profile_id=None,
        )

    tool.validate_release_mode(
        "production",
        verification_status="verified",
        deployment_profile_id="P3",
    )


def test_release_mode_rejects_unknown_mode() -> None:
    tool = _load_bundle_tool()

    with pytest.raises(
        tool.OfflineBundleError,
        match="bundle_release_status_invalid",
    ):
        tool.validate_release_mode(
            "developer",
            verification_status="unverified",
            deployment_profile_id=None,
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
    assert "Qualified host: Ubuntu 24.04 x86_64" in instructions
    assert "Native ABI: glibc 2.39 / linux_x86_64" in instructions
    assert "libstdc++ ABI: GLIBCXX_3.4.33 available" in instructions
    assert "Portability: qualified-host-only" in instructions
    assert "http://" not in instructions
    assert "https://" not in instructions


def test_bundle_embeds_deployment_profile_policy(tmp_path: Path) -> None:
    tool, inputs = _fixture_inputs(tmp_path)
    output = tmp_path / "bundle"

    manifest = tool.build_bundle_from_verified_inputs(
        inputs,
        output,
    )

    policy_path = (
        output
        / "release"
        / "config"
        / "acceptance"
        / "phase1-deployment-profiles-v1.json"
    )
    assert policy_path.is_file()
    assert (
        tool.sha256_file(policy_path)
        == inputs.deployment_profile_policy_sha256
    )
    assert (
        manifest.deployment_profile_policy_sha256
        == inputs.deployment_profile_policy_sha256
    )


def test_production_bundle_requires_explicit_profile() -> None:
    tool = _load_bundle_tool()
    with pytest.raises(
        tool.OfflineBundleError,
        match="production_release_not_profile_qualified",
    ):
        tool.validate_release_mode(
            "production",
            verification_status="verified",
            deployment_profile_id=None,
        )


def test_every_qualified_lock_enters_the_bundle_identity_of_every_variant(
    tmp_path: Path,
) -> None:
    """A lock qualified for one variant changes the bundle ID of all of them.

    `verify_runtime_release_locks` returns every lock whose status is
    `qualified-offline-lock`, unfiltered by deployment profile, and `_bundle_id`
    folds all of them into `qualifiedReleaseLocks`. So freezing the Windows CUDA
    Development lock at C3 will change the identity of the Linux and Windows
    Production bundles too, and ship that lock inside them.

    ADR-009 records this consequence and leaves the choice open: either filter
    the bundled locks to what the selected deployment profile requires, or
    accept that a Development lock participates in Production bundle identity
    and reissue Production acceptance evidence. This test pins today's
    behaviour so whichever is chosen is chosen deliberately.
    """
    tool, inputs = _fixture_inputs(tmp_path)
    only_this_variant = {inputs.platform_variant: inputs.runtime_lock_path}

    other_lock = tmp_path / "windows-x86_64-cuda.lock"
    other_lock.write_bytes(b"a different qualified lock\n")
    with_a_foreign_lock = dict(
        only_this_variant, **{"windows-x86_64-cuda": other_lock}
    )

    assert tool._bundle_id(inputs, only_this_variant) != tool._bundle_id(
        inputs, with_a_foreign_lock
    )
