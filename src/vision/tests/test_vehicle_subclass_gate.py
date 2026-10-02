"""Stage 3 Track-identity gate (ADR-016).

The detector-native vehicle subclass must not change anything a Track is made of.
``fixtures/vehicle-subclass-track-identity-gate-v1.json`` is the scenario's output
from ``main@68b5b48b`` (before Stage 3). The current code must reproduce every Track
field, every artefact and the evidence accounting exactly, with the subclass vote on
and off; only the subclass itself is added.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests import vehicle_subclass_gate as gate

GOLDEN = json.loads((Path(__file__).parent / "fixtures/vehicle-subclass-track-identity-gate-v1.json").read_text(encoding="utf-8"))


def _without_crop_bytes(summary: dict) -> dict:
    """The summary with every encoder-dependent value removed (crop size and digests)."""
    copy = json.loads(json.dumps(summary))
    for track in copy["tracks"]:
        for observation in track["observations"]:
            observation["crop"] = {"storageKey": observation["crop"]["storageKey"]}
    for counts in copy["evidenceAccounting"].values():
        counts[3:] = []
    return copy


@pytest.mark.parametrize("vehicle_subclass", [True, False])
def test_every_track_is_identical_to_the_pre_stage_3_output(tmp_path: Path, vehicle_subclass: bool) -> None:
    result = gate.run(tmp_path, vehicle_subclass=vehicle_subclass)
    summary = gate.summarize(result, tmp_path)

    # Geometry, offsets, counts, confidences, the trajectory artefact bytes, the evidence
    # selection (roles, ranks, frames, boxes, scores) and the accounting counts: always.
    assert _without_crop_bytes(summary) == _without_crop_bytes(GOLDEN["summary"])
    # The crop bytes too, wherever the encoder is the one the golden was made with.
    if gate.encoding_identity() == GOLDEN["encodingIdentity"]:
        assert summary == GOLDEN["summary"]


def test_the_vote_on_and_off_produce_the_same_tracks_and_bytes(tmp_path: Path) -> None:
    on = gate.run(tmp_path / "on", vehicle_subclass=True)
    off = gate.run(tmp_path / "off", vehicle_subclass=False)
    assert gate.summarize(on, tmp_path / "on") == gate.summarize(off, tmp_path / "off")


def test_only_the_subclass_is_added(tmp_path: Path) -> None:
    on = {track.track_id: track.object_subclass for track in gate.run(tmp_path / "on", vehicle_subclass=True).tracks}
    off = {track.track_id: track.object_subclass for track in gate.run(tmp_path / "off", vehicle_subclass=False).tracks}

    # The bus is always a bus; vehicle A is a car for 14 of 20 frames (share 0.71); vehicle C
    # alternates car and truck at equal confidence, an exact tie, so it abstains.
    assert on == {"person-000001": None, "vehicle-000001": "bus", "vehicle-000002": "car", "vehicle-000003": None}
    assert set(off.values()) == {None}
