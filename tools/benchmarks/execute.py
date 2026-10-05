"""``execute`` (S3.2d-1 plan §11 step 3): one MAVI processing run per prepared benchmark sequence.

The T9 pattern, reusing its code (``tools/stage3/ingest_source_pool.py``) rather than copying it: MAVI is driven
through its product API only, on a loopback URL, against a fresh and dedicated catalogue (``t9_catalogue_not_fresh``
otherwise). Per sequence: one camera, one import of the sequence's derived ``video.mp4``, one processing run that is
journalled before polling, and one T1 export into ``<exports>/<processingRunId>/``. Pre-existing assets and runs are
never adopted, and a resume is allowed only from this instance's journal, which is bound to the derivation manifest.

Before any API call, every prepared file is re-hashed (``prepare.load``) and the pipeline profile must pass the S3.2
measurement identity gate. Afterwards the exports must name exactly the derived videos, carry one attested producer
that measured exactly this profile, and every sealed trajectory must be present in the evidence root with its
attested hash. ``evaluate`` then binds all of it into the run envelope. The journal, API URL and paths are runtime
only and never part of any result.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.benchmarks import prepare as preparation
from tools.benchmarks.capabilities.vehicle_tracks import mavi_tracks
from tools.benchmarks.core._stage3 import artefacts
from tools.benchmarks.core.identity import S32Error, require, sha256_hex

import ingest_source_pool as t9  # noqa: E402  (tools/stage3, on the path via _stage3)

CAMERA_PREFIX = "BDD-"
CAMERA_ZONE = "UTC"
# Benchmark footage has no wall-clock meaning for MAVI; one fixed, valid local start is declared for every import.
RECORDING_START_LOCAL = "2020-01-01T00:00:00"


def camera_code(sequence_id: str) -> str:
    """``BDD-`` + the sequence id upper-cased, every character outside A–Z, 0–9 and ``-`` replaced by ``-`` (the T9
    rule); refused rather than truncated past MAVI's 32-character limit, so two sequences never share a camera."""
    body = "".join(c if ("A" <= c <= "Z" or "0" <= c <= "9" or c == "-") else "-" for c in sequence_id.upper())
    code = CAMERA_PREFIX + body
    require(len(code) <= t9.ingestion_map.CODE_MAX, f"benchmark_camera_code_too_long:{sequence_id}")
    return code


def execute(*, derived: Path, profile_path: Path, api_url: str, journal_path: Path, export_root: Path,
            export_command: list[str], evidence_root: Path, poll_seconds: float = 5.0,
            timeout_seconds: float = 6 * 3600) -> list[dict[str, Any]]:
    """Runs MAVI once per prepared sequence; returns ``[{sequenceId, videoAssetId, processingRunId, exportSha256}]``.
    Malformed inputs are refusals (``benchmark_input_invalid``), never raw exceptions, as in ``evaluate``."""
    try:
        return _execute(derived, profile_path, api_url, journal_path, export_root, export_command, evidence_root,
                        poll_seconds, timeout_seconds)
    except S32Error:
        raise
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
        raise S32Error(f"benchmark_input_invalid:{type(exc).__name__}") from exc


def _execute(derived, profile_path, api_url, journal_path, export_root, export_command, evidence_root, poll_seconds,
             timeout_seconds) -> list[dict[str, Any]]:
    manifest, manifest_sha, _ = preparation.load(derived)
    profile_bytes = artefacts.read_bytes(profile_path, "pipeline_profile_unreadable")
    t9.require_measurement_profile(profile_bytes)
    profile_sha = sha256_hex(profile_bytes)
    require(Path(export_root).is_dir(), "benchmark_export_root_missing")
    require(Path(evidence_root).is_dir(), "benchmark_evidence_root_missing")
    sequences = manifest["sequences"]
    cameras = {camera_code(row["sequenceId"]): {"name": f"Benchmark {manifest['datasetId']} {row['sequenceId']}",
                                                "timeZoneId": CAMERA_ZONE} for row in sequences}
    require(len(cameras) == len(sequences), "benchmark_camera_code_collision")

    # Every input is verified; only now is the API touched.
    api = t9.Api(api_url)
    journal = t9.Journal(journal_path, manifest_sha, manifest["descriptorSha256"])
    videos = t9.check_fresh(api, journal)
    camera_ids = t9.ensure_cameras(api, journal, cameras)
    command = list(export_command)
    runs = {}
    for row in sequences:
        sequence, code = row["sequenceId"], camera_code(row["sequenceId"])
        entry = {"cameraCode": code, "recordingStartLocal": RECORDING_START_LOCAL}
        video = Path(derived) / "sequences" / sequence / preparation.VIDEO
        derivation = {"video": video, "videoSha256": row["derivedVideoSha256"]}
        asset = t9.ensure_asset(api, journal, sequence, entry, (camera_ids[code], CAMERA_ZONE), derivation, videos)
        run = t9.ensure_run(api, journal, sequence, asset, poll_seconds, timeout_seconds)
        runs[sequence] = (asset, run, t9.ensure_export(run, profile_path, export_root, command))

    exports = artefacts.load_exports([path for _, _, path in runs.values()])
    by_run = {export.run_id: (sha, export) for sha, export in exports.items()}
    t9.producer(exports, profile_sha)  # one attested producer, which measured exactly this profile
    rows = []
    for row in sequences:
        sequence = row["sequenceId"]
        asset, run, _ = runs[sequence]
        require(run in by_run, f"benchmark_run_substituted:{sequence}")
        export_sha, export = by_run[run]
        require(export.document["processingRun"]["status"] == "Completed", f"benchmark_run_failed:{sequence}")
        require(export.video["videoAssetId"] == asset and export.video["sourceSha256"] == row["derivedVideoSha256"]
                and export.video["cameraCode"] == camera_code(sequence), f"benchmark_export_mismatch:{sequence}")
        mavi_tracks.project(export, evidence_root)  # every sealed trajectory present with its attested hash
        rows.append({"sequenceId": sequence, "videoAssetId": asset, "processingRunId": run,
                     "exportSha256": export_sha})
    return rows
