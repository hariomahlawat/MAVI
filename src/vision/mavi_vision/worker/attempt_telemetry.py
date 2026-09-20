"""One durable line per completed attempt, carrying what only the worker knows.

The C6 run record asks for figures that exist nowhere but inside the worker
process at the moment an attempt completes: the detection count across the
tracks it produced, the process's peak working set, the device's peak memory
and native-operator attestation, and the salted identity of the card the
provenance names. The API attestation corroborates several of these; it cannot
produce them. So the worker writes them down, one JSON line per completion,
in the same place and the same durable way the watchdog writes incidents.

This sits after `complete()` has succeeded and is best-effort: a failure to
record telemetry is logged and otherwise invisible to the attempt, which has
already reached its authoritative outcome. Nothing here may raise into the
runner, and nothing here is read by the worker itself.
"""

from __future__ import annotations

import json
import logging
import os
import platform
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from uuid import UUID

from mavi_vision.common.analytical import VisionProcessingResult
from mavi_vision.common.gpu_digest import gpu_uuid_digest
from mavi_vision.runtime.provenance import RuntimeProvenance


_LOGGER = logging.getLogger(__name__)

SCHEMA_VERSION = "mavi-attempt-telemetry-v1"
_MAX_RECORD_BYTES = 64 * 1024

DeviceTelemetryProvider = Callable[[], Awaitable[Mapping[str, object] | None]]


@dataclass(frozen=True, slots=True)
class AttemptCompletion:
    """Everything the runner holds when one attempt has been accepted."""

    job_id: UUID
    attempt_count: int
    result: VisionProcessingResult
    processing_duration_ms: int
    provenance: RuntimeProvenance


class AttemptTelemetrySink(Protocol):
    async def __call__(self, completion: AttemptCompletion) -> None: ...


def host_peak_working_set_bytes() -> int | None:
    """This process's peak resident memory, or None where it cannot be read."""
    try:
        if platform.system().casefold() == "windows":
            import ctypes
            from ctypes import wintypes

            class _Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = _Counters()
            counters.cb = ctypes.sizeof(_Counters)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.GetCurrentProcess()
            if not psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb
            ):
                return None
            return int(counters.PeakWorkingSetSize)

        import resource

        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # Linux reports kibibytes; macOS reports bytes. Only Linux is a MAVI
        # platform, and the value is diagnostic either way.
        return peak * 1024 if platform.system().casefold() == "linux" else peak
    except Exception:
        return None


def compose_record(
    completion: AttemptCompletion,
    *,
    device_telemetry: Mapping[str, object] | None,
    host_ram_peak_bytes: int | None,
    recorded_at_utc: str,
) -> dict[str, object]:
    """Assemble the line from values already in hand; no I/O, so it is testable."""
    provenance = completion.provenance
    gpu = provenance.gpu
    tracks = completion.result.tracks
    return {
        "schemaVersion": SCHEMA_VERSION,
        "recordedAtUtc": recorded_at_utc,
        "jobId": str(completion.job_id),
        "attemptCount": completion.attempt_count,
        "framesProcessed": completion.result.frames_processed,
        "trackCount": len(tracks),
        "detectionCount": sum(track.detection_count for track in tracks),
        "processingDurationMs": completion.processing_duration_ms,
        "configuredDevicePolicy": provenance.configured_device_policy,
        "actualDevice": provenance.actual_device,
        "deviceResolutionReason": provenance.device_resolution_reason,
        "verificationStatus": provenance.verification_status,
        "runtimeVariant": provenance.runtime_variant,
        # The raw UUID never enters the record; the digest is what the C4
        # corroboration and the C6 assembler compare against.
        "gpuUuidSha256": None if gpu is None else gpu_uuid_digest(gpu.uuid),
        "driverVersion": None if gpu is None else gpu.driver_version,
        "hostRamPeakBytes": host_ram_peak_bytes,
        "cuda": None if device_telemetry is None else dict(device_telemetry),
    }


class JsonlAttemptTelemetryRecorder:
    """Append one telemetry line per accepted attempt, durably, best-effort."""

    def __init__(
        self,
        path: Path,
        *,
        device_telemetry: DeviceTelemetryProvider | None = None,
        host_ram_peak: Callable[[], int | None] = host_peak_working_set_bytes,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._path = path
        self._device_telemetry = device_telemetry
        self._host_ram_peak = host_ram_peak
        self._clock = clock

    async def __call__(self, completion: AttemptCompletion) -> None:
        try:
            telemetry = (
                None
                if self._device_telemetry is None
                else await self._device_telemetry()
            )
        except Exception:
            _LOGGER.warning(
                "Device telemetry could not be read for job %s attempt %s",
                completion.job_id,
                completion.attempt_count,
            )
            telemetry = None

        try:
            record = compose_record(
                completion,
                device_telemetry=telemetry,
                host_ram_peak_bytes=self._host_ram_peak(),
                recorded_at_utc=self._clock()
                .isoformat()
                .replace("+00:00", "Z"),
            )
            self._append(record)
        except Exception:
            # The attempt already has its authoritative outcome. Telemetry
            # failing to land must not be able to change that, and the record
            # may contain paths, so the exception is not rendered.
            _LOGGER.warning(
                "Attempt telemetry could not be recorded for job %s attempt %s",
                completion.job_id,
                completion.attempt_count,
            )

    def _append(self, record: dict[str, object]) -> None:
        encoded = (
            json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            + "\n"
        ).encode("utf-8")
        if len(encoded) > _MAX_RECORD_BYTES:
            raise ValueError("attempt_telemetry_record_too_large")

        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists() and self._path.is_symlink():
            raise OSError("attempt_telemetry_path_symlink_forbidden")

        descriptor = os.open(
            self._path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600
        )
        try:
            with os.fdopen(descriptor, "ab", closefd=False) as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(descriptor)


__all__ = [
    "SCHEMA_VERSION",
    "AttemptCompletion",
    "AttemptTelemetrySink",
    "DeviceTelemetryProvider",
    "JsonlAttemptTelemetryRecorder",
    "compose_record",
    "host_peak_working_set_bytes",
]
