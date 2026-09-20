"""Ask Windows not to fall asleep while one vision attempt is running.

A vision attempt is a long, quiet stretch of native GPU work with no user
input, which is exactly what Windows idle timers are built to interpret as an
idle machine. If the host suspends mid-attempt every thread in this process is
frozen, and what the worker sees on resume is indistinguishable from work that
stopped making progress. This module asks Windows to leave the system alone for
the duration of one attempt, and nothing else.

What this is not
----------------
A power request defeats *idle* transitions only. It does not, and is not
claimed to, prevent a closed lid, a pressed power button, an operator choosing
Sleep or Hibernate, or every Modern Standby transition -- Windows honours a
user's explicit intent over any process's request. So this narrows a window; it
does not close one. Nothing downstream may be written as though the host can no
longer suspend.

Nor does it diagnose anything. Whether a suspended host is what ended a given
attempt is a separate question answered by separate evidence, and this module
deliberately produces no qualification signal, no readiness input and no
failure code.

Why best-effort
---------------
Every call here is allowed to fail and the attempt proceeds regardless. A
worker that refused to process video because Windows declined to keep the
machine awake would be strictly worse than the failure this guards against, so
the API boundary swallows its own errors and reports what it managed to get.

`PowerRequestDisplayRequired` is deliberately never requested. A dark monitor
does not suspend a process, so keeping one lit would be an unrequested change
to how an operator's workstation behaves in exchange for nothing.

Release
-------
Requests are per-attempt and per-handle: one handle is created, used and closed
inside a single `with` block, so an idle worker holds nothing and a sequence of
attempts accumulates nothing. Windows also reclaims a process's power requests
when that process exits, which is what covers the watchdog's `os._exit` path --
that path runs no `finally` block by design and needs none here.
"""

from __future__ import annotations

import logging
import platform
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Protocol


_LOGGER = logging.getLogger(__name__)

# POWER_REQUEST_TYPE. Only these two are ever requested; see the module
# docstring for why PowerRequestDisplayRequired (0) is not among them.
POWER_REQUEST_SYSTEM_REQUIRED = 1
POWER_REQUEST_EXECUTION_REQUIRED = 3

_REQUEST_TYPE_NAMES = {
    POWER_REQUEST_SYSTEM_REQUIRED: "PowerRequestSystemRequired",
    POWER_REQUEST_EXECUTION_REQUIRED: "PowerRequestExecutionRequired",
}

# REASON_CONTEXT
_POWER_REQUEST_CONTEXT_VERSION = 0
_POWER_REQUEST_CONTEXT_SIMPLE_STRING = 0x1

_MAX_REASON_CHARACTERS = 256


class HostPowerApi(Protocol):
    """The Windows call surface, isolated so it can be exercised anywhere.

    Keeping this a protocol is what lets the Windows-specific behaviour be
    tested on any platform: the real implementation is the only part that
    cannot run in CI, and it is the only part with no logic in it.
    """

    def create_request(self, reason: str) -> object: ...

    def set_request(self, handle: object, request_type: int) -> bool: ...

    def clear_request(self, handle: object, request_type: int) -> bool: ...

    def close_handle(self, handle: object) -> None: ...


@dataclass(frozen=True, slots=True)
class HostPowerRequestState:
    """What was actually obtained, as opposed to what was asked for.

    `granted` is empty on every platform that is not Windows and on any Windows
    host that refused the request. Callers may report this; none may depend on
    it, because an empty grant is a supported outcome rather than an error.
    """

    supported: bool = False
    granted: tuple[int, ...] = field(default=())

    @property
    def active(self) -> bool:
        return bool(self.granted)


class _CtypesHostPowerApi:
    """`PowerCreateRequest`/`PowerSetRequest` through ctypes, no logic added.

    Constructed only after the caller has established that this is Windows;
    `ctypes.windll` does not exist elsewhere, so the import and the attribute
    access are both deferred to this point.
    """

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes

        class _DetailedReason(ctypes.Structure):
            _fields_ = [
                ("LocalizedReasonModule", wintypes.HMODULE),
                ("LocalizedReasonId", wintypes.ULONG),
                ("ReasonStringCount", wintypes.ULONG),
                ("ReasonStrings", ctypes.POINTER(wintypes.LPWSTR)),
            ]

        class _Reason(ctypes.Union):
            _fields_ = [
                ("Detailed", _DetailedReason),
                ("SimpleReasonString", wintypes.LPWSTR),
            ]

        class _ReasonContext(ctypes.Structure):
            _fields_ = [
                ("Version", wintypes.ULONG),
                ("Flags", wintypes.DWORD),
                ("Reason", _Reason),
            ]

        self._reason_context_type = _ReasonContext

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.PowerCreateRequest.argtypes = [ctypes.POINTER(_ReasonContext)]
        kernel32.PowerCreateRequest.restype = wintypes.HANDLE
        kernel32.PowerSetRequest.argtypes = [wintypes.HANDLE, ctypes.c_int]
        kernel32.PowerSetRequest.restype = wintypes.BOOL
        kernel32.PowerClearRequest.argtypes = [wintypes.HANDLE, ctypes.c_int]
        kernel32.PowerClearRequest.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        self._kernel32 = kernel32

    def create_request(self, reason: str) -> object:
        context = self._reason_context_type()
        context.Version = _POWER_REQUEST_CONTEXT_VERSION
        context.Flags = _POWER_REQUEST_CONTEXT_SIMPLE_STRING
        context.Reason.SimpleReasonString = reason

        handle = self._kernel32.PowerCreateRequest(self._ctypes.byref(context))
        if not handle:
            raise OSError(
                self._ctypes.get_last_error(),
                "PowerCreateRequest failed",
            )
        return handle

    def set_request(self, handle: object, request_type: int) -> bool:
        return bool(self._kernel32.PowerSetRequest(handle, request_type))

    def clear_request(self, handle: object, request_type: int) -> bool:
        return bool(self._kernel32.PowerClearRequest(handle, request_type))

    def close_handle(self, handle: object) -> None:
        self._kernel32.CloseHandle(handle)


