"""What the idle-sleep inhibition must do, and what it must never do.

The Windows call surface cannot run in CI, so every test here drives the real
control flow through a fake `HostPowerApi`. That is the point of the protocol:
the only untestable part is the ctypes binding, which contains no decisions.

The negative properties carry most of the weight. This mechanism sits directly
in the path of every vision attempt on every platform, so the tests that matter
most are the ones proving it cannot refuse work, cannot retain state between
attempts, and does nothing whatsoever off Windows.
"""

from __future__ import annotations

import logging

import pytest

from mavi_vision.runtime import host_power
from mavi_vision.runtime.host_power import (
    POWER_REQUEST_EXECUTION_REQUIRED,
    POWER_REQUEST_SYSTEM_REQUIRED,
    HostPowerRequestState,
    keep_host_awake,
    reset_failure_warning_state,
)


class FakeHostPowerApi:
    """Records the call sequence and can be told to fail at any boundary."""

    def __init__(
        self,
        *,
        create_error: Exception | None = None,
        set_error: Exception | None = None,
        clear_error: Exception | None = None,
        close_error: Exception | None = None,
        refuse: tuple[int, ...] = (),
    ) -> None:
        self.create_error = create_error
        self.set_error = set_error
        self.clear_error = clear_error
        self.close_error = close_error
        self.refuse = refuse
        self.events: list[str] = []
        self.reasons: list[str] = []
        self.handles: list[object] = []
        self.open_handles: set[int] = set()
        self._next_handle = 1000

    def create_request(self, reason: str) -> object:
        self.reasons.append(reason)
        if self.create_error is not None:
            self.events.append("create:error")
            raise self.create_error
        handle = self._next_handle
        self._next_handle += 1
        self.handles.append(handle)
        self.open_handles.add(handle)
        self.events.append(f"create:{handle}")
        return handle

    def set_request(self, handle: object, request_type: int) -> bool:
        if self.set_error is not None:
            self.events.append(f"set:error:{request_type}")
            raise self.set_error
        if request_type in self.refuse:
            self.events.append(f"set:refused:{request_type}")
            return False
        self.events.append(f"set:{request_type}")
        return True

    def clear_request(self, handle: object, request_type: int) -> bool:
        if self.clear_error is not None:
            self.events.append(f"clear:error:{request_type}")
            raise self.clear_error
        self.events.append(f"clear:{request_type}")
        return True

    def close_handle(self, handle: object) -> None:
        if self.close_error is not None:
            self.events.append("close:error")
            raise self.close_error
        self.open_handles.discard(int(handle))  # type: ignore[arg-type]
        self.events.append(f"close:{handle}")


@pytest.fixture(autouse=True)
def _reset_warning_state():
    """Each case must be able to observe its own once-per-process warning."""
    reset_failure_warning_state()
    yield
    reset_failure_warning_state()


# Non-Windows platforms
def test_non_windows_does_nothing_at_all() -> None:
    api = FakeHostPowerApi()

    with keep_host_awake("reason", api=api, system="Linux") as state:
        assert state == HostPowerRequestState(supported=False, granted=())
        assert state.active is False

    # Not "the request failed" -- the request was never attempted. A Linux
    # vision attempt must take a path with no Windows semantics in it.
    assert api.events == []


def test_non_windows_is_silent(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger=host_power.__name__):
        with keep_host_awake(system="Linux"):
            pass

    assert caplog.records == []


def test_non_windows_never_touches_the_ctypes_boundary(monkeypatch) -> None:
    """Constructing the real API on Linux would raise; it must not be reached."""

    def _explode() -> None:
        raise AssertionError("the Windows API was constructed off Windows")

    monkeypatch.setattr(host_power, "_CtypesHostPowerApi", _explode)

    with keep_host_awake(system="Linux") as state:
        assert state.supported is False


