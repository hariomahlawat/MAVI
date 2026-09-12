from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


VERIFY_REPO_PATH = Path(__file__).parents[3] / "tools" / "verify_repo.py"


def _load_verify_repo():
    spec = importlib.util.spec_from_file_location("verify_repo_task12", VERIFY_REPO_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("verify_repo_module_unloadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "text",
    [
        '{"checkpoint":"https://example.invalid/model.pth"}',
        '{"source":"http://example.invalid"}',
        '{"source":"git+ssh://example.invalid/repo"}',
        '{"source":"ssh://example.invalid/repo"}',
        '{"source":"ftp://example.invalid/file"}',
        '{"source":"s3://bucket/key"}',
        '{"source":"hf://org/model"}',
        '{"source":"mim://mmdet/model"}',
        '{"source":"modelzoo://rtmdet"}',
        '{"source":"torchvision://weights"}',
        '{"source":"openmmlab://rtmdet"}',
    ],
)
def test_release_metadata_network_locator_detection(text: str) -> None:
    verifier = _load_verify_repo()

    assert verifier.find_release_network_hazard(text) is not None


def test_release_metadata_network_scan_avoids_unrelated_words() -> None:
    verifier = _load_verify_repo()

    assert verifier.find_release_network_hazard(
        '{"reference":"run=123;job=456;artifact=789"}'
    ) is None


def test_wheels_are_prohibited_from_git_tracking() -> None:
    verifier = _load_verify_repo()

    assert ".whl" in verifier.PROHIBITED_TRACKED_SUFFIXES


def test_tracked_runtime_lock_must_parse_canonically(tmp_path: Path) -> None:
    verifier = _load_verify_repo()
    lock = tmp_path / "runtime.lock"
    lock.write_text(
        "# schema: mavi-offline-lock-v1\n"
        "# platform-variant: linux-x86_64-cpu\n"
        "# python-version: 3.12.14\n"
        "mavi-vision==0.1.0 --hash=sha256:" + "a" * 64 + "\n",
        encoding="utf-8",
        newline="\n",
    )
    errors: list[str] = []

    verifier.check_runtime_lock_file(lock, errors)

    assert errors == []


@pytest.mark.parametrize(
    "row",
    [
        "torch @ https://example.invalid/torch.whl",
        "--index-url https://example.invalid/simple",
        "git+https://example.invalid/repo.git",
    ],
)
def test_tracked_runtime_lock_rejects_online_requirement(
    tmp_path: Path,
    row: str,
) -> None:
    verifier = _load_verify_repo()
    lock = tmp_path / "runtime.lock"
    lock.write_text(
        "# schema: mavi-offline-lock-v1\n"
        "# platform-variant: linux-x86_64-cpu\n"
        "# python-version: 3.12.14\n"
        + row
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    errors: list[str] = []

    verifier.check_runtime_lock_file(lock, errors)

    assert len(errors) == 1
    assert "Runtime release lock invalid" in errors[0]


def test_release_metadata_scan_is_scoped_by_caller_not_docs_or_workflows() -> None:
    verifier = _load_verify_repo()

    assert "docs" not in [root.name for root in verifier.RELEASE_TEXT_ROOTS]
    assert ".github" not in [root.name for root in verifier.RELEASE_TEXT_ROOTS]

def test_task12_workflow_covers_wheel_inputs_and_uses_pinned_reproduction() -> None:
    workflow = (
        Path(__file__).parents[3] / ".github" / "workflows" / "task12-offline-bundle.yml"
    ).read_text(encoding="utf-8")

    assert "'src/vision/mavi_vision/**'" in workflow
    assert "python -m pip wheel" in workflow
    assert "--no-build-isolation" in workflow
    assert "--no-deps" in workflow
    assert "./src/vision" in workflow
    assert '"mavi-vision[vision-runtime]==0.1.0"' not in workflow
    assert "Materialize reviewed locked runtime closure" in workflow
    assert "--require-hashes" in workflow
    assert "Stabilize Linux native extension environment" in workflow
    assert "-frandom-seed=mavi-task12" in workflow
    assert "Prove clean MMCV wheel reproducibility" in workflow
    assert 'test "$first_hash" = "$second_hash"' in workflow
    assert "os: ubuntu-24.04" in workflow
    assert "os: windows-2025" in workflow
    assert 'toolset: "14.44"' in workflow
    assert 'sdk: "10.0.26100.0"' in workflow
    assert "CC=gcc-14" in workflow
    assert "CXX=g++-14" in workflow
    assert "gcc-14 -dumpfullversion -dumpversion" in workflow
    assert "14.44." in workflow

