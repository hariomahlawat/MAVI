"""Sampling two objects of 136 answers the question for two objects.

The C2 host investigation hashed all 136 intermediate objects of an MMCV CUDA
build, found all 136 raw hashes differed, then inspected two by hand and
concluded the divergence was metadata. These tests pin the tool that makes that
conclusion mechanical for all of them -- and that fails on the one object in a
hundred and thirty-six that does not reduce.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

import native_binary_fixtures as fixtures


ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tools" / "vision" / "compare_native_object_trees.py"


def _load():
    spec = importlib.util.spec_from_file_location("compare_native_object_trees", TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError("comparator_unloadable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load()


def _tree(root: Path, objects: dict[str, bytes]) -> Path:
    for name, data in objects.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return root


def _build(seed: int, *, count: int = 6) -> dict[str, bytes]:
    """A build's object tree: CUDA objects plus one `/bigobj` CPU object."""
    objects = {
        f"mmcv/ops/csrc/pytorch/cuda/op{index}.obj": fixtures.coff_object(
            timestamp=0x68A00000 + seed, body=bytes([index]) * 256
        )
        for index in range(count)
    }
    objects["mmcv/ops/csrc/pytorch/cpu/active_rotated_filter.obj"] = (
        fixtures.bigobj_object(timestamp=0x68A00000 + seed)
    )
    return objects


def test_a_whole_tree_of_timestamp_only_differences_reduces(tmp_path: Path) -> None:
    left = _tree(tmp_path / "a", _build(1))
    right = _tree(tmp_path / "b", _build(2))

    result = MODULE.compare_object_trees(left, right)

    assert result["verdict"] == "metadata-normalized-identical"
    assert result["comparedCount"] == 7
    assert result["metadataNormalizedCount"] == 7
    assert result["unresolvedCount"] == 0
    assert result["normalizedFieldCounts"] == {
        "bigobj.TimeDateStamp": 1,
        "coff.TimeDateStamp": 6,
    }
    assert result["formatCounts"] == {"bigobj-object": 1, "coff-object": 6}


def test_identical_trees_report_identical(tmp_path: Path) -> None:
    left = _tree(tmp_path / "a", _build(1))
    right = _tree(tmp_path / "b", _build(1))

    result = MODULE.compare_object_trees(left, right)

    assert result["verdict"] == "identical"
    assert result["identicalCount"] == 7
    assert result["metadataNormalizedCount"] == 0


def test_one_divergent_object_among_many_fails_the_whole_tree(tmp_path: Path) -> None:
    """One divergent translation unit is one divergent translation unit."""
    left = _tree(tmp_path / "a", _build(1))
    right_objects = _build(2)
    right_objects["mmcv/ops/csrc/pytorch/cuda/op3.obj"] = fixtures.coff_object(
        timestamp=0x68A00002, body=b"\x03" * 255 + b"\xcc"
    )
    right = _tree(tmp_path / "b", right_objects)

    result = MODULE.compare_object_trees(left, right)

    assert result["verdict"] == "divergent-content"
    assert result["unresolvedCount"] == 1
    assert result["unresolved"][0]["object"] == "mmcv/ops/csrc/pytorch/cuda/op3.obj"
    assert (
        result["unresolved"][0]["analysis"]["classification"]
        == "unexplained-native-difference"
    )


def test_a_bigobj_metadata_field_difference_blocks_the_tree(tmp_path: Path) -> None:
    left_objects = _build(1)
    right_objects = _build(2)
    right_objects["mmcv/ops/csrc/pytorch/cpu/active_rotated_filter.obj"] = (
        fixtures.bigobj_object(timestamp=0x68A00002, metadata_size=0x68A0FFFF)
    )
    result = MODULE.compare_object_trees(
        _tree(tmp_path / "a", left_objects), _tree(tmp_path / "b", right_objects)
    )

    assert result["verdict"] == "divergent-content"
    assert (
        result["unresolved"][0]["analysis"]["classification"]
        == "undocumented-header-field-divergence"
    )


def test_a_missing_object_is_an_inventory_divergence(tmp_path: Path) -> None:
    left_objects = _build(1)
    right_objects = _build(2)
    del right_objects["mmcv/ops/csrc/pytorch/cuda/op0.obj"]

    result = MODULE.compare_object_trees(
        _tree(tmp_path / "a", left_objects), _tree(tmp_path / "b", right_objects)
    )

    assert result["verdict"] == "divergent-inventory"
    assert result["onlyInLeft"] == ["mmcv/ops/csrc/pytorch/cuda/op0.obj"]


