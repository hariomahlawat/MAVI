"""Builders for vehicle-track association fixtures: canonical GT documents and class-free MAVI runs from geometry.

A GT track is ``{index: box}`` (``box`` = (x, y, w, h) normalised) or ``{index: ("ignore", box)}``; a MAVI Track is a
list of ``(offset_ms, cx, cy)`` points plus observations ``[(offset_ms, (x, y, w, h)), …]``. Times default to
5 Hz labels (200 ms) and a 5 fps source, so frame ``k`` is at ``200·k`` ms.
"""

from __future__ import annotations

import copy
import json
from fractions import Fraction
from pathlib import Path
from typing import Any

from tools.benchmarks.capabilities.vehicle_tracks import association as a
from tools.benchmarks.capabilities.vehicle_tracks import policy as policies
from tools.benchmarks.capabilities.vehicle_tracks.ground_truth import Box
from tools.benchmarks.capabilities.vehicle_tracks.mavi_tracks import MaviRun, MaviTrack, Observation
from tools.benchmarks.core import envelope as envelopes
from tools.benchmarks.core.identity import document_sha256, rational

ROOT = Path(__file__).resolve().parents[3]
EXPORT_EXAMPLE = ROOT / "contracts" / "examples" / "vehicle-subclass-measurement-export-v1.example.json"
PERIOD = Fraction(200)
FILES = [{"path": "tools/benchmarks/capabilities/vehicle_tracks/association.py", "sha256": "2" * 64}]


def mid(n: int) -> str:
    """A UUID-shaped MAVI Track id (the association contract requires UUIDs)."""
    return f"{n:08x}-0000-4000-8000-000000000000"


def gt_document(tracks: dict[str, dict[int, Any]], *, instants: list[Fraction] | None = None, frames: int | None = None,
                sequence: str = "seq-1", classes: dict[str, str] | None = None,
                regions: list[tuple[int, tuple[float, float, float, float]]] | None = None) -> dict[str, Any]:
    if instants is None:
        count = frames if frames is not None else 1 + max(i for track in tracks.values() for i in track)
        instants = [PERIOD * k for k in range(count)]
    rows = [{"frameIndex": k, "videoOffsetMs": rational(time)} for k, time in enumerate(instants)]
    document: dict[str, Any] = {"sequenceId": sequence, "split": "val", "frameSize": {"width": 32, "height": 18},
                                "instants": rows, "tracks": []}
    for track_id in sorted(tracks):
        frames_ = []
        for k in sorted(tracks[track_id]):
            value = tracks[track_id][k]
            ignore = isinstance(value, tuple) and len(value) == 2 and value[0] == "ignore"
            x, y, w, h = value[1] if ignore else value
            frames_.append({"frameIndex": k, "videoOffsetMs": rational(instants[k]), "ignore": ignore,
                            "box": {"x": x, "y": y, "width": w, "height": h}})
        document["tracks"].append({"gtTrackId": track_id, "nativeClass": (classes or {}).get(track_id, "car"),
                                   "frames": frames_})
    if regions:
        document["ignoreRegions"] = [{"frameIndex": k, "box": {"x": x, "y": y, "width": w, "height": h}}
                                     for k, (x, y, w, h) in regions]
    return document


def follow(box: tuple[float, float, float, float], frames: range | list[int], *, dx: float = 0.0, dy: float = 0.0,
           period: Fraction = PERIOD) -> list[tuple[int, float, float]]:
    """Points at the centre of ``box`` (optionally offset) at each frame's time."""
    x, y, w, h = box
    return [(int(period * k), x + w / 2 + dx, y + h / 2 + dy) for k in frames]


def track(n: int, points: list[tuple[int, float, float]],
          observations: list[tuple[int, tuple[float, float, float, float]]] | None = None) -> MaviTrack:
    obs = tuple(Observation(offset, Box(*box)) for offset, box in sorted(observations or []))
    return MaviTrack(mid(n), tuple(sorted(points)), obs)


def run(*tracks: MaviTrack, rate: Fraction = Fraction(5), video: int = 1) -> MaviRun:
    """A directly built run; its identities are deterministic stand-ins (export, video and per-Track trajectory)."""
    from tools.benchmarks.core.identity import sha256_hex

    ordered = tuple(sorted(tracks, key=lambda item: item.mavi_track_id))
    return MaviRun(f"aaaaaaaa-0000-4000-8000-{video:012x}", f"bbbbbbbb-0000-4000-8000-{video:012x}", rate, ordered,
                   sha256_hex(f"export-{video}".encode()), sha256_hex(f"video-{video}".encode()),
                   frozenset(sha256_hex(f"trajectory-{video}-{item.mavi_track_id}".encode()) for item in ordered))


def static(box: tuple[float, float, float, float], frames: range | list[int]) -> dict[int, Any]:
    return {k: box for k in frames}


