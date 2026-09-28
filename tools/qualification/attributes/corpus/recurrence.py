"""Cross-partition recurrence audit (S2c plan §10.2): bookkeeping, not re-identification.

A recurring subject (a regular person or vehicle seen on several dates) could appear in
training and in an evaluation partition and inflate generalisation results. Humans
decide recurrence. The record holds only Track UUIDs and reviewer decisions: no names,
no identity, no embedding. A proposal from an evaluation-only similarity pass (S2c.3,
never shipped, never of a bake-off candidate's family) is imported as ``proposed`` and
applies only once a reviewer confirms it. Rejected groups are kept, never deleted.
"""

from __future__ import annotations

from .canonical import (
    document_sha256,
    refuse_path_leaks,
    require,
    require_date,
    require_free_text,
    require_keys,
    require_pseudonym,
    require_sha256,
    require_uuid,
)
from .manifest import CorpusManifest
from .partition import LinkGroup

RECURRENCE_SCHEMA = "mavi-attribute-recurrence-audit-v1"
STATUSES = ("proposed", "confirmed", "rejected")
PROPOSERS = ("reviewer", "similarity-pass")


def parse_recurrence(document: dict, corpus: CorpusManifest) -> tuple[str, list[LinkGroup]]:
    code = "recurrence_invalid"
    require_keys(document, code, ("schemaVersion", "corpusManifestSha256", "groups"))
    require(document["schemaVersion"] == RECURRENCE_SCHEMA, f"{code}:schema")
    require(require_sha256(document["corpusManifestSha256"], code) == corpus.sha256, "recurrence_corpus_mismatch")
    refuse_path_leaks(document, "recurrence_path_leak")
    applied: list[LinkGroup] = []
    seen: set[str] = set()
    for group in document["groups"]:
        gcode = f"{code}:group"
        require_keys(group, gcode, ("groupId", "subjectKind", "trackIds", "status", "proposer", "decision"))
        group_id = require_pseudonym(group["groupId"], gcode)
        require(group_id not in seen, f"recurrence_duplicate_group:{group_id}")
        seen.add(group_id)
        require(group["subjectKind"] in ("person", "vehicle"), gcode)
        track_ids = [require_uuid(t, gcode) for t in group["trackIds"]]
        require(len(track_ids) >= 2 and len(set(track_ids)) == len(track_ids), f"recurrence_group_size:{group_id}")
        for track_id in track_ids:
            require(track_id in corpus.tracks, f"recurrence_unknown_track:{group_id}")
            require(corpus.tracks[track_id].object_class == group["subjectKind"], f"recurrence_class_mismatch:{group_id}")
        require(group["status"] in STATUSES, gcode)
        proposer = group["proposer"]
        require_keys(proposer, f"{gcode}:proposer", ("kind", "family"))
        require(proposer["kind"] in PROPOSERS, f"{gcode}:proposer")
        require((proposer["kind"] == "similarity-pass") == (proposer["family"] is not None), f"{gcode}:proposer_family")
        decision = group["decision"]
        if group["status"] == "proposed":
            require(decision is None, f"recurrence_proposed_with_decision:{group_id}")
        else:
            require_keys(decision, f"{gcode}:decision", ("by", "date", "note"))
            require_pseudonym(decision["by"], f"{gcode}:decision")
            require_date(decision["date"], f"{gcode}:decision")
            require_free_text(decision["note"], f"{gcode}:decision")
        # Only a human-confirmed recurrence moves Tracks.
        if group["status"] == "confirmed":
            applied.append(LinkGroup(group_id, "recurrence", frozenset(track_ids)))
    normal = dict(document)
    normal["groups"] = sorted(
        ({**g, "trackIds": sorted(g["trackIds"])} for g in document["groups"]), key=lambda g: g["groupId"]
    )
    return document_sha256(normal), applied
