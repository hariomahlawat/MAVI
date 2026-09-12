from __future__ import annotations

import hashlib
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Iterator

import numpy as np
import pytest

from mavi_vision.common.analytical import ObjectClass
from mavi_vision.runtime.activity import InferenceActivity
from mavi_vision.runtime.errors import (
    GpuOutOfMemoryError,
    GpuRuntimeError,
    InferenceContractError,
    RuntimeCompatibilityError,
)
from mavi_vision.runtime.interfaces import PixelBoxXYXY, RawDetection
from mavi_vision.runtime.manifest import ArtifactRef, ModelManifest
from mavi_vision.runtime.mmdetection import (
    MMDetectionRuntime,
    _MMDetectionBindings,
)
import mavi_vision.runtime.mmdetection as mmdetection_module
from mavi_vision.runtime.profile import ByteTrackProfile, PipelineProfile
from mavi_vision.runtime.qualification import VerifiedReleaseSelection


VOCABULARY = ("person", "car", "dog")
VERSIONS = {
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
    "av": "16.1.0",
    "pillow": "11.3.0",
}


class FakeCudaOutOfMemory(RuntimeError):
    pass


class FakeTensor:
    def __init__(self, value: np.ndarray) -> None:
        self._value = value

    def detach(self) -> "FakeTensor":
        return self

    def cpu(self) -> "FakeTensor":
        return self

    def numpy(self) -> np.ndarray:
        return self._value


class FakeModel:
    def __init__(
        self,
        *,
        vocabulary: tuple[str, ...] = VOCABULARY,
        device: str = "cpu",
    ) -> None:
        self.dataset_meta = {"classes": vocabulary}
        self._device = device

    def parameters(self):
        return iter((SimpleNamespace(device=self._device),))


class FakePrediction:
    def __init__(
        self,
        *,
        boxes: np.ndarray,
        scores: np.ndarray,
        labels: np.ndarray,
    ) -> None:
        self.pred_instances = SimpleNamespace(
            bboxes=FakeTensor(boxes),
            scores=FakeTensor(scores),
            labels=FakeTensor(labels),
        )


class BackendHarness:
    def __init__(
        self,
        *,
        vocabulary: tuple[str, ...] = VOCABULARY,
        model_device: str = "cpu",
        versions: dict[str, str] | None = None,
        prediction: FakePrediction | None = None,
        inference_error: Exception | None = None,
        cuda_available: bool = True,
        cuda_count: int = 4,
    ) -> None:
        self.vocabulary = vocabulary
        self.model_device = model_device
        self.versions = dict(VERSIONS if versions is None else versions)
        self.prediction = prediction or _empty_prediction()
        self.inference_error = inference_error
        self.cuda_available = cuda_available
        self.cuda_count = cuda_count
        self.configs: list[dict[str, object]] = []
        self.init_calls: list[tuple[dict[str, object], str, str]] = []
        self.inference_images: list[np.ndarray] = []
        self.checkpoint_scope_active = False
        self.init_observed_checkpoint_scope = False
        self.empty_cache_calls = 0

    def bindings(self) -> _MMDetectionBindings:
        @contextmanager
        def checkpoint_scope() -> Iterator[None]:
            assert self.checkpoint_scope_active is False
            self.checkpoint_scope_active = True
            try:
                yield
            finally:
                self.checkpoint_scope_active = False

        def config_fromfile(path: str) -> dict[str, object]:
            assert Path(path).is_file()
            config: dict[str, object] = {
                "model": {
                    "type": "RTMDet",
                    "test_cfg": {
                        "score_thr": 0.001,
                        "nms": {"type": "nms", "iou_threshold": 0.65},
                    },
                }
            }
            self.configs.append(config)
            return config

        def init_detector(
            config: dict[str, object],
            checkpoint: str,
            device: str,
        ) -> FakeModel:
            self.init_observed_checkpoint_scope = self.checkpoint_scope_active
            self.init_calls.append((config, checkpoint, device))
            return FakeModel(
                vocabulary=self.vocabulary,
                device=self.model_device,
            )

        def inference_detector(
            model: FakeModel,
            image_bgr: np.ndarray,
        ) -> FakePrediction:
            assert isinstance(model, FakeModel)
            self.inference_images.append(image_bgr.copy())
            if self.inference_error is not None:
                raise self.inference_error
            return self.prediction

        def empty_cache() -> None:
            self.empty_cache_calls += 1

        return _MMDetectionBindings(
            config_fromfile=config_fromfile,
            init_detector=init_detector,
            inference_detector=inference_detector,
            checkpoint_scope=checkpoint_scope,
            versions=MappingProxyType(self.versions),
            cuda_oom_error_type=FakeCudaOutOfMemory,
            cuda_is_available=lambda: self.cuda_available,
            cuda_device_count=lambda: self.cuda_count,
            cuda_empty_cache=empty_cache,
        )


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _profile() -> PipelineProfile:
    return PipelineProfile(
        schema_version="1.0",
        profile_id="phase1-detection-tracking-v1",
        profile_version="1.0.0-candidate",
        model_id="rtmdet-m-coco-phase1",
        detector_inference_floor=0.05,
        allowed_source_classes=("person", "car"),
        class_mapping=MappingProxyType(
            {
                "person": ObjectClass.PERSON,
                "car": ObjectClass.VEHICLE,
            }
        ),
        tracker=ByteTrackProfile(
            track_activation_threshold=0.25,
            high_confidence_threshold=0.6,
            minimum_matching_threshold=0.8,
            minimum_consecutive_frames=1,
            lost_track_buffer_seconds=1.0,
        ),
        frame_policy="every-frame",
    )


