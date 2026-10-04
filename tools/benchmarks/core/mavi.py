"""MAVI execution identity for the envelope (plan §2, §5, §7 inputs). Reading only; no trajectory parsing here.

Exports are T1's ``vehicle-subclass-measurement-export-v1`` read by ``artefacts.load_exports`` (exact bytes, one
run per video). The producer is the single attested producer, checked as T2 and T9 check it, and must have
processed the measured profile (``producer_mixed``, ``profile_mismatch``). The capability selection is applied
before anything else: only Tracks whose broad ``objectClass`` is ``Vehicle`` are this capability's evidence.
Trajectories are located by hash under the evidence root (``*-{sha256}.msgpack``; the export does not carry the
vision job id) and their bytes verified; decoding them belongs to the association slice.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.benchmarks.core._stage3 import artefacts
from tools.benchmarks.core.identity import S32Error, require, sha256_hex

import evaluate_vehicle_subclass as evaluator  # noqa: E402  (tools/phase1, on the path via _stage3)

VEHICLE = "Vehicle"
# Producer members T2's check does not compare; required equal across runs as T9 requires them (ingest_source_pool).
PRODUCER_KEYS = (*evaluator._PRODUCER_TEXT, *evaluator._PRODUCER_SHA256, *evaluator._PRODUCER_OPTIONAL_SHA256)
PRODUCER_EXTRA = ("maviBuild", "modelPackId", "runtimePackId", "runtimePackSource", "platform")


def load_exports(paths: list[Path]) -> dict[str, artefacts.Export]:
    require(paths, "export_invalid:none")
    return artefacts.load_exports(list(paths))


def producer(exports: dict[str, artefacts.Export], measured_profile_sha256: str) -> dict[str, Any]:
    attestations = [export.attestation for export in exports.values()]
    try:
        checked = evaluator._producer(attestations, measured_profile_sha256)
    except evaluator.SubclassEvaluationError as exc:
        code = str(exc)
        if code == "attestation_pipeline_profile_mismatch":
            raise S32Error("profile_mismatch") from exc
        if code == "attestation_producers_differ":
            raise S32Error("producer_mixed") from exc
        raise S32Error(f"export_invalid:attestation:{code}") from exc
    extras = {tuple(json.dumps(item.get(key), sort_keys=True) for key in PRODUCER_EXTRA) for item in attestations}
    require(len(extras) == 1, "producer_mixed")
    return {**{key: checked[key] for key in PRODUCER_KEYS}, **{key: attestations[0].get(key) for key in PRODUCER_EXTRA}}


def vehicle_tracks(export: artefacts.Export) -> list[dict[str, Any]]:
    """The capability selection: Vehicle Tracks only, in export order (Person Tracks never enter any count)."""
    return [track for track in export.tracks if track["objectClass"] == VEHICLE]


def mavi_identity(exports: dict[str, artefacts.Export], measured_profile_sha256: str) -> dict[str, Any]:
    """The envelope's ``mavi`` block. Every selected Vehicle Track must name its trajectory."""
    checked = producer(exports, measured_profile_sha256)
    trajectories: set[str] = set()
    for export in exports.values():
        for track in vehicle_tracks(export):
            require(track["trajectorySha256"] is not None, f"trajectory_missing:{track['id']}")
            trajectories.add(track["trajectorySha256"])
    return {"maviCommit": checked["maviCommit"], "pipelineProfileSha256": measured_profile_sha256,
            "producer": checked, "exportSha256s": sorted(exports), "trajectorySha256s": sorted(trajectories)}


def locate_trajectory(evidence_root: Path, sha256: str) -> Path:
    """The sealed trajectory file whose name ends ``-{sha256}.msgpack`` and whose bytes hash to ``sha256``."""
    require(artefacts.SHA256_RE.fullmatch(sha256 or ""), "trajectory_missing:invalid_sha256")
    root = Path(evidence_root)
    require(root.is_dir(), "trajectory_missing:evidence_root")
    candidates = sorted(root.rglob(f"*-{sha256}.msgpack"), key=lambda path: path.as_posix())
    require(candidates, f"trajectory_missing:{sha256}")
    for candidate in candidates:
        require(sha256_hex(artefacts.read_bytes(candidate, "trajectory_missing")) == sha256,
                f"trajectory_hash_mismatch:{sha256}")
    return candidates[0]
