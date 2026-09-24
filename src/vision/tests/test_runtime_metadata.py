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

    assert payload["schemaVersion"] == "1.0"
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
    assert payload["checkpoint"]["sha256"] == (
        "229f527ca88498e8894a778a62a878a322b4a3ea2cae09ea537d34b7e907792b"
    )
    assert payload["resolvedConfig"] == {
        "artifact": "rtmdet_m_resolved.py",
        "sha256": "377d9f57abf6a73a6c308f765b70fc571715448c62998819d609d2eebc7c5ee3",
        "format": "python",
        "encoding": "utf-8",
        "lineEndings": "lf",
        "selfContained": True,
    }
    for variant in ("linux-x86_64-cpu", "windows-x86_64-cpu"):
        assert payload["platformVariants"][variant]["status"] == "qualified-hosted-cpu"
        assert payload["platformVariants"][variant]["resolvedConfigSha256"] == (
            payload["resolvedConfig"]["sha256"]
        )

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
    assert cuda["resolvedConfigSha256"] == payload["resolvedConfig"]["sha256"]
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


def test_task10_triggers_on_and_qualifies_the_whole_s1_surface() -> None:
    """S1.4 §10.1: every vision-package change runs Task 10, and the qualified
    CPU job runs the S1 suites that used to run only on the unqualified Quality
    Gate interpreter, with JUnit XML so pass/skip/fail counts are retained."""
    workflow = (
        Path(__file__).parents[3] / ".github" / "workflows" / "task10-runtime-qualification.yml"
    ).read_text(encoding="utf-8")
    pull_request, push = workflow.split("\n  push:\n", 1)
    push = push.split("\n  workflow_dispatch:", 1)[0]
    for trigger in (pull_request, push):
        assert "- 'src/vision/mavi_vision/**'" in trigger
        assert "- 'tools/qualification/**'" in trigger
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
        (Path(__file__).parents[3] / "models/qualifications/rtmdet-m-coco-phase1-v1.json")
        .read_text(encoding="utf-8")
    )
    expected = hashlib.sha256(RUNTIME_PATH.read_bytes()).hexdigest()

    assert record["runtimeProfileId"] == "mmdetection-phase1-v1"
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
        (Path(__file__).parents[3] / "models/qualifications/rtmdet-m-coco-phase1-v1.json")
        .read_text(encoding="utf-8")
    )
    profile = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))

    assert (
        profile["platformVariants"]["windows-x86_64-cuda"]["status"]
        == "qualified-development-hardware"
    )
    assert record["requiredGates"]["windows-x86_64-cuda"] == "pending"
    assert record["overallResult"] == "pending"
    assert profile["qualificationStatus"] == "partial"