def _selection(
    tmp_path: Path,
    *,
    config_text: str | None = None,
    checkpoint_bytes: bytes = b"checkpoint",
    versions: dict[str, str] | None = None,
) -> VerifiedReleaseSelection:
    release_dir = tmp_path / "release"
    release_dir.mkdir(parents=True, exist_ok=True)
    config_path = release_dir / "config.py"
    checkpoint_path = release_dir / "checkpoint.pth"
    config_payload = (
        config_text
        if config_text is not None
        else (
            "model = dict(type='RTMDet', "
            "test_cfg=dict(score_thr=0.001, "
            "nms=dict(type='nms', iou_threshold=0.65)))\n"
            "load_from = None\n"
            "resume_from = None\n"
        )
    ).encode("utf-8")
    config_path.write_bytes(config_payload)
    checkpoint_path.write_bytes(checkpoint_bytes)

    manifest = ModelManifest(
        schema_version="1.0",
        model_id="rtmdet-m-coco-phase1",
        model_version="1.0.0",
        purpose="phase1-person-vehicle-detection",
        backend="mmdetection",
        architecture="rtmdet-m",
        class_vocabulary=VOCABULARY,
        checkpoint=ArtifactRef(
            relative_path="release/checkpoint.pth",
            sha256=_sha(checkpoint_bytes),
        ),
        resolved_config=ArtifactRef(
            relative_path="release/config.py",
            sha256=_sha(config_payload),
        ),
        runtime_profile_id="mmdetection-phase1-v1",
        verification_status="unverified",
        qualification_id=None,
    )

    return VerifiedReleaseSelection(
        manifest=manifest,
        profile=_profile(),
        qualification=None,
        manifest_sha256="a" * 64,
        profile_sha256="b" * 64,
        qualification_sha256=None,
        runtime_profile_id=manifest.runtime_profile_id,
        runtime_profile_sha256="c" * 64,
        checkpoint_path=checkpoint_path,
        resolved_config_path=config_path,
        verification_status="unverified",
        runtime_qualification_status="partial",
        runtime_semantic_graph=MappingProxyType(
            dict(VERSIONS if versions is None else versions)
        ),
    )


