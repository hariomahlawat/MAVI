"""Prediction-independent GT↔MAVI Track association (plan §7; ADR-017 §6) → ``benchmark-association-v1``.

Inputs are the class-free projections only (``ground_truth.GtSequence``, ``mavi_tracks.MaviRun``) and one bound
``policy.Policy``. Every decision is geometry and time.

**Per-frame evidence (§7.2).** For a GT track's non-ignored labelled frame with an evaluable MAVI point (§7.1):
``d`` = distance from the MAVI centre to the GT box centre over the GT box diagonal; the point is *inside* the GT
only if it lies in the box **and** that GT is the nearest-centre one among all GT boxes of the instant containing
it (ties: smaller ``d``, then smaller ``gtTrackId``). At each MAVI observation the IoU is taken against the GT box
at the observation time: in labelled-rate mode the box of the observation's window instant; otherwise linearly
interpolated between the two bracketing labelled frames of that GT track. An observation outside the track's
labelled span, whose window instant is an ignored frame of the track, or whose bracket includes an ignored frame,
has no IoU for that track.

**Pair score (§7.3).** ``overlapFrames`` (non-ignored GT frames with an evaluable point), ``containment`` = inside ÷
overlap, ``meanNormalisedDistance``, ``gtCoverage`` = inside ÷ non-ignored GT frames, ``maviCoverage`` = inside ÷
the Track's evaluable points not on this track's ignored instants, ``longestContainedRun`` over the track's
non-ignored labelled frames in order (a frame without an evaluable point breaks a run), ``spotCheckIoU``.

**Eligibility (§7.4).** All policy floors, the continuity run, and the IoU gate (at least one IoU, every IoU at the
floor). A pair passing every condition except the IoU gate is *verification-failed*; a pair failing any other
condition is simply ineligible, whatever its IoU.

**Assignment.** Eligible pairs in order (containment desc, overlapFrames desc, meanNormalisedDistance asc,
gtTrackId, maviTrackId); greedy one-to-one. Before accepting the best remaining pair (g, m): another unassigned
eligible Track m′ for g comparable on containment, gtCoverage and distance (policy margins) makes g ambiguous;
otherwise another unassigned eligible GT g′ for m comparable on containment, maviCoverage and distance makes m
ambiguous. Neither candidate is assigned; both stay available to others.

**Outcomes** are mutually exclusive by precedence — GT: ``ambiguousGt`` → ``mergedGt`` → ``fragmentedGt`` (no
eligible pair; at least two distinct contained fragments, none verification-failed, together covering the floor)
→ ``unverifiedGt`` → ``unmatchedGt``; MAVI:
``fragmentMavi`` → ``ignoredMavi`` → ``unverifiedMavi`` → ``unmatchedMavi``. Ignored GT tracks are ``ignoredGt``.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from tools.benchmarks.capabilities.vehicle_tracks import alignment
from tools.benchmarks.capabilities.vehicle_tracks import ground_truth as gt_module
from tools.benchmarks.capabilities.vehicle_tracks.ground_truth import Box, GtSequence, GtTrack
from tools.benchmarks.capabilities.vehicle_tracks.mavi_tracks import MaviRun, MaviTrack
from tools.benchmarks.capabilities.vehicle_tracks import policy as policies
from tools.benchmarks.capabilities.vehicle_tracks.policy import IGNORED_MAVI_SHARE, Policy
from tools.benchmarks.core import descriptor as descriptors
from tools.benchmarks.core import envelope as envelopes
from tools.benchmarks.core.identity import (
    S32Error, canonical_json, document_sha256, from_rational, rational, require, require_canonical_rationals,
    validate, write_once)

SCHEMA = "benchmark-association-v1"
CODE = "association_invalid"
LIMITATION = (
    "Centre-only trajectories: per-frame IoU is available only at the MAVI observation frames; the rest of the "
    "overlap is checked by nearest-centre exclusive containment, both coverage floors and continuity "
    "(S3.2d-1 plan §7.7). Development/reference evidence; not independent generalisation evidence.")
GT_STATES = ("ambiguousGt", "mergedGt", "fragmentedGt", "unverifiedGt", "unmatchedGt")
MAVI_STATES = ("fragmentMavi", "ignoredMavi", "unverifiedMavi", "unmatchedMavi")


def _fraction(numerator: int, denominator: int) -> dict[str, Any]:
    return {"numerator": numerator, "denominator": denominator,
            "value": None if denominator == 0 else numerator / denominator}


def _ratio(numerator: int, denominator: int) -> Fraction | None:
    return None if denominator == 0 else Fraction(numerator, denominator)


@dataclass(slots=True)
class Pair:
    gt: str
    mavi: str
    overlap: int
    contained: int
    gt_frames: int
    mavi_points: int
    distance: float | None
    run: int
    ious: tuple[float, ...]
    eligible: bool = False
    verification_failed: bool = False
    contained_instants: frozenset[int] = field(default_factory=frozenset)

    @property
    def containment(self) -> Fraction:
        return _ratio(self.contained, self.overlap) or Fraction(0)

    @property
    def gt_coverage(self) -> Fraction:
        return _ratio(self.contained, self.gt_frames) or Fraction(0)

    @property
    def mavi_coverage(self) -> Fraction:
        return _ratio(self.contained, self.mavi_points) or Fraction(0)

    def document(self) -> dict[str, Any]:
        return {"gtTrackId": self.gt, "maviTrackId": self.mavi, "overlapFrames": self.overlap,
                "containment": _fraction(self.contained, self.overlap), "meanNormalisedDistance": self.distance,
                "gtCoverage": _fraction(self.contained, self.gt_frames),
                "maviCoverage": _fraction(self.contained, self.mavi_points), "longestContainedRun": self.run,
                "spotCheckIoU": list(self.ious)}


# Per-sequence evidence


class _Sequence:
    def __init__(self, gt: GtSequence, run: MaviRun, policy: Policy, labelled_rate: Fraction | None,
                 labelled_mode: bool) -> None:
        self.gt, self.run, self.policy, self.labelled_mode = gt, run, policy, labelled_mode
        self.windows = alignment.windows(gt.instants, labelled_rate)
        floor = policy.min_overlap_frames
        self.ignored = [track for track in gt.tracks if len(track.evaluable) < floor]
        self.active = [track for track in gt.tracks if len(track.evaluable) >= floor]
        # Ignore evidence per instant: ignored frames of active tracks, every frame of an ignored track, regions.
        self.ignore_boxes: dict[int, list[Box]] = {}
        for track in gt.tracks:
            whole = len(track.evaluable) < floor
            for frame in track.frames:
                if frame.ignore or whole:
                    self.ignore_boxes.setdefault(frame.instant, []).append(frame.box)
        for instant, region in gt.ignore_regions:
            self.ignore_boxes.setdefault(instant, []).append(region)
        # Evaluable points of each MAVI Track: instant -> (offset, cx, cy).
        self.evaluable: dict[str, dict[int, tuple[int, float, float]]] = {}
        for track in run.tracks:
            chosen = alignment.evaluable_points(self.windows, [point[0] for point in track.points])
            self.evaluable[track.mavi_track_id] = {instant: track.points[index] for instant, index in chosen.items()}
        # Nearest-centre exclusivity: the one GT that owns a MAVI point at an instant, if any.
        boxes_at: dict[int, list[tuple[str, Box]]] = {}
        for track in self.active:
            for frame in track.evaluable:
                boxes_at.setdefault(frame.instant, []).append((track.gt_track_id, frame.box))
        self.owner: dict[tuple[str, int], str] = {}
        for mavi_id, points in self.evaluable.items():
            for instant, (_, cx, cy) in points.items():
                inside = [(_distance(box, cx, cy), gt_id) for gt_id, box in boxes_at.get(instant, ())
                          if box.contains(cx, cy)]
                if inside:
                    self.owner[(mavi_id, instant)] = min(inside)[1]

    def pair(self, track: GtTrack, mavi: MaviTrack) -> Pair | None:
        points = self.evaluable[mavi.mavi_track_id]
        frames = track.evaluable
        aligned = [frame for frame in frames if frame.instant in points]
        if not aligned:
            return None
        contained: set[int] = set()
        distances = []
        for frame in aligned:
            _, cx, cy = points[frame.instant]
            distances.append(_distance(frame.box, cx, cy))
            if self.owner.get((mavi.mavi_track_id, frame.instant)) == track.gt_track_id:
                contained.add(frame.instant)
        run = longest = 0
        for frame in frames:  # adjacency over the track's non-ignored labelled frames
            run = run + 1 if frame.instant in contained else 0
            longest = max(longest, run)
        ignored_instants = {frame.instant for frame in track.frames if frame.ignore}
        mavi_points = sum(1 for instant in points if instant not in ignored_instants)
        ious = tuple(box.iou(observation.box) for observation in mavi.observations
                     if (box := self.gt_box_at(track, observation.offset_ms)) is not None)
        result = Pair(track.gt_track_id, mavi.mavi_track_id, len(aligned), len(contained), len(frames), mavi_points,
                      math.fsum(distances) / len(distances), longest, ious, contained_instants=frozenset(contained))
        p = self.policy
        geometric = (result.overlap >= p.min_overlap_frames and result.containment >= p.min_containment
                     and result.gt_coverage >= p.min_gt_coverage and result.mavi_coverage >= p.min_mavi_coverage
                     and result.run >= p.min_consecutive_contained_frames)
        # IoU is a float, so the floor is compared as the same float (an IoU of exactly 0.3 meets 3/10; the exact
        # rational of the double 0.3 is a hair below 3/10 and would wrongly fail).
        floor = float(p.min_spot_check_iou)
        verified = bool(ious) and all(value >= floor for value in ious)
        result.eligible = geometric and verified
        result.verification_failed = geometric and not verified
        return result

    def gt_box_at(self, track: GtTrack, offset_ms: int) -> Box | None:
        time = Fraction(offset_ms)
        instant = self.windows.instant_of(time)
        by_instant = {frame.instant: frame for frame in track.frames}
        if instant is not None and instant in by_instant:
            frame = by_instant[instant]
            if frame.ignore:
                return None
            if self.labelled_mode or self.gt.instants[instant] == time:
                return frame.box
        times = [self.gt.instants[frame.instant] for frame in track.frames]
        if not times[0] <= time <= times[-1]:
            return None
        position = bisect.bisect_right(times, time) - 1
        before = track.frames[position]
        if times[position] == time:
            return None if before.ignore else before.box
        after = track.frames[position + 1]
        if before.ignore or after.ignore:
            return None  # never interpolate across an ignored frame
        weight = (time - times[position]) / (times[position + 1] - times[position])
        return before.box.interpolate(after.box, weight)

    def candidates(self) -> list[Pair]:
        """Pairs whose time spans overlap (sweep over MAVI start times), with at least one aligned frame."""
        mavi_tracks = sorted(self.run.tracks, key=lambda track: (track.points[0][0], track.mavi_track_id))
        starts = [Fraction(track.points[0][0]) for track in mavi_tracks]
        pairs = []
        for track in self.active:
            # The GT track's aligned span: the windows of its first and last non-ignored labelled frames.
            low, high = self.windows.lows[track.evaluable[0].instant], self.windows.highs[track.evaluable[-1].instant]
            for mavi in mavi_tracks[:bisect.bisect_left(starts, high)]:
                if Fraction(mavi.points[-1][0]) < low:
                    continue
                pair = self.pair(track, mavi)
                if pair is not None:
                    pairs.append(pair)
        return sorted(pairs, key=lambda pair: (pair.gt, pair.mavi))

    def ignored_points(self, mavi_id: str) -> tuple[int, int]:
        points = self.evaluable[mavi_id]
        inside = sum(1 for instant, (_, cx, cy) in points.items()
                     if any(box.contains(cx, cy) for box in self.ignore_boxes.get(instant, ())))
        return len(points), inside


def _distance(box: Box, cx: float, cy: float) -> float:
    gx, gy = box.centre
    return math.hypot(cx - gx, cy - gy) / box.diagonal


# Assignment and outcomes


def _comparable(best: Pair, other: Pair, coverage: str, policy: Policy) -> bool:
    margin = policy.ambiguity_margin
    return (other.containment >= best.containment - margin
            and getattr(other, coverage) >= getattr(best, coverage) - margin
            and other.distance is not None and best.distance is not None
            and other.distance <= best.distance + float(policy.distance_ambiguity_margin))


def _assign(pairs: list[Pair], policy: Policy) -> tuple[dict[str, Pair], set[str]]:
    eligible = sorted((pair for pair in pairs if pair.eligible),
                      key=lambda pair: (-pair.containment, -pair.overlap, pair.distance, pair.gt, pair.mavi))
    by_gt: dict[str, list[Pair]] = {}
    by_mavi: dict[str, list[Pair]] = {}
    for pair in eligible:
        by_gt.setdefault(pair.gt, []).append(pair)
        by_mavi.setdefault(pair.mavi, []).append(pair)
    assigned_gt: dict[str, Pair] = {}
    assigned_mavi: set[str] = set()
    rejected_gt: set[str] = set()  # GT-side ambiguity: g is never assigned
    rejected_mavi: set[str] = set()  # MAVI-side ambiguity: m is never assigned
    contested_gt: set[str] = set()  # GT candidates of a rejected m: still available to other Tracks
    for pair in eligible:
        if pair.gt in assigned_gt or pair.mavi in assigned_mavi or pair.gt in rejected_gt \
                or pair.mavi in rejected_mavi:
            continue
        # A rival must still be assignable: assigned or ambiguity-rejected candidates never compete again.
        rivals = [other for other in by_gt[pair.gt] if other.mavi != pair.mavi and other.mavi not in assigned_mavi
                  and other.mavi not in rejected_mavi
                  and _comparable(pair, other, "gt_coverage", policy)]
        if rivals:
            rejected_gt.add(pair.gt)
            continue
        rivals = [other for other in by_mavi[pair.mavi] if other.gt != pair.gt and other.gt not in assigned_gt
                  and other.gt not in rejected_gt
                  and _comparable(pair, other, "mavi_coverage", policy)]
        if rivals:
            rejected_mavi.add(pair.mavi)
            contested_gt.update({pair.gt, *(other.gt for other in rivals)})
            continue
        assigned_gt[pair.gt] = pair
        assigned_mavi.add(pair.mavi)
    return assigned_gt, {gt for gt in rejected_gt | contested_gt if gt not in assigned_gt}


def _gt_state(track: GtTrack, pairs: list[Pair], assigned_gt: dict[str, Pair], assigned_mavi: dict[str, str],
              ambiguous: set[str], policy: Policy) -> str:
    gt_id = track.gt_track_id
    if gt_id in ambiguous:
        return "ambiguousGt"
    if any(pair.mavi in assigned_mavi and assigned_mavi[pair.mavi] != gt_id
           and pair.containment >= policy.min_containment and pair.overlap >= policy.min_overlap_frames
           and pair.gt_coverage >= policy.min_gt_coverage for pair in pairs):
        return "mergedGt"
    # A fragment is contained spatial evidence of part of the identity: containment and overlap at their floors,
    # neither eligible nor verification-failed. A pair that passes every non-IoU condition and fails only the IoU
    # gate is a verification failure, never a fragment, so several such Tracks make the GT unverifiedGt
    # (plan §7.4; §9 "one GT with three verification-failed MAVI fragments"). Two or more fragments whose contained
    # instants together reach the coverage floor make the GT fragmentedGt.
    fragments = [pair for pair in pairs if pair.containment >= policy.min_containment
                 and pair.overlap >= policy.min_overlap_frames
                 and not pair.eligible and not pair.verification_failed]
    covered = frozenset().union(*(pair.contained_instants for pair in fragments)) if fragments else frozenset()
    if not any(pair.eligible for pair in pairs) and len({pair.mavi for pair in fragments}) >= 2 \
            and Fraction(len(covered), len(track.evaluable)) >= policy.min_gt_coverage:
        return "fragmentedGt"
    if any(pair.verification_failed for pair in pairs):
        return "unverifiedGt"
    return "unmatchedGt"


def _mavi_state(pairs: list[Pair], assigned_gt: dict[str, Pair], mavi_id: str, sequence: _Sequence,
                policy: Policy) -> str:
    if any(pair.gt in assigned_gt and assigned_gt[pair.gt].mavi != mavi_id
           and pair.containment >= policy.min_containment and pair.overlap >= policy.min_overlap_frames
           and pair.mavi_coverage >= policy.min_mavi_coverage for pair in pairs):
        return "fragmentMavi"
    evaluable, inside = sequence.ignored_points(mavi_id)
    if evaluable and Fraction(inside, evaluable) >= IGNORED_MAVI_SHARE:
        return "ignoredMavi"
    if any(pair.verification_failed for pair in pairs):
        return "unverifiedMavi"
    return "unmatchedMavi"


def associate_sequence(gt: GtSequence, run: MaviRun, policy: Policy, labelled_rate: Fraction | None,
                       labelled_mode: bool) -> tuple[dict[str, Any], int, int]:
    """One ``sequences[]`` entry of the association artefact, with its evaluable and total MAVI point counts."""
    sequence = _Sequence(gt, run, policy, labelled_rate, labelled_mode)
    pairs = sequence.candidates()
    assigned_gt, ambiguous = _assign(pairs, policy)
    assigned_mavi = {pair.mavi: gt_id for gt_id, pair in assigned_gt.items()}
    by_gt: dict[str, list[Pair]] = {}
    by_mavi: dict[str, list[Pair]] = {}
    for pair in pairs:
        by_gt.setdefault(pair.gt, []).append(pair)
        by_mavi.setdefault(pair.mavi, []).append(pair)
    body: dict[str, Any] = {"sequenceId": gt.sequence_id, "videoAssetId": run.video_asset_id,
                            "processingRunId": run.processing_run_id,
                            "pairs": [assigned_gt[gt_id].document() for gt_id in sorted(assigned_gt)]}
    for state in GT_STATES:
        body[state] = []
    for track in sequence.active:
        if track.gt_track_id in assigned_gt:
            continue
        own = by_gt.get(track.gt_track_id, [])
        state = _gt_state(track, own, assigned_gt, assigned_mavi, ambiguous, policy)
        body[state].append({"gtTrackId": track.gt_track_id, "candidates": [pair.document() for pair in own]})
    body["ignoredGt"] = [{"gtTrackId": track.gt_track_id, "nonIgnoredFrames": len(track.evaluable)}
                         for track in sequence.ignored]
    for state in MAVI_STATES:
        body[state] = []
    for track in run.tracks:
        if track.mavi_track_id in assigned_mavi:
            continue
        own = by_mavi.get(track.mavi_track_id, [])
        state = _mavi_state(own, assigned_gt, track.mavi_track_id, sequence, policy)
        if state == "ignoredMavi":
            evaluable, inside = sequence.ignored_points(track.mavi_track_id)
            body[state].append({"maviTrackId": track.mavi_track_id, "evaluablePoints": evaluable,
                                "pointsInIgnoreRegions": inside})
        else:
            body[state].append({"maviTrackId": track.mavi_track_id, "candidates": [pair.document() for pair in own]})
    evaluable_total = sum(len(points) for points in sequence.evaluable.values())
    return body, evaluable_total, run.point_count


# The artefact


def labelled_timing(descriptor: dict[str, Any], envelope: dict[str, Any]) -> Fraction:
    """The labelled rate from the descriptor the envelope binds (never a caller-chosen value).

    The descriptor must hash to ``dataset.descriptorSha256`` and name the envelope's dataset and release. Its
    ``frameTime`` declares the labelled rate (``index-at-fps``) or the nominal rate of recorded timestamps
    (``per-frame-timestamp``); association needs it for the labelled-rate test and a single-instant window, so an
    undeclared rate is refused.
    """
    descriptors.check(descriptor)
    dataset = envelope["dataset"]
    require(document_sha256(descriptor) == dataset["descriptorSha256"], f"{CODE}:descriptor_mismatch")
    require(descriptor["datasetId"] == dataset["datasetId"] and descriptor["release"] == dataset["release"],
            f"{CODE}:descriptor_mismatch")
    frame_time = descriptor["frameTime"]
    require("fpsNumerator" in frame_time, f"{CODE}:labelled_rate_undeclared")
    return Fraction(frame_time["fpsNumerator"], frame_time["fpsDenominator"])


def _require_instants_follow_descriptor(document: dict[str, Any], descriptor: dict[str, Any]) -> None:
    """Under ``index-at-fps`` every labelled instant is the descriptor's frame time of its index (exact)."""
    if descriptor["frameTime"]["kind"] != "index-at-fps":
        return  # recorded timestamps are carried by the canonical GT, whose hash the envelope binds
    for row in document["instants"]:
        require(from_rational(row["videoOffsetMs"], CODE) == descriptors.index_offset_ms(descriptor, row["frameIndex"]),
                f"{CODE}:instant_time:{document['sequenceId']}")


