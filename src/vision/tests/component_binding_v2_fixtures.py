"""Shared builders for the component-binding v2 tests (S2a.1).

The valid baseline documents are produced by the one-shot migration generator
from the repository's real v1 artefacts, so every negative test mutates exactly
what S2a.3 will ship rather than a hand-invented shape.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from functools import lru_cache
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[3]
TOOL_PATH = REPOSITORY / "tools" / "vision" / "migrate_component_binding_v1.py"
RUNTIME_DIR = REPOSITORY / "src/vision/runtime/mmdetection-phase1-v1"

# The v1 release artefacts were deleted at the S2a.3 cut-over. Their exact bytes
# are frozen here as the generator's inputs only; nothing at runtime reads them.
V1_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "component-binding-v1"
V1_BINDING = V1_FIXTURES / "mmdetection-phase1-v1.json"
V1_MANIFEST = V1_FIXTURES / "rtmdet-m-coco-phase1-v1.manifest.json"
V1_QUALIFICATION = V1_FIXTURES / "rtmdet-m-coco-phase1-v1.qualification.json"
V1_RUNTIME_PROFILE_BYTES = V1_FIXTURES / "runtime.v1.json"
# The mmdetection LICENSE at the commit pinned by vision-model-pack.yml, extracted
# with `git show <commit>:LICENSE` (never a working-tree copy, so no line-ending
# conversion can change the identity-bearing bytes).
LICENCE_NOTICE = V1_FIXTURES / "mmdetection-44ebd17b-LICENSE"
LICENCE_BYTES = LICENCE_NOTICE.read_bytes()

# The committed v2 artefacts the cut-over published.
V2_BINDING = REPOSITORY / "src/vision/config/components/phase1-bindings-v2.json"
V2_MANIFEST = REPOSITORY / "models/manifests/rtmdet-m-coco-phase1-v2.json"
V2_RUNTIME_PROFILE = RUNTIME_DIR / "runtime.json"
V2_QUALIFICATION = REPOSITORY / "models/qualifications/rtmdet-m-coco-phase1-v2.json"

GATE_SETS = REPOSITORY / "config/acceptance/capability-gate-sets-v1.json"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "model-manifests"
MMDETECTION_REVISION = "44ebd17b145c2372c4b700bfb9cb20dbd28ab64a"


def _stage_v1_runtime_profile() -> Path:
    """The frozen v1 profile beside the tracked locks, as the generator reads it.

    The generator classifies variants and re-derives Runtime Pack ids from the lock
    and requirements files beside its input profile, so the frozen v1 profile is
    staged next to copies of the real, tracked lock files.
    """
    import atexit
    import shutil
    import tempfile

    staged = Path(tempfile.mkdtemp(prefix="mavi-v1-runtime-")) / "mmdetection-phase1-v1"
    staged.mkdir()
    atexit.register(shutil.rmtree, staged.parent, True)
    for item in RUNTIME_DIR.iterdir():
        if item.suffix == ".lock" or item.name.endswith(".requirements.txt"):
            shutil.copy2(item, staged / item.name)
    shutil.copy2(V1_RUNTIME_PROFILE_BYTES, staged / "runtime.json")
    return staged / "runtime.json"


V1_RUNTIME_PROFILE = _stage_v1_runtime_profile()


@lru_cache(maxsize=1)
def load_migration_tool():
    spec = importlib.util.spec_from_file_location("migrate_component_binding_v1", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("migration_tool_unloadable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def generate(tmp_path: Path, *, licence_bytes: bytes = LICENCE_BYTES, **paths: Path) -> dict[str, bytes]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    licence = tmp_path / "LICENSE"
    licence.write_bytes(licence_bytes)
    tool = load_migration_tool()
    return tool.build_v2_documents(
        v1_binding_path=paths.get("v1_binding", V1_BINDING),
        v1_manifest_path=paths.get("v1_manifest", V1_MANIFEST),
        v1_runtime_profile_path=paths.get("v1_runtime_profile", V1_RUNTIME_PROFILE),
        v1_qualification_path=paths.get("v1_qualification", V1_QUALIFICATION),
        gate_sets_path=paths.get("gate_sets", GATE_SETS),
        licence_notice_path=licence,
        licence_spdx_id="Apache-2.0",
        source_repository="open-mmlab/mmdetection",
        source_revision=MMDETECTION_REVISION,
        binding_id="phase1-v2",
        qualification_id="rtmdet-m-coco-phase1-v2",
    )


@lru_cache(maxsize=1)
def _baseline_cached() -> dict[str, str]:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        documents = generate(Path(directory))
    return {key: value.decode("utf-8") for key, value in documents.items()}


def baseline(name: str) -> dict:
    """A fresh, mutable copy of one generated v2 document."""
    return copy.deepcopy(json.loads(_baseline_cached()[name]))


def gate_sets():
    from mavi_vision.runtime.qualification_v2 import load_capability_gate_sets

    return load_capability_gate_sets(GATE_SETS)
