"""The frozen identity of one Stage-3 Development producer, for A2 benchmark execution (ADR-014 2026-10-06 note).

A Development producer (``a2-scale640``, ``a2-scale1280``) is defined by three tracked files: the producer registry,
the producer's component binding and its A2 pipeline profile. Benchmark execution must measure exactly the producer
it names, as it was committed: a dirty local edit must not be able to redefine it. So the identity is read from the
blobs at ``HEAD`` (never from the working tree), and each of the three working files must be byte-identical to its
``HEAD`` blob as Git would store it, the same rule ``identity.tooling_identity`` applies to the harness's own code.

``producer_identity`` returns one small object derived from the selected registry entry:

* ``producerId``, ``pipelineProfileSha256``, ``componentBindingSha256`` and the detector ``modelPackId``: what every
  run of that producer attests, and what the resume journal binds;
* ``gitCommit`` and, per file, its path, Git blob id and SHA-256: where those bytes came from.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tools.benchmarks.core._stage3 import ROOT
from tools.benchmarks.core.identity import COMMIT_RE, _git, document_sha256, require, sha256_hex

REGISTRY_PATH = "src/vision/config/development-producers-v1.json"
REGISTRY_SCHEMA = "mavi-vision-development-producers-v1"
DIRTY = "benchmark_producer_dirty"
# What a run attests and the journal binds: the producer's material identity, without the commit it was read from.
ATTESTED_KEYS = ("pipelineProfileSha256", "componentBindingSha256", "modelPackId")
JOURNAL_KEYS = ("producerId", *ATTESTED_KEYS)


def _head(root: Path) -> str:
    head = _git(root, "rev-parse", "--verify", "HEAD^{commit}")
    require(head.returncode == 0, f"{DIRTY}:no_commit")
    commit = head.stdout.decode("ascii").strip()
    require(COMMIT_RE.fullmatch(commit) is not None, f"{DIRTY}:no_commit")
    return commit


def _committed(root: Path, commit: str, path: str) -> tuple[str, bytes]:
    """The ``HEAD`` blob of ``path`` and its bytes; the working file must hash to the same blob."""
    listed = _git(root, "ls-tree", "-z", "--full-tree", commit, "--", path)
    require(listed.returncode == 0, f"{DIRTY}:{path}")
    entry = listed.stdout.rstrip(b"\0")
    meta, _, listed_path = entry.partition(b"\t")
    parts = meta.split(b" ")
    require(listed_path.decode("utf-8") == path and len(parts) == 3 and parts[1] == b"blob", f"{DIRTY}:{path}")
    blob = parts[2].decode("ascii")
    working = _git(root, "hash-object", "--path", path, "--", str(Path(root) / path))
    require(working.returncode == 0 and working.stdout.decode("ascii").strip() == blob, f"{DIRTY}:{path}")
    shown = _git(root, "cat-file", "blob", blob)
    require(shown.returncode == 0, f"{DIRTY}:{path}")
    return blob, shown.stdout


def producer_identity(producer_id: str, root: Path = ROOT) -> dict[str, Any]:
    """The committed identity of ``producer_id``; refuses ``benchmark_producer_dirty:<path>`` on any uncommitted byte."""
    require(isinstance(producer_id, str) and producer_id, "benchmark_development_producer_unknown")
    root = Path(root)
    commit = _head(root)
    files: list[dict[str, str]] = []

    def read(path: str) -> bytes:
        blob, data = _committed(root, commit, path)
        files.append({"path": path, "gitBlob": blob, "sha256": sha256_hex(data)})
        return data

    registry_bytes = read(REGISTRY_PATH)  # outside the try: S32Error is a ValueError
    try:
        registry = json.loads(registry_bytes)
    except ValueError:
        registry = None
    require(isinstance(registry, dict) and registry.get("schemaVersion") == REGISTRY_SCHEMA
            and isinstance(registry.get("producers"), list), "benchmark_producers_invalid")
    entries = [item for item in registry["producers"] if isinstance(item, dict) and item.get("producerId") == producer_id]
    require(len(entries) == 1, f"benchmark_development_producer_unknown:{producer_id}")
    entry = entries[0]
    require(isinstance(entry.get("bindingPath"), str) and isinstance(entry.get("pipelineProfilePath"), str),
            "benchmark_producers_invalid")
    binding_bytes = read(entry["bindingPath"])
    profile_bytes = read(entry["pipelineProfilePath"])
    try:
        binding = json.loads(binding_bytes)
        packs = [item["modelPackId"] for item in binding["capabilityBindings"]
                 if item["roleId"] == "vision" and item["capabilityId"] == "detector"]
    except (ValueError, KeyError, TypeError):
        packs = []
    require(len(packs) == 1, "benchmark_producers_invalid")
    identity: dict[str, Any] = {
        "producerId": producer_id,
        "pipelineProfileSha256": sha256_hex(profile_bytes),
        "componentBindingSha256": sha256_hex(binding_bytes),
        "modelPackId": packs[0],
        "gitCommit": commit,
        "files": files,
    }
    identity["producerIdentitySha256"] = document_sha256(journal_identity(identity))
    return identity


def journal_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    """What the resume journal binds: the producer and its material identity (not the commit it was read at)."""
    return {key: identity[key] for key in JOURNAL_KEYS}


def require_attested(attestation: Mapping[str, Any], identity: Mapping[str, Any]) -> None:
    """The attested producer of a run is exactly the requested one (``benchmark_producer_mismatch:<key>``)."""
    for key in ATTESTED_KEYS:
        require(attestation.get(key) == identity[key], f"benchmark_producer_mismatch:{key}")