def _empty_prediction() -> FakePrediction:
    return FakePrediction(
        boxes=np.empty((0, 4), dtype=np.float32),
        scores=np.empty((0,), dtype=np.float32),
        labels=np.empty((0,), dtype=np.int64),
    )


def _patch_backend(
    monkeypatch: pytest.MonkeyPatch,
    harness: BackendHarness,
) -> None:
    monkeypatch.setattr(
        mmdetection_module,
        "_load_backend_bindings",
        harness.bindings,
    )


def test_constructor_uses_verified_local_artifacts_and_profile_floor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = _selection(tmp_path)
    harness = BackendHarness()
    _patch_backend(monkeypatch, harness)

    runtime = MMDetectionRuntime(
        selection,
        device="cpu",
        activity=InferenceActivity(),
    )

    assert len(harness.init_calls) == 1
    config, checkpoint, device = harness.init_calls[0]
    assert checkpoint == str(selection.checkpoint_path.resolve())
    assert device == "cpu"
    assert harness.init_observed_checkpoint_scope is True
    assert config["model"]["test_cfg"]["score_thr"] == 0.05
    assert runtime.metadata.backend == "mmdetection"
    assert runtime.metadata.model_id == selection.manifest.model_id
    assert runtime.metadata.device == "cpu"
    assert runtime.metadata.ordered_class_vocabulary == VOCABULARY
    assert dict(runtime.metadata.versions) == VERSIONS


def test_constructor_rejects_dependency_version_drift_before_model_init(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = BackendHarness()
    harness.versions["mmdet"] = "3.4.0"
    _patch_backend(monkeypatch, harness)

    with pytest.raises(
        RuntimeCompatibilityError,
        match="runtime_dependency_version_mismatch:mmdet",
    ):
        MMDetectionRuntime(
            _selection(tmp_path),
            device="cpu",
            activity=InferenceActivity(),
        )

    assert harness.init_calls == []


def test_constructor_rejects_runtime_vocabulary_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = BackendHarness(vocabulary=("person", "dog", "car"))
    _patch_backend(monkeypatch, harness)

    with pytest.raises(RuntimeCompatibilityError, match="runtime_vocabulary_mismatch"):
        MMDetectionRuntime(
            _selection(tmp_path),
            device="cpu",
            activity=InferenceActivity(),
        )


@pytest.mark.parametrize(
    ("config_text", "error"),
    [
        (
            "_base_ = ['base.py']\nmodel = dict(test_cfg=dict(score_thr=0.1))\n",
            "resolved_config_base_unresolved",
        ),
        (
            "model = dict(test_cfg=dict(score_thr=0.1), "
            "init_cfg='https://example.invalid/checkpoint.pth')\n",
            "resolved_config_remote_reference_forbidden",
        ),
        (
            "import os\nmodel = dict(test_cfg=dict(score_thr=0.1))\n",
            "resolved_config_import_forbidden",
        ),
        (
            "model = build_model()\n",
            "resolved_config_dynamic_call_forbidden",
        ),
        (
            "model = dict(test_cfg=dict(score_thr=0.1))\n"
            "load_from = 'local-but-unreviewed.pth'\n",
            "resolved_config_external_checkpoint_forbidden",
        ),
    ],
)
def test_constructor_rejects_non_self_contained_resolved_config_before_imports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_text: str,
    error: str,
) -> None:
    selection = _selection(tmp_path, config_text=config_text)

    def fail_if_loaded() -> _MMDetectionBindings:
        raise AssertionError("heavy backend must not load before config preflight")

    monkeypatch.setattr(
        mmdetection_module,
        "_load_backend_bindings",
        fail_if_loaded,
    )

    with pytest.raises(RuntimeCompatibilityError, match=error):
        MMDetectionRuntime(
            selection,
            device="cpu",
            activity=InferenceActivity(),
        )


