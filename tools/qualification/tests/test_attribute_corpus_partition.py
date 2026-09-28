"""S2c.1: cluster-aware partitioning, recurrence and duplicate leakage control."""

from __future__ import annotations

import copy
import hashlib
import io
import random
from collections import defaultdict

import pytest
from attribute_corpus_fixtures import build_corpus, policy

from attributes.corpus.canonical import CorpusError
from attributes.corpus.duplicates import build_duplicate_audit, dhash64, fingerprint_corpus, hamming, parse_duplicate_audit
from attributes.corpus.manifest import parse_corpus
from attributes.corpus.partition import (
    FROZEN,
    PARTITIONS,
    TRAINING,
    LinkGroup,
    build_partition,
    partition_of,
    verify_partition,
)
from attributes.corpus.recurrence import parse_recurrence


@pytest.fixture(scope="module")
def corpus():
    return parse_corpus(build_corpus(sites=4, cameras_per_site=3, days=12))


def _partition(corpus, links=(), **overrides):
    return build_partition(corpus, policy(**overrides), list(links), {"recurrence": None, "duplicate": None})


def test_partition_is_deterministic_and_seed_dependent(corpus) -> None:
    assert _partition(corpus) == _partition(corpus)
    assert partition_of(_partition(corpus)) != partition_of(_partition(corpus, seed="another-seed"))


def test_every_track_is_assigned_exactly_once_and_all_four_partitions_exist(corpus) -> None:
    document = _partition(corpus)
    ids = [a["trackId"] for a in document["assignments"]]
    assert len(ids) == len(set(ids)) == len(corpus.tracks)
    assert {a["partition"] for a in document["assignments"]} == set(PARTITIONS)
    verify_partition(corpus, document, [])


def test_no_site_date_cluster_crosses_partitions(corpus) -> None:
    document = _partition(corpus)
    by_cluster = defaultdict(set)
    for entry in document["assignments"]:
        by_cluster[entry["clusterId"]].add(entry["partition"])
    assert all(len(p) == 1 for p in by_cluster.values())
    # All cameras of one site on the same day share a partition.
    by_site_day = defaultdict(set)
    parts = partition_of(document)
    for track in corpus.tracks.values():
        source = corpus.sources[track.source_id]
        by_site_day[(source.site_id, source.recording_date)].add(parts[track.track_id])
    assert all(len(p) == 1 for p in by_site_day.values())


def test_frozen_test_holds_a_whole_site_and_the_latest_blocks_of_seen_sites(corpus) -> None:
    document = _partition(corpus)
    assert document["checks"]["unseenFrozenCameras"], "a held-out site gives cameras unseen elsewhere"
    frozen_clusters = [c for c in document["clusters"] if c["partition"] == FROZEN]
    seen_sites = {c["siteId"] for c in document["clusters"] if c["partition"] != FROZEN}
    for site in seen_sites:
        blocks = sorted(c["dateBlock"] for c in document["clusters"] if c["siteId"] == site)
        frozen = sorted(c["dateBlock"] for c in frozen_clusters if c["siteId"] == site)
        assert frozen == blocks[len(blocks) - len(frozen):], "only the latest, contiguous blocks are held out"
    assert document["checks"]["limitations"] == []


def test_mutation_random_track_split_is_detected(corpus) -> None:
    """Mutation 1: an iid Track-level split must fail verification."""
    document = _partition(corpus)
    rng = random.Random(7)
    for entry in document["assignments"]:
        entry["partition"] = rng.choice(PARTITIONS)
    with pytest.raises(CorpusError, match="partition_cluster_fragmented|partition_move_invalid|partition_not_reproducible"):
        verify_partition(corpus, document, [])


def test_mutation_camera_date_block_in_two_partitions_is_detected(corpus) -> None:
    """Mutation 2: one Track of a cluster moved elsewhere without a recorded move."""
    document = _partition(corpus)
    victim = next(a for a in document["assignments"] if a["partition"] == "selection")
    victim["partition"] = "tuning"
    with pytest.raises(CorpusError, match="partition_cluster_fragmented"):
        verify_partition(corpus, document, [])


def test_mutation_tuning_and_selection_collapsed_is_detected(corpus) -> None:
    """Mutation 5: collapsing selection into tuning leaves an empty partition."""
    document = _partition(corpus)
    for entry in document["assignments"]:
        if entry["partition"] == "selection":
            entry["partition"] = "tuning"
    with pytest.raises(CorpusError, match="partition_empty:selection"):
        verify_partition(corpus, document, [])


def test_shortfalls_are_recorded_as_limitations_not_waived() -> None:
    small = parse_corpus(build_corpus(sites=2, cameras_per_site=1, days=12))
    document = _partition(small)
    assert any(l.startswith("cameras_below_minimum") for l in document["checks"]["limitations"])


# ---- recurrence ------------------------------------------------------------------------


