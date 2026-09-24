"""Process memory probes for the S1.4 B2 harness, without ``psutil``.

``psutil`` is not a MAVI dependency and must not be added for qualification
(S1.4 plan §6.2). Each platform's own interface is read directly:

- **Linux** — ``/proc/self/smaps_rollup`` gives RSS, PSS and USS (private clean +
  private dirty); ``/proc/self/status`` gives the ``VmHWM`` peak.
- **Windows** — ``GetProcessMemoryInfo`` (``PROCESS_MEMORY_COUNTERS_EX``) gives
  the working set and ``PrivateUsage``. ``PrivateUsage`` is the process's
  **commit charge**, not USS, and every sample names it as such.

Any other platform raises: a probe that silently returned zeros would make the
bound-3 slope trivially pass.
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass
from pathlib import Path

_KIB = 1024


@dataclass(frozen=True)
class MemorySample:
    """One reading. ``primary`` is the value B2 bound 3 fits a slope to."""

    platform: str
    primary_metric: str
    primary_bytes: int
    rss_bytes: int
    peak_bytes: int
    pss_bytes: int | None = None
    uss_bytes: int | None = None
    commit_charge_bytes: int | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def parse_smaps_rollup(text: str) -> dict[str, int]:
    """Bytes for every ``Key: <n> kB`` line of ``smaps_rollup``."""
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if len(parts) == 2 and parts[1] == "kB" and parts[0].isdigit():
            values[key.strip()] = int(parts[0]) * _KIB
    required = {"Rss", "Pss", "Private_Clean", "Private_Dirty"}
    missing = required - values.keys()
    if missing:
        raise RuntimeError(f"smaps_rollup_incomplete:{sorted(missing)}")
    return values


def parse_status_peak(text: str) -> int:
    for line in text.splitlines():
        if line.startswith("VmHWM:"):
            parts = line.split()
            if len(parts) == 3 and parts[2] == "kB":
                return int(parts[1]) * _KIB
    raise RuntimeError("status_vmhwm_missing")


def _linux(proc: Path = Path("/proc/self")) -> MemorySample:
    rollup = parse_smaps_rollup((proc / "smaps_rollup").read_text(encoding="ascii"))
    uss = rollup["Private_Clean"] + rollup["Private_Dirty"]
    return MemorySample(
        platform="linux",
        primary_metric="uss",
        primary_bytes=uss,
        rss_bytes=rollup["Rss"],
        peak_bytes=parse_status_peak((proc / "status").read_text(encoding="ascii")),
        pss_bytes=rollup["Pss"],
        uss_bytes=uss,
    )


def _windows() -> MemorySample:  # pragma: no cover - exercised on the Windows variant
    import ctypes
    from ctypes import wintypes

    class ProcessMemoryCountersEx(ctypes.Structure):
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
            ("PrivateUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCountersEx()
    counters.cb = ctypes.sizeof(ProcessMemoryCountersEx)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo failed")
    return MemorySample(
        platform="win32",
        primary_metric="commit_charge",
        primary_bytes=int(counters.PrivateUsage),
        rss_bytes=int(counters.WorkingSetSize),
        peak_bytes=int(counters.PeakWorkingSetSize),
        commit_charge_bytes=int(counters.PrivateUsage),
    )


def sample() -> MemorySample:
    if sys.platform.startswith("linux"):
        return _linux()
    if sys.platform == "win32":
        return _windows()
    raise RuntimeError(f"process_memory_unsupported_platform:{sys.platform}")
