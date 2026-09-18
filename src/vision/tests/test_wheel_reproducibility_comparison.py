"""The C2 reproducibility experiment must give a measured answer, not a hoped one.

Every wheel in these tests is synthesised in-test, so the cases are independent
of any artefact on disk and of the repository's current state.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tools" / "vision" / "compare_wheel_reproducibility.py"

_EPOCH = (1980, 1, 1, 0, 0, 0)
_LATER = (2026, 9, 18, 12, 0, 0)


def _load():
    spec = importlib.util.spec_from_file_location("compare_wheel", TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError("comparator_unloadable")
    module = importlib.util.module_from_spec(spec)
    # Slotted dataclasses resolve their module during class creation, so the
    # module must be registered before it is executed.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _record_line(name: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return f"{name},sha256={digest.decode()},{len(data)}"


def _wheel(
    path: Path,
    *,
    members: list[tuple[str, bytes]],
    date_time: tuple[int, int, int, int, int, int] = _EPOCH,
) -> Path:
    lines = []
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members:
            info = zipfile.ZipInfo(name, date_time=date_time)
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
            lines.append(_record_line(name, data))
        record = "\n".join(lines) + "\nmmcv-2.1.0.dist-info/RECORD,,\n"
        archive.writestr(
            zipfile.ZipInfo("mmcv-2.1.0.dist-info/RECORD", date_time=date_time),
            record.encode(),
        )
    return path


def _base_members() -> list[tuple[str, bytes]]:
    return [
        ("mmcv/__init__.py", b"__version__ = '2.1.0'\n"),
        ("mmcv/_ext.pyd", b"MZ" + b"\x00" * 64 + b"cudart64_12.dll\x00" + b"\x01" * 128),
        (
            "mmcv-2.1.0.dist-info/METADATA",
            b"Metadata-Version: 2.1\nName: mmcv\nVersion: 2.1.0\n",
        ),
        (
            "mmcv-2.1.0.dist-info/WHEEL",
            b"Wheel-Version: 1.0\nTag: cp312-cp312-win_amd64\n",
        ),
    ]


def test_identical_builds_are_byte_identical(tmp_path: Path) -> None:
    module = _load()
    left = _wheel(tmp_path / "a.whl", members=_base_members())
    right = _wheel(tmp_path / "b.whl", members=_base_members())

    result = module.compare_wheels(left, right)

    assert result["verdict"] == "byte-identical"
    assert result["byteIdentical"] is True
    assert result["varianceSources"] == []
    assert result["left"]["sha256"] == result["right"]["sha256"]


def test_timestamp_variance_is_semantically_identical(tmp_path: Path) -> None:
    """Archive timestamps change nothing that gets installed."""
    module = _load()
    left = _wheel(tmp_path / "a.whl", members=_base_members())
    right = _wheel(tmp_path / "b.whl", members=_base_members(), date_time=_LATER)

    result = module.compare_wheels(left, right)

    assert result["verdict"] == "semantically-identical"
    assert result["byteIdentical"] is False
    assert result["varianceSources"] == ["archive-timestamps"]
    assert result["contentDiffers"] == []
    assert result["timestampOnlyDiffers"]


def test_native_payload_variance_is_divergent(tmp_path: Path) -> None:
    """A different native extension is never cosmetic."""
    module = _load()
    members = _base_members()
    left = _wheel(tmp_path / "a.whl", members=members)
    mutated = list(members)
    mutated[1] = ("mmcv/_ext.pyd", members[1][1][:-1] + b"\x02")
    right = _wheel(tmp_path / "b.whl", members=mutated)

    result = module.compare_wheels(left, right)

    assert result["verdict"] == "divergent-content"
    assert "native-binary-content" in result["varianceSources"]
    assert result["nativeContentDiffers"] == ["mmcv/_ext.pyd"]


def test_metadata_variance_is_divergent(tmp_path: Path) -> None:
    module = _load()
    members = _base_members()
    left = _wheel(tmp_path / "a.whl", members=members)
    mutated = list(members)
    mutated[2] = (
        "mmcv-2.1.0.dist-info/METADATA",
        b"Metadata-Version: 2.1\nName: mmcv\nVersion: 2.1.1\n",
    )
    right = _wheel(tmp_path / "b.whl", members=mutated)

    result = module.compare_wheels(left, right)

    assert result["verdict"] == "divergent-content"
    assert "distribution-metadata" in result["varianceSources"]


def test_member_inventory_variance_is_divergent(tmp_path: Path) -> None:
    module = _load()
    left = _wheel(tmp_path / "a.whl", members=_base_members())
    right = _wheel(
        tmp_path / "b.whl",
        members=_base_members() + [("mmcv/extra.py", b"# stray\n")],
    )

    result = module.compare_wheels(left, right)

    assert result["verdict"] == "divergent-inventory"
    assert result["onlyInRight"] == ["mmcv/extra.py"]
    assert "member-inventory" in result["varianceSources"]


def test_record_alone_is_not_reported_as_an_independent_difference(
    tmp_path: Path,
) -> None:
    """RECORD restates the other members, so it must not double-count."""
    module = _load()
    members = _base_members()
    left = _wheel(tmp_path / "a.whl", members=members)
    mutated = list(members)
    mutated[1] = ("mmcv/_ext.pyd", members[1][1][:-1] + b"\x02")
    right = _wheel(tmp_path / "b.whl", members=mutated)

    result = module.compare_wheels(left, right)

    assert not any("RECORD" in name for name in result["contentDiffers"])
    assert result["nativeContentDiffers"] == ["mmcv/_ext.pyd"]


def test_embedded_build_paths_are_surfaced(tmp_path: Path) -> None:
    """Absolute build paths defeat relocatable reproduction, so name them."""
    module = _load()
    members = _base_members()
    left = _wheel(tmp_path / "a.whl", members=members)
    mutated = list(members)
    mutated[1] = (
        "mmcv/_ext.pyd",
        b"MZ" + b"\x00" * 16 + rb"C:\Users\builder\work\mmcv\_ext.cpp" + b"\x00" * 16,
    )
    right = _wheel(tmp_path / "b.whl", members=mutated)

    result = module.compare_wheels(left, right)

    embedded = result["embeddedBuildPaths"]
    assert "mmcv/_ext.pyd" in embedded
    assert any("builder" in item for item in embedded["mmcv/_ext.pyd"])


def test_missing_and_invalid_wheels_fail_closed(tmp_path: Path) -> None:
    module = _load()
    present = _wheel(tmp_path / "a.whl", members=_base_members())
    absent = tmp_path / "nope.whl"
    corrupt = tmp_path / "corrupt.whl"
    corrupt.write_bytes(b"not a zip")

    with pytest.raises(module.WheelComparisonError, match="wheel_missing"):
        module.compare_wheels(present, absent)
    with pytest.raises(module.WheelComparisonError, match="wheel_invalid_zip"):
        module.compare_wheels(present, corrupt)


@pytest.mark.parametrize(
    ("require", "expected"),
    [("byte-identical", 3), ("semantically-identical", 0)],
)
def test_require_threshold_gates_the_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    require: str,
    expected: int,
) -> None:
    """A timestamp-only build satisfies the weaker contract, not the stronger."""
    module = _load()
    left = _wheel(tmp_path / "a.whl", members=_base_members())
    right = _wheel(tmp_path / "b.whl", members=_base_members(), date_time=_LATER)
    monkeypatch.setattr(
        "sys.argv",
        [
            "compare_wheel_reproducibility.py",
            "--left",
            str(left),
            "--right",
            str(right),
            "--require",
            require,
        ],
    )

    assert module.main() == expected


def test_comparison_never_claims_qualification(tmp_path: Path) -> None:
    module = _load()
    left = _wheel(tmp_path / "a.whl", members=_base_members())
    right = _wheel(tmp_path / "b.whl", members=_base_members())

    note = module.compare_wheels(left, right)["note"].casefold()

    assert "not a runtime, hardware or production qualification" in note