def test_constructor_rechecks_artifact_hash_immediately_before_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = _selection(tmp_path)
    selection.checkpoint_path.write_bytes(b"tampered")

    def fail_if_loaded() -> _MMDetectionBindings:
        raise AssertionError("heavy backend must not load after integrity failure")

    monkeypatch.setattr(
        mmdetection_module,
        "_load_backend_bindings",
        fail_if_loaded,
    )

    with pytest.raises(RuntimeCompatibilityError, match="checkpoint_hash_mismatch"):
        MMDetectionRuntime(
            selection,
            device="cpu",
            activity=InferenceActivity(),
        )


def test_infer_converts_rgb_once_filters_floor_and_returns_framework_neutral_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prediction = FakePrediction(
        boxes=np.array(
            [
                [1.5, 2.5, 11.5, 22.5],
                [3.0, 4.0, 13.0, 24.0],
                [5.0, 6.0, 15.0, 26.0],
            ],
            dtype=np.float32,
        ),
        scores=np.array([0.90, 0.049, 0.60], dtype=np.float32),
        labels=np.array([0, 1, 2], dtype=np.int64),
    )
    harness = BackendHarness(prediction=prediction)
    _patch_backend(monkeypatch, harness)
    activity = InferenceActivity()
    runtime = MMDetectionRuntime(
        _selection(tmp_path),
        device="cpu",
        activity=activity,
    )
    image_rgb = np.zeros((3, 4, 3), dtype=np.uint8)
    image_rgb[..., 0] = 11
    image_rgb[..., 1] = 22
    image_rgb[..., 2] = 33
    source_before = image_rgb.copy()

    output = runtime.infer(image_rgb)

    assert len(harness.inference_images) == 1
    assert harness.inference_images[0][0, 0].tolist() == [33, 22, 11]
    assert np.array_equal(image_rgb, source_before)
    assert len(output) == 2
    assert all(isinstance(item, RawDetection) for item in output)
    assert all(isinstance(item.bounding_box, PixelBoxXYXY) for item in output)
    assert output[0].source_class == "person"
    assert output[0].confidence == pytest.approx(0.90)
    assert (
        output[0].bounding_box.x1,
        output[0].bounding_box.y1,
        output[0].bounding_box.x2,
        output[0].bounding_box.y2,
    ) == pytest.approx((1.5, 2.5, 11.5, 22.5))
    assert output[1].source_class == "dog"
    snapshot = activity.snapshot()
    assert snapshot.active is False
    assert snapshot.completed_count == 1


def test_warmup_uses_channel_distinct_in_memory_rgb_frame(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = BackendHarness()
    _patch_backend(monkeypatch, harness)
    activity = InferenceActivity()
    runtime = MMDetectionRuntime(
        _selection(tmp_path),
        device="cpu",
        activity=activity,
    )

    runtime.warmup()

    assert len(harness.inference_images) == 1
    image_bgr = harness.inference_images[0]
    assert image_bgr.shape == (64, 96, 3)
    assert image_bgr.dtype == np.uint8
    assert image_bgr.flags.c_contiguous is True
    assert image_bgr[0, 0].tolist() == [191, 83, 17]
    assert activity.snapshot().completed_count == 1


@pytest.mark.parametrize(
    ("error", "expected_type"),
    [
        (FakeCudaOutOfMemory("CUDA OOM"), GpuOutOfMemoryError),
        (RuntimeError("CUDA out of memory while allocating"), GpuOutOfMemoryError),
        (RuntimeError("CUDA error: device-side assert triggered"), GpuRuntimeError),
        (RuntimeError("backend exploded"), InferenceContractError),
    ],
)
def test_inference_translates_backend_failures_and_clears_activity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_type: type[Exception],
) -> None:
    harness = BackendHarness(inference_error=error)
    _patch_backend(monkeypatch, harness)
    activity = InferenceActivity()
    runtime = MMDetectionRuntime(
        _selection(tmp_path),
        device="cpu",
        activity=activity,
    )

    with pytest.raises(expected_type):
        runtime.infer(np.zeros((2, 2, 3), dtype=np.uint8))

    snapshot = activity.snapshot()
    assert snapshot.active is False
    assert snapshot.completed_count == 1


