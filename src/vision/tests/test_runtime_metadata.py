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


def _task10_job(name: str) -> str:
    """One job's text in the Task 10 workflow (jobs are two-space indented keys)."""
    import re

    workflow = (_WORKFLOWS / "task10-runtime-qualification.yml").read_text(encoding="utf-8")
    jobs = workflow.split("\njobs:\n", 1)[1]
    parts = re.split(r"\n(?=  [a-z0-9-]+:\n)", "\n" + jobs)
    matching = [part for part in parts if part.startswith(f"  {name}:\n")]
    assert len(matching) == 1, name
    return matching[0]


def _job_step(job: str, name: str) -> str:
    assert job.count(f"- name: {name}\n") == 1, name
    return job.split(f"- name: {name}\n", 1)[1].split("\n      - ", 1)[0]


def test_task10_reuses_only_a_verified_wheel_it_built_for_this_exact_identity() -> None:
    """The decision note: an exact identity key, no fallback restore, rebuild on an
    unverifiable entry, fail on an integrity violation, verify again at install."""
    candidate = _task10_job("cpu-candidate")
    command = candidate.split("MMCV_BUILD_COMMAND: ", 1)[1].split("\n", 1)[0]
    commit = candidate.split("MMCV_SOURCE_COMMIT: ", 1)[1].split("\n", 1)[0]
    assert commit == "57c4e25e06e2d4f8a9357c84bcd24089a284dc88"

    identity = _job_step(candidate, "Compute MMCV build identity")
    assert 'identity --mmcv-commit "$MMCV_SOURCE_COMMIT" --recipe "$MMCV_BUILD_COMMAND|MMCV_WITH_OPS=$MMCV_WITH_OPS"' in identity
    assert 'echo "key=task10-mmcv-wheel-v1-${MAVI_RUNTIME_VARIANT}-${digest}"' in identity

    restore = _job_step(candidate, "Restore Task 10 MMCV wheel")
    assert "uses: actions/cache/restore@v4" in restore
    assert "key: ${{ steps.mmcv-identity.outputs.key }}" in restore
    assert not [line for line in candidate.splitlines() if "restore-keys" in line and not line.strip().startswith("#")]
    assert candidate.count("uses: actions/cache") == 2

    verify = _job_step(candidate, "Verify restored MMCV wheel")
    assert 'if [ "$CACHE_HIT" != "true" ]; then' in verify
    assert '0) echo "state=reuse" >> "$GITHUB_OUTPUT" ;;' in verify
    assert '3) rm -rf .mmcv-wheel .mmcv-attestation.json; echo "state=build" >> "$GITHUB_OUTPUT" ;;' in verify
    assert '*) exit "$code" ;;' in verify

    build_only = "if: steps.mmcv-verify.outputs.state == 'build'"
    for name in (
        "Checkout immutable MMCV 2.1.0 source",
        "Build MMCV 2.1.0 wheel against installed PyTorch",
        "Record MMCV wheel provenance",
        "Save Task 10 MMCV wheel",
    ):
        assert build_only in _job_step(candidate, name), name
    source = _job_step(candidate, "Checkout immutable MMCV 2.1.0 source")
    assert 'test "$(git -C .qualification-mmcv rev-parse HEAD)" = "$MMCV_SOURCE_COMMIT"' in source
    # What is built is exactly the recipe that enters the identity.
    build = _job_step(candidate, "Build MMCV 2.1.0 wheel against installed PyTorch")
    assert build.split("run: ", 1)[1].strip() == command
    save = _job_step(candidate, "Save Task 10 MMCV wheel")
    assert "uses: actions/cache/save@v4" in save and "key: ${{ steps.mmcv-identity.outputs.key }}" in save

    install = _job_step(candidate, "Install verified MMCV 2.1.0 wheel")
    assert "set -euo pipefail" in install
    verify_at = install.index("mmcv_wheel_cache.py verify --dir .mmcv-wheel --identity .mmcv-identity.json")
    assert verify_at < install.index("python -m pip install .mmcv-wheel/*.whl")
    assert "qualification-evidence/mmcv-wheel.json" in install
    # No other step installs MMCV.
    assert candidate.count("pip install .mmcv-wheel/") == 1
    assert "pip install --no-build-isolation" not in candidate

    order = [candidate.index(f"- name: {name}\n") for name in (
        "Compute MMCV build identity", "Restore Task 10 MMCV wheel", "Verify restored MMCV wheel",
        "Checkout immutable MMCV 2.1.0 source", "Build MMCV 2.1.0 wheel against installed PyTorch",
        "Record MMCV wheel provenance", "Save Task 10 MMCV wheel", "Install verified MMCV 2.1.0 wheel",
        "Install remaining candidate graph",
    )]
    assert order == sorted(order)
    evidence = _job_step(candidate, "Verify qualification evidence set")
    assert '"mmcv-wheel.json",' in evidence and '"candidate-environment.json",' in evidence


