"""The Quality Gate scope classifier: which lanes a change makes applicable.

A false skip is the failure this guards against: every doubtful path runs every
lane, and the classifier's own inputs (the scope list, the workflow) run every
lane too.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "ci"))

import quality_scope as qs  # noqa: E402

SCOPE = qs.read_scope()
LANES = list(SCOPE["lanes"])
WORKFLOW = (ROOT / ".github/workflows/quality-gate.yml").read_text(encoding="utf-8")


def lanes_for(*paths: str) -> set[str]:
    verdict, _ = qs.applicable_lanes(list(paths), SCOPE)
    return {lane for lane, on in verdict.items() if on}


def test_the_scope_file_declares_the_lanes_the_workflow_gates() -> None:
    """Every lane the workflow conditions on `needs.scope.outputs.<lane>` is a
    declared lane, and every declared lane gates at least one job."""
    gated = set(re.findall(r"needs\.scope\.outputs\.([a-z0-9-]+) != 'false'", WORKFLOW))
    assert gated == set(LANES), (gated, LANES)
    for lane in LANES:
        assert f"{lane}: ${{{{ steps.scope.outputs.{lane} }}}}" in WORKFLOW, lane


def test_a_markdown_plan_only_change_skips_every_expensive_lane() -> None:
    assert lanes_for("docs/superpowers/plans/2026-10-10-stage3-5-s6-x1-accessibility-assertions.md") == set()
    assert lanes_for("docs/reviews/2026-10-07-stage3-5-ui-ux-professionalisation-acceptance.md", "README.md", "AGENTS.md") == set()
    assert lanes_for("docs/architecture/ui-ux-design-specification.md", "docs/adr/adr-017.md") == set()


def test_documents_a_lane_reads_still_run_that_lane() -> None:
    """Qualification evidence under docs/qualification and the three documents
    the vision tests read are lane inputs, not inert prose."""
    assert {"vision", "qualification", "tooling", "dotnet"} <= lanes_for("docs/qualification/stage2-s1/summary.md")
    assert "vision" in lanes_for("docs/runbooks/windows-cuda-host-session.md")
    assert "vision" in lanes_for("docs/superpowers/plans/c8-pr49-readiness.md")
    assert "web" not in lanes_for("docs/runbooks/windows-cuda-host-session.md")


def test_a_web_change_runs_web_and_visual_lanes_only() -> None:
    assert lanes_for("src/web/mavi-web/src/styles/components.css") == {"web", "visual"}
    assert lanes_for("src/web/mavi-web/src/app/AppShell.tsx", "src/web/mavi-web/package-lock.json") == {"web", "visual"}


def test_a_visual_harness_change_runs_the_visual_lane() -> None:
    assert lanes_for("tools/web-visual-qa/assertions.mjs") == {"visual"}
    assert lanes_for("tools/web-visual-qa/README.md") == {"visual"}  # lane globs outrank the Markdown inert rule


def test_a_platform_change_runs_dotnet_and_the_production_host() -> None:
    lanes = lanes_for("src/platform/Mavi.Api/Program.cs")
    assert {"dotnet", "web"} <= lanes
    assert "visual" not in lanes and "guard" not in lanes


def test_a_vision_change_runs_every_lane_that_imports_it() -> None:
    assert lanes_for("src/vision/mavi_vision/evidence/selector.py") == {"tooling", "dotnet", "vision", "guard", "qualification"}


def test_the_gate_workflow_and_the_scope_tool_run_every_lane() -> None:
    assert lanes_for(".github/workflows/quality-gate.yml") == set(LANES)
    assert lanes_for("tools/ci/quality-scope.json") == set(LANES)
    assert lanes_for("tools/ci/quality_scope.py") == set(LANES)


def test_shared_configuration_and_other_workflows_are_classified_conservatively() -> None:
    assert {"tooling", "dotnet", "vision", "qualification", "web"} <= lanes_for("config/dependencies/offline-dependency-policy-v1.json")
    assert {"vision", "qualification"} <= lanes_for(".github/workflows/task10-runtime-qualification.yml")
    assert {"tooling", "dotnet", "vision", "qualification"} <= lanes_for("contracts/schemas/vision-job-complete-v3.3.schema.json")
    assert "vision" in lanes_for("tools/verify_repo.py")


def test_inputs_a_lane_reads_outside_its_source_tree_still_run_it() -> None:
    """Found by the cold review: a web test imports a fixture under tests/, a
    vision test reads the .NET worker contract, a qualification test reads
    .gitattributes and the qualification suite reads Task 10's scope list."""
    assert "web" in lanes_for("tests/fixtures/scene-analytics/c1-operator-contract.json")
    assert "vision" in lanes_for("src/platform/Mavi.Contracts/Worker/WorkerContractRules.cs")
    assert {"qualification", "tooling", "vision"} <= lanes_for(".gitattributes")
    assert "qualification" in lanes_for("tools/vision/task10-scope-paths.txt")
    assert "qualification" in lanes_for("tools/phase1/qualify_offline_variant.py")
    assert "vision" in lanes_for(".github/CODEOWNERS")
    # .editorconfig can turn analyzer warnings into build errors: unlisted, so every lane.
    assert lanes_for(".editorconfig") == set(LANES)


