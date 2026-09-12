from __future__ import annotations

from pathlib import Path

import pytest

from mavi_vision.runtime.offline_lock import (
    LockedDistribution,
    OfflineLockError,
    OfflineRuntimeLock,
    load_offline_runtime_lock,
    serialize_offline_runtime_lock,
    validate_offline_runtime_lock_for_runtime,
)


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64
_HASH_D = "d" * 64
_HASH_E = "e" * 64


def _lock_text(
    rows: list[str] | None = None,
    *,
    schema: str = "mavi-offline-lock-v1",
    variant: str = "linux-x86_64-cpu",
    python_version: str = "3.12.14",
) -> str:
    package_rows = rows or [
        f"av==16.1.0 --hash=sha256:{_HASH_A}",
        f"mavi-vision==0.1.0 --hash=sha256:{_HASH_B}",
        f"mmcv==2.1.0 --hash=sha256:{_HASH_C}",
        f"torch==2.6.0+cpu --hash=sha256:{_HASH_D}",
        f"torchvision==0.21.0+cpu --hash=sha256:{_HASH_E}",
    ]
    return (
        f"# schema: {schema}\n"
        f"# platform-variant: {variant}\n"
        f"# python-version: {python_version}\n"
        + "\n".join(package_rows)
        + "\n"
    )


def _write_lock(tmp_path: Path, text: str | bytes) -> Path:
    path = tmp_path / "runtime.lock"
    payload = text.encode("utf-8") if isinstance(text, str) else text
    path.write_bytes(payload)
    return path


def _assert_code(exc: pytest.ExceptionInfo[OfflineLockError], code: str) -> None:
    assert exc.value.code == code


def test_canonical_cpu_lock_round_trips_to_immutable_records(tmp_path: Path) -> None:
    path = _write_lock(tmp_path, _lock_text())

    lock = load_offline_runtime_lock(path)

    assert lock == OfflineRuntimeLock(
        schema_version="mavi-offline-lock-v1",
        platform_variant="linux-x86_64-cpu",
        python_version="3.12.14",
        distributions=(
            LockedDistribution("av", "16.1.0", _HASH_A),
            LockedDistribution("mavi-vision", "0.1.0", _HASH_B),
            LockedDistribution("mmcv", "2.1.0", _HASH_C),
            LockedDistribution("torch", "2.6.0+cpu", _HASH_D),
            LockedDistribution("torchvision", "0.21.0+cpu", _HASH_E),
        ),
    )
    assert serialize_offline_runtime_lock(lock) == path.read_bytes()


@pytest.mark.parametrize(
    ("text", "code"),
    [
        (
            _lock_text().replace(
                "# schema: mavi-offline-lock-v1\n",
                "",
                1,
            ),
            "offline_lock_header_invalid",
        ),
        (
            _lock_text(schema="mavi-offline-lock-v2"),
            "offline_lock_schema_invalid",
        ),
        (
            _lock_text().replace(
                "# platform-variant: linux-x86_64-cpu\n"
                "# python-version: 3.12.14\n",
                "# python-version: 3.12.14\n"
                "# platform-variant: linux-x86_64-cpu\n",
                1,
            ),
            "offline_lock_header_invalid",
        ),
        (
            _lock_text(variant="darwin-arm64-cpu"),
            "offline_lock_variant_invalid",
        ),
        (
            _lock_text(python_version="3.12"),
            "offline_lock_python_version_invalid",
        ),
        (
            _lock_text(rows=[]),
            "offline_lock_empty",
        ),
    ],
)
def test_rejects_invalid_headers_or_empty_lock(
    tmp_path: Path,
    text: str,
    code: str,
) -> None:
    with pytest.raises(OfflineLockError) as exc:
        load_offline_runtime_lock(_write_lock(tmp_path, text))
    _assert_code(exc, code)


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (
            b"\xef\xbb\xbf" + _lock_text().encode(),
            "offline_lock_bom_forbidden",
        ),
        (
            _lock_text().replace("\n", "\r\n").encode(),
            "offline_lock_cr_forbidden",
        ),
        (
            _lock_text().encode() + b"\xff",
            "offline_lock_utf8_invalid",
        ),
    ],
)
def test_rejects_noncanonical_text_encoding(
    tmp_path: Path,
    payload: bytes,
    code: str,
) -> None:
    with pytest.raises(OfflineLockError) as exc:
        load_offline_runtime_lock(_write_lock(tmp_path, payload))
    _assert_code(exc, code)