def test_non_object_files_are_ignored(tmp_path: Path) -> None:
    left_objects = _build(1)
    left_objects["mmcv/ops/build.log"] = b"left log\n"
    right_objects = _build(2)
    right_objects["mmcv/ops/build.log"] = b"right log, entirely different\n"

    result = MODULE.compare_object_trees(
        _tree(tmp_path / "a", left_objects), _tree(tmp_path / "b", right_objects)
    )

    assert result["verdict"] == "metadata-normalized-identical"
    assert result["comparedCount"] == 7


def test_an_empty_tree_is_refused_rather_than_reported_as_agreement(
    tmp_path: Path,
) -> None:
    """The likeliest cause of an empty tree is the wrong directory.

    Reporting "every object agrees" would be true and would pass the gate.
    """
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "notes.txt").write_text("no objects here")
    right = _tree(tmp_path / "b", _build(1))

    with pytest.raises(MODULE.ObjectTreeError) as excinfo:
        MODULE.compare_object_trees(tmp_path / "a", right)
    assert excinfo.value.code.startswith("object_tree_empty:")


def test_a_missing_tree_is_refused(tmp_path: Path) -> None:
    right = _tree(tmp_path / "b", _build(1))
    with pytest.raises(MODULE.ObjectTreeError) as excinfo:
        MODULE.compare_object_trees(tmp_path / "nope", right)
    assert excinfo.value.code.startswith("object_tree_missing:")


def test_a_symlinked_object_is_not_compared(tmp_path: Path) -> None:
    left = _tree(tmp_path / "a", _build(1))
    right = _tree(tmp_path / "b", _build(2))
    try:
        (left / "mmcv" / "ops" / "link.obj").symlink_to(
            left / "mmcv" / "ops" / "csrc" / "pytorch" / "cuda" / "op0.obj"
        )
    except (OSError, NotImplementedError):  # pragma: no cover - platform dependent
        pytest.skip("symlinks unavailable")

    result = MODULE.compare_object_trees(left, right)

    assert result["comparedCount"] == 7
    assert result["verdict"] == "metadata-normalized-identical"


def _run_cli(left: Path, right: Path, require: str | None) -> int:
    argv = sys.argv
    sys.argv = [
        "compare_native_object_trees.py",
        "--left",
        str(left),
        "--right",
        str(right),
    ] + ([] if require is None else ["--require", require])
    try:
        return MODULE.main()
    finally:
        sys.argv = argv


def test_the_require_tiers_are_distinct(tmp_path: Path) -> None:
    left = _tree(tmp_path / "a", _build(1))
    right = _tree(tmp_path / "b", _build(2))

    assert _run_cli(left, right, "identical") == 3
    assert _run_cli(left, right, "normalized-identical") == 0
    assert _run_cli(left, right, None) == 0


def test_a_divergent_tree_fails_the_relaxed_tier_too(tmp_path: Path) -> None:
    right_objects = _build(2)
    right_objects["mmcv/ops/csrc/pytorch/cuda/op1.obj"] = fixtures.coff_object(
        timestamp=0x68A00002, body=b"\x01" * 255 + b"\xcc"
    )
    left = _tree(tmp_path / "a", _build(1))
    right = _tree(tmp_path / "b", right_objects)

    assert _run_cli(left, right, "normalized-identical") == 3


def test_the_report_refuses_to_overwrite_an_existing_file(tmp_path: Path) -> None:
    left = _tree(tmp_path / "a", _build(1))
    right = _tree(tmp_path / "b", _build(2))
    output = tmp_path / "report.json"
    output.write_text("{}")

    argv = sys.argv
    sys.argv = [
        "compare_native_object_trees.py",
        "--left",
        str(left),
        "--right",
        str(right),
        "--output",
        str(output),
    ]
    try:
        assert MODULE.main() == 2
    finally:
        sys.argv = argv
    assert output.read_text() == "{}"


