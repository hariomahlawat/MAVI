"""Task 10 split jobs: the harness must run on a subset of the candidate
environment, and its retained JUnit must be complete and honestly skipped."""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

TOOL = Path(__file__).resolve().parents[3] / "tools" / "vision" / "task10_environment.py"


def _load():
    spec = importlib.util.spec_from_file_location("task10_environment", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


env = _load()

COMMON = {
    "schema": env.SCHEMA,
    "headSha": "a" * 40,
    "runtimeVariant": "windows-x86_64-cpu",
    "python": {"version": "3.12.10", "implementation": "CPython", "build": ["tags/v3.12.10", "x"], "compiler": "MSC"},
    "platform": {"system": "Windows", "machine": "AMD64", "sysconfigPlatform": "win-amd64", "runnerImage": "win25"},
}
HARNESS = {**COMMON, "distributions": {"numpy": "2.5.3", "trackers": "2.6.0", "supervision": "0.30.2", "pytest": "9.1.1"}}
CANDIDATE = {**COMMON, "distributions": {**HARNESS["distributions"], "torch": "2.6.0+cpu", "torchvision": "0.21.0+cpu",
                                          "mmcv": "2.1.0", "mmengine": "0.10.7", "mmdet": "3.3.0"}}


def test_a_harness_on_a_subset_of_the_candidate_environment_passes() -> None:
    assert env.compare(CANDIDATE, HARNESS) == []


def test_a_harness_distribution_at_another_version_is_refused() -> None:
    harness = copy.deepcopy(HARNESS)
    harness["distributions"]["supervision"] = "0.30.3"
    assert "distribution_version_differs:supervision:0.30.3!=0.30.2" in env.compare(CANDIDATE, harness)


def test_a_distribution_only_the_harness_had_is_refused() -> None:
    harness = copy.deepcopy(HARNESS)
    harness["distributions"]["lap"] = "0.5.12"
    assert "harness_only_distribution:lap==0.5.12" in env.compare(CANDIDATE, harness)


def test_another_head_variant_python_or_platform_is_refused() -> None:
    for field, value in (("headSha", "b" * 40), ("runtimeVariant", "linux-x86_64-cpu"),
                         ("python", {**COMMON["python"], "version": "3.12.11"}),
                         ("platform", {**COMMON["platform"], "runnerImage": "win22"})):
        harness = {**copy.deepcopy(HARNESS), field: value}
        assert f"{field}_differs" in env.compare(CANDIDATE, harness), field


def test_the_runtime_graph_belongs_to_the_candidate_not_the_harness() -> None:
    harness = copy.deepcopy(HARNESS)
    harness["distributions"]["torch"] = "2.6.0+cpu"
    assert "harness_has_runtime_graph_distribution:torch" in env.compare(CANDIDATE, harness)
    candidate = copy.deepcopy(CANDIDATE)
    del candidate["distributions"]["mmcv"]
    assert "candidate_lacks_runtime_graph_distribution:mmcv" in env.compare(candidate, HARNESS)


def _junit(tmp_path: Path, body: str, name: str = "windows-x86_64-cpu") -> Path:
    path = tmp_path / "s1-qualification-harness.xml"
    path.write_text(f'<testsuites><testsuite name="{name}">{body}</testsuite></testsuites>', encoding="utf-8")
    return path


PASSED = '<testcase classname="tools.qualification.tests.test_s1_b1" name="test_ok" time="0.1"/>'


def test_a_complete_passing_harness_junit_passes(tmp_path: Path) -> None:
    approved = ('<testcase classname="tools.qualification.tests.test_s1_memory" '
                'name="test_linux_probe_reads_this_process"><skipped/></testcase>')
    assert env.check_harness(_junit(tmp_path, PASSED + approved), "windows-x86_64-cpu") == []


def test_an_unapproved_skip_fails_the_harness(tmp_path: Path) -> None:
    # For example a test that importorskips a package the harness job lacks.
    skipped = ('<testcase classname="tools.qualification.tests.test_s1_memory" '
               'name="test_a_small_native_bytetrack_run_retires_through_the_real_adapter"><skipped/></testcase>')
    problems = env.check_harness(_junit(tmp_path, PASSED + skipped), "windows-x86_64-cpu")
    assert any(p.startswith("harness_skip_not_approved:") for p in problems)
    # A skip approved only on the other variant is not approved here.
    other = ('<testcase classname="tools.qualification.tests.test_s1_memory" '
             'name="test_windows_probe_reads_commit_charge"><skipped/></testcase>')
    assert env.check_harness(_junit(tmp_path, PASSED + other), "windows-x86_64-cpu")


def test_missing_empty_mislabelled_or_failed_harness_evidence_fails(tmp_path: Path) -> None:
    assert env.check_harness(tmp_path / "absent.xml", "windows-x86_64-cpu")
    assert "junit_has_no_testcases" in env.check_harness(_junit(tmp_path, ""), "windows-x86_64-cpu")
    assert any(p.startswith("junit_suite_not_this_variant") for p in
               env.check_harness(_junit(tmp_path, PASSED, name="linux-x86_64-cpu"), "windows-x86_64-cpu"))
    failed = '<testcase classname="tools.qualification.tests.test_s1_b1" name="test_x"><failure/></testcase>'
    assert any(p.startswith("harness_test_failed") for p in env.check_harness(_junit(tmp_path, failed), "windows-x86_64-cpu"))
    (tmp_path / "s1-qualification-harness.xml").write_text("<testsuites", encoding="utf-8")
    assert any(p.startswith("junit_unreadable") for p in
               env.check_harness(tmp_path / "s1-qualification-harness.xml", "windows-x86_64-cpu"))


def test_missing_environment_records_fail_the_comparison(tmp_path: Path) -> None:
    assert env.main(["compare", "--candidate", str(tmp_path / "c.json"), "--harness", str(tmp_path / "h.json")]) == 1
