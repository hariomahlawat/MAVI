"""Release descriptor and source manifest (S3.2d-1 plan §5, §11 prepare, §14)."""

from __future__ import annotations

import copy
import os
import shutil
from fractions import Fraction
from pathlib import Path

import pytest

from tools.benchmarks.core import descriptor as d
from tools.benchmarks.core.identity import S32Error, canonical_json, document_sha256
from tools.benchmarks.datasets import synthetic as s


def refused(code: str):
    return pytest.raises(S32Error, match=f"^{code}")


def test_synthetic_descriptor_is_valid_and_unfrozen():
    document = s.descriptor()
    assert document["manifest"]["entries"] == []
    assert d.native_classes(document) == ["bus", "car", "motorcycle", "pedestrian", "truck", "van"]
    assert d.split(document, "val")["labelled"] is True


@pytest.mark.parametrize("edit, code", [
    (lambda doc: doc.update(datasetId="Not A Slug"), "descriptor_invalid:schema:datasetId"),
    (lambda doc: doc["researchUse"].update(status="MAYBE"), "descriptor_invalid:schema:researchUse/status"),
    (lambda doc: doc["researchUse"].update(redistribution="permitted"), "descriptor_invalid:schema"),
    (lambda doc: doc.update(intendedUse="production"), "descriptor_invalid:schema:intendedUse"),
    (lambda doc: doc["source"].update(kind="research-mirror"), "descriptor_invalid:schema:source"),
    (lambda doc: doc["frameTime"].pop("fpsNumerator"), "descriptor_invalid:schema:frameTime"),
    (lambda doc: doc["nativeTaxonomy"].append(dict(doc["nativeTaxonomy"][0])),
     "descriptor_invalid:duplicate_native_class"),
    (lambda doc: doc["nativeTaxonomy"].clear(), "descriptor_invalid:schema:nativeTaxonomy"),
    (lambda doc: doc["nativeTaxonomy"][0].pop("definition"), "descriptor_invalid:schema:nativeTaxonomy/0"),
    (lambda doc: doc["splits"].append(dict(doc["splits"][0])), "descriptor_invalid:duplicate_split"),
    (lambda doc: doc.update(extra=1), "descriptor_invalid:schema"),
    (lambda doc: doc["exposure"].update(status="perhaps"), "descriptor_invalid:schema:exposure/status"),
])
def test_invalid_descriptors_are_refused(edit, code):
    document = copy.deepcopy(s.descriptor())
    edit(document)
    with refused(code):
        d.check(document)


def test_non_official_source_needs_a_credibility_basis():
    document = copy.deepcopy(s.descriptor())
    document["source"].update(kind="research-mirror", credibilityBasis="Author-maintained mirror of the release.")
    d.check(document)


def test_per_frame_timestamps_need_no_rate():
    document = copy.deepcopy(s.descriptor())
    document["frameTime"] = {"kind": "per-frame-timestamp"}
    d.check(document)
    with refused("descriptor_invalid:frame_time_kind"):
        d.index_offset_ms(document, 1)


def test_frame_rate_must_be_in_lowest_terms():
    document = copy.deepcopy(s.descriptor())
    document["frameTime"].update(fpsNumerator=10, fpsDenominator=2)  # same instants as 5/1, another hash
    with refused("descriptor_invalid:frame_rate_not_lowest_terms$"):
        d.check(document)
    document["frameTime"].update(fpsNumerator=30000, fpsDenominator=1001)
    d.check(document)


def test_index_frame_times_are_exact_rationals():
    document = copy.deepcopy(s.descriptor())
    assert d.index_offset_ms(document, 3) == 600
    document["frameTime"].update(fpsNumerator=30000, fpsDenominator=1001)
    assert d.index_offset_ms(document, 1) == Fraction(1001, 30)
    document["frameTime"].update(fpsNumerator=30, fpsDenominator=1)
    assert d.index_offset_ms(document, 1) == Fraction(100, 3)


def test_blocked_release_is_refused_everywhere(source):
    document = copy.deepcopy(s.descriptor())
    document["researchUse"]["status"] = "BLOCKED"
    with refused("descriptor_blocked"):
        d.require_usable(document)
    with refused("descriptor_blocked"):
        d.freeze(document, source)
    frozen = d.freeze(s.descriptor(), source)
    frozen["researchUse"]["status"] = "BLOCKED"
    with refused("descriptor_blocked"):
        d.reconcile(frozen, source)