def test_the_written_report_is_canonical_json(tmp_path: Path) -> None:
    left = _tree(tmp_path / "a", _build(1))
    right = _tree(tmp_path / "b", _build(2))
    output = tmp_path / "report.json"

    argv = sys.argv
    sys.argv = [
        "compare_native_object_trees.py",
        "--left",
        str(left),
        "--right",
        str(right),
        "--output",
        str(output),
    ]
    try:
        assert MODULE.main() == 0
    finally:
        sys.argv = argv

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schemaVersion"] == "mavi-native-object-tree-comparison-v1"
    assert payload["verdict"] == "metadata-normalized-identical"
    assert "Production" in payload["note"]


def test_an_import_library_is_not_compared_as_an_object(tmp_path: Path) -> None:
    """MSVC drops `_ext.lib` into the same temp directory as the objects.

    An archive has its own container format, so parsing it as a COFF object
    fails -- and a fail-closed parser turns that into a divergent verdict on
    every single run, for a file the compiler did not write. It is listed as
    out of scope instead, which keeps "we did not look at that" visible.
    """
    left_objects = _build(1)
    left_objects["mmcv/ops/_ext.cp312-win_amd64.lib"] = b"!<arch>\nleft-archive"
    right_objects = _build(2)
    right_objects["mmcv/ops/_ext.cp312-win_amd64.lib"] = b"!<arch>\nright-archive"

    result = MODULE.compare_object_trees(
        _tree(tmp_path / "a", left_objects), _tree(tmp_path / "b", right_objects)
    )

    assert result["verdict"] == "metadata-normalized-identical"
    assert result["comparedCount"] == 7
    assert result["outOfScopeNativeFiles"]["left"] == [
        "mmcv/ops/_ext.cp312-win_amd64.lib"
    ]
    assert result["outOfScopeNativeFiles"]["right"] == [
        "mmcv/ops/_ext.cp312-win_amd64.lib"
    ]


def test_out_of_scope_files_are_named_not_merely_counted(tmp_path: Path) -> None:
    left_objects = _build(1)
    for name in ("mmcv/ops/_ext.exp", "mmcv/ops/_ext.pdb", "mmcv/ops/_ext.pyd"):
        left_objects[name] = b"whatever"
    result = MODULE.compare_object_trees(
        _tree(tmp_path / "a", left_objects), _tree(tmp_path / "b", _build(2))
    )

    assert result["outOfScopeNativeFiles"]["left"] == [
        "mmcv/ops/_ext.exp",
        "mmcv/ops/_ext.pdb",
        "mmcv/ops/_ext.pyd",
    ]
    assert result["outOfScopeNativeFiles"]["right"] == []


def test_a_shared_parser_gap_is_summarised_not_buried(tmp_path: Path) -> None:
    """129 objects sharing one parser gap is a different situation from 129
    divergent objects, and the report has to say which without the reader
    opening every entry.
    """
    left_objects = {
        f"mmcv/ops/cpu/op{index}.obj": fixtures.bigobj_object(
            version=1, timestamp=0x68A00001, body=bytes([index]) * 128
        )
        for index in range(30)
    }
    right_objects = {
        f"mmcv/ops/cpu/op{index}.obj": fixtures.bigobj_object(
            version=1, timestamp=0x68A00999, body=bytes([index]) * 128
        )
        for index in range(30)
    }
    result = MODULE.compare_object_trees(
        _tree(tmp_path / "a", left_objects), _tree(tmp_path / "b", right_objects)
    )

    assert result["verdict"] == "divergent-content"
    assert result["unresolvedCount"] == 30
    assert result["unresolvedReasonCounts"] == {
        "bigobj_anon_object_header_unsupported": 30
    }
    signatures = result["unresolvedHeaderSignatures"]
    assert len(signatures) == 1
    signature, count = next(iter(signatures.items()))
    assert count == 30
    assert "version=1" in signature
    assert "D1BAA1C7" in signature


def test_a_parser_gap_is_never_reported_as_agreement(tmp_path: Path) -> None:
    """Fail-closed: an unsupported variant must not pass as reproducible."""
    objects = {
        "mmcv/ops/cpu/op0.obj": fixtures.bigobj_object(version=1, timestamp=1),
    }
    other = {
        "mmcv/ops/cpu/op0.obj": fixtures.bigobj_object(version=1, timestamp=2),
    }
    result = MODULE.compare_object_trees(
        _tree(tmp_path / "a", objects), _tree(tmp_path / "b", other)
    )
    assert result["verdict"] == "divergent-content"
    assert result["metadataNormalizedCount"] == 0
