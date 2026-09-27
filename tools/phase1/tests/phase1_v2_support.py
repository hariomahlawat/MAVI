"""Shared support for the Phase-1 tool tests after the S2a.3 v2 cut-over."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPOSITORY = Path(__file__).resolve().parents[3]
PHASE1_ROOT = REPOSITORY / "tools" / "phase1"
VISION_ROOT = REPOSITORY / "src" / "vision"
for _candidate in (PHASE1_ROOT, VISION_ROOT):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

COMMITTED_BINDING = REPOSITORY / "src/vision/config/components/phase1-bindings-v2.json"
COMMITTED_MANIFEST = REPOSITORY / "models/manifests/rtmdet-m-coco-phase1-v2.json"
COMMITTED_RECORD = REPOSITORY / "models/qualifications/rtmdet-m-coco-phase1-v2.json"
COMMITTED_RUNTIME_PROFILE = REPOSITORY / "src/vision/runtime/mmdetection-phase1-v1/runtime.json"
COMMITTED_PIPELINE = REPOSITORY / "src/vision/config/pipelines/phase1-detection-tracking-v1.json"
GATE_SETS = REPOSITORY / "config/acceptance/capability-gate-sets-v1.json"
ACCEPTANCE_PROFILE = REPOSITORY / "config/acceptance/phase1-acceptance-v1.json"

# Every committed release file a promotion could mutate.
COMMITTED_RELEASE_FILES = (
    COMMITTED_BINDING,
    COMMITTED_MANIFEST,
    COMMITTED_RECORD,
    COMMITTED_RUNTIME_PROFILE,
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def committed_release_hashes() -> dict[str, str]:
    return {str(path): sha256_file(path) for path in COMMITTED_RELEASE_FILES}


def load_tool(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, PHASE1_ROOT / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def overlay_type():
    """The vision tests' self-consistent temporary v2 overlay (``src/vision/tests``)."""
    from tests.resolver_overlay import Overlay

    return Overlay