def _pins(install_step: str) -> set[str]:
    return {
        token.strip('"')
        for token in install_step.split("run: >-", 1)[1].split()
        if token not in {"python", "-m", "pip", "install", "--upgrade"}
    }


def test_the_s1_harness_runs_concurrently_on_a_pinned_subset_of_the_candidate_graph() -> None:
    harness = _task10_job("s1-harness")
    candidate = _task10_job("cpu-candidate")
    harness_step_name = "Run S1.4 qualification harness tests with the native ByteTrack backend"

    # The harness runs only in its own job, which needs nothing and so starts at once.
    assert f"- name: {harness_step_name}\n" not in candidate
    assert "needs:" not in harness
    step = _job_step(harness, harness_step_name)
    assert "MAVI_RUN_QUALIFIED_BYTETRACK_TESTS=1" in step
    assert "tools/qualification/tests/test_s1_*.py" in step
    assert "--junitxml=qualification-evidence/junit/s1-qualification-harness.xml" in step

    # The same matrix variants on the same head.
    matrix = candidate.split("matrix:\n", 1)[1].split("    runs-on:", 1)[0]
    assert matrix == harness.split("matrix:\n", 1)[1].split("    runs-on:", 1)[0]
    assert "ref: ${{ github.event.pull_request.head.sha || github.sha }}" in harness
    assert 'test "$(git rev-parse HEAD)" = "$MAVI_EXPECTED_SOURCE_SHA"' in harness
    assert "MAVI_RUNTIME_VARIANT: ${{ matrix.runtime-variant }}" in harness

    # Every harness pin is a candidate pin; the runtime graph proper is absent.
    installs = [
        _job_step(candidate, "Install compatible build tooling"),
        _job_step(candidate, "Install remaining candidate graph"),
    ]
    candidate_pins = set().union(*(_pins(step) for step in installs))
    requirements = Path(__file__).parents[3] / "tools" / "vision" / "task10-s1-harness-requirements.txt"
    harness_pins = {
        line.split("#", 1)[0].strip()
        for line in requirements.read_text(encoding="utf-8").splitlines()
        if line.split("#", 1)[0].strip()
    }
    assert harness_pins and harness_pins <= candidate_pins | {"pip"}, sorted(harness_pins - candidate_pins)
    install = _job_step(harness, "Install S1 harness subset of the candidate graph")
    assert install.split("run: ", 1)[1].strip() == "python -m pip install --upgrade -r tools/vision/task10-s1-harness-requirements.txt"
    for forbidden in ("torch", "mmcv", "mmengine", "mmdet"):
        assert forbidden not in harness.lower(), forbidden
        assert forbidden not in requirements.read_text(encoding="utf-8").lower(), forbidden

    # Harness evidence is checked in the job and always retained.
    check = _job_step(harness, "Check retained harness evidence and skips")
    assert "task10_environment.py check-harness --junit qualification-evidence/junit/s1-qualification-harness.xml" in check
    record = _job_step(harness, "Record harness environment")
    assert "if: always()" in record and "s1-harness-environment.json" in record
    assert "--closure-roots tools/vision/task10-s1-harness-requirements.txt" in record
    upload = harness.split("uses: actions/upload-artifact@v4", 1)[1]
    assert "if: always()" in harness.split("uses: actions/upload-artifact@v4", 1)[1][:40]
    assert "name: s1-harness-${{ matrix.os }}-py3.12" in upload
    assert "if-no-files-found: error" in upload


def test_task10_passes_only_when_every_split_job_and_its_evidence_does() -> None:
    gate = _task10_job("task10-qualification")
    workflow = (_WORKFLOWS / "task10-runtime-qualification.yml").read_text(encoding="utf-8")

    assert "    if: always()\n" in gate
    assert "      - cpu-candidate\n" in gate and "      - s1-harness\n" in gate
    require = _job_step(gate, "Require every Task 10 job")
    for job in ("cpu-candidate", "s1-harness"):
        assert f"test '${{{{ needs.{job}.result }}}}' = 'success'" in require, job
    assert 'test "$(git rev-parse HEAD)" = "$MAVI_EXPECTED_SOURCE_SHA"' in gate
    evidence = _job_step(gate, "Require harness evidence bound to each candidate environment")
    assert "set -euo pipefail" in evidence
    assert "ubuntu-latest:linux-x86_64-cpu windows-latest:windows-x86_64-cpu" in evidence
    assert 'check-harness --junit "$harness/junit/s1-qualification-harness.xml" --variant "$variant"' in evidence
    assert 'compare --candidate "$candidate/candidate-environment.json" --harness "$harness/s1-harness-environment.json"' in evidence
    import re

    candidate_steps = set(re.findall(r"--junitxml=(?:\.\./\.\./)?qualification-evidence/junit/([a-z0-9-]+)\.xml", _task10_job("cpu-candidate")))
    listed = set(evidence.split("for step in ", 1)[1].split(";", 1)[0].split())
    assert listed == candidate_steps
    assert candidate_steps | {"s1-qualification-harness"} == set(_s1_task10_steps())

    # Never a green aggregate over a red job.
    assert "continue-on-error" not in workflow


