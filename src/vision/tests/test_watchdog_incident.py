from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID

import pytest

from mavi_vision.runtime.progress import ProcessingProgressSnapshot
from mavi_vision.runtime.watchdog import RuntimeWatchdogSnapshot
from mavi_vision.worker.watchdog_incident import (
    WATCHDOG_FAILURE_CODE,
    WATCHDOG_OBSERVATION_FAILURE_CODE,
    JsonlWatchdogIncidentRecorder,
    WatchdogIncidentSnapshot,
)


def _incident() -> WatchdogIncidentSnapshot:
    return WatchdogIncidentSnapshot(
        worker_id="dev-worker-01",
        job_id=UUID("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761"),
        attempt_count=2,
        failure_code=WATCHDOG_FAILURE_CODE,
        progress=ProcessingProgressSnapshot(
            stage="processing",
            frames_processed=123,
            source_offset_ms=4_567,
            source_duration_ms=60_000,
            progress_percent=11.3938,
            last_progress_monotonic=500.0,
        ),
        runtime=RuntimeWatchdogSnapshot(
            observed_monotonic=630.0,
            active=True,
            started_monotonic=500.0,
            elapsed_seconds=130.0,
            completed_count=122,
            threshold_seconds=120.0,
            expired=True,
            device="cpu",
            model_id="rtmdet-m-coco",
            runtime_variant="windows-x86_64-cpu",
            pipeline_profile_id="phase1-detection-tracking-v1",
            model_manifest_sha256="a" * 64,
            checkpoint_sha256="b" * 64,
            resolved_config_sha256="c" * 64,
            pipeline_profile_sha256="d" * 64,
            runtime_profile_sha256="e" * 64,
        ),
    )


def test_incident_recorder_fsyncs_secret_safe_structured_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fsync_calls: list[int] = []
    monkeypatch.setattr(os, "fsync", lambda fd: fsync_calls.append(fd))
    target = tmp_path / "diagnostics" / "watchdog-incidents.jsonl"

    JsonlWatchdogIncidentRecorder(target).record(_incident())

    assert len(fsync_calls) == 1
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["failureCode"] == WATCHDOG_FAILURE_CODE
    assert payload["workerId"] == "dev-worker-01"
    assert payload["attemptCount"] == 2
    assert payload["progress"]["frames_processed"] == 123
    assert payload["runtime"]["expired"] is True
    assert payload["runtime"]["device"] == "cpu"

    serialized = target.read_text(encoding="utf-8")
    assert "leaseToken" not in serialized
    assert "do-not-send" not in serialized
    assert "\\secret\\" not in serialized


def test_incident_recorder_rotates_with_bounded_retention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os, "fsync", lambda fd: None)
    target = tmp_path / "watchdog-incidents.jsonl"
    recorder = JsonlWatchdogIncidentRecorder(
        target,
        max_bytes=64 * 1024,
        backup_count=2,
    )

    for _ in range(120):
        recorder.record(_incident())

    assert target.exists()
    assert target.stat().st_size <= 64 * 1024
    assert target.with_name(target.name + ".1").exists()
    assert not target.with_name(target.name + ".3").exists()


def test_incident_snapshot_rejects_non_watchdog_failure_code() -> None:
    incident = _incident()

    with pytest.raises(ValueError, match="watchdog_incident_failure_code_invalid"):
        WatchdogIncidentSnapshot(
            worker_id=incident.worker_id,
            job_id=incident.job_id,
            attempt_count=incident.attempt_count,
            failure_code="worker_unhandled_error",
            progress=incident.progress,
            runtime=incident.runtime,
        )


def test_incident_recorder_rejects_symlink_target(tmp_path: Path) -> None:
    destination = tmp_path / "elsewhere.jsonl"
    destination.write_text("keep", encoding="utf-8")
    target = tmp_path / "watchdog-incidents.jsonl"
    try:
        target.symlink_to(destination)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this host")

    with pytest.raises(OSError, match="watchdog_incident_path_symlink_forbidden"):
        JsonlWatchdogIncidentRecorder(target).record(_incident())

    assert destination.read_text(encoding="utf-8") == "keep"



def test_incident_recorder_persists_observation_failure_without_runtime_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os, "fsync", lambda fd: None)
    base = _incident()
    incident = WatchdogIncidentSnapshot(
        worker_id=base.worker_id,
        job_id=base.job_id,
        attempt_count=base.attempt_count,
        failure_code=WATCHDOG_OBSERVATION_FAILURE_CODE,
        progress=base.progress,
        runtime=None,
    )
    target = tmp_path / "watchdog-incidents.jsonl"

    JsonlWatchdogIncidentRecorder(target).record(incident)

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["failureCode"] == WATCHDOG_OBSERVATION_FAILURE_CODE
    assert payload["runtimeSnapshotAvailable"] is False
    assert payload["runtime"] is None