@pytest.mark.parametrize(
    ("row", "code"),
    [
        (
            f"torch>=2.6.0 --hash=sha256:{_HASH_D}",
            "offline_lock_requirement_invalid",
        ),
        (
            f"torch==2.6.* --hash=sha256:{_HASH_D}",
            "offline_lock_requirement_invalid",
        ),
        (
            f"torch==2.6.0+cpu; python_version>='3.12' --hash=sha256:{_HASH_D}",
            "offline_lock_requirement_invalid",
        ),
        (
            f"torch @ https://example.invalid/torch.whl --hash=sha256:{_HASH_D}",
            "offline_lock_requirement_invalid",
        ),
        (
            f"git+https://example.invalid/repo.git --hash=sha256:{_HASH_D}",
            "offline_lock_requirement_invalid",
        ),
        (
            f"-e ./local-package --hash=sha256:{_HASH_D}",
            "offline_lock_requirement_invalid",
        ),
        (
            "--index-url https://example.invalid/simple",
            "offline_lock_requirement_invalid",
        ),
        (
            f"torch==2.6.0+cpu",
            "offline_lock_hash_invalid",
        ),
        (
            "torch==2.6.0+cpu --hash=sha256:not-a-hash",
            "offline_lock_hash_invalid",
        ),
        (
            f"torch==2.6.0+cpu --hash=md5:{_HASH_D}",
            "offline_lock_hash_invalid",
        ),
        (
            f"torch==2.6.0+cpu --hash=sha256:{_HASH_D} --hash=sha256:{_HASH_E}",
            "offline_lock_requirement_invalid",
        ),
        (
            f"MAVI_Vision==0.1.0 --hash=sha256:{_HASH_B}",
            "offline_lock_name_noncanonical",
        ),
    ],
)
def test_rejects_unsafe_or_noncanonical_requirement_rows(
    tmp_path: Path,
    row: str,
    code: str,
) -> None:
    rows = [
        f"av==16.1.0 --hash=sha256:{_HASH_A}",
        f"mavi-vision==0.1.0 --hash=sha256:{_HASH_B}",
        f"mmcv==2.1.0 --hash=sha256:{_HASH_C}",
        row,
        f"torchvision==0.21.0+cpu --hash=sha256:{_HASH_E}",
    ]

    with pytest.raises(OfflineLockError) as exc:
        load_offline_runtime_lock(_write_lock(tmp_path, _lock_text(rows=rows)))
    _assert_code(exc, code)


def test_rejects_duplicate_package_names(tmp_path: Path) -> None:
    rows = [
        f"av==16.1.0 --hash=sha256:{_HASH_A}",
        f"mavi-vision==0.1.0 --hash=sha256:{_HASH_B}",
        f"mmcv==2.1.0 --hash=sha256:{_HASH_C}",
        f"torch==2.6.0+cpu --hash=sha256:{_HASH_D}",
        f"torch==2.6.0+cpu --hash=sha256:{_HASH_E}",
        f"torchvision==0.21.0+cpu --hash=sha256:{_HASH_A}",
    ]

    with pytest.raises(OfflineLockError) as exc:
        load_offline_runtime_lock(_write_lock(tmp_path, _lock_text(rows=rows)))
    _assert_code(exc, "offline_lock_duplicate_distribution")