def _s1_task10_steps() -> tuple[str, ...]:
    import sys

    sys.path.insert(0, str(Path(__file__).parents[3] / "tools" / "qualification"))
    import s1_evidence

    return s1_evidence.TASK10_JUNIT_STEPS


def test_the_split_job_tools_trigger_task10() -> None:
    task10 = (_WORKFLOWS / "task10-runtime-qualification.yml").read_text(encoding="utf-8")
    for path in ("tools/vision/mmcv_wheel_cache.py", "tools/vision/task10_environment.py",
                 "tools/vision/compare_wheel_reproducibility.py", "tools/vision/task10-s1-harness-requirements.txt"):
        assert _triggers(task10, path), path


def _git_bash() -> str:
    """The bash GitHub's ``shell: bash`` uses: Git's on Windows, never WSL's."""
    import os
    import shutil

    if os.name == "nt":
        git = shutil.which("git")
        assert git, "git is required"
        for candidate in (Path(git).parents[1] / "bin" / "bash.exe", Path(git).parents[1] / "usr" / "bin" / "bash.exe"):
            if candidate.is_file():
                return str(candidate)
    bash = shutil.which("bash")
    assert bash, "bash is required"
    return bash


def test_the_verify_step_rebuilds_unverifiable_entries_under_github_s_bash_flags(tmp_path: Path) -> None:
    """GitHub runs ``shell: bash`` as ``bash --noprofile --norc -eo pipefail``; the
    step must still reach its exit-code dispatch rather than exit on the code."""
    import subprocess

    step = _job_step(_task10_job("cpu-candidate"), "Verify restored MMCV wheel")
    body = "\n".join(line[10:] for line in step.split("        run: |\n", 1)[1].splitlines())
    import re

    # Replace only the verifier invocation; keep whatever surrounds it.
    body, replaced = re.subn(r"python tools/vision/mmcv_wheel_cache\.py verify[^|\n]*?(?= \|\||\n)",
                             '( exit "$FAKE_VERIFY_CODE" )', body)
    assert replaced == 1

    def run(code: int, hit: str = "true") -> tuple[int, str]:
        output = tmp_path / f"out-{code}-{hit}"
        output.write_text("", encoding="utf-8")
        completed = subprocess.run(
            [_git_bash(), "--noprofile", "--norc", "-eo", "pipefail", "-s"],
            input=body, text=True, cwd=tmp_path, capture_output=True,
            env={**__import__("os").environ, "FAKE_VERIFY_CODE": str(code), "CACHE_HIT": hit,
                 "GITHUB_OUTPUT": output.as_posix(), "MMCV_PRODUCER_ARTIFACT": "a"},
        )
        return completed.returncode, output.read_text(encoding="utf-8").strip()

    (tmp_path / ".mmcv-wheel").mkdir()
    assert run(0) == (0, "state=reuse")
    assert run(3) == (0, "state=build")
    assert not (tmp_path / ".mmcv-wheel").exists()
    assert run(2) == (2, "")
    assert run(1) == (1, "")
    assert run(0, hit="false") == (0, "state=build")


def test_pull_request_runs_never_save_and_reuse_is_attested() -> None:
    candidate = _task10_job("cpu-candidate")
    save = _job_step(candidate, "Save Task 10 MMCV wheel")
    assert "if: steps.mmcv-verify.outputs.state == 'build' && github.event_name != 'pull_request'" in save
    verify = _job_step(candidate, "Verify restored MMCV wheel")
    assert "--attest --artifact-name \"$MMCV_PRODUCER_ARTIFACT\" --attestation-out .mmcv-attestation.json" in verify
    assert "MMCV_PRODUCER_ARTIFACT: runtime-probe-${{ matrix.os }}-py3.12-torch2.6.0" in verify
    assert "name: runtime-probe-${{ matrix.os }}-py3.12-torch2.6.0" in candidate
    assert "MAVI_DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}" in verify
    assert "      actions: read\n" in candidate.split("    steps:", 1)[0]
    gate = _job_step(_task10_job("task10-qualification"), "Require harness evidence bound to each candidate environment")
    assert ('check-mmcv --record "$candidate/mmcv-wheel.json" --variant "$variant" '
            '--head "$MAVI_EXPECTED_SOURCE_SHA" --run-id "$GITHUB_RUN_ID"') in gate
