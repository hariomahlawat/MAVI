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
HARNESS = {**COMMON, "distributions": {"numpy": "2.5.3", "trackers": "2.6.0", "supervision": "0.30.2", "pytest": "9.1.1"},
           "closure": ["numpy", "pytest", "supervision", "trackers"]}
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
    harness["closure"].append("lap")
    assert "harness_only_distribution:lap==0.5.12" in env.compare(CANDIDATE, harness)


def test_runner_preinstalled_tools_outside_the_closure_do_not_count() -> None:
    # Measured on run 36817371563: the two Windows jobs ran on different image
    # versions, whose tool-cache Python preinstalls different pipx/platformdirs/filelock.
    harness = copy.deepcopy(HARNESS)
    harness["distributions"].update({"pipx": "1.17.6", "platformdirs": "4.11.14", "filelock": "4.0.3"})
    candidate = copy.deepcopy(CANDIDATE)
    candidate["distributions"].update({"pipx": "1.17.5", "platformdirs": "4.11.12", "filelock": "4.0.1"})
    assert env.compare(candidate, harness) == []
    # Inside the closure, the same difference is refused.
    harness["closure"].append("platformdirs")
    assert "distribution_version_differs:platformdirs:4.11.14!=4.11.12" in env.compare(candidate, harness)


def test_a_harness_record_without_a_complete_closure_is_refused() -> None:
    harness = copy.deepcopy(HARNESS)
    del harness["closure"]
    assert "harness_closure_missing" in env.compare(CANDIDATE, harness)
    harness["closure"] = []
    assert "harness_closure_missing" in env.compare(CANDIDATE, harness)
    harness["closure"] = ["numpy", "scipy"]
    assert "harness_closure_not_installed:scipy" in env.compare(CANDIDATE, harness)


def test_the_closure_follows_installed_requirements_and_their_markers(tmp_path: Path) -> None:
    roots = tmp_path / "requirements.txt"
    roots.write_text("# comment\npytest\n", encoding="utf-8")
    closure = env.dependency_closure(env._requirement_names(roots))
    assert {"pytest", "pluggy", "iniconfig", "packaging"} <= set(closure)
    # tomli/exceptiongroup are pytest requirements only below Python 3.11.
    import sys

    if sys.version_info >= (3, 11):
        assert "tomli" not in closure and "exceptiongroup" not in closure
    record = env.environment_record(roots)
    assert record["closure"] == closure
    assert set(closure) <= set(record["distributions"])
    roots.write_text("not-an-installed-distribution-xyz\n", encoding="utf-8")
    import pytest as _pytest

    with _pytest.raises(SystemExit, match="closure_root_or_dependency_not_installed"):
        env.dependency_closure(env._requirement_names(roots))


def test_the_harness_requirements_file_parses() -> None:
    names = env._requirement_names(TOOL.parent / "task10-s1-harness-requirements.txt")
    assert {"trackers", "supervision", "scipy", "opencv-python", "numpy", "av", "pytest"} <= set(names)
    assert not set(names) & env.CANDIDATE_ONLY


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


RUN_ID = "123"


def _mmcv_record(state: str = "build", **overrides):
    record = {
        "state": state, "headSha": "a" * 40, "runtimeVariant": "windows-x86_64-cpu", "runId": RUN_ID,
        "attestation": {"trust": "built-in-this-run", "runId": RUN_ID},
        "provenance": {"identitySha256": "1" * 64, "wheel": {"sha256": "2" * 64},
                       "build": {"runId": RUN_ID, "sourceSha": "a" * 40}},
    }
    if state == "reuse":
        record["attestation"] = {"trust": "default-branch", "runId": "99", "headSha": "e" * 40}
        record["provenance"]["build"] = {"runId": "99", "sourceSha": "e" * 40}
    record.update(overrides)
    return record


def _check(record):
    return env.check_mmcv(record, "windows-x86_64-cpu", "a" * 40, RUN_ID)


def test_a_built_or_attested_reused_wheel_record_passes() -> None:
    assert _check(_mmcv_record()) == []
    assert _check(_mmcv_record("reuse")) == []
    same_head = _mmcv_record("reuse")
    same_head["attestation"] = {"trust": "same-head", "runId": "99", "headSha": "a" * 40}
    assert _check(same_head) == []


def test_a_wheel_record_from_elsewhere_or_unattested_fails() -> None:
    assert "mmcv_record_head_differs" in _check(_mmcv_record(headSha="b" * 40))
    assert "mmcv_record_variant_differs" in _check(_mmcv_record(runtimeVariant="linux-x86_64-cpu"))
    assert "mmcv_record_not_this_run" in _check(_mmcv_record(runId="5"))
    assert any(p.startswith("mmcv_state_unknown") for p in _check(_mmcv_record(state="skipped")))
    built_elsewhere = _mmcv_record()
    built_elsewhere["provenance"]["build"]["runId"] = "5"
    assert "mmcv_build_not_this_run" in _check(built_elsewhere)
    other_head = _mmcv_record()
    other_head["provenance"]["build"]["sourceSha"] = "b" * 40
    assert "mmcv_build_not_this_head" in _check(other_head)
    unattested = _mmcv_record("reuse", attestation={"trust": "self-asserted", "runId": "99"})
    assert any(p.startswith("mmcv_reuse_not_attested") for p in _check(unattested))
    wrong_producer = _mmcv_record("reuse")
    wrong_producer["attestation"]["runId"] = "98"
    assert "mmcv_reuse_attestation_not_the_producer" in _check(wrong_producer)
    other_same_head = _mmcv_record("reuse")
    other_same_head["attestation"] = {"trust": "same-head", "runId": "99", "headSha": "b" * 40}
    assert "mmcv_reuse_same_head_differs" in _check(other_same_head)
    incomplete = _mmcv_record()
    incomplete["provenance"]["wheel"] = {}
    assert "mmcv_record_provenance_incomplete" in _check(incomplete)


def test_a_missing_or_unreadable_wheel_record_fails(tmp_path: Path) -> None:
    args = ["--variant", "windows-x86_64-cpu", "--head", "a" * 40, "--run-id", RUN_ID]
    assert env.main(["check-mmcv", "--record", str(tmp_path / "absent.json"), *args]) == 1
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    assert env.main(["check-mmcv", "--record", str(tmp_path / "bad.json"), *args]) == 1
    (tmp_path / "list.json").write_text("[]", encoding="utf-8")
    assert env.main(["check-mmcv", "--record", str(tmp_path / "list.json"), *args]) == 1