def _reconcile_runs(envelope: dict[str, Any], sequences: Sequence[tuple[dict[str, Any], MaviRun]]) -> None:
    """Every MAVI run is exactly the evidence the envelope binds for its sequence (identities, not counts)."""
    runs = [run for _, run in sequences]
    for key in ("processing_run_id", "video_asset_id", "export_sha256"):
        values = [getattr(run, key) for run in runs]
        require(len(values) == len(set(values)), f"{CODE}:processing_run_duplicate")
    videos = {item["sequenceId"]: item["derivedVideoSha256"] for item in envelope["sequences"]}
    for document, run in sequences:
        require(run.source_sha256 == videos[document["sequenceId"]],
                f"{CODE}:video_asset_mismatch:{document['sequenceId']}")
    mavi = envelope["mavi"]
    require(sorted(run.export_sha256 for run in runs) == mavi["exportSha256s"], f"{CODE}:mavi_export_mismatch")
    require(sorted(set().union(*(run.trajectory_sha256s for run in runs))) == mavi["trajectorySha256s"],
            f"{CODE}:trajectory_set_mismatch")
    require(all(run.pipeline_profile_sha256 == mavi["pipelineProfileSha256"] and run.mavi_commit == mavi["maviCommit"]
                for run in runs), f"{CODE}:producer_mismatch")