def _cross_partition_pair(corpus, document):
    parts = partition_of(document)
    train = next(t for t, p in sorted(parts.items()) if p == TRAINING and corpus.tracks[t].object_class == "person")
    frozen = next(t for t, p in sorted(parts.items()) if p == FROZEN and corpus.tracks[t].object_class == "person")
    return train, frozen


def _recurrence(corpus, track_ids, status="confirmed"):
    return {
        "schemaVersion": "mavi-attribute-recurrence-audit-v1",
        "corpusManifestSha256": corpus.sha256,
        "groups": [
            {
                "groupId": "rec-1",
                "subjectKind": "person",
                "trackIds": list(track_ids),
                "status": status,
                "proposer": {"kind": "reviewer", "family": None},
                "decision": None if status == "proposed" else {"by": "reviewer-a", "date": "2026-10-02", "note": "same regular subject"},
            }
        ],
    }


def test_confirmed_recurrence_moves_the_whole_group_to_training_with_an_audit_trail(corpus) -> None:
    base = _partition(corpus)
    pair = _cross_partition_pair(corpus, base)
    sha, links = parse_recurrence(_recurrence(corpus, pair), corpus)
    document = build_partition(corpus, policy(), links, {"recurrence": sha, "duplicate": None})
    parts = partition_of(document)
    assert parts[pair[0]] == parts[pair[1]] == TRAINING
    move = next(m for m in document["moves"] if m["trackId"] == pair[1])
    assert move == {"trackId": pair[1], "from": FROZEN, "to": TRAINING, "reasons": ["recurrence:rec-1"]}
    assert len(document["assignments"]) == len(corpus.tracks), "nothing is deleted"
    verify_partition(corpus, document, links)
    assert build_partition(corpus, policy(), links, {"recurrence": sha, "duplicate": None}) == document


def test_mutation_recurring_subject_left_across_partitions_is_detected(corpus) -> None:
    """Mutation 3: undoing the move leaves a confirmed group spanning partitions."""
    base = _partition(corpus)
    pair = _cross_partition_pair(corpus, base)
    _, links = parse_recurrence(_recurrence(corpus, pair), corpus)
    document = build_partition(corpus, policy(), links, {"recurrence": "0" * 64, "duplicate": None})
    document["moves"] = []
    for entry in document["assignments"]:
        if entry["trackId"] == pair[1]:
            entry["partition"] = FROZEN
    with pytest.raises(CorpusError, match="partition_link_spans_partitions|partition_not_reproducible"):
        verify_partition(corpus, document, links)


def test_unconfirmed_or_rejected_recurrence_moves_nothing(corpus) -> None:
    base = _partition(corpus)
    pair = _cross_partition_pair(corpus, base)
    for status in ("proposed", "rejected"):
        _, links = parse_recurrence(_recurrence(corpus, pair, status), corpus)
        assert links == []


def test_recurrence_records_carry_no_identity(corpus) -> None:
    base = _partition(corpus)
    record = _recurrence(corpus, _cross_partition_pair(corpus, base))
    record["groups"][0]["decision"]["note"] = "see /home/reviewer/faces/"
    with pytest.raises(CorpusError, match="path"):
        parse_recurrence(record, corpus)
    record = _recurrence(corpus, _cross_partition_pair(corpus, base))
    record["groups"][0]["groupId"] = "John Smith"
    with pytest.raises(CorpusError):
        parse_recurrence(record, corpus)


def test_similarity_pass_proposals_need_a_reviewer_and_a_declared_family(corpus) -> None:
    record = _recurrence(corpus, _cross_partition_pair(corpus, _partition(corpus)), "proposed")
    record["groups"][0]["proposer"] = {"kind": "similarity-pass", "family": None}
    with pytest.raises(CorpusError, match="proposer_family"):
        parse_recurrence(record, corpus)


# ---- duplicates ------------------------------------------------------------------------


def _png(seed: int, jitter: int = 0) -> bytes:
    from PIL import Image

    rng = random.Random(seed)
    image = Image.new("L", (64, 96))
    image.putdata([rng.randrange(256) for _ in range(64 * 96)])
    image = image.resize((64, 96))
    if jitter:
        noise = random.Random(seed * 31 + jitter)
        image.putdata([min(255, max(0, p + noise.randrange(-jitter, jitter + 1))) for p in image.getdata()])
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_dhash_detects_a_near_duplicate_and_separates_different_images() -> None:
    original, noisy, different = _png(1), _png(1, jitter=3), _png(2)
    assert hamming(dhash64(original), dhash64(noisy)) <= 6
    assert hamming(dhash64(original), dhash64(different)) > 12


