from __future__ import annotations

from pathlib import Path
import importlib.util
import zipfile

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

FREEZE_TOOL_PATH = (
    Path(__file__).parents[3] / "tools" / "vision" / "freeze_offline_lock.py"
)


def _load_freeze_tool():
    spec = importlib.util.spec_from_file_location(
        "freeze_offline_lock",
        FREEZE_TOOL_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("freeze_offline_lock_module_unloadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_wheel(
    root: Path,
    *,
    filename: str,
    name: str,
    version: str,
    duplicate_metadata: bool = False,
) -> Path:
    path = root / filename
    root.mkdir(parents=True, exist_ok=True)
    dist_info = f"{name.replace('-', '_')}-{version}.dist-info"
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{dist_info}/METADATA", metadata)
        if duplicate_metadata:
            archive.writestr(
                f"other-{version}.dist-info/METADATA",
                "Metadata-Version: 2.1\nName: other\nVersion: 1.0\n\n",
            )
    return path



def _lock_text(
    rows: list[str] | None = None,
    *,
    schema: str = "mavi-offline-lock-v1",
    variant: str = "linux-x86_64-cpu",
    python_version: str = "3.12.14",
) -> str:
    package_rows = [
        f"av==16.1.0 --hash=sha256:{_HASH_A}",
        f"mavi-vision==0.1.0 --hash=sha256:{_HASH_B}",
        f"mmcv==2.1.0 --hash=sha256:{_HASH_C}",
        f"torch==2.6.0+cpu --hash=sha256:{_HASH_D}",
        f"torchvision==0.21.0+cpu --hash=sha256:{_HASH_E}",
    ] if rows is None else rows
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


def test_freeze_tool_reads_name_and_version_from_wheel_metadata(
    tmp_path: Path,
) -> None:
    tool = _load_freeze_tool()
    wheelhouse = tmp_path / "wheels"
    wheel = _write_wheel(
        wheelhouse,
        filename="renamed-file.whl",
        name="MAVI.Vision",
        version="0.1.0",
    )

    record = tool.inspect_wheel(wheel)

    assert record.name == "mavi-vision"
    assert record.version == "0.1.0"
    assert record.sha256 == tool.sha256_file(wheel)


def test_freeze_tool_is_deterministic_regardless_of_directory_enumeration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = _load_freeze_tool()
    wheelhouse = tmp_path / "wheels"
    first = _write_wheel(
        wheelhouse,
        filename="z.whl",
        name="torch",
        version="2.6.0+cpu",
    )
    second = _write_wheel(
        wheelhouse,
        filename="a.whl",
        name="mavi-vision",
        version="0.1.0",
    )

    original_iterdir = Path.iterdir

    def reversed_iterdir(path: Path):
        items = list(original_iterdir(path))
        return iter(reversed(items))

    monkeypatch.setattr(Path, "iterdir", reversed_iterdir)
    lock = tool.freeze_wheelhouse(
        wheelhouse,
        platform_variant="linux-x86_64-cpu",
        python_version="3.12.14",
    )

    assert [item.name for item in lock.distributions] == [
        "mavi-vision",
        "torch",
    ]
    assert {item.sha256 for item in lock.distributions} == {
        tool.sha256_file(first),
        tool.sha256_file(second),
    }


def test_freeze_tool_rejects_duplicate_distribution_wheels(tmp_path: Path) -> None:
    tool = _load_freeze_tool()
    wheelhouse = tmp_path / "wheels"
    _write_wheel(
        wheelhouse,
        filename="one.whl",
        name="torch",
        version="2.6.0+cpu",
    )
    _write_wheel(
        wheelhouse,
        filename="two.whl",
        name="Torch",
        version="2.6.0+cpu",
    )

    with pytest.raises(tool.FreezeOfflineLockError, match="duplicate_distribution"):
        tool.freeze_wheelhouse(
            wheelhouse,
            platform_variant="linux-x86_64-cpu",
            python_version="3.12.14",
        )


@pytest.mark.parametrize("name", ["package.tar.gz", "package.zip", "README.txt"])
def test_freeze_tool_rejects_non_wheel_entries(
    tmp_path: Path,
    name: str,
) -> None:
    tool = _load_freeze_tool()
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    (wheelhouse / name).write_bytes(b"not-a-wheel")

    with pytest.raises(tool.FreezeOfflineLockError, match="non_wheel_entry"):
        tool.freeze_wheelhouse(
            wheelhouse,
            platform_variant="linux-x86_64-cpu",
            python_version="3.12.14",
        )


def test_freeze_tool_rejects_corrupt_wheel(tmp_path: Path) -> None:
    tool = _load_freeze_tool()
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    (wheelhouse / "broken.whl").write_bytes(b"not-zip")

    with pytest.raises(tool.FreezeOfflineLockError, match="wheel_invalid"):
        tool.freeze_wheelhouse(
            wheelhouse,
            platform_variant="linux-x86_64-cpu",
            python_version="3.12.14",
        )


def test_freeze_tool_rejects_missing_or_duplicate_metadata(tmp_path: Path) -> None:
    tool = _load_freeze_tool()
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()

    missing = wheelhouse / "missing.whl"
    with zipfile.ZipFile(missing, "w") as archive:
        archive.writestr("module.py", "value = 1\n")

    with pytest.raises(tool.FreezeOfflineLockError, match="wheel_metadata_invalid"):
        tool.inspect_wheel(missing)

    missing.unlink()
    duplicate = _write_wheel(
        wheelhouse,
        filename="duplicate.whl",
        name="sample",
        version="1.0.0",
        duplicate_metadata=True,
    )
    with pytest.raises(tool.FreezeOfflineLockError, match="wheel_metadata_invalid"):
        tool.inspect_wheel(duplicate)


def test_freeze_tool_refuses_differing_lock_without_replace(tmp_path: Path) -> None:
    tool = _load_freeze_tool()
    output = tmp_path / "runtime.lock"
    output.write_bytes(b"existing\n")
    lock = OfflineRuntimeLock(
        schema_version="mavi-offline-lock-v1",
        platform_variant="linux-x86_64-cpu",
        python_version="3.12.14",
        distributions=(
            LockedDistribution("mavi-vision", "0.1.0", _HASH_A),
        ),
    )

    with pytest.raises(tool.FreezeOfflineLockError, match="output_differs"):
        tool.write_lock(output, lock, replace=False)

    tool.write_lock(output, lock, replace=True)
    assert output.read_bytes() == serialize_offline_runtime_lock(lock)
