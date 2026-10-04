#!/usr/bin/env python3
"""Prediction-blind Track sampler (Stage 3, S3.2 plan T3; algorithm ``s3-2-video-quota-diversity-v1``).

Every sampling decision is made from :func:`_blind`'s projection of a Track: an
allow-list of identity, class, timing and Evidence Set fields. The predicted
subclass, its vocabulary and source, and the confidence summaries are never
copied into it, so no later step can read them. The sample is bound to its
exports (exact T1 bytes), the derivation manifests that produced the source
videos, one release record, and the requirements committed before sampling.

Usage::

    sample_tracks.py --export <file>... --derivation <file>... --requirements <file>
        --requirements-commit <sha> --target N --overlap-fraction 0.2 --seed <text>
        --design continuation|supplemental [--reason <text>] [--exclude-sample <file>...]
        [--repository <git-dir>] --out <file>

Exit 0 prints the sample's SHA-256; exit 2 prints ``refused <code>`` and writes nothing.
"""

from __future__ import annotations

import argparse
import io
import math
import sys
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import artefacts as a  # noqa: E402

ALGORITHM = "s3-2-video-quota-diversity-v1"
DIMENSIONS = ("scale", "duration", "density", "luma", "quality")
DERIVATION_SCHEMA = "vehicle-subclass-derivation-v1"
DERIVATION_MODES = ("passthrough", "remux", "transcode")
# What T8 must have obtained (plan §8, §15): the established purposes, and create-derivatives
# exactly when a new media artefact was made. T3 checks the record; it decides nothing.
DERIVATION_PURPOSES = ["benchmarking", "development"]
DERIVATION_OPERATIONS = {"passthrough": [], "remux": ["create-derivatives"], "transcode": ["create-derivatives"]}

# The only Track members a sampling decision could be biased by. They are named here so
# that the projection below can be checked against them; nothing in this module reads them.
PREDICTION_MEMBERS = ("objectSubclass", "objectSubclassVocabulary", "objectSubclassSource",
                      "meanConfidence", "maxConfidence")


@dataclass(frozen=True)
class BlindObservation:
    role: str
    rank: int
    width: float
    height: float
    quality: float
    evidence: dict[str, Any]  # path, digest and size only, for verifying bytes


@dataclass(frozen=True)
class BlindTrack:
    run_id: str
    track_id: str
    object_class: str
    start_ms: int
    end_ms: int
    observations: tuple[BlindObservation, ...]


def _blind(run_id: str, track: dict[str, Any]) -> BlindTrack:
    """The only view of a Track the sampler has: an allow-list, never a copy minus some keys."""
    return BlindTrack(
        run_id=run_id,
        track_id=track["id"],
        object_class=track["objectClass"],
        start_ms=track["startOffsetMs"],
        end_ms=track["endOffsetMs"],
        observations=tuple(
            BlindObservation(
                role=observation["evidenceRole"],
                rank=observation["evidenceRank"],
                width=observation["boundingBox"]["width"],
                height=observation["boundingBox"]["height"],
                quality=observation["qualityScore"],
                evidence={key: observation[key] for key in ("evidencePath", "evidenceSha256", "evidenceSizeBytes")},
            )
            for observation in track["observations"]
        ),
    )


# Inputs


def _derivations(paths: list[Path], exports: dict[str, a.Export]) -> tuple[list[str], str, str]:
    """Consumer-side check of T8 manifests: each export's source is exactly one authorised derivation."""
    by_output: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for path in paths:
        data = a.read_bytes(path, "derivation_unreadable")
        document = a.parse_json(data, "derivation_unreadable")
        # The T8 contract first (derivation_invalid:schema); the semantic checks below stay as defence in depth.
        a.validate(document, DERIVATION_SCHEMA, "derivation_invalid")
        a.require(isinstance(document, dict) and document.get("schemaVersion") == DERIVATION_SCHEMA, "derivation_invalid")
        release = document.get("release")
        authorisation = document.get("authorisation")
        a.require(isinstance(release, dict) and isinstance(release.get("releaseId"), str) and release["releaseId"].strip()
                  and a.SHA256_RE.fullmatch(str(release.get("releaseRecordSha256", "")))
                  and isinstance(release.get("member"), str) and release["member"].strip(), "derivation_invalid:release")
        a.require(document.get("mode") in DERIVATION_MODES, "derivation_invalid:mode")
        a.require(isinstance(authorisation, dict) and set(authorisation) == {"purposes", "operations", "blockers"},
                  "derivation_invalid:authorisation")
        a.require(authorisation["purposes"] == DERIVATION_PURPOSES, "derivation_invalid:authorisation:purposes")
        a.require(authorisation["operations"] == DERIVATION_OPERATIONS[document["mode"]],
                  "derivation_invalid:authorisation:operations")
        a.require(authorisation["blockers"] == [], "derivation_invalid:authorisation:blockers")
        for key in ("sourceSha256", "outputSha256"):
            a.require(a.SHA256_RE.fullmatch(str(document.get(key, ""))), f"derivation_invalid:{key}")
        a.require(document["mode"] != "passthrough" or document["outputSha256"] == document["sourceSha256"],
                  "derivation_invalid:passthrough")
        a.require(a.canonical_json(document) == data, "derivation_invalid:not_canonical")
        by_output.setdefault(document["outputSha256"], []).append((a.sha256_hex(data), document))

    used: dict[str, dict[str, Any]] = {}
    for export in exports.values():
        matches = by_output.get(export.video["sourceSha256"], [])
        a.require(len(matches) == 1, "export_not_derived")
        used[matches[0][0]] = matches[0][1]
    a.require(len(used) == sum(len(items) for items in by_output.values()), "export_not_derived:unused_derivation")
    releases = {(d["release"]["releaseId"], d["release"]["releaseRecordSha256"]) for d in used.values()}
    a.require(len(releases) == 1, "export_not_derived:releases_differ")
    release_id, release_record = releases.pop()
    return sorted(used), release_id, release_record