# Windows success path
def test_windows_acquires_both_requests_and_releases_them() -> None:
    api = FakeHostPowerApi()

    with keep_host_awake("MAVI vision processing active", api=api, system="Windows") as state:
        assert state.supported is True
        assert state.granted == (
            POWER_REQUEST_SYSTEM_REQUIRED,
            POWER_REQUEST_EXECUTION_REQUIRED,
        )
        assert state.active is True
        assert api.events == [
            "create:1000",
            f"set:{POWER_REQUEST_SYSTEM_REQUIRED}",
            f"set:{POWER_REQUEST_EXECUTION_REQUIRED}",
        ]

    assert api.events[-3:] == [
        f"clear:{POWER_REQUEST_SYSTEM_REQUIRED}",
        f"clear:{POWER_REQUEST_EXECUTION_REQUIRED}",
        "close:1000",
    ]
    assert api.open_handles == set()


def test_the_display_request_is_never_asked_for() -> None:
    """A dark monitor does not suspend a process; keeping one lit is not ours."""
    api = FakeHostPowerApi()

    with keep_host_awake(api=api, system="Windows"):
        pass

    assert not any(event == "set:0" for event in api.events)


def test_the_reason_reaches_the_windows_api_verbatim() -> None:
    api = FakeHostPowerApi()

    with keep_host_awake("MAVI vision processing active", api=api, system="Windows"):
        pass

    assert api.reasons == ["MAVI vision processing active"]


def test_a_multiline_reason_is_collapsed_for_powercfg() -> None:
    api = FakeHostPowerApi()

    with keep_host_awake("MAVI\nvision   active\n", api=api, system="Windows"):
        pass

    assert api.reasons == ["MAVI vision active"]


def test_a_long_reason_is_bounded() -> None:
    api = FakeHostPowerApi()

    with keep_host_awake("x" * 5000, api=api, system="Windows"):
        pass

    assert len(api.reasons[0]) == 256


def test_an_empty_reason_falls_back_to_a_usable_one() -> None:
    api = FakeHostPowerApi()

    with keep_host_awake("   ", api=api, system="Windows"):
        pass

    assert api.reasons == ["MAVI vision processing active"]


# Windows partial support
def test_execution_required_may_be_refused_without_losing_system_required() -> None:
    """PowerRequestExecutionRequired needs Win8+ and can be refused alone."""
    api = FakeHostPowerApi(refuse=(POWER_REQUEST_EXECUTION_REQUIRED,))

    with keep_host_awake(api=api, system="Windows") as state:
        assert state.granted == (POWER_REQUEST_SYSTEM_REQUIRED,)
        assert state.active is True

    # Only what was granted is cleared.
    assert f"clear:{POWER_REQUEST_EXECUTION_REQUIRED}" not in api.events
    assert f"clear:{POWER_REQUEST_SYSTEM_REQUIRED}" in api.events
    assert api.open_handles == set()


def test_every_request_refused_still_yields_and_still_closes() -> None:
    api = FakeHostPowerApi(
        refuse=(POWER_REQUEST_SYSTEM_REQUIRED, POWER_REQUEST_EXECUTION_REQUIRED)
    )

    with keep_host_awake(api=api, system="Windows") as state:
        assert state.granted == ()
        assert state.active is False

    assert api.open_handles == set()


# Failure semantics
def test_create_failure_yields_instead_of_raising() -> None:
    api = FakeHostPowerApi(create_error=OSError(5, "Access is denied"))

    with keep_host_awake(api=api, system="Windows") as state:
        assert state.supported is True
        assert state.active is False

    assert api.open_handles == set()