def test_uncertain_release_is_usable_for_development():
    document = copy.deepcopy(s.descriptor())
    document["researchUse"]["status"] = "RESEARCH-UNCERTAIN"
    d.require_usable(document)


def test_freeze_lists_every_file_sorted_with_size_and_hash(frozen):
    import hashlib

    entries = frozen["manifest"]["entries"]
    expected = s.source_files()
    assert [entry["path"] for entry in entries] == sorted(expected)
    for entry in entries:
        assert entry["sizeBytes"] == len(expected[entry["path"]])
        assert entry["sha256"] == hashlib.sha256(expected[entry["path"]]).hexdigest()


def test_freeze_is_deterministic_and_order_independent(tmp_path):
    first = s.write_source(tmp_path / "one")
    second = tmp_path / "two"
    for relative, data in sorted(s.source_files().items(), reverse=True):  # created in the opposite order
        (second / relative).parent.mkdir(parents=True, exist_ok=True)
        (second / relative).write_bytes(data)
    a, b = d.freeze(s.descriptor(), first), d.freeze(s.descriptor(), second)
    assert canonical_json(a) == canonical_json(b)
    assert document_sha256(a) == document_sha256(b)


def test_manifest_paths_are_posix_relative(frozen):
    for entry in frozen["manifest"]["entries"]:
        assert "\\" not in entry["path"] and not entry["path"].startswith("/") and ":" not in entry["path"]


def test_unsorted_or_windows_manifest_paths_are_refused(frozen):
    reordered = copy.deepcopy(frozen)
    reordered["manifest"]["entries"].reverse()
    with refused("descriptor_invalid:manifest_order"):
        d.check(reordered)
    windows = copy.deepcopy(frozen)
    windows["manifest"]["entries"][0]["path"] = windows["manifest"]["entries"][0]["path"].replace("/", "\\")
    with refused("descriptor_invalid"):
        d.check(windows)


def test_freeze_refuses_a_frozen_descriptor_and_an_empty_source(source, frozen, tmp_path):
    with refused("descriptor_invalid:manifest_already_frozen"):
        d.freeze(frozen, source)
    (tmp_path / "empty").mkdir()
    with refused("source_manifest_missing"):
        d.freeze(s.descriptor(), tmp_path / "empty")


def test_freeze_does_not_modify_its_input(source):
    document = s.descriptor()
    before = canonical_json(document)
    d.freeze(document, source)
    assert canonical_json(document) == before


def test_archive_manifest_kind_is_refused_not_treated_as_a_file_tree(source, frozen):
    assert frozen["manifest"]["kind"] == "file-hashes"  # file-hashes freezes and reconciles normally
    d.reconcile(frozen, source)
    unfrozen = copy.deepcopy(s.descriptor())
    unfrozen["manifest"]["kind"] = "archive-hashes"
    d.check(unfrozen)  # the v1 contract still names the kind
    with refused("descriptor_invalid:manifest_kind_unsupported$"):
        d.freeze(unfrozen, source)
    relabelled = copy.deepcopy(frozen)
    relabelled["manifest"]["kind"] = "archive-hashes"
    with refused("descriptor_invalid:manifest_kind_unsupported$"):
        d.reconcile(relabelled, source)


def test_reconcile_accepts_the_exact_source(source, frozen):
    entries = d.reconcile(frozen, source)
    assert sorted(entries) == sorted(s.source_files())


def test_unfrozen_descriptor_cannot_be_reconciled(source):
    with refused("source_manifest_missing$"):
        d.reconcile(s.descriptor(), source)


def test_missing_member_is_incomplete_even_if_nothing_would_read_it(source, frozen):
    # An annotation file and its whole frame directory removed together: no adapter path would touch them.
    (source / s.annotation_path("val", "seq-b")).unlink()
    shutil.rmtree(source / "frames" / "val" / "seq-b")
    with refused("source_manifest_incomplete:annotations/val/seq-b.json$"):
        d.reconcile(frozen, source)


def test_member_of_another_split_is_reconciled_too(source, frozen):
    (source / s.frame_path("train", "seq-c", 2)).unlink()
    with refused("source_manifest_incomplete:frames/train/seq-c/000002.ppm$"):
        d.reconcile(frozen, source)


