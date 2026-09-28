"""The labelling pilot (S2c plan §10.3; qualification plan §4, R1 step 1).

The pilot is drawn from the **training** partition only: its results decide vocabulary
merges and removals, so none of it may touch tuning, selection or the frozen test. Its
decision thresholds are the task's ``pilotDecisionRules``, which must be owner-confirmed
before any pilot label exists and are never lowered afterwards (``task.confirm_rules``).
The pilot report *recommends*; the owner decides through ``task.freeze_task``.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from .agreement import agreement_report, independent_labels
from .annotation import Label
from .canonical import document_sha256, hash_rank, require, require_int
from .manifest import CorpusManifest
from .partition import TRAINING, partition_of
from .task import Task, attribute_verdicts, require_confirmed_rules

PILOT_SCHEMA = "mavi-attribute-pilot-report-v1"


def sample_pilot_tracks(corpus: CorpusManifest, partition: dict, size: int, seed: str) -> list[str]:
    """Deterministic, camera-stratified round-robin over training Tracks only."""
    require_int(size, "pilot_size", 1)
    parts = partition_of(partition)
    by_camera: dict[str, list[str]] = defaultdict(list)
    for track_id, part in parts.items():
        if part == TRAINING:
            by_camera[corpus.source_of(track_id).camera_id].append(track_id)
    for camera in by_camera:
        by_camera[camera].sort(key=lambda t: hash_rank(seed, "pilot", t))
    cameras = sorted(by_camera, key=lambda c: hash_rank(seed, "pilot-camera", c))
    chosen: list[str] = []
    depth = 0
    while len(chosen) < size and any(depth < len(by_camera[c]) for c in cameras):
        for camera in cameras:
            if depth < len(by_camera[camera]) and len(chosen) < size:
                chosen.append(by_camera[camera][depth])
        depth += 1
    require(all(parts[t] == TRAINING for t in chosen), "pilot_outside_training")
    return chosen


def _swap_share(grouped: dict[tuple[str, str], list[tuple[str, Label]]], first: str, second: str) -> tuple[int, int]:
    """Units where one rater says only ``first`` and another only ``second`` (the distinction fails)."""
    swaps = considered = 0
    units = {u for (u, a) in grouped if a == first} & {u for (u, a) in grouped if a == second}
    for unit in units:
        a = dict(grouped[(unit, first)])
        b = dict(grouped[(unit, second)])
        raters = sorted(set(a) & set(b))
        says = {r: (a[r].value == "present", b[r].value == "present") for r in raters}
        if any(x or y for x, y in says.values()) and len(raters) >= 2:
            considered += 1
            if (True, False) in says.values() and (False, True) in says.values():
                swaps += 1
    return swaps, considered


def _pair_confusion(grouped: dict[tuple[str, str], list[tuple[str, Label]]], attribute: str, a: str, b: str) -> tuple[int, int]:
    """Rater pairs on a double-labelled unit where either chose a or b; confused when one chose each."""
    from itertools import combinations

    confused = considered = 0
    for (unit, name), entries in grouped.items():
        if name != attribute or len(entries) < 2:
            continue
        for (_, x), (_, y) in combinations(entries, 2):
            chosen = {x.category, y.category}
            if chosen & {a, b}:
                considered += 1
                confused += chosen == {a, b}
    return confused, considered


def pilot_report(
    task: Task,
    corpus: CorpusManifest,
    partition: dict,
    partition_sha256: str,
    batches: list[tuple[dict, list[Label]]],
    assignments: dict[str, dict],
    annotators: dict[str, bool],
    registered_batches: set[str],
) -> dict:
    rules = require_confirmed_rules(task)
    parts = partition_of(partition)
    for batch, labels in batches:
        require(assignments[batch["assignmentId"]]["phase"] == "pilot", "pilot_report_non_pilot_batch")
        for label in labels:
            require(parts[label.unit.split(":")[1]] == TRAINING, "pilot_report_outside_training")
    agreement = agreement_report("pilot", corpus, partition, partition_sha256, task.sha256, batches, assignments, annotators, set(), registered_batches)

    grouped = independent_labels(batches, assignments)
    recommendations = list(attribute_verdicts(task, agreement, rules).values())
    merges = []
    for candidate in task.document["valueMergeCandidates"]:
        a, b = sorted(candidate["values"])
        confused, considered = _pair_confusion(grouped, candidate["attributeType"], a, b)
        share = None if considered == 0 else confused / considered
        merges.append({"attributeType": candidate["attributeType"], "values": [a, b], "confusedPairs": confused, "consideredPairs": considered, "share": None if share is None else round(share, 6), "recommendMerge": share is not None and share >= rules["mergeConfusionShare"]})
    attribute_merges = []
    for candidate in task.document["attributeMergeCandidates"]:
        first, second = sorted(candidate["attributeTypes"])
        swaps, considered = _swap_share(grouped, first, second)
        share = None if considered == 0 else swaps / considered
        attribute_merges.append({"attributeTypes": [first, second], "swaps": swaps, "considered": considered, "share": None if share is None else round(share, 6), "recommendMerge": share is not None and share >= rules["mergeConfusionShare"]})
    seconds = [b["activeSeconds"] for b, _ in batches if b["activeSeconds"] is not None]
    labels_count = sum(len(l) for _, l in batches)
    prevalence = {
        a["attributeType"]: a["categoryCounts"] for a in agreement["attributes"]
    }
    document = {
        "schemaVersion": PILOT_SCHEMA,
        "corpusKind": corpus.corpus_kind,
        "taskSha256": task.sha256,
        "pilotDecisionRules": rules,
        "agreementReportSha256": agreement["reportSha256"],
        "agreement": agreement,
        "prevalence": prevalence,
        "timing": {"batchesWithTiming": len(seconds), "activeSeconds": sum(seconds), "secondsPerLabel": None if not seconds or not labels_count else round(sum(seconds) / labels_count, 3)},
        "attributeRecommendations": recommendations,
        "valueMergeRecommendations": merges,
        "attributeMergeRecommendations": attribute_merges,
        "cameras": dict(sorted(Counter(corpus.source_of(u.split(":")[1]).camera_id for u in {unit for (unit, _a) in grouped}).items())),
    }
    document["reportSha256"] = document_sha256(document)
    return document
