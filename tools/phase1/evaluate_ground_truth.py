#!/usr/bin/env python3
"""Deterministic Phase-1 ground-truth evaluator.

The evaluator is intentionally release-agnostic. It consumes only reviewed
ground-truth bytes, normalized Track-detail data obtained from public MAVI APIs,
and the versioned acceptance profile. Formal qualification fails closed unless
both supported classes have reviewed coverage and approved thresholds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

SUPPORTED_CLASSES = ("Person", "Vehicle")


class EvaluationError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _load_json(path: Path) -> tuple[dict[str, Any], str]:
    data = path.read_bytes()
    try:
        value = json.loads(data)
    except json.JSONDecodeError as exc:
        raise EvaluationError("json_invalid") from exc
    if not isinstance(value, dict):
        raise EvaluationError("json_root_invalid")
    return value, hashlib.sha256(data).hexdigest()


def _require_number(value: Any, code: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationError(code)
    result = Decimal(str(value))
    if not result.is_finite():
        raise EvaluationError(code)
    return result


def _validate_box(raw: Any) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    if not isinstance(raw, dict) or set(raw) != {"x", "y", "width", "height"}:
        raise EvaluationError("bounding_box_invalid")
    x, y, width, height = (_require_number(raw[k], "bounding_box_invalid") for k in ("x", "y", "width", "height"))
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
        raise EvaluationError("bounding_box_out_of_range")
    return x, y, width, height


def validate_profile(profile: dict[str, Any]) -> dict[str, Any]:
    if profile.get("schemaVersion") != "mavi-phase1-acceptance-profile-v1":
        raise EvaluationError("acceptance_profile_schema_invalid")
    mode = profile.get("mode")
    if mode not in {"baseline", "qualification"}:
        raise EvaluationError("acceptance_profile_mode_invalid")
    matching = profile.get("matching")
    if not isinstance(matching, dict):
        raise EvaluationError("acceptance_profile_matching_invalid")
    temporal = _require_number(matching.get("minimumTemporalIou"), "minimum_temporal_iou_invalid")
    spatial = _require_number(matching.get("minimumSpatialIou"), "minimum_spatial_iou_invalid")
    if temporal < 0 or temporal > 1 or spatial < 0 or spatial > 1:
        raise EvaluationError("minimum_iou_out_of_range")
    span = matching.get("maximumInterpolationSpanMs")
    scale = matching.get("iouFixedPrecisionScale")
    if not isinstance(span, int) or isinstance(span, bool) or span <= 0:
        raise EvaluationError("interpolation_span_invalid")
    if not isinstance(scale, int) or isinstance(scale, bool) or scale <= 0:
        raise EvaluationError("iou_scale_invalid")
    if matching.get("iouRounding") != "half-up":
        raise EvaluationError("iou_rounding_invalid")
    if profile.get("requiredClasses") != list(SUPPORTED_CLASSES):
        raise EvaluationError("required_classes_invalid")
    corpus_sha = profile.get("qualificationCorpusManifestSha256")
    if mode == "qualification" and (
        not isinstance(corpus_sha, str)
        or len(corpus_sha) != 64
        or any(ch not in "0123456789abcdef" for ch in corpus_sha)
    ):
        raise EvaluationError("qualification_corpus_identity_not_approved")
    if mode == "baseline" and corpus_sha is not None and (
        not isinstance(corpus_sha, str)
        or len(corpus_sha) != 64
        or any(ch not in "0123456789abcdef" for ch in corpus_sha)
    ):
        raise EvaluationError("qualification_corpus_identity_invalid")

    thresholds = profile.get("classThresholds")
    if not isinstance(thresholds, dict) or set(thresholds) != set(SUPPORTED_CLASSES):
        raise EvaluationError("class_thresholds_invalid")
    if mode == "qualification":
        for object_class in SUPPORTED_CLASSES:
            value = thresholds[object_class]
            if not isinstance(value, dict) or set(value) != {"precision", "recall", "f1"}:
                raise EvaluationError("qualification_threshold_missing")
            for metric in ("precision", "recall", "f1"):
                number = _require_number(value[metric], "qualification_threshold_invalid")
                if number < 0 or number > 1:
                    raise EvaluationError("qualification_threshold_invalid")
    return profile


def validate_ground_truth(gt: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    required = {"schemaVersion", "videoSha256", "durationMs", "cameraCode", "evaluationWindows", "events"}
    if set(gt) != required or gt.get("schemaVersion") != "mavi-phase1-ground-truth-v1":
        raise EvaluationError("ground_truth_schema_invalid")
    video_sha = gt.get("videoSha256")
    if not isinstance(video_sha, str) or len(video_sha) != 64 or any(ch not in "0123456789abcdef" for ch in video_sha):
        raise EvaluationError("ground_truth_video_sha_invalid")
    duration = gt.get("durationMs")
    if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
        raise EvaluationError("ground_truth_duration_invalid")
    if not isinstance(gt.get("cameraCode"), str) or not gt["cameraCode"].strip():
        raise EvaluationError("ground_truth_camera_invalid")

    windows = gt.get("evaluationWindows")
    if not isinstance(windows, list) or not windows:
        raise EvaluationError("evaluation_windows_required")
    previous_end = -1
    normalized_windows: list[tuple[int, int]] = []
    for window in windows:
        if not isinstance(window, dict) or set(window) != {"startOffsetMs", "endOffsetMs"}:
            raise EvaluationError("evaluation_window_invalid")
        start, end = window["startOffsetMs"], window["endOffsetMs"]
        if not isinstance(start, int) or not isinstance(end, int) or isinstance(start, bool) or isinstance(end, bool):
            raise EvaluationError("evaluation_window_invalid")
        if start < 0 or start >= end or end > duration or start < previous_end:
            raise EvaluationError("evaluation_window_invalid")
        normalized_windows.append((start, end))
        previous_end = end

    events = gt.get("events")
    if not isinstance(events, list):
        raise EvaluationError("ground_truth_events_invalid")
    seen_ids: set[str] = set()
    max_span = profile["matching"]["maximumInterpolationSpanMs"]
    for event in events:
        expected = {"eventId", "objectClass", "startOffsetMs", "endOffsetMs", "spatialSamples"}
        if not isinstance(event, dict) or set(event) != expected:
            raise EvaluationError("ground_truth_event_invalid")
        event_id = event["eventId"]
        if not isinstance(event_id, str) or not event_id or event_id in seen_ids:
            raise EvaluationError("ground_truth_event_id_invalid")
        seen_ids.add(event_id)
        if event["objectClass"] not in SUPPORTED_CLASSES:
            raise EvaluationError("ground_truth_class_invalid")
        start, end = event["startOffsetMs"], event["endOffsetMs"]
        if not isinstance(start, int) or not isinstance(end, int) or isinstance(start, bool) or isinstance(end, bool):
            raise EvaluationError("ground_truth_event_interval_invalid")
        if start < 0 or start >= end or end > duration:
            raise EvaluationError("ground_truth_event_interval_invalid")
        if not any(start >= ws and end <= we for ws, we in normalized_windows):
            raise EvaluationError("ground_truth_event_outside_evaluation_window")
        samples = event["spatialSamples"]
        if not isinstance(samples, list) or len(samples) < 2:
            raise EvaluationError("spatial_samples_invalid")
        offsets: list[int] = []
        for sample in samples:
            if not isinstance(sample, dict) or set(sample) != {"offsetMs", "boundingBox"}:
                raise EvaluationError("spatial_sample_invalid")
            offset = sample["offsetMs"]
            if not isinstance(offset, int) or isinstance(offset, bool) or offset < start or offset > end:
                raise EvaluationError("spatial_sample_offset_invalid")
            _validate_box(sample["boundingBox"])
            offsets.append(offset)
        if offsets != sorted(set(offsets)) or offsets[0] != start or offsets[-1] != end:
            raise EvaluationError("spatial_sample_coverage_invalid")
        if any(b - a > max_span for a, b in zip(offsets, offsets[1:])):
            raise EvaluationError("spatial_sample_gap_invalid")
    return gt


def validate_tracks(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise EvaluationError("tracks_invalid")
    ids: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in raw:
        required = {"id", "processingRunId", "videoAssetId", "objectClass", "startOffsetMs", "endOffsetMs", "representative"}
        if not isinstance(item, dict) or set(item) != required:
            raise EvaluationError("track_invalid")
        track_id = item["id"]
        if not isinstance(track_id, str) or not track_id or track_id in ids:
            raise EvaluationError("track_id_invalid")
        ids.add(track_id)
        if item["objectClass"] not in SUPPORTED_CLASSES:
            raise EvaluationError("track_class_invalid")
        start, end = item["startOffsetMs"], item["endOffsetMs"]
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or start >= end:
            raise EvaluationError("track_interval_invalid")
        rep = item["representative"]
        if not isinstance(rep, dict) or set(rep) != {"videoOffsetMs", "boundingBox"}:
            raise EvaluationError("track_representative_invalid")
        if not isinstance(rep["videoOffsetMs"], int) or rep["videoOffsetMs"] < start or rep["videoOffsetMs"] > end:
            raise EvaluationError("track_representative_offset_invalid")
        _validate_box(rep["boundingBox"])
        result.append(item)
    return result


def _interval_iou(a0: int, a1: int, b0: int, b1: int) -> Decimal:
    intersection = max(0, min(a1, b1) - max(a0, b0))
    union = max(a1, b1) - min(a0, b0)
    return Decimal(intersection) / Decimal(union) if union else Decimal(0)


def _box_iou(a: tuple[Decimal, Decimal, Decimal, Decimal], b: tuple[Decimal, Decimal, Decimal, Decimal]) -> Decimal:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix0, iy0 = max(ax, bx), max(ay, by)
    ix1, iy1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    iw, ih = max(Decimal(0), ix1 - ix0), max(Decimal(0), iy1 - iy0)
    intersection = iw * ih
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else Decimal(0)


def _reference_box(event: dict[str, Any], offset: int, max_span: int) -> tuple[Decimal, Decimal, Decimal, Decimal] | None:
    samples = event["spatialSamples"]
    for sample in samples:
        if sample["offsetMs"] == offset:
            return _validate_box(sample["boundingBox"])
    left = None
    right = None
    for sample in samples:
        if sample["offsetMs"] < offset:
            left = sample
        elif sample["offsetMs"] > offset:
            right = sample
            break
    if left is None or right is None or right["offsetMs"] - left["offsetMs"] > max_span:
        return None
    fraction = Decimal(offset - left["offsetMs"]) / Decimal(right["offsetMs"] - left["offsetMs"])
    lbox, rbox = _validate_box(left["boundingBox"]), _validate_box(right["boundingBox"])
    return tuple(l + (r - l) * fraction for l, r in zip(lbox, rbox))  # type: ignore[return-value]


def _fixed(value: Decimal, scale: int) -> int:
    return int((value * Decimal(scale)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class Edge:
    event_index: int
    track_index: int
    spatial_iou: Decimal
    temporal_iou: Decimal
    spatial_fixed: int
    temporal_fixed: int


def _candidate_edges(events: list[dict[str, Any]], tracks: list[dict[str, Any]], profile: dict[str, Any]) -> list[Edge]:
    minimum_temporal = Decimal(str(profile["matching"]["minimumTemporalIou"]))
    minimum_spatial = Decimal(str(profile["matching"]["minimumSpatialIou"]))
    max_span = profile["matching"]["maximumInterpolationSpanMs"]
    scale = profile["matching"]["iouFixedPrecisionScale"]
    result: list[Edge] = []
    for ei, event in enumerate(events):
        for ti, track in enumerate(tracks):
            if event["objectClass"] != track["objectClass"]:
                continue
            representative_offset = track["representative"]["videoOffsetMs"]
            if representative_offset < event["startOffsetMs"] or representative_offset > event["endOffsetMs"]:
                continue
            temporal = _interval_iou(event["startOffsetMs"], event["endOffsetMs"], track["startOffsetMs"], track["endOffsetMs"])
            if temporal < minimum_temporal:
                continue
            reference = _reference_box(event, representative_offset, max_span)
            if reference is None:
                continue
            spatial = _box_iou(reference, _validate_box(track["representative"]["boundingBox"]))
            if spatial < minimum_spatial:
                continue
            result.append(Edge(ei, ti, spatial, temporal, _fixed(spatial, scale), _fixed(temporal, scale)))
    return result


def _best_matching(events: list[dict[str, Any]], tracks: list[dict[str, Any]], edges: list[Edge]) -> list[Edge]:
    """Polynomial min-cost maximum-flow with deterministic lexicographic objectives.

    Flow cardinality is maximized first by augmenting until no source→sink path
    remains. For that fixed cardinality, edge reward encodes the remaining
    objectives strictly in this order:
      1. total fixed-precision spatial IoU;
      2. total fixed-precision temporal IoU;
      3. canonical lexical eventId/trackId pair set.

    The lexical component uses a bit significance per sorted candidate pair.
    Python integers are unbounded, so this remains exact without floating-point
    tie behavior.
    """
    if not events or not tracks or not edges:
        return []

    pair_keys = sorted(
        {
            (events[edge.event_index]["eventId"], tracks[edge.track_index]["id"])
            for edge in edges
        }
    )
    pair_rank = {key: index for index, key in enumerate(pair_keys)}
    pair_count = len(pair_keys)
    tie_base = 1 << (pair_count + 1)
    scale = max(
        1,
        max(
            max(edge.spatial_fixed, edge.temporal_fixed)
            for edge in edges
        ),
    )
    maximum_flow = min(len(events), len(tracks))
    temporal_span = maximum_flow * scale + 1
    spatial_multiplier = temporal_span * tie_base

    node_source = 0
    event_base = 1
    track_base = event_base + len(events)
    node_sink = track_base + len(tracks)
    node_count = node_sink + 1

    graph: list[list[list[int | Edge | None]]] = [[] for _ in range(node_count)]

    def add_arc(
        source: int,
        target: int,
        capacity: int,
        cost: int,
        edge_ref: Edge | None = None,
    ) -> None:
        forward: list[int | Edge | None] = [target, len(graph[target]), capacity, cost, edge_ref]
        reverse: list[int | Edge | None] = [source, len(graph[source]), 0, -cost, None]
        graph[source].append(forward)
        graph[target].append(reverse)

    for event_index in range(len(events)):
        add_arc(node_source, event_base + event_index, 1, 0)
    for track_index in range(len(tracks)):
        add_arc(track_base + track_index, node_sink, 1, 0)

    for edge in sorted(
        edges,
        key=lambda item: (
            events[item.event_index]["eventId"],
            tracks[item.track_index]["id"],
        ),
    ):
        key = (
            events[edge.event_index]["eventId"],
            tracks[edge.track_index]["id"],
        )
        lexical_reward = 1 << (pair_count - pair_rank[key])
        reward = (
            edge.spatial_fixed * spatial_multiplier
            + edge.temporal_fixed * tie_base
            + lexical_reward
        )
        add_arc(
            event_base + edge.event_index,
            track_base + edge.track_index,
            1,
            -reward,
            edge,
        )

    # Bellman-Ford is deliberate here. Residual reverse arcs can carry negative
    # costs, and the qualification corpus is small enough that O(FVE) is both
    # predictable and materially safer than exponential assignment search.
    while True:
        infinity = None
        distance: list[int | None] = [infinity] * node_count
        previous: list[tuple[int, int] | None] = [None] * node_count
        distance[node_source] = 0

        for _ in range(node_count - 1):
            changed = False
            for source_node in range(node_count):
                source_distance = distance[source_node]
                if source_distance is None:
                    continue
                for arc_index, arc in enumerate(graph[source_node]):
                    target = int(arc[0])
                    capacity = int(arc[2])
                    cost = int(arc[3])
                    if capacity <= 0:
                        continue
                    candidate = source_distance + cost
                    current = distance[target]
                    predecessor_key = (source_node, arc_index)
                    if (
                        current is None
                        or candidate < current
                        or (
                            candidate == current
                            and (
                                previous[target] is None
                                or predecessor_key < previous[target]
                            )
                        )
                    ):
                        distance[target] = candidate
                        previous[target] = predecessor_key
                        changed = True
            if not changed:
                break

        if distance[node_sink] is None:
            break

        node = node_sink
        path: list[tuple[int, int]] = []
        while node != node_source:
            predecessor = previous[node]
            if predecessor is None:
                raise EvaluationError("matching_residual_path_invalid")
            path.append(predecessor)
            source_node, arc_index = predecessor
            node = source_node

        for source_node, arc_index in reversed(path):
            arc = graph[source_node][arc_index]
            target = int(arc[0])
            reverse_index = int(arc[1])
            arc[2] = int(arc[2]) - 1
            reverse_arc = graph[target][reverse_index]
            reverse_arc[2] = int(reverse_arc[2]) + 1

    selected: list[Edge] = []
    for event_index in range(len(events)):
        node = event_base + event_index
        for arc in graph[node]:
            edge_ref = arc[4]
            if isinstance(edge_ref, Edge) and int(arc[2]) == 0:
                selected.append(edge_ref)

    return sorted(
        selected,
        key=lambda edge: (
            events[edge.event_index]["eventId"],
            tracks[edge.track_index]["id"],
        ),
    )

def _metric(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _summarize(gt_count: int, track_count: int, matched: int) -> dict[str, Any]:
    missed = gt_count - matched
    unmatched = track_count - matched
    precision = _metric(matched, matched + unmatched)
    recall = _metric(matched, matched + missed)
    f1 = None if precision is None or recall is None or precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return {
        "groundTruthEventCount": gt_count,
        "producedTrackCount": track_count,
        "matchedCount": matched,
        "missedCount": missed,
        "unmatchedTrackCount": unmatched,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def evaluate(gt: dict[str, Any], tracks: list[dict[str, Any]], profile: dict[str, Any]) -> dict[str, Any]:
    validate_profile(profile)
    validate_ground_truth(gt, profile)
    validate_tracks(tracks)

    windows = [(w["startOffsetMs"], w["endOffsetMs"]) for w in gt["evaluationWindows"]]
    scored_tracks = [
        track for track in tracks
        if any(track["endOffsetMs"] > start and track["startOffsetMs"] < end for start, end in windows)
    ]
    # Clip track intervals to the first intersecting annotated window for temporal scoring.
    normalized_tracks: list[dict[str, Any]] = []
    for track in scored_tracks:
        intersections = [(max(track["startOffsetMs"], s), min(track["endOffsetMs"], e)) for s, e in windows if track["endOffsetMs"] > s and track["startOffsetMs"] < e]
        if len(intersections) != 1:
            raise EvaluationError("track_intersects_multiple_evaluation_windows")
        start, end = intersections[0]
        clone = dict(track)
        clone["startOffsetMs"], clone["endOffsetMs"] = start, end
        normalized_tracks.append(clone)

    edges = _candidate_edges(gt["events"], normalized_tracks, profile)
    matching = _best_matching(gt["events"], normalized_tracks, edges)

    per_class: dict[str, Any] = {}
    for object_class in SUPPORTED_CLASSES:
        gt_indices = {i for i, event in enumerate(gt["events"]) if event["objectClass"] == object_class}
        track_indices = {i for i, track in enumerate(normalized_tracks) if track["objectClass"] == object_class}
        class_matches = [edge for edge in matching if edge.event_index in gt_indices]
        summary = _summarize(len(gt_indices), len(track_indices), len(class_matches))
        summary["temporalIou"] = [float(edge.temporal_iou) for edge in class_matches]
        summary["spatialIou"] = [float(edge.spatial_iou) for edge in class_matches]
        per_class[object_class] = summary

    overall = _summarize(len(gt["events"]), len(normalized_tracks), len(matching))
    formal = profile["mode"] == "qualification"
    qualification_pass: bool | None = None
    failures: list[str] = []
    if formal:
        for object_class in SUPPORTED_CLASSES:
            metrics = per_class[object_class]
            if metrics["groundTruthEventCount"] == 0:
                failures.append(f"{object_class}:coverage_zero")
                continue
            thresholds = profile["classThresholds"][object_class]
            for metric in ("precision", "recall", "f1"):
                actual = metrics[metric]
                if actual is None or actual < thresholds[metric]:
                    failures.append(f"{object_class}:{metric}")
        qualification_pass = not failures

    return {
        "schemaVersion": "mavi-phase1-evaluation-result-v1",
        "mode": profile["mode"],
        "perClass": per_class,
        "overall": overall,
        "matching": [
            {
                "eventId": gt["events"][edge.event_index]["eventId"],
                "trackId": normalized_tracks[edge.track_index]["id"],
                "spatialIou": float(edge.spatial_iou),
                "temporalIou": float(edge.temporal_iou),
            }
            for edge in sorted(matching, key=lambda e: (gt["events"][e.event_index]["eventId"], normalized_tracks[e.track_index]["id"]))
        ],
        "qualification": {
            "passed": qualification_pass,
            "failures": failures,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--tracks", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        gt, gt_sha = _load_json(args.ground_truth)
        tracks_raw, tracks_sha = _load_json(args.tracks)
        profile, profile_sha = _load_json(args.profile)
        tracks = tracks_raw.get("tracks")
        result = evaluate(gt, tracks, profile)
        result["inputs"] = {
            "groundTruthSha256": gt_sha,
            "tracksSha256": tracks_sha,
            "profileSha256": profile_sha,
            "videoSha256": gt["videoSha256"],
        }
    except EvaluationError as exc:
        print(json.dumps({"ok": False, "code": exc.code}, sort_keys=True))
        return 2

    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    if result["mode"] == "qualification" and result["qualification"]["passed"] is not True:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
