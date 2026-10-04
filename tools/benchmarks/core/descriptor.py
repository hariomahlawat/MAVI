"""The dataset release descriptor ``benchmark-dataset-release-v1`` and its source manifest (plan §5, §11).

One record per release carries the release-level provenance and ADR-017 §7 admissibility, the splits, the native
taxonomy (object classes only), the frame-time declaration, the exposure block and the source manifest.

**Manifest.** ``freeze`` lists every regular file under the source root (path, size, SHA-256) into a descriptor
whose manifest was empty; the frozen descriptor is written once. ``reconcile`` is the first step of ``prepare``:
before any dataset discovery it checks the **entire** frozen manifest against the source root, in this order —
``source_manifest_missing`` (nothing frozen), ``source_manifest_incomplete`` (a member is absent),
``source_manifest_unexpected`` (a file the manifest does not list), ``source_manifest_mismatch`` (a member's size
or bytes differ). Files read afterwards are verified again on read (``read_verified``). Manifest paths are
repository-style relative POSIX paths sorted by code point, so the manifest and its hash are the same on Windows
and Linux. Symbolic links and junctions are never followed, and links, unlistable directories and unreadable files
are all refused (``source_root_invalid``), never skipped.
"""

from __future__ import annotations

import copy
import hashlib
import math
import os
from fractions import Fraction
from pathlib import Path
from typing import Any

from tools.benchmarks.core.identity import (
    S32Error, read_artefact, require, safe_relative, sha256_hex, validate)

SCHEMA = "benchmark-dataset-release-v1"
CODE = "descriptor_invalid"
BLOCKED = "BLOCKED"
_CHUNK = 1 << 20


def check(document: dict[str, Any]) -> dict[str, Any]:
    """Schema and the rules a schema cannot express: unique split names and taxonomy codes, and a canonical
    manifest (safe relative paths, sorted, unique)."""
    validate(document, SCHEMA, CODE)
    names = [split["name"] for split in document["splits"]]
    require(len(names) == len(set(names)), f"{CODE}:duplicate_split")
    codes = [entry["code"] for entry in document["nativeTaxonomy"]]
    require(len(codes) == len(set(codes)), f"{CODE}:duplicate_native_class")
    frame_time = document["frameTime"]
    if "fpsNumerator" in frame_time:
        # One timing, one spelling: 10/2 and 5/1 give identical instants, so only lowest terms is accepted
        # (otherwise one release timing could carry two descriptor hashes and two run identities).
        require(math.gcd(frame_time["fpsNumerator"], frame_time["fpsDenominator"]) == 1,
                f"{CODE}:frame_rate_not_lowest_terms")
    paths = [entry["path"] for entry in document["manifest"]["entries"]]
    for path in paths:
        safe_relative(path, f"{CODE}:manifest_path")
    require(paths == sorted(set(paths)), f"{CODE}:manifest_order")
    return document


def load(path: Path) -> tuple[dict[str, Any], str]:
    """A canonical descriptor file and its SHA-256 (the identity the result envelope binds)."""
    document, _, sha = read_artefact(path, SCHEMA, CODE)
    return check(document), sha


def require_usable(document: dict[str, Any]) -> None:
    """ADR-017 §7: ``BLOCKED`` is never used; ``RESEARCH-UNCERTAIN`` is usable for Development with its basis."""
    require(document["researchUse"]["status"] != BLOCKED, "descriptor_blocked")


def native_classes(document: dict[str, Any]) -> list[str]:
    return [entry["code"] for entry in document["nativeTaxonomy"]]


def split(document: dict[str, Any], name: str) -> dict[str, Any]:
    found = [entry for entry in document["splits"] if entry["name"] == name]
    require(found, f"{CODE}:split_unknown:{name}")
    return found[0]


# Frame time (plan §7.1: exact rationals, never rounded before comparison)


def index_offset_ms(document: dict[str, Any], frame_index: int) -> Fraction:
    """The media offset of labelled frame ``frame_index`` under ``index-at-fps``: ``k × 1000 × den / num``."""
    frame_time = document["frameTime"]
    require(frame_time["kind"] == "index-at-fps", f"{CODE}:frame_time_kind")
    require(type(frame_index) is int and frame_index >= 0, f"{CODE}:frame_index")
    return Fraction(frame_index * 1000 * frame_time["fpsDenominator"], frame_time["fpsNumerator"])


# Source manifest


