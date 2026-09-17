from __future__ import annotations

import pytest

from mavi_vision.runtime.offline_lock import (
    LockedDistribution,
    OfflineLockError,
    OfflineRuntimeLock,
    validate_offline_runtime_lock_for_runtime,
)

_HASH = "a" * 64


def _lock(*rows: tuple[str, str]) -> OfflineRuntimeLock:
    return OfflineRuntimeLock(
        schema_version="mavi-offline-lock-v1",
        platform_variant="windows-x86_64-cpu",
        python_version="3.12.10",
        distributions=tuple(
            LockedDistribution(name, version, _HASH)
            for name, version in sorted(rows)
        ),
    )


def _validate(lock: OfflineRuntimeLock, roots: tuple[str, ...]) -> None:
    validate_offline_runtime_lock_for_runtime(
        lock,
        expected_variant="windows-x86_64-cpu",
        expected_python_version="3.12.10",
        semantic_graph={},
        binary_versions=None,
        root_requirements=roots,
    )


def test_v2_runtime_roots_accept_third_party_only_lock() -> None:
    _validate(
        _lock(("httpx", "0.28.1"), ("torch", "2.6.0")),
        ("httpx<0.29,>=0.28", "torch==2.6.0"),
    )


def test_v2_runtime_roots_reject_first_party_wheel_in_lock() -> None:
    with pytest.raises(
        OfflineLockError,
        match="offline_lock_first_party_distribution_forbidden",
    ):
        _validate(
            _lock(
                ("httpx", "0.28.1"),
                ("mavi-vision", "0.1.0"),
                ("torch", "2.6.0"),
            ),
            ("httpx<0.29,>=0.28", "torch==2.6.0"),
        )


def test_v2_runtime_roots_reject_missing_application_root() -> None:
    with pytest.raises(
        OfflineLockError,
        match="offline_lock_root_distribution_missing",
    ):
        _validate(
            _lock(("torch", "2.6.0")),
            ("httpx<0.29,>=0.28", "torch==2.6.0"),
        )


def test_v2_runtime_roots_reject_incompatible_locked_version() -> None:
    with pytest.raises(
        OfflineLockError,
        match="offline_lock_root_version_mismatch",
    ):
        _validate(
            _lock(("httpx", "0.27.2"), ("torch", "2.6.0")),
            ("httpx<0.29,>=0.28", "torch==2.6.0"),
        )


def test_v2_runtime_roots_reject_direct_url() -> None:
    with pytest.raises(
        OfflineLockError,
        match="offline_lock_root_requirement_invalid",
    ):
        _validate(
            _lock(("unsafe", "1.0")),
            ("unsafe @ https://example.invalid/unsafe.whl",),
        )