def associate(*, envelope: dict[str, Any], policy: Policy, descriptor: dict[str, Any],
              sequences: Sequence[tuple[dict[str, Any], MaviRun]]) -> dict[str, Any]:
    """The ``benchmark-association-v1`` artefact for canonical GT documents paired with their MAVI runs.

    Everything that can change the result is bound by the envelope and checked first: the policy
    (``associationPolicySha256``), the labelled timing (the descriptor, ``descriptorSha256``), each sequence's
    canonical GT (``groundTruthSha256``) and the MAVI evidence (derived videos, exports, trajectories, producer).
    """
    envelopes.check(envelope)
    require(envelope["tooling"]["associationPolicySha256"] == policy.sha256, "association_policy_invalid:not_bound")
    labelled_rate = labelled_timing(descriptor, envelope)
    bound = {item["sequenceId"]: item["groundTruthSha256"] for item in envelope["sequences"]}
    ids = [document.get("sequenceId") if isinstance(document, dict) else None for document, _ in sequences]
    require(len(ids) == len(set(ids)) and sorted(ids, key=str) == sorted(bound), f"{CODE}:sequences")
    _reconcile_runs(envelope, sequences)
    rates = {run.frame_rate for _, run in sequences}
    require(len(rates) == 1, f"{CODE}:mixed_source_rate")
    source_rate = rates.pop()
    require(source_rate >= labelled_rate, f"{CODE}:rates")
    entries, evaluable_total, point_total = [], 0, 0
    for document, run in sorted(sequences, key=lambda item: item[0]["sequenceId"]):
        gt = gt_module.project(document)
        require(document_sha256(document) == bound[gt.sequence_id], f"{CODE}:ground_truth_hash:{gt.sequence_id}")
        require(document["split"] == envelope["dataset"]["split"], f"{CODE}:split_mismatch:{gt.sequence_id}")
        _require_instants_follow_descriptor(document, descriptor)
        entry, evaluable, points = associate_sequence(gt, run, policy, labelled_rate, source_rate == labelled_rate)
        entries.append(entry)
        evaluable_total += evaluable
        point_total += points
    alignment_block = {"sourceRate": rational(source_rate), "labelledRate": rational(labelled_rate),
                       "evaluablePointsTotal": evaluable_total, "maviPointsTotal": point_total}
    body = {"policy": policy.document, "sequences": entries, "alignment": alignment_block}
    artefact = {"schemaVersion": SCHEMA, "envelope": envelope, "associationBodySha256": document_sha256(body),
                **body, "limitation": LIMITATION}
    return check(artefact)


