"""The Stage-3 scale-1280 resolved config is the H3 E1 intervention and nothing else.

``tools/vision/derive_detector_test_scale.py`` rewrites only the test ``Resize``
scale and ``Pad`` size of ``test_dataloader.dataset.pipeline`` and
``test_pipeline``. These tests pin that on a synthetic config of the same shape
(the base resolved config is a Model Pack artefact, not in Git), refuse every
other change, and check that the derived nodes are the E1 override recorded in
the candidate's provenance. When the installed base pack is present the real
bytes are derived too and must reproduce the tracked 1280 manifest's hash.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).parents[3]
TOOL_PATH = REPOSITORY / "tools" / "vision" / "derive_detector_test_scale.py"
CANDIDATE = REPOSITORY / "docs/qualification/stage3/dev-candidates/phase1-rtmdet-m-scale1280-a2-v1.json"
MANIFEST_1280 = REPOSITORY / "models/manifests/rtmdet-m-coco-phase1-scale1280-v2.json"
BASE_SHA256 = "377d9f57abf6a73a6c308f765b70fc571715448c62998819d609d2eebc7c5ee3"


def _load_tool():
    spec = importlib.util.spec_from_file_location("derive_detector_test_scale", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TOOL = _load_tool()

# The shape of the mmengine dump: multi-line tuples, a validation pipeline that also
# resizes to 640 (it must not move) and a training pipeline with 640 elsewhere.
BASE = b"""model = dict(
    test_cfg=dict(max_per_img=300, nms=dict(iou_threshold=0.65, type='nms'), nms_pre=30000, score_thr=0.001),
    type='RTMDet')
img_scale = (
    640,
    640,
)
test_dataloader = dict(
    batch_size=5,
    dataset=dict(
        pipeline=[
            dict(backend_args=None, type='LoadImageFromFile'),
            dict(keep_ratio=True, scale=(
                640,
                640,
            ), type='Resize'),
            dict(
                pad_val=dict(img=(
                    114,
                    114,
                    114,
                )),
                size=(
                    640,
                    640,
                ),
                type='Pad'),
            dict(type='PackDetInputs'),
        ],
        test_mode=True,
        type='CocoDataset'))
test_pipeline = [
    dict(backend_args=None, type='LoadImageFromFile'),
    dict(keep_ratio=True, scale=(
        640,
        640,
    ), type='Resize'),
    dict(pad_val=dict(img=(
        114,
        114,
        114,
    )), size=(
        640,
        640,
    ), type='Pad'),
    dict(type='PackDetInputs'),
]
val_dataloader = dict(
    dataset=dict(
        pipeline=[
            dict(keep_ratio=True, scale=(
                640,
                640,
            ), type='Resize'),
            dict(pad_val=dict(img=(
                114,
                114,
                114,
            )), size=(
                640,
                640,
            ), type='Pad'),
        ]))
