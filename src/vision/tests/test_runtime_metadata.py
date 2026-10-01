from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path


RUNTIME_PATH = (
    Path(__file__).parents[1]
    / "runtime"
    / "mmdetection-phase1-v1"
    / "runtime.json"
)


def test_runtime_candidate_records_exact_semantic_graph_and_pending_hardware() -> None:
    payload = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))

    # S2a.3: a v2 runtime family profile (P-2) carries no model identity.
    assert payload["schemaVersion"] == "2.0"
    assert payload["runtimeProfileId"] == "mmdetection-phase1-v1"
    assert payload["qualificationStatus"] == "partial"
    assert payload["pythonMinor"] == "3.12"
    assert payload["semanticGraph"] == {
        "torch": "2.6.0",
        "torchvision": "0.21.0",
        "mmcv": "2.1.0",
        "mmengine": "0.10.7",
        "mmdet": "3.3.0",
        "trackers": "2.6.0",
        "supervision": "0.30.2",
        "scipy": "1.18.1",
        "numpy": "2.5.3",
        "opencv": "5.0.0",
        "opencvPython": "5.0.0.93",
        "pillow": "11.3.0",
        "av": "16.1.0",
    }
    assert "checkpoint" not in payload and "resolvedConfig" not in payload
    for variant in ("linux-x86_64-cpu", "windows-x86_64-cpu"):
        assert payload["platformVariants"][variant]["status"] == "qualified-hosted-cpu"
        assert "resolvedConfigSha256" not in payload["platformVariants"][variant]
    # The model bytes moved to the Model Pack manifest, unchanged.
    manifest = json.loads(
        (Path(__file__).parents[3] / "models/manifests/rtmdet-m-coco-phase1-v2.json").read_text(encoding="utf-8")
    )
    digests = {item["artifactRole"]: item["sha256"] for item in manifest["artifacts"]}
    assert digests["checkpoint"] == "229f527ca88498e8894a778a62a878a322b4a3ea2cae09ea537d34b7e907792b"
    assert digests["resolved-config"] == "377d9f57abf6a73a6c308f765b70fc571715448c62998819d609d2eebc7c5ee3"

    assert payload["platformVariants"]["linux-x86_64-cpu"]["pythonIdentity"] == {
        "version": "3.12.14",
        "implementation": "CPython",
        "build": ["main", "Aug 13 2026 02:47:42"],
        "compiler": "GCC 13.3.0",
    }
    assert payload["platformVariants"]["windows-x86_64-cpu"]["pythonIdentity"] == {
        "version": "3.12.10",
        "implementation": "CPython",
        "build": ["tags/v3.12.10:0cc8128", "Apr  8 2025 12:21:36"],
        "compiler": "MSC v.1943 64 bit (AMD64)",
    }
    for variant in ("linux-x86_64-cpu", "windows-x86_64-cpu"):
        assert payload["platformVariants"][variant]["binaryVersions"] == {
            "torch": "2.6.0+cpu",
            "torchvision": "0.21.0+cpu",
        }
    assert payload["platformVariants"]["linux-x86_64-cuda"]["status"] == (
        "pending-hardware-qualification"
    )
    # Windows CUDA reached `qualified-development-hardware` at Gate C4. Linux
    # CUDA above is still pending, which is what keeps this assertion honest:
    # the two are not promoted together, and the profile stays `partial`
    # either way because Development qualification never completes it.
    cuda = payload["platformVariants"]["windows-x86_64-cuda"]
    assert cuda["status"] == "qualified-development-hardware"
    assert cuda["binaryVersions"] == {
        "torch": "2.6.0+cu124",
        "torchvision": "0.21.0+cu124",
    }
    assert "resolvedConfigSha256" not in cuda  # model identity is the Model Pack's (S2a.3)
    assert cuda["pythonIdentity"]["version"] == "3.12.10"
    assert cuda["developmentEvidence"]["sourceHeadSha"]
    assert cuda["developmentEvidence"]["evidenceBundleSha256"]


