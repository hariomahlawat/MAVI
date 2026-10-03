"""The production evidence policy, loaded from the repository pipeline profile.

Tests that build a ``PipelineProfile`` by hand use this instead of restating the
evidence section, so they always exercise the profile the worker ships.
"""

from __future__ import annotations

import json
from pathlib import Path

from mavi_vision.runtime.profile import load_pipeline_profile

PIPELINE_PROFILE_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "pipelines"
    / "phase1-detection-tracking-v1.json"
)
PRODUCTION_EVIDENCE_POLICY = load_pipeline_profile(PIPELINE_PROFILE_PATH).evidence
# The evidence section exactly as the shipped profile JSON spells it.
PRODUCTION_EVIDENCE_SECTION = json.loads(
    PIPELINE_PROFILE_PATH.read_text(encoding="utf-8")
)["evidence"]


# The vehicleSubclass block of a schema-1.2 pipeline profile (ADR-016), as committed.
VEHICLE_SUBCLASS_SECTION = {
    "vocabularyId": "mavi-vehicle-subclass-v1",
    "mapping": {"car": "car", "motorcycle": "motorcycle", "bus": "bus", "truck": "truck"},
    "minShare": 0.6,
    "minMatchedDetections": 3,
}
