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
