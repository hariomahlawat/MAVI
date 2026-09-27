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

    # An application overlay in the repository layout (the bundle mirrors it
    # under release/); the payloads are placeholders because the resolver is
    # bypassed here -- the resolver-backed paths are exercised further down.
    overlay = source / "overlay"
    files: dict[str, Path] = {}
    payloads = {
        "binding": ("binding.json", b'{"schemaVersion":"mavi-vision-component-binding-v2"}\n'),
        "manifest": ("models/manifests/model-a.json", b'{"verificationStatus":"unverified"}\n'),
        "qualification": ("models/qualifications/model-a.json", b'{"overallResult":"pending"}\n'),
        "gate-sets": ("config/acceptance/capability-gate-sets-v1.json", b'{"gateSets":[]}\n'),
        "profile": ("profile.json", b'{"profileId":"profile-a"}\n'),
        "runtime": ("src/vision/runtime/runtime-a/runtime.json", b'{"runtimeProfileId":"runtime-a"}\n'),
        "lock": ("src/vision/runtime/runtime-a/linux-x86_64-cpu.lock", serialize_offline_runtime_lock(lock)),
        "requirements": (
            "src/vision/runtime/runtime-a/linux-x86_64-cpu.requirements.txt",
            b"# schema: mavi-vision-runtime-requirements-v1\n"
            b"# platform-variant: linux-x86_64-cpu\n"
            b"# python-version: 3.12.14\n"
            b"torch==2.6.0+cpu\n",
        ),
        "checkpoint": ("store/model-a-v1/checkpoint.pth", b"checkpoint"),
        "config": ("store/model-a-v1/config.py", b"model = dict(type='RTMDet')\n"),
        "licence": ("store/model-a-v1/LICENSE", b"Apache License 2.0\n"),
    }
    for name, (relative, payload) in payloads.items():
        path = overlay / relative
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
        model_pack_id="mavi-model-v2-" + "7" * 64,
        component_binding_sha256=tool.sha256_file(files["binding"]),
        component_binding_path=files["binding"],
        overlay_root=overlay,
        model_root=overlay / "store",
        model_manifest_path=files["manifest"],
        qualification_path=files["qualification"],
        pipeline_profile_path=files["profile"],
        runtime_profile_path=files["runtime"],
        runtime_lock_path=files["lock"],
        model_artifacts=tuple(
            tool.BundledModelArtifact(
                artifact_role=role,
                relative_path=files[name].relative_to(overlay / "store").as_posix(),
                path=files[name],
                sha256=tool.sha256_file(files[name]),
            )
            for role, name in (
                ("checkpoint", "checkpoint"),
                ("licence-notice", "licence"),
                ("resolved-config", "config"),
            )
        ),
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
            "linux-x86_64-cpu.lock": files["lock"],
            "linux-x86_64-cpu.requirements.txt": files["requirements"],
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

    # The placeholder binding is the first file the resolver reads.
    with pytest.raises(tool.OfflineBundleError, match="component_binding_invalid"):
        tool.build_bundle_from_verified_inputs(
            inputs,
            tmp_path / "candidate-bundle",
        )

def test_a_production_bundle_is_refused_by_the_resolver_policy(tmp_path: Path) -> None:
    """P-8: a bundle-built environment is not an installed Runtime Pack.

    An unverified manifest is refused first; a fully qualified one is still
    refused, because Production requires an installed Runtime Pack. No bundle
    path reaches a Production claim after the cut-over.
    """
    from mavi_vision.runtime.deployment_profiles import select_profile
    from tests.resolver_overlay import DEPLOYMENT_PROFILES, Overlay

    tool = _load_bundle_tool()
    overlay = Overlay.create(tmp_path / "unverified")
    profile, policy_sha = select_profile("P3", DEPLOYMENT_PROFILES)

    def resolve(target):
        return tool.resolve_bundle_role(
            overlay_root=target.root,
            component_binding_path=target.binding_path,
            model_root=target.model_root,
            pipeline_profile_path=target.pipeline_path,
            platform_variant="windows-x86_64-cpu",
            release_status="production",
            deployment_profile=profile,
            deployment_profile_policy_sha256=policy_sha,
        )

    with pytest.raises(tool.OfflineBundleError, match="unverified_release_forbidden"):
        resolve(overlay)

    qualified = Overlay.create(tmp_path / "qualified")
    qualified.qualify_for_production()
    with pytest.raises(tool.OfflineBundleError, match="runtime_pack_required"):
        resolve(qualified)

