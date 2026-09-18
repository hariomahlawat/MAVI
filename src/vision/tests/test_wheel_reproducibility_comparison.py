"""The C2 reproducibility experiment must give a measured answer, not a hoped one.

Every wheel in these tests is synthesised in-test, so the cases are independent
of any artefact on disk and of the repository's current state.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
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
    mode: int = 0o644,
    compress_type: int = zipfile.ZIP_DEFLATED,
    include_record: bool = True,
    record_body: str | None = None,
    duplicate: tuple[str, bytes] | None = None,
    reverse_order: bool = False,
    comment: bytes = b"",
) -> Path:
    lines = []
    ordered = list(reversed(members)) if reverse_order else list(members)
    with zipfile.ZipFile(path, "w", compress_type) as archive:
        if duplicate is not None:
            info = zipfile.ZipInfo(duplicate[0], date_time=date_time)
            info.external_attr = mode << 16
            archive.writestr(info, duplicate[1], compress_type=compress_type)
        for name, data in ordered:
            info = zipfile.ZipInfo(name, date_time=date_time)
            info.external_attr = mode << 16
            archive.writestr(info, data, compress_type=compress_type)
        # RECORD follows the declared order, not the write order, so varying
        # entry order varies the container alone.
        for name, data in members:
            lines.append(_record_line(name, data))
        if include_record:
            body = (
                record_body
                if record_body is not None
                else "\n".join(lines) + "\nmmcv-2.1.0.dist-info/RECORD,,\n"
            )
            info = zipfile.ZipInfo(
                "mmcv-2.1.0.dist-info/RECORD", date_time=date_time
            )
            info.external_attr = mode << 16
            archive.writestr(info, body.encode(), compress_type=compress_type)
        if comment:
            archive.comment = comment
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


def test_record_is_not_double_counted_alongside_a_real_difference(
    tmp_path: Path,
) -> None:
    """RECORD restates the other members, so it must not double-count.

    The dangerous converse -- RECORD differing alone -- is covered separately.
    """
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

    embedded = result["embeddedBuildPaths"]["right"]
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


def test_a_record_only_difference_is_divergent(tmp_path: Path) -> None:
    """RECORD can disagree with the members it lists, and that is installable.

    RECORD differs whenever the members do, but not only then. A stale or wrong
    RECORD changes what pip verifies and what pip uninstall removes.
    """
    module = _load()
    members = _base_members()
    left = _wheel(tmp_path / "a.whl", members=members)
    right = _wheel(
        tmp_path / "b.whl",
        members=members,
        record_body="mmcv/__init__.py,sha256=deadbeef,7\nmmcv-2.1.0.dist-info/RECORD,,\n",
    )

    result = module.compare_wheels(left, right)

    assert result["verdict"] == "divergent-content"
    assert "record-metadata" in result["varianceSources"]
    assert result["recordDiffers"] == ["mmcv-2.1.0.dist-info/RECORD"]
    assert result["contentDiffers"] == []


def test_a_duplicate_member_is_refused(tmp_path: Path) -> None:
    """Installers disagree on which copy wins, so the artefact is defective."""
    module = _load()
    left = _wheel(tmp_path / "a.whl", members=_base_members())
    right = _wheel(
        tmp_path / "b.whl",
        members=_base_members(),
        duplicate=("mmcv/__init__.py", b"shadowed\n"),
    )

    with pytest.raises(module.WheelComparisonError, match="wheel_duplicate_member"):
        module.compare_wheels(left, right)


def test_a_permission_difference_is_divergent(tmp_path: Path) -> None:
    """The executable bit and the symlink bit live in the mode."""
    module = _load()
    left = _wheel(tmp_path / "a.whl", members=_base_members(), mode=0o644)
    right = _wheel(tmp_path / "b.whl", members=_base_members(), mode=0o755)

    result = module.compare_wheels(left, right)

    assert result["verdict"] == "divergent-content"
    assert "member-permissions" in result["varianceSources"]
    assert result["permissionDiffers"]
    assert result["contentDiffers"] == []


def test_a_compression_difference_is_container_only(tmp_path: Path) -> None:
    """Compression changes the archive, not the installed bytes -- but say so."""
    module = _load()
    left = _wheel(tmp_path / "a.whl", members=_base_members())
    right = _wheel(
        tmp_path / "b.whl", members=_base_members(), compress_type=zipfile.ZIP_STORED
    )

    result = module.compare_wheels(left, right)

    assert result["verdict"] == "semantically-identical"
    assert "compression-method" in result["varianceSources"]
    assert result["compressionDiffers"]


def test_an_entry_order_difference_is_named(tmp_path: Path) -> None:
    module = _load()
    left = _wheel(tmp_path / "a.whl", members=_base_members())
    right = _wheel(tmp_path / "b.whl", members=_base_members(), reverse_order=True)

    result = module.compare_wheels(left, right)

    assert result["verdict"] == "semantically-identical"
    assert "entry-order" in result["varianceSources"]
    assert result["entryOrderDiffers"] is True


def test_an_archive_comment_difference_is_named(tmp_path: Path) -> None:
    module = _load()
    left = _wheel(tmp_path / "a.whl", members=_base_members())
    right = _wheel(tmp_path / "b.whl", members=_base_members(), comment=b"built-by-ci")

    result = module.compare_wheels(left, right)

    assert result["verdict"] == "semantically-identical"
    assert "archive-comment" in result["varianceSources"]
    assert result["archiveCommentDiffers"] is True


def test_identical_embedded_build_paths_are_still_reported(tmp_path: Path) -> None:
    """The expected C2 shape: two builds from one directory, byte-identical.

    Scanning only differing members would report nothing precisely when the
    non-relocatability exists.
    """
    module = _load()
    members = _base_members()
    members[1] = (
        "mmcv/_ext.pyd",
        b"MZ" + b"\x00" * 8 + rb"D:\a\mmcv\mmcv\mmcv\ops\csrc\nms_cuda.cu" + b"\x00" * 8,
    )
    left = _wheel(tmp_path / "a.whl", members=members)
    right = _wheel(tmp_path / "b.whl", members=members)

    result = module.compare_wheels(left, right)

    assert result["verdict"] == "byte-identical"
    embedded = result["embeddedBuildPaths"]
    assert "mmcv/_ext.pyd" in embedded["left"]
    assert "mmcv/_ext.pyd" in embedded["identicalInBoth"]
    assert any("mmcv" in item for item in embedded["left"]["mmcv/_ext.pyd"])


@pytest.mark.parametrize(
    "embedded",
    [
        rb"D:\a\mmcv\mmcv\setup.py",
        rb"C:\hostedtoolcache\windows\Python\3.12.10\x64\include\Python.h",
        rb"C:\Users\builder\work\mmcv\_ext.cpp",
        b"/opt/conda/lib/python3.12/site-packages/torch/include",
        b"/home/runner/work/mmcv/mmcv/build",
    ],
)
def test_real_ci_build_paths_are_detected(tmp_path: Path, embedded: bytes) -> None:
    """The GitHub Windows runner workspace is D:\\a\\<repo>; an allow-list misses it."""
    module = _load()
    members = _base_members()
    members[1] = ("mmcv/_ext.pyd", b"MZ" + b"\x00" * 8 + embedded + b"\x00" * 8)
    left = _wheel(tmp_path / "a.whl", members=members)
    right = _wheel(tmp_path / "b.whl", members=members)

    result = module.compare_wheels(left, right)

    assert result["embeddedBuildPaths"]["left"].get("mmcv/_ext.pyd")


def test_only_in_left_is_reported(tmp_path: Path) -> None:
    module = _load()
    left = _wheel(
        tmp_path / "a.whl",
        members=_base_members() + [("mmcv/extra.py", b"# extra\n")],
    )
    right = _wheel(tmp_path / "b.whl", members=_base_members())

    result = module.compare_wheels(left, right)

    assert result["verdict"] == "divergent-inventory"
    assert result["onlyInLeft"] == ["mmcv/extra.py"]
    assert result["onlyInRight"] == []


def test_a_corrupt_member_fails_closed_with_a_code(tmp_path: Path) -> None:
    """A valid directory over a damaged payload must not escape as a traceback."""
    module = _load()
    left = _wheel(tmp_path / "a.whl", members=_base_members())
    right_path = _wheel(tmp_path / "b.whl", members=_base_members())
    raw = bytearray(right_path.read_bytes())
    # Locate the first local file header and flip a byte inside its payload,
    # so the central directory stays valid but the member fails its CRC.
    start = raw.index(b"PK\x03\x04")
    name_length = int.from_bytes(raw[start + 26 : start + 28], "little")
    extra_length = int.from_bytes(raw[start + 28 : start + 30], "little")
    payload = start + 30 + name_length + extra_length
    raw[payload + 2] ^= 0xFF
    right_path.write_bytes(bytes(raw))

    with pytest.raises(module.WheelComparisonError, match="wheel_"):
        module.compare_wheels(left, right_path)


@pytest.mark.parametrize("suffix", [".PYD", ".DLL", ".Pyd"])
def test_native_members_are_recognised_case_insensitively(
    tmp_path: Path, suffix: str
) -> None:
    module = _load()
    members = [("mmcv/_ext" + suffix, b"MZ" + b"\x01" * 32)] + _base_members()[2:]
    mutated = list(members)
    mutated[0] = ("mmcv/_ext" + suffix, b"MZ" + b"\x02" * 32)
    left = _wheel(tmp_path / "a.whl", members=members)
    right = _wheel(tmp_path / "b.whl", members=mutated)

    result = module.compare_wheels(left, right)

    assert "native-binary-content" in result["varianceSources"]


@pytest.mark.parametrize(
    ("require", "expected"),
    [("byte-identical", 3), ("semantically-identical", 3)],
)
def test_require_rejects_a_divergent_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    require: str,
    expected: int,
) -> None:
    module = _load()
    members = _base_members()
    mutated = list(members)
    mutated[1] = ("mmcv/_ext.pyd", members[1][1][:-1] + b"\x02")
    left = _wheel(tmp_path / "a.whl", members=members)
    right = _wheel(tmp_path / "b.whl", members=mutated)
    monkeypatch.setattr(
        "sys.argv",
        [
            "compare_wheel_reproducibility.py",
            "--left", str(left), "--right", str(right), "--require", require,
        ],
    )

    assert module.main() == expected


def test_output_file_is_written_and_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    left = _wheel(tmp_path / "a.whl", members=_base_members())
    right = _wheel(tmp_path / "b.whl", members=_base_members())
    output = tmp_path / "comparison.json"
    argv = [
        "compare_wheel_reproducibility.py",
        "--left", str(left), "--right", str(right), "--output", str(output),
    ]
    monkeypatch.setattr("sys.argv", argv)

    assert module.main() == 0
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["verdict"] == "byte-identical"

    monkeypatch.setattr("sys.argv", argv)
    assert module.main() == 2
