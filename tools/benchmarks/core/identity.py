"""Deterministic identity for the benchmark harness (plan §5).

Canonical JSON, SHA-256, write-once output and refusals are the Stage-3 ones (``artefacts``), re-exported here
so the harness has one canonical form. Exact rationals are written as ``{numerator, denominator}``.

**Tooling identity.** ``toolingSha256`` binds the behaviour of the harness that produced a result, enumerated by
the import graph rather than a hand-maintained list or a version string: every loaded module whose file lies
under the repository's ``tools/`` tree (test modules excluded; the benchmark process never imports them), plus
the benchmark schemas. Each file must equal its blob at ``toolingCommit`` (the checkout's ``HEAD``) under Git's
own checkout filters, otherwise the run is refused ``tooling_dirty``; the hash is then taken over the committed
blob bytes, so a CRLF and an LF checkout of the same commit agree. The enumerated path list is recorded beside
the hash for audit.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterable, Mapping
from fractions import Fraction
from pathlib import Path
from typing import Any

from tools.benchmarks.core._stage3 import ROOT, artefacts

S32Error = artefacts.S32Error
require = artefacts.require
canonical_json = artefacts.canonical_json
sha256_hex = artefacts.sha256_hex
document_sha256 = artefacts.document_sha256
write_once = artefacts.write_once
OutputDirectory = artefacts.OutputDirectory
read_artefact = artefacts.read_artefact
validate = artefacts.validate
safe_relative = artefacts.safe_relative
COMMIT_RE = artefacts.COMMIT_RE
SHA256_RE = artefacts.SHA256_RE

SCHEMA_STEMS = (
    "benchmark-dataset-release-v1",
    "benchmark-class-mapping-v1",
    "benchmark-association-v1",
    "benchmark-vehicle-subclass-result-v1",
)
TOOLING_DIRTY = "tooling_dirty"


# Exact rationals


def rational(value: Fraction | int) -> dict[str, int]:
    """An exact non-negative rational in lowest terms, as ``{numerator, denominator}``."""
    value = Fraction(value)
    require(value >= 0, "rational_negative")
    return {"numerator": value.numerator, "denominator": value.denominator}


def from_rational(document: Mapping[str, Any], code: str) -> Fraction:
    require(isinstance(document, Mapping) and set(document) == {"numerator", "denominator"}, code)
    numerator, denominator = document["numerator"], document["denominator"]
    require(type(numerator) is int and type(denominator) is int and numerator >= 0 and denominator >= 1, code)
    value = Fraction(numerator, denominator)
    require(value.numerator == numerator and value.denominator == denominator, f"{code}:not_lowest_terms")
    return value


def require_canonical_rationals(document: Any, code: str) -> None:
    """Every exact rational ``{numerator, denominator}`` anywhere in ``document`` is in lowest terms, so one value
    has one spelling and one hash (thresholds and rates are hashed into ``associationBodySha256`` and the run
    identity). Count fractions ``{numerator, denominator, value}`` are deliberately not reduced and are not
    touched. Association and result validation call this on every document they accept."""
    if isinstance(document, Mapping):
        if set(document) == {"numerator", "denominator"}:
            from_rational(document, code)
            return
        for value in document.values():
            require_canonical_rationals(value, code)
    elif isinstance(document, list):
        for value in document:
            require_canonical_rationals(value, code)


# Tooling identity


def _git(root: Path, *args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(root), *args], input=stdin, capture_output=True, check=False)


def loaded_tool_files(root: Path = ROOT, modules: Mapping[str, Any] | None = None) -> list[str]:
    """Repository-relative POSIX paths of the loaded Python modules under ``root/tools`` (tests excluded)."""
    tools = (Path(root).resolve() / "tools")
    found: set[str] = set()
    for module in list((sys.modules if modules is None else modules).values()):
        location = getattr(module, "__file__", None)
        if not location:
            continue
        path = Path(location).resolve()
        if path.suffix != ".py" or not path.is_relative_to(tools):
            continue
        relative = path.relative_to(Path(root).resolve()).as_posix()
        if "tests" in relative.split("/")[:-1]:
            continue
        found.add(relative)
    return sorted(found)


def tooling_paths(root: Path = ROOT, modules: Mapping[str, Any] | None = None,
                  schema_stems: Iterable[str] = SCHEMA_STEMS) -> list[str]:
    schemas = {f"contracts/schemas/{stem}.schema.json" for stem in schema_stems}
    return sorted(set(loaded_tool_files(root, modules)) | schemas)


def _blobs_at(root: Path, commit: str, paths: list[str]) -> dict[str, str]:
    listed = _git(root, "ls-tree", "-r", "-z", "--full-tree", commit, "--", *paths)
    require(listed.returncode == 0, f"{TOOLING_DIRTY}:ls_tree")
    blobs: dict[str, str] = {}
    for entry in listed.stdout.split(b"\0"):
        if not entry:
            continue
        meta, _, path = entry.partition(b"\t")
        _mode, kind, blob = meta.split(b" ")
        if kind == b"blob":
            blobs[path.decode("utf-8")] = blob.decode("ascii")
    return blobs


def _working_blob_ids(root: Path, paths: list[str]) -> list[str]:
    """Blob ids of the working files as Git would store them (checkout filters applied, e.g. ``eol``)."""
    hashed = _git(root, "hash-object", "--stdin-paths", stdin="".join(f"{p}\n" for p in paths).encode("utf-8"))
    require(hashed.returncode == 0, f"{TOOLING_DIRTY}:hash_object")
    ids = hashed.stdout.decode("ascii").split()
    require(len(ids) == len(paths), f"{TOOLING_DIRTY}:hash_object")
    return ids


def _blob_bytes(root: Path, blob_ids: list[str]) -> list[bytes]:
    batch = _git(root, "cat-file", "--batch", stdin="".join(f"{blob}\n" for blob in blob_ids).encode("ascii"))
    require(batch.returncode == 0, f"{TOOLING_DIRTY}:cat_file")
    output, contents = batch.stdout, []
    for blob in blob_ids:
        header, _, output = output.partition(b"\n")
        parts = header.split(b" ")
        require(len(parts) == 3 and parts[0].decode("ascii") == blob and parts[1] == b"blob",
                f"{TOOLING_DIRTY}:cat_file")
        size = int(parts[2])
        contents.append(output[:size])
        output = output[size + 1:]
    return contents


def tooling_identity(root: Path = ROOT, modules: Mapping[str, Any] | None = None,
                     schema_stems: Iterable[str] = SCHEMA_STEMS) -> dict[str, Any]:
    """``{toolingCommit, toolingSha256, toolingFiles}`` for the files this process executes with.

    Call it after the command module (and everything it imports) is loaded. Refuses ``tooling_dirty`` when the
    checkout has no commit, or any enumerated file is untracked at ``HEAD`` or differs from its blob there.
    """
    root = Path(root)
    paths = tooling_paths(root, modules, schema_stems)
    head = _git(root, "rev-parse", "--verify", "HEAD^{commit}")
    require(head.returncode == 0, f"{TOOLING_DIRTY}:no_commit")
    commit = head.stdout.decode("ascii").strip()
    require(COMMIT_RE.fullmatch(commit), f"{TOOLING_DIRTY}:no_commit")
    committed = _blobs_at(root, commit, paths)
    for path in paths:
        require(path in committed, f"{TOOLING_DIRTY}:{path}")
    for path, working in zip(paths, _working_blob_ids(root, paths)):
        require(working == committed[path], f"{TOOLING_DIRTY}:{path}")
    contents = _blob_bytes(root, [committed[path] for path in paths])
    files = [{"path": path, "sha256": sha256_hex(data)} for path, data in zip(paths, contents)]
    return {"toolingCommit": commit, "toolingSha256": document_sha256(files), "toolingFiles": files}


def require_tooling(identity: Mapping[str, Any]) -> None:
    """``toolingSha256`` is the hash of the recorded file list (the audit list cannot drift from the hash)."""
    files = identity.get("toolingFiles")
    require(isinstance(files, list) and files, "envelope_invalid:tooling")
    paths = [item.get("path") for item in files]
    require(paths == sorted(set(paths)), "envelope_invalid:tooling_order")
    require(identity.get("toolingSha256") == document_sha256(files), "envelope_invalid:tooling_sha256")