def test_same_inputs_create_identical_bundle_bytes(tmp_path: Path) -> None:
    tool, inputs = _fixture_inputs(tmp_path)
    first = tmp_path / "out-a"
    second = tmp_path / "out-b"

    first_manifest = tool.build_bundle_from_verified_inputs(inputs, first)
    second_manifest = tool.build_bundle_from_verified_inputs(inputs, second)

    assert first_manifest == second_manifest
    assert _relative_file_bytes(first) == _relative_file_bytes(second)


def test_bundle_carries_every_binding_declared_lock_and_each_enters_its_identity(
    tmp_path: Path,
) -> None:
    """The bundle is a complete record of its runtime family (ADR-009 follow-up 5).

    The resolver cross-checks every lock the binding pins, so the staged overlay
    must carry all of them; and a lock that ships is part of the bundle identity.
    """
    tool, inputs = _fixture_inputs(tmp_path)
    runtime_dir = inputs.runtime_lock_path.parent
    other_lock = runtime_dir / "windows-x86_64-cpu.lock"
    other_requirements = runtime_dir / "windows-x86_64-cpu.requirements.txt"
    other_lock.write_bytes(b"# another variant's lock\n")
    other_requirements.write_bytes(b"# another variant's requirements\n")
    family = {
        "linux-x86_64-cpu.lock": inputs.runtime_lock_path,
        "linux-x86_64-cpu.requirements.txt": runtime_dir / "linux-x86_64-cpu.requirements.txt",
        "windows-x86_64-cpu.lock": other_lock,
        "windows-x86_64-cpu.requirements.txt": other_requirements,
    }
    tool._revalidate_assembly_boundary = lambda _inputs: dict(family)

    first = tmp_path / "bundle-a"
    first_manifest = tool.build_bundle_from_verified_inputs(inputs, first)

    bundled = first / "release" / "src" / "vision" / "runtime" / "runtime-a"
    assert sorted(path.name for path in bundled.iterdir()) == [
        "linux-x86_64-cpu.lock",
        "linux-x86_64-cpu.requirements.txt",
        "runtime.json",
        "windows-x86_64-cpu.lock",
        "windows-x86_64-cpu.requirements.txt",
    ]
    assert {
        (item.purpose, item.platform_variant)
        for item in first_manifest.artifacts
        if item.purpose.startswith("runtime-l") or item.purpose == "runtime-requirements"
    } == {
        ("runtime-lock", "linux-x86_64-cpu"),
        ("runtime-lock", "windows-x86_64-cpu"),
        ("runtime-requirements", "linux-x86_64-cpu"),
        ("runtime-requirements", "windows-x86_64-cpu"),
    }
    # The bundle's own lock is still the selected variant's.
    assert first_manifest.lock_sha256 == tool.sha256_file(inputs.runtime_lock_path)

    other_lock.write_bytes(b"# another variant's lock, changed\n")
    second_manifest = tool.build_bundle_from_verified_inputs(inputs, tmp_path / "bundle-b")
    assert second_manifest.bundle_id != first_manifest.bundle_id

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


@pytest.mark.parametrize(
    ("name", "role"),
    [("checkpoint.pth", "checkpoint"), ("config.py", "resolved-config"), ("LICENSE", "licence-notice")],
)
def test_bundle_rejects_model_artefact_hash_drift(tmp_path: Path, name: str, role: str) -> None:
    tool, inputs = _fixture_inputs(tmp_path)
    (inputs.model_root / "model-a-v1" / name).write_bytes(b"changed")

    with pytest.raises(tool.OfflineBundleError, match=f"model_artifact_hash_mismatch:{role}"):
        tool.build_bundle_from_verified_inputs(inputs, tmp_path / "output")
    assert not (tmp_path / "output").exists()

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
    # The worker composes the bundle through the binding; the retired paths are gone.
    assert "MAVI_COMPONENT_BINDING_PATH=./release/src/vision/config/components/phase1-bindings-v2.json" in instructions
    assert "MAVI_OVERLAY_ROOT=./release\n" in instructions
    assert "MAVI_ROLE_ID=vision\n" in instructions
    for retired in ("MAVI_MODEL_MANIFEST_PATH=", "MAVI_QUALIFICATION_RECORD_PATH=", "MAVI_RUNTIME_PROFILE_PATH="):
        assert retired not in instructions