def _requirements(repository: Path, path: Path, commit: str) -> dict[str, str]:
    binding = a.git_binding(repository, path, commit, a.REQUIREMENTS_GIT_PATH, "requirements_not_committed")
    document = a.parse_json(a.read_bytes(path, "requirements_not_committed"), "requirements_not_committed")
    a.validate(document, "vehicle-subclass-requirements-v1", "requirements_not_committed")
    a.require_preregistered(binding, "requirements_not_preregistered")
    return {"sha256": binding["sha256"], "gitCommit": binding["gitCommit"], "gitPath": binding["gitPath"]}


def _design(kind: str | None, reason: str | None, parents: list[dict[str, Any]], export_set: list[str],
            release_record: str, overlap_fraction: float, requirements_sha: str) -> dict[str, Any]:
    a.require(kind in ("continuation", "supplemental"), "design_invalid:kind")
    if kind == "continuation":
        a.require(reason is None, "design_invalid:reason_with_continuation")
        if parents:
            # The pilot is the parent that is itself a continuation without parents; earlier
            # supplemental batches may be excluded too, but only the pilot defines the design.
            pilots = [p for p in parents if p["design"]["kind"] == "continuation" and not p["design"]["parentSampleSha256s"]]
            a.require(len(pilots) == 1, "continuation_pool_mismatch:pilot")
            pilot = pilots[0]
            # A continuation draws only from the pilot's processed pool: no added and no omitted video.
            a.require(sorted(pilot["exportSha256s"]) == export_set, "continuation_pool_mismatch")
            a.require(pilot["releaseRecordSha256"] == release_record, "continuation_pool_mismatch:release")
            # Fail before any labelling work on what T2 would refuse to pool.
            a.require(pilot["design"]["parameters"] == {"overlapFraction": overlap_fraction}
                      and pilot["design"]["samplingAlgorithm"] == ALGORITHM
                      and pilot["requirements"]["sha256"] == requirements_sha, "continuation_design_mismatch")
        return {"kind": kind}
    a.require(reason is not None, "design_invalid:reason_missing")
    a.require(isinstance(reason, str) and reason.strip() == reason and 0 < len(reason) <= a.REASON_MAX
              and "\n" not in reason and "\r" not in reason, "design_invalid:reason")
    return {"kind": kind, "reason": reason}


# Algorithm


def _overlaps(first: BlindTrack, second: BlindTrack) -> bool:
    return first.start_ms <= second.end_ms and second.start_ms <= first.end_ms


def _tercile_bins(pool: list[BlindTrack], values: dict[tuple[str, str], float], seed: str) -> dict[tuple[str, str], int]:
    n = len(pool)
    order = sorted(pool, key=lambda t: (values[(t.run_id, t.track_id)], a.h(seed, t.run_id, t.track_id)))
    first, second = n // 3, (2 * n) // 3
    return {(t.run_id, t.track_id): 0 if index < first else 1 if index < second else 2 for index, t in enumerate(order)}


def allocate(available: dict[str, int], total: int, floor_each: int, seed: str) -> tuple[dict[str, int], dict[str, int]]:
    """Step 2: floors, then the remainder by largest remainder over spare capacity, capped and re-shared."""
    a.require(total <= sum(available.values()), "target_exceeds_pool")
    floors = {run: min(count, floor_each) for run, count in available.items()}
    quotas = dict(floors)
    remaining = total - sum(quotas.values())
    while remaining > 0:
        spare = {run: available[run] - quotas[run] for run in available if available[run] > quotas[run]}
        weight = sum(spare.values())
        shares = {run: Fraction(remaining * capacity, weight) for run, capacity in spare.items()}
        grant = {run: math.floor(share) for run, share in shares.items()}
        extra = remaining - sum(grant.values())
        for run in sorted(spare, key=lambda r: (-(shares[r] - grant[r]), a.h(seed, "alloc", r)))[:extra]:
            grant[run] += 1
        for run in spare:
            quotas[run] += min(grant[run], spare[run])
        remaining = total - sum(quotas.values())
    return floors, quotas