def test_changed_bytes_are_a_mismatch(source, frozen):
    path = source / s.frame_path("val", "seq-a", 4)
    data = bytearray(path.read_bytes())
    data[-1] ^= 1  # same size, one bit
    path.write_bytes(bytes(data))
    with refused("source_manifest_mismatch:frames/val/seq-a/000004.ppm$"):
        d.reconcile(frozen, source)


def test_changed_size_is_a_mismatch(source, frozen):
    path = source / s.annotation_path("val", "seq-a")
    path.write_bytes(path.read_bytes() + b" ")
    with refused("source_manifest_mismatch:annotations/val/seq-a.json$"):
        d.reconcile(frozen, source)


def test_unexpected_file_is_refused(source, frozen):
    (source / "frames" / "val" / "seq-a" / "extra.ppm").write_bytes(b"P6\n1 1\n255\n\0\0\0")
    with refused("source_manifest_unexpected:frames/val/seq-a/extra.ppm$"):
        d.reconcile(frozen, source)


def test_refusal_order_is_incomplete_then_unexpected_then_mismatch(source, frozen):
    (source / "zzz.txt").write_bytes(b"x")
    path = source / s.frame_path("val", "seq-a", 0)
    path.write_bytes(path.read_bytes()[:-1] + b"\1")
    with refused("source_manifest_unexpected"):
        d.reconcile(frozen, source)
    (source / s.frame_path("val", "seq-b", 0)).unlink()
    with refused("source_manifest_incomplete"):
        d.reconcile(frozen, source)


def test_symbolic_links_are_never_followed(source, frozen, tmp_path):
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    link = source / "link.bin"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available to this account")
    with refused("source_root_invalid:link.bin$"):
        d.reconcile(frozen, source)


def test_an_unlistable_directory_is_a_refusal_not_a_silent_omission(source, frozen, monkeypatch):
    import os

    blocked = (source / "frames" / "val" / "seq-b").resolve()
    real_scandir = os.scandir

    def scandir(path="."):
        if Path(os.fsdecode(path)).resolve() == blocked:
            raise PermissionError(13, "Permission denied", os.fsdecode(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)
    with refused("source_root_invalid:frames/val/seq-b$"):
        d.reconcile(frozen, source)
    with refused("source_root_invalid:frames/val/seq-b$"):
        d.manifest_entries(source)


@pytest.mark.parametrize("error", [PermissionError(13, "Permission denied"), FileNotFoundError(2, "Vanished")])
def test_a_listed_but_unreadable_file_is_a_refusal(source, frozen, monkeypatch, error):
    blocked = (source / s.frame_path("val", "seq-a", 1)).resolve()
    real_open = open

    def guarded_open(path, *args, **kwargs):
        if Path(path).resolve() == blocked:
            raise error
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(d, "open", guarded_open, raising=False)
    with refused("source_root_invalid:frames/val/seq-a/000001.ppm$"):
        d.reconcile(frozen, source)
    with refused("source_root_invalid:frames/val/seq-a/000001.ppm$"):
        d.freeze(s.descriptor(), source)


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0,
                    reason="POSIX permissions only; root can list any directory")
def test_a_really_unreadable_directory_is_refused(source, frozen):
    directory = source / "frames" / "val" / "seq-a"
    directory.chmod(0)
    try:
        with refused("source_root_invalid:frames/val/seq-a$"):
            d.reconcile(frozen, source)
    finally:
        directory.chmod(0o755)


def test_read_verified_rechecks_bytes_after_reconcile(source, frozen):
    entries = d.reconcile(frozen, source)
    relative = s.annotation_path("val", "seq-a")
    assert d.read_verified(entries, source, relative) == s.source_files()[relative]
    (source / relative).write_bytes(b"{}")
    with refused(f"source_manifest_mismatch:{relative}$"):
        d.read_verified(entries, source, relative)
    with refused("source_manifest_unexpected:not/listed.json$"):
        d.read_verified(entries, source, "not/listed.json")


def test_descriptor_file_round_trip(tmp_path, frozen):
    path = tmp_path / "release.json"
    path.write_bytes(canonical_json(frozen))
    document, sha = d.load(path)
    assert document == frozen and sha == document_sha256(frozen)
    path.write_bytes(canonical_json(frozen) + b"\n")
    with refused("descriptor_invalid:not_canonical"):
        d.load(path)
