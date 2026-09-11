from __future__ import annotations

import json
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
        "av": "16.1.0",
    }
    assert payload["checkpoint"]["sha256"] == (
        "229f527ca88498e8894a778a62a878a322b4a3ea2cae09ea537d34b7e907792b"
    )
    assert payload["platformVariants"]["linux-x86_64-cuda"]["status"] == (
        "pending-hardware-qualification"
    )
    assert payload["platformVariants"]["windows-x86_64-cuda"]["status"] == (
        "pending-hardware-qualification"
    )