def test_rejects_unsorted_package_rows(tmp_path: Path) -> None:
    rows = [
        f"mavi-vision==0.1.0 --hash=sha256:{_HASH_B}",
        f"av==16.1.0 --hash=sha256:{_HASH_A}",
        f"mmcv==2.1.0 --hash=sha256:{_HASH_C}",
        f"torch==2.6.0+cpu --hash=sha256:{_HASH_D}",
        f"torchvision==0.21.0+cpu --hash=sha256:{_HASH_E}",
    ]

    with pytest.raises(OfflineLockError) as exc:
        load_offline_runtime_lock(_write_lock(tmp_path, _lock_text(rows=rows)))
    _assert_code(exc, "offline_lock_not_sorted")


def test_runtime_validation_requires_mavi_and_exact_cpu_binary_identity(
    tmp_path: Path,
) -> None:
    lock = load_offline_runtime_lock(_write_lock(tmp_path, _lock_text()))

    validate_offline_runtime_lock_for_runtime(
        lock,
        expected_variant="linux-x86_64-cpu",
        expected_python_version="3.12.14",
        semantic_graph={
            "av": "16.1.0",
            "mmcv": "2.1.0",
            "torch": "2.6.0",
            "torchvision": "0.21.0",
        },
        binary_versions={
            "torch": "2.6.0+cpu",
            "torchvision": "0.21.0+cpu",
        },
    )

    without_mavi = OfflineRuntimeLock(
        schema_version=lock.schema_version,
        platform_variant=lock.platform_variant,
        python_version=lock.python_version,
        distributions=tuple(
            item for item in lock.distributions if item.name != "mavi-vision"
        ),
    )
    with pytest.raises(OfflineLockError) as exc:
        validate_offline_runtime_lock_for_runtime(
            without_mavi,
            expected_variant="linux-x86_64-cpu",
            expected_python_version="3.12.14",
            semantic_graph={"torch": "2.6.0", "torchvision": "0.21.0"},
            binary_versions={
                "torch": "2.6.0+cpu",
                "torchvision": "0.21.0+cpu",
            },
        )
    _assert_code(exc, "offline_lock_mavi_missing")

    wrong_torch = OfflineRuntimeLock(
        schema_version=lock.schema_version,
        platform_variant=lock.platform_variant,
        python_version=lock.python_version,
        distributions=tuple(
            LockedDistribution(item.name, "2.6.1+cpu", item.sha256)
            if item.name == "torch"
            else item
            for item in lock.distributions
        ),
    )
    with pytest.raises(OfflineLockError) as exc:
        validate_offline_runtime_lock_for_runtime(
            wrong_torch,
            expected_variant="linux-x86_64-cpu",
            expected_python_version="3.12.14",
            semantic_graph={"torch": "2.6.0", "torchvision": "0.21.0"},
            binary_versions={
                "torch": "2.6.0+cpu",
                "torchvision": "0.21.0+cpu",
            },
        )
    _assert_code(exc, "offline_lock_binary_version_mismatch")


def test_runtime_validation_rejects_variant_or_python_mismatch(tmp_path: Path) -> None:
    lock = load_offline_runtime_lock(_write_lock(tmp_path, _lock_text()))

    with pytest.raises(OfflineLockError) as exc:
        validate_offline_runtime_lock_for_runtime(
            lock,
            expected_variant="windows-x86_64-cpu",
            expected_python_version="3.12.10",
            semantic_graph={},
            binary_versions=None,
        )
    _assert_code(exc, "offline_lock_variant_mismatch")


def test_runtime_validation_rejects_qualified_cuda_lock_before_hardware_gate(
    tmp_path: Path,
) -> None:
    lock = load_offline_runtime_lock(
        _write_lock(
            tmp_path,
            _lock_text(
                variant="linux-x86_64-cuda",
                python_version="3.12.14",
            ),
        )
    )

    with pytest.raises(OfflineLockError) as exc:
        validate_offline_runtime_lock_for_runtime(
            lock,
            expected_variant="linux-x86_64-cuda",
            expected_python_version="3.12.14",
            semantic_graph={},
            binary_versions=None,
            platform_status="pending-hardware-qualification",
        )
    _assert_code(exc, "offline_lock_platform_not_qualified")