def test_pyproject_qualified_runtime_extra_matches_frozen_semantic_graph() -> None:
    runtime = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
    pyproject_path = Path(__file__).parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert pyproject["project"]["requires-python"] == ">=3.12,<3.14"

    dependencies = pyproject["project"]["optional-dependencies"]["vision-runtime"]
    pins = {}
    for dependency in dependencies:
        name, separator, version = dependency.partition("==")
        assert separator == "==", dependency
        assert name not in pins, name
        pins[name] = version

    semantic = runtime["semanticGraph"]
    assert pins == {
        "torch": semantic["torch"],
        "torchvision": semantic["torchvision"],
        "mmcv": semantic["mmcv"],
        "mmengine": semantic["mmengine"],
        "mmdet": semantic["mmdet"],
        "trackers": semantic["trackers"],
        "supervision": semantic["supervision"],
        "scipy": semantic["scipy"],
        "numpy": semantic["numpy"],
        "opencv-python": semantic["opencvPython"],
        "av": semantic["av"],
        "Pillow": semantic["pillow"],
    }


def test_runtime_qualification_binds_evidence_to_exact_checked_out_source() -> None:
    workflow_path = (
        Path(__file__).parents[3]
        / ".github"
        / "workflows"
        / "task10-runtime-qualification.yml"
    )
    workflow = workflow_path.read_text(encoding="utf-8")

    assert "MAVI_EXPECTED_SOURCE_SHA: ${{ github.event.pull_request.head.sha || github.sha }}" in workflow
    assert "MAVI_EVENT_SHA: ${{ github.sha }}" in workflow
    assert "ref: ${{ github.event.pull_request.head.sha || github.sha }}" in workflow
    assert "executed_source_sha = subprocess.check_output(" in workflow
    assert '["git", "rev-parse", "HEAD"]' in workflow
    assert '"headSha": executed_source_sha' in workflow
    assert '"eventSha": os.environ["MAVI_EVENT_SHA"]' in workflow
    assert '"prHeadSha": os.environ.get("MAVI_PR_HEAD_SHA") or None' in workflow
    assert 'if bytetrack.get("headSha") != executed_source_sha:' in workflow


def test_task10_triggers_on_and_qualifies_the_runtime_bearing_s1_surface() -> None:
    """S1.4 §10.1: every runtime-bearing vision/S1 change runs Task 10.

    Generic qualification helpers have their own Quality Gate coverage and must
    not force an MMCV/RTMDet rebuild merely by living under tools/qualification.
    """
    workflow = (
        Path(__file__).parents[3] / ".github" / "workflows" / "task10-runtime-qualification.yml"
    ).read_text(encoding="utf-8")
    pull_request, push = workflow.split("\n  push:\n", 1)
    push = push.split("\n  workflow_dispatch:", 1)[0]
    for trigger in (pull_request, push):
        assert "- 'src/vision/mavi_vision/**'" in trigger
        assert "- 'tools/qualification/**'" not in trigger
        for qualification_path in (
            "s1-qualification-evidence.schema.json",
            "s1_b1.py",
            "s1_evidence.py",
            "s1_memory.py",
            "process_memory.py",
            "tests/conftest.py",
            "tests/test_s1_*.py",
            "tests/fixtures/**",
        ):
            assert f"- 'tools/qualification/{qualification_path}'" in trigger, qualification_path
        for suite in (
            "test_worker_completion_v3.py",
            "test_completion_contract_*.py",
            "test_tracker_update.py",
            "test_track_finalization.py",
            "test_artifact_store*.py",
            "test_artifact_publisher.py",
            "test_analytical_models.py",
            "test_s1_bound_agreement.py",
        ):
            assert f"- 'src/vision/tests/{suite}'" in trigger, suite

    boundary_step = workflow.split("- name: Run production runtime boundary unit tests without ML imports", 1)[1]
    boundary_step = boundary_step.split("\n      - name:", 1)[0]
    for suite in (
        "test_evidence_encoder.py",
        "test_evidence_selector.py",
        "test_evidence_scripted_corpus.py",
        "test_worker_completion_v3.py",
        "test_completion_contract_bounds.py",
        "test_tracker_update.py",
        "test_track_finalization.py",
        "test_artifact_store.py",
        "test_artifact_store_windows.py",
        "test_artifact_publisher.py",
        "test_analytical_models.py",
        "test_s1_bound_agreement.py",
    ):
        assert f"tests/{suite}" in boundary_step, suite

    # Every JUnit file carries its matrix variant as the test-suite name, so a
    # retained XML cannot be relabelled as the other variant's evidence.
    for line in workflow.splitlines():
        if "--junitxml=" in line:
            assert "-o junit_suite_name=${{ matrix.runtime-variant }} --junitxml=" in line, line

    # The qualification harness tests run on the qualified runtime with the
    # native ByteTrack backend, where a missing backend fails instead of skipping.
    harness_step = workflow.split("- name: Run S1.4 qualification harness tests with the native ByteTrack backend", 1)[1]
    harness_step = harness_step.split("\n      - name:", 1)[0]
    assert "MAVI_RUN_QUALIFIED_BYTETRACK_TESTS: '1'" in harness_step or "MAVI_RUN_QUALIFIED_BYTETRACK_TESTS=1" in harness_step
    assert "tools/qualification/tests" in harness_step

    # Every pytest invocation in the qualified job writes JUnit XML.
    invocations = [line for line in workflow.splitlines() if "python -m pytest" in line]
    assert invocations
    for index, line in enumerate(workflow.splitlines()):
        if "python -m pytest" not in line:
            continue
        window = "\n".join(workflow.splitlines()[index:index + 40])
        command = window.split("\n      - ", 1)[0]
        assert "--junitxml=" in command, line.strip()

    assert "tools/qualification/tests" in workflow
    assert "MAVI_RUNTIME_VARIANT: ${{ matrix.runtime-variant }}" in workflow


