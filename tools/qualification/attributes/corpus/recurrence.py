"""Cross-partition recurrence audit (S2c plan §10.2): bookkeeping, not re-identification.

A recurring subject (a regular person or vehicle seen on several dates) could appear in
training and in an evaluation partition and inflate generalisation results. Humans
decide recurrence. The record holds only Track UUIDs and reviewer decisions: no names,
no identity, no embedding. A proposal from an evaluation-only similarity pass (S2c.3,
never shipped, never of a bake-off candidate's family) is imported as ``proposed`` and
applies only once a reviewer confirms it. Rejected groups are kept, never deleted.

Reviewers can only confirm recurrences they notice. ``recallSample`` records a human
second look at a **reproducible** sample of cross-partition Track pairs
(``draw_recall_sample``, method ``recall-sample-v1``): the seed, the population identity,
the exact sampled pairs and one reviewer decision per pair (``recurrence``,
``not-recurrence`` or ``uncertain``). F1 regenerates the sample from the corpus, the final
partition and the recurrence groups, so neither the pairs nor a zero-miss claim can be
asserted without the reviewed pairs. There is no biometric matcher (excluded by design):
the decisions themselves remain a human attestation, and recall stays an estimate.

Identity: ``parse_recurrence`` returns the SHA-256 of the recurrence **groups** (the audit
without its recall sample), which is what a partition binds. The sample is drawn on that
partition afterwards, so ``recurrence_document_sha256`` (including the sample) is what an
evidence record names.
"""

from __future__ import annotations