def _small_corpus_with_images():
    document = build_corpus(sites=4, cameras_per_site=3, days=12, tracks_per_source=1)
    images = {}
    for index, track in enumerate(document["tracks"]):
        for observation in track["observations"]:
            data = _png(1000 + index * 2 + observation["evidenceRank"])
            images[hashlib.sha256(data).hexdigest()] = data
            observation["sha256"] = hashlib.sha256(data).hexdigest()
    return document, images


def test_duplicate_audit_finds_exact_and_near_duplicates_across_tracks_and_resolves_them() -> None:
    document, images = _small_corpus_with_images()
    corpus = parse_corpus(document)
    base = build_partition(corpus, policy(), [], {"recurrence": None, "duplicate": None})
    parts = partition_of(base)
    train = next(t for t in sorted(parts) if parts[t] == TRAINING)
    frozen = next(t for t in sorted(parts) if parts[t] == FROZEN)
    selection = next(t for t in sorted(parts) if parts[t] == "selection")
    tracks = {t["trackId"]: t for t in document["tracks"]}
    # Exact: the frozen Track's representative is byte-identical to the training one.
    tracks[frozen]["observations"][0]["sha256"] = tracks[train]["observations"][0]["sha256"]
    # Near: the selection Track's representative is a lightly perturbed copy.
    near = _png(1000 + list(tracks).index(train) * 2, jitter=3)
    images[hashlib.sha256(near).hexdigest()] = near
    tracks[selection]["observations"][0]["sha256"] = hashlib.sha256(near).hexdigest()
    corpus = parse_corpus(document)
    fingerprints = fingerprint_corpus(corpus, images.__getitem__)
    audit = build_duplicate_audit(corpus, fingerprints, threshold=6)
    kinds = {p["kind"] for p in audit["pairs"]}
    assert kinds == {"exact", "near"}
    sha, links = parse_duplicate_audit(audit, corpus)
    resolved = build_partition(corpus, policy(), links, {"recurrence": None, "duplicate": sha})
    after = partition_of(resolved)
    assert after[train] == after[frozen] == after[selection] == TRAINING
    verify_partition(corpus, resolved, links)


def test_mutation_duplicate_crossing_partitions_fails_verification() -> None:
    """Mutation 4: a duplicate group left across partitions."""
    document, images = _small_corpus_with_images()
    corpus = parse_corpus(document)
    parts = partition_of(build_partition(corpus, policy(), [], {"recurrence": None, "duplicate": None}))
    a = next(t for t in sorted(parts) if parts[t] == TRAINING)
    b = next(t for t in sorted(parts) if parts[t] == FROZEN)
    tracks = {t["trackId"]: t for t in document["tracks"]}
    tracks[b]["observations"][0]["sha256"] = tracks[a]["observations"][0]["sha256"]
    corpus = parse_corpus(document)
    audit = build_duplicate_audit(corpus, fingerprint_corpus(corpus, images.__getitem__), threshold=6)
    _, links = parse_duplicate_audit(audit, corpus)
    unresolved = build_partition(corpus, policy(), [], {"recurrence": None, "duplicate": None})
    with pytest.raises(CorpusError, match="partition_link_spans_partitions|partition_not_reproducible"):
        verify_partition(corpus, unresolved, links)


def test_duplicate_audit_cannot_be_trimmed_by_hand_and_exact_groups_cannot_be_rejected() -> None:
    document, images = _small_corpus_with_images()
    tracks = document["tracks"]
    tracks[1]["observations"][0]["sha256"] = tracks[0]["observations"][0]["sha256"]
    corpus = parse_corpus(document)
    audit = build_duplicate_audit(corpus, fingerprint_corpus(corpus, images.__getitem__), threshold=6)
    trimmed = copy.deepcopy(audit)
    trimmed["pairs"], trimmed["groups"] = [], []
    with pytest.raises(CorpusError, match="not_reproducible"):
        parse_duplicate_audit(trimmed, corpus)
    rejected = copy.deepcopy(audit)
    rejected["groups"][0]["decision"] = {"status": "rejected", "by": "reviewer-a", "date": "2026-10-02", "note": "x"}
    with pytest.raises(CorpusError, match="exact_cannot_be_rejected"):
        parse_duplicate_audit(rejected, corpus)


def test_crop_integrity_is_checked_before_fingerprinting() -> None:
    document, images = _small_corpus_with_images()
    corpus = parse_corpus(document)
    first = next(iter(images))
    images[first] = images[first] + b"tampered"
    with pytest.raises(CorpusError, match="duplicate_crop_integrity"):
        fingerprint_corpus(corpus, images.__getitem__)


def test_mutation_partition_hash_covers_assignments(corpus) -> None:
    """Mutation 7: the partition identity must change when any assignment changes."""
    from attributes.corpus.canonical import document_sha256

    document = _partition(corpus)
    before = document_sha256(document)
    document["assignments"][0]["partition"] = "tuning" if document["assignments"][0]["partition"] != "tuning" else "selection"
    assert document_sha256(document) != before