def test_probe_tests_needing_the_ml_graph_run_after_it_is_installed() -> None:
    """S1.4 §3: a test that imports torch or mmengine must not skip in the
    pre-install tooling step, and must run in the post-install step, so the
    qualified job neither reports an unapproved skip nor leaves it unexecuted."""
    import ast
    import re

    probe_tests = Path(__file__).parent / "test_runtime_probe.py"
    tree = ast.parse(probe_tests.read_text(encoding="utf-8"))
    needs_ml = {
        f"src/vision/tests/test_runtime_probe.py::{node.name}"
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name.startswith("test")
        and any(
            isinstance(call, ast.Call)
            and ast.unparse(call.func) == "pytest.importorskip"
            and isinstance(call.args[0], ast.Constant)
            and call.args[0].value.split(".")[0] in {"torch", "mmengine", "mmcv", "mmdet"}
            for call in ast.walk(node)
        )
    }
    assert needs_ml, "the probe suite has no ML-dependent tests; the step split is obsolete"

    workflow = (
        Path(__file__).parents[3] / ".github" / "workflows" / "task10-runtime-qualification.yml"
    ).read_text(encoding="utf-8")

    def step(name: str) -> str:
        return workflow.split(f"- name: {name}", 1)[1].split("\n      - name:", 1)[0]

    tooling = step("Run runtime qualification tooling unit tests")
    real_torch = step("Test real PyTorch restricted checkpoint loading")
    selected = set(re.findall(r"(src/vision/tests/test_runtime_probe\.py::\w+)", real_torch))
    assert selected == needs_ml
    assert " -k " not in real_torch

    # What the tooling step actually collects, with its exact arguments from the
    # repository root: a --deselect that matches no node id would be a no-op.
    import subprocess
    import sys

    command = tooling.split("python -m pytest", 1)[1].split("-o junit_suite_name", 1)[0].split()
    repository = Path(__file__).parents[3]
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", *command, "--collect-only", "-o", "addopts=", "-p", "no:cacheprovider"],
        cwd=repository, capture_output=True, text=True, check=True,
    ).stdout
    collected_probe = {
        "src/vision/" + line.strip()
        for line in collected.splitlines()
        if line.strip().startswith("tests/test_runtime_probe.py::")
    }
    assert collected_probe, collected
    assert not collected_probe & needs_ml, sorted(collected_probe & needs_ml)
    assert f"({len(needs_ml)} deselected)" in collected, collected.splitlines()[-1:]


def test_task12_linux_native_bundle_is_bound_to_qualified_host_abi() -> None:
    workflow_path = (
        Path(__file__).parents[3]
        / ".github"
        / "workflows"
        / "task12-offline-bundle.yml"
    )
    workflow = workflow_path.read_text(encoding="utf-8")

    assert "os: ubuntu-24.04" in workflow
    assert 'test "$ID" = "ubuntu"' in workflow
    assert 'test "$VERSION_ID" = "24.04"' in workflow
    assert 'test "$(getconf GNU_LIBC_VERSION)" = "glibc 2.39"' in workflow
    assert 'test "$max_glibcxx" = "GLIBCXX_3.4.33"' in workflow