def test_create_failure_warns_once_per_process(
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = FakeHostPowerApi(create_error=OSError(5, "Access is denied"))

    with caplog.at_level(logging.WARNING, logger=host_power.__name__):
        for _ in range(3):
            with keep_host_awake(api=api, system="Windows"):
                pass

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    # A host where this fails fails every attempt; one warning, not one per job.
    assert len(warnings) == 1


def test_set_failure_is_tolerated() -> None:
    api = FakeHostPowerApi(set_error=OSError("boom"))

    with keep_host_awake(api=api, system="Windows") as state:
        assert state.granted == ()

    assert api.open_handles == set()


def test_clear_failure_does_not_escape() -> None:
    api = FakeHostPowerApi(clear_error=OSError("boom"))

    with keep_host_awake(api=api, system="Windows"):
        pass

    assert "close:1000" in api.events


def test_close_failure_does_not_escape() -> None:
    api = FakeHostPowerApi(close_error=OSError("boom"))

    with keep_host_awake(api=api, system="Windows"):
        pass


def test_an_unavailable_ctypes_binding_is_survivable(monkeypatch) -> None:
    def _explode() -> None:
        raise OSError("powrprof unavailable")

    monkeypatch.setattr(host_power, "_CtypesHostPowerApi", _explode)

    with keep_host_awake(system="Windows") as state:
        assert state.supported is False
        assert state.active is False


# Body exceptions and handle lifetime
def test_release_happens_when_the_body_raises() -> None:
    api = FakeHostPowerApi()

    with pytest.raises(RuntimeError, match="processing exploded"):
        with keep_host_awake(api=api, system="Windows"):
            raise RuntimeError("processing exploded")

    assert api.events[-1] == "close:1000"
    assert api.open_handles == set()


def test_release_happens_on_cancellation() -> None:
    api = FakeHostPowerApi()

    with pytest.raises(BaseException):
        with keep_host_awake(api=api, system="Windows"):
            raise KeyboardInterrupt()

    assert api.open_handles == set()


def test_a_clear_failure_cannot_displace_the_body_exception() -> None:
    """The attempt's own outcome outranks anything that goes wrong releasing."""
    api = FakeHostPowerApi(clear_error=OSError("boom"), close_error=OSError("boom"))

    with pytest.raises(RuntimeError, match="processing exploded"):
        with keep_host_awake(api=api, system="Windows"):
            raise RuntimeError("processing exploded")


def test_repeated_attempts_leak_no_handle_and_retain_no_state() -> None:
    api = FakeHostPowerApi()

    for _ in range(5):
        with keep_host_awake(api=api, system="Windows") as state:
            assert state.granted == (
                POWER_REQUEST_SYSTEM_REQUIRED,
                POWER_REQUEST_EXECUTION_REQUIRED,
            )
            assert len(api.open_handles) == 1

    assert len(api.handles) == 5
    assert len(set(api.handles)) == 5
    assert api.open_handles == set()


def test_nothing_is_held_outside_the_block() -> None:
    """An idle worker must hold no request at all."""
    api = FakeHostPowerApi()

    with keep_host_awake(api=api, system="Windows"):
        assert api.open_handles

    assert api.open_handles == set()
    assert api.events.count("create:1000") == 1


# The state object
def test_state_defaults_describe_an_unsupported_host() -> None:
    state = HostPowerRequestState()

    assert state.supported is False
    assert state.granted == ()
    assert state.active is False


def test_state_is_immutable() -> None:
    state = HostPowerRequestState(supported=True, granted=(1,))

    with pytest.raises(Exception):
        state.granted = ()  # type: ignore[misc]


# Scope boundaries
def test_the_module_never_mutates_host_power_configuration() -> None:
    """`powercfg /change` would outlive the process and the operator's consent."""
    source = (
        host_power.__file__
        and open(host_power.__file__, encoding="utf-8").read()
    )

    assert "powercfg" not in source.replace(
        "`powercfg /requests`", ""
    ).replace("`powercfg /change`", "")
    assert "subprocess" not in source
    assert "SetThreadExecutionState" not in source


def test_the_module_imports_nothing_from_the_runtime_it_must_not_influence() -> None:
    """Coupling is what an import makes possible, not what prose mentions.

    Power management must stay unable to reach qualification, readiness, device
    resolution or the watchdog, so the check is on the import graph.
    """
    import ast

    tree = ast.parse(open(host_power.__file__, encoding="utf-8").read())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert not any(name.startswith("mavi_vision") for name in imported)
    assert imported <= {
        "__future__",
        "logging",
        "platform",
        "threading",
        "collections.abc",
        "contextlib",
        "dataclasses",
        "typing",
        "ctypes",
        "ctypes.wintypes",
    }
