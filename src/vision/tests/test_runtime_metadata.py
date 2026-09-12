from __future__ import annotations

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
    assert payload["platformVariants"]["windows-x86_64-cuda"]["status"] == (
        "pending-hardware-qualification"
    )

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