def _greedy(candidates: list[BlindTrack], quota: int, bins: dict[str, dict[tuple[str, str], int]], seed: str) -> list[BlindTrack]:
    """Step 3: within one video, repeatedly take the Track whose bins are least represented so far."""
    counts = {dimension: [0, 0, 0] for dimension in DIMENSIONS}
    chosen: list[BlindTrack] = []
    remaining = list(candidates)
    for _ in range(quota):
        def score(track: BlindTrack) -> tuple[int, str]:
            key = (track.run_id, track.track_id)
            return sum(counts[d][bins[d][key]] for d in DIMENSIONS), a.h(seed, track.run_id, track.track_id)
        best = min(remaining, key=score)
        remaining.remove(best)
        chosen.append(best)
        for dimension in DIMENSIONS:
            counts[dimension][bins[dimension][(best.run_id, best.track_id)]] += 1
    return chosen


def _luma_decoder() -> dict[str, str]:
    """The luma bins depend on JPEG decoding; the sample records what decoded them."""
    import numpy
    from PIL import __version__ as pillow

    return {"pillow": pillow, "numpy": numpy.__version__}


def _luma(data: bytes) -> float:
    import numpy
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        return float(numpy.asarray(image.convert("L"), dtype=numpy.float64).mean())


def sample(exports: dict[str, a.Export], *, target: int, overlap_fraction: float, seed: str,
           previously_sampled: set[tuple[str, str]]) -> dict[str, Any]:
    """The selection, from blinded Tracks only."""
    a.require(isinstance(target, int) and target >= 1, "target_invalid")
    a.require(isinstance(overlap_fraction, float) and math.isfinite(overlap_fraction), "overlap_fraction_invalid")
    fraction = Fraction(repr(overlap_fraction))
    a.require(0 < fraction <= 1, "overlap_fraction_invalid")

    excluded = {"not-vehicle": 0, "no-verified-evidence": 0, "previously-sampled": 0}
    pool: list[BlindTrack] = []
    values: dict[str, dict[tuple[str, str], float]] = {d: {} for d in DIMENSIONS}
    seen: set[str] = set()
    export_of: dict[str, str] = {}
    video_of: dict[str, dict[str, Any]] = {}
    for export_sha, export in sorted(exports.items(), key=lambda item: item[1].run_id):
        blinded = [_blind(export.run_id, track) for track in export.tracks]
        vehicles = [t for t in blinded if t.object_class == "Vehicle"]
        export_of[export.run_id] = export_sha
        video_of[export.run_id] = export.video
        for track in blinded:
            a.require(track.track_id not in seen, "track_duplicate")
            seen.add(track.track_id)
            if track.object_class != "Vehicle":
                excluded["not-vehicle"] += 1
                continue
            if (track.run_id, track.track_id) in previously_sampled:
                excluded["previously-sampled"] += 1
                continue
            verified = [(o, export.evidence_bytes(o.evidence)) for o in sorted(track.observations, key=lambda o: o.rank)]
            verified = [(o, data) for o, data in verified if data is not None]
            if not verified:
                excluded["no-verified-evidence"] += 1
                continue
            # The Representative, or where its bytes do not verify, the lowest-ranked verified observation.
            representative, data = next(((o, d) for o, d in verified if o.role == "Representative"), verified[0])
            key = (track.run_id, track.track_id)
            values["scale"][key] = representative.width * representative.height
            values["duration"][key] = track.end_ms - track.start_ms
            values["density"][key] = sum(1 for other in vehicles if other.track_id != track.track_id and _overlaps(track, other))
            values["luma"][key] = _luma(data)
            values["quality"][key] = representative.quality
            pool.append(track)

    a.require(target <= len(pool), "target_exceeds_pool")
    bins = {d: _tercile_bins(pool, values[d], seed) for d in DIMENSIONS}
    # Every exported video counts in V, including one with no usable Track (a_v = 0).
    by_run: dict[str, list[BlindTrack]] = {export.run_id: [] for export in exports.values()}
    for track in pool:
        by_run[track.run_id].append(track)
    runs = sorted(by_run)
    floors, quotas = allocate({run: len(by_run[run]) for run in runs}, target, target // (2 * len(runs)), seed)

    selected: dict[str, list[BlindTrack]] = {run: _greedy(by_run[run], quotas[run], bins, seed) for run in runs}
    chosen_runs = [run for run in runs if selected[run]]
    k = math.ceil(fraction * target)
    overlap_floors, overlap_quotas = allocate(
        {run: len(selected[run]) for run in chosen_runs}, k, 1 if k >= len(chosen_runs) else 0, seed)
    overlap = [t for run in chosen_runs
               for t in sorted(selected[run], key=lambda t: a.h(seed, "overlap", t.run_id, t.track_id))[:overlap_quotas[run]]]

    available_counts = {f"{d}:{b}": 0 for d in DIMENSIONS for b in range(3)}
    for d in DIMENSIONS:
        for value in bins[d].values():
            available_counts[f"{d}:{value}"] += 1
    return {
        "allocation": {run: {"available": len(by_run[run]), "floor": floors[run], "quota": quotas[run],
                             "overlapFloor": overlap_floors.get(run, 0), "overlapQuota": overlap_quotas.get(run, 0),
                             "exportSha256": export_of[run], "videoAssetId": video_of[run]["videoAssetId"],
                             "cameraCode": video_of[run]["cameraCode"]} for run in runs},
        "strata": {"dimensions": list(DIMENSIONS), "poolSize": len(pool), "cutPositions": [len(pool) // 3, (2 * len(pool)) // 3],
                   "lumaDecoder": _luma_decoder()},
        "available": available_counts,
        "selected": sorted(
            ({"processingRunId": t.run_id, "trackId": t.track_id, "exportSha256": export_of[t.run_id],
              "bins": {d: bins[d][(t.run_id, t.track_id)] for d in DIMENSIONS}}
             for run in runs for t in selected[run]),
            key=lambda item: (item["processingRunId"], item["trackId"])),
        "overlapSelected": sorted(({"processingRunId": t.run_id, "trackId": t.track_id} for t in overlap),
                                  key=lambda item: (item["processingRunId"], item["trackId"])),
        "excluded": {reason: count for reason, count in excluded.items() if count},
    }


def build(args: argparse.Namespace) -> bytes:
    exports = a.load_exports(args.export)
    export_set = sorted(exports)
    derivations, release_id, release_record = _derivations(args.derivation, exports)
    requirements = _requirements(args.repository, args.requirements, args.requirements_commit)

    parents: list[dict[str, Any]] = []
    previously: set[tuple[str, str]] = set()
    parent_shas: list[str] = []
    for path in args.exclude_sample:
        document, _, sha = a.read_artefact(path, "vehicle-subclass-sample-v1", "exclusion_sample_invalid")
        a.require(sha not in parent_shas, "exclusion_sample_invalid:duplicate")
        parents.append(document)
        parent_shas.append(sha)
        previously.update((item["processingRunId"], item["trackId"]) for item in document["selected"])

    design = _design(args.design, args.reason, parents, export_set, release_record, args.overlap_fraction,
                     requirements["sha256"])
    a.require(isinstance(args.seed, str) and args.seed.strip() == args.seed and args.seed, "seed_invalid")
    result = sample(exports, target=args.target, overlap_fraction=args.overlap_fraction, seed=args.seed,
                    previously_sampled=previously)
    document = {
        "schemaVersion": "vehicle-subclass-sample-v1",
        "seed": args.seed,
        "target": args.target,
        "exportSha256s": export_set,
        "derivationSha256s": derivations,
        "releaseRecordSha256": release_record,
        "requirements": requirements,
        "excludedSampleSha256s": sorted(parent_shas),
        "design": {**design, "samplingAlgorithm": ALGORITHM,
                   "parameters": {"overlapFraction": args.overlap_fraction},
                   "releaseId": release_id, "parentSampleSha256s": sorted(parent_shas)},
        **result,
    }
    a.validate(document, "vehicle-subclass-sample-v1", "sample_invalid")
    return a.canonical_json(document)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--export", type=Path, action="append", required=True)
    p.add_argument("--derivation", type=Path, action="append", required=True)
    p.add_argument("--requirements", type=Path, required=True)
    p.add_argument("--requirements-commit", required=True)
    p.add_argument("--target", type=int, required=True)
    p.add_argument("--overlap-fraction", type=float, required=True)
    p.add_argument("--seed", required=True)
    p.add_argument("--design")
    p.add_argument("--reason")
    p.add_argument("--exclude-sample", type=Path, action="append", default=[])
    p.add_argument("--repository", type=Path, default=a.ROOT,
                   help="the git repository holding the committed requirements (default: this MAVI checkout)")
    p.add_argument("--out", type=Path, required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        a.require(not args.out.exists(), "output_exists")
        data = build(args)
        a.write_once(args.out, data)
    except a.S32Error as exc:
        print(f"refused {exc}", file=sys.stderr)
        return 2
    print(a.sha256_hex(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