@pytest.mark.parametrize(
    "prediction",
    [
        FakePrediction(
            boxes=np.array([[np.nan, 0.0, 1.0, 1.0]], dtype=np.float32),
            scores=np.array([0.8], dtype=np.float32),
            labels=np.array([0], dtype=np.int64),
        ),
        FakePrediction(
            boxes=np.array([[0.0, 0.0, 1.0]], dtype=np.float32),
            scores=np.array([0.8], dtype=np.float32),
            labels=np.array([0], dtype=np.int64),
        ),
        FakePrediction(
            boxes=np.array([[0.0, 0.0, 1.0, 1.0]], dtype=np.float32),
            scores=np.array([1.1], dtype=np.float32),
            labels=np.array([0], dtype=np.int64),
        ),
        FakePrediction(
            boxes=np.array([[0.0, 0.0, 1.0, 1.0]], dtype=np.float32),
            scores=np.array([0.8], dtype=np.float32),
            labels=np.array([99], dtype=np.int64),
        ),
        FakePrediction(
            boxes=np.array([[0.0, 0.0, 1.0, 1.0]], dtype=np.float32),
            scores=np.array([0.8], dtype=np.float32),
            labels=np.array([0.0], dtype=np.float32),
        ),
    ],
)
def test_inference_rejects_invalid_backend_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prediction: FakePrediction,
) -> None:
    harness = BackendHarness(prediction=prediction)
    _patch_backend(monkeypatch, harness)

    runtime = MMDetectionRuntime(
        _selection(tmp_path),
        device="cpu",
        activity=InferenceActivity(),
    )

    with pytest.raises(InferenceContractError):
        runtime.infer(np.zeros((2, 2, 3), dtype=np.uint8))


def test_invalid_input_frame_fails_before_activity_or_backend_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = BackendHarness()
    _patch_backend(monkeypatch, harness)
    activity = InferenceActivity()
    runtime = MMDetectionRuntime(
        _selection(tmp_path),
        device="cpu",
        activity=activity,
    )

    with pytest.raises(InferenceContractError, match="runtime_input_image_invalid"):
        runtime.infer(np.zeros((2, 2, 3), dtype=np.float32))

    assert harness.inference_images == []
    assert activity.snapshot().completed_count == 0


def test_cuda_selection_requires_available_requested_index_before_model_init(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = BackendHarness(cuda_available=False)
    _patch_backend(monkeypatch, harness)

    with pytest.raises(RuntimeCompatibilityError, match="cuda_unavailable"):
        MMDetectionRuntime(
            _selection(tmp_path),
            device="cuda:0",
            activity=InferenceActivity(),
        )
    assert harness.init_calls == []


def test_constructor_rejects_actual_model_device_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = BackendHarness(model_device="cpu")
    _patch_backend(monkeypatch, harness)

    with pytest.raises(RuntimeCompatibilityError, match="runtime_device_mismatch"):
        MMDetectionRuntime(
            _selection(tmp_path),
            device="cuda:1",
            activity=InferenceActivity(),
        )


def test_cuda_close_is_idempotent_and_releases_cache_best_effort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = BackendHarness(model_device="cuda:1")
    _patch_backend(monkeypatch, harness)
    runtime = MMDetectionRuntime(
        _selection(tmp_path),
        device="cuda:1",
        activity=InferenceActivity(),
    )

    runtime.close()
    runtime.close()

    assert harness.empty_cache_calls == 1
    with pytest.raises(GpuRuntimeError, match="mmdetection_runtime_closed"):
        runtime.infer(np.zeros((2, 2, 3), dtype=np.uint8))