from .canonical import (
    document_sha256,
    hash_rank,
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
RECALL_METHOD = "recall-sample-v1"
RECALL_DECISIONS = ("recurrence", "not-recurrence", "uncertain")
# The sample size is fixed by the method, not chosen per draw: because a larger sample
# extends a smaller one, a free size would let a reviewer stop just before a found
# recurrence. With zero recurrences found in n random pairs, the one-sided 95% upper bound
# on the missed rate is about 3/n: 100 pairs bound it near 3%. Raising it is a reviewed
# change to this constant (and so to every F1 check), never a per-sample choice.
RECALL_SAMPLE_PAIRS = 100


def _track_identity_sha256(corpus: CorpusManifest) -> str:
    return document_sha256(sorted([t.track_id, t.object_class] for t in corpus.tracks.values()))


def _assignments_sha256(partition: dict) -> str:
    return document_sha256(sorted([a["trackId"], a["partition"]] for a in partition["assignments"]))


def recall_seed(corpus: CorpusManifest) -> str:
    """The seed depends only on which Tracks exist (and their class), never on the partition,
    the audits or any metadata: the pair order is fixed for the corpus, so no edit — a new
    recurrence group, a policy field, a corpus metadata revision — can redraw the sample. A
    found pair leaves the sample only if a re-partition really puts both Tracks in one
    partition, which is exactly the case in which it no longer leaks."""
    return f"{RECALL_METHOD}:{_track_identity_sha256(corpus)}"


STATUSES = ("proposed", "confirmed", "rejected")
PROPOSERS = ("reviewer", "similarity-pass")


def parse_recurrence(document: dict, corpus: CorpusManifest) -> tuple[str, list[LinkGroup]]:
    code = "recurrence_invalid"
    require_keys(document, code, ("schemaVersion", "corpusManifestSha256", "groups"), ("recallSample",))
    require(document["schemaVersion"] == RECURRENCE_SCHEMA, f"{code}:schema")
    require(require_sha256(document["corpusManifestSha256"], code) == corpus.sha256, "recurrence_corpus_mismatch")
    refuse_path_leaks(document, "recurrence_path_leak")
    sample = document.get("recallSample")
    if sample is not None:
        scode = f"{code}:recallSample"
        require_keys(sample, scode, ("method", "seed", "sampleSize", "populationSha256", "pairs", "by", "date", "note"))
        require(sample["method"] == RECALL_METHOD, f"{scode}:method")
        require(isinstance(sample["seed"], str) and sample["seed"].startswith(f"{RECALL_METHOD}:"), f"{scode}:seed")
        require(isinstance(sample["sampleSize"], int) and not isinstance(sample["sampleSize"], bool) and sample["sampleSize"] >= 1, f"{scode}:size")
        require_sha256(sample["populationSha256"], scode)
        require(isinstance(sample["pairs"], list) and len(sample["pairs"]) == sample["sampleSize"], f"{scode}:pairs")
        for pair in sample["pairs"]:
            require_keys(pair, f"{scode}:pair", ("trackIds", "decision"))
            ids = [require_uuid(t, f"{scode}:pair") for t in pair["trackIds"]]
            require(len(ids) == 2 and ids == sorted(set(ids)) and all(t in corpus.tracks for t in ids), f"{scode}:pair")
            require(pair["decision"] is None or pair["decision"] in RECALL_DECISIONS, f"{scode}:decision")
        require_pseudonym(sample["by"], scode)
        require_date(sample["date"], scode)
        require_free_text(sample["note"], scode)
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
    return recurrence_groups_sha256(document), applied


def _normal(document: dict) -> dict:
    normal = dict(document)
    normal["groups"] = sorted(({**g, "trackIds": sorted(g["trackIds"])} for g in document["groups"]), key=lambda g: g["groupId"])
    return normal


def recurrence_groups_sha256(document: dict) -> str:
    """Identity of the recurrence decisions (without the recall sample): what a partition binds."""
    return document_sha256({k: v for k, v in _normal(document).items() if k != "recallSample"})


def recurrence_document_sha256(document: dict) -> str:
    """Identity of the whole audit, recall sample included: what an evidence record names."""
    return document_sha256(_normal(document))


def recall_population_sha256(corpus: CorpusManifest, partition: dict) -> str:
    return document_sha256({"method": RECALL_METHOD, "trackIdentitySha256": _track_identity_sha256(corpus), "assignmentsSha256": _assignments_sha256(partition), "population": "unordered Track pairs of the same object class in different partitions"})


def draw_recall_sample(corpus: CorpusManifest, partition: dict, size: int = RECALL_SAMPLE_PAIRS) -> dict:
    """Deterministic sample of ``size`` distinct cross-partition, same-class Track pairs.

    Two seeded permutations P1, P2 of the Tracks; step i pairs P1[i mod n] with
    P2[(i div n + i) mod n], which visits every ordered pair once, in a seed-determined
    order (the seed is ``recall_seed``). A larger sample extends a smaller one, so a sample
    cannot be regrown to push a found recurrence out. Invalid pairs (same Track, different class, same partition) and repeats are
    skipped. The decisions start empty for the reviewer to fill."""
    require(isinstance(size, int) and size >= 1, "recall_sample_size")
    seed = recall_seed(corpus)
    parts = {a["trackId"]: a["partition"] for a in partition["assignments"]}
    require(set(parts) == set(corpus.tracks), "recall_sample_partition_mismatch")
    first = sorted(corpus.tracks, key=lambda t: hash_rank(seed, "recall-a", t))
    second = sorted(corpus.tracks, key=lambda t: hash_rank(seed, "recall-b", t))
    n = len(first)
    seen: set[tuple[str, str]] = set()
    pairs: list[dict] = []
    for i in range(n * n):
        a, b = first[i % n], second[(i // n + i) % n]
        pair = tuple(sorted((a, b)))
        if a == b or pair in seen or parts[a] == parts[b] or corpus.tracks[a].object_class != corpus.tracks[b].object_class:
            continue
        seen.add(pair)
        pairs.append({"trackIds": list(pair), "decision": None})
        if len(pairs) == size:
            break
    require(len(pairs) == size, "recall_population_too_small")
    return {"method": RECALL_METHOD, "seed": seed, "sampleSize": size, "populationSha256": recall_population_sha256(corpus, partition), "pairs": pairs}
