"""MAVI's Track outcome, reused exactly from the S3.2 measurement (plan §4 reuse decisions).

The outcome of a Vehicle Track is its stored ``objectSubclass`` (one of the v1 values) or ``undetermined`` when the
detector-native vote abstained (``minShare`` 0.6, ``minMatchedDetections`` 3, applied by the vision worker when the
Track was finalised). ``evaluate_vehicle_subclass._track_outcome`` reads it with the same provenance checks as T2:
vocabulary ``mavi-vehicle-subclass-v1`` and source ``detector-native:<pipelineProfileSha256>`` of the single attested
producer. Nothing here votes again; the subject dict is built exactly as T2 builds it.
"""

from __future__ import annotations

from typing import Any

from tools.benchmarks.core._stage3 import artefacts
from tools.benchmarks.core.identity import S32Error

import evaluate_vehicle_subclass as evaluator  # noqa: E402  (tools/phase1, on the path via _stage3)

UNDETERMINED = evaluator.UNDETERMINED
CLASSES = tuple(evaluator.VALUES_V1)
OUTCOMES = (*CLASSES, UNDETERMINED)


def subclass_source(exports: dict[str, artefacts.Export], measured_profile_sha256: str) -> str:
    """The single attested producer's subclass source (``detector-native:<profile>``)."""
    try:
        return evaluator._producer([export.attestation for export in exports.values()],
                                   measured_profile_sha256)["subclassSource"]
    except evaluator.SubclassEvaluationError as exc:
        raise S32Error(f"result_invalid:producer:{exc}") from exc


def track_outcomes(export: artefacts.Export, source: str) -> dict[str, str]:
    """Vehicle Track id -> outcome (a v1 value or ``undetermined``); Person Tracks are not this capability's."""
    runs = {export.run_id: export.attestation}
    outcomes: dict[str, str] = {}
    for track in export.tracks:
        subject = {**track, "processingRunId": export.run_id, "videoAssetId": export.video["videoAssetId"]}
        try:
            value = evaluator._track_outcome(subject, runs, source)
        except evaluator.SubclassEvaluationError as exc:
            raise S32Error(f"result_invalid:track_outcome:{exc}:{track['id']}") from exc
        if value is not None:
            outcomes[track["id"]] = value
    return outcomes