"""

FROZEN_PATHS = {
    "test_dataloader.dataset.pipeline.1.scale",
    "test_dataloader.dataset.pipeline.2.size",
    "test_pipeline.1.scale",
    "test_pipeline.2.size",
}


def test_the_derivation_changes_exactly_the_four_frozen_test_nodes() -> None:
    derived = TOOL.derive(BASE, scale=1280)
    rows = TOOL.check_test_scale_derivation(BASE, derived, scale=1280)
    assert {row["path"] for row in rows} == FROZEN_PATHS
    assert all(row["from"] == [640, 640] and row["to"] == [1280, 1280] for row in rows)
    base_tree, derived_tree = TOOL.config_tree(BASE), TOOL.config_tree(derived)
    # Validation, model, test_cfg and every other name are untouched.
    for name in ("model", "img_scale", "val_dataloader"):
        assert derived_tree[name] == base_tree[name]
    # Byte-minimal: only the eight integer literals moved, every other line is identical.
    changed = [(a, b) for a, b in zip(BASE.split(b"\n"), derived.split(b"\n")) if a != b]
    assert len(changed) == 8 and all(a.strip() == b"640," and b.strip() == b"1280," for a, b in changed)


def test_the_derivation_is_deterministic() -> None:
    assert TOOL.derive(BASE, scale=1280) == TOOL.derive(BASE, scale=1280)


def test_the_derived_nodes_are_the_recorded_e1_override() -> None:
    candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    (change,) = [
        item
        for item in candidate["differences"]["fromBoundDevelopmentReferenceProfile"]
        if "Resize" in item
    ]
    assert change["targets"] == [".".join(path) for path in TOOL.TEST_PIPELINE_PATHS]
    tree = TOOL.config_tree(TOOL.derive(BASE, scale=1280))
    for path in TOOL.TEST_PIPELINE_PATHS:
        pipeline = tree
        for key in path:
            pipeline = pipeline[key]
        resize = next(step for step in pipeline if step["type"] == "Resize")
        pad = next(step for step in pipeline if step["type"] == "Pad")
        assert resize == {"type": "Resize", "scale": tuple(change["Resize"]["to"]["scale"]), "keep_ratio": change["Resize"]["to"]["keep_ratio"]}
        assert pad == {"type": "Pad", "size": tuple(change["Pad"]["to"]["size"]), "pad_val": {"img": tuple(change["Pad"]["to"]["pad_val"]["img"])}}


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (b"max_per_img=300", b"max_per_img=301"),
        (b"iou_threshold=0.65", b"iou_threshold=0.6"),
        (b"keep_ratio=True, scale=(\n                640", b"keep_ratio=True, scale=(\n                641"),
    ],
    ids=["max-per-img", "nms", "other-value"],
)
def test_any_other_change_is_refused(old: bytes, new: bytes) -> None:
    derived = TOOL.derive(BASE, scale=1280)
    assert old in derived
    with pytest.raises(TOOL.DerivationError, match="config_derivation"):
        TOOL.check_test_scale_derivation(BASE, derived.replace(old, new, 1), scale=1280)


def test_a_validation_pipeline_change_is_refused() -> None:
    derived = TOOL.derive(BASE, scale=1280)
    head, tail = derived.split(b"val_dataloader", 1)
    moved = head + b"val_dataloader" + tail.replace(b"640,", b"1280,")
    with pytest.raises(TOOL.DerivationError, match="config_derivation_not_test_scale_only"):
        TOOL.check_test_scale_derivation(BASE, moved, scale=1280)


@pytest.mark.parametrize(
    ("old", "new", "code"),
    [
        (b"keep_ratio=True, scale=(\n                640", b"keep_ratio=False, scale=(\n                640", "keep_ratio"),
        (b"                    114,\n                    114,\n                    114,", b"                    0,\n                    0,\n                    0,", "pad_val"),
        (b"test_pipeline = [", b"test_pipeline = list(\n[", "config_not_literal"),
    ],
    ids=["keep-ratio", "pad-value", "not-literal"],
)
def test_an_unexpected_base_is_refused(old: bytes, new: bytes, code: str) -> None:
    assert old in BASE
    base = BASE.replace(old, new, 1)
    if code == "config_not_literal":
        base = base.replace(b"    dict(type='PackDetInputs'),\n]\nval", b"    dict(type='PackDetInputs'),\n])\nval")
    with pytest.raises(TOOL.DerivationError, match=code):
        TOOL.derive(base, scale=1280)


def test_a_scale_that_is_not_an_upscale_is_refused() -> None:
    for scale in (640, 320, True, 1280.0):
        with pytest.raises(TOOL.DerivationError, match="scale_invalid"):
            TOOL.derive(BASE, scale=scale)  # type: ignore[arg-type]


def _installed_base() -> Path | None:
    configured = os.environ.get("MAVI_TEST_BASE_RESOLVED_CONFIG")
    candidates = [Path(configured)] if configured else [
        Path(os.environ.get("MAVI_VISION_MODEL_ROOT", r"C:\ProgramData\MAVI\Development\VisionModels")) / "rtmdet-m-coco-phase1-v1" / "rtmdet_m_resolved.py",
        Path(r"E:\MAVI-Runtime\VisionModels\rtmdet-m-coco-phase1-v1\rtmdet_m_resolved.py"),
    ]
    for path in candidates:
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == BASE_SHA256:
            return path
    return None


@pytest.mark.skipif(_installed_base() is None, reason="the installed base Model Pack (resolved config 377d9f57) is not on this host")
def test_the_installed_base_derives_the_tracked_1280_resolved_config() -> None:
    base = _installed_base().read_bytes()  # type: ignore[union-attr]
    derived = TOOL.derive(base, scale=1280)
    manifest = json.loads(MANIFEST_1280.read_text(encoding="utf-8"))
    (artifact,) = [item for item in manifest["artifacts"] if item["artifactRole"] == "resolved-config"]
    assert hashlib.sha256(derived).hexdigest() == artifact["sha256"]
    assert {row["path"] for row in TOOL.check_test_scale_derivation(base, derived, scale=1280)} == FROZEN_PATHS