def test_task12_gate_is_scoped_to_runtime_pack_inputs() -> None:
    workflow_path = (
        Path(__file__).parents[3]
        / ".github"
        / "workflows"
        / "task12-offline-bundle.yml"
    )
    workflow = workflow_path.read_text(encoding="utf-8")

    assert "'src/vision/**'" not in workflow
    assert "'src/vision/mavi_vision/**'" not in workflow
    for required_trigger in (
        "'tools/vision/build_runtime_pack.py'",
        "'tools/vision/freeze_offline_lock.py'",
        "'src/vision/mavi_vision/runtime/offline_lock.py'",
        "'src/vision/mavi_vision/runtime/requirements_projection.py'",
        "'src/vision/mavi_vision/runtime/component_identity.py'",
        "'src/vision/pyproject.toml'",
        "'src/vision/runtime/mmdetection-phase1-v1/**'",
    ):
        assert required_trigger in workflow


def test_pyproject_declares_packaging_runtime_dependency() -> None:
    pyproject_path = Path(__file__).parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert "packaging>=26,<27" in pyproject["project"]["dependencies"]


def test_the_qualification_record_binds_the_runtime_profile_it_ships_with() -> None:
    """`runtimeProfileSha256` must be the digest of the tracked profile.

    Nothing in the repository *produces* this record -- `verify_repo`,
    `promote_phase1_release` and `phase1_e2e_check` all only consume it -- so
    the field is maintained by hand and had no mechanical check. Gate C4
    changed one variant's status, the profile's digest moved, and the binding
    silently went stale until `verify_repo` refused with
    `qualification_identity_mismatch` in CI.

    The whole-file binding is deliberate and is not loosened here: it is the
    tripwire that forces this record to be re-examined whenever the runtime
    profile changes, which is exactly what a variant promotion should trigger.
    What was missing was a check that says so before CI does. The fix when
    this fails is to re-derive the field from the file, never to type a digest.
    """
    record = json.loads(
        (Path(__file__).parents[3] / "models/qualifications/rtmdet-m-coco-phase1-v2.json")
        .read_text(encoding="utf-8")
    )
    expected = hashlib.sha256(RUNTIME_PATH.read_bytes()).hexdigest()

    assert record["runtimePackFamilyId"] == "mmdetection-phase1-v1"
    assert record["runtimeProfileSha256"] == expected, (
        "re-derive with: "
        "payload['runtimeProfileSha256'] = sha256(runtime.json); "
        "do not type the digest"
    )


def test_development_qualification_does_not_satisfy_a_release_gate() -> None:
    """ADR-009: Development never completes a gate Production depends on.

    The Windows CUDA variant is `qualified-development-hardware` in the
    runtime profile, and the release record still calls that gate `pending`.
    Those two facts have to coexist, and a future edit that "tidies" the gate
    to `passed` because the variant looks qualified is the exact collapse the
    qualification vocabulary exists to prevent.
    """
    record = json.loads(
        (Path(__file__).parents[3] / "models/qualifications/rtmdet-m-coco-phase1-v2.json")
        .read_text(encoding="utf-8")
    )
    profile = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))

    assert (
        profile["platformVariants"]["windows-x86_64-cuda"]["status"]
        == "qualified-development-hardware"
    )
    # v2: gates are per variant (P-12); every Windows CUDA gate stays pending.
    cuda = record["variants"]["windows-x86_64-cuda"]
    assert cuda["status"] == "pending"
    assert set(cuda["gates"].values()) == {"pending"}
    assert "windows-x86_64-cuda" not in record["evidence"]
    assert record["overallResult"] == "pending"
    assert profile["qualificationStatus"] == "partial"


_WORKFLOWS = Path(__file__).parents[3] / ".github" / "workflows"


def _trigger_paths(workflow: str, event: str) -> list[str]:
    """The ``paths:`` globs of one ``on:`` event, read line by line."""
    block = workflow.split(f"\n  {event}:\n", 1)[1]
    lines = block.split("\n    paths:\n", 1)[1].splitlines()
    globs = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if not stripped.startswith("- '"):
            break
        globs.append(stripped[3:-1])
    return globs


def _glob_matches(glob: str, path: str) -> bool:
    """GitHub path-filter semantics: ``**`` crosses ``/``; ``*`` does not."""
    import re

    pattern = "".join(
        ".*" if token == "**" else "[^/]*" if token == "*" else re.escape(token)
        for token in re.split(r"(\*\*|\*)", glob)
    )
    return re.fullmatch(pattern, path) is not None


