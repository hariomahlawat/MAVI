"""Exact and near-duplicate crop control (S2c plan §10.2 "Contamination").

Two simple, explainable methods; no learned model:

* **exact** — identical crop bytes (same SHA-256 under different Observation UUIDs);
* **near** — a 64-bit difference hash (dHash): the crop is converted to 8-bit greyscale
  with Pillow (already a declared MAVI Vision dependency), resized to 9x8 with the
  ``BOX`` filter, and bit *i* records whether pixel ``(x, y)`` is brighter than
  ``(x + 1, y)``. Two crops whose dHash Hamming distance is at most ``hammingThreshold``
  are likely near-duplicates (the same frame re-encoded or an almost static scene).

Candidate pairs are found with a pigeonhole index: with a threshold ``t < 8`` two hashes
within distance ``t`` agree exactly on at least one of their eight bytes, so only
Tracks sharing a byte bucket are compared. Exact groups always apply. Near groups apply
unless a reviewer rejects them: for leakage, the conservative error is to link too much
(resolution only moves Tracks into training), never too little. Nothing is deleted.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from .canonical import (
    CorpusError,
    document_sha256,
    refuse_path_leaks,
    require,
    require_date,
    require_free_text,
    require_int,
    require_keys,
    require_pseudonym,
    require_sha256,
)
from .manifest import CorpusManifest
from .partition import LinkGroup

DUPLICATE_SCHEMA = "mavi-attribute-duplicate-audit-v1"
DHASH_BITS = 64


def dhash64(image_bytes: bytes) -> int:
    from io import BytesIO

    from PIL import Image  # declared MAVI Vision dependency (src/vision/pyproject.toml)

    with Image.open(BytesIO(image_bytes)) as image:
        small = image.convert("L").resize((9, 8), Image.Resampling.BOX)
        pixels = list(small.getdata())
    value = 0
    for y in range(8):
        for x in range(8):
            value = (value << 1) | (1 if pixels[y * 9 + x] > pixels[y * 9 + x + 1] else 0)
    return value


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def fingerprint_corpus(corpus: CorpusManifest, read_crop: Callable[[str], bytes]) -> dict[str, str]:
    """dHash of every crop, read by SHA-256 from a local evidence store the caller owns.

    The integrity of each crop is checked against the manifest; the store's location
    never enters any record.
    """
    fingerprints = {}
    for observation in corpus.observations.values():
        data = read_crop(observation.sha256)
        require(hashlib.sha256(data).hexdigest() == observation.sha256, f"duplicate_crop_integrity:{observation.observation_id}")
        fingerprints[observation.observation_id] = f"{dhash64(data):016x}"
    return fingerprints


def directory_reader(root: Path) -> Callable[[str], bytes]:
    """Crops stored as ``<root>/<sha256>`` or ``<root>/<sha256>.<ext>``; ``root`` is never recorded."""

    def read(sha256: str) -> bytes:
        matches = sorted(p for p in (root / sha256, *root.glob(f"{sha256}.*")) if p.is_file())
        if not matches:
            raise CorpusError(f"duplicate_crop_missing:{sha256}")
        return matches[0].read_bytes()

    return read


def find_pairs(corpus: CorpusManifest, fingerprints: dict[str, str], threshold: int) -> list[dict]:
    require_int(threshold, "duplicate_threshold", 0, 7)  # pigeonhole bound: t < 8 bytes
    require(set(fingerprints) == set(corpus.observations), "duplicate_fingerprint_coverage")
    observations = corpus.observations
    pairs: dict[tuple[str, str], dict] = {}
    by_sha: dict[str, list[str]] = defaultdict(list)
    for observation_id, observation in observations.items():
        by_sha[observation.sha256].append(observation_id)
    for ids in by_sha.values():
        ids.sort()
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                pairs[(a, b)] = {"a": a, "b": b, "kind": "exact", "distance": 0}
    values = {o: int(h, 16) for o, h in fingerprints.items()}
    buckets: dict[tuple[int, int], list[str]] = defaultdict(list)
    for observation_id, value in values.items():
        for byte in range(8):
            buckets[(byte, (value >> (8 * byte)) & 0xFF)].append(observation_id)
    for members in buckets.values():
        members.sort()
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                if (a, b) in pairs or observations[a].track_id == observations[b].track_id:
                    continue
                distance = hamming(values[a], values[b])
                if distance <= threshold:
                    pairs[(a, b)] = {"a": a, "b": b, "kind": "near", "distance": distance}
    return [pairs[key] for key in sorted(pairs)]


def build_duplicate_audit(corpus: CorpusManifest, fingerprints: dict[str, str], threshold: int, decisions: dict[str, dict] | None = None) -> dict:
    """Group pairs into connected components; exact components are always ``confirmed``."""
    pairs = find_pairs(corpus, fingerprints, threshold)
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for pair in pairs:
        parent[find(pair["b"])] = find(pair["a"])
    members: dict[str, set[str]] = defaultdict(set)
    for observation_id in parent:
        members[find(observation_id)].add(observation_id)
    groups = []
    for root in sorted(members):
        ids = sorted(members[root])
        kinds = {p["kind"] for p in pairs if p["a"] in members[root]}
        group_id = "dup-" + hashlib.sha256("|".join(ids).encode()).hexdigest()[:16]
        decision = (decisions or {}).get(group_id)
        status = "confirmed" if "exact" in kinds and not decision else (decision or {}).get("status", "proposed")
        groups.append({"groupId": group_id, "observationIds": ids, "kinds": sorted(kinds), "status": status, "decision": decision})
    return {
        "schemaVersion": DUPLICATE_SCHEMA,
        "corpusManifestSha256": corpus.sha256,
        "method": {"exact": "sha256", "near": "dhash-64-box-9x8", "hammingThreshold": threshold},
        "fingerprints": [{"observationId": o, "dhash": fingerprints[o]} for o in sorted(fingerprints)],
        "pairs": pairs,
        "groups": groups,
    }


def parse_duplicate_audit(document: dict, corpus: CorpusManifest) -> tuple[str, list[LinkGroup]]:
    code = "duplicate_invalid"
    require_keys(document, code, ("schemaVersion", "corpusManifestSha256", "method", "fingerprints", "pairs", "groups"))
    require(document["schemaVersion"] == DUPLICATE_SCHEMA, f"{code}:schema")
    require(require_sha256(document["corpusManifestSha256"], code) == corpus.sha256, "duplicate_corpus_mismatch")
    refuse_path_leaks(document, "duplicate_path_leak")
    fingerprints = {f["observationId"]: f["dhash"] for f in document["fingerprints"]}
    decisions = {g["groupId"]: g["decision"] for g in document["groups"] if g["decision"] is not None}
    for group in document["groups"]:
        if group["decision"] is not None:
            require_keys(group["decision"], f"{code}:decision", ("status", "by", "date", "note"))
            require(group["decision"]["status"] in ("confirmed", "rejected"), f"{code}:decision")
            require("exact" not in group["kinds"] or group["decision"]["status"] == "confirmed", f"duplicate_exact_cannot_be_rejected:{group['groupId']}")
            require_pseudonym(group["decision"]["by"], f"{code}:decision")
            require_date(group["decision"]["date"], f"{code}:decision")
            require_free_text(group["decision"]["note"], f"{code}:decision")
    # The audit must be exactly what the method produces from the fingerprints: no pair or
    # group can be dropped by hand.
    rebuilt = build_duplicate_audit(corpus, fingerprints, document["method"]["hammingThreshold"], decisions)
    require(rebuilt == document, "duplicate_audit_not_reproducible")
    observations = corpus.observations
    links = []
    for group in document["groups"]:
        if group["status"] == "rejected":
            continue
        tracks = frozenset(observations[o].track_id for o in group["observationIds"])
        if len(tracks) >= 2:
            links.append(LinkGroup(group["groupId"], "duplicate", tracks))
    return document_sha256(document), links