def test_a_rename_runs_the_lanes_of_both_its_paths() -> None:
    assert lanes_for("src/web/mavi-web/src/old.tsx", "docs/old.md") == {"web", "visual"}
    assert lanes_for("tools/web-visual-qa/old.mjs", "src/platform/New.cs") == {"visual", "dotnet", "web", "vision"}


def test_an_unknown_path_runs_every_lane() -> None:
    assert lanes_for("infrastructure/new-thing.yml") == set(LANES)
    assert lanes_for("Setup-MAVI-Development.cmd") == set(LANES)
    assert lanes_for("docs/notes.md", "some/new/area/file.txt") == set(LANES)


def test_an_empty_change_list_runs_every_lane() -> None:
    verdict, reason = qs.applicable_lanes([], SCOPE)
    assert all(verdict.values()) and "every lane" in reason


def test_an_unparseable_scope_runs_every_lane(tmp_path: Path) -> None:
    bad = tmp_path / "quality-scope.json"
    bad.write_text(json.dumps({"lanes": {"web": ["src/web/{a,b}/**"]}}), encoding="utf-8")
    with pytest.raises(qs.ScopeError):
        qs.read_scope(bad)


def test_the_command_line_answers_every_lane_on_any_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    files = tmp_path / "changed"
    files.write_bytes(b"docs/x.md\0src/web/mavi-web/src/a.tsx\0")
    out = subprocess.run([sys.executable, str(ROOT / "tools/ci/quality_scope.py"), "lanes", "--files", str(files)], capture_output=True, text=True, check=True)
    verdict = dict(line.split("=", 1) for line in out.stdout.strip().splitlines())
    assert verdict == {lane: ("true" if lane in {"web", "visual"} else "false") for lane in LANES}
    # A missing file: every lane, exit 0, so the workflow proceeds with everything.
    out = subprocess.run([sys.executable, str(ROOT / "tools/ci/quality_scope.py"), "lanes", "--files", str(tmp_path / "absent")], capture_output=True, text=True, check=True)
    verdict = dict(line.split("=", 1) for line in out.stdout.strip().splitlines())
    assert verdict == {lane: "true" for lane in LANES}
    assert "scope undetermined" in out.stderr


def test_glob_semantics_are_never_narrower_than_github() -> None:
    assert qs.glob_regex("src/web/**").fullmatch("src/web")
    assert qs.glob_regex("src/web/**").fullmatch("src/web/a/b/c.ts")
    assert qs.glob_regex("**/*.md").fullmatch("README.md")
    assert qs.glob_regex("**/*.md").fullmatch("docs/a/b.md")
    assert not qs.glob_regex("*.md").fullmatch("docs/a.md")
    assert qs.glob_regex("tools/requirements.txt").fullmatch("tools/requirements.txt")
    assert not qs.glob_regex("tools/requirements.txt").fullmatch("tools/requirements.txt.bak")