def check(artefact: dict[str, Any]) -> dict[str, Any]:
    """Schema, canonical rationals, envelope, policy binding, sequence set, body hash, set-exclusive outcomes."""
    validate(artefact, SCHEMA, CODE)
    require_canonical_rationals(artefact, CODE)
    envelopes.check(artefact["envelope"])
    # The embedded policy is the one the run identity binds (the same rule associate() enforces).
    require(policies.load(artefact["policy"]).sha256 == artefact["envelope"]["tooling"]["associationPolicySha256"],
            "association_policy_invalid:not_bound")
    ids = [entry["sequenceId"] for entry in artefact["sequences"]]
    require(ids == sorted(set(ids)) and ids == [item["sequenceId"] for item in artefact["envelope"]["sequences"]],
            f"{CODE}:sequences")
    body = {key: artefact[key] for key in ("policy", "sequences", "alignment")}
    require(artefact["associationBodySha256"] == document_sha256(body), f"{CODE}:body_sha256")
    for entry in artefact["sequences"]:
        gt_ids = [pair["gtTrackId"] for pair in entry["pairs"]]
        mavi_ids = [pair["maviTrackId"] for pair in entry["pairs"]]
        for state in (*GT_STATES, "ignoredGt"):
            gt_ids += [item["gtTrackId"] for item in entry[state]]
        for state in MAVI_STATES:
            mavi_ids += [item["maviTrackId"] for item in entry[state]]
        require(len(gt_ids) == len(set(gt_ids)), f"{CODE}:gt_counted_twice:{entry['sequenceId']}")
        require(len(mavi_ids) == len(set(mavi_ids)), f"{CODE}:mavi_counted_twice:{entry['sequenceId']}")
    return artefact


def write(artefact: dict[str, Any], path: Path) -> bytes:
    data = canonical_json(check(artefact))
    write_once(path, data)
    return data


def body_sha256(artefact: dict[str, Any]) -> str:
    return artefact["associationBodySha256"]


def counts(entries: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Outcome sizes over sequences (for reports and tests)."""
    totals = {"pairs": 0, **{state: 0 for state in (*GT_STATES, "ignoredGt", *MAVI_STATES)}}
    for entry in entries:
        for key in totals:
            totals[key] += len(entry[key])
    return totals


__all__ = ["associate", "associate_sequence", "check", "write", "counts", "S32Error", "Pair"]
