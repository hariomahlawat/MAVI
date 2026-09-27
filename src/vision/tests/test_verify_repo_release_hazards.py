from __future__ import annotations

import importlib.util
import re
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


def test_task12_workflow_builds_reusable_third_party_pack_reproducibly() -> None:
    workflow = (
        Path(__file__).parents[3] / ".github" / "workflows" / "task12-offline-bundle.yml"
    ).read_text(encoding="utf-8")

    # Application source must not invalidate or enter the expensive runtime pack.
    assert "'src/vision/**'" not in workflow
    assert "'src/vision/mavi_vision/**'" not in workflow
    assert "./src/vision" not in workflow
    assert "Build MAVI Vision wheel" not in workflow
    assert "task12_first_party_distribution_forbidden" in workflow
    assert "mavi-vision must not be installed in the reusable runtime pack" in workflow

    # Heavy third-party materialization remains pinned, hashed, and reproducible.
    assert "tools/vision/build_runtime_pack.py" in workflow
    assert "python -m pip wheel" in workflow
    assert "--no-build-isolation" in workflow
    assert "--no-deps" in workflow
    assert "Materialize reviewed third-party runtime closure" in workflow
    assert "--require-hashes" in workflow
    assert "Verify qualified Linux native build identity" in workflow
    assert "-frandom-seed=mavi-task12" in workflow
    assert "Prove clean MMCV wheel reproducibility" in workflow
    assert 'test "$first_hash" = "$second_hash"' in workflow
    assert "os: ubuntu-24.04" in workflow
    assert "os: windows-2025" in workflow
    assert "CC=gcc-14" in workflow
    assert "CXX=g++-14" in workflow
    assert "gcc-14 -dumpfullversion -dumpversion" in workflow
    assert "14.44." in workflow


def test_task12_windows_toolchain_is_pinned_by_compiler_build_not_toolset_directory() -> None:
    """The 14.44 toolset directory is serviced in place; only the binaries identify it.

    Hosted images moved cl/link from 19.44.35228 to 19.44.35229 under the same
    14.44.35207 directory, which changed the MMCV wheel bytes and broke the
    committed Windows CPU lock. The qualified wheel is reproduced only by the
    pinned, hash-verified, signed fixed-version Build Tools and an exact
    compiler/linker build check before anything is compiled.
    """
    workflow = (
        Path(__file__).parents[3] / ".github" / "workflows" / "task12-offline-bundle.yml"
    ).read_text(encoding="utf-8")

    # A floating image toolchain must not return.
    assert "ilammy/msvc-dev-cmd" not in workflow
    pinned = workflow.split("- name: Install pinned Windows MMCV build toolchain", 1)[1]
    pinned = pinned.split("\n      - name: ", 1)[0]
    assert "MAVI_VS_BUILDTOOLS_SHA256: aac092d0d839fd078e86b301d886130f1605891061242b36facf55ccbdd5a0a7" in pinned
    assert "/aac092d0d839fd078e86b301d886130f1605891061242b36facf55ccbdd5a0a7/vs_BuildTools.exe" in pinned
    assert "vs_buildtools_sha256_mismatch" in pinned
    assert "Get-AuthenticodeSignature" in pinned and "^CN=Microsoft Corporation," in pinned
    assert "Microsoft.VisualStudio.Component.VC.Tools.x86.x64" in pinned
    assert "Microsoft.VisualStudio.Component.Windows11SDK.26100" in pinned
    assert "x64 10.0.26100.0 -vcvars_ver=14.44" in pinned

    verify = workflow.split("- name: Verify qualified Windows native build identity", 1)[1]
    verify = verify.split("\n      - name: ", 1)[0]
    assert 'if ($clVersion -ne "19.44.35228.0")' in verify
    assert 'if ($linkVersion -ne "14.44.35228.0")' in verify
    assert "unpinned_cl_path" in verify and "unexpected_link_path" in verify
    assert '"CL=/Brepro"' in verify and '"LINK=/Brepro"' in verify
    # The exact-build check runs before the first compile.
    assert workflow.index("unexpected_msvc_compiler_build") < workflow.index("- name: Build local MMCV wheel")

    # Windows proves a clean rebuild reproduces the bytes, as Linux already does,
    # and does so in PowerShell: Git Bash rewrites CL=/Brepro into a path and
    # resolves GNU link ahead of MSVC link.exe.
    rebuild = workflow.split("- name: Prove clean MMCV wheel reproducibility on Windows", 1)[1]
    rebuild = rebuild.split("\n      - name: ", 1)[0]
    assert "if: runner.os == 'Windows'" in rebuild
    assert "shell: pwsh" in rebuild
    assert "git clean -xfd" in rebuild
    assert "task12_mmcv_windows_rebuild_not_reproducible" in rebuild

    # PowerShell reads "$name:" inside a string as a scope/drive-qualified
    # variable and refuses to parse the whole step; delimit as "${name}:".
    for block in (pinned, verify, rebuild):
        assert re.search(r"\$(?!env:)[A-Za-z_][A-Za-z0-9_]*:", block) is None


def test_offline_bundle_contract_retains_all_qualified_runtime_locks() -> None:
    contract = (
        Path(__file__).parents[3]
        / "infrastructure"
        / "offline-bundle"
        / "README.md"
    ).read_text(encoding="utf-8")

    assert "every qualified runtime lock referenced by `runtime.json`" in contract
    assert "selected platform lock is the only lock used by the offline `pip install`" in contract
    assert "hashes of **all qualified runtime locks included in the bundle**" in contract