def _file_identity(path: Path, relative: str) -> tuple[int, str]:
    """``(size, sha256)`` of one listed source file, from a single open handle. A file that can be listed but not
    read (an ACL, a file removed after listing) is a refusal, never a raw ``OSError``."""
    digest, size = hashlib.sha256(), 0
    try:
        with open(path, "rb") as stream:
            for block in iter(lambda: stream.read(_CHUNK), b""):
                digest.update(block)
                size += len(block)
    except OSError as exc:
        raise S32Error(f"source_root_invalid:{relative}") from exc
    return size, digest.hexdigest()


def _is_link(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(os.path, "isjunction", lambda _: False)(path))


def source_files(source_root: Path) -> dict[str, Path]:
    """Every regular file under ``source_root`` by relative POSIX path; links are refused, never followed."""
    root = Path(source_root)
    require(root.is_dir() and not _is_link(root), "source_root_invalid")
    files: dict[str, Path] = {}

    def unreadable(error: OSError) -> None:
        # os.walk skips a directory it cannot list; a silently skipped subtree would let a manifest or a
        # reconciliation pass while missing members, so any traversal error is a refusal.
        where = Path(error.filename) if error.filename else root
        relative = where.relative_to(root).as_posix() if where != root and where.is_relative_to(root) else "."
        raise S32Error(f"source_root_invalid:{relative}") from error

    for directory, subdirectories, names in os.walk(root, onerror=unreadable, followlinks=False):
        here = Path(directory)
        for name in subdirectories:
            require(not _is_link(here / name), f"source_root_invalid:{(here / name).relative_to(root).as_posix()}")
        for name in names:
            path = here / name
            relative = path.relative_to(root).as_posix()
            require(not _is_link(path) and path.is_file(), f"source_root_invalid:{relative}")
            files[safe_relative(relative, f"source_root_invalid:{relative}")] = path
    return files


def manifest_entries(source_root: Path) -> list[dict[str, Any]]:
    files = source_files(source_root)
    entries = []
    for relative in sorted(files):
        size, sha = _file_identity(files[relative], relative)
        entries.append({"path": relative, "sizeBytes": size, "sha256": sha})
    return entries


def require_file_hashes(document: dict[str, Any]) -> None:
    """Freeze, reconcile and verified reads implement file-tree semantics only. The v1 contract also names
    ``archive-hashes``, but archive members are not supported yet, so that kind is refused rather than treated as
    a file tree (which would misstate the provenance the descriptor declares)."""
    require(document["manifest"]["kind"] == "file-hashes", f"{CODE}:manifest_kind_unsupported")


def freeze(document: dict[str, Any], source_root: Path) -> dict[str, Any]:
    """The descriptor with its manifest frozen from ``source_root`` (the input is not modified)."""
    check(document)
    require_usable(document)
    require_file_hashes(document)
    require(not document["manifest"]["entries"], f"{CODE}:manifest_already_frozen")
    entries = manifest_entries(source_root)
    require(entries, "source_manifest_missing:empty_source")
    frozen = copy.deepcopy(document)
    frozen["manifest"]["entries"] = entries
    return check(frozen)


def reconcile(document: dict[str, Any], source_root: Path) -> dict[str, dict[str, Any]]:
    """Checks the whole frozen manifest against ``source_root`` before discovery; returns entries by path."""
    check(document)
    require_usable(document)
    require_file_hashes(document)
    entries = {entry["path"]: entry for entry in document["manifest"]["entries"]}
    require(entries, "source_manifest_missing")
    files = source_files(source_root)
    missing = sorted(set(entries) - set(files))
    require(not missing, f"source_manifest_incomplete:{missing[0] if missing else ''}")
    unexpected = sorted(set(files) - set(entries))
    require(not unexpected, f"source_manifest_unexpected:{unexpected[0] if unexpected else ''}")
    for relative in sorted(entries):
        entry = entries[relative]
        size, sha = _file_identity(files[relative], relative)
        require(size == entry["sizeBytes"] and sha == entry["sha256"], f"source_manifest_mismatch:{relative}")
    return entries


def read_verified(entries: dict[str, dict[str, Any]], source_root: Path, relative: str) -> bytes:
    """A manifest member's bytes, verified again on read."""
    entry = entries.get(relative)
    require(entry is not None, f"source_manifest_unexpected:{relative}")
    try:
        data = (Path(source_root) / safe_relative(relative, f"source_manifest_unexpected:{relative}")).read_bytes()
    except OSError as exc:
        raise S32Error(f"source_manifest_incomplete:{relative}") from exc
    require(len(data) == entry["sizeBytes"] and sha256_hex(data) == entry["sha256"],
            f"source_manifest_mismatch:{relative}")
    return data
