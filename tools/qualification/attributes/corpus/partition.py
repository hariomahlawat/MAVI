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
   Tracks. When a connected set of linked Tracks spans more than one partition, every
   **cluster** it touches moves wholly to **training** (repeated until no link spans
   partitions). Moving whole clusters keeps "all cameras of one site on one date block
   share a partition" true after resolution, so the same subject seen at the same time
   on another camera cannot stay behind. Resolution only ever moves clusters *into*
   training, so an evaluation partition can lose Tracks but never gain one it should not
   have. Every cluster move is recorded with its reasons; nothing is deleted.

The date-block epoch is pinned in the policy (``dateEpoch``), so adding an earlier
source in a corpus revision cannot silently shift every block boundary.
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
    require_date,
    require_token,
    require_uuid,
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
        ("policyId", "version", "seed", "dateEpoch", "dateBlockDays", "heldOutSites", "frozenLatestBlockFraction", "targetFractions", "minimumCamerasPerPartition", "requireUnseenFrozenCamera"),
        ("pinnedTrainingTrackIds",),
    )
    # Tracks already labelled in a training-only step (the pilot) must stay in training when
    # the corpus is re-partitioned, for example after a compromised seal (R1). Their whole
    # clusters move to training, recorded like any other move.
    pinned = policy.get("pinnedTrainingTrackIds", [])
    require(isinstance(pinned, list) and pinned == sorted(set(pinned)), f"{code}:pinned")
    for track_id in pinned:
        require_uuid(track_id, f"{code}:pinned")
    require_date(policy["dateEpoch"], f"{code}:epoch")
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


def _clusters(corpus: CorpusManifest, block_days: int, epoch: date) -> tuple[date, dict[str, dict]]:
    require(all(date.fromisoformat(s.recording_date) >= epoch for s in corpus.sources.values()), "partition_source_before_epoch")
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


def _resolve(clusters: dict[str, dict], initial: dict[str, str], links: list[LinkGroup], pinned: tuple[str, ...] = ()) -> tuple[dict[str, str], list[dict]]:
    """Move every cluster touched by a partition-spanning link component to training, to a fixpoint."""
    track_cluster = {t: c for c, cluster in clusters.items() for t in cluster["trackIds"]}
    final = dict(initial)
    reasons: dict[str, set[str]] = defaultdict(set)
    for track_id in pinned:
        cluster_id = track_cluster[track_id]
        if final[cluster_id] != TRAINING:
            reasons[cluster_id].add("pinned-training")
            final[cluster_id] = TRAINING
    components = _components(links)
    changed = True
    while changed:
        changed = False
        for members, why in components:
            touched = {track_cluster[t] for t in members}
            if len({final[c] for c in touched}) > 1:
                for cluster_id in touched:
                    reasons[cluster_id].update(why)
                    if final[cluster_id] != TRAINING:
                        final[cluster_id] = TRAINING
                        changed = True
    moves = [
        {"clusterId": c, "from": initial[c], "to": TRAINING, "reasons": sorted(reasons[c])}
        for c in sorted(final)
        if final[c] != initial[c]
    ]
    return final, moves


