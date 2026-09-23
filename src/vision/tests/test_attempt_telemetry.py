"""The per-attempt telemetry line: what it carries and what it can never do.

It carries figures only the worker process holds at completion -- detection
count across produced tracks, host peak working set, device counters and the
salted card identity. It can never raise into the runner or change an attempt's
outcome, and the raw GPU UUID can never appear in it.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from mavi_vision.common.analytical import (
    ArtifactDescriptor,
    NormalizedBoundingBox,
    ObjectClass,
    ProcessedTrack,
    RepresentativeObservation,
    VisionProcessingResult,
)
from mavi_vision.common import gpu_digest
from mavi_vision.runtime.provenance import (
    GpuIdentity,
    PlatformIdentity,
    RuntimeProvenance,
    TrackerParameters,
)
from mavi_vision.worker import attempt_telemetry as MODULE
from mavi_vision.worker.attempt_telemetry import (
    AttemptCompletion,
    JsonlAttemptTelemetryRecorder,
    compose_record,
)


TOOLS = Path(__file__).resolve().parents[3] / "tools" / "vision"
_JOB = UUID(int=7)
_RAW_UUID = "GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _artifact(key: str) -> ArtifactDescriptor:
    return ArtifactDescriptor(
        storage_key=key,
        media_type="application/octet-stream",
        size_bytes=10,
        sha256="a" * 64,
    )


def _track(track_id: str, detections: int) -> ProcessedTrack:
    return ProcessedTrack(
        track_id=track_id,
        object_class=ObjectClass.PERSON,
        start_offset_ms=0,
        end_offset_ms=1000 * detections,
        detection_count=detections,
        mean_confidence=0.8,
        max_confidence=0.9,
        representative=RepresentativeObservation(
            offset_ms=0,
            source_frame_number=1,
            confidence=0.9,
            bounding_box=NormalizedBoundingBox(0.1, 0.1, 0.2, 0.4),
            quality_score=0.8,
        ),
        thumbnail=_artifact(f"staging/job/thumbnails/{track_id}.jpg"),
        trajectory_artifact=_artifact(f"staging/job/trajectories/{track_id}.msgpack"),
    )


def _cpu_provenance() -> RuntimeProvenance:
    return RuntimeProvenance(
        model_id="rtmdet-m",
        model_version="1",
        model_manifest_sha256="1" * 64,
        checkpoint_sha256="2" * 64,
        resolved_config_sha256="3" * 64,
        pipeline_profile_id="phase1",
        pipeline_profile_version="1",
        pipeline_profile_sha256="4" * 64,
        qualification_id=None,
        qualification_sha256=None,
        verification_status="unverified",
        runtime_profile_id="runtime-v1",
        runtime_profile_sha256="5" * 64,
        runtime_variant="windows-x86_64-cpu",
        platform_lock_sha256="6" * 64,
        detector_backend="mmdetection",
        dependency_versions={"trackers": "2.6.0"},
        ffmpeg_version=None,
        platform=PlatformIdentity(
            system="Windows",
            release="11",
            version="qualified",
            machine="AMD64",
            processor="x86_64",
            python_version="3.12.10",
            python_implementation="CPython",
            python_build=("tags", "Apr 2025"),
            python_compiler="MSC",
        ),
        configured_device_policy="cpu",
        configured_device_index=0,
        device_resolution_reason="explicit_cpu",
        actual_device="cpu",
        gpu=None,
        mavi_build="development",
        mavi_commit="a" * 40,
        frame_policy="every-frame",
        tracker_parameters=TrackerParameters(
            reference_frame_rate=30,
            track_activation_threshold=0.25,
            high_confidence_threshold=0.1,
            minimum_iou_threshold=0.2,
            minimum_consecutive_frames=2,
            lost_track_buffer_seconds=1,
        ),
    )


def _cuda_provenance() -> RuntimeProvenance:
    return replace(
        _cpu_provenance(),
        runtime_variant="windows-x86_64-cuda",
        configured_device_policy="cuda",
        device_resolution_reason="cuda_selected",
        actual_device="cuda:0",
        gpu=GpuIdentity(
            name="NVIDIA GeForce GTX 1650 Ti",
            index=0,
            vram_bytes=4 * 1024**3,
            driver_version="576.83",
            cuda_runtime_version="12.4",
            uuid=_RAW_UUID,
            pci_bus_id="00000000:01:00.0",
            compute_capability="7.5",
        ),
    )


def _completion(provenance: RuntimeProvenance, *, attempt: int = 1) -> AttemptCompletion:
    return AttemptCompletion(
        job_id=_JOB,
        attempt_count=attempt,
        result=VisionProcessingResult(
            job_id=_JOB,
            frames_processed=3600,
            tracks=(_track("fixture-0001", 3), _track("fixture-0002", 5)),
        ),
        processing_duration_ms=96400,
        provenance=provenance,
    )


_CUDA_READING = {
    "device": "cuda:0",
    "maxMemoryAllocatedBytes": 1824 * 1024 * 1024,
    "maxMemoryReservedBytes": 2048 * 1024 * 1024,
    "archList": ["sm_75"],
    "runtimeVersion": "12.4",
    "mmcvNmsExecutedOnCuda": True,
    "probeError": None,
}


# Composition
def test_the_record_carries_what_only_the_worker_knows():
    record = compose_record(
        _completion(_cuda_provenance(), attempt=2),
        device_telemetry=_CUDA_READING,
        host_ram_peak_bytes=4 * 1024**3,
        recorded_at_utc="2026-09-19T15:00:00Z",
    )

    assert record["schemaVersion"] == "mavi-attempt-telemetry-v1"
    assert record["jobId"] == str(_JOB)
    assert record["attemptCount"] == 2
    assert record["framesProcessed"] == 3600
    assert record["trackCount"] == 2
    # Summed over the tracks the attempt produced; the API never carried it.
    assert record["detectionCount"] == 8
    assert record["processingDurationMs"] == 96400
    assert record["configuredDevicePolicy"] == "cuda"
    assert record["actualDevice"] == "cuda:0"
    assert record["deviceResolutionReason"] == "cuda_selected"
    assert record["verificationStatus"] == "unverified"
    assert record["runtimeVariant"] == "windows-x86_64-cuda"
    assert record["driverVersion"] == "576.83"
    assert record["hostRamPeakBytes"] == 4 * 1024**3
    assert record["cuda"] == _CUDA_READING


def test_the_raw_gpu_uuid_never_enters_the_record():
    record = compose_record(
        _completion(_cuda_provenance()),
        device_telemetry=_CUDA_READING,
        host_ram_peak_bytes=1,
        recorded_at_utc="2026-09-19T15:00:00Z",
    )

    assert _RAW_UUID not in json.dumps(record)
    assert record["gpuUuidSha256"] == gpu_digest.gpu_uuid_digest(_RAW_UUID)


def test_a_cpu_attempt_carries_no_device_fields():
    record = compose_record(
        _completion(_cpu_provenance()),
        device_telemetry=None,
        host_ram_peak_bytes=None,
        recorded_at_utc="2026-09-19T15:00:00Z",
    )

    assert record["gpuUuidSha256"] is None
    assert record["driverVersion"] is None
    assert record["cuda"] is None
    assert record["actualDevice"] == "cpu"


# The digest must be the one the host tools compute
def test_the_worker_digest_is_byte_identical_to_the_tool_digest():
    """Two definitions are unavoidable; drift between them would be invisible."""
    spec = importlib.util.spec_from_file_location(
        "host_gpu_digest", TOOLS / "host_gpu_digest.py"
    )
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)

    assert tool.GPU_UUID_HASH_DOMAIN == gpu_digest.GPU_UUID_HASH_DOMAIN
    assert tool.gpu_uuid_digest(_RAW_UUID) == gpu_digest.gpu_uuid_digest(_RAW_UUID)


# The recorder
def _recorder(tmp_path: Path, **kwargs) -> JsonlAttemptTelemetryRecorder:
    kwargs.setdefault("host_ram_peak", lambda: 123456)
    kwargs.setdefault(
        "clock", lambda: datetime(2026, 9, 19, 15, 0, tzinfo=timezone.utc)
    )
    return JsonlAttemptTelemetryRecorder(
        tmp_path / "diagnostics" / "attempt-telemetry.jsonl", **kwargs
    )


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def test_the_recorder_appends_one_durable_line_per_attempt(tmp_path, monkeypatch):
    synced: list[int] = []
    real_fsync = os.fsync

    def spy(fd: int) -> None:
        synced.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(MODULE.os, "fsync", spy)

    async def device_telemetry():
        return _CUDA_READING

    recorder = _recorder(tmp_path, device_telemetry=device_telemetry)
    _run(recorder(_completion(_cuda_provenance(), attempt=1)))
    _run(recorder(_completion(_cuda_provenance(), attempt=2)))

    lines = recorder._path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["attemptCount"] for line in lines] == [1, 2]
    assert json.loads(lines[0])["recordedAtUtc"] == "2026-09-19T15:00:00Z"
    assert json.loads(lines[0])["cuda"]["mmcvNmsExecutedOnCuda"] is True
    assert json.loads(lines[0])["hostRamPeakBytes"] == 123456
    # One fsync per line: the line must be on disk before the next attempt.
    assert len(synced) == 2


def test_a_failing_device_reading_still_records_the_attempt(tmp_path, caplog):
    async def device_telemetry():
        raise RuntimeError("cuda context gone")

    recorder = _recorder(tmp_path, device_telemetry=device_telemetry)
    with caplog.at_level(logging.WARNING, logger=MODULE.__name__):
        _run(recorder(_completion(_cuda_provenance())))

    record = json.loads(recorder._path.read_text(encoding="utf-8"))
    assert record["cuda"] is None
    assert record["framesProcessed"] == 3600
    assert any("Device telemetry" in r.message for r in caplog.records)


def test_a_failing_write_never_escapes(tmp_path, caplog):
    """The attempt already has its outcome; telemetry cannot change it."""
    blocker = tmp_path / "diagnostics"
    blocker.write_text("not a directory", encoding="utf-8")

    recorder = _recorder(tmp_path)
    with caplog.at_level(logging.WARNING, logger=MODULE.__name__):
        _run(recorder(_completion(_cpu_provenance())))

    assert any("could not be recorded" in r.message for r in caplog.records)


def test_a_symlinked_telemetry_path_is_refused(tmp_path, caplog):
    target = tmp_path / "elsewhere.jsonl"
    target.write_text("", encoding="utf-8")
    (tmp_path / "diagnostics").mkdir()
    (tmp_path / "diagnostics" / "attempt-telemetry.jsonl").symlink_to(target)

    recorder = _recorder(tmp_path)
    with caplog.at_level(logging.WARNING, logger=MODULE.__name__):
        _run(recorder(_completion(_cpu_provenance())))

    assert target.read_text(encoding="utf-8") == ""
    assert any("could not be recorded" in r.message for r in caplog.records)


def test_no_device_provider_means_no_device_block(tmp_path):
    recorder = _recorder(tmp_path)
    _run(recorder(_completion(_cpu_provenance())))

    record = json.loads(recorder._path.read_text(encoding="utf-8"))
    assert record["cuda"] is None


def test_host_peak_working_set_is_a_positive_integer_or_none():
    value = MODULE.host_peak_working_set_bytes()

    assert value is None or (isinstance(value, int) and value > 0)
