from __future__ import annotations

from pathlib import Path

import pytest

from mavi_vision.runtime.requirements_projection import (
    RuntimeRequirementsError,
    build_runtime_requirements_projection,
    runtime_requirements_sha256,
    serialize_runtime_requirements_projection,
)


def _write_pyproject(path: Path, *, dependencies: str, vision_runtime: str, dev: str = '"pytest>=8.4"') -> Path:
    path.write_text(
        "\n".join(
            [
                "[project]",
                'name = "fixture"',
                'version = "0.0.0"',
                f"dependencies = [{dependencies}]",
                "",
                "[project.optional-dependencies]",
                f"vision-runtime = [{vision_runtime}]",
                f"dev = [{dev}]",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )
    return path


def test_projection_uses_application_and_vision_runtime_roots_but_not_dev(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path / "pyproject.toml",
        dependencies='"httpx>=0.28,<0.29", "numpy>=2.2,<3"',
        vision_runtime='"numpy==2.5.3", "torch==2.6.0"',
    )

    projection = build_runtime_requirements_projection(
        pyproject,
        platform_variant="windows-x86_64-cpu",
        python_version="3.12.10",
    )

    assert projection.schema_version == "mavi-vision-runtime-requirements-v1"
    assert projection.platform_variant == "windows-x86_64-cpu"
    assert projection.python_version == "3.12.10"
    assert projection.requirements == (
        "httpx<0.29,>=0.28",
        "numpy<3,>=2.2",
        "numpy==2.5.3",
        "torch==2.6.0",
    )
    assert all("pytest" not in item for item in projection.requirements)


def test_projection_evaluates_markers_for_target_not_build_host(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path / "pyproject.toml",
        dependencies=(
            '"winonly==1.0; sys_platform == \'win32\'", '
            '"linuxonly==1.0; sys_platform == \'linux\'"'
        ),
        vision_runtime='"shared==2.0"',
    )

    windows = build_runtime_requirements_projection(
        pyproject,
        platform_variant="windows-x86_64-cpu",
        python_version="3.12.10",
    )
    linux = build_runtime_requirements_projection(
        pyproject,
        platform_variant="linux-x86_64-cpu",
        python_version="3.12.14",
    )

    assert windows.requirements == ("shared==2.0", "winonly==1.0")
    assert linux.requirements == ("linuxonly==1.0", "shared==2.0")


def test_projection_serialization_and_hash_are_deterministic(tmp_path: Path) -> None:
    first = _write_pyproject(
        tmp_path / "first.toml",
        dependencies='"zeta==1", "alpha>=2,<3"',
        vision_runtime='"beta==4"',
    )
    second = _write_pyproject(
        tmp_path / "second.toml",
        dependencies='"alpha<3,>=2", "zeta==1"',
        vision_runtime='"beta==4"',
    )

    projection_a = build_runtime_requirements_projection(
        first,
        platform_variant="windows-x86_64-cpu",
        python_version="3.12.10",
    )
    projection_b = build_runtime_requirements_projection(
        second,
        platform_variant="windows-x86_64-cpu",
        python_version="3.12.10",
    )

    assert serialize_runtime_requirements_projection(projection_a) == serialize_runtime_requirements_projection(projection_b)
    assert runtime_requirements_sha256(projection_a) == runtime_requirements_sha256(projection_b)
    assert serialize_runtime_requirements_projection(projection_a).endswith(b"\n")
    assert b"\r" not in serialize_runtime_requirements_projection(projection_a)


def test_projection_rejects_direct_url_runtime_root(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path / "pyproject.toml",
        dependencies='"unsafe @ https://example.invalid/unsafe.whl"',
        vision_runtime='"torch==2.6.0"',
    )

    with pytest.raises(RuntimeRequirementsError, match="runtime_requirement_direct_url_forbidden"):
        build_runtime_requirements_projection(
            pyproject,
            platform_variant="windows-x86_64-cpu",
            python_version="3.12.10",
        )


def test_projection_rejects_unsupported_target_identity(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path / "pyproject.toml",
        dependencies='"httpx>=0.28,<0.29"',
        vision_runtime='"torch==2.6.0"',
    )

    with pytest.raises(RuntimeRequirementsError, match="runtime_requirement_platform_invalid"):
        build_runtime_requirements_projection(
            pyproject,
            platform_variant="darwin-arm64-cpu",
            python_version="3.12.10",
        )
