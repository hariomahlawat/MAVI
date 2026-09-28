"""Frozen qualification-test sealing and access control (qualification plan §19 R1, §20 R2).

The seal commits the frozen test's identity before any candidate runs: the member set
(Tracks and crop SHA-256s), the frozen ground-truth file's SHA-256 and the annotation
ledger head. The frozen labels are held outside the evaluation environment by the Corpus
Custodian; model-selection code reads only the evaluation view
(``annotation.load_evaluation_view``), which refuses frozen rows by construction.

Every access after sealing goes through ``access_frozen`` and is written to an append-only,
hash-chained access log *before* anything is returned. Only two purposes are proper
before S5: ``integrity-verify`` (hash the file; nothing is returned) and
``custody-transfer``. ``s5-scoring`` is proper only at stage ``S5``. Any other access —
including an access declared after the fact with ``declare_improper_access`` — marks the
seal **compromised**, and R1 then requires a new frozen set with a new seal
(``build_seal(..., supersedes=...)``).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .canonical import (
    CorpusError,
    document_sha256,
    read_json,
    require,
    require_datetime,
    require_free_text,
    require_pseudonym,
    require_sha256,
)
from .ledger import Ledger
from .manifest import CorpusManifest
from .partition import FROZEN, partition_of

SEAL_SCHEMA = "mavi-attribute-frozen-test-seal-v1"
PROPER_BEFORE_S5 = ("integrity-verify", "custody-transfer")
STAGES = ("S2c.1", "S2c.2", "S2c.3", "S2c.4", "S2c.5", "S2c.6", "S2c.7", "S2c.8", "S2c.9", "S2c.10", "S3", "S4", "S5")


def frozen_members(corpus: CorpusManifest, partition: dict) -> list[dict]:
    parts = partition_of(partition)
    return [
        {"trackId": t, "cropSha256s": [o.sha256 for o in corpus.tracks[t].observations]}
        for t in sorted(t for t, p in parts.items() if p == FROZEN)
    ]


def build_seal(
    corpus: CorpusManifest,
    partition: dict,
    partition_sha256: str,
    frozen_ground_truth: dict,
    annotation_ledger_head: str,
    sealed_by: str,
    sealed_at: str,
    custody_note: str,
    supersedes: dict | None = None,
) -> dict:
    require(frozen_ground_truth.get("view") == "frozen-test", "seal_requires_frozen_view")
    require(frozen_ground_truth.get("partitionManifestSha256") == partition_sha256, "seal_partition_mismatch")
    members = frozen_members(corpus, partition)
    require(members, "seal_frozen_partition_empty")
    labelled = {r["trackId"] for r in frozen_ground_truth["rows"]}
    unlabelled = [m["trackId"] for m in members if m["trackId"] not in labelled]
    require(not unlabelled, f"seal_frozen_tracks_unlabelled:{len(unlabelled)}")
    require(all(r["partition"] == FROZEN for r in frozen_ground_truth["rows"]), "seal_frozen_view_contains_other_partitions")
    if supersedes is not None:
        require(set(supersedes) == {"sealSha256", "reason"}, "seal_supersedes_invalid")
        require_sha256(supersedes["sealSha256"], "seal_supersedes_invalid")
        require_free_text(supersedes["reason"], "seal_supersedes_reason")
    parts = partition_of(partition)
    cameras = sorted({corpus.source_of(t).camera_id for t, p in parts.items() if p == FROZEN})
    sites = sorted({corpus.source_of(t).site_id for t, p in parts.items() if p == FROZEN})
    return {
        "schemaVersion": SEAL_SCHEMA,
        "corpusKind": corpus.corpus_kind,
        "corpusManifestSha256": corpus.sha256,
        "partitionManifestSha256": partition_sha256,
        "frozenMembers": {
            "trackCount": len(members),
            "cropCount": sum(len(m["cropSha256s"]) for m in members),
            "cameraIds": cameras,
            "siteIds": sites,
            "membersSha256": document_sha256(members),
        },
        "frozenGroundTruthSha256": document_sha256(frozen_ground_truth),
        "annotationLedgerHead": require_sha256(annotation_ledger_head, "seal_ledger_head"),
        "sealedBy": require_pseudonym(sealed_by, "seal_owner"),
        "sealedAt": require_datetime(sealed_at, "seal_time"),
        "custodyNote": require_free_text(custody_note, "seal_custody_note"),
        "supersedes": supersedes,
    }


def open_access_log(path: Path, seal: dict, at: str) -> Ledger:
    """The access log starts with the seal itself, so the log and seal are bound together."""
    log = Ledger(path)
    seal_sha = document_sha256(seal)
    if not log.entries:
        log.append("seal-created", {"sealSha256": seal_sha}, at)
    require(log.entries[0]["kind"] == "seal-created" and log.entries[0]["payload"]["sealSha256"] == seal_sha, "access_log_seal_mismatch")
    return log


def _proper(purpose: str, stage: str) -> bool:
    if purpose == "s5-scoring":
        return stage == "S5"
    return purpose in PROPER_BEFORE_S5


def access_frozen(log: Ledger, seal: dict, frozen_path: Path, actor: str, purpose: str, stage: str, at: str) -> dict | str:
    """Log first, then act. Returns the labels only for S5 scoring; a hash for integrity checks."""
    require_pseudonym(actor, "access_actor")
    require(stage in STAGES, f"access_stage_unknown:{stage}")
    require(isinstance(purpose, str) and purpose, "access_purpose")
    proper = _proper(purpose, stage)
    log.append("frozen-access", {"sealSha256": document_sha256(seal), "actor": actor, "purpose": purpose, "stage": stage, "proper": proper}, at)
    if not proper:
        raise CorpusError(f"frozen_access_improper_seal_compromised:{purpose}@{stage}")
    data = frozen_path.read_bytes()
    document = read_json(frozen_path)
    require(document_sha256(document) == seal["frozenGroundTruthSha256"], "frozen_ground_truth_hash_mismatch")
    if purpose == "s5-scoring":
        return document
    return hashlib.sha256(data).hexdigest()


def declare_improper_access(log: Ledger, seal: dict, actor: str, stage: str, description: str, at: str) -> None:
    """Record an access that happened outside the tool (for example a file opened by hand)."""
    require_pseudonym(actor, "access_actor")
    require(stage in STAGES, f"access_stage_unknown:{stage}")
    log.append("frozen-access", {"sealSha256": document_sha256(seal), "actor": actor, "purpose": "declared-out-of-band", "stage": stage, "proper": False, "description": require_free_text(description, "access_description")}, at)


def seal_status(log: Ledger, seal: dict) -> dict:
    log.verify()
    seal_sha = document_sha256(seal)
    accesses = [e for e in log.of_kind("frozen-access") if e["payload"]["sealSha256"] == seal_sha]
    improper = [e for e in accesses if not e["payload"]["proper"]]
    scored = [e for e in accesses if e["payload"]["purpose"] == "s5-scoring"]
    return {
        "sealSha256": seal_sha,
        "status": "compromised" if improper else "intact",
        "accessCount": len(accesses),
        "improperAccesses": [{"seq": e["seq"], "purpose": e["payload"]["purpose"], "stage": e["payload"]["stage"], "actor": e["payload"]["actor"]} for e in improper],
        "s5ScoringCount": len(scored),
        "logHead": log.head,
    }


def verify_superseding_seal(new_seal: dict, old_seal: dict, old_log: Ledger) -> None:
    """A replacement seal must name the compromised one and a genuinely new frozen set."""
    require(new_seal["supersedes"] is not None and new_seal["supersedes"]["sealSha256"] == document_sha256(old_seal), "seal_supersedes_mismatch")
    require(seal_status(old_log, old_seal)["status"] == "compromised", "seal_superseded_while_intact")
    require(new_seal["frozenMembers"]["membersSha256"] != old_seal["frozenMembers"]["membersSha256"], "seal_reuses_compromised_frozen_set")