def envelope_for(documents: list[dict[str, Any]], runs: list[MaviRun], policy: policies.Policy,
                 mapping_sha256: str = "d" * 64, **changes: Any) -> dict[str, Any]:
    """The envelope Slice 3 builds: GT hashes from the documents; video, export and trajectory hashes from the runs
    (paired by position, as ``associate`` receives them)."""
    attestation = json.loads(EXPORT_EXAMPLE.read_text(encoding="utf-8"))["processingRun"]["attestation"]
    from tools.benchmarks.core import mavi

    producer = {key: attestation.get(key) for key in (*mavi.PRODUCER_KEYS, *mavi.PRODUCER_EXTRA)}
    inputs = {
        "dataset": {"datasetId": "synthetic-vehicles", "release": "synthetic-v1", "split": "val",
                    "descriptorSha256": "a" * 64},
        "sequences": [{"sequenceId": document["sequenceId"], "derivedVideoSha256": mavi_run.source_sha256,
                       "groundTruthSha256": document_sha256(document)} for document, mavi_run in zip(documents, runs)],
        "derivation_manifest_sha256": "6" * 64,
        "mavi": {"maviCommit": producer["maviCommit"], "pipelineProfileSha256": producer["pipelineProfileSha256"],
                 "producer": producer, "exportSha256s": sorted(mavi_run.export_sha256 for mavi_run in runs),
                 "trajectorySha256s": sorted(set().union(*(mavi_run.trajectory_sha256s for mavi_run in runs)))},
        "tooling": {"adapterId": "synthetic", "adapterVersion": "1", "mappingSha256": mapping_sha256,
                    "associationPolicySha256": policy.sha256, "requirementsSha256": "f" * 64, "runnerVersion": "1",
                    "toolingCommit": "1" * 40, "toolingSha256": document_sha256(FILES),
                    "toolingFiles": copy.deepcopy(FILES)},
        "exposure": {"status": "none-known", "basis": "Synthetic."},
    }
    inputs.update(changes)
    return envelopes.build(**inputs)


def associate(documents: list[dict[str, Any]], runs: list[MaviRun], *, policy: policies.Policy | None = None,
              labelled_rate: Fraction = Fraction(5), **envelope_changes: Any) -> dict[str, Any]:
    policy = policy or policies.v1()
    return a.associate(envelope=envelope_for(documents, runs, policy, **envelope_changes), policy=policy,
                       sequences=list(zip(documents, runs)), labelled_rate=labelled_rate)


def one(document: dict[str, Any], mavi_run: MaviRun, **kwargs: Any) -> dict[str, Any]:
    """The single sequence entry of a one-sequence association."""
    return associate([document], [mavi_run], **kwargs)["sequences"][0]


def write_export(directory: Path, evidence_root: Path, tracks: list[dict[str, Any]], *, rate: tuple[int, int] = (5, 1),
                 video: int = 1) -> Path:
    """A schema-valid T1 export of one run plus its sealed trajectories under ``evidence_root``.

    Each track spec: ``{"n", "points", "observations" [(offset, box)], "objectClass", "subclass", "confidence"}``.
    Observation frame numbers follow the declared rate exactly (the derived-video timing rule).
    """
    import msgpack

    from tools.benchmarks.core._stage3 import artefacts
    from tools.benchmarks.core.identity import canonical_json, sha256_hex

    template = json.loads(EXPORT_EXAMPLE.read_text(encoding="utf-8"))
    vehicle = next(t for t in template["tracks"] if t["objectClass"] == "Vehicle")
    person = next(t for t in template["tracks"] if t["objectClass"] == "Person")
    asset, run_id = f"aaaaaaaa-0000-4000-8000-{video:012x}", f"bbbbbbbb-0000-4000-8000-{video:012x}"
    template["video"].update(videoAssetId=asset, frameRateNumerator=rate[0], frameRateDenominator=rate[1],
                             sourceSha256=sha256_hex(f"video-{video}".encode()))
    template["processingRun"].update(videoAssetId=asset, processingRunId=run_id)
    template["processingRun"]["attestation"].update(videoAssetId=asset, processingRunId=run_id)
    period = Fraction(1000 * rate[1], rate[0])
    rows = []
    evidence_root.mkdir(parents=True, exist_ok=True)
    for spec in tracks:
        payload = msgpack.packb({"v": 1, "points": [list(point) for point in spec["points"]]}, use_bin_type=True)
        sha = sha256_hex(payload)
        (evidence_root / f"track{spec['n']}-{sha}.msgpack").write_bytes(payload)
        is_person = spec.get("objectClass", "Vehicle") == "Person"
        row = copy.deepcopy(person if is_person else vehicle)
        observations = []
        for rank, (offset, (x, y, w, h)) in enumerate(spec.get("observations", [])):
            frame = Fraction(offset) / period
            assert frame.denominator == 1, "fixture observation off the frame grid"
            observations.append({**copy.deepcopy(vehicle["observations"][0]), "evidenceRank": rank,
                                 "evidenceRole": "Representative" if rank == 0 else "NearView",
                                 "sourceFrameNumber": int(frame), "videoOffsetMs": offset,
                                 "boundingBox": {"x": x, "y": y, "width": w, "height": h}})
        confidence = spec.get("confidence", 0.8)
        row.update(id=mid(spec["n"]), localTrackNumber=spec["n"], startOffsetMs=spec["points"][0][0],
                   endOffsetMs=spec["points"][-1][0], detectionCount=len(spec["points"]), meanConfidence=confidence,
                   maxConfidence=confidence, trajectorySha256=sha, observations=observations,
                   representative=({"videoOffsetMs": observations[0]["videoOffsetMs"],
                                    "boundingBox": observations[0]["boundingBox"]} if observations else None))
        if not is_person:
            row["objectSubclass"] = spec.get("subclass", "car")
        rows.append(row)
    template["tracks"] = rows
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / artefacts.EXPORT_FILE_NAME
    path.write_bytes(canonical_json(template))
    return path


def states(entry: dict[str, Any]) -> dict[str, list[str]]:
    """GT and MAVI ids per outcome (assigned pairs as ``assigned``/``assignedMavi``)."""
    result = {"assigned": [pair["gtTrackId"] for pair in entry["pairs"]],
              "assignedMavi": [pair["maviTrackId"] for pair in entry["pairs"]]}
    for state in (*a.GT_STATES, "ignoredGt"):
        result[state] = [item["gtTrackId"] for item in entry[state]]
    for state in a.MAVI_STATES:
        result[state] = [item["maviTrackId"] for item in entry[state]]
    return result