def test_bundle_embeds_deployment_profile_policy(tmp_path: Path) -> None:
    tool, inputs = _fixture_inputs(tmp_path)
    output = tmp_path / "bundle"

    manifest = tool.build_bundle_from_verified_inputs(
        inputs,
        output,
    )

    policy_path = output / tool.BUNDLED_DEPLOYMENT_POLICY
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


# --------------------------------------------------------------------------- resolver-backed


def _overlay_bundle_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Real v2 composition (resolver overlay); only the wheel checks are stubbed."""
    from tests.resolver_overlay import Overlay

    tool = _load_bundle_tool()
    overlay = Overlay.create(tmp_path)
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    monkeypatch.setattr(tool, "_validate_wheelhouse", lambda *_: {})
    monkeypatch.setattr(tool, "_verify_mavi_wheel_source", lambda **_: None)
    inputs = tool.resolve_verified_bundle_inputs(
        source_commit=tool._repository_head(tool.ROOT),
        release_status="qualification-candidate",
        platform_variant="linux-x86_64-cpu",
        model_root=overlay.model_root,
        wheelhouse=wheelhouse,
        overlay_root=overlay.root,
        component_binding_path=overlay.binding_path,
        pipeline_profile_path=overlay.pipeline_path,
    )
    return tool, overlay, inputs


def test_a_candidate_bundle_is_a_resolvable_overlay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool, overlay, inputs = _overlay_bundle_inputs(tmp_path, monkeypatch)
    output = tmp_path / "bundle"
    manifest = tool.build_bundle_from_verified_inputs(inputs, output)

    assert inputs.model_pack_id == overlay.derived_model_pack_id()
    assert inputs.component_binding_sha256 == tool.sha256_file(overlay.binding_path)
    shipped = {item.relative_path for item in manifest.artifacts}
    for required in (
        "release/src/vision/config/components/phase1-bindings-v2.json",
        "release/models/manifests/rtmdet-m-coco-phase1-v2.json",
        "release/models/qualifications/rtmdet-m-coco-phase1-v2.json",
        "release/config/acceptance/capability-gate-sets-v1.json",
        "release/models/rtmdet-m-coco-phase1-v1/LICENSE",
        "release/src/vision/runtime/mmdetection-phase1-v1/runtime.json",
        "release/src/vision/runtime/mmdetection-phase1-v1/windows-x86_64-cuda.lock",
        "release/src/vision/runtime/mmdetection-phase1-v1/windows-x86_64-cuda.requirements.txt",
    ):
        assert required in shipped, required
    # The shipped overlay resolves on its own, to the same identities.
    payload = json.loads((output / "bundle-manifest.json").read_text(encoding="utf-8"))
    tool.verify_bundled_release_manifest(output, payload)
    staged = tool._resolve_staged_bundle(
        output,
        release_status="qualification-candidate",
        platform_variant="linux-x86_64-cpu",
        deployment_profile_id=None,
        expected_policy_sha256=inputs.deployment_profile_policy_sha256,
    )
    assert staged.capabilities["detector"].model_pack_id == inputs.model_pack_id
    assert staged.component_binding_sha256 == inputs.component_binding_sha256
    assert staged.runtime_pack.runtime_pack_id is None


def test_a_tampered_bundled_binding_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool, _overlay, inputs = _overlay_bundle_inputs(tmp_path, monkeypatch)
    output = tmp_path / "bundle"
    tool.build_bundle_from_verified_inputs(inputs, output)
    payload = json.loads((output / "bundle-manifest.json").read_text(encoding="utf-8"))

    bundled = output / tool.BUNDLED_BINDING
    document = json.loads(bundled.read_text(encoding="utf-8"))
    document["capabilityBindings"][0]["enabled"] = False
    bundled.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(tool.OfflineBundleError, match="capability_binding_disabled"):
        tool.verify_bundled_release_manifest(output, payload)


def test_the_assembly_boundary_refuses_inputs_that_moved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool, _overlay, inputs = _overlay_bundle_inputs(tmp_path, monkeypatch)
    moved = replace(inputs, model_pack_id="mavi-model-v2-" + "1" * 64)
    with pytest.raises(tool.OfflineBundleError, match="bundle_verified_inputs_mismatch"):
        tool.build_bundle_from_verified_inputs(moved, tmp_path / "bundle")