def _triggers(workflow: str, path: str) -> bool:
    return all(
        any(_glob_matches(glob, path) for glob in _trigger_paths(workflow, event))
        for event in ("pull_request", "push")
    )


GENERIC_QUALIFICATION_CHANGES = (
    "tools/qualification/source_acquisition/acquire.py",
    "tools/qualification/model_selection/credibility.py",
    "tools/qualification/model_selection/acquire_s2c_candidates.ps1",
    "tools/qualification/attributes/corpus/canonical.py",
    "tools/qualification/tests/test_s2c_artifacts.py",
    "tools/qualification/tests/s2c_acquisition_behaviour.ps1",
    "tools/qualification/model_selection_check.py",
    "docs/qualification/model-selection/s2c-quality-statistics-contract.json",
    "docs/qualification/stage2-s2c/corpus/f1-evidence-record.json",
    "tests/fixtures/visual-attributes/fixture-pipeline-v1.json",
)
S1_RUNTIME_QUALIFICATION_CHANGES = (
    "tools/qualification/s1_evidence.py",
    "tools/qualification/s1_memory.py",
    "tools/qualification/s1_b1.py",
    "tools/qualification/process_memory.py",
    "tools/qualification/s1-qualification-evidence.schema.json",
    "tools/qualification/tests/conftest.py",
    "tools/qualification/tests/test_s1_memory.py",
    "tools/qualification/tests/fixtures/m2-quality-gate-domain-theories.trx",
)


def test_qualification_changes_split_between_windows_portability_and_task10() -> None:
    """Generic qualification tooling gets Windows portability CI without forcing
    the native Task 10 rebuild; S1/runtime-bearing qualification still runs Task 10."""
    windows = (_WORKFLOWS / "qualification-tooling-windows.yml").read_text(encoding="utf-8")
    task10 = (_WORKFLOWS / "task10-runtime-qualification.yml").read_text(encoding="utf-8")

    for path in GENERIC_QUALIFICATION_CHANGES + S1_RUNTIME_QUALIFICATION_CHANGES:
        assert _triggers(windows, path), path
    for path in GENERIC_QUALIFICATION_CHANGES:
        if not path.startswith("tools/qualification/tests/fixtures/"):
            assert not _triggers(task10, path), path
    for path in S1_RUNTIME_QUALIFICATION_CHANGES:
        assert _triggers(task10, path), path
    # A runtime-bearing vision change stays Task 10's, not this lane's.
    assert _triggers(task10, "src/vision/mavi_vision/tracking/bytetrack.py")
    assert not _triggers(windows, "src/vision/mavi_vision/tracking/bytetrack.py")
    assert _triggers(windows, ".github/workflows/qualification-tooling-windows.yml")


def test_windows_qualification_lane_is_exact_head_and_runtime_free() -> None:
    windows = (_WORKFLOWS / "qualification-tooling-windows.yml").read_text(encoding="utf-8")
    jobs = windows.split("\njobs:\n", 1)[1]

    assert "runs-on: windows-latest" in jobs
    assert "ref: ${{ env.MAVI_EXPECTED_SOURCE_SHA }}" in jobs
    assert "MAVI_EXPECTED_SOURCE_SHA: ${{ github.event.pull_request.head.sha || github.sha }}" in windows
    assert "(git rev-parse HEAD).Trim()" in jobs and "-ne $env:MAVI_EXPECTED_SOURCE_SHA" in jobs
    # The whole qualification suite, split by test, never an empty shard.
    assert "--collect-only -q -p no:cacheprovider tools/qualification/tests" in jobs
    assert 'test "$total" -gt 0' in jobs and 'test "$selected" -gt 0' in jobs
    assert "python -m pytest -q -rs -p no:cacheprovider @shard-tests.txt" in jobs
    assert "test '${{ needs.qualification-tests.result }}' = 'success'" in jobs
    # Portability only: no runtime graph, native qualification or evidence upload.
    lowered = jobs.lower()
    for forbidden in (
        "torch", "mmcv", "mmdet", "mmengine", "rtmdet", "vision-runtime",
        "probe_runtime", "mavi_run_qualified", "upload-artifact", "qualification-evidence",
    ):
        assert forbidden not in lowered, forbidden