_warning_lock = threading.Lock()
_warning_emitted = False


def reset_failure_warning_state() -> None:
    """Forget that the once-per-process failure warning was already emitted.

    Exists for tests. A host where the power API fails will fail for every
    attempt, so the warning is suppressed after the first to keep a worker log
    readable; tests need each case to observe its own warning.
    """
    global _warning_emitted
    with _warning_lock:
        _warning_emitted = False


def _warn_once(message: str, *args: object) -> None:
    global _warning_emitted
    with _warning_lock:
        if _warning_emitted:
            return
        _warning_emitted = True
    _LOGGER.warning(message, *args)


def _is_windows(system: str | None) -> bool:
    return (system or platform.system()).casefold() == "windows"


def _sanitize_reason(reason: str) -> str:
    """Bound the reason and keep it to one line.

    The string is surfaced verbatim by `powercfg /requests`, so a newline would
    corrupt an operator's reading of that output.
    """
    collapsed = " ".join(str(reason).split())
    if not collapsed:
        collapsed = "MAVI vision processing active"
    return collapsed[:_MAX_REASON_CHARACTERS]


@contextmanager
def keep_host_awake(
    reason: str = "MAVI vision processing active",
    *,
    api: HostPowerApi | None = None,
    system: str | None = None,
) -> Iterator[HostPowerRequestState]:
    """Hold an idle-sleep inhibition for the body, on Windows, best-effort.

    Yields what was granted and never raises: every failure path yields an
    inactive state instead, because the caller's work is more important than
    the request and must not be conditioned on it.
    """
    if not _is_windows(system):
        # No syscall, no log line, no behavioural difference of any kind on
        # Linux -- the CPU and CUDA attempt paths are identical here.
        yield HostPowerRequestState(supported=False)
        return

    if api is None:
        try:
            api = _CtypesHostPowerApi()
        except Exception as exc:
            _warn_once(
                "Windows power API unavailable; host may sleep during a vision "
                "attempt (%s)",
                type(exc).__name__,
            )
            yield HostPowerRequestState(supported=False)
            return

    safe_reason = _sanitize_reason(reason)
    try:
        handle = api.create_request(safe_reason)
    except Exception as exc:
        _warn_once(
            "PowerCreateRequest failed; host may sleep during a vision attempt "
            "(%s)",
            type(exc).__name__,
        )
        yield HostPowerRequestState(supported=True)
        return

    granted: list[int] = []
    for request_type in (
        POWER_REQUEST_SYSTEM_REQUIRED,
        POWER_REQUEST_EXECUTION_REQUIRED,
    ):
        # Each type is requested independently. PowerRequestExecutionRequired
        # needs Windows 8 or later and can be refused on its own; the system
        # request is the one that matters and must survive that refusal.
        try:
            if api.set_request(handle, request_type):
                granted.append(request_type)
                continue
        except Exception:
            pass
        _warn_once(
            "PowerSetRequest(%s) was refused; host may sleep during a vision "
            "attempt",
            _REQUEST_TYPE_NAMES.get(request_type, request_type),
        )

    if granted:
        _LOGGER.info(
            "Holding Windows power request for the active attempt: %s",
            ", ".join(_REQUEST_TYPE_NAMES[value] for value in granted),
        )

    try:
        yield HostPowerRequestState(supported=True, granted=tuple(granted))
    finally:
        # Releasing is as best-effort as acquiring: a failure here must not
        # displace whatever outcome the attempt is already carrying.
        for request_type in granted:
            try:
                api.clear_request(handle, request_type)
            except Exception:
                _LOGGER.debug("PowerClearRequest failed", exc_info=False)
        try:
            api.close_handle(handle)
        except Exception:
            _LOGGER.debug("CloseHandle failed", exc_info=False)
        if granted:
            _LOGGER.info("Released the Windows power request for the attempt")
