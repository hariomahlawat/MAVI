"""Leakage-safe four-way partitioning (S2c plan §10.2; qualification plan §3.1–§3.2, R2 item 7).

Algorithm (deterministic; the only inputs are the corpus, the policy and the audits):

1. **Clusters.** A cluster is every source of one site within one contiguous date block
   (``(siteId, floor((recordingDate - corpusEpoch) / dateBlockDays))``). All cameras of
   a site on the same days therefore share a partition, so a subject seen by several
   cameras at once cannot straddle partitions. Tracks are never split individually.
2. **Frozen test.** ``heldOutSites`` whole sites (ordered by seeded hash) go to the frozen
   test, giving cameras unseen elsewhere. For every other site the latest
   ``frozenLatestBlockFraction`` of its date blocks also go to the frozen test (a temporal
   hold-out of seen sites; blocks are contiguous, never interleaved days).
3. **Training / tuning / selection.** The remaining clusters, ordered by seeded hash, are
   assigned greedily to the partition with the largest Track deficit against
   ``targetFractions``. Tuning and selection are distinct partitions (R2 item 7).
4. **Link resolution.** Confirmed recurrence groups and applied duplicate groups link
   Tracks. Every connected set of linked Tracks that spans more than one partition is
   moved wholly to **training**. Resolution only ever moves Tracks *into* training, so an
   evaluation partition can lose Tracks but never gain one it should not have. Every
   move is recorded with its reason; nothing is deleted.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from .canonical import (
    CorpusError,
    document_sha256,
    hash_rank,
    require,
    require_int,
    require_keys,
    require_pseudonym,
    require_sha256,
    require_token,
)
from .manifest import CorpusManifest

PARTITION_SCHEMA = "mavi-attribute-partition-manifest-v1"
TRAINING, TUNING, SELECTION, FROZEN = "training", "tuning", "selection", "frozen-test"
PARTITIONS = (TRAINING, TUNING, SELECTION, FROZEN)
NON_FROZEN = (TRAINING, TUNING, SELECTION)
EVALUATION_READABLE = (TRAINING, TUNING, SELECTION)  # R2 item 3: the frozen test is never read for selection


@dataclass(frozen=True, slots=True)
class LinkGroup:
    """Tracks that must share a partition (a confirmed recurrence or a duplicate group)."""

    group_id: str
    kind: str  # "recurrence" | "duplicate"
    track_ids: frozenset[str]


def parse_policy(policy: dict) -> dict:
    code = "partition_policy_invalid"
    require(isinstance(policy, dict), code)
    require_keys(
        policy,
        code,
        ("policyId", "version", "seed", "dateBlockDays", "heldOutSites", "frozenLatestBlockFraction", "targetFractions", "minimumCamerasPerPartition", "requireUnseenFrozenCamera"),
    )
    require_pseudonym(policy["policyId"], f"{code}:id")
    require_token(f"v{policy['version']}", f"{code}:version")
    require(isinstance(policy["seed"], str) and 1 <= len(policy["seed"]) <= 128, f"{code}:seed")
    require_int(policy["dateBlockDays"], f"{code}:block", 1, 366)
    require_int(policy["heldOutSites"], f"{code}:held_out", 0)
    fraction = policy["frozenLatestBlockFraction"]
    require(isinstance(fraction, (int, float)) and 0 <= fraction < 1, f"{code}:frozen_fraction")
    targets = policy["targetFractions"]
    require(isinstance(targets, dict) and set(targets) == set(NON_FROZEN), f"{code}:targets")
    require(all(isinstance(v, (int, float)) and v > 0 for v in targets.values()), f"{code}:targets")
    require(abs(sum(targets.values()) - 1) < 1e-9, f"{code}:targets_sum")
    require_int(policy["minimumCamerasPerPartition"], f"{code}:cameras", 1)
    require(isinstance(policy["requireUnseenFrozenCamera"], bool), f"{code}:unseen")
    return policy


def _clusters(corpus: CorpusManifest, block_days: int) -> tuple[date, dict[str, dict]]:
    epoch = min(date.fromisoformat(s.recording_date) for s in corpus.sources.values())
    clusters: dict[str, dict] = {}
    for track in corpus.tracks.values():
        source = corpus.sources[track.source_id]
        block = (date.fromisoformat(source.recording_date) - epoch).days // block_days
        cluster_id = f"{source.site_id}~b{block:04d}"
        entry = clusters.setdefault(
            cluster_id,
            {"clusterId": cluster_id, "siteId": source.site_id, "dateBlock": block, "firstDate": source.recording_date, "lastDate": source.recording_date, "trackIds": set(), "cameraIds": set()},
        )
        entry["trackIds"].add(track.track_id)
        entry["cameraIds"].add(source.camera_id)
        entry["firstDate"] = min(entry["firstDate"], source.recording_date)
        entry["lastDate"] = max(entry["lastDate"], source.recording_date)
    return epoch, clusters


def _initial_assignment(clusters: dict[str, dict], policy: dict) -> dict[str, str]:
    seed = policy["seed"]
    sites = sorted({c["siteId"] for c in clusters.values()}, key=lambda s: hash_rank(seed, "site", s))
    held_out = set(sites[: policy["heldOutSites"]])
    require(len(held_out) < len(sites) or not sites, "partition_all_sites_held_out")
    assignment: dict[str, str] = {}
    for cluster_id, cluster in clusters.items():
        if cluster["siteId"] in held_out:
            assignment[cluster_id] = FROZEN
    for site in sites:
        if site in held_out:
            continue
        blocks = sorted((c for c in clusters.values() if c["siteId"] == site), key=lambda c: c["dateBlock"])
        frozen_count = int(len(blocks) * policy["frozenLatestBlockFraction"])
        for cluster in blocks[len(blocks) - frozen_count:] if frozen_count else []:
            assignment[cluster["clusterId"]] = FROZEN
    remaining = sorted((c for c in clusters if c not in assignment), key=lambda c: hash_rank(seed, "cluster", c))
    total = sum(len(clusters[c]["trackIds"]) for c in remaining)
    assigned = {p: 0 for p in NON_FROZEN}
    for cluster_id in remaining:
        deficits = {p: policy["targetFractions"][p] * total - assigned[p] for p in NON_FROZEN}
        # Largest deficit wins; ties fall to canonical partition order.
        choice = max(NON_FROZEN, key=lambda p: (deficits[p], -NON_FROZEN.index(p)))
        assignment[cluster_id] = choice
        assigned[choice] += len(clusters[cluster_id]["trackIds"])
    return assignment


def _components(groups: list[LinkGroup]) -> list[tuple[frozenset[str], tuple[str, ...]]]:
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for group in groups:
        members = sorted(group.track_ids)
        for member in members[1:]:
            parent[find(member)] = find(members[0])
        find(members[0])
    members_by_root: dict[str, set[str]] = defaultdict(set)
    for track_id in parent:
        members_by_root[find(track_id)].add(track_id)
    reasons_by_root: dict[str, set[str]] = defaultdict(set)
    for group in groups:
        reasons_by_root[find(next(iter(group.track_ids)))].add(f"{group.kind}:{group.group_id}")
    return [(frozenset(members_by_root[r]), tuple(sorted(reasons_by_root[r]))) for r in sorted(members_by_root)]


def build_partition(corpus: CorpusManifest, policy: dict, links: list[LinkGroup], audit_hashes: dict[str, str | None]) -> dict:
    parse_policy(policy)
    for group in links:
        require(group.track_ids <= corpus.tracks.keys(), f"partition_link_unknown_track:{group.group_id}")
        require(len(group.track_ids) >= 2, f"partition_link_too_small:{group.group_id}")
    epoch, clusters = _clusters(corpus, policy["dateBlockDays"])
    cluster_assignment = _initial_assignment(clusters, policy)
    track_partition = {t: cluster_assignment[c] for c, cluster in clusters.items() for t in cluster["trackIds"]}
    track_cluster = {t: c for c, cluster in clusters.items() for t in cluster["trackIds"]}
    moves = []
    for members, reasons in _components(links):
        if len({track_partition[t] for t in members}) > 1:
            for track_id in sorted(members):
                if track_partition[track_id] != TRAINING:
                    moves.append({"trackId": track_id, "from": track_partition[track_id], "to": TRAINING, "reasons": list(reasons)})
                    track_partition[track_id] = TRAINING
    document = {
        "schemaVersion": PARTITION_SCHEMA,
        "corpusManifestSha256": corpus.sha256,
        "policy": policy,
        "corpusEpoch": epoch.isoformat(),
        "audits": {
            "recurrenceAuditSha256": audit_hashes.get("recurrence"),
            "duplicateAuditSha256": audit_hashes.get("duplicate"),
        },
        "clusters": [
            {
                "clusterId": cid,
                "siteId": c["siteId"],
                "dateBlock": c["dateBlock"],
                "firstDate": c["firstDate"],
                "lastDate": c["lastDate"],
                "cameraIds": sorted(c["cameraIds"]),
                "trackCount": len(c["trackIds"]),
                "partition": cluster_assignment[cid],
            }
            for cid, c in sorted(clusters.items())
        ],
        "moves": sorted(moves, key=lambda m: m["trackId"]),
        "assignments": [{"trackId": t, "clusterId": track_cluster[t], "partition": track_partition[t]} for t in sorted(track_partition)],
    }
    document["checks"] = partition_checks(corpus, document)
    return document


def partition_checks(corpus: CorpusManifest, document: dict) -> dict:
    """Coverage facts; a shortfall is a recorded limitation, never silently waived (plan §10.2)."""
    policy = document["policy"]
    cameras: dict[str, set[str]] = {p: set() for p in PARTITIONS}
    counts = {p: 0 for p in PARTITIONS}
    for entry in document["assignments"]:
        cameras[entry["partition"]].add(corpus.source_of(entry["trackId"]).camera_id)
        counts[entry["partition"]] += 1
    elsewhere = cameras[TRAINING] | cameras[TUNING] | cameras[SELECTION]
    unseen = sorted(cameras[FROZEN] - elsewhere)
    limitations = []
    for partition in PARTITIONS:
        if len(cameras[partition]) < policy["minimumCamerasPerPartition"]:
            limitations.append(f"cameras_below_minimum:{partition}:{len(cameras[partition])}")
    if policy["requireUnseenFrozenCamera"] and not unseen:
        limitations.append("no_unseen_frozen_camera")
    return {
        "trackCounts": counts,
        "cameraCounts": {p: len(cameras[p]) for p in PARTITIONS},
        "unseenFrozenCameras": unseen,
        "limitations": limitations,
    }


def partition_sha256(document: dict) -> str:
    return document_sha256(document)


def verify_partition(corpus: CorpusManifest, document: dict, links: list[LinkGroup]) -> None:
    """Independent re-check of every invariant a partition manifest must satisfy."""
    require(document.get("schemaVersion") == PARTITION_SCHEMA, "partition_schema")
    require(document.get("corpusManifestSha256") == corpus.sha256, "partition_corpus_mismatch")
    require_sha256(document["corpusManifestSha256"], "partition_corpus_hash")
    assignments = document["assignments"]
    ids = [a["trackId"] for a in assignments]
    require(len(ids) == len(set(ids)), "partition_track_assigned_twice")
    require(set(ids) == set(corpus.tracks), "partition_track_coverage")
    for entry in assignments:
        require(entry["partition"] in PARTITIONS, f"partition_unknown:{entry['partition']}")
    counts = {p: sum(a["partition"] == p for a in assignments) for p in PARTITIONS}
    for partition in PARTITIONS:
        require(counts[partition] > 0, f"partition_empty:{partition}")  # tuning and selection may not collapse
    # Recompute clusters and the initial assignment; every deviation must be a recorded move to training.
    expected = build_partition(corpus, document["policy"], links, document["audits"])
    require(expected["clusters"] == document["clusters"], "partition_clusters_not_reproducible")
    cluster_partition = {c["clusterId"]: c["partition"] for c in document["clusters"]}
    moved = {m["trackId"]: m for m in document["moves"]}
    for entry in assignments:
        initial = cluster_partition[entry["clusterId"]]
        if entry["trackId"] in moved:
            move = moved[entry["trackId"]]
            require(move["from"] == initial and move["to"] == TRAINING == entry["partition"], f"partition_move_invalid:{entry['trackId']}")
        else:
            require(entry["partition"] == initial, f"partition_cluster_fragmented:{entry['clusterId']}")
    by_track = {a["trackId"]: a["partition"] for a in assignments}
    for group in links:
        require(len({by_track[t] for t in group.track_ids}) == 1, f"partition_link_spans_partitions:{group.kind}:{group.group_id}")
    require(expected["assignments"] == assignments and expected["moves"] == document["moves"], "partition_not_reproducible")
    require(expected["checks"] == document["checks"], "partition_checks_mismatch")


def partition_of(document: dict) -> dict[str, str]:
    return {a["trackId"]: a["partition"] for a in document["assignments"]}


def ensure_readable(partition: str) -> None:
    if partition not in EVALUATION_READABLE:
        raise CorpusError(f"frozen_test_not_readable_for_selection:{partition}")
