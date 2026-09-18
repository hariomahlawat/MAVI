from __future__ import annotations

import importlib.metadata
import os
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import av
import numpy as np
import pytest

if os.environ.get("MAVI_RUN_QUALIFIED_PRODUCTION_PROCESSOR_TESTS") != "1":
    pytest.skip(
        "exact production composition suite runs only in the qualified runtime job",
        allow_module_level=True,
    )


def _require_exact_distribution(name: str, expected: str) -> None:
    try:
        actual = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        pytest.fail(f"qualified runtime dependency missing: {name}", pytrace=False)
    if actual != expected:
        pytest.fail(
            f"qualified runtime dependency drift: {name}={actual}, expected={expected}",
            pytrace=False,
        )


_require_exact_distribution("trackers", "2.6.0")
_require_exact_distribution("supervision", "0.30.2")

from mavi_vision.common.lease import LeaseGuard  # noqa: E402
from mavi_vision.pipeline.production_processor import ProductionVisionProcessor  # noqa: E402
from mavi_vision.runtime.interfaces import (  # noqa: E402
    PixelBoxXYXY,
    RawDetection,
    RuntimeMetadata,
)
from mavi_vision.runtime.profile import load_pipeline_profile  # noqa: E402
from mavi_vision.storage.artifact_store import StagingArtifactStore  # noqa: E402


JOB_ID = UUID("018fa7b6-2b31-7f42-9f33-9fd9f6fdd772")
BASE = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)


class _FakeRuntime:
    def __init__(self, model_id: str, vocabulary: tuple[str, ...]) -> None:
        self._metadata = RuntimeMetadata(
            backend="qualified-composition-fixture",
            model_id=model_id,
            device="cpu",
            versions={"fixture": "1"},
            ordered_class_vocabulary=vocabulary,
        )
        self.infer_calls = 0
        self.warmup_calls = 0
        self.close_calls = 0

    @property
    def metadata(self) -> RuntimeMetadata:
        return self._metadata

    def warmup(self) -> None:
        self.warmup_calls += 1

    def infer(self, image_rgb: np.ndarray):
        self.infer_calls += 1
        height, width, _ = image_rgb.shape
        return (
            RawDetection(
                source_class="person",
                confidence=0.95,
                bounding_box=PixelBoxXYXY(
                    x1=0.20 * width,
                    y1=0.15 * height,
                    x2=0.60 * width,
                    y2=0.85 * height,
                ),
            ),
        )

    def close(self) -> None:
        self.close_calls += 1


def _write_tiny_mp4(path: Path, frame_count: int = 4) -> None:
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=10)
        stream.width = 64
        stream.height = 48
        stream.pix_fmt = "yuv420p"
        for index in range(frame_count):
            image = np.zeros((48, 64, 3), dtype=np.uint8)
            image[:, :, 0] = 30 + index
            image[:, :, 1] = 80
            image[:, :, 2] = 140
            frame = av.VideoFrame.from_ndarray(image, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def _guard() -> LeaseGuard:
    return LeaseGuard(BASE + timedelta(minutes=5), now_utc=lambda: BASE)


def _artifact_path(root: Path, storage_key: str) -> Path:
    return root.joinpath(*storage_key.split("/"))


def test_exact_packages_compose_two_isolated_attempts_around_one_runtime(
    tmp_path: Path,
) -> None:
    vision_root = Path(__file__).resolve().parents[1]
    profile = load_pipeline_profile(
        vision_root / "config" / "pipelines" / "phase1-detection-tracking-v1.json"
    )
    runtime = _FakeRuntime(profile.model_id, tuple(profile.allowed_source_classes))
    provider_calls = 0
    sink_calls = []

    def runtime_provider():
        nonlocal provider_calls
        provider_calls += 1
        return runtime

    source = tmp_path / "tiny.mp4"
    _write_tiny_mp4(source)
    payload = source.read_bytes()

    processor = ProductionVisionProcessor(
        runtime_provider=runtime_provider,
        profile=profile,
        staging_factory=lambda job_id, attempt: StagingArtifactStore(
            tmp_path,
            job_id,
            attempt,
        ),
        runtime_failure_sink=sink_calls.append,
    )

    first = processor.process(
        job_id=JOB_ID,
        attempt_count=1,
        source_path=source,
        expected_source_size_bytes=len(payload),
        expected_source_sha256=sha256(payload).hexdigest(),
        lease_guard=_guard(),
    )
    second = processor.process(
        job_id=JOB_ID,
        attempt_count=2,
        source_path=source,
        expected_source_size_bytes=len(payload),
        expected_source_sha256=sha256(payload).hexdigest(),
        lease_guard=_guard(),
    )

    assert provider_calls == 2
    assert runtime.infer_calls == 8
    assert runtime.warmup_calls == 0
    assert runtime.close_calls == 0
    assert sink_calls == []

    assert first.frames_processed == second.frames_processed == 4
    assert len(first.tracks) == len(second.tracks) == 1
    assert first.tracks[0].track_id == "person-000001"
    assert second.tracks[0].track_id == "person-000001"

    first_thumbnail = first.tracks[0].thumbnail
    first_trajectory = first.tracks[0].trajectory_artifact
    second_thumbnail = second.tracks[0].thumbnail
    second_trajectory = second.tracks[0].trajectory_artifact

    assert "/attempt-0001/" in first_thumbnail.storage_key
    assert "/attempt-0001/" in first_trajectory.storage_key
    assert "/attempt-0002/" in second_thumbnail.storage_key
    assert "/attempt-0002/" in second_trajectory.storage_key

    first_paths = {
        _artifact_path(tmp_path, first_thumbnail.storage_key),
        _artifact_path(tmp_path, first_trajectory.storage_key),
    }
    second_paths = {
        _artifact_path(tmp_path, second_thumbnail.storage_key),
        _artifact_path(tmp_path, second_trajectory.storage_key),
    }
    assert first_paths.isdisjoint(second_paths)
    assert all(path.is_file() for path in first_paths | second_paths)