def build_partition(corpus: CorpusManifest, policy: dict, links: list[LinkGroup], audit_hashes: dict[str, str | None]) -> dict:
    parse_policy(policy)
    require(set(audit_hashes) == {"recurrence", "duplicate"}, "partition_audit_hashes_invalid")
    for value in audit_hashes.values():
        if value is not None:
            require_sha256(value, "partition_audit_hashes_invalid")
    if corpus.corpus_kind == "operational":
        # An operational partition is never built without both leakage audits.
        require(all(v is not None for v in audit_hashes.values()), "partition_operational_requires_audits")
    for group in links:
        require(group.track_ids <= corpus.tracks.keys(), f"partition_link_unknown_track:{group.group_id}")
        require(len(group.track_ids) >= 2, f"partition_link_too_small:{group.group_id}")
    epoch, clusters = _clusters(corpus, policy["dateBlockDays"], date.fromisoformat(policy["dateEpoch"]))
    initial = _initial_assignment(clusters, policy)
    pinned = tuple(policy.get("pinnedTrainingTrackIds", []))
    require(set(pinned) <= corpus.tracks.keys(), "partition_pinned_unknown_track")
    final, moves = _resolve(clusters, initial, links, pinned)
    track_cluster = {t: c for c, cluster in clusters.items() for t in cluster["trackIds"]}
    document = {
        "schemaVersion": PARTITION_SCHEMA,
        "corpusManifestSha256": corpus.sha256,
        "policy": policy,
        "corpusEpoch": epoch.isoformat(),
        "audits": {
            "recurrenceAuditSha256": audit_hashes["recurrence"],
            "duplicateAuditSha256": audit_hashes["duplicate"],
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
                "initialPartition": initial[cid],
                "partition": final[cid],
            }
            for cid, c in sorted(clusters.items())
        ],
        "moves": moves,
        "assignments": [{"trackId": t, "clusterId": track_cluster[t], "partition": final[track_cluster[t]]} for t in sorted(track_cluster)],
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


def verify_partition(corpus: CorpusManifest, document: dict, links: list[LinkGroup], audit_hashes: dict[str, str | None]) -> None:
    """Independent re-check of every invariant a partition manifest must satisfy.

    ``links`` and ``audit_hashes`` come from the audits actually supplied; they must be
    the audits the manifest names, so a partition cannot be verified against a
    different (or no) audit.
    """
    require(document.get("schemaVersion") == PARTITION_SCHEMA, "partition_schema")
    require(document.get("corpusManifestSha256") == corpus.sha256, "partition_corpus_mismatch")
    require(
        document.get("audits") == {"recurrenceAuditSha256": audit_hashes.get("recurrence"), "duplicateAuditSha256": audit_hashes.get("duplicate")},
        "partition_audits_mismatch",
    )
    assignments = document["assignments"]
    ids = [a["trackId"] for a in assignments]
    require(len(ids) == len(set(ids)), "partition_track_assigned_twice")
    require(set(ids) == set(corpus.tracks), "partition_track_coverage")
    for entry in assignments:
        require(entry["partition"] in PARTITIONS, f"partition_unknown:{entry['partition']}")
    counts = {p: sum(a["partition"] == p for a in assignments) for p in PARTITIONS}
    for partition in PARTITIONS:
        require(counts[partition] > 0, f"partition_empty:{partition}")  # tuning and selection may not collapse
    cluster_partition = {c["clusterId"]: c["partition"] for c in document["clusters"]}
    for entry in assignments:
        # No Track ever leaves its site/date-block cluster's partition.
        require(entry["partition"] == cluster_partition.get(entry["clusterId"]), f"partition_cluster_fragmented:{entry['clusterId']}")
    for move in document["moves"]:
        require(move["to"] == TRAINING, f"partition_move_invalid:{move['clusterId']}")
    by_track = {a["trackId"]: a["partition"] for a in assignments}
    for group in links:
        require(len({by_track[t] for t in group.track_ids}) == 1, f"partition_link_spans_partitions:{group.kind}:{group.group_id}")
    expected = build_partition(corpus, document["policy"], links, audit_hashes)
    require(expected["clusters"] == document["clusters"], "partition_clusters_not_reproducible")
    require(expected["assignments"] == assignments and expected["moves"] == document["moves"], "partition_not_reproducible")
    require(expected["checks"] == document["checks"], "partition_checks_mismatch")


def partition_of(document: dict) -> dict[str, str]:
    return {a["trackId"]: a["partition"] for a in document["assignments"]}


def ensure_readable(partition: str) -> None:
    if partition not in EVALUATION_READABLE:
        raise CorpusError(f"frozen_test_not_readable_for_selection:{partition}")
