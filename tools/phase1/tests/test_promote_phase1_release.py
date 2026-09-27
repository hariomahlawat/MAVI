"""The S2a.3 fence on ``promote_phase1_release.py``: no v2 promotion path exists.

The v1 promotion model this tool implemented (gate evidence keyed by the v1
``requiredGates`` names, promoted v1 manifest/record bytes, re-verification
with the v1 release verifier) was retired at the Component Binding v2 cut-over
and its tests were deleted with it. What remains to prove is that every entry
point refuses with the one stable fence code, touches nothing, and leaves
RTMDet unverified/pending.
"""

from __future__ import annotations

import ast
import inspect
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from phase1_v2_support import (
    ACCEPTANCE_PROFILE,
    COMMITTED_MANIFEST,
    COMMITTED_PIPELINE,
    COMMITTED_RECORD,
    COMMITTED_RUNTIME_PROFILE,
    GATE_SETS,
    PHASE1_ROOT,
    REPOSITORY,
    committed_release_hashes,
    load_tool,
    sha256_file,
)

mod = load_tool("phase1_promotion", "promote_phase1_release.py")
FENCE = "v2_promotion_not_supported_by_this_slice"
SCRIPT = PHASE1_ROOT / "promote_phase1_release.py"


def _v1_style_arguments(*, manifest: Path, record: Path, output_dir: Path) -> list[str]:
    """Every argument the retired promotion tool took, pointed at real files."""
    return [
        "--model-root", str(REPOSITORY / "models"),
        "--manifest", str(manifest),
        "--qualification", str(record),
        "--pipeline-profile", str(COMMITTED_PIPELINE),
        "--runtime-profile", str(COMMITTED_RUNTIME_PROFILE),
        "--acceptance-profile", str(ACCEPTANCE_PROFILE),
        "--deployment-profile", "P3",
        "--source-commit", "a" * 40,
        "--expected-mavi-build", "build-a",
        "--quality-corpus-manifest", str(ACCEPTANCE_PROFILE),
        "--gate-evidence", f"cctv-quality-baseline={ACCEPTANCE_PROFILE}",
        "--output-dir", str(output_dir),
    ]


def test_the_fence_code_is_the_single_shared_code() -> None:
    assert mod.V2_PROMOTION_NOT_SUPPORTED == FENCE
    target = load_tool("phase1_target_manifest_code", "compute_target_verified_manifest.py")
    assert target.V2_PROMOTION_NOT_SUPPORTED == FENCE


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--help"],
        ["--deployment-profile", "P1"],
    ],
)
def test_the_cli_refuses_every_invocation_without_side_effects(argv: list[str], tmp_path: Path) -> None:
    before = committed_release_hashes()
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *argv],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert json.loads(completed.stdout) == {"ok": False, "code": FENCE}
    assert list(tmp_path.iterdir()) == []
    assert committed_release_hashes() == before


def test_a_full_promotion_request_is_refused_and_writes_nothing(tmp_path: Path) -> None:
    before = committed_release_hashes()
    manifest = tmp_path / "manifest.json"
    record = tmp_path / "qualification.json"
    shutil.copyfile(COMMITTED_MANIFEST, manifest)
    shutil.copyfile(COMMITTED_RECORD, record)
    copies = {manifest: sha256_file(manifest), record: sha256_file(record)}
    output_dir = tmp_path / "promoted"

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            *_v1_style_arguments(manifest=manifest, record=record, output_dir=output_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert json.loads(completed.stdout) == {"ok": False, "code": FENCE}
    assert not output_dir.exists()
    assert {path: sha256_file(path) for path in copies} == copies
    assert sorted(path.name for path in tmp_path.iterdir()) == ["manifest.json", "qualification.json"]
    assert committed_release_hashes() == before


def test_the_in_process_main_refuses(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = committed_release_hashes()
    output_dir = tmp_path / "promoted"
    code = mod.main(
        _v1_style_arguments(manifest=COMMITTED_MANIFEST, record=COMMITTED_RECORD, output_dir=output_dir)
    )
    assert code == 2
    assert json.loads(capsys.readouterr().out) == {"ok": False, "code": FENCE}
    assert not output_dir.exists()
    assert committed_release_hashes() == before


@pytest.mark.parametrize("name", ["build_promoted_metadata", "validate_promoted_outputs"])
def test_every_public_writer_function_refuses(name: str) -> None:
    before = committed_release_hashes()
    with pytest.raises(mod.PromotionError) as raised:
        getattr(mod, name)(
            manifest_raw=json.loads(COMMITTED_MANIFEST.read_text(encoding="utf-8")),
            qualification_raw=json.loads(COMMITTED_RECORD.read_text(encoding="utf-8")),
            manifest_bytes=COMMITTED_MANIFEST.read_bytes(),
            qualification_bytes=COMMITTED_RECORD.read_bytes(),
        )
    assert raised.value.code == FENCE
    assert str(raised.value) == FENCE
    assert committed_release_hashes() == before


def test_no_function_in_the_tool_escapes_the_fence() -> None:
    """Every function the module defines is a fenced entry point: no hidden writer survives."""
    defined = {
        name
        for name, value in inspect.getmembers(mod, inspect.isfunction)
        if value.__module__ == mod.__name__
    }
    assert defined == {"build_promoted_metadata", "validate_promoted_outputs", "main"}


def test_the_fenced_tools_import_no_v1_schema_and_no_release_reader() -> None:
    """Statically and at run time: the fence refuses before any reader or v1 schema loads."""
    for filename in ("promote_phase1_release.py", "compute_target_verified_manifest.py", "v2_promotion_fence.py"):
        tree = ast.parse((PHASE1_ROOT / filename).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert not any("v1_release_schemas" in name for name in imported), filename
        assert not any(name.startswith("mavi_vision") for name in imported), filename

    probe = (
        "import sys, json\n"
        f"sys.path.insert(0, {str(PHASE1_ROOT)!r})\n"
        "import promote_phase1_release as p, compute_target_verified_manifest as c\n"
        "p.main([]); c.main([])\n"
        "loaded = sorted(m for m in sys.modules if 'v1_release_schemas' in m or m.startswith('mavi_vision'))\n"
        "print(json.dumps(loaded))\n"
    )
    completed = subprocess.run([sys.executable, "-c", probe], check=True, capture_output=True, text=True)
    assert json.loads(completed.stdout.strip().splitlines()[-1]) == []


def test_rtmdet_stays_unverified_and_pending() -> None:
    from mavi_vision.runtime.model_manifest_v2 import load_model_manifest_v2
    from mavi_vision.runtime.qualification_v2 import (
        load_capability_gate_sets,
        load_qualification_record_v2,
    )

    manifest = load_model_manifest_v2(COMMITTED_MANIFEST)
    record = load_qualification_record_v2(COMMITTED_RECORD, gate_sets=load_capability_gate_sets(GATE_SETS))
    assert manifest.verification_status == "unverified"
    assert manifest.qualification_id is None
    assert record.overall_result == "pending"
    assert record.qualified_profiles == ()
    assert {variant.status for variant in record.variants.values()} == {"pending"}
    assert all(
        status == "pending" for variant in record.variants.values() for status in variant.gates.values()
    )
